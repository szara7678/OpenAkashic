"""Online SQLite snapshots using only the Python standard library."""

from contextlib import closing
import errno
import os
from pathlib import Path
import sqlite3
import tempfile


def backup_database(source, destination):
    """Publish a standalone snapshot without replacing an existing destination.

    The snapshot is established by the first source read, after function entry.
    Paths must name local filesystem databases. Returns None.
    """
    source_path = Path(source).resolve()
    destination_path = Path(os.path.abspath(os.fspath(destination)))
    if os.path.lexists(destination_path):
        raise FileExistsError(errno.EEXIST, "Destination exists", str(destination_path))
    if source_path == destination_path.resolve():
        raise ValueError("Source and destination must differ")

    with tempfile.TemporaryDirectory(
        prefix=".sqlite-backup-", dir=destination_path.parent
    ) as staging_directory:
        staging_path = Path(staging_directory) / "snapshot.sqlite"
        with closing(sqlite3.connect(
            source_path.as_uri() + "?mode=ro&cache=private",
            uri=True,
            isolation_level=None,
        )) as source_connection:
            source_connection.execute("BEGIN")
            source_connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()
            with closing(sqlite3.connect(staging_path)) as destination_connection:
                source_connection.backup(destination_connection, pages=256)
                journal_mode = destination_connection.execute(
                    "PRAGMA journal_mode=DELETE"
                ).fetchone()[0]
                if journal_mode.lower() != "delete":
                    raise sqlite3.DatabaseError("Snapshot is not standalone")
        os.link(staging_path, destination_path)
