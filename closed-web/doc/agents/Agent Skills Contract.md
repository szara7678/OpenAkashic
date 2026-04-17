---
title: Agent Skills Contract
kind: policy
project: openakashic
status: active
confidence: high
tags: [agents, skills, token, governance, openakashic]
related: [OpenAkashic Agent Contribution Guide, OpenAkashic Skills Guide, Knowledge Distillation Guide, AGENTS, OpenAkashic MCP Guide]
owner: sagwan
visibility: public
publication_status: published
created_by: aaron
original_owner: aaron
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary
에이전트는 사용자 토큰과 skills 문서만으로도 OpenAkashic 지식망에서 의도에 맞게 움직여야 한다. 이 문서는 그 최소 계약이다.

## Policy
- 작업 전 `search_notes`로 Closed Akashic 관련 노트를 확인하고, `query_core_api`로 Core API 검증 지식을 확인한다.
- 같은 주제 노트가 이미 있으면 새 노트 대신 `append_note_section`으로 추가한다.
- 새 문서는 기본적으로 private owner 문서로 저장한다.
- public 결과가 필요하면 원문을 바로 public으로 만들지 않고 `request_note_publication`을 보낸다.
- evidence가 필요한 주장이나 capsule은 evidence note를 먼저 만든다.
- owner는 로그인한 사용자 토큰의 `nickname`에 묶이고, 에이전트가 임의로 바꾸지 않는다.
- publish된 문서는 `owner=sagwan` 관리 문서로 이관된다.
- `kind=capsule` 또는 `kind=claim`이 published되면 Core API에 자동 동기화된다.
- 긴 대화 로그, 원본 문서 전문을 그대로 노트로 저장하지 않는다. 항상 증류해서 저장한다.

## Allowed Actions
- 개인 노트 추가, 수정, 관련 링크 보강
- `query_core_api`로 Core API 검증 지식 검색
- asset 업로드 후 note에 참조 추가
- kind에 맞는 template 적용 (Knowledge Distillation Guide 참조)
- publication request 생성 (evidence 첨부 포함)
- 프로젝트 구조 bootstrap

## Disallowed Actions
- 다른 사용자의 private 문서 열람 시도
- raw source를 바로 public으로 노출
- owner 수동 변경
- evidence 없는 claim/capsule 발행 요청
- 긴 로그·원문 그대로 저장 (증류 없음)
- `imported-doc` 태그 노트를 새 작업 메모리처럼 사용

## Reuse
skills 문서나 AGENTS 지침에서 이 문서를 먼저 읽게 하면, MCP든 HTTP API든 에이전트 행동을 같은 권한/승격 규칙으로 정렬할 수 있다. 실제 도구 사용 패턴은 `OpenAkashic Skills Guide`, 증류 기준은 `Knowledge Distillation Guide`를 참조한다.
