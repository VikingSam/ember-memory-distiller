import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.patch_tombstones import OLD, NEW, TARGET, patch_plan, revert_latest

class TombstoneTests(unittest.TestCase):
    def test_real_sqlite_37707_and_semantics(self):
        result=subprocess.run(['node','-e',Path('tests/tombstone_lookup_harness.cjs').read_text()],input=json.dumps({'old':OLD,'new':NEW}),text=True,capture_output=True,check=True)
        report=json.loads(result.stdout)
        self.assertEqual(report['originalBindings'],37707)
        self.assertEqual(report['maxBindings'],401)
        self.assertTrue(report['semanticsVerified'])

    def test_independent_apply_restore_reinstall_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'dist').mkdir()
            (root/'package.json').write_text(json.dumps({'name':'openclaw','version':'2026.8.1'}))
            target=root/TARGET;target.write_text(OLD)
            v2=root/'dist/session-accessor.sqlite-entry-CoLie3L_.js';v2.write_text('V2 stays applied')
            ident=patch_plan(root).commit()
            self.assertEqual(target.read_text(),NEW)
            self.assertFalse(patch_plan(root).changes())
            revert_latest(root)
            self.assertEqual(target.read_text(),OLD)
            self.assertEqual(v2.read_text(),'V2 stays applied')
            patch_plan(root).commit();target.write_text(OLD)
            self.assertEqual(set(patch_plan(root).changes()),{TARGET})
            target.write_text('different code')
            with self.assertRaises(ValueError):patch_plan(root)
            with self.assertRaises(RuntimeError):revert_latest(root)
