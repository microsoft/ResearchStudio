# Aggregate Over Diverse Candidates
_id: `candidate_aggregation_over_diversity` · confidence: **low** · O6/H2/R3 · meta cov O5/6, H1/2, R3/3_

**Plain alias**. _Combine many imperfect candidates instead of perfecting one_

**Definition**. Replace single-path outputs with aggregation over a diverse set of independently generated candidates—samples, agents, retrievers, sub-models, debate rounds—using voting, weighted combination, or consensus to suppress individual errors and amplify shared signal.

**Operational signature**. generate diverse candidate set {c_i} via stochasticity or heterogeneity → score/aggregate via voting, weighting, or consensus → return aggregated result with improved robustness

**When to apply**. When the correct answer is stable across perturbations but individual passes are noisy, or when the failure modes of different candidate generators are uncorrelated.

**Sample note**. Sample sizes are small (n_oral=6, n_reject=3, n_hc=2); meta-review coverage is adequate (Oral 83%, Reject 100%) but HC is too small to support an Oral-vs-HC contrast, so confidence is set low.

## Step-by-Step
1. Identify the regime where single-shot perfectionism dominates: stable correct answer across perturbations, individual passes noisy.
2. Specify the source of diversity (random sampling, structural heterogeneity, learned policy diversity) and prove or empirically show it is genuinely independent — not relabeling.
3. Specify the aggregation rule: weighted vote, consensus, layered cross-conditioning, or closed-form weighted aggregation — pick the rule the error model justifies.
4. State the error model under which aggregation provably dominates single-best (independence, voting majority, support coverage) — without an error model, aggregation is a heuristic.
5. Run the aggregation; report the diversity statistics that justify the assumed error model — independence claims need induced-diversity analysis.
6. Compare against the strongest single-pass baseline and against simpler aggregation rules — gains over both are the threshold for novelty.

## Success conditions (from Oral)
- **Accompany the aggregation with a formal guarantee or a measurable independence argument — a bound, a theorem, or controlled ablations that show the candidates carry complementary (not redundant) errors.**
  - evidence: `ICLR_2023_0165`, `ICML_2025_1710`
  - ICLR_2023_0165 extends weighted least squares to vector-valued outputs so the aggregation parameter is computable from source data with a provable target-error bound; ICML_2025_1710 runs systematic FM-by-granularity ablations to identify exactly when complementary signals exist. Both replace the intuition 'diversity should help' with evidence it does.
- **Re-frame the problem so that aggregation becomes the natural primitive rather than a post-hoc combination trick.**
  - evidence: `ICLR_2025_1509`, `NeurIPS_2025_1845`, `ICML_2023_0475`
  - Mixture-of-Agents recasts inference as a collaboration medium where competing outputs are first-class inputs; COMPASS recasts RL performance ceilings as inference-sampling failures rather than training failures; Instant Soup recasts pruning-plus-ensembling as a single weight-averaging pass. Each reframing relocates the novelty from 'we combined k models' to 'the object we aggregate is different.'
- **Decompose the task before aggregating, assigning different generators to sub-problems matched to their competence.**
  - evidence: `ICLR_2025_1360`, `ICLR_2023_0165`
  - BIRD splits LLM work into factor enumeration vs. conditional probability estimation before assembling a Bayesian network; the UDA paper extends aggregation to vector-valued outputs so each dimension can be handled by a different system. Structured division of labor is what keeps aggregation from just averaging noise.
- **Empirically establish that diversity is genuine and load-bearing by varying candidate sources and showing the aggregate exceeds the strongest individual.**
  - evidence: `ICLR_2025_1509`, `ICML_2025_1710`
  - MoA shows performance improves even when peers are weaker than the synthesizer, proving the gain is not 'pick the best model'; the FM subset-selection paper shows the multi-FM ranker beats any single FM across fine-grained datasets. Without this evidence reviewers suspect the ensemble is just oracle selection in disguise.
- **Account explicitly for the k-fold candidate budget, either by bounding it, amortizing it, or treating compute as a first-class experimental axis.**
  - evidence: `ICML_2023_0475`, `NeurIPS_2025_1845`
  - Instant Soup collapses k training passes to 1 before claiming ensemble quality; COMPASS treats inference compute as an explicit axis against which ceiling-breaking is demonstrated. Orals preempt the 'you just used k× compute' critique that sinks many Reject papers.

## Failure modes (from Reject)
- **Aggregation is asserted to induce diversity but the mechanism producing uncorrelated candidates is neither proven nor measured.**
  - evidence: `ICML_2025_1734`, `ICLR_2023_0401`
  - Jakiro's reviewers explicitly complained it 'lacks justification and convincing analysis why MoE would lead to more diversity benefits'; the retrieval hybrid paper likewise combined dense+sparse without quantifying independence between the two signals. Without a diversity measurement, the method looks like it could reduce to a single generator with extra parameters.
- **Additive stacking of off-the-shelf components where the aggregate gain cannot be distinguished from the strongest individual component.**
  - evidence: `ICLR_2023_0401`, `ICML_2025_1734`
  - Reviewers of the search-agent retrieval paper found the contribution over prior iterative retrieval small because dense+sparse+reranker are each pre-validated; similarly Jakiro stacks MoE onto EAGLE draft models. In both cases the aggregation is a composition, not a reframing, so reviewers credit the parts, not the ensemble.
- **No cost/latency accounting for the k-fold candidate budget that aggregation implies.**
  - evidence: `ICLR_2023_0401`, `ICML_2025_1734`, `NeurIPS_2025_1832`
  - Reject meta-reviews consistently demand latency discussion (retrieval paper), efficiency and memory ablations vs. non-ensemble baselines (Jakiro), or deeper insight beyond cost savings (AdaCoT). Diverse-candidate methods multiply compute, and reviewers refuse to grant acceptance when that multiplier is hidden.
