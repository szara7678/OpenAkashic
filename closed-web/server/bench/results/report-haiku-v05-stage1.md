# OpenAkashicBench v0.5 — A/B Report

**Model**: `claude-haiku-4-5`  
**Conditions compared**: baseline, openakashic, standard  
**Tasks**: 7

## Summary (pass@k by condition)

| task | baseline pass@k | openakashic pass@k | standard pass@k | baseline hit rate | openakashic hit rate | standard hit rate | baseline traps | openakashic traps | standard traps |
|---|---|---|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| domain_jlpt_gen | 1 | 0 | 0 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0 |
| general_web_fact | 0 | 0 | 0 | 0.67 | 0.00 | 0.67 | 1 | 0 | 0 |
| ichimozzi_deploy | 1 | 1 | 0 | 1.00 | 1.00 | 0.00 | 0 | 0 | 0 |
| memory_roundtrip | 0 | 0 | 1 | 0.33 | 0.00 | 1.00 | 1 | 0 | 0 |
| onboarding_openakashic | 0 | 0 | 0 | 0.75 | 0.25 | 0.00 | 0 | 0 | 0 |
| triage_ichimozzi_500 | 0 | 0 | 0 | 0.75 | 0.00 | 0.00 | 1 | 0 | 0 |

## Lift: standard vs baseline (기본 에이전트 도구가 주는 이득)

| task | baseline hit | standard hit | Δ hit | baseline traps | standard traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 0.67 | 0.67 | +0.00 | 1 | 0 | -1 |
| ichimozzi_deploy | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 1.00 | +0.67 | 1 | 0 | -1 |
| onboarding_openakashic | 0.75 | 0.00 | -0.75 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.75 | 0.00 | -0.75 | 1 | 0 | -1 |
| **mean** | **0.64** | **0.24** | **-0.40** | **3** | **0** | **-3** |

## Lift: openakashic vs standard (OpenAkashic 고유 가치)

| task | standard hit | openakashic hit | Δ hit | standard traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| general_web_fact | 0.67 | 0.00 | -0.67 | 0 | 0 | +0 |
| ichimozzi_deploy | 0.00 | 1.00 | +1.00 | 0 | 0 | +0 |
| memory_roundtrip | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| onboarding_openakashic | 0.00 | 0.25 | +0.25 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| **mean** | **0.24** | **0.18** | **-0.06** | **0** | **0** | **+0** |

## Lift: openakashic vs baseline (전체 lift)

| task | baseline hit | openakashic hit | Δ hit | baseline traps | openakashic traps | Δ traps |
|---|---|---|---|---|---|---|
| busagwan_sagwan_roles | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| domain_jlpt_gen | 1.00 | 0.00 | -1.00 | 0 | 0 | +0 |
| general_web_fact | 0.67 | 0.00 | -0.67 | 1 | 0 | -1 |
| ichimozzi_deploy | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| memory_roundtrip | 0.33 | 0.00 | -0.33 | 1 | 0 | -1 |
| onboarding_openakashic | 0.75 | 0.25 | -0.50 | 0 | 0 | +0 |
| triage_ichimozzi_500 | 0.75 | 0.00 | -0.75 | 1 | 0 | -1 |
| **mean** | **0.64** | **0.18** | **-0.46** | **3** | **0** | **-3** |

## Per-task detail

### busagwan_sagwan_roles

- **baseline** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 80% 임계값에 미달해 fail이다. 다만 rubric이 예상한 대로 baseline은 이 OpenAkashic 고유 용어를 알 수 없어 정직한 '모르겠다' 응답을 택했고, hallucination trap 3개를 모두 회피한 점은 baseline 조건에서 최선의 대응이나 내용 충족 불가로 fail 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - 4개 expected_outcome 모두 미충족(0% hit)으로 fail이다. openakashic 조건에서 관련 문서를 찾았음에도 문서 내용을 깊이 읽지 않아 두 워커의 모델 차이·주기·게이트 구조가 answer에 전혀 반영되지 않았으며, 'gate-deferred' 언급이 있으나 두 워커 간 gate 관계로 명시되지 않았다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. standard 조건에서 검색 결과가 완전히 무관한 내용만 나왔고 notes도 비어있어 실질적 답변을 제공하지 못했다. 트랩은 미발동이나 핵심 내용 부재로 fail 판정한다.

