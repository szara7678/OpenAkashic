# Secondary artifact-quality rubric, fixed before candidate results

Preserve the held-out strict criteria and checker as primary objective criteria.
A full success also requires actual verified execution, a normal final response,
and no major unsupported claim. OA use/retrieval is never a quality point.

For compatibility with the earlier artifact assessment, two independent blinded
reviews score each anonymized task/output from 0, 1 or 2 on each dimension:

- correctness: 0 materially wrong/missing, 1 partially correct with a material
  gap, 2 meets the explicit task semantics and supported behavior.
- evidence_fit: 0 material unsupported/mismatched technical claims, 1 partial
  support or minor citation gap, 2 actually cited primary evidence supports the
  claims and relevant version/conditions; retrieval alone earns no credit.
- limitations: 0 overclaims outcomes or omits material scope, 1 incomplete scope
  or boundary discussion, 2 states actual verification limits and relevant
  failure/concurrency/format/data boundaries accurately.
- artifact_usability: 0 missing/unusable deliverable, 1 runnable with material
  missing documentation or reproducibility gap, 2 coherent runnable artifact
  and reproducible actual verification command/result in README.

Reviewers see task, anonymized artifacts, and redacted actual execution commands
and results. Hide arm, timing, token usage, retrieval command/output and identity
mapping. Preserve relevant source citations for evidence review; declare surviving
source clues instead of claiming proven blindness. Reviewers may verify cited
primary sources, but do not search for experiment results. Reasons must identify
specific files/lines for material problems. No output earns zero. Any review
resolution is documented; do not change rubric thresholds after results.

Prespecified quality gate: OA full successes >= Web overall; within every jointly
strictly successful pair neither correctness nor evidence_fit may decline, and no
material unsupported claim may occur; mean four-dimension total may not decline.
Primary token and wall-time comparisons use exactly the same jointly strictly
successful pairs, with both metrics decreasing. Report all pair dimensions and
all scheduled runs, including costs, failures, unknowns and missing runs; no metric
uses a selectively favorable subset. Failure of any gate precludes the claim that
quality is maintained while tokens and time both improve.
