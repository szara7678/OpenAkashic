---
title: Librarian Project
kind: index
project: ops/librarian
status: active
confidence: high
tags: [project, ops, librarian, agent]
related: [Agent Guide, Distributed Agent Memory Contract, OpenAkashic Project]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary
사서장 에이전트의 정책, 프로필, 메모리, 플레이북, 활동 로그를 관리하는 작업 공간이다.

## Memory Map
- `profile/` 사서장의 역할, 페르소나, 기본 툴 설명
- `policy/` 공개 승격과 권한 처리 규칙
- `memory/` 재사용 가치가 높은 운영 메모
- `activity/` 날짜별 활동 로그
- `playbooks/` 반복 작업 절차
- `reference/` 구현 참고와 연결 메모

## Working Agreement
- private/source/shared/public 레이어를 섞지 않는다.
- 사서장은 공개 승격과 구조 정리에 집중한다.
- 장황한 전체 세션 로그 대신 재사용 포인트만 메모리로 남긴다.

## Reuse
사서장 관련 구현이나 정책을 바꿀 때는 이 인덱스를 먼저 열고 관련 노트를 갱신한다.
