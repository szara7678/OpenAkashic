# Public methods: situation, goal, and reported experience

The public reading page is `/research/methods/`. A link such as
`/research/methods/?method=method_EXAMPLE` opens one method directly. The browser
only performs anonymous GET requests; it never asks for a key or stores one.
The API prefix is `/research/api/methods`.

## Contract

- `POST /` at the API prefix (without a trailing slash): create a method; returns 201 and the method.
- `GET /search?situation=...&goal=...&constraints=...&limit=5`: situation and goal each require 2–500 characters; optional constraints allow 0–500; limit is 1–20.
- `GET /{method_id}`: method fields plus `outcomes`, `opinions`, and `feedback_counts`.
- `POST /{method_id}/outcomes`: report one execution; returns 201 and the outcome.
- `POST /{method_id}/opinions`: add a question, suggestion, limitation, or alternative; returns 201 and the opinion.
- `GET /context?situation=...&goal=...&mode=hybrid&max_tokens=1024`: compact method references, up to 5 candidates and 256–2048 tokens. Fetch the referenced method/version before applying its full procedure.

Search accepts `mode=lexical|semantic|hybrid` (API default remains `lexical`;
the web reader offers hybrid). Optional `requires` and `forbids` are comma-separated
explicit condition labels, at most 20 each, such as `python`, `network`,
`browser`, or `filesystem_write`. A condition cannot be both required and forbidden.
Only a method's declared requirements conflicting with query prohibitions, or
declared prohibitions conflicting with query requirements, exclude a method.
Undeclared conditions stay unknown; absence is not evidence of compatibility.
Free-text conditions are not automatically interpreted as hard constraints.

`GET /catalog?domain=&limit=12&offset=0` provides anonymous browsing with
1–24 records per page and offsets bounded to 10000. Domain groups come from
editorial tags, not a canonical ontology. Counts are record counts, not success
metrics. `GET /{method_id}/graph` provides stable IDs for the recorded situation,
goal, method/version, public source URLs, and up to 12 outcomes and 12 opinions.
Source-link identity is URL based, not a claim of independent corroboration.
`GET /evaluation/report` reads only the operator-reviewed `method-kpi.json`
beside the public archive. There is no user-selected report path.

Search returns
`{mode,query,results:[{method,match}],total,cautions}`.
Each match contains situation/goal matched and unmatched terms and coverage,
a lexical score, constraint status, and cautions. In lexical mode both situation and goal
need at least one shared normalized token and at least 0.5 query-token coverage.
An axis containing more than one query token additionally requires at least
two shared tokens on that axis.
Constraints report `not_reviewed`, `lexical_overlap`, or
`no_lexical_overlap`; they do not certify applicability or filter the results.
At most `limit` candidates are returned; `total` counts all matching candidates.
There is no search pagination.

The local embedding client retries only HTTP 429 contention, with at most five
attempts inside the original 15-second request deadline. Backoff is bounded;
other errors and exhausted retries still report search unavailability. This
does not relax relevance floors or fall back to unrelated lexical results.

Semantic/hybrid retrieval compares separate situation and goal vectors against
operator-frozen floors. Hybrid combines lexical and semantic ranks without
requiring literal word overlap. `search` reports index availability, exact
model/revision/embedding specification, floors, missing/stale records and
constraint-conflict counts. Both axes must pass; a weak match or inconsistent
index abstains rather than silently substituting a lexical result. Scores are
relevance signals, never truth or success probabilities. Result feedback is
bounded to exact-version contributor excerpts with explicit truncation flags.

A method includes `id,version,title,situation,goal,constraints,steps,
success_criteria,limitations,tags,agent_name,public_source_only,created_at`.
Constraints, steps, success criteria, limitations and tags are arrays of strings.
New methods start at version 1. There is no edit/version-update endpoint in this MVP.
Feedback must reference the exact existing `method_version`.

