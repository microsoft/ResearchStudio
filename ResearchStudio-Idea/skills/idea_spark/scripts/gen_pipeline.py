from __future__ import annotations

import argparse
import base64
import os
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SUMMARIZER_SYSTEM_PROMPT = (
    "You are a senior ML researcher preparing a concise specification of a "
    "method so that a downstream image model can render a faithful pipeline "
    "diagram. Read the provided research description and produce a compact, "
    "structured summary that:\n"
    "  1. Names the method (if available) and its one-line goal.\n"
    "  2. Lists every distinct stage / module of the pipeline in execution order, "
    "     each as a short noun phrase (3-6 words).\n"
    "  3. For each stage, gives ONE short sub-line describing its function "
    "     and, where relevant, its input and output tensors / artifacts.\n"
    "  4. Explicitly identifies the input(s) on the far left/top and the "
    "     final output(s) on the far right/bottom.\n"
    "  5. Notes any feedback loops, skip connections, or branching paths.\n"
    "Do NOT include motivation, related work, results, or prose paragraphs. "
    "Return plain text only — no markdown headers, no code fences."
)


DIAGRAM_PROMPT_TEMPLATE = (
    "Render a clean, publication-quality METHOD PIPELINE / FRAMEWORK OVERVIEW "
    "diagram suitable for the main figure of a top-tier ML conference paper "
    "(NeurIPS / ICML / ICLR / CVPR style).\n\n"
    "LAYOUT\n"
    "  - Strict left-to-right (preferred) or top-to-bottom data flow.\n"
    "  - Each major stage is a distinct rectangular block with a short title "
    "    and, optionally, one sub-line of clarifying text.\n"
    "  - Connect blocks with thin straight or right-angled arrows showing the "
    "    direction of data flow. Label arrows only when the data type is "
    "    non-obvious (e.g. 'embeddings', 'logits').\n"
    "  - Place input artifacts (data, prompts, images, etc.) on the far left "
    "    or top; place final outputs on the far right or bottom.\n"
    "  - Group sub-modules belonging to the same stage inside a lightly "
    "    shaded rounded container.\n\n"
    "STYLE\n"
    "  - Flat, vector-style aesthetic. NO 3D, NO drop shadows, NO gradients, "
    "    NO photorealistic textures, NO decorative clip-art.\n"
    "  - Restrained academic palette: white background, light blue / light "
    "    gray / pale beige fills, dark gray or black borders and text.\n"
    "  - Use at most 4 distinct fill colors; reuse a color to indicate that "
    "    blocks share a role (e.g. all encoders one color).\n"
    "  - Sans-serif typography, consistent font size, ample whitespace, "
    "    aligned baselines.\n\n"
    "TEXT\n"
    "  - All text in clear, correctly spelled English.\n"
    "  - Keep block titles to <= 4 words; sub-lines to <= 8 words.\n"
    "  - Do NOT invent components that are not in the specification below.\n"
    "  - Do NOT add a title bar, caption, legend, page number, or watermark.\n\n"
    "METHOD SPECIFICATION\n"
    "{method_text}\n"
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def read_novelty(path: str = "novelty.txt") -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt(method_text: str) -> str:
    return DIAGRAM_PROMPT_TEMPLATE.format(method_text=method_text.strip())


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def generate_pipeline(input_path: str, output_path: str | None = None) -> str | None:
    """Generate a pipeline diagram from a research-idea text file.

    Returns the output image path on success, or None on failure.
    """
    endpoint = os.getenv("AZURE_OPENAI_IMAGE_ENDPOINT", "")
    api_version = os.getenv("OPENAI_API_VERSION", "2025-04-01-preview")
    chat_model = os.getenv("CHAT_DEPLOYMENT_NAME", "gpt-5.2")
    image_model = os.getenv("IMAGE_DEPLOYMENT_NAME", "gpt-5.2")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")

    try:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(managed_identity_client_id=identity_id),
            "https://cognitiveservices.azure.com/.default",
        )

        # Single client using AAD auth for both chat and image endpoints.
        client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )

        novelty_text = read_novelty(input_path)

        print("Summarizing method for diagram generation...")
        chat_response = client.chat.completions.create(
            model=chat_model,
            messages=[
                {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
                {"role": "user", "content": novelty_text},
            ],
            max_completion_tokens=16384,
        )
        method_text = chat_response.choices[0].message.content or ""
        if not method_text.strip():
            print("Warning: empty method summary returned by chat model.", file=sys.stderr)
            return None

        prompt = build_prompt(method_text)

        print("Generating method pipeline diagram...")
        result = client.images.generate(
            model=image_model,
            prompt=prompt,
            n=1,
            size="1536x1024",
            quality="medium",
        )

        image_b64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_b64)

        if output_path is None:
            output_path = os.path.splitext(input_path)[0] + "_pipeline.png"
        with open(output_path, "wb") as f:
            f.write(image_bytes)

        print(f"Image saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"gen_pipeline failed: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a method pipeline diagram from a research idea."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="novelty.txt",
        help="Path to the novelty text file (default: novelty.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output image path (default: <input>_pipeline.png)",
    )
    args = parser.parse_args()

    out = generate_pipeline(args.input, args.output)
    sys.exit(0 if out else 1)
