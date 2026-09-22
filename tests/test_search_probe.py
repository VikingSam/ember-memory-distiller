from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from scripts.probe_search_readonly import probe

class SearchProbeTests(unittest.TestCase):
    def test_fts_timing_and_no_content_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'private-database.sqlite'
            with sqlite3.connect(p) as db:
                db.executescript('CREATE TABLE memory_index_chunks(id TEXT); CREATE TABLE memory_index_sources(id TEXT); CREATE VIRTUAL TABLE memory_index_chunks_fts USING fts5(text);')
                db.execute('INSERT INTO memory_index_chunks_fts VALUES(?)', ('synthetic private phrase',))
                db.execute('INSERT INTO memory_index_chunks VALUES(?)', ('secret-id',))
            original=p.read_bytes()
            result=probe(p,'synthetic private phrase')
            encoded=json.dumps(result)
            self.assertNotIn('private',encoded);self.assertNotIn('secret-id',encoded)
            self.assertEqual([x['value'] for x in result['phases'] if x['phase'].startswith('fts_')],[1,1])
            self.assertEqual(original,p.read_bytes())
            self.assertEqual({x.name for x in Path(tmp).iterdir()},{p.name})

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'absent.sqlite'
            result=probe(p)
            self.assertEqual(result['phases'][0]['status'],'error')
            self.assertFalse(p.exists())

    def test_wrong_database_reports_missing_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'empty.sqlite';sqlite3.connect(p).close()
            result=probe(p)
            self.assertEqual([x['value'] for x in result['phases'] if x['phase'].endswith('_present')],[False]*3)
