---
title: Agent Setup Snippets
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [agent, codex, mcp, setup]
related: [Distributed Agent Memory Contract, Remote Agent Enrollment, Codex MCP Deployment, MCP Debugging and Logs]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-13T00:00:00Z
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
