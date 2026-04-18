# OpenAkashicBench v0.5 — A/B Report

**Model**: `claude-haiku-4-5`  
**Conditions compared**: baseline, openakashic, standard  
**Tasks**: 7

## Summary (pass@k by condition)

| task | baseline pass@k | openakashic pass@k | standard pass@k | baseline hit rate | openakashic hit rate | standard hit rate | baseline traps | openakashic traps | standard traps |
|---|---|---|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0 | 1 | 0 | 0.75 | 1.00 | 0.00 | 0 | 0 | 0 |
| domain_jlpt_gen | 1 | 1 | 0 | 1.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| general_web_fact | 1 | 1 | 0 | 1.00 | 1.00 | 0.67 | 0 | 0 | 0 |
| ichimozzi_deploy | 1 | 1 | 0 | 1.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| memory_roundtrip | 0 | 0 | 1 | 0.33 | 0.00 | 1.00 | 1 | 0 | 0 |
| onboarding_openakashic | 1 | 0 | 0 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| triage_ichimozzi_500 | 1 | 0 | 0 | 1.00 | 0.75 | 0.00 | 0 | 0 | 0 |

## Lift: standard vs baseline (기본 에이전트 도구가 주는 이득)

| task | baseline hit | standard hit | Δ hit | baseline traps | standard traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.75 | 0.00 | -0.75 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 1.00 | 0.67 | -0.33 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 1.00 | +0.67 | 1 | 0 | -1 |
| onboarding_openakashic | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| **mean** | **0.87** | **0.24** | **-0.63** | **1** | **0** | **-1** |

## Lift: openakashic vs standard (OpenAkashic 고유 가치)

| task | standard hit | openakashic hit | Δ hit | standard traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| general_web_fact | 0.67 | 1.00 | +0.33 | 0 | 0 | +0 |
| ichimozzi_deploy | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| memory_roundtrip | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| onboarding_openakashic | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.00 | 0.75 | +0.75 | 0 | 0 | +0 |
| **mean** | **0.24** | **0.68** | **+0.44** | **0** | **0** | **+0** |

## Lift: openakashic vs baseline (전체 lift)

| task | baseline hit | openakashic hit | Δ hit | baseline traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.75 | 1.00 | +0.25 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| general_web_fact | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 0.00 | -0.33 | 1 | 0 | -1 |
| onboarding_openakashic | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 1.00 | 0.75 | -0.25 | 0 | 0 | +0 |
| **mean** | **0.87** | **0.68** | **-0.19** | **1** | **0** | **-1** |

## Per-task detail

### busagwan_sagwan_roles

- **baseline** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - Busagwan=1차 자동화, Sagwan=2차 고품질 최종 결정이라는 상응하는 구분과 Busagwan→Sagwan 게이트 구조는 충족(3/4=75%)했으나, 10분/15분/1시간 같은 구체적 cadence 언급이 없어 80% 기준에 미달한다. 할루시네이션 트랩(동일 모델, Sagwan=gemma, 도구/DB 이름)은 발동하지 않았으나 hit률 75%로 fail이다.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - Sagwan=Claude CLI/최종 승인/10분~1시간, Busagwan=Ollama gemma/1차 리뷰/15분으로 각각의 모델·주기·역할이 명확히 구분되고, 1차 리뷰→최종 승인의 계층 구조가 gate 관계를 의미적으로 충족하여 4개 expected_outcome 모두 hit(100%)했다. 할루시네이션 트랩(같은 모델, Sagwan=gemma, 도구/DB 이름)은 발동하지 않아 pass로 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - standard 조건에서 노트와 웹 검색 모두 실패해 4개 expected_outcome 전부 미충족(0%)이다. 할루시네이션 트랩(도구/DB 이름, 같은 모델, Sagwan=gemma)은 발동하지 않았으나 정보 제공 자체가 불가능한 상황이어서 fail이다.

### domain_jlpt_gen

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - （　）형 일본어 빈칸 본문, 起きる/立つ/起こす/開く 4개의 N4 이하 어휘 보기, correctAnswer 및 해설 명시, 정답의 보기 내 실존 — 4개 expected_outcome 모두 충족(100%)했다. 한국어 본문·동의어 선택·N1/N2 어휘 트랩은 발동하지 않아 pass로 판정한다.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - '彼は毎日図書館で___勉強しています。' 라는 일본어 빈칸 본문, ねっしんに/あつしんに/ねつしんに/ねっしんく 4개의 N4 수준 일본어 선택지, (정답) 표시로 ねっしんに 명시, 정답이 선택지 안에 실제 포함되어 순환 오류 없음 — 4개 expected_outcome 모두 충족(100%). 한국어 본문·동의어 선택·N1/N2 어휘 트랩은 발동하지 않아 pass로 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - answer가 IchiMozzi N4 fill-in 문제 생성 요청에 전혀 응답하지 않고 무관한 도움 제안으로 대체했다. 4개 expected_outcome이 모두 미충족(0%)이며, 할루시네이션 트랩은 발동하지 않았으나 과제 이행 실패로 fail이다.

### general_web_fact

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 공식 GitHub URL 제시, 'LLM 애플리케이션이 외부 데이터 소스와 도구에 표준화된 방식으로 접근하게 하는 프로토콜' 설명, 'Anthropic이 2024년 11월에 발표한 개방형 표준 프로토콜' 언급으로 3개 expected_outcome 모두 충족(100%)했다. OpenAI 귀속·환각 URL 트랩은 발동하지 않아 pass로 판정한다.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - modelcontextprotocol.io URL 제시, Resources·Tools·Prompts·Sampling 설명으로 외부 도구/데이터 연결 표준 프로토콜 의미 전달, '2025 Anthropic 권고 사항' 언급으로 Anthropic 설계 맥락 충족 — 3개 expected_outcome 모두 hit(100%). OpenAI 귀속·환각 URL 트랩은 발동하지 않아 pass로 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.67, traps_hit 0
  - github.com/modelcontextprotocol URL 제시와 'Anthropic 공식 발표' 언급으로 2개 항목은 충족했지만(67%), 프로토콜 자체의 목적(LLM↔외부 도구/데이터 연결 표준)에 대한 설명 없이 pre-built 서버 목록만 언급해 핵심 outcome을 놓쳤다. 할루시네이션 트랩은 발동하지 않았으나 hit률 67% < 80%로 fail이다.