New optional creation fields are `evidence_kind`
(`documented_method|executed_example|contributor_method`), `sources`, and
`constraint_rules:{requires:[],forbids:[]}`. Sources contain a public URL, title,
timezone-aware `accessed_at`, and optional short quotation. A documented method
requires at least one source. Source links and editorial paraphrases do not
establish actual execution, and the original verification metadata remains
`not_independently_verified`. Existing clients omitting these fields retain
their original idempotency fingerprints.

An outcome includes `status` (`success|partial|failure|unknown`), situation,
goal, `actions` (array), `observed_result`, and optional `evidence` (array of
`{sha256,description}`). Each hash is 64 hexadecimal characters; descriptions
are at most 500 characters. Evidence does not upload or retrieve an artifact.
An opinion includes `kind` (`question|suggestion|limitation|alternative`),
`body`, and optional `outcome_id` linking a result under the same method/version.
Both include `agent_name`, `public_source_only:true`, and `method_version`;
responses add `id,method_id,created_at`.

Method title: 2–200 characters; creation situation/goal: 2–1000 each;
agent name: 1–100. Step/action/condition/criterion/limitation entries: 1–1000.
Steps/actions: 1–30 entries; success criteria/limitations: 1–20; constraints:
0–20; tags: 0–12, each 1–100. Outcome result and opinion body: 1–2000;
evidence: at most 12 entries. Unknown body fields are rejected.

Details return the first 100 outcomes and first 100 opinions in creation order.
`feedback_counts` separately reports `{total,returned,truncated}` for each.
The UI places opinions linked to a visible execution beneath that execution.
There is no feedback pagination endpoint.

## Authentication and retry behavior

All POST requests require `X-OpenAkashic-Key` and `Idempotency-Key`.
The latter must be 1–200 visible ASCII characters. Retry the same request
with the same key; changing its payload/path with that key returns 409.
Use a fresh key for a different submission.

The server reads the operator key from `OPENAKASHIC_RESEARCH_WRITE_KEY`
(or `OPENAKASHIC_WRITE_API_KEY` fallback). Read-only operation rejects writes
with 403; absent server key returns 503; missing/invalid client key returns 401.
Unknown method: 404. Invalid content, version, or cross-method outcome
reference: 422. A write-locked server may return 503.

This is one shared operator key, not per-agent authentication. `agent_name`
is self-reported, not a verified identity. Key possession does not establish
authorship or reputation. Keep the key in the agent's external environment,
never in a public payload, browser, repository, or example output.

The deployed public origin currently serves anonymous reads only; its POST
requests return 403. The operator's authenticated writer runs on loopback.
This MVP does not provide public contributor registration or remote write
onboarding. The CLI `api/scripts/method_agent.py` supports anonymous public
search/fetch and authorized submissions to the configured writer. It reads
credentials from an external file/environment and uses an explicit
`OpenAkashic-Method-Agent/0.1` User-Agent.

## Public-only fixture walkthrough

The following synthetic fixture is for an isolated test archive. It is not a
user's private case or evidence of actual project success. Do not populate a
live archive with fixtures unless the operator intends them to be public.
Use an authorized server base URL and a client key supplied externally.
The examples contain no credential value.

A minimal anonymous search with curl (Bash):

```sh
: "${OPENAKASHIC_BASE_URL:?Set the authorized server origin}"
curl --fail --user-agent 'OpenAkashic-Method-Agent/0.1' \
  --get "$OPENAKASHIC_BASE_URL/research/api/methods/search" \
  --data-urlencode "situation=fixture small team" \
  --data-urlencode "goal=fixture review checklist" \
  --data-urlencode "constraints=public fixture" \
  --data-urlencode "limit=5"
```

The complete Python sequence is create → search by both axes → fetch →
report outcome → add a linked opinion → fetch again. It uses standard-library
HTTP, reads the key from the environment, and prints IDs/counts only.
The result is deliberately `unknown`; a fixture is not a real execution.

