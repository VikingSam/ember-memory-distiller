# One-process search-stage comparison after V4

Purpose: determine the retrieval cost against the published index without
starting routine search-triggered maintenance. This is a diagnostic, not V5
or a permanent change to freshness policy. It is not a speed claim.

Requires Node with `node:module.register` (tested Node 22.17.1) and the exact
V4 manager-runtime SHA256:
`9580e3f7d3d18db3fa881e438cac96d93347a59e6e796b6a35b2733fb5f7a483`.

The CommonJS preload registers an ESM loader. The loader checks that exact
module hash, then transforms its source **in memory**. Installed files, service
configuration, and saved config are not modified. The transformation survives
only within this CLI invocation and inherited child processes. Do not configure
the preload in a service or export its environment variables globally.

`published-only` mode disables only the background-maintenance launch inside
CLI search. It does not suppress bootstrap or invalid-index repair, bypass
generation locks, or disable integrity checks. Thus the underlying search can
still write if repair is required, invoke the existing embedding provider, and
record recall metadata. It is not a read-only database operation. Results can
omit pending updates that have not been indexed. Existing background work in
other processes can still cause contention; the probe does not stop it.

`observe` mode adds identical timing without suppressing maintenance. Do not
run observe now; one published-only comparison is the requested next step.

The phase records include only PID, relative milliseconds, sequence IDs,
fixed phase names, success booleans, mode, and exit status. They never include
queries, result text, provider payloads, URLs, keys, or error messages. Ordinary
CLI stdout/stderr may contain private content and must remain local. Phases
nest and overlap; do not sum their durations. Each PID has its own timeline.

Measured phases: manager acquisition, provider initialization, sync/preflight,
background maintenance, sync passes, document and query embedding wrappers,
FTS, vector lookup, generation-read-lease acquisition, search, and close.
An embedding wrapper includes retries, not merely network transfer. Slow
module import/startup appears before module_loaded relative to preload time.

## Run

Unpack `ember-search-phase-probe.zip` into a private temporary directory, then
enter `ember-search-phase-probe/`. Review both scripts and this document.
The two scripts must remain together in scripts/.

```
python3 -B -m unittest discover -s tests -v
umask 077
phase_probe_dir="$PWD"
OPENCLAW_STATE_DIR=/home/ubuntu/.openclaw-ember \
EMBER_SEARCH_PROBE_MODE=published-only \
NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--require=$phase_probe_dir/scripts/search-phase-probe.cjs" \
openclaw memory search --agent main "YOUR LOCAL TEST QUERY" \
> "$phase_probe_dir/results.txt" 2> "$phase_probe_dir/trace.txt"
phase_probe_exit=$?
printf 'exit_status=%s\n' "$phase_probe_exit"
```

Use a temporary path without spaces for the NODE_OPTIONS example. Do not run
another diagnostic search/reindex concurrently. Leave the gateway as it is.
Do not add the old SQLite timing preload for this comparison; preserving normal
NODE_OPTIONS is fine, but remove any diagnostic --require left there from an
earlier run. Preserve unrelated required options.

Extract only diagnostic records:

```
python3 - "$phase_probe_dir/trace.txt" <<'PY'
import sys
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    for line in f:
        if line.startswith('EMBER_SEARCH_PHASE '):
            print(line[len('EMBER_SEARCH_PHASE '):], end='')
PY
```

Return these records, exit status, result count, and relevance assessment. Do
not relay ordinary output, query text, or the contents of configuration files.
Require `module_loaded` with mode `published-only` before interpreting a result
as the comparison. If the module hash is rejected or the command fails, stop
and report the sanitized error category; do not retry or alter the hash gate.

No revert command is necessary: omit this command-local preload/mode on the
next invocation. V2/V3/V4 remain as installed. A gateway restart remains a
separate, coordinated step after we have evidence for a production change.

## Validation limits

Three synthetic tests verify suppression scope, retained preflight calls,
return values, errors, sanitized phase logs, CLI-only entry gating, actual
Node loader registration, rejection of changed code, and no file modification.
The complete V4 module transforms successfully and passes syntax checking.
This has not been run against Ember's database or provider from here.
