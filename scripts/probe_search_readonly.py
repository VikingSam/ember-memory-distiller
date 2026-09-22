#!/usr/bin/env python3
"""Direct SQLite timing baseline; no OpenClaw imports or remote API calls.

Opens only the explicitly supplied database with mode=ro. No result text,
query, path, schema contents, or exception messages are emitted. SQLite may
use existing WAL/shared-memory sidecars; immutable mode is deliberately avoided
so committed WAL data is not silently ignored. No migrations/checkpoints run.
"""
import argparse
import getpass
import json
from pathlib import Path
import sqlite3
import time


def probe(path, query=None, budget=5.0):
    report = {'probe': 'sqlite-readonly-baseline-v1', 'sqlite_version': sqlite3.sqlite_version, 'phases': []}
    db = None
    def phase(name, fn):
        started = time.monotonic()
        try:
            value = fn()
            result = {'phase': name, 'status': 'ok', 'value': value}
        except sqlite3.Error as exc:
            result = {'phase': name, 'status': 'error', 'sqlite_code': getattr(exc, 'sqlite_errorname', type(exc).__name__)}
        result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)
        report['phases'].append(result)
        return result
    def open_db():
        nonlocal db
        # No immutable=1: read the current committed WAL state.
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1.0)
        return True
    if phase('raw_connection_open', open_db)['status'] != 'ok':
        return report
    try:
        db.execute('PRAGMA query_only=ON')
        deadline = [time.monotonic() + budget]
        db.set_progress_handler(lambda: int(time.monotonic() > deadline[0]), 1000)
        def timed(name, fn):
            deadline[0] = time.monotonic() + budget
            return phase(name, fn)
        timed('schema_read', lambda: db.execute('SELECT count(*) FROM sqlite_schema').fetchone()[0])
        for name in ('memory_index_chunks', 'memory_index_sources', 'memory_index_chunks_fts'):
            existence = timed(name + '_present', lambda name=name: bool(db.execute('SELECT 1 FROM sqlite_schema WHERE name=? AND type=?', (name, 'table')).fetchone()))
            if existence.get('value') is not True:
                continue
            if name != 'memory_index_chunks_fts':
                timed(name + '_count', lambda name=name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0])
            elif query:
                # Match one literal phrase, limit to ten hits; return only hit count.
                phrase = '"' + query.replace('"', '""') + '"'
                for label in ('fts_first', 'fts_repeat'):
                    timed(label, lambda: len(db.execute('SELECT rowid FROM memory_index_chunks_fts WHERE memory_index_chunks_fts MATCH ? LIMIT 10', (phrase,)).fetchall()))
        return report
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True, help='Exact existing index database path; no auto-discovery')
    p.add_argument('--fts', action='store_true', help='Prompt locally for a familiar literal phrase; never print it')
    args = p.parse_args()
    query = getpass.getpass('Local FTS phrase (not echoed): ') if args.fts else None
    print(json.dumps(probe(args.db, query), indent=2))


if __name__ == '__main__':
    main()
