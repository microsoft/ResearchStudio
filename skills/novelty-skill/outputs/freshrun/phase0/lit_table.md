# Phase 0 lit_table — diffusion sampling acceleration (freshrun)

Top 15 papers from 29 deduped retrieval hits, classified per pattern-summary-rubric.md.

| paper_id | year_month | venue | title | methodology tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem | retrieved_via |
|---|---|---|---|---|---|---|---|---|
| openalex:W4402557656 | 2024-09 | TPAMI / IEEE Trans | Efficient Diffusion Model for Image Restoration by Residual Shifting | redundancy_compression_and_distillation | hundreds of sampling steps required for diffusion-based IR | residual shifting reformulation that achieves few-step IR sampling | | openalex |
| arxiv:2604.10857v1 | 2026-04 | arXiv | Query Lower Bounds for Diffusion Sampling | analytic_refinement_of_loose_bounds | information-theoretic limits of score-evaluation reduction unknown | tight matching upper-lower bounds for query complexity | analytic_refinement_of_loose_bounds: query-complexity lower bound | arxiv |
| arxiv:2603.24260v1 | 2026-03 | arXiv | Accelerating Diffusion-based Video Editing via Heterogeneous Caching | redundancy_compression_and_distillation; decomposition_into_tractable_stages | DiT-based video editing computationally expensive due to iterative denoising | heterogeneous caching across diffusion timesteps | | arxiv |
| arxiv:2603.19570v1 | 2026-03 | arXiv | Accelerating Diffusion Decoders via Multi-Scale Sampling and One-Step Distillation | redundancy_compression_and_distillation; decomposition_into_tractable_stages | iterative diffusion decoders expensive in tokenization pipeline | one-step distillation with multi-scale stage decomposition | | arxiv |
| dblp:conf/aaai/LiuXYDCTFLZ25 | 2025 | AAAI | SCott: Accelerating Diffusion Models with Stochastic Consistency Distillation | redundancy_compression_and_distillation; assumption_audit_and_relax | consistency distillation assumes deterministic teacher trajectory | stochastic consistency distillation theory | | dblp |
| dblp:conf/nips/0001LYLWLD0W24 | 2024 | NeurIPS | Motion Consistency Model: Accelerating Video Diffusion with Disentangled Motion-Appearance Distillation | redundancy_compression_and_distillation; decomposition_into_tractable_stages | video diffusion models computationally heavy | motion-appearance disentangled CD for video | | dblp |
| dblp:conf/cvpr/LiuZ0H25 | 2025 | CVPR | Acc3D: Accelerating Single Image to 3D Diffusion Models via Edge Consistency Guided Score Distillation | redundancy_compression_and_distillation; auxiliary_signal_engineering | 3D diffusion models slow at inference | edge-consistency-guided SDS for 3D acceleration | | dblp |
| arxiv:2603.08709v1 | 2026-03 | arXiv | Scale Space Diffusion | formal_reframing_via_equivalence | diffusion timestep semantics not formalized as an information hierarchy | scale-space machinery applied to diffusion sampling | | arxiv |
| arxiv:2604.18471v2 | 2026-04 | arXiv | NI Sampling: Accelerating Discrete Diffusion Sampling by Token Order Optimization | decomposition_into_tractable_stages | discrete diffusion sampling order heuristic | optimal token order for parallel decoding | | arxiv |
| arxiv:2602.05961v1 | 2026-02 | arXiv | Discrete diffusion samplers and bridges: Off-policy algorithms and applications in latent spaces | formal_reframing_via_equivalence; auxiliary_signal_engineering | sampling from unnormalised distributions intractable | off-policy training of amortised diffusion samplers | | arxiv |
| openalex:W4401413870 | 2024-08 | IEEE Trans Med Imaging | Diffusion Modeling With Domain-Conditioned Prior Guidance for Accelerated MRI and qMRI Reconstruction | auxiliary_signal_engineering | iterative diffusion expensive for MRI reconstruction | domain-conditioned prior for MRI acceleration | | openalex |
| openalex:W4401752208 | 2024-05 | Medical Image Analysis | Fast Controllable Diffusion Models for Undersampled MRI Reconstruction | redundancy_compression_and_distillation | controllable diffusion for MRI is slow | accelerated controllable MRI sampling | | openalex |
| arxiv:2603.29239v1 | 2026-03 | arXiv | Diffusion Mental Averages | formal_reframing_via_equivalence | diffusion model concept averaging unclear | sharp model-centric concept averages | | arxiv |
| arxiv:2601.04153v2 | 2026-01 | arXiv | Diffusion-DRF: Free, Rich, and Differentiable Reward for Video Diffusion Fine-Tuning | auxiliary_signal_engineering | scalar reward models limit video alignment | dense differentiable reward without preference data | | arxiv |
| openalex:W4406874777 | 2025-01 | Mech Sys & Signal Proc | Data augmentation of dynamic responses for SHM using DDPM | auxiliary_signal_engineering | structural health monitoring data imbalance | DDPM-based data augmentation for SHM | | openalex |

## Notes

- 7 papers (47%) directly target diffusion sampling acceleration via distillation/compression — the user's regime.
- 1 paper (arxiv:2604.10857) is theoretical (query lower bounds for diffusion sampling) — relevant to user's regime as a complementary axis.
- 5 papers are diffusion application accelerations (IR, MRI, video editing, 3D, video reward) — adjacent but not core.
- 1 paper (Diffusion Mental Averages) is unrelated to acceleration; included because relevance scorer matched on "diffusion".
- Methodology distribution: redundancy_compression × 8 (53%), auxiliary_signal × 5, decomposition × 4, formal_reframing × 3, analytic_refinement × 1, assumption_audit × 1.
- `redundancy_compression_and_distillation` is **saturated** (53% of recent retrieval) — distillation is the dominant move.
- Fresh evidence on consistency-distillation specifics (SCott stochastic CD, Motion CM) — both leave the **finite-NFE boundary regime** open.
