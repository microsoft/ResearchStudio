# Substitute the Operator or Representation
_id: `architectural_operator_substitution`_

**Plain alias**. _Substitute the operator or representation_

**Definition**. Replace or relocate a costly computational operator, primitive, or intermediate representation with a cheaper surrogate that provably preserves the essential property (expressivity, sensitivity bound, curvature spectrum), breaking a complexity or cost bottleneck.

**Operational signature**. identify an expensive operator or representation → substitute a cheaper surrogate → prove it preserves the essential property (expressivity, sensitivity, curvature)

**When to apply**. When a cost/complexity bottleneck comes from an operator or representation that can be cheaply approximated without losing what matters.

## Success conditions (from Oral)
- **The substitution is anchored by an explicit, named structural invariant that is proven to hold rather than assumed.**
  - rationale: Accepted work isolates the precise algebraic property (positivity, low-rank-plus-normal structure, bounded per-element sparsity, a bijective correspondence) that makes the cheaper form compute the same object; this invariant is what converts 'a cheaper approximation' into 'a guaranteed-equivalent rewrite,' and its absence is what makes a swap look arbitrary.
- **The preserved property is delivered as a formal guarantee with bounds, not as benchmark parity.**
  - rationale: When the essential quantity (estimation bias, approximation error, traversal-path length, landscape geometry, additive error) is bounded in closed form, reviewers can verify the surrogate is faithful independent of any dataset, which is why theoretically-grounded substitutions become durable references.
- **Optimality or necessity is pinned down via matching lower bounds or insufficiency arguments.**
  - rationale: Proving a lower bound that the surrogate meets, or proving that each cheaper ingredient alone fails, upgrades a scalability claim from 'we found something faster' to 'this is as good as possible,' which is the structural difference between a useful trick and a settled result.
- **One substitution resolves multiple symptoms traced to a single shared root cause, or unifies two previously-separate constructs.**
  - rationale: Diagnosing that two apparently independent pathologies (slow convergence and high cost, two parallel modeling paradigms) share one mechanism, then dissolving both with one change, demonstrates that the author understood the structure rather than patched a surface symptom.
- **The cheaper form is shown to be efficient in practice — hardware-friendly and drop-in — not only asymptotically.**
  - rationale: Substitutions that map onto dense linear algebra, fast algorithmic primitives, or existing pipelines without architectural rewrites get adopted and built upon, so the asymptotic win is realized as a real, reproducible speed/memory gain rather than a paper-only complexity claim.
- **Validity is demonstrated across heterogeneous domains, modalities, or constraint models from a single mechanism.**
  - rationale: Showing the same surrogate works across unrelated tasks (or instantiates uniformly across multiple trust/constraint models via one oracle interface) signals the contribution is the structural principle itself, not a benchmark-specific tuning.

## Failure modes (from Reject)
- **A known cheap surrogate is wrapped around an existing pipeline without surfacing any new identifying structure.**
  - rationale: When the move amounts to attaching a generic sketch, a fixed curvature proxy, a solver substitution, or composing two prior results, reviewers read it as methodological dressing; the cheaper machinery is real but no previously-blocked structure was unlocked, so the contribution collapses to recombination.
- **Preservation of the essential property is claimed but supported only empirically or under contrived, restrictive regimes.**
  - rationale: An equivalence shown on a single toy experiment, a degenerate dimensionality, or resting on an unproven ansatz fails precisely on the claim reviewers stress-test, because the whole chain of downstream results inherits the unverified linchpin and cannot be trusted at scale.
- **The reported gain is confounded — not isolated from co-introduced components or measured against the strongest efficient baselines.**
  - rationale: Substituting the operator while also adding features, normalization fixes, or new pretraining, then comparing only to the original expensive baseline, makes it impossible to attribute improvement to the substitution itself, and reviewers consistently flag the missing ablation or the missing efficient competitor.
- **The substitution is technically correct but judged obvious or incremental.**
  - rationale: If the equivalence was already implicitly known, trivially adaptable from a prior proof, or improves only a small constant, the work is penalized regardless of clean execution, because demonstrating the move is not the same as demonstrating that reaching it was hard.
- **The real bottleneck is left untouched, producing a silent performance ceiling.**
  - rationale: Swapping the named-expensive operator when the binding constraint actually lived in the surrounding modules or the learning signal yields a system that runs without error yet cannot exploit the intended capacity, which reviewers detect as unexplained or saturated gains.
- **Presentation obscures the load-bearing argument, or the claim is overstated relative to what is shown.**
  - rationale: When the key derivation is buried, a parallelization or generality claim is asserted but not actually delivered, or correctness becomes unclear, reviewers cannot locate the contribution and default to rejection even when the underlying idea has merit.

## Oral vs Reject gap
The sharpest observable split is proof versus assertion of preservation: accepted work names a specific, previously-unrecognized structural invariant (a positivity constraint, a low-rank-plus-well-conditioned decomposition, a bounded-sparsity property, a bijective dual) and proves the cheaper surrogate retains the essential quantity, whereas rejected work substitutes an already-known cheaper form and supports equivalence empirically or only on a contrived regime (single experiment, degenerate width, unproven ansatz). Accepted papers go further and pin down necessity — matching lower bounds, proofs that each ingredient alone is insufficient, or a demonstration that training independently recovers the constructed configuration — while rejected papers present one feasible cheaper form without arguing why it is the right one or why the discarded structure was redundant. Accepted work also isolates the substitution's effect with ablations and reports a concrete complexity collapse against the strongest efficient alternatives; rejected work confounds the gain with co-introduced components or compares only to the original expensive baseline. Finally, rejected substitutions frequently leave the true bottleneck untouched (the surrounding modules or the training signal), producing unexplained or saturated gains, whereas accepted ones diagnose the binding constraint correctly before swapping it.

