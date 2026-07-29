#!/usr/bin/env python3
"""Shared Paper2Reel download-manifest contract.

The manifest describes the files in each user-facing archive without requiring
an archive to be persisted in the Reel bundle.  Both the standalone server and
the final-package checker use this module so path validation cannot drift.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


DOWNLOAD_SCHEMA_VERSION = "paper2reel.downloads.v1"
DOWNLOAD_MANIFEST_PATH = Path("assets/meta/reel_downloads.json")
DOWNLOAD_DELIVERIES = {"materialized", "on_demand"}
ARCHIVE_ORDER = ("all", "poster", "video", "blog")
ARCHIVE_META = {
    "all": {"label": "All", "filename": "all_final.zip"},
    "poster": {"label": "Poster", "filename": "poster_final.zip"},
    "video": {"label": "Video", "filename": "video_final.zip"},
    "blog": {"label": "Blog", "filename": "blog_final.zip"},
}
MODULE_FILES: dict[str, dict[str, set[str]]] = {
    "poster": {
        "files": {"poster.html", "poster.png", "poster.pdf", "poster.pptx"},
        "directories": {
            "assets/_pptx_build",
            "assets/figures",
            "assets/fonts",
            "assets/logos",
            "assets/qr",
        },
    },
    "video": {
        "files": {"video.mp4", "video.pptx"},
        "directories": {"assets/captions"},
    },
    "blog": {
        "files": {"blog_en.docx", "blog_zh.docx"},
        "directories": set(),
    },
}
PROHIBITED_PARTS = {
    ".claude",
    ".codex",
    ".git",
    "__pycache__",
    "_debug",
    "backup",
    "backups",
    "downloads",
    "internal",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_backup_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.endswith((".bak", ".backup", ".old", ".orig", "~"))
        or ".bak." in lowered
        or ".backup." in lowered
    )


def is_safe_relative_posix(value: str) -> bool:
    """Return whether *value* is a normalized, non-internal POSIX path."""
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or value.startswith("/")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if path.as_posix() != value:
        return False
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & PROHIBITED_PARTS:
        return False
    return not any(is_backup_name(part) for part in path.parts)


def is_internal_path(relative: Path) -> bool:
    value = relative.as_posix()
    return not is_safe_relative_posix(value)


def matches_module(relative: Path | PurePosixPath, module: str) -> bool:
    spec = MODULE_FILES[module]
    relative_posix = relative.as_posix()
    return (
        relative_posix in spec["files"]
        or any(
            relative_posix.startswith(f"{directory}/")
            for directory in spec["directories"]
        )
    )


def selected_files(
    source: Path,
    *,
    module: str | None,
) -> list[tuple[Path, Path]]:
    """Return safe files below *source*, optionally restricted by module."""
    selected: list[tuple[Path, Path]] = []
    source = source.resolve()
    if not source.is_dir():
        return selected
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if is_internal_path(relative):
            continue
        if module is not None and not matches_module(relative, module):
            continue
        selected.append((path, relative))
    return selected


def _bundle_path(path: Path, source: Path, bundle_root: Path, *, strict: bool) -> str:
    try:
        return path.resolve().relative_to(bundle_root.resolve()).as_posix()
    except ValueError:
        if strict:
            raise ValueError(
                f"on-demand download source is outside the final bundle: {path}"
            )
        return path.resolve().relative_to(source.resolve()).as_posix()


def _entry(path: Path, relative: Path, source: Path, bundle_root: Path, *, strict: bool) -> dict[str, Any]:
    return {
        "path": _bundle_path(path, source, bundle_root, strict=strict),
        "arcname": relative.as_posix(),
        "size": path.stat().st_size,
    }


def build_download_manifest(
    *,
    bundle_root: Path,
    poster_source: Path | None,
    video_source: Path | None,
    blog_source: Path | None,
    delivery: str,
) -> dict[str, Any]:
    """Build a deterministic download manifest from final-deliverable sources.

    ``on_demand`` is intentionally strict: every selected source must live
    below ``bundle_root`` and every module uses the explicit deliverable
    whitelist.  ``materialized`` preserves the legacy behavior for separate
    per-module source directories, where the whole safe source directory was
    archived.
    """
    if delivery not in DOWNLOAD_DELIVERIES:
        raise ValueError(f"unsupported download delivery mode: {delivery}")

    bundle_root = bundle_root.resolve()
    raw_sources = {
        "poster": poster_source,
        "video": video_source,
        "blog": blog_source,
    }
    sources = {
        module: Path(source).resolve()
        for module, source in raw_sources.items()
        if source is not None and Path(source).is_dir()
    }
    source_counts: dict[Path, int] = {}
    for source in sources.values():
        source_counts[source] = source_counts.get(source, 0) + 1

    module_entries: dict[str, list[dict[str, Any]]] = {
        "poster": [],
        "video": [],
        "blog": [],
    }
    strict = delivery == "on_demand"
    for module in ("poster", "video", "blog"):
        source = sources.get(module)
        if source is None:
            continue
        shared_source = source_counts[source] > 1
        module_filter = module if strict or shared_source else None
        module_entries[module] = [
            _entry(path, relative, source, bundle_root, strict=strict)
            for path, relative in selected_files(source, module=module_filter)
        ]

    all_entries: dict[str, dict[str, Any]] = {}
    if len(set(sources.values())) <= 1:
        for module in ("poster", "video", "blog"):
            for item in module_entries[module]:
                all_entries.setdefault(str(item["arcname"]), dict(item))
    else:
        for module in ("poster", "video", "blog"):
            for item in module_entries[module]:
                combined = dict(item)
                combined["arcname"] = f"{module}/{item['arcname']}"
                all_entries.setdefault(str(combined["arcname"]), combined)

    archives: dict[str, dict[str, Any]] = {}
    entries_by_archive = {
        "all": sorted(all_entries.values(), key=lambda item: str(item["arcname"])),
        **{
            module: sorted(module_entries[module], key=lambda item: str(item["arcname"]))
            for module in ("poster", "video", "blog")
        },
    }
    for kind in ARCHIVE_ORDER:
        archives[kind] = {
            **ARCHIVE_META[kind],
            "files": entries_by_archive[kind],
        }
    return {
        "schema_version": DOWNLOAD_SCHEMA_VERSION,
        "delivery": delivery,
        "created_at": utc_now(),
        "archives": archives,
    }


def write_download_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _issue(
    code: str,
    message: str,
    *,
    path: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "path": path,
        "data": data or {},
    }


def validate_download_manifest(
    payload: Any,
    *,
    bundle_root: Path,
    require_sources: bool | None = None,
) -> list[dict[str, Any]]:
    """Validate manifest schema, classification, path safety, and sources."""
    issues: list[dict[str, Any]] = []
    bundle_root = bundle_root.resolve()
    if not isinstance(payload, dict):
        return [_issue("DOWNLOAD_MANIFEST_SCHEMA_INVALID", "Download manifest must be a JSON object.")]
    if payload.get("schema_version") != DOWNLOAD_SCHEMA_VERSION:
        issues.append(
            _issue(
                "DOWNLOAD_MANIFEST_SCHEMA_INVALID",
                f"schema_version must be {DOWNLOAD_SCHEMA_VERSION}.",
                data={"actual": payload.get("schema_version")},
            )
        )
    delivery = payload.get("delivery")
    if delivery not in DOWNLOAD_DELIVERIES:
        issues.append(
            _issue(
                "DOWNLOAD_DELIVERY_INVALID",
                "Download manifest delivery must be materialized or on_demand.",
                data={"actual": delivery},
            )
        )
    if require_sources is None:
        require_sources = delivery == "on_demand"

    archives = payload.get("archives")
    if not isinstance(archives, dict):
        issues.append(_issue("DOWNLOAD_ARCHIVES_SCHEMA_INVALID", "archives must be an object."))
        return issues
    actual_kinds = set(archives)
    expected_kinds = set(ARCHIVE_ORDER)
    if actual_kinds != expected_kinds:
        issues.append(
            _issue(
                "DOWNLOAD_ARCHIVE_SET_INVALID",
                "archives must contain exactly all, poster, video, and blog.",
                data={"actual": sorted(actual_kinds), "expected": list(ARCHIVE_ORDER)},
            )
        )

    normalized: dict[str, list[tuple[str, str, int]]] = {}
    for kind in ARCHIVE_ORDER:
        archive = archives.get(kind)
        if not isinstance(archive, dict):
            issues.append(
                _issue(
                    "DOWNLOAD_ARCHIVE_SCHEMA_INVALID",
                    "Archive entry must be an object.",
                    path=f"archives.{kind}",
                )
            )
            continue
        expected = ARCHIVE_META[kind]
        for field in ("label", "filename"):
            if archive.get(field) != expected[field]:
                issues.append(
                    _issue(
                        "DOWNLOAD_ARCHIVE_METADATA_INVALID",
                        f"Archive {kind} has an invalid {field}.",
                        path=f"archives.{kind}.{field}",
                        data={"actual": archive.get(field), "expected": expected[field]},
                    )
                )
        files = archive.get("files")
        if not isinstance(files, list):
            issues.append(
                _issue(
                    "DOWNLOAD_FILES_SCHEMA_INVALID",
                    "Archive files must be a list.",
                    path=f"archives.{kind}.files",
                )
            )
            continue
        if delivery == "on_demand" and not files:
            issues.append(
                _issue(
                    "DOWNLOAD_ARCHIVE_EMPTY",
                    "Every on-demand archive must contain at least one whitelisted source file.",
                    path=f"archives.{kind}.files",
                )
            )
        seen_paths: set[str] = set()
        seen_arcnames: set[str] = set()
        valid_entries: list[tuple[str, str, int]] = []
        for index, item in enumerate(files):
            item_path = f"archives.{kind}.files[{index}]"
            if not isinstance(item, dict):
                issues.append(
                    _issue("DOWNLOAD_FILE_SCHEMA_INVALID", "Download file entry must be an object.", path=item_path)
                )
                continue
            source_path = item.get("path")
            arcname = item.get("arcname")
            size = item.get("size")
            if not isinstance(source_path, str) or not is_safe_relative_posix(source_path):
                issues.append(
                    _issue(
                        "DOWNLOAD_SOURCE_PATH_UNSAFE",
                        "Download source path must be a safe bundle-relative POSIX path.",
                        path=f"{item_path}.path",
                        data={"value": source_path},
                    )
                )
                continue
            if not isinstance(arcname, str) or not is_safe_relative_posix(arcname):
                issues.append(
                    _issue(
                        "DOWNLOAD_ARCHIVE_PATH_UNSAFE",
                        "Download archive name must be a safe relative POSIX path.",
                        path=f"{item_path}.arcname",
                        data={"value": arcname},
                    )
                )
                continue
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                issues.append(
                    _issue(
                        "DOWNLOAD_SOURCE_SIZE_INVALID",
                        "Download source size must be a non-negative integer.",
                        path=f"{item_path}.size",
                        data={"value": size},
                    )
                )
                continue
            arcname_key = arcname.casefold()
            duplicate_source = (
                delivery == "on_demand"
                and source_path in seen_paths
            )
            if duplicate_source or arcname_key in seen_arcnames:
                issues.append(
                    _issue(
                        "DOWNLOAD_FILE_DUPLICATE",
                        "Archive files must not repeat a source path or archive name.",
                        path=item_path,
                        data={"path": source_path, "arcname": arcname},
                    )
                )
                continue
            seen_paths.add(source_path)
            seen_arcnames.add(arcname_key)

            if delivery == "on_demand" and kind in MODULE_FILES:
                if not matches_module(PurePosixPath(source_path), kind) or not matches_module(
                    PurePosixPath(arcname), kind
                ):
                    issues.append(
                        _issue(
                            "DOWNLOAD_FILE_CLASSIFICATION_INVALID",
                            "On-demand module archives may contain only their whitelisted final deliverables.",
                            path=item_path,
                            data={"archive": kind, "path": source_path, "arcname": arcname},
                        )
                    )

            if require_sources:
                candidate = bundle_root / source_path
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(bundle_root)
                except (OSError, ValueError):
                    issues.append(
                        _issue(
                            "DOWNLOAD_SOURCE_PATH_ESCAPE",
                            "Download source resolves outside the Reel bundle.",
                            path=source_path,
                        )
                    )
                else:
                    if not resolved.is_file():
                        issues.append(
                            _issue(
                                "DOWNLOAD_SOURCE_MISSING",
                                "Download source listed in the manifest is missing.",
                                path=source_path,
                                data={"archive": kind},
                            )
                        )
                    elif resolved.stat().st_size != size:
                        issues.append(
                            _issue(
                                "DOWNLOAD_SOURCE_SIZE_MISMATCH",
                                "Download source size no longer matches the manifest.",
                                path=source_path,
                                data={
                                    "archive": kind,
                                    "actual": resolved.stat().st_size,
                                    "expected": size,
                                },
                            )
                        )
            valid_entries.append((source_path, arcname, size))
        normalized[kind] = valid_entries

    if delivery == "on_demand" and all(kind in normalized for kind in ARCHIVE_ORDER):
        expected_all: dict[str, tuple[str, str, int]] = {}
        for kind in ("poster", "video", "blog"):
            for entry in normalized[kind]:
                expected_all.setdefault(entry[1].casefold(), entry)
        actual_all = {
            entry[1].casefold(): entry
            for entry in normalized["all"]
        }
        if actual_all != expected_all:
            issues.append(
                _issue(
                    "DOWNLOAD_ALL_UNION_INVALID",
                    "The All archive must be the deduplicated union of Poster, Video, and Blog.",
                    path="archives.all.files",
                )
            )
    return issues


def read_download_manifest(bundle_root: Path) -> dict[str, Any]:
    manifest_path = bundle_root.resolve() / DOWNLOAD_MANIFEST_PATH
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"download manifest missing: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"download manifest is invalid JSON: {exc}") from exc
    issues = validate_download_manifest(payload, bundle_root=bundle_root)
    if issues:
        first = issues[0]
        raise ValueError(f"{first['code']}: {first['message']}")
    return payload


def archive_files(
    payload: dict[str, Any],
    kind: str,
    *,
    bundle_root: Path,
) -> tuple[str, list[tuple[Path, str]]]:
    """Resolve one validated on-demand archive to concrete source paths."""
    if kind not in ARCHIVE_ORDER:
        raise ValueError(f"unknown download archive: {kind}")
    if payload.get("delivery") != "on_demand":
        raise ValueError("dynamic downloads require delivery=on_demand")
    issues = validate_download_manifest(payload, bundle_root=bundle_root, require_sources=True)
    if issues:
        first = issues[0]
        raise ValueError(f"{first['code']}: {first['message']}")
    archive = payload["archives"][kind]
    files = [
        (bundle_root.resolve() / item["path"], item["arcname"])
        for item in archive["files"]
    ]
    return str(archive["filename"]), files


def archive_links(delivery: str) -> list[dict[str, str]]:
    """Return fixed-order viewer links for one delivery mode."""
    if delivery not in DOWNLOAD_DELIVERIES:
        raise ValueError(f"unsupported download delivery mode: {delivery}")
    return [
        {
            "label": ARCHIVE_META[kind]["label"],
            "href": (
                f"assets/downloads/{ARCHIVE_META[kind]['filename']}"
                if delivery == "materialized"
                else f"__download__/{kind}"
            ),
        }
        for kind in ARCHIVE_ORDER
    ]
