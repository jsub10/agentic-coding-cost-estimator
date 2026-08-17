"""Scenarios — declared as which of the ten process steps are active, never by copying.

CLAUDE.md §8 forbids adding a scenario by copying another and editing numbers. So a scenario
here is a set of active steps with an intensity, and every parameter that distinguishes one
scenario from another either *follows* from those steps (``resolve_scenario`` below) or is a
per-scenario POLICY declared with its own provenance in ``SCENARIO_POLICY``.

The five scenarios match the briefing set's A / B / C / D / D+ exactly (SPEC.md §6):

=========================  ===================================================
``execute_only``           A. Code generation only. Humans write every
                           criterion and read every diff.
``execute_decide``         B. Adds the Decide phase — spec oracles, source
                           conformance, completeness sweeps.
``execute_deliver``        C. Adds the Deliver phase instead — frozen
                           acceptance suites, mutation scoring, independent
                           oracles, cross-implementation comparison, a gate.
``all_three``              D. Both.
``all_three_quality``      D+. Both, spending more tokens on verification
                           depth rather than on displacing human hours.
=========================  ===================================================

**B and C are the two single-phase additions to A**, and running both is what makes each
phase's marginal contribution visible. The sharpest comparison in the set is B against C: B
has better criteria and still a high escape rate, because automating Decide does not freeze
the acceptance suite, so the check stays co-derived with the implementation. Better
specifications alone do not buy independence.

Depends on ``params`` only, and nothing here formats output (CLAUDE.md §3).
"""

from __future__ import annotations

from params import CLASSES, param_record, param_spec

# --- The ten steps, SPEC.md §7 --------------------------------------------------------
# Each step either changes a parameter or adds a cost term. The third column names the
# effect so that a reader can trace any row of SPEC.md §7 into resolve_scenario below.

STEPS = {
    1: ("System specification", "Lowers k and raises p; adds spec_hours."),
    2: ("Criteria vs governing sources", "d_base -> d_specced; S_manual -> S_oracled; "
                                         "adds decide tokens."),
    3: ("Completeness sweep", "Folded into the Step 2 effect on d and S; adds the "
                              "adjudication touch."),
    4: ("Program design and slicing", "Contributes to the d reduction and to reuse; "
                                      "deliberately not separately parameterised."),
    5: ("Frozen acceptance suite", "Collapses rho; switches k and p to their frozen tables."),
    6: ("Mutation scoring + different route", "m_unscored -> m_scored -> m_deep; lowers rho "
                                              "further; adds oracle tokens."),
    7: ("N implementations, compared", "Sets N_impl; multiplies generation tokens; adds "
                                       "crosstest tokens and the adjudication touch."),
    8: ("Tiered gate", "Sets f_base; R_large -> R_gated."),
    9: ("Integration verification", "Adds integration tokens; caps WIP (reported, not costed)."),
    10: ("Repo-scope gates", "Adds repo-scope tokens and the restructuring reserve."),
}

# Intensity 2 means the step is run deeper, SPEC.md §6's double tick. Only D+ uses it, on
# Step 6 (deeper mutation and formal methods) and Step 7 (more implementations).
SCENARIO_STEPS: dict[str, dict[int, int]] = {
    "execute_only": {},
    "execute_decide": {1: 1, 2: 1, 3: 1, 4: 1},
    "execute_deliver": {1: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1},
    "all_three": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1},
    "all_three_quality": {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 1, 9: 1, 10: 1},
}

SCENARIO_LABELS = {
    "execute_only": "A. Execute only",
    "execute_decide": "B. Execute + Decide",
    "execute_deliver": "C. Execute + Deliver",
    "all_three": "D. Decide + Execute + Deliver",
    "all_three_quality": "D+. All three, quality maximised",
}

# The baseline every saving is quoted against (SPEC.md §6).
BASELINE = "execute_only"

# The five apparatus token lines of SPEC.md §4.3. repo_scope is the fifth, added by
# REVIEW.md S2-1 — without it Step 10 consumed no tokens and D+ could not reconcile.
APPARATUS_LINES = ("decide", "oracle", "crosstest", "integration", "repo_scope")

# --- The rho menu, SPEC.md §3.6 -------------------------------------------------------
# rho is the fraction of implementation errors the check is blind to *by construction*. It
# is not measured — estimating it empirically would require observing implementations
# checked against oracles co-derived with them, and Step 5 exists to guarantee that case
# never arises. It is read off this menu instead. Note there is no human-review row:
# REVIEW.md S3-3 removed it, because review enters the chain through q_rev only and
# counting it here as well would discount it twice.

