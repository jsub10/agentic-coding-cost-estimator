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
  iteration, shared by every story in that iteration. Arrays are shaped `(iterations,)` for run-level draws,
  `(iterations, n_stories)` for story-level draws and `(iterations, stories_in_class, N_impl)` for
  per-implementation draws, and they must never be conflated. A `theta` array shaped `(iterations, n_stories)`
  silently removes the correlation the model exists to capture and no shape assertion will catch it.
  `tests/test_properties.py` catches it by measuring the over-dispersion of the escape *count* against the
  binomial: shared `theta` gives 3.0x to 22.4x across the five scenarios, and a per-story `theta` gives 1.00x.
- **All parameters live in `params.py`**, and the per-scenario ones in `scenarios.py`'s `SCENARIO_POLICY`
  under the same record shape. No numeric literal that a user might want to change appears anywhere else. If
  you find yourself typing `0.30` in `model.py`, it belongs in the registry with a name and a source.
- **Every parameter carries its provenance.** Each entry records whether it is a PRICE, a CALIBRATED value, a
  POLICY choice or an EPISTEMIC width, and where its value came from. See §5.
- **Money in dollars, time in hours, tokens in whole tokens.** No mixed units, no millions-of-tokens
  shorthand inside the model — convert only at the reporting boundary.
- **`float64` throughout.** Do not downcast to save memory; the token counts run to 10^10 and the cost
  differences that matter are in the hundreds.

## 3. Layout

```
params.py        constants and calibrated values, with provenance. The only place numbers live.
scenarios.py     the ten process steps, and which parameters each scenario's active steps select.
escape.py        the escape equation and the mean-preserving scalings applied to it.
model.py         one simulation run: portfolio -> cost. Pure function of (params, scenario, rng).
montecarlo.py    repeats model.py, collects percentiles, the variance decomposition, sweeps.
report.py        formats results as text or CSV. No computation.
__main__.py      CLI entry point. Argument parsing and one config-file read.
reference_model.py   the *supplied* reference that generated the published figures. Not project
                 source: exempt from every rule in this file, and excluded by tests/test_deps.py.
tests/           see §7.
```

Seven modules, not the five this section originally fixed. `params.py` split from `scenarios.py` because the
registry plus the ten-step resolution does not fit in one 400-line file, and `escape.py` split from
`model.py` for the same reason when the covariance correction landed. Both are recorded in SPEC.md §11.

Dependency direction is strictly one way, and `tests/test_deps.py` checks it by rank:

```
params.py -> scenarios.py -> escape.py -> model.py -> montecarlo.py -> report.py -> __main__.py
```

Read that as "may import from anything to its left". It is not a call chain: `report.py` imports `params`
and `scenarios` for the registry listings and never imports `montecarlo`, and `__main__.py` imports
`montecarlo` and `report` directly.

`params.py` and `escape.py` import nothing from this project. `model.py` never formats output. `report.py`
never computes a derived quantity — if a number appears in a report, it was computed upstream and passed in —
and never imports NumPy, which is how that is enforced.

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
| `k_scale` | epistemic global multiplier on `k`, mean 1 |
| `repo_scope_tokens` | Step 10 apparatus tokens, repository scope |
| `S` | criteria-authoring hours per story |
| `R` | review hours per story actually reviewed |
| `I` | hours to resolve one escaped defect |
| `N_impl` | independent implementations generated per story, by class |
| `theta` | repo-level common factor, drawn once per run |
| `s` | context-switch cost per human touch, hours |
| `b` | human touches handled per batched session |
| `A_max` | attempt cap; `n_compare_min` is the converged implementations a story needs |
| `e_scale` | the mean-preserving random multiplier applied to `e` within a run |
| `gamma` | the scalar that makes `E[e_base × e_scale]` equal the derived `e` (SPEC.md §5) |

Greek letters are spelled out (`rho`, `theta`, `lambda_e`). Class names are the strings `"routine"`,
`"standard"`, `"hard"` — never abbreviated, never an enum with different casing.

