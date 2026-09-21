// Synthetic only. Executes the exact replacement function against real SQLite.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { DatabaseSync } = require('node:sqlite');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const db = new DatabaseSync(':memory:');
db.exec('CREATE TABLE session_transcript_archives (archive_name TEXT UNIQUE, session_id TEXT, session_key TEXT, created_at INTEGER)');
const insert = db.prepare('INSERT INTO session_transcript_archives VALUES(?,?,?,?)');
const selectors = Array.from({length:37217}, (_,i)=>`id${i}`);
selectors[1000] = 'main:key0'; // same row matches in two different batches
for(let i=0;i<1800;i++) insert.run(`archive${i}`,`id${i}`,`${i%11===0?'other':'main'}:key${i}`,1800-i);
// Ensure a cross-batch duplicate survives exactly once and test ordering ties.
insert.run('cross','id2000','main:key0',10);
insert.run('tie-a','id99','main:tie-a',10);
insert.run('tie-b','id98','main:tie-b',10);
let maxBindings=0, enforce999=false, injectFailure=false, queryCount=0, databasePresent=true;
function getSessionKysely(){
 const q={selectFrom(){return q;},select(){return q;},where(fn){
   const expr=(column,op,values)=>({column,values});expr.or=(parts)=>parts;q.parts=fn(expr);return q;
 },orderBy(){return q;}};return q;
}
function executeSqliteQuerySync(db,q){
 queryCount++;
 if(injectFailure && queryCount===2)throw new Error('synthetic query failure');
 const bindings=q.parts.flatMap(p=>p.values);
 maxBindings=Math.max(maxBindings,bindings.length);
 if(enforce999 && bindings.length>999) throw new Error('too many SQL variables (999 test guard)');
 const sql='SELECT archive_name AS archiveName, session_id AS sessionId, session_key AS sessionKey, created_at AS createdAt FROM session_transcript_archives WHERE '+q.parts.map(p=>p.column+' IN ('+p.values.map(()=>'?').join(',')+')').join(' OR ')+' ORDER BY created_at, session_id';
 return {rows:db.prepare(sql).all(...bindings)};
}
function resolveSqliteReadScope(scope){return scope;}
function toDatabaseOptions(scope){return scope;}
function resolveAgentIdFromSessionKey(key,fallback){return key.includes(':')?key.split(':')[0]:fallback;}
function withOpenClawAgentDatabaseReadOnly(fn){return databasePresent?{found:true,value:fn({db,agentId:'main'})}:{found:false};}
const original=eval('('+source.old+')');
const patched=eval('('+source.new+')');
assert.throws(()=>original({sessionIds:selectors,agentId:'main'}),/too many SQL variables/);
const originalBindings=maxBindings;maxBindings=0;enforce999=true;
const selected=new Set(selectors);
const expected=db.prepare('SELECT archive_name AS archiveName, session_id AS sessionId, session_key AS sessionKey, created_at AS createdAt FROM session_transcript_archives ORDER BY created_at,session_id').all().filter(r=>(selected.has(r.sessionId)||selected.has(r.sessionKey))&&r.sessionKey.startsWith('main:'));
db.exec('PRAGMA query_only=ON');
const actual=patched({sessionIds:selectors,agentId:'main'});
assert.deepEqual(actual,expected);
assert.equal(actual.filter(r=>r.archiveName==='cross').length,1);
assert.equal(db.isTransaction,false);
assert.deepEqual(patched({sessionIds:[],agentId:'main'}),[]);
assert.deepEqual(patched({sessionIds:['id1','id1'],agentId:'main'}),original({sessionIds:['id1'],agentId:'main'}));
databasePresent=false;assert.deepEqual(patched({sessionIds:['id1'],agentId:'main'}),[]);databasePresent=true;
db.exec('BEGIN'); patched({sessionIds:selectors,agentId:'main'});assert.equal(db.isTransaction,true);db.exec('ROLLBACK');
injectFailure=true;queryCount=0;
assert.throws(()=>patched({sessionIds:selectors,agentId:'main'}),/synthetic query failure/);
assert.equal(db.isTransaction,false);
injectFailure=false;
assert.deepEqual(patched({sessionIds:selectors,agentId:'main'}),expected);
console.log(JSON.stringify({originalBindings,maxPatchedBindings:maxBindings,sameRowsAndOrder:true,rollbackVerified:true}));db.close();
