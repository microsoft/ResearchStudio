#!/usr/bin/env python3
"""Unified interface to search for academic papers across multiple sources.

Supported sources: arXiv, DBLP, OpenAlex, OpenReview, Semantic Scholar,
Crossref. (Google Scholar exists as an optional connector but is disabled by
default — it needs `scholarly`; see _SOURCE_MODULE.)

Post-processing (default ON, see postprocess.py): cross-source dedup with a
`found_in` provenance column, lexical relevance ranking against the query,
survey tagging (sunk, never dropped), and an opt-in --min-score filter that
prints exactly what it dropped. --raw restores the legacy per-source view.
"""

import argparse
import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from _http_runtime import validate_environment

# Load .env (credentials for openreview etc.) before any source runs, so the aggregator works
# when invoked via bash without a shell-sourced .env. No-op if no .env is found.
try:
    from _env import load_env_once
    load_env_once()
except Exception:
    pass

# Map source name -> module that defines `search_papers_by_<source>`. Modules are imported
# LAZILY (only when a source is actually queried, see _load_source_func) so that a missing
# optional dependency for ONE source — e.g. `scholarly` for google_scholar — no longer crashes
# the whole aggregator at import time. By convention the function name equals the module name.
_SOURCE_MODULE = {
    "arxiv": "search_papers_by_arxiv",
    "dblp": "search_papers_by_dblp",
    # "google_scholar": "search_papers_by_google_scholar",  # needs `scholarly`; disabled by default
    "open_alex": "search_papers_by_open_alex",
    "openreview": "search_papers_by_openreview",
    "semantic_scholar": "search_papers_by_semantic_scholar",
    "crossref": "search_papers_by_crossref",
}
ALL_SOURCES = list(_SOURCE_MODULE.keys())
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SOURCE_WORKER = _SCRIPTS_DIR / "source_worker.py"


def _load_source_func(source: str):
    """Lazily import and return the search function for one source.

    Raises ImportError (with the underlying missing-module message) if the source's
    optional dependency is not installed — callers catch this and skip just that source."""
    module_name = _SOURCE_MODULE[source]
    module = importlib.import_module(module_name)
    return getattr(module, module_name)


def _worker_command(
    source: str,
    queries: list[str],
    start_year: int,
    end_year: int,
    max_results: int,
    out_path: Path,
) -> list[str]:
    return [
        sys.executable,
        str(_SOURCE_WORKER),
        "--source",
        source,
        "--queries-json",
        json.dumps(queries, ensure_ascii=False),
        "--start-year",
        str(start_year),
        "--end-year",
        str(end_year),
        "--max-results",
        str(max_results),
        "--out",
        str(out_path),
    ]


def _start_worker(
    source: str,
    queries: list[str],
    start_year: int,
    end_year: int,
    max_results: int,
    work_dir: Path,
) -> tuple[subprocess.Popen, Path, Path]:
    out_path = work_dir / f"{source}.json"
    log_path = work_dir / f"{source}.log"
    command = _worker_command(
        source, queries, start_year, end_year, max_results, out_path
    )
    with log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(_SCRIPTS_DIR),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=(os.name == "posix"),
        )
    return process, out_path, log_path


def _terminate_workers(processes: list[subprocess.Popen]) -> None:
    alive = [process for process in processes if process.poll() is None]
    for process in alive:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass
    for process in alive:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
    for process in alive:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _collect_worker(
    source: str,
    process: subprocess.Popen,
    out_path: Path,
    log_path: Path,
) -> list[dict]:
    returncode = process.wait()
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log = f"[{source}] could not read worker log: {exc}\n"
    if log:
        sys.stderr.write(log)
        if not log.endswith("\n"):
            sys.stderr.write("\n")

    if returncode != 0:
        print(
            f"[{source}] worker exited with status {returncode}; skipping this source.",
            file=sys.stderr,
        )
        return []
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[{source}] worker produced no result file; skipping this source.", file=sys.stderr)
        return []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[{source}] invalid worker result: {exc}; skipping this source.", file=sys.stderr)
        return []

    if not isinstance(payload, dict) or payload.get("source") != source:
        print(f"[{source}] worker result has the wrong source; skipping it.", file=sys.stderr)
        return []
    papers = payload.get("papers")
    if not isinstance(papers, list) or not all(
        isinstance(paper, dict) for paper in papers
    ):
        print(f"[{source}] worker result has invalid papers; skipping it.", file=sys.stderr)
        return []
    return papers


