"""Formats results as text or CSV. No computation (CLAUDE.md §3).

Every number printed here arrived in a result dict already computed. The only arithmetic
permitted is unit conversion at the reporting boundary — tokens to billions, fractions to
percentages — which SPEC.md §2 explicitly reserves for this layer.

The report is opinionated about reading order, because the numbers are easy to misread. The
P95 comes before the P50, the caveats are printed rather than optional, and the variance
shares are labelled as not summing to 100%.
"""

from __future__ import annotations

import params as params_module
import scenarios as scenarios_module

COMPONENT_ORDER = ("tokens", "criteria", "review", "incident", "spec",
                   "architecture", "switch", "fallback", "restructure")

COMPONENT_LABELS = {
    "tokens": "tokens", "criteria": "criteria", "review": "review",
    "incident": "incidents", "spec": "spec", "architecture": "arch",
    "switch": "switch", "fallback": "fallback", "restructure": "restr",
}

RULE = "=" * 84
THIN = "-" * 84


def money(value: float) -> str:
    """Dollars, no cents. The model's precision does not extend to cents."""
    return f"${value:,.0f}"


def tokens(value: float) -> str:
    """Tokens in billions — the only place the millions/billions shorthand is allowed."""
    return f"{value / 1e9:.2f}B"


def percent(fraction: float, places: int = 1) -> str:
    return f"{fraction * 100:.{places}f}%"


def _row(label: str, left: str, right: str = "") -> str:
    """One aligned line of a scenario block: label, main field, right-hand field."""
    return f"  {label:<10}{left:<52}{right}".rstrip()


def format_scenario(result: dict) -> str:
    """One scenario block, in the order of SPEC.md §10."""
    total = result["percentiles"]["total"]
    lines = [
        result["label"],
        _row("Cost", f"P50 {money(total['p50']):>11}  P80 {money(total['p80']):>11}"
                     f"  P95 {money(total['p95']):>11}",
             f"P95/P50 {result['ratio_p95_p50']:>5.2f}"),
        _row("Tokens", f"{tokens(result['mean_tokens']):>7}"
                       f"  {money(result['percentiles']['tokens']['p50']):>11}",
             f"share   {percent(result['token_share']):>5}"),
        _row("Hours", f"{result['mean_hours']:>7,.0f}"
                      f"  {result['fte']:.2f} FTE over {result['calendar_weeks']:.0f} weeks",
             f"stories {result['n_stories']:>5}"),
        _row("Escapes", f"e = {percent(result['e'], 2):>6}"
                        f"  {result['mean_escaped']:.1f} stories escape",
             f"fallback{result['mean_fallback']:>6.1f}"),
        "  Breakdown at P50:",
        "    " + "  ".join(
            f"{COMPONENT_LABELS[term]} {money(result['percentiles'][term]['p50'])}"
            for term in COMPONENT_ORDER),
    ]
    if result["variance"]:
        lines.append(format_variance(result))
    return "\n".join(lines)


def format_variance(result: dict) -> str:
    """The variance decomposition, labelled as what it is and is not (SPEC.md §5)."""
    ranked = sorted(result["variance"].items(), key=lambda item: -item[1])
    body = "  ".join(f"{source} {share * 100:.0f}%" for source, share in ranked)
    note = ("not a partition; shares do not sum to 100%"
            if not result["variance_is_partition"] else "")
    return f"  Variance  {body}\n            ({note})"


def format_comparison(results: dict, savings: dict | None, superadd: dict | None) -> str:
    """The cross-scenario table and the marginal saving of each against the baseline.

    ``savings`` is None when the baseline scenario was not among those run, in which case
    the column is dropped and the reason stated. A saving against an absent baseline would
    have to be invented, and this program does not invent numbers (CLAUDE.md §8).
    """
    heading = ("COMPARISON — saving quoted against the baseline" if savings
               else "COMPARISON")
    lines = [RULE, heading, THIN,
             f"{'scenario':<32}{'P50':>12}{'P80':>12}{'P95':>12}{'P95/P50':>9}"
             + (f"{'saving':>8}" if savings else "")]
    for name, result in results.items():
        total = result["percentiles"]["total"]
        row = (f"{result['label']:<32}{money(total['p50']):>12}{money(total['p80']):>12}"
               f"{money(total['p95']):>12}{result['ratio_p95_p50']:>9.2f}")
        if savings:
            row += f"{percent(savings[name]['p50'], 0):>8}"
        lines.append(row)

    if savings is None:
        lines += [THIN,
                  "No saving column: the baseline scenario was not among those run, and a",
                  "saving against a baseline that was not computed would be invented.",
                  "Add --scenario execute_only to quote savings."]

    if superadd is not None:
        lines += [THIN,
                  "Savings fractions do not add. The correct null for two independent",
                  "interventions is multiplicative:",
                  f"  1 - (1 - decide)(1 - deliver) = {percent(superadd['null'])}"
                  f"   realised {percent(superadd['realised'])}"
                  f"   synergy {superadd['synergy'] * 100:+.0f} points"]
    return "\n".join(lines)


