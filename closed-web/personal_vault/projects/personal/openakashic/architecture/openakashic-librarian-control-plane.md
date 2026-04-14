---
title: "OpenAkashic Librarian Control Plane"
kind: architecture
project: personal/openakashic
status: active
confidence: high
tags: [openakashic, architecture, librarian, closed-akashic, control-plane]
related: ["Closed Akashic User Scope Review", "Librarian Project", "Agent Guide"]
updated_at: 2026-04-14T08:20:24Z
created_at: 2026-04-14T01:52:31Z
owner: sagwan
visibility: public
publication_status: published
created_by: aaron
original_owner: aaron
---

## Summary
OpenAkashic/Closed Akashic를 하나의 제어면(control plane)으로 다루되, 사용자 private 작업과 공개 승격 레이어는 분리하는 방향으로 현재 구현과 다음 확장 방향을 정리한다.

## Current Implementation
- Closed Akashic 웹 UI는 공통 고정 헤더, 관리자 토큰 모달, 관리자 전용 편집 버튼, 관리자 전용 사서장 플로팅 채팅 UI를 공유한다.
- 노트 페이지의 하단 인라인 저장/취소/헤딩/체크리스트/콜아웃/이미지/파일 버튼은 제거하고, 상단 공통 헤더의 Edit/Save/Cancel 흐름으로 통일했다.
- 관리자 권한은 `CLOSED_AKASHIC_TOKEN`으로 판정하며, 유효하지 않으면 편집 버튼과 사서장 UI가 노출되지 않는다.
- 사서장은 현재 `exec_command`, `search_notes`, `read_note`, `append_note_section`, `upsert_note` 도구를 가진 서버측 운영 에이전트로 구현했다.
- 사서장 활동은 `personal_vault/projects/ops/librarian/` 아래의 profile/policy/memory/activity 구조에 계속 기록된다.
- 검색은 lexical 검색에 더해 local multilingual embedding(`intfloat/multilingual-e5-small`) 기반 semantic ranking을 섞는다.

## Control Plane Shape
- 단일 MCP와 단일 관리자 제어면을 유지한다.
- 내부 저장 모델은 두 논리 계층으로 유지한다: private/source memory layer 와 shared/public knowledge layer.
- 일반 사용자는 공개 가능한 fact/evidence/capsule/result 중심으로 소비한다.
- shared/public 승격은 사용자의 직접 쓰기보다 서버측 사서장 검토와 정책 적용을 거친다.

## Next Steps
- Google 로그인, 토큰 발급, 닉네임 수정, 역할 부여 기반 ACL을 붙인다.
- `scope`는 폴더/맥락 힌트로 유지하고 권한은 `owner`, `visibility`, `publication_status`로 판단한다.
- source asset(문서, 이미지, 데이터, 논문, 재현 기록)과 derived artifact(fact, evidence summary, capsule, know-how)를 분리 저장한다.
- 사서장에 publish-review, evidence-linking, duplicate-merge, memory distillation playbook을 추가한다.
- OpenAI API 키가 서버 환경에 들어오면 현재 Codex 계열 모델 호출을 실제 운영 응답 경로로 활성화한다.
- 의미검색은 현재 local embedding cache를 기반으로 하고, 추후 asset chunking과 권한 필터를 함께 얹는다.

## Reuse
다음 구현에서는 이 노트를 기준으로 ACL, 공개 승격 파이프라인, 사서장 플레이북을 확장한다.

## 2026-04-14 Deployment Correction
- `knowledge.openakashic.com` was still serving the old `closed-akashic-web` container because the Docker service had not been rebuilt/restarted after local UI changes.
- Rebuilt and restarted `ichimozzi-migration-closed-akashic-web-1`; public HTML now includes the fixed global header, token modal, admin-only librarian shell, and no residual `New Page/New Folder` or bottom save/cancel controls.
- OpenClaw is treated as an architecture/reference pattern, not a runtime API or credential source. The librarian status now reports `provider=codex-style` and model label `openai-codex/gpt-5.4`; direct long-running agent runtime remains a future integration.
- Semantic search now uses Ollama `nomic-embed-text` through the shared Docker network `openakashic-prod_default`, with document text truncated to 1200 chars and batched by 16. First index build populated 366 docs; cached semantic searches return in about 1 second.
- GPU diagnosis: host RTX 3060 is visible, but Docker has no NVIDIA runtime/container toolkit and Ollama logs show CPU-only execution. GPU enablement requires installing/configuring NVIDIA container toolkit/CDI and then restarting the Ollama compose stack with GPU device requests.

## 2026-04-14 Governance Metadata And Publication Requests
- Implemented note governance metadata defaults: new writes now get `owner=aaron`, `visibility=private`, and `publication_status=none` unless explicitly overridden.
- Added publication request workflow: `/api/publication/request`, `/api/publication/requests`, MCP tools `request_note_publication` and `list_note_publication_requests`.
- Publication requests keep the source note private, mark it `publication_status=requested`, and create a private librarian queue note owned by `sagwan` under `personal_vault/projects/ops/librarian/publication_requests/`.
- Updated the web note info/editor surfaces to show and edit owner, visibility, and publication status.
- Updated librarian policy and user scope review docs to state that MCP/API writes are private by default and public exposure must go through librarian review to produce public fact/evidence summary/capsule/know-how artifacts rather than raw source disclosure.
- Verified via public API: default private metadata, publication request creation, source request markers, request listing, MCP tool exposure, and cleanup of smoke-test notes.

## 2026-04-14 Owner And Publication Governance Correction
- Bootstrap identities are now explicit: master-token admin is `aaron`; server librarian manager is `sagwan`.
- `visibility` is intentionally small: only `private` and `public`.
- `publication_status` carries the review state: normal users can set only `none` or `requested` on their own notes; admin/manager decisions use `reviewing`, `approved`, `rejected`, or `published`.
- `scope` remains only a folder/context selector for `shared` common knowledge/opinion versus `personal` personal information/opinion, not an authorization primitive.
- Added admin/API/MCP publication decision path so `published` records the decision and flips the source to `visibility=public`.

## 2026-04-14 Immutable Owner And Public Stewardship
- Corrected the librarian identity spelling to `sagwan`.
- Owner is no longer editable through the web editor or normal note write payloads; new private notes bind owner to the authenticated creator nickname.
- Private read/write is limited to owner and admin.
- Public artifacts are readable as public knowledge, but only admin/manager workflows may add, modify, delete, move, or merge them.
- Publishing records `original_owner`, keeps `created_by`, transfers current stewardship to `owner=sagwan`, and sets `visibility=public`.
- The web token modal now mirrors the token into a same-site cookie so server-rendered private pages can be authorized before login exists.
