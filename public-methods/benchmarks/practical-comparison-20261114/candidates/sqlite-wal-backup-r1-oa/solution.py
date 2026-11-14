"""Consistent, no-clobber SQLite backups using the standard library."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time


def backup_database(source, destination):
    """Return a new standalone snapshot's absolute Path; never replace a file.

    Paths are local filenames, not SQLite URIs. Snapshot time is the first
    source read. See README.md for filesystem and concurrency limitations.
    """
    source_path = Path(source).absolute()
    destination_path = Path(destination).absolute()
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("source and destination must differ")
    if os.path.lexists(destination_path):
        if source_path.exists() and destination_path.exists():
            if os.path.samefile(source_path, destination_path):
                raise ValueError("source and destination refer to the same file")
        raise FileExistsError(destination_path)

    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(destination_path) + suffix)
        if os.path.lexists(sidecar):
            raise FileExistsError(sidecar)

    temporary_path = None
    deadline = time.monotonic() + 60

    def check_deadline(status, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded its 60 second budget")

    try:
        with closing(sqlite3.connect(
            source_path.as_uri() + "?mode=ro", uri=True,
            isolation_level=None, timeout=5,
        )) as source_connection:
            source_connection.execute("BEGIN")
            source_connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".sqlite-backup-", suffix=".db", dir=destination_path.parent,
            )
            temporary_path = Path(temporary_name)
            os.close(descriptor)
            with closing(sqlite3.connect(temporary_path, isolation_level=None)) as target:
                source_connection.backup(
                    target, pages=128, progress=check_deadline, sleep=0.05,
                )
                mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                if mode.lower() != "delete":
                    raise sqlite3.OperationalError("backup requires a standalone file")
            source_connection.rollback()

        with closing(sqlite3.connect(
            temporary_path.as_uri() + "?mode=ro", uri=True,
        )) as verification:
            if verification.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise sqlite3.DatabaseError("backup integrity check failed")

        os.link(temporary_path, destination_path)
        return destination_path
    finally:
        if temporary_path is not None:
            for suffix in ("-wal", "-shm", "-journal", ""):
                try:
                    Path(str(temporary_path) + suffix).unlink()
                except FileNotFoundError:
                    pass
