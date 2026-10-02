# CaseTally on Kubernetes (local)

Local Kubernetes deployment of CaseTally, running on kind. No cloud and no Helm:
plain manifests applied with `kubectl`, so every object is readable in the file
that creates it. KEDA is installed from its vendored release manifest, pinned by
digest, for worker autoscaling.

## Service Summary

- Cluster: kind, single node, context `kind-casetally`
- Namespace: `casetally`
- Database: PostgreSQL 16.15 with pgvector 0.8.6, StatefulSet, 8Gi PVC
- Cache: Redis 7.4.11, Deployment, no persistence
- API: FastAPI on uvicorn, Deployment, 2 replicas
- Worker: embedding worker, Deployment, autoscaled 0-3 by KEDA on queue depth, no Service
- Ingestion: one-shot Job, parallelism 1, advisory-locked
- Frontend: Next.js standalone, Deployment, 2 replicas
- Ingress: Traefik 3.3.7, hostPort 80/443, single host path-based routing

Reachable at **http://localhost** once the cluster is up.
- Corpus: 83,706 chunks, 47,207 citations, 53 titles, 100% embedded
- Source PDFs: mounted read-only at `/data/uscode`

The docker compose stack stays available until it is retired. The two run side
by side: kind binds host ports 80 and 443, compose uses 3000, 3001, 5433 and
6380.

## Prerequisites

| Tool | Version used |
| --- | --- |
| Docker Desktop | 29.8.1 (7.75 GiB VM) |
| kind | v0.33.0 |
| kubectl | v1.36.1 |
| node image | kindest/node:v1.36.4 (pinned by digest) |

## Files

Numeric prefixes show dependency order. Do not run `kubectl apply -f .` on this
directory: it also holds `kind-cluster.yaml`, which is a kind object rather than
a Kubernetes one, and `secret.example.yaml`, which must never be applied. Use
the explicit list below.

| File | Purpose |
| --- | --- |
| `kind-cluster.yaml` | Cluster config: ports 80 and 443, `ingress-ready=true`, PDF mount |
| `00-namespace.yaml` | Namespace `casetally` |
| `01-configmap.yaml` | All non-secret config, for every component |
| `10-postgres-init-configmap.yaml` | Generated from `casetally-db/init.sql` |
| `11-postgres-service.yaml` | Headless Service for Postgres |
| `12-postgres-statefulset.yaml` | Postgres 16 with pgvector, 1 replica, PVC |
| `20-redis-service.yaml` | ClusterIP Service for Redis |
| `21-redis-deployment.yaml` | Redis 7, 1 replica, no persistence |
| `30-api-service.yaml` | ClusterIP Service for the API |
| `31-api-deployment.yaml` | FastAPI on uvicorn, 2 replicas, PDF mount |
| `40-worker-deployment.yaml` | Embedding worker, no Service, no `replicas` (KEDA owns it) |
| `41-worker-scaledobject.yaml` | ScaledObject + TriggerAuthentication for the worker |
| `keda/keda-2.21.0.yaml` | Vendored KEDA release, images pinned by digest |
| `keda/keda-resource-limits.yaml` | JSON patch trimming KEDA memory limits to 192Mi |
| `50-ingestion-job.yaml` | One-shot US Code ingestion Job |
| `60-traefik-rbac.yaml` | ServiceAccount, ClusterRole, binding |
| `61-traefik-deployment.yaml` | Traefik controller, hostPort 80/443 |
| `62-traefik-service.yaml` | IngressClass and ClusterIP Service |
| `63-ingress.yaml` | Path-based routing rules |
| `70-frontend-service.yaml` | ClusterIP Service for the frontend |
| `71-frontend-deployment.yaml` | Next.js standalone, 2 replicas |
| `demo-worker.sh` | Backlog, drain, failure demos, correctness proof |
| `restore-db.sh` | Rebuilds the database from the compose corpus |
| `secret.example.yaml` | Secret shape. Documentation only, never applied |
| `.env.k8s` | Gitignored. Real credentials |

## Running It

```bash
# 1. Cluster
kind create cluster --config casetally-infrastructure/k8s/kind-cluster.yaml

cd casetally-infrastructure/k8s

# 2. Namespace and config
kubectl apply -f 00-namespace.yaml -f 01-configmap.yaml \
              -f 10-postgres-init-configmap.yaml

# 3. Secret. See "Secrets" below. .env.k8s must exist first
kubectl create secret generic casetally-secrets --namespace casetally \
  --from-env-file=.env.k8s --dry-run=client -o yaml | kubectl apply -f -

# 4. Postgres and Redis
kubectl apply -f 11-postgres-service.yaml -f 12-postgres-statefulset.yaml \
              -f 20-redis-service.yaml    -f 21-redis-deployment.yaml

kubectl wait --for=condition=Ready pod/casetally-postgres-0 \
  -n casetally --timeout=600s

# 5. Load the corpus
./restore-db.sh

# 6. Build and load the API image, then deploy it
docker build --platform linux/arm64 -t casetally-backend:0.2.0 ../../casetally-backend
kind load docker-image casetally-backend:0.2.0 --name casetally
kubectl apply -f 30-api-service.yaml -f 31-api-deployment.yaml

# 7. KEDA, then the worker and its ScaledObject
kubectl apply --server-side -f keda/keda-2.21.0.yaml
kubectl apply -f 40-worker-deployment.yaml -f 41-worker-scaledobject.yaml

# 8. Frontend image. The ingress origin is baked in at build time
docker build --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_BACKEND_URL=http://localhost \
  -t casetally-frontend:0.3.0 ../../casetally-frontend
kind load docker-image casetally-frontend:0.3.0 --name casetally

# 9. Ingress and frontend
kubectl apply -f 60-traefik-rbac.yaml -f 61-traefik-deployment.yaml \
              -f 62-traefik-service.yaml \
              -f 70-frontend-service.yaml -f 71-frontend-deployment.yaml \
              -f 63-ingress.yaml
```

