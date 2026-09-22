import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import patch_search_published as p


class PublishedSearchTests(unittest.TestCase):
    def test_actual_search_method(self):
        text = Path(__file__).with_name('search_published_fixture.js').read_text()
        for old, new in p.REPLACEMENTS:
            self.assertEqual(text.count(old), 1)
            text = text.replace(old, new)
        with tempfile.TemporaryDirectory() as d:
            fixture = Path(d) / 'fixture.js';fixture.write_text(text)
            result = subprocess.run(['node', str(Path(__file__).with_name('search_published_harness.cjs')), str(fixture)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_revert_only_v5_and_reject_changed_file(self):
        before = Path(__file__).with_name('search_published_fixture.js').read_text()
        after = before
        for old, new in p.REPLACEMENTS: after = after.replace(old, new)
        sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch.object(p,'ORIGINAL_SHA256',sha(before)), patch.object(p,'PATCHED_SHA256',sha(after)):
            root = Path(d);target = root / p.TARGET
            target.parent.mkdir(parents=True);target.write_text(before)
            (root/'package.json').write_text(json.dumps({'name':'openclaw','version':'2026.8.1'}))
            old_backup = root/'.ember-distiller/backups/old'
            old_backup.mkdir(parents=True)
            (old_backup/'manifest.json').write_text(json.dumps({'status':'committed','files':{p.TARGET:{'after':'prior-v4-hash'}}}))
            with self.assertRaises(ValueError): p.revert_latest(root)
            plan = p.patch_plan(root)
            self.assertEqual(target.read_text(),before)
            backup = plan.commit();self.assertEqual(target.read_text(),after)
            self.assertEqual(p.patch_plan(root).changes(),{})
            self.assertEqual(p.revert_latest(root),backup)
            self.assertEqual(target.read_text(),before)
            with self.assertRaises(ValueError): p.revert_latest(root)
            target.write_text(before+'\n// local change')
            with self.assertRaises(ValueError):p.patch_plan(root)
