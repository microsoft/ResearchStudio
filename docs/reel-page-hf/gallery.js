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
function assetURL(rel){
  const value = String(rel || "");
  return /^https:\/\//i.test(value) ? value : `${ASSET_BASE}/${value}`;
}
// Poster thumbnail URL — from the CDN (POSTER_BASE) if set, else the bundled relative path.
function posterURL(e){
  const source = String(e.poster_thumb || "");
  if (/^https:\/\//i.test(source)) return source;
  const name = source.split("/").pop();
  return (typeof POSTER_BASE !== "undefined" && POSTER_BASE) ? `${POSTER_BASE}/${name}` : e.poster_thumb;
}

const BENCHMARK_BY_SLUG = Object.fromEntries(GALLERY_DATA.map(e => [e.slug, e]));
const BENCHMARK_FEATURED = FEATURED_SLUGS.map(s => BENCHMARK_BY_SLUG[s]).filter(Boolean);
const DAILY_PREVIEW_ENABLED = new URLSearchParams(window.location.search).get("daily-preview") === "1"
  || (typeof DAILY_PREVIEW_DEFAULT !== "undefined" && DAILY_PREVIEW_DEFAULT);
const DAILY_EDITION_RETENTION_DAYS = 7;
const DAILY_EDITIONS = new Map();
let ACTIVE_DAILY_DATE = "";
let DAILY_FEATURED = [];
let FEATURED = BENCHMARK_FEATURED.slice();
let BY_SLUG = { ...BENCHMARK_BY_SLUG };
const DAILY_ENGAGEMENT = new Map();

function formatEditionDate(value){
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(match[3])} ${months[Number(match[2]) - 1]} ${match[1]}`;
}

function normalizeDailyPayload(payload, allowPartial){
  if (!payload || !Array.isArray(payload.papers)) return [];
  if (!allowPartial && (payload.status !== "done" || payload.papers.length !== 10)) return [];
  const date = String(payload.date || "");
  const dateLabel = formatEditionDate(date);
  return payload.papers.map(paper => {
    const token = String(paper.token || "");
    const paperId = String(paper.paper_id || "");
    const rank = Number(paper.rank);
    const poster = String(paper.poster_url || "");
    const reel = String(paper.reel_url || "");
    const result = String(paper.result_url || "");
    if (!token || !paperId || !Number.isInteger(rank) || !poster) return null;
    const embedReady = paper.embed_ready !== false && /^https:\/\/researchstudio\.site\/daily-reels\//.test(reel);
    return {
      id: `hf-${date}-${rank}`,
      slug: `hf-${date}-${rank}-${paperId}`,
      source: "hf_daily",
      source_label: "Hugging Face Daily Papers",
      source_url: `https://huggingface.co/papers/date/${date}`,
      source_ref_label: "source",
      source_count_label: "Top-10",
      source_date: date,
      source_note: dateLabel,
      title: String(paper.title || paperId),
      authors: Array.isArray(paper.authors) ? paper.authors.join(", ") : String(paper.authors || ""),
      venue: `Hugging Face Daily Papers · ${dateLabel}`,
      paper_url: String(paper.hf_url || paper.arxiv_url || ""),
      hook: String(paper.summary || ""),
      poster_thumb: poster,
      w: 2016,
      h: 1210,
      rank,
      token,
      result_url: result,
      embed_ready: embedReady,
      has: { reel: Boolean(reel) && embedReady },
      rel: { reel }
    };
  }).filter(Boolean).sort((a, b) => a.rank - b.rank);
}

function activateDailyEdition(date){
  if (!DAILY_EDITIONS.has(date)) return false;
  ACTIVE_DAILY_DATE = date;
  DAILY_FEATURED = DAILY_EDITIONS.get(date);
  FEATURED = BENCHMARK_FEATURED.concat(DAILY_FEATURED);
  BY_SLUG = Object.fromEntries(FEATURED.map(entry => [entry.slug, entry]));
  return true;
}

function installDailyEntries(entries, makeActive = true){
  if (!entries.length) return false;
  const date = String(entries[0].source_date || "");
  if (!date) return false;
  DAILY_EDITIONS.set(date, entries);
  entries.forEach(entry => {
    if (!DAILY_ENGAGEMENT.has(entry.token)) {
      DAILY_ENGAGEMENT.set(entry.token, {
        state: { liked: false, disliked: false },
        counts: { liked: 0, disliked: 0 },
        pending: false
      });
    }
  });
  if (makeActive || !ACTIVE_DAILY_DATE) activateDailyEdition(date);
  return true;
}

