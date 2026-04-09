"""Initial citation-centric schema

Revision ID: 001_initial
Revises:
Create Date: 2025-01-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(100), unique=True, nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('full_name', sa.String(200)),
        sa.Column('role', sa.String(50), server_default='user'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.now()),
    )

    # Legal chunks table (citation-centric)
    op.create_table(
        'legal_chunks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('citation', sa.String(200), nullable=False, index=True),
        sa.Column('clause_id', sa.String(250), unique=True, nullable=False),
        sa.Column('text_content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(384)),
        sa.Column('search_vector', sa.dialects.postgresql.TSVECTOR()),
        sa.Column('jurisdiction', sa.String(100), server_default='Federal'),
        sa.Column('document_type', sa.String(50)),
        sa.Column('chunk_type', sa.String(50)),
        sa.Column('tags', ARRAY(sa.Text())),
        sa.Column('version_hash', sa.String(64), nullable=False),
        sa.Column('is_current', sa.Boolean(), server_default='true'),
        sa.Column('effective_date', sa.Date()),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.func.now()),
    )

    # Legal artifacts table
    op.create_table(
        'legal_artifacts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('citation', sa.String(200), nullable=False, index=True),
        sa.Column('artifact_type', sa.String(50), nullable=False),
        sa.Column('artifact_metadata', JSONB(), nullable=False),
        sa.Column('version_hash', sa.String(64), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint('citation', 'artifact_type', 'version_hash', name='unique_citation_artifact'),
    )

    # Search queries table
    op.create_table(
        'search_queries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('search_type', sa.String(50)),
        sa.Column('results_count', sa.Integer()),
        sa.Column('execution_time_ms', sa.Integer()),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column('filters', JSONB()),
    )

    # Notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text()),
        sa.Column('notification_type', sa.String(50)),
        sa.Column('is_read', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column('notification_metadata', JSONB()),
    )

    # Ingestion runs table
    op.create_table(
        'ingestion_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('jurisdiction', sa.String(100)),
        sa.Column('run_started_at', sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column('run_completed_at', sa.TIMESTAMP()),
        sa.Column('status', sa.String(20)),
        sa.Column('last_hash', sa.String(64)),
        sa.Column('chunks_added', sa.Integer(), server_default='0'),
        sa.Column('chunks_updated', sa.Integer(), server_default='0'),
        sa.Column('artifacts_added', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text()),
    )

    # Create indexes for legal_chunks
    op.create_index('idx_chunks_clause_id', 'legal_chunks', ['clause_id'])
    op.create_index('idx_chunks_jurisdiction', 'legal_chunks', ['jurisdiction'])
    op.create_index('idx_chunks_document_type', 'legal_chunks', ['document_type'])
    op.create_index('idx_chunks_version', 'legal_chunks', ['version_hash'])
    op.execute(
        'CREATE INDEX idx_chunks_embedding ON legal_chunks '
        'USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)'
    )
    op.execute(
        'CREATE INDEX idx_chunks_search_vector ON legal_chunks USING gin(search_vector)'
    )
    op.execute(
        'CREATE INDEX idx_chunks_tags ON legal_chunks USING gin(tags)'
    )
    op.execute(
        'CREATE INDEX idx_chunks_current ON legal_chunks(is_current) WHERE is_current = TRUE'
    )

    # Create indexes for legal_artifacts
    op.create_index('idx_artifacts_type', 'legal_artifacts', ['artifact_type'])
    op.create_index('idx_artifacts_version', 'legal_artifacts', ['version_hash'])
    op.execute(
        'CREATE INDEX idx_artifacts_primary ON legal_artifacts(is_primary) WHERE is_primary = TRUE'
    )

    # Create indexes for other tables
    op.create_index('idx_search_queries_user_id', 'search_queries', ['user_id'])
    op.create_index('idx_search_queries_created_at', 'search_queries', ['created_at'])
    op.create_index('idx_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('idx_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('idx_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('idx_ingestion_source', 'ingestion_runs', ['source_type'])
    op.create_index('idx_ingestion_started', 'ingestion_runs', ['run_started_at'])

    # Create triggers for search_vector auto-update
    op.execute("""
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector = to_tsvector('english', NEW.text_content);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trigger_chunks_search_vector
            BEFORE INSERT OR UPDATE OF text_content
            ON legal_chunks
            FOR EACH ROW
            EXECUTE FUNCTION update_search_vector()
    """)

    # Create triggers for updated_at auto-update
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trigger_users_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at()
    """)

    op.execute("""
        CREATE TRIGGER trigger_chunks_updated_at
            BEFORE UPDATE ON legal_chunks
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at()
    """)

    # Insert default admin user
    op.execute("""
        INSERT INTO users (username, email, full_name, role, is_active)
        VALUES ('admin', 'admin@casetally.com', 'System Administrator', 'admin', TRUE)
        ON CONFLICT (username) DO NOTHING
    """)


def downgrade() -> None:
    # Drop triggers
    op.execute('DROP TRIGGER IF EXISTS trigger_chunks_updated_at ON legal_chunks')
    op.execute('DROP TRIGGER IF EXISTS trigger_users_updated_at ON users')
    op.execute('DROP TRIGGER IF EXISTS trigger_chunks_search_vector ON legal_chunks')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at()')
    op.execute('DROP FUNCTION IF EXISTS update_search_vector()')

    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('ingestion_runs')
    op.drop_table('notifications')
    op.drop_table('search_queries')
    op.drop_table('legal_artifacts')
    op.drop_table('legal_chunks')
    op.drop_table('users')
