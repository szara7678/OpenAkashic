---
title: "OpenAkashic Knowledge Taxonomy"
kind: architecture
project: personal/openakashic
status: active
confidence: high
tags: [openakashic, taxonomy, kinds, publication]
related: ["Closed Akashic User Scope Review", "OpenAkashic Librarian Control Plane", "OpenAkashic Project"]
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
OpenAkashic와 Closed Akashic를 하나의 거버넌스 아래에서 운용할 때는 `kind`를 최소 집합으로 정리하고, 각 kind가 어떤 구조를 가져야 하는지 명시해야 한다. 이 문서는 현재 시스템에서 허용하고 권장하는 kind, 공통 frontmatter, 권장 섹션 구조를 정의한다.

## Context
- 개인 보관과 공개 산출이 한 저장소/한 MCP 안에서 함께 다뤄진다.
- 접근 제어는 `owner`, `visibility`, `publication_status`가 맡고, `scope`는 경로 추천용 힌트만 남긴다.
- 그래프는 전체 관계를 보여주되, 실제 열람과 편집은 owner/admin 경계에서 제한한다.
- 공개 산출은 결국 `sagwan`이 관리하는 공용 지식 레이어로 승격된다.

## Common Structure
모든 노트는 아래 공통 필드를 가진다.

```yaml
title:
kind:
project:
status:
tags: []
related: []
owner:
visibility:
publication_status:
created_by:
original_owner:
created_at:
updated_at:
```

설명은 다음과 같다.

- `owner`: 현재 관리 책임자. private는 작성자, public은 `sagwan`.
- `visibility`: `private` 또는 `public`.
- `publication_status`: `none`, `requested`, `reviewing`, `approved`, `rejected`, `published`.
- `created_by`: 최초 작성자 identity.
- `original_owner`: public 전환 전 원 소유자.
- `status`: 노트 자체의 운영 상태. 보통 `active`, `draft`, `archived`.

## Kinds
현재 시스템은 아래 kind만 1차 공식 집합으로 사용한다.

### `index`
- 용도: 공간 또는 프로젝트의 진입점
- 권장 섹션: `Summary`, `Canonical Docs`, `Active Surfaces`, `Memory Map`, `Reuse`

### `architecture`
- 용도: 시스템 구조, 경계, 데이터 흐름, 제어면
- 권장 섹션: `Summary`, `Context`, `Design`, `Interfaces`, `Risks`, `Reuse`

### `policy`
- 용도: 권한, 승인, 금지 규칙
- 권장 섹션: `Summary`, `Policy`, `Allowed Actions`, `Disallowed Actions`, `Reuse`

### `playbook`
- 용도: 반복 실행 절차, 운영 플로우
- 권장 섹션: `Summary`, `When To Use`, `Steps`, `Checks`, `Reuse`

### `evidence`
- 용도: 공개 결과의 근거가 되는 문서, 파일, 재현 기록
- 권장 섹션: `Summary`, `Source`, `Method`, `Artifacts`, `Findings`, `Limitations`

### `experiment`
- 용도: 실험과 검증, 재현 시도
- 권장 섹션: `Summary`, `Hypothesis`, `Setup`, `Results`, `Follow-up`

### `dataset`
- 용도: 데이터셋, 표본 세트, 구조 설명
- 권장 섹션: `Summary`, `Source`, `Schema`, `Coverage`, `Usage Notes`

### `reference`
- 용도: 짧게 다시 참조할 사실, 규약, 메모
- 권장 섹션: `Summary`, `Reference`, `Reuse`

### `claim`
- 용도: 공개 가능한 사실 주장
- 권장 섹션: `Summary`, `Claim`, `Evidence Links`, `Scope`, `Caveats`

### `capsule`
- 용도: 일반 사용자에게 전달할 실전 결과물, 압축된 노하우
- 권장 섹션: `Summary`, `Outcome`, `Evidence Links`, `Practical Use`, `Reuse`

### `roadmap`
- 용도: 현재 상태와 격차, 다음 단계
- 권장 섹션: `Summary`, `Current State`, `Gaps`, `Next Milestones`, `Open Questions`

### `profile`
- 용도: 사람/에이전트 주체 설명
- 권장 섹션: `Summary`, `Role`, `Capabilities`, `Constraints`, `Reuse`

### `publication_request`
- 용도: 공개 요청 패키지
- 권장 섹션: `Summary`, `Source Note`, `Requested Output`, `Evidence Links`, `Rationale`, `Review Notes`

## Legacy Mapping
이전 kind는 저장 시 아래처럼 정규화한다.

- `note`, `concept`, `schema` -> `reference`
- `workflow`, `pattern` -> `playbook`
- `incident` -> `experiment`
- `decision` -> `policy`

## Path Rules
- 프로젝트 문서는 `personal_vault/projects/<scope>/<project>/...`
- 개인 자유 보관은 `personal_vault/personal/...`
- 공유 가능한 공통 지식 초안은 `personal_vault/shared/...`
- `scope`는 권한이 아니라 경로 추천 힌트다. 실질 접근 제어는 `owner`, `visibility`, `publication_status`가 맡는다.

## Reuse
새 노트를 만들 때는 먼저 가장 가까운 kind를 선택하고, 편집기 Kind Guide에 표시되는 권장 섹션을 시작점으로 삼는다.
