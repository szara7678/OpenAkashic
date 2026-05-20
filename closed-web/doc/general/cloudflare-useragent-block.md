---
title: "Cloudflare User-Agent 미설정 시 요청 차단"
kind: capsule
project: openakashic
status: active
confidence: high
tags: [cloudflare, http, agent-troubleshooting]
related: ["personal_vault/shared/reference/OpenAkashic MCP Guide Capsule.md"]
visibility: private
created_by: aaron
owner: aaron
publication_status: none
updated_at: 2026-05-18T08:43:54Z
created_at: 2026-04-16T02:38:02Z
conflict_candidates: [{"path": "personal_vault/shared/reference/Claim Cloudflare Blocks Missing UserAgent.md", "score": 0.8052}]
conflict_status: clear
superseded_by: "personal_vault/shared/reference/Claim Cloudflare Blocks Missing UserAgent.md"
claim_review_status: merged
last_consolidated_at: 2026-05-10T02:47:53Z
last_consolidation_verdict: supersede
last_maintained_at: 2026-05-18T08:43:54Z
last_maintenance_verdict: merge
last_maintenance_note: "[vault: doc/general/cloudflare-useragent-block.md; personal_vault/projects/ops/librarian/capsules/Cloudflare User-Agent 미설정 시 요청 차단 (Superseded).md; personal_vault/shared/reference/Claim Cloudflare Blocks Missing UserAgent.md; doc/agents/OpenAkashic MCP Guide.md][public: Claim 7cf69b17-6b16-4e13-adea-fcfbef42eb14 / Claim: Cloudflare WAF rule 1010 blocks requests with no User-Agent] 대상 노트는 이미 claim_review_status=superseded이고 superseded_by가 중간 Superseded 캡슐을 거쳐 공개 Claim으로 이어진다. 원문 요지는 실제 OpenAkash"
related_candidates: [{"path": "doc/agents/OpenAkashic MCP Guide.md", "count": 1, "last_seen_at": "2026-05-18T08:43:54Z", "last_stage": "maintenance", "last_verdict": "merge"}]
---

# Cloudflare User-Agent 미설정 시 요청 차단

## Summary
Cloudflare WAF가 보호하는 엔드포인트에 HTTP 요청 시 User-Agent 헤더가 없으면 Error 1010 (browser_signature_banned)으로 차단된다.

## Outcome
요청 헤더에 `User-Agent` 값을 포함하면 해결. 값은 임의 문자열이어도 무방.

## Caveats
- Python `urllib.request`는 기본 User-Agent를 보내지만 커스텀 Request 객체 사용 시 명시 필요
- curl은 기본적으로 User-Agent를 보내지 않으므로 `-A` 플래그 필수
- 403 응답 body에 `error_code: 1010`이 포함되어 있으면 이 케이스

## Related
- [[OpenAkashic MCP Guide Capsule]]
