# ingestion/core/base_ingestor.py
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .chunker import TextChunker

logger = logging.getLogger(__name__)


class BaseIngestor(ABC):
    """
    Abstract base class for all data ingestors.

    Uses the citation-centric schema (v2.0):
    - legal_chunks: Citation-indexed text chunks for search
    - legal_artifacts: PDF/HTML links for display

    Subclasses must implement:
    - run(): Main ingestion logic
    """

    def __init__(self, session: Session, data_dir: Path, batch_size: int = 100):
        self.session = session
        self.data_dir = data_dir
        self.batch_size = batch_size
        self.chunker = TextChunker(chunk_size=512, overlap=50)

        # Create data directory if needed
        self.data_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized {self.__class__.__name__}")
        logger.info(f"Data directory: {self.data_dir}")
        logger.info(f"Batch size: {self.batch_size}")

    @abstractmethod
    def run(self, limit: Optional[int] = None) -> Dict:
        """
        Main ingestion method - must be implemented by subclasses.

        Args:
            limit: Optional limit on number of documents to process

        Returns:
            Dict with statistics: {
                'processed': int,
                'inserted': int,
                'skipped': int,
                'errors': int,
                'chunks_created': int
            }
        """
        raise NotImplementedError("Subclasses must implement run()")

    def _compute_version_hash(self, content: str) -> str:
        """Compute SHA256 hash of content for version control."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _generate_clause_id(self, citation: str, chunk_index: int) -> str:
        """Generate unique clause_id for a chunk."""
        return f"{citation}, chunk {chunk_index}"

    def insert_legal_chunk(
        self,
        citation: str,
        text_content: str,
        chunk_index: int,
        version_hash: str,
        jurisdiction: str = 'Federal',
        document_type: str = None,
        chunk_type: str = 'section',
        tags: List[str] = None,
        effective_date: str = None
    ) -> Dict:
        """
        Insert a legal chunk into the database.

        Args:
            citation: Legal citation (e.g., "18 U.S.C. § 1001")
            text_content: Full text content of the chunk
            chunk_index: Index of this chunk within the document
            jurisdiction: Federal, State, etc.
            document_type: 'US Code', 'State Code', 'Case Law'
            chunk_type: 'section', 'clause', 'paragraph'
            tags: Array of tags
            effective_date: Date the law took effect (YYYY-MM-DD)

        Returns:
            Dict with insertion/update details
        """
        clause_id = self._generate_clause_id(citation, chunk_index)
        params = {
            'citation': citation,
            'clause_id': clause_id,
            'text_content': text_content,
            'jurisdiction': jurisdiction,
            'document_type': document_type,
            'chunk_type': chunk_type,
            'tags': tags,
            'version_hash': version_hash,
            'effective_date': effective_date
        }

        existing_sql = text("""
            SELECT id, citation, text_content, jurisdiction, document_type,
                   chunk_type, tags, version_hash, effective_date
            FROM legal_chunks
            WHERE clause_id = :clause_id
            LIMIT 1
        """)
        existing = self.session.execute(existing_sql, {'clause_id': clause_id}).mappings().first()

        if existing is None:
            insert_sql = text("""
                INSERT INTO legal_chunks
                (citation, clause_id, text_content, jurisdiction, document_type,
                 chunk_type, tags, version_hash, is_current, effective_date)
                VALUES
                (:citation, :clause_id, :text_content, :jurisdiction, :document_type,
                 :chunk_type, :tags, :version_hash, TRUE, :effective_date)
                RETURNING id
            """)
            chunk_id = self.session.execute(insert_sql, params).scalar()
            logger.debug(f"Inserted chunk: {clause_id} (ID: {chunk_id})")
            return {'id': chunk_id, 'created': 1, 'updated': 0, 'unchanged': 0}

        text_changed = (
            existing['text_content'] != text_content
            or existing['version_hash'] != version_hash
        )
        metadata_changed = (
            existing['citation'] != citation
            or existing['jurisdiction'] != jurisdiction
            or existing['document_type'] != document_type
            or existing['chunk_type'] != chunk_type
            or (existing['tags'] or []) != (tags or [])
            or existing['effective_date'] != effective_date
        )

        if not text_changed and not metadata_changed:
            return {'id': existing['id'], 'created': 0, 'updated': 0, 'unchanged': 1}

        update_sql = text("""
            UPDATE legal_chunks
            SET citation = :citation,
                text_content = :text_content,
                jurisdiction = :jurisdiction,
                document_type = :document_type,
                chunk_type = :chunk_type,
                tags = :tags,
                version_hash = :version_hash,
                effective_date = :effective_date,
                is_current = TRUE,
                embedding = CASE WHEN :reset_embedding THEN NULL ELSE embedding END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """)
        self.session.execute(update_sql, {**params, 'id': existing['id'], 'reset_embedding': text_changed})
        logger.debug(f"Updated chunk: {clause_id} (ID: {existing['id']}) text_changed={text_changed}")
        return {'id': existing['id'], 'created': 0, 'updated': 1, 'unchanged': 0}

    def insert_legal_artifact(
        self,
        citation: str,
        artifact_type: str,
        artifact_metadata: Dict,
        version_hash: str,
        is_primary: bool = True
    ) -> Dict:
        """
        Insert a legal artifact (PDF link, HTML link, etc.) into the database.

        Args:
            citation: Legal citation this artifact belongs to
            artifact_type: 'pdf', 'html', 'xml', 'api'
            artifact_metadata: Type-specific metadata (file_path, page, url, etc.)
            version_hash: Must match legal_chunks.version_hash
            is_primary: Whether this is the primary display artifact

        Returns:
            Dict with insertion/update details
        """
        artifact_payload = json.dumps(artifact_metadata)
        existing_sql = text("""
            SELECT id, artifact_metadata, is_primary
            FROM legal_artifacts
            WHERE citation = :citation
              AND artifact_type = :artifact_type
              AND version_hash = :version_hash
            LIMIT 1
        """)
        existing = self.session.execute(existing_sql, {
            'citation': citation,
            'artifact_type': artifact_type,
            'version_hash': version_hash
        }).mappings().first()

        if existing is None:
            insert_sql = text("""
                INSERT INTO legal_artifacts
                (citation, artifact_type, artifact_metadata, version_hash, is_primary)
                VALUES
                (:citation, :artifact_type, :artifact_metadata, :version_hash, :is_primary)
                RETURNING id
            """)
            artifact_id = self.session.execute(insert_sql, {
                'citation': citation,
                'artifact_type': artifact_type,
                'artifact_metadata': artifact_payload,
                'version_hash': version_hash,
                'is_primary': is_primary
            }).scalar()
            logger.debug(f"Inserted artifact: {citation} ({artifact_type})")
            return {'id': artifact_id, 'created': 1, 'updated': 0, 'unchanged': 0}

        if existing['artifact_metadata'] == artifact_metadata and existing['is_primary'] == is_primary:
            return {'id': existing['id'], 'created': 0, 'updated': 0, 'unchanged': 1}

        update_sql = text("""
            UPDATE legal_artifacts
            SET artifact_metadata = :artifact_metadata,
                is_primary = :is_primary
            WHERE id = :id
        """)
        self.session.execute(update_sql, {
            'id': existing['id'],
            'artifact_metadata': artifact_payload,
            'is_primary': is_primary
        })
        logger.debug(f"Updated artifact: {citation} ({artifact_type})")
        return {'id': existing['id'], 'created': 0, 'updated': 1, 'unchanged': 0}

    def deactivate_stale_chunks(self, citation: str, active_clause_ids: List[str]) -> int:
        """Mark chunks not present in the latest ingestion for a citation as non-current."""
        if active_clause_ids:
            sql = text("""
                UPDATE legal_chunks
                SET is_current = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE citation = :citation
                  AND is_current = TRUE
                  AND NOT (clause_id = ANY(:active_clause_ids))
            """)
            result = self.session.execute(sql, {
                'citation': citation,
                'active_clause_ids': active_clause_ids
            })
            return result.rowcount or 0

        sql = text("""
            UPDATE legal_chunks
            SET is_current = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE citation = :citation
              AND is_current = TRUE
        """)
        result = self.session.execute(sql, {'citation': citation})
        return result.rowcount or 0

    def ingest_document(
        self,
        citation: str,
        content: str,
        jurisdiction: str = 'Federal',
        document_type: str = None,
        pdf_path: str = None,
        pdf_page: int = None,
        html_url: str = None,
        metadata: Dict = None
    ) -> Dict:
        """
        High-level method to ingest a complete document.

        Chunks the content and inserts both legal_chunks and legal_artifacts.

        Args:
            citation: Legal citation (e.g., "18 U.S.C. § 1001")
            content: Full text content
            jurisdiction: Federal, State, etc.
            document_type: 'US Code', 'State Code', 'Case Law'
            pdf_path: Path to PDF file (optional)
            pdf_page: Page number in PDF (optional)
            html_url: URL to HTML version (optional)
            metadata: Additional metadata (optional)

        Returns:
            Dict with created/updated counters for chunks and artifacts
        """
        result = {
            'chunks_created': 0,
            'chunks_updated': 0,
            'chunks_unchanged': 0,
            'chunks_deactivated': 0,
            'artifacts_created': 0,
            'artifacts_updated': 0,
            'artifacts_unchanged': 0,
            'status': 'unchanged'
        }

        # Chunk the content
        chunks = self.chunker.chunk_text(content)

        if not chunks:
            logger.warning(f"No chunks generated for {citation}")
            return result

        # Compute version hash from full content
        version_hash = self._compute_version_hash(content)

        # Insert each chunk with document-level version hash so chunks/artifacts stay consistent.
        active_clause_ids: List[str] = []
        for idx, chunk in enumerate(chunks):
            chunk_result = self.insert_legal_chunk(
                citation=citation,
                text_content=chunk['text'],
                chunk_index=idx,
                version_hash=version_hash,
                jurisdiction=jurisdiction,
                document_type=document_type,
                chunk_type=chunk.get('type', 'section'),
                tags=(metadata or {}).get('tags'),
                effective_date=(metadata or {}).get('effective_date')
            )
            active_clause_ids.append(self._generate_clause_id(citation, idx))
            result['chunks_created'] += chunk_result['created']
            result['chunks_updated'] += chunk_result['updated']
            result['chunks_unchanged'] += chunk_result['unchanged']

        result['chunks_deactivated'] = self.deactivate_stale_chunks(citation, active_clause_ids)

        # Insert PDF artifact if provided
        if pdf_path:
            artifact_metadata = {'file_path': pdf_path}
            if pdf_page is not None:
                artifact_metadata['page'] = pdf_page

            artifact_result = self.insert_legal_artifact(
                citation=citation,
                artifact_type='pdf',
                artifact_metadata=artifact_metadata,
                version_hash=version_hash,
                is_primary=True
            )
            result['artifacts_created'] += artifact_result['created']
            result['artifacts_updated'] += artifact_result['updated']
            result['artifacts_unchanged'] += artifact_result['unchanged']

        # Insert HTML artifact if provided
        if html_url:
            artifact_result = self.insert_legal_artifact(
                citation=citation,
                artifact_type='html',
                artifact_metadata={'url': html_url},
                version_hash=version_hash,
                is_primary=not pdf_path  # Primary if no PDF
            )
            result['artifacts_created'] += artifact_result['created']
            result['artifacts_updated'] += artifact_result['updated']
            result['artifacts_unchanged'] += artifact_result['unchanged']

        if result['chunks_created'] > 0:
            result['status'] = 'inserted'
        elif result['chunks_updated'] > 0 or result['chunks_deactivated'] > 0:
            result['status'] = 'updated'
        else:
            result['status'] = 'unchanged'

        logger.debug(
            "Ingested %s: chunks(created=%s, updated=%s, unchanged=%s, deactivated=%s), "
            "artifacts(created=%s, updated=%s, unchanged=%s)",
            citation,
            result['chunks_created'],
            result['chunks_updated'],
            result['chunks_unchanged'],
            result['chunks_deactivated'],
            result['artifacts_created'],
            result['artifacts_updated'],
            result['artifacts_unchanged']
        )
        return result

    def chunk_exists(self, citation: str) -> bool:
        """
        Check if any chunk exists for a citation.

        Args:
            citation: Legal citation to check

        Returns:
            True if any chunk exists for this citation
        """
        sql = text("SELECT id FROM legal_chunks WHERE citation = :citation LIMIT 1")
        result = self.session.execute(sql, {'citation': citation})
        return result.fetchone() is not None

    def get_chunk_count(self) -> int:
        """Get total number of chunks in database."""
        sql = text("SELECT COUNT(*) FROM legal_chunks")
        result = self.session.execute(sql)
        return result.scalar()

    def get_artifact_count(self) -> int:
        """Get total number of artifacts in database."""
        sql = text("SELECT COUNT(*) FROM legal_artifacts")
        result = self.session.execute(sql)
        return result.scalar()

    def get_citation_count(self) -> int:
        """Get number of unique citations in database."""
        sql = text("SELECT COUNT(DISTINCT citation) FROM legal_chunks")
        result = self.session.execute(sql)
        return result.scalar()

    def start_ingestion_run(self, source_type: str, jurisdiction: str = None) -> int:
        """
        Record the start of an ingestion run.

        Args:
            source_type: 'uscode', 'california', etc.
            jurisdiction: Federal, State name, etc.

        Returns:
            Run ID
        """
        sql = text("""
            INSERT INTO ingestion_runs (source_type, jurisdiction, status)
            VALUES (:source_type, :jurisdiction, 'running')
            RETURNING id
        """)

        result = self.session.execute(sql, {
            'source_type': source_type,
            'jurisdiction': jurisdiction
        })
        self.session.commit()

        run_id = result.fetchone()[0]
        logger.info(f"Started ingestion run {run_id} for {source_type}")
        return run_id

    def complete_ingestion_run(
        self,
        run_id: int,
        chunks_added: int = 0,
        chunks_updated: int = 0,
        artifacts_added: int = 0,
        error_message: str = None
    ):
        """
        Record the completion of an ingestion run.

        Args:
            run_id: ID from start_ingestion_run
            chunks_added: Number of new chunks
            chunks_updated: Number of updated chunks
            artifacts_added: Number of new artifacts
            error_message: Error message if failed
        """
        status = 'failed' if error_message else 'success'

        sql = text("""
            UPDATE ingestion_runs SET
                run_completed_at = CURRENT_TIMESTAMP,
                status = :status,
                chunks_added = :chunks_added,
                chunks_updated = :chunks_updated,
                artifacts_added = :artifacts_added,
                error_message = :error_message
            WHERE id = :run_id
        """)

        self.session.execute(sql, {
            'run_id': run_id,
            'status': status,
            'chunks_added': chunks_added,
            'chunks_updated': chunks_updated,
            'artifacts_added': artifacts_added,
            'error_message': error_message
        })
        self.session.commit()

        logger.info(f"Completed ingestion run {run_id}: {status}")

    def commit_batch(self):
        """Commit current transaction."""
        try:
            self.session.commit()
            logger.debug("Batch committed successfully")
        except Exception as e:
            logger.error(f"Error committing batch: {e}")
            self.session.rollback()
            raise


# Backward compatibility aliases
BaseIngestor.document_exists = BaseIngestor.chunk_exists
BaseIngestor.get_document_count = BaseIngestor.get_citation_count
