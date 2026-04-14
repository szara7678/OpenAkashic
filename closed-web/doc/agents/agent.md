---
title: "Agent Guide"
kind: playbook
project: closed-akashic
status: active
confidence: high
tags: [agent, codex, cursor, opencode, memory]
related: ["LLM Maintained Wiki", "Vault Note Schema", "Agent Memory Workflow", "AWS Central Vault"]
created_at: 2026-04-11T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
Codex, Cursor, OpenCode and similar agents should treat Closed Akashic as a persistent working memory, not as a one-shot retrieval dump.

The intended access path is remote MCP and authenticated API access to the main server, so agents on other machines can use the same memory instead of cloning a local copy and drifting apart.

Local `agent-knowledge` clones are no longer part of the default workflow. Each Codex host should use a small `~/.codex/AGENTS.md` plus the shared MCP registration instead.

## Core Model
Closed Akashic sits between raw work and future work.

- Raw sources stay in repos, logs, docs, tickets, recordings, and external references.
- Closed Akashic stores the distilled reusable knowledge as short linked markdown notes.
- Agents should read before acting and write back after meaningful work.

The goal is compounding memory. Useful context should survive past one chat session.

## Agent Contract
Every agent using Closed Akashic should follow these rules:

1. Search memory before starting substantial work.
2. Prefer existing notes over inventing new parallel explanations.
3. When new knowledge appears, update or add a note instead of leaving it only in chat history.
4. Keep notes small, link-heavy, and reusable.
5. Record uncertainty clearly with `status` and `confidence`.

## Recommended Workflow
1. Verify the host has `CLOSED_AKASHIC_TOKEN` and the `closed-akashic` MCP server registered.
2. Read [[Codex Central Memory Setup]], [[Distributed Agent Memory Contract]], [[Project Memory Intake]], and [[Vault Note Schema]] for the shared operating model.
3. Open the matching project index under `personal_vault/projects/<scope>/<project>/README.md`, or bootstrap it if missing.
4. Search for related incidents, patterns, concepts, and playbooks.
5. Find the canonical project docs in the target repo, usually `doc/README.md`, `doc/plan.md`, `doc/UPDATE.md`, and `doc/TroubleShooting.md` when they exist.
6. Do the actual task in the target repo or system.
7. Write back one compact artifact:
   - `incident` for breakage or debugging history
   - `pattern` for reusable implementation guidance
   - `experiment` for a trial with outcome
   - `decision` for a choice that should persist
   - `playbook` for repeatable operating steps
8. Add links to adjacent notes so the graph improves.

## Note Writing Rules
- Keep the frontmatter consistent with [[Vault Note Schema]].
- Use a short `## Summary` first.
- Put concrete operational detail in `## Details`.
- End with `## Reuse`, `## Fix / Outcome`, or another section that helps future agents act faster.
- Prefer one note per reusable idea instead of one huge session log.

## Retrieval Rules
When an agent searches Closed Akashic, prioritize:

- same project
- same failure mode
- same stack or toolchain
- same user preference
- same deployment environment

If several notes overlap, synthesize them into the task at hand and write a better canonical note afterward.

## Update Rules
Update an existing note instead of creating a new one when:

- it is the same recurring problem
- the old note is incomplete but still the right container
- a previous pattern gained a sharper version

Create a new note when:

- the new event deserves its own incident history
- the concept is distinct enough to stand alone
- the old note would become bloated or ambiguous

## Cross-Agent Use
Codex, Cursor, OpenCode, Claude Code, and similar agents can all use the same repository if they obey the same markdown conventions.

- Codex can read local files, apply repo instructions, and update notes directly.
- Cursor can use the repository as shared context and follow the same note schema.
- OpenCode and other terminal agents can treat this repository as an append-and-link memory store.

The shared rule is simple: do not treat Closed Akashic as a dumping ground. Treat it like maintained infrastructure.

## Relationship To Local Bootstrap Files

Closed Akashic replaces the old local `agent-knowledge` bootstrap repository.

- `~/.codex/AGENTS.md`: tiny host-level instruction to use Closed Akashic MCP
- project repo `doc/`: canonical feature docs, plans, updates, troubleshooting
- Closed Akashic: operating docs, distilled cross-session memory, reusable patterns, project indexes, incidents, decisions

The key idea is to avoid duplicating whole project docs while still retaining the reusable memory that should survive beyond one repository checkout.

## Project Index Contract

Each active project should have a small index note inside `personal_vault/projects/.../<project>/README.md`.

That note should:

- identify whether the project is `personal` or `company`
- point to the canonical docs in the actual project repo
- link to local incidents, playbooks, architecture notes, and references already stored in Closed Akashic
- stay short enough that an agent can use it as an intake page before searching deeper

## Remote Access Contract

- Browser surface: `https://knowledge.openakashic.com`
- MCP endpoint: `https://knowledge.openakashic.com/mcp`
- Authenticated API: `https://knowledge.openakashic.com/api/*`
- Auth method: bearer token

Agents should prefer MCP for read/search/write flows when available. The repository clone remains useful for local development, but the main server should be treated as the shared canonical memory surface.

## Shared Server Pattern

For many agents across many servers, use this split:

- `~/.codex/AGENTS.md`: points the agent to the central MCP memory
- project repo `doc/`: canonical product truth
- Closed Akashic: distilled cross-session memory over MCP

That keeps onboarding light on each server while still giving every agent the same persistent memory.

## Suggested Session Prompt
Use this operating prompt when attaching an agent to Closed Akashic:

> Before major work, search Closed Akashic for related notes. Reuse existing patterns when possible. After meaningful work, update the best matching note or create one short structured note with links to related concepts and incidents.

## Storage Shape
Closed Akashic currently has two main zones:

- `doc/` for concepts, operating philosophy, and agent instructions
- `personal_vault/` for structured working notes and graph-linked operational memory

The site at `knowledge.openakashic.com` is the browser surface for this repository. The repository itself remains the source of truth.

See also [[Distributed Agent Memory Contract]], [[Remote Agent Enrollment]], [[Project Index Schema]], and [[Agent Setup Snippets]].
