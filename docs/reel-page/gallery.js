(function () {
"use strict";

// ---------- helpers ----------
function esc(s){
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function t(key){ const d = (window.I18N && window.I18N[window.LANG]) || {}; return d[key] !== undefined ? d[key] : key; }
// Compose a URL to a heavy per-run asset from a record-relative path (rel.*),
// which already encodes the run's layout (nested <slug>/<slug>/… or root <slug>/…).
function assetURL(rel){ return `${ASSET_BASE}/${rel}`; }
// Poster thumbnail URL — from the CDN (POSTER_BASE) if set, else the bundled relative path.
function posterURL(e){
  const name = String(e.poster_thumb || "").split("/").pop();
  return (typeof POSTER_BASE !== "undefined" && POSTER_BASE) ? `${POSTER_BASE}/${name}` : e.poster_thumb;
}

const BY_SLUG = Object.fromEntries(GALLERY_DATA.map(e => [e.slug, e]));
// Featured, in curated order, silently dropping any slug without data.
const FEATURED = FEATURED_SLUGS.map(s => BY_SLUG[s]).filter(Boolean);

// ---------- current filtered set ----------
function filtered(){
  const q = document.getElementById("searchbox").value.trim().toLowerCase();
  if (!q) return FEATURED;
  return FEATURED.filter(e =>
    (e.title||"").toLowerCase().includes(q) ||
    (e.authors||"").toLowerCase().includes(q) ||
    (e.venue||"").toLowerCase().includes(q) ||
    (e.source_label||"").toLowerCase().includes(q) ||
    (e.hook||"").toLowerCase().includes(q)
  );
}

// ---------- a single poster tile ----------
function tileHTML(e){
  const ar = (e.w && e.h) ? ` style="aspect-ratio:${e.w}/${e.h}"` : "";
  return `<div class="tile" data-slug="${esc(e.slug)}" title="${esc(e.title)}">
    <img${ar} data-src="${esc(posterURL(e))}" alt="${esc(e.title)}"/>
    <div class="play"><span>▶</span></div>
    <div class="cap">${esc(e.title)}</div>
  </div>`;
}

// ---------- lazy image loading ----------
// With 100–200+ posters (each row duplicated for the seamless loop), eager loading
// is the bottleneck. Load a poster only as its tile nears the viewport; the marquee
// then spreads loads across the first scroll cycle. Layout stays stable because each
// <img> reserves space via aspect-ratio, so scrollWidth (loop sizing) is correct now.
const _io = ("IntersectionObserver" in window)
  ? new IntersectionObserver((entries, obs) => {
      entries.forEach(en => {
        if (!en.isIntersecting) return;
        const img = en.target, ds = img.dataset.src;
        if (ds){
          img.addEventListener("load", () => img.classList.add("loaded"), { once: true });
          img.src = ds;
          img.removeAttribute("data-src");
        }
        obs.unobserve(img);
      });
    }, { rootMargin: "400px" })
  : null;
function lazyObserve(scope){
  const imgs = (scope || document).querySelectorAll("img[data-src]");
  if (!_io){ imgs.forEach(i => { i.src = i.dataset.src; i.classList.add("loaded"); i.removeAttribute("data-src"); }); return; }
  imgs.forEach(i => _io.observe(i));
}

// ---------- render: wall (one auto-scrolling row per source) ----------
function renderWall(data){
  const host = document.getElementById("wall-view");
  if (!data.length){ host.innerHTML = `<div class="empty-note">${esc(t("gallery_lead"))}</div>`; return; }
  // group by source, preserving first-seen order (Paper2Poster, then MSRA-2026)
  const order = [], groups = {};
  data.forEach(e => {
    const k = e.source || "other";
    if (!groups[k]){ groups[k] = { label: e.source_label || k, url: e.source_url || "", items: [] }; order.push(k); }
    groups[k].items.push(e);
  });
  const multi = order.length > 1;   // per-row source labels only when >1 source
  host.innerHTML = order.map((k, i) => {
    const g = groups[k];
    const ref = g.url ? `<a class="wl-ref" href="${esc(g.url)}" target="_blank" rel="noopener" title="${esc(g.url)}">[1]</a>` : "";
    const lbl = multi ? `<div class="wall-lbl"><span class="wl-name">${esc(g.label)}</span>${ref}<span class="wl-count">${g.items.length}</span></div>` : "";
    return `<div class="wall-row">${lbl}<div class="wall-wrap">
      <button class="cnav prev" data-target="wall-${i}" aria-label="scroll left"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6"/></svg></button>
      <div class="wall" id="wall-${i}">${g.items.map(tileHTML).join("")}</div>
      <button class="cnav next" data-target="wall-${i}" aria-label="scroll right"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6"/></svg></button>
    </div></div>`;
  }).join("");
  setupAutoScroll();
  lazyObserve(host);
}

// ---------- render: grid ----------
function renderGrid(data){
  const host = document.getElementById("grid-view");
  host.innerHTML = data.length ? data.map(tileHTML).join("") : `<div class="empty-note">—</div>`;
  lazyObserve(host);
}

function renderCount(data){
  const el = document.getElementById("count-note");
  if (el) el.textContent = t("count_tpl").replace("{n}", data.length);
}

function renderAll(){
  const data = filtered();
  renderWall(data);
  renderGrid(data);
  renderCount(data);
}

// ---------- auto-scroll marquee (pauses on hover so the zoom is usable) ----------
const REDUCE_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEED = 0.4; // px/frame
let tracks = [];
function wrapPhase(value, period){
  return ((value % period) + period) % period;
}
function setupAutoScroll(){
  tracks = [];
  document.querySelectorAll("#wall-view .wall").forEach((track, idx) => {
    if (track.dataset.looping === "1"){
      // Already duplicated + measured: re-measure the period (tile widths / padding can
      // change on resize) without duplicating the content a second time, and re-attach
      // with the current position so the phase stays in sync with where the row is.
      const kids = track.children;
      const n = track.children.length / 2;
      const period = kids[n] ? kids[n].offsetLeft - kids[0].offsetLeft : track.scrollWidth / 2;
      if (period > 0) track.dataset.period = String(period);
      tracks.push({ el: track, period: +track.dataset.period, paused: false, dir: +track.dataset.dir, position: track.scrollLeft, _lastWritten: track.scrollLeft });
      return;
    }
    if (track.scrollWidth <= track.clientWidth + 4) return; // fits, no loop needed
    track.style.scrollBehavior = "auto";
    const originalCount = track.children.length;
    if (!originalCount) return;
    track.insertAdjacentHTML("beforeend", track.innerHTML); // duplicate for a seamless wrap
    // True loop period = distance between a tile and its clone. scrollWidth is WRONG here
    // because .wall has horizontal padding, which would make every wrap visibly jump.
    const kids = track.children;
    const period = kids[originalCount]
      ? kids[originalCount].offsetLeft - kids[0].offsetLeft
      : track.scrollWidth / 2;
    if (period <= 0) return;
    const dir = idx % 2 ? -1 : 1;                           // alternate row directions
    const position = dir < 0 ? period : 0;
    track.scrollLeft = position;
    const state = { el: track, originalCount, period, position, paused: false, dir, _lastWritten: position };
    track.dataset.looping = "1";
    track.dataset.period = String(period);
    track.dataset.dir = String(dir);
    // Manual scrolls (arrow buttons, touch, wheel) must resync the phase accumulator,
    // otherwise the next tick would snap back to the stale phase. Our own writes are
    // detected by comparing against the last value we wrote.
    track.addEventListener("scroll", () => {
      const st = tracks.find(s => s.el === track);
      if (st && Math.abs(track.scrollLeft - st._lastWritten) > 0.5) st.position = track.scrollLeft;
    });
    // Pause ONLY while the cursor is over an actual poster tile — not the gaps/padding.
    // Look the state up by element instead of closing over `state`: setupAutoScroll is
    // re-run on resize and replaces the state objects, so a stale closure would keep
    // mutating an object the tick loop no longer reads (hover-pause silently breaks).
    track.addEventListener("mousemove", (e) => {
      const st = tracks.find(s => s.el === track);
      if (st) st.paused = !!(e.target.closest && e.target.closest(".tile"));
    });
    track.addEventListener("mouseleave", () => {
      const st = tracks.find(s => s.el === track);
      if (st) st.paused = false;
    });
    // Pause the marquee while the cursor is over a left/right arrow so its scroll is clean.
    const wrap = track.closest(".wall-wrap");
    if (wrap) wrap.querySelectorAll(".cnav").forEach(nav => {
      nav.addEventListener("mouseenter", () => {
        const st = tracks.find(s => s.el === track);
        if (st) st.paused = true;
      });
      nav.addEventListener("mouseleave", () => {
        const st = tracks.find(s => s.el === track);
        if (st) st.paused = false;
      });
    });
    tracks.push(state);
  });
}
let wallResizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(wallResizeTimer);
  wallResizeTimer = setTimeout(() => {
    tracks.forEach(s => {
      const kids = s.el.children;
      const period = kids[s.originalCount]
        ? kids[s.originalCount].offsetLeft - kids[0].offsetLeft
        : s.period;
      if (period <= 0) return;
      s.period = period;
      s.position = wrapPhase(s.el.scrollLeft, period);
      s._lastWritten = s.el.scrollLeft;
    });
  }, 150);
});
(function tick(){
  if (!REDUCE_MOTION) tracks.forEach(s => {
    // Keep the floating-point phase in JS. Chromium rounds sub-pixel scrollLeft
    // writes, so deriving every frame from the DOM would discard SPEED entirely.
    if (s.paused){
      s.position = wrapPhase(s.el.scrollLeft, s.period);
      s._lastWritten = s.el.scrollLeft;
      return;
    }
    const next = s.position + SPEED * s.dir;
    // Wrap by exactly one period, and ONLY on the edge this row is travelling toward.
    // Checking both edges makes each wrap land on the other edge's trigger -> per-frame ping-pong.
    s.position = s.dir > 0
      ? (next >= s.period ? next - s.period : next)
      : (next <= 0 ? next + s.period : next);
    s._lastWritten = Math.round(s.position);
    s.el.scrollLeft = s._lastWritten;
  });
  requestAnimationFrame(tick);
})();

// Re-measure on resize: the loop period depends on tile widths, and a row that fit at
// one width can overflow at a narrower one. setupAutoScroll is idempotent, so
// already-looping rows keep their duplicated content and only get re-synced.
let marqueeResizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(marqueeResizeTimer);
  marqueeResizeTimer = setTimeout(setupAutoScroll, 150);
});

