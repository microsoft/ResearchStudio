#!/usr/bin/env bash
# fetch_paper.sh — download a paper PDF and extract its text.
#
# Usage:
#   scripts/fetch_paper.sh <PDF_URL> <pdf_name>
#
# Behavior:
#   1. Downloads the PDF to ${CLAUDE_PROJECT_DIR}/papers/<pdf_name>.pdf via curl
#      (falls back to wget if curl is missing).
#   2. Verifies the result is actually a PDF (catches HTML error pages saved
#      as .pdf).
#   3. Extracts text to ${CLAUDE_PROJECT_DIR}/papers/<pdf_name>.txt using
#      `pdftotext -layout`. Falls back to plain `pdftotext`, then to a Python
#      pdfplumber/pymupdf extractor if either is available.
#   4. On success, prints the final .txt path on the last line of stdout so
#      callers can capture it.
#   5. On unrecoverable failure, prints a "FAILED: <reason>" line and exits
#      non-zero. Callers should fall back to abstract-only handling.
#
# This script exists so Step 5 of the scoop-check skill has a single,
# deterministic entry point. Editing the recipe here updates every future
# invocation at once.

set -u
set -o pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <PDF_URL> <pdf_name>" >&2
  exit 2
fi

PDF_URL="$1"
PDF_NAME="$2"

: "${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR must be set}"
PAPERS_DIR="${CLAUDE_PROJECT_DIR}/papers"
mkdir -p "${PAPERS_DIR}"

PDF_PATH="${PAPERS_DIR}/${PDF_NAME}.pdf"
TXT_PATH="${PAPERS_DIR}/${PDF_NAME}.txt"

# -- Step 1: download --------------------------------------------------------
download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 60 -o "${PDF_PATH}" "${PDF_URL}"
  elif command -v wget >/dev/null 2>&1; then
    wget -q --timeout=60 -O "${PDF_PATH}" "${PDF_URL}"
  else
    echo "FAILED: neither curl nor wget is installed" >&2
    return 1
  fi
}

if ! download; then
  echo "FAILED: download error for ${PDF_URL}" >&2
  exit 1
fi

# -- Step 2: verify it's actually a PDF --------------------------------------
if ! file "${PDF_PATH}" 2>/dev/null | grep -qi 'PDF document'; then
  echo "FAILED: ${PDF_PATH} is not a PDF (likely an HTML error page)" >&2
  exit 1
fi

# -- Step 3: extract text ----------------------------------------------------
extract_with_pdftotext_layout() {
  pdftotext -layout "${PDF_PATH}" "${TXT_PATH}" 2>/dev/null
}
extract_with_pdftotext_plain() {
  pdftotext "${PDF_PATH}" "${TXT_PATH}" 2>/dev/null
}
extract_with_python() {
  # Try pdfplumber first, then pymupdf. Both are common; either is fine.
  python3 - "${PDF_PATH}" "${TXT_PATH}" <<'PY' 2>/dev/null
import sys
src, dst = sys.argv[1], sys.argv[2]
text = None
try:
    import pdfplumber
    with pdfplumber.open(src) as pdf:
        text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
except Exception:
    try:
        import fitz  # pymupdf
        doc = fitz.open(src)
        text = "\n\n".join(page.get_text() for page in doc)
    except Exception:
        sys.exit(2)
if not text or not text.strip():
    sys.exit(3)
with open(dst, "w") as f:
    f.write(text)
PY
}

EXTRACTOR=""
if command -v pdftotext >/dev/null 2>&1 && extract_with_pdftotext_layout && [[ -s "${TXT_PATH}" ]]; then
  EXTRACTOR="pdftotext -layout"
elif command -v pdftotext >/dev/null 2>&1 && extract_with_pdftotext_plain && [[ -s "${TXT_PATH}" ]]; then
  EXTRACTOR="pdftotext (plain)"
elif extract_with_python && [[ -s "${TXT_PATH}" ]]; then
  EXTRACTOR="python (pdfplumber/pymupdf)"
else
  echo "FAILED: no working PDF-to-text extractor produced output" >&2
  exit 1
fi

# -- Step 4: report results --------------------------------------------------
PDF_SIZE=$(wc -c < "${PDF_PATH}" 2>/dev/null || echo 0)
TXT_SIZE=$(wc -c < "${TXT_PATH}" 2>/dev/null || echo 0)
TXT_LINES=$(wc -l < "${TXT_PATH}" 2>/dev/null || echo 0)

echo "ok: extractor=${EXTRACTOR} pdf_bytes=${PDF_SIZE} txt_bytes=${TXT_SIZE} txt_lines=${TXT_LINES}"
echo "${TXT_PATH}"
