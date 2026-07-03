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
