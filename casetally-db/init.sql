-- =============================================================================
-- CaseTally - Citation-Centric Schema
-- Version: 2.0 (Migration from document-centric to citation-centric)
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- =============================================================================
-- TABLE 1: users (UNCHANGED)
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(200),
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- TABLE 2: legal_chunks (REPLACES legal_documents + document_chunks)
-- Citation-indexed search chunks with hybrid search support
-- =============================================================================
CREATE TABLE IF NOT EXISTS legal_chunks (
    id SERIAL PRIMARY KEY,
    
    -- Citation is the primary searchable key
    citation VARCHAR(200) NOT NULL,
    clause_id VARCHAR(250) UNIQUE NOT NULL,
    
    -- Content
    text_content TEXT NOT NULL,
    
    -- Hybrid search: Vector (semantic) + BM25 (keyword)
    embedding VECTOR(384),              -- Sentence transformer embeddings
    search_vector tsvector,              -- Auto-generated for BM25 search
    
    -- Metadata
    jurisdiction VARCHAR(100) DEFAULT 'Federal',
    document_type VARCHAR(50),           -- 'US Code', 'State Code', 'Case Law'
    chunk_type VARCHAR(50),              -- 'section', 'clause', 'paragraph'
    tags TEXT[],                         -- Fast array-based tags
    
    -- Version control (critical for legal accuracy)
    version_hash VARCHAR(64) NOT NULL,   -- SHA256 of source
    is_current BOOLEAN DEFAULT TRUE,     -- Handle statute updates
    effective_date DATE,                 -- When law took effect

    -- Embedding failure tracking: the worker's queue is "embedding IS NULL",
    -- so a chunk that always fails to encode would be retried forever and
    -- starve everything behind it. Rows at or above the retry cap are skipped.
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- TABLE 3: legal_artifacts (NEW)
-- Display layer: PDF pages, HTML links, API endpoints
-- =============================================================================
CREATE TABLE IF NOT EXISTS legal_artifacts (
    id SERIAL PRIMARY KEY,
    
    -- Links to legal_chunks
    citation VARCHAR(200) NOT NULL,
    
    -- Flexible artifact storage
    artifact_type VARCHAR(50) NOT NULL,  -- 'pdf', 'html', 'xml', 'api'
    artifact_metadata JSONB NOT NULL,
    -- Examples:
    -- PDF:  {"file_path": "/data/title1.pdf", "page": 2}
    -- HTML: {"url": "https://...", "section_id": "#section-1"}
    -- API:  {"endpoint": "https://...", "opinion_id": 12345}
    
    -- Version control (must match legal_chunks.version_hash)
    version_hash VARCHAR(64) NOT NULL,
    is_primary BOOLEAN DEFAULT TRUE,     -- Which artifact to show first
    
    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT unique_citation_artifact UNIQUE (citation, artifact_type, version_hash)
);

-- =============================================================================
-- TABLE 4: search_queries (UNCHANGED)
-- =============================================================================
CREATE TABLE IF NOT EXISTS search_queries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    query_text TEXT NOT NULL,
    search_type VARCHAR(50),             -- 'vector', 'bm25', 'hybrid'
    results_count INTEGER,
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filters JSONB
);

-- =============================================================================
-- TABLE 5: notifications (UNCHANGED)
-- =============================================================================
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    message TEXT,
    notification_type VARCHAR(50),
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notification_metadata JSONB
);

-- =============================================================================
-- TABLE 6: ingestion_runs (NEW)
-- Track scraper execution and changes
-- =============================================================================
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50) NOT NULL,    -- 'uscode', 'arizona', 'texas'
    jurisdiction VARCHAR(100),
    run_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    run_completed_at TIMESTAMP,
    status VARCHAR(20),                  -- 'running', 'success', 'failed'
    last_hash VARCHAR(64),               -- Detect if source changed
    chunks_added INTEGER DEFAULT 0,
    chunks_updated INTEGER DEFAULT 0,
    artifacts_added INTEGER DEFAULT 0,
    error_message TEXT
);

