# Agentic Coding Cost Estimator

A Monte Carlo estimator for the cost of building software under agentic coding, across five levels of process
automation. Python 3.11+ and NumPy, deterministic given a seed, no network.

It answers one question: **for a portfolio of stories, what does the build cost distribution look like, and
what is actually driving the spread?**

---

## Quick start

```bash
python __main__.py                       # all five scenarios, 160-story default portfolio
python __main__.py --iterations 50000    # tighter percentiles
python __main__.py --stories 40 28 12    # routine, standard, hard
python __main__.py --scenario all_three --format csv
python __main__.py --sensitivity rho     # sweep one parameter, report effect on P50 and P95
python __main__.py --deterministic       # variance off; reproduces the published point estimates
python __main__.py --decompose --iterations 150000   # variance decomposition
```

The modules sit flat at the repository root, so `python <path-to-repo>` works too. Requires
Python 3.11+ and NumPy (`pip install numpy`). Nothing else.

### Changing the numbers

Every parameter is configurable, carries its provenance, and declares the range over which
sweeping it is meaningful:

```bash
python __main__.py --list-params         # all 56 parameters: value, range, kind, source
python __main__.py --list-steps          # which of the ten steps each scenario activates
python __main__.py --set w=200 --set b=1 # override anything; b=1 makes every touch an interruption
python __main__.py --set all_three.oracle_tokens=900e6    # per-scenario policy
python __main__.py --config example-config.json           # a JSON object of the same overrides
```

`example-config.json` ships with the repository. It is annotated — any key beginning with an
underscore is a comment and is ignored, since JSON has no comment syntax — and it lists the
parameters in the order worth replacing them, starting with the prices you already know. Run
it unedited and you get the shipped defaults; copy it and change the ones you have measured.

An unknown parameter name raises rather than defaulting, and an integer parameter refuses a
fractional override rather than truncating it — silently accepting `A_max=5.5` would make a
published total irreproducible from the parameter you thought you set.

---

## The five scenarios

Each is defined by which of the ten process steps are active, not by a set of hand-tuned numbers. They match
the briefing set's A / B / C / D / D+ exactly.

| Scenario | Flag | What is automated |
|---|---|---|
| **A. Execute only** | `execute_only` | Code generation. Humans write every criterion and read every diff. |
| **B. + Decide** | `execute_decide` | Adds spec oracles: source-document conformance, completeness sweeps, precedent checks. Humans still read every diff. |
| **C. + Deliver** | `execute_deliver` | Adds the verification apparatus instead: frozen acceptance suites, mutation scoring, independent oracles, cross-implementation comparison, a calibrated gate. |
| **D. All three** | `all_three` | Both of the above. |
| **D+. All three + quality** | `all_three_quality` | Same process, deliberately spending more tokens on verification depth rather than on displacing human hours. |

**B and C are the two single-phase additions to A**, and running both is what makes the marginal contribution
of each phase visible. Deliver alone saves more than Decide alone, and the two together save more than the sum
of their parts — better specifications reduce escapes, and better oracles catch specification ambiguity.

The most instructive comparison in the whole set is **B against C**: B has better criteria and still a high
escape rate, because automating Decide does not freeze the acceptance suite, so the check remains co-derived
with the implementation. **Better specifications alone do not buy independence.**

---

## Reading the output

```
D. Decide + Execute + Deliver
  Cost      P50     $69,097  P80     $84,918  P95    $121,930   P95/P50  1.76
  Tokens      3.71B      $11,049                                share   14.8%
  Hours         351  0.42 FTE over 26 weeks                     stories   160
  Escapes   e =  2.40%  3.8 stories escape                      fallback   0.7
  Breakdown at P50:
    tokens $11,049  criteria $23,263  review $3,600  incidents $9,600  spec $12,000  arch $1,500  switch $1,506  fallback $0  restr $2,030
  Variance  escape 71% ±0.4  m 1% ±0.5
            below the estimator's own noise, so indistinguishable from zero: d, k_scale, q_rev, tokens, S
            (not a partition; shares do not sum to 100%)
```

Four things to look at, in order of how much they should change your decision.