// ---------- lightbox: show the reel directly ----------
let openSlug = null;
function openReel(slug){
  const e = BY_SLUG[slug];
  if (!e) return;
  openSlug = slug;
  document.getElementById("lb-title").textContent = e.title;

  const frame = document.getElementById("lb-reel-el");
  const fallback = document.getElementById("lb-fallback");
  const openTab = document.getElementById("lb-open-tab");
  const loading = document.getElementById("lb-loading");
  if (e.has.reel){
    const url = assetURL(e.rel.reel);
    frame.hidden = false; fallback.hidden = true;
    loading.classList.add("on");                       // spinner until the reel is fully loaded
    frame.onload = () => { setTimeout(() => loading.classList.remove("on"), 250); };
    clearTimeout(loading._t); loading._t = setTimeout(() => loading.classList.remove("on"), 20000);
    frame.src = url;
    openTab.href = url; openTab.hidden = false;
  } else {
    // no reel for this run -> fall back to the poster image
    loading.classList.remove("on");
    frame.hidden = true; frame.onload = null; frame.src = "about:blank";
    fallback.hidden = false;
    fallback.innerHTML = `<img src="${esc(posterURL(e))}" alt="${esc(e.title)}"/>`;
    openTab.hidden = true;
  }

  document.getElementById("lb").classList.add("show");
  document.body.style.overflow = "hidden";
}

