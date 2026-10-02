import json
import logging
import os
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.dependencies import groq_service, search_service
from app.models import LegalArtifact
from app.services.groq_service import _terms
from app.services.search import normalize_citation

router = APIRouter(prefix="/v1", tags=["chat"])

logger = logging.getLogger(__name__)

# Retrieval depth, then how the answer's context is selected from it.
#
# CANDIDATE_K is deliberately wider than the answer needs. The per-citation cap
# below discards chunks, so there has to be a deeper pool to replace them from,
# otherwise capping just shortens the context.
CANDIDATE_K = 30

# Eight chunks rather than three. With issue spotting, the fused list holds the
# best chunk for each of several distinct legal issues, so a three-chunk window
# cannot hold even one chunk per issue plus any supporting text. Three was
# already marginal for a single-issue question; across four it guarantees that
# most issues reach the model as a single orphaned fragment or not at all.
ANSWER_TOP_K = 8

# At most two chunks from any one citation.
#
# Without this, one statute crowds out the rest: 42 U.S.C. § 2000e alone holds 38
# chunks under a single citation, and a query that matches it strongly can fill
# the entire context with subsections of one law while the other issues in the
# question go unrepresented. Two is enough for a provision plus its definition or
# exception, and cheap enough that six other slots remain.
MAX_CHUNKS_PER_CITATION = 2

# Slots filled from the fused ranking before issue balancing starts.
#
# Pure round-robin gives every issue a turn, which is what makes a multi-issue
# answer possible, but it ignores how good a chunk is overall. Measured on the
# tax question, the failure-to-file penalty sat at fused rank 12 and reached the
# model on two runs out of three: when the decomposition changed, the per-issue
# lists filled all eight slots between them and the strongest overall chunks
# never got one. Reserving the head of the fused list guarantees that the
# chunks the two branches most agree on are always present, whatever the
# decomposition happened to produce, and the overlap with what round-robin would
# have picked anyway lets the issue passes reach deeper into each list.
#
# Three of eight: enough to anchor the answer, few enough that five slots remain
# for issue coverage. The per-citation cap still applies to these.
FUSED_RESERVE = 3


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []


def _event(data: str) -> str:
    return f"data: {data}\n\n"


def _error_event(message: str, detail: str = "") -> str:
    """An explicit failure the client can show.

    Everything in this endpoint streams over a 200 response, so a failure after
    the headers are sent has no status code to carry it. Without an event of its
    own, a retrieval outage or an empty model response reached the browser as a
    valid stream containing no text: a blank answer, no error, and a spinner that
    never stopped. The client needs to be told, not left to infer silence.
    """
    return _event(json.dumps({"type": "error", "message": message, "detail": detail[:300]}))


# "17 U.S.C. § 504", "29 USC 623", "18 U.S.C. §922(g)" and so on.
_CITE_RE = re.compile(r"(\d+)\s*U\.?\s*S\.?\s*C\.?\s*§*\s*(\d+[A-Za-z]*(?:-\d+)?)")


def _cite_key(text: str) -> str:
    m = _CITE_RE.search(text)
    # The regex already stops before a trailing period, so the dotted and
    # undotted spellings of a citation produce the same key. normalize_citation
    # covers the fallback branch, where no section number was found and the whole
    # string is used.
    return f"{m.group(1)}:{m.group(2)}" if m else normalize_citation(text)


