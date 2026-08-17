# SPEC.md — The Estimation Model

Specification for the Monte Carlo estimator. This document is the source of truth: the acceptance suite is
derived from it, and no behaviour exists in the code that is not stated here.

Companion reading, in the briefing set: `cio-briefing-v6.md` §7 (why token cost cannot dominate), §8 (the ten
steps), §11 (human time and availability); `cost-model-simplified.md` (the arithmetic); and
`agentic-coding-estimation-model.md` (the stochastic treatment this implements).

---

## 1. What the model computes

For a portfolio of stories and a chosen level of process automation, the distribution of **build cost**:

```
Build cost = token cost
           + criteria authoring
           + review and adjudication
           + escaped-defect response
           + system specification and architecture (amortised)
           + switch cost
           + restructuring reserve
           + fallback capacity
```

Reported as **P50 / P80 / P95**, never as a mean, with a variance decomposition naming which inputs drive the
spread.

Implemented in Python 3.11+ with NumPy, vectorised across Monte Carlo iterations, deterministic given a seed.

**Out of scope:** maintenance, design decay, and cost of ownership. These scale with shipped surface area
rather than with build effort and belong to a separate model. Including them here would invite the error of
inferring maintenance from build cost.

---

## 2. Units and conventions

| Quantity | Unit |
|---|---|
| Money | US dollars |
| Time | hours |
| Tokens | whole tokens (convert to millions only when reporting) |
| Probabilities | fractions in [0, 1], never percentages |

Story classes are exactly three: `routine`, `standard`, `hard`. Classification is by **oracle closure** — can
a machine decide whether this is correct? — not by size. A large, well-specified, test-decidable story is
Routine; a small ambiguous one is Hard. Concurrent and ordering-sensitive code is Hard by construction
regardless of specification quality, because the determinism the whole apparatus assumes does not hold there.

---

## 3. Inputs

### 3.1 Portfolio (user-supplied)

| Name | Default | Meaning |
|---|---|---|
| `n_routine` | 80 | count of Routine stories |
| `n_standard` | 56 | count of Standard stories |
| `n_hard` | 24 | count of Hard stories |

Defaults give the 160-story epic used throughout the briefing set, so the shipped output is directly
comparable with the published figures.

### 3.2 Prices — `kind = PRICE`

Organisational facts. Change with contracts, not with engineering.

| Symbol | Default | Meaning | Source |
|---|---|---|---|
| `w` | 150 | loaded engineer cost, $/hr | your finance function |
| `w_inc` | 400 | incident-response cost, $/hr | your finance function; higher than `w` because incidents pull senior people out of planned work |
| `c` | 3.0 | blended token cost, $/M tokens | your provider invoices, blended across model tiers actually used |

### 3.3 Calibrated parameters — `kind = CALIBRATED`

**These are fitted from your own telemetry. The shipped values are illustrative placeholders and must be
replaced before any real decision.** §8 states where each one comes from.

Per story class. **Token cost per attempt turns on one thing — whether Step 5 has frozen an acceptance
suite** — because without a machine verdict the session has no stopping rule:

| Symbol | Routine | Standard | Hard | Meaning |
|---|---|---|---|---|
| `k_frozen` | 0.20M | 1.3M | 8.8M | tokens per attempt per implementation, with a frozen acceptance suite |
| `k_unfrozen` | 0.25M | 1.6M | 11.0M | same, without one — no machine verdict, so sessions run longer |

**Per-attempt success turns on two things, and needs four tables, not two.** A frozen suite (Step 5) tells the
agent when it is done; conformed criteria (Steps 2–3) tell it what done means. These are independent
improvements and both raise `p`, so the table is selected by the *pair* `(Step 5 active?, Steps 2–3 active?)`:

| Symbol | Step 5 | Steps 2–3 | Routine | Standard | Hard | Scenarios |
|---|---|---|---|---|---|---|
| `p_unfrozen` | — | — | 0.85 | 0.50 | 0.28 | A |
| `p_unfrozen_specced` | — | ✓ | 0.87 | 0.55 | 0.32 | B |
| `p_frozen` | ✓ | — | 0.90 | 0.65 | 0.40 | C |
| `p_frozen_specced` | ✓ | ✓ | 0.92 | 0.70 | 0.45 | D, D+ |

Earlier versions of this section declared only `p_frozen` and `p_unfrozen`. That is **not sufficient to
reproduce §6's pinned outputs**, and the discrepancy is not small: two tables give B 1.56B tokens against a
pinned 1.49B, and D 3.83B against a pinned 3.69B. D's pinned fallback count settles it independently — two
tables give 1.0 fallback stories, the pinned figure is 0.4, and `p_frozen_specced` gives 0.448. The four-table
form is also the more faithful one, because it keeps every parameter a consequence of which steps are active
rather than of which scenario is being run (§6). Recorded in §11.

Organisation-wide:

