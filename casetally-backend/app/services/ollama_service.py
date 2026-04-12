import json
import logging
import os
from typing import Any, Dict, Generator, List, Optional

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a precise legal research assistant for CaseTally.
Answer the user's question using ONLY the legal text excerpts provided below.
Always cite the specific statute or section (e.g. "Under 42 U.S.C. § 1983...").
If the excerpts do not contain enough information to answer, say so clearly.
Do not speculate or add information not present in the excerpts."""


def _build_context(results: List[Dict[str, Any]]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"[{i}] {r['citation']}\n{r['text_content']}")
    return "\n\n---\n\n".join(parts)


class OllamaService:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_URL", "http://casetally-ollama:11434")
        self.model = os.getenv("OLLAMA_MODEL", "phi3.5")

    def stream_answer(
        self,
        query: str,
        search_results: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Generator[str, None, None]:
        context = _build_context(search_results)

        messages = [
            {
                "role": "system",
                "content": f"{_SYSTEM_PROMPT}\n\n## Legal Excerpts\n\n{context}",
            }
        ]

        for turn in (history or []):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": query})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }

        with httpx.Client(timeout=120.0) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token

                    if data.get("done"):
                        break

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            if r.status_code != 200:
                return False
            models = [m["name"] for m in r.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False
