---
title: "Cloudflare User-Agent 미설정 시 요청 차단"
kind: capsule
project: openakashic
status: active
confidence: high
tags: [cloudflare, http, agent-troubleshooting]
related: []
visibility: private
created_by: aaron
owner: aaron
publication_status: none
updated_at: 2026-04-19T21:19:54Z
created_at: 2026-04-16T02:38:02Z
conflict_candidates: [{"path": "personal_vault/shared/reference/Claim Cloudflare Blocks Missing UserAgent.md", "score": 0.8052}]
conflict_status: clear
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
