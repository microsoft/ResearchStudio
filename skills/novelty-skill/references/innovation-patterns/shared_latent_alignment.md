# Align Heterogeneous Sources in Shared Space
_id: `shared_latent_alignment` · confidence: **high** · O45/H18/R52 · meta cov O34/45, H12/18, R51/52_

**Plain alias**. _Put different signals into one shared representation_

**Definition**. Project heterogeneous inputs—modalities, tasks, domains, representations—into a common latent space so that a single model, metric, or retrieval mechanism can operate uniformly across them without source-specific machinery.

**Operational signature**. choose shared space Z → learn encoders {E_i} mapping source i into Z under alignment objective → perform downstream tasks in Z with unified operators

**When to apply**. When a task requires crossing modality, domain, or representation boundaries, or when many downstream tasks could be served by one unified backbone if inputs were comparably encoded.

**Sample note**. Sample is large and balanced (n_oral=45, n_reject=52, n_hc=18) with strong meta coverage on the reject side (51/52) and adequate coverage on the oral side (34/45, 76%); HC sample of 18 supports the oral_hc_gap claim.

## Step-by-Step
1. Identify ≥ 2 heterogeneous sources / modalities / tasks the literature treats in isolation — name what each contributes.
2. Establish a structural identity (algebraic, geometric, semantic) that justifies merging them into one shared space — not just empirical correlation between outputs.
3. Choose the shared space Z carefully: continuous latent, tokenized vocabulary, or operator-level alignment — pick the level that respects the structural identity.
4. Learn encoders {E_i} mapping each source into Z under a diagnosis-first alignment objective — identify which component is the modality-bias bottleneck and individualize only that.
5. Operate in Z with unified downstream operators — alignment is a means; the contribution is what becomes derivable / transferable / interpretable in Z.
6. Isolate which alignment component carries the gain via per-component ablation — bundling without isolation draws 'where does the improvement come from' critique.

## Success conditions (from Oral)
- **Identify a specific structural property of the source/target modalities that justifies why a shared space is even reachable, and instantiate that property as a concrete architectural or objective choice (not a generic 'projection layer + alignment loss').**
  - evidence: `ICLR_2021_0041`, `NeurIPS_2025_1906`, `ICML_2025_1825`, `ICLR_2025_1635`
  - Bisimulation distance (0041) gives a fixed-point equation that defines what 'aligned' means; MokA isolates the A matrix as the modality-bias bottleneck; VideoRoPE reasons about frequency allocation rather than token-index allocation; the modality-gap paper traces two phenomena to one information-imbalance cause. In each case the shared-space construction follows from a diagnosed property, not from a generic recipe.
- **Introduce a domain-appropriate discretization or tokenization that lets a heterogeneous source enter the shared space using the dominant paradigm's machinery, rather than reusing an off-the-shelf tokenizer.**
  - evidence: `ICLR_2022_0081`, `ICML_2023_0403`, `ICML_2023_0418`, `ICML_2024_1140`, `NeurIPS_2025_1894`
  - BEiT introduces visual tokens to make masked prediction work for images; Mu²SLAM quantizes speech into tokens that share the text vocabulary; BEATs makes the tokenizer itself learnable and co-evolving; Moirai designs patch+output-scaling to bridge time-series heterogeneity; InfinityStar designs a spacetime pyramid tokenizer. The tokenizer choice is treated as the load-bearing contribution, not as preprocessing.
- **Demonstrate that the shared space unlocks a qualitatively new capability (zero-shot transfer, cross-domain morphing, interpretability, any-to-any generation) rather than only incremental gains on existing benchmarks.**
  - evidence: `ICLR_2022_0137`, `ICLR_2024_0863`, `ICML_2024_1074`, `ICML_2024_1143`, `NeurIPS_2023_0743`
  - StyleAlign uses correspondence in the latent space to perform cross-domain morphing without retraining; CLIP-decomposition turns alignment into an interpretability tool; NExT-GPT enables any-to-any generation through frozen modules; VideoPoet shows emergent multi-task generation from unified tokens; LLaVA bootstraps multimodal instruction-following via text-only GPT-4. Reviewers respond strongly to capabilities that did not exist before alignment.
