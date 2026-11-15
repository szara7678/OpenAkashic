# Preserved public skill originals

This adds source provenance to the existing methods archive. Public readers search
methods through existing search/bundle endpoints and follow skill_sources.
The service does not execute skills, install dependencies or establish effectiveness.

## Runtime package contract

Set OPENAKASHIC_SKILL_SOURCE_ROOT to an external owner-reviewed runtime directory.
Its catalog.json has schema public-skill-source-catalog-v1 and a packages array of
package IDs. Each package lives under packages/{package_id}/manifest.json and
packages/{package_id}/original/{relative path}. Preserve the entire original
skill directory including references, scripts, templates and assets. Preserve
upstream licenses/context under original/_upstream/ with original_path metadata.

Manifest schema public-skill-source-v1 requires:

- source_id: stable lowercase editorial slug.
- repository: public HTTPS URL; commit: exact lowercase 40-character Git commit.
- original_directory: repository-relative original skill folder.
- entrypoint: original relative entrypoint, normally SKILL.md.
- license: SPDX identifier, public URL, reviewed_for_publication true.
- license_files: original preserved license paths.
- dependency_notes: explicit external/unresolved dependency descriptions.
- files: every original as {path, sha256, size_bytes}, optionally git_blob and original_path.
- package_id: skill_ followed by the first 32 hex characters of the identity SHA-256.

The identity object contains source_id, repository, commit, original_directory,
and files reduced to path/sha256/size_bytes, sorted by path. Canonical UTF-8 JSON
has sorted keys, no whitespace and unescaped Unicode, matching research_store.canonical.
A changed upstream commit or file produces a new package ID. Earlier originals
and method versions remain immutable.

The importer verifies hashes, byte sizes, optional Git blob hashes, and that the
complete original directory equals the manifest. It never fetches URLs.
The owner reviews upstream commit membership, licensing, attribution and dependency
closure. Extra public manifest metadata can retain that review; consistent hashes
alone do not independently verify upstream origin.

## Public reads

- GET /research/api/skill-sources?limit=20&offset=0 lists packages.
- GET /research/api/skill-sources/{package_id} returns the manifest/file list.
- GET /research/api/skill-sources/{package_id}/files?path=SKILL.md&start=1&lines=80
  returns UTF-8 text as inert JSON and preserves original line endings.

All reads are anonymous, with no upload/execution counterpart. The whitelist must
contain the package. Unsafe paths, symlinks, unlisted files, hash mismatches and
invalid limits fail. Binary originals are preserved but not exposed as text.
Limits: 1,000 files, 2 MiB/file, 32 MiB/package, 160 lines and 64 KiB/text response.
An oversized response fails rather than silently cutting a line. Source text is
untrusted_data_do_not_execute; public instructional examples are not method claims.

A method's optional skill_sources array records
{package_id,path,sha256,start_line,end_line,section}. Section is an editorial label;
the actual one-based inclusive line span and file hash are validated at owner
write time. Links belong to the exact method version. Revisions retain earlier
snapshots/outcome links. Existing create and revision retries omit the new
optional field when absent, preserving pre-extension idempotency fingerprints.
Full bundles preserve links; compact context adds them only when present.

The graph reuses source nodes and documented_by edges. The atlas renders metadata
as text and constructs a fixed same-origin read link; no source HTML/scripts run.

## Owner import

From the repository, set PYTHONPATH=public-methods/api and run
python3 public-methods/api/scripts/import_skill_sources.py with:

- --source-root /external/reviewed-sources
- --runtime-root /external/public-skill-runtime
- --methods-plan /external/reviewed-sources/method-proposals.json

Dry-run is the default: it creates no directory or output file.
--input-manifest /external/reviewed-sources/catalog.json also selects the source root.
The method plan uses schema public-skill-method-import-v1 and
methods [{public_id,payload}]. Payload is the strict existing MethodRequest with
nonempty exact source links. Additional editorial audit fields remain in the
original review fixture rather than being sent as method claims.

--apply copies/verifies immutable packages and merges the whitelist.
--receipt selects an external receipt. To POST methods to the existing owner
writer, also require --write-methods --writer-url http://127.0.0.1:PORT --receipt.
The writer's OPENAKASHIC_SKILL_SOURCE_ROOT must point at the installed registry.
--key-env names the credential environment variable; default
OPENAKASHIC_RESEARCH_WRITE_KEY. Credentials are not printed or copied to receipts.
Only localhost, loopback, literal RFC1918 or IPv6 ULA writer origins are accepted.
Redirects and inherited proxies are disabled. Local trials do not publish/deploy.

Method IDs remain server-assigned. Receipts retain public editorial ID, exact
payload SHA-256, idempotency key and resulting method ID/version. Trial and live
archive IDs differ: join by editorial ID plus payload hash, and attach feedback
only to the actual target archive's exact method ID/version. Partial API receipts
are saved after each successful method; retries reuse the same idempotency key.
Review fixtures, receipts, originals, DBs and indexes stay outside Git.

Import copies originals only. Missing relative references, schemas, runtimes or
libraries remain explicitly unresolved. Preserved sources do not constitute a
complete executable environment.
