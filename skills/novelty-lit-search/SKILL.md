---
name: novelty-lit-search
description: Search recent ML/AI literature across DBLP, OpenAlex, OpenReview, and arXiv, summarize the methodology landscape for a research query, and check whether a specific candidate idea collides with existing prior art (6-month focused window). Use whenever a user (or another skill) asks for "what has been done recently in X", "is my idea novel", "find papers similar to this idea", or needs a literature scan before writing a proposal. Also use as the literature-grounding sub-skill for novelty-skill.
---

# novelty-lit-search

A literature-grounding sub-skill. Two modes:

1. **Map mode (Phase 0 in novelty-skill)** — given a user research question, retrieve 40–100 recent papers (last 24 months broad + last 4 months fresh) across 4 sources, dedupe, and emit a methodology-distribution summary plus saturation flags.
2. **Collision mode (Phase 5 in novelty-skill)** — given a *candidate idea* with a core mechanism and novelty claim, retrieve the most-similar recent papers (last 6 months) and classify each into a 7-class collision taxonomy.

The two modes share the same source connectors and dedup pipeline; only the query construction and post-processing differ.

## When to use this skill

- "Search recent literature on X."
- "Has anyone done Y in the last 6 months?"
- "Map the methodology landscape for this research area."
- "Is this idea novel?" (collision mode)
- As Phase 0 / Phase 5 in `novelty-skill`.

## When NOT to use

- A single-paper deep-dive (use a paper-reading skill).
- Cross-decade survey writing (use a survey skill; this one is scoped to recent literature).
- Code search.

## Inputs

**Map mode**:
```json
{"mode": "map", "query": "<user's research question, free text>", "domain_hints": ["nlp", "rl"], "venue_hints": ["ICLR", "NeurIPS"]}
```

**Collision mode**:
```json
{"mode": "collision",
 "idea": {
   "title": "...",
   "core_mechanism": "...",
   "novelty_claim": "...",
   "domain": "..."
 }}
```

## Outputs

**Map mode**:
- `lit_results.json` — 40–100 deduped papers (title, abstract, year, year_month, citations, source, arxiv_id, openreview_id, paper_url).
- `lit_table.md` — paper-level evidence table consumed by parent skill's Phase 1 lens probing. Columns: `paper_id | year_month | venue | title | methodology tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem`. The `methodology tags` come from the pattern summary pass. The `resolves_problem` column lists `<methodology_id>: <what_resolved>` entries when a paper definitively closes a sub-part of a methodology's load-bearing problem (high bar, ≤ 5% of papers; see Step 4 below).
- `novelty_pattern_summary.md` — which methodologies dominate this query's recent literature; under-used methodologies; saturation flag (≥40% of recent work in one methodology = saturated; ≤5% = under-used).
- `collision_warnings.md` — initial scoop warnings: any paper <2 months old whose abstract overlaps with the user's framing.

**Collision mode**:
- `collision_report.json` — 10 most-similar recent papers, each classified into one of 7 categories (see [references/collision-rubric.md](references/collision-rubric.md)):
  1. exact collision (blocking)
  2. mechanism collision (blocking)
  3. claim collision (blocking)
  4. evaluation collision (blocking)
  5. terminology reframing only (blocking)
  6. weak domain transfer (blocking)
  7. non-blocking related work (pass with explicit delta)
- `recommended_action.md` — for each blocking hit, one of: regenerate, narrow the claim, change mechanism, change evaluation target, reposition as benchmark/analysis paper, abandon.

## Workflow

### Step 1 — Intent extraction ([scripts/intent.py](scripts/intent.py))

Use a [CLASSIFY_FAST]-capable LLM to extract from the input:

- **Map mode**: 3–5 search queries (one broad-domain, one method-signature, one most-similar-problem, optional application angle).
- **Collision mode**: 3–5 signature terms (mechanism + claim + setting), tightly worded for phrase matching.

The prompt template and worked examples are in [references/intent-recognition.md](references/intent-recognition.md).

### Step 2 — Source retrieval (parallel)

Run the four source connectors in parallel. Each returns a list of papers in the same internal format. Source selection logic and rate-limit notes are in [references/source-routing.md](references/source-routing.md).

