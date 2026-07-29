#!/usr/bin/env python3
"""Bootstrap a paper2reel bundle from a PDF or an incomplete v2 bundle.

This script is intentionally conservative. It can refresh deterministic
paper2assets package metadata and it can assemble a reel once poster, blog, and
video deliverables already exist. It does not fabricate missing poster, blog,
or video artifacts; those stages remain full skill workflows.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reel_downloads import (
    DOWNLOAD_MANIFEST_PATH,
    build_download_manifest,
    validate_download_manifest,
    write_download_manifest,
)


STATUS_PASS = "PASS"
STATUS_MISSING = "MISSING"
STATUS_BLOCKED = "BLOCKED"
STATUS_RAN = "RAN"

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "skills" / "paper2reel" / "scripts"
PAPER2ASSETS_BUILD = REPO_ROOT / "skills" / "paper2assets" / "scripts" / "build_package.py"
BUILD_VIEWER = SCRIPTS_DIR / "build_poster_slides_view.py"
BUILD_MEDIA = SCRIPTS_DIR / "build_section_media_from_timeline.py"
CHECK_REEL = SCRIPTS_DIR / "check_reel_package.py"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}


@dataclass
class StageStatus:
    name: str
    status: str
    missing: list[str] = field(default_factory=list)
    message: str = ""
    commands: list[list[str]] = field(default_factory=list)
    auto_runnable: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def has_file(bundle_dir: Path, rel_path: str) -> bool:
    return (bundle_dir / rel_path).is_file()


def missing_files(bundle_dir: Path, rel_paths: list[str]) -> list[str]:
    return [p for p in rel_paths if not has_file(bundle_dir, p)]


def list_images(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def default_bundle_dir(source: Path) -> Path:
    if source.is_dir():
        return source.resolve()
    return (source.parent / source.stem).resolve()


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_pdf_from_manifest(bundle_dir: Path) -> Path | None:
    manifest = load_json(bundle_dir / "manifest.json", {})
    if not isinstance(manifest, dict):
        return None
    source = manifest.get("source")
    if not isinstance(source, dict):
        return None
    pdf = source.get("pdf")
    if not isinstance(pdf, str) or not pdf:
        return None
    path = Path(pdf)
    if not path.is_absolute():
        path = bundle_dir / path
    return path.resolve() if path.is_file() else None


def resolve_input(input_arg: str, bundle_arg: Path | None, pdf_arg: Path | None) -> tuple[Path, Path | None]:
    raw = input_arg.strip()
    if raw.startswith(("http://", "https://")):
        if bundle_arg is None:
            raise SystemExit("URL input requires --bundle-dir so existing outputs can be inspected.")
        return bundle_arg.resolve(), pdf_arg.resolve() if pdf_arg else None

    source = Path(raw).expanduser().resolve()
    if source.is_dir():
        bundle_dir = (bundle_arg or source).resolve()
        source_pdf = pdf_arg.resolve() if pdf_arg else source_pdf_from_manifest(bundle_dir)
        return bundle_dir, source_pdf
    if source.suffix.lower() != ".pdf":
        raise SystemExit(f"Input must be a PDF, URL, or bundle directory: {source}")
    if not source.is_file():
        raise SystemExit(f"PDF not found: {source}")
    return (bundle_arg.resolve() if bundle_arg else default_bundle_dir(source)), source


def assets_status(bundle_dir: Path, source_pdf: Path | None, python_exe: str) -> StageStatus:
    core = [
        "assets/meta/paper_spec.md",
        "assets/meta/text.txt",
        "assets/meta/figures.json",
        "assets/meta/metadata.json",
    ]
    derived = [
        "manifest.json",
        "assets/meta/sections.json",
        "assets/meta/narration.json",
    ]
    missing_core = missing_files(bundle_dir, core)
    missing_derived = missing_files(bundle_dir, derived)
    if not missing_core and not missing_derived:
        return StageStatus("paper2assets", STATUS_PASS)
    if not missing_core and missing_derived:
        cmd = [
            python_exe,
            str(PAPER2ASSETS_BUILD),
            str(source_pdf) if source_pdf else "<source.pdf>",
            "--outdir",
            str(bundle_dir),
            "--skip-extract",
            "--paper-spec",
            str(bundle_dir / "assets" / "meta" / "paper_spec.md"),
        ]
        return StageStatus(
            "paper2assets",
            STATUS_MISSING,
            missing=missing_derived,
            message="Only derived package metadata is missing; it can be refreshed from the existing paper_spec.md.",
            commands=[cmd],
            auto_runnable=source_pdf is not None,
        )
    return StageStatus(
        "paper2assets",
        STATUS_BLOCKED,
        missing=missing_core + missing_derived,
        message=(
            "Full paper2assets is missing model-driven outputs. Run the complete paper2assets skill first; "
            "do not substitute extract_pdf.py output for paper_spec.md."
        ),
    )


def poster_status(bundle_dir: Path) -> StageStatus:
    required = ["poster.html", "poster.pdf", "poster.png", "poster.pptx"]
    missing = missing_files(bundle_dir, required)
    if not missing:
        return StageStatus("paper2poster", STATUS_PASS)
    return StageStatus(
        "paper2poster",
        STATUS_BLOCKED,
        missing=missing,
        message="Run the complete paper2poster skill on the paper2assets bundle; do not create a simplified poster.",
    )


def blog_status(bundle_dir: Path) -> StageStatus:
    required = [
        "blog_zh.docx",
        "blog_en.docx",
        "assets/meta/outline_zh.json",
        "assets/meta/outline_en.json",
    ]
    missing = missing_files(bundle_dir, required)
    if not missing:
        return StageStatus("paper2blog", STATUS_PASS)
    return StageStatus(
        "paper2blog",
        STATUS_BLOCKED,
        missing=missing,
        message="Run the complete bilingual paper2blog skill; reel modals require the real EN/CN outlines and DOCX outputs.",
    )


def resolve_slides_dir(bundle_dir: Path) -> Path | None:
    candidates = [
        bundle_dir / "assets" / "slides" / "frames",
        bundle_dir / "assets" / "slides",
    ]
    for candidate in candidates:
        if list_images(candidate):
            return candidate
    return None


def video_status(bundle_dir: Path) -> StageStatus:
    required = [
        "video.mp4",
        "video_no_subtitles.mp4",
        "video.pptx",
        "assets/audio/script.json",
        "assets/meta/timeline.json",
        "assets/captions/video.vtt",
    ]
    missing = missing_files(bundle_dir, required)
    if resolve_slides_dir(bundle_dir) is None:
        missing.append("assets/slides/frames/*.png")
    if not missing:
        return StageStatus("paper2video", STATUS_PASS)
    return StageStatus(
        "paper2video",
        STATUS_BLOCKED,
        missing=missing,
        message="Run the complete paper2video skill, including ppt-master, timeline, captions, audio, highlights, and video gates.",
    )


def reel_status(bundle_dir: Path) -> StageStatus:
    required = [
        "reel.html",
        "content_alignment.json",
        "assets/poster/poster.html",
        "assets/media/video.mp4",
    ]
    missing = missing_files(bundle_dir, required)
    clips_dir = bundle_dir / "assets" / "media" / "clips"
    if not clips_dir.is_dir() or not any(clips_dir.glob("*.mp4")):
        missing.append("assets/media/clips/*.mp4")
    if not missing:
        return StageStatus("paper2reel", STATUS_PASS)
    return StageStatus(
        "paper2reel",
        STATUS_MISSING,
        missing=missing,
        message="Reel can be assembled once paper2poster, paper2blog, and paper2video are complete.",
        auto_runnable=True,
    )


def collect_statuses(
    bundle_dir: Path,
    source_pdf: Path | None,
    python_exe: str,
    *,
    reel_dir: Path | None = None,
) -> list[StageStatus]:
    reel_root = reel_dir or bundle_dir
    return [
        assets_status(bundle_dir, source_pdf, python_exe),
        poster_status(bundle_dir),
        blog_status(bundle_dir),
        video_status(bundle_dir),
        reel_status(reel_root),
    ]


def run_cmd(cmd: list[str], *, dry_run: bool) -> None:
    print("+ " + " ".join(cmd), flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def refresh_assets(bundle_dir: Path, source_pdf: Path, python_exe: str, *, dry_run: bool) -> None:
    cmd = [
        python_exe,
        str(PAPER2ASSETS_BUILD),
        str(source_pdf),
        "--outdir",
        str(bundle_dir),
        "--skip-extract",
        "--paper-spec",
        str(bundle_dir / "assets" / "meta" / "paper_spec.md"),
    ]
    run_cmd(cmd, dry_run=dry_run)


def build_viewer_command(
    bundle_dir: Path,
    staging_dir: Path,
    slides_dir: Path,
    python_exe: str,
    download_mode: str = "materialized",
) -> list[str]:
    cmd = [
        python_exe,
        str(BUILD_VIEWER),
        "--poster-dir",
        str(bundle_dir),
        "--slides-dir",
        str(slides_dir),
        "--outdir",
        str(staging_dir),
        "--download-mode",
        download_mode,
    ]
    optional_pairs = [
        ("--script-json", bundle_dir / "assets" / "audio" / "script.json"),
        ("--blog-outline-en", bundle_dir / "assets" / "meta" / "outline_en.json"),
        ("--blog-outline-zh", bundle_dir / "assets" / "meta" / "outline_zh.json"),
        ("--blog-figures-dir", bundle_dir / "assets" / "figures"),
        ("--download-poster-dir", bundle_dir),
        ("--download-blog-dir", bundle_dir),
        ("--download-video-dir", bundle_dir),
    ]
    for flag, path in optional_pairs:
        if path.exists():
            cmd.extend([flag, str(path)])
    return cmd


def resolve_executable(value: str) -> str | None:
    path = Path(value)
    if path.parent != Path("."):
        return str(path.resolve()) if path.is_file() else None
    return shutil.which(value)


def build_media_command(
    bundle_dir: Path,
    staging_dir: Path,
    python_exe: str,
    section_tail_seconds: float,
    ffmpeg: str,
) -> list[str]:
    return [
        python_exe,
        str(BUILD_MEDIA),
        "--viewer-dir",
        str(staging_dir),
        "--timeline",
        str(bundle_dir / "assets" / "meta" / "timeline.json"),
        "--video",
        str(bundle_dir / "video_no_subtitles.mp4"),
        "--captions-vtt",
        str(bundle_dir / "assets" / "captions" / "video.vtt"),
        "--section-tail-seconds",
        str(section_tail_seconds),
        "--ffmpeg",
        ffmpeg,
    ]


def remove_slide_frames(slides_dir: Path) -> None:
    if not slides_dir.is_dir():
        return
    for path in slides_dir.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stem.startswith("slide_"):
            path.unlink()


def copytree_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)


def sync_reel_into_bundle(
    staging_dir: Path,
    target_dir: Path,
    *,
    download_mode: str = "materialized",
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging_dir / "reel.html", target_dir / "reel.html")
    shutil.copy2(staging_dir / "content_alignment.json", target_dir / "content_alignment.json")

    stage_assets = staging_dir / "assets"
    target_assets = target_dir / "assets"
    target_assets.mkdir(parents=True, exist_ok=True)

    for name in ("poster", "media", "blog", "ui"):
        copytree_replace(stage_assets / name, target_assets / name)
    target_downloads = target_assets / "downloads"
    if download_mode == "materialized":
        copytree_replace(stage_assets / "downloads", target_downloads)
    elif target_downloads.exists():
        # Reclaim historical ZIPs when publishing an on-demand Reel.
        shutil.rmtree(target_downloads)

    stage_slides = stage_assets / "slides"
    target_slides = target_assets / "slides"
    target_slides.mkdir(parents=True, exist_ok=True)
    remove_slide_frames(target_slides)
    if stage_slides.is_dir():
        for src in stage_slides.iterdir():
            if src.is_file():
                shutil.copy2(src, target_slides / src.name)

    meta_dir = target_assets / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging_dir / "manifest.json", meta_dir / "reel_manifest.json")
    if download_mode == "materialized":
        shutil.copy2(
            staging_dir / DOWNLOAD_MANIFEST_PATH,
            target_dir / DOWNLOAD_MANIFEST_PATH,
        )
    else:
        download_manifest = build_download_manifest(
            bundle_root=target_dir,
            poster_source=target_dir,
            video_source=target_dir,
            blog_source=target_dir,
            delivery="on_demand",
        )
        issues = validate_download_manifest(
            download_manifest,
            bundle_root=target_dir,
            require_sources=True,
        )
        if issues:
            first = issues[0]
            raise SystemExit(
                "Cannot publish on-demand Reel downloads: "
                f"{first['code']}: {first['message']}"
            )
        write_download_manifest(target_dir / DOWNLOAD_MANIFEST_PATH, download_manifest)

    manifest_path = target_dir / "manifest.json"
    manifest = load_json(manifest_path, {})
    if not isinstance(manifest, dict):
        manifest = {}
    manifest.setdefault("layout", "v2-assets")
    files = manifest.setdefault("files", {})
    if isinstance(files, dict):
        files["reel"] = {
            "html": "reel.html",
            "alignment": "content_alignment.json",
            "manifest": "assets/meta/reel_manifest.json",
            "poster_dir": "assets/poster",
            "media_dir": "assets/media",
            "slides_dir": "assets/slides",
            "blog_dir": "assets/blog",
            "downloads_manifest": DOWNLOAD_MANIFEST_PATH.as_posix(),
            "ui_dir": "assets/ui",
        }
        if download_mode == "materialized":
            files["reel"]["downloads_dir"] = "assets/downloads"
    reel_manifest = load_json(staging_dir / "manifest.json", {})
    if isinstance(reel_manifest, dict) and isinstance(reel_manifest.get("local_open"), dict):
        manifest["reel_local_open"] = reel_manifest["local_open"]
    manifest["updated_at"] = utc_now()
    write_json(manifest_path, manifest)


def build_reel(
    bundle_dir: Path,
    target_dir: Path,
    python_exe: str,
    *,
    dry_run: bool,
    browser: bool,
    section_tail_seconds: float,
    keep_staging: bool,
    ffmpeg: str,
    download_mode: str = "materialized",
) -> None:
    slides_dir = resolve_slides_dir(bundle_dir)
    if slides_dir is None:
        raise SystemExit("Cannot build reel: no slide frames found under assets/slides/frames or assets/slides.")
    resolved_ffmpeg = resolve_executable(ffmpeg)
    if resolved_ffmpeg is None and not dry_run:
        raise SystemExit(
            "Cannot build reel section media: ffmpeg was not found. Install ffmpeg or pass --ffmpeg /path/to/ffmpeg."
        )

    with tempfile.TemporaryDirectory(prefix="paper2reel-build-") as tmp:
        staging_dir = Path(tmp) / "reel"
        run_cmd(
            build_viewer_command(
                bundle_dir,
                staging_dir,
                slides_dir,
                python_exe,
                download_mode,
            ),
            dry_run=dry_run,
        )
        run_cmd(
            build_media_command(
                bundle_dir,
                staging_dir,
                python_exe,
                section_tail_seconds,
                resolved_ffmpeg or ffmpeg,
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return
        sync_reel_into_bundle(
            staging_dir,
            target_dir,
            download_mode=download_mode,
        )
        if keep_staging:
            keep_dir = target_dir / "assets" / "meta" / "reel_build_staging"
            copytree_replace(staging_dir, keep_dir)

    report = target_dir / "assets" / "meta" / "reports" / "reel_qa_report.json"
    screenshot = target_dir / "assets" / "meta" / "previews" / "reel_browser_gate.png"
    cmd = [
        python_exe,
        str(CHECK_REEL),
        str(target_dir),
        "--report",
        str(report),
        "--screenshot",
        str(screenshot),
    ]
    if browser:
        cmd.append("--browser")
        cmd.append("--file-browser")
    run_cmd(cmd, dry_run=dry_run)


def make_report(
    *,
    bundle_dir: Path,
    source_pdf: Path | None,
    target_dir: Path,
    statuses: list[StageStatus],
) -> dict[str, Any]:
    return {
        "schema_version": "paper2reel_bootstrap.v1",
        "created_at": utc_now(),
        "bundle_dir": str(bundle_dir),
        "source_pdf": str(source_pdf) if source_pdf else None,
        "reel_outdir": str(target_dir),
        "stages": [asdict(status) for status in statuses],
    }


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Source PDF, URL, or existing v2 bundle directory.")
    parser.add_argument("--bundle-dir", type=Path, help="Existing or desired shared paper bundle directory.")
    parser.add_argument("--pdf", type=Path, help="Source PDF when input is a bundle directory.")
    parser.add_argument("--reel-outdir", type=Path, help="Where to write reel.html. Defaults to the shared bundle root.")
    parser.add_argument("--run-missing", action="store_true", help="Run safe automatic repairs and build reel when prerequisites pass.")
    parser.add_argument("--force-reel", action="store_true", help="Rebuild reel even if existing reel outputs are present.")
    parser.add_argument("--dry-run", action="store_true", help="Only report missing stages and commands.")
    parser.add_argument("--json-out", type=Path, help="Write a bootstrap status report.")
    parser.add_argument("--no-browser", action="store_true", help="Skip Playwright browser gate when checking the rebuilt reel.")
    parser.add_argument("--section-tail-seconds", type=float, default=0.9)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable for timeline-backed section media.")
    parser.add_argument("--keep-staging", action="store_true", help="Copy the temporary reel staging bundle into assets/meta for debugging.")
    parser.add_argument(
        "--download-mode",
        choices=("materialized", "on_demand"),
        default="materialized",
        help=(
            "materialized keeps standalone ZIP downloads; on_demand publishes "
            "only the validated download manifest for the dynamic endpoint"
        ),
    )
    parser.add_argument("--python", default=sys.executable, help="Python interpreter for child scripts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle_dir, source_pdf = resolve_input(args.input, args.bundle_dir, args.pdf)
    target_dir = (args.reel_outdir.resolve() if args.reel_outdir else bundle_dir).resolve()

    statuses = collect_statuses(bundle_dir, source_pdf, args.python, reel_dir=target_dir)
    initial_report = make_report(bundle_dir=bundle_dir, source_pdf=source_pdf, target_dir=target_dir, statuses=statuses)
    print_report(initial_report)

    if args.json_out:
        write_json(args.json_out.resolve(), initial_report)

    if not args.run_missing:
        blocked = any(s.status == STATUS_BLOCKED for s in statuses)
        missing = any(s.status == STATUS_MISSING for s in statuses)
        if blocked or missing:
            print("[paper2reel/bootstrap] dry status only; pass --run-missing to execute safe automatic steps.")
        return 0

    assets = next(s for s in statuses if s.name == "paper2assets")
    if assets.status == STATUS_MISSING and assets.auto_runnable:
        if source_pdf is None:
            raise SystemExit("Cannot refresh paper2assets metadata without a source PDF.")
        refresh_assets(bundle_dir, source_pdf, args.python, dry_run=args.dry_run)
        statuses = collect_statuses(bundle_dir, source_pdf, args.python, reel_dir=target_dir)

    blocked = [s for s in statuses if s.status == STATUS_BLOCKED]
    if blocked:
        report = make_report(bundle_dir=bundle_dir, source_pdf=source_pdf, target_dir=target_dir, statuses=statuses)
        if args.json_out:
            write_json(args.json_out.resolve(), report)
        print("[paper2reel/bootstrap] blocked; complete the listed full skill stages before building reel.", file=sys.stderr)
        return 2

    reel = next(s for s in statuses if s.name == "paper2reel")
    if reel.status != STATUS_PASS or args.force_reel:
        build_reel(
            bundle_dir,
            target_dir,
            args.python,
            dry_run=args.dry_run,
            browser=not args.no_browser,
            section_tail_seconds=args.section_tail_seconds,
            keep_staging=args.keep_staging,
            ffmpeg=args.ffmpeg,
            download_mode=args.download_mode,
        )
        statuses = collect_statuses(bundle_dir, source_pdf, args.python, reel_dir=target_dir)
        for status in statuses:
            if status.name == "paper2reel" and status.status == STATUS_PASS:
                status.status = STATUS_RAN

    final_report = make_report(bundle_dir=bundle_dir, source_pdf=source_pdf, target_dir=target_dir, statuses=statuses)
    if args.json_out:
        write_json(args.json_out.resolve(), final_report)
    print_report(final_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