function availableDailyDates(){
  return Array.from(DAILY_EDITIONS.keys())
    .sort((a, b) => b.localeCompare(a))
    .slice(0, DAILY_EDITION_RETENTION_DAYS);
}

if (DAILY_PREVIEW_ENABLED && typeof DAILY_PAPERS_PREVIEW !== "undefined") {
  installDailyEntries(normalizeDailyPayload(DAILY_PAPERS_PREVIEW, true));
}

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
  const isDaily = e.source === "hf_daily";
  const directReel = isDaily && !e.embed_ready
    ? String((e.rel && e.rel.reel) || e.result_url || e.paper_url || "")
    : "";
  const directLink = directReel
    ? `<a class="tile-direct-link" href="${esc(directReel)}" target="_blank" rel="noopener noreferrer" aria-label="Open interactive Reel: ${esc(e.title)}"></a>`
    : "";
  const dailyControls = isDaily ? `<span class="daily-rank">HF #${esc(e.rank)}</span>
    <span class="daily-engagement" aria-label="ResearchStudio feedback">
      <button type="button" class="daily-vote" data-engagement-action="like" data-token="${esc(e.token)}" aria-label="Like this Reel" aria-pressed="false">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>
        <span data-engagement-count="liked">0</span>
      </button>
      <button type="button" class="daily-vote" data-engagement-action="dislike" data-token="${esc(e.token)}" aria-label="Dislike this Reel" aria-pressed="false">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>
        <span data-engagement-count="disliked">0</span>
      </button>
    </span>` : "";
  return `<div class="tile${isDaily ? " daily-tile" : ""}" data-slug="${esc(e.slug)}" title="${esc(e.title)}">
    ${directLink}
    ${dailyControls}
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
    if (!groups[k]){
      groups[k] = {
        label: e.source_label || k,
        url: e.source_url || "",
        refLabel: e.source_ref_label || "1",
        countLabel: e.source_count_label || "",
        note: e.source_note || "",
        hideCount: Boolean(e.source_hide_count),
        items: []
      };
      order.push(k);
    }
    groups[k].items.push(e);
  });
  const multi = order.length > 1;   // per-row source labels only when >1 source
  host.innerHTML = order.map((k, i) => {
    const g = groups[k];
    const ref = g.url ? `<a class="wl-ref" href="${esc(g.url)}" target="_blank" rel="noopener" title="${esc(g.url)}">[${esc(g.refLabel)}]</a>` : "";
    const dates = k === "hf_daily" ? availableDailyDates() : [];
    const note = dates.length
      ? `<select class="wl-date-select" data-daily-date aria-label="Hugging Face Daily Papers date">${dates.map(date => `<option value="${esc(date)}"${date === ACTIVE_DAILY_DATE ? " selected" : ""}>${esc(formatEditionDate(date))}</option>`).join("")}</select>`
      : (g.note ? `<span class="wl-date">${esc(g.note)}</span>` : "");
    const countText = g.countLabel || g.items.length;
    const count = g.hideCount ? "" : `<span class="wl-count">${esc(countText)}</span>`;
    const lbl = multi ? `<div class="wall-lbl"><span class="wl-name">${esc(g.label)}</span>${ref}${count}${note}</div>` : "";
    return `<div class="wall-row">${lbl}<div class="wall-wrap">
      <button class="cnav prev" data-target="wall-${i}" aria-label="scroll left"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6"/></svg></button>
      <div class="wall" id="wall-${i}" data-source="${esc(k)}">${g.items.map(tileHTML).join("")}</div>
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
  paintDailyEngagement();
}

// ---------- shared ResearchStudio like / dislike counts ----------
const ENGAGEMENT_CLIENT_KEY = "researchstudio:engagement-client";
function engagementClientId(){
  let clientId = "";
  try { clientId = localStorage.getItem(ENGAGEMENT_CLIENT_KEY) || ""; } catch (_) {}
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(clientId)) {
    const random = (window.crypto && typeof window.crypto.randomUUID === "function")
      ? window.crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
    clientId = `gallery_${random}`.slice(0, 64);
    try { localStorage.setItem(ENGAGEMENT_CLIENT_KEY, clientId); } catch (_) {}
  }
  return clientId;
}

