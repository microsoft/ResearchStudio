#!/usr/bin/env bash
#
# ResearchStudio — unified installer for ResearchStudio-Idea + ResearchStudio-Reel.
#
# Lets you pick:
#   • which skill bundles to install   — Idea, Reel, or both
#   • which agent runtimes to link into — Claude Code, Codex, QwenPaw, and/or Qoder
#
# Auto-detects OS + Python, installs each bundle's native and Python deps,
# and symlinks the selected skills into <repo-root>/.claude/skills/ and/or
# <repo-root>/.codex/skills/ and/or <repo-root>/.qoder/skills/ (all git-ignored).
# QwenPaw gets real copies in its shared skill pool instead of links — its
# scanner rejects symlinked skill dirs. Idempotent — safe to re-run.
#
# Usage:
#   bash install.sh                              # interactive prompts
#   bash install.sh --yes                        # non-interactive (idea+reel, claude only)
#   bash install.sh --idea --claude              # explicit selection
#   bash install.sh --reel --codex --with-pdf    # explicit selection + LaTeX
#   bash install.sh --idea --reel --claude --codex --qwenpaw --qoder
#
# Flags (anything you don't pass falls back to a prompt, or the --yes defaults):
#   --idea / --no-idea            include / skip Idea skills
#   --reel / --no-reel            include / skip Reel skills
#   --claude / --no-claude        link into <repo-root>/.claude/skills/
#   --codex / --no-codex          link into <repo-root>/.codex/skills/
#   --qwenpaw / --no-qwenpaw      copy into the QwenPaw shared skill pool
#   --qoder / --no-qoder          link into <repo-root>/.qoder/skills/
#   --with-pdf                    also install a LaTeX engine (Idea PDF idea cards)
#   --yes, -y                     non-interactive; default selection = idea+reel for Claude
#   --help, -h                    this help
#
# Env overrides:
#   PYTHON=./.venv/bin/python          use a specific interpreter
#   EDITOR=code                        use a specific editor (defaults to vim)
#   CLAUDE_SKILLS_DIR=/custom/path      use a non-default Claude skills dir
#   CODEX_SKILLS_DIR=/custom/path       use a non-default Codex skills dir
#   QODER_SKILLS_DIR=/custom/path       use a non-default Qoder skills dir
#   QWENPAW_WORKING_DIR=/custom/path    use a non-default QwenPaw working dir
#   QWENPAW_POOL_DIR=/custom/path       use a non-default QwenPaw skill pool
#
set -euo pipefail

# Some install steps and their child processes expect EDITOR to be set. Keep a
# caller-provided value; otherwise use the widely available terminal editor.
export EDITOR="${EDITOR:-vim}"

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IDEA_REPO="${REPO_ROOT}/ResearchStudio-Idea"
REEL_REPO="${REPO_ROOT}/ResearchStudio-Reel"

CLAUDE_SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$REPO_ROOT/.claude/skills}"
CODEX_SKILLS_DIR="${CODEX_SKILLS_DIR:-$REPO_ROOT/.codex/skills}"
QODER_SKILLS_DIR="${QODER_SKILLS_DIR:-$REPO_ROOT/.qoder/skills}"

# QwenPaw working-dir resolution mirrors its own constant.py: explicit
# QWENPAW_WORKING_DIR first, then the legacy ~/.copaw layout, then ~/.qwenpaw.
if [ -n "${QWENPAW_WORKING_DIR:-}" ]; then
  QWENPAW_HOME="${QWENPAW_WORKING_DIR}"
elif [ -d "$HOME/.copaw" ]; then
  QWENPAW_HOME="$HOME/.copaw"
else
  QWENPAW_HOME="$HOME/.qwenpaw"
fi
QWENPAW_POOL_DIR="${QWENPAW_POOL_DIR:-$QWENPAW_HOME/skill_pool}"

