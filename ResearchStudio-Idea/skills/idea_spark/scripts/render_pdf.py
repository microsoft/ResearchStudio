"""Phase 4.2 — render the Phase 4 expansion JSON into the lean idea-card deliverables.

Why: Phase 4.1 emits a rich, structured `phase4_expansion.json` that doubles as the audit
record (motivation / method / claims / falsification / feasibility / literature). The
*deliverable* the user reads, however, is intentionally lean: only **Title + Motivation +
Method**, in two registers × the languages each register ships:

  普通版 (std / plain register)      — 英文 + 中文   → .md, .tex, .pdf each
  详细版 (detail / detailed register) — 英文 only      → .md

So this script emits 7 files (no model call — pure templating):

  idea.std.en.md   idea.std.en.tex   idea.std.en.pdf
  idea.std.zh.md   idea.std.zh.tex   idea.std.zh.pdf
  idea.detail.en.md

Method in every card = module buckets (steps not claimed by any module fall into a leading
"Background" bucket) + per-step detail + the key equations, each as a numbered display
equation on its own line. The std cards read off the `plain_*` fields (language simplified,
mechanism preserved); the pro card reads off `motivation` + `method_flow.steps`.

PDF compilation uses the TeX Live xelatex on PATH (or ~/texlive/2026/bin/x86_64-linux).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BACKGROUND_LABEL = {'en': 'Background', 'zh': '背景'}

# Fixed structural labels are localized per language (the 普通版中文 card should read as Chinese);
# only identifiers / symbols / acronyms stay English, handled in the content fields themselves.
LABELS = {
    'en': {'motivation': 'Motivation', 'method': 'Method', 'method_name': 'Method',
           'why': 'Why', 'equations': 'Key equations', 'label_sep': '.', 'colon': ':'},
    'zh': {'motivation': '研究动机', 'method': '方法', 'method_name': '方法名称',
           'why': '为什么', 'equations': '关键公式', 'label_sep': '：', 'colon': '：'},
}

# ----------------------------------------------------------------------------- LaTeX escaping
LATEX_REPLACEMENTS = [
    ('\\', r'\textbackslash{}'),
    ('&', r'\&'), ('%', r'\%'), ('$', r'\$'), ('#', r'\#'), ('_', r'\_'),
    ('{', r'\{'), ('}', r'\}'),
    ('~', r'\textasciitilde{}'), ('^', r'\textasciicircum{}'),
    ('—', '---'), ('–', '--'), ('"', "''"),
    ('θ', r'$\theta$'), ('β', r'$\beta$'), ('α', r'$\alpha$'),
    ('γ', r'$\gamma$'), ('δ', r'$\delta$'), ('λ', r'$\lambda$'),
    ('μ', r'$\mu$'), ('σ', r'$\sigma$'), ('π', r'$\pi$'),
    ('ε', r'$\epsilon$'), ('τ', r'$\tau$'), ('κ', r'$\kappa$'),
    ('Δ', r'$\Delta$'), ('Σ', r'$\Sigma$'), ('∇', r'$\nabla$'),
    ('→', r'$\to$'), ('↔', r'$\leftrightarrow$'),
    ('≤', r'$\le$'), ('≥', r'$\ge$'), ('≈', r'$\approx$'), ('≠', r'$\ne$'),
    ('×', r'$\times$'), ('±', r'$\pm$'), ('·', r'$\cdot$'),
    ('∈', r'$\in$'), ('∉', r'$\notin$'),
    ('∥', r'$\|$'), ('‖', r'$\|$'),
]


def latex_escape(s) -> str:
    if s is None:
        return ''
    s = str(s)
    for k, v in LATEX_REPLACEMENTS:
        s = s.replace(k, v)
    return s


# ----------------------------------------------------------------------------- inline math
# Prose fields carry inline math in a literal-Unicode + ASCII-subscript convention (e.g. `z_t`,
# `ρ_t`, `Φ_Δt(z_t,c)`, `σ²_uv`, `‖·‖`). Plain `latex_escape` turns `_`→`\_` (killing subscripts)
# and renders unknown Unicode as tofu, so such fragments came out broken. `_render_inline` detects
# the math fragments inside prose and wraps them in proper inline math (`\(...\)` for LaTeX,
# `$...$` for Markdown), converting the Unicode to LaTeX along the way. CJK runs and ordinary
# English words pass through as text, so only the actual math gets math-mode treatment.

_GREEK = {
    'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta', 'ε': r'\epsilon',
    'ϵ': r'\epsilon', 'ζ': r'\zeta', 'η': r'\eta', 'θ': r'\theta', 'ϑ': r'\vartheta',
    'ι': r'\iota', 'κ': r'\kappa', 'λ': r'\lambda', 'μ': r'\mu', 'ν': r'\nu', 'ξ': r'\xi',
    'π': r'\pi', 'ϖ': r'\varpi', 'ρ': r'\rho', 'ϱ': r'\varrho', 'σ': r'\sigma', 'ς': r'\varsigma',
    'τ': r'\tau', 'υ': r'\upsilon', 'φ': r'\phi', 'ϕ': r'\varphi', 'χ': r'\chi', 'ψ': r'\psi',
    'ω': r'\omega', 'Γ': r'\Gamma', 'Δ': r'\Delta', 'Θ': r'\Theta', 'Λ': r'\Lambda',
    'Ξ': r'\Xi', 'Π': r'\Pi', 'Σ': r'\Sigma', 'Υ': r'\Upsilon', 'Φ': r'\Phi', 'Ψ': r'\Psi',
    'Ω': r'\Omega',
}
_SYMS = {
    '∇': r'\nabla', '∂': r'\partial', '∑': r'\sum', '∏': r'\prod', '∫': r'\int',
    '∈': r'\in', '∉': r'\notin', '∋': r'\ni', '⊙': r'\odot', '⊗': r'\otimes', '⊕': r'\oplus',
    '⊤': r'\top', '⊥': r'\bot', '·': r'\cdot', '∙': r'\cdot', '×': r'\times', '÷': r'\div',
    '±': r'\pm', '∓': r'\mp', '→': r'\to', '←': r'\leftarrow', '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow', '⇐': r'\Leftarrow', '⇔': r'\Leftrightarrow', '↦': r'\mapsto',
    '≤': r'\le', '≥': r'\ge', '≈': r'\approx', '≠': r'\ne', '≡': r'\equiv', '≜': r'\triangleq',
    '≅': r'\cong', '∼': r'\sim', '∝': r'\propto', '∞': r'\infty', '∅': r'\emptyset',
    '∪': r'\cup', '∩': r'\cap', '⊂': r'\subset', '⊆': r'\subseteq', '⊃': r'\supset',
    '⊇': r'\supseteq', '∀': r'\forall', '∃': r'\exists', '¬': r'\neg', '∧': r'\wedge',
    '∨': r'\vee', '‖': r'\|', '∥': r'\|', '⟨': r'\langle', '⟩': r'\rangle', '⌊': r'\lfloor',
    '⌋': r'\rfloor', '⌈': r'\lceil', '⌉': r'\rceil', '√': r'\surd', '∘': r'\circ',
    '∖': r'\setminus', '…': r'\dots', '⋯': r'\cdots', '′': r'\prime',
    'ℝ': r'\mathbb{R}', 'ℕ': r'\mathbb{N}', 'ℤ': r'\mathbb{Z}', 'ℚ': r'\mathbb{Q}',
    'ℂ': r'\mathbb{C}', '𝔼': r'\mathbb{E}', 'ℋ': r'\mathcal{H}', 'ℒ': r'\mathcal{L}',
    '𝒩': r'\mathcal{N}', 'ℓ': r'\ell', '−': '-',
}
_MATH_UNICODE = {**_GREEK, **_SYMS}
_SUP = {'⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7',
        '⁸': '8', '⁹': '9', '⁺': '+', '⁻': '-', 'ⁿ': 'n', 'ⁱ': 'i', 'ᵀ': 'T'}
_SUB = {'₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5', '₆': '6', '₇': '7',
        '₈': '8', '₉': '9', '₊': '+', '₋': '-', 'ₜ': 't', 'ᵤ': 'u', 'ᵥ': 'v', 'ᵢ': 'i',
        'ⱼ': 'j', 'ₖ': 'k', 'ₙ': 'n', 'ₐ': 'a', 'ₑ': 'e', 'ₒ': 'o', 'ₓ': 'x', 'ₘ': 'm',
        'ₚ': 'p', 'ₛ': 's'}
_FUNCS = {'tr', 'det', 'exp', 'log', 'ln', 'min', 'max', 'arg', 'argmin', 'argmax', 'sd',
          'var', 'cov', 'kl', 'mmd', 'svd', 'rbf', 'mean', 'median', 'logp', 'softmax',
          'sigmoid', 'relu', 'fps', 'sin', 'cos', 'tan', 'tanh', 'sup', 'inf', 'dim',
          'rank', 'diag', 'vec', 'sign'}
_SIGNAL = set(_MATH_UNICODE) | set(_SUP) | set(_SUB)
_COMBINING = [('̄', r'\bar'), ('̃', r'\tilde'), ('̂', r'\hat'),
              ('́', r'\acute'), ('̀', r'\grave'), ('̇', r'\dot'),
              ('̆', r'\breve'), ('̌', r'\check'), ('⃗', r'\vec')]

_CJK_RANGES = ((0x3000, 0x303F), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
               (0xFE30, 0xFE4F), (0xFF00, 0xFFEF))


def _is_cjk(ch) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CJK_RANGES)


def _collapse_scripts(t: str) -> str:
    """Fold runs of Unicode super/subscript glyphs into a single ^{...}/_{...} group."""
    out, i, n = [], 0, len(t)
    while i < n:
        table = _SUP if t[i] in _SUP else (_SUB if t[i] in _SUB else None)
        if table is None:
            out.append(t[i]); i += 1; continue
        buf = []
        while i < n and t[i] in table:
            buf.append(table[t[i]]); i += 1
        out.append(('^{' if table is _SUP else '_{') + ''.join(buf) + '}')
    return ''.join(out)


def _escape_unbalanced_braces(t: str) -> str:
    """Hide unmatched literal braces behind sentinels so they survive as escaped text. Prose set
    notation like {text, type, source_span} can get split across the text/math boundary, leaving a
    lone `}` inside a math run; balanced pairs (real grouping, e.g. {z_t}) are left intact."""
    out, stack = list(t), []
    for i, ch in enumerate(t):
        if ch == '{':
            stack.append(i)
        elif ch == '}':
            if stack:
                stack.pop()
            else:
                out[i] = '\x02'
    for i in stack:
        out[i] = '\x01'
    return ''.join(out)


def _conv_math(run: str) -> str:
    """Convert one math fragment from the Unicode/ASCII convention to LaTeX (no delimiters)."""
    t = _escape_unbalanced_braces(unicodedata.normalize('NFD', run))
    for mark, macro in _COMBINING:
        t = re.sub(r'(.)' + mark, lambda m, _mc=macro: _mc + '{' + m.group(1) + '}', t)
    t = _collapse_scripts(t)
    # A snake_case identifier (2+ underscores, e.g. source_paper_id) is code, not nested math
    # subscripts — render it upright with literal underscores so it neither crashes xelatex with a
    # double subscript nor reads as a tower of subscripts. The \x00 sentinel hides those literal
    # underscores from the single-subscript pass that follows, then becomes \_ at the end.
    t = re.sub(r'[A-Za-z0-9]+(?:_[A-Za-z0-9]+){2,}',
               lambda m: r'\mathit{' + m.group(0).replace('_', '\x00') + '}', t)
    t = re.sub(r'_(?!\{)([A-Za-z0-9]+)', r'_{\1}', t)   # z_ab -> z_{ab}, leave z_{..} alone
    t = re.sub(r'\^(?!\{)([A-Za-z0-9]+)', r'^{\1}', t)
    for k, v in _MATH_UNICODE.items():
        t = t.replace(k, v + ' ')                        # trailing space terminates control words
    t = t.replace('%', r'\%').replace('#', r'\#').replace('&', r'\&')
    return t.replace('\x00', r'\_').replace('\x01', r'\{').replace('\x02', r'\}')


def _classify(tok: str) -> str:
    if any(ch in _SIGNAL for ch in tok):
        return 'STRONG'
    if any(unicodedata.combining(ch) for ch in unicodedata.normalize('NFD', tok)):
        return 'STRONG'
    if '^' in tok or (tok.startswith('{') and tok.endswith('}')):
        return 'STRONG'
    if re.search(r'[A-Za-z0-9\)\]\}]_', tok):            # underscore used as subscript
        return 'STRONG'
    if tok.lower().strip("()[],.") in _FUNCS:
        return 'CONNISH'
    if re.fullmatch(r"[-+*/=(),.<>|']+", tok):
        return 'CONNISH'
    if re.fullmatch(r'\d+(?:[./]\d+)*', tok):
        return 'CONNISH'
    if re.fullmatch(r'[A-Za-z]', tok) or re.fullmatch(r'[A-Za-z]\d+', tok):
        return 'CONNISH'                                  # single-letter var, or m0/x1
    return 'WORD'


def _emit_text(s, mode: str) -> str:
    return latex_escape(s) if mode == 'tex' else str(s)


def _wrap_math(inner: str, mode: str) -> str:
    return (r'\(' + inner + r'\)') if mode == 'tex' else ('$' + inner + '$')


def _flush_run(run: list, mode: str) -> str:
    if not run:
        return ''
    if not any(k == 'STRONG' for k, _ in run):
        return ''.join(_emit_text(t, mode) for _, t in run)
    items, lead, trail = list(run), [], []
    while items and items[0][0] == 'SPACE':
        lead.append(items.pop(0)[1])
    while items and items[-1][0] == 'SPACE':
        trail.insert(0, items.pop()[1])
    body = _wrap_math(_conv_math(''.join(t for _, t in items)), mode)
    return (''.join(_emit_text(x, mode) for x in lead) + body
            + ''.join(_emit_text(x, mode) for x in trail))


def _render_latin(text: str, mode: str) -> str:
    out, run = [], []
    for tok in re.split(r'(\s+|;)', text):
        if tok == '':
            continue
        if tok == ';':
            out.append(_flush_run(run, mode)); run = []
            out.append(_emit_text(';', mode))
            if mode == 'tex':
                out.append(r'\allowbreak{}')             # let a long formula chain break at ';'
        elif tok.isspace():
            run.append(('SPACE', tok))
        elif _classify(tok) == 'WORD':
            out.append(_flush_run(run, mode)); run = []
            out.append(_emit_text(tok, mode))
        else:
            run.append((_classify(tok), tok))
    out.append(_flush_run(run, mode))
    return ''.join(out)


def _render_inline(s, mode: str = 'tex') -> str:
    """Render a prose string that may embed inline math. `mode` is 'tex' or 'md'."""
    if s is None:
        return ''
    s = str(s)
    segs, buf, cur = [], [], None
    for ch in s:
        c = _is_cjk(ch)
        if buf and c != cur:
            segs.append((cur, ''.join(buf))); buf = []
        cur = c; buf.append(ch)
    if buf:
        segs.append((cur, ''.join(buf)))
    return ''.join(_emit_text(t, mode) if is_cjk else _render_latin(t, mode)
                   for is_cjk, t in segs)


# ----------------------------------------------------------------------------- shared shaping
def _is_background_header(h: str) -> bool:
    """True for the scaffolding module — the unchanged-setup part of the method. Author modules
    name it 'Background' / '背景脚手架'; we match loosely so the renderer can float it to the front."""
    h = (h or '').lower()
    return 'background' in h or 'scaffold' in h or '背景' in h or '脚手架' in h


def _bucket(steps: list, modules: list, lang: str) -> list:
    """Group `steps` under the declared `modules`; un-claimed steps fall into a leading
    Background bucket so the reader sees unchanged scaffolding apart from the contributions.
    Background/scaffolding modules are floated to the front of the method (before the contribution
    modules), so the reader meets the fixed setup first. Steps are renumbered continuously in render
    order by the renderer. Falls back to a single flat bucket when no modules are declared."""
    by_id = {s.get('step_id'): s for s in steps}
    if not modules:
        return [{'header': '', 'purpose': '', 'steps': steps}]
    assigned: set = set()
    module_buckets = []
    for m in modules:
        ids = m.get('step_ids', []) or []
        assigned.update(ids)
        module_buckets.append({
            'header': m.get('module_id', ''),
            'purpose': m.get('purpose_oneline', ''),
            'steps': [by_id[i] for i in ids if i in by_id],
        })
    glue = [s for s in steps if s.get('step_id') not in assigned]
    bg_modules = [b for b in module_buckets if _is_background_header(b['header'])]
    contrib_modules = [b for b in module_buckets if not _is_background_header(b['header'])]
    buckets = []
    if glue:
        buckets.append({'header': BACKGROUND_LABEL[lang], 'purpose': '', 'steps': glue})
    buckets.extend(bg_modules)
    buckets.extend(contrib_modules)
    return buckets


def _card_inputs(d: dict, register: str, lang: str) -> dict:
    """Pick the title / motivation / steps / modules source for a (register, lang) card."""
    if register == 'std':
        return {
            'title': d.get('title_zh' if lang == 'zh' else 'title', ''),
            'steps': d.get(f'plain_method_steps_{lang}') or [],
            'modules': d.get(f'plain_method_modules_{lang}') or [],
        }
    # detail register ships English only and reads the professional fields verbatim
    return {
        'title': d.get('title', ''),
        'steps': (d.get('method_flow', {}) or {}).get('steps', []) or [],
        'modules': d.get('plain_method_modules_en') or [],
    }


def _step_view(s: dict, register: str) -> tuple:
    """(head, what, why) for one step, register-aware. std steps carry no title."""
    if register == 'std':
        return ('', s.get('what_to_do', ''), s.get('why_this_makes_sense', ''))
    return (s.get('title', ''), s.get('what_changes', ''), s.get('why_this_step', ''))


def _equations_by_step(d: dict) -> tuple:
    """Group key_equations under the method step each one explains (`linked_step_id`), so the
    formula renders inside its step rather than in a detached trailing list. Equations with no
    (or an unknown) link fall back to a trailing block so nothing is silently dropped."""
    eqs = d.get('key_equations') or []
    by_step: dict = {}
    linked = []
    for e in eqs:
        sid = e.get('linked_step_id')
        if sid:
            by_step.setdefault(sid, []).append(e)
            linked.append(id(e))
    leftover = [e for e in eqs if id(e) not in linked]
    return by_step, leftover


def _eq_desc(e: dict, lang: str) -> str:
    """Equation caption in the card's language. zh is an idiomatic rendering (description_zh),
    not a literal translation of the English; fall back to English if absent."""
    if lang == 'zh':
        return e.get('description_zh') or e.get('description', '')
    return e.get('description', '')


def _step_brief(s: dict, lang: str) -> str:
    """A short locator label for a step — its first clause, capped — so a cross-reference can read
    '第5步（用 LoRA 微调生成器）' instead of a bare number the reader must hunt for across modules."""
    txt = (s.get('what_to_do') or s.get('title') or '').strip()
    if not txt:
        return ''
    head = re.split(r'[，。；：（、,.;:(]', txt, 1)[0].strip()
    limit = 14 if lang == 'zh' else 36
    if len(head) > limit:
        cut = head[:limit]
        sp = cut.rfind(' ')
        if sp >= limit // 2:  # back off to a word boundary when one is reasonably close
            cut = cut[:sp]
        head = cut.rstrip() + '…'
    return head


def _step_number_map(buckets: list, lang: str) -> dict:
    """Map each step_id to (visible_number, short_label) in render order. The std card hides the internal
    S-ids and renumbers steps, so prose that cross-references a step by id (e.g. 'S7') would otherwise
    point at a number the reader never sees; this lets us rewrite the id to the visible number plus a
    one-clause hint so the reader doesn't have to count across module headers to locate it."""
    m, n = {}, 0
    for b in buckets:
        for s in b['steps']:
            n += 1
            sid = s.get('step_id')
            if sid:
                m[sid] = (n, _step_brief(s, lang))
    return m


