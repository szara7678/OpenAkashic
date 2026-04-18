# OpenAkashicBench v0.5 — A/B Report

**Model**: `claude-haiku-4-5`  
**Conditions compared**: baseline, openakashic, standard  
**Tasks**: 12

## Summary (pass@k by condition)

| task | baseline pass@k | openakashic pass@k | standard pass@k | baseline hit rate | openakashic hit rate | standard hit rate | baseline traps | openakashic traps | standard traps |
|---|---|---|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0 | 1 | 0 | 0.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| coding_python_bug | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | 0 | 0 | 0 |
| coding_sql_index | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | 0 | 0 | 0 |
| daily_agenda | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | 0 | 0 | 0 |
| daily_email_rewrite | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | 0 | 0 | 0 |
| domain_jlpt_gen | 1 | 0 | 0 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| general_web_fact | 1 | 1 | 1 | 1.00 | 1.00 | 1.00 | 0 | 0 | 0 |
| ichimozzi_deploy | 1 | 1 | 0 | 1.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| memory_roundtrip | 0 | 1 | 1 | 0.33 | 1.00 | 1.00 | 1 | 0 | 0 |
| multihop_synthesis | 0 | 0 | 0 | 0.67 | 0.33 | 0.00 | 2 | 1 | 0 |
| onboarding_openakashic | 1 | 1 | 0 | 1.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| triage_ichimozzi_500 | 0 | 1 | 0 | 0.50 | 1.00 | 0.00 | 2 | 0 | 0 |

## Lift: standard vs baseline (기본 에이전트 도구가 주는 이득)

| task | baseline hit | standard hit | Δ hit | baseline traps | standard traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| coding_python_bug | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| coding_sql_index | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_agenda | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_email_rewrite | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 1.00 | +0.67 | 1 | 0 | -1 |
| multihop_synthesis | 0.67 | 0.00 | -0.67 | 2 | 0 | -2 |
| onboarding_openakashic | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.50 | 0.00 | -0.50 | 2 | 0 | -2 |
| **mean** | **0.79** | **0.50** | **-0.29** | **5** | **0** | **-5** |

## Lift: openakashic vs standard (OpenAkashic 고유 가치)

| task | standard hit | openakashic hit | Δ hit | standard traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| coding_python_bug | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| coding_sql_index | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_agenda | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_email_rewrite | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| general_web_fact | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| memory_roundtrip | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| multihop_synthesis | 0.00 | 0.33 | +0.33 | 0 | 1 | +1 |
| onboarding_openakashic | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| **mean** | **0.50** | **0.86** | **+0.36** | **0** | **1** | **+1** |

## Lift: openakashic vs baseline (전체 lift)

| task | baseline hit | openakashic hit | Δ hit | baseline traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| coding_python_bug | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| coding_sql_index | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_agenda | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| daily_email_rewrite | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| ichimozzi_deploy | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 1.00 | +0.67 | 1 | 0 | -1 |
| multihop_synthesis | 0.67 | 0.33 | -0.33 | 2 | 1 | -1 |
| onboarding_openakashic | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.50 | 1.00 | +0.50 | 2 | 0 | -2 |
| **mean** | **0.79** | **0.86** | **+0.07** | **5** | **1** | **-4** |

## Per-task detail

### busagwan_sagwan_roles

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. OpenAkashic 고유 용어인 Busagwan/Sagwan은 baseline에서 알 수 없어야 하는데, 모델이 정직하게 '모른다'고 표현했으므로 hallucination_trap은 hit하지 않음. 하지만 rubric에 따라 이것은 정보 부재로 판정되어 실패 처리.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. OpenAkashic 노트에서 Sagwan(Claude CLI, 1시간, 승인/게이트), Busagwan(Ollama gemma, 10~15분, 크롤/요약/1차 리뷰), gate 관계를 정확히 설명. 모두 receipt에 기반하고 hallucination_trap은 없음.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. Standard 조건에서도 로컬 메모와 웹 검색으로 정보를 획득할 수 없었음. OpenAkashic 고유 용어(Busagwan/Sagwan)는 내부 아키텍처 문서에만 기록되어 있을 것으로 보이며, 이는 OpenAkashic 검색이나 관련 노트 경로를 직접 알아야만 접근 가능.

