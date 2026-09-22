// In-memory transformation of the exact V4 module. No source files are written.
import { createHash } from 'node:crypto';
const EXPECTED = '9580e3f7d3d18db3fa881e438cac96d93347a59e6e796b6a35b2733fb5f7a483';
let publishedOnly = false;
export function initialize(data) { publishedOnly = data.publishedOnly === true; }
export function checkedTransform(source, mode) {
  if (createHash('sha256').update(source).digest('hex') !== EXPECTED) {
    throw new Error('Ember phase probe: manager-runtime hash is not the tested V4 hash');
  }
  return instrument(source, mode);
}
export function instrument(source, mode) {
  const once = (old, replacement) => {
    if (source.split(old).length !== 2) throw new Error('Ember phase probe: source anchor mismatch');
    source = source.replace(old, replacement);
  };
  once('enabled: (this.settings.sync.onSearch || sessionStartSync) && (this.purpose === "default" || this.purpose === "cli"),',
    'enabled: !(__emberPublishedOnly && this.purpose === "cli") && (this.settings.sync.onSearch || sessionStartSync) && (this.purpose === "default" || this.purpose === "cli"),');
  once('async function acquireMemoryIndexReadGeneration(databasePath, signal) {\n\treturn await acquire(databasePath, "read", signal);\n}',
    'async function acquireMemoryIndexReadGeneration(databasePath, signal) {\n\treturn await __emberTimed("generation_read_wait", () => acquire(databasePath, "read", signal));\n}');
  const helpers = `
const __emberPublishedOnly = ${mode === true};
const __emberEpoch = globalThis.__emberSearchProbeBootAt ?? performance.now();
let __emberSequence = 0;
function __emberEmit(record) {
  try { process.stderr.write('EMBER_SEARCH_PHASE ' + JSON.stringify({pid:process.pid,
    at_ms:Math.round(performance.now()-__emberEpoch),...record}) + '\\n'); } catch {}
}
async function __emberTimed(phase, run) {
  const id=++__emberSequence, start=performance.now(); let ok=false;
  __emberEmit({event:'start',phase,id});
  try { const result=await run(); ok=true; return result; }
  finally { __emberEmit({event:'end',phase,id,ok,elapsed_ms:Math.round(performance.now()-start)}); }
}
__emberEmit({event:'module_loaded',mode:__emberPublishedOnly?'published-only':'observe'});
`;
  const wrappers = `
for (const [method, phase] of [
  ['searchCandidates','search'], ['ensureProviderInitialized','provider_init'],
  ['syncAdmitted','sync_preflight_or_maintenance'],
  ['syncPublishedIndexInBackground','background_maintenance'],
  ['runSyncPass','sync_pass'], ['embedBatchWithRetry','document_embedding'],
  ['embedQueryWithRetry','query_embedding'],
  ['searchKeywordWithFallback','fts'], ['searchVector','vector'], ['close','close']
]) {
  const original=MemoryIndexManager.prototype[method];
  if (typeof original!=='function') throw new Error('Ember phase probe: missing method');
  MemoryIndexManager.prototype[method]=function(...args) {
    return __emberTimed(phase, () => original.apply(this,args));
  };
}
const __emberGet=MemoryIndexManager.get;
MemoryIndexManager.get=function(...args) {
  return __emberTimed('manager_get', () => __emberGet.apply(this,args));
};
`;
  once('export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };',
    wrappers + '\nexport { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };');
  return helpers + '\n' + source;
}
export async function load(url, context, nextLoad) {
  const result = await nextLoad(url, context);
  if (!new URL(url).pathname.endsWith('/dist/extensions/memory-core/manager-runtime.js')) return result;
  if (result.source == null) throw new Error('Ember phase probe: module source unavailable');
  const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString('utf8');
  return {...result, source: checkedTransform(source, publishedOnly)};
}