Then open **http://localhost**.

Reach the API with a port-forward:

```bash
kubectl port-forward -n casetally svc/casetally-api 3001:3001
curl localhost:3001/health/ready
```

Tear down with `kind delete cluster --name casetally`. That deletes the PVC and
the database with it. Rebuilding from scratch takes about three minutes.

## Rebuilding the Database

`restore-db.sh` is the only thing you need to get a populated database back:

```bash
./restore-db.sh                 # dump from compose, then restore
./restore-db.sh --dump FILE     # restore from an existing dump
./restore-db.sh --verify-only   # run the checks, change nothing
```

It is safe to re-run. In order it dumps from compose using the pg16 client,
copies the dump into the pod and checks the md5 on both sides, drops the HNSW
index, truncates `users`, restores in a single transaction, compares the
`legal_artifacts` checksum against compose, rewrites PDF paths, rebuilds the
index using the `CREATE INDEX` statement read out of `init.sql`, runs `ANALYZE`,
and then verifies counts, index validity, sequences, checksums, path rewriting,
file readability inside a pod, and a live hybrid query.

The verification suite fails loudly rather than exiting zero on a bad restore,
so the script doubles as a test.

## Secrets

Two values are secret: `POSTGRES_PASSWORD` and `GROQ_API_KEY`. Everything else
lives in `01-configmap.yaml`.

`DATABASE_URL` is deliberately not a Secret. It embeds the password, so it looks
like one, but storing it would put that password in two places where they could
drift apart. The API Deployment assembles the URL instead, using Kubernetes
`$(VAR)` interpolation over `POSTGRES_PASSWORD`. See "API Notes" below.

No file containing a live credential exists in the manifest tree. The Secret is
built from `.env.k8s`, which `casetally-infrastructure/.gitignore` already
excludes through its `.env.*` rule. You can confirm this:

```bash
git check-ignore -v casetally-infrastructure/k8s/.env.k8s
git add -n casetally-infrastructure/k8s/    # .env.k8s must not appear
```

Two things that will bite you:

- Do not quote values in `.env.k8s`. The `--from-env-file` parser is not a
  shell. `FOO="bar"` becomes the literal value `"bar"` with the quotes
  included, and Postgres then rejects the password. Blank lines and `#`
  comments are skipped normally.
- Do not point `--from-env-file` at `.env.local`. That file has eight keys, and
  six of them are ordinary config such as `GROQ_MODEL` and `EMBEDDING_MODEL`.
  They would end up in the Secret instead of the ConfigMap, and its connection
  details describe compose rather than the cluster.

## PDF Access

The API serves source PDFs with `FileResponse` on whatever absolute path the
database holds, so those files have to be reachable from inside a pod. Rather
than change application code, the path itself was made resolvable:

- `kind-cluster.yaml` mounts the host archive directory to `/data/uscode` on
  the node, read-only.
- Pods mount `/data/uscode` from the node with a read-only `hostPath` volume.
- `restore-db.sh` rewrites all 26,737 `artifact_metadata->>'file_path'` values
  to `/data/uscode/<filename>` after every restore.

The rewrite is idempotent, because it only touches rows whose path is not
already under `/data/uscode`, and it is independent of the source prefix, so a
dump taken on another machine restores correctly too. It refuses to run if the
paths span more than one source directory, since a basename-only rewrite would
then be able to collapse two different files that share a name.

The result is that the only machine-specific path in the whole repository lives
in `kind-cluster.yaml`, which is a local development file by nature. The
database rows and the pod specs both refer to `/data/uscode`, so the
application manifests stay portable.

Read-only is enforced twice, at the kind mount and again at the pod volume.
Nothing in CaseTally writes to the archive.

**Coverage is partial.** Only 25 distinct PDFs are referenced, covering 25 of
the 53 titles. 24,596 of 47,207 citations have an artifact row; the other
22,611 have none. This is a gap in the ingested data, not in the mount: all 25
referenced files are present and readable. Expect source links to be missing
for roughly half the corpus.

## Design Notes

**Stock image plus a ConfigMap, not the custom `casetally-db` image.** Compose
builds its database from `casetally-db/Dockerfile`, which uses
`ankane/pgvector:latest`. That repository is retired and frozen at PostgreSQL
15.4 with pgvector 0.5.1. Mounting `init.sql` from a ConfigMap lets the cluster
run the stock, maintained `pgvector/pgvector:pg16` image with no custom build
step. The schema becomes data mounted into a standard image instead of a layer
baked into a bespoke one.

