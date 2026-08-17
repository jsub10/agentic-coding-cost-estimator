"""One simulation pass: portfolio -> cost. A pure function of (params, scenario, rng).

Two paths sharing all their arithmetic downstream of the counts. ``deterministic_run`` puts
every random source at its expected value analytically — a *mean-like* quantity, above the
P50 on a right-skewed distribution (SPEC.md §6). ``simulate`` is the Monte Carlo pass.

The two rules this module exists to get right, both of which fail silently.

**``theta`` is drawn once per run, never per story.** Run-level arrays are ``(iterations,)``
and story-level arrays ``(iterations, n_stories, N_impl)``. A ``theta`` shaped like the
latter removes the correlation the model exists to capture, and no shape assertion catches
it — only the over-dispersion measurement in tests/test_properties.py does.

**Every random scaling is mean-preserving.** A lognormal carries its ``-sigma^2/2``; the
cluster multiplier's off-branch value is derived so the pair has expectation 1. Missing
either inflated the escape rate by 51% (REVIEW.md S1-1). The residual covariance between
``e_base`` and ``e_scale`` is documented in SPEC.md §5.

No I/O (CLAUDE.md §8). Draws come from an injected Generator.
"""

from __future__ import annotations

import math

import numpy as np

from params import CLASSES

UNCERTAINTY_MODES = ("full", "aleatory", "none")

# The genuinely random sources the variance decomposition may freeze (SPEC.md §5). A
# constant contributes zero variance, so no policy parameter appears here — that was the
# defect behind the old "batching 20%" line (REVIEW.md S3-1).
VARIANCE_SOURCES = ("escape", "q_rev", "d", "m", "S", "tokens", "k_scale")

HOUR_TERMS = ("criteria", "review", "spec", "architecture",
              "switch", "fallback", "restructure", "incident")

COST_TERMS = ("tokens",) + HOUR_TERMS


# --- Small closed forms ---------------------------------------------------------------

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


def expected_attempts(p, A_max):
    """Truncated attempt expectation: ``sum (1-p)^k, k < A_max``. Never ``1/p``.

    Required everywhere including the deterministic pass: ``1/p`` overstates Hard attempts
    by 5.3% in D and 8.4% in C, and Hard carries most of the token mass. Closed form below.
    """
    q = 1.0 - np.asarray(p, dtype=np.float64)
    return (1.0 - q ** A_max) / np.asarray(p, dtype=np.float64)


def implementation_fallback_probability(p, A_max):
    """``(1 - p)^A_max``: one implementation never converges (SPEC.md §4.2).

    Hitting the cap is not failing: one at the cap fails outright only with probability
    ``1 - p``, giving ``q^(A_max-1) * q``.
    """
    return (1.0 - p) ** A_max


def story_fallback_probability(p, A_max, n_impl, n_compare_min):
    """Probability a *story* falls back, over ``n_impl`` independent implementations.

    It falls back when fewer than ``min(n_compare_min, n_impl)`` converge, because Step 7
    needs two to compare (SPEC.md §4.2). With three, only zero or one survivor is a fallback.
    """
    u = implementation_fallback_probability(p, A_max)
    survived = 1.0 - u
    return float(sum(math.comb(n_impl, j) * survived ** j * u ** (n_impl - j)
                     for j in range(min(n_compare_min, n_impl))))


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



# --- Shared assembly. Both paths route through these, so there is one hours equation. ---

def count_touches(scenario, n_stories, n_reviewed, n_fallback):
    """Human contacts (SPEC.md §4.4).

    One per story for criteria, including stories that later fall back — criteria are
    authored before anyone knows which converge. One per story reviewed. One per flagged
    question, against all stories, only where Step 7 is active. One per fallback.
    """
    return (n_stories + n_reviewed
            + scenario["adjudication_rate"] * n_stories
            + n_fallback)