def _cap_allowance(
    results: Dict[str, Any],
    query: str,
    per_citation_cap: int,
) -> Dict[str, Any]:
    """Decide WHICH chunks a capped citation is allowed to spend its slots on.

    The cap used to be first-come: the two highest ranked chunks of a statute won
    its two slots. Rank answers "which part of this statute looks most like the
    query", which is not the same as "which part answers the question", and for a
    long statute split across many chunks it is routinely the wrong part.
    Measured on FERPA: 20 U.S.C. 1232g has nine chunks, the consent rule lives in
    chunks 18247-18251, and the two that ranked highest were 18245 and 18246,
    which do not contain it. The model was asked whether a school may release
    grades without permission while being shown the parts of FERPA about
    inspecting and challenging records, and it correctly said the rule was not
    there.

    So score each chunk of a citation by how much of the question it actually
    covers, and let the best ones hold the slots however they ranked. Scoring
    counts DISTINCT question terms present, so a chunk repeating one word does
    not beat a chunk addressing several parts of the question. Ties keep retrieval
    order, which is deterministic now, so the result is stable.
    """
    terms = _terms(query, *(results.get("sub_queries") or []))
    if not terms or per_citation_cap <= 0:
        return {}

    # Everything that could be selected: the fused list plus every per-issue list.
    pool: List[Dict[str, Any]] = list(results.get("results") or [])
    for rows in (results.get("by_issue") or {}).values():
        pool.extend(rows)

    # Deduplicate the pool first, then weight terms by how rare they are in it.
    #
    # Counting matched terms equally does not work: it rewards a chunk carrying
    # several common words over the one chunk carrying the single decisive word.
    # Measured on the pregnancy question, plain counting moved Title VII from the
    # chunk defining "because of sex" to include pregnancy and childbirth to a
    # chunk that merely said "employment", "termination" and "employer" more
    # often, which is the opposite of what was wanted. A term that appears in
    # almost every candidate chunk cannot discriminate between them; a term that
    # appears in two of forty is the whole signal.
    texts: Dict[int, str] = {}
    order_of: Dict[int, int] = {}
    cite_of: Dict[int, str] = {}
    for order, row in enumerate(pool):
        cid = row.get("chunk_id")
        if cid is None or cid in texts:
            continue
        texts[cid] = (row.get("text_content") or row.get("snippet") or "").lower()
        order_of[cid] = order
        cite_of[cid] = normalize_citation(row["citation"])

    if not texts:
        return {}

    weight: Dict[str, float] = {}
    for t in terms:
        df = sum(1 for txt in texts.values() if t in txt)
        weight[t] = 1.0 / (1.0 + df) if df else 0.0

    by_citation: Dict[str, Dict[int, tuple]] = {}
    for cid, txt in texts.items():
        score = sum(w for t, w in weight.items() if w and t in txt)
        # Negative score so a plain sort puts the best first; order breaks ties.
        by_citation.setdefault(cite_of[cid], {})[cid] = (-score, order_of[cid])

    # Per citation, the chunk ids in best-match order. Restricting which chunks
    # MAY be used is not enough on its own: the caller offers chunks in retrieval
    # order, so a statute's slot is spent on whichever of its chunks happens to be
    # offered first. Measured on the pregnancy question, the best chunk was
    # allowed but the per-issue list offered a weaker one first, the slot went to
    # that, and the eight slots filled before the good chunk came up. Handing back
    # an ordering lets the caller spend the slot on the best chunk instead of the
    # first one.
    ranked: Dict[str, List[int]] = {}
    rows_by_id: Dict[int, Dict[str, Any]] = {}
    for order, row in enumerate(pool):
        cid = row.get("chunk_id")
        if cid is not None and cid not in rows_by_id:
            rows_by_id[cid] = row
    for cit, chunks in by_citation.items():
        ranked[cit] = sorted(chunks, key=lambda c: chunks[c])
    return {"ranked": ranked, "rows": rows_by_id}


def _select_context(
    results: Dict[str, Any],
    limit: int,
    per_citation_cap: int,
    reserve_fused: int = FUSED_RESERVE,
    query: str = "",
) -> List[Dict[str, Any]]:
    """Choose the chunks the model will see, giving every issue a fair share.

    Taking the head of the fused list looks right and is not: fusion answers "what
    is most relevant overall", so it can legitimately rank every chunk of one issue
    above the best chunk of another. When "can I get fired for joining a union" was
    decomposed into two discrimination queries and one union query, discrimination
    chunks accumulated two RRF contributions each and filled all eight slots, and
    the NLRA never reached the model at all.

    So fill round-robin across issues instead: one chunk per issue per pass, best
    first within each issue. Every issue is represented before any issue gets a
    second chunk, which is what makes a multi-issue answer possible. The
    per-citation cap still applies, so one statute cannot take the whole context
    even inside its own issue.

    Falls back to the fused order when there are no per-issue lists, which is the
    single-query path.

    The first `reserve_fused` slots come from the fused ranking regardless of
    issue, so a chunk both branches rank highly cannot be displaced by issue
    balancing alone. See FUSED_RESERVE.
    """
    by_issue: Dict[str, List[Dict[str, Any]]] = results.get("by_issue") or {}
    per_citation: Dict[str, int] = {}
    chosen: List[Dict[str, Any]] = []
    seen_chunks: set = set()
    allowance = _cap_allowance(results, query, per_citation_cap)
    ranked: Dict[str, List[int]] = allowance.get("ranked") or {}
    rows_by_id: Dict[int, Dict[str, Any]] = allowance.get("rows") or {}

    def take(row: Dict[str, Any]) -> bool:
        cid = row.get("chunk_id")
        if cid in seen_chunks:
            return False
        # Normalised, so the dotted and undotted spellings of one statute share a
        # single budget instead of getting two chunks each.
        cit = normalize_citation(row["citation"])
        if per_citation.get(cit, 0) >= per_citation_cap:
            return False
        # Spend this citation's slot on the chunk that best covers the question
        # rather than whichever of its chunks was offered first. See
        # _cap_allowance.
        order = ranked.get(cit)
        if order:
            pick = next((c for c in order if c not in seen_chunks), None)
            if pick is None:
                return False
            if pick != cid:
                row = rows_by_id.get(pick, row)
                cid = pick
        per_citation[cit] = per_citation.get(cit, 0) + 1
        seen_chunks.add(cid)
        chosen.append(row)
        return True

    # Anchor on the strongest overall results before balancing by issue.
    if by_issue and reserve_fused > 0:
        for row in results.get("results", []):
            if len(chosen) >= min(reserve_fused, limit):
                break
            take(row)

    if by_issue:
        cursors = {k: 0 for k in by_issue}
        # Loop until a whole pass adds nothing, which means every list is either
        # exhausted or entirely blocked by the citation cap.
        while len(chosen) < limit:
            progressed = False
            for issue, rows in by_issue.items():
                if len(chosen) >= limit:
                    break
                i = cursors[issue]
                while i < len(rows):
                    row = rows[i]
                    i += 1
                    if take(row):
                        progressed = True
                        break
                cursors[issue] = i
            if not progressed:
                break

    # Top up from the fused list if round-robin came up short, or fill it entirely
    # on the single-query path.
    for row in results.get("results", []):
        if len(chosen) >= limit:
            break
        take(row)

    return chosen


