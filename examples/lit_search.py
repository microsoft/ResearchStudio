"""
Phase 1.5 literature search CLI.

Auto-detects your LLM backend from env vars (OPENAI_API_KEY / ANTHROPIC_API_KEY /
GOOGLE_API_KEY / running Ollama) and uses it to classify each paper's primary
innovation lens (C00-C17).

Usage:
    python examples/lit_search.py "GRPO rollout efficiency"
    python examples/lit_search.py "your topic" --backend ollama --top_k 10
    NOVELTY_LLM_BACKEND=none python examples/lit_search.py "your topic"   # skip classify

Date window default: [today - 24 months, today].
"""

import json
import os
import sys
from pathlib import Path

# Make sibling `lit_search/` package importable whether the user runs this from
# the release root or from inside `examples/`.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from lit_search import search_recent_literature, detect_backend  # noqa: E402


def main():
    import argparse
    ap = argparse.ArgumentParser(description="NoveltySkill Phase 1.5 literature search")
    ap.add_argument("query", help="Search query, e.g. 'LLM reasoning token efficiency'")
    ap.add_argument("--months_back", type=int, default=24)
    ap.add_argument("--top_k", type=int, default=15)
    ap.add_argument("--backend", default=None,
                    help="openai / anthropic / gemini / ollama / none. "
                         "Default: auto-detect.")
    ap.add_argument("--no_classify", action="store_true",
                    help="Skip LLM lens classification (just fetch papers).")
    ap.add_argument("--json_out", default=None, help="Write full JSON to this path.")
    args = ap.parse_args()

    backend = args.backend or detect_backend()
    print(f"[lit_search] backend = {backend}", file=sys.stderr)
    if backend == "none" and not args.no_classify:
        print(
            "[lit_search] no LLM backend detected — lens classification will be skipped.\n"
            "            To enable: set one of OPENAI_API_KEY / ANTHROPIC_API_KEY / "
            "GOOGLE_API_KEY, or start Ollama.",
            file=sys.stderr,
        )

    res = search_recent_literature(
        args.query,
        months_back=args.months_back,
        top_k=args.top_k,
        classify_lens=not args.no_classify,
        backend=backend,
    )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print(f"[lit_search] wrote JSON to {args.json_out}", file=sys.stderr)

    # Human-readable summary
    print(f"\nQuery:         {res['query']}")
    print(f"Date window:   {res['date_window'][0]} → {res['date_window'][1]}")
    print(f"Sources:       arxiv={res['source_counts']['arxiv']}, gs={res['source_counts']['gs']}")
    print(f"Papers kept:   {len(res['papers'])}")
    if res.get("warning"):
        print(f"[!] Warning:   {res['warning']}")
    print(f"\nLens distribution: {res['lens_distribution']}")
    print(f"Saturated (>=40%): {res['saturated_lenses']}")
    print(f"Under-used (<=5%): {res['under_used_lenses'][:8]}...")
    print("\nTop papers:")
    for i, p in enumerate(res["papers"][:10], 1):
        lens = p.get("primary_lens") or "—"
        cites = p.get("citations", 0)
        print(f"  {i:2d}. [{lens}] ({cites}c) {p['title'][:100]}")


if __name__ == "__main__":
    main()