**The init ConfigMap is generated, not transcribed.** `init.sql` is 358 lines.
A hand-copied YAML version would drift the first time the schema changed.
Regenerate it after any schema change:

```bash
kubectl create configmap casetally-postgres-init \
  --namespace casetally \
  --from-file=init.sql=casetally-db/init.sql \
  --dry-run=client -o yaml \
  > casetally-infrastructure/k8s/10-postgres-init-configmap.yaml
# then re-add the header comment
```

**Images are pinned by digest, not by tag.** `pg16`, `7-alpine` and `v1.36.4`
all move when upstream re-pushes them. A digest does not.

**Probes use TCP, not the unix socket.** The Postgres entrypoint runs
`/docker-entrypoint-initdb.d` scripts against a temporary server started with
`listen_addresses=''`. A socket probe reports ready during that window, so the
pod would go Ready while `init.sql` was still creating tables. TCP is closed
until the real server starts, which is the signal we actually want.

**Liveness is slacker than readiness.** Readiness failing pulls the pod out of
the Service and is recoverable. Liveness failing kills the process. Postgres can
be briefly unresponsive under a heavy bulk load, and restarting it then would be
the worst available response.

**`preStop` forces a fast shutdown.** Postgres treats SIGTERM as a smart
shutdown and waits for clients to disconnect, which can outlast the grace period
and earn a SIGKILL. That means crash recovery on the next boot. The hook runs
`gosu postgres pg_ctl -m fast -w stop`. It needs `gosu` because the container's
main process is root and `pg_ctl` refuses to run as root.

**`/dev/shm` is a 512Mi tmpfs.** A container gets 64MB by default. Postgres runs
with `dynamic_shared_memory_type=posix`, so parallel workers allocate shared
memory there and fail with "could not resize shared memory segment" on large
operations. Setting `max_parallel_maintenance_workers = 0` would have fixed the
index build alone and left the same limit in place for hybrid search, which runs
parallel scans over 83,706 rows at query time.

**Redis is a Deployment, Postgres is a StatefulSet.** Everything Redis holds is
worker state with its own TTL, and the embedding worker's real queue is
`legal_chunks WHERE embedding IS NULL` in Postgres. Losing Redis loses one poll
interval of observability, not work. With no durable state there is no PVC and
no pod identity worth preserving. Persistence is explicitly disabled in the
container args so it cannot be switched back on by a config file in a future
base image, which also allows `readOnlyRootFilesystem`.

**Redis uses `Recreate`, not `RollingUpdate`.** Two Redis pods briefly serving
the same Service would split worker state across two key spaces, so the same
worker could look IDLE through one pod and PROCESSING through the other. A
moment of downtime is the cheaper failure.

**PGDATA is a subdirectory of the mount.** `initdb` refuses to bootstrap into a
directory that is not empty, and a volume root never is. Compose uses the same
layout.

## Known Rough Edges

- `DATABASE_URL` duplicates `POSTGRES_PASSWORD`. The API step will switch to
  storing only the password and building the URL in the pod spec with
  Kubernetes `$(VAR)` interpolation.
- Ingestion must be configured to write `/data/uscode` paths when it runs in
  the cluster. Otherwise a re-ingest reintroduces host paths that no pod can
  resolve, and `restore-db.sh` would only fix them on the next full restore.
- `local-path` does not enforce PVC capacity. The `8Gi` request is
  documentation here. On a real CSI driver it would be a hard limit.
- The Groq API key in `.env.local` returns 401 Invalid API Key. Search is
  unaffected, but chat answers and query rewriting fall back to their degraded
  paths. Replace the key at console.groq.com.
- `HF_HUB_OFFLINE=1` is set on the API Deployment rather than in the shared
  ConfigMap, because the worker image does not bake the model in yet. Move it
  to the ConfigMap once it does.
- `DATABASE_URL` is assembled by string substitution, so a password containing
  URI-reserved characters would corrupt it. The current one was checked.
- Alembic is still not wired up. `casetally-db/alembic/` exists and is copied
  into the compose image, but nothing runs it. `init.sql` is the only schema
  path in both stacks.

## Loading Local Images into kind

The cluster cannot pull `casetally-backend:0.2.0` from anywhere, so it has to be
pushed into the node's containerd. For images you built yourself this just
works:

```bash
docker build --platform linux/arm64 -t casetally-backend:0.2.0 ./casetally-backend
kind load docker-image casetally-backend:0.2.0 --name casetally
```

That takes about 16 seconds for a 2GB image.

**The failure mode worth knowing about.** `kind load` fails on multi-architecture
images with a confusing error:

```text
ctr: content digest sha256:...: not found
```

The cause is that `kind load` always runs `ctr images import --all-platforms`,
while Docker only keeps the blobs for the platform you actually pulled. So the
manifest list references layers that are not on your machine. It has nothing to
do with the image being local, and `docker save` piped to
`kind load image-archive` fails in exactly the same way for the same reason.

Two things work:

```bash
# Export a single platform, then load normally
docker save --platform linux/arm64 redis:7-alpine -o /tmp/redis.tar
kind load image-archive /tmp/redis.tar --name casetally

# Or bypass kind and import without --all-platforms
docker save redis:7-alpine | docker exec -i casetally-control-plane \
  ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs -
```

