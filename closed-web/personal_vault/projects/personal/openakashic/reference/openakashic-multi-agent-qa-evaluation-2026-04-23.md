---

## title: "OpenAkashic 다중 에이전트 QA 및 설계 적합성 평가 (2026-04-23)"
kind: reference
project: openakashic
status: active
confidence: high
tags: [openakashic, qa, evaluation, agents, architecture, productivity]
related:
  - "Open and Closed Akashic Strategy"
  - "OpenAkashic System Architecture"
  - "OpenAkashic Project Index & Agent Onboarding"
  - "OpenAkashicBench v0.5 Stage 6 — 12 tasks (haiku, 2026-04-18)"
created_by: insu
owner: insu
visibility: private
publication_status: none

## Summary

OpenAkashic의 설계 취지는 여전히 강하다. 특히 `Open Akashic = 공개 검증 지식`, `Closed Akashic = 개인/운영 작업 메모리`, `승격 브릿지 = publication + review`라는 분리는 단순한 "에이전트 기억 시스템"이 아니라 **월드 에이전트 공용 메모리 시스템**을 지향하는 구조로서 논리적으로 타당하다.

현재 구현도 이 취지를 상당 부분 실제 제품 형태로 옮겨 놓았다. `search_akashic` 중심의 SLM-friendly 공개 레이어, `search_and_read_top` 같은 저컨텍스트 도구, 프로젝트 README 중심 온보딩, `upsert_note -> request_note_publication -> sync_published_note` 루프는 모두 "에이전트가 읽고, 일하고, 다시 남기는" 구조를 잘 반영한다.

다만 "여러 에이전트가 활발하게 참여하는 운영" 기준으로 보면 아직 세 가지가 발목을 잡는다.

1. 검색/저장소 구현이 문서가 약속하는 수준만큼 확장형이 아니다.
2. `shared` 권한, publication 대상 kind, 운영 역할 설명이 인터페이스마다 다르게 보인다.
3. 공개 승격은 사실상 Sagwan 단일 판정 병목에 걸려 있어 규모가 커질수록 큐가 쌓일 가능성이 높다.

결론적으로, OpenAkashic은 "월드 에이전트 공용 메모리 시스템이라는 취지에 맞는가?"라는 질문에 대해 **방향은 맞다**, 다만 **현재 구현은 아직 world-scale public/shared memory governance까지 완성된 상태는 아니다**라고 보는 편이 정확하다.

## Implementation Status

후속 구현으로 다음 항목은 이미 적용됐다.

- HTTP API의 `shared` visibility 계약을 Web/MCP와 통일
- public OpenAkashic sync 대상을 `capsule` / `claim`으로 통일
- publication admin UI 기본 상태를 `requested` 중심으로 수정하고 summary 카운터 추가
- librarian 기본 enabled tools에서 `exec_command` 제거

그래서 아래 본문에서 언급한 `shared` 계약 불일치와 public sync kind 불일치 문제는 **평가 시점에는 실제 이슈였지만, 지금은 1차 수정이 적용된 상태**로 읽으면 된다. 이후 후속 구현으로 Closed lexical retrieval의 SQLite FTS5화와 claim trust workflow의 검색/UI/MCP 관통 반영까지 들어갔다. 반면 Sagwan throughput, answer synthesis 품질, 테스트 런타임 부족은 여전히 남아 있다.

## 평가 기준

이번 평가는 아래 질문에 맞춰 진행했다.

- 설계 취지와 현재 구현이 실제로 같은 방향을 보고 있는가
- 새로운 에이전트가 빠르게 붙어 쓸 수 있는가
- 작은 모델/짧은 컨텍스트에서도 실질적 도움을 주는가
- 여러 에이전트가 동시에 쓰면 운영적으로 버틸 수 있는가
- 검색, write-back, publication 루프가 실제 생산성 향상으로 이어지는가

근거는 세 층에서 모았다.

- 설계 문서: `doc/general/Open and Closed Akashic Strategy.md`, `doc/general/plan.md`
- 구현 코드: `closed-web/server/app/*.py`, `api/app/*.py`, `install.sh`
- 운영/벤치 노트: `bench-v05-stage1-2026-04-17.md`, `bench-v05-stage6-2026-04-18.md`, 프로젝트 README

## 설계 취지와 잘 맞는 점

### 0. "월드 에이전트 공용 메모리 시스템" 관점에서도 방향은 맞다

이 표현으로 다시 보면 설계 핵심은 세 가지다.

- 에이전트가 각자 로컬 세션에 갇히지 않고, 공용 지식면과 작업 메모리면에 흔적을 남긴다
- private work와 public knowledge를 분리하되, explicit bridge로 연결한다
- 특정 단일 모델의 캐시가 아니라 여러 에이전트가 반복적으로 읽고 쓰고 승격하는 shared substrate를 만든다

현재 구현은 이 세 가지 방향과는 잘 맞는다.

- remote MCP / web / API가 모두 같은 지식 표면을 향한다
- `search -> work -> write-back -> publication` 루프가 제품 구조에 들어가 있다
- public Open layer와 private/shared Closed layer를 의도적으로 분리했다

즉 OpenAkashic은 철학적으로는 이미 "agent memory app"보다 **world agent shared memory substrate**에 더 가깝다.

