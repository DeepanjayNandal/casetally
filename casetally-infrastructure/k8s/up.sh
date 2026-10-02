#!/usr/bin/env bash
#
# Bring the whole CaseTally stack up on kind, from nothing, in one command.
#
#   ./up.sh              create the cluster, deploy everything, load the corpus
#   ./up.sh --rebuild    force a rebuild of all three application images
#   ./up.sh --skip-data  deploy but leave the database empty
#
# Images are reused when the tag already exists locally, because a full rebuild
# of all three is roughly 20 minutes and almost never what you want. Pass
# --rebuild after changing application code.
#
# Safe to re-run against a cluster that already exists: cluster creation and
# every kubectl apply are idempotent, and restore-db.sh is too.

set -euo pipefail

K8S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${K8S_DIR}/../.." && pwd)"
CLUSTER="casetally"
NS="casetally"

# Tags are pinned here rather than read from the manifests, so there is exactly
# one place to bump a version and the manifests stay declarative.
IMG_BACKEND="casetally-backend:1.1.3"
IMG_WORKER="casetally-worker:0.3.1"
IMG_FRONTEND="casetally-frontend:1.1.0"

# Empty on purpose. The frontend reads this with ?? rather than ||, so an empty
# value means the bundle issues RELATIVE requests and is therefore same-origin on
# whatever host serves it. A non-empty absolute URL would hard-code one hostname
# into the bundle.
FRONTEND_BACKEND_URL=""

REBUILD=0
SKIP_DATA=0

c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_hdr=$'\033[1;36m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
T_START=$(date +%s)
phase() { printf '\n%s==> %s%s %s(+%ss)%s\n' "$c_hdr" "$*" "$c_off" "$c_dim" "$(( $(date +%s) - T_START ))" "$c_off"; }
log()   { printf '%s\n' "   $*"; }
ok()    { printf '%s   OK%s  %s\n' "$c_ok" "$c_off" "$*"; }
warn()  { printf '%s   WARN%s %s\n' "$c_warn" "$c_off" "$*"; }
die()   { printf '%s   FAIL%s %s\n' "$c_err" "$c_off" "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild)   REBUILD=1; shift ;;
    --skip-data) SKIP_DATA=1; shift ;;
    -h|--help)   sed -n '3,15p' "$0"; exit 0 ;;
    *)           die "unknown argument: $1" ;;
  esac
done

# --------------------------------------------------------------------------
phase "Preflight"
# --------------------------------------------------------------------------
for t in docker kind kubectl; do
  command -v "$t" >/dev/null || die "$t is not installed"
done
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and retry."
ok "docker, kind, kubectl present and the daemon is up"

[[ -f "${K8S_DIR}/.env.k8s" ]] || die "${K8S_DIR}/.env.k8s is missing.
       It must contain POSTGRES_PASSWORD and GROQ_API_KEY, unquoted, one per line.
       See secret.example.yaml. It is gitignored and never committed."
for k in POSTGRES_PASSWORD GROQ_API_KEY; do
  grep -q "^${k}=" "${K8S_DIR}/.env.k8s" || die "$k missing from .env.k8s"
done
ok ".env.k8s present with both required keys"

mem=$(docker info --format '{{.MemTotal}}' | awk '{printf "%.0f", $1/1048576}')
log "Docker VM memory: ${mem} MiB"
[[ "$mem" -ge 6000 ]] || warn "under 6 GiB. The stack declares ~6.7 GiB of limits and may not schedule."

# --------------------------------------------------------------------------
phase "Cluster"
# --------------------------------------------------------------------------
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  ok "cluster '$CLUSTER' already exists, reusing it"
else
  # The PDF archive is mounted by this config, so the path inside it has to
  # exist on the host before the node starts.
  archive="${REPO_ROOT}/casetally-data-archive/openrights-data-archive/uscode"
  [[ -d "$archive" ]] || die "source archive not found at:
       $archive
       kind-cluster.yaml mounts it to /data/uscode, and the API serves PDFs from there."
  log "source archive: $(du -sh "$archive" | cut -f1), $(ls "$archive"/*.pdf 2>/dev/null | wc -l | tr -d ' ') PDFs, $(ls "$archive"/*.html 2>/dev/null | wc -l | tr -d ' ') HTML"
  kind create cluster --config "${K8S_DIR}/kind-cluster.yaml" --wait 180s
  ok "cluster created"
