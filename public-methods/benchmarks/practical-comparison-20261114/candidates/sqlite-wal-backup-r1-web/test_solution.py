from contextlib import closing
from pathlib import Path
import os
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
        self.source = self.root / "source #?.sqlite"
        self.destination = self.root / "backup.sqlite"
        self.service = sqlite3.connect(self.source)
        self.addCleanup(self.service.close)
        self.service.execute("PRAGMA journal_mode=WAL")
        self.service.execute("PRAGMA wal_autocheckpoint=0")
        self.service.execute("CREATE TABLE records(value INTEGER, payload BLOB)")
        self.service.execute("INSERT INTO records VALUES (1, zeroblob(4096))")
        self.service.commit()

    def assert_clean(self):
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob(".sqlite-backup-*")))

    def test_wal_committed_uncommitted_and_independent(self):
        self.assertGreater(Path(str(self.source) + "-wal").stat().st_size, 0)
        self.service.execute("INSERT INTO records VALUES (2, NULL)")
        backup_database(self.source, self.destination)
        self.service.rollback()
        moved = self.root / "isolated"
        moved.mkdir()
        isolated = moved / "only.sqlite"
        self.destination.rename(isolated)
        with closing(sqlite3.connect(isolated)) as restored:
            self.assertEqual(restored.execute("SELECT value FROM records").fetchall(), [(1,)])
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(restored.execute("PRAGMA journal_mode").fetchone(), ("delete",))
        self.assertEqual(list(moved.iterdir()), [isolated])
        self.assertEqual(self.service.execute("SELECT value FROM records").fetchall(), [(1,)])

    def test_existing_same_and_alias_paths(self):
        self.destination.write_bytes(b"keep me")
        for destination in (self.destination, self.source):
            with self.assertRaises(FileExistsError):
                backup_database(self.source, destination)
        self.assertEqual(self.destination.read_bytes(), b"keep me")
        alias = self.root / "alias"
        alias.symlink_to(self.source)
        with self.assertRaises(FileExistsError):
            backup_database(self.source, alias)
        self.assertEqual(self.service.execute("SELECT count(*) FROM records").fetchone(), (1,))

    def test_dangling_destination_symlink(self):
        self.destination.symlink_to(self.root / "absent")
        with self.assertRaises(FileExistsError):
            backup_database(self.source, self.destination)
        self.assertTrue(self.destination.is_symlink())

    def test_same_missing_path(self):
        missing = self.root / "missing"
        with self.assertRaises(ValueError):
            backup_database(missing, missing)
        self.assertFalse(missing.exists())

    def test_missing_source_not_created(self):
        missing = self.root / "missing"
        with self.assertRaises(sqlite3.OperationalError):
            backup_database(missing, self.destination)
        self.assertFalse(missing.exists())
        self.assert_clean()

    def test_invalid_source_cleanup(self):
        invalid = self.root / "invalid"
        invalid.write_bytes(b"not a database" * 100)
        with self.assertRaises(sqlite3.DatabaseError):
            backup_database(invalid, self.destination)
        self.assert_clean()

    def test_partial_copy_failure_cleanup(self):
        real_connect = sqlite3.connect

        class InterruptedConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                target.execute("CREATE TABLE partial(value)")
                target.commit()
                raise OSError("injected copy failure")

        def connect(database, *args, **kwargs):
            if kwargs.get("uri"):
                kwargs["factory"] = InterruptedConnection
            return real_connect(database, *args, **kwargs)

        with patch("solution.sqlite3.connect", side_effect=connect):
            with self.assertRaisesRegex(OSError, "injected"):
                backup_database(self.source, self.destination)
        self.assert_clean()

    def test_publication_failure_cleanup(self):
        with patch("solution.os.link", side_effect=OSError("injected publication failure")):
            with self.assertRaises(OSError):
                backup_database(self.source, self.destination)
        self.assert_clean()

    def test_racing_destination_preserved(self):
        real_link = os.link

        def racing_link(source, destination):
            Path(destination).write_bytes(b"race winner")
            real_link(source, destination)

        with patch("solution.os.link", side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                backup_database(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"race winner")
        self.assertFalse(list(self.root.glob(".sqlite-backup-*")))

    def test_concurrent_commit_does_not_change_pinned_snapshot(self):
        self.service.executemany(
            "INSERT INTO records VALUES (?, zeroblob(4096))",
            [(value,) for value in range(2, 700)],
        )
        self.service.commit()
        copy_started = threading.Event()
        writer_finished = threading.Event()
        errors = []
        real_connect = sqlite3.connect

        def writer():
            try:
                if not copy_started.wait(5):
                    raise TimeoutError("backup did not start")
                with closing(real_connect(self.source)) as connection:
                    connection.execute("DELETE FROM records")
                    connection.execute("INSERT INTO records VALUES (9999, NULL)")
                    connection.commit()
            except BaseException as error:
                errors.append(error)
            finally:
                writer_finished.set()

        class ObservedConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                def progress(status, remaining, total):
                    if not copy_started.is_set():
                        copy_started.set()
                        if not writer_finished.wait(5):
                            raise TimeoutError("writer blocked by backup")

                return super().backup(target, progress=progress, **kwargs)

        def connect(database, *args, **kwargs):
            if kwargs.get("uri"):
                kwargs["factory"] = ObservedConnection
            return real_connect(database, *args, **kwargs)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            with patch("solution.sqlite3.connect", side_effect=connect):
                backup_database(self.source, self.destination)
        finally:
            thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        with closing(real_connect(self.destination)) as restored:
            self.assertEqual(restored.execute("SELECT count(*), max(value) FROM records").fetchone(), (699, 699))
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone(), ("ok",))
        self.assertEqual(self.service.execute("SELECT value FROM records").fetchall(), [(9999,)])


if __name__ == "__main__":
    unittest.main()
