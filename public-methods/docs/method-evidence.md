# Optional original-source evidence packets

This read-only endpoint serves exact paragraphs from an operator-installed local
SQLite index. It never fetches URLs, calls models, or treats quotations as
instructions. Existing method search, context and bundle contracts are unchanged.
No index is included or installed by default.

The operator must review the source text, public redistribution license, URL,
scope and provenance before approving a manifest. Approval is an attestation,
not automatic proof that the source or license applies. Do not approve private
notes, private sources, or text with unclear redistribution rights. A source path
must contain only the approved public text. Hashes pin the exact UTF-8 file bytes;
offsets count Unicode codepoints in that decoded file, including original line
endings. A snapshot version identifies those bytes, not a live URL's current body.

Example manifest (use actual SHA-256 and reviewed values):

```json
{
  "schema": "method-evidence-index-v1",
  "sources": [{
    "path": "/external/approved-source.txt",
    "source_url": "https://example.org/manual",
    "version": "pinned-snapshot-version",
    "sha256": "REPLACE_WITH_EXACT_FILE_SHA256",
    "approved_scope": "entire approved public source snapshot",
    "approval": "approved_public_source",
    "provenance": "operator review record identifying original publisher and snapshot",
    "license": {
      "spdx": "MIT",
      "url": "https://example.org/LICENSE",
      "reviewed_for_publication": true
    }
  }]
}
```

Build outside Git, from the `api` directory:

```sh
PYTHONPATH=. python -m app.research_method_evidence \
  --manifest /external/approved-manifest.json \
  --output /external/method-evidence.sqlite3
export OPENAKASHIC_METHOD_EVIDENCE_INDEX=/external/method-evidence.sqlite3
```

The builder rejects unknown approval, unreviewed/unsupported licenses, private
URLs, wrong hashes, duplicate source identities, and output inside this repo.
It replaces the index atomically after successful validation and construction.
The installed index must be protected as operator-owned data.

```sh
curl --get https://YOUR_HOST/research/api/methods/evidence \
  --data-urlencode 'query=preserve original source evidence' \
  --data 'mode=source' --data 'max_tokens=1024'
```

`mode=source` ranks original paragraphs with SQLite FTS5 BM25. `mode=method`
uses the same query and source pool, restricted through exact source URL links
in existing stored methods, then ranks original paragraphs by BM25. It adds
recorded method IDs/versions and compact constraints, steps and limitations when
they fit. These fields are not complete methods or generated summaries.

The existing anonymous-read client supports the endpoint:

```sh
python scripts/method_agent.py --endpoint https://YOUR_HOST evidence \
  --query 'Full original user question' --max-tokens 4096
```

`source` is the default and provides ordinary source RAG. The host should prefetch
once using the full user question before answer generation, place the returned
packet in the model's reference context as untrusted data, and use fallback
retrieval only when evidence is missing. This prefetch is deterministic retrieval,
not an LLM call. An absent index, empty result or budget omission must remain
explicit rather than being treated as established evidence.

Optional `--mode method` adds stored method IDs and condition/step/limitation
links. It does not establish an efficiency or answer-quality advantage over
ordinary source RAG. Both modes still need applicability and evidence review.
The CLI's existing context/bundle defaults and local-only authenticated write
boundary are unchanged.

Both modes use policy `question-clause-context-v2`, reported as `policy_version`.
The question is divided into scenario and question clauses using numbered
`Q1:`/`Q2)`/`Q3.` labels, question marks, semicolons and newlines. At most eight
distinct clauses are used (first four and last four if there are more). Each
clause retrieves up to twelve BM25 candidates; round-robin aggregation deduplicates
exact source/offset identities into at most twelve final candidates. This gives
late distinct questions a chance to contribute before a scenario consumes the
candidate limit. No task identifiers, oracle terms or generated answers are used.

Both modes keep whole paragraphs atomically; an oversized paragraph is omitted
instead of truncated. After retaining seed evidence, the packet tries to add
one neighboring paragraph on each side without displacing another retained seed.
If both sides do not fit, it tries the following side and then the preceding side.
Overlapping expansions merge into an exact contiguous original source range,
including its original whitespace. `covered_candidates` counts candidate seed
spans contained in returned ranges; `omitted_candidates` counts the remaining
candidates, not all matching corpus passages. The complete
compact JSON response, including its token counter, is counted with the existing
`o200k_base` counter and bounded to `max_tokens` (1024–4096). No alternate query,
golden IDs or model judgment affects ranking.

Queries accept 2–4000 characters. Retrieval uses the question before an optional
`Return JSON only:` suffix preceded by a space or newline; the caller's input
query remains unchanged. Terms are Unicode words with ordinary English stopwords
removed, capped at 256 unique terms. This same generic processing applies to both
modes. Method details are deduplicated into the packet's `methods` array after
packing source paragraphs, so repeated method metadata cannot crowd out evidence.