def compose_hours(params, scenario, n_stories, n_fallback, n_reviewed, n_escaped, S):
    """All eight hour terms of SPEC.md §4.4. Broadcasts over scalars or arrays alike.

    Architecture and switch are separate lines. They are the same size at the defaults,
    which let two documents disagree about which the total contained (REVIEW.md S2-2).
    """
    criteria = n_stories * S
    review = n_reviewed * scenario["R"]
    spec = scenario["spec_hours"]
    architecture = scenario["architecture_hours"]
    fallback = n_fallback * params["fallback_hours"]
    incident = n_escaped * params["I"]

    # The reserve is taken against the planned base only. Switch, fallback and incident
    # hours are consequences rather than plan, and reserving against them would compound.
    restructure = params["restructure_fraction"] * (criteria + review + spec + architecture)
    switch = count_touches(scenario, n_stories, n_reviewed, n_fallback) / params["b"] \
        * params["s"]

    hours = {"criteria": criteria, "review": review, "spec": spec, "switch": switch,
             "architecture": architecture, "fallback": fallback,
             "restructure": restructure, "incident": incident}
    hours["total"] = sum(hours[term] for term in HOUR_TERMS)
    return hours


def compose_costs(params, hours, token_cost):
    """SPEC.md §4.5. Every hour bills at ``w`` except incidents, which bill at ``w_inc``."""
    costs = {term: hours[term] * params["w"] for term in HOUR_TERMS if term != "incident"}
    costs["incident"] = hours["incident"] * params["w_inc"]
    costs["tokens"] = token_cost
    costs["total"] = sum(costs[term] for term in COST_TERMS)
    return costs


def token_cost_of(params, total_tokens):
    """SPEC.md §4.3. Tokens stay whole in the model; the conversion happens here only."""
    return total_tokens * params["c"] / 1.0e6


# --- The deterministic pass -----------------------------------------------------------


def deterministic_generation(params, scenario):
    """Expected generation tokens and expected fallback stories, analytically.

    ``E[L] = 1`` and ``E[k_scale] = 1``, so both drop out of the expectation and only the
    truncated attempt count remains.
    """
    A_max, n_compare_min = params["A_max"], params["n_compare_min"]
    generation_tokens = 0.0
    n_fallback = 0.0

    for cls in CLASSES:
        count, n_impl = scenario["n_stories"][cls], scenario["N_impl"][cls]
        p = scenario["p"][cls]
        generation_tokens += (count * n_impl * scenario["k"][cls]
                              * float(expected_attempts(p, A_max)))
        n_fallback += count * story_fallback_probability(p, A_max, n_impl, n_compare_min)

    return generation_tokens, n_fallback


def deterministic_run(params, scenario) -> dict:
    """Every random source at its expected value (SPEC.md §6).

    Must reproduce the published point estimates from the published parameters. Mean-like,
    so it is pinned separately from the P50 and sits above it (REVIEW.md S3-2).
    """
    n_stories = sum(scenario["n_stories"].values())
    generation_tokens, n_fallback = deterministic_generation(params, scenario)
    apparatus_tokens = sum(scenario["apparatus_tokens"].values())
    total_tokens = generation_tokens + apparatus_tokens

    e_gate = escape_gate(scenario["d"], scenario["rho"], scenario["m"])
    e = escape_rate(e_gate, scenario["f_base"], params["q_rev"])

    # A fallen-back story is human-written and leaves the auto-merge population. Escapes are
    # counted against the whole portfolio, per SPEC.md §5.
    n_reviewed = (n_stories - n_fallback) * (1.0 - scenario["f_base"])
    n_escaped = n_stories * e

    hours = compose_hours(params, scenario, n_stories, n_fallback, n_reviewed,
                          n_escaped, scenario["S"])
    token_cost = token_cost_of(params, total_tokens)
    costs = compose_costs(params, hours, token_cost)

    return {
        "scenario": scenario["name"],
        "label": scenario["label"],
        "n_stories": n_stories,
        "e_gate": float(e_gate),
        "e": float(e),
        "n_escaped": float(n_escaped),
        "n_reviewed": float(n_reviewed),
        "n_fallback": float(n_fallback),
        "n_touches": float(count_touches(scenario, n_stories, n_reviewed, n_fallback)),
        "generation_tokens": float(generation_tokens),
        "apparatus_tokens": float(apparatus_tokens),
        "total_tokens": float(total_tokens),
        "token_cost": float(token_cost),
        "hours": {term: float(value) for term, value in hours.items()},
        "cost": {term: float(value) for term, value in costs.items()},
        "human_cost": float(costs["total"] - token_cost),
        "total_cost": float(costs["total"]),
        "token_share": float(token_cost / costs["total"]),
        "fte": float(hours["total"]
                     / (params["calendar_weeks"] * params["hours_per_fte_week"])),
    }