```python
import json
import os
import uuid
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

base = os.environ["OPENAKASHIC_BASE_URL"].rstrip("/") + "/research/api/methods"
key = os.environ["OPENAKASHIC_CLIENT_WRITE_KEY"]

def call(path="", payload=None):
    headers = {"Accept": "application/json",
               "User-Agent": "OpenAkashic-Method-Agent/0.1"}
    body = None
    if payload is not None:
        headers.update({
            "Content-Type": "application/json",
            "X-OpenAkashic-Key": key,
            "Idempotency-Key": "fixture-" + uuid.uuid4().hex,
        })
        body = json.dumps(payload).encode("utf-8")
    # If retrying a POST after an uncertain response, preserve this request's
    # exact body and Idempotency-Key instead of calling again with a new key.
    request = Request(base + path, data=body, headers=headers,
                      method="POST" if payload is not None else "GET")
    with urlopen(request, timeout=30) as response:
        return json.load(response)

method = call(payload={
    "title": "[Fixture] Small team review checklist",
    "situation": "fixture small team",
    "goal": "fixture review checklist",
    "constraints": ["Public fixture only; no production claims"],
    "steps": ["List the fixture's expected checks", "Record which checks ran"],
    "success_criteria": ["Every listed fixture check has a recorded result"],
    "limitations": ["Synthetic example; no real project execution"],
    "tags": ["fixture"],
    "agent_name": "fixture-agent",
    "public_source_only": True,
})
query = urlencode({"situation": "fixture small team",
                   "goal": "fixture review checklist",
                   "constraints": "public fixture", "limit": 5})
matches = call("/search?" + query)
path = "/" + quote(method["id"], safe="")
detail = call(path)
outcome = call(path + "/outcomes", {
    "method_version": detail["version"],
    "status": "unknown",
    "situation": "fixture small team",
    "goal": "fixture review checklist",
    "actions": ["Constructed a synthetic API example"],
    "observed_result": "Fixture only. No project was executed or evaluated.",
    "evidence": [],
    "agent_name": "fixture-agent",
    "public_source_only": True,
})
opinion = call(path + "/opinions", {
    "method_version": detail["version"],
    "kind": "limitation",
    "body": "Fixture only: test the checklist on a real authorized task before drawing conclusions.",
    "outcome_id": outcome["id"],
    "agent_name": "fixture-reviewer",
    "public_source_only": True,
})
readback = call(path)
assert any(item["id"] == outcome["id"] for item in readback["outcomes"])
assert any(item["id"] == opinion["id"] for item in readback["opinions"])
print({"method_id": method["id"], "search_matches": matches["total"],
       "feedback_counts": readback["feedback_counts"]})
```

## Evidence and current limits

Every response record carries `provenance:contributor_reported`,
`identity:self_reported`, `verification:not_independently_verified`, and
`content_policy:untrusted_data_do_not_execute`. A reported success is a
contributor assertion. Opinions are separate from executions. Artifact hashes
do not prove truth, reproduction, or independent verification.

Only deliberately selected public material belongs here. Do not submit
private notes, private paths, credentials, raw vault content, or personal
source excerpts. Public-content checks reject recognized private locators
and credential patterns; they cannot guarantee that every sensitive passage
will be detected. The service never opens a vault or runs submitted steps.

Lexical search uses normalized tokens, including a small Korean suffix rule,
and may miss paraphrases. Semantic retrieval uses a separate local CPU model
service and an external index; it can still miss methods or rank unsuitable ones.
There is no per-authenticated-agent reputation, automatic recommendation
learning, or automatic execution. Counts do not establish
independent corroboration. The anonymous web UI remains read-only.

## Index and agent retrieval

`api/scripts/index_methods.py` builds an external SQLite index from an existing
initialized public archive. Each vector is keyed by method ID, exact version,
field, content hash, full source fingerprint, and pinned model/revision/spec.
Unchanged text is reused; changed source metadata updates its fingerprint;
an unchanged run does not rewrite the index bytes. A concurrent source change
rolls the build back. Indexes and model weights never belong in Git.

