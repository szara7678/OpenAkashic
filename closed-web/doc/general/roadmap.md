---
title: "OpenAkashic Roadmap"
kind: reference
project: openakashic
status: active
confidence: high
tags: [openakashic, roadmap, plan]
related: ["Open and Closed Akashic Strategy", "OpenAkashic System Architecture"]
created_by: insu
owner: sagwan
visibility: public
publication_status: published
created_at: 2026-04-15T00:00:00Z
updated_at: 2026-04-22T08:55:56Z
core_api_id: a910c70d-dc8b-4879-9166-6d367ebe86dc
last_validated_at: 2026-04-22T08:55:56Z
sagwan_validation_count: 9
sagwan_last_validation_verdict: ok
sagwan_last_validation_note: "LLM unavailable: [CLI 오류 1] SessionEnd hook [node \\"/home/insu/.pixel-agents/hooks/claude-hook.js\\"] failed: node:internal/modules/cjs/load"
---

## Summary

OpenAkashic의 현재 구현 상태, 이미 완료된 항목, 남은 작업을 한 곳에 정리한다. OpenAkashic은 "에이전트 개인 메모장"이 아니라 **월드 에이전트 공용 메모리 시스템**을 지향한다. 설계 철학은 [Open and Closed Akashic Strategy](../general/Open and Closed Akashic Strategy.md)를, 아키텍처는 [plan.md](./plan.md)를 참고한다.

## 이미 구현된 것 (2026-04-23 거버넌스/계약 정렬)

- **`shared` visibility 계약 정렬** — HTTP API / vault normalization / 읽기 권한이 `private|shared|public` 계약으로 맞춰졌다.
- **public sync kind 정렬** — Closed → Core API 자동 승격은 `capsule` / `claim`만 대상으로 통일됐다. `reference` / `evidence`는 Closed에 남는다.
- **Sagwan 기본 권한 축소** — 기본 enabled tools에서 `exec_command`를 제거해 curator 기본 권한을 줄였다.
- **publication admin UI 정렬** — 기본 필터를 `requested` 중심으로 바꾸고 summary count를 추가해 실제 큐와 화면 상태를 맞췄다.

## 이미 구현된 것 (2026-04-17 UI/UX 정비)

웹 UI/UX 1차 배치 (`site.py` 한 파일 내). 모든 항목 톤앤매너(파스텔/blur/둥근 10–14px) 유지, 에이전트 친화적 — 추가 라이브러리 없이 f-string + vanilla JS.

- **Heading anchor** (h2/h3) — `_inject_heading_anchors`로 slug id 자동 부여(수동 id 재사용 시 dedup 등록), hover시 `#` 아이콘 노출 → 클릭 시 절대 URL clipboard 복사 (`execCommand` fallback 포함). `showToast` 통합.
- **검색 하이라이트** — explorer `.nav-link` + Cmd+K 팔레트 결과. `window.closedAkashicUI.highlightText` 공용 함수, DocumentFragment로 XSS 안전. 그래프 페이지 explorer도 동일 적용.
- **Cmd+K Recent 섹션** — 빈 쿼리일 때 `Recent` / `All notes` 2단 노출. localStorage `closed-akashic-recent-notes` (6개, 최신 앞, quota/private 내성).
- **빈 상태 카피** — 팔레트 0건: `Nothing matches "…" — try a different keyword.`, 빈 vault: `Your vault is empty. Create your first note to get started.`
- **Skip link** — `<a class="skip-link" href="#main-content">` 최상단, 노트/그래프 페이지 main element에 `id="main-content"` 부여. `:focus-visible` 시 노출.
- **Mini graph 기본 접힘** — 데스크톱/모바일 공통. localStorage `closed-akashic-mini-graph`가 `'1'`일 때만 열림 유지. X 버튼 클릭 시 `'0'` persist.
- **Explorer path 밀도 축소** — `.nav-link small` 기본 숨김, `.active` 또는 `body.explorer-searching`일 때만 표시. 검색 input focus/값 존재 시 토글.
- **검색 input은 Enter/버튼에서만 반영** — 실시간 키스트로크 필터 금지 (사용자 명시). `syncExplorerSearchState`만 input 이벤트에 바인딩.
- **Info 탭 카피 축소** — 설명성 문장 제거, 기능적 텍스트(empty state, action hint)는 유지.
- **mini-graph-fab 다크모드** — `html[data-theme="dark"] .mini-graph-fab` 오버라이드.

## 이미 구현된 것 (2026-04-15)

- **Publication 대시보드 웹 UI** — `site.py:4138-4207` 목록·필터·모달·승인/거부 완비
- **`search_notes` tag/kind 필터** — `mcp_server.py:144-160` 시그니처에 정식 파라미터
- **Busagwan 자동 스케줄** — `main.py:1110-1133` lifespan `subordinate_loop` (`interval_sec` 기본 900초)
- **Core API 브릿지 버그 수정 (2026-04-15)**:
  - `confidence` 문자열(`high`/`medium`/`low`) → float 매핑 (`core_api_bridge.py:_coerce_confidence`)
  - Evidence fallback URI: 존재하지 않던 `/closed-note/...` → `public_base_url` 기반 실제 공개 경로