**The P95, not the P50.** The distribution is right-skewed and the P50 is the number that will be quoted back
at you. What matters is whether the recommendation survives its own bad case — and **scenario D's P95
($121,930) sits below scenario A's median ($197,249)**. Note also that D+ costs more at the P50 and *less* at
the P95: quality investment buys tail reduction, not expected-value reduction. (Figures from the run above, at
40,000 iterations and seed 7. They reproduce the briefing set's published $120,000 and $197,600 to within
Monte Carlo error; `SPEC.md` §6 pins the published values.)

**The variance decomposition, and read it per scenario.** Escaped defects dominate everywhere, but not by the
same margin, and the second driver is not the same either:

| Source frozen | A | B | C | D | D+ |
|---|---|---|---|---|---|
| **Escape** | **70%** | **77%** | **43%** | **71%** | **46%** |
| Criteria hours `S` | — | — | **9%** | — | **9%** |

A dash means the share did not clear two standard errors of its own estimator and so is not distinguishable
from zero. Every share is printed with that standard error, from a paired bootstrap over the iteration axis,
and the report names unresolved sources rather than quoting each a spurious one percent. Raising
`--iterations` shrinks the errors as `1/sqrt(n)`.

**In C and D+, escape falls to 43–46% and criteria authoring becomes the clear second driver.** C carries the
unaided `S_manual` = 3.0, which makes criteria its largest single cost line; D+ has the lowest escape rate in
the set, so the same spread in `S` is a larger share of a smaller total. Once the apparatus has suppressed
escaped defects, **the next largest uncertainty is how long it takes humans to write criteria** — and that is
one of the cheaper parameters to measure. Quoting scenario D alone would hide this.

These are one-at-a-time freezes on a non-linear model, so they are not a partition and do not sum to 100%.

**The token share.** It rises as total cost falls, from about 1.3% to about 38%. This is the correct
direction. Do not govern to a token budget: the model will show you that underspending on tokens is the more
expensive error.

**The escape rate.** It is derived, not entered:

```
e_gate = d × [ρ + (1 − ρ)m]              survives the automated oracle
e      = e_gate × [f + (1 − f)q_rev]     also survives whatever review follows
```

Four inputs, and each moves because a step was switched on: Steps 2–3 lower `d`, Step 5 collapses `ρ`, Step 6
collapses `m`, Step 8 sets `f`. If you change nothing else in this model, replace those four with your own
measurements. Note the counter-intuitive term — raising `f` *raises* the escape rate for a fixed `e_gate`,
because it removes the second filter. Automating review is only safe as part of the same change that installs
the oracle apparatus.

---

## Before you trust a number

**The shipped calibrated parameters are illustrative placeholders.** They reproduce the figures in the
briefing set, which makes the code checkable, but they are not your organisation's numbers and using them for
a real decision would be a mistake.

Replace them in this order, easiest and highest-value first:

1. **Prices** — `w`, `w_inc`, `c`. You already know these.
2. **`m` and `q_rev`** — one mutation-testing run gives `m = 1 − mutation score`; the random sampled-review stream gives `q_rev`, which is not zero.
3. **`d`** — the failure rate of fresh implementations against the oracle set, divided by the mutation score.
4. **`k` and `p` per class** — two or three metered spikes per class against your real repository. At $10–50
   a spike this is the cheapest decision-relevant information available anywhere in this exercise.
5. **`S`, `R`, `I`** — time-tracking on one instrumented epic.
6. **`rho`** — not measured. Read it off the menu in `SPEC.md` §3.5 according to how you have structured
   verification.
7. **`lambda_e`, `lambda_f`, `p_cluster`** — the hardest, and they need several epics of history. Until then
   they are structural assumptions; run `--sensitivity` on them rather than believing the defaults.

`SPEC.md` §8 gives the provenance of every parameter. Every entry in `params.py` carries its own `source`
string, and a parameter without one fails the test suite.

---

## What the model deliberately leaves out

Say these aloud whenever you present a number from it.

- **Design decay.** The escape rate counts functional defects. A story that ships correct behaviour through a
  bad decomposition scores clean here and makes everything after it more expensive. Watch change amplification
  and cost-per-Routine-story instead; neither is in this model.