RHO_MENU = {
    "self_review": (0.70, "Same model, same context, self-review"),
    "fresh_context": (0.50, "Same model, fresh context"),
    "adversarial": (0.40, "Different model, adversarial prompt"),
    "frozen_suite": (0.20, "Frozen acceptance suite + isolated contexts"),
    "different_route": (0.05, "The above + at least one check from a different derivation route"),
    "formal_methods": (0.02, "The above + formal methods on critical paths"),
}

# --- Per-scenario POLICY, SPEC.md §6 --------------------------------------------------
# Provenance is declared once per policy name, because the source is the same table for
# every scenario; the values then sit in one readable block per scenario. Composed into
# full records by scenario_policy_spec().

_POLICY_META = {
    "rho": ("SPEC.md §6 parameter table, read off the §3.6 rho menu.", 0.0, 1.0, "fraction",
            "Fraction of implementation errors the check is blind to by construction."),
    "f_base": ("SPEC.md §6 parameter table; set by Step 8. Before the gate is running this "
               "is a policy target, and afterwards the observed auto-merge fraction (§8).",
               0.0, 1.0, "fraction",
               "Auto-merge fraction. Raising it *raises* the escape rate for a fixed "
               "e_gate, because it removes the second filter."),
    "spec_hours": ("SPEC.md §6 parameter table. Amortised system-specification effort.",
                   0.0, 2000.0, "hours", "System specification and architecture, amortised."),
    "architecture_hours": ("SPEC.md §6 parameter table. A separate line from switch cost: "
                           "REVIEW.md S2-2 found two documents disagreeing about which of "
                           "the two the total contained, because they are the same size at "
                           "the defaults.", 0.0, 2000.0, "hours", "Architecture decisions."),
    "decide_tokens": ("SPEC.md §6 parameter table; Step 2 apparatus.", 0.0, 1.0e11, "tokens",
                      "Source conformance, completeness sweeps, precedent checks."),
    "oracle_tokens": ("SPEC.md §6 parameter table; Step 6 apparatus.", 0.0, 1.0e11, "tokens",
                      "Oracle construction, mutation scoring, formal methods."),
    "crosstest_tokens": ("SPEC.md §6 parameter table; Step 7 apparatus.", 0.0, 1.0e11, "tokens",
                         "Cross-testing N implementations against each other."),
    "integration_tokens": ("SPEC.md §6 parameter table; Step 9 apparatus.", 0.0, 1.0e11,
                           "tokens", "Integration verification across stories."),
    "repo_scope_tokens": ("SPEC.md §6 parameter table; Step 10 apparatus. Added by "
                          "REVIEW.md S2-1, which found Step 10 consuming no tokens in any "
                          "scenario — the reason D+ could not reconcile from its own "
                          "parameters.", 0.0, 1.0e11, "tokens",
                          "Repository-wide duplication sweeps, conformance graph queries, "
                          "change amplification, the weekly trend basket."),
}

_N_IMPL_META = ("SPEC.md §6 parameter table; set by Step 7. Costs tokens and buys nothing in "
                "the escape equation — SPEC.md §7 states plainly that best-of-N selection "
                "and ambiguity detection are unmodelled, so the model understates D+.",
                1, 20, "implementations",
                "Independent implementations generated per story, run in isolated contexts.")

SCENARIO_POLICY: dict[str, dict[str, float]] = {
    "execute_only": {
        "rho": 0.70, "f_base": 0.00,
        "spec_hours": 0.0, "architecture_hours": 40.0,
        "N_impl_routine": 1, "N_impl_standard": 1, "N_impl_hard": 1,
        "decide_tokens": 0.0, "oracle_tokens": 0.0, "crosstest_tokens": 0.0,
        "integration_tokens": 0.0, "repo_scope_tokens": 0.0,
    },
    "execute_decide": {
        # rho stays at 0.70. Automating Decide does not freeze the acceptance suite, so the
        # check remains co-derived with the implementation. This is the model's sharpest
        # structural statement (SPEC.md §6).
        "rho": 0.70, "f_base": 0.00,
        "spec_hours": 40.0, "architecture_hours": 40.0,
        "N_impl_routine": 1, "N_impl_standard": 1, "N_impl_hard": 1,
        "decide_tokens": 600.0e6, "oracle_tokens": 0.0, "crosstest_tokens": 0.0,
        "integration_tokens": 0.0, "repo_scope_tokens": 0.0,
    },
    "execute_deliver": {
        "rho": 0.05, "f_base": 0.85,
        "spec_hours": 80.0, "architecture_hours": 40.0,
        "N_impl_routine": 1, "N_impl_standard": 2, "N_impl_hard": 2,
        "decide_tokens": 0.0, "oracle_tokens": 592.0e6, "crosstest_tokens": 296.0e6,
        "integration_tokens": 120.0e6, "repo_scope_tokens": 200.0e6,
    },
    "all_three": {
        "rho": 0.05, "f_base": 0.90,
        "spec_hours": 80.0, "architecture_hours": 10.0,
        "N_impl_routine": 1, "N_impl_standard": 2, "N_impl_hard": 3,
        "decide_tokens": 600.0e6, "oracle_tokens": 760.0e6, "crosstest_tokens": 368.0e6,
        "integration_tokens": 150.0e6, "repo_scope_tokens": 250.0e6,
    },
    "all_three_quality": {
        # The oracle line carries the formal-methods and deeper-mutation spend; the
        # repo-scope line carries the repository-wide duplication sweep and drift-driven
        # refactor proposals. Together: generation 2,557M + apparatus 7,878M = 10,435M,
        # which is the pinned 10.44B. An earlier version declared 4,200M of apparatus and
        # would have produced 6.9B against its own fixture (REVIEW.md S1-3).
        "rho": 0.02, "f_base": 0.90,
        "spec_hours": 80.0, "architecture_hours": 10.0,
        "N_impl_routine": 1, "N_impl_standard": 3, "N_impl_hard": 5,
        "decide_tokens": 600.0e6, "oracle_tokens": 4460.0e6, "crosstest_tokens": 768.0e6,
        "integration_tokens": 200.0e6, "repo_scope_tokens": 1850.0e6,
    },
}


