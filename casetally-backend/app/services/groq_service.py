import logging
import os
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a precise legal research assistant for CaseTally. Answer using ONLY the provided legal excerpts — never add outside knowledge.

Reply in this exact format every time:

**Short Answer**
1-2 sentences directly answering the question. If the excerpts lack sufficient information, state that clearly.

**Relevant Statutes**
- [Title] U.S.C. § [Section] — [one-line description of what it covers]

**Analysis**
3-4 sentences. Explain how each cited statute applies to the question. Reference section numbers inline (e.g. "Under 18 U.S.C. § 1343..."). Be specific — state what the law requires, prohibits, or permits.

**Key Statutory Language**
> [The single most relevant direct quote from the excerpts]

**Limitation**
This summarizes retrieved statutory text only and is not legal advice."""


def _build_context(results: List[Dict[str, Any]]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        # Use snippet (~100 tokens) not text_content (~500 tokens) to save tokens.
        # Full text is served separately to the frontend via /v1/search.
        text = r.get("snippet") or r.get("text_content", "")
        parts.append(f"[{i}] {r['citation']}\n{text}")
    return "\n\n---\n\n".join(parts)


class GroqService:
    def __init__(self):
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
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
            max_tokens=1024,
        )

        for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token

    def rewrite_query(self, query: str) -> str:
        """
        Rewrites a conversational question into precise legal search terms.
        Returns the rewritten string, or the original query if rewriting fails.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert the user's question into 3-6 precise legal search terms "
                        "suitable for searching U.S. statutes. Output only the search terms, "
                        "no punctuation, no explanation."
                    ),
                },
                {"role": "user", "content": query},
            ],
            stream=False,
            temperature=0.0,
            max_tokens=32,
        )
        rewritten = response.choices[0].message.content or ""
        return rewritten.strip() or query

    def is_available(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))
