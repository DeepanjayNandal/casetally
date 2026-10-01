#!/usr/bin/env bash
#
# Embedding worker demo harness.
#
# The corpus is 100% embedded, so the worker queue is permanently empty and
# there is nothing to show. This manufactures a backlog, lets the worker tier
# drain it, and then proves that the work was neither lost nor duplicated.
#
#   ./demo-worker.sh backlog [N]   create a backlog of N rows (default 6000)
#   ./demo-worker.sh watch         live progress, exits when the queue drains
#   ./demo-worker.sh verify        prove correctness, then drop the backup
#   ./demo-worker.sh graceful      delete a pod mid-batch
#   ./demo-worker.sh crash         SIGKILL a worker from the node
#   ./demo-worker.sh restore       put the original embeddings back and stop
#
# Typical interview flow, two terminals:
#   term1: ./demo-worker.sh backlog 6000 && ./demo-worker.sh watch
#   term2: ./demo-worker.sh graceful      (or crash)
#   term1: after watch exits -> ./demo-worker.sh verify

set -euo pipefail

NS="casetally"
PGPOD="casetally-postgres-0"
DB="casetally_law"
DB_USER="casetally"
BACKUP_TBL="embedding_demo_backup"
STATE_DIR="/tmp/casetally-demo"
SNAP="${STATE_DIR}/worker-totals.tsv"
# Pods destroyed during a demo bank their committed total here before the pod
# object disappears and its logs become unreachable.
LEDGER="${STATE_DIR}/ledger.tsv"

c_ok=$'\033[32m'; c_warn=$'\033[33m'; c_err=$'\033[31m'; c_hdr=$'\033[1;36m'; c_off=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$c_hdr" "$*" "$c_off"; }
log()  { printf '%s\n' "  $*"; }
ok()   { printf '%s  OK%s   %s\n' "$c_ok" "$c_off" "$*"; }
warn() { printf '%s  WARN%s %s\n' "$c_warn" "$c_off" "$*"; }
die()  { printf '%s  FAIL%s %s\n' "$c_err" "$c_off" "$*" >&2; exit 1; }

q() { kubectl exec -n "$NS" "$PGPOD" -- psql -U "$DB_USER" -d "$DB" -qAtX -c "$1"; }

worker_pods() {
  kubectl get pods -n "$NS" -l app.kubernetes.io/name=worker \
    --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}'
}

redis_pod() {
  kubectl get pod -n "$NS" -l app.kubernetes.io/name=redis -o jsonpath='{.items[0].metadata.name}'
}

# Read every worker's total_processed out of Redis and append to the snapshot
# file. Snapshotting matters: a worker that shuts down gracefully calls
# StateManager.cleanup(), which DELETES its metrics key, so the live value is
# gone by the time verification runs. The file keeps the last seen maximum.
snapshot() {
  mkdir -p "$STATE_DIR"
  local rp; rp="$(redis_pod)"
  kubectl exec -n "$NS" "$rp" -- sh -c '
    for k in $(redis-cli --scan --pattern "worker:embedding:*:metrics" 2>/dev/null); do
      v=$(redis-cli get "$k" 2>/dev/null)
      [ -n "$v" ] && echo "$k|$v"
    done' 2>/dev/null | python3 -c "
import sys, json, re
for line in sys.stdin:
    line = line.strip()
    if '|' not in line: continue
    key, blob = line.split('|', 1)
    m = re.match(r'worker:embedding:(.+):metrics', key)
    if not m: continue
    try:
        total = json.loads(blob).get('total_processed', 0)
    except Exception:
        continue
    print(f'{m.group(1)}\t{total}')
" >> "$SNAP" 2>/dev/null || true
}