def scenario_names() -> tuple[str, ...]:
    """Return the scenario keys in reporting order: A, B, C, D, D+."""
    return tuple(SCENARIO_STEPS)


def scenario_label(name: str) -> str:
    """Return the human-facing label for a scenario. Raises on an unknown name (§8)."""
    if name not in SCENARIO_LABELS:
        raise KeyError(f"unknown scenario {name!r}; known: {', '.join(scenario_names())}")
    return SCENARIO_LABELS[name]


def scenario_policy_spec(scenario: str, name: str) -> dict:
    """Return the full record for one per-scenario POLICY parameter.

    Composed from the shared ``_POLICY_META`` provenance and this scenario's value, so that
    the registry walk in ``tests/test_params.py`` sees the same record shape as ``params``.
    """
    scenario_label(scenario)
    values = SCENARIO_POLICY[scenario]
    if name not in values:
        raise KeyError(f"unknown scenario parameter {scenario}.{name}")
    meta = _N_IMPL_META if name.startswith("N_impl_") else _POLICY_META[name]
    source, low, high, unit, doc = meta
    if name.startswith("N_impl_"):
        doc = f"{doc} Story class: {name[len('N_impl_'):]}."
    return param_record(values[name], "POLICY", source, low, high, unit, doc)


def iter_scenario_params():
    """Yield ("scenario.parameter", record) for every per-scenario POLICY parameter."""
    for scenario, values in SCENARIO_POLICY.items():
        for name in values:
            yield f"{scenario}.{name}", scenario_policy_spec(scenario, name)


def default_scenario_policy() -> dict[str, dict[str, float]]:
    """Return a deep-enough copy of the per-scenario POLICY values, safe to mutate."""
    return {scenario: dict(values) for scenario, values in SCENARIO_POLICY.items()}


def apply_scenario_overrides(policy: dict, overrides: dict) -> dict:
    """Apply ``{"all_three.oracle_tokens": 800e6}``-style overrides to a policy mapping."""
    merged = {scenario: dict(values) for scenario, values in policy.items()}
    for dotted, raw in overrides.items():
        scenario, _, name = dotted.partition(".")
        if not name:
            raise ValueError(f"scenario override {dotted!r} must read scenario.parameter")
        default = scenario_policy_spec(scenario, name)["value"]
        number = float(raw)
        if isinstance(default, int):
            if number != int(number):
                raise ValueError(f"{dotted} is an integer parameter; got {raw!r}")
            number = int(number)
        merged[scenario][name] = number
    return merged


def step_intensity(steps: dict[int, int], step: int) -> int:
    """Return how deeply a step is run: 0 inactive, 1 active, 2 deeper (SPEC.md §6)."""
    if step not in STEPS:
        raise KeyError(f"unknown process step {step}; steps are 1-10 (SPEC.md §7)")
    return steps.get(step, 0)


