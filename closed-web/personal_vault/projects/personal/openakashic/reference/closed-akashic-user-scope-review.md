---
title: Closed Akashic User Scope Review
kind: reference
project: personal/openakashic
status: active
confidence: high
tags: [closed-akashic, review, scope, sharing, llm]
related: [Open and Closed Akashic Strategy, LLM Maintained Wiki, OpenAkashic Project]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T05:30:00Z
---

## Summary
Closed Akashic should split internal memory into at least two scopes: per-user private memory and shared-but-private team memory. Shared memory should not be written directly by arbitrary clients; a server-side LLM or controlled promotion pipeline should decide what enters shared space.

## Findings
- The current product intent already separates Open and Closed instead of merging them.
- Closed Akashic already distinguishes `shared` and `personal` folders, but this is a content convention, not a user-aware access model.
- Closed Akashic currently uses one bearer token and one vault root, so it is effectively a single trust domain.
- Open Akashic already fits a server-side promotion model because writes are controlled and accepted claims require evidence.
- An LLM-maintained wiki loop fits Closed Akashic well if it is bounded by queue, scope, and review rules.

## Recommendation
1. Keep Open and Closed separate.
2. Inside Closed, treat `scope` as a folder/context hint, not as an access-control field.
3. Use `owner`, `visibility`, and `publication_status` as the explicit governance fields.
4. Keep user drafts, opinions, and raw reflections private by default.
5. Run a periodic librarian job that only updates targeted note sets, records provenance, and never rewrites beyond a configured budget.

## Clarification
If the product goal is one MCP endpoint, prefer one control plane over one undifferentiated store. A single authenticated MCP can expose both note-style private memory and public claim/evidence memory, while the backend still keeps separate schemas, visibility policies, and promotion rules.

## Product Direction
The stronger product shape is not "everyone reads the raw knowledge base" but "vetted source corpus in, publishable know-how out".

- Store validated source materials such as wiki-style evidence notes, experiments, reproductions, theories, papers, datasets, images, and files behind access control.
- Let agents and server-side jobs use that source layer to derive public claims, evidence summaries, capsules, and practical know-how.
- Let general users mainly receive the publishable result layer, not the full raw source layer.
- Keep provenance from public outputs back to internal source objects, while exposing only what the policy allows.

## Librarian Agent
Non-public data can remain user-editable like the current Closed Akashic flow, while publication-related handling is owned by a server-side librarian agent.

- Users and local agents should freely manage private drafts, notes, source files, and internal working memory.
- The librarian agent should own publication review, promotion to shared/public layers, backlinking, deduplication, and bounded restructuring.
- The librarian agent can store its operating prompt, persona, allowed skills, tool access policy, and reusable playbooks inside the same system as explicit governed documents.
- Prefer storing the librarian's durable configuration and policy memory, not every transient chain-of-thought or chat trace.
- Separate `agent profile`, `agent policy`, `agent playbooks`, `agent memory`, and `agent activity log` so long-term behavior stays auditable.
- Let the librarian read broad source material, but only write into shared/public zones through policy-constrained workflows.

## Ownership And Publication Metadata
Every document should carry explicit governance metadata.

- `owner`: the accountable nickname or agent identity. Current bootstrap identities are `aaron` for the master-token admin and `saguan` for the librarian manager.
- `visibility`: defaults to `private`; valid values are only `private` and `public`.
- `publication_status`: defaults to `none`; publication flow uses `requested`, `reviewing`, `approved`, `rejected`, and `published`.
- `scope`: optional folder/context helper such as `shared` for common knowledge/opinion and `personal` for personal information/opinion; it should not duplicate the permission model.
- MCP/API note writes are private personal storage by default, not public publishing.
- Public exposure starts only through a publication request owned by the server-side librarian workflow.
- Normal users may only edit their own notes and set publication status to `none` or `requested`; admins/managers decide `reviewing`, `approved`, `rejected`, and `published`.

## MCP Flow
The unified MCP should expose one control plane while keeping storage policy explicit.

- `upsert_note`: saves private/personal notes by default.
- `request_note_publication`: creates a librarian review request and marks the source note as requested.
- `list_note_publication_requests`: lets the librarian or admin review pending publication requests.
- `set_note_publication_status`: lets the librarian or admin record decisions; `published` also makes the source `visibility=public`.
- Public-facing tools should read only `public` derived artifacts unless an authenticated policy grants broader source access.

## Reuse
Prefer a three-step flow: private capture, librarian review, public promotion to Open Akashic.
