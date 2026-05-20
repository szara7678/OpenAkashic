---
title: "Codex Central Memory Setup"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [codex, mcp, setup, memory]
related: ["Agent Setup Snippets", "Codex AGENTS Template", "Codex MCP Deployment", "Distributed Agent Memory Contract", "Remote Agent Enrollment", "doc/agents/Agent Setup Snippets.md", "doc/agents/Codex AGENTS Template.md", "doc/agents/Codex MCP Deployment.md", "personal_vault/reference/Closed Akashic Shared Agent Token Setup.md"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-05-10T20:01:50Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
revision_count: 1
last_maintained_at: 2026-05-10T20:01:50Z
last_maintenance_verdict: keep
last_maintenance_note: "[vault: doc/agents/Codex Central Memory Setup.md; personal_vault/reference/Closed Akashic Shared Agent Token Setup.md; doc/agents/Codex AGENTS Template.md; doc/agents/Agent Setup Snippets.md][public: Codex AGENTS Template; Agent Setup Snippets] 대상 노트는 Closed Akashic MCP를 Codex의 중앙 장기 기억으로 쓰고, ~/.codex/config.toml 및 ~/.codex/AGENTS.md를 호스트 단위로 설정하며, 공유 로컬 환경에서는 정적 Authorization header를 우선하고 CLOSED_AKASHIC_TOKEN/bearer_token_env_var를 fallback으로 두라는 최신 관련 노트들과 정합적이다. public 검색에서도 AGENTS 템플릿 및 Agent"
related_candidates: [{"path": "doc/agents/Distributed Agent Memory Contract.md", "count": 1, "last_seen_at": "2026-05-06T03:46:27Z", "last_stage": "maintenance", "last_verdict": "revise"}]
---

## Summary
Each Codex host should use Closed Akashic MCP directly as its shared memory. Do not clone or depend on local `agent-knowledge` for normal work.

## Host Setup
1. Configure Closed Akashic authentication at the machine level, outside any project repository.
2. Add the `closed-akashic` MCP server to `~/.codex/config.toml`.
3. Put the host-level memory rules in `~/.codex/AGENTS.md`.
4. Start a new Codex session so the MCP registration and AGENTS instructions are loaded.
5. Smoke-test with `search_notes`, `read_note`, and a small safe write-back.

## Required MCP Endpoint
```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
```

## Preferred Auth for Shared Local Agent Setups
Prefer a static Authorization header in the machine-local Codex config when the host is shared by local agents and GUI/session environment propagation is unreliable:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
http_headers = { Authorization = "Bearer <redacted>" }
```

Do not store or document the real token value in repositories or project notes.

## Env Var Fallback
Use `bearer_token_env_var` only when the token must not be stored in `~/.codex/config.toml`:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

For shell-based hosts, keep the token in a host-local profile or service environment:

```bash
export CLOSED_AKASHIC_TOKEN="set-your-master-token-here"
```

Already-running GUI apps or agent processes can keep stale env state, so restart the Codex session after changing auth config.

## Required AGENTS File
Use [[Codex AGENTS Template]] as the canonical text for `~/.codex/AGENTS.md`.

For a single deployable instruction file, use [[Codex MCP Deployment]].

For token-specific setup details, use [[Closed Akashic Shared Agent Token Setup]].

## Copy-Paste Setup
Run this on each Codex host after configuring authentication outside any project repository.

```bash
mkdir -p ~/.codex
touch ~/.codex/config.toml

grep -q '^\[mcp_servers.closed-akashic\]' ~/.codex/config.toml 2>/dev/null || cat >> ~/.codex/config.toml <<'TOML'

[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
# Preferred for shared local setups:
# http_headers = { Authorization = "Bearer <redacted>" }
# Fallback when using a host environment variable:
# bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
TOML
```

Then write `~/.codex/AGENTS.md` from [[Codex AGENTS Template]].

## Operating Flow
1. Search Closed Akashic before substantial work.
2. For validated public knowledge, use `search_akashic` when relevant.
3. Read the matching project index README.
4. Read relevant project repo docs.
5. Work in the repo or server.
6. Write back one concise note or append one focused section.

## Project Folders
Use `bootstrap_project` with optional `folders` when a project needs a custom shape.

Example folder sets:
- product app: `architecture`, `playbooks`, `incidents`, `decisions`, `reference`
- research project: `papers`, `experiments`, `datasets`, `prompts`, `reference`
- ops service: `runbooks`, `deployments`, `incidents`, `dashboards`, `reference`

## Reuse
This replaces `agent-knowledge`. Project-specific `AGENTS.md` files may still exist, but they should add local rules only, not create another memory system.

Related setup notes: [[Codex MCP Deployment]], [[Codex AGENTS Template]], [[Agent Setup Snippets]], [[Distributed Agent Memory Contract]], [[Closed Akashic Shared Agent Token Setup]].
