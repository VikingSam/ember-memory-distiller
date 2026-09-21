import json
from pathlib import Path
import subprocess
import tempfile
import unittest

class DiagnosticTests(unittest.TestCase):
    def test_caught_error_emits_only_sanitized_callsites(self):
        source = Path('scripts/sqlite-diagnostic.cjs').read_text()
        with tempfile.TemporaryDirectory(prefix='private path with spaces ') as directory:
            hook = Path(directory) / 'sqlite-diagnostic.cjs'
            hook.write_text(source)
            result = subprocess.run(['node', '--require', str(hook), '-e', '''
const {DatabaseSync}=require('node:sqlite');
const db=new DatabaseSync(':memory:');
try { db.prepare('SELECT 1 WHERE 1 IN ('+Array(40000).fill('?').join(',')+')'); }
catch(e) { if(!/too many SQL variables/.test(e.message))throw e; console.log('caught'); }
finally {db.close();}
'''], text=True, capture_output=True, check=True)
            report = next(json.loads(line) for line in result.stderr.splitlines() if line.startswith('{'))
            self.assertEqual(report['event'], 'SQLITE_BIND_OVERFLOW')
            self.assertEqual(report['question_mark_count'],40000)
            self.assertTrue(report['callsites'])
            for frame in report['callsites']:
                self.assertRegex(frame, r'^sqlite-diagnostic\.cjs:\d+:\d+$')
            self.assertNotIn(directory,result.stderr)
            self.assertEqual(result.stdout.strip(),'caught')
