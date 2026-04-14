---
title: "Open and Closed Akashic Strategy"
kind: architecture
project: openakashic
status: active
confidence: high
tags: [openakashic, closed-akashic, strategy, architecture]
related: ["Agent Guide", "Closed Akashic Remote Access"]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
Open Akashic and Closed Akashic should stay as separate surfaces with a deliberate bridge between them, not as one undifferentiated store.

Open Akashic is the public memory layer for publishable claims, evidences, mentions, entities, and derived capsules. Closed Akashic is the private working memory layer for notes, decisions, incidents, playbooks, project indexes, and agent operating knowledge.

## Role Split

### Open Akashic
- public or publishable knowledge
- structured records with explicit schema
- claims and evidences that can be queried by agents or public clients
- capsules derived from accepted structured records
- good fit for facts, sources, citations, and externally visible positions

### Closed Akashic
- private notes and operating memory
- markdown-first human and agent workspace
- project indexes, incidents, decisions, experiments, playbooks
- good fit for drafts, internal reasoning, preferences, sensitive context, and evolving operational knowledge

## Why Not Merge Them Directly

1. Their security models differ.
   Open Akashic is intended to expose publishable material. Closed Akashic exists specifically to hold private working memory.

2. Their storage models differ.
   Open Akashic is record-based and schema-driven. Closed Akashic is note-based and graph-linked.

3. Their retrieval intent differs.
   Open Akashic answers factual or source-grounded public memory queries. Closed Akashic supports active work, incidents, and reusable internal patterns.

4. Their editorial standards differ.
   Closed Akashic can contain partial conclusions and operational uncertainty. Open Akashic should only receive material that has been normalized and is safe to publish.

## Recommended Bridge

Use a promotion workflow from Closed to Open, not a raw sync.

### Closed -> Open
- draft or investigate in Closed Akashic
- extract publishable claims
- attach evidence and source weight
- review and sanitize private material
- publish only accepted claims and evidences into Open Akashic

### Open -> Closed
- reference Open claim IDs or capsules inside Closed notes
- pull accepted public knowledge into project notes when it helps decisions
- keep private interpretation and planning in Closed

## Practical Product Shape

1. Keep both services running separately.
2. Add an explicit `publish_to_open` workflow or tool later.
3. Tag Closed notes with visibility intent such as `private`, `draft-public`, or `public-candidate`.
4. Store provenance so Open entries can point back to the Closed note that originated them, without exposing the private note body.
5. Treat opinions separately from facts:
   - facts and evidence go to Open
   - internal judgments, strategy, and preference stay in Closed

## What Is Feasible Now

This split is already feasible with the current codebase.

- Open Akashic already has structured endpoints for claims, evidences, entities, and capsules.
- Closed Akashic already has authenticated note APIs and MCP tools for project memory.
- The missing piece is a small bridge layer that converts a vetted Closed note or section into Open claim/evidence records.

## Recommended Next Step

Build a small promotion path instead of merging databases:

1. select a Closed note or section
2. extract candidate claims and evidence
3. review for privacy and publishability
4. write to Open Akashic
5. append backlink metadata in Closed

## Reuse
Keep Open and Closed Akashic separate as products and data models, but make them interoperable through explicit promotion, backlinking, and visibility-aware tooling.
