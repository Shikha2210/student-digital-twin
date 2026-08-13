"""Feature provenance.

Answers "where did this feature come from?" for any column in the matrix. This is
not documentation for its own sake: hypothesis H3 requires partitioning features
by tier, and a transfer experiment that cannot state which canonical types a
feature depends on cannot be channel-controlled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schema import CanonicalType


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    tier: int                       # 1 = universal, 2 = context, 3 = institution
    description: str
    depends_on: tuple[str, ...]     # canonical types consumed
    normalisation: str              # how it is made context-comparable
    defined_from_week: int = 0      # first week the value is meaningful

    def __post_init__(self) -> None:
        if self.tier not in (1, 2, 3):
            raise ValueError(f"tier must be 1, 2 or 3; got {self.tier}")
        known = {t.value for t in CanonicalType}
        unknown = set(self.depends_on) - known - {"context_metadata", "derived"}
        if unknown:
            raise ValueError(f"{self.name}: unknown canonical types {sorted(unknown)}")
        if self.tier == 1 and self.normalisation == "none":
            raise ValueError(
                f"{self.name}: a tier-1 feature must be self-relative or "
                "within-context normalised. Raw values are not portable."
            )


class FeatureRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, FeatureSpec] = {}

    def register(self, spec: FeatureSpec) -> FeatureSpec:
        if spec.name in self._specs:
            raise KeyError(f"feature {spec.name!r} already registered")
        self._specs[spec.name] = spec
        return spec

    def __getitem__(self, name: str) -> FeatureSpec:
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def names(self, tier: int | None = None) -> list[str]:
        return sorted(n for n, s in self._specs.items() if tier is None or s.tier == tier)

    def explain(self, name: str) -> str:
        s = self._specs[name]
        return (
            f"{s.name}  (tier {s.tier})\n"
            f"  what        : {s.description}\n"
            f"  built from  : {', '.join(s.depends_on)}\n"
            f"  normalised  : {s.normalisation}\n"
            f"  valid from  : week {s.defined_from_week}"
        )

    def requires_types(self, names: list[str]) -> set[str]:
        """Canonical types needed by a set of features  -  for channel control."""
        out: set[str] = set()
        for n in names:
            out |= set(self._specs[n].depends_on)
        return out - {"context_metadata", "derived"}

    def as_frame(self):
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "feature": s.name,
                    "tier": s.tier,
                    "depends_on": ",".join(s.depends_on),
                    "normalisation": s.normalisation,
                    "from_week": s.defined_from_week,
                    "description": s.description,
                }
                for s in self._specs.values()
            ]
        ).sort_values(["tier", "feature"]).reset_index(drop=True)


REGISTRY = FeatureRegistry()
