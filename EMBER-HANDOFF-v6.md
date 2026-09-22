# V6 candidate — cooperative session corpus scans

## Current instruction: review and dry-run only

Do not apply, restart, or run another search from this handoff yet. Review the
change, run the three packaged tests, and report the dry-run output. Activation
is a separate coordinated step because the running gateway caches these modules.
This package is a candidate, not proof of a working live search.

## What changed and why

The recorded gateway search spent 16.753 seconds acquiring its manager. Startup
session catch-up began inside that acquisition. The public source confirms that
the supposedly asynchronous corpus-listing function immediately ran an entire
synchronous scan. CLI managers skip constructor catch-up; gateway managers do not.

V6 makes the asynchronous corpus-listing API yield before scanning, then at most
every 64 enumeration checkpoints or after an observed 8 ms slice. This is a
cooperative scheduling target, not a hard maximum: one native SQLite or filesystem
call cannot be interrupted. Other synchronous callers retain the original API.
The generator copies the exact existing owner, cron, retained-instance, artifact,
path-deduplication, and revision rules. No cache is introduced. Each scan still
reads current entries, revisions, additions and removals.

The archive lookup is the other part of this change. V2 bounded the SQLite
bindings by splitting a large selector set into 400-item batches. The stock
schema has no session_key index, so those OR queries can repeatedly scan the
archive table. V6 passes the selectors as two bound JSON arrays using SQLite's
json_each and executes ONE SELECT. Values are bound, never interpolated. It
retains the owner filter, selected columns, and created_at/session_id ordering.
A single SELECT supplies the read snapshot; no multi-statement savepoint is
needed. Empty selectors still return nothing. The typed string-identity API
now explicitly rejects non-string selectors rather than silently serializing
unsupported values. No schema, indexes, journal settings or database contents
are changed by the patch installer.

The synthetic 38,000-row SQLite test returned identical 35,765 eligible rows
for over 40,000 selectors, including duplicates, key matches, and quoted strings.
It reduced 101 statements to one, using TWO bindings. Its measured time was
approximately 1,000 ms versus 80 ms locally. That is not a server benchmark.

## Exact installed file changes

1. dist/memory-core-host-engine-sessions-BzzfWTfG.js
   Before: ee239cfc4d98c262cb54562bc971505199fd8fc4a9b8ed5e10ab0c17713113f8
   After:  26645cb127d4cecbec4f20ed0563cceaf31b1db463df3a625e05d5870501bf2e
2. dist/session-accessor.sqlite-entry-CoLie3L_.js
   Before: 02efd3d54ae2fab43fadc60d09f0a5421375c3fd87820c4defb4b45e55c37ba0 (V2)
   After:  4f519421417b86a97cfe306afe030366e9f4a75ef9f44d5162fb2465b52104d9

The installer requires OpenClaw 2026.8.1 and exact unchanged V5 manager and V3
tombstone hashes. It replaces V2's archive implementation while preserving its
bind-overflow protection with a smaller, constant bind count. It does not modify
manager-runtime.js, V3, timeouts, locks, integrity checks, watchers, or provider
configuration. Unknown hashes and mixed installation states are refused.

On apply, only those two code files and recoverable backup/manifest files under
<package>/.ember-distiller/backups/<backup_id>/ are written. The file replacements
are individually atomic, not a two-file filesystem transaction; coordinate with
other users of the shared installation so no new process loads a mixed pair
while applying. No service is automatically stopped or restarted. Keep the backup.

## Local review commands

Extract into a fresh operator-owned directory outside any watched/indexed
workspace. Set TRACE_PACKAGE locally to the verified OpenClaw package directory.
Do not copy private deployment configuration into this public package.

```
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_session_cooperative.py' -v
python3 -B scripts/patch_session_cooperative.py --package-dir "$TRACE_PACKAGE" --dry-run
```

Read PATCH-v6.diff, scripts/patch_session_cooperative.py,
scripts/v6_session_corpus_original.js, and ember_memory/storage.py. The imported
patch_openclaw.py supplies the exact prior V2 function; its command-line entry
point does not run on import. No OpenClaw package code is executed by dry-run.
Tests use synthetic data; the SQL test requires Node with node:sqlite and json_each.

Expected dry-run: exactly the two files listed above. Report tests, checksum,
and dry-run output as V6 PREFLIGHT. If anything differs, stop without applying.

## Apply and revert reference — only after coordinated activation approval

Apply:

```
python3 -B scripts/patch_session_cooperative.py --package-dir "$TRACE_PACKAGE"
node --check "$TRACE_PACKAGE/dist/memory-core-host-engine-sessions-BzzfWTfG.js"
node --check "$TRACE_PACKAGE/dist/session-accessor.sqlite-entry-CoLie3L_.js"
```

One-command code revert (restores the previous V2 archive and stock corpus module):

```
python3 -B scripts/patch_session_cooperative.py --package-dir "$TRACE_PACKAGE" --revert
```

Revert refuses subsequent local edits and restores only a matching V6 backup.
A running gateway still holds its loaded code after either apply or revert.
Coordinate an Ember-only restart to activate the intended code; do not restart
another service. Existing V5 backup/revert is separate: do not use it to undo V6.

## Planned live verification

After activation is explicitly approved: record new process identity/readiness,
verify installed hashes, then run ONE ordinary gateway memory_search using the
same known query and the existing 15-second ceiling. No diagnostic preload is
required and no CLI search substitutes for this check. Report elapsed time,
result count and relevance without private text. If it fails, retain the result
and stop; do not retry, extend the timeout, force-index or clean anything up.

If retrieval passes, normal-watcher addition/removal tests still need to be
coordinated and completed before claiming memory is fully fixed. The code tests
prove enumeration observes additions/removals; they do not prove live indexing,
embedding, watcher delivery, or conversation responsiveness. Existing startup
catch-up, update listeners, and background work remain enabled.

## Validation and limitations

Three packaged tests cover: the extracted real corpus rules across shared and
agent-owned stores, retained entries and foreign owners; progress of timers during
scan; fresh revisions/additions/removals; error propagation; real SQLite selection
of more than 40,000 selectors with equivalent ordering/owner filtering; operation
inside an existing transaction and query_only mode; exact-state apply, idempotence,
rollback, refusal after edits and refusal of a mixed installation.

The complete local suite passed 50 tests. Exact public full modules were also
patched in a temporary tree, syntax checked, reapplied idempotently and reverted
byte-for-byte. No actual server data or server access was used for development.

This does not move all SQLite work to a worker thread. A single long native query,
a database lock, initial integrity checks, unrelated disk-budget maintenance or
other synchronous OpenClaw work can still delay the event loop. The earlier
180-second CPU profile included such work; it did not attribute all of it to the
initial failed search. The live trial determines whether the remaining costs fit
inside the existing tool budget. Do not describe this as a complete performance
fix until that trial and freshness checks pass.
