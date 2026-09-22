// Observe exact V5 source in memory. No maintenance suppression or disk edits.
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {realpathSync} from 'node:fs';
export const EXPECTED='e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df';
export const TOOLS_EXPECTED='5efc8c5eb2079a359adedf3e2f8abfb93780f5bac54b4314bc3cba1e2c9873c5';
let target, toolsTarget;
export function initialize(data) {target=realpathSync(path.resolve(data.packageDir,'dist/extensions/memory-core/manager-runtime.js'));toolsTarget=realpathSync(path.resolve(data.packageDir,'dist/tools-DNmkgIrY.js'));}
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
export function instrumentTools(source) {
  const once=(old,replacement)=>{
    if(source.split(old).length!==2) throw new Error('Ember gateway trace: tool source anchor mismatch');
    source=source.replace(old,replacement);
  };
  once('function createMemorySearchTool(options) {', `function createMemorySearchTool(options) {
    const tool=__emberOriginalCreateMemorySearchTool(options);
    if(tool && typeof tool.execute==='function') {
      const execute=tool.execute;
      tool.execute=function(...args){return __emberGW.captureSearch(()=>execute.apply(this,args));};
    }
    return tool;
  }
  function __emberOriginalCreateMemorySearchTool(options) {`);
  for(const [name,phase] of [
    ['runMemorySearchWithDeadline','tool_deadline'],
    ['executeMemorySearchToolQuery','tool_query'],
    ['getMemoryManagerContextWithPurpose','manager_context']
  ]) once('async function '+name+'(params) {',
    'async function '+name+'(params) { return await __emberGW.timed("'+phase+'", () => __emberOriginal_'+name+'(params)); }\nasync function __emberOriginal_'+name+'(params) {');
  once('import { t as filterMemorySearchHitsBySessionVisibility } from "./session-search-visibility-goTjejWD.js";',
    'import { t as __emberOriginalVisibility } from "./session-search-visibility-goTjejWD.js";\nasync function filterMemorySearchHitsBySessionVisibility(...args) { return await __emberGW.timed("visibility_filter", () => __emberOriginalVisibility(...args)); }');
  return 'const __emberGW=globalThis.__emberGatewayTrace;\n__emberGW.emit({event:"tool_hook_ready"},true);\n'+source;
}
export function checkedToolsTransform(source) {
  if(createHash('sha256').update(source).digest('hex')!==TOOLS_EXPECTED) throw new Error('Ember gateway trace: tools hash mismatch');
  return instrumentTools(source);
}
export async function load(url,context,nextLoad) {
  const result=await nextLoad(url,context);
  if (!url.startsWith('file:')) return result;
  const filename=path.resolve(fileURLToPath(url));
  if(filename!==target && filename!==toolsTarget) return result;
  if(result.source==null) throw new Error('Ember gateway trace: no source');
  const source=typeof result.source==='string'?result.source:Buffer.from(result.source).toString('utf8');
  return {...result,source:filename===target?checkedTransform(source):checkedToolsTransform(source)};
}
