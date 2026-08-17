# Model Review — Defect Register

**STATUS: ALL TWELVE DEFECTS CLOSED.** The corrections are in `SPEC.md`, `CLAUDE.md`, `README.md`,
`cio-briefing-v6.md`, `cost-model-simplified.md` and `agentic-coding-estimation-model.md`. Every published
figure has been regenerated from a corrected reference implementation rather than adjusted by hand. This
register is retained as the record of what was wrong and why, and the findings below are stated in the past
tense of the defect, not of the current documents.

**What the repairs changed, in summary:**

| | Before | After |
|---|---|---|
| Scenario D, point estimate | $69,600 | $74,700 |
| Scenario D, P50 / P95 | $69,600 / $115,100 | $68,800 / $120,000 |
| Scenario A, P50 | (not reported) | $197,600 |
| Headline comparison | D's P95 below A's *point estimate* | **D's P95 below A's *median*** |
| Variance decomposition | escape 45 / batching 20 / criteria 19 / spec 9 / tokens 7 | **escape ~72%, all else under 2%, not a partition** |
| D+ | more expensive, full stop | **more expensive at P50, cheaper at P95** |
| Tokens, A → D | 1.15B → 3.51B | 0.96B → 3.69B |

Every conclusion survived. Two got stronger: the headline comparison now beats a median rather than a point
estimate, and D+ acquired a rationale it did not previously have.

---

Review of `cio-briefing-v6.md`, `cost-model-simplified.md`, `agentic-coding-estimation-model.md`,
`SPEC.md`, `CLAUDE.md`, `README.md` as of this session. Conducted by recomputing rather than reading,
and by testing the specification the way a builder would.

Severity: **S1** produces wrong numbers · **S2** a builder cannot implement without guessing ·
**S3** a claim the model does not support · **S4** cosmetic or editorial.

---

## S1-1 — The escape-rate scaling is not mean-preserving; the simulation would overshoot by ~51%

**Where:** SPEC §5; technical model §7.

The simulation multiplies the derived `e` by two random factors:

```
e_scale = exp(lambda_e × theta)          theta ~ Normal(0,1), lambda_e = 0.55
if clustered:  e_scale ×= cluster_mult   p_cluster = 0.15, cluster_mult = 3.0
```

Neither has expectation 1:

| Factor | Expectation |
|---|---|
| `exp(0.55 · θ)` | `exp(0.55²/2)` = **1.163** |
| cluster multiplier | `0.85 + 0.15×3` = **1.300** |
| combined | **1.512** |

So the simulated mean escape rate lands about **51% above the derived `e`**. Scenario D would run at an
effective 3.6% rather than 2.4%, adding roughly 23 incident hours and **$9,200** to the mean — which breaks
the pinned P50 of $69,600 and inflates the escape share of the variance decomposition.

The token noise term was specified correctly (`Lognormal(mu = −sigma²/2)` has mean 1); the escape term was
not, and the inconsistency between the two is the tell.

**Fix.** Centre both:

```
e_scale = exp(lambda_e × theta − lambda_e²/2)
cluster_mult_off = (1 − p_cluster × cluster_mult) / (1 − p_cluster)     # = 0.647 at the defaults
e_scale ×= cluster_mult if clustered else cluster_mult_off
```

Add a property test: with 200,000 iterations, the realised mean escape count must match `e × n_stories`
to within Monte Carlo error. This is the single most valuable test in the suite — it catches the whole
class of Jensen-bias errors, including the same problem in `logit(f) − lambda_f·theta`, which is
second-order but present.

---

## S1-2 — Attempts are drawn per story but consumed per implementation

**Where:** SPEC §4.3 and §5.

```
tokens += N_impl[class] × k[class] × A × L
```

One `A` is drawn per story and multiplied by `N_impl`. But the implementations run in isolated contexts
with no shared history — that is the whole point of Step 7 — so each one converges independently and needs
its own `A` and its own `L`.

