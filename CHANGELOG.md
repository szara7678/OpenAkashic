# Changelog

All notable changes to OpenAkashic are documented here.

---

## [Unreleased]

### Added — MCP tools (26 total, up from 21)

| Tool | What it does |
|---|---|
| `confirm_note(path, comment?)` | Independently endorse a note. `confirm_count` boosts retrieval ranking — higher means more agents independently verified this note. |
| `list_stale_notes(days_overdue?)` | Find notes whose freshness window has expired per their `decay_tier`. Useful before trusting old memory. |
| `snooze_note(path, days)` | Extend a note's stale window when it's still valid but you can't verify right now. |
| `resolve_conflict(path, verdict, comment?)` | Record a resolution when two agents wrote incompatible claims. Verdict: `keep` / `supersede` / `merge`. |
| `whoami()` | Return your token's profile (handle, role, vault scope). Call at session start to confirm which identity the MCP client is running as. |

### Added — `search_notes` improvements

- **`include_related` param** — when `True` (or the query contains reasoning words like *why/how/architecture/decision*), depth-1 graph neighbors of the top results are returned as `context_neighbors`. Useful for getting surrounding context without a second `read_note` call.
- **`_next` affordance** — every `search_notes` response now includes `"_next": {"read_note": {"path": "<top result>"}}` so models can continue directly without re-deriving the path.
- **Gap feedback in response** — when a zero-result miss is recorded as a knowledge gap, the response carries a `gap` field pointing to the auto-created gap note.

### Added — Busagwan (background clerk) new capabilities

Busagwan now runs an Ollama-backed tool loop with these new internal functions exposed as scheduled tasks:

| Task | What Busagwan does |
|---|---|
| `_detect_conflicts` | Scan published notes for incompatible claims and flag them as conflicts for agent resolution. |
| `_scan_stale_private_notes` | Per-owner scan of private notes past their decay window. Creates a summary note listing stale items. |
| `_draft_claim` | Extract atomic, testable claims from a source note and write them as `kind=claim` child notes. `auto_request=True` queues them for Sagwan review automatically. |
| `_analyze_search_gaps` | Promote the top frequently-missed queries into `doc/knowledge-gaps/` request notes (up to 10 per run). |
| `_verify_evidence_paths` | Before queuing a publication request, verify evidence URLs (HEAD request) and vault paths actually exist. |

### Added — Librarian (Sagwan) Claude CLI backend

The librarian can now run as a Claude Code CLI subprocess inside the container:

- `CLOSED_AKASHIC_LIBRARIAN_PROVIDER=claude-cli` switches the librarian backend from Ollama to the Claude Code CLI (`@anthropic-ai/claude-code` installed in the Docker image).
- `librarian_effective_base_url` property auto-resolves the Anthropic OpenAI-compat endpoint when `claude-cli` is set and no explicit base URL is configured.
- `_invoke_claude_cli`, `_build_cli_prompt`, `_run_claude_cli_librarian` — full CLI integration with MCP tool loop.

### Added — Semantic search in-memory cache

- Embedding vectors are now kept in an in-process memory cache between requests (`_get_mem_cache` / `_load_from_disk`).
- Background thread flushes the cache to disk asynchronously (`_schedule_bg_save` / `_flush_to_disk`) so cold restarts are fast.
- `flush_semantic_cache()` and `invalidate_semantic_cache()` are exposed for admin-triggered cache management.
- **Effect:** first search after restart is slightly slower (disk load); subsequent searches are significantly faster.

### Added — Thread-safe vault writes

- `vault.py` now uses per-path `threading.Lock` objects (`_get_path_lock`).
- Concurrent writes to the same note are serialized at the lock level, eliminating partial-write races in multi-agent environments.

### Added — Authentication improvements

- `POST /api/profile/setup-password` — provisioned token users (no password set) can set their password in a first-login flow without knowing the current password.
- `set_first_time_password` — backend function for the above, enforces that only users with no password set can use this path.
- `create_user` now accepts `provisioned=True` flag for token-only bootstrapped accounts.

### Changed — Config

| Setting | Change |
|---|---|
| `default_note_owner` | Default changed from `"admin"` to `"anonymous"`. Notes without explicit owner fall back to this. |
| `CLOSED_AKASHIC_OPEN_SIGNUP` | New boolean flag. `False` (default) = admin-invite only. `True` = allow self-registration on trusted networks. |
| Librarian API key | Now accepts `ANTHROPIC_API_KEY`, `CLOSED_AKASHIC_LIBRARIAN_API_KEY`, or `CODEX_API_KEY` — whichever is set. |
| `admin_username` / `admin_nickname` | Removed from config. Admin identity is now a first-class user in the user store, not a static env var. |

### Changed — Web UI (site.py)

- **Heading anchors** — h2/h3 automatically get slugified `id` + hover `#` link. Click copies absolute URL to clipboard (with `execCommand` textarea fallback for non-HTTPS contexts).
- **Search highlight** — query matches wrapped in `<mark class="hl">` in explorer, Cmd+K palette, and graph explorer. XSS-safe via `textContent` split / `DocumentFragment` assembly.
- **Cmd+K Recent** — empty-query palette shows a `Recent` section (localStorage, 6 notes, latest-first) before all notes. `recordRecentNote` is try/catch wrapped for Safari Private / quota.
- **Empty-state copy** — palette zero-results: `Nothing matches "…" — try a different keyword.` / empty vault: `Your vault is empty. Create your first note to get started.`
- **Skip link** — `<a class="skip-link" href="#main-content">` at body top for keyboard/screen-reader navigation. Both note and graph pages have `id="main-content"`.
- **Mini graph default-closed** — widget starts collapsed on all screen sizes; opens only when localStorage `closed-akashic-mini-graph === '1'`.
- **Explorer path density** — `.nav-link small` (path segment) hidden by default, visible only when link is active or `body.explorer-searching` is set.
- **Info tab copy trimmed** — descriptive filler sentences removed from the note metadata tab; functional messages (empty states, action hints) are kept.
- **Dark mode** — `html[data-theme="dark"] .mini-graph-fab` override added.
- **Search trigger rule** — explorer filter fires only on Enter or submit-button click, not on every keystroke. `body.explorer-searching` class toggle still fires on input to show path context.

---

## Earlier releases

See [git log](https://github.com/szara7678/OpenAkashic/commits/main) for full history.
