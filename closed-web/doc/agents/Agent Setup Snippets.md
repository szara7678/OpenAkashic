---
title: "Agent Setup Snippets"
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [agent, codex, mcp, setup]
related: ["Distributed Agent Memory Contract", "Remote Agent Enrollment", "Codex MCP Deployment", "MCP Debugging and Logs"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-17T08:21:01Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
core_api_id: 30389611-3e68-46b7-b7a1-05414ca7f45f
last_validated_at: 2026-04-17T08:21:01Z
sagwan_validation_count: 5
sagwan_last_validation_verdict: refresh
sagwan_last_validation_note: "이전 검증(2026-04-15)의 CLOSED_AKASHIC_TOKEN 표준화 미해결. 현재 ~/.claude/settings.json 방식과 조화 필요."
---

## Summary
All agents should point to the same Closed Akashic MCP endpoint and use the same bearer token environment variable.

## Shared Values
- MCP endpoint: `https://knowledge.openakashic.com/mcp/`
- API base: `https://knowledge.openakashic.com/api/`
- bearer token env var: `CLOSED_AKASHIC_TOKEN`

## Codex Example
Add this to `~/.codex/config.toml` on each Codex host:

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

Add the matching host-level instructions to `~/.codex/AGENTS.md`. Use [[Codex AGENTS Template]] as the source.

## Shell Example
```bash
export CLOSED_AKASHIC_TOKEN="set-your-master-token-here"
```

For persistent shell sessions, put the export in a host-local shell profile or service environment. Keep the token out of project repositories.

## Generic MCP Client Example
Use a client entry that points to the same `url` and resolves the bearer token from `CLOSED_AKASHIC_TOKEN`. Keep the token outside the repository when possible.

## Reuse
The point is consistency. Different agents may have different config files, but they should all resolve to the same endpoint, the same token variable, and the same project README structure.

For Codex hosts, [[Codex MCP Deployment]] is the copyable one-file setup guide.
For failed remote connections, use [[MCP Debugging and Logs]].

## Sagwan Revalidation 2026-04-15T06:47:38Z
- verdict: `refresh`
- note: CLOSED_AKASHIC_TOKEN 환경 변수명이 현재 표준(~/.claude/settings.json에서 읽는 방식)과 불일치.

## Sagwan Revalidation 2026-04-15T06:56:03Z
- verdict: `refresh`
- note: 노트의 CLOSED_AKASHIC_TOKEN이 현재 ~/.claude/settings.json 기반 표준과 불일치.

## Sagwan Revalidation 2026-04-15T07:13:35Z
- verdict: `refresh`
- note: CLOSED_AKASHIC_TOKEN 환경변수 방식이 ~/.claude/settings.json 표준과 맞지 않으며, 이전 refresh 미적용.

## Sagwan Revalidation 2026-04-16T08:18:21Z
- verdict: `refresh`
- note: CLOSED_AKASHIC_TOKEN 환경변수 권장이 현재표준(~/.claude/settings.json)과 불일치하여 업데이트 필요.

## Sagwan Revalidation 2026-04-17T08:21:01Z
- verdict: `refresh`
- note: 이전 검증(2026-04-15)의 CLOSED_AKASHIC_TOKEN 표준화 미해결. 현재 ~/.claude/settings.json 방식과 조화 필요.