# Sum committed rows per worker across the whole run.
#
# total_processed is an in-process counter, so it is monotonic only within one
# container lifetime. A SIGKILLed pod restarts under the SAME pod name, which
# means the same Redis key, and the counter restarts at 0. Taking a plain max
# would therefore discard either the pre-crash or the post-crash work.
#
# So treat a DECREASE as a restart boundary: bank the previous segment's peak
# and begin a new one. The worker's true contribution is the sum of its
# segments.
summarise_snapshots() {
  [[ -f "$SNAP" ]] || { echo "0"; return; }
  python3 - "$SNAP" <<'PY'
import sys, collections
banked  = collections.OrderedDict()   # worker -> committed in finished segments
current = collections.OrderedDict()   # worker -> peak of the live segment
restarts = collections.Counter()

for line in open(sys.argv[1]):
    parts = line.rstrip("\n").split("\t")
    if len(parts) != 2:
        continue
    w, t = parts[0], int(parts[1])
    prev = current.get(w)
    if prev is not None and t < prev:
        banked[w] = banked.get(w, 0) + prev   # counter reset: bank and restart
        restarts[w] += 1
        current[w] = t
    else:
        current[w] = max(prev or 0, t)

total = 0
for w in current:
    n = banked.get(w, 0) + current[w]
    total += n
    note = f"  (restarted {restarts[w]}x, segments summed)" if restarts[w] else ""
    print(f"  {w:38s} committed {n}{note}", file=sys.stderr)
print(total)
PY
}

# Rows a single container lifetime committed, read from its own log.
#
# This is the authoritative tally, not the Redis counter. Every
# "Successfully processed N chunks" line is emitted AFTER session.commit()
# returns, so a line exists if and only if those rows are durable. The Redis
# metric is sampled on a timer and is deleted outright by StateManager.cleanup()
# on graceful shutdown, so it systematically undercounts a worker that exits
# cleanly. The per-chunk retry path commits too, and logs its own total.
committed_from_log() {   # $1 = pod, $2 = "--previous" or empty
  kubectl logs "$1" -n "$NS" ${2:+$2} 2>/dev/null \
    | sed -n -e 's/.*Successfully processed \([0-9]\{1,\}\) chunks.*/\1/p' \
             -e 's/.*Per-chunk retry: \([0-9]\{1,\}\) succeeded.*/\1/p' \
    | awk '{s+=$1} END {print s+0}'
}

# Bank a pod's committed total before it is destroyed.
bank_pod() {
  mkdir -p "$STATE_DIR"
  local n prev=0
  n="$(committed_from_log "$1" "")"
  [[ "$(kubectl get pod "$1" -n "$NS" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)" -gt 0 ]] \
    && prev="$(committed_from_log "$1" "--previous")"
  printf '%s\t%s\n' "$1" "$(( n + prev ))" >> "$LEDGER"
  log "banked $(( n + prev )) committed rows for $1"
}

cmd="${1:-}"; shift || true

case "$cmd" in

backlog)
  N="${1:-6000}"
  step "Creating a backlog of $N rows"
  kubectl get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found"

  existing="$(q "select count(*) from legal_chunks where embedding is null")"
  [[ "$existing" == "0" ]] || die "queue already has $existing NULL rows. Run verify or restore first."

  if [[ "$(q "select count(*) from information_schema.tables where table_name='${BACKUP_TBL}'")" != "0" ]]; then
    die "backup table ${BACKUP_TBL} already exists. Run verify or restore first."
  fi

  # Back the originals up BEFORE nulling anything. Done inside one transaction
  # so there is no window where embeddings are gone and nothing has a copy.
  q "
    BEGIN;
    CREATE TABLE ${BACKUP_TBL} AS
      SELECT id, clause_id, embedding
        FROM legal_chunks
       WHERE is_current AND embedding IS NOT NULL
       ORDER BY id
       LIMIT ${N};
    ALTER TABLE ${BACKUP_TBL} ADD PRIMARY KEY (id);

    UPDATE legal_chunks c
       SET embedding = NULL, retry_count = 0
      FROM ${BACKUP_TBL} b
     WHERE c.id = b.id;
    COMMIT;" >/dev/null

  backed="$(q "select count(*) from ${BACKUP_TBL}")"
  nulled="$(q "select count(*) from legal_chunks where embedding is null")"
  ok "backed up $backed rows into ${BACKUP_TBL}"
  ok "queue now holds $nulled rows with embedding IS NULL"
  [[ "$backed" == "$nulled" ]] || die "backup count $backed != queue depth $nulled"
  rm -f "$SNAP" "$LEDGER"; mkdir -p "$STATE_DIR"
  log ""
  log "Workers will start draining within one poll interval (5s)."
  log "Next:  ./demo-worker.sh watch"
  ;;

