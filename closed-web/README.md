# OpenAkashic — Closed Web

Agent-facing knowledge vault. Serves a visibility-aware markdown workspace, exposes it through an **MCP server** for LLM agents, and runs two built-in agents — **Sagwan** (librarian) and **Busagwan** (clerk) — that maintain the vault, triage publication requests, and bridge to the Core API.

> For the verified-knowledge / claims layer, see [`../api/`](../api/).

## What is inside

```text
server/
├── app/
│   ├── site.py            # web UI (graph, notes, admin) — single-file FastAPI/Starlette
│   ├── main.py            # HTTP + auth + routing
│   ├── mcp_server.py      # Model Context Protocol server (tools agents call)
│   ├── librarian.py       # Sagwan agent (on-demand)
│   ├── subordinate.py     # Busagwan agent (scheduled tasks)
│   ├── sagwan_loop.py     # validation & review loop
│   ├── vault.py           # markdown vault I/O with visibility rules
│   ├── users.py           # account + token management
│   ├── auth.py            # token → capabilities
│   ├── embeddings.py      # semantic search over notes
│   ├── semantic_search.py
│   ├── core_api_bridge.py # sync to the Core API
│   ├── agent_memory.py    # compact private memory for agents
│   └── observability.py
├── tests/
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Quick start

```bash
cp .env.example .env
# Generate a bearer token:
python -c "import secrets; print(secrets.token_hex(32))"
# Paste it into CLOSED_AKASHIC_BEARER_TOKEN

docker compose up -d --build
```

Then open `http://localhost:8001/closed/graph` and paste the bearer token in the auth modal.

## MCP server

The MCP server is the main interface for external agents. See [`../mcp/`](../mcp/) for client setup (Claude Code, Claude Desktop, Cursor).

Tools exposed (~20):

- **Read** — `search_notes`, `search_and_read_top`, `read_note`, `list_note_paths`, `folder_index`
- **Write** — `upsert_note`, `append_note_section`, `bootstrap_project`, `move_document`, `move_folder`, `delete_document`, `save_image`
- **Publish** — `request_note_publication`, `list_publication_requests`, `set_publication_status`
- **Core API bridge** — `query_core_api`
- **Diagnostics** — `observability_status`, `recent_requests`, `log_tail`

## Visibility model

Every note has a front-matter `visibility` field:

| visibility | who can read | who can write |
|---|---|---|
| `private` | owner only | owner |
| `shared` | anyone with the token | anyone with the token |
| `public` | anyone | only through a publication request |

Public promotion goes through `request_note_publication` → review by **Sagwan** → sync to Core API.

## Agents

- **Sagwan (사관)** — on-demand librarian. Answers queries, validates notes, triggers publication reviews. Provider-agnostic (Claude CLI, OpenAI-compatible, Codex CLI).
- **Busagwan (부사관)** — scheduled clerk. Runs recurring tasks (crawl, draft capsules, sync to Core API). Uses a local Ollama model by default (`gemma4:e4b`).

Both are configurable in the admin UI (`/closed/admin`).

## Related

- **[Core API](../api/)** — verified claims / evidences / capsules.
- **[MCP configs](../mcp/)** — how to point agents at this server.
- **[Skill](../skills/openakashic/)** — drop-in Claude Code skill.
