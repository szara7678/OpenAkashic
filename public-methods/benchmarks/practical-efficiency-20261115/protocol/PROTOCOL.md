# V2 common initial task-context correction

This is a separate cohort. The original freeze and two pilot runs remain intact;
its remaining fourteen runs will not launch. That pilot passed transport and
mechanical checker gates, but the OA query used a literal instruction to read
TASK.md and a generic goal. Its empty bundle and cheaper fallback do not establish
OA method benefit. Do not relabel the original pilot as a successful OA test.

The only candidate behavioral change is to append the exact task text from
TASK.md to the initial prompt in BOTH arms, so the model knows the task before
issuing its first retrieval query, including a same-batch cat/retrieval call.
Both arms also receive identical generic guidance to query the actual task
situation and desired outcome rather than filenames or task-wrapper instructions.
The engine, public snapshot/index, tasks, checker, model, binary/image, tools,
limits and schedule algorithm remain the same. No target documents or answers
are supplied to either arm. This is a common input-interface correction, not
engine tuning from held-out outputs.

Parent review of the v2 pilot must inspect the first OA query situation/goal for
actual task meaning, then distinguish complete method delivery, actual read and
applied steps. A genuine task-specific archive miss and honest web fallback may
be valid task behavior, but cannot by itself demonstrate OA method benefit. Do
not launch the remaining fourteen without explicit parent review approval.

The unchanged base protocol follows.

# Fresh held-out nativeCLI comparison, 2026-11-15

Prepared, not launched. Parent approval is required before the pilot and one
resource/receipt review before the remaining fourteen runs. Freeze only after
candidate retrieval code and held-out task/checker files are final.

- Four fresh tasks, two repetitions, two arms = sixteen scheduled runs; eight
  matched pairs. Seed 20261115 shuffles task/repetition pairs; alternating arm
  order balances first position. Run sequentially to avoid timing contention.
- Same gpt-6.1-sol medium, signed-in existing auth via trusted host broker,
  installed Codex binary, oa-practical-eval:20261114 image digest, runtime,
  dependencies, fresh HOME, common instructions and tools in both arms.
- OA-first arm alone may access OA routes. Web-first uses genuine native live
  web_search freely with no preselected corpus. Both can fetch public URLs;
  neither candidate receives credentials, API keys or private sources.
- Shared workflow clarifies actual exposed tools, file-writing, early artifact
  completion and evidence sufficiency. This is a new cohort, not a clean causal
  estimate against v4. Current frozen public v3 method data also differs from
  the older v2 data; retain all earlier cohorts unchanged.
- NativeCLI system/tool overhead remains common, and first provider requests
  are measured with actual usage. Do not attribute whole savings versus old
  cohorts to retrieval. No framework switch or surrogate web search is used.
- A full OA bundle counts as the complete method read. The reusable read-cache
  returns an exact fingerprint receipt and artifact on repeated body reads,
  after fresh server validation. New content/version, unknown fields or explicit
  refetch return full text; current outcomes/opinions/counts always pass through.
- Broker OA reads execute the candidate ASGI app against the frozen read-only
  public database/index. There is no live OA_BASE fallback. Code/snapshot/index
  and harness files are hashed before launch and checked before every run.
- Common limits: 240 seconds candidate wall time, 24 public retrieval requests,
  12 provider requests; new admission stops after 200000 already observed
  provider tokens. In-flight responses are never token-clipped. Provider streams
  are drained after client disconnection; receipt collection is outside the
  candidate wall clock. A resource failure remains a failure, never success.
- Each admitted request gets an immutable ordinal, received/forwarded body
  hashes, section character counts, stable response ID, complete stream hash,
  completion status and actual usage or null. Missing/incomplete usage is unknown,
  never zero. Both cached and uncached input, output and total tokens are recorded.
- Freeze all sixteen rows before pilot. If receipt/auth/live-web/resource gates
  fail, stop execution and retain the planned unrun rows as missing; no selective
  replacement. Pilot review may stop the cohort, never silently change its limits.

Quality and efficiency gates, fixed before model results:

1. Report every scheduled run, completion, failure and missing row. Score actual
   artifacts and README with the held-out checker and blinded rubric; no points
   from merely finding or citing a method. Evidence-fit/application must be real.
2. Quality is maintained only if OA full successes are at least Web overall, no
   material unsupported claim occurs in any jointly successful matched pair,
   correctness and evidence-fit do not fall within any such pair, and mean
   four-dimension total does not fall.
3. Primary token and wall-time comparisons use the SAME set of jointly full
   successful pairs. Both must decrease; disclose n and individual pairs, all-run
   costs and unknown accounting. Do not select a different subset per metric.
4. Eight matched pairs provide limited uncertainty information, not formal
   general noninferiority or proof of user utility. Mechanistic fixed-query
   replay without models is a separate result, not billed-token/quality proof.

No source data, service runtime or deployment is modified. Only isolated public
snapshots, external experiment files and the approved candidate worktree change.

The cache term already_read denotes a complete method delivered by the trusted
candidate client. It does not establish model attention or application. Verify
fullbody visibility in native command stdout (including truncation) and actual
applied steps in artifacts before scoring application. Raw upstream OA responses
and client-presented bodies/receipts are recorded separately with byte counts and
hashes. Local presentation logs are corroborated by native stdout, not treated as
independent evidence that the model read the source.

The immutable heldout/criteria.json and ACCEPTANCE.md define primary strict
objective success. SECONDARY_RUBRIC.md preserves the earlier four 0..2 dimensions
for separate blinded artifact review. Both are frozen before results. Every entry
in heldout/SHA256SUMS is verified before freeze and each run; these hidden files
never enter candidate mounts. Reviewers see redacted execution commands/results
without arm, retrieval output, time or usage, while surviving citation clues are
declared. The quality gate includes the per-pair strict nonworse conditions, not
only the count of checker-passing solutions.

The 125-second absolute provider transport deadline and 130-second drain limit
are new shared harness accounting bounds. V4 used a 120-second per-read socket
timeout, so these limits are disclosed as a cohort change. They are distinct
from token clipping: an incomplete/deadline response has unknown usage and fails
the accounting gate. No incomplete request is assigned zero tokens.
