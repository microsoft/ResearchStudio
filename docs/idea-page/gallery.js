(function(){
"use strict";

// ---------- helpers ----------
function esc(s){
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function para(s){ // turn \n\n paragraphs into <p>
  if (!s) return "";
  return String(s).split(/\n{2,}/).map(p => `<p>${esc(p).replace(/\n/g,"<br>")}</p>`).join("");
}
function fmtVerdict(v){
  const m = {advance:"Advance", revise:"Revise", abandon:"Abandon"};
  return m[v] || v || "—";
}
function verdictClass(v){
  return {advance:"verdict-advance", revise:"verdict-revise", abandon:"verdict-abandon"}[v] || "";
}
function feasClass(v){
  const s = String(v||"").toLowerCase();
  if (s.includes("infeasible")) return "v-infeasible";
  if (s.includes("tight")) return "v-tight";
  if (s.includes("feasible")) return "v-feasible";
  return "";
}

// ---------- shared color palette (used for both domain categories and patterns) ----------
const PALETTE = [
  "#6c5ce7","#00d4a8","#ff2d55","#ff9500","#34c759","#af52de","#00c7be",
  "#ff3b30","#5ac8fa","#ffcc00","#a2845e","#8e8e93","#30b0c7","#d70015","#ff6482",
  "#32ade6","#ff375f","#66d4cf","#bf5af2","#ff8000"
];
const colorFor = (() => {
  const map = {};
  let i = 0;
  return (key) => {
    if (!map[key]) { map[key] = PALETTE[i % PALETTE.length]; i++; }
    return map[key];
  };
})();
// pre-assign stable colors based on first appearance in data, domains first (default grouping)
(function(){
  const seen = new Set();
  GALLERY_DATA.forEach(e => { if (e.domain_category && !seen.has(e.domain_category)) { seen.add(e.domain_category); colorFor(e.domain_category); } });
  GALLERY_DATA.forEach(e => { if (e.anchor_pattern_id && !seen.has(e.anchor_pattern_id)) { seen.add(e.anchor_pattern_id); colorFor(e.anchor_pattern_id); } });
})();
// back-compat alias used throughout the render code below
const patternColor = colorFor;

// ---------- grouping (Domain or Ideation Pattern) ----------
let currentGroupBy = "domain"; // "domain" | "pattern"
function groupKeyName(e){
  return currentGroupBy === "domain"
    ? { key: e.domain_category || "Other", name: e.domain_category || "Other" }
    : { key: e.anchor_pattern_id || "outside_taxonomy", name: e.anchor_pattern_name || "Unclassified" };
}
function groupData(data){
  const groups = {};
  data.forEach(e => {
    const { key, name } = groupKeyName(e);
    if (!groups[key]) groups[key] = { name, items: [] };
    groups[key].items.push(e);
  });
  return Object.entries(groups)
    .map(([id, g]) => ({ id, name: g.name, items: g.items.sort((a,b)=>a.index-b.index) }))
    .sort((a,b) => b.items.length - a.items.length);
}

// ---------- stats ----------
function renderStats(data){
  const patterns = new Set(data.map(e => e.anchor_pattern_id)).size;
  const domains = new Set(data.map(e => e.domain_category)).size;
  const advance = data.filter(e => e.phase3.verdict === "advance").length;
  const revise = data.filter(e => e.phase3.verdict === "revise").length;
  const totalPapers = data.reduce((s,e) => s + (e.phase0.n_papers||0), 0);
  document.getElementById("stats").innerHTML = `
    <div class="stat"><b>${data.length}</b><span data-i18n="stat_cards">Idea Cards</span></div>
    <div class="stat"><b>${domains}</b><span data-i18n="stat_domains">Research Domains</span></div>
    <div class="stat"><b>${patterns}</b><span data-i18n="stat_patterns">Ideation Patterns Used</span></div>
    <div class="stat"><b>${advance}</b><span data-i18n="stat_advance">Advanced Clean</span></div>
    <div class="stat"><b>${revise}</b><span data-i18n="stat_revise">Revised After Audit</span></div>
    <div class="stat"><b>${Math.round(totalPapers/data.length)}</b><span data-i18n="stat_papers">Avg Papers Retrieved</span></div>
  `;
}

// ---------- card ----------
function cardHTML(e){
  const domColor = colorFor(e.domain_category);
  const patColor = colorFor(e.anchor_pattern_id);
  return `
  <div class="card" data-id="${e.id}">
    <div class="card-idx">#${e.id}</div>
    <div class="card-title">${esc(e.title)}</div>
    <div class="card-hook">${esc(e.hook)}</div>
    <div class="card-badges">
      <span class="badge" style="background:${domColor}">${esc(e.domain_category)}</span>
      <span class="badge badge-outline" style="border-color:${patColor};color:${patColor}">${esc(e.anchor_pattern_name)}</span>
    </div>
    <div class="card-foot">
      <span class="verdict-pill ${verdictClass(e.phase3.verdict)}">${fmtVerdict(e.phase3.verdict)}</span>
    </div>
  </div>`;
}

// ---------- carousel view ----------
function renderCarousel(data){
  const groups = groupData(data);
  const el = document.getElementById("carousel-view");
  if (!groups.length){ el.innerHTML = `<div class="empty-note">No matching ideas.</div>`; return; }
  el.innerHTML = groups.map(g => {
    const color = patternColor(g.id);
    const rid = "car_" + g.id;
    return `
    <div class="cat-row" data-key="${esc(g.id)}">
      <div class="cat-head">
        <span class="cat-dot" style="background:${color}"></span>
        <span class="cat-name">${esc(g.name)}</span>
        <span class="cat-count">${g.items.length}</span>
      </div>
      <div class="carousel-wrap">
        <div class="cnav prev" data-target="${rid}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6"/></svg></div>
        <div class="carousel" id="${rid}">${g.items.map(cardHTML).join("")}</div>
        <div class="cnav next" data-target="${rid}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6"/></svg></div>
      </div>
    </div>`;
  }).join("");
  setupCarouselAutoScroll();
}

// ---------- grid view ----------
function renderGrid(data){
  const el = document.getElementById("grid-view");
  el.innerHTML = data.length ? data.map(cardHTML).join("") : `<div class="empty-note">No matching ideas.</div>`;
}

// ---------- carousel auto-scroll (marquee, pauses on hover/drag) ----------
const REDUCE_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const CAROUSEL_SPEED = 0.45; // px per frame
let carouselTracks = [];
const carouselStateByTrack = new WeakMap();
function wrapCarouselPhase(value, period){
  return ((value % period) + period) % period;
}
// Idempotent per track: a track already set up keeps its duplicated content and its
// measured period, so this can be re-run on resize without duplicating twice.
function setupCarouselAutoScroll(){
  carouselTracks = [];
  document.querySelectorAll(".carousel").forEach(track => {
    const wrap = track.closest(".carousel-wrap");
    if (track.dataset.looping === "1"){
      // Already duplicated: re-measure the period (tile widths / padding can change on
      // resize) without duplicating again, and resync the phase to the current position.
      const n = track.children.length / 2;
      const kids = track.children;
      const measuredWidth = kids[n] ? kids[n].offsetLeft - kids[0].offsetLeft : 0;
      const singleWidth = measuredWidth > 0 ? measuredWidth : +track.dataset.period;
      const state = carouselStateByTrack.get(track);
      if (state){
        state.singleWidth = singleWidth;
        state.position = wrapCarouselPhase(track.scrollLeft, singleWidth);
        state._lastWritten = track.scrollLeft;
        track.dataset.period = String(singleWidth);
        carouselTracks.push(state);
      }
      return;
    }
    if (track.scrollWidth <= track.clientWidth + 4){
      // Whole row is on screen: it cannot scroll, so the arrows would do nothing.
      if (wrap) wrap.classList.add("no-scroll");
      return;
    }
    if (wrap) wrap.classList.remove("no-scroll");
    track.style.scrollBehavior = "auto";
    const n = track.children.length;
    track.insertAdjacentHTML("beforeend", track.innerHTML); // duplicate set for a seamless wrap
    // Measure the repeat period from the DOM rather than deriving it from scrollWidth:
    // scrollWidth includes the left and right padding, but the distance that actually
    // returns the row to an identical state is first-card-of-set-A to first-card-of-set-B.
    // The two differ by (padLeft + padRight - gap), which is invisible while the padding
    // is small and becomes a large visible jump once the track is full-bleed and the
    // left padding carries the whole content gutter.
    const kids = track.children;
    const singleWidth = kids[n] ? kids[n].offsetLeft - kids[0].offsetLeft : track.scrollWidth;
    track.dataset.looping = "1";
    track.dataset.period = String(singleWidth);
    const state = { el: track, singleWidth, position: 0, paused: false, _lastWritten: 0 };
    carouselStateByTrack.set(track, state);
    // Manual scrolls (arrow buttons, touch, wheel) must resync the phase accumulator,
    // otherwise the next tick would snap back to the stale phase. Our own writes are
    // detected by comparing against the last value we wrote.
    track.addEventListener("scroll", () => {
      const st = carouselStateByTrack.get(track);
      if (st && Math.abs(track.scrollLeft - st._lastWritten) > 0.5) st.position = track.scrollLeft;
    });
    // Look the state up by element instead of closing over `state`: setupCarouselAutoScroll
    // is re-run on resize and replaces the state objects, so a stale closure would keep
    // mutating an object the tick loop no longer reads (hover-pause silently breaks).
    track.addEventListener("mouseenter", () => {
      const st = carouselStateByTrack.get(track);
      if (st) st.paused = true;
    });
    track.addEventListener("mouseleave", () => {
      const st = carouselStateByTrack.get(track);
      if (st) st.paused = false;
    });
    track.addEventListener("pointerdown", () => {
      const st = carouselStateByTrack.get(track);
      if (st) st.paused = true;
    });
    track.addEventListener("pointerup", () => {
      const st = carouselStateByTrack.get(track);
      if (st) st.paused = false;
    });
    track.addEventListener("pointercancel", () => {
      const st = carouselStateByTrack.get(track);
      if (st) st.paused = false;
    });
    carouselTracks.push(state);
  });
}

// A row that fits at one width can overflow at a narrower one, so re-evaluate on
// resize. setupCarouselAutoScroll is idempotent, so already-looping rows are left
// alone and only newly-overflowing ones get set up.
let carouselResizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(carouselResizeTimer);
  carouselResizeTimer = setTimeout(setupCarouselAutoScroll, 150);
});
(function tickCarousels(){
  if (!REDUCE_MOTION) {
    carouselTracks.forEach(s => {
      // Keep the floating-point phase in JS. Chromium rounds sub-pixel scrollLeft
      // writes, so deriving every frame from the DOM would discard the speed.
      if (s.paused){
        s.position = wrapCarouselPhase(s.el.scrollLeft, s.singleWidth);
        s._lastWritten = s.el.scrollLeft;
        return;
      }
      // Shift by exactly one period so the wrap is phase-continuous and invisible.
      // Never clamp the landing position: clamping leaves a residual offset that
      // accumulates into a visible jump.
      const next = s.position + CAROUSEL_SPEED;
      s.position = next >= s.singleWidth ? next - s.singleWidth : next;
      s._lastWritten = Math.round(s.position);
      s.el.scrollLeft = s._lastWritten;
    });
  }
  requestAnimationFrame(tickCarousels);
})();

// ---------- source tag chip (shared) ----------
function srcTag(source){
  const cls = ["arxiv","openalex","openreview","semanticscholar"].includes(source) ? source : "other";
  return `<span class="st ${cls}">${esc(source||"other")}</span>`;
}
function verdictAccent(v){
  return {advance:"var(--green)", revise:"var(--amber)", abandon:"var(--red)"}[v] || "var(--dim)";
}

// ---------- literature tree builders (Phase 0) ----------
function buildSourceTree(p0){
  const by = p0.by_source || [];
  if (!by.length) return `<p class="muted">—</p>`;
  const rows = [`<div class="trow root"><span class="gut"></span><span class="lbl">📚 <b>${p0.n_papers||0}</b> papers retrieved across ${by.length} sources</span></div>`];
  by.forEach((s,i) => {
    const guide = i === by.length-1 ? "└─" : "├─";
    rows.push(`<div class="trow src"><span class="gut">${guide}</span><span class="lbl">${srcTag(s.source)}<b>${s.n}</b> papers</span></div>`);
  });
  return rows.join("");
}
function buildYearTree(p0){
  const Y = p0.by_year || [];
  if (!Y.length) return `<p class="muted">—</p>`;
  const rows = [`<div class="trow root"><span class="gut"></span><span class="lbl">🗓 timeline · ${esc(Y[0].year)} → ${esc(Y[Y.length-1].year)}</span></div>`];
  Y.forEach((g,gi) => {
    const lastGroup = gi === Y.length-1;
    rows.push(`<div class="trow src"><span class="gut">${lastGroup?"└─":"├─"}</span><span class="lbl"><b style="color:var(--violet)">${esc(g.year)}</b> <span class="yr">· ${g.n} papers</span></span></div>`);
    const papers = g.papers || [];
    papers.forEach((p,pi) => {
      const isLastLine = pi === papers.length-1 && !g.more;
      rows.push(`<div class="trow leaf"><span class="gut">${(lastGroup?"   ":"│  ")+(isLastLine?"└─":"├─")}</span><span class="lbl">${srcTag(p.source)}${esc(p.title)}</span></div>`);
    });
    if (g.more) rows.push(`<div class="trow leaf"><span class="gut">${(lastGroup?"   ":"│  ")}└─</span><span class="lbl"><span class="yr">…and ${g.more} more</span></span></div>`);
  });
  return rows.join("");
}
function buildDist(p0){
  const pd = p0.pattern_dist || [];
  if (!pd.length) return `<p class="muted">—</p>`;
  return pd.map(p => `<div class="bar"><span class="nm">${esc(p.pattern_name)}</span><span class="tk"><i style="width:${Math.round((p.share||0)*100)}%"></i></span><span class="ct">${p.count}</span></div>`).join("");
}

// ---------- scene: Phase 0 ----------
function renderScene0(e){
  const p0 = e.phase0;
  return `
  <div class="phase-tag"><span class="pill" style="background:var(--cyan)">PHASE 0</span> Reading and mapping the field</div>
  <div class="h">${esc(p0.topic || "First, it reads the field")}</div>
  <div class="scard"><div style="display:flex;align-items:baseline;gap:14px">
    <span class="counter">${p0.n_papers||0}</span>
    <span class="muted">papers retrieved and tagged against the 15 induced ideation patterns<br>real connector retrieval — arXiv · OpenAlex · Semantic Scholar · OpenReview</span></div></div>
  <div class="lead">the retrieved literature, by source</div>
  <div class="tree">${buildSourceTree(p0)}</div>
  <div class="lead">the same literature on a timeline, by year</div>
  <div class="tree">${buildYearTree(p0)}</div>
  <div class="lead">how those papers split across research patterns</div>
  <div class="dist">${buildDist(p0)}</div>`;
}

// ---------- scene: Phase 1 ----------
function buildClosest(list){
  if (!list || !list.length) return `<p class="muted">—</p>`;
  return list.map(a => `
    <div class="cwork ${a.is_anchor?"anchor-w":""}">
      <span class="ctag ${a.is_anchor?"anc":"sib"}">${a.is_anchor?"Anchor":"Sibling"}</span>
      <span class="cnm">${esc(a.paper_id||"")}</span>
      <div class="cres">${esc(a.summary_and_residue||"")}</div>
    </div>`).join("");
}
function renderScene1(e){
  const p1 = e.phase1;
  return `
  <div class="phase-tag"><span class="pill" style="background:var(--violet)">PHASE 1</span> Finding the bottleneck that matters</div>
  <div class="h">Where does the field actually stall?</div>
  <div class="scard bncard"><div class="bncore">${esc(p1.bottleneck_statement)}</div></div>
  <div class="lead">the closest prior work <span class="sub2">· the anchor is what this idea directly builds against</span></div>
  ${buildClosest(p1.closest_adjacent)}`;
}

// ---------- scene: Phase 2 ----------
function buildGapEntries(patterns){
  if (!patterns || !patterns.length) return `<p class="muted">—</p>`;
  return patterns.map(g => `
    <div class="entry ${g.is_anchor?"anchor-e":"sibling-e"}">
      <div class="gap"><span class="gaplabel ${g.is_anchor?"anchor":"cosel"}">${g.is_anchor?"Anchor gap":"Co-targeted"}</span>${esc(g.gap)}</div>
      <div class="movewrap"><span class="muted" style="font-size:11px">pattern ·</span> <span class="move">${esc(g.pattern_name)}</span>${g.sub_pattern?`<span class="subt">Sub-pattern: ${esc(g.sub_pattern)}</span>`:""}</div>
      <div class="how">${g.companion_pattern?`<div class="companion">+ paired with ${esc(PATTERN_NAMES[g.companion_pattern] || g.companion_pattern)}</div>`:""}<b>How it closes the gap:</b> ${esc(g.how_closed)}</div>
    </div>`).join("");
}
function renderScene2(e){
  const p2 = e.phase2;
  const diffs = (p2.differentiation_from_lit||[]).map(d => {
    if (typeof d === "string") return `<li>${esc(d)}</li>`;
    return `<li><b>${esc(d.paper_id||"")}</b> — ${esc(d.delta || d.description || "")}</li>`;
  }).join("");
  return `
  <div class="phase-tag"><span class="pill" style="background:var(--purple)">PHASE 2</span> Choosing the gaps and the pattern for each</div>
  <div class="h">Which gaps make the cut — and how do we close them?</div>
  ${buildGapEntries(e.patterns)}
  <div class="kbox" style="--acc:var(--cyan)"><span class="l">core mechanism</span><div class="v">${esc(p2.core_mechanism)}</div></div>
  <div class="kbox" style="--acc:var(--violet)"><span class="l">why this mechanism</span><div class="v">${esc(p2.core_mechanism_reasoning)}</div></div>
  <div class="kbox" style="--acc:var(--amber)"><span class="l">how we'd try to break it</span><div class="v">${esc(p2.falsification_prediction)}</div></div>
  ${diffs ? `<div class="lead">differentiation from literature</div><ul style="margin:0;padding-left:20px;font-size:12.5px;line-height:1.65">${diffs}</ul>` : ""}`;
}

// ---------- scene: Phase 3 ----------
function gapVerdictCheck(name, val, flagVerdicts){
  if (!val) return "";
  const n = (val.entries||[]).length;
  const flagged = flagVerdicts.includes(val.verdict);
  const note = `${n} gap${n===1?"":"s"} checked · verdict: ${val.verdict||"—"}. ${val.reasoning||""}`;
  return `<div class="chk ${flagged?"flag":"pass"}"><div class="ic">${flagged?"!":"✓"}</div><div class="t">${esc(name)}<small>${esc(note)}</small></div></div>`;
}
function antiPatternCheck(val){
  if (!val) return "";
  const flagged = !!val.matched_pattern_id;
  const comp = (val.composition_set||[]).join(" + ");
  const note = flagged
    ? `Matched anti-pattern: ${val.matched_pattern_id}. ${val.reasoning||""}`
    : `Composition checked (${comp || "—"}) against the reject-favored anti-pattern library — no match. ${val.reasoning||""}`;
  return `<div class="chk ${flagged?"flag":"pass"}"><div class="ic">${flagged?"!":"✓"}</div><div class="t">Anti-pattern check<small>${esc(note)}</small></div></div>`;
}
function threatBlock(val){
  if (!val) return "";
  const bits = [`<b>${esc(val.threat_paper_id||"")}</b>`, esc(val.subsumption_argument||"")].filter(Boolean).join(" — ");
  const addr = val.addressable_via ? `<div class="muted" style="margin-top:7px;color:var(--ink)"><b style="color:var(--amber)">how to handle it:</b> ${esc(val.addressable_via)}</div>` : "";
  return `<div class="threat">⚠ <b>paper-pointed threat</b> — ${bits}${addr}</div>`;
}
function renderScene3(e){
  const p3 = e.phase3;
  const c = p3.checks;
  const checksHtml = [
    gapVerdictCheck("Gap-closure reject check", c.gap_closure_reject_check, ["triggered"]),
    gapVerdictCheck("Recipe application check", c.recipe_application_check, ["bypassed"]),
    antiPatternCheck(c.anti_pattern_check),
  ].filter(Boolean).join("");
  const revTargets = (p3.revision_targets||[]).map(t => {
    if (typeof t === "string") return `<div class="tgt">${esc(t)}</div>`;
    return `<div class="tgt"><b>[${esc(t.scope||"")}] ${esc(t.field||"")}</b> — ${esc(t.issue||"")}<div class="muted" style="margin-top:6px;color:var(--ink)">→ fix: ${esc(t.fix_direction||"")}</div></div>`;
  }).join("");
  const appliedRev = (p3.applied_revisions||[]).map(r => {
    if (typeof r === "string") return `<div class="revrow">${esc(r)}</div>`;
    return `<div class="revrow"><span class="revbadge">${esc(r.outcome||"revised")}</span><span class="what">${esc(r.field||"")}</span><div class="muted" style="margin-top:8px;color:var(--ink)">${esc(r.delta_summary||"")}</div></div>`;
  }).join("");
  return `
  <div class="phase-tag"><span class="pill" style="background:var(--amber)">PHASE 3</span> Auditing and revising against the corpus</div>
  <div class="h" style="display:flex;align-items:center;gap:12px">Is the idea defensible? <span class="stamp" style="background:${verdictAccent(p3.verdict)}">${esc(fmtVerdict(p3.verdict).toUpperCase())}</span></div>
  <div class="muted" style="margin-bottom:10px">${p3.collision_hits_count||0} closely-related prior works pulled and checked against this idea</div>
  <div class="checks">${checksHtml || "<p class='muted'>—</p>"}</div>
  ${threatBlock(c.paper_pointed_threat)}
  <div class="muted" style="margin:12px 2px 0">${esc(p3.verdict_rationale)}</div>
  ${revTargets ? `<div class="lead">revision targets</div>${revTargets}` : ""}
  ${appliedRev ? `<div class="lead">applied revisions</div>${appliedRev}` : ""}`;
}

// ---------- detail panel: Phase 4 — the actual rendered idea card (verbatim markdown) ----------
// The pipeline's own deterministic templater (phase4_render) already produces the final
// idea.std.{en,zh}.md files -- we render those directly rather than re-deriving a custom
// breakdown, so what you see here is exactly what the skill itself hands back to a user.
//
// Math protection: extract every $...$/$$...$$ span BEFORE handing text to the markdown
// parser (which would otherwise mangle underscores/braces inside LaTeX), then restore each
// span as a raw DOM Text node (not via innerHTML) so characters like the "<" in "x_{<t}"
// can never be misread as the start of an HTML tag. MathJax then typesets those text nodes.
// Placeholder uses only plain alphanumerics -- deliberately avoids control characters
// (e.g. NUL), which browsers silently rewrite (observed: to a plain space) once a string
// passes through marked.parse()+innerHTML, making a control-character marker unreliable
// to match back against the live DOM.
function extractMath(md){
  const spans = [];
  const protectedMd = String(md||"").replace(/\$\$[\s\S]+?\$\$|\$[^\$\n]+?\$/g, (m) => {
    spans.push(m);
    return `zMATHPLACEHOLDERz${spans.length-1}zENDPLACEHOLDERz`;
  });
  return { protectedMd, spans };
}
function restoreMathInDom(container, spans){
  if (!spans.length) return;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  const re = /zMATHPLACEHOLDERz(\d+)zENDPLACEHOLDERz/g;
  textNodes.forEach(node => {
    re.lastIndex = 0;
    if (!re.test(node.nodeValue)) return;
    re.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0, m;
    while ((m = re.exec(node.nodeValue))) {
      if (m.index > last) frag.appendChild(document.createTextNode(node.nodeValue.slice(last, m.index)));
      frag.appendChild(document.createTextNode(spans[+m[1]]));
      last = m.index + m[0].length;
    }
    if (last < node.nodeValue.length) frag.appendChild(document.createTextNode(node.nodeValue.slice(last)));
    node.replaceWith(frag);
  });
}
function renderMdInto(containerEl, md){
  if (!md) { containerEl.innerHTML = `<p class="empty-note">This run did not produce a rendered card for this language.</p>`; return; }
  const { protectedMd, spans } = extractMath(md);
  const html = (window.marked ? marked.parse(protectedMd) : `<pre>${esc(protectedMd)}</pre>`);
  containerEl.innerHTML = `<div class="md-card"><div class="md-content">${html}</div></div>`;
  restoreMathInDom(containerEl, spans);
}

// ---------- rail (phase navigation) ----------
const RAIL = [
  {k:"0", lbl:"Read the field", acc:"var(--cyan)"},
  {k:"1", lbl:"Find the bottleneck", acc:"var(--violet)"},
  {k:"2", lbl:"Choose the pattern", acc:"var(--purple)"},
  {k:"3", lbl:"Audit & revise", acc:"var(--amber)"},
  {k:"EN", lbl:"Idea Card (EN)", acc:"var(--green)"},
  {k:"中", lbl:"Idea Card (中文)", acc:"var(--green)"},
];
let railBuilt = false;
let visitedScenes = new Set();
function buildRail(){
  const rail = document.getElementById("rail");
  rail.innerHTML = `<div class="pipetrack"></div><div class="pipeprog" id="pipeprog"></div>` +
    RAIL.map((p,i) => `<div class="node" data-i="${i}" style="--acc:${p.acc}"><div class="bead" style="--acc:${p.acc}">${esc(p.k)}</div><div class="lbl">${esc(p.lbl)}</div></div>`).join("");
  railBuilt = true;
}
function setScene(i){
  document.querySelectorAll("#rail .node").forEach((n,k) => {
    n.classList.toggle("active", k===i);
    n.classList.toggle("done", visitedScenes.has(k) && k!==i);
  });
  visitedScenes.add(i);
  document.querySelectorAll(".scene").forEach((s,k) => s.classList.toggle("on", k===i));
  const prog = document.getElementById("pipeprog");
  if (prog) prog.style.width = (5 + (i/(RAIL.length-1))*90) + "%";
  typesetMath();
}

// ---------- overlay open/close ----------
let currentExample = null;
// CSS vh/dvh units are unreliable across browsers (mobile Safari overshoots the
// real visible viewport when the address bar is showing; some embedded webviews
// resolve dvh to 0 outright). window.innerHeight is always the true, current
// visible height, so set the panel's size from it directly instead of trusting
// any viewport-unit CSS to do the right thing.
function fitPanelToViewport(){
  const panel = document.querySelector(".panel");
  const vh = window.innerHeight;
  if (!panel || !vh) return; // nothing sane to measure; let the CSS fallback stand
  const mobile = window.innerWidth <= 640;
  const margin = mobile ? 10 : 16;
  panel.style.maxHeight = Math.max(280, vh - margin) + "px";
  panel.style.height = Math.round(vh * (mobile ? 0.92 : 0.88)) + "px";
}
window.addEventListener("resize", fitPanelToViewport);
window.addEventListener("orientationchange", () => setTimeout(fitPanelToViewport, 150));

function openDetail(id){
  const e = GALLERY_DATA.find(x => x.id === id);
  if (!e) return;
  currentExample = e;
  fitPanelToViewport();
  document.getElementById("pt-title").textContent = e.title;
  document.getElementById("pt-title-zh").textContent = e.title_zh || "";
  document.getElementById("pt-hook").textContent = e.hook;
  document.getElementById("pt-badges").innerHTML =
    `<span class="badge" style="background:${colorFor(e.domain_category)}">${esc(e.domain_category)}</span>` +
    (e.patterns||[]).map(g =>
      `<span class="badge badge-outline" style="border-color:${patternColor(g.pattern_id)};color:${patternColor(g.pattern_id)}">${esc(g.pattern_name)}${g.is_anchor?" (anchor)":""}</span>`
    ).join("") + `<span class="verdict-pill ${verdictClass(e.phase3.verdict)}" style="margin-left:4px">${fmtVerdict(e.phase3.verdict)}</span>`;

  document.getElementById("scene-p0").innerHTML = renderScene0(e);
  document.getElementById("scene-p1").innerHTML = renderScene1(e);
  document.getElementById("scene-p2").innerHTML = renderScene2(e);
  document.getElementById("scene-p3").innerHTML = renderScene3(e);
  document.getElementById("scene-p4en").innerHTML = `<div class="phase-tag"><span class="pill" style="background:var(--green)">RESULT</span> Idea Card — English</div><div id="mden"></div>`;
  renderMdInto(document.getElementById("mden"), e.phase4_md_en);
  document.getElementById("scene-p4zh").innerHTML = `<div class="phase-tag"><span class="pill" style="background:var(--green)">RESULT</span> Idea Card — 中文</div><div id="mdzh"></div>`;
  renderMdInto(document.getElementById("mdzh"), e.phase4_md_zh);

  if (!railBuilt) buildRail();
  visitedScenes = new Set();
  setScene(0);

  document.getElementById("overlay").classList.add("show");
  document.body.style.overflow = "hidden";
  typesetMath();
}
function closeDetail(){
  document.getElementById("overlay").classList.remove("show");
  document.body.style.overflow = "";
}
function typesetMath(){
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetPromise([document.getElementById("overlay")]).catch(()=>{});
  }
}