다만 아직 부족한 부분도 명확하다.

- 세계 공용 메모리라면 인터페이스 간 권한 계약이 완전히 같아야 하는데 `shared` 계약이 아직 엇갈린다
- 세계 공용 메모리라면 publication kind와 trust state가 명확해야 하는데 `capsule/claim/reference/evidence` 계약이 아직 흔들린다
- 세계 공용 메모리라면 reviewer throughput과 moderation tooling이 강해야 하는데 Sagwan 병목이 남아 있다
- 세계 공용 메모리라면 검색이 규모 증가에 버텨야 하는데 Closed lexical path는 아직 전수 스캔이다

### 1. 레이어 분리는 설계적으로 타당하고 구현도 존재한다

설계 문서는 Open/Closed를 하나로 합치지 말고, 보안 모델과 검색 의도가 다른 두 표면으로 유지하라고 말한다. 현재 구현은 이 철학을 실제 코드 구조로 반영한다.

- 전략 문서: Open은 publishable claim/capsule, Closed는 private working memory
- 구현: `search_akashic`는 Core API를 직접 질의하고, `search_notes`는 Closed note graph를 질의한다
- 승격: `request_note_publication` 이후 `sync_published_note()`가 Core API 동기화를 담당한다

즉 설계 슬로건 수준이 아니라, 실제 요청 경로와 저장 모델이 분리돼 있다.

### 2. 에이전트 온보딩 경험은 꽤 좋다

온보딩 관점에서는 강점이 분명하다.

- `install.sh`가 여러 클라이언트용 MCP 설정을 자동 작성한다
- 프로젝트 README가 `search_and_read_top`을 1순위 진입점으로 명확히 지정한다
- `bootstrap_project()`가 프로젝트 인덱스와 폴더 구조를 빠르게 맞춰 준다
- `upsert_note()`가 `content` alias를 받아 작은 모델의 schema 실수를 흡수한다

특히 README가 "두 단계 검색 대신 `search_and_read_top`부터"라고 못 박은 것은 agent UX 관점에서 좋은 선택이다.

### 3. 작은 모델용 최적화가 실제로 존재한다

이 시스템은 "human UI를 agent가 억지로 파싱하는" 형태가 아니라, 도구 응답 자체를 agent-friendly하게 재배열한다.

- `search_akashic(mode="compact")`는 작은 페이로드를 제공한다
- `search_notes()`는 `_next.read_note` affordance를 준다
- `search_and_read_top()`는 `directive`, `note_body_preview`, `retrieval_value`를 앞에 배치해 잘림에 견디게 설계되어 있다

이건 단순 편의가 아니라, 실제 벤치 실패 패턴을 반영한 개선이다.

### 4. write-back 문화와 knowledge gap 루프가 살아 있다

OpenAkashic은 검색만 하는 RAG 도구가 아니라, 실패와 새 지식이 다시 축적되는 루프를 중시한다.

- miss query는 gap note로 전환된다
- 작업 후 `upsert_note()` / `append_note_section()`가 자연스러운 후속 행동으로 설계돼 있다
- publication request가 "개인 메모 -> 공용 캡슐" 브릿지 역할을 한다

이 점은 장기적으로 가장 큰 자산이다. 많은 도구가 retrieval은 잘해도 contribution loop가 약한데, OpenAkashic은 반대로 여기를 제품 핵심으로 둔다.

## 운영 모델 재평가: 쓰기 입구는 느슨하게, 승격은 엄격하게

이번 재검토 기준으로 보면 현재 OpenAkashic은 "쓰기 전에 너무 많은 것을 맞춰야 하는" 쪽으로 약간 기울어 있다. 설계 취지는 contribution loop를 키우는 것인데, 실제 참여 경험은 publication 계약과 검수 기대치 때문에 다소 빡빡해질 수 있다.

더 설계 취지에 맞는 운영 모델은 아래에 가깝다.

- `Closed Akashic`에는 형식만 맞으면 request/claim draft/reference/evidence/raw note를 `rate limit` 안에서 우선 저장한다
- 저장 시점에는 `private` 또는 `shared`가 기본이고, "public truth" 승격은 나중 단계로 분리한다
- `Sagwan`은 업로드 입구의 심사관이라기보다, 이미 올라온 것을 정리하고 연결하고 캡슐화하고 승격시키는 curator로 동작한다
- 검색 결과에서는 `capsule`과 `claim`을 같은 신뢰 레이어로 섞지 말고 분리한다

즉, **ingest는 느슨하게, promotion은 엄격하게**가 더 맞다.

### 권장 신뢰 레이어

- `capsule`: 대표 답변층. 기본 검색 결과의 1순위. Sagwan 또는 명시적 검토를 거친 canonical output.
- `claim`: 검토 전 또는 부분 검증 레이어이면서 기본 공개 참여 레이어. capsule보다 낮은 신뢰도로 보여주되, confirm/dispute/superseded/merged 신호로 점수 조정하며 관련 evidence와 함께 검색 가능하게.
- `reference` / `evidence`: 근거층. 상단 정답층보다는 supporting context로 노출.
- `raw note` / `request`: Closed 전용 작업 메모리. 자유 업로드 허용.

### claim 점수 모델 권장안

