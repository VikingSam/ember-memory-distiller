# For Ember — V3 tombstone lookup fix

Repository: https://github.com/VikingSam/ember-memory-distiller
Download ember-memory-distiller-v3.zip, verify PACKAGE-SHA256.txt, and unpack
separately. Keep V2 applied. V1 is obsolete.

1. Wait for the currently executing reindex to exit and report its status.
2. Read PATCH-v3.diff and README's V3 section; run all 23 tests locally.
3. Use scripts/inspect_openclaw.py to check V2 and V3 statuses.
4. Preview then apply scripts/patch_tombstones.py with the same --package-dir
   as V2. Exact target: dist/memory-entry-origins-DHPCnUGh.js.
5. One-command rollback that LEAVES V2 APPLIED:
   python3 -B scripts/patch_tombstones.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert
6. Start one fresh instrumented reindex using the existing profile/environment.
   Return its exit code, summary, and any new SQLITE_BIND_OVERFLOW record.
7. On clean completion, measure actual memory_search elapsed time and relevance.

The captured tombstone query has ONE IN list plus agent_id, not two IN lists:
37,706 session IDs + 1 agent binding = 37,707. V3 caps each query at 401 bindings.
The installed target is directly under dist/, not dist/extensions/memory-core/.

Synthetic tests reproduce the original overflow and validate the fix. Full
live indexing is not yet verified. This revision involved no server access.
