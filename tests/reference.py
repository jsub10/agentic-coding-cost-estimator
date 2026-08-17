"""A differential reference: the deterministic case computed the slow and obvious way.

**Pure Python. Nested loops. No NumPy, no vectorisation, no shortcuts.** That is the whole
point (CLAUDE.md §7): it is structurally unlike ``model.py``, so the two are unlikely to
share a bug. Where ``model.py`` sums a class in one array operation, this loops over every
story and every implementation individually and adds them up one at a time.

It also computes the attempt expectation as an explicit series rather than by the closed
form ``(1 - q^A_max) / p``, and the story fallback probability by enumerating every
convergence outcome rather than by a binomial tail. If the two agree to floating-point
tolerance, both are probably right.

Not imported by the model. Only ``tests/test_reference.py`` uses it.
"""

from __future__ import annotations

from itertools import product

CLASSES = ("routine", "standard", "hard")

HOUR_TERMS = ("criteria", "review", "spec", "architecture",
              "switch", "fallback", "restructure", "incident")


def expected_attempts(p, A_max):
    """Sum the truncated geometric series term by term (SPEC.md §4.2)."""
    total = 0.0
    for k in range(A_max):
        term = 1.0
        for _ in range(k):
            term *= 1.0 - p
        total += term
    return total


def story_fallback_probability(p, A_max, n_impl, n_compare_min):
    """Enumerate every convergence outcome across implementations, one at a time.

    ``model.story_fallback_probability`` reaches the same number through a binomial tail.
    This walks all 2^n_impl combinations explicitly, which is obviously correct and
    obviously slow.
    """
    u = 1.0
    for _ in range(A_max):
        u *= 1.0 - p
    threshold = min(n_compare_min, n_impl)

    total = 0.0
    for outcome in product((True, False), repeat=n_impl):
        converged = sum(1 for survived in outcome if survived)
        if converged >= threshold:
            continue
        probability = 1.0
        for survived in outcome:
            probability *= (1.0 - u) if survived else u
        total += probability
    return total


def deterministic_run(params, scenario):
    """The deterministic pass, story by story and implementation by implementation."""
    A_max = params["A_max"]
    n_compare_min = params["n_compare_min"]

    generation_tokens = 0.0
    n_fallback = 0.0
    n_stories = 0

    for cls in CLASSES:
        count = scenario["n_stories"][cls]
        n_impl = scenario["N_impl"][cls]
        p = scenario["p"][cls]
        k = scenario["k"][cls]
        attempts = expected_attempts(p, A_max)
        fallback_probability = story_fallback_probability(p, A_max, n_impl, n_compare_min)

        for _story in range(count):
            n_stories += 1
            n_fallback += fallback_probability
            for _implementation in range(n_impl):
                generation_tokens += k * attempts

    apparatus_tokens = 0.0
    for line in ("decide", "oracle", "crosstest", "integration", "repo_scope"):
        apparatus_tokens += scenario["apparatus_tokens"][line]

    total_tokens = generation_tokens + apparatus_tokens
    token_cost = total_tokens * params["c"] / 1.0e6

    # SPEC.md §4.1, both stages spelled out.
    e_gate = scenario["d"] * (scenario["rho"] + (1.0 - scenario["rho"]) * scenario["m"])
    e = e_gate * (scenario["f_base"] + (1.0 - scenario["f_base"]) * params["q_rev"])

    n_reviewed = (n_stories - n_fallback) * (1.0 - scenario["f_base"])
    n_escaped = n_stories * e

    hours = {}
    hours["criteria"] = n_stories * scenario["S"]
    hours["review"] = n_reviewed * scenario["R"]
    hours["spec"] = scenario["spec_hours"]
    hours["architecture"] = scenario["architecture_hours"]
    hours["fallback"] = n_fallback * params["fallback_hours"]
    hours["incident"] = n_escaped * params["I"]
    hours["restructure"] = params["restructure_fraction"] * (
        hours["criteria"] + hours["review"] + hours["spec"] + hours["architecture"])

    n_touches = (n_stories + n_reviewed
                 + scenario["adjudication_rate"] * n_stories + n_fallback)
    hours["switch"] = n_touches / params["b"] * params["s"]

    total_hours = 0.0
    for term in HOUR_TERMS:
        total_hours += hours[term]
    hours["total"] = total_hours

    human_cost = 0.0
    for term in HOUR_TERMS:
        rate = params["w_inc"] if term == "incident" else params["w"]
        human_cost += hours[term] * rate

    return {
        "n_stories": n_stories,
        "e_gate": e_gate,
        "e": e,
        "n_escaped": n_escaped,
        "n_reviewed": n_reviewed,
        "n_fallback": n_fallback,
        "n_touches": n_touches,
        "generation_tokens": generation_tokens,
        "apparatus_tokens": apparatus_tokens,
        "total_tokens": total_tokens,
        "token_cost": token_cost,
        "hours": hours,
        "human_cost": human_cost,
        "total_cost": human_cost + token_cost,
        "token_share": token_cost / (human_cost + token_cost),
    }
