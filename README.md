<h1>
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/docs/logo.svg" alt="" width="48" align="absmiddle"> ResearchStudio
</h1>

> Our AI co-author, from research problem to final publication.

[![arXiv](https://img.shields.io/badge/arXiv-2026.XXXXX-b31b1b.svg)](https://arxiv.org/abs/2026.XXXXX)
[![Code](https://img.shields.io/badge/Code-GitHub-181717.svg?logo=github)](https://github.com/ai-nuts/ResearchStudio)
[![Video](https://img.shields.io/badge/Video-YouTube-FF0000.svg?logo=youtube)](https://www.youtube.com/watch?v=yK9S5eTZ3cM)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status: Active](https://img.shields.io/badge/Status-Active-brightgreen)

ResearchStudio is a collection of skills covering the **entire research lifecycle** — from the moment you have a vague research direction to the moment your paper goes public.
These skills are supported by [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex). We recommend utilizing these skills with Opus 4.6+ and GPT 5.5+.

---

### 🎞️ Reel — one research paper, all deliverables (poster, video, blog, and reel)

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel_demo.gif" alt="Paper2Reel — interactive reel feature demo" width="70%" align="top">
</p>
<p align="center">
  <sub>Presenting an all-in-one interactive reel.</sub>
</p>

### 💡 Idea — one research direction, one reviewer-defensible idea card

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_teaser.gif" alt="IdeaSpark — turning a research direction into a reviewer-defensible idea card end to end" width="70%">
</p>
<p align="center">
  <sub>IdeaSpark runs the full pipeline end-to-end. </sub>
</p>

---

## News🔥🔥🔥

- **2026-06** — 💡 **[ResearchStudio-Idea](ResearchStudio-Idea/)** released — the *pre-paper* half: turn an under-specified research direction into a reviewer-defensible, implementable idea, grounded in an empirical taxonomy induced from a large-scale papers of ICLR / ICML / NeurIPS submissions.
- **2026-06** — 🎞️ **[ResearchStudio-Reel](ResearchStudio-Reel/)** released — the *post-paper* half: turn a finished paper PDF into the artifacts a publication needs — a print-ready poster, a narrated walkthrough video, a bilingual blog post, and an interactive reel viewer.

---

## Quick Start

```bash
git clone <repo-url> && cd ResearchStudio
bash install.sh

# required by paper-search and idea-spark skills.
# MANDATORY: ensure you populate the necessary keys in the `<repo-root>/.env` file.

# required by paper2video skill.
npx skills add hugohe3/ppt-master
```

The two halves usage independently — pick the one you need and follow its README:

- 💡 **ResearchStudio-Idea** → [`ResearchStudio-Idea/README.md`](ResearchStudio-Idea/README.md)
- 🎞️ **ResearchStudio-Reel** → [`ResearchStudio-Reel/README.md`](ResearchStudio-Reel/README.md)

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Citation

If ResearchStudio helps your research workflow, please cite:

```bibtex
Placeholder
```