| Symbol | Default | Meaning |
|---|---|---|
| `d_base` | 0.30 | probability a fresh implementation carries a defect |
| `d_specced` | 0.24 | same, when criteria have passed spec oracles (Steps 2–3) |
| `m_unscored` | 0.30 | miss rate of an oracle set of unknown strength |
| `m_scored` | 0.06 | miss rate at a 94% mutation score |
| `m_deep` | 0.02 | miss rate at a 98% mutation score with wider property generation |
| `q_rev` | 0.35 | probability human review misses a defect that reaches it — measured from the random sampled-review stream, and emphatically not zero |
| `S_manual` | 3.0 | criteria-authoring hours per story, unaided |
| `S_oracled` | 1.0 | same, with spec oracles running |
| `R_large` | 2.5 | review hours per reviewed story when diffs are unconstrained |
| `R_gated` | 1.5 | same, when review means adjudicating a flagged question |
| `I` | 12.0 | hours to resolve one escaped defect |
| `sigma_k` | 0.35 | lognormal shape for per-attempt token variation |
| `A_max` | 5 | attempt cap before falling back to human execution |
| `fallback_hours` | 8.0 | human execution of one story that hit the cap |
| `adjudication_rate` | 0.40 | share of stories raising a flagged question at Step 7 (scenarios with Step 7 active only) |
| `restructure_fraction` | 0.05 | capacity reserved for restructuring stories fired by Step 10 |
| `s` | 0.25 | context-switch cost per human touch, hours |

Scheduling — `kind = POLICY`, because you choose it rather than measure it (§8):

| Symbol | Default | Meaning |
|---|---|---|
| `b` | 6 | human touches handled per batched session |

`b` was previously named in the hours equation (§4.4) and in the symbol table without ever being given a
value, which forced a builder to invent one — the exact failure the provenance rule exists to prevent. The
default of 6 is recovered from §6's pinned figures for scenario A: 320 touches at `s` = 0.25 must produce the
13.3 switch hours that closes A's 1,173-hour total and its $215,800 human cost. **`b = 1` means every touch
arrives as an interruption**, and the model will show what that costs; the switch line is linear in `1/b`, so
sweeping it is cheap and worth doing.

Reporting only — `kind = POLICY`. These scale the FTE line required by §10 and enter no cost:

| Symbol | Default | Meaning |
|---|---|---|
| `calendar_weeks` | 26 | the stated calendar duration FTE is quoted against |
| `hours_per_fte_week` | 32 | productive engineering hours per FTE-week, net of overheads |

### 3.4 Correlation parameters — `kind = CALIBRATED`

| Symbol | Default | Meaning |
|---|---|---|
| `lambda_e` | 0.55 | loading of the common factor on escape rate |
| `lambda_f` | 0.40 | loading on auto-merge fraction |
| `lambda_p` | 0.15 | loading on per-attempt success probability |
| `p_cluster` | 0.15 | probability a run is a clustered-escape run |
| `cluster_mult` | 3.0 | escape-rate multiplier in a clustered run |

**`lambda_e` and `lambda_f` are deliberately much larger than `lambda_p`.** Correlated failure of the gate is
worth roughly an order of magnitude more in dollars than correlated failure of generation: an unfavourable
move in `p` costs extra tokens, while a doubling of `e` costs incident hours at premium rates.

### 3.5 Parameter uncertainty — `kind = EPISTEMIC`

The parameters above are estimates, and we do not know them to better than a factor. That ignorance is a
larger source of uncertainty than trajectory noise, and a model that reports percentiles while treating its
own inputs as exact is understating its range.

Each of these is drawn **once per Monte Carlo run** — they are beliefs about one organisation, not
story-level noise:

| Parameter | Distribution | Rationale |
|---|---|---|
| `d` | Lognormal, **mean** = nominal, σ = 0.20 | Estimated from a failure rate over one epic; ±20% is optimistic |
| `m` | Lognormal, **mean** = nominal, σ = 0.30, clipped to [0,1] | Mutation score varies by suite and by domain |
| `q_rev` | Beta, mean 0.35, sd 0.08 | Estimated from a 5–10% sample, so the sample itself is small |
| `S` | Lognormal, **mean** = nominal, σ = 0.25 | Criteria-authoring hours vary widely by story and by author |
| `k_scale` | Global lognormal scale factor, **mean** 1, σ = 0.15 | Applies to all classes together; per-class `k` moves with the harness |

Every lognormal above is drawn as `nominal × exp(σZ − σ²/2)` with `Z ~ Normal(0,1)`, which puts the **mean** at
the nominal value and the median slightly below it. An earlier version of this table said "median = nominal"
while the note beneath it specified `mu = ln(nominal) − σ²/2`; those are different distributions, and only the
second is mean-preserving. Mean-preservation is the binding requirement — it is what §5's mandatory property
test checks and what CLAUDE.md §6 requires of every random scaling — so the note governs and the table has
been corrected to match it. The `m` clip at 1 is never binding at the shipped values (`m` ≤ 0.30, σ = 0.30) and
so does not disturb the mean in practice; the clip at 0 never binds at all.

The Beta for `q_rev` is parameterised from its mean and standard deviation:
`nu = mean(1 − mean)/sd² − 1`, `alpha = mean × nu`, `beta = (1 − mean) × nu`, giving α = 12.09 and β = 22.46
at the defaults. Its mean is exactly nominal by construction.

**`e` is not given a distribution directly.** It inherits one from `d`, `m` and `q_rev` through the escape
equation. Giving it an independent distribution would break the derive-don't-assert rule and double-count
the same uncertainty.

