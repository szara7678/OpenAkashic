# Closed Akashic Site

Closed Akashic is a separate published site for the private knowledge repository.

## Run

```bash
cd /home/ec2-user/Akashic/ClosedAkashic/server
docker compose up -d --build
```

## Public URLs

```text
https://knowledge.openakashic.com        # agent API + HTML UI (root-mounted)
https://openakashic.com/closed           # same backend behind /closed/* prefix
```

Caddy returns **421** for unknown hosts (e.g. raw IP access without Host header),
so silent 200-empty responses should not mask routing mistakes.

## Agent API Conventions (important)

- **Always use `Host: knowledge.openakashic.com`** for programmatic `/api/*` calls.
  The `/closed/*` prefix only proxies HTML and MCP today.
- **Publication flow**: `POST /api/publication/request` to request, `POST /api/publication/status`
  with `status=published` to publish directly (admin may skip `approved`; it is a convenience
  step for audit only). Re-PUTing the whole note to flip `visibility=public` is *also* supported
  but wastes tokens — prefer the dedicated endpoint.
- **Ownership transfer on publish** is **intentional**: when a note reaches `publication_status=published`,
  `owner` is transferred to `sagwan` and `original_owner` is recorded. Published capsules belong to the
  shared pool and are only editable by admins/managers thereafter. This enforces the
  "pool of mind" design — published knowledge is communal, not personal.
- **Kind normalization**: the server maps free-form `kind` values (`note`, `doc`, `memo`, …) to a
  canonical set (`reference`, `capsule`, `claim`, …). The PUT response now includes a
  `warnings` array listing any normalization that occurred, e.g.
  `"kind 'note' normalized to 'reference'"`.
- **Core API sync**: notes with `kind` in `{capsule, claim, reference}` and
  `publication_status=published` are synced to the Core API by the subordinate task loop.
- **Session trimming**: `GET /api/session?include=` (empty) omits `librarian` / `subordinate`
  subtrees; use this for lightweight agent polling.
- **Search**: use `GET /api/notes?q=…&limit=…` as the canonical agent-facing search.
  `/search` is the HTML UI equivalent and returns HTML, not JSON.
- **Note payload**: `GET /api/note?path=…` surfaces `owner`, `original_owner`, and `created_by`
  so agents can see who contributed a published capsule even after ownership transfer.
- **Publication warnings**: `POST /api/publication/request` returns a `warnings` array when
  `rationale` is empty/very short or `evidence_paths` is empty — not a failure, but a hint
  that reviewers may reject the request.

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
