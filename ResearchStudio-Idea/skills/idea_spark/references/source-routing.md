# Source routing — which connector handles which query type

## arXiv — [scripts/search_arxiv.py](../scripts/search_arxiv.py)

- **Strength**: freshest preprints, no auth, full abstracts.
- **Use for**: 6-month freshness scan in map mode; 6-month focused window in collision mode.
- **Auth**: none.
- **Rate**: throttle to 3 req/s. Use the `export.arxiv.org/api/query` endpoint with `sortBy=submittedDate&sortOrder=descending`.

## OpenAlex — [scripts/search_openalex.py](../scripts/search_openalex.py)

- **Strength**: comprehensive academic graph (~250M works), full abstracts, citation counts. Broad coverage including journals + adjacent fields.
- **Use for**: peer-reviewed proceedings + journals (6-24mo) in both map and collision modes.
- **Auth**: `OPENALEX_API_KEY` from env. Without it the polite-pool still works but rate is lower.
- **Rate**: ≥10 req/s with key, ≥1 req/s without. The connector pages with `cursor` for stable pagination.
- **Caveat**: OpenAlex's broad indexing causes some drift (~11% of hits drift to adjacent fields like biology/medicine for ML queries). Combine with Semantic Scholar to compensate.

## Semantic Scholar — [scripts/search_semanticscholar.py](../scripts/search_semanticscholar.py)

- **Strength**: CS-focused academic graph (~200M works), returns **TLDR auto-summary** (Allen-AI 1-sentence) and **`externalIds` block** with DOI + ArXiv ID + DBLP key + MAG ID + PMID — enabling cross-source dedup without title-only matching.
- **Use for**: peer-reviewed proceedings + journals (6-24mo). DBLP keys arrive via `externalIds`, so no standalone DBLP connector is needed.
- **Auth**: `SEMANTICSCHOLAR_API_KEY` strongly recommended. Apply free at https://www.semanticscholar.org/product/api#api-key-form
- **Rate**: 1 req/sec **cumulative across all SS endpoints** (introductory key tier); ~100 req/5min anonymous (bursty, frequent 429s). Connector sleeps 1.1s between calls when authenticated.
- **Caveat**: similar drift to OpenAlex (~73% on-topic in test) — keyword-search-driven, not topic-classified.

## OpenReview — [scripts/search_openreview.py](../scripts/search_openreview.py)

- **Strength**: in-review submissions for ICLR / NeurIPS / ICML — sees concurrent work that hasn't yet hit arXiv or peer-reviewed venues. Forward signal.
- **Use for**: catching very-recent in-review work (0-6 months); concurrent-work check at collision time.
- **Auth**: `OPENREVIEW_USER` + `OPENREVIEW_PASS` from env (the orchestrator at `idea_spark/scripts/run.py` auto-loads `.env`).
- **Rate**: strict — single thread, 1 req/s, retry-after-429 backoff up to 600s. Per-query cost ~7s with `get_notes(limit=500, sort='cdate:desc', mintcdate=since_ms)`.
- **Performance note**: connector uses `get_notes(limit=500, ...)` to fetch only the most recent 500 notes within the date window (~7s/query). The orchestrator gives openreview a 600s timeout as safety margin.

## Source selection rules

```
mode=map:        arXiv(0-6mo) + OpenAlex(6-24mo) + SemanticScholar(6-24mo) + OpenReview(0-6mo)
mode=collision:  arXiv(0-6mo) + OpenAlex(0-6mo) + SemanticScholar(0-6mo) + OpenReview(0-6mo)
```

If any source is unavailable (429 after retries, network down), continue with the others and emit a `lit_source_unavailable: <source>` warning. Do not silently skip.

## Dedup priority order

When the same paper appears in multiple sources after title-normalization:

1. Prefer **Semantic Scholar** record (richest cross-IDs in `externalIds`: DOI + ArXiv + DBLP keys all in one record; also has TLDR + abstract).
2. Then **OpenAlex** (full abstract + citation count, broad coverage).
3. Then **OpenReview** (rich review info but unstable abstract for in-review papers).
4. Then **arXiv** (full abstract, stable id; lowest priority because preprint metadata can drift after publication).
