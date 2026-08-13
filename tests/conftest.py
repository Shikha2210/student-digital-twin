"""Shared fixtures. Everything is seeded; nothing here touches OULAD."""

from __future__ import annotations

import pytest

from student_twin.adapters import get_adapter
from student_twin.config import Config
from student_twin.features.context import build_context_covariates
from student_twin.features.tier1 import build_tier1, observation_frame
from student_twin.state.filter import TwinFilter
from student_twin.state.fit import fit_twin


@pytest.fixture(scope="session")
def config() -> Config:
    return Config()


@pytest.fixture(scope="session")
def small_data():
    """A deliberately tiny deterministic cohort - fast enough for every test."""
    return get_adapter("synthetic", n_students=40, n_weeks=12, seed=7).load()


@pytest.fixture(scope="session")
def obs(small_data):
    return observation_frame(small_data.events, n_weeks=12)


@pytest.fixture(scope="session")
def feats(small_data, config):
    return build_tier1(small_data.events, config.features, n_weeks=12)


@pytest.fixture(scope="session")
def ctx(small_data):
    return build_context_covariates(small_data.events, small_data.contexts, n_weeks=12)


@pytest.fixture(scope="session")
def params(small_data, obs, ctx, config):
    return fit_twin(small_data, obs, ctx, config)


@pytest.fixture(scope="session")
def twin_filter(params, config):
    return TwinFilter(params, config.state)