Any distribution added later must be mean-preserving in the same way — see §5.

**Aleatory versus epistemic.** These draws express what we do not know about the organisation. The `theta`
common factor in §5 expresses how one epic could differ from another in the same organisation. They are
different things and the model keeps them separate: `--uncertainty aleatory` switches the table above off, so
you can see how much of the range is irreducible trajectory risk and how much is our own ignorance. At the
shipped defaults the answer is that parameter uncertainty adds surprisingly little, because correlated escape
already dominates — a result worth reporting rather than assuming.

### 3.6 The ρ menu — `kind = POLICY`

`ρ` is the fraction of implementation errors the check is blind to **by construction**. It is not measured; it
is a consequence of how verification is structured, and it is read off this menu:

| Verification structure | `rho` |
|---|---|
| Same model, same context, self-review | 0.70 |
| Same model, fresh context | 0.50 |
| Different model, adversarial prompt | 0.40 |
| Frozen acceptance suite + isolated contexts | 0.20 |
| The above + at least one check from a different derivation route | 0.05 |
| The above + formal methods on critical paths | 0.02 |

Why not measure it: estimating `ρ` empirically requires observing implementations checked against oracles
co-derived with them, and Step 5 exists to guarantee that case never arises. Building co-derived oracles
purely to measure the harm of co-derivation would pay for an apparatus whose only output is a number the
process already controls. **Validate the prediction, not the parameter** — see §7.

---

## 4. Derived quantities

Nothing below is entered by hand. Each is computed from §3.

### 4.1 Escape rate

The heart of the model, and the reason it needs fewer free parameters than earlier versions.

```
e_gate  = d × [ rho + (1 − rho) × m ]        probability a defect survives the automated oracle
e       = e_gate × [ f + (1 − f) × q_rev ]   probability it also survives the review that follows
```

The second factor reads: with probability `f` the story is auto-merged and no human sees it, so the defect
survives with certainty; with probability `1 − f` a human reviews it and misses it with probability `q_rev`.

**This reproduces the published escape rates for all five scenarios from four primitives.** Verify:

| Scenario | `d` | `rho` | `m` | `f` | computed `e` | published |
|---|---|---|---|---|---|---|
| A Execute only | 0.30 | 0.70 | 0.30 | 0.00 | 8.3% | 8.1% |
| B + Decide | 0.24 | 0.70 | 0.30 | 0.00 | 6.6% | 6.3% |
| C + Deliver | 0.30 | 0.05 | 0.06 | 0.85 | 2.9% | 3.1% |
| D All three | 0.24 | 0.05 | 0.06 | 0.90 | 2.4% | 2.3% |
| D+ + quality | 0.24 | 0.02 | 0.02 | 0.90 | 0.9% | 0.9% |

### 4.2 Attempts

```
A ~ Geometric(p_story), truncated at A_max
E[A] = sum over k = 0 .. A_max-1 of (1 - p)^k          NOT 1/p
```

**Use the truncated expectation everywhere, including the deterministic pass.** `1/p` overstates Hard-class
attempts by 5.3% in scenario D and 8.4% in C, and Hard stories carry most of the token mass. Using `1/p`
would mean the published token totals are not reproducible from the published parameters, which is the one
property the derivation exists to provide.

**Fallback is per implementation, and a story falls back only when it cannot be compared.** Each
implementation draws its own `A`. An implementation that hits the cap has failed outright with probability
`(1 − p)`; conditioning correctly, `P(implementation falls back) = (1 − p)^A_max`. A **story** falls back when
fewer than `min(2, N_impl)` implementations converge, because Step 7 needs two to compare. It then costs
`fallback_hours` of human time and leaves the auto-merge population.

At the shipped parameters this gives 6.4 fallback stories in A and **0.4 in D** — the apparatus that raises
`p` also nearly eliminates the fallback queue. The 10%-fallback figure used illustratively elsewhere is a
stress case, not a model output, and must be labelled as one.

### 4.3 Tokens

```
generation_tokens = Σ over stories, Σ over the N_impl implementations of  k[class] × A × L
                    where A and L are drawn INDEPENDENTLY FOR EACH IMPLEMENTATION
                    and L ~ Lognormal(mu = −sigma_k²/2, sigma = sigma_k), so E[L] = 1
apparatus_tokens  = decide + oracle + crosstest + integration + repo_scope
total_tokens      = generation_tokens × k_scale + apparatus_tokens
token_cost        = total_tokens × c / 1e6
```

**One draw per implementation, not one per story multiplied by N.** The implementations run in isolated
contexts with no shared history — that is the point of Step 7 — so each converges independently. Multiplying
a single draw by `N_impl` leaves the mean correct and inflates the variance: epic token CV comes out 7.1%
that way against **4.1%** done properly.

The lognormal multiplier carries per-attempt trajectory variation. Its mean is 1 by construction, so it adds
spread without shifting the expected value. `k_scale` is the epistemic draw from §3.5 and applies to all
classes together.

**`repo_scope` (Step 10) is a real token line, not zero.** Repository-wide semantic duplication detection,
conformance graph queries, change amplification, and the weekly trend basket all run agent work. Omitting it
was why D+ previously failed to reconcile from its own parameters.

