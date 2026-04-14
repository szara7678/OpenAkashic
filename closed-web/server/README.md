# Closed Akashic Site

Closed Akashic is a separate published site for the private knowledge repository.

## Run

```bash
cd /home/ec2-user/Akashic/ClosedAkashic/server
docker compose up -d --build
```

## Public URLs

```text
https://knowledge.openakashic.com
https://openakashic.com/closed
```

## Source

The service reads the whole repository at:

```text
/home/ec2-user/Akashic/ClosedAkashic
```

## Agent Deployment

Use this Markdown when attaching a Codex host to the central Closed Akashic MCP memory:

```text
/home/ec2-user/Akashic/ClosedAkashic/doc/agents/Codex MCP Deployment.md
```

Browser page:

```text
https://knowledge.openakashic.com/notes/codex-mcp-deployment
```

## Debugging

Authenticated debug endpoints:

```text
https://knowledge.openakashic.com/debug
https://knowledge.openakashic.com/api/debug/status
https://knowledge.openakashic.com/api/debug/recent-requests
https://knowledge.openakashic.com/api/debug/log-tail
```

The browser debug console supports search, type, method, status, request id, time/type/status/method/duration sorting, and ascending/descending order.

Persistent request log:

```text
/home/ec2-user/Akashic/ClosedAkashic/server/logs/requests.jsonl
```
