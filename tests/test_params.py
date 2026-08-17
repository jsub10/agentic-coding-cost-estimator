"""Provenance discipline. A parameter with no source is a bug (CLAUDE.md §5)."""

from __future__ import annotations

import pytest

import params as params_module
import scenarios


def all_records():
    """Every record in the project: the global registry and per-scenario POLICY."""
    yield from params_module.iter_params()
    yield from scenarios.iter_scenario_params()


@pytest.mark.parametrize("name,spec", list(all_records()))
def test_every_parameter_has_a_source(name, spec):
    assert spec["source"], f"{name} has no source; see CLAUDE.md §5"
    assert len(spec["source"]) > 20, f"{name}'s source is too thin to be provenance"


@pytest.mark.parametrize("name,spec", list(all_records()))
def test_every_parameter_declares_a_valid_kind(name, spec):
    assert spec["kind"] in params_module.KINDS, name


@pytest.mark.parametrize("name,spec", list(all_records()))
def test_every_parameter_has_a_range_containing_its_default(name, spec):
    assert spec["low"] <= spec["value"] <= spec["high"], name
    assert spec["low"] < spec["high"], f"{name} has an empty range"


@pytest.mark.parametrize("name,spec", list(all_records()))
def test_every_parameter_has_a_unit_and_a_doc(name, spec):
    assert spec["unit"], name
    assert spec["doc"], name


def test_calibrated_values_are_marked_as_placeholders():
    """SPEC.md §3.3: the shipped calibrated values must not be mistaken for measurements."""
    calibrated = [name for name, spec in params_module.iter_params()
                  if spec["kind"] == "CALIBRATED"]
    assert len(calibrated) > 20
    import report
    assert "illustrative placeholders" in report.CAVEATS


def test_prices_are_the_only_organisational_facts():
    prices = {name for name, spec in params_module.iter_params()
              if spec["kind"] == "PRICE"}
    assert prices == {"w", "w_inc", "c"}


def test_epistemic_parameters_are_exactly_the_five_of_spec_3_5():
    epistemic = {name for name, spec in params_module.iter_params()
                 if spec["kind"] == "EPISTEMIC"}
    assert epistemic == {"sigma_d", "sigma_m", "sd_q_rev", "sigma_S", "sigma_k_scale"}


def test_registry_is_not_mutable_through_its_accessors():
    """CLAUDE.md §8: no global mutable state, so no accessor hands out a live reference."""
    spec = params_module.param_spec("w")
    spec["value"] = 999.0
    assert params_module.param_spec("w")["value"] == 150.0

    values = params_module.default_params()
    values["w"] = 999.0
    assert params_module.default_params()["w"] == 150.0

    policy = scenarios.default_scenario_policy()
    policy["all_three"]["rho"] = 0.99
    assert scenarios.default_scenario_policy()["all_three"]["rho"] == 0.05


def test_overrides_do_not_mutate_the_input():
    base = params_module.default_params()
    params_module.apply_overrides(base, {"w": 200.0})
    assert base["w"] == 150.0


def test_unknown_names_raise_rather_than_defaulting():
    """CLAUDE.md §8: no silent fallbacks."""
    with pytest.raises(KeyError):
        params_module.param_spec("wages")
    with pytest.raises(KeyError):
        params_module.apply_overrides(params_module.default_params(), {"wages": 1})
    with pytest.raises(KeyError):
        scenarios.scenario_label("execute_everything")
    with pytest.raises(KeyError):
        scenarios.scenario_policy_spec("all_three", "orcale_tokens")


def test_scenario_override_requires_a_scenario_prefix():
    with pytest.raises(ValueError):
        scenarios.apply_scenario_overrides(
            scenarios.default_scenario_policy(), {"oracle_tokens": 1.0})


def test_integer_parameters_refuse_a_fractional_override():
    """Truncating would make a published total irreproducible from the stated parameter."""
    for name in ("A_max", "b", "n_routine", "n_compare_min"):
        with pytest.raises(ValueError):
            params_module.coerce(name, 2.5)


def test_scenarios_are_declared_as_steps_not_as_copied_numbers():
    """CLAUDE.md §8: a scenario is a set of active steps, and its parameters follow."""
    for name in scenarios.scenario_names():
        assert name in scenarios.SCENARIO_STEPS
        for step in scenarios.SCENARIO_STEPS[name]:
            assert step in scenarios.STEPS


def test_the_step_table_matches_spec_6():
    """SPEC.md §6's tick table, transcribed and checked."""
    expected = {
        "execute_only": set(),
        "execute_decide": {1, 2, 3, 4},
        "execute_deliver": {1, 4, 5, 6, 7, 8, 9, 10},
        "all_three": {1, 2, 3, 4, 5, 6, 7, 8, 9, 10},
        "all_three_quality": {1, 2, 3, 4, 5, 6, 7, 8, 9, 10},
    }
    for name, steps in expected.items():
        assert set(scenarios.SCENARIO_STEPS[name]) == steps, name
    # D+ differs from D only by running Steps 6 and 7 deeper, SPEC.md §6's double tick.
    deeper = scenarios.SCENARIO_STEPS["all_three_quality"]
    assert deeper[6] == 2 and deeper[7] == 2
    assert scenarios.SCENARIO_STEPS["all_three"][6] == 1


def test_rho_menu_has_no_human_review_row():
    """REVIEW.md S3-3: review enters through q_rev only, or it is discounted twice."""
    for key, (_value, description) in scenarios.RHO_MENU.items():
        assert "human" not in description.lower(), key
        assert "human" not in key
    # self_review is the model checking its own work, which is a rho mechanism and stays.
    assert "self_review" in scenarios.RHO_MENU


def test_rho_choices_come_from_the_menu():
    """SPEC.md §3.6: rho is read off the menu, not invented per scenario."""
    menu = {value for value, _ in scenarios.RHO_MENU.values()}
    for name in scenarios.scenario_names():
        assert scenarios.SCENARIO_POLICY[name]["rho"] in menu, name


def test_step_ten_is_the_only_source_of_repo_scope_tokens():
    """REVIEW.md S2-1: non-zero wherever Step 10 is active, zero where it is not."""
    for name in scenarios.scenario_names():
        active = 10 in scenarios.SCENARIO_STEPS[name]
        tokens = scenarios.SCENARIO_POLICY[name]["repo_scope_tokens"]
        assert (tokens > 0) == active, name
