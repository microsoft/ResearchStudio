# NoveltySkill

A data-driven innovation engine for generating Oral-level ML research ideas. Built from 1,370 papers (ICLR, NeurIPS, ICML 2020-2025) with three-way contrastive analysis (Oral vs High-Cited vs Rejected).

## What It Does

Given a research problem description, NoveltySkill guides any LLM through a structured 5-phase workflow:

1. **Problem Understanding** - identify the essential bottleneck
2. **Hierarchical Lens Reasoning** - scan 9 meta-categories, drill into 18 specific innovation lenses, explore proven combinations
3. **Idea Generation** - produce a concrete, implementable research idea
4. **Quality Audit** - check against failure modes, reviewer expectations, combination coherence
5. **Framing** - craft hook, scope, narrative arc, and abstract draft

**Output**: Title, Research Question, Core Approach, Differentiation from Related Work, Experiment Plan, Reviewer Response Strategy, Abstract Draft.

## 18 Innovation Lenses (organized in 9 Meta-Categories)

| Meta-Category | Lenses | Core Question |
|--------------|--------|--------------|
| Cross-Domain Transfer | C03 + C10 | Has another domain solved this? |
| Theoretical Formalization | C01 + C14 + C17 | Can we prove formal properties? |
| Structural Diagnosis | C12 + C16 | Is the objective/parameterization flawed? |
| Sequential Decision & Game Theory | C04 + C13 | Can we reframe what to optimize? |
| Symmetry & Domain Structure | C05 + C06 | What structural constraint is missing? |
| Compositional & Process | C08 + C09 | Can we decompose and supervise steps? |
| Mathematical Reformulation | C07 + C15 | Does a different math language help? |
| Assumption & Role Inversion | C00 + C11 | What assumption can we challenge? |
| Causal Identification | C02 | Does causal structure give guarantees? |

Each lens includes: step-by-step procedure, success conditions (from Oral papers), failure modes (from Rejected papers), impact drivers (from High-Cited papers), cognitive barriers, and reviewer expectations.

---

## Installation & Usage

### Quickest: interactive installer

```bash
cd /path/to/your/project
bash /path/to/novelty-skill-release/install.sh
```

`install.sh` walks you through:

1. Installing the skill (Markdown) into `.claude/skills/novelty-skill/` for Claude Code.
2. Optionally installing the Phase 1.5 **literature-search** Python module and wiring it to **whichever LLM backend you already have** (OpenAI / Anthropic / Gemini / local Ollama). It detects `*_API_KEY` env vars and a running Ollama automatically, writes `.novelty_skill.env` pinning the choice, and offers to `pip install` the matching SDK.

Once installed:

```bash
source .novelty_skill.env
python examples/lit_search.py "GRPO rollout efficiency"
```

The CLI prints papers from arXiv + Google Scholar over `[today-24mo, today]`, each tagged with its primary innovation lens (C00-C17) via the backend you selected. Saturated / under-used lenses feed directly into Phase 2 of the skill.

---

### Option A: Claude Code (Recommended)

The native, highest-quality mode. Claude Code reads supporting files on-demand for detailed methodologies.

**Install:**

```bash
# In your project root directory:
cd /path/to/your/project
bash /path/to/novelty-skill-release/install_claude_code.sh
```

Or manually:

```bash
mkdir -p .claude/skills/novelty-skill
cp skill/SKILL.md .claude/skills/novelty-skill/
cp skill/methodologies.md .claude/skills/novelty-skill/
cp skill/pitfalls.md .claude/skills/novelty-skill/
cp skill/domain-analysis.md .claude/skills/novelty-skill/
```

**Use:**

Open Claude Code in your project directory, then type:

```
/novelty-skill "How to improve LLM reasoning without additional training data"
```

Claude will automatically follow the 5-phase workflow, read methodologies on-demand, and generate a complete research idea.

---

### Option B: OpenAI GPT-4o / GPT-4.1

Uses the self-contained system prompt (~19K tokens). Works with any model that has 20K+ context window.

**Install:**

```bash
pip install openai
export OPENAI_API_KEY="sk-..."
```

**Use:**

```bash
python examples/use_openai.py "How to improve LLM reasoning without more training data"
```

Or in your own code:

```python
from openai import OpenAI

client = OpenAI()
system = open("skill/system_prompt.txt").read()

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": "How to improve LLM reasoning?"}
    ],
    temperature=0.7,
)
print(response.choices[0].message.content)
```

---

### Option C: Anthropic Claude API (without Claude Code)

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
python examples/use_anthropic.py "How to improve LLM reasoning without more training data"
```

Or in your own code:

```python
import anthropic

client = anthropic.Anthropic()
system = open("skill/system_prompt.txt").read()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system=system,
    messages=[{"role": "user", "content": "How to improve LLM reasoning?"}],
)
print(response.content[0].text)
```

---

### Option D: Google Gemini

```bash
pip install google-genai
export GOOGLE_API_KEY="..."
```

```bash
python examples/use_gemini.py "How to improve LLM reasoning without more training data"
```

---

### Option E: Local Models via Ollama (Llama, Qwen, DeepSeek)

Works with any local model that has 32K+ context. The system prompt is ~19K tokens.

**Install:**

```bash
# Install Ollama: https://ollama.com
ollama pull qwen2.5:72b   # or llama3.1:70b, deepseek-v3, etc.
```

**Use:**

```bash
python examples/use_ollama.py "How to improve LLM reasoning without more training data"

