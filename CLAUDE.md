# CLAUDE.md — System Specification

This file is the architectural constitution for this repository. It is loaded as the cached prefix of every
agent session. Read it before writing any code. If a change would violate anything here, stop and raise it
rather than working around it.

This project is itself an instance of Step 1 of the process it models. Treat that as a working constraint, not
a curiosity: if this file is vague, the code will be too.

---

## 1. What this repository is

A Monte Carlo estimator for the cost of building software under agentic coding, implementing the model in
`SPEC.md`. It answers one question: **given a portfolio of stories and a choice of how much of the software
engineering process is automated, what is the cost distribution — P50, P80, P95 — and where does the variance
come from?**

It is a calculator, not a service. No network, no database, no UI, no persistence.

## 2. Non-negotiables

- **Python 3.11+, NumPy, nothing else.** No pandas, no scipy, no plotting libraries. NumPy is permitted because
  the Monte Carlo is genuinely vectorisable and the speed buys larger iteration counts; anything beyond it is a
  sign the model is being complicated rather than the code. Enforced by an allowlist in `tests/test_deps.py`.
- **Deterministic given a seed.** Every run takes an explicit seed. Two runs with the same seed and the same
  parameters produce byte-identical output. Use `numpy.random.default_rng(seed)` and pass the `Generator`
  down explicitly — never `numpy.random.seed`, never the legacy `numpy.random.*` functions, never Python's
  global `random`.
- **Vectorise across iterations, never across the common factor.** `theta` is one draw per Monte Carlo
  iteration, shared by every story in that iteration. Arrays are shaped `(iterations,)` for run-level draws
  and `(iterations, n_stories)` for story-level draws, and the two must never be conflated. A `theta` array
  shaped `(iterations, n_stories)` silently removes the correlation the model exists to capture and no shape
  assertion will catch it. `tests/test_properties.py` checks it by measuring correlation between story
  outcomes within a run.
- **All parameters live in `params.py`.** No numeric literal that a user might want to change appears anywhere
  else. If you find yourself typing `0.30` in `model.py`, it belongs in `params.py` with a name and a source.
- **Every parameter carries its provenance.** Each entry records whether it is a PRICE, a CALIBRATED value, or
  a POLICY choice, and where its value came from. See §5.
- **Money in dollars, time in hours, tokens in whole tokens.** No mixed units, no millions-of-tokens
  shorthand inside the model — convert only at the reporting boundary.
- **`float64` throughout.** Do not downcast to save memory; the token counts run to 10^10 and the cost
  differences that matter are in the hundreds.

## 3. Layout

```
params.py        constants, calibrated values, scenario policies. The only place numbers live.
model.py         one simulation run: portfolio -> cost. Pure function of (params, scenario, rng).
montecarlo.py    repeats model.py, collects percentiles and the variance decomposition.
report.py        formats results as text or CSV. No computation.
__main__.py      CLI entry point. Argument parsing only.
tests/           see §7.
```

Dependency direction is strictly one way:

```
__main__.py -> report.py -> montecarlo.py -> model.py -> params.py
```

`params.py` imports nothing from this project. `model.py` never formats output. `report.py` never computes a
derived quantity — if a number appears in a report, it was computed upstream and passed in.

## 4. Naming

Use the symbol names from `SPEC.md` exactly, as they appear in the briefing documents. Do not rename them to
be more descriptive; the whole point is that a reader can trace a variable from the briefing to the code.

| Code name | Meaning |
|---|---|
| `k` | tokens per attempt per implementation, by story class |
| `p` | per-attempt success probability, by story class |
| `d` | probability an implementation carries a defect |
| `m` | probability an independently derived oracle set misses a defect it should catch |
| `rho` | fraction of implementation errors the check is blind to by construction |
| `q_rev` | probability human review misses a defect that reached it |
| `f` | auto-merge fraction |
| `e_gate` | probability a defect survives the automated oracle set |
| `e` | escape rate — probability a merged story carries a functional defect, after review |
| `k_scale` | epistemic global multiplier on `k`, median 1 |
| `repo_scope_tokens` | Step 10 apparatus tokens, repository scope |
| `q_rev` | probability human review misses a defect that reaches it |
| `S` | criteria-authoring hours per story |
| `R` | review hours per story actually reviewed |
| `I` | hours to resolve one escaped defect |
| `N_impl` | independent implementations generated per story, by class |
| `theta` | repo-level common factor, drawn once per run |
| `s` | context-switch cost per human touch, hours |
| `b` | human touches handled per batched session |

Greek letters are spelled out (`rho`, `theta`, `lambda_e`). Class names are the strings `"routine"`,
`"standard"`, `"hard"` — never abbreviated, never an enum with different casing.

## 5. Parameter provenance is mandatory

Every parameter in `params.py` is declared with a `Param` record carrying `value`, `kind`, and `source`.
`kind` is exactly one of:

- **`PRICE`** — an organisational fact. Loaded engineer cost, incident cost, token price. Changes with your
  contracts, not with your engineering.
- **`CALIBRATED`** — fitted from telemetry. Token cost per attempt, success probability, mutation score,
  defect rate. These are the numbers a pilot produces, and the defaults shipped here are **illustrative
  placeholders that must be replaced before any real decision**.
