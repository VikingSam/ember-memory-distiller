import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from scripts.patch_openclaw import OLD, NEW, TARGET, patch_plan, revert_latest


class PatchTests(unittest.TestCase):
    def test_archive_lookup_real_sqlite_74434_bindings(self):
        harness = Path('tests/archive_lookup_harness.cjs').read_text()
        result = subprocess.run(['node', '-e', harness], input=json.dumps({'old': OLD, 'new': NEW}), text=True, capture_output=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['originalBindings'], 74434)
        self.assertEqual(report['maxPatchedBindings'], 800)
        self.assertTrue(report['sameRowsAndOrder'])
        self.assertTrue(report['rollbackVerified'])

    def test_patch_reinstall_idempotence_and_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dist').mkdir()
            (root / 'package.json').write_text(json.dumps({'name':'openclaw','version':'2026.8.1'}))
            code = root / TARGET
            code.write_text(OLD)
            patch_plan(root).commit()
            self.assertEqual(code.read_text(), NEW)
            self.assertFalse(patch_plan(root).changes())
            revert_latest(root)
            self.assertEqual(code.read_text(), OLD)
            patch_plan(root).commit()
            code.write_text(OLD)  # simulated npm reinstall
            self.assertTrue(patch_plan(root).changes())
            code.write_text('unknown code')
            with self.assertRaises(ValueError):
                patch_plan(root)
