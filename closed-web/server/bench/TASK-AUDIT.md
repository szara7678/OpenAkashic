# OpenAkashicBench Task Audit

Date: 2026-04-25  
Scope: `closed-web/server/bench/tasks.yaml` 17 tasks  
Question: which tasks remain fair and signal-producing once both conditions use **real CLI agents with real web access**, differing mainly by whether OpenAkashic MCP is connected?

## Executive summary

- The current task set mixes three different benchmark intents:
  - public/control tasks that any capable CLI agent should solve
  - OpenAkashic-public workflow knowledge tasks that both conditions may solve via docs/web, but `cli_openakashic` may do more directly
  - insu-private environment tasks that only a connected OpenAkashic vault can answer precisely
- For the new CLI benchmark, the strongest primary signal will not come from the current private topology tasks alone, because they conflate "has OpenAkashic" with "has insu's private vault".
- `standard` remains useful only as a historical simulation baseline. It should not be treated as the real generic-tools comparison.
- Recommended split for v0.7:
  - `tasks-v0.7.yaml`: 10-12 fair CLI-harness tasks
  - `tasks-private.yaml`: insu-specific/private-memory tasks such as IchiMozzi deployment and home-server triage

## Task-by-task audit

### `domain_jlpt_gen`

1. Prompt clarity: clear. The user asks for a concrete artifact with explicit formatting constraints.
2. Expected outcome fairness: fair in isolation. A capable agent can produce an N4 fill-in item from general knowledge alone.
3. Hallucination trap realism: realistic. Korean prompt leakage, wrong format, and level mismatch are common model failures.
4. Rubric balance: currently imbalanced. It assumes OpenAkashic should help because IchiMozzi has internal notes, but the expected outcome itself does not require private knowledge.
5. CLI harness suitability: weak. With real CLI web access, both conditions should usually pass. The current `openakashic` regression in `report-stage6.md` looks like a **misleading retrieval problem**: the MCP returned a non-fill-in JLPT note, and the model followed it too literally instead of falling back to parametric generation.
6. Proposed changes: revise or drop from the primary signal set. If kept, make it an explicit control task and remove the implication that OpenAkashic should outperform.

Verdict: `Revise as control`, not a primary differentiator.

### `onboarding_openakashic`

1. Prompt clarity: clear.
2. Expected outcome fairness: unfair for a public CLI benchmark. It requires `personal_vault/projects/personal/openakashic/README.md` and local path conventions that are insu-instance-specific.
3. Hallucination trap realism: realistic for agents that invent paths, but still anchored to a private environment.
4. Rubric balance: under-claim is penalized, but over-claim is much easier for baseline because the prompt asks for exact internal paths.
5. CLI harness suitability: low for public benchmark, high for private-instance regression testing.
6. Proposed changes: move to an `insu-private` subset, or rewrite as a public-doc onboarding task:
   - ask for "how to start using OpenAkashic MCP" based on public docs
   - do not require private vault paths

Verdict: `Move to insu-private subset`.

### `triage_ichimozzi_500`

1. Prompt clarity: clear.
2. Expected outcome fairness: unfair for public CLI comparison. Exact container names and stack order depend on insu's private deployment notes.
3. Hallucination trap realism: realistic. EC2/nginx hallucinations are common.
4. Rubric balance: reasonable inside a private benchmark, not in a public/fair benchmark.
5. CLI harness suitability: good only if the explicit goal is "does OpenAkashic recover private operational memory?"
6. Proposed changes: move to `insu-private` subset. If a public version is needed, rewrite around a public incident playbook with attached docs or repo-visible topology.

Verdict: `Move to insu-private subset`.

### `ichimozzi_deploy`

1. Prompt clarity: clear.
2. Expected outcome fairness: unfair for public CLI benchmark. It depends on insu's actual deployment topology and operational notes.
3. Hallucination trap realism: realistic. EC2/PM2/AWS assumptions are common failures.
4. Rubric balance: balanced only if private-vault access is intentionally under test.
5. CLI harness suitability: strong private-memory signal, weak public benchmark fairness.
6. Proposed changes: move to `insu-private` subset. If retained publicly, rewrite to a repo-local deployment target whose commands are visible in the repo.

Verdict: `Move to insu-private subset`.

### `general_web_fact`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: low signal because both `cli_baseline` and `cli_openakashic` have real web access and should usually pass equally.
6. Proposed changes: keep as a sanity/control task, but not as a headline differentiator.

Verdict: `Keep as control`.

### `memory_roundtrip`

