# Search timeout diagnostic — after V2/V3 indexing success

Reported milestone: indexing completed with 650 files and no bind overflows.
Search still reaches the 15-second tool limit. Do not increase that limit or
modify more installed files without identifying the time-consuming phase.

## Findings from the matching public package

- `openclaw-agent-db-DwEkomYQ.js` logs slow database open at line 230, after
  schema/integrity checks, connection setup, schema ensure, and registration.
  The warning alone does not prove the OS/SQLite file open itself is slow.
- `manager-runtime.js` search can bootstrap/repair an index and start background
  sync (`syncAdmitted`, `sync.onSearch`, session warm sync). Invoking memory_search
  is therefore not guaranteed read-only. An embedding request may also occur.
- Successful indexing does not establish whether the persistent gateway has
  adopted the updated database/manager state. No restart is requested yet.

## Direct read-only baseline

Download `scripts/probe_search_readonly.py` from this repository to a fresh local
directory and inspect it. It imports no OpenClaw code, loads no extensions, makes
no network calls, and reads no configuration or transcripts. It opens only the
explicitly supplied existing database with SQLite `mode=ro` and query_only.
There are no migrations, integrity scans, checkpoints, index builds, or writes
to database records. SQLite's normal read-only WAL access may use WAL/SHM
sidecars; this is not a promise of zero filesystem metadata/sidecar activity.
Do not use immutable mode: it can ignore the live WAL state.

Use the exact index database path already known locally from configuration or
prior status output. Do not send the path or configuration to Codex. The script
does not discover databases. If unsure which database is used, stop and report
that uncertainty instead of guessing.

```sh
python3 -B /path/to/probe_search_readonly.py --db /exact/local/index.sqlite --fts
```

At the local hidden prompt, enter a simple familiar phrase. It is never printed
or sent anywhere. The output contains phase labels, elapsed milliseconds,
counts, and SQLite error codes only. Return that JSON. Also report whether the
index database is the same file as the agent database mentioned in the slow-open
warning (yes/no), and the warning's elapsedMs number if already available; omit
its path and agent identifier. No additional `status --deep` run is needed.

The probe times raw connection creation and schema access separately. It counts
known index tables and performs the same limited FTS phrase lookup twice, with
at most ten row IDs read internally; IDs and text are never emitted. Missing
expected tables are reported rather than treated as healthy. Each SQL phase
has a five-second SQLite VM progress deadline and a one-second lock timeout;
blocked OS I/O cannot be interrupted by the VM callback. Stop/report a hang
rather than starting duplicate probes.

## Interpretation

- Fast raw/schema/FTS phases: investigate OpenClaw initialization, provider/query
  embedding, generation locks, and gateway manager state next. This does not
  prove vector search is fast: the probe intentionally does not load sqlite-vec.
- Slow raw/schema phases or SQLITE_BUSY: investigate storage/locking first.
- Slow FTS with fast schema access: focus on lexical query execution.
- Missing tables: check that the chosen file is the actual index DB locally.
- Fast FTS with zero matches: use a simpler locally known phrase; zero counts
  alone do not establish a broken index or equivalent memory_search semantics.

V2 and V3 stay applied. This probe does not change OpenClaw's code or settings.
