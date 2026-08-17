"""Acceptance suite — derived from SPEC.md, and from nothing else.

**This file must never be edited to make an implementation pass** (CLAUDE.md §7). If it is
wrong, fix SPEC.md first and then regenerate it. It was written before model.py existed,
which is why it reads as a specification of the API rather than a tour of it.

Every assertion cites the SPEC.md section it comes from. Where SPEC.md publishes a figure to
a stated precision, the tolerance here is that precision and no looser — a value rounded to
the nearest $100 is checked to $100, not to 1%.

The API this suite pins down, all plain functions returning plain dicts (SPEC.md §11,
2026-08-17):

    params.default_params()                          -> {name: value}
    scenarios.resolve_scenario(name, params)         -> resolved scenario dict
    model.expected_attempts(p, A_max)                -> truncated E[A]
    model.escape_gate(d, rho, m)                     -> e_gate
    model.escape_rate(e_gate, f, q_rev)              -> e
    model.story_fallback_probability(p, A_max, n, c) -> P(story falls back)
    model.deterministic_run(params, scenario)        -> result dict
    montecarlo.run_scenario(name, params, ...)       -> result dict
    montecarlo.run_all(params, ...)                  -> {name: result dict}
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import model
import montecarlo
import params as params_module
import scenarios

SCENARIOS = ("execute_only", "execute_decide", "execute_deliver",
             "all_three", "all_three_quality")


@pytest.fixture()
def params():
    return params_module.default_params()


def resolved(name, params):
    return scenarios.resolve_scenario(name, params)


# ======================================================================================
# SPEC.md §4.1 — the escape rate, derived in two stages from four primitives
# ======================================================================================

# The table in SPEC.md §4.1: d, rho, m, f, and the e it must compute to.
ESCAPE_TABLE = {
    "execute_only": (0.30, 0.70, 0.30, 0.00, 0.083),
    "execute_decide": (0.24, 0.70, 0.30, 0.00, 0.066),
    "execute_deliver": (0.30, 0.05, 0.06, 0.85, 0.029),
    "all_three": (0.24, 0.05, 0.06, 0.90, 0.024),
    "all_three_quality": (0.24, 0.02, 0.02, 0.90, 0.009),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_resolves_to_the_primitives_in_the_escape_table(name, params):
    """§4.1's d, rho, m and f must come out of the step declarations, not be entered."""
    d, rho, m, f, _ = ESCAPE_TABLE[name]
    scenario = resolved(name, params)
    assert scenario["d"] == pytest.approx(d)
    assert scenario["rho"] == pytest.approx(rho)
    assert scenario["m"] == pytest.approx(m)
    assert scenario["f_base"] == pytest.approx(f)


@pytest.mark.parametrize("name", SCENARIOS)
def test_escape_rate_reproduces_the_published_table(name, params):
    """§4.1: five published escape rates from four primitives, to the stated 0.1%."""
    d, rho, m, f, expected_e = ESCAPE_TABLE[name]
    e_gate = model.escape_gate(d, rho, m)
    e = model.escape_rate(e_gate, f, params["q_rev"])
    assert e == pytest.approx(expected_e, abs=0.0005)


def test_escape_gate_is_the_first_stage_only():
    """§4.1: e_gate = d(rho + (1-rho)m), the probability of surviving the oracle set."""
    assert model.escape_gate(0.30, 0.70, 0.30) == pytest.approx(0.30 * (0.70 + 0.30 * 0.30))
    # A perfectly independent check (rho = 0) leaves only the oracle miss rate.
    assert model.escape_gate(0.30, 0.0, 0.06) == pytest.approx(0.30 * 0.06)
    # A wholly blind check (rho = 1) catches nothing at all.
    assert model.escape_gate(0.30, 1.0, 0.0) == pytest.approx(0.30)


def test_auto_merge_raises_the_escape_rate_for_a_fixed_gate():
    """§4.1 and README: raising f *raises* e, because it removes the second filter.

    This is the counter-intuitive term, and it is why automating review is only safe as
    part of the same change that installs the oracle apparatus.
    """
    e_gate = 0.03
    assert model.escape_rate(e_gate, 0.0, 0.35) < model.escape_rate(e_gate, 0.9, 0.35)
    # With no auto-merge, only review stands between the defect and the trunk.
    assert model.escape_rate(e_gate, 0.0, 0.35) == pytest.approx(e_gate * 0.35)
    # With everything auto-merged, nothing does.
    assert model.escape_rate(e_gate, 1.0, 0.35) == pytest.approx(e_gate)