현재 구현도 Closed note 검색에서 `confirm_count`를 점수에 반영하고, Core API claim에는 `confidence` 개념이 이미 있으므로 확장 방향은 자연스럽다. 다만 단순 upvote/downvote보다 아래처럼 이유 있는 상호작용이 더 낫다.

- `confirm`
- `dispute`
- `superseded`
- `merged`

각 액션에는 짧은 이유 필드를 남기고, 검색 랭킹은 아래 요소를 합성하는 편이 좋다.

- 기본: lexical/semantic retrieval + claim confidence
- 가산: confirm 수, 독립 confirmer 수, evidence 수, freshness
- 감산: dispute 수, stale 상태, 충돌 상태, self-confirm만 있는 경우

UI에서는 최소한 아래 배지를 분리해서 보여주는 것이 좋다.

- `validated capsule`
- `supported claim`
- `disputed claim`
- `stale claim`

## 시나리오별 QA

### 시나리오 A. 신규 에이전트가 처음 붙는다

기대:

- 어디서 시작할지 바로 안다
- 최소 도구 호출로 핵심 문서를 읽는다
- 자기 프로젝트 메모리 위치를 알 수 있다

현재 평가:

- **좋음**

근거:

- 프로젝트 README가 `search_and_read_top(query="openakashic 온보딩")`를 첫 단계로 명시한다
- MCP 설정 자동화가 설치 스크립트에 있다
- `bootstrap_project()`가 프로젝트 구조를 바로 만든다

리스크:

- 일부 오래된 문서가 아직 Busagwan 1차 리뷰 모델을 전제로 적혀 있어 초반 학습 비용을 올린다

판정:

- **실사용 가능**

### 시나리오 B. 같은 프로젝트를 여러 에이전트가 이어받아 문제를 다시 푼다

기대:

- 이전 맥락을 검색해 바로 이어서 작업한다
- 반복 실수 없이 이전 결정/실험을 재사용한다

현재 평가:

- **좋음**

근거:

- Closed note 구조와 프로젝트 README, playbook, reference 폴더가 잘 맞물린다
- `search_notes()`와 `search_and_read_top()`가 작은 모델도 이전 노트를 읽게 설계돼 있다

리스크:

- lexical retrieval이 실제 FTS가 아니라 전수 문자열 스캔이라 노트 수가 커지면 응답 품질과 속도 모두 흔들릴 수 있다

판정:

- **지금은 유효, 규모 증가 시 재설계 필요**

### 시나리오 C. 여러 사용자가 `shared` 메모리를 함께 쓴다

기대:

- 인증된 에이전트라면 `shared` 노트를 읽을 수 있다
- MCP, Web UI, HTTP API에서 동일하게 보인다

현재 평가:

- **부분 실패**

근거:

- Web UI와 MCP는 `shared`를 읽기 가능으로 처리한다
- HTTP API의 `_can_read_frontmatter()`는 `shared` 케이스를 빠뜨린다

영향:

- 어떤 에이전트는 MCP로는 읽고, 어떤 에이전트는 HTTP API로는 못 읽는 계약 불일치가 생긴다
- "다양한 에이전트가 여러 인터페이스로 붙는다"는 설계 취지와 충돌한다

판정:

- **운영 전에 통일 필요**

### 시나리오 D. 개인 노트를 공개 가능한 지식으로 승격한다

기대:

- capsule/claim 중심으로 publication이 일관되게 동작한다
- 승격 대상 kind와 정책이 문서/코드/UX에서 동일하다

현재 평가:

- **부분 성공**

강점:

- publication request, rationale, evidence_paths, Sagwan review, Core API sync라는 큰 흐름은 닫혀 있다

리스크:

- 문서는 capsule/claim만 승격된다고 말하는데, `core_api_bridge.py`는 `reference`도 `_SYNCABLE_KINDS`에 포함한다
- 반대로 Sagwan gate는 `capsule`, `claim`만 허용한다
- Busagwan sync는 `reference`, `evidence`까지 스캔 대상으로 본다

영향:

- 에이전트 입장에서는 "reference/evidence를 공개해도 되는가?"가 인터페이스마다 다르게 보인다
- 이런 계약 불일치는 실제 contribution willingness를 떨어뜨린다

판정:

- **동작은 하나, 계약이 여러 개다**

### 시나리오 E. 작은 모델이 짧은 컨텍스트에서 도움을 받는다

기대:

- 긴 markdown 전체를 다 읽지 않고도 핵심을 잡는다
- hallucinatory trap이 줄어든다

현재 평가:

- **좋음**

근거:

- `OpenAkashicBench v0.5 Stage 1`에서는 초기 상태가 1/7 pass로 매우 약했고, 실패 원인이 synthesis/read-depth 부족으로 분석되었다
- 이후 `search_and_read_top` 중심 온보딩과 응답 재배열을 거친 `Stage 6`에서는 `openakashic = 10/12 pass@1, hit 0.86, trap 1`까지 올라왔다
- baseline 8/12, standard 5/12보다 낫다

해석:

- 이 시스템은 "있으면 무조건 좋아지는 지식베이스"가 아니라, **agent UX와 prompt contract가 맞아야 성능이 올라가는 시스템**이다
- 반대로 말하면, 현재까지의 개선이 실제 성능 향상으로 이어졌다는 증거도 이미 있다

판정:

- **생산성 향상 효과 있음**

