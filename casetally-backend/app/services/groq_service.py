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
    # Upper bound on rewrite length, enforced in code as well as in the prompt.
    REWRITE_MAX_WORDS = 10

    # The rewrite exists to cross a vocabulary gap, not to make the question
    # sound more legal. Statutes are written in formal operative language, and a
    # user's words often appear nowhere in the corpus while the concept is
    # present under different wording. A rewrite that adds plausible-sounding
    # legal English without matching how statutes are actually written makes
    # retrieval worse, not better: it can inject terms with zero occurrences and
    # amplify a common word used in an unrelated sense.
    #
    # The examples below are drawn from areas outside the evaluation benchmark on
    # purpose. Examples from benchmark domains would tune the prompt to the test
    # and stop it measuring generalisation.
    REWRITE_SYSTEM_PROMPT = (
        "You turn a question into search terms for a database of U.S. statutes. "
        "The database contains the literal text of the statutes, so the terms must "
        "be words that appear in statutory language.\n"
        "\n"
        "Rules:\n"
        "1. Output 3 to 6 terms, at most 10 words in total.\n"
        "2. Use the formal operative wording a statute would use, not everyday "
        "wording and not practitioner shorthand.\n"
        "3. Prefer the words that create a duty, prohibition, right or penalty: "
        "the verbs and nouns the statute itself would use.\n"
        "4. Do not output doctrine or case-law names, or labels that describe a "
        "rule from the outside. Those appear in commentary, not in statutes.\n"
        "5. Output only the terms, separated by spaces. No punctuation, no "
        "explanation, no numbering.\n"
        "\n"
        "Examples of the shift from everyday to statutory wording:\n"
        "  will I get deported -> removal proceedings inadmissible alien\n"
        "  the bank hid fees from me -> finance charge disclosure creditor\n"
        "  hurt working on a ship -> seaman vessel injury liability\n"
        "  benefits for my army injury -> veteran service-connected disability compensation\n"
        "  school will not give me my records -> education records disclosure consent\n"
        "\n"
        "Note what each example avoids: 'deported', 'hid fees' and 'army' do not "
        "appear in the statutes that govern them."
    )

    def __init__(self):
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        # gpt-oss and qwen models on Groq emit reasoning tokens before their
        # answer. Without a low effort setting they exhaust short token budgets
        # thinking and return empty content. Set to "" to omit the parameter
        # for models that do not support it.
        self.reasoning_effort = os.getenv("GROQ_REASONING_EFFORT", "low")
        self.client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )

    def _extra(self) -> Dict[str, Any]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

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
            extra_body=self._extra(),
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
                {"role": "system", "content": self.REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            stream=False,
            temperature=0.0,
            # Budget covers reasoning tokens as well as the terms themselves, and
            # the terms are only ever a handful of words, so almost all of this is
            # reasoning headroom.
            #
            # 250 was enough for the previous one-sentence prompt. This prompt has
            # rules and examples, which makes the model reason longer, and at 250
            # it hit finish_reason=length with content='' on some queries: the
            # whole budget went to reasoning and nothing was emitted. The caller
            # then silently fell back to the unrewritten query, so the failure
            # looked like a rewrite that did nothing rather than one that never
            # finished. 512 leaves room; the empty case is logged below so a
            # recurrence is visible instead of silent.
            max_tokens=512,
            extra_body=self._extra(),
        )
        rewritten = response.choices[0].message.content or ""
        if not rewritten.strip():
            logger.warning(
                "rewrite produced no content (finish_reason=%s, completion_tokens=%s); "
                "falling back to the original query",
                response.choices[0].finish_reason,
                getattr(response.usage, "completion_tokens", "?"),
            )
        # Models may return one term per line; collapse to a single query string.
        rewritten = " ".join(rewritten.split())
        rewritten = rewritten.strip()
        if not rewritten:
            return query

        # Hard cap, because the prompt alone does not reliably hold the model to
        # a length. Asked for "3-6 terms" it has returned 16 words, and the
        # lexical branch requires every term to appear in one chunk, so a long
        # rewrite can make that branch match nothing at all and silently reduce
        # hybrid search to vector-only.
        words = rewritten.split()
        if len(words) > self.REWRITE_MAX_WORDS:
            logger.warning(
                "rewrite returned %d words, truncating to %d: %r",
                len(words), self.REWRITE_MAX_WORDS, rewritten,
            )
            rewritten = " ".join(words[: self.REWRITE_MAX_WORDS])
        return rewritten

    def is_available(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))
