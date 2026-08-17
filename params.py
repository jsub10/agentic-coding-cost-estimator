"""Parameter registry — the only place in this project where a number lives.

Every parameter is a *record*: a plain dict carrying its value, its provenance, the source
that value came from, and the range over which sweeping it is meaningful. CLAUDE.md §2
forbids a numeric literal a user might want to change from appearing anywhere else, and
CLAUDE.md §5 makes a missing ``source`` a bug — ``tests/test_params.py`` enforces both.

Provenance kinds, per SPEC.md §3. ``PRICE`` is an organisational fact, changing with your
contracts rather than your engineering. ``CALIBRATED`` is fitted from your own telemetry —
**the shipped values are illustrative placeholders and must be replaced before any real
decision**, and SPEC.md §8 says where each one comes from. ``POLICY`` is a choice you make,
and these are the levers under discussion. ``EPISTEMIC`` is the width of our ignorance about
a CALIBRATED value (SPEC.md §3.5), admitted as a fourth kind by the §11 entry of 2026-08-17.

This module imports nothing from this project (CLAUDE.md §3). Per-scenario POLICY lives
next door in ``scenarios.py``, because it is selected by which process steps are active.
"""

from __future__ import annotations

KINDS = ("PRICE", "CALIBRATED", "POLICY", "EPISTEMIC")

CLASSES = ("routine", "standard", "hard")

# Reporting boundary only: SPEC.md §2 keeps tokens whole inside the model and converts to
# millions when printing. Not a tunable, so not a parameter.
TOKENS_PER_MILLION = 1.0e6