# ---------------------------------------------------------------------------
# pretty-print helpers
# ---------------------------------------------------------------------------
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
log()   { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------
USE_IDEA=""; USE_REEL=""
USE_CLAUDE=""; USE_CODEX=""; USE_QWENPAW=""; USE_QODER=""
WITH_PDF=0
NONINTERACTIVE=0

print_help() {
  # Print the leading comment block (everything after the shebang up to the
  # first non-comment line) so adding a flag never silently truncates --help.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --idea)        USE_IDEA=1 ;;
    --no-idea)     USE_IDEA=0 ;;
    --reel)        USE_REEL=1 ;;
    --no-reel)     USE_REEL=0 ;;
    --claude)      USE_CLAUDE=1 ;;
    --no-claude)   USE_CLAUDE=0 ;;
    --codex)       USE_CODEX=1 ;;
    --no-codex)    USE_CODEX=0 ;;
    --qwenpaw)     USE_QWENPAW=1 ;;
    --no-qwenpaw)  USE_QWENPAW=0 ;;
    --qoder)       USE_QODER=1 ;;
    --no-qoder)    USE_QODER=0 ;;
    --with-pdf)    WITH_PDF=1 ;;
    --yes|-y)      NONINTERACTIVE=1 ;;
    --help|-h)     print_help; exit 0 ;;
    *) die "Unknown flag: $1  (try --help)" ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# interactive prompts (only ask when a flag wasn't set)
# ---------------------------------------------------------------------------
ask_yn() {
  # ask_yn "question" "default(Y|N)" -> returns 0 for yes, 1 for no
  local q="$1" def="$2" ans
  if [ "$NONINTERACTIVE" = 1 ] || [ ! -t 0 ]; then
    [ "$def" = "Y" ] && return 0 || return 1
  fi
  local hint="[Y/n]"
  [ "$def" = "N" ] && hint="[y/N]"
  printf '\033[1m%s %s \033[0m' "$q" "$hint"
  read -r ans || true
  ans="${ans:-$def}"
  case "$ans" in
    [Yy]*) return 0 ;;
    *)     return 1 ;;
  esac
}

bold " installer"
echo "  repo root:    $REPO_ROOT"

# Bundle selection
if [ -z "$USE_IDEA" ]; then ask_yn "Install ResearchStudio-Idea skills (idea-spark, paper-search, scoop-check)?" Y && USE_IDEA=1 || USE_IDEA=0; fi
if [ -z "$USE_REEL" ]; then ask_yn "Install ResearchStudio-Reel skills (paper2assets, paper2poster, paper2video, paper2blog, paper2reel)?" Y && USE_REEL=1 || USE_REEL=0; fi

if [ "$USE_IDEA" = 0 ] && [ "$USE_REEL" = 0 ]; then
  die "Nothing selected — pick --idea and/or --reel."
fi

# Runtime selection
if [ -z "$USE_CLAUDE" ]; then ask_yn "Link skills for Claude Code  (-> $CLAUDE_SKILLS_DIR)?" Y && USE_CLAUDE=1 || USE_CLAUDE=0; fi
if [ -z "$USE_CODEX"  ]; then ask_yn "Link skills for Codex        (-> $CODEX_SKILLS_DIR)?"  N && USE_CODEX=1  || USE_CODEX=0;  fi
if [ -z "$USE_QWENPAW" ]; then ask_yn "Copy skills into the QwenPaw pool (-> $QWENPAW_POOL_DIR)?" N && USE_QWENPAW=1 || USE_QWENPAW=0; fi
if [ -z "$USE_QODER" ]; then ask_yn "Link skills for Qoder CLI    (-> $QODER_SKILLS_DIR)?" N && USE_QODER=1 || USE_QODER=0; fi

if [ "$USE_CLAUDE" = 0 ] && [ "$USE_CODEX" = 0 ] && [ "$USE_QWENPAW" = 0 ] && [ "$USE_QODER" = 0 ]; then
  die "No runtime selected — pick --claude, --codex, --qwenpaw and/or --qoder."
