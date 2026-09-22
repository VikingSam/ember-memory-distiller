# Search-triggered gateway diagnostic v1.3

This replaces v1.2: it arms at startup but records only when the FIRST
memory_search tool executes. The 180-second recording no longer expires
during quiet startup. It includes tool entry, the existing deadline, manager
acquisition, retrieval, and session visibility filtering. It changes no search
behavior or timeout. The arm expires after 15 minutes if no search arrives.

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
- A Node loader transforms the exact V5 manager and stock tools-DNmkgIrY.js in memory. Maintenance, retries,
  timeouts, locks, sync configuration, V2/V3/V4/V5 behavior stay in place.
- Existing async operations are wrapped for timing; a local V8 inspector
  session samples CPU stacks every 10 ms. No inspector TCP port is opened.
  Instrumentation has overhead; this is not a clean latency benchmark.
- Capture lasts 180 seconds from the first memory_search execution per gateway
  process. Before that, only a fixed armed record and tool-hook readiness
  record are emitted; no CPU profiling occurs. The first call waits for local
  profiler initialization before invoking the unchanged tool. If the event
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
and the extracted SHA256SUMS. As the service-owning account on Linux (systemctl and busctl required), from that directory, set these shell variables
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

Thirteen packaged tests cover privacy, async parent correlation, error/result
preservation, release on failure, capture expiry/cap, actual local CPU-profiler
lifecycle, safe service scope, preservation of existing NODE_OPTIONS/environment files, journal export field
filtering, stage/remove drift protection, typed launch metadata, automatic
rollback on readback mismatch, and CPU-stall attribution through native calls.
Both complete transformed public modules were separately syntax-checked locally.
Tests also cover idle arming, expiry without a search, one-shot capture, and
tool receiver/argument/result/error preservation.
These are local tests, not live gateway proof.

Preflight reads package files, systemd properties and the live MainPID's
process environment. From that environment it selects only the state-dir,
service-unit and NODE_OPTIONS fields; nothing is exported. It does not read
EnvironmentFiles or invoke OpenClaw or open the DB. NODE_OPTIONS is only
checked for an already-installed diagnostic; its contents are never copied
into the drop-in or output.

Typed launch metadata is read using busctl --user --json=short and systemd's
ExecStartEx property. Exactly one ordinary direct Node gateway command is
supported. Shell wrappers, custom argv[0], special execution flags and dollar
variable expansion are refused rather than reconstructed approximately.

It also refuses unexpected hashes/identities, inactive services or existing
diagnostics. If it refuses, send only the fixed refusal message. Never paste
environment values or a full launch command containing private arguments.

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
and its `.sha256` ownership record, both created with mode 0600. The helper
resets and replaces ONLY ExecStart with the original Node command plus
--require and the diagnostic path. It adds diagnostic scope variables.
Existing Environment and EnvironmentFiles remain in effect unchanged;
NODE_OPTIONS is not set, cleared or concatenated. No environment secrets are
copied or printed. Original launch arguments are retained locally in the
protected drop-in, so keep it private if the original command has private
arguments. The drop-in disappears on reboot. No other unit is touched.

After daemon-reload, the helper reads ExecStartEx back. If the resulting
command is not the original command plus the intended preload, it removes
its own override, reloads again, and reports failure without restarting.

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

After the approved restart and readiness, remove the temporary drop-in as
above. Confirm an `armed` record for the new gateway PID. Within 15 minutes
of startup, coordinate EXACTLY ONE normal gateway memory_search using the
same familiar query. This new captured call is separate from the already
reported failed check; it is not a request to repeat the old check now.
Do not use CLI search, alter the 15-second timeout, or retry on failure.

If a normal search has already triggered capture, do not add another. Keep
watcher-addition/removal tests deferred. Do not add synthetic files, force-index,
cleanup, prune, VACUUM, or health probes. The recorder does not call a search
itself. It follows natural continuation for 180 seconds after the first call,
including operations that outlive the tool timeout. Do not extend/repeat.

A `tool_hook_ready` record proves the tool module was instrumented. If the
controlled call produces no `capture_start`/`tool_call`, report that; the live
load path was not established. Do not interpret missing phases as idle work.
If `arm_expired` appears instead, send that and stop without rearming.

Obtain the new invocation ID with systemctl (OS metadata only):

```
systemctl --user show "$TRACE_UNIT" -p InvocationID --value
python3 -B scripts/collect_gateway_trace.py --unit "$TRACE_UNIT" --invocation <NEW_INVOCATION_ID> > gateway-trace.jsonl
```

The collector reads only that service/invocation's existing journal and exports
only lines starting `EMBER_GATEWAY_TRACE ` with diagnostic event names. It
does not export ordinary logs or start any OpenClaw work. Forward that JSONL. Keep other stderr, query text, content and provider errors local.
Records required: armed, tool_hook_ready, capture_start, tool_call, health records,
start/end pairs (or active IDs at capture_end), capture_end, cpu_samples.
Both launcher/child PIDs may appear; correlate records by PID.
module_loaded mode=observe-v5 appears if the manager loads during capture;
if already loaded while armed, later manager_get/search phases establish it. Keep the IDs, timestamps and parent links intact.

If capture_end is not yet present after 180 seconds, an event-loop stall may
have delayed its callback. Do not restart just to produce the record. Report
missing records and current service responsiveness from passive evidence.

## Interpretation

- `tool_call` wraps the actual tool execution. `tool_deadline` wraps the
  original deadline without replacing it. `manager_context` includes lazy
  loading and manager acquisition. `tool_query` includes retrieval and the
  `visibility_filter` phase, which CLI-only tests may not exercise.
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
- CPU samples attribute synchronous busy work while timers cannot run. Each sample is counted once, NOT once per ancestor. `leaf` means the
  sampled frame itself; `openclaw_caller` means native/Node/dependency work
  attributed to its nearest public dist ancestor; `unattributed` means no such
  ancestor was found. Counts are NOT milliseconds or lock wait time. Worker/subprocess CPU is
  outside this profiler; missing samples are not proof those workers are idle.
- CPU line numbers identify function starts, not sampled instructions. They
  refer to the IN-MEMORY instrumented V5 module. Use
  GATEWAY-TRACE.diff to map manager and tools locations; other dist modules are unchanged.
- No database query counters are included. A long async phase alone cannot
  establish that SQL was idle or a database transaction was held.

Checks for gateway retrieval and normal watcher additions/removals stay
pending. This recording does not itself establish that memory is fixed.

## API reference for local review

The helper uses the typed ExecStartEx property, documented in the official
systemd D-Bus interface, rather than parsing a shell command from human output:
https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
Source form: https://github.com/systemd/systemd/blob/main/man/org.freedesktop.systemd1.xml
No service has been restarted by local packaging/tests. The service tests use
synthetic systemd responses; actual typed readback is checked on the target
before any restart.