watch)
  step "Draining. Ctrl-C is safe at any time."
  total="$(q "select count(*) from ${BACKUP_TBL}" 2>/dev/null || echo 0)"
  [[ "$total" != "0" ]] || die "no backup table, so nothing to watch. Run backlog first."
  printf '  %-9s %-11s %-9s %s\n' "elapsed" "remaining" "done" "rate"
  start=$(date +%s); last_done=0; last_t=$start
  while :; do
    snapshot
    remaining="$(q "select count(*) from legal_chunks where embedding is null")"
    now=$(date +%s); done=$(( total - remaining )); el=$(( now - start ))
    dt=$(( now - last_t )); dd=$(( done - last_done ))
    rate=0; [[ "$dt" -gt 0 ]] && rate=$(( dd / dt ))
    printf '  %-9s %-11s %-9s %s/s\n' "${el}s" "$remaining" "$done" "$rate"
    [[ "$remaining" == "0" ]] && break
    last_done=$done; last_t=$now
    sleep 3
  done
  snapshot
  ok "queue drained in $(( $(date +%s) - start ))s"
  log "Next:  ./demo-worker.sh verify"
  ;;

verify)
  step "Verify: nothing lost, nothing double-processed"
  [[ "$(q "select count(*) from information_schema.tables where table_name='${BACKUP_TBL}'")" != "0" ]] \
    || die "no backup table. Run backlog first."

  N="$(q "select count(*) from ${BACKUP_TBL}")"
  log "backlog size N = $N"

  failed=0

  nullrem="$(q "select count(*) from legal_chunks where embedding is null")"
  [[ "$nullrem" == "0" ]] && ok "0 rows left with embedding IS NULL" \
                          || { warn "$nullrem rows still NULL; the queue has not drained"; failed=1; }

  refilled="$(q "select count(*) from legal_chunks c join ${BACKUP_TBL} b on b.id=c.id where c.embedding is not null")"
  [[ "$refilled" == "$N" ]] && ok "all $N backlog rows were re-embedded" \
                            || { warn "only $refilled of $N re-embedded"; failed=1; }

  step "Verify: per-worker committed counts sum to exactly N"
  # Counted from each worker's own log, where a line is written only after the
  # commit returns. Live pods are read directly (plus --previous if the
  # container was restarted by a crash); pods destroyed during a demo were
  # banked to the ledger before they disappeared.
  sum=0
  for p in $(worker_pods); do
    n="$(committed_from_log "$p" "")"
    rc="$(kubectl get pod "$p" -n "$NS" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)"
    extra=0; note=""
    if [[ "${rc:-0}" -gt 0 ]]; then
      extra="$(committed_from_log "$p" "--previous")"
      note="  (restarted ${rc}x: ${extra} pre-crash + ${n} after)"
    fi
    log "$(printf '%-38s committed %s%s' "$p" "$(( n + extra ))" "$note")"
    sum=$(( sum + n + extra ))
  done
  if [[ -f "$LEDGER" ]]; then
    while IFS=$'\t' read -r wp wn; do
      [[ -n "${wp:-}" ]] || continue
      log "$(printf '%-38s committed %s  (destroyed during demo, from ledger)' "$wp" "$wn")"
      sum=$(( sum + wn ))
    done < "$LEDGER"
  fi
  log "sum of per-worker committed = $sum   (N = $N)"
  if [[ "$sum" == "$N" ]]; then
    ok "sum equals N exactly: nothing lost and nothing processed twice"
  elif [[ "$sum" -gt "$N" ]]; then
    warn "sum exceeds N by $(( sum - N )): at least one row was embedded more than once"; failed=1
  else
    warn "sum is $(( N - sum )) short of N: some committed work was not attributed"; failed=1
  fi

  log ""
  log "Cross-check against the sampled Redis counters (expected to UNDERCOUNT,"
  log "because cleanup() deletes a key on graceful exit and sampling is periodic):"
  rsum="$(summarise_snapshots)"
  log "redis-sampled sum = $rsum"

  step "Verify: re-embedded vectors match the originals (cosine similarity)"
  # Cosine similarity, not byte equality. Batch composition changes between runs
  # and transformer padding shifts the last decimal places, so identical input
  # text legitimately yields vectors that differ in the final digits while
  # pointing the same direction.
  read -r mn avg mx <<<"$(q "
    select round(min(1-(b.embedding <=> c.embedding))::numeric,8)||' '||
           round(avg(1-(b.embedding <=> c.embedding))::numeric,8)||' '||
           round(max(1-(b.embedding <=> c.embedding))::numeric,8)
      from ${BACKUP_TBL} b join legal_chunks c on c.id=b.id
     where c.embedding is not null")"
  log "min=$mn  avg=$avg  max=$mx"
  if python3 -c "import sys; sys.exit(0 if float('$mn') > 0.99999 else 1)"; then
    ok "every vector is cosine-identical to its original (min > 0.99999)"
  else
    warn "lowest similarity is $mn, below the 0.99999 threshold"; failed=1
  fi

  below="$(q "select count(*) from ${BACKUP_TBL} b join legal_chunks c on c.id=b.id
              where c.embedding is not null and (1-(b.embedding <=> c.embedding)) < 0.99999")"
  [[ "$below" == "0" ]] && ok "0 vectors drifted" || { warn "$below vectors below threshold"; failed=1; }

  step "Cleanup"
  if [[ "$failed" -eq 0 ]]; then
    q "DROP TABLE ${BACKUP_TBL};" >/dev/null
    ok "dropped ${BACKUP_TBL}"
    rm -f "$SNAP"
    printf '\n%s  DEMO VERIFIED%s\n\n' "$c_ok" "$c_off"
  else
    warn "keeping ${BACKUP_TBL} so you can inspect it. ./demo-worker.sh restore puts the originals back."
    printf '\n%s  DEMO HAD FAILURES%s\n\n' "$c_err" "$c_off"; exit 1
  fi
  ;;

