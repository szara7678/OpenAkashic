# SQLite rehearsal backup reviewer

`solution.py` exposes `backup_review(source: str, target: str) -> dict` and a
command-line interface. Python standard library only; no production systems,
credentials, external packages, or network access are needed to run it.

## Run

From this directory:

```sh
python -m unittest -v test_solution
```

Actually run in this workspace on November 14, 2026: **10 tests passed**, output
`Ran 10 tests in 0.020s` followed by `OK`. Environment: Python **3.12.16**, linked
SQLite **3.53.4**. These are observed runtime versions, not minimum requirements.

To review your own synthetic fixture (the destination must not exist):

```sh
python make_sqlite.py source.db
python solution.py source.db backup.db
```

The test suite creates only temporary synthetic databases. It covers committed
WAL data while an idle connection stays open, inherited foreign-key violations
(including a WITHOUT ROWID table), quoted identifiers, duplicate rows, SQLite
storage types, blobs, nulls, generated columns, empty tables, indexes, triggers,
views, source-byte preservation, standalone reopening, missing sources, existing
targets and sidecars, dangling symlinks, and same-path rejection. An injected
post-backup edit confirms that verification detects differing row data.

## Behavior

- Reject an existing target first, including dangling symlinks. Reject a missing
  source without creating either database. Open the source using URI `mode=ro`.
  URI paths are escaped, so spaces, question marks and hash characters are safe.
- Reject existing target `-wal`, `-shm`, or `-journal` files as well, avoiding
  collisions with another database's artifacts. Reserve a new target with
  exclusive creation rather than overwriting it.
- Start a source read transaction, capture its schema, and use SQLite's connection
  backup API. Do not copy just the main file: committed data can reside in WAL.
- Switch the copied database to DELETE journal mode and close the destination
  connection. Reopen that file read-only for verification. The WAL test checks
  that no destination sidecars remain and that the file alone opens elsewhere.
- Compare all main-database schema records (including indexes, triggers and
  views) and complete `SELECT *` row multisets for every user table. User tables
  exclude names starting with SQLite's reserved `sqlite_` prefix, not similarly
  spelled names such as `sqliteXmuseum`. Identifiers use doubled double quotes.
  Rows retain duplicate multiplicities and storage types; floats use their binary
  representation. Row order is not treated as meaningful.
- Return `integrity_ok`, `copy_matches`, `foreign_key_violations`,
  `relation_valid`, and `tables`. Violations are four-element JSON lists; table
  counts are integers. An empty database is valid. Foreign-key violations are
  reported, never repaired: `copy_matches=true` can coexist with
  `relation_valid=false`. Integrity and relational validity are separate checks.

## Scope and limitations

Writers must remain quiescent throughout the function, as required by the task.
The explicit read transaction holds a source snapshot; this is not a protocol
for reviewing a changing production database. A long reader can delay rollback
journal writers or WAL checkpoint progress. Another idle connection may remain
open, and committed WAL data is supported. No checkpoint, repair, or DML is
issued against the source; SQLite may access/update shared-memory coordination
files while opening/reading WAL databases. Byte-for-byte preservation of those
coordination files is not promised.

Use trusted, stable local directories. Exclusive creation protects against an
already-existing target and a competing creator, but does not defend against a
hostile process replacing the file between reservation and SQLite opening it.
Other processes must not modify the target or its sidecars during review.

The scope is the main database and ordinary user tables supported by the local
SQLite build, not attached databases, TEMP objects, arbitrary extension virtual
tables/hidden columns, encryption, filesystem metadata, or byte-identical page
layout. Rowid values are not independently compared unless declared as columns;
rows are compared as SQL-visible column data. The backup API still copies the
whole main database. Default Python SQLite text decoding requires valid UTF-8
TEXT; malformed text and unavailable extensions/collations/functions can raise.
No extensions are loaded and no user-defined functions are registered.

Row multisets use memory proportional to distinct rows. Corrupt databases, I/O
errors, malformed foreign-key schemas, and unsupported SQLite features can
raise exceptions instead of producing a report. A newly created partial target
may remain on failure for diagnosis; no existing target is removed. The function
is not a crash-durable atomic publication mechanism. Successful copy verification
does not certify application semantics or absence of malicious SQL in a database.

## Sources and corrections

The designated first retrieval was a native live web search for SQLite backup,
WAL, and verification guidance. Its responses, and native URL-open responses,
contained no visible source text, so they were not treated as evidence. Official
pages were subsequently requested directly; successful retrievals and passages
actually read are recorded below. No method pack, method ID, or hash is claimed.

Design corrections relative to tempting shortcuts: a raw main-file copy can
omit committed WAL data; `integrity_check` does not replace `foreign_key_check`;
row counts or sets do not establish equality of complete duplicate-bearing
rows; unescaped identifier interpolation is unsafe; a normal create/open call
can overwrite or accidentally create a database. No test results are inferred.
