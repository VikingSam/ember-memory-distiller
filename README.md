# Ember memory distiller — V1 review package

Built for Ember to run locally. No server installation, cron changes, reindex,
provider call, or live memory changes were performed by this package's author.
The package contains code and synthetic tests only; no private memory samples.
Python 3.10+ on Linux/macOS. No third-party Python dependencies. Node is needed
only for the OpenClaw regression tests and diagnostic.

## Current delivery status

- Distiller implemented and tested locally: DeepSeek v4 Pro JSON extraction,
  deterministic routing/writes, linked entity/project pages, ceilings, whole-item
  demotion, backups, dry-run, same-date idempotence, restore, and change logs.
- Found a real unbounded `readMemoryRecallMetadata` query in the public
  `openclaw@2026.8.1` npm tarball. A version- and code-matched patch batches it at
  400 IDs. It is **not yet established as Ember's indexing failure**. The public
  package already batches embedding-cache reads at 400 hashes, cache writes at
  seven bindings, and chunk writes individually. Do not call JOB 1 resolved yet.
- A synthetic regression feeds the exact original/patched JavaScript function
  18,918 IDs through a query-builder bridge, then runs the resulting batches on
  real SQLite with its variable limit set to 999. Original fails; patched reads
  all 18,918 rows. This is a function-level reproduction, not a full OpenClaw
  CLI reindex or a live Voyage benchmark.
- Live DeepSeek credentials/config shape, real transcript naming, indexing
  failure callsite, and sub-five-second `memory_search` remain to be validated
  by Ember. No embeddings provider is changed.

## Download

Download [ember-memory-distiller-v1.zip](https://github.com/VikingSam/ember-memory-distiller/raw/refs/heads/main/ember-memory-distiller-v1.zip)
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

## JOB 1: diagnose the actual indexing failure first

Start with this strictly read-only inspection. It reads installed public code
and package metadata only, never config, memory, logs, databases, or transcripts.
Return its JSON report. This confirms whether Ember has the same code as the
public package; it cannot by itself identify the runtime failure.

```sh
python3 -B scripts/inspect_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
```

To identify the failure without rerunning indexing, also return any **already
captured, manually sanitized** error stack with just JavaScript basenames and
line/column numbers. Do not export unrestricted logs. If that stack does not
exist, stop here: a new reproduction needs a separately agreed reindex.

### Optional reproduction — NOT read-only

The following command writes the index and may incur embedding costs. Do not
run it as part of the read-only inspection above.

Run this with Ember's existing profile/config environment, adding the preload
only for this invocation. The diagnostic prints no SQL text or binding values;
its own output is restricted to a SQL hash, placeholder count, and JS basenames
with line numbers. OpenClaw's own output is separate and must be reviewed before
sharing. Forced indexing can call Voyage and consume embedding credits, just as
Ember's original reindex command does.

```sh
NODE_OPTIONS="${NODE_OPTIONS:-} --require=/home/ubuntu/ember-memory-distiller/scripts/sqlite-diagnostic.cjs" openclaw --profile ember memory index --force --agent main
```

Return only the `SQLITE_BIND_OVERFLOW` diagnostic record first. Do not send
memory databases, transcripts, config files, keys, or whole unrestricted logs.
If no diagnostic appears, report that fact and a sanitized stack trace; the
failure may use a different SQLite implementation or process.

The confirmed recall-query patch is optional pending the callsite result:

```sh
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --dry-run
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw
```

**This patch lives in node_modules.** Re-run the same script after a reinstall of
2026.8.1. It is idempotent, backs up code before writing, and refuses an unknown
version or changed function. It does not silently patch future releases or
restart agents. A shared installation may serve Blade too: the change affects
new processes loading that installation. Coordinate locally before applying.
Restore using `--package-dir ... --restore BACKUP_ID`. npm reinstall may remove
backups inside the old package directory, so copy that backup directory outside
node_modules if rollback across reinstall is required.

JOB 1 acceptance still requires a successful full index and a real Ember
`memory_search` result in under five seconds. Timing an isolated SQL query or
seeing “ready” is not that proof. Capture local elapsed time plus result count;
keep the private result text on the server.

## Exact patch footprint and pre-agreed rollback

The patch now accepts only this installed code target:

`/home/ubuntu/.npm-global/lib/node_modules/openclaw/dist/engine-storage-MMPynmDa.js`

Its only additional durable writes on apply are:

- `openclaw/.ember-distiller/backups/ID/0` — original code bytes
- `openclaw/.ember-distiller/backups/ID/manifest.json` — hashes and commit status

It does not modify package.json, memory files, databases, config, credentials,
Voyage settings, cron, or services. Temporary sibling files are used for atomic
replacement. A different hashed filename is rejected rather than guessed.

One-command revert, from the unpacked package directory:

```sh
python3 -B scripts/patch_openclaw.py --package-dir /home/ubuntu/.npm-global/lib/node_modules/openclaw --revert
```

Revert selects the latest active backup for this exact target and rejects later
code edits. It restores the original bytes, marks the manifest restored, and
preserves the replaced patched file under
`openclaw/.ember-distiller/restore-archives/ID/dist/engine-storage-MMPynmDa.js`.
Keep backups outside node_modules as well before any reinstall.

## Diagnostic follow-up

The public CLI catches the failure in `dist/cli.runtime-Bmy6tBkC.js:708` and
prints its message. An uncaught-exception handler or larger stack limit cannot
recover a stack discarded by that catch. The preload in
`scripts/sqlite-diagnostic.cjs` intercepts `DatabaseSync.prepare` before it.
It emits only a SQL hash, approximate placeholder count, and basename:line:column
callsites. It does not print SQL or bound values. The added regression verifies
capture even when an outer handler catches the error, including paths with spaces.

The standalone updated preload is also available at `scripts/sqlite-diagnostic.cjs`
in the repository. A synthetic `:memory:` database can test it without opening
OpenClaw data. Instrumenting a real reindex still writes the index and is a
separate step; do not launch overlapping reindexes. Existing processes cannot
acquire a new NODE_OPTIONS preload after launch. Slow transaction warnings alone
do not identify the oversized statement.