fi

echo
echo "  bundles:      $([ "$USE_IDEA" = 1 ] && echo -n "Idea ")$([ "$USE_REEL" = 1 ] && echo -n "Reel")"
echo "  runtimes:     $([ "$USE_CLAUDE" = 1 ] && echo -n "Claude($CLAUDE_SKILLS_DIR) ")$([ "$USE_CODEX" = 1 ] && echo -n "Codex($CODEX_SKILLS_DIR) ")$([ "$USE_QWENPAW" = 1 ] && echo -n "QwenPaw($QWENPAW_POOL_DIR) ")$([ "$USE_QODER" = 1 ] && echo -n "Qoder($QODER_SKILLS_DIR)")"
echo "  optional pdf: $([ "$WITH_PDF" = 1 ] && echo yes || echo no)"

# Sanity: required bundle repos must exist
[ "$USE_IDEA" = 1 ] && [ ! -d "$IDEA_REPO/skills" ] && die "Missing ${IDEA_REPO}/skills — did you clone the submodule?"
[ "$USE_REEL" = 1 ] && [ ! -d "$REEL_REPO/skills" ] && die "Missing ${REEL_REPO}/skills — did you clone the submodule?"

# ---------------------------------------------------------------------------
# 0) OS detect (for package-manager hints)
# ---------------------------------------------------------------------------
case "$(uname -s)" in
  Darwin) OS=macos; PKG=brew ;;
  Linux)
    if grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then OS=wsl; else OS=linux; fi
    if   command -v apt-get >/dev/null 2>&1; then PKG=apt
    elif command -v dnf     >/dev/null 2>&1; then PKG=dnf
    elif command -v pacman  >/dev/null 2>&1; then PKG=pacman
    else PKG=none; fi ;;
  MINGW*|MSYS*|CYGWIN*|Windows*)
    echo "Windows shell detected — install.sh is a bash script. Run it inside WSL (Ubuntu):"
    echo "    wsl --install        # one-time, then reopen Ubuntu and re-run: bash install.sh"
    exit 1 ;;
  *) OS=unknown; PKG=none ;;
esac
echo "  os:           $OS  (package manager: $PKG)"

# ---------------------------------------------------------------------------
# 1) Python detection — Reel needs ≥3.10, Idea-only is happy with ≥3.9
# ---------------------------------------------------------------------------
MIN_PY="3.9"
[ "$USE_REEL" = 1 ] && MIN_PY="3.10"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= tuple(int(x) for x in '$MIN_PY'.split('.')) else 1)" 2>/dev/null; then
      PY="$c"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "Python ${MIN_PY}+ not found. Install it, then re-run."
  case "$OS" in
    macos)     echo "    brew install python" ;;
    wsl|linux) [ "$PKG" = apt ] && echo "    sudo apt-get install -y python3 python3-pip" || echo "    install python3 (>=${MIN_PY}) with your package manager" ;;
    *)         echo "    install python3 (>=${MIN_PY})" ;;
  esac
  exit 1