### ichimozzi_deploy

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - production.yml 기반 docker compose 명령어 제시, 로컬 Docker 스택 명시(제목: '로컬 Docker'), 단계별 수동 배포 절차 제공으로 3개 expected_outcome 모두 충족(100%)했다. EC2·PM2·systemd·/home/ec2-user/ 트랩은 발동하지 않았으며(EC2는 '사용하지 말 것' 경고 문맥), pass로 판정한다.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 홈서버 Docker 실행 명시, production.yml을 사용한 docker compose 명령어 제시, 수동 절차를 직접 제공함으로써 3개 expected_outcome 모두 충족(100%)했다. EC2·nginx·PM2·CI/CD 자동화 트랩은 발동하지 않았으며 근거 기반 답변으로 pass 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - standard 조건에서 노트가 비어 있어 docker compose 명령어·홈서버 Docker 환경·수동 배포 절차 등 3개 expected_outcome 모두 미충족(0%)이다. 노트 조회 실패 후 파라메트릭 지식이나 대안적 답변 시도 없이 '어떤 정보가 필요하냐'고 되물은 것이 핵심 실패 원인이다. 할루시네이션 트랩은 발동하지 않았으나 정보 제공 자체가 없어 fail이다.

### memory_roundtrip

- **baseline** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - baseline 조건에서 rubric은 '저장 불가를 정직하게 답하거나 파라메트릭 회상 인정'을 요구하는데, 모델이 도구 호출 없이 '완료했습니다'라고 선언해 '저장하지 않고 저장했습니다만 주장' 트랩이 발동했다. 세 항목 나열은 충족했으나 저장 호출·read 회수 2개 outcome 미충족(33%)에 트랩 발동까지 겹쳐 fail이다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - openakashic 조건에서 upsert_note→read_note 라운드트립이 필수이나 단 하나의 도구도 호출되지 않아 3개 expected_outcome 전부 미충족(0%)이다. 할루시네이션 트랩('저장했습니다'만 주장, 일부만 회수)은 발동하지 않았으나 기능 자체가 미동작한 완전한 실패다.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - notes_write 저장 확인(104바이트), notes_read 회수, 세 항목(저녁 커피 금지·주말 이메일 미확인·아침 6시 30분 운동) 모두 answer에 정확히 반영되어 3개 expected_outcome 전부 충족(100%)했다. '저장만 주장'·'일부만 회수' 트랩은 발동하지 않았으며 라운드트립 조건을 완전히 만족해 pass로 판정한다.

### onboarding_openakashic

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - personal_vault/projects/personal/openakashic/README.md 시작점 제시, search_notes/read_note/upsert_note 도구 명시, 'search → read → upsert' 워크플로우 설명, doc/ 및 personal_vault/ 폴더 구조 제시로 4개 expected_outcome 모두 충족(100%)했다. 존재하지 않는 경로 형식(/vault/closed/, /kb/)·list_notes(path=...)·bootstrap_project 무조건 호출 트랩은 발동하지 않아 pass로 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - answer가 '20개 이상의 노트로 구성'이라는 구조 요약에 머물렀고, README.md를 시작점으로 제시하거나 search/writeback 절차·경로 제약을 안내하는 내용을 단 하나도 포함하지 않아 4개 expected_outcome 모두 미충족(0%)이다. 할루시네이션 트랩은 발동하지 않았으나 핵심 온보딩 안내 자체가 누락된 실패다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - answer가 '저장된 노트가 없다'는 상태 보고에 그쳐 4개 expected_outcome 전부 미충족(0%)이다. standard 조건에서 노트가 비어 있을 때 web_search 등 대안을 시도하지 않고 사용자에게 되물은 점이 핵심 실패 원인이다. 할루시네이션 트랩은 발동하지 않았으나 정보 제공 자체가 없어 fail이다.

### triage_ichimozzi_500

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 4개 expected_outcome(Caddy 우선 확인, 정확한 백엔드 컨테이너 이름, Caddy→backend→DB 순서, docker logs/compose 명령어) 모두 충족(100%)했다. EC2·nginx·DB 역순·가상 컨테이너 이름 트랩은 발동하지 않았으며(ichimozzi-api-1은 명시적 경고 문맥으로만 언급) pass로 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - 컨테이너 이름 정확 지목, Caddy 우선 확인, Caddy→backend→DB 방향성 등 3개 항목을 충족했으나(75%) '도커 로그 또는 compose 명령어 언급' 항목이 누락되어 80% 기준에 미달한다. 할루시네이션 트랩(EC2 가정, nginx, 가상 컨테이너 이름, DB 역순)은 발동하지 않았지만 hit률 75%로 fail이다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - standard 조건에서 노트가 비어 있어 컨테이너 이름·triage 순서·docker 명령어 등 4개 expected_outcome 모두 미충족(0%)이다. 대안 탐색(일반 Docker triage 지식 적용 등)을 시도하지 않고 '노트 없다'는 상태 보고만 반환한 것이 핵심 실패 원인이다. 할루시네이션 트랩은 발동하지 않았으나 정보 제공 자체가 없어 fail이다.
