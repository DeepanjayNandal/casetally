#!/usr/bin/env bash
#
# Rebuild the CaseTally database inside the kind cluster from the compose
# corpus, in one command.
#
#   ./restore-db.sh                 dump from compose, then restore
#   ./restore-db.sh --dump FILE     restore from an existing dump
#   ./restore-db.sh --verify-only   run the verification suite, change nothing
#
# The whole thing is safe to re-run. Every mutating step is either idempotent
# on its own or is preceded by the teardown that makes it so.
#
# Why a data-only restore instead of a full dump: init.sql stays the single
# source of schema truth and is exercised on every fresh cluster. Carrying the
# schema across in the dump would make the init ConfigMap dead code that
# nothing tests, and a rebuilt cluster would then differ from what the
# manifests describe.

set -euo pipefail

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
NS="casetally"
POD="casetally-postgres-0"
DB="casetally_law"
DB_USER="casetally"

COMPOSE_CTR="casetally-postgres"
COMPOSE_NET="casetally-network"

# Path prefix the cluster serves PDFs from. The kind extraMount maps the host
# archive here, and the API's hostPath volume mounts the same path, so this
# string is the contract between the database rows and the filesystem.
PDF_PREFIX="/data/uscode"

# Pinned to the same digest as the StatefulSet, so the pg_dump client that
# talks to compose is the same build as the server we restore into.
PG_IMAGE="pgvector/pgvector:pg16@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INIT_SQL="${REPO_ROOT}/casetally-db/init.sql"
ARCHIVE_DIR="${REPO_ROOT}/casetally-data-archive"

DUMP_FILE=""
VERIFY_ONLY=0

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_hdr=$'\033[1;36m'; c_off=$'\033[0m'

log()  { printf '%s\n' "  $*"; }
step() { printf '\n%s==> %s%s\n' "$c_hdr" "$*" "$c_off"; }
ok()   { printf '%s  OK%s   %s\n' "$c_ok" "$c_off" "$*"; }
warn() { printf '%s  WARN%s %s\n' "$c_warn" "$c_off" "$*"; }
die()  { printf '%s  FAIL%s %s\n' "$c_err" "$c_off" "$*" >&2; exit 1; }

# psql against the cluster. -qAtX gives bare values, suitable for capture.
kq()  { kubectl exec -n "$NS" "$POD" -- psql -U "$DB_USER" -d "$DB" -qAtX -c "$1"; }
# psql against the compose database.
cq()  { docker exec "$COMPOSE_CTR" psql -U "$DB_USER" -d "$DB" -qAtX -c "$1"; }

compose_up() { docker ps --format '{{.Names}}' | grep -qx "$COMPOSE_CTR"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump)        DUMP_FILE="${2:?--dump needs a file}"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    -h|--help)     sed -n '3,18p' "$0"; exit 0 ;;
    *)             die "unknown argument: $1" ;;
  esac
done

# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------
step "Preflight"

ctx="$(kubectl config current-context 2>/dev/null || true)"
[[ "$ctx" == "kind-casetally" ]] || die "kubectl context is '$ctx', expected 'kind-casetally'"
ok "context $ctx"

kubectl get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found. Apply the manifests first."
kubectl wait --for=condition=Ready "pod/$POD" -n "$NS" --timeout=300s >/dev/null \
  || die "$POD never became Ready"
ok "$POD is Ready"

[[ -f "$INIT_SQL" ]] || die "init.sql not found at $INIT_SQL"
ok "init.sql found"

# The CREATE INDEX is extracted from init.sql rather than written out here, so
# the rebuilt index cannot drift from the one a fresh cluster would create.
HNSW_DDL="$(perl -0777 -ne 'print $1 if /(CREATE INDEX[^;]*idx_chunks_embedding[^;]*;)/s' "$INIT_SQL")"
[[ -n "$HNSW_DDL" ]] || die "could not extract the HNSW CREATE INDEX from init.sql"
ok "HNSW DDL extracted from init.sql"

