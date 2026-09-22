'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const {performance}=require('node:perf_hooks');
const fixture=fs.readFileSync(process.argv[2],'utf8');
const addition=fs.readFileSync(process.argv[3],'utf8');
let shared=false,revision=1,fail=false,slow=false;
const records=[
 {sessionKey:'agent:one:main',entry:{sessionId:'active',updatedAt:10}},
 {sessionKey:'agent:two:main',entry:{sessionId:'foreign',updatedAt:11}},
 {sessionKey:'cron:one:job',entry:{sessionId:'cron',updatedAt:12}},
 {sessionKey:'agent:one:child',entry:{sessionId:'child',spawnedBy:'cron:one:job',updatedAt:13}}
];
const retained=[{provenanceKnown:true,acpOwned:false,sessionId:'retained',sessionKey:'agent:one:old',entry:{},updatedAtMs:9},
 {provenanceKnown:false,sessionId:'private',sessionKey:'agent:one:hidden',entry:{}}];
const names=Array.from({length:2000},(_,i)=>`archive-${i}.jsonl`);
names.push('foreign.jsonl','active.jsonl','notes.txt');
const io={statSync(p){if(slow){const end=performance.now()+0.08;while(performance.now()<end){}}return {isFile:()=>true,dev:1n,ino:2n,size:3n,mtimeNs:BigInt(revision),ctimeNs:4n};},
 realpathSync:p=>p,
 readdirSync(p){if(fail)throw Object.assign(new Error('fixture read failure'),{code:'EACCES'});return names.map(name=>({name,isFile:()=>true}));}};
const c=vm.createContext({fs:io,path,performance,setImmediate,
 normalizeAgentId:x=>x.toLowerCase(),getRuntimeConfig:()=>({session:shared?{store:'/shared/sessions.json'}:{}}),
 resolveStorePath:()=>shared?'/shared/sessions.json':'/agents/one/sessions/sessions.json',
 resolveSessionTranscriptsDirForAgent:()=>'/agents/one/sessions',
 extractAgentIdFromSessionsDir:p=>p.includes('/agents/one/')?'one':null,
 listSessionEntries:()=>records,listSessionTranscriptInstances:()=>retained,
 readTranscriptContentRevisionSync:()=>`revision:${revision}`,
 isDreamingNarrativeSessionStoreKey:k=>k.startsWith('dream:'),isCronRunSessionKey:k=>k.startsWith('cron:'),
 resolveSessionAgentId:({sessionKey})=>sessionKey.includes(':two:')?'two':'one',canonicalizeMainSessionAlias:({sessionKey})=>sessionKey,
 isUsageCountedSessionTranscriptFileName:n=>n.endsWith('.jsonl'),isSessionArchiveArtifactName:n=>n.endsWith('.jsonl'),
 parseUsageCountedSessionIdFromFileName:n=>n.slice(0,-6),process:{platform:process.platform}
});
vm.runInContext(fixture+'\n'+addition,c);
const plain=x=>JSON.parse(JSON.stringify(x));
(async()=>{
 for(shared of [false,true])for(const includeRetainedSqlite of [false,true]){
  const expected=c.listSessionTranscriptCorpusEntriesForAgentSync('one',{includeRetainedSqlite});
  const actual=await c.listSessionTranscriptCorpusEntriesForAgent('one',{includeRetainedSqlite});
  assert.deepEqual(plain(actual),plain(expected));
  assert(!actual.some(x=>x.sessionId==='private'));
  assert(!actual.some(x=>x.sessionId==='foreign'));
 }
 shared=false;slow=true;
 let tick=0,settled=false;const timer=setInterval(()=>tick++,1);
 const promise=c.listSessionTranscriptCorpusEntriesForAgent('one',{}).then(r=>{settled=true;return r;});
 assert.equal(settled,false);assert.equal(tick,0);
 await promise;clearInterval(timer);assert(tick>3,`other work did not run: ${tick}`);
 slow=false;const before=await c.listSessionTranscriptCorpusEntriesForAgent('one',{});revision++;
 const after=await c.listSessionTranscriptCorpusEntriesForAgent('one',{});
 assert.notEqual(before[0].contentRevision,after[0].contentRevision);
 names.push('new-archive.jsonl');assert((await c.listSessionTranscriptCorpusEntriesForAgent('one',{})).some(x=>x.sessionId==='new-archive'));
 names.splice(names.indexOf('new-archive.jsonl'),1);assert(!(await c.listSessionTranscriptCorpusEntriesForAgent('one',{})).some(x=>x.sessionId==='new-archive'));
 fail=true;await assert.rejects(c.listSessionTranscriptCorpusEntriesForAgent('one',{}),/fixture read failure/);
 console.log(JSON.stringify({corpus_equivalence:true,timer_ticks_during_scan:tick,freshness:true,error_propagation:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
