"""Configuration and seeding.

Config is plain dataclasses loaded from TOML via the stdlib `tomllib`, so the
project has no YAML dependency. Every run records the config it used, which is
what makes an experiment reproducible rather than merely repeatable.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

# The single seed from which every other seed is derived. Changing this changes
# every stochastic result in the project, which is the point.
DEFAULT_SEED = 20260813


@dataclass(frozen=True)
class StateConfig:
    """Latent state dimensionality and dynamics priors.

    Gate 1 fixes the default at 2 dimensions and the maximum at 3. `n_dims` is
    validated rather than merely documented, because the temptation to add
    dimensions when the model underperforms is exactly what the constraint exists
    to resist.
    """

    n_dims: int = 2
    dim_names: tuple[str, ...] = ("engagement", "capability")
    # Mean reversion rate per dimension, alpha in the Gate 1 transition equation.
    alpha_init: tuple[float, ...] = (0.30, 0.20)
    # Process noise variance per dimension, diag(Q).
    process_noise_init: tuple[float, ...] = (0.25, 0.15)
    # Prior covariance on z at t=0, before any observation is seen.
    initial_state_variance: float = 1.0
    # Empirical-Bayes shrinkage strength pulling a student's set point toward the
    # context mean. Higher = more pooling = a new student looks more like their cohort.
    setpoint_shrinkage: float = 4.0
    # Newton iterations in the Laplace update.
    max_newton_iters: int = 25
    newton_tol: float = 1e-8

    def __post_init__(self) -> None:
        if not 1 <= self.n_dims <= 3:
            raise ValueError(
                f"n_dims={self.n_dims} violates the Gate 1 constraint of 2 by default, "
                "3 maximum. Higher-dimensional states fitted to weekly counts are not "
                "identifiable and will fail test T4."
            )
        if len(self.dim_names) != self.n_dims:
            raise ValueError(f"dim_names has {len(self.dim_names)} entries, n_dims={self.n_dims}")
        for name, vec in (("alpha_init", self.alpha_init),
                          ("process_noise_init", self.process_noise_init)):
            if len(vec) != self.n_dims:
                raise ValueError(f"{name} has {len(vec)} entries, n_dims={self.n_dims}")


@dataclass(frozen=True)
class FeatureConfig:
    """Tier-1 feature construction."""

    # Trailing window for personal-baseline normalisation, in weeks.
    baseline_window: int = 4
    # Minimum weeks of history before a self-relative feature is considered defined.
    min_history: int = 2
    # Window for engagement slope and volatility.
    trend_window: int = 3
    epsilon: float = 1e-9


@dataclass(frozen=True)
class SimulationConfig:
    """Forward generative simulation."""

    n_particles: int = 500
    horizon_weeks: int = 8
    quantiles: tuple[float, ...] = (0.05, 0.25, 0.50, 0.75, 0.95)


@dataclass(frozen=True)
class EvaluationConfig:
    """Evaluation protocol.

    `forward_chained` is the only honest default for longitudinal data. Random
    splitting is available solely so that L0 can be reported to demonstrate how
    inflated it is.
    """

    calibration_bins: int = 10
    forward_chained: bool = True
    min_train_weeks: int = 3


@dataclass(frozen=True)
class Config:
    seed: int = DEFAULT_SEED
    run_name: str = "prototype"
    data_root: Path = Path("data")
    state: StateConfig = field(default_factory=StateConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    @property
    def raw_dir(self) -> Path:
        return Path(self.data_root) / "raw"

    @property
    def processed_dir(self) -> Path:
        return Path(self.data_root) / "processed"

    @classmethod
    def from_toml(cls, path: str | Path) -> "Config":
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        cfg = cls()
        if "run" in raw:
            cfg = replace(cfg, **{k: v for k, v in raw["run"].items() if k in {"seed", "run_name"}})
            if "data_root" in raw["run"]:
                cfg = replace(cfg, data_root=Path(raw["run"]["data_root"]))
        for key, klass in (("state", StateConfig), ("features", FeatureConfig),
                           ("simulation", SimulationConfig), ("evaluation", EvaluationConfig)):
            if key in raw:
                section = dict(raw[key])
                for tup_key in ("dim_names", "alpha_init", "process_noise_init", "quantiles"):
                    if tup_key in section:
                        section[tup_key] = tuple(section[tup_key])
                cfg = replace(cfg, **{key: klass(**section)})
        return cfg

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_root"] = str(self.data_root)
        return d


def rng_for(config: Config, purpose: str) -> np.random.Generator:
    """Derive an independent generator per purpose from the master seed.

    Using one global generator makes results depend on call order, so adding a
    diagnostic silently changes an experiment. Deriving per purpose means the
    simulation stream is unaffected by anything the fitting code does.
    """
    offset = int.from_bytes(purpose.encode("utf-8"), "little") % 1_000_003
    return np.random.default_rng(config.seed + offset)
