---
title: "Distributed Agent Memory Contract"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [agent, distributed, mcp, memory, codex, cursor, opencode]
related: ["Agent Guide", "Project Memory Intake", "Remote Agent Enrollment", "Project Index Schema"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
Remote agents on different servers should use one shared operating pattern: central memory from Closed Akashic over MCP, canonical truth from each project repo, and a tiny per-Codex `AGENTS.md` that points agents back to this server.

## Two-Layer Model
- **Closed Akashic** (`knowledge.openakashic.com/mcp/`): shared memory, operating docs, project indexes, incidents, decisions, playbooks, images. 20 MCP tools.
- **Core API** (`api.openakashic.com`): validated public knowledge. claims / capsules. SLM agents query this via `search_akashic`.
- **project repo `doc/`**: canonical product and implementation documents.

`kind=capsule` and `kind=claim` notes auto-sync to Core API on publication approval. This is the bridge from personal work memory to SLM-queryable knowledge.

Local `agent-knowledge` clones are no longer part of the default workflow.

## Standard Flow
1. Verify `CLOSED_AKASHIC_TOKEN` and MCP access to `https://knowledge.openakashic.com/mcp/` (trailing slash required).
2. Read [[Codex Central Memory Setup]] and this contract when attaching a new Codex host.
3. Open the project index README in Closed Akashic.
4. Before implementation: `search_notes` for related Closed Akashic notes, `search_akashic` for validated knowledge.
5. Read the project repo's canonical docs.
6. Do the work in the repo or server.
7. Write back one concise linked note or update the existing best container. Distill — never paste raw logs.

## Project Routing
- project memory: `personal_vault/projects/<scope>/<project>/...`
- cross-project reusable memory: `personal_vault/shared/...`
- operating docs for all agents: `doc/agents/...`

Common scopes include `personal`, `company`, `client`, `research`, and `ops`, but they are not hard-coded categories.

Each project workspace should have a `README.md`. Agents may create or revise subfolders through MCP according to the project shape.

## Write-Back Contract
- update an existing note when the container is already right
- create a new note only when the new fact deserves its own history
- keep notes short, link-heavy, and reusable
- do not paste whole chat transcripts
- do not duplicate canonical repo docs

## Shared Failure Modes
- letting each server keep a different private memory copy
- requiring local `agent-knowledge` before the central MCP memory is available
- storing raw project docs in Closed Akashic instead of links plus distillation
- skipping the project README and writing orphan notes
- forcing personal/company intro pages instead of letting agents manage project structure
- writing long session logs instead of a small incident, decision, or playbook

## Reuse
When attaching a new agent or a new server, use [[Codex Central Memory Setup]] and [[Remote Agent Enrollment]] first. When attaching a new project, follow [[Project Index Schema]] and [[Project Memory Intake]].
