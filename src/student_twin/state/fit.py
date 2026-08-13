"""Parameter estimation.

PROTOTYPE SIMPLIFICATION (docs/assumptions.md A-03). Gate 1 specifies joint
estimation of states and parameters. This module fits them in two stages instead:

  Stage 1  build observable proxies for each latent dimension
  Stage 2  fit emission parameters by GLM against those proxies
  Stage 3  fit transition parameters (alpha, Q, B) and per-student set points
  Stage 4  hand off to the filter, which re-estimates the states properly

The consequence is honest and specific: emission loadings are conditioned on a
noisy proxy rather than on the posterior state, so they are attenuated toward
zero (classical errors-in-variables). Full EM  -  iterate stages 2-4 to convergence
 -  is Phase 1 work and needs no interface change; `fit_twin(n_em_iters=...)`
already threads it, with 0 meaning two-stage only.

Identifiability is imposed by structure, not by regularisation:
    behaviour counts load on engagement only
    score loads on capability only
    submission loads on both
Without that, the two dimensions are exchangeable and test T4 cannot pass.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression, PoissonRegressor

from ..config import Config, StateConfig
from ..schema import BEHAVIOR_TYPES, AdapterOutput, CanonicalType
from ..features.context import TRANSITION_COVARIATES
from .model import TwinParameters

BEHAVIOR_COLS = [t.value for t in BEHAVIOR_TYPES]
_EPS = 1e-9


def _zscore_within(df: pd.DataFrame, col: str, by: str) -> pd.Series:
    g = df.groupby(by, observed=True)[col]
    mu, sd = g.transform("mean"), g.transform("std")
    return (df[col] - mu) / sd.replace(0.0, np.nan).fillna(1.0)


def build_proxies(obs: pd.DataFrame) -> pd.DataFrame:
    """Stage 1  -  observable stand-ins for the latent dimensions.

    These are NOT the latent state. They initialise the fit and are discarded
    afterwards; the filter produces the actual state estimates.
    """
    df = obs.copy()
    present = [c for c in BEHAVIOR_COLS if c in df.columns]
    df["_activity"] = df[present].sum(axis=1) if present else 0.0
    df["_log_activity"] = np.log1p(df["_activity"])
    df["proxy_engagement"] = _zscore_within(df, "_log_activity", "context_id").fillna(0.0)

    if CanonicalType.SCORE.value in df.columns:
        s = df[CanonicalType.SCORE.value].clip(1e-4, 1 - 1e-4)
        df["_logit_score"] = np.log(s / (1 - s))
        df["_logit_score"] = (
            df.sort_values(["student_id", "t"])
            .groupby(["student_id", "context_id"], observed=True)["_logit_score"]
            .ffill()
            .reindex(df.index)
        )
        df["proxy_capability"] = _zscore_within(df, "_logit_score", "context_id").fillna(0.0)
    else:
        df["proxy_capability"] = 0.0
    return df


def _fit_count_channel(y: np.ndarray, x: np.ndarray, d: int) -> tuple[float, np.ndarray, float]:
    """Poisson GLM for the mean, method-of-moments for the dispersion."""
    loading = np.zeros(d)
    if len(y) < 10 or np.all(y == y[0]):
        return float(np.log(max(y.mean(), 0.1))), loading, 4.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        glm = PoissonRegressor(alpha=1e-6, max_iter=500).fit(x.reshape(-1, 1), y)
    loading[0] = float(glm.coef_[0])
    intercept = float(glm.intercept_)
    mu = np.exp(np.clip(intercept + loading[0] * x, -12, 12))
    var = float(np.mean((y - mu) ** 2))
    mbar = float(np.mean(mu))
    # NegBin: var = mu + mu^2/phi  =>  phi = mu^2 / (var - mu)
    phi = (mbar**2) / max(var - mbar, 1e-3) if var > mbar * 1.05 else 50.0
    return intercept, loading, float(np.clip(phi, 0.25, 200.0))


def fit_twin(
    data: AdapterOutput,
    obs: pd.DataFrame,
    context_frame: pd.DataFrame | None = None,
    config: Config | None = None,
    *,
    n_em_iters: int = 0,
) -> TwinParameters:
    """Fit the state-space model. Returns parameters; states come from the filter."""
    cfg = config or Config()
    scfg: StateConfig = cfg.state
    d = scfg.n_dims

    df = build_proxies(obs)
    pe = df["proxy_engagement"].to_numpy(dtype=float)
    pm = df["proxy_capability"].to_numpy(dtype=float)

    # --- Stage 2: emissions ---------------------------------------------
    count_params: dict[str, tuple[float, np.ndarray, float]] = {}
    for col in BEHAVIOR_COLS:
        if col not in df.columns:
            continue
        y = df[col].fillna(0.0).to_numpy(dtype=float)
        count_params[col] = _fit_count_channel(y, pe, d)

    submit_params = None
    sub_col = CanonicalType.SUBMISSION.value
    if sub_col in df.columns:
        ysub = (df[sub_col].fillna(0.0).to_numpy(dtype=float) > 0).astype(int)
        if 0 < ysub.sum() < len(ysub):
            X = np.column_stack([pe, pm])[:, :d]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lr = LogisticRegression(max_iter=1000, C=1e3).fit(X, ysub)
            w = np.zeros(d)
            w[: X.shape[1]] = lr.coef_[0]
            submit_params = (float(lr.intercept_[0]), w)

    score_params = None
    sc_col = CanonicalType.SCORE.value
    if sc_col in df.columns and df[sc_col].notna().any():
        mask = df[sc_col].notna().to_numpy()
        s = df.loc[mask, sc_col].clip(1e-4, 1 - 1e-4).to_numpy(dtype=float)
        y_logit = np.log(s / (1 - s))
        if d >= 2 and mask.sum() >= 10:
            xm = pm[mask].reshape(-1, 1)
            reg = LinearRegression().fit(xm, y_logit)
            w = np.zeros(d)
            w[1] = float(reg.coef_[0])
            resid = y_logit - reg.predict(xm)
            score_params = (float(reg.intercept_), w, float(max(resid.std(), 0.1)))

    # --- Stage 3: set points, transition --------------------------------
    proxy_cols = ["proxy_engagement", "proxy_capability"][:d]
    per_student = (
        df.groupby(["student_id", "context_id"], observed=True)[proxy_cols].mean().reset_index()
    )
    context_means = {
        str(cid): grp[proxy_cols].mean().to_numpy(dtype=float)
        for cid, grp in per_student.groupby("context_id", observed=True)
    }
    mu0 = per_student[proxy_cols].mean().to_numpy(dtype=float)

    setpoints = {
        str(r["student_id"]): r[proxy_cols].to_numpy(dtype=float)
        for _, r in per_student.iterrows()
    }

    # alpha and Q from the proxy dynamics: regress (z_{t+1} - z_t) on (theta - z_t)
    ordered = df.sort_values(["student_id", "context_id", "t"])
    alpha = np.array(scfg.alpha_init[:d], dtype=float)
    Q = np.diag(np.array(scfg.process_noise_init[:d], dtype=float))
    for j, col in enumerate(proxy_cols):
        z = ordered[col].to_numpy(dtype=float)
        sid = ordered["student_id"].to_numpy()
        theta_vec = np.array([setpoints[str(s)][j] for s in sid])
        same = sid[:-1] == sid[1:]
        dz = (z[1:] - z[:-1])[same]
        gap = (theta_vec[:-1] - z[:-1])[same]
        if len(dz) > 20 and np.std(gap) > _EPS:
            a = float(np.clip(np.dot(gap, dz) / max(np.dot(gap, gap), _EPS), 0.01, 0.95))
            resid = dz - a * gap
            alpha[j] = a
            Q[j, j] = float(max(np.var(resid), 1e-3))

    ctx_names = tuple(c for c in TRANSITION_COVARIATES
                      if context_frame is not None and c in context_frame.columns)
    B = np.zeros((d, len(ctx_names)))
    if ctx_names:
        merged = ordered.merge(
            context_frame[["context_id", "t", *ctx_names]], on=["context_id", "t"], how="left"
        )
        U = merged[list(ctx_names)].fillna(0.0).to_numpy(dtype=float)
        sid = merged["student_id"].to_numpy()
        same = sid[:-1] == sid[1:]
        for j, col in enumerate(proxy_cols):
            z = merged[col].to_numpy(dtype=float)
            theta_vec = np.array([setpoints[str(s)][j] for s in sid])
            dz = (z[1:] - z[:-1])[same]
            gap = (theta_vec[:-1] - z[:-1])[same]
            resid = dz - alpha[j] * gap
            Uu = U[:-1][same]
            if len(resid) > 20 and np.linalg.matrix_rank(Uu) == Uu.shape[1]:
                B[j] = LinearRegression(fit_intercept=False).fit(Uu, resid).coef_

    # --- intervention matrix --------------------------------------------
    # C is NOT estimated. OULAD records no interventions, so there is nothing to
    # estimate it from. These are declared simulation sensitivities; see
    # simulation/intervention.py and docs/assumptions.md A-08.
    from ..simulation.intervention import INTERVENTION_NAMES, default_C

    C = default_C(d)

    params = TwinParameters(
        n_dims=d,
        dim_names=tuple(scfg.dim_names[:d]),
        alpha=alpha,
        Q=Q,
        B=B,
        C=C,
        context_covariates=ctx_names,
        intervention_names=INTERVENTION_NAMES,
        count_params=count_params,
        submit_params=submit_params,
        score_params=score_params,
        mu0=mu0,
        P0=np.eye(d) * scfg.initial_state_variance,
        setpoint_shrinkage=scfg.setpoint_shrinkage,
        context_means=context_means,
        fitted_on=data.coverage.dataset,
        synthetic=(data.coverage.dataset == "synthetic"),
    )
    params.student_setpoints = setpoints  # type: ignore[attr-defined]

    if n_em_iters:
        params = _em_refine(params, obs, context_frame, cfg, n_iters=n_em_iters)
    return params


# --------------------------------------------------------------------------
# EM refinement
# --------------------------------------------------------------------------

def _fit_phi_mle(y: np.ndarray, mu: np.ndarray) -> float:
    """Maximum-likelihood negative-binomial dispersion, given fitted means.

    Replaces the method-of-moments estimate, which is badly biased when the mean
    is itself estimated from a noisy proxy.
    """
    from scipy.optimize import minimize_scalar
    from scipy.special import gammaln

    y = np.asarray(y, dtype=float)
    mu = np.clip(np.asarray(mu, dtype=float), 1e-6, None)

    def nll(log_phi: float) -> float:
        phi = float(np.exp(log_phi))
        return -float(np.sum(
            gammaln(y + phi) - gammaln(phi) - gammaln(y + 1.0)
            + phi * (np.log(phi) - np.log(phi + mu))
            + y * (np.log(mu) - np.log(phi + mu))
        ))

    try:
        res = minimize_scalar(nll, bounds=(np.log(0.25), np.log(200.0)), method="bounded")
        return float(np.clip(np.exp(res.x), 0.25, 200.0))
    except Exception:
        return 4.0


def _em_refine(
    params: TwinParameters,
    obs: pd.DataFrame,
    context_frame: pd.DataFrame | None,
    cfg: Config,
    *,
    n_iters: int,
    tol: float = 1e-3,
) -> TwinParameters:
    """Iterate filter/smooth -> refit, starting from the two-stage estimate.

    The two-stage fit is a good initialiser and a poor final answer: it regresses
    against observable proxies, so proxy measurement noise is absorbed into the
    transition as if it were process noise. That inflates both alpha (apparent
    over-reversion) and Q. Refitting against SMOOTHED states removes that path.
    """
    from .filter import TwinFilter

    d = params.n_dims
    setpoints = dict(getattr(params, "student_setpoints", {}))

    for it in range(n_iters):
        prev_alpha = params.alpha.copy()

        # --- E step: filter then smooth every student ----------------------
        filt = TwinFilter(params, cfg.state)
        trajs = filt.filter_all(obs, context_frame, setpoints=setpoints)

        rows: list[pd.DataFrame] = []
        for sid, traj in trajs.items():
            if len(traj) < 2:
                continue
            m_s, _, _ = filt.smooth(traj)
            rec = pd.DataFrame(m_s, columns=[f"s_{n}" for n in params.dim_names])
            rec["student_id"] = sid
            rec["context_id"] = traj.context_id
            rec["t"] = [s.t for s in traj.states]
            rows.append(rec)
        if not rows:
            break
        smooth_df = pd.concat(rows, ignore_index=True)

        merged = obs.merge(smooth_df, on=["student_id", "context_id", "t"], how="inner")
        if merged.empty:
            break
        S = merged[[f"s_{n}" for n in params.dim_names]].to_numpy(dtype=float)

        # --- M step: emissions against smoothed states ---------------------
        new_counts: dict[str, tuple[float, np.ndarray, float]] = {}
        for col in BEHAVIOR_COLS:
            if col not in merged.columns:
                continue
            y = merged[col].fillna(0.0).to_numpy(dtype=float)
            if len(y) < 10 or np.all(y == y[0]):
                new_counts[col] = params.count_params.get(
                    col, (float(np.log(max(y.mean(), 0.1))), np.zeros(d), 4.0)
                )
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                glm = PoissonRegressor(alpha=1e-6, max_iter=500).fit(S[:, [0]], y)
            load = np.zeros(d)
            load[0] = float(glm.coef_[0])
            b0 = float(glm.intercept_)
            mu = np.exp(np.clip(b0 + S[:, 0] * load[0], -12, 12))
            new_counts[col] = (b0, load, _fit_phi_mle(y, mu))
        params.count_params = new_counts

        sub_col = CanonicalType.SUBMISSION.value
        if sub_col in merged.columns:
            ysub = (merged[sub_col].fillna(0.0).to_numpy(dtype=float) > 0).astype(int)
            if 0 < ysub.sum() < len(ysub):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    lr = LogisticRegression(max_iter=1000, C=1e3).fit(S, ysub)
                params.submit_params = (float(lr.intercept_[0]), lr.coef_[0].copy())

        sc_col = CanonicalType.SCORE.value
        if sc_col in merged.columns and merged[sc_col].notna().any() and d >= 2:
            mask = merged[sc_col].notna().to_numpy()
            if mask.sum() >= 10:
                s = merged.loc[mask, sc_col].clip(1e-4, 1 - 1e-4).to_numpy(dtype=float)
                y_logit = np.log(s / (1 - s))
                reg = LinearRegression().fit(S[mask][:, [1]], y_logit)
                w = np.zeros(d)
                w[1] = float(reg.coef_[0])
                resid = y_logit - reg.predict(S[mask][:, [1]])
                params.score_params = (
                    float(reg.intercept_), w, float(max(resid.std(), 0.05))
                )

        # --- M step: set points and transition -----------------------------
        scols = [f"s_{n}" for n in params.dim_names]
        per_student = (
            smooth_df.groupby(["student_id", "context_id"], observed=True)[scols]
            .mean().reset_index()
        )
        setpoints = {
            str(r["student_id"]): r[scols].to_numpy(dtype=float)
            for _, r in per_student.iterrows()
        }
        params.context_means = {
            str(cid): grp[scols].mean().to_numpy(dtype=float)
            for cid, grp in per_student.groupby("context_id", observed=True)
        }

        ordered = smooth_df.sort_values(["student_id", "t"])
        sid_arr = ordered["student_id"].to_numpy()
        same = sid_arr[:-1] == sid_arr[1:]
        alpha = params.alpha.copy()
        Q = params.Q.copy()
        for j, col in enumerate(scols):
            z = ordered[col].to_numpy(dtype=float)
            th = np.array([setpoints[str(s)][j] for s in sid_arr])
            dz = (z[1:] - z[:-1])[same]
            gap = (th[:-1] - z[:-1])[same]
            if len(dz) > 20 and np.dot(gap, gap) > _EPS:
                a = float(np.clip(np.dot(gap, dz) / np.dot(gap, gap), 0.01, 0.95))
                alpha[j] = a
                Q[j, j] = float(max(np.var(dz - a * gap), 1e-4))
        params.alpha = alpha
        params.Q = Q

        if float(np.max(np.abs(alpha - prev_alpha))) < tol:
            break

    params.student_setpoints = setpoints  # type: ignore[attr-defined]
    params.em_iterations = it + 1  # type: ignore[attr-defined]
    return params
