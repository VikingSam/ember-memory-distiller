// Process-local diagnostic; no files, network, SQL, values, or error text emitted.
// Use only for the one CLI invocation being measured. No installed files change.
'use strict';
const { DatabaseSync } = require('node:sqlite');
const { performance } = require('node:perf_hooks');
const started = performance.now();
const databases = new WeakMap();
const groups = new Map();
let nextDb = 0;
function emit(value) {
  try { process.stderr.write('EMBER_SQL_TIMING ' + JSON.stringify({pid: process.pid,
    at_ms: Math.round(performance.now() - started), ...value}) + '\n'); } catch {}
}
function sites() {
  return (new Error().stack || '').split('\n').slice(1)
    .map(s => s.match(/([^/\\\s()]+\.[cm]?js:\d+:\d+)\)?$/)?.[1])
    .filter(s => s && !s.startsWith('sqlite-timing.cjs:')).slice(0, 10);
}
function state(db) {
  if (!databases.has(db)) databases.set(db, {id: ++nextDb, sqlMs: 0, calls: 0, tx: null});
  return databases.get(db);
}
function kind(sql) {
  const s = String(sql).trim();
  if (/^PRAGMA\s+(?:main\.)?integrity_check\b/i.test(s)) return 'integrity_check';
  if (/^PRAGMA\s+(?:main\.)?foreign_key_check\b/i.test(s)) return 'foreign_key_check';
  const word = s.match(/^[A-Za-z]+/)?.[0].toUpperCase();
  return ['SELECT','WITH','INSERT','UPDATE','DELETE','PRAGMA','BEGIN','COMMIT',
    'ROLLBACK','SAVEPOINT','RELEASE','CREATE','DROP','ALTER'].includes(word) ? word : 'other';
}
function record(db, meta, op, ms, failed) {
  const st = state(db);
  st.sqlMs += ms; st.calls++;
  const key = JSON.stringify([st.id, meta.kind, meta.callsites, op]);
  const g = groups.get(key) || {db: st.id, kind: meta.kind, callsites: meta.callsites,
    op, calls: 0, failed: 0, total_ms: 0, max_ms: 0};
  g.calls++; g.failed += Number(failed); g.total_ms += ms; g.max_ms = Math.max(g.max_ms, ms);
  groups.set(key, g);
  if (ms >= 250) emit({event: 'slow_sql', db: st.id, ...meta, op,
    elapsed_ms: Math.round(ms), failed});
}
function measured(db, meta, op, run) {
  const start = performance.now(); let failed = true;
  try { const value = run(); failed = false; return value; }
  finally { record(db, meta, op, performance.now() - start, failed); }
}
const prepare = DatabaseSync.prototype.prepare;
DatabaseSync.prototype.prepare = function(sql, ...args) {
  const db = this, meta = {kind: kind(sql), callsites: sites()};
  const stmt = measured(db, meta, 'prepare', () => prepare.call(db, sql, ...args));
  for (const name of ['all', 'get', 'run']) {
    const original = stmt[name];
    stmt[name] = function(...values) {
      return measured(db, meta, name, () => original.apply(this, values));
    };
  }
  const iterate = stmt.iterate;
  stmt.iterate = function(...values) {
    const iterator = measured(db, meta, 'iterate', () => iterate.apply(this, values));
    for (const name of ['next', 'return', 'throw']) {
      if (typeof iterator[name] !== 'function') continue;
      const original = iterator[name];
      iterator[name] = function(...args) {
        return measured(db, meta, 'iterate.' + name, () => original.apply(this, args));
      };
    }
    return iterator;
  };
  return stmt;
};
const exec = DatabaseSync.prototype.exec;
DatabaseSync.prototype.exec = function(sql, ...args) {
  const st = state(this), meta = {kind: kind(sql), callsites: sites()};
  const begin = /^\s*BEGIN(?:\s+(?:IMMEDIATE|DEFERRED|EXCLUSIVE))?(?:\s+TRANSACTION)?\s*;?\s*$/i.test(sql);
  const end = /^\s*(?:COMMIT|END|ROLLBACK)(?:\s+TRANSACTION)?\s*;?\s*$/i.test(sql);
  const before = performance.now(), tx = st.tx;
  // Snapshot before COMMIT/ROLLBACK; SQL time excludes those boundary calls.
  const body = end && tx ? {event: 'transaction_body', db: st.id,
    elapsed_ms: Math.round(before - tx.start), sql_ms: Math.round(st.sqlMs - tx.sqlMs),
    sql_calls: st.calls - tx.calls, callsites: tx.callsites} : null;
  const result = measured(this, meta, 'exec', () => exec.call(this, sql, ...args));
  if (begin) st.tx = {start: performance.now(), sqlMs: st.sqlMs, calls: st.calls, callsites: meta.callsites};
  if (end) { st.tx = null; if (body) emit(body); }
  return result;
};
emit({event: 'loaded'});
process.once('exit', () => {
  const top = [...groups.values()].sort((a,b) => b.total_ms-a.total_ms).slice(0,30)
    .map(g => ({...g, total_ms: Math.round(g.total_ms), max_ms: Math.round(g.max_ms)}));
  emit({event: 'summary', top});
});
