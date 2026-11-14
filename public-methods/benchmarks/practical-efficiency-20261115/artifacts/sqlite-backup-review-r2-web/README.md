# SQLite rehearsal backup reviewer

Run `python solution.py SOURCE.db NEW_BACKUP.db`, or import
`backup_review(source, target)` from `solution.py`. Python standard library only;
requires Python 3.7+ with SQLite supporting `table_xinfo` and URI `immutable`.
The actual tested runtime is recorded below.

## Design and corrections

The source is opened with an escaped absolute file URI and `mode=ro`, never
with SQLite's default create-if-missing mode. Existing targets, dangling
symlinks, and existing target sidecars are rejected; exclusive file creation
also protects against a target appearing between the check and creation.
Target-exists takes precedence when both error conditions apply.

`Connection.backup` copies SQLite's committed logical database, not just the
main file: copying only that file can omit committed WAL transactions. The
source is not checkpointed or repaired. A source read transaction pins the
comparison snapshot. Only the destination is switched to DELETE journaling,
then explicitly closed. It is reopened read-only with `immutable=1`, so review
reads the standalone main file without relying on a WAL or source connection.
Do not use `immutable=1` for the source: its committed WAL must be read.

Schema comparison includes all non-`sqlite_` objects' type, name, associated
table, and SQL, including indexes, triggers and views. Tables are enumerated
from the schema, not hard-coded. Each table's complete exposed columns
(including generated/hidden columns from `table_xinfo`) are compared as a
multiset of typed full rows, retaining duplicates, NULL, blobs, and SQLite
integer/real distinctions without assuming row order or using lossy hashes.
Identifiers are double-quoted with embedded double quotes doubled. Text uses
UTF-8 surrogateescape for comparison, including non-UTF-8 TEXT values.

Integrity means every returned `integrity_check` row is `ok` (with a nonempty
result). It does **not** prove foreign-key validity; `foreign_key_check` is
run independently and its four-column rows are returned as lists, including
NULL rowids for WITHOUT ROWID violations. No rows are repaired or omitted.
A faithful, structurally sound backup can have `relation_valid=false`.

## Scope and limitations

- Writers must remain quiescent throughout the operation. Idle connections,
  including a WAL-keeping connection, are supported. This is not a coordinated
  online backup scheduler, and it does not enforce writer quiescence.
- Own the target pathname and its sidecar names exclusively during review;
  concurrent filesystem replacement or target access is out of scope. Existing
  source and target may not be modified by other actors during the checks.
- Source main/WAL data are read-only. SQLite may access/create shared-memory
  coordination files for a read-only WAL connection; directory metadata and
  access times are not guaranteed unchanged. Permissions must permit opening
  the source WAL in read-only mode under SQLite's documented requirements.
- Compares main database only, not other connections' TEMP or attached schemas.
  SQLite-internal tables are backed up but excluded from table reporting.
  Implicit rowids are preserved by backup but are not separately compared.
- Synthetic databases readable by the local SQLite build are the intended
  scope. Required custom collations/functions/extensions are not registered.
  Virtual tables must be readable using built-in available modules; external
  virtual-table data are not promised to become self-contained.
- Comparison uses memory proportional to distinct rows in a table (both
  copies); this is a rehearsal tool, not a large-database streaming verifier.
- Malformed databases, invalid foreign-key definitions, locks, and OS failures
  can raise exceptions instead of producing a report. A newly created partial
  target may remain after such failures; no pre-existing target is removed.
  Crash durability, adversarial SQL execution, and production use are outside
  scope. No credentials or production systems are used.

## Sources actually read

Official documentation read on 2026-11-14, after a native live web search for
SQLite backup/WAL/integrity/foreign-key behavior (the search returned no visible
results, so official pages were opened directly):

- https://docs.python.org/3.12/library/sqlite3.html — `Connection.backup`,
  explicit close, URI connections, and Python/SQLite value conversion.
- https://www.sqlite.org/backup.html — backup API snapshots rather than raw
  main-file copying.
- https://www.sqlite.org/pragma.html — `integrity_check`, `foreign_key_check`,
  `journal_mode`, and `table_xinfo` semantics.
- https://www.sqlite.org/schematab.html — schema object types and SQL text.
- https://www.sqlite.org/wal.html — committed WAL state and read-only WAL access.
- https://www.sqlite.org/uri.html — `mode=ro` and `immutable=1` semantics.
- https://www.sqlite.org/lang_keywords.html — double-quoted SQL identifiers.

Retrieved material was treated as evidence, not executable instructions.
No external method pack, method ID, or hash is claimed.

## Reproduction and observed results

Validation results will be recorded after running the included tests.