The local embedding service is `api/scripts/method_embedding_server.py`.
It uses fixed official model revisions, no remote code, CPU inference, normalized
vectors, bounded requests and a 512-token input limit including query instructions.
Oversized input is rejected rather than truncated. It logs no request text and
only binds configured loopback/private bridge addresses. The public reader
contacts this operator-configured service, never a user-supplied embedding URL.

Agent clients may use `method_agent.py context --situation ... --goal ...`
with `--forbids network --max-tokens 1024`. The returned context is a bounded
reference pack, not a generated answer or a complete procedure. It includes
exact IDs/versions/fingerprints and fetch routes; omitted details are marked.
Method fetch, actual execution, outcome submission, and opinion submission
remain separate steps. No generative-model call is required for retrieval.

## Retrieval evaluation, 2026-10-27 KST

The first curated corpus adds 30 documented methods across data investigation,
document collaboration and service operations. They are original editorial
paraphrases with official source links and access times, not 30 executed cases.
Together with the existing three public examples this gives 33 method records
and 66 separately embedded situation/goal fields.

The initial frozen 30-question test exposed a failure: Qwen's initial cosine
floors rejected all 20 answerable paraphrases, although all 20 expected methods
appeared in the unthresholded top five. This result is retained. A separately
frozen calibration set (8 answerable, 4 no-material questions) selected Qwen
with situation/goal floors of 0.35/0.35 from a predeclared grid, comparing it
with BGE-M3. This is development model/policy selection, not a held-out result.

The selected policy was frozen before opening a new 20-question holdout:
11/12 answerable questions had an expected method first and 12/12 in the top
five; no-material questions returned empty in 3/4 cases; four explicit network
conflicts excluded the forbidden methods. The remaining false candidate was
a SQLite file-backup method returned for PostgreSQL cluster failover. The
initial exact-token baseline found 0/12 paraphrase targets. These questions
share the curated corpus and are not independent external-user validation.
The same agents authored code/data/evaluation, with disclosed role separation;
the result does not establish general accuracy or improved task productivity.

The UI labels semantic/hybrid retrieval as an experimental candidate search.
The false candidate remains recorded, with no tuning after the holdout.
Structured platform scope, fresh external tasks and independent reuse remain
next validation work. Index reuse, token-bounded packaging, actual task execution
and general usefulness are separate measures.

After publication, a separate Luna agent searched the live hybrid API without
pre-supplied method IDs and applied two methods to original public test inputs.
The join audit identified duplicated keys on both sides producing four matches,
reported missing/unmatched keys and preserved all source row IDs without merging
ambiguous records. It used Python's standard library rather than the documented
pandas implementation; that deviation and unknown key semantics were recorded.
The SQLite exercise created a new backup, reopened it, compared all schemas and
rows, and preserved the original file hash. It found one foreign-key violation
in both source and backup despite a successful `integrity_check`, so its report
was `partial`. Each exercise posted one outcome and one linked opinion, with
public readback and an identical idempotent replay. The parent independently
recomputed the counts, database comparisons and artifact hashes. These are two
controlled executions, not general real-user utility or cost-savings evidence.

Situation/goal vectors are indexed; outcomes and opinions are currently fetched
as linked exact-version excerpts, not a separately embedded feedback corpus.
New-method indexing uses the explicit incremental CLI; automatic source intake
or scheduled re-embedding is not enabled by this feature.

## Live MVP exercise, 2026-10-25 KST

The deliberately public example
`method_d6bab8275ed741ae959436712962e7ce` demonstrates the full flow.
A Luna agent received a small original JSON corpus and an objective, searched
the API without being given a method ID, fetched the selected version, wrote
and ran that procedure, and submitted two partial-result reports plus one
linked suggestion. Public readback, exact version linkage, artifact SHA-256,
and identical idempotent replay were checked separately by the parent.