# --- The Monte Carlo pass -------------------------------------------------------------


def _draw_epistemic(params, scenario, rng, n, uncertainty, frozen):
    """Parameter uncertainty, drawn once per iteration (SPEC.md §3.5).

    Beliefs about one organisation, not story-level noise. Every source is drawn whether or
    not it is switched off, then overwritten, so freezing one source changes it alone.
    """
    z = rng.standard_normal((4, n))
    alpha, beta = beta_shape(params["q_rev"], params["sd_q_rev"])
    q_rev_draw = rng.beta(alpha, beta, n)

    on = uncertainty == "full"
    ones = np.ones(n, dtype=np.float64)

    def epistemic(nominal, sigma, normals, name):
        if not on or name in frozen:
            return nominal * ones
        return nominal * lognormal_scale(normals, sigma)

    return {
        "d": epistemic(scenario["d"], params["sigma_d"], z[0], "d"),
        # m is a probability, so the lognormal is clipped. At the shipped values the clip
        # never binds, so it does not disturb the mean in practice (SPEC.md §3.5).
        "m": np.clip(epistemic(scenario["m"], params["sigma_m"], z[1], "m"), 0.0, 1.0),
        "S": epistemic(scenario["S"], params["sigma_S"], z[2], "S"),
        "k_scale": epistemic(1.0, params["sigma_k_scale"], z[3], "k_scale"),
        "q_rev": q_rev_draw if on and "q_rev" not in frozen else params["q_rev"] * ones,
    }


def _draw_escape(params, scenario, rng, n, uncertainty, frozen, epistemic):
    """The repo-level common factor and the escape rate it drives (SPEC.md §5)."""
    theta = rng.standard_normal(n)
    clustered = rng.random(n) < params["p_cluster"]
    ones = np.ones(n, dtype=np.float64)

    if uncertainty == "none" or "escape" in frozen:
        theta = np.zeros(n, dtype=np.float64)
        cluster_scale = ones
    else:
        off = cluster_off_multiplier(params["p_cluster"], params["cluster_mult"])
        cluster_scale = np.where(clustered, params["cluster_mult"], off)

    # f_base = 0 has no logit, and no amount of theta should move a gate that is switched
    # off. Handled explicitly rather than by letting an infinity propagate.
    if scenario["f_base"] <= 0.0:
        f_run = np.zeros(n, dtype=np.float64)
    else:
        f_run = logistic(logit(scenario["f_base"]) - params["lambda_f"] * theta)

    e_base = escape_rate(
        escape_gate(epistemic["d"], scenario["rho"], epistemic["m"]),
        f_run, epistemic["q_rev"])

    # exp(lambda_e*theta - lambda_e^2/2). The correction is not optional: without it this
    # factor has expectation exp(lambda_e^2/2) = 1.163 rather than 1, and with an uncentred
    # cluster multiplier it inflated the escape rate 51% (REVIEW.md S1-1). At lambda_e = 0
    # it collapses to 1, so no special case is needed.
    e_scale = lognormal_scale(theta, params["lambda_e"])
    return theta, f_run, np.clip(e_base * e_scale * cluster_scale, 0.0, 1.0)


