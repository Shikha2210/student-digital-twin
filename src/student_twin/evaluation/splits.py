"""Evaluation splits.

Only one of these is defensible for longitudinal data. The other exists to be
reported alongside it as evidence of how much it inflates results, which is why
its name is deliberately hard to type by accident.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def forward_chained_split(
    person_period: pd.DataFrame, cutoff_week: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on weeks <= cutoff, test on weeks > cutoff.

    The honest protocol: the model never sees a week it is asked to predict, for
    any student. Contrast with a random row split, which lets week 9 of a student
    train a model tested on week 4 of the same student.
    """
    train = person_period[person_period["t"] <= cutoff_week].copy()
    test = person_period[person_period["t"] > cutoff_week].copy()
    return train, test


def random_split_LEAKY(
    person_period: pd.DataFrame, test_frac: float = 0.3, seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Random row split. LEAKS THE FUTURE. Reported at L0 only, never as a result.

    Rows from the same student's later weeks end up in training while earlier
    weeks are tested, so the model has effectively seen the outcome. Any number
    from this split is an upper bound on self-deception, not on performance.
    """
    rng = np.random.default_rng(seed)
    mask = rng.random(len(person_period)) < test_frac
    return person_period[~mask].copy(), person_period[mask].copy()