function paintDailyEngagement(token){
  const entries = token ? [[token, DAILY_ENGAGEMENT.get(token)]] : Array.from(DAILY_ENGAGEMENT.entries());
  entries.forEach(([entryToken, engagement]) => {
    if (!engagement) return;
    document.querySelectorAll(`.daily-vote[data-token="${entryToken}"]`).forEach(button => {
      const action = button.dataset.engagementAction;
      const key = action === "like" ? "liked" : "disliked";
      button.setAttribute("aria-pressed", String(Boolean(engagement.state[key])));
      button.disabled = Boolean(engagement.pending);
      const count = button.querySelector(`[data-engagement-count="${key}"]`);
      if (count) count.textContent = String(Number(engagement.counts[key]) || 0);
    });
  });
}

async function loadDailyEngagement(){
  const tokens = DAILY_FEATURED.map(entry => entry.token).filter(Boolean);
  if (!tokens.length || typeof ENGAGEMENT_API_BASE === "undefined") return;
  try {
    const response = await fetch(`${ENGAGEMENT_API_BASE}/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: engagementClientId(), tokens })
    });
    if (!response.ok) throw new Error(`engagement batch ${response.status}`);
    const payload = await response.json();
    Object.entries(payload.engagement || {}).forEach(([token, value]) => {
      DAILY_ENGAGEMENT.set(token, {
        state: {
          liked: Boolean(value && value.state && value.state.liked),
          disliked: Boolean(value && value.state && value.state.disliked)
        },
        counts: {
          liked: Number(value && value.counts && value.counts.liked) || 0,
          disliked: Number(value && value.counts && value.counts.disliked) || 0
        },
        pending: false
      });
    });
    paintDailyEngagement();
  } catch (error) {
    console.warn("Daily Reel feedback is temporarily unavailable.", error);
  }
}

async function toggleDailyEngagement(token, action){
  const key = action === "like" ? "liked" : action === "dislike" ? "disliked" : "";
  const engagement = DAILY_ENGAGEMENT.get(token);
  if (!key || !engagement || engagement.pending || typeof ENGAGEMENT_API_BASE === "undefined") return;
  engagement.pending = true;
  paintDailyEngagement(token);
  try {
    const nextState = !engagement.state[key];
    const response = await fetch(`${ENGAGEMENT_API_BASE}/${encodeURIComponent(token)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: engagementClientId(), action, state: nextState })
    });
    if (!response.ok) throw new Error(`engagement update ${response.status}`);
    const payload = await response.json();
    DAILY_ENGAGEMENT.set(token, {
      state: {
        liked: Boolean(payload.state && payload.state.liked),
        disliked: Boolean(payload.state && payload.state.disliked)
      },
      counts: {
        liked: Number(payload.counts && payload.counts.liked) || 0,
        disliked: Number(payload.counts && payload.counts.disliked) || 0
      },
      pending: false
    });
  } catch (error) {
    engagement.pending = false;
    console.warn("Could not save Daily Reel feedback.", error);
  }
  paintDailyEngagement(token);
}