fi
kubectl config use-context "kind-${CLUSTER}" >/dev/null
ok "context kind-${CLUSTER}"

# --------------------------------------------------------------------------
phase "Images"
# --------------------------------------------------------------------------
build_if_needed() {   # $1=tag  $2=context  $3...=extra build args
  local tag="$1" ctx="$2"; shift 2
  if [[ "$REBUILD" -eq 0 ]] && docker image inspect "$tag" >/dev/null 2>&1; then
    log "$tag already built, skipping (use --rebuild to force)"
  else
    log "building $tag ..."
    docker build --platform linux/arm64 "$@" -t "$tag" "$ctx" >/dev/null
    ok "built $tag"
  fi
}

build_if_needed "$IMG_BACKEND"  "${REPO_ROOT}/casetally-backend"
build_if_needed "$IMG_WORKER"   "${REPO_ROOT}/casetally-workers"
build_if_needed "$IMG_FRONTEND" "${REPO_ROOT}/casetally-frontend" \
                --build-arg "NEXT_PUBLIC_BACKEND_URL=${FRONTEND_BACKEND_URL}"

# `kind load` is a no-op when the node already has the image, so this is cheap on
# a re-run. It works for these because they are built single-platform; it fails
# on multi-arch registry images, which the node pulls for itself instead.
for img in "$IMG_BACKEND" "$IMG_WORKER" "$IMG_FRONTEND"; do
  # Match the repository and tag COLUMNS exactly.
  #
  # This used to be grep "${img%%:*}.*${img##*:}" over the whole crictl line,
  # which is an unanchored regex where the dots in a version are wildcards and
  # the image ID is part of the subject. Looking for casetally-frontend:1.1.0
  # matched the digest "4b7216170a135" of an unrelated 0.5.0 row, because
  # "16170" satisfies 1.1.0. The image was then reported as already present,
  # kind load was skipped, and the pod tried to pull a local-only tag from
  # Docker Hub and sat in ImagePullBackOff. Every earlier tag passed by luck.
  if docker exec "${CLUSTER}-control-plane" crictl images 2>/dev/null \
       | awk -v repo="${img%%:*}" -v tag="${img##*:}" \
             '$1 == repo || $1 == "docker.io/library/" repo { if ($2 == tag) found = 1 }
              END { exit !found }'; then
    log "$img already on the node"
  else
    kind load docker-image "$img" --name "$CLUSTER" >/dev/null 2>&1 && ok "loaded $img" \
      || die "could not load $img into the node"
  fi
done

# --------------------------------------------------------------------------
phase "Namespace, config and Secret"
# --------------------------------------------------------------------------
kubectl apply -f "${K8S_DIR}/00-namespace.yaml" \
              -f "${K8S_DIR}/01-configmap.yaml" \
              -f "${K8S_DIR}/10-postgres-init-configmap.yaml" >/dev/null
ok "namespace and ConfigMaps"

# Rendered client-side and piped into apply, so re-running does not fail with
# AlreadyExists the way a plain `kubectl create secret` would.
kubectl create secret generic casetally-secrets --namespace "$NS" \
  --from-env-file="${K8S_DIR}/.env.k8s" --dry-run=client -o yaml \
  | kubectl apply -f - >/dev/null
ok "Secret casetally-secrets (2 keys, values never printed)"

# --------------------------------------------------------------------------
phase "Postgres and Redis"
# --------------------------------------------------------------------------
kubectl apply -f "${K8S_DIR}/11-postgres-service.yaml" \
              -f "${K8S_DIR}/12-postgres-statefulset.yaml" \
              -f "${K8S_DIR}/20-redis-service.yaml" \
              -f "${K8S_DIR}/21-redis-deployment.yaml" >/dev/null
