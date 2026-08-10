#!/usr/bin/env python3
"""Seed concise ``[handle]`` Notes and compact Alt Text into an animated PPTX."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from editable_pptx import ProtocolError, bootstrap_protocol, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--script-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = bootstrap_protocol(args.pptx, args.script_json, args.out)
    except (OSError, ProtocolError) as exc:
        sys.exit(f"[bootstrap_editable_pptx] {exc}")
    write_json(args.report_out, report)
    print(
        f"[bootstrap_editable_pptx] wrote {args.out} "
        f"({report['slide_count']} slides, {report['effect_count']} effects)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
