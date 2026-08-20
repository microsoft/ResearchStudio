// ---------------------------------------------------------------------------
// Where the heavy per-paper assets (video.mp4, reel.html, blog_*.docx, poster.pdf)
// are served from. Each record's `rel.*` path (e.g.
// "paper2poster/runs/<slug>/<slug>/video.mp4" or "msra_26/runs/<slug>/video.mp4")
// is appended to this base, so ONE base serves every benchmark.
//
// LOCAL PREVIEW (default): a relative path from this page to ResearchStudio's
//   benchmarks/ dir, so `python -m http.server` rooted at /datadisk/project works.
// DEPLOY: point this at the public repo that mirrors benchmarks/, e.g.
//   "https://raw.githubusercontent.com/ai-nuts/reel-assets/main"
//   Keep each run's "<bench>/runs/<slug>/[<slug>/]…" structure intact, because
//   reel.html references its sibling `assets/` and `video.mp4` by relative path.
// ---------------------------------------------------------------------------
// LOCAL PREVIEW (relative, needs serving from the project root):
// const ASSET_BASE = "../../ResearchStudio/benchmarks";
// HOSTED (ai-nuts/Storage via githack — serves reel.html as text/html so the iframe
// renders; jsDelivr serves HTML as text/plain and would only show source). rawcdn is
// the CDN endpoint, pinned to a commit for immutable caching + no dev rate-limits.
// If you push new reel assets to Storage, bump the commit SHA below.
const ASSET_BASE = "https://rawcdn.githack.com/ai-nuts/Storage/53f7ccdefcdc11ea28d0cd4914fc571d726a158f/ResearchStudio/ResearchStudio-Reel/reels";
// Poster thumbnails: served from jsDelivr (fast CDN, correct image/jpeg) so the page
// repo doesn't bundle 100 JPGs. gallery.js appends basename(poster_thumb). Bump the
// SHA together with ASSET_BASE when you re-push assets.
const POSTER_BASE = "https://cdn.jsdelivr.net/gh/ai-nuts/Storage@53f7ccdefcdc11ea28d0cd4914fc571d726a158f/ResearchStudio/ResearchStudio-Reel/posters";

// The public API switches atomically only after a complete Daily Papers Top-10
// edition is ready.  Until then the Gallery keeps showing its previous edition.
const DAILY_PAPERS_API = "https://researchstudio.site/api/daily-papers/latest";
const ENGAGEMENT_API_BASE = "https://researchstudio.site/api/engagement";

// This separate leadership-review page shows the current audited preview batch
// until the first complete Top-10 edition is atomically published.  A complete
// API edition always takes precedence as soon as it becomes available.
const DAILY_PREVIEW_DEFAULT = true;
