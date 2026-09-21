# For Ember — delivery revision

Delivery repository: https://github.com/VikingSam/ember-memory-distiller

Download ember-memory-distiller-v1.zip from that repository, then unzip it.
The repository carries the distributable ZIP; run the code from its unpacked
ember-memory-distiller directory. Nothing is automatically installed on your server.

1. Once published, download and unpack outside `memory/`, for example at
   `/home/ubuntu/ember-memory-distiller`. No server shell access is needed by Codex.
2. Run `python3 -B -m unittest discover -s tests -v` from the unpacked directory.
   All 21 tests pass locally, including restoration of the exact patch target.
3. For a READ-ONLY first diagnostic, run:
   `python3 -B scripts/inspect_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw`
   Return the JSON. It contains public-code filenames, hashes, and match flags.
   If available, also return a manually sanitized EXISTING error stack containing
   only JavaScript filenames and line/column numbers. No memory/config/DB/log dump.
4. Do not apply the batching patch yet: the tested unbounded recall query has
   not been established as the cause of your forced-index failure. A forced
   reindex is NOT read-only; the README labels it separately now.
5. The patch changes only this installed code file:
   `/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/engine-storage-MMPynmDa.js`.
   It additionally creates an original-file backup and manifest under the
   installed package's `.ember-distiller/backups/ID/` directory.
6. The one-command revert from the unpacked directory is:
   `python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert`
   It refuses to overwrite later code edits and preserves the patched copy.
7. For the distiller, follow README: configure your existing marked template,
   preview `--adopt --dry-run`, then preview a dated nightly run. Keep private
   diffs local. DeepSeek is invoked by a normal extraction dry-run; `--items`
   is the offline option. No provider fallback or credentials in this package.

Nothing has been installed on the server, and no live memory has been changed.
The package contains code, documentation, and synthetic tests only.
