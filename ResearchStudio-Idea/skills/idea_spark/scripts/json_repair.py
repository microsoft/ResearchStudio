"""Tolerant loader for LLM-written JSON artifacts.

Sub-agents writing CJK prose type an ASCII `"` as a content quote, which terminates
the string early; raw newlines inside strings appear the same way. Both abort an
assemble mid-run, and both have occurred live.

`load_llm_json` tries a strict parse first (the only path for orchestrator-written
files) and repairs only on failure, distinguishing a real string terminator from a
stray inner quote by lookahead: a closing quote is followed, after whitespace, by one
of `,}]:` or EOF. Repair-on-read, never on write — the artifact on disk stays as the
author wrote it unless the caller passes `rewrite=True`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Tuple

_TERMINATORS = ',}]:'


def repair_json_text(s: str) -> str:
    """Escape stray inner quotes and raw control chars inside JSON string values."""
    out = []
    i, n = 0, len(s)
    in_str = False
    esc = False
    while i < n:
        c = s[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            i += 1
            continue
        if esc:
            out.append(c)
            esc = False
            i += 1
            continue
        if c == '\\':
            out.append(c)
            esc = True
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] in ' \t\r\n':
                j += 1
            nxt = s[j] if j < n else ''
            if nxt in _TERMINATORS or nxt == '':
                out.append('"')
                in_str = False
            else:
                out.append('\\"')      # stray content quote
            i += 1
            continue
        if c == '\n':
            out.append('\\n')
        elif c == '\t':
            out.append('\\t')
        elif c == '\r':
            out.append('\\r')
        else:
            out.append(c)
        i += 1
    return ''.join(out)


def loads_llm_json(text: str) -> Tuple[Any, bool]:
    """Parse `text`, repairing it if a strict parse fails.

    Returns (obj, was_repaired). Raises the ORIGINAL JSONDecodeError if the
    repair does not produce valid JSON either — a repair that fails should not
    mask where the real damage is.
    """
    try:
        return json.loads(text), False
    except json.JSONDecodeError as first_error:
        try:
            return json.loads(repair_json_text(text)), True
        except json.JSONDecodeError:
            raise first_error


def load_llm_json(path: str | Path, rewrite: bool = False,
                  quiet: bool = False) -> Any:
    """Read an LLM-written JSON file, repairing stray quotes / control chars.

    `rewrite=True` writes the normalized form back so downstream readers do not
    each repeat the repair. A repair is always reported on stderr unless
    `quiet` — a silently repaired artifact is how a subtle corruption survives.
    """
    p = Path(path)
    obj, repaired = loads_llm_json(p.read_text())
    if repaired:
        if not quiet:
            import sys
            print(f'  [json_repair] {p.name}: escaped stray quote(s)/control '
                  f'char(s) inside string values to parse it'
                  + (' (rewrote the file)' if rewrite else ''), file=sys.stderr)
        if rewrite:
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    return obj
