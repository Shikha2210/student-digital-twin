"""Observation likelihoods and their derivatives with respect to the state.

Each emission returns (loglik, gradient, Hessian) in state space, which is what
the Laplace update needs. Keeping them here  -  rather than inline in the filter  - 
means adding a channel (a survey instrument, say) is a new function plus a
registry entry, not surgery on the filter.

Channel-to-likelihood mapping:

    behaviour counts  negative binomial with log link   (over-dispersed counts)
    submission        Bernoulli with logit link         (non-submission is a datum)
    score             Gaussian on the logit scale       (PROTOTYPE SIMPLIFICATION,
                                                         see docs/assumptions.md A-04)
"""

from __future__ import annotations

import numpy as np
from scipy.special import gammaln

_ETA_CLIP = 12.0
_EPS = 1e-9


def _clip(eta: float) -> float:
    return float(np.clip(eta, -_ETA_CLIP, _ETA_CLIP))


def negbin(
    y: float, z: np.ndarray, intercept: float, loading: np.ndarray, phi: float
) -> tuple[float, np.ndarray, np.ndarray]:
    """Negative binomial, mean = exp(intercept + loading . z), dispersion phi.

    Poisson would assert variance equals mean, which weekly click counts violate
    badly; the resulting over-confidence would propagate straight into the state
    covariance and make the twin's uncertainty a fiction.
    """
    eta = _clip(intercept + float(loading @ z))
    mu = np.exp(eta)
    denom = phi + mu
    ll = (
        gammaln(y + phi) - gammaln(phi) - gammaln(y + 1.0)
        + phi * (np.log(phi + _EPS) - np.log(denom + _EPS))
        + y * (eta - np.log(denom + _EPS))
    )
    dll_deta = y - (y + phi) * mu / (denom + _EPS)
    d2ll_deta2 = -(y + phi) * phi * mu / (denom * denom + _EPS)
    grad = dll_deta * loading
    hess = d2ll_deta2 * np.outer(loading, loading)
    return float(ll), grad, hess


def bernoulli(
    y: float, z: np.ndarray, intercept: float, weights: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Bernoulli with logit link. y = 1 submitted, y = 0 did not.

    A zero here is an observation, not a gap. That is the whole reason the channel
    exists separately from the score channel.
    """
    eta = _clip(intercept + float(weights @ z))
    p = 1.0 / (1.0 + np.exp(-eta))
    ll = y * eta - np.log1p(np.exp(eta)) if eta < 30 else y * eta - eta
    grad = (y - p) * weights
    hess = -p * (1.0 - p) * np.outer(weights, weights)
    return float(ll), grad, hess


def gaussian_logit(
    y: float, z: np.ndarray, intercept: float, weights: np.ndarray, sigma: float
) -> tuple[float, np.ndarray, np.ndarray]:
    """Gaussian on logit(score).

    PROTOTYPE SIMPLIFICATION. Gate 1 equation 3 specifies a Beta likelihood with
    mean sigmoid(w.z). We use a Gaussian on the logit-transformed score, which
    shares the mean structure and the support constraint but has constant rather
    than mean-dependent variance. The consequence is under-dispersion near the
    bounds; scores concentrated at 0 or 1 will be modelled with too much
    confidence. Replacing this with the Beta form is Phase 1 work and requires no
    change outside this function.
    """
    y = float(np.clip(y, 1e-4, 1 - 1e-4))
    y_logit = np.log(y / (1.0 - y))
    eta = _clip(intercept + float(weights @ z))
    resid = y_logit - eta
    var = max(sigma * sigma, _EPS)
    ll = -0.5 * resid * resid / var - np.log(max(sigma, _EPS)) - 0.5 * np.log(2 * np.pi)
    grad = (resid / var) * weights
    hess = -(1.0 / var) * np.outer(weights, weights)
    return float(ll), grad, hess


def hazard_logit(z: np.ndarray, intercept: float, weights: np.ndarray) -> float:
    """Discrete-time hazard readout, P(withdraw in week t | survived, z_t).

    This is a *readout*, not an emission: it does not update the state. Keeping it
    out of the filter is what makes "prediction is a byproduct of state" true in
    the code and not just in the report.
    """
    eta = _clip(intercept + float(weights @ z))
    return float(1.0 / (1.0 + np.exp(-eta)))
