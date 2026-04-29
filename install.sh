#!/bin/bash
# Install NoveltySkill for Claude Code
# Run this in your project root directory

set -e

SKILL_DIR=".claude/skills/novelty-skill"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/claude-code-install/.claude/skills/novelty-skill"

echo "Installing NoveltySkill to $SKILL_DIR ..."

mkdir -p "$SKILL_DIR"

cp "$SOURCE_DIR/SKILL.md" "$SKILL_DIR/"
cp "$SOURCE_DIR/methodologies.md" "$SKILL_DIR/"
cp "$SOURCE_DIR/pitfalls.md" "$SKILL_DIR/"
cp "$SOURCE_DIR/domain-analysis.md" "$SKILL_DIR/"

echo ""
echo "NoveltySkill installed successfully!"
echo ""
echo "Usage:"
echo "  Open Claude Code in this directory, then type:"
echo "  /novelty-skill \"How to improve LLM reasoning without more training data\""
echo ""
echo "Files installed:"
ls -lh "$SKILL_DIR/"