### 시나리오 F. 일반 웹 검색이 필요한 질문이 들어온다

기대:

- OpenAkashic가 도움 안 될 때는 외부 검색/파라메트릭 fallback이 자연스럽게 이어진다

현재 평가:

- **보완 필요**

근거:

- Stage 1에서는 off-domain refusal이 명시적으로 관찰됐다
- Stage 6에서도 standard condition은 "도구가 빈 결과를 주면 회피" 문제가 남아 있다

의미:

- OpenAkashic 자체의 품질 문제라기보다, 이 도구를 사용하는 에이전트 시스템 프롬프트와 runner의 fallback 설계 문제다
- 하지만 실제 사용자 경험에서는 이것도 제품의 일부다

판정:

- **도구 자체보다 orchestration 개선 필요**

### 시나리오 G. 에이전트 수가 늘고 publication 요청이 몰린다

기대:

- 리뷰 큐가 적정 시간 안에 흘러간다
- 단일 LLM 실패가 전체 승격 파이프라인을 막지 않는다

현재 평가:

- **병목 우려 큼**

근거:

- Sagwan 기본 설정은 `approval_max_per_cycle = 10`, `interval_sec = 600`
- 단일 Sagwan이 최종 판단을 독점한다
- 버전 문서와 운영 문서 일부는 여전히 Busagwan 1차 리뷰 흐름을 설명하고 있어 실제 운영 책임을 흐리게 만든다

영향:

- private 작업 메모리는 계속 쓸 수 있어도 public layer 성장 속도는 쉽게 병목된다
- 다중 에이전트 참여가 활발해질수록 큐와 문서 불일치가 사용자 불신으로 이어질 수 있다

판정:

- **개인/소규모 팀에는 충분, 활발한 공개 지식 네트워크로 가려면 확장 전략 필요**

## 핵심 불일치와 개선 포인트

### 1. 검색 확장성: 문서는 FTS를 약속하지만 실제 lexical path는 전수 스캔이다

가장 큰 설계-구현 괴리다.

- 문서/메타는 `lexical+semantic+rrf`와 사실상 FTS급 retrieval을 기대하게 만든다
- 실제 구현은 모든 노트의 `title + summary + kind + project + path + owner + tags + body`를 합쳐 `q in haystack`, `haystack.count(q)`로 lexical score를 계산한다

문제:

- 노트 수가 커질수록 검색 비용이 선형으로 증가한다
- "활발하게 사용하는 다중 에이전트 네트워크"로 갈수록 가장 먼저 부딪힐 병목이다
- semantic cache가 완충은 해주지만, lexical 경로 자체가 FTS가 아니면 규모 대응성이 떨어진다

개선:

- SQLite FTS5 또는 Postgres FTS 기반 인덱스로 lexical layer를 분리
- 현재 RRF 구조는 유지하되 lexical 후보 생성만 인덱스 기반으로 교체

### 2. `shared` 권한 계약이 인터페이스마다 다르다

- Web UI: `shared`는 인증 사용자면 읽을 수 있다
- MCP: 동일
- HTTP API: `public` 아니면 owner/admin만 읽을 수 있다

문제:

- 에이전트 종류에 따라 동일한 note visibility가 다르게 동작한다
- 협업 메모리로서 `shared`를 도입한 의미가 약해진다

개선:

- 권한 판별 함수를 한 곳으로 모으고, Web/MCP/API가 같은 함수를 쓰게 만든다
- 계약 테스트에 `shared` read/write matrix를 추가

### 3. publication 대상 kind가 문서, gate, bridge에서 서로 다르다

- 전략 문서와 여러 가이드: `capsule`, `claim` 중심
- `core_api_bridge.py`: `reference`도 sync 대상
- `subordinate.py`: `capsule`, `claim`, `reference`, `evidence`를 스캔
- `sagwan_loop.py`: source kind는 사실상 `capsule`, `claim`만 허용

문제:

- agent가 어떤 kind로 저장해야 공개 승격이 가능한지 예측하기 어렵다
- UX에서 "될 것처럼 보이는데 실제로는 defer"가 발생한다

개선:

- publication 계약을 한 줄로 고정:
  - 옵션 A: `capsule` / `claim`만 승격
  - 옵션 B: `reference`는 Core API의 capsule 변형으로 명시 지원
- 그 계약을 `AGENTS.md`, MCP schema description, gate, bridge, sync worker에 동시에 반영

### 4. Sagwan 단일 병목은 품질에는 좋지만 규모에는 약하다

지금 구조는 품질 면에서 이해된다. 다만 활발한 다중 에이전트 참여를 목표로 하면 throughput이 낮다.

문제:

- 최종 승인자가 사실상 하나다
- 기본 배치 상한이 10건/10분이다
- LLM 장애나 reviewer backlog가 public layer 성장 속도를 직접 제한한다

개선:

- "최종 판정은 단일"을 유지하되, 전단을 더 강하게 rule-based prefilter + deterministic validation으로 자동화
- claim/capsule 구조 검증, evidence URI 검증, 금칙어/민감정보 검사를 Sagwan 이전에 끝내기
- queue metrics와 SLA를 문서화

### 5. 패키징 계약에 보안 의존성이 빠져 있다

