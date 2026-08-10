#!/usr/bin/env python3
"""
render_video.py — composite a presentation video (MP4) from a ppt-master deck
and per-slide narration MP3s.

Pipeline position (Stage 3 of paper2video):
    Inputs:
        --pptx        : the canonical PPTX written by ppt-master
        --audio-dir   : a directory of per-slide MP3s (paper2poster's TTS output)
        --out         : MP4 destination path

    Steps:
        1. Use the current PPTX for editable animation manifests. Otherwise,
           prefer ppt-master's final SVG frames and fall back to PPTX/PDF.
        2. Pair each slide PNG with its matching MP3 (by script order)
        3. Probe each MP3's duration with ffprobe
        4. Build a per-slide concat segment, optionally pad trailing silence
        5. Concat into a single H.264 / AAC MP4 with ffmpeg's concat demuxer
        6. Verify the output plays and report duration

Why the non-editable authoring route prefers svg_final over PPTX/PDF:
    ppt-master authors and previews slides as SVG before exporting the PPTX.
    LibreOffice can reflow text and vector geometry differently from
    PowerPoint/Keynote, producing video frames that no longer match the deck the
    user inspected. The final SVGs are the same 16:9 visual source used before
    PPTX export. In the editable route, this preference is intentionally
    reversed: the current PPTX supplies all static and animated pixels so user
    changes cannot be hidden by an older SVG export.

ffmpeg fallback:
    If system ffmpeg/ffprobe aren't on PATH, we fall back to imageio_ffmpeg's
    bundled static binary. install with `pip install imageio-ffmpeg`. We don't
    silently use moviepy or ffmpeg-python — they wrap the same binary, just
    with more layers to debug when something goes wrong.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from editable_pptx import ProtocolError, file_sha256, write_reveal_variant

RESOLUTIONS = {
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k":    (3840, 2160),
}

DURATION_REPORT_SCHEMA_VERSION = "paper2video_duration_report.v1"
ANIMATION_RENDER_REPORT_SCHEMA_VERSION = "paper2video_animation_render.v1"
SUPPORTED_ANIMATION_NAMES = frozenset(
    {
        "Appear",
        "Fade In",
        "Dissolve In",
        "Fly In",
        "Wipe In",
        "Zoom In",
        "Circle In",
        "Diamond In",
    }
)
HIGHLIGHT_BORDER_ALPHA = 0.68
HIGHLIGHT_BOX_EXPAND_MULTIPLIER = 1.0
SPOTLIGHT_DIM_COLOR = "0x000000"
SPOTLIGHT_BORDER_ALPHA = 0.34
SPOTLIGHT_MAX_ALPHA = float(os.environ.get("VIDEO_SPOTLIGHT_DIM", "0.24"))
SPOTLIGHT_FEATHER_RATIO = float(os.environ.get("VIDEO_SPOTLIGHT_FEATHER_RATIO", "0.052"))
SPOTLIGHT_MIN_FEATHER_PX = int(os.environ.get("VIDEO_SPOTLIGHT_FEATHER_PX", "56"))
SPOTLIGHT_FEATHER_THICKNESS_MULTIPLIER = int(os.environ.get("VIDEO_SPOTLIGHT_FEATHER_THICK_MULT", "8"))
SPOTLIGHT_INNER_PAD_MULTIPLIER = 1.0
# Ink-tighten: shrink a highlight box to the actually-painted (ink) pixels inside
# it before building the spotlight mask. The upstream cue box is the shape's
# DECLARED geometry (PPTX off/ext) or a semantic estimate, so a loose text box
# spotlights a lot of empty leading/padding. Default on; needs Pillow+numpy and
# degrades to the declared box when they are absent or confidence is low.
INK_TIGHTEN = os.environ.get("VIDEO_SPOTLIGHT_INK_TIGHTEN", "1").strip().lower() not in ("0", "off", "false", "no")
INK_TIGHTEN_PAD_FRAC = float(os.environ.get("VIDEO_SPOTLIGHT_INK_PAD", "0.012"))
# Card/panel awareness: a highlight box whose border ring is mostly ONE fill
# colour (>= CARD_UNIFORM of the ring hugs its median) that differs from the
# SLIDE background by more than CARD_DELTA (summed RGB) sits on a FILLED
# card/panel — its fill (including an accent bar and padding) is part of the
# visual unit, so ink-tighten keeps the whole box instead of hugging the inner
# glyphs (which would dim the card and leave a "hole"/short frame).
INK_TIGHTEN_CARD_DELTA = float(os.environ.get("VIDEO_SPOTLIGHT_CARD_DELTA", "24"))
INK_TIGHTEN_CARD_UNIFORM = float(os.environ.get("VIDEO_SPOTLIGHT_CARD_UNIFORM", "0.6"))
CURSOR_MOVE_SECONDS = 0.55
CURSOR_POINTER_FILL = "0x1E293B"
CURSOR_POINTER_BORDER = "0xF8FAFC"
CURSOR_POINTER_SHADOW = "0x000000"
CURSOR_POINTER_FILL_ALPHA = 0.94
CURSOR_POINTER_BORDER_ALPHA = 0.96
CURSOR_POINTER_SHADOW_ALPHA = 0.26
CURSOR_OVERLAY_TIP_OFFSET = 3
LASER_DOT_FILL = (239, 68, 68)
LASER_DOT_HALO = (248, 113, 113)
LASER_DOT_CORE_ALPHA = 0.96
LASER_DOT_HALO_ALPHA = 0.34
LASER_DOT_SIZE_MULTIPLIER = 0.55
LASER_DOT_MIN_DIAMETER = 28
LASER_DOT_MAX_DIAMETER = 48
VALID_HIGHLIGHT_STYLES = {
    "box",
    "spotlight",
    "cursor",
    "box_cursor",
    "spotlight_cursor",
    "laser",
    "box_laser",
    "spotlight_laser",
}
CURSOR_STYLES = {"cursor", "box_cursor", "spotlight_cursor"}
LASER_STYLES = {"laser", "box_laser", "spotlight_laser"}
SPOTLIGHT_STYLES = {"spotlight", "spotlight_cursor", "spotlight_laser"}


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

def _which(name: str) -> str | None:
    return shutil.which(name)


def _imageio_ffmpeg_binary() -> str | None:
    """Fall back to the imageio_ffmpeg static binary if it's installed.

    Some environments don't have system ffmpeg but do have the pip package,
    which ships a portable binary. We use it for both ffmpeg and ffprobe
    (the package ships ffmpeg only, so probing happens through ffmpeg's
    own `-i` output as a last resort).
    """
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_libreoffice() -> str:
    for cand in ("libreoffice", "soffice"):
        path = _which(cand)
        if path:
            return path
    sys.exit(
        "[render_video] LibreOffice not found on PATH. Install with:\n"
        "  Ubuntu/Debian:  sudo apt-get install -y libreoffice\n"
        "  macOS:          brew install --cask libreoffice\n"
    )


def find_pdftoppm() -> str:
    path = _which("pdftoppm")
    if path:
        return path
    sys.exit(
        "[render_video] pdftoppm not found (part of poppler-utils). Install with:\n"
        "  Ubuntu/Debian:  sudo apt-get install -y poppler-utils\n"
        "  macOS:          brew install poppler\n"
    )


def find_chrome() -> str | None:
    """Return a local Chromium/Chrome executable for SVG screenshots."""
    for env_name in ("PAPER2VIDEO_CHROME", "CHROME", "CHROMIUM"):
        raw = os.getenv(env_name)
        if raw and Path(raw).expanduser().is_file():
            return str(Path(raw).expanduser())

    for candidate in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if Path(candidate).is_file():
            return candidate

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"):
        path = _which(name)
        if path:
            return path
    return None


def find_ffmpeg_pair() -> tuple[str, str]:
    """Return (ffmpeg, ffprobe) paths or exit with guidance."""
    env_ffmpeg = os.getenv("PAPER2VIDEO_FFMPEG") or os.getenv("FFMPEG_BINARY")
    if env_ffmpeg:
        env_path = Path(env_ffmpeg).expanduser()
        if env_path.is_file():
            env_ffprobe = os.getenv("PAPER2VIDEO_FFPROBE")
            if env_ffprobe and Path(env_ffprobe).expanduser().is_file():
                return str(env_path), str(Path(env_ffprobe).expanduser())
            return str(env_path), str(env_path)

    fallback = _imageio_ffmpeg_binary()
    if fallback:
        # Prefer the bundled static ffmpeg when available. In the ACL26
        # environment, system ffmpeg is 2.4.x and lacks newer filters/codecs,
        # while imageio-ffmpeg provides a modern static build.
        return fallback, fallback

    ffmpeg = _which("ffmpeg")
    ffprobe = _which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe

    sys.exit(
        "[render_video] ffmpeg/ffprobe not found and imageio_ffmpeg is not installed.\n"
        "Pick one:\n"
        "  • System install:  sudo apt-get install -y ffmpeg\n"
        "  • Python fallback: pip install imageio-ffmpeg\n"
    )


# ---------------------------------------------------------------------------
# Stage A — deck source → per-slide PNG
# ---------------------------------------------------------------------------

def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def discover_svg_dir(project_path: Path, explicit_svg_dir: Path | None, frame_source: str) -> Path | None:
    if explicit_svg_dir is not None:
        if not explicit_svg_dir.is_dir():
            sys.exit(f"[render_video] --svg-dir not found: {explicit_svg_dir}")
        return explicit_svg_dir

    for name in ("svg_final", "svg_output"):
        candidate = project_path / name
        if candidate.is_dir() and list(candidate.glob("*.svg")):
            return candidate

    if frame_source == "svg":
        sys.exit(
            "[render_video] --frame-source svg requested, but no SVG deck was found. "
            "Expected <project>/svg_final/*.svg or <project>/svg_output/*.svg."
        )
    return None


def collect_svgs(svg_dir: Path) -> list[Path]:
    svgs = sorted(svg_dir.glob("*.svg"), key=natural_key)
    if not svgs:
        sys.exit(f"[render_video] SVG deck has no .svg files: {svg_dir}")
    return svgs


def _resolve_svg_asset_href(raw: str, *, svg_path: Path, project_path: Path) -> str:
    raw = raw.strip()
    if not raw or raw.startswith(("#", "data:", "http://", "https://", "file:")):
        return raw

    asset_part, sep, fragment = raw.partition("#")
    asset_path = Path(asset_part)
    candidates = [svg_path.parent / asset_path, project_path / asset_path]
    for candidate in candidates:
        if candidate.is_file():
            uri = candidate.resolve().as_uri()
            return f"{uri}{sep}{fragment}" if sep else uri
    return raw


def _inline_svg_html(
    svg_path: Path, project_path: Path, *, transparent: bool = False,
) -> str:
    text = svg_path.read_text(encoding="utf-8")
    text = re.sub(r"^\s*<\?xml[^>]*>\s*", "", text)

    def replace_href(match: re.Match[str]) -> str:
        attr, quote, href = match.group(1), match.group(2), match.group(3)
        resolved = _resolve_svg_asset_href(href, svg_path=svg_path, project_path=project_path)
        return f"{attr}={quote}{resolved}{quote}"

    text = re.sub(r"((?:xlink:)?href)=(['\"])([^'\"]+)\2", replace_href, text)
    base_uri = svg_path.parent.resolve().as_uri() + "/"
    page_background = "transparent" if transparent else "white"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<base href=\"{base_uri}\">"
        "<style>"
        f"html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{page_background};}}"
        "body>svg{width:100vw!important;height:100vh!important;display:block;}"
        "</style></head><body>"
        f"{text}"
        "</body></html>"
    )


def render_svg_frames(
    svgs: list[Path],
    out_dir: Path,
    *,
    project_path: Path,
    width: int,
    height: int,
    browser_executable: str | None = None,
) -> list[Path]:
    """Render final ppt-master SVGs to PNG frames with a browser renderer."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        sys.exit(
            "[render_video] SVG frame rendering requires Playwright for Python. "
            "Install it in this environment or rerun with --frame-source pptx for "
            "the legacy LibreOffice path."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    html_dir = out_dir.parent / "svg_html"
    if html_dir.exists():
        shutil.rmtree(html_dir)
    html_dir.mkdir(parents=True, exist_ok=True)

    browser_path = browser_executable or find_chrome()
    launch_kwargs: dict[str, object] = {"headless": True}
    if browser_path:
        launch_kwargs["executable_path"] = browser_path

    frames: list[Path] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            for idx, svg_path in enumerate(svgs, start=1):
                html_path = html_dir / f"slide-{idx:02d}.html"
                html_path.write_text(_inline_svg_html(svg_path, project_path), encoding="utf-8")
                page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=60000)
                frame_path = out_dir / f"slide-{idx:02d}.png"
                page.screenshot(path=str(frame_path), full_page=False, omit_background=False)
                frames.append(frame_path)
            browser.close()
    except Exception as exc:
        sys.exit(f"[render_video] browser SVG render failed: {exc}")

    if len(frames) != len(svgs):
        sys.exit(f"[render_video] expected {len(svgs)} SVG frame(s), rendered {len(frames)}")
    return frames


def copy_frames(frames: list[Path], frames_out: Path) -> list[Path]:
    frames_out = frames_out.resolve()
    if frames and frames[0].parent.resolve() == frames_out:
        return frames
    if frames_out.exists():
        shutil.rmtree(frames_out)
    frames_out.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for idx, frame in enumerate(frames, start=1):
        dest = frames_out / f"slide-{idx:02d}{frame.suffix.lower() or '.png'}"
        shutil.copy2(frame, dest)
        copied.append(dest)
    return copied

