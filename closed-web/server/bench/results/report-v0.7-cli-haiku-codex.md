# OpenAkashicBench — A/B Report

**Model**: `claude-haiku-4-5`  
**Conditions compared**: cli_baseline, cli_openakashic  
**CLI harnesses**: n/a  
**Tasks**: 12

## Summary (pass@k by condition)

| task | cli_baseline pass@k | cli_openakashic pass@k | cli_baseline hit rate | cli_openakashic hit rate | cli_baseline traps | cli_openakashic traps |
|---|---|---|---|---|---|---|
| citation_integrity | 0 | 0 | 0.67 | 0.67 | 0 | 0 |
| coding_python_bug | 1 | 1 | 1.00 | 1.00 | 0 | 0 |
| coding_sql_index | 1 | 1 | 1.00 | 1.00 | 0 | 1 |
| consolidation_awareness | 1 | 1 | 0.50 | 0.62 | 0 | 0 |
| daily_email_rewrite | 1 | 1 | 1.00 | 1.00 | 0 | 0 |
| general_web_fact | 1 | 1 | 0.83 | 0.83 | 1 | 1 |
| list_reviews_first | 1 | 1 | 0.50 | 0.83 | 0 | 0 |
| memory_contract_check | 0 | 0 | 0.00 | 0.00 | 0 | 0 |
| onboarding_public_openakashic | 0 | 0 | 0.00 | 0.00 | 0 | 0 |
| public_multihop_openakashic | 0 | 0 | 0.00 | 0.00 | 0 | 0 |
| review_workflow | 0 | 1 | 0.50 | 1.00 | 1 | 1 |
| version_lineage | 0 | 0 | 0.62 | 0.75 | 0 | 0 |

## CLI conditions

### Primary benchmark: cli_openakashic vs cli_baseline

| task | cli_baseline pass@k | cli_openakashic pass@k | Δ pass@k | cli_baseline hit | cli_openakashic hit | Δ hit | cli_baseline traps | cli_openakashic traps | trap reduction |
|---|---|---|---|---|---|---|---|---|---|
| citation_integrity | 0 | 0 | +0 | 0.67 | 0.67 | +0.00 | 0 | 0 | +0 |
| coding_python_bug | 1 | 1 | +0 | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| coding_sql_index | 1 | 1 | +0 | 1.00 | 1.00 | +0.00 | 0 | 1 | -1 |
| consolidation_awareness | 1 | 1 | +0 | 0.50 | 0.62 | +0.12 | 0 | 0 | +0 |
| daily_email_rewrite | 1 | 1 | +0 | 1.00 | 1.00 | +0.00 | 0 | 0 | +0 |
| general_web_fact | 1 | 1 | +0 | 0.83 | 0.83 | +0.00 | 1 | 1 | +0 |
| list_reviews_first | 1 | 1 | +0 | 0.50 | 0.83 | +0.33 | 0 | 0 | +0 |
| memory_contract_check | 0 | 0 | +0 | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| onboarding_public_openakashic | 0 | 0 | +0 | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| public_multihop_openakashic | 0 | 0 | +0 | 0.00 | 0.00 | +0.00 | 0 | 0 | +0 |
| review_workflow | 0 | 1 | +1 | 0.50 | 1.00 | +0.50 | 1 | 1 | +0 |
| version_lineage | 0 | 0 | +0 | 0.62 | 0.75 | +0.12 | 0 | 0 | +0 |
| **mean** | **0.50** | **0.58** | **+0.08** | **0.55** | **0.64** | **+0.09** | **2** | **3** | **-1** |

## Per-task detail

### citation_integrity

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.67, traps_hit 0
  - 3가지 expected_outcome 중 2개 충족(67% < 80%). 인용 방법론은 올바르나, 출처 없는 결과 복사가 'overclaim'에 해당한다는 명시적 경계 설명이 없어 80% 기준 미달로 fail 판정.
  - 3가지 expected_outcome 중 2개 충족(67% < 80%). 인용 방법론과 식별자 사용은 올바르나, 출처 없는 복사가 'overclaim'에 해당한다는 핵심 경계 설명이 누락되어 80% 기준 미달로 fail 판정.
