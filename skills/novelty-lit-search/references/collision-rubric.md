# Collision rubric — 7-class prior-art taxonomy

For each paper in the top-10 of a collision-mode retrieval, classify into exactly one of these 7 categories. Each classification must cite at least one quote from the paper's abstract that justifies the call.

| # | Name | Definition | Verdict |
|---|---|---|---|
| 1 | **Exact collision** | Same core idea is already published. Mechanism, claim, and setting all match. | Blocking |
| 2 | **Mechanism collision** | Same mechanism, different task or domain. The technical move is the same. | Blocking |
| 3 | **Claim collision** | Same claim (theorem, identifiability result, bound), different experimental subject. | Blocking |
| 4 | **Evaluation collision** | Same setup or benchmark already used in a closely-similar way. | Blocking |
| 5 | **Terminology reframing only** | Existing idea relabeled with new vocabulary. The substance is unchanged. | Blocking |
| 6 | **Weak domain transfer** | Existing method ported to a new domain with no new mechanism. | Blocking |
| 7 | **Non-blocking related work** | Adjacent, but with a clear, articulable delta the user can name. | Pass |

## Decision algorithm

For each retrieved paper, in order:

1. Read the abstract.
2. Compare against the candidate idea's `core_mechanism` and `novelty_claim`.
3. Pick the strictest applicable category (lower number wins).
4. Quote the abstract span that drove the call.

```json
{
  "paper_id": "<from retrieval>",
  "category": <1-7>,
  "category_name": "<name>",
  "evidence_quote": "<verbatim from abstract>",
  "rationale": "<one sentence on why this category>"
}
```

## Action mapping (collision → recommendation)

The action depends on category and the user's `novelty_target` (`oral` default; `publication` lower bar; `best_paper` higher bar).

| Category | novelty_target=oral | novelty_target=publication | novelty_target=best_paper |
|---|---|---|---|
| 1 exact | regenerate | regenerate | regenerate |
| 2 mechanism | regenerate **or** change mechanism | narrow the claim **or** change mechanism | regenerate |
| 3 claim | narrow the claim | narrow the claim | regenerate |
| 4 evaluation | change evaluation target | reposition as benchmark/analysis | change evaluation target |
| 5 terminology | regenerate | regenerate | regenerate |
| 6 weak transfer | change mechanism | abandon | regenerate |
| 7 non-blocking | pass; cite in `differentiation_from_lit` | pass | pass |

For Best-Paper target, blocking categories trigger `regenerate` more aggressively because Best-Paper-grade work cannot afford even partial overlap.

## Worked examples

**Example A — Mechanism collision**

Candidate idea: "Truncated-step training for diffusion samplers; analytically derive truncation point from Lipschitz argument."

Retrieved paper abstract (verbatim, simplified): "We show the score function has unbounded Lipschitz constant near t=0 and propose to truncate the diffusion timestep window during training, removing the singular region."

Classification: `category=2 mechanism`, `evidence_quote="propose to truncate the diffusion timestep window during training, removing the singular region"`, `rationale="The retrieved paper executes the same mechanism (timestep truncation justified by Lipschitz argument) on the same task (diffusion training)"`. Action under `oral`: regenerate or change mechanism.

**Example B — Non-blocking related work**

Candidate: same as A.

Retrieved paper abstract: "We propose adaptive sampling steps for diffusion at inference time, dropping intermediate steps based on a learned schedule predictor."

Classification: `category=7 non-blocking`, `evidence_quote="adaptive sampling steps ... at inference time"`, `rationale="The retrieved paper modifies inference, not training, and uses a learned predictor rather than analytic Lipschitz argument"`. Action: pass; cite in `differentiation_from_lit`.

## Output schema

```json
{
  "candidate_idea_id": "...",
  "queried_at": "<ISO date>",
  "hits": [
    {"paper_id": "...", "category": <1-7>, "category_name": "...", "evidence_quote": "...", "rationale": "..."},
    ...
  ],
  "blocking_count": <int>,
  "recommended_action": "regenerate | narrow_claim | change_mechanism | change_evaluation | reposition | downgrade_l1 | pass",
  "action_rationale": "<one sentence>"
}
```