`site.py`는 `nh3`가 없으면 markdown sanitize를 포기하고 경고만 남긴다. 그런데 `pyproject.toml`에는 `nh3`가 없고, `closed-web/server/requirements.txt`에만 들어 있다.

문제:

- `pip install .` 또는 pyproject 기반 설치에서는 `nh3`가 빠질 수 있다
- 결과적으로 markdown sanitize가 비활성화될 수 있다

이건 "에이전트 생산성"과 직접 연결되진 않지만, 외부 에이전트와 공개 note를 많이 받는 시스템에서 신뢰도에 치명적이다.

개선:

- `pyproject.toml` dependencies에 `nh3` 추가
- startup에서 optional warning이 아니라 hard failure 또는 health check red로 전환 검토

### 6. publication queue UI 상태값이 실제 계약과 어긋난다

라이브 API와 실제 admin 화면을 함께 확인한 결과, publication queue는 운영자가 큐가 비어 있다고 오해하기 쉬운 상태다.

- 실제 API `GET /api/publication/requests?limit=3`는 `status=requested`인 항목들을 반환했고 총 `79`건이 있었다
- admin 화면의 Publication 탭 기본 필터는 `Pending`
- 같은 API에 `status=pending`을 주면 실제로 `0건`이 반환된다
- UI 코드의 상태 컬러/필터는 `pending`, `approved`, `rejected`, `published`, `reviewing`을 가정하지만, 실제 주요 흐름은 `requested -> reviewing -> published/rejected`다

즉 "데이터는 있는데 기본 화면이 숨기고 있는" 상태다. 운영자 신뢰를 해치는 종류의 버그다.

개선:

- UI 기본 필터를 `requested` 또는 `requested + reviewing`로 바꿀 것
- 상태 enum을 백엔드와 단일 계약으로 고정할 것
- publication queue 상단에 `requested / reviewing / published / rejected` 카운터를 노출할 것

## Sagwan 검토/검수 방식 재평가

현재 Sagwan은 품질 관점에서는 꽤 합리적이다. 하지만 "여러 에이전트가 활발하게 기여하는 네트워크"를 목표로 보면 운영 역할을 조금 바꿔야 한다.

### 지금 방식의 장점

- private와 public 사이에 명시적 승격 게이트가 있다
- rationale 최소 길이, source path 제한, self-approval 차단 같은 governance gate가 존재한다
- LLM 판단 이전에 규칙 기반 pre-filter가 있어 완전 무방비 상태는 아니다
- 실제 운영 runtime과 queue 상태를 admin 화면에서 확인할 수 있다

### 지금 방식의 약점

- 실질적으로 단일 Sagwan이 최종 판정을 독점한다
- 기본 배치 처리량이 낮아 backlog가 커지기 쉽다
- 문서 일부는 아직 Busagwan 1차 리뷰 모델을 전제로 해서 운영 이해를 흐린다
- Sagwan tool set에 `exec_command`가 포함되어 있어 검수자/관리자의 권한 경계가 넓다
- approve/defer 중심이라 merge, duplicate, supersede, dispute 같은 curator 액션이 부족하다
- claim 수준의 상태 관리가 얕아 "검토 중이지만 검색에는 보이는 지식"을 잘 표현하지 못한다

라이브 세션 기준으로도 subordinate queue는 `done 921 / failed 111 / running 1`, publication request는 `79건`이 남아 있었다. 작은 규모에서는 감당 가능하지만, 참여가 늘면 reviewer backlog가 바로 체감될 구조다.

### 추천 개선안

#### 1. Sagwan의 역할을 "승인자"에서 "정리자 + 연결자 + 승격자"로 재정의

- upload acceptance는 schema/rate-limit 중심으로 빠르게 통과
- Sagwan은 이후에 merge, dedupe, link, capsuleize, promote를 담당
- "쓰기 허용"과 "공개 승격"을 절대 같은 문턱으로 두지 말 것

#### 2. 검수 파이프라인을 2단으로 나눌 것

- 1단 deterministic preflight:
  - schema 검사
  - visibility/publication contract 검사
  - evidence path 존재 여부
  - 민감정보/금칙어
  - duplicate / near-duplicate 탐지
- 2단 curator review:
  - claim/capsule 가치 판단
  - merge / supersede / dispute / publish 결정

이렇게 하면 Sagwan의 LLM 판단은 "정성 평가"에 집중하고, 단순 계약 검사는 자동화할 수 있다.

#### 3. publication 결과를 approve/reject만 두지 말 것

최소한 아래 상태나 액션이 필요하다.

- `requested`
- `reviewing`
- `needs_merge`
- `needs_evidence`
- `superseded`
- `published`
- `rejected`

이 구조가 있어야 Sagwan이 "안 된다"보다 "어떻게 정리되면 된다"를 남길 수 있다.

#### 4. Sagwan tool 권한을 더 좁힐 것

현재 live runtime에는 Sagwan tool로 `exec_command`가 노출된다. 운영 편의는 있겠지만, 검수자 역할과 시스템 운영자 역할이 한 프로세스에 섞이는 효과가 있다.

권장:

- 기본 검수 runtime에서는 `exec_command` 제거
- 정말 필요하면 별도 maintenance mode에서만 활성화
- publication reviewer와 ops controller를 logical role로 분리

#### 5. 큐 운영 지표를 제품 화면에 올릴 것

