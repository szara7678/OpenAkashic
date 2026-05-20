---
title: "Agent Setup Snippets"
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [agent, codex, mcp, setup]
related: ["Codex MCP Deployment", "Distributed Agent Memory Contract", "MCP Debugging and Logs", "Remote Agent Enrollment", "doc/agents/Codex AGENTS Template.md", "doc/agents/Codex Central Memory Setup.md", "doc/agents/Codex MCP Deployment.md", "personal_vault/reference/Closed Akashic Shared Agent Token Setup.md"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-05-10T20:02:13Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
core_api_id: 9e1f9d7d-821e-420c-bad3-55d51b20bad7
last_validated_at: 2026-04-22T10:39:49Z
sagwan_validation_count: 10
sagwan_last_validation_verdict: ok
sagwan_last_validation_note: "LLM unavailable: [CLI 오류 1] SessionEnd hook [node \\\\\\\\"/home/insu/.pixel-agents/hooks/claude-hook.js\\\\\\\\"] failed: node:internal/modules/cjs/load"
needs_refresh: True
refresh_requested_at: 2026-04-19T09:20:05Z
refresh_reason: "`CLOSED_AKASHIC_TOKEN` 환경 변수 방식이 현재 표준(`~/.claude/settings.json` Authorization 필드 참조)과 여전히 불일치하며, 이전 검증에서도 동일 이유로 refresh 판정됨."
revision_count: 2
last_maintained_at: 2026-05-10T20:02:13Z
last_maintenance_verdict: keep
last_maintenance_note: "[vault: personal_vault/reference/Closed Akashic Shared Agent Token Setup.md; doc/agents/Codex Central Memory Setup.md; doc/agents/Codex MCP Deployment.md; personal_vault/projects/ops/librarian/capsules/Closed Akashic MCP Bearer Token Setup Snippets and Auth Failure Modes for Codex and Claude.md][public: Agent Setup Snippets; OpenAkashic MCP Guide Capsule; claim: Authorization: Bearer <CLOSED_AKASHIC_TOKEN> 헤더 필수] vault의 토큰 전용/중앙 메모리/배포 노트가 모두 동일하게 shared local Codex host에서는 machine-local static "
related_candidates: [{"path": "personal_vault/projects/ops/librarian/capsules/Closed Akashic MCP Bearer Token Setup Snippets and Auth Failure Modes for Codex and Claude.md", "count": 1, "last_seen_at": "2026-05-10T20:02:13Z", "last_stage": "maintenance", "last_verdict": "keep"}]
---

## Summary
All agents should point to the same Closed Akashic MCP endpoint. For shared local Codex/agent hosts, prefer a machine-local static `Authorization` header in `~/.codex/config.toml`; use `CLOSED_AKASHIC_TOKEN` as the environment-variable fallback only when the token must not be stored in the config file.

## Shared Values
- MCP endpoint: `https://knowledge.openakashic.com/mcp/`
- API base: `https://knowledge.openakashic.com/api/`
- bearer token env var fallback: `CLOSED_AKASHIC_TOKEN`

## Codex Recommended Example
Add this to `~/.codex/config.toml` on each Codex host when a shared local config is acceptable:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
http_headers = { Authorization = "Bearer <redacted>" }
```

Do not store or document the real token value in repositories or project notes.

## Codex Env Var Fallback
Use this only when the token must not be stored in `~/.codex/config.toml`:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

For shell-based hosts:

```bash
export CLOSED_AKASHIC_TOKEN="set-your-master-token-here"
```

Put the export in a host-local shell profile or service environment, not in a project repository. Restart the Codex or GUI agent session after changing auth configuration, because already-running processes can keep stale environment state.

## Generic MCP Client Example
Use a client entry that points to the same MCP `url` and sends `Authorization: Bearer <token>`. If the client supports env-var resolution reliably, resolve the token from `CLOSED_AKASHIC_TOKEN`; otherwise use the client’s secure machine-local secret/header mechanism.

## Reuse
The point is consistency: all agents should use the same Closed Akashic endpoint and machine-level authentication, while keeping the real token out of repositories.

- Use [[Codex Central Memory Setup]] for the current canonical Codex setup flow.
- Use [[Closed Akashic Shared Agent Token Setup]] for token/header-specific guidance.
- Use [[Codex AGENTS Template]] as the source for `~/.codex/AGENTS.md`.
- Use [[Codex MCP Deployment]] as the copyable one-file setup guide.
- For failed remote connections, use [[MCP Debugging and Logs]].
