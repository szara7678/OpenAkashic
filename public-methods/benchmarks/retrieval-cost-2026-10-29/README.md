# Source retrieval cost pilot ? 2026-10-29

Three existing diagnostic tasks, one fresh gpt-6-luna execution per condition: **nine runs**. This corrects the earlier no-retrieval comparison by requiring external evidence. It is still a bounded official-document pilot, **not a whole-web search evaluation or a new held-out task set**.

| Condition | Decisions /18 | Blind rubric /18 | Input | Cached within input | Output | Total | Model calls | Reference reads | Observed run seconds, sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct source search/read |17|15|131519|51328|3421|134940|10|15|66.77|
| Same-information flat methods |18|16|134033|83712|3258|137291|10|7|70.27|
| Complete method bundle |18|15|157999|77824|4542|162541|11|8|87.96|

**The 30% equal-quality token saving target was not met.** Bundle total tokens were 20.45% above direct source browsing and 18.39% above the same-information flat baseline. All calls are included; cached input is a subset, not added twice. Actual dollars, end-user latency, human expertise and production task completion were not measured. Timing is serial shared-host observation, not causal speed evidence.

## Conditions and identity

- Direct: autonomous keyword search over nine pinned official public sources; selected line ranges read through real HTTP and verified against frozen source SHA-256. Search is local and bounded, not Google/Bing or general Internet search. No oracle document IDs or quotes supplied to the candidate.
- Flat: six pre-existing curated method records derived only from those sources, identical hybrid retriever and full bundle content flattened as text.
- Bundle: the new additive `/research/api/methods/bundle` with complete stored methods, exact ID/version/fingerprint, conditions, steps, verification criteria, limitations and sources. Flat and bundle have the same 4096-token maximum, no mandatory second fetch, and explicit omission states.
- Same gpt-6-luna/medium, fresh Docker filesystem/home, no prior memory, host credential or source DB mounts, no unrestricted network; a per-run broker provides model inference and bounded references. No graph traversal. 8-model-call/12-read/180-second limits, cyclic arm order fixed before outputs.

The methods already existed in Korean; source originals are English. Preparation/translation/embedding were reused and are not free. This is not an isolated causal claim about graph representation, language or model routing. Only three distinct tasks, not 18 independent tasks.

## Failures and interpretation

Repeated lookups for source quotations missing from the stored records consumed model context. Fewer reference reads did not imply fewer model calls or tokens. The API now says explicitly that complete method content is not complete source evidence; missing original text requires following the original source, not repeating the same lookup. **That guidance was deployed after the evaluation and has not been measured in fresh model runs.**

Strict JSON validity: direct2/3, flat2/3, bundle3/3. Two delivered responses contain extra closing text. The table additionally parses the first complete JSON object without editing its values. This secondary parsing was introduced after observing the issue; strict failures remain recorded. The direct DuckDB answer contains one genuine incorrect boolean.

The preregistered quote rule passes0/3 in every arm. It mixes literal-source checks with a uniform two-source requirement and a6?18-word limit. Markdown/reStructuredText formatting, an actual paraphrase presented as a quote, overlong/short quotations, and semantically unrelated citations are distinguished in the audit. The two-source requirement is unnecessarily restrictive for the disabled-query guide. Do not use this failed metric as a general estimate of answer quality, and do not silently remove failed cases.

A separate Sol agent graded anonymized answers using the frozen condition/fix/uncertainty rubric. It found unsupported quote-to-claim links (for example cancellation evidence attached to cached-success claims) and incomplete repair guard/deprecation explanations. It is model review, not independent human ground truth. An evaluator packet retained an obsolete four-key schema; candidate prompts required citations as a fifth key. Original grades are retained; the erroneous schema complaint was removed from all nine, with **no numeric score changes**.

## Inspect and reproduce

`report.json` includes per-run actual usage, scores, citations, review issues and failures. `artifacts/` retains actual provider receipts, CLI usage, unmodified final answers, prompts and timing, with no credentials or reasoning transcripts. `protocol/` retains original task/gold; the actual candidate contract is in each frozen prompt. `source-manifest.json` has exact official URLs and hashes. `frozen-hashes.json` records64 inputs/runtime files; all were unchanged after execution. The retained input database/index and operator transport remain outside Git.

Run `python replay.py` here to recompute actual provider usage and exact answer content scores without a model or key. Source semantics and rendering-normalized quote review are not automatically validated by that replay. The earlier negative pilots remain unchanged.

A post-evaluation operator limitation opinion corrects the Streamlit full-app quote on live method `method_9de7657701024d8bba83793ef08c4887` version1. The original immutable method and frozen experiment are preserved; this is an evidence correction, not a new execution outcome.
