#!/usr/bin/env python3
"""Build word-aligned animation beats from an editable PPTX or legacy SVG report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from editable_pptx import (
    ProtocolError,
    build_pptx_animation_manifest,
    extract_protocol,
    write_json,
)


SCHEMA_VERSION = "paper2video_animation_manifest.v1"
DEFAULT_EFFECT_SECONDS = {
    "Appear": 0.12,
    "Fade In": 0.48,
    "Dissolve In": 0.48,
    "Fly In": 0.56,
    "Wipe In": 0.52,
    "Zoom In": 0.48,
    "Circle In": 0.52,
    "Diamond In": 0.52,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalized_chars(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", text.lower()))


def _top_level_ids(svg_path: Path) -> set[str]:
    root = ET.parse(svg_path).getroot()
    return {
        str(child.attrib.get("id") or "").strip()
        for child in list(root)
        if str(child.attrib.get("id") or "").strip()
    }


def _align_block(
    words: list[dict[str, object]], cursor: int, transcript: str,
) -> tuple[int, int]:
    target = _normalized_chars(transcript)
    if not target:
        raise ValueError("animation transcript block is empty")
    combined = ""
    end = cursor
    while end < len(words) and len(combined) < len(target):
        combined += _normalized_chars(str(words[end].get("text") or ""))
        end += 1
    if combined != target:
        raise ValueError(
            f"could not align animation transcript {transcript!r} at word index {cursor}; "
            f"normalized timing text was {combined!r}, expected {target!r}"
        )
    return cursor, end


def build_manifest(
    author_notes_report: Path,
    word_timings: Path,
    svg_dir: Path,
) -> dict[str, object]:
    notes = json.loads(author_notes_report.read_text(encoding="utf-8"))
    timings = json.loads(word_timings.read_text(encoding="utf-8"))
    note_slides = notes.get("slides") or []
    timing_sections = timings.get("sections") or []
    svg_paths = sorted(svg_dir.glob("*.svg"))
    if not note_slides:
        raise ValueError("author notes report has no slides")
    if len(note_slides) != len(timing_sections):
        raise ValueError(
            f"author notes slide count {len(note_slides)} != timing section count "
            f"{len(timing_sections)}"
        )
    if len(note_slides) != len(svg_paths):
        raise ValueError(
            f"author notes slide count {len(note_slides)} != SVG count {len(svg_paths)}"
        )

    manifest_slides: list[dict[str, object]] = []
    effect_count = 0
    for index, (slide, section, svg_path) in enumerate(
        zip(note_slides, timing_sections, svg_paths), start=1
    ):
        slide_id = str(slide.get("section_id") or "")
        timing_id = str(section.get("id") or "")
        if slide_id != timing_id:
            raise ValueError(
                f"slide {index} id {slide_id!r} != timing section id {timing_id!r}"
            )
        words = section.get("words") or []
        if not isinstance(words, list) or not words:
            raise ValueError(f"slide {index} has no word timings")
        available_ids = _top_level_ids(svg_path)
        cursor = 0
        effects_out: list[dict[str, object]] = []
        for block_index, block in enumerate(slide.get("blocks") or [], start=1):
            locator = str(block.get("locator") or "").strip()
            if not locator or locator not in available_ids:
                raise ValueError(
                    f"slide {index} animation locator {locator!r} is not a top-level SVG id"
                )
            start_index, end_index = _align_block(
                words, cursor, str(block.get("transcript") or "")
            )
            cursor = end_index
            word_start = float(words[start_index].get("start") or 0.0)
            word_end = float(words[end_index - 1].get("end") or word_start)
            names = block.get("effects") or []
            if not names:
                raise ValueError(f"slide {index} block {block_index} has no named effects")
            for effect_index, raw_name in enumerate(names):
                name = str(raw_name)
                if name not in DEFAULT_EFFECT_SECONDS:
                    raise ValueError(
                        f"slide {index} block {block_index} uses unsupported video "
                        f"animation {name!r}"
                    )
                duration = DEFAULT_EFFECT_SECONDS[name]
                start = word_start + effect_index * 0.12
                effects_out.append(
                    {
                        "order": len(effects_out) + 1,
                        "shape_id": str(block.get("shape_id") or ""),
                        "handle": str(block.get("handle") or ""),
                        "locator": locator,
                        "name": name,
                        "start": round(start, 3),
                        "duration": duration,
                        "word_start": start_index,
                        "word_end": end_index - 1,
                        "spoken_end": round(word_end, 3),
                        "timing_source": "edge_word_alignment",
                    }
                )
                effect_count += 1
        if cursor != len(words):
            raise ValueError(
                f"slide {index} animation blocks consumed {cursor}/{len(words)} timing words"
            )
        manifest_slides.append(
            {
                "index": index,
                "id": slide_id,
                "svg": str(svg_path.resolve()),
                "effect_count": len(effects_out),
                "effects": effects_out,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": _utc_now(),
        "author_notes_report": str(author_notes_report.resolve()),
        "word_timings": str(word_timings.resolve()),
        "svg_dir": str(svg_dir.resolve()),
        "slide_count": len(manifest_slides),
        "effect_count": effect_count,
        "timing_source": "edge_word_alignment",
        "slides": manifest_slides,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--author-notes-report", type=Path)
    source.add_argument(
        "--pptx",
        type=Path,
        help="Editable source deck carrying native animations, authoritative Notes, and compact Alt Text.",
    )
    parser.add_argument("--word-timings", type=Path, required=True)
    parser.add_argument(
        "--svg-dir",
        type=Path,
        help="Required with --author-notes-report; not used by the editable PPTX route.",
    )
    parser.add_argument(
        "--protocol-report-out",
        type=Path,
        help="Optional strict PPTX protocol report written by the editable route.",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.pptx is not None:
            timing_payload = json.loads(args.word_timings.read_text(encoding="utf-8"))
            section_ids = [
                str(section.get("id") or "")
                for section in timing_payload.get("sections") or []
            ]
            if not section_ids or any(not section_id for section_id in section_ids):
                raise ProtocolError("word timings contain missing or empty section IDs")
            protocol = extract_protocol(args.pptx, section_ids=section_ids)
            manifest = build_pptx_animation_manifest(
                protocol,
                args.word_timings.resolve(),
            )
            if args.protocol_report_out is not None:
                write_json(args.protocol_report_out, protocol)
        else:
            if args.svg_dir is None:
                raise ValueError("--svg-dir is required with --author-notes-report")
            if args.protocol_report_out is not None:
                raise ValueError("--protocol-report-out is only valid with --pptx")
            manifest = build_manifest(
                args.author_notes_report.resolve(),
                args.word_timings.resolve(),
                args.svg_dir.resolve(),
            )
    except (OSError, ValueError, ProtocolError, json.JSONDecodeError, ET.ParseError) as exc:
        sys.exit(f"[build_animation_manifest] {exc}")
    write_json(args.out, manifest)
    print(
        f"[build_animation_manifest] wrote {args.out} "
        f"({manifest['slide_count']} slides, {manifest['effect_count']} effects)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
