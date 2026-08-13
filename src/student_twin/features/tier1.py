"""Tier-1 universal features.

Every feature here is either relative to the student's own trailing history or
z-scored within (context x cohort). None carries a unit that depends on a
platform, a grading scale, or a country. That is the whole point: these are the
features hypothesis H3 predicts will survive transfer.

All windows are strictly *trailing*  -  a feature at week t uses weeks <= t only.
Any lookahead here is a temporal leak that would silently inflate every result in
the project, so `tests/test_features.py` asserts it directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import FeatureConfig
from ..schema import BEHAVIOR_TYPES, CanonicalType, EventTable
from .provenance import REGISTRY, FeatureSpec

BEHAVIOR_COLS = [t.value for t in BEHAVIOR_TYPES]

_SPECS = [
    FeatureSpec(
        name="engagement_ratio",
        tier=1,
        description="Weekly activity relative to the student's own trailing median activity.",
        depends_on=tuple(BEHAVIOR_COLS),
        normalisation="divided by own trailing median (self-relative)",
        defined_from_week=1,
    ),
    FeatureSpec(
        name="engagement_slope",
        tier=1,
        description="OLS slope of log activity over the trailing window; direction of travel.",
        depends_on=tuple(BEHAVIOR_COLS),
        normalisation="slope of a log-transformed self-relative series",
        defined_from_week=2,
    ),
    FeatureSpec(
        name="engagement_volatility",
        tier=1,
        description="Std. dev. of log activity over the trailing window.",
        depends_on=tuple(BEHAVIOR_COLS),
        normalisation="dispersion of a log-transformed self-relative series",
        defined_from_week=2,
    ),
    FeatureSpec(
        name="activity_entropy",
        tier=1,
        description="Normalised Shannon entropy across activity types; breadth vs. narrowness.",
        depends_on=tuple(BEHAVIOR_COLS),
        normalisation="entropy divided by log(n_types); bounded [0,1]",
    ),
    FeatureSpec(
        name="inactive_streak",
        tier=1,
        description="Consecutive weeks with zero recorded activity, capped.",
        depends_on=tuple(BEHAVIOR_COLS),
        normalisation="counted in weeks then divided by cap; bounded [0,1]",
    ),
    FeatureSpec(
        name="submission_rate",
        tier=1,
        description="Fraction of assessment opportunities so far that the student submitted.",
        depends_on=(CanonicalType.SUBMISSION.value,),
        normalisation="rate over own opportunities, not cohort counts",
        defined_from_week=1,
    ),
    FeatureSpec(
        name="score_vs_own_baseline",
        tier=1,
        description="Latest score minus the student's own trailing mean score.",
        depends_on=(CanonicalType.SCORE.value,),
        normalisation="difference from own trailing mean, not the cohort mean",
        defined_from_week=1,
    ),
    FeatureSpec(
        name="post_setback_recovery",
        tier=1,
        description=(
            "Change in engagement in the week after a below-own-baseline score. "
            "Zero when no setback has occurred."
        ),
        depends_on=(CanonicalType.SCORE.value, *BEHAVIOR_COLS),
        normalisation="difference of self-relative engagement values",
        defined_from_week=2,
    ),
]

for _s in _SPECS:
    if _s.name not in REGISTRY:
        REGISTRY.register(_s)

TIER1_FEATURES: tuple[str, ...] = tuple(s.name for s in _SPECS)
_INACTIVE_CAP = 4.0


def _trailing_slope(x: np.ndarray) -> float:
    """OLS slope over an equally spaced window; 0.0 when underdetermined."""
    n = len(x)
    if n < 2 or np.allclose(x, x[0]):
        return 0.0
    t = np.arange(n, dtype=float)
    t -= t.mean()
    denom = float((t * t).sum())
    return float((t * (x - x.mean())).sum() / denom) if denom > 0 else 0.0


def build_tier1(
    events: EventTable,
    config: FeatureConfig | None = None,
    *,
    n_weeks: int | None = None,
) -> pd.DataFrame:
    """Build the tier-1 matrix, one row per (student, context, week).

    The grid is dense: a student with no events in week 5 still gets a week-5 row,
    because silence is an observation. Filling it in only at event weeks would
    make disengagement invisible to the model.
    """
    cfg = config or FeatureConfig()
    wide = events.weekly_pivot()
    if wide.empty:
        return pd.DataFrame(columns=["student_id", "context_id", "t", *TIER1_FEATURES])

    horizon = int(n_weeks if n_weeks is not None else wide["t"].max() + 1)
    keys = wide[["student_id", "context_id"]].drop_duplicates()
    grid = keys.merge(pd.DataFrame({"t": np.arange(horizon)}), how="cross")
    df = grid.merge(wide, on=["student_id", "context_id", "t"], how="left")

    present = [c for c in BEHAVIOR_COLS if c in df.columns]
    df[present] = df[present].fillna(0.0)
    for col in (CanonicalType.SUBMISSION.value,):
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    df = df.sort_values(["student_id", "context_id", "t"]).reset_index(drop=True)
    df["_activity"] = df[present].sum(axis=1)
    df["_log_activity"] = np.log1p(df["_activity"])

    g = df.groupby(["student_id", "context_id"], observed=True, sort=False)
    w, eps = cfg.baseline_window, cfg.epsilon

    # --- engagement relative to own trailing baseline -------------------
    # shift(1) so week t never sees its own value: this is the leak guard.
    trailing_median = g["_activity"].transform(
        lambda s: s.shift(1).rolling(w, min_periods=1).median()
    )
    df["engagement_ratio"] = np.where(
        trailing_median.isna(), np.nan, df["_activity"] / (trailing_median + 1.0)
    )

    df["engagement_slope"] = g["_log_activity"].transform(
        lambda s: s.rolling(cfg.trend_window, min_periods=2).apply(_trailing_slope, raw=True)
    )
    df["engagement_volatility"] = g["_log_activity"].transform(
        lambda s: s.rolling(cfg.trend_window, min_periods=2).std()
    )

    # --- breadth of activity --------------------------------------------
    counts = df[present].to_numpy(dtype=float)
    totals = counts.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(totals > 0, counts / np.maximum(totals, eps), 0.0)
        ent = -np.where(p > 0, p * np.log(p), 0.0).sum(axis=1)
    df["activity_entropy"] = np.where(
        totals.ravel() > 0, ent / max(np.log(max(len(present), 2)), eps), 0.0
    )

    # --- inactivity streak ----------------------------------------------
    def _streak(s: pd.Series) -> pd.Series:
        out, run = [], 0
        for v in s.to_numpy():
            run = run + 1 if v <= 0 else 0
            out.append(min(run, _INACTIVE_CAP))
        return pd.Series(out, index=s.index, dtype=float)

    df["inactive_streak"] = g["_activity"].transform(_streak) / _INACTIVE_CAP

    # --- assessment behaviour -------------------------------------------
    sub = df[CanonicalType.SUBMISSION.value] if CanonicalType.SUBMISSION.value in df else 0.0
    df["_sub"] = np.minimum(pd.Series(sub, index=df.index).fillna(0.0), 1.0)
    g2 = df.groupby(["student_id", "context_id"], observed=True, sort=False)
    df["_cum_sub"] = g2["_sub"].transform(lambda s: s.shift(1).fillna(0.0).cumsum())
    df["_opportunities"] = g2["_sub"].transform(lambda s: s.shift(1).notna().cumsum().clip(lower=0))
    df["submission_rate"] = np.where(
        df["t"] > 0, df["_cum_sub"] / np.maximum(df["t"], 1.0), np.nan
    )

    score_col = CanonicalType.SCORE.value
    if score_col in df.columns:
        s_ffill = g2[score_col].transform(lambda s: s.ffill())
        own_mean = g2[score_col].transform(
            lambda s: s.shift(1).expanding(min_periods=1).mean().ffill()
        )
        df["score_vs_own_baseline"] = s_ffill - own_mean
        setback = (df[score_col].notna() & (df[score_col] < own_mean)).astype(float)
    else:
        df["score_vs_own_baseline"] = np.nan
        setback = pd.Series(0.0, index=df.index)

    df["_setback"] = np.asarray(setback, dtype=float)
    df["_setback_prev"] = (
        df.groupby(["student_id", "context_id"], observed=True, sort=False)["_setback"]
        .shift(1)
        .fillna(0.0)
    )
    delta_eng = g2["engagement_ratio"].transform(lambda s: s.diff())
    df["post_setback_recovery"] = np.where(df["_setback_prev"] > 0, delta_eng.fillna(0.0), 0.0)

    out_cols = ["student_id", "context_id", "t", *TIER1_FEATURES]
    out = df[out_cols].copy()
    # Early weeks legitimately have undefined self-relative features. Zero is the
    # neutral value here because every tier-1 feature is centred on "same as usual".
    for c in TIER1_FEATURES:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out[list(TIER1_FEATURES)] = out[list(TIER1_FEATURES)].fillna(0.0)
    out["engagement_ratio"] = out["engagement_ratio"].clip(0.0, 5.0)
    return out.reset_index(drop=True)


def observation_frame(events: EventTable, n_weeks: int | None = None) -> pd.DataFrame:
    """Raw weekly observations the state filter consumes.

    Distinct from the feature matrix: the filter needs counts and the submission
    indicator on their natural scales, because its emission models are count and
    Bernoulli likelihoods. Features are for baselines and explanation.
    """
    wide = events.weekly_pivot()
    if wide.empty:
        return wide
    horizon = int(n_weeks if n_weeks is not None else wide["t"].max() + 1)
    keys = wide[["student_id", "context_id"]].drop_duplicates()
    grid = keys.merge(pd.DataFrame({"t": np.arange(horizon)}), how="cross")
    df = grid.merge(wide, on=["student_id", "context_id", "t"], how="left")
    for c in BEHAVIOR_COLS:
        if c in df.columns:
            df[c] = df[c].fillna(0.0)
    if CanonicalType.SUBMISSION.value in df.columns:
        df[CanonicalType.SUBMISSION.value] = (
            df[CanonicalType.SUBMISSION.value].fillna(0.0).clip(0, 1)
        )
    # score stays NaN where absent  -  not submitting is not a zero score
    return df.sort_values(["student_id", "context_id", "t"]).reset_index(drop=True)
