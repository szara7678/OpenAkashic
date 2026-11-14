"""Local demonstration: committed WAL data, with a writer still open."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile

from solution import backup_database


def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "service.sqlite"
        snapshot = Path(directory) / "snapshot.sqlite"
        with closing(sqlite3.connect(source)) as service:
            service.execute("PRAGMA journal_mode=WAL")
            service.execute("PRAGMA wal_autocheckpoint=0")
            service.execute("CREATE TABLE messages(body TEXT)")
            service.execute("INSERT INTO messages VALUES ('committed in WAL')")
            service.commit()
            with closing(sqlite3.connect(source)) as pending:
                pending.execute("INSERT INTO messages VALUES ('not committed')")
                backup_database(source, snapshot)
                with closing(sqlite3.connect(snapshot)) as restored:
                    rows = restored.execute("SELECT body FROM messages").fetchall()
                    assert rows == [("committed in WAL",)]
                    assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    print("Snapshot while writer is open:", rows)
                pending.rollback()
        print("PASS: committed WAL data included; uncommitted data excluded")


if __name__ == "__main__":
    main()