## Oral vs HC gap
The high-cited-but-non-Oral sample here (roughly ten papers) is dominated by strong, immediately adoptable substitutions — disentangled or convolution-generated positional encodings, large-kernel convolutions replacing attention, residual-MLP backbones, anchor-box queries, gather-and-distribute fusion — that win decisively on empirical effectiveness, simplicity, and drop-in usability, and several were explicitly tagged by reviewers as 'incremental' in novelty (the core mechanism recombined from prior art). What lets a substitution graduate to Oral is the addition of a closed formal result that grounds the swap: a provable preservation guarantee (unbiased estimation, numerical stability, simultaneous path-length-and-complexity bounds, a spurious-minima-free landscape theorem), a matching lower bound establishing optimality, or a constructive equivalence that training is then shown to recover — rather than a mechanism whose justification remains empirical. Put concretely, HC papers establish that the cheaper operator works and is widely usable, often releasing code that drives adoption; Oral papers additionally close a theoretical gap or resolve/unify an open question, so the substitution carries both the engineering payoff and a proof of why it must work. The HC sample is small, so this should be read as a directional pattern rather than a hard law.

## Reviewer expectations
- **Justify the substitution with a proof that it preserves the target property, and explicitly articulate what was technically hard about reaching it — benchmark wins alone do not suffice.** _(source: both)_
- **Provide ablations that isolate the substituted operator's contribution from any co-introduced components (extra features, normalization changes, auxiliary pretraining).** _(source: both)_
- **Compare against the strongest efficient alternatives, not merely the original expensive baseline the surrogate replaces.** _(source: both)_
- **Do not merely recombine known surrogates; reviewers penalize swaps that add no new identifying structure over existing approximations or that read as a composition of prior works.** _(source: reject_reviews)_
- **Show the claimed equivalence or guarantee holds beyond toy or contrived regimes and rests on a proven assumption rather than an unverified ansatz or a single experiment.** _(source: reject_reviews)_
- **Tie the theoretical result back to the practical motivation that justified the substitution, and ensure improvements exceed run-to-run variance against strong baselines.** _(source: both)_

## Cognitive barriers
- The canonical, expensive form is tacitly treated as the irreducible primitive — the natural object the field composes and optimizes around — so no one asks whether an algebraically equivalent but cheaper representation exists that satisfies the same structural requirements.
- Two separate symptoms, or two parallel non-communicating research threads, are assumed to require separate remedies, which hides that a single substitution can dissolve both at once or that the two objects are formally the same thing in different vocabularies.
- An apparent tradeoff (path length versus cost, efficiency versus quality, compactness versus robustness) is accepted as fundamental, when it is actually an artifact of the chosen problem formulation that a reparameterization can break.
- The expensive cost is perceived as a structural inevitability rather than a consequence of operating at the wrong layer — injecting the cheap operation at an intermediate representation instead of the raw input or final output is invisible while the field conflates the task with the level at which it must be solved.

## Examples
### Oral lessons
- When two pathologies appear to need separate patches, hunt for the single shared root cause — one substitution that dissolves both at once is far stronger than two independent fixes.
- Equivalent expressive coverage does not imply equivalent cost: a reparameterization that spans the same function space can still unlock linear-time operations the original form algebraically forbids.
- The decisive move is often one small structural constraint — non-negativity, a low-rank split, a bounded per-element influence — that simultaneously preserves correctness and enables the efficient rewrite.
- Proving a matching lower bound is what turns 'our surrogate is cheaper' into 'our surrogate is optimal,' and that upgrade is frequently what separates a graduating result from a useful trick.
- Changing where you inject the cheap operation — an intermediate, sensitivity-reduced representation rather than the raw input or the final output — can be the entire contribution.
- An expensive mechanism can often be re-read as a familiar cheap one (a memory lookup, a single optimization step, a kernel evaluation); showing that standard training independently recovers that configuration proves the equivalence is real rather than merely analogical.

### Reject lessons
- Wrapping a known approximation — a generic sketch, a fixed second-order proxy, an off-the-shelf solver — around an existing pipeline without surfacing new identifying structure reads as dressing, not contribution.
- An equivalence shown only on a single toy experiment or a degenerate, contrived regime does not establish that the substitution preserves what matters at realistic scale.
- Claiming a property is preserved while leaning on an unproven ansatz or an asserted equivalence leaves the entire result resting on an untested linchpin reviewers will pull.
- Swapping the named-expensive operator while leaving the true bottleneck (surrounding normalization, the pretraining signal) untouched produces a silent performance ceiling that surfaces as unexplained gains.
- Benchmarking only against the original expensive baseline, with no comparison to the strongest efficient alternatives, makes a 'cheaper-and-competitive' claim impossible to credit.
- A correct but already-known equivalence, or a gain that is marginal and within variance against strong baselines, is judged incremental no matter how clean the derivation.

_(corpus support: 109 papers under cluster-level primary)_