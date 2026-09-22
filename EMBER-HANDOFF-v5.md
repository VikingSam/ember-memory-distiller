# V5 candidate: search the published index without initiating routine sync

Ember's process-only comparison returned the same six relevant hits in a
3,533 ms search phase: FTS 20 ms, query embedding 210 ms, vector retrieval
2,896 ms, read-generation acquisition 2 ms. Manager acquisition was separately
3,655 ms and module loading occurred 18,123 ms after child preload. This does
not prove warm or cold gateway timing, nor concurrent-update performance.

V5 makes the comparison's core behavior durable for CLI **and default gateway**
searches: the routine background-maintenance launch inside search is disabled.
Search uses the current published index. It does not bypass generation locks,
index-validity checks, missing-index bootstrap, or identity-repair paths.
The query can therefore still wait on existing work or perform required repair.
This patch is not a general guarantee of lock-free reads or a 3.5-second SLA.

## Freshness behavior and limits

Ordinary search no longer refreshes the index as a side effect. This is an
intentional behavior change, including the formerly implicit session-start
refresh. Pending dirty state is retained, not cleared. Searches may report a
stale/dirty index until maintenance completes.

Existing gateway file watchers, transcript-update listeners, session startup
catch-up, explicit `memory index`, and existing interval sync are untouched.
Default intervalMinutes is zero: this patch does NOT invent a periodic job.
File watchers cover edits while running; they alone do not prove reconciliation
of edits made while the gateway was stopped or events missed during failures.
Run explicit non-forced indexing when such a catch-up is needed. No automatic
startup memory-file reconciliation is added by V5. Do not claim fresh retrieval
until the gateway synthetic-update test below passes, and retain an explicit
maintenance procedure for downtime/missed events.

Existing background jobs can still consume CPU, embedding time, or locks.
The wake-up gate fix is independent. A result here does not prove that all
conversation-lane waits are resolved.

## Scope and review

Exactly one installed code target:
`dist/extensions/memory-core/manager-runtime.js`.
Required V4 SHA256:
`9580e3f7d3d18db3fa881e438cac96d93347a59e6e796b6a35b2733fb5f7a483`.
Expected V5 SHA256:
`e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df`.

Read PATCH-v5.diff, scripts/patch_search_published.py, and storage.py. The
script refuses other versions/hashes and later local edits. Only the code file
plus backup/manifest under `.ember-distiller/backups/` is written on apply.
V2/V3, integrity checking, configuration, service identity, and database files
are not changed by the patch script. Running searches/indexing is separate and
can write database records and call the configured provider.

Unpack ember-memory-search-v5.zip into a fresh directory and enter
ember-memory-search-v5/. Commands:

```
python3 -B -m unittest discover -s tests -v
python3 -B scripts/patch_search_published.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --dry-run
python3 -B scripts/patch_search_published.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
```

Apply only after successful review, tests and dry-run, with no competing
diagnostic search/reindex. Retain backup_id and run node --check on the target.
Two packaged tests cover the extracted real search method (CLI/default modes,
dirty state, bootstrap/identity safety, release of leases) and backup/revert
behavior. Whole development suite: 34 tests. These use mock dependencies; live
freshness/concurrency have not been proven. Complete-module syntax and exact
V4 apply/idempotence/byte-exact revert are checked separately.

## CLI trial, then coordinated gateway activation

Run ONE ordinary CLI search using Ember's existing state directory and familiar
query. Do NOT use search-phase-probe.cjs: its package is V4-specific and its
suppression would confound validation of the installed V5 change. No diagnostic
preload is required. Keep private results local. Report exit, elapsed time,
count and relevance. CLI startup can still make total time around tens of
seconds; the goal here is no renewed maintenance-driven multi-minute run.

A running gateway retains previously loaded code. Restart ONLY
openclaw-ember.service after Sam agrees to the brief interruption and the CLI
trial succeeds. Use the corrected service identity confirmed by Blade. Record
its new invocation/start, verify ready, then test actual memory_search. Report
first-call timing and relevance; warm timing is separate evidence. Do not
increase the 15-second tool timeout to pass the test. If the first call times
out, retain that result and follow the tool's cooldown before one warm retry.

Verify freshness using a temporary synthetic Markdown file under Ember's
watched memory directory (unique filename/phrase, no personal data). Record
when it was created; allow the existing watcher/debounce to index it, then use
the gateway search to find it. Report timing and whether the source is the test
file, not merely a transcript mentioning the phrase. Remove only that test
file afterward; verify its indexed source disappears through normal updates.
Do not force-index to make this test pass. If creation or deletion is not
reflected, retain the failure and investigate background indexing before
declaring production freshness restored. Do not repeatedly search to provoke
maintenance; searches deliberately no longer do that.

No archive cleanup, VACUUM, cache pruning, or unrelated changes during trials.
This file change affects future loaders of this shared installation; coordinate
any other agent's activation separately. Do not restart Blade.

## One-command V5-only revert

```
python3 -B scripts/patch_search_published.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert
```

This restores V4, leaves V2/V3 intact, and selects only V5 backups even though
V4 patched the same file. It refuses to overwrite later edits. A second revert
does not roll back V4. It does not undo database writes made by searches.
Already-running processes keep loaded code; reverting an activated gateway
also requires a coordinated Ember-only restart. Reinstall removes these code
patches; do not apply to an unreviewed newer version.