fi
PY_EXE="$("$PY" -c 'import sys; print(sys.executable)')"
# Re-point $PY at the interpreter's absolute path. Steps below run in subshells
# that `cd` elsewhere, so a caller-supplied relative value — the documented
# `PYTHON=./.venv/bin/python` — would otherwise stop resolving mid-install.
case "$PY_EXE" in
  /*) PY="$PY_EXE" ;;
  [A-Za-z]:[\\/]*) PY="$PY_EXE" ;;   # Windows-style absolute (bash on Windows)
esac
echo "  python:       $("$PY" --version 2>&1) — $PY_EXE"

# A default `uv venv` intentionally has no pip module. Prefer pip when the
# selected interpreter provides it (including conda), otherwise let uv install
# directly into that interpreter's environment.
if "$PY" -m pip --version >/dev/null 2>&1; then
  PY_PACKAGE_MANAGER=pip
elif command -v uv >/dev/null 2>&1; then
  PY_PACKAGE_MANAGER=uv
else
  die "Neither pip for $PY_EXE nor uv was found. Install pip or uv, then re-run."
fi
echo "  python deps:  $PY_PACKAGE_MANAGER"
echo

# ---------------------------------------------------------------------------
# helpers used by both bundles
# ---------------------------------------------------------------------------

# pip_install <pkg> [<pkg> …] — install into the selected conda/venv/uv environment.
pip_install() {
  if [ "$PY_PACKAGE_MANAGER" = uv ]; then
    uv pip install --python "$PY_EXE" --upgrade "$@"
    return
  fi
  if "$PY" -m pip install --upgrade "$@"; then return 0; fi
  if "$PY" -m pip install --user --break-system-packages --upgrade "$@"; then
    echo "  (used --user --break-system-packages for an externally-managed environment)"
    return 0
  fi
  "$PY" -m pip install --user --upgrade "$@"
}

# skill_slot_name <abs_src_dir> — the name a skill declares in its SKILL.md
# frontmatter. That is the identity agent hosts show the user, and it need not
# match the directory (idea_spark/ declares name: idea-spark). Falls back to the
# directory name, so installers never carry a rename table that can go stale.
skill_slot_name() {
  local src="$1" name
  name="$(sed -n '2,120p' "$src/SKILL.md" 2>/dev/null \
            | awk '/^---[[:space:]]*$/{ exit } { print }' \
            | sed -n 's/^name:[[:space:]]*//p' | head -n1)"
  name="${name%\"}"; name="${name#\"}"
  printf '%s' "${name:-$(basename "$src")}"
}

# copy_skill_qwenpaw <abs_src_dir> — real copy into the QwenPaw shared pool.
# QwenPaw's scanner resolves skill dirs and rejects anything outside the pool
# root, so symlinked skills would be dropped — pool entries must be copies.
copy_skill_qwenpaw() {
  local src="$1" name slot
  [ -d "$src" ] || { warn "missing $src — skipped"; return; }
  name="$(skill_slot_name "$src")"
  mkdir -p "$QWENPAW_POOL_DIR"
  rm -rf "$QWENPAW_POOL_DIR/$name"
  slot="$(basename "$src")"
  [ "$slot" = "$name" ] || rm -rf "$QWENPAW_POOL_DIR/$slot"
  cp -R "$src" "$QWENPAW_POOL_DIR/$name"
  printf '   • qwenpaw %s → %s\n' "$name" "$QWENPAW_POOL_DIR/$name"
}

# link_into <abs_dst> <abs_src> — symlink the skill, falling back to a real copy
# on a filesystem that won't take symlinks (some mounted / Windows-drive repos).
# Returns 1 when it had to copy, so the caller can label the line it prints.
link_into() {
  local dst="$1" src="$2" slot
  mkdir -p "$(dirname "$dst")"
  rm -rf "$dst"
  # A skill installed before its frontmatter name was adopted still sits in the
  # skills dir under its directory name; every host lists both. Clear it.
  slot="$(basename "$src")"
  [ "$slot" = "$(basename "$dst")" ] || rm -rf "$(dirname "$dst")/$slot"
  ln -s "$src" "$dst" 2>/dev/null && return 0
  cp -R "$src" "$dst"
  return 1
}

