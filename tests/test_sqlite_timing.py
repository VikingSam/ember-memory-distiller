import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class SqliteTimingTests(unittest.TestCase):
    def test_results_errors_iterators_timings_and_privacy(self):
        hook = Path(__file__).resolve().parents[1] / 'scripts/sqlite-timing.cjs'
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / 'timing-fixture.cjs'
            fixture.write_text('''
const assert = require('node:assert/strict');
const {DatabaseSync} = require('node:sqlite');
const db = new DatabaseSync(':memory:');
db.function('slow', () => { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,270); return 7; });
db.exec('CREATE TABLE private_table(x)');
db.exec('BEGIN IMMEDIATE');
db.prepare('INSERT INTO private_table VALUES(?)').run('PRIVATE_SENTINEL');
db.exec('SAVEPOINT nested');
assert.equal(db.prepare('SELECT slow() n').get().n,7);
db.exec('RELEASE nested');
db.exec('COMMIT');
assert.equal(db.prepare('SELECT * FROM private_table').all()[0].x,'PRIVATE_SENTINEL');
assert.equal([...db.prepare('SELECT * FROM private_table').iterate()].length,1);
for (const row of db.prepare('SELECT * FROM private_table').iterate()) break;
assert.throws(() => db.prepare('INVALID PRIVATE_SENTINEL'));
db.exec('BEGIN'); db.exec('ROLLBACK');
db.close();
''')
            result = subprocess.run(['node', '--require', str(hook), str(fixture)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line.removeprefix('EMBER_SQL_TIMING ')) for line in result.stderr.splitlines() if line.startswith('EMBER_SQL_TIMING ')]
            encoded = json.dumps(records)
            for secret in ('PRIVATE_SENTINEL', 'private_table', tmp, str(hook.parent)):
                self.assertNotIn(secret, encoded)
            bodies = [r for r in records if r['event'] == 'transaction_body']
            self.assertEqual(len(bodies), 2)
            self.assertGreaterEqual(bodies[0]['sql_ms'], 250)
            self.assertTrue(any(r['event'] == 'slow_sql' and r['op'] == 'get' for r in records))
            self.assertIn('timing-fixture.cjs:', encoded)
            self.assertEqual(records[-1]['event'], 'summary')
