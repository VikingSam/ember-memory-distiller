# Bounded gateway memory diagnostic v1

This is an observational diagnostic, not V6 and not a search fix. The goal is
to distinguish background indexing, provider checks, search requests, lock
waiting and synchronous CPU work. A plain batch-embedding retry warning can
come from indexing or a provider probe. This trace adds nested operation IDs
and CPU samples without embedding any deployment identity in the package.

## Scope

The preloader verifies the configured state directory and service identity
against the operator-supplied scope. The setup helper verifies that scope
before producing a runtime drop-in. It has no default target.

- Exact OpenClaw 2026.8.1 V5 manager hash required:
  `e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df`.
- No installed OpenClaw file changes, database opens, direct SQL, searches,
  provider requests, or indexing commands are performed by the diagnostic.
  The running gateway continues its normal work, which can write and use APIs.
- A Node loader transforms only that manager in memory. Maintenance, retries,
  timeouts, locks, sync configuration, V2/V3/V4/V5 behavior stay in place.
- Existing async operations are wrapped for timing; a local V8 inspector
  session samples CPU stacks every 10 ms. No inspector TCP port is opened.
  Instrumentation has overhead; this is not a clean latency benchmark.
- Capture lasts 180 seconds from preload per gateway process. If the event
  loop stalls, finalization runs when it becomes schedulable; it is not a hard
  real-time timer. Phase records stop after the deadline. Up to 2,000 regular
  records plus cap/end/profile records are emitted. Timers do not keep a
  process alive. A process killed early may have no capture_end/profile.
- After expiry wrappers delegate without recording; existing in-memory
  wrappers/loader remain until normal restart. This is not a recurring job.
- Fixed labels, integer IDs, safe sync reasons, batch sizes, timing,
  allowlisted error classes only. No inputs, outputs, error messages, SQL,
  bind values, auth headers, credentials, configuration dump or transcripts.
  CPU output contains only OpenClaw dist basenames and line numbers; external
  paths/functions collapse into `outside-openclaw`. Full CPU profiles remain
  in memory and are never written. Existing ordinary gateway logs remain
  private and may contain content; do not forward them.

## Review and preflight — no restart needed

Extract outside the gateway's watched/indexed workspace into a persistent
operator-owned directory. Supply the intended deployment identity LOCALLY.
No server paths or unit names are provided by this public package.
Read the five scripts, tests, and this handoff. Verify the archive checksum
and the extracted SHA256SUMS. As the service-owning account, from that directory, set these shell variables
to the verified local values (the examples are placeholders, not commands
ready to run):

```
TRACE_UNIT='your-approved-unit.service'
TRACE_STATE='/absolute/path/to/your/state'
TRACE_PACKAGE='/absolute/path/to/node_modules/openclaw'
```

Then:

```
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_gateway*.py' -v
python3 -B scripts/gateway_trace_service.py --check --unit "$TRACE_UNIT" --state-dir "$TRACE_STATE" --package-dir "$TRACE_PACKAGE"
```

Eight packaged tests cover privacy, async parent correlation, error/result
preservation, release on failure, capture expiry/cap, actual local CPU-profiler
lifecycle, safe service scope, preservation of existing NODE_OPTIONS, journal export field filtering, and stage/remove drift protection without restarting.
The complete transformed V5 module was separately syntax-checked locally.
These are local tests, not live gateway proof.

Preflight reads package files and systemd properties; it does not invoke
OpenClaw or open the DB. It refuses an unexpected hash, service identity,
inactive service, preexisting diagnostic, or EnvironmentFiles whose precedence
would make blindly combining NODE_OPTIONS unsafe. If it refuses, report only
the fixed refusal message. Do not work around it or paste environment values.

## Activation — ONE coordinated restart of the explicitly approved unit

A gateway restart is required to load this diagnostic and briefly interrupts
service. Obtain the service owner's approval before activation. Stage only
after review. The helper never restarts anything by itself. Verify the unit
selection locally; do not use another agent's service or a generic alias.