graceful)
  step "Graceful shutdown demo: SIGTERM mid-batch"
  pods=($(worker_pods)); [[ "${#pods[@]}" -gt 0 ]] || die "no running worker pods"
  victim="${pods[0]}"
  log "victim: $victim"
  before="$(q "select count(*) from legal_chunks where embedding is null")"
  log "queue depth before: $before"

  # Delete without waiting, so the pod object survives long enough to read the
  # shutdown sequence out of its logs. With --wait=true the object is gone by
  # the time the command returns and the logs are unreachable, which hides the
  # very thing this demo exists to show.
  log "deleting the pod, timing termination..."
  t0=$(date +%s)
  kubectl delete pod "$victim" -n "$NS" --wait=false >/dev/null

  # Poll until the handler's own messages appear.
  for i in $(seq 1 60); do
    kubectl logs "$victim" -n "$NS" --tail=40 > "${STATE_DIR}/graceful.log" 2>/dev/null || break
    grep -q "Worker stopped gracefully" "${STATE_DIR}/graceful.log" && break
    sleep 1
  done
  # Bank its tally while the pod object still exists. After deletion its logs
  # are gone for good, and its Redis metrics key has already been removed by
  # StateManager.cleanup().
  bank_pod "$victim"
  while kubectl get pod "$victim" -n "$NS" >/dev/null 2>&1; do sleep 1; done
  t1=$(date +%s)
  ok "terminated in $(( t1 - t0 ))s (grace period is 45s; ~45s would mean SIGKILL)"

  step "What the dying worker logged"
  grep -E "Received signal|Shutting down worker|Successfully processed|stopped gracefully|State transition: .* -> stopped" \
       "${STATE_DIR}/graceful.log" | tail -10 | sed 's/^/    /' \
    || log "(nothing matched; full capture in ${STATE_DIR}/graceful.log)"
  log ""
  log "The handler sets running=False, which the loop checks at the TOP of the next"
  log "iteration, so the in-flight batch finishes and commits before exit. Rows are"
  log "not requeued because they were committed, not rolled back."
  kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=worker -n "$NS" --timeout=300s >/dev/null 2>&1 || true
  ok "replacement pod is Ready; the tier is back to $(echo $(worker_pods) | wc -w | tr -d ' ') replicas"
  ;;

