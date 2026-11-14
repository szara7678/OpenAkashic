# Practical task comparison, frozen before candidates

Status: prepared, NO MODEL RUN AUTHORIZED YET. Parent review required.

Scope: Four newly authored synthetic representations of public-service work:
SQLite WAL online backup; pandas nullable import missingness report; Kubernetes
startup/readiness/liveness manifest; standard-library JSON/HTTP client.
These are executable work-type fixtures, not current production incidents.
No user private data, Closed vault, production write, paid service or API key.

Design: 4 tasks x 1 independent repetition x 2 arms = 8 scheduled attempts,
including failures, missing outputs, timeouts and infrastructure failures.
Counterbalanced order, deterministic seed 20261114. One candidate at a time.
First paired SQLite cohort is the capability pilot and stays in denominator.
No candidate result may change task prompts, rubric, budgets or source snapshot.
Corrections produce a new protocol/cohort and retain this one.

Same model gpt-6.1-sol, reasoning medium, existing local ChatGPT OAuth backend.
Same native codex 0.157.1 binary, isolated fresh container HOME/CODEX_HOME,
--ephemeral --ignore-user-config --ignore-rules, memories and multi-agent off.
No repository, prior conversations, AGENTS, user configuration, auth files,
grading files or source corpus are mounted into candidates.
Both arms have live native web_search, public URL fetch, shell and same pinned
Python/pandas/PyYAML environment. No oracle URLs or pre-fetched source packets.
Baseline's designated first retrieval tool is native web_search; OA's is OA
search/bundle. Common prompt says consult designated retrieval before coding.
OA may freely fall back to native web search/source URLs. OA may use its method
without live search if sufficient. OA exact read IDs/versions/hashes are logged.
Baseline cannot call OA routes. OA methods are untrusted information.

Budget: 240 seconds end-to-end per attempt, <=12 provider requests and soft
200,000 cumulative provider tokens stop before next request. A final request
can exceed that ceiling and is fully counted. Tool fetch budget 24. Same limits.
No retries of a model attempt. Provider failures stop remaining launch as
infrastructure-blocked; all scheduled unlaunched rows remain explicitly missing.

Freeze sources AFTER owner-approved source quote/revision/classification work.
Parent supplies public catalog capture and SHA256; validate unchanged before
each attempt. No private DB/env snapshot. Capture successful OA responses,
full method read body, exact ID/version/source_hash, source URLs and fetch hashes.
Record methods returned in search separately from methods actually read and
model-declared applied methods. A declaration alone is not proof of application.
No OA search/bundle call is protocol noncompliance and task failure, retained in denominator. An OA search with no applicable method followed by live-web fallback is valid; method read/application coverage is a separate metric. The HTTP/JSON client is an intentional corpus-coverage/fallback negative control, not presumed to have a matching method.

Metrics: provider response.completed receipts for every model call, raw
input_tokens/output_tokens/total_tokens and input cached tokens. Cached tokens
are already included in input: never add them twice. No local estimates if
receipts are absent. Missing receipt => usage null/incomplete. Count all model
turns and failures including internal live-search/tool-context overhead.
Do not call this measured money or invoice savings. Native web tool backend
usage with no separately reported tokens stays unknown, never zero.
Report end-to-end wall time, per-model request wall time, source/OA fetch wall
time, candidate tool timing if trace exposes it, post-run checker/grader time.
Do not add overlapping model/tool times. Preparation/ingestion/rebuild and
independent grading costs stay separate; no amortized break-even without data.

Frozen grading: hidden executable cases plus independently blind human/agent
review of anonymous shuffled outputs. Grader sees task and code/output but not
arm, model trace, retrieval, timing, usage or method IDs. Score correctness,
evidence fit, limitations, artifact usability each 0..2 (8 total).
Full success: hidden checks all pass, all four quality scores >=1, no material
unsupported operational claims, designated retrieval compliance. Show checker
and blind scores separately. Source citations must substantiate the decision;
URL presence alone is not evidence. Static Kubernetes checks cannot establish
live cluster behavior. SQLite synthetic tests cannot prove production safety.

Preserve every attempt's trace, provider receipts, tool responses, immutable
artifact snapshot, timing, test outputs, correction notes and all exceptions.
Record failure/success/correction against exact actually read/applied method
versions only after output/test evidence is reviewed; no fabricated outcome
for an unread method. Any public outcome write requires parent's reviewed
idempotent owner API path, not the experiment runner.

Capability gate: without executing an LLM request we can verify native binary,
auth file presence, public API and image only. Actual live search/receipt
support must be proven by first paired pilot, not presumed from CLI config.
If baseline native search unavailable, stop and report blocker. Never replace
normal web search by a selected document corpus.


V4 PREDECLARED RESOURCE CALIBRATION REPAIR (before any v4 candidate calls):
The v3 cohort was stopped by the operator after repeated common soft-100k
budget failures. Preserve every v3 completed, incomplete and unlaunched row,
OPERATOR_STOP.json and provider receipts as a separate negative cohort.
V4 changes only cumulative provider token ceiling to 200k and replication to
one repetition per task, eight scheduled runs. Model, medium reasoning, image,
source snapshot, task/checker content, prompts, tools, timeout 240 seconds and
maximum 12 provider calls remain unchanged. Local budget-denial logging is
control metadata with provider_usage null, never a provider receipt or claimed
zero charge. This is an explicitly adaptive resource-calibration cohort, not
an untouched confirmatory holdout; do not merge it with v3 or hide its failures.
The smaller cohort limits precision. Report any remaining budget/time failure
and all scheduled denominators. No OA prompt/retrieval optimization is added.