- **Maintenance and cost of ownership.** Out of scope. Never infer maintenance from build cost.
- **Calendar duration.** The saving this model reports is a **headcount** reduction at roughly constant
  duration, not a delivery speed-up — the surviving work requires authority, and authority does not
  parallelise. FTE is reported alongside cost so the point is hard to miss.
- **The value of Steps 4, 9 and 10.** Reuse, cross-story defect detection, and design conformance are real
  but poorly quantified, so they are under-parameterised. The model therefore **understates** the case for the
  full process rather than overstating it.

---

## How this maps to the ten-step process

Every step changes a parameter or adds a cost term:

| Step | Model effect |
|---|---|
| 1 System specification | Lowers `k`, raises `p`, adds amortised hours |
| 2 Criteria vs governing sources | Lowers `d` and `S`, adds Decide tokens |
| 3 Completeness sweep | Folded into the Step 2 effect; adds the adjudication touch |
| 4 Program design and slicing | Contributes to the `d` reduction |
| 5 Frozen acceptance suite | Drops `rho` sharply; switches `k`/`p` to the frozen values |
| 6 Mutation scoring + a check from another route | Drops `m` and `rho` further; adds oracle tokens |
| 7 N implementations, compared | Sets `N_impl`; adds generation and cross-testing tokens |
| 8 Tiered gate | Sets `f`; changes what "review" means and therefore `R` |
| 9 Integration verification | Adds integration tokens |
| 10 Repo-scope gates | Adds the restructuring reserve |

Full detail in `SPEC.md` §7.

---

## Project layout

```
params.py             every constant and calibrated value — the only place numbers live
scenarios.py          the ten steps, and which parameters each scenario's steps select
model.py              one vectorised pass: portfolio -> cost, all iterations at once
montecarlo.py         percentiles, variance decomposition, sensitivity sweeps
report.py             formatting only, no computation, no NumPy arrays
__main__.py           CLI
reference_model.py    the supplied reference that generated the published figures
tests/                acceptance suite, property tests, two differential references, fixtures
```

Plain functions and dicts throughout — no classes anywhere, checked mechanically by
`tests/test_deps.py`. Dependency direction is strictly one way, params -> scenarios -> model
-> montecarlo -> report -> `__main__`, also checked mechanically.

`CLAUDE.md` is the architectural constitution — read it before changing anything. `SPEC.md` is the model
specification and the source the acceptance suite is derived from: **if the tests and the code disagree, fix
the code; if the spec and the tests disagree, fix the spec first.**

---

## Development

```bash
python -m pytest                    # everything
python -m pytest tests/test_acceptance.py -v
python -m pytest tests/test_properties.py     # invariants from arithmetic, not from the spec text
```

The test suite is structured the way the model recommends: an acceptance suite written from `SPEC.md` before
the implementation and never edited to make code pass; property tests asserting invariants derived from
arithmetic; a slow, obvious differential reference the fast path must agree with; and pinned fixtures for the
published figures.

**There are two differential references, and they check different things.**

`tests/reference.py` is a pure-Python nested-loop rewrite of *this* model — no NumPy, no vectorisation, the
attempt expectation summed term by term and the fallback probability found by enumerating all 2^N convergence
outcomes. It is structurally unlike the vectorised implementation, so the two are unlikely to share a bug.

`reference_model.py` is the *supplied* reference that generated the published figures — a second independent
implementation with its own draw order. The deterministic pass agrees with it on all 70 figures across all
five scenarios to 1.8e-16; the Monte Carlo percentiles agree to within 1.2%, which is sampling error rather
than disagreement, since the two consume their random streams in different orders.

Neither catches the one error vectorisation really invites — drawing the common factor per story rather than
per iteration, which produces plausible numbers and quietly removes the correlation. That is caught by
measuring over-dispersion: escape counts run 2.9x to 21.7x the binomial variance when `theta` is shared, and
1.00x when it is not.

If a change moves a pinned figure, that is either a bug or a decision — record it in `SPEC.md` §11.
