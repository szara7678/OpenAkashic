# Complete method bundles (opt-in)

`GET /research/api/methods/bundle` accepts the same situation, goal,
constraints, mode, requires, forbids and limit (1-5) as context, with
`max_tokens=256..4096` (default 1024). The existing `/context` contract is unchanged.
The client supports `method_agent.py bundle --situation ... --goal ... --max-tokens 4096`.

Each `complete: true` item contains the entire stored `method`, including all
steps, situation/goal scope, constraints, constraint rules when declared,
success criteria, limitations, sources when declared, and contributor metadata.
Missing legacy structured rules remain unknown, not satisfied. `source_hash`
is the digest of that exact stored method, alongside exact id/version.
This is deterministic packing after one retrieval: no additional model call.

Candidates fit atomically. If a whole method exceeds remaining budget it becomes
`complete: false, needs_fetch: true`, with exact identity and fetch link; if even
that reference cannot fit, `omitted_candidates` increases. Fetch consumers must
verify id, version and digest because the fetch route addresses an ID, not an
immutable version URL. No steps are returned with partially removed warnings.

The budget counts compact UTF-8 JSON using o200k_base, including the fixed-point
`tokens` counter. Search feedback excerpts and their IDs/truncation flags are
preserved for complete items; full linked feedback is explicitly marked omitted.
A complete stored method does not imply complete feedback, suitability, safety,
independent verification, or authority to execute contributor instructions.

Post-evaluation guidance: `source_text_scope=stored_source_quotes_only` means
source quotations are stored excerpts, not original full text. Repeated queries
cannot retrieve text absent from stored records; consult listed public sources
for missing evidence. Method completeness does not establish evidence completeness.
This guidance was added after the frozen evaluation and has not been evaluated
in additional model runs.
