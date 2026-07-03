# Reframe as a Solvable Object
_id: `reframe_as_solvable_object`_

**Plain alias**. _Reformulate the unsolved as a solvable object_

**Definition**. Recast an intractable problem as a different, well-studied mathematical object — combinatorial selection, an optimization/constraint program, a game/equilibrium, or a supervised-relabeling problem — so that existing solvers and guarantees apply.

**Operational signature**. identify an intractable problem → recast it as a well-studied object (subset selection, game, constraint, supervised relabeling) → solve with that object's existing machinery

**When to apply**. When the native formulation is intractable but isomorphic to a problem class with mature solvers or guarantees.

## Success conditions (from Oral)
- **A correspondence theorem ties the reframed object's solution to the original problem's solution.**
  - rationale: Across accepted work the load-bearing contribution is a proof — the equilibrium recovers individually-ordered components, a near-stationary point extends to a full-problem equilibrium, a submodular objective makes greedy near-optimal, corrected data provably beats removal. Without this the reframe is a restatement, and the new solver's output has no claim to be the answer to the original question.
- **The chosen object dissolves the specific blocker and unlocks machinery the native formulation could not access.**
  - rationale: Decentralized updates, closed-form attribution, long-horizon sequence-model scaling, or value-free supervision follow directly from the object choice. The reframe earns acceptance by importing concrete capability — parallelism, tractability, sample efficiency — not just new vocabulary for the same difficulty.
- **The reframe deletes a component rather than wrapping new machinery around the old pipeline.**
  - rationale: Collapsing an estimate-then-optimize loop into a pure supervised fit, bypassing model training to read a quantity directly, or replacing exponential subset re-evaluation with an analytic per-step term both simplifies and stabilizes. Reviewers treat the disappearance of a previously-mandatory component as evidence the isomorphism is real rather than cosmetic.
- **The structural condition enabling the equivalence is stated explicitly and its boundary acknowledged.**
  - rationale: Accepted papers name the residual architecture, separability condition, or algebraic-combination assumption that makes the mapping valid, so a reader knows exactly when the reframe transfers and when it does not — converting a clever trick into a reusable result.
- **Faithfulness back to the original problem is independently validated.**
  - rationale: Causal interventions, oracle ground-truth constructions, or recovery proofs confirm that solving the new object solves the original and not a degenerate proxy — guarding against the failure where the reframed solver optimizes something subtly different from the intended target.

## Failure modes (from Reject)
- **The reframe is a mechanical wrapper that re-applies an existing solver to a new input granularity or domain without introducing new identifying structure.**
  - rationale: When the target object is granularity-agnostic to begin with, 'reframing' reduces to a calling convention; reviewers flag limited novelty because the object solves nothing the original tool did not already handle, and the contribution evaporates under scrutiny.
- **The correspondence between the new object and the original problem is asserted but never proven or motivated.**
  - rationale: If the reason the object's solution is 'correct' — an equal-credit split, a frequency-based importance, a particular reference set — stays at the level of intuition, reviewers cannot accept the reframe as grounded, no matter how strong the empirical numbers, because there is no argument that the right thing is being optimized.
- **The central object being solved is left informally defined.**
  - rationale: When the very construct under study (a behavior, a payoff, the 'true' attribution, a threat model) is never formalized, the reframed problem is indistinguishable from standard practice and any guarantees about it are vacuous; reviewers repeatedly cannot tell what new problem has actually been posed.
- **The tractability or scalability the reframe promises is not delivered, or rests on an assumption that rarely holds in practice.**
  - rationale: The payoff that justified the reframe is the new solver's efficiency; a reformulation whose solver does not scale, or whose equivalence depends on an exact structural relationship that seldom obtains, removes the only reason to prefer the new object over the original.
- **The reframe produces a descriptive comparison, benchmark, or taxonomy rather than a solvable object with actionable output.**
  - rationale: Reframing a question as 'compare these approaches' yields observations, not a crisp transferable principle; even reasonable framings fall below the contribution bar when they leave the reader with no operational takeaway about what to do next.

## Oral vs Reject gap
The decisive, observable difference is whether a correspondence is proven and whether the new object actually unlocks something. Accepted work pairs the reframe with a load-bearing theorem — the game's equilibrium recovers the ordered components, a near-stationary point extends to a full-problem equilibrium, the objective is submodular so greedy is near-optimal, corrected data provably lowers held-out error versus removal — and then shows the object imports machinery the native formulation blocked: decentralized updates, closed-form attribution computable from a few snapshots, sequence-model scaling, or value-estimator-free supervision. Rejected work typically stops at the reformulation: it wraps an off-the-shelf solver (a variance decomposition, a Shapley estimator, a linear program) around a new input granularity or domain, leaves the reason the object's solution is 'correct' at the level of intuition (an equal-credit split, a frequency definition), or never formally defines the object being solved (an undefined deceptive action, an unspecified threat model). A second concrete tell: accepted reframings delete a previously-mandatory component (an estimator, a retraining loop, a centralized normalization) and verify the promised tractability at the claimed scale, whereas rejected ones add machinery and leave scalability or a load-bearing assumption (an exact algebraic relationship) unexamined.

