# OpenAkashicBench v0.7 — CLI 4-way Headline Report

**Date**: 2026-04-25
**Tasks**: 12 (tasks-v0.7.yaml, environment-neutral subset)
**Judge**: claude-sonnet-4-6 with rubric-based scoring
**Conditions**: `cli_baseline` (no MCP) vs `cli_openakashic` (OpenAkashic MCP connected)
**CLI harnesses**: Claude Code 2.1.118 (Haiku 4.5) + Codex 0.120.0 (gpt-5.4)
**Total runs**: 48 (12 tasks × 2 conditions × 2 models, k=1)

## Headline table

| Model | Condition | Pass@1 | Hit rate | Traps | Avg duration |
|---|---|---:|---:|---:|---:|
| Claude Haiku 4.5 | cli_baseline | 3/12 (25%) | 0.40 | 1 | 17.2s |
| Claude Haiku 4.5 | **cli_openakashic** | 3/12 (25%) | **0.58** | 2 | 14.8s |
| Codex gpt-5.4 | cli_baseline | 6/12 (50%) | 0.70 | 1 | 34.3s |
| Codex gpt-5.4 | **cli_openakashic** | 6/12 (50%) | 0.70 | 1 | **62.0s** |

## Deltas (openakashic − baseline)

| Model | Δ pass@1 | Δ hit_rate | Δ traps | Δ avg_duration |
|---|---:|---:|---:|---:|
| Claude Haiku 4.5 | +0 | **+0.18** | +1 | -2.4s |
| Codex gpt-5.4 | +0 | +0.00 | +0 | **+27.7s** |

## Per-task pass matrix

| task | Haiku baseline | Haiku MCP | gpt-5.4 baseline | gpt-5.4 MCP | note |
|---|:---:|:---:|:---:|:---:|---|
| coding_python_bug | ✓ | ✓ | ✓ | ✓ | control |
| coding_sql_index | ✓ | · | ✓ | ✓ | **MCP regression (Haiku)** — 대안으로 역순 인덱스 제시 (trap hit) |
| general_web_fact | · | · | ✓ | ✓ | 판정 strict (GitHub URL trivial miss) |
| daily_email_rewrite | ✓ | ✓ | ✓ | ✓ | control |
| consolidation_awareness | · | · | ✓ | ✓ | gpt-5.4가 더 완벽한 설명 |
| list_reviews_first | · | · | ✓ | ✓ | gpt-5.4만 통과 |
| review_workflow | · | **✓** | · | · | **Haiku MCP 우위** — MCP로 review_note 정확히 식별 |
| version_lineage | · | · | · | · | 4/4 fail (80% hit 임계 엄격) |
| citation_integrity | · | · | · | · | 4/4 fail (rubric 엄격) |
| memory_contract_check | · | · | · | · | 4/4 fail — **모든 에이전트 가짜 저장 주장** |
| onboarding_public_openakashic | · | · | · | · | 4/4 fail (rubric 엄격) |
| public_multihop_openakashic | · | · | · | · | 4/4 fail (rubric 엄격) |

## 결론

### 1️⃣ pass@1 지표로는 MCP 효과 보이지 않음

Pass delta 0/0. **하지만 hit_rate (expected_outcome 충족률)에서는 Haiku +18% 개선**. 즉 MCP는 답변의 **완성도를 올리지만 binary pass/fail 기준을 넘기지는 못함** (판정 80% hit 임계가 엄격).

### 2️⃣ MCP는 OpenAkashic 워크플로우 지식 task에서 차별화

Haiku의 hit_rate 개선이 집중된 영역:
- `list_reviews_first`: 0.50 → **0.83** (+33%)
- `review_workflow`: 0.50 → **1.00** (+50%, pass로 전환)
- `consolidation_awareness`: 0.50 → 0.62
- `version_lineage`: 0.62 → 0.75

모두 OpenAkashic 고유 워크플로우 task. **MCP 연결된 에이전트는 review_note / list_reviews / claim_review_lifecycle 같은 실제 도구명과 시그니처를 정확히 인용**.

### 3️⃣ Codex(gpt-5.4)는 MCP에 느려지기만 함

