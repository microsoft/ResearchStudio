# ResearchStudio - <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/idea-wordmark.png" alt="Idea" height="28">

> From a research problem to a reviewer-defensible idea card — Automating the First Mile of Research Ideation.

**ResearchStudio - Idea** streamlines the *first* steps of a research project — the thinking that has to happen *before* any writing. Drop in a research problem and **IdeaSpark** runs the full pipeline end-to-end — read the field → find the bottleneck → choose the ideation pattern → draft the idea → check prior art → audit & revise → render the card — and hands back one reviewer-defensible, **implementable** idea card. Every step is grounded in a 1,947-paper ICLR / ICML / NeurIPS corpus (2021–2025) and its induced taxonomy of **15 ideation patterns** and **31 sub-patterns** — and **faithful by construction**: every load-bearing claim either traces to a retrieved record or is flagged as model-supplied.

<!-- Hero strip: two demos side by side. Left: the Paper2Reel interactive reel walkthrough. Right: a real Paper2Poster build. -->
<table align="center">
<tr>
<td align="center" valign="top" width="50%">
<img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_teaser.gif" alt="IdeaSpark idea generation — one research problem turned into one idea card end to end" width="100%">
</td>
<td align="center" valign="top" width="50%">
<img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_data_construction.gif" alt="IdeaSpark data construction — 1,947 ICLR/ICML/NeurIPS papers flow through signature extraction and pattern discovery into operational pattern cards" width="100%">
</td>
</tr>
<tr>
<td align="center" valign="top"><sub><b>Idea generation</b> — one research problem → one idea card.</sub></td>
<td align="center" valign="top"><sub><b>Data construction</b> — 1,947 ICLR / ICML / NeurIPS papers → operational pattern cards.</sub></td>
</tr>
</table>

---

## The skills

Three skills compose into one research-ideation loop — **search → generate → review** — with **IdeaSpark** the end-to-end flagship and the other two usable standalone:

| Skill | Input | Output | Built for |
|---|---|---|---|
| [**Idea-Spark**](skills/idea_spark/SKILL.md)| A research problem / direction (optional constraints, seed papers, compute) | one reviewer-defensible, implementable idea card — Title · Motivation · Method, as Markdown + PDF | the **full research-problem → idea-card pipeline**, calibrated against Oral-accepted papers |
| [**Paper-Search**](skills/paper_search/SKILL.md) | A query + year range (optional venues) | a deduped paper list across arXiv / DBLP / OpenAlex / OpenReview / Semantic Scholar / Crossref | the literature-grounding building block, usable on its own |
| [**Scoop-Check**](skills/scoop_check/SKILL.md) | A problem statement + a claimed novelty | a prior-art collision verdict: an overlap level + the closest prior works, per axis | a standalone "has this been done?" prior-art check on one novelty claim |

---

## Usage