1. Prompt clarity: clear in the current runner, but semantically ambiguous for stateless CLI agents.
2. Expected outcome fairness: not fair for the new CLI benchmark as written. A one-shot stateless CLI agent without persistent memory can still "pass" by echoing within the same session, while a read-only CLI baseline cannot meaningfully demonstrate durable memory.
3. Hallucination trap realism: realistic for simulated tool conditions.
4. Rubric balance: imbalanced under CLI conditions because "save then immediately recall" is not the same as persistence.
5. CLI harness suitability: poor in current form. It does not cleanly distinguish durable memory from short-context recall.
6. Proposed changes: replace with a persistence-contract task:
   - require an actual durable write target
   - explicitly reward "I cannot persist this without a memory tool" for baseline
   - optionally validate writeback artifact path in `cli_openakashic`

Verdict: `Rewrite heavily` or remove from v0.7 primary set.

### `busagwan_sagwan_roles`

1. Prompt clarity: clear.
2. Expected outcome fairness: unfair for public CLI comparison. The terms are instance-specific and private unless surfaced in public docs.
3. Hallucination trap realism: realistic.
4. Rubric balance: good for private knowledge retrieval, not for general benchmark fairness.
5. CLI harness suitability: good only in an insu-private subset.
6. Proposed changes: move to `insu-private` subset, or rewrite into a public architecture question based on public docs.

Verdict: `Move to insu-private subset`.

### `coding_python_bug`

1. Prompt clarity: very clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: useful as a control/sanity task. It should pass in both conditions.
6. Proposed changes: keep as-is.

Verdict: `Keep as-is`.

### `coding_sql_index`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: useful as a control/sanity task.
6. Proposed changes: keep as-is.

Verdict: `Keep as-is`.

### `daily_agenda`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic but easy.
4. Rubric balance: balanced.
5. CLI harness suitability: low signal. Real CLI agents should both pass easily.
6. Proposed changes: optional control only. If task count needs trimming, drop before dropping coding controls.

Verdict: `Optional control`.

### `daily_email_rewrite`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: moderate only as a writing control. It will not distinguish OpenAkashic access.
6. Proposed changes: keep one of `daily_agenda` / `daily_email_rewrite`, not both, if the v0.7 set needs to stay compact.

Verdict: `Keep one writing control`.

### `multihop_synthesis`

1. Prompt clarity: clear.
2. Expected outcome fairness: unfair for public CLI comparison. Exact systems and names are private to insu's deployment.
3. Hallucination trap realism: realistic.
4. Rubric balance: okay for private-memory retrieval, not for public fairness.
5. CLI harness suitability: good in an insu-private subset, weak for the primary CLI benchmark.
6. Proposed changes: move to `insu-private` subset. If a public multihop task is wanted, base it on public OpenAkashic docs spanning multiple pages/tools.

Verdict: `Move to insu-private subset`.

### `review_workflow`

1. Prompt clarity: clear.
2. Expected outcome fairness: mostly fair. The required behavior is documented in the public OpenAkashic guidance and repo instructions.
3. Hallucination trap realism: realistic. `dispute_note` vs `review_note` confusion is plausible.
4. Rubric balance: balanced. It checks correct tool use without requiring hidden state.
5. CLI harness suitability: good. `cli_baseline` can use web/repo docs; `cli_openakashic` can potentially answer more directly from connected knowledge. The signal may be modest, but the task is fair.
6. Proposed changes: keep, but explicitly allow answers derived from public docs instead of implying private vault access is required.

Verdict: `Keep as-is`.

### `list_reviews_first`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: good. This is a specific workflow question with plausible confusion points.
6. Proposed changes: keep as-is.

Verdict: `Keep as-is`.

### `consolidation_awareness`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair if the public docs remain reachable.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: moderate-to-good. It tests whether the agent can synthesize lifecycle semantics instead of guessing.
6. Proposed changes: keep as-is, but consider slightly simplifying the wording if weaker models over-index on the colloquial "정리".

Verdict: `Keep as-is`.

### `version_lineage`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: mostly balanced, though the exact `0.35x` demotion mechanic is implementation-specific and may be brittle if docs change.
5. CLI harness suitability: moderate. Good signal if the docs remain current; brittle if the exact multiplier changes.
6. Proposed changes: soften the exact-number requirement in future revisions:
   - prefer "search-demoted automatically" as core
   - treat the exact multiplier as bonus or supporting detail

Verdict: `Keep with minor rubric softening`.

### `citation_integrity`

1. Prompt clarity: clear.
2. Expected outcome fairness: fair.
3. Hallucination trap realism: realistic.
4. Rubric balance: balanced.
5. CLI harness suitability: good. It tests behavior that should improve with connected OpenAkashic, but is still answerable from public docs.
6. Proposed changes: keep as-is.

Verdict: `Keep as-is`.

## Specifically flagged tasks

### `domain_jlpt_gen`

- The Stage 6 result where baseline beats openakashic looks more like a **retrieval steering failure** than proof that OpenAkashic is worse.
- The retrieved note appears to have been adjacent JLPT content but not the requested fill-in format.
- In a real CLI benchmark, the correct fallback behavior is:
  - use retrieved material only if it matches the task shape
  - otherwise generate from general knowledge