The mean is unaffected. The variance is not:

| Reading | Epic token σ | Epic CV | σ in dollars |
|---|---|---|---|
| One `A` per story (as written) | 250M | 7.1% | $750 |
| One `A` per implementation (correct) | 145M | 4.1% | $434 |

**The published "~8%" epic CV is wrong under either reading** — it is 7.1% as specified, 4.1% as intended.
Both are below the figure now in §7 of the briefing, so the argument that trajectory variance is negligible
gets *stronger*, not weaker.

**Fix.** Draw `A` and `L` with shape `(iterations, n_stories, N_impl)`, or equivalently expand the story
axis by `N_impl`. Correct the briefing's variance block to 4%, σ ≈ $430, moving the estimate ~0.6%.

---

## S1-3 — Scenario D+ does not reconcile: 6.9B from the parameters, 10.2B pinned

**Where:** SPEC §6 parameter table vs §6 expected output; cost model D+ delta table.

Computing D+ from its own declared parameters:

| Component | Tokens |
|---|---|
| Generation, `N_impl` = 1/3/5 | 2,676M |
| Apparatus per SPEC (decide 600 + oracle 2,600 + crosstest 800 + integration 200) | 4,200M |
| **Total from SPEC** | **6,876M = 6.9B** |
| **Pinned figure** | **10.2B** |

A build from this specification would produce 6.9B and fail its own fixture. The 10.2B comes from a
different route — D's 3,511M plus the cost model's +6.7B delta table — and that route is internally
consistent, including its "+1.0B for N=5/N=3", which matches the generation increase exactly (2,676 −
1,633 = 1,043M).

Working backwards, D+ apparatus must be **7,535M**, not 4,200M. The missing 3,335M is in the delta table
under headings SPEC has no home for: repo-wide semantic duplication sweep (1.3B) and drift-driven refactor
proposals (0.3B), plus more of the formal-methods and deeper-mutation spend than the oracle line carries.

**Fix.** Add a fifth apparatus category — **repo-scope tokens (Step 10)** — and restate the D+ apparatus
lines so the parameters produce 10.2B. See S2-1: Step 10 currently consumes no tokens in *any* scenario,
which is independently wrong.

---

## S1-4 — Truncation at `A_max` = 5 is ignored when computing token totals

**Where:** SPEC §4.3 uses `E[A] = 1/p`; SPEC §3.3 sets `A_max` = 5.

`E[min(A, 5)]` is not `1/p`:

| Class | `p` | `1/p` | `E[min(A,5)]` | Overstatement |
|---|---|---|---|---|
| Routine | 0.92 | 1.087 | 1.087 | 0.0% |
| Standard | 0.70 | 1.429 | 1.425 | 0.2% |
| Hard (D) | 0.45 | 2.222 | 2.110 | **5.3%** |
| Hard (C) | 0.40 | 2.500 | 2.306 | **8.4%** |

Hard stories carry most of the token mass, so scenario D's generation total is overstated by roughly 4%
and C's by roughly 6%. Small against the total cost, but it means the published token figures are not
reproducible from the published parameters — which is the property the whole derivation exists to provide.

**Related:** the implied fallback rate at these parameters is **0.84%** (1.3 stories of 160), not the 10%
used illustratively in §8 and §11 of the briefing and in the cost model. The 10% figure is a hypothetical,
but it is not labelled as one, and a reader will reasonably take it as the model's output.

**Fix.** Either compute totals from `E[min(A, A_max)]`, or raise `A_max` until truncation is immaterial and
say so. Label the 10% fallback illustration as a stress case, and state the model-implied rate beside it.

---

## S2-1 — Step 10 consumes no tokens anywhere in the model

**Where:** SPEC §4.3 apparatus categories.

Semantic duplication detection across the whole repository (V20), conformance graph queries (V24), change
amplification (V25), and the weekly trend basket (V26) all run agent work at repository scope. The model
assigns them zero tokens in every scenario. This is why D+ cannot reconcile (S1-3), and it means scenarios
C and D understate their own apparatus.