### coding_python_bug

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 빈 리스트 입력 시 발생하는 ZeroDivisionError를 명확히 진단하고, len(nums) == 0 체크와 동등한 if not nums: 가드를 추가한 수정된 코드를 제시함. Hallucination trap도 없음.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 빈 리스트 입력 시 발생하는 ZeroDivisionError를 명확히 진단하고, 두 가지 실행 가능한 수정 코드(0 반환 버전, None 반환 버전)를 제시함. Hallucination trap도 없음. OpenAkashic 조건이지만 일반 코딩 문제는 도구 필요 없이 파라메트릭 지식으로 충분히 해결 가능.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 빈 리스트 입력 시 발생하는 ZeroDivisionError를 명확히 진단하고, if not nums: 가드를 추가한 실행 가능한 수정된 코드를 제시함. Hallucination trap도 없음. Standard 조건이지만 도구 없이 기본 프로그래밍 지식으로 충분히 답변.

### coding_sql_index

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확한 인덱스 구조(user_id, created_at DESC)와 그 이유(동등→범위/정렬 순서), 실제 SQL 문법을 제시함. Hallucination trap도 없음 (단일 인덱스 두 개, 역순, 전체 테이블 인덱싱 주장 모두 없음).
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확한 인덱스 구조(user_id, created_at DESC), 그 이유(user_id 필터링→created_at 정렬), index-only scan 가능성까지 설명하고 실제 SQL 제시. Hallucination trap도 없음(단일 인덱스, 역순, 전체 테이블 인덱싱 주장 모두 없음).
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확한 인덱스 구조(user_id, created_at DESC), 그 이유(동등 필터→범위/정렬), DESC 명시 이유(정렬 오버헤드 제거)를 설명하고 실제 SQL 제시. Hallucination trap도 없음(단일 인덱스, 역순, 전체 테이블 인덱싱 주장 모두 없음).

### daily_agenda

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확히 3개의 어젠다(지난주 완료/주간 로드맵, 블로커/의존성, 우선순위 재확인), 각 항목의 명확한 목적, 합계 30분의 정확한 시간 배분 제시. Hallucination trap도 없음(5개 이상, 시간 생략, 불일치 등 모두 없음). Rubric의 '파라메트릭으로 바로 답하는' 요구사항 충족.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확히 3개의 어젠다(지난주 완료 사항, 이번주 주요 계획, 장애물/리스크), 각 항목의 명확한 목적, 합계 30분의 정확한 시간 배분 제시. Hallucination trap도 없음(5개 이상, 시간 생략, 불일치 등 모두 없음). OpenAkashic 조건이지만 일반적인 회의 운영은 도구 필요 없이 파라메트릭으로 충분.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 정확히 3개의 어젠다(주간 우선순위 정렬, 개인 진행 상황 및 계획, 장애물 및 협력 요청), 각 항목의 명확한 목적, 합계 30분의 정확한 시간 배분 제시. Hallucination trap도 없음(5개 이상, 시간 생략, 불일치 등 모두 없음). Rubric의 '파라메트릭으로 바로 답하는' 요구사항 충족.

### daily_email_rewrite

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 반말/욕설 없이 존댓말로 변환, 지연을 정중하게 묻고 도움을 제안하며, 정확히 3문장의 정중한 협조 요청 형태로 마무리. Hallucination trap도 없음(반말, 장문, 의도 왜곡 모두 없음). 파라메트릭 글쓰기 task로 rubric 충족.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 반말/욕설을 존댓말(요청드렸던, 전달해 주시면, 말씀해 주시기 바랍니다)로 변환, 지연을 정중하게 묻고 도움을 제안하며, 정확히 4문장의 협조 요청 형태로 마무리. Hallucination trap도 없음(반말, 장문, 의도 왜곡 모두 없음). OpenAkashic 조건이지만 일반적인 한국어 글쓰기는 도구 불필요하며 파라메트릭으로 충분.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 반말/욕설을 존댓말(여쭤봅니다, 말씀해 주시기 바랍니다)로 변환, 지연을 정중하게 묻고 도움을 제안하며, 정확히 3문장의 협조 요청 형태로 마무리. Hallucination trap도 없음(반말, 장문, 의도 왜곡 모두 없음). 파라메트릭 글쓰기 task로 rubric 충족.

