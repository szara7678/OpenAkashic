---
title: "Working Memory"
kind: reference
project: ops/librarian
status: active
confidence: high
tags: [librarian, memory]
related: ["Librarian Project", "Librarian Profile"]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T08:35:27Z
owner: aaron
visibility: private
publication_status: none
---

## Summary
사서장이 반복 작업에 재사용할 운영 메모와 주의점을 짧게 축적하는 메모다.

## Reuse
매번 모든 대화를 저장하지 말고, 다음 판단에 실제 도움이 되는 기준과 링크만 남긴다.

## 2026-04-14T01:46:59Z Reusable Note
- request: 현재 구현된 관리자 UI와 사서장 구조를 짧게 요약해줘
- takeaway: 전용 사서장 모델 런타임은 아직 서버에 연결되지 않았고, 관련 노트와 정책 구조만 준비되어 있다.

## 2026-04-14T02:10:29Z Reusable Note
- request: 한 줄로 현재 역할을 소개해줘
- takeaway: `openai-codex/gpt-5.4`는 OpenRouter 직접 모델 ID가 아니라 Codex/OpenClaw 계열의 운용 라벨로 취급해야 한다. OpenClaw를 직접 호출하지 말고 모델 사용 방식과 에이전트 운용 패턴만 참고한다.

## 2026-04-14T04:24:32Z Reusable Note
- request: 상태를 한 줄로 보고해줘
- takeaway: 사서장 런타임은 지금 OpenClaw를 직접 호출하지 않고, 그 구조를 참고한 Codex-style 운용 모드로 설정되어 있다.
참고 모델 라벨: `openai-codex/gpt-5.4`

현재 단계에서는 웹 권한, 메모리 작업공간, 도구 목록, 관련 노트 검색을 먼저 제공하고, 실제 장기 실행 에이전트 루프는 별도 런타임으로 연결해야 한다.

관련 컨텍스트:
- Librarian Project (personal_vault/projects/ops/librarian/README.md)
- Librarian Profile (personal_vault/projects/ops/librarian/profile/Librarian Profile.md)
- Librarian Policy (personal_vault/projects/ops/librarian/policy/Librarian Policy.md)
- Working Memory (personal_vault/projects/ops/librarian/memory/Working Memory.md)

요청 기록: 상태를 한 줄로 보고해줘

## 2026-04-14 Owner Governance Deployment
- Implemented bootstrap identities: `aaron` is the master-token admin and `sagwan` is the server librarian manager.
- Kept `visibility` intentionally small: `private` and `public` only; legacy source/shared/internal visibility names normalize back to `private`.
- Treated `scope` as a folder/context hint, not an authorization field.
- Added admin publication decision flow: `set_note_publication_status` and `/api/publication/status`; setting `published` makes the source note `visibility=public`.
- Deployment verified on `knowledge.openakashic.com` through API smoke test and MCP tools/list.

## 2026-04-14 Immutable Owner And Sagwan Stewardship
- Corrected the librarian identity to `sagwan`.
- Normal note writes can no longer change an existing `owner`; owner is bound to the authenticated creator nickname.
- Private notes are readable and writable only by their owner or an admin.
- Public artifacts are readable publicly, but admin/manager workflows control add, update, delete, move, and merge operations.
- Publishing preserves `original_owner` and `created_by`, then transfers current stewardship to `owner=sagwan` with `visibility=public`.
- The web token modal now mirrors the browser token into a same-site cookie so server-rendered private pages can be authorized until Google login exists.

## 2026-04-14 Graph Visibility Correction
- Restored graph visibility so `/graph-data` and `/api/graph` expose the full node/link topology regardless of note visibility.
- Tightened note opening instead: note pages and note-content APIs now require owner or admin even for public artifacts.
- This keeps relationship discovery visible while preserving content access control at the note-open boundary.

## 2026-04-14 UI Governance And Taxonomy Pass
Closed Akashic/OpenAkashic 통합 작업에서 graph inspector와 note sidebar를 같은 좌측 inspector 패턴으로 정리했다. Graph는 전체 topology를 유지하되, Explore/Search/Open Note는 현재 권한으로 열 수 있는 문서만 보여주고 선택 패널에는 owner, status, visibility, publication metadata를 함께 노출한다. `kind`는 index, architecture, policy, playbook, evidence, experiment, dataset, reference, claim, capsule, roadmap, profile, publication_request로 정규화했고, 편집기 Kind Guide가 권장 섹션과 경로 힌트를 즉시 보여주도록 연결했다. `publication_request`와 evidence 중심 공개 계약, 구현/기획 gap roadmap 문서를 OpenAkashic 프로젝트 노트에 추가했다.

## 2026-04-14 Public Read Rollback, User Auth, And Publication Request Flow
Public notes are readable again on the main site and now surface in home, explorer, and search while private notes remain owner-or-admin only. The graph inspector recovered from the runtime template bug, keeps the persistent reopen arrow, and now includes display filters for kind, owner, query, path, and degree.

A local user-account flow was added with signup, login, profile update, and token rotation endpoints plus a shared header auth modal. User tokens now resolve to user capabilities and can create personal private notes, browse public knowledge, and contribute publication requests without MCP.

Publication save flow is now verified end to end: a regular user can save a note with visibility set to public, the source note stays private under the author, publication_status becomes requested, and a librarian request note is created under the sagwan-managed publication queue. Safe OpenAkashic and shared docs were promoted to public ownership under sagwan, while company-sensitive, portfolio, ops, and personal-private materials were left private.

A follow-up bug in user account storage was fixed by remapping legacy /server paths to the active Closed Akashic vault root so signup/login now work in the deployed container environment.
