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
