#!/usr/bin/env python3
"""Change-aware optional narration regeneration for editable PPTX video."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from editable_pptx import ProtocolError, apply_user_script


DEFAULT_MODEL = "gpt-5.6-sol"


def _regeneration_targets(
    protocol: dict[str, object],
    change_report: dict[str, object],
) -> list[dict[str, object]]:
    blocks_by_key: dict[tuple[int, str], dict[str, object]] = {}
    for slide in protocol.get("slides") or []:
        slide_index = int(slide["index"])
        for block in slide.get("blocks") or []:
            blocks_by_key[(slide_index, str(block["handle"]))] = block

    targets: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for change in change_report.get("changes") or []:
        if str(change.get("kind") or "") == "removed":
            continue
        after = change.get("after") or {}
        slide_index = int(change.get("slide_index") or 0)
        handle = str(change.get("handle") or after.get("handle") or "")
        key = (slide_index, handle)
        block = blocks_by_key.get(key)
        if block is None or key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "slide_index": slide_index,
                "handle": handle,
                "change_kind": change.get("kind"),
                "shape_name": after.get("shape_name") or block.get("shape_name"),
                "shape_text": after.get("text") or "",
                "animations": [
                    str(effect.get("name") or "") for effect in block.get("effects") or []
                ],
                "existing_script": str(block.get("raw_transcript") or ""),
            }
        )
    return targets


def _openai_responder(
    targets: list[dict[str, object]],
    *,
    model: str,
) -> list[dict[str, object]]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise ProtocolError(
            "OPENAI_API_KEY is required only when --narration-mode regenerate is selected"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - installer supplies openai
        raise ProtocolError(
            "the openai Python package is required for narration regeneration"
        ) from exc

    schema = {
        "type": "object",
        "properties": {
            "updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slide_index": {"type": "integer"},
                        "handle": {"type": "string"},
                        "script": {"type": "string"},
                    },
                    "required": ["slide_index", "handle", "script"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["updates"],
        "additionalProperties": False,
    }
    client = OpenAI()
    response = client.responses.create(
        model=model,
        reasoning={"effort": "low"},
        instructions=(
            "Rewrite narration only for the supplied changed PowerPoint elements. "
            "Keep each script concise and factual. Preserve a [[Animation Name]] marker "
            "only when it corresponds to an animation listed for that element. Return "
            "exactly one update per supplied target and do not rename handles."
        ),
        input=json.dumps({"targets": targets}, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "pptx_narration_updates",
                "strict": True,
                "schema": schema,
            }
        },
    )
    try:
        payload = json.loads(response.output_text)
    except (AttributeError, json.JSONDecodeError) as exc:
        raise ProtocolError("OpenAI returned invalid narration update JSON") from exc
    return list(payload.get("updates") or [])


def regenerate_changed_narration(
    protocol: dict[str, object],
    change_report: dict[str, object],
    *,
    model: str = DEFAULT_MODEL,
    responder: Callable[[list[dict[str, object]]], list[dict[str, object]]] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Regenerate only changed current handles and leave every other script intact."""
    targets = _regeneration_targets(protocol, change_report)
    if not targets:
        return protocol, {
            "schema_version": "paper2video_narration_regeneration.v1",
            "model": model,
            "target_count": 0,
            "updated_count": 0,
            "updates": [],
        }
    updates = (
        responder(targets)
        if responder is not None
        else _openai_responder(targets, model=model)
    )
    expected = {(int(item["slide_index"]), str(item["handle"])) for item in targets}
    received: dict[tuple[int, str], str] = {}
    for update in updates:
        key = (int(update.get("slide_index") or 0), str(update.get("handle") or ""))
        script = str(update.get("script") or "").strip()
        if key not in expected or key in received or not script:
            raise ProtocolError(
                "narration regeneration returned an unknown, duplicate, or empty update"
            )
        received[key] = script
    if set(received) != expected:
        missing = sorted(expected - set(received))
        raise ProtocolError(f"narration regeneration omitted changed handles: {missing}")

    sections: list[dict[str, object]] = []
    for slide in protocol.get("slides") or []:
        slide_index = int(slide["index"])
        elements = [
            {"handle": handle, "script": script}
            for (index, handle), script in received.items()
            if index == slide_index
        ]
        sections.append({"id": slide["section_id"], "elements": elements})
    with tempfile.NamedTemporaryFile(
        prefix="paper2video-regenerated-",
        suffix=".json",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as temporary:
        temporary.write(json.dumps({"sections": sections}, ensure_ascii=False))
        script_path = Path(temporary.name)
    try:
        updated, _ = apply_user_script(protocol, script_path)
    finally:
        script_path.unlink(missing_ok=True)
    for slide in updated.get("slides") or []:
        for block in slide.get("blocks") or []:
            if (int(slide["index"]), str(block["handle"])) in received:
                block["script_source"] = "llm_regeneration"
        slide["script_sources"] = list(
            dict.fromkeys(
                str(block["script_source"])
                for block in slide.get("blocks") or []
                if str(block.get("transcript") or "")
            )
        )
    updated["script_sources"] = sorted(
        {
            str(source)
            for slide in updated.get("slides") or []
            for source in slide.get("script_sources") or []
        }
    )
    return updated, {
        "schema_version": "paper2video_narration_regeneration.v1",
        "model": model,
        "target_count": len(targets),
        "updated_count": len(received),
        "targets": targets,
        "updates": [
            {"slide_index": index, "handle": handle, "script": script}
            for (index, handle), script in received.items()
        ],
    }