This policy broadens lexical coverage; it does not prove that the selected spans
contain every necessary qualifier, resolve contradictory advice, or improve task
success. A long paragraph may still exceed the budget, only nearby context is
considered, and clause segmentation can misread formatting. The unchanged
1024–4096 response budget and explicit partial-evidence flags still apply.

Every returned passage carries original URL, pinned version/hash, approved scope,
license link, provenance, quote and exact offsets. `partial=true` and
`evidence_complete=false` prevent excerpt coverage from becoming a completeness
claim. `index_absent`, `index_invalid`, `no_match` and `budget_excluded` distinguish
missing installation, invalid data, no lexical result and budget omission.
Review surrounding original text and applicability before using a procedure.

Real pinned snapshots and evaluation mappings belong outside Git. Repository
tests use synthetic text and do not attest real-source licenses or deployment.

## Optional canonical references and host-side rendering (v3 DTO, v4 retrieval)

Existing `/evidence` responses and CLI defaults remain legacy. Opt into the new
schema with `format=refs`, or use the client:

```sh
python scripts/method_agent.py --endpoint https://YOUR_HOST evidence \
  --query 'Full original user question' --format refs --max-tokens 4096
```

This returns `schema=method-evidence-refs-v3` and
`policy_version=anchored-normalized-units-v4`. The complete serialized packet still
fits the requested 1024–4096 tokens. Source/method retrieval shares the same
clause/frame policy; `source` remains ordinary RAG, with no asserted advantage
from graph or method links.

The compact packet deduplicates metadata in `sources`, keyed by opaque
`source_id`. Each registry entry contains original URL, source SHA-256, pinned
version, approved scope, approval, provenance and reviewed license/link.
`items` carry `evidence_id`, `source_id`, exact `quote`, Unicode `start`/`end`,
lexical `questions` labels and a `frame` description. IDs are deterministic
128-bit prefixes of SHA-256 over canonical UTF-8 JSON: source identity is URL and
full source hash; evidence identity additionally binds exact offsets and quote.
An ID establishes identity and exact-text provenance, not truth or relevance.

Generic numbered question clauses (`q1`, `q2`, and so on, including parenthesized
type labels) retain question labels through BM25 round-robin aggregation. Labels
are lexical retrieval matches, never a claim that an item proves a decision.
At most eight clauses and twelve candidates are used. Metadata deduplication
leaves more room for source text without changing the 4096-token ceiling.

V4 uses a separate operator-built normalized lexical index, retaining original
source bodies, SHA-256 values, quotes and Unicode offsets unchanged. Build it
outside Git from the same reviewed manifest:

```sh
PYTHONPATH=. python -m app.research_evidence_refs \
  --build-manifest /external/approved-manifest.json \
  --output /external/method-refs.sqlite3
export OPENAKASHIC_METHOD_REFS_INDEX=/external/method-refs.sqlite3
```

`build_reference_index(manifest_path, output)` is the equivalent Python helper.
It validates sources with the existing approval/license/hash gate, adds Porter
FTS5 search units, and atomically replaces only the specified output. It preserves
the legacy passage tables. Existing legacy API/index defaults stay unchanged.
The refs environment variable takes precedence; if absent, refs/render/read
validation falls back to `OPENAKASHIC_METHOD_EVIDENCE_INDEX`. An old index can
still validate already returned reads and references, but v4 source retrieval
returns `index_upgrade_required` until its normalized search units are built.
There is no query-time index mutation, URL fetch or model call.

Search units retain original identifiers and split camelCase/snake_case into
generic component tokens, preserving ordinary word frequencies. Query terms
are deduplicated; Porter stemming is handled by SQLite FTS5. Whole braced
functions and fenced code blocks remain atomic units. Distinct normalized
query-term coverage and unit BM25 ranks are combined by reciprocal rank fusion
with constant 60. Within each clause, candidates below half the largest distinct
term coverage are dropped. At most three candidates per explicit question and
one scenario candidate enter round-robin aggregation; explicit questions precede
the broader scenario. Final candidates remain capped at twelve.

Product scoping uses only approved metadata: the first product token in a pinned
version must also occur in its public source URL, and the query must explicitly
name exactly one such known product. A uniquely matching dotted version can
further restrict the pool, allowing compatible major/minor prefixes. Multiple
named products or an unrecognized product leave the pool unrestricted. A known
product with an unpinned requested version is flagged rather than relabelled as
verified. No product names, task IDs, answer terms or gold source IDs are built
into the algorithm. This conservative lexical anchor is not entity disambiguation
or semantic version compatibility proof.

The shared helpers are `search_terms(text)`,
`anchored_sources([(id, metadata), ...], query)` and
`anchored_source_ids(query, approved_index)`. Both anchoring helpers return
`(allowed_ids_or_None, scope_info)`; the first also works with a direct browser's
manifest IDs. `inspect_candidate_rank(query, index_path=...)` exposes offline
scope, terms, unit offsets and BM25/coverage/RRF diagnostics without a model call.
A direct-search baseline can use the same normalizer and metadata scoping;
automatic source prefetch remains the separate retrieval mechanism.

