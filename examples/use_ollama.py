"""
NoveltySkill with local models via Ollama (Llama, Qwen, DeepSeek, etc.)
Usage: python use_ollama.py "How to improve LLM reasoning without more training data"

Requires: ollama running locally with a model pulled (e.g., ollama pull qwen2.5:72b)
Note: system_prompt.txt is ~19K tokens. Use models with >=32K context window.
Recommended: qwen2.5:72b, llama3.1:70b, deepseek-v3, or any model with 32K+ context.
"""

import sys
import os
import requests
import json

OLLAMA_URL = "http://localhost:11434/api/chat"

def load_system_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'skill', 'system_prompt.txt')
    with open(prompt_path) as f:
        return f.read()

def generate_idea(problem: str, model: str = "qwen2.5:72b") -> str:
    system = load_system_prompt()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": problem},
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_ctx": 32768,
        },
    }

    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()
    return response.json()["message"]["content"]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python use_ollama.py \"your research problem\"")
        print("Make sure Ollama is running: ollama serve")
        print("And a model is pulled: ollama pull qwen2.5:72b")
        sys.exit(1)

    problem = " ".join(sys.argv[1:])
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:72b")
    print(f"Problem: {problem}")
    print(f"Model: {model}\n")
    print("Generating idea with NoveltySkill...\n")
    result = generate_idea(problem, model)
    print(result)
