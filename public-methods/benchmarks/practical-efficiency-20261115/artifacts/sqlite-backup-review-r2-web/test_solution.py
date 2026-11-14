import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import solution


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'source ?#.db'
        self.target = self.root / 'target ?#.db'

    def connect(self):
        connection = sqlite3.connect(self.source)
        self.addCleanup(connection.close)
        return connection

    def review(self):
        result = solution.backup_review(str(self.source), str(self.target))
        json.dumps(result, allow_nan=False)
        return result

    def test_wal_quoted_names_and_inherited_violations(self):
        keeper = self.connect()
        keeper.execute('PRAGMA journal_mode=WAL')
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        keeper.executescript('''
            CREATE TABLE "museum rooms" (id INTEGER PRIMARY KEY, label TEXT);
            CREATE TABLE "a""rt; DROP TABLE x;--" (
                id INTEGER PRIMARY KEY, room REFERENCES "museum rooms"(id), payload BLOB);
            CREATE TABLE empty_table (value);
            CREATE INDEX room_index ON "a""rt; DROP TABLE x;--"(room);
            CREATE VIEW room_view AS SELECT * FROM "museum rooms";
            CREATE TRIGGER room_trigger AFTER UPDATE ON "museum rooms" BEGIN SELECT 1; END;
            INSERT INTO "museum rooms" VALUES (1, 'north');
            INSERT INTO "a""rt; DROP TABLE x;--" VALUES (3, 1, X'00FF'), (4, 404, NULL);
        ''')
        wal = Path(str(self.source) + '-wal')
        self.assertGreater(wal.stat().st_size, 0)
        before = (self.source.read_bytes(), wal.read_bytes())
        result = self.review()
        self.assertTrue(result['integrity_ok'])
        self.assertTrue(result['copy_matches'])
        self.assertFalse(result['relation_valid'])
        self.assertEqual(result['foreign_key_violations'], [
            ['a"rt; DROP TABLE x;--', 4, 'museum rooms', 0]])
        self.assertEqual(result['tables'], {
            'museum rooms': 1, 'a"rt; DROP TABLE x;--': 2, 'empty_table': 0})
        self.assertEqual(before, (self.source.read_bytes(), wal.read_bytes()))
        for suffix in ('-wal', '-shm', '-journal'):
            self.assertFalse(Path(str(self.target) + suffix).exists())
        moved = self.root / 'isolated' / 'alone.db'
        moved.parent.mkdir()
        shutil.copyfile(self.target, moved)
        with sqlite3.connect(moved) as alone:
            self.assertEqual(alone.execute('SELECT * FROM "museum rooms"').fetchall(), [(1, 'north')])
            self.assertEqual(alone.execute('PRAGMA journal_mode').fetchone(), ('delete',))

    def test_missing_source_creates_neither(self):
        with self.assertRaises(FileNotFoundError):
            self.review()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_target_preserved_even_when_source_missing(self):
        self.target.write_bytes(b'untouched target')
        with self.assertRaises(FileExistsError):
            self.review()
        self.assertEqual(self.target.read_bytes(), b'untouched target')
        self.assertFalse(self.source.exists())

    def test_dangling_target_symlink(self):
        self.target.symlink_to(self.root / 'absent')
        with self.assertRaises(FileExistsError):
            self.review()
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(self.source.exists())

    def test_same_path(self):
        connection = self.connect()
        connection.execute('CREATE TABLE kept(value)')
        connection.commit()
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            solution.backup_review(str(self.source), str(self.source))
        self.assertEqual(self.source.read_bytes(), before)

    def test_duplicates_types_generated_and_without_rowid(self):
        connection = self.connect()
        connection.executescript('''
            CREATE TABLE values_table (value);
            INSERT INTO values_table VALUES (1), (1.0), ('1'), (X'31'), (NULL), (1),
                (CAST(X'FF' AS TEXT));
            CREATE TABLE generated (value INTEGER, doubled INTEGER AS (value * 2));
            INSERT INTO generated(value) VALUES (7);
            CREATE TABLE parents (id INTEGER PRIMARY KEY);
            CREATE TABLE child (key TEXT PRIMARY KEY, parent REFERENCES parents(id)) WITHOUT ROWID;
            INSERT INTO child VALUES ('orphan', 9);
            CREATE TABLE sqliteXuser(value);
        ''')
        result = self.review()
        self.assertTrue(result['copy_matches'])
        self.assertTrue(result['integrity_ok'])
        self.assertEqual(result['tables']['values_table'], 7)
        self.assertIn('sqliteXuser', result['tables'])
        self.assertEqual(result['foreign_key_violations'], [['child', None, 'parents', 0]])
        self.assertFalse(result['relation_valid'])

    def test_empty_database(self):
        connection = self.connect()
        connection.execute('PRAGMA user_version=1')
        result = self.review()
        self.assertEqual(result, dict(integrity_ok=True, copy_matches=True,
                                     foreign_key_violations=[], relation_valid=True, tables={}))

    def test_data_comparison_detects_same_count_mutation(self):
        connection = self.connect()
        connection.executescript('CREATE TABLE records(value); INSERT INTO records VALUES(1), (1);')
        actual_connect = solution._connect

        def changed_connect(path, *, immutable=False):
            if immutable:
                with sqlite3.connect(path) as altered:
                    altered.execute('UPDATE records SET value=2 WHERE rowid=1')
            return actual_connect(path, immutable=immutable)

        with patch.object(solution, '_connect', side_effect=changed_connect):
            result = self.review()
        self.assertFalse(result['copy_matches'])
        self.assertTrue(result['integrity_ok'])
        self.assertEqual(result['tables'], {'records': 2})

    def test_preexisting_sidecar_preserved(self):
        self.connect().execute('CREATE TABLE records(value)')
        sidecar = Path(str(self.target) + '-wal')
        sidecar.write_bytes(b'not ours')
        with self.assertRaises(FileExistsError):
            self.review()
        self.assertEqual(sidecar.read_bytes(), b'not ours')
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