# link_skill <abs_src_dir>  — into every selected runtime's skills dir.
link_skill() {
  local src="$1" name
  [ -d "$src" ] || { warn "missing $src — skipped"; return; }
  name="$(skill_slot_name "$src")"
  if [ "$USE_CLAUDE" = 1 ]; then
    local dst="$CLAUDE_SKILLS_DIR/$name" how="→"
    link_into "$dst" "$src" || how="(copied)"
    printf '   • claude  %s %s %s\n' "$name" "$how" "$src"
  fi
  if [ "$USE_CODEX" = 1 ]; then
    local dst="$CODEX_SKILLS_DIR/$name" how="→"
    link_into "$dst" "$src" || how="(copied)"
    printf '   • codex   %s %s %s\n' "$name" "$how" "$src"
  fi
  if [ "$USE_QODER" = 1 ]; then
    local dst="$QODER_SKILLS_DIR/$name" how="→"
    link_into "$dst" "$src" || how="(copied)"
    printf '   • qoder   %s %s %s\n' "$name" "$how" "$src"
  fi
  if [ "$USE_QWENPAW" = 1 ]; then
    copy_skill_qwenpaw "$src"
  fi
}

# seed_config <runtime>  — write the embedded settings.json into
# <repo-root>/.<runtime>/ unless one is already present. The settings are
# inlined below (no .<runtime>_template/ directory required) so the installer
# is self-contained. Re-runs leave user edits intact.
seed_config() {
  local runtime="$1"
  local dst_dir="$REPO_ROOT/.${runtime}"
  local dst="$dst_dir/settings.json"
  mkdir -p "$dst_dir"
  if [ -f "$dst" ]; then
    echo "  $dst already exists — left untouched"
    return 0
  fi
  case "$runtime" in
    claude)
      cat >"$dst" <<'CLAUDE_SETTINGS_JSON'
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read",
      "Write",
      "Edit",
      "WebFetch(*)",
      "NotebookEdit(*)"
    ],
    "defaultMode": "dontAsk"
  },
  "skipDangerousModePermissionPrompt": true,
  "autoCompactEnabled": true,
  "debug": true,
  "effortLevel": "high"
}
CLAUDE_SETTINGS_JSON
      ;;
    codex)
      cat >"$dst" <<'CODEX_SETTINGS_JSON'
{
  "approval_policy": "never",
  "sandbox_mode": "danger-full-access",
  "model_reasoning_effort": "high",
  "model_reasoning_summary": "auto",
  "disable_response_storage": false,
  "hide_agent_reasoning": false,
  "tools": {
    "web_search": true
  },
  "shell_environment_policy": {
    "inherit": "all"
  },
  "history": {
    "persistence": "save-all"
  }
}
CODEX_SETTINGS_JSON
      ;;
    *) warn "seed_config: unknown runtime '$runtime'"; return 1 ;;
  esac
  echo "  seeded $dst"
}