## Oral vs HC gap
The HC sample is small (five papers) and skewed toward one sub-family — extracting a structured object from a trained system (a computational circuit, a portable task vector, a covariance-eigenvalue reliability score, sparse interpretable latent dimensions) and validating it causally. These papers succeed by demonstrating that the object exists and causally drives behavior, but they remain largely phenomenological: the object is found and probed, not derived from a principle, and they carry no correspondence guarantee or optimality result — several are explicitly noted as showing 'that' the object exists without explaining 'how' or 'why' it must. Oral papers in the same territory go a step further: they derive the reframing from first principles, state the structural condition under which the mapping is valid, and show the reframed object enables a new capability or a provable improvement rather than a measurement. Put plainly, an HC paper convincingly answers 'this object exists and matters'; an Oral paper additionally answers 'here is why solving this object is equivalent to solving the original, and here is what that equivalence buys you.'

## Reviewer expectations
- **Prove the reduction or equivalence rather than assert it — demonstrate that the reframed object's solution corresponds to (or provably bounds/improves) the original's, ideally isolating the one construction that makes it work.** _(source: both)_
- **Formally define the central object being solved; a behavior, payoff, or 'correct' quantity left informally specified is treated as fatal because reviewers cannot tell the reframed problem apart from standard practice.** _(source: reject_reviews)_
- **Show the reframe contributes new identifying structure rather than re-applying existing machinery to a new input or domain — re-application alone is scored as limited novelty.** _(source: reject_reviews)_
- **Validate faithfulness to the original problem with causal intervention or a ground-truth oracle, not just downstream metric gains.** _(source: oral_reviews)_
- **Examine the new solver's scalability and the assumptions the equivalence rests on; unproven convergence can be tolerated if the empirical payoff is shown, but unexamined scaling or a brittle structural assumption is penalized.** _(source: both)_
- **Deliver an actionable principle, not a descriptive taxonomy or benchmark observation; reframings that yield only 'observations' about the problem fall below the bar.** _(source: reject_reviews)_

## Cognitive barriers
- The two problems are habitually treated as belonging to separate problem classes with separate, incompatible toolchains, so the isomorphism that would let one borrow the other's solvers is nearly invisible — especially when the relevant sub-communities rarely cross-pollinate.
- A structural feature that looks like an obstacle to optimization — a circular dependency between the scoring rule and what it scores, a hard constraint, a missing supervision channel — is, after reframing, the very thing that makes the new object's solution unique or correct; the instinct is to engineer it away rather than to build on it.
- The native formulation carries components that feel mandatory (a value estimator, a retraining loop, parameter-space sampling, exhaustive subset evaluation), and it is hard to doubt that an entire load-bearing component is actually an unnecessary detour the reframing can delete.
- There is a tacit belief that theoretical convergence or optimality guarantees, or full advance knowledge of the problem's structure, are prerequisites before a borrowed solver may be applied — when in fact the machinery can transfer to the broader regime and the missing structure can be estimated online.

## Examples
### Oral lessons
- Reframing a rotation-invariant joint objective as a game with hierarchically-ordered per-agent penalties recovers the individually-ranked components the joint form structurally cannot distinguish — and the same move unlocks decentralized, normalization-free updates.
- Relabeling each collected trajectory by the outcome it actually reached turns suboptimal data into optimal demonstrations, collapsing an estimate-then-optimize loop into a single stable supervised fit.
- Casting attribution as subset selection under a provably submodular objective lets greedy search return compact, near-optimal explanations where continuous global scoring stays diffuse.
- An intractable high-dimensional kernel regression becomes a small dense linear system once per-instance features are randomly projected, recovering ensemble-level accuracy from only a few model snapshots.
- Recasting dynamics modeling as autoregressive prediction over discrete tokens imports long-horizon sequence-model machinery and decouples sequence length from raw observation dimensionality.
- Estimating an irreducible target quantity directly as the expectation of a marginal statistic can eliminate the model-training step the field had assumed was mandatory.

### Reject lessons
- Applying a granularity-agnostic decomposition to coarser input groups through a thin wrapper, with no new identifying structure, reads as repackaging an existing tool rather than a contribution.
- Linearizing a computation and splitting credit equally across factors yields tidy closed-form scores, but without a principled argument for why that split is the right one the object's solution is unmotivated.
- Leaving the central object informally defined — an undefined behavior, a benchmark payoff, a 'true' attribution — makes the reframed problem indistinguishable from standard practice and its guarantees vacuous.
- Proposing a tractable reformulation whose solver does not actually scale, or whose key step assumes an exact structural relationship that rarely holds, undercuts the very tractability that motivated the reframe.
- Reframing a problem as an empirical comparison or taxonomy produces descriptive observations rather than a solvable object with a crisp, actionable takeaway.
- Substituting one oracle for another is promising, but validating it only on small, analytically tractable cases fails to show the reframe delivers where the original formulation actually broke.

_(corpus support: 79 papers under cluster-level primary)_