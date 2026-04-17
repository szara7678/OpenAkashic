---
title: "Codex Central Memory Setup"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [codex, mcp, setup, memory]
related: ["Codex MCP Deployment", "Codex AGENTS Template", "Agent Setup Snippets", "Distributed Agent Memory Contract", "Remote Agent Enrollment"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
Each Codex host should use Closed Akashic MCP directly as its shared memory. Do not clone or depend on local `agent-knowledge` for normal work.

## Host Setup
1. Set `CLOSED_AKASHIC_TOKEN` on the host.
2. Add the `closed-akashic` MCP server to `~/.codex/config.toml`.
3. Put the host-level memory rules in `~/.codex/AGENTS.md`.
4. Start a new Codex session so the MCP registration and AGENTS instructions are loaded.
5. Smoke-test with `search_notes`, `read_note`, and a small safe write-back.

## Required Config
```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

## Required AGENTS File
Use [[Codex AGENTS Template]] as the canonical text for `~/.codex/AGENTS.md`.

For a single deployable instruction file, use [[Codex MCP Deployment]].

## Copy-Paste Setup
Run this on each Codex host after setting the token outside any project repository.

```bash
mkdir -p ~/.codex

grep -q '^\[mcp_servers.closed-akashic\]' ~/.codex/config.toml 2>/dev/null || cat >> ~/.codex/config.toml <<'TOML'

[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
TOML
```

Then write `~/.codex/AGENTS.md` from [[Codex AGENTS Template]].

For shell-based hosts, keep the token in a host-local profile or service environment:

```bash
export CLOSED_AKASHIC_TOKEN="set-your-master-token-here"
```

## Operating Flow
1. Search Closed Akashic before substantial work.
2. Read the matching project index README.
3. Read relevant project repo docs.
4. Work in the repo or server.
5. Write back one concise note or append one focused section.

## Project Folders
Use `bootstrap_project` with optional `folders` when a project needs a custom shape.

Example folder sets:
- product app: `architecture`, `playbooks`, `incidents`, `decisions`, `reference`
- research project: `papers`, `experiments`, `datasets`, `prompts`, `reference`
- ops service: `runbooks`, `deployments`, `incidents`, `dashboards`, `reference`

## Reuse
This replaces `agent-knowledge`. Project-specific `AGENTS.md` files may still exist, but they should add local rules only, not create another memory system.