### domain_jlpt_gen

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목을 만족했다: (1) 일본어 본문 + （　）형 빈칸, (2) N4 수준 어휘 4개, (3) 정답+상세 해설 포함, (4) 정답이 보기에 존재. Hallucination trap 없음 — 한국어 혼용 없고, fill-in-the-blank 형식이 정확하며, N1/N2 고급 어휘 없음.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족. 모델이 OpenAkashic 노트에서 찾은 JLPT 문제 유형(한자 읽기, 표기)은 어휘 선택 fill-in 형식이 아니며, 실제 요청된 형태의 문제를 생성하지 않음. 검색 결과에서 어휘 fill-in 유형이 없었다면, 그 사실을 명시하고 기본 지식으로 문제를 생성했어야 함.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. 모델은 로컬 메모에 저장된 형식 정보가 없다는 것을 확인한 후, 문제를 생성하지 않고 '정보가 없다'는 답변만 제시했다. 형식 정보가 없더라도 JLPT N4 표준 fill-in-the-blank 형식을 기본 지식으로 활용하여 문제를 생성하거나, OpenAkashic 등 다른 리소스 접근을 시도했어야 함.

### general_web_fact

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. 실제 GitHub 저장소를 정확히 제시하고, MCP가 LLM 에이전트와 외부 시스템을 연결하는 표준 프로토콜임을 명확히 설명하며, Anthropic의 open standard라는 맥락을 제시함. Hallucination trap도 없음.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. Anthropic의 MCP GitHub 저장소(github.com/anthropics/model-context-protocol)를 정확히 제시하고, MCP가 AI 모델과 외부 도구/데이터 소스를 연결하는 표준 프로토콜임을 명확히 설명하며, Anthropic의 설계 + 표준 프로토콜 맥락을 제시함. Hallucination trap도 없음.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. Anthropic의 MCP GitHub 저장소를 정확히 제시하고, MCP가 AI 모델과 외부 도구/데이터 소스를 연결하는 표준 프로토콜임을 명확히 설명하며, Anthropic의 설계 + 표준화 맥락을 제시함. Hallucination trap도 없음.

### ichimozzi_deploy

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. docker compose 명령어가 구체적이고 정확하며, /home/insu/insu_server 경로와 production.yml로 로컬 스택이 명시됨. 자동 webhook 배포를 언급하지 않고 수동 절차만 제시함. EC2, AWS, CodeDeploy, PM2 등 잘못된 가정은 없음.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. OpenAkashic 검색을 통해 정확한 docker compose 명령어(production.yml up -d --build backend-prod), 로컬 Docker 홈서버 명시, 수동 배포 절차를 제시함. EC2, AWS, CodeDeploy, PM2 등 hallucination_trap을 모두 회피함.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. Standard 조건에서도 로컬 정보가 없으면 OpenAkashic의 update-and-deploy playbook을 검색하거나, 기본 지식으로 docker compose 배포 절차를 제시할 수 있었음. 정보 부재로 답변 제공을 포기한 것은 부적절함.

### memory_roundtrip

