// Observe exact V5 source in memory. No maintenance suppression or disk edits.
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {realpathSync} from 'node:fs';
export const EXPECTED='e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df';
let target;
export function initialize(data) {target=realpathSync(path.resolve(data.packageDir,'dist/extensions/memory-core/manager-runtime.js'));}
export function checkedTransform(source) {
  if (createHash('sha256').update(source).digest('hex')!==EXPECTED) throw new Error('Ember gateway trace: V5 hash mismatch');
  return instrument(source);
}
export function instrument(source) {
  const once=(old,replacement)=>{
    if(source.split(old).length!==2) throw new Error('Ember gateway trace: source anchor mismatch');
    source=source.replace(old,replacement);
  };
  once('async function acquireMemoryIndexReadGeneration(databasePath, signal) {\n\treturn await acquire(databasePath, "read", signal);\n}',
    'async function acquireMemoryIndexReadGeneration(databasePath, signal) {\n\treturn await __emberGW.timed("generation_read_wait", () => acquire(databasePath, "read", signal));\n}');
  once('async function withMemoryIndexPublishGeneration(databasePath, run) {\n\treturn await withLease(databasePath, "write", run);\n}',
    'async function withMemoryIndexPublishGeneration(databasePath, run) {\n\tconst release = await __emberGW.timed("generation_write_wait", () => acquire(databasePath, "write"));\n\ttry { return await __emberGW.timed("generation_write_hold", run); } finally { release(); }\n}');
  once('import { d as withMemoryWorkspaceLock } from "../../dreaming-dreams-file-k2G5pqAC.js";',
    'import { d as __emberOriginalWorkspaceLock } from "../../dreaming-dreams-file-k2G5pqAC.js";');
  // Wrap existing async declaration bodies without changing arguments or returns.
  once('async function runEmbeddingOperationWithTimeout(params) {',
    'async function runEmbeddingOperationWithTimeout(params) { return await __emberGW.timed("embedding_request", () => __emberOriginalEmbeddingOperation(params), [params]); }\nasync function __emberOriginalEmbeddingOperation(params) {');
  const wrappers=`
function withMemoryWorkspaceLock(workspaceDir, task) {
 return __emberGW.timed('workspace_operation', () => __emberOriginalWorkspaceLock(workspaceDir,
   () => __emberGW.timed('workspace_hold', task)));
}
for (const [method,phase] of [
 ['searchCandidates','search'],['ensureProviderInitialized','provider_init'],
 ['syncAdmitted','sync_admitted'],['syncPublishedIndexInBackground','background_maintenance'],
 ['runSyncPass','sync_pass'],['runSessionStartupCatchup','startup_catchup'],
 ['processSessionUpdateBatch','session_update'],['syncMemoryFiles','memory_files'],
 ['syncArchiveFiles','session_files'],['embedBatchWithRetry','batch_embedding'],
 ['embedBatchInputsWithRetry','batch_embedding'],['embedQueryWithRetry','query_embedding'],
 ['probeEmbeddingAvailability','provider_probe'],['confirmEmbeddingBootstrapRecovery','bootstrap_probe'],
 ['waitForEmbeddingRetry','retry_sleep'],['searchKeywordWithFallback','fts'],['searchVector','vector']
]) __emberGW.wrap(MemoryIndexManager.prototype,method,phase);
__emberGW.wrap(MemoryIndexManager,'get','manager_get');
__emberGW.emit({event:'module_loaded',mode:'observe-v5'});
`;
  once('export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };',wrappers+'\nexport { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };');
  return "const __emberGW = globalThis.__emberGatewayTrace;\nif (!__emberGW) throw new Error('Ember gateway trace: runtime missing');\n" + source;
}
export async function load(url,context,nextLoad) {
  const result=await nextLoad(url,context);
  if (!url.startsWith('file:') || path.resolve(fileURLToPath(url))!==target) return result;
  if(result.source==null) throw new Error('Ember gateway trace: no source');
  return {...result,source:checkedTransform(typeof result.source==='string'?result.source:Buffer.from(result.source).toString('utf8'))};
}