# ==========================================================================
# Verification suite. Defined before use so --verify-only can jump straight
# to it.
# ==========================================================================
verify() {
  local failed=0

  step "Verify: corpus counts"
  local want=(
    "83706|select count(*) from legal_chunks"
    "83706|select count(*) from legal_chunks where is_current"
    "0|select count(*) from legal_chunks where not is_current"
    "47207|select count(distinct citation) from legal_chunks where is_current"
    "53|select count(distinct split_part(citation,' ',1)) from legal_chunks where is_current"
    "83706|select count(*) from legal_chunks where embedding is not null"
    "0|select count(*) from legal_chunks where embedding is null"
    "26737|select count(*) from legal_artifacts"
    "1|select count(*) from users"
  )
  local row expected query actual
  for row in "${want[@]}"; do
    expected="${row%%|*}"; query="${row#*|}"
    actual="$(kq "$query")"
    if [[ "$actual" == "$expected" ]]; then
      ok "$(printf '%-6s %s' "$actual" "$query")"
    else
      warn "expected $expected, got $actual  ::  $query"; failed=1
    fi
  done

  step "Verify: HNSW index present and valid"
  local idx
  idx="$(kq "select am.amname||' valid='||i.indisvalid||' ready='||i.indisready||' opts='||coalesce(array_to_string(c.reloptions,','),'none')
             from pg_index i join pg_class c on c.oid=i.indexrelid join pg_am am on am.oid=c.relam
             where c.relname='idx_chunks_embedding'")"
  if [[ "$idx" == "hnsw valid=true ready=true opts=m=16,ef_construction=64" ]]; then
    ok "$idx"
  else
    warn "unexpected index state: ${idx:-MISSING}"; failed=1
  fi

  step "Verify: sequences ahead of max(id)"
  local seq
  for seq in legal_chunks legal_artifacts; do
    local lv mx
    lv="$(kq "select last_value from ${seq}_id_seq")"
    mx="$(kq "select coalesce(max(id),0) from ${seq}")"
    if [[ "$lv" -ge "$mx" ]]; then ok "${seq}_id_seq last_value=$lv >= max(id)=$mx"
    else warn "${seq}_id_seq last_value=$lv < max(id)=$mx"; failed=1; fi
  done

  step "Verify: corpus checksums"
  local k_chunks k_embed
  k_chunks="$(kq "select md5(string_agg(clause_id||version_hash,'' order by clause_id)) from legal_chunks")"
  k_embed="$(kq "select md5(string_agg(clause_id||embedding::text,'' order by clause_id)) from legal_chunks where embedding is not null")"
  log "chunks     $k_chunks"
  log "embeddings $k_embed"
  if compose_up; then
    local c_chunks c_embed
    c_chunks="$(cq "select md5(string_agg(clause_id||version_hash,'' order by clause_id)) from legal_chunks")"
    c_embed="$(cq "select md5(string_agg(clause_id||embedding::text,'' order by clause_id)) from legal_chunks where embedding is not null")"
    [[ "$k_chunks" == "$c_chunks" ]] && ok "chunk checksum matches compose"     || { warn "chunk checksum DIFFERS from compose"; failed=1; }
    [[ "$k_embed"  == "$c_embed"  ]] && ok "embedding checksum matches compose" || { warn "embedding checksum DIFFERS from compose"; failed=1; }
  else
    warn "compose is not running, skipping the cross-database checksum comparison"
  fi

  step "Verify: PDF paths rewritten"
  local total rewritten stale
  total="$(kq "select count(*) from legal_artifacts where artifact_metadata ? 'file_path'")"
  rewritten="$(kq "select count(*) from legal_artifacts where artifact_metadata->>'file_path' like '${PDF_PREFIX}/%'")"
  stale="$(kq "select count(*) from legal_artifacts where artifact_metadata ? 'file_path' and artifact_metadata->>'file_path' not like '${PDF_PREFIX}/%'")"
  [[ "$rewritten" == "$total" ]] && ok "$rewritten/$total paths under $PDF_PREFIX" || { warn "only $rewritten/$total rewritten"; failed=1; }
  [[ "$stale" == "0" ]] && ok "0 rows retain the old prefix" || { warn "$stale rows still hold a non-cluster path"; failed=1; }

  # Condition 5: the paths must not merely look right, the bytes must be
  # reachable from inside a pod. The Postgres pod does not mount the archive,
  # so this runs a throwaway pod carrying the same hostPath the API will use.
  step "Verify: rewritten paths resolve inside a pod"
  local sample
  sample="$(kq "select string_agg(p,' ') from (select distinct artifact_metadata->>'file_path' p from legal_artifacts order by 1 limit 5) s")"
  if [[ -z "$sample" ]]; then
    warn "no sample paths to check"; failed=1
  else
    kubectl delete pod pdf-check -n "$NS" --ignore-not-found >/dev/null 2>&1
    cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata: { name: pdf-check, namespace: $NS }
spec:
  restartPolicy: Never
  containers:
    - name: check
      image: busybox:1.36
      command: ["sh","-c","for f in $sample; do [ -f \"\$f\" ] && echo \"FOUND \$f\" || echo \"MISSING \$f\"; done; echo COUNT=\$(ls $PDF_PREFIX | wc -l)"]
      volumeMounts:
        - { name: pdfs, mountPath: $PDF_PREFIX, readOnly: true }
  volumes:
    - name: pdfs
      hostPath: { path: $PDF_PREFIX, type: Directory }
EOF
    kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/pdf-check -n "$NS" --timeout=120s >/dev/null 2>&1 || true
    local out
    out="$(kubectl logs pdf-check -n "$NS" 2>&1 || true)"
    kubectl delete pod pdf-check -n "$NS" --ignore-not-found >/dev/null 2>&1
    printf '%s\n' "$out" | sed 's/^/    /'
    if printf '%s' "$out" | grep -q MISSING || [[ -z "$out" ]]; then
      warn "at least one sampled PDF is not readable inside a pod"; failed=1
    else
      ok "all sampled PDFs resolve under $PDF_PREFIX"
    fi
  fi

  step "Verify: live hybrid query"
  kq "select clause_id||'  '||round(ts_rank_cd(search_vector, plainto_tsquery('english','copyright infringement damages'))::numeric,8)
      from legal_chunks
      where is_current and search_vector @@ plainto_tsquery('english','copyright infringement damages')
      order by ts_rank_cd(search_vector, plainto_tsquery('english','copyright infringement damages')) desc, clause_id
      limit 3" | sed 's/^/    /'

  if [[ "$failed" -eq 0 ]]; then
    printf '\n%s  ALL CHECKS PASSED%s\n\n' "$c_ok" "$c_off"
  else
    printf '\n%s  ONE OR MORE CHECKS FAILED%s\n\n' "$c_err" "$c_off"; return 1
  fi
}

