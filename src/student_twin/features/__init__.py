"""Feature layer, tiered per Gate 1 §03.

Tier 1 features are self-relative and dimensionless by construction; they are the
only tier the state model consumes. Tier 2 describes the context and is used for
conditioning. Tier 3 (institution-specific) has no builder here at all  -  the
absence is the enforcement.
"""

from .provenance import FeatureSpec, FeatureRegistry, REGISTRY
from .tier1 import build_tier1
from .context import build_context_covariates

__all__ = [
    "FeatureSpec",
    "FeatureRegistry",
    "REGISTRY",
    "build_tier1",
    "build_context_covariates",
]
