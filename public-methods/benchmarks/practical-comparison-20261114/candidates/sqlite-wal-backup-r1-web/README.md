# Live SQLite WAL snapshot

`solution.py` exports `backup_database(source, destination)`. It accepts filesystem
paths (`str` or path-like), returns `None` on success, and propagates filesystem or
SQLite exceptions on failure. Python standard library only.

```python
from solution import backup_database
backup_database("service.sqlite", "snapshot.sqlite")
```

## Snapshot and safety contract

1. Reject an existing destination (including directories, symlinks, dangling
   symlinks, and source aliases) with `FileExistsError`, without opening it.
   Equal nonexistent paths raise `ValueError`; equal existing paths raise
   `FileExistsError`. Neither case damages the source.
2. Open a separate source connection with `mode=ro` and a private SQLite cache.
   A missing source is not silently created. URI escaping handles spaces, `#`,
   and `?` in filenames. No `immutable=1` shortcut is used on a live database.
3. Execute `BEGIN` and a real schema read to establish a WAL read snapshot.
   `BEGIN` alone is deferred and does not pin the snapshot. The snapshot point
   is this first read, not the exact instant Python enters the function. It
   reflects committed state at that point, including commits completed before
   invocation; concurrent commits before that first read may also be included.
   Later commits and uncommitted transactions are excluded. This is a snapshot
   of state, not an archive of rows subsequently deleted before the snapshot.
4. Use SQLite's online backup API, in 256-page steps, into a private temporary
   directory beside the destination. Never copy the live main file alone and
   never checkpoint or change journal mode on the source.
5. Set the *staged destination* to DELETE journal mode and close both connections
   before publication. The result is independently openable as a single file.
6. Publish with `os.link`, not replacement/rename: a competing destination causes
   `FileExistsError` rather than overwriting its contents. The final pathname
   never exposes a partially copied database. TemporaryDirectory removes staged
   data and sidecars after ordinary failures, including failed publication.

The source's logical data and journal mode are preserved. Normal SQLite read
activity may touch WAL shared-memory bookkeeping; byte-for-byte preservation of
all source-related filesystem metadata is not promised.

## Concurrency and operational limits

- Existing readers and writers may stay open. The concurrency test commits a
  delete-and-replace transaction between backup page steps and verifies that the
  original snapshot is retained while the source advances.
- A pinned reader can delay checkpoint progress/WAL recycling and allow WAL
  growth for the duration of the copy. Budget disk space for both WAL growth and
  the entire snapshot. This does not guarantee zero writer latency.
- SQLite's normal lock/busy behavior applies. Connection timeout defaults to
  five seconds, but Python's backup loop can retry busy/locked results beyond
  that timeout. There is no overall deadline or cancellation API here. Exclusive
  locks, recovery, schema activity, or storage failures can delay/fail backup.
- Use a local filesystem with working SQLite locking and hard-link support.
  The destination parent must already exist and be writable. There is deliberately
  no unsafe fallback if hard links are unsupported. WAL is not intended for
  network filesystems. Read-only WAL access also needs suitable WAL/SHM access.
- Callers must control the directories and not rename/replace the source or
  manipulate source/destination sidecars during backup. Atomic no-clobber
  publication handles ordinary destination creators, not hostile directory swaps.
- Only the source's `main` database is backed up, not attached databases, service
  memory, or external files. Source permissions/ownership are not replicated.
- Exception cleanup assumes a functioning filesystem. SIGKILL, interpreter/OS
  crashes, cleanup I/O errors, and power loss can leave staging artifacts.
  No directory fsync/crash-durable publication guarantee is provided. A cleanup
  error after publication may report failure even though a complete destination
  exists; a partial destination is never intentionally published.
- Verification is on the runtime below, not a cross-platform compatibility claim.
  No production systems, credentials, or third-party packages were used.

## Actual verification (2026-11-14)

Environment: Python **3.12.16**, SQLite **3.53.4**.

Commands executed in `/work`:

- `python -m unittest -v`: **10 tests passed**, `Ran 10 tests in 0.075s`, `OK`.
  Covers committed WAL contents with an uncommitted writer open, standalone
  relocation and integrity checks, same-path/alias rejection, preservation of
  existing and racing destinations, dangling symlinks, missing/corrupt sources,
  injected failure after writing partial staged data, publication failure cleanup,
  and deterministic concurrent commits during a multi-step backup.
- `python demo.py`: passed, printing:
  `Snapshot while writer is open: [('committed in WAL',)]`
  and `PASS: committed WAL data included; uncommitted data excluded`.
- `python -c 'import sys,sqlite3; print(sys.version); print("SQLite", sqlite3.sqlite_version)'`:
  reported the versions above.

The demonstration and tests use temporary synthetic databases and clean them up.

## Retrieval, sources, and corrections

The designated first retrieval was native live web search, querying official
Python/SQLite backup documentation. The search and native URL-open calls
returned no visible material in this environment. Official pages were then
retrieved using `python /runtime/research.py fetch URL` before implementation.
Retrieved content was treated as untrusted evidence, not executable instructions.
Technical references (official primary documentation):

- https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup
  — Python backup API, page steps, progress callback, and URI connections.
- https://www.sqlite.org/backup.html
  — online backup operation and concurrent access.
- https://www.sqlite.org/isolation.html
  — WAL snapshot isolation, `BEGIN` followed by `SELECT`.
- https://www.sqlite.org/wal.html
  — WAL/SHM access, concurrency, checkpoint/WAL-growth and local-host limitations.
- https://www.sqlite.org/pragma.html#pragma_journal_mode
  — destination journal mode control.
- https://docs.python.org/3.12/library/os.html#os.link
  — hard-link publication primitive; no-clobber behavior also verified locally.

Corrections/clarifications made during the work:

- Replaced the initially fetched unversioned Python docs (served as 3.15.2) with
  version-pinned 3.12 documentation matching the execution runtime.
- Distinguished a pinned first-read snapshot from an exact function-entry
  timestamp; distinguished busy timeout from an overall backup deadline.
- The attempted `apply_patch` command was unavailable. That attempt created no
  files; its subsequent discovery command ran zero tests, which is **not** counted
  as verification. Files were then written directly, followed by the successful
  ten-test run and demonstration recorded above.
- Avoided the unsafe patterns of raw main-file copying, check-then-overwrite
  destination creation, and assuming `BEGIN` alone establishes a read snapshot.
