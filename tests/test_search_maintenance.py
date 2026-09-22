import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import patch_search_maintenance as p


class SearchMaintenanceTests(unittest.TestCase):
    def test_runtime_routing_and_recovery(self):
        source = Path(__file__).with_name('search_maintenance_fixture.js').read_text()
        for old, new in p.REPLACEMENTS:
            self.assertEqual(source.count(old), 1)
            source = source.replace(old, new)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'runtime.js'
            target.write_text(source)
            result = subprocess.run(['node', str(Path(__file__).with_name('search_maintenance_harness.cjs')), str(target)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_patch_revert_idempotence_unknown_edits(self):
        original = Path(__file__).with_name('search_maintenance_fixture.js').read_text()
        new = original
        for old, replacement in p.REPLACEMENTS:
            new = new.replace(old, replacement)
        sha = lambda x: hashlib.sha256(x.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, 'ORIGINAL_SHA256', sha(original)), patch.object(p, 'PATCHED_SHA256', sha(new)):
            root = Path(tmp)
            (root / 'package.json').write_text(json.dumps({'name':'openclaw','version':'2026.8.1'}))
            target = root / p.TARGET
            target.parent.mkdir(parents=True)
            target.write_text(original)
            plan = p.patch_plan(root)
            self.assertFalse((root / '.ember-distiller').exists())
            self.assertEqual(target.read_text(), original)
            self.assertEqual(list(plan.changes()), [p.TARGET])
            backup = plan.commit()
            self.assertEqual(target.read_text(), new)
            self.assertEqual(p.patch_plan(root).changes(), {})
            self.assertEqual(p.revert_latest(root), backup)
            self.assertEqual(target.read_text(), original)
            target.write_text(original + '\n// local alteration\n')
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                p.patch_plan(root)
