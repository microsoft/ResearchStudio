<h1>
  <img src="docs/assets/logo.svg" alt="" width="48" align="absmiddle"> ResearchStudio
</h1>

> Our AI co-author, from research problem to final publication.

[![Code](https://img.shields.io/github/stars/microsoft/ResearchStudio?style=flat&amp;logo=github&amp;label=Code&amp;color=black)](https://github.com/microsoft/ResearchStudio)
[![arXiv-Idea](https://img.shields.io/badge/arXiv-Idea%3A%202607.04439-b31b1b.svg)](https://arxiv.org/abs/2607.04439)
[![arXiv-Reel](https://img.shields.io/badge/arXiv-Reel%3A%202607.04438-b31b1b.svg)](https://arxiv.org/abs/2607.04438)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://raw.githubusercontent.com/microsoft/ResearchStudio/refs/heads/main/LICENSE)
[![Status: Active](https://img.shields.io/badge/Status-Active-brightgreen)](https://aka.ms/ResearchStudio)

ResearchStudio is a collection of skills covering the **entire research lifecycle** — from an under-specified research direction to a published paper.
The skills run on [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex).

---

### <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel-wordmark.png" alt="Reel" height="16">: one research paper, all deliverables (editable poster, video, blog, and reel)

<div align="center">

#### [📄 Paper](https://arxiv.org/abs/2607.04438) &nbsp;·&nbsp; [💻 Code](ResearchStudio-Reel/) &nbsp;·&nbsp; [🎬 Demo](https://researchstudio.site/)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Reel/docs/figures/reel_demo.gif" alt="Paper2Reel — interactive reel feature demo" width="100%" align="top">
</p>
<p align="center">
  <sub>Presenting an all-in-one interactive reel.</sub>
</p>

### <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/idea-wordmark.png" alt="Idea" height="16">: one research direction, one reviewer-defensible idea card

<div align="center">

#### [📄 Paper](https://arxiv.org/abs/2607.04439) &nbsp;·&nbsp; [💻 Code](ResearchStudio-Idea/) &nbsp;·&nbsp; [🎬 Demo](https://researchstudio.site/)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_teaser.gif" alt="IdeaSpark — turning a research direction into a reviewer-defensible idea card end to end" width="100%">
</p>
<p align="center">
  <sub>IdeaSpark runs the full pipeline end-to-end.</sub>
</p>

## News 🔥🔥🔥

- [**2026-07-08**] **[ResearchStudio-Reel](ResearchStudio-Reel/) is released** — the *post-paper* half: turn a finished paper PDF into the artifacts a publication needs — a print-ready poster, a narrated walkthrough video, a bilingual blog post, and an interactive reel viewer.
- [**2026-07-03**] **[ResearchStudio-Idea](ResearchStudio-Idea/) is released** — the *pre-paper* half: turn an under-specified research direction into a reviewer-defensible, implementable idea, grounded in an empirical taxonomy induced from a large-scale corpus of ICLR / ICML / NeurIPS submissions.

## Quick Start

We recommend creating an isolated environment first:

```bash
conda create -n researchstudio "python>=3.10" -y
conda activate researchstudio
```

Then pick one of the two install paths below:

**Option 1 — clone and run `install.sh`** (installs native tools, Python deps, symlinks the skills from a local clone and scaffolds `.env`):

```bash
git clone https://github.com/microsoft/ResearchStudio.git && cd ResearchStudio
bash install.sh
```

**Option 2 — interactive `npx` installer** (choose which plugins to install, enter your API keys when prompted, and it writes `.env`):

```bash
npx github:microsoft/ResearchStudio
```

For usage, see [Idea](ResearchStudio-Idea/#usage) and [Reel](ResearchStudio-Reel/#usage).
We recommend using these skills with model versions $\ge$ `claude-opus-4.6` or `gpt-5.5`.

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
