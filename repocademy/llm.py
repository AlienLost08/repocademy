"""Optional language-model backends. Everything in Repocademy works without one.

Order of preference:
1. Any OpenAI-compatible endpoint you configure (e.g. a free tier):
     REPOCADEMY_LLM_BASE_URL  e.g. https://api.groq.com/openai/v1
                              or https://generativelanguage.googleapis.com/v1beta/openai
     REPOCADEMY_LLM_API_KEY   your key (never sent to the browser, never logged)
     REPOCADEMY_LLM_MODEL     e.g. llama-3.1-8b-instant / gemini-2.0-flash
2. A local Ollama model: REPOCADEMY_OLLAMA_MODEL (default: auto-detect qwen2.5-coder if installed)
     REPOCADEMY_OLLAMA_URL    default http://127.0.0.1:11434
3. None -> deterministic templates only.
Set REPOCADEMY_LLM=off to force templates.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import httpx

_PREFERRED_LOCAL = ["qwen2.5-coder:3b", "qwen2.5-coder:1.5b", "qwen2.5-coder", "qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b"]


class LLM:
    def __init__(self, kind: str, model: str, base_url: str, api_key: str | None = None):
        self.kind, self.model, self.base_url, self._key = kind, model, base_url.rstrip("/"), api_key

    @property
    def label(self) -> str:
        return f"{'ollama' if self.kind == 'ollama' else 'api'}:{self.model}"

    def _payload(self, messages, max_tokens, temperature, stream):
        if self.kind == "ollama":
            return f"{self.base_url}/api/chat", {"model": self.model, "messages": messages, "stream": stream,
                                                 "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192}}, {}
        return (f"{self.base_url}/chat/completions",
                {"model": self.model, "messages": messages, "stream": stream, "max_tokens": max_tokens, "temperature": temperature},
                {"Authorization": f"Bearer {self._key}"})

    def chat(self, messages: list[dict], max_tokens: int = 400, temperature: float = 0.2, timeout: float = 180) -> str:
        url, body, headers = self._payload(messages, max_tokens, temperature, False)
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if self.kind == "ollama":
            return d.get("message", {}).get("content", "")
        return d["choices"][0]["message"]["content"] or ""

    def stream(self, messages: list[dict], max_tokens: int = 400, temperature: float = 0.2, timeout: float = 180) -> Iterator[str]:
        url, body, headers = self._payload(messages, max_tokens, temperature, True)
        with httpx.stream("POST", url, json=body, headers=headers, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if self.kind == "ollama":
                    d = json.loads(line)
                    piece = d.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if d.get("done"):
                        break
                else:
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    d = json.loads(data)
                    piece = (d.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                    if piece:
                        yield piece


def get_llm(purpose: str = "chat") -> LLM | None:
    """purpose: 'chat' (fast, interactive) or 'narrate' (offline, can be slower/stronger)."""
    if os.environ.get("REPOCADEMY_LLM", "").lower() in ("off", "0", "none", "false"):
        return None
    base = os.environ.get("REPOCADEMY_LLM_BASE_URL")
    if base:
        return LLM("openai", os.environ.get("REPOCADEMY_LLM_MODEL", "llama-3.1-8b-instant"), base, os.environ.get("REPOCADEMY_LLM_API_KEY", ""))
    url = os.environ.get("REPOCADEMY_OLLAMA_URL", "http://127.0.0.1:11434")
    env_model = os.environ.get("REPOCADEMY_NARRATE_MODEL" if purpose == "narrate" else "REPOCADEMY_OLLAMA_MODEL") or os.environ.get("REPOCADEMY_OLLAMA_MODEL")
    try:
        tags = httpx.get(f"{url}/api/tags", timeout=1.5).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return None
    names = [t.get("name", "") for t in tags]
    if env_model:
        return LLM("ollama", env_model, url) if any(n == env_model or n.split(":")[0] == env_model for n in names) else None
    prefs = _PREFERRED_LOCAL
    for p in prefs:
        if p in names:
            return LLM("ollama", p, url)
    return None
