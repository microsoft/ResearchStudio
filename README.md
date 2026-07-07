<h1>
  <img src="page/assets/logo.svg" alt="" width="48" align="absmiddle"> ResearchStudio
</h1>

> Our AI co-author, from research problem to final publication.

[![arXiv](https://img.shields.io/badge/arXiv-2026.XXXXX-b31b1b.svg)](https://arxiv.org/abs/2026.XXXXX)
[![Code](https://img.shields.io/badge/Code-GitHub-181717.svg?logo=github)](https://github.com/ai-nuts/ResearchStudio)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status: Active](https://img.shields.io/badge/Status-Active-brightgreen)

ResearchStudio is a collection of skills covering the **entire research lifecycle** — from the moment you have a vague research direction to the moment your paper goes public.
These skills are supported by [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex).

---

### <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel-wordmark.png" alt="Reel" height="16">: one research paper, all deliverables (poster, video, blog, and reel)

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel_demo.gif" alt="Paper2Reel — interactive reel feature demo" width="70%" align="top">
</p>
<p align="center">
  <sub>Presenting an all-in-one interactive reel.</sub>
</p>

### <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/idea-wordmark.png" alt="Idea" height="16">: one research direction, one reviewer-defensible idea card

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_teaser.gif" alt="IdeaSpark — turning a research direction into a reviewer-defensible idea card end to end" width="70%">
</p>
<p align="center">
  <sub>IdeaSpark runs the full pipeline end-to-end. </sub>
</p>


## News🔥🔥🔥

- [**Preview**] **[ResearchStudio-Reel](ResearchStudio-Reel/) is comming soon** — the *post-paper* half: turn a finished paper PDF into the artifacts a publication needs — a print-ready poster, a narrated walkthrough video, a bilingual blog post, and an interactive reel viewer.
- [**2026-07-03**] **[ResearchStudio-Idea](ResearchStudio-Idea/) is released** — the *pre-paper* half: turn an under-specified research direction into a reviewer-defensible, implementable idea, grounded in an empirical taxonomy induced from a large-scale papers of ICLR / ICML / NeurIPS submissions.


## Quick Start

**Option 1 — clone and run `install.sh`** (symlinks the skills from a local clone and scaffolds `.env`):

```bash
git clone https://github.com/microsoft/ResearchStudio.git && cd ResearchStudio
bash install.sh
```

**Option 2 — interactive `npx` installer** (choose which plugins to install, enter your API keys when prompted, and it writes `.env` for you):

```bash
npx github:microsoft/ResearchStudio
```

We recommend utilizing these skills with models versions $\ge$ `claude-opus-4.6` and `gpt-5.5`.

## License

[MIT](LICENSE)

## Citation

If ResearchStudio helps your research workflow, please cite:

```
@article{xiao2026researchstudioreel,
  title   = {ResearchStudio-Reel: Automate the Last Mile of Research from Paper to Poster, Video, and Blog},
  author  = {Lingao Xiao and Yalun Dai and Yangyu Huang and Qihao Zhao and Wenshan Wu and Hugo He and Ruishuo Chen and Jin Jiang and Qianli Ma and Jiahuan Zhang and Xin Zhang and Ying Xin and Yang Ou and Yan Xia and Scarlett Li and Longbo Huang and Zhipeng Zhang and Yang He and Yap Kim Hui and Yan Lu},
  journal = {arXiv preprint arXiv:2607.04438},
  year    = {2026},
  url     = {https://arxiv.org/abs/2607.04438}
}

@article{zhao2026researchstudioidea,
  title   = {ResearchStudio-Idea: An Evidence-Grounded Research-Ideation Skill Suite from ML Conference Outcomes},
  author  = {Qihao Zhao and Yangyu Huang and Yalun Dai and Lingao Xiao and Jianjun Gao and Xin Zhang and Wenshan Wu and Scarlett Li and Yang He and Yan Lu and Yap Kim Hui},
  journal = {arXiv preprint arXiv:2607.04439},
  year    = {2026},
  url     = {https://arxiv.org/abs/2607.04439}
}
```
