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
const native=safeProfile({samples:[3,3,2],nodes:[
 {id:1,children:[2],callFrame:{url:'file:///pkg/dist/outer.js',lineNumber:1}},
 {id:2,children:[3],callFrame:{url:'file:///pkg/dist/inner.js',lineNumber:10}},
 {id:3,callFrame:{url:'node:internal/crypto',functionName:'PRIVATE_INTERNAL'}}
]},'/pkg');
assert.equal(native.reduce((n,r)=>n+r.samples,0),3);
assert(native.some(r=>r.file==='inner.js'&&r.attribution==='openclaw_caller'&&r.samples===2));
assert(!native.some(r=>r.file==='outer.js'));

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

    def test_real_cpu_stall_identifies_native_caller_without_private_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp);dist=package/'dist';dist.mkdir()
            (dist/'fixture-hotspot.cjs').write_text("""
const {performance}=require('node:perf_hooks');
const {pbkdf2Sync}=require('node:crypto');
exports.spin=function(){const end=performance.now()+250;while(performance.now()<end){};};
exports.native=function(){return pbkdf2Sync('PRIVATE_SYNTHETIC','PRIVATE_SYNTHETIC',1000000,32,'sha256').length;};
""")
            self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';const require=createRequire(import.meta.url);
const {createRuntime}=require(RUNTIME);const hotspot=require(HOTSPOT);const rows=[];
const t=createRuntime({packageDir:PACKAGE,durationMs:5000,sink:r=>rows.push(r)});
await t.startCapture();
await t.timed('session_update',()=>t.timed('session_files',async()=>{hotspot.spin();hotspot.native();}));
await t.finish();
const profile=rows.find(r=>r.event==='cpu_samples');assert(profile,'CPU profile unavailable');
assert(profile.frames.some(r=>r.file==='fixture-hotspot.cjs'&&r.attribution==='openclaw_caller'&&r.samples>0));
assert(rows.some(r=>r.event==='end'&&r.phase==='session_files'&&r.elapsed_ms>=250));
assert(!JSON.stringify(rows).includes('PRIVATE'));
assert(!JSON.stringify(profile).includes(PACKAGE));
'''.replace('RUNTIME',json.dumps(str(ROOT/'scripts/gateway-trace-runtime.cjs'))).replace('HOTSPOT',json.dumps(str(dist/'fixture-hotspot.cjs'))).replace('PACKAGE',json.dumps(str(package))))

    def test_search_trigger_waits_then_records_once_and_expires(self):
        self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';const require=createRequire(import.meta.url);
const {createRuntime}=require(RUNTIME);const rows=[];let time=0;
const t=createRuntime({searchTriggered:true,armMs:1000,durationMs:100,now:()=>time,profile:false,sink:r=>rows.push(r)});
t.arm();time=500;
await t.timed('search',async()=>1);
assert.deepEqual(rows.map(r=>r.event),['armed']);
assert.equal(await t.captureSearch(()=>t.timed('manager_context',async()=>42)),42);
assert.equal(rows.filter(r=>r.event==='capture_start').length,1);
assert(rows.some(r=>r.phase==='manager_context'&&r.parent!==null));
time=601;const n=rows.length;
assert.equal(await t.captureSearch(async()=>43),43);assert.equal(rows.length,n);
await t.finish();assert.equal(rows.filter(r=>r.event==='capture_start').length,1);
const expired=[];const e=createRuntime({searchTriggered:true,armMs:1,profile:false,sink:r=>expired.push(r)});e.arm();
await new Promise(r=>setTimeout(r,20));
assert.equal(await e.captureSearch(async()=>44),44);
assert.deepEqual(expired.map(r=>r.event),['armed','arm_expired']);
'''.replace('RUNTIME',json.dumps(str(ROOT/'scripts/gateway-trace-runtime.cjs'))))

    def test_tool_transform_preserves_receiver_args_results_and_errors(self):
        fixture = '''
import { t as filterMemorySearchHitsBySessionVisibility } from "./session-search-visibility-goTjejWD.js";
function createMemorySearchTool(options) { return options; }
async function runMemorySearchWithDeadline(params) { return params.run(); }
async function executeMemorySearchToolQuery(params) { return filterMemorySearchHitsBySessionVisibility(params); }
async function getMemoryManagerContextWithPurpose(params) { return params; }
export {createMemorySearchTool,runMemorySearchWithDeadline,executeMemorySearchToolQuery,getMemoryManagerContextWithPurpose};
'''
        self.node('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';const require=createRequire(import.meta.url);
const {createRuntime}=require(RUNTIME);const {instrumentTools,checkedToolsTransform}=await import(LOADER);
assert.throws(()=>checkedToolsTransform(FIXTURE),/hash mismatch/);
let source=instrumentTools(FIXTURE).replace(/import { t as __emberOriginalVisibility }[^;]+;/,'async function __emberOriginalVisibility(x){return x;}');
const rows=[];globalThis.__emberGatewayTrace=createRuntime({searchTriggered:true,profile:false,sink:r=>rows.push(r)});
globalThis.__emberGatewayTrace.arm();
const m=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(m.createMemorySearchTool(undefined),undefined);
const params={secret:'PRIVATE'},signal=new AbortController().signal,result={private:'PRIVATE_RESULT'};
const tool=m.createMemorySearchTool({execute:async function(id,p,s){assert.equal(this,tool);assert.equal(id,'PRIVATE_ID');assert.equal(p,params);assert.equal(s,signal);return result;}});
assert.equal(await tool.execute('PRIVATE_ID',params,signal),result);
const failure=new Error('PRIVATE');
await assert.rejects(m.runMemorySearchWithDeadline({run:async()=>{throw failure;}}),e=>e===failure);
assert.equal(await m.executeMemorySearchToolQuery(params),params);
assert.equal(await m.getMemoryManagerContextWithPurpose(params),params);
assert(rows.some(r=>r.phase==='tool_call'));
assert(rows.some(r=>r.phase==='visibility_filter'));
assert(!JSON.stringify(rows).includes('PRIVATE'));
await globalThis.__emberGatewayTrace.finish();
'''.replace('RUNTIME',json.dumps(str(ROOT/'scripts/gateway-trace-runtime.cjs'))).replace('LOADER',json.dumps((ROOT/'scripts/gateway-trace-loader.mjs').as_uri())).replace('FIXTURE',json.dumps(fixture)))

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
