"""Map mode pattern summary — per-paper ideation pattern tagging.

For each paper in the merged lit_results, classify into 1-3 of the 15 induced
ideation patterns, plus a bottleneck-targeted line and an open-issue line,
then render as `lit_table.md` with the columns the parent skill's run.py
contract specifies.

I/O contract (matches scripts.run phase0 invocation):
  python3 -m scripts.pattern_summary \
    --lit-results lit_results.json \
    --rubric pattern-summary-rubric.md \
    --out-table lit_table.md \
    [--out-json lit_assignments.json] \
    [--top 30]

Capability profile: [CLASSIFY_FAST] — short context, JSON output. Backed by
NOVELTY_LLM_CLASSIFY_FAST_CMD (a CLI that reads <<SYSTEM>>...<<USER>>...
on stdin and returns one JSON object on stdout).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

METHODOLOGIES = [
    ("assumption_audit_and_pivot", "Audit and Pivot an Assumption"),
    ("architectural_operator_substitution", "Substitute the Operator or Representation"),
    ("generative_process_redesign", "Liberate a Fixed Generative Component"),
    ("controlled_diagnostic_design", "Design a Confound-Isolating Diagnostic"),
    ("unify_into_shared_representation", "Unify Heterogeneous Inputs into One Space"),
    ("reframe_as_solvable_object", "Reframe as a Solvable Object"),
    ("self_supervised_signal_engineering", "Manufacture the Supervisory Signal"),
    ("structural_prior_encoding", "Encode Structure by Construction"),
    ("algebraic_equivalence_unification", "Prove Equivalence to Unify"),
    ("heterogeneous_decomposition", "Decompose for Differentiated Treatment"),
    ("decompose_and_delegate", "Decompose and Delegate to Solvers"),
    ("relax_discrete_search_to_continuous", "Relax Discrete Search to Continuous"),
    ("adapt_via_conditioning", "Adapt by Conditioning, Not Retraining"),
    ("characterize_limit_then_surpass", "Characterize a Limit, Then Surpass It"),
    ("targeted_self_supervised_objective", "Design a Property-Targeting Pretext Objective"),
]
NAMES = dict(METHODOLOGIES)

SYSTEM_TEMPLATE = """You classify a single paper into 1-3 of the 15 induced ideation patterns it EXECUTES (not merely mentions), and extract two short fields.

The 15 ideation patterns:
{pattern_list}

Decision rule: see rubric.

Return strict JSON, no preamble, no code fence:
{{
  "primary": "<pattern_id>",
  "supporting": ["<pattern_id>", ...],
  "outside_taxonomy": false,
  "bottleneck_targeted": "<≤25 words: the specific bottleneck this paper attacks>",
  "open_issue": "<≤25 words: an open issue the paper itself does not close, OR \"\" when none stands out>",
  "resolves_problem": "<≤20 words on what part of the ideation pattern's load-bearing problem this paper definitively closes, OR \"\" when this paper only executes the pattern (typical case — leave empty for ≥95% of papers)>"
}}

