#!/usr/bin/env python3
"""Exact-version V6 candidate: cooperative corpus scans and bounded archive selection."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ember_memory.storage import Plan, locked, restore
from scripts.patch_openclaw import NEW as ARCHIVE_V2

CORPUS = 'dist/memory-core-host-engine-sessions-BzzfWTfG.js'
ARCHIVE = 'dist/session-accessor.sqlite-entry-CoLie3L_.js'
BEFORE = {CORPUS: 'ee239cfc4d98c262cb54562bc971505199fd8fc4a9b8ed5e10ab0c17713113f8',
           ARCHIVE: '02efd3d54ae2fab43fadc60d09f0a5421375c3fd87820c4defb4b45e55c37ba0'}
AFTER = {'dist/memory-core-host-engine-sessions-BzzfWTfG.js': '26645cb127d4cecbec4f20ed0563cceaf31b1db463df3a625e05d5870501bf2e', 'dist/session-accessor.sqlite-entry-CoLie3L_.js': '4f519421417b86a97cfe306afe030366e9f4a75ef9f44d5162fb2465b52104d9'}
BASELINE = {
    'dist/extensions/memory-core/manager-runtime.js': 'e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df',
    'dist/memory-entry-origins-DHPCnUGh.js': 'fde5cbab1337a25a849d753849fda35cb1b5b83c526720593e66b1a56ad7e6a9'
}
CORPUS_SYNC = Path(__file__).with_name('v6_session_corpus_original.js').read_text().rstrip('\n')
ASYNC_OLD = '''async function listSessionTranscriptCorpusEntriesForAgent(agentId, options = {}) {
	return listSessionTranscriptCorpusEntriesForAgentSync(agentId, options);
}'''


def corpus_steps():
    source = CORPUS_SYNC.replace('function listSessionTranscriptCorpusEntriesForAgentSync(', 'function* emberSessionCorpusSteps(', 1)
    anchors = ['for (const summary of sessionEntries) {',
               'if (options.includeRetainedSqlite) for (const instance of retainedInstances) {',
               'for (const artifactDir of artifactDirsByPath.values()) for (const artifactPath of listSessionTranscriptArtifactFiles(artifactDir)) {']
    for anchor in anchors:
        if source.count(anchor) != 1:
            raise ValueError('Unexpected coroutine anchor')
        source = source.replace(anchor, anchor + '\n\t\tyield;')
    return source

ASYNC_NEW = '''// ember-memory v6: same enumeration rules, cooperative scheduling for async callers.
async function listSessionTranscriptCorpusEntriesForAgent(agentId, options = {}) {
	// Yield before entering the synchronous prelude, including during construction.
	await new Promise((resolve) => setImmediate(resolve));
	const steps = emberSessionCorpusSteps(agentId, options);
	let work = 0;
	let sliceStarted = performance.now();
	for (;;) {
		const step = steps.next();
		if (step.done) return step.value;
		if (++work >= 64 || performance.now() - sliceStarted >= 8) {
			await new Promise((resolve) => setImmediate(resolve));
			work = 0;
			sliceStarted = performance.now();
		}
	}
}'''

ARCHIVE_NEW = '''function listSessionTranscriptArchivesReadOnly(scope) {
	// ember-memory v6: two bound JSON arrays, one statement/read snapshot.
	const selectors = [...new Set(scope.sessionIds)];
	if (selectors.length === 0) return [];
	if (!selectors.every((value) => typeof value === "string")) throw new TypeError("Expected session identity strings");
	const resolved = resolveSqliteReadScope(scope);
	const result = withOpenClawAgentDatabaseReadOnly(({ db, agentId }) => {
		const encoded = JSON.stringify(selectors);
		return db.prepare(`SELECT archive_name AS archiveName, session_id AS sessionId,
			session_key AS sessionKey, created_at AS createdAt
			FROM session_transcript_archives
			WHERE session_id IN (SELECT value FROM json_each(?))
			   OR session_key IN (SELECT value FROM json_each(?))
			ORDER BY created_at, session_id`).all(encoded, encoded)
			.filter((row) => resolveAgentIdFromSessionKey(row.sessionKey, agentId) === resolved.agentId);
	}, toDatabaseOptions(resolved));
	return result.found ? result.value : [];
}'''


def transform(name, text):
    if name == CORPUS:
        if text.count(CORPUS_SYNC) != 1 or text.count(ASYNC_OLD) != 1:
            raise ValueError('Unexpected corpus source anchors')
        return text.replace(ASYNC_OLD, corpus_steps() + '\n' + ASYNC_NEW)
    if name == ARCHIVE:
        if text.count(ARCHIVE_V2) != 1:
            raise ValueError('Expected exact V2 archive lookup')
        return text.replace(ARCHIVE_V2, ARCHIVE_NEW)
    raise ValueError('Unknown patch target')


def patch_plan(root):
    plan = Plan(root)
    package = json.loads(plan.read('package.json'))
    if package.get('name') != 'openclaw' or package.get('version') != '2026.8.1':
        raise ValueError('Only OpenClaw 2026.8.1 is supported')
    # Preserve the known V5/V3 baseline; neither is edited by V6.
    for name, digest in BASELINE.items():
        if hashlib.sha256(plan.read(name).encode()).hexdigest() != digest:
            raise ValueError('Expected unchanged V5 manager and V3 tombstone baseline')
    installed = {name: hashlib.sha256(plan.read(name).encode()).hexdigest() for name in BEFORE}
    if installed == AFTER:
        return plan
    if installed != BEFORE:
        raise ValueError('Unknown or mixed patch state; no changes')
    for name in BEFORE:
        text = plan.read(name)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest == AFTER[name]:
            continue
        if digest != BEFORE[name]:
            raise ValueError('Unknown installed patch target; no changes')
        changed = transform(name, text)
        if hashlib.sha256(changed.encode()).hexdigest() != AFTER[name]:
            raise ValueError('Unexpected patch result; no changes')
        plan.write(name, changed)
    return plan


def revert_latest(root):
    candidates = []
    for path in root.glob('.ember-distiller/backups/*/manifest.json'):
        manifest = json.loads(path.read_text())
        if (set(manifest['files']) == set(BEFORE) and manifest['status'] in ('prepared', 'committed')
                and all(manifest['files'][name]['after'] == AFTER[name] for name in BEFORE)):
            candidates.append(path)
    if not candidates:
        raise ValueError('No active V6 backup found; nothing reverted')
    latest = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    restore(root, latest.parent.name)
    return latest.parent.name


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir', type=Path, required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--revert', action='store_true')
    args = p.parse_args()
    root = args.package_dir.resolve()
    with locked(root):
        if args.revert:
            if args.dry_run:
                raise ValueError('Revert does not support dry-run')
            print(json.dumps({'reverted_backup': revert_latest(root)}))
            return
        plan = patch_plan(root)
        changes = list(plan.changes())
        if args.dry_run:
            print(json.dumps({'changed_files': changes, 'patch': 'cooperative corpus enumeration; two-binding archive lookup'}))
        else:
            backup = plan.commit()
            print(json.dumps({'backup_id': backup, 'changed_files': changes}))

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
