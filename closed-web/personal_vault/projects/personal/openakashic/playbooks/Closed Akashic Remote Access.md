---
title: "Closed Akashic Remote Access"
kind: playbook
project: personal/openakashic
status: active
tags: [mcp, api, agent, memory]
related: ["Agent Memory Workflow", "AWS Central Vault", "Agent Guide"]
updated_at: 2026-04-13T10:00:00Z
created_at: 2026-04-11T18:12:43Z
confidence: high
---

## Summary
Closed Akashic exposes authenticated MCP and API access from the main server so remote agents can share one memory surface.

## Details
- MCP endpoint: https://knowledge.openakashic.com/mcp/
- API prefix: https://knowledge.openakashic.com/api/
- Bearer env var for local agents: CLOSED_AKASHIC_TOKEN
- Writable roots: doc/, personal_vault/

## Reuse
Before substantial work, search this vault through MCP. After meaningful work, update the best matching note or append one focused section.

## 2026-04-13 Explorer And Folder Refresh
- Explorer sidebar now uses a single sidebar scroll instead of a nested explorer scroll.
- Folder groups are collapsible and default to collapsed; the current note path opens automatically.
- Vault layout now distinguishes `shared`, `personal`, and `projects/personal|company`.
- MCP now exposes `move_note`, `create_folder`, and `rename_folder` so remote agents can reorganize the vault without shell access.
- Verified `path_suggestion` with `project: company/acme` returns `personal_vault/projects/company/acme/playbooks/ACME Onboarding.md`.

## 2026-04-13 Browser Editing And Agent Bootstrap
- Browser note pages now expose a token-gated workspace panel for human editing.
- The site can create notes, edit existing notes, suggest paths, create folders, and upload images through the existing authenticated API.
- Closed Akashic now treats local `./agent-knowledge` as a bootstrap layer: read `common-rules.md`, `playbook.md`, `guardrails.md`, then move into project docs and persistent Akashic memory.
- Project memory was initially organized around `projects/personal/<project>` and `projects/company/<project>` with small project index notes pointing to canonical repo docs.
- Asset file responses now render inline instead of forcing attachment headers.

## 2026-04-13 Distributed Agent Contract
Earlier standardized multi-server use around one shared contract: local `agent-knowledge` as bootstrap, repo `doc/` as canonical truth, and Closed Akashic MCP/API as the durable memory layer. This was later superseded by the central MCP only model. Added `bootstrap_project` over MCP plus `/api/project/bootstrap` so remote agents can create or verify `personal_vault/projects/<scope>/<project>/README.md` and core project folders without improvising.

## 2026-04-13 Central MCP Replaces Agent Knowledge
Closed Akashic now replaces local `agent-knowledge` as the default agent memory bootstrap. Each Codex host should keep only a small `~/.codex/AGENTS.md` and a `closed-akashic` MCP entry in `~/.codex/config.toml`, both pointing to `https://knowledge.openakashic.com/mcp/` with token env var `CLOSED_AKASHIC_TOKEN`. Added `doc/agents/Codex Central Memory Setup.md` and `doc/agents/Codex AGENTS Template.md`; updated the distributed contract, enrollment playbook, project intake flow, local `.codex/AGENTS.md`, and deprecated the local `agent-knowledge` folder as historical reference only.

## 2026-04-13 Deployable Codex MCP Guide And Flexible Projects
Added a self-contained deployment Markdown at `doc/agents/Codex MCP Deployment.md` so a fresh Codex host can read one file, update `~/.codex/config.toml`, write `~/.codex/AGENTS.md`, and attach to `https://knowledge.openakashic.com/mcp/` using `CLOSED_AKASHIC_TOKEN`. Project folders are no longer treated as fixed personal/company introduction pages: the index pattern is now `personal_vault/projects/<scope>/<project>/README.md`, scopes are flexible, and agents can create/update project structure through `bootstrap_project`, `create_folder`, `rename_folder`, `move_note`, and `path_suggestion`. `bootstrap_project` now accepts optional `folders` to create agent-defined structures such as `deployments`, `qa/smoke`, and `prompts`.

## 2026-04-13 Local Codex Host Applied Deployment Guide
Applied `doc/agents/Codex MCP Deployment.md` to the current `/home/ec2-user` Codex host. Replaced `/home/ec2-user/.codex/AGENTS.md` with the deployment template, verified `/home/ec2-user/.codex/config.toml` contains `[mcp_servers.closed-akashic]` pointing at `https://knowledge.openakashic.com/mcp/`, confirmed `CLOSED_AKASHIC_TOKEN` loads in a fresh login shell through the host profile, and smoke-tested the authenticated API with the token without printing the secret.

## 2026-04-13 Codex Workspace Verification
- Verified from `/home/arica/arica/arc-fleet` that `CLOSED_AKASHIC_TOKEN` is present in the shell environment.
- `https://knowledge.openakashic.com` returned `200` and the browser surface loaded.
- MCP `tools/list` succeeded when the client sent `Accept: application/json, text/event-stream`.
- `search_notes` returned the `personal/openakashic` project index and related playbooks.
- `read_note` loaded `personal_vault/projects/personal/openakashic/README.md` and this playbook, confirming authenticated read access from this host.