In practice you rarely need either. Public multi-arch images are pulled by the
node itself, which also proves any digest pin resolves, and the images you build
locally are single-platform already.

## API Notes

**The model is baked into the image and loaded before the port opens.** The
Dockerfile pre-downloads MiniLM to `/opt/hf`, so no pod ever needs HuggingFace
at runtime, and `HF_HUB_OFFLINE=1` makes that guarantee fail fast rather than
silently re-downloading. A FastAPI lifespan handler then encodes one dummy
string during startup. Uvicorn does not bind its socket until lifespan
completes, so a cold pod is not merely kept out of Service endpoints, it is
unreachable. Measured warmup is 0.2 seconds.

The warmup deliberately touches only the model. If it called Postgres or Groq,
an unrelated outage in either would turn into pods that refuse to start.

**`DATABASE_URL` is assembled in the pod spec, not stored.** Only
`POSTGRES_PASSWORD` lives in the Secret. The Deployment builds the URL with
Kubernetes `$(VAR)` interpolation, which expands variables defined earlier in
the same `env` list, so `POSTGRES_USER`, `POSTGRES_DB` and `POSTGRES_PASSWORD`
all appear above `DATABASE_URL`. Reorder them and the literal string
`$(POSTGRES_USER)` is injected instead. The password now has exactly one source
of truth.

**Liveness never checks the database.** `/health/ready` runs a real `SELECT 1`
and controls Service membership. `/health/live` is static. If liveness checked
the database, a brief Postgres outage would fail it on every replica
simultaneously and Kubernetes would restart the whole API tier, converting a
recoverable dependency blip into a self-inflicted outage.

**Draining.** Pod deletion sends SIGTERM and removes the pod from Service
endpoints concurrently, with no ordering between them. A 5 second `preStop`
sleep lets endpoint removal propagate first, so SIGTERM arrives only after
traffic has stopped being routed here. Uvicorn then drains, bounded by
`--timeout-graceful-shutdown 40` because `/v1/chat/stream` is an SSE response
that could otherwise hold shutdown open indefinitely. Verified under load: 240
in-cluster requests during a pod deletion produced 0 failures, and the pod
terminated in 7 seconds against a 60 second grace period.

**Memory is set from measurement.** With the model warm and after serving real
searches, an SSE stream and a 1.2MB PDF, cgroup `memory.peak` was 423 MiB.
Requests are 512Mi and limits 1Gi.

## Worker Notes

**No Service, and no readiness probe.** The worker exposes no port and nothing
calls it; it pulls work from Postgres. Readiness answers "should traffic be
routed here", and with no Service there is no traffic to route. The only other
thing readiness affects is rollout progression, and for a queue consumer "ready"
and "alive" are the same question. A readiness probe here would duplicate
liveness while implying a routing decision that does not exist.

**Liveness checks a local file, not Redis.** The obvious probe is
`redis-cli EXISTS worker:embedding:$HOSTNAME:heartbeat`, and it is wrong twice
over. Redis runs with a Recreate strategy, so when it restarts every replica's
probe fails at the same moment and Kubernetes restarts the whole worker tier
over an outage in a service the workers do not need in order to make progress.
It also tests Redis as much as it tests the worker.

Instead the worker writes `/tmp/heartbeat` from inside its main loop, and the
probe checks that file's age. This was worth confirming before building: the
existing Redis heartbeat is also called from the main loop, not a background
thread, so neither can report healthy while the loop is wedged. A thread would
have been exactly the wrong design, because it keeps answering while the thing
it is reporting on has stopped.

The threshold is 150s. A normal batch takes about 2s, but the per-chunk retry
path re-encodes up to 100 rows individually and legitimately takes far longer.
The threshold has to exceed the slowest honest iteration or the probe kills
workers that are merely busy. The Redis heartbeat is kept, for observability.

**RollingUpdate is safe** because `_get_pending_chunks` ends with
`FOR UPDATE SKIP LOCKED`, so an old and a new replica overlapping cannot claim
the same row. Compare Redis, which uses Recreate because two instances would
split state.

**Throughput, and the thread-pinning fix.** torch sizes its thread pool from the
HOST core count, not the cgroup quota, so inside a `cpu: 1` container it started
11 threads to share 1 CPU of quota. The cost was measurable:

| | threads | periods throttled | throttled_usec | rows/sec per replica |
| --- | --- | --- | --- | --- |
| before | 11 | 70 to 77% | 164M to 422M | 5.3 |
| after `OMP_NUM_THREADS=1` | 1 | 6 to 11% | 18k to 99k | 8.2 |

A 55% throughput gain from one env var, and time spent throttled fell by about
four orders of magnitude. Threads above the quota do not add throughput, they add
context switching. 8.2 rows/sec is the per-replica figure under a 1-CPU limit and
is the one to quote; three replicas together drain about 24.6 rows/sec, so 1500
rows takes about a minute.

Set as env vars rather than `torch.set_num_threads()` because OpenMP and MKL read
them at import time, before any Python call could take effect.

**Memory headroom.** Three workers, two API pods, Postgres and Redis declare
7052Mi of limits against a 7934Mi VM, which is 89%. Requests total only 3136Mi,
so scheduling is comfortable, but there is not room for the frontend and an
ingestion Job on top if everything sits at its ceiling. That is a 2-replica
decision or a bigger Docker VM, not a reason to raise the worker ceiling.