## 5. Parameter provenance is mandatory

Every parameter in `params.py` is declared through `param_record()`, which carries `value`, `kind`, `source`,
`low`, `high`, `unit` and `doc`, and refuses to build a record missing any of them. The `low`/`high` pair is
the range over which sweeping the parameter is meaningful, and drives `--sensitivity`. `scenarios.py`
declares its per-scenario POLICY parameters in the same shape, so one registry walk covers both.

`kind` is exactly one of:

- **`PRICE`** — an organisational fact. Loaded engineer cost, incident cost, token price. Changes with your
  contracts, not with your engineering.
- **`CALIBRATED`** — fitted from telemetry. Token cost per attempt, success probability, mutation score,
  defect rate. These are the numbers a pilot produces, and the defaults shipped here are **illustrative
  placeholders that must be replaced before any real decision**.
- **`POLICY`** — a choice you make. How many implementations to generate, what escape rate to accept per
  tier, whether to batch adjudication. These differ by scenario and are the levers under discussion.
- **`EPISTEMIC`** — the width of our ignorance about a CALIBRATED value, not a quantity of the world:
  `sigma_d`, `sigma_m`, `sd_q_rev`, `sigma_S`, `sigma_k_scale`. Admitted as a fourth kind by the SPEC.md §11
  entry of 2026-08-17, because SPEC.md §3.5 declares them and SPEC governs.

A parameter with no `source` string is a bug. `tests/test_params.py` enforces it, and walks the per-scenario
policy block in `scenarios.py` under the same rule.

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
- **Centring each scaling is not enough when two of them share `theta`.** `e_base` and `e_scale` are both
  functions of the common factor and are negatively correlated through it, so their product is biased low
  even when each factor has expectation 1 — by 2.0% to 2.7% in the gated scenarios. The correction is the
  scalar `gamma` of SPEC.md §5, computed once per scenario by Cameron–Martin in `escape.py`. Any new random
  factor that touches `theta` must be checked the same way: mean-preserving individually is a necessary
  condition, not a sufficient one.
- **Draw per implementation, not per story times N.** Implementations run in isolated contexts and converge
  independently. Multiplying one draw by `N_impl` preserves the mean and inflates the spread by ~70% —
  epic token σ 145M → 250M, CV 4.1% → 7.1%.
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
- **A second differential reference** (`reference_model.py`, at the repository root) is the *supplied*
  implementation that generated the published figures, with its own draw order. `tests/test_reference_model.py`
  checks the deterministic pass against it on 80 figures across the five scenarios, and the Monte Carlo
  percentiles to sampling error. It carries the pre-`gamma` covariance defect, and the test asserts that it
  does rather than assuming it, so the looser bound on gated scenarios stays justified.
- **Regression fixtures** (`tests/fixtures/`) pin the published scenario figures from the briefing. If a
  change moves them, that is either a bug or a decision that must be recorded in `SPEC.md` §11.
- **The registry and the import allowlist** are checked mechanically too: `tests/test_params.py` walks every
  parameter record for provenance and range, and `tests/test_deps.py` enforces §2's dependency rules, §3's
  one-way direction, the no-classes decision, and the no-I/O rule.

Run `python -m pytest` before declaring anything done. The suite is 787 tests and takes four to five minutes:
about two of them in the two variance-decomposition fixtures, which run the whole freeze-one-source sweep,
and most of the rest in the 200,000-iteration mean-preservation checks.

## 8. Prohibitions

- No third-party imports beyond NumPy (tests may additionally use `pytest`).
- No global mutable state. No module-level caches. No singletons.
- No random draws outside a `numpy.random.Generator` derived deterministically from the injected seed.
  `model.simulate` takes a `Generator` and spawns one child per draw site from it; `montecarlo._collect`
  constructs one `Generator` per chunk from `(seed, chunk_index)`. Both are required by SPEC.md §5 — a single
  shared stream lets a perturbed discrete draw desynchronise every draw after it, and lets one chunk corrupt
  its successors, which is what put a ±2-point noise floor under the variance decomposition. Neither is a
  licence to seed from anything but the caller's seed.