## 2026-04-13 MCP Debug Logging
Added safe observability for Closed Akashic MCP/API traffic. The server now logs API and MCP requests through an ASGI middleware without recording bearer tokens or request bodies, writes persistent JSONL logs to `server/logs/requests.jsonl`, keeps an in-memory recent request ring buffer, and exposes authenticated debug endpoints: `/api/debug/status`, `/api/debug/recent-requests`, and `/api/debug/log-tail`. Also added MCP tools `debug_recent_requests` and `debug_log_tail`, plus `doc/agents/MCP Debugging and Logs.md` with remote smoke-test steps using `X-Request-ID`. Verified a `/mcp/` request with a unique request id appears in the debug API and that debug status/log-tail work with the bearer token.

## 2026-04-13 Web Edit Root Note Fix
Fixed a browser edit failure where the site rendered root `README.md` and non-note markdown such as `server/README.md`, but the authenticated edit API only allowed configured writable note roots. Root `README.md` and `AGENTS.md` are now treated as editable top-level note files, the published note list is driven by the allowed note path index, and invalid edit paths return 400/404/409 instead of 500. Verified `/api/raw-note?path=README.md`, browser `Edit Note` opening on the home page, and create/read/delete smoke flow for a temporary note under `personal_vault/shared/reference/`.

## 2026-04-13 Resizable Sidebar UX
Updated the Closed Akashic note UI so deep explorer paths remain readable. The note page now defaults the left sidebar to 340px, adds a draggable desktop resize handle with `closed-akashic-sidebar-width` localStorage persistence, reduces compounded tree indentation, and allows long folder/note names and paths to wrap instead of clipping. Verified with Playwright on a deep `company/arc-fleet/reference/page-css` note: drag resized the sidebar from 340px to 500px and persisted it; mobile viewport hides the handle and keeps body width equal to viewport width.

## 2026-04-13 Breadcrumb Explorer Highlight
Updated the Closed Akashic note header path into clickable breadcrumb segments. Each explorer folder and note now carries a `data-path`; clicking a folder segment opens its ancestor folders, scrolls the matching sidebar folder into view, and applies a temporary highlight. Clicking the file segment scrolls/highlights the active note. Verified with Playwright on `/notes/로봇관리-css-index`: clicking `page-css` highlighted the `personal_vault/projects/company/arc-fleet/reference/page-css` folder, and clicking `로봇관리 CSS Index.md` highlighted the matching active nav link.

## 2026-04-13 Image Upload Save Flow
Investigated `personal_vault/projects/personal/portfolio/reference/my_photo.md` after the page showed no image. The note body contained only `## Summary`, and request logs showed no `POST /api/assets/images` for that edit, so the selected image had not been persisted into the note body. Updated the web editor so if an image file is selected but not yet uploaded, `Save Note` first uploads the image, inserts the returned Markdown into the body, and then saves the note. The explicit `Upload Image` button still works.

## 2026-04-13 Notion-like Web Shell Refresh
Updated the Closed Akashic web surface to behave more like a lightweight Notion workspace.

- Note pages now have a sticky top workspace bar with sidebar, search, graph, document, info, relations, edit, new, and panel controls.
- The left explorer can be collapsed or resized, and the right metadata panel can be hidden or switched between Info, Relations, and Edit.
- The right panel exposes note metadata, tags, relation helpers, and the existing authenticated editor/image upload drawer from one consistent place.
- Graph view now has a compact top workspace bar and floating controls/details panels that can be hidden, restored, and resized on mobile.
- Debug view now has a Filters toggle so request logs can use the full width when needed.
- Validation: rebuilt `closed-akashic-web`, confirmed `https://knowledge.openakashic.com/health`, and used Playwright on desktop and 390px mobile to verify note/graph/debug controls with no horizontal overflow.

## 2026-04-13 Unified Sidebar And Inline Editor Refresh
Reworked the previous Notion-like shell after the first version duplicated top tabs, right sidebar panels, and sidebar tabs.

- Top navigation now stays minimal: Home, Graph, Debug, plus the sidebar toggle.
- Removed the right sidebar from note pages.
- Moved Explore, Info, Relations, and Edit into left sidebar tabs.
- Clicking the title, summary, or document body enters inline edit mode after token unlock.
- Inline editing now covers title, summary, body Markdown, block snippets, image upload, file attachment links, image width markup, note metadata, related notes, path suggestions, folder creation, save, cancel, and delete.
- Added `/api/assets/files` and generic `save_asset` support so non-image files can be uploaded into `assets/files` and inserted as Markdown links.
- Graph view now uses a single floating menu with internal Search, Selection, and Display tabs instead of separate controls/details panels.
- Added `personal_vault/shared/reference/Agent UI Skills and Editor References.md` to document relevant local skills and external UI/editor references.
- Validation: rebuilt `closed-akashic-web`, verified health, Playwright-checked note sidebar tabs, inline edit entry/cancel, graph single-menu tabs, 390px mobile overflow, and `/api/assets/files` upload smoke.