## Worker Demo

The corpus is 100% embedded, so the queue is permanently empty and there is
nothing to watch. `demo-worker.sh` manufactures a backlog and then proves the
work was neither lost nor duplicated.

```bash
cd casetally-infrastructure/k8s

./demo-worker.sh backlog [N]   # default 6000. Backs originals up first
./demo-worker.sh watch         # live progress, exits when the queue drains
./demo-worker.sh verify        # prove correctness, then drop the backup
./demo-worker.sh graceful      # delete a pod mid-batch
./demo-worker.sh crash         # real SIGKILL from the node
./demo-worker.sh restore       # put the originals back and stop
```

### Replaying it live, two terminals

```bash
# Terminal 1
cd casetally-infrastructure/k8s
./demo-worker.sh backlog 3000
./demo-worker.sh watch

# Terminal 2, while the drain is running
./demo-worker.sh graceful      # then, still mid-drain:
./demo-worker.sh crash

# Terminal 1, once watch exits
./demo-worker.sh verify
```

### What each demo shows

**Graceful.** SIGTERM arrives mid-batch. The handler sets `running = False`,
which the loop only checks at the top of the next iteration, so the in-flight
batch finishes and commits first. Actual log from a run:

```text
02:39:36  Successfully processed 100 chunks
02:39:40  Received signal 15, initiating graceful shutdown...
02:39:52  Successfully processed 100 chunks     <- the in-flight batch committed
02:39:52  Shutting down worker...
02:39:52  Worker stopped gracefully
```

Terminated in 14s against a 45s grace period. Nothing is requeued, because
those rows were committed rather than rolled back.

**Crash.** `kubectl exec kill -9 1` does not work: PID 1 ignores signals from
inside its own namespace unless it installed a handler. The kill has to come
from outside, so the script resolves the container's PID as the node sees it and
signals that:

```bash
cid=$(kubectl get pod "$POD" -n casetally \
       -o jsonpath='{.status.containerStatuses[0].containerID}')
cid=${cid#containerd://}
hostpid=$(docker exec casetally-control-plane crictl inspect "$cid" \
           | python3 -c 'import sys,json; print(json.load(sys.stdin)["info"]["pid"])')
docker exec casetally-control-plane kill -9 "$hostpid"
```

No handler runs and nothing commits. The worker held its rows under
`FOR UPDATE SKIP LOCKED` from the SELECT until commit, so Postgres rolls the
transaction back, the locks release, and the rows reappear as
`embedding IS NULL`. Another replica claims them on its next poll. No lease
table and no reaper are needed. Observed: `restartCount` 1 after 2s, and the
queue depth unchanged across the kill.

### How correctness is proven

Four checks, all in `verify`:

1. 0 rows left with `embedding IS NULL`.
2. All N backlog rows re-embedded.
3. Per-worker committed counts sum to **exactly N**. More than N would mean a
   row was embedded twice; less would mean committed work went unattributed.
4. Cosine similarity against the pre-demo backup. Expect ~1.0 rather than byte
   equality, since batch composition and transformer padding shift the last
   decimal places. A measured run gave min 0.99999988, avg 1.00000000.

The tally is read from each worker's **log**, not from the Redis counter, and
that distinction matters. `"Successfully processed N chunks"` is logged only
after `session.commit()` returns, so the line exists if and only if the rows are
durable. The Redis metric is sampled on a timer and is deleted outright by
`StateManager.cleanup()` when a worker exits cleanly, so it systematically
undercounts a graceful shutdown. A pod destroyed during a demo is banked to a
ledger before it disappears, because its logs are unreachable afterwards.

A measured run, with one graceful delete and one SIGKILL:

```text
worker-l9974   committed  900   (restarted 1x: 200 pre-crash + 700 after)
worker-v9d9g   committed 1000
worker-w754n   committed  900
worker-gdbdb   committed  200   (destroyed during demo, from ledger)
sum = 3000   (N = 3000)   exact

redis-sampled sum = 2900      <- undercounts by 100, as expected
```

`verify` drops the backup table on success. On failure it keeps the table so
you can inspect it, and `restore` puts the original embeddings back.

## Worker autoscaling (KEDA)

KEDA 2.21.0, vendored at `keda/keda-2.21.0.yaml` with all three images pinned by
digest. `up.sh` installs it before the application manifests, because
`41-worker-scaledobject.yaml` needs the ScaledObject CRD to exist.

| | |
| --- | --- |
| trigger | `postgresql`, counting the worker's own queue predicate |
| range | `minReplicaCount: 0`, `maxReplicaCount: 3` |
| target | `targetQueryValue: 1000` rows per replica |
| activation | `activationTargetQueryValue: 0`, so one waiting row wakes the tier |
| poll | `pollingInterval: 10` |
| cooldown | `cooldownPeriod: 60`, plus `scaleDown.stabilizationWindowSeconds: 30` |

**Why queue depth and not CPU.** The worker is a poller: it sleeps, wakes, asks
Postgres for rows, and sleeps again. Its CPU looks the same whether 0 rows are
waiting or 80,000, because what bounds it is how much work exists. A CPU trigger
would only react after a worker was already saturated. Queue depth is the actual
demand and it is known before any work starts.

