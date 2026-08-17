"""Invariants that come from arithmetic rather than from the spec text (CLAUDE.md §7).

The most important test in this file, and in the suite, is
``test_theta_is_shared_within_a_run``. Drawing the common factor per story instead of per
iteration produces entirely plausible numbers, passes every shape assertion, and silently
removes the correlation the model exists to capture. It is caught here by measuring the
correlation between story outcomes within a run, which is the only thing that can catch it.
"""

from __future__ import annotations

import numpy as np
import pytest

import model
import montecarlo
import params as params_module
import scenarios

import reference

SCENARIOS = scenarios.scenario_names()


@pytest.fixture()
def params():
    return params_module.default_params()


def resolved(name, params):
    return scenarios.resolve_scenario(name, params)


# --- The correlation the model exists to capture --------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_theta_is_shared_within_a_run(name, params):
    """The common factor must be one draw per run, shared by every story in it.

    Measured rather than asserted structurally, because the failure this catches produces
    entirely plausible numbers and passes every shape assertion. If ``theta`` were drawn per
    story, escape outcomes within a run would be independent and the variance of the escape
    *count* would collapse to the binomial ``n*e*(1-e)``. Because theta is shared, runs are
    heavily over-dispersed instead.

    Measured over-dispersion at the shipped parameters is 21.7x in A, 17.7x in B, 7.2x in C,
    6.3x in D and 2.9x in D+. Drawing theta with shape ``(iterations, n_stories)`` gives
    1.00x. The threshold sits at 2.5x, which every scenario clears and the bug cannot.
    """
    scenario = resolved(name, params)
    n_stories = sum(scenario["n_stories"].values())

    rng = np.random.default_rng(13)
    draw = model.simulate(params, scenario, rng, 40_000)
    escaped = np.asarray(draw["n_escaped"])

    e_hat = escaped.mean() / n_stories
    binomial_variance = n_stories * e_hat * (1.0 - e_hat)

    assert escaped.var() > 2.5 * binomial_variance, (
        f"{name}: escape counts are only {escaped.var() / binomial_variance:.2f}x "
        "over-dispersed relative to binomial, which is what a per-story theta produces")


def test_theta_is_one_value_per_iteration(params):
    """The shape rule itself, checked directly: theta is (iterations,), never wider."""
    rng = np.random.default_rng(1)
    draw = model.simulate(params, resolved("all_three", params), rng, 500)
    assert np.asarray(draw["theta"]).shape == (500,)
    assert np.asarray(draw["e_run"]).shape == (500,)
    assert np.asarray(draw["f_run"]).shape == (500,)


def test_a_high_theta_run_escapes_more_than_a_low_theta_one(params):
    """The loading has the sign the model claims: bad repo conditions cost more."""
    rng = np.random.default_rng(2)
    draw = model.simulate(params, resolved("all_three", params), rng, 40_000)
    theta = np.asarray(draw["theta"])
    escaped = np.asarray(draw["n_escaped"])
    worst = escaped[theta > 1.0].mean()
    best = escaped[theta < -1.0].mean()
    assert worst > best


# --- The differential reference --------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_agrees_with_the_slow_obvious_reference(name, params):
    """The vectorised deterministic pass must match nested Python loops (CLAUDE.md §7)."""
    scenario = resolved(name, params)
    fast = model.deterministic_run(params, scenario)
    slow = reference.deterministic_run(params, scenario)

    for key in ("e_gate", "e", "n_escaped", "n_reviewed", "n_fallback", "n_touches",
                "generation_tokens", "apparatus_tokens", "total_tokens", "token_cost",
                "human_cost", "total_cost", "token_share"):
        assert fast[key] == pytest.approx(slow[key], rel=1e-9), key
    for term in model.HOUR_TERMS + ("total",):
        assert fast["hours"][term] == pytest.approx(slow["hours"][term], rel=1e-9), term


