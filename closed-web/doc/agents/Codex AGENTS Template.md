---
title: "Codex AGENTS Template"
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [codex, agents, template, mcp]
related: ["Codex Central Memory Setup", "Agent Setup Snippets", "Distributed Agent Memory Contract"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-17T08:52:47Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
core_api_id: b20db7b8-1d3e-40a5-8077-3edddde811e0
last_validated_at: 2026-04-17T08:52:47Z
sagwan_validation_count: 5
sagwan_last_validation_verdict: refresh
sagwan_last_validation_note: "노트가 'Common starting folders: `arc'에서 미완성 끝남. 환경변수명, 도구 목록 최신화 필요."
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

1. Before substantial work, `search_notes` for related Closed Akashic notes, then `query_core_api` for validated knowledge.
2. When a project is involved, open `personal_vault/projects/<scope>/<project>/README.md`.
3. Prefer existing notes and update them when they are the right container.
4. After meaningful work, write back one concise, linked note or append one focused section. Distill — never paste raw logs.
5. Keep notes inside `doc/`, organized `personal_vault/` subfolders, or `assets/images/` for uploads.
6. Do not use, clone, or update local `agent-knowledge` as a memory bootstrap.

## Preferred MCP tools

- `search_notes` — Closed Akashic 작업 메모리 검색
- `query_core_api` — Core API 검증 지식 검색 (SLM-ready capsules/claims)
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
