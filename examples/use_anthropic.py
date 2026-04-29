"""
NoveltySkill with Anthropic Claude API (without Claude Code)
Usage: python use_anthropic.py "How to improve LLM reasoning without more training data"
"""

import sys
import os
import anthropic

def load_system_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'skill', 'system_prompt.txt')
    with open(prompt_path) as f:
        return f.read()

def generate_idea(problem: str, model: str = "claude-sonnet-4-6") -> str:
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    system = load_system_prompt()

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[
            {"role": "user", "content": problem},
        ],
    )
    return response.content[0].text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python use_anthropic.py \"your research problem\"")
        print("Set ANTHROPIC_API_KEY environment variable first.")
        sys.exit(1)

    problem = " ".join(sys.argv[1:])
    print(f"Problem: {problem}\n")
    print("Generating idea with NoveltySkill...\n")
    result = generate_idea(problem)
    print(result)
