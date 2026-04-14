---
title: Codex MCP Deployment
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [codex, mcp, deployment, setup]
related: [Codex Central Memory Setup, Codex AGENTS Template, Agent Setup Snippets, Distributed Agent Memory Contract]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-13T00:00:00Z
---

## Summary
This is the deployment Markdown for a Codex host. If an agent reads this file, it should configure itself to use Closed Akashic MCP as its central memory and stop relying on local `agent-knowledge`.

## Agent Instruction
If you are Codex running on a server:

1. Ensure `CLOSED_AKASHIC_TOKEN` is available in the host environment.
2. Add the `closed-akashic` MCP server to `~/.codex/config.toml`.
3. Replace or create `~/.codex/AGENTS.md` with the central memory rules below.
4. Start a new Codex session after setup.
5. Smoke-test with `search_notes`, `read_note`, and one safe write-back.

## Required MCP Config
Add this block to `~/.codex/config.toml` if it is missing:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

## Required AGENTS.md
Write this to `~/.codex/AGENTS.md`:

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
- `create_folder`
- `rename_folder`
- `move_note`
- `upsert_note`
- `append_note_section`
- `upload_image`
- `debug_recent_requests`
- `debug_log_tail`

## Project workspaces

- Project index: `personal_vault/projects/<scope>/<project>/README.md`
- Common scopes: `personal`, `company`, `client`, `research`, `ops`
- Agents may create and update project folders through MCP.
- Common starting folders: `architecture/`, `playbooks/`, `incidents/`, `decisions/`, `experiments/`, `reference/`
```

## Idempotent Setup Script
Run this on a Codex host after setting `CLOSED_AKASHIC_TOKEN` outside any project repository.

```bash
mkdir -p "$HOME/.codex"

touch "$HOME/.codex/config.toml"
grep -q '^\[mcp_servers.closed-akashic\]' "$HOME/.codex/config.toml" || cat >> "$HOME/.codex/config.toml" <<'TOML'

[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
TOML

cat > "$HOME/.codex/AGENTS.md" <<'MARKDOWN'
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
- `create_folder`
- `rename_folder`
- `move_note`
- `upsert_note`
- `append_note_section`
- `upload_image`
- `debug_recent_requests`
- `debug_log_tail`

## Project workspaces

- Project index: `personal_vault/projects/<scope>/<project>/README.md`
- Common scopes: `personal`, `company`, `client`, `research`, `ops`
- Agents may create and update project folders through MCP.
- Common starting folders: `architecture/`, `playbooks/`, `incidents/`, `decisions/`, `experiments/`, `reference/`
MARKDOWN
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