def pptx_to_pdf(pptx_path: Path, out_dir: Path, libreoffice: str) -> Path:
    """Convert PPTX to PDF in `out_dir`. Return the PDF path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Use a throwaway user profile so a logged-in LibreOffice GUI doesn't
    # hold a lock on the default ~/.config/libreoffice profile.
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_dir:
        cmd = [
            libreoffice,
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless", "--norestore", "--nologo",
            "--convert-to", "pdf",
            "--outdir", str(out_dir),
            str(pptx_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        sys.exit(f"[render_video] LibreOffice failed (exit {proc.returncode}):\n"
                 f"stdout: {proc.stdout}\nstderr: {proc.stderr}")

    pdf = out_dir / (pptx_path.stem + ".pdf")
    if not pdf.exists():
        sys.exit(f"[render_video] expected PDF not produced: {pdf}\n"
                 f"LibreOffice stdout:\n{proc.stdout}")
    return pdf


def pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int, pdftoppm: str) -> list[Path]:
    """Rasterize a PDF to one PNG per page.

    We use the `-png` switch so output is RGB without alpha, and pad the page
    number so sorted order matches slide order even with 100+ slides.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "slide"
    cmd = [
        pdftoppm, "-png", "-r", str(dpi),
        # Wide enough for any sane deck; pdftoppm default is 6 already.
        str(pdf_path), str(prefix),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        sys.exit(f"[render_video] pdftoppm failed:\n{proc.stderr}")

    pngs = sorted(out_dir.glob("slide-*.png"))
    if not pngs:
        sys.exit(f"[render_video] pdftoppm produced no PNGs in {out_dir}")
    return pngs


# ---------------------------------------------------------------------------
# Stage B — pair frames with audio
# ---------------------------------------------------------------------------

@dataclass
class SlidePair:
    index: int           # 1-based slide number
    frame: Path
    audio: Path
    duration: float      # seconds (from probe)


@dataclass
class VisualCue:
    cue_type: str
    start: float
    end: float
    box: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    color: str = "#64748B"
    opacity: float = 0.18
    border: int = 5
    size: int | None = None
    style: str = "spotlight_laser"
    # When True the box is already the intended LOGICAL unit (a grouped
    # multi-line label or a filled card) and must be used verbatim — skip
    # ink-tighten, which would hug the inner glyphs and leave a fill-only
    # card's background padding dimmed (the "hole in the card" defect).
    no_ink_tighten: bool = False


@dataclass
class AnimationEffect:
    order: int
    locator: str
    name: str
    start: float
    duration: float
    timing_source: str
    shape_id: str | None = None


@dataclass
class AnimationSlide:
    index: int
    slide_id: str
    effects: list[AnimationEffect]


@dataclass
class AnimationLayer:
    effect: AnimationEffect
    path: Path
    x: int
    y: int
    width: int
    height: int


def animation_manifest_metadata(path: Path | None) -> dict[str, str]:
    if path is None:
        return {"source_kind": "svg"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"[render_video] invalid animation manifest {path}: {exc}")
    source_kind = str(payload.get("source_kind") or "svg")
    if source_kind not in {"svg", "pptx"}:
        sys.exit(
            f"[render_video] animation manifest has unsupported source_kind {source_kind!r}"
        )
    return {
        "source_kind": source_kind,
        "source_sha256": str(payload.get("source_sha256") or ""),
        "source_pptx": str(payload.get("source_pptx") or ""),
    }


@dataclass
class AnimationSlideAssets:
    index: int
    base_frame: Path
    layers: list[AnimationLayer]


def load_animation_manifest(
    path: Path | None,
    pairs: list[SlidePair],
    *,
    pad_tail: float,
) -> dict[int, AnimationSlide]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"[render_video] invalid animation manifest {path}: {exc}")
    if payload.get("schema_version") != "paper2video_animation_manifest.v1":
        sys.exit(f"[render_video] unsupported animation manifest schema in {path}")
    source_kind = str(payload.get("source_kind") or "svg")
    if source_kind not in {"svg", "pptx"}:
        sys.exit(
            f"[render_video] animation manifest has unsupported source_kind {source_kind!r}"
        )
    slides = payload.get("slides") or []
    if len(slides) != len(pairs):
        sys.exit(
            f"[render_video] animation manifest has {len(slides)} slides, "
            f"expected {len(pairs)}"
        )
    result: dict[int, AnimationSlide] = {}
    total_effects = 0
    for pair, raw_slide in zip(pairs, slides):
        index = int(raw_slide.get("index") or 0)
        if index != pair.index:
            sys.exit(
                f"[render_video] animation slide index {index} != expected {pair.index}"
            )
        slide_id = str(raw_slide.get("id") or "").strip()
        if slide_id != pair.audio.stem:
            sys.exit(
                f"[render_video] animation slide {index} id {slide_id!r} does not "
                f"match audio/script id {pair.audio.stem!r}"
            )
        effects: list[AnimationEffect] = []
        for raw in raw_slide.get("effects") or []:
            start = float(raw.get("start") or 0.0)
            duration = float(raw.get("duration") or 0.0)
            locator = str(raw.get("locator") or "").strip()
            name = str(raw.get("name") or "").strip()
            timing_source = str(raw.get("timing_source") or "")
            if not locator or not name:
                sys.exit(f"[render_video] slide {index} has an animation without locator/name")
            shape_id = str(raw.get("shape_id") or "").strip() or None
            if source_kind == "pptx" and shape_id is None:
                sys.exit(
                    f"[render_video] slide {index} PPTX animation {locator!r} "
                    "is missing shape_id"
                )
            if name not in SUPPORTED_ANIMATION_NAMES:
                sys.exit(
                    f"[render_video] slide {index} animation {locator!r} has unsupported "
                    f"effect name {name!r}"
                )
            if start < 0 or duration <= 0 or start + duration > pair.duration + pad_tail + 0.01:
                sys.exit(
                    f"[render_video] slide {index} animation {locator!r} has invalid timing "
                    f"start={start}, duration={duration}, segment={pair.duration + pad_tail:.3f}"
                )
            if timing_source not in {"edge_word_alignment", "animation_pane"}:
                sys.exit(
                    f"[render_video] slide {index} animation {locator!r} has "
                    f"unsupported timing source {timing_source!r}"
                )
            order = int(raw.get("order") or len(effects) + 1)
            if order != len(effects) + 1:
                sys.exit(
                    f"[render_video] slide {index} animation order {order} is not "
                    f"the expected contiguous order {len(effects) + 1}"
                )
            effects.append(
                AnimationEffect(
                    order=order,
                    locator=locator,
                    name=name,
                    start=start,
                    duration=duration,
                    timing_source=timing_source,
                    shape_id=shape_id,
                )
            )
        result[index] = AnimationSlide(
            index=index,
            slide_id=slide_id,
            effects=effects,
        )
        total_effects += len(effects)
    declared = int(payload.get("effect_count") or 0)
    if declared != total_effects:
        sys.exit(
            f"[render_video] animation manifest effect_count {declared} != {total_effects}"
        )
    return result


def render_svg_animation_assets(
    svgs: list[Path],
    animation_map: dict[int, AnimationSlide],
    out_dir: Path,
    *,
    project_path: Path,
    width: int,
    height: int,
    browser_executable: str | None = None,
) -> dict[int, AnimationSlideAssets]:
    """Rasterize one static base plus transparent SVG-group layers per slide."""
    if not animation_map:
        return {}
    try:
        from PIL import Image  # type: ignore
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        sys.exit(
            "[render_video] animated SVG rendering requires Pillow and Playwright."
        )
    if len(svgs) != len(animation_map):
        sys.exit(
            f"[render_video] animation SVG count {len(svgs)} != manifest slide count "
            f"{len(animation_map)}"
        )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_dir = out_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    browser_path = browser_executable or find_chrome()
    launch_kwargs: dict[str, object] = {"headless": True}
    if browser_path:
        launch_kwargs["executable_path"] = browser_path
    assets: dict[int, AnimationSlideAssets] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_kwargs)
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1,
            )
            for index, svg_path in enumerate(svgs, start=1):
                slide = animation_map[index]
                slide_dir = out_dir / f"slide-{index:02d}"
                slide_dir.mkdir(parents=True, exist_ok=True)
                html_path = html_dir / f"slide-{index:02d}.html"
                html_path.write_text(
                    _inline_svg_html(svg_path, project_path, transparent=True),
                    encoding="utf-8",
                )
                uri = html_path.resolve().as_uri()
                locators = [effect.locator for effect in slide.effects]
                page.goto(uri, wait_until="networkidle", timeout=60000)
                missing = page.evaluate(
                    """ids => ids.filter(id => !Array.from(
                        document.querySelector('svg').children
                    ).some(el => el.id === id))""",
                    locators,
                )
                if missing:
                    sys.exit(
                        f"[render_video] slide {index} animation SVG locators missing: {missing}"
                    )
                page.evaluate(
                    """ids => {
                        const root = document.querySelector('svg');
                        for (const id of ids) {
                            const el = Array.from(root.children).find(node => node.id === id);
                            if (el) el.style.display = 'none';
                        }
                    }""",
                    locators,
                )
                base_path = slide_dir / "base.png"
                page.screenshot(
                    path=str(base_path), full_page=False, omit_background=True,
                )

                layer_cache: dict[str, tuple[Path, int, int, int, int]] = {}
                layers: list[AnimationLayer] = []
                for effect in slide.effects:
                    if effect.locator not in layer_cache:
                        page.goto(uri, wait_until="networkidle", timeout=60000)
                        page.evaluate(
                            """target => {
                                const root = document.querySelector('svg');
                                for (const el of Array.from(root.children)) {
                                    const tag = el.tagName.toLowerCase();
                                    if (tag !== 'defs' && el.id !== target) {
                                        el.style.display = 'none';
                                    }
                                }
                            }""",
                            effect.locator,
                        )
                        full_path = slide_dir / f"layer-{len(layer_cache) + 1:02d}-full.png"
                        page.screenshot(
                            path=str(full_path), full_page=False, omit_background=True,
                        )
                        with Image.open(full_path) as source:
                            image = source.convert("RGBA")
                            bbox = image.getchannel("A").getbbox()
                            if bbox is None:
                                sys.exit(
                                    f"[render_video] slide {index} animation layer "
                                    f"{effect.locator!r} rendered empty"
                                )
                            x0, y0, x1, y1 = bbox
                            cropped = image.crop(bbox)
                            layer_path = slide_dir / f"layer-{len(layer_cache) + 1:02d}.png"
                            cropped.save(layer_path)
                        full_path.unlink(missing_ok=True)
                        layer_cache[effect.locator] = (
                            layer_path, x0, y0, x1 - x0, y1 - y0,
                        )
                    layer_path, x, y, layer_w, layer_h = layer_cache[effect.locator]
                    layers.append(
                        AnimationLayer(
                            effect=effect,
                            path=layer_path,
                            x=x,
                            y=y,
                            width=layer_w,
                            height=layer_h,
                        )
                    )
                assets[index] = AnimationSlideAssets(
                    index=index, base_frame=base_path, layers=layers,
                )
            browser.close()
    except SystemExit:
        raise
    except Exception as exc:
        sys.exit(f"[render_video] animated SVG layer render failed: {exc}")
    return assets