현재도 runtime status는 보이지만, curator 운영에 필요한 지표는 더 직접적으로 보여야 한다.

- backlog count
- oldest requested age
- avg review latency
- defer reason top categories
- merge/supersede ratio
- published claim/capsule count by week

이 지표가 있어야 "사관이 병목인지", "정말 유의미한 정제가 되는지"를 판단할 수 있다.

## 웹 화면/기능 실검증

2026-04-23 기준으로 관리자 토큰을 사용해 실제 웹/API를 확인했고, 인증된 상태로 데스크톱/모바일 스크린샷을 캡처했다. 캡처 파일은 아래에 남겨두었다.

- `/home/insu/tmp/openakashic-ui-audit/out/desktop-admin-overview.png`
- `/home/insu/tmp/openakashic-ui-audit/out/desktop-admin-publication.png`
- `/home/insu/tmp/openakashic-ui-audit/out/desktop-admin-sagwan.png`
- `/home/insu/tmp/openakashic-ui-audit/out/desktop-graph.png`
- `/home/insu/tmp/openakashic-ui-audit/out/desktop-note.png`
- `/home/insu/tmp/openakashic-ui-audit/out/mobile-admin.png`
- `/home/insu/tmp/openakashic-ui-audit/out/mobile-graph.png`
- `/home/insu/tmp/openakashic-ui-audit/out/mobile-note.png`

### 확인한 사실

- `GET /api/session` 기준 admin 세션이 정상 동작했고, admin capability와 librarian/subordinate runtime 정보가 노출됐다
- `GET /api/admin/librarian`는 Sagwan provider/model/tool 목록을 반환했다
- `GET /api/publication/requests?limit=3`는 총 `79`건의 requested queue를 반환했다
- graph, note, admin 화면은 인증 상태에서 실제 렌더링됐다

### 화면별 평가

#### Admin Overview

- 장점:
  - 관리자용 정보 구조가 단순하고 이해가 쉽다
  - session, user counts, librarian runtime, request log 상태가 한 화면에 모여 있다
  - 설계 취지인 "운영 제어면(control plane)"은 잘 드러난다
- 아쉬움:
  - 중요한 운영 지표에 비해 actionability가 약하다
  - publication backlog, queue age, failure trend 같은 "지금 막히는가" 지표가 overview에 없다

판정:

- **control plane의 골격은 좋지만 운영 깊이는 아직 얕다**

#### Admin Publication

- 장점:
  - publication queue라는 개념 자체는 명확하게 분리돼 있다
- 문제:
  - 기본 필터가 `Pending`이라 실제 `requested` 큐 79건이 비어 보인다
  - status naming이 backend contract와 달라 운영자가 잘못 이해하기 쉽다
  - approve/reject 외 curator action이 부족하다

판정:

- **설계 의도는 맞지만 현재 UX는 실제 운영 상황을 오해하게 만든다**

#### Admin Sagwan

- 장점:
  - provider/model/tool/runtime/schedule이 한 화면에 있다
  - 승인 주기와 batch 설정을 직접 볼 수 있어 운영 투명성이 있다
- 문제:
  - 검수자 tool 권한이 너무 강하다
  - queue/backlog 중심 정보보다 설정 입력칸 비중이 크다
  - "왜 defer 되었는지", "무슨 종류의 정리를 많이 하는지" 같은 reviewer UX가 없다

판정:

- **설정 화면으로는 충분하지만 검수 대시보드로는 아직 부족하다**

#### Graph Desktop / Mobile

- 장점:
  - graph 자체는 OpenAkashic의 linked-memory 철학을 강하게 드러낸다
  - selected note의 메타데이터와 open affordance가 명확하다
  - desktop에서는 knowledge graph 데모로서 인상이 좋다
- 문제:
  - 모바일에서는 그래프 밀도가 너무 높아 정보 해석성이 급격히 떨어진다
  - chat FAB가 하단 우측의 노드/라벨을 가린다
  - 초기 상태에서 모바일 사용자는 "무엇을 먼저 해야 하는지"를 바로 알기 어렵다

판정:

- **철학 표현에는 강하지만 mobile task UX는 아직 약하다**

#### Note Desktop / Mobile

- 장점:
  - 데스크톱 note 화면은 explorer + 본문 + 편집 affordance 구성이 안정적이다
  - 모바일에서도 본문 가독성은 대체로 유지된다
  - linked note / explorer 구조가 working memory 제품이라는 성격을 잘 보여 준다
- 문제:
  - 모바일에서는 상단 헤더와 고정 요소가 차지하는 세로 공간이 크다
  - chat FAB가 본문 우측 하단을 부분적으로 가린다
  - 아주 긴 문서에서는 mobile reading comfort가 다소 떨어진다

판정:

- **문서 읽기/편집 표면은 꽤 성숙했고, mobile polishing이 조금 더 필요하다**

### 실검증 범위와 한계

- production 데이터 변경을 피하려고 publication 승인, Sagwan run, user role 변경 같은 쓰기 액션은 실행하지 않았다
- 읽기 API, 세션, 큐 상태, 실제 렌더링, responsive layout, 주요 admin panel 노출 여부를 중심으로 확인했다
- Playwright는 시스템 라이브러리 부재 때문에 바로 실행되지 않았고, 필요한 런타임 라이브러리를 사용자 공간에 내려받아 우회 실행했다

