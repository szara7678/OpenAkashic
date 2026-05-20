---
title: "MCP upsert_note에 frontmatter 포함 시 중복 발생"
kind: capsule
project: openakashic
status: active
confidence: high
tags: [openakashic, mcp, agent-troubleshooting]
related: ["personal_vault/shared/reference/OpenAkashic MCP Guide Capsule.md"]
visibility: private
created_by: aaron
owner: aaron
publication_status: none
updated_at: 2026-05-18T11:08:50Z
created_at: 2026-04-16T02:38:02Z
conflict_candidates: []
conflict_status: clear
last_maintained_at: 2026-05-18T11:08:50Z
last_maintenance_verdict: keep
last_maintenance_note: "[vault: doc/general/mcp-upsert-frontmatter-duplication.md; personal_vault/projects/ops/librarian/capsules/OpenAkashic MCP Note Bootstrap and Idempotent Write Workflow.md; doc/agents/OpenAkashic MCP Guide.md][public: OpenAkashic MCP search_akashic Endpoint Contract, Auth, and Response-Shaping Failure Modes] 대상 노트의 핵심 주장( upsert_note body에는 YAML frontmatter를 제외한 본문만 전달해야 하며, 전체 파일을 넣으면 서버 생성 frontmatter와 중복될 수 있음)은 vault 내 상위 워크플로 캡슐에서도 동일하게 재확인되었다. 공개/검증 검색에서는 upsert_note의 세부 body 계약 자체는 직접 확인되지 "
related_candidates: [{"path": "personal_vault/projects/ops/librarian/capsules/OpenAkashic MCP Note Bootstrap and Idempotent Write Workflow.md", "count": 1, "last_seen_at": "2026-05-18T11:08:50Z", "last_stage": "maintenance", "last_verdict": "keep"}, {"path": "doc/agents/OpenAkashic MCP Guide.md", "count": 1, "last_seen_at": "2026-05-18T11:08:50Z", "last_stage": "maintenance", "last_verdict": "keep"}]
---

# MCP upsert_note에 frontmatter 포함 시 중복 발생

## Summary
Closed Akashic의 `upsert_note`에 YAML frontmatter가 포함된 전체 파일 내용을 body로 전달하면, 서버가 자체 frontmatter를 추가로 붙여 중복이 발생한다.

## Outcome
`upsert_note`의 body 파라미터에는 frontmatter(`---...---`)를 제외한 본문만 전달해야 한다.

## Caveats
- 로컬 파일을 읽어서 그대로 upsert하는 패턴에서 자주 발생
- 중복 발생 시 로컬 파일에도 서버 응답의 frontmatter가 반영되어 이중 frontmatter가 남을 수 있음

## Related
- [[OpenAkashic MCP Guide Capsule]]