- **Framing the aggregation as a principled optimization while the method collapses to hyperparameter tuning.**
  - evidence: `NeurIPS_2025_1832`, `ICML_2025_1734`
  - AdaCoT's Pareto framing 'basically reduces to tuning penalty coefficients in an RL reward function' per the AC; Jakiro's MoE diversity claim likewise reduces to weighting expert outputs without a formal independence argument. When the scaffolding can be unwrapped back to knob-turning, reviewers classify the work as engineering, not science.

## Oral vs Reject gap
> Oral papers prove or measure that their candidates carry uncorrelated errors before claiming aggregation helps — via a target-error bound computable from source data (ICLR_2023_0165), controlled ablations across many foundation models and granularities (ICML_2025_1710), or a reframed problem statement that makes aggregation the primitive (NeurIPS_2025_1845 reframes performance ceilings as inference-sampling failures; ICLR_2025_1509 reframes inference itself as a collaboration medium). Reject papers introduce a diversity mechanism (MoE experts, dense+sparse retrievers, adaptive triggering) but skip the 'why are these candidates actually independent?' step, leaving reviewers with a composition of known parts whose gain could come from any single component. Orals also account explicitly for the multiplicative cost of producing k candidates (COMPASS treats compute budget as a first-class axis; Instant Soup collapses k passes to 1); Rejects either hide or under-analyze latency and memory overhead. The asymmetry is structural, not rhetorical: Orals change the object being aggregated, Rejects change only the aggregator on top of a conventional pipeline.

## Oral vs HC gap
> HC sample (n=2) too small for reliable contrast.

## Reviewer expectations
- _[both]_ A theoretical or mechanistic explanation for why the chosen candidate-generation scheme produces uncorrelated (or at least complementary) errors, not just that it produces many candidates.
- _[oral_reviews]_ Controlled experiments identifying the regime where aggregation wins and where it fails (e.g., granularity, task difficulty, budget), not only headline accuracy numbers.
- _[reject_reviews]_ Explicit accounting for the compute/latency cost of generating and scoring k candidates, with comparison against matched-compute single-path baselines.
- _[both]_ A clear articulation of what conceptual shift the aggregation enables (e.g., inference as collaboration, ceiling as sampling failure) rather than presenting the method as a composition of existing tricks.
- _[reject_reviews]_ Differentiation from close prior work that already combined similar ingredients — reviewers penalize heavily when the delta over a cited predecessor is unclear.
- _[oral_reviews]_ Evidence that the aggregation result exceeds the best single candidate, not merely the average candidate, ruling out the 'oracle selection would be sufficient' objection.

## Cognitive barriers
- The prior belief that combining imperfect candidates amplifies rather than cancels their errors — making researchers default to 'pick the single best' rather than 'weight them all' (ICLR_2023_0165, ICLR_2023_0339).
- Treating powerful models as monolithic black-box reasoners rather than as replaceable components in a structured division of labor (ICLR_2025_1360, ICML_2024_1047, ICLR_2025_1509).
- Framing performance limits as training-time failures that demand bigger models or more data, rather than inference-time sampling failures that admit cheap test-time fixes (NeurIPS_2025_1845, ICLR_2023_0339).
- Failing to connect separately-developed research threads — the methodology often requires fusing two existing primitives that nobody had linked, e.g. model soups + lottery tickets, or CoT + majority vote (ICML_2023_0475, ICLR_2023_0339).

## Representative examples
- **[Oral]** `ICLR_2023_0165` — Turns 'which model do I pick without a validation signal?' into a closed-form weighted aggregation with a provable target-error bound — the only paper in the set that derives an aggregation guarantee rather than asserting one.
  - _Lesson_: Convert 'which model do I pick' into a closed-form weighted aggregation with a provable target-error bound — the only paper in the set that derives an aggregation guarantee rather than asserting one.
- **[Oral]** `ICLR_2025_1509` — Reframes inference from a single-pass, single-model process into a layered cross-output conditioning pipeline, making 'feed competing outputs back as context' a first-class architectural primitive rather than a post-hoc combination trick.
  - _Lesson_: Reframe inference as a layered conditioning pipeline — feeding competing outputs back as context becomes a first-class architectural primitive, not a post-hoc combination.
- **[Oral]** `NeurIPS_2025_1845` — Recasts RL performance ceilings as inference-time sampling failures (the right answer lives in the policy's support but not its mode), justifying diversity-driven test-time search without additional training.
  - _Lesson_: Recast performance ceilings as inference-time sampling failures — when the right answer is in the policy's support but not its mode, diversity-driven test-time search is justified without retraining.
- **[Oral]** `ICML_2023_0475` — Fuses two previously disconnected threads (model soups and lottery tickets) to collapse an O(k) multi-retraining ensemble into an O(1) single-pass procedure that still preserves candidate diversity.
  - _Lesson_: Fuse two previously-disconnected threads to collapse multi-retraining into single-pass — the contribution is the structural fusion, not either component alone.
- **[Reject]** `ICML_2025_1734` — Claims MoE experts generate statistically independent speculative-decoding candidates but provides no theoretical or empirical analysis of the induced diversity, exactly the gap reviewers flagged as fatal.
  - _Lesson_: Independence claims need analysis — 'MoE experts generate statistically independent candidates' without theoretical or empirical support is the gap reviewers flag as fatal.
- **[Reject]** `ICLR_2023_0401` — Combines dense + sparse retrieval with a cross-encoder reranker — three pre-validated components whose additive composition reviewers found indistinguishable from prior iterative-retrieval work.
  - _Lesson_: Additive composition of pre-validated components reads as iterative-retrieval reuse — the aggregation must produce a structural advantage the components don't have individually.