### domain_jlpt_gen

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 4개 expected_outcome 모두 충족(100% hit)하며 한국어 본문 사용·동의어 선택 형식·N1/N2 어휘 트랩 어느 것도 발동되지 않았다. correctAnswer='A'는 보기 A(の筋肉)와 일치하여 순환 오류도 없고 explanation도 명시되어 있다. 형식 구조(JSON 스키마)는 검증되지 않은 추측이나, 채점 기준 내 expected_outcome 및 trap 판정 기준을 모두 통과하므로 pass 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - openakashic 조건에서 IchiMozzi 문제 형식 가이드 문서를 성공적으로 조회했음에도 그 내용을 바탕으로 실제 JLPT N4 fill-in 문제를 만들지 않아 expected_outcome 4개 모두 미충족(0% hit)으로 fail이다. 트랩은 발동하지 않았으나 핵심 출력물(문제 1개)이 완전히 부재하므로 pass 조건을 충족하지 못한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. IchiMozzi 고유 형식 정보를 못 찾더라도 일반 JLPT N4 fill-in-the-blank 4지선다 문제를 생성했어야 하나, 모델은 문제 생성을 완전히 포기했다. 트랩은 미발동이나 핵심 출력 부재로 fail 판정한다.

### general_web_fact

- **baseline** (k=1): passes 0/1, hit_rate mean 0.67, traps_hit 1
  - 2/3 hit(67%)으로 80% 임계값 미달이며, 공식 저장소 URL을 github.com/anthropics/mcp로 잘못 제시해 '존재하지 않는 환각 URL' 트랩을 발동시켰다. 프로토콜 설명 자체는 올바르지만 URL 환각과 hit율 미달 두 가지 이유로 fail 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 3개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. 이 task는 openakashic 도구 없이도 파라메트릭 지식으로 답할 수 있는 일반 웹 사실임에도, 모델은 도구 호출을 생략하면서 답변 자체도 제공하지 않아 완전히 실패했다. 트랩은 미발동이나 답변 부재로 fail 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.67, traps_hit 0
  - URL 제시와 Anthropic 맥락 2개 hit으로 2/3(67%)이며 80% 임계값 미달이다. 검색 결과 스니펫에 'MCP allows applications to provide context for LLMs'가 있었음에도 답변에서 프로토콜 목적 설명을 생략했다. 트랩은 미발동이나 hit율 미달로 fail 판정한다.

### ichimozzi_deploy

- **baseline** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 3개 expected_outcome 모두 충족(100% hit)했다: production.yml docker compose 명령어 명시, /home/insu/ 로컬 홈서버 Docker 스택과 일관된 경로 사용, 자동 webhook 배포 언급 없이 수동 절차만 서술. EC2/AWS/PM2/systemd 트랩 4개 모두 미발동이므로 pass 판정한다.
- **openakashic** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 3개 expected_outcome 모두 충족(100% hit)했다: docker compose 프로덕션 스택 재빌드 언급, /home/insu/ 로컬 홈서버 경로로 일관된 Docker 스택 답변, 수동 절차(npm run build → docker compose)만 명시. EC2/AWS/PM2/systemd 트랩 4개 모두 미발동이고 인용 경로도 tool_calls receipt에서 확인되므로 pass 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 3개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. 트랩은 모두 회피했으나 답변 자체가 부재하며, notes가 없더라도 Docker 기반 배포 절차를 일반적 수준에서라도 제시했어야 한다.

### memory_roundtrip

