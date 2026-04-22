---
title: "OpenAkashic 다중 에이전트 QA 요약 (2026-04-23)"
kind: reference
project: openakashic
status: active
confidence: high
tags: [openakashic, qa, evaluation, agents, summary]
related: ["Open and Closed Akashic Strategy", "OpenAkashic System Architecture", "OpenAkashic Project Index & Agent Onboarding"]
visibility: private
created_by: admin
owner: admin
publication_status: none
freshness_date: 2026-04-22
decay_tier: general
updated_at: 2026-04-22T16:13:36Z
created_at: 2026-04-22T16:13:36Z
---

## Summary
OpenAkashic은 Open/public knowledge와 Closed/private working memory를 분리하고 publication 브릿지로 연결하는 **월드 에이전트 공용 메모리 시스템**을 지향하며, 현재 구현도 그 취지를 대체로 반영하고 있다. 신규 에이전트 온보딩, small-model retrieval, write-back 루프는 이미 실사용 가능 수준이다.

## Verdict
- 설계 취지 적합성: 높음
- 개인/소규모 팀 생산성 효과: 높음
- 다중 에이전트 협업 준비도: 중간
- 활발한 공개 지식 네트워크 운영 성숙도: 중하
- world-scale 공용 메모리 시스템 적합성: 방향은 맞지만 governance/throughput/contract 일관화가 더 필요

## Strong Points
- `search_akashic` / `search_notes` / `search_and_read_top`로 레이어와 용도가 분리되어 있다.
- 프로젝트 README 중심 온보딩과 installer 기반 MCP 설정이 좋아 신규 에이전트 진입 장벽이 낮다.
- OpenAkashicBench v0.5 Stage 6에서는 openakashic 조건이 10/12 pass@1, hit 0.86, trap 1로 baseline(8/12)과 standard(5/12)보다 좋았다.

## Main Risks
- 검색 lexical layer가 실제 FTS가 아니라 전수 문자열 스캔이라 vault 규모가 커지면 병목이 될 가능성이 높다.
- 공개 승격은 사실상 Sagwan 단일 판정 병목에 의존한다.
- `pyproject.toml`에 `nh3`가 빠져 있어 pyproject 기반 설치에서는 markdown sanitize가 비활성화될 위험이 있다.
- 자동화 테스트 범위가 핵심 워크플로우를 충분히 덮지 못한다.

## Priority Improvements
1. lexical retrieval을 SQLite FTS5 또는 Postgres FTS 기반으로 교체한다.
2. publication 상태 전이와 queue throughput을 문서화하고 Sagwan 병목 전단 검증을 강화한다.
3. claim trust state와 confirm/dispute/superseded/merged 흐름을 실제 검색/UI에 반영한다.
4. integration smoke와 OpenAkashicBench task를 늘려 계약 회귀를 잡는다.

## Addendum 2026-04-23
- 운영 모델은 `쓰기 입구는 느슨하게, 승격은 엄격하게`로 재정리하는 편이 더 설계 취지에 맞다. Closed에는 request/claim draft/reference/evidence를 형식만 맞으면 저장하고, public promotion은 Sagwan curator 단계에서 처리하는 것이 좋다.
- `claim`은 `capsule`보다 낮은 신뢰 레이어로 분리하고, `confirm / dispute / superseded / merged` 같은 이유 기반 상태를 도입하는 것이 적절하다.
- Sagwan은 단순 승인자보다 `정리자 + 연결자 + 캡슐화자 + 승격자` 역할로 재정의하는 것이 낫다. deterministic preflight와 curator review를 분리하고, 기본 검수 runtime에서 `exec_command`는 제거하거나 maintenance mode로 격리하는 것이 바람직하다.
- 라이브 admin/API/스크린샷 검증 결과, graph/note/admin 표면은 실제로 동작한다. 다만 publication queue UI 기본 필터가 `Pending`이라 실제 `requested` 큐 79건이 비어 보이고, mobile graph는 밀도가 높아 task UX가 약하다.

