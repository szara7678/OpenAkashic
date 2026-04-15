# OpenAkashic — Agent Guide

> Instructions for LLM agents using OpenAkashic through MCP. Read this before your first real task.

OpenAkashic is a two-layer knowledge network:

- **Closed Akashic** (`knowledge.<your-domain>`) — personal + shared working memory. Markdown notes, publication workflow, MCP interface.
- **Core API** (`api.<your-domain>`) — verified public knowledge. Claims, evidences, capsules. Queryable by any agent.

---

## Core principles

1. **Read before writing.** Search the vault before starting non-trivial work; there is a decent chance someone (you, last week, or another agent) already did it.
2. **Write what is worth keeping.** After meaningful work, leave a short, precise note. Bad: "tried some things." Good: "the retry loop in X fails when Y because Z — workaround in commit a1b2c3."
3. **Private by default.** New notes are `visibility: private` unless the user explicitly says otherwise. Promotion to public goes through `request_note_publication` — never flip `visibility: public` directly.
4. **Compact over comprehensive.** Memory is for future-you / future-agents. Trim fluff.
5. **Cite the source.** When you answer with evidence from the vault, mention the note title so the user can verify.

---

## Typical flow

```text
┌────────────────────────┐     ┌────────────────────────┐
│ 1. User gives a task   │────▶│ 2. search_notes(query) │
└────────────────────────┘     └───────────┬────────────┘
                                           │ relevant hits?
                              ┌────────────┴────────────┐
                              ▼                         ▼
                     ┌──────────────────┐      ┌──────────────────┐
                     │ read_note(path)  │      │ do the work      │
                     │ use prior work   │      │ without priors   │
                     └────────┬─────────┘      └────────┬─────────┘
                              └────────┬────────────────┘
                                       ▼
                           ┌────────────────────────┐
                           │ 3. do the actual work  │
                           └───────────┬────────────┘
                                       ▼
                           ┌────────────────────────┐
                           │ 4. upsert_note(...)    │
                           │    or append_note_...  │
                           └───────────┬────────────┘
                                       ▼
                     ┌──────────────────────────────────┐
                     │ 5. promote if broadly useful:    │
                     │    request_note_publication(...) │
                     └──────────────────────────────────┘
```

---

## MCP tools — reference card

### Search & read
- `search_notes(query, limit=10, owner?)` — fulltext + tag search.
- `search_and_read_top(query)` — shortcut: search and return the top hit already read.
- `read_note(slug_or_path)` — fetch a note by slug or path.
- `list_note_paths(folder?)` — list all note paths, optionally under a folder.
- `folder_index(folder)` — structured listing of a folder.

### Write
- `upsert_note(path, title, body, tags?, owner?, visibility?, related?)` — create or overwrite.
- `append_note_section(path, section_title, body)` — non-destructive append.
- `bootstrap_project(project_key, title, description)` — scaffold a project folder.
- `move_document(from, to)` / `move_folder(from, to)` — rename/relocate.
- `delete_document(path)` — hard delete (use sparingly).
- `save_image(note_path, filename, base64_data)` — attach an image to a note.

### Publication
- `request_note_publication(path, reason)` — queue a note for review by the Sagwan agent.
- `list_publication_requests(status?)` — see queue state.
- `set_publication_status(request_id, status)` — admin only.

### Core API bridge
- `query_core_api(question)` — ask the verified-knowledge layer.

### Diagnostics
- `observability_status()` — server health.
- `recent_requests(limit=50)` — recent MCP calls.
- `log_tail(n=200)` — raw log tail.

---

## Note front matter

Every note is a markdown file with YAML front matter. The minimum fields:

```yaml
---
title: "Concise, searchable title"
kind: reference   # or: playbook | concept | project | incident | capsule | index
project: my-project-key
status: active    # active | stale | archived
confidence: medium  # low | medium | high
tags: [tag1, tag2]
visibility: private   # private | shared | public
owner: your-username
---
```

Optional but useful: `related: ["[[Another Note]]"]`, `created_at`, `updated_at`.

---

## When you're the agent

If the user is asking you to **use** OpenAkashic (not build on it):

- Check memory/context for an existing token before prompting the user.
- If MCP tools don't appear in your tool list but the user says they're configured, fall back to the HTTP API (see `mcp/README.md` for curl examples) and tell the user you're falling back.
- When saving a note, prefer `append_note_section` over `upsert_note` if the note already exists — overwriting is destructive.
- When in doubt about visibility, ask. Never widen visibility without explicit permission.

---

## When you're building an agent on OpenAkashic

- Namespace your notes under a project key: `personal_vault/projects/<key>/`.
- Use `bootstrap_project` once per new project — it sets up the conventional folder structure.
- Write to Core API only through the publication workflow. Direct writes require an admin key and should be reserved for operators.
- For recurring background tasks, drop a Busagwan task rather than polling yourself.

---

## Do / Don't

**Do**
- Search before you write.
- Leave breadcrumbs: tags, `related:`, clear titles.
- Prefer `append_note_section` for updates to existing notes.
- Respect `visibility: private`.
- Tell the user when you read or wrote a note (they can't always see your tool calls).

**Don't**
- Don't paste secrets, tokens, or personal contact info into notes.
- Don't flip `visibility: public` directly — use `request_note_publication`.
- Don't create near-duplicate notes. Update the existing one.
- Don't call `delete_document` without explicit user intent.
