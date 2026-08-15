#!/usr/bin/env python3
"""Build a poster/slides reel bundle.

The generated viewer uses a sidecar content_alignment.json to connect
paper2poster sections with slide frames. It intentionally leaves the original
poster HTML and PPTX/slide source untouched.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import tarfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reel_downloads import (
    ARCHIVE_META,
    DOWNLOAD_ALL_PACKAGE_VERSION,
    DOWNLOAD_MANIFEST_PATH,
    archive_links,
    build_download_manifest,
    selected_all_package_files,
    selected_files,
    validate_download_manifest,
    write_download_manifest,
)


SCHEMA_VERSION = "paper2any_alignment.v1"
VIEWER_VERSION = "section_modal.v2"
TEMPLATE_VERSION = "attention_golden_section_modal.v1"
LAYOUT_VERSION = "v2-assets"
LOCAL_OPEN_RUNTIME = "srcdoc-poster.v1"
MATHJAX_VERSION = "3.2.2"
MATHJAX_TARBALL_URL = f"https://registry.npmjs.org/mathjax/-/mathjax-{MATHJAX_VERSION}.tgz"
REEL_ROOT = Path(__file__).resolve().parents[3]
KATEX_ASSET_DIR = REEL_ROOT / "skills" / "paper2poster" / "assets" / "katex"

POSTER_DIR = "assets/poster"
SLIDES_DIR = "assets/slides"
BLOG_FIGURES_DIR = "assets/blog/figures"
DOWNLOADS_DIR = "assets/downloads"
UI_DIR = "assets/ui"
REEL_WORDMARK_SRC = (
    Path(__file__).resolve().parents[1] / "assets" / "reel-wordmark.png"
)
MATHJAX_CDN_RE = re.compile(
    r"""(?P<prefix>\bsrc\s*=\s*)(?P<quote>["'])"""
    r"""(?P<url>https?://(?:cdn\.jsdelivr\.net/npm|unpkg\.com)/mathjax@[^"']*/es5/tex-svg\.js)"""
    r"""(?P=quote)""",
    re.IGNORECASE,
)
KATEX_CDN_REPLACEMENTS = (
    (
        re.compile(
            r"https://cdn\.jsdelivr\.net/npm/katex@[^/\"']+/dist/katex\.min\.css"
        ),
        "katex/katex.min.css",
    ),
    (
        re.compile(
            r"https://cdn\.jsdelivr\.net/npm/katex@[^/\"']+/dist/katex\.min\.js"
        ),
        "katex/katex.min.js",
    ),
    (
        re.compile(
            r"https://cdn\.jsdelivr\.net/npm/katex@[^/\"']+/"
            r"dist/contrib/auto-render\.min\.js"
        ),
        "katex/auto-render.min.js",
    ),
)


CANONICAL_DEFAULT_MAP: dict[str, list[int]] = {
    "title": [1],
    "problem": [2],
    "motivation": [1, 2],
    "contribution": [3],
    "method": [4, 5],
    "dataset-benchmark": [6],
    "key-result": [7, 9],
    "ablation-study": [8],
    "headline-numbers": [7, 9],
    "takeaway": [10],
    "failure-modes-limitations": [10],
}

KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("title", ["title", "data_ordering_lever", "opening", "intro"]),
    ("problem", ["problem", "missing_when_dimension", "motivation"]),
    ("motivation", ["data_ordering_lever", "missing_when_dimension", "motivation"]),
    ("contribution", ["scores_become_schedule", "contribution", "schedule"]),
    ("method", ["four_guidances", "str_saw_recipes", "method", "guidance", "recipe"]),
    ("dataset-benchmark", ["evaluation_coverage", "dataset", "benchmark", "evaluation"]),
    ("key-result", ["fineweb_accuracy_lift", "scaling_signal_persists", "result", "accuracy", "scaling"]),
    ("ablation-study", ["guidance_ablations", "ablation"]),
    ("headline-numbers", ["fineweb_accuracy_lift", "scaling_signal_persists", "numbers"]),
    ("takeaway", ["curation_includes_organization", "takeaway", "conclusion"]),
    ("failure-modes-limitations", ["curation_includes_organization", "limitations", "future"]),
]


BLOG_SECTION_KEYWORDS: dict[str, list[str]] = {
    "problem": [
        "problem", "missing axis", "selection", "what data", "order matters",
        "问题", "选好数据", "顺序仍然重要", "数据选择",
    ],
    "motivation": [
        "motivation", "missing axis", "selection", "implementation detail", "learning signal",
        "动机", "顺序", "训练信号", "实现细节",
    ],
    "contribution": [
        "contribution", "reusing scores", "score", "schedule", "organization",
        "贡献", "复用", "样本分数", "训练轨迹", "数据组织",
    ],
    "method": [
        "method", "reusing scores", "boundary", "cyclic", "continuity", "local diversity",
        "方法", "复用已有 score", "构造训练轨迹", "连续性", "局部多样性",
    ],
    "dataset-benchmark": [
        "dataset", "benchmark", "fineweb", "dclm", "corpus", "pre-training",
        "数据集", "基准", "语料", "预训练",
    ],
    "key-result": [
        "result", "accuracy", "fineweb", "1.7b", "50.11", "scaling", "gain",
        "结果", "准确率", "收益", "模型规模",
    ],
    "ablation-study": [
        "ablation", "gradient", "continuity", "spike", "why", "helps",
        "消融", "梯度", "连续性", "为什么有效", "稳定训练",
    ],
    "headline-numbers": [
        "headline", "47.72", "48.92", "49.85", "50.11", "1.7b", "table",
        "关键数字", "数字", "表 1", "平均准确率",
    ],
    "takeaway": [
        "takeaway", "conclusion", "future", "practice", "governance",
        "总结", "实践提示", "数据治理", "未来", "结论",
    ],
}


