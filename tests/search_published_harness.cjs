const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
let background=0, leases=0, releases=0;
const ctx={
  resolveMemorySearchPreflight: p=>({shouldSearch:p.hasIndexedContent,normalizedQuery:p.query,shouldInitializeProvider:false}),
  startAsyncSearchSync:p=>{if(p.enabled && (p.dirty||p.sessionsDirty)){background++;return p.sync({reason:'search'});}},
  acquireMemoryIndexReadGeneration:async()=>{leases++;return()=>releases++;},
  uniqueValues:x=>[...new Set(x)], formatErrorMessage:e=>e.message,
  log$1:{warn:()=>{}},redactSensitiveText:x=>x,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8')+'\nglobalThis.Search=SearchFixture;',ctx);
function make(purpose, indexed=true, identity='valid') {
 const m=new ctx.Search();
 Object.assign(m,{
  purpose, providerRequirement:{mode:'optional'},provider:{model:'voyage-3'},providerRuntime:{},providerInitialized:true,
  providerLifecycle:{mode:'ready'},dirty:true,sessionsDirty:true,sources:new Set(['memory','sessions']),
  settings:{sync:{onSearch:true},store:{databasePath:'test'},query:{minScore:0,maxResults:6,hybrid:{enabled:true,candidateMultiplier:1}}},
  fts:{enabled:true,available:true},activeBackgroundSearchSyncs:new Set(),preflightSyncs:0,
  withManagerOperation:async f=>await f(),hasIndexedContent:()=>indexed,
  ensureProviderInitialized:async()=>{},assertRequiredProviderAvailable:()=>{},
  ensureEmbeddingProviderForSearch:async()=>false,claimSessionWarmSync:()=>true,
  refreshIndexIdentityDirty:()=>({status:identity}),
  syncAdmitted:async p=>{assert.equal(p.force,true);m.preflightSyncs++;indexed=true;identity='valid';},
  syncPublishedIndexInBackground:async()=>{throw Error('unexpected maintenance');},
  resolveProviderIndexIdentities:()=>[],acquireProviderUse:()=>()=>{},
  searchKeywordWithFallback:async()=>[{score:.595,path:'synthetic'}],
  finalizeKeywordOnlyResults:async p=>p.results,
 });return m;
}
(async()=>{
 for(const purpose of ['cli','default']) {
  const m=make(purpose);
  const result=await m.searchCandidates('synthetic',{lexicalOnly:true});
  assert.equal(result.length,1);assert.equal(result[0].score,.595);
  assert.equal(m.preflightSyncs,0);assert.equal(m.dirty,true);assert.equal(m.sessionsDirty,true);
 }
 assert.equal(background,0);assert.equal(leases,2);assert.equal(releases,2);
 for(const [indexed,identity] of [[false,'missing'],[true,'missing']]) {
  const m=make('default',indexed,identity);
  assert.equal((await m.searchCandidates('synthetic',{lexicalOnly:true})).length,1);
  assert.equal(m.preflightSyncs,1);
 }
 const m=make('default',true,'mismatched');
 m.adoptPublishedFallbackProviderIfMatched=async()=>false;
 assert.equal((await m.searchCandidates('synthetic',{})).length,0);
 const broken=make('default');broken.searchKeywordWithFallback=async()=>{throw Error('expected');};
 assert.equal((await broken.searchCandidates('synthetic',{lexicalOnly:true})).length,0);
 assert.equal(leases,releases);
 assert.equal(background,0);
 console.log('PASS: CLI/gateway published retrieval, dirty preservation, bootstrap/identity safety, lease release');
})().catch(e=>{console.error(e);process.exitCode=1;});
