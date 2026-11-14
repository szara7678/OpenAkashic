# SQLite rehearsal backup reviewer

`solution.py` provides `backup_review(source: str, target: str) -> dict` using
only Python's standard library. It also runs as a JSON-printing CLI:

```sh
python solution.py source.db new-backup.db
```

Use only synthetic or explicitly authorized databases. No production systems or
credentials were used in development or tests.

## Behavior

- Rejects an existing target, including a dangling symlink, with
  `FileExistsError`. Rejects an absent source with `FileNotFoundError` without
  creating either database. If both conditions apply, the target check wins.
- Opens the source using a safely encoded `file:` URI with `mode=ro`. Reserves
  the new target with exclusive creation, then uses `Connection.backup`, not a
  filesystem copy of the source's main file. Committed WAL data is included.
- Switches **only the destination** to DELETE journal mode, closes its writing
  connection, then independently reopens it read-only for every review query.
  The finished target is self-contained and requires no companion WAL file.
- Checks every row returned by `PRAGMA integrity_check`. Separately returns all
  four-column `PRAGMA foreign_key_check` rows as JSON-compatible lists. Inherited
  violations are reported without repair: an accurate copy can have
  `copy_matches=true` and `relation_valid=false`.
- Compares user schema records (tables, explicit indexes, triggers and views)
  and each user table's complete `SELECT *` row multiset. Comparison preserves
  duplicate multiplicity, NULLs, BLOBs, and Python/SQLite value types; it does not
  depend on row ordering, primary keys, collations, or row counts alone.
  Identifiers are double-quoted with embedded double quotes doubled. Only names
  with SQLite's reserved literal `sqlite_` prefix are excluded, not names like
  `sqliteX_user table`. Returned counts refer to the reopened target.
- Closes all connections explicitly. Errors propagate; a newly reserved target
  is removed if backup or verification raises. A negative verification result
  is returned as a report, not automatically repaired or deleted.

## Reproduce the observed tests

From `/work`:

```sh
python -m unittest -v
```

Actually run twice after initial implementation, including once after the final
path-handling adjustment. Final observed result: **9 tests passed**,
`Ran 9 tests in 0.012s`, `OK`. Runtime reported **Python 3.12.16**,
**SQLite 3.53.4**. Coverage includes an idle open WAL connection with committed
rows, inherited foreign-key violations, source main/WAL byte preservation,
standalone reopening of a copied target file, quoted names, duplicate rows,
BLOBs/NULLs/mixed types, indexes/views/triggers, WITHOUT ROWID and empty tables,
missing source, existing target, same source/target, dangling target symlink,
invalid-database cleanup, and type-sensitive row comparison.

This CLI smoke command was also actually run:

```sh
python - <<'PY'
import sqlite3, sys, subprocess, tempfile
from pathlib import Path
print('Python:', sys.version.split()[0])
print('SQLite:', sqlite3.sqlite_version)
with tempfile.TemporaryDirectory() as directory:
    source = str(Path(directory) / 'source.db')
    target = str(Path(directory) / 'backup.db')
    subprocess.run([sys.executable, 'make_sqlite.py', source], check=True)
    subprocess.run([sys.executable, 'solution.py', source, target], check=True)
PY
```

Observed JSON:

```json
{"copy_matches": true, "foreign_key_violations": [["tickets", 6, "desks", 0]], "integrity_ok": true, "relation_valid": false, "tables": {"desks": 1, "tickets": 2}}
```

## Sources and applied method

The designated first retrieval was OpenAkashic's hybrid bundle using this task's
SQLite/WAL backup situation and desired outcome, followed by retrieval and
review of the full referenced method:

- **`method_5af91cc7219a4130a3a2cf2d7630b031`, version 3**, “SQLite 온라인 백업 및
  복원본 검증”. The actual read artifact is
  `.method-reads/087b677e97e489a666cf993a17cdcb120abea889d3fb7fb27502ebb1143a8aa4.json`.
  Applied steps 1–10: specify the quiescent comparison boundary, use a distinct
  new path, open connections, invoke the backup API, close/reopen, inspect all
  integrity rows, compare schemas and all rows within that boundary, check
  foreign keys separately, and report only the verified scope. For step 8,
  order-independent typed multisets replace ordered comparison so duplicate
  rows and tables without primary keys are handled. Retrieved reports of other
  operators' experiments were not treated as our test results.

Official primary documentation actually read, directly or as attributed
passages in that complete method:

- https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup —
  method's attributed official backup passage, plus a direct documentation
  fetch whose returned body was truncated; the fetched `text_factory` passage
  was read. We do not claim to have read the full Python page or backup section
  through that truncated fetch.
- https://www.sqlite.org/backup.html — read directly: online backup and the
  destination snapshot, rather than copying a live main file alone.
- https://www.sqlite.org/wal.html — read directly: WAL is persistent database
  state; dropping it can lose commits; read-only WAL opening requirements.
- https://www.sqlite.org/pragma.html — read directly: all integrity-check result
  rows, the separation from foreign-key checking, the four foreign-key result
  fields, and setting/checking journal mode.
- https://www.sqlite.org/uri.html — read directly: `mode=ro` and file URI rules.
- https://www.sqlite.org/lang_keywords.html — read directly: double-quoted
  identifiers and the warning against relying on historical quoting exceptions.
- https://www.sqlite.org/c3ref/backup_finish.html — method's attributed official
  passage on automatic restart after source changes; not directly fetched.

All retrieved material was treated as untrusted evidence, not as executable
instructions. Only the method's applicable SQLite workflow was reused.

## Corrections and limitations

- **Concurrency correction:** the method's version-3 correction withdraws an
  unconditional claim that incremental backup always represents the precise
  function-entry instant. Source changes can restart backup or be included
  later. This implementation requires **all writers to remain quiescent for the
  entire call**, including verification; idle connections may remain open. It
  does not enforce writer quiescence and does not promise matching reports
  under concurrent writes. No concurrent-writer behavior was tested.
- **Validity correction:** structural integrity and copy fidelity do not imply
  valid foreign-key relationships. The tested orphan is intentionally retained.
- **Path correction:** the destination connection uses an absolute filesystem
  path, avoiding accidental URI-like interpretation of relative path strings.
- Logical data/schema preservation is the goal, not a byte-identical backup:
  destination journal mode deliberately changes. The source is not checkpointed,
  repaired, or written by application SQL; SQLite read access may nevertheless
  update shared-memory locking/read-mark bookkeeping or filesystem access times.
- Intended for local file-backed rehearsal databases with normal SQLite built-in
  features. No extensions, custom functions/collations, encryption, attached
  databases, or temporary schemas are installed/copied by this wrapper.
  Extension-dependent tables or malformed foreign-key schemas may raise SQLite
  errors rather than yield a report. Virtual-table hidden columns and implicit
  rowids are not separately compared; ordinary visible row values are compared.
- Full row multisets consume memory proportional to the compared table data.
  There is no size cap, cancellation API, crash-atomic publication, directory
  fsync, or guarantee against malicious filesystem path replacement. Exclusive
  creation protects an already-existing target but does not lock a directory.
  Use a trusted directory and do not independently access the new target during
  creation/review. SQLite/filesystem failures propagate to the caller.