### 4.4 Human hours

```
criteria_hours     = n_stories × S
review_hours       = n_reviewed × R
                     where n_reviewed = stories not auto-merged and not fallen back
incident_hours     = n_escaped × I                    (billed at w_inc, not w)
spec_hours         = system_spec_amortised            (policy, per scenario)
architecture_hours = architecture_decisions           (policy, per scenario)
switch_hours       = (n_touches / b) × s
fallback_hours     = n_fallback × fallback_hours
restructure_hours  = restructure_fraction × (criteria + review + spec + architecture)

total_hours        = criteria + review + spec + architecture
                   + switch + fallback + restructure + incident
```

**All eight terms are included. Architecture decisions and switch cost are separate lines** — they are the
same size at the shipped defaults, which previously let two documents disagree about which one the total
contained while still summing correctly. **The restructuring reserve is included too**: recommending a 5–10%
reserve and then publishing totals that reserve nothing is not a defensible position.

`n_touches` counts human contacts, explicitly:

```
n_adjudications = adjudication_rate × n_stories     if Step 7 active, else 0
n_touches       = n_stories          criteria, one per story — including stories that later fall back
                + n_reviewed         one per story actually reviewed
                + n_adjudications    one per flagged question
                + n_fallback         one per story handed to a human
```

The criteria touch is counted for **every** story because criteria are authored before anyone knows which
stories will converge, and the adjudication share is taken against **all** stories rather than reviewed ones,
because a flagged question is raised by the comparison at Step 7 and not by the review that may follow it.
At the defaults this gives 320.0 touches in A and 240.4 in D. **Adjudication touches exist only where Step 7
is active** — scenarios without
cross-implementation comparison raise no flagged questions, and their adjudication count is zero. `b` is the
batch size — how many touches are handled in one scheduled session. **`b = 1` means every touch arrives as an
interruption**, and the model will show what that costs.

### 4.5 Cost

```
cost = token_cost
     + (criteria + review + spec + architecture + switch + fallback + restructure) × w
     + incident_hours × w_inc
```

---

## 5. The simulation

One run:

```
--- epistemic draws (§3.5), once per run ---
d, m, q_rev, S, k_scale   ~ as specified in §3.5

--- aleatory draws, once per run ---
theta ~ Normal(0, 1)                                   NEVER per story
f_run   = logistic(logit(f_base) − lambda_f × theta)
e_base  = d × [rho + (1 − rho) × m] × [f_run + (1 − f_run) × q_rev]

--- mean-preserving escape scaling ---
e_scale = exp(lambda_e × theta − lambda_e²/2)          the −lambda_e²/2 is REQUIRED
clustered ~ Bernoulli(p_cluster)
e_scale ×= cluster_mult          if clustered
e_scale ×= (1 − p_cluster × cluster_mult) / (1 − p_cluster)   otherwise   [= 0.647 at defaults]
e_run   = clip(e_base × e_scale, 0, 1)

--- per story, per implementation ---
p_impl  = logistic(logit(p[class]) + lambda_p × theta + eps),  eps ~ Normal(0, 0.25)
A       = min(Geometric(p_impl), A_max)
tokens += k[class] × A × L
capped  = (A == A_max) AND Bernoulli(1 − p_impl)        P(capped) = (1 − p)^A_max
story falls back when converged implementations < min(2, N_impl)

--- portfolio ---
reviewed = Binomial(n_stories − n_fallback, 1 − f_run)
escaped  = Binomial(n_stories, e_run)
hours and cost per §4.4 and §4.5
```

**Both random scalings must be mean-preserving, and one of them was not.** `exp(lambda_e × theta)` has
expectation `exp(lambda_e²/2)` = 1.163, and a cluster multiplier applied only on the clustered branch has
expectation `1 + p_cluster(cluster_mult − 1)` = 1.300. Together they inflated the simulated escape rate by
**51%** above the derived `e` — scenario D running at an effective 3.6% instead of 2.4%. The token lognormal
was centred correctly and the escape scaling was not; the asymmetry between two adjacent lines is the tell.

**A third mean error, of the same family, survives in the specification above.** Centring both scalings makes
each of them individually mean-preserving. It does not make their *product* mean-preserving, because `e_base`
and `e_scale` are both functions of the same `theta` and are negatively correlated through it:

```
theta up  ->  f_run = logistic(logit(f) − lambda_f × theta)   DOWN
          ->  more stories reviewed, so e_base                DOWN
theta up  ->  e_scale = exp(lambda_e × theta − lambda_e²/2)   UP
```

so `E[e_base × e_scale] < E[e_base] × E[e_scale] = e`. By Gauss-Hermite quadrature, exactly:

| Scenario | derived `e` | `E[e_run]` as specified | ratio | f-Jensen alone | covariance alone |
|---|---|---|---|---|---|
| A Execute only | 0.08295 | 0.08295 | 1.0000 | 1.0000 | 1.0000 |
| B + Decide | 0.06636 | 0.06636 | 1.0000 | 1.0000 | 1.0000 |
| C + Deliver | 0.02897 | 0.02819 | 0.9729 | 0.9950 | 0.9778 |
| D All three | 0.02401 | 0.02354 | 0.9805 | 0.9960 | 0.9845 |
| D+ + quality | 0.00889 | 0.00871 | 0.9805 | 0.9960 | 0.9845 |