// ---------- events ----------
document.addEventListener("click", (ev) => {
  const card = ev.target.closest(".card");
  if (card) { openDetail(card.dataset.id); return; }
  const nav = ev.target.closest(".cnav");
  if (nav) {
    const track = document.getElementById(nav.dataset.target);
    if (track){
      const state = carouselStateByTrack.get(track);
      if (state){
        state.paused = true;
        clearTimeout(state._resume);
        state._resume = setTimeout(() => { state.paused = false; }, 900);
      }
      track.scrollBy({left: nav.classList.contains("prev") ? -320 : 320, behavior:"smooth"});
    }
    return;
  }
  const node = ev.target.closest(".node");
  if (node && document.getElementById("rail").contains(node)) {
    setScene(+node.dataset.i);
    return;
  }
  if (ev.target.id === "panel-close" || ev.target === document.getElementById("overlay")) closeDetail();
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDetail(); });

document.getElementById("btn-carousel").addEventListener("click", () => setView("carousel"));
document.getElementById("btn-grid").addEventListener("click", () => setView("grid"));
function setView(v){
  document.getElementById("btn-carousel").classList.toggle("active", v==="carousel");
  document.getElementById("btn-grid").classList.toggle("active", v==="grid");
  document.getElementById("carousel-view").style.display = v==="carousel" ? "" : "none";
  document.getElementById("grid-view").classList.toggle("on", v==="grid");
}