def test_better_specifications_alone_do_not_buy_independence(params):
    """§6: rho stays at 0.70 in B, so its escape rate stays in A's band.

    The model's sharpest structural statement. B lowers d, which is worth something, but
    the escape rate does not move into C's band until Step 5 freezes the suite.
    """
    a, b, c = (resolved(n, params) for n in ("execute_only", "execute_decide",
                                             "execute_deliver"))
    assert b["rho"] == a["rho"] == 0.70
    assert c["rho"] < 0.10

    def e_of(s):
        return model.escape_rate(model.escape_gate(s["d"], s["rho"], s["m"]),
                                 s["f_base"], params["q_rev"])

    assert e_of(b) > 0.5 * e_of(a)      # same band: Decide alone buys well under half
    assert e_of(c) < 0.5 * e_of(a)      # Deliver alone more than halves it


# ======================================================================================
# SPEC.md §4.2 — attempts, truncated, and the fallback branch that truncation creates
# ======================================================================================


@pytest.mark.parametrize("p", [0.28, 0.40, 0.45, 0.65, 0.90])
def test_expected_attempts_is_the_truncated_sum(p):
    """§4.2: E[A] = sum of (1-p)^k for k in 0..A_max-1. Never 1/p."""
    A_max = 5
    expected = sum((1.0 - p) ** k for k in range(A_max))
    assert model.expected_attempts(p, A_max) == pytest.approx(expected, rel=1e-12)


def test_truncation_matters_by_the_published_amount():
    """§4.2: 1/p overstates Hard attempts by 5.3% in D and 8.4% in C.

    Both figures follow only if D's Hard p is 0.45 and C's is 0.40, which is independent
    confirmation of the four-table p selection in §3.3.
    """
    for p, overstatement in ((0.45, 0.053), (0.40, 0.084)):
        truncated = model.expected_attempts(p, 5)
        assert (1.0 / p) / truncated - 1.0 == pytest.approx(overstatement, abs=0.001)


def test_expected_attempts_approaches_one_over_p_as_the_cap_lifts():
    """§4.2: the truncated expectation is the honest one, and it has the right limit."""
    assert model.expected_attempts(0.40, 200) == pytest.approx(1.0 / 0.40, rel=1e-6)
    assert model.expected_attempts(0.40, 1) == pytest.approx(1.0)


@pytest.mark.parametrize("p", [0.28, 0.50, 0.90])
def test_implementation_fallback_probability(p):
    """§4.2: P(implementation falls back) = (1-p)^A_max, conditioned correctly."""
    single = model.story_fallback_probability(p, A_max=5, n_impl=1, n_compare_min=1)
    assert single == pytest.approx((1.0 - p) ** 5)


def test_story_falls_back_when_too_few_implementations_converge():
    """§4.2: a story falls back when converged < min(2, N_impl); Step 7 needs two."""
    p, A_max, u = 0.65, 5, (1.0 - 0.65) ** 5

    # N = 1: the comparison threshold collapses to 1, so the story falls back only if its
    # single implementation does.
    assert model.story_fallback_probability(p, A_max, 1, 2) == pytest.approx(u)
    # N = 2: it needs both, so it falls back if either fails.
    assert model.story_fallback_probability(p, A_max, 2, 2) == pytest.approx(1.0 - (1 - u) ** 2)
    # N = 3: it needs any two, so it falls back only on zero or one survivor.
    expected = u ** 3 + 3 * u ** 2 * (1 - u)
    assert model.story_fallback_probability(p, A_max, 3, 2) == pytest.approx(expected)


def test_more_implementations_reduce_fallback_once_past_the_threshold():
    """§4.2: the apparatus that raises p also nearly eliminates the fallback queue."""
    at_two = model.story_fallback_probability(0.40, 5, 2, 2)
    at_five = model.story_fallback_probability(0.40, 5, 5, 2)
    assert at_five < at_two


