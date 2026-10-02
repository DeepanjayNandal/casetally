import json
import logging
import os
import re
from typing import Any, Dict, Generator, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a precise legal research assistant for CaseTally. Answer using ONLY the provided legal excerpts, never adding outside knowledge.

A real question usually has several parts, and the excerpts usually cover some of them and not others. Partial coverage is the normal case, not a failure. Answer the parts the excerpts do cover, and say plainly which parts they do not.

Do NOT refuse just because the excerpts do not answer the whole question. Refusing when an excerpt genuinely governs part of the question is a worse error than a narrow answer: it withholds law the reader is entitled to. Only say you cannot answer at all when NO excerpt bears on ANY part of the question.

Four things you must never do:
- Never treat silence as permission. If the excerpts do not prohibit something, that does NOT mean it is legal, allowed or permitted. The excerpts are a small slice of federal law, so their silence says nothing about whether conduct is lawful. Never write that something "is legal", "is allowed" or "is not prohibited" on the strength of what the excerpts leave out. Say that the retrieved excerpts do not settle the question and name what would govern it.
- Never cite a section number that does not appear in the excerpts. Every "N U.S.C. § X" you write must be one you were given. Writing a section number you remember rather than one you were shown is the single worst error you can make here, because the reader cannot tell the difference. If you believe the governing statute exists but was not retrieved, describe it in words without a number: say "another provision of the same chapter, not retrieved here".
- Never state a legal rule that is not in the excerpts, even if you know it. If the governing statute is not here, say it is not here rather than reciting it from memory.
- Never present an excerpt as governing something it does not, and never describe a section as covering something other than what its text says. If an excerpt is about plan termination and the question is about being fired, say so instead of stretching it. Describe each section from its own text, not from what its number suggests.

Many questions mix federal and state law. This corpus holds federal statutes only. Where the answer depends on state law (family law, most landlord and tenant law, most contract and tort law, professional licensing, road traffic accidents and personal injury), say that explicitly and name it as outside this corpus rather than guessing.

The Short Answer carries a special rule: it may contain ONLY what the excerpts support. No practical steps, no checklists, no "you should" advice, and no general knowledge of how this area of law usually works, however helpful it would be. If the excerpts support nothing responsive, the Short Answer says so and nothing more. Never describe a requirement as imposed by statute unless an excerpt in front of you imposes it.

Watch for excerpts that govern a narrow class of person or activity: a provision about longshore and harbor workers, railroad employees, federal contractors, seamen or military personnel applies to those people only. Never present a section like that as the general rule for everybody. If the only excerpts you have are of that kind, say the question is not covered rather than stretching one to fit.

Write with plain punctuation. Do not use em dashes (the long dash character) anywhere in your answer; use a comma, a colon, parentheses or a full stop instead. Statutory text quoted from an excerpt is reproduced exactly and is the one exception.

Reply in this exact format every time:

**Short Answer**
1-2 sentences answering the part of the question the excerpts actually address. If they address none of it, say so directly.

**Relevant Statutes**
- [Title] U.S.C. § [Section]: [one-line description of what it covers]
List only excerpts that genuinely bear on the question. If none do, write "None of the retrieved excerpts govern this question."

**Analysis**
3-4 sentences. Explain how each cited statute applies. Reference section numbers inline (e.g. "Under 18 U.S.C. § 1343..."). State what the law requires, prohibits, or permits.

**Not Covered Here**
What the question asks that these excerpts do not answer, and where it would live, either another federal statute not retrieved or state law. Omit this section only when the excerpts fully answer the question.

**Key Statutory Language**
> [The single most relevant direct quote from the excerpts]