def _run_source_workers(
    sources: list[str],
    queries: list[str],
    start_year: int,
    end_year: int,
    max_results: int,
    parallel: bool,
) -> dict[str, list[dict]]:
    gathered: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory(prefix="paper_search_workers_") as temp_dir:
        work_dir = Path(temp_dir)
        states: dict[str, tuple[subprocess.Popen, Path, Path]] = {}
        try:
            if parallel:
                for source in sources:
                    try:
                        states[source] = _start_worker(
                            source, queries, start_year, end_year, max_results, work_dir
                        )
                    except OSError as exc:
                        print(f"[{source}] worker could not start: {exc}", file=sys.stderr)
                        gathered[source] = []
                # Every process is already running; collecting in requested order does
                # not serialize the network work and keeps diagnostics deterministic.
                for source in sources:
                    state = states.get(source)
                    if state is not None:
                        gathered[source] = _collect_worker(source, *state)
            else:
                for source in sources:
                    try:
                        state = _start_worker(
                            source, queries, start_year, end_year, max_results, work_dir
                        )
                    except OSError as exc:
                        print(f"[{source}] worker could not start: {exc}", file=sys.stderr)
                        gathered[source] = []
                        continue
                    states[source] = state
                    gathered[source] = _collect_worker(source, *state)
        except BaseException:
            _terminate_workers([state[0] for state in states.values()])
            raise
        finally:
            _terminate_workers([state[0] for state in states.values()])

    return {source: gathered.get(source, []) for source in sources}


def _parse_date(value, field_name: str) -> Optional[date]:
    """Parse a YYYY-MM-DD string (or pass through date/None) for the post-filter."""
    if value is None or isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from e


