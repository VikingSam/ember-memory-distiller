// Local-only diagnostic preload. Emits no SQL, values, config, or memory text.
const { DatabaseSync } = require('node:sqlite');
const { createHash } = require('node:crypto');
const original = DatabaseSync.prototype.prepare;
DatabaseSync.prototype.prepare = function (sql, ...args) {
  try { return original.call(this, sql, ...args); }
  catch (error) {
    if (/too many SQL variables/i.test(String(error.message))) {
      const frames = new Error().stack.split('\n').slice(1)
        .map(line => line.match(/([^/\\\s()]+\.[cm]?js:\d+:\d+)\)?$/)?.[1])
        .filter(Boolean);
      console.error(JSON.stringify({ event: 'SQLITE_BIND_OVERFLOW',
        sql_sha256: createHash('sha256').update(String(sql)).digest('hex'),
        question_mark_count: (String(sql).match(/\?/g) || []).length,
        callsites: frames }));
    }
    throw error;
  }
};
