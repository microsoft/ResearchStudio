# Exploit Redundancy via Compression
_id: `redundancy_compression_and_distillation` · confidence: **high** · O31/H9/R29 · meta cov O25/31, H7/9, R29/29_

**Plain alias**. _Compress what is redundant_

**Definition**. Identify computational, parametric, or procedural redundancy in an existing system and replace it with a compact reparameterization, low-rank factorization, quantization scheme, or distilled shortcut that preserves predictive fidelity at substantially lower cost.

**Operational signature**. detect redundancy R in system S → design compact proxy P that captures R's essential outputs → train/calibrate P to match S on the task distribution → deploy P in place of S

**When to apply**. When a system is known to be overparameterized, when multi-step inference is unnecessarily expensive, or when a structural property (sparsity, low rank, frequency concentration) permits lossless or near-lossless reduction.

**Sample note**. Sample is adequate (n_oral=31, n_reject=29, meta_coverage 25/31 oral and 29/29 reject); HC sample (n=9) supports a tendency-level Oral-vs-HC contrast but not strong claims.

## Step-by-Step
1. Detect redundancy R in the system: where in the pipeline is compute / memory / parameter budget being spent on structurally removable computation? Localize to a layer / module / phase.
2. Classify R as structural (theoretically removable without loss — low-rank, sparse, separable) vs. empirical (typically noisy, removable with quality cost).
3. Design a compact proxy P that captures R's essential outputs — orthogonal-decomposition (base + adapter), per-layer reconstruction, null-space projection, entanglement-aware factoring.
4. Anchor P with a structural certificate: closed-form geometric guarantee, dropped independence assumption, or per-layer reconstruction objective — not heuristic ratios.
5. Train / calibrate P to match S on the task distribution; preserve the abstraction-level shift (global → per-layer, full → adapter).
6. Validate the compute-quality frontier across the deployment regime — practical throughput must match paper-only efficiency; theory-practice disconnects are flagged.

## Success conditions (from Oral)
- **Anchor compression in a previously-unexploited structural property of the system, then design the compact proxy as a direct algebraic consequence of that property — not as a heuristic shortcut.**
  - evidence: `ICML_2024_1032`, `ICLR_2025_1350`, `ICML_2024_1016`, `NeurIPS_2024_1203`, `ICML_2024_0996`
  - Oral papers consistently locate a specific structural fact the field had overlooked (weight–momentum entanglement, null-space of preserved keys, training-induced parameter manifold, outlier distribution geometry, mutual-information bottleneck) and derive the compression scheme from it. The structural framing is what makes the resulting method principled rather than another point on the compression Pareto front.
- **Decompose the system into orthogonal concerns whose interface is explicit and provably separable, then compress only one side aggressively while keeping the coupled side at full fidelity.**
  - evidence: `NeurIPS_2023_0714`, `ICML_2023_0538`, `ICLR_2024_0886`, `NeurIPS_2023_0685`
  - QLoRA (frozen 4-bit base + full-precision LoRA buffer), SparseGPT (global pruning → per-layer reconstruction), LoftQ (initialize LoRA to absorb quantization residual), and Monarch Mixer (single primitive across two axes) all succeed by exposing an interface that lets compression error be quarantined. Without this clean split, compression-induced distortion contaminates downstream learning.
- **Provide a closed-form, geometric, or information-theoretic derivation that the compressed proxy preserves the relevant signal — before the empirical sweep.**
  - evidence: `ICLR_2025_1350`, `ICLR_2025_1559`, `ICLR_2025_1544`, `ICML_2025_1731`
  - AlphaEdit's null-space projection, the Rotation Trick's exact Jacobian, Progressive Distillation's sample-complexity proof, and IMM's moment-matching guarantee all turn what could have been an empirical ablation into a structural certificate. Reviewers treat the derivation as evidence the gain is not coincidence.
- **Reformulate a discrete, non-differentiable, or multi-step bottleneck as a continuous (or single-step) operation in a transformed domain so end-to-end gradients flow through what was previously opaque.**
  - evidence: `ICLR_2022_0105`, `ICLR_2025_1559`, `ICLR_2021_0054`, `ICML_2025_1793`
  - Fourier-domain stride learning, Householder/Cayley rotations replacing nearest-neighbor lookup, randomized AD over the DAG, and score-of-mixture single-step training all show that a domain change converts a hard combinatorial choice into a differentiable parameter — enabling joint optimization that uniform-precision baselines cannot reach.
