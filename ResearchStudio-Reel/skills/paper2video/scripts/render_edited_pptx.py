#!/usr/bin/env python3
"""Render an edited protocol PPTX to a strictly checked video without an LLM."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from editable_pptx import (
    ProtocolError,
    apply_user_script,
    build_pptx_animation_manifest,
    build_pptx_visual_cue_plan,
    build_pptx_visual_cues,
    detect_pptx_changes,
    extract_protocol,
    normalize_author_notes_authority,
    script_from_protocol,
    write_protocol_to_pptx,
    write_json,
)
from narration_regeneration import DEFAULT_MODEL, regenerate_changed_narration
from generate_edge_audio import ensure_minimum_audio_duration, probe_audio_duration


SCRIPT_DIR = Path(__file__).resolve().parent


def _run(command: list[str]) -> None:
    print("[render_edited_pptx] $ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def _copy_audio_bundle(source: Path, destination: Path, section_ids: list[str]) -> None:
    source = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for section_id in section_ids:
        source_mp3 = source / f"{section_id}.mp3"
        if not source_mp3.is_file():
            raise ProtocolError(f"prebuilt audio is missing {source_mp3}")
        destination_mp3 = destination / source_mp3.name
        if source_mp3.resolve() != destination_mp3.resolve():
            shutil.copy2(source_mp3, destination_mp3)
    timings = source / "word_timings.json"
    if not timings.is_file():
        raise ProtocolError(f"prebuilt audio is missing {timings}")
    if timings.resolve() != (destination / timings.name).resolve():
        shutil.copy2(timings, destination / timings.name)
    manifest = source / "manifest.json"
    if manifest.is_file() and manifest.resolve() != (destination / manifest.name).resolve():
        shutil.copy2(manifest, destination / manifest.name)


def _prune_orphan_audio(audio_dir: Path, section_ids: set[str]) -> None:
    for mp3 in audio_dir.glob("*.mp3"):
        if mp3.stem not in section_ids:
            mp3.unlink()


def _pad_audio_for_sequence(
    manifest: dict[str, object],
    audio_dir: Path,
) -> dict[str, object]:
    """Keep the rendered segment alive through the resolved animation schedule."""
    entries: list[dict[str, object]] = []
    for slide in manifest.get("slides") or []:
        section_id = str(slide["id"])
        audio_path = audio_dir / f"{section_id}.mp3"
        minimum = round(float(slide.get("schedule_end") or 0.0) + 0.05, 3)
        before = probe_audio_duration(audio_path)
        padded = ensure_minimum_audio_duration(audio_path, minimum)
        after = probe_audio_duration(audio_path)
        if after is None or after + 0.02 < minimum:
            raise ProtocolError(
                f"audio {audio_path} ends at {after!r}s but the resolved animation "
                f"sequence requires at least {minimum:.3f}s"
            )
        entries.append(
            {
                "id": section_id,
                "schedule_end": slide.get("schedule_end"),
                "minimum_audio_seconds": minimum,
                "before_seconds": round(before, 3) if before is not None else None,
                "after_seconds": round(after, 3),
                "padded": padded,
            }
        )

    audio_manifest_path = audio_dir / "manifest.json"
    if audio_manifest_path.is_file():
        try:
            audio_manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProtocolError(f"could not refresh {audio_manifest_path}: {exc}") from exc
        by_id = {str(entry["id"]): entry for entry in entries}
        for item in audio_manifest:
            section_id = str(item.get("id") or "")
            if section_id not in by_id:
                continue
            item["bytes"] = (audio_dir / f"{section_id}.mp3").stat().st_size
            item["sequence_minimum_seconds"] = by_id[section_id]["minimum_audio_seconds"]
            item["sequence_padding_applied"] = by_id[section_id]["padded"]
        audio_manifest_path.write_text(
            json.dumps(audio_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "schema_version": "paper2video_animation_sequence_audio.v1",
        "slide_count": len(entries),
        "padded_count": sum(1 for entry in entries if entry["padded"]),
        "slides": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path, help="Edited PPTX source of truth")
    parser.add_argument("outdir", type=Path, help="Paper2Video v2 output bundle")
    parser.add_argument(
        "--ids-from-script",
        type=Path,
        default=None,
        help="Preserve existing semantic slide IDs while rebuilding narration from the PPTX protocol.",
    )
    parser.add_argument(
        "--script-json",
        type=Path,
        default=None,
        help=(
            "Use a user-edited script.json as narration authority. Section text replaces "
            "slide narration; optional per-section elements preserve precise handle timing."
        ),
    )
    parser.add_argument(
        "--baseline-pptx",
        type=Path,
        default=None,
        help="Previous editable PPTX used to identify which elements changed.",
    )
    parser.add_argument(
        "--narration-mode",
        choices=("keep", "regenerate"),
        default="keep",
        help="Keep PPTX narration, or regenerate narration only for changed elements.",
    )
    parser.add_argument(
        "--regeneration-model",
        default=DEFAULT_MODEL,
        help="OpenAI model used only with --narration-mode regenerate.",
    )
    parser.add_argument("--voice", default=None, help="Edge TTS voice")
    parser.add_argument("--rate", default="+0%", help="Edge TTS rate")
    parser.add_argument(
        "--prebuilt-audio-dir",
        type=Path,
        default=None,
        help="Offline/test mode: use matching MP3s and word_timings.json instead of calling Edge TTS.",
    )
    parser.add_argument("--resolution", choices=("720p", "1080p", "1440p", "4k"), default="1080p")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--start-pad", type=float, default=0.5)
    parser.add_argument("--pad-tail", type=float, default=0.3)
    parser.add_argument("--visual-cues", type=Path, default=None)
    parser.add_argument(
        "--visual-cue-plan",
        type=Path,
        default=None,
        help="Optional matching visual_cue_plan.json for an externally supplied --visual-cues file.",
    )
    parser.add_argument(
        "--highlight-style",
        default="spotlight_laser",
        choices=(
            "box", "spotlight", "cursor", "box_cursor", "spotlight_cursor",
            "laser", "box_laser", "spotlight_laser",
        ),
    )
    parser.add_argument("--no-subtitles", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument(
        "--no-qa",
        action="store_true",
        help="Debug only: skip the final strict package gate.",
    )
    args = parser.parse_args()

    source_pptx = args.pptx.resolve()
    outdir = args.outdir.resolve()
    if not source_pptx.is_file():
        sys.exit(f"[render_edited_pptx] PPTX not found: {source_pptx}")
    if outdir.exists():
        sys.exit(
            f"[render_edited_pptx] output bundle already exists; choose a fresh path: {outdir}"
        )
    if args.fps <= 0 or args.start_pad < 0 or args.pad_tail < 0:
        sys.exit("[render_edited_pptx] fps must be positive and padding must be non-negative")

    audio_dir = outdir / "assets" / "audio"
    captions_dir = outdir / "assets" / "captions"
    slides_dir = outdir / "assets" / "slides"
    clips_dir = outdir / "assets" / "clips"
    meta_dir = outdir / "assets" / "meta"
    reports_dir = meta_dir / "reports"
    frames_dir = slides_dir / "frames"
    for directory in (
        audio_dir,
        captions_dir,
        slides_dir,
        clips_dir,
        reports_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    script_path = audio_dir / "script.json"
    protocol_path = reports_dir / "editable_pptx_protocol.json"
    timings_path = audio_dir / "word_timings.json"
    animation_manifest_path = meta_dir / "animation_manifest.json"
    animation_report_path = reports_dir / "animation_render_report.json"
    author_cues_path = meta_dir / "editable_pptx_visual_cues.json"
    author_cue_plan_path = meta_dir / "editable_pptx_visual_cue_plan.json"
    duration_report_path = meta_dir / "video_duration_report.json"
    timeline_path = meta_dir / "timeline.json"
    raw_path = clips_dir / "video_raw.mp4"
    raw_delivery = outdir / "video_no_subtitles.mp4"
    final_path = outdir / "video.mp4"
    srt_path = captions_dir / "video.srt"
    vtt_path = captions_dir / "video.vtt"
    qa_path = reports_dir / "video_qa_report.json"
    authority_report_path = reports_dir / "author_notes_authority.json"
    script_authority_path = reports_dir / "script_authority.json"
    changes_report_path = reports_dir / "pptx_changes.json"
    regeneration_report_path = reports_dir / "narration_regeneration.json"
    sequence_audio_report_path = reports_dir / "animation_sequence_audio.json"
    protocol_writeback_path = reports_dir / "protocol_writeback.json"
    subtitle_timing_report_path = reports_dir / "subtitle_timing_alignment.json"
    delivered_pptx = outdir / "video.pptx"
    try:
        if args.narration_mode == "regenerate" and args.baseline_pptx is None:
            raise ProtocolError(
                "--narration-mode regenerate requires --baseline-pptx"
            )
        if args.narration_mode == "regenerate" and args.script_json is not None:
            raise ProtocolError(
                "--narration-mode regenerate and --script-json are mutually exclusive"
            )
        authority_report = normalize_author_notes_authority(source_pptx, delivered_pptx)
        write_json(authority_report_path, authority_report)
        protocol = extract_protocol(
            delivered_pptx,
            ids_from_script=args.ids_from_script or args.script_json,
        )
        change_report = None
        if args.baseline_pptx is not None:
            baseline_pptx = args.baseline_pptx.resolve()
            if not baseline_pptx.is_file():
                raise ProtocolError(f"baseline PPTX not found: {baseline_pptx}")
            change_report = detect_pptx_changes(baseline_pptx, delivered_pptx)
            write_json(changes_report_path, change_report)
        if args.narration_mode == "regenerate":
            assert change_report is not None
            protocol, regeneration_report = regenerate_changed_narration(
                protocol,
                change_report,
                model=args.regeneration_model,
            )
            write_json(regeneration_report_path, regeneration_report)
            write_protocol_to_pptx(delivered_pptx, protocol, delivered_pptx)
            protocol = extract_protocol(
                delivered_pptx,
                ids_from_script=args.ids_from_script,
            )
            script_authority = {
                "schema_version": "paper2video_user_script_authority.v1",
                "script_json": None,
                "resolution": "llm_regeneration",
                "model": args.regeneration_model,
                "changed_target_count": regeneration_report["target_count"],
                "updated_count": regeneration_report["updated_count"],
                "slide_count": protocol["slide_count"],
            }
        if args.script_json is not None:
            protocol, script_authority = apply_user_script(protocol, args.script_json)
            write_protocol_to_pptx(delivered_pptx, protocol, delivered_pptx)
            protocol = extract_protocol(delivered_pptx, ids_from_script=args.script_json)
        elif args.narration_mode == "keep":
            script_authority = {
                "schema_version": "paper2video_user_script_authority.v1",
                "script_json": None,
                "resolution": "pptx_protocol",
                "script_sources": protocol.get("script_sources") or [],
                "slide_count": protocol["slide_count"],
                "baseline_pptx": (
                    str(args.baseline_pptx.resolve()) if args.baseline_pptx else None
                ),
                "detected_change_count": (
                    int(change_report["change_count"]) if change_report else None
                ),
            }
        protocol_writeback = write_protocol_to_pptx(
            delivered_pptx,
            protocol,
            delivered_pptx,
        )
        write_json(protocol_writeback_path, protocol_writeback)
        protocol = extract_protocol(
            delivered_pptx,
            ids_from_script=args.ids_from_script or args.script_json,
        )
        script = script_from_protocol(protocol, voice=args.voice)
    except (OSError, ProtocolError) as exc:
        sys.exit(f"[render_edited_pptx] PPTX protocol reconciliation failed: {exc}")
    write_json(script_path, script)
    write_json(protocol_path, protocol)
    write_json(script_authority_path, script_authority)
    section_ids = [str(section["id"]) for section in script["sections"]]
    has_narration = any(str(section.get("text") or "").strip() for section in script["sections"])
    effective_no_subtitles = args.no_subtitles or not has_narration
    _prune_orphan_audio(audio_dir, set(section_ids))

    try:
        if args.prebuilt_audio_dir is not None:
            _copy_audio_bundle(args.prebuilt_audio_dir, audio_dir, section_ids)
        else:
            tts_command = [
                sys.executable,
                str(SCRIPT_DIR / "generate_edge_audio.py"),
                str(script_path),
                "--outdir",
                str(audio_dir),
                "--rate",
                args.rate,
                "--timings-out",
                str(timings_path),
            ]
            if args.voice:
                tts_command.extend(["--voice", args.voice])
            _run(tts_command)

        manifest = build_pptx_animation_manifest(protocol, timings_path)
        write_json(animation_manifest_path, manifest)
        author_cues = build_pptx_visual_cues(protocol, timings_path)
        write_json(author_cues_path, author_cues)
        author_cue_plan = build_pptx_visual_cue_plan(author_cues)
        write_json(author_cue_plan_path, author_cue_plan)
        write_json(
            sequence_audio_report_path,
            _pad_audio_for_sequence(manifest, audio_dir),
        )
    except (OSError, ProtocolError, subprocess.CalledProcessError) as exc:
        sys.exit(f"[render_edited_pptx] audio/manifest stage failed: {exc}")

    render_command = [
        sys.executable,
        str(SCRIPT_DIR / "render_video.py"),
        str(outdir),
        "--pptx",
        str(delivered_pptx),
        "--audio-dir",
        str(audio_dir),
        "--script-json",
        str(script_path),
        "--frame-source",
        "pptx",
        "--animation-source",
        "pptx",
        "--animation-manifest",
        str(animation_manifest_path),
        "--animation-report-out",
        str(animation_report_path),
        "--duration-report-out",
        str(duration_report_path),
        "--resolution",
        args.resolution,
        "--fps",
        str(args.fps),
        "--start-pad",
        str(args.start_pad),
        "--pad-tail",
        str(args.pad_tail),
        "--frames-out",
        str(frames_dir),
        "--out",
        str(raw_path),
    ]
    if int(manifest.get("effect_count") or 0) > 0:
        render_command.append("--require-animations")
    effective_visual_cues = (
        args.visual_cues.resolve()
        if args.visual_cues is not None
        else (author_cues_path if int(author_cues.get("cue_count") or 0) else None)
    )
    using_native_emphasis_cues = (
        args.visual_cues is None and effective_visual_cues == author_cues_path
    )
    effective_cue_plan = (
        args.visual_cue_plan.resolve()
        if args.visual_cue_plan is not None
        else (author_cue_plan_path if using_native_emphasis_cues else None)
    )
    if args.visual_cue_plan is not None and args.visual_cues is None:
        sys.exit("[render_edited_pptx] --visual-cue-plan requires --visual-cues")
    if effective_visual_cues is not None:
        render_command.extend(
            [
                "--attention-mode",
                "highlight",
                "--highlight-style",
                args.highlight_style,
                "--visual-cues",
                str(effective_visual_cues),
            ]
        )
    else:
        render_command.extend(["--attention-mode", "none"])
    if args.keep_temp:
        render_command.append("--keep-temp")

    try:
        _run(render_command)
        shutil.copy2(raw_path, raw_delivery)
        subtitle_command = [
            sys.executable,
            str(SCRIPT_DIR / "add_subtitles.py"),
            str(outdir),
            "--mp4",
            str(raw_path),
            "--audio-dir",
            str(audio_dir),
            "--script-json",
            str(script_path),
            "--word-timings",
            str(timings_path),
            "--require-word-timings",
            "--timing-report-out",
            str(subtitle_timing_report_path),
            "--start-pad",
            str(args.start_pad),
            "--pad-tail",
            str(args.pad_tail),
            "--srt-out",
            str(srt_path),
            "--vtt-out",
            str(vtt_path),
            "--out",
            str(final_path),
        ]
        if effective_no_subtitles:
            subtitle_command.append("--no-subtitles")
        _run(subtitle_command)
        shutil.copy2(delivered_pptx, slides_dir / "slides.pptx")

        timeline_command = [
            sys.executable,
            str(SCRIPT_DIR / "build_timeline.py"),
            "--script-json",
            str(script_path),
            "--duration-report",
            str(duration_report_path),
            "--captions-vtt",
            str(vtt_path),
            "--audio-dir",
            str(audio_dir),
            "--video",
            str(raw_delivery),
            "--out",
            str(timeline_path),
        ]
        if effective_visual_cues is not None:
            timeline_command.extend(["--visual-cues", str(effective_visual_cues)])
        if effective_cue_plan is not None:
            timeline_command.extend(["--visual-cue-plan", str(effective_cue_plan)])
        _run(timeline_command)
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"[render_edited_pptx] render stage failed: {exc}")

    if not args.no_qa:
        qa_command = [
            sys.executable,
            str(SCRIPT_DIR / "check_video_package.py"),
            str(outdir),
            "--pptx",
            str(outdir / "video.pptx"),
            "--script-json",
            str(script_path),
            "--audio-dir",
            str(audio_dir),
            "--frames-dir",
            str(frames_dir),
            "--mp4",
            str(final_path),
            "--raw-mp4",
            str(raw_delivery),
            "--subtitle-file",
            str(vtt_path),
            "--subtitle-timing-report",
            str(subtitle_timing_report_path),
            "--animation-manifest",
            str(animation_manifest_path),
            "--animation-report",
            str(animation_report_path),
            "--timeline",
            str(timeline_path),
            "--require-word-timings",
            "--require-timeline",
            "--strict",
            "--out",
            str(qa_path),
        ]
        if int(manifest.get("effect_count") or 0) > 0:
            qa_command.append("--require-animations")
        if not effective_no_subtitles:
            qa_command.extend(
                ["--require-subtitles", "--require-subtitle-word-alignment"]
            )
        if effective_visual_cues is not None:
            qa_command.extend(
                [
                    "--visual-cues",
                    str(effective_visual_cues),
                ]
            )
        if effective_cue_plan is not None:
            qa_command.extend(["--cue-plan", str(effective_cue_plan)])
        if args.visual_cues is not None and effective_cue_plan is not None:
            qa_command.extend(
                ["--strict-attention", "--require-visual-cues", "--require-cue-plan"]
            )
        else:
            # Native emphasis is optional. It is still rendered and audited
            # when present, but an editable deck is not required to spotlight
            # every narration chunk merely to pass media/protocol QA.
            qa_command.append("--allow-missing-attention")
        try:
            _run(qa_command)
        except subprocess.CalledProcessError as exc:
            sys.exit(f"[render_edited_pptx] strict QA failed with exit {exc.returncode}")

    print(
        f"[render_edited_pptx] DONE: {final_path} "
        f"({protocol['slide_count']} slides, {protocol['effect_count']} effects)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