def _deref_step_ids(text, idmap: dict, lang: str):
    """Rewrite internal step ids (S3, S7, …) in prose to the visible number + hint
    ('第N步（…）' / 'step N (…)'). No-op when idmap is empty (the pro card surfaces the S-ids verbatim)."""
    if not text or not idmap:
        return text

    def repl(mm):
        ref = idmap.get(mm.group(0))
        if not ref:
            return mm.group(0)
        n, brief = ref
        if lang == 'zh':
            return f'第{n}步（{brief}）' if brief else f'第{n}步'
        return f'step {n} ({brief})' if brief else f'step {n}'

    return re.sub(r'(?<![A-Za-z0-9])S\d+(?![A-Za-z0-9])', repl, str(text))


# ----------------------------------------------------------------------------- markdown
def _md_motivation(d: dict, register: str, lang: str) -> list:
    if register == 'std':
        body = d.get(f'plain_motivation_{lang}', '') or ''
        return [_render_inline(body, 'md') if body else '_(missing)_', '']
    mot = d.get('motivation', {}) or {}
    mi = lambda k: _render_inline(mot.get(k, ''), 'md') or '_(missing)_'
    out = [
        f'**Problem framing.** {mi("problem_framing")}', '',
        f'**Why now.** {mi("why_now")}', '',
    ]
    wps = mot.get('why_prior_stopped', []) or []
    if wps:
        out.append('**Why prior work stopped.**')
        for it in wps:
            pid = it.get('paper_id', '')
            vy = it.get('venue_year', '')
            head = f'`{pid}`' + (f' ({vy})' if vy else '')
            out.append(f'- {head}: {_render_inline(it.get("what_they_did", ""), "md")}')
            out.append(f'  - _Did not do_: {_render_inline(it.get("what_they_did_not_do", ""), "md")}')
            out.append(f'  - _Structural reason_: {_render_inline(it.get("structural_reason_they_stopped", ""), "md")}')
        out.append('')
    out.append(f'**What changes when the gap closes.** {mi("what_changes_when_gap_closes")}')
    out.append('')
    return out


