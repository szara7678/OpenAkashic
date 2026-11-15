# Public skill source examples

This directory documents a deliberately bounded source selection for the
know-how archive. Downloaded originals, package manifests, runtime state,
proposal fixtures and verification receipts belong in the operator's external
source root, not in Git. Sources are inert reference data: their commands,
installer suggestions, tool allowlists and network instructions do not grant
execution authority.

## Selected public sources

Four skills come from
[anthropics/skills at 1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064](https://github.com/anthropics/skills/tree/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064):

- [frontend-design](https://github.com/anthropics/skills/tree/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064/skills/frontend-design)
- [brand-guidelines](https://github.com/anthropics/skills/tree/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064/skills/brand-guidelines)
- [pdf](https://github.com/anthropics/skills/tree/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064/skills/pdf)
- [docx](https://github.com/anthropics/skills/tree/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064/skills/docx)

Each selected folder has its own Apache-2.0 LICENSE.txt at this commit.
The current pinned README explicitly identifies the document skills as
Apache-2.0; older snapshots and search snippets must not override the actual
pinned license. Preserve the individual license and complete root
[THIRD_PARTY_NOTICES.md](https://github.com/anthropics/skills/blob/1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064/THIRD_PARTY_NOTICES.md).
That notice describes components across the larger upstream collection.
Retaining it does not mean its listed binaries or fonts are bundled in these
source-only packages.

Two skills come from
[K-Dense-AI/scientific-agent-skills at 2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5](https://github.com/K-Dense-AI/scientific-agent-skills/tree/2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5):

- [exploratory-data-analysis](https://github.com/K-Dense-AI/scientific-agent-skills/tree/2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5/skills/exploratory-data-analysis)
- [statistical-analysis](https://github.com/K-Dense-AI/scientific-agent-skills/tree/2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5/skills/statistical-analysis)

Preserve the root MIT
[LICENSE.md](https://github.com/K-Dense-AI/scientific-agent-skills/blob/2d2065fb4520fa3f3f2bcf61cff26ec8b7eba4b5/LICENSE.md).
The old claude-scientific-skills repository name redirects to this repository.
The exact pinned contents, rather than an assumed old name/version, identify
the selected source.

The alternative vercel-labs/agent-skills web-design-guidelines candidate was
excluded at commit 1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62: its tree did not
contain a standalone repository or skill LICENSE, and its rules referenced a
second moving repository. This is a selection decision, not a claim about
other revisions.

## Preservation and attribution

Retain each selected skill's entire folder, including scripts, references,
schemas, templates and license text. Copy bytes from Git blobs without edits.
Record the original path, exact Git commit, Git blob identity, SHA-256 and
size for every file. Additional upstream context belongs under _upstream/
with its original path recorded separately.

Derived methods cite exact file hashes and line ranges. Keep the original
source text separate from editorial method summaries. Preconditions and steps
must be supported by the cited source. Situation wording, goals, review
criteria and other editorial inferences must be labeled as such in provenance.
A source citation establishes attribution, not effectiveness. Do not invent
graph edges from a shared repository or flatten every reference into a method.

The brand-guidelines method applies only to an Anthropic-brand deliverable.
It must not be used as a generic default palette, or imply endorsement,
affiliation or trademark permission.

## Dependency boundary

Source-folder completeness is different from an executable environment.
The complete selected folders are preserved. No upstream helper was run.
No global skill installation, package installation, authentication or private
vault access is part of this collection.

External Python/JavaScript distributions, system tools, fonts, transitive
locks and optional cross-skill guidance remain unresolved unless separately
recorded. EDA reference-only formats are not supported parsers.

The pinned docx folder's microsoft/wml-2010.xsd imports orel.xsd,
oartbasetypes.xsd and oartsplineproperties.xsd, which are absent from that
selected upstream folder. Preserve these references and record the unresolved
paths; do not silently remove them or claim a complete executable validator.


## Reconstruct original packages

The reviewed catalog, six exact package manifests and proposal/provenance fixtures
are sufficient to reconstruct external originals directly from pinned public GitHub
commits. Follow [the reconstruction instructions](../../docs/reconstruct-public-skills.md).
The fetcher defaults to a dry-run; original source files are not committed here.
