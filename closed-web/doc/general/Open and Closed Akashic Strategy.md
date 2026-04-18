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

## Current Implementation Status (2026-04-18)

브릿지 레이어가 구현되었고, 2026-04-18 에 역할이 재정의되었다.

- **`core_api_bridge.py`**: `set_publication_status("published")` 호출 시 `kind=capsule` → Core API `/capsules`, `kind=claim` → Core API `/claims` + `/evidences` 자동 동기화.
- **`core_api_id`**: 동기화 후 note frontmatter에 `core_api_id` 자동 기록.
- **`search_akashic` MCP 도구**: 에이전트가 MCP를 통해 Core API 검증 지식을 직접 검색 가능.
- **`sync_to_core_api` 태스크**: 사관 큐레이션 사이클에서 미동기화 published notes 감지 후 워커(부사관) 큐에 enqueue → 부사관이 순수 HTTP 실행.

### 역할 재정의 (2026-04-18)

| 역할 | 책임 | LLM |
|---|---|---|
| **사관 (Sagwan)** | 단독 판정자. publication 승인/거절, capsule 생성, 재검증, 피드 수급, 충돌 판정, 큐레이션 계획 | ✅ claude-haiku-4-5 |
| **부사관 (Busagwan)** | 워커(큐 실행기). 판단 없음. crawl_url, sync_to_core_api, analyze_search_gaps, scan_stale_private_notes | ❌ 없음 |

과거의 "부사관 1차 리뷰 → 사관 2차 승인" 두 단계 검토는 폐지되었다. 작은 LLM 이 생성·판정하고 큰 LLM 이 재확인하는 것은 redundant 였고, 품질도 거꾸로였다.

흐름:
```
Closed Akashic (kind=capsule/claim)
  → request_note_publication
  → Sagwan 단독 판정 (rule-based pre-filter + claude-cli LLM)
  → set_publication_status("published")
  → core_api_bridge 자동 실행
  → Core API /capsules or /claims 등록
  → 사관 curation 이 sync_to_core_api 워커 태스크 enqueue (미동기화 감지 시)
  → search_akashic("키워드") 로 SLM 검색 가능
```

### Deprecated

- **Entity 파이프라인** (`/entities`, `claim_mentions.entity_id`): 테이블/엔드포인트는 남아있으나 추출기·소비처 없음. 1082 노트 규모에서 정규화 이득 < 유지 비용. 재활성화는 vault ≥ 10k 노트 또는 alias 충돌 다발 시점까지 보류.
- **Claim 자동 생성** (`draft_claim`): 수동 `upsert_note(kind=claim)` 만 허용. 자동화는 capsule 과 중복되어 가치 낮음.

## Reuse
Keep Open and Closed Akashic separate as products and data models, but make them interoperable through explicit promotion, backlinking, and visibility-aware tooling. The bridge is now operational.