- No I/O in `escape.py`, `model.py` or `montecarlo.py` — not even logging. The single config-file read lives
  in `__main__.py`.
- No silent fallbacks. If a parameter is missing or a scenario name is unknown, raise; never substitute a
  default and continue. The one documented exception is a config key beginning with an underscore, which
  declares itself a comment; every other unknown name still raises.
- No `float` comparison with `==` on a *computed* quantity, outside tests that use an explicit tolerance.
  Comparing a value against the same stored value it came from is identity rather than numerics, and is
  permitted where it is deliberate and commented: `params.coerce` rejecting a fractional override of an
  integer parameter, and `report.format_sensitivity` marking the baseline row of a sweep.
- Do not add a scenario by copying an existing one and editing numbers. Scenarios are declared as a set of
  active process steps; the parameters follow from that. See SPEC.md §6.

## 9. Budgets

- A full run — 5 scenarios × 10,000 iterations × 160 stories — completes in **under 5 seconds** on one core.
  Measured: 1.3 s wall and 5.3 s of CPU, so it is at the budget on one core and under it on any laptop.
  Vectorised, this is a small problem; if it is slow, the story loop has not been vectorised.
- Peak memory under 500 MB. Measured 409 MB on the default run and 422 MB on the worst case in the shipped
  set, D+ at 200,000 iterations. The largest arrays are the per-implementation draws, shaped
  `(chunk, stories_in_class, N_impl)`, and the two per-story uniform matrices behind the reviewed and escaped
  counts. **The iteration axis is chunked unconditionally**, not only above some iteration count:
  `montecarlo.CHUNK_ELEMENTS` bounds the widest array at 2,000,000 elements and the chunk size follows from
  the scenario. Chunk boundaries are part of the model's determinism, not just its memory profile — see §8.
- No single function exceeds 50 lines. No module exceeds 400. `reference_model.py` is supplied rather than
  written here and is exempt; nothing else is.
- Public API surface: `montecarlo.run_scenario`, `montecarlo.run_all`, `montecarlo.deterministic_all`,
  `montecarlo.savings_against_baseline`, `montecarlo.superadditivity`, `montecarlo.sensitivity`,
  `scenarios.resolve_scenario`, `params.default_params`. The `Scenario` / `Params` / `Result` records this
  list originally named are plain dicts, per the no-classes decision in SPEC.md §11. Adding to this list
  requires a note in SPEC.md §11.

## 10. Style

- Type hints on every public function. `from __future__ import annotations` at the top of every module.
  **The code does not currently meet the first half of this rule** — the arithmetic functions in `escape.py`
  and `model.py` are unannotated, because they take and return either scalars or arrays and a truthful
  annotation would say so at more length than it is worth. The rule stands as written; closing the gap means
  either annotating them or narrowing the rule deliberately, not letting the drift continue.
- **Plain functions and dicts. No classes anywhere**, at the owner's instruction, recorded in SPEC.md §11 and
  checked by `tests/test_deps.py`. This supersedes the dataclass rule this section originally carried:
  `Scenario`, `Params` and `Result` are dicts built by `resolve_scenario()`, `default_params()` and
  `run_scenario()`. NumPy arrays live only inside `escape.py`, `model.py` and `montecarlo.py`; the result dict
  exposes plain floats and dicts so `report.py` never touches an array, which `tests/test_deps.py` enforces
  by forbidding `report.py` to import NumPy at all.
- Docstrings state the *why* and cite the SPEC section number. The *what* should be evident from the names.
- Prefer a named intermediate variable over a clever one-liner. This code will be read by someone checking
  arithmetic against a document, and their job should be easy.