### 7. 테스트 범위가 핵심 워크플로우를 거의 덮지 못한다

현재 저장소에서 확인한 자동화 테스트는 `closed-web/server/tests/test_core_api_bridge.py` 하나뿐이다.

부족한 영역:

- `search_notes` ranking / visibility
- `shared` 권한
- `request_note_publication -> set_publication_status -> sync_published_note`
- `search_and_read_top` / `_next` affordance
- install/onboarding smoke

이 상태에서는 "문서가 최신인지"보다 "계약이 실제로 안 깨졌는지"를 보장하기 어렵다.

## 실제 생산성 도움 여부

짧게 답하면 이렇다.

### 도움이 되는 부분

- 같은 프로젝트를 반복 수행하는 에이전트
- 내부 지식, 운영 절차, 프로젝트 맥락이 중요한 작업
- 작은 모델이 짧은 컨텍스트에서 빠르게 요약된 근거를 받아야 하는 작업
- write-back을 통해 다음 에이전트 성공 확률을 올리고 싶은 팀

### 아직 덜 도움이 되는 부분

- 외부 웹 검색이 주가 되는 질문
- 공개 승격 throughput이 중요한 대규모 협업
- 권한/표면 계약이 완전히 일관돼야 하는 멀티클라이언트 운영
- 노트 수가 급격히 늘어나는 대형 vault

최종 판단:

- **개인 생산성**: 이미 도움 된다
- **소규모 팀 협업**: 충분히 쓸 만하다
- **활발한 다중 에이전트 네트워크**: 가능성은 높지만, 지금 상태로는 운영 계약 정리가 먼저다

## 우선순위 개선안

### P0. ingest / promotion 운영 모델 정리

- Closed 쓰기 입구는 느슨하게 두고, publication 승격만 엄격하게 둘 것
- capsule과 claim을 검색/UI에서 별도 신뢰 레이어로 분리할 것
- claim에 confirm/dispute/superseded/merged 흐름을 도입할 것

### P0. 계약 일관화

- `shared` visibility 계약을 Web/MCP/API에서 통일
- publication 가능한 kind를 한 가지 정책으로 고정
- 오래된 운영 문서에서 "Busagwan 1차 리뷰" 설명 제거 또는 deprecated 표시

### P1. 검색 스택 재설계

- lexical retrieval을 실제 인덱스 기반으로 교체
- note 수 1k, 10k, 50k에서 검색 성능 회귀 테스트 추가

### P1. publication 파이프라인 명시화

- `requested/reviewing/needs_merge/needs_evidence/superseded/published/rejected` 상태 전이를 문서와 코드에서 동일하게 정의
- Sagwan 큐 용량, 처리량, backlog 관측 지표 추가

### P1. 테스트/벤치 강화

- integration smoke: note write, shared read, publication, core sync
- OpenAkashicBench에 `gap_writeback`, `shared_visibility`, `publication_kind_contract` task 추가

### P1. 문서/대외 설명 정렬

- GitHub 루트 README/AGENTS/install 문구를 `월드 에이전트 공용 메모리 시스템` 기준으로 통일
- `capsule` / `claim`만 public 승격된다는 계약을 README/AGENTS/agent guide에 동일하게 명시
- Busagwan 설명을 `1차 리뷰어`가 아닌 worker로 수정하고, Sagwan 설명을 curator/governor로 수정
- claim은 capsule보다 낮은 신뢰 레이어라는 설계 의도를 distillation/roadmap 문서에 반영

### P2. agent orchestration 개선

- off-domain/empty receipt 자동 fallback
- top hit preview가 얕을 때 `read_note` 강제 규칙
- retrieval miss와 tool error를 구분해 Turn-2 프롬프트에 전달

## Re-test After Implementation

후속 구현 반영 뒤 실서비스와 로컬 런타임을 다시 확인했다.

### 실서비스 검색 재검증

- `https://knowledge.openakashic.com/search?q=OpenAkashic onboarding README project index start here&limit=3`가 정상 응답했고, 최상위 결과가 `personal_vault/projects/personal/openakashic/README.md`로 정렬됐다.
- 응답 메타에 `retrieval=sqlite_fts5+semantic+rrf`, `lexical_backend=sqlite_fts5`가 노출돼 실제 FTS 경로가 live surface에도 반영된 것을 확인했다.
- 이전에는 외부 도메인 `/search`, `/api/notes`가 15~20초 read timeout에 걸렸는데, lexical-first 재구성과 `knowledge-gaps` 제외 후 동일 질의가 다시 응답했다.

### 로컬 도구 런타임 재검증

- `search_closed_notes("OpenAkashic 프로젝트 온보딩 작업 시작 순서")`는 약 0.48초 수준으로 응답했다.
- `search_and_read_top("OpenAkashic onboarding README project index start here")`는 약 0.94초에 `personal_vault/projects/personal/openakashic/README.md`를 top으로 읽었다.
- `search_and_read_top("Busagwan Sagwan 역할 차이")`는 약 1.10초 수준으로 응답했다.
- trust state smoke에서는 `confirm_note -> dispute_note -> resolve_conflict(verdict="supersede")` 흐름 뒤 frontmatter가 `confirm_count=1`, `dispute_count=1`, `claim_review_status=superseded`로 정리되는 것을 다시 확인했다.

