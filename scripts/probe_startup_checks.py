#!/usr/bin/env python3
"""Time startup PRAGMAs read-only; emit no paths, row contents, or errors' text.

Each check has a 20-second SQLite progress deadline, not a hard I/O timeout.
No OpenClaw imports, extension loads, network calls, repairs, or checkpoints.
SQLite can use WAL/shared-memory sidecars. Run separately from indexing.
"""
import json
from pathlib import Path
import sqlite3
import sys
import time


def probe(path, budget=20.0):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.execute('PRAGMA query_only=ON')
        for name in ('integrity_check', 'foreign_key_check'):
            started = time.monotonic()
            deadline = started + budget
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            print(json.dumps({'phase': name, 'event': 'started'}), flush=True)
            result = {'phase': name, 'sqlite_version': sqlite3.sqlite_version}
            try:
                rows = db.execute('PRAGMA ' + name)
                count, healthy = 0, True
                for row in rows:
                    count += 1
                    healthy = healthy and row == ('ok',)
                result['status'] = 'ok'
                result['healthy'] = (count == 1 and healthy) if name == 'integrity_check' else count == 0
            except sqlite3.Error as exc:
                code = getattr(exc, 'sqlite_errorname', 'SQLITE_ERROR')
                result.update(status='budget_exceeded' if code == 'SQLITE_INTERRUPT' else 'error', sqlite_code=code)
            result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
            print(json.dumps(result), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('one database argument required')
        probe(sys.argv[1])
    except Exception:
        print('{"status":"probe_failed","details":"suppressed"}')
        sys.exit(1)