A and B are exact because `f = 0` there, so `e_base` does not depend on `theta` and no covariance exists. The
covariance term is **three to four times larger than the `f` Jensen term** it was previously lumped in with,
and it is the reason the simulation cannot reproduce its own derived `e` in any scenario with a gate. The
direction is conservative — the simulation escapes slightly *less* than the derivation claims, so it
understates cost rather than overstating it — but it is the same defect as S1-1 with a smaller coefficient
and the opposite sign.

**It is left uncorrected, deliberately.** Correcting it means dividing `e_scale` by
`E[e_base × e_scale] / E[e_base]`, a quadrature over `theta` inside the hot loop, which makes `e_run` depend
on the whole joint distribution rather than on the line above it. That is a change to the model rather than a
bug fix, and it would move every pinned percentile. Recorded in §11 as a decision rather than absorbed
silently.

**Mandatory property test.** At 200,000 iterations, the realised mean escape count must equal `e × n_stories`
for every scenario **to 4%**, and **to 0.5%** for A and B, where no covariance term exists. The 4% bound is
C's 2.71% structural gap plus Monte Carlo error at 200,000 iterations, with margin; 3% would sit directly on
top of C and fail intermittently on the seed. The suite
additionally asserts the 0.5% bound for every scenario with `lambda_f` set to zero, which removes the
covariance and isolates the Jensen-bias class exactly. Those three checks together still catch the whole
class decisively — S1-1 was a **51%** error and its two components were 16% and 30% — while stating the
residual instead of hiding it inside one loose bound.

Repeat 10,000 times. Report P50 / P80 / P95 of total cost, and of each component.

**Vectorise across iterations, not across stories.** `theta`, `f_run` and the cluster indicator are drawn as
arrays of length `iterations`; the story loop runs once per class rather than once per story, with per-class
draws shaped `(iterations, n_stories_in_class)`. This keeps the common factor correctly shared within a run —
one `theta` per row — while letting NumPy do the work. Drawing `theta` with shape `(iterations, n_stories)`
would silently destroy the correlation the model exists to capture, and is the single easiest way to break
this program without any test failing on shape.

Attempts are drawn with `rng.geometric(p)` and clipped at `A_max`; the clip is what creates the fallback
branch, so count clipped draws rather than discarding them.

**Variance decomposition** is computed by re-running with one random source at a time frozen at its median
and measuring the reduction in the P50→P95 spread.

**Only genuinely random sources may appear.** A constant contributes zero variance, so batch size and any
other policy parameter must never be listed as a variance share — that was a defect in earlier versions,
which reported "batching 20%" and "criteria hours 19%" for quantities the model held fixed. Those were
one-at-a-time sensitivities, which are a different and also useful thing, and must be reported under that
name in a separate table.

**The shares do not sum to 100%,** and the report must not imply they do. The model is non-linear, so
freeze-one-at-a-time reductions are not a partition of the variance.

At the shipped parameters the result is stark and worth stating plainly:

| Source frozen | Reduction in P50→P95 spread |
|---|---|
| **Escape (theta, clustering, Bernoulli draw)** | **~72%** |
| `q_rev` | ~1% |
| `d` | ~1% |
| `m` | within Monte Carlo noise |
| Criteria hours `S` | within Monte Carlo noise |
| Token trajectory (`A`, `L`) | within Monte Carlo noise |
| Token `k_scale` | within Monte Carlo noise |

Escaped defects are essentially the entire uncertainty of this model. Everything else, including all
parameter uncertainty and all trajectory noise, is individually under two percent.

---

## 6. Scenarios

A scenario is declared as **which of the ten process steps are active**, and the parameters follow. Never
define a scenario by copying another and editing numbers.

**Five scenarios**, matching the briefing set's A / B / C / D / D+ exactly.

| Step | A `execute_only` | B `execute_decide` | C `execute_deliver` | D `all_three` | D+ `all_three_quality` |
|---|---|---|---|---|---|
| 1 System specification | — | ✓ | ✓ | ✓ | ✓ |
| 2 Criteria vs governing sources | — | ✓ | — | ✓ | ✓ |
| 3 Completeness sweep | — | ✓ | — | ✓ | ✓ |
| 4 Program design and slicing | — | ✓ | ✓ | ✓ | ✓ |
| 5 Frozen acceptance suite | — | — | ✓ | ✓ | ✓ |
| 6 Mutation scoring + different route | — | — | ✓ | ✓ | ✓✓ deeper |
| 7 N implementations, compared | — | — | ✓ | ✓ | ✓✓ more |
| 8 Tiered gate | — | — | ✓ | ✓ | ✓ |
| 9 Integration verification | — | — | ✓ | ✓ | ✓ |
| 10 Repo-scope gates | — | — | ✓ | ✓ | ✓ |

**B automates Decide without Deliver; C automates Deliver without Decide.** They are the two single-phase
additions to A, and running both is what lets the report show each phase's marginal contribution separately —
which turns out to be superadditive, since better specifications reduce escapes while better oracles catch
specification ambiguity.

