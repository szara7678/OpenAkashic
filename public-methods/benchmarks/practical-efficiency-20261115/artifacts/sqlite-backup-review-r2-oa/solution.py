"""Create and independently review a SQLite backup of a quiescent source."""

from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys


def _quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _connect(path, mode):
    return sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True)


def _schema(connection):
    return sorted(
        row for row in connection.execute(
            'SELECT type, name, tbl_name, sql FROM main.sqlite_master'
        ) if not row[1].lower().startswith('sqlite_')
    )


def _rows(connection, table):
    return Counter(
        tuple((type(value).__name__, value) for value in row)
        for row in connection.execute('SELECT * FROM main.' + _quote_identifier(table))
    )


def backup_review(source: str, target: str) -> dict:
    """Back up a quiescent database without repairing inherited FK violations.

    Paths are filesystem paths, not SQLite URIs. The target must not exist.
    SQLite errors propagate; a target created before such an error may remain.
    """
    source_path = Path(source).absolute()
    target_path = Path(target).absolute()
    if os.path.lexists(target_path):
        raise FileExistsError(str(target_path))
    source_path.stat()

    with closing(_connect(source_path, 'ro')) as original:
        with target_path.open('xb'):
            pass
        with closing(_connect(target_path, 'rw')) as destination:
            original.backup(destination)
            mode = destination.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
            if mode.lower() != 'delete':
                raise sqlite3.OperationalError('Could not make target self-contained')

        with closing(_connect(target_path, 'ro')) as restored:
            integrity = restored.execute('PRAGMA integrity_check').fetchall()
            violations = [list(row) for row in restored.execute('PRAGMA foreign_key_check')]
            original_schema = _schema(original)
            restored_schema = _schema(restored)
            tables = {}
            copy_matches = original_schema == restored_schema
            for object_type, name, table_name, sql in restored_schema:
                if object_type != 'table':
                    continue
                restored_rows = _rows(restored, name)
                tables[name] = sum(restored_rows.values())
                if copy_matches and _rows(original, name) != restored_rows:
                    copy_matches = False
            return {
                'integrity_ok': bool(integrity) and all(row == ('ok',) for row in integrity),
                'copy_matches': copy_matches,
                'foreign_key_violations': violations,
                'relation_valid': not violations,
                'tables': tables,
            }


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python solution.py SOURCE TARGET')
    print(json.dumps(backup_review(sys.argv[1], sys.argv[2]), indent=2))