function currentFilteredData(){
  const q = document.getElementById("searchbox").value.trim().toLowerCase();
  if (!q) return GALLERY_DATA;
  return GALLERY_DATA.filter(e =>
    e.title.toLowerCase().includes(q) ||
    (e.hook||"").toLowerCase().includes(q) ||
    (e.domain_category||"").toLowerCase().includes(q) ||
    (e.anchor_pattern_name||"").toLowerCase().includes(q) ||
    (e.patterns||[]).some(p => (p.pattern_name||"").toLowerCase().includes(q))
  );
}

document.getElementById("btn-group-domain").addEventListener("click", () => setGroupBy("domain"));
document.getElementById("btn-group-pattern").addEventListener("click", () => setGroupBy("pattern"));
function setGroupBy(mode){
  currentGroupBy = mode;
  document.getElementById("btn-group-domain").classList.toggle("active", mode==="domain");
  document.getElementById("btn-group-pattern").classList.toggle("active", mode==="pattern");
  const data = currentFilteredData();
  renderCarousel(data);
  renderGrid(data);
}

// ---------- jump from the sphere to a domain's row ----------
function jumpToCategory(cat){
  document.getElementById("searchbox").value = "";
  if (currentGroupBy !== "domain") setGroupBy("domain");
  else { renderCarousel(GALLERY_DATA); renderGrid(GALLERY_DATA); }
  setView("carousel");
  requestAnimationFrame(() => {
    const row = document.querySelector(`.cat-row[data-key="${CSS.escape(cat)}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "start" });
    row.classList.add("cat-row-flash");
    setTimeout(() => row.classList.remove("cat-row-flash"), 1200);
  });
}

let searchTimer;
document.getElementById("searchbox").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const filtered = currentFilteredData();
    renderCarousel(filtered);
    renderGrid(filtered);
  }, 120);
});

// ---------- domain sphere (draggable, idle-spinning 3D tag cloud) ----------
function buildSphere(){
  const wrap = document.getElementById("sphere3d");
  const inner = document.getElementById("sphereinner");
  if (!wrap || !inner) return;

  const counts = {};
  GALLERY_DATA.forEach(e => { const k = e.domain_category || "Other"; counts[k] = (counts[k]||0) + 1; });
  const cats = Object.keys(counts).sort((a,b) => counts[b]-counts[a]);
  const n = cats.length;
  const R = 155;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const tags = cats.map((cat,i) => {
    const y = n > 1 ? 1 - (i/(n-1))*2 : 0;
    const rY = Math.sqrt(Math.max(0, 1 - y*y));
    const theta = golden * i;
    return { cat, count: counts[cat], x: Math.cos(theta)*rY, y, z: Math.sin(theta)*rY };
  });

  inner.innerHTML = tags.map(t =>
    `<div class="stag" data-cat="${esc(t.cat)}" style="background:${colorFor(t.cat)}">${esc(t.cat)}<span class="n">${t.count}</span></div>`
  ).join("");

  // Labels are always billboarded (kept flat, facing the viewer) — only their
  // projected position/scale/opacity move in 3D, exactly like a standard tag-cloud
  // sphere. Rotating the text itself would make far-side labels render sideways
  // or mirrored, which is unreadable.
  const tagEls = [...inner.querySelectorAll(".stag")];
  let gx = -14, gy = 0;
  let dragging = false, lastX = 0, lastY = 0, startX = 0, startY = 0, wasDrag = false;
  const PERSPECTIVE = 900;

  function paint(){
    const gxr = gx*Math.PI/180, gyr = gy*Math.PI/180;
    tagEls.forEach((el,i) => {
      const t = tags[i];
      const bx = t.x*R, by = t.y*R, bz = t.z*R;
      const x1 = bx*Math.cos(gyr) + bz*Math.sin(gyr);
      const z1 = -bx*Math.sin(gyr) + bz*Math.cos(gyr);
      const y2 = by*Math.cos(gxr) - z1*Math.sin(gxr);
      const z2 = by*Math.sin(gxr) + z1*Math.cos(gxr);
      const persp = PERSPECTIVE / (PERSPECTIVE - z2);
      const depth = (z2/R + 1) / 2; // 0 (back) .. 1 (front)

      // 20 wide text pills on one sphere overlap in projection no matter how they
      // are distributed -- there is simply more label than circumference. So the
      // fix is not to stop the overlap but to make depth unmistakable, which turns
      // it back into legible occlusion instead of a pile. Perspective alone only
      // spans 0.86x-1.19x here, far too weak to read, hence the explicit falloff.
      const d = Math.pow(depth, 1.9);
      const scale = persp * (0.55 + 0.45*depth);
      el.style.opacity = String(0.05 + d*0.95);
      el.style.filter = depth > 0.92 ? "none" : `blur(${((1-depth)*2.1).toFixed(2)}px)`;
      // Far labels must not intercept a click aimed at the near label drawn over
      // them; elementFromPoint in the pointerup handler hit-tests the topmost node.
      el.style.pointerEvents = depth < 0.5 ? "none" : "auto";
      el.style.zIndex = String(Math.round(depth*100));
      el.style.transform = `translate(-50%,-50%) translate(${x1*persp}px, ${y2*persp}px) scale(${scale})`;
    });
  }

  wrap.addEventListener("pointerdown", (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY; startX = e.clientX; startY = e.clientY;
    wrap.setPointerCapture(e.pointerId);
  });
  wrap.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    gy += dx*0.35;
    gx = Math.max(-80, Math.min(80, gx - dy*0.35));
  });
  wrap.addEventListener("pointerup", (e) => {
    dragging = false;
    // Use straight-line distance from where the gesture started, not accumulated
    // jitter -- summing every intermediate move's delta over-counts small mouse/
    // trackpad noise during an intended click and made real clicks register as drags.
    const dist = Math.hypot(e.clientX - startX, e.clientY - startY);
    wasDrag = dist > 10;
    // e.target is retargeted to `wrap` while it holds pointer capture, so hit-test
    // the release coordinates directly instead of trusting e.target.
    if (!wasDrag) {
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const tag = hit && hit.closest(".stag");
      if (tag) jumpToCategory(tag.dataset.cat);
    }
  });
  wrap.addEventListener("pointercancel", () => { dragging = false; });

  (function spin(){
    if (!dragging && !REDUCE_MOTION) gy += 0.06;
    paint();
    requestAnimationFrame(spin);
  })();
}

// ---------- init ----------
renderStats(GALLERY_DATA);
renderCarousel(GALLERY_DATA);
renderGrid(GALLERY_DATA);
buildSphere();

})();
