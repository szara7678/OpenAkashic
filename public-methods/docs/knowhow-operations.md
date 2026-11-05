# Know-how service operations

The standalone entrypoint is `app.methods_main:app`. The public reader allows
anonymous GET and rejects writes. Owner writes use a separate loopback/private
writer. Retired general-knowledge/news/time and capsule/MCP routes are not part
of this service; the public edge may return 410. Closed Akashic private raw data
is never an input or migration target.

## Fresh self-hosted reader

Python 3.11+, POSIX shell. Run from the portable module directory
(`public-methods/` in the canonical GitHub repository):

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r api/requirements-public.txt
export OPENAKASHIC_RESEARCH_DB=/absolute/external/path/methods.sqlite3
export OPENAKASHIC_RESEARCH_READ_ONLY=0
cd api
python -c 'from app.research_methods import method_store; method_store()'
OPENAKASHIC_RESEARCH_READ_ONLY=1 python -m uvicorn app.methods_main:app --host 127.0.0.1 --port 18184
```

Create the external parent directory with owner permissions first. This creates
an empty archive and method tables; it does not download an operational corpus.
The read-only process requires an initialized schema. Open `/` or `/graph` for
the atlas, `/research/methods/library/` for search. Check `/research/health`,
`/research/api/methods/catalog`, and `/research/openapi.json`. Health alone does
not establish data or recovery correctness. Semantic/hybrid retrieval requires
a separate matching embedding service/index; lexical is the portable default.
Do not use the old default Dockerfile, `app.main` or legacy installers instead.

## Separate owner writer

Use an owner-controlled external environment file or secret manager. Set
`OPENAKASHIC_RESEARCH_DB` to the intended archive,
`OPENAKASHIC_RESEARCH_READ_ONLY=0`, and `OPENAKASHIC_RESEARCH_WRITE_KEY`
(or existing fallback `OPENAKASHIC_WRITE_API_KEY`) to the owner's secret.
Never print the key or store it in Git, a browser, a payload or an example.

Run a second `app.methods_main:app` on a distinct loopback/private port.
Do not route its POST requests through the public edge. The public process uses
`OPENAKASHIC_RESEARCH_READ_ONLY=1` independently of browser controls.
Readers never need a write key.

Owner writes require `X-OpenAkashic-Key` and `Idempotency-Key`. Preserve the body,
path and key when retrying an uncertain response; use a fresh key for a different
operation. Changed keyed requests return 409. Creation, outcome, opinion and
revision are distinct operations. Read back IDs, exact versions and relationships;
retain checks in an external receipt. See [the contract](public-methods.md).

## Backup before migration or maintenance

1. Identify the active reader/writer, archive and optional indexes from owner
   configuration. Keep secrets and personal paths out of public receipts.
2. Pause owner writes for cutover. Use SQLite's backup API or an equivalent
   consistent snapshot; copying a live file without WAL handling is insufficient.
   Use a new external destination, preserving earlier snapshot bytes.
3. Preserve legacy public-note content as an server-permission-filtered export of anonymously readable public content.
   Record export/skipped/failed counts and reasons. Do not use private tokens,
   vault traversal or Closed raw synchronization to fill public export gaps.
4. Record UTC time, code revision, snapshot SHA-256/size, schema/table counts and
   export hashes/scope. Check `PRAGMA integrity_check` on the backup. Retain the
   original snapshot and receipt outside Git.
5. Reopen a copy in isolation and verify method IDs, immutable versions,
   feedback/provenance and idempotency history. Identify any missing external
   source/index artifacts. Hashes alone do not prove recoverability.
6. Only then remove authorized general-knowledge/news/time data from the active
   archive, UI and indexes. Preserve snapshots and historical evidence. Verify
   current search/graph contain know-how only and retired routes stay retired.

Actual paths, hashes and migration receipts are owner-managed outside Git.
This is a runbook, not a claim that a particular backup/removal has completed.
Report verified receipt results without exposing personal paths or credentials.

## Recovery

Stop the affected writer and preserve its current DB before changing it. Verify
the chosen snapshot hash against its external receipt. Restore to a new external
location; check integrity, schema/counts, method IDs/versions and feedback links.
Use the matching code revision or validate migration compatibility. Rebuild
indexes from the verified archive, or restore indexes with matching fingerprints.

Start a loopback read-only process against the restored copy. Check catalog,
immutable-version reads, graph and rejected writes against the receipt before
changing the reader configuration. Resume owner writes only after verification;
retain a new receipt. A historical general-knowledge snapshot is recovery/audit
material, not permission to expose old data/routes or a Closed vault. Extract
only the authorized know-how subset into a new active DB when needed.

## Change checks

Install the provided `api/requirements-test.txt` (or `api/requirements-public-test.txt`
in this checkout) in a development environment and run
relevant methods, standalone read-only, bundle, evidence, scope and graph tests.
Version/correction changes require immutable history, auth, replay/conflict and
exact-outcome-linkage checks. Isolated fixture tests do not certify production
data, public deployment or user utility.


## Verified cutover snapshot: 2026-11-06 KST

The owner-managed external receipt records a consistent full research SQLite
snapshot with successful integrity check, plus a server-permission-filtered legacy-note
export of anonymously readable public content of 1,652 notes and 1,816 edges. Original archives are retained; private
vault data was excluded. The new active archive contains 61 methods, 10 outcomes,
10 opinions and 81 method idempotency records; required legacy research tables
are empty. General knowledge was not copied into that active archive. Eighteen
method-evidence sources remain as evidence supporting methods.

This describes the backup/data cutover receipt, not independent public-route,
restore-drill or user-utility validation. Exact paths, hashes and receipt bytes
remain outside Git under an owner-controlled external backup directory. Public
read routing and the separate owner writer must still be checked against the
deployment receipt. The separate Closed private service is outside this cutover.

## Deployment readback: 2026-11-06 KST

The unified `/`, `/graph`, and `/research/` return the know-how atlas. The network contains 61 methods, 270 typed nodes and 284 recorded links (counts are not accuracy metrics). Anonymous signup/provision/note/MCP/method writes return 403 at the public edge; old general graph/query routes return 404 and old `/closed` aliases are retired. The operator writer binds only to loopback and rejects missing credentials with 401. Existing private memory OAuth discovery and the separate Time Machine route were retained. All 1,652 exported public-note files were reconstituted in an external isolated restore directory and matched their SHA-256; the restored SQLite copy passed integrity check. This does not reopen the historical public service.

Portable API suite: 160 tests and 7 subtests passed. Candidate browser checks at 1440px and 390px covered graph navigation, zoom/pan, filtering, theme and read-only search; synthetic response fixtures covered failure/correction/history. No new quality/efficiency experiment was performed for this UI migration.