@pytest.mark.parametrize("p", [0.28, 0.40, 0.65, 0.90])
def test_attempt_expectation_matches_the_explicit_series(p):
    """Closed form against term-by-term summation."""
    for A_max in (1, 3, 5, 12):
        assert model.expected_attempts(p, A_max) == pytest.approx(
            reference.expected_attempts(p, A_max), rel=1e-12)


@pytest.mark.parametrize("n_impl", [1, 2, 3, 5])
def test_fallback_probability_matches_full_enumeration(n_impl):
    """Binomial tail against enumerating all 2^n outcomes."""
    for p in (0.28, 0.65, 0.92):
        assert model.story_fallback_probability(p, 5, n_impl, 2) == pytest.approx(
            reference.story_fallback_probability(p, 5, n_impl, 2), rel=1e-12)


# --- Mean-preserving scalings ----------------------------------------------------------


def test_lognormal_scale_has_mean_one():
    """CLAUDE.md §6: a lognormal needs mu = -sigma^2/2, or it is not mean-preserving."""
    rng = np.random.default_rng(4)
    for sigma in (0.15, 0.35, 0.55):
        draws = model.lognormal_scale(rng.standard_normal(400_000), sigma)
        assert draws.mean() == pytest.approx(1.0, rel=0.01)


def test_cluster_pair_has_mean_one(params):
    """CLAUDE.md §6: the off-branch value must be set so the branch pair averages to 1."""
    p_cluster, mult = params["p_cluster"], params["cluster_mult"]
    off = model.cluster_off_multiplier(p_cluster, mult)
    assert p_cluster * mult + (1.0 - p_cluster) * off == pytest.approx(1.0)
    # And the uncentred version, which is the error REVIEW.md S1-1 found, is 1.30 not 1.
    assert p_cluster * mult + (1.0 - p_cluster) * 1.0 == pytest.approx(1.30)


def test_beta_shape_recovers_its_mean_and_sd(params):
    alpha, beta = model.beta_shape(params["q_rev"], params["sd_q_rev"])
    mean = alpha / (alpha + beta)
    variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1.0))
    assert mean == pytest.approx(params["q_rev"])
    assert variance ** 0.5 == pytest.approx(params["sd_q_rev"])


def test_token_multiplier_does_not_shift_expected_tokens(params):
    """§4.3: L adds spread without shifting the expected value."""
    scenario = resolved("all_three", params)
    rng = np.random.default_rng(6)
    draw = model.simulate(params, scenario, rng, 60_000, uncertainty="aleatory")
    direct = model.deterministic_run(params, scenario)
    assert np.asarray(draw["total_tokens"]).mean() == pytest.approx(
        direct["total_tokens"], rel=0.01)


# --- Ordering and monotonicity ---------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_percentiles_are_ordered_for_every_component(name, params):
    result = montecarlo.run_scenario(name, params, iterations=3000, seed=8)
    for component, pct in result["percentiles"].items():
        assert pct["p50"] <= pct["p80"] <= pct["p95"], component


def test_scenario_total_equals_the_sum_of_its_components(params):
    """A component breakdown that does not sum to its total is not a breakdown."""
    scenario = resolved("all_three", params)
    direct = model.deterministic_run(params, scenario)
    parts = sum(direct["cost"][term] for term in model.COST_TERMS)
    assert direct["cost"]["total"] == pytest.approx(parts)


@pytest.mark.parametrize("name", SCENARIOS)
def test_cost_is_non_decreasing_in_story_count(name, params):
    costs = []
    for n in (5, 20, 60, 120):
        widened = params_module.apply_overrides(
            params, {"n_routine": n, "n_standard": n, "n_hard": n})
        costs.append(model.deterministic_run(
            widened, resolved(name, widened))["total_cost"])
    assert costs == sorted(costs)


def test_token_cost_is_exactly_tokens_times_price(params):
    for name in SCENARIOS:
        direct = model.deterministic_run(params, resolved(name, params))
        assert direct["token_cost"] == pytest.approx(
            direct["total_tokens"] * params["c"] / 1e6, rel=1e-12)


