const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
let held = false, workspaceHeld = false, identity = 'valid', events = [], restores = [], fail = false;
const context = {
  resolveMemoryIndexIdentityState: () => ({status: identity}),
  resolveConfiguredSourcesForMeta: () => [], resolveConfiguredScopeHash: () => 'scope',
  runMemoryTargetedSessionSync: async () => ({handled:false}),
  markMemoryTargetArchiveFilesDirty: () => false,
  formatErrorMessage: e => e.message, toErrorObject: e => e,
  withMemoryWorkspaceLock: async (path, run) => {
    assert.equal(held, false, 'workspace lock must precede generation lock');
    assert.equal(workspaceHeld, false);
    workspaceHeld = true;
    try { return await run(); } finally { workspaceHeld = false; }
  },
  withMemoryIndexPublishGeneration: async (path, run) => {
    assert.equal(workspaceHeld, true, 'match existing publisher lock ordering');
    assert.equal(held, false, 'must not acquire generation lease recursively');
    held = true; events.push('lock');
    try { return await run(); } finally { held = false; events.push('unlock'); }
  }
};
vm.createContext(context);
vm.runInContext(source+'\nglobalThis.Manager=FixtureManager; globalThis.maintain=runMemorySearchMaintenance;', context);
function manager() {
  const m = new context.Manager();
  Object.assign(m, {
    provider:{id:'voyage',model:'voyage-3'}, syncProviderGeneration:null,
    settings:{store:{databasePath:'test',fts:{tokenizer:'unicode61'}},multimodal:{},chunking:{},provider:'voyage'},
    sources:new Set(['memory','sessions']), dirty:true, sessionsDirty:true,
    memoryFullRetryDirty:false,sessionsFullRetryDirty:false,sessionsReconcileDirty:false,
    sessionsDirtyFiles:new Set(),
    assertFtsOnlySyncAllowed(){}, ensureVectorReady:async()=>true,
    readMeta:()=>({chunkingVersion:3}), hasRequestedTargetSessionSync:()=>false,
    resolveProviderIndexIdentities:()=>[],hasIndexedChunks:()=>true,hasSemanticChunks:()=>true,
    shouldSyncSessions:()=>true,shouldDeferSourceWideBatch:()=>false,
    clearMemoryRetryState(){this.dirty=false;this.memoryFullRetryDirty=false;},
    clearSessionRetryState(){this.sessionsDirty=false;this.sessionsFullRetryDirty=false;this.sessionsDirtyFiles.clear();},
    refreshSessionDirtyFlag(){},shouldFallbackOnError:()=>false,
    runInPlaceReindex:async()=>{assert.equal(held,false);assert.equal(workspaceHeld,false);events.push('full');},
    syncMemoryFiles:async p=>{assert.equal(held,true);assert.equal(!!p.needsFullReindex,false);events.push('memory-incremental');if(fail)throw Error('expected');},
    syncArchiveFiles:async p=>{assert.equal(held,true);events.push(p.needsFullReindex?'sessions-full':'sessions-incremental');},
    markSessionStartupCatchupDirtyFiles:async()=>{}
  });
  return m;
}
async function run() {
  events=[];let m=manager();
  await m.runSyncPass({reason:'search',emberSearchMaintenanceV4:true});
  assert.deepEqual(events,['lock','memory-incremental','sessions-incremental','unlock']);
  for(const status of ['missing','mismatched']) {
    identity=status;events=[];m=manager();
    await m.runSyncPass({reason:'search',emberSearchMaintenanceV4:true});
    assert.deepEqual(events,['lock','unlock','full']);
  }
  identity='valid';events=[];m=manager();m.memoryFullRetryDirty=true;
  await m.runSyncPass({reason:'search',emberSearchMaintenanceV4:true});
  assert.deepEqual(events,['lock','unlock','full']);
  events=[];m=manager();m.sessionsFullRetryDirty=true;
  await m.runSyncPass({reason:'search',emberSearchMaintenanceV4:true});
  assert.deepEqual(events,['lock','memory-incremental','sessions-full','unlock']);
  events=[];m=manager();
  await m.runSyncPass({reason:'cli',force:true});
  assert.deepEqual(events,['full']);
  events=[];fail=true;m=manager();
  await assert.rejects(m.runSyncPass({reason:'search',emberSearchMaintenanceV4:true}),/expected/);
  assert.equal(held,false);assert.equal(workspaceHeld,false);fail=false;
  // Dirty handoff preserves session sets/retry state and restores on failure.
  const dirty={dirty:true,memoryFullRetryDirty:true,sessionsFullRetryDirty:true,
    sessionsDirty:true,sessionsReconcileDirty:true,sessionsDirtyFiles:new Set(['pending'])};
  m=manager();m.sessionsDirtyFiles.add('existing');
  let called=false,closed=false;
  m.sync=async p=>{
    called=true;assert.equal(p.force,undefined);assert.equal(p.emberSearchMaintenanceV4,true);
    assert.equal(m.memoryFullRetryDirty,true);assert.equal(m.sessionsFullRetryDirty,true);
    assert.equal(m.sessionsReconcileDirty,true);
    assert.deepEqual([...m.sessionsDirtyFiles].sort(),['existing','pending']);
  };
  m.status=()=>({dirty:false});m.close=async()=>{closed=true;};
  const params={reason:'search',takeDirtyGeneration:()=>dirty,
    restoreDirtyGeneration:x=>restores.push(x),acquireManager:async()=>m};
  await context.maintain(params);assert(called&&closed);assert.equal(restores.length,0);
  m.sync=async()=>{throw Error('sync-failed');};closed=false;
  await assert.rejects(context.maintain(params),/sync-failed/);assert(closed);assert.equal(restores.pop(),dirty);
  m.sync=async()=>{};m.status=()=>({dirty:true,lastSyncError:'incomplete'});
  assert.equal(await context.maintain(params),'incomplete');assert.equal(restores.pop(),dirty);
  await context.maintain({...params,acquireManager:async()=>null});assert.equal(restores.pop(),dirty);
  await assert.rejects(context.maintain({...params,acquireManager:async()=>{throw Error('acquire-failed');}}),/acquire-failed/);
  assert.equal(restores.pop(),dirty);
  console.log('PASS: incremental routing, mismatch/missing rebuild, retries, explicit force, lease release, dirty handoff and failure restoration');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