def render_card_md(d: dict, register: str, lang: str) -> str:
    src = _card_inputs(d, register, lang)
    lab = LABELS[lang]
    eq_by_step, leftover_eqs = _equations_by_step(d)
    tag = 0
    method_name = d.get('method_name', '')
    parts = [f'# {src["title"] or "Untitled"}', '']
    if method_name:
        parts += [f'**{lab["method_name"]}{lab["label_sep"]}** {method_name}', '']

    parts.append(f'## {lab["motivation"]}')
    parts += _md_motivation(d, register, lang)

    parts.append(f'## {lab["method"]}')
    if register == 'detail':
        hp = (d.get('method_flow', {}) or {}).get('high_level_pipeline', '')
        if hp:
            parts += [f'**Pipeline.** {_render_inline(hp, "md")}', '']
    buckets = _bucket(src['steps'], src['modules'], lang)
    idmap = _step_number_map(buckets, lang) if register == 'std' else {}
    n = 0
    for b in buckets:
        if b['header']:
            parts.append(f'### {b["header"]}')
            if b['purpose']:
                parts.append(f'*{_render_inline(b["purpose"], "md")}*')
            parts.append('')
        for s in b['steps']:
            n += 1
            head, what, why = _step_view(s, register)
            sid = s.get('step_id', '')
            what = _deref_step_ids(what, idmap, lang)
            if head:
                parts.append(f'{n}. **{head}** (`{sid}`)')
                parts.append(f'   - {_render_inline(what, "md")}')
            else:
                parts.append(f'{n}. {_render_inline(what, "md")}')
            for e in eq_by_step.get(sid, []):
                tag += 1
                desc = _deref_step_ids(_eq_desc(e, lang), idmap, lang)
                body = (e.get('latex', '') or '').strip()
                parts.append('')
                if desc:
                    parts.append(f'*{_render_inline(desc, "md")}*')
                parts.append(f'$$ {body} \\tag{{{tag}}} $$')
                parts.append('')
            if why:
                parts.append(f'   - _{lab["why"]}{lab["colon"]}_ {_render_inline(_deref_step_ids(why, idmap, lang), "md")}')
        parts.append('')

    if leftover_eqs:
        parts.append(f'### {lab["equations"]}')
        for e in leftover_eqs:
            tag += 1
            desc = _deref_step_ids(_eq_desc(e, lang), idmap, lang)
            body = (e.get('latex', '') or '').strip()
            if desc:
                parts.append(f'*{_render_inline(desc, "md")}*')
            parts.append(f'$$ {body} \\tag{{{tag}}} $$')
            parts.append('')

    return '\n'.join(parts) + '\n'