- **baseline** (k=1): passes 0/1, hit_rate mean 0.33, traps_hit 1
  - rubric에 따르면 baseline은 '저장 불가를 정직하게 고지'해야 pass인데, 이 답변은 tool_calls 없이 '저장했습니다'라고 허위 주장하여 핵심 트랩을 발동시켰다. 저장 호출·읽기 호출 두 expected_outcome이 모두 미충족(1/3 hit, 33%)이며 트랩도 발동했으므로 fail 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - upsert_note가 body 필드 누락으로 실패해 실제 저장이 이루어지지 않았고, 결과적으로 세 선호사항을 저장·회수하는 expected_outcome 3개 모두 미충족(0% hit)으로 fail이다. 트랩은 미발동이나 API 시그니처 오류로 인한 라운드트립 실패가 근본 원인으로 fail 판정한다.
- **standard** (k=1): passes 1/1, hit_rate mean 1.00, traps_hit 0
  - 3개 expected_outcome 모두 충족(100% hit)했다: notes_write 저장 호출 수행, notes_read 회수 후 세 항목 모두 answer에 포함, 세 선호사항 정확히 반영. '저장하지 않고 저장했다고 주장' 트랩도 미발동(실제 tool_calls 존재)이므로 pass 판정한다.

### onboarding_openakashic

- **baseline** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 0
  - 도구 목록(search_notes, upsert_note 등), 작업 전후 절차, personal_vault//doc/ 경로 제약은 올바르게 설명해 3/4 hit(75%)이나 80% 임계값 미달이다. 가장 중요한 기준인 '실존하는 시작점 경로 제시'가 미충족으로, README.md 등 표준 진입점 대신 검증 불가한 날짜 기반 파일명을 1순위로 제시했다. 트랩은 미발동이나 hit율 미달로 fail 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.25, traps_hit 0
  - 실존 경로 README.md를 tool_calls receipt에서 확인해 1/4 hit(25%)이나 80% 임계값에 크게 미달해 fail이다. search_and_read_top을 실제 사용했음에도 답변 본문에서 도구 사용 방법, 작업 전후 절차, personal_vault//doc/ 경로 제약을 전혀 설명하지 않아 온보딩 가이드로서 핵심 내용 3개가 누락되었다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. 트랩은 모두 회피했으나 실제 온보딩 내용이 부재하며, standard 조건에서 검색 결과가 빈약해도 OpenAkashic 문서 구조(personal_vault/, doc/ 경로 등)에 대한 최소한의 안내는 제공했어야 한다.

### triage_ichimozzi_500

- **baseline** (k=1): passes 0/1, hit_rate mean 0.75, traps_hit 1
  - Caddy 우선 확인, 프록시→앱→DB 순서, docker logs 절차는 올바르게 제시해 3/4 hit(75%)이나 80% 임계값 미달이다. 결정적으로 백엔드 컨테이너명을 insu-server-backend-prod-1이라는 존재하지 않는 이름으로 명시했는데 이는 실제 컨테이너명 ichimozzi-migration-backend-prod-1과 다른 hallucinated 이름으로 '가상 컨테이너 이름' 트랩을 hit했다. hit율 미달과 트랩 발동 두 이유로 fail 판정한다.
- **openakashic** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 fail이다. container-naming.md를 발견하고도 내용을 읽어 컨테이너 이름과 순서를 추출하는 단계로 나아가지 않아, 핵심 정보(insu-shared-caddy, ichimozzi-migration-backend-prod-1, triage 순서)가 answer에 전혀 포함되지 않았다. 트랩은 미발동이나 답변 부재로 fail 판정한다.
- **standard** (k=1): passes 0/1, hit_rate mean 0.00, traps_hit 0
  - expected_outcome 4개 모두 미충족(0% hit)으로 80% 임계값에 한참 못 미쳐 fail이다. 트랩은 모두 회피했으나 답변 자체가 부재하며, notes가 없더라도 일반 Docker/Caddy 스택 기반으로 최소한의 triage 절차와 명령어를 제공했어야 한다.