def _pdf_to_scaled_pngs(
    pdf_path: Path,
    out_dir: Path,
    *,
    width: int,
    height: int,
    pdftoppm: str,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "slide"
    cmd = [
        pdftoppm,
        "-png",
        "-r",
        "144",
        "-scale-to-x",
        str(width),
        "-scale-to-y",
        str(height),
        str(pdf_path),
        str(prefix),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        sys.exit(f"[render_video] pdftoppm animation-state render failed:\n{proc.stderr}")
    frames = sorted(out_dir.glob("slide-*.png"), key=natural_key)
    if not frames:
        sys.exit(f"[render_video] no animation-state frames produced under {out_dir}")
    return frames


def _pptx_diff_layer(
    before_path: Path,
    after_path: Path,
    output_path: Path,
) -> tuple[int, int, int, int]:
    """Create a transparent layer from two deterministic PPTX reveal states."""
    try:
        import numpy as np  # type: ignore
        from PIL import Image, ImageFilter  # type: ignore
    except Exception:
        sys.exit("[render_video] editable PPTX animation rendering requires Pillow and numpy")
    with Image.open(before_path) as before_source, Image.open(after_path) as after_source:
        before = before_source.convert("RGB")
        after = after_source.convert("RGB")
        if before.size != after.size:
            sys.exit(
                "[render_video] editable PPTX reveal states have mismatched dimensions "
                f"{before.size} != {after.size}"
            )
        before_array = np.asarray(before, dtype=np.int16)
        after_array = np.asarray(after, dtype=np.int16)
        delta = np.abs(after_array - before_array).max(axis=2).astype(np.float32)
        visible = delta >= 2.0
        ys, xs = np.nonzero(visible)
        if len(xs) == 0 or len(ys) == 0:
            sys.exit(
                "[render_video] editable PPTX animation target produced no visible pixel change; "
                "check that the shape is visible and has a real entrance effect"
            )
        pad = 2
        x0 = max(0, int(xs.min()) - pad)
        y0 = max(0, int(ys.min()) - pad)
        x1 = min(after.width, int(xs.max()) + pad + 1)
        y1 = min(after.height, int(ys.max()) + pad + 1)
        alpha = np.clip((delta - 1.0) * 18.0, 0.0, 255.0).astype(np.uint8)
        alpha[~visible] = 0
        alpha_image = Image.fromarray(alpha, mode="L").filter(ImageFilter.GaussianBlur(0.45))
        cropped = after.crop((x0, y0, x1, y1)).convert("RGBA")
        cropped.putalpha(alpha_image.crop((x0, y0, x1, y1)))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path)
    return x0, y0, x1 - x0, y1 - y0


def render_pptx_animation_assets(
    pptx_path: Path,
    animation_map: dict[int, AnimationSlide],
    out_dir: Path,
    *,
    width: int,
    height: int,
    libreoffice: str,
    pdftoppm: str,
) -> dict[int, AnimationSlideAssets]:
    """Render Author Notes animations from the current editable PPTX pixels.

    The function creates cumulative reveal variants. State 0 removes all
    protocol targets; state N keeps the first N targets on every slide. A
    layer is the pixel delta between adjacent states, so PowerPoint text,
    color, geometry, image, add, delete, and style edits all flow into video.
    """
    if not animation_map:
        return {}
    slide_shape_ids: list[list[str]] = []
    max_effects = 0
    for index in range(1, len(animation_map) + 1):
        slide = animation_map[index]
        shape_ids = [str(effect.shape_id or "") for effect in slide.effects]
        if any(not shape_id for shape_id in shape_ids):
            sys.exit(f"[render_video] slide {index} editable PPTX effect is missing shape_id")
        if len(set(shape_ids)) != len(shape_ids):
            sys.exit(
                f"[render_video] slide {index} has multiple entrance effects for one shape; "
                "the editable renderer currently requires one entrance per target"
            )
        slide_shape_ids.append(shape_ids)
        max_effects = max(max_effects, len(shape_ids))

    if out_dir.exists():
        shutil.rmtree(out_dir)
    variants_dir = out_dir / "variants"
    states_dir = out_dir / "states"
    variants_dir.mkdir(parents=True, exist_ok=True)
    states_dir.mkdir(parents=True, exist_ok=True)

    state_frames: dict[int, list[Path]] = {}
    for reveal_count in range(max_effects + 1):
        variant = variants_dir / f"state-{reveal_count:02d}.pptx"
        try:
            write_reveal_variant(
                pptx_path,
                slide_shape_ids,
                reveal_count,
                variant,
            )
        except ProtocolError as exc:
            sys.exit(f"[render_video] could not build editable PPTX reveal state: {exc}")
        state_root = states_dir / f"state-{reveal_count:02d}"
        pdf = pptx_to_pdf(variant, state_root / "pdf", libreoffice)
        frames = _pdf_to_scaled_pngs(
            pdf,
            state_root / "frames",
            width=width,
            height=height,
            pdftoppm=pdftoppm,
        )
        if len(frames) != len(animation_map):
            sys.exit(
                f"[render_video] reveal state {reveal_count} rendered {len(frames)} slides, "
                f"expected {len(animation_map)}"
            )
        state_frames[reveal_count] = frames

    assets: dict[int, AnimationSlideAssets] = {}
    for index in range(1, len(animation_map) + 1):
        slide = animation_map[index]
        slide_dir = out_dir / f"slide-{index:02d}"
        slide_dir.mkdir(parents=True, exist_ok=True)
        base_path = slide_dir / "base.png"
        shutil.copy2(state_frames[0][index - 1], base_path)
        layers: list[AnimationLayer] = []
        for effect_index, effect in enumerate(slide.effects, start=1):
            layer_path = slide_dir / f"layer-{effect_index:02d}.png"
            x, y, layer_width, layer_height = _pptx_diff_layer(
                state_frames[effect_index - 1][index - 1],
                state_frames[effect_index][index - 1],
                layer_path,
            )
            layers.append(
                AnimationLayer(
                    effect=effect,
                    path=layer_path,
                    x=x,
                    y=y,
                    width=layer_width,
                    height=layer_height,
                )
            )
        assets[index] = AnimationSlideAssets(
            index=index,
            base_frame=base_path,
            layers=layers,
        )
    return assets


def _load_script_order(script_json: Path) -> list[str]:
    try:
        payload = json.loads(script_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"[render_video] invalid script JSON {script_json}: {exc}")

    sections = payload.get("sections") or []
    if not isinstance(sections, list):
        sys.exit(f"[render_video] script JSON has no sections array: {script_json}")

    ids: list[str] = []
    for idx, sec in enumerate(sections, start=1):
        if not isinstance(sec, dict) or not sec.get("id"):
            sys.exit(f"[render_video] script section {idx} is missing an id in {script_json}")
        ids.append(str(sec["id"]))
    if not ids:
        sys.exit(f"[render_video] script JSON has an empty sections array: {script_json}")
    return ids


def _load_manifest_order(manifest_json: Path) -> list[str]:
    try:
        payload = json.loads(manifest_json.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    # paper2poster's generate_audio.py writes a plain list of
    # {"id": ..., "file": ...} entries. Be liberal in case a later manifest
    # wraps that list under a root key.
    entries = payload.get("sections") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    files: list[str] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        if item.get("file"):
            files.append(str(item["file"]))
        elif item.get("id"):
            files.append(f"{item['id']}.mp3")
    return files


def autodetect_script_json(project_path: Path, audio_dir: Path) -> Path | None:
    for candidate in (
        audio_dir / "script.json",
        project_path / "assets" / "meta" / "narration.json",
        project_path / "narration.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def collect_audio(
    audio_dir: Path,
    *,
    script_json: Path | None = None,
    project_path: Path | None = None,
) -> list[Path]:
    if not audio_dir.is_dir():
        sys.exit(f"[render_video] audio dir not found: {audio_dir}")

    if script_json is None and project_path is not None:
        script_json = autodetect_script_json(project_path, audio_dir)

    if script_json is not None:
        script_json = script_json.resolve()
        ids = _load_script_order(script_json)
        ordered = [audio_dir / f"{sid}.mp3" for sid in ids]
        missing = [p.name for p in ordered if not p.is_file()]
        if missing:
            sys.exit(
                f"[render_video] script/audio mismatch using {script_json}:\n"
                f"  missing mp3s under {audio_dir}: {missing}"
            )
        print(f"[render_video]   audio order from {script_json}")
        return ordered

    manifest_order = _load_manifest_order(audio_dir / "manifest.json")
    if manifest_order:
        ordered = [audio_dir / name for name in manifest_order]
        if all(p.is_file() for p in ordered):
            print(f"[render_video]   audio order from {audio_dir / 'manifest.json'}")
            return ordered

    mp3s = sorted(audio_dir.glob("*.mp3"))
    if not mp3s:
        sys.exit(f"[render_video] no .mp3 files in {audio_dir}")
    print("[render_video]   audio order from sorted *.mp3 filenames")
    return mp3s


def probe_duration(audio: Path, ffprobe: str, ffmpeg: str) -> float:
    """Return duration in seconds.

    Prefers ffprobe; falls back to parsing ffmpeg's stderr when only the
    imageio_ffmpeg static binary is available (it doesn't ship ffprobe).
    """
    if ffprobe != ffmpeg:  # we have a real ffprobe
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(audio)]
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())

    # Fallback: ffmpeg -i prints "Duration: HH:MM:SS.xx"
    out = subprocess.run([ffmpeg, "-i", str(audio)], capture_output=True, text=True)
    m = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", out.stderr)
    if not m:
        sys.exit(f"[render_video] could not probe duration for {audio.name}")
    h, mm, ss = m.group(1), m.group(2), m.group(3)
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def pair_slides(frames: list[Path], audio_files: list[Path],
                ffprobe: str, ffmpeg: str) -> list[SlidePair]:
    """Match frames to audio in sorted order and probe durations.

    We match by index, not by filename, because LibreOffice writes
    slide-01.png … slide-NN.png while paper2poster writes audio named after
    the original slide stems. The only thing we need is that *count matches
    and order matches*. The preferred order source is a script JSON
    (`--script-json`, `audio/script.json`, `assets/meta/narration.json`, or `narration.json`); otherwise
    we fall back to manifest order or sorted filenames. For ppt-master decks,
    sorted filenames still work when notes use numeric prefixes.

    Order is guaranteed because:
      • LibreOffice walks the PPTX slides in order
      • paper2poster writes one MP3 per script section in array order
      • notes_to_script.py walks notes/*.md sorted by filename, which is the
        same sort ppt-master uses for SVGs.
    """
    if len(frames) != len(audio_files):
        sys.exit(
            f"[render_video] slide/audio count mismatch: "
            f"{len(frames)} frames vs {len(audio_files)} mp3s.\n"
            f"  Frames found: {[p.name for p in frames]}\n"
            f"  Audio  found: {[p.name for p in audio_files]}\n"
            f"  Most likely a notes/<slide>.md was missing during Stage 2 — "
            f"regenerate audio/script.json and re-run paper2poster's "
            f"generate_audio.py before muxing."
        )
    pairs = []
    for i, (frame, audio) in enumerate(zip(frames, audio_files), start=1):
        dur = probe_duration(audio, ffprobe, ffmpeg)
        pairs.append(SlidePair(index=i, frame=frame, audio=audio, duration=dur))
    return pairs


# ---------------------------------------------------------------------------
# Optional attention overlays — semantic highlight boxes / cursor markers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_float_list(value: object, *, length: int, field: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{field} must be a list of {length} numbers")
    out: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise ValueError(f"{field} must be a list of {length} numbers")
        out.append(float(item))
    return out


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_color(raw: object, fallback: str) -> str:
    color = str(raw or fallback).strip()
    if re.match(r"^#[0-9A-Fa-f]{6}$", color):
        return "0x" + color[1:]
    if re.match(r"^0x[0-9A-Fa-f]{6}$", color):
        return color
    if re.match(r"^[A-Za-z]+$", color):
        return color
    return "0x" + fallback.lstrip("#")


def _color_alpha(color: str, alpha: float) -> str:
    return f"{color}@{max(0.0, min(alpha, 1.0)):.3f}"


def _cue_enabled_for_mode(cue_type: str, attention_mode: str) -> bool:
    if attention_mode == "none":
        return False
    if attention_mode == "both":
        return cue_type in {"highlight", "cursor"}
    return cue_type == attention_mode


def _cue_time(raw: dict, pair: SlidePair, pad_tail: float) -> tuple[float, float]:
    if "at" in raw and "start" not in raw:
        start = float(raw["at"])
    else:
        start = float(raw.get("start", 0.0))

    if raw.get("end") is not None:
        end = float(raw["end"])
    else:
        end = start + float(raw.get("duration", 3.0))

    segment_end = max(pair.duration + pad_tail, 0.1)
    start = max(0.0, min(start, segment_end))
    end = max(start + 0.05, min(end, segment_end))
    return start, end