Before packing, a conservative lexical scanner expands overlapping braced
function/arrow-function and generic class-method declarations to whole frames,
including final returns after internal blank lines. Oversized detected frames
are omitted instead of split. Immediately associated block comments are retained
with a code declaration. Markdown prose is never scanned as a code function;
its fenced code is atomic instead. After retaining units, v4 adds at most one
nearby qualifier paragraph within the same Markdown heading section and does not
pad a code frame with sibling functions. This avoids filling the budget with
unrelated neighboring sections. Overlapping ranges merge into a single exact
contiguous source span. No LLM compression, paraphrase, code execution, task IDs,
answer keys or domain-specific method-name rules are used.

The scanner ignores ordinary quoted strings and line/block comments. It is not a
language parser: unsupported syntax, unbalanced code, template interpolation,
Markdown and languages without braces can defeat frame recognition. Undetected
structures remain paragraph-based. Nearby context may still be insufficient or
contradictory, and an entire relevant frame may not fit. Partial/uncertainty flags
remain explicit; v3 does not assert improved task success.

Source descriptors expose their approved public `read_url`, `total_lines`, and
`read_action`. Every item retains Unicode-character `start`/`end` and additionally
has one-based `start_line`/`end_line` plus
`read_action={id: canonical_source_id, start: start_line, lines: ..., unit:
"one_based_lines"}`. The action is capped at 160 lines per read; longer ranges
require another read. Character offsets must never be sent as line numbers.
The original source URL remains separate from the tool's canonical source ID;
neither is a local file path. Rendering revalidates this action/offset metadata.

The model selects already received IDs rather than copying quotations:

```json
{"q1":["ev_OPAQUE_ID"],"q2":[],"q3":["ev_ANOTHER_ID"]}
```

The host renders them with `app.research_evidence_refs.render_citations`:

```python
rendered = render_citations(
    selections, [actual_prefetch_packet, actual_read_packet],
    index_path="/external/method-evidence.sqlite3",
)
# rendered["evidence"] is the legacy-compatible array of
# {url, quote, supports, evidence_id, sha256, version, start, end, ...}.
```

Only the host retains and supplies these exposure packets. Never accept a packet
or rewritten registry from model output. For direct browsing, after an official
read has actually returned and its source hash has been checked, use
`register_read(source_url, sha256, start, end, quote, index_path=..., version=...)`.
It validates that exact read window against the approved local index and emits
the same canonical IDs for contained paragraph/function frames. A clipped read
is labelled `partial_read_frame`; it never expands into unseen source text.
Search snippets alone do not grant citation IDs. Direct and prefetch arms must
use this same resolver so quoting mechanics do not handicap the baseline.

The resolver accepts only IDs present in these actual host-held packets. It
rechecks the approved source metadata/version/hash, exact offsets/text and
canonical ID, rejects unknown, stale, tampered or ambiguous references, and hashes
each source body once per operation. It performs no URL fetch and no fuzzy quote
repair. Its `supports` array is the model's question selection;
`semantic_support=not_assessed` remains explicit. A separate grader or reviewer
must assess whether those spans support the answer and recommendation.

For a local host-side render without another model call:

```sh
PYTHONPATH=. python -m app.research_evidence_refs \
  --index /external/method-evidence.sqlite3 \
  --packet /external/actual-prefetch.json --packet /external/actual-read.json \
  --selections /external/selected-ids.json --output /external/rendered.json
```

Short model-selected IDs do not erase transferred evidence. Measure original
packet/context tokens, model usage, renderer latency, rendered final response
tokens and final response size separately. The renderer's `tokens` field counts
its full output JSON; rendering cost is not an extra LLM call. Actual billed
money and equal-quality success still require separate evidence.

### Publication metadata projection after evaluation

`public_projection(packet)` is a pure final serialization boundary. It deep-copies
the selected packet, removes nonpublic license fields and recounts the complete
public JSON. License metadata permits `spdx`, public `url`,
`reviewed_for_publication`, a validated public license-text `sha256`, and safe
`attribution`/`copyright`/`notice` strings. Operator-local pointers such as
`preserved_file` and other unknown license fields never appear in public API,
read-registration or renderer results. Attribution strings cannot contain local
file paths.

Projection happens after original packing: the space removed cannot admit extra
candidates or alter ranking, canonical IDs, quotes, hashes, ranges or read actions.
The renderer accepts host-held original or projected exposures by comparing their
public provenance, then emits public metadata only. Internal approved indexes
and frozen evaluation inputs are unchanged. On the nine evaluated Sol source
queries, the public API equals `public_projection(frozen_packet)` exactly; only
`license.preserved_file` and the response's counted `tokens` differ.

The benchmark retains originally observed packet/context and provider usage
counters. Recounted public-response tokens are not substituted retroactively for
measured usage, and original versus metadata-redacted public transport hashes and
sizes are reported separately. No new model run or equal-quality/cash-savings
claim follows from this privacy correction.
