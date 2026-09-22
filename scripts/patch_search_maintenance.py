#!/usr/bin/env python3
"""Exact-hash OpenClaw 2026.8.1 search-maintenance patch; backed up and reversible."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ember_memory.storage import Plan, locked, restore

TARGET = 'dist/extensions/memory-core/manager-runtime.js'
ORIGINAL_SHA256 = '859363eb27769c57a371ebdf4d0b5d74f588faa882fb82f42cad9222966169bd'
PATCHED_SHA256 = '9580e3f7d3d18db3fa881e438cac96d93347a59e6e796b6a35b2733fb5f7a483'
REPLACEMENTS = [('\t\tawait manager.sync({\n\t\t\treason: params.reason,\n\t\t\tforce: true\n\t\t});', '\t\t// ember-memory v4: transfer pending work, not an unconditional full rebuild.\n\t\tmanager.restoreReindexRetryState(dirtyGeneration);\n\t\tawait manager.sync({\n\t\t\treason: params.reason,\n\t\t\temberSearchMaintenanceV4: true\n\t\t});'), ('\tasync runSyncPass(params) {\n\t\tthis.assertFtsOnlySyncAllowed();', '\tasync runSyncPass(params) {\n\t\t// Incremental maintenance mutates live tables: exclude generation readers.\n\t\tif (params?.emberSearchMaintenanceV4 && !params.emberGenerationLeaseHeldV4) {\n\t\t\tconst outcome = await withMemoryWorkspaceLock(this.workspaceDir, async () =>\n\t\t\t\tawait withMemoryIndexPublishGeneration(this.settings.store.databasePath, async () =>\n\t\t\t\t\tawait this.runSyncPass({ ...params, emberGenerationLeaseHeldV4: true })));\n\t\t\t// Release the lease before the full-rebuild path acquires its own lease.\n\t\t\tif (outcome === "ember-full-reindex-v4") await this.runSyncPass({\n\t\t\t\t...params, emberSearchMaintenanceV4: false, emberGenerationLeaseHeldV4: false, force: true\n\t\t\t});\n\t\t\treturn;\n\t\t}\n\t\tthis.assertFtsOnlySyncAllowed();'), ('const needsExplicitIdentityReindex = params?.reason === "cli" && indexIdentity.status !== "valid" && !hasTargetArchiveFiles;', 'const needsExplicitIdentityReindex = (params?.reason === "cli" || params?.emberSearchMaintenanceV4) && indexIdentity.status !== "valid" && !hasTargetArchiveFiles;'), ('\t\tconst needsFullSessionReindex = needsFullReindex || this.sessionsFullRetryDirty;', '\t\tif (needsFullReindex && params?.emberGenerationLeaseHeldV4) return "ember-full-reindex-v4";\n\t\tconst needsFullSessionReindex = needsFullReindex || this.sessionsFullRetryDirty;')]


def patch_plan(root):
    plan = Plan(root)
    package = json.loads(plan.read('package.json'))
    if package.get('name') != 'openclaw' or package.get('version') != '2026.8.1':
        raise ValueError('Only OpenClaw 2026.8.1 is supported')
    text = plan.read(TARGET)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest == PATCHED_SHA256:
        return plan
    if digest != ORIGINAL_SHA256:
        raise ValueError('Unknown manager-runtime.js hash; no changes. Review local modifications first.')
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise ValueError('Ambiguous patch anchor; no changes')
        text = text.replace(old, new)
    if hashlib.sha256(text.encode()).hexdigest() != PATCHED_SHA256:
        raise ValueError('Unexpected patch result; no changes')
    plan.write(TARGET, text)
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
            print(json.dumps({'changed_files': list(plan.changes()), 'patch': 'incremental search maintenance with generation exclusion; full rebuild on identity mismatch/retry'}))
        else:
            backup = plan.commit()
            print(json.dumps({'backup_id': backup, 'changed_files': list(plan.changes()), 'revert': f'python3 -B scripts/patch_search_maintenance.py --package-dir {root} --revert'}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
