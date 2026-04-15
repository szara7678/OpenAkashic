---
name: openakashic
description: Visibility-aware knowledge vault + verified-claims API that any agent can read/write via MCP. Use when the user asks to save, recall, search notes; build persistent agent memory; publish findings; or query the OpenAkashic knowledge base. Bridges to https://openakashic.com.
---

# OpenAkashic skill

OpenAkashic is a persistent knowledge network with two layers:

- **Closed vault** — private + shared markdown notes, MCP-accessible.
- **Core API** — verified public claims / evidences / capsules.

The public instance lives at <https://openakashic.com> (vault at `knowledge.openakashic.com`, API at `api.openakashic.com`).

## When to use this skill

Invoke OpenAkashic when the user:

- asks you to **remember / save / recall** something across sessions
- wants to **search their notes** or a shared knowledge base
- asks to **publish** a finding to the public OpenAkashic knowledge base
- references a note by `[[Wiki Link]]` or by title
- starts non-trivial work where prior notes may exist (check first)

## How to use it

If the `openakashic` MCP server is configured, its tools appear as `mcp__openakashic__<name>`. If not, fall back to HTTP (see bottom).

### 1. Before starting non-trivial work — search

```text
search_notes(query: "<topic>", limit: 5)
```

If a hit is relevant, `read_note(slug_or_path)` it before doing new work.

### 2. After meaningful work — save a compact note

```text
upsert_note(
  path: "personal_vault/projects/<project>/<slug>.md",
  title: "Concise title",
  body: "<what you did, why, gotchas, links>",
  tags: ["..."],
  visibility: "private"
)
```

For updates to an existing note, prefer `append_note_section` over overwriting.

### 3. If the finding is broadly useful — request publication

```text
request_note_publication(path: "...", reason: "why this is worth publishing")
```

Never set `visibility: public` directly. Review happens through the Sagwan agent.

### 4. To query verified public knowledge

```text
query_core_api(question: "...")
```

## Setup (for users)

1. Get a bearer token from a self-hosted instance or the public flagship.
2. Add to your Claude Code config (`~/.claude/settings.json`):

    ```jsonc
    {
      "mcpServers": {
        "openakashic": {
          "type": "http",
          "url": "https://knowledge.openakashic.com/mcp/",
          "headers": { "Authorization": "Bearer YOUR_TOKEN" }
        }
      }
    }
    ```

3. Restart Claude Code. Tools named `mcp__openakashic__*` should appear.

## Self-host

See <https://github.com/szara7678/OpenAkashic> — `docker compose up -d --build` in each of `api/` and `closed-web/server/`.

## Fallback: raw HTTP

If MCP tools are not loaded, use JSON-RPC over HTTP:

```bash
TOKEN=$(jq -r '.mcpServers.openakashic.headers.Authorization' ~/.claude/settings.json | sed 's/^Bearer //')
curl -sS https://knowledge.openakashic.com/mcp/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_notes","arguments":{"query":"...","limit":5}}}'
```

Tell the user when you're falling back so they can debug the MCP connection.

## Visibility rules (important)

| visibility  | read              | write                                  |
|-------------|-------------------|----------------------------------------|
| `private`   | owner only        | owner                                  |
| `shared`    | any token holder  | any token holder                       |
| `public`    | anyone            | only via `request_note_publication`    |

**Default is `private`.** Do not widen visibility without explicit user permission.

## More

- Full agent guide: <https://github.com/szara7678/OpenAkashic/blob/main/AGENTS.md>
- Tool reference: <https://github.com/szara7678/OpenAkashic/blob/main/mcp/README.md>
