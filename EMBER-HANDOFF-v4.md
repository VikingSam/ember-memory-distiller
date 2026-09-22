# V4 candidate: incremental search maintenance

OpenClaw 2026.8.1 starts fresh CLI memory managers dirty, and its default
search/session-start synchronization invokes maintenance with `force: true`.
Consequently, ordinary searches can rebuild and publish the entire index.
V4 transfers pending changes to the maintenance manager and uses incremental
sync for a valid index. It preserves explicit forced indexing, full retry
flags, missing/mismatched identity rebuilds, and session retry work.

## Exact scope

Only installed code target: `dist/extensions/memory-core/manager-runtime.js`.
V2/V3 files are not touched. No configuration, integrity checks, service units,
locks, database records, or temporary rebuild files are modified by the patch
script. Applying the patch additionally creates an original-file backup and
manifest under the package's `.ember-distiller/backups/<backup_id>/`.
Revert archives the patched file under `.ember-distiller/restore-archives/`.

The original file must have SHA256
`859363eb27769c57a371ebdf4d0b5d74f588faa882fb82f42cad9222966169bd`.
A different file, version, or partial patch is rejected without modification.
Review local repair changes rather than bypassing the hash check. Applying an
already-patched file is a no-op. Reinstalling OpenClaw replaces this patch;
reapply only to the supported version/hash after an upgrade/reinstall.

## Locking and recovery

Incremental maintenance takes the existing workspace lock, then generation
publication lease, in the same order as full publication. This prevents
generation readers from seeing partially updated live tables. Existing nested
workspace locking supports reentrancy. The full-rebuild decision is evaluated
while protected; if needed, both locks are released before rerunning the
existing full-rebuild path, avoiding recursive acquisition.

The pending memory/session state is merged into the maintenance manager before
sync. Existing restoration paths still return it to the search manager on
failure or incomplete work. Failed/incomplete incremental work can require a
retry; the patch does not turn every incremental update into one atomic full
index transaction. Background maintenance may still contend with searches,
and changed documents still require embeddings. No sub-15-second performance
claim is made before a live test.

## Review and test

Unpack `ember-memory-search-v4.zip` into a fresh directory and work inside
`ember-memory-search-v4/`. Read this file, PATCH-v4.diff, the patch script,
and ember_memory/storage.py. The archive is an add-on, not a replacement for
the previously delivered distiller.

```
python3 -B -m unittest discover -s tests -v
python3 -B scripts/patch_search_maintenance.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --dry-run
```

Expected dry-run: exactly the one code file named above. Two packaged Python
tests cover multiple JS runtime scenarios and patch storage behavior. The
whole development suite has 29 passing tests. Tests use extracted public
functions with mocked I/O/locks, not Ember's real database or a running gateway.
The complete patched module passes Node syntax checking. Applying/idempotence/
byte-exact revert were also exercised against the original public npm file.

## Controlled CLI trial

Record Blade's repair changes and confirm no diagnostic search/reindex is
running. Do not combine this trial with cleanup, configuration edits, or
integrity changes. Apply only after the exact-hash dry-run and diff review:

```
python3 -B scripts/patch_search_maintenance.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
```

Keep the emitted backup_id. Run one fresh CLI search under Ember's existing
OPENCLAW_STATE_DIR, with the prior sqlite-timing.cjs hook if available. Ordinary
search can write the index and call the configured embedding provider. Return
exit status, elapsed time, result count/relevance, and sanitized timing records.
In the valid-index/no-full-retry case, expect incremental maintenance rather
than a new full shadow rebuild/vector-table publication. A legitimate metadata
mismatch may still rebuild once; report it instead of disabling that check.

This does not activate new code in an already-running gateway. Do not restart
either service for the CLI trial. Gateway activation is a separate coordinated
step after the trial succeeds; the known wrong OPENCLAW_SYSTEMD_UNIT setting
must not be used to restart Ember.

## One-command V4-only revert

```
python3 -B scripts/patch_search_maintenance.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert
```

Revert refuses to overwrite later edits. It leaves V2/V3 intact and restores
code only, not index changes made by a search. A running process keeps whatever
code it loaded until restarted; no restart is performed by this script.