- **Bridge frozen pretrained components with a small learned interface trained in stages, rather than retraining either side end-to-end, when reusing strong existing models from each modality.**
  - evidence: `ICML_2023_0433`, `ICML_2024_1074`, `NeurIPS_2025_1944`
  - ORCA aligns distributions before fine-tuning a frozen backbone for cross-modal transfer; NExT-GPT trains only lightweight projections between frozen encoders/decoders; Vita-1.5 stages vision then speech curriculum to avoid mutual interference. The decomposition of 'where the alignment lives' into a separable bridging step is consistently rewarded.
- **Apply per-modality objectives or per-modality components within a shared backbone to prevent one modality from dominating, with explicit ablation showing the asymmetric treatment matters.**
  - evidence: `ICLR_2025_1632`, `NeurIPS_2025_1906`, `ICLR_2025_1397`
  - Transfusion mixes next-token loss for text and diffusion loss for images in one transformer; MokA splits A matrices per modality but shares B and adds cross-modal attention; DEPT decouples embeddings per source while sharing the transformer body. Each shows that uniform sharing creates interference and that selective splitting—at exactly the right component—resolves it.

## Failure modes (from Reject)
- **Stack alignment as a generic recipe (separate encoders + projection + contrastive/reconstruction loss + downstream head) without identifying any structural property of the modalities that makes the alignment load-bearing.**
  - evidence: `ICLR_2024_0782`, `ICLR_2024_0948`, `ICLR_2025_1515`, `ICLR_2025_1608`
  - Reject meta-reviews repeatedly note 'combination of existing techniques' or 'limited methodological innovation' (MULAN, SMILE, ICLR_2025_1608). The latent-alignment scaffolding looks correct in isolation, but reviewers flag that the gains are not attributed to any specific property and could equally come from any of the components.
- **Inherit a tokenization or backbone from a source domain (ViT, LLM tokenizer, CLIP encoder) and apply it to the target domain without justifying that the target's structural primitives match the source's, or showing the choice is the right one.**
  - evidence: `ICLR_2023_0391`, `ICLR_2025_1414`, `ICLR_2024_0966`
  - ViTMTSC drops time series into ViT patches; MEIT encodes ECG via a generic 1D CNN for an MLLM; TEST aligns to LLM embedding anchors. Reviewers consistently ask why this specific bridge is appropriate and note absence of analysis showing what about the target's structure justifies the inherited tokenization.
- **Marginal/inconsistent improvements across datasets, where the aligned model wins on one benchmark but only ties or loses on others, exposing that the shared representation is not the binding constraint.**
  - evidence: `ICLR_2023_0259`, `ICLR_2025_1588`, `NeurIPS_2024_1175`
  - Cross-domain MUDA gains hold on DomainNet but not Office-31; DynaMer Adapter shows 0.5-1% improvements; concept-text aggregation receives borderline accept-reject scores. ACs treat inconsistency across datasets as evidence that the alignment mechanism is not the actual driver of the wins.
- **Train the alignment with synthetically generated paired data without validating that the synthesis preserves the structural correspondence the alignment depends on.**
  - evidence: `ICLR_2025_1387`, `ICLR_2025_1399`, `NeurIPS_2023_0610`, `NeurIPS_2023_0611`
  - CtrlSynth, DiffTell, CoVR, and the captioning-curation paper all align via paired data fabricated by another generative model. Reviewers question whether gains transfer to real distributions and whether the synthetic pairings encode the relationship being learned, treating this as an unverified premise of the alignment.
- **Claim a unified shared space across many tasks but evaluate on a narrow set, leaving the universality claim unsupported.**
  - evidence: `ICLR_2024_0782`, `ICLR_2024_0927`, `ICLR_2024_0986`
  - Conditional Protein Generation claims joint-task versatility but is evaluated on inverse folding + docking only; PROSE claims bimodal-bimodal generality on 15 ODE systems; USLNet claims unsupervised sign-language translation/generation but reviewers note poor numerical results. ACs ask for either an extra task showing the unified space pays off, or a narrower claim.
