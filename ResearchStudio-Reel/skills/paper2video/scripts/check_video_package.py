#!/usr/bin/env python3
"""Quality gate for a paper2video package.

This checker is intentionally deterministic: it reads PPTX geometry, audio/video
metadata, visual-cue JSON, and the exported slide frames used by render_video.py.
It is not a replacement for human taste, but it catches the boring red-line
failures before a video is shown to users: missing audio, slide/audio drift,
blank frames, severe text-box overflow, obvious text/image overlap, cue timing
errors, and broken MP4 streams.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from PIL import Image, ImageStat
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageStat = None

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


EMU_PER_PT = 12700
EMU_PER_IN = 914400
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
SCHEMA_VERSION = "paper2video_qa.v1"
ANIMATION_MANIFEST_SCHEMA_VERSION = "paper2video_animation_manifest.v1"
ANIMATION_RENDER_REPORT_SCHEMA_VERSION = "paper2video_animation_render.v1"
ANIMATION_MIN_MEAN_ABS_DELTA = 0.12
ANIMATION_MIN_CHANGED_FRACTION = 0.002
ANIMATION_RENDER_STRATEGIES = {
    "Appear": "appear",
    "Fade In": "alpha_fade",
    "Dissolve In": "alpha_fade",
    "Fly In": "fly_from_left",
    "Wipe In": "wipe_from_left",
    "Zoom In": "zoom_in",
    "Circle In": "circle_reveal",
    "Diamond In": "diamond_reveal",
}
NON_BLOCKING_WARNING_CODES = frozenset({"audio_extra_files"})


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    location: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Box:
    slide_index: int
    kind: str
    name: str
    x: float
    y: float
    w: float
    h: float
    text: str = ""

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def add(findings: list[Finding], severity: str, code: str, message: str, *, location: str | None = None, **data: Any) -> None:
    findings.append(Finding(severity=severity, code=code, message=message, location=location, data=data))


def findings_pass_gate(
    findings: list[Finding],
    *,
    fail_on_warning: bool,
) -> bool:
    """Return whether findings pass the final package gate.

    Unreferenced MP3s remain visible in the report but do not invalidate the
    delivered timeline or MP4. Every other warning remains blocking when
    strict/fail-on-warning policy is active, and errors always block.
    """
    if any(finding.severity == "error" for finding in findings):
        return False
    if not fail_on_warning:
        return True
    return not any(
        finding.severity == "warning"
        and finding.code not in NON_BLOCKING_WARNING_CODES
        for finding in findings
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"[check_video_package] file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[check_video_package] invalid JSON {path}: {exc}")


def which(name: str) -> str | None:
    return shutil.which(name)


def imageio_ffmpeg_binary() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffmpeg_pair() -> tuple[str | None, str | None]:
    env_ffmpeg = os.getenv("PAPER2VIDEO_FFMPEG") or os.getenv("FFMPEG_BINARY")
    if env_ffmpeg and Path(env_ffmpeg).expanduser().is_file():
        env_ffprobe = os.getenv("PAPER2VIDEO_FFPROBE")
        if env_ffprobe and Path(env_ffprobe).expanduser().is_file():
            return str(Path(env_ffmpeg).expanduser()), str(Path(env_ffprobe).expanduser())
        return str(Path(env_ffmpeg).expanduser()), str(Path(env_ffmpeg).expanduser())

    fallback = imageio_ffmpeg_binary()
    if fallback:
        return fallback, fallback

    return which("ffmpeg"), which("ffprobe")


def find_libreoffice() -> str | None:
    return which("libreoffice") or which("soffice")


def find_pdftoppm() -> str | None:
    found = which("pdftoppm")
    if found:
        return found
    sibling = Path(sys.executable).resolve().parent / "pdftoppm"
    if sibling.is_file():
        return str(sibling)
    return None


def render_frames_from_pptx(pptx: Path, work_dir: Path, findings: list[Finding]) -> Path | None:
    """Export PPTX to slide PNGs for visual QA.

    This is a fallback for legacy packages that did not archive the actual
    render_video.py frames under assets/slides/frames.
    """
    libreoffice = find_libreoffice()
    pdftoppm = find_pdftoppm()
    if not libreoffice:
        add(findings, "error", "libreoffice_missing", "LibreOffice/soffice is required to render PPTX frames for QA.")
        return None
    if not pdftoppm:
        add(findings, "error", "pdftoppm_missing", "pdftoppm is required to rasterize the QA PDF into frames.")
        return None
    if not pptx.is_file():
        add(findings, "error", "pptx_missing_for_frame_render", "Cannot render frames because PPTX is missing.", location=str(pptx))
        return None

    qa_root = work_dir / ".video_qa"
    pdf_dir = qa_root / "pdf"
    frames_dir = qa_root / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    if pdf_dir.exists():
        shutil.rmtree(pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_dir:
        cmd = [
            libreoffice,
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless", "--norestore", "--nologo",
            "--convert-to", "pdf",
            "--outdir", str(pdf_dir),
            str(pptx),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            add(findings, "error", "pptx_frame_render_timeout", "LibreOffice timed out while exporting PPTX for QA frames.", location=str(pptx))
            return None
    if proc.returncode != 0:
        add(
            findings,
            "error",
            "pptx_frame_render_failed",
            "LibreOffice failed while exporting PPTX for QA frames.",
            location=str(pptx),
            stdout=proc.stdout[-1000:],
            stderr=proc.stderr[-1000:],
        )
        return None

    pdf = pdf_dir / f"{pptx.stem}.pdf"
    if not pdf.exists():
        add(findings, "error", "pptx_frame_pdf_missing", "LibreOffice did not produce the expected QA PDF.", location=str(pdf), stdout=proc.stdout[-1000:])
        return None

    cmd = [pdftoppm, "-png", "-r", "120", str(pdf), str(frames_dir / "slide")]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        add(findings, "error", "pptx_frame_raster_timeout", "pdftoppm timed out while rasterizing QA frames.", location=str(pdf))
        return None
    if proc.returncode != 0:
        add(findings, "error", "pptx_frame_raster_failed", "pdftoppm failed while rasterizing QA frames.", location=str(pdf), stderr=proc.stderr[-1000:])
        return None
    if not list(frames_dir.glob("slide-*.png")):
        add(findings, "error", "pptx_frame_output_empty", "Frame rasterization produced no PNG files.", location=str(frames_dir))
        return None
    return frames_dir


def probe_duration(path: Path, ffprobe: str | None, ffmpeg: str | None) -> float | None:
    if ffprobe and ffmpeg and ffprobe != ffmpeg:
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return float(proc.stdout.strip())
            except ValueError:
                pass
    if ffmpeg:
        proc = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True)
        match = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", proc.stderr)
        if match:
            return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    return None


def probe_video_streams(path: Path, ffprobe: str | None, ffmpeg: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"duration": None, "has_video": False, "has_audio": False}
    if ffprobe and ffmpeg and ffprobe != ffmpeg:
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            payload = json.loads(proc.stdout)
            try:
                out["duration"] = float(payload.get("format", {}).get("duration"))
            except (TypeError, ValueError):
                out["duration"] = None
            stream_types = {s.get("codec_type") for s in payload.get("streams", []) if isinstance(s, dict)}
            out["has_video"] = "video" in stream_types
            out["has_audio"] = "audio" in stream_types
            return out

    if ffmpeg:
        proc = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True)
        stderr = proc.stderr
        dur = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", stderr)
        if dur:
            out["duration"] = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
        out["has_video"] = "Video:" in stderr
        out["has_audio"] = "Audio:" in stderr
    return out


def natural_key(path: Path) -> list[Any]:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", path.stem)]


def load_script(script_json: Path) -> list[dict[str, str]]:
    payload = read_json(script_json)
    sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(sections, list) or not sections:
        raise SystemExit(f"[check_video_package] script JSON has no non-empty sections array: {script_json}")
    out: list[dict[str, str]] = []
    for i, sec in enumerate(sections, start=1):
        if not isinstance(sec, dict) or not sec.get("id"):
            raise SystemExit(f"[check_video_package] script section {i} is missing id")
        out.append({"id": str(sec["id"]), "heading": str(sec.get("heading") or ""), "text": str(sec.get("text") or "")})
    return out


def list_slide_xml_names(zf: zipfile.ZipFile) -> list[str]:
    try:
        presentation = ET.fromstring(zf.read("ppt/presentation.xml"))
        rels_root = ET.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
        rels = {
            rel.attrib.get("Id"): rel.attrib.get("Target")
            for rel in rels_root
            if rel.tag.rsplit("}", 1)[-1] == "Relationship"
        }
        ordered = []
        for sld_id in presentation.findall("p:sldIdLst/p:sldId", NS):
            rid = sld_id.attrib.get(f"{{{NS['r']}}}id")
            target = rels.get(rid)
            if not target:
                continue
            target = target.lstrip("/")
            if not target.startswith("ppt/"):
                target = f"ppt/{target}"
            if target in zf.namelist():
                ordered.append(target)
        if ordered:
            return ordered
    except Exception:
        pass

    names = [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
    return sorted(names, key=lambda n: int(re.search(r"slide(\d+)\.xml$", n).group(1)))  # type: ignore[union-attr]


def read_slide_size(zf: zipfile.ZipFile) -> tuple[int, int]:
    try:
        root = ET.fromstring(zf.read("ppt/presentation.xml"))
        sld_sz = root.find("p:sldSz", NS)
        if sld_sz is not None:
            return int(sld_sz.attrib.get("cx", "12192000")), int(sld_sz.attrib.get("cy", "6858000"))
    except Exception:
        pass
    return 12192000, 6858000


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def shape_name(el: ET.Element) -> str:
    nv = el.find(".//p:cNvPr", NS)
    if nv is not None:
        return nv.attrib.get("name") or nv.attrib.get("id") or local_name(el.tag)
    return local_name(el.tag)


def get_xfrm(el: ET.Element) -> tuple[float, float, float, float] | None:
    xfrm = el.find(".//a:xfrm", NS)
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    try:
        x = float(off.attrib.get("x", "0"))
        y = float(off.attrib.get("y", "0"))
        w = float(ext.attrib.get("cx", "0"))
        h = float(ext.attrib.get("cy", "0"))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def text_of(el: ET.Element) -> str:
    return "\n".join(t.text or "" for t in el.findall(".//a:t", NS)).strip()


def first_font_pt(el: ET.Element) -> float:
    sizes: list[float] = []
    for rpr in el.findall(".//a:rPr", NS):
        raw = rpr.attrib.get("sz")
        if raw and raw.isdigit():
            sizes.append(int(raw) / 100.0)
    if sizes:
        return max(6.0, min(max(sizes), 60.0))
    return 18.0


def body_margins_pt(el: ET.Element) -> tuple[float, float, float, float]:
    body_pr = el.find(".//a:bodyPr", NS)
    defaults = {"lIns": 91440, "rIns": 91440, "tIns": 45720, "bIns": 45720}
    vals = []
    for key in ("lIns", "rIns", "tIns", "bIns"):
        raw = body_pr.attrib.get(key) if body_pr is not None else None
        try:
            vals.append(float(raw if raw is not None else defaults[key]) / EMU_PER_PT)
        except ValueError:
            vals.append(defaults[key] / EMU_PER_PT)
    return tuple(vals)  # type: ignore[return-value]


def char_units(ch: str) -> float:
    if ch.isspace():
        return 0.34
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF:
        return 1.0
    if ch in "il.,:;|'!":
        return 0.28
    if ch in "MW@#%&":
        return 0.85
    return 0.55


def estimate_text_lines(text: str, width_pt: float, font_pt: float) -> int:
    if not text.strip():
        return 0
    max_units = max(width_pt / max(font_pt, 1.0), 1.0)
    lines = 0
    for para in re.split(r"\n+", text):
        units = sum(char_units(ch) for ch in para.strip())
        lines += max(1, math.ceil(units / max_units))
    return lines


def box_intersection(a: Box, b: Box) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def parse_pptx(pptx: Path, findings: list[Finding]) -> dict[str, Any]:
    if not pptx.is_file():
        add(findings, "error", "pptx_missing", "PPTX file is missing.", location=str(pptx))
        return {"slide_count": 0, "slides": []}

    slides: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(pptx) as zf:
            slide_names = list_slide_xml_names(zf)
            slide_w, slide_h = read_slide_size(zf)
            slide_area = max(float(slide_w) * float(slide_h), 1.0)
            for idx, name in enumerate(slide_names, start=1):
                root = ET.fromstring(zf.read(name))
                boxes: list[Box] = []
                for el in root.findall(".//p:sp", NS) + root.findall(".//p:pic", NS) + root.findall(".//p:graphicFrame", NS):
                    xfrm = get_xfrm(el)
                    if xfrm is None:
                        continue
                    kind = local_name(el.tag)
                    text = text_of(el) if kind == "sp" else ""
                    if kind == "sp" and text:
                        kind = "text"
                    elif kind == "pic":
                        kind = "image"
                    elif kind == "graphicFrame":
                        kind = "graphic"
                    boxes.append(Box(idx, kind, shape_name(el), *xfrm, text=text))

                    if text:
                        l_pt, r_pt, t_pt, b_pt = body_margins_pt(el)
                        font_pt = first_font_pt(el)
                        usable_w = max((xfrm[2] / EMU_PER_PT) - l_pt - r_pt, 1.0)
                        usable_h = max((xfrm[3] / EMU_PER_PT) - t_pt - b_pt, 1.0)
                        lines = estimate_text_lines(text, usable_w, font_pt)
                        needed_h = lines * font_pt * 1.16
                        ratio = needed_h / usable_h if usable_h else 99
                        if ratio > 1.22:
                            # Native SVG->PPTX conversion often represents
                            # intentionally single-line labels/cards as short
                            # text boxes whose text may visually extend within
                            # the designed row. Keep the XML estimate in the
                            # report for agent review, but only make it a hard
                            # finding when the estimate is extreme enough that
                            # it is likely to survive into the rendered frame.
                            compact_single_line = usable_h <= font_pt * 1.75 and len(text) <= 140
                            sev = "error" if ratio > 4.0 or (ratio > 3.8 and not compact_single_line) else "info"
                            add(
                                findings,
                                sev,
                                "ppt_text_overflow_risk",
                                "Text likely exceeds its PPTX text box.",
                                location=f"slide {idx}: {shape_name(el)}",
                                needed_height_pt=round(needed_h, 1),
                                box_height_pt=round(usable_h, 1),
                                overflow_ratio=round(ratio, 2),
                                font_pt=round(font_pt, 1),
                                text_preview=re.sub(r"\s+", " ", text)[:180],
                            )

                text_boxes = [b for b in boxes if b.kind == "text" and b.text.strip()]
                image_boxes = [b for b in boxes if b.kind in {"image", "graphic"}]
                visual_metrics = {
                    "visual_count": len(image_boxes),
                    "max_visual_axis_fill": 0.0,
                    "max_visual_area_ratio": 0.0,
                    "total_visual_area_ratio": 0.0,
                    "small_visual_count": 0,
                }
                if image_boxes:
                    axis_fills = [max(b.w / slide_w, b.h / slide_h) for b in image_boxes]
                    area_ratios = [b.area / slide_area for b in image_boxes]
                    visual_metrics = {
                        "visual_count": len(image_boxes),
                        "max_visual_axis_fill": round(max(axis_fills), 4),
                        "max_visual_area_ratio": round(max(area_ratios), 4),
                        "total_visual_area_ratio": round(sum(area_ratios), 4),
                        "small_visual_count": sum(1 for fill, area in zip(axis_fills, area_ratios) if fill < 0.24 and area < 0.035),
                    }
                    # Ignore purely textual/title slides, but when a slide does
                    # contain non-zero-area visuals they must be large enough to
                    # be useful in a 1080p video frame. SVG->PPTX conversion can
                    # leave zero-size graphicFrame placeholders; report those as
                    # info instead of failing strict QA on an invisible object.
                    meaningful_images = [
                        b for b in image_boxes
                        if (b.area / slide_area) >= 0.003 or max(b.w / slide_w, b.h / slide_h) >= 0.08
                    ]
                    small_meaningful_count = sum(
                        1
                        for b in meaningful_images
                        if max(b.w / slide_w, b.h / slide_h) < 0.24 and (b.area / slide_area) < 0.035
                    )
                    if meaningful_images and small_meaningful_count == len(meaningful_images):
                        add(
                            findings,
                            "warning",
                            "ppt_visuals_too_small",
                            "All picture/graphic elements on this slide are small; viewers may not be able to read them in the video.",
                            location=f"slide {idx}",
                            **visual_metrics,
                            meaningful_visual_count=len(meaningful_images),
                        )
                    if (
                        len(image_boxes) >= 1
                        and visual_metrics["max_visual_axis_fill"] < 0.30
                        and visual_metrics["total_visual_area_ratio"] < 0.075
                        and len(text_boxes) <= 4
                    ):
                        add(
                            findings,
                            "warning",
                            "slide_visual_story_too_small",
                            "Slide has a visual, but the visual story occupies too little of the slide.",
                            location=f"slide {idx}",
                            **visual_metrics,
                        )
                for a_i, a in enumerate(text_boxes):
                    for b in text_boxes[a_i + 1 :]:
                        inter = box_intersection(a, b)
                        if inter <= 0:
                            continue
                        overlap = inter / max(min(a.area, b.area), 1.0)
                        # Adjacent PPT text lines often have bounding boxes
                        # that overlap a little because each line carries font
                        # ascent/descent slack. Treat only heavy overlap as a
                        # red-line risk; lighter cases are usually normal line
                        # stacking, not visible collision.
                        if overlap > 0.55:
                            long_pair = len(a.text.strip()) > 80 or len(b.text.strip()) > 80
                            add(
                                findings,
                                "warning" if long_pair else "info",
                                "ppt_text_text_overlap",
                                "Two text boxes substantially overlap.",
                                location=f"slide {idx}",
                                first=a.name,
                                second=b.name,
                                overlap_ratio=round(overlap, 3),
                                first_preview=re.sub(r"\s+", " ", a.text)[:120],
                                second_preview=re.sub(r"\s+", " ", b.text)[:120],
                            )
                for text_box in text_boxes:
                    for obj in image_boxes:
                        inter = box_intersection(text_box, obj)
                        if inter <= 0:
                            continue
                        overlap = inter / max(min(text_box.area, obj.area), 1.0)
                        if overlap > 0.16:
                            obj_area_ratio = obj.area / slide_area
                            obj_axis_fill = max(obj.w / slide_w, obj.h / slide_h)
                            full_bleed_or_background = obj_area_ratio > 0.30 or obj_axis_fill > 0.75
                            small_visual_covered = obj_area_ratio < 0.08 and obj_axis_fill < 0.35 and overlap > 0.45
                            add(
                                findings,
                                "warning" if small_visual_covered and not full_bleed_or_background else "info",
                                "ppt_text_visual_overlap",
                                "Text overlaps a picture or graphic frame; verify this is intentional.",
                                location=f"slide {idx}",
                                text_box=text_box.name,
                                visual=obj.name,
                                overlap_ratio=round(overlap, 3),
                                visual_area_ratio=round(obj_area_ratio, 4),
                                visual_axis_fill=round(obj_axis_fill, 4),
                            )
                slides.append({
                    "index": idx,
                    "name": name,
                    "box_count": len(boxes),
                    "text_box_count": len(text_boxes),
                    "image_box_count": len(image_boxes),
                    "visual_metrics": visual_metrics,
                })
            return {"slide_count": len(slide_names), "slide_size": [slide_w, slide_h], "slides": slides}
    except zipfile.BadZipFile:
        add(findings, "error", "pptx_invalid_zip", "PPTX is not a readable zip archive.", location=str(pptx))
    except ET.ParseError as exc:
        add(findings, "error", "pptx_xml_parse_failed", f"Could not parse PPTX XML: {exc}", location=str(pptx))
    return {"slide_count": 0, "slides": slides}


def frame_foreground_metrics(rgb_image: Any) -> dict[str, Any] | None:
    if np is None:
        return None
    arr = np.asarray(rgb_image.convert("RGB")).astype(np.int16)
    height, width = arr.shape[:2]
    border = max(4, min(width, height) // 40)
    samples = np.concatenate(
        [
            arr[:border, :, :].reshape(-1, 3),
            arr[-border:, :, :].reshape(-1, 3),
            arr[:, :border, :].reshape(-1, 3),
            arr[:, -border:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    bg = np.median(samples, axis=0)
    diff = np.max(np.abs(arr - bg), axis=2)
    # Also treat dark ink on a white page as foreground even when border
    # sampling is imperfect because of colored title bars.
    dark_ink = np.max(arr, axis=2) < 238
    mask = (diff > 18) | dark_ink
    # Ignore a tiny outer rim; PDF rasterization can add antialiasing noise.
    rim = max(2, min(width, height) // 200)
    mask[:rim, :] = False
    mask[-rim:, :] = False
    mask[:, :rim] = False
    mask[:, -rim:] = False

    foreground = int(mask.sum())
    total = int(mask.size)
    ratio = foreground / max(total, 1)
    if foreground == 0:
        return {
            "foreground_ratio": 0.0,
            "content_bbox": None,
            "content_bbox_area_ratio": 0.0,
            "bottom_blank_ratio": 1.0,
            "edge_touch_ratio": 0.0,
        }
    ys, xs = np.where(mask)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bbox_area = ((x1 - x0 + 1) * (y1 - y0 + 1)) / max(total, 1)
    edge_band = max(6, min(width, height) // 80)
    edge_mask = np.zeros_like(mask)
    edge_mask[:edge_band, :] = True
    edge_mask[-edge_band:, :] = True
    edge_mask[:, :edge_band] = True
    edge_mask[:, -edge_band:] = True
    edge_touch = int((mask & edge_mask).sum()) / max(foreground, 1)
    return {
        "foreground_ratio": round(ratio, 5),
        "content_bbox": [round(x0 / width, 4), round(y0 / height, 4), round((x1 - x0 + 1) / width, 4), round((y1 - y0 + 1) / height, 4)],
        "content_bbox_area_ratio": round(bbox_area, 5),
        "bottom_blank_ratio": round(max(0, height - y1 - 1) / height, 5),
        "edge_touch_ratio": round(edge_touch, 5),
    }


def check_frames(
    frames_dir: Path | None,
    expected_count: int,
    findings: list[Finding],
    *,
    min_foreground_ratio: float = 0.006,
    sparse_foreground_ratio: float = 0.015,
    min_bbox_area_ratio: float = 0.055,
    sparse_bbox_area_ratio: float = 0.12,
) -> dict[str, Any]:
    if frames_dir is None:
        return {"checked": False, "frames": []}
    if not frames_dir.is_dir():
        add(findings, "warning", "frames_dir_missing", "Rendered frames directory is missing.", location=str(frames_dir))
        return {"checked": False, "frames": []}
    frames = sorted([p for p in frames_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}], key=natural_key)
    if expected_count and len(frames) != expected_count:
        add(findings, "error", "frame_count_mismatch", "Rendered frame count does not match PPTX slide count.", location=str(frames_dir), expected=expected_count, actual=len(frames))
    details = []
    if Image is None:
        add(findings, "warning", "pil_unavailable", "Pillow is not available; frame pixel checks were skipped.")
        return {"checked": False, "frames": [str(p) for p in frames]}
    if np is None:
        add(findings, "warning", "numpy_unavailable", "NumPy is not available; rendered-frame foreground checks were skipped.")
    first_size: tuple[int, int] | None = None
    for idx, frame in enumerate(frames, start=1):
        try:
            with Image.open(frame) as im:
                rgb = im.convert("RGB")
                stat = ImageStat.Stat(rgb)
                mean = sum(stat.mean) / 3.0
                var = sum(stat.var) / 3.0
                size = rgb.size
                if first_size is None:
                    first_size = size
                elif size != first_size:
                    add(findings, "error", "frame_size_mismatch", "Rendered frames have inconsistent dimensions.", location=str(frame), expected=first_size, actual=size)
                if var < 4.0 or mean < 3.0 or mean > 252.0:
                    add(findings, "error", "blank_or_near_blank_frame", "Rendered slide frame appears blank or nearly blank.", location=str(frame), mean=round(mean, 2), variance=round(var, 2))
                metrics = frame_foreground_metrics(rgb) if np is not None else None
                if metrics:
                    fg = float(metrics["foreground_ratio"])
                    bbox_area = float(metrics["content_bbox_area_ratio"])
                    bottom_blank = float(metrics["bottom_blank_ratio"])
                    edge_touch = float(metrics["edge_touch_ratio"])
                    if fg < min_foreground_ratio or bbox_area < min_bbox_area_ratio:
                        sev = "warning" if idx == 1 else "error"
                        add(
                            findings,
                            sev,
                            "rendered_slide_too_sparse",
                            "Rendered slide has very little visible foreground content.",
                            location=str(frame),
                            foreground_ratio=fg,
                            content_bbox_area_ratio=bbox_area,
                            content_bbox=metrics["content_bbox"],
                        )
                    elif fg < sparse_foreground_ratio or bbox_area < sparse_bbox_area_ratio:
                        add(
                            findings,
                            "warning",
                            "rendered_slide_sparse",
                            "Rendered slide content occupies a small part of the frame; check for over-shrunk images or excessive blank space.",
                            location=str(frame),
                            foreground_ratio=fg,
                            content_bbox_area_ratio=bbox_area,
                            content_bbox=metrics["content_bbox"],
                        )
                    if idx not in {1, len(frames)} and bottom_blank > 0.42 and bbox_area < 0.45:
                        add(
                            findings,
                            "warning",
                            "rendered_slide_bottom_blank",
                            "Rendered slide leaves a large blank band at the bottom.",
                            location=str(frame),
                            bottom_blank_ratio=bottom_blank,
                            content_bbox=metrics["content_bbox"],
                        )
                    if edge_touch > 0.08:
                        add(
                            findings,
                            "warning",
                            "rendered_slide_edge_touch",
                            "Visible content touches the slide edge; check for cropped text/images.",
                            location=str(frame),
                            edge_touch_ratio=edge_touch,
                        )
                details.append({"index": idx, "path": str(frame), "width": size[0], "height": size[1], "mean": round(mean, 2), "variance": round(var, 2), "foreground": metrics})
        except Exception as exc:
            add(findings, "error", "frame_read_failed", f"Could not read rendered frame: {exc}", location=str(frame))
    return {"checked": True, "frames": details}


def check_audio(audio_dir: Path | None, sections: list[dict[str, str]], ffprobe: str | None, ffmpeg: str | None, findings: list[Finding]) -> dict[str, Any]:
    if audio_dir is None:
        return {"checked": False, "files": []}
    if not audio_dir.is_dir():
        add(findings, "error", "audio_dir_missing", "Audio directory is missing.", location=str(audio_dir))
        return {"checked": False, "files": []}
    details = []
    for sec in sections:
        path = audio_dir / f"{sec['id']}.mp3"
        if not path.is_file():
            add(findings, "error", "audio_missing", "Expected MP3 for script section is missing.", location=str(path), section_id=sec["id"])
            continue
        duration = probe_duration(path, ffprobe, ffmpeg)
        if duration is None or duration <= 0:
            add(findings, "error", "audio_duration_invalid", "Could not probe a positive MP3 duration.", location=str(path), section_id=sec["id"])
        details.append({"id": sec["id"], "path": str(path), "duration": duration})
    extra = sorted(p.name for p in audio_dir.glob("*.mp3") if p.stem not in {s["id"] for s in sections})
    if extra:
        add(findings, "warning", "audio_extra_files", "Audio directory contains MP3s not referenced by script.json.", location=str(audio_dir), files=extra)
    return {"checked": True, "files": details, "total_duration": sum(float(d["duration"] or 0) for d in details)}


def normalized_point_error(point: Any) -> str | None:
    if not isinstance(point, list) or len(point) != 2:
        return "point must be normalized [x, y] coordinates"
    if not all(isinstance(v, (int, float)) for v in point):
        return "point values must be numeric"
    x, y = [float(v) for v in point]
    if x < 0 or x > 1 or y < 0 or y > 1:
        return "point is outside the slide canvas"
    return None


def normalized_box_error(box: Any) -> str | None:
    if not isinstance(box, list) or len(box) != 4:
        return "box must be normalized [x, y, w, h] coordinates"
    if not all(isinstance(v, (int, float)) for v in box):
        return "box values must be numeric"
    x, y, w, h = [float(v) for v in box]
    if w <= 0 or h <= 0:
        return "box width/height must be positive"
    if x >= 1 or y >= 1 or x + w <= 0 or y + h <= 0:
        return "box is completely outside the slide canvas"
    if x < -0.0001 or y < -0.0001 or x + w > 1.0001 or y + h > 1.0001:
        return "box extends outside the slide canvas"
    return None


def highlight_module_box_error(box: Any, role: str | None = None) -> str | None:
    """Reject word-sized boxes for presentation-style highlights."""
    if normalized_box_error(box):
        return None
    x, y, w, h = [float(v) for v in box]
    area = w * h
    role_l = str(role or "").lower()
    if area < 0.012 and role_l not in {"qr"}:
        return "highlight box is too small for presentation use; target a module, card, row, figure part, or bullet group instead of a word/short phrase"
    return None


def _accepted_plan_chunks_by_slide(cue_plan_path: Path | None) -> dict[int, list[dict[str, Any]]]:
    if cue_plan_path is None or not cue_plan_path.is_file():
        return {}
    payload = read_json(cue_plan_path)
    out: dict[int, list[dict[str, Any]]] = {}
    for slide in payload.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        try:
            slide_index = int(slide.get("index"))
        except (TypeError, ValueError):
            continue
        chunks = [
            chunk
            for chunk in (slide.get("chunks") or [])
            if isinstance(chunk, dict) and chunk.get("accepted")
        ]
        out[slide_index] = chunks
    return out


def _cue_matches_plan_chunk(cue: dict[str, Any], chunk: dict[str, Any], *, time_tolerance: float = 0.08) -> bool:
    target = str(cue.get("target") or "")
    if target and str(chunk.get("target") or "") != target:
        return False
    try:
        cue_start = float(cue.get("start", 0) or 0)
        cue_end = float(cue.get("end", 0) or 0)
        chunk_start = float(chunk.get("start", 0) or 0)
        chunk_end = float(chunk.get("end", 0) or 0)
    except (TypeError, ValueError):
        return False
    return abs(cue_start - chunk_start) <= time_tolerance and abs(cue_end - chunk_end) <= time_tolerance


def check_visual_cues(
    path: Path | None,
    sections: list[dict[str, str]],
    audio_report: dict[str, Any],
    pad_tail: float,
    findings: list[Finding],
    *,
    required: bool = False,
    cue_plan_path: Path | None = None,
    strict_attention: bool = False,
    min_slide_coverage: float = 0.85,
) -> dict[str, Any]:
    if path is None:
        if required:
            add(findings, "error", "visual_cues_required", "Visual-cue JSON is required for attention/highlight QA.")
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "visual_cues_missing", "Visual cues JSON is missing.", location=str(path))
        return {"checked": False}
    payload = read_json(path)
    slides = payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(slides, list):
        add(findings, "error", "visual_cues_schema", "Visual cues JSON must contain a slides array.", location=str(path))
        return {"checked": False}
    duration_by_id = {item["id"]: float(item["duration"] or 0) for item in audio_report.get("files", []) if item.get("id")}
    section_ids = {sec["id"] for sec in sections}
    section_by_index = {idx: sec["id"] for idx, sec in enumerate(sections, start=1)}
    accepted_plan_by_slide = _accepted_plan_chunks_by_slide(cue_plan_path)
    cue_count = 0
    box_cue_count = 0
    geometry_source_counts: Counter[str] = Counter()
    geometry_matched_count = 0
    geometry_field_errors = 0
    slides_with_cues: set[str] = set()
    empty_slides = 0
    cues_missing_plan_match = 0
    for slide in slides:
        if not isinstance(slide, dict):
            add(findings, "error", "visual_cues_slide_schema", "Each visual-cue slide entry must be an object.", location=str(path))
            continue
        sid = str(slide.get("id") or "")
        slide_index = None
        if slide.get("index") is not None:
            try:
                slide_index = int(slide["index"])
            except (TypeError, ValueError):
                add(findings, "error", "visual_cues_bad_index", "Visual cue slide index must be an integer.", location=str(path), index=slide.get("index"))
        if not sid and slide_index is not None:
            sid = section_by_index.get(slide_index, "")
        if sid and sid not in section_ids:
            add(findings, "warning", "visual_cues_unknown_section", "Visual cue slide id is not in script.json.", location=str(path), section_id=sid)
        cues = slide.get("cues") or []
        if not isinstance(cues, list):
            add(findings, "error", "visual_cues_cues_schema", "Visual cue slide entry has non-list cues.", location=str(path), section_id=sid)
            continue
        if not cues:
            empty_slides += 1
            if required or strict_attention:
                add(findings, "error", "visual_cues_empty_slide", "A slide has no visual attention cues.", location=str(path), section_id=sid)
        elif sid:
            slides_with_cues.add(sid)
        max_duration = duration_by_id.get(sid, 0) + pad_tail
        for cue in cues:
            cue_count += 1
            if not isinstance(cue, dict):
                add(findings, "error", "visual_cue_schema", "Each cue must be an object.", location=str(path), section_id=sid)
                continue
            cue_type = str(cue.get("type") or "highlight")
            try:
                start = float(cue.get("start", cue.get("at", 0)) or 0)
                end = float(cue.get("end", start + float(cue.get("duration", 0) or 0)) or 0)
            except (TypeError, ValueError):
                add(findings, "error", "visual_cue_bad_time", "Cue timing fields must be numeric.", location=str(path), section_id=sid, cue=cue)
                continue
            if start < -0.01 or end <= start:
                add(findings, "error", "visual_cue_bad_time", "Cue has invalid start/end timing.", location=str(path), section_id=sid, cue=cue)
            if max_duration > 0 and end > max_duration + 0.15:
                add(findings, "error", "visual_cue_time_overflow", "Cue extends beyond the matching audio segment.", location=str(path), section_id=sid, end=end, segment_duration=max_duration)
            point = cue.get("point")
            box = cue.get("box")
            if point is None and box is None:
                add(findings, "error", "visual_cue_missing_geometry", "Cue must include a normalized box or point.", location=str(path), section_id=sid, cue=cue)
            if point is not None:
                point_error = normalized_point_error(point)
                if point_error:
                    add(findings, "error", "visual_cue_bad_point", point_error, location=str(path), section_id=sid, cue=cue)
            if box is not None:
                box_error = normalized_box_error(box)
                if box_error:
                    add(findings, "error", "visual_cue_bad_box", box_error, location=str(path), section_id=sid, cue=cue)
                else:
                    box_cue_count += 1
                    module_error = highlight_module_box_error(box, str(cue.get("target_role") or ""))
                    if module_error:
                        severity = "error" if strict_attention else "warning"
                        add(findings, severity, "visual_cue_micro_box", module_error, location=str(path), section_id=sid, cue=cue)
            elif required and cue_type == "highlight":
                add(findings, "error", "visual_cue_highlight_missing_box", "Strict highlight cues must include the target region box.", location=str(path), section_id=sid, cue=cue)
            geometry_source = str(cue.get("geometry_source") or cue.get("target_source") or "").strip()
            if geometry_source:
                geometry_source_counts[geometry_source] += 1
            if cue.get("geometry_matched"):
                geometry_matched_count += 1
            if cue_type == "highlight" and strict_attention:
                geometry_box = cue.get("geometry_box")
                semantic_box = cue.get("semantic_box")
                if geometry_box is not None:
                    geometry_error = normalized_box_error(geometry_box)
                    if geometry_error:
                        geometry_field_errors += 1
                        add(findings, "error", "visual_cue_geometry_box_bad", geometry_error, location=str(path), section_id=sid, cue=cue)
                    elif box is not None:
                        try:
                            if any(abs(float(a) - float(b)) > 0.002 for a, b in zip(geometry_box, box)):
                                geometry_field_errors += 1
                                add(findings, "error", "visual_cue_geometry_box_mismatch", "geometry_box must match the rendered cue box.", location=str(path), section_id=sid, cue=cue)
                        except (TypeError, ValueError):
                            geometry_field_errors += 1
                if semantic_box is not None:
                    semantic_error = normalized_box_error(semantic_box)
                    if semantic_error:
                        geometry_field_errors += 1
                        add(findings, "error", "visual_cue_semantic_box_bad", semantic_error, location=str(path), section_id=sid, cue=cue)
                if geometry_source and geometry_source not in {"svg", "pptx", "pptx_cluster"}:
                    geometry_field_errors += 1
                    add(findings, "error", "visual_cue_geometry_source_unknown", "geometry_source must be svg, pptx, or pptx_cluster.", location=str(path), section_id=sid, cue=cue)
            if not str(cue.get("target") or "").strip():
                severity = "error" if strict_attention else "warning"
                add(findings, severity, "visual_cue_target_missing", "Cue is missing a semantic target id.", location=str(path), section_id=sid, cue=cue)
            if accepted_plan_by_slide and slide_index is not None:
                candidates = accepted_plan_by_slide.get(slide_index, [])
                if not any(_cue_matches_plan_chunk(cue, chunk) for chunk in candidates):
                    cues_missing_plan_match += 1
                    severity = "error" if strict_attention else "warning"
                    add(findings, severity, "visual_cue_not_in_plan", "Cue does not match an accepted chunk in visual_cue_plan.json.", location=str(path), section_id=sid, cue=cue)
    expected_sections = len(sections)
    coverage = len(slides_with_cues) / expected_sections if expected_sections else 0.0
    if required and coverage + 1e-9 < min_slide_coverage:
        add(
            findings,
            "error",
            "visual_cue_coverage_low",
            "Visual cues do not cover enough script sections for reliable highlight playback.",
            location=str(path),
            coverage=round(coverage, 3),
            required=min_slide_coverage,
            covered_sections=sorted(slides_with_cues),
            expected_sections=expected_sections,
        )
    if required and cue_count == 0:
        add(findings, "error", "visual_cue_count_zero", "No visual attention cues were produced.", location=str(path))
    return {
        "checked": True,
        "cue_count": cue_count,
        "box_cue_count": box_cue_count,
        "slide_entries": len(slides),
        "slides_with_cues": len(slides_with_cues),
        "empty_slide_entries": empty_slides,
        "cues_missing_plan_match": cues_missing_plan_match,
        "geometry_source_counts": dict(sorted(geometry_source_counts.items())),
        "geometry_matched_count": geometry_matched_count,
        "geometry_field_errors": geometry_field_errors,
        "coverage": round(coverage, 4),
    }


def check_cue_plan(
    path: Path | None,
    findings: list[Finding],
    *,
    required: bool = False,
    strict_attention: bool = False,
    require_word_timings: bool = False,
    min_acceptance_rate: float = 0.85,
) -> dict[str, Any]:
    if path is None:
        if required:
            add(findings, "error", "cue_plan_required", "Cue-plan JSON is required for attention/highlight QA.")
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "cue_plan_missing", "Visual cue plan JSON is missing.", location=str(path))
        return {"checked": False}
    payload = read_json(path)
    slides = payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(slides, list):
        add(findings, "error", "cue_plan_schema", "Cue plan must contain a slides array.", location=str(path))
        return {"checked": False}

    for err in payload.get("errors") or []:
        add(findings, "error", "cue_plan_error", "Cue planner reported an error.", location=str(path), detail=str(err))
    for warn in payload.get("warnings") or []:
        add(findings, "warning", "cue_plan_warning", "Cue planner reported a warning.", location=str(path), detail=str(warn))

    accepted = skipped = low_confidence = risky_targets = estimated_timing = 0
    missing_targets = missing_region_boxes = bad_region_boxes = bad_points = bad_timing = 0
    timing_source_counts: Counter[str] = Counter()
    low_timing_alignment = 0
    min_confidence = float(payload.get("min_confidence") or 0)
    for slide in slides:
        if not isinstance(slide, dict):
            add(findings, "error", "cue_plan_slide_schema", "Cue plan slide entry must be an object.", location=str(path))
            continue
        timing_source = str(slide.get("timing_source") or "unknown")
        timing_source_counts[timing_source] += 1
        if timing_source == "duration_proportional":
            estimated_timing += 1
        chunks = slide.get("chunks") or []
        if not isinstance(chunks, list):
            add(findings, "error", "cue_plan_chunks_schema", "Cue plan slide chunks must be an array.", location=str(path), section_id=slide.get("id"))
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                add(findings, "error", "cue_plan_chunk_schema", "Cue plan chunk must be an object.", location=str(path), section_id=slide.get("id"))
                continue
            try:
                start = float(chunk.get("start"))
                end = float(chunk.get("end"))
            except (TypeError, ValueError):
                bad_timing += 1
                add(findings, "error", "cue_plan_bad_time", "Cue-plan chunk start/end must be numeric.", location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"))
                start = end = None
            if start is not None and end is not None and end <= start:
                bad_timing += 1
                add(findings, "error", "cue_plan_bad_time", "Cue-plan chunk end must be after start.", location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), start=start, end=end)
            timing = chunk.get("timing") if isinstance(chunk.get("timing"), dict) else {}
            if require_word_timings and timing_source.startswith("edge_word_"):
                score = timing.get("score")
                if isinstance(score, (int, float)) and float(score) < 0.58:
                    low_timing_alignment += 1
                    add(findings, "error", "cue_plan_low_timing_alignment", "Cue timing text alignment score is too low.", location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), score=score, timing=timing)
            if chunk.get("accepted"):
                accepted += 1
                conf = float(chunk.get("confidence") or 0)
                if conf < min_confidence:
                    low_confidence += 1
                    add(findings, "error", "cue_plan_low_confidence", "Accepted cue is below the plan confidence threshold.", location=str(path), section_id=slide.get("id"), confidence=conf, target=chunk.get("target"))
                if str(chunk.get("target_role") or "") in {"header", "caption", "chrome", "footer", "background"}:
                    risky_targets += 1
                    severity = "error" if strict_attention else "warning"
                    add(findings, severity, "cue_plan_risky_target", "Accepted cue points at slide chrome/header/caption and needs review.", location=str(path), section_id=slide.get("id"), target=chunk.get("target"), role=chunk.get("target_role"))
                if not str(chunk.get("target") or "").strip():
                    missing_targets += 1
                    severity = "error" if strict_attention else "warning"
                    add(findings, severity, "cue_plan_target_missing", "Accepted cue is missing a semantic target id.", location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"))
                box = chunk.get("region_box")
                if box is None:
                    missing_region_boxes += 1
                    severity = "error" if strict_attention else "warning"
                    add(findings, severity, "cue_plan_region_box_missing", "Accepted cue is missing the target region box.", location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), target=chunk.get("target"))
                else:
                    box_error = normalized_box_error(box)
                    if box_error:
                        bad_region_boxes += 1
                        add(findings, "error", "cue_plan_region_box_bad", box_error, location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), target=chunk.get("target"), region_box=box)
                    else:
                        module_error = highlight_module_box_error(box, str(chunk.get("target_role") or ""))
                        if module_error:
                            bad_region_boxes += 1
                            severity = "error" if strict_attention else "warning"
                            add(findings, severity, "cue_plan_micro_box", module_error, location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), target=chunk.get("target"), region_box=box)
                point = chunk.get("point")
                if point is not None:
                    point_error = normalized_point_error(point)
                    if point_error:
                        bad_points += 1
                        add(findings, "error", "cue_plan_point_bad", point_error, location=str(path), section_id=slide.get("id"), chunk_index=chunk.get("chunk_index"), target=chunk.get("target"), point=point)
            else:
                skipped += 1
    if estimated_timing:
        severity = "error" if require_word_timings else "warning"
        add(findings, severity, "cue_plan_estimated_timing", "Cue plan uses proportional timing instead of word-boundary timing.", location=str(path), slide_count=estimated_timing)
    total_chunks = accepted + skipped
    acceptance_rate = accepted / total_chunks if total_chunks else 0.0
    if required and total_chunks == 0:
        add(findings, "error", "cue_plan_empty", "Cue plan contains no cue chunks.", location=str(path))
    if strict_attention and skipped:
        add(findings, "error", "cue_plan_skipped_chunks", "Cue planner skipped one or more narration chunks; highlight timing cannot be trusted.", location=str(path), skipped_chunks=skipped)
    if strict_attention and acceptance_rate + 1e-9 < min_acceptance_rate:
        add(
            findings,
            "error",
            "cue_plan_acceptance_low",
            "Cue-plan acceptance rate is below the strict attention threshold.",
            location=str(path),
            accepted_chunks=accepted,
            skipped_chunks=skipped,
            acceptance_rate=round(acceptance_rate, 3),
            required=min_acceptance_rate,
        )
    return {
        "checked": True,
        "accepted_chunks": accepted,
        "skipped_chunks": skipped,
        "low_confidence": low_confidence,
        "risky_targets": risky_targets,
        "missing_targets": missing_targets,
        "missing_region_boxes": missing_region_boxes,
        "bad_region_boxes": bad_region_boxes,
        "bad_points": bad_points,
        "bad_timing_chunks": bad_timing,
        "timing_source_counts": dict(sorted(timing_source_counts.items())),
        "low_timing_alignment": low_timing_alignment,
        "estimated_timing_slides": estimated_timing,
        "acceptance_rate": round(acceptance_rate, 4),
    }


def _contract_chunks(payload: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for slide in payload.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        try:
            slide_index = int(slide.get("index"))
        except (TypeError, ValueError):
            continue
        for chunk in slide.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            try:
                chunk_index = int(chunk.get("chunk_index"))
            except (TypeError, ValueError):
                continue
            out[(slide_index, chunk_index)] = chunk
    return out


def _cue_plan_chunks(path: Path | None) -> dict[tuple[int, int], dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    payload = read_json(path)
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for slide in payload.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        try:
            slide_index = int(slide.get("index"))
        except (TypeError, ValueError):
            continue
        for chunk in slide.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            try:
                chunk_index = int(chunk.get("chunk_index"))
            except (TypeError, ValueError):
                continue
            out[(slide_index, chunk_index)] = chunk
    return out


def check_anchor_contract(
    path: Path | None,
    cue_plan_path: Path | None,
    findings: list[Finding],
    *,
    required: bool = False,
    strict_attention: bool = False,
    require_pptx_anchors: bool = False,
) -> dict[str, Any]:
    if path is None:
        if required:
            add(findings, "error", "anchor_contract_required", "Visual anchor contract is required for strict attention QA.")
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "anchor_contract_missing", "Visual anchor contract is missing.", location=str(path))
        return {"checked": False}
    payload = read_json(path)
    if not isinstance(payload, dict):
        add(findings, "error", "anchor_contract_schema", "Visual anchor contract must be a JSON object.", location=str(path))
        return {"checked": False}
    if payload.get("schema_version") not in {"paper2video_visual_anchor_contract.v1", "paper2video_cue_requirements.v1"}:
        add(findings, "error", "anchor_contract_schema_version", "Visual anchor contract has an unsupported schema_version.", location=str(path), schema_version=payload.get("schema_version"))

    contract = _contract_chunks(payload)
    required_chunks = {key: chunk for key, chunk in contract.items() if chunk.get("required", True)}
    missing_anchor_ids = 0
    for (slide_index, chunk_index), chunk in required_chunks.items():
        if not str(chunk.get("anchor_id") or "").strip():
            missing_anchor_ids += 1
            add(findings, "error", "anchor_contract_chunk_missing_anchor", "Required contract chunk is missing anchor_id.", location=str(path), slide_index=slide_index, chunk_index=chunk_index)

    plan = _cue_plan_chunks(cue_plan_path)
    matched = unmatched = missing_in_plan = non_pptx_matches = 0
    if cue_plan_path is not None and cue_plan_path.is_file():
        for key, chunk in required_chunks.items():
            expected = str(chunk.get("anchor_id") or "").strip()
            if not expected:
                continue
            planned = plan.get(key)
            if not planned:
                missing_in_plan += 1
                add(findings, "error" if strict_attention else "warning", "anchor_contract_chunk_missing_in_plan", "Anchor contract chunk is missing from cue plan.", location=str(path), slide_index=key[0], chunk_index=key[1], anchor_id=expected)
                continue
            actual = str(planned.get("anchor_id") or "").strip()
            if actual != expected:
                add(findings, "error" if strict_attention else "warning", "anchor_contract_id_mismatch", "Cue plan anchor_id does not match the visual anchor contract.", location=str(path), slide_index=key[0], chunk_index=key[1], expected_anchor=expected, actual_anchor=actual)
            if planned.get("anchor_matched") and planned.get("accepted"):
                matched += 1
                if require_pptx_anchors and str(planned.get("target_source") or "") != "pptx":
                    non_pptx_matches += 1
                    add(findings, "error", "anchor_contract_non_pptx_match", "Anchor matched outside PPTX, but PPTX anchors were explicitly required for this QA run.", location=str(path), slide_index=key[0], chunk_index=key[1], anchor_id=expected, target_source=planned.get("target_source"))
            else:
                unmatched += 1
                add(findings, "error" if strict_attention else "warning", "anchor_contract_unmatched", "Required visual anchor was not matched by the cue plan.", location=str(path), slide_index=key[0], chunk_index=key[1], anchor_id=expected, reason=planned.get("reason"))
    elif required or strict_attention:
        add(findings, "error", "anchor_contract_cue_plan_missing", "Cue plan is required to validate the visual anchor contract.", location=str(path))

    return {
        "checked": True,
        "required_chunks": len(required_chunks),
        "missing_anchor_ids": missing_anchor_ids,
        "matched_chunks": matched,
        "unmatched_chunks": unmatched,
        "missing_in_plan": missing_in_plan,
        "non_pptx_matches": non_pptx_matches,
    }


def check_timeline(
    path: Path | None,
    findings: list[Finding],
    *,
    required: bool = False,
    strict_attention: bool = False,
) -> dict[str, Any]:
    if path is None:
        if required:
            add(findings, "error", "timeline_required", "timeline.json is required to bind audio, subtitles, and visual cues.")
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "timeline_missing", "timeline.json is missing.", location=str(path))
        return {"checked": False}
    payload = read_json(path)
    if not isinstance(payload, dict):
        add(findings, "error", "timeline_schema", "timeline.json must be a JSON object.", location=str(path))
        return {"checked": False}
    if payload.get("schema_version") != "paper2video_timeline.v1":
        add(findings, "error", "timeline_schema_version", "timeline.json has an unsupported schema_version.", location=str(path), schema_version=payload.get("schema_version"))
    slides = payload.get("slides") or []
    chunks = payload.get("chunks") or []
    sections = payload.get("sections") or []
    if not isinstance(slides, list) or not isinstance(chunks, list) or not isinstance(sections, list):
        add(findings, "error", "timeline_schema", "timeline.json must contain slides, sections, and chunks arrays.", location=str(path))
        return {"checked": True, "slide_count": 0, "section_count": 0, "chunk_count": 0}

    slide_windows: dict[int, tuple[float, float]] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        try:
            idx = int(slide.get("index"))
            segment = slide.get("segment") or {}
            slide_windows[idx] = (float(segment.get("start")), float(segment.get("end")))
        except (TypeError, ValueError):
            continue

    chunk_ids: set[str] = set()
    subtitle_chunks = 0
    visual_chunks = 0
    bad_time_chunks = 0
    missing_subtitles = 0
    missing_visuals = 0
    visual_geometry_errors = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            add(findings, "error", "timeline_chunk_schema", "Timeline chunk entry must be an object.", location=str(path))
            continue
        cid = str(chunk.get("id") or "")
        if not cid:
            add(findings, "error", "timeline_chunk_id_missing", "Timeline chunk is missing a stable id.", location=str(path), chunk=chunk)
        elif cid in chunk_ids:
            add(findings, "error", "timeline_chunk_id_duplicate", "Timeline chunk id is duplicated.", location=str(path), chunk_id=cid)
        chunk_ids.add(cid)
        try:
            start = float(chunk.get("start"))
            end = float(chunk.get("end"))
        except (TypeError, ValueError):
            add(findings, "error", "timeline_chunk_time_bad", "Timeline chunk start/end must be numeric.", location=str(path), chunk_id=cid)
            bad_time_chunks += 1
            continue
        if end <= start:
            add(findings, "error", "timeline_chunk_time_bad", "Timeline chunk end must be after start.", location=str(path), chunk_id=cid, start=start, end=end)
            bad_time_chunks += 1
        try:
            slide_index = int(chunk.get("slide_index"))
        except (TypeError, ValueError):
            slide_index = 0
        if slide_index in slide_windows:
            slide_start, slide_end = slide_windows[slide_index]
            if start < slide_start - 0.05 or end > slide_end + 0.05:
                add(
                    findings,
                    "error",
                    "timeline_chunk_outside_slide_window",
                    "Timeline chunk timing falls outside its slide segment window.",
                    location=str(path),
                    chunk_id=cid,
                    slide_index=slide_index,
                    chunk_window=[round(start, 3), round(end, 3)],
                    slide_window=[round(slide_start, 3), round(slide_end, 3)],
                )
                bad_time_chunks += 1
        subtitles = chunk.get("subtitles") or []
        if subtitles:
            subtitle_chunks += 1
        else:
            missing_subtitles += 1
            add(findings, "warning", "timeline_chunk_no_subtitles", "Timeline chunk has no subtitle cues.", location=str(path), chunk_id=cid)
        visual = chunk.get("visual_cue")
        if isinstance(visual, dict) and visual.get("accepted") and (visual.get("region_box") or visual.get("point")):
            visual_chunks += 1
            if visual.get("region_box") is not None:
                box_error = normalized_box_error(visual.get("region_box"))
                if box_error:
                    visual_geometry_errors += 1
                    add(findings, "error", "timeline_visual_box_bad", box_error, location=str(path), chunk_id=cid, region_box=visual.get("region_box"))
            if visual.get("point") is not None:
                point_error = normalized_point_error(visual.get("point"))
                if point_error:
                    visual_geometry_errors += 1
                    add(findings, "error", "timeline_visual_point_bad", point_error, location=str(path), chunk_id=cid, point=visual.get("point"))
            if strict_attention and not str(visual.get("target") or "").strip():
                add(findings, "error", "timeline_visual_target_missing", "Timeline visual cue is missing a semantic target id.", location=str(path), chunk_id=cid)
        else:
            missing_visuals += 1
            if strict_attention:
                add(findings, "error", "timeline_chunk_no_visual_cue", "Timeline chunk has no accepted visual cue.", location=str(path), chunk_id=cid)

    slide_indices: set[int] = set()
    for slide in slides:
        if not isinstance(slide, dict):
            add(findings, "error", "timeline_slide_schema", "Timeline slide entry must be an object.", location=str(path))
            continue
        try:
            idx = int(slide.get("index"))
        except (TypeError, ValueError):
            add(findings, "error", "timeline_slide_index_bad", "Timeline slide index must be an integer.", location=str(path), slide=slide)
            continue
        if idx in slide_indices:
            add(findings, "error", "timeline_slide_index_duplicate", "Timeline slide index is duplicated.", location=str(path), slide_index=idx)
        slide_indices.add(idx)

    section_windows = []
    for section in sections:
        if not isinstance(section, dict):
            add(findings, "error", "timeline_section_schema", "Timeline section entry must be an object.", location=str(path))
            continue
        sid = str(section.get("id") or "")
        if not sid:
            add(findings, "error", "timeline_section_id_missing", "Timeline section is missing id.", location=str(path))
            continue
        try:
            start = float(section.get("start"))
            end = float(section.get("end"))
        except (TypeError, ValueError):
            add(findings, "error", "timeline_section_time_bad", "Timeline section start/end must be numeric.", location=str(path), section_id=sid)
            continue
        if end <= start:
            add(findings, "error", "timeline_section_time_bad", "Timeline section end must be after start.", location=str(path), section_id=sid, start=start, end=end)
        section_slide_indices: set[int] = set()
        for idx in section.get("slide_indices") or []:
            try:
                section_slide_indices.add(int(idx))
            except (TypeError, ValueError):
                add(findings, "error", "timeline_section_slide_index_bad", "Timeline section slide_indices must be integers.", location=str(path), section_id=sid, slide_index=idx)
        if sid != "title":
            section_windows.append((start, end, sid, section_slide_indices))
        for cid in section.get("chunk_ids") or []:
            if str(cid) not in chunk_ids:
                add(findings, "error", "timeline_section_unknown_chunk", "Timeline section references a missing chunk id.", location=str(path), section_id=sid, chunk_id=cid)

    section_windows.sort()
    for (prev_start, prev_end, prev_id, prev_slides), (start, end, sid, slides_for_section) in zip(section_windows, section_windows[1:]):
        if start < prev_end - 0.05:
            shared_slides = sorted(prev_slides & slides_for_section)
            if shared_slides:
                continue
            add(
                findings,
                "warning",
                "timeline_section_overlap",
                "Non-title timeline sections overlap; visualization clips may play unexpected content.",
                location=str(path),
                first=prev_id,
                second=sid,
                first_window=[round(prev_start, 3), round(prev_end, 3)],
                second_window=[round(start, 3), round(end, 3)],
            )

    return {
        "checked": True,
        "section_count": len(sections),
        "slide_count": len(slides),
        "chunk_count": len(chunks),
        "chunks_with_subtitles": subtitle_chunks,
        "chunks_with_visual_cues": visual_chunks,
        "missing_subtitle_chunks": missing_subtitles,
        "missing_visual_cue_chunks": missing_visuals,
        "visual_geometry_errors": visual_geometry_errors,
        "bad_time_chunks": bad_time_chunks,
    }


def check_rate_plan(
    path: Path | None,
    findings: list[Finding],
    *,
    required: bool = False,
    max_adjust_percent: float = 8.0,
) -> dict[str, Any]:
    if path is None:
        if required:
            add(findings, "error", "tts_rate_plan_required", "TTS rate plan is required for duration-controlled video.")
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "tts_rate_plan_missing", "TTS rate plan is missing.", location=str(path))
        return {"checked": False}
    payload = read_json(path)
    if not isinstance(payload, dict):
        add(findings, "error", "tts_rate_plan_schema", "TTS rate plan must be a JSON object.", location=str(path))
        return {"checked": False}
    if payload.get("schema_version") != "paper2video_tts_rate_plan.v1":
        add(findings, "error", "tts_rate_plan_schema_version", "TTS rate plan has an unsupported schema_version.", location=str(path), schema_version=payload.get("schema_version"))
    status = str(payload.get("status") or "")
    safe = bool(payload.get("safe"))
    try:
        recommended = abs(float(payload.get("recommended_adjust_percent") or 0.0))
        required_adjust = abs(float(payload.get("required_adjust_percent") or 0.0))
    except (TypeError, ValueError):
        add(findings, "error", "tts_rate_plan_bad_adjustment", "TTS rate adjustment fields must be numeric.", location=str(path))
        recommended = required_adjust = 0.0
    if status == "needs_script_rewrite":
        add(findings, "error", "tts_rate_requires_script_rewrite", "Duration mismatch is too large for safe TTS rate adjustment; rewrite script first.", location=str(path), required_adjust_percent=round(required_adjust, 3))
    elif not safe:
        add(findings, "error", "tts_rate_plan_unsafe", "TTS rate plan is marked unsafe.", location=str(path), status=status)
    if recommended > max_adjust_percent + 1e-9:
        add(findings, "error", "tts_rate_adjustment_too_large", "Recommended TTS rate adjustment is too large for natural speech.", location=str(path), recommended_adjust_percent=round(recommended, 3), max_adjust_percent=max_adjust_percent)
    elif recommended > 6.0:
        add(findings, "warning", "tts_rate_adjustment_borderline", "Recommended TTS rate adjustment is audible; prefer script rewrite if quality matters.", location=str(path), recommended_adjust_percent=round(recommended, 3))
    return {
        "checked": True,
        "status": status,
        "safe": safe,
        "recommended_edge_rate": payload.get("recommended_edge_rate"),
        "recommended_adjust_percent": payload.get("recommended_adjust_percent"),
        "required_adjust_percent": payload.get("required_adjust_percent"),
        "current_delta_seconds": payload.get("current_delta_seconds"),
    }


def check_video(path: Path | None, target_minutes: float | None, tolerance_seconds: float, ffprobe: str | None, ffmpeg: str | None, findings: list[Finding]) -> dict[str, Any]:
    if path is None:
        return {"checked": False}
    if not path.is_file():
        add(findings, "error", "video_missing", "Final MP4 is missing.", location=str(path))
        return {"checked": False}
    streams = probe_video_streams(path, ffprobe, ffmpeg)
    if not streams.get("has_video"):
        add(findings, "error", "video_stream_missing", "MP4 has no video stream.", location=str(path))
    if not streams.get("has_audio"):
        add(findings, "error", "audio_stream_missing", "MP4 has no audio stream.", location=str(path))
    duration = streams.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        add(findings, "error", "video_duration_invalid", "Could not probe a positive MP4 duration.", location=str(path))
    elif target_minutes is not None:
        target_seconds = target_minutes * 60
        delta = abs(duration - target_seconds)
        if delta > tolerance_seconds:
            add(findings, "error", "video_duration_out_of_tolerance", "Final MP4 duration is outside the requested tolerance.", location=str(path), duration=round(duration, 2), target_seconds=round(target_seconds, 2), tolerance_seconds=tolerance_seconds)
    return {"checked": True, **streams}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_subtitle_cues(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", text))


def check_subtitle_delivery(
    *,
    raw_mp4: Path | None,
    final_mp4: Path | None,
    subtitle_file: Path | None,
    required: bool,
    ffprobe: str | None,
    ffmpeg: str | None,
    findings: list[Finding],
) -> dict[str, Any]:
    if not required:
        return {"checked": False}
    report: dict[str, Any] = {
        "checked": True,
        "raw_mp4": str(raw_mp4) if raw_mp4 else None,
        "final_mp4": str(final_mp4) if final_mp4 else None,
        "subtitle_file": str(subtitle_file) if subtitle_file else None,
    }
    if raw_mp4 is None:
        add(findings, "error", "subtitle_raw_mp4_required", "--raw-mp4 is required when --require-subtitles is set.")
    elif not raw_mp4.is_file():
        add(findings, "error", "subtitle_raw_mp4_missing", "Raw pre-subtitle MP4 is missing.", location=str(raw_mp4))
    if final_mp4 is None:
        add(findings, "error", "subtitle_final_mp4_required", "--mp4 final video is required when --require-subtitles is set.")
    elif not final_mp4.is_file():
        add(findings, "error", "subtitle_final_mp4_missing", "Final subtitled MP4 is missing.", location=str(final_mp4))
    if subtitle_file is None:
        add(findings, "error", "subtitle_sidecar_required", "--subtitle-file is required when --require-subtitles is set.")
    elif not subtitle_file.is_file():
        add(findings, "error", "subtitle_sidecar_missing", "Subtitle sidecar file is missing.", location=str(subtitle_file))
    else:
        cue_count = count_subtitle_cues(subtitle_file)
        report["cue_count"] = cue_count
        if cue_count <= 0:
            add(findings, "error", "subtitle_sidecar_empty", "Subtitle sidecar has no timestamped cues.", location=str(subtitle_file))

    if raw_mp4 and final_mp4 and raw_mp4.exists() and final_mp4.exists():
        same_path = raw_mp4.resolve() == final_mp4.resolve()
        report["same_path"] = same_path
        if same_path:
            add(findings, "error", "subtitle_final_is_raw", "Final MP4 points at the raw render; add_subtitles.py was not applied.", location=str(final_mp4))
        elif raw_mp4.stat().st_size == final_mp4.stat().st_size and sha256_file(raw_mp4) == sha256_file(final_mp4):
            add(findings, "error", "subtitle_final_identical_to_raw", "Final MP4 is byte-identical to the raw render; subtitles were likely skipped.", location=str(final_mp4))
        raw_streams = probe_video_streams(raw_mp4, ffprobe, ffmpeg)
        final_streams = probe_video_streams(final_mp4, ffprobe, ffmpeg)
        raw_duration = raw_streams.get("duration")
        final_duration = final_streams.get("duration")
        report["raw_duration"] = raw_duration
        report["final_duration"] = final_duration
        if isinstance(raw_duration, (int, float)) and isinstance(final_duration, (int, float)):
            delta = abs(float(final_duration) - float(raw_duration))
            report["duration_delta"] = round(delta, 3)
            if delta > 2.0:
                add(findings, "warning", "subtitle_duration_drift", "Final subtitled MP4 duration differs from raw render by more than 2 seconds.", location=str(final_mp4), raw_duration=round(float(raw_duration), 3), final_duration=round(float(final_duration), 3))
    return report


def check_subtitle_word_alignment(
    path: Path | None,
    *,
    required: bool,
    pad_tail: float,
    findings: list[Finding],
) -> dict[str, Any]:
    """Validate fail-closed subtitle evidence from actual Edge word boundaries."""
    if path is None:
        if required:
            add(
                findings,
                "error",
                "subtitle_word_alignment_required",
                "Strict subtitle delivery requires a word-alignment timing report.",
            )
        return {"checked": False}
    if not path.is_file():
        add(
            findings,
            "error",
            "subtitle_word_alignment_missing",
            "Subtitle word-alignment timing report is missing.",
            location=str(path),
        )
        return {"checked": False}
    payload = read_json(path)
    if not isinstance(payload, dict):
        add(
            findings,
            "error",
            "subtitle_word_alignment_schema",
            "Subtitle timing report must be a JSON object.",
            location=str(path),
        )
        return {"checked": False}
    if payload.get("schema_version") != "paper2video_subtitle_word_alignment.v1":
        add(
            findings,
            "error",
            "subtitle_word_alignment_schema_version",
            "Subtitle timing report has an unsupported schema version.",
            location=str(path),
        )
    status = str(payload.get("status") or "")
    if required and status != "word_aligned":
        add(
            findings,
            "error",
            "subtitle_timing_estimated",
            "Final subtitles are not fully aligned to actual Edge word boundaries.",
            location=str(path),
            status=status,
        )
    sections = payload.get("sections") or []
    if not isinstance(sections, list):
        add(
            findings,
            "error",
            "subtitle_word_alignment_sections_schema",
            "Subtitle timing report sections must be an array.",
            location=str(path),
        )
        sections = []
    cue_count = 0
    previous_slide_end: float | None = None
    for section_index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            add(
                findings,
                "error",
                "subtitle_word_alignment_section_schema",
                "Subtitle timing section must be an object.",
                location=str(path),
                section_index=section_index,
            )
            continue
        source = str(section.get("timing_source") or "")
        cues = section.get("cues") or []
        try:
            slide_start = float(section.get("slide_start"))
            audio_duration = float(section.get("audio_duration"))
        except (TypeError, ValueError):
            add(
                findings,
                "error",
                "subtitle_word_alignment_section_time",
                "Subtitle timing section has invalid slide/audio times.",
                location=str(path),
                section_index=section_index,
            )
            continue
        if previous_slide_end is not None and abs(slide_start - previous_slide_end) > 0.003:
            add(
                findings,
                "error",
                "subtitle_slide_offset_mismatch",
                "Subtitle page offset does not match prior audio duration plus pad tail.",
                location=str(path),
                section_index=section_index,
                expected=round(previous_slide_end, 3),
                actual=round(slide_start, 3),
            )
        previous_slide_end = slide_start + audio_duration + max(0.0, pad_tail)
        if source == "silent":
            if cues:
                add(
                    findings,
                    "error",
                    "subtitle_silent_section_has_cues",
                    "A silent subtitle section unexpectedly contains cues.",
                    location=str(path),
                    section_index=section_index,
                )
            continue
        if source != "edge_word_boundary":
            add(
                findings,
                "error" if required else "warning",
                "subtitle_section_estimated_timing",
                "Subtitle section uses estimated timing instead of Edge word boundaries.",
                location=str(path),
                section_index=section_index,
                timing_source=source,
            )
        if not isinstance(cues, list) or not cues:
            add(
                findings,
                "error",
                "subtitle_word_alignment_cues_missing",
                "Narrated subtitle section has no alignment cues.",
                location=str(path),
                section_index=section_index,
            )
            continue
        previous_cue_end = -1.0
        for cue_index, cue in enumerate(cues, start=1):
            cue_count += 1
            if not isinstance(cue, dict):
                add(
                    findings,
                    "error",
                    "subtitle_word_alignment_cue_schema",
                    "Subtitle timing cue must be an object.",
                    location=str(path),
                    section_index=section_index,
                    cue_index=cue_index,
                )
                continue
            try:
                relative_start = float(cue.get("relative_start"))
                relative_end = float(cue.get("relative_end"))
                absolute_start = float(cue.get("absolute_start"))
                absolute_end = float(cue.get("absolute_end"))
                word_start = int(cue.get("word_start"))
                word_end = int(cue.get("word_end"))
            except (TypeError, ValueError):
                add(
                    findings,
                    "error",
                    "subtitle_word_alignment_cue_time",
                    "Subtitle timing cue lacks valid word/time boundaries.",
                    location=str(path),
                    section_index=section_index,
                    cue_index=cue_index,
                )
                continue
            if (
                cue.get("timing_source") != "edge_word_boundary"
                or relative_start < 0.0
                or relative_end < relative_start
                or word_end < word_start
                or relative_start + 1e-6 < previous_cue_end
                or abs(absolute_start - (slide_start + relative_start)) > 0.003
                or abs(absolute_end - (slide_start + relative_end)) > 0.003
                or relative_end > audio_duration + 0.05
            ):
                add(
                    findings,
                    "error",
                    "subtitle_word_alignment_cue_mismatch",
                    "Subtitle cue is not an exact monotonic Edge word interval.",
                    location=str(path),
                    section_index=section_index,
                    cue_index=cue_index,
                )
            previous_cue_end = relative_end
    try:
        declared_cues = int(payload.get("cue_count") or 0)
    except (TypeError, ValueError):
        declared_cues = -1
    if cue_count != declared_cues:
        add(
            findings,
            "error",
            "subtitle_word_alignment_cue_count",
            "Subtitle timing report cue count does not match its sections.",
            location=str(path),
            expected=declared_cues,
            actual=cue_count,
        )
    return {
        "checked": True,
        "status": status,
        "section_count": len(sections),
        "cue_count": cue_count,
    }


def _animation_effects(
    payload: dict[str, Any],
    *,
    findings: list[Finding],
    path: Path,
    label: str,
) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    slides = payload.get("slides") or []
    if not isinstance(slides, list):
        add(findings, "error", f"{label}_slides_schema", f"{label} slides must be an array.", location=str(path))
        return out
    for slide in slides:
        if not isinstance(slide, dict):
            add(findings, "error", f"{label}_slide_schema", f"{label} slide entries must be objects.", location=str(path))
            continue
        try:
            slide_index = int(slide.get("index"))
        except (TypeError, ValueError):
            add(findings, "error", f"{label}_slide_index_bad", f"{label} slide index must be an integer.", location=str(path))
            continue
        effects = slide.get("effects") or []
        if not isinstance(effects, list):
            add(findings, "error", f"{label}_effects_schema", f"{label} effects must be an array.", location=str(path), slide_index=slide_index)
            continue
        for effect in effects:
            if not isinstance(effect, dict):
                add(findings, "error", f"{label}_effect_schema", f"{label} effect entries must be objects.", location=str(path), slide_index=slide_index)
                continue
            try:
                order = int(effect.get("order"))
            except (TypeError, ValueError):
                add(findings, "error", f"{label}_effect_order_bad", f"{label} effect order must be an integer.", location=str(path), slide_index=slide_index)
                continue
            key = (slide_index, order)
            if key in out:
                add(findings, "error", f"{label}_effect_duplicate", f"{label} contains a duplicate slide/order effect key.", location=str(path), slide_index=slide_index, order=order)
                continue
            out[key] = effect
    return out


def _extract_animation_sample_frames(
    raw_mp4: Path,
    frame_numbers: list[int],
    ffmpeg: str,
    output_dir: Path,
) -> dict[int, Path]:
    unique = sorted(set(frame_numbers))
    if not unique:
        return {}
    select_expr = "+".join(f"eq(n\\,{number})" for number in unique)
    pattern = output_dir / "sample-%04d.png"
    cmd = [
        ffmpeg,
        "-v", "error",
        "-i", str(raw_mp4),
        "-vf", f"select={select_expr}",
        "-vsync", "0",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] or "ffmpeg sample extraction failed")
    paths = sorted(output_dir.glob("sample-*.png"))
    if len(paths) != len(unique):
        raise RuntimeError(
            f"ffmpeg extracted {len(paths)} animation samples, expected {len(unique)}"
        )
    return dict(zip(unique, paths))


def _animation_pixel_delta(
    early_path: Path,
    late_path: Path,
    bbox: list[int],
) -> tuple[float, float]:
    if Image is None:
        raise RuntimeError("Pillow is required for animation pixel QA")
    with Image.open(early_path) as early_source, Image.open(late_path) as late_source:
        early = early_source.convert("RGB")
        late = late_source.convert("RGB")
        if early.size != late.size:
            raise RuntimeError("animation sample frames have mismatched dimensions")
        x, y, width, height = bbox
        x0 = max(0, min(early.width - 1, x))
        y0 = max(0, min(early.height - 1, y))
        x1 = max(x0 + 1, min(early.width, x + width))
        y1 = max(y0 + 1, min(early.height, y + height))
        early_crop = early.crop((x0, y0, x1, y1))
        late_crop = late.crop((x0, y0, x1, y1))
        if np is not None:
            early_array = np.asarray(early_crop, dtype=np.int16)
            late_array = np.asarray(late_crop, dtype=np.int16)
            delta = np.abs(late_array - early_array)
            mean_abs = float(delta.mean())
            changed_fraction = float((delta.max(axis=2) >= 8).mean())
            return mean_abs, changed_fraction

        from PIL import ImageChops  # type: ignore

        diff = ImageChops.difference(early_crop, late_crop)
        mean_abs = float(sum(ImageStat.Stat(diff).mean) / 3.0)
        gray = diff.convert("L")
        histogram = gray.histogram()
        pixels = max(1, gray.width * gray.height)
        changed_fraction = float(sum(histogram[8:]) / pixels)
        return mean_abs, changed_fraction


def _check_pptx_sequence_schedule(
    manifest: dict[str, Any],
    *,
    path: Path,
    findings: list[Finding],
) -> dict[str, Any]:
    """Reject the mixed absolute clocks that previously allowed early overlap."""
    checked_blocks = 0
    checked_effects = 0
    gate_violations = 0
    for slide in manifest.get("slides") or []:
        slide_index = int(slide.get("index") or 0)
        if slide.get("schedule_policy") != "author_notes_block_sequence_v1":
            add(findings, "error", "animation_sequence_policy_missing", "Editable PPTX animation manifest is missing the unified Notes/Pane sequence policy.", location=str(path), slide_index=slide_index)
            continue
        blocks = slide.get("sequence_blocks") or []
        prior_release = 0.0
        for expected_index, block in enumerate(blocks, start=1):
            checked_blocks += 1
            try:
                block_index = int(block.get("index"))
                release_before = float(block.get("release_before"))
                spoken_end = float(block.get("spoken_end"))
                release = float(block.get("release"))
            except (TypeError, ValueError):
                add(findings, "error", "animation_sequence_block_bad", "Animation sequence block has invalid timing fields.", location=str(path), slide_index=slide_index, block=block)
                continue
            if block_index != expected_index:
                add(findings, "error", "animation_sequence_block_order", "Animation sequence block indices are not contiguous.", location=str(path), slide_index=slide_index, expected=expected_index, actual=block_index)
            if abs(release_before - prior_release) > 0.002:
                add(findings, "error", "animation_sequence_release_chain", "Animation sequence block does not start from the prior block release.", location=str(path), slide_index=slide_index, block_index=block_index, expected=prior_release, actual=release_before)
            required_release = max(release_before, spoken_end)
            for effect in block.get("effects") or []:
                checked_effects += 1
                try:
                    start = float(effect.get("start"))
                    end = float(effect.get("end"))
                    gate = float(effect.get("sequence_gate"))
                except (TypeError, ValueError):
                    add(findings, "error", "animation_sequence_effect_bad", "Animation sequence effect has invalid timing fields.", location=str(path), slide_index=slide_index, block_index=block_index, effect=effect)
                    continue
                if end <= start:
                    add(findings, "error", "animation_sequence_effect_window", "Animation sequence effect has a non-positive window.", location=str(path), slide_index=slide_index, block_index=block_index, effect=effect)
                if abs(gate - release_before) > 0.002:
                    add(findings, "error", "animation_sequence_gate_mismatch", "Animation effect sequence gate differs from its block release gate.", location=str(path), slide_index=slide_index, block_index=block_index, expected=release_before, actual=gate)
                trigger = str(effect.get("pane_trigger") or "").lower()
                timing_source = str(effect.get("timing_source") or "")
                overlap_allowed = timing_source == "animation_pane" and trigger == "witheffect"
                if not overlap_allowed and start + 0.002 < release_before:
                    gate_violations += 1
                    add(findings, "error", "animation_sequence_gate_violated", "A sequential animation starts before the prior Notes block narration/effects release.", location=str(path), slide_index=slide_index, block_index=block_index, handle=block.get("handle"), start=start, required_start=release_before)
                required_release = max(required_release, end)
            if release + 0.002 < required_release:
                add(findings, "error", "animation_sequence_release_early", "Animation block releases the following block before its narration/effects finish.", location=str(path), slide_index=slide_index, block_index=block_index, release=release, required_release=required_release)
            prior_release = release
        try:
            schedule_end = float(slide.get("schedule_end"))
        except (TypeError, ValueError):
            add(findings, "error", "animation_sequence_end_bad", "Animation sequence has no valid schedule_end.", location=str(path), slide_index=slide_index)
        else:
            if abs(schedule_end - prior_release) > 0.002:
                add(findings, "error", "animation_sequence_end_mismatch", "Animation sequence end differs from the final block release.", location=str(path), slide_index=slide_index, expected=prior_release, actual=schedule_end)
    return {
        "schedule_policy": "author_notes_block_sequence_v1",
        "checked_blocks": checked_blocks,
        "checked_effects": checked_effects,
        "gate_violations": gate_violations,
    }


def check_animation_delivery(
    *,
    manifest_path: Path | None,
    render_report_path: Path | None,
    raw_mp4: Path | None,
    pptx_path: Path | None = None,
    required: bool,
    ffmpeg: str | None,
    findings: list[Finding],
) -> dict[str, Any]:
    """Cross-check animation mappings and prove each transition changes MP4 pixels."""
    if manifest_path is None and render_report_path is None:
        if required:
            add(findings, "error", "animations_required", "Strict animation QA requires --animation-manifest and --animation-report.")
        return {"checked": False}
    if manifest_path is None:
        add(findings, "error", "animation_manifest_required", "--animation-manifest is required when checking animations.")
        return {"checked": False}
    if render_report_path is None:
        add(findings, "error", "animation_report_required", "--animation-report is required when checking animations.")
        return {"checked": False}
    if not manifest_path.is_file():
        add(findings, "error", "animation_manifest_missing", "Animation manifest is missing.", location=str(manifest_path))
        return {"checked": False}
    if not render_report_path.is_file():
        add(findings, "error", "animation_report_missing", "Animation render report is missing.", location=str(render_report_path))
        return {"checked": False}

    manifest = read_json(manifest_path)
    render_report = read_json(render_report_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != ANIMATION_MANIFEST_SCHEMA_VERSION:
        add(findings, "error", "animation_manifest_schema", "Animation manifest has an unsupported schema.", location=str(manifest_path), schema_version=manifest.get("schema_version") if isinstance(manifest, dict) else None)
        return {"checked": True}
    if not isinstance(render_report, dict) or render_report.get("schema_version") != ANIMATION_RENDER_REPORT_SCHEMA_VERSION:
        add(findings, "error", "animation_report_schema", "Animation render report has an unsupported schema.", location=str(render_report_path), schema_version=render_report.get("schema_version") if isinstance(render_report, dict) else None)
        return {"checked": True}

    source_kind = str(manifest.get("source_kind") or "svg")
    report_source_kind = str(render_report.get("source_kind") or "svg")
    if source_kind not in {"svg", "pptx"}:
        add(findings, "error", "animation_source_kind_bad", "Animation manifest has an unsupported source_kind.", location=str(manifest_path), source_kind=source_kind)
    if report_source_kind != source_kind:
        add(findings, "error", "animation_source_kind_mismatch", "Animation render source_kind does not match the manifest.", location=str(render_report_path), manifest_source_kind=source_kind, report_source_kind=report_source_kind)
    if source_kind == "pptx":
        sequence_schedule = _check_pptx_sequence_schedule(
            manifest,
            path=manifest_path,
            findings=findings,
        )
        manifest_sha = str(manifest.get("source_sha256") or "")
        report_sha = str(render_report.get("source_sha256") or "")
        if not manifest_sha or report_sha != manifest_sha:
            add(findings, "error", "animation_pptx_hash_mismatch", "Editable PPTX manifest and render report do not name the same source hash.", location=str(render_report_path), manifest_sha256=manifest_sha, report_sha256=report_sha)
        if pptx_path is None or not pptx_path.is_file():
            add(findings, "error", "animation_pptx_required", "Editable PPTX animation QA requires the delivered --pptx source.", location=str(pptx_path) if pptx_path else None)
        elif manifest_sha and sha256_file(pptx_path) != manifest_sha:
            add(findings, "error", "animation_pptx_delivery_stale", "Delivered PPTX bytes differ from the deck used to build and render animations.", location=str(pptx_path), expected_sha256=manifest_sha, actual_sha256=sha256_file(pptx_path))

    else:
        sequence_schedule = {"checked_blocks": 0, "checked_effects": 0, "gate_violations": 0}

    manifest_effects = _animation_effects(manifest, findings=findings, path=manifest_path, label="animation_manifest")
    rendered_effects = _animation_effects(render_report, findings=findings, path=render_report_path, label="animation_report")
    manifest_slides = manifest.get("slides") or []
    rendered_slides = render_report.get("slides") or []
    manifest_declared = int(manifest.get("effect_count") or 0)
    rendered_declared = int(render_report.get("effect_count") or 0)
    if int(manifest.get("slide_count") or 0) != len(manifest_slides):
        add(findings, "error", "animation_manifest_slide_count", "Animation manifest slide_count does not match its slides array.", location=str(manifest_path))
    if int(render_report.get("slide_count") or 0) != len(rendered_slides):
        add(findings, "error", "animation_report_slide_count", "Animation render slide_count does not match its slides array.", location=str(render_report_path))
    if manifest_declared != len(manifest_effects):
        add(findings, "error", "animation_manifest_effect_count", "Animation manifest effect_count does not match its effects.", location=str(manifest_path), declared=manifest_declared, actual=len(manifest_effects))
    if rendered_declared != len(rendered_effects):
        add(findings, "error", "animation_report_effect_count", "Animation render effect_count does not match its effects.", location=str(render_report_path), declared=rendered_declared, actual=len(rendered_effects))
    if set(manifest_effects) != set(rendered_effects):
        missing = sorted(set(manifest_effects) - set(rendered_effects))
        extra = sorted(set(rendered_effects) - set(manifest_effects))
        add(findings, "error", "animation_effect_coverage", "Rendered animation effect keys do not exactly cover the manifest.", location=str(render_report_path), missing=missing, extra=extra)

    resolution = render_report.get("resolution") or {}
    try:
        render_width = int(resolution.get("width"))
        render_height = int(resolution.get("height"))
        fps = float(render_report.get("fps"))
    except (TypeError, ValueError):
        render_width = render_height = 0
        fps = 0.0
    if render_width <= 0 or render_height <= 0 or fps <= 0:
        add(findings, "error", "animation_report_video_geometry", "Animation render report has invalid resolution or fps.", location=str(render_report_path))

    valid_effects: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for key, expected in manifest_effects.items():
        actual = rendered_effects.get(key)
        if actual is None:
            continue
        locator = str(expected.get("locator") or "").strip()
        name = str(expected.get("name") or "").strip()
        if str(actual.get("locator") or "").strip() != locator or str(actual.get("name") or "").strip() != name:
            add(findings, "error", "animation_effect_mapping_mismatch", "Rendered animation locator/name does not match the manifest.", location=str(render_report_path), slide_index=key[0], order=key[1], expected_locator=locator, actual_locator=actual.get("locator"), expected_name=name, actual_name=actual.get("name"))
            continue
        if source_kind == "pptx":
            expected_shape_id = str(expected.get("shape_id") or "").strip()
            actual_shape_id = str(actual.get("shape_id") or "").strip()
            if not expected_shape_id or actual_shape_id != expected_shape_id:
                add(findings, "error", "animation_shape_mapping_mismatch", "Rendered editable PPTX shape_id does not match the manifest.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, expected_shape_id=expected_shape_id, actual_shape_id=actual_shape_id)
                continue
        expected_strategy = ANIMATION_RENDER_STRATEGIES.get(name)
        if expected_strategy is None:
            add(findings, "error", "animation_effect_unsupported", "Animation manifest names an effect unsupported by the video renderer.", location=str(manifest_path), slide_index=key[0], order=key[1], locator=locator, name=name)
            continue
        if str(actual.get("strategy") or "") != expected_strategy:
            add(findings, "error", "animation_strategy_mismatch", "Animation render strategy does not match the named Author Notes effect.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, name=name, expected_strategy=expected_strategy, actual_strategy=actual.get("strategy"))
            continue
        expected_timing_source = str(expected.get("timing_source") or "")
        actual_timing_source = str(actual.get("timing_source") or "")
        if expected_timing_source not in {"edge_word_alignment", "animation_pane"}:
            add(findings, "error", "animation_timing_source_unsupported", "Animation effect has an unsupported timing source.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, timing_source=expected_timing_source)
        elif actual_timing_source != expected_timing_source:
            add(findings, "error", "animation_timing_source_mismatch", "Rendered animation timing source does not match the manifest.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, expected=expected_timing_source, actual=actual_timing_source)
        try:
            expected_start = float(expected.get("start"))
            expected_duration = float(expected.get("duration"))
            actual_start = float(actual.get("start"))
            actual_duration = float(actual.get("duration"))
        except (TypeError, ValueError):
            add(findings, "error", "animation_effect_timing_bad", "Animation effect timing fields must be numeric.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator)
            continue
        if abs(expected_start - actual_start) > 0.002 or abs(expected_duration - actual_duration) > 0.002:
            add(findings, "error", "animation_effect_timing_mismatch", "Rendered animation timing does not match the manifest.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, expected=[expected_start, expected_duration], actual=[actual_start, actual_duration])
        bbox = actual.get("bbox")
        bbox_valid = isinstance(bbox, list) and len(bbox) == 4
        if bbox_valid:
            try:
                bbox = [int(round(float(value))) for value in bbox]
            except (TypeError, ValueError):
                bbox_valid = False
        if not bbox_valid or bbox[2] <= 0 or bbox[3] <= 0 or bbox[0] < 0 or bbox[1] < 0 or bbox[0] + bbox[2] > render_width or bbox[1] + bbox[3] > render_height:
            add(findings, "error", "animation_effect_bbox_bad", "Rendered animation bbox is invalid or outside the video canvas.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, bbox=actual.get("bbox"))
            continue
        if not actual.get("rendered"):
            add(findings, "error", "animation_effect_not_rendered", "Animation report does not mark the effect as rendered.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator)
            continue
        try:
            global_start = float(actual.get("global_start"))
            global_end = float(actual.get("global_end"))
            sample_early = float(actual.get("sample_early"))
            sample_late = float(actual.get("sample_late"))
        except (TypeError, ValueError):
            add(findings, "error", "animation_sample_time_bad", "Animation render report sample and global times must be numeric.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator)
            continue
        if expected_strategy == "appear":
            sample_window_valid = sample_early < global_start < sample_late
        else:
            sample_window_valid = (
                global_start <= sample_early < sample_late <= global_end
            )
        if not sample_window_valid:
            add(findings, "error", "animation_sample_window_bad", "Animation pixel-QA samples do not cover the named effect transition.", location=str(render_report_path), slide_index=key[0], order=key[1], locator=locator, strategy=expected_strategy, global_window=[global_start, global_end], sample_window=[sample_early, sample_late])
            continue
        valid_effects.append((key, actual))

    pixel_checked = 0
    pixel_changed = 0
    pixel_metrics: list[dict[str, Any]] = []
    if valid_effects:
        if raw_mp4 is None or not raw_mp4.is_file():
            add(findings, "error", "animation_raw_video_required", "Raw no-subtitle MP4 is required for animation pixel QA.", location=str(raw_mp4) if raw_mp4 else None)
        elif not ffmpeg:
            add(findings, "error", "animation_ffmpeg_required", "ffmpeg is required for animation pixel QA.")
        elif Image is None:
            add(findings, "error", "animation_pillow_required", "Pillow is required for animation pixel QA.")
        elif fps > 0:
            frame_pairs: dict[tuple[int, int], tuple[int, int]] = {}
            frame_numbers: list[int] = []
            for key, effect in valid_effects:
                try:
                    early_number = max(0, int(round(float(effect.get("sample_early")) * fps)))
                    late_number = max(0, int(round(float(effect.get("sample_late")) * fps)))
                except (TypeError, ValueError):
                    add(findings, "error", "animation_sample_time_bad", "Animation sample times must be numeric.", location=str(render_report_path), slide_index=key[0], order=key[1])
                    continue
                if late_number <= early_number:
                    late_number = early_number + 1
                frame_pairs[key] = (early_number, late_number)
                frame_numbers.extend((early_number, late_number))
            try:
                with tempfile.TemporaryDirectory(prefix="paper2video_animation_qa_") as temp_dir:
                    frame_paths = _extract_animation_sample_frames(raw_mp4, frame_numbers, ffmpeg, Path(temp_dir))
                    for key, effect in valid_effects:
                        if key not in frame_pairs:
                            continue
                        early_number, late_number = frame_pairs[key]
                        bbox = [int(round(float(value))) for value in effect["bbox"]]
                        mean_abs, changed_fraction = _animation_pixel_delta(
                            frame_paths[early_number], frame_paths[late_number], bbox
                        )
                        pixel_checked += 1
                        # Sparse full-width groups such as a one-pixel grid can
                        # be visibly animated while changing well under 1% of
                        # their bbox. Keep both an intensity and coverage gate.
                        changed = (
                            mean_abs >= ANIMATION_MIN_MEAN_ABS_DELTA
                            or changed_fraction >= ANIMATION_MIN_CHANGED_FRACTION
                        )
                        if changed:
                            pixel_changed += 1
                        else:
                            add(findings, "error", "animation_pixel_motion_missing", "Animation transition frames do not show enough pixel change inside the mapped SVG layer.", location=str(raw_mp4), slide_index=key[0], order=key[1], locator=effect.get("locator"), name=effect.get("name"), mean_abs_delta=round(mean_abs, 4), changed_fraction=round(changed_fraction, 6))
                        pixel_metrics.append(
                            {
                                "slide_index": key[0],
                                "order": key[1],
                                "locator": effect.get("locator"),
                                "name": effect.get("name"),
                                "early_frame": early_number,
                                "late_frame": late_number,
                                "mean_abs_delta": round(mean_abs, 4),
                                "changed_fraction": round(changed_fraction, 6),
                                "changed": changed,
                            }
                        )
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                add(findings, "error", "animation_pixel_check_failed", f"Could not extract or compare animation transition frames: {exc}", location=str(raw_mp4))

    if required and (not manifest_effects or len(manifest_effects) != len(rendered_effects)):
        add(findings, "error", "animation_delivery_incomplete", "Required animation delivery has no effects or incomplete effect coverage.", location=str(render_report_path))
    if required and pixel_checked != len(manifest_effects):
        add(findings, "error", "animation_pixel_coverage_incomplete", "Pixel QA did not check every required animation effect.", location=str(raw_mp4) if raw_mp4 else None, expected=len(manifest_effects), checked=pixel_checked)

    return {
        "checked": True,
        "source_kind": source_kind,
        "manifest_slide_count": len(manifest_slides),
        "rendered_slide_count": len(rendered_slides),
        "manifest_effect_count": len(manifest_effects),
        "rendered_effect_count": len(rendered_effects),
        "pixel_checked_effects": pixel_checked,
        "pixel_changed_effects": pixel_changed,
        "timing_source": render_report.get("timing_source"),
        "sequence_schedule": sequence_schedule,
        "pixel_metrics": pixel_metrics,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel_to(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def maybe_write_manifest(project_dir: Path, args: argparse.Namespace, report_path: Path, passed: bool) -> None:
    files: dict[str, str] = {
        "assets_dir": "assets",
        "audio_dir": "assets/audio",
        "captions_dir": "assets/captions",
        "slides_dir": "assets/slides",
        "clips_dir": "assets/clips",
        "meta_dir": "assets/meta",
        "qa_report": rel_to(report_path, project_dir),
    }
    if args.mp4:
        files["video"] = rel_to(args.mp4.resolve(), project_dir)
    if args.raw_mp4:
        files["video_no_subtitles"] = rel_to(args.raw_mp4.resolve(), project_dir)
    if args.pptx:
        files["slides_pptx"] = rel_to(args.pptx.resolve(), project_dir)
    if args.script_json:
        files["script_json"] = rel_to(args.script_json.resolve(), project_dir)
    if args.subtitle_file:
        files["captions_vtt"] = rel_to(args.subtitle_file.resolve(), project_dir)
    if args.timeline:
        files["timeline"] = rel_to(args.timeline.resolve(), project_dir)
    if args.visual_cues:
        files["visual_cues"] = rel_to(args.visual_cues.resolve(), project_dir)
    if args.cue_plan:
        files["visual_cue_plan"] = rel_to(args.cue_plan.resolve(), project_dir)
    if args.animation_manifest:
        files["animation_manifest"] = rel_to(args.animation_manifest.resolve(), project_dir)
    if args.animation_report:
        files["animation_render_report"] = rel_to(args.animation_report.resolve(), project_dir)

    manifest = {
        "schema_version": "paper2video.v1",
        "layout": "v2-assets",
        "created_at": utc_now(),
        "files": files,
        "qa": {
            "check": "check_video_package",
            "passed": passed,
            "report": rel_to(report_path, project_dir),
        },
    }
    write_report(project_dir / "manifest.json", manifest)


def default_report_path(project_dir: Path) -> Path:
    return project_dir / "assets" / "meta" / "reports" / "video_qa_report.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic QA gates for a paper2video package.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--pptx", type=Path, required=True)
    parser.add_argument("--script-json", type=Path, required=True)
    parser.add_argument("--audio-dir", type=Path)
    parser.add_argument("--frames-dir", type=Path, help="Rendered slide PNG/JPG directory. Defaults to <project>/assets/slides/frames when present.")
    parser.add_argument("--visual-cues", type=Path)
    parser.add_argument("--cue-plan", type=Path, help="visual_cue_plan.json written by generate_visual_cues.py.")
    parser.add_argument("--anchor-contract", type=Path, help="visual_anchor_contract.json written by generate_cue_requirements.py.")
    parser.add_argument("--timeline", type=Path, help="timeline.json written by build_timeline.py.")
    parser.add_argument("--rate-plan", type=Path, help="tts_rate_plan.json written by plan_tts_rate.py.")
    parser.add_argument("--mp4", type=Path)
    parser.add_argument("--raw-mp4", type=Path, help="Raw MP4 before add_subtitles.py; used to verify final subtitle delivery.")
    parser.add_argument("--subtitle-file", type=Path, help="SRT/VTT sidecar written by add_subtitles.py.")
    parser.add_argument("--subtitle-timing-report", type=Path, help="Exact Edge word-alignment evidence written by add_subtitles.py.")
    parser.add_argument("--animation-manifest", type=Path, help="Author Notes animation manifest used by render_video.py.")
    parser.add_argument("--animation-report", type=Path, help="Persistent animation render report written by render_video.py.")
    parser.add_argument("--target-minutes", type=float)
    parser.add_argument("--duration-tolerance-seconds", type=float, default=30.0)
    parser.add_argument("--pad-tail", type=float, default=0.3)
    parser.add_argument("--no-render-frames", action="store_true", help="Do not auto-render PPTX frames for visual QA when --frames-dir is omitted.")
    parser.add_argument("--require-audio", action="store_true", help="Fail when --audio-dir is omitted.")
    parser.add_argument("--require-mp4", action="store_true", help="Fail when --mp4 is omitted.")
    parser.add_argument("--require-visual-cues", action="store_true", help="Fail when --visual-cues is omitted or coverage is low.")
    parser.add_argument("--require-cue-plan", action="store_true", help="Fail when --cue-plan is omitted.")
    parser.add_argument("--require-anchor-contract", action="store_true", help="Fail when visual anchor contract is omitted.")
    parser.add_argument("--require-timeline", action="store_true", help="Fail when timeline.json is omitted or invalid.")
    parser.add_argument("--require-rate-plan", action="store_true", help="Fail when tts_rate_plan.json is omitted for duration-controlled video.")
    parser.add_argument("--require-subtitles", action="store_true", help="Fail unless subtitle sidecar exists and final MP4 differs from the raw pre-subtitle render.")
    parser.add_argument("--require-subtitle-word-alignment", action="store_true", help="Fail unless every narrated subtitle cue uses exact Edge word-boundary timing.")
    parser.add_argument("--require-word-timings", action="store_true", help="Fail if cue timings are proportional estimates rather than word-boundary timings.")
    parser.add_argument("--require-animations", action="store_true", help="Fail unless every mapped Author Notes effect was rendered and passes pixel-motion QA.")
    parser.add_argument("--strict-attention", action="store_true", help="Promote cue-plan semantic-alignment risks to hard failures.")
    parser.add_argument("--allow-missing-attention", action="store_true", help="Degraded/debug only: allow --strict without visual cues/cue plan/timeline gates.")
    parser.add_argument("--require-pptx-anchors", action="store_true", help="Require strict visual anchors to resolve to PPTX geometry.")
    parser.add_argument("--min-cue-coverage", type=float, default=0.85, help="Minimum section coverage required when --require-visual-cues is used.")
    parser.add_argument("--min-cue-acceptance", type=float, default=0.85, help="Minimum cue-plan acceptance rate required by --strict-attention.")
    parser.add_argument("--max-tts-rate-adjust-percent", type=float, default=8.0, help="Hard maximum absolute TTS rate adjustment allowed by the final QA gate.")
    parser.add_argument("--strict", action="store_true", help="Final-package hard gate: require audio, MP4, rendered frames, and fail on warnings.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    findings: list[Finding] = []
    project_dir = args.project_dir.resolve()
    sections = load_script(args.script_json.resolve())
    ffmpeg, ffprobe = find_ffmpeg_pair()

    pptx_report = parse_pptx(args.pptx.resolve(), findings)
    slide_count = int(pptx_report.get("slide_count") or 0)
    if slide_count and len(sections) != slide_count:
        add(findings, "error", "script_slide_count_mismatch", "script.json section count does not match PPTX slide count.", expected=slide_count, actual=len(sections))

    require_audio = args.require_audio or args.strict
    require_mp4 = args.require_mp4 or args.strict
    if require_audio and args.audio_dir is None:
        add(findings, "error", "audio_dir_required", "Final video QA requires --audio-dir.")
    if require_mp4 and args.mp4 is None:
        add(findings, "error", "mp4_required", "Final video QA requires --mp4.")

    audio_report = check_audio(args.audio_dir.resolve() if args.audio_dir else None, sections, ffprobe, ffmpeg, findings)

    frames_dir = args.frames_dir.resolve() if args.frames_dir else None
    if frames_dir is None:
        bundled_frames = project_dir / "assets" / "slides" / "frames"
        if bundled_frames.is_dir():
            frames_dir = bundled_frames.resolve()
    if frames_dir is None and not args.no_render_frames:
        frames_dir = render_frames_from_pptx(args.pptx.resolve(), project_dir, findings)
    if args.strict and frames_dir is None:
        add(findings, "error", "frames_required", "Strict video QA requires rendered slide frames.")
    frames_report = check_frames(frames_dir, slide_count, findings)

    strict_attention_required = args.strict_attention or (args.strict and not args.allow_missing_attention)
    cues_report = check_visual_cues(
        args.visual_cues.resolve() if args.visual_cues else None,
        sections,
        audio_report,
        args.pad_tail,
        findings,
        required=args.require_visual_cues or strict_attention_required,
        cue_plan_path=args.cue_plan.resolve() if args.cue_plan else None,
        strict_attention=strict_attention_required,
        min_slide_coverage=args.min_cue_coverage,
    )
    cue_plan_report = check_cue_plan(
        args.cue_plan.resolve() if args.cue_plan else None,
        findings,
        required=args.require_cue_plan or strict_attention_required,
        strict_attention=strict_attention_required,
        require_word_timings=args.require_word_timings or strict_attention_required,
        min_acceptance_rate=args.min_cue_acceptance,
    )
    anchor_contract_report = check_anchor_contract(
        args.anchor_contract.resolve() if args.anchor_contract else None,
        args.cue_plan.resolve() if args.cue_plan else None,
        findings,
        required=args.require_anchor_contract,
        strict_attention=strict_attention_required,
        require_pptx_anchors=args.require_pptx_anchors,
    )
    timeline_report = check_timeline(
        args.timeline.resolve() if args.timeline else None,
        findings,
        required=args.require_timeline or strict_attention_required,
        strict_attention=strict_attention_required,
    )
    rate_plan_report = check_rate_plan(
        args.rate_plan.resolve() if args.rate_plan else None,
        findings,
        required=args.require_rate_plan,
        max_adjust_percent=args.max_tts_rate_adjust_percent,
    )
    video_report = check_video(args.mp4.resolve() if args.mp4 else None, args.target_minutes, args.duration_tolerance_seconds, ffprobe, ffmpeg, findings)
    subtitle_report = check_subtitle_delivery(
        raw_mp4=args.raw_mp4.resolve() if args.raw_mp4 else None,
        final_mp4=args.mp4.resolve() if args.mp4 else None,
        subtitle_file=args.subtitle_file.resolve() if args.subtitle_file else None,
        required=args.require_subtitles,
        ffprobe=ffprobe,
        ffmpeg=ffmpeg,
        findings=findings,
    )
    subtitle_timing_report = check_subtitle_word_alignment(
        args.subtitle_timing_report.resolve() if args.subtitle_timing_report else None,
        required=args.require_subtitle_word_alignment,
        pad_tail=args.pad_tail,
        findings=findings,
    )
    animation_report = check_animation_delivery(
        manifest_path=args.animation_manifest.resolve() if args.animation_manifest else None,
        render_report_path=args.animation_report.resolve() if args.animation_report else None,
        raw_mp4=args.raw_mp4.resolve() if args.raw_mp4 else None,
        pptx_path=args.pptx.resolve() if args.pptx else None,
        required=args.require_animations,
        ffmpeg=ffmpeg,
        findings=findings,
    )

    counts = {
        "error": sum(1 for f in findings if f.severity == "error"),
        "warning": sum(1 for f in findings if f.severity == "warning"),
        "info": sum(1 for f in findings if f.severity == "info"),
    }
    fail_on_warning = args.fail_on_warning or args.strict
    passed = findings_pass_gate(findings, fail_on_warning=fail_on_warning)
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "project_dir": str(project_dir),
        "inputs": {
            "pptx": str(args.pptx.resolve()),
            "script_json": str(args.script_json.resolve()),
            "audio_dir": str(args.audio_dir.resolve()) if args.audio_dir else None,
            "frames_dir": str(frames_dir) if frames_dir else None,
            "visual_cues": str(args.visual_cues.resolve()) if args.visual_cues else None,
            "cue_plan": str(args.cue_plan.resolve()) if args.cue_plan else None,
            "anchor_contract": str(args.anchor_contract.resolve()) if args.anchor_contract else None,
            "timeline": str(args.timeline.resolve()) if args.timeline else None,
            "rate_plan": str(args.rate_plan.resolve()) if args.rate_plan else None,
            "mp4": str(args.mp4.resolve()) if args.mp4 else None,
            "raw_mp4": str(args.raw_mp4.resolve()) if args.raw_mp4 else None,
            "subtitle_file": str(args.subtitle_file.resolve()) if args.subtitle_file else None,
            "subtitle_timing_report": str(args.subtitle_timing_report.resolve()) if args.subtitle_timing_report else None,
            "animation_manifest": str(args.animation_manifest.resolve()) if args.animation_manifest else None,
            "animation_report": str(args.animation_report.resolve()) if args.animation_report else None,
        },
        "options": {
            "strict": args.strict,
            "fail_on_warning": fail_on_warning,
            "require_audio": require_audio,
            "require_mp4": require_mp4,
            "require_visual_cues": args.require_visual_cues,
            "require_cue_plan": args.require_cue_plan,
            "require_subtitle_word_alignment": args.require_subtitle_word_alignment,
            "require_anchor_contract": args.require_anchor_contract,
            "require_timeline": args.require_timeline,
            "require_rate_plan": args.require_rate_plan,
            "require_subtitles": args.require_subtitles,
            "require_word_timings": args.require_word_timings,
            "require_animations": args.require_animations,
            "strict_attention": strict_attention_required,
            "allow_missing_attention": args.allow_missing_attention,
            "require_pptx_anchors": args.require_pptx_anchors,
            "min_cue_coverage": args.min_cue_coverage,
            "min_cue_acceptance": args.min_cue_acceptance,
            "max_tts_rate_adjust_percent": args.max_tts_rate_adjust_percent,
        },
        "passed": passed,
        "counts": counts,
        "script": {"section_count": len(sections), "section_ids": [s["id"] for s in sections]},
        "pptx": pptx_report,
        "audio": audio_report,
        "frames": frames_report,
        "visual_cues": cues_report,
        "cue_plan": cue_plan_report,
        "anchor_contract": anchor_contract_report,
        "timeline": timeline_report,
        "tts_rate_plan": rate_plan_report,
        "video": video_report,
        "subtitles": subtitle_report,
        "subtitle_timing": subtitle_timing_report,
        "animations": animation_report,
        "findings": [f.__dict__ for f in findings],
    }
    out_path = args.out or default_report_path(project_dir)
    write_report(out_path, report)
    maybe_write_manifest(project_dir, args, out_path, passed)

    status = "PASS" if passed else "FAIL"
    print(f"[check_video_package] {status}: {counts['error']} error(s), {counts['warning']} warning(s)")
    print(f"[check_video_package] report: {out_path}")
    if not passed:
        for finding in findings[:20]:
            loc = f" ({finding.location})" if finding.location else ""
            print(f"  - {finding.severity.upper()} {finding.code}{loc}: {finding.message}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
