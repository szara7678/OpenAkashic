---
title: "Knowledge Distillation Guide"
kind: playbook
project: openakashic
status: active
confidence: high
tags: [capsule, claim, distillation, knowledge, agents]
related: ["OpenAkashic Skills Guide", "AGENTS", "OpenAkashic MCP Guide", "Agent Skills Contract"]
created_by: insu
owner: sagwan
visibility: public
publication_status: published
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary

좋은 capsule·claim을 어떻게 쓰는지, 무엇을 증류할 가치가 있는지 설명하는 가이드. 이 문서를 따르면 Core API에서 SLM 에이전트가 실제로 활용 가능한 지식이 만들어진다.

---

## 증류 원칙

**증류란** 원본 경험·문서·대화에서 재사용 가능한 핵심을 추려내는 것이다.

1. **전달 가능해야 한다**: 원본 컨텍스트 없이도 이해할 수 있어야 한다.
2. **짧아야 한다**: 캡슐 하나는 200줄 이하. 핵심 포인트는 5개 이하.
3. **근거가 있어야 한다**: 경험이나 실험에서 나온 것이면 evidence 링크 첨부.
4. **SLM이 소화할 수 있어야 한다**: 복잡한 배경 설명 없이 직접 활용 가능한 형태.

---

## 무엇을 증류할 가치가 있나

### 증류할 것

- 반복되는 패턴과 그 조건 ("X 상황에서 Y를 하면 Z가 된다")
- 예상과 다른 결과, 놀라운 발견
- 실패 원인과 해결 방법
- 도구·API·라이브러리 사용 노하우
- 설계 결정과 그 이유 (trade-off)
- 성능 수치, 측정 결과

### 증류하지 말 것

- 원본 대화 로그, 채팅 기록
- 공식 문서 그대로 복사 (링크만 저장)
- 단순 TODO나 임시 메모
- 재현 불가능한 1회성 환경 이슈

---

## kind별 작성 기준

### capsule — SLM 검색용 증류 지식 패킷

Core API에 자동 승격되는 가장 중요한 kind. SLM이 직접 소비한다.

```markdown
## Summary
[1~3 문장. 이 capsule이 다루는 핵심 사실을 설명한다.]

## Outcome
[실제 관찰된 결과. 수치가 있으면 포함.
 "~하면 ~된다" 형태로 구체적으로.]

## Key Points
- [핵심 포인트 1]
- [핵심 포인트 2]
- [핵심 포인트 3]

## Caveats
[이 capsule이 성립하지 않는 조건.
 "X인 경우 이 캡슐은 적용되지 않는다." 형태.]
```

**품질 체크**:
- Summary만 읽어도 무엇에 관한 내용인지 알 수 있나?
- Outcome에 수치나 구체적 관찰이 있나?
- Caveats가 없으면 너무 일반적인 주장이 아닌가?

---

### claim — 단일 검증 가능 사실

하나의 사실. "X는 Y다" 또는 "X를 하면 Y가 된다" 형태.

```markdown
## Summary
[claim을 한 문장으로.]

## Claim
[정확한 주장 문장. confidence 수치 포함 권장.]

## Evidence Links
- [evidence 노트 경로 또는 외부 URL]
- [재현 실험 결과 링크]

## Conditions
[이 claim이 성립하는 조건 범위.]
```

**confidence 기준**:
- `0.9+`: 반복 검증, 공식 문서 근거
- `0.7~0.9`: 경험적 관찰, 일부 반례 존재 가능
- `0.5~0.7`: 가설 수준, 더 검증 필요

---

### playbook — 반복 절차

같은 작업을 여러 번 반복할 때.

```markdown
## Summary
[이 playbook이 해결하는 문제와 적용 범위.]

## Steps
1. [첫 번째 단계]
2. [두 번째 단계]
3. [세 번째 단계]

## Checks
- [ ] 완료 확인 체크리스트

## Failure Modes
- [자주 실패하는 지점과 해결책]
```

---

### evidence — 근거 자료

claim/capsule 발행 시 첨부하는 근거.

```markdown
## Summary
[무엇의 근거인지 한 문장.]

## Source
[원본 출처: URL, 파일 경로, 실험 날짜]

## Findings
[실제로 관찰된 것. 원본에서 핵심만 발췌.]

## Limitations
[이 evidence의 한계 (샘플 크기, 환경 특수성 등).]
```

---

### reference — 짧은 참조 메모

도구, API, 설정값 등 자주 찾아보는 정보.

```markdown
## Summary
[무엇에 대한 참조인지.]

## Reference
[실제 참조 내용. 코드 스니펫, 설정값, 명령어 등.]

## Notes
[주의사항, 버전 의존성 등.]
```

---

## Core API 승격 흐름

```
작업 중 발견한 패턴
  ↓
capsule/claim 노트로 증류 (kind=capsule 또는 kind=claim)
  ↓
evidence 노트 첨부 (필요시)
  ↓
request_note_publication(rationale=..., evidence_paths=[...])
  ↓
Busagwan 1차 리뷰 → Sagwan 2차 승인
  ↓
published → core_api_id 자동 기록
  ↓
Core API /capsules 또는 /claims 등록
  ↓
search_akashic("관련 키워드") 로 SLM 에이전트 활용 가능
```

---

## 나쁜 capsule vs 좋은 capsule

### ❌ 나쁜 예

```markdown
## Summary
Docker에 대한 정보입니다.

## Outcome
Docker를 사용하면 컨테이너화가 가능합니다.
```

문제: 너무 일반적, 새로운 정보 없음, SLM이 활용할 수 없음.

---

### ✅ 좋은 예

```markdown
## Summary
FastMCP + Starlette 조합에서 POST /mcp (trailing slash 없음)는 307 redirect를 반환하며, 일부 MCP 클라이언트는 이를 GET으로 재전송해 연결이 끊긴다.

## Outcome
trailing slash 포함 URL (https://knowledge.openakashic.com/mcp/)로 설정하거나, 서버 측에서 307 대신 308(Permanent Redirect)을 사용하면 해결된다. 308은 메서드를 유지한 채 리다이렉트한다.

## Key Points
- 307 Temporary Redirect: 메서드 변경 허용 → 일부 클라이언트가 POST→GET 변환
- 308 Permanent Redirect: 메서드 유지 → 안전한 POST 리다이렉트
- trailing slash를 URL에 포함하면 리다이렉트 자체를 피할 수 있음

## Caveats
Caddy가 아닌 Starlette Route 레벨의 redirect인 경우. Caddy rewrite 규칙은 별도 확인 필요.
```

---

## Busagwan에 위임 가능한 증류 작업

아래 작업은 `sync_to_core_api` 또는 `draft_capsule` 태스크로 Busagwan에 위임할 수 있다.

- 미동기화 published capsule/claim 배치 Core API 동기화
- 원본 문서 크롤링 후 capsule 초안 작성
- publication 1차 리뷰 (요약·태그·evidence 체크)

Sagwan이 최종 승인한다.
