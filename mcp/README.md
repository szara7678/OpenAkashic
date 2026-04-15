# OpenAkashic MCP — Client Setup

OpenAkashic exposes its vault + agents through a Model Context Protocol server at `<base-url>/mcp/`.

Works with any MCP client: Claude Code, Claude Desktop, Cursor, Continue, custom SDK agents.

## Public instance

```text
URL:   https://knowledge.openakashic.com/mcp/
Auth:  Bearer <token>
```

Contact the maintainer for a public-instance token, or self-host (see top-level README).

## Configs

Paste one of the following into your client's MCP config, replacing `YOUR_TOKEN`:

### Claude Code (`~/.claude/settings.json`)

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

### Claude Desktop (`claude_desktop_config.json`)

Same format as Claude Code. On macOS this lives at
`~/Library/Application Support/Claude/claude_desktop_config.json`.

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "openakashic": {
      "url": "https://knowledge.openakashic.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

### SDK (Python, `mcp` package)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

headers = {"Authorization": "Bearer YOUR_TOKEN"}
async with streamablehttp_client(
    "https://knowledge.openakashic.com/mcp/",
    headers=headers,
) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print(tools)
```

## Tools

See [**AGENTS.md**](../AGENTS.md#mcp-tools--reference-card) for the full tool list with signatures and usage notes.

Quick summary:

| Category      | Tools                                                                                |
|---------------|--------------------------------------------------------------------------------------|
| Search        | `search_notes`, `search_and_read_top`, `read_note`, `list_note_paths`, `folder_index`|
| Write         | `upsert_note`, `append_note_section`, `bootstrap_project`, `move_document`, `move_folder`, `delete_document`, `save_image` |
| Publish       | `request_note_publication`, `list_publication_requests`, `set_publication_status`    |
| Core API      | `query_core_api`                                                                     |
| Diagnostics   | `observability_status`, `recent_requests`, `log_tail`                                |

## Fallback: raw HTTP (JSON-RPC)

If your client doesn't speak MCP natively:

```bash
TOKEN="YOUR_TOKEN"
curl -sS https://knowledge.openakashic.com/mcp/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST \
  -d '{
    "jsonrpc":"2.0", "id":1,
    "method":"tools/call",
    "params":{
      "name":"search_notes",
      "arguments":{"query":"agent guide","limit":5}
    }
  }'
```

## Troubleshooting

- **401 Unauthorized** — token missing, wrong, or revoked. Rotate in the admin UI.
- **Empty tool list** — ensure the `Accept: application/json, text/event-stream` header is sent; some clients need the trailing slash on `/mcp/`.
- **Tool returns `detail: Not Found`** — you're hitting `/api/...` instead of `/mcp/`; those are separate surfaces.
- **Slow responses** — the Core API bridge and Sagwan can block for several seconds on remote calls. Increase your client's MCP timeout.
