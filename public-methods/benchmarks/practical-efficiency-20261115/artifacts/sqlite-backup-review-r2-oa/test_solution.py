from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from solution import backup_review, _rows, _schema


class BackupReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'source ?#.db'
        self.target = Path(self.directory.name) / 'target ?#.db'

    def create(self, sql='CREATE TABLE records(value);'):
        with closing(sqlite3.connect(self.source)) as connection:
            connection.executescript(sql)
            connection.commit()

    def test_missing_source_creates_neither(self):
        with self.assertRaises(FileNotFoundError):
            backup_review(str(self.source), str(self.target))
        self.assertFalse(self.source.exists())
        self.assertFalse(self.target.exists())

    def test_existing_target_preserved(self):
        self.create()
        self.target.write_bytes(b'not a database')
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertEqual(self.target.read_bytes(), b'not a database')
        self.assertEqual(self.source.read_bytes(), before)

    def test_dangling_target_symlink_preserved(self):
        self.create()
        missing = self.target.with_name('absent')
        self.target.symlink_to(missing)
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(missing.exists())

    def test_source_as_target(self):
        self.create()
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.source))
        self.assertEqual(self.source.read_bytes(), before)

    def test_empty_database(self):
        self.create('')
        self.assertEqual(backup_review(str(self.source), str(self.target)), {
            'integrity_ok': True, 'copy_matches': True,
            'foreign_key_violations': [], 'relation_valid': True, 'tables': {}})

    def test_quoted_names_full_rows_and_schema(self):
        self.create('''
            CREATE TABLE "art "" works"(value, payload BLOB);
            INSERT INTO "art "" works" VALUES(NULL, x'0001'),('é', x'FF'),
                ('duplicate', NULL),('duplicate', NULL),(1,NULL),(1.0,NULL);
            CREATE TABLE sqlitex_user(value);
            CREATE TABLE empty(value);
            CREATE TABLE keyed(id TEXT PRIMARY KEY, value) WITHOUT ROWID;
            INSERT INTO keyed VALUES('a',42);
            CREATE INDEX "index with spaces" ON "art "" works"(value);
            CREATE VIEW "catalog view" AS SELECT * FROM keyed;
            CREATE TRIGGER "catalog trigger" AFTER INSERT ON keyed
                BEGIN INSERT INTO empty VALUES(new.value); END;
        ''')
        before = self.source.read_bytes()
        result = backup_review(str(self.source), str(self.target))
        self.assertTrue(result['integrity_ok'])
        self.assertTrue(result['copy_matches'])
        self.assertTrue(result['relation_valid'])
        self.assertEqual(result['tables'], {'art " works': 6, 'sqlitex_user': 0,
                                           'empty': 0, 'keyed': 1})
        json.dumps(result)
        self.assertEqual(self.source.read_bytes(), before)
        with closing(sqlite3.connect(self.source)) as original:
            with closing(sqlite3.connect(self.target)) as restored:
                self.assertEqual(_schema(original), _schema(restored))
                self.assertEqual(_rows(original, 'art " works'), _rows(restored, 'art " works'))

    def test_inherited_fk_violations_including_without_rowid(self):
        self.create('''
            PRAGMA foreign_keys=OFF;
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id REFERENCES parent(id));
            INSERT INTO child VALUES(7,404);
            CREATE TABLE "child no rowid"(id TEXT PRIMARY KEY,
                parent_id REFERENCES parent(id)) WITHOUT ROWID;
            INSERT INTO "child no rowid" VALUES('x',405);
        ''')
        result = backup_review(str(self.source), str(self.target))
        self.assertTrue(result['integrity_ok'])
        self.assertTrue(result['copy_matches'])
        self.assertFalse(result['relation_valid'])
        self.assertCountEqual(result['foreign_key_violations'],
                              [['child', 7, 'parent', 0], ['child no rowid', None, 'parent', 0]])

    def test_live_wal_is_included_and_target_is_standalone(self):
        with closing(sqlite3.connect(self.source)) as keeper:
            keeper.execute('PRAGMA journal_mode=WAL')
            keeper.execute('PRAGMA wal_autocheckpoint=0')
            keeper.execute('CREATE TABLE records(value)')
            keeper.executemany('INSERT INTO records VALUES(?)', [(1,), (2,), (2,)])
            keeper.commit()
            source_before = self.source.read_bytes()
            wal = Path(str(self.source) + '-wal')
            wal_before = wal.read_bytes()
            self.assertGreater(len(wal_before), 0)
            result = backup_review(str(self.source), str(self.target))
            self.assertTrue(result['copy_matches'])
            self.assertEqual(result['tables'], {'records': 3})
            self.assertEqual(self.source.read_bytes(), source_before)
            self.assertEqual(wal.read_bytes(), wal_before)
            self.assertFalse(Path(str(self.target) + '-wal').exists())
            isolated = self.target.with_name('isolated.db')
            shutil.copyfile(self.target, isolated)
            with closing(sqlite3.connect(isolated)) as restored:
                self.assertEqual(restored.execute('SELECT value FROM records').fetchall(),
                                 [(1,), (2,), (2,)])
                self.assertEqual(restored.execute('PRAGMA journal_mode').fetchone(), ('delete',))

    def test_row_comparison_counts_duplicates_and_storage_types(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.executescript('CREATE TABLE a(value); CREATE TABLE b(value);'
                                     'INSERT INTO a VALUES(1),(1),(1.0);'
                                     'INSERT INTO b VALUES(1),(1.0),(1.0);')
            self.assertNotEqual(_rows(connection, 'a'), _rows(connection, 'b'))


if __name__ == '__main__':
    unittest.main()