# ----------------------------------------------------------------------------- LaTeX
LATEX_PREAMBLE = r"""\documentclass[10pt,a4paper]{article}
\usepackage[margin=1.55cm]{geometry}
\usepackage{xcolor}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{fontspec}
\usepackage[CJKmath=true]{xeCJK}
% CJK main font is resolved at COMPILE time on the actual machine, not baked in at
% generation time, so a .tex generated on one OS still renders on another (the older
% Python-side probe hardcoded one OS's font name into the file and broke when moved).
% Walk a cross-platform priority list and use the first font that exists; AutoFakeBold
% + AutoFakeSlant give bold/italic CJK even on faces that ship no bold/italic cut.
\newcommand{\setCJKto}[1]{\setCJKmainfont{#1}[AutoFakeBold=true,AutoFakeSlant=0.2]}
\IfFontExistsTF{Noto Sans CJK SC}{\setCJKto{Noto Sans CJK SC}}{%        % Linux (fonts-noto-cjk); cross-platform if installed
 \IfFontExistsTF{Source Han Sans SC}{\setCJKto{Source Han Sans SC}}{%   % Adobe 思源黑体; cross-platform
  \IfFontExistsTF{PingFang SC}{\setCJKto{PingFang SC}}{%               % macOS 10.11+
   \IfFontExistsTF{Hiragino Sans GB}{\setCJKto{Hiragino Sans GB}}{%    % older macOS
    \IfFontExistsTF{Microsoft YaHei}{\setCJKto{Microsoft YaHei}}{%     % Windows
     \IfFontExistsTF{WenQuanYi Micro Hei}{\setCJKto{WenQuanYi Micro Hei}}{% % older Linux
      \setCJKto{Songti SC}}}}}}}                                       % macOS bottom fallback
\definecolor{cblue}{HTML}{4C72B0}
\setlength{\parskip}{3pt}\setlength{\parindent}{0pt}
\setlist[enumerate]{topsep=2pt,itemsep=2pt,parsep=1pt,partopsep=0pt}
\setlist[itemize]{topsep=2pt,itemsep=2pt,parsep=1pt,partopsep=0pt}
% Let prose-embedded inline math break across lines and absorb small overflows, so simple
% formulas inserted mid-sentence stop running past the right margin.
\tolerance=1200
\emergencystretch=2.5em
\relpenalty=20
\binoppenalty=40
\hfuzz=1pt
\begin{document}
"""