Resulting parameter selection:

| Parameter | A | B | C | D | D+ |
|---|---|---|---|---|---|
| `d` | `d_base` | `d_specced` | `d_base` | `d_specced` | `d_specced` |
| `m` | `m_unscored` | `m_unscored` | `m_scored` | `m_scored` | `m_deep` |
| `rho` | 0.70 | 0.70 | 0.05 | 0.05 | 0.02 |
| `f_base` | 0.00 | 0.00 | 0.85 | 0.90 | 0.90 |
| `S` | `S_manual` | `S_oracled` | `S_manual` | `S_oracled` | `S_oracled` |
| `R` | `R_large` | `R_large` | `R_gated` | `R_gated` | `R_gated` |
| `k` | `k_unfrozen` | `k_unfrozen` | `k_frozen` | `k_frozen` | `k_frozen` |
| `p` | `p_unfrozen` | `p_unfrozen_specced` | `p_frozen` | `p_frozen_specced` | `p_frozen_specced` |
| `N_impl` R/S/H | 1/1/1 | 1/1/1 | 1/2/2 | 1/2/3 | 1/3/5 |
| spec hours | 0 | 40 | 80 | 80 | 80 |
| architecture hours | 40 | 40 | 40 | 10 | 10 |
| decide tokens | 0 | 600M | 0 | 600M | 600M |
| oracle tokens | 0 | 0 | 592M | 760M | 4,460M |
| crosstest tokens | 0 | 0 | 296M | 368M | 768M |
| integration tokens (Step 9) | 0 | 0 | 120M | 150M | 200M |
| **repo-scope tokens (Step 10)** | 0 | 0 | 200M | 250M | 1,850M |

**D+ apparatus reconciles from these lines.** Earlier versions declared 4,200M of apparatus for D+ against a
pinned 10.2B total — a build from that specification would have produced 6.9B and failed its own fixture. The
D+ oracle line carries the formal-methods and deeper-mutation spend; the repo-scope line carries the
repository-wide duplication sweep and drift-driven refactor proposals.

**`rho` stays at 0.70 in B.** Automating Decide does not freeze the acceptance suite, so the check remains
co-derived with the implementation. This is the model's sharpest structural statement: **better specifications
alone do not buy independence.** They lower `d`, which is worth something, but the escape rate stays in the
same band until Step 5 is in place.

### Expected output, for regression

At the defaults, and with variance switched off, the deterministic case should land near:

**Deterministic pass** — all random sources at their expected values. This is a *mean-like* quantity and
should be pinned separately from the P50, which on a right-skewed distribution sits below it.

| Scenario | Hours | Human cost | Tokens | Token cost | Total | Token share | `e` | Fallback stories |
|---|---|---|---|---|---|---|---|---|
| A Execute only | 1,173 | $215,800 | 0.96B | $2,900 | **$218,600** | 1.3% | 8.3% | 6.4 |
| B + Decide | 838 | $157,500 | 1.49B | $4,500 | **$162,000** | 2.8% | 6.6% | 4.6 |
| C + Deliver | 766 | $128,900 | 2.42B | $7,300 | **$136,100** | 5.3% | 2.9% | 4.2 |
| D All three | 347 | $63,600 | 3.69B | $11,100 | **$74,700** | 14.8% | 2.4% | 0.4 |
| D+ + quality | 315 | $51,500 | 10.44B | $31,300 | **$82,800** | 37.8% | 0.9% | 0.0 |

Savings against A: B 26%, C 38%, **D 66%**, D+ 62%.

**Monte Carlo, full uncertainty** — 40,000 iterations, seed 7:

| Scenario | P50 | P80 | P95 | P95/P50 |
|---|---|---|---|---|
| A | $197,600 | $243,900 | $369,800 | 1.87 |
| B | $143,400 | $179,000 | $279,200 | 1.95 |
| C | $130,400 | $155,900 | $197,500 | 1.52 |
| D | **$68,800** | **$85,000** | **$120,000** | 1.74 |
| D+ | $80,800 | $90,300 | $104,600 | **1.29** |

**Two results the corrected model produces that the earlier one could not.**

**D's P95 sits below A's P50.** $120,000 against $197,600 — the recommendation's bad case beats the
alternative's median, which is a stronger claim than comparing against a point estimate.

**D+ costs more at the P50 and less at the P95.** $80,800 versus $68,800 at the median; $104,600 versus
$120,000 at the 95th percentile. **Deliberate quality investment buys tail reduction, not expected-value
reduction** — you pay about $12,000 at the median to remove about $15,000 of tail. That is the correct way to
present D+ to a risk-averse decision-maker, and it was invisible while the escape scaling was uncentred.

With `--uncertainty aleatory`, D gives P50 $68,300 / P95 $118,300 — so **parameter uncertainty adds under 2%
to the P95.** Correlated escape dominates so completely that our ignorance of the parameters barely registers,
which is worth reporting rather than assuming.

**Marginal contributions, which only appear once B and C are both present.** Automating Deliver alone saves
more than automating Decide alone (38% vs 26% against A), because review volume is the largest single block in
the bolt-on baseline.

