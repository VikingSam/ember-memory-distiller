# Ember memory distiller — V2 review package

Built for Ember to run locally. No server installation, cron changes, reindex,
provider call, or live memory changes were performed by this package's author.
The package contains code and synthetic tests only; no private memory samples.
Python 3.10+ on Linux/macOS. No third-party Python dependencies. Node is needed
only for the OpenClaw regression tests and diagnostic.

## Current delivery status

- Distiller implemented and tested locally: DeepSeek v4 Pro JSON extraction,
  deterministic routing/writes, linked entity/project pages, ceilings, whole-item
  demotion, backups, dry-run, same-date idempotence, restore, and change logs.
- JOB 1's captured stack identifies `listSessionTranscriptArchivesReadOnly` in
  `dist/session-accessor.sqlite-entry-CoLie3L_.js`. Two unbounded IN lists produce
  74,434 bindings for 37,217 unique selectors. V2 batches 400 selectors per query
  (800 bindings), deduplicates by unique archive name, restores global ordering,
  preserves agent filtering, and holds one read snapshot using a savepoint.
- The earlier memory-recall patch was not the captured failure and is superseded.
  Do not apply the V1 patch. V2 does not modify that recall bundle.
- The 21-test suite includes the original failure on real in-memory SQLite at
  74,434 binds, patched query execution under an additional 999-binding guard,
  result/order equivalence, cross-batch duplicates, agent filtering, empty and
  missing databases, nested transactions, failure recovery, and query-only mode.
  Patch apply/revert and JS syntax were also checked on the public package locally.
- Live DeepSeek credentials/config shape, real transcript naming, post-patch indexing
  completion, and sub-five-second `memory_search` remain to be validated
  by Ember. No embeddings provider is changed.

## Download

