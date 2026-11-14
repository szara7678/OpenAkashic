"""Create and independently review a quiescent, local SQLite backup."""

import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import struct


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _connect(path, mode):
    return sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True)


def _schema(connection):
    return connection.execute(
        'SELECT type, name, tbl_name, sql FROM main.sqlite_master '
        'ORDER BY type, name'
    ).fetchall()


def _tables(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM main.sqlite_master WHERE type='table' "
        "AND name NOT GLOB 'sqlite_*' ORDER BY name"
    )]


def _rows(connection, table):
    def typed(value):
        if isinstance(value, float):
            return ('float', struct.pack('!d', value))
        return (type(value).__name__, value)

    return Counter(
        tuple(typed(value) for value in row)
        for row in connection.execute('SELECT * FROM main.' + _identifier(table))
    )


def backup_review(source: str, target: str) -> dict:
    """Back up main and review it; writers must remain quiescent throughout.

    Existing target paths (including dangling symlinks) are never overwritten.
    Database/IO errors propagate. A newly created partial target may remain on
    failure, for diagnosis; no existing target is removed or modified.
    """
    source_path = Path(os.path.abspath(source))
    target_path = Path(os.path.abspath(target))
    if os.path.lexists(target_path):
        raise FileExistsError(str(target_path))
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))
    for suffix in ('-wal', '-shm', '-journal'):
        if os.path.lexists(str(target_path) + suffix):
            raise FileExistsError(str(target_path) + suffix)

    with closing(_connect(source_path, 'ro')) as original:
        original.execute('BEGIN')
        original_schema = _schema(original)
        source_tables = _tables(original)
        with open(target_path, 'xb'):
            pass
        with closing(_connect(target_path, 'rw')) as destination:
            original.backup(destination)
            mode = destination.execute('PRAGMA journal_mode=DELETE').fetchone()
            if mode != ('delete',):
                raise sqlite3.OperationalError('Cannot make backup self-contained')

        with closing(_connect(target_path, 'ro')) as reviewed:
            integrity = reviewed.execute('PRAGMA integrity_check').fetchall()
            violations = [list(row) for row in reviewed.execute(
                'PRAGMA foreign_key_check'
            )]
            target_tables = _tables(reviewed)
            matches = original_schema == _schema(reviewed)
            matches = matches and source_tables == target_tables
            counts = {}
            for table in target_tables:
                copied_rows = _rows(reviewed, table)
                counts[table] = sum(copied_rows.values())
                if table not in source_tables or copied_rows != _rows(original, table):
                    matches = False
            return {
                'integrity_ok': bool(integrity) and all(
                    row == ('ok',) for row in integrity
                ),
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