| Source | Map window | Collision window | Notes |
| --- | --- | --- | --- |
| DBLP | 24mo | — (skip in collision) | AI conferences only, free, no key |
| OpenAlex | 24mo + 4mo | 6mo | Most comprehensive; needs `OPENALEX_API_KEY` for higher rate |
| OpenReview | 4mo | 6mo | Rate-limited; needs `OPENREVIEW_USER` + `OPENREVIEW_PASS` |
| arXiv | 4mo | 6mo | No key; throttle to 3 req/s |

If any source 429s, retry with exponential backoff capped at 600s. If after 3 retries the source is still down, continue with the others and emit a `lit_source_unavailable: <name>` warning.

### Step 3 — Dedup and merge ([scripts/dedup_merge.py](scripts/dedup_merge.py))

Title-normalize (lowercase, strip punct, first 80 chars), deterministic-hash, cross-source dedup. Prefer the OpenAlex record when available (richer metadata + citations); otherwise prefer arXiv (full abstract).

### Step 4 — Map mode: pattern summary + lit_table ([scripts/pattern_summary.py](scripts/pattern_summary.py))

Use [CLASSIFY_FAST] over the merged top-30 abstracts (or all 40-100 for the full lit_table) to:

- For each of the 13 induced methodologies, count papers that primarily execute it (read the rubric in [references/pattern-summary-rubric.md](references/pattern-summary-rubric.md)).
- Per paper, also assign `bottleneck this paper targets` (one short sentence) and `open issue / unresolved gap` (one short sentence — what this paper leaves open for follow-up work).
- Per paper, additionally tag `resolves_problem` (a list, possibly empty) — for each methodology in `primary` or `supporting`, ask whether the paper **definitively closes** a sub-part of that methodology's load-bearing problem. Empty is the common case; expect ≤ 5% of retrieved papers to have a non-empty `resolves_problem`. The high-bar criterion is in [references/pattern-summary-rubric.md](references/pattern-summary-rubric.md) under "`resolves_problem` decision rule". This field feeds the parent skill's Phase 1 persistence check (positive count, not absence inference).
- Emit `dominant: [methodology_id, share]`, `under_used: [methodology_id, share]`, and 3–5 sentences narrating the recent landscape.
- Render `lit_table.md` from the per-paper assignments (one row per paper, columns specified in Outputs above).

### Step 4' — Collision mode: classification ([scripts/novelty_check.py](scripts/novelty_check.py))

Use [CLASSIFY_FAST] + an embedding cosine pre-filter:

1. Embed `core_mechanism + novelty_claim` with [EMBEDDING].
2. Embed every paper's title+abstract.
3. Top-15 by cosine, then BM25 over signature terms for re-ranking.
4. For each top-15 paper, classify into one of the 7 categories using the rubric in [references/collision-rubric.md](references/collision-rubric.md). Each classification cites a quote from the abstract.
5. Emit `recommended_action` per the user-supplied novelty-target (`oral`, `publication`, or `best_paper` — `oral` default). See [references/collision-rubric.md](references/collision-rubric.md) for the action mapping.

## Validation

- Schema-check `lit_results.json` and `collision_report.json` against [references/schemas.md](references/schemas.md) before returning.
- If 0 papers after dedup, emit `lit_search_empty: true` and recommend the user broaden the query.
- If every retrieved paper is non-English or off-topic, fall back to a broader query and re-run once.

## Best-practices compliance

- Scripts handle deterministic API calls; the LLM is used only for intent extraction (Step 1), pattern summary (Step 4), and collision classification (Step 4').
- Every script has a top-of-file docstring explaining what / why / capability profile / rate-limit.
- Rate-limit handling: capped exponential backoff, no silent skips.
- Negative cases: skip paper-reading, code search, or cross-decade surveys (see top of file).

## See also

- **Intent recognition prompts**: see [references/intent-recognition.md](references/intent-recognition.md).
- **Source routing**: see [references/source-routing.md](references/source-routing.md) for which source to use when, plus rate limits.
- **Pattern summary rubric**: see [references/pattern-summary-rubric.md](references/pattern-summary-rubric.md) for assigning methodologies to retrieved papers, including the high-bar `resolves_problem` decision rule that feeds the parent skill's Phase 1 persistence check.
- **Collision rubric**: see [references/collision-rubric.md](references/collision-rubric.md) for the 7-class taxonomy with worked examples and the action mapping.
- **JSON schemas**: see [references/schemas.md](references/schemas.md) for output formats.
- **Connectors**: see the [scripts/](scripts/) directory; every script is a thin wrapper around an API + a small post-process.