# When True, every equation is rendered as raw escaped text instead of typeset math.
# render_one flips this on for a single whole-document retry if the first compile fails,
# so an equation that is brace-balanced but otherwise broken (e.g. an undefined macro,
# which _math_is_safe cannot detect) still yields a PDF instead of nothing.
_FORCE_DEGRADE_MATH = False


def _math_is_safe(body: str) -> bool:
    """Cheap structural sanity check on an LLM-supplied equation body. The compile uses
    -halt-on-error, so a SINGLE unbalanced brace or stray `$` aborts the whole card PDF,
    not just one equation. Reject the common LLM glitches (brace / `$` / environment
    imbalance, math-mode/document breakout, empty) so the caller can degrade just that
    equation. Does NOT catch balanced-but-broken bodies (undefined macro, bad arg count);
    the whole-document retry in render_one is the backstop for those."""
    if not body or not body.strip():
        return False
    depth = dollars = 0
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == '\\':            # skip the escaped next char (\{ \} \$ \\ ...)
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth < 0:
                return False
        elif c == '$':
            dollars += 1
        i += 1
    if depth != 0 or dollars % 2 != 0:
        return False
    if body.count(r'\begin') != body.count(r'\end'):
        return False
    if r'\end{document}' in body or r'\documentclass' in body:
        return False
    return True


