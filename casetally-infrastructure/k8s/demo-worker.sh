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
# Without arguments: prints the total to stdout and a per-pod breakdown to stderr,
# which is what the cross-check wants. With --per-pod: prints "pod<TAB>count" rows
# to stdout and nothing else, so the caller can fold them into a sum.
summarise_snapshots() {
  [[ -f "$SNAP" ]] || { [[ "${1:-}" == "--per-pod" ]] || echo "0"; return; }
  SNAP_MODE="${1:-total}" python3 - "$SNAP" <<'PY'
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

import os
per_pod = os.environ.get("SNAP_MODE") == "--per-pod"

total = 0
for w in current:
    n = banked.get(w, 0) + current[w]
    total += n
    if per_pod:
        print(f"{w}\t{n}")
    else:
        note = f"  (restarted {restarts[w]}x, segments summed)" if restarts[w] else ""
        print(f"  {w:38s} committed {n}{note}", file=sys.stderr)
if not per_pod:
    print(total)
PY
}

# The durable per-pod committed tally.
#
# This is the primary accounting source. The worker does an HINCRBY on this hash
# after every commit returns, the hash has no TTL, and nothing deletes it on
# shutdown, so a pod that KEDA scales away leaves its total behind. That is the
# property the log-based tally lacks: logs disappear with the pod.
#
# Caveat worth knowing before a demo: the hash lives in Redis, which runs with no
# persistence and a Recreate strategy. A Redis restart mid-run resets the tally to
# zero and the sum will come up short even though no rows were lost.
committed_hash() {   # prints "pod<TAB>count" rows
  # hgetall returns field and value on alternate lines, so pair them up.
  kubectl exec -n "$NS" "$(redis_pod)" -- \
    redis-cli hgetall worker:embedding:committed 2>/dev/null \
    | awk 'NR%2{f=$0;next}{print f"\t"$0}'
}