### 벤치마크 재실행

하이쿠 대신 `gpt-5.4-mini`로 소규모 회귀 벤치를 다시 돌렸다. 대상 시나리오는 `onboarding_openakashic`, `busagwan_sagwan_roles`, `multihop_synthesis` 3개였다.

요약 결과:

- `onboarding_openakashic`
  - baseline hit rate `0.50`
  - standard hit rate `0.75`
  - openakashic hit rate `0.75`
- `multihop_synthesis`
  - baseline / standard / openakashic 모두 hit rate `0.33`
  - 다만 openakashic은 trap `0`, baseline/standard는 trap `1`
- `busagwan_sagwan_roles`
  - 세 조건 모두 hit rate `0.00`

해석은 분명하다.

- 이번 변경은 **검색 성능과 응답 신뢰성**에는 실질적으로 효과가 있었다.
- 하지만 **retrieval grounding이 곧바로 high-quality answer synthesis로 이어지지는 않는다**.
- 특히 `busagwan_sagwan_roles`는 top hit가 더 빨라졌어도, 모델이 필요한 구체 facts(Claude CLI vs Ollama gemma, cadence, gate 구조)를 final answer에 끌어오지 못했다.
- `multihop_synthesis`도 도구 사용은 했지만, 실제 컨테이너 실명 3개를 답으로 꺼내는 규율이 아직 약하다.

즉 이번 턴의 결과는 "search substrate는 한 단계 올라갔고, 이제 남은 병목은 answer assembly와 stronger read-after-search discipline"으로 요약할 수 있다.

## 최종 평가

OpenAkashic은 "에이전트 기억 시스템"이라기보다 **월드 에이전트 공용 메모리 시스템**으로 설명하는 편이 더 정확하다. 그리고 그 관점에서도 큰 방향은 맞다. 아이디어만 좋은 프로젝트가 아니라, 온보딩, 검색, write-back, publication까지 실제 사용 가능한 형태가 이미 있다. 또한 벤치 결과상 초기 실패를 학습해 agent UX를 개선했고, 그 개선이 pass rate 상승으로 이어진 근거도 있다.

하지만 지금의 강점은 **좋은 철학 + 빠른 실험 + agent UX 감각**에 더 가깝고, **규모 대응형 운영 계약**까지 완성된 상태는 아니다.

따라서 지금 시점의 가장 정확한 평가는 아래와 같다.

- 설계 취지 적합성: **높음**
- 단일/소규모 에이전트 생산성 효과: **높음**
- 다중 에이전트 협업 준비도: **중간**
- 대규모 활성 사용 대비 운영 성숙도: **중하**

핵심은 구조를 갈아엎는 것이 아니다. 이미 맞는 방향으로 가고 있다. 지금 필요한 것은 **검색 스택의 확장성 보강**, **권한/승격 계약 통일**, **Sagwan 병목을 전제로 한 운영 설계 명문화**, **벤치와 통합 테스트 강화**다.

이 네 가지가 정리되면 OpenAkashic은 "재미있는 개인 실험" 수준을 넘어서, 실제로 여러 에이전트가 반복적으로 기대고 기여하는 **월드 에이전트 공용 메모리 substrate**가 될 가능성이 충분하다.

## Evidence Sources

- 설계/전략
  - `doc/general/Open and Closed Akashic Strategy.md`
  - `doc/general/plan.md`
- 온보딩/운영
  - `personal_vault/projects/personal/openakashic/README.md`
  - `doc/agents/OpenAkashic Agent Contribution Guide.md`
  - `install.sh`
- 구현
  - `closed-web/server/app/site.py:16-46`
  - `closed-web/server/app/site.py:323-438`
  - `closed-web/server/app/mcp_server.py:629-730`
  - `closed-web/server/app/mcp_server.py:1028-1088`
  - `closed-web/server/app/mcp_server.py:1397-1403`
  - `closed-web/server/app/main.py:424-427`
  - `closed-web/server/app/core_api_bridge.py:26-27`
  - `closed-web/server/app/core_api_bridge.py:423-435`
  - `closed-web/server/app/sagwan_loop.py:46-70`
  - `closed-web/server/app/sagwan_loop.py:161-202`
  - `closed-web/server/app/sagwan_loop.py:331-435`
  - `closed-web/server/app/subordinate.py:496-532`
  - `pyproject.toml:21-28`
  - `closed-web/server/requirements.txt:1-6`
- 문서 정렬 적용
  - `README.md`
  - `AGENTS.md`
  - `llms-install.md`
  - `closed-web/README.md`
  - `closed-web/AGENTS.md`
  - `closed-web/doc/agents/agent.md`
  - `closed-web/doc/agents/OpenAkashic Agent Contribution Guide.md`
  - `closed-web/doc/agents/Distributed Agent Memory Contract.md`
  - `closed-web/doc/agents/Knowledge Distillation Guide.md`
  - `closed-web/doc/general/plan.md`
  - `closed-web/doc/general/roadmap.md`
- 벤치
  - `personal_vault/projects/personal/openakashic/bench-v05-stage1-2026-04-17.md:27-72`
  - `personal_vault/projects/personal/openakashic/bench-v05-stage6-2026-04-18.md:19-73`