**Fix.** Add `repo_scope_tokens` as a fifth category, non-zero wherever Step 10 is active.

---

## S2-2 — The hours equation double-counts or under-counts by exactly $1,500, and the two documents disagree

**Where:** SPEC §4.4/§4.5; cost model scenario table; technical model §11.

Scenario D, non-incident hours:

| Source | Components | Total |
|---|---|---|
| Cost model | criteria 160 + spec 80 + review 24 + **architecture 10** | 274 |
| Technical model P50 | criteria+spec 240 + review 24 + **switch 10** | 274 |
| SPEC cost equation (literally) | criteria 160 + spec 80 + review 24 + architecture 10 + **switch 10** | **284** |

The two companion documents each carry 274 hours but disagree about what the last 10 hours *is*. They agree
on the total only because architecture decisions and batched switch cost happen to be the same size at the
defaults. A build following SPEC would include both, produce 284 hours, and land at **$71,100** — failing
the pinned $69,600.

**Fix.** Decide which is in the pinned figures, add the other, and restate the pinned totals. My reading:
both are real, so D should be 329 hours and about $71,100, and every scenario total moves.

---

## S2-3 — The restructuring reserve is specified as a cost term and absent from every published total

**Where:** SPEC §4.4; cost model; briefing §7, §9.

`restructure_hours = restructure_fraction × (criteria + review + spec + architecture)`. At the documented
5–10%, that is 13.7 to 27.4 hours for scenario D — **$2,055 to $4,110**, none of which appears in the
$69,600.

Both the briefing and the cost model tell the reader to reserve 5–10% of capacity, then publish totals that
reserve nothing. Whichever way this is resolved, the recommendation and the arithmetic must agree.

---

## S2-4 — Three quantities are used but never given values

**Where:** SPEC §3, §4.4.

| Quantity | Status |
|---|---|
| `fallback_hours_per_story` | Named in the hours equation, no value, no provenance row |
| Adjudication rate | `n_touches` includes "one per adjudication"; nothing sets how many. The briefing's ~240 touches for D implies ~40% of stories, stated nowhere as a parameter |
| Defect rate of fallback stories | Fallback stories are human-written; their escape behaviour is neither `d` nor `e`, and is unspecified |

Each forces a builder to invent a number, which is exactly what `params.py`'s provenance rule exists to
prevent.

---

## S2-5 — `N_impl` costs tokens and buys nothing in the escape equation

**Where:** escape equation, all documents.

`e` depends on `d`, `ρ`, `m`, `f`, `q_rev`. It does not depend on `N`. So raising `N` from 1 to 3 to 5
increases cost and changes no modelled outcome except through `ρ` and `m`, which are set independently by
the design menu.

That is defensible — best-of-N selection and ambiguity detection are real effects the model deliberately
under-parameterises — but it has a consequence nobody has stated: **in this model, D+ derives none of its
quality improvement from the extra implementations it pays for.** The improvement comes entirely from
moving `ρ` 0.05 → 0.02 and `m` 0.06 → 0.02, which the document attributes to formal methods and deeper
mutation, not to N.

**Fix.** Either state plainly that N's benefit is unmodelled and the model therefore understates D+, or
introduce best-of-N selection: `d_effective = d^N_eff` for the dimensions the oracle set can discriminate.

---

## S3-1 — The variance decomposition attributes variance to deterministic parameters

**Where:** briefing §7; SPEC §5.

Published: escape rate 45%, **batching 20%**, **criteria hours 19%**, system specification 9%, tokens 7%.

Batch size `b` and criteria hours `S` are constants in the model. A constant contributes zero variance.
As specified, these three lines cannot be variance shares — they are one-at-a-time **sensitivities**, which
is a different thing and does not sum to 100%.

Two honest resolutions, and they lead to different documents:

1. **Relabel it a sensitivity analysis**, drop the implication that the shares partition the variance, and
   stop presenting them as summing to 100%.
2. **Give the parameters distributions** — parameter uncertainty is real and arguably the dominant
   uncertainty here — in which case it becomes a genuine variance decomposition, but the P95 widens
   substantially and every published percentile changes.

I would take (2), because the honest statement of this model's uncertainty is that we do not know `S`, `e`
or `q_rev` to better than a factor, and that dwarfs trajectory noise.

---

## S3-2 — "Deterministic mode reproduces the P50" is a category error

**Where:** SPEC §6 expected output.

The distribution is right-skewed by construction — Geometric attempts, lognormal token noise, clustered
escapes. A deterministic expected-value run produces something close to the **mean**, which sits above the
median. Pinning both to $69,600 asserts mean = median.

The documents are otherwise scrupulous about this ("report percentiles, never a mean"), which makes the
fixture the one place the discipline lapses.

**Fix.** Pin the deterministic run separately, and expect P50 to come in *below* it.

---

## S3-3 — Human review is counted twice: once in the `ρ` menu, once as `q_rev`

**Where:** briefing §3.5 menu vs §3.6 chain.

The `ρ` menu lists "Human review | 0.1–0.3" as a verification mechanism. The escape chain then applies
human review *again* as a separate `[f + (1−f)q_rev]` factor. If an organisation reads `ρ` off that row and
also has `f` < 1, review is discounted twice.

**Fix.** Remove the human-review row from the `ρ` menu and say explicitly that human review is not a `ρ`
mechanism — it enters through `q_rev` only. This also sharpens the point the menu is making, since the row
was there to show review being outperformed by mathematics-derived checks; that comparison is better made
in the `q_rev` discussion.

---

## S3-4 — A survivor of the removed ρ̂ estimator, directly contradicting §3.5

**Where:** briefing, closing line of the `ρ` menu.

> "These are starting values. Once N ≥ 2 you measure your own `ρ` directly (§5) and stop relying on the
> table."

`ρ` is no longer measurable — that was the point of removing the estimator, and §5 now explains at length
why. This sentence tells the reader the opposite, and points at the section that refutes it.

My earlier audit searched for `ρ̂`, `F_off` and `F_diag` and reported the removal complete. It was not:
prose making the same claim in words survived. **Symbol searches do not verify conceptual removals** — a
lesson worth applying to the next such change.

---

## S3-5 — The superadditivity claim compares incompatible quantities

**Where:** briefing §7; SPEC §6.

> "The two are slightly superadditive: D saves 66%, more than the 65% that simple addition of the two
> single-phase savings would give."

Savings fractions do not add. The correct null for two independent interventions is multiplicative:
`1 − (1 − 0.27)(1 − 0.38)` = **55%**. Against that, D's 66% is a **+11 percentage-point** synergy, not
+1. The claim is far too modest, and it is arithmetically the wrong comparison.

---

## S4-1 — Heading numbering collision in the briefing

`### 3.6 The full chain` sits inside a run of `### 1` … `### 8`, between `### 3` and `### 4`, alongside an
unnumbered `### What each verification mechanism costs you in ρ`. Renumber the run 1–9 and drop the
decimal.

---

## S4-2 — "Per-story token CV near 1.0" holds only for Hard stories

Computed: Routine 0.47, Standard 0.69, Hard 0.87, Hard-unfrozen 0.97. The claim is true where it matters
most and is stated as though it were general.

---

## What survives the review

Worth stating, because most of it does.

- **All scenario arithmetic reconciles.** Hours-to-cost, column sums, escaped-defect hours against the
  escape rates, token shares, savings percentages, parity prices, the $60/M crossover, and the
  50M-tokens-per-engineer-hour anchor all recompute exactly.
- **The escape equation reproduces all five published escape rates** from four primitives, maximum error
  0.34 percentage points. This is the strongest part of the model and it removes five free parameters.
