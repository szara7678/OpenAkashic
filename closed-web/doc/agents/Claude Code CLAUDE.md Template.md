---
title: "Claude Code CLAUDE.md Template"
kind: playbook
project: openakashic
status: active
confidence: high
tags: [agent, claude-code, template, mcp, bootstrap]
related: ["Distributed Agent Memory Contract", "Remote Agent Enrollment", "Codex AGENTS Template"]
visibility: private
created_by: aaron
owner: aaron
publication_status: none
updated_at: 2026-04-16T01:41:22Z
created_at: 2026-04-16T01:41:22Z
---

## Summary
프로젝트 루트에 `CLAUDE.md`를 두면 Claude Code가 매 세션 시작 시 자동 로드한다. Codex의 `~/.codex/AGENTS.md` + 프로젝트 `AGENTS.md`, Cursor의 `.cursor/rules/*.mdc`와 동등한 역할.

## Why Needed
- Claude Code는 CLAUDE.md가 없으면 MCP 도구가 보여도 **언제/어떻게 써야 하는지 모른다**.
- Codex/Cursor는 AGENTS.md/.mdc를 자동 로드해 Akashic 검색→작업→write-back 패턴을 따르지만, Claude Code는 해당 파일이 없으면 사용자가 일일이 지시해야 한다.
- 2026-04-16 arc-fleet 세션에서 이 갭이 발견됨: Claude Code가 배포 검증·메모리 write-back·사전 검색을 건너뛰고 빌드만 확인 후 완료 선언.

## Template Structure
CLAUDE.md에 포함해야 하는 최소 섹션:
1. **Closed Akashic Memory** — Preflight, 작업 전 검색, 작업 후 write-back, Fail Fast
2. **수정 가능 영역** — 서브모듈 소유권 경계
3. **구현 워크플로** — 모호한 지시 구체화, 빌드→도커 배포→실사용 검증→Playwright 테스트 한 흐름
4. **로컬 Working Log** — `doc/UPDATE.md` 사용 규칙
5. **Git / 버전 관리** — 커밋 정책
6. **참조 Akashic 노트** — 세션 시작 시 검색할 핵심 노트 목록

## How to Create for a New Project
1. 프로젝트 루트에 `CLAUDE.md` 생성.
2. 위 Template Structure를 프로젝트에 맞게 채운다 — 수정 가능 영역, 도커 명령어, QA 경로 등은 프로젝트별로 다르다.
3. Akashic의 프로젝트 README에 "Claude Code 에이전트 지침: `CLAUDE.md`"를 추가한다.
4. 기존 Codex AGENTS.md / Cursor .mdc와 **핵심 규칙(메모리 규칙, 구현 워크플로)**이 일치하도록 유지한다.

## Reference Implementation
arc-fleet 프로젝트의 `CLAUDE.md`가 첫 번째 적용 사례다. 이 노트의 구조를 따라 만들면 된다.

## Reuse
새 프로젝트에 Claude Code를 붙일 때 이 템플릿을 참조한다. Remote Agent Enrollment의 Claude Code 단계에서 이 노트를 안내한다.
