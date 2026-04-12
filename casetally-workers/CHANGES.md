# Production-Ready Improvements

## Changes Made

### 1. ✅ Dynamic Embedding Dimension (Breaking Change)
**File**: `shared/models_chunk.py`
- Removed hard-coded `384` dimension
- Added `EMBEDDING_DIMENSION` constant read from environment variable `EMBEDDING_DIMENSION`
- Default remains `384` for backward compatibility
- **Impact**: Can now switch embedding models without code changes

**Environment Variable**:
```bash
EMBEDDING_DIMENSION=768  # For models like all-mpnet-base-v2, bge-base-en-v1.5
```

### 2. ✅ Improved Database Query Methods
**File**: `embedding_worker.py`
- Changed `_get_pending_chunks()` from raw SQL to SQLAlchemy ORM query
  - Uses `session.query(DocumentChunk.id, DocumentChunk.content).filter(...)`
  - More maintainable and consistent with codebase style
- Changed `_update_embeddings()` from raw SQL update to ORM object assignment
  - Fetches chunk objects and updates `.embedding` attribute
  - Cleaner, more readable, and easier to debug

### 3. ✅ Startup Validation
**File**: `embedding_worker.py`
- **Database Connection Check**: Validates PostgreSQL connectivity on `__init__`
  - Tests connection with `SELECT 1` query
  - Fails fast if database is unreachable
- **Redis Connection Check**: Validates Redis connectivity on `__init__`
  - Tests connection with `ping()`
  - Fails fast if Redis is unreachable
- **Configuration Logging**: Logs embedding model, dimension, and device on startup
  - Helps with debugging configuration issues

### 4. ✅ Documentation Updates
**File**: `README.md`
- Added `EMBEDDING_DIMENSION` environment variable to configuration table
- New section: "Changing Embedding Models" with:
  - Instructions for switching models
  - Common model dimension mappings
  - SQL migration examples
- New section: "Startup Validation" documenting pre-flight checks

## Backward Compatibility

✅ **Fully backward compatible**
- Default `EMBEDDING_DIMENSION=384` matches previous hard-coded value
- No breaking changes to existing deployments
- Existing environment variables work unchanged

## Migration Guide

### For Existing Deployments
No action required - everything works as before.

### For Changing Embedding Models
1. **Update Docker environment or docker-compose.yml**:
   ```yaml
   environment:
     - EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
     - EMBEDDING_DIMENSION=768
   ```

2. **Update database schema** (one-time):
   ```sql
   -- If document_chunks table doesn't exist yet:
   ALTER TABLE document_chunks 
   ALTER COLUMN embedding TYPE vector(768);
   
   -- Clear existing embeddings for re-processing:
   UPDATE document_chunks SET embedding = NULL;
   ```

3. **Restart worker**:
   - Will log new configuration on startup
   - Database connection will validate before processing

## Testing Recommendations

1. **Unit Tests**:
   - Verify `EMBEDDING_DIMENSION` reads from environment
   - Mock database/Redis connections for startup validation

2. **Integration Tests**:
   - Test with valid `DATABASE_URL` and `REDIS_HOST`
   - Test with invalid URLs (should fail fast)
   - Test ORM queries match raw SQL behavior

3. **Deployment Tests**:
   - Verify logs show correct embedding configuration
   - Verify "Database connection verified" and "Redis connection verified"
   - Test with different `EMBEDDING_DIMENSION` values

## Files Modified
- `embedding_worker.py` - Added validation, improved queries, fixed imports
- `shared/models_chunk.py` - Dynamic embedding dimension
- `README.md` - Configuration and migration documentation
