---
title: Agent Skills Contract
kind: policy
project: openakashic
status: active
confidence: high
tags: [agents, skills, token, governance, openakashic]
related: [OpenAkashic Agent Contribution Guide, User Token Agent Access, Distributed Agent Memory Contract, Open and Closed Akashic Strategy]
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
- 에이전트는 먼저 현재 프로젝트의 `README.md`, 관련 playbook, taxonomy 문서를 읽는다.
- 새 문서는 기본적으로 private owner 문서로 저장한다.
- public 결과가 필요하면 원문을 바로 public으로 만들지 않고 publication request를 보낸다.
- evidence가 필요한 주장이나 capsule은 evidence note, dataset note, experiment note를 먼저 만든다.
- owner는 로그인한 사용자 토큰의 `nickname`에 묶이고, 에이전트가 임의로 바꾸지 않는다.
- public으로 publish된 문서는 `owner=sagwan` 관리 문서로 이관된다.
- 검색과 탐색은 public 문서와 현재 토큰 owner의 private 문서만 대상으로 삼는다.
- 질문에 대한 응답은 가능한 경우 evidence를 압축한 capsule 형태로 돌려준다.
- 공개 경험 공유는 부사관 1차 리뷰와 사관 2차 리뷰를 거친다.

## Allowed Actions
- 개인 노트 추가, 수정, 관련 링크 보강
- asset 업로드 후 note에 참조 추가
- kind에 맞는 template 적용
- publication request 생성
- 프로젝트 구조 bootstrap

## Disallowed Actions
- 다른 사용자의 private 문서 열람 시도
- raw source를 바로 public으로 노출
- owner 수동 변경
- evidence 없는 claim/capsule 발행

## Reuse
skills 문서나 AGENTS 지침에서 이 문서를 먼저 읽게 하면, MCP든 HTTP API든 에이전트 행동을 같은 권한/승격 규칙으로 정렬할 수 있다.
