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
ORIGINAL_SHA256 = '9580e3f7d3d18db3fa881e438cac96d93347a59e6e796b6a35b2733fb5f7a483'
PATCHED_SHA256 = 'e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df'
REPLACEMENTS = [('enabled: (this.settings.sync.onSearch || sessionStartSync) && (this.purpose === "default" || this.purpose === "cli"),', 'enabled: false, // ember-memory v5: retrieval uses published index; update listeners and explicit indexing remain active.')]


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
        raise ValueError('Expected exact V4 manager-runtime.js; no changes.')
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
        if (set(manifest['files']) == {TARGET} and manifest['status'] in ('prepared', 'committed')
                and manifest['files'][TARGET]['after'] == PATCHED_SHA256):
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
            print(json.dumps({'changed_files': list(plan.changes()), 'patch': 'published-index search; routine maintenance not launched by retrieval'}))
        else:
            backup = plan.commit()
            print(json.dumps({'backup_id': backup, 'changed_files': list(plan.changes()), 'revert': f'python3 -B scripts/patch_search_published.py --package-dir {root} --revert'}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