SECTION_MODAL_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Reel</title>
<meta name="paper2reel-viewer" content="section_modal.v2">
<meta name="paper2reel-template" content="attention_golden_section_modal.v1">
<style>
:root { color-scheme: light; --ink:#172026; --muted:#68737d; --line:#d9e0e6; --accent:#0e6a6e; --hot:#d64a36; --soft:#eef6f5; }
* { box-sizing:border-box; }
html, body { margin:0; height:100%; font-family:Arial, Helvetica, sans-serif; color:var(--ink); background:#f5f7f8; letter-spacing:0; }
body { overflow:hidden; }
.app { width:100vw; min-width:0; height:100vh; display:grid; grid-template-rows:minmax(0,1fr); overflow:hidden; }
body.show-menu .app { grid-template-rows:auto minmax(0,1fr); }
.topbar { width:100%; min-width:0; height:56px; display:none; align-items:center; gap:12px; padding:0 16px; background:rgba(255,255,255,.94); border-bottom:1px solid var(--line); box-shadow:0 10px 34px rgba(18,42,48,.08); overflow:visible; }
body.show-menu .topbar { display:flex; }
.brand { flex:0 0 auto; display:flex; align-items:center; height:40px; padding:0 4px 0 0; margin-right:8px; }
.brand-mark { display:block; width:auto; height:36px; object-fit:contain; }
.downloads { display:flex; align-items:center; gap:7px; flex:0 0 auto; margin-left:auto; height:34px; padding:0 10px 0 7px; border:1px solid rgba(14,106,110,.28); border-radius:999px; background:linear-gradient(180deg,#ffffff,#eef7f6); box-shadow:0 7px 18px rgba(14,106,110,.12); }
.download-icon { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:999px; background:var(--accent); color:#fff; box-shadow:0 5px 12px rgba(14,106,110,.26); }
.download-icon svg { width:14px; height:14px; stroke:currentColor; stroke-width:2.4; fill:none; stroke-linecap:round; stroke-linejoin:round; }
.download-link { color:#17323a; border-radius:5px; padding:4px 4px; font-size:12px; line-height:1; font-weight:700; text-decoration:none; white-space:nowrap; transition:color .14s ease, background .14s ease, transform .14s ease; }
.download-link:hover { color:var(--accent); background:rgba(14,106,110,.09); transform:translateY(-1px); }
.download-sep { color:#89a0a6; font-size:12px; line-height:1; }
.help-top { flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center; gap:6px; height:34px; padding:0 12px 0 9px; border:1px solid #17323a; border-radius:999px; background:#17323a; color:#fff; font-size:12px; line-height:1; font-weight:800; cursor:pointer; box-shadow:0 7px 18px rgba(23,50,58,.14); transition:background .14s ease, transform .14s ease, box-shadow .14s ease; }
.help-top:hover, .help-top:focus-visible { background:#0e6a6e; border-color:#0e6a6e; transform:translateY(-1px); box-shadow:0 9px 20px rgba(14,106,110,.18); outline:none; }
.help-dot { display:inline-flex; align-items:center; justify-content:center; width:18px; height:18px; border-radius:999px; background:#fff; color:#17323a; font-weight:900; font-size:12px; line-height:1; }
.section-rail { display:flex; gap:2px; flex:1 1 0; min-width:0; height:100%; overflow-x:auto; overflow-y:visible; padding:0 6px; align-items:center; justify-content:flex-start; scrollbar-width:none; }
.section-rail::-webkit-scrollbar { display:none; }
.section-rail button, .lang button, .close { border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:6px; padding:6px 9px; font-size:12px; cursor:pointer; }
.section-rail button {
  position:relative;
  flex:0 0 auto;
  min-width:68px;
  max-width:124px;
  height:42px;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:7px;
  padding:0 11px;
  border:0;
  border-radius:14px;
  font-size:12px;
  font-weight:800;
  text-align:left;
  white-space:nowrap;
  line-height:1;
  overflow:hidden;
  transform-origin:center;
  background:transparent;
  color:#3c4d55;
  transition:background .14s ease, color .14s ease, transform .14s ease, box-shadow .14s ease;
}
.section-rail button:hover, .section-rail button:focus-visible {
  z-index:2;
  background:rgba(231,243,241,.78);
  color:#0b5559;
  box-shadow:0 8px 18px rgba(14,106,110,.08);
  transform:translateY(-1px);
  outline:none;
}
.section-rail button.active, .lang button.active { border-color:var(--accent); background:var(--soft); }
.section-rail button.active { color:#0f3b37; background:#e7f3f1; box-shadow:none; }
.section-rail button.active::after { content:''; position:absolute; left:13px; right:13px; bottom:-7px; height:3px; border-radius:999px; background:#0c827b; box-shadow:0 6px 14px rgba(10,123,116,.24); }
.section-index { flex:0 0 auto; color:#6f8581; font-size:10.5px; font-weight:850; }
.section-label { min-width:0; overflow:hidden; text-overflow:ellipsis; }
.section-rail button.active .section-index { color:#0c827b; }
.poster-wrap { position:relative; min-width:0; min-height:0; overflow:hidden; }
.poster-frame { width:100%; height:100%; border:0; display:block; background:#fff; }
.overlay { position:fixed; inset:0; background:rgba(12,20,26,.42); display:none; align-items:center; justify-content:center; padding:34px; z-index:20; }
.overlay.open { display:flex; }
.help-overlay { position:fixed; inset:0; background:rgba(12,20,26,.42); display:none; align-items:center; justify-content:center; padding:28px; z-index:30; }
.help-overlay.open { display:flex; }
.help-card { width:min(620px, 94vw); background:#fff; border-radius:8px; box-shadow:0 30px 90px rgba(0,0,0,.3); padding:22px 24px; }
.help-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
.help-head h2 { margin:0; font-size:20px; }
.help-close { border:1px solid var(--line); background:#fff; border-radius:6px; width:34px; height:32px; cursor:pointer; font-size:18px; }
.shortcut-list { display:grid; gap:10px; margin-top:12px; }
.shortcut-row { display:grid; grid-template-columns:84px 1fr; gap:12px; align-items:start; font-size:14px; color:#34434d; }
.kbd { display:inline-flex; align-items:center; justify-content:center; min-width:32px; height:28px; border:1px solid #cbd5dc; border-bottom-width:2px; border-radius:6px; background:#f6f8fa; color:#172026; font-weight:700; font-family:Arial, Helvetica, sans-serif; }
.help-note { color:var(--muted); font-size:13px; margin:14px 0 0; }
.modal { width:min(1420px, 96vw); height:min(820px, 92vh); background:#fff; border-radius:8px; box-shadow:0 30px 90px rgba(0,0,0,.32); display:grid; grid-template-rows:auto 1fr; overflow:hidden; }
.modal-head { display:flex; align-items:center; gap:12px; padding:12px 16px; border-bottom:1px solid var(--line); }
.modal-title { font-weight:800; font-size:16px; }
.segment { color:var(--muted); font-size:12px; }
.lang { margin-left:auto; display:flex; gap:6px; }
.close { font-size:18px; width:34px; height:32px; padding:0; }
.modal-body { --video-pane-width:60%; display:grid; grid-template-columns:minmax(420px, var(--video-pane-width)) 8px minmax(360px, 1fr); min-height:0; }
.video-pane { background:#101820; padding:16px; display:grid; grid-template-rows:1fr auto; gap:12px; min-width:0; }
.splitter { background:linear-gradient(90deg,#d8e1e8,#f8fafb,#d8e1e8); cursor:col-resize; position:relative; }
.splitter::after { content:''; position:absolute; left:50%; top:50%; width:3px; height:52px; transform:translate(-50%,-50%); border-radius:4px; background:#9aa8b3; }
body.resizing { cursor:col-resize; user-select:none; }
.video-shell { position:relative; min-width:0; min-height:0; display:flex; }
.video-pane video { width:100%; height:100%; max-height:100%; background:#000; object-fit:contain; border-radius:6px; }
.video-pane video::cue { color:#fff; background:rgba(8,14,18,.72); font:600 18px/1.35 Arial, Helvetica, sans-serif; }
.caption-toggle { position:absolute; right:14px; bottom:54px; z-index:3; min-width:46px; height:32px; border:1px solid rgba(255,255,255,.58); border-radius:6px; background:rgba(8,14,18,.62); color:#fff; font-size:12px; font-weight:800; letter-spacing:.04em; cursor:pointer; box-shadow:0 8px 24px rgba(0,0,0,.24); }
.sound-button { position:absolute; left:14px; bottom:54px; z-index:3; min-width:92px; height:32px; border:1px solid rgba(255,255,255,.65); border-radius:6px; background:rgba(14,106,110,.88); color:#fff; font-size:12px; font-weight:800; cursor:pointer; box-shadow:0 8px 24px rgba(0,0,0,.24); display:none; }
.sound-button.show { display:block; }
.caption-toggle:hover, .caption-toggle.active { background:rgba(214,74,54,.9); border-color:rgba(255,255,255,.82); }
.caption-toggle[disabled] { opacity:.45; cursor:not-allowed; background:rgba(8,14,18,.45); }
.thumb-row { display:flex; gap:8px; overflow:auto; min-height:98px; align-items:stretch; }
.thumb-btn { flex:0 0 auto; width:138px; border:2px solid transparent; border-radius:6px; padding:0; background:#ffffff; cursor:pointer; overflow:hidden; text-align:left; color:#172026; }
.thumb-btn:hover, .thumb-btn.active { border-color:var(--hot); }
.thumb-btn img { display:block; width:100%; height:76px; object-fit:cover; background:#fff; }
.thumb-btn span { display:block; padding:4px 7px 6px; font-size:11px; line-height:1.15; color:#34434d; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.blog-pane { padding:0; overflow:auto; min-width:0; background:#f6f8fa; }
.blog-article { max-width:760px; margin:0 auto; padding:28px 34px 36px; background:#fff; min-height:100%; box-shadow:inset 1px 0 0 #edf1f3; }
.blog-title-block { margin:0 0 24px; padding:0 0 18px; border-bottom:1px solid #e3ebf1; }
.blog-kicker { margin:0 0 8px; color:#0e6a6e; font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.blog-title-block h2 { margin:0 0 9px; font-size:28px; line-height:1.18; letter-spacing:0; color:#10243a; }
.blog-title-block p { margin:0; color:#5a6771; font-size:15px; line-height:1.5; }
.blog-article h3 { margin:24px 0 10px; font-size:21px; line-height:1.25; letter-spacing:0; color:#10243a; }
.blog-article h3:first-child { margin-top:0; }
.blog-article p { margin:0 0 13px; font-size:16px; line-height:1.68; color:#26333d; }
.blog-figure { margin:18px 0 22px; padding:12px; border:1px solid #dde6ee; border-radius:8px; background:#fbfdfe; }
.blog-figure img { display:block; width:100%; max-height:430px; object-fit:contain; background:#fff; border-radius:4px; }
.blog-figure figcaption { margin-top:9px; color:#53616b; font-size:13px; line-height:1.45; }
.blog-table { margin:18px 0 22px; border:1px solid #dce5ec; border-radius:8px; overflow:hidden; background:#fff; }
.blog-table figcaption { padding:10px 12px; background:#f2f6f8; color:#53616b; font-size:13px; border-bottom:1px solid #dce5ec; }
.blog-table table { width:100%; border-collapse:collapse; font-size:14px; }
.blog-table th, .blog-table td { padding:10px 12px; border-bottom:1px solid #edf1f3; text-align:left; vertical-align:top; }
.blog-table th { background:#f8fafb; color:#10243a; font-weight:700; }
.blog-table tr:last-child td { border-bottom:0; }
@media (max-width:900px) { .overlay { padding:10px; } .modal-body { grid-template-columns:1fr; grid-template-rows:46vh 0 1fr; } .splitter { display:none; } .topbar { height:52px; gap:7px; padding:0 8px; } .brand { margin-right:2px; } .brand-mark { height:30px; } .section-rail { padding:0 2px; } .section-rail button { min-width:64px; max-width:108px; height:38px; padding:0 9px; gap:6px; font-size:11px; } .section-index { font-size:9.8px; } .downloads { gap:4px; padding-right:7px; } .download-link { font-size:11px; padding:4px 2px; } .help-top { width:36px; padding:0; } .help-top span:not(.help-dot) { display:none; } .blog-article { padding:22px 20px 28px; } }
</style>
</head>
<body data-viewer-version="section_modal.v2" data-template-version="attention_golden_section_modal.v1">
<div class="app">
  <div class="topbar">
    <div class="brand" aria-label="Paper Reel"><img class="brand-mark" src="assets/ui/reel-wordmark.png" alt="Reel"></div>
    <div class="section-rail" id="sectionRail"></div>
    <div class="downloads" id="downloadLinks"></div>
    <button class="help-top" id="helpTopBtn" type="button" aria-label="Open keyboard shortcuts"><span class="help-dot" aria-hidden="true">?</span><span>Help</span></button>
  </div>
  <main class="poster-wrap">
    <iframe id="posterFrame" class="poster-frame" data-src="assets/poster/poster.html"></iframe>
  </main>
</div>
<div class="help-overlay" id="helpOverlay" aria-hidden="true">
  <section class="help-card" role="dialog" aria-modal="true" aria-labelledby="helpTitle">
    <div class="help-head">
      <h2 id="helpTitle">Keyboard Shortcuts</h2>
      <button class="help-close" id="helpCloseBtn" type="button" aria-label="Close help">×</button>
    </div>
    <div class="shortcut-list">
      <div class="shortcut-row"><span class="kbd">a</span><span>Show or hide poster audio controls. Poster Listen buttons keep their original behavior.</span></div>
      <div class="shortcut-row"><span class="kbd">s</span><span>Toggle fullscreen.</span></div>
      <div class="shortcut-row"><span class="kbd">d</span><span>Toggle poster debug overlay and hover opacity control.</span></div>
      <div class="shortcut-row"><span class="kbd">v</span><span>Show or hide the section menu bar.</span></div>
      <div class="shortcut-row"><span class="kbd">h</span><span>Show or hide this shortcut help.</span></div>
      <div class="shortcut-row"><span class="kbd">Esc</span><span>Close help or the video/blog modal.</span></div>
    </div>
    <p class="help-note">Default view intentionally shows only the poster. Double-click a poster section to open the corresponding video clip and blog text; click the title area for the full paper view.</p>
  </section>
</div>
<div class="overlay" id="overlay" aria-hidden="true">
  <section class="modal" role="dialog" aria-modal="true">
    <header class="modal-head">
      <div>
        <div class="modal-title" id="modalTitle">Section</div>
        <div class="segment" id="segmentText"></div>
      </div>
      <div class="lang">
        <button id="langEn" class="active" type="button">EN</button>
        <button id="langCn" type="button">中文</button>
      </div>
      <button class="close" id="closeBtn" type="button" aria-label="Close">×</button>
    </header>
    <div class="modal-body">
      <div class="video-pane">
        <div class="video-shell">
          <video id="sectionVideo" controls preload="metadata"></video>
          <button class="sound-button" id="playSoundBtn" type="button">Play Sound</button>
          <button class="caption-toggle" id="captionToggle" type="button" aria-pressed="false" title="Show subtitles">CC</button>
        </div>
        <div class="thumb-row" id="thumbRow"></div>
      </div>
      <div class="splitter" id="splitter" role="separator" aria-orientation="vertical" aria-label="Resize video and blog panes"></div>
      <article class="blog-pane" id="blogPane"></article>
    </div>
  </section>
</div>
<script>
const VIEWER_VERSION = 'section_modal.v2';
const TEMPLATE_VERSION = 'attention_golden_section_modal.v1';
const ALIGNMENT = {};
const POSTER_HTML = null;
const POSTER_SRC = 'assets/poster/poster.html';
const CAPTION_TEXT = {};
const sections = new Map();
let current = null;
let lang = 'en';
let modalOpenedAt = 0;
let subtitlesEnabled = false;
let videoLoadRequestId = 0;
const rail = document.getElementById('sectionRail');
const overlay = document.getElementById('overlay');
const video = document.getElementById('sectionVideo');
const captionToggle = document.getElementById('captionToggle');
const playSoundBtn = document.getElementById('playSoundBtn');
const blogPane = document.getElementById('blogPane');
const posterFrame = document.getElementById('posterFrame');

function artifactVideo() { return ALIGNMENT.video || (ALIGNMENT.artifacts && ALIGNMENT.artifacts.video) || 'assets/media/video.mp4'; }
function fmtTime(s) { const m = Math.floor((Number(s)||0)/60); const sec = Math.round((Number(s)||0)%60).toString().padStart(2,'0'); return `${m}:${sec}`; }
function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function sectionTitle(sec) { return sec.title || sec.label || sec.id || 'Section'; }
function slideNumber(item) {
  if (typeof item === 'number') return item;
  if (item && item.slide != null) return Number(item.slide);
  if (item && item.slide_index != null) return Number(item.slide_index);
  return 0;
}
function slideSrc(n) {
  const slide = (ALIGNMENT.slides || []).find(s => Number(s.index) === Number(n));
  return slide && slide.src ? slide.src : `assets/slides/slide_${String(n).padStart(2,'0')}.png`;
}
function slideList(sec) {
  if (Array.isArray(sec.slide_indices) && sec.slide_indices.length) return sec.slide_indices.map(Number);
  if (Array.isArray(sec.slides)) return sec.slides.map(slideNumber).filter(Boolean);
  return [];
}
function normalizeBlogBlock(block) {
  if (typeof block === 'string') return {type:'paragraph', text:block};
  return block && typeof block === 'object' ? block : {type:'paragraph', text:String(block || '')};
}
function blogBlocks(sec, code) {
  const blog = sec.blog || {};
  if (blog.blocks && Array.isArray(blog.blocks[code])) return blog.blocks[code].map(normalizeBlogBlock);
  if (Array.isArray(blog[code])) return blog[code].map(normalizeBlogBlock);
  return [];
}
function blogMeta(sec, code) {
  const blog = sec.blog || {};
  return (sec.blog_meta && sec.blog_meta[code]) || (blog.meta && blog.meta[code]) || {};
}
function renderBlock(block) {
  const type = block.type || 'paragraph';
  if (type === 'heading') return `<h3>${escapeHtml(block.text || '')}</h3>`;
  if (type === 'figure') {
    const src = escapeHtml(block.src || block.path || '');
    const cap = escapeHtml(block.caption || '');
    return `<figure class="blog-figure"><img src="${src}" alt="${cap}"><figcaption>${cap}</figcaption></figure>`;
  }
  if (type === 'table') {
    const headers = (block.headers || []).map(h => `<th>${escapeHtml(h)}</th>`).join('');
    const rows = (block.rows || []).map(row => `<tr>${(row || []).map(c => `<td>${escapeHtml(c)}</td>`).join('')}</tr>`).join('');
    const cap = block.caption ? `<figcaption>${escapeHtml(block.caption)}</figcaption>` : '';
    return `<figure class="blog-table">${cap}<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></figure>`;
  }
  return `<p>${escapeHtml(block.text || '')}</p>`;
}
function renderBlog() {
  if (!current) return;
  const meta = blogMeta(current, lang);
  const title = meta.title || sectionTitle(current);
  const subtitle = meta.subtitle || '';
  const blocks = blogBlocks(current, lang);
  const fallback = blocks.length ? '' : '<p>No blog block mapped for this section.</p>';
  blogPane.innerHTML = `<div class="blog-article"><header class="blog-title-block"><div class="blog-kicker">${escapeHtml(sectionTitle(current))}</div><h2>${escapeHtml(title)}</h2>${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ''}</header>${blocks.map(renderBlock).join('')}${fallback}</div>`;
  document.getElementById('langEn').classList.toggle('active', lang === 'en');
  document.getElementById('langCn').classList.toggle('active', lang === 'zh');
}
function renderRail() {
  rail.innerHTML = '';
  (ALIGNMENT.sections || []).forEach((sec, index) => {
    if (!sections.has(sec.id)) sections.set(sec.id, sec);
    const b = document.createElement('button');
    b.type = 'button';
    b.title = sectionTitle(sec);
    b.dataset.section = sec.id;
    const number = document.createElement('span');
    number.className = 'section-index';
    number.textContent = String(index + 1).padStart(2, '0');
    const label = document.createElement('span');
    label.className = 'section-label';
    label.textContent = sectionTitle(sec);
    b.append(number, label);
    b.addEventListener('click', () => openSection(sec.id));
    rail.appendChild(b);
  });
}
function renderDownloads() {
  const box = document.getElementById('downloadLinks');
  const downloads = ALIGNMENT.downloads || [];
  const onDemand = ALIGNMENT.download_delivery === 'on_demand';
  if (onDemand && window.location.protocol === 'file:') {
    box.innerHTML = '';
    box.style.display = 'none';
    box.setAttribute('aria-hidden', 'true');
    return;
  }
  box.style.display = '';
  box.removeAttribute('aria-hidden');
  const icon = '<span class="download-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v11"></path><path d="m7 10 5 5 5-5"></path><path d="M5 20h14"></path></svg></span>';
  const links = downloads.map((item, idx) => `${idx ? '<span class="download-sep" aria-hidden="true">|</span>' : ''}<a class="download-link" href="${escapeHtml(item.href)}" download>${escapeHtml(item.label)}</a>`).join('');
  box.innerHTML = icon + links;
}
function renderThumbs() {
  const row = document.getElementById('thumbRow');
  const segs = current.slide_segments || slideList(current).map(n => ({slide:n, relative_start:0}));
  row.innerHTML = segs.map((s, idx) => {
    const n = slideNumber(s);
    const t = Number(s.relative_start || 0);
    return `<button class="thumb-btn${idx === 0 ? ' active' : ''}" type="button" data-index="${idx}" data-time="${t}" data-slide="${n}" title="Jump to ${fmtTime(t)}"><img src="${slideSrc(n)}" alt="Slide ${n}"><span>Slide ${String(n).padStart(2,'0')} · ${fmtTime(t)}</span></button>`;
  }).join('');
}
function captionSrcForClip(src) {
  const clean = String(src || '').split('?')[0];
  if (!clean) return '';
  if (clean === artifactVideo() || clean.endsWith('/video.mp4') || clean === 'assets/media/video.mp4' || clean === 'media/video.mp4') return (ALIGNMENT.artifacts && ALIGNMENT.artifacts.captions) || 'assets/media/captions/video.vtt';
  if (clean.startsWith('assets/media/clips/') && clean.endsWith('.mp4')) return clean.replace('assets/media/clips/', 'assets/media/captions/clips/').replace(/\.mp4$/, '.vtt');
  if (clean.startsWith('assets/media/slide_clips/') && clean.endsWith('.mp4')) return clean.replace('assets/media/slide_clips/', 'assets/media/captions/slide_clips/').replace(/\.mp4$/, '.vtt');
  if (clean.startsWith('media/clips/') && clean.endsWith('.mp4')) return clean.replace('media/clips/', 'media/captions/clips/').replace(/\.mp4$/, '.vtt');
  if (clean.startsWith('media/slide_clips/') && clean.endsWith('.mp4')) return clean.replace('media/slide_clips/', 'media/captions/slide_clips/').replace(/\.mp4$/, '.vtt');
  return '';
}
function applyCaptionMode() {
  Array.from(video.textTracks || []).forEach(track => { track.mode = subtitlesEnabled ? 'showing' : 'disabled'; });
  captionToggle.classList.toggle('active', subtitlesEnabled);
  captionToggle.setAttribute('aria-pressed', subtitlesEnabled ? 'true' : 'false');
  captionToggle.textContent = subtitlesEnabled ? 'CC On' : 'CC';
  captionToggle.title = subtitlesEnabled ? 'Hide subtitles' : 'Show subtitles';
}
function setCaptionTrackForClip(src) {
  const capSrc = captionSrcForClip(src);
  Array.from(video.querySelectorAll('track[data-reel-caption]')).forEach(track => track.remove());
  if (!capSrc) { captionToggle.disabled = true; applyCaptionMode(); return; }
  captionToggle.disabled = false;
  const track = document.createElement('track');
  track.kind = 'subtitles';
  track.label = 'English';
  track.srclang = 'en';
  const embedded = CAPTION_TEXT[capSrc];
  track.src = embedded ? `data:text/vtt;charset=utf-8,${encodeURIComponent(embedded)}` : capSrc;
  track.dataset.reelCaption = '1';
  track.addEventListener('load', applyCaptionMode, {once:true});
  video.appendChild(track);
  setTimeout(applyCaptionMode, 0);
}
function loadAndPlayClip(src, startAt) {
  const requestId = ++videoLoadRequestId;
  playSoundBtn.classList.remove('show');
  video.pause();
  const playNow = () => {
    if (requestId !== videoLoadRequestId) return;
    try { video.currentTime = Math.max(0, Number(startAt)||0); } catch(e) {}
    video.muted = false;
    video.volume = 1;
    const playPromise = video.play();
    if (playPromise && playPromise.catch) playPromise.catch(() => playSoundBtn.classList.add('show'));
    setTimeout(() => { if (video.paused) playSoundBtn.classList.add('show'); }, 600);
    syncActiveThumb();
  };
  if ((video.getAttribute('src') || '') !== src) {
    video.setAttribute('src', src);
    setCaptionTrackForClip(src);
    video.load();
    video.addEventListener('loadedmetadata', playNow, {once:true});
  } else {
    setCaptionTrackForClip(src);
    if (video.readyState >= 1) playNow();
    else video.addEventListener('loadedmetadata', playNow, {once:true});
  }
}
function openSection(id) {
  const sec = sections.get(id);
  if (!sec) return;
  current = sec;
  document.querySelectorAll('.section-rail button').forEach(b => b.classList.toggle('active', b.dataset.section === id));
  document.getElementById('modalTitle').textContent = sectionTitle(sec);
  const slides = slideList(sec);
  const seg = sec.segment || {};
  document.getElementById('segmentText').textContent = id === 'title' ? `Full video · ${fmtTime(seg.end || 0)} · all mapped content` : `${fmtTime(seg.start || 0)} – ${fmtTime(seg.end || 0)} · slides ${slides.join(', ') || 'mapped'}`;
  renderThumbs();
  renderBlog();
  modalOpenedAt = Date.now();
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  loadAndPlayClip(sec.clip || artifactVideo(), 0);
  flashPosterSection(id);
}
function closeModal() { overlay.classList.remove('open'); overlay.setAttribute('aria-hidden', 'true'); video.pause(); }
function playSlide(index) {
  if (!current) return;
  const segs = current.slide_segments || [];
  const seg = segs[Math.max(0, Math.min(segs.length - 1, Number(index)||0))];
  if (!seg) return;
  loadAndPlayClip(current.clip || artifactVideo(), Number(seg.relative_start || 0));
  syncActiveThumb();
}
function syncActiveThumb() {
  const buttons = Array.from(document.querySelectorAll('.thumb-btn'));
  if (!buttons.length) return;
  let active = buttons[0];
  for (const b of buttons) if (Number(b.dataset.time || 0) <= (video.currentTime || 0) + 0.15) active = b;
  buttons.forEach(b => b.classList.toggle('active', b === active));
}
function posterDoc() { try { return posterFrame.contentDocument; } catch(e) { return null; } }
function shouldUseLocalOpenRuntime() { return window.location.protocol === 'file:' && typeof POSTER_HTML === 'string' && POSTER_HTML.length > 0; }
const POSTER_HOOK_PENDING_RETRY_MS = 50;
const POSTER_HOOK_STEADY_RETRY_MS = 500;
let posterHookRetryTimer = null;
let posterHookState = null;
function posterHookIdentityMatches(state, doc) {
  return Boolean(
    state && doc && state.doc === doc && state.root === doc.documentElement &&
    state.head === doc.head && state.body === doc.body
  );
}
function disposePosterHookState() {
  if (posterHookState && posterHookState.observer) {
    try { posterHookState.observer.disconnect(); } catch(e) {}
  }
  posterHookState = null;
}
function schedulePosterToolsRetry(delayMs) {
  if (posterHookRetryTimer !== null) clearTimeout(posterHookRetryTimer);
  posterHookRetryTimer = setTimeout(() => {
    posterHookRetryTimer = null;
    injectPosterTools();
  }, Math.max(0, Number(delayMs) || 0));
}
function initPosterFrame() {
  posterFrame.addEventListener('load', injectPosterTools);
  if (shouldUseLocalOpenRuntime()) {
    posterFrame.removeAttribute('src');
    posterFrame.srcdoc = POSTER_HTML;
    schedulePosterToolsRetry(0);
    return;
  }
  if (posterFrame.getAttribute('src') !== POSTER_SRC) posterFrame.setAttribute('src', POSTER_SRC);
  schedulePosterToolsRetry(0);
}
function showTooltip(doc, text, x, y) {
  let tip = doc.getElementById('paperReelTip');
  if (!tip) {
    tip = doc.createElement('div');
    tip.id = 'paperReelTip';
    tip.style.cssText = 'position:fixed;z-index:2147483647;padding:6px 9px;border-radius:5px;background:rgba(20,20,20,.82);color:#fff;font:700 12px Arial;pointer-events:none;opacity:0;transition:opacity .12s;';
    doc.body.appendChild(tip);
  }
  tip.textContent = text;
  tip.style.left = Math.min(x + 12, doc.defaultView.innerWidth - 180) + 'px';
  tip.style.top = Math.max(8, y + 12) + 'px';
  tip.style.opacity = '1';
  clearTimeout(tip._timer);
  tip._timer = setTimeout(() => { tip.style.opacity = '0'; }, 2000);
}
function posterTargetId(el) {
  if (el.matches('.titlebar')) return 'title';
  if (!el.hasAttribute('data-section')) return '';
  if (el.matches('button, a, .listen-btn, .listen-title, .listen-all')) return '';
  if (el.closest('.titlebar')) return '';
  const id = el.getAttribute('data-section') || '';
  return sections.has(id) ? id : '';
}
function bindPosterTarget(state, el) {
  const view = state.doc.defaultView;
  if (!view || !(el instanceof view.Element)) return;
  const id = posterTargetId(el);
  if (!id) return;
  if (!el.classList.contains('paper-reel-clickable')) {
    el.classList.add('paper-reel-clickable');
  }
  el.removeAttribute('title');
  if (state.bound.has(el)) return;
  state.bound.add(el);
  el.addEventListener('mouseenter', e => {
    state.body.classList.add('paper-reel-has-hover');
    el.classList.add('paper-reel-hover');
    showTooltip(state.doc, 'Double Click to Open', e.clientX, e.clientY);
  });
  el.addEventListener('mousemove', e => showTooltip(state.doc, 'Double Click to Open', e.clientX, e.clientY));
  el.addEventListener('mouseleave', () => {
    el.classList.remove('paper-reel-hover');
    if (!state.doc.querySelector('.paper-reel-hover')) state.body.classList.remove('paper-reel-has-hover');
  });
  el.addEventListener('dblclick', ev => {
    if (ev.target.closest('button, a')) return;
    const currentId = posterTargetId(el);
    if (!currentId) return;
    ev.preventDefault();
    ev.stopPropagation();
    openSection(currentId);
  });
}
function bindPosterTargetTree(state, node) {
  const view = state.doc.defaultView;
  if (!view || !(node instanceof view.Element)) return;
  bindPosterTarget(state, node);
  node.querySelectorAll('[data-section], .titlebar').forEach(el => bindPosterTarget(state, el));
}
function bindPosterTargets(state) {
  state.doc.querySelectorAll('[data-section], .titlebar').forEach(el => bindPosterTarget(state, el));
}
function installPosterTools(doc) {
  const state = {
    doc,
    root: doc.documentElement,
    head: doc.head,
    body: doc.body,
    bound: new WeakSet(),
    observer: null,
  };
  let style = doc.getElementById('paperReelToolsStyle');
  if (!style) {
    style = doc.createElement('style');
    style.id = 'paperReelToolsStyle';
    style.textContent = `
    [data-section].paper-reel-clickable, .titlebar.paper-reel-clickable { cursor:pointer !important; transition:opacity .16s ease, border-color .16s ease, box-shadow .16s ease, filter .16s ease; }
    body.paper-reel-has-hover [data-section].paper-reel-clickable:not(.paper-reel-hover) { opacity:var(--paper-reel-dim-opacity,.48); }
    [data-section].paper-reel-hover { border-color:rgba(14,106,110,.9) !important; box-shadow:inset 0 0 0 5px rgba(14,106,110,.72), 0 0 18px rgba(14,106,110,.16) !important; filter:brightness(1.015); }
    .titlebar.paper-reel-hover { filter:brightness(1.04); }
    [data-section].paper-reel-flash { border-color:rgba(214,74,54,.72) !important; box-shadow:inset 0 0 0 7px rgba(214,74,54,.46), 0 0 20px rgba(214,74,54,.16) !important; }
    .titlebar.paper-reel-flash { filter:brightness(1.08); }
    #paperReelDebug { position:fixed; right:14px; bottom:14px; z-index:2147483646; display:none; background:rgba(255,255,255,.96); border:1px solid #cbd5dc; border-radius:8px; padding:10px; font:12px Arial; box-shadow:0 12px 30px rgba(0,0,0,.2); }
    body.paper-reel-debug #paperReelDebug { display:block; }
  `;
    doc.head.appendChild(style);
  }
  let debug = doc.getElementById('paperReelDebug');
  if (!debug) {
    debug = doc.createElement('div');
    debug.id = 'paperReelDebug';
    debug.innerHTML = '<b>Reel Hover</b><br><label>Other section opacity <input id="paperReelOpacity" type="range" min="0.2" max="1" step="0.05" value="0.48"></label>';
    doc.body.appendChild(debug);
  }
  const opacity = debug.querySelector('#paperReelOpacity');
  if (opacity && !opacity.__paperReelBound) {
    opacity.__paperReelBound = true;
    opacity.addEventListener('input', e => doc.documentElement.style.setProperty('--paper-reel-dim-opacity', e.target.value));
  }
  doc.defaultView.__paperReelToggleOpacityDebug = () => doc.body.classList.toggle('paper-reel-debug');
  if (!doc.getElementById('paperReelShortcutBridge')) {
    const bridge = doc.createElement('script');
    bridge.id = 'paperReelShortcutBridge';
    bridge.textContent = `
    (() => {
      const bridgeRoot = document.documentElement;
      if (window.__paperReelShortcutBridgeRoot === bridgeRoot) return;
      window.__paperReelShortcutBridgeRoot = bridgeRoot;
      window.__paperReelShortcutBridge = true;
      function forwardPaperReelShortcut(key) {
        try {
          if (window.parent && window.parent.handleShortcut) {
            window.parent.handleShortcut(key);
            return;
          }
        } catch (err) {}
        try { window.parent.postMessage({type:'paper2reel:shortcut', key}, '*'); } catch (err) {}
      }
      window.__paperReelForwardShortcut = forwardPaperReelShortcut;
      document.addEventListener('keydown', event => {
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const key = event.key ? event.key.toLowerCase() : '';
        if (['a','s','d','v','h'].includes(key)) {
          event.preventDefault();
          event.stopImmediatePropagation();
          forwardPaperReelShortcut(key);
        }
      }, true);
    })();
  `;
    doc.body.appendChild(bridge);
  }
  const iframeReelKeydown = e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key ? e.key.toLowerCase() : '';
    if (['a','s','d','v','h'].includes(key)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      try { doc.defaultView.parent.handleShortcut(key); }
      catch(err) { doc.defaultView.parent.postMessage({type:'paper2reel:shortcut', key}, '*'); }
    }
  };
  doc.defaultView.onkeydown = iframeReelKeydown;
  doc.onkeydown = iframeReelKeydown;
  if (doc.body) doc.body.onkeydown = iframeReelKeydown;
  bindPosterTargets(state);
  state.observer = new doc.defaultView.MutationObserver(records => {
    if (!posterHookIdentityMatches(state, posterDoc())) {
      injectPosterTools();
      return;
    }
    records.forEach(record => {
      if (record.type === 'attributes') bindPosterTargetTree(state, record.target);
      record.addedNodes.forEach(node => bindPosterTargetTree(state, node));
    });
  });
  state.observer.observe(doc, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['data-section', 'class'],
  });
  return state;
}
function injectPosterTools() {
  const doc = posterDoc();
  if (!doc || !doc.documentElement || !doc.head || !doc.body || !doc.defaultView) {
    if (posterHookState && posterHookState.doc !== doc) disposePosterHookState();
    schedulePosterToolsRetry(POSTER_HOOK_PENDING_RETRY_MS);
    return false;
  }
  if (!posterHookIdentityMatches(posterHookState, doc)) {
    disposePosterHookState();
    try { posterHookState = installPosterTools(doc); }
    catch(e) {
      disposePosterHookState();
      schedulePosterToolsRetry(POSTER_HOOK_PENDING_RETRY_MS);
      return false;
    }
  } else {
    bindPosterTargets(posterHookState);
  }
  const ready = Boolean(doc.querySelector('[data-section].paper-reel-clickable, .titlebar.paper-reel-clickable'));
  schedulePosterToolsRetry(ready ? POSTER_HOOK_STEADY_RETRY_MS : POSTER_HOOK_PENDING_RETRY_MS);
  return ready;
}
function flashPosterSection(id) {
  const doc = posterDoc();
  if (!doc) return;
  const selector = id === 'title' ? '.titlebar' : `[data-section="${id.replace(/"/g, '\\"')}"]`;
  const el = doc.querySelector(selector);
  if (!el) return;
  el.classList.add('paper-reel-flash');
  el.scrollIntoView({block:'center', inline:'center', behavior:'smooth'});
  setTimeout(() => el.classList.remove('paper-reel-flash'), 1600);
}
function postShortcutToPoster(key) {
  try { posterFrame.contentWindow && posterFrame.contentWindow.postMessage({type:'paper2reel:shortcut', key}, '*'); } catch(e) {}
}
function togglePosterListenControls() {
  const doc = posterDoc();
  if (doc && doc.body) doc.body.classList.toggle('show-listen');
  else postShortcutToPoster('a');
}
function togglePosterDebug() {
  const doc = posterDoc();
  if (doc && doc.defaultView) {
    const nativeInitiallyOn = !!(doc.body && doc.body.classList.contains('debug'));
    const opacityInitiallyOn = !!(doc.body && doc.body.classList.contains('paper-reel-debug'));
    const targetOn = nativeInitiallyOn !== opacityInitiallyOn ? true : !nativeInitiallyOn;
    const alignDebugState = () => {
      if (!doc.body) return;
      const nativeOn = doc.body.classList.contains('debug');
      const opacityOn = doc.body.classList.contains('paper-reel-debug');
      if (typeof doc.defaultView.__togglePosterDebug === 'function' && nativeOn !== targetOn) doc.defaultView.__togglePosterDebug();
      if (typeof doc.defaultView.__paperReelToggleOpacityDebug === 'function') {
        if (opacityOn !== targetOn) doc.defaultView.__paperReelToggleOpacityDebug();
      } else if (opacityOn !== targetOn) {
        doc.body.classList.toggle('paper-reel-debug', targetOn);
      }
    };
    alignDebugState();
    setTimeout(alignDebugState, 40);
    setTimeout(alignDebugState, 180);
    return;
  }
  postShortcutToPoster('d');
}
function toggleTopMenu(force) { document.body.classList.toggle('show-menu', typeof force === 'boolean' ? force : !document.body.classList.contains('show-menu')); }
function toggleHelp(force) {
  const help = document.getElementById('helpOverlay');
  const on = typeof force === 'boolean' ? force : !help.classList.contains('open');
  help.classList.toggle('open', on);
  help.setAttribute('aria-hidden', on ? 'false' : 'true');
}
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else document.documentElement.requestFullscreen().catch(() => {});
}
function handleShortcut(key) {
  if (key === 'a') togglePosterListenControls();
  else if (key === 'd') togglePosterDebug();
  else if (key === 's') toggleFullscreen();
  else if (key === 'v') toggleTopMenu();
  else if (key === 'h') toggleHelp();
}
window.handleShortcut = handleShortcut;
window.addEventListener('message', e => {
  const data = e.data || {};
  if (data.type === 'paper2reel:shortcut' && data.key) handleShortcut(String(data.key).toLowerCase());
});
function initSplitter() {
  const splitter = document.getElementById('splitter');
  const body = document.querySelector('.modal-body');
  let dragging = false;
  const setFromClientX = x => {
    const rect = body.getBoundingClientRect();
    if (!rect.width) return;
    const pct = Math.max(42, Math.min(76, ((x - rect.left) / rect.width) * 100));
    body.style.setProperty('--video-pane-width', pct.toFixed(1) + '%');
  };
  splitter.addEventListener('pointerdown', e => { dragging = true; splitter.setPointerCapture(e.pointerId); document.body.classList.add('resizing'); e.preventDefault(); });
  splitter.addEventListener('pointermove', e => { if (dragging) setFromClientX(e.clientX); });
  splitter.addEventListener('pointerup', e => { dragging = false; document.body.classList.remove('resizing'); try { splitter.releasePointerCapture(e.pointerId); } catch(err) {} });
}
function init() {
  (ALIGNMENT.sections || []).forEach(sec => sections.set(sec.id, sec));
  renderRail();
  renderDownloads();
  initPosterFrame();
  document.getElementById('closeBtn').addEventListener('click', closeModal);
  captionToggle.addEventListener('click', () => { subtitlesEnabled = !subtitlesEnabled; applyCaptionMode(); });
  playSoundBtn.addEventListener('click', () => {
    video.muted = false;
    video.volume = 1;
    video.play().then(() => playSoundBtn.classList.remove('show')).catch(() => {});
  });
  video.addEventListener('play', () => playSoundBtn.classList.remove('show'));
  document.getElementById('thumbRow').addEventListener('click', e => { const btn = e.target.closest('.thumb-btn'); if (btn) playSlide(btn.dataset.index); });
  document.getElementById('langEn').addEventListener('click', () => { lang='en'; renderBlog(); });
  document.getElementById('langCn').addEventListener('click', () => { lang='zh'; renderBlog(); });
  overlay.addEventListener('click', e => { if (e.target === overlay && Date.now() - modalOpenedAt > 400) closeModal(); });
  document.getElementById('helpTopBtn').addEventListener('click', () => toggleHelp(true));
  document.getElementById('helpCloseBtn').addEventListener('click', () => toggleHelp(false));
  document.getElementById('helpOverlay').addEventListener('click', e => { if (e.target.id === 'helpOverlay') toggleHelp(false); });
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key ? e.key.toLowerCase() : '';
    if (key === 'escape') {
      const help = document.getElementById('helpOverlay');
      if (help.classList.contains('open')) toggleHelp(false);
      else closeModal();
      return;
    }
    if (['a','s','d','v','h'].includes(key)) { e.preventDefault(); handleShortcut(key); }
  });
  video.addEventListener('timeupdate', syncActiveThumb);
  initSplitter();
}
init();
</script>
</body>
</html>
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore_backup_artifacts)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def is_backup_artifact_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".bak", ".backup")) or ".bak." in lowered


def ignore_backup_artifacts(_dir: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name == "_debug" or is_backup_artifact_name(name):
            ignored.add(name)
    return ignored


def copy_poster_assets(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    generated_reel_dirs = {
        "poster",
        "media",
        "blog",
        "downloads",
        "slides",
        "ui",
    }

    def ignore(dir_name: str, names: list[str]) -> set[str]:
        ignored = ignore_backup_artifacts(dir_name, names)
        try:
            is_root = Path(dir_name).resolve() == src.resolve()
        except OSError:
            is_root = False
        if is_root:
            ignored.update(name for name in names if name in generated_reel_dirs)
        return ignored

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def js_string_for_html(text: str) -> str:
    """Encode HTML as a JS string without closing the surrounding script tag."""
    return js_json_for_script(text)


def js_json_for_script(value: Any) -> str:
    """Encode one JSON value without allowing it to close an inline script."""
    return json.dumps(value, ensure_ascii=True).replace("</", "<\\/")


def render_reel_html(
    alignment: dict[str, Any],
    poster_srcdoc_html: str,
    caption_text: dict[str, str] | None = None,
) -> str:
    """Render the locked Reel wrapper with all inline runtime values.

    Substitute every marker against the pristine template in one pass. A
    value can legitimately contain another marker, so chained replacements on
    partially rendered HTML are unsafe.
    """
    if not isinstance(alignment, dict):
        raise TypeError("alignment must be an object")
    if not isinstance(poster_srcdoc_html, str):
        raise TypeError("poster_srcdoc_html must be a string")
    captions = {} if caption_text is None else caption_text
    if not isinstance(captions, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in captions.items()
    ):
        raise TypeError("caption_text must map strings to strings")

    replacements = {
        "const ALIGNMENT = {};": (
            "const ALIGNMENT = " + js_json_for_script(alignment) + ";"
        ),
        "const POSTER_HTML = null;": (
            "const POSTER_HTML = " + js_string_for_html(poster_srcdoc_html) + ";"
        ),
        "const CAPTION_TEXT = {};": (
            "const CAPTION_TEXT = " + js_json_for_script(captions) + ";"
        ),
    }
    for marker in replacements:
        count = SECTION_MODAL_HTML.count(marker)
        if count != 1:
            raise RuntimeError(
                f"Reel template marker must occur exactly once: {marker!r} ({count})"
            )
    marker_pattern = re.compile(
        "|".join(re.escape(marker) for marker in replacements)
    )
    rendered, count = marker_pattern.subn(
        lambda match: replacements[match.group(0)], SECTION_MODAL_HTML
    )
    if count != len(replacements):
        raise RuntimeError(f"Reel template substitution count mismatch: {count}")
    return rendered


def default_mathjax_cache_dir() -> Path:
    return Path.home() / ".cache" / "autoresearch" / "paper2reel" / f"mathjax-{MATHJAX_VERSION}"


def ensure_mathjax_es5(cache_dir: Path) -> Path:
    es5_dir = cache_dir / "es5"
    if (es5_dir / "tex-svg.js").is_file():
        return es5_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball = cache_dir / f"mathjax-{MATHJAX_VERSION}.tgz"
    if not tarball.is_file():
        print(f"[paper2reel] downloading MathJax {MATHJAX_VERSION} for local-open bundles")
        try:
            urllib.request.urlretrieve(MATHJAX_TARBALL_URL, tarball)
        except Exception as exc:
            raise SystemExit(
                "poster.html references CDN MathJax, but paper2reel could not download "
                f"MathJax {MATHJAX_VERSION} for the local-open bundle: {exc}"
            ) from exc

    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.name.startswith("package/es5/") or member.isdir():
                continue
            rel = member.name[len("package/") :]
            target = cache_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, target.open("wb") as dst:
                if src is None:
                    continue
                shutil.copyfileobj(src, dst)
    if not (es5_dir / "tex-svg.js").is_file():
        raise SystemExit(f"MathJax extraction did not produce {es5_dir / 'tex-svg.js'}")
    return es5_dir


def rewrite_mathjax_to_local(poster_html: str) -> tuple[str, int]:
    return MATHJAX_CDN_RE.subn(
        lambda match: f"{match.group('prefix')}{match.group('quote')}mathjax/es5/tex-svg.js{match.group('quote')}",
        poster_html,
    )


def install_local_mathjax_if_needed(poster_html: str, poster_out: Path, cache_dir: Path) -> tuple[str, int]:
    rewritten, count = rewrite_mathjax_to_local(poster_html)
    if count == 0:
        return poster_html, 0
    es5_src = ensure_mathjax_es5(cache_dir)
    target = poster_out / "mathjax" / "es5"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(es5_src, target)
    return rewritten, count


def install_local_katex_if_needed(poster_html: str, poster_out: Path) -> tuple[str, int]:
    rewritten = poster_html
    count = 0
    for pattern, replacement in KATEX_CDN_REPLACEMENTS:
        rewritten, replaced = pattern.subn(replacement, rewritten)
        count += replaced
    if count == 0:
        return poster_html, 0
    if not KATEX_ASSET_DIR.is_dir():
        raise SystemExit(
            "poster.html references CDN KaTeX, but paper2poster's local KaTeX "
            f"assets are missing: {KATEX_ASSET_DIR}"
        )
    target = poster_out / "katex"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(KATEX_ASSET_DIR, target, ignore=ignore_backup_artifacts)
    return rewritten, count


def inject_srcdoc_base(poster_html: str) -> str:
    head = poster_html.split("</head>", 1)[0]
    if re.search(r"<base\s", head, flags=re.IGNORECASE):
        return poster_html
    updated, count = re.subn(
        r"(<head\b[^>]*>)",
        r'\1\n<base href="assets/poster/">',
        poster_html,
        count=1,
        flags=re.IGNORECASE,
    )
    if count:
        return updated
    return '<base href="assets/poster/">\n' + poster_html


def prepare_poster_for_local_open(poster_html: Path, cache_dir: Path) -> str:
    text = poster_html.read_text(encoding="utf-8")
    text, katex_count = install_local_katex_if_needed(text, poster_html.parent)
    text, mathjax_count = install_local_mathjax_if_needed(text, poster_html.parent, cache_dir)
    if katex_count or mathjax_count:
        poster_html.write_text(text, encoding="utf-8")
    if katex_count:
        print(f"[paper2reel] localized {katex_count} KaTeX reference(s) for local-open")
    if mathjax_count:
        print(f"[paper2reel] localized {mathjax_count} MathJax reference(s) for local-open")
    return inject_srcdoc_base(text)


def patch_poster_shortcut_bridge(poster_html: Path) -> None:
    text = poster_html.read_text(encoding="utf-8")
    if "paper2reel-shortcut-bridge" in text:
        return
    bridge = r"""
<script id="paper2reel-shortcut-bridge">
(() => {
  if (window.__paperReelShortcutBridge) return;
  window.__paperReelShortcutBridge = true;
  function forwardPaperReelShortcut(key) {
    try {
      if (window.parent && window.parent.handleShortcut) {
        window.parent.handleShortcut(key);
        return;
      }
    } catch (err) {}
    try { window.parent.postMessage({type:'paper2reel:shortcut', key}, '*'); } catch (err) {}
  }
  window.__paperReelForwardShortcut = forwardPaperReelShortcut;
  function onPaperReelKeydown(event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const key = event.key ? event.key.toLowerCase() : '';
    if (['a','s','d','v','h'].includes(key)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      forwardPaperReelShortcut(key);
    }
  }
  function bindPaperReelShortcutTarget(target) {
    if (!target || target.__paperReelShortcutTarget) return;
    target.__paperReelShortcutTarget = true;
    target.addEventListener('keydown', onPaperReelKeydown, true);
  }
  bindPaperReelShortcutTarget(window);
  bindPaperReelShortcutTarget(document);
  bindPaperReelShortcutTarget(document.body);
  document.addEventListener('DOMContentLoaded', () => bindPaperReelShortcutTarget(document.body), {once:true});
})();
</script>
""".strip()
    if re.search(r"</body\s*>", text, flags=re.IGNORECASE):
        text = re.sub(r"</body\s*>", bridge + "\n</body>", text, count=1, flags=re.IGNORECASE)
    else:
        text = text.rstrip() + "\n" + bridge + "\n"
    poster_html.write_text(text, encoding="utf-8")


def rel_to(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def slug_label(section_id: str) -> str:
    return section_id.replace("-", " ").replace("_", " ").title()


def normalize_section_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def natural_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def discover_slide_files(slides_dir: Path) -> list[Path]:
    if not slides_dir.is_dir():
        raise SystemExit(f"slides dir not found: {slides_dir}")
    candidates = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.svg"):
        candidates.extend(slides_dir.glob(pattern))
    files = sorted([p for p in candidates if p.is_file()], key=natural_key)
    if not files:
        raise SystemExit(f"no slide images found in {slides_dir}")
    return files


def load_script_sections(script_json: Path | None) -> list[dict[str, Any]]:
    if script_json is None:
        return []
    payload = load_json(script_json, {})
    sections = payload.get("sections") if isinstance(payload, dict) else []
    return sections if isinstance(sections, list) else []


def copy_poster_bundle(poster_dir: Path, outdir: Path) -> None:
    poster_out = outdir / POSTER_DIR
    clean_dir(poster_out)
    required = poster_dir / "poster.html"
    if not required.is_file():
        raise SystemExit(f"poster.html not found under {poster_dir}")
    copy_if_exists(required, poster_out / "poster.html")
    patch_poster_shortcut_bridge(poster_out / "poster.html")
    copy_poster_assets(poster_dir / "assets", poster_out / "assets")
    for name in ("figures", "fonts", "logos", "qr", "audio"):
        copy_if_exists(poster_dir / name, poster_out / name)


def copy_ui_assets(outdir: Path) -> None:
    ui_out = outdir / UI_DIR
    ui_out.mkdir(parents=True, exist_ok=True)
    wordmark_out = ui_out / "reel-wordmark.png"
    if REEL_WORDMARK_SRC.is_file():
        shutil.copy2(REEL_WORDMARK_SRC, wordmark_out)
        return
    # A historical self-contained Reel already owns this exact runtime asset.
    # Preserve it when refreshing that bundle even if the source checkout does
    # not carry the optional docs tree used by a from-scratch build.
    if wordmark_out.is_file() and not wordmark_out.is_symlink():
        return
    raise SystemExit(f"reel wordmark asset not found: {REEL_WORDMARK_SRC}")


def copy_slides(slide_files: list[Path], outdir: Path) -> list[dict[str, Any]]:
    slides_out = outdir / SLIDES_DIR
    clean_dir(slides_out)
    slides: list[dict[str, Any]] = []
    for idx, src in enumerate(slide_files, start=1):
        dst = slides_out / f"slide_{idx:02d}{src.suffix.lower()}"
        shutil.copy2(src, dst)
        slides.append(
            {
                "index": idx,
                "source": src.name,
                "src": rel_to(dst, outdir),
                "id": src.stem,
                "label": slug_label(src.stem),
            }
        )
    return slides


def copy_blog_assets(outdir: Path, blog_figures_dir: Path | None) -> dict[str, str]:
    if blog_figures_dir is None or not blog_figures_dir.is_dir():
        return {}
    blog_out = outdir / BLOG_FIGURES_DIR
    blog_out.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for src in sorted(blog_figures_dir.iterdir()):
        if not src.is_file() or is_backup_artifact_name(src.name):
            continue
        dst = blog_out / src.name
        shutil.copy2(src, dst)
        rel = rel_to(dst, outdir)
        mapping[src.name] = rel
        mapping[f"figures/{src.name}"] = rel
        mapping[src.as_posix()] = rel
    return mapping


def normalize_blog_blocks(payload: dict[str, Any], asset_map: dict[str, str]) -> list[dict[str, Any]]:
    raw_blocks = payload.get("blocks") if isinstance(payload, dict) else []
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[dict[str, Any]] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        block = dict(raw)
        btype = str(block.get("type") or "").lower()
        if btype == "figure":
            path = str(block.get("path") or "").strip()
            if path:
                block["src"] = asset_map.get(path) or asset_map.get(Path(path).name) or path
                block["path"] = block["src"]
        blocks.append(block)
    return blocks


def block_text(block: dict[str, Any]) -> str:
    parts = [
        str(block.get("text") or ""),
        str(block.get("caption") or ""),
        " ".join(str(x) for x in block.get("headers") or []),
    ]
    for row in block.get("rows") or []:
        if isinstance(row, list):
            parts.extend(str(x) for x in row)
    return " ".join(parts)


def blog_segments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not blocks:
        return []
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for block in blocks:
        is_heading = str(block.get("type") or "").lower() == "heading"
        if is_heading and current:
            segments.append({"blocks": current, "text": " ".join(block_text(b) for b in current)})
            current = [block]
        else:
            current.append(block)
    if current:
        segments.append({"blocks": current, "text": " ".join(block_text(b) for b in current)})
    return segments


def score_segment(section_id: str, segment: dict[str, Any]) -> int:
    text = str(segment.get("text") or "").lower()
    return sum(1 for keyword in BLOG_SECTION_KEYWORDS.get(section_id, []) if keyword.lower() in text)


def has_figure(blocks: list[dict[str, Any]]) -> bool:
    return any(str(block.get("type") or "").lower() == "figure" for block in blocks)


def first_figure(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        if str(block.get("type") or "").lower() == "figure":
            return dict(block)
    return None


def section_figure(section_id: str, blocks: list[dict[str, Any]], segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for idx, seg in enumerate(segments):
        fig = first_figure(seg.get("blocks") or [])
        if fig:
            candidates.append((score_segment(section_id, seg), idx, fig))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return dict(candidates[0][2])
    return first_figure(blocks)


def ensure_section_figure(section_id: str, picked: list[dict[str, Any]], blocks: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if section_id == "title" or not picked or has_figure(picked):
        return picked
    fig = section_figure(section_id, blocks, segments)
    if not fig:
        return picked
    # Keep the section modal visually anchored to the article assets even when
    # the matching prose segment did not itself contain a figure.
    return [fig, *picked]


def blocks_for_section(section_id: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if section_id == "title":
        return blocks
    segments = blog_segments(blocks)
    if not segments:
        return []
    scored = [(score_segment(section_id, seg), idx, seg) for idx, seg in enumerate(segments)]
    positives = [(score, idx, seg) for score, idx, seg in scored if score > 0]
    if positives:
        positives.sort(key=lambda item: (-item[0], item[1]))
        chosen = positives[:2] if section_id in {"method", "key-result", "takeaway"} else positives[:1]
        out: list[dict[str, Any]] = []
        for _score, _idx, seg in sorted(chosen, key=lambda item: item[1]):
            out.extend(seg["blocks"])
        return ensure_section_figure(section_id, out, blocks, segments)

    # Last-resort deterministic fallback: give each section enough useful text
    # to keep the modal informative, but do not invent content.
    non_title_ids = [sid for sid in BLOG_SECTION_KEYWORDS]
    try:
        offset = non_title_ids.index(section_id)
    except ValueError:
        offset = 0
    seg = segments[min(offset, len(segments) - 1)]
    return ensure_section_figure(section_id, seg["blocks"], blocks, segments)


def load_blog_outline(path: Path | None, asset_map: dict[str, str]) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        return None
    return {
        "title": str(payload.get("title") or ""),
        "subtitle": str(payload.get("subtitle") or ""),
        "lang": str(payload.get("lang") or ""),
        "blocks": normalize_blog_blocks(payload, asset_map),
    }


def bundle_json_path(bundle_dir: Path, key: str, legacy_name: str) -> Path:
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path, {})
        if isinstance(manifest, dict):
            files = manifest.get("files")
            if isinstance(files, dict) and isinstance(files.get(key), str):
                candidate = bundle_dir / files[key]
                if candidate.is_file():
                    return candidate
    candidate = bundle_dir / "assets" / "meta" / legacy_name
    if candidate.is_file():
        return candidate
    return bundle_dir / legacy_name


def apply_blog_blocks(sections: list[dict[str, Any]], blog_outlines: dict[str, dict[str, Any] | None]) -> None:
    for sec in sections:
        sid = str(sec.get("id") or "")
        blocks: dict[str, list[dict[str, Any]]] = {}
        meta: dict[str, dict[str, str]] = {}
        for lang, outline in blog_outlines.items():
            if not outline:
                continue
            outline_blocks = outline.get("blocks") if isinstance(outline.get("blocks"), list) else []
            picked = blocks_for_section(sid, outline_blocks)
            if picked:
                blocks[lang] = picked
            meta[lang] = {
                "title": str(outline.get("title") or sec.get("label") or slug_label(sid)),
                "subtitle": str(outline.get("subtitle") or ""),
            }
        if blocks:
            sec["blog"] = {"blocks": blocks, "meta": meta}


def enrich_slides_from_script(slides: list[dict[str, Any]], script_sections: list[dict[str, Any]]) -> None:
    for idx, slide in enumerate(slides):
        if idx >= len(script_sections):
            continue
        sec = script_sections[idx]
        if sec.get("id"):
            slide["id"] = str(sec["id"])
        if sec.get("heading"):
            slide["label"] = str(sec["heading"])


def section_docs(poster_dir: Path) -> list[dict[str, str]]:
    sections_doc = load_json(bundle_json_path(poster_dir, "sections", "sections.json"), {})
    sections = []
    title = str(sections_doc.get("title") or "").strip()
    sections.append({"id": "title", "label": "Title", "heading": title or "Title"})
    for sec in sections_doc.get("sections", []):
        if not isinstance(sec, dict) or not sec.get("id"):
            continue
        sections.append(
            {
                "id": str(sec["id"]),
                "label": str(sec.get("heading") or slug_label(str(sec["id"]))),
                "heading": str(sec.get("heading") or ""),
            }
        )
    return sections


def load_section_slide_map(path: Path | None, slides: list[dict[str, Any]]) -> dict[str, list[int]]:
    if path is None:
        return {}
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        raise SystemExit(f"section slide map must be a JSON object: {path}")
    slide_lookup: dict[str, int] = {}
    for slide in slides:
        index = int(slide["index"])
        candidates = [
            str(index),
            f"slide-{index}",
            str(slide.get("id") or ""),
            str(slide.get("label") or ""),
        ]
        for candidate in candidates:
            key = normalize_section_id(candidate)
            if key:
                slide_lookup[key] = index
    out: dict[str, list[int]] = {}
    for key, value in payload.items():
        if not isinstance(value, list):
            raise SystemExit(f"section slide map entry must be a list: {key}")
        indexes: list[int] = []
        for item in value:
            if isinstance(item, int):
                indexes.append(item)
                continue
            if isinstance(item, str):
                stripped = item.strip()
                if stripped.isdigit():
                    indexes.append(int(stripped))
                    continue
                lookup_key = normalize_section_id(stripped)
                if lookup_key in slide_lookup:
                    indexes.append(slide_lookup[lookup_key])
                    continue
            raise SystemExit(
                f"section slide map entry {key!r} references unknown slide/section id: {item!r}"
            )
        out[str(key)] = sorted(set(indexes))
    return out


def infer_slide_map(slides: list[dict[str, Any]], sections: list[dict[str, str]]) -> dict[str, list[int]]:
    section_ids = {sec["id"] for sec in sections}
    out: dict[str, list[int]] = {sid: [] for sid in section_ids}
    for sid, defaults in CANONICAL_DEFAULT_MAP.items():
        if sid in section_ids:
            out[sid] = [idx for idx in defaults if 1 <= idx <= len(slides)]

    slide_text = {
        slide["index"]: " ".join([str(slide.get("id", "")), str(slide.get("label", ""))]).lower()
        for slide in slides
    }
    for sid, keywords in KEYWORD_MAP:
        if sid not in section_ids or out.get(sid):
            continue
        for index, text in slide_text.items():
            if any(keyword in text for keyword in keywords):
                out.setdefault(sid, []).append(index)
    return {sid: sorted(set(indexes)) for sid, indexes in out.items()}


def write_download_zip(files: list[tuple[Path, Path]], destination: Path) -> bool:
    if not files:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, archive_name in files:
            archive.write(path, archive_name.as_posix())
    return True


def build_downloads(
    *,
    outdir: Path,
    poster_final_dir: Path | None,
    blog_final_dir: Path | None,
    video_final_dir: Path | None,
    download_mode: str = "materialized",
) -> list[dict[str, str]]:
    """Build legacy ZIPs or an on-demand manifest, plus fixed viewer links."""
    outdir = Path(outdir)
    sources = {
        "poster": Path(poster_final_dir).resolve() if poster_final_dir else None,
        "video": Path(video_final_dir).resolve() if video_final_dir else None,
        "blog": Path(blog_final_dir).resolve() if blog_final_dir else None,
    }
    available = {
        module: source
        for module, source in sources.items()
        if source is not None and source.is_dir()
    }
    resolved_sources = set(available.values())
    if download_mode == "materialized" or len(resolved_sources) != 1:
        manifest_root = outdir.resolve()
    else:
        manifest_root = next(iter(resolved_sources))
    download_manifest = build_download_manifest(
        bundle_root=manifest_root,
        poster_source=available.get("poster"),
        video_source=available.get("video"),
        blog_source=available.get("blog"),
        delivery=download_mode,
    )
    if download_mode == "on_demand":
        issues = validate_download_manifest(
            download_manifest,
            bundle_root=manifest_root,
            require_sources=True,
        )
        if issues:
            first = issues[0]
            raise SystemExit(
                f"Cannot build on-demand Reel downloads: {first['code']}: {first['message']}"
            )
        downloads_dir = outdir / DOWNLOADS_DIR
        if downloads_dir.exists():
            shutil.rmtree(downloads_dir)
        write_download_manifest(outdir / DOWNLOAD_MANIFEST_PATH, download_manifest)
        return archive_links(download_mode)

    downloads_dir = outdir / DOWNLOADS_DIR
    downloads: list[dict[str, str]] = []
    if available:
        if (
            download_manifest.get("all_package_version")
            == DOWNLOAD_ALL_PACKAGE_VERSION
        ):
            all_files = [
                (path, relative)
                for path, relative, _source in selected_all_package_files(
                    outdir,
                    poster_source=available.get("poster"),
                    video_source=available.get("video"),
                    blog_source=available.get("blog"),
                )
            ]
        elif len(resolved_sources) == 1:
            source = next(iter(resolved_sources))
            union: dict[str, tuple[Path, Path]] = {}
            for module in available:
                for path, relative in selected_files(source, module=module):
                    union[relative.as_posix()] = (path, relative)
            all_files = list(union.values())
        else:
            all_files = []
            for module, source in available.items():
                all_files.extend(
                    (path, Path(module) / relative)
                    for path, relative in selected_files(source, module=None)
                )
        all_path = downloads_dir / ARCHIVE_META["all"]["filename"]
        if write_download_zip(all_files, all_path):
            downloads.append({
                "label": ARCHIVE_META["all"]["label"],
                "href": rel_to(all_path, outdir),
            })

    source_counts: dict[Path, int] = {}
    for source in available.values():
        source_counts[source] = source_counts.get(source, 0) + 1
    for module in ("poster", "video", "blog"):
        source = available.get(module)
        if source is None:
            continue
        shared = source_counts[source] > 1
        archive_path = downloads_dir / ARCHIVE_META[module]["filename"]
        if write_download_zip(
            selected_files(source, module=module if shared else None),
            archive_path,
        ):
            downloads.append({
                "label": ARCHIVE_META[module]["label"],
                "href": rel_to(archive_path, outdir),
            })
    write_download_manifest(outdir / DOWNLOAD_MANIFEST_PATH, download_manifest)
    return downloads


def build_alignment(
    *,
    poster_dir: Path,
    outdir: Path,
    slides: list[dict[str, Any]],
    override_map: dict[str, list[int]],
    blog_outlines: dict[str, dict[str, Any] | None],
    downloads: list[dict[str, str]],
    download_delivery: str,
) -> dict[str, Any]:
    sections = section_docs(poster_dir)
    auto_map = infer_slide_map(slides, sections)
    slide_by_index = {slide["index"]: slide for slide in slides}
    title = ""
    sections_json = load_json(bundle_json_path(poster_dir, "sections", "sections.json"), {})
    if isinstance(sections_json, dict):
        title = str(sections_json.get("title") or "")

    aligned_sections = []
    for sec in sections:
        sid = sec["id"]
        indexes = override_map.get(sid, auto_map.get(sid, []))
        slide_targets = []
        for idx in indexes:
            if idx not in slide_by_index:
                continue
            slide = slide_by_index[idx]
            slide_targets.append(
                {
                    "slide_index": idx,
                    "slide_id": slide.get("id", f"slide-{idx}"),
                    "target": f"#slide-{idx}",
                }
            )
        poster_selector = ".titlebar" if sid == "title" else f"[data-section='{sid}']"
        aligned_sections.append(
            {
                "id": sid,
                "label": sec["label"],
                "poster": {
                    "artifact": f"{POSTER_DIR}/poster.html",
                    "selector": poster_selector,
                },
                "slide_indices": [target["slide_index"] for target in slide_targets],
                "slides": slide_targets,
            }
        )
    apply_blog_blocks(aligned_sections, blog_outlines)

    return {
        "schema_version": SCHEMA_VERSION,
        "viewer_version": VIEWER_VERSION,
        "template_version": TEMPLATE_VERSION,
        "created_at": utc_now(),
        "title": title,
        "artifacts": {
            "poster": f"{POSTER_DIR}/poster.html",
            "slides_dir": SLIDES_DIR,
        },
        "download_delivery": download_delivery,
        "downloads": downloads,
        "slides": [
            {
                "index": slide["index"],
                "id": slide.get("id", f"slide-{slide['index']}"),
                "label": slide.get("label", f"Slide {slide['index']}"),
                "src": slide["src"],
                "source": slide["source"],
            }
            for slide in slides
        ],
        "sections": aligned_sections,
    }


def build_manifest(alignment: dict[str, Any]) -> dict[str, Any]:
    files = {
        "reel": "reel.html",
        "content_alignment": "content_alignment.json",
        "poster_dir": POSTER_DIR,
        "slides_dir": SLIDES_DIR,
        "blog_figures_dir": BLOG_FIGURES_DIR,
        "media_dir": "assets/media",
        "downloads_manifest": DOWNLOAD_MANIFEST_PATH.as_posix(),
        "ui_dir": UI_DIR,
    }
    if alignment.get("download_delivery") == "materialized":
        files["downloads_dir"] = DOWNLOADS_DIR
    return {
        "schema_version": "paper2reel.v1",
        "layout": LAYOUT_VERSION,
        "created_at": utc_now(),
        "local_open": {
            "supported": True,
            "runtime": LOCAL_OPEN_RUNTIME,
            "entrypoint": "reel.html",
            "requires_bundle_folder": True,
            "poster_runtime": "iframe.srcdoc under file:; iframe.src under http:",
        },
        "files": files,
        "counts": {
            "sections": len(alignment.get("sections") or []),
            "slides": len(alignment.get("slides") or []),
            "downloads": len(alignment.get("downloads") or []),
        },
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--poster-dir", required=True, type=Path,
                    help="paper2poster bundle directory containing poster.html and assets/meta/sections.json")
    ap.add_argument("--slides-dir", required=True, type=Path,
                    help="Directory containing slide PNG/JPG/SVG frames")
    ap.add_argument("--script-json", type=Path,
                    help="Optional TTS script JSON whose sections order names the slides")
    ap.add_argument("--section-slide-map", type=Path,
                    help="Optional JSON object mapping canonical section ids to 1-based slide indexes")
    ap.add_argument("--blog-outline-en", type=Path,
                    help="Optional paper2blog English outline JSON to show in section modals")
    ap.add_argument("--blog-outline-zh", type=Path,
                    help="Optional paper2blog Chinese outline JSON to show in section modals")
    ap.add_argument("--blog-figures-dir", type=Path,
                    help="Optional paper2blog figure directory to copy into the reel bundle")
    ap.add_argument("--download-poster-dir", type=Path,
                    help="Optional paper2poster bundle directory to zip for the top menu download")
    ap.add_argument("--download-blog-dir", type=Path,
                    help="Optional paper2blog bundle directory to zip for the top menu download")
    ap.add_argument("--download-video-dir", type=Path,
                    help="Optional paper2video bundle directory to zip for the top menu download")
    ap.add_argument(
        "--download-mode",
        choices=("materialized", "on_demand"),
        default="materialized",
        help=(
            "materialized writes the legacy ZIPs; on_demand writes only "
            "assets/meta/reel_downloads.json for a dynamic endpoint"
        ),
    )
    ap.add_argument("--outdir", required=True, type=Path,
                    help="Output reel bundle directory")
    ap.add_argument("--mathjax-cache", type=Path, default=default_mathjax_cache_dir(),
                    help="Cache dir for MathJax copied into local-open bundles when poster.html references CDN MathJax")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    poster_dir = args.poster_dir.resolve()
    slides_dir = args.slides_dir.resolve()
    outdir = args.outdir.resolve()
    script_json = args.script_json.resolve() if args.script_json else None
    section_slide_map = args.section_slide_map.resolve() if args.section_slide_map else None
    blog_outline_en = args.blog_outline_en.resolve() if args.blog_outline_en else None
    blog_outline_zh = args.blog_outline_zh.resolve() if args.blog_outline_zh else None
    blog_figures_dir = args.blog_figures_dir.resolve() if args.blog_figures_dir else None
    download_poster_dir = args.download_poster_dir.resolve() if args.download_poster_dir else None
    download_blog_dir = args.download_blog_dir.resolve() if args.download_blog_dir else None
    download_video_dir = args.download_video_dir.resolve() if args.download_video_dir else None
    mathjax_cache = args.mathjax_cache.expanduser().resolve()

    clean_dir(outdir)
    for rel_dir in ("assets/meta", "assets/meta/reports", "assets/meta/previews"):
        (outdir / rel_dir).mkdir(parents=True, exist_ok=True)
    copy_poster_bundle(poster_dir, outdir)
    copy_ui_assets(outdir)
    poster_srcdoc_html = prepare_poster_for_local_open(outdir / POSTER_DIR / "poster.html", mathjax_cache)
    blog_asset_map = copy_blog_assets(outdir, blog_figures_dir)
    slide_files = discover_slide_files(slides_dir)
    slides = copy_slides(slide_files, outdir)
    enrich_slides_from_script(slides, load_script_sections(script_json))
    downloads = build_downloads(
        outdir=outdir,
        poster_final_dir=download_poster_dir,
        blog_final_dir=download_blog_dir,
        video_final_dir=download_video_dir,
        download_mode=args.download_mode,
    )
    alignment = build_alignment(
        poster_dir=poster_dir,
        outdir=outdir,
        slides=slides,
        override_map=load_section_slide_map(section_slide_map, slides),
        blog_outlines={
            "en": load_blog_outline(blog_outline_en, blog_asset_map),
            "zh": load_blog_outline(blog_outline_zh, blog_asset_map),
        },
        downloads=downloads,
        download_delivery=args.download_mode,
    )
    write_json(outdir / "content_alignment.json", alignment)
    write_json(outdir / "manifest.json", build_manifest(alignment))
    html = render_reel_html(alignment, poster_srcdoc_html)
    (outdir / "reel.html").write_text(html, encoding="utf-8")

    # Rebuild after the two Reel root files exist. The bootstrap publisher
    # rebuilds once more after timeline media is copied into the final bundle.
    build_downloads(
        outdir=outdir,
        poster_final_dir=download_poster_dir,
        blog_final_dir=download_blog_dir,
        video_final_dir=download_video_dir,
        download_mode=args.download_mode,
    )

    print(f"[paper2reel] wrote {outdir / 'reel.html'}")
    print(f"[paper2reel] wrote {outdir / 'content_alignment.json'}")
    print(f"[paper2reel] wrote {outdir / 'manifest.json'}")
    print(f"[paper2reel] sections: {len(alignment['sections'])}")
    print(f"[paper2reel] slides: {len(alignment['slides'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
