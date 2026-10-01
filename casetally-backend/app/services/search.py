import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

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
        model = self._get_model()
        if model is None:
            return None
        vec = model.encode(
            [query],
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]
        return vec.astype(np.float32).tolist()


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
            ORDER BY bm25_score DESC
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
        sql = text(
            """
            SELECT id, citation, clause_id, text_content, jurisdiction, document_type, tags,
                   1 - (embedding <=> CAST(:query_vec AS vector)) AS vector_score
            FROM legal_chunks
            WHERE is_current = TRUE
              AND embedding IS NOT NULL
              AND (:jurisdiction IS NULL OR jurisdiction = :jurisdiction)
              AND (:document_type IS NULL OR document_type = :document_type)
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
    ) -> Dict[str, Any]:
        started = time.perf_counter()

        bm25_rows = self._fetch_bm25(db, query, bm25_k, jurisdiction, document_type)
        embedding = self.embedding_service.embed(query)
        vector_rows: List[RetrievalRow] = []
        if embedding is not None:
            vector_rows = self._fetch_vector(db, embedding, vector_k, jurisdiction, document_type)

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
            title = row.citation
            results.append(
                {
                    "chunk_id": row.chunk_id,
                    "citation": row.citation,
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
