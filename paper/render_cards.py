#!/usr/bin/env python3
"""Render 13 methodology cards from clustering/cards/methodology_cards.json
into a LaTeX file the technical_report.tex can \\input{}.

Output:
  paper/methodology_cards.tex
"""
import json
import re
from pathlib import Path

ROOT = Path('/home/ntu/zqh/research/novelty_skill')
CARDS = ROOT / 'data' / 'clustering' / 'cards' / 'methodology_cards.json'
OUT = ROOT / 'paper' / 'methodology_cards.tex'


def latex_escape(s: str) -> str:
    """Escape LaTeX-special characters in user text."""
    if s is None:
        return ''
    s = str(s)
    s = s.replace('\\', r'\textbackslash{}')
    repl = [
        ('&',  r'\&'),
        ('%',  r'\%'),
        ('$',  r'\$'),
        ('#',  r'\#'),
        ('_',  r'\_'),
        ('{',  r'\{'),
        ('}',  r'\}'),
        ('~',  r'\textasciitilde{}'),
        ('^',  r'\textasciicircum{}'),
    ]
    for k, v in repl:
        s = s.replace(k, v)
    # Unicode math symbols → ensure they compile under any font
    unicode_repl = [
        ('θ', r'$\theta$'), ('β', r'$\beta$'), ('α', r'$\alpha$'),
        ('γ', r'$\gamma$'), ('δ', r'$\delta$'), ('λ', r'$\lambda$'),
        ('μ', r'$\mu$'),    ('σ', r'$\sigma$'), ('π', r'$\pi$'),
        ('ε', r'$\epsilon$'), ('τ', r'$\tau$'),
        ('ω', r'$\omega$'), ('φ', r'$\phi$'), ('ψ', r'$\psi$'),
        ('ρ', r'$\rho$'),  ('η', r'$\eta$'), ('χ', r'$\chi$'),
        ('ξ', r'$\xi$'),   ('ζ', r'$\zeta$'), ('κ', r'$\kappa$'),
        ('Σ', r'$\Sigma$'), ('Δ', r'$\Delta$'), ('Π', r'$\Pi$'),
        ('Λ', r'$\Lambda$'),('Θ', r'$\Theta$'),
        ('↔', r'$\leftrightarrow$'), ('→', r'$\to$'),
        ('←', r'$\leftarrow$'),
        ('≤', r'$\le$'), ('≥', r'$\ge$'),
        ('∈', r'$\in$'),  ('∉', r'$\notin$'),
        ('∇', r'$\nabla$'),
        ('±', r'$\pm$'),  ('×', r'$\times$'),
        ('₀', r'$_0$'), ('₁', r'$_1$'),
        ('₂', r'$_2$'), ('₃', r'$_3$'),
        ('₄', r'$_4$'), ('₅', r'$_5$'),
        ('₆', r'$_6$'), ('₇', r'$_7$'),
        ('₈', r'$_8$'), ('₉', r'$_9$'),
        ('²', r'$^2$'), ('³', r'$^3$'),
        ('⁴', r'$^4$'),
        ('ℓ', r'$\ell$'),
        ('·', r'$\cdot$'),
        ('…', r'\ldots{}'),
        ('⊃', r'$\supset$'), ('⊂', r'$\subset$'),
        ('⊥', r'$\perp$'),   ('⊤', r'$\top$'),
        ('′', "'"),  ('″', "''"),
        ('ⁿ', r'$^n$'), ('ᵢ', r'$_i$'), ('ʲ', r'$^j$'),
        ('‟', '"'),  ('„', '"'),
        ('⟨', r'$\langle$'), ('⟩', r'$\rangle$'),
        ('∞', r'$\infty$'),  ('∑', r'$\sum$'),  ('∏', r'$\prod$'),
        ('∫', r'$\int$'),    ('∂', r'$\partial$'),
        ('≈', r'$\approx$'), ('≠', r'$\ne$'),
        ('∼', r'$\sim$'),
        ('—', '---'), ('–', '--'),
        ('“', '``'), ('”', "''"),
        ('‘', '`'),  ('’', "'"),
    ]
    for k, v in unicode_repl:
        s = s.replace(k, v)
    return s


def fmt_paper_ids(ids):
    return ', '.join(f'\\texttt{{{latex_escape(p)}}}' for p in ids)