def format_headline(results: dict) -> str:
    """The two comparisons the corrected model produces that the earlier one could not."""
    if not {"execute_only", "all_three"} <= set(results):
        return ""
    a = results["execute_only"]["percentiles"]["total"]
    d = results["all_three"]["percentiles"]["total"]
    lines = [THIN, "Read the P95, not the P50."]
    if d["p95"] < a["p50"]:
        lines.append(f"  The recommendation's bad case beats the alternative's median: "
                     f"D P95 {money(d['p95'])} < A P50 {money(a['p50'])}.")
    if "all_three_quality" in results:
        q = results["all_three_quality"]["percentiles"]["total"]
        if q["p50"] > d["p50"] and q["p95"] < d["p95"]:
            lines.append(
                f"  D+ costs {money(q['p50'] - d['p50'])} more at the median and "
                f"{money(d['p95'] - q['p95'])} less at the P95: deliberate quality")
            lines.append("  investment buys tail reduction, not expected-value reduction.")
    return "\n".join(lines)


CAVEATS = """\
What this model does not contain — state these whenever you present a number from it.
  Design decay.        e counts functional defects only. A story that ships correct
                       behaviour through a bad decomposition scores clean here and makes
                       everything after it more expensive.
  Maintenance.         Out of scope by design. Never infer maintenance from build cost.
  Calendar duration.   The saving is a headcount reduction at roughly constant duration,
                       not a delivery speed-up. Authority does not parallelise, which is
                       why FTE is printed beside cost.
  Steps 4, 9 and 10.   Reuse, cross-story defect detection and design conformance are
                       real but poorly quantified, so they are under-parameterised. The
                       model therefore understates the full process rather than
                       overstating it.
  N_impl.              Costs tokens and enters no modelled outcome. Best-of-N selection
                       and ambiguity detection are unmodelled, so D+ is understated most.

The shipped CALIBRATED values are illustrative placeholders. They reproduce the briefing
set's figures, which makes this code checkable — they are not your organisation's numbers,
and using them for a real decision would be a mistake. See SPEC.md §8."""


def format_report(results: dict, savings: dict | None, superadd: dict | None = None,
                  caveats: bool = True) -> str:
    """The default text report: every scenario, the comparison, and the caveats."""
    first = next(iter(results.values()))
    blocks = [
        RULE,
        "AGENTIC CODING COST ESTIMATOR",
        f"  {first['iterations']:,} iterations, seed {first['seed']}, "
        f"uncertainty: {first['uncertainty']}",
        RULE,
    ]
    for result in results.values():
        blocks.append(format_scenario(result))
        blocks.append("")
    blocks.append(format_comparison(results, savings, superadd))
    headline = format_headline(results)
    if headline:
        blocks.append(headline)
    if caveats:
        blocks += [RULE, CAVEATS]
    blocks.append(RULE)
    return "\n".join(blocks)


def format_deterministic(results: dict) -> str:
    """The deterministic pass — a mean-like quantity, pinned separately from the P50."""
    lines = [RULE,
             "DETERMINISTIC PASS — every random source at its expected value",
             "  This is a mean-like quantity. On a right-skewed distribution the P50 sits",
             "  below it, so the two are pinned separately (SPEC.md §6).",
             THIN,
             f"{'scenario':<32}{'hours':>8}{'human $':>11}{'tokens':>9}{'token $':>10}"
             f"{'total':>11}{'share':>7}{'e':>7}{'fallb':>7}"]
    for result in results.values():
        lines.append(
            f"{result['label']:<32}{result['hours']['total']:>8.0f}"
            f"{money(result['human_cost']):>11}{tokens(result['total_tokens']):>9}"
            f"{money(result['token_cost']):>10}{money(result['total_cost']):>11}"
            f"{percent(result['token_share']):>7}{percent(result['e']):>7}"
            f"{result['n_fallback']:>7.1f}")
    return "\n".join(lines + [RULE])