```
python3 -B scripts/gateway_trace_service.py --stage --unit "$TRACE_UNIT" --state-dir "$TRACE_STATE" --package-dir "$TRACE_PACKAGE"
systemctl --user restart "$TRACE_UNIT"
```

The sole service change is a new runtime drop-in:
`/run/user/<uid>/systemd/user/<approved-unit>.d/90-ember-memory-trace-v1.conf`
and its `.sha256` ownership record. It preserves existing service Environment
NODE_OPTIONS and appends the preload. Other environment values are not copied
or printed. The drop-in disappears on reboot. No other unit is touched.

Read existing journal readiness and record the new gateway PID/invocation. Do
not run OpenClaw status or a CLI search. Once ready, remove the drop-in now:

```
python3 -B scripts/gateway_trace_service.py --remove --unit "$TRACE_UNIT"
```

Removal runs daemon-reload but NO restart. It prevents the probe from loading
again on a later restart while the current process completes its capture.
If startup fails, remove the drop-in immediately and coordinate a recovery restart of the same approved unit with its owner. No package revert is needed for this diagnostic.
The existing V5 backup/revert remains independent and unchanged.

## Capture

Let normal gateway activity run for the one 180-second capture. Do not add a
search, synthetic file, force-index, cleanup, prune, VACUUM, or health probe to
stimulate it. Keep existing logs local. If there is no relevant activity in
this window, report that; do not silently extend or repeat the experiment.

Obtain the new invocation ID with systemctl (OS metadata only):

```
systemctl --user show "$TRACE_UNIT" -p InvocationID --value
python3 -B scripts/collect_gateway_trace.py --unit "$TRACE_UNIT" --invocation <NEW_INVOCATION_ID> > gateway-trace.jsonl
```

The collector reads only that service/invocation's existing journal and exports
only lines starting `EMBER_GATEWAY_TRACE ` with diagnostic event names. It
does not export ordinary logs or start any OpenClaw work. Forward that JSONL. Keep other stderr, query text, content and provider errors local.
Records required: capture_start, module_loaded mode=observe-v5, health records,
start/end pairs (or active IDs at capture_end), capture_end, cpu_samples.
Both launcher/child PIDs may appear; only the PID emitting module_loaded owns
these manager phases. Keep the IDs, timestamps and parent links intact.

If capture_end is not yet present after 180 seconds, an event-loop stall may
have delayed its callback. Do not restart just to produce the record. Report
missing records and current service responsiveness from passive evidence.

## Interpretation

- `startup_catchup` includes startup inspection; its return does NOT mean the
  detached sync finished. Follow the child `sync_admitted`/`sync_pass` IDs.
- `sync_admitted` with reason watch/session-delta/session-startup-catchup
  identifies the caller even when its work waits on an existing sync.
- `provider_probe`/`bootstrap_probe` vs `memory_files`/`session_files` ancestry
  distinguishes health probes from actual indexing batches.
- `embedding_request` reports EACH attempt and a coarse error classification;
  retry_sleep is separate. Lack of a status remains `other`, never guessed.
- `generation_write_wait` and `generation_write_hold` are distinct.
  `generation_read_wait` measures reader admission, not retrieval.
- `workspace_operation` covers wait + body + release. `workspace_hold` begins
  inside the original callback. Reentrant scopes can overlap; don't sum them
  or call the outer interval pure waiting.
- CPU samples attribute synchronous busy work while timers cannot run. Counts
  are exclusive sampled stacks, NOT milliseconds or lock wait time. Native
  work may be attributed to its JavaScript caller. Worker/subprocess CPU is
  outside this profiler; missing samples are not proof those workers are idle.
- CPU line numbers refer to the IN-MEMORY instrumented V5 module. Use
  GATEWAY-TRACE.diff to map manager locations; other dist modules are unchanged.
- No database query counters are included. A long async phase alone cannot
  establish that SQL was idle or a database transaction was held.

Checks for gateway retrieval and normal watcher additions/removals stay
pending. This recording does not itself establish that memory is fixed.
