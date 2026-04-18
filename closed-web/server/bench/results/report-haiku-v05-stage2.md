# OpenAkashicBench v0.5 — A/B Report

**Model**: `claude-haiku-4-5`  
**Conditions compared**: baseline, openakashic, standard  
**Tasks**: 7

## Summary (pass@k by condition)

| task | baseline pass@k | openakashic pass@k | standard pass@k | baseline hit rate | openakashic hit rate | standard hit rate | baseline traps | openakashic traps | standard traps |
|---|---|---|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0 | 1 | 0 | 0.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| domain_jlpt_gen | 1 | 0 | 0 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| general_web_fact | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| ichimozzi_deploy | 1 | 0 | 0 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| memory_roundtrip | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| onboarding_openakashic | 1 | 0 | 0 | 1.00 | 0.25 | 0.00 | 0 | 0 | 0 |
| triage_ichimozzi_500 | 0 | 0 | 0 | 0.75 | 0.00 | 0.00 | 0 | 0 | 0 |

## Lift: standard vs baseline (기본 에이전트 도구가 주는 이득)

| task | baseline hit | standard hit | Δ hit | baseline traps | standard traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| onboarding_openakashic | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.75 | 0.00 | -0.75 | 0 | 0 | +0 |
| **mean** | **0.54** | **0.00** | **-0.54** | **0** | **0** | **+0** |

## Lift: openakashic vs standard (OpenAkashic 고유 가치)

| task | standard hit | openakashic hit | Δ hit | standard traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| general_web_fact | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| onboarding_openakashic | 0.00 | 0.25 | +0.25 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| **mean** | **0.00** | **0.18** | **+0.18** | **0** | **0** | **+0** |

## Lift: openakashic vs baseline (전체 lift)

| task | baseline hit | openakashic hit | Δ hit | baseline traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| onboarding_openakashic | 1.00 | 0.25 | -0.75 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.75 | 0.00 | -0.75 | 0 | 0 | +0 |
| **mean** | **0.54** | **0.18** | **-0.36** | **0** | **0** | **+0** |

## Per-task detail

### busagwan_sagwan_roles

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - Sagwan=Claude CLI/느린 주기, Busagwan=gemma/빠른 주기, cadence 수치(15분/1시간), Busagwan→Sagwan 2단계 gate 구조까지 4/4 expected_outcome 전부 충족했고 명시된 3개 트랩(도구·DB 오인, 동일 모델, Sagwan=gemma 역전)은 미발동이다. 허위 출처 인용('아까 검색한 브리핑')은 groundedness 오염이지만 현재 trap 목록에 해당 항목이 없으므로 기술적 verdict는 pass.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6

### domain_jlpt_gen

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 4개 expected_outcome 모두 충족됐고 정의된 트랩(한국어 본문, 동의어 형식, N1/N2 어휘) 중 어느 것도 발동되지 않아 PASS. baseline 조건에서 tool_calls 없이 Akashic 저장을 완료했다고 주장한 것은 허위이나 채점 기준인 content 품질 트랩과 무관하다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - search_and_read_top이 N4 패턴 파일과 예시 파일을 반환했음에도 모델은 문서 내용을 합성하지 않고 경로 나열에 그쳤다. N4 fill-in 문제 자체가 answer에 없어 4개 expected_outcome을 모두 누락했고 0/4 hit(0%)으로 FAIL.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모델은 '명시적 요청이 보이지 않는다'며 도움 제안 메뉴를 출력하는 데 그쳤고, JLPT N4 fill-in 문제를 전혀 작성하지 않았다. standard 조건에서 notes_list가 빈 결과를 반환했어도 훈련 지식으로 충분히 생성 가능한 과제임에도 완전히 회피해 0/4 hit(0%) FAIL.

### general_web_fact

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 검색 결과가 불량했더라도 MCP URL과 설명은 모델 자체 지식으로 답할 수 있었으나 모델은 '검색 실패' 보고로 종료했다. 3개 expected_outcome 모두 누락, 0/3 hit(0%) FAIL.

### ichimozzi_deploy

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - production.yml docker compose 명령어, 로컬 홈서버 Docker 스택 명시, 수동 배포 절차 제공으로 3개 expected_outcome을 모두 충족했다. EC2·CodeDeploy·ec2-user 경로·PM2/systemd 트랩 중 어느 것도 발동되지 않아 3/3 hit(100%), traps_hit 없음으로 PASS.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - search_and_read_top이 핵심 배포 플레이북(playbooks/update-and-deploy.md)을 반환했음에도 read_note 호출 없이 경로만 안내했다. docker compose 명령어, 로컬 홈서버 언급, webhook 상태 등 3개 expected_outcome이 모두 누락되어 0/3 hit(0%) FAIL.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - standard 조건이므로 web_search로 배포 절차를 보완하거나 일반 Docker 지식으로 답변할 수 있었으나 모델은 아무 시도 없이 종료했다. 3개 expected_outcome 모두 누락, 0/3 hit(0%) FAIL.

### memory_roundtrip

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - judge error: RuntimeError: proxy returned empty stream for model=claude-sonnet-4-6

### onboarding_openakashic

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - README.md 경로, search_notes, upsert_note/append_note_section writeback, personal_vault/doc/ 경로 제약 4개 항목 모두 포함됐다. 정의된 트랩(존재하지 않는 /vault/closed/ 경로, list_notes 잘못된 시그니처, bootstrap_project 무조건 선행 안내) 중 어느 것도 발동되지 않았으며 bootstrap_project는 오히려 올바르게 '호출 금지'로 안내했다. 4/4 hit, traps_hit 없음으로 PASS.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.25, traps_hit 0
  - README.md 경로 제시 1개만 hit하고, 탐색 도구 언급·writeback 절차·경로 제약 설명 3개가 모두 누락됐다. list_notes와 search_and_read_top을 사용해 정확한 문서를 찾았음에도 read_note 없이 경로만 나열한 패턴이 반복되어 1/4 hit(25%) FAIL.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모델은 notes_list 빈 결과만 보고하고 그 이상 진행하지 않았다. standard 조건에서 web_search 활용도 없었고 경로·도구·절차·제약 등 4개 expected_outcome이 전부 누락되어 0/4 hit(0%) FAIL.

### triage_ichimozzi_500

- **baseline** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - insu-shared-caddy 우선 확인, Caddy→backend→DB 트리아지 순서, docker logs 절차 3개는 hit했으나, 백엔드 컨테이너 이름을 insu-server-backend-prod-1로 오표기하여 expected_outcome의 ichimozzi-migration-backend-prod-1 항목을 충족하지 못했다. 3/4 hit(75%)으로 80% 기준 미달 FAIL.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - list_notes와 search_and_read_top으로 triage-500-runbook.md를 두 번 확인했음에도 read_note 호출 없이 경로 안내에 그쳤다. insu-shared-caddy, 컨테이너 이름, 체크 순서, docker logs 절차 4개 expected_outcome 모두 누락되어 0/4 hit(0%) FAIL.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - standard 조건에서 web_search를 활용하거나 일반 Docker 지식으로라도 triage 절차를 제시했어야 하나, 모델은 단 한 문장으로 응답을 종료했다. 4개 expected_outcome 모두 누락, 0/4 hit(0%)으로 FAIL.
