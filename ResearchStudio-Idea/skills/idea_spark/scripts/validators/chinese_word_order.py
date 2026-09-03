"""Validator: a Chinese field must not carry an English relative clause in front of its noun.

The plain-Chinese fields are the ones a reader actually reads, and they are derived from
finished English prose one sentence at a time. The failure that survives that derivation is
word order: an English relative clause lands as a pre-nominal modifier, so the reader has to
reach the end of a long run before learning what is being described.

`derive_plain.txt` has always asked for "natural Chinese prose, not a word-for-word
translation". That phrasing states the goal and not the test, and it is satisfiable in the
model's own judgement while the calque goes out — which is why this check exists in code.

The test is the one the prompt now states: characters before 的, no comma among them, past a
threshold. `warn` and not `fail` — a long modifier is a readability defect, not a broken
contract, and a technical noun phrase can legitimately run long.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# The threshold the prompt states; keep the two in step, or the check silently permits what the
# rule forbids. Calibrated on 36 rendered cards (>12 flags all, >15 flags 81%, >18 flags 50%) and
# fixed by an A/B on one card: the same technical fields derived under the prompt with and without
# the CHINESE WORD ORDER block gave 6 vs 2 runs at >18, while >20 gave 1 vs 2 — so 18 is where the
# check still separates the two, and 20 is where it stops. Artifacts: ideaspark_run/_derive_ab/.
_MAX_MODIFIER = 18
_CJK = r'一-鿿'
# 的 itself must be excluded from the run, or one 'modifier' rolls across the previous 的
# and reports a span that is really two clauses.
_LONG_MODIFIER = re.compile(rf'((?:(?!的)[{_CJK}A-Za-z0-9\-_`]){{{_MAX_MODIFIER + 1},}})的[{_CJK}]')
_BREAK = re.compile(r'[，。；、：（）()]')

# Calques whose Chinese reading is a different word, so the sentence is not merely awkward.
_CALQUES = {'保留任务': '留出任务 (held-out)', '保留集': '留出集 (held-out set)',
            '两个位': '两个二值判定 (the two bits)'}

_ZH_FIELDS = ('title_zh', 'plain_motivation_zh')
_ZH_LISTS = ('plain_method_steps_zh', 'plain_method_modules_zh')


def _spans(doc):
    """Yield (label, text) for every Chinese prose field in an expansion."""
    for k in _ZH_FIELDS:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            yield k, v
    for k in _ZH_LISTS:
        for i, item in enumerate(doc.get(k) or []):
            if isinstance(item, str):
                yield f'{k}[{i}]', item
            elif isinstance(item, dict):
                for kk, vv in item.items():
                    if isinstance(vv, str) and vv.strip():
                        yield f'{k}[{i}].{kk}', vv


def validate_chinese_word_order(phase4_path: str) -> list[dict]:
    findings: list[dict] = []
    try:
        doc = json.loads(Path(phase4_path).read_text())
    except Exception:
        return findings
    if not isinstance(doc, dict):
        return findings

    long_hits, calque_hits = [], []
    for label, text in _spans(doc):
        for m in _LONG_MODIFIER.finditer(text):
            if not _BREAK.search(m.group(1)):
                long_hits.append((label, m.group(1)[:34]))
                break                     # one report per field is enough to act on
        for bad, good in _CALQUES.items():
            if bad in text:
                calque_hits.append((label, bad, good))

    if long_hits:
        shown = '; '.join(f'{lb}: 「{s}…的」' for lb, s in long_hits[:3])
        findings.append({
            'validator': 'chinese_word_order', 'severity': 'warn',
            'message': (f'{len(long_hits)} Chinese field(s) put more than {_MAX_MODIFIER} '
                        f'characters in front of 的 with no break — {shown}. That is an English '
                        f'relative clause left in pre-nominal position; the reader cannot tell '
                        f'what is being described until the end. Split it: noun first, '
                        f'description as its own clause (see CHINESE WORD ORDER in '
                        f'derive_plain.txt).')})
    if calque_hits:
        shown = '; '.join(f'{lb}: 「{b}」→ {g}' for lb, b, g in calque_hits[:3])
        findings.append({
            'validator': 'chinese_word_order', 'severity': 'warn',
            'message': f'Calqued term(s) whose Chinese reading is a different word — {shown}.'})

    if not findings:
        findings.append({
            'validator': 'chinese_word_order', 'severity': 'pass',
            'message': 'Chinese fields carry no over-long pre-nominal modifier and no known calque.'})
    return findings