# ---------------------------------------------------------------------------
# 2) ResearchStudio-Idea
# ---------------------------------------------------------------------------
if [ "$USE_IDEA" = 1 ]; then
  bold "── Installing ResearchStudio-Idea ──"

  log "Python dependencies (idea-spark, paper-search, scoop-check)"
  IDEA_PKGS=(
    "feedparser>=6.0.12"        # idea-spark: arXiv connector
    "openreview-py>=2.2.3"      # idea-spark + paper-search: OpenReview connector
    "beautifulsoup4>=4.13.0"    # idea-spark: full-text HTML parsing
    "pymupdf>=1.26.0"           # idea-spark: full-text PDF parsing
    "scholarly>=1.7.11"         # paper-search: Google Scholar connector
    "requests>=2.31.0"          # paper-search / idea-spark: HTTP
  )
  pip_install "${IDEA_PKGS[@]}"

  log "Linking Idea skills"
  # Slot names come from each skill's own frontmatter, and any older slot left
  # behind under the source directory name is cleared as the new one is written.
  link_skill "$IDEA_REPO/skills/idea_spark"
  link_skill "$IDEA_REPO/skills/paper_search"
  link_skill "$IDEA_REPO/skills/scoop_check"

  log ".env scaffold"
  if [ -f "$REPO_ROOT/.env" ]; then
    echo "  .env already exists — left untouched"
  elif [ -f "$IDEA_REPO/.env.template" ]; then
    cp "$IDEA_REPO/.env.template" "$REPO_ROOT/.env"
    echo "  created .env from .env.template — fill in the Phase 0 connector keys"
  else
    echo "  (no .env.template found — skipping)"
  fi

  log "Verifying IdeaSpark connectors (best-effort)"
  ( cd "$IDEA_REPO/skills/idea_spark" && "$PY" -m scripts.run check_connectors ) \
    || echo "  (connector check skipped/failed — fill .env and re-run: cd ResearchStudio-Idea/skills/idea_spark && $PY -m scripts.run check_connectors)"

  log "PDF idea cards (optional LaTeX engine)"
  if command -v tectonic >/dev/null 2>&1 || command -v xelatex >/dev/null 2>&1; then
    echo "  a LaTeX engine is already on PATH ✓"
  else
    case "$OS" in
      macos)      PDF_CMD="brew install tectonic" ;;
      wsl|linux)
        case "$PKG" in
          apt)    PDF_CMD="sudo apt-get install -y texlive-xetex" ;;
          dnf)    PDF_CMD="sudo dnf install -y texlive-xetex" ;;
          pacman) PDF_CMD="sudo pacman -S --noconfirm texlive-bin texlive-latexextra" ;;
          *)      PDF_CMD="cargo install tectonic" ;;
        esac ;;
      *)          PDF_CMD="install 'tectonic' or 'xelatex'" ;;
    esac
    if [ "$WITH_PDF" = 1 ]; then
      echo "  installing a LaTeX engine: $PDF_CMD"
      eval "$PDF_CMD" || echo "  (install failed — cards still render as .md/.tex; only the PDF is skipped)"
    else
      echo "  none found — cards still render as .md/.tex (only the PDF is skipped)."
      echo "  for PDF cards:  $PDF_CMD      (or re-run: bash install.sh --idea --with-pdf)"
    fi
  fi
  echo
fi

