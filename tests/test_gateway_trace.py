import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GatewayTraceTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(['node', '--input-type=module', '-e', source], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_runtime_context_error_privacy_expiry_and_cap(self):
        self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {createRuntime,errorClass,safeProfile}=require(RUNTIME);
let time=0; const rows=[];
const t=createRuntime({now:()=>time,durationMs:100,sink:r=>rows.push(r),profile:false});
const secret=Object.assign(new Error('PRIVATE_TOKEN PRIVATE_HISTORY'),{status:429});
let caught;
await t.timed('sync_pass',async()=>{
  await Promise.all([
    t.timed('batch_embedding',async()=>{time+=5;return 'PRIVATE_RESULT';},[['PRIVATE_TEXT']]),
    t.timed('provider_probe',async()=>{try {await t.timed('embedding_request',async()=>{throw secret;},[{timeoutMs:500}]);}catch(e){caught=e;}})
  ]);
},[{reason:'PRIVATE_REASON'}]);
assert.equal(caught,secret);
const begin=rows.filter(r=>r.event==='start');
assert.equal(begin.find(r=>r.phase==='batch_embedding').parent,begin[0].id);
assert.equal(begin.find(r=>r.phase==='embedding_request').parent,begin.find(r=>r.phase==='provider_probe').id);
assert(rows.some(r=>r.error_class==='http_429'));
assert.equal(errorClass({message:'PRIVATE database is locked'}),'sqlite_locked');
const before=rows.length;time=101;
assert.equal(await t.timed('search',async()=>42),42);assert.equal(rows.length,before);
await t.finish();
assert(!JSON.stringify(rows).includes('PRIVATE'));
const capRows=[];const c=createRuntime({sink:r=>capRows.push(r),maxRecords:2,profile:false});
for(let i=0;i<10;i++)await c.timed('search',async()=>1);
assert.equal(capRows.filter(r=>r.event==='record_cap').length,1);
await c.finish();assert(capRows.some(r=>r.event==='capture_end'));
const frames=safeProfile({samples:[1,2,2,3],nodes:[
 {id:1,callFrame:{url:'file:///pkg/dist/manager-runtime.js',lineNumber:5,functionName:'PRIVATE_FUNCTION'}},
 {id:2,callFrame:{url:'file:///home/PRIVATE/script.js',lineNumber:2,functionName:'PRIVATE'}},
 {id:3,callFrame:{url:'file:///pkg/dist-PRIVATE/script.js',lineNumber:2}}
]},'/pkg');
assert(!JSON.stringify(frames).includes('PRIVATE'));
assert(frames.some(x=>x.file==='manager-runtime.js'&&x.line===6));
'''.replace('RUNTIME', json.dumps(str(ROOT / 'scripts/gateway-trace-runtime.cjs'))))

    def test_bounded_actual_profiler_lifecycle(self):
        self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';const require=createRequire(import.meta.url);
const {createRuntime}=require(RUNTIME);const rows=[];
const t=createRuntime({durationMs:100,packageDir:'/nonexistent',sink:r=>rows.push(r)});
await t.startCapture();
await new Promise(resolve=>setTimeout(resolve,250));
assert(rows.some(r=>r.event==='capture_end'));
assert(rows.some(r=>r.event==='cpu_samples'||r.event==='profiler_unavailable'));
const n=rows.length;await t.timed('search',async()=>true);assert.equal(rows.length,n);
'''.replace('RUNTIME', json.dumps(str(ROOT / 'scripts/gateway-trace-runtime.cjs'))))

    def test_preload_scope_and_non_gateway_noop(self):
        hook=ROOT / 'scripts/gateway-trace-preload.cjs'
        r=subprocess.run(['node','--require',str(hook),'-e',''],capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            entry=Path(tmp)/'entry.cjs';entry.write_text('')
            r=subprocess.run(['node','--require',str(hook),str(entry),'gateway'],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('explicit Ember service scope required',r.stderr)

    def test_transform_preserves_behavior_and_releases_failed_lease(self):
        fixture='''
import { d as withMemoryWorkspaceLock } from "../../dreaming-dreams-file-k2G5pqAC.js";
let released=0;
async function acquire(){return ()=>released++;}
async function withLease(p,k,run){const release=await acquire();try{return await run();}finally{release();}}
async function acquireMemoryIndexReadGeneration(databasePath, signal) {
\treturn await acquire(databasePath, "read", signal);
}
async function withMemoryIndexPublishGeneration(databasePath, run) {
\treturn await withLease(databasePath, "write", run);
}
async function runEmbeddingOperationWithTimeout(params) {return await params.run();}
class MemoryIndexManager {static async get(){return new this();}}
function closeAllMemoryIndexManagers(){}
function closeMemoryIndexManagersForAgent(){}
export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };
'''
        self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';const require=createRequire(import.meta.url);
const {createRuntime}=require(RUNTIME);
const {instrument,checkedTransform}=await import(LOADER);
assert.throws(()=>checkedTransform(FIXTURE),/hash mismatch/);
let source=instrument(FIXTURE);
// Replace dependency only in this synthetic fixture; production import is unchanged.
source=source.replace(/import \\{ d as __emberOriginalWorkspaceLock \\}[^;]+;/,
 'async function __emberOriginalWorkspaceLock(p,task){return task();}');
const methods=[...source.matchAll(/\\['([^']+)','[^']+'\\]/g)].map(m=>m[1]);
source=source.replace('function withMemoryWorkspaceLock(workspaceDir, task) {',
 methods.map(m=>`MemoryIndexManager.prototype.${m}=async function(...args){return args[0];};`).join('\\n')+'\\nfunction withMemoryWorkspaceLock(workspaceDir, task) {');
source+='\\nexport {withMemoryIndexPublishGeneration,acquireMemoryIndexReadGeneration,runEmbeddingOperationWithTimeout,withMemoryWorkspaceLock,released};';
const rows=[];globalThis.__emberGatewayTrace=createRuntime({sink:r=>rows.push(r),profile:false});
const m=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const error=new Error('PRIVATE');
await assert.rejects(m.withMemoryIndexPublishGeneration('PRIVATE_PATH',async()=>{throw error;}),e=>e===error);
assert.equal(m.released,1);
assert.equal(await m.withMemoryWorkspaceLock('PRIVATE_PATH',async()=>9),9);
assert.equal(await m.runEmbeddingOperationWithTimeout({run:async()=>7,timeoutMs:5}),7);
assert.equal(await (await m.MemoryIndexManager.get()).searchCandidates('PRIVATE_QUERY'),'PRIVATE_QUERY');
assert(!JSON.stringify(rows).includes('PRIVATE'));
await globalThis.__emberGatewayTrace.finish();
'''.replace('RUNTIME',json.dumps(str(ROOT/'scripts/gateway-trace-runtime.cjs'))).replace('LOADER',json.dumps((ROOT/'scripts/gateway-trace-loader.mjs').as_uri())).replace('FIXTURE',json.dumps(fixture)))


if __name__ == '__main__':
    unittest.main()