if [[ "$VERIFY_ONLY" -eq 1 ]]; then verify; exit $?; fi

# --------------------------------------------------------------------------
# 1. Dump
# --------------------------------------------------------------------------
if [[ -n "$DUMP_FILE" ]]; then
  step "Dump: reusing $DUMP_FILE"
  [[ -f "$DUMP_FILE" ]] || die "dump file not found: $DUMP_FILE"
  ok "$(du -h "$DUMP_FILE" | cut -f1) on disk"
else
  step "Dump: from the compose database"
  compose_up || die "compose container '$COMPOSE_CTR' is not running. Start it with:
      docker compose -f docker-compose.local.yml --env-file .env.local up -d postgres"

  PW="$(grep '^POSTGRES_PASSWORD=' "$REPO_ROOT/.env.local" | cut -d= -f2-)"
  [[ -n "$PW" ]] || die "POSTGRES_PASSWORD not found in $REPO_ROOT/.env.local"

  mkdir -p "$ARCHIVE_DIR"
  DUMP_FILE="${ARCHIVE_DIR}/casetally-$(date +%Y%m%d-%H%M%S).dump"

  # The pg16 client against the 15.4 server. Newer client to older server is
  # the supported direction; the reverse is not.
  docker run --rm --network "$COMPOSE_NET" \
    -e PGPASSWORD="$PW" -v "$ARCHIVE_DIR":/out "$PG_IMAGE" \
    pg_dump -h "$COMPOSE_CTR" -U "$DB_USER" -d "$DB" \
            --data-only --no-owner --no-privileges --format=custom \
            -f "/out/$(basename "$DUMP_FILE")"
  ok "wrote $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
fi

# --------------------------------------------------------------------------
# 2. Copy into the pod
# --------------------------------------------------------------------------
step "Copy the dump into $POD"
kubectl cp "$DUMP_FILE" "$NS/$POD:/tmp/restore.dump"
host_md5="$(md5 -q "$DUMP_FILE" 2>/dev/null || md5sum "$DUMP_FILE" | awk '{print $1}')"
pod_md5="$(kubectl exec -n "$NS" "$POD" -- md5sum /tmp/restore.dump | awk '{print $1}')"
[[ "$host_md5" == "$pod_md5" ]] || die "dump corrupted in transit: $host_md5 != $pod_md5"
ok "md5 verified on both sides: $host_md5"

# --------------------------------------------------------------------------
# 3. Prepare the target
# --------------------------------------------------------------------------
step "Prepare: drop the HNSW index, clear the seeded admin row"
# Dropping the index before a bulk load is the point of this whole ordering.
# Inserting 83,706 vectors into a live HNSW index maintains the graph one row
# at a time, which is far slower and yields a worse-connected graph than a
# single bulk build afterwards.
#
# users already holds the admin row that init.sql seeds, and the dump carries
# that same row with the same id, so the COPY would abort on a primary key
# conflict. CASCADE reaches search_queries and notifications, both of which the
# dump repopulates.
kq "DROP INDEX IF EXISTS idx_chunks_embedding;
    TRUNCATE users RESTART IDENTITY CASCADE;" >/dev/null
ok "index dropped, users cleared"

# --------------------------------------------------------------------------
# 4. Restore
# --------------------------------------------------------------------------
step "Restore (single transaction, triggers left enabled)"
# Triggers stay on deliberately. trigger_chunks_search_vector fires on INSERT
# and recomputes search_vector with PostgreSQL 16's dictionary rather than
# carrying 15.4's output across. trigger_chunks_updated_at is BEFORE UPDATE
# only (tgtype 19), so it never fires here and original updated_at values
# survive untouched.
time kubectl exec -n "$NS" "$POD" -- \
  pg_restore -U "$DB_USER" -d "$DB" --data-only --no-owner --single-transaction \
  /tmp/restore.dump
