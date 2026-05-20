---
title: "Codex MCP Deployment"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [codex, mcp, deployment, setup]
related: ["Agent Setup Snippets", "Codex AGENTS Template", "Codex Central Memory Setup", "Distributed Agent Memory Contract", "doc/agents/Agent Setup Snippets.md", "doc/agents/Codex AGENTS Template.md", "doc/agents/Codex Central Memory Setup.md"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-05-10T17:11:55Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
last_maintained_at: 2026-05-10T17:11:54Z
last_maintenance_verdict: keep
last_maintenance_note: "[vault: doc/agents/Codex MCP Deployment.md; doc/agents/Codex Central Memory Setup.md; doc/agents/Codex AGENTS Template.md; doc/agents/Agent Setup Snippets.md][public: Codex AGENTS Template; Agent Setup Snippets] 대상 노트는 Codex 호스트가 Closed Akashic MCP를 중앙 장기 메모리로 쓰고 local agent-knowledge에 의존하지 말라는 목적, ~/.codex/config.toml의 MCP endpoint 설정, 공유 로컬 호스트에서 Authorization header 우선·CLOSED_AKASHIC_TOKEN env-var fallback, ~/.codex/AGENTS.md 템플릿 적용, 세션 재시작 및 smoke-test 절차를 관련 vault 노트들과 일관되게 설명한다. validated "
related_candidates: [{"path": "personal_vault/reference/Closed Akashic Shared Agent Token Setup.md", "count": 1, "last_seen_at": "2026-05-08T23:16:16Z", "last_stage": "maintenance", "last_verdict": "revise"}]
revision_count: 2
---

## Summary
This is the deployment Markdown for a Codex host. If an agent reads this file, it should configure itself to use Closed Akashic MCP as its central memory and stop relying on local `agent-knowledge`.

## Agent Instruction
If you are Codex running on a server:

1. Configure the `closed-akashic` MCP server in `~/.codex/config.toml`.
2. Prefer a machine-local static `Authorization` header for shared local agent hosts.
3. Use `bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"` only when the token must not be stored in `~/.codex/config.toml`.
4. Replace or create `~/.codex/AGENTS.md` with the central memory rules below, aligned with [[Codex AGENTS Template]].
5. Start a new Codex session after setup.
6. Smoke-test with `search_notes`, `read_note`, and one safe write-back.

## Required MCP Config
Preferred shared local setup:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
http_headers = { Authorization = "Bearer <redacted>" }
```

Do not store or document the real token value in repo docs or project notes.

Fallback when the token must remain outside config:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

`CLOSED_AKASHIC_TOKEN` is a machine-level Closed Akashic setting, not a per-project setting. After changing `~/.codex/config.toml`, restart the Codex session so MCP config reloads.

## Required AGENTS.md
Write this to `~/.codex/AGENTS.md`:

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

- `search_notes` — Closed Akashic working-memory search
- `search_akashic` — validated public knowledge search for SLM-ready capsules/claims
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

## Smoke Test
After opening a new Codex session:

1. Use `search_notes` for `Codex MCP Deployment`.
2. Use `read_note` for `doc/agents/Codex MCP Deployment.md`.
3. If working on a new project, call `bootstrap_project`.
4. Append one short section to a safe project operations note after meaningful work.

## Debugging
If MCP setup fails from another server, use [[MCP Debugging and Logs]].

Fast checks:

```bash
curl -fsS https://knowledge.openakashic.com/health
curl -fsS https://knowledge.openakashic.com/api/debug/status \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

Use a request id when testing from a remote host:

```bash
REQ_ID="remote-mcp-test-$(date +%s)"
curl -i https://knowledge.openakashic.com/mcp/ \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN" \
  -H "X-Request-ID: $REQ_ID"
```

## Project Folder Policy
Agents do not need a fixed personal/company introduction page. They should create and update project folders through MCP based on the project shape.

Use:

- `bootstrap_project` to create the project README and initial folders
- `create_folder` to add a new folder
- `rename_folder` to reorganize
- `move_note` to clean up existing notes
- `path_suggestion` to route new notes

## Reuse
This Markdown is intentionally self-contained so it can be copied to another server, pasted into a setup issue, or opened by a fresh Codex agent.

Related setup notes: [[Codex Central Memory Setup]], [[Codex AGENTS Template]], [[Agent Setup Snippets]], [[Distributed Agent Memory Contract]], [[Closed Akashic Shared Agent Token Setup]].