committed_hash_reset() {
  kubectl exec -n "$NS" "$(redis_pod)" -- \
    redis-cli del worker:embedding:committed >/dev/null 2>&1 || true
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
  # The durable tally is cumulative and has no TTL, so the previous run's
  # totals have to be cleared here. This is the only point at which they stop
  # being meaningful.
  committed_hash_reset
  ok "reset the durable committed tally (worker:embedding:committed)"
  log ""
  paused="$(kubectl get scaledobject casetally-worker -n "$NS" \
             -o jsonpath='{.metadata.annotations.autoscaling\.keda\.sh/paused-replicas}' 2>/dev/null || true)"
  if [[ -n "$paused" ]]; then
    warn "the ScaledObject is PAUSED at $paused replicas, so nothing will drain."
    warn "unpause:  kubectl annotate scaledobject casetally-worker -n $NS autoscaling.keda.sh/paused-replicas-"
  else
    log "There are currently $(kubectl get deploy casetally-worker -n "$NS" -o jsonpath='{.spec.replicas}') worker replicas."
    log "KEDA polls the queue every 10s and will scale the tier up on its own:"
    log "  ${N} rows / targetQueryValue 1000 -> $(( (N + 999) / 1000 )) replicas, capped at 3."
    log "Nothing here scales by hand."
  fi
  log "Next:  ./demo-worker.sh watch"
  ;;

watch)
  step "Draining. Ctrl-C is safe at any time."
  total="$(q "select count(*) from ${BACKUP_TBL}" 2>/dev/null || echo 0)"
  [[ "$total" != "0" ]] || die "no backup table, so nothing to watch. Run backlog first."
  # The replica and ready columns are the point of this view now: the tier is
  # scaled by KEDA from queue depth, so you watch it climb 0 -> 3 and fall back to
  # 0 without anyone touching kubectl.
  printf '  %-9s %-11s %-9s %-8s %-6s %s\n' "elapsed" "remaining" "done" "rate" "repl" "ready"
  start=$(date +%s); last_done=0; last_t=$start
  t_first=""; t_max=""; t_drained=""
  while :; do
    snapshot
    remaining="$(q "select count(*) from legal_chunks where embedding is null")"
    repl="$(kubectl get deploy casetally-worker -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo '?')"
    ready="$(kubectl get deploy casetally-worker -n "$NS" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)"
    ready="${ready:-0}"
    now=$(date +%s); done=$(( total - remaining )); el=$(( now - start ))
    dt=$(( now - last_t )); dd=$(( done - last_done ))
    rate=0; [[ "$dt" -gt 0 ]] && rate=$(( dd / dt ))
    printf '  %-9s %-11s %-9s %-8s %-6s %s\n' "${el}s" "$remaining" "$done" "${rate}/s" "$repl" "$ready"
    [[ -z "$t_first"   && "$done" -gt 0      ]] && t_first=$el
    [[ -z "$t_max"     && "$ready" -ge 3     ]] && t_max=$el
    [[ "$remaining" == "0" ]] && { t_drained=$el; break; }
    last_done=$done; last_t=$now
    sleep 3
  done
  snapshot
  ok "queue drained in ${t_drained}s"
  log "  first row processed at   ${t_first:-n/a}s   (cold start: pod pull, model load, first claim)"
  log "  reached 3 ready replicas at ${t_max:-never}s"

  # Scale-down is the other half of the story, and it is the half people forget
  # to show. KEDA waits cooldownPeriod with the queue below the activation
  # threshold before going to zero.
  step "Waiting for KEDA to scale back to zero (cooldownPeriod 60s)"
  z=$(date +%s)
  while :; do
    repl="$(kubectl get deploy casetally-worker -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo '?')"
    el=$(( $(date +%s) - z ))
    printf '  %-9s replicas=%s\n' "${el}s" "$repl"
    [[ "$repl" == "0" ]] && { ok "back to zero ${el}s after the queue emptied"; break; }
    [[ "$el" -gt 300 ]] && { warn "still at $repl after ${el}s, giving up on the wait"; break; }
    sleep 10
  done
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
  # Primary source: the durable Redis hash the worker HINCRBYs after each commit
  # returns. It has no TTL and nothing deletes it on shutdown, so pods that KEDA
  # scaled away still appear here. That is the whole reason it exists: the
  # log-based tally below cannot see them, because their logs left with the pod.
  sum=0; rows=0
  while IFS=$'\t' read -r wp wn; do
    [[ -n "${wp:-}" && -n "${wn:-}" ]] || continue
    log "$(printf '%-38s committed %s' "$wp" "$wn")"
    sum=$(( sum + wn )); rows=$(( rows + 1 ))
  done < <(committed_hash)

  if [[ "$rows" == "0" ]]; then
    warn "the durable tally is empty. Either no work ran, or Redis was restarted"
    warn "and took the counter with it (no persistence, Recreate strategy)."
  fi
  log "sum of per-worker committed = $sum   (N = $N)"
  if [[ "$sum" == "$N" ]]; then
    ok "sum equals N exactly: nothing lost and nothing processed twice"
  elif [[ "$sum" -gt "$N" ]]; then
    warn "sum exceeds N by $(( sum - N )): at least one row was embedded more than once"; failed=1
  else
    warn "sum is $(( N - sum )) short of N. A Redis restart mid-run would do this"
    warn "without any row being lost; the row-level checks above are the authority."
    failed=1
  fi

  log ""
  log "Cross-check, read from each surviving worker's own log. A log line is"
  log "written only after the commit returns, so this cannot overcount, but it"
  log "only covers pods that still exist:"
  logsum=0
  for p in $(worker_pods); do
    n="$(committed_from_log "$p" "")"
    rc="$(kubectl get pod "$p" -n "$NS" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || echo 0)"
    extra=0; note=""
    if [[ "${rc:-0}" -gt 0 ]]; then
      extra="$(committed_from_log "$p" "--previous")"
      note="  (restarted ${rc}x: ${extra} pre-crash + ${n} after)"
    fi
    log "$(printf '%-38s committed %s%s' "$p" "$(( n + extra ))" "$note")"
    logsum=$(( logsum + n + extra ))
  done
  if [[ -f "$LEDGER" ]]; then
    while IFS=$'\t' read -r wp wn; do
      [[ -n "${wp:-}" ]] || continue
      log "$(printf '%-38s committed %s  (destroyed by this script, from ledger)' "$wp" "$wn")"
      logsum=$(( logsum + wn ))
    done < "$LEDGER"
  fi
  log "log-based sum = $logsum of $N   (expected to be short by whatever KEDA scaled away)"

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
