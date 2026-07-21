#!/usr/bin/env python3
"""source_figures.py — use the paper's ORIGINAL figure files instead of
cropping them out of the rendered PDF.

The rendered-PDF path (extract_pdf.py + crop_figure.py's LLM bbox-refinement
loop) is the single most expensive stage of paper2assets (~6 min wall + heavy
tokens). When the paper's real, already-clean figure graphics are available we
skip all of that:

  --arxiv <id|url>   download the arXiv source tarball (arxiv.org/e-print/<id>),
                     parse the main .tex for figures in document order, and
                     rasterise each graphic to assets/figures/*.png.
  --images <p|url>…  use figures the user attached / linked directly.

Writes assets/figures/*.png + assets/meta/figures.json in the SAME schema as
extract_pdf.py. Exits 0 if >=1 figure was produced, non-zero otherwise (the
caller then falls back to the crop pipeline). Never raises on a bad source.

Captions / text / metadata are unaffected — they still come from the PDF text
(extract_pdf.py), so run this for figures only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import layout  # noqa: E402

_UA = {"User-Agent": "Mozilla/5.0 (paper2assets source_figures)"}
_RASTER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_VECTOR_EXT = {".pdf", ".eps", ".ps"}
_GRAPHIC_EXT = _RASTER_EXT | _VECTOR_EXT


def _eprint(*a):
    print(*a, file=sys.stderr)


def _arxiv_id(s: str) -> str:
    """Bare arXiv id from an id or a URL (abs/pdf/e-print)."""
    m = re.search(r"(\d{4}\.\d{4,5}(v\d+)?)", s) or re.search(r"([a-z\-]+/\d{7})", s)
    return m.group(1) if m else s.strip()


# ── download + unpack the arXiv source tarball ──────────────────────────────
def download_arxiv_source(aid: str, dest: Path) -> bool:
    url = f"https://arxiv.org/e-print/{aid}"
    tarball = dest / "source.tar.gz"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(tarball, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        _eprint(f"[source_figures] arXiv e-print download failed: {e}")
        return False
    srcdir = dest / "source"
    srcdir.mkdir(exist_ok=True)
    try:                                      # e-print is usually a gzipped tar
        with tarfile.open(tarball, "r:*") as t:
            t.extractall(srcdir, filter="data")
        return True
    except Exception:
        pass
    try:                                      # …sometimes a single gzipped .tex
        with gzip.open(tarball, "rb") as g:
            (srcdir / "main.tex").write_bytes(g.read())
        return True
    except Exception as e:
        _eprint(f"[source_figures] could not unpack e-print: {e}")
        return False


# ── parse .tex figure order (best-effort) ───────────────────────────────────
_FIG_ENV = re.compile(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.S)
_INCL = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_CAP = re.compile(r"\\caption\s*\{", re.S)
_LABEL = re.compile(r"\\label\s*\{([^}]+)\}")
_GPATH = re.compile(r"\\graphicspath\s*\{\s*((?:\{[^}]*\}\s*)+)\}")


def _balanced(s: str, start: int) -> str:
    """Text inside the {...} that begins at s[start] (a '{'), brace-balanced."""
    depth, out = 0, []
    for ch in s[start:]:
        if ch == "{":
            depth += 1
            if depth == 1:
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
    return "".join(out)


def _clean_caption(t: str) -> str:
    t = re.sub(r"\\label\s*\{[^}]*\}", "", t)
    t = re.sub(r"\\[a-zA-Z]+\*?\s*(\[[^\]]*\])?", " ", t)   # strip macros
    t = re.sub(r"[{}]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def find_main_tex(srcdir: Path) -> Path | None:
    texs = list(srcdir.rglob("*.tex"))
    if not texs:
        return None
    for t in texs:                            # prefer the one with \documentclass
        try:
            if "\\documentclass" in t.read_text(errors="ignore"):
                return t
        except Exception:
            continue
    return max(texs, key=lambda p: p.stat().st_size)


def parse_tex_figures(main_tex: Path) -> list[dict]:
    """Ordered [{graphic, caption, label}] from the main .tex (+ its \\inputs)."""
    root = main_tex.parent
    try:
        text = main_tex.read_text(errors="ignore")
    except Exception:
        return []
    # inline simple \input/\include so figure order across files is preserved
    def _inline(txt, depth=0):
        if depth > 3:
            return txt
        def repl(m):
            name = m.group(1).strip()
            for cand in (root / name, root / f"{name}.tex"):
                if cand.exists():
                    return _inline(cand.read_text(errors="ignore"), depth + 1)
            return ""
        return re.sub(r"\\(?:input|include)\s*\{([^}]+)\}", repl, txt)
    text = _inline(text)
    text = text.split("\\appendix")[0]        # main-body only
    gpaths = [""]
    gm = _GPATH.search(text)
    if gm:
        gpaths += re.findall(r"\{([^}]*)\}", gm.group(1))
    out = []
    for env in _FIG_ENV.finditer(text):
        body = env.group(1)
        incls = _INCL.findall(body)
        if not incls:
            continue
        cap = ""
        cm = _CAP.search(body)
        if cm:
            cap = _clean_caption(_balanced(body, cm.end() - 1))
        lm = _LABEL.search(body)
        out.append({"graphics": incls, "caption": cap,
                    "label": lm.group(1) if lm else "", "gpaths": gpaths})
    return out


def _resolve(root: Path, ref: str, gpaths: list[str]) -> Path | None:
    ref = ref.strip().strip('"')
    cands = []
    for gp in gpaths:
        base = (root / gp / ref) if gp else (root / ref)
        cands.append(base)
        if not base.suffix:
            for ext in (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps"):
                cands.append(base.with_suffix(ext))
    for c in cands:
        if c.exists() and c.suffix.lower() in _GRAPHIC_EXT:
            return c
    # last resort: match by stem anywhere in the tree
    stem = Path(ref).stem
    for f in root.rglob("*"):
        if f.stem == stem and f.suffix.lower() in _GRAPHIC_EXT:
            return f
    return None


# ── rasterise any graphic to PNG ────────────────────────────────────────────
def rasterize(src: Path, dst: Path, dpi: int = 432) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except Exception:
        Image = None
    ext = src.suffix.lower()
    try:
        if ext in _RASTER_EXT and Image is not None:
            im = Image.open(src).convert("RGBA")
            im.save(dst)
            return im.size
        pdf = src
        if ext in (".eps", ".ps"):            # convert to pdf first (ghostscript)
            if not shutil.which("ps2pdf") and not shutil.which("gs"):
                return None
            pdf = dst.with_suffix(".src.pdf")
            tool = (["ps2pdf", str(src), str(pdf)] if shutil.which("ps2pdf")
                    else ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
                          f"-sOutputFile={pdf}", str(src)])
            subprocess.run(tool, capture_output=True, timeout=120)
        # vector pdf -> png via pdftoppm (first page).
        # -cropbox: rasterize the CropBox (what \includegraphics shows in the paper),
        # NOT the full MediaBox. Figure PDFs whose CropBox < MediaBox carry leftover /
        # off-canvas content outside the visible crop (e.g. an unused panel parked in
        # the page margin); without -cropbox that junk leaks into the extracted figure.
        prefix = dst.with_suffix("")
        subprocess.run(["pdftoppm", "-cropbox", "-png", "-r", str(dpi), "-singlefile",
                        str(pdf), str(prefix)], capture_output=True, timeout=120, check=True)
        if pdf != src:
            pdf.unlink(missing_ok=True)
        if not dst.exists() and prefix.with_suffix(".png").exists():
            prefix.with_suffix(".png").rename(dst)
        if Image is not None and dst.exists():
            return Image.open(dst).size
        return (0, 0) if dst.exists() else None
    except Exception as e:
        _eprint(f"[source_figures] rasterize failed for {src.name}: {e}")
        return None


def _fetch(ref: str, dest: Path) -> Path | None:
    if re.match(r"https?://", ref):
        try:
            req = urllib.request.Request(ref, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            p = dest / (Path(ref.split("?")[0]).name or "image")
            p.write_bytes(data)
            return p
        except Exception as e:
            _eprint(f"[source_figures] download failed {ref}: {e}")
            return None
    p = Path(ref)
    return p if p.exists() else None


# ── figures.json (extract_pdf schema) ───────────────────────────────────────
def _load_captions(outdir: Path) -> dict[int, dict]:
    try:
        caps = json.loads(layout.meta_file(outdir, "captions").read_text())
    except Exception:
        return {}
    by_num = {}
    # extract_pdf may emit either a list of {label,text,page} dicts or a
    # {"Figure N": "text"} mapping. Handle both.
    if isinstance(caps, dict):
        for label, text in caps.items():
            m = re.search(r"(\d+)", str(label))
            if m and str(label).lower().startswith("figure"):
                by_num[int(m.group(1))] = {"label": label, "text": text, "page": 0}
        return by_num
    for c in caps:
        if not isinstance(c, dict):
            continue
        m = re.search(r"(\d+)", c.get("label", ""))
        if m:
            by_num[int(m.group(1))] = c
    return by_num


def write_figures(entries: list[tuple[Path, str, str]], outdir: Path) -> int:
    """entries = [(rasterised_png, caption, label)] in figure order."""
    figdir = layout.figures_dir(outdir, create=True)
    caps = _load_captions(outdir)
    manifest = []
    for i, (png, caption, label) in enumerate(entries, 1):
        final = figdir / f"figure{i}.png"
        if png.resolve() != final.resolve():
            shutil.move(str(png), str(final))
        try:
            from PIL import Image
            w, h = Image.open(final).size
        except Exception:
            w = h = 0
        clabel = f"Figure {i}"
        cap = caption or (caps.get(i, {}).get("text", ""))
        page = caps.get(i, {}).get("page", 0)
        manifest.append({
            "file": f"{layout.FIGURES}/{final.name}",
            "page": page, "page_width": w, "page_height": h,
            "width": w, "height": h, "column": "full", "num_columns": 1,
            "caption_label": clabel, "caption": cap,
            "caption_candidates": [{"label": clabel, "text": cap}],
            "source": "original",
        })
    layout.meta_file(outdir, "figures", create_parent=True).write_text(json.dumps(manifest, indent=2))
    return len(manifest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--arxiv", help="arXiv id or URL — download the source tarball")
    ap.add_argument("--images", nargs="+", help="figure paths/URLs to use directly")
    ap.add_argument("--dpi", type=int, default=432)
    a = ap.parse_args()
    outdir = Path(a.outdir)
    figdir = layout.figures_dir(outdir, create=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        entries: list[tuple[Path, str, str]] = []

        if a.images:
            for j, ref in enumerate(a.images, 1):
                src = _fetch(ref, tmp)
                if not src:
                    continue
                png = rasterize(src, tmp / f"img{j}.png", a.dpi)
                if png is not None:
                    entries.append((tmp / f"img{j}.png", "", ""))
        elif a.arxiv:
            aid = _arxiv_id(a.arxiv)
            print(f"[source_figures] arXiv {aid}: downloading source…")
            if not download_arxiv_source(aid, tmp):
                _eprint("[source_figures] no source bundle — fall back to crop.")
                return 3
            main_tex = find_main_tex(tmp / "source")
            figs = parse_tex_figures(main_tex) if main_tex else []
            if figs:
                print(f"[source_figures] parsed {len(figs)} figure env(s) from {main_tex.name}")
                for k, fig in enumerate(figs, 1):
                    ref = fig["graphics"][0]        # main graphic (subfigs -> first)
                    src = _resolve((tmp / "source"), ref, fig["gpaths"])
                    if not src:
                        _eprint(f"[source_figures]   fig{k}: could not resolve {ref}")
                        continue
                    if rasterize(src, tmp / f"f{k}.png", a.dpi) is not None:
                        entries.append((tmp / f"f{k}.png", fig["caption"], fig["label"]))
            else:                                    # no tex figures -> all graphics
                gfx = sorted(p for p in (tmp / "source").rglob("*")
                             if p.suffix.lower() in _GRAPHIC_EXT and p.stat().st_size > 2000)
                for k, src in enumerate(gfx, 1):
                    if rasterize(src, tmp / f"f{k}.png", a.dpi) is not None:
                        entries.append((tmp / f"f{k}.png", "", ""))
        else:
            _eprint("[source_figures] need --arxiv or --images")
            return 2

        if not entries:
            _eprint("[source_figures] produced 0 figures — fall back to crop.")
            return 4
        n = write_figures(entries, outdir)

    print(f"[source_figures] wrote {n} original figure(s) -> {figdir}  (crop loop skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
