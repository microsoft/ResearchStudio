"""merge_revisions: apply Phase 3.3 patch to Phase 2.2 candidate.

Why this script exists:
  Phase 3.3 used to ask the LLM to echo the full Phase 2.2 candidate JSON
  (12 flat fields, kill-switch fields byte-identical) with named field edits
  applied. That payload is ~25k tokens of mostly verbatim copy, dominated by
  re-typing `falsification_prediction` + `compute_budget` — the model has no
  reason to know that re-typing them risks a backend inference timeout.

  The new contract: Phase 3.3 emits only the `applied_revisions[]` patch list
  (one entry per revision_target, each carrying the new value of one named
  field plus an explicit `op`). This script walks that patch, applies each
  op to a deep copy of the Phase 2.2 candidate, refuses to touch kill-switch
  fields (mechanical guard, not a post-hoc validator), and writes
  `final_candidate.json` next to the patch.

  It also injects `final_candidate` BACK into the patch file at the top
  level, so `kill_switch_integrity` and any downstream consumer that expects
  `phase3_revise_output.json['final_candidate']` (legacy shape) keep working.

Patch op vocabulary:
  - `replace`         — set field to value (full replacement of a string / list / dict)
  - `append_sentence` — append " " + value to an existing string (preserves prior content)
  - `append_items`    — extend an existing list field with value (must itself be a list)
  - `swap_sub_pattern` — for scope=sub_pattern: identify a gap_closure entry by
                        the GAP TEXT (the patch's `field` is the gap verbatim) and
                        replace that entry's `sub_pattern` with value; the patch
                        may include additional `replace`/`append_sentence` ops on
                        sibling fields to re-align `how_closed` / `core_mechanism`.

Field path syntax (the `field` slot in each patch entry):
  - Top-level:    `core_mechanism`, `differentiation_from_lit`
  - List index:   `differentiation_from_lit[2].delta`
  - Gap-text key: for swap_sub_pattern, `gap_closure[<verbatim gap text>].sub_pattern`
                  — we match by gap text rather than index so a re-ordering upstream
                  doesn't break the patch.

Kill-switch guard:
  Any patch op targeting `falsification_prediction` or `compute_budget` via the
  generic ops is REFUSED — the merger raises with a clear message naming the
  offending entry. This makes the anti-substitution contract STRUCTURAL: the
  model physically cannot drift the kill switch even if the audit emits a bad
  target.

  ONE audited exception: the audit's falsification_structure_check can find the
  falsification_prediction paragraph structurally deficient (no load-bearing
  variable / tautological negative control). That finding is repairable without
  weakening the committed experiment or claim, so Phase 3.3 may carry a single
  `rewrite_falsification` op (scope=falsification). The merger applies it ONLY
  when the Phase 3.2 critique report (passed via --critique) contains a
  scope=falsification revision_target — the LLM cannot self-authorize. The
  rewritten paragraph must then pass the falsification re-audit before Phase 4,
  and kill_switch_integrity validates the Phase 3.3 → Phase 4 link instead of
  Phase 2.2 → Phase 4 for this field. `compute_budget` has no exception.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
from typing import Any


KILL_SWITCH_FIELDS = {'falsification_prediction', 'compute_budget'}

# Valid ops; anything else is a process error
VALID_OPS = {'replace', 'append_sentence', 'append_items', 'swap_sub_pattern',
             'rewrite_falsification'}

# `differentiation_from_lit[2].delta` -> ('differentiation_from_lit', 2, 'delta')
_LIST_IDX = re.compile(r'^([a-z_][a-z0-9_]*)\[(\d+)\]$')


def _parse_field_path(path: str) -> list[str | int]:
    """Tokenize a dotted/bracketed JSON path into a list of keys / indices.

    Examples:
      'core_mechanism' -> ['core_mechanism']
      'differentiation_from_lit[2].delta' -> ['differentiation_from_lit', 2, 'delta']

    The gap_closure[<verbatim text>] form is handled separately by the
    swap_sub_pattern op (we don't try to embed arbitrary text inside this
    grammar — quoting rules get ugly).
    """
    tokens: list[str | int] = []
    for segment in path.split('.'):
        m = _LIST_IDX.match(segment)
        if m:
            tokens.append(m.group(1))
            tokens.append(int(m.group(2)))
        else:
            tokens.append(segment)
    return tokens


def _resolve_parent(root: dict, tokens: list[str | int]) -> tuple[Any, str | int]:
    """Walk tokens[:-1]; return (container, last_key). Raises on a missing or
    non-container intermediate."""
    cur = root
    for tok in tokens[:-1]:
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok >= len(cur):
                raise ValueError(f'cannot walk list index [{tok}] on {type(cur).__name__} of len '
                                 f'{len(cur) if isinstance(cur, list) else "n/a"}')
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                raise ValueError(f'cannot walk key {tok!r} on {type(cur).__name__} '
                                 f'(available: {list(cur.keys()) if isinstance(cur, dict) else "n/a"})')
            cur = cur[tok]
    return cur, tokens[-1]


def _check_kill_switch(field_path: str) -> None:
    """Refuse any field path whose ROOT key is a kill-switch field."""
    root_key = field_path.split('.', 1)[0].split('[', 1)[0]
    if root_key in KILL_SWITCH_FIELDS:
        raise ValueError(
            f'patch refused: field {field_path!r} targets kill-switch root {root_key!r}. '
            f'`falsification_prediction` and `compute_budget` are byte-identical across '
            f'Phase 2.2 → Phase 3.3 → Phase 4 by anti-substitution contract. The merger '
            f'will not write them under any op. If the audit emitted this target, the '
            f'audit has a process error.'
        )


def _apply_replace(root: dict, field_path: str, value: Any) -> None:
    tokens = _parse_field_path(field_path)
    parent, last = _resolve_parent(root, tokens)
    if isinstance(last, int):
        if not isinstance(parent, list) or last >= len(parent):
            raise ValueError(f'replace: cannot set list[{last}] on {type(parent).__name__} of len '
                             f'{len(parent) if isinstance(parent, list) else "n/a"}')
        parent[last] = value
    else:
        if not isinstance(parent, dict):
            raise ValueError(f'replace: cannot set key {last!r} on {type(parent).__name__}')
        parent[last] = value


def _apply_append_sentence(root: dict, field_path: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError(f'append_sentence: value must be a string, got {type(value).__name__}')
    tokens = _parse_field_path(field_path)
    parent, last = _resolve_parent(root, tokens)
    cur = parent[last] if isinstance(last, (str, int)) else None
    if not isinstance(cur, str):
        raise ValueError(f'append_sentence: target {field_path!r} is not a string '
                         f'(found {type(cur).__name__}); use `replace` instead')
    # Single space separator; if existing string ends with whitespace already, don't double it
    sep = '' if cur.endswith((' ', '\n', '\t')) else ' '
    parent[last] = cur + sep + value


def _apply_append_items(root: dict, field_path: str, value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError(f'append_items: value must be a list, got {type(value).__name__}')
    tokens = _parse_field_path(field_path)
    parent, last = _resolve_parent(root, tokens)
    cur = parent[last] if isinstance(last, (str, int)) else None
    if not isinstance(cur, list):
        raise ValueError(f'append_items: target {field_path!r} is not a list '
                         f'(found {type(cur).__name__}); use `replace` instead')
    cur.extend(value)


def _apply_swap_sub_pattern(root: dict, field_path: str, value: Any) -> None:
    """field_path is the GAP TEXT verbatim (no JSON-path grammar). Find the
    gap_closure entry whose `gap` equals this text exactly; replace its
    `sub_pattern` with value (a string of the form `C## (Parent Display Name)`).

    The patch may carry additional `replace` / `append_sentence` ops on
    related fields (how_closed, core_mechanism); those are independent patch
    entries handled in their own loop iteration.
    """
    if not isinstance(value, str):
        raise ValueError(f'swap_sub_pattern: value must be a string (C## form), got {type(value).__name__}')
    gap_closure = root.get('gap_closure')
    if not isinstance(gap_closure, list):
        raise ValueError('swap_sub_pattern: candidate has no gap_closure[] to swap into')
    for entry in gap_closure:
        if isinstance(entry, dict) and entry.get('gap') == field_path:
            entry['sub_pattern'] = value
            return
    raise ValueError(
        f'swap_sub_pattern: no gap_closure entry matches gap text. The patch field is the '
        f'verbatim gap; this is what Phase 2.2 wrote (matched word-for-word). Got '
        f'len={len(field_path)} chars. First 80: {field_path[:80]!r}'
    )


def _apply_rewrite_falsification(root: dict, field_path: str, value: Any) -> None:
    """The single audited kill-switch exception: replace `falsification_prediction`
    wholesale. Authorization (audit emitted a scope=falsification revision_target)
    is verified by the caller (apply_patch) BEFORE dispatch; this function only
    enforces the local shape rules."""
    if field_path != 'falsification_prediction':
        raise ValueError(
            f'rewrite_falsification: field must be exactly "falsification_prediction", '
            f'got {field_path!r}. compute_budget and every other field have no rewrite route.')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('rewrite_falsification: value must be a non-empty string '
                         '(the full rewritten 3-5 sentence paragraph)')
    root['falsification_prediction'] = value


_OP_DISPATCH = {
    'replace': _apply_replace,
    'append_sentence': _apply_append_sentence,
    'append_items': _apply_append_items,
    'swap_sub_pattern': _apply_swap_sub_pattern,
    'rewrite_falsification': _apply_rewrite_falsification,
}


def apply_patch(candidate: dict, applied_revisions: list[dict],
                falsification_authorized: bool = False) -> dict:
    """Return a deep-copied candidate with every applied_revisions entry whose
    `outcome == 'applied'` (or missing/falsy outcome — defensive: apply unless
    explicitly skipped) executed. Skipped entries (`outcome` starting with
    'skipped_') are left for audit trail but do not mutate the candidate.

    The result is the new `final_candidate`. Kill-switch fields are guaranteed
    byte-identical to the input candidate — except `falsification_prediction`
    when `falsification_authorized` is True (the Phase 3.2 audit emitted a
    scope=falsification revision_target) AND the patch carries a
    `rewrite_falsification` op; at most one such entry is applied.
    """
    out = copy.deepcopy(candidate)
    n_falsification_rewrites = 0

    for i, rev in enumerate(applied_revisions or []):
        if not isinstance(rev, dict):
            raise ValueError(f'applied_revisions[{i}] is not an object: {type(rev).__name__}')
        outcome = rev.get('outcome', '')
        if isinstance(outcome, str) and outcome.startswith('skipped_'):
            continue  # audit trail only; do not apply

        op = rev.get('op')
        if op not in VALID_OPS:
            raise ValueError(f'applied_revisions[{i}].op = {op!r} is not one of {sorted(VALID_OPS)}')

        field = rev.get('field')
        if not field or not isinstance(field, str):
            raise ValueError(f'applied_revisions[{i}].field is empty or non-string')

        if op == 'rewrite_falsification':
            if not falsification_authorized:
                raise ValueError(
                    f'applied_revisions[{i}]: rewrite_falsification is NOT authorized — the '
                    f'Phase 3.2 critique report contains no scope="falsification" '
                    f'revision_target (or --critique was not passed to the merger). The LLM '
                    f'cannot self-authorize a kill-switch rewrite.')
            n_falsification_rewrites += 1
            if n_falsification_rewrites > 1:
                raise ValueError(
                    f'applied_revisions[{i}]: a patch may carry at most ONE applied '
                    f'rewrite_falsification entry (exactly one rewrite attempt per run).')
        elif op != 'swap_sub_pattern':
            # swap_sub_pattern uses the field slot for the gap text, not a JSON path,
            # so the kill-switch guard does not apply (cannot touch the kill switch via
            # that op). Every other generic op is guarded.
            _check_kill_switch(field)

        if 'value' not in rev:
            raise ValueError(f'applied_revisions[{i}] missing `value`')

        try:
            _OP_DISPATCH[op](out, field, rev['value'])
        except ValueError as e:
            raise ValueError(f'applied_revisions[{i}] ({op} {field!r}): {e}') from None

    return out


def _critique_authorizes_falsification_rewrite(critique_path: Path | None) -> bool:
    """True iff the Phase 3.2 critique report exists and contains at least one
    revision_targets[] entry with scope == 'falsification'. This is the ONLY
    source of authorization for a rewrite_falsification patch op — the audit
    (a separate LLM call from the reviser) must have found the structure
    deficient; the reviser cannot self-authorize."""
    if not critique_path:
        return False
    try:
        critique = json.loads(Path(critique_path).read_text())
    except Exception:
        return False
    targets = critique.get('revision_targets') or []
    return any(isinstance(t, dict) and t.get('scope') == 'falsification' for t in targets)


def merge_phase3_revisions(phase2_candidate_path: Path, revisions_path: Path,
                           out_dir: Path, critique_path: Path | None = None) -> tuple[Path, Path]:
    """Top-level entry. Read Phase 2.2 candidate + Phase 3.3 patch; write
    `final_candidate.json` to out_dir AND back-inject `final_candidate` into
    the patch file (so the legacy kill_switch_integrity check on
    `phase3_revise_output.json['final_candidate']` keeps working).

    `critique_path` (the Phase 3.2 report) authorizes an audited
    `rewrite_falsification` op when its revision_targets[] carry a
    scope=falsification entry; without it the merger refuses that op.

    Returns (final_candidate_path, updated_revisions_path).
    """
    candidate = json.loads(phase2_candidate_path.read_text())
    patch_doc = json.loads(revisions_path.read_text())
    if not isinstance(patch_doc, dict):
        raise ValueError(f'{revisions_path} is not a JSON object')
    applied = patch_doc.get('applied_revisions') or []

    authorized = _critique_authorizes_falsification_rewrite(critique_path)
    final_candidate = apply_patch(candidate, applied, falsification_authorized=authorized)

    falsification_rewritten = any(
        isinstance(r, dict) and r.get('op') == 'rewrite_falsification'
        and not str(r.get('outcome', '')).startswith('skipped_')
        for r in applied)

    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / 'final_candidate.json'
    final_path.write_text(json.dumps(final_candidate, indent=2, ensure_ascii=False))

    # Back-inject for legacy consumers (kill_switch_integrity, host LLM expecting
    # `phase3_revise_output.json['final_candidate']`). `falsification_rewritten`
    # tells kill_switch_integrity to validate the 3.3 → 4 link for that field
    # (instead of 2.2 → 4) and tells the host a re-audit is REQUIRED before Phase 4.
    patch_doc['final_candidate'] = final_candidate
    patch_doc['falsification_rewritten'] = falsification_rewritten
    revisions_path.write_text(json.dumps(patch_doc, indent=2, ensure_ascii=False))

    return final_path, revisions_path
