#!/usr/bin/env python3
"""Hard gate for paper2reel final packages.

The checker validates the section-modal reel contract. It is strict on
purpose: a bundle with a stale tabbed viewer, missing section clips, or broken
modal interaction must fail before delivery.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "paper2reel_qa.v1"
SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from serve_reel import RangeRequestHandler, ThreadedRangeHTTPServer  # noqa: E402
from reel_downloads import (  # noqa: E402
    ARCHIVE_META,
    ARCHIVE_ORDER,
    DOWNLOAD_MANIFEST_PATH,
    validate_download_manifest,
)

DEFAULT_CONTRACT_PATH = SKILL_DIR / "assets" / "section_modal_contract.json"
DOWNLOAD_ARCHIVES = {
    "poster": "poster_final.zip",
    "video": "video_final.zip",
    "blog": "blog_final.zip",
    "all": "all_final.zip",
}
DOWNLOAD_PROHIBITED_FILES = {
    "poster": {"video.mp4", "video.pptx", "blog_en.docx", "blog_zh.docx"},
    "video": {
        "poster.html",
        "poster.png",
        "poster.pdf",
        "poster.pptx",
        "blog_en.docx",
        "blog_zh.docx",
    },
    "blog": {
        "poster.html",
        "poster.png",
        "poster.pdf",
        "poster.pptx",
        "video.mp4",
        "video.pptx",
    },
}


DEFAULT_CONTRACT = {
    "viewer_version": "section_modal.v2",
    "template_version": "attention_golden_section_modal.v1",
    "required_html_markers": {
        "poster iframe": 'id="posterFrame"',
        "modal overlay": 'id="overlay"',
        "section video": 'id="sectionVideo"',
        "caption toggle": 'id="captionToggle"',
        "download links": 'id="downloadLinks"',
        "top help button": 'id="helpTopBtn"',
        "reel wordmark": 'class="brand-mark"',
        "download icon": 'class="download-icon"',
        "download link style": 'class="download-link"',
        "download separators": 'class="download-sep"',
        "section rail tab min width": "min-width:68px",
        "section rail tab index": "className = 'section-index'",
        "section rail active underline": ".section-rail button.active::after",
        "double-click tooltip": "Double Click to Open",
        "local-open poster embed": "const POSTER_HTML =",
        "local-open runtime switch": "shouldUseLocalOpenRuntime",
        "local-open on-demand guard": "onDemand && window.location.protocol === 'file:'",
    },
    "forbidden_html_markers": {
        "old poster tab": 'id="posterTab"',
        "old slides tab": 'id="slidesTab"',
        "old video tab": 'id="videoTab"',
        "old blog tab": 'id="blogTab"',
        "old tab strip": 'class="mode-tabs"',
    },
    "required_download_labels": ["All", "Poster", "Video", "Blog"],
    "required_poster_debug_markers": ["window.__togglePosterDebug", "body.debug", "dbg-bbox"],
    "required_output_paths": [
        "reel.html",
        "content_alignment.json",
        "manifest.json",
        "assets/poster/poster.html",
        "assets/ui/reel-wordmark.png",
        "assets/meta/reel_downloads.json",
    ],
    "required_media_subdirs": ["assets/media/clips", "assets/media/captions", "assets/media/slide_clips"],
    "min_blog_text_chars": 80,
    "min_download_buttons": 4,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_json(path: Path, findings: list[dict[str, Any]], root: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        add_finding(findings, "ERROR", "ALIGNMENT_JSON_MISSING", "content_alignment.json is missing.", path=rel(path, root))
    except json.JSONDecodeError as exc:
        add_finding(findings, "ERROR", "ALIGNMENT_JSON_INVALID", f"content_alignment.json is invalid JSON: {exc}", path=rel(path, root))
    return None


def load_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = path or DEFAULT_CONTRACT_PATH
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULT_CONTRACT)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[check_reel_package] invalid contract JSON {contract_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"[check_reel_package] contract must be a JSON object: {contract_path}")
    merged = dict(DEFAULT_CONTRACT)
    merged.update(payload)
    return merged


def add_finding(
    findings: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    path: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    findings.append({
        "severity": severity,
        "code": code,
        "message": message,
        "location": path,
        "data": data or {},
    })


def file_exists(findings: list[dict[str, Any]], path: Path, root: Path, code: str, message: str) -> bool:
    if path.is_file():
        return True
    add_finding(findings, "ERROR", code, message, path=rel(path, root))
    return False


def path_exists(path: Path) -> bool:
    return path.exists() or path.is_dir() or path.is_file()


def validate_no_local_paths(findings: list[dict[str, Any]], text: str, *, path: str) -> None:
    forbidden_patterns = [
        "file:///",
        "file:/Users/",
        "/Users/",
        "/mnt/",
        "/home/",
        "/tmp/",
    ]
    for pattern in forbidden_patterns:
        if pattern in text:
            add_finding(
                findings,
                "ERROR",
                "LOCAL_PATH_LEAK",
                "Reel package contains a local or machine-specific path; final viewer must be self-contained.",
                path=path,
                data={"pattern": pattern},
            )
            return


def validate_no_backup_files(findings: list[dict[str, Any]], viewer_dir: Path) -> None:
    scan_roots = [
        viewer_dir / "reel.html",
        viewer_dir / "content_alignment.json",
        viewer_dir / "assets" / "poster",
        viewer_dir / "assets" / "media",
        viewer_dir / "assets" / "blog",
        viewer_dir / "assets" / "slides",
        viewer_dir / "assets" / "downloads",
    ]
    paths: list[Path] = []
    for root in scan_roots:
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(sorted(root.rglob("*")))
    for path in paths:
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if lowered.endswith((".bak", ".backup")) or ".bak." in lowered:
            add_finding(
                findings,
                "ERROR",
                "BACKUP_FILE_IN_PACKAGE",
                "Reel package must not include backup or patch scratch files.",
                path=rel(path, viewer_dir),
            )


def is_backup_archive_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".bak", ".backup")) or ".bak." in lowered


def archive_internal_names(names: list[str]) -> list[str]:
    internal: list[str] = []
    for name in names:
        archive_path = PurePosixPath(name.replace("\\", "/"))
        parts = archive_path.parts
        contains_downloads = any(
            parts[index:index + 2] == ("assets", "downloads")
            for index in range(max(0, len(parts) - 1))
        )
        if (
            archive_path.is_absolute()
            or ".." in parts
            or ".claude" in parts
            or contains_downloads
            or any(is_backup_archive_name(part) for part in parts)
        ):
            internal.append(name)
    return internal


def archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_download_archives(
    findings: list[dict[str, Any]],
    viewer_dir: Path,
) -> None:
    """Validate the four user-facing archives produced by paper2reel."""
    downloads_dir = viewer_dir / "assets" / "downloads"
    paths = {
        module: downloads_dir / filename
        for module, filename in DOWNLOAD_ARCHIVES.items()
    }
    names: dict[str, set[str]] = {}
    valid_paths: dict[str, Path] = {}
    for module, path in paths.items():
        if not path.is_file():
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ARCHIVE_MISSING",
                "A required Reel download archive is missing.",
                path=rel(path, viewer_dir),
                data={"module": module},
            )
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                archive_names = archive.namelist()
                bad_file = archive.testzip()
                if bad_file:
                    raise zipfile.BadZipFile(f"CRC failure in {bad_file}")
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ARCHIVE_INVALID",
                "A Reel download archive is unreadable or corrupt.",
                path=rel(path, viewer_dir),
                data={"module": module, "error": str(exc)},
            )
            continue

        if len(archive_names) != len(set(archive_names)):
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ARCHIVE_DUPLICATE_PATH",
                "A Reel download archive contains duplicate paths.",
                path=rel(path, viewer_dir),
                data={"module": module},
            )
        internal = archive_internal_names(archive_names)
        if internal:
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ARCHIVE_INTERNAL_FILE",
                "A Reel download archive contains internal, backup, or nested download files.",
                path=rel(path, viewer_dir),
                data={"module": module, "files": internal[:20]},
            )
        names[module] = set(archive_names)
        valid_paths[module] = path

    module_names = ("poster", "video", "blog")
    if all(module in valid_paths for module in module_names):
        hashes = [archive_sha256(valid_paths[module]) for module in module_names]
        if len(set(hashes)) != len(hashes):
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_MODULE_ARCHIVES_IDENTICAL",
                "Poster, Video, and Blog archives must contain separate module deliverables.",
                path=rel(downloads_dir, viewer_dir),
            )

    for module, forbidden in DOWNLOAD_PROHIBITED_FILES.items():
        archive_names = names.get(module)
        if archive_names is None:
            continue
        leaked = sorted(
            name
            for name in archive_names
            if PurePosixPath(name).name in forbidden
        )
        if leaked:
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ARCHIVE_CROSS_MODULE_FILE",
                "A Reel module archive contains another module's final deliverables.",
                path=rel(paths[module], viewer_dir),
                data={"module": module, "files": leaked[:20]},
            )


def validate_download_contract(
    findings: list[dict[str, Any]],
    viewer_dir: Path,
) -> dict[str, Any] | None:
    """Validate the explicit delivery mode and its corresponding artifacts."""
    manifest_path = viewer_dir / DOWNLOAD_MANIFEST_PATH
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        add_finding(
            findings,
            "ERROR",
            "DOWNLOAD_MANIFEST_MISSING",
            "assets/meta/reel_downloads.json is missing.",
            path=rel(manifest_path, viewer_dir),
        )
        return None
    except json.JSONDecodeError as exc:
        add_finding(
            findings,
            "ERROR",
            "DOWNLOAD_MANIFEST_INVALID",
            f"Download manifest is invalid JSON: {exc}",
            path=rel(manifest_path, viewer_dir),
        )
        return None
    issues = validate_download_manifest(
        payload,
        bundle_root=viewer_dir,
        require_sources=(
            isinstance(payload, dict) and payload.get("delivery") == "on_demand"
        ),
    )
    for issue in issues:
        issue_path = str(issue.get("path") or "")
        add_finding(
            findings,
            "ERROR",
            str(issue["code"]),
            str(issue["message"]),
            path=(
                f"{DOWNLOAD_MANIFEST_PATH.as_posix()}:{issue_path}"
                if issue_path
                else DOWNLOAD_MANIFEST_PATH.as_posix()
            ),
            data=issue.get("data") if isinstance(issue.get("data"), dict) else {},
        )

    if not isinstance(payload, dict):
        return None
    delivery = payload.get("delivery")
    if delivery == "materialized":
        validate_download_archives(findings, viewer_dir)
    elif delivery == "on_demand":
        downloads_dir = viewer_dir / "assets" / "downloads"
        stale_archives = (
            sorted(
                path
                for path in downloads_dir.rglob("*")
                if path.is_file() and path.suffix.lower() == ".zip"
            )
            if downloads_dir.is_dir()
            else []
        )
        if stale_archives:
            add_finding(
                findings,
                "ERROR",
                "ON_DEMAND_ARCHIVE_PERSISTED",
                "On-demand Reel bundles must not persist ZIP archives under assets/downloads.",
                path=rel(downloads_dir, viewer_dir),
                data={"files": [rel(path, viewer_dir) for path in stale_archives[:20]]},
            )
    return payload


def download_delivery(viewer_dir: Path) -> str | None:
    try:
        payload = json.loads(
            (viewer_dir.resolve() / DOWNLOAD_MANIFEST_PATH).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("delivery") in {
        "materialized",
        "on_demand",
    }:
        return str(payload["delivery"])
    return None


def validate_local_open_resources(findings: list[dict[str, Any]], poster_html: str, poster_path: Path, root: Path) -> None:
    resource_patterns = {
        "external script": r"<script\b[^>]*\bsrc\s*=\s*['\"]https?://",
        "external stylesheet": r"<link\b[^>]*\bhref\s*=\s*['\"]https?://",
        "external image": r"<img\b[^>]*\bsrc\s*=\s*['\"]https?://",
        "external css url": r"url\(\s*['\"]?https?://",
    }
    for label, pattern in resource_patterns.items():
        if re.search(pattern, poster_html, flags=re.IGNORECASE):
            add_finding(
                findings,
                "ERROR",
                "LOCAL_OPEN_EXTERNAL_RESOURCE",
                "Direct-open reel bundles must not depend on external poster render resources.",
                path=rel(poster_path, root),
                data={"resource": label},
            )
    if "mathjax/es5/tex-svg.js" in poster_html and not (poster_path.parent / "mathjax" / "es5" / "tex-svg.js").is_file():
        add_finding(
            findings,
            "ERROR",
            "LOCAL_OPEN_MATHJAX_FILE_MISSING",
            "poster.html points to local MathJax, but assets/poster/mathjax/es5/tex-svg.js is missing.",
            path=rel(poster_path, root),
        )


def blocks_for_language(section: dict[str, Any], lang: str) -> list[Any]:
    blog = section.get("blog") if isinstance(section.get("blog"), dict) else {}
    blocks = blog.get("blocks") if isinstance(blog.get("blocks"), dict) else {}
    if isinstance(blocks.get(lang), list):
        return blocks[lang]
    legacy = blog.get(lang)
    if isinstance(legacy, list):
        return legacy
    return []


def figure_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    return [block for block in blocks if isinstance(block, dict) and str(block.get("type") or "").lower() == "figure"]


def validate_static(
    viewer_dir: Path,
    *,
    require_media: bool = True,
    require_blog: bool = True,
    require_captions: bool = True,
    contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    contract = contract or load_contract()
    viewer_dir = viewer_dir.resolve()
    if not viewer_dir.is_dir():
        add_finding(findings, "ERROR", "VIEWER_DIR_MISSING", "Reel final directory is missing.", path=str(viewer_dir))
        return findings

    html_path = viewer_dir / "reel.html"
    alignment_path = viewer_dir / "content_alignment.json"
    poster_path = viewer_dir / "assets" / "poster" / "poster.html"
    file_exists(findings, html_path, viewer_dir, "REEL_HTML_MISSING", "reel.html is missing.")
    file_exists(findings, poster_path, viewer_dir, "POSTER_HTML_MISSING", "Copied assets/poster/poster.html is missing.")

    html = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    poster_html = poster_path.read_text(encoding="utf-8") if poster_path.is_file() else ""
    validate_no_backup_files(findings, viewer_dir)
    download_manifest = validate_download_contract(findings, viewer_dir)
    validate_no_local_paths(findings, html, path=rel(html_path, viewer_dir))
    validate_local_open_resources(findings, poster_html, poster_path, viewer_dir)
    required_html_markers = contract.get("required_html_markers") if isinstance(contract.get("required_html_markers"), dict) else {}
    for label, marker in required_html_markers.items():
        if marker not in html:
            add_finding(
                findings,
                "ERROR",
                "SECTION_MODAL_MARKER_MISSING",
                f"Reel HTML is missing required section-modal marker: {label}.",
                path=rel(html_path, viewer_dir),
                data={"marker": marker},
            )
    forbidden_html_markers = contract.get("forbidden_html_markers") if isinstance(contract.get("forbidden_html_markers"), dict) else {}
    for label, marker in forbidden_html_markers.items():
        if marker in html:
            add_finding(
                findings,
                "ERROR",
                "STALE_TABBED_VIEWER_MARKER",
                f"Reel HTML still contains stale tabbed-viewer marker: {label}.",
                path=rel(html_path, viewer_dir),
                data={"marker": marker},
            )

    for marker in contract.get("required_poster_debug_markers") or []:
        if str(marker) not in poster_html:
            add_finding(
                findings,
                "ERROR",
                "POSTER_NATIVE_DEBUG_MARKER_MISSING",
                "Copied poster.html is missing a native paper2poster debug marker required by the golden reel contract.",
                path=rel(poster_path, viewer_dir),
                data={"marker": marker},
            )
    if "__togglePosterDebug = ()" in html or "__togglePosterDebug=()" in html:
        add_finding(
            findings,
            "ERROR",
            "POSTER_DEBUG_OVERRIDE_REGRESSION",
            "Reel template must not overwrite paper2poster's native __togglePosterDebug; it must call it and layer its own opacity control separately.",
            path=rel(html_path, viewer_dir),
        )

    alignment = read_json(alignment_path, findings, viewer_dir)
    if not isinstance(alignment, dict):
        return findings
    validate_no_local_paths(findings, json.dumps(alignment, ensure_ascii=True), path=rel(alignment_path, viewer_dir))

    expected_viewer_version = str(contract.get("viewer_version") or DEFAULT_CONTRACT["viewer_version"])
    expected_template_version = str(contract.get("template_version") or DEFAULT_CONTRACT["template_version"])
    if alignment.get("viewer_version") != expected_viewer_version:
        add_finding(
            findings,
            "ERROR",
            "VIEWER_VERSION_MISMATCH",
            f"viewer_version must be {expected_viewer_version}.",
            path=rel(alignment_path, viewer_dir),
            data={"actual": alignment.get("viewer_version"), "expected": expected_viewer_version},
        )
    if alignment.get("template_version") != expected_template_version:
        add_finding(
            findings,
            "ERROR",
            "TEMPLATE_VERSION_MISMATCH",
            f"template_version must be {expected_template_version}.",
            path=rel(alignment_path, viewer_dir),
            data={"actual": alignment.get("template_version"), "expected": expected_template_version},
        )

    for required in contract.get("required_output_paths") or []:
        path = viewer_dir / str(required)
        if not path_exists(path):
            add_finding(
                findings,
                "ERROR",
                "REQUIRED_VIEWER_PATH_MISSING",
                "Reel final package is missing a path required by the golden viewer contract.",
                path=str(required),
            )

    if require_media:
        for required in contract.get("required_media_subdirs") or []:
            path = viewer_dir / str(required)
            if not path.is_dir():
                add_finding(
                    findings,
                    "ERROR",
                    "REQUIRED_MEDIA_DIR_MISSING",
                    "Reel final package is missing a media directory required by the golden viewer contract.",
                    path=str(required),
                )

    sections = alignment.get("sections")
    if not isinstance(sections, list) or not sections:
        add_finding(findings, "ERROR", "SECTIONS_MISSING", "content_alignment.json must contain a non-empty sections list.", path=rel(alignment_path, viewer_dir))
        return findings

    if not any(section.get("id") == "title" for section in sections if isinstance(section, dict)):
        add_finding(findings, "WARNING", "TITLE_SECTION_MISSING", "No title section is mapped; title click may not open the full-paper modal.", path=rel(alignment_path, viewer_dir))

    if require_media and not (viewer_dir / "assets" / "media" / "video.mp4").is_file():
        add_finding(findings, "ERROR", "FULL_VIDEO_MISSING", "assets/media/video.mp4 is missing.", path="assets/media/video.mp4")
    artifacts = alignment.get("artifacts") if isinstance(alignment.get("artifacts"), dict) else {}
    if require_media and artifacts.get("video_source_kind") != "raw_pre_subtitle":
        add_finding(
            findings,
            "ERROR",
            "REEL_VIDEO_SOURCE_NOT_RAW",
            "paper2reel must use the raw pre-subtitle video as its playback source; subtitles are supplied by the CC/VTT toggle.",
            path=rel(alignment_path, viewer_dir),
            data={"actual": artifacts.get("video_source_kind")},
        )
    if require_captions and artifacts.get("caption_delivery") != "sidecar_vtt_toggle":
        add_finding(
            findings,
            "ERROR",
            "REEL_CAPTION_DELIVERY_NOT_TOGGLEABLE",
            "paper2reel captions must be delivered as sidecar VTT tracks so the CC button controls them.",
            path=rel(alignment_path, viewer_dir),
            data={"actual": artifacts.get("caption_delivery")},
        )
    if not any((viewer_dir / "assets" / "slides").glob("slide_*.*")):
        add_finding(findings, "ERROR", "SLIDE_FRAMES_MISSING", "assets/slides/ contains no slide frames.", path="assets/slides/")
    downloads = alignment.get("downloads") if isinstance(alignment.get("downloads"), list) else []
    delivery = (
        str(download_manifest.get("delivery"))
        if isinstance(download_manifest, dict)
        else None
    )
    if alignment.get("download_delivery") != delivery:
        add_finding(
            findings,
            "ERROR",
            "DOWNLOAD_DELIVERY_MISMATCH",
            "content_alignment.json and reel_downloads.json must declare the same delivery mode.",
            path=rel(alignment_path, viewer_dir),
            data={
                "alignment": alignment.get("download_delivery"),
                "manifest": delivery,
            },
        )
    min_downloads = int(contract.get("min_download_buttons") or 0)
    if len(downloads) < min_downloads:
        add_finding(findings, "ERROR", "DOWNLOADS_MISSING", "Top menu must expose every download bundle required by the golden viewer contract.", path=rel(alignment_path, viewer_dir), data={"count": len(downloads), "required": min_downloads})
    download_labels = {str(item.get("label") or "") for item in downloads if isinstance(item, dict)}
    for label in contract.get("required_download_labels") or []:
        if str(label) not in download_labels:
            add_finding(findings, "ERROR", "DOWNLOAD_LABEL_MISSING", "A required top-menu download label is missing.", path=rel(alignment_path, viewer_dir), data={"label": label, "found": sorted(download_labels)})
    expected_hrefs = {
        kind: (
            f"assets/downloads/{ARCHIVE_META[kind]['filename']}"
            if delivery == "materialized"
            else f"__download__/{kind}"
        )
        for kind in ARCHIVE_ORDER
    }
    label_to_kind = {
        str(ARCHIVE_META[kind]["label"]): kind
        for kind in ARCHIVE_ORDER
    }
    for item in downloads:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        href = str(item.get("href") or "")
        kind = label_to_kind.get(label)
        expected_href = expected_hrefs.get(kind) if kind else None
        if href != expected_href:
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_HREF_INVALID",
                "Download link does not match the declared delivery mode.",
                path=href or rel(alignment_path, viewer_dir),
                data={"label": label, "actual": href, "expected": expected_href},
            )
        elif delivery == "materialized" and not (viewer_dir / href).is_file():
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_FILE_MISSING",
                "Materialized download listed in content_alignment.json is missing.",
                path=href,
            )

    for raw_section in sections:
        if not isinstance(raw_section, dict):
            add_finding(findings, "ERROR", "SECTION_SCHEMA_INVALID", "Each section entry must be an object.", path=rel(alignment_path, viewer_dir))
            continue
        sid = str(raw_section.get("id") or "").strip()
        if not sid:
            add_finding(findings, "ERROR", "SECTION_ID_MISSING", "A section entry is missing id.", path=rel(alignment_path, viewer_dir))
            continue
        if sid == "title":
            continue

        slides = raw_section.get("slides")
        slide_indices = raw_section.get("slide_indices")
        if not slides and not slide_indices:
            add_finding(findings, "ERROR", "SECTION_SLIDES_MISSING", f"Section {sid} has no mapped slide thumbnails.", path=rel(alignment_path, viewer_dir), data={"section": sid})

        if require_media:
            clip = raw_section.get("clip")
            if not clip:
                add_finding(findings, "ERROR", "SECTION_CLIP_MISSING", f"Section {sid} has no video clip path.", path=rel(alignment_path, viewer_dir), data={"section": sid})
            elif not (viewer_dir / str(clip)).is_file():
                add_finding(findings, "ERROR", "SECTION_CLIP_FILE_MISSING", f"Section {sid} video clip file is missing.", path=str(clip), data={"section": sid})

        if require_captions:
            captions = raw_section.get("captions")
            if not captions:
                add_finding(findings, "ERROR", "SECTION_CAPTIONS_MISSING", f"Section {sid} has no subtitle track.", path=rel(alignment_path, viewer_dir), data={"section": sid})
            elif not (viewer_dir / str(captions)).is_file():
                add_finding(findings, "ERROR", "SECTION_CAPTIONS_FILE_MISSING", f"Section {sid} subtitle file is missing.", path=str(captions), data={"section": sid})

        if require_blog:
            en_blocks = blocks_for_language(raw_section, "en")
            zh_blocks = blocks_for_language(raw_section, "zh")
            if not en_blocks:
                add_finding(findings, "ERROR", "SECTION_BLOG_EN_MISSING", f"Section {sid} has no English blog blocks.", path=rel(alignment_path, viewer_dir), data={"section": sid})
            if not zh_blocks:
                add_finding(findings, "ERROR", "SECTION_BLOG_CN_MISSING", f"Section {sid} has no Chinese blog blocks.", path=rel(alignment_path, viewer_dir), data={"section": sid})
            for lang, blocks in (("en", en_blocks), ("zh", zh_blocks)):
                figs = figure_blocks(blocks)
                if not figs:
                    add_finding(findings, "ERROR", "SECTION_BLOG_FIGURE_MISSING", f"Section {sid} has no {lang} blog figure block.", path=rel(alignment_path, viewer_dir), data={"section": sid, "lang": lang})
                for fig in figs:
                    src = str(fig.get("src") or fig.get("path") or "")
                    if not src or not (viewer_dir / src).is_file():
                        add_finding(findings, "ERROR", "SECTION_BLOG_FIGURE_FILE_MISSING", f"Section {sid} {lang} blog figure file is missing.", path=src or rel(alignment_path, viewer_dir), data={"section": sid, "lang": lang})

    return findings


def validate_range_support(base_url: str, viewer_dir: Path, findings: list[dict[str, Any]]) -> None:
    """Verify the QA server can serve video byte ranges required for seeking."""
    candidates = ["assets/media/video.mp4"]
    candidates.extend(
        rel(path, viewer_dir)
        for path in sorted((viewer_dir / "assets" / "media" / "clips").glob("*.mp4"))[:1]
    )
    checked = 0
    for candidate in candidates:
        if not (viewer_dir / candidate).is_file():
            continue
        checked += 1
        url = f"{base_url}/{candidate}"
        request = urllib.request.Request(url, headers={"Range": "bytes=0-99"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = int(response.status)
                headers = response.headers
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            headers = exc.headers
        except Exception as exc:
            add_finding(
                findings,
                "ERROR",
                "VIDEO_RANGE_REQUEST_FAILED",
                "Browser QA server could not answer a video Range request.",
                path=candidate,
                data={"error": str(exc)},
            )
            continue
        content_range = str(headers.get("Content-Range") or "")
        accept_ranges = str(headers.get("Accept-Ranges") or "")
        if status != 206 or "bytes" not in accept_ranges.lower() or not content_range.startswith("bytes 0-"):
            add_finding(
                findings,
                "ERROR",
                "VIDEO_RANGE_UNSUPPORTED",
                "paper2reel preview/browser gate must serve MP4 files with HTTP 206 byte ranges so video seeking and thumbnail jumps work.",
                path=candidate,
                data={"status": status, "accept_ranges": accept_ranges, "content_range": content_range},
            )
    if checked == 0:
        add_finding(
            findings,
            "ERROR",
            "VIDEO_RANGE_CANDIDATE_MISSING",
            "No MP4 candidate was available for Range/seek validation.",
            path="assets/media/",
        )


def validate_on_demand_endpoints(
    base_url: str,
    findings: list[dict[str, Any]],
) -> None:
    """Verify every dynamic link resolves without materializing its ZIP."""
    for kind in ARCHIVE_ORDER:
        url = f"{base_url}/__download__/{kind}"
        request = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = int(response.status)
                content_type = str(response.headers.get("Content-Type") or "")
                disposition = str(response.headers.get("Content-Disposition") or "")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            content_type = str(exc.headers.get("Content-Type") or "")
            disposition = str(exc.headers.get("Content-Disposition") or "")
        except Exception as exc:
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ENDPOINT_REQUEST_FAILED",
                "Browser QA server could not validate an on-demand download endpoint.",
                path=f"__download__/{kind}",
                data={"error": str(exc)},
            )
            continue
        expected_filename = str(ARCHIVE_META[kind]["filename"])
        if (
            status != 200
            or "application/zip" not in content_type.lower()
            or expected_filename not in disposition
        ):
            add_finding(
                findings,
                "ERROR",
                "DOWNLOAD_ENDPOINT_INVALID",
                "On-demand download endpoint did not return the expected ZIP response.",
                path=f"__download__/{kind}",
                data={
                    "status": status,
                    "content_type": content_type,
                    "content_disposition": disposition,
                    "expected_filename": expected_filename,
                },
            )


def direct_video_seek(page: Any, findings: list[dict[str, Any]], *, label: str) -> None:
    try:
        result = page.evaluate(
            """async () => {
              const video = document.getElementById('sectionVideo');
              if (!video) return {ok:false, reason:'missing_video'};
              await new Promise((resolve, reject) => {
                if (video.readyState >= 1 && Number.isFinite(video.duration)) return resolve();
                const timer = setTimeout(() => reject(new Error('metadata timeout')), 8000);
                video.addEventListener('loadedmetadata', () => { clearTimeout(timer); resolve(); }, {once:true});
              });
              const duration = Number(video.duration) || 0;
              if (duration < 2) return {ok:false, reason:'duration_too_short', duration, src:video.currentSrc || video.src};
              let target = Math.max(1, Math.min(duration - 0.8, duration * 0.65));
              if (Math.abs((Number(video.currentTime) || 0) - target) < 1.5) {
                target = Math.max(1, Math.min(duration - 0.8, duration * 0.35));
              }
              const before = Number(video.currentTime) || 0;
              const seeked = new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(new Error('seek timeout')), 8000);
                video.addEventListener('seeked', () => { clearTimeout(timer); resolve(); }, {once:true});
              });
              video.currentTime = target;
              await seeked;
              const currentTime = Number(video.currentTime) || 0;
              return {
                ok: Math.abs(currentTime - target) <= 2.5 || currentTime >= target - 1.5,
                before,
                target,
                currentTime,
                duration,
                readyState: video.readyState,
                src: video.currentSrc || video.src,
              };
            }"""
        )
    except Exception as exc:
        add_finding(
            findings,
            "ERROR",
            "VIDEO_DIRECT_SEEK_FAILED",
            "Direct video seeking failed in the browser gate.",
            data={"label": label, "error": str(exc)},
        )
        return
    if not isinstance(result, dict) or not result.get("ok"):
        add_finding(
            findings,
            "ERROR",
            "VIDEO_DIRECT_SEEK_FAILED",
            "Video progress-bar style seeking did not move playback to the requested time.",
            data={"label": label, "result": result},
        )


def validate_topbar_layout(
    page: Any,
    findings: list[dict[str, Any]],
    *,
    label: str,
    downloads_expected: bool = True,
) -> None:
    try:
        result = page.evaluate(
            """() => {
              const item = selector => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {left:r.left, right:r.right, width:r.width, text:(el.textContent || '').trim()};
              };
              return {
                brand: item('.topbar .brand'),
                brandImage: (() => {
                  const img = document.querySelector('.topbar .brand-mark');
                  if (!img) return null;
                  return {src: img.getAttribute('src') || '', complete: img.complete, naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight};
                })(),
                oldTitleCount: document.querySelectorAll('.topbar .title').length,
                rail: item('#sectionRail'),
                downloads: item('#downloadLinks'),
                help: item('#helpTopBtn'),
                hintCount: document.querySelectorAll('.topbar .hint').length,
              };
            }"""
        )
    except Exception as exc:
        add_finding(
            findings,
            "ERROR",
            "TOPBAR_LAYOUT_CHECK_FAILED",
            "Browser gate could not inspect the top menu layout.",
            data={"label": label, "error": str(exc)},
        )
        return
    if not isinstance(result, dict):
        add_finding(findings, "ERROR", "TOPBAR_LAYOUT_CHECK_FAILED", "Top menu layout inspection returned no data.", data={"label": label, "result": result})
        return
    required_elements = ["brand", "rail", "help"]
    if downloads_expected:
        required_elements.append("downloads")
    missing = [name for name in required_elements if not result.get(name)]
    if missing:
        add_finding(findings, "ERROR", "TOPBAR_ELEMENT_MISSING", "Top menu is missing an element required by the current layout.", data={"label": label, "missing": missing, "result": result})
        return
    if int(result.get("oldTitleCount") or 0) != 0:
        add_finding(findings, "ERROR", "TOPBAR_TEXT_TITLE_STALE", "Top menu must use the Reel wordmark instead of the old Paper Reel text title.", data={"label": label, "title_count": result.get("oldTitleCount")})
    if int(result.get("hintCount") or 0) != 0:
        add_finding(findings, "ERROR", "TOPBAR_HINT_TEXT_STALE", "Top menu must not show the old hint text next to Paper Reel.", data={"label": label, "hint_count": result.get("hintCount")})
    brand_image = result.get("brandImage") if isinstance(result.get("brandImage"), dict) else {}
    if not brand_image or not brand_image.get("complete") or int(brand_image.get("naturalWidth") or 0) <= 0:
        add_finding(findings, "ERROR", "TOPBAR_WORDMARK_BROKEN", "Top menu Reel wordmark image did not load.", data={"label": label, "brand_image": brand_image})
    brand = result["brand"]
    rail = result["rail"]
    downloads = result["downloads"]
    help_btn = result["help"]
    ordered = (
        brand["left"] < rail["left"] < downloads["left"] < help_btn["left"]
        if downloads_expected
        else brand["left"] < rail["left"] < help_btn["left"]
    )
    if not ordered:
        add_finding(
            findings,
            "ERROR",
            "TOPBAR_LAYOUT_ORDER_WRONG",
            "Top menu elements are not in the required editorial order.",
            data={"label": label, "layout": result},
        )
    try:
        tab_state = page.evaluate(
            """() => {
              const buttons = Array.from(document.querySelectorAll('#sectionRail button'));
              return {
                count: buttons.length,
                first: buttons[0] ? {
                  index: (buttons[0].querySelector('.section-index')?.textContent || '').trim(),
                  label: (buttons[0].querySelector('.section-label')?.textContent || '').trim(),
                  height: buttons[0].getBoundingClientRect().height,
                  minWidth: getComputedStyle(buttons[0]).minWidth,
                  borderRadius: getComputedStyle(buttons[0]).borderRadius,
                } : null,
                hasIndexes: buttons.every(button => button.querySelector('.section-index')),
                hasLabels: buttons.every(button => button.querySelector('.section-label')),
              };
            }"""
        )
        if not isinstance(tab_state, dict) or int(tab_state.get("count") or 0) <= 0:
            add_finding(findings, "ERROR", "SECTION_RAIL_TABS_MISSING", "Top menu section rail has no editorial section tabs.", data={"label": label, "state": tab_state})
        elif not tab_state.get("hasIndexes") or not tab_state.get("hasLabels"):
            add_finding(findings, "ERROR", "SECTION_RAIL_TAB_STRUCTURE_BROKEN", "Editorial section tabs must include a numeric index and section label.", data={"label": label, "state": tab_state})
        else:
            first = tab_state.get("first") if isinstance(tab_state.get("first"), dict) else {}
            if str(first.get("index") or "") != "01" or not str(first.get("label") or "").strip():
                add_finding(findings, "ERROR", "SECTION_RAIL_TAB_STRUCTURE_BROKEN", "Editorial section tabs did not render the expected index/label text.", data={"label": label, "state": tab_state})
    except Exception as exc:
        add_finding(findings, "ERROR", "SECTION_RAIL_TAB_STRUCTURE_BROKEN", "Browser gate could not inspect the editorial section tabs.", data={"label": label, "error": str(exc)})
    if "Help" not in str(help_btn.get("text") or "") and "?" not in str(help_btn.get("text") or ""):
        add_finding(findings, "ERROR", "TOPBAR_HELP_BUTTON_LABEL_MISSING", "Top Help button must visibly indicate help.", data={"label": label, "text": help_btn.get("text")})
    try:
        page.locator("#helpTopBtn").click()
        page.wait_for_timeout(150)
        help_open = page.locator("#helpOverlay").evaluate("el => el.classList.contains('open')")
        if not help_open:
            add_finding(findings, "ERROR", "TOPBAR_HELP_BUTTON_BROKEN", "Top Help button did not open the help overlay.", data={"label": label})
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
    except Exception as exc:
        add_finding(findings, "ERROR", "TOPBAR_HELP_BUTTON_BROKEN", "Browser gate could not exercise the top Help button.", data={"label": label, "error": str(exc)})


def validate_browser_seek_interactions(page: Any, findings: list[dict[str, Any]]) -> None:
    """Exercise thumbnail jumps and direct seeking, not just element presence."""
    try:
        overlay_open = page.locator("#overlay").evaluate("el => el.classList.contains('open')")
        if overlay_open:
            page.locator("#closeBtn").click()
            page.wait_for_timeout(150)
        topbar_display = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
        if topbar_display == "none":
            page.keyboard.press("v")
            page.wait_for_timeout(100)
        title_button = page.locator('#sectionRail button[data-section="title"]')
        if title_button.count() != 1:
            add_finding(findings, "ERROR", "TITLE_RAIL_BUTTON_MISSING", "Cannot test full-video thumbnail seek because the title rail button is missing.")
            return
        title_button.click()
        page.wait_for_selector("#overlay.open", timeout=5000)
        page.wait_for_timeout(500)
        thumb_count = page.locator(".thumb-btn").count()
        if thumb_count < 2:
            add_finding(
                findings,
                "ERROR",
                "THUMBNAIL_SEEK_UNTESTABLE",
                "Full-video modal does not expose at least two slide thumbnails, so thumbnail seek cannot be validated.",
                data={"thumb_count": thumb_count},
            )
        else:
            target_index = min(4, thumb_count - 1)
            target_thumb = page.locator(".thumb-btn").nth(target_index)
            target_time = float(target_thumb.get_attribute("data-time") or "0")
            target_thumb.click()
            page.wait_for_function(
                """target => {
                  const video = document.getElementById('sectionVideo');
                  if (!video) return false;
                  const current = Number(video.currentTime) || 0;
                  return current >= target - 1.5 && current <= target + 8.0;
                }""",
                arg=target_time,
                timeout=10000,
            )
            current_time = page.locator("#sectionVideo").evaluate("video => Number(video.currentTime) || 0")
            if current_time < target_time - 1.5:
                add_finding(
                    findings,
                    "ERROR",
                    "THUMBNAIL_SEEK_FAILED",
                    "Clicking a slide thumbnail did not seek the video to the thumbnail timestamp.",
                    data={"target_index": target_index, "target_time": target_time, "current_time": current_time},
                )
        direct_video_seek(page, findings, label="full_video")

        section_id = page.evaluate(
            """() => {
              const button = Array.from(document.querySelectorAll('#sectionRail button'))
                .find(item => item.dataset.section && item.dataset.section !== 'title');
              if (!button) return null;
              button.click();
              return button.dataset.section;
            }"""
        )
        if not section_id:
            add_finding(findings, "ERROR", "SECTION_RAIL_BUTTON_MISSING", "Cannot test section-clip seeking because no non-title section rail button is available.")
            return
        page.wait_for_selector("#overlay.open", timeout=5000)
        page.wait_for_timeout(500)
        video_src = page.locator("#sectionVideo").get_attribute("src") or ""
        if "assets/media/clips/" not in video_src and "media/clips/" not in video_src:
            add_finding(
                findings,
                "ERROR",
                "SECTION_SEEK_VIDEO_NOT_CLIP",
                "Cannot validate section-clip seeking because the section modal is not playing a section clip.",
                data={"section": section_id, "src": video_src},
            )
        else:
            direct_video_seek(page, findings, label=f"section:{section_id}")
    except Exception as exc:
        add_finding(
            findings,
            "ERROR",
            "VIDEO_SEEK_INTERACTION_FAILED",
            "Browser gate could not validate thumbnail/progress seeking.",
            data={"error": str(exc)},
        )


def browser_gate(viewer_dir: Path, screenshot: Path | None = None, *, contract: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    contract = contract or load_contract()
    delivery = download_delivery(viewer_dir)
    min_downloads = int(contract.get("min_download_buttons") or DEFAULT_CONTRACT["min_download_buttons"])
    min_blog_text = int(contract.get("min_blog_text_chars") or DEFAULT_CONTRACT["min_blog_text_chars"])
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local env
        add_finding(findings, "ERROR", "PLAYWRIGHT_UNAVAILABLE", f"Playwright is required for browser reel gate: {exc}")
        return findings

    handler = functools.partial(RangeRequestHandler, directory=str(viewer_dir.resolve()))
    with ThreadedRangeHTTPServer(("127.0.0.1", 0), handler) as httpd:
        port = int(httpd.server_address[1])
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        url = f"{base_url}/reel.html"
        validate_range_support(base_url, viewer_dir.resolve(), findings)
        if delivery == "on_demand":
            validate_on_demand_endpoints(base_url, findings)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)

                topbar_initial = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
                overlay_initial = page.locator("#overlay").evaluate("el => getComputedStyle(el).display")
                if topbar_initial != "none":
                    add_finding(findings, "ERROR", "TOPBAR_VISIBLE_BY_DEFAULT", "Top reel menu must be hidden by default.", data={"display": topbar_initial})
                if overlay_initial != "none":
                    add_finding(findings, "ERROR", "MODAL_VISIBLE_BY_DEFAULT", "Section modal must be hidden by default.", data={"display": overlay_initial})

                page.keyboard.press("h")
                page.wait_for_timeout(100)
                help_open = page.locator("#helpOverlay").evaluate("el => el.classList.contains('open')")
                if not help_open:
                    add_finding(findings, "ERROR", "HELP_SHORTCUT_BROKEN", "Shortcut h did not open the help overlay.")
                page.keyboard.press("Escape")

                page.keyboard.press("v")
                page.wait_for_timeout(100)
                topbar_after_v = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
                if topbar_after_v == "none":
                    add_finding(findings, "ERROR", "MENU_SHORTCUT_BROKEN", "Shortcut v did not show the section menu.")
                validate_topbar_layout(page, findings, label="http")
                download_labels = page.locator("#downloadLinks .download-link").evaluate_all("els => els.map(el => el.textContent.trim())")
                if page.locator("#downloadLinks .download-icon").count() != 1:
                    add_finding(findings, "ERROR", "DOWNLOAD_ICON_MISSING", "Top menu is missing the golden download icon.")
                if page.locator("#downloadLinks .download-sep").count() < max(0, len(contract.get("required_download_labels") or []) - 1):
                    add_finding(findings, "ERROR", "DOWNLOAD_SEPARATORS_MISSING", "Top menu download links must use the golden icon + separated link group.")
                required_download_labels = [str(label) for label in (contract.get("required_download_labels") or [])]
                if download_labels[: len(required_download_labels)] != required_download_labels:
                    add_finding(
                        findings,
                        "ERROR",
                        "DOWNLOAD_LINK_ORDER_MISMATCH",
                        "Top menu download links must match the golden order.",
                        data={"actual": download_labels, "expected": required_download_labels},
                    )
                rail_metrics = page.locator("#sectionRail button").evaluate_all(
                    """buttons => buttons.map(button => {
                      const style = getComputedStyle(button);
                      const rect = button.getBoundingClientRect();
                      return {
                        text: button.textContent.trim(),
                        width: rect.width,
                        height: rect.height,
                        display: style.display,
                        alignItems: style.alignItems,
                        justifyContent: style.justifyContent,
                        lineHeight: style.lineHeight,
                        transition: style.transition,
                        hasIndex: !!button.querySelector('.section-index'),
                        hasLabel: !!button.querySelector('.section-label'),
                      };
                    })"""
                )
                bad_rail_buttons = [
                    item for item in rail_metrics
                    if not (
                        60 <= float(item.get("width") or 0) <= 140
                        and 36 <= float(item.get("height") or 0) <= 46
                        and item.get("display") == "flex"
                        and item.get("hasIndex")
                        and item.get("hasLabel")
                    )
                ]
                if bad_rail_buttons:
                    add_finding(
                        findings,
                        "ERROR",
                        "SECTION_RAIL_BUTTON_STYLE_REGRESSION",
                        "Section rail buttons must keep the editorial tab structure and stable compact dimensions.",
                        data={"buttons": bad_rail_buttons[:6]},
                    )
                if page.locator("#sectionRail button").count():
                    first_rail = page.locator("#sectionRail button").first
                    first_rail.hover()
                    page.wait_for_timeout(100)
                    hover_transform = first_rail.evaluate("el => getComputedStyle(el).transform")
                    if hover_transform in ("none", "matrix(1, 0, 0, 1, 0, 0)"):
                        add_finding(
                            findings,
                            "ERROR",
                            "SECTION_RAIL_HOVER_STYLE_MISSING",
                            "Section rail buttons must keep the golden hover lift/glow style.",
                            data={"transform": hover_transform},
                        )

                frame = page.locator("#posterFrame").element_handle().content_frame()
                if frame is None:
                    add_finding(findings, "ERROR", "POSTER_IFRAME_NOT_LOADED", "Poster iframe did not load.")
                else:
                    frame.wait_for_selector("[data-section]", state="attached", timeout=5000)
                    frame.wait_for_selector("[data-section].paper-reel-clickable, .titlebar.paper-reel-clickable", state="attached", timeout=5000)
                    sid = frame.evaluate(
                        """() => {
                          const candidates = Array.from(document.querySelectorAll('[data-section]'))
                            .filter(el => !el.matches('button, a, .listen-btn, .listen-title, .listen-all'))
                            .filter(el => {
                              const r = el.getBoundingClientRect();
                              return r.width > 40 && r.height > 30;
                            });
                          const el = candidates[0];
                          if (!el) return null;
                          const r = el.getBoundingClientRect();
                          el.dispatchEvent(new MouseEvent('dblclick', {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: r.left + Math.min(12, Math.max(1, r.width / 2)),
                            clientY: r.top + Math.min(12, Math.max(1, r.height / 2))
                          }));
                          return el.getAttribute('data-section');
                        }"""
                    )
                    if not sid:
                        add_finding(findings, "ERROR", "NO_POSTER_SECTION_TARGET", "No visible poster section target was available for double-click.")
                    else:
                        page.wait_for_selector("#overlay.open", timeout=5000)
                        page.wait_for_timeout(500)
                        modal_opened = page.locator("#overlay").evaluate("el => el.classList.contains('open')")
                        video_src = page.locator("#sectionVideo").get_attribute("src") or ""
                        thumb_count = page.locator(".thumb-btn").count()
                        download_count = page.locator("#downloadLinks a").count()
                        blog_text_len = len(page.locator("#blogPane").inner_text())
                        blog_img_count = page.locator("#blogPane img").count()
                        broken_imgs = page.locator("#blogPane img").evaluate_all("imgs => imgs.filter(img => !img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0).map(img => img.getAttribute('src'))")
                        video_state = page.locator("#sectionVideo").evaluate("v => ({muted:v.muted, volume:v.volume, paused:v.paused, readyState:v.readyState, src:v.currentSrc || v.src})")
                        if not modal_opened:
                            add_finding(findings, "ERROR", "SECTION_MODAL_DID_NOT_OPEN", "Double-clicking a poster section did not open the modal.", data={"section": sid})
                        if "assets/media/clips/" not in video_src and "media/clips/" not in video_src:
                            add_finding(findings, "ERROR", "SECTION_VIDEO_NOT_CLIP", "Section modal video is not a section clip.", data={"section": sid, "src": video_src})
                        if video_state.get("muted") or float(video_state.get("volume") or 0) <= 0:
                            add_finding(findings, "ERROR", "SECTION_VIDEO_MUTED", "Section video is muted or has zero volume.", data={"section": sid, **video_state})
                        if page.locator("#captionToggle").count() != 1:
                            add_finding(findings, "ERROR", "CAPTION_TOGGLE_MISSING", "Section modal is missing the CC subtitle toggle.", data={"section": sid})
                        if page.locator("#playSoundBtn").count() != 1:
                            add_finding(findings, "ERROR", "SOUND_BUTTON_MISSING", "Section modal is missing the explicit sound playback button.", data={"section": sid})
                        if thumb_count < 1:
                            add_finding(findings, "ERROR", "SLIDE_THUMBNAILS_MISSING", "Section modal has no slide thumbnails.", data={"section": sid})
                        if download_count < min_downloads:
                            add_finding(findings, "ERROR", "DOWNLOAD_BUTTONS_MISSING", "Top menu has fewer download buttons than the golden viewer contract requires.", data={"count": download_count, "required": min_downloads})
                        if blog_text_len < min_blog_text:
                            add_finding(findings, "ERROR", "SECTION_BLOG_TOO_SHORT", "Section modal blog text is missing or too short.", data={"section": sid, "text_length": blog_text_len, "required": min_blog_text})
                        if blog_img_count < 1:
                            add_finding(findings, "ERROR", "SECTION_BLOG_IMAGE_MISSING", "Section modal rendered no blog image.", data={"section": sid})
                        if broken_imgs:
                            add_finding(findings, "ERROR", "SECTION_BLOG_IMAGE_BROKEN", "Section modal has broken blog images.", data={"section": sid, "broken": broken_imgs})

                    frame.evaluate(
                        """() => document.dispatchEvent(new KeyboardEvent('keydown', {key:'h', bubbles:true, cancelable:true}))"""
                    )
                    page.wait_for_timeout(200)
                    iframe_help_open = page.locator("#helpOverlay").evaluate("el => el.classList.contains('open')")
                    if not iframe_help_open:
                        add_finding(findings, "ERROR", "IFRAME_HELP_SHORTCUT_BROKEN", "Shortcut h did not work while poster iframe had focus.")
                    page.keyboard.press("Escape")
                    page.evaluate("() => document.body.classList.remove('show-menu')")
                    frame.evaluate(
                        """() => document.dispatchEvent(new KeyboardEvent('keydown', {key:'v', bubbles:true, cancelable:true}))"""
                    )
                    page.wait_for_timeout(200)
                    iframe_topbar = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
                    if iframe_topbar == "none":
                        add_finding(findings, "ERROR", "IFRAME_MENU_SHORTCUT_BROKEN", "Shortcut v did not work while poster iframe had focus.")
                    frame.evaluate(
                        """() => document.dispatchEvent(new KeyboardEvent('keydown', {key:'d', bubbles:true, cancelable:true}))"""
                    )
                    page.wait_for_timeout(450)
                    iframe_debug = frame.locator("#paperReelDebug").evaluate("el => getComputedStyle(el).display") if frame.locator("#paperReelDebug").count() else "missing"
                    if iframe_debug == "none" or iframe_debug == "missing":
                        add_finding(findings, "ERROR", "IFRAME_DEBUG_SHORTCUT_BROKEN", "Shortcut d did not reveal the poster debug opacity control while poster iframe had focus.")
                    native_debug = frame.evaluate("() => document.body.classList.contains('debug')")
                    bbox_count = frame.locator(".dbg-bbox").count()
                    if not native_debug or bbox_count < 1:
                        add_finding(
                            findings,
                            "ERROR",
                            "POSTER_NATIVE_DEBUG_SHORTCUT_BROKEN",
                            "Shortcut d must also reveal paper2poster's native debug boxes and size details, not only the reel opacity slider.",
                            data={"body_debug": native_debug, "bbox_count": bbox_count},
                        )

                validate_browser_seek_interactions(page, findings)

                if screenshot:
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot), full_page=True)
                browser.close()
        except Exception as exc:
            add_finding(findings, "ERROR", "BROWSER_GATE_EXCEPTION", f"Browser reel gate failed: {exc}")
        finally:
            httpd.shutdown()
            thread.join(timeout=2)
    return findings


def file_browser_gate(viewer_dir: Path, screenshot: Path | None = None, *, contract: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Exercise the direct-open file:// runtime.

    This gate intentionally does not require HTTP 206 Range support; file:// has
    no response headers. It instead validates that the same user-facing reel
    interactions work when reel.html is opened directly from disk.
    """
    findings: list[dict[str, Any]] = []
    contract = contract or load_contract()
    delivery = download_delivery(viewer_dir)
    min_downloads = int(contract.get("min_download_buttons") or DEFAULT_CONTRACT["min_download_buttons"])
    min_blog_text = int(contract.get("min_blog_text_chars") or DEFAULT_CONTRACT["min_blog_text_chars"])
    html_path = viewer_dir.resolve() / "reel.html"
    if not html_path.is_file():
        add_finding(findings, "ERROR", "REEL_HTML_MISSING", "reel.html is missing.", path=rel(html_path, viewer_dir))
        return findings
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local env
        add_finding(findings, "ERROR", "PLAYWRIGHT_UNAVAILABLE", f"Playwright is required for file browser reel gate: {exc}")
        return findings

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(html_path.as_uri(), wait_until="domcontentloaded")
            page.wait_for_timeout(1200)

            protocol = page.evaluate("() => window.location.protocol")
            if protocol != "file:":
                add_finding(findings, "ERROR", "FILE_GATE_NOT_FILE_PROTOCOL", "File browser gate did not open reel.html through file://.", data={"protocol": protocol})

            topbar_initial = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
            overlay_initial = page.locator("#overlay").evaluate("el => getComputedStyle(el).display")
            if topbar_initial != "none":
                add_finding(findings, "ERROR", "TOPBAR_VISIBLE_BY_DEFAULT", "Top reel menu must be hidden by default in file-open mode.", data={"display": topbar_initial})
            if overlay_initial != "none":
                add_finding(findings, "ERROR", "MODAL_VISIBLE_BY_DEFAULT", "Section modal must be hidden by default in file-open mode.", data={"display": overlay_initial})

            iframe_state = page.locator("#posterFrame").evaluate(
                """el => ({
                  src: el.getAttribute('src'),
                  dataSrc: el.getAttribute('data-src'),
                  srcdocLength: (el.getAttribute('srcdoc') || '').length
                })"""
            )
            if iframe_state.get("src"):
                add_finding(findings, "ERROR", "FILE_POSTER_IFRAME_SRC_NOT_DISABLED", "file:// mode must load the poster through iframe.srcdoc, not iframe.src.", data=iframe_state)
            if int(iframe_state.get("srcdocLength") or 0) < 1000:
                add_finding(findings, "ERROR", "FILE_POSTER_SRCDOC_MISSING", "file:// mode did not embed poster.html into iframe.srcdoc.", data=iframe_state)

            page.keyboard.press("h")
            page.wait_for_timeout(100)
            if not page.locator("#helpOverlay").evaluate("el => el.classList.contains('open')"):
                add_finding(findings, "ERROR", "HELP_SHORTCUT_BROKEN", "Shortcut h did not open help in file-open mode.")
            page.keyboard.press("Escape")

            page.keyboard.press("v")
            page.wait_for_timeout(100)
            topbar_after_v = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
            if topbar_after_v == "none":
                add_finding(findings, "ERROR", "MENU_SHORTCUT_BROKEN", "Shortcut v did not show the top menu in file-open mode.")
            validate_topbar_layout(
                page,
                findings,
                label="file",
                downloads_expected=delivery != "on_demand",
            )
            download_count = page.locator("#downloadLinks .download-link").count()
            download_display = page.locator("#downloadLinks").evaluate(
                "el => getComputedStyle(el).display"
            )
            if delivery == "on_demand" and (
                download_count != 0 or download_display != "none"
            ):
                add_finding(
                    findings,
                    "ERROR",
                    "FILE_ON_DEMAND_DOWNLOADS_VISIBLE",
                    "Online-only downloads must be hidden when reel.html is opened through file://.",
                    data={"count": download_count, "display": download_display},
                )
            elif delivery != "on_demand" and download_count < min_downloads:
                add_finding(findings, "ERROR", "DOWNLOAD_BUTTONS_MISSING", "Top menu has fewer download buttons than the golden viewer contract requires in file-open mode.", data={"count": download_count, "required": min_downloads})

            frame = page.locator("#posterFrame").element_handle().content_frame()
            if frame is None:
                add_finding(findings, "ERROR", "POSTER_IFRAME_NOT_LOADED", "Poster iframe did not load in file-open mode.")
            else:
                frame.wait_for_selector("[data-section]", state="attached", timeout=5000)
                frame.wait_for_selector("[data-section].paper-reel-clickable, .titlebar.paper-reel-clickable", state="attached", timeout=5000)
                base_uri = frame.evaluate("() => document.baseURI")
                if "/assets/poster/" not in str(base_uri):
                    add_finding(findings, "ERROR", "FILE_POSTER_BASE_URI_WRONG", "srcdoc poster must set base href to assets/poster/ so relative resources resolve.", data={"baseURI": base_uri})
                broken_poster_images = frame.evaluate(
                    """() => Array.from(document.images)
                      .filter(img => img.getAttribute('src'))
                      .filter(img => !img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0)
                      .map(img => img.getAttribute('src'))"""
                )
                if broken_poster_images:
                    add_finding(findings, "ERROR", "FILE_POSTER_IMAGE_BROKEN", "file-open poster has broken images.", data={"broken": broken_poster_images[:10]})

                hover_result = frame.evaluate(
                    """() => {
                      const candidates = Array.from(document.querySelectorAll('[data-section].paper-reel-clickable'))
                        .filter(el => !el.matches('button, a, .listen-btn, .listen-title, .listen-all'))
                        .filter(el => {
                          const r = el.getBoundingClientRect();
                          return r.width > 40 && r.height > 30;
                        });
                      const el = candidates.find(item => !item.closest('.titlebar')) || candidates[0];
                      if (!el) return {ok:false, reason:'no_target'};
                      const r = el.getBoundingClientRect();
                      el.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, clientX:r.left + 8, clientY:r.top + 8, view:window}));
                      el.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:r.left + 16, clientY:r.top + 16, view:window}));
                      return {
                        ok: el.classList.contains('paper-reel-hover') && document.body.classList.contains('paper-reel-has-hover'),
                        section: el.getAttribute('data-section'),
                        tooltip: document.getElementById('paperReelTip') ? document.getElementById('paperReelTip').textContent : ''
                      };
                    }"""
                )
                if not isinstance(hover_result, dict) or not hover_result.get("ok"):
                    add_finding(findings, "ERROR", "FILE_SECTION_HOVER_BROKEN", "Poster section hover highlight did not work in file-open mode.", data={"result": hover_result})

                sid = frame.evaluate(
                    """() => {
                      const candidates = Array.from(document.querySelectorAll('[data-section].paper-reel-clickable'))
                        .filter(el => !el.matches('button, a, .listen-btn, .listen-title, .listen-all'))
                        .filter(el => !el.closest('.titlebar'))
                        .filter(el => {
                          const r = el.getBoundingClientRect();
                          return r.width > 40 && r.height > 30;
                        });
                      const el = candidates[0];
                      if (!el) return null;
                      const r = el.getBoundingClientRect();
                      el.dispatchEvent(new MouseEvent('dblclick', {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: r.left + Math.min(12, Math.max(1, r.width / 2)),
                        clientY: r.top + Math.min(12, Math.max(1, r.height / 2))
                      }));
                      return el.getAttribute('data-section');
                    }"""
                )
                if not sid:
                    add_finding(findings, "ERROR", "NO_POSTER_SECTION_TARGET", "No visible poster section target was available for file-open double-click.")
                else:
                    page.wait_for_selector("#overlay.open", timeout=5000)
                    page.wait_for_timeout(600)
                    video_state = page.locator("#sectionVideo").evaluate(
                        """async video => {
                          await new Promise((resolve, reject) => {
                            if (video.readyState >= 1 && Number.isFinite(video.duration)) return resolve();
                            const timer = setTimeout(() => reject(new Error('metadata timeout')), 8000);
                            video.addEventListener('loadedmetadata', () => { clearTimeout(timer); resolve(); }, {once:true});
                          });
                          return {readyState: video.readyState, duration: video.duration, src: video.currentSrc || video.src};
                        }"""
                    )
                    if "assets/media/clips/" not in str(video_state.get("src")) and "media/clips/" not in str(video_state.get("src")):
                        add_finding(findings, "ERROR", "SECTION_VIDEO_NOT_CLIP", "Section modal video is not a section clip in file-open mode.", data={"section": sid, **video_state})
                    if float(video_state.get("duration") or 0) <= 1:
                        add_finding(findings, "ERROR", "SECTION_VIDEO_METADATA_BAD", "Section modal video metadata did not load in file-open mode.", data={"section": sid, **video_state})

                    blog_text_len = len(page.locator("#blogPane").inner_text())
                    blog_img_count = page.locator("#blogPane img").count()
                    broken_imgs = page.locator("#blogPane img").evaluate_all("imgs => imgs.filter(img => !img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0).map(img => img.getAttribute('src'))")
                    if blog_text_len < min_blog_text:
                        add_finding(findings, "ERROR", "SECTION_BLOG_TOO_SHORT", "Section modal blog text is missing or too short in file-open mode.", data={"section": sid, "text_length": blog_text_len, "required": min_blog_text})
                    if blog_img_count < 1:
                        add_finding(findings, "ERROR", "SECTION_BLOG_IMAGE_MISSING", "Section modal rendered no blog image in file-open mode.", data={"section": sid})
                    if broken_imgs:
                        add_finding(findings, "ERROR", "SECTION_BLOG_IMAGE_BROKEN", "Section modal has broken blog images in file-open mode.", data={"section": sid, "broken": broken_imgs})

                    page.locator("#langCn").click()
                    page.wait_for_timeout(100)
                    zh_text_len = len(page.locator("#blogPane").inner_text())
                    if zh_text_len < min_blog_text:
                        add_finding(findings, "ERROR", "SECTION_BLOG_CN_TOO_SHORT", "Chinese blog content is missing or too short in file-open mode.", data={"section": sid, "text_length": zh_text_len, "required": min_blog_text})

                    page.locator("#captionToggle").click()
                    page.wait_for_timeout(500)
                    caption_state = page.locator("#sectionVideo").evaluate(
                        """video => {
                          const tracks = Array.from(video.querySelectorAll('track[data-reel-caption]'));
                          const textTracks = Array.from(video.textTracks || []);
                          return {
                            button: document.getElementById('captionToggle').textContent,
                            trackCount: tracks.length,
                            trackSrc: tracks[0] ? tracks[0].src : '',
                            textTrackModes: textTracks.map(track => track.mode),
                            cueCounts: textTracks.map(track => track.cues ? track.cues.length : 0)
                          };
                        }"""
                    )
                    if int(caption_state.get("trackCount") or 0) < 1 or "data:text/vtt" not in str(caption_state.get("trackSrc")):
                        add_finding(findings, "ERROR", "FILE_CAPTION_NOT_INLINE", "file-open mode must use inline/data URI captions so CC works without HTTP.", data=caption_state)
                    if "showing" not in (caption_state.get("textTrackModes") or []):
                        add_finding(findings, "ERROR", "CAPTION_TOGGLE_BROKEN", "CC toggle did not show captions in file-open mode.", data=caption_state)

                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                page.keyboard.press("a")
                page.wait_for_timeout(150)
                listen_visible = frame.evaluate("() => !!(document.body && document.body.classList.contains('show-listen'))")
                if not listen_visible:
                    add_finding(findings, "ERROR", "AUDIO_SHORTCUT_BROKEN", "Shortcut a did not reveal poster audio controls in file-open mode.")
                page.evaluate("() => document.body.classList.remove('show-menu')")
                frame.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key:'v', bubbles:true, cancelable:true}))")
                page.wait_for_timeout(150)
                iframe_topbar = page.locator(".topbar").evaluate("el => getComputedStyle(el).display")
                if iframe_topbar == "none":
                    add_finding(findings, "ERROR", "IFRAME_MENU_SHORTCUT_BROKEN", "Shortcut v did not work while poster iframe had focus in file-open mode.")
                frame.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key:'d', bubbles:true, cancelable:true}))")
                page.wait_for_timeout(450)
                iframe_debug = frame.locator("#paperReelDebug").evaluate("el => getComputedStyle(el).display") if frame.locator("#paperReelDebug").count() else "missing"
                native_debug = frame.evaluate("() => !!(document.body && document.body.classList.contains('debug'))")
                if iframe_debug in ("none", "missing") or not native_debug:
                    add_finding(
                        findings,
                        "ERROR",
                        "IFRAME_DEBUG_SHORTCUT_BROKEN",
                        "Shortcut d did not reveal both reel and native poster debug controls in file-open mode.",
                        data={"reel_debug": iframe_debug, "native_debug": native_debug},
                    )

            validate_browser_seek_interactions(page, findings)

            if screenshot:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), full_page=True)
            browser.close()
    except Exception as exc:
        add_finding(findings, "ERROR", "FILE_BROWSER_GATE_EXCEPTION", f"File browser reel gate failed: {exc}")
    return findings


