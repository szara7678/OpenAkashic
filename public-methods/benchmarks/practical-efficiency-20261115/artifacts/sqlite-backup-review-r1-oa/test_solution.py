import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from solution import _rows, backup_review


class BackupReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'source ?#.db'
        self.target = Path(self.directory.name) / 'target.db'

    def make(self, sql='CREATE TABLE items(value);'):
        with sqlite3.connect(self.source) as connection:
            connection.executescript(sql)

    def test_wal_commits_and_foreign_key_violation(self):
        with sqlite3.connect(self.source) as idle:
            self.assertEqual(idle.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            idle.executescript('''
                CREATE TABLE desks(id INTEGER PRIMARY KEY, label TEXT);
                CREATE TABLE tickets(id INTEGER PRIMARY KEY, desk_id REFERENCES desks(id));
                INSERT INTO desks VALUES(1, 'north');
                INSERT INTO tickets VALUES(5,1),(6,404);
            ''')
            idle.commit()
            before = self.source.read_bytes()
            wal_path = Path(str(self.source) + '-wal')
            wal_before = wal_path.read_bytes()
            result = backup_review(str(self.source), str(self.target))
            self.assertEqual(result, {
                'integrity_ok': True, 'copy_matches': True,
                'foreign_key_violations': [['tickets', 6, 'desks', 0]],
                'relation_valid': False, 'tables': {'desks': 1, 'tickets': 2},
            })
            self.assertEqual(before, self.source.read_bytes())
            self.assertEqual(wal_before, wal_path.read_bytes())
            isolated = self.target.with_name('isolated.db')
            shutil.copyfile(self.target, isolated)
            with sqlite3.connect(isolated) as reopened:
                self.assertEqual(reopened.execute('SELECT count(*) FROM tickets').fetchone(), (2,))
                self.assertEqual(reopened.execute('PRAGMA journal_mode').fetchone(), ('delete',))
            self.assertFalse(Path(str(self.target) + '-wal').exists())
            json.dumps(result)

    def test_schema_quoted_names_duplicates_and_types(self):
        self.make('''
            CREATE TABLE "museum "" objects"(value, payload BLOB);
            INSERT INTO "museum "" objects" VALUES(NULL, X'00ff'),(1, X''),
              (1.0, X''),('1', X''),('duplicate',NULL),('duplicate',NULL);
            CREATE INDEX "display index" ON "museum "" objects"(value);
            CREATE VIEW inventory AS SELECT * FROM "museum "" objects";
            CREATE TABLE "sqliteX_user table"(key TEXT PRIMARY KEY) WITHOUT ROWID;
            CREATE TABLE empty(value);
            CREATE TRIGGER log_insert AFTER INSERT ON empty BEGIN SELECT 1; END;
        ''')
        before = self.source.read_bytes()
        result = backup_review(str(self.source), str(self.target))
        self.assertTrue(result['copy_matches'])
        self.assertTrue(result['relation_valid'])
        self.assertEqual(result['tables'], {'museum " objects': 6, 'sqliteX_user table': 0, 'empty': 0})
        self.assertEqual(before, self.source.read_bytes())

    def test_existing_target_unchanged(self):
        self.make()
        self.target.write_bytes(b'preserve me')
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertEqual(self.target.read_bytes(), b'preserve me')
        self.assertEqual(self.source.read_bytes(), before)

    def test_missing_source_creates_nothing(self):
        with self.assertRaises(FileNotFoundError):
            backup_review(str(self.source), str(self.target))
        self.assertFalse(self.source.exists())
        self.assertFalse(self.target.exists())

    def test_same_path(self):
        self.make()
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.source))
        self.assertEqual(before, self.source.read_bytes())

    def test_dangling_target_symlink(self):
        self.make()
        missing = self.target.with_name('missing.db')
        self.target.symlink_to(missing)
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(missing.exists())

    def test_empty_database(self):
        self.source.touch()
        result = backup_review(str(self.source), str(self.target))
        self.assertEqual(result['tables'], {})
        self.assertTrue(result['copy_matches'])
        self.assertTrue(result['integrity_ok'])

    def test_bad_source_cleanup(self):
        self.source.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            backup_review(str(self.source), str(self.target))
        self.assertFalse(self.target.exists())
        self.assertEqual(self.source.read_bytes(), b'not a database')

    def test_rows_are_type_sensitive_multisets(self):
        with sqlite3.connect(':memory:') as connection:
            connection.executescript('CREATE TABLE a(x); CREATE TABLE b(x); '
                                     'INSERT INTO a VALUES(1),(1); INSERT INTO b VALUES(1.0);')
            self.assertNotEqual(_rows(connection, 'a'), _rows(connection, 'b'))
            connection.execute('DELETE FROM a')
            connection.execute('INSERT INTO a VALUES(1)')
            self.assertNotEqual(_rows(connection, 'a'), _rows(connection, 'b'))


if __name__ == '__main__':
    unittest.main()