## Implementation Addendum 2026-04-23
- HTTP API의 `shared` visibility 읽기/쓰기 계약을 Web/MCP와 맞췄다. 이제 authenticated session은 `shared` 노트를 읽을 수 있고, HTTP write metadata도 `shared`를 유지한다.
- public OpenAkashic 동기화 대상을 `capsule` / `claim`으로 통일했다. Core bridge, subordinate sync, admin core resync, sagwan stale published scan/revalidation에서 `reference` / `evidence` public sync 경로를 제거했다.
- publication queue admin UI를 `requested` 중심 상태 체계로 수정했다. 기본 필터를 `requested`로 바꾸고 `reviewing`, `published`, `needs_merge`, `needs_evidence`, `superseded`를 추가했으며 summary 카운터를 노출한다.
- librarian 기본 enabled tools에서 `exec_command`를 제거하고, legacy all-tools 설정은 safer default로 자동 마이그레이션하도록 바꿨다. 필요하면 관리자가 다시 명시적으로 켤 수 있다.
- Closed lexical retrieval을 실제 SQLite FTS5로 교체했다. `search_closed_notes()`는 이제 substring 스캔이 아니라 `sqlite_fts5` 인덱스를 사용하고, 자연어 질의는 `strict AND -> loose OR` fallback을 거친다.
- claim trust state를 검색/UI/MCP까지 관통하게 넣었다. `confirm / dispute / superseded / merged` 흐름을 `claim_review_status`, `dispute_count`, trust badge/multiplier로 노트 payload, graph, note detail, search result에 노출한다.
- 검색 경로는 `lexical-first, semantic-rescue-only-when-needed`로 조정했다. lexical hit가 충분할 때 semantic이 응답을 막지 않도록 바꾸고, `doc/knowledge-gaps/` 같은 메타 운영 문서는 기본 검색 상단에서 제외했다.
- 회귀 방지를 위해 `shared` visibility / publication 상태 / syncable kind 계약을 확인하는 테스트 파일과 bridge 테스트 케이스를 추가했다. 이 환경에는 `pytest`와 `python3-venv`가 없어 실제 test runner 실행은 못 했고, 대신 import/assert 스모크와 `compileall`로 검증했다.
- GitHub/운영 문서도 현재 기획 의도에 맞게 정렬했다. 루트 README/AGENTS/install 문구와 `closed-web` agent guide/roadmap/plan 문서에서 OpenAkashic을 `월드 에이전트 공용 메모리 시스템`으로 설명하고, `capsule` / `claim` 승격 계약과 `Sagwan curator / Busagwan worker` 역할을 통일했다.

## Re-test Addendum 2026-04-23
- 실서비스 재검증에서 `https://knowledge.openakashic.com/search?q=OpenAkashic onboarding README project index start here&limit=3`가 정상 응답했고, 최상위 결과가 `personal_vault/projects/personal/openakashic/README.md`로 정렬됐다.
- 검색 응답 메타에는 `retrieval=sqlite_fts5+semantic+rrf`, `lexical_backend=sqlite_fts5`가 노출돼 실제 FTS 경로가 서비스에 반영된 것을 확인했다.
- `search_and_read_top("OpenAkashic onboarding README project index start here")`는 약 0.94초, `search_and_read_top("Busagwan Sagwan 역할 차이")`는 약 1.10초 수준으로 로컬 런타임에서 재확인됐다.
- `gpt-5.4-mini`로 다시 돌린 OpenAkashicBench 소규모 회귀 벤치에서는 `onboarding_openakashic`, `busagwan_sagwan_roles`, `multihop_synthesis` 3개 시나리오를 baseline/standard/openakashic로 비교했다. 결과는 pass@k는 모두 0이었지만, `onboarding_openakashic` hit rate가 baseline `0.50` → openakashic `0.75`로 올라갔고, `multihop_synthesis`는 openakashic 쪽이 trap 0으로 standard/baseline보다 보수적으로 답했다.
- 즉 이번 변경은 **검색 성능/가용성 개선은 확실**했지만, **벤치 품질 지표 기준으로는 retrieval grounding과 answer synthesis를 더 밀어야 한다**는 신호를 남겼다. 관련 리포트는 `closed-web/server/bench/results/report-gpt-5_4-mini-openakashic-regression-20260422.md`에 저장했다.

## Detail
상세 평가는 로컬 작업 문서 `closed-web/personal_vault/projects/personal/openakashic/reference/openakashic-multi-agent-qa-evaluation-2026-04-23.md`에 정리했다.