**The host must be fully qualified.** `host: casetally-postgres` leaves the
ScaledObject `Ready=False` with `hostname resolving error: lookup
casetally-postgres ... no such host`, which reads like a database fault and is
really DNS scope: the query is run by the KEDA operator, which lives in the
`keda` namespace, and a bare Service name only resolves inside its own namespace.

**Auth adds no new credentials.** The `TriggerAuthentication` takes the password
from the existing `casetally-secrets` and the user and database names from the
existing `casetally-config`, via `configMapTargetRef`, so the scaler cannot drift
from what the API and worker connect as.

**The Deployment declares no `replicas`.** KEDA owns that number. Leaving it in
the manifest means every `kubectl apply` resets it and KEDA moves it back, so the
two fight and the apply looks like it did nothing.

### The scaler query, and the index behind it

The trigger counts the worker's claim predicate verbatim:

```sql
SELECT count(*) FROM legal_chunks
WHERE embedding IS NULL AND is_current = TRUE AND retry_count < 3
```

Unindexed, that is a parallel sequential scan of all 83,706 rows: 17ms warm
across 17,408 buffers. Cheap once, not cheap every ten seconds forever, and it
spends two parallel workers each time competing with live search. `init.sql` now
creates a partial index on exactly that predicate, which takes the same query to
**0.037ms over 1 buffer** as an index-only scan. The index is 8 KB when the queue
is empty, because a partial index only covers the rows that match.

### Memory

Upstream ships each KEDA component at limits 1000m/1000Mi. Measured working set
idle is 31 MiB (operator), 28 MiB (metrics apiserver) and 10 MiB (admission): 69
MiB against 3,000 MiB declared. On a node with 7,934 MiB allocatable, where the
stack already declared 89% in limits, that took the total to 105%.

`keda/keda-resource-limits.yaml` trims the memory limits to 192Mi and requests to
64Mi, as a JSON patch applied by `up.sh`. The vendored manifest is left untouched
so it stays diffable against the upstream release. Declared memory limits are now
**74% of allocatable**, and scale-to-zero returns the 712 MiB two idle workers
used to hold.

### Accounting across scale-downs

`demo-worker.sh verify` sums committed rows per pod from a Redis hash,
`worker:embedding:committed`, which the worker `HINCRBY`s after each commit
returns. It has no TTL and `cleanup()` does not delete it.

That exists because autoscaling broke the previous approach. The tally used to
read each worker's log, which is the one source that cannot overcount, since a
line is written only after the commit returns. Pods KEDA scales away take their
logs with them, so a 3,000 row drain could only account for 1,500. The work was
never lost; the evidence was.

Two caveats to know before demoing: Redis has no persistence and uses a
`Recreate` strategy, so a Redis restart mid-run resets the tally to zero without
any row being lost; and the counter is cumulative, so `demo-worker.sh backlog`
resets it. The row-level checks against the backup table are the authority either
way.

---

## Ingestion Job

One-shot re-ingestion of the US Code from the source HTML. It is idempotent: a
run against an already-ingested corpus writes nothing.

**Pause worker autoscaling first.** This is now required, not an optimisation.
Ingestion inserts chunks with `embedding IS NULL`, which is exactly the queue
KEDA scales on, so an unpaused run has the autoscaler racing the Job: the queue
climbs into the tens of thousands, KEDA takes the workers to 3, and three 900Mi
workers plus a 2Gi Job ceiling overcommit a 7.9Gi VM while the Job is still
writing.

```bash
# 1. pin the worker tier at zero for the duration
kubectl annotate scaledobject casetally-worker -n casetally \
  autoscaling.keda.sh/paused-replicas=0 --overwrite

# 2. run the Job
kubectl delete job casetally-ingestion -n casetally --ignore-not-found
kubectl apply -f 50-ingestion-job.yaml
kubectl logs -f -n casetally -l app.kubernetes.io/name=ingestion

# 3. hand the queue back to KEDA, which scales up on its next poll
kubectl annotate scaledobject casetally-worker -n casetally \
  autoscaling.keda.sh/paused-replicas-
```

`paused-replicas=0` rather than `kubectl scale`, because the Deployment no longer
declares a replica count: KEDA owns it, and a manual scale would be reverted on
KEDA's next poll ten seconds later. The annotation tells KEDA itself to hold a
fixed number, which is the only instruction it will respect. Note the trailing
dash in step 3, which is how kubectl removes an annotation.

Parking the queue is safe because the queue *is* `embedding IS NULL` in Postgres.
Nothing is lost by having no workers; the rows simply wait, and the first thing
KEDA does when unpaused is notice them.

### Why the paths work without any code change

Ingestion derives `artifact_metadata->>'file_path'` from the real on-disk
location of each PDF: `plugins/uscode.py` globs `uscode_dir` and passes
`str(pdf_file)` straight through. So pointing it at the mount is what makes a
re-run reproduce the paths already in the database, rather than reintroducing
host paths that no pod can resolve. `USCODE_DATA_DIR=/data/uscode` lives in the
ConfigMap, which is the one place that decides this.

The same directory holds both the 53 source HTML files (433MB) and the 49 PDFs,
so the existing kind `extraMount` already covers the source data. No separate
mount and no cluster recreation was needed.