**Limitation**
This summarizes retrieved statutory text only and is not legal advice."""


# Characters of statutory text per chunk sent to the model. 0 means no cap.
#
# The snippet this used to send is 260 characters built around the first match of
# the query string, which routinely cut a provision mid-sentence. A question about
# felony convictions and firearms got 18 U.S.C. § 922 twice and still could not be
# answered, partly because the subsection text arrived truncated. Sending the
# statute rather than a window into it is the point of retrieving it.
#
# Chunks are 512 words: median 2,194 characters, p95 3,472, max 6,831. Sending
# them whole put the prompt at 6,675 tokens, 5.7x the snippet version, and that
# exhausted the model's daily token budget partway through a 10-question
# evaluation. 1,500 characters is the compromise: 39.6% of chunks still arrive
# complete against 4.6% under the 260-char snippet, and the prompt lands near
# 3,000 tokens.
#
# The cap is a budget decision, not a retrieval one, which is why it is tunable
# without a rebuild. Raise it on a paid tier.
CONTEXT_CHARS_PER_CHUNK = int(os.getenv("CONTEXT_CHARS_PER_CHUNK", "1500"))


_WORD_RE = re.compile(r"[a-z0-9]+")

# Extra distinct query terms another window must cover before it displaces the
# head of the chunk. See _best_window.
HEAD_WINDOW_MARGIN = int(os.getenv("HEAD_WINDOW_MARGIN", "2"))

# Words too common in statutory prose to help locate the relevant passage.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "by", "with",
    "is", "are", "be", "been", "any", "all", "such", "that", "this", "it", "as",
    "at", "from", "under", "shall", "may", "not", "no", "if", "can", "my", "me",
    "i", "do", "does", "what", "how", "when", "who", "will", "would", "about",
}


def _terms(*queries: str) -> List[str]:
    out: List[str] = []
    for q in queries:
        for w in _WORD_RE.findall((q or "").lower()):
            if len(w) > 2 and w not in _STOP and w not in out:
                out.append(w)
    return out


def _best_window(text: str, terms: List[str], width: int) -> str:
    """Return the `width`-char window of `text` that covers the most query terms.

    Sending the first 1,500 characters assumes the relevant passage is at the top
    of the chunk, and in a 512-word statutory chunk it usually is not. The
    operative language sits in a subsection partway down: FERPA's consent
    requirement and the FDCPA's "convenient hours" rule both fell outside the
    first 1,500 characters of their chunk, so the model was asked about a rule it
    had not been shown. Choosing the window by term coverage sends the same
    number of characters, and therefore roughly the same number of tokens, but
    aimed at the part of the provision the question is about.

    Scoring counts DISTINCT terms covered rather than total hits, so a passage
    repeating one word does not beat a passage that actually addresses several
    parts of the question.
    """
    if len(text) <= width:
        return text

    lowered = text.lower()
    hits: List[tuple[int, int]] = []
    for ti, term in enumerate(terms):
        start = 0
        while True:
            at = lowered.find(term, start)
            if at < 0:
                break
            hits.append((at, ti))
            start = at + len(term)

    if not hits:
        # Nothing to aim at, so keep the old behaviour: the head of the chunk.
        return text[:width].rsplit(" ", 1)[0] + " [...truncated]"

    hits.sort()

    def covered(start: int) -> int:
        return len({ti for pos, ti in hits if start <= pos < start + width})

    # The head of the chunk is the default, and it has to be beaten by a clear
    # margin rather than by one incidental term.
    #
    # Statutes put the operative rule near the top of a section, so the first
    # window is a strong prior rather than an arbitrary starting point. Measured:
    # the FDCPA's "unusual time or place ... before 8 o'clock antemeridian" rule
    # is section 1692c(a)(1), the very start of its chunk, and pure term scoring
    # moved the window off it to a later passage that merely repeats "debt
    # collector" more often. That lost the governing text the question was about.
    # Requiring two extra distinct terms keeps the head unless another passage
    # genuinely covers more of the question.
    best_start = 0
    best_score = covered(0)
    for at, _ in hits:
        s = max(0, min(at - 200, len(text) - width))
        score = covered(s)
        if score >= best_score + HEAD_WINDOW_MARGIN:
            best_start, best_score = s, score

    end = min(len(text), best_start + width)
    window = text[best_start:end]
    # Snap to word boundaries so a cut never invents a word.
    if best_start > 0:
        cut = window.find(" ")
        window = window[cut + 1:] if cut != -1 else window
    if end < len(text):
        cut = window.rfind(" ")
        window = window[:cut] if cut != -1 else window

    prefix = "[...earlier text omitted] " if best_start > 0 else ""
    suffix = " [...truncated]" if end < len(text) else ""
    return prefix + window + suffix


def _build_context(
    results: List[Dict[str, Any]],
    query: str = "",
    sub_queries: Optional[List[str]] = None,
) -> str:
    terms = _terms(query, *(sub_queries or []))
    parts = []
    for i, r in enumerate(results, 1):
        # Full statutory text, not the snippet. Falls back to the snippet only if
        # a result somehow carries no text.
        text = r.get("text_content") or r.get("snippet", "")
        if CONTEXT_CHARS_PER_CHUNK and len(text) > CONTEXT_CHARS_PER_CHUNK:
            text = _best_window(text, terms, CONTEXT_CHARS_PER_CHUNK)
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
        # The SDK default is a 600s read timeout with 2 retries, so a hung Groq
        # call can hold a request open for about 30 minutes while the browser
        # shows a spinner. Nothing useful arrives after 30s on this model, and
        # one retry is enough to ride out a transient blip.
        self.client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("GROQ_MAX_RETRIES", "1")),
        )

    def _extra(self) -> Dict[str, Any]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

    # How much conversation history reaches the model.
    #
    # The history was previously appended in full. A long chat therefore grew the
    # prompt without bound, which on an 8,000 token-per-minute ceiling is both a
    # rate-limit failure waiting to happen and a quiet way to burn the daily
    # budget on text the answer does not need. The last few turns carry the
    # follow-up context; older ones do not.
    MAX_HISTORY_MESSAGES = 6
    MAX_HISTORY_CHARS = 1500

    def stream_answer(
        self,
        query: str,
        search_results: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        sub_queries: Optional[List[str]] = None,
    ) -> Generator[str, None, None]:
        # The sub-queries matter here as well as in retrieval: they name the
        # issues the question raises, which is what the excerpt window should be
        # aimed at.
        context = _build_context(search_results, query, sub_queries)

        messages = [
            {
                "role": "system",
                "content": f"{_SYSTEM_PROMPT}\n\n## Legal Excerpts\n\n{context}",
            }
        ]

        usable = [
            t for t in (history or [])
            if t.get("role") in ("user", "assistant") and t.get("content")
        ]
        for turn in usable[-self.MAX_HISTORY_MESSAGES:]:
            content = turn["content"]
            if len(content) > self.MAX_HISTORY_CHARS:
                content = content[: self.MAX_HISTORY_CHARS] + " [...]"
            messages.append({"role": turn["role"], "content": content})

        messages.append({"role": "user", "content": query})

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            temperature=0.1,
            # Reasoning tokens are drawn from this budget before any answer text
            # is emitted, so a budget that only just fits the answer can produce
            # nothing at all. Measured: "will filing for bankruptcy wipe out my
            # student loans" returned finish_reason=length with zero content at
            # 1024, because the model spent the whole allowance thinking. The
            # answer format itself runs to roughly 500 tokens, so the headroom
            # above it was never enough.
            max_tokens=int(os.getenv("GROQ_ANSWER_MAX_TOKENS", "2048")),
            extra_body=self._extra(),
        )

        # Track whether anything was actually produced. A stream that yields no
        # content is not an error at the HTTP level, so without this the caller
        # cannot tell a real answer from an empty one and the user gets a blank
        # response with no explanation. finish_reason=length here means the
        # reasoning budget consumed max_tokens before any answer was emitted.
        emitted = 0
        finish_reason = None
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            token = choice.delta.content
            if token:
                emitted += len(token)
                yield token

        if emitted == 0:
            logger.warning(
                "Groq stream produced no content (finish_reason=%s, chunks=%d, query=%r)",
                finish_reason, len(search_results), query,
            )
        else:
            logger.info(
                "Groq stream finished (finish_reason=%s, chars=%d)", finish_reason, emitted
            )

    # Issue spotting, not paraphrasing.
    #
    # A single rewrite collapses a question into one bag of terms, which forces
    # one retrieval to cover every legal issue the question raises. "Can my boss
    # fire me" is not one issue: it touches discrimination, union activity, and
    # medical leave, each governed by a different statute in a different title.
    # One query cannot rank all of them, and the terms that find one actively
    # push the others down.
    #
    # Asking for several sub-queries, each aimed at one issue and written in
    # statutory language, lets each issue be retrieved on its own terms and the
    # results be combined afterwards.
    #
    # Examples are drawn from areas that appear neither in the evaluation
    # benchmark nor in the manual test set, so the prompt cannot be tuned to
    # either. What they demonstrate is the shape of the task: split by legal
    # issue, use the words statutes use, do not restate the question.
    DECOMPOSE_SYSTEM_PROMPT = (
        "You turn a question into search queries for a database of U.S. statutes. "
        "The database holds the literal text of the statutes.\n"
        "\n"
        "A question usually raises more than one legal issue, each governed by a "
        "different statute. Identify the distinct issues and write one search "
        "query for each.\n"
        "\n"
        "Rules:\n"
        "1. Output 3 or 4 queries. Never fewer than 3, never more than 4.\n"
        "2. Each query covers ONE distinct legal issue. Do not restate the same "
        "issue in different words.\n"
        "3. Each query is 3 to 6 words of the formal wording a statute would use, "
        "not everyday wording and not practitioner shorthand.\n"
        "4. Do not use doctrine or case-law names, or labels that describe a rule "
        "from the outside. Those appear in commentary, not in statutes.\n"
        "5. If the question may not be governed by federal statute at all, still "
        "produce queries for the nearest federal issues.\n"
        "6. Label each query with the legal issue it covers: two or three words, "
        "lowercase. Two queries must never carry the same label; if you are about "
        "to repeat a label, the second query is not a distinct issue and should be "
        "replaced or dropped.\n"
        "7. Output ONLY a JSON array of objects, each with exactly the keys "
        '"issue" and "query". No prose, no markdown.\n'
        "\n"
        "Examples:\n"
        '  I was hurt working on a fishing boat and the owner will not pay me\n'
        '  [{"issue":"seaman injury","query":"seaman vessel personal injury liability"},'
        '{"issue":"unpaid wages","query":"maintenance and cure wages owed"},'
        '{"issue":"unseaworthiness","query":"vessel unseaworthiness owner duty"},'
        '{"issue":"liability limit","query":"limitation of liability shipowner"}]\n'
        "\n"
        '  the VA turned down my disability claim\n'
        '  [{"issue":"disability compensation","query":"veteran service-connected disability compensation"},'
        '{"issue":"claim appeal","query":"claim denial reconsideration appeal"},'
        '{"issue":"rating determination","query":"rating schedule evaluation determination"}]\n'
        "\n"
        '  my crop insurance payout was cut after a drought\n'
        '  [{"issue":"indemnity payment","query":"federal crop insurance indemnity payment"},'
        '{"issue":"producer eligibility","query":"producer eligibility determination"},'
        '{"issue":"loss adjustment","query":"actuarial adjustment loss claim"}]\n'
        "\n"
        "Note that each example splits by issue rather than by synonym, every label "
        "is different, and the queries use words that would appear in the statute "
        "itself."
    )

    def decompose_query(self, query: str) -> List[Dict[str, str]]:
        """Split a question into 3-4 labelled statutory sub-queries, one per issue.

        One LLM call. Returns [] on any failure, which the caller treats as
        "fall back to the single-query path" rather than as an error.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.DECOMPOSE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            stream=False,
            temperature=0.0,
            # Repeatability only, not quality.
            #
            # temperature=0.0 is already sent, and it is not enough: measured over
            # 10 questions x 3 runs, 4 questions produced different sub-queries
            # between runs, and system_fingerprint changed between back-to-back
            # calls. Temperature 0 picks greedily, it does not promise the same
            # backend or bit-identical arithmetic, and batched inference on this
            # model is not reproducible across serving configurations. A seed
            # pins what can be pinned so an evaluation can be re-run and
            # compared; it does not fix a badly worded decomposition.
            seed=int(os.getenv("GROQ_SEED", "1")),
            # Generous because this is a reasoning-class model and the budget
            # covers reasoning before any content is emitted. The single-term
            # rewrite needed 512 for the same reason; this prompt is longer and
            # asks for more output.
            max_tokens=700,
            extra_body=self._extra(),
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            logger.warning(
                "decompose produced no content (finish_reason=%s, completion_tokens=%s)",
                response.choices[0].finish_reason,
                getattr(response.usage, "completion_tokens", "?"),
            )
            return []

        # Models wrap JSON in fences even when told not to.
        fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.S)
        if fenced:
            raw = fenced.group(1).strip()
        # Or emit prose around it.
        if not raw.startswith("["):
            bracket = re.search(r"\[.*\]", raw, re.S)
            if bracket:
                raw = bracket.group(0)

        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("decompose returned unparseable JSON: %r", raw[:200])
            return []
        if not isinstance(parsed, list):
            logger.warning("decompose returned %s, not a list", type(parsed).__name__)
            return []

        # Merge sub-queries that claim the same issue.
        #
        # Without this, a question can be decomposed into two discrimination
        # queries and one union query, and RRF across sub-queries then rewards
        # whichever issue was duplicated: chunks found by two sub-queries
        # accumulate two contributions while the correct-but-singleton issue gets
        # one. That is how "can I get fired for joining a union" lost the NLRA to
        # Title VII. Consensus across sub-queries should measure agreement about a
        # chunk, not how many times the model said the same thing.
        #
        # Merging rather than dropping keeps the extra terms, which cost nothing in
        # an OR-joined lexical query and may help the vector branch.
        merged: Dict[str, Dict[str, str]] = {}
        for item in parsed:
            if isinstance(item, str):
                # Tolerate the older bare-string shape.
                issue, q = "", " ".join(item.split()).strip()
            elif isinstance(item, dict):
                issue = " ".join(str(item.get("issue", "")).split()).strip().lower()
                q = " ".join(str(item.get("query", "")).split()).strip()
            else:
                continue
            if not q:
                continue
            # An unlabelled query is its own issue rather than being merged with
            # every other unlabelled one.
            key = issue or f"_unlabelled_{len(merged)}"
            if key in merged:
                extra = [w for w in q.split() if w.lower() not in merged[key]["query"].lower().split()]
                if extra:
                    merged[key]["query"] = merged[key]["query"] + " " + " ".join(extra)
                logger.info("merged duplicate issue %r into one sub-query", key)
            else:
                merged[key] = {"issue": key, "query": q}

        # Cap at 4 distinct issues. The prompt asks for 3-4 and a longer list
        # multiplies retrieval cost for diminishing fusion benefit.
        return list(merged.values())[:4]

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