def _draw_generation(params, scenario, rng, n, theta, frozen):
    """Generation tokens and the fallback count, drawn per implementation (SPEC.md §4.3).

    One ``A`` and one ``L`` per implementation, not one per story multiplied by ``N_impl``.
    Implementations run in isolated contexts with no shared history — the point of Step 7 —
    so each converges independently. Multiplying one draw by ``N_impl`` keeps the mean and
    inflates the epic token CV from 4.1% to 7.1% (REVIEW.md S1-2).
    """
    A_max, n_compare_min = params["A_max"], params["n_compare_min"]
    tokens = np.zeros(n, dtype=np.float64)
    n_fallback = np.zeros(n, dtype=np.float64)

    for cls in CLASSES:
        count, n_impl = scenario["n_stories"][cls], scenario["N_impl"][cls]
        if count == 0:
            continue
        shape = (n, count, n_impl)

        # theta loads only weakly on p, deliberately: an unfavourable move in p costs extra
        # tokens, while a doubling of e costs incident hours at premium rates.
        eps = rng.standard_normal(shape) * params["sigma_p"]
        p_impl = logistic(logit(scenario["p"][cls])
                          + params["lambda_p"] * theta[:, None, None] + eps)

        attempts = np.minimum(rng.geometric(p_impl), A_max).astype(np.float64)
        multiplier = lognormal_scale(rng.standard_normal(shape), params["sigma_k"])
        exhausted = rng.random(shape) < (1.0 - p_impl)

        if "tokens" in frozen:
            attempts_for_tokens = expected_attempts(p_impl, A_max)
            multiplier = np.ones(shape, dtype=np.float64)
        else:
            attempts_for_tokens = attempts
        tokens += scenario["k"][cls] * (attempts_for_tokens * multiplier).sum(axis=(1, 2))

        # Capped and then failed outright: P = q^(A_max-1) * q = q^A_max (SPEC.md §4.2).
        capped = (attempts >= A_max) & exhausted
        converged = n_impl - capped.sum(axis=2)
        n_fallback += (converged < min(n_compare_min, n_impl)).sum(axis=1)

    return tokens, n_fallback


def simulate(params, scenario, rng, iterations, uncertainty="full", frozen=()) -> dict:
    """One vectorised Monte Carlo block. Returns ``(iterations,)`` arrays, nothing wider.

    ``frozen`` names random sources to hold at their expected value, for the variance
    decomposition of SPEC.md §5. Valid names are in :data:`VARIANCE_SOURCES`.
    """
    if uncertainty not in UNCERTAINTY_MODES:
        raise ValueError(f"unknown uncertainty mode {uncertainty!r}; "
                         f"expected one of {UNCERTAINTY_MODES}")
    unknown = set(frozen) - set(VARIANCE_SOURCES)
    if unknown:
        raise ValueError(f"cannot freeze {sorted(unknown)}; "
                         f"random sources are {VARIANCE_SOURCES}")

    n_stories = sum(scenario["n_stories"].values())
    epistemic = _draw_epistemic(params, scenario, rng, iterations, uncertainty, frozen)
    theta, f_run, e_run = _draw_escape(params, scenario, rng, iterations, uncertainty,
                                       frozen, epistemic)
    generation, n_fallback = _draw_generation(params, scenario, rng, iterations, theta,
                                              frozen)

    total_tokens = (generation * epistemic["k_scale"]
                    + sum(scenario["apparatus_tokens"].values()))

    reviewable = np.maximum(n_stories - n_fallback, 0.0).astype(np.int64)
    n_reviewed = rng.binomial(reviewable, 1.0 - f_run).astype(np.float64)
    if "escape" in frozen:
        n_escaped = n_stories * e_run
    else:
        n_escaped = rng.binomial(n_stories, e_run).astype(np.float64)

    hours = compose_hours(params, scenario, n_stories, n_fallback, n_reviewed,
                          n_escaped, epistemic["S"])
    costs = compose_costs(params, hours, token_cost_of(params, total_tokens))

    return {"hours": hours, "cost": costs, "total_tokens": total_tokens,
            "n_escaped": n_escaped, "n_reviewed": n_reviewed, "n_fallback": n_fallback,
            "e_run": e_run, "f_run": f_run, "theta": theta}
