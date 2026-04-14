---
title: AGENTS
kind: reference
project: closed-akashic
status: active
confidence: high
tags: []
related: []
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
updated_at: 2026-04-14T08:20:24Z
created_at: 2026-04-14T08:20:24Z
---

# Closed Akashic Agent Rules

Closed Akashic is a maintained private memory store, not a dump folder.

## Default behavior

1. Read Closed Akashic before major work.
2. Reuse existing notes before writing a parallel explanation.
3. Write back one compact note or one precise update after meaningful work.
4. Keep notes small, linked, and reusable.
5. Prefer `doc/` for durable operating docs, `personal_vault/` subfolders for working memory, and `assets/images/` for uploaded images.

## Shared Multi-Server Contract

Every remote Codex, Cursor, OpenCode, or similar agent should follow the same flow:

1. Use the main Closed Akashic server over MCP or authenticated API as the central memory layer.
2. Do not require, clone, or update local `agent-knowledge` folders for normal work.
3. Open the matching project index at `personal_vault/projects/<scope>/<project>/README.md`.
4. Search related notes before implementation, debugging, or deployment work.
5. After meaningful work, update the best existing note or add one concise linked note.

## Codex bootstrap

- Each Codex host should keep a short `~/.codex/AGENTS.md` that points to this MCP server.
- Each Codex host should register `closed-akashic` in `~/.codex/config.toml`.
- Project repositories may still have their own `AGENTS.md` for project-specific rules, but memory behavior should stay centralized here.

## Remote access

- Site: `https://knowledge.openakashic.com`
- Authenticated API: `https://knowledge.openakashic.com/api/*`
- Authenticated MCP: `https://knowledge.openakashic.com/mcp`
- Bearer token env var for local agents: `CLOSED_AKASHIC_TOKEN`

Use the main server as the canonical shared memory surface. Do not let each server keep its own divergent Closed Akashic clone for normal retrieval and write-back.

## Writing rules

- Stay inside `doc/`, `personal_vault/`, or `assets/`.
- Preserve frontmatter shape.
- Use `## Summary` near the top.
- Update existing notes when the concept is the same recurring container.
- Create a new note when the incident, decision, or pattern deserves its own history.

## Folder hints

- `doc/general/`, `doc/agents/`, `doc/reference/`
- `personal_vault/shared/concepts/`, `shared/playbooks/`, `shared/schemas/`, `shared/reference/`
- `personal_vault/personal/concepts/`, `personal/playbooks/`, `personal/reference/`
- `personal_vault/projects/<scope>/<project>/README.md`
- Agents may create and revise project subfolders through MCP.
- `assets/images/`

## Project memory contract

- Give each active project a `personal_vault/projects/<scope>/<project>/README.md` index note.
- Put canonical source docs in the project repo itself, usually `doc/README.md`, `doc/plan.md`, `doc/UPDATE.md`, `doc/TroubleShooting.md` when available.
- Keep only distilled patterns, incidents, decisions, and reusable references in Closed Akashic.
- Do not copy whole project docs into Closed Akashic when an index note and links are enough.
- Let the project folder structure follow the project. Use `bootstrap_project`, `create_folder`, `rename_folder`, and `move_note` instead of forcing one taxonomy.

## Good write-back targets

- incident
- pattern
- decision
- playbook
- experiment

## Preferred MCP Flow

- `search_notes` for retrieval
- `read_note` for the exact container
- `bootstrap_project` when a project index does not exist yet
- `path_suggestion` for new note routing
- `upsert_note` or `append_note_section` for write-back
- `upload_image` for screenshots or diagrams

See [agent.md](/home/ec2-user/Akashic/ClosedAkashic/doc/agents/agent.md), [Distributed Agent Memory Contract.md](/home/ec2-user/Akashic/ClosedAkashic/doc/agents/Distributed%20Agent%20Memory%20Contract.md), [Project Memory Intake.md](/home/ec2-user/Akashic/ClosedAkashic/personal_vault/shared/playbooks/Project%20Memory%20Intake.md), and [Remote Agent Enrollment.md](/home/ec2-user/Akashic/ClosedAkashic/personal_vault/shared/playbooks/Remote%20Agent%20Enrollment.md) for the longer workflow.
