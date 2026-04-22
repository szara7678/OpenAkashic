# OpenAkashicBench v0.5 — A/B Report

**Model**: `gpt-5.4-mini`  
**Conditions compared**: baseline, openakashic, standard  
**Tasks**: 3

## Summary (pass@k by condition)

| task | baseline pass@k | openakashic pass@k | standard pass@k | baseline hit rate | openakashic hit rate | standard hit rate | baseline traps | openakashic traps | standard traps |
|---|---|---|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| multihop_synthesis | 0 | 0 | 0 | 0.33 | 0.33 | 0.33 | 1 | 0 | 1 |
| onboarding_openakashic | 0 | 0 | 0 | 0.50 | 0.75 | 0.75 | 0 | 0 | 0 |

## Lift: standard vs baseline (기본 에이전트 도구가 주는 이득)

| task | baseline hit | standard hit | Δ hit | baseline traps | standard traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| multihop_synthesis | 0.33 | 0.33 | +0.00 | 1 | 1 | +0 |
| onboarding_openakashic | 0.50 | 0.75 | +0.25 | 0 | 0 | +0 |
| **mean** | **0.28** | **0.36** | **+0.08** | **1** | **1** | **+0** |

## Lift: openakashic vs standard (OpenAkashic 고유 가치)

| task | standard hit | openakashic hit | Δ hit | standard traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| multihop_synthesis | 0.33 | 0.33 | +0.00 | 1 | 0 | -1 |
| onboarding_openakashic | 0.75 | 0.75 | +0.00 | 0 | 0 | +0 |
| **mean** | **0.36** | **0.36** | **+0.00** | **1** | **0** | **-1** |

## Lift: openakashic vs baseline (전체 lift)

| task | baseline hit | openakashic hit | Δ hit | baseline traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| multihop_synthesis | 0.33 | 0.33 | +0.00 | 1 | 0 | -1 |
| onboarding_openakashic | 0.50 | 0.75 | +0.25 | 0 | 0 | +0 |
| **mean** | **0.28** | **0.36** | **+0.08** | **1** | **0** | **-1** |

## Per-task detail

### busagwan_sagwan_roles

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 정답 체크포인트 4개 중 충족된 항목이 없다. 환각 트랩을 직접 밟지는 않았지만, 답변 전체가 문서 기반 설명이 아니라 추정적 서술이어서 최종 판정은 fail이다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome의 핵심 항목들인 Claude CLI vs Ollama gemma 구분, 빠름/느림, 주기 차이, gate 구조가 답변에 포함되지 않았습니다. 환각 트랩을 직접 밟지는 않았지만, 근거가 부족한 추상적 설명만 있어 채점 기준상 fail입니다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 기대된 핵심 내용인 Claude CLI 기반 Sagwan, Ollama gemma 기반 Busagwan, 각자의 cadence, 그리고 두 워커의 gate 구조가 전혀 언급되지 않았습니다. 명시된 hallucination trap을 직접 밟지는 않았지만, 답변 전체가 과제의 대상 개념을 잘못 해석한 비근거성 응답이므로 fail입니다.

### multihop_synthesis

- **baseline** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - 각 항목에 점검 이유는 붙였지만, 요구된 실제 시스템명 3개를 전혀 제시하지 못했다. 또한 Docker container/proxy/DB 같은 실인프라 단위가 아니라 추상적인 역할 수준으로 답해 환각 트랩에도 해당하므로 fail이다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 0
  - 세 항목 모두에 이유를 붙인 점은 충족했다. 그러나 요구사항의 핵심인 실제 인프라 구성요소 3개의 실명을 제시하지 못했고, `health` URL은 컨테이너/proxy/DB 같은 시스템명으로 보기 어렵다. 따라서 expected_outcome 충족률이 80%에 못 미쳐 fail이다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - 기대된 핵심은 IchiMozzi 실제 배포 인프라의 실명 컨테이너/시스템 3개를 짚는 것이었는데, 답변은 API 서버·DB·캐시/큐라는 일반론에 머물렀다. 각 항목의 점검 이유는 제시했지만, 실제 구성요소 기반 답변이 아니고 일반론 회피 트랩에도 걸려 전체 판정은 fail이다.

### onboarding_openakashic

- **baseline** (k=1): passes 0/1, hit_rate mean 0.50, traps_hit 0
  - 핵심 기대사항인 실제 시작점 경로(`personal_vault/projects/personal/openakashic/README.md` 등)와 `search_notes`/`search_and_read_top` 같은 구체 도구 언급이 빠졌습니다. 작업 전 검색과 작업 후 기록 원칙, 그리고 `personal_vault/`·`doc/` 경로 제약은 설명했지만 전체 expected_outcome 충족률이 80%에 못 미쳐 fail입니다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - 핵심 절차 설명은 대체로 맞았고 환각 트랩도 직접 밟지 않았다. 하지만 expected_outcome의 중요한 항목인 실존 시작점 경로 제시를 충족하지 못해 총 4개 중 3개만 hit였고, 80% 기준에 미달하므로 fail이다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - 검색 도구, 사전 검색/사후 writeback 절차, personal_vault/doc 제약은 제대로 설명했습니다. 하지만 핵심 기대사항인 실제 시작점 경로(예: personal_vault/projects/personal/openakashic/README.md)를 구체적으로 제시하지 않아 expected_outcome 충족률이 80% 미만이므로 fail입니다.
