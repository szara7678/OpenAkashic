---
title: "OpenAkashic Roadmap Gap Review"
kind: roadmap
project: personal/openakashic
status: active
confidence: high
tags: [roadmap, gaps, implementation, librarian]
related: ["OpenAkashic Knowledge Taxonomy", "Publication Evidence Contract", "OpenAkashic Librarian Control Plane"]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T10:38:57Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
현재 구현은 owner/admin 권한 경계, public 승격 소유권 이전, 그래프/탐색 노출 제어, 사서장 기본 제어면, kind 정규화까지 들어왔다. 아직 로그인 기반 사용자 체계, 공개 산출 자동화, evidence 중심 publish UX, 임베딩/검색 운영면은 더 구체화가 필요하다.

## Current State
- private 노트는 owner/admin만 읽고 수정한다.
- public 산출은 관리자 계층만 수정하고 steward owner는 `sagwan`으로 이동한다.
- 그래프는 전체 관계를 유지하지만, Explore/Search/Open Note는 현재 권한으로 열 수 있는 문서만 보여준다.
- note/graph 좌측 패널은 공통 헤더와 접힘 애니메이션이 있는 inspector 스타일로 수렴했다.
- 사서장 identity와 기본 채팅/상태 surface, publication queue, observability surface가 존재한다.
- kind는 최소 집합으로 정규화되고, 편집기에서 Kind Guide로 권장 구조를 보여준다.

## Gaps
- 웹은 아직 진짜 로그인 기반 사용자 시스템이 아니라 토큰 기반 관리자 중심이다.
- owner identity는 닉네임/토큰에 묶였지만, Google 로그인 이후 사용자 CRUD와 역할 관리가 아직 없다.
- publication request에 evidence를 붙이는 전용 웹 폼과 검토 UI가 부족하다.
- public claim/capsule 전용 뷰, provenance 뷰, 공개 라이브러리 UX가 아직 약하다.
- 사서장의 메모리 축적은 시작됐지만, 주기적 정리 작업 budget과 rewrite policy가 아직 자동화되지 않았다.
- 임베딩은 로컬 의미 검색 기반이 있으나 모델 운영, GPU health check, 재색인 스케줄링은 더 손봐야 한다.

## Next Milestones
1. Google 로그인, 사용자 닉네임, 역할, 웹 세션 체계를 붙인다.
2. publication request 작성 화면과 evidence 첨부/선택 UI를 만든다.
3. public claim/capsule 브라우징 화면과 provenance 패널을 만든다.
4. 사서장 background job이 지정 범위만 재정리하도록 budgeted maintenance loop를 구현한다.
5. 임베딩 모델 선택, GPU 경로, 재색인 작업, 검색 품질 측정을 운영 플레이북으로 묶는다.
6. public 레이어와 private 레이어를 나누는 API surface를 명확히 분리한다.

## Open Questions
- public 산출을 원문 note 그대로 둘지, claim/capsule 전용 스키마로 더 엄격히 분리할지
- publication request를 문서 kind로만 둘지, 별도 DB queue도 병행할지
- 사서장의 장기 메모리를 같은 vault에 둘지, 일부는 별도 operational store로 뺄지
- evidence 노트와 asset provenance를 어느 수준까지 자동 추적할지

## Reuse
새 구현을 시작할 때는 이 문서의 Gaps를 기준으로 우선순위를 잡고, 완료되면 Current State를 갱신한다.

## 2026-04-14 Graph Permission And Agent Workflow Implementation
- commit: `399f13b feat: align openakashic access and agent workflow`
- UI: graph nodes now carry server-side `can_open`; unauthorized private nodes keep graph relationships visible but hide the sidebar `Open Note` action and cannot be opened by double click.
- Auth: login/signup/logout now reload the page after token changes so server-rendered permissions update immediately.
- Branding: main web surface, FastAPI title, MCP instructions, public vault index, and key agent docs now use OpenAkashic as the product name while compatibility aliases remain for `closed-akashic://` resources and `CLOSED_AKASHIC_TOKEN`.
- Agents: added Busagwan subordinate worker/chat, admin settings panel, first publication review loop, crawl/capsule task skeleton, and Sagwan/Busagwan chat tabs.
- Public knowledge: added development and Japanese learning resource maps plus public capsule bundles for agent retrieval.
- Validation: local py_compile, rendered JS syntax, graph/search permission smoke, Docker rebuild via `/home/insu/insu_server/compose/production.yml`, public `/health`, `/graph-data`, `/search`, `/admin`, `/api/session`, and authenticated `/mcp/ resources/list` all passed.
- Remaining cleanup: old historical notes still contain some Closed Akashic titles for migration context; decide later whether to rewrite or archive them.