def test_escape_rate_is_monotone_in_each_primitive(params):
    """Each of d, rho, m, f can only push e in one direction."""
    base = model.escape_rate(model.escape_gate(0.24, 0.05, 0.06), 0.90, 0.35)
    assert model.escape_rate(model.escape_gate(0.30, 0.05, 0.06), 0.90, 0.35) > base
    assert model.escape_rate(model.escape_gate(0.24, 0.20, 0.06), 0.90, 0.35) > base
    assert model.escape_rate(model.escape_gate(0.24, 0.05, 0.30), 0.90, 0.35) > base
    assert model.escape_rate(model.escape_gate(0.24, 0.05, 0.06), 0.95, 0.35) > base


def test_more_iterations_move_percentiles_less(params):
    """Convergence: the estimate should settle, not wander."""
    quick = montecarlo.run_scenario("all_three", params, iterations=2000, seed=8)
    fine = montecarlo.run_scenario("all_three", params, iterations=60_000, seed=8)
    finer = montecarlo.run_scenario("all_three", params, iterations=60_000, seed=9)
    gap = abs(fine["percentiles"]["total"]["p50"] - finer["percentiles"]["total"]["p50"])
    assert gap < 0.02 * fine["percentiles"]["total"]["p50"]
    assert quick["percentiles"]["total"]["p50"] == pytest.approx(
        fine["percentiles"]["total"]["p50"], rel=0.05)


# --- Determinism -----------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_same_seed_same_answer(name, params):
    """CLAUDE.md §2: byte-identical output for the same seed and parameters."""
    first = montecarlo.run_scenario(name, params, iterations=1500, seed=99)
    second = montecarlo.run_scenario(name, params, iterations=1500, seed=99)
    assert first == second


def test_chunking_does_not_change_the_answer(params, monkeypatch):
    """Chunk boundaries are an implementation detail of memory, not of the model.

    They do change the RNG stream, so the two runs cannot be identical — but they must
    agree to Monte Carlo error, which is what rules out a chunk-boundary bug such as
    theta being redrawn or a class being dropped.
    """
    scenario_name = "all_three_quality"
    big = montecarlo.run_scenario(scenario_name, params, iterations=30_000, seed=5)
    monkeypatch.setattr(montecarlo, "CHUNK_ELEMENTS", 120_000)
    small = montecarlo.run_scenario(scenario_name, params, iterations=30_000, seed=5)
    assert small["percentiles"]["total"]["p50"] == pytest.approx(
        big["percentiles"]["total"]["p50"], rel=0.02)
    assert small["mean_escaped"] == pytest.approx(big["mean_escaped"], rel=0.05)


def test_no_global_random_state_is_used(params, monkeypatch):
    """CLAUDE.md §2: no numpy.random.seed, no legacy numpy.random.*, no global random."""
    def explode(*args, **kwargs):
        raise AssertionError("the model reached for a global RNG")

    monkeypatch.setattr(np.random, "seed", explode)
    monkeypatch.setattr(np.random, "normal", explode)
    monkeypatch.setattr(np.random, "geometric", explode)
    monkeypatch.setattr(np.random, "binomial", explode)
    montecarlo.run_scenario("all_three", params, iterations=500, seed=1)


# --- Budgets, CLAUDE.md §9 -------------------------------------------------------------


def test_full_run_is_fast(params):
    """5 scenarios x 10,000 iterations x 160 stories in under 5 seconds on one core."""
    import time
    start = time.perf_counter()
    montecarlo.run_all(params, iterations=10_000, seed=7)
    assert time.perf_counter() - start < 5.0


def test_no_function_exceeds_fifty_lines():
    """CLAUDE.md §9. Checked mechanically, because it is easy to drift past."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "reference_model.py":     # supplied reference, not project source
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno + 1
                if length > 50:
                    offenders.append(f"{path.name}:{node.name} is {length} lines")
    assert not offenders, "; ".join(offenders)


def test_no_module_exceeds_four_hundred_lines():
    """CLAUDE.md §9."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "reference_model.py":     # supplied reference, not project source
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 400:
            offenders.append(f"{path.name} is {lines} lines")
    assert not offenders, "; ".join(offenders)
