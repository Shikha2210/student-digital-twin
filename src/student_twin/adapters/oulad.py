"""OULAD adapter.

Maps the Open University Learning Analytics Dataset (Kuzilek, Hlosta & Zdrahal,
Scientific Data 2017) into the canonical schema.

Status: written against the published OULAD table layout but **not yet executed
against real data**, because the CSVs are not present in this environment. Every
column reference below is taken from the dataset documentation. The adapter is
covered by a structural test using a miniature fixture with the real column
names; it has not been validated against the full 10.6M-row clickstream.

Institution-specific fields (`imd_band`, `region`, `highest_education`,
`code_module` identity, raw `id_site`, `num_of_prev_attempts`) are deliberately
NOT emitted as events. Gate 1 §03 places them in tier 3, excluded from the twin.
They are retained in `tier3_frame()` so the transfer experiments can later
measure what including them costs  -  which is hypothesis H3.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import (
    CHANNEL_OF,
    AdapterOutput,
    CanonicalType,
    ContextMetadata,
    CoverageManifest,
    EventTable,
    OutcomeTable,
)
from . import DatasetAdapter, RawDataMissing

REQUIRED_FILES = [
    "studentInfo.csv",
    "studentRegistration.csv",
    "studentAssessment.csv",
    "assessments.csv",
    "courses.csv",
    "studentVle.csv",
    "vle.csv",
]

#: OULAD `activity_type` -> canonical behaviour type.
#: Types absent from this map fall back to RESOURCE, which is recorded in the run
#: manifest so the fallback is visible rather than silent.
ACTIVITY_MAP: dict[str, CanonicalType] = {
    "forumng": CanonicalType.FORUM,
    "ouwiki": CanonicalType.FORUM,
    "oucollaborate": CanonicalType.FORUM,
    "quiz": CanonicalType.QUIZ_ATTEMPT,
    "questionnaire": CanonicalType.QUIZ_ATTEMPT,
    "oucontent": CanonicalType.CONTENT_VIEW,
    "subpage": CanonicalType.CONTENT_VIEW,
    "page": CanonicalType.CONTENT_VIEW,
    "homepage": CanonicalType.CONTENT_VIEW,
    "resource": CanonicalType.RESOURCE,
    "url": CanonicalType.RESOURCE,
    "glossary": CanonicalType.RESOURCE,
    "externalquiz": CanonicalType.QUIZ_ATTEMPT,
    "dataplus": CanonicalType.RESOURCE,
    "folder": CanonicalType.RESOURCE,
    "htmlactivity": CanonicalType.CONTENT_VIEW,
    "sharedsubpage": CanonicalType.CONTENT_VIEW,
    "repeatactivity": CanonicalType.CONTENT_VIEW,
    "dualpane": CanonicalType.CONTENT_VIEW,
}

# OULAD modules AAA, BBB, GGG are Social Science; CCC, DDD, EEE, FFF are STEM.
# Verified against the dataset documentation.
DISCIPLINE: dict[str, str] = {
    "AAA": "social_science",
    "BBB": "social_science",
    "GGG": "social_science",
    "CCC": "stem",
    "DDD": "stem",
    "EEE": "stem",
    "FFF": "stem",
}

DAYS_PER_WEEK = 7


class OULADAdapter(DatasetAdapter):
    name = "oulad"

    def __init__(self, root: str | Path = "data/raw/oulad") -> None:
        self.root = Path(root)

    # -- contract --------------------------------------------------------

    def is_available(self) -> bool:
        return all((self.root / f).exists() for f in REQUIRED_FILES)

    def coverage(self) -> CoverageManifest:
        available = {
            CanonicalType.CONTENT_VIEW.value,
            CanonicalType.FORUM.value,
            CanonicalType.QUIZ_ATTEMPT.value,
            CanonicalType.RESOURCE.value,
            CanonicalType.SUBMISSION.value,
            CanonicalType.SCORE.value,
            CanonicalType.REGISTER.value,
            CanonicalType.WITHDRAW.value,
        }
        unavailable = {t.value for t in CanonicalType} - available
        return CoverageManifest(
            dataset=self.name,
            available=frozenset(available),
            unavailable=frozenset(unavailable),
            notes={
                "admin": "OULAD has no separable administrative-action channel.",
                "activity_log": (
                    "No lifestyle data. Would require a separate instrument; see "
                    "docs/assumptions.md A-07."
                ),
                "perceived_load": (
                    "No self-reported cognitive or affective data. OULAD is trace-only."
                ),
                "granularity": (
                    "Clickstream is daily-aggregated counts per activity type, not "
                    "per-interaction. Per-question knowledge tracing is NOT supported."
                ),
                "vintage": "2013-2014 presentations. Interaction norms have since shifted.",
                "modality": "100% distance learning. Clicks capture ~all study behaviour, "
                            "which is not true in residential settings.",
            },
        )

    # -- loading ---------------------------------------------------------

    def load(self, *, max_students_per_context: int | None = None) -> AdapterOutput:
        if not self.is_available():
            raise RawDataMissing(self.name, self.root, REQUIRED_FILES)

        info = pd.read_csv(self.root / "studentInfo.csv")
        reg = pd.read_csv(self.root / "studentRegistration.csv")
        courses = pd.read_csv(self.root / "courses.csv")
        assess = pd.read_csv(self.root / "assessments.csv")
        st_assess = pd.read_csv(self.root / "studentAssessment.csv")
        vle_meta = pd.read_csv(self.root / "vle.csv")

        info["context_id"] = info["code_module"] + "_" + info["code_presentation"]
        info["student_id"] = info["id_student"].astype(str)

        if max_students_per_context is not None:
            keep = (
                info.sort_values(["context_id", "student_id"])
                .groupby("context_id", observed=True)
                .head(max_students_per_context)
            )
            info = keep
        keep_ids = set(info["student_id"])

        contexts = self._build_contexts(info, courses, assess)
        outcomes = self._build_outcomes(info, reg)
        events = self._build_events(info, reg, assess, st_assess, vle_meta, keep_ids)

        # observed base rate is measured, never asserted
        rates = (
            outcomes.df.groupby("context_id", observed=True)["event_observed"].mean().to_dict()
        )
        contexts = {
            cid: ContextMetadata(**{**vars(meta), "observed_base_rate": rates.get(cid, float("nan"))})
            for cid, meta in contexts.items()
        }

        return AdapterOutput(
            events=events, contexts=contexts, outcomes=outcomes, coverage=self.coverage()
        )

    # -- pieces ----------------------------------------------------------

    def _build_contexts(
        self, info: pd.DataFrame, courses: pd.DataFrame, assess: pd.DataFrame
    ) -> dict[str, ContextMetadata]:
        courses = courses.copy()
        courses["context_id"] = courses["code_module"] + "_" + courses["code_presentation"]
        assess = assess.copy()
        assess["context_id"] = assess["code_module"] + "_" + assess["code_presentation"]

        n_assess = assess.groupby("context_id", observed=True).size()
        has_exam = (
            assess.assign(is_exam=assess["assessment_type"].eq("Exam"))
            .groupby("context_id", observed=True)["is_exam"]
            .any()
        )
        sizes = info.groupby("context_id", observed=True).size()
        credits = info.groupby("context_id", observed=True)["studied_credits"].mean()

        out: dict[str, ContextMetadata] = {}
        for _, row in courses.iterrows():
            cid = row["context_id"]
            if cid not in sizes.index:
                continue
            weeks = max(1, int(np.ceil(row["module_presentation_length"] / DAYS_PER_WEEK)))
            out[cid] = ContextMetadata(
                context_id=cid,
                n_weeks=weeks,
                modality="distance",
                discipline=DISCIPLINE.get(row["code_module"], "other"),
                cohort_size=int(sizes.get(cid, 0)),
                assessment_density=float(n_assess.get(cid, 0)) / weeks,
                has_high_stakes_exam=bool(has_exam.get(cid, False)),
                mean_credit_load=float(credits.get(cid, np.nan)),
                source_dataset=self.name,
            )
        return out

    def _build_outcomes(self, info: pd.DataFrame, reg: pd.DataFrame) -> OutcomeTable:
        reg = reg.copy()
        reg["context_id"] = reg["code_module"] + "_" + reg["code_presentation"]
        reg["student_id"] = reg["id_student"].astype(str)
        merged = info.merge(
            reg[["student_id", "context_id", "date_unregistration"]],
            on=["student_id", "context_id"],
            how="left",
        )
        withdrawn = merged["final_result"].eq("Withdrawn")
        # date_unregistration is days from module start; convert to a week index.
        week = np.floor(merged["date_unregistration"] / DAYS_PER_WEEK)
        merged["event_week"] = np.where(withdrawn, week, np.nan)
        merged["event_observed"] = withdrawn.astype(bool)
        return OutcomeTable(
            merged[["student_id", "context_id", "event_week", "event_observed", "final_result"]]
            .reset_index(drop=True)
        )

    def _build_events(
        self,
        info: pd.DataFrame,
        reg: pd.DataFrame,
        assess: pd.DataFrame,
        st_assess: pd.DataFrame,
        vle_meta: pd.DataFrame,
        keep_ids: set[str],
    ) -> EventTable:
        frames: list[pd.DataFrame] = []
        ctx_of = info.set_index("student_id")["context_id"].to_dict()

        # --- behaviour: streamed, because studentVle is the large table -----
        site_type = vle_meta.set_index("id_site")["activity_type"].to_dict()
        unmapped: set[str] = set()
        chunks: list[pd.DataFrame] = []
        for chunk in pd.read_csv(self.root / "studentVle.csv", chunksize=1_000_000):
            chunk["student_id"] = chunk["id_student"].astype(str)
            chunk = chunk[chunk["student_id"].isin(keep_ids)]
            if chunk.empty:
                continue
            chunk["context_id"] = chunk["code_module"] + "_" + chunk["code_presentation"]
            act = chunk["id_site"].map(site_type).fillna("resource")
            unmapped |= set(act.unique()) - set(ACTIVITY_MAP)
            chunk["canonical_type"] = (
                act.map(lambda a: ACTIVITY_MAP.get(a, CanonicalType.RESOURCE).value)
            )
            chunk["t"] = np.floor(chunk["date"] / DAYS_PER_WEEK).astype("int64")
            chunk = chunk[chunk["t"] >= 0]
            grouped = (
                chunk.groupby(
                    ["student_id", "context_id", "t", "canonical_type"], observed=True
                )["sum_click"]
                .sum()
                .reset_index()
                .rename(columns={"sum_click": "value"})
            )
            chunks.append(grouped)
        if chunks:
            beh = pd.concat(chunks, ignore_index=True)
            beh = (
                beh.groupby(["student_id", "context_id", "t", "canonical_type"], observed=True)[
                    "value"
                ]
                .sum()
                .reset_index()
            )
            beh["channel"] = "behavior"
            frames.append(beh)
        self.unmapped_activity_types = sorted(unmapped)

        # --- assessment: submission indicator + score -----------------------
        assess = assess.copy()
        assess["context_id"] = assess["code_module"] + "_" + assess["code_presentation"]
        sa = st_assess.merge(
            assess[["id_assessment", "context_id", "date", "weight"]], on="id_assessment", how="left"
        )
        sa["student_id"] = sa["id_student"].astype(str)
        sa = sa[sa["student_id"].isin(keep_ids)]
        if not sa.empty:
            sa["t"] = np.floor(sa["date_submitted"] / DAYS_PER_WEEK).astype("int64")
            sa = sa[sa["t"] >= 0]
            sub = sa.assign(
                canonical_type=CanonicalType.SUBMISSION.value, channel="assessment", value=1.0
            )[["student_id", "context_id", "t", "canonical_type", "channel", "value"]]
            frames.append(sub)
            sc = sa.dropna(subset=["score"]).assign(
                canonical_type=CanonicalType.SCORE.value,
                channel="assessment",
                value=lambda d: d["score"] / 100.0,
            )[["student_id", "context_id", "t", "canonical_type", "channel", "value"]]
            frames.append(sc)

        # --- enrolment ------------------------------------------------------
        reg = reg.copy()
        reg["student_id"] = reg["id_student"].astype(str)
        reg = reg[reg["student_id"].isin(keep_ids)]
        reg["context_id"] = reg["code_module"] + "_" + reg["code_presentation"]
        regs = reg.assign(
            t=0, canonical_type=CanonicalType.REGISTER.value, channel="enrolment", value=1.0
        )[["student_id", "context_id", "t", "canonical_type", "channel", "value"]]
        frames.append(regs)

        wd = reg.dropna(subset=["date_unregistration"]).copy()
        if not wd.empty:
            wd["t"] = np.floor(wd["date_unregistration"] / DAYS_PER_WEEK).astype("int64")
            wd = wd[wd["t"] >= 0]
            frames.append(
                wd.assign(
                    canonical_type=CanonicalType.WITHDRAW.value, channel="enrolment", value=1.0
                )[["student_id", "context_id", "t", "canonical_type", "channel", "value"]]
            )

        allev = pd.concat(frames, ignore_index=True)
        allev = allev[allev["student_id"].map(ctx_of).notna()]
        return EventTable(allev)

    # -- tier 3, kept out of the twin ------------------------------------

    def tier3_frame(self) -> pd.DataFrame:
        """Institution-specific attributes, for H3 measurement only.

        Never joined into the feature matrix used by the state model.
        """
        if not self.is_available():
            raise RawDataMissing(self.name, self.root, REQUIRED_FILES)
        info = pd.read_csv(self.root / "studentInfo.csv")
        info["student_id"] = info["id_student"].astype(str)
        info["context_id"] = info["code_module"] + "_" + info["code_presentation"]
        cols = [
            "student_id", "context_id", "imd_band", "region", "highest_education",
            "code_module", "num_of_prev_attempts", "age_band", "gender", "disability",
        ]
        return info[[c for c in cols if c in info.columns]].copy()
