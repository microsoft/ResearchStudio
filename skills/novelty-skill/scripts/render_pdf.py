"""Phase 4.2 — render the Phase 4 expansion JSON into the idea-card PDF.

Why: Phase 4.1 emits a structured `phase4_expansion.json`; this script templates it into
LaTeX via `references/templates/idea_card.tex.j2` and compiles with tectonic. No model
call — pure templating.

The template uses two placeholder forms:
  {{ key }}                 — flat / nested scalar substitution
  {{ key.subkey }}          — nested via dotted path
  {{ __list__key }}         — render a list-of-dict (or list-of-string) as a LaTeX itemize block

Run after Phase 4.1:
  python -m scripts.render_pdf --expansion outputs/phase4/phase4_expansion.json --out outputs/phase4/

Earlier design read a `phase7_ideas.json` list and switched between tiered idea-card templates
by `final_decision.maturity`. That structure was deleted with the Phase 3 escalation state machine —
Phase 4 now produces a single expansion object and a single idea-card template.
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'references' / 'templates'

LATEX_REPLACEMENTS = [
    ('\\', r'\textbackslash{}'),
    ('&', r'\&'), ('%', r'\%'), ('$', r'\$'), ('#', r'\#'), ('_', r'\_'),
    ('{', r'\{'), ('}', r'\}'),
    ('~', r'\textasciitilde{}'), ('^', r'\textasciicircum{}'),
    ('—', '---'), ('–', '--'), ('"', "''"),
    ('θ', r'$\theta$'), ('β', r'$\beta$'), ('α', r'$\alpha$'),
    ('γ', r'$\gamma$'), ('δ', r'$\delta$'), ('λ', r'$\lambda$'),
    ('μ', r'$\mu$'), ('σ', r'$\sigma$'), ('π', r'$\pi$'),
    ('ε', r'$\epsilon$'), ('τ', r'$\tau$'),
    ('Δ', r'$\Delta$'), ('Σ', r'$\Sigma$'), ('∇', r'$\nabla$'),
    ('→', r'$\to$'), ('↔', r'$\leftrightarrow$'),
    ('≤', r'$\le$'), ('≥', r'$\ge$'), ('≈', r'$\approx$'),
    ('×', r'$\times$'), ('±', r'$\pm$'),
    ('∈', r'$\in$'), ('∉', r'$\notin$'),
    ('∥', r'$\|$'), ('‖', r'$\|$'),
]


def latex_escape(s) -> str:
    if s is None: return ''
    s = str(s)
    for k, v in LATEX_REPLACEMENTS:
        s = s.replace(k, v)
    return s


def get_nested(d: dict, dotted_key: str):
    """Resolve `motivation.problem_framing` against a nested dict. Returns None if any segment missing."""
    cur = d
    for seg in dotted_key.split('.'):
        if not isinstance(cur, dict): return None
        cur = cur.get(seg)
        if cur is None: return None
    return cur


def render_list(items, dotted_key: str) -> str:
    """Render a list of dicts (or strings) as a LaTeX itemize block.

    Per-key formatting: for known structured lists we render specific sub-fields in a readable
    layout. For unknown lists we fall back to JSON-dumping each item."""
    if not isinstance(items, list) or len(items) == 0:
        return r'\emph{(none)}'

    lines = [r'\begin{itemize}[leftmargin=*]']

    if dotted_key == 'motivation.why_prior_stopped':
        for it in items:
            pid = latex_escape(it.get('paper_id', ''))
            wd = latex_escape(it.get('what_they_did', ''))
            wdn = latex_escape(it.get('what_they_did_not_do', ''))
            sr = latex_escape(it.get('structural_reason_they_stopped', ''))
            lines.append(rf'  \item \textbf{{{pid}}}: {wd} \\ \emph{{Did not do:}} {wdn} \\ \emph{{Structural reason:}} {sr}')

    elif dotted_key == 'sub_claims':
        for it in items:
            cid = latex_escape(it.get('id', ''))
            stmt = latex_escape(it.get('statement', ''))
            sup = latex_escape(it.get('supports_which_aspect', ''))
            lines.append(rf'  \item \textbf{{{cid}}}: {stmt} \\ \emph{{Supports:}} {sup}')

    elif dotted_key == 'method_flow.steps':
        for it in items:
            sid = latex_escape(it.get('step_id', ''))
            ttl = latex_escape(it.get('title', ''))
            wc = latex_escape(it.get('what_changes', ''))
            wts = latex_escape(it.get('why_this_step', ''))
            lc = latex_escape(it.get('linked_component', ''))
            lf = latex_escape(it.get('linked_falsification', ''))
            lines.append(
                rf'  \item \textbf{{{sid}: {ttl}}} \\ '
                rf'\emph{{What changes:}} {wc} \\ '
                rf'\emph{{Why:}} {wts} \\ '
                rf'\emph{{Linked component:}} {lc} \quad \emph{{Linked falsification:}} {lf}'
            )

    elif dotted_key == 'differentiation_from_lit':
        for it in items:
            pid = latex_escape(it.get('paper_id', ''))
            delta = latex_escape(it.get('delta', ''))
            lines.append(rf'  \item \textbf{{{pid}}}: {delta}')

    elif dotted_key == 'reviewer_concerns_and_responses':
        for it in items:
            atk = latex_escape(it.get('attack', ''))
            sev = latex_escape(it.get('severity', ''))
            resp = latex_escape(it.get('response', ''))
            fc = it.get('fields_changed_to_address', []) or []
            fc_str = latex_escape(', '.join(fc) if fc else '(implicit defense, no field changes)')
            lines.append(
                rf'  \item \textbf{{Severity {sev}.}} \emph{{Attack:}} {atk} \\ '
                rf'\emph{{Response:}} {resp} \\ '
                rf'\emph{{Fields changed:}} {fc_str}'
            )

    elif dotted_key == 'domain_landscape.pattern_distribution':
        for it in items:
            pid = latex_escape(it.get('pattern_id', ''))
            count = latex_escape(it.get('count', ''))
            share = it.get('share', 0)
            share_str = f'{share*100:.0f}\\%' if isinstance(share, (int, float)) else latex_escape(share)
            sat = latex_escape(it.get('saturation', ''))
            lines.append(rf'  \item \texttt{{{pid}}}: {count} papers ({share_str}) \quad saturation: \emph{{{sat}}}')

    elif dotted_key == 'domain_landscape.candidate_uses':
        for it in items:
            pid = latex_escape(it.get('pattern_id', ''))
            role = latex_escape(it.get('role', ''))
            sat = latex_escape(it.get('saturation_in_domain', ''))
            lines.append(rf'  \item \texttt{{{pid}}} ({role}, saturation in this area: \emph{{{sat}}})')

    else:
        for it in items:
            if isinstance(it, dict):
                lines.append(rf'  \item {latex_escape(json.dumps(it, ensure_ascii=False))}')
            else:
                lines.append(rf'  \item {latex_escape(it)}')

    lines.append(r'\end{itemize}')
    return '\n'.join(lines)


PLACEHOLDER_RE = re.compile(r'\{\{\s*(__list__)?([\w\.]+)\s*\}\}')


def render_template(tpl: str, data: dict) -> str:
    def repl(m):
        is_list = bool(m.group(1))
        key = m.group(2)
        if is_list:
            return render_list(get_nested(data, key) or [], key)
        val = get_nested(data, key)
        if val is None:
            return r'\emph{(missing)}'
        if isinstance(val, (dict, list)):
            # No template-side bracket form for these — fall back to JSON.
            return latex_escape(json.dumps(val, ensure_ascii=False))
        return latex_escape(val)
    return PLACEHOLDER_RE.sub(repl, tpl)


def render_markdown(d: dict) -> str:
    """Render the same Phase 4 expansion JSON as a clean human-readable markdown idea card.
    Same content as the PDF; markdown is the AI-context-friendly variant for downstream tooling."""
    parts = []
    parts.append(f'# {d.get("title", "Untitled")}')
    parts.append('')
    parts.append(f'> _{d.get("hook", "")}_')
    parts.append('')

    parts.append('## Abstract')
    parts.append(d.get('abstract_draft', '') or '_(missing)_')
    parts.append('')

    mot = d.get('motivation', {}) or {}
    parts.append('## Motivation')
    parts.append(f'**Problem framing.** {mot.get("problem_framing", "_(missing)_")}')
    parts.append('')
    parts.append(f'**Why now.** {mot.get("why_now", "_(missing)_")}')
    parts.append('')
    parts.append(f'**What changes when the gap closes.** {mot.get("what_changes_when_gap_closes", "_(missing)_")}')
    parts.append('')
    parts.append('**Why prior work stopped:**')
    for it in mot.get('why_prior_stopped', []) or []:
        parts.append(f'- **`{it.get("paper_id","")}`**: {it.get("what_they_did","")}')
        parts.append(f'  - _Did not do_: {it.get("what_they_did_not_do","")}')
        parts.append(f'  - _Structural reason_: {it.get("structural_reason_they_stopped","")}')
    parts.append('')

    parts.append('## Core claim')
    parts.append(f'**{d.get("core_claim","_(missing)_")}**')
    parts.append('')
    parts.append('**Sub-claims:**')
    for it in d.get('sub_claims', []) or []:
        parts.append(f'- **{it.get("id","")}**: {it.get("statement","")}')
        parts.append(f'  - _Supports_: {it.get("supports_which_aspect","")}')
    parts.append('')

    mf = d.get('method_flow', {}) or {}
    parts.append('## Method flow')
    parts.append(f'**High-level pipeline.** {mf.get("high_level_pipeline","_(missing)_")}')
    parts.append('')
    parts.append('**Steps:**')
    for s in mf.get('steps', []) or []:
        parts.append(f'- **{s.get("step_id","")}: {s.get("title","")}**')
        parts.append(f'  - _What changes_: {s.get("what_changes","")}')
        parts.append(f'  - _Why_: {s.get("why_this_step","")}')
        parts.append(f'  - _Linked component_: `{s.get("linked_component","")}` · _Linked falsification_: `{s.get("linked_falsification","")}`')
    parts.append('')
    if mf.get('preservation_argument'):
        parts.append(f'**Preservation argument.** {mf["preservation_argument"]}')
        parts.append('')

    parts.append('## Theorem / algorithm / system design')
    parts.append('```')
    parts.append(d.get('theorem_or_algorithm_or_system_design', '_(missing)_'))
    parts.append('```')
    parts.append('')

    parts.append('## Theoretical leg')
    parts.append(d.get('theoretical_leg', '_(missing)_'))
    parts.append('')
    parts.append('## Engineering leg')
    parts.append(d.get('engineering_leg', '_(missing)_'))
    parts.append('')

    fp = d.get('falsification_prediction', {}) or {}
    parts.append('## Falsification prediction')
    parts.append(f'**What we run.** {fp.get("what_we_run","_(missing)_")}')
    parts.append('')
    parts.append(f'**Success.** {fp.get("success","_(missing)_")}')
    parts.append('')
    parts.append(f'**Failure (a) — numerical.** {fp.get("failure_a_numerical","_(missing)_")}')
    parts.append('')
    parts.append(f'**Failure (b) — mechanistic.** {fp.get("failure_b_mechanistic","_(missing)_")}')
    parts.append('')
    parts.append(f'**Compute budget.** {fp.get("compute_budget","_(missing)_")}')
    parts.append('')
    parts.append(f'**Decision rule.** `{fp.get("decision_rule","_(missing)_")}`')
    parts.append('')

    parts.append('## Mechanism probe')
    parts.append(d.get('mechanism_probe_proposal', '_(missing)_'))
    parts.append('')

    fv = d.get('feasibility_validation', {}) or {}
    parts.append('## Feasibility validation')
    parts.append('| Axis | Verdict | Rationale |')
    parts.append('| --- | --- | --- |')
    for axis in ('compute', 'data', 'theoretical', 'engineering', 'falsification'):
        block = fv.get(axis, {}) or {}
        v = block.get('verdict', '_(missing)_')
        r = (block.get('rationale', '') or '').replace('|', '\\|').replace('\n', ' ')
        parts.append(f'| `{axis}` | **{v}** | {r} |')
    parts.append('')
    parts.append(f'**Overall.** **{fv.get("overall","_(missing)_")}**')
    parts.append('')

    parts.append('## Differentiation from recent literature')
    for it in d.get('differentiation_from_lit', []) or []:
        parts.append(f'- **`{it.get("paper_id","")}`**: {it.get("delta","")}')
    parts.append('')

    parts.append('## Reviewer concerns and responses')
    for it in d.get('reviewer_concerns_and_responses', []) or []:
        sev = it.get('severity', '')
        parts.append(f'- **Severity: {sev}**')
        parts.append(f'  - _Attack_: {it.get("attack","")}')
        parts.append(f'  - _Response_: {it.get("response","")}')
        fc = it.get('fields_changed_to_address', []) or []
        parts.append(f'  - _Fields changed_: {", ".join(fc) if fc else "(implicit defense, no field changes)"}')
    parts.append('')

    landscape = d.get('domain_landscape', {}) or {}
    if landscape:
        parts.append('## Innovation patterns active in this area')
        parts.append(f'_Based on Phase 0 retrieval (n = {landscape.get("n_papers","?")} on-topic papers):_')
        parts.append('')
        parts.append('| Pattern | Count | Share | Saturation |')
        parts.append('| --- | --- | --- | --- |')
        for it in landscape.get('pattern_distribution', []) or []:
            share = it.get('share', 0)
            share_str = f'{share*100:.0f}%' if isinstance(share, (int, float)) else share
            parts.append(f'| `{it.get("pattern_id","")}` | {it.get("count","")} | {share_str} | _{it.get("saturation","")}_ |')
        parts.append('')
        parts.append('**This candidate uses:**')
        for it in landscape.get('candidate_uses', []) or []:
            parts.append(f'- `{it.get("pattern_id","")}` ({it.get("role","")}, saturation in area: _{it.get("saturation_in_domain","")}_)')
        parts.append('')
        parts.append(f'**Position.** {landscape.get("position_note","")}')
        parts.append('')

    return '\n'.join(parts) + '\n'


def render_one(expansion: dict, out_dir: Path) -> Path:
    tpl_path = TEMPLATES / 'idea_card.tex.j2'
    if not tpl_path.exists():
        raise FileNotFoundError(f'Idea-card template missing at {tpl_path}')

    tpl = tpl_path.read_text()
    rendered = render_template(tpl, expansion)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tex_path = out_dir / f'idea_{timestamp}.tex'
    pdf_path = tex_path.with_suffix('.pdf')
    md_path = tex_path.with_suffix('.md')
    tex_path.write_text(rendered)
    md_path.write_text(render_markdown(expansion))
    print(f'  wrote {md_path}')

    if shutil.which('tectonic'):
        try:
            subprocess.run(['tectonic', str(tex_path)], check=True, cwd=out_dir, timeout=180)
            print(f'  wrote {pdf_path}')
        except subprocess.CalledProcessError as e:
            print(f'  tectonic failed for {tex_path.name}: {e}', file=sys.stderr)
            print(f'  .tex saved at {tex_path} for manual inspection', file=sys.stderr)
            return tex_path
    else:
        print(f'  tectonic not found; .tex written at {tex_path} but not compiled', file=sys.stderr)
        return tex_path
    return pdf_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expansion', required=True, help='Phase 4 expansion JSON path')
    ap.add_argument('--out', required=True, help='Output dir')
    args = ap.parse_args()

    expansion = json.loads(Path(args.expansion).read_text())
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    render_one(expansion, out_dir)


if __name__ == '__main__':
    main()
