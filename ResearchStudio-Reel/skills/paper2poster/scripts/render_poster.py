#!/usr/bin/env python3
"""render_preview - render a poster HTML to print-ready PDF + thumbnail.

Canvas-agnostic: reads ``@page { size: <W> <H> }`` from the input HTML
or accepts ``--canvas '<W>x<H>in'`` / ``--canvas 'A0 portrait'`` as
override. Print-emulates Chromium so MathJax typesets against the
``@media print`` layout from the start.

This is the SOFT path (vs the HARD ``measure`` gate): a MathJax
typeset timeout or a missing ``<mjx-container>`` warns and continues
— users would rather see raw ``$…$`` on the rendered PDF than a
silent abort.

Outputs:
    <stem>.pdf   exact-size PDF
    <stem>.png   scaled thumbnail (default 0.35×)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

# Make `utils` importable when run directly.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from utils import canvas as _canvas  # noqa: E402
from utils import render as _render  # noqa: E402
from utils.cli_common import eprint as _eprint, import_playwright  # noqa: E402
from utils.font_fidelity import (  # noqa: E402
    freeze_system_font_webfont,
    managed_font_asset_names,
)
from utils.textutil import ascii_safe  # noqa: E402


_PUBLIC_ARTIFACT_MODE = 0o644
_FONT_ROLLBACK_PREFIX = ".poster-font-rollback."
_EXPAND_GAP_TOLERANCE_PX = 0.1
_EXPAND_GEOMETRY_TOLERANCE_PX = 1.0
_EXPAND_MEDIA_REL_TOLERANCE = 0.005
_EXPAND_FIG_MIN_RATIO = 0.90
_EXPAND_FIG_MAX_RATIO = 1.01
_LAYOUT_TIMER_GUARD_ID = "poster-layout-timer-guard"
_LEGACY_FIGURE_FLOOR_ENV = "POSTER_LEGACY_FIGURE_FLOOR_POLICY"
_LEGACY_FIGURE_FLOOR_TOKEN = "preserve-immutable-source-v1"
_GEOMETRY_SNAPSHOT_ID = "poster-geometry-snapshot"
_GEOMETRY_FROZEN_ATTR = "data-poster-geometry-frozen"
_GEOMETRY_FIT_GUARD = """
    /* paper2poster:frozen-geometry-fit-guard */
    if (document.documentElement.getAttribute('data-poster-geometry-frozen') === '1') return;"""
_GEOMETRY_FIT_ALL_GUARD = """
    /* paper2poster:frozen-geometry-fit-all-guard */
    if (document.documentElement.getAttribute('data-poster-geometry-frozen') === '1') return;"""


def _pdf_content_scale(
    canvas_in: tuple[float, float], viewport_px: tuple[int, int]
) -> float:
    """Keep a rounded Chromium viewport inside the exact physical page.

    ``viewport_for`` must return integer CSS pixels, while a decimal-inch
    canvas such as Portrait A0 (33.1 x 46.8 in) maps to fractional pixels at
    96 ppi.  When rounding goes up, printing the integer-sized document at
    scale 1 can spill a fraction of a pixel onto a blank second PDF page.
    Scale only by that rounding delta; integer canvases such as 60 x 36 in
    remain exactly 1.0.
    """
    w_in, h_in = canvas_in
    w_px, h_px = viewport_px
    if w_px <= 0 or h_px <= 0:
        return 1.0
    return min(1.0, (w_in * 96.0) / w_px, (h_in * 96.0) / h_px)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0]
    )
    p.add_argument("html", help="poster HTML file")
    p.add_argument(
        "--pdf", default=None,
        help="output PDF path (default: <stem>.pdf)",
    )
    p.add_argument(
        "--png", default=None,
        help="output PNG thumbnail path (default: <stem>.png)",
    )
    p.add_argument(
        "--thumb-scale", type=float, default=0.35,
        help="thumbnail scale factor (default 0.35)",
    )
    p.add_argument(
        "--mathjax-timeout-ms", type=int, default=15000,
        help="timeout for MathJax typesetting (default 15000); "
             "render is the SOFT path; timeout warns, not fails",
    )
    p.add_argument(
        "--canvas", type=_canvas.parse_canvas_arg, default=None,
        help="override canvas (e.g. '60x36in' / 'A0 portrait'); "
             "by default we parse @page from the HTML",
    )
    return p


def _copy_asset_atomic(
    source: Path,
    target: Path,
    *,
    mode: int | None = None,
) -> None:
    """Copy one renderer-managed asset without exposing partial bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".asset-next",
    )
    os.close(descriptor)
    temporary = Path(raw)
    try:
        shutil.copy2(source, temporary)
        if mode is not None:
            temporary.chmod(mode)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _renderer_font_asset_names(
    fonts_dir: Path | None = None,
) -> frozenset[str]:
    """Return the closed set of font files a render may add or replace."""
    skill_fonts = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    bundled = (
        {path.name for path in skill_fonts.glob("*.woff2")}
        if skill_fonts.is_dir()
        else set()
    )
    return frozenset(bundled | set(managed_font_asset_names(fonts_dir)))


class _FontAssetJournal:
    """Restore renderer-managed ``assets/fonts`` files if a render fails.

    The staged HTML remains adjacent to the deliverable so every existing
    relative figure/logo/QR URL resolves exactly as it will after promotion.
    That means font preparation also targets the adjacent live ``assets``
    directory.  Each individual write is atomic, and this journal extends the
    HTML/PDF/PNG rollback contract to the complete set of font dependencies.
    """

    def __init__(self, html_path: Path):
        self.fonts_dir = html_path.parent / "assets" / "fonts"
        self.fonts_dir_existed = self.fonts_dir.is_dir()
        if self.fonts_dir.is_symlink() or (
            self.fonts_dir.exists() and not self.fonts_dir.is_dir()
        ):
            raise RuntimeError(
                f"font asset path must be a real directory: {self.fonts_dir}"
            )
        self.backup_dir = Path(
            tempfile.mkdtemp(
                dir=html_path.parent,
                prefix=_FONT_ROLLBACK_PREFIX,
            )
        )
        self.backup_dir.chmod(0o700)
        self.originals: dict[str, Path | None] = {}
        self.closed = False
        try:
            for name in sorted(_renderer_font_asset_names(self.fonts_dir)):
                target = self.fonts_dir / name
                if target.is_symlink() or (
                    target.exists() and not target.is_file()
                ):
                    raise RuntimeError(
                        f"font asset target must be a regular file: {target}"
                    )
                if target.is_file():
                    saved = self.backup_dir / name
                    shutil.copy2(target, saved)
                    self.originals[name] = saved
                else:
                    self.originals[name] = None
        except BaseException:
            shutil.rmtree(self.backup_dir, ignore_errors=True)
            raise

    def rollback(self) -> None:
        if self.closed:
            return
        errors: list[str] = []
        try:
            # Content-addressed poster subsets are named only after the source
            # face and glyph repertoire have been resolved inside the render.
            # Discover them again here so a failed transaction removes every
            # identity asset that did not exist when this journal was opened.
            for name in managed_font_asset_names(self.fonts_dir):
                self.originals.setdefault(name, None)
            for name, saved in self.originals.items():
                target = self.fonts_dir / name
                try:
                    if saved is None:
                        if target.is_symlink() or target.is_file():
                            target.unlink()
                        elif target.exists():
                            raise RuntimeError(
                                "new font asset became a non-file target"
                            )
                    else:
                        _copy_asset_atomic(saved, target)
                except Exception as exc:  # keep restoring the remaining set
                    errors.append(f"{target}: {exc}")
            if (
                not self.fonts_dir_existed
                and self.fonts_dir.is_dir()
                and not any(self.fonts_dir.iterdir())
            ):
                self.fonts_dir.rmdir()
                assets_dir = self.fonts_dir.parent
                if assets_dir.is_dir() and not any(assets_dir.iterdir()):
                    assets_dir.rmdir()
        finally:
            shutil.rmtree(self.backup_dir, ignore_errors=True)
            self.closed = True
        if errors:
            raise RuntimeError(
                "font asset rollback was incomplete: " + "; ".join(errors)
            )

    def commit(self) -> None:
        if self.closed:
            return
        try:
            shutil.rmtree(self.backup_dir)
        except OSError as exc:
            _eprint(
                f"[render_preview] WARN: could not remove font rollback "
                f"journal {ascii_safe(self.backup_dir)}: {ascii_safe(exc)}"
            )
        self.closed = True


def _sync_bundled_fonts(html_path: Path) -> None:
    """Mirror the skill's bundled Inter webfonts into <html_dir>/assets/fonts/
    so the @font-face URLs in the template (relative `assets/fonts/Inter-*.woff2`)
    resolve when playwright loads the page. Idempotent — only copies missing
    or stale files. Silent no-op if the skill's fonts/ subdir doesn't exist
    (e.g. user editing a template that doesn't use bundled webfonts).

    Why mirror instead of symlink: the deliverable folder needs to be
    self-contained so a reviewer can zip + share it; a symlink into the
    skill assets would break once the folder leaves this machine.
    """
    import shutil
    skill_fonts = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    if not skill_fonts.is_dir():
        return
    out_fonts = html_path.parent / "assets" / "fonts"
    out_fonts.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in skill_fonts.glob("*.woff2"):
        dst = out_fonts / src.name
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            _copy_asset_atomic(src, dst, mode=_PUBLIC_ARTIFACT_MODE)
            copied += 1
    if copied:
        _eprint(f"[render_preview] mirrored {copied} font file(s) -> "
                f"{out_fonts.relative_to(html_path.parent)}/")