- **Use the system itself (or a fixed teacher) as the supervision oracle for compression — reconstruction loss, activation matching, or self-filtered synthetic data — eliminating dependence on the original training corpus.**
  - evidence: `NeurIPS_2025_1898`, `ICLR_2025_1527`, `NeurIPS_2025_1869`, `ICML_2024_1016`
  - KVzip (model reconstructs its own context), data-free CLIP distillation (teacher filters its own synthetic data), grafting (activation matching across operator substitutions), and Riemannian data-free compression all sidestep the data-access bottleneck by treating the trained system's outputs/geometry as the importance signal. This converts compression from a data problem into a model-internal problem.
- **Validate across multiple model scales, architectural families, and downstream tasks — not just a single benchmark — and characterize the failure regime explicitly.**
  - evidence: `ICML_2023_0538`, `NeurIPS_2023_0714`, `ICLR_2023_0181`, `NeurIPS_2024_1203`
  - Oral compression papers routinely cover several LLM sizes (7B–65B), multiple model families, and ablations of the binding constraint (e.g., DuQuant's outlier analysis, SparseGPT's sparsity sweep, climate compression's rare-event failure). Reviewers treat absence of this scope as evidence the structural claim is parochial.

## Failure modes (from Reject)
- **Stitching two existing compression primitives into a 'wrapper' or 'pipeline' without identifying a joint structural property that makes their combination more than additive.**
  - evidence: `ICLR_2023_0283`, `NeurIPS_2023_0761`, `NeurIPS_2023_0690`, `ICLR_2024_0887`
  - MixQuant (bit-width search over arbitrary quantizers), XYZ Data Efficiency (sampling + routing), Architectural Compression (prune + distill for SD), and binary+distill for long-tail all draw 'limited novelty' verdicts because each module was independently validated and the combination is presented as additive rather than as a new structural object.
- **Theory-practice disconnect: theoretical analysis assumes one structure (random vectors, smooth functions, balanced data) but the implementation silently swaps in a different one, leaving the headline guarantee unsupported.**
  - evidence: `ICLR_2023_0221`, `ICLR_2024_0876`, `ICML_2025_1782`, `ICLR_2025_1421`
  - Efficient HDC theorizes over random hypervectors but experiments use a trained BNN encoder; Laplacian Sparsification proves a sparsifier bound without ablating that the sparsified step is the dominant cost; Regression-tree gradients require smoothness atypical of the regimes trees are used in; CCWT's algebraic equivalence isn't backed by wall-clock evidence. Reviewers explicitly flag the gap.
- **Claimed efficiency gains do not translate to the resource the deployment pipeline actually cares about (wall-clock latency, real throughput, supported hardware), leaving the compression a paper-only win.**
  - evidence: `ICLR_2023_0275`, `ICLR_2024_0868`, `ICLR_2025_1374`, `NeurIPS_2024_1197`
  - LVQ-VAE's runtime is too slow to be practical despite SOTA RD curves; KVTQ's ternary scheme fits limited hardware configurations; ClusComp's 1-bit numbers don't match throughput at higher bit-widths; Diff-PCC's stochastic decoder reaches good perceptual quality but reviewers flag undefined fidelity-diversity trade. The proxy P beats S on a metric nobody deploys against.
- **Empirical scope confined to small or stale benchmarks (MNIST/CIFAR, ResNet-only, single model size) so the structural claim cannot be distinguished from overfitting to that regime.**
  - evidence: `ICLR_2023_0247`, `NeurIPS_2023_0637`, `ICML_2025_1766`, `NeurIPS_2024_1265`
  - HRBP evaluated only on CIFAR/ImageNet ResNets; FITS lacks multiple-seed runs; OD³ benchmarks only on RetinaNet/Faster R-CNN with ResNet backbone; NeCGS shows significant compression-time overhead vs baselines. Reviewers downgrade because the binding constraint at deployment scale is invisible.
- **Treating compression and an adjacent stage (adaptation, rebalancing, decoder) as independent modules when they are coupled, so quantization/pruning error propagates into the downstream signal without compensation.**
  - evidence: `NeurIPS_2024_1190`, `NeurIPS_2023_0623`, `ICLR_2024_0806`, `NeurIPS_2024_1264`
  - decoupleQ adds a floating-point correction but reviewers note its similarity to layer-norm without a coupled-stage analysis; EmbedDistill aligns geometries without showing the layer choice is sufficient; orthogonal-gradient NAS treats parameter sharing as independent updates; Adaptive Bit Switching's two-stage rounding lacks coupled analysis. The Oral analog (LoftQ, IR-QLoRA, AlphaEdit) explicitly co-designs the stages.
- **Asserting a universal compression rule over a population that is structurally heterogeneous (outliers, long-tail importance, hetero-modular components), without partitioning the population first.**
  - evidence: `NeurIPS_2023_0750`, `NeurIPS_2024_1266`, `ICLR_2025_1652`
  - Subspace Projection imposes one global subspace on all transformer layers; Neural Expressiveness applies an overlap criterion uniformly; XoRA imposes a fixed expander mask. Compare to Oral counterparts (BiLLM/SqueezeLLM partition by sensitivity strata, MoDeGPT decomposes per sub-module, DuQuant routes outliers separately) — uniform schemes reliably underperform when importance is long-tailed.

## Oral vs Reject gap
> Oral compression papers lead with a *structural* discovery — an unrecognized coupling, geometry, or distribution (weight-momentum entanglement in ExCP, null space of preserved keys in AlphaEdit, long-tail sensitivity strata in BiLLM, outlier-rotation duality in DuQuant) — and derive the compact proxy as the unique consequence of that discovery, often with closed-form initialization or a provable bound. Reject papers, by contrast, present the proxy first and motivate it post-hoc: the abstract describes the method as 'combining', 'wrapping', 'extending', or 'searching over' established primitives (MixQuant, XYZ, Architectural Compression, OD³). A second consistent gap is interface design: Oral papers expose a clean separability between the compressed component and an adjacent fidelity-preserving component (QLoRA's full-precision adapter, SparseGPT's per-layer reconstruction, LoftQ's SVD compensation), whereas Reject papers either compress everything uniformly (Subspace Projection) or stack independent stages without analyzing their interaction (decoupleQ, Adaptive Bit Switching). Finally, Oral papers report wall-clock or downstream-metric evidence that the binding constraint actually moves at deployment scale and characterize the failure regime; Reject papers cite FLOPs, parameter counts, or single-benchmark accuracy and leave the latency/throughput trade-off unexplored (KVTQ, ClusComp, LVQ-VAE).

## Oral vs HC gap
> HC papers (Fourier Neural Operator, Quant-Noise, Progressive Distillation, LLM-Pruner, BiLLM, SqueezeLLM, ProlificDreamer, Language Modeling Is Compression, Long-Term Memory) clear the same structural-discovery bar as Orals — each identifies a non-obvious property (Shannon-ML duality, dense-and-sparse heterogeneity, residual-correction recursion, parameter-drift cache invalidation). The Oral-vs-HC delta is sharper on two axes: (1) Orals more often produce a *theorem-grade* artifact — closed-form null-space projection, provable curriculum complexity, exact rotation Jacobian — whereas HC papers tend to land their structural claim through targeted empirical analysis (e.g., SqueezeLLM's sensitivity profile, BiLLM's importance distribution); and (2) Orals more frequently introduce a primitive that *generalizes beyond compression* (SDS for any 2D-to-3D bridge, Monarch matrix as a substrate, score-distillation as a pretraining objective), where HC papers more often refine compression for a specific target. HC sample is small (n=9) so this is a tendency, not a rule.

## Reviewer expectations
- _[oral_reviews]_ A theoretical or geometric derivation showing that the compact proxy preserves the property the original system relied on, not just empirical parity at a chosen budget.
- _[both]_ Experiments spanning multiple model scales, architectures, and downstream tasks; reviewers explicitly question the structural claim when validation is confined to a single family or small dataset.
- _[reject_reviews]_ Wall-clock or hardware-realistic measurement of the claimed efficiency gain; FLOPs and parameter counts alone are repeatedly called insufficient.
- _[reject_reviews]_ Comparison against the most recent competing compression methods (not just classical baselines) on the same metric the paper claims to advance.
- _[both]_ Explicit characterization of the failure regime — when does the proxy degrade, on which inputs, at which compression ratio — rather than headline numbers at a fixed operating point.
- _[oral_reviews]_ Evidence that the structural claim is non-trivial: a clean ablation isolating the proposed insight from generic engineering improvements (better hyperparameters, more data, larger teacher).

## Cognitive barriers
- Compression and adaptation are assumed mutually exclusive — practitioners expect quantization to corrupt gradient flow, blocking the insight (QLoRA, IR-QLoRA, LoftQ) that a small full-precision buffer can absorb compression error and make the two concerns orthogonal.
- Standard practice equates protecting capability with protecting parameters; reaching gradient-space, null-space, or manifold-space framings (Gradient Projection Memory, AlphaEdit, Riemannian compression) requires shifting the object of protection up an abstraction level.
- Co-produced artifacts (weights and optimizer state, quantization and adaptation, encoder and decoder) are stored or trained as if statistically independent; the entanglement insight (ExCP, IR-QLoRA, EmbedDistill) requires connecting two literatures (optimization theory and compression theory) that operate at different abstractions.
- Discrete or non-differentiable operations (quantization, stride, sorting) are treated as inherently un-trainable; recognizing them as projections, rotations, or frequency-domain crops with exact Jacobians (Rotation Trick, Learning Strides, Randomized AD) requires a domain-change move that practitioners trained inside the original domain don't naturally make.

## Representative examples
- **[Oral]** `ICLR_2025_1350` — AlphaEdit converts a 'do not interfere' statistical objective into an exact null-space projection — a closed-form geometric guarantee that exemplifies how Oral compression/edit work derives the compact proxy from a structural certificate rather than an empirical heuristic.
  - _Lesson_: Convert a statistical objective ('don't interfere') into a closed-form geometric guarantee (null-space projection) — Oral compression derives the proxy from a structural certificate, not a heuristic.
- **[Oral]** `ICML_2024_1032` — ExCP exposes a previously-unrecognized statistical entanglement between adaptive-optimizer momentum and weights — the compression ratio is a direct consequence of dropping an unjustified independence assumption.
  - _Lesson_: The compression ratio is a direct consequence of dropping an unjustified independence assumption between optimizer momentum and weights — diagnosis of a hidden statistical structure beats engineering tuning.
- **[Oral]** `NeurIPS_2023_0714` — QLoRA exemplifies the orthogonal-decomposition pattern: aggressive 4-bit base storage plus a full-precision adapter that acts as a buffer absorbing compression error — the clean interface is what makes 65B finetuning on one GPU work.
  - _Lesson_: Orthogonal decomposition with a clean interface — aggressive base storage + full-precision adapter buffer absorbs compression error. The interface clarity is what makes 65B-on-one-GPU work.
- **[Oral]** `ICML_2023_0538` — SparseGPT decomposes global one-shot pruning into independent per-layer reconstruction problems solved with local Hessians, showing the abstraction-level shift (global → layer-wise reconstruction) that distinguishes Oral compression from heuristic mass pruning.
  - _Lesson_: Abstraction-level shift (global one-shot pruning → per-layer reconstruction) distinguishes Oral compression from heuristic mass pruning.
- **[Reject]** `ICLR_2023_0283` — MixQuant proposes bit-width search as a generic wrapper over any quantizer — a pure 'combine existing primitives' move with no joint structural property, drawing reject votes for limited novelty and weak baselines.
  - _Lesson_: Combining existing primitives without a joint structural property reads as a wrapper — bit-width search over a quantizer is not a methodological contribution.
- **[Reject]** `ICLR_2023_0221` — Efficient HDC's theory assumes random hypervectors but the experiments use a trained BNN encoder, exemplifying the theory-practice disconnect that reviewers reliably flag in compression rejects.
  - _Lesson_: Theory-practice disconnects (random hypervectors in theory, trained encoder in experiments) are reliably flagged in compression rejects.
- **[Reject]** `ICLR_2025_1374` — ClusComp claims 1-bit clustering compression but throughput collapses at higher bit-widths and the practical impact remains unproven — a textbook 'paper-only efficiency win' rejection.
  - _Lesson_: Throughput collapse at higher bit-widths converts the contribution to 'paper-only efficiency win' — practical throughput is the binding metric.