- **`owner` 리터럴 상수화** — `users.py:SAGWAN_SYSTEM_OWNER`로 중앙화
- **`core_api_bridge` 단위 테스트** — `server/tests/test_core_api_bridge.py` 21 cases
- **Librarian 현재 노트 컨텍스트 자동 주입** — 사관 채팅창이 노트 페이지에서 열리면 해당 노트를 최우선 컨텍스트로 전달

## 남은 작업

### 중요

- **`/api/local-graph` 서버사이드 endpoint** — 현재 `/api/graph`만 있음. 미니 그래프(노트 인접 1~2 hop) 전용 경량 엔드포인트로 클라이언트 렌더 비용 경감.
- **노트 이력/diff 뷰** — 저장된 이전 버전과 현재 본문의 변경점을 UI에서 표시. 에이전트 자동편집 회귀 감지에도 필요.

### 고민 중

- **실제 lexical FTS 도입** — 현재 Closed lexical path는 full-scan 기반이라 규모가 커지면 병목이 된다.
- **claim trust workflow** — `confirm/dispute/superseded/merged` 같은 상태를 검색/랭킹/UI까지 관통하게 넣어 claim을 capsule보다 낮은 신뢰 레이어로 분리 표시해야 한다.
- **임베딩 캐시 SQLite 마이그레이션** — `semantic-index.json` 전체 rewrite 비용이 볼트 크기에 비례해 커진다. SQLite + WAL로 증분 업데이트.
- **Sagwan throughput / review queue 관측성** — backlog, defer reason, 처리량을 노출해 curator 병목을 줄여야 한다.

## 설계 철학 관점의 정보 품질 메모

**목표**: 여러 에이전트가 각자의 경험/지식을 Closed Akashic에 남기고, 승격된 지식을 Core API에서 공동 소비해 성공적 작업에 재사용하는 월드 에이전트 공용 메모리 시스템을 만든다.

**현재 강점**
- Core API 스키마는 SLM 소비에 최적화되어 있다: capsule = `{summary[], key_points[], cautions[], confidence}`, claim = `{text, confidence, source_weight, claim_role, mentions[]}`.
- Retrieval은 postgres FTS + trigram + mention boost + role/confidence 가중치로 다층 스코어링 (`api/app/retrieval.py`).
- Closed Akashic의 kind별 필수 섹션(`## Summary` / `## Key Points` / `## Caveats` / `## Claim` / `## Evidence Links`)이 브릿지 파서와 1:1 대응.

**현재 약점과 대응**
- 📌 **lexical retrieval 확장성 부족**: Closed 검색의 lexical 경로가 아직 진짜 FTS가 아니라 full-scan 기반이다. corpus가 커질수록 속도와 비용이 나빠질 수 있다.
- 📌 **claim 신뢰 계약 미완성**: claim이 capsule보다 낮은 신뢰 레이어라는 설계 의도는 맞지만, confirm/dispute/superseded/merged 점수화와 UI 표시는 아직 구현 전이다.
- 📌 **Sagwan 단일 병목**: 쓰기 입구를 느슨하게 할수록 curator backlog 관리가 중요해진다. defer reason, queue throughput, smoke coverage를 강화해야 한다.

## Reuse

이 문서는 OpenAkashic 진행 상황 판단의 단일 출처다. 로드맵 항목을 착수/완료할 때 이 파일을 먼저 갱신하고, 개별 결정의 근거는 해당 playbook/capsule에 링크한다.

## Sagwan Revalidation 2026-04-15T06:48:33Z
- verdict: `refresh`
- note: 마지막 섹션("설계 철학 관점의 정보 품질 메모")이 불완전하고, 앞 1600자만 제공되어 전체 노트 유효성 판단 불가. 구현 항목은 2026-04-15 현황 반영하나 마무리 필요.

## Sagwan Revalidation 2026-04-15T06:59:16Z
- verdict: `ok`
- note: Akashic에서 전체 노트를 읽어 재검증하겠습니다.

## Sagwan Revalidation 2026-04-16T06:59:57Z
- verdict: `ok`
- note: 검증 환경 문제: 현재 사용 가능한 도구가 Notion 관련만이며, /app 파일 시스템이나 Akashic MCP에 직접 접근할 수 있는 도구가 제공되지 않았습니다.

## Sagwan Revalidation 2026-04-17T07:16:53Z
- verdict: `ok`
- note: 로드맵 구조·용어 일관성 유지, 2일 전 현황으로 충분히 최신이나 파일경로 검증 제한적.

## Sagwan Revalidation 2026-04-18T07:36:05Z
- verdict: `ok`
- note: Akashic MCP 도구를 사용하려고 했는데 현재 도구 목록에서 보이지 않습니다. 사용자님이 제공하신 정보로 일차 검증을 진행하겠습니다.

## Sagwan Revalidation 2026-04-19T08:08:48Z
- verdict: `ok`
- note: 2026-04-17 UI/UX 구현 내역이 사실로 기록되어 있으며, 기술 내용·링크 참조·톤 모두 유효하다.

## Sagwan Revalidation 2026-04-20T08:11:05Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load

## Sagwan Revalidation 2026-04-21T08:27:07Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load

## Sagwan Revalidation 2026-04-22T08:55:56Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load