- **cli_openakashic** (k=2): passes 0/2, hit_rate mean 0.67, traps_hit 0
  - 3가지 expected_outcome 중 2개 충족(67% < 80%). 인용 방법론과 도구별 식별자 사용은 올바르나, 출처 없이 결과만 복사하는 행위를 'overclaim'으로 규정하는 명시적 경계 설명이 없어 80% 기준 미달로 fail 판정.
  - 3가지 expected_outcome 중 2개 충족(67% < 80%). 인용 방법론은 올바르나, 출처 없는 결과 복사를 'overclaim'으로 규정하는 명시적 경계 설명이 없어 80% 기준 미달로 fail 판정.

### coding_python_bug

- **cli_baseline** (k=2): passes 2/2, hit_rate mean 1.00, traps_hit 0
  - 세 가지 expected_outcome 모두 충족. ZeroDivisionError 진단, if not nums 가드(ValueError raise), 실행 가능한 코드 스니펫이 포함됨. 할루시네이션 트랩 항목은 전혀 언급되지 않았음.
  - 세 가지 expected_outcome 모두 충족. ZeroDivisionError 진단, if not nums 가드, 실행 가능한 코드 스니펫이 모두 포함됨. 할루시네이션 트랩(Python 2/3 나눗셈 차이, total=1, for문 오류)은 전혀 언급되지 않았음.
- **cli_openakashic** (k=2): passes 2/2, hit_rate mean 1.00, traps_hit 0
  - 세 가지 expected_outcome 모두 충족. ZeroDivisionError 진단, if not nums 가드(두 가지 형태로), 실행 가능한 코드 스니펫이 포함됨. 할루시네이션 트랩 항목은 전혀 언급되지 않았음.
  - 세 가지 expected_outcome 모두 충족. ZeroDivisionError 진단, if not nums 가드(ValueError raise 형태), 실행 가능한 코드 스니펫이 모두 포함됨. 할루시네이션 트랩 항목은 전혀 언급되지 않았음.

### coding_sql_index

- **cli_baseline** (k=2): passes 2/2, hit_rate mean 1.00, traps_hit 0
  - 세 가지 expected_outcome 모두 충족. (user_id, created_at DESC) 복합 인덱스, user_id 필터링 우선 + created_at 정렬 근거, CREATE INDEX SQL이 포함됨. 정의된 세 가지 트랩(단일 인덱스 두 개 권장, 역순, 전체 테이블 인덱싱) 모두 언급되지 않았음.
  - 세 가지 expected_outcome 모두 충족. (user_id, created_at DESC) 복합 인덱스, 컬럼 순서 근거, CREATE INDEX CONCURRENTLY SQL이 모두 포함됨. 정의된 트랩(단일 인덱스 두 개 권장, 역순, 전체 테이블 인덱싱)은 언급되지 않았음.
- **cli_openakashic** (k=2): passes 1/2, hit_rate mean 1.00, traps_hit 1
  - 세 가지 expected_outcome은 모두 충족했으나, '대안' 섹션에서 (created_at DESC, user_id) 역순 복합 인덱스를 실제 SQL과 함께 안내했으므로 reverse-order 트랩이 발동됨. 첫 번째 권장안이 더 효율적이라고 부연했더라도 역순 인덱스를 제시 자체가 strict 판정 기준에 따라 fail에 해당함.
  - 세 가지 expected_outcome 모두 충족. (user_id, created_at DESC) 복합 인덱스, user_id 동등 조건 + created_at 범위/정렬 순서 근거, CREATE INDEX CONCURRENTLY SQL이 모두 포함됨. 단일 인덱스 언급은 비효율적이라고 명시하며 권장하지 않아 트랩 미발동. 정의된 세 가지 트랩 모두 해당 없음.

### consolidation_awareness

- **cli_baseline** (k=2): passes 1/2, hit_rate mean 0.50, traps_hit 0
  - 4가지 expected_outcome 모두 미충족(0% hit). OpenAkashic의 consolidation/lifecycle 개념을 GitHub PR dismiss로 잘못 해석해 관련 도구나 3-way verdict 등을 전혀 언급하지 못함. 정의된 트랩은 발동되지 않았으나 완전한 문맥 오해로 fail 판정.
  - 네 가지 expected_outcome 모두 충족. claim_review_lifecycle=consolidated 전환, uphold/revise/supersede 3-way 판정, list_reviews(include_consolidated=True) 조회 가능, 집계에서 제외 설명이 모두 포함됨. 삭제 오안내 및 revise=supersede 혼동 트랩 모두 발동되지 않았음.
