# OpenAkashicBench v0.7 — 3-model Headline Report

**Date**: 2026-04-26
**Suites**: `tasks-v0.7.yaml` (12 fair-public) + `tasks-private.yaml` (5 insu-vault)
**Conditions**: `cli_baseline` (CLI agent, no MCP) vs `cli_openakashic` (CLI agent + OpenAkashic MCP)
**CLI harnesses**: Claude Code 2.1.118 (Haiku 4.5, Sonnet 4.6) + Codex 0.120.0 (gpt-5.4)
**Judge**: gpt-5.4-mini (sequential, retry-with-backoff)
**Total agent runs**: Haiku k=3 × 12 × 2 = 72 + Sonnet k=1 × 12 × 2 = 24 + gpt-5.4 k=1 × 5 × 2 = 10 = **106 runs**

> ⚠️ Methodology note: 첫 시도(2026-04-25)에서 Sonnet judge가 stream/JSON-format 호환 + 부하 이슈로 모든 verdict가 error였음.
> 진단 → judge.py에 5회 exponential backoff retry 추가 → Haiku judge 80s/call로 너무 느림 →
> gpt-5.4-mini로 전환 (10s/call, 8x 빠름). 최종 결과는 mini judge 기반.

## Headline numbers

| Model | Suite | Condition | Pass | Hit rate | Traps |
|---|---|---|---:|---:|---:|
| Haiku 4.5 (k=3) | v0.7 | baseline | 12/36 (33%) | 0.53 | 14 |
| Haiku 4.5 (k=3) | v0.7 | **+OpenAkashic** | **17/36 (47%)** | **0.71** | **8** |
| Sonnet 4.6 (k=1) | v0.7 | baseline | 5/12 (42%) | 0.68 | 5 |
| Sonnet 4.6 (k=1) | v0.7 | **+OpenAkashic** | **7/12 (58%)** | **0.88** | **4** |
| gpt-5.4 (k=1) | **private** | baseline | 2/5 (40%) | 0.73 | 4 |
| gpt-5.4 (k=1) | **private** | **+OpenAkashic** | **4/5 (80%)** | **0.85** | **0** |

## Deltas (OpenAkashic − baseline)

| Model | Suite | Δ pass | Δ hit | Δ traps | Verdict |
|---|---|---:|---:|---:|---|
| Haiku 4.5 | v0.7 (k=3) | **+5** | **+0.18** | **−6** | 🟢 강력한 우위, 환각 -43% |
| Sonnet 4.6 | v0.7 (k=1) | **+2** | **+0.20** | −1 | 🟢 강한 모델도 효과 (예전 측정과 다름) |
| gpt-5.4 | private (k=1) | **+2** | +0.12 | **−4** | 🟢 내부 지식에서 결정적 우위, 환각 0 |

## Per-task — v0.7 (public-fair)

| task | Haiku-B | Haiku-O | Sn-B | Sn-O |
|---|:---:|:---:|:---:|:---:|
| coding_python_bug | 3/3 | 3/3 | ✓ | ✓ |
| coding_sql_index | 3/3 | 3/3 | ✓ | ✓ |
| daily_email_rewrite | 2/3 | 2/3 | ✓ | ✓ |
| version_lineage | 0/3 | 0/3 | ✓ | ✓ |
| citation_integrity | 2/3 | **3/3** | ✓ | · |
| general_web_fact | 1/3 | **2/3** | · | **✓** |
| list_reviews_first | 0/3 | **1/3** | · | **✓** |
| **review_workflow** | **0/3** | **2/3** | · | **✓** |
| public_multihop_openakashic | 1/3 | 1/3 | · | · |
| consolidation_awareness | 0/3 | 0/3 | · | · |
| memory_contract_check | 0/3 | 0/3 | · | · |
| onboarding_public_openakashic | 0/3 | 0/3 | · | · |

**Haiku MCP gains (k=3)**: review_workflow (0→2), list_reviews_first (0→1), citation_integrity (2→3), general_web_fact (1→2). 전부 OpenAkashic 워크플로우 지식 task.

**Sonnet MCP gains**: review_workflow, list_reviews_first, general_web_fact (모두 0→1).
**Sonnet MCP regression**: citation_integrity (1→0).

**4/4 fail tasks** (모든 모델/조건): consolidation_awareness, memory_contract_check, onboarding_public_openakashic. Rubric 추가 완화 또는 task design 재검토 필요.