baseline 34s → openakashic **62s (+80%)**, 답변 품질 변화 없음 (hit_rate 0.70 고정). Codex가 MCP tool을 호출하지만 답변에 반영되지 않는 패턴. **강력한 파라메트릭 모델에겐 MCP 비용 > 이득**.

### 4️⃣ Haiku가 OpenAkashic의 타겟 사용자

`cli_baseline` 25% pass → 상대적으로 약한 파라메트릭 지식. MCP 붙으면 hit_rate +18% 향상. **작은 모델일수록 OpenAkashic 효과 큼**. 이는 OpenAkashic mission ("작은 모델 + 공유 메모리 = 큰 모델 성능")과 일치.

## 지적 사항 + 개선 대상

### A. v0.7 rubric 재조정 필요 (high priority)

4개 task (`citation_integrity`, `memory_contract_check`, `onboarding_public_openakashic`, `public_multihop_openakashic`, `version_lineage`)가 **4 조건 모두 fail**. 모든 에이전트가 hit_rate 0.50-0.75 구간이지만 80% 임계 미달로 판정관이 fail 판정.

**원인**:
- expected_outcome 항목이 5-6개로 많아 **80% 중 1개 missing으로 바로 fail**
- 일부 항목이 너무 specific (예: "구체적 multiplier 수치 언급")

**제안**: rubric 재조정 — 각 task의 expected_outcome을 3-4개 필수 + 1-2개 bonus로 구조화, 판정 임계 60-70%로 낮춤.

### B. `memory_contract_check` task 설계 결함

4/4 에이전트가 **실제 저장 없이 "durable memory에 저장되었습니다" 거짓 주장** → trap hit이지만 rubric이 약해서 fail만 계산되고 trap count는 누락.

**원인**: CLI 에이전트는 `Bash` 도구로 임의 파일 쓸 수 있음 → 자기가 만든 임시 파일을 "durable memory"라 주장.

**제안**: expected_outcome 조건에 "OpenAkashic `upsert_note` 또는 `Memory` 도구 **실제 호출 receipt 언급**"을 추가하고, 파일 경로만 제시하면 trap 처리.

### C. `coding_sql_index` MCP 회귀 (Haiku)

baseline은 (user_id, created_at DESC) 단일 복합 인덱스 제시 → pass. MCP 조건에선 추가로 "대안: 역순 조합도 가능" 제시 → reverse-order trap hit.

**원인**: MCP 연결이 에이전트를 더 elaborate하게 만듦 → 더 많은 옵션 나열 → trap 밟을 확률↑

**제안**: 이건 rubric 문제가 아니라 실제 risk signal. 유지 권장. 에이전트에게 "최우선 추천만 제시, 대안 서술 시 trap 리스크" 힌트를 guidance에 반영.

## Raw data

- Claude Haiku baseline: [run-cli_baseline-claude-claude-haiku-4-5-20260424T175930Z-judged.json](run-cli_baseline-claude-claude-haiku-4-5-20260424T175930Z-judged.json)
- Claude Haiku openakashic: [run-cli_openakashic-claude-claude-haiku-4-5-20260424T180250Z-judged.json](run-cli_openakashic-claude-claude-haiku-4-5-20260424T180250Z-judged.json)
- Codex gpt-5.4 baseline: [run-cli_baseline-codex-gpt-5_4-20260424T180954Z-judged.json](run-cli_baseline-codex-gpt-5_4-20260424T180954Z-judged.json)
- Codex gpt-5.4 openakashic: [run-cli_openakashic-codex-gpt-5_4-20260424T182244Z-judged.json](run-cli_openakashic-codex-gpt-5_4-20260424T182244Z-judged.json)

## 다음 단계 (권장 우선순위)

1. **v0.7 rubric 재조정** — 4개 "all-fail" task 수정 후 재실행, 실제 pass 차이가 나오는지 확인
2. **k=3 재실행** — k=1은 variance가 큼. 각 task 3회로 confidence interval 확보
3. **`memory_contract_check` 태스크 rewrite** — 명시적 upsert_note receipt 요구
4. **Sonnet 4.6 baseline/openakashic 추가** — Haiku와 Codex 사이 성능 곡선 커버
5. **Private 태스크 5개도 동일 harness로 실행** — 내부 지식 retrieval에서 MCP 우위 크기 측정