**They are substantially superadditive, and savings fractions do not add.** The correct null for two
independent interventions is multiplicative: `1 − (1 − 0.26)(1 − 0.38)` = **54%**. D delivers 66%, so the
synergy is **+12 percentage points**, not the +1 that an additive comparison suggests. Better specifications
reduce escapes and better oracles catch specification ambiguity, so each raises the return on the other. **These figures are pinned in `tests/fixtures/`.** A change that moves them is either a bug or a
decision to record in §11.

---

## 7. How the model relates to the ten steps

Each step either changes a parameter or adds a cost term. This table is the model's connection to the process,
and every row should be traceable in the code.

| Step | Effect in the model |
|---|---|
| **1** System specification | Lowers `k` (cached prefix) and raises `p`; adds `spec_hours` |
| **2** Criteria vs governing sources | `d_base` → `d_specced`; `S_manual` → `S_oracled`; adds decide tokens |
| **3** Completeness sweep | Included in the Step 2 effect on `S` and `d`; adds the adjudication touch |
| **4** Program design and slicing | Contributes to the `d` reduction and to reuse; not separately parameterised |
| **5** Frozen acceptance suite | `rho` 0.70 → 0.20; switches `k`/`p` from unfrozen to frozen |
| **6** Mutation scoring + different route | `m_unscored` → `m_scored`; `rho` 0.20 → 0.05; adds oracle tokens |
| **7** N implementations, compared | Sets `N_impl`; multiplies generation tokens; adds crosstest tokens |
| **8** Tiered gate | Sets `f_base`; `R_large` → `R_gated` |
| **9** Integration verification | Adds integration tokens; caps WIP (reported, not costed) |
| **10** Repo-scope gates | Adds the restructuring reserve; design decay itself is out of scope |

**`N_impl` costs tokens and does not enter the escape equation.** Raising N from 1 to 3 to 5 changes cost and
no modelled outcome; D+'s quality gain comes entirely from `rho` 0.05 → 0.02 and `m` 0.06 → 0.02, which the
process attributes to formal methods and deeper mutation. The real benefits of more implementations —
best-of-N selection and ambiguity detection — are not modelled, so **the model understates D+ in particular**.
Adding best-of-N selection (`d_effective = d^N_eff` on the dimensions the oracle set discriminates) is the
obvious extension and is deliberately not taken, because `N_eff` depends on `rho`, which is an input rather
than a measurement.

**Steps 4, 9 and 10 are deliberately under-parameterised.** Their main effects — reuse, cross-story defect
detection, design decay — are real but poorly quantified, and inventing parameters for them would add
precision the evidence does not support. The model therefore **understates** the value of the full process.
Say so when reporting.

---

## 8. Where the numbers come from

| Kind | How to obtain it |
|---|---|
| `w`, `w_inc`, `c` | Your finance function and your provider invoices. Blend `c` across the model tiers actually used. |
| `k`, `p` per class | **Metered spikes.** Run 2–3 representative stories per class against the real repository and log turns, attempts, and tokens. At $10–50 per spike the information is nearly free relative to what it decides. |
| `d` | Failure rate of fresh implementations against the oracle set, divided by the mutation score: `d = F / mutation_score`. |
| `m` | `1 − mutation score`, straight off the mutation-testing run. |
| `rho` | The menu in §3.5. Not measured — chosen by how you structure verification. |
| `q_rev` | The sampled-review stream (Step 8, V12) is the only unbiased source. Measure it; it is not zero. |
| `S`, `R`, `I` | Time-tracking on an instrumented epic. `I` from the incident record. |
| `f` | Observed auto-merge fraction once the gate is running. Before that, a policy target. |
| `A_max` | A policy you set, informed by logged trajectories: the turn count past which sessions rarely recover. |
| `s`, `b` | `s` from calendar analysis of context switching; `b` is a scheduling policy you choose. |
| `lambda_*`, `p_cluster` | The hardest to fit. Require several epics of history. Until then, treat the defaults as structural assumptions and run the sensitivity command. |

**Nothing here comes from a published benchmark, and none should.** These parameters are properties of your
codebase, your corpus, and your organisation.

### Validating the model rather than the parameters

The escape rate is the one output with an independent check available. Compute predicted `e` before merge
from `d`, `m`, `rho`, `q_rev` and `f`; compare it against the 90-day traced escape rate. Persistent
under-prediction means a structural assumption is wrong — most likely that `rho` is higher than the menu
value, because contexts are sharing more than intended or the "different route" check is not as independent
as assumed. That is actionable without knowing `rho` precisely.

---

## 9. What the model does not contain

State these whenever the output is presented.

- **Design decay.** `e` counts functional defects. A story that ships correct behaviour through a poor
  decomposition scores zero here and still raises the cost of everything after it.
- **Story-interaction defects beyond their token cost.** Integration verification is costed; the defects it
  catches are not modelled as a rate.
- **Maintenance and cost of ownership.** Out of scope by design.
- **Calendar duration.** The model reports cost, not time. The saving is a headcount reduction at roughly
  constant duration, because the surviving work requires authority and authority does not parallelise. Report
  FTE alongside cost so this is not misread.
- **Recalibration after a model change.** A model upgrade invalidates every calibrated parameter at once.
  Budget it per upgrade, not per quarter.

---

## 10. Outputs

