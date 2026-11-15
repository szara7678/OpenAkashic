# Reconstruct the reviewed public skill sources

The repository keeps reviewed source manifests, licenses/provenance metadata and
method proposals. Raw source originals remain external runtime artifacts. You
can reconstruct the same six packages directly from their immutable upstream
Git commits without the maintainer's operational cache.

Run from the repository with Python dependencies for public-methods installed:

    PYTHONPATH=public-methods/api python3 public-methods/api/scripts/fetch_skill_sources.py \
      --catalog public-methods/examples/skill-sources/catalog.json \
      --methods-plan public-methods/examples/skill-sources/method-proposals.json \
      --output /tmp/openakashic-public-skill-sources

This is a dry-run: it validates reviewed metadata and any existing files but
makes no network request and creates no output. Choose an output directory
outside every Git checkout. Repeat with --apply to fetch exact original bytes.

Only public HTTPS GitHub repositories are accepted. Every raw URL is derived
from the repository owner/name, exact 40-character commit and original_path in
the reviewed manifest. Arbitrary per-file URL fields are ignored. No
authentication, inherited proxies, external programs, script installation or
skill execution are used. Redirects are rejected. A failed or unavailable
immutable source does not fall back to main, latest or another host.

Every file must match its reviewed byte size, SHA-256 and Git blob SHA-1 before
an exclusive write. Original skill directories, reference files, scripts,
templates, assets, license and notice context are preserved. Input limits are
20 packages, 64 MiB total, 32 MiB per package and 2 MiB per file, with a 20-second
request timeout. Unexpected/unlisted files, corrupt preexisting files, unsafe
paths and symlinks fail rather than being replaced.

fetch-receipt.json records partial/completed progress without credentials or
file content. A rerun rechecks all existing hashes and downloads only missing
files. It does not trust a prior receipt as proof of file integrity. No original
file is overwritten. If a preexisting file is corrupt, inspect and move it aside
explicitly before resuming. The runtime catalog is published only after all
reviewed originals have been downloaded; use only a complete receipt for import.

The resulting source root is compatible with the existing owner importer:

    PYTHONPATH=public-methods/api python3 public-methods/api/scripts/import_skill_sources.py \
      --source-root /tmp/openakashic-public-skill-sources \
      --runtime-root /external/public-skill-runtime \
      --methods-plan public-methods/examples/skill-sources/method-proposals.json

That command is also a dry-run. API writes remain owner-only and require the
existing explicit private-writer options. Reconstruction does not publish any
method, start a service or change deployment.

The editorial-provenance.json fixture separates explicit upstream instructions
from the editor's inferred situations, goals, criteria and limitations.
Source pinning establishes reproducible originals, not independent effectiveness.
External libraries, runtimes and unresolved references remain described in
the package manifests; preserving originals does not install or complete them.

## Verification record

On 2026-11-15, a fresh anonymous download reproduced all six reviewed packages:
121 original files, 2,025,414 bytes. Every size, SHA-256 and Git blob identity
matched the committed manifests, including original license/notice context.
The requests used raw.githubusercontent.com URLs pinned to the exact commits.
A repeat run reverified all 121 files with network access explicitly disabled.

The [sanitized verification summary](../examples/skill-sources/reconstruction-verification.json)
records package/commit identities, manifest and license hashes, byte totals and
the fetcher version. It contains no operational paths, credentials or raw logs.
Twelve mock-network tests cover dry-run, exclusive preservation, partial resume,
corruption, path and host restrictions, redirect rejection and exact method spans.

The initial attempt selected an output under an existing Git ancestor and was
refused before writes. Selecting a fresh directory outside Git resolved that
expected guard refusal. A separate post-trial importer path-boundary correction
allows an external preview beside a portable release while still rejecting
locations inside the actual checkout; focused importer tests cover both layouts.

These checks establish reproducible source preservation. No upstream helper ran,
no dependency environment was installed, and no live method import or deployment
occurred as part of reconstruction. They do not establish utility or token savings.
