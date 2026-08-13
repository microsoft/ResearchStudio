"""Validator: a stated user direction may be departed from, but never silently.

Declare-don't-obey. Users arrive with a solution shape in mind, and Phase 1 hard rule 10
keeps that shape out of gap selection on purpose — a cure named before diagnosis gets
built faithfully and the idea comes out incremental — so `intake.user_direction` never
gates anything. `phase2_select_output.user_direction_disposition` records what became of
it. This validator enforces the recording, not the choice.

The verbatim check is what `phase0/user_query.txt` buys: without the question on disk,
"copy the user's words" is unfalsifiable and a direction can be paraphrased into one that
is easier to satisfy. Absent that file (legacy runs) the check is skipped, not guessed at.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_VALID = {'adopted', 'departed', 'n_a'}


def _norm(s: str) -> str:
    return ' '.join((s or '').lower().split())


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _run_dir(phase1_path: Path) -> Path:
    d = phase1_path.parent.parent
    return d.parent if d.name.startswith('attempt_') else d


def validate_user_direction(phase1_path: str, phase2_select_path: str) -> list[dict]:
    findings: list[dict] = []
    p1 = Path(phase1_path)
    ps = Path(phase2_select_path)
    d1, ds = _load(p1), _load(ps)
    if not isinstance(d1, dict) or not isinstance(ds, dict):
        return findings

    intake = d1.get('intake') or {}
    wanted = str(intake.get('user_direction') or '').strip()
    if not wanted or _norm(wanted) in ('n_a', 'n/a', 'none'):
        return findings          # user stated no direction — nothing to disposition

    def fail(msg):
        findings.append({'validator': 'user_direction', 'severity': 'fail', 'message': msg})

    disp = ds.get('user_direction_disposition')
    if not isinstance(disp, dict):
        fail(f'intake.user_direction is set ({wanted[:70]!r}) but {ps.name} has no '
             f'user_direction_disposition. The selection may depart from what the user asked '
             f'for — hard rule 10 is why it is allowed to — but it must say so. Add the field '
             f'with verdict adopted|departed and, when departed, why_departed.')
        return findings

    verdict = _norm(disp.get('verdict'))
    if verdict not in _VALID:
        fail(f'user_direction_disposition.verdict is {disp.get("verdict")!r}; expected one of '
             f'{sorted(_VALID)}.')
        return findings

    if verdict == 'n_a':
        fail('user_direction_disposition.verdict is n_a while intake.user_direction is set. '
             'n_a is only for a user who named no direction.')
        return findings

    if verdict == 'departed' and not str(disp.get('why_departed') or '').strip():
        fail('user_direction_disposition says departed but why_departed is empty. The departure '
             'is the one thing the user cannot see for themselves — state what the chosen path '
             'closes that theirs does not, or what theirs costs that it avoids.')

    # Verbatim check — only possible because phase0 persists the question.
    uq = _run_dir(p1) / 'phase0' / 'user_query.txt'
    try:
        query_norm = _norm(uq.read_text())
    except Exception:
        return findings          # no question on disk -> cannot judge, do not cry wolf

    quoted = str(disp.get('user_wanted') or '').strip()
    for label, span in (('intake.user_direction', wanted),
                        ('user_direction_disposition.user_wanted', quoted)):
        n = _norm(span)
        if not n or n in ('n_a', 'n/a'):
            continue
        if n in query_norm:
            continue
        # Tolerate an elided middle ("A ... B") before failing on a real rewrite.
        parts = [x for x in re.split(r'\s*\.\.\.\s*|\s*…\s*', n) if x]
        if len(parts) > 1 and all(p in query_norm for p in parts):
            continue
        fail(f'{label} is not a span of {uq.name}: {span[:90]!r}. It must be COPIED from the '
             f'question, not restated — a paraphrase here is how a direction quietly becomes an '
             f'easier one to satisfy, and it makes the disposition unauditable.')

    if not findings:
        findings.append({
            'validator': 'user_direction', 'severity': 'pass',
            'message': (f'User direction is dispositioned ({verdict}) and every quoted span is '
                        f'verbatim from {uq.name}.')})
    return findings