- **cli_openakashic** (k=2): passes 1/2, hit_rate mean 0.62, traps_hit 0
  - 4가지 expected_outcome 중 1개만 충족(25% < 80%). claim_review_lifecycle=consolidated 전환, 3-way 판정, aggregate 제외가 모두 언급되지 않아 consolidation 프로세스를 정확히 설명하지 못함. 정의된 트랩은 발동되지 않았으나 핵심 내용 누락으로 fail 판정.
  - 네 가지 expected_outcome 모두 충족. claim_review_lifecycle=consolidated 전환, uphold/revise/supersede 3-way 판정(의미 구분 포함), list_reviews(include_consolidated=True) 조회 안내, 집계 제외 설명이 모두 포함됨. 삭제 오안내 및 revise=supersede 혼동 트랩 모두 발동되지 않았음.

### daily_email_rewrite

- **cli_baseline** (k=2): passes 2/2, hit_rate mean 1.00, traps_hit 0
  - 네 가지 expected_outcome 모두 충족. 존댓말 변환, 지연 확인 및 일정 문의, 4문장 분량(가이드라인 내), 위협 없는 협조 요청 형태가 모두 포함됨. 반말 잔존, 장문, 발신자 사과 왜곡 트랩 모두 해당 없음.
  - 네 가지 expected_outcome 모두 충족. 존댓말 변환, 지연 확인 요청, 4문장 분량, 위협 없는 협조 요청 형태가 모두 포함됨. 반말 잔존, 장문, 발신자 사과 왜곡 트랩 모두 해당 없음.
- **cli_openakashic** (k=2): passes 2/2, hit_rate mean 1.00, traps_hit 0
  - 네 가지 expected_outcome 모두 충족. 존댓말 변환, 지연 확인 요청, 3문장 분량(가이드라인 내), 위협 없는 협조 요청 형태가 모두 포함됨. 반말 잔존, 장문, 발신자 사과 왜곡 트랩 모두 해당 없음.
  - 네 가지 expected_outcome 모두 충족. 존댓말 변환, 지연 확인 및 회신 요청, 3문장 분량(가이드라인 내), 위협 없는 협조 요청 형태가 모두 포함됨. 반말 잔존, 장문, 발신자 사과 왜곡 트랩 모두 해당 없음.

### general_web_fact

- **cli_baseline** (k=2): passes 1/2, hit_rate mean 0.83, traps_hit 1
  - expected_outcome 3개 중 2개만 충족(67% < 80%)하여 기준 미달이며, `github.com/anthropics/mcp`라는 존재하지 않는 URL을 제시해 환각 URL 트랩을 발동시켰음. 두 가지 이유 모두로 fail 판정.
  - 세 가지 expected_outcome 모두 충족. github.com/modelcontextprotocol URL과 modelcontextprotocol.io 언급, 외부 도구/데이터 연결 표준 프로토콜 설명, Anthropic 공개 오픈 프로토콜 맥락이 모두 포함됨. 정의된 두 가지 트랩(OpenAI 프로토콜 주장, /mcp/docs 형태 환각 URL)은 발동되지 않았음.
- **cli_openakashic** (k=2): passes 1/2, hit_rate mean 0.83, traps_hit 1
  - expected_outcome 3개 중 2개만 충족(67% < 80%)하여 기준 미달이며, 제시된 GitHub URL(`anthropics/model-context-protocol`)이 실재하지 않는 환각 URL로 '존재하지 않는 환각 URL' 트랩을 발동시켰음. 두 가지 이유 모두로 fail 판정.
  - 세 가지 expected_outcome 모두 충족. 올바른 github.com/modelcontextprotocol URL, LLM-외부 도구/데이터 연결 표준 프로토콜 설명, Anthropic 공개 개방형 표준 맥락이 모두 포함됨. 정의된 두 트랩(OpenAI 주장, 환각 URL) 모두 발동되지 않았음.

### list_reviews_first

- **cli_baseline** (k=2): passes 1/2, hit_rate mean 0.50, traps_hit 0
  - 3가지 expected_outcome 모두 미충족(0% hit). list_reviews 미언급, review_note 미언급, include_consolidated 옵션 미언급. 정의된 트랩은 발동되지 않았으나 OpenAkashic 전용 워크플로를 전혀 반영하지 못해 fail 판정.
  - 세 가지 expected_outcome 모두 충족. list_reviews(target) 우선 호출, 기존 리뷰 확인 후 review_note 작성 순서, include_consolidated 옵션 언급이 모두 포함됨. search_notes 오용 및 즉시 review_note 호출 트랩 모두 발동되지 않았음.