def _strip_derived_style_block(text: str, style_id: str) -> tuple[str, int]:
    """Remove a renderer-owned style block from HTML text.

    Expand and scan suppression are derived from the current DOM and current
    environment knobs.  Keeping an older block in the source while measuring a
    rerender makes that stale output influence its own replacement (and makes a
    ``0`` override unable to disable it), so both blocks are stripped before
    the first browser navigation and rebuilt from the fresh layout.
    """
    import re

    pattern = re.compile(
        rf'\s*<style\b(?=[^>]*\bid\s*=\s*["\']{re.escape(style_id)}["\'])'
        rf'[^>]*>.*?</style>\s*',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return pattern.subn("\n", text)


def _strip_derived_render_styles(html_path: Path) -> set[str]:
    """Strip stale expand/scan renderer output before a fresh measurement."""
    text = html_path.read_text(encoding="utf-8")
    removed: set[str] = set()
    for style_id in ("poster-expand-baked", "poster-scan-suppress"):
        text, count = _strip_derived_style_block(text, style_id)
        if count:
            removed.add(style_id)
    if removed:
        html_path.write_text(text, encoding="utf-8")
    return removed


def _append_style_at_end(text: str, block: str) -> str:
    """Append a durable style after every existing author style.

    The final ``</body>`` is the stable insertion point used by the generated
    posters.  Falling back to EOF keeps malformed/minimal fixtures usable.
    """
    import re

    closes = list(re.finditer(r"</body\s*>", text, flags=re.IGNORECASE))
    if not closes:
        return text.rstrip() + "\n" + block + "\n"
    at = closes[-1].start()
    return text[:at].rstrip() + "\n" + block + "\n" + text[at:]


def _strip_durable_geometry_snapshot(html_path: Path) -> bool:
    """Remove the previous renderer-owned geometry freeze before rerendering.

    A completed render is intentionally frozen for cold opens.  A later,
    explicit rerender must first recover the authored/natural document so its
    fitters can recompute against current content and assets.  The snapshot is
    one script, one root marker, and two sentinel-guard snippets, which makes
    this removal idempotent and narrowly scoped.
    """
    import re

    original = html_path.read_text(encoding="utf-8")
    text = original
    snapshot_pattern = re.compile(
        rf'\s*<script\b(?=[^>]*\bid\s*=\s*["\']'
        rf'{re.escape(_GEOMETRY_SNAPSHOT_ID)}["\'])[^>]*>.*?</script>\s*',
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = snapshot_pattern.sub("\n", text)
    text = text.replace(_GEOMETRY_FIT_GUARD, "")
    text = text.replace(_GEOMETRY_FIT_ALL_GUARD, "")

    root_pattern = re.compile(r"<html\b[^>]*>", flags=re.IGNORECASE)
    marker_pattern = re.compile(
        rf"\s+{re.escape(_GEOMETRY_FROZEN_ATTR)}"
        r"(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?",
        flags=re.IGNORECASE,
    )
    match = root_pattern.search(text)
    if match:
        cleaned = marker_pattern.sub("", match.group(0))
        text = text[:match.start()] + cleaned + text[match.end():]

    if text == original:
        return False
    html_path.write_text(text, encoding="utf-8")
    return True


_GEOMETRY_SNAPSHOT_JS = r"""
() => {
  const specs = [
    {
      name:'figures',
      selector:'.section[data-section] figure, .section[data-section] .figure',
      attributes:['style', 'class'],
    },
    {
      name:'images',
      selector:'.section[data-section] img',
      attributes:['style', 'class'],
    },
    {
      name:'methodBodies',
      selector:'.method-body',
      attributes:['style', 'class'],
    },
    {
      name:'sections',
      selector:'.section[data-section]',
      attributes:['style'],
    },
  ];
  return {
    version:1,
    viewport:{width:window.innerWidth, height:window.innerHeight},
    groups:specs.map(spec => ({
      name:spec.name,
      selector:spec.selector,
      attributes:spec.attributes,
      nodes:Array.from(document.querySelectorAll(spec.selector)).map(node => {
        const attributes = {};
        spec.attributes.forEach(name => {
          attributes[name] = node.hasAttribute(name)
            ? node.getAttribute(name) : null;
        });
        return attributes;
      }),
    })),
  };
}
"""


def _capture_durable_geometry_snapshot(page) -> dict:
    """Serialize the final live geometry mutations that affect poster media."""
    snapshot = page.evaluate(_GEOMETRY_SNAPSHOT_JS)
    if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
        raise RuntimeError("geometry snapshot returned malformed data")
    groups = snapshot.get("groups")
    if not isinstance(groups, list):
        raise RuntimeError("geometry snapshot omitted its node groups")
    for group in groups:
        if (not isinstance(group, dict)
                or not isinstance(group.get("selector"), str)
                or not isinstance(group.get("attributes"), list)
                or not isinstance(group.get("nodes"), list)):
            raise RuntimeError("geometry snapshot contains a malformed group")
    return snapshot


def _persist_durable_geometry_snapshot(
    html_path: Path,
    snapshot: dict,
    *,
    timeout_ms: int = 15_000,
) -> dict[str, int]:
    """Bake the warm DOM's figure geometry and freeze its fitters on reload.

    The saved attributes are installed by a one-shot script at the end of
    ``body``.  It temporarily disarms the static frozen marker so the authored
    load fitter reproduces the same warm-render glyph/paint sequence once,
    reasserts the accepted attributes two animation frames later, and only then
    re-arms the ``fit``/``fitAll`` guards and publishes its readiness marker.
    """
    import re

    # Defensive idempotence for direct helper use; the normal render path also
    # strips the prior snapshot before its first natural measurement.
    _strip_durable_geometry_snapshot(html_path)
    original = html_path.read_text(encoding="utf-8")
    text = original

    fit_pattern = re.compile(
        r"(function\s+fit\s*\(\s*img\s*\)\s*\{)",
        flags=re.IGNORECASE,
    )
    fit_all_pattern = re.compile(
        r"(function\s+fitAll\s*\(\s*\)\s*\{)",
        flags=re.IGNORECASE,
    )
    text, fit_count = fit_pattern.subn(
        lambda match: match.group(1) + _GEOMETRY_FIT_GUARD,
        text,
    )
    text, fit_all_count = fit_all_pattern.subn(
        lambda match: match.group(1) + _GEOMETRY_FIT_ALL_GUARD,
        text,
    )

    root_pattern = re.compile(r"<html\b[^>]*>", flags=re.IGNORECASE)
    root_match = root_pattern.search(text)
    if not root_match:
        raise RuntimeError("cannot freeze geometry without an <html> root")
    root_tag = root_match.group(0)
    frozen_root = (
        root_tag[:-1].rstrip()
        + f' {_GEOMETRY_FROZEN_ATTR}="1">'
    )
    text = text[:root_match.start()] + frozen_root + text[root_match.end():]

    timeout_ms = max(1_000, int(timeout_ms))
    # Keep the DOMContentLoaded and FontFaceSet fallbacks comfortably inside
    # the renderer's outer readiness wait.  Normal pages still take the
    # window.load path; these bounds matter only when a subresource never
    # finishes and load therefore never fires.
    phase_wait_ms = max(100, min(2_000, timeout_ms // 4))
    compatibility_wait_ms = min(500, phase_wait_ms)

    payload = json.dumps(
        snapshot,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    # A style/class attribute can legally contain ``</script>``.  Keep the
    # embedded JSON from ever terminating its owner script early.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    install_script = (
        f'<script id="{_GEOMETRY_SNAPSHOT_ID}">\n'
        "(() => {\n"
        "  const root = document.documentElement;\n"
        f"  const snapshot = {payload};\n"
        "  let finished = false;\n"
        "  let started = false;\n"
        "  let observer = null;\n"
        "  let restoringAttributes = false;\n"
        "  const protectedNodes = new Map();\n"
        f"  const phaseWaitMs = {phase_wait_ms};\n"
        f"  const compatibilityWaitMs = {compatibility_wait_ms};\n"
        "  const restore = () => {\n"
        "    if (finished) return;\n"
        "    finished = true;\n"
        "    try {\n"
        "      for (const group of snapshot.groups) {\n"
        "        const nodes = Array.from(document.querySelectorAll(group.selector));\n"
        "        if (nodes.length !== group.nodes.length)\n"
        "          throw new Error(group.name + ': expected ' + group.nodes.length\n"
        "            + ' nodes, found ' + nodes.length);\n"
        "        nodes.forEach((node, index) => {\n"
        "          const attributes = group.nodes[index];\n"
        "          const protectedAttributes = protectedNodes.get(node) || {};\n"
        "          group.attributes.forEach(name => {\n"
        "            const value = attributes[name];\n"
        "            protectedAttributes[name] = value;\n"
        "            if (value === null) node.removeAttribute(name);\n"
        "            else node.setAttribute(name, value);\n"
        "          });\n"
        "          protectedNodes.set(node, protectedAttributes);\n"
        "        });\n"
        "      }\n"
        f"      root.setAttribute('{_GEOMETRY_FROZEN_ATTR}', '1');\n"
        "      if (observer) observer.disconnect();\n"
        "      observer = new MutationObserver(records => {\n"
        f"        if (root.getAttribute('{_GEOMETRY_FROZEN_ATTR}') !== '1'\n"
        "            || restoringAttributes) return;\n"
        "        restoringAttributes = true;\n"
        "        try {\n"
        "          records.forEach(record => {\n"
        "            const expected = protectedNodes.get(record.target);\n"
        "            const name = record.attributeName;\n"
        "            if (!expected || !Object.prototype.hasOwnProperty.call(\n"
        "                expected, name)) return;\n"
        "            const value = expected[name];\n"
        "            const actual = record.target.hasAttribute(name)\n"
        "              ? record.target.getAttribute(name) : null;\n"
        "            if (actual === value) return;\n"
        "            if (value === null) record.target.removeAttribute(name);\n"
        "            else record.target.setAttribute(name, value);\n"
        "          });\n"
        "        } finally { restoringAttributes = false; }\n"
        "      });\n"
        "      observer.observe(root, {subtree:true, attributes:true,\n"
        "        attributeFilter:['style', 'class']});\n"
        "      root.dataset.posterGeometrySnapshotApplied = '1';\n"
        "      delete root.dataset.posterGeometrySnapshotError;\n"
        "    } catch (error) {\n"
        f"      root.setAttribute('{_GEOMETRY_FROZEN_ATTR}', '1');\n"
        "      delete root.dataset.posterGeometrySnapshotApplied;\n"
        "      root.dataset.posterGeometrySnapshotError = String(error);\n"
        "    }\n"
        "  };\n"
        "  const afterWarmFit = async () => {\n"
        "    if (started) return;\n"
        "    started = true;\n"
        "    // FontFaceSet.ready can resolve after window.load.  Give the\n"
        "    // authored fitter the same post-font settle window as the warm\n"
        "    // renderer before reasserting its accepted inline geometry. A\n"
        "    // broken font resource must not hold the durable marker forever.\n"
        "    try {\n"
        "      if (document.fonts && document.fonts.ready)\n"
        "        await Promise.race([\n"
        "          Promise.resolve(document.fonts.ready).catch(() => {}),\n"
        "          new Promise(resolve => setTimeout(resolve, phaseWaitMs)),\n"
        "        ]);\n"
        "    } catch (_) {}\n"
        "    await new Promise(resolve =>\n"
        "      setTimeout(resolve, compatibilityWaitMs));\n"
        "    requestAnimationFrame(() => requestAnimationFrame(restore));\n"
        "  };\n"
        "  const queueDomFallback = () => {\n"
        "    // DOMContentLoaded proves the authored DOM exists even when one\n"
        "    // subresource prevents window.load forever. Preserve the normal\n"
        "    // load ordering for one bounded phase, then restore exactly once.\n"
        "    setTimeout(afterWarmFit, phaseWaitMs);\n"
        "  };\n"
        "  // The static marker documents the delivered frozen state, but a\n"
        "  // cold browser must reproduce the original warm sequence once.\n"
        "  // Arm the authored fitter now; its earlier window.load listener\n"
        "  // runs first. After fonts settle, a bounded compatibility window and\n"
        "  // two animation frames later, reassert the exact accepted styles,\n"
        "  // freeze future callbacks, and publish readiness.\n"
        f"  root.removeAttribute('{_GEOMETRY_FROZEN_ATTR}');\n"
        "  delete root.dataset.posterGeometrySnapshotApplied;\n"
        "  delete root.dataset.posterGeometrySnapshotError;\n"
        "  if (document.readyState === 'complete') afterWarmFit();\n"
        "  else {\n"
        "    window.addEventListener('load', afterWarmFit, {once:true});\n"
        "    if (document.readyState === 'loading')\n"
        "      document.addEventListener(\n"
        "        'DOMContentLoaded', queueDomFallback, {once:true});\n"
        "    else queueDomFallback();\n"
        "  }\n"
        "})();\n"
        "</script>"
    )
    text = _append_style_at_end(text, install_script)
    html_path.write_text(text, encoding="utf-8")
    return {"fit": fit_count, "fitAll": fit_all_count}


def _validate_installed_geometry_snapshot(page, snapshot: dict) -> list[str]:
    """Verify the cold DOM applied every persisted attribute exactly."""
    result = page.evaluate(
        """snapshot => {
          const root = document.documentElement;
          const failures = [];
          if (root.getAttribute('data-poster-geometry-frozen') !== '1')
            failures.push('frozen root marker is absent');
          if (root.dataset.posterGeometrySnapshotApplied !== '1')
            failures.push('snapshot installer did not complete');
          if (root.dataset.posterGeometrySnapshotError)
            failures.push('snapshot installer: '
              + root.dataset.posterGeometrySnapshotError);
          for (const group of snapshot.groups || []) {
            const nodes = Array.from(document.querySelectorAll(group.selector));
            if (nodes.length !== group.nodes.length) {
              failures.push(group.name + ' count changed ('
                + group.nodes.length + ' -> ' + nodes.length + ')');
              continue;
            }
            nodes.forEach((node, index) => {
              for (const name of group.attributes) {
                const expected = group.nodes[index][name];
                const actual = node.hasAttribute(name)
                  ? node.getAttribute(name) : null;
                if (actual !== expected)
                  failures.push(group.name + '[' + index + '] '
                    + name + ' changed');
              }
            });
          }
          return failures.slice(0, 80);
        }""",
        snapshot,
    )
    if not isinstance(result, list):
        return ["geometry snapshot validator returned malformed data"]
    return [str(item) for item in result]


def _wait_for_installed_geometry_snapshot(
    page,
    *,
    timeout_ms: int,
) -> bool:
    """Wait for the cold page's warm-fit-then-restore one-shot to finish."""
    try:
        page.wait_for_function(
            """() => {
              const root = document.documentElement;
              return root.dataset.posterGeometrySnapshotApplied === '1'
                || !!root.dataset.posterGeometrySnapshotError;
            }""",
            timeout=timeout_ms,
        )
        state = page.evaluate(
            """() => ({
              applied:document.documentElement.dataset
                .posterGeometrySnapshotApplied || '',
              error:document.documentElement.dataset
                .posterGeometrySnapshotError || '',
              frozen:document.documentElement.getAttribute(
                'data-poster-geometry-frozen') || '',
            })"""
        )
    except Exception as exc:
        _eprint(
            "[render_preview] WARN: geometry snapshot readiness wait failed: "
            f"{ascii_safe(exc)}"
        )
        return False
    if (not isinstance(state, dict)
            or state.get("applied") != "1"
            or state.get("frozen") != "1"
            or state.get("error")):
        _eprint(
            "[render_preview] WARN: geometry snapshot did not publish a clean "
            f"ready state: {ascii_safe(state)}"
        )
        return False
    return True


def _decode_browser_png(payload: bytes) -> tuple[int, int, int, bytes]:
    """Decode an 8-bit, non-interlaced browser screenshot without Pillow.

    Chromium's PNG screenshots use the ordinary non-interlaced RGB/RGBA PNG
    subset.  Keeping this tiny decoder in the renderer makes the mandatory
    pixel gate self-contained instead of adding an optional image dependency.
    The returned bytes are fully unfiltered native pixels; the comparison
    helper below interprets them as RGBA.
    """
    signature = b"\x89PNG\r\n\x1a\n"
    if not isinstance(payload, (bytes, bytearray)) or not payload.startswith(signature):
        raise RuntimeError("screenshot is not a PNG")
    offset = len(signature)
    width = height = bit_depth = color_type = None
    compression = png_filter = interlace = None
    idat: list[bytes] = []
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        chunk_type = bytes(payload[offset + 4:offset + 8])
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise RuntimeError("PNG chunk extends beyond screenshot bytes")
        data = bytes(payload[data_start:data_end])
        expected_crc = struct.unpack(">I", payload[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise RuntimeError(f"PNG {chunk_type!r} checksum mismatch")
        if chunk_type == b"IHDR":
            if len(data) != 13:
                raise RuntimeError("PNG IHDR has the wrong size")
            (width, height, bit_depth, color_type, compression,
             png_filter, interlace) = struct.unpack(">IIBBBBB", data)
        elif chunk_type == b"IDAT":
            idat.append(data)
        elif chunk_type == b"IEND":
            break
        offset = crc_end

    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if (not width or not height or bit_depth != 8 or channels is None
            or compression != 0 or png_filter != 0 or interlace != 0):
        raise RuntimeError(
            "unsupported browser PNG encoding "
            f"({width}x{height}, depth={bit_depth}, color={color_type}, "
            f"compression={compression}, filter={png_filter}, "
            f"interlace={interlace})"
        )
    compressed = b"".join(idat)
    filtered = zlib.decompress(compressed)
    stride = int(width) * channels
    expected_size = int(height) * (stride + 1)
    if len(filtered) != expected_size:
        raise RuntimeError(
            f"decoded PNG scanline size changed ({len(filtered)} != {expected_size})"
        )

    pixels = bytearray(int(height) * stride)
    previous = bytearray(stride)

    def paeth(left: int, above: int, upper_left: int) -> int:
        estimate = left + above - upper_left
        d_left = abs(estimate - left)
        d_above = abs(estimate - above)
        d_upper_left = abs(estimate - upper_left)
        if d_left <= d_above and d_left <= d_upper_left:
            return left
        if d_above <= d_upper_left:
            return above
        return upper_left

    for row_index in range(int(height)):
        start = row_index * (stride + 1)
        filter_type = filtered[start]
        source = filtered[start + 1:start + 1 + stride]
        current = bytearray(stride)
        if filter_type == 0:
            current[:] = source
        elif filter_type in (1, 2, 3, 4):
            for index, encoded in enumerate(source):
                left = current[index - channels] if index >= channels else 0
                above = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = above
                elif filter_type == 3:
                    predictor = (left + above) // 2
                else:
                    predictor = paeth(left, above, upper_left)
                current[index] = (encoded + predictor) & 0xFF
        else:
            raise RuntimeError(f"unsupported PNG row filter {filter_type}")
        pixel_start = row_index * stride
        pixels[pixel_start:pixel_start + stride] = current
        previous = current
    return int(width), int(height), int(color_type), bytes(pixels)


def _compare_decoded_rgba(
    reference_png: bytes,
    candidate_png: bytes,
) -> tuple[bool, str]:
    """Require two PNG screenshots to have zero differing decoded RGBA pixels."""
    # Chromium's screenshot encoder is deterministic.  Byte-identical valid
    # PNGs necessarily decode to identical RGBA and are a strictly stronger
    # equality proof; avoid two expensive 20-megapixel unfilter passes in this
    # overwhelmingly common success case.  Differently encoded PNGs still go
    # through the complete decoder below (covered by the compression-level
    # self-test used for this renderer).
    if reference_png == candidate_png:
        signature = b"\x89PNG\r\n\x1a\n"
        if (len(reference_png) < 33
                or not reference_png.startswith(signature)
                or reference_png[12:16] != b"IHDR"):
            raise RuntimeError("byte-identical screenshots are not valid PNGs")
        ref_w, ref_h = struct.unpack(">II", reference_png[16:24])
        return True, f"{ref_w}x{ref_h}, 0 differing decoded RGBA pixels"

    ref_w, ref_h, ref_type, ref_pixels = _decode_browser_png(reference_png)
    cur_w, cur_h, cur_type, cur_pixels = _decode_browser_png(candidate_png)
    if (ref_w, ref_h) != (cur_w, cur_h):
        return False, (
            f"dimensions changed ({ref_w}x{ref_h} -> {cur_w}x{cur_h})"
        )
    # The common path avoids materialising two additional 80 MB RGBA buffers:
    # equal decoded RGB (or RGBA) samples imply equal RGBA samples exactly.
    if ref_type == cur_type and ref_pixels == cur_pixels:
        return True, f"{ref_w}x{ref_h}, 0 differing decoded RGBA pixels"

    channels = {0: 1, 2: 3, 4: 2, 6: 4}

    def rgba_at(pixels: bytes, color_type: int, index: int):
        channel_count = channels[color_type]
        at = index * channel_count
        if color_type == 0:
            value = pixels[at]
            return value, value, value, 255
        if color_type == 2:
            return pixels[at], pixels[at + 1], pixels[at + 2], 255
        if color_type == 4:
            value = pixels[at]
            return value, value, value, pixels[at + 1]
        return tuple(pixels[at:at + 4])

    for pixel_index in range(ref_w * ref_h):
        if rgba_at(ref_pixels, ref_type, pixel_index) != rgba_at(
                cur_pixels, cur_type, pixel_index):
            x = pixel_index % ref_w
            y = pixel_index // ref_w
            return False, (
                f"at least 1 decoded RGBA pixel differs; first at ({x}, {y})"
            )
    return True, f"{ref_w}x{ref_h}, 0 differing decoded RGBA pixels"


def _capture_full_viewport_png(page, viewport: tuple[int, int]) -> bytes:
    """Capture the fixed 1x poster viewport used by the geometry pixel gate."""
    width, height = viewport
    payload = page.screenshot(
        type="png",
        full_page=False,
        clip={"x": 0, "y": 0, "width": width, "height": height},
    )
    if not isinstance(payload, bytes) or not payload:
        raise RuntimeError("Playwright returned an empty reference screenshot")
    return payload


def _ensure_unscaled_layout_timer_guard(html_path: Path) -> bool:
    """Run recurring geometry fitters against the unscaled poster canvas.

    Some legacy/model-authored posters keep a figure fitted with a short
    ``setInterval`` callback that reads ``getBoundingClientRect()``.  The
    standalone poster controller deliberately scales the complete fixed canvas
    with a CSS transform.  A timer that reads the transformed rectangle and
    writes that screen-space width back as CSS pixels applies the scale twice.

    Install a tiny early guard only when an authored script contains both
    primitives.  It preserves timer behavior and arguments, but temporarily
    clears the poster's exact inline transform around each interval callback,
    then restores the same value and priority in ``finally``.  This deliberately
    does not call ``__fitPosterStage``: that controller recomputes a transform
    from the viewport and would overwrite an external thumbnail/backfill scale.
    Wrapping every interval on an affected legacy page also covers callbacks
    written as ``() => enforce()`` whose own source hides the geometry read.
    The block is renderer-owned and idempotent so rerenders never accumulate
    shims.
    """
    import re

    original = html_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'\s*<script\b(?=[^>]*\bid\s*=\s*["\']'
        rf'{re.escape(_LAYOUT_TIMER_GUARD_ID)}["\'])[^>]*>.*?</script>\s*',
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = pattern.sub("\n", original)
    authored_scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # The scheduler and the fitter are often authored in separate blocks
    # (for example, one block exports ``fit`` and a later block installs the
    # interval).  Treat the page's authored scripts as one program when
    # deciding whether the guard is required; requiring both primitives in a
    # single ``<script>`` silently misses that common split form.
    authored_program = "\n".join(authored_scripts)
    needs_guard = (
        "setInterval" in authored_program
        and "getBoundingClientRect" in authored_program
    )
    if needs_guard:
        guard = f'''<script id="{_LAYOUT_TIMER_GUARD_ID}">
(() => {{
  const nativeSetInterval = window.setInterval.bind(window);
  window.setInterval = function(callback, delay, ...args) {{
    if (typeof callback !== 'function') {{
      const guardedSource =
        "if (document.documentElement.getAttribute("
        + "'{_GEOMETRY_FROZEN_ATTR}') !== '1') {{\\n"
        + String(callback) + "\\n}}";
      return nativeSetInterval(guardedSource, delay, ...args);
    }}
    const guarded = function(...tickArgs) {{
      if (document.documentElement.getAttribute(
            '{_GEOMETRY_FROZEN_ATTR}') === '1') return;
      const invoke = () => callback.apply(window, tickArgs);
      const poster = document.querySelector('[data-measure-role="poster"]')
        || document.querySelector('.poster')
        || document.body;
      if (!poster) return invoke();
      const oldTransform = poster.style.getPropertyValue('transform');
      const oldPriority = poster.style.getPropertyPriority('transform');
      try {{
        poster.style.setProperty('transform', 'none', 'important');
        return invoke();
      }} finally {{
        if (oldTransform)
          poster.style.setProperty('transform', oldTransform, oldPriority);
        else
          poster.style.removeProperty('transform');
      }}
    }};
    return nativeSetInterval(guarded, delay, ...args);
  }};
}})();
</script>'''
        opening_head = re.search(r"<head\b[^>]*>", text, flags=re.IGNORECASE)
        if opening_head:
            at = opening_head.end()
            text = text[:at] + "\n" + guard + text[at:]
        else:
            text = guard + "\n" + text
    if text == original:
        return False
    html_path.write_text(text, encoding="utf-8")
    return True


def _bake_expand_into_html(html_path: Path, baked: list) -> bool:
    """Persist the render-time expand into the deliverable poster.html.

    The expand pass grows each under-filled card's inner row-gaps in the live
    DOM before printing the PDF/PNG. To keep the editable poster.html (its `D`
    debug overlay, and the downstream html2pptx read) consistent with the
    rendered PDF/PNG, write the resulting row-gaps back as one
    <style id="poster-expand-baked"> block. Responsive-safe: the templates use a
    fixed internal layout scaled by an outer `transform: scale()`, so an inline
    px row-gap renders identically at any view size. Idempotent -- a re-render
    strips the old derived block before measuring and appends this fresh block
    after every other author style, so an older/newer autofit block cannot win
    again on reload. Written only at final render (after the fill loop), so the
    loop still measures the natural layout.
    """
    original = html_path.read_text(encoding="utf-8")
    txt, _ = _strip_derived_style_block(original, "poster-expand-baked")
    if baked:
        rules = "\n".join(
            f'  .section[data-section="{sid}"]{{ row-gap: {gap} !important; }}'
            for sid, gap in baked
        )
        block = f'<style id="poster-expand-baked">\n{rules}\n</style>'
        txt = _append_style_at_end(txt, block)
    if txt == original:
        return False
    html_path.write_text(txt, encoding="utf-8")
    return True


_EXPAND_SNAPSHOT_JS = r"""
() => {
  const rectOf = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x:r.x, y:r.y, w:r.width, h:r.height};
  };
  // Match the polish gate for object-fit:contain. scale-down differs when the
  // intrinsic image is already smaller than its CSS box, so preserve its
  // unscaled natural size in that case.
  const paintedDims = (img, r) => {
    const nw = img.naturalWidth || 0;
    const nh = img.naturalHeight || 0;
    const fit = getComputedStyle(img).objectFit || 'fill';
    if (nw <= 0 || nh <= 0 || r.width <= 0 || r.height <= 0)
      return {w:r.width, h:r.height, nw:nw, nh:nh, fit:fit};
    const boxAR = r.width / r.height;
    const natAR = nw / nh;
    const contained = natAR > boxAR
      ? {w:r.width, h:r.width / natAR}
      : {w:r.height * natAR, h:r.height};
    if (fit === 'contain')
      return {...contained, nw:nw, nh:nh, fit:fit};
    if (fit === 'scale-down') {
      const scaled = contained.w <= nw && contained.h <= nh;
      return scaled
        ? {...contained, nw:nw, nh:nh, fit:fit}
        : {w:nw, h:nh, nw:nw, nh:nh, fit:fit};
    }
    if (fit === 'none')
      return {w:Math.min(nw, r.width), h:Math.min(nh, r.height),
              nw:nw, nh:nh, fit:fit};
    // fill and cover both paint the visible element box completely.
    return {w:r.width, h:r.height, nw:nw, nh:nh, fit:fit};
  };
  const sectionNodes = Array.from(
    document.querySelectorAll('.section[data-section]')
  );
  const parentNodes = [];
  const parentKey = node => {
    if (!node) return 'parent:none';
    let index = parentNodes.indexOf(node);
    if (index < 0) { parentNodes.push(node); index = parentNodes.length - 1; }
    return 'parent:' + index;
  };
  const sections = sectionNodes.map((sec, index) => ({
    key:'section:' + index,
    sid:sec.getAttribute('data-section') || '',
    parentKey:parentKey(sec.parentElement),
    rect:rectOf(sec),
    parentRect:rectOf(sec.parentElement),
    rowGap:parseFloat(getComputedStyle(sec).rowGap) || 0,
  }));
  const media = [];
  sectionNodes.forEach((sec, sectionIndex) => {
    const section = sections[sectionIndex];
    const eligibleImages = new Set();
    Array.from(sec.querySelectorAll('img')).forEach((img, imageIndex) => {
      if (img.closest('.section[data-section]') !== sec) return;
      const source = img.getAttribute('src') || '';
      const isResearchFigure = !!img.closest('figure, .figure')
        || /(^|\/)figures?\//i.test(source);
      const r = img.getBoundingClientRect();
      // The size cutoff excludes incidental utility icons only.  A collapsed
      // research image is itself a figure-floor failure and must remain in the
      // snapshot; otherwise its larger <figure> wrapper is misreported below as
      // a fully painted fallback and the absolute >=90% gate is bypassed.
      if (!isResearchFigure && (r.width < 50 || r.height < 1)) return;
      eligibleImages.add(img);
      const p = paintedDims(img, r);
      media.push({
        key:section.key + '|img:' + imageIndex,
        sectionKey:section.key, sid:section.sid,
        parentKey:section.parentKey, kind:'img',
        isResearchFigure:isResearchFigure,
        src:source,
        currentSrc:img.currentSrc || '',
        boxW:r.width, boxH:r.height,
        paintedW:p.w, paintedH:p.h,
        nw:p.nw, nh:p.nh, fit:p.fit,
      });
    });
    // A fixture or legacy poster may use a painted .figure block instead of
    // an <img>. Keep these fallbacks even when another real image exists
    // elsewhere in the same card.
    Array.from(sec.querySelectorAll('figure, .figure'))
      .forEach((node, figureIndex) => {
        if (node.closest('.section[data-section]') !== sec) return;
        if (Array.from(node.querySelectorAll('img'))
            .some(img => eligibleImages.has(img))) return;
        const r = node.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return;
        const visualRects = Array.from(node.querySelectorAll(
          'svg, canvas, video, object, embed'
        )).filter(visual => visual.closest('figure, .figure') === node)
          .map(visual => visual.getBoundingClientRect())
          .filter(box => box.width >= 1 && box.height >= 1);
        let paintedW = 0;
        let paintedH = 0;
        let fallbackFit = 'unverified-fallback';
        if (visualRects.length) {
          const left = Math.max(r.left,
            Math.min(...visualRects.map(box => box.left)));
          const top = Math.max(r.top,
            Math.min(...visualRects.map(box => box.top)));
          const right = Math.min(r.right,
            Math.max(...visualRects.map(box => box.right)));
          const bottom = Math.min(r.bottom,
            Math.max(...visualRects.map(box => box.bottom)));
          paintedW = Math.max(0, right - left);
          paintedH = Math.max(0, bottom - top);
          fallbackFit = 'visual-descendant';
        } else {
          const style = getComputedStyle(node);
          const backgroundSize = (style.backgroundSize || '')
            .trim().toLowerCase();
          if (style.backgroundImage !== 'none'
              && (backgroundSize === 'cover'
                || backgroundSize === '100% 100%')) {
            paintedW = r.width;
            paintedH = r.height;
            fallbackFit = 'background-cover';
          }
        }
        media.push({
          key:section.key + '|figure:' + figureIndex,
          sectionKey:section.key, sid:section.sid,
          parentKey:section.parentKey, kind:'figure',
          isResearchFigure:true,
          src:'', currentSrc:'', boxW:r.width, boxH:r.height,
          paintedW:paintedW, paintedH:paintedH,
          nw:0, nh:0, fit:fallbackFit,
        });
      });
  });
  const text = Array.from(document.querySelectorAll(
    'h1,h2,h3,h4,h5,h6,p,li,td,th,figcaption,blockquote'
  )).map((node, index) => {
    const rect = node.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(node);
    const inkRects = Array.from(range.getClientRects()).filter(
      r => r.width > 0.01 && r.height > 0.01
    );
    const lineTops = [];
    inkRects.forEach(r => {
      if (!lineTops.some(y => Math.abs(y - r.top) <= 1)) lineTops.push(r.top);
    });
    const ink = inkRects.length ? {
      x:Math.min(...inkRects.map(r => r.left)),
      y:Math.min(...inkRects.map(r => r.top)),
      w:Math.max(...inkRects.map(r => r.right))
        - Math.min(...inkRects.map(r => r.left)),
      h:Math.max(...inkRects.map(r => r.bottom))
        - Math.min(...inkRects.map(r => r.top)),
    } : {x:rect.x, y:rect.y, w:0, h:0};
    const section = node.closest('.section[data-section]');
    const sectionIndex = section ? sectionNodes.indexOf(section) : -1;
    return {
      key:'text:' + index,
      tag:node.tagName.toLowerCase(),
      value:(node.innerText || '').replace(/\s+/g, ' ').trim(),
      sid:section ? (section.getAttribute('data-section') || '') : '',
      parentKey:sectionIndex >= 0 ? sections[sectionIndex].parentKey : '',
      controlled:!!node.closest('.section[data-section="scan-to-read"]'),
      rect:rectOf(node), ink:ink, lineCount:lineTops.length,
    };
  });
  const landmarkNodes = [
    ...document.querySelectorAll('.poster'),
    ...document.querySelectorAll('.titlebar'),
    ...document.querySelectorAll('.columns'),
    ...document.querySelectorAll('.columns > .col'),
  ];
  const landmarks = landmarkNodes.map((node, index) => ({
    key:'landmark:' + index,
    classes:node.className || '',
    rect:rectOf(node),
  }));
  return {sections:sections, media:media, text:text, landmarks:landmarks};
}
"""


def _capture_expand_snapshot(page) -> dict:
    """Capture the natural section/parent/media geometry in one JS source."""
    result = page.evaluate(_EXPAND_SNAPSHOT_JS)
    if not isinstance(result, dict):
        raise RuntimeError("expand snapshot returned malformed data")
    return result


def _validate_source_geometry(
    page,
    baseline: dict,
    *,
    allow_scan_reflow: bool = False,
) -> list[str]:
    """Compare the accepted cold page with its pre-font-freeze source layout.

    Renderer-owned row-gap expansion may move content vertically inside a card,
    so text *positions* are intentionally not compared.  Text wrapping/ink
    bounds, section/card geometry, landmarks, and media dimensions remain hard
    invariants.  The parent column containing Scan-to-Read is excluded only
    after the explicit scan-suppression pass actually hides that section and
    is therefore allowed to reflow that one scope.  Callers must first run a
    strict pre-suppression comparison so portable-font changes cannot hide in
    the same column.
    """
    after = _capture_expand_snapshot(page)
    failures: list[str] = []

    def close(left, right, tolerance: float = _EXPAND_GEOMETRY_TOLERANCE_PX):
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False

    def rect_close(left, right, *, position: bool = True) -> bool:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        keys = ("x", "y", "w", "h") if position else ("w", "h")
        return all(close(left.get(key), right.get(key)) for key in keys)

    before_sections = [
        item for item in (baseline.get("sections") or [])
        if isinstance(item, dict)
    ]
    after_sections = [
        item for item in (after.get("sections") or [])
        if isinstance(item, dict)
    ]
    controlled_parents = (
        {
            str(item.get("parentKey", "")) for item in before_sections
            if str(item.get("sid", "")) == "scan-to-read"
        }
        if allow_scan_reflow
        else set()
    )
    if len(before_sections) != len(after_sections):
        failures.append(
            f"section count changed ({len(before_sections)} -> {len(after_sections)})"
        )
    for index, (before, current) in enumerate(zip(before_sections, after_sections)):
        identity = ("key", "sid", "parentKey")
        if any(before.get(key) != current.get(key) for key in identity):
            failures.append(f"section identity/order changed at index {index}")
            continue
        if str(before.get("parentKey", "")) in controlled_parents:
            continue
        if not rect_close(before.get("rect"), current.get("rect")):
            failures.append(f"section geometry changed: {before.get('sid', index)}")
        if not rect_close(before.get("parentRect"), current.get("parentRect")):
            failures.append(f"section parent geometry changed: {before.get('sid', index)}")

    before_landmarks = [
        item for item in (baseline.get("landmarks") or [])
        if isinstance(item, dict)
    ]
    after_landmarks = [
        item for item in (after.get("landmarks") or [])
        if isinstance(item, dict)
    ]
    if len(before_landmarks) != len(after_landmarks):
        failures.append(
            "poster/header/column landmark count changed "
            f"({len(before_landmarks)} -> {len(after_landmarks)})"
        )
    for index, (before, current) in enumerate(zip(before_landmarks, after_landmarks)):
        if (before.get("key") != current.get("key")
                or before.get("classes") != current.get("classes")):
            failures.append(f"landmark identity/order changed at index {index}")
        elif not rect_close(before.get("rect"), current.get("rect")):
            failures.append(f"landmark geometry changed at index {index}")

    before_media = [
        item for item in (baseline.get("media") or [])
        if isinstance(item, dict)
    ]
    after_media = [
        item for item in (after.get("media") or [])
        if isinstance(item, dict)
    ]
    if allow_scan_reflow:
        # A suppressed legacy Scan-to-Read tile can collapse its QR <img> to
        # 0x0.  The snapshot intentionally omits such non-research media, so
        # remove the complete controlled parent scope before comparing key
        # sets.  Additions/removals everywhere else remain strict.
        before_media = [
            item for item in before_media
            if str(item.get("parentKey", "")) not in controlled_parents
        ]
        after_media = [
            item for item in after_media
            if str(item.get("parentKey", "")) not in controlled_parents
        ]
    before_media_by_key = {str(item.get("key", "")): item for item in before_media}
    after_media_by_key = {str(item.get("key", "")): item for item in after_media}
    if set(before_media_by_key) != set(after_media_by_key):
        failures.append("media set changed")
    for key, before in before_media_by_key.items():
        if str(before.get("parentKey", "")) in controlled_parents:
            continue
        current = after_media_by_key.get(key)
        if current is None:
            continue
        identity = ("sectionKey", "sid", "kind", "src", "fit", "isResearchFigure")
        if any(before.get(field) != current.get(field) for field in identity):
            failures.append(f"media identity/source changed: {key}")
            continue
        for field in ("boxW", "boxH", "paintedW", "paintedH"):
            old_value = float(before.get(field) or 0)
            new_value = float(current.get(field) or 0)
            tolerance = min(
                _EXPAND_GEOMETRY_TOLERANCE_PX,
                _EXPAND_MEDIA_REL_TOLERANCE
                * max(abs(old_value), abs(new_value)),
            )
            if not close(old_value, new_value, tolerance):
                failures.append(f"media {field} changed: {key}")
        if (before.get("nw"), before.get("nh")) != (
                current.get("nw"), current.get("nh")):
            failures.append(f"media intrinsic dimensions changed: {key}")

    before_text = [
        item for item in (baseline.get("text") or [])
        if isinstance(item, dict)
    ]
    after_text = [
        item for item in (after.get("text") or [])
        if isinstance(item, dict)
    ]
    if len(before_text) != len(after_text):
        failures.append(f"text-block count changed ({len(before_text)} -> {len(after_text)})")
    for index, (before, current) in enumerate(zip(before_text, after_text)):
        if (before.get("key") != current.get("key")
                or before.get("tag") != current.get("tag")
                or before.get("value") != current.get("value")):
            failures.append(f"text identity/content changed at index {index}")
            continue
        if allow_scan_reflow and (
                before.get("controlled")
                or str(before.get("parentKey", "")) in controlled_parents):
            continue
        if before.get("lineCount") != current.get("lineCount"):
            failures.append(f"text wrapping changed: {before.get('key', index)}")
        if not rect_close(before.get("rect"), current.get("rect"), position=False):
            failures.append(f"text block size changed: {before.get('key', index)}")
        if not rect_close(before.get("ink"), current.get("ink"), position=False):
            failures.append(f"text ink bounds changed: {before.get('key', index)}")

    # Keep diagnostics bounded even on a badly diverged legacy page.
    return failures[:80]


def _wait_for_images_decoded(page, *, timeout_ms: int, label: str) -> bool:
    """Wait until every document image has loaded and decoded.

    A same-context reload can reuse Chromium's decoded-image cache while a
    standalone reopen cannot.  Durable geometry must therefore be measured
    only after a bounded decode wait in the fresh context used for capture.
    """
    # Playwright interprets timeout=0 as "wait forever".  The CLI accepts
    # zero for historical compatibility, so clamp every call to a genuinely
    # bounded host-side timeout before entering the page.
    timeout_ms = max(1_000, int(timeout_ms))
    state_name = "__paper2posterImageDecodeState"
    try:
        # Start and poll the asynchronous decode inside wait_for_function.
        # Unlike page.evaluate, Playwright enforces this call's timeout from
        # the host even when the page main thread is busy or the poster has
        # replaced/throttled window.setTimeout. This keeps a nominally bounded
        # image gate from hanging the complete render transaction.
        status_handle = page.wait_for_function(
            """stateName => {
              let state = window[stateName];
              if (!state) {
                state = {status:'pending'};
                window[stateName] = state;
                Promise.all(Array.from(document.images).map(async img => {
                  if (!img.complete) {
                    await new Promise(resolve => {
                      img.addEventListener('load', resolve, {once:true});
                      img.addEventListener('error', resolve, {once:true});
                    });
                  }
                  if (typeof img.decode === 'function') {
                    try { await img.decode(); } catch (_) {}
                  }
                  return img.complete && img.naturalWidth > 0
                    && img.naturalHeight > 0;
                })).then(
                  results => { state.status = results.every(Boolean)
                    ? 'ok' : 'failed'; },
                  () => { state.status = 'failed'; },
                );
              }
              return state.status === 'pending' ? false : state.status;
            }""",
            arg=state_name,
            timeout=timeout_ms,
            polling=100,
        )
        try:
            status = status_handle.json_value()
        finally:
            status_handle.dispose()
    except Exception as exc:
        _eprint(
            f"[render_preview] WARN: {label} images did not decode cleanly "
            f"within {timeout_ms} ms: {ascii_safe(exc)}."
        )
        return False
    if status != "ok":
        _eprint(
            f"[render_preview] WARN: {label} images did not decode cleanly "
            f"within {timeout_ms} ms ({ascii_safe(status)})."
        )
        return False
    return True


def _validate_durable_expand(
    page,
    records: list[dict],
    baseline: dict,
    *,
    enforce_figure_floor: bool = True,
) -> dict:
    """Validate provisional rules against the whole natural poster snapshot.

    A gap added in one card can make an on-load fitter shrink a figure in a
    sibling card.  Looking only inside the candidate card would miss that
    collateral change, so validation covers every section, its immediate
    parent, and every visible card image/figure fallback.  Failures remove all
    rules in the affected original parent scope; an un-attributable failure
    removes every remaining rule (fail closed).
    """
    after = _capture_expand_snapshot(page)
    result = page.evaluate(
        """({records, baseline, after, gapTol, geomTol,
              mediaRelTol, figMin, figMax}) => {
          const beforeSections = Array.isArray(baseline && baseline.sections)
            ? baseline.sections : [];
          const beforeMedia = Array.isArray(baseline && baseline.media)
            ? baseline.media : [];
          const close = (a, b, tol) => Number.isFinite(a)
            && Number.isFinite(b) && Math.abs(a - b) <= tol;
          const rectClose = (a, b) => !!a && !!b
            && ['x', 'y', 'w', 'h'].every(k => close(a[k], b[k], geomTol));
          // One CSS pixel is the maximum media drift.  The 0.5% allowance is
          // only a tighter tolerance for small media, never a looser large-box
          // tolerance.
          const mediaTol = (a, b) => Math.min(
            geomTol,
            mediaRelTol * Math.max(Math.abs(a), Math.abs(b)),
          );
          const scopedReasons = new Map();
          const globalReasons = [];
          const addFailure = (scope, reason) => {
            const key = String(scope || '');
            if (!key) { globalReasons.push(reason); return; }
            if (!scopedReasons.has(key)) scopedReasons.set(key, []);
            const reasons = scopedReasons.get(key);
            if (!reasons.includes(reason)) reasons.push(reason);
          };
          const recordsByScope = new Map();
          records.forEach(record => {
            const scope = String(record.scope || '');
            if (!recordsByScope.has(scope)) recordsByScope.set(scope, []);
            recordsByScope.get(scope).push(record);
          });

          const style = document.getElementById('poster-expand-baked');
          if (!!style !== (records.length > 0))
            globalReasons.push('persisted expand style presence does not match rules');
          if (document.documentElement.dataset.posterExpandEphemeral)
            globalReasons.push('page still carries a live-only expand marker');

          const beforeSectionByKey = new Map(
            beforeSections.map(item => [item.key, item])
          );
          const sectionByKey = new Map(after.sections.map(item => [item.key, item]));
          const currentNodes = Array.from(
            document.querySelectorAll('.section[data-section]')
          );
          for (const record of records) {
            const sid = String(record.sid || '');
            const matches = currentNodes.filter(
              sec => sec.getAttribute('data-section') === sid
            );
            if (matches.length !== 1) {
              addFailure(record.scope,
                'expected one durable section for ' + sid + ', found ' + matches.length);
              continue;
            }
            const targetGap = parseFloat(record.gap);
            const durableGap = parseFloat(getComputedStyle(matches[0]).rowGap);
            if (!close(targetGap, durableGap, gapTol))
              addFailure(record.scope, 'row-gap lost after reload: ' + sid);
          }

          if (beforeSections.length !== after.sections.length)
            globalReasons.push('section set changed');
          const sectionCount = Math.min(beforeSections.length, after.sections.length);
          for (let i = 0; i < sectionCount; i += 1) {
            const before = beforeSections[i];
            const current = after.sections[i];
            if (before.key !== current.key || before.sid !== current.sid
                || before.parentKey !== current.parentKey) {
              globalReasons.push('section identity/order changed at index ' + i);
              continue;
            }
            if (!rectClose(before.rect, current.rect))
              addFailure(before.parentKey, 'section geometry changed: ' + before.sid);
            if (!rectClose(before.parentRect, current.parentRect))
              addFailure(before.parentKey, 'parent geometry changed: ' + before.sid);
            const target = records.find(record => record.sid === before.sid);
            const expectedGap = target ? parseFloat(target.gap) : before.rowGap;
            if (!close(expectedGap, current.rowGap, gapTol))
              addFailure(before.parentKey, 'unexpected row-gap changed: ' + before.sid);
          }

          const beforeMediaByKey = new Map(beforeMedia.map(item => [item.key, item]));
          const afterMediaByKey = new Map(after.media.map(item => [item.key, item]));
          for (const before of beforeMedia) {
            const current = afterMediaByKey.get(before.key);
            if (!current) {
              addFailure(before.parentKey, 'media removed: ' + before.key);
              continue;
            }
            if (before.kind !== current.kind || before.sectionKey !== current.sectionKey
                || before.sid !== current.sid || before.src !== current.src
                || before.currentSrc !== current.currentSrc || before.fit !== current.fit) {
              addFailure(before.parentKey, 'media identity/source changed: ' + before.key);
              continue;
            }
            const dims = [
              ['box width', before.boxW, current.boxW],
              ['box height', before.boxH, current.boxH],
              ['painted width', before.paintedW, current.paintedW],
              ['painted height', before.paintedH, current.paintedH],
            ];
            for (const [label, oldValue, newValue] of dims) {
              if (!close(oldValue, newValue, mediaTol(oldValue, newValue)))
                addFailure(before.parentKey,
                  'media ' + label + ' changed: ' + before.key);
            }
            if (before.nw !== current.nw || before.nh !== current.nh)
              addFailure(before.parentKey,
                'media intrinsic dimensions changed: ' + before.key);
            if (current.kind === 'img' && (current.nw <= 0 || current.nh <= 0))
              addFailure(before.parentKey, 'media failed to load: ' + before.key);
            const beforeSec = beforeSectionByKey.get(before.sectionKey);
            const sec = sectionByKey.get(current.sectionKey);
            const beforeWr = beforeSec && beforeSec.rect && beforeSec.rect.w > 0
              ? before.paintedW / beforeSec.rect.w : 0;
            const beforeHr = beforeSec && beforeSec.rect && beforeSec.rect.h > 0
              ? before.paintedH / beforeSec.rect.h : 0;
            const wr = sec && sec.rect && sec.rect.w > 0
              ? current.paintedW / sec.rect.w : 0;
            const hr = sec && sec.rect && sec.rect.h > 0
              ? current.paintedH / sec.rect.h : 0;
            const fill = Math.max(wr, hr);
            // Research figures normally have an absolute minimum.  The only
            // exception is the explicit historical-backfill token, represented
            // here by figMin=0; the <=1.01 overflow ceiling stays unconditional.
            // QR codes and utility images are excluded by isResearchFigure.
            if (current.isResearchFigure && fill + 1e-6 < figMin)
              addFailure(before.parentKey,
                'media fill dropped below floor: ' + before.key);
            if (current.isResearchFigure && (wr > figMax || hr > figMax))
              addFailure(before.parentKey,
                'media overflowed its section: ' + before.key);
          }
          for (const current of after.media) {
            if (!beforeMediaByKey.has(current.key))
              addFailure(current.parentKey, 'media added: ' + current.key);
          }

          const unattributed = [...scopedReasons.keys()].filter(
            scope => !(recordsByScope.get(scope) || []).length
          );
          if (unattributed.length) {
            globalReasons.push(...unattributed.map(scope =>
              'collateral change outside a candidate scope: ' + scope));
          }
          const failures = [];
          for (const record of records) {
            const reasons = [
              ...(scopedReasons.get(String(record.scope || '')) || []),
              ...globalReasons,
            ];
            if (reasons.length)
              failures.push({sid:String(record.sid || ''), reasons:reasons});
          }
          const snapshotReasons = [
            ...globalReasons,
            ...[...scopedReasons.values()].flat(),
          ];
          return {
            failures:failures,
            snapshotOk:snapshotReasons.length === 0,
            snapshotReasons:snapshotReasons,
          };
        }""",
        {
            "records": records,
            "baseline": baseline,
            "after": after,
            "gapTol": _EXPAND_GAP_TOLERANCE_PX,
            "geomTol": _EXPAND_GEOMETRY_TOLERANCE_PX,
            "mediaRelTol": _EXPAND_MEDIA_REL_TOLERANCE,
            "figMin": (
                _EXPAND_FIG_MIN_RATIO if enforce_figure_floor else 0.0
            ),
            "figMax": _EXPAND_FIG_MAX_RATIO,
        },
    )
    if not isinstance(result, dict):
        return {
            "failures": [
                {"sid": str(record.get("sid", "")),
                 "reasons": ["durable validator returned malformed data"]}
                for record in records
            ],
            "snapshotOk": False,
            "snapshotReasons": ["durable validator returned malformed data"],
        }
    return result


def _validate_final_figure_fill(
    page,
    *,
    enforce_minimum: bool = True,
) -> list[str]:
    """Return absolute research-figure fill/overflow failures for ``page``.

    Expand validation is conditional: a poster with no provisional expand rule
    can reach capture without calling ``_validate_durable_expand`` at all.  The
    >=90% figure contract is normally unconditional, so enforce it once
    more on the accepted cold page immediately before PDF/PNG capture.  The
    sole exception is the explicit historical-backfill compatibility token:
    those immutable source pixels may already violate the modern minimum.
    Overflow remains strict in both modes.
    """
    snapshot = _capture_expand_snapshot(page)
    sections = {
        str(item.get("key", "")): item
        for item in (snapshot.get("sections") or [])
        if isinstance(item, dict)
    }
    failures: list[str] = []
    for media in snapshot.get("media") or []:
        if not isinstance(media, dict) or not media.get("isResearchFigure"):
            continue
        section = sections.get(str(media.get("sectionKey", ""))) or {}
        rect = section.get("rect") or {}
        section_w = float(rect.get("w") or 0)
        section_h = float(rect.get("h") or 0)
        if section_w <= 0 or section_h <= 0:
            failures.append(
                f"research figure has no measurable section: {media.get('key', '')}"
            )
            continue
        width_ratio = float(media.get("paintedW") or 0) / section_w
        height_ratio = float(media.get("paintedH") or 0) / section_h
        fill = max(width_ratio, height_ratio)
        key = str(media.get("key", ""))
        if enforce_minimum and fill + 1e-6 < _EXPAND_FIG_MIN_RATIO:
            failures.append(
                f"research figure fill {fill:.4f} is below "
                f"{_EXPAND_FIG_MIN_RATIO:.2f}: {key}"
            )
        if (width_ratio > _EXPAND_FIG_MAX_RATIO + 1e-6
                or height_ratio > _EXPAND_FIG_MAX_RATIO + 1e-6):
            failures.append(
                "research figure overflows its section "
                f"({width_ratio:.4f}x{height_ratio:.4f}): {key}"
            )
    return failures


def _settle_loaded_durable_page(
    page,
    *,
    timeout_ms: int,
    playwright_timeout_error,
    label: str,
) -> bool:
    """Settle one loaded durable page and fail closed for expand validation."""
    stable = True
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except playwright_timeout_error:
        _eprint(
            f"[render_preview] WARN: {label} never went idle within "
            f"{timeout_ms} ms; continuing to the bounded settle check."
        )
    except Exception as exc:
        _eprint(
            f"[render_preview] WARN: {label} load-state check failed: "
            f"{ascii_safe(exc)}."
        )
        stable = False
    if not _wait_for_images_decoded(
        page,
        timeout_ms=timeout_ms,
        label=label,
    ):
        stable = False
    try:
        durable_settle = _render.settle_page(
            page,
            mathjax_timeout_ms=timeout_ms,
            settle_ms=1500,
        )
    except Exception as exc:
        _eprint(
            f"[render_preview] WARN: {label} settle failed: "
            f"{ascii_safe(exc)}; provisional expand rules will fail closed."
        )
        return False
    if durable_settle.mathjax_status == "timeout":
        stable = False
        _eprint(
            f"[render_preview] WARN: MathJax typeset timed out after {label} "
            f"({timeout_ms} ms)."
        )
    elif durable_settle.mathjax_status == "error":
        stable = False
        _eprint(
            f"[render_preview] WARN: MathJax error after {label}: "
            f"{ascii_safe(durable_settle.mathjax_error)}"
        )
    if (durable_settle.mathjax_intended and
            durable_settle.tex_without_mathjax):
        stable = False
        _eprint(
            f"[render_preview] WARN: {label} intended to load MathJax but no "
            "<mjx-container> rendered -- PDF will show raw $...$ text."
        )
    return stable


def _reload_and_settle_after_bake(
    page,
    *,
    timeout_ms: int,
    playwright_timeout_error,
    label: str,
) -> tuple[bool, bool]:
    """Reload renderer-owned CSS and report navigation and settle separately.

    Rendering remains a soft path for MathJax/network failures, but provisional
    expand rules are optional.  A rule may be kept only when the durable page
    completed the same settle cycle used for final capture; otherwise its
    validator fails closed and removes it.  A failed navigation is different:
    there is no persisted page to validate or capture, so callers keep that as
    a hard transaction failure.
    """
    navigated = True
    try:
        # ``Page.reload`` can detach a ``file:`` target with net::ERR_FAILED
        # when the renderer has just atomically rewritten that same file.
        # Navigating the existing page to its identical URL preserves the
        # BrowserContext/cache semantics required by this warm check without
        # depending on Chromium's reload fast path.
        page.goto(
            page.url.split("#", 1)[0],
            timeout=timeout_ms,
            wait_until="domcontentloaded",
        )
    except playwright_timeout_error:
        navigated = False
        _eprint(
            f"[render_preview] WARN: {label} did not reach "
            "`domcontentloaded` within "
            f"{timeout_ms} ms; provisional expand rules will fail closed."
        )
    except Exception as exc:
        _eprint(
            f"[render_preview] WARN: {label} failed: {ascii_safe(exc)}; "
            "provisional expand rules will fail closed."
        )
        return False, False
    settled = _settle_loaded_durable_page(
        page,
        timeout_ms=timeout_ms,
        playwright_timeout_error=playwright_timeout_error,
        label=label,
    )
    return navigated, settled


def _new_print_context_page(browser, viewport: tuple[int, int]):
    """Create an isolated print-emulated page without warming its context."""
    width, height = viewport
    context = browser.new_context(
        viewport={"width": width, "height": height},
    )
    page = context.new_page()
    _render.route_mathjax_local(page)
    _render.route_katex_local(page)
    page.emulate_media(media="print")
    page.set_viewport_size({"width": width, "height": height})
    return context, page


def _open_fresh_durable_page(
    browser,
    viewport: tuple[int, int],
    html_path: Path,
    *,
    timeout_ms: int,
    playwright_timeout_error,
    label: str,
):
    """Open a fresh context and return navigation and settle independently."""
    context, page = _new_print_context_page(browser, viewport)
    navigated = True
    try:
        page.goto(
            html_path.as_uri(),
            timeout=timeout_ms,
            wait_until="domcontentloaded",
        )
    except playwright_timeout_error:
        navigated = False
        _eprint(
            f"[render_preview] WARN: {label} did not reach "
            "`domcontentloaded` within "
            f"{timeout_ms} ms; provisional expand rules will fail closed."
        )
    except Exception as exc:
        _eprint(
            f"[render_preview] WARN: {label} failed: {ascii_safe(exc)}; "
            "provisional expand rules will fail closed."
        )
        return context, page, False, False
    stable = _settle_loaded_durable_page(
        page,
        timeout_ms=timeout_ms,
        playwright_timeout_error=playwright_timeout_error,
        label=label,
    )
    return context, page, navigated, stable


def _capture_style_targets_and_freeze(context, page):
    """Disable page scripts and return CDP nodes used for thumbnail scaling.

    The accepted durable page may still contain recurring author fitters.  They
    are harmless at the 1x print viewport but can observe the renderer's later
    thumbnail transform and write screen-space dimensions back into the fixed
    canvas.  Freeze script execution before either artifact is captured; CDP
    DOM commands remain available for the live-only thumbnail transform.
    """
    session = context.new_cdp_session(page)
    session.send("DOM.enable")
    root = session.send("DOM.getDocument", {"depth": 1}).get("root") or {}
    root_id = int(root.get("nodeId") or 0)
    if not root_id:
        raise RuntimeError("CDP did not return a document node")

    def query(*selectors: str) -> int:
        for selector in selectors:
            result = session.send(
                "DOM.querySelector",
                {"nodeId": root_id, "selector": selector},
            )
            node_id = int(result.get("nodeId") or 0)
            if node_id:
                return node_id
        return 0

    def style_of(node_id: int) -> str:
        attributes = session.send(
            "DOM.getAttributes", {"nodeId": node_id}
        ).get("attributes") or []
        for index in range(0, len(attributes) - 1, 2):
            if attributes[index].lower() == "style":
                return str(attributes[index + 1])
        return ""

    poster_id = query('[data-measure-role="poster"]', ".poster", "body")
    body_id = query("body")
    html_id = query("html")
    if not poster_id or not body_id or not html_id:
        raise RuntimeError("CDP could not resolve poster/body/html nodes")
    targets = {
        "poster": (poster_id, style_of(poster_id)),
        "body": (body_id, style_of(body_id)),
        "html": (html_id, style_of(html_id)),
    }
    session.send("Emulation.setScriptExecutionDisabled", {"value": True})
    return session, targets


def _apply_thumbnail_transform_cdp(session, targets: dict, scale: float) -> None:
    """Apply the thumbnail-only style while page JavaScript stays disabled."""
    declarations = (
        (
            "poster",
            "transform-origin:top left!important;"
            f"transform:scale({scale})!important;",
        ),
        ("body", "margin:0!important;"),
        ("html", "margin:0!important;"),
    )
    # A minimal document can legitimately fall back to <body> as its poster.
    # Coalesce by CDP node id so the later body-margin declaration extends the
    # transform instead of rebuilding the same node from its original style and
    # accidentally erasing that transform.
    updates: dict[int, tuple[str, list[str]]] = {}
    for key, declaration in declarations:
        node_id, original = targets[key]
        if node_id not in updates:
            updates[node_id] = (str(original), [])
        updates[node_id][1].append(declaration)
    for node_id, (original, additions) in updates.items():
        prefix = original.strip()
        if prefix and not prefix.endswith(";"):
            prefix += ";"
        session.send(
            "DOM.setAttributeValue",
            {
                "nodeId": node_id,
                "name": "style",
                "value": prefix + "".join(additions),
            },
        )


def _bake_scan_suppress_into_html(html_path: Path) -> bool:
    """Persist a render-time Scan-to-Read suppression into poster.html.

    When the aspect-ratio guard (below) decides the Scan-to-Read section is too
    elongated for its little QR + caption (the lone-QR-in-empty-space defect),
    it sets the section `display:none` on the live page before the expand pass,
    so the column reflows and the expand pass refills the freed space into the
    flex-grow neighbours. To keep the editable poster.html, its `D` overlay, and
    the downstream html2pptx read consistent with the rendered PDF/PNG, write the
    same suppression back as one idempotent <style> block (mirrors
    `_bake_expand_into_html`; `display:none !important` wins regardless of block
    position). This generalises the 3col layout's static scan suppression to any
    layout whose scan column came out as elongated as a 3-column even split.
    """
    block = ('<style id="poster-scan-suppress">\n'
             '  .section[data-section="scan-to-read"] { display: none !important; }\n'
             '</style>')
    txt = html_path.read_text(encoding="utf-8")
    txt, _ = _strip_derived_style_block(txt, "poster-scan-suppress")
    txt = _append_style_at_end(txt, block)
    html_path.write_text(txt, encoding="utf-8")
    return True


def _remove_scan_suppress_from_html(html_path: Path) -> bool:
    """Remove the optional scan mutation after any durability uncertainty."""
    original = html_path.read_text(encoding="utf-8")
    text, count = _strip_derived_style_block(
        original, "poster-scan-suppress"
    )
    if not count:
        return False
    html_path.write_text(text, encoding="utf-8")
    return True


def _autopack_header_logos(html_path: Path) -> None:
    """Step 5.9 auto-run: pack the header institution logos so they FILL their
    zone (multi-row, grown to fit) instead of one tiny row. This is a manual
    step in the docs that the agent routinely skips, so run it here right before
    rendering. Soft: any failure just leaves the raw logos and never blocks the
    render (best-effort, like the render-time expand pass). A non-zero fitter
    exit is still surfaced as a warning so the render log distinguishes
    "attempted" from "successfully packed"."""
    import subprocess
    fit = Path(__file__).resolve().parent.parent / "references" / "fit_logos.py"
    if not fit.exists():
        return
    try:
        r = subprocess.run([sys.executable, str(fit), "--poster", str(html_path)],
                           capture_output=True, text=True, timeout=180)
        for line in (r.stdout or "").splitlines():
            if "baked" in line or "fit_logos" in line:
                print(f"[render_preview] {line.strip()}")
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "no diagnostic output").strip()
            _eprint(
                f"[render_preview] WARN: fit_logos auto-pack exited "
                f"with status {r.returncode}: {ascii_safe(detail)}"
            )
    except Exception as e:                       # noqa: BLE001 -- soft, never block render
        _eprint(f"[render_preview] fit_logos auto-pack skipped ({e})")


def _render_staged(
    args: argparse.Namespace,
    html_path: Path,
    pdf_path: Path,
    png_path: Path,
) -> int:
    """Render a disposable HTML working copy into staged artifacts.

    ``html_path`` is deliberately not the user's deliverable.  Every renderer
    mutation (font freeze, logo fitting, stale-style removal, and the fresh
    derived bake) lands on this adjacent working copy.  The caller promotes it
    only after both staged exports have completed successfully.
    """
    legacy_figure_floor_compat = (
        os.environ.get(_LEGACY_FIGURE_FLOOR_ENV, "").strip()
        == _LEGACY_FIGURE_FLOOR_TOKEN
    )
    enforce_figure_floor = not legacy_figure_floor_compat
    figure_policy_label = (
        "the >=90% minimum and <=1.01 overflow research-figure contracts"
        if enforce_figure_floor
        else (
            "the <=1.01 research-figure overflow contract under the explicit "
            "legacy minimum-only exception"
        )
    )
    if legacy_figure_floor_compat:
        _eprint(
            "[render_preview] LEGACY COMPAT: preserving an immutable "
            "historical source that predates the >=90% research-figure "
            "minimum; the minimum-only gate is disabled for this render, "
            "while intrinsic geometry and <=1.01 overflow remain strict."
        )

    # Geometry/expand/scan state is renderer-derived final output.  Recover the
    # authored natural document on every explicit rerender; otherwise the prior
    # frozen snapshot (or an old row-gap bake) would feed back into itself.
    _strip_durable_geometry_snapshot(html_path)
    _strip_derived_render_styles(html_path)
    _ensure_unscaled_layout_timer_guard(html_path)
    _sync_bundled_fonts(html_path)
    _autopack_header_logos(html_path)   # Step 5.9, auto-run so it's never skipped

    resolved = _canvas.resolve_canvas(
        html_path, args.canvas, label="[render_preview]"
    )
    if resolved is None:
        _eprint(
            "ERROR: could not find `@page { size: <W> <H> }` in HTML. "
            "Add an @page rule (units: in/mm/cm/pt) or pass "
            "`--canvas <W>x<H>in` / `--canvas 'A0 portrait'`. "
            "Refusing to silently fall back."
        )
        return 2
    canvas, viewport = resolved
    w_in, h_in = canvas

    pw = import_playwright()
    if pw is None:
        return 2
    sync_playwright, PWTimeoutError = pw

    with sync_playwright() as p_:
        browser = p_.chromium.launch()
        (
            _source_ctx,
            _source_page,
            _source_navigated,
            _source_settled,
        ) = _open_fresh_durable_page(
            browser,
            viewport,
            html_path,
            timeout_ms=args.mathjax_timeout_ms,
            playwright_timeout_error=PWTimeoutError,
            label="pre-font-freeze source baseline",
        )
        if not _source_navigated:
            _eprint(
                "[render_preview] ERROR: source layout did not complete "
                "navigation; refusing to mutate a render transaction without "
                "a geometry baseline."
            )
            _source_ctx.close()
            browser.close()
            return 2
        if not _source_settled:
            _eprint(
                "[render_preview] WARN: source layout did not fully settle; "
                "continuing on the renderer's soft path with all optional "
                "expand/scan mutations disabled."
            )
        try:
            _source_baseline = _capture_expand_snapshot(_source_page)
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not capture the source layout "
                f"baseline: {ascii_safe(exc)}"
            )
            _source_ctx.close()
            browser.close()
            return 2
        _source_ctx.close()

        # Font freezing is the portability mutation under test.  It runs only
        # after a settled source snapshot exists, and the final cold page must
        # prove that section/media geometry and text wrapping survived it.
        freeze_system_font_webfont(html_path)
        ctx, page = _new_print_context_page(browser, viewport)
        # Soft path: a hung CDN (blocked MathJax fetch, unreachable
        # web font) must not hard-crash render. Playwright's default
        # `page.goto` waits for `load` (all subresources), which can
        # block ~30s on a single blocked CDN. settle_page below has
        # its own bounded waits; let it surface MathJax issues as
        # warnings, not tracebacks.
        try:
            page.goto(html_path.as_uri(), timeout=args.mathjax_timeout_ms)
        except PWTimeoutError:
            _eprint(
                f"[render_preview] WARN: page.goto did not reach `load` "
                f"within {args.mathjax_timeout_ms} ms; continuing with "
                f"whatever has loaded (a CDN or external resource is "
                f"likely blocked)."
            )
        try:
            page.wait_for_load_state(
                "networkidle", timeout=args.mathjax_timeout_ms,
            )
        except PWTimeoutError:
            _eprint(
                f"[render_preview] WARN: network never went idle within "
                f"{args.mathjax_timeout_ms} ms; continuing with whatever "
                f"loaded (likely a slow/blocked external resource)."
            )

        _initial_images_ready = _wait_for_images_decoded(
            page,
            timeout_ms=args.mathjax_timeout_ms,
            label="initial load",
        )

        _initial_settle_complete = bool(
            _source_settled and _initial_images_ready
        )
        try:
            settle = _render.settle_page(
                page,
                mathjax_timeout_ms=args.mathjax_timeout_ms,
                settle_ms=1500,
            )
        except Exception as exc:
            # Rendering is a soft path.  Navigation succeeded, so retain the
            # natural page and reject only renderer-owned optional mutations.
            _initial_settle_complete = False
            _eprint(
                "[render_preview] WARN: initial settle failed: "
                f"{ascii_safe(exc)}; continuing without optional expand/scan "
                "mutations."
            )
        else:
            # Render is a soft path: warn but continue, even on MathJax
            # problems — the user can SEE raw $...$ on the resulting PDF.
            if settle.mathjax_status == "timeout":
                _initial_settle_complete = False
                _eprint(
                    f"[render_preview] WARN: MathJax typeset timed out "
                    f"after {args.mathjax_timeout_ms} ms."
                )
            elif settle.mathjax_status == "error":
                _initial_settle_complete = False
                _eprint(
                    f"[render_preview] WARN: MathJax error: "
                    f"{ascii_safe(settle.mathjax_error)}"
                )
            if settle.mathjax_intended and settle.tex_without_mathjax:
                _initial_settle_complete = False
                _eprint(
                    "[render_preview] WARN: page intended to load MathJax "
                    "but no <mjx-container> rendered -- MathJax may have "
                    "failed to load. PDF will show raw $...$ text."
                )

        # Prove the portable-font mutation itself preserves the complete
        # authored layout before Scan-to-Read suppression is allowed to reflow
        # one column.  Without this strict pre-scan gate, the later intentional
        # reflow exception could also conceal unrelated font wrapping changes
        # in Headline Numbers, Takeaway, or another sibling card.
        if _initial_settle_complete:
            try:
                _pre_scan_source_geometry_failures = (
                    _validate_source_geometry(page, _source_baseline)
                )
            except Exception as exc:
                _eprint(
                    "[render_preview] ERROR: could not validate portable-font "
                    "geometry before optional Scan-to-Read suppression: "
                    f"{ascii_safe(exc)}"
                )
                browser.close()
                return 2
            if _pre_scan_source_geometry_failures:
                _eprint(
                    "[render_preview] ERROR: portable-font mutation changed "
                    "source geometry or text wrapping before optional "
                    "Scan-to-Read suppression: "
                    + ascii_safe(
                        "; ".join(_pre_scan_source_geometry_failures)
                    )
                )
                browser.close()
                return 2

        # Scan-to-Read aspect guard (runs BEFORE the expand pass). A scan section
        # that came out wide and flat -- its own width many times its own height
        # -- holds just a small QR (and maybe a heading) marooned in horizontal
        # empty space. Poster #8 is the worst case: a grid column that blew out
        # to ~2x width (a wide unbreakable child forced the track wider) left the
        # directory scan variant a 730x156 px band with one 110 px QR filling
        # ~15% of the width. The metric is the section's OWN aspect ratio
        # (width / height) -- NOT relative to the canvas -- mirroring the 3col
        # layout's static suppression ("far more horizontal room than its little
        # content fills"). When width/height exceeds the threshold, hide the
        # section now so the column reflows and the expand pass below refills the
        # freed height into the flex-grow neighbours. Defensive: a scan section
        # that is the ONLY section in its column is never removed (would blank a
        # whole column). Tunable via POSTER_SCAN_SUPPRESS_WH (default 3.8 -- in
        # the v2 benchmark the offending #8 reads ~4.7 while well-filled scan
        # sections sit at 1.2-3.3; 0 disables).
        _scan_suppressed = False
        try:
            _scan_wh = float(os.environ.get("POSTER_SCAN_SUPPRESS_WH", "3.8"))
        except Exception:
            _scan_wh = 3.8
        if _scan_wh > 0 and _initial_settle_complete:
            try:
                _sv = page.evaluate(
                    """(T) => {
                      const sec = document.querySelector('.section[data-section="scan-to-read"]');
                      if (!sec) return {act:false, why:'none'};
                      const r = sec.getBoundingClientRect();
                      if (r.width < 4 || r.height < 4) return {act:false, why:'hidden'};
                      const col = sec.closest('.col');
                      if (col && col.querySelectorAll('.section').length <= 1)
                        return {act:false, why:'alone'};        // never blank a whole column
                      const wh = r.width / r.height;            // the section's OWN aspect (width / height)
                      if (wh >= T) { sec.style.display = 'none';
                        return {act:true, why:'aspect', wh: wh}; }
                      return {act:false, why:'within', wh: wh};
                    }""",
                    _scan_wh,
                )
                if isinstance(_sv, dict) and _sv.get("wh") is not None:
                    _eprint(
                        "[render_preview] Scan-to-Read aspect (w/h) "
                        f"{round(float(_sv['wh']), 2)} "
                        f"(suppress at >= {_scan_wh}) -> "
                        f"{'SUPPRESSED' if _sv.get('act') else 'kept'}."
                    )
                if isinstance(_sv, dict) and _sv.get("act"):
                    _scan_suppressed = True
                    page.wait_for_timeout(120)          # let the column reflow before the expand pass measures it
            except Exception:
                pass

        # Expand deliverable: stretch each under-filled card's inner content to
        # ~POSTER_EXPAND_THRESHOLD of the card (default 0.98) by growing the
        # row-gaps BETWEEN its rows -- COLUMN bottoms stay aligned. Figure/image
        # cards participate too, but only provisionally: after the rule is baked
        # and the page's on-load figure fitter runs again, a durable validation
        # removes any rule that changes figure dimensions, violates the >=90%
        # minimum when enforced, or exceeds the unconditional <=1.01 overflow
        # ceiling. Two immediate guardrails remain: (a) the slack
        # cap -- never push content past the bottom padding; (b) the
        # PARENT-height revert -- if
        # growing the gap changes the card's CONTAINER (column/grid) height, undo
        # it. (b) is deliberately on the parent, not the card: a flex:1 grow card
        # absorbs the fill inside its column (column height unchanged -> bottoms
        # stay put -> we DO fill that trailing space, which is the whole point),
        # whereas a grid/content card whose fill would grow its container (pushing
        # the fixed-canvas layout) is reverted. This is a render-time "expand"
        # pass separate from the staged-fill loop's FILL gate (POSTER_FULL_THRESHOLD,
        # default 0.90): the loop still measures the natural top-aligned layout via
        # check_poster.py so the fill gate stays correct; this only makes the final
        # deliverable read fuller. Configurable: POSTER_EXPAND_THRESHOLD (0 disables).
        try:
            _expand_t = float(os.environ.get("POSTER_EXPAND_THRESHOLD", "0.98"))
        except Exception:
            _expand_t = 0.98
        _expand_records = []
        _expand_baseline = {}
        _expand_failed = False
        _baked = []
        if _expand_t > 0 and _initial_settle_complete:
            try:
                # This is the one natural-layout capture. It completes before
                # the proposal evaluator is allowed to mutate any row-gap.
                _expand_baseline = _capture_expand_snapshot(page)
                _expand_result = page.evaluate(
                    """({T, baseline}) => {
                      // Phase 1 is strictly read-only.  Every proposal and the
                      // target gap is collected before a single row-gap changes,
                      // so DOM order cannot make later proposals depend on an
                      // earlier candidate.
                      const sectionNodes = Array.from(
                        document.querySelectorAll('.section[data-section]')
                      );
                      const sidCounts = new Map();
                      sectionNodes.forEach(sec => {
                        const sid = sec.getAttribute('data-section') || '';
                        sidCounts.set(sid, (sidCounts.get(sid) || 0) + 1);
                      });
                      const proposals = [];
                      sectionNodes.forEach((sec, sectionIndex) => {
                        const sid = sec.getAttribute('data-section') || '';
                        // One CSS selector cannot persist two different live
                        // element decisions. Fail closed on malformed duplicate
                        // ids rather than baking an ambiguous rule.
                        if (!sid || sidCounts.get(sid) !== 1) return;
                        const kids = Array.from(sec.children).filter(k => k.classList
                          && !k.classList.contains('listen-btn')
                          && !k.classList.contains('dbg-badge')
                          && !k.classList.contains('dbg-bbox'));
                        if (kids.length < 2) return;
                        const oldInlineGap = sec.style.getPropertyValue('row-gap');
                        const oldInlinePriority = sec.style.getPropertyPriority('row-gap');
                        const authoredInlineImportant = [
                          'row-gap', 'gap', 'grid-row-gap'
                        ].some(prop => sec.style.getPropertyPriority(prop) === 'important');
                        if (authoredInlineImportant) return;
                        const sb = sec.getBoundingClientRect();
                        const bot = Math.max.apply(null,
                          kids.map(k => k.getBoundingClientRect().bottom));
                        const cur = (bot - sb.top) / sb.height;
                        if (cur >= T) return;
                        const cs = getComputedStyle(sec);
                        const padBot = parseFloat(cs.paddingBottom) || 0;
                        const scale = sec.offsetHeight ? sb.height / sec.offsetHeight : 1;
                        const slack = (sb.bottom - padBot * scale) - bot;
                        if (slack <= 1) return;
                        const add = Math.min((T - cur) * sb.height, slack);
                        const per = add / (kids.length - 1);
                        const curGap = parseFloat(cs.rowGap) || 0;
                        proposals.push({
                          sec:sec, sid:sid,
                          scope:baseline.sections[sectionIndex].parentKey,
                          gap:(curGap + per) + 'px',
                          parent:sec.parentElement,
                          oldInlineGap:oldInlineGap,
                          oldInlinePriority:oldInlinePriority,
                        });
                      });

                      // Phase 2 mutates only after every natural baseline and
                      // target gap is frozen.  The immediate parent guard stays
                      // local to each mutation; the durable global validator
                      // below catches sibling and cross-card collateral changes.
                      const records = [];
                      if (proposals.length)
                        document.documentElement.dataset.posterExpandEphemeral = '1';
                      for (const proposal of proposals) {
                        const par = proposal.parent;
                        const liveParentH = par ? par.getBoundingClientRect().height : 0;
                        proposal.sec.style.setProperty(
                          'row-gap', proposal.gap, 'important'
                        );
                        if (par && Math.abs(
                            par.getBoundingClientRect().height - liveParentH
                        ) > 1) {
                          if (proposal.oldInlineGap)
                            proposal.sec.style.setProperty(
                              'row-gap', proposal.oldInlineGap,
                              proposal.oldInlinePriority,
                            );
                          else
                            proposal.sec.style.removeProperty('row-gap');
                          continue;
                        }
                        records.push({
                          sid:proposal.sid,
                          scope:proposal.scope,
                          gap:getComputedStyle(proposal.sec).rowGap || '0px',
                        });
                      }
                      if (!records.length)
                        delete document.documentElement.dataset.posterExpandEphemeral;
                      return records;
                    }""",
                    {"T": _expand_t, "baseline": _expand_baseline},
                )
                page.wait_for_timeout(150)
                # Persist the expand into the deliverable html so poster.html,
                # its `D` overlay, the PDF/PNG, and the downstream html2pptx read
                # all show the same expanded layout (not the pre-expand one).
                if not isinstance(_expand_result, list):
                    raise RuntimeError("expand pass returned malformed data")
                _expand_records = list(_expand_result)
                if _expand_records and not _expand_baseline:
                    raise RuntimeError("expand pass omitted its natural baseline")
                _baked = [
                    [record["sid"], record["gap"]]
                    for record in _expand_records
                ]
            except Exception as exc:
                _expand_failed = True
                _expand_records = []
                _expand_baseline = {}
                _baked = []
                _eprint(
                    "[render_preview] WARN: provisional expand failed: "
                    f"{ascii_safe(exc)}; reloading the natural persisted HTML."
                )
        elif _expand_t > 0:
            _eprint(
                "[render_preview] WARN: render-time expand skipped because "
                "the natural page did not fully settle."
            )

        # Persist renderer-derived state in cascade order: scan first, expand
        # LAST.  The latter must follow autofit and every other author style so
        # the computed gap captured above is still the winner after reload.
        _html_mutated = False
        if _scan_suppressed:
            _html_mutated = _bake_scan_suppress_into_html(html_path)
        if _baked:
            _html_mutated = _bake_expand_into_html(html_path, _baked) or _html_mutated

        # Render artifacts only from the durable HTML.  Provisional rules are
        # monotonically pruned by original parent scope until the reloaded page
        # matches the complete natural geometry/media snapshot.  A clean state
        # must survive one extra identical-rule reload before capture; this
        # catches load-count-dependent fitters and late cascade overrides.
        _survivors = list(_expand_records)
        _had_provisional_expand = bool(_survivors)
        _durable_navigated = True
        _durable_settled = True
        if _html_mutated or _expand_failed:
            _durable_navigated, _durable_settled = (
                _reload_and_settle_after_bake(
                    page,
                    timeout_ms=args.mathjax_timeout_ms,
                    playwright_timeout_error=PWTimeoutError,
                    label="post-bake reload",
                )
            )
        if not _durable_navigated:
            _eprint(
                "[render_preview] ERROR: persisted HTML could not complete "
                "post-bake navigation; refusing to capture a live-only DOM."
            )
            browser.close()
            return 2
        if not _durable_settled and _scan_suppressed:
            _eprint(
                "[render_preview] scan suppression rollback: durable settle "
                "incomplete."
            )
            _remove_scan_suppress_from_html(html_path)
            _scan_suppressed = False
            _durable_navigated, _durable_settled = (
                _reload_and_settle_after_bake(
                    page,
                    timeout_ms=args.mathjax_timeout_ms,
                    playwright_timeout_error=PWTimeoutError,
                    label="post-scan rollback reload",
                )
            )
        if not _durable_navigated:
            _eprint(
                "[render_preview] ERROR: natural persisted HTML could not "
                "complete navigation after optional scan rollback."
            )
            browser.close()
            return 2

        if _had_provisional_expand:
            _clean_validations = 0
            while True:
                if not _durable_navigated or not _durable_settled:
                    _state_reason = (
                        "durable navigation incomplete"
                        if not _durable_navigated
                        else "durable settle incomplete"
                    )
                    _validation = {
                        "failures": [
                            {
                                "sid": str(record.get("sid", "")),
                                "reasons": [_state_reason],
                            }
                            for record in _survivors
                        ],
                        "snapshotOk": False,
                        "snapshotReasons": [_state_reason],
                    }
                else:
                    try:
                        _validation = _validate_durable_expand(
                            page,
                            _survivors,
                            _expand_baseline,
                            enforce_figure_floor=enforce_figure_floor,
                        )
                    except Exception as exc:
                        _reason = f"durable validation failed: {ascii_safe(exc)}"
                        _validation = {
                            "failures": [
                                {
                                    "sid": str(record.get("sid", "")),
                                    "reasons": [_reason],
                                }
                                for record in _survivors
                            ],
                            "snapshotOk": False,
                            "snapshotReasons": [_reason],
                        }

                _failures = list(_validation.get("failures") or [])
                _snapshot_ok = bool(_validation.get("snapshotOk"))
                if not _failures and _snapshot_ok:
                    if _clean_validations >= 1:
                        break
                    _clean_validations += 1
                    _durable_navigated, _durable_settled = (
                        _reload_and_settle_after_bake(
                            page,
                            timeout_ms=args.mathjax_timeout_ms,
                            playwright_timeout_error=PWTimeoutError,
                            label="post-expand confirmation reload",
                        )
                    )
                    continue

                if _survivors:
                    _failed_sids = {
                        str(failure.get("sid", ""))
                        for failure in _failures
                        if str(failure.get("sid", ""))
                    }
                    _known_sids = {
                        str(record.get("sid", "")) for record in _survivors
                    }
                    # Unknown/unattributed validation output cannot safely pick
                    # one rule.  Remove all remaining provisional rules.
                    if (not _failed_sids
                            or not _failed_sids.issubset(_known_sids)):
                        _failed_sids = set(_known_sids)
                    _next_survivors = [
                        record for record in _survivors
                        if str(record.get("sid", "")) not in _failed_sids
                    ]
                    if len(_next_survivors) >= len(_survivors):
                        _failed_sids = set(_known_sids)
                        _next_survivors = []
                    for failure in _failures:
                        sid = str(failure.get("sid", ""))
                        if sid not in _failed_sids:
                            continue
                        reasons = "; ".join(
                            str(reason)
                            for reason in (failure.get("reasons") or [])
                        ) or "durable validation failed"
                        _eprint(
                            f"[render_preview] expand rollback {sid!r}: "
                            f"{ascii_safe(reasons)}"
                        )
                    if not _failures:
                        reasons = "; ".join(
                            str(reason) for reason in
                            (_validation.get("snapshotReasons") or [])
                        ) or "unattributed durable snapshot mismatch"
                        _eprint(
                            "[render_preview] expand rollback (all rules): "
                            f"{ascii_safe(reasons)}"
                        )
                    _survivors = _next_survivors
                    _bake_expand_into_html(
                        html_path,
                        [
                            [record["sid"], record["gap"]]
                            for record in _survivors
                        ],
                    )
                    _durable_navigated, _durable_settled = (
                        _reload_and_settle_after_bake(
                            page,
                            timeout_ms=args.mathjax_timeout_ms,
                            playwright_timeout_error=PWTimeoutError,
                            label="post-expand rollback reload",
                        )
                    )
                    _clean_validations = 0
                    continue

                # All optional rules are already gone.  If the natural page
                # navigated but a soft image/MathJax settle did not complete,
                # the natural page remains renderable; the later independent
                # warm/cold RGBA equality gate still protects durability.  A
                # navigation failure or a settled geometry mismatch remains
                # fatal.
                if not _durable_navigated:
                    _eprint(
                        "[render_preview] ERROR: natural HTML did not complete "
                        "navigation after expand rollback."
                    )
                    browser.close()
                    return 2
                if not _durable_settled:
                    _eprint(
                        "[render_preview] WARN: natural HTML settle remained "
                        "incomplete after expand rollback; continuing on the "
                        "soft render path."
                    )
                    break
                _reasons = "; ".join(
                    str(reason) for reason in
                    (_validation.get("snapshotReasons") or [])
                ) or "natural durable snapshot mismatch"
                _eprint(
                    "[render_preview] ERROR: natural HTML did not restore "
                    f"after expand rollback: {ascii_safe(_reasons)}"
                )
                browser.close()
                return 2

        # Same-context reloads reuse storage, decoded images, and other browser
        # caches.  They are useful for cheaply pruning ordinary cascade/refit
        # failures above, but they do not prove that the baked HTML survives a
        # real standalone open.  Confirm each remaining fixed point in a brand-
        # new BrowserContext.  A rejected candidate is closed; after its parent
        # scope is removed from the bake, the next attempt gets another new
        # context rather than a warmed retry.  The accepted cold page becomes
        # the capture page, so validation and artifacts share one DOM.
        _needs_fresh_confirmation = bool(
            _html_mutated or _expand_failed or _had_provisional_expand
        )
        if _needs_fresh_confirmation:
            _fresh_attempt = 0
            while True:
                _fresh_attempt += 1
                (
                    _fresh_ctx,
                    _fresh_page,
                    _fresh_navigated,
                    _fresh_settled,
                ) = _open_fresh_durable_page(
                    browser,
                    viewport,
                    html_path,
                    timeout_ms=args.mathjax_timeout_ms,
                    playwright_timeout_error=PWTimeoutError,
                    label=(
                        "fresh-context expand confirmation "
                        f"#{_fresh_attempt}"
                    ),
                )
                if (not _fresh_settled and _fresh_navigated
                        and _scan_suppressed):
                    _eprint(
                        "[render_preview] scan suppression rollback: "
                        "fresh-context settle incomplete."
                    )
                    try:
                        _fresh_ctx.close()
                    except Exception:
                        pass
                    _remove_scan_suppress_from_html(html_path)
                    _scan_suppressed = False
                    continue
                if (not _fresh_settled and _fresh_navigated
                        and not _survivors and not _scan_suppressed):
                    # All optional output is gone.  Keep the navigated natural
                    # page on the documented soft path; the independent final
                    # warm/cold pixel gate remains mandatory.
                    _eprint(
                        "[render_preview] WARN: natural fresh-context settle "
                        "incomplete after optional rollback; continuing on "
                        "the soft render path."
                    )
                    _old_ctx = ctx
                    ctx, page = _fresh_ctx, _fresh_page
                    try:
                        _old_ctx.close()
                    except Exception:
                        pass
                    break
                if not _fresh_navigated or not _fresh_settled:
                    _fresh_state_reason = (
                        "fresh-context navigation incomplete"
                        if not _fresh_navigated
                        else "fresh-context settle incomplete"
                    )
                    _fresh_validation = {
                        "failures": [
                            {
                                "sid": str(record.get("sid", "")),
                                "reasons": [_fresh_state_reason],
                            }
                            for record in _survivors
                        ],
                        "snapshotOk": False,
                        "snapshotReasons": [_fresh_state_reason],
                    }
                elif _expand_baseline:
                    try:
                        _fresh_validation = _validate_durable_expand(
                            _fresh_page,
                            _survivors,
                            _expand_baseline,
                            enforce_figure_floor=enforce_figure_floor,
                        )
                    except Exception as exc:
                        _reason = (
                            "fresh-context durable validation failed: "
                            f"{ascii_safe(exc)}"
                        )
                        _fresh_validation = {
                            "failures": [
                                {
                                    "sid": str(record.get("sid", "")),
                                    "reasons": [_reason],
                                }
                                for record in _survivors
                            ],
                            "snapshotOk": False,
                            "snapshotReasons": [_reason],
                        }
                else:
                    # Scan suppression and a failed/no-op provisional pass can
                    # mutate the staged HTML without producing an expand
                    # baseline.  A fully settled one-navigation cold page is
                    # still required, but there is no optional geometry record
                    # to compare or prune.
                    _fresh_validation = {
                        "failures": [],
                        "snapshotOk": True,
                        "snapshotReasons": [],
                    }

                _fresh_failures = list(
                    _fresh_validation.get("failures") or []
                )
                _fresh_snapshot_ok = bool(
                    _fresh_validation.get("snapshotOk")
                )
                if (not _fresh_failures and _fresh_snapshot_ok
                        and _fresh_navigated and _fresh_settled):
                    _old_ctx = ctx
                    ctx, page = _fresh_ctx, _fresh_page
                    try:
                        _old_ctx.close()
                    except Exception:
                        pass
                    break

                try:
                    _fresh_ctx.close()
                except Exception:
                    pass

                if _survivors:
                    _failed_sids = {
                        str(failure.get("sid", ""))
                        for failure in _fresh_failures
                        if str(failure.get("sid", ""))
                    }
                    _known_sids = {
                        str(record.get("sid", "")) for record in _survivors
                    }
                    if (not _failed_sids
                            or not _failed_sids.issubset(_known_sids)):
                        _failed_sids = set(_known_sids)
                    _next_survivors = [
                        record for record in _survivors
                        if str(record.get("sid", "")) not in _failed_sids
                    ]
                    if len(_next_survivors) >= len(_survivors):
                        _failed_sids = set(_known_sids)
                        _next_survivors = []
                    for failure in _fresh_failures:
                        sid = str(failure.get("sid", ""))
                        if sid not in _failed_sids:
                            continue
                        reasons = "; ".join(
                            str(reason)
                            for reason in (failure.get("reasons") or [])
                        ) or "fresh-context durable validation failed"
                        _eprint(
                            f"[render_preview] expand rollback {sid!r}: "
                            f"{ascii_safe(reasons)}"
                        )
                    if not _fresh_failures:
                        reasons = "; ".join(
                            str(reason) for reason in
                            (_fresh_validation.get("snapshotReasons") or [])
                        ) or "unattributed fresh-context snapshot mismatch"
                        _eprint(
                            "[render_preview] expand rollback (all rules): "
                            f"{ascii_safe(reasons)}"
                        )
                    _survivors = _next_survivors
                    _bake_expand_into_html(
                        html_path,
                        [
                            [record["sid"], record["gap"]]
                            for record in _survivors
                        ],
                    )
                    continue

                if _scan_suppressed:
                    _eprint(
                        "[render_preview] scan suppression rollback: "
                        "fresh-context validation did not reach a durable "
                        "fixed point."
                    )
                    _remove_scan_suppress_from_html(html_path)
                    _scan_suppressed = False
                    continue

                _reasons = "; ".join(
                    str(reason) for reason in
                    (_fresh_validation.get("snapshotReasons") or [])
                ) or "natural fresh-context snapshot mismatch"
                _eprint(
                    "[render_preview] ERROR: natural HTML did not survive "
                    "a fresh-context confirmation after expand rollback: "
                    f"{ascii_safe(_reasons)}"
                )
                browser.close()
                return 2

        # If the provisional script itself raised after partially touching the
        # live DOM, the reload above is the rollback.  Verify a live-only marker
        # did not survive and that capture is still on the staged persisted URL.
        try:
            _final_page_state = page.evaluate(
                """() => ({
                  ephemeral:document.documentElement.dataset.posterExpandEphemeral || '',
                  hasExpand:!!document.getElementById('poster-expand-baked'),
                })"""
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not verify final persisted "
                f"HTML before capture: {ascii_safe(exc)}"
            )
            browser.close()
            return 2
        _expected_expand = bool(_survivors)
        if (page.url.split("#", 1)[0] != html_path.as_uri()
                or bool(_final_page_state.get("ephemeral"))
                or bool(_final_page_state.get("hasExpand")) != _expected_expand):
            _eprint(
                "[render_preview] ERROR: final browser page is not the final "
                "persisted expand state; refusing to capture stale HTML."
            )
            browser.close()
            return 2

        try:
            _source_geometry_failures = _validate_source_geometry(
                page,
                _source_baseline,
                allow_scan_reflow=_scan_suppressed,
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not validate final cold page "
                f"against its source geometry: {ascii_safe(exc)}"
            )
            browser.close()
            return 2
        if _source_geometry_failures:
            _eprint(
                "[render_preview] ERROR: portable-font/render mutations "
                "changed source geometry or text wrapping: "
                + ascii_safe("; ".join(_source_geometry_failures))
            )
            browser.close()
            return 2

        try:
            _figure_fill_failures = _validate_final_figure_fill(
                page,
                enforce_minimum=enforce_figure_floor,
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not validate final research "
                f"figure fill: {ascii_safe(exc)}"
            )
            browser.close()
            return 2
        if _figure_fill_failures:
            _eprint(
                "[render_preview] ERROR: final poster violates "
                f"{figure_policy_label}: "
                + ascii_safe("; ".join(_figure_fill_failures))
            )
            browser.close()
            return 2

        # Persist the *actual* final figure geometry, not only the expand CSS.
        # The current page is the accepted warm reference: all image fitters,
        # MathJax, font freezing, logo packing, and expand rollback have already
        # reached their fixed point and passed the active minimum/overflow
        # figure policy.
        # Capture its authored-node attributes, freeze scripts immediately, and
        # take a full-canvas reference screenshot before touching the HTML.
        try:
            _geometry_snapshot = _capture_durable_geometry_snapshot(page)
            _warm_cdp, _warm_style_targets = (
                _capture_style_targets_and_freeze(ctx, page)
            )
            _warm_reference_png = _capture_full_viewport_png(page, viewport)
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not capture/freeze the final "
                "warm geometry reference: "
                f"{ascii_safe(exc)}"
            )
            browser.close()
            return 2

        try:
            _guard_counts = _persist_durable_geometry_snapshot(
                html_path,
                _geometry_snapshot,
                timeout_ms=args.mathjax_timeout_ms,
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not persist the final figure "
                f"geometry snapshot: {ascii_safe(exc)}"
            )
            browser.close()
            return 2

        # A brand-new BrowserContext is the equality oracle.  The final
        # HTML must replay the authored warm fitter once, reassert the saved
        # figure/img styles, publish its frozen/ready markers, preserve source
        # geometry and the active figure policy, then paint the exact same
        # decoded RGBA pixels as the warm reference.  No tolerance or
        # approximate geometry gate can substitute for this comparison.  Only
        # this accepted cold page is subsequently used for PDF and PNG capture.
        (
            _cold_ctx,
            _cold_page,
            _cold_navigated,
            _cold_settled,
        ) = _open_fresh_durable_page(
            browser,
            viewport,
            html_path,
            timeout_ms=args.mathjax_timeout_ms,
            playwright_timeout_error=PWTimeoutError,
            label="frozen-geometry cold confirmation",
        )
        if not _cold_navigated:
            _eprint(
                "[render_preview] ERROR: frozen-geometry HTML did not "
                "complete navigation in a brand-new BrowserContext; refusing "
                "promotion."
            )
            _cold_ctx.close()
            browser.close()
            return 2
        if not _cold_settled:
            _eprint(
                "[render_preview] WARN: frozen-geometry cold page did not "
                "fully settle; continuing on the soft render path because "
                "the durable snapshot and exact warm/cold RGBA gates remain "
                "mandatory."
            )
        if not _wait_for_installed_geometry_snapshot(
            _cold_page,
            timeout_ms=args.mathjax_timeout_ms,
        ):
            _eprint(
                "[render_preview] ERROR: frozen-geometry cold page did not "
                "complete its warm-fit-then-restore handshake; refusing "
                "promotion."
            )
            _cold_ctx.close()
            browser.close()
            return 2
        try:
            _snapshot_failures = _validate_installed_geometry_snapshot(
                _cold_page,
                _geometry_snapshot,
            )
            _cold_source_geometry_failures = _validate_source_geometry(
                _cold_page,
                _source_baseline,
                allow_scan_reflow=_scan_suppressed,
            )
            _cold_figure_fill_failures = _validate_final_figure_fill(
                _cold_page,
                enforce_minimum=enforce_figure_floor,
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: frozen-geometry cold validation "
                f"failed: {ascii_safe(exc)}"
            )
            _cold_ctx.close()
            browser.close()
            return 2
        if _snapshot_failures:
            _eprint(
                "[render_preview] ERROR: frozen-geometry snapshot was not "
                "installed exactly: "
                + ascii_safe("; ".join(_snapshot_failures))
            )
            _cold_ctx.close()
            browser.close()
            return 2
        if _cold_source_geometry_failures:
            _eprint(
                "[render_preview] ERROR: frozen-geometry cold page changed "
                "source geometry or text wrapping: "
                + ascii_safe("; ".join(_cold_source_geometry_failures))
            )
            _cold_ctx.close()
            browser.close()
            return 2
        if _cold_figure_fill_failures:
            _eprint(
                "[render_preview] ERROR: frozen-geometry cold page violates "
                f"{figure_policy_label}: "
                + ascii_safe("; ".join(_cold_figure_fill_failures))
            )
            _cold_ctx.close()
            browser.close()
            return 2

        try:
            _capture_cdp, _capture_style_targets = (
                _capture_style_targets_and_freeze(_cold_ctx, _cold_page)
            )
            _cold_candidate_png = _capture_full_viewport_png(
                _cold_page,
                viewport,
            )
            _pixels_equal, _pixel_detail = _compare_decoded_rgba(
                _warm_reference_png,
                _cold_candidate_png,
            )
        except Exception as exc:
            _eprint(
                "[render_preview] ERROR: could not run the warm/cold decoded "
                f"RGBA pixel gate: {ascii_safe(exc)}"
            )
            _cold_ctx.close()
            browser.close()
            return 2
        if not _pixels_equal:
            _eprint(
                "[render_preview] ERROR: frozen-geometry cold page is not "
                "pixel-identical to the final warm DOM: "
                f"{ascii_safe(_pixel_detail)}"
            )
            _cold_ctx.close()
            browser.close()
            return 2

        _eprint(
            "[render_preview] frozen geometry persisted "
            f"(fit guards={_guard_counts.get('fit', 0)}, "
            f"fitAll guards={_guard_counts.get('fitAll', 0)}); "
            f"warm/cold pixel gate PASS: {ascii_safe(_pixel_detail)}."
        )
        _warm_ctx = ctx
        ctx, page = _cold_ctx, _cold_page
        try:
            _warm_ctx.close()
        except Exception:
            pass

        # ---- PDF: exact poster size, print-emulated ----
        pdf_scale = _pdf_content_scale(canvas, viewport)
        if pdf_scale < 0.999999:
            _eprint(
                "[render_preview] fractional canvas rounding: PDF content "
                f"scale={pdf_scale:.6f} to prevent a blank trailing page"
            )
        page.pdf(
            path=str(pdf_path),
            width=f"{w_in}in",
            height=f"{h_in}in",
            scale=pdf_scale,
            print_background=True,
            margin={"top": "0", "bottom": "0",
                    "left": "0", "right": "0"},
        )

        # ---- PNG: scaled thumbnail of `.poster` (or document body) ----
        # IMPORTANT: do NOT resize the viewport for the screenshot. The
        # poster CSS uses `width: min(100vw, calc(100vh * 5 / 3))`, so a
        # viewport change retriggers reflow and the scaled poster ends up
        # occupying only a fraction of the captured area. Instead, keep
        # the print viewport, apply the scale transform, and `clip` the
        # screenshot to the scaled region.
        s = args.thumb_scale
        _apply_thumbnail_transform_cdp(
            _capture_cdp,
            _capture_style_targets,
            s,
        )
        thumb_w = int(round(w_in * 96 * s))
        thumb_h = int(round(h_in * 96 * s))
        page.screenshot(
            path=str(png_path),
            full_page=False,
            clip={"x": 0, "y": 0,
                  "width": thumb_w, "height": thumb_h},
        )

        browser.close()

    return 0


def _temporary_path(
    parent: Path,
    *,
    prefix: str,
    suffix: str,
    mode: int | None = None,
) -> Path:
    """Reserve a unique adjacent path suitable for Chromium or an HTML copy.

    ``mkstemp`` deliberately creates private ``0600`` files.  That is right for
    rollback backups, but HTML/PDF/PNG deliverables are public bundle assets.
    Their intended mode must be applied to the *staged* inode before promotion
    so permissions are committed atomically with the file contents.
    """
    fd, raw = tempfile.mkstemp(dir=parent, prefix=prefix, suffix=suffix)
    os.close(fd)
    path = Path(raw)
    try:
        if mode is not None:
            path.chmod(mode)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _promote_render_transaction(pairs: list[tuple[Path, Path]]) -> None:
    """Promote all staged files, rolling every target back on any failure.

    ``os.replace`` is atomic for each same-directory file.  A small backup
    journal extends that property across the HTML/PDF/PNG set: if any replace
    fails, already-promoted targets are removed and all prior files are put
    back byte-for-byte before the exception escapes.
    """
    targets = [target for _staged, target in pairs]
    if len(set(targets)) != len(targets):
        raise ValueError("HTML, PDF, and PNG output paths must be distinct")

    for staged, target in pairs:
        if not staged.is_file() or staged.stat().st_size <= 0:
            raise RuntimeError(f"staged render output is missing or empty: {staged}")
        if target.exists() and not target.is_file():
            raise IsADirectoryError(f"render output target is not a file: {target}")

    backups: dict[Path, Path] = {}
    promoted: list[Path] = []
    try:
        for staged, target in pairs:
            if target.exists():
                backup = _temporary_path(
                    target.parent,
                    prefix=f".{target.name}.",
                    suffix=".render-backup",
                )
                backup.unlink()
                os.replace(target, backup)
                backups[target] = backup
            os.replace(staged, target)
            promoted.append(target)
    except BaseException:
        rollback_errors: list[str] = []
        for target in reversed(promoted):
            try:
                if target.exists():
                    target.unlink()
            except OSError as exc:
                rollback_errors.append(f"remove {target}: {exc}")
        for target, backup in backups.items():
            try:
                if backup.exists():
                    os.replace(backup, target)
            except OSError as exc:
                rollback_errors.append(f"restore {target}: {exc}")
        if rollback_errors:
            _eprint(
                "[render_preview] ERROR: render promotion rollback was "
                "incomplete: " + "; ".join(rollback_errors)
            )
        raise
    else:
        for backup in backups.values():
            try:
                if backup.exists():
                    backup.unlink()
            except OSError as exc:
                # The committed deliverables are complete; a stale private
                # backup is cleanup debt, not a failed render transaction.
                _eprint(
                    f"[render_preview] WARN: could not remove render backup "
                    f"{ascii_safe(backup)}: {ascii_safe(exc)}"
                )


def main() -> int:
    args = build_parser().parse_args()

    deliverable_html = Path(args.html).resolve()
    if not deliverable_html.is_file():
        _eprint(f"ERROR: HTML not found: {ascii_safe(deliverable_html)}")
        return 2

    pdf_path = (
        Path(args.pdf).resolve() if args.pdf
        else deliverable_html.with_name(deliverable_html.stem + ".pdf")
    )
    png_path = (
        Path(args.png).resolve() if args.png
        else deliverable_html.with_name(deliverable_html.stem + ".png")
    )
    targets = (deliverable_html, pdf_path, png_path)
    if len(set(targets)) != len(targets):
        _eprint("ERROR: HTML, PDF, and PNG output paths must be distinct")
        return 2
    if not pdf_path.parent.is_dir() or not png_path.parent.is_dir():
        _eprint("ERROR: PDF and PNG output directories must already exist")
        return 2

    staged_html = _temporary_path(
        deliverable_html.parent,
        prefix=f".{deliverable_html.name}.",
        suffix=".render.html",
    )
    staged_pdf = _temporary_path(
        pdf_path.parent,
        prefix=f".{pdf_path.name}.",
        suffix=".render.pdf",
        mode=_PUBLIC_ARTIFACT_MODE,
    )
    staged_png = _temporary_path(
        png_path.parent,
        prefix=f".{png_path.name}.",
        suffix=".render.png",
        mode=_PUBLIC_ARTIFACT_MODE,
    )
    staged_paths = (staged_html, staged_pdf, staged_png)
    font_journal: _FontAssetJournal | None = None
    try:
        shutil.copy2(deliverable_html, staged_html)
        # copy2 preserves the source mode (including legacy 0700/0755 poster
        # HTML). Normalize the staged inode before rendering so the final
        # three-file promotion commits content and public-readability together.
        staged_html.chmod(_PUBLIC_ARTIFACT_MODE)
        font_journal = _FontAssetJournal(deliverable_html)
        result = _render_staged(args, staged_html, staged_pdf, staged_png)
        if result != 0:
            return result

        _promote_render_transaction(
            [
                (staged_pdf, pdf_path),
                (staged_png, png_path),
                # HTML is the commit marker: never expose the freshly baked
                # source until both binary artifacts are ready to accompany it.
                (staged_html, deliverable_html),
            ]
        )
        font_journal.commit()
    finally:
        if font_journal is not None and not font_journal.closed:
            active_error = sys.exc_info()[0]
            try:
                font_journal.rollback()
            except Exception as exc:
                _eprint(
                    "[render_preview] ERROR: "
                    f"{ascii_safe(exc)}"
                )
                # Do not hide an exception already in flight, but a failed
                # rollback after a normal non-zero return is itself fatal.
                if active_error is None:
                    raise
        for staged in staged_paths:
            try:
                if staged.exists():
                    staged.unlink()
            except OSError:
                pass

    print(
        f"[render_preview] PDF -> {ascii_safe(pdf_path)}  "
        f"({pdf_path.stat().st_size / 1024:.1f} KB)"
    )
    print(
        f"[render_preview] PNG -> {ascii_safe(png_path)}  "
        f"({png_path.stat().st_size / 1024:.1f} KB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
