# Frozen ten-method retrieval diagnostic

Six exact OA queries were replayed against the same frozen ten-method archive,
index, model revision/specification and .35/.35 floors. Six local embedding
requests were made; no generation, benchmark rerun or production/configuration
change occurred. The additional no-floor inspection reused those vectors in
memory, retained subject/scope/constraint checks, and was never a candidate policy.

All six reproduced bundles match the logged JSON. Packing caused none of the
four empty results: each search had zero eligible candidates and omitted zero.
The two returned ReportLab methods were complete, 956-token bundles within the
2048-token budget.

- Documents r1/r2: ReportLab similarities are .566393/.562239 and
  .535412/.585800, above both floors. They are nevertheless excluded by two
  independent automatic subject/topic checks: `pdf` is recognized but the title
  subject `reportlab` is unmentioned, and one axis has no non-subject lexical
  overlap (r1 goal, r2 situation). Removing floors alone still returns zero.
  The PDF-extraction method also passes both semantic floors but has no required
  non-subject lexical topic overlap; its procedure is extraction rather than
  the requested generation task. High similarity is not verified applicability.
- Analysis r1/r2: no recognized subjects activate lexical recall. The
  missingness method scores .295187/.383247 and .346746/.381996; the
  statistical-design method scores .306294/.370389 and .290977/.398631.
  Each fails the situation floor. ReportLab passes both in r1 (.354163/.370629)
  despite being unrelated to the requested HTML analysis.
- Design r1/r2: planning scores .205141/.328962 and .200401/.258677, below
  both floors. The unrelated ReportLab record scores .349435/.375811 in r1
  (excluded) and .360885/.366632 in r2 (returned). No recognized subject
  constrains that semantic-only path. This is an observed near-threshold
  eligibility change, not evidence that the returned method is suitable.

All index entries were current, retrieval was ready, explicit domain/product
parameters were absent, and no structured constraint conflict excluded a method.
Empty declared condition tags mean no declared conflict, not environment review.

The queries are English compound tasks and the indexed situation/goal summaries
are Korean. The PDF lexical gate has a measured cross-language overlap failure.
No translated/shortened-query or tokenizer control was run, so the embedding
scores cannot be causally assigned to length or cross-language quality alone.
Source coverage is also partial: these are ten extracted procedures, not the
full six skills' capability catalog. This audit diagnoses retrieval and packing;
it does not regrade generated artifacts or establish method effectiveness.

No thresholds or guards were tuned on this cohort. Any next retrieval change
needs a new held-out evaluation. Full axes, all-corpus and actual eligible ranks,
constraints, subject evidence and in-memory sentinel results are retained in
`retrieval-diagnostic.json`. IDs belong to this isolated frozen snapshot.