- Recommendation: do not treat this as a core OpenAkashic memory task. Either demote it to a control or rewrite it.

### `ichimozzi_deploy`, `triage_ichimozzi_500`, `onboarding_openakashic`, `busagwan_sagwan_roles`

- These leak insu's environment names, private vault paths, or instance-private terminology.
- They are valid if the goal is "does the agent recover private, connected operational memory from OpenAkashic?"
- They are not valid if the goal is a generally publishable OpenAkashic benchmark.
- Recommendation: move them into an explicit `insu-private` subset rather than keeping them in the primary CLI benchmark headline.

### `memory_roundtrip`

- With a stateless one-shot CLI baseline, this no longer cleanly measures persistent memory.
- The baseline can still answer from immediate context, and a tool-capable CLI may write transient local artifacts unrelated to OpenAkashic.
- Recommendation: replace with a persistence-contract task that explicitly distinguishes durable memory from same-turn recall.

## Proposed v0.7 task set

Target: 10-12 tasks, mixing controls with fair OpenAkashic-specific workflow questions.

### Keep in primary v0.7

- `coding_python_bug`
- `coding_sql_index`
- `general_web_fact`
- `daily_email_rewrite`
- `review_workflow`
- `list_reviews_first`
- `consolidation_awareness`
- `version_lineage`
- `citation_integrity`

### Rewrite for primary v0.7

- `onboarding_public_openakashic`
  - public onboarding only, no private vault paths
- `memory_contract_check`
  - baseline should explicitly say it cannot durably persist without a memory system
  - openakashic should perform actual durable writeback
- `public_multihop_openakashic`
  - cross-reference two public OpenAkashic docs/workflows instead of insu-private topology

### Move to `insu-private` subset

- `onboarding_openakashic`
- `triage_ichimozzi_500`
- `ichimozzi_deploy`
- `busagwan_sagwan_roles`
- `multihop_synthesis`

### Drop or demote to optional control

- `domain_jlpt_gen`
- `daily_agenda`

## Proposed `tasks-v0.7.yaml` skeleton

This is a sketch only. It is intentionally not committed as `tasks-v0.7.yaml` yet.

```yaml
version: v0.7
k_default: 3

tasks:
  - id: coding_python_bug
    keep: as_is

  - id: coding_sql_index
    keep: as_is

  - id: general_web_fact
    keep: as_is

  - id: daily_email_rewrite
    keep: as_is

  - id: review_workflow
    keep: as_is

  - id: list_reviews_first
    keep: as_is

  - id: consolidation_awareness
    keep: as_is

  - id: version_lineage
    edits:
      - make exact demotion multiplier optional, not mandatory

  - id: citation_integrity
    keep: as_is

  - id: onboarding_public_openakashic
    prompt: |
      OpenAkashic을 처음 쓰는 에이전트라고 가정할게.
      public docs 기준으로 어디서부터 읽고 어떤 순서로 검색/기록 workflow를 시작해야 하는지 알려줘.
      private vault 내부 경로를 가정하지 말고, public하게 재현 가능한 시작점만 써줘.
    expected_outcome:
      - "search_akashic first, then search_notes workflow"
      - "public docs or MCP guidance starting points"
      - "after meaningful work, write back a concise note"
    hallucination_traps:
      - "private path를 필수 전제로 제시"
      - "존재하지 않는 MCP tool 또는 시그니처 제시"

  - id: memory_contract_check
    prompt: |
      이 선호사항을 나중에도 다시 꺼낼 수 있게 durable하게 저장해줘: 저녁 커피 금지.
      만약 지금 네가 durable memory를 쓸 수 없다면, 그 사실을 분명히 말하고 왜 그런지 설명해줘.
    expected_outcome:
      - "openakashic이면 actual durable write 또는 그 결과를 명시"
      - "baseline이면 durable persistence 부재를 정직하게 설명"
      - "저장 여부를 거짓으로 주장하지 않음"
    hallucination_traps:
      - "실제 저장 없이 저장했다고 주장"

  - id: public_multihop_openakashic
    prompt: |
      OpenAkashic에서 claim과 capsule의 차이, 그리고 capsule을 public knowledge로 올릴 때 review/publication 흐름이 어떻게 이어지는지 설명해줘.
      가능한 한 실제 도구명 기준으로 정리해줘.
    expected_outcome:
      - "claim vs capsule distinction"
      - "request_note_publication flow"
      - "review/consolidation or publication workflow linkage"
    hallucination_traps:
      - "claim을 publication-review 없이 private-only라고 설명"
      - "존재하지 않는 publication tool 제시"
```

## Recommendation

- Make `cli_baseline` vs `cli_openakashic` the only headline chart for v0.7.
- Keep the old simulated trio only as historical appendix.
- Split task inventory into:
  - `tasks-v0.7.yaml` for fair/public CLI comparison
  - `tasks-private.yaml` for insu-connected private memory regression tests
