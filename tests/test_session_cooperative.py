import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import patch_session_cooperative as p

ROOT=Path(__file__).resolve().parents[1]

class CooperativeTests(unittest.TestCase):
    def test_corpus_semantics_yielding_freshness_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            addition=Path(d)/'addition.js';addition.write_text(p.corpus_steps()+'\n'+p.ASYNC_NEW)
            r=subprocess.run(['node',str(ROOT/'tests/session_cooperative_harness.cjs'),str(ROOT/'tests/session_corpus_fixture.js'),str(addition)],text=True,capture_output=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr)
            print(r.stdout.strip())

    def test_real_sqlite_archive_equivalence_large_selectors_readonly(self):
        script=r'''
const assert=require('node:assert/strict');const vm=require('node:vm');const {DatabaseSync}=require('node:sqlite');
const {performance}=require('node:perf_hooks');
const db=new DatabaseSync(':memory:');
db.exec(`CREATE TABLE session_transcript_archives(session_id TEXT, session_key TEXT,archive_name TEXT UNIQUE,created_at INTEGER,archive_blob BLOB,PRIMARY KEY(session_id,archive_name));`);
const insert=db.prepare('INSERT INTO session_transcript_archives VALUES(?,?,?,?,?)');
db.exec('BEGIN');for(let i=0;i<38000;i++)insert.run('s'+i,i%17===0?'agent:two:k'+i:'agent:one:k'+i,'archive'+i,38000-i,Buffer.alloc(256));
insert.run('special','agent:one:quoted\"key','quotes',0,Buffer.alloc(0));db.exec('COMMIT');db.exec('PRAGMA query_only=ON');
let selects=0;
const wrapped={exec:sql=>db.exec(sql),prepare(sql){selects++;return db.prepare(sql);}};
const c=vm.createContext({JSON,Map,Set,Buffer,TypeError,
 resolveSqliteReadScope:s=>({agentId:s.agentId}),toDatabaseOptions:x=>x,
 withOpenClawAgentDatabaseReadOnly:(op,opt)=>({found:true,value:op({db:wrapped,agentId:opt.agentId})}),
 resolveAgentIdFromSessionKey:key=>key.split(':')[1],
 getSessionKysely:()=>({selectFrom(){return this},select(){return this},where(fn){let batches;const e=(col,op,values)=>{batches=values;return values};e.or=x=>x;fn(e);this.batch=batches;return this},orderBy(){return this}}),
 executeSqliteQuerySync:(unused,q)=>{selects++;const marks=q.batch.map(()=>'?').join(',');return {rows:db.prepare(`SELECT archive_name AS archiveName,session_id AS sessionId,session_key AS sessionKey,created_at AS createdAt FROM session_transcript_archives WHERE session_id IN (${marks}) OR session_key IN (${marks}) ORDER BY created_at,session_id`).all(...q.batch,...q.batch)}}
});
vm.runInContext(OLD+'\nconst oldLookup=listSessionTranscriptArchivesReadOnly;\n'+NEW+'\nconst newLookup=listSessionTranscriptArchivesReadOnly;',c);
// Use distinct contexts because declaration hoisting must not replace oldLookup.
vm.runInContext('globalThis.before='+OLD+';globalThis.after='+NEW+';',c);
const selectors=Array.from({length:40000},(_,i)=>'s'+i);selectors.push('s0','agent:one:quoted\"key','agent:one:k1');
const scope={agentId:'one',sessionIds:selectors};
const totalBefore=db.prepare('SELECT total_changes() AS n').get().n;
let t=performance.now();selects=0;const old=c.before(scope);const oldMs=performance.now()-t,oldCalls=selects;
t=performance.now();selects=0;const next=c.after(scope);const newMs=performance.now()-t,newCalls=selects;
assert.deepEqual(JSON.parse(JSON.stringify(next)),JSON.parse(JSON.stringify(old)));
assert.equal(newCalls,1);assert(oldCalls>90);assert.equal(db.prepare('SELECT total_changes() AS n').get().n,totalBefore);
assert.equal(c.after({agentId:'one',sessionIds:[]}).length,0);
db.exec('BEGIN');assert.equal(c.after({agentId:'one',sessionIds:['s1']}).length,1);assert(db.isTransaction);db.exec('ROLLBACK');
assert(!next.some(r=>r.sessionKey.startsWith('agent:two:')));
console.log(JSON.stringify({archive_equivalence:true,rows:next.length,old_queries:oldCalls,new_queries:newCalls,old_ms:Math.round(oldMs),new_ms:Math.round(newMs),bindings:2}));db.close();
'''.replace('OLD',json.dumps(p.ARCHIVE_V2)).replace('NEW',json.dumps(p.ARCHIVE_NEW))
        r=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=60)
        self.assertEqual(r.returncode,0,r.stderr);print(r.stdout.strip())

    def test_exact_state_apply_idempotence_and_two_file_revert(self):
        old={p.CORPUS:p.CORPUS_SYNC+'\n'+p.ASYNC_OLD, p.ARCHIVE:p.ARCHIVE_V2}
        new={name:p.transform(name,text) for name,text in old.items()}
        digest=lambda text:hashlib.sha256(text.encode()).hexdigest()
        baseline={'dist/unchanged.js':digest('preserve')}
        with tempfile.TemporaryDirectory() as d, patch.object(p,'BEFORE',{n:digest(s) for n,s in old.items()}),patch.object(p,'AFTER',{n:digest(s) for n,s in new.items()}),patch.object(p,'BASELINE',baseline):
            root=Path(d);(root/'package.json').write_text(json.dumps({'name':'openclaw','version':'2026.8.1'}))
            for name,text in old.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
            (root/'dist/unchanged.js').write_text('preserve')
            plan=p.patch_plan(root);self.assertEqual(set(plan.changes()),set(old))
            self.assertEqual((root/p.CORPUS).read_text(),old[p.CORPUS])
            backup=plan.commit();self.assertEqual(p.patch_plan(root).changes(),{})
            (root/p.ARCHIVE).write_text(new[p.ARCHIVE]+'\n// later edit')
            with self.assertRaises((ValueError,RuntimeError)):p.revert_latest(root)
            self.assertEqual((root/p.CORPUS).read_text(),new[p.CORPUS])
            (root/p.ARCHIVE).write_text(new[p.ARCHIVE])
            self.assertEqual(p.revert_latest(root),backup)
            for name,text in old.items():self.assertEqual((root/name).read_text(),text)
            self.assertEqual((root/'dist/unchanged.js').read_text(),'preserve')
            # A partial/mixed reinstall must not produce a one-file rollback manifest.
            (root/p.ARCHIVE).write_text(new[p.ARCHIVE])
            with self.assertRaisesRegex(ValueError,'mixed'):p.patch_plan(root)
            self.assertEqual((root/p.CORPUS).read_text(),old[p.CORPUS])
            (root/p.ARCHIVE).write_text(old[p.ARCHIVE])
            (root/'dist/unchanged.js').write_text('drift')
            with self.assertRaisesRegex(ValueError,'baseline'):p.patch_plan(root)

if __name__=='__main__':unittest.main()
