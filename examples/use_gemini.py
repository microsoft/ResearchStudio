"""
NoveltySkill with Google Gemini
Usage: python use_gemini.py "How to improve LLM reasoning without more training data"
"""

import sys
import os
from google import genai

def load_system_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'skill', 'system_prompt.txt')
    with open(prompt_path) as f:
        return f.read()

def generate_idea(problem: str, model: str = "gemini-2.5-flash") -> str:
    client = genai.Client()  # uses GOOGLE_API_KEY env var
    system = load_system_prompt()

    response = client.models.generate_content(
        model=model,
        contents=problem,
        config=genai.types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    return response.text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python use_gemini.py \"your research problem\"")
        print("Set GOOGLE_API_KEY environment variable first.")
        sys.exit(1)

    problem = " ".join(sys.argv[1:])
    print(f"Problem: {problem}\n")
    print("Generating idea with NoveltySkill...\n")
    result = generate_idea(problem)
    print(result)