# ---------------------------------------------------------------------------
# 3) ResearchStudio-Reel
# ---------------------------------------------------------------------------
if [ "$USE_REEL" = 1 ]; then
  bold "── Installing ResearchStudio-Reel ──"

  log "Native tools (poppler-utils, libreoffice, ffmpeg)"
  REEL_APT=(poppler-utils libreoffice ffmpeg)
  case "$PKG" in
    apt)
      SUDO=""; [ "${EUID:-$(id -u)}" -ne 0 ] && SUDO="sudo"
      ${SUDO} apt-get update -y || warn "apt-get update failed — continuing"
      ${SUDO} apt-get install -y --no-install-recommends "${REEL_APT[@]}" || warn "native tools (poppler-utils/libreoffice/ffmpeg) failed to install — Reel features degrade; install manually if needed"
      ;;
    brew)
      brew install poppler ffmpeg || warn "poppler/ffmpeg via brew failed — Reel features may degrade"
      brew install --cask libreoffice || warn "libreoffice cask failed — install manually if you need it"
      ;;
    dnf)    sudo dnf install -y poppler-utils libreoffice ffmpeg || warn "native tools failed — Reel features degrade; install manually if needed" ;;
    pacman) sudo pacman -S --noconfirm poppler libreoffice-fresh ffmpeg || warn "native tools failed — Reel features degrade; install manually if needed" ;;
    *)      warn "no known package manager — install these manually: ${REEL_APT[*]}" ;;
  esac

  log "Python dependencies (PyMuPDF, Pillow, numpy, python-docx, qrcode, playwright, imageio-ffmpeg, edge-tts)"
  REEL_PIP=(
    "pymupdf"
    "pillow"
    "numpy"
    "python-docx>=1.1.2"
    "qrcode"
    "playwright"
    "imageio-ffmpeg"
    "edge-tts>=7.2.8"
  )
  if [ "$PY_PACKAGE_MANAGER" = pip ]; then
    "$PY" -m pip install --upgrade pip || true
  fi
  pip_install "${REEL_PIP[@]}"

  log "Playwright Chromium (used by Paper2Poster HTML → PDF/PNG)"
  "$PY" -m playwright install chromium

  log "Linking Reel skills"
  for skill_dir in "$REEL_REPO/skills"/*/; do
    link_skill "${skill_dir%/}"
  done

  # Paper2Video delegates deck authoring to ppt-master and rendering/QA to
  # pptx2video. Fetch both skills from their upstream repos via `npx skills add`.
  # The skills CLI refuses non-interactive runs without --agent, and the agent
  # choice only decides where content lands, so fetch into a throwaway dir and
  # copy from there into every selected runtime.
  if command -v npx >/dev/null 2>&1; then
    log "Fetching Paper2Video dependency skills via npx skills add (ppt-master, pptx2video)"
    dep_tmp="$(mktemp -d)"
    npx -y skills add hugohe3/ppt-master --skill ppt-master -y --agent claude-code \
      || warn "npx skills add failed for ppt-master — install manually; paper2video will not work until then"
    npx -y skills add ai-nuts/pptx2video --skill pptx2video -y --agent claude-code \
      || warn "npx skills add failed for pptx2video — install manually; paper2video will not work until then"

    for target_dir in \
      "$([ "$USE_CLAUDE" = 1 ] && echo "$CLAUDE_SKILLS_DIR")" \
      "$([ "$USE_CODEX" = 1 ] && echo "$CODEX_SKILLS_DIR")" \
      "$([ "$USE_QWENPAW" = 1 ] && echo "$QWENPAW_POOL_DIR")" \
      "$([ "$USE_QODER" = 1 ] && echo "$QODER_SKILLS_DIR")"; do
      [ -n "$target_dir" ] || continue
      mkdir -p "$target_dir"
      for dep_name in ppt-master pptx2video; do
        # Accept both CLI layouts: the current direct .claude/skills/<name>
        # and the legacy .agents/skills/<name> scaffold.
        dep_src="$dep_tmp/.claude/skills/$dep_name"
        [ -d "$dep_src" ] || dep_src="$dep_tmp/.agents/skills/$dep_name"
        if [ -d "$dep_src" ]; then
          rm -rf "$target_dir/$dep_name"
          cp -R "$dep_src" "$target_dir/$dep_name"
        fi
      done
    done
    rm -rf "$dep_tmp"
  else
    warn "npx not found — install ppt-master + pptx2video manually:"
    warn "    npx skills add hugohe3/ppt-master --skill ppt-master -y --agent claude-code"
    warn "    npx skills add ai-nuts/pptx2video --skill pptx2video -y --agent claude-code"
  fi
  echo
fi

# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------
if [ "$USE_CLAUDE" = 1 ]; then
  bold "Seeding Claude config (.claude/)"
  seed_config claude
fi
if [ "$USE_CODEX" = 1 ]; then
  bold "Seeding Codex config (.codex/)"
  seed_config codex
fi

# QwenPaw: seed the user-level .env its runtime loads (keys reach skills run
# inside QwenPaw), and nudge a pool manifest reconcile so the new skills show
# up right away. Both best-effort — re-runs never overwrite an existing .env.
if [ "$USE_QWENPAW" = 1 ]; then
  bold "Seeding QwenPaw ($QWENPAW_HOME)"
  if [ -f "$QWENPAW_HOME/.env" ]; then
    echo "  $QWENPAW_HOME/.env already exists — left untouched"
  elif [ -f "$IDEA_REPO/.env.template" ]; then
    mkdir -p "$QWENPAW_HOME"
    cp "$IDEA_REPO/.env.template" "$QWENPAW_HOME/.env"
    echo "  created $QWENPAW_HOME/.env from .env.template — fill in the connector keys"
  fi
  if command -v qwenpaw >/dev/null 2>&1; then
    qwenpaw skills list --pool >/dev/null 2>&1 \
      && echo "  skill pool reconciled — new skills are visible" \
      || echo "  (qwenpaw CLI reconcile failed — skills appear after the next pool refresh)"
  fi
fi

bold "Done."
if [ "$USE_CLAUDE" = 1 ]; then
  echo "  Claude Code:"
  echo "    skills linked into $CLAUDE_SKILLS_DIR"
  echo "    launch with:  CLAUDE_CONFIG_DIR=\"$REPO_ROOT/.claude\" claude"
fi
if [ "$USE_CODEX" = 1 ]; then
  echo "  Codex:"
  echo "    skills linked into $CODEX_SKILLS_DIR"
  echo "    settings:      $REPO_ROOT/.codex/settings.json"
fi
if [ "$USE_QWENPAW" = 1 ]; then
  echo "  QwenPaw:"
  echo "    skills copied into the shared pool: $QWENPAW_POOL_DIR"
  echo "    load them into a workspace: Console → Workspace → Skills → \"Load from Skill Pool\""
  echo "    (or copy a skill into $QWENPAW_HOME/workspaces/<agent_id>/skills/ and run:"
  echo "        qwenpaw skills enable <skill-name> --agent-id <agent_id>)"
fi
if [ "$USE_QODER" = 1 ]; then
  echo "  Qoder:"
  echo "    skills linked into $QODER_SKILLS_DIR"
  echo "    open Qoder in this repo and run /skills to list what it discovered"
  echo "    (invoke one by name, e.g. /idea-spark — see https://docs.qoder.com/cli/Skills)"
fi
if [ "$USE_REEL" = 1 ]; then
  echo
  echo "  Reel notes:"
  echo "    • Export ANTHROPIC_API_KEY (or your backend's key) in your shell."
  echo "    • Paper2Video's 'ppt-master' + 'pptx2video' skills were fetched via npx skills add."
  echo "    • pptx2video also needs its pip runtime (see ResearchStudio-Reel/skills/paper2video/README.md):"
  echo "        pip install 'pptx2video[svg] @ git+https://github.com/ai-nuts/pptx2video.git'"
fi
if [ "$USE_IDEA" = 1 ]; then
  echo
  echo "  Idea notes:"
  echo "    • Fill in connector keys in ResearchStudio-Idea/.env, then re-run the connector check:"
  echo "        cd ResearchStudio-Idea/skills/idea_spark && $PY -m scripts.run check_connectors"
fi

# ---------------------------------------------------------------------------
# Offer to open the connector .env now, otherwise remind the user to fill it in.
# ---------------------------------------------------------------------------
ENV_FILE="$REPO_ROOT/.env"
if [ "$USE_IDEA" = 1 ] && [ -f "$ENV_FILE" ]; then
  echo
  if [ "$NONINTERACTIVE" = 1 ] || [ ! -t 0 ]; then
    echo "  >> Remember to edit $ENV_FILE and fill in your connector keys before the skills can use them."
  elif ask_yn "Open $ENV_FILE in your editor now to fill in the connector keys?" Y; then
    _ed="${VISUAL:-$EDITOR}"
    if   [ -n "$_ed" ];                              then $_ed "$ENV_FILE"
    elif command -v sensible-editor >/dev/null 2>&1; then sensible-editor "$ENV_FILE"
    elif command -v xdg-open        >/dev/null 2>&1; then xdg-open "$ENV_FILE" >/dev/null 2>&1 || true
    elif command -v open            >/dev/null 2>&1; then open "$ENV_FILE"
    elif command -v nano            >/dev/null 2>&1; then nano "$ENV_FILE"
    else                                                  vi "$ENV_FILE"
    fi
  else
    echo "  >> Remember to edit $ENV_FILE and fill in your connector keys before the skills can use them."
  fi
fi
