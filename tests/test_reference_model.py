"""Differential check against the *supplied* reference, ``reference_model.py``.

That file ships with the repository as the artefact that generated the published figures. It
is a second independent implementation — written before this one, structured differently,
with its own draw order — so agreement between the two is real evidence rather than a
tautology. It is deliberately not imported by any source module.

This is a different check from ``tests/reference.py``, which is a slow nested-loop rewrite of
*this* model. Together they triangulate: one confirms the vectorisation, the other confirms
the model.

**The deterministic pass must agree exactly**, to floating-point rounding, on every figure.
There is no sampling in it, so anything else is a discrepancy in the arithmetic.

**The Monte Carlo pass agrees only to Monte Carlo error, and only where gamma is 1.** The two
implementations consume their random streams in different orders, so identical seeds do not
produce identical draws. Beyond that, the supplied reference predates the SPEC.md §5
covariance correction and so still carries that defect: its escape rate runs 1.95% to 2.71%
below its own derived e in the three gated scenarios. This build is expected to read higher
there, and ``test_the_supplied_reference_carries_the_covariance_defect`` checks that the
reference really does have the defect rather than assuming it.
"""

from __future__ import annotations

import importlib.util
import pathlib

import numpy as np
import pytest

import model
import montecarlo
import params as params_module
import scenarios

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_supplied_reference():
    spec = importlib.util.spec_from_file_location("reference_model",
                                                  ROOT / "reference_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reference_model = _load_supplied_reference()

# The supplied reference keys scenarios by briefing letter; this build keys them by which
# steps are active. Same five scenarios (SPEC.md §6).
BY_LETTER = {"A": "execute_only", "B": "execute_decide", "C": "execute_deliver",
             "D": "all_three", "D+": "all_three_quality"}


@pytest.fixture(scope="module")
def params():
    return params_module.default_params()


def _mine(name, params):
    return model.deterministic_run(params, scenarios.resolve_scenario(name, params))


@pytest.mark.parametrize("letter,name", list(BY_LETTER.items()))
def test_deterministic_pass_agrees_exactly(letter, name, params):
    """Every deterministic figure, to floating-point rounding. No sampling is involved."""
    theirs = reference_model.deterministic(letter)
    mine = _mine(name, params)

    comparisons = {
        "total hours": (mine["hours"]["total"], theirs["hours"]),
        "total cost": (mine["total_cost"], theirs["cost"]),
        "human cost": (mine["human_cost"], theirs["cost"] - theirs["tok_cost"]),
        "total tokens": (mine["total_tokens"], theirs["tokens"]),
        "token cost": (mine["token_cost"], theirs["tok_cost"]),
        "escape rate": (mine["e"], theirs["e"]),
        "fallback stories": (mine["n_fallback"], theirs["fb"]),
        "reviewed stories": (mine["n_reviewed"], theirs["reviewed"]),
        "criteria hours": (mine["hours"]["criteria"], theirs["criteria"]),
        "review hours": (mine["hours"]["review"], theirs["review"]),
        "switch hours": (mine["hours"]["switch"], theirs["switch"]),
        "restructure hours": (mine["hours"]["restructure"], theirs["restr"]),
        "incident hours": (mine["hours"]["incident"], theirs["incid"]),
        "fallback hours": (mine["hours"]["fallback"], theirs["fb_h"]),
        "spec hours": (mine["hours"]["spec"], theirs["spec"]),
        "architecture hours": (mine["hours"]["architecture"], theirs["arch"]),
    }
    for label, (ours, reference) in comparisons.items():
        assert ours == pytest.approx(reference, rel=1e-12), f"{letter} {label}"


@pytest.mark.parametrize("letter,name", list(BY_LETTER.items()))
def test_the_supplied_reference_selects_the_same_primitives(letter, name, params):
    """The escape primitives this build *derives* from steps, that one declares by hand.

    reference_model.py writes d, rho, m and f into a per-scenario table. This build derives
    them from which of the ten steps are active (CLAUDE.md §8 forbids the table). They must
    come out the same, which is what makes the derivation trustworthy rather than merely
    tidier.
    """
    theirs = reference_model.SCEN[letter]
    mine = scenarios.resolve_scenario(name, params)
    assert mine["d"] == pytest.approx(theirs["d"])
    assert mine["rho"] == pytest.approx(theirs["rho"])
    assert mine["m"] == pytest.approx(theirs["m"])
    assert mine["f_base"] == pytest.approx(theirs["f"])
    assert mine["S"] == pytest.approx(theirs["S"])
    assert mine["R"] == pytest.approx(theirs["R"])
    assert mine["N_impl"] == theirs["N"]
    assert mine["p"] == pytest.approx(theirs["p"])
    assert mine["spec_hours"] == pytest.approx(theirs["spec_h"])
    assert mine["architecture_hours"] == pytest.approx(theirs["arch_h"])


@pytest.mark.parametrize("letter,name", list(BY_LETTER.items()))
def test_apparatus_token_lines_agree(letter, name, params):
    """All five apparatus lines, including the repo_scope one REVIEW.md S2-1 added."""
    theirs = reference_model.SCEN[letter]["app"]
    mine = scenarios.resolve_scenario(name, params)["apparatus_tokens"]
    assert mine["decide"] == pytest.approx(theirs["decide"])
    assert mine["oracle"] == pytest.approx(theirs["oracle"])
    assert mine["crosstest"] == pytest.approx(theirs["cross"])
    assert mine["integration"] == pytest.approx(theirs["integ"])
    assert mine["repo_scope"] == pytest.approx(theirs["repo"])


def test_the_batch_size_matches(params):
    """b = 6, which SPEC.md §3.3 omitted and this build recovered from A's pinned hours."""
    assert params["b"] == reference_model.BATCH


def test_the_attempt_cap_and_truncation_match(params):
    assert params["A_max"] == reference_model.A_MAX
    for p in (0.28, 0.40, 0.45, 0.65, 0.92):
        assert model.expected_attempts(p, params["A_max"]) == pytest.approx(
            reference_model.E_trunc(p), rel=1e-12)


def test_the_escape_equation_matches():
    """Two stages here, one expression there. Same number."""
    for d, rho, m, f, q in ((0.30, 0.70, 0.30, 0.00, 0.35),
                            (0.24, 0.05, 0.06, 0.90, 0.35),
                            (0.24, 0.02, 0.02, 0.90, 0.35)):
        mine = model.escape_rate(model.escape_gate(d, rho, m), f, q)
        assert mine == pytest.approx(reference_model.e_from(d, rho, m, f, q), rel=1e-12)


@pytest.mark.parametrize("letter,name", list(BY_LETTER.items()))
@pytest.mark.parametrize("epistemic,uncertainty", [(True, "full"), (False, "aleatory")])
def test_monte_carlo_agrees_to_sampling_error(letter, name, epistemic, uncertainty, params):
    """P50 and P95, with a bound that depends on whether the correction applies.

    **The supplied reference does not carry the SPEC.md §5 covariance correction.** It was
    written before that defect was found, so its escape rate runs 1.95% to 2.71% below its
    own derived e in any scenario with a gate. This build is therefore *expected* to read
    slightly higher there, and the test says so rather than hiding it in a loose bound.

    Where gamma is 1 — A and B, which have f = 0 — the two implementations are the same
    model and agree to sampling error alone. The two draw in different orders, so identical
    seeds give different draws; measured divergence is under 1.2%, worst on A's P95, the
    fattest tail in the set and so exactly where sampling error is largest.
    """
    theirs = reference_model.simulate(letter, iters=40_000, seed=7, epistemic=epistemic)
    reference_p50, reference_p95 = np.percentile(theirs["cost"], [50, 95])

    mine = montecarlo.run_scenario(name, params, iterations=40_000, seed=7,
                                   uncertainty=uncertainty)
    gamma = model.covariance_correction(params, scenarios.resolve_scenario(name, params))

    if gamma == 1.0:
        assert mine["percentiles"]["total"]["p50"] == pytest.approx(reference_p50, rel=0.02)
        assert mine["percentiles"]["total"]["p95"] == pytest.approx(reference_p95, rel=0.02)
        return

    # Gated scenarios: the correction can only raise the escape rate, so this build must sit
    # at or above the reference, and close to it. The gap is bounded by what the correction
    # is worth on the incident line, which is the only line it touches.
    assert mine["percentiles"]["total"]["p50"] >= reference_p50 * 0.995, (
        "the correction raises escapes, so the corrected model cannot read lower")
    assert mine["percentiles"]["total"]["p50"] == pytest.approx(reference_p50, rel=0.035)
    assert mine["percentiles"]["total"]["p95"] == pytest.approx(reference_p95, rel=0.035)


@pytest.mark.parametrize("letter,name", list(BY_LETTER.items()))
def test_the_supplied_reference_carries_the_covariance_defect(letter, name, params):
    """Confirms the reference really does have the defect, rather than assuming it.

    Its simulated mean escape rate is compared against the e it derives itself. A and B come
    out clean because f = 0 leaves no covariance; C, D and D+ come out 2-3% low. If this
    ever stops being true the reference has been changed, and the looser bound above is no
    longer justified.
    """
    theirs = reference_model.simulate(letter, iters=200_000, seed=11, epistemic=False)
    derived = reference_model.deterministic(letter)["e"]
    ratio = float(np.mean(theirs["e_run"])) / derived

    gamma = model.covariance_correction(params, scenarios.resolve_scenario(name, params))
    if gamma == 1.0:
        assert ratio == pytest.approx(1.0, rel=0.01), letter
    else:
        assert ratio < 0.99, f"{letter} should show the defect, ratio {ratio:.4f}"
        assert ratio == pytest.approx(1.0 / gamma, rel=0.01), letter
