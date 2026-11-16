"""Minimal Ollama chat client (adapted from Ask Data) with a JSON-mode helper."""
import json
import time
from dataclasses import dataclass
from functools import cache

import requests

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.6:27b"
# Prompts here are a few thousand tokens; 8K keeps the model fully in VRAM on a 24 GB GPU.
NUM_CTX = 8192


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    output_tokens: int
    seconds: float


@cache
def supports_thinking(model: str) -> bool:
    """Reasoning models (e.g. qwen3) write a long hidden "thinking" pass unless it's turned off."""
    r = requests.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=60)
    r.raise_for_status()
    return "thinking" in r.json().get("capabilities", [])


def chat(messages: list[dict], model: str = DEFAULT_MODEL, json_mode: bool = False) -> Reply:
    started = time.time()
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    if json_mode:
        body["format"] = "json"
    if supports_thinking(model):
        body["think"] = False
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=600, json=body)
    r.raise_for_status()
    data = r.json()
    return Reply(data["message"]["content"], data.get("prompt_eval_count", 0),
                 data.get("eval_count", 0), time.time() - started)


def chat_json(messages: list[dict], model: str = DEFAULT_MODEL) -> tuple[dict, Reply]:
    """Ask for a JSON object. Retries once with the parse error if the reply isn't valid JSON."""
    reply = chat(messages, model, json_mode=True)
    try:
        return json.loads(reply.text), reply
    except json.JSONDecodeError as e:
        retry = messages + [{"role": "assistant", "content": reply.text},
                            {"role": "user", "content": f"That wasn't valid JSON ({e}). Reply with the JSON object only."}]
        reply2 = chat(retry, model, json_mode=True)
        reply2.seconds += reply.seconds
        return json.loads(reply2.text), reply2


def unload(model: str = DEFAULT_MODEL) -> None:
    requests.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=120).raise_for_status()
