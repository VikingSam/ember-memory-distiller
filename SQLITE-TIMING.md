# Process-local SQLite timing

Use `scripts/sqlite-timing.cjs` as a Node preload for one already-authorized
CLI memory search using Ember's existing configuration. Do not attach it to the
gateway, restart services, or modify installed OpenClaw files.

The hook itself reads no files/configuration and makes no network requests.
The underlying search retains its normal behavior: provider requests and
possible synchronization/index writes. This is **not a read-only search**.

Output lines start with `EMBER_SQL_TIMING `. Only relay these diagnostic JSON
records, not ordinary CLI results or stderr. Each record includes PID and
milliseconds since that process loaded the hook; inherited child processes
may have separate timelines. Database numbers are process-local, not paths.

The hook times prepare, exec, all/get/run, and iterator calls. Calls of at least
250 ms emit immediately. Exit emits the top 30 aggregated callsite groups,
including many individually fast statements. Locations contain only file
basenames and line/column numbers; SQL, bound values, results, paths, and error
messages are not emitted. Errors still propagate unchanged to the application.

Transaction records cover standalone BEGIN through entry to COMMIT/ROLLBACK,
excluding boundary execution time. `sql_ms` sums instrumented SQLite calls
inside that interval. SAVEPOINT operations appear as statements inside the
outer transaction; nested transaction timings are not independently emitted.
Compound exec strings and transactions started through prepared statements
are not recognized as transaction boundaries. Failed transaction-end calls
do not emit completed transaction records. Slow boundary calls still appear
as `slow_sql` records. Callsites for statements are captured at preparation.

Instrumentation adds overhead, especially for many iterator steps. Use this
for attribution, not a precise production benchmark. Do not sum transaction
and statement times: they overlap. No direct embedding/FTS/vector phase or
generation-lease timers are added; SQL callsites identify the next targeted
phase if the database work does not account for the delay.

Use a fresh private temporary directory for the downloaded hook and local
stdout/stderr capture. Download and inspect before execution. Preserve any
existing NODE_OPTIONS, adding --require only on that one command. Revert is
simply the next command without the added --require; nothing persists in the
service environment or installed package. Do not force-kill a running search
just because a 15-second tool deadline has passed.

Validated locally on Node 22.17.1 with synthetic in-memory SQLite: statement
results, iterator exhaustion/early return, original error propagation,
nested savepoints, commit/rollback, slow statement attribution, and suppression
of SQL, bind values, and directory paths.
