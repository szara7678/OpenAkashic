"""Run an isolated synthetic WAL backup demonstration: python demo.py."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from solution import backup_database


def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "live.db"
        destination = Path(directory) / "snapshot.db"
        with closing(sqlite3.connect(source)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.executescript(
                "CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT);"
                "INSERT INTO items VALUES(1, 'committed in WAL');"
            )
            assert Path(str(source) + "-wal").stat().st_size > 0
            with closing(sqlite3.connect(source)) as reader:
                reader.execute("BEGIN")
                reader.execute("SELECT * FROM items").fetchall()
                writer.execute("INSERT INTO items VALUES(2, 'not committed')")
                backup_database(source, destination)
                with closing(sqlite3.connect(destination)) as restored:
                    rows = restored.execute("SELECT * FROM items ORDER BY id").fetchall()
                    assert rows == [(1, "committed in WAL")]
                    assert restored.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                    print("PASS: open WAL writer/reader; committed rows included; uncommitted excluded")
                    print("Restored rows:", rows)
                writer.rollback()
                assert reader.execute("SELECT count(*) FROM items").fetchone() == (1,)
        assert not Path(str(destination) + "-wal").exists()
        print("PASS: independently reopened snapshot; source remains usable")


if __name__ == "__main__":
    main()
