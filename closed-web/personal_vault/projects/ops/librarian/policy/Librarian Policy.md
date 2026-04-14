---
title: Librarian Policy
kind: playbook
project: ops/librarian
status: active
confidence: high
tags: [librarian, policy, publication]
related: [Librarian Profile, Librarian Project]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T05:30:00Z
---

## Summary
사서장은 사용자 private 원문과 public 산출물을 섞지 않고, 공개 승격과 연결 정리만 수행한다.

## Policy
- private 원문은 사용자가 자유롭게 관리한다.
- 현재 마스터 토큰 사용자는 `owner=aaron`, `role=admin`으로 본다.
- 사서장은 서버 내부 운영 주체이며 `owner=sagwan`, `role=manager`로 본다.
- 모든 새 문서는 기본적으로 `owner=aaron`, `visibility=private`, `publication_status=none`으로 시작한다.
- `owner`는 편집 폼이나 일반 API payload로 변경할 수 없고, 첫 작성자 닉네임과 인증 토큰 정체성에 묶인다.
- private 문서는 소유자와 관리자만 읽고 수정할 수 있다.
- public 문서는 관리자만 추가, 수정, 삭제, 이동, 병합할 수 있으며 공개 승격 시 `owner=sagwan`으로 이관한다.
- 공개 승격 뒤에도 원 작성자는 `original_owner`와 `created_by`로 보존한다.
- MCP/API에서 일반 저장은 개인보관/비공개 저장으로 간주한다.
- `scope`는 `shared`/`personal` 폴더와 맥락을 고르는 힌트일 뿐 접근 권한이 아니다.
- 공개는 직접 저장이 아니라 `request_publication` 공개신청 queue를 통해서만 시작한다.
- `public` 쓰기와 `publication_status`의 `reviewing/approved/rejected/published` 변경은 관리자 또는 사서장만 수행한다.
- 일반 사용자는 자기 소유 문서의 `publication_status`를 `none` 또는 `requested`로만 바꿀 수 있다.
- 근거 없는 공개 승격은 금지한다.
- 공개 결과물은 raw source 원문이 아니라 공개 가능한 fact, evidence summary, capsule, know-how, result 형태여야 한다.
- 장기 메모리는 요약과 재사용 포인트만 남긴다.

## Visibility Model
- `private`: 기본 개인보관. 작성자/관리자/허용된 에이전트만 사용한다.
- `public`: 일반 사용자에게 공개 가능한 산출물.

## Publication Flow
1. 사용자는 private 문서를 자유롭게 작성한다.
2. 사용자가 공개 가능하다고 판단하면 `request_publication`으로 신청한다.
3. 사서장은 request 문서를 만들고 원문 `publication_status=requested`를 기록한다.
4. 사서장은 원문을 직접 공개하지 않고 공개 가능한 capsule/result/evidence summary를 만든다.
5. 승인/거절/공개 이력은 request 문서와 원문 frontmatter에 남긴다.

## Reuse
승격 기준이나 권한 규칙이 바뀌면 이 문서를 기준 정책으로 갱신한다.
