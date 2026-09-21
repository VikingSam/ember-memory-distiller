const fs=require('node:fs'), assert=require('node:assert/strict');
const {DatabaseSync}=require('node:sqlite');
const source=JSON.parse(fs.readFileSync(0,'utf8'));
const db=new DatabaseSync(':memory:');
db.exec('CREATE TABLE memory_session_tombstones(session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, reason TEXT, created_at INTEGER)');
const insert=db.prepare('INSERT INTO memory_session_tombstones VALUES(?,?,?,?)');
for(let i=0;i<1400;i++)insert.run('id'+i,i%9?'main':'other','forgotten',i);
insert.run('é','main','unicode',1);insert.run('𝄞','main','unicode',2);
const selectors=Array.from({length:37706},(_,i)=>'id'+i);
const ensuredTombstoneDatabases=new WeakSet();
let present=true, tablePresent=true, maxBindings=0, guard=false, fail=false, queries=0;
function tableExists(){return tablePresent;}
function withOpenClawAgentDatabaseReadOnly(fn){return present?{found:true,value:fn({db})}:{found:false};}
function getNodeSqliteKysely(){
 const q={clauses:[],selectFrom(){return q;},selectAll(){return q;},where(c,op,v){q.clauses.push({c,op,v});return q;},orderBy(){return q;}};return q;
}
function executeSqliteQuerySync(db,q){
 queries++;if(fail && queries===2)throw new Error('synthetic failure');
 const params=q.clauses.flatMap(x=>x.op==='in'?x.v:[x.v]);
 maxBindings=Math.max(maxBindings,params.length);
 if(guard && params.length>999)throw new Error('too many SQL variables (999 guard)');
 const where=q.clauses.map(x=>x.op==='in'?x.c+' IN ('+x.v.map(()=>'?').join(',')+')':x.c+' = ?').join(' AND ');
 return {rows:db.prepare('SELECT * FROM memory_session_tombstones WHERE '+where+' ORDER BY session_id ASC').all(...params)};
}
const original=eval('('+source.old+')'),patched=eval('('+source.new+')');
assert.throws(()=>original({agentId:'main',sessionIds:selectors}),/too many SQL variables/);
const originalBindings=maxBindings; maxBindings=0; guard=true;
db.exec('PRAGMA query_only=ON');
const map=r=>({sessionId:r.session_id,agentId:r.agent_id,reason:r.reason,createdAt:r.created_at});
const expected=db.prepare("SELECT * FROM memory_session_tombstones WHERE agent_id='main' ORDER BY session_id").all().filter(r=>r.session_id.startsWith('id')).map(map);
assert.deepEqual(patched({agentId:'main',sessionIds:selectors}),expected);
assert.deepEqual(patched({agentId:'main',sessionIds:[...selectors,'id1','id1']}),expected);
assert.deepEqual(patched({agentId:'main'}),original({agentId:'main'}));
assert.deepEqual(patched({agentId:'main',sessionIds:['é','𝄞','id2','id1']}),original({agentId:'main',sessionIds:['é','𝄞','id2','id1']}));
assert.deepEqual(patched({agentId:'main',sessionIds:[]}),[]);
assert.deepEqual(patched({agentId:'missing',sessionIds:selectors}),[]);
present=false;assert.deepEqual(patched({agentId:'main'}),[]);present=true;
tablePresent=false;assert.deepEqual(patched({agentId:'main'}),[]);tablePresent=true;
db.exec('BEGIN');patched({agentId:'main',sessionIds:selectors});assert.equal(db.isTransaction,true);db.exec('ROLLBACK');
queries=0;fail=true;assert.throws(()=>patched({agentId:'main',sessionIds:selectors}),/synthetic failure/);assert.equal(db.isTransaction,false);fail=false;
assert.deepEqual(patched({agentId:'main',sessionIds:selectors}),expected);
console.log(JSON.stringify({originalBindings,maxBindings,semanticsVerified:true}));db.close();