def select_tables(steps: dict[int, int]) -> dict[str, str]:
    """Which calibrated tables the active steps select. SPEC.md §7, row by row.

    Steps 2 and 3 together are what conform the criteria — SPEC.md §7 folds Step 3's effect
    into Step 2's, so both must be active. Step 5 is what freezes the acceptance suite, and
    it alone decides ``k``. ``p`` needs the pair of them, hence four tables (SPEC.md §3.3).
    ``m`` follows Step 6's intensity: absent, scored, or deeper with wider property
    generation.
    """
    specced = bool(step_intensity(steps, 2)) and bool(step_intensity(steps, 3))
    frozen = bool(step_intensity(steps, 5))
    return {
        "d": "d_specced" if specced else "d_base",
        "m": ("m_unscored", "m_scored", "m_deep")[step_intensity(steps, 6)],
        "S": "S_oracled" if specced else "S_manual",
        "R": "R_gated" if step_intensity(steps, 8) else "R_large",
        "k": "k_frozen" if frozen else "k_unfrozen",
        "p": ("p_frozen" if frozen else "p_unfrozen") + ("_specced" if specced else ""),
    }


def resolve_scenario(name: str, params: dict, policy: dict | None = None) -> dict:
    """Resolve a scenario name into the parameter set the model consumes.

    This function is the model's connection to the process (SPEC.md §7). Nothing is entered
    per scenario that could be derived from which steps are active — CLAUDE.md §6's
    derive-don't-assert rule — so ``d``, ``m``, ``S``, ``R`` and the ``k``/``p`` tables are
    all *selected* by :func:`select_tables` rather than declared.

    Returns a plain dict (no classes, per the SPEC.md §11 entry of 2026-08-17), carrying the
    resolved scalars, the per-class tables, and the apparatus token lines.
    """
    steps = SCENARIO_STEPS[name] if name in SCENARIO_STEPS else scenario_label(name)
    policy = default_scenario_policy() if policy is None else policy
    chosen = policy[name]
    table = select_tables(steps)
    compared = bool(step_intensity(steps, 7))
    k_table, p_table, m_name = table["k"], table["p"], table["m"]

    return {
        "name": name,
        "label": scenario_label(name),
        "steps": dict(steps),
        # --- escape-equation primitives, SPEC.md §4.1
        "d": params[table["d"]],
        "m": params[m_name],
        "rho": chosen["rho"],
        "f_base": chosen["f_base"],
        # --- human time, SPEC.md §4.4
        "S": params[table["S"]],
        "R": params[table["R"]],
        "spec_hours": chosen["spec_hours"],
        "architecture_hours": chosen["architecture_hours"],
        # Adjudication touches exist only where Step 7 is active: a scenario without
        # cross-implementation comparison raises no flagged questions (SPEC.md §4.4).
        "adjudication_rate": params["adjudication_rate"] if compared else 0.0,
        # --- generation, SPEC.md §4.3
        "k": {cls: params[f"{k_table}_{cls}"] for cls in CLASSES},
        "p": {cls: params[f"{p_table}_{cls}"] for cls in CLASSES},
        "N_impl": {cls: chosen[f"N_impl_{cls}"] for cls in CLASSES},
        "n_stories": {cls: params[f"n_{cls}"] for cls in CLASSES},
        "apparatus_tokens": {line: chosen[f"{line}_tokens"] for line in APPARATUS_LINES},
        # Which tables were selected, so the report can show the reader why.
        "k_table": k_table,
        "p_table": p_table,
        "m_table": m_name,
    }


def describe_steps(name: str) -> list[str]:
    """Return one line per active step, for the report's provenance block."""
    steps = SCENARIO_STEPS[name] if name in SCENARIO_STEPS else scenario_label(name)
    lines = []
    for step in sorted(steps):
        title, effect = STEPS[step]
        deeper = " (deeper)" if steps[step] > 1 else ""
        lines.append(f"{step:>2}. {title}{deeper} — {effect}")
    return lines


def validate_scenario_policy(policy: dict) -> None:
    """Raise unless every scenario carries every policy parameter it needs (§8)."""
    for scenario in SCENARIO_STEPS:
        if scenario not in policy:
            raise KeyError(f"scenario policy missing {scenario!r}")
        missing = set(SCENARIO_POLICY[scenario]) - set(policy[scenario])
        if missing:
            raise KeyError(f"{scenario} missing policy: {', '.join(sorted(missing))}")
        chosen = policy[scenario]
        if not 0.0 <= chosen["rho"] <= 1.0:
            raise ValueError(f"{scenario}.rho must lie in [0, 1]; got {chosen['rho']}")
        if not 0.0 <= chosen["f_base"] <= 1.0:
            raise ValueError(f"{scenario}.f_base must lie in [0, 1]; got {chosen['f_base']}")
        for cls in CLASSES:
            if chosen[f"N_impl_{cls}"] < 1:
                raise ValueError(f"{scenario}.N_impl_{cls} must be at least 1")


# Keeps the import of param_spec honest: the report shows a resolved scalar next to the
# registry record it came from, and this is the lookup it uses.
def source_of(name: str) -> str:
    """Return the provenance string for a top-level parameter, for the report."""
    return param_spec(name)["source"]