# ======================================================================================
# SPEC.md §6 — the deterministic pass, all random sources at their expected values
# ======================================================================================

# SPEC.md §6 "Deterministic pass". Precision as published: hours to 1, dollars to $100,
# tokens to 0.01B, share to 0.1pp, e to 0.1pp, fallback stories to 0.1.
DETERMINISTIC = {
    #                  hours  human $   tokens     token $   total $  share%   e%   fallback
    "execute_only":      (1173, 215800, 0.96e9,     2900,  218600,  1.3,  8.3, 6.4),
    "execute_decide":    (838,  157500, 1.49e9,     4500,  162000,  2.8,  6.6, 4.6),
    "execute_deliver":   (766,  128900, 2.42e9,     7300,  136100,  5.3,  2.9, 4.2),
    "all_three":         (347,   63600, 3.69e9,    11100,   74700, 14.8,  2.4, 0.4),
    "all_three_quality": (315,   51500, 10.44e9,   31300,   82800, 37.8,  0.9, 0.0),
}


@pytest.fixture()
def deterministic(params):
    """The deterministic pass for all five scenarios, computed once."""
    return {name: model.deterministic_run(params, resolved(name, params))
            for name in SCENARIOS}


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_hours(name, deterministic):
    """§6: total hours, all eight terms included (§4.4)."""
    assert deterministic[name]["hours"]["total"] == pytest.approx(
        DETERMINISTIC[name][0], abs=1.0)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_human_cost(name, deterministic):
    """§4.5: non-incident hours at w, incident hours at the premium w_inc."""
    assert deterministic[name]["human_cost"] == pytest.approx(
        DETERMINISTIC[name][1], abs=100.0)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_tokens(name, deterministic):
    """§4.3: generation x k_scale + apparatus, with all five apparatus lines."""
    assert deterministic[name]["total_tokens"] == pytest.approx(
        DETERMINISTIC[name][2], abs=0.01e9)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_token_cost(name, deterministic):
    """§4.3: token_cost = total_tokens x c / 1e6, converted only at the boundary."""
    assert deterministic[name]["token_cost"] == pytest.approx(
        DETERMINISTIC[name][3], abs=100.0)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_total_cost(name, deterministic):
    """§6: the pinned deterministic total. This is a mean-like quantity, not a P50 (§3.2)."""
    assert deterministic[name]["total_cost"] == pytest.approx(
        DETERMINISTIC[name][4], abs=100.0)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_token_share(name, deterministic):
    """§6: token share rises as total cost falls, from 1.3% to 37.8%."""
    assert deterministic[name]["token_share"] * 100.0 == pytest.approx(
        DETERMINISTIC[name][5], abs=0.1)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_escape_rate(name, deterministic):
    """§6: the derived e, carried through to the result rather than recomputed downstream."""
    assert deterministic[name]["e"] * 100.0 == pytest.approx(DETERMINISTIC[name][6], abs=0.1)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_fallback_count(name, deterministic):
    """§4.2: 6.4 fallback stories in A and 0.4 in D. The 10% figure is a stress case."""
    assert deterministic[name]["n_fallback"] == pytest.approx(
        DETERMINISTIC[name][7], abs=0.06)


def test_token_share_rises_as_total_cost_falls(deterministic):
    """§6 and README: the correct direction. Do not govern to a token budget."""
    shares = [deterministic[n]["token_share"] for n in SCENARIOS]
    assert shares == sorted(shares)
    assert shares[0] < 0.02 and shares[-1] > 0.30


def test_fallback_queue_nearly_vanishes_under_the_full_process(deterministic):
    """§4.2: the apparatus that raises p also nearly eliminates the fallback queue."""
    assert deterministic["all_three"]["n_fallback"] < 0.1 * deterministic[
        "execute_only"]["n_fallback"]


# ======================================================================================
# SPEC.md §4.4 and §4.5 — the eight hour terms and the two wage rates
# ======================================================================================

HOUR_TERMS = ("criteria", "review", "spec", "architecture",
              "switch", "fallback", "restructure", "incident")