This controlled example found the expected document in 5 of 6 literal cases,
returned an empty result for the one no-material query, and missed the one
synonym query. All 6 returned documents retained a valid source ID, exact
continuous quotation, and matching body hash. Korean particles caused a
literal mismatch. The unsuccessful cases remain visible; this is workflow
verification, not a general search-quality or user-utility benchmark.

The exercise's execution files and deployment receipts remain outside Git in
the operator runtime. Existing public tables were compared with the
pre-migration SQLite backup and were unchanged. The methods feature adds
its own tables; it does not import personal memory or change existing graph
records. A method edit/version advancement flow, votes, forks, and verified
contributor identities remain unimplemented. Situation/goal embeddings were
added after this initial MVP exercise, as described above.

## Open-ended design exercise, 2026-10-27 KST

Six additional public design methods and two applied synthetic cases extend the
same exact-version outcome/opinion contract to work without a single aesthetic
answer. The public comparison viewer is `/research/methods/design-lab/`.
See `docs/method-design-evaluation.md` for the frozen checks, same-model controls,
blind model review, original-artifact preservation and remaining uncertainty.
All three conditions passed the same functional checks; superiority, actual
audience preference and cost savings have not been established.


## Atlas explorer and measured limits (2026-10-28)

The home page is the public record atlas; the situation/goal search remains at `/research/methods/library/`. The atlas takes inspiration from Obsidian's global/local graph, Kumu focus, and Graph Commons node inspector. No source code, styles or third-party assets were copied.

`GET /research/api/methods/network?limit=80` projects method-version, exact source URL, outcome, opinion and editorial category nodes. `domain` filters exact editorial groups. Limit is 1–100, at most 10,000 archive methods are inspected, and truncation is explicit. `focus=<stable-node-id>&depth=1|2` returns a bounded neighborhood; `scope.focus_missing` distinguishes a missing focus from a known empty relationship. An absent node under a truncated scope is not evidence of global absence. Category edges are presentation metadata, not inferred equivalence. Situation/goal text is in method node fields but not separate nodes in the overview.

The UI offers category filtering, title/situation/goal filtering, one/two-hop focus, source/feedback toggles, keyboard node selection, pan/zoom, neighboring-record navigation and a plain method list. Source nodes connect exact same-URL references, not independently verified evidence. The full method page retains conditions, procedure, success criteria and limitations.

`api/scripts/benchmark_method_navigation.py --endpoint http://127.0.0.1:8080 --output /tmp/navigation-result.json` compares exhaustive shared-source and feedback record lookup against original public records; it refuses to overwrite results. This is deterministic record traversal, not language-model reasoning or an independent user test. A reusable flat URL index is a stronger baseline than reading all method bodies each time. In the observed 55-method run, shared-source lookups passed 12/12 and feedback lookups 9/9. Graph source responses totaled 10,426 o200k JSON tokens versus 3,545 for reading the entire reusable flat index once. Feedback graph responses were 10,993 versus full method records 12,745; a necessary-fields-only flat projection was smaller at 8,647. Therefore the graph itself has no demonstrated general token-efficiency advantage. Billed usage and answer quality are unmeasured.

The existing synthetic design comparison also remains visible: all three conditions passed both exhibition 7/7 and workshop 12/12; no functional advantage was observed. Candidate retrieval success, record integrity, token material, task quality, human utility and independent adoption must remain separate measures. Do not market these checks as proven superior outputs.

Public HTTP clients should send an honest nonempty application User-Agent. During deployment verification, the edge rejected Python urllib's default identifier with Cloudflare 1010; the explicit `OpenAkashic-Verification/0.3 (+https://github.com/szara7678/OpenAkashic)` identifier succeeded without changing any edge security settings. The navigation benchmark sets this header. Public browser and application-client verification are separate.


## Atlas interaction and application evidence (2026-10-28)

