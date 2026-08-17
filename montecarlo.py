"""Repeats ``model.simulate``, collects percentiles, and decomposes the variance.

Three jobs, and no arithmetic beyond them: percentiles of each cost component, the
freeze-one-source variance decomposition of SPEC.md §5, and one-at-a-time parameter
sensitivity sweeps — which are a *different* thing from a variance share and are reported
under their own name (REVIEW.md S3-1).

The iteration axis is chunked so that the widest intermediate array stays small: the
``(iterations, n_stories, N_impl)`` draws in ``model._draw_generation`` are the only large
allocation in the program, and scenario D+ makes 120 of them per Hard story-row. Chunking is
derived from the parameters, so it is deterministic given a seed (CLAUDE.md §9).

No I/O, not even logging (CLAUDE.md §8).
"""

from __future__ import annotations

import numpy as np

import model
import scenarios as scenarios_module

PERCENTILES = {"p50": 50.0, "p80": 80.0, "p95": 95.0}

# Widest intermediate array, in elements. Six such arrays live at once inside
# _draw_generation, so this holds the peak near 100 MB against CLAUDE.md §9's 500 MB budget.
CHUNK_ELEMENTS = 2_000_000


def _chunk_size(scenario, iterations: int) -> int:
    """Iterations per block, so the widest per-implementation array stays bounded."""
    widest = max(scenario["n_stories"][cls] * scenario["N_impl"][cls]
                 for cls in scenario["n_stories"]) or 1
    return max(1, min(iterations, CHUNK_ELEMENTS // widest))


def _collect(params, scenario, iterations, seed, uncertainty, frozen):
    """Run every chunk and concatenate the ``(iterations,)`` columns.

    Only run-level quantities survive the chunk boundary, so peak memory is set by one
    chunk's draws rather than by the whole run.
    """
    rng = np.random.default_rng(seed)
    size = _chunk_size(scenario, iterations)
    parts: dict[str, list] = {}
    done = 0

    while done < iterations:
        n = min(size, iterations - done)
        out = model.simulate(params, scenario, rng, n, uncertainty, frozen)
        columns = {f"cost.{term}": out["cost"][term]
                   for term in model.COST_TERMS + ("total",)}
        columns["hours.total"] = out["hours"]["total"]
        for name in ("total_tokens", "n_escaped", "n_reviewed", "n_fallback", "e_run"):
            columns[name] = out[name]
        for name, value in columns.items():
            # spec and architecture hours are constants; broadcast so every column is a
            # full-length array and the percentile of a constant is that constant.
            parts.setdefault(name, []).append(
                np.broadcast_to(np.asarray(value, dtype=np.float64), (n,)).copy())
        done += n

    return {name: np.concatenate(chunks) for name, chunks in parts.items()}


def _percentiles(columns) -> dict[str, dict[str, float]]:
    """P50 / P80 / P95 of every cost component. Never a mean (CLAUDE.md §6)."""
    result = {}
    for term in model.COST_TERMS + ("total",):
        values = columns[f"cost.{term}"]
        result[term] = {label: float(np.percentile(values, q))
                        for label, q in PERCENTILES.items()}
    return result


def _spread(percentiles) -> float:
    """The P50->P95 spread of total cost, which is what the decomposition reduces."""
    return percentiles["total"]["p95"] - percentiles["total"]["p50"]


def _decompose(params, scenario, iterations, seed, uncertainty, baseline_spread):
    """Freeze one random source at a time and measure the reduction in the spread.

    Common random numbers throughout: every run uses the same seed and draws in the same
    order, so the only thing that differs between the baseline and a frozen run is the
    source being frozen. Without that, the measurement is swamped by Monte Carlo noise.

    The shares **do not sum to 100%** and must never be presented as though they did. The
    model is non-linear, so freeze-one-at-a-time reductions are not a partition of the
    variance (SPEC.md §5).
    """
    if baseline_spread <= 0.0:
        return {source: 0.0 for source in model.VARIANCE_SOURCES}

    shares = {}
    for source in model.VARIANCE_SOURCES:
        columns = _collect(params, scenario, iterations, seed, uncertainty, (source,))
        shares[source] = float(1.0 - _spread(_percentiles(columns)) / baseline_spread)
    return shares


def _deterministic_result(name, params, scenario, seed):
    """Wrap the deterministic pass in the same result shape, for ``uncertainty="none"``."""
    direct = model.deterministic_run(params, scenario)
    flat = {term: {label: direct["cost"][term] for label in PERCENTILES}
            for term in model.COST_TERMS + ("total",)}
    return {
        "scenario": name,
        "label": scenario["label"],
        "iterations": 1,
        "seed": seed,
        "uncertainty": "none",
        "percentiles": flat,
        "ratio_p95_p50": 1.0,
        "e": direct["e"],
        "e_gate": direct["e_gate"],
        "mean_escaped": direct["n_escaped"],
        "mean_reviewed": direct["n_reviewed"],
        "mean_fallback": direct["n_fallback"],
        "mean_tokens": direct["total_tokens"],
        "mean_hours": direct["hours"]["total"],
        "token_share": direct["token_share"],
        "fte": direct["fte"],
        "calendar_weeks": float(params["calendar_weeks"]),
        "n_stories": direct["n_stories"],
        "variance": {},
        "variance_is_partition": False,
        "deterministic": direct,
    }


def run_scenario(name, params, policy=None, iterations=10_000, seed=7,
                 uncertainty="full", decompose=False) -> dict:
    """Run one scenario and return its result as a plain dict.

    ``uncertainty`` is ``"full"`` (epistemic and aleatory), ``"aleatory"`` (the repo common
    factor only, so parameter uncertainty is switched off — SPEC.md §3.5), or ``"none"``
    (the deterministic pass). ``decompose`` adds the SPEC.md §5 variance decomposition, which
    costs one extra full run per random source.

    Returns plain floats and dicts only, so ``report.py`` never touches an array
    (CLAUDE.md §10).
    """
    if uncertainty not in model.UNCERTAINTY_MODES:
        raise ValueError(f"unknown uncertainty mode {uncertainty!r}; "
                         f"expected one of {model.UNCERTAINTY_MODES}")
    if iterations < 1:
        raise ValueError(f"iterations must be at least 1; got {iterations}")

    scenario = scenarios_module.resolve_scenario(name, params, policy)
    direct = model.deterministic_run(params, scenario)

    if uncertainty == "none":
        return _deterministic_result(name, params, scenario, seed)

    columns = _collect(params, scenario, iterations, seed, uncertainty, ())
    variance = {}
    if decompose:
        variance = _decompose(params, scenario, iterations, seed, uncertainty,
                              _spread(_percentiles(columns)))
    return _assemble(name, params, scenario, direct, columns, variance,
                     iterations, seed, uncertainty)


def _assemble(name, params, scenario, direct, columns, variance,
              iterations, seed, uncertainty) -> dict:
    """Build the result dict. Plain floats only, so report.py never sees an array (§10)."""
    percentiles = _percentiles(columns)
    return {
        "scenario": name,
        "label": scenario["label"],
        "iterations": int(iterations),
        "seed": int(seed),
        "uncertainty": uncertainty,
        "percentiles": percentiles,
        # Computed here rather than in report.py, which formats and computes nothing (§3).
        "ratio_p95_p50": float(percentiles["total"]["p95"] / percentiles["total"]["p50"]),
        # The derived escape rate, from the nominal parameters. mean_escaped is what the
        # simulation realised, and the two must agree — SPEC.md §5's mandatory test.
        "e": direct["e"],
        "e_gate": direct["e_gate"],
        "mean_escaped": float(columns["n_escaped"].mean()),
        "mean_reviewed": float(columns["n_reviewed"].mean()),
        "mean_fallback": float(columns["n_fallback"].mean()),
        "mean_tokens": float(columns["total_tokens"].mean()),
        "mean_hours": float(columns["hours.total"].mean()),
        # A share is a ratio, so it is taken between expected values: the ratio of two
        # percentiles is not the percentile of the ratio, and would be a share of nothing.
        "token_share": float(columns["cost.tokens"].mean() / columns["cost.total"].mean()),
        # FTE comes off the deterministic hours so that the headcount statement is a
        # property of the plan rather than of one tail (SPEC.md §9, §10). The duration it
        # is quoted against travels with it, because an FTE without one means nothing.
        "fte": direct["fte"],
        "calendar_weeks": float(params["calendar_weeks"]),
        "n_stories": direct["n_stories"],
        "variance": variance,
        "variance_is_partition": False,
        "deterministic": direct,
    }


def run_all(params, policy=None, iterations=10_000, seed=7, uncertainty="full",
            decompose=False, names=None) -> dict[str, dict]:
    """Run every scenario in reporting order, A through D+.

    Each scenario gets the same seed. That is deliberate: it puts them on common random
    numbers, so a comparison between two scenarios is not itself noisy.
    """
    names = scenarios_module.scenario_names() if names is None else tuple(names)
    return {name: run_scenario(name, params, policy, iterations, seed,
                               uncertainty, decompose)
            for name in names}


def savings_against_baseline(results, baseline=None) -> dict[str, dict[str, float]]:
    """Marginal saving of each scenario against the baseline, at each percentile.

    Also returns the multiplicative null for the two single-phase additions, because savings
    fractions do not add: the correct null for two independent interventions is
    ``1 - (1 - saving_b)(1 - saving_c)``, and comparing against an additive one understates
    the synergy by an order of magnitude (SPEC.md §6, REVIEW.md S3-5).
    """
    baseline = scenarios_module.BASELINE if baseline is None else baseline
    if baseline not in results:
        raise KeyError(f"baseline {baseline!r} was not run, so no saving can be quoted")
    reference = results[baseline]["percentiles"]["total"]

    savings = {}
    for name, result in results.items():
        savings[name] = {label: float(1.0 - result["percentiles"]["total"][label]
                                      / reference[label])
                         for label in PERCENTILES}
    return savings


def superadditivity(savings, decide="execute_decide", deliver="execute_deliver",
                    both="all_three", at="p50") -> dict[str, float]:
    """The multiplicative null, the realised saving, and the synergy between them."""
    for name in (decide, deliver, both):
        if name not in savings:
            raise KeyError(f"{name!r} was not run, so superadditivity cannot be computed")
    null = 1.0 - (1.0 - savings[decide][at]) * (1.0 - savings[deliver][at])
    realised = savings[both][at]
    return {"null": float(null), "realised": float(realised),
            "synergy": float(realised - null)}


def _resolve_sweep_target(name, param_name):
    """Return (scenario_or_None, leaf) for a sweep target.

    A bare name may address either the global registry or the swept scenario's own POLICY
    block. ``--sensitivity rho`` means "rho for this scenario", because ``rho`` has no global
    value at all — SPEC.md §3.6 makes it a per-scenario choice off a menu.
    """
    if "." in param_name:
        scenario_name, _, leaf = param_name.partition(".")
        return scenario_name, leaf
    import params as params_module
    if param_name in params_module.PARAMS:
        return None, param_name
    if param_name in scenarios_module.SCENARIO_POLICY[name]:
        return name, param_name
    raise KeyError(f"unknown parameter {param_name!r}; it is neither in the global registry "
                   f"nor in {name}'s policy block. --list-params lists both.")


def sensitivity(name, param_name, params, policy=None, points=9, iterations=2000,
                seed=7, uncertainty="full", low=None, high=None) -> dict:
    """Sweep one parameter across its declared range and report the effect on P50 and P95.

    This is a **sensitivity analysis, not a variance decomposition**. A constant contributes
    zero variance, so a policy parameter can never be a variance share — but sweeping it is
    still informative, and the two must not be presented under the same heading
    (SPEC.md §5, REVIEW.md S3-1).

    Accepts a top-level name, a bare per-scenario POLICY name, or ``scenario.parameter``.
    """
    import params as params_module

    scenario_name, leaf = _resolve_sweep_target(name, param_name)
    scoped = scenario_name is not None
    spec = (scenarios_module.scenario_policy_spec(scenario_name, leaf) if scoped
            else params_module.param_spec(leaf))

    start = spec["low"] if low is None else float(low)
    stop = spec["high"] if high is None else float(high)
    if not stop > start:
        raise ValueError(f"empty sweep range for {param_name}: [{start}, {stop}]")

    # An integer parameter is swept over integers. Rounding the sweep points is right;
    # rounding an explicit --set would not be, and params.coerce refuses to do it there.
    grid = np.linspace(start, stop, points)
    if isinstance(spec["value"], int):
        grid = sorted({int(round(point)) for point in grid})

    rows = []
    for value in grid:
        value = float(value)
        if scoped:
            swept_params = params
            swept_policy = scenarios_module.apply_scenario_overrides(
                scenarios_module.default_scenario_policy() if policy is None else policy,
                {f"{scenario_name}.{leaf}": value})
        else:
            swept_params = params_module.apply_overrides(params, {leaf: value})
            swept_policy = policy
        result = run_scenario(name, swept_params, swept_policy, iterations, seed, uncertainty)
        rows.append({"value": value, "e": result["e"],
                     "p50": result["percentiles"]["total"]["p50"],
                     "p95": result["percentiles"]["total"]["p95"],
                     "mean_escaped": result["mean_escaped"]})

    return {"scenario": name, "parameter": param_name, "baseline": spec["value"],
            "unit": spec["unit"], "kind": spec["kind"], "source": spec["source"],
            "iterations": int(iterations), "seed": int(seed), "rows": rows}


def deterministic_all(params, policy=None, names=None) -> dict[str, dict]:
    """The deterministic pass for every scenario — the pinned point estimates of SPEC.md §6."""
    names = scenarios_module.scenario_names() if names is None else tuple(names)
    return {name: model.deterministic_run(
        params, scenarios_module.resolve_scenario(name, params, policy))
        for name in names}