def format_csv(results: dict, savings: dict | None) -> str:
    """One row per scenario per percentile (SPEC.md §10)."""
    header = ["scenario", "label", "percentile", "total"]
    header += list(COMPONENT_ORDER)
    header += ["saving_vs_baseline", "e", "mean_escaped", "mean_fallback",
               "mean_tokens", "token_share", "fte", "iterations", "seed", "uncertainty"]
    rows = [",".join(header)]
    for name, result in results.items():
        for label in ("p50", "p80", "p95"):
            row = [name, f'"{result["label"]}"', label,
                   f"{result['percentiles']['total'][label]:.2f}"]
            row += [f"{result['percentiles'][term][label]:.2f}"
                    for term in COMPONENT_ORDER]
            row += [f"{savings[name][label]:.6f}" if savings else "",
                    f"{result['e']:.6f}",
                    f"{result['mean_escaped']:.4f}", f"{result['mean_fallback']:.4f}",
                    f"{result['mean_tokens']:.0f}", f"{result['token_share']:.6f}",
                    f"{result['fte']:.4f}", str(result["iterations"]),
                    str(result["seed"]), result["uncertainty"]]
            rows.append(",".join(row))
    return "\n".join(rows)


def format_sensitivity(sweep: dict) -> str:
    """One-at-a-time sweep. A sensitivity, emphatically not a variance share (§5)."""
    lines = [
        RULE,
        f"SENSITIVITY — {sweep['parameter']} on {sweep['scenario']}",
        f"  kind {sweep['kind']}, baseline {sweep['baseline']:g} {sweep['unit']}, "
        f"{sweep['iterations']:,} iterations, seed {sweep['seed']}",
        "  This is a one-at-a-time sensitivity, not a variance decomposition. A constant",
        "  contributes zero variance and can never be a variance share (SPEC.md §5).",
        THIN,
        f"{'value':>14}{'P50':>13}{'P95':>13}{'e':>9}{'escapes':>9}",
    ]
    for row in sweep["rows"]:
        marker = "  <- baseline" if row["value"] == sweep["baseline"] else ""
        lines.append(f"{row['value']:>14.4g}{money(row['p50']):>13}{money(row['p95']):>13}"
                     f"{percent(row['e'], 2):>9}{row['mean_escaped']:>9.1f}{marker}")
    return "\n".join(lines + [THIN, f"source: {sweep['source']}", RULE])


def format_params() -> str:
    """The full registry — value, kind, range and provenance for every parameter."""
    lines = [RULE, "PARAMETER REGISTRY", THIN,
             "Override any of these with --set name=value, or a batch with --config file.",
             "Per-scenario policy is addressed as scenario.parameter.", THIN]
    for name, spec in params_module.iter_params():
        lines.append(f"{name:<28}{spec['value']:>14g}  [{spec['low']:g}, {spec['high']:g}]"
                     f"  {spec['kind']:<11}{spec['unit']}")
        lines.append(f"{'':<28}{spec['doc']}")
        lines.append(f"{'':<28}source: {spec['source']}")
        lines.append("")
    lines += [THIN, "PER-SCENARIO POLICY", THIN]
    for name, spec in scenarios_module.iter_scenario_params():
        lines.append(f"{name:<44}{spec['value']:>14g}  {spec['unit']}")
    return "\n".join(lines + [RULE])


def format_steps() -> str:
    """Which of the ten steps each scenario switches on (SPEC.md §6, §7)."""
    lines = [RULE, "SCENARIOS — declared as which process steps are active", THIN]
    for name in scenarios_module.scenario_names():
        lines.append(scenarios_module.scenario_label(name))
        described = scenarios_module.describe_steps(name)
        lines += [f"    {line}" for line in described] or ["    (no steps automated)"]
        lines.append("")
    return "\n".join(lines + [RULE])