- **baseline** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - Hallucination_trap #1 hit (저장하지 않고 저장했다고 주장). Baseline 조건에서는 도구가 없으므로 정직하게 '저장할 수 없습니다'라고 답해야 pass하는데, 실제 저장 없이 '로컬 메모리 저장' 주장은 거짓임. 세 항목은 정확하지만 저장/읽기 호출이 없어 라운드트립 요구사항 미충족.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. upsert_note를 통해 실제 OpenAkashic에 저장하고, result_preview에서 세 항목을 모두 검증한 후 answer에 정확히 포함함. personal_vault/preferences 경로 사용과 private 가시성 설정도 적절함. Hallucination trap도 없음.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. notes_write → notes_read 라운드트립을 정확하게 수행하고, 저장된 내용을 receipt에서 검증한 후 answer에 세 항목을 정확히 포함함. Hallucination trap도 없음.

### multihop_synthesis

- **baseline** (k=1): passes 0/1, hit_rate mean 0.67, traps_hit 2
  - Expected_outcome #1이 미충족됨 (67% hit, 80% 미만). 예시에서 기대하는 'insu-server-backend-prod-1', 'insu-server-ichimozzi-db-1', 'insu-shared-caddy' 같은 실명 대신 일반명과 의심스러운 컨테이너명 제시. Trap #2, #3 동시에 가능성 있음 (실존하지 않는 컨테이너 이름 + 일반론 회피).
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - Expected_outcome #1 미충족: '백엔드-프로드' 1개만 명확하고 나머지는 구체적 컨테이너명이 아님. #2 미충족: 각 항목별 개별 이유가 없고 전체 이유만 제시. Trap #3 hit: DB 마이그레이션, SMTP, JWT, OAuth는 구체적 컨테이너명 대신 일반적 배포 체크리스트로 회피한 형태.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨 (0% hit). Standard 조건이므로 로컬 메모 부재 후에도 OpenAkashic 검색이나 기본 지식을 활용한 답변이 필요했으나, 정보 없음 보고로 회피. Rubric에서 openakashic 우위를 기대하는 task이므로 standard도 최소한의 답변은 제공해야 함.

### onboarding_openakashic

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. Baseline 조건이지만 CLAUDE.md에 명시된 personal_vault 구조, MCP 도구(search_notes, read_note, upsert_note), 작업 흐름(작업 전 검색→작업 후 writeback)이 모두 정확하게 제시됨. Hallucination trap도 발생하지 않음.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. OpenAkashic 도구를 실제로 사용하여 검색한 결과를 기반으로 구체적인 경로(personal_vault/, doc/), 도구(search_and_read_top, read_note, upsert_note, append_note_section), 절차(작업 전 검색→작업 후 writeback)가 정확히 제시됨. Hallucination trap도 발생하지 않음.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. Standard 조건에서도 로컬 메모가 없으면 OpenAkashic을 직접 검색하거나 CLAUDE.md의 기본 지시문을 활용하여 온보딩 가이드를 구성할 수 있었음. 정보 부재로 요청을 포기한 것은 부적절함.

### triage_ichimozzi_500

- **baseline** (k=1): passes 0/1, hit_rate mean 0.50, traps_hit 2
  - Triage 순서 방향성과 docker 명령어는 맞으나, 핵심 정보가 틀림: (1) 리버스 프록시가 nginx가 아닌 Caddy, (2) 백엔드 컨테이너 이름이 insu-server-backend-prod-1이 아닌 다른 이름을 가정. Baseline 조건에서 실제 토폴로지 노트를 참고하지 않아 두 개의 할루시네이션 trap을 hit함.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 모든 expected_outcome 항목이 충족됨. OpenAkashic 검색을 통해 실제 홈서버 토폴로지와 Triage runbook을 기반으로 정확한 Caddy/backend 컨테이너명, 프록시→앱→DB 순서, docker logs/compose 명령어를 제시함. Hallucination trap도 발생하지 않음.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 모든 expected_outcome 항목이 미충족됨. Standard 조건에서 로컬 정보가 없을 때, OpenAkashic(개인 프로젝트 vault)에서 insu-server 배포/system-snapshot 노트를 검색하거나, 최소한 구체적인 triage 절차를 기본 지식으로 제공할 수 있었음. 정보 부재를 이유로 답변을 포기한 것은 부적절함.
