import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.common_lexemes import COMMON_LEXEME_PCT

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - allows startup without model package issues
    SentenceTransformer = None  # type: ignore

logger = logging.getLogger(__name__)

# Reciprocal rank fusion damping constant. See HybridSearchService.search.
#
# 60 is the value from the original RRF paper and was the starting point, but it
# was measured and 20 does better here. k is large relative to a 50-row candidate
# pool, and at 60 it flattens the score range almost out of existence: rank 1
# scores 1/61 and rank 50 scores 1/110, under a 2x spread across the whole pool,
# so near-ties decide the order. Measured on fixed query strings, dropping to 20
# moved Title VII from fused rank 6 to 4 on the headline employment query and left
# the other probes equal or better, and on the deterministic no-rewrite benchmark
# core P@3 went from 0.69 to 0.76 with R@5 and MRR unchanged.
#
# The paper's 60 was chosen for fusing much longer result lists; with 50 per
# branch a smaller constant is the right scale. Env-overridable so it can be swept
# against the eval harness without a rebuild.
RRF_K = int(os.getenv("RRF_K", "20"))

# A lexeme appearing in at least this percentage of chunks is dropped from the
# OR-joined lexical query. See _fetch_bm25, and common_lexemes.py for the
# frequencies.
#
# 50 rather than 10, on measurement. At 10% this cut the lexical branch's median
# from 171ms to 20ms and then failed the quality gate: core P@3 fell 0.78 to
# 0.69, R@5 0.83 to 0.78, MRR 0.85 to 0.75. The reason is that "common in the
# corpus" is not "unimportant to the query". "amend" is in 34% of chunks because
# almost every section carries amendment notes, and it is also the whole point of
# "freedom of speech First Amendment": dropping it left 0% of the original top 50
# in place. Ranking with the full term set while narrowing only the WHERE clause
# was better but still only recovered 70% of the original results.
#
# It also never addressed p95. The slowest queries have no common term to drop at
# all: "income tax deduction business expense" is 232ms before and after, because
# every one of its terms is below the threshold and their union is simply large.
#
# At 50% only the terms that carry no selectivity anywhere go: shall, section,
# may, state, title, note, provided, related and a handful of bare numbers and
# letters. That is quality-neutral and costs nothing to keep. The real wins came
# from the vector index and from caching; see _fetch_vector and the Postgres
# settings.
LEXICAL_DF_MAX_PCT = float(os.getenv("LEXICAL_DF_MAX_PCT", "50.0"))

# HNSW search breadth. Must be at least as large as the number of rows the vector
# branch requests, or pgvector returns fewer. See _fetch_vector.
HNSW_EF_SEARCH = int(os.getenv("HNSW_EF_SEARCH", "200"))


def normalize_citation(citation: str) -> str:
    """Collapse the punctuation variants of one citation into a single key.

    The corpus stores the same statute under more than one citation string: 928
    statutes are split across a dotted and an undotted spelling, covering 9,910
    chunks. "42 U.S.C. § 2000e" holds 38 chunks and "42 U.S.C. § 2000e." holds a
    further 4, and the Pregnancy Discrimination Act text lives only in the second
    one. Anything that groups or compares chunks by citation therefore has to
    normalise first, or the two spellings count as two different statutes: the
    per-citation cap allows two chunks from each instead of two overall, the
    sources panel lists one statute twice, and the citation guard can treat a
    correctly cited section as unsupplied.

    This is a read-side repair. The real fix belongs in ingestion, which should
    not have minted two citation strings for one section in the first place.
    """
    return re.sub(r"[.\s]+$", "", (citation or "").strip())


@dataclass
class RetrievalRow:
    chunk_id: int
    citation: str
    clause_id: str
    text_content: str
    jurisdiction: Optional[str]
    document_type: Optional[str]
    tags: List[str]
    bm25_score: float = 0.0
    vector_score: float = 0.0
    hybrid_score: float = 0.0


