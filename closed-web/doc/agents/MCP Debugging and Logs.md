---
title: "MCP Debugging and Logs"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [mcp, debug, logs, troubleshooting]
related: ["Codex MCP Deployment", "Codex Central Memory Setup", "Closed Akashic Remote Access"]
created_at: 2026-04-13T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
Closed Akashic records safe request logs for API and MCP traffic. Logs redact bearer tokens and secret-like fields, then keep bounded request/response body previews for debugging.

## What Gets Logged
- timestamp
- request id
- method
- path
- sanitized query string
- status code
- duration
- response bytes
- client IP from forwarding headers when available
- host
- user agent
- Cloudflare ray id when present
- sanitized request headers and response headers
- bounded request body preview and response body preview
- binary or multipart payload summaries instead of raw file bodies

## Debug API
All debug API routes require the same bearer token.

Browser console:

```text
https://knowledge.openakashic.com/admin
```

The browser console uses the same master token stored in localStorage and supports search, request type, method, status, request id, limit, sort, and order filters.

```bash
curl -fsS https://knowledge.openakashic.com/api/debug/status \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

```bash
curl -fsS "https://knowledge.openakashic.com/api/debug/recent-requests?path_prefix=/mcp&limit=50" \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

Useful recent-request filters:

```text
kind=mcp|api|debug|page|asset|health|other
method=GET|POST|PUT|DELETE
status_min=400
request_id=<exact id>
q=<path, user agent, cf-ray, id, status, error>
sort_by=time|kind|status|method|duration
order=desc|asc
limit=1..500
```

Example:

```bash
curl -fsS "https://knowledge.openakashic.com/api/debug/recent-requests?kind=mcp&sort_by=duration&order=desc&limit=25" \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

```bash
curl -fsS "https://knowledge.openakashic.com/api/debug/log-tail?limit=100" \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

## Request ID Smoke Test
From the remote server, send a unique request id.

```bash
REQ_ID="remote-mcp-test-$(date +%s)"

curl -i https://knowledge.openakashic.com/mcp/ \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN" \
  -H "X-Request-ID: $REQ_ID"
```

Then inspect it from any authenticated host.

```bash
curl -fsS "https://knowledge.openakashic.com/api/debug/recent-requests?request_id=$REQ_ID" \
  -H "Authorization: Bearer $CLOSED_AKASHIC_TOKEN"
```

## MCP Tools
When MCP connection works enough to call tools, use:

- `debug_recent_requests`
- `debug_log_tail`

`debug_recent_requests` accepts the same core filters: `limit`, `path_prefix`, `status_min`, `request_id`, `method`, `kind`, `q`, `sort_by`, and `order`.

If MCP cannot initialize at all, use the debug API instead.

## Host Logs
On the main server:

```bash
docker logs closed-akashic-web --tail 100
```

Persistent JSONL request log:

```text
/home/ec2-user/Akashic/ClosedAkashic/server/logs/requests.jsonl
```

## Reuse
When another server has MCP trouble, first check `/health`, then `/api/debug/status`, then recent MCP requests in `/admin` or `/api/debug/recent-requests` filtered by `kind=mcp`, `request_id`, or a search term.

## Debug Console UI Update
2026-04-13: Added the browser debug console at `https://knowledge.openakashic.com/admin`. It uses the browser's `closed-akashic-token` localStorage key, loads `/api/debug/status` and `/api/debug/recent-requests`, and supports search plus `kind`, `method`, `status_min`, `request_id`, `limit`, `sort_by`, and `order` filters. Use this page first when a remote Codex host reports MCP connection trouble, then narrow to `kind=mcp` or an exact request id.

## 2026-04-13 Debug Modal And Body Preview Update
Closed Akashic debug now stores sanitized request/response detail previews for recent API and MCP traffic. The debug console request rows open a modal with request headers, response headers, request body preview, and response body preview. Authorization, cookies, token, access_token, api_key, password, and secret-like fields are redacted before storage. Multipart and binary payload bodies are summarized instead of stored. Debug log API responses omit their own response body to avoid recursive log growth.

UI notes: Graph View uses resizable floating control/detail panels with hide/show buttons. On mobile the panels stack, stay inside the viewport, and text-heavy fields such as degree/path wrap inside their metric cells. Markdown note rendering now wraps long paragraphs, inline code, fenced code, tables, and related-note cards so content does not push outside its card.
