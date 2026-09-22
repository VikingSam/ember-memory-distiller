'use strict';
// No application data is serialized. Only fixed labels, numeric IDs and timings.
const { AsyncLocalStorage } = require('node:async_hooks');
const { performance, monitorEventLoopDelay } = require('node:perf_hooks');
const path = require('node:path');
const { fileURLToPath } = require('node:url');
const inspector = require('node:inspector');
const PHASES = new Set(['manager_get','search','provider_init','sync_admitted','background_maintenance','sync_pass','startup_catchup','session_update','memory_files','session_files','prepare_entry','write_chunks','batch_embedding','query_embedding','provider_probe','bootstrap_probe','embedding_request','retry_sleep','fts','vector','generation_read_wait','generation_write_wait','generation_write_hold','workspace_operation','workspace_hold']);
const REASONS = new Set(['watch','interval','session-delta','session-startup-catchup','cli','search','session-start','retry','fallback']);
function errorClass(err) {
  // Inspect locally; never emit messages, arbitrary codes or provider bodies.
  try {
    const chain = [err, err?.cause];
    for (const e of chain) {
      const status = e?.status ?? e?.statusCode;
      if (Number.isInteger(status) && status >= 400 && status <= 599) return 'http_' + status;
      if (['SQLITE_BUSY','SQLITE_LOCKED','ETIMEDOUT','ECONNRESET','ECONNREFUSED','EAI_AGAIN','ABORT_ERR'].includes(e?.code)) return e.code;
      const message = typeof e?.message === 'string' ? e.message : '';
      if (/database is locked|SQLITE_BUSY|SQLITE_LOCKED/i.test(message)) return 'sqlite_locked';
      if (/\b429\b|rate.?limit|too many requests/i.test(message)) return 'rate_limit';
      if (/timed?\s*out|timeout/i.test(message)) return 'timeout';
      if (/abort/i.test(message)) return 'aborted';
      if (/fetch failed|ECONNRESET|socket|network/i.test(message)) return 'transport';
    }
  } catch {}
  return 'other';
}
function safeProfile(profile, packageDir) {
  const counts = new Map();
  for (const id of profile.samples ?? []) counts.set(id, (counts.get(id) ?? 0) + 1);
  const rows = new Map();
  const prefix = path.resolve(packageDir, 'dist') + path.sep;
  for (const node of profile.nodes ?? []) {
    const samples = counts.get(node.id) ?? 0;
    if (!samples) continue;
    const f = node.callFrame ?? {};
    let file = 'outside-openclaw', line = 0;
    try {
      const url = f.url ?? '';
      const p = url.startsWith('file:') ? fileURLToPath(url) : url;
      if (path.isAbsolute(p) && path.resolve(p).startsWith(prefix)) {
        const base = path.basename(p);
        if (/^[A-Za-z0-9_.-]+\.m?js$/.test(base)) { file = base; line = Math.max(0, (f.lineNumber ?? -1) + 1); }
      } else if (['(idle)','(garbage collector)','(program)'].includes(f.functionName)) file = f.functionName;
    } catch {}
    const key = file + ':' + line;
    const row = rows.get(key) ?? {file,line,samples:0};
    row.samples += samples; rows.set(key,row);
  }
  return [...rows.values()].sort((a,b) => b.samples-a.samples).slice(0,20);
}
function createRuntime(options = {}) {
  const durationMs = options.durationMs ?? 180000;
  const now = options.now ?? (() => performance.now());
  const start = now(), context = new AsyncLocalStorage(), active = new Map();
  let sequence=0, count=0, capped=false, stopped=false, finishing=false;
  const maxRecords = options.maxRecords ?? 2000;
  const sink = options.sink ?? (record => process.stderr.write('EMBER_GATEWAY_TRACE ' + JSON.stringify(record) + '\n'));
  const live = () => !stopped && now()-start < durationMs;
  function emit(record, force=false) {
    if (!force && !live()) return;
    if (!force && count >= maxRecords) {
      if (!capped) { capped=true; emit({event:'record_cap',limit:maxRecords},true); }
      return;
    }
    count++;
    try { sink({pid:process.pid,at_ms:Math.round(now()-start),...record}); } catch {}
  }
  function meta(phase, args) {
    const out={};
    if (['sync_admitted','sync_pass','background_maintenance'].includes(phase)) {
      const reason=args?.[0]?.reason;
      out.reason=REASONS.has(reason)?reason:'other';
    }
    if (phase==='batch_embedding' && Array.isArray(args?.[0])) out.items=args[0].length;
    if (phase==='embedding_request' && Number.isFinite(args?.[0]?.timeoutMs)) out.timeout_ms=args[0].timeoutMs;
    return out;
  }
  async function timed(phase, run, args) {
    if (!PHASES.has(phase) || !live() || capped) return run();
    const id=++sequence, parent=context.getStore() ?? null, t=now();
    const record={id,parent,phase,...meta(phase,args)};
    if (active.size < 256) active.set(id,record);
    emit({event:'start',...record});
    return context.run(id,async () => {
      let ok=false, failure;
      try { const result=await run();ok=true;return result; }
      catch (err) {failure=errorClass(err);throw err;}
      finally {
        active.delete(id);
        emit({event:'end',id,parent,phase,ok,elapsed_ms:Math.round(now()-t),...(failure?{error_class:failure}:{})});
      }
    });
  }
  let timer, ticks, delay, session;
  let cpu=process.cpuUsage(), wall=now();
  async function finish() {
    if (finishing || stopped) return;
    finishing=true; stopped=true;
    clearTimeout(timer);clearInterval(ticks);delay?.disable();
    emit({event:'capture_end',active:[...active.values()],record_cap_reached:capped},true);
    if (session) {
      try {
        const {profile}=await post('Profiler.stop');
        emit({event:'cpu_samples',sample_interval_us:10000,frames:safeProfile(profile,options.packageDir),note:'exclusive_samples_not_lock_wait_time'},true);
        await post('Profiler.disable');
      } catch {emit({event:'profiler_unavailable'},true);}
      finally {session.disconnect();session=null;}
    }
  }
  const post=(method,params={})=>new Promise((resolve,reject)=>session.post(method,params,(err,result)=>err?reject(err):resolve(result)));
  async function startCapture() {
    emit({event:'capture_start',duration_ms:durationMs,max_records:maxRecords});
    // A local inspector session only: no TCP inspector port is opened.
    if (options.profile !== false) {
      try {session=new inspector.Session();session.connect();await post('Profiler.enable');await post('Profiler.setSamplingInterval',{interval:10000});await post('Profiler.start');}
      catch {try {session?.disconnect();} catch {} session=null;emit({event:'profiler_unavailable'});}
    }
    if (stopped) return;
    delay=monitorEventLoopDelay({resolution:50});delay.enable();
    ticks=setInterval(()=>{
      const t=now(), usage=process.cpuUsage(cpu), elapsed=t-wall;
      cpu=process.cpuUsage();wall=t;
      emit({event:'health',elapsed_ms:Math.round(elapsed),cpu_ms:Math.round((usage.user+usage.system)/1000),event_loop_max_ms:Math.round(delay.max/1e6),active_ids:[...active.keys()]});
      delay.reset();
    },10000);ticks.unref();
    timer=setTimeout(()=>void finish(),Math.max(1,durationMs-(now()-start)));timer.unref();
  }
  function wrap(target, method, phase) {
    const original=target[method];
    if (typeof original!=='function') throw new Error('Ember gateway trace: missing fixed method');
    target[method]=function(...args){return timed(phase,()=>original.apply(this,args),args);};
  }
  return {timed,wrap,emit,startCapture,finish};
}
module.exports={createRuntime,errorClass,safeProfile};
