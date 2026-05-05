# novelty-lit-search

Sub-skill: literature retrieval for the parent `novelty-skill`. Two modes:

1. **Map mode** — given a research question, retrieve ~30-40 deduped recent papers across 4 connectors with role-based time windows; tag each with innovation pattern + bottleneck + open issue. Used as Phase 0 of the parent skill.
2. **Collision mode** — given a candidate idea (with `signature_terms[]`), retrieve papers from a 6-month focused window using mechanism-specific queries; dedup. Used as Phase 3.1 of the parent skill.

**Note**: collision mode used to also run a 7-class LLM classification step. That step was removed because the parent skill's Phase 3.2 audit performs paper-pointed threat search over `lit_table ∪ collision_hits` directly, which subsumed the standalone classification. Collision mode now is **retrieval-only** (no LLM call inside this sub-skill for collision).

## When to use

- As Phase 0 + Phase 3.1 of `novelty-skill`.
- Standalone when a user asks "has anyone done X recently?" or "find recent work in the area of Y".

## When NOT to use

- Single-paper deep dives.
- Cross-decade survey writing.
- Code search.

## Configure

```bash
export OPENALEX_MAILTO=<your-email>     # optional but recommended (polite-pool: 10 req/s vs 1 anonymous)
export OPENALEX_API_KEY=<your-key>      # optional, premium tier
export OPENREVIEW_USER=<your-user>      # required for OpenReview connector
export OPENREVIEW_PASS=<your-pass>
```

`OPENALEX_MAILTO` should be your real email — it's used as `mailto:` in the User-Agent so OpenAlex can identify you for polite-pool rate-limiting (not authentication, just friendly identification per their API guidelines).

For dev workflow, copy the project root's `.env.template` to `.env` and source it (`.env` is gitignored):

```bash
cp ../../.env.template ../../.env  # at project root
$EDITOR ../../.env                 # fill in real values
set -a; source ../../.env; set +a
```

Never commit `.env` or embed keys in tracked files.

For map-mode pattern tagging (Phase 0 step 5), the parent skill's host LLM does the tagging via sentinel handshake; no LLM env needed inside this sub-skill in the standard path. Optional override:

```bash
export NOVELTY_LLM_CLASSIFY_FAST_CMD='your-cli --model <fast-model>'
```

If set, intent extraction + pattern summary run automatically inside the orchestrator instead of emitting sentinels.

Python deps:

```bash
pip install feedparser openreview-py
```

## Connector roles

Each connector has a specific role in retrieval; total target ~30-40 papers per query:

| Connector  | Window  | Role                                | Cap |
|------------|---------|-------------------------------------|-----|
| arxiv      | 0-4 mo  | Recent active preprints             | 10  |
| dblp       | 4-24 mo | Top-venue conference index          | 15  |
| openalex   | 4-24 mo | Peer-reviewed proceedings/journals  | 15  |
| openreview | 0-6 mo  | In-review submissions               | 10  |

Cross-source dedup: dblp > openalex > openreview > arxiv priority. Graceful degradation if any connector unavailable (e.g., no OpenReview creds → ~20-30 papers).

## Anatomy

```
novelty-lit-search/
├── SKILL.md                          ← entry point, 2 modes documented
├── README.md                         ← this file
├── references/
│   ├── intent-recognition.md         ← extract queries (map mode) / signature_terms (collision mode)
│   ├── source-routing.md             ← when to use which source + rate-limit notes
│   ├── pattern-summary-rubric.md     ← assign 1-3 of 13 innovation patterns to retrieved papers
│   ├── collision-rubric.md           ← (legacy) 7-class collision taxonomy; not used in current flow
│   └── schemas.md                    ← JSON output schemas
└── scripts/
    ├── search_dblp.py                ← DBLP scrape connector
    ├── search_openalex.py            ← OpenAlex API connector
    ├── search_openreview.py          ← OpenReview API connector
    ├── search_arxiv.py               ← arXiv API connector
    ├── dedup_merge.py                ← cross-source dedup merge
    ├── pattern_summary.py            ← (optional) auto pattern tagging when CLASSIFY_FAST is set
    └── novelty_check.py              ← (legacy) 7-class collision classifier; not invoked in current flow
```

## Inputs / outputs

### Map mode (Phase 0)

Invoked by the parent's orchestrator:

```bash
python -m scripts.run phase0 --query "<user research question>" --out outputs/<run>/phase0/
```

Produces:
- `arxiv_phase0.json`, `dblp_phase0.json`, `openalex_phase0.json`, `openreview_phase0.json` — per-source raw retrieval
- `lit_results.json` — deduped papers (title, abstract, year, citations, source, ids)
- `lit_table.md` — pattern-tagged paper table (consumed by Phase 1 of parent skill)
- `.lit_grounding_mode` sentinel — `real` if any connector worked; `connector_failure` if none did and no `--allow-webfallback` flag was passed

### Collision mode (Phase 3.1)

Invoked by the parent's orchestrator:

```bash
python -m scripts.run phase3_collision --idea-json <candidate.json> --out outputs/<run>/phase3_collision/
```

Reads `signature_terms[]` from the candidate JSON and uses them as queries against arxiv + openalex + openreview (DBLP skipped — its 4-24 mo window does not overlap the 6-month collision focus).

Produces:
- `arxiv_collision.json`, `openalex_collision.json`, `openreview_collision.json` — per-source raw retrieval
- `collision_hits.json` — deduped retrieval (no classification)

If candidate JSON lacks `signature_terms[]` (legacy schema), the orchestrator emits a `.signature_extraction_pending` sentinel and exits rc=11 — the host LLM produces 3-5 signature terms, edits the candidate JSON, re-invokes.

## Source rate-limit guarantees

- arXiv: 3 req/s (default).
- OpenAlex (with key): 10 req/s; (without key): 1 req/s polite-pool.
- DBLP: 1 req/s.
- OpenReview: 1 req/s, retry-after-429 with exponential backoff up to 600s.

If any source 429s after retries, the connector emits `lit_source_unavailable: <name>` and the orchestrator continues with the others.

## Standalone use

The sub-skill works independently of the parent. To use just for retrieval:

```bash
# Map mode against arbitrary query
python -m scripts.run phase0 --query "<your research question>" --out /tmp/lit/

# Read the output
cat /tmp/lit/lit_table.md
```

The orchestrator will emit `intent_extraction_pending` if no `--queries` was provided and no `NOVELTY_LLM_CLASSIFY_FAST_CMD` is set; in that case re-invoke with `--queries "q1|q2|q3"`. See `references/intent-recognition.md` for the rubric.

## See also

- [`references/source-routing.md`](references/source-routing.md) — when to use which source; rate-limit details.
- [`references/intent-recognition.md`](references/intent-recognition.md) — query extraction (map mode) and signature_terms extraction (collision mode) rubrics.
- Parent skill: [`../novelty-skill/`](../novelty-skill/) — the 5-phase ideation workflow that consumes this sub-skill at Phase 0 + 3.1.