Verified after a full run: all 26,737 artifact paths still begin with
`/data/uscode`, and **0** carry a host path.

### Single-run enforcement

`parallelism: 1` constrains this Job object, and nothing else.
`finalize_deactivation` retires every chunk absent from *that process's*
accumulated `_active_clause_ids`, so two concurrent runs would each retire the
chunks the other just wrote. An earlier version of exactly that bug cut a
31-chunk section down to 1 live chunk and 30 dead ones.

Kubernetes config cannot prevent a second `kubectl create job`, or someone
running `cli.py` by hand, so the guarantee lives next to the data instead:

- `cli.py` takes `pg_try_advisory_lock` before reading or writing anything.
- Losing the race exits **75**, deliberately distinct from the generic 1.
- The Job's `podFailurePolicy` matches exit 75 with `action: FailJob`, so
  Kubernetes does not retry a refusal that is guaranteed to lose again.
- `podReplacementPolicy: Failed` stops a replacement pod from starting while the
  previous one is still terminating, which would otherwise create the race
  itself.

A session-level advisory lock is the right primitive here: it lives exactly as
long as the connection, and Postgres drops it automatically if the process dies.
No lock table, no TTL, no reaper.

### Replaying the concurrency test

```bash
# Terminal 1: start a real run and leave it going
kubectl delete job casetally-ingestion -n casetally --ignore-not-found
kubectl apply -f 50-ingestion-job.yaml

# Confirm the lock is actually held
kubectl exec -n casetally casetally-postgres-0 -- psql -U casetally -d casetally_law \
  -qAtX -c "select count(*) from pg_locks where locktype='advisory'"

# Terminal 2: launch a second Job while the first still holds the lock
sed 's/name: casetally-ingestion/name: casetally-ingestion-second/' \
  50-ingestion-job.yaml | kubectl apply -f -

# It fails in seconds. Show why:
kubectl get job casetally-ingestion-second -n casetally
kubectl get job casetally-ingestion-second -n casetally \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason}{"\n"}{end}'
kubectl logs -n casetally -l job-name=casetally-ingestion-second

# Exactly one pod: no retries, despite backoffLimit 2
kubectl get pods -n casetally -l job-name=casetally-ingestion-second

kubectl delete job casetally-ingestion-second -n casetally
```

Measured result:

```text
casetally-ingestion-second   Failed   0/1   3s
Failed=True reason=PodFailurePolicy
  msg=Container ingestion ... failed with exit code 75 matching FailJob rule at index 0
pod exitCode=75
log: Another ingestion run already holds advisory lock 1128351557/1.
     Exiting 75 without reading or writing anything.
pods created: 1
```

### What a clean run looks like

```text
Chunks deactivated: 0
Statistics: {'processed': 53, 'inserted': 0, 'updated': 0, 'skipped': 50915,
             'errors': 0, 'chunks_created': 0, 'chunks_updated': 0,
             'chunks_deactivated': 0, 'artifacts_created': 0}
```

50,915 skipped headings with every write counter at zero, which is the README's
corpus-wide idempotency claim reproduced inside the cluster. The corpus md5 over
`clause_id || version_hash` was byte-identical before and after
(`f8c787eb4db4f66ddb2e73543c79a9b8`), and `./restore-db.sh --verify-only` passes
afterwards.

## Ingress

Everything is reachable on one origin at **http://localhost**:

| Path | Backend |
| --- | --- |
| `/` | `casetally-frontend:3000` |
| `/v1` | `casetally-api:3001` |
| `/health` | `casetally-api:3001` |

Routing both the page and its API calls through one host is what removes CORS
from the picture entirely: the browser loads the page and calls the API on the
same scheme, host and port, so there is no cross-origin request to permit.

### Why Traefik

ingress-nginx was retired by the Kubernetes project with end of life in March
2026, so it gets no further releases or security fixes. Starting new work on it
would mean adopting a dead component. Traefik is also what CaseTally already
runs in production (`docker-compose.infra.prod.yml` pins `traefik:v2.10`), so the
two environments share a proxy instead of diverging.

It is the better technical fit here too: Traefik streams responses through
without buffering by default, which is what `/v1/chat/stream` needs. The nginx
controller buffers unless told otherwise and needs a per-Ingress
`proxy-buffering: off` annotation to stream SSE at all.

Installed as plain manifests, not Helm, matching the project-wide decision that
every object is readable in the file that creates it. The ClusterRole rules are
copied verbatim from Traefik's own docs at the pinned version
(`docs/content/reference/dynamic-configuration/kubernetes-crd-rbac.yml` at tag
`v3.3`), with the `traefik.io` CRD rules omitted because no CRDs are installed
and the CRD provider is not enabled. Verified after deploying: **0 forbidden and
0 error lines** in the controller log.

### Why standard Ingress and not Gateway API

Gateway API is where Kubernetes ingress is heading and it is the better answer
for multi-team clusters: `Gateway` and `HTTPRoute` separate infrastructure
ownership from route ownership, and it expresses header matching, traffic
splitting and filters natively instead of through vendor annotations. None of
that applies here. This is one application, one host, three path prefixes, owned
by one person, needing no feature Ingress cannot express. Gateway API would add
three CRDs and two more objects to describe the same three routes, so Ingress is
the smaller correct tool. The trigger to revisit would be needing per-route
middleware or traffic splitting.

