# Programmatic API

Most use cases are best served by the CLI in `scripts/search_papers.py`. Reach
for the function-call interface only when you need something the CLI doesn't
expose — e.g. consuming the structured dict directly without re-parsing CLI
output.

```bash
cd scripts && python -c "
import json, sys
from search_papers import search_papers
res = search_papers(
    query='<QUERY>',
    start_year=2024,
    end_year=2026,
    max_results=10,
    sources=['semantic_scholar', 'open_alex', 'arxiv', 'openreview'],
    parallel=True,
)
for source, papers in res.items():
    print(f'{source}: {len(papers)} papers')
    for p in papers:
        print(f'  - {p[\"title\"]} ({p[\"year\"]})')
"
```

Return shape: see "Output schema" in `SKILL.md`.

Each selected source runs in its own child process. `parallel=False` preserves
the same isolation while running source workers serially. For a multi-query
call, `max_results` remains the limit for each query, and results are extended
in query order before the existing parent-side date filtering and CLI
post-processing.

HTTP runtime settings can be exported before calling the function:

```bash
export PAPER_SEARCH_TIMEOUT_SECONDS=300
export PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS=15
export PAPER_SEARCH_OPENREVIEW_TIMEOUT_SECONDS=600
export PAPER_SEARCH_MAX_ATTEMPTS=4
```

The source-specific variable overrides only the socket read-idle timeout for
that source. All values must be positive; invalid configuration raises before
any worker starts.
