"""Create and review a standalone rehearsal backup of a quiescent database."""

import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    query = '?mode=ro' + ('&immutable=1' if immutable else '')
    connection = sqlite3.connect(path.as_uri() + query, uri=True)
    connection.text_factory = lambda raw: raw.decode('utf-8', 'surrogateescape')
    return connection


def _schema(connection: sqlite3.Connection) -> list:
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM main.sqlite_master "
        "WHERE substr(name, 1, 7) != 'sqlite_' ORDER BY type, name"
    ).fetchall()


def _rows(connection: sqlite3.Connection, table: str) -> Counter:
    quoted = _identifier(table)
    columns = connection.execute(f'PRAGMA main.table_xinfo({quoted})').fetchall()
    selection = ', '.join(_identifier(column[1]) for column in columns)
    if not selection:
        raise sqlite3.DatabaseError(f'No readable columns in {table!r}')
    return Counter(
        tuple((type(value).__name__, value) for value in row)
        for row in connection.execute(f'SELECT {selection} FROM main.{quoted}')
    )


def backup_review(source: str, target: str) -> dict:
    """Back up main, close/reopen the copy, and compare all user-table data.

    Requires quiescent writers and exclusive ownership of the target pathname
    and its sidecar names. Existing targets (including symlinks) are refused.
    SQLite/OS failures propagate; an incomplete newly created target may remain.
    """
    source_path = Path(os.path.abspath(source))
    target_path = Path(os.path.abspath(target))
    if os.path.lexists(target_path):
        raise FileExistsError(target)
    if not source_path.exists():
        raise FileNotFoundError(source)
    for suffix in ('-wal', '-shm', '-journal'):
        if os.path.lexists(str(target_path) + suffix):
            raise FileExistsError(str(target_path) + suffix)

    with closing(_connect(source_path)) as original:
        original.execute('BEGIN')
        source_schema = _schema(original)
        descriptor = os.open(target_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(target_path)) as destination:
            original.backup(destination)
            mode = destination.execute('PRAGMA main.journal_mode=DELETE').fetchone()
            if mode != ('delete',):
                raise sqlite3.DatabaseError('Could not make backup standalone')

        with closing(_connect(target_path, immutable=True)) as reopened:
            integrity_rows = reopened.execute('PRAGMA main.integrity_check').fetchall()
            violations = [list(row) for row in reopened.execute('PRAGMA main.foreign_key_check')]
            target_schema = _schema(reopened)
            matches = source_schema == target_schema
            source_tables = {row[1] for row in source_schema if row[0] == 'table'}
            target_tables = {row[1] for row in target_schema if row[0] == 'table'}
            counts = {}
            for table in sorted(source_tables | target_tables):
                source_rows = _rows(original, table) if table in source_tables else None
                target_rows = _rows(reopened, table) if table in target_tables else None
                if target_rows is not None:
                    counts[table] = sum(target_rows.values())
                if source_rows != target_rows:
                    matches = False
            return {
                'integrity_ok': bool(integrity_rows) and all(row == ('ok',) for row in integrity_rows),
                'copy_matches': matches,
                'foreign_key_violations': violations,
                'relation_valid': not violations,
                'tables': counts,
            }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('target')
    arguments = parser.parse_args()
    print(json.dumps(backup_review(arguments.source, arguments.target), indent=2))