Download [ember-memory-distiller-v2.zip](https://github.com/VikingSam/ember-memory-distiller/raw/refs/heads/main/ember-memory-distiller-v2.zip)
and unzip it into a separate working directory. This repository distributes the
complete source/tests as a ZIP. Read `EMBER-HANDOFF.md` first. Nothing installs
itself or contacts Ember's server merely by downloading.

## Start here

Unpack outside the indexed memory tree, for example `/home/ubuntu/ember-memory-distiller`.
From that package directory:

```sh
python3 -B -m unittest discover -s tests -v
cp config.example.json config.json
```

Set `entity_template` in `config.json` to Ember's existing template, relative to
her workspace. A compatible template needs `{name}` and exactly one marker pair:

```markdown
# {name}

## The flood
<!-- ember:flood:start -->
<!-- ember:flood:end -->
```

If she has no template, `templates/entity.md` is the supplied starting point.
Copy it to `bank/templates/entity.md` only if that destination does not already
exist. Existing templates should be backed up before Ember adds the markers.
No personal text needs to leave her server for this setup.

## First migrate the Tier-1 boundaries

Existing unmarked pages stop the nightly run before any write. Migration is an
explicit separate operation. It archives each complete original verbatim to
Tier 2, preserves a recognized `## ... The flood` section up to the next heading
or horizontal rule, creates the marked template page, and links the archive.
Pages without a recognized flood section get a link to their entire original;
Ember should compose/review their short headlines before enabling cron.
Marked pages are left in place. No LLM is called during migration.

```sh
sh scripts/nightly.sh --adopt --dry-run
sh scripts/nightly.sh --adopt
```

Review migration output **on the server**. A dry-run diff contains memory text;
redact private information before sharing any portion with Sam/Codex. Credential
redaction is defense in depth, not a guarantee that arbitrary prose is public.

## Preview and run

```sh
sh scripts/nightly.sh --date 2026-09-20 --dry-run
sh scripts/nightly.sh --date 2026-09-20
```

Default date is yesterday in `America/Chicago`, configurable in `config.json`.
Sources are `memory/YYYY-MM-DD.md` and `memory/transcripts/YYYY-MM-DD*.md`.
Missing dated input fails visibly without marking the date complete. Supply a
redacted filename example if Ember's transcripts use a different convention.

Dry-run prints a redacted unified diff and writes no workspace files, backups,
state, or lock files. Use the supplied wrapper or `python3 -B` to also suppress
Python bytecode caches. **Dry-run still calls the approved DeepSeek API**, so it
has API cost and sends redacted source chunks to that configured provider.
`--items /path/to/items.json` instead validates a previously prepared extraction
and makes no model call. Copy the JSON item shape from `PROMPT` in
`ember_memory/distiller.py` when producing a fixture.

The adapter reads the existing `models.providers.deepseek` entry from
`/home/ubuntu/.openclaw-ember/openclaw.json` at runtime. It supports a literal key,
`${ENV_NAME}`, or an environment SecretRef. File/exec SecretRefs and JSON5 are
not silently guessed: unsupported configuration fails with no memory changes.
Set `EMBER_OPENCLAW_CONFIG` to override the config location. No key is embedded
in this package, command line, or logs. HTTP response bodies are not logged.
Only `deepseek-v4-pro` is requested; there is no fallback model/provider.

Extraction uses DeepSeek's documented JSON response mode:
https://api-docs.deepseek.com/guides/json_mode/
All chunks must succeed and pass schema, path, length, secret-pattern, and exact
source-quote validation before the first write. The model supplies text fields;
code escapes markup and owns the final Markdown and links. Source quotes support
review but cannot mathematically prove that a model's paraphrase is faithful.
Common labeled credentials, private-key blocks, and known token formats are
removed before extraction. Unlabeled/novel secrets still require source hygiene.

## Ceiling and retention semantics

- `CORE.md`: at most 8,000 Unicode characters in the full file. No automatic
  model-written identity additions. Overflow moves complete Markdown blocks to
  Tier 2, creates a Tier-1 `core-context` headline, and links it from CORE.
- Tier-1 flood content: at most 2,500 Unicode characters between markers. New
  headlines are one line and at most 180 characters before escaping/link markup.
  Existing wrapped bullets/feeling paragraphs are retained as indivisible units.
  Overflow moves whole units to Tier 2 and leaves a bounded archive pointer.
- Every existing entity/project page is checked on each new successful day.
  Both `bank/entities/` and `bank/projects/` are supported. Slugs must be unique
  across these directories; ambiguity stops the run instead of misrouting.
- New facts and related-page links update reference timestamps. Record actual
  on-demand reads with the reference hook below. Without that integration,
  historical reference times are unknown and sort oldest, with file order used
  to break ties. Filesystem access times are deliberately not treated as proof.
- Duplicate same-entity/kind/source-quote facts are suppressed even when the
  model paraphrases the headline. This is evidence-based deduplication, not a
  claim of perfect semantic duplicate detection across unrelated quotations.
- Completion is keyed by source date. Running the completed date again does
  nothing, even if its source file has changed. Late additions require an
  explicit reviewed follow-up date/input; automatic rewrites are not inferred.
- No historic corpus backfill is performed. Nightly processing begins with the
  requested day. Backups and Tier-2 archives grow intentionally; loaded tiers
  stay bounded. No automatic retention deletion is included.

After reading a Tier-1 page, Ember can record that reference:

```sh
sh scripts/nightly.sh --reference bank/entities/example.md
```

The hook defaults to today; `--date` can supply an explicit reference date.
`CORE.md` is also supported. This is an integration hook, not an installed
OpenClaw read interceptor.

## Recovery

Every commit prints its backup ID and exact restore command. Originals, hashes,
and a manifest are saved before any target write in
`.ember-distiller/backups/ID/`. State and logs are included. Restore checks for
later edits before changing anything and archives superseded/new files instead
of destroying them.

```sh
python3 -B -m ember_memory.distiller --root /home/ubuntu/ember --restore BACKUP_ID
```

An interrupted commit blocks the next run until restored. Each individual file
write is atomic; the whole multi-file operation is recoverable, not a single
filesystem transaction. A directory lock serializes this program's runs, and
content checks reject observed concurrent edits. Other writers must coordinate
or pause during the brief commit; an unrelated writer ignoring the lock can
still race a filesystem rename. Run the nightly job during Ember's quiet window.

## Cron (Ember installs after reviewing a successful run)

Add this to **ubuntu's existing crontab**; do not replace other jobs. It runs at
03:17 in the server's timezone; the source date uses the configured timezone.
Choose a different server-time schedule if needed. Keep cron failure mail or
an existing local alert mechanism enabled so extraction failures are visible.

```cron
17 3 * * * /bin/sh /home/ubuntu/ember-memory-distiller/scripts/nightly.sh
```

Human-readable change logs are `memory/distill-log-YYYY-MM-DD.md`.

## JOB 1: V2 patch for the captured archive lookup overflow

The current unpatched reindex must exit before applying this patch. No running
process is stopped or restarted by the package. Review `PATCH-v2.diff` first.
From the freshly unpacked V2 directory:

```sh
python3 -B scripts/inspect_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --dry-run
```

The sole modified installed code file is:

`/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/session-accessor.sqlite-entry-CoLie3L_.js`

Additional apply writes under that installed package are only the original
backup `.ember-distiller/backups/ID/0` and its `manifest.json` (plus transient
atomic-write files). No memory, database, configuration, provider, cron, or
service changes are made by the patch script. Because the package is shared,
new Blade processes loading this file also receive the bounded lookup.

After the existing run exits and the dry-run shows exactly that target:

```sh
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
```

One-command revert, available before apply:

```sh
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert
```

Revert restores the latest active backup for the V2 target and refuses to
overwrite later code edits. It keeps the patched copy in
`.ember-distiller/restore-archives/ID/dist/session-accessor.sqlite-entry-CoLie3L_.js`.
An explicit older backup can instead be selected with `--restore BACKUP_ID`.

**The fix lives in node_modules.** Re-run V2's patch script after reinstalling
2026.8.1. Exact version/function matching rejects unknown code; repeated apply
is a no-op. Copy backups outside node_modules before a reinstall if needed.

For validation, use the same working OpenClaw profile/environment as the
captured failure. Start one fresh reindex with V2's preload after the prior run
has exited. This command writes the index and uses the existing embedding setup:

```sh
NODE_OPTIONS="${NODE_OPTIONS:-} --require=$PWD/scripts/sqlite-diagnostic.cjs" openclaw memory index --force --agent main
```

Return exit code, summary, and any `SQLITE_BIND_OVERFLOW` records. A subsequent
failure may expose another oversized query; this patch targets the captured one
only. A clean index must be followed by one real `memory_search`: report elapsed
time and relevance without sharing private result text. Under five seconds with
relevant results is the acceptance target, not yet established by local tests.

The diagnostic captures `DatabaseSync.prepare` before the CLI message-only catch
at `cli.runtime-Bmy6tBkC.js:708`. It emits no SQL or values, only a hash, approximate
placeholder count, and sanitized basename/line/column callsites. Slow transaction
warnings alone are not a diagnosis.