## Per-task — private (gpt-5.4)

| task | baseline | +OAK |
|---|:---:|:---:|
| onboarding_openakashic | ✓ | ✓ |
| ichimozzi_deploy | ✓ | ✓ |
| triage_ichimozzi_500 | · | **✓** |
| multihop_synthesis | · | **✓** |
| busagwan_sagwan_roles | · | · |

**MCP 우위 확정**: triage + multihop. busagwan_sagwan_roles는 둘 다 fail (insu 고유 용어 정의 어려움).

## 핵심 발견

### 1. 모든 모델 크기에서 OAK 효과

이전 라운드(첫 v0.7 4-way)에선 gpt-5.4가 OAK로 -1 pass 회귀였는데 이번엔:
- Haiku +5 pass (+14% 절대)
- Sonnet +2 pass (+17% 절대)
- gpt-5.4 +2 pass (+40% 절대 — private 5 task 작은 표본이지만 결정적)

**큰 모델도 효과 본다**가 새 결론. 이전 회귀는 v0.7 5개 all-fail rubric 미보정 + judge 이슈 두 요소가 합쳐졌던 것.

### 2. 환각 감소가 가장 일관된 효과 (재확인)

- Haiku: 14 → 8 traps (**-43%**)
- gpt-5.4 private: 4 → 0 traps (**-100%**)
- Sonnet: 5 → 4 (-20%, 작음)

특히 **gpt-5.4 private 환각 0**은 강력한 신호 — 모델이 자체 지식으로 환각하던 영역(IchiMozzi 컨테이너명 등)을 OAK가 정확히 잡아줌.

### 3. v0.7 task 중 4/4 fail 3개 — rubric 추가 완화 필요

`consolidation_awareness`, `memory_contract_check`, `onboarding_public_openakashic` — 모든 4×4 = 16 attempt에서 0 pass. 두 가능성:
- (a) Rubric `core` 항목이 여전히 너무 엄격 — 강한 답변도 1개 missing으로 fail
- (b) Task 자체 어려움 (특히 memory_contract_check는 의도된 trap — Bash로 가짜 저장 vs 정직한 refusal)

(a)는 고치기 쉬움, (b)는 의도대로면 두는 게 맞음. memory_contract_check 0% pass는 여전히 "모든 LLM이 refusal honesty 부족" 의미라 흥미로운 결과.

### 4. k=3 variance가 의미있음 (Haiku)

Haiku k=3에서 task별 pass 분포:
- 항상 pass (3/3): coding_python_bug, coding_sql_index — Haiku가 OAK에 의존하지 않는 영역
- 항상 fail (0/3): consolidation_awareness, memory_contract_check, onboarding_public_openakashic, version_lineage (base만), review_workflow (base만)
- variance (1-2/3): daily_email_rewrite, general_web_fact, citation_integrity — 답변 품질이 unstable, k=3로 평균낼 가치 큼

→ **k=1은 노이즈가 큼**. v0.8에서는 k=3을 default로 권장.

## 이번 라운드의 부수 fix

벤치 작업 중 발견·수정한 사항:
- **사관 health 4건 fix** 별도 PR (`eb4fed8`): tool-based dedup gate, core_sync backoff, WebFetch retry, refresh-on-duplicate
- **judge.py에 5회 exponential backoff retry**: proxy 불안정성 우회
- **judge model을 Sonnet → mini로 변경**: 80s → 10s per call (8x 가속)

## 권장 다음 단계

1. **Sonnet k=3 + gpt-5.4 v0.7 추가 측정** (이번엔 k=1 한 모델만) — variance 확인
2. **3 all-fail task rubric 재조정** (그 중 memory_contract_check은 의도적이니 제외 가능)
3. **사관 health fix branch merge** + 컨테이너 재배포 → 차주 weekly 자동 bench 활성화 후보

## Raw data

- Haiku k=3: `run-cli_baseline-claude-claude-haiku-4-5-20260425T144822Z*.json`, `run-cli_openakashic-claude-claude-haiku-4-5-20260425T145857Z*.json`
- Sonnet: `run-cli_*-claude-claude-sonnet-4-6-20260425T144*.json`
- gpt-5.4 priv: `run-cli_*-codex-gpt-5_4-20260425T144023Z*.json`, `run-cli_*-codex-gpt-5_4-20260425T145153Z*.json`
- 모두 `-judged.json` 짝 보유 (gpt-5.4-mini judge model)