### Two things that are easy to get wrong

**`/ping` is not on the web entrypoint.** Traefik attaches it to its internal
entrypoint, which defaults to `:8080`. Probing port 80 for `/ping` returns 404
and the pod crash-loops on a failing startup probe, which is exactly what
happened on the first deploy. The manifest now declares a named `health`
entrypoint on 8080 and binds ping to it, with no hostPort so health checking
stays inside the cluster.

**Traefik needs `Recreate`, not `RollingUpdate`.** The pod binds hostPort 80 and
443 on the node. Two pods cannot hold the same host port, so a rolling update
would leave the new pod Pending forever behind the old one.

### SSE through the proxy

Measured, because "Traefik does not buffer" is a claim worth testing rather than
repeating. Raw-socket timings of the same request with and without the proxy:

| | headers at | first body byte | body window | socket reads |
| --- | --- | --- | --- | --- |
| direct to API | +0.008s | +6.30s | 0.402s | 371 |
| through Traefik | +0.006s | +8.80s | 0.381s | 342 |

Three things show it is streamed, not buffered. Headers arrive in 6ms while the
body completes 9s later, and a buffering proxy holds the headers too. The body
lands in 342 separate socket reads spread across 5 distinct 100ms buckets. And
the delivery window is the same with and without the proxy, so Traefik adds no
buffering of its own.

The timeouts that would otherwise kill a long stream are disabled explicitly:
`respondingTimeouts.writeTimeout=0` bounds how long Traefik spends writing a
response, so any finite value becomes a hard cap on stream length.
`forwardingTimeouts.responseHeaderTimeout=0` does the same on the backend side.

**Worth knowing about perceived latency.** Nothing streams for the first 6 to 9
seconds, then the whole answer arrives in about 0.4s. That gap is the
application, not the proxy: a blocking non-streaming Groq call for query
rewriting, then retrieval, then the reasoning model spending tokens on internal
reasoning before emitting any content. The streaming UX benefit is mostly lost to
that prefix. Reducing it means either dropping the synchronous rewrite from the
critical path or emitting a progress event before it.

**Long-stream drain, verified.** An API pod deleted 3 seconds into a live stream:
the stream still completed in 10.70s with 315 frames and a `[DONE]` terminator,
exit code 0, while the pod took 9s to terminate inside its 60s grace period. The
`--timeout-graceful-shutdown 40` bound was never reached.

## Frontend

Built with Next.js standalone output, which cut the image from **1.15 GB to
297 MB**. `next.config.mjs` sets `output: 'standalone'` so the build emits a
self-contained server with only the modules the app actually imports; the runtime
stage then installs nothing.

Two details that bite:

- `HOSTNAME=0.0.0.0` is required. Next's standalone server binds localhost
  otherwise, which inside a pod makes it unreachable from everything, including
  the kubelet's probes.
- `public/` and `.next/static` are not part of the standalone bundle and have to
  be copied separately, or every asset 404s while the HTML renders fine.

**The ingress origin is baked into the image.** `NEXT_PUBLIC_*` variables are
inlined into the client bundle at build time, so it is a `--build-arg`, not
runtime config. The image is built for `http://localhost`; serving the same
bundle on a different hostname would leave the page calling an origin it was not
loaded from. **That is a rebuild, not a config change.** A relative URL would
make any host work, but the app does
`process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:3001"`, and `||`
treats an empty string as falsy, so an empty value falls back to the dev default.
Changing `||` to `??` in the three call sites would enable relative URLs; that is
an application change and has not been made.

**The frontend pod holds no credentials**, and that is deliberate rather than an
oversight. Every backend call is made from the browser: all three call sites are
`"use client"` components, and the app has no API routes, no `route.ts` handlers,
no `getServerSideProps` and no server actions. This pod never reaches Postgres,
Groq, or even the API. It serves JavaScript.

## Memory Budget

| Component | requests | limits |
| --- | --- | --- |
| api x2 | 1024 Mi | 2048 Mi |
| postgres | 512 Mi | 2048 Mi |
| worker x2 | 1024 Mi | 1800 Mi |
| frontend x2 | 128 Mi | 384 Mi |
| redis | 64 Mi | 256 Mi |
| traefik | 48 Mi | 128 Mi |
| **total** | **2800 Mi** | **6664 Mi** of 7934 (84%) |

Workers default to **2**, not 3. Adding the ingress and frontend pushed the
declared limits past what the VM holds, and giving back one worker frees 900Mi,
which is more than those two need together. The queue is `embedding IS NULL` in
Postgres, so worker count only changes how fast a backlog drains, never whether
the work happens:

```bash
kubectl scale deployment/casetally-worker -n casetally --replicas=3   # demo
kubectl scale deployment/casetally-worker -n casetally --replicas=2   # default
```

A third worker brings the total to 7564 Mi, 95% of the VM, which is fine for a
demo and not something to leave running. Raising per-pod ceilings would have been
the wrong fix: the pods were not short of memory, the node was.

Frontend and Traefik limits are set from measurement, not guesses: both peak
around 39 to 41 MiB, so they sit at 192Mi and 128Mi respectively.
