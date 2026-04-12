import logging
import os
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI

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


class GroqService:
    def __init__(self):
        self.model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
        self.client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )

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

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            temperature=0.1,
            max_tokens=512,
        )

        for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token

    def is_available(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))
