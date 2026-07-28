# Phase 0.4 — Relevance partition rubric

You are the **relevance gate** between a wide retrieval net and the expensive
per-paper tagging + deep-read. Retrieval deliberately over-fetches (saturated
connector caps), so a chunk of what came back is off-topic noise or adjacent
context. Your one job: read every retrieved record's **title + abstract** and
sort each into exactly one bucket, so the gap diagnosis and deep-read pool see a
clean corpus.

Use **your own model** — this is open-ended relevance judgment, not mechanical
classification. Do NOT downgrade to a cheap tier.

## Input
`lit_results.json` — the raw deduped retrieval pool (title + abstract per record)
+ the user's original research question/direction.

## The three buckets

- **`core`** — squarely on the research direction: the mechanism/problem the user
  asked about, studied in the user's setting (or a near-neighbor of it). These
  form the gap cluster and are the only papers eligible for the deep-read pool.
- **`adjacent`** — same field, genuinely useful as **background / baseline /
  backbone / benchmark**, but NOT an instance of the mechanism the gap is about.
  Examples for a "memory mechanism in VLA" direction: base policies (OpenVLA, π0,
  Octo), pure spatial/tactile/reasoning VLA work with no memory component,
  world-model or eval-only papers. Kept in the corpus and citeable, but never
  consumes a deep-read slot.
- **`off_topic`** — clearly outside the research direction. **Drop.** The usual
  culprits are **cross-domain false positives** from broad keyword matching
  (e.g. "memory-augmented" matching wireless-network resource allocation,
  recommender systems, fake-news NLP), **pure surveys/reviews**, and papers from
  an unrelated field the connector mis-ranked in.

## The one rule that matters: be conservative on the core/adjacent line

A wrong `off_topic` is a **recall loss the rest of the pipeline can never undo** —
a dropped paper is invisible to Phase 1, deep-read, and collision. So:

- **When unsure between `core` and `adjacent`, choose `core`.** Over-inclusion
  costs one tagging row; under-inclusion silently narrows the gap.
- **Only hard-label `off_topic` when you are confident** the paper is outside the
  direction — a different domain, or pure survey. If a paper is in the right field
  but you're unsure how central it is, it is `adjacent`, not `off_topic`.
- Do not off_topic a paper merely for being older, less novel, or a baseline —
  that is what `adjacent` is for.

## Output

A JSON list, one entry per input record, **every paper_id appearing exactly once**:

```json
[
  {"paper_id": "arxiv:2606.20092v2", "relevance": "core", "reason": "event-driven keyframe memory for long-horizon VLA — exactly the mechanism cluster"},
  {"paper_id": "dblp:...openvla",     "relevance": "adjacent", "reason": "base VLA policy memory work builds on; backbone/baseline, no memory mechanism of its own"},
  {"paper_id": "openalex:W...",       "relevance": "off_topic", "reason": "memory-augmented model for cognitive-radio resource allocation — wrong domain, keyword false positive"}
]
```

Return the output path and a one-line count (`N core / M adjacent / K off_topic`).
