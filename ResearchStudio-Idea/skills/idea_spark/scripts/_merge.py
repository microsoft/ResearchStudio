"""Fair multi-query merge for the Phase 0 / 3.1 connectors.

Every connector runs ONE cap against 4 role-differentiated queries. Merging must be
ROUND-ROBIN, not concatenate-then-truncate: concatenation makes query ORDER the
priority, so the cap is spent entirely on query 1 and every later query — including
the escape-mechanism query, whose whole job is to find solution-named prior work —
contributes nothing while still costing its fetch. Measured at cap 40: 40 kept, all
from query 1, 229 unique in-window papers discarded.

Rationale and the full measurement: references/design-notes.md, "Why the multi-query
merge is round-robin".
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional


def interleave_by_query(per_query: Iterable[list], key_of: Callable[[dict], Optional[str]],
                        max_results: int = 0, queries: Optional[list] = None) -> list:
    """Round-robin across per-query result lists, de-duplicating by `key_of`.

    `per_query` is one already-filtered, already-relevance-ordered list per query
    (in query order). Ties inside a rank go to the earlier query, so with a
    single query the output is byte-identical to the old concatenation path.
    Records whose key is None are dropped, matching the connectors' prior
    behaviour. `max_results <= 0` means no cap.

    When `queries` (the query strings, same order as `per_query`) is supplied,
    every kept record is stamped with `from_query: [<query text>, ...]` — the
    queries that retrieved it, unioned when more than one did. That provenance is
    what lets a later stage grade the QUERIES themselves: join it against the
    Phase 0.4 relevance labels and each query's core/adjacent/off_topic yield
    falls out, turning "how many queries should I write" from a judgement call
    into a per-run measurement.
    """
    queues = [list(q) for q in per_query]
    qtext = list(queries) if queries else []
    seen: dict = {}
    merged: list = []
    rank = 0
    while any(len(q) > rank for q in queues):
        for qi, q in enumerate(queues):
            if len(q) <= rank:
                continue
            h = q[rank]
            key = key_of(h)
            if not key:
                continue
            label = qtext[qi] if qi < len(qtext) else None
            if key in seen:
                # Same paper reachable from another query — credit that query too,
                # rather than attributing the paper to whichever query happened to
                # rank it first.
                if label:
                    prev = seen[key].setdefault('from_query', [])
                    if label not in prev:
                        prev.append(label)
                continue
            if label:
                h = dict(h)
                h['from_query'] = [label]
            seen[key] = h
            merged.append(h)
            if max_results > 0 and len(merged) >= max_results:
                return merged
        rank += 1
    return merged