Ask your agent in natural language — it picks up the matching skill and runs it end-to-end. Examples use Claude Code; other backends are in [docs/USAGE.md](https://github.com/ai-nuts/Storage/blob/main/ResearchStudio/ResearchStudio-Idea/docs/USAGE.md).

### 💡 IdeaSpark

```text
> /idea-spark I want a novel ML research idea about physical realism in text-to-video models.
```

One research direction → one reviewer-defensible idea card (Title · Motivation · Method), returned inline with PDF + LaTeX side artifacts.

**Example output** — three ideas IdeaSpark generated for ICLR-2026-Oral problem seeds, rendered as lean cards (Title · Motivation · Method). Click a card for the full PDF.

| [<img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_01.png" width="270" alt="Latent Conserved Charges for Text-to-Video">](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_01.pdf) | [<img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_80.png" width="270" alt="Water-Filling RoPE">](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_80.pdf) | [<img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_11.png" width="270" alt="Knowing-Falsehood Diagnosis">](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_11.pdf) |
|:--:|:--:|:--:|
| **Make the Generator Its Own Physicist** — give a text-to-video model an internal *conserved charge* updated symplectically, so physics holds by construction with no external simulator or trained scorer. <br> [PDF](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_01.pdf) | **Water-Filling RoPE** — allocate rotary position-encoding frequencies by a rate–distortion (water-filling) rule instead of the fixed geometric schedule. <br> [PDF](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_80.pdf) | **Knowing-Falsehood Diagnosis** — a counterfactual knowledge-contradiction test giving per-prompt evidence that an LLM *had* the right answer but stated a falsehood on a benign prompt. <br> [PDF](https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/examples/example_11.pdf) |

### 🔍 Paper-Search

```text
> /paper-search KV cache compression for long-context LLMs, 2024–2026
```

Returns a deduped paper list across arXiv / DBLP / OpenAlex / OpenReview / Semantic Scholar / Crossref.

### 🛡️ Scoop-Check

```text
> /scoop-check Problem: efficient LLM inference. Novelty: a calibrated per-token
  early-exit stop rule read from the model's own layer-wise prediction trajectory.
```

Returns a per-axis overlap verdict against the closest published work. Input: a **research problem + the claimed novelty** — or just paste an idea card (it reads them from Motivation + Method).

---

## Evaluation

On 100 ICLR-2026-Oral problem seeds, each IdeaSpark idea card is scored on **quality** (the `idea-quality` skill) and **novelty** (`scoop-check`) against three baselines — Opus-4.8 (bare), Opus-4.8 (self-gen), and GPT-5.5 (bare). IdeaSpark lands top — the highest idea-quality while staying solidly novel — and scores highest in **every research domain**.

<p align="center">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_evaluation.png" alt="Quality vs novelty — IdeaSpark scores highest on idea-quality while remaining novel, above Opus-4.8 (bare), Opus-self-gen, and GPT-5.5 (bare)" width="46%">
  <img src="https://raw.githubusercontent.com/ai-nuts/Storage/main/ResearchStudio/ResearchStudio-Idea/docs/figures/ideaspark_quality_by_domain.png" alt="Idea-quality by research domain — IdeaSpark (blue) is outermost on every one of the 21 ICLR primary-area domains, above Opus-self-gen, Opus-4.8 (bare), and GPT-5.5 (bare)" width="48%">
</p>
<p align="center">
  <sub>Left: quality × novelty positioning. &nbsp; Right: idea-quality across research domains.</sub>
</p>

Full protocol, IdeaSpark vs the baselines, and the scoring skill are in [`evaluation/README.md`](evaluation/README.md).

---

## Acknowledgements

- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and [Codex](https://developers.openai.com/codex) — the agent runtime that drives every skill.
- [arXiv](https://arxiv.org/), [OpenAlex](https://openalex.org/), [Semantic Scholar](https://www.semanticscholar.org/product/api), [OpenReview](https://openreview.net/) — the Phase 0 / 3.1 literature connectors.
- [PyMuPDF](https://pymupdf.readthedocs.io/) + [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — full-text fetch and parsing.
- [tectonic](https://tectonic-typesetting.github.io/) / XeLaTeX — optional PDF compilation of the idea cards.

## License

[MIT](../LICENSE)

## Citation

If ResearchStudio - Idea / IdeaSpark helps your research workflow, please cite:

```
@article{zhao2026researchstudioidea,
  title   = {ResearchStudio-Idea: An Evidence-Grounded Research-Ideation Skill Suite from ML Conference Outcomes},
  author  = {Qihao Zhao and Yangyu Huang and Yalun Dai and Lingao Xiao and Jianjun Gao and Xin Zhang and Wenshan Wu and Scarlett Li and Yang He and Yan Lu and Yap Kim Hui},
  journal = {arXiv preprint arXiv:2607.04439},
  year    = {2026},
  url     = {https://arxiv.org/abs/2607.04439}
}
```
