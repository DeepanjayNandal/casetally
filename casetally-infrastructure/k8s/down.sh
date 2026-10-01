#!/usr/bin/env bash
#
# Tear the CaseTally cluster down.
#
#   ./down.sh            delete the kind cluster (the database goes with it)
#   ./down.sh --keep-data  delete the workloads but leave the cluster and PVC
#
# What survives either way: the built images in Docker, the source archive on
# disk, and the dumps in casetally-data-archive/. So `./up.sh` afterwards is fast
# and does not need the retired compose stack.

set -euo pipefail

K8S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${K8S_DIR}/../.." && pwd)"
CLUSTER="casetally"
NS="casetally"

c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_hdr=$'\033[1;36m'; c_off=$'\033[0m'
phase() { printf '\n%s==> %s%s\n' "$c_hdr" "$*" "$c_off"; }
log()   { printf '%s\n' "   $*"; }
ok()    { printf '%s   OK%s  %s\n' "$c_ok" "$c_off" "$*"; }
warn()  { printf '%s   WARN%s %s\n' "$c_warn" "$c_off" "$*"; }

KEEP_DATA=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-data) KEEP_DATA=1; shift ;;
    -h|--help)   sed -n '3,12p' "$0"; exit 0 ;;
    *)           echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  ok "cluster '$CLUSTER' does not exist, nothing to do"
  exit 0
fi

if [[ "$KEEP_DATA" -eq 1 ]]; then
  phase "Removing workloads, keeping the cluster and the PVC"
  # Postgres is deliberately left alone: deleting the StatefulSet would orphan
  # the PVC, and deleting the PVC destroys the restored corpus.
  kubectl delete deployment casetally-api casetally-frontend casetally-worker traefik \
    -n "$NS" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete job casetally-ingestion -n "$NS" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete ingress casetally -n "$NS" --ignore-not-found >/dev/null 2>&1 || true
  ok "workloads removed"
  log "Postgres, Redis and the PVC are still running. Bring the rest back with ./up.sh"
  exit 0
fi

phase "Deleting the cluster"
rows=$(kubectl exec -n "$NS" casetally-postgres-0 -- \
        psql -U casetally -d casetally_law -qAtX -c "select count(*) from legal_chunks" 2>/dev/null || echo "?")
warn "this destroys the PVC and the ${rows} chunks in it"
dumps=$(ls "${REPO_ROOT}/casetally-data-archive"/*.dump 2>/dev/null | wc -l | tr -d ' ')
if [[ "${dumps:-0}" -gt 0 ]]; then
  log "${dumps} dump(s) remain in casetally-data-archive/, so ./up.sh can restore without compose"
else
  warn "no dump in casetally-data-archive/. ./up.sh will need the compose database to rebuild the corpus."
fi

kind delete cluster --name "$CLUSTER"
ok "cluster deleted"
log "Images, the source archive and the dumps are untouched."
log "Bring it back with: ./up.sh"
