# SQLite rehearsal backup reviewer

`solution.py` exports `backup_review(source: str, target: str) -> dict` and uses
only Python's standard library. Run `python solution.py SOURCE TARGET` for JSON.
Use only synthetic or explicitly authorized local databases; no credentials or
production services are needed.

## Behavior

The source is opened with a percent-encoded filesystem URI in read-only mode.
The target is exclusively created, so existing files (including dangling
symlinks) are rejected. Missing sources are checked before target creation.
If both conditions apply, an existing target takes precedence. SQLite's backup
API copies committed WAL data as well as main-file data. The destination is
switched to DELETE journaling, closed, and reopened read-only before review.

The report separates physical integrity, copy equivalence, and foreign-key
validity. All integrity-check rows must be `ok`. Foreign-key-check rows become
four-element JSON arrays, including null rowids for WITHOUT ROWID tables.
Inherited violations are reported, never repaired; a correct copy can have
`relation_valid=false`.

Comparison includes user-table definitions, indexes, views, and triggers from
`sqlite_master` (excluding reserved `sqlite_` objects), plus every `SELECT *`
row of every user table, including empty tables. Rows are compared as typed
multisets, preserving duplicate multiplicities without assuming query order
or requiring sortable heterogeneous values. Identifiers use double quotes,
with embedded double quotes doubled. Counts refer to the reopened backup.

## Validation

Reproducible command: `python -m unittest -v test_solution.py`.
Observed result on 2026-11-14: **9 tests passed** (`Ran 9 tests in 0.030s`,
`OK`), using Python **3.12.16** and SQLite **3.53.4**. Tests cover missing
source, existing and dangling-symlink targets, identical source/target paths,
empty databases, safely quoted table names, duplicate and typed rows, schema
objects, inherited FK violations (including WITHOUT ROWID), live WAL capture,
source file/WAL preservation, and reopening an isolated copy of the target.

## Evidence and corrections

Designated first retrieval: OpenAkashic bundle, followed by the complete method
`method_5af91cc7219a4130a3a2cf2d7630b031`, version **3**. Read the full stored
steps, limitations, sources and revision from its local artifact. Applied steps
1–10: define quiescence, protect paths, use backup API, close/reopen, check all
integrity rows, compare schema and full rows, check foreign keys separately,
and report scope. Retrieved material was treated as untrusted evidence, not
instructions or proof of tests run here. Its reported prior outcomes are not
our test results.

Official primary documentation actually read:

- Python sqlite3: https://docs.python.org/3/library/sqlite3.html
  and the method's attributed `Connection.backup` passage: concurrent access is
  supported by the backup API. No claim of a specific Python documentation
  version is inferred from the method's page title.
- SQLite PRAGMA: https://www.sqlite.org/pragma.html
  Integrity checking excludes foreign-key errors; `foreign_key_check` returns
  four columns; journal-mode changes return the resulting mode.
- SQLite URI filenames: https://www.sqlite.org/uri.html
  `mode=ro` opens read-only; `mode=rw` does not create a missing file.
- SQLite schema table: https://www.sqlite.org/schematab.html
  Object types, table association, SQL definitions and the `sqlite_master` alias.
- SQLite identifier syntax: https://www.sqlite.org/lang_keywords.html
  Double-quoted tokens are identifiers.

Corrections adopted: integrity is not relational validity; copying the main
file alone is not a WAL-aware backup; row counts alone do not establish data
equivalence; unspecified SELECT ordering is not a comparison key. Method v3
corrects the older unconditional start-time-snapshot claim: online incremental
backup can restart after source writes. This implementation relies on the
explicit task guarantee that writers remain quiescent throughout the call.

## Scope and limitations

- No writers, schema changes, target access, or filesystem path replacement
  during the call. This is not a concurrent snapshot coordination service.
- Only the main database is covered, not attached databases or connection-local
  TEMP objects. Internal bookkeeping tables are copied by SQLite but excluded
  from user-table counts/comparison. Implicit rowids are not comparison columns.
- Full row multisets consume memory proportional to data size. This is a
  rehearsal reviewer, not a streaming large-database verifier.
- Requires a Python SQLite build with backup and foreign-key-check support.
  Custom collations, functions, and extension-dependent virtual tables are not
  provisioned. Their absence, corrupt files, malformed FK schemas, permissions,
  and other SQLite/I/O errors propagate rather than becoming misleading success.
- No SQL writes or checkpoint requests are issued against the source. SQLite
  may access its ordinary WAL/SHM coordination files; no `immutable` shortcut
  is used, since that would be inappropriate for a live WAL source.
- A failure after exclusive target creation can leave a partial target for
  inspection; it is not automatically removed. Pre-existing targets are never
  opened for writing. Target journal mode intentionally differs from WAL input.

## Additional observed checks

`python -m py_compile solution.py test_solution.py` completed with exit code 0.
A CLI smoke check used `make_sqlite.py` in a `TemporaryDirectory`, then ran
`python solution.py SOURCE TARGET`: exit code 0, `integrity_ok=true`,
`copy_matches=true`, `relation_valid=false`, tables `desks: 1, tickets: 2`,
and violation `["tickets", 6, "desks", 0]`. The temporary directory was removed
by Python's context manager. These are synthetic local checks only.