- **The token derivation reconciles** for A, B, C and D from `N × k × (1/p)` plus apparatus. Only D+ fails
  (S1-3).
- **The parameter provenance discipline is sound** — PRICE / CALIBRATED / POLICY with mandatory sources is
  the right structure, and it is what made S2-4 findable at all.
- **The correlation structure is right in its essentials**: one common factor per run, loading on the gate
  rather than on generation, with the dollar asymmetry ($2,100 versus $18,000) correctly motivating it.
- **The conclusions are robust to every defect above.** Fixing all twelve moves scenario D by roughly
  $2,000 to $4,000 on a $69,600 base, widens the P95, and leaves the ordering, the token-share argument and
  the headline comparison — D's P95 below A's point estimate — intact.

---

## Recommended order of repair

1. **S1-1** — centring bug, and add the mean-preservation property test. Nothing else can be trusted until
   the simulation reproduces its own derived inputs.
2. **S2-2, S2-3** — settle what is in the pinned totals, then repin. Everything downstream depends on it.
3. **S1-3, S2-1** — add repo-scope tokens and make D+ reconcile from its parameters.
4. **S1-2, S1-4** — per-implementation draws and truncation-aware expectations; correct the published CV.
5. **S3-1** — decide between sensitivity analysis and parameter uncertainty. This is a judgment call about
   what the model is for, not a bug fix.
6. **S3-3, S3-4, S3-5, S2-4, S2-5** — text and specification corrections.
7. **S4** — editorial.


---

## Closure record

| Defect | Resolution |
|---|---|
| S1-1 escape scaling not mean-preserving | `exp(λθ − λ²/2)` and off-branch multiplier `(1 − p·mult)/(1 − p)`. Simulated mean `e` now matches derived `e` to within Monte Carlo error in every scenario; mandatory property test specified |
| S1-2 attempts per story vs per implementation | Independent `A` and `L` per implementation. Epic token CV 7.1% → **4.1%** |
| S1-3 D+ irreconcilable | Apparatus restated: oracle 4,460M, crosstest 768M, integration 200M, repo-scope 1,850M. Generation 2,557M + apparatus 7,878M = **10,435M**, matching the pinned 10.44B |
| S1-4 truncation ignored | `E[A] = Σ (1−p)^k for k < A_max` everywhere. Fallback recomputed properly: **0.4 stories in D**, 6.4 in A; the 10% figure relabelled a stress case |
| S2-1 Step 10 consumed no tokens | `repo_scope_tokens` added as a fifth apparatus category: 200M in C, 250M in D, 1,850M in D+ |
| S2-2 $1,500 hours ambiguity | Both architecture decisions and switch cost included, and named as separate lines in all three documents |
| S2-3 restructuring reserve absent | Included at 5% of the criteria/review/spec/architecture base |
| S2-4 undefined quantities | `fallback_hours` = 8.0, `adjudication_rate` = 0.40 (Step 7 scenarios only), `restructure_fraction` = 0.05 |
| S2-5 `N_impl` buys nothing | Stated explicitly, with the best-of-N extension named and deliberately declined |
| S3-1 variance decomposition | `d`, `m`, `q_rev`, `S` and a global `k` scale given distributions; decomposition recomputed on genuinely random sources only, with "does not sum to 100%" stated |
| S3-2 deterministic ≠ P50 | Deterministic pass pinned separately; it lands near the mean, above the median |
| S3-3 human review double-counted | Removed from the `ρ` menu; enters only through `q_rev` |
| S3-4 ρ̂ survivor | Sentence deleted and replaced with the chosen-not-measured statement |
| S3-5 superadditivity null | Multiplicative null 54%, D 66%, **synergy +12 points** |
| S4-1 heading collision | Subsections renumbered 1–9 |
| S4-2 CV overgeneralised | Restated per class: Routine 0.5, Standard 0.7, Hard 0.9 |