- **Conflate distinct subproblems behind a unification banner without ablations isolating which alignment component carries the gain.**
  - evidence: `NeurIPS_2023_0688`, `ICLR_2024_0801`, `ICML_2025_1737`
  - Multitask face-forgery joint embedding bundles symbolic supervision + shared space + multitask loss without isolating contributions; LEAD bundles dataset curation + sample-level + subject-level contrastive without showing each is needed; multilingual-vision claims rest on aggregated metrics. Reviewers explicitly demand ablations attributing improvements.

## Oral vs Reject gap
> Oral papers diagnose a specific structural property (a fixed-point condition, an asymmetric matrix role, a frequency-allocation problem, an information-imbalance source) and let the shared-space construction fall out of that diagnosis—the alignment objective is not the contribution, the diagnosis is. Reject papers, by contrast, present the alignment scaffolding itself as the contribution: pick two encoders, project to a shared space, add contrastive or reconstruction loss, evaluate. Oral papers also typically introduce a domain-appropriate discretization or interface (BEiT visual tokens, Mu²SLAM speech tokens, BEATs co-evolving tokenizer, Moirai patches) that becomes the load-bearing element; reject papers more often inherit a tokenizer/backbone from a source domain (ViT for time series, LLM embedding for ECG/protein) without showing that the target's primitives match. Finally, Oral papers demonstrate the alignment unlocks a new capability—cross-domain morphing, zero-shot generation across modalities, interpretability tooling—while reject papers report 0.5-2% gains on existing benchmarks with inconsistent improvements across datasets, which ACs read as evidence the shared space is not the binding constraint.

## Oral vs HC gap
> HC papers (n=18) tend to be polished engineering instantiations of an established alignment paradigm: BLIP-2's Q-Former bridges frozen models, AIM adds spatiotemporal adapters to a frozen image model, Make-A-Video factorizes T2V into modular reuse, TimesNet reshapes 1D series into 2D for image-CNN reuse. They succeed by choosing the right bridge between known components and validating it across benchmarks. Oral papers go further by introducing a structural reframing that did not exist before: StyleAlign formalizes correspondence as a discovered invariant rather than a designed objective; CLIP-decomposition turns alignment into an interpretability protocol via additive residual decomposition; the modality-gap paper unifies two phenomena under one information-theoretic cause; MokA diagnoses A vs B asymmetry as the modality-imbalance bottleneck. The Oral move is to make the alignment's existence or geometry into the discovery; the HC move is to bridge well between pre-existing alignments. HC papers also more often defer the conceptual contribution to dataset/scale and validate empirically, while Oral papers spend more pages on why the construction had to take this shape.

## Reviewer expectations
- _[both]_ Ablations isolating which alignment component (which projector, which loss, which matrix, which tokenizer choice) actually drives the gain, not just whole-system improvements.
- _[oral_reviews]_ Demonstration that the shared space transfers or generalizes across tasks/datasets/modalities the model was not directly trained on—zero-shot or held-out behavior, not just in-distribution wins.
- _[reject_reviews]_ Justification for why the chosen tokenization or bridging interface matches the target domain's structural primitives, especially when the bridge is borrowed from another domain.
- _[reject_reviews]_ Comparisons against the strongest contemporary baselines in each modality, including modern foundation models and recent unification methods, to defend that the alignment is the source of improvement.
- _[reject_reviews]_ Consistent improvements across multiple benchmarks/datasets; ACs treat dataset-by-dataset inconsistency as evidence that the alignment mechanism is not the actual driver.
- _[reject_reviews]_ Clear articulation of what is conceptually novel beyond a 'separate encoders + shared projection + contrastive loss' template; reviewers explicitly flag and reject this template when the structural insight is missing.

