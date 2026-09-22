'use strict';
// Explicit Ember-only scope; inherited workers and non-gateway children do nothing.
if (!require('node:worker_threads').isMainThread) return;
const path=require('node:path');
const fs=require('node:fs');
const {createHash}=require('node:crypto');
const {pathToFileURL}=require('node:url');
if (!process.argv.slice(1).includes('gateway')) return;
if (process.env.EMBER_GATEWAY_TRACE!=='1' ||
    !process.env.EMBER_TRACE_STATE_DIR || process.env.OPENCLAW_STATE_DIR!==process.env.EMBER_TRACE_STATE_DIR ||
    !process.env.EMBER_TRACE_UNIT || process.env.OPENCLAW_SYSTEMD_UNIT!==process.env.EMBER_TRACE_UNIT) {
  throw new Error('Ember gateway trace: explicit Ember service scope required');
}
const packageDir=process.env.EMBER_TRACE_PACKAGE_DIR;
if (!packageDir || !path.isAbsolute(packageDir)) throw new Error('Ember gateway trace: explicit package directory required');
const target=path.join(packageDir,'dist/extensions/memory-core/manager-runtime.js');
const expected='e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df';
if(createHash('sha256').update(fs.readFileSync(target)).digest('hex')!==expected) {
  throw new Error('Ember gateway trace: V5 hash mismatch');
}
if(createHash('sha256').update(fs.readFileSync(path.join(packageDir,'dist/tools-DNmkgIrY.js'))).digest('hex')!=='5efc8c5eb2079a359adedf3e2f8abfb93780f5bac54b4314bc3cba1e2c9873c5') throw new Error('Ember gateway trace: tools hash mismatch');
const {createRuntime}=require('./gateway-trace-runtime.cjs');
globalThis.__emberGatewayTrace=createRuntime({packageDir,searchTriggered:true});
require('node:module').register(pathToFileURL(path.join(__dirname,'gateway-trace-loader.mjs')),{parentURL:pathToFileURL(__filename),data:{packageDir}});
globalThis.__emberGatewayTrace.arm();