def _degraded_equation(body: str, tag: int) -> list:
    """Render an unsafe equation as escaped monospace text instead of typeset math, so one
    malformed formula degrades to a readable raw-LaTeX line rather than taking down the
    whole PDF. Marked so a reader can spot that it needs a manual fix."""
    shown = latex_escape(body.strip()) if body and body.strip() else '(empty)'
    return [rf'\par\noindent{{\small\ttfamily [eq~{tag}, raw LaTeX, not typeset] {shown}}}']


def _tex_equation(body: str, tag: int) -> list:
    # Degrade a malformed (or force-degraded) equation to escaped text so it cannot abort
    # the build; otherwise typeset normally.
    if _FORCE_DEGRADE_MATH or not _math_is_safe(body):
        return _degraded_equation(body, tag)
    # Scale a long single-line equation down to the text width only when it would overflow (\ifdim guard),
    # so wide multi-part formulas stop running past the right margin in the PDF while short ones keep
    # their natural size. Avoids fragile auto-line-breaking packages on arbitrary latex bodies.
    return [
        r'\begin{equation}',
        rf'\resizebox{{\ifdim\width>\linewidth \linewidth\else\width\fi}}{{!}}{{$\displaystyle {body}$}} \tag{{{tag}}}',
        r'\end{equation}',
    ]


def _tex_motivation(d: dict, register: str, lang: str) -> list:
    if register == 'std':
        return [_render_inline(d.get(f'plain_motivation_{lang}', '') or '', 'tex')]
    mot = d.get('motivation', {}) or {}
    ri = lambda k: _render_inline(mot.get(k, ''), 'tex')
    out = [
        rf'\textbf{{Problem framing.}} {ri("problem_framing")}', '',
        rf'\textbf{{Why now.}} {ri("why_now")}', '',
    ]
    wps = mot.get('why_prior_stopped', []) or []
    if wps:
        out.append(r'\textbf{Why prior work stopped.}')
        out.append(r'\begin{itemize}[leftmargin=*]')
        for it in wps:
            pid = latex_escape(it.get('paper_id', ''))
            vy = latex_escape(it.get('venue_year', ''))
            head = rf'\texttt{{{pid}}}' + (rf' ({vy})' if vy else '')
            out.append(
                rf'  \item {head}: {_render_inline(it.get("what_they_did", ""), "tex")} \\ '
                rf'\emph{{Did not do:}} {_render_inline(it.get("what_they_did_not_do", ""), "tex")} \\ '
                rf'\emph{{Structural reason:}} {_render_inline(it.get("structural_reason_they_stopped", ""), "tex")}'
            )
        out.append(r'\end{itemize}')
    out.append(rf'\textbf{{What changes when the gap closes.}} {_render_inline(mot.get("what_changes_when_gap_closes", ""), "tex")}')
    return out