# Use a different model:
OLLAMA_MODEL=llama3.1:70b python examples/use_ollama.py "your problem"
```

**Recommended local models** (need 32K+ context):
- `qwen2.5:72b` - best quality/speed balance
- `llama3.1:70b` - strong general capability
- `deepseek-v3` - strong on research tasks
- `qwen2.5:32b` - smaller but still capable

---

### Option F: Any OpenAI-Compatible API

Any service that supports the OpenAI chat completions format (vLLM, Together AI, Fireworks, etc.):

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.together.xyz/v1",  # or your endpoint
    api_key="your-key",
)
system = open("skill/system_prompt.txt").read()

response = client.chat.completions.create(
    model="meta-llama/Llama-3.1-70B-Instruct",
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": "your research problem"},
    ],
)
print(response.choices[0].message.content)
```

---

## File Structure

```
novelty-skill-release/
├── README.md                          # This file
├── install.sh                         # Interactive installer (skill + lit_search + LLM wiring)
├── install_claude_code.sh             # Legacy: skill-only Claude Code installer
│
├── skill/                             # Core skill files
│   ├── SKILL.md                       # Main entry - hierarchy, workflow, Phase 1.5, output format
│   ├── methodologies.md               # 18 complete methodologies
│   ├── pitfalls.md                    # Failure mode checklist
│   ├── domain-analysis.md             # Domain mapping, trends, PC bias
│   └── system_prompt.txt              # Self-contained prompt for any LLM (~19K tokens)
│
├── claude-code-install/               # Pre-structured for Claude Code
│   └── .claude/skills/novelty-skill/
│
├── lit_search/                        # Phase 1.5 Python module (multi-LLM)
│   ├── __init__.py
│   ├── literature_search.py           # arXiv + Google Scholar + dedup + lens classify
│   ├── backends.py                    # auto-detect OpenAI/Anthropic/Gemini/Ollama
│   └── clusters.py                    # 18 lens names + 9 meta-categories
│
└── examples/                          # Usage examples
    ├── lit_search.py                  # Phase 1.5 CLI (auto-picks your LLM)
    ├── use_openai.py                  # Idea generation: GPT-4o / GPT-4.1
    ├── use_anthropic.py               # Idea generation: Claude API
    ├── use_gemini.py                  # Idea generation: Google Gemini
    └── use_ollama.py                  # Idea generation: local models
```

### Literature search — backend selection

The Phase 1.5 module picks a backend with this priority:

1. `NOVELTY_LLM_BACKEND` env var (explicit override: `openai` / `anthropic` / `gemini` / `ollama` / `none`)
2. `OPENAI_API_KEY` → OpenAI
3. `ANTHROPIC_API_KEY` → Anthropic
4. `GOOGLE_API_KEY` → Gemini
5. A running Ollama on `$OLLAMA_URL` (default `http://localhost:11434`)
6. `none` — skip classification, still return papers

Per-backend model defaults (override via env):

| Backend | Env var | Default model |
|---|---|---|
| openai | `NOVELTY_OPENAI_MODEL` | `gpt-4o-mini` |
| anthropic | `NOVELTY_ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` |
| gemini | `NOVELTY_GEMINI_MODEL` | `gemini-2.5-flash` |
| ollama | `NOVELTY_OLLAMA_MODEL` | `qwen2.5:7b` |

Programmatic usage:

```python
from lit_search import search_recent_literature

res = search_recent_literature(
    "LLM reasoning token efficiency",
    months_back=24,
    top_k=15,
    backend=None,        # None = auto-detect
)
print(res["lens_distribution"])   # e.g. {"C12": 8, "C11": 3, ...}
print(res["saturated_lenses"])    # lenses that already dominate this topic
print(res["under_used_lenses"])   # open opportunities to feed Phase 2
if res["warning"]:
    print("[!]", res["warning"])  # load-bearing: never silently ignore
```

## How It Works

The skill is built from:
- **1,370 papers** from ICLR, NeurIPS, ICML (2020-2025)
- **Three paper types**: 1,024 Oral + 239 High-Cited + 132 Rejected
- **SPECTER2 embeddings** of domain-abstracted innovation strategy descriptions
- **HDBSCAN clustering** discovering 18 innovation patterns
- **Three-way contrastive analysis** producing success conditions, failure modes, and impact drivers for each pattern

For the full methodology, see our paper: *"Can Frontier ML Innovation Be Modeled, Predicted, and Operationalized?"*

## Requirements

- **Claude Code**: No additional dependencies (native skill)
- **API usage**: `pip install openai` / `pip install anthropic` / `pip install google-genai`
- **Local models**: Ollama + a model with 32K+ context window
- **Minimum context window**: 20K tokens (for system_prompt.txt)

## Citation

```bibtex
@article{noveskill2026,
  title={Can Frontier ML Innovation Be Modeled, Predicted, and Operationalized?},
  year={2026},
}
```