def render_card(name, mid, card, meta):
    out = []
    title_box = (
        f'\\textbf{{{latex_escape(name)}}} '
        f'\\textcolor{{gray}}{{\\small\\texttt{{{latex_escape(mid)}}}}} '
        f'\\hfill confidence: \\textbf{{{card["confidence"]}}}'
    )
    out.append(
        '\\begin{tcolorbox}[colback=bgskill, colframe=cblue!70, '
        'title={' + title_box + '}, breakable, '
        'before skip=4pt, after skip=4pt]'
    )

    # Sample line
    s = meta['sample_sizes']
    cov = meta['meta_coverage']
    out.append(
        f'\\textcolor{{gray}}{{\\small Oral $n={s["oral"]}$ (meta {cov["oral"]}) | '
        f'HC $n={s["hc"]}$ (meta {cov["hc"]}) | '
        f'Reject $n={s["reject"]}$ (meta {cov["reject"]})}}'
    )
    out.append('')
    out.append(
        f'\\textbf{{Sample note.}} \\textit{{{latex_escape(card["sample_note"])}}}'
    )
    out.append('')

    # Step-by-Step
    if card.get('step_by_step'):
        out.append('\\textbf{Step-by-Step:}')
        out.append('\\begin{enumerate}[leftmargin=14pt,topsep=2pt,itemsep=1pt]')
        for step in card['step_by_step']:
            out.append(f'  \\item {latex_escape(step)}')
        out.append('\\end{enumerate}')

    # Success conditions
    out.append('\\textbf{Success conditions} (Oral):')
    out.append('\\begin{itemize}[leftmargin=12pt,topsep=2pt,itemsep=2pt]')
    for c in card['success_conditions']:
        out.append(
            f'  \\item \\textbf{{{latex_escape(c["condition"])}}} '
            f'\\textcolor{{gray}}{{\\footnotesize evidence: {fmt_paper_ids(c["evidence_papers"])}}} '
            f'\\\\ {latex_escape(c["rationale"])}'
        )
    out.append('\\end{itemize}')

    # Failure modes
    out.append('\\textbf{Failure modes} (Reject):')
    out.append('\\begin{itemize}[leftmargin=12pt,topsep=2pt,itemsep=2pt]')
    for m in card['failure_modes']:
        out.append(
            f'  \\item \\textbf{{{latex_escape(m["mode"])}}} '
            f'\\textcolor{{gray}}{{\\footnotesize evidence: {fmt_paper_ids(m["evidence_papers"])}}} '
            f'\\\\ {latex_escape(m["rationale"])}'
        )
    out.append('\\end{itemize}')

    # Gaps
    out.append('\\textbf{Oral vs Reject gap.} ' + latex_escape(card['oral_reject_gap']))
    out.append('')
    out.append('\\textbf{Oral vs HC gap.} ' + latex_escape(card['oral_hc_gap']))
    out.append('')

    # Reviewer expectations
    out.append('\\textbf{Reviewer expectations:}')
    out.append('\\begin{itemize}[leftmargin=12pt,topsep=2pt,itemsep=1pt]')
    for e in card['reviewer_expectations']:
        out.append(
            f'  \\item \\textit{{[{latex_escape(e["evidence_source"])}]}} '
            f'{latex_escape(e["expectation"])}'
        )
    out.append('\\end{itemize}')

    # Cognitive barriers
    out.append('\\textbf{Cognitive barriers:}')
    out.append('\\begin{itemize}[leftmargin=12pt,topsep=2pt,itemsep=1pt]')
    for b in card['cognitive_barriers']:
        out.append(f'  \\item {latex_escape(b)}')
    out.append('\\end{itemize}')

    # Examples
    out.append('\\textbf{Representative examples:}')
    out.append('\\begin{itemize}[leftmargin=12pt,topsep=2pt,itemsep=1pt]')
    for ex in card['representative_examples']['oral']:
        out.append(
            f'  \\item \\textbf{{[Oral]}} \\texttt{{{latex_escape(ex["paper_id"])}}} '
            f'\\textemdash\\ {latex_escape(ex["one_sentence_why"])}'
        )
        if ex.get('lesson'):
            out.append(
                f'  \\\\ \\textcolor{{gray}}{{\\footnotesize \\textit{{Lesson:}} {latex_escape(ex["lesson"])}}}'
            )
    for ex in card['representative_examples']['reject']:
        out.append(
            f'  \\item \\textbf{{[Reject]}} \\texttt{{{latex_escape(ex["paper_id"])}}} '
            f'\\textemdash\\ {latex_escape(ex["one_sentence_why"])}'
        )
        if ex.get('lesson'):
            out.append(
                f'  \\\\ \\textcolor{{gray}}{{\\footnotesize \\textit{{Lesson:}} {latex_escape(ex["lesson"])}}}'
            )
    out.append('\\end{itemize}')

    out.append('\\end{tcolorbox}')
    out.append('')
    return '\n'.join(out)


def main():
    data = json.load(CARDS.open())
    tax = data['taxonomy']
    cards = data['cards']

    parts = [
        '% Auto-generated from clustering/cards/methodology_cards.json by paper/render_cards.py',
        '% Do not edit by hand — re-run render_cards.py.',
        '',
    ]
    for t in tax:
        mid = t['id']
        if mid not in cards:
            parts.append(f'% MISSING CARD: {mid}')
            continue
        c = cards[mid]
        parts.append(render_card(c['methodology_name'], mid, c['card'], c['meta']))

    OUT.write_text('\n'.join(parts))
    print(f'wrote {OUT} ({len(cards)} cards)')


if __name__ == '__main__':
    main()
