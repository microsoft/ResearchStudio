# Novelty Skill — One-Page Doc

## What
**Novelty Skill** is a research ideation assistant that generates **Oral-level machine-learning research ideas** using a structured, data-driven methodology. It is built on an empirical analysis of **1,370 ICLR / NeurIPS / ICML papers (2020–2025)**, from which **18 innovation lenses** were extracted as reusable patterns for producing high-impact contributions.

Core components:
- **18 Innovation Lenses** — recurring structural patterns behind accepted Oral papers (e.g., reframing assumptions, cross-domain transfer, scaling-law inversions, mechanistic reinterpretation, etc.).
- **Three-way Contrastive Methodology** — every idea is stress-tested against three reference classes:
  - *Oral papers* (what high-impact looks like)
  - *High-cited papers* (what's influential but incremental)
  - *Rejected papers* (what looks novel but fails review)
- **Failure-mode warnings** — flags common pitfalls (over-claiming, weak baselines, ill-posed novelty).
- **Framing suggestions** — guidance on how to position, narrate, and title the work for top-tier venues.

## Why
Most "novel" ideas land as incremental or borderline-reject because researchers rely on intuition rather than evidence about what reviewers and program chairs actually elevate.

This skill addresses three concrete pain points:
1. **Ideation is unstructured.** Brainstorming without priors yields ideas clustered around current trends → high rejection risk.
2. **Novelty ≠ acceptance.** Many rejected papers were "novel" but missed the framing, contrast, or evidence pattern of Orals.
3. **Tacit knowledge gap.** The difference between Oral and reject is often craft — knowable from data, but rarely taught.

By grounding ideation in 1,370 papers and contrasting outcomes, it converts tacit reviewer judgment into explicit, actionable lenses.

## How (Usage Flow)
1. **Seed** — provide a topic, problem, or rough direction (e.g., "efficient long-context attention").
2. **Lens application** — the skill walks through relevant lenses from the 18, generating candidate reframings.
3. **Contrastive scoring** — each candidate is compared against Oral / high-cited / rejected exemplars to predict positioning.
4. **Failure-mode review** — flags pitfalls (e.g., "this resembles rejected pattern X — strengthen baseline Y").
5. **Framing output** — returns refined idea(s) with suggested title, abstract framing, and key claims.

Invoke via the Skill tool with `skill: "novelty-skill"` and your research seed as the argument.

## Target Users & Scenarios
| User | Scenario |
|---|---|
| **PhD students / early researchers** | Choosing thesis directions; converting a vague interest into a defensible, top-venue-shaped project. |
| **Industry research scientists** | Pitching ambitious internal projects that need to clear publication bar. |
| **Research leads / advisors** | Sanity-checking student proposals; generating a portfolio of complementary ideas for a lab. |
| **Paper rebuttal / revision** | Diagnosing why a draft reads as "incremental" and reframing toward Oral-style contributions. |
| **Workshop / grant proposals** | Producing differentiated angles when a topic is crowded. |

**Best fit:** ML/AI researchers aiming at ICLR, NeurIPS, ICML (or similar). **Less suited for:** purely engineering work, applied product features, or non-ML domains where the underlying corpus does not generalize.
