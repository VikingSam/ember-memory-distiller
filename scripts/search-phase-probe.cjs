// One CLI process (and its inherited Node children), never a gateway preload.
'use strict';
// register() starts a loader worker which inherits --require; do not recurse.
if (!require('node:worker_threads').isMainThread) return;
const { register } = require('node:module');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
globalThis.__emberSearchProbeBootAt = performance.now();
const args = process.argv.slice(1);
if (!args.some((arg, i) => arg === 'memory' && args[i + 1] === 'search') &&
    process.env.EMBER_SEARCH_PROBE_ACTIVE !== '1') {
  throw new Error('Ember search probe permits only the memory search CLI command');
}
const mode = process.env.EMBER_SEARCH_PROBE_MODE;
if (!['published-only', 'observe'].includes(mode)) {
  throw new Error('Set EMBER_SEARCH_PROBE_MODE to published-only or observe');
}
process.env.EMBER_SEARCH_PROBE_ACTIVE = '1';
register(pathToFileURL(path.join(__dirname, 'search-phase-loader.mjs')), {
  parentURL: pathToFileURL(__filename), data: { publishedOnly: mode === 'published-only' }
});
process.stderr.write('EMBER_SEARCH_PHASE ' + JSON.stringify({event:'preload',pid:process.pid,at_ms:0,mode}) + '\n');
process.once('exit', code => process.stderr.write('EMBER_SEARCH_PHASE ' + JSON.stringify({
  event:'process_exit',pid:process.pid,code,
  at_ms:Math.round(performance.now()-globalThis.__emberSearchProbeBootAt)
}) + '\n'));
