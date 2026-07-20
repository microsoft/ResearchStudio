#!/usr/bin/env python3
"""Run exactly one paper-search connector and atomically persist its result."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from _env import load_env_once
    load_env_once()
except Exception:
    pass

from _http_runtime import validate_environment
from search_papers import ALL_SOURCES, _load_source_func


def _error(query, exc: Exception) -> dict:
    return {
        "query": query,
        "type": type(exc).__name__,
        "message": str(exc),
    }


def run_source(
    source: str,
    queries: list[str],
    start_year: int,
    end_year: int,
    max_results: int,
) -> dict:
    """Mirror search_papers' historical per-source, per-query behavior."""
    papers: list[dict] = []
    errors: list[dict] = []
    try:
        # Imports are connector execution too: keep any dependency warnings or
        # incidental prints out of stdout just like the search call itself.
        with contextlib.redirect_stdout(sys.stderr):
            func = _load_source_func(source)
    except Exception as exc:
        print(
            f"[{source}] unavailable (import failed: {exc}); skipping this source.",
            file=sys.stderr,
        )
        errors.append(_error(None, exc))
        return {"source": source, "papers": papers, "errors": errors}

    for query in queries:
        try:
            # A connector must never share stdout with the machine-readable result.
            with contextlib.redirect_stdout(sys.stderr):
                papers.extend(func(query, start_year, end_year, max_results))
        except Exception as exc:
            print(f"[{source}] Error on query {query!r}: {exc}", file=sys.stderr)
            errors.append(_error(query, exc))

    return {"source": source, "papers": papers, "errors": errors}


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=ALL_SOURCES)
    parser.add_argument("--queries-json", required=True)
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--max-results", default=10, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    queries = json.loads(args.queries_json)
    if not isinstance(queries, list) or not queries or not all(
        isinstance(query, str) and query for query in queries
    ):
        parser.error("--queries-json must be a non-empty JSON array of strings")
    if args.max_results < 0:
        parser.error("--max-results must be >= 0")

    validate_environment([args.source])
    payload = run_source(
        args.source, queries, args.start_year, args.end_year, args.max_results
    )
    write_atomic(args.out, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