- **`POLICY`** — a choice you make. How many implementations to generate, what escape rate to accept per
  tier, whether to batch adjudication. These differ by scenario and are the levers under discussion.

A parameter with no `source` string is a bug. `tests/test_params.py` enforces it.

## 6. Modelling rules

- **Derive, do not assert.** If a quantity can be computed from more primitive parameters, compute it. The
  escape rate is derived in two stages — `e_gate = d(rho + (1-rho)m)` then `e = e_gate(f + (1-f)q_rev)` — and
  is never entered directly. Adding a free parameter that could have been derived is a design regression. Keep
  both stages as named intermediates; a reader checking arithmetic against SPEC.md §4.1 needs to see them.
- **Report percentiles, never a mean.** The distribution is right-skewed. Any function returning a single
  summary number for a cost is wrong; return the distribution or named percentiles.
- **The common factor is drawn once per run, not per story.** `theta` represents repo-level conditions shared
  by every story. Drawing it inside the story loop destroys the correlation the model exists to capture, and
  is the single easiest way to silently break this program.
- **`theta` loads primarily on `e` and `f`, only weakly on `p`.** This is deliberate and counter-intuitive:
  correlated failure of the gate costs an order of magnitude more than correlated failure of generation.
- **Truncate every attempt loop, and use the truncated expectation.** `A_max` is not optional, and `E[A]` is
  `sum(q^k for k in range(A_max))`, never `1/p`. Using `1/p` alongside a cap makes the published totals
  irreproducible from the published parameters.
- **Every random scaling must be mean-preserving.** A lognormal needs `mu = −sigma²/2`; a branch multiplier
  needs its off-branch value set so the expectation is 1. `exp(lambda·theta)` without the `−lambda²/2`
  correction, and a cluster multiplier applied only on the clustered branch, together inflated the escape
  rate by 51% in an earlier version. `tests/test_properties.py` asserts realised means equal nominal means at
  200,000 iterations, per scenario. **This is the most important test in the suite.**
- **Draw per implementation, not per story times N.** Implementations run in isolated contexts and converge
  independently. Multiplying one draw by `N_impl` preserves the mean and inflates the variance by ~70%.
- **Separate epistemic from aleatory draws.** Parameter uncertainty (§3.5 of SPEC) and the repo common factor
  are different quantities and must remain independently switchable.
- Maintenance and design decay are **out of scope** and must not be added to the build cost. They belong to a
  separate ownership model. See SPEC.md §9.

## 7. Verification

This repository practises what it models, in miniature.

- **The acceptance suite is written before the implementation** and lives in `tests/test_acceptance.py`. It
  is derived from `SPEC.md` only. It must never be edited to make an implementation pass — if it is wrong,
  fix `SPEC.md` first, then regenerate.
- **Property tests** (`tests/test_properties.py`) assert invariants that come from arithmetic rather than
  from the spec text: cost is monotonically non-decreasing in story count; P50 ≤ P80 ≤ P95; token cost equals
  tokens × price exactly; scenario totals equal the sum of their components; identical seeds give identical
  results.
- **A differential reference** (`tests/reference.py`) computes the deterministic expected-value case the slow
  and obvious way — nested loops, no vectorisation, no shortcuts. The main model run at zero variance must
  agree with it to within floating-point tolerance.
- **Regression fixtures** (`tests/fixtures/`) pin the published scenario figures from the briefing. If a
  change moves them, that is either a bug or a decision that must be recorded in `SPEC.md` §11.

Run `python -m pytest` before declaring anything done.

## 8. Prohibitions

- No third-party imports beyond NumPy (tests may additionally use `pytest`).
- No global mutable state. No module-level caches. No singletons.
- No random draws outside an injected `numpy.random.Generator`.
- No I/O in `model.py` or `montecarlo.py` — not even logging.
- No silent fallbacks. If a parameter is missing or a scenario name is unknown, raise; never substitute a
  default and continue.
- No `float` comparison with `==` outside tests that use an explicit tolerance.
- Do not add a scenario by copying an existing one and editing numbers. Scenarios are declared as a set of
  active process steps; the parameters follow from that. See SPEC.md §6.

## 9. Budgets

- A full run — 5 scenarios × 10,000 iterations × 160 stories — completes in **under 5 seconds** on one core. Vectorised, this is a small problem; if it is slow, the story loop has not been vectorised.
- Peak memory under 500 MB. The largest array is `(iterations, n_hard)` per draw; chunk the iteration axis if a user requests more than 200,000 iterations.
- No single function exceeds 50 lines. No module exceeds 400.
- Public API surface: `run_scenario`, `run_all`, `Scenario`, `Params`, `Result`. Adding to this list requires
  a note in SPEC.md §11.

## 10. Style

- Type hints on every public function. `from __future__ import annotations` at the top of every module.
- Dataclasses for records, frozen where the value is not meant to change after construction. NumPy arrays live only inside `model.py` and `montecarlo.py`; `Result` exposes plain floats and dicts so `report.py` never touches an array.
- Docstrings state the *why* and cite the SPEC section number. The *what* should be evident from the names.
- Prefer a named intermediate variable over a clever one-liner. This code will be read by someone checking
  arithmetic against a document, and their job should be easy.