crash)
  step "Crash demo: real SIGKILL mid-batch"
  pods=($(worker_pods)); [[ "${#pods[@]}" -gt 0 ]] || die "no running worker pods"
  victim="${pods[0]}"
  log "victim: $victim"

  # kubectl exec kill -9 1 does NOT work: PID 1 ignores signals sent from
  # inside its own PID namespace unless it has installed a handler for them.
  # The kill has to come from outside, so resolve the container's PID as the
  # node sees it and signal that.
  cid="$(kubectl get pod "$victim" -n "$NS" -o jsonpath='{.status.containerStatuses[0].containerID}')"
  cid="${cid#containerd://}"
  log "container id: ${cid:0:20}..."
  hostpid="$(docker exec casetally-control-plane crictl inspect "$cid" \
             | python3 -c 'import sys,json; print(json.load(sys.stdin)["info"]["pid"])')"
  log "host PID as the node sees it: $hostpid"

  before="$(q "select count(*) from legal_chunks where embedding is null")"
  log "queue depth before: $before"

  t0=$(date +%s)
  docker exec casetally-control-plane kill -9 "$hostpid"
  ok "sent SIGKILL to $hostpid. No handler runs, no commit, the open transaction is lost."

  log "waiting for the container to be restarted by the kubelet..."
  for i in $(seq 1 60); do
    rc="$(kubectl get pod "$victim" -n "$NS" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)"
    [[ "${rc:-0}" -gt 0 ]] && break
    sleep 2
  done
  ok "restartCount is now ${rc:-unknown} after $(( $(date +%s) - t0 ))s"

  step "Rollback proof"
  log "The killed worker held its rows under FOR UPDATE SKIP LOCKED from SELECT"
  log "until commit. SIGKILL drops the connection, Postgres rolls the transaction"
  log "back, the locks release, and the rows are visible as embedding IS NULL again."
  log "Another replica picks them up on its next poll. Nothing is stranded, and no"
  log "lease reaper is needed."
  log ""
  log "queue depth now: $(q "select count(*) from legal_chunks where embedding is null")"
  ;;

restore)
  step "Restoring original embeddings and removing the backlog"
  [[ "$(q "select count(*) from information_schema.tables where table_name='${BACKUP_TBL}'")" != "0" ]] \
    || die "no backup table to restore from"
  n="$(q "
    WITH upd AS (
      UPDATE legal_chunks c SET embedding = b.embedding
        FROM ${BACKUP_TBL} b WHERE c.id = b.id RETURNING 1)
    SELECT count(*) FROM upd")"
  ok "restored $n embeddings from backup"
  q "DROP TABLE ${BACKUP_TBL};" >/dev/null
  ok "dropped ${BACKUP_TBL}"
  log "NULL rows remaining: $(q "select count(*) from legal_chunks where embedding is null")"
  rm -f "$SNAP"
  ;;

*)
  sed -n '3,22p' "$0"; exit 1 ;;
esac