async function loadPublishedDailyPapers(){
  let installedPublishedEdition = false;
  if (typeof DAILY_PAPERS_API !== "undefined") {
    try {
      const response = await fetch(DAILY_PAPERS_API, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error(`daily papers ${response.status}`);
      const payload = await response.json();
      const payloads = (Array.isArray(payload.editions) ? payload.editions : [payload])
        .slice()
        .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")))
        .slice(0, DAILY_EDITION_RETENTION_DAYS);
      payloads.forEach((edition, index) => {
        const entries = normalizeDailyPayload(edition, false);
        if (entries.length !== 10) throw new Error("daily papers response is incomplete");
        installDailyEntries(entries, index === 0);
        installedPublishedEdition = true;
      });
      renderAll();
    } catch (error) {
      // A missing/in-progress edition is expected: retain the previous complete
      // edition, or the explicit local preview fixture when requested.
      if (!DAILY_PREVIEW_ENABLED) console.info("No complete Daily Papers edition is published yet.");
    }
  }
  if (installedPublishedEdition || DAILY_FEATURED.length) await loadDailyEngagement();
}

// ---------- auto-scroll marquee (pauses on hover so the zoom is usable) ----------
const REDUCE_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const SPEED = 0.4; // px/frame
let tracks = [];
function setupAutoScroll(){
  tracks = [];
  document.querySelectorAll("#wall-view .wall").forEach((track, idx) => {
    const singleWidth = track.scrollWidth;
    if (singleWidth <= track.clientWidth + 4) return; // fits, no loop needed
    track.style.scrollBehavior = "auto";
    track.insertAdjacentHTML("beforeend", track.innerHTML); // duplicate for a seamless wrap
    // Preserve the visible Top-10 ranking order; benchmark rows may continue
    // alternating directions when additional benchmark sources are present.
    const dir = track.dataset.source === "hf_daily" ? 1 : (idx % 2 ? -1 : 1);
    if (dir < 0) track.scrollLeft = singleWidth;
    const state = { el: track, singleWidth, paused: false, dir };
    // Pause ONLY while the cursor is over an actual poster tile — not the gaps/padding.
    track.addEventListener("mousemove", (e) => { state.paused = !!(e.target.closest && e.target.closest(".tile")); });
    track.addEventListener("mouseleave", () => { state.paused = false; });
    // Pause the marquee while the cursor is over a left/right arrow so its scroll is clean.
    const wrap = track.closest(".wall-wrap");
    if (wrap) wrap.querySelectorAll(".cnav").forEach(nav => {
      nav.addEventListener("mouseenter", () => { state.paused = true; });
      nav.addEventListener("mouseleave", () => { state.paused = false; });
    });
    tracks.push(state);
  });
}
(function tick(){
  if (!REDUCE_MOTION) tracks.forEach(s => {
    if (s.paused) return;
    s.el.scrollLeft += SPEED * s.dir;
    if (s.el.scrollLeft >= s.singleWidth) s.el.scrollLeft -= s.singleWidth;
    else if (s.el.scrollLeft <= 0) s.el.scrollLeft += s.singleWidth;
  });
  requestAnimationFrame(tick);
})();

// ---------- lightbox: show the reel directly ----------
let openSlug = null;
function openReel(slug){
  const e = BY_SLUG[slug];
  if (!e) return;
  // Preview entries cannot be embedded cross-origin before the edition is
  // published, but their completed Reel is still a valid top-level page.
  // Open that real interactive deliverable directly instead of presenting a
  // poster-only lightbox that looks like a dead card.
  if (e.source === "hf_daily" && !e.embed_ready) {
    const directReel = String((e.rel && e.rel.reel) || e.result_url || e.paper_url || "");
    if (directReel) window.open(directReel, "_blank", "noopener,noreferrer");
    return;
  }
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
    // Before a Daily edition is atomically published, its temporary review
    // fixture is intentionally not embeddable.  Show the real poster here and
    // keep the full result available in a new tab.  Published Daily entries use
    // the allowlisted /daily-reels/ URL and follow the normal iframe path above.
    loading.classList.remove("on");
    frame.hidden = true; frame.onload = null; frame.src = "about:blank";
    fallback.hidden = false;
    fallback.innerHTML = `<img src="${esc(posterURL(e))}" alt="${esc(e.title)}"/>`;
    const fallbackURL = e.result_url || e.paper_url || "";
    openTab.href = fallbackURL;
    openTab.hidden = !fallbackURL;
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
  if (ev.target.closest(".tile-direct-link")) return;
  const engagementButton = ev.target.closest(".daily-vote");
  if (engagementButton){
    toggleDailyEngagement(
      engagementButton.dataset.token,
      engagementButton.dataset.engagementAction
    );
    return;
  }
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

document.addEventListener("change", (ev) => {
  const picker = ev.target.closest && ev.target.closest("[data-daily-date]");
  if (!picker || !activateDailyEdition(picker.value)) return;
  renderAll();
  loadDailyEngagement();
});

let searchTimer;
document.getElementById("searchbox").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderAll, 120);
});

// language switch: captions are language-agnostic; only the counter needs refreshing
window.onLanguageChange = () => { renderCount(filtered()); };

// ---------- init ----------
renderAll();
loadPublishedDailyPapers();

})();
