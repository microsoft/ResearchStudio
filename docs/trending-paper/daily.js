(() => {
  "use strict";

  const API_BASE = "https://researchstudio.site/daily-paper/api";
  const region = document.querySelector("#paper-region");
  const grid = document.querySelector("#paper-grid");
  const loading = document.querySelector("#loading");
  const empty = document.querySelector("#empty");
  const count = document.querySelector("#paper-count");
  const select = document.querySelector("#edition-select");
  const selectLabel = document.querySelector("#edition-label");
  const olderButton = document.querySelector("#edition-older");
  const newerButton = document.querySelector("#edition-newer");
  const modeButtons = [...document.querySelectorAll("[data-mode]")];
  const sourceLink = document.querySelector("#source-link");
  const searchInput = document.querySelector("#paper-search");
  const sortButton = document.querySelector("#paper-sort");
  const template = document.querySelector("#paper-template");
  const viewer = document.querySelector("#paper-viewer");
  const viewerTitle = document.querySelector("#viewer-title");
  const viewerCategory = document.querySelector("#viewer-category");
  const viewerExternal = document.querySelector("#viewer-external");
  const viewerQA = document.querySelector("#viewer-qa");
  const viewerLoading = document.querySelector("#viewer-loading");
  const reelTab = document.querySelector("#reel-tab");
  const paperTab = document.querySelector("#paper-tab");
  const reelPanel = document.querySelector("#reel-panel");
  const paperPanel = document.querySelector("#paper-panel");
  const reelFrame = document.querySelector("#reel-frame");
  const paperFrame = document.querySelector("#paper-frame");
  const pdfFallbackLink = document.querySelector("#pdf-fallback-link");

  let editions = [];
  let activeMode = "weekly";
  let activeSelection = null;
  let activeContext = null;
  let activeRecords = [];
  let selectedWeekly = null;
  let selectedDaily = null;
  let activePaper = null;
  let reelReady = false;
  let paperReady = false;
  function setLink(element, url) {
    element.href = url;
  }

  function githubRepoUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const raw = value.trim();
      const parsed = new URL(
        /^https?:\/\//i.test(raw) ? raw : `https://github.com/${raw.replace(/^\/+/, "")}`
      );
      if (parsed.protocol !== "https:" || !["github.com", "www.github.com"].includes(parsed.hostname.toLowerCase())) {
        return null;
      }
      const parts = parsed.pathname.split("/").filter(Boolean);
      if (parts.length < 2) return null;
      const owner = encodeURIComponent(parts[0]);
      const repo = encodeURIComponent(parts[1].replace(/\.git$/i, ""));
      return `https://github.com/${owner}/${repo}`;
    } catch (_error) {
      return null;
    }
  }

  function compactCount(value) {
    return new Intl.NumberFormat("en-US", {
      notation: "compact",
      maximumFractionDigits: 1
    }).format(value);
  }

  function parseUtcDate(value) {
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(parsed.valueOf()) ? null : parsed;
  }

  function formatDate(value, options = {}) {
    const parsed = parseUtcDate(value);
    if (!parsed) return value || "Unknown date";
    return new Intl.DateTimeFormat("en-US", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
      ...options
    }).format(parsed);
  }

  function formatWeek(edition) {
    const start = parseUtcDate(edition?.week_start);
    const end = parseUtcDate(edition?.week_end);
    if (!start || !end) return edition?.week_id || "Unknown date";
    const startLabel = formatDate(edition.week_start, {year: undefined});
    const endLabel = formatDate(edition.week_end, {year: undefined});
    return `${startLabel} – ${endLabel}`;
  }

  function formatDaily(value) {
    return formatDate(value, {year: undefined});
  }

  function editionForWeek(weekId) {
    return editions.find(edition => edition.week_id === weekId) || null;
  }

  function dailyDates() {
    const values = new Set();
    for (const edition of editions) {
      for (const paper of edition.papers || []) {
        if (paper.daily_date) values.add(paper.daily_date);
      }
    }
    return [...values].sort((left, right) => right.localeCompare(left));
  }

  function dailyDatesForWeek(weekId) {
    const edition = editionForWeek(weekId);
    if (!edition) return [];
    return [...new Set((edition.papers || []).map(paper => paper.daily_date).filter(Boolean))]
      .sort((left, right) => right.localeCompare(left));
  }

  function weekForDate(date) {
    return editions.find(edition =>
      (edition.papers || []).some(paper => paper.daily_date === date)
    ) || editions.find(edition =>
      edition.week_start <= date && date <= edition.week_end
    ) || null;
  }

  function selectionValues(mode) {
    return mode === "weekly"
      ? editions.map(edition => edition.week_id).filter(Boolean)
      : dailyDates();
  }

  function populateSelector(mode) {
    select.replaceChildren();
    selectLabel.textContent = "Date";
    const values = selectionValues(mode);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = mode === "weekly" ? formatWeek(editionForWeek(value)) : formatDaily(value);
      select.appendChild(option);
    }
    select.disabled = values.length === 0;
    return values;
  }

  function recordsFor(mode, key) {
    if (mode === "weekly") {
      const edition = editionForWeek(key);
      if (!edition) return [];
      return (edition.papers || []).map(paper => ({edition, paper}));
    }

    const records = [];
    const seen = new Set();
    for (const edition of editions) {
      for (const paper of edition.papers || []) {
        if (paper.daily_date !== key) continue;
        const identity = paper.token || paper.paper_id;
        if (identity && seen.has(identity)) continue;
        if (identity) seen.add(identity);
        records.push({edition, paper});
      }
    }
    records.sort((left, right) => {
      const votes = (Number(right.paper.hf_upvotes_at_snapshot) || 0)
        - (Number(left.paper.hf_upvotes_at_snapshot) || 0);
      if (votes) return votes;
      return String(left.paper.paper_id).localeCompare(String(right.paper.paper_id));
    });
    return records.map((record, index) => ({
      edition: record.edition,
      paper: {...record.paper, rank: index + 1}
    }));
  }

  function updateEditionNavigation() {
    const values = selectionValues(activeMode);
    const index = values.indexOf(activeSelection);
    olderButton.disabled = index < 0 || index >= values.length - 1;
    newerButton.disabled = index <= 0;
  }

  function contextFor(mode, key) {
    if (mode === "weekly") {
      const edition = editionForWeek(key);
      return {
        mode,
        key,
        edition,
        sourceUrl: edition?.source_url || `https://huggingface.co/papers/week/${encodeURIComponent(key)}`
      };
    }
    return {
      mode,
      key,
      edition: weekForDate(key),
      sourceUrl: `https://huggingface.co/papers/date/${encodeURIComponent(key)}`
    };
  }

  function normalizeSearch(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function applyCatalogControls() {
    const query = normalizeSearch(searchInput.value);
    const ascending = sortButton.dataset.sort === "votes-asc";
    const cards = [...grid.querySelectorAll(".paper-card")];
    cards.sort((left, right) => {
      const voteDifference = Number(left.dataset.hfVotes) - Number(right.dataset.hfVotes);
      if (voteDifference) return ascending ? voteDifference : -voteDifference;
      return Number(left.dataset.originalOrder) - Number(right.dataset.originalOrder);
    });

    let visibleCount = 0;
    for (const card of cards) {
      const matches = !query || card.dataset.searchText.includes(query);
      card.hidden = !matches;
      if (matches) visibleCount += 1;
      grid.appendChild(card);
    }

    const totalCount = cards.length;
    count.textContent = query
      ? `${visibleCount} of ${totalCount} papers`
      : `${totalCount} ${totalCount === 1 ? "paper" : "papers"}`;
    count.hidden = false;
    loading.hidden = true;
    empty.textContent = totalCount
      ? "No papers match this search."
      : "No published papers are available for this selection yet.";
    empty.hidden = visibleCount > 0;
    grid.hidden = visibleCount === 0;
  }

  function setSortDirection(value) {
    const ascending = value === "votes-asc";
    sortButton.dataset.sort = ascending ? "votes-asc" : "votes-desc";
    sortButton.title = ascending ? "Least voted first" : "Most voted first";
    sortButton.setAttribute(
      "aria-label",
      ascending
        ? "Sorted by Hugging Face votes, least voted first. Activate for most voted first."
        : "Sorted by Hugging Face votes, most voted first. Activate for least voted first."
    );
  }

  function toggleSortDirection() {
    setSortDirection(sortButton.dataset.sort === "votes-asc" ? "votes-desc" : "votes-asc");
    applyCatalogControls();
  }

  function renderRecords(records, context) {
    grid.replaceChildren();
    sourceLink.href = context.sourceUrl;
    activeRecords = records;
    activeContext = context;

    for (const [recordIndex, {edition, paper}] of records.entries()) {
      const fragment = template.content.cloneNode(true);
      const card = fragment.querySelector(".paper-card");
      card.dataset.originalOrder = String(recordIndex);
      card.dataset.searchText = normalizeSearch(`${paper.title} ${paper.paper_id}`);
      card.dataset.paperId = paper.paper_id;

      const rank = fragment.querySelector(".rank");
      if (paper.rank === null || paper.rank === undefined) {
        rank.hidden = true;
      } else {
        rank.textContent = `#${paper.rank}`;
      }

      const hfVotes = Number(paper.hf_upvotes_at_snapshot) || 0;
      card.dataset.hfVotes = String(hfVotes);
      const hfScore = fragment.querySelector(".hf-score");
      hfScore.querySelector(".hf-vote-count").textContent = hfVotes.toLocaleString("en-US");
      hfScore.setAttribute(
        "aria-label",
        `${hfVotes} Huggingface votes; open this paper on Hugging Face`
      );
      setLink(
        hfScore,
        paper.hf_url || `https://huggingface.co/papers/${encodeURIComponent(paper.paper_id)}`
      );

      const arxivChip = fragment.querySelector(".arxiv-chip");
      arxivChip.querySelector(".paper-id").textContent = paper.paper_id;
      arxivChip.setAttribute("aria-label", `Open ${paper.paper_id} on arXiv`);
      setLink(
        arxivChip,
        paper.arxiv_url || `https://arxiv.org/abs/${encodeURIComponent(paper.paper_id)}`
      );

      const githubChip = fragment.querySelector(".github-chip");
      const githubUrl = githubRepoUrl(paper.github_repo);
      const githubStarValue = paper.github_stars_at_snapshot;
      const githubStars = githubStarValue === null || githubStarValue === undefined
        ? Number.NaN
        : Number(githubStarValue);
      if (githubUrl && Number.isFinite(githubStars) && githubStars >= 0) {
        githubChip.href = githubUrl;
        githubChip.hidden = false;
        githubChip.querySelector(".github-star-count").textContent = compactCount(githubStars);
        githubChip.setAttribute(
          "aria-label",
          `Open the paper repository on GitHub; ${githubStars.toLocaleString("en-US")} stars`
        );
      }
      fragment.querySelector(".paper-title").textContent = paper.title;
      const poster = fragment.querySelector(".poster");
      poster.src = paper.poster_url;
      poster.alt = `Preview for ${paper.title}`;
      setLink(fragment.querySelector(".poster-link"), paper.reel_url);

      for (const opener of fragment.querySelectorAll("[data-open-view]")) {
        opener.addEventListener("click", event => {
          event.preventDefault();
          openViewer(edition, paper, opener.dataset.openView);
        });
      }
      grid.appendChild(fragment);
    }

    applyCatalogControls();
    region.setAttribute("aria-busy", "false");
  }

  function writeSelectionUrl(clearViewer = true) {
    const url = new URL(window.location.href);
    url.searchParams.set("mode", activeMode);
    if (activeMode === "weekly") {
      if (activeSelection) url.searchParams.set("week", activeSelection);
      else url.searchParams.delete("week");
      url.searchParams.delete("date");
    } else {
      if (activeSelection) url.searchParams.set("date", activeSelection);
      else url.searchParams.delete("date");
      url.searchParams.delete("week");
    }
    if (clearViewer) {
      url.searchParams.delete("paper");
      url.searchParams.delete("view");
    }
    history.replaceState({}, "", url);
  }

  function renderSelection(mode, key, updateUrl = true) {
    searchInput.value = "";
    activeMode = mode;
    activeSelection = key;
    select.value = key;
    if (mode === "weekly") selectedWeekly = key;
    else selectedDaily = key;
    updateEditionNavigation();
    renderRecords(recordsFor(mode, key), contextFor(mode, key));
    if (updateUrl) writeSelectionUrl();
  }

  function switchMode(mode, updateUrl = true, preferredKey = null) {
    activeMode = mode === "daily" ? "daily" : "weekly";
    for (const button of modeButtons) {
      button.setAttribute("aria-pressed", button.dataset.mode === activeMode ? "true" : "false");
    }
    const values = populateSelector(activeMode);
    const remembered = activeMode === "weekly" ? selectedWeekly : selectedDaily;
    const key = values.includes(preferredKey)
      ? preferredKey
      : values.includes(remembered)
        ? remembered
        : values[0] || null;
    if (key) {
      renderSelection(activeMode, key, updateUrl);
      return;
    }
    activeSelection = null;
    searchInput.value = "";
    updateEditionNavigation();
    renderRecords([], contextFor(activeMode, ""));
    if (updateUrl) writeSelectionUrl();
  }

  function stepEdition(offset) {
    const values = selectionValues(activeMode);
    const index = values.indexOf(activeSelection);
    const nextKey = values[index + offset];
    if (nextKey) renderSelection(activeMode, nextKey);
  }

  function paperPdfUrl(url) {
    const parsed = new URL(url, window.location.href);
    parsed.hash = "view=FitH";
    return parsed.href;
  }

  function showView(view, updateUrl = true) {
    if (!activePaper) return;
    const paperMode = view === "paper";
    reelTab.setAttribute("aria-selected", paperMode ? "false" : "true");
    paperTab.setAttribute("aria-selected", paperMode ? "true" : "false");
    reelPanel.hidden = paperMode;
    paperPanel.hidden = !paperMode;
    viewerLoading.hidden = paperMode ? paperReady : reelReady;
    viewerLoading.textContent = paperMode ? "Loading paper…" : "Loading Reel…";
    if (paperMode && paperFrame.src === "about:blank") paperFrame.src = paperPdfUrl(activePaper.pdf_url);
    viewerExternal.href = paperMode ? paperPdfUrl(activePaper.pdf_url) : activePaper.reel_url;
    if (updateUrl) setPermalink(paperMode ? "paper" : "reel");
  }

  function setPermalink(view) {
    writeSelectionUrl(false);
    const url = new URL(window.location.href);
    url.searchParams.set("paper", activePaper.paper_id);
    url.searchParams.set("view", view);
    history.replaceState({}, "", url);
  }

  function viewerCategoryText(edition, paper) {
    const rank = paper.rank === null || paper.rank === undefined ? "" : ` · #${paper.rank}`;
    if (activeMode === "daily") return `${paper.daily_date}${rank}`;
    return `${formatWeek(edition)} · ${formatDaily(paper.daily_date)}${rank}`;
  }

  function openViewer(edition, paper, view = "reel", updateUrl = true) {
    activePaper = paper;
    reelReady = false;
    paperReady = false;
    viewerTitle.textContent = paper.title;
    viewerCategory.textContent = viewerCategoryText(edition, paper);
    viewerQA.href = paper.qa_url;
    pdfFallbackLink.href = paperPdfUrl(paper.pdf_url);
    reelFrame.src = paper.reel_url;
    paperFrame.src = "about:blank";
    showView(view === "paper" ? "paper" : "reel", updateUrl);
    if (!viewer.open) viewer.showModal();
    document.body.classList.add("viewer-open");
  }

  function closeViewer(updateUrl = true) {
    viewer.close();
    document.body.classList.remove("viewer-open");
    reelFrame.src = "about:blank";
    paperFrame.src = "about:blank";
    activePaper = null;
    reelReady = false;
    paperReady = false;
    if (updateUrl) writeSelectionUrl();
  }

  function restoreLocation() {
    const params = new URLSearchParams(window.location.search);
    const requestedMode = params.get("mode");
    const legacyDate = !requestedMode && params.has("date");
    const mode = requestedMode === "daily" || legacyDate ? "daily" : "weekly";
    const key = mode === "daily" ? params.get("date") : params.get("week");

    switchMode(mode, false, key);

    const paperId = params.get("paper");
    const record = paperId
      ? activeRecords.find(item => item.paper.paper_id === paperId)
      : null;
    if (record) {
      openViewer(record.edition, record.paper, params.get("view") === "paper" ? "paper" : "reel", false);
      setPermalink(params.get("view") === "paper" ? "paper" : "reel");
    } else {
      writeSelectionUrl();
    }
  }

  async function requestEditions() {
    const response = await fetch(`${API_BASE}/editions?limit=31`, {
      headers: {"Accept": "application/json"}
    });
    if (!response.ok) throw new Error("edition request failed");
    return ((await response.json()).editions || [])
      .filter(edition => edition && edition.week_id)
      .sort((left, right) => String(right.week_end).localeCompare(String(left.week_end)));
  }

  async function refreshEditions() {
    const mode = activeMode;
    const selection = activeSelection;
    const query = searchInput.value;
    const sort = sortButton.dataset.sort;
    const updatedEditions = await requestEditions();
    if (!updatedEditions.length) return;
    editions = updatedEditions;

    const values = populateSelector(mode);
    const nextSelection = values.includes(selection) ? selection : values[0];
    if (!nextSelection) return;
    renderSelection(mode, nextSelection, false);
    searchInput.value = query;
    setSortDirection(sort);
    applyCatalogControls();
  }

  async function load() {
    try {
      editions = await requestEditions();
      if (!editions.length) {
        loading.hidden = true;
        empty.hidden = false;
        count.hidden = true;
        region.setAttribute("aria-busy", "false");
        return;
      }
      select.addEventListener("change", () => renderSelection(activeMode, select.value));
      searchInput.addEventListener("input", applyCatalogControls);
      sortButton.addEventListener("click", toggleSortDirection);
      olderButton.addEventListener("click", () => stepEdition(1));
      newerButton.addEventListener("click", () => stepEdition(-1));
      for (const button of modeButtons) {
        button.addEventListener("click", () => {
          const nextMode = button.dataset.mode;
          if (nextMode === activeMode) return;
          if (nextMode === "daily") {
            const dates = dailyDatesForWeek(activeSelection);
            switchMode("daily", true, dates.includes(selectedDaily) ? selectedDaily : dates[0]);
          } else {
            switchMode("weekly", true, weekForDate(activeSelection)?.week_id || selectedWeekly);
          }
        });
      }
      restoreLocation();
    } catch (_error) {
      loading.textContent = "Trending Paper is temporarily unavailable. Please try again shortly.";
      region.setAttribute("aria-busy", "false");
    }
  }

  document.querySelector("#viewer-back").addEventListener("click", () => closeViewer());
  viewer.addEventListener("cancel", event => { event.preventDefault(); closeViewer(); });
  reelTab.addEventListener("click", () => showView("reel"));
  paperTab.addEventListener("click", () => showView("paper"));
  reelFrame.addEventListener("load", () => {
    if (reelFrame.getAttribute("src") === "about:blank") return;
    reelReady = true;
    if (!reelPanel.hidden) viewerLoading.hidden = true;
  });
  paperFrame.addEventListener("load", () => {
    if (paperFrame.getAttribute("src") === "about:blank") return;
    paperReady = true;
    if (!paperPanel.hidden) viewerLoading.hidden = true;
  });
  load();
})();
