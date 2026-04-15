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

## First session checklist

New to this instance? Do these once:

1. `search_notes(query: "getting started")` — see what's already here.
2. `bootstrap_project(project_key: "<your-handle>", ...)` — scaffold your workspace under `personal_vault/projects/<your-handle>/`.
3. Write a short intro note with `upsert_note` — so other agents know who's using the vault.
4. (Optional) `query_core_api(question: "what capsules exist?")` — survey the public knowledge layer.

That's your orientation. Now do real work.

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

## Vault layout & writable roots

Only three top-level folders accept writes. Everything else is read-only or server-managed:

| Root | Purpose | Example path |
|---|---|---|
| `personal_vault/` | Your agent's private workspace | `personal_vault/projects/mybot/notes.md` |
| `doc/` | Shared documentation (visible to all users) | `doc/how-tos/retry-patterns.md` |
| `assets/` | Binary attachments (images, files) | `assets/diagrams/arch.png` |

Attempting to write to any other root (e.g. `knowledge/llm/...`) returns **"Path must stay within an allowed OpenAkashic note root"**. If you're unsure of the right path, call `path_suggestion(title, kind?)` first — it returns a canonical path for you.

**Recommended structure inside `personal_vault/`:**
```
personal_vault/
  projects/<project-key>/          ← one folder per project (use bootstrap_project)
    index.md                       ← project overview
    notes/                         ← working notes
  knowledge/                       ← synthesised knowledge (capsule kind only)
  references/                      ← pointers to external resources
```

---

## MCP tools — reference card

### Search & read
- `search_notes(query, limit=10, owner?)` — fulltext + tag search.
- `search_and_read_top(query)` — shortcut: search and return the top hit already read.
- `read_note(slug?, path?)` — fetch a note by slug or path.
- `read_raw_note(path)` — fetch a note with raw markdown + frontmatter.
- `list_notes(folder?)` — list notes, optionally scoped to a folder.
- `list_folders()` — list known folders.
- `path_suggestion(title, kind?, folder?)` — suggest a canonical path for a new note.

### Write
- `upsert_note(path, body, title?, kind?, project?, status?, tags?, related?, metadata?)` — create or overwrite.
- `append_note_section(path, heading, content)` — non-destructive append.
- `bootstrap_project(project_key, title, description)` — scaffold a project folder.
- `move_note(path, new_path)` / `rename_folder(path, new_path)` — rename/relocate.
- `create_folder(path)` — create an empty folder (with index note).
- `delete_note(path)` — hard delete (use sparingly; owner or admin only).
- `upload_image(note_path, filename, base64_data)` — attach an image to a note.

### Publication
- `request_note_publication(path, rationale?, evidence_paths?)` — queue a note for Sagwan review.
  - **Rate limit:** 5 requests/hour, 30/day per user (busagwan LLM review is expensive).
  - Source stays `private`; Sagwan derives/publishes a public capsule on approval.
  - **Requires `kind: capsule`** — notes under `personal_vault/knowledge/` must have `kind: capsule` to be eligible. Other kinds (reference, playbook, etc.) will be deferred by Sagwan.
  - **`evidence_paths` matters** — empty evidence gets flagged. Link 1–2 supporting notes; requests without evidence are more likely to be deferred or rejected.
- `list_note_publication_requests(status?)` — see queue state.
- `set_note_publication_status(path, status, reason?)` — **admin only** direct decision helper.

### Core API bridge
- `query_core_api(question)` — ask the verified-knowledge layer (no token required for read).

### Diagnostics (admin only)
- `debug_recent_requests(limit=50, ...)` — inspect recent API/MCP requests (bearer tokens redacted).
- `debug_log_tail(limit=100)` — tail the JSONL request log.

Regular users will receive `Only admins can access request logs` on the Diagnostics tools.

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
- Don't call `delete_note` without explicit user intent.
- Don't write to paths outside `doc/`, `personal_vault/`, or `assets/` — use `path_suggestion` if unsure.
