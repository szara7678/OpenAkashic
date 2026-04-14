---
title: Publication Evidence Contract
kind: playbook
project: personal/openakashic
status: active
confidence: high
tags: [publication, evidence, claim, capsule, librarian]
related: [OpenAkashic Knowledge Taxonomy, Closed Akashic User Scope Review, OpenAkashic Librarian Control Plane]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary
공동 publish는 원문 하나만 던지는 방식이 아니라, source note와 evidence note, 첨부 파일, 요청 메모를 묶은 패키지로 올린다. 이 문서는 evidence를 어떻게 저장하고, 어떻게 참조하고, 사서장이 무엇을 기준으로 검토하는지 정의한다.

## When To Use
- private 노트를 public claim이나 capsule로 승격하고 싶을 때
- 실험 결과, 파일, 이미지, 데이터셋을 근거로 공개 산출을 만들고 싶을 때
- 사서장에게 검토 가능한 최소 단위를 넘기고 싶을 때

## Steps
1. 원본 private 노트를 작성한다.
2. 근거가 되는 자료가 있으면 `evidence` kind 노트로 정리한다.
3. 이미지와 파일은 `assets/images` 또는 `assets/files`에 업로드한다.
4. evidence 노트의 `Artifacts` 섹션에 파일 링크를 넣고, `Findings`에 무엇이 확인됐는지 적는다.
5. 공개 요청은 `publication_request` kind 문서나 API `request_note_publication`으로 만든다.
6. 요청 본문에는 source note, 원하는 공개 산출 형태, 근거 링크, 공개 범위와 주의점을 적는다.
7. 사서장은 `reviewing -> approved/rejected -> published` 흐름으로 상태를 바꾼다.

## Checks
공개 요청에는 최소한 아래가 있어야 한다.

- `Source Note`: 공개를 원하는 원본 노트 경로 또는 링크
- `Requested Output`: `claim`, `capsule`, `reference` 중 어떤 산출인지
- `Evidence Links`: evidence 노트 링크 또는 asset 링크
- `Rationale`: 왜 공개 가능한지, 무엇을 공개하면 안 되는지

Evidence note는 아래 구조를 권장한다.

```md
## Summary
## Source
## Method
## Artifacts
## Findings
## Limitations
```

Publication request는 아래 구조를 권장한다.

```md
## Summary
## Source Note
## Requested Output
## Evidence Links
## Rationale
## Review Notes
```

## Claim And Capsule Rules
- `claim`은 하나의 명확한 주장 단위로 쪼갠다.
- `claim`의 `Evidence Links`는 근거 note나 asset을 직접 가리켜야 한다.
- `capsule`은 사용자가 바로 써먹을 결과물로 쓴다.
- `capsule`은 보통 여러 `claim` 또는 `evidence`를 묶어 요약한다.
- 원문 전문 공개가 아니라, 공개 가능한 사실과 결과만 밖으로 보낸다.

## Review Notes
사서장은 아래를 본다.

- private 정보가 남아 있지 않은가
- 근거가 최소 1개 이상 연결되어 있는가
- 공개 산출이 근거 범위를 넘어서 주장하지 않는가
- 결과를 다시 재현하거나 추적할 링크가 있는가

## Reuse
공개 요청은 "원본 노트 + evidence note + request note"의 세트로 생각하면 된다.
