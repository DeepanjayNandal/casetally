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


def _normalize_scores(values: List[float]) -> List[float]:
    if not values:
        return []
    max_v = max(values)
    min_v = min(values)
    if max_v == min_v:
        return [0.0 if max_v == 0.0 else 1.0 for _ in values]
    return [(v - min_v) / (max_v - min_v) for v in values]


class HybridSearchService:
    def __init__(self):
        self.embedding_service = QueryEmbeddingService()

    def _fetch_bm25(self, db: Session, query: str, limit: int, jurisdiction: Optional[str], document_type: Optional[str]):
        sql = text(
            """
            SELECT id, citation, clause_id, text_content, jurisdiction, document_type, tags,
                   ts_rank_cd(search_vector, plainto_tsquery('english', :query)) AS bm25_score
            FROM legal_chunks
            WHERE is_current = TRUE
              AND search_vector @@ plainto_tsquery('english', :query)
              AND (:jurisdiction IS NULL OR jurisdiction = :jurisdiction)
              AND (:document_type IS NULL OR document_type = :document_type)
            ORDER BY bm25_score DESC
            LIMIT :limit
            """
        )
        rows = db.execute(
            sql,
            {
                "query": query,
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

        merged = list(by_id.values())
        bm25_norm = _normalize_scores([r.bm25_score for r in merged])
        vector_norm = _normalize_scores([r.vector_score for r in merged])

        for i, row in enumerate(merged):
            row.hybrid_score = (weight_bm25 * bm25_norm[i]) + (weight_vector * vector_norm[i])

        merged.sort(key=lambda x: x.hybrid_score, reverse=True)
        top = merged[:top_k]

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