log "waiting for Postgres (first boot runs initdb plus init.sql) ..."
kubectl wait --for=condition=Ready "pod/casetally-postgres-0" -n "$NS" --timeout=600s >/dev/null
ok "Postgres Ready"
kubectl rollout status deployment/casetally-redis -n "$NS" --timeout=300s >/dev/null
ok "Redis Ready"

# --------------------------------------------------------------------------
phase "Corpus"
# --------------------------------------------------------------------------
if [[ "$SKIP_DATA" -eq 1 ]]; then
  warn "--skip-data: leaving the database empty (schema only, from init.sql)"
else
  rows=$(kubectl exec -n "$NS" casetally-postgres-0 -- \
           psql -U casetally -d casetally_law -qAtX -c "select count(*) from legal_chunks" 2>/dev/null || echo 0)
  if [[ "${rows:-0}" -gt 1000 ]]; then
    ok "database already holds ${rows} chunks, skipping restore"
  else
    # Prefer an existing dump over starting compose. The compose stack is
    # retired, so requiring it just to bring the cluster up would be a
    # dependency on the thing this replaces.
    newest=$(ls -t "${REPO_ROOT}/casetally-data-archive"/*.dump 2>/dev/null | head -1 || true)
    if [[ -n "$newest" ]]; then
      log "restoring from $(basename "$newest") ($(du -h "$newest" | cut -f1))"
      "${K8S_DIR}/restore-db.sh" --dump "$newest"
    else
      warn "no dump found in casetally-data-archive/, falling back to dumping from compose"
      "${K8S_DIR}/restore-db.sh"
    fi
  fi
fi

# --------------------------------------------------------------------------
phase "API, worker, ingress and frontend"
# --------------------------------------------------------------------------
kubectl apply -f "${K8S_DIR}/30-api-service.yaml" \
              -f "${K8S_DIR}/31-api-deployment.yaml" \
              -f "${K8S_DIR}/40-worker-deployment.yaml" \
              -f "${K8S_DIR}/60-traefik-rbac.yaml" \
              -f "${K8S_DIR}/61-traefik-deployment.yaml" \
              -f "${K8S_DIR}/62-traefik-service.yaml" \
              -f "${K8S_DIR}/70-frontend-service.yaml" \
              -f "${K8S_DIR}/71-frontend-deployment.yaml" \
              -f "${K8S_DIR}/63-ingress.yaml" >/dev/null
ok "applied"

for d in traefik casetally-api casetally-frontend casetally-worker; do
  log "waiting for $d ..."
  kubectl rollout status "deployment/$d" -n "$NS" --timeout=600s >/dev/null
  ok "$d Ready"
done

# --------------------------------------------------------------------------
phase "Smoke test through the ingress"
# --------------------------------------------------------------------------
fails=0
check() {  # $1=label  $2=expected  $3...=curl args
  local label="$1" want="$2"; shift 2
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@" || echo 000)
  if [[ "$got" == "$want" ]]; then printf '%s   OK%s  %-26s %s\n' "$c_ok" "$c_off" "$label" "$got"
  else printf '%s   FAIL%s %-26s got %s want %s\n' "$c_err" "$c_off" "$label" "$got" "$want"; fails=1; fi
}
check "GET  /"              200 http://localhost/
check "GET  /health/ready"  200 http://localhost/health/ready
check "POST /v1/search"     200 -X POST http://localhost/v1/search \
        -H 'Content-Type: application/json' -d '{"query":"copyright infringement damages","top_k":3}'

chunks=$(kubectl exec -n "$NS" casetally-postgres-0 -- \
          psql -U casetally -d casetally_law -qAtX -c \
          "select count(*)||'/'||count(distinct citation) from legal_chunks where is_current" 2>/dev/null || echo "?")
log "corpus: ${chunks} (chunks/citations)"

elapsed=$(( $(date +%s) - T_START ))
printf '\n'
if [[ "$fails" -eq 0 ]]; then
  printf '%s  CaseTally is up in %sm %ss  ->  http://localhost%s\n\n' "$c_ok" "$((elapsed/60))" "$((elapsed%60))" "$c_off"
else
  printf '%s  Up in %sm %ss but smoke tests FAILED%s\n\n' "$c_err" "$((elapsed/60))" "$((elapsed%60))" "$c_off"
  exit 1
fi
