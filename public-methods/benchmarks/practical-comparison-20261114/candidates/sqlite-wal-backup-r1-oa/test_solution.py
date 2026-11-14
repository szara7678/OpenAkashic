from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from solution import backup_database


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'live #?.db'
        self.destination = self.root / 'backup #?.db'
        self.writer = sqlite3.connect(self.source)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('PRAGMA wal_autocheckpoint=0')
        self.writer.executescript(
            'CREATE TABLE parents(id INTEGER PRIMARY KEY);'
            'CREATE TABLE items(id INTEGER PRIMARY KEY, parent INTEGER REFERENCES parents(id), value BLOB);'
            'INSERT INTO parents VALUES(1);'
        )
        self.writer.executemany('INSERT INTO items VALUES(?, 1, ?)',
                                [(number, bytes(2000)) for number in range(500)])
        self.writer.commit()

    def assert_clean(self):
        self.assertFalse(list(self.root.glob('.sqlite-backup-*')))

    def test_wal_schema_rows_integrity_foreign_keys_and_standalone(self):
        before = self.source.read_bytes()
        wal_before = Path(str(self.source) + '-wal').read_bytes()
        self.writer.execute("INSERT INTO items VALUES(999, 1, 'uncommitted')")
        backup_database(self.source, self.destination)
        self.writer.rollback()
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(Path(str(self.source) + '-wal').read_bytes(), wal_before)
        detached = self.root / 'detached.db'
        shutil.copyfile(self.destination, detached)
        with closing(sqlite3.connect(detached)) as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ('parents', 'items'):
                query = 'SELECT * FROM ' + table + ' ORDER BY id'
                self.assertEqual(restored.execute(query).fetchall(), self.writer.execute(query).fetchall())
            query = "SELECT name, sql FROM sqlite_schema WHERE type='table' ORDER BY name"
            self.assertEqual(restored.execute(query).fetchall(), self.writer.execute(query).fetchall())
        self.assert_clean()

    def test_existing_preserved(self):
        self.destination.write_bytes(b'untouched')
        with self.assertRaises(FileExistsError):
            backup_database(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'untouched')

    def test_same_and_aliases_preserved(self):
        aliases = [self.source, self.root / 'symlink.db', self.root / 'hardlink.db']
        aliases[1].symlink_to(self.source)
        os.link(self.source, aliases[2])
        for alias in aliases:
            with self.assertRaises(ValueError):
                backup_database(self.source, alias)
        self.assertEqual(self.writer.execute('SELECT count(*) FROM items').fetchone(), (500,))

    def test_dangling_destination_preserved(self):
        self.destination.symlink_to(self.root / 'absent')
        with self.assertRaises(FileExistsError):
            backup_database(self.source, self.destination)
        self.assertTrue(self.destination.is_symlink())

    def test_existing_destination_sidecar_preserved(self):
        sidecar = Path(str(self.destination) + '-wal')
        sidecar.write_bytes(b'old WAL must not be paired with new snapshot')
        with self.assertRaises(FileExistsError):
            backup_database(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(sidecar.read_bytes(), b'old WAL must not be paired with new snapshot')
        self.assert_clean()

    def test_missing_source_not_created(self):
        missing = self.root / 'absent.db'
        with self.assertRaises(sqlite3.OperationalError):
            backup_database(missing, self.destination)
        self.assertFalse(missing.exists())
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_corrupt_source_cleanup(self):
        bad = self.root / 'bad.db'
        bad.write_bytes(b'not sqlite' * 100)
        with self.assertRaises(sqlite3.DatabaseError):
            backup_database(bad, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_publication_failure_cleanup(self):
        with patch('solution.os.link', side_effect=OSError('injected publication failure')):
            with self.assertRaises(OSError):
                backup_database(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_destination_race_preserves_winner(self):
        def competitor(temporary, destination):
            Path(destination).write_bytes(b'competitor')
            raise FileExistsError(destination)
        with patch('solution.os.link', side_effect=competitor):
            with self.assertRaises(FileExistsError):
                backup_database(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'competitor')
        self.assert_clean()

    def test_mid_backup_failure_cleanup(self):
        original_connect = sqlite3.connect
        class FailingConnection(sqlite3.Connection):
            def backup(self, target, **options):
                def fail(status, remaining, total):
                    raise RuntimeError('injected after backup step')
                return super().backup(target, pages=1, progress=fail)
        def connect(*args, **kwargs):
            if kwargs.get('uri'):
                kwargs['factory'] = FailingConnection
            return original_connect(*args, **kwargs)
        with patch('solution.sqlite3.connect', side_effect=connect):
            with self.assertRaises(RuntimeError):
                backup_database(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_clean()

    def test_writer_commits_during_backup_pinned_snapshot(self):
        started = threading.Event()
        committed = threading.Event()
        errors = []
        def write():
            try:
                if not started.wait(5):
                    raise TimeoutError('backup did not start')
                with closing(sqlite3.connect(self.source)) as connection:
                    connection.execute("INSERT INTO items VALUES(1000, 1, 'later')")
                    connection.commit()
            except BaseException as error:
                errors.append(error)
            finally:
                committed.set()
        thread = threading.Thread(target=write)
        original_connect = sqlite3.connect
        class CoordinatedConnection(sqlite3.Connection):
            def backup(self, target, **options):
                def progress(status, remaining, total):
                    if not started.is_set():
                        started.set()
                        if not committed.wait(5):
                            raise TimeoutError('writer blocked')
                return super().backup(target, pages=1, progress=progress)
        def connect(*args, **kwargs):
            if kwargs.get('uri'):
                kwargs['factory'] = CoordinatedConnection
            return original_connect(*args, **kwargs)
        thread.start()
        try:
            with patch('solution.sqlite3.connect', side_effect=connect):
                backup_database(self.source, self.destination)
        finally:
            started.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.writer.execute('SELECT count(*) FROM items').fetchone(), (501,))
        with closing(sqlite3.connect(self.destination)) as restored:
            self.assertEqual(restored.execute('SELECT count(*) FROM items').fetchone(), (500,))
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
