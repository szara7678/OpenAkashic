---
title: "Codex AGENTS Template"
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [codex, agents, template, mcp]
related: ["Codex Central Memory Setup", "Agent Setup Snippets", "Distributed Agent Memory Contract"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-22T11:14:35Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
core_api_id: 50bb02da-1bf9-438d-8fcd-20583865047c
last_validated_at: 2026-04-22T11:14:35Z
sagwan_validation_count: 10
sagwan_last_validation_verdict: ok
sagwan_last_validation_note: "LLM unavailable: [CLI 오류 1] SessionEnd hook [node \\"/home/insu/.pixel-agents/hooks/claude-hook.js\\"] failed: node:internal/modules/cjs/load"
---

## Summary
Copy this text into `~/.codex/AGENTS.md` on each Codex host so every Codex uses the same central Closed Akashic memory.

## Template
```markdown
# Codex Memory Rules

Use Closed Akashic MCP as the only shared long-term working memory.

## Where to read and write

- Browser surface: `https://knowledge.openakashic.com`
- MCP endpoint: `https://knowledge.openakashic.com/mcp/`
- Bearer token env var: `CLOSED_AKASHIC_TOKEN`

## Operating behavior

1. Before substantial work, `search_notes` for related Closed Akashic notes, then `search_akashic` for validated knowledge.
2. When a project is involved, open `personal_vault/projects/<scope>/<project>/README.md`.
3. Prefer existing notes and update them when they are the right container.
4. After meaningful work, write back one concise, linked note or append one focused section. Distill — never paste raw logs.
5. Keep notes inside `doc/`, organized `personal_vault/` subfolders, or `assets/images/` for uploads.
6. Do not use, clone, or update local `agent-knowledge` as a memory bootstrap.

## Preferred MCP tools

- `search_notes` — Closed Akashic 작업 메모리 검색
- `search_akashic` — Core API 검증 지식 검색 (SLM-ready capsules/claims)
- `read_note`
- `bootstrap_project`
- `path_suggestion`
- `upsert_note`
- `append_note_section`
- `upload_image`
- `debug_recent_requests`
- `debug_log_tail`

## Project folders

- Project index: `personal_vault/projects/<scope>/<project>/README.md`
- Common scopes: `personal`, `company`, `client`, `research`, `ops`
- Agents may create and update project folders through MCP.
- Common starting folders: `architecture/`, `playbooks/`, `incidents/`, `decisions/`, `experiments/`, `reference/`
```

## Reuse
This is deliberately short. Long instructions live in Closed Akashic itself so future changes update one central source instead of many local agent folders.

## Sagwan Revalidation 2026-04-15T06:47:51Z
- verdict: `refresh`
- note: Bearer token을 env var `CLOSED_AKASHIC_TOKEN`으로 표기했으나 실제는 settings.json에서 읽음. 미완성 문장("Common starting folders: `arc`") 있음.

## Sagwan Revalidation 2026-04-15T06:58:25Z
- verdict: `ok`
- note: 오늘 아침 검증, 핵심 MCP 설정·workflow·경로 구조 현재와 일치하며 즉시 활용 가능.

## Sagwan Revalidation 2026-04-15T07:13:52Z
- verdict: `refresh`
- note: MCP 엔드포인트·도구·폴더구조는 현행 유효하나 본문이 1600자에서 절단되어 원전 복구·완성도 검증 필요.

## Sagwan Revalidation 2026-04-16T08:51:53Z
- verdict: `refresh`
- note: 마지막 부분 "Common starting folders: `arc" 이 불완전하고, bearer token 환경변수 이름 확인 필요.

## Sagwan Revalidation 2026-04-17T08:52:47Z
- verdict: `refresh`
- note: 노트가 'Common starting folders: `arc'에서 미완성 끝남. 환경변수명, 도구 목록 최신화 필요.

## Sagwan Revalidation 2026-04-18T09:18:42Z
- verdict: `ok`
- note: MCP 엔드포인트·도구명·프로젝트폴더 모두 현 운영과 일치, 1일 경과로 변화 없음.

## Sagwan Revalidation 2026-04-19T09:54:47Z
- verdict: `ok`
- note: 엔드포인트·도구 목록·폴더 구조가 현행 운영 기준과 일치하며 모순·오탈자 없음.

## Sagwan Revalidation 2026-04-20T10:27:51Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load

## Sagwan Revalidation 2026-04-21T10:47:05Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load

## Sagwan Revalidation 2026-04-22T11:14:35Z
- verdict: `ok`
- note: LLM unavailable: [CLI 오류 1] SessionEnd hook [node "/home/insu/.pixel-agents/hooks/claude-hook.js"] failed: node:internal/modules/cjs/load