ok "restore complete"

kubectl exec -n "$NS" "$POD" -- rm -f /tmp/restore.dump
ok "dump removed from the pod"

# --------------------------------------------------------------------------
# 5. Artifact checksum against compose, BEFORE the path rewrite
# --------------------------------------------------------------------------
# Once paths are rewritten the two databases legitimately differ, so this is
# the only moment the artifact tables can be compared meaningfully.
step "Checksum legal_artifacts against compose (pre-rewrite)"
ART_Q="select md5(string_agg(citation||artifact_type||version_hash||artifact_metadata::text, '' order by id)) from legal_artifacts"
k_art="$(kq "$ART_Q")"
log "k8s     $k_art"
if compose_up; then
  c_art="$(cq "$ART_Q")"
  log "compose $c_art"
  [[ "$k_art" == "$c_art" ]] || die "legal_artifacts differ from compose BEFORE any rewrite. Restore is not faithful; stopping."
  ok "legal_artifacts is a faithful copy of compose"
else
  warn "compose not running, cannot compare legal_artifacts. Continuing."
fi

# --------------------------------------------------------------------------
# 6. Rewrite PDF paths
# --------------------------------------------------------------------------
step "Rewrite PDF paths to $PDF_PREFIX"

# Guard first. Every row must live in exactly one source directory. If the
# corpus ever spans more than one, a blind basename rewrite would silently
# collapse two different files that share a name.
ndirs="$(kq "select count(distinct regexp_replace(artifact_metadata->>'file_path','/[^/]+$','')) from legal_artifacts where artifact_metadata ? 'file_path'")"
nomissing="$(kq "select count(*) from legal_artifacts where not (artifact_metadata ? 'file_path')")"
nbasenames="$(kq "select count(distinct regexp_replace(artifact_metadata->>'file_path','^.*/','')) from legal_artifacts where artifact_metadata ? 'file_path'")"
log "distinct source directories : $ndirs"
log "distinct file names         : $nbasenames"
log "rows without a file_path    : $nomissing"
[[ "$ndirs" == "1" ]] || die "paths span $ndirs directories, expected exactly 1. Refusing to rewrite; inspect the data."
[[ "$nomissing" == "0" ]] || die "$nomissing artifact rows have no file_path. Refusing to rewrite."
ok "all paths share a single source directory"

# Idempotent by construction: the NOT LIKE guard means a second run matches
# zero rows. It is also independent of the source prefix, so it works whether
# the dump came from this machine or another one.
updated="$(kq "
  WITH upd AS (
    UPDATE legal_artifacts
       SET artifact_metadata = jsonb_set(
             artifact_metadata, '{file_path}',
             to_jsonb('${PDF_PREFIX}/' || regexp_replace(artifact_metadata->>'file_path', '^.*/', '')))
     WHERE artifact_metadata ? 'file_path'
       AND artifact_metadata->>'file_path' NOT LIKE '${PDF_PREFIX}/%'
    RETURNING 1)
  SELECT count(*) FROM upd")"
ok "rewrote $updated rows"

again="$(kq "
  WITH upd AS (
    UPDATE legal_artifacts
       SET artifact_metadata = jsonb_set(
             artifact_metadata, '{file_path}',
             to_jsonb('${PDF_PREFIX}/' || regexp_replace(artifact_metadata->>'file_path', '^.*/', '')))
     WHERE artifact_metadata ? 'file_path'
       AND artifact_metadata->>'file_path' NOT LIKE '${PDF_PREFIX}/%'
    RETURNING 1)
  SELECT count(*) FROM upd")"
[[ "$again" == "0" ]] && ok "idempotency confirmed: a second pass changed 0 rows" \
                      || die "rewrite is not idempotent, second pass changed $again rows"

# --------------------------------------------------------------------------
# 7. Rebuild the HNSW index
# --------------------------------------------------------------------------
step "Rebuild the HNSW index using init.sql's own DDL"
printf '%s\n' "$HNSW_DDL" | sed 's/^/    /'
time kubectl exec -n "$NS" "$POD" -- psql -U "$DB_USER" -d "$DB" -v ON_ERROR_STOP=1 \
  -c "SET maintenance_work_mem='512MB'; SET max_parallel_maintenance_workers=2; $HNSW_DDL" >/dev/null
ok "index built"

step "ANALYZE"
kq "ANALYZE;" >/dev/null
ok "statistics refreshed"

# --------------------------------------------------------------------------
# 8. Verify
# --------------------------------------------------------------------------
verify