def load_visual_cues(
    visual_cues_path: Path | None,
    pairs: list[SlidePair],
    *,
    attention_mode: str,
    highlight_style: str,
    pad_tail: float,
    allow_missing_visual_cues: bool = False,
) -> dict[int, list[VisualCue]]:
    """Load cue JSON keyed by 1-based slide index.

    Accepted shape:
        {"slides": [{"id": "audio_stem", "index": 1, "cues": [...]}]}
    Each cue uses normalized coordinates: box=[x,y,w,h], point=[x,y].
    Highlight cues render as translucent boxes when `box` is available.
    Legacy point-only cues are still accepted as soft dots.
    """
    if attention_mode == "none":
        return {}
    if visual_cues_path is None:
        message = (
            f"[render_video] attention mode '{attention_mode}' requires --visual-cues. "
            "Use --attention-mode none for a user-approved no-highlight render, or pass "
            "--allow-missing-visual-cues for a degraded/debug run."
        )
        if not allow_missing_visual_cues:
            sys.exit(message)
        print(message + " Continuing without overlays.")
        return {}

    try:
        payload = json.loads(visual_cues_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"[render_video] visual cues file not found: {visual_cues_path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"[render_video] invalid visual cues JSON {visual_cues_path}: {exc}")

    slides = payload.get("slides") if isinstance(payload, dict) else payload
    if not isinstance(slides, list):
        sys.exit(f"[render_video] visual cues JSON must contain a slides array: {visual_cues_path}")

    by_id = {pair.audio.stem: pair for pair in pairs}
    by_index = {pair.index: pair for pair in pairs}
    out: dict[int, list[VisualCue]] = {}
    loaded = 0

    for slide in slides:
        if not isinstance(slide, dict):
            sys.exit("[render_video] each visual cue slide entry must be an object")
        pair: SlidePair | None = None
        if slide.get("id") is not None:
            pair = by_id.get(str(slide["id"]))
        if pair is None and slide.get("index") is not None:
            pair = by_index.get(int(slide["index"]))
        if pair is None:
            sys.exit(f"[render_video] visual cue slide does not match any audio stem/index: {slide}")

        raw_cues = slide.get("cues") or []
        if not isinstance(raw_cues, list):
            sys.exit(f"[render_video] visual cues for slide {pair.index} must be an array")

        for raw in raw_cues:
            if not isinstance(raw, dict):
                sys.exit(f"[render_video] visual cue for slide {pair.index} must be an object")
            cue_type = str(raw.get("type") or ("highlight" if attention_mode != "cursor" else "cursor")).strip()
            if cue_type not in {"highlight", "cursor"}:
                sys.exit(f"[render_video] unsupported visual cue type: {cue_type}")
            if not _cue_enabled_for_mode(cue_type, attention_mode):
                continue

            start, end = _cue_time(raw, pair, pad_tail)
            color = _normalize_color(raw.get("color"), "#64748B")
            opacity = float(raw.get("opacity", 0.18 if cue_type == "highlight" else 0.95))
            opacity = max(0.05, min(opacity, 1.0))
            border = max(1, int(raw.get("border", 5)))
            try:
                size = int(raw["size"]) if raw.get("size") is not None else None
            except (TypeError, ValueError):
                sys.exit(f"[render_video] visual cue size must be an integer on slide {pair.index}")
            if size is not None:
                size = max(1, size)

            if cue_type == "highlight":
                box = None
                if raw.get("box") is not None:
                    box_vals = _as_float_list(raw.get("box"), length=4, field="box")
                    x, y, w, h = box_vals
                    x = _clamp01(x)
                    y = _clamp01(y)
                    w = max(0.001, min(float(w), 1.0 - x))
                    h = max(0.001, min(float(h), 1.0 - y))
                    box = (x, y, w, h)
                    if raw.get("point") is not None:
                        point_vals = _as_float_list(raw.get("point"), length=2, field="point")
                        point = (_clamp01(point_vals[0]), _clamp01(point_vals[1]))
                    else:
                        point = (_clamp01(x + w / 2.0), _clamp01(y + h / 2.0))
                elif raw.get("point") is not None:
                    point_vals = _as_float_list(raw.get("point"), length=2, field="point")
                    point = (_clamp01(point_vals[0]), _clamp01(point_vals[1]))
                else:
                    sys.exit(f"[render_video] highlight cue on slide {pair.index} needs either point or box")
                style = str(raw.get("style") or highlight_style).strip()
                cue = VisualCue(cue_type=cue_type, start=start, end=end, box=box, point=point,
                                color=color, opacity=opacity, border=border, size=size, style=style,
                                no_ink_tighten=bool(raw.get("no_ink_tighten", False)))
            else:
                point_vals = _as_float_list(raw.get("point"), length=2, field="point")
                point = (_clamp01(point_vals[0]), _clamp01(point_vals[1]))
                cue = VisualCue(cue_type=cue_type, start=start, end=end, point=point,
                                color=color, opacity=opacity, border=border, size=size, style="cursor")

            out.setdefault(pair.index, []).append(cue)
            loaded += 1

    print(f"[render_video]   visual cues from {visual_cues_path}: {loaded} cue(s) enabled")
    return out


def _enable_expr(cue: VisualCue) -> str:
    return f"enable='between(t,{cue.start:.3f},{cue.end:.3f})'"


def _circle_drawbox_filters(
    *,
    cx: int,
    cy: int,
    radius: int,
    width: int,
    height: int,
    color: str,
    enable: str,
) -> list[str]:
    """Approximate a circular dot with thin drawbox bands.

    Staying inside the simple `-vf` chain keeps this compatible with older
    ffmpeg builds that lack richer shape/alpha filters.
    """
    radius = max(4, radius)
    band_count = max(21, min(51, radius // 2 + 1))
    if band_count % 2 == 0:
        band_count += 1

    filters: list[str] = []
    step = (2.0 * radius) / band_count
    for band in range(band_count):
        y0f = cy - radius + band * step
        y1f = cy - radius + (band + 1) * step
        ym = (y0f + y1f) / 2.0 - cy
        half_w = math.sqrt(max(radius * radius - ym * ym, 0.0))

        x0 = int(round(cx - half_w))
        x1 = int(round(cx + half_w))
        y0 = int(round(y0f))
        y1 = int(round(y1f))

        x0_clip = max(0, x0)
        y0_clip = max(0, y0)
        x1_clip = min(width, x1)
        y1_clip = min(height, y1)
        w = x1_clip - x0_clip
        h = y1_clip - y0_clip
        if w <= 0 or h <= 0:
            continue
        filters.append(f"drawbox=x={x0_clip}:y={y0_clip}:w={w}:h={h}:color={color}:t=fill:{enable}")
    return filters


def _box_pixels(
    box: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
    pad: int = 0,
) -> tuple[int, int, int, int]:
    x = int(round(box[0] * width)) - pad
    y = int(round(box[1] * height)) - pad
    w = int(round(box[2] * width)) + pad * 2
    h = int(round(box[3] * height)) + pad * 2
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(1, min(width - x, w))
    h = max(1, min(height - y, h))
    return x, y, w, h


def _box_draw_filters(
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    color: str,
    border_color: str,
    thickness: int,
    enable: str,
) -> list[str]:
    return [
        f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:{enable}",
        f"drawbox=x={x}:y={y}:w={w}:h={h}:color={border_color}:t={thickness}:{enable}",
    ]


def _cursor_filters(
    *,
    point: tuple[float, float],
    width: int,
    height: int,
    color: str,
    border_color: str,
    size: int | None,
    enable: str,
) -> list[str]:
    del color, border_color
    x, y = _pointer_tip_pixels(point, width=width, height=height, size=size)
    return _pointer_shape_filters(
        x_expr=f"{x:.3f}",
        y_expr=f"{y:.3f}",
        width=width,
        height=height,
        size=size,
        enable=enable,
    )


def _expr_add(expr: str, offset: int) -> str:
    if offset == 0:
        return f"({expr})"
    op = "+" if offset > 0 else "-"
    return f"({expr}){op}{abs(offset)}"


def _pointer_dimensions(*, width: int, height: int, size: int | None) -> tuple[int, int]:
    base = size or max(34, min(width, height) // 24)
    pointer_h = max(30, min(54, int(round(base * 0.72))))
    pointer_w = max(18, int(round(pointer_h * 0.62)))
    return pointer_w, pointer_h


def _pointer_tip_pixels(
    point: tuple[float, float],
    *,
    width: int,
    height: int,
    size: int | None,
) -> tuple[float, float]:
    pointer_w, pointer_h = _pointer_dimensions(width=width, height=height, size=size)
    x = point[0] * width
    y = point[1] * height
    x = max(2.0, min(width - pointer_w - 4.0, x))
    y = max(2.0, min(height - pointer_h - 4.0, y))
    return x, y


def _laser_dimensions(*, width: int, height: int, size: int | None) -> tuple[int, int]:
    base = size or max(44, min(width, height) // 22)
    diameter = max(
        LASER_DOT_MIN_DIAMETER,
        min(LASER_DOT_MAX_DIAMETER, int(round(base * LASER_DOT_SIZE_MULTIPLIER))),
    )
    return diameter, diameter


def _ease_expr(start_px: float, end_px: float, start: float, end: float) -> str:
    duration = max(0.001, end - start)
    delta = end_px - start_px
    return f"({start_px:.3f}+({delta:.3f})*(1-cos(PI*(t-{start:.3f})/{duration:.3f}))/2)"


def _pointer_shape_filters(
    *,
    x_expr: str,
    y_expr: str,
    width: int,
    height: int,
    size: int | None,
    enable: str,
) -> list[str]:
    pointer_w, pointer_h = _pointer_dimensions(width=width, height=height, size=size)
    band_h = max(2, pointer_h // 12)

    def draw_triangle(*, dx: int, dy: int, inset: int, color: str) -> list[str]:
        parts: list[str] = []
        for top in range(0, pointer_h, band_h):
            frac = min(1.0, (top + band_h) / pointer_h)
            band_w = max(2, int(round(pointer_w * frac)))
            x = _expr_add(x_expr, dx + inset)
            y = _expr_add(y_expr, dy + top + inset)
            w = max(1, band_w - inset * 2)
            h = max(1, min(band_h, pointer_h - top) - inset)
            if w <= 0 or h <= 0:
                continue
            parts.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill:{enable}")
        return parts

    filters: list[str] = []
    filters.extend(
        draw_triangle(
            dx=2,
            dy=2,
            inset=0,
            color=_color_alpha(CURSOR_POINTER_SHADOW, CURSOR_POINTER_SHADOW_ALPHA),
        )
    )
    filters.extend(
        draw_triangle(
            dx=0,
            dy=0,
            inset=0,
            color=_color_alpha(CURSOR_POINTER_BORDER, CURSOR_POINTER_BORDER_ALPHA),
        )
    )
    filters.extend(
        draw_triangle(
            dx=0,
            dy=0,
            inset=2,
            color=_color_alpha(CURSOR_POINTER_FILL, CURSOR_POINTER_FILL_ALPHA),
        )
    )

    stem_x = int(round(pointer_w * 0.39))
    stem_y = int(round(pointer_h * 0.56))
    stem_w = max(5, int(round(pointer_w * 0.28)))
    stem_h = max(9, int(round(pointer_h * 0.34)))
    filters.append(
        f"drawbox=x={_expr_add(x_expr, stem_x + 2)}:y={_expr_add(y_expr, stem_y + 2)}:"
        f"w={stem_w}:h={stem_h}:"
        f"color={_color_alpha(CURSOR_POINTER_SHADOW, CURSOR_POINTER_SHADOW_ALPHA)}:"
        f"t=fill:{enable}"
    )
    filters.append(
        f"drawbox=x={_expr_add(x_expr, stem_x)}:y={_expr_add(y_expr, stem_y)}:"
        f"w={stem_w}:h={stem_h}:"
        f"color={_color_alpha(CURSOR_POINTER_BORDER, CURSOR_POINTER_BORDER_ALPHA)}:"
        f"t=fill:{enable}"
    )
    filters.append(
        f"drawbox=x={_expr_add(x_expr, stem_x + 2)}:y={_expr_add(y_expr, stem_y + 2)}:"
        f"w={max(1, stem_w - 4)}:h={max(1, stem_h - 4)}:"
        f"color={_color_alpha(CURSOR_POINTER_FILL, CURSOR_POINTER_FILL_ALPHA)}:"
        f"t=fill:{enable}"
    )
    return filters


def _cursor_enabled_cues(cues: list[VisualCue]) -> list[VisualCue]:
    out: list[VisualCue] = []
    for cue in cues:
        if cue.point is None:
            continue
        if cue.cue_type == "cursor":
            out.append(cue)
            continue
        if cue.cue_type == "highlight" and cue.style in CURSOR_STYLES:
            out.append(cue)
    return sorted(out, key=lambda item: (item.start, item.end))


def _laser_enabled_cues(cues: list[VisualCue]) -> list[VisualCue]:
    out: list[VisualCue] = []
    for cue in cues:
        if cue.point is None:
            continue
        if cue.cue_type == "highlight" and cue.style in LASER_STYLES:
            out.append(cue)
    return sorted(out, key=lambda item: (item.start, item.end))


def _spotlight_enabled_cues(cues: list[VisualCue]) -> list[VisualCue]:
    out: list[VisualCue] = []
    for cue in cues:
        if cue.cue_type != "highlight" or cue.box is None:
            continue
        if cue.style in SPOTLIGHT_STYLES:
            out.append(cue)
    return sorted(out, key=lambda item: (item.start, item.end))


def _cursor_path_filters(cues: list[VisualCue], *, width: int, height: int) -> list[str]:
    points = [cue for cue in sorted(cues, key=lambda item: (item.start, item.end)) if cue.point is not None]
    filters: list[str] = []
    for index, cue in enumerate(points):
        next_cue = points[index + 1] if index + 1 < len(points) else None
        start = cue.start
        end = cue.end
        if end <= start:
            continue

        x0, y0 = _pointer_tip_pixels(cue.point, width=width, height=height, size=cue.size)
        stationary_end = end
        if next_cue is not None and next_cue.start > start and next_cue.point is not None:
            move_end = next_cue.start
            move_start = max(start, move_end - CURSOR_MOVE_SECONDS)
            stationary_end = min(end, move_start)
        else:
            move_start = move_end = 0.0

        if stationary_end > start + 0.01:
            filters.extend(
                _pointer_shape_filters(
                    x_expr=f"{x0:.3f}",
                    y_expr=f"{y0:.3f}",
                    width=width,
                    height=height,
                    size=cue.size,
                    enable=f"enable='between(t,{start:.3f},{stationary_end:.3f})'",
                )
            )

        if next_cue is not None and next_cue.point is not None and move_end > move_start + 0.01:
            x1, y1 = _pointer_tip_pixels(next_cue.point, width=width, height=height, size=next_cue.size)
            filters.extend(
                _pointer_shape_filters(
                    x_expr=_ease_expr(x0, x1, move_start, move_end),
                    y_expr=_ease_expr(y0, y1, move_start, move_end),
                    width=width,
                    height=height,
                    size=cue.size,
                    enable=f"enable='between(t,{move_start:.3f},{move_end:.3f})'",
                )
            )
    return filters


def _laser_dot_filters(
    *,
    x_expr: str,
    y_expr: str,
    width: int,
    height: int,
    size: int | None,
    enable: str,
) -> list[str]:
    dot_w, dot_h = _laser_dimensions(width=width, height=height, size=size)
    radius = max(8, min(dot_w, dot_h) // 2)
    core_radius = max(4, int(round(radius * 0.30)))
    band_h = max(2, radius // 8)
    filters: list[str] = []

    for radius_px, color in (
        (radius, _color_alpha("0xF87171", LASER_DOT_HALO_ALPHA)),
        (max(core_radius + 3, int(round(radius * 0.48))), _color_alpha("0xEF4444", 0.72)),
        (core_radius, _color_alpha("0xEF4444", LASER_DOT_CORE_ALPHA)),
    ):
        for y_offset in range(-radius_px, radius_px + 1, band_h):
            y_mid = y_offset + band_h / 2.0
            half_w = int(round(math.sqrt(max(0.0, radius_px * radius_px - y_mid * y_mid))))
            if half_w <= 0:
                continue
            filters.append(
                f"drawbox=x={_expr_add(x_expr, -half_w)}:"
                f"y={_expr_add(y_expr, y_offset)}:"
                f"w={half_w * 2}:h={band_h}:color={color}:t=fill:{enable}"
            )
    return filters


def _laser_path_filters(cues: list[VisualCue], *, width: int, height: int) -> list[str]:
    points = [cue for cue in sorted(cues, key=lambda item: (item.start, item.end)) if cue.point is not None]
    filters: list[str] = []
    for index, cue in enumerate(points):
        next_cue = points[index + 1] if index + 1 < len(points) else None
        start = cue.start
        end = cue.end
        if end <= start:
            continue

        x0 = cue.point[0] * width
        y0 = cue.point[1] * height
        stationary_end = end
        if next_cue is not None and next_cue.start > start and next_cue.point is not None:
            move_end = next_cue.start
            move_start = max(start, move_end - CURSOR_MOVE_SECONDS)
            stationary_end = min(end, move_start)
        else:
            move_start = move_end = 0.0

        if stationary_end > start + 0.01:
            filters.extend(
                _laser_dot_filters(
                    x_expr=f"{x0:.3f}",
                    y_expr=f"{y0:.3f}",
                    width=width,
                    height=height,
                    size=cue.size,
                    enable=f"enable='between(t,{start:.3f},{stationary_end:.3f})'",
                )
            )

        if next_cue is not None and next_cue.point is not None and move_end > move_start + 0.01:
            x1 = next_cue.point[0] * width
            y1 = next_cue.point[1] * height
            filters.extend(
                _laser_dot_filters(
                    x_expr=_ease_expr(x0, x1, move_start, move_end),
                    y_expr=_ease_expr(y0, y1, move_start, move_end),
                    width=width,
                    height=height,
                    size=cue.size,
                    enable=f"enable='between(t,{move_start:.3f},{move_end:.3f})'",
                )
            )
    return filters


def _blend_pixel(dst: tuple[int, int, int, int], src: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    sr, sg, sb, sa = src
    if sa <= 0:
        return dst
    dr, dg, db, da = dst
    src_a = sa / 255.0
    dst_a = da / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0:
        return 0, 0, 0, 0
    out_r = (sr * src_a + dr * dst_a * (1.0 - src_a)) / out_a
    out_g = (sg * src_a + dg * dst_a * (1.0 - src_a)) / out_a
    out_b = (sb * src_a + db * dst_a * (1.0 - src_a)) / out_a
    return int(round(out_r)), int(round(out_g)), int(round(out_b)), int(round(out_a * 255))


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            cross_x = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < cross_x:
                inside = not inside
        j = i
    return inside


def _scale_polygon(
    polygon: list[tuple[float, float]],
    *,
    scale: float,
    origin: tuple[float, float],
) -> list[tuple[float, float]]:
    ox, oy = origin
    return [(ox + (x - ox) * scale, oy + (y - oy) * scale) for x, y in polygon]


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _write_png_rgba_raw(path: Path, width: int, height: int, raw_scanlines: bytes | bytearray) -> None:
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw_scanlines), level=9)))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _write_png_rgba(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row = pixels[y * width:(y + 1) * width]
        for r, g, b, a in row:
            raw.extend((r, g, b, a))
    _write_png_rgba_raw(path, width, height, raw)


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _ink_tighten_box(frame_path, box, *, width: int, height: int,
                     pad_frac: float = INK_TIGHTEN_PAD_FRAC):
    """Shrink a normalized (x, y, w, h) highlight box to the painted-pixel (ink)
    bounds of the content inside it, measured from the rendered slide frame.

    Samples the pixels inside the box, reads the local background from the box's
    border ring, and tightens to the non-background (inked) content, so a loose
    text box spotlights the glyphs rather than the leading/padding. Composes with
    grouping: hand it a UNIONED multi-line box and it hugs all the lines. It is
    CARD-AWARE — a box sitting on a filled card/panel (ring bg differs from the
    slide bg) is kept verbatim so the card reads as one lit unit (no "hole"),
    while transparent text is hugged to its glyphs. Best-effort: needs
    Pillow+numpy; returns the ORIGINAL box on any error, low ink confidence, a
    filled card, or when it would not meaningfully shrink (already tight)."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return box
    try:
        x, y, w, h = box
        img = Image.open(frame_path).convert("RGB")
        iw, ih = img.size
        # replicate the ffmpeg scale(decrease)+pad(black) that letterboxes the
        # slide onto the video frame, so the normalized box maps to real pixels.
        s = min(width / iw, height / ih)
        nw, nh = max(1, round(iw * s)), max(1, round(ih * s))
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(img.resize((nw, nh), Image.LANCZOS), ((width - nw) // 2, (height - nh) // 2))
        px0 = max(0, min(width - 1, int(round(x * width))))
        py0 = max(0, min(height - 1, int(round(y * height))))
        pw = max(2, min(width - px0, int(round(w * width))))
        ph = max(2, min(height - py0, int(round(h * height))))
        crop = np.asarray(canvas.crop((px0, py0, px0 + pw, py0 + ph)), dtype=np.int16)
        ring = np.concatenate([
            crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3),
            crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
        bg = np.median(ring, axis=0)
        # Card/panel guard: keep the whole box when it sits on a FILLED card.
        # page_bg = the dominant colour over a coarse grid of the SOURCE slide
        # (robust to a corner accent bar, unlike sampling the four corners). The
        # box is a filled panel when most of its border ring hugs one fill colour
        # (close_frac, which survives a thin accent bar on one edge) AND that fill
        # differs from the page bg. Then keep the box verbatim (its fill + accent
        # + padding is one lit unit); otherwise fall through and hug the glyphs.
        src = np.asarray(img, dtype=np.int16)
        gy = max(1, ih // 24)
        gx = max(1, iw // 24)
        grid = ((src[::gy, ::gx].reshape(-1, 3)) // 12) * 12
        uv, uc = np.unique(grid, axis=0, return_counts=True)
        page_bg = uv[uc.argmax()].astype(np.int16)
        close_frac = float((np.abs(ring - bg).sum(axis=1) < 30).mean())
        if close_frac > INK_TIGHTEN_CARD_UNIFORM and float(np.abs(bg - page_bg).sum()) > INK_TIGHTEN_CARD_DELTA:
            return box
        mask = np.abs(crop - bg).sum(axis=2) > 40
        if int(mask.sum()) < 0.002 * mask.size:          # too little ink -> not confident
            return box
        # Tight bbox of all inked pixels: trims the box's outer whitespace (leading,
        # internal padding, top/middle anchor) down to the visible glyphs. This hugs
        # whatever ink is in the box, so the box must already be the intended LOGICAL
        # unit. Grouping fragments that belong together (e.g. a title split across two
        # overlapping boxes) is the caller's / upstream's job — paper2video's
        # generate_visual_cues unions same-group text fragments into the cue box;
        # ink-tighten does not decide WHAT to highlight, only HOW tightly.
        ys, xs = np.where(mask)
        ix0, iy0, ix1, iy1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        pad = int(round(pad_frac * min(width, height)))
        ix0 = max(0, ix0 - pad); iy0 = max(0, iy0 - pad)
        ix1 = min(pw, ix1 + pad); iy1 = min(ph, iy1 + pad)
        if (ix1 - ix0) * (iy1 - iy0) > 0.985 * pw * ph:  # already tight -> keep declared box
            return box
        return ((px0 + ix0) / width, (py0 + iy0) / height,
                (ix1 - ix0) / width, (iy1 - iy0) / height)
    except Exception:
        return box


def _write_spotlight_mask_png(
    path: Path,
    *,
    box: tuple[float, float, float, float],
    width: int,
    height: int,
    thickness: int,
) -> None:
    """Write a full-frame RGBA dimming mask with a smooth transparent window."""
    inner_pad = max(4, int(round(thickness * SPOTLIGHT_INNER_PAD_MULTIPLIER)))
    x, y, w, h = _box_pixels(box, width=width, height=height, pad=inner_pad)
    left = float(x)
    top = float(y)
    right = float(x + w)
    bottom = float(y + h)
    feather = max(
        SPOTLIGHT_MIN_FEATHER_PX,
        int(round(min(width, height) * SPOTLIGHT_FEATHER_RATIO)),
        thickness * SPOTLIGHT_FEATHER_THICKNESS_MULTIPLIER,
    )
    max_alpha = int(round(255 * SPOTLIGHT_MAX_ALPHA))

    raw = bytearray()
    for py in range(height):
        raw.append(0)
        cy = py + 0.5
        if cy < top:
            dy = top - cy
        elif cy > bottom:
            dy = cy - bottom
        else:
            dy = 0.0
        for px in range(width):
            cx = px + 0.5
            if cx < left:
                dx = left - cx
            elif cx > right:
                dx = cx - right
            else:
                dx = 0.0
            if dx == 0.0 and dy == 0.0:
                alpha = 0
            else:
                distance = math.hypot(dx, dy)
                alpha = int(round(max_alpha * _smoothstep(distance / feather)))
            raw.extend((0, 0, 0, alpha))
    _write_png_rgba_raw(path, width, height, raw)


def _write_cursor_png(path: Path, *, width: int, height: int) -> tuple[int, int]:
    """Write a small transparent mouse pointer PNG using only stdlib code."""
    tip = (CURSOR_OVERLAY_TIP_OFFSET, CURSOR_OVERLAY_TIP_OFFSET)
    pointer = [
        tip,
        (width * 0.78, height * 0.58),
        (width * 0.54, height * 0.60),
        (width * 0.68, height * 0.88),
        (width * 0.52, height * 0.94),
        (width * 0.39, height * 0.66),
        (width * 0.21, height * 0.82),
    ]
    fill = _scale_polygon(pointer, scale=0.80, origin=tip)
    layers = [
        ([(x + 2.0, y + 2.0) for x, y in pointer], (0, 0, 0, int(255 * CURSOR_POINTER_SHADOW_ALPHA))),
        (pointer, (248, 250, 252, int(255 * CURSOR_POINTER_BORDER_ALPHA))),
        (fill, (30, 41, 59, int(255 * CURSOR_POINTER_FILL_ALPHA))),
    ]

    pixels: list[tuple[int, int, int, int]] = []
    samples = (0.25, 0.5, 0.75)
    for py in range(height):
        for px in range(width):
            pixel = (0, 0, 0, 0)
            for polygon, color in layers:
                hits = 0
                for sy in samples:
                    for sx in samples:
                        if _point_in_polygon(px + sx, py + sy, polygon):
                            hits += 1
                if hits:
                    alpha = int(round(color[3] * hits / (len(samples) ** 2)))
                    pixel = _blend_pixel(pixel, (color[0], color[1], color[2], alpha))
            pixels.append(pixel)
    _write_png_rgba(path, width, height, pixels)
    return CURSOR_OVERLAY_TIP_OFFSET, CURSOR_OVERLAY_TIP_OFFSET


def _write_laser_png(path: Path, *, width: int, height: int) -> tuple[int, int]:
    """Write a small transparent laser-pointer dot with a soft red halo."""
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    halo_radius = max(1.0, min(width, height) * 0.46)
    ring_radius = max(1.0, min(width, height) * 0.22)
    core_radius = max(4.0, min(width, height) * 0.135)

    pixels: list[tuple[int, int, int, int]] = []
    for py in range(height):
        for px in range(width):
            dx = px + 0.5 - center_x
            dy = py + 0.5 - center_y
            distance = math.hypot(dx, dy)
            pixel = (0, 0, 0, 0)
            if distance <= halo_radius:
                if distance <= core_radius:
                    alpha = int(round(255 * LASER_DOT_CORE_ALPHA))
                    pixel = (*LASER_DOT_FILL, alpha)
                elif distance <= ring_radius:
                    t = (distance - core_radius) / max(0.001, ring_radius - core_radius)
                    alpha = int(round(255 * (0.82 - 0.40 * _smoothstep(t))))
                    pixel = (*LASER_DOT_FILL, alpha)
                else:
                    t = (distance - ring_radius) / max(0.001, halo_radius - ring_radius)
                    alpha = int(round(255 * LASER_DOT_HALO_ALPHA * (1.0 - _smoothstep(t))))
                    pixel = (*LASER_DOT_HALO, alpha)
            pixels.append(pixel)
    _write_png_rgba(path, width, height, pixels)
    return int(round(center_x)), int(round(center_y))


def _cursor_overlay_intervals(
    cues: list[VisualCue],
    *,
    width: int,
    height: int,
    cursor_width: int,
    cursor_height: int,
    tip_x: int,
    tip_y: int,
) -> tuple[list[tuple[float, float, str, str]], float, float]:
    points = [cue for cue in cues if cue.point is not None]
    if not points:
        return [], 0.0, 0.0

    def overlay_xy(cue: VisualCue) -> tuple[float, float]:
        px = cue.point[0] * width - tip_x
        py = cue.point[1] * height - tip_y
        px = max(0.0, min(width - cursor_width, px))
        py = max(0.0, min(height - cursor_height, py))
        return px, py

    intervals: list[tuple[float, float, str, str]] = []
    for index, cue in enumerate(points):
        next_cue = points[index + 1] if index + 1 < len(points) else None
        x0, y0 = overlay_xy(cue)
        start = cue.start
        end = cue.end
        if next_cue is not None and next_cue.start > start:
            move_end = next_cue.start
            move_start = max(start, move_end - CURSOR_MOVE_SECONDS)
            if move_start > start + 0.01:
                intervals.append((start, move_start, f"{x0:.3f}", f"{y0:.3f}"))
            x1, y1 = overlay_xy(next_cue)
            if move_end > move_start + 0.01:
                intervals.append((move_start, move_end, _ease_expr(x0, x1, move_start, move_end), _ease_expr(y0, y1, move_start, move_end)))
        elif end > start + 0.01:
            intervals.append((start, end, f"{x0:.3f}", f"{y0:.3f}"))

    return intervals, points[0].start, max(point.end for point in points)


def _piecewise_overlay_expr(intervals: list[tuple[float, float, str, str]], *, axis: int) -> str:
    if not intervals:
        return "0"
    expr = intervals[-1][2 + axis]
    for start, end, x_expr, y_expr in reversed(intervals[:-1]):
        value = x_expr if axis == 0 else y_expr
        expr = f"if(between(t,{start:.3f},{end:.3f}),{value},{expr})"
    return expr


def _outside_box_filters(
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    width: int,
    height: int,
    color: str,
    enable: str,
) -> list[str]:
    filters: list[str] = []
    if y > 0:
        filters.append(f"drawbox=x=0:y=0:w={width}:h={y}:color={color}:t=fill:{enable}")
    bottom = y + h
    if bottom < height:
        filters.append(f"drawbox=x=0:y={bottom}:w={width}:h={height - bottom}:color={color}:t=fill:{enable}")
    if x > 0 and h > 0:
        filters.append(f"drawbox=x=0:y={y}:w={x}:h={h}:color={color}:t=fill:{enable}")
    right = x + w
    if right < width and h > 0:
        filters.append(f"drawbox=x={right}:y={y}:w={width - right}:h={h}:color={color}:t=fill:{enable}")
    return filters


def _spotlight_filters(
    *,
    box: tuple[float, float, float, float],
    width: int,
    height: int,
    accent_color: str,
    thickness: int,
    enable: str,
) -> list[str]:
    filters: list[str] = []
    # Dim only outside the selected target. This keeps the target at original
    # slide brightness instead of washing the whole slide gray.
    fade_layers = (
        (max(56, thickness * 11), 0.028),
        (max(28, thickness * 6), 0.040),
        (max(6, thickness * 2), 0.052),
    )
    for pad, alpha in fade_layers:
        x, y, w, h = _box_pixels(box, width=width, height=height, pad=pad)
        filters.extend(
            _outside_box_filters(
                x=x,
                y=y,
                w=w,
                h=h,
                width=width,
                height=height,
                color=_color_alpha(SPOTLIGHT_DIM_COLOR, alpha),
                enable=enable,
            )
        )
    x, y, w, h = _box_pixels(box, width=width, height=height, pad=max(2, thickness))
    filters.append(
        f"drawbox=x={x}:y={y}:w={w}:h={h}:"
        f"color={_color_alpha(accent_color, SPOTLIGHT_BORDER_ALPHA)}:"
        f"t={max(2, thickness - 1)}:{enable}"
    )
    return filters


def _attention_filters(
    cues: list[VisualCue],
    *,
    width: int,
    height: int,
    include_cursor: bool = True,
    include_laser: bool = True,
    include_spotlight: bool = True,
) -> list[str]:
    filters: list[str] = []
    cursor_cues: list[VisualCue] = []
    laser_cues: list[VisualCue] = []
    for cue in cues:
        color = _color_alpha(cue.color, cue.opacity)
        border_color = _color_alpha(cue.color, HIGHLIGHT_BORDER_ALPHA)
        enable = _enable_expr(cue)

        if cue.cue_type == "highlight" and cue.box is not None:
            thickness = max(3, cue.border or min(width, height) // 180)
            pad = max(1, int(round(thickness * HIGHLIGHT_BOX_EXPAND_MULTIPLIER)))
            style = cue.style if cue.style in VALID_HIGHLIGHT_STYLES else "box"
            x, y, w, h = _box_pixels(cue.box, width=width, height=height, pad=pad)
            if style in {"box", "box_cursor", "box_laser"}:
                filters.extend(
                    _box_draw_filters(
                        x=x, y=y, w=w, h=h,
                        color=color,
                        border_color=border_color,
                        thickness=thickness,
                        enable=enable,
                    )
                )
            elif include_spotlight and style in SPOTLIGHT_STYLES:
                filters.extend(
                    _spotlight_filters(
                        box=cue.box,
                        width=width,
                        height=height,
                        accent_color=cue.color,
                        thickness=thickness,
                        enable=enable,
                    )
                )
            if include_cursor and style in CURSOR_STYLES and cue.point is not None:
                cursor_cues.append(cue)
            if include_laser and style in LASER_STYLES and cue.point is not None:
                laser_cues.append(cue)
            continue

        if cue.cue_type == "highlight" and cue.point is not None:
            style = cue.style if cue.style in VALID_HIGHLIGHT_STYLES else "box"
            if style in CURSOR_STYLES:
                if include_cursor:
                    cursor_cues.append(cue)
                continue
            if style in LASER_STYLES:
                if include_laser:
                    laser_cues.append(cue)
                continue
            radius = cue.size or max(42, min(width, height) // 18)
            cx = int(round(cue.point[0] * width))
            cy = int(round(cue.point[1] * height))
            filters.extend(
                _circle_drawbox_filters(
                    cx=cx, cy=cy, radius=radius,
                    width=width, height=height,
                    color=color, enable=enable,
                )
            )
            continue

        if cue.cue_type == "cursor" and cue.point is not None:
            if include_cursor:
                cursor_cues.append(cue)
    if cursor_cues:
        filters.extend(_cursor_path_filters(cursor_cues, width=width, height=height))
    if laser_cues:
        filters.extend(_laser_path_filters(laser_cues, width=width, height=height))
    return filters


# ---------------------------------------------------------------------------
# Stage C — encode each slide as an MP4 segment, then concat
# ---------------------------------------------------------------------------

def _animation_strategy(name: str) -> str:
    if name == "Appear":
        return "appear"
    if name in {"Fade In", "Dissolve In"}:
        return "alpha_fade"
    if name == "Fly In":
        return "fly_from_left"
    if name == "Wipe In":
        return "wipe_from_left"
    if name == "Zoom In":
        return "zoom_in"
    if name == "Circle In":
        return "circle_reveal"
    if name == "Diamond In":
        return "diamond_reveal"
    raise ValueError(f"unsupported animation effect: {name}")


def _animation_sample_times(
    strategy: str,
    *,
    global_start: float,
    duration: float,
    segment_start: float,
    fps: int,
) -> tuple[float, float]:
    """Choose pixel-QA samples that straddle an instant Appear transition."""
    if strategy == "appear":
        frame_step = 1.25 / max(1, fps)
        return (
            max(segment_start, global_start - frame_step),
            global_start + frame_step,
        )
    return (
        global_start + duration * 0.20,
        global_start + duration * 0.85,
    )


def _animation_overlay_filters(
    layer: AnimationLayer,
    *,
    input_index: int,
    current_label: str,
    sequence: int,
    fps: int,
) -> tuple[list[str], str]:
    effect = layer.effect
    start = effect.start
    duration = max(0.05, effect.duration)
    strategy = _animation_strategy(effect.name)
    source_label = f"animsrc{sequence}"
    output_label = f"animbase{sequence}"
    progress = f"min(max((t-{start:.3f})/{duration:.3f},0),1)"
    alpha_progress = f"min(max((T-{start:.3f})/{duration:.3f},0),1)"
    x_expr = f"{layer.x}"
    y_expr = f"{layer.y}"
    # Layer inputs are static PNGs read at 1 fps to avoid image-demux queues
    # growing by tens of gigabytes in a long multi-input filter graph. Restore
    # the delivery frame rate lazily inside the filter graph before animation.
    source_filter = f"[{input_index}:v]fps={fps},format=rgba"
    if strategy == "alpha_fade":
        source_filter += f",fade=t=in:st={start:.3f}:d={duration:.3f}:alpha=1"
    if strategy == "fly_from_left":
        source_filter += f",fade=t=in:st={start:.3f}:d={min(0.18, duration):.3f}:alpha=1"
        travel = max(96, min(420, int(round(layer.width * 0.55))))
        x_expr = f"{layer.x}-{travel}*(1-{progress})"
    elif strategy == "wipe_from_left":
        # `crop` dimensions are configured once, so use a per-frame alpha mask.
        source_filter += (
            ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='alpha(X,Y)*lte(X,W*{alpha_progress})'"
        )
    elif strategy == "zoom_in":
        # Scale into a fixed transparent canvas so overlay geometry never jumps.
        scale = f"0.72+0.28*{progress}"
        pad_margin = 2
        source_filter += (
            f",scale=w='min({layer.width},max(2,floor({layer.width}*({scale}))))':"
            f"h='min({layer.height},max(2,floor({layer.height}*({scale}))))':eval=frame,"
            f"pad=w={layer.width + pad_margin * 2}:h={layer.height + pad_margin * 2}:"
            "x='(ow-iw)/2':y='(oh-ih)/2':"
            "color=0x00000000:eval=frame,"
            f"fade=t=in:st={start:.3f}:d={min(0.20, duration):.3f}:alpha=1"
        )
        x_expr = f"{layer.x - pad_margin}"
        y_expr = f"{layer.y - pad_margin}"
    elif strategy == "circle_reveal":
        radius = math.hypot(layer.width / 2.0, layer.height / 2.0)
        source_filter += (
            ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='alpha(X,Y)*lte(hypot(X-W/2,Y-H/2),{radius:.3f}*{alpha_progress})'"
        )
    elif strategy == "diamond_reveal":
        source_filter += (
            ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='alpha(X,Y)*lte(abs(X-W/2)/(W/2)+abs(Y-H/2)/(H/2),{alpha_progress})'"
        )
    source_filter += f"[{source_label}]"
    filters = [
        source_filter,
        f"[{current_label}][{source_label}]overlay=x='{x_expr}':y='{y_expr}':"
        f"enable='gte(t,{start:.3f})'"
        f"[{output_label}]",
    ]
    return filters, output_label


def write_animation_render_report(
    path: Path,
    *,
    manifest_path: Path,
    out_path: Path,
    pairs: list[SlidePair],
    animation_map: dict[int, AnimationSlide],
    animation_assets: dict[int, AnimationSlideAssets],
    source_kind: str,
    source_path: Path,
    source_sha256: str,
    start_pad: float,
    pad_tail: float,
    fps: int,
    width: int,
    height: int,
) -> dict[str, object]:
    """Persist the exact Author Notes animation mapping rendered into MP4 pixels."""
    segment_start = start_pad
    slides: list[dict[str, object]] = []
    effect_count = 0
    for pair in pairs:
        slide = animation_map[pair.index]
        assets = animation_assets[pair.index]
        effects: list[dict[str, object]] = []
        for layer in assets.layers:
            effect = layer.effect
            global_start = segment_start + effect.start
            global_end = global_start + effect.duration
            strategy = _animation_strategy(effect.name)
            sample_early, sample_late = _animation_sample_times(
                strategy,
                global_start=global_start,
                duration=effect.duration,
                segment_start=segment_start,
                fps=fps,
            )
            effects.append(
                {
                    "order": effect.order,
                    "shape_id": effect.shape_id,
                    "locator": effect.locator,
                    "name": effect.name,
                    "strategy": strategy,
                    "start": round(effect.start, 3),
                    "duration": round(effect.duration, 3),
                    "global_start": round(global_start, 3),
                    "global_end": round(global_end, 3),
                    "timing_source": effect.timing_source,
                    "bbox": [layer.x, layer.y, layer.width, layer.height],
                    "sample_early": round(sample_early, 3),
                    "sample_late": round(sample_late, 3),
                    "rendered": True,
                }
            )
            effect_count += 1
        segment_end = segment_start + pair.duration + pad_tail
        slides.append(
            {
                "index": pair.index,
                "id": slide.slide_id,
                "segment_start": round(segment_start, 3),
                "segment_end": round(segment_end, 3),
                "effect_count": len(effects),
                "effects": effects,
            }
        )
        segment_start = segment_end
    report: dict[str, object] = {
        "schema_version": ANIMATION_RENDER_REPORT_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "manifest": str(manifest_path),
        "output": str(out_path),
        "source_kind": source_kind,
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "timing_source": "author_notes_or_animation_pane",
        "slide_count": len(slides),
        "effect_count": effect_count,
        "start_pad": start_pad,
        "pad_tail": pad_tail,
        "fps": fps,
        "resolution": {"width": width, "height": height},
        "slides": slides,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report

def encode_segment(pair: SlidePair, out_seg: Path, *,
                   width: int, height: int, fps: int, pad_tail: float,
                   ffmpeg: str, visual_cues: list[VisualCue] | None = None,
                   animation_assets: AnimationSlideAssets | None = None) -> None:
    """Render one PNG + one MP3 → an MP4 segment of length audio + pad_tail.

    Image is scaled to fit `width`x`height` while preserving aspect ratio,
    then padded with black to exact size — matches how a presentation app
    letterboxes a slide on a 16:9 screen if the deck is 4:3, etc.
    """
    total_dur = pair.duration + pad_tail
    vf_filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
    ]
    if visual_cues:
        cursor_cues = _cursor_enabled_cues(visual_cues)
        laser_cues = _laser_enabled_cues(visual_cues)
        spotlight_cues = _spotlight_enabled_cues(visual_cues)
        vf_filters.extend(
            _attention_filters(
                visual_cues,
                width=width,
                height=height,
                include_cursor=not cursor_cues,
                include_laser=not laser_cues,
                include_spotlight=not spotlight_cues,
            )
        )
    else:
        cursor_cues = []
        laser_cues = []
        spotlight_cues = []

    # apad pads the audio with silence so we don't depend on -shortest and risk
    # the video ending mid-word. We intentionally use bare `apad` rather than
    # `apad=pad_dur=...`: older ffmpeg builds (for example 2.4.x) don't support
    # pad_dur. The segment-level `-t total_dur` below still clips the padded
    # stream to exactly audio_duration + pad_tail.
    #
    # The aresample+aformat prefix is critical: TTS MP3s arrive with varying
    # sample rates / channel layouts, and feeding them straight into AAC + apad
    # produces segment-level AAC streams whose internal frame parameters drift
    # between slides. The concat demuxer then stream-copies those mismatched
    # streams into a single MP4 whose audio track decodes to garbage (silent /
    # clicky playback). Pre-normalizing to 44.1 kHz stereo and pinning
    # -profile:a aac_low makes every segment's AAC bytestream identical-shaped.
    af = (
        f"aresample=44100,"
        f"aformat=channel_layouts=stereo:sample_rates=44100,"
        f"apad"
    )

    if animation_assets or spotlight_cues or cursor_cues or laser_cues:
        with tempfile.TemporaryDirectory(prefix="paper2video_attention_") as td:
            base_frame = animation_assets.base_frame if animation_assets else pair.frame
            input_args = [
                "-loop", "1", "-framerate", str(fps), "-i", str(base_frame),
                "-i", str(pair.audio),
            ]
            next_input = 2
            animation_inputs: list[tuple[int, AnimationLayer]] = []
            if animation_assets:
                for layer in animation_assets.layers:
                    input_args.extend(
                        ["-loop", "1", "-framerate", "1", "-i", str(layer.path)]
                    )
                    animation_inputs.append((next_input, layer))
                    next_input += 1
            spotlight_inputs: list[tuple[int, VisualCue]] = []
            for index, cue in enumerate(spotlight_cues):
                if cue.box is None:
                    continue
                thickness = max(3, cue.border or min(width, height) // 180)
                spot_box = (_ink_tighten_box(pair.frame, cue.box, width=width, height=height)
                            if (INK_TIGHTEN and not cue.no_ink_tighten) else cue.box)
                mask_path = Path(td) / f"spotlight_{index:02d}.png"
                _write_spotlight_mask_png(
                    mask_path,
                    box=spot_box,
                    width=width,
                    height=height,
                    thickness=thickness,
                )
                input_args.extend(["-loop", "1", "-framerate", "1", "-i", str(mask_path)])
                spotlight_inputs.append((next_input, cue))
                next_input += 1

            cursor_input: int | None = None
            intervals: list[tuple[float, float, str, str]] = []
            first_start = 0.0
            last_end = 0.0
            if cursor_cues:
                cursor_size = max((cue.size or 0) for cue in cursor_cues) or None
                pointer_w, pointer_h = _pointer_dimensions(width=width, height=height, size=cursor_size)
                cursor_w = pointer_w + 10
                cursor_h = pointer_h + 10
                cursor_path = Path(td) / "cursor.png"
                tip_x, tip_y = _write_cursor_png(cursor_path, width=cursor_w, height=cursor_h)
                intervals, first_start, last_end = _cursor_overlay_intervals(
                    cursor_cues,
                    width=width,
                    height=height,
                    cursor_width=cursor_w,
                    cursor_height=cursor_h,
                    tip_x=tip_x,
                    tip_y=tip_y,
                )
                if intervals:
                    input_args.extend(["-loop", "1", "-framerate", "1", "-i", str(cursor_path)])
                    cursor_input = next_input
                    next_input += 1

            laser_input: int | None = None
            laser_intervals: list[tuple[float, float, str, str]] = []
            laser_first_start = 0.0
            laser_last_end = 0.0
            if laser_cues:
                laser_size = max((cue.size or 0) for cue in laser_cues) or None
                laser_w, laser_h = _laser_dimensions(width=width, height=height, size=laser_size)
                laser_path = Path(td) / "laser.png"
                laser_tip_x, laser_tip_y = _write_laser_png(laser_path, width=laser_w, height=laser_h)
                laser_intervals, laser_first_start, laser_last_end = _cursor_overlay_intervals(
                    laser_cues,
                    width=width,
                    height=height,
                    cursor_width=laser_w,
                    cursor_height=laser_h,
                    tip_x=laser_tip_x,
                    tip_y=laser_tip_y,
                )
                if laser_intervals:
                    input_args.extend(["-loop", "1", "-framerate", "1", "-i", str(laser_path)])
                    laser_input = next_input
                    next_input += 1

            filter_parts = [f"[0:v]{','.join(vf_filters)}[base0]"]
            current_label = "base0"
            for index, (input_index, layer) in enumerate(animation_inputs):
                layer_filters, current_label = _animation_overlay_filters(
                    layer,
                    input_index=input_index,
                    current_label=current_label,
                    sequence=index,
                    fps=fps,
                )
                filter_parts.extend(layer_filters)
            for index, (input_index, cue) in enumerate(spotlight_inputs):
                mask_label = f"spotmask{index}"
                next_label = f"spotbase{index}"
                filter_parts.append(f"[{input_index}:v]fps={fps},format=rgba[{mask_label}]")
                filter_parts.append(
                    f"[{current_label}][{mask_label}]overlay=x=0:y=0:"
                    f"enable='between(t,{cue.start:.3f},{cue.end:.3f})'[{next_label}]"
                )
                current_label = next_label

            if cursor_input is not None:
                x_expr = _piecewise_overlay_expr(intervals, axis=0)
                y_expr = _piecewise_overlay_expr(intervals, axis=1)
                filter_parts.append(f"[{cursor_input}:v]fps={fps},format=rgba[cursor]")
                filter_parts.append(
                    f"[{current_label}][cursor]overlay=x='{x_expr}':y='{y_expr}':"
                    f"enable='between(t,{first_start:.3f},{last_end:.3f})'[withcursor]"
                )
                current_label = "withcursor"

            if laser_input is not None:
                x_expr = _piecewise_overlay_expr(laser_intervals, axis=0)
                y_expr = _piecewise_overlay_expr(laser_intervals, axis=1)
                filter_parts.append(f"[{laser_input}:v]fps={fps},format=rgba[laser]")
                filter_parts.append(
                    f"[{current_label}][laser]overlay=x='{x_expr}':y='{y_expr}':"
                    f"enable='between(t,{laser_first_start:.3f},{laser_last_end:.3f})'[withlaser]"
                )
                current_label = "withlaser"

            filter_parts.append(f"[{current_label}]format=yuv420p[v]")
            cmd = [
                ffmpeg, "-y",
                *input_args,
                "-filter_complex", ";".join(filter_parts),
                "-map", "[v]",
                "-map", "1:a",
                "-af", af,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-strict", "-2",
                "-profile:a", "aac_low",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-t", f"{total_dur:.3f}",
                "-movflags", "+faststart",
                str(out_seg),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
    else:
        vf_filters.append("format=yuv420p")
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-framerate", str(fps), "-i", str(pair.frame),
            "-i", str(pair.audio),
            "-vf", ",".join(vf_filters),
            "-af", af,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-strict", "-2",
            "-profile:a", "aac_low",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-t", f"{total_dur:.3f}",
            "-movflags", "+faststart",
            str(out_seg),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"[render_video] ffmpeg failed on slide {pair.index}:\n{proc.stderr}")


def concat_segments(segments: list[Path], out_path: Path, ffmpeg: str,
                    start_pad: float, fps: int, width: int, height: int) -> None:
    """Concatenate per-slide segments into the final MP4.

    We use the concat *demuxer* (file-list approach) rather than the concat
    filter because all our segments share codecs/dimensions — the demuxer is
    a stream copy, much faster than re-encoding and bit-exact for video.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="concat_list_") as td:
        list_path = Path(td) / "list.txt"

        # Optional leading silence before the first slide.
        if start_pad > 0:
            black_seg = Path(td) / "black.mp4"
            blackcmd = [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"color=black:s={width}x{height}:r={fps}",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{start_pad:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-strict", "-2",
                "-pix_fmt", "yuv420p",
                "-shortest", str(black_seg),
            ]
            proc = subprocess.run(blackcmd, capture_output=True, text=True)
            if proc.returncode != 0:
                sys.exit(f"[render_video] ffmpeg failed on lead-in:\n{proc.stderr}")
            segments = [black_seg] + segments

        list_lines = [f"file {shlex.quote(str(s.resolve()))}" for s in segments]
        list_path.write_text("\n".join(list_lines) + "\n", encoding="utf-8")

        # All segments share codecs/dimensions AND identical AAC frame layout
        # (encode_segment normalizes via aresample+aformat+aac_low), so the
        # concat demuxer can stream-copy both video and audio — bit-exact and
        # much faster than re-encoding. If you change encode_segment in a way
        # that lets segment audio shape drift again, switch this back to a
        # full re-encode or you'll get silent/corrupt audio in the output.
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"[render_video] ffmpeg concat failed:\n{proc.stderr}")


def verify_output(mp4: Path, ffprobe: str, ffmpeg: str) -> float:
    """Confirm the file plays and return its duration."""
    if ffprobe != ffmpeg:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
            capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())

    out = subprocess.run([ffmpeg, "-i", str(mp4)], capture_output=True, text=True)
    m = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", out.stderr)
    if not m:
        sys.exit(f"[render_video] could not verify {mp4} — ffmpeg/ffprobe gave no duration.")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def write_duration_report(
    report_path: Path,
    *,
    out_path: Path,
    pairs: list[SlidePair],
    frame_source: str,
    frames_dir: Path,
    svg_dir: Path | None,
    actual_seconds: float,
    expected_seconds: float,
    target_minutes: float | None,
    tolerance_seconds: float,
    start_pad: float,
    pad_tail: float,
    fps: int,
    width: int,
    height: int,
    visual_cue_map: dict[int, list[VisualCue]],
) -> dict:
    target_seconds = target_minutes * 60.0 if target_minutes is not None else None
    if target_seconds is None:
        status = "no_target"
        delta = None
    else:
        delta = actual_seconds - target_seconds
        if abs(delta) <= tolerance_seconds:
            status = "within_tolerance"
        elif delta > 0:
            status = "above_target"
        else:
            status = "below_target"

    report = {
        "schema_version": DURATION_REPORT_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "output": str(out_path),
        "status": status,
        "target_minutes": target_minutes,
        "target_seconds": round(target_seconds, 3) if target_seconds is not None else None,
        "tolerance_seconds": tolerance_seconds,
        "actual_seconds": round(actual_seconds, 3),
        "expected_seconds": round(expected_seconds, 3),
        "target_delta_seconds": round(delta, 3) if delta is not None else None,
        "render_delta_seconds": round(actual_seconds - expected_seconds, 3),
        "start_pad": start_pad,
        "pad_tail": pad_tail,
        "fps": fps,
        "resolution": {"width": width, "height": height},
        "frame_source": frame_source,
        "frames_dir": str(frames_dir),
        "svg_dir": str(svg_dir) if svg_dir is not None else None,
        "slides": [
            {
                "index": pair.index,
                "audio": pair.audio.name,
                "audio_seconds": round(pair.duration, 3),
                "segment_seconds": round(pair.duration + pad_tail, 3),
                "visual_cues": len(visual_cue_map.get(pair.index, [])),
            }
            for pair in pairs
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_path", help="ppt-master project root")
    ap.add_argument("--pptx", required=True, help="Path to the exported PPTX")
    ap.add_argument("--audio-dir", default=None,
                    help="Directory of per-slide MP3s (default: <project>/audio)")
    ap.add_argument("--script-json", default=None,
                    help="Narration script JSON whose sections order defines audio order. "
                         "Defaults to <audio-dir>/script.json, then <project>/assets/meta/narration.json, then <project>/narration.json, "
                         "then manifest/sorted filenames.")
    ap.add_argument("--out", default=None,
                    help="Output MP4 path (default: <project>/exports/<pptx_stem>.mp4)")
    ap.add_argument("--resolution", choices=tuple(RESOLUTIONS), default="1080p",
                    help="Output frame size preset (default: 1080p)")
    ap.add_argument("--dpi", type=int, default=None,
                    help="Legacy PPTX/PDF PNG render DPI; default chosen to match the resolution preset")
    ap.add_argument("--frame-source", choices=("auto", "svg", "pptx"), default="auto",
                    help="Slide raster source. auto prefers <project>/svg_final, then svg_output, "
                         "and falls back to PPTX/PDF only when no SVG deck exists.")
    ap.add_argument("--svg-dir", default=None,
                    help="Explicit SVG frame directory. Defaults to <project>/svg_final, then svg_output.")
    ap.add_argument("--browser-executable", default=None,
                    help="Chrome/Chromium executable for SVG frame screenshots. Defaults to "
                         "PAPER2VIDEO_CHROME/CHROME/CHROMIUM or a common system install.")
    ap.add_argument("--frames-out", default=None,
                    help="Copy the exact rendered frames used for the MP4 to this directory, "
                         "for example $VIDEO_OUT/assets/slides/frames.")
    ap.add_argument("--fps", type=int, default=30, help="Output frame rate (default: 30)")
    ap.add_argument("--pad-tail", type=float, default=0.3,
                    help="Silence appended after each slide's narration (default: 0.3s)")
    ap.add_argument("--start-pad", type=float, default=0.5,
                    help="Black-screen silence before slide 1 (default: 0.5s)")
    ap.add_argument("--target-minutes", type=float, default=None,
                    help="Target final video duration in minutes. render_video.py reports whether "
                         "the actual MP4 lands within tolerance; use notes_to_script.py or "
                         "assets_to_script.py with the same target to shape narration before TTS.")
    ap.add_argument("--duration-tolerance-seconds", type=float, default=30.0,
                    help="Allowed final video duration error when --target-minutes is set (default: 30s).")
    ap.add_argument("--duration-report-out", default=None,
                    help="Output duration report JSON (default: <out_stem>_duration_report.json "
                         "when --target-minutes is set).")
    ap.add_argument("--attention-mode", choices=("none", "highlight", "cursor", "both"), default="highlight",
                    help="Attention overlay mode (default: highlight). Requires --visual-cues "
                         "for positioned highlights/cursors.")
    ap.add_argument("--highlight-style", choices=tuple(sorted(VALID_HIGHLIGHT_STYLES)), default="spotlight_laser",
                    help="How highlight cues should render: box, spotlight, cursor, box+cursor, "
                         "spotlight+cursor, laser dot, box+laser, or spotlight+laser.")
    ap.add_argument("--visual-cues", default=None,
                    help="JSON file describing per-slide highlight/cursor cues in normalized coordinates.")
    ap.add_argument("--allow-missing-visual-cues", action="store_true",
                    help="Degraded/debug only: allow highlight/cursor/both without --visual-cues.")
    ap.add_argument("--animation-manifest", default=None,
                    help="Author Notes animation manifest written by build_animation_manifest.py. "
                         "Burns the mapped effects into MP4 pixels from SVG or editable PPTX states.")
    ap.add_argument("--animation-source", choices=("auto", "svg", "pptx"), default="auto",
                    help="Animation pixel source. auto follows animation_manifest.source_kind; "
                         "editable PPTX manifests force the current PPTX to be the frame source.")
    ap.add_argument("--animation-report-out", default=None,
                    help="Persistent animation render report JSON. Defaults to "
                         "<out_stem>_animation_report.json when animations are rendered.")
    ap.add_argument("--require-animations", action="store_true",
                    help="Fail unless a non-empty, Edge-aligned animation manifest is rendered.")
    ap.add_argument("--frames-only", action="store_true",
                    help="Stop after PNG export — useful for previewing slide rendering")
    ap.add_argument("--audio-only-check", action="store_true",
                    help="Verify each slide has matching audio, then exit (no rendering)")
    ap.add_argument("--keep-temp", action="store_true",
                    help="Keep the temp working dir (slides/segments) for debugging")
    args = ap.parse_args()

    project_path = Path(args.project_path).resolve()
    pptx_path = Path(args.pptx).resolve()
    if not pptx_path.is_file():
        sys.exit(f"[render_video] PPTX not found: {pptx_path}")
    if args.target_minutes is not None and args.target_minutes <= 0:
        sys.exit("[render_video] --target-minutes must be positive")
    if args.duration_tolerance_seconds < 0:
        sys.exit("[render_video] --duration-tolerance-seconds must be non-negative")
    if args.require_animations and args.frames_only:
        sys.exit("[render_video] --require-animations cannot be combined with --frames-only")

    audio_dir = Path(args.audio_dir).resolve() if args.audio_dir else project_path / "audio"
    script_json = Path(args.script_json).resolve() if args.script_json else None
    out_path = Path(args.out).resolve() if args.out else project_path / "exports" / f"{pptx_path.stem}.mp4"
    visual_cues_path = Path(args.visual_cues).resolve() if args.visual_cues else None
    animation_manifest_path = (
        Path(args.animation_manifest).resolve() if args.animation_manifest else None
    )
    animation_metadata = animation_manifest_metadata(animation_manifest_path)
    animation_source = (
        animation_metadata["source_kind"]
        if args.animation_source == "auto"
        else args.animation_source
    )
    animation_report_path = (
        Path(args.animation_report_out).resolve() if args.animation_report_out else None
    )
    if args.require_animations and animation_manifest_path is None:
        sys.exit("[render_video] --require-animations requires --animation-manifest")
    if animation_report_path is not None and animation_manifest_path is None:
        sys.exit("[render_video] --animation-report-out requires --animation-manifest")
    if args.animation_source != "auto" and animation_manifest_path is None:
        sys.exit("[render_video] --animation-source requires --animation-manifest")
    if animation_manifest_path is not None and args.animation_source != "auto":
        declared_source = animation_metadata["source_kind"]
        if declared_source != animation_source:
            sys.exit(
                f"[render_video] --animation-source {animation_source!r} conflicts with "
                f"manifest source_kind {declared_source!r}"
            )
    if animation_source == "pptx" and args.frame_source == "svg":
        sys.exit(
            "[render_video] editable PPTX animations cannot use --frame-source svg; "
            "the current PPTX must supply both static and animated pixels"
        )
    explicit_svg_dir = Path(args.svg_dir).resolve() if args.svg_dir else None
    frames_out = Path(args.frames_out).resolve() if args.frames_out else None
    browser_executable = Path(args.browser_executable).expanduser() if args.browser_executable else None
    if browser_executable is not None and not browser_executable.is_file():
        sys.exit(f"[render_video] --browser-executable not found: {browser_executable}")

    width, height = RESOLUTIONS[args.resolution]
    dpi = args.dpi or {"720p": 110, "1080p": 150, "1440p": 200, "4k": 300}[args.resolution]

    ffmpeg, ffprobe = find_ffmpeg_pair()

    # Working area
    work_root = project_path / ".video_work"
    if work_root.exists() and not args.keep_temp:
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    png_dir = work_root / "frames"
    effective_frame_source = "pptx" if animation_source == "pptx" else args.frame_source
    svg_dir = discover_svg_dir(project_path, explicit_svg_dir, effective_frame_source)
    use_svg = effective_frame_source in {"auto", "svg"} and svg_dir is not None
    frame_source_used = "svg" if use_svg else "pptx"

    svgs: list[Path] = []
    libreoffice: str | None = None
    pdftoppm: str | None = None
    if use_svg:
        svgs = collect_svgs(svg_dir)
        if svg_dir.name == "svg_output":
            print(
                "[render_video] WARNING: using svg_output; prefer svg_final because "
                "svg_output may still contain unexpanded icon placeholders."
            )
        print(f"[render_video] Stage A: SVG → PNG  ({width}x{height}) from {svg_dir}")
        frames = render_svg_frames(
            svgs,
            png_dir,
            project_path=project_path,
            width=width,
            height=height,
            browser_executable=str(browser_executable) if browser_executable else None,
        )
    else:
        print(f"[render_video] Stage A: PPTX → PDF → PNG  (DPI={dpi}, {width}x{height})")
        pdf_dir = work_root / "pdf"
        libreoffice = find_libreoffice()
        pdftoppm = find_pdftoppm()
        pdf = pptx_to_pdf(pptx_path, pdf_dir, libreoffice)
        frames = pdf_to_pngs(pdf, png_dir, dpi, pdftoppm)

    if frames_out is not None:
        frames = copy_frames(frames, frames_out)
        png_dir = frames_out
    print(f"[render_video]   {len(frames)} frame(s) under {png_dir}")

    if args.frames_only:
        print(f"[render_video] --frames-only: stopping. Frames: {png_dir}")
        return 0

    print(f"[render_video] Stage B: pair frames with {audio_dir}/*.mp3")
    audio_files = collect_audio(audio_dir, script_json=script_json, project_path=project_path)
    pairs = pair_slides(frames, audio_files, ffprobe, ffmpeg)
    total_audio = sum(p.duration for p in pairs)
    print(f"[render_video]   {len(pairs)} slide(s), audio total {total_audio:.1f}s")
    animation_map = load_animation_manifest(
        animation_manifest_path,
        pairs,
        pad_tail=args.pad_tail,
    )
    if animation_map and animation_source == "svg" and not use_svg:
        sys.exit(
            "[render_video] Author Notes animations require SVG frame rendering; "
            "pass --frame-source svg and --svg-dir."
        )
    if animation_map and animation_source == "pptx":
        expected_sha = animation_metadata.get("source_sha256") or ""
        actual_sha = file_sha256(pptx_path)
        if not expected_sha:
            sys.exit(
                "[render_video] editable PPTX animation manifest is missing source_sha256"
            )
        if expected_sha != actual_sha:
            sys.exit(
                "[render_video] editable PPTX changed after the animation manifest was built; "
                "rerun build_animation_manifest.py --pptx before rendering"
            )
    if args.audio_only_check:
        print("[render_video] --audio-only-check passed.")
        return 0

    visual_cue_map = load_visual_cues(
        visual_cues_path,
        pairs,
        attention_mode=args.attention_mode,
        highlight_style=args.highlight_style,
        pad_tail=args.pad_tail,
        allow_missing_visual_cues=args.allow_missing_visual_cues,
    )

    animation_assets: dict[int, AnimationSlideAssets] = {}
    if animation_map:
        print(
            f"[render_video] Stage B2: rasterize {sum(len(s.effects) for s in animation_map.values())} "
            "Author Notes animation layer(s)"
        )
        if animation_source == "pptx":
            if libreoffice is None:
                libreoffice = find_libreoffice()
            if pdftoppm is None:
                pdftoppm = find_pdftoppm()
            animation_assets = render_pptx_animation_assets(
                pptx_path,
                animation_map,
                work_root / "animation_layers",
                width=width,
                height=height,
                libreoffice=libreoffice,
                pdftoppm=pdftoppm,
            )
        else:
            animation_assets = render_svg_animation_assets(
                svgs,
                animation_map,
                work_root / "animation_layers",
                project_path=project_path,
                width=width,
                height=height,
                browser_executable=str(browser_executable) if browser_executable else None,
            )

    print(f"[render_video] Stage C: encode {len(pairs)} segment(s) and concat")
    seg_dir = work_root / "segments"
    seg_dir.mkdir(exist_ok=True)
    segments: list[Path] = []
    for pair in pairs:
        seg_path = seg_dir / f"seg_{pair.index:04d}.mp4"
        animation_count = len(animation_assets.get(pair.index).layers) if pair.index in animation_assets else 0
        print(
            f"[render_video]   segment {pair.index}/{len(pairs)}: {pair.audio.stem} "
            f"({animation_count} animation effect(s))",
            flush=True,
        )
        encode_segment(pair, seg_path,
                       width=width, height=height, fps=args.fps,
                       pad_tail=args.pad_tail, ffmpeg=ffmpeg,
                       visual_cues=visual_cue_map.get(pair.index),
                       animation_assets=animation_assets.get(pair.index))
        segments.append(seg_path)

    concat_segments(segments, out_path, ffmpeg,
                    start_pad=args.start_pad, fps=args.fps,
                    width=width, height=height)

    duration = verify_output(out_path, ffprobe, ffmpeg)
    expected = total_audio + args.start_pad + args.pad_tail * len(pairs)
    drift = duration - expected

    print()
    print(f"[render_video] DONE → {out_path}")
    print(f"  duration: {duration:.1f}s  (expected ≈ {expected:.1f}s, drift {drift:+.1f}s)")
    print(f"  slides:   {len(pairs)}  resolution: {width}x{height}@{args.fps}fps")
    print(f"  frames:   {frame_source_used} → {png_dir}")

    if animation_map:
        if animation_report_path is None:
            animation_report_path = out_path.with_name(
                f"{out_path.stem}_animation_report.json"
            )
        animation_report = write_animation_render_report(
            animation_report_path,
            manifest_path=animation_manifest_path,
            out_path=out_path,
            pairs=pairs,
            animation_map=animation_map,
            animation_assets=animation_assets,
            source_kind=animation_source,
            source_path=pptx_path if animation_source == "pptx" else svg_dir,
            source_sha256=(
                file_sha256(pptx_path)
                if animation_source == "pptx"
                else animation_metadata.get("source_sha256", "")
            ),
            start_pad=args.start_pad,
            pad_tail=args.pad_tail,
            fps=args.fps,
            width=width,
            height=height,
        )
        print(
            f"  animations: {animation_report['effect_count']} effect(s) → "
            f"{animation_report_path}"
        )

    report_path: Path | None = None
    if args.duration_report_out:
        report_path = Path(args.duration_report_out).resolve()
    elif args.target_minutes is not None:
        report_path = out_path.with_name(f"{out_path.stem}_duration_report.json")

    if report_path is not None:
        report = write_duration_report(
            report_path,
            out_path=out_path,
            pairs=pairs,
            frame_source=frame_source_used,
            frames_dir=png_dir,
            svg_dir=svg_dir if use_svg else None,
            actual_seconds=duration,
            expected_seconds=expected,
            target_minutes=args.target_minutes,
            tolerance_seconds=args.duration_tolerance_seconds,
            start_pad=args.start_pad,
            pad_tail=args.pad_tail,
            fps=args.fps,
            width=width,
            height=height,
            visual_cue_map=visual_cue_map,
        )
        if args.target_minutes is not None:
            print(
                f"  target:   {args.target_minutes:.2f} min "
                f"({report['status']}, delta {report['target_delta_seconds']:+.1f}s)"
            )
        print(f"  duration report: {report_path}")

    if not args.keep_temp:
        shutil.rmtree(work_root, ignore_errors=True)
    else:
        print(f"  work dir kept at: {work_root}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
