import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SearchPhaseProbeTests(unittest.TestCase):
    def test_modes_preflight_errors_and_sanitization(self):
        loader = (Path(__file__).resolve().parents[1] / 'scripts/search-phase-loader.mjs').as_uri()
        fixture = '''
async function acquire() { return () => {}; }
async function acquireMemoryIndexReadGeneration(databasePath, signal) {
\treturn await acquire(databasePath, "read", signal);
}
function startAsyncSearchSync(p) { if (p.enabled) return p.sync(); }
class MemoryIndexManager {
 constructor(purpose='cli') {this.purpose=purpose;this.settings={sync:{onSearch:true}};this.maintenance=0;this.preflight=0;}
 static async get() {return new this();}
 async searchCandidates(query) {
   await this.syncAdmitted(); // Safety/identity preflight must remain present.
   const sessionStartSync=true;
   startAsyncSearchSync({
     enabled: (this.settings.sync.onSearch || sessionStartSync) && (this.purpose === "default" || this.purpose === "cli"),
     sync:()=>this.syncPublishedIndexInBackground()
   });
   const release=await acquireMemoryIndexReadGeneration('PRIVATE_PATH');
   release(); return [query];
 }
 async ensureProviderInitialized() {}
 async syncAdmitted() {this.preflight++;}
 async syncPublishedIndexInBackground() {this.maintenance++;}
 async runSyncPass() {}
 async embedBatchWithRetry() {}
 async embedQueryWithRetry() {throw Error('PRIVATE_ERROR');}
 async searchKeywordWithFallback() {return ['PRIVATE_RESULT'];}
 async searchVector() {return [];}
 async close() {}
}
function closeAllMemoryIndexManagers() {}
function closeMemoryIndexManagersForAgent() {}
export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };
'''
        script = f'''
import assert from 'node:assert/strict';
import {{instrument,checkedTransform}} from {json.dumps(loader)};
const source={json.dumps(fixture)};
assert.throws(()=>checkedTransform(source,true),/hash/);
for (const mode of [true,false]) {{
 const transformed=instrument(source,mode);
 const {{MemoryIndexManager:M}}=await import('data:text/javascript;base64,'+Buffer.from(transformed).toString('base64'));
 const m=await M.get();
 assert.deepEqual(await m.searchCandidates('PRIVATE_QUERY'),['PRIVATE_QUERY']);
 assert.equal(m.maintenance,mode?0:1); assert.equal(m.preflight,1);
 assert.deepEqual(await m.searchKeywordWithFallback(),['PRIVATE_RESULT']);
 await assert.rejects(m.embedQueryWithRetry(),/PRIVATE_ERROR/);
 const gateway=new M('default');await gateway.searchCandidates('PRIVATE_QUERY');
 assert.equal(gateway.maintenance,1);
 await m.close();
}}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'test.mjs';p.write_text(script)
            result = subprocess.run(['node', str(p)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(s.removeprefix('EMBER_SEARCH_PHASE ')) for s in result.stderr.splitlines() if s.startswith('EMBER_SEARCH_PHASE ')]
        encoded = json.dumps(records)
        self.assertNotIn('PRIVATE', encoded)
        self.assertTrue(any(x.get('phase') == 'generation_read_wait' for x in records))
        self.assertTrue(any(x.get('phase') == 'query_embedding' and x.get('ok') is False for x in records))

    def test_preload_rejects_gateway_and_invalid_mode(self):
        hook = Path(__file__).resolve().parents[1] / 'scripts/search-phase-probe.cjs'
        result = subprocess.run(['node', '--require', str(hook), '-e', ''], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('only the memory search CLI', result.stderr)

    def test_real_loader_registration_rejects_changed_target(self):
        hook = Path(__file__).resolve().parents[1] / 'scripts/search-phase-probe.cjs'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text('{"type":"module"}')
            target = root / 'dist/extensions/memory-core/manager-runtime.js'
            target.parent.mkdir(parents=True)
            target.write_text('export const untouched = true;')
            entry = root / 'entry.mjs'
            entry.write_text("await import('./dist/extensions/memory-core/manager-runtime.js');")
            env = dict(os.environ, EMBER_SEARCH_PROBE_MODE='published-only')
            result = subprocess.run(['node', '--require', str(hook), str(entry), 'memory', 'search'], env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not the tested V4 hash', result.stderr)
            self.assertEqual(target.read_text(), 'export const untouched = true;')
