"""
NoveltySkill with OpenAI GPT-4o / GPT-4.1
Usage: python use_openai.py "How to improve LLM reasoning without more training data"
"""

import sys
import os
from openai import OpenAI

def load_system_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'skill', 'system_prompt.txt')
    with open(prompt_path) as f:
        return f.read()

def generate_idea(problem: str, model: str = "gpt-4o") -> str:
    client = OpenAI()  # uses OPENAI_API_KEY env var
    system = load_system_prompt()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": problem},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    return response.choices[0].message.content

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python use_openai.py \"your research problem\"")
        print("Set OPENAI_API_KEY environment variable first.")
        sys.exit(1)

    problem = " ".join(sys.argv[1:])
    print(f"Problem: {problem}\n")
    print("Generating idea with NoveltySkill...\n")
    result = generate_idea(problem)
    print(result)
