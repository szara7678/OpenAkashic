"""Create and independently review a quiescent SQLite database backup."""

import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3


def _quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.text_factory = lambda value: value.decode('utf-8', 'surrogateescape')
    return connection


def _schema(connection):
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM main.sqlite_master "
        "WHERE substr(name, 1, 7) != 'sqlite_' ORDER BY type, name"
    ).fetchall()


def _rows(connection, name):
    return Counter(
        tuple((type(value).__name__, value) for value in row)
        for row in connection.execute('SELECT * FROM main.' + _quote_identifier(name))
    )


def backup_review(source: str, target: str) -> dict:
    """Back up a file database; callers must keep all writers quiescent.

    Existing targets (including dangling symlinks) are never overwritten.
    SQLite and filesystem errors propagate; a failed new backup is removed.
    """
    source_path = Path(source)
    target_path = Path(target)
    if os.path.lexists(target_path):
        raise FileExistsError(str(target_path))
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))

    with closing(_readonly(source_path)) as original:
        descriptor = os.open(target_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(str(target_path.resolve()))) as destination:
                original.backup(destination)
                mode = destination.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
                if mode.lower() != 'delete':
                    raise sqlite3.OperationalError('Backup could not leave WAL mode')
            with closing(_readonly(target_path)) as restored:
                integrity = restored.execute('PRAGMA integrity_check').fetchall()
                violations = [list(row) for row in restored.execute('PRAGMA foreign_key_check')]
                original_schema = _schema(original)
                restored_schema = _schema(restored)
                tables = {}
                matches = original_schema == restored_schema
                original_tables = {row[1] for row in original_schema if row[0] == 'table'}
                restored_tables = {row[1] for row in restored_schema if row[0] == 'table'}
                for name in sorted(restored_tables):
                    restored_rows = _rows(restored, name)
                    tables[name] = sum(restored_rows.values())
                    if name not in original_tables or restored_rows != _rows(original, name):
                        matches = False
                return {
                    'integrity_ok': bool(integrity) and all(row == ('ok',) for row in integrity),
                    'copy_matches': matches,
                    'foreign_key_violations': violations,
                    'relation_valid': not violations,
                    'tables': tables,
                }
        except BaseException:
            target_path.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('target')
    arguments = parser.parse_args()
    print(json.dumps(backup_review(arguments.source, arguments.target), sort_keys=True))


if __name__ == '__main__':
    main()
