# Source routing — which connector handles which query type

## DBLP — [scripts/search_dblp.py](../scripts/search_dblp.py)

- **Strength**: AI/ML conference index; canonical metadata (authors, venue, year) for top conferences.
- **Use for**: confirming whether a topic appeared at ICLR / NeurIPS / ICML / ACL / EMNLP / CVPR / ECCV / ICCV / AAAI / IJCAI in the past 24 months; resolving author ambiguity.
- **Skip for**: collision mode (DBLP doesn't expose abstracts on the simple HTTP endpoint).
- **Auth**: none.
- **Rate**: HTTP scraping, throttle to 1 req/s, cache aggressively.

## OpenAlex — [scripts/search_openalex.py](../scripts/search_openalex.py)

- **Strength**: most comprehensive academic graph (~250M works), full abstracts, citation counts, free with API key.
- **Use for**: primary backbone in both map and collision modes.
- **Auth**: `OPENALEX_API_KEY` from env. Without it the polite-pool still works but rate is lower.
- **Rate**: ≥10 req/s with key, ≥1 req/s without. The connector pages with `cursor` for stable pagination.

## OpenReview — [scripts/search_openreview.py](../scripts/search_openreview.py)

- **Strength**: in-review submissions for ICLR / NeurIPS / ICML — sees concurrent work that hasn't yet hit a venue.
- **Use for**: catching very-recent collision (last 4-6 months); concurrent-work check.
- **Auth**: `OPENREVIEW_USER` + `OPENREVIEW_PASS` from env.
- **Rate**: strict — single thread, 1 req/s, retry-after-429 backoff up to 600s.

## arXiv — [scripts/search_arxiv.py](../scripts/search_arxiv.py)

- **Strength**: freshest preprints, no auth, full abstracts.
- **Use for**: 4-month freshness scan in map mode; 6-month focused window in collision mode.
- **Auth**: none.
- **Rate**: throttle to 3 req/s. Use the `export.arxiv.org/api/query` endpoint with `sortBy=submittedDate&sortOrder=descending`.

## Source selection rules

```
mode=map:        DBLP(24mo) + OpenAlex(24mo+4mo) + OpenReview(4mo) + arXiv(24mo+4mo)
mode=collision:  OpenAlex(6mo) + OpenReview(6mo) + arXiv(6mo)
                 (DBLP skipped — no abstracts on the simple endpoint, can't classify)
```

If any source is unavailable (429 after retries, network down), continue with the others and emit a `lit_source_unavailable: <source>` warning. Do not silently skip.

## Dedup priority order

When the same paper appears in multiple sources after title-normalization:

1. Prefer **OpenAlex** record (richer metadata + citations).
2. Then **arXiv** (full abstract, stable id).
3. Then **OpenReview** (rich review info but unstable abstract for in-review papers).
4. Then **DBLP** (last; no abstract).