class QueryEmbeddingService:
    def __init__(self):
        self.model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.device = os.getenv("EMBEDDING_DEVICE", "cpu")
        self.enabled = os.getenv("SEARCH_EMBEDDING_ENABLED", "true").lower() == "true"
        self._model = None

    def _get_model(self):
        if not self.enabled:
            return None
        if self._model is None:
            if SentenceTransformer is None:
                logger.warning("sentence-transformers unavailable; vector search disabled")
                self.enabled = False
                return None
            logger.info("Loading query embedding model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            try:
                self._model.to(self.device)
            except Exception as exc:
                logger.warning("Could not move model to %s: %s", self.device, exc)
        return self._model

    def warmup(self) -> bool:
        """Load the model and run one encode so the first real request is fast.

        Touches only the model: no database, no external API. Startup must not
        depend on Postgres or Groq being reachable.
        """
        if not self.enabled:
            logger.info("Vector search disabled; skipping embedding warmup")
            return False
        started = time.perf_counter()
        vec = self.embed("warmup")
        if vec is None:
            logger.warning("Warmup produced no embedding; vector search unavailable")
            return False
        logger.info(
            "Embedding model warm in %.1fs (dim=%d)", time.perf_counter() - started, len(vec)
        )
        return True

    def embed(self, query: str) -> Optional[List[float]]:
        vecs = self.embed_many([query])
        return vecs[0] if vecs else None

    def embed_many(self, queries: List[str]) -> List[Optional[List[float]]]:
        """Encode several queries in one call.

        Multi-query retrieval needs 3-4 embeddings per request. Encoding them in
        one batch rather than one at a time keeps it to a single forward pass, and
        avoids running concurrent encodes on a model that is shared across threads
        and pinned to one OMP thread.
        """
        model = self._get_model()
        if model is None or not queries:
            return [None] * len(queries)
        vecs = model.encode(
            queries,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [v.astype(np.float32).tolist() for v in vecs]


def _vector_literal(embedding: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def _snippet(text_content: str, query: str, max_len: int = 260) -> str:
    plain = re.sub(r"\s+", " ", text_content or "").strip()
    if not plain:
        return ""

    idx = plain.lower().find(query.lower())
    if idx == -1:
        return plain[:max_len] + ("..." if len(plain) > max_len else "")

    start = max(0, idx - 80)
    end = min(len(plain), idx + 180)
    chunk = plain[start:end]
    if start > 0:
        chunk = "..." + chunk
    if end < len(plain):
        chunk = chunk + "..."
    return chunk


def _row_to_retrieval(row: Dict[str, Any], bm25_score: float = 0.0, vector_score: float = 0.0) -> RetrievalRow:
    return RetrievalRow(
        chunk_id=row["id"],
        citation=row["citation"],
        clause_id=row["clause_id"],
        text_content=row["text_content"],
        jurisdiction=row.get("jurisdiction"),
        document_type=row.get("document_type"),
        tags=row.get("tags") or [],
        bm25_score=float(bm25_score or 0.0),
        vector_score=float(vector_score or 0.0),
    )


class HybridSearchService:
    def __init__(self):
        self.embedding_service = QueryEmbeddingService()

    def _fetch_bm25(self, db: Session, query: str, limit: int, jurisdiction: Optional[str], document_type: Optional[str]):
        # Ask Postgres for the query's lexemes rather than guessing them. This
        # applies the same stemming and stopword list as the indexed
        # search_vector, so the terms built below cannot disagree with the index.
        # It touches no table, so it is cheap.
        lexemes = [
            row[0]
            for row in db.execute(
                text("SELECT lexeme FROM unnest(to_tsvector('english', :q))"),
                {"q": query},
            ).all()
        ]
        if not lexemes:
            return []

        # Drop lexemes common enough that they cannot discriminate.
        #
        # ORing every term is what makes the branch correct, and it is also what
        # makes it slow: the cost is not the index, it is ranking every matching
        # row. EXPLAIN on "freedom of speech First Amendment" showed the bitmap
        # index scan finishing in 8.8ms and the heap scan then taking 487ms to
        # fetch 34,259 rows so ts_rank_cd could be computed on each. The reason
        # the set is that large is one term: "amend" appears in 34% of chunks,
        # while "freedom" is in 0.6% and "speech" in 0.2%. A term in a third of
        # the corpus adds tens of thousands of rows to rank and almost nothing to
        # the ranking.
        #
        # The threshold is 10% rather than lower because the cut has to stay away
        # from terms that genuinely select: "tax" is 5.5% of chunks and is the
        # whole point of a tax question, and "termin" is 8.4%. Both survive at
        # 10%; both would be discarded at 5%.
        #
        # If every lexeme is common the filter is skipped entirely, because a
        # query of nothing but common words still has to return something, and an
        # empty tsquery would silently reduce hybrid search to vector-only.
        kept = [lx for lx in lexemes if COMMON_LEXEME_PCT.get(lx, 0.0) < LEXICAL_DF_MAX_PCT]
        if kept and len(kept) < len(lexemes):
            dropped = [lx for lx in lexemes if lx not in kept]
            logger.debug("lexical: dropped common lexemes %s, kept %s", dropped, kept)
            lexemes = kept

        # Any term may match, and ts_rank_cd decides what is actually relevant.
        #
        # ANDing every term, which plainto_tsquery does, requires all of them in
        # one 512-word chunk. That constraint gets harder the better the query is:
        # on this corpus "freedom of speech First Amendment" matched 2 chunks and
        # the more precise "Congress shall make no law abridge freedom of speech"
        # matched 0, and every multi-term rewrite of "can my boss fire me" matched
        # 0. When this branch returns nothing, hybrid search silently becomes
        # vector-only.
        #
        # A minimum-match requirement was the obvious guard against OR becoming
        # noise, and it was measured and rejected. Requiring any two lexemes to
        # co-occur shrank the candidate pool 7x as intended, but it made retrieval
        # worse, not better: on the same fixed query strings, Title VII's lexical
        # rank went from 4 under plain OR to 402 under min-2, and ADEA from 19 to
        # 2339. The reason is that requiring two terms rewards chunks containing
        # two COMMON words together, which in this corpus means pension and plan
        # documents carrying both "employment" and "termination", while
        # structurally excluding the chunk that matches one rare, highly
        # discriminating term very strongly. ts_rank_cd already weights by cover
        # density, so it handles that judgement better than a match-count filter
        # does.
        #
        # The cost is latency: pool sizes grow into the tens of thousands and p50
        # went from roughly 45ms to a few hundred. The LIMIT bounds what is
        # returned, not what is scanned.
        tsq = "|".join(lexemes)

        sql = text(
            """
            SELECT id, citation, clause_id, text_content, jurisdiction, document_type, tags,
                   ts_rank_cd(search_vector, to_tsquery('english', :tsq)) AS bm25_score
            FROM legal_chunks
            WHERE is_current = TRUE
              AND search_vector @@ to_tsquery('english', :tsq)
              AND (:jurisdiction IS NULL OR jurisdiction = :jurisdiction)
              AND (:document_type IS NULL OR document_type = :document_type)
            -- id breaks ties. 30 of the 50 rows in a typical window share a
            -- ts_rank_cd score, and without a tiebreaker Postgres may return
            -- tied rows in any order, so which of them survives LIMIT is not
            -- stable between executions or plans. That made identical
            -- sub-queries score a target at rank 14 on one run and 15 on the
            -- next, which is small but makes every measurement unreproducible.
            ORDER BY bm25_score DESC, id
            LIMIT :limit
            """
        )
        rows = db.execute(
            sql,
            {
                "tsq": tsq,
                "limit": limit,
                "jurisdiction": jurisdiction,
                "document_type": document_type,
            },
        ).mappings().all()
        return [_row_to_retrieval(r, bm25_score=r.get("bm25_score", 0.0)) for r in rows]

    def _fetch_vector(
        self,
        db: Session,
        embedding: List[float],
        limit: int,
        jurisdiction: Optional[str],
        document_type: Optional[str],
    ):
        # How many candidates HNSW keeps while descending the graph.
        #
        # The default is 40, which is LOWER than the 50 rows this branch asks
        # for, and pgvector cannot return more rows than it kept: the query was
        # silently returning 40 results for a LIMIT of 50. Measured against an
        # exact brute-force scan of all 83,706 vectors, ef_search=40 returned 40
        # of the true top 50, ef_search=100 returned 48, and ef_search=200
        # returned all 50. Latency at 200 is about 8ms, against 136ms for the
        # sequential scan this replaced, so exact-equivalent recall is affordable
        # here and worth paying for.
        #
        # SET LOCAL rather than a database-level setting, so the value lives with
        # the query it belongs to, is version controlled, and applies on a fresh
        # cluster without a migration. It is transaction scoped.
        db.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH:d}"))

        sql = text(
            """
            SELECT id, citation, clause_id, text_content, jurisdiction, document_type, tags,
                   1 - (embedding <=> CAST(:query_vec AS vector)) AS vector_score
            FROM legal_chunks
            WHERE is_current = TRUE
              AND embedding IS NOT NULL
              AND (:jurisdiction IS NULL OR jurisdiction = :jurisdiction)
              AND (:document_type IS NULL OR document_type = :document_type)
            -- No id tiebreaker here, deliberately, and this is the single most
            -- expensive mistake measured in this service.
            --
            -- An HNSW index can satisfy "ORDER BY embedding <=> q" and nothing
            -- else. Adding ", id" makes the ordering unsatisfiable by the index,
            -- so the planner silently abandons it and sequentially scans all
            -- 83,706 rows computing every distance. Measured warm, the same
            -- query took 104-147ms with the tiebreaker and 0.5-3.7ms without it,
            -- and EXPLAIN confirmed Seq Scan versus Index Scan using
            -- idx_chunks_embedding. Cold, the scan version took 2.5 seconds.
            --
            -- Nothing is lost by dropping it. The tiebreaker was added to make
            -- retrieval reproducible, and an index scan over a fixed HNSW index
            -- already is: the returned id order hashed identically across five
            -- consecutive runs. Exact ties in cosine distance between distinct
            -- 384-dimensional float vectors are vanishingly unlikely, which is
            -- why the lexical branch needs a tiebreaker and this one does not.
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT :limit
            """
        )
        rows = db.execute(
            sql,
            {
                "query_vec": _vector_literal(embedding),
                "limit": limit,
                "jurisdiction": jurisdiction,
                "document_type": document_type,
            },
        ).mappings().all()
        return [_row_to_retrieval(r, vector_score=r.get("vector_score", 0.0)) for r in rows]

    def _fetch_artifacts(self, db: Session, citation_version_pairs: List[tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
        if not citation_version_pairs:
            return {}

        # Fetch primary artifact per citation for current version rows.
        sql = text(
            """
            SELECT DISTINCT ON (c.citation)
                   c.citation,
                   a.id AS artifact_id,
                   a.artifact_type,
                   a.artifact_metadata
            FROM legal_chunks c
            LEFT JOIN legal_artifacts a
              ON a.citation = c.citation
             AND a.version_hash = c.version_hash
             AND a.is_primary = TRUE
            WHERE c.is_current = TRUE
              AND c.citation = ANY(:citations)
            ORDER BY c.citation, a.id NULLS LAST
            """
        )
        citations = sorted({pair[0] for pair in citation_version_pairs})
        rows = db.execute(sql, {"citations": citations}).mappings().all()

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if row.get("artifact_id") is None:
                continue
            result[row["citation"]] = {
                "artifact_id": row["artifact_id"],
                "artifact_type": row["artifact_type"],
                "artifact_metadata": row["artifact_metadata"],
            }
        return result

    def search(
        self,
        db: Session,
        query: str,
        top_k: int,
        bm25_k: int,
        vector_k: int,
        weight_bm25: float,
        weight_vector: float,
        jurisdiction: Optional[str] = None,
        document_type: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        session_factory=None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()

        # The two branches are independent, so run them at the same time when the
        # caller can supply a second session.
        #
        # They were sequential, which meant took_ms was the sum of two unrelated
        # waits. The lexical branch dominates at about 72ms, while encoding the
        # query takes 5ms and the vector branch 6ms, so overlapping them hides the
        # whole embedding and vector cost behind the lexical scan.
        #
        # A session is not thread safe, hence the factory: the lexical branch gets
        # its own. search_multi does not pass one, because it already runs a
        # separate search per sub-query concurrently and nesting a second level of
        # threads would oversubscribe two cores rather than use them.
        bm25_rows: List[RetrievalRow] = []
        vector_rows: List[RetrievalRow] = []

        if session_factory is not None:
            def lexical():
                own = session_factory()
                try:
                    return self._fetch_bm25(own, query, bm25_k, jurisdiction, document_type)
                finally:
                    own.close()

            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(lexical)
                if embedding is None:
                    embedding = self.embedding_service.embed(query)
                if embedding is not None:
                    vector_rows = self._fetch_vector(
                        db, embedding, vector_k, jurisdiction, document_type
                    )
                bm25_rows = fut.result()
        else:
            bm25_rows = self._fetch_bm25(db, query, bm25_k, jurisdiction, document_type)
            # Accepting a precomputed vector lets search_multi encode every
            # sub-query in one batch instead of once per call.
            if embedding is None:
                embedding = self.embedding_service.embed(query)
            if embedding is not None:
                vector_rows = self._fetch_vector(
                    db, embedding, vector_k, jurisdiction, document_type
                )

        by_id: Dict[int, RetrievalRow] = {}
        for row in bm25_rows:
            by_id[row.chunk_id] = row

        for row in vector_rows:
            existing = by_id.get(row.chunk_id)
            if existing:
                existing.vector_score = row.vector_score
            else:
                by_id[row.chunk_id] = row

        # Reciprocal rank fusion, replacing min-max normalised score averaging.
        #
        # The old scheme normalised each branch to 0..1 across the merged set and
        # averaged them, which meant a chunk missing from one branch was scored 0
        # for it and could not exceed half the maximum however strong the other
        # branch was. That is the wrong penalty when the branches disagree about
        # whether something exists at all rather than about where it ranks: the
        # lexical branch returns 50 rows and the vector branch returns a different
        # 50, so most items are absent from one of them by construction. For
        # "can my boss fire me" Title VII tied for the top lexical score and was
        # absent from the vector top 50, which capped it at 0.41 and put it at
        # fused rank 13 behind pension sections that scored on both.
        #
        # RRF uses position rather than magnitude, so the two branches do not need
        # a shared scale: ts_rank_cd values and cosine similarities are not
        # comparable quantities and normalising them only hid that. Absence
        # contributes nothing instead of contributing a zero that drags an average
        # down.
        #
        # k dampens how much the very top ranks dominate. 60 is the value from the
        # original RRF paper. Note it is large relative to a 50-row pool, so it
        # compresses the score range: with k=60 rank 1 scores 1/61 and rank 50
        # scores 1/110, under a 2x spread. A smaller k discriminates more sharply.
        #
        # weight_bm25 and weight_vector still mean relative branch influence, so
        # callers passing 0.5/0.5, or 1/0 to isolate a branch, behave as before.
        bm25_rank = {row.chunk_id: i + 1 for i, row in enumerate(bm25_rows)}
        vector_rank = {row.chunk_id: i + 1 for i, row in enumerate(vector_rows)}

        merged = list(by_id.values())
        for row in merged:
            score = 0.0
            if row.chunk_id in bm25_rank:
                score += weight_bm25 / (RRF_K + bm25_rank[row.chunk_id])
            if row.chunk_id in vector_rank:
                score += weight_vector / (RRF_K + vector_rank[row.chunk_id])
            row.hybrid_score = score

        merged.sort(key=lambda x: x.hybrid_score, reverse=True)
        top = merged[:top_k]

        # Rescale so the best result reads 1.0. Raw RRF scores are around 0.01 to
        # 0.03 and mean nothing to a reader; the ordering is untouched. Done after
        # the sort and over the returned slice, so the number shown is relative to
        # the best result for this query.
        if top and top[0].hybrid_score > 0:
            best = top[0].hybrid_score
            for row in top:
                row.hybrid_score = row.hybrid_score / best

        # Best effort query logging.
        took_ms = int((time.perf_counter() - started) * 1000)
        try:
            db.execute(
                text(
                    """
                    INSERT INTO search_queries (query_text, search_type, results_count, execution_time_ms)
                    VALUES (:query_text, 'hybrid', :results_count, :execution_time_ms)
                    """
                ),
                {
                    "query_text": query,
                    "results_count": len(top),
                    "execution_time_ms": took_ms,
                },
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to log search query: %s", exc)

        artifacts = self._fetch_artifacts(db, [(r.citation, "") for r in top])

        results: List[Dict[str, Any]] = []
        for row in top:
            # Normalised for display, grouping and comparison; the raw string is
            # kept because the artifact join is keyed on the exact DB value.
            citation = normalize_citation(row.citation)
            title = citation
            results.append(
                {
                    "chunk_id": row.chunk_id,
                    "citation": citation,
                    "citation_raw": row.citation,
                    "clause_id": row.clause_id,
                    "title": title,
                    "snippet": _snippet(row.text_content, query),
                    "text_content": row.text_content,
                    "jurisdiction": row.jurisdiction,
                    "document_type": row.document_type,
                    "tags": row.tags,
                    "bm25_score": round(float(row.bm25_score), 6),
                    "vector_score": round(float(row.vector_score), 6),
                    "hybrid_score": round(float(row.hybrid_score), 6),
                    "artifact": artifacts.get(row.citation),
                }
            )

        return {
            "query": query,
            "total": len(results),
            "took_ms": took_ms,
            "embedding_used": embedding is not None,
            "results": results,
        }

    def search_multi(
        self,
        session_factory,
        queries: List[str],
        top_k: int,
        bm25_k: int,
        vector_k: int,
        weight_bm25: float,
        weight_vector: float,
        per_query_k: int = 20,
        jurisdiction: Optional[str] = None,
        document_type: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve for several sub-queries and fuse the results.

        One rewrite collapses a question into a single bag of terms, so one
        ranking has to cover every legal issue the question raises. "Can my boss
        fire me" spans discrimination, union activity and medical leave, each in a
        different statute and a different title; terms that surface one push the
        others down. Retrieving per issue and fusing afterwards lets each issue
        compete on its own terms.

        Fusion is RRF over the per-sub-query result lists, with the same k as the
        within-query fusion. Each sub-query gets equal weight: there is no signal
        saying which issue the user cared about most, so weighting one would be
        inventing one. A chunk that several sub-queries agree on accumulates
        contributions and rises, which is the behaviour wanted when a question has
        one dominant issue.

        Searches run concurrently, each on its own session, because they are
        independent and sequential execution would multiply latency by the number
        of sub-queries. Embeddings are computed in a single batch beforehand so
        the shared model is never entered from several threads at once.
        """
        started = time.perf_counter()
        keep = [i for i, q in enumerate(queries) if q and q.strip()]
        labels = labels or [str(i) for i in range(len(queries))]
        queries = [queries[i] for i in keep]
        labels = [labels[i] if i < len(labels) else str(i) for i in keep]
        if not queries:
            return {"query": "", "total": 0, "took_ms": 0, "embedding_used": False,
                    "results": [], "sub_queries": [], "by_issue": {}}

        embeddings = self.embedding_service.embed_many(queries)

        def run(idx: int) -> List[Dict[str, Any]]:
            db = session_factory()
            try:
                return self.search(
                    db=db,
                    query=queries[idx],
                    top_k=per_query_k,
                    bm25_k=bm25_k,
                    vector_k=vector_k,
                    weight_bm25=weight_bm25,
                    weight_vector=weight_vector,
                    jurisdiction=jurisdiction,
                    document_type=document_type,
                    embedding=embeddings[idx],
                )["results"]
            finally:
                db.close()

        per_query: List[List[Dict[str, Any]]] = [[] for _ in queries]
        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=min(len(queries), 4)) as pool:
            futures = {pool.submit(run, i): i for i in range(len(queries))}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    per_query[i] = fut.result()
                except Exception as exc:
                    # One sub-query failing should not lose the others, but it
                    # must not vanish either. Swallowing these made a database
                    # outage look identical to a question with no results: every
                    # sub-query failed, the fused list came back empty, and the
                    # endpoint returned 200 with no answer and no error.
                    #
                    # exc_info because the message alone rarely identifies the
                    # cause, and the caller gets the count so it can tell
                    # "retrieval broke" from "nothing matched".
                    logger.warning(
                        "sub-query %d (%r) failed: %s", i, queries[i], exc, exc_info=True
                    )
                    errors.append(f"{type(exc).__name__}: {exc}")

        fused: Dict[int, float] = {}
        best: Dict[int, Dict[str, Any]] = {}
        contributors: Dict[int, int] = {}
        for rows in per_query:
            for rank, row in enumerate(rows, 1):
                cid = row["chunk_id"]
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
                contributors[cid] = contributors.get(cid, 0) + 1
                if cid not in best:
                    best[cid] = row

        order = sorted(fused, key=lambda c: fused[c], reverse=True)[:top_k]
        results = []
        for cid in order:
            row = dict(best[cid])
            row["hybrid_score"] = round(fused[cid] / fused[order[0]], 6) if fused[order[0]] else 0.0
            # How many sub-queries found this chunk. Useful for reading a result
            # set: a chunk every sub-query agrees on is a different kind of hit
            # from one only a single issue surfaced.
            row["matched_sub_queries"] = contributors[cid]
            results.append(row)

        # Also hand back each issue's own ranking. The fused list answers "what is
        # most relevant overall", which is the wrong question when the caller needs
        # to guarantee every issue is represented: fusion can legitimately rank one
        # issue's chunks above every chunk of another. Keeping the per-issue lists
        # lets the caller fill its context fairly instead of taking the head of a
        # list that may be dominated by one issue.
        by_issue = {labels[i]: per_query[i] for i in range(len(queries))}

        took_ms = int((time.perf_counter() - started) * 1000)
        return {
            "query": " | ".join(queries),
            "total": len(results),
            "took_ms": took_ms,
            "embedding_used": any(e is not None for e in embeddings),
            "results": results,
            "sub_queries": queries,
            "issues": labels,
            "by_issue": by_issue,
            # How many sub-queries failed, and how many ran at all. The caller
            # needs both to tell a retrieval outage from a genuine no-match.
            "errors": errors,
            "n_queries": len(queries),
        }
