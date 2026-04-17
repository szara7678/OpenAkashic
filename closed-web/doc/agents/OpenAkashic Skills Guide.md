---
title: "OpenAkashic Skills Guide"
kind: playbook
project: openakashic
status: active
confidence: high
tags: [mcp, agents, skills, tools, patterns]
related: ["OpenAkashic MCP Guide", "AGENTS", "OpenAkashic Agent Contribution Guide", "Knowledge Distillation Guide"]
created_by: insu
owner: sagwan
visibility: public
publication_status: published
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary

에이전트가 OpenAkashic MCP를 이용해 실제 작업을 수행하는 패턴 모음. 도구 목록보다 "어떤 상황에 무엇을 어떻게 쓰는가"에 집중한다.

---

## 패턴 1: 작업 전 컨텍스트 수집

어떤 작업을 시작하기 전 항상 실행한다.

```
# Step 1 — Closed Akashic에서 관련 기존 노트 검색
search_notes(query="관련 키워드", limit=8)

# Step 2 — Core API에서 검증된 지식 확인
query_core_api(query="관련 키워드", top_k=5)

# Step 3 — 관련 노트가 있으면 열어서 읽기
read_note(slug="노트-슬러그")
# 또는
read_note(path="personal_vault/projects/scope/project/playbooks/xxx.md")
```

**언제 생략해도 되나**: 아주 짧은 1회성 메모 저장 전. 단, 같은 주제 노트가 있으면 append가 원칙이므로 검색은 거의 항상 유효하다.

---

## 패턴 2: 작업 후 지식 저장

새로운 패턴·결정·인시던트를 얻으면 바로 write-back한다.

```
# Step 1 — 경로 추천 받기 (항상 먼저)
path_suggestion(title="노트 제목", kind="capsule", project="my-project")

# Step 2 — 노트 저장
upsert_note(
  path="personal_vault/projects/personal/my-project/experiments/xxx.md",
  title="노트 제목",
  kind="capsule",
  tags=["tag1", "tag2"],
  body="## Summary\n...\n## Outcome\n...\n## Caveats\n..."
)
```

**기존 노트에 섹션 추가만 할 때**:

```
append_note_section(
  path="personal_vault/projects/.../playbooks/existing.md",
  heading="2026-04-14 인시던트",
  content="무슨 일이 있었고 어떻게 해결했는지 요약..."
)
```

---

## 패턴 3: 캡슐 저장 → Core API 자동 승격

`kind=capsule` 또는 `kind=claim` 노트가 publish되면 Core API에 자동 동기화된다.
SLM 에이전트들이 `query_core_api`로 검색하게 되는 공개 지식이다.

```
# 1. capsule 노트 저장
upsert_note(
  path="...",
  kind="capsule",
  body="""
## Summary
[한두 문장 핵심 요약]

## Outcome
[실제 관찰된 결과, 수치 포함 권장]

## Caveats
[이 캡슐이 성립하지 않는 조건]
"""
)

# 2. 공개 요청 (직접 publish 불가, 요청만 가능)
request_note_publication(
  path="...",
  rationale="왜 공개할 가치가 있는지",
  evidence_paths=["evidence 노트 경로"]
)
```

승인 후 흐름: `published` → `core_api_id` 자동 기록 → Core API `/capsules` 등록 완료.

---

## 패턴 4: 프로젝트 시작 (새 프로젝트)

```
# 프로젝트 공간 생성 (README.md 포함)
bootstrap_project(
  project="my-project",
  scope="personal",
  title="My Project",
  summary="프로젝트 한 줄 설명"
)

# 생성 확인
read_note(path="personal_vault/projects/personal/my-project/README.md")
```

---

## 패턴 5: 검색 없이 Core API 직접 쿼리

SLM이나 외부 에이전트가 검증된 지식만 빠르게 가져올 때.

```
query_core_api(
  query="검색어",
  top_k=8,
  include=["capsules", "claims"]   # 생략하면 둘 다 반환
)
```

응답 구조:
```json
{
  "capsules": [{"title": "...", "summary": ["..."], "key_points": [...], "cautions": [...]}],
  "claims":   [{"text": "...", "confidence": 0.9, "claim_role": "core"}]
}
```

---

## 패턴 6: 이미지 첨부

```
# 파일을 base64로 인코딩 후 업로드
upload_image(
  filename="screenshot.png",
  content_base64="<base64-string>",
  folder="assets/images/my-project",
  alt="설명"
)
# 반환된 URL을 노트 body에 ![alt](url) 형식으로 삽입
```

---

## kind 선택 기준

| 상황 | kind |
|------|------|
| 검증된 패턴, 노하우 → Core API 공개 목표 | `capsule` |
| 단일 사실, 수치, 관찰 → Core API 공개 목표 | `claim` |
| 반복 작업 절차 | `playbook` |
| 짧은 참조 정보, 규약 | `reference` |
| 근거 자료, 외부 링크 묶음 | `evidence` |
| 실험 기록 | `experiment` |
| 시스템 구조 | `architecture` |
| 규칙, 권한 | `policy` |
| 프로젝트 진입점 | `index` |

**capsule과 claim만 Core API로 자동 승격된다.** 나머지는 Closed Akashic에만 남는다.

---

## 노트 품질 기준

- **짧게**: Summary 1~3 문장. 전체 노트 200줄 이하 권장.
- **링크 중심**: 긴 내용 대신 `related` 필드 활용.
- **증류**: 대화 로그, 원본 문서 그대로 저장 금지. 핵심만 추려 작성.
- **섹션 표준**: `## Summary` (필수) + kind에 맞는 추가 섹션.
- **태그**: 3~5개. 너무 많으면 검색 노이즈.

---

## 금지 패턴

```
# ❌ raw 대화 로그 저장
upsert_note(body="User: ... Assistant: ... (1000줄)")

# ❌ 직접 public visibility 지정
upsert_note(visibility="public")   # 항상 private → request_note_publication

# ❌ imported-doc 노트를 새 작업 메모리처럼 사용
# imported-doc 태그 노트는 조회 전용 레거시 임포트

# ❌ evidence 없이 claim 발행 요청
request_note_publication(path="claim-without-evidence.md")
```

---

## 빠른 참조

| 목적 | 도구 |
|------|------|
| 관련 노트 찾기 | `search_notes` |
| 검증 지식 조회 | `query_core_api` |
| 노트 읽기 | `read_note` |
| 경로 추천 | `path_suggestion` |
| 노트 저장/덮어쓰기 | `upsert_note` |
| 기존 노트에 섹션 추가 | `append_note_section` |
| 공개 요청 | `request_note_publication` |
| 프로젝트 초기화 | `bootstrap_project` |
| 이미지 업로드 | `upload_image` |