If no ideation pattern fits cleanly, set "primary": "outside_taxonomy" and outside_taxonomy=true."""


def call_llm(system: str, user: str) -> dict:
    cmd = os.environ.get("NOVELTY_LLM_CLASSIFY_FAST_CMD")
    if not cmd:
        raise RuntimeError("NOVELTY_LLM_CLASSIFY_FAST_CMD not set")
    payload = f"<<SYSTEM>>\n{system}\n<<USER>>\n{user}"
    r = subprocess.run(
        cmd, shell=True, input=payload, capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        raise RuntimeError(f"classify-fast exit {r.returncode}: {r.stderr[:200]}")
    out = r.stdout.strip()
    # Strip code fences if any
    if out.startswith("```"):
        out = out.split("\n", 1)[1] if "\n" in out else out[3:]
        if out.endswith("```"):
            out = out[:-3]
        out = out.strip()
    if not out.startswith("{"):
        i, j = out.find("{"), out.rfind("}")
        if i >= 0 and j > i:
            out = out[i: j + 1]
    return json.loads(out)


def assign_one(paper: dict) -> dict:
    user = json.dumps({
        "title": paper.get("title", ""),
        "abstract": (paper.get("abstract") or "")[:1500],
        "venue": paper.get("venue", ""),
        "year": paper.get("year", ""),
    }, ensure_ascii=False)
    sys_prompt = SYSTEM_TEMPLATE.format(
        pattern_list="\n".join(f"- {mid} — {name}" for mid, name in METHODOLOGIES)
    )
    return call_llm(sys_prompt, user)


def pattern_tags(a: dict) -> str:
    if a.get("outside_taxonomy"):
        return "outside_taxonomy"
    parts = []
    if a.get("primary"):
        parts.append(a["primary"])
    for s in a.get("supporting", []):
        if s not in parts:
            parts.append(s)
    return ", ".join(parts) or "n/a"


def md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def year_month(p: dict) -> str:
    # Prefer the value dedup_merge already derived (from published_iso); then the
    # ISO timestamp directly; then year+month. Keeps lit_table.md month-accurate
    # and consistent with collision_hits.json.
    pre = str(p.get("year_month") or "").strip()
    if pre:
        return pre
    iso = str(p.get("published_iso") or "")
    if len(iso) >= 7 and iso[4] == "-" and iso[:4].isdigit() and iso[5:7].isdigit():
        return iso[:7]
    y = str(p.get("year") or "").strip()
    m = str(p.get("month") or "").strip()
    if m and len(m) == 1:
        m = "0" + m
    return f"{y}-{m}" if y and m else y or ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lit-results", required=True, help="lit_results.json from Phase 0 retrieval")
    ap.add_argument("--rubric", required=False, default="",
                    help="path to pattern-summary-rubric.md (informational; not directly read)")
    ap.add_argument("--out-table", required=True, help="lit_table.md output path")
    ap.add_argument("--out-json", default="", help="optional JSON sidecar with full assignments")
    ap.add_argument("--top", type=int, default=40,
                    help="cap on number of papers to classify (default 40)")
    args = ap.parse_args()

    papers = json.loads(Path(args.lit_results).read_text())
    if isinstance(papers, dict):
        papers = papers.get("papers", [])
    papers = papers[: args.top]

    assignments = []
    for i, p in enumerate(papers):
        try:
            a = assign_one(p)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i + 1}/{len(papers)}] assign failed: {type(e).__name__}: {str(e)[:120]}",
                  file=sys.stderr)
            a = {
                "primary": "n/a (classify_fast_fail)",
                "supporting": [], "outside_taxonomy": False,
                "bottleneck_targeted": "", "open_issue": "", "resolves_problem": "",
            }
        a["paper_id"] = p.get("paper_id") or p.get("source_id") or p.get("id") or ""
        a["title"] = p.get("title", "")
        a["venue"] = p.get("venue", "")
        a["year_month"] = year_month(p)
        a["retrieved_via"] = p.get("source") or p.get("retrieved_via") or ""
        assignments.append(a)

    # Render lit_table.md (parent's expected schema)
    cols = [
        "paper_id", "year_month", "venue", "title",
        "ideation pattern tags", "bottleneck this paper targets",
        "open issue / unresolved gap", "resolves_problem", "retrieved_via",
    ]
    md = []
    md.append("| " + " | ".join(cols) + " |")
    md.append("|" + "|".join(["---"] * len(cols)) + "|")
    for a in assignments:
        row = [
            md_escape(a.get("paper_id", "")),
            md_escape(a.get("year_month", "")),
            md_escape(a.get("venue", "")),
            md_escape(a.get("title", "")),
            md_escape(pattern_tags(a)),
            md_escape(a.get("bottleneck_targeted", "")),
            md_escape(a.get("open_issue", "")),
            md_escape(a.get("resolves_problem", "")),
            md_escape(a.get("retrieved_via", "")),
        ]
        md.append("| " + " | ".join(row) + " |")

    Path(args.out_table).write_text("\n".join(md) + "\n")
    print(f"wrote {args.out_table} ({len(assignments)} rows)")

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(assignments, ensure_ascii=False, indent=1)
        )
        print(f"wrote {args.out_json}")

    # Quick distribution summary on stderr (informational)
    cnt = Counter()
    for a in assignments:
        if a.get("primary") and a["primary"] not in ("outside_taxonomy", "n/a (classify_fast_fail)"):
            cnt[a["primary"]] += 1
        for s in a.get("supporting", []):
            cnt[s] += 1
    if cnt:
        print("ideation pattern distribution:", file=sys.stderr)
        for mid, c in cnt.most_common(5):
            print(f"  {NAMES.get(mid, mid):<48} n={c}", file=sys.stderr)


if __name__ == "__main__":
    main()
