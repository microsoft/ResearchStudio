#!/usr/bin/env python3
"""Extract a no-LLM narration script and strict protocol report from a PPTX."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from editable_pptx import ProtocolError, extract_protocol, script_from_protocol, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--ids-from-script", type=Path, default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--script-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        protocol = extract_protocol(
            args.pptx,
            ids_from_script=args.ids_from_script,
        )
        script = script_from_protocol(protocol, voice=args.voice)
    except (OSError, ProtocolError) as exc:
        sys.exit(f"[extract_editable_pptx] {exc}")
    write_json(args.report_out, protocol)
    write_json(args.script_out, script)
    print(
        f"[extract_editable_pptx] wrote {args.script_out} and {args.report_out} "
        f"({protocol['slide_count']} slides, {protocol['effect_count']} effects)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