def _stream(query: str, history: List[Dict[str, Any]]):
    db = SessionLocal()
    try:
        # Split the question into one sub-query per legal issue, then retrieve for
        # each and fuse.
        #
        # A single rewrite has to cover every issue a question raises with one
        # ranking. "Can my boss fire me" spans discrimination, union activity and
        # medical leave, each in a different statute in a different title, and the
        # terms that surface one push the others down. Issue spotting first is what
        # a lawyer does before searching.
        #
        # Every failure path falls back to the single-query behaviour rather than
        # breaking: no Groq, an unparseable response, or an empty list.
        decomposed: List[Dict[str, str]] = []
        if groq_service.is_available():
            try:
                decomposed = groq_service.decompose_query(query)
                if decomposed:
                    logger.info("query decomposed: %r -> %r", query, decomposed)
                else:
                    logger.warning("decompose returned nothing, falling back to single rewrite")
            except Exception as exc:
                logger.warning("decompose failed, falling back to single rewrite: %s", exc)

        try:
            if decomposed:
                results = search_service.search_multi(
                    session_factory=SessionLocal,
                    queries=[d["query"] for d in decomposed],
                    labels=[d["issue"] for d in decomposed],
                    top_k=CANDIDATE_K,
                    bm25_k=50,
                    vector_k=50,
                    weight_bm25=0.5,
                    weight_vector=0.5,
                )
            else:
                search_query = query
                if groq_service.is_available():
                    try:
                        rewritten = groq_service.rewrite_query(query)
                        if rewritten and rewritten != query:
                            logger.info("query rewritten: %r -> %r", query, rewritten)
                            search_query = rewritten
                    except Exception as exc:
                        logger.warning("query rewriting failed, using original: %s", exc)
                results = search_service.search(
                    db=db,
                    query=search_query,
                    top_k=CANDIDATE_K,
                    bm25_k=50,
                    vector_k=50,
                    weight_bm25=0.5,
                    weight_vector=0.5,
                )
        except Exception as exc:
            logger.exception("retrieval failed for %r", query)
            yield _error_event(
                "Search is temporarily unavailable, so no statutes could be "
                "retrieved. Please try again in a moment.",
                f"{type(exc).__name__}: {exc}",
            )
            yield _event("[DONE]")
            return

        # search_multi catches per-sub-query failures so one bad sub-query cannot
        # lose the others. When every one of them failed the list is empty for a
        # reason that has nothing to do with the question, and saying "nothing
        # matched" would be a lie.
        errors = results.get("errors") or []
        n_queries = results.get("n_queries") or 0
        if errors and n_queries and len(errors) >= n_queries:
            logger.error("all %d sub-queries failed for %r: %s", n_queries, query, errors[:3])
            yield _error_event(
                "Search is temporarily unavailable, so no statutes could be "
                "retrieved. Please try again in a moment.",
                "; ".join(errors[:2]),
            )
            yield _event("[DONE]")
            return

        # One retrieval, used for both the answer and the sources panel.
        #
        # The panel used to call /v1/search separately with the RAW question while
        # this endpoint searched the REWRITTEN one, at a different depth. Two
        # independent retrievals over two different query strings, so the panel
        # could display the correct statute while the answer, reasoning over a
        # different set, said it had no relevant information. That is not a
        # ranking bug, it is two answers to two different questions presented as
        # one result.
        #
        # Select the answer's context from the candidate pool, then show exactly
        # that. The panel and the answer are the same list, so the panel can never
        # display a statute the answer did not see, which is the inconsistency this
        # endpoint used to have.
        chunks = _select_context(
            results, ANSWER_TOP_K, MAX_CHUNKS_PER_CITATION, query=query
        )
        sources = chunks

        # Emitted before the answer so the panel fills while tokens are still
        # streaming, and so it is populated even if the LLM call fails.
        yield _event(json.dumps({
            "type": "sources",
            "results": sources,
            "took_ms": results.get("took_ms"),
            "query": results.get("query"),
            "sub_queries": results.get("sub_queries", []),
            "embedding_used": results.get("embedding_used"),
        }))

        # Retrieval worked and genuinely matched nothing. Distinct from the
        # outage above, and it still has to be said out loud rather than
        # producing an empty answer.
        if not chunks:
            logger.info("no chunks retrieved for %r", query)
            yield _error_event(
                "No statutes in this corpus matched that question. This corpus "
                "holds federal statutes only, so questions governed by state law "
                "will not be found here."
            )
            yield _event("[DONE]")
            return

        # Accumulate the answer while streaming it, so the citation check can run
        # at the end without delaying a single token. Each chunk is still yielded
        # the moment it arrives; only the check waits.
        answer_parts: List[str] = []

        if groq_service.is_available():
            stream_failed = False
            try:
                for token in groq_service.stream_answer(
                    query, chunks, history, sub_queries=results.get("sub_queries"),
                ):
                    answer_parts.append(token)
                    yield _event(json.dumps({"type": "text", "chunk": token}))
            except Exception as exc:
                stream_failed = True
                logger.warning("Groq stream failed: %s", exc, exc_info=True)
                yield _error_event(
                    "The AI assistant is temporarily unavailable, so the answer "
                    "could not be written. The statutes found for your question "
                    "are listed below.",
                    f"{type(exc).__name__}: {exc}",
                )
            # A stream can finish successfully having emitted nothing at all,
            # usually because the reasoning budget consumed max_tokens. That is
            # not an exception, so it has to be checked for explicitly. Only
            # reported when the stream did not already fail, so one failure does
            # not produce two error events.
            if not stream_failed and not "".join(answer_parts).strip():
                logger.error("empty answer for %r (chunks=%d)", query, len(chunks))
                yield _error_event(
                    "The AI assistant returned an empty answer. Please try again. "
                    "The statutes found for your question are listed below."
                )
        else:
            for result in chunks:
                text = f"{result['citation']}: {result['snippet']}"
                answer_parts.append(text)
                yield _event(json.dumps({"type": "text", "chunk": text}))

        # Citation guard.
        #
        # The prompt forbids citing a section that was not supplied, and a prompt is
        # not an enforcement mechanism. A model that writes "26 U.S.C. § 7203" from
        # memory produces something the reader cannot distinguish from a retrieved
        # citation, which is the most damaging failure this system has: a fabricated
        # citation that looks authoritative. So verify rather than trust.
        #
        # Verification is by section identity, not string equality, because the
        # answer legitimately writes subsections ("§ 2000e-2(a)") that the corpus
        # stores under a parent citation ("42 U.S.C. § 2000e").
        supplied = {_cite_key(c["citation"]) for c in chunks}
        answer_text = "".join(answer_parts)
        cited_keys = []
        for t, s in _CITE_RE.findall(answer_text):
            key = f"{t}:{s}"
            if key not in cited_keys:
                cited_keys.append(key)
        unverified = [k for k in cited_keys if k not in supplied]

        if unverified:
            logger.warning(
                "citation guard: answer cited %s which were NOT supplied (supplied=%s) for query %r",
                unverified, sorted(supplied), query,
            )
        yield _event(json.dumps({
            "type": "citation_check",
            "supplied": sorted(supplied),
            "cited": cited_keys,
            "unverified": unverified,
        }))

        for result in chunks:
            if result.get("artifact"):
                artifact = result["artifact"]
                yield _event(json.dumps({
                    "type": "artifact",
                    "id": str(artifact["artifact_id"]),
                    "title": result["citation"],
                    "url": f"/v1/artifacts/{artifact['artifact_id']}/file",
                }))

        yield _event("[DONE]")
    finally:
        db.close()


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    return StreamingResponse(
        _stream(payload.message, payload.history),
        media_type="text/event-stream",
    )


@router.get("/artifacts/{artifact_id}/file")
def get_artifact_file(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.query(LegalArtifact).filter(LegalArtifact.id == artifact_id).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = artifact.artifact_metadata.get("file_path", "")
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=500, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )
