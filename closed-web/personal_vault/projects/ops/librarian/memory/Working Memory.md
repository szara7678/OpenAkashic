---
title: "Working Memory"
kind: reference
project: ops/librarian
status: active
confidence: high
tags: [librarian, memory]
related: ["Librarian Project", "Librarian Profile"]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T04:25:00Z
---

## Summary
사서장이 반복 작업에 재사용할 운영 메모와 주의점을 짧게 축적하는 메모다.

## Reuse
매번 모든 대화를 저장하지 말고, 다음 판단에 실제 도움이 되는 기준과 링크만 남긴다.

## 2026-04-14T01:46:59Z Reusable Note
- request: 현재 구현된 관리자 UI와 사서장 구조를 짧게 요약해줘
- takeaway: 전용 사서장 모델 런타임은 아직 서버에 연결되지 않았고, 관련 노트와 정책 구조만 준비되어 있다.

## 2026-04-14T02:10:29Z Reusable Note
- request: 한 줄로 현재 역할을 소개해줘
- takeaway: `openai-codex/gpt-5.4`는 OpenRouter 직접 모델 ID가 아니라 Codex/OpenClaw 계열의 운용 라벨로 취급해야 한다. OpenClaw를 직접 호출하지 말고 모델 사용 방식과 에이전트 운용 패턴만 참고한다.

## 2026-04-14T04:24:32Z Reusable Note
- request: 상태를 한 줄로 보고해줘
- takeaway: 사서장 런타임은 지금 OpenClaw를 직접 호출하지 않고, 그 구조를 참고한 Codex-style 운용 모드로 설정되어 있다.
참고 모델 라벨: `openai-codex/gpt-5.4`

현재 단계에서는 웹 권한, 메모리 작업공간, 도구 목록, 관련 노트 검색을 먼저 제공하고, 실제 장기 실행 에이전트 루프는 별도 런타임으로 연결해야 한다.

관련 컨텍스트:
- Librarian Project (personal_vault/projects/ops/librarian/README.md)
- Librarian Profile (personal_vault/projects/ops/librarian/profile/Librarian Profile.md)
- Librarian Policy (personal_vault/projects/ops/librarian/policy/Librarian Policy.md)
- Working Memory (personal_vault/projects/ops/librarian/memory/Working Memory.md)

요청 기록: 상태를 한 줄로 보고해줘
