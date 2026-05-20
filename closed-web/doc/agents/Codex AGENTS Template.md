---
title: "Codex AGENTS Template"
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [codex, agents, template, mcp]
related: ["Agent Setup Snippets", "Codex Central Memory Setup", "Distributed Agent Memory Contract", "doc/agents/Codex MCP Deployment.md", "personal_vault/projects/ops/librarian/capsules/Closed Akashic MCP Bearer Token Setup Snippets and Auth Failure Modes for Codex and Claude.md", "personal_vault/reference/Closed Akashic Shared Agent Token Setup.md"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-05-10T22:52:52Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
core_api_id: 50bb02da-1bf9-438d-8fcd-20583865047c
last_validated_at: 2026-04-22T11:14:35Z
sagwan_validation_count: 10
sagwan_last_validation_verdict: ok
sagwan_last_validation_note: "LLM unavailable: [CLI 오류 1] SessionEnd hook [node \\\\\\\\\\\\"/home/insu/.pixel-agents/hooks/claude-hook.js\\\\\\\\\\\\"] failed: node:internal/modules/cjs/load"
last_maintained_at: 2026-05-10T22:52:51Z
last_maintenance_verdict: keep
last_maintenance_note: "[vault: doc/agents/Codex AGENTS Template.md; doc/agents/Codex MCP Deployment.md; personal_vault/reference/Closed Akashic Shared Agent Token Setup.md; personal_vault/projects/ops/librarian/capsules/Closed Akashic MCP Bearer Token Setup Snippets and Auth Failure Modes for Codex and Claude.md][public: Codex AGENTS Template; OpenAkashic MCP Guide Capsule] 대상 노트는 현재 배포 노트와 토큰 설정 플레이북의 최신 기준(공유 로컬 Codex 호스트는 static Authorization header 우선, CLOSED_AKASHIC_TOKEN은 fallback)과 정합하며, Preferred MCP tools도 Co"
related_candidates: [{"path": "doc/agents/Codex Central Memory Setup.md", "count": 1, "last_seen_at": "2026-05-06T04:04:46Z", "last_stage": "maintenance", "last_verdict": "keep"}, {"path": "doc/agents/Agent Setup Snippets.md", "count": 1, "last_seen_at": "2026-05-06T04:04:46Z", "last_stage": "maintenance", "last_verdict": "keep"}, {"path": "doc/agents/Distributed Agent Memory Contract.md", "count": 1, "last_seen_at": "2026-05-06T04:04:46Z", "last_stage": "maintenance", "last_verdict": "keep"}]
revision_count: 1
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
- Auth: use the host-level MCP config; prefer a static `Authorization` header on shared local hosts, or `CLOSED_AKASHIC_TOKEN` as the env-var fallback when the token must not be stored in config.

## Operating behavior

1. Before substantial work, search Closed Akashic for related notes, then use validated public knowledge when available.
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
- `create_folder`
- `rename_folder`
- `move_note`
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

## Sagwan Revalidation 2026-05-08T23:18:00Z
- verdict: `revise`
- note: 최신 관련 노트인 `doc/agents/Codex MCP Deployment.md`와 `personal_vault/reference/Closed Akashic Shared Agent Token Setup.md` 기준으로, 공유 로컬 Codex 호스트에서는 정적 `Authorization` header를 우선하고 `CLOSED_AKASHIC_TOKEN`은 fallback으로 표기해야 한다. Preferred MCP tools도 배포 노트와 맞추기 위해 folder/move 도구를 보강한다.
