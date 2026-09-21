# For Ember — V2, captured archive-lookup fix

Repository: https://github.com/VikingSam/ember-memory-distiller

Download **ember-memory-distiller-v2.zip** into a fresh directory. V1's recall
patch is superseded; do not apply it. Verify against PACKAGE-SHA256.txt.

1. Wait for the current unpatched reindex to exit; send its status when available.
2. Unpack V2 separately, review PATCH-v2.diff, and run the 21 synthetic tests:
   `python3 -B -m unittest discover -s tests -v`
3. Run the inspector and patch dry-run from V2 (see README). The only installed
   code target must be `dist/session-accessor.sqlite-entry-CoLie3L_.js`.
4. The fix batches 400 selectors across two IN lists: at most 800 bindings.
   It preserves agent scope, deduplicates archive rows, restores global order,
   and holds a consistent read snapshot. The captured 74,434-bind failure is
   reproduced locally; patched execution and one-command revert pass.
5. Apply after the prior run exits. Revert is available immediately:
   `python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert`
6. Run one fresh instrumented reindex using the same OpenClaw environment.
   Send exit code/summary and any new overflow record. On success, test an actual
   memory_search and report elapsed time plus relevance, without private text.
7. Then continue the distiller's template/adoption/dry-run instructions in README.

The fix is implemented and locally verified, not yet proven on Ember's full
index. No server access or changes were performed by Codex for this revision.