def _filter_by_date_range(
    papers: list[dict],
    start_date: Optional[date],
    end_date: Optional[date],
) -> list[dict]:
    """Drop papers whose publication_date falls outside [start_date, end_date].

    Papers without a parseable publication_date are KEPT (we can't prove they're
    out of range, and dropping them would silently lose otherwise relevant results)."""
    if not start_date and not end_date:
        return papers
    kept: list[dict] = []
    for p in papers:
        pub_str = p.get("publication_date")
        if not pub_str:
            kept.append(p)
            continue
        try:
            pub = datetime.strptime(pub_str[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            kept.append(p)
            continue
        if start_date and pub < start_date:
            continue
        if end_date and pub > end_date:
            continue
        kept.append(p)
    return kept


def search_papers(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
    sources: Optional[list[str]] = None,
    parallel: bool = True,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, list[dict]]:
    """Search for papers across multiple academic sources.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year (used in source queries).
        end_year: Filter papers published up to this year (used in source queries).
        max_results: Maximum number of papers to return per source.
        sources: List of source names to search. Defaults to all sources.
            Valid values: arxiv, dblp, google_scholar, open_alex, openreview,
            semantic_scholar, crossref.
        parallel: Whether to query sources in parallel (default: True).
        start_date: Optional YYYY-MM-DD lower bound applied as a post-filter to all
            returned papers (finer-grained than start_year). Papers without a
            parseable publication_date are kept.
        end_date: Optional YYYY-MM-DD upper bound applied as a post-filter (inclusive).

    Returns:
        Dictionary mapping source name to list of paper dictionaries.
        Each paper dict contains: title, authors, year, abstract, url,
        venue, citation_count, publication_date, source.
    """
    sources = list(dict.fromkeys(sources or ALL_SOURCES))
    invalid = set(sources) - set(ALL_SOURCES)
    if invalid:
        raise ValueError(f"Unknown sources: {invalid}. Valid: {ALL_SOURCES}")
    # Multi-query union: `query` may be a list (or a single string). Each query
    # runs against every source; per-source results are unioned in query order.
    queries = [q for q in (query if isinstance(query, (list, tuple)) else [query]) if q]
    if not queries:
        raise ValueError("query must be a non-empty string or list of strings")

    start_d = _parse_date(start_date, "start_date")
    end_d = _parse_date(end_date, "end_date")
    if start_d and end_d and start_d > end_d:
        raise ValueError(f"start_date {start_d} is after end_date {end_d}")

    validate_environment(sources)
    results = _run_source_workers(
        sources, queries, start_year, end_year, max_results, parallel
    )

    if start_d or end_d:
        results = {s: _filter_by_date_range(ps, start_d, end_d) for s, ps in results.items()}

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Search papers across multiple academic sources",
    )
    parser.add_argument("--query", default=None, help="Search query")
    parser.add_argument(
        "--queries", default=None,
        help="Pipe-separated multi-query union (e.g. 'a|b|c'); alternative to --query",
    )
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument(
        "--max-papers", type=int, default=10,
        help="Max number of papers per source (default: 10)",
    )
    parser.add_argument(
        "--sources", nargs="+", default=None,
        choices=ALL_SOURCES,
        help=f"Sources to search (default: all). Choices: {', '.join(ALL_SOURCES)}",
    )
    parser.add_argument(
        "--no-parallel", action="store_true",
        help="Disable parallel querying of sources",
    )
    parser.add_argument(
        "--start-date", default=None,
        help="Optional YYYY-MM-DD lower bound; applied as a post-filter (finer than --start-year)",
    )
    parser.add_argument(
        "--end-date", default=None,
        help="Optional YYYY-MM-DD inclusive upper bound; applied as a post-filter",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Legacy per-source view: no dedup, no ranking (full raw output)",
    )
    parser.add_argument(
        "--min-score", type=int, default=None,
        help="OPT-IN noise filter: drop papers with relevance score below N "
             "(the number dropped is always printed; default: keep everything)",
    )
    args = parser.parse_args()
    if not args.query and not args.queries:
        parser.error("one of --query / --queries is required")
    query_list = ([q.strip() for q in args.queries.split("|") if q.strip()]
                  if args.queries else [args.query])

    results = search_papers(
        query=query_list,
        start_year=args.start_year,
        end_year=args.end_year,
        max_results=args.max_papers,
        sources=args.sources,
        parallel=not args.no_parallel,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    if args.raw:
        total = 0
        for source, papers in results.items():
            print(f"\n{'='*60}")
            print(f"  {source}: {len(papers)} papers found")
            print(f"{'='*60}")
            for i, p in enumerate(papers, 1):
                print(f"  [{i}] {p['title']}")
                print(f"      Authors: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}")
                print(f"      Year: {p['year']}  Citations: {p['citation_count']}  Venue: {p['venue']}")
                print(f"      URL: {p['url']}")
                print()
            total += len(papers)
        print(f"\nTotal: {total} papers from {len(results)} sources.")
    else:
        from postprocess import dedup, rank
        per_source = {s_: len(ps) for s_, ps in results.items()}
        merged = dedup(results)
        ranked, n_dropped = rank(merged, query_list, min_score=args.min_score)
        n_dup = sum(per_source.values()) - len(merged)
        print("\nper-source hits: " + ", ".join(f"{k}={v}" for k, v in per_source.items()))
        print(f"unique papers: {len(merged)} ({n_dup} cross-source duplicate records merged)")
        if n_dropped:
            print(f"DROPPED {n_dropped} paper(s) below --min-score {args.min_score} "
                  f"(opt-in filter; omit --min-score for full recall)")
        print(f"{'='*60}")
        for i, p in enumerate(ranked, 1):
            tag = " [survey]" if p.get("is_survey") else ""
            srcs = ",".join(p.get("found_in") or [])
            ids = " ".join(x for x in (f"doi:{p['doi']}" if p.get("doi") else "",
                                       f"arXiv:{p['arxiv_id']}" if p.get("arxiv_id") else "") if x)
            print(f"  [{i}] (score {p.get('relevance_score', 0)}){tag} {p['title']}")
            print(f"      Authors: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}")
            print(f"      Year: {p['year']}  Citations: {p['citation_count']}  Venue: {p['venue']}")
            print(f"      Sources: {srcs}" + (f"  {ids}" if ids else ""))
            print(f"      URL: {p['url']}")
            print()
        print(f"Total: {len(ranked)} unique papers (ranked; surveys sunk to the bottom).")

# Example usage:
# python search_papers.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
# python search_papers.py --query "transformers" --start-year 2023 --end-year 2025 --sources arxiv semantic_scholar