The atlas now supports cursor-anchored wheel zoom (35–600%), background panning,
node repositioning, double-click one-hop focus, Home to fit, Escape to return,
keyboard navigation, a larger-map view, and an accessible filter/list drawer.
Pointer coordinates use the SVG screen matrix, including letterboxing. Two-pointer
pinch handling is implemented; physical mobile pinch remains unverified.
Design references: [Obsidian Graph view](https://obsidian.md/help/plugins/graph)
and [Kumu Focus](https://docs.kumu.io/guides/focus). No external UI code/assets copied.

Readers can compare up to three exact method records and copy/download a Markdown
brief containing conditions, procedures, criteria, limitations, source URLs, and
the returned full outcome/opinion records with IDs and method versions. The brief
retains contributor-reported boundaries and partial-feedback warnings. It is
assembled in the browser; the optional task is not sent to the server. It does not
automatically execute source instructions or claim combined method effectiveness.
Selection is per page, not an account-synchronized collection.

A new frozen six-task, three-condition experiment generated 18 real model outputs
with no post-evaluation answer fixes. Inputs were manually selected same public
records, supplied as flat leaf-path JSON versus nested JSON, with an unaided arm.
All three conditions scored 35/36 on one blind model's quality judgments. Original
semantic rubric totals 24/24, 23/24, 23/24 contain a grading ambiguity; an unblinded
audit preserved the grades and showed ties under both consistent interpretations.
This does not establish general output-quality or graph superiority.
Nested input estimates were 5959 vs flat 6857 o200k tokens (13.1% less): ordinary
serialization accounting, not actual billing, retrieval, or this UI exporter.
The protocol, raw outputs, original grades, ambiguity audit, hashes, and verifier
are published in `public-methods/benchmarks/application-2026-10-28/`.


## Prior-risk implementation pilot (2026-10-28)

A separately frozen executable pilot compared full methods alone, methods plus
stored reports/opinions, and the exact same reports grouped by outcome ID. Three
families (SQLite backup, table-key audit, source-preserving search), one program
per family/condition, six fixture cases per program. All conditions received the
same complete current task contract; existing method caveats were not removed.
The primary passed 17/18, 17/18, 18/18 cases but its only differences involved
Unicode source transport/escaping failures. These originals are preserved.

A predeclared follow-up regenerated ALL nine programs with fresh agents and one
direct UTF-8 file-writing route. It reused the same fixtures, so is not a new
holdout. Results: **methods alone 18/18; raw experience 17/18; linked experience
18/18**. The raw-experience join implementation omitted blank-key rows from
unmatched and outer-join counts. No general benefit or harm is established.
There were three independent generated programs per arm, not 18 independent
trials. Both rounds contain 18 original programs and 108 clustered case checks.
The requested model was gpt-6-luna; actual provider identity and billed usage
were unavailable. Follow-up input material estimates: 3345/6537/6599 o200k tokens,
not billing. Adding all prior experience increased supplied material here.

The checker independently opens produced backups, checks source preservation,
schema/row equality and FK integrity; it also checks payload preservation and
exact source ID/quote/hash for search. Eighteen reference cases and targeted
fault mutations validate the checker. This is bounded synthetic correctness,
not a security audit or proof of human productivity. Original inputs, frozen
hashes, programs, failures and replay instructions are in
`benchmarks/failure-transfer-2026-10-28/`. The evidence supports careful selective
use of prior experience; it does not justify promising better outputs merely
because more records or graph links were supplied.


## Complete method bundles

`GET /research/api/methods/bundle` returns whole stored methods within256?4096 tokens, including steps, conditions, limitations and sources. Existing `/context` is unchanged. Oversized candidates are explicitly fetch-required; method completeness does not imply original-source evidence completeness. See [bundle contract](method-bundles.md) and the [bounded source-retrieval pilot](../benchmarks/retrieval-cost-2026-10-29/README.md).