## Cognitive barriers
- Domain-separation prior: practitioners assume two modalities (speech vs. text, EEG vs. signal, time series vs. language) require different architectures, vocabularies, and objectives, blocking the move to recognize discretization as the bridge that resolves the modality gap (Mu²SLAM, BEiT, time-series-as-pixels).
- Tokenizer-as-fixed-preprocessing: the prediction target / discretization is treated as an upstream design choice rather than a learnable parameter that should co-evolve with the representation (BEATs, BEiT).
- Direct-alignment default: the assumption that two heterogeneous sources must be aligned head-on, missing that an intermediate third modality (text, HTML, latent semantic space) can serve as a bridge that makes the problem tractable (Pix2Struct, UniMedI vs. its rejection, 3D-LLM).
- Architecture-over-distribution framing: cross-modal transfer is assumed to require modality-specific architectures or adapters, obscuring that pretrained backbones are modality-agnostic if input distributions are matched (ORCA, BLIP-2).

## Representative examples
- **[Oral]** `NeurIPS_2025_1906` — MokA exemplifies the diagnosis-first pattern: it identifies the A matrix specifically (not B, not both) as the modality-bias bottleneck in LoRA-based MLLM tuning, and then individualizes only that component while keeping B shared—the alignment fix follows directly from the diagnosis.
  - _Lesson_: The diagnosis-first pattern — identify the A matrix specifically (not B, not both) as the modality-bias bottleneck, then individualize only that component. The fix follows directly from the diagnosis.
- **[Oral]** `ICML_2023_0403` — Mu²SLAM shows the canonical 'tokenize the continuous modality so it joins the discrete vocabulary' move, treating speech tokens as another sequential symbol system inside a multilingual text framework rather than building a separate speech encoder.
  - _Lesson_: Tokenize the continuous modality so it joins the discrete vocabulary — treating speech tokens as another sequential symbol system is a cleaner unification than separate-encoder + alignment-loss.
- **[Oral]** `ICLR_2024_0863` — CLIP decomposition repurposes an existing shared latent space as an interpretability tool by additively decomposing the image representation across heads/layers/tokens and projecting summands into text—turning alignment into a downstream capability rather than a training objective.
  - _Lesson_: Repurpose an existing shared latent as an interpretability tool — additive decomposition across heads / layers / tokens, projecting summands into text. Alignment becomes a downstream capability, not the training objective.
- **[Oral]** `ICLR_2025_1635` — This paper unifies two separate empirical phenomena (modality gap and object bias) under a single information-imbalance cause—showing the cognitive move that distinguishes Orals: collapsing apparently distinct symptoms into one root property of the shared space.
  - _Lesson_: Collapse apparently-distinct symptoms into one root property of the shared space — information-imbalance unifies modality gap and object bias under a single cause.
- **[Reject]** `ICLR_2025_1515` — MULAN attaches a structure-aware adapter to a protein language model to inject a complementary modality, but reviewers found the alignment template indistinguishable from prior structure-aware PLMs and the gains incremental—a clean case of 'alignment scaffolding as the contribution' failing.
  - _Lesson_: Alignment scaffolding indistinguishable from prior structure-aware work draws 'incremental' critique — the structural identity must be specifically new.
- **[Reject]** `ICLR_2023_0391` — ViTMTSC reshapes multivariate time series into 2D images and applies a pretrained ViT—exemplifying the inherited-tokenizer failure mode where the source-domain primitive is reused without justifying that target structure matches.
  - _Lesson_: Inheriting a tokenizer from another domain (here: ViT for time series) without justifying that target structure matches the source primitive is the inherited-tokenizer failure.
- **[Reject]** `NeurIPS_2023_0688` — Joint embedding for face forgery bundles multitask + symbolic supervision + shared latent space without isolating which alignment component carries the gain, drawing exactly the 'where does the improvement come from' critique reviewers raise repeatedly.
  - _Lesson_: Bundling multitask + symbolic supervision + shared latent without per-component ablation draws 'where does the improvement come from' — alignment claims must be ablated.