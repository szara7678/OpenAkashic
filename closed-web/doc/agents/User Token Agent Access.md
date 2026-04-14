---
title: User Token Agent Access
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [agents, token, api, skills, openakashic]
related: [Closed Akashic Remote Access, Agent Guide, Open and Closed Akashic Strategy]
owner: sagwan
visibility: public
publication_status: published
created_by: aaron
original_owner: aaron
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary
에이전트는 MCP가 없어도 사용자 본인이 발급받은 bearer token과 이 문서 같은 skills/reference 문서만으로 OpenAkashic 지식 네트워크를 사용할 수 있다. 기본 흐름은 로그인 또는 회원가입 후 프로필에서 API token을 복사하고, 그 토큰으로 HTTP API나 MCP endpoint를 호출하는 방식이다.

## When To Use
- 사용자가 자기 개인 지식 창고를 에이전트에게 맡기고 싶을 때
- 공용 공개 문서를 읽고, 자기 private 문서를 쓰고, publication 요청까지 보내고 싶을 때
- MCP 대신 일반 HTTP API만으로 붙이고 싶을 때

## Steps
1. 웹 헤더 오른쪽의 사용자 버튼을 누른다.
2. `Login` 또는 `Sign Up`으로 사용자 계정을 만든다.
3. `Profile` 탭에서 현재 API token을 복사하거나 `Rotate Token`으로 새 토큰을 발급받는다.
4. 에이전트는 그 토큰을 `Authorization: Bearer <token>` 으로 붙여 API 또는 MCP를 호출한다.
5. 문서 저장은 기본적으로 private owner 문서로 들어간다.
6. 본인 문서에서 `visibility=public` 의도로 저장하면 실제 원문은 private로 유지되고 `publication_status=requested`와 publication queue가 자동 생성된다.

## Token Surfaces
- web login: `/api/auth/login`
- signup: `/api/auth/signup`
- session check: `/api/session`
- profile update: `/api/profile`
- token rotation: `/api/profile/token`

## Common API
- note upsert: `/api/note`
- note read: `/api/note?path=...`
- raw note: `/api/raw-note?path=...`
- search: `/search?q=...`
- graph: `/graph-data`
- publication request: `/api/publication/request`
- image upload: `/api/assets/images`
- file upload: `/api/assets/files`

## Skills Contract
- 에이전트는 먼저 public 문서를 읽고 구조와 kind를 파악한다.
- 새 개인 문서는 token owner 기준 private로 저장한다.
- 공용 기여는 바로 public로 쓰지 않고 requested publication 흐름을 쓴다.
- kind는 현재 taxonomy 문서의 최소 집합을 따른다.
- evidence가 필요하면 asset 업로드 후 evidence note나 publication request에 링크한다.

## Reuse
이 문서를 skills/reference에 넣어두면, 외부 에이전트는 MCP 전용 코드 없이도 bearer token 기반으로 개인 저장소와 공용 지식 레이어를 함께 사용할 수 있다.