def param_record(value, kind, source, low, high, unit, doc):
    """Build one parameter record. Every field is mandatory, including provenance.

    Shared with ``scenarios.py``, which declares its per-scenario POLICY parameters in the
    same shape so that a single registry walk covers both (``tests/test_params.py``).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown provenance kind {kind!r}; expected one of {KINDS}")
    if not source:
        raise ValueError(f"parameter with value {value!r} has no source; see CLAUDE.md §5")
    if not low <= value <= high:
        raise ValueError(f"default {value!r} lies outside its own range [{low}, {high}]")
    return {"value": value, "kind": kind, "source": source,
            "low": low, "high": high, "unit": unit, "doc": doc}


_FINANCE = "Your finance function. SPEC.md §3.2."
_SPIKES = "SPEC.md §3.3. Metered spikes against the real repository, SPEC.md §8."
_TRACKED = "SPEC.md §3.3. Time-tracking on an instrumented epic, SPEC.md §8."
_LAMBDAS = ("SPEC.md §3.4. The hardest parameters to fit — they need several epics of "
            "history (§8). Until then they are structural assumptions: run --sensitivity.")
_PORTFOLIO = "SPEC.md §3.1 default portfolio, the 160-story epic used in the briefing set."

# --- Prices, SPEC.md §3.2 -------------------------------------------------------------

PARAMS: dict[str, dict] = {
    "w": param_record(
        150.0, "PRICE", _FINANCE, 60.0, 500.0, "$/hour",
        "Loaded engineer cost."),
    "w_inc": param_record(
        400.0, "PRICE",
        _FINANCE + " Higher than w: incidents pull senior people out of planned work.",
        100.0, 1200.0, "$/hour",
        "Incident-response cost. Escaped defects bill at this rate, not at w."),
    "c": param_record(
        3.0, "PRICE",
        "Your provider invoices, blended across the model tiers actually used. SPEC.md §3.2.",
        0.25, 60.0, "$/M tokens",
        "Blended token price. The briefing's crossover argument runs out to $60/M."),

    # --- Portfolio, SPEC.md §3.1. User-supplied; the defaults make shipped output directly
    # comparable with the published figures.
    "n_routine": param_record(
        80, "POLICY", _PORTFOLIO, 0, 5000, "stories",
        "Routine stories: a machine can decide whether they are correct."),
    "n_standard": param_record(
        56, "POLICY", _PORTFOLIO, 0, 5000, "stories",
        "Standard stories: partial oracle closure."),
    "n_hard": param_record(
        24, "POLICY", _PORTFOLIO, 0, 5000, "stories",
        "Hard stories: no oracle closure. Concurrent and ordering-sensitive code is Hard "
        "by construction, however well specified it is."),
}

# --- Tokens per attempt, SPEC.md §3.3 -------------------------------------------------
# Selected by whether Step 5 froze an acceptance suite: with no machine verdict the session
# has no stopping rule, so it runs longer.

_K_RANGE = {"routine": (0.02e6, 2.0e6), "standard": (0.1e6, 12.0e6), "hard": (0.5e6, 80.0e6)}
_K_TABLES = {
    "k_frozen": ((0.20e6, 1.3e6, 8.8e6), "with a frozen acceptance suite"),
    "k_unfrozen": ((0.25e6, 1.6e6, 11.0e6), "without one, so sessions run longer"),
}

for _table, (_values, _when) in _K_TABLES.items():
    for _cls, _value in zip(CLASSES, _values):
        PARAMS[f"{_table}_{_cls}"] = param_record(
            _value, "CALIBRATED", _SPIKES, *_K_RANGE[_cls], "tokens",
            f"Tokens per attempt per implementation, {_cls} stories, {_when}.")

# --- Per-attempt success, SPEC.md §3.3 ------------------------------------------------
# Four tables, selected by the pair (Step 5 active?, Steps 2-3 active?). A frozen suite
# tells the agent when it is done; conformed criteria tell it what done means. Those are
# independent improvements and both raise p, hence four tables rather than two.

_P_SPECCED = (
    "SPEC.md §3.3 four-table p selection, added by the §11 entry of 2026-08-17. Back-solved "
    "so §6's pinned outputs reconcile from the parameters: two tables gave B 1.56B tokens "
    "against a pinned 1.49B, D 3.83B against 3.69B, and D's fallback count 1.0 stories "
    "against a pinned 0.4. p_frozen_specced was recovered independently and matches "
    "reference_model.py exactly; p_unfrozen_specced is taken from reference_model.py, whose "
    "B values generated the published figures. Replace both with your own spikes (§8).")
_P_TABLES = {
    "p_unfrozen": ((0.85, 0.50, 0.28), _SPIKES,
                   "no frozen suite, criteria not conformed (scenario A)"),
    "p_unfrozen_specced": ((0.87, 0.54, 0.32), _P_SPECCED,
                           "no frozen suite, criteria conformed by Steps 2-3 (scenario B)"),
    "p_frozen": ((0.90, 0.65, 0.40), _SPIKES,
                 "frozen suite, criteria not conformed (scenario C)"),
    "p_frozen_specced": ((0.92, 0.70, 0.45), _P_SPECCED,
                         "frozen suite and conformed criteria (scenarios D, D+)"),
}

for _table, (_values, _source, _when) in _P_TABLES.items():
    for _cls, _value in zip(CLASSES, _values):
        PARAMS[f"{_table}_{_cls}"] = param_record(
            _value, "CALIBRATED", _source, 0.02, 0.999, "probability",
            f"Per-attempt success probability, {_cls} stories, {_when}.")

# --- Organisation-wide calibrated parameters, SPEC.md §3.3 ----------------------------

PARAMS.update({
    "d_base": param_record(
        0.30, "CALIBRATED",
        "SPEC.md §3.3. Failure rate of fresh implementations against the oracle set, "
        "divided by the mutation score: d = F / mutation_score (§8).",
        0.01, 0.90, "probability",
        "Probability a fresh implementation carries a defect."),
    "d_specced": param_record(
        0.24, "CALIBRATED",
        "SPEC.md §3.3. The same measurement, taken once Steps 2-3 are running.",
        0.01, 0.90, "probability",
        "Same as d_base, when criteria have passed the spec oracles."),
    "m_unscored": param_record(
        0.30, "CALIBRATED",
        "SPEC.md §3.3. m = 1 - mutation score (§8); an unscored suite is assumed no "
        "better than a 70% score.",
        0.01, 0.95, "probability",
        "Miss rate of an oracle set of unknown strength."),
    "m_scored": param_record(
        0.06, "CALIBRATED",
        "SPEC.md §3.3. 1 - 0.94, straight off the mutation-testing run.",
        0.001, 0.60, "probability",
        "Miss rate at a 94% mutation score."),
    "m_deep": param_record(
        0.02, "CALIBRATED",
        "SPEC.md §3.3. 1 - 0.98, with wider property generation.",
        0.001, 0.40, "probability",
        "Miss rate at a 98% mutation score."),
    "q_rev": param_record(
        0.35, "CALIBRATED",
        "SPEC.md §3.3. The Step 8 random sampled-review stream is the only unbiased "
        "source (§8). Measure it; it is emphatically not zero.",
        0.0, 0.95, "probability",
        "Probability human review misses a defect that reaches it."),
    "S_manual": param_record(
        3.0, "CALIBRATED", _TRACKED, 0.1, 16.0, "hours/story",
        "Criteria-authoring hours per story, unaided."),
    "S_oracled": param_record(
        1.0, "CALIBRATED", _TRACKED, 0.05, 12.0, "hours/story",
        "Criteria-authoring hours per story, with spec oracles running."),
    "R_large": param_record(
        2.5, "CALIBRATED", _TRACKED, 0.1, 12.0, "hours/story",
        "Review hours per reviewed story when diffs are unconstrained."),
    "R_gated": param_record(
        1.5, "CALIBRATED", _TRACKED, 0.05, 10.0, "hours/story",
        "Review hours per reviewed story when review means adjudicating a flagged question."),
    "I": param_record(
        12.0, "CALIBRATED", "SPEC.md §3.3. From the incident record (§8).",
        0.5, 120.0, "hours/defect",
        "Hours to resolve one escaped defect. Billed at w_inc, not w."),
    "sigma_k": param_record(
        0.35, "CALIBRATED",
        "SPEC.md §3.3. Spread of logged per-attempt token counts within a class.",
        0.0, 1.5, "lognormal sigma",
        "Shape of the mean-preserving per-attempt token multiplier L (SPEC.md §4.3)."),
    "fallback_hours": param_record(
        8.0, "CALIBRATED",
        "SPEC.md §3.3, added by REVIEW.md S2-4, which found it named in the hours equation "
        "with no value and no provenance row.",
        0.5, 120.0, "hours/story",
        "Human execution of one story that could not be compared at Step 7."),
    "adjudication_rate": param_record(
        0.40, "CALIBRATED",
        "SPEC.md §3.3, added by REVIEW.md S2-4. Implied by the briefing's ~240 touches for D.",
        0.0, 1.0, "fraction",
        "Share of stories raising a flagged question at Step 7. Zero where Step 7 is off."),
    "restructure_fraction": param_record(
        0.05, "CALIBRATED",
        "SPEC.md §3.3. The 5-10% reserve the briefing recommends; REVIEW.md S2-3 found it "
        "recommended but reserved in no published total.",
        0.0, 0.40, "fraction",
        "Capacity reserved for restructuring stories fired by Step 10."),
    "s": param_record(
        0.25, "CALIBRATED", "SPEC.md §3.3. Calendar analysis of context switching (§8).",
        0.0, 3.0, "hours/session",
        "Context-switch cost per batched session of human touches."),
})

# --- Policy, SPEC.md §3.3 scheduling block and §8, which says you choose these ---------

PARAMS.update({
    "A_max": param_record(
        5, "POLICY",
        "SPEC.md §3.3; §8 calls it a policy informed by logged trajectories — the turn "
        "count past which sessions rarely recover.",
        1, 40, "attempts",
        "Attempt cap. Not optional: SPEC.md §4.2 requires the truncated expectation "
        "E[A] = sum of (1-p)^k for k < A_max, never 1/p."),
    "b": param_record(
        6, "POLICY",
        "SPEC.md §3.3 scheduling block, added by the §11 entry of 2026-08-17. Recovered "
        "from scenario A's pinned 1,173 hours: 320 touches x 0.25 h / b = 13.3 switch hours.",
        1, 100, "touches/session",
        "Human touches handled per batched session. b = 1 means every touch arrives as an "
        "interruption, and the model will show what that costs."),
    "n_compare_min": param_record(
        2, "POLICY",
        "SPEC.md §4.2: Step 7 needs two implementations to compare. Structural, but exposed "
        "here rather than buried as a literal in model.py.",
        1, 10, "implementations",
        "Converged implementations a story needs before it can be compared instead of "
        "handed to a human. Applied as min(n_compare_min, N_impl)."),
    "calendar_weeks": param_record(
        26, "POLICY",
        "SPEC.md §3.3 reporting block. The duration FTE is quoted against; §9 insists the "
        "saving is headcount at roughly constant duration, not a delivery speed-up.",
        1, 260, "weeks",
        "Calendar duration for the FTE line. Enters no cost."),
    "hours_per_fte_week": param_record(
        32.0, "POLICY",
        "SPEC.md §3.3 reporting block. Productive engineering hours net of overheads.",
        1.0, 60.0, "hours/week",
        "FTE denominator. Enters no cost."),
})

# --- Correlation, SPEC.md §3.4 --------------------------------------------------------
# lambda_e and lambda_f are deliberately much larger than lambda_p. An unfavourable move in
# p costs extra tokens; a doubling of e costs incident hours at premium rates. That
# asymmetry is roughly an order of magnitude in dollars, and it is the point of the block.

PARAMS.update({
    "lambda_e": param_record(
        0.55, "CALIBRATED", _LAMBDAS, 0.0, 2.0, "loading",
        "Loading of the repo-level common factor theta on the escape rate."),
    "lambda_f": param_record(
        0.40, "CALIBRATED", _LAMBDAS, 0.0, 2.0, "loading",
        "Loading of theta on the auto-merge fraction, in logit space."),
    "lambda_p": param_record(
        0.15, "CALIBRATED", _LAMBDAS, 0.0, 2.0, "loading",
        "Loading of theta on per-attempt success, in logit space. Deliberately small."),
    "p_cluster": param_record(
        0.15, "CALIBRATED", _LAMBDAS, 0.0, 0.60, "probability",
        "Probability a run is a clustered-escape run."),
    "cluster_mult": param_record(
        3.0, "CALIBRATED", _LAMBDAS, 1.0, 10.0, "multiplier",
        "Escape multiplier in a clustered run. Its off-branch counterpart is derived, not "
        "entered, so the pair is mean-preserving (SPEC.md §5)."),
    "sigma_p": param_record(
        0.25, "CALIBRATED",
        "SPEC.md §5, the eps ~ Normal(0, 0.25) term in the p_impl line, read as a standard "
        "deviation to match the theta ~ Normal(0, 1) convention beside it.",
        0.0, 1.5, "logit sd",
        "Per-implementation noise on per-attempt success, in logit space."),

    # --- Parameter uncertainty, SPEC.md §3.5. Drawn once per run: these are beliefs about
    # one organisation, not story-level noise. --uncertainty aleatory switches them off.
    "sigma_d": param_record(
        0.20, "EPISTEMIC",
        "SPEC.md §3.5. d is estimated from a failure rate over one epic, so +/-20% is "
        "optimistic.",
        0.0, 1.0, "lognormal sigma", "Width of our ignorance about d."),
    "sigma_m": param_record(
        0.30, "EPISTEMIC", "SPEC.md §3.5. Mutation score varies by suite and by domain.",
        0.0, 1.0, "lognormal sigma", "Width of our ignorance about m."),
    "sd_q_rev": param_record(
        0.08, "EPISTEMIC",
        "SPEC.md §3.5. q_rev is estimated from a 5-10% sample, so the sample is small.",
        0.0, 0.30, "probability sd",
        "Standard deviation of the Beta on q_rev. Requires sd^2 < mean(1-mean)."),
    "sigma_S": param_record(
        0.25, "EPISTEMIC",
        "SPEC.md §3.5. Criteria-authoring hours vary widely by story and by author.",
        0.0, 1.0, "lognormal sigma", "Width of our ignorance about S."),
    "sigma_k_scale": param_record(
        0.15, "EPISTEMIC",
        "SPEC.md §3.5. Applies to all classes together; per-class k moves with the harness.",
        0.0, 1.0, "lognormal sigma",
        "Width of the global epistemic multiplier k_scale on generation tokens."),
})


# --- Accessors ------------------------------------------------------------------------
# Everything below returns fresh objects. CLAUDE.md §8 forbids global mutable state, so no
# caller is ever handed a reference into PARAMS.


def default_params() -> dict[str, float]:
    """Return name -> value for every registered parameter.

    A plain dict of numbers, which is what the model consumes. Provenance is metadata for
    the report and the tests, and deliberately does not travel into the arithmetic.
    """
    return {name: spec["value"] for name, spec in PARAMS.items()}


def param_spec(name: str) -> dict:
    """Return a copy of one parameter record. Raises on an unknown name (CLAUDE.md §8)."""
    if name not in PARAMS:
        raise KeyError(f"unknown parameter {name!r}; --list-params prints the registry")
    return dict(PARAMS[name])


def iter_params():
    """Yield (name, record copy) for every parameter, in declaration order."""
    for name in PARAMS:
        yield name, dict(PARAMS[name])


def param_range(name: str) -> tuple[float, float]:
    """Return the (low, high) sweep range for one parameter, used by --sensitivity."""
    spec = param_spec(name)
    return spec["low"], spec["high"]


def coerce(name: str, raw) -> float | int:
    """Coerce an override to the declared type of its parameter, strictly.

    An integer parameter refuses a fractional override rather than truncating it: silently
    turning ``A_max=5.5`` into 5 would make a published total irreproducible from the
    parameter the user believes they set.
    """
    default = param_spec(name)["value"]
    number = float(raw)
    if isinstance(default, int):
        if number != int(number):
            raise ValueError(f"{name} is an integer parameter; got {raw!r}")
        return int(number)
    return number


def apply_overrides(params: dict, overrides: dict) -> dict:
    """Return a copy of ``params`` with ``overrides`` applied, then validated.

    Values outside a declared range are permitted — a deliberate stress case is legitimate,
    and the range exists to drive sweeps rather than to police intent. Unknown names raise.
    """
    merged = dict(params)
    for name, raw in overrides.items():
        merged[name] = coerce(name, raw)
    validate(merged)
    return merged


def validate(params: dict) -> None:
    """Raise on any parameter set the model cannot evaluate. No silent fallbacks (§8).

    These are constraints arithmetic imposes rather than matters of judgement: a set that
    violates one of them has no well-defined answer, so it must not be run at all.
    """
    missing = [name for name in PARAMS if name not in params]
    if missing:
        raise KeyError(f"missing parameters: {', '.join(sorted(missing))}")

    if params["n_routine"] + params["n_standard"] + params["n_hard"] <= 0:
        raise ValueError("portfolio is empty; give at least one story")
    if params["A_max"] < 1:
        raise ValueError("A_max must be at least 1; SPEC.md §4.2 requires a real cap")
    if params["b"] < 1:
        raise ValueError("b must be at least 1 touch per session")
    if params["p_cluster"] >= 1.0:
        raise ValueError("p_cluster must be < 1")

    # The off-branch cluster multiplier is (1 - p_cluster*cluster_mult)/(1 - p_cluster). It
    # goes non-positive once the clustered branch alone would exceed the whole mean, at
    # which point no mean-preserving pair exists (SPEC.md §5).
    if params["p_cluster"] * params["cluster_mult"] >= 1.0:
        raise ValueError(
            "p_cluster * cluster_mult must be < 1 for a mean-preserving cluster pair; got "
            f"{params['p_cluster']} * {params['cluster_mult']}")

    # A Beta with a given mean and standard deviation exists only when sd^2 < mean(1-mean).
    mean, sd = params["q_rev"], params["sd_q_rev"]
    if sd > 0.0 and sd ** 2 >= mean * (1.0 - mean):
        raise ValueError(f"no Beta has mean {mean} and sd {sd}; require sd^2 < "
                         f"mean*(1-mean) = {mean * (1.0 - mean):.4f}")

    for name in PARAMS:
        if name.startswith(("p_unfrozen", "p_frozen")) and not 0.0 < params[name] <= 1.0:
            raise ValueError(f"{name} must lie in (0, 1]; got {params[name]}")