function closeDetail(){
  const frame = document.getElementById("lb-reel-el");
  if (frame){ frame.onload = null; frame.src = "about:blank"; } // stop playing video/audio inside the reel
  const loading = document.getElementById("lb-loading");
  if (loading){ clearTimeout(loading._t); loading.classList.remove("on"); }
  document.getElementById("lb").classList.remove("show");
  document.body.style.overflow = "";
  openSlug = null;
}

// ---------- view toggle ----------
function setView(v){
  document.getElementById("btn-wall").classList.toggle("active", v === "wall");
  document.getElementById("btn-grid").classList.toggle("active", v === "grid");
  document.getElementById("wall-view").classList.toggle("off", v !== "wall");
  document.getElementById("grid-view").classList.toggle("on", v === "grid");
}

// ---------- events ----------
document.addEventListener("click", (ev) => {
  const nav = ev.target.closest(".cnav");
  if (nav){
    const track = document.getElementById(nav.dataset.target);
    if (track){
      // Pause this row's marquee briefly, else its per-frame scrollLeft writes cancel the smooth scroll.
      const st = tracks.find(s => s.el === track);
      if (st){ st.paused = true; clearTimeout(st._resume); st._resume = setTimeout(() => { st.paused = false; }, 900); }
      track.scrollBy({ left: (nav.classList.contains("prev") ? -1 : 1) * track.clientWidth * 0.8, behavior: "smooth" });
    }
    return;
  }
  const tile = ev.target.closest(".tile");
  if (tile){ openReel(tile.dataset.slug); return; }
  if (ev.target.id === "lb-close" || ev.target === document.getElementById("lb")) closeDetail();
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDetail(); });

document.getElementById("btn-wall").addEventListener("click", () => setView("wall"));
document.getElementById("btn-grid").addEventListener("click", () => setView("grid"));

let searchTimer;
document.getElementById("searchbox").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderAll, 120);
});

// language switch: captions are language-agnostic; only the counter needs refreshing
window.onLanguageChange = () => { renderCount(filtered()); };

// ---------- init ----------
renderAll();

})();