- **cli_openakashic** (k=2): passes 1/2, hit_rate mean 0.83, traps_hit 0
  - 3가지 expected_outcome 중 2개 충족(67% < 80%). include_consolidated 파라미터는 언급했으나 true(consolidated 포함)가 아닌 false로 안내해 중복 확인을 위한 전체 리뷰 조회 목적에 부합하지 않아 세 번째 항목이 miss 처리됨.
  - 세 가지 expected_outcome 모두 충족. list_reviews(target, include_consolidated=True) 명시, 확인 후 review_note 작성 순서, consolidated 포함 옵션이 모두 포함됨. search_notes 오용 및 즉시 review_note 호출 트랩 모두 발동되지 않았음.

### memory_contract_check

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task memory_contract_check not found in tasks.yaml
  - task memory_contract_check not found in tasks.yaml
- **cli_openakashic** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task memory_contract_check not found in tasks.yaml
  - task memory_contract_check not found in tasks.yaml

### onboarding_public_openakashic

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task onboarding_public_openakashic not found in tasks.yaml
  - task onboarding_public_openakashic not found in tasks.yaml
- **cli_openakashic** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task onboarding_public_openakashic not found in tasks.yaml
  - task onboarding_public_openakashic not found in tasks.yaml

### public_multihop_openakashic

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task public_multihop_openakashic not found in tasks.yaml
  - task public_multihop_openakashic not found in tasks.yaml
- **cli_openakashic** (k=2): passes 0/2, hit_rate mean 0.00, traps_hit 0
  - task public_multihop_openakashic not found in tasks.yaml
  - task public_multihop_openakashic not found in tasks.yaml

### review_workflow

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.50, traps_hit 1
  - 4가지 expected_outcome 중 0개 충족(0% hit). review_note, stance='dispute', rationale, evidence_urls/paths 모두 언급되지 않았음. 정의된 트랩은 발동되지 않았으나, 공식 dispute 워크플로를 완전히 놓쳐 fail 판정.
  - 4가지 expected_outcome은 모두 충족했으나, 분쟁 워크플로 내에서 upsert_note(kind='claim')를 보조 단계로 명시적으로 제안해 첫 번째 트랩을 발동시켰음. 트랩 원칙은 strict — 보조 용도라도 언급 자체가 fail 사유임.
- **cli_openakashic** (k=2): passes 1/2, hit_rate mean 1.00, traps_hit 1
  - 네 가지 expected_outcome 모두 충족. review_note 명시, stance='dispute', 20자 이상 rationale, evidence_urls/paths가 모두 포함됨. dispute_note를 rich review 수단으로 잘못 안내하지 않았고, upsert_note(kind='claim') 조립 안내나 존재하지 않는 도구명도 없어 세 트랩 모두 발동되지 않았음.
  - 4가지 expected_outcome은 모두 충족했으나, '더 강하게 경고를 퍼뜨리고 싶다면'이라는 맥락에서 upsert_note(kind='claim') 호출을 명시적으로 안내해 첫 번째 트랩이 발동됨. 트랩 원칙은 strict — 보조 권장이라도 언급 자체가 fail 사유임.

### version_lineage

- **cli_baseline** (k=2): passes 0/2, hit_rate mean 0.62, traps_hit 0
  - 4가지 expected_outcome 중 2개 충족(50% < 80%). supersedes 방향 설명과 최신 버전 우선 참조는 맞으나, superseded_by 필드의 반대 방향 개념과 검색 demotion mechanics가 언급되지 않아 80% 기준 미달로 fail 판정.
  - 4가지 expected_outcome 중 3개 충족(75% < 80%). supersedes/superseded_by 방향 구분, 최신 버전 우선 참조 안내는 올바르나 검색 demotion mechanics(0.35x)가 누락되어 80% 기준 미달로 fail 판정.
- **cli_openakashic** (k=2): passes 0/2, hit_rate mean 0.75, traps_hit 0
  - 4가지 expected_outcome 중 3개 충족(75% < 80%). supersedes/superseded_by 방향 구분, 최신/구버전 참조 우선순위는 올바르나 검색 랭킹 demotion의 구체적 mechanics(0.35x)가 누락되어 80% 기준 미달로 fail 판정.
  - 4가지 expected_outcome 중 3개 충족(75% < 80%). supersedes/superseded_by 방향 구분과 우선 참조 안내는 올바르나, 검색 demotion을 언급하되 0.35x 배율 등 구체적 mechanics가 누락되어 80% 기준 미달로 fail 판정.
