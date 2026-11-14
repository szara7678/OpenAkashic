import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from solution import backup_review, _rows


class BackupReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'museum ?# source.db'
        self.target = self.root / 'review ?# target.db'

    def connect(self):
        connection = sqlite3.connect(self.source)
        self.addCleanup(connection.close)
        return connection

    def review(self):
        result = backup_review(str(self.source), str(self.target))
        json.dumps(result, allow_nan=False)
        self.assertTrue(result['copy_matches'])
        return result

    def test_wal_foreign_keys_and_standalone(self):
        connection = self.connect()
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.executescript('''
            CREATE TABLE parent(id INTEGER PRIMARY KEY);
            CREATE TABLE "catalog items"(id INTEGER PRIMARY KEY,
                parent_id REFERENCES parent(id), title TEXT, image BLOB);
            CREATE TABLE "odd""; DROP TABLE parent;--"(value);
            CREATE TABLE sqliteXmuseum(value);
            CREATE TABLE empty(value);
            CREATE TABLE "no rowid"(id TEXT PRIMARY KEY,
                parent_id REFERENCES parent(id)) WITHOUT ROWID;
            CREATE INDEX titles ON "catalog items"(title);
            CREATE VIEW titles_view AS SELECT title FROM "catalog items";
            CREATE TRIGGER keep_empty AFTER INSERT ON parent
                BEGIN INSERT INTO empty VALUES (new.id); END;
            INSERT INTO parent VALUES(1);
            INSERT INTO "catalog items" VALUES(1,1,'valid',X'00ff');
            INSERT INTO "catalog items" VALUES(2,99,'orphan',NULL);
            INSERT INTO "no rowid" VALUES('lost',99);
            INSERT INTO "odd""; DROP TABLE parent;--" VALUES(NULL),(1),(1),(1.0),('1'),(X'31');
            INSERT INTO sqliteXmuseum VALUES('included');
        ''')
        connection.commit()
        before = self.source.read_bytes()
        wal_path = Path(str(self.source) + '-wal')
        wal_before = wal_path.read_bytes()
        result = self.review()
        self.assertTrue(result['integrity_ok'])
        self.assertFalse(result['relation_valid'])
        self.assertCountEqual(result['foreign_key_violations'], [
            ['catalog items', 2, 'parent', 0], ['no rowid', None, 'parent', 0]
        ])
        self.assertEqual(result['tables'], {
            'parent': 1, 'catalog items': 2, 'no rowid': 1,
            'odd"; DROP TABLE parent;--': 6, 'sqliteXmuseum': 1, 'empty': 1
        })
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(wal_before, wal_path.read_bytes())
        self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone(), ('wal',))
        for suffix in ('-wal', '-shm', '-journal'):
            self.assertFalse(Path(str(self.target) + suffix).exists())
        isolated = self.root / 'isolated'
        isolated.mkdir()
        standalone = isolated / 'only.db'
        shutil.copyfile(self.target, standalone)
        with sqlite3.connect(standalone) as reopened:
            self.assertEqual(reopened.execute('SELECT count(*) FROM "catalog items"').fetchone(), (2,))
            self.assertEqual(reopened.execute('PRAGMA integrity_check').fetchall(), [('ok',)])

    def test_empty_database(self):
        self.connect().execute('PRAGMA user_version=3')
        self.assertEqual(self.review(), {
            'integrity_ok': True, 'copy_matches': True,
            'foreign_key_violations': [], 'relation_valid': True, 'tables': {}
        })

    def test_missing_source_creates_nothing(self):
        with self.assertRaises(FileNotFoundError):
            backup_review(str(self.source), str(self.target))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_target_preserved_even_if_source_missing(self):
        self.target.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertEqual(self.target.read_bytes(), b'keep me')
        self.assertFalse(self.source.exists())

    def test_same_source_target(self):
        self.connect().execute('CREATE TABLE item(value)')
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.source))
        self.assertEqual(before, self.source.read_bytes())

    def test_dangling_target_symlink(self):
        self.target.symlink_to(self.root / 'absent')
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertTrue(self.target.is_symlink())
        self.assertFalse((self.root / 'absent').exists())

    def test_existing_target_sidecar_preserved(self):
        self.connect().execute('CREATE TABLE item(value)')
        sidecar = Path(str(self.target) + '-wal')
        sidecar.write_bytes(b'keep sidecar')
        with self.assertRaises(FileExistsError):
            backup_review(str(self.source), str(self.target))
        self.assertFalse(self.target.exists())
        self.assertEqual(sidecar.read_bytes(), b'keep sidecar')

    def test_generated_columns_and_duplicate_rows(self):
        connection = self.connect()
        connection.executescript('''
            CREATE TABLE objects(value, derived GENERATED ALWAYS AS (value * 2));
            INSERT INTO objects(value) VALUES(3),(3),(NULL);
            CREATE TABLE empty_table(value);
        ''')
        result = self.review()
        self.assertEqual(result['tables'], {'objects': 3, 'empty_table': 0})
        self.assertTrue(result['relation_valid'])

    def test_row_comparison_is_typed_and_duplicate_preserving(self):
        connection = self.connect()
        connection.executescript('''
            CREATE TABLE first(value); CREATE TABLE second(value);
            INSERT INTO first VALUES(1),(1),(NULL);
            INSERT INTO second VALUES(1),(1.0),(NULL);
        ''')
        self.assertNotEqual(_rows(connection, 'first'), _rows(connection, 'second'))
        connection.execute('UPDATE second SET value=1 WHERE typeof(value)="real"')
        self.assertEqual(_rows(connection, 'first'), _rows(connection, 'second'))
        connection.execute('DELETE FROM second WHERE rowid=1')
        self.assertNotEqual(_rows(connection, 'first'), _rows(connection, 'second'))

    def test_changed_backup_is_detected_after_close(self):
        connection = self.connect()
        connection.executescript('CREATE TABLE item(value); INSERT INTO item VALUES(1);')
        import solution
        real_connect = solution._connect

        def tamper_then_reopen(path, mode):
            if path == self.target and mode == 'ro':
                with sqlite3.connect(path) as tampered:
                    tampered.execute('UPDATE item SET value=2')
            return real_connect(path, mode)

        with patch('solution._connect', side_effect=tamper_then_reopen):
            result = backup_review(str(self.source), str(self.target))
        self.assertTrue(result['integrity_ok'])
        self.assertFalse(result['copy_matches'])


if __name__ == '__main__':
    unittest.main()
