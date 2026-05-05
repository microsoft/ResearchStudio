"""Map mode pattern summary.

Why: given the merged top-30 lit hits, we want to know which of the 13 induced
methodologies dominate the recent landscape (saturation flag) and which are
under-used (novelty gap candidate).

Capability profile: [CLASSIFY_FAST] — short context, JSON output.

I/O:
  python -m scripts.pattern_summary --in lit_results.json --top 30 --out pattern.md
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

METHODOLOGIES = [
    ('assumption_audit_and_relax', 'Audit and Relax Implicit Assumption'),
    ('formal_reframing_via_equivalence', 'Reframe via Alternative Formalism'),
    ('shared_latent_alignment', 'Align Heterogeneous Sources in Shared Space'),
    ('invariance_as_architectural_constraint', 'Encode Invariance as Hard Constraint'),
    ('root_cause_surgical_remediation', 'Diagnose Then Surgically Fix'),
    ('evaluation_validity_via_controlled_perturbation', 'Audit Evaluation via Controlled Perturbation'),
    ('analytic_refinement_of_loose_bounds', 'Sharpen a Single Analytic Step'),
    ('redundancy_compression_and_distillation', 'Exploit Redundancy via Compression'),
    ('decomposition_into_tractable_stages', 'Decompose and Recombine'),
    ('auxiliary_signal_engineering', 'Engineer Auxiliary Supervision Signal'),
    ('mechanistic_probing_with_intervention', 'Localize via Causal Probing'),
    ('soft_probabilistic_relaxation', 'Soft Probabilistic Relaxation'),
    ('candidate_aggregation_over_diversity', 'Aggregate Over Diverse Candidates'),
]
NAMES = dict(METHODOLOGIES)

SYSTEM = """You assign each paper to 1-3 of the 13 induced methodologies that the paper EXECUTES (not merely mentions).
Read the paper's abstract; select methodologies based on the rubric below.
Return JSON: {"primary": "<id>", "supporting": ["<id>", ...], "outside_taxonomy": <bool>, "rationale": "<one-sentence>"}.

The 13 methodologies (id — name — short signature):
""" + '\n'.join(f"- {mid} — {name}" for mid, name in METHODOLOGIES) + """

Decision rules: see the parent skill's references/pattern-summary-rubric.md.
If the paper does not clearly fit any methodology, set outside_taxonomy=true."""


def call_llm(system: str, user: str) -> dict:
    cmd = os.environ.get('NOVELTY_LLM_CLASSIFY_FAST_CMD')
    if cmd:
        import subprocess
        full = f'<<SYSTEM>>\n{system}\n<<USER>>\n{user}'
        r = subprocess.run(cmd, input=full, shell=True, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[:200])
        return json.loads(r.stdout)
    raise RuntimeError('NOVELTY_LLM_CLASSIFY_FAST_CMD not set')


def assign(paper: dict) -> dict:
    user = json.dumps({
        'title': paper.get('title', ''),
        'abstract': (paper.get('abstract') or '')[:1500],
    }, ensure_ascii=False)
    return call_llm(SYSTEM, user)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--in', dest='inp', required=True, help='lit_results.json')
    ap.add_argument('--top', type=int, default=30)
    ap.add_argument('--out', required=True, help='pattern.md path')
    ap.add_argument('--out-json', default='', help='optional JSON output for programmatic consumption')
    args = ap.parse_args()

    lit = json.loads(Path(args.inp).read_text())
    papers = (lit if isinstance(lit, list) else lit.get('papers', []))[:args.top]

    assignments = []
    for p in papers:
        try:
            r = assign(p)
            r['paper_id'] = p.get('paper_id') or p.get('source_id')
            assignments.append(r)
        except Exception as e:
            print(f'  assign failed for {p.get("title","")[:40]!r}: {e}', file=sys.stderr)

    cnt = Counter(a['primary'] for a in assignments if a.get('primary'))
    n = max(1, sum(cnt.values()))
    saturated = [mid for mid, c in cnt.items() if c / n >= 0.4]
    under_used = [mid for mid in NAMES if cnt.get(mid, 0) / n <= 0.05]

    md = ['# Pattern summary', '',
          f'**Papers analyzed**: {len(assignments)}', '',
          '## Methodology distribution',
          '| Methodology | n | share |',
          '|---|---|---|']
    for mid, c in cnt.most_common():
        md.append(f'| {NAMES.get(mid, mid)} | {c} | {100*c/n:.1f}% |')
    md += ['', '**Saturated** (>=40%): ' + (', '.join(NAMES[m] for m in saturated) or '_none_'),
           '**Under-used** (<=5%): ' + (', '.join(NAMES[m] for m in under_used) or '_none_'),
           '', '## Recent landscape (auto-narrative will be filled by the orchestrator)']
    Path(args.out).write_text('\n'.join(md))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps({
            'distribution': dict(cnt),
            'saturated': saturated,
            'under_used': under_used,
            'assignments': assignments,
        }, ensure_ascii=False, indent=1))
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
