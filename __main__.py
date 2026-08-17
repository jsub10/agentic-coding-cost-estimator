"""Command-line entry point. Argument parsing only (CLAUDE.md §3).

    python __main__.py                          all five scenarios, 160-story portfolio
    python __main__.py --iterations 50000       tighter percentiles
    python __main__.py --stories 40 28 12       routine, standard, hard
    python __main__.py --scenario all_three --format csv
    python __main__.py --sensitivity rho        sweep one parameter, P50 and P95
    python __main__.py --deterministic          variance off; the published point estimates
    python __main__.py --list-params            every parameter, its range and provenance
    python __main__.py --set w=200 --set b=1    override any parameter
    python __main__.py --config mine.json       override a batch of them

Reading a config file is the only I/O in the program, and it happens here rather than
anywhere downstream: ``model.py`` and ``montecarlo.py`` do no I/O at all (CLAUDE.md §8).
"""

from __future__ import annotations

import argparse
import json
import sys

import montecarlo
import params as params_module
import report
import scenarios as scenarios_module


def build_parser() -> argparse.ArgumentParser:
    """Assemble the CLI. Split by group so no one function runs long (CLAUDE.md §9)."""
    parser = argparse.ArgumentParser(
        prog="agentic-coding-cost-estimator",
        description="Monte Carlo estimator for the cost of building software under "
                    "agentic coding, across five levels of process automation.",
        epilog="The shipped CALIBRATED values are illustrative placeholders. Replace them "
               "with your own telemetry before making a real decision (SPEC.md §8).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_run_arguments(parser)
    _add_configuration_arguments(parser)
    _add_output_arguments(parser)
    return parser


def _add_run_arguments(parser):
    """What to run: which scenarios, how many iterations, and under what uncertainty."""
    run = parser.add_argument_group("what to run")
    run.add_argument("--scenario", action="append", metavar="NAME",
                     choices=scenarios_module.scenario_names(),
                     help="run one scenario; repeatable. Default: all five.")
    run.add_argument("--iterations", type=int, default=10_000, metavar="N",
                     help="Monte Carlo iterations (default: 10000)")
    run.add_argument("--seed", type=int, default=7, metavar="N",
                     help="random seed; identical seeds give identical output (default: 7)")
    run.add_argument("--stories", type=int, nargs=3,
                     metavar=("ROUTINE", "STANDARD", "HARD"),
                     help="portfolio counts (default: 80 56 24)")
    run.add_argument("--uncertainty", choices=("full", "aleatory", "none"), default="full",
                     help="full = parameter and trajectory uncertainty; aleatory = the "
                          "repo common factor only; none = the deterministic pass")
    run.add_argument("--deterministic", action="store_true",
                     help="shorthand for --uncertainty none, and prints the point-estimate "
                          "table instead of percentiles")
    run.add_argument("--decompose", action="store_true",
                     help="add the variance decomposition. Costs one extra run per random "
                          "source, and needs ~100k iterations to settle.")


def _add_configuration_arguments(parser):
    """How to change the numbers: overrides, a config file, and sweeps."""
    tune = parser.add_argument_group("configuration")
    tune.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                      dest="overrides",
                      help="override a parameter; repeatable. Per-scenario policy is "
                           "addressed as scenario.parameter, e.g. all_three.oracle_tokens")
    tune.add_argument("--config", metavar="FILE",
                      help="JSON object of NAME: VALUE overrides, applied before --set")
    tune.add_argument("--sensitivity", metavar="PARAM",
                      help="sweep one parameter across its declared range and report the "
                           "effect on P50 and P95")
    tune.add_argument("--points", type=int, default=9, metavar="N",
                      help="sweep points for --sensitivity (default: 9)")


def _add_output_arguments(parser):
    """What to print, and the two registry listings that print and exit."""
    out = parser.add_argument_group("output")
    out.add_argument("--format", choices=("text", "csv"), default="text")
    out.add_argument("--no-caveats", action="store_true",
                     help="suppress the what-this-does-not-contain block. Not advised.")
    out.add_argument("--list-params", action="store_true",
                     help="print every parameter with its range and provenance, then exit")
    out.add_argument("--list-steps", action="store_true",
                     help="print which of the ten steps each scenario activates, then exit")


def split_overrides(pairs):
    """Split ``NAME=VALUE`` strings into top-level and per-scenario override mappings."""
    top, scoped = {}, {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--set expects NAME=VALUE, got {pair!r}")
        target = scoped if "." in name else top
        target[name.strip()] = value.strip()
    return top, scoped


def load_config(path):
    """Read a JSON object of overrides. Raises rather than ignoring a malformed file."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path}: expected a JSON object of NAME: VALUE overrides")
    return {str(name): value for name, value in loaded.items()}


def resolve_configuration(args):
    """Apply --config then --set, and return (params, policy). Unknown names raise (§8)."""
    top, scoped = {}, {}
    if args.config:
        config_top, config_scoped = split_overrides(
            f"{name}={value}" for name, value in load_config(args.config).items())
        top.update(config_top)
        scoped.update(config_scoped)

    cli_top, cli_scoped = split_overrides(args.overrides)
    top.update(cli_top)
    scoped.update(cli_scoped)

    if args.stories:
        routine, standard, hard = args.stories
        top.update({"n_routine": routine, "n_standard": standard, "n_hard": hard})

    params = params_module.apply_overrides(params_module.default_params(), top)
    policy = scenarios_module.default_scenario_policy()
    if scoped:
        policy = scenarios_module.apply_scenario_overrides(policy, scoped)
    scenarios_module.validate_scenario_policy(policy)
    return params, policy


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_params:
        print(report.format_params())
        return 0
    if args.list_steps:
        print(report.format_steps())
        return 0

    try:
        params, policy = resolve_configuration(args)
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"configuration error: {error}") from error

    names = tuple(args.scenario) if args.scenario else None
    uncertainty = "none" if args.deterministic else args.uncertainty

    if args.sensitivity:
        target = names[0] if names else "all_three"
        sweep = montecarlo.sensitivity(target, args.sensitivity, params, policy,
                                       points=args.points, iterations=args.iterations,
                                       seed=args.seed, uncertainty=uncertainty)
        print(report.format_sensitivity(sweep))
        return 0

    if args.deterministic:
        print(report.format_deterministic(
            montecarlo.deterministic_all(params, policy, names)))
        return 0

    results = montecarlo.run_all(params, policy, args.iterations, args.seed,
                                 uncertainty, args.decompose, names)

    # A saving needs a baseline. If the user asked for a subset that excludes it, the
    # column is dropped and the report says so, rather than a baseline being run behind
    # their back or a number invented (CLAUDE.md §8).
    savings = (montecarlo.savings_against_baseline(results)
               if scenarios_module.BASELINE in results else None)

    if args.format == "csv":
        print(report.format_csv(results, savings))
        return 0

    superadd = None
    if savings and {"execute_decide", "execute_deliver", "all_three"} <= set(results):
        superadd = montecarlo.superadditivity(savings)
    print(report.format_report(results, savings, superadd, caveats=not args.no_caveats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
