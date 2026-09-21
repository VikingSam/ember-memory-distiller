#!/usr/bin/env python3
"""Version-scoped, backed-up patch for the captured session tombstone lookup overflow.

Targets the function identified by the 37,707-bind instrumented stack.
Unknown installed code is rejected instead of guessed at.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ember_memory.storage import Plan, locked, restore

OLD = '''function listMemorySessionTombstones(params) {
	if (params.sessionIds?.length === 0) return [];
	const result = withOpenClawAgentDatabaseReadOnly(({ db }) => {
		if (!ensuredTombstoneDatabases.has(db) && !tableExists(db, "memory_session_tombstones")) return [];
		let query = getNodeSqliteKysely(db).selectFrom("memory_session_tombstones").selectAll().where("agent_id", "=", params.agentId);
		if (params.sessionIds) query = query.where("session_id", "in", params.sessionIds);
		return executeSqliteQuerySync(db, query.orderBy("session_id", "asc")).rows.map((row) => ({
			sessionId: row.session_id,
			agentId: row.agent_id,
			reason: row.reason,
			createdAt: row.created_at
		}));
	}, params);
	return result.found ? result.value : [];
}'''
NEW = '''function listMemorySessionTombstones(params) {
	// ember-memory: bounded-session-tombstones-v3; <=401 bindings including agent.
	if (params.sessionIds?.length === 0) return [];
	const selectors = params.sessionIds ? [...new Set(params.sessionIds)] : void 0;
	const result = withOpenClawAgentDatabaseReadOnly(({ db }) => {
		if (!ensuredTombstoneDatabases.has(db) && !tableExists(db, "memory_session_tombstones")) return [];
		const rowsBySession = new Map();
		db.exec("SAVEPOINT ember_tombstone_lookup");
		try {
			for (let start = 0; start < (selectors?.length ?? 1); start += 400) {
				let query = getNodeSqliteKysely(db).selectFrom("memory_session_tombstones").selectAll().where("agent_id", "=", params.agentId);
				if (selectors) query = query.where("session_id", "in", selectors.slice(start, start + 400));
				for (const row of executeSqliteQuerySync(db, query.orderBy("session_id", "asc")).rows) rowsBySession.set(row.session_id, row);
			}
			db.exec("RELEASE ember_tombstone_lookup");
		} catch (error) {
			db.exec("ROLLBACK TO ember_tombstone_lookup");
			db.exec("RELEASE ember_tombstone_lookup");
			throw error;
		}
		return [...rowsBySession.values()].sort((a, b) => Buffer.compare(Buffer.from(a.session_id), Buffer.from(b.session_id))).map((row) => ({
			sessionId: row.session_id,
			agentId: row.agent_id,
			reason: row.reason,
			createdAt: row.created_at
		}));
	}, params);
	return result.found ? result.value : [];
}'''
TARGET = 'dist/memory-entry-origins-DHPCnUGh.js'


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
            print(json.dumps({'changed_files': list(plan.changes()), 'patch': 'bounded session tombstone lookup; max 401 bindings'}))
        else:
            backup = plan.commit()
            print(json.dumps({'backup_id': backup, 'changed_files': list(plan.changes()), 'revert': f'python3 -B scripts/patch_tombstones.py --package-dir {root} --revert'}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
