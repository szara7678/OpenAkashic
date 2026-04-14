---
title: Librarian Policy
kind: playbook
project: ops/librarian
status: active
confidence: high
tags: [librarian, policy, publication]
related: [Librarian Profile, Librarian Project]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T04:40:00Z
---

## Summary
사서장은 private/source/shared/public 레이어를 섞지 않고, 공개 승격과 연결 정리만 수행한다.

## Policy
- private 원문은 사용자가 자유롭게 관리한다.
- 모든 새 문서는 기본적으로 `owner=personal`, `visibility=private`, `publication_status=none`으로 시작한다.
- MCP/API에서 일반 저장은 개인보관/비공개 저장으로 간주한다.
- 공개나 공유는 직접 저장이 아니라 `request_publication` 공개신청 queue를 통해서만 시작한다.
- shared/public 쓰기는 소유자, 요청자, 근거, 공개 가능 범위 검토 뒤에만 수행한다.
- 근거 없는 공개 승격은 금지한다.
- 공개 결과물은 raw source 원문이 아니라 공개 가능한 fact, evidence summary, capsule, know-how, result 형태여야 한다.
- 장기 메모리는 요약과 재사용 포인트만 남긴다.

## Visibility Model
- `private`: 기본 개인보관. 작성자/관리자/허용된 에이전트만 사용한다.
- `source_private`: 논문, 데이터, 이미지, 재현 기록 같은 비공개 근거 원천.
- `source_shared`: 특정 팀/사용자군에만 공유되는 검증 자료.
- `derived_internal`: 공개 전 내부 요약, 검토 중 capsule, 사서장 queue.
- `public_requested`: 공개 검토가 요청된 상태.
- `public`: 일반 사용자에게 공개 가능한 산출물.

## Publication Flow
1. 사용자는 private/source 문서를 자유롭게 작성한다.
2. 사용자가 공개 가능하다고 판단하면 `request_publication`으로 신청한다.
3. 사서장은 request 문서를 만들고 원문 `publication_status=requested`를 기록한다.
4. 사서장은 원문을 직접 공개하지 않고 공개 가능한 capsule/result/evidence summary를 만든다.
5. 승인/거절/공개 이력은 request 문서와 원문 frontmatter에 남긴다.

## Reuse
승격 기준이나 권한 규칙이 바뀌면 이 문서를 기준 정책으로 갱신한다.