def render_card_latex(d: dict, register: str, lang: str) -> str:
    src = _card_inputs(d, register, lang)
    lab = LABELS[lang]
    eq_by_step, leftover_eqs = _equations_by_step(d)
    tag = 0
    method_name = d.get('method_name', '')
    out = [LATEX_PREAMBLE]
    out.append(rf'\section*{{{latex_escape(src["title"] or "Untitled")}}}')
    if method_name:
        out.append(rf'\textbf{{{latex_escape(lab["method_name"] + lab["label_sep"])}}} {latex_escape(method_name)}')

    out.append(rf'\section*{{{latex_escape(lab["motivation"])}}}')
    out += _tex_motivation(d, register, lang)

    out.append(rf'\section*{{{latex_escape(lab["method"])}}}')
    if register == 'detail':
        hp = (d.get('method_flow', {}) or {}).get('high_level_pipeline', '')
        if hp:
            out.append(rf'\textbf{{Pipeline.}} {_render_inline(hp, "tex")}')
    buckets = _bucket(src['steps'], src['modules'], lang)
    idmap = _step_number_map(buckets, lang) if register == 'std' else {}
    n = 0
    for b in buckets:
        if b['header']:
            out.append(rf'\subsection*{{{latex_escape(b["header"])}}}')
            if b['purpose']:
                out.append(rf'\emph{{{_render_inline(b["purpose"], "tex")}}}')
        out.append(rf'\begin{{enumerate}}[leftmargin=*,start={n + 1}]')
        for s in b['steps']:
            n += 1
            head, what, why = _step_view(s, register)
            sid = s.get('step_id', '')
            sid_tex = latex_escape(sid)
            head_tex = rf'\textbf{{{latex_escape(head)}}} (\texttt{{{sid_tex}}}) \\ ' if head else ''
            what = _deref_step_ids(what, idmap, lang)
            out.append(rf'  \item {head_tex}{_render_inline(what, "tex")}')
            for e in eq_by_step.get(sid, []):
                tag += 1
                desc = _render_inline(_deref_step_ids(_eq_desc(e, lang), idmap, lang), 'tex')
                body = (e.get('latex', '') or '').strip()
                if desc:
                    out.append(rf'\noindent\emph{{{desc}}}')
                out.extend(_tex_equation(body, tag))
            if why:
                out.append(rf'\par\emph{{{latex_escape(lab["why"] + lab["colon"])}}} {_render_inline(_deref_step_ids(why, idmap, lang), "tex")}')
        out.append(r'\end{enumerate}')

    if leftover_eqs:
        out.append(rf'\subsection*{{{latex_escape(lab["equations"])}}}')
        for e in leftover_eqs:
            tag += 1
            desc = _render_inline(_deref_step_ids(_eq_desc(e, lang), idmap, lang), 'tex')
            body = (e.get('latex', '') or '').strip()
            if desc:
                out.append(rf'\noindent\emph{{{desc}}}')
            out.extend(_tex_equation(body, tag))

    out.append(r'\end{document}')
    return '\n'.join(out) + '\n'


# ----------------------------------------------------------------------------- PDF compile
def _tex_env() -> dict:
    """Augment PATH with the common TeX-install bin dirs on BOTH macOS and Linux,
    so a system TeX Live / MacTeX is found even when the shell PATH omits it."""
    env = os.environ.copy()
    candidates = [
        # macOS (MacTeX / TeX Live)
        Path('/Library/TeX/texbin'),
        Path('/usr/local/texlive/2026/bin/universal-darwin'),
        Path('/usr/local/texlive/2025/bin/universal-darwin'),
        Path('/opt/homebrew/bin'),
        # Linux (TeX Live system + per-user)
        Path('/usr/local/texlive/2026/bin/x86_64-linux'),
        Path('/usr/local/texlive/2025/bin/x86_64-linux'),
        Path.home() / 'texlive' / '2026' / 'bin' / 'x86_64-linux',
        Path.home() / '.local' / 'bin',
        Path('/usr/bin'),
    ]
    extra = os.pathsep.join(str(c) for c in candidates if c.is_dir())
    if extra:
        env['PATH'] = f'{extra}{os.pathsep}{env.get("PATH", "")}'
    return env


def _find_tex_engine(env: dict) -> tuple[str, list[str]] | None:
    """Pick an available LaTeX engine, preferring xelatex (font support) then a
    tectonic single-binary fallback (trivial to install, no full TeX Live).
    Returns (engine_name, argv_prefix) or None."""
    if shutil.which('xelatex', path=env['PATH']):
        return 'xelatex', ['xelatex', '-interaction=nonstopmode', '-halt-on-error']
    if shutil.which('tectonic', path=env['PATH']):
        # tectonic auto-fetches packages; -X compile keeps it to a single .tex file.
        return 'tectonic', ['tectonic', '--keep-logs', '--synctex=0']
    return None