Default text report, per scenario:

1. Cost P50 / P80 / P95, and P95/P50
2. Component breakdown at P50: tokens, criteria, review, incidents, spec, switch, fallback, restructure
3. Token share of total
4. Derived `e` and predicted escaped-defect count
5. Fallback count and its hours
6. Variance decomposition
7. FTE at a stated calendar duration

Plus a comparison table across all scenarios, and the marginal saving of each against (a).

`--format csv` emits one row per scenario per percentile. `--sensitivity PARAM` re-runs across a range for one
parameter and reports the effect on P50 and P95.

---

## 11. Decision log

Record any change that moves a pinned figure, with the reason.

| Date | Change | Effect on pinned figures |
|---|---|---|
| — | Initial specification | — |
| 2026-08-17 | **§3.3 — `b` given a value of 6.** It was named in the hours equation and the symbol table with no value and no provenance row, so no implementation could reproduce the switch line. Recovered from A's pinned 1,173 hours: 320 touches × 0.25 h ÷ `b` = 13.3 h. | **None.** This is the value the pinned figures were already computed with; stating it makes them reproducible. |
| 2026-08-17 | **§3.3 — `p` split from two tables into four,** selected by `(Step 5, Steps 2–3)`. Two tables cannot reproduce §6: B came out at 1.56B tokens against a pinned 1.49B, D at 3.83B against 3.69B, and D's fallback count at 1.0 stories against a pinned 0.4. New values `p_unfrozen_specced` = 0.87/0.55/0.32 and `p_frozen_specced` = 0.92/0.70/0.45. | **None.** All five scenarios now reconcile from the parameters: hours 1,173 / 837 / 766 / 347 / 315 and totals $218,638 / $161,952 / $136,120 / $74,696 / $82,788, against pins of 1,173 / 838 / 766 / 347 / 315 and $218,600 / $162,000 / $136,100 / $74,700 / $82,800. |
| 2026-08-17 | **§4.4 — touch counting made explicit.** `n_adjudications = adjudication_rate × n_stories`; the criteria touch counts every story. Previously a builder had to guess whether the adjudication share applied to all stories or only reviewed ones. | **None.** Both readings round to the same pinned totals; the ambiguity is removed rather than resolved in a new direction. |
| 2026-08-17 | **No classes anywhere in the implementation,** at the owner's instruction. `Scenario`, `Params` and `Result` — named as public API in CLAUDE.md §9 — become plain dicts built by `resolve_scenario()`, `default_params()` and `run_scenario()`. Supersedes CLAUDE.md §10's dataclass rule. | None. Representation only. |
| 2026-08-17 | **Layout extended by one module.** CLAUDE.md §3 fixes a five-file layout and §9 caps a module at 400 lines; the parameter registry with mandatory provenance strings plus the ten-step resolution does not fit in one file. Split into `params.py` (records) and `scenarios.py` (steps → parameter selection). Dependency direction unchanged and still one-way. | None. |
| 2026-08-17 | **`EPISTEMIC` admitted as a fourth provenance kind.** CLAUDE.md §5 says kind is "exactly one of" PRICE / CALIBRATED / POLICY, while §3.5 above declares `kind = EPISTEMIC`. SPEC governs, so the registry accepts four kinds. | None. |
| 2026-08-17 | **Checked against the supplied `reference_model.py` after the build.** It independently confirms `b` = 6 and the per-scenario `p` tables that §3.3 lacked — A 0.85/0.50/0.28, C 0.90/0.65/0.40, D and D+ 0.92/0.70/0.45, all recovered here before that file was opened. It also confirms the touch counting, the restructure base, and the `min(2, N_impl)` fallback rule. `p_unfrozen_specced` was adopted from it at 0.87/0.54/0.32, replacing an independent fit of 0.88/0.545/0.318 that met every pin equally well; the reference's values are the ones that generated the published figures. | **None.** The deterministic pass now agrees with `reference_model.py` on all 70 figures across all five scenarios to 1.8e-16, and the Monte Carlo P50/P95 agree to within 1.2% — sampling error, since the two consume their streams in different orders. Pinned by `tests/test_reference_model.py`. |
| 2026-08-17 | **§3.5 — the epistemic lognormals restated as mean-preserving.** The table said "median = nominal" and the note beneath it said `mu = ln(nominal) − σ²/2`; those are different distributions and a builder had to pick one. The note governs, per CLAUDE.md §6. | None. The note was already what the pinned figures used. |
| 2026-08-17 | **§5 — a third mean error found, of the S1-1 family, and left uncorrected by decision.** `e_base` and `e_scale` are both functions of the same `theta` and negatively correlated through it, so centring each one individually does not make their product mean-preserving. `E[e_run]` sits 1.95% below derived `e` in D and D+ and 2.71% below in C; A and B are exact because `f` = 0 there. The covariance term is 3-4x the `f` Jensen term it was previously lumped in with. REVIEW.md S1-1 caught the two marginal mean errors and missed this one. | **None to the deterministic pins**, which do not use `theta`. The Monte Carlo pins are unaffected because they were generated from this same specification. The mean-preservation test is toleranced to 3%, with a 0.5% bound for A and B and a 0.5% bound for all five at `lambda_f` = 0. |
