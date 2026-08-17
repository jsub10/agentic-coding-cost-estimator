"""The escape equation and the mean-preserving scalings that perturb it.

Split out of ``model.py`` when the covariance correction pushed that module past CLAUDE.md
§9's 400-line budget. The grouping is a real one rather than a convenience: everything here
is about the probability a defect reaches the trunk, and about keeping the random scalings
applied to it centred on their own means.

Three separate mean errors have been found in this small amount of arithmetic, which is why
each one is spelled out where it lives:

- ``exp(lambda_e*theta)`` without its ``-lambda_e^2/2`` — expectation 1.163 (REVIEW.md S1-1)
- a cluster multiplier applied only on the clustered branch — expectation 1.300 (S1-1)
- the covariance between ``e_base`` and ``e_scale``, which centring each one individually
  cannot remove — 2.0 to 2.7% low, corrected by :func:`covariance_correction` (SPEC.md §5)

Imports nothing from this project. No I/O (CLAUDE.md §8).
"""

from __future__ import annotations

import numpy as np

# Gauss-Hermite nodes for the one scalar quadrature in covariance_correction. A numerical
# detail rather than a modelling choice, so not a Param. The integrand is a bounded logistic
# against a Gaussian; 64 nodes converges it to machine precision, and hermegauss itself
# loses accuracy well before a few hundred.
_QUADRATURE_NODES = 64


def logit(p):
    """Log-odds — the space in which theta loads on a probability additively."""
    return np.log(p) - np.log1p(-np.asarray(p, dtype=np.float64))


def logistic(x):
    """Inverse of :func:`logit`."""
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=np.float64)))


def escape_gate(d, rho, m):
    """Stage one: the defect survives the automated oracle set (SPEC.md §4.1).

    ``d * (rho + (1 - rho) * m)`` — missed either because the check is blind to it by
    construction, or because the oracle set misses it. A named intermediate: a reader
    checking against SPEC.md §4.1 needs both stages visible.
    """
    return d * (rho + (1.0 - rho) * m)


def escape_rate(e_gate, f, q_rev):
    """Stage two: it also survives whatever review follows (SPEC.md §4.1).

    ``e_gate * (f + (1 - f) * q_rev)``. With probability ``f`` nobody sees it; otherwise a
    human reviews and misses it with probability ``q_rev``. Hence the counter-intuitive
    term: raising ``f`` *raises* ``e`` for a fixed gate.
    """
    return e_gate * (f + (1.0 - f) * q_rev)


def cluster_off_multiplier(p_cluster, cluster_mult):
    """Off-branch escape multiplier, derived so the clustered pair has expectation 1.

    ``(1 - p_cluster*cluster_mult) / (1 - p_cluster)`` = 0.647 at the defaults; applying
    ``cluster_mult`` on the clustered branch alone gives 1.300, half of REVIEW.md S1-1.
    """
    return (1.0 - p_cluster * cluster_mult) / (1.0 - p_cluster)


def lognormal_scale(normals, sigma):
    """Mean-preserving lognormal multiplier ``exp(sigma*Z - sigma^2/2)``, so ``E[.] = 1``.

    Takes standard normals rather than making them, so the caller controls the order the
    stream is consumed in — which is what gives the decomposition common random numbers.
    """
    return np.exp(sigma * normals - 0.5 * sigma * sigma)


def beta_shape(mean, sd):
    """A Beta's (alpha, beta) from its mean and standard deviation (SPEC.md §3.5)."""
    nu = mean * (1.0 - mean) / (sd * sd) - 1.0
    return mean * nu, (1.0 - mean) * nu


def covariance_correction(params, scenario):
    """``gamma``: the constant that makes ``E[e_base * e_scale]`` equal derived ``e``.

    Centring each scaling individually does not centre their product, because ``e_base`` and
    ``e_scale`` are both functions of the same ``theta`` and negatively correlated through
    it — a rising theta lowers ``f_run``, which sends more stories to review and lowers
    ``e_base``, while raising ``e_scale`` (SPEC.md §5).

    No quadrature is needed inside the loop. ``d``, ``m`` and ``q_rev`` are independent of
    theta and enter linearly, so they factor out, and Cameron-Martin removes the exponential
    from what remains: ``E[g(Z)exp(lambda_e*Z - lambda_e^2/2)] = E[g(Z + lambda_e)]``,
    because ``exp(lambda_e*z - lambda_e^2/2) phi(z) = phi(z - lambda_e)``. What is left is a
    bounded logistic against a shifted Gaussian, evaluated once per scenario.

    Returns exactly 1.0 when ``f_base`` is 0: ``f_run`` is then identically zero, ``e_base``
    does not depend on theta at all, and there is no covariance to remove.
    """
    f_base, q_rev = scenario["f_base"], params["q_rev"]
    if f_base <= 0.0:
        return 1.0

    nodes, weights = np.polynomial.hermite_e.hermegauss(_QUADRATURE_NODES)
    weights = weights / weights.sum()
    shifted_f = logistic(logit(f_base)
                         - params["lambda_f"] * (nodes + params["lambda_e"]))

    target = f_base + (1.0 - f_base) * q_rev
    shifted = float((weights * (shifted_f + (1.0 - shifted_f) * q_rev)).sum())
    return target / shifted