def compile_pdf(tex_path: Path) -> Path | None:
    """Compile one .tex to .pdf in its own directory. Returns the PDF path, or None
    (with an actionable, cross-platform hint on stderr) if no engine is available
    or the build fails. Tries xelatex first, then tectonic."""
    env = _tex_env()
    engine = _find_tex_engine(env)
    if engine is None:
        print(
            f'  ⚠️ no LaTeX engine (xelatex / tectonic) found; skipped PDF for {tex_path.name}.\n'
            f'     The .tex is written — compile it manually, or install an engine:\n'
            f'       macOS:  brew install --cask mactex-no-gui   (or: brew install tectonic)\n'
            f'       Ubuntu: sudo apt-get install texlive-xetex   (or: cargo install tectonic)\n',
            file=sys.stderr)
        return None
    engine_name, prefix = engine
    try:
        proc = subprocess.run(
            prefix + [tex_path.name],
            cwd=tex_path.parent, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
    except subprocess.TimeoutExpired:
        print(f'  ⚠️ {engine_name} timed out for {tex_path.name}', file=sys.stderr)
        return None
    pdf_path = tex_path.with_suffix('.pdf')
    if proc.returncode != 0 or not pdf_path.exists():
        log = proc.stdout.decode('utf-8', 'replace')[-1500:]
        print(f'  ⚠️ {engine_name} failed for {tex_path.name}:\n{log}', file=sys.stderr)
        return pdf_path if pdf_path.exists() else None
    for ext in ('.aux', '.log', '.out'):
        tex_path.with_suffix(ext).unlink(missing_ok=True)
    return pdf_path


# ----------------------------------------------------------------------------- implementability merge
def merge_implementability(expansion: dict, impl: dict) -> int:
    """Fold the Phase 4.1.5 implementability audit's `enriched_steps` into `expansion` IN PLACE so the
    rendered Method section carries the detailed, implementable step text instead of the terse Phase 4.1
    gestures. Bounded by design: for each enriched step we replace ONLY the three prose surfaces the cards
    render — `method_flow.steps[].what_changes` (pro card), `plain_method_steps_en[].what_to_do` and
    `plain_method_steps_zh[].what_to_do` (std cards) — matched by `step_id`. Every other field (titles,
    why_*, linked_*, inputs/outputs, equations, and the kill-switch fields) is untouched; the audit file
    structurally never carries them. Returns the number of steps enriched."""
    enriched = {e.get('step_id'): e for e in (impl.get('enriched_steps') or []) if e.get('step_id')}
    if not enriched:
        return 0
    # The audit writes any 【作者需决定：…】/【author decision: …】 annotation INLINE in the enriched text,
    # placed right after the sentence it qualifies — so we render the enriched prose verbatim rather than
    # appending notes at the step end (which detaches the decision from the sentence it bites).
    pro_steps = (expansion.get('method_flow', {}) or {}).get('steps', []) or []
    std_en = expansion.get('plain_method_steps_en') or []
    std_zh = expansion.get('plain_method_steps_zh') or []
    n = 0
    for s in pro_steps:
        e = enriched.get(s.get('step_id'))
        if e and e.get('what_changes'):
            s['what_changes'] = e['what_changes']; n += 1
    for s in std_en:
        e = enriched.get(s.get('step_id'))
        if e and e.get('what_to_do_en'):
            s['what_to_do'] = e['what_to_do_en']
    for s in std_zh:
        e = enriched.get(s.get('step_id'))
        if e and e.get('what_to_do_zh'):
            s['what_to_do'] = e['what_to_do_zh']
    return n


def apply_implementability(expansion: dict, expansion_path: Path, impl_path: Path | None = None) -> int:
    """Locate the implementability audit JSON (explicit `impl_path`, else the sibling
    `phase4_implementability.json` next to the expansion) and merge it. No-op (returns 0) when absent,
    so rendering still works for runs produced before this step existed."""
    p = impl_path or (expansion_path.parent / 'phase4_implementability.json')
    if not p.exists():
        return 0
    impl = json.loads(p.read_text())
    n = merge_implementability(expansion, impl)
    if n:
        print(f'  merged implementability audit ({n} steps enriched) from {p}')
    return n


# ----------------------------------------------------------------------------- entry point
def render_one(expansion: dict, out_dir: Path) -> Path:
    """Emit the 7 lean deliverables. Returns the std/en markdown path (the primary surface
    the host LLM reads back to the caller)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # std register ships both languages; detail register ships English markdown only.
    std_md_path = None
    for lang in ('en', 'zh'):
        md_path = out_dir / f'idea.std.{lang}.md'
        tex_path = out_dir / f'idea.std.{lang}.tex'
        md_path.write_text(render_card_md(expansion, 'std', lang))
        tex_path.write_text(render_card_latex(expansion, 'std', lang))
        print(f'  wrote {md_path}')
        print(f'  wrote {tex_path}')
        pdf = compile_pdf(tex_path)
        if pdf is None:
            # First compile failed despite the per-equation structural guard (e.g. an
            # equation that is brace-balanced but uses an undefined macro). Retry once
            # with ALL equations degraded to raw text so a PDF is still produced.
            global _FORCE_DEGRADE_MATH
            _FORCE_DEGRADE_MATH = True
            try:
                tex_path.write_text(render_card_latex(expansion, 'std', lang))
                pdf = compile_pdf(tex_path)
            finally:
                _FORCE_DEGRADE_MATH = False
            if pdf is not None:
                print(f'  ⚠️ {tex_path.name}: a formula would not typeset; recompiled with '
                      f'equations shown as raw LaTeX')
        if pdf and pdf.exists():
            print(f'  wrote {pdf}')
        if lang == 'en':
            std_md_path = md_path

    detail_md_path = out_dir / 'idea.detail.en.md'
    detail_md_path.write_text(render_card_md(expansion, 'detail', 'en'))
    print(f'  wrote {detail_md_path}')

    return std_md_path


def _resolve_input(p):
    """Resolve an input path, falling back to the run-dir env var for relatives.

    The skill documents every path under a run dir, but argparse/Path resolve a
    bare relative path against the process cwd, which may not be the run dir. If
    the as-given path is missing and relative, retry under the run-dir variable
    (IDEA_SPARK_PROJECT_DIR, or legacy CLAUDE_PROJECT_DIR) before giving up.
    """
    path = Path(p)
    if not path.exists() and not path.is_absolute():
        base = (os.environ.get('IDEA_SPARK_PROJECT_DIR')
                or os.environ.get('CLAUDE_PROJECT_DIR'))
        if base:
            alt = Path(base) / p
            if alt.exists():
                return alt
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expansion', required=True, help='Phase 4 expansion JSON path')
    ap.add_argument('--out', required=True, help='Output dir')
    ap.add_argument('--implementability', default=None,
                    help='Phase 4.1.5 implementability audit JSON (default: sibling phase4_implementability.json)')
    args = ap.parse_args()

    expansion_path = _resolve_input(args.expansion)
    expansion = json.loads(expansion_path.read_text())
    apply_implementability(expansion, expansion_path,
                           _resolve_input(args.implementability) if args.implementability else None)
    out_dir = Path(args.out)
    render_one(expansion, out_dir)


if __name__ == '__main__':
    main()