@pytest.mark.parametrize("name", SCENARIOS)
def test_all_eight_hour_terms_are_present_and_sum_to_the_total(name, deterministic):
    """§4.4: all eight terms are included. Architecture and switch are separate lines."""
    hours = deterministic[name]["hours"]
    for term in HOUR_TERMS:
        assert term in hours, f"{name} is missing the {term} hours line"
    assert hours["total"] == pytest.approx(sum(hours[t] for t in HOUR_TERMS))


@pytest.mark.parametrize("name", SCENARIOS)
def test_restructuring_reserve_is_actually_reserved(name, deterministic, params):
    """§4.4: restructure = fraction x (criteria + review + spec + architecture).

    REVIEW.md S2-3 found the reserve recommended and reserved in no published total.
    """
    hours = deterministic[name]["hours"]
    base = hours["criteria"] + hours["review"] + hours["spec"] + hours["architecture"]
    assert hours["restructure"] == pytest.approx(params["restructure_fraction"] * base)
    assert hours["restructure"] > 0.0


@pytest.mark.parametrize("name", SCENARIOS)
def test_incident_hours_are_billed_at_the_premium_rate(name, deterministic, params):
    """§4.5: incident hours bill at w_inc, every other hour at w."""
    result = deterministic[name]
    hours = result["hours"]
    non_incident = sum(hours[t] for t in HOUR_TERMS if t != "incident")
    expected = non_incident * params["w"] + hours["incident"] * params["w_inc"]
    assert result["human_cost"] == pytest.approx(expected)
    assert params["w_inc"] > params["w"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_cost_is_token_cost_plus_human_cost(name, deterministic):
    """§4.5: nothing else is in the total."""
    result = deterministic[name]
    assert result["total_cost"] == pytest.approx(result["token_cost"] + result["human_cost"])


@pytest.mark.parametrize("name", SCENARIOS)
def test_criteria_and_review_volumes(name, deterministic, params):
    """§4.4: criteria for every story; review only for stories neither merged nor fallen back."""
    result, scenario = deterministic[name], resolved(name, params)
    n_stories = sum(scenario["n_stories"].values())
    assert result["hours"]["criteria"] == pytest.approx(n_stories * scenario["S"])
    expected_reviewed = (n_stories - result["n_fallback"]) * (1.0 - scenario["f_base"])
    assert result["n_reviewed"] == pytest.approx(expected_reviewed)
    assert result["hours"]["review"] == pytest.approx(result["n_reviewed"] * scenario["R"])


@pytest.mark.parametrize("name", SCENARIOS)
def test_touch_counting_and_switch_cost(name, deterministic, params):
    """§4.4: touches = stories + reviewed + adjudications + fallbacks, batched by b."""
    result, scenario = deterministic[name], resolved(name, params)
    n_stories = sum(scenario["n_stories"].values())
    expected = (n_stories + result["n_reviewed"]
                + scenario["adjudication_rate"] * n_stories + result["n_fallback"])
    assert result["n_touches"] == pytest.approx(expected)
    assert result["hours"]["switch"] == pytest.approx(
        result["n_touches"] / params["b"] * params["s"])


@pytest.mark.parametrize("name", ("execute_only", "execute_decide"))
def test_no_adjudication_touches_without_step_seven(name, params):
    """§4.4: a scenario with no cross-implementation comparison raises no flagged questions."""
    assert resolved(name, params)["adjudication_rate"] == 0.0


@pytest.mark.parametrize("name", ("execute_deliver", "all_three", "all_three_quality"))
def test_adjudication_touches_exist_where_step_seven_is_active(name, params):
    assert resolved(name, params)["adjudication_rate"] > 0.0


def test_batching_is_the_only_thing_that_moves_switch_cost(params):
    """§4.4: b = 1 means every touch is an interruption, and the model shows what it costs."""
    scenario = resolved("execute_only", params)
    batched = model.deterministic_run(params, scenario)
    interrupted = model.deterministic_run(
        params_module.apply_overrides(params, {"b": 1}), scenario)
    assert interrupted["hours"]["switch"] == pytest.approx(
        batched["hours"]["switch"] * params["b"])
    assert interrupted["total_cost"] > batched["total_cost"]


# ======================================================================================
# SPEC.md §6 — savings, and the superadditivity of the two phases
# ======================================================================================


def test_published_savings_against_the_baseline(deterministic):
    """§6: B 26%, C 38%, D 66%, D+ 62% against A."""
    baseline = deterministic["execute_only"]["total_cost"]
    expected = {"execute_decide": 26.0, "execute_deliver": 38.0,
                "all_three": 66.0, "all_three_quality": 62.0}
    for name, published in expected.items():
        saving = (1.0 - deterministic[name]["total_cost"] / baseline) * 100.0
        assert saving == pytest.approx(published, abs=0.5)


def test_deliver_alone_saves_more_than_decide_alone(deterministic):
    """§6: review volume is the largest single block in the bolt-on baseline."""
    assert deterministic["execute_deliver"]["total_cost"] < deterministic[
        "execute_decide"]["total_cost"]


def test_the_two_phases_are_substantially_superadditive(deterministic):
    """§6: the null for two independent interventions is multiplicative, not additive.

    1 - (1 - 0.26)(1 - 0.38) = 54%. D delivers 66%, so the synergy is +12 points, not the
    +1 an additive comparison suggests.
    """
    baseline = deterministic["execute_only"]["total_cost"]
    saving_b = 1.0 - deterministic["execute_decide"]["total_cost"] / baseline
    saving_c = 1.0 - deterministic["execute_deliver"]["total_cost"] / baseline
    saving_d = 1.0 - deterministic["all_three"]["total_cost"] / baseline

    null = 1.0 - (1.0 - saving_b) * (1.0 - saving_c)
    assert null * 100.0 == pytest.approx(54.0, abs=1.0)
    assert (saving_d - null) * 100.0 == pytest.approx(12.0, abs=1.0)
    # Savings fractions do not add, and the additive comparison is the wrong one.
    assert saving_d > null


def test_quality_maximisation_costs_more_at_the_expected_value(deterministic):
    """§6: D+ is more expensive than D deterministically. Its case is about the tail."""
    assert deterministic["all_three_quality"]["total_cost"] > deterministic[
        "all_three"]["total_cost"]
    assert deterministic["all_three_quality"]["e"] < deterministic["all_three"]["e"]


# ======================================================================================
# SPEC.md §5 — the simulation. Mean-preservation is the property the model turns on.
# ======================================================================================


def derived_escape_count(name, params):
    """e x n_stories, from the nominal parameters, the way SPEC.md §4.1 derives it."""
    scenario = resolved(name, params)
    e = model.escape_rate(
        model.escape_gate(scenario["d"], scenario["rho"], scenario["m"]),
        scenario["f_base"], params["q_rev"])
    return e * sum(scenario["n_stories"].values())


@pytest.mark.parametrize("name", SCENARIOS)
def test_covariance_correction_is_exact(name, params):
    """§5, part 1 of the mandatory property test. gamma, to 1e-10, with no sampling in it.

    model.covariance_correction computes gamma by Cameron-Martin, which removes the
    exponential from the integrand analytically. This recomputes it the other way — direct
    quadrature of E[e_base x e_scale] / E[e_base] with the exponential left in — so the two
    routes are genuinely independent. This is where the precision lives: Monte Carlo can
    only bound the same property to about 1%, against a defect of 2.0-2.7%.
    """
    scenario = resolved(name, params)
    nodes, weights = np.polynomial.hermite_e.hermegauss(96)
    weights = weights / weights.sum()

    f_base, q_rev = scenario["f_base"], params["q_rev"]
    if f_base <= 0.0:
        f_run = np.zeros_like(nodes)
    else:
        f_run = model.logistic(model.logit(f_base) - params["lambda_f"] * nodes)
    review_factor = f_run + (1.0 - f_run) * q_rev
    e_scale = np.exp(params["lambda_e"] * nodes - 0.5 * params["lambda_e"] ** 2)

    expected = (f_base + (1.0 - f_base) * q_rev) / float((weights * review_factor
                                                          * e_scale).sum())
    assert model.covariance_correction(params, scenario) == pytest.approx(
        expected, rel=1e-10)


@pytest.mark.parametrize("name", ("execute_only", "execute_decide"))
def test_correction_is_exactly_one_where_there_is_no_covariance(name, params):
    """§5: with f = 0, e_base does not depend on theta, so there is nothing to correct.

    Exactly 1.0, not approximately: A and B's pinned figures must not be able to move.
    """
    assert model.covariance_correction(params, resolved(name, params)) == 1.0


@pytest.mark.parametrize("name", SCENARIOS)
def test_simulated_mean_escape_count_matches_the_derived_rate(name, params):
    """§5, part 2. Realised mean escapes = e x n_stories, end to end, to 1%.

    Catches the whole class of Jensen-bias errors — uncentred exp(lambda_e x theta), a
    cluster multiplier applied only on the clustered branch, a lognormal without its
    -sigma^2/2, and the e_base/e_scale covariance. The first two together inflated the
    escape rate by 51% (REVIEW.md S1-1).

    1% is about 3.5 standard errors at 200,000 iterations: the escape count is 2.9x to
    21.7x over-dispersed relative to binomial, so its sampling error is around 0.3%
    relative. The bound is stable across seeds rather than merely on this one. The exact
    check on gamma above is what pins the correction; this catches wiring errors that a
    check on gamma alone would miss — a correct gamma applied to the wrong factor, or
    dropped on one code path.
    """
    result = montecarlo.run_scenario(name, params, iterations=200_000, seed=11)
    assert result["mean_escaped"] == pytest.approx(
        derived_escape_count(name, params), rel=0.01)


@pytest.mark.parametrize("name", SCENARIOS)
def test_mean_escape_is_exact_once_the_gate_coupling_is_removed(name, params):
    """§5: with lambda_f = 0, theta no longer moves f, so the covariance term vanishes.

    This isolates the Jensen-bias class exactly, for every scenario including the gated
    ones, and holds the implementation to 0.5% rather than to the 3% the covariance forces.
    """
    uncoupled = params_module.apply_overrides(params, {"lambda_f": 0.0})
    assert model.covariance_correction(uncoupled, resolved(name, uncoupled)) == \
        pytest.approx(1.0, rel=1e-12)
    result = montecarlo.run_scenario(name, uncoupled, iterations=200_000, seed=11)
    assert result["mean_escaped"] == pytest.approx(
        derived_escape_count(name, uncoupled), rel=0.01)


@pytest.mark.parametrize("name", SCENARIOS)
def test_percentiles_are_ordered(name, params):
    """§10: P50 <= P80 <= P95, for the total and for every component."""
    result = montecarlo.run_scenario(name, params, iterations=4000, seed=3)
    for component, pct in result["percentiles"].items():
        assert pct["p50"] <= pct["p80"] <= pct["p95"], component


def test_identical_seeds_give_identical_results(params):
    """CLAUDE.md §2: two runs with the same seed and parameters agree exactly."""
    first = montecarlo.run_scenario("all_three", params, iterations=2000, seed=5)
    second = montecarlo.run_scenario("all_three", params, iterations=2000, seed=5)
    assert first["percentiles"] == second["percentiles"]
    assert first["mean_escaped"] == second["mean_escaped"]


def test_different_seeds_give_different_results(params):
    """A seed that changes nothing would mean the draws are not being used."""
    first = montecarlo.run_scenario("all_three", params, iterations=2000, seed=5)
    second = montecarlo.run_scenario("all_three", params, iterations=2000, seed=6)
    assert first["percentiles"]["total"]["p95"] != second["percentiles"]["total"]["p95"]


def test_no_mean_is_reported_for_a_cost(params):
    """CLAUDE.md §6: the distribution is right-skewed, so a single summary cost is wrong."""
    result = montecarlo.run_scenario("all_three", params, iterations=2000, seed=5)
    for component, pct in result["percentiles"].items():
        assert set(pct) == {"p50", "p80", "p95"}, component


def test_epistemic_and_aleatory_uncertainty_are_independently_switchable(params):
    """§3.5: parameter uncertainty and the repo common factor are different quantities."""
    full = montecarlo.run_scenario("all_three", params, iterations=20_000, seed=7)
    aleatory = montecarlo.run_scenario("all_three", params, iterations=20_000, seed=7,
                                       uncertainty="aleatory")
    assert aleatory["percentiles"]["total"]["p95"] < full["percentiles"]["total"]["p95"]
    # §6: parameter uncertainty adds under 2% to D's P95, because correlated escape already
    # dominates. A result worth reporting rather than assuming.
    ratio = full["percentiles"]["total"]["p95"] / aleatory["percentiles"]["total"]["p95"]
    assert 1.0 < ratio < 1.05


def test_switching_all_uncertainty_off_reproduces_the_deterministic_pass(params):
    """§6: 'variance switched off' must mean the deterministic pass, not something near it."""
    result = montecarlo.run_scenario("all_three", params, iterations=1, seed=7,
                                     uncertainty="none")
    direct = model.deterministic_run(params, resolved("all_three", params))
    assert result["percentiles"]["total"]["p50"] == pytest.approx(direct["total_cost"])


# ======================================================================================
# SPEC.md §5 — variance decomposition, on genuinely random sources only
# ======================================================================================


def test_escape_dominates_the_variance(params):
    """§5: freezing escape removes ~72% of the P50->P95 spread; all else is under 2%."""
    result = montecarlo.run_scenario("all_three", params, iterations=20_000, seed=7,
                                     decompose=True)
    shares = result["variance"]
    assert shares["escape"] > 0.55
    for source, share in shares.items():
        if source != "escape":
            assert share < 0.10, f"{source} should be individually small, got {share:.3f}"


def test_no_constant_appears_as_a_variance_share(params):
    """§5: a constant contributes zero variance, so batching and policy must not be listed.

    REVIEW.md S3-1: earlier versions reported 'batching 20%' and 'criteria hours 19%' for
    quantities the model held fixed. Those are one-at-a-time sensitivities, a different and
    also useful thing, reported under that name in a separate table.
    """
    result = montecarlo.run_scenario("all_three", params, iterations=4000, seed=7,
                                     decompose=True)
    forbidden = {"b", "batching", "batch_size", "spec", "criteria_hours",
                 "architecture", "restructure_fraction"}
    assert not (forbidden & set(result["variance"]))


def test_variance_shares_are_not_presented_as_a_partition(params):
    """§5: the model is non-linear, so freeze-one-at-a-time reductions do not sum to 100%."""
    result = montecarlo.run_scenario("all_three", params, iterations=4000, seed=7,
                                     decompose=True)
    assert result["variance_is_partition"] is False


# ======================================================================================
# SPEC.md §10 — outputs
# ======================================================================================


@pytest.mark.parametrize("name", SCENARIOS)
def test_result_carries_everything_the_report_needs(name, params):
    """§10: report.py computes nothing, so every reported number arrives in the result."""
    result = montecarlo.run_scenario(name, params, iterations=2000, seed=7, decompose=True)
    for key in ("scenario", "label", "percentiles", "e", "mean_escaped", "mean_fallback",
                "token_share", "fte", "variance", "iterations", "seed", "deterministic"):
        assert key in result, f"{name} result is missing {key}"
    for component in ("total", "tokens", "criteria", "review", "incident", "spec",
                      "switch", "fallback", "restructure"):
        assert component in result["percentiles"], component


@pytest.mark.parametrize("name", SCENARIOS)
def test_result_exposes_no_numpy_arrays(name, params):
    """CLAUDE.md §10: Result exposes plain floats and dicts so report.py never sees an array."""
    result = montecarlo.run_scenario(name, params, iterations=1000, seed=7, decompose=True)

    def check(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                check(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                check(item, f"{path}[{index}]")
        else:
            assert isinstance(value, (int, float, str, bool, type(None))), \
                f"{path} is {type(value).__name__}, not a plain value"

    check(result, name)


def test_fte_is_reported_so_the_saving_is_not_misread(params):
    """§9: the saving is a headcount reduction at roughly constant duration."""
    result = montecarlo.run_scenario("all_three", params, iterations=1000, seed=7)
    expected = result["deterministic"]["hours"]["total"] / (
        params["calendar_weeks"] * params["hours_per_fte_week"])
    assert result["fte"] == pytest.approx(expected)


def test_run_all_covers_the_five_scenarios(params):
    """§6: five scenarios, matching the briefing set's A / B / C / D / D+ exactly."""
    results = montecarlo.run_all(params, iterations=1000, seed=7)
    assert tuple(results) == SCENARIOS


# ======================================================================================
# CLAUDE.md §8 — no silent fallbacks
# ======================================================================================


def test_unknown_scenario_raises(params):
    with pytest.raises(KeyError):
        montecarlo.run_scenario("execute_everything", params, iterations=10, seed=1)


def test_unknown_parameter_raises(params):
    with pytest.raises(KeyError):
        params_module.apply_overrides(params, {"lambda_q": 0.5})


def test_unknown_uncertainty_mode_raises(params):
    with pytest.raises(ValueError):
        montecarlo.run_scenario("all_three", params, iterations=10, seed=1,
                                uncertainty="some")


def test_impossible_cluster_pair_raises(params):
    """§5: no mean-preserving pair exists once p_cluster x cluster_mult reaches 1."""
    with pytest.raises(ValueError):
        params_module.apply_overrides(params, {"p_cluster": 0.5, "cluster_mult": 3.0})


# ======================================================================================
# SPEC.md §2 — units and conventions
# ======================================================================================


@pytest.mark.parametrize("name", SCENARIOS)
def test_token_cost_is_exactly_tokens_times_price(name, deterministic, params):
    """§2: tokens stay whole inside the model; the conversion happens at the boundary."""
    result = deterministic[name]
    assert result["token_cost"] == pytest.approx(
        result["total_tokens"] * params["c"] / 1e6, rel=1e-12)
    assert result["total_tokens"] > 1e8      # whole tokens, not millions-of-tokens shorthand


@pytest.mark.parametrize("name", SCENARIOS)
def test_probabilities_are_fractions(name, deterministic):
    """§2: probabilities are fractions in [0, 1], never percentages."""
    result = deterministic[name]
    assert 0.0 <= result["e"] <= 1.0
    assert 0.0 <= result["e_gate"] <= 1.0
    assert result["e"] <= result["e_gate"]      # review can only ever help
    assert 0.0 <= result["token_share"] <= 1.0


@pytest.mark.parametrize("name", SCENARIOS)
def test_generation_and_apparatus_sum_to_total_tokens(name, deterministic):
    """§4.3: total = generation x k_scale + apparatus, and all five apparatus lines count."""
    result = deterministic[name]
    assert result["total_tokens"] == pytest.approx(
        result["generation_tokens"] + result["apparatus_tokens"])


@pytest.mark.parametrize("name", ("execute_deliver", "all_three", "all_three_quality"))
def test_step_ten_consumes_tokens_wherever_it_is_active(name, params):
    """§4.3: repo_scope is a real token line, not zero (REVIEW.md S2-1)."""
    scenario = resolved(name, params)
    assert scenario["apparatus_tokens"]["repo_scope"] > 0.0


def test_step_ten_consumes_nothing_where_it_is_inactive(params):
    for name in ("execute_only", "execute_decide"):
        assert resolved(name, params)["apparatus_tokens"]["repo_scope"] == 0.0


def test_cost_is_monotonic_in_story_count(params):
    """Arithmetic, not spec text: more stories cannot cost less."""
    scenario_name = "all_three"
    costs = []
    for n in (10, 40, 80):
        widened = params_module.apply_overrides(
            params, {"n_routine": n, "n_standard": n, "n_hard": n})
        costs.append(model.deterministic_run(
            widened, resolved(scenario_name, widened))["total_cost"])
    assert costs == sorted(costs)


def test_hard_stories_carry_most_of_the_token_mass(params):
    """§4.2: which is why truncation matters, and why Hard-class p is the number to measure."""
    scenario = resolved("all_three", params)
    per_class = {}
    for cls in ("routine", "standard", "hard"):
        per_class[cls] = (scenario["n_stories"][cls] * scenario["N_impl"][cls]
                          * scenario["k"][cls]
                          * model.expected_attempts(scenario["p"][cls], params["A_max"]))
    assert per_class["hard"] > 0.5 * sum(per_class.values())


def test_no_free_escape_parameter_exists():
    """CLAUDE.md §6: e is derived in two stages and never entered directly."""
    assert "e" not in params_module.PARAMS
    assert "e_gate" not in params_module.PARAMS
    assert "escape_rate" not in params_module.PARAMS
    # Both stages survive as named intermediates, for a reader checking the arithmetic.
    assert math.isclose(
        model.escape_rate(model.escape_gate(0.24, 0.05, 0.06), 0.90, 0.35), 0.024011,
        abs_tol=1e-6)
