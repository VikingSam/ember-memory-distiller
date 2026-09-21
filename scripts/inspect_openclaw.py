#!/usr/bin/env python3
"""Read-only package inspection: never opens memory, config, logs or databases."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from patch_openclaw import OLD, NEW, TARGET

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--package-dir', type=Path, required=True)
a = p.parse_args()
root = a.package_dir.resolve()
package = json.loads((root / 'package.json').read_text())
report = {'package': package.get('name'), 'version': package.get('version'), 'files': []}
for pattern in ('dist/session-accessor.sqlite-entry-*.js', 'dist/extensions/memory-core/manager-runtime.js'):
    for path in sorted(root.glob(pattern)):
        data = path.read_bytes()
        text = data.decode()
        report['files'].append({
            'file': str(path.relative_to(root)),
            'sha256': hashlib.sha256(data).hexdigest(),
            'exact_patch_target': str(path.relative_to(root)) == TARGET,
            'original_archive_function_matches': OLD in text,
            'patched_archive_function_matches': NEW in text,
            'cache_batch_400_present': 'const batchSize = 400;' in text,
        })
print(json.dumps(report, indent=2))