def make_report(viewer_dir: Path, findings: list[dict[str, Any]], *, contract: dict[str, Any]) -> dict[str, Any]:
    counts = {
        "error": sum(1 for item in findings if item.get("severity") == "ERROR"),
        "warning": sum(1 for item in findings if item.get("severity") == "WARNING"),
        "info": sum(1 for item in findings if item.get("severity") == "INFO"),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "viewer_dir": str(viewer_dir.resolve()),
        "contract": {
            "viewer_version": contract.get("viewer_version"),
            "template_version": contract.get("template_version"),
            "required_download_labels": contract.get("required_download_labels"),
        },
        "passed": counts["error"] == 0,
        "counts": counts,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate paper2reel final package.")
    parser.add_argument("viewer_dir", type=Path, help="paper2reel v2 bundle directory containing reel.html.")
    parser.add_argument("--contract", type=Path, help="Golden viewer contract JSON. Defaults to assets/section_modal_contract.json.")
    parser.add_argument("--browser", action="store_true", help="Run Playwright interaction gate in addition to static checks.")
    parser.add_argument("--file-browser", action="store_true", help="Run Playwright direct-open file:// interaction gate in addition to static checks.")
    parser.add_argument("--no-require-media", action="store_true", help="Do not require assets/media/video.mp4 or section clips.")
    parser.add_argument("--no-require-blog", action="store_true", help="Do not require EN/CN blog blocks per section.")
    parser.add_argument("--no-require-captions", action="store_true", help="Do not require subtitle tracks per section.")
    parser.add_argument("--screenshot", type=Path, help="Optional browser-gate screenshot path.")
    parser.add_argument("--report", type=Path, help="Write JSON QA report.")
    args = parser.parse_args()

    contract = load_contract(args.contract.resolve() if args.contract else None)
    findings = validate_static(
        args.viewer_dir,
        require_media=not args.no_require_media,
        require_blog=not args.no_require_blog,
        require_captions=not args.no_require_captions,
        contract=contract,
    )
    if args.browser:
        findings.extend(browser_gate(args.viewer_dir, screenshot=args.screenshot, contract=contract))
    if args.file_browser:
        findings.extend(file_browser_gate(args.viewer_dir, screenshot=args.screenshot, contract=contract))

    report = make_report(args.viewer_dir, findings, contract=contract)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    status = "PASS" if report["passed"] else "ERROR"
    print(f"[check_reel_package] {status}: {report['counts']['error']} error(s), {report['counts']['warning']} warning(s)")
    if args.report:
        print(f"[check_reel_package] wrote: {args.report}")
    for finding in findings[:30]:
        print(f"  - {finding['severity']} {finding['code']}: {finding['message']} ({finding.get('location') or ''})")
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
