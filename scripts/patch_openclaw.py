#!/usr/bin/env python3
"""Version-scoped, backed-up patch for the captured session archive lookup overflow.

Targets the function identified by the 74,434-bind instrumented stack.
Unknown installed code is rejected instead of guessed at.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ember_memory.storage import Plan, locked, restore

OLD = '''function listSessionTranscriptArchivesReadOnly(scope) {
	const selectors = [...new Set(scope.sessionIds)];
	if (selectors.length === 0) return [];
	const resolved = resolveSqliteReadScope(scope);
	const result = withOpenClawAgentDatabaseReadOnly(({ db, agentId }) => {
		return executeSqliteQuerySync(db, getSessionKysely(db).selectFrom("session_transcript_archives").select([
			"archive_name as archiveName",
			"session_id as sessionId",
			"session_key as sessionKey",
			"created_at as createdAt"
		]).where((expression) => expression.or([expression("session_id", "in", selectors), expression("session_key", "in", selectors)])).orderBy("created_at").orderBy("session_id")).rows.filter((row) => resolveAgentIdFromSessionKey(row.sessionKey, agentId) === resolved.agentId);
	}, toDatabaseOptions(resolved));
	return result.found ? result.value : [];
}'''
NEW = '''function listSessionTranscriptArchivesReadOnly(scope) {
	// ember-memory: bounded-session-archives-v2; two IN lists, <=800 bindings.
	const selectors = [...new Set(scope.sessionIds)];
	if (selectors.length === 0) return [];
	const resolved = resolveSqliteReadScope(scope);
	const result = withOpenClawAgentDatabaseReadOnly(({ db, agentId }) => {
		const byArchive = new Map();
		// Keep all batches in one read snapshot, including when already in a transaction.
		db.exec("SAVEPOINT ember_archive_lookup");
		try {
			for (let start = 0; start < selectors.length; start += 400) {
				const batch = selectors.slice(start, start + 400);
				const rows = executeSqliteQuerySync(db, getSessionKysely(db).selectFrom("session_transcript_archives").select([
					"archive_name as archiveName",
					"session_id as sessionId",
					"session_key as sessionKey",
					"created_at as createdAt"
				]).where((expression) => expression.or([expression("session_id", "in", batch), expression("session_key", "in", batch)])).orderBy("created_at").orderBy("session_id")).rows;
				for (const row of rows) {
					if (resolveAgentIdFromSessionKey(row.sessionKey, agentId) === resolved.agentId) byArchive.set(row.archiveName, row);
				}
			}
			db.exec("RELEASE ember_archive_lookup");
		} catch (error) {
			db.exec("ROLLBACK TO ember_archive_lookup");
			db.exec("RELEASE ember_archive_lookup");
			throw error;
		}
		// Restore the original global ordering; do not concatenate batch-local orders.
		return [...byArchive.values()].sort((a, b) => a.createdAt - b.createdAt || Buffer.compare(Buffer.from(a.sessionId), Buffer.from(b.sessionId)));
	}, toDatabaseOptions(resolved));
	return result.found ? result.value : [];
}'''
TARGET = 'dist/session-accessor.sqlite-entry-CoLie3L_.js'


def patch_plan(root):
    plan = Plan(root)
    package = json.loads(plan.read('package.json'))
    if package.get('name') != 'openclaw' or package.get('version') != '2026.8.1':
        raise ValueError('Only OpenClaw 2026.8.1 is supported; inspect a new version before patching')
    matches = []
    for path in [root / TARGET]:
        rel = str(path.relative_to(root))
        text = plan.read(rel)
        if OLD in text:
            if text.count(OLD) != 1:
                raise ValueError('Ambiguous patch target')
            plan.write(rel, text.replace(OLD, NEW))
            matches.append(rel)
        elif NEW in text:
            matches.append(rel)
    if not matches:
        raise ValueError('Expected function not found; no patch applied. Send sanitized diagnostic callsites.')
    return plan


def revert_latest(root):
    candidates = []
    for path in root.glob('.ember-distiller/backups/*/manifest.json'):
        manifest = json.loads(path.read_text())
        if set(manifest['files']) == {TARGET} and manifest['status'] in ('prepared', 'committed'):
            candidates.append(path)
    if not candidates:
        raise ValueError('No active patch backup found; nothing reverted')
    latest = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    restore(root, latest.parent.name)
    return latest.parent.name


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir', type=Path, required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--restore')
    p.add_argument('--revert', action='store_true', help='Restore the most recent active backup for the exact patch target')
    args = p.parse_args()
    root = args.package_dir.resolve()
    with locked(root):
        if args.restore or args.revert:
            if args.dry_run:
                raise ValueError('Restore does not support dry-run')
            if args.revert:
                print(json.dumps({'reverted_backup': revert_latest(root)}))
            else:
                restore(root, args.restore)
            return
        plan = patch_plan(root)
        if args.dry_run:
            print(json.dumps({'changed_files': list(plan.changes()), 'patch': 'bounded session archive lookup; max 800 bindings'}))
        else:
            backup = plan.commit()
            print(json.dumps({'backup_id': backup, 'changed_files': list(plan.changes()), 'revert': f'python3 -B scripts/patch_openclaw.py --package-dir {root} --revert'}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