-- =============================================================================
-- INDEXES: Performance optimization
-- =============================================================================

-- legal_chunks indexes
CREATE INDEX IF NOT EXISTS idx_chunks_citation ON legal_chunks(citation);
CREATE INDEX IF NOT EXISTS idx_chunks_clause_id ON legal_chunks(clause_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON legal_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector ON legal_chunks 
    USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_tags ON legal_chunks 
    USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_chunks_jurisdiction ON legal_chunks(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_chunks_document_type ON legal_chunks(document_type);
CREATE INDEX IF NOT EXISTS idx_chunks_current ON legal_chunks(is_current) 
    WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_chunks_version ON legal_chunks(version_hash);

-- legal_artifacts indexes
CREATE INDEX IF NOT EXISTS idx_artifacts_citation ON legal_artifacts(citation);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON legal_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_primary ON legal_artifacts(is_primary) 
    WHERE is_primary = TRUE;
CREATE INDEX IF NOT EXISTS idx_artifacts_version ON legal_artifacts(version_hash);

-- Other tables
CREATE INDEX IF NOT EXISTS idx_search_queries_user_id ON search_queries(user_id);
CREATE INDEX IF NOT EXISTS idx_search_queries_created_at ON search_queries(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_source ON ingestion_runs(source_type);
CREATE INDEX IF NOT EXISTS idx_ingestion_started ON ingestion_runs(run_started_at);

-- =============================================================================
-- TRIGGERS: Auto-update computed columns
-- =============================================================================

-- Auto-update search_vector from text_content
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector = to_tsvector('english', NEW.text_content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_chunks_search_vector
    BEFORE INSERT OR UPDATE OF text_content
    ON legal_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_search_vector();

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_chunks_updated_at
    BEFORE UPDATE ON legal_chunks 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- VIEWS: Common query patterns
-- =============================================================================

-- Unified search results view (joins chunks with artifacts)
CREATE OR REPLACE VIEW legal_search_results AS
SELECT 
    c.id,
    c.citation,
    c.clause_id,
    c.text_content,
    c.chunk_type,
    c.jurisdiction,
    c.document_type,
    c.tags,
    c.effective_date,
    c.version_hash,
    c.is_current,
    c.created_at,
    
    -- Aggregate all artifacts as JSONB
    jsonb_object_agg(
        a.artifact_type, 
        a.artifact_metadata
    ) FILTER (WHERE a.id IS NOT NULL) as artifacts
    
FROM legal_chunks c
LEFT JOIN legal_artifacts a 
    ON c.citation = a.citation 
    AND c.version_hash = a.version_hash
WHERE c.is_current = TRUE
GROUP BY c.id, c.citation, c.clause_id, c.text_content, c.chunk_type, 
         c.jurisdiction, c.document_type, c.tags, c.effective_date, 
         c.version_hash, c.is_current, c.created_at;

-- Current citations summary (deduplicated)
CREATE OR REPLACE VIEW current_citations AS
SELECT DISTINCT ON (citation)
    citation,
    jurisdiction,
    document_type,
    effective_date,
    tags,
    COUNT(*) OVER (PARTITION BY citation) as clause_count
FROM legal_chunks
WHERE is_current = TRUE
ORDER BY citation, effective_date DESC NULLS LAST;

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get PDF page for a citation
CREATE OR REPLACE FUNCTION get_pdf_page(citation_text VARCHAR)
RETURNS INTEGER AS $$
DECLARE
    page_num INTEGER;
BEGIN
    SELECT (artifact_metadata->>'page')::INTEGER INTO page_num
    FROM legal_artifacts
    WHERE citation = citation_text
      AND artifact_type = 'pdf'
      AND is_primary = TRUE
    LIMIT 1;
    
    RETURN page_num;
END;
$$ LANGUAGE plpgsql;

-- Check version consistency
CREATE OR REPLACE FUNCTION check_version_consistency()
RETURNS TABLE (
    citation VARCHAR,
    atom_hash VARCHAR,
    artifact_hash VARCHAR,
    status TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.citation,
        c.version_hash as atom_hash,
        a.version_hash as artifact_hash,
        CASE 
            WHEN c.version_hash = a.version_hash THEN 'OK'
            WHEN a.version_hash IS NULL THEN 'MISSING_ARTIFACT'
            ELSE 'VERSION_MISMATCH'
        END as status
    FROM legal_chunks c
    LEFT JOIN legal_artifacts a ON c.citation = a.citation
    WHERE c.is_current = TRUE;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- SEED DATA
-- =============================================================================

-- Insert default admin user
INSERT INTO users (username, email, full_name, role, is_active)
VALUES ('admin', 'admin@casetally.com', 'System Administrator', 'admin', TRUE)
ON CONFLICT (username) DO NOTHING;

-- =============================================================================
-- COMMENTS: Documentation
-- =============================================================================

COMMENT ON TABLE users IS 'User accounts for the law library system';
COMMENT ON TABLE legal_chunks IS 'Citation-indexed chunks for hybrid search (BM25 + vector) and LLM context';
COMMENT ON TABLE legal_artifacts IS 'Display metadata (PDF pages, HTML links, etc.) for citations';
COMMENT ON TABLE search_queries IS 'Log of user search queries for analytics';
COMMENT ON TABLE notifications IS 'User notifications and alerts';
COMMENT ON TABLE ingestion_runs IS 'Track scraper execution and version changes';

COMMENT ON COLUMN legal_chunks.citation IS 'Primary legal citation (e.g., "1 U.S.C. § 1")';
COMMENT ON COLUMN legal_chunks.clause_id IS 'Unique clause identifier (e.g., "1 U.S.C. § 1, cl. 2")';
COMMENT ON COLUMN legal_chunks.embedding IS 'Vector embedding for semantic search (sentence-transformers/all-MiniLM-L6-v2, 384 dimensions)';
COMMENT ON COLUMN legal_chunks.search_vector IS 'Auto-generated tsvector for BM25 full-text search';
COMMENT ON COLUMN legal_chunks.tags IS 'Deterministic tags extracted from citation structure';
COMMENT ON COLUMN legal_chunks.version_hash IS 'SHA256 hash of source document for version control';
COMMENT ON COLUMN legal_chunks.is_current IS 'TRUE for current version, FALSE for historical versions';

COMMENT ON COLUMN legal_artifacts.artifact_type IS 'Type of display artifact: pdf, html, xml, api';
COMMENT ON COLUMN legal_artifacts.artifact_metadata IS 'Type-specific data (file_path, page, url, etc.)';
COMMENT ON COLUMN legal_artifacts.version_hash IS 'MUST match legal_chunks.version_hash to ensure consistency';

COMMENT ON VIEW legal_search_results IS 'Unified search results joining chunks with all their artifacts';
COMMENT ON VIEW current_citations IS 'Deduplicated list of current citations with summary stats';

-- =============================================================================
-- MIGRATION NOTES
-- =============================================================================

-- This schema replaces:
--   - legal_documents (removed - citation is now the primary key)
--   - document_chunks (replaced by legal_chunks with citation indexing)
--
-- Key improvements:
--   1. Citation-centric design (not document-centric)
--   2. Hybrid search (BM25 + vector, not just vector)
--   3. Version control (prevents search/PDF drift)
--   4. Flexible artifacts (supports PDF, HTML, XML, API)
--   5. Multi-source ready (US Code, state codes, case law)
--
-- Breaking changes:
--   - All existing data must be re-ingested
--   - Old API endpoints need to query legal_chunks, not document_chunks
--   - Search now returns citations, not document IDs