---
title: Codex AGENTS Template
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [codex, agents, template, mcp]
related: [Codex Central Memory Setup, Agent Setup Snippets, Distributed Agent Memory Contract]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-13T00:00:00Z
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

1. Before substantial work, search Closed Akashic for related notes.
2. When a project is involved, open `personal_vault/projects/<scope>/<project>/README.md`.
3. Prefer existing notes and update them when they are the right container.
4. After meaningful work, write back one concise, linked note or append one focused section.
5. Keep notes inside `doc/`, organized `personal_vault/` subfolders, or `assets/images/` for uploads.
6. Do not use, clone, or update local `agent-knowledge` as a memory bootstrap.

## Preferred MCP tools

- `search_notes`
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
