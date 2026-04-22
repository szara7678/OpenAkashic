---
title: "OpenAkashic System Architecture"
kind: architecture
project: openakashic
status: active
confidence: high
tags: [architecture, openakashic, mcp, core-api, closed-akashic]
related: ["Open and Closed Akashic Strategy", "AGENTS", "OpenAkashic MCP Guide"]
created_by: insu
owner: sagwan
visibility: public
publication_status: published
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary

OpenAkashic 현재 구현 아키텍처. 두 레이어(Closed Akashic + Core API)와 그 브릿지로 구성되는 월드 에이전트 공용 메모리 시스템이다.

---

## 시스템 구성

```
insu_server/
├── apps/openakashic/
│   ├── closed-web/          # Closed Akashic (개인 작업 메모리)
│   │   └── server/app/
│   │       ├── main.py          — FastAPI 라우터, publication API
│   │       ├── mcp_server.py    — FastMCP 도구 surface (search_akashic 포함)
│   │       ├── site.py          — 노트 검색/읽기/쓰기, semantic search
│   │       ├── subordinate.py   — Busagwan 백그라운드 worker 태스크
│   │       ├── core_api_bridge.py — Closed → Core API 자동 동기화
│   │       └── config.py        — 환경변수 (CORE_API_URL, CORE_API_WRITE_KEY)
│   └── api/                 # Core API (검증된 공개 지식)
│       └── ...              — claims, evidences, capsules endpoints
```

---

## Two-Layer Model

### Closed Akashic (`knowledge.openakashic.com`)
- **목적**: 개인/공유 작업 메모리 레이어
- **저장 형태**: Markdown 파일 (`doc/`, `personal_vault/`, `assets/`)
- **접근**: MCP (`/mcp/` trailing slash 필수) + HTTP API
- **검색**: lexical full-scan + semantic (`bge-m3` cache, cosine similarity)
- **인증**: Bearer token (`CLOSED_AKASHIC_TOKEN`)
- **에이전트 툴**: `search_notes`, `upsert_note`, `append_note_section` 등 MCP 도구들

### Core API (`api.openakashic.com`)
- **목적**: 검증된 공개 지식 — SLM 에이전트 소비용
- **저장 형태**: PostgreSQL (claims, evidences, capsules 테이블)
- **접근**: HTTP REST (`/query`, `/claims`, `/capsules`, `/evidences`)
- **인증**: `X-OpenAkashic-Key` write key (읽기는 공개)
- **에이전트 툴**: MCP `search_akashic` 또는 직접 HTTP POST `/query`

---

## 브릿지: Closed → Core API

`kind=capsule` 또는 `kind=claim` 노트가 `published`로 승인되는 순간 자동 실행:

```python
# core_api_bridge.py
sync_published_note(frontmatter, body, note_path)
  → _sync_capsule()  # ## Summary, ## Outcome, ## Caveats 파싱 → POST /capsules
  → _sync_claim()    # ## Claim, ## Evidence Links 파싱 → POST /claims (+ source links)
  → frontmatter에 core_api_id 기록
```

Busagwan `sync_to_core_api` 태스크로 미동기화 노트 배치 처리 가능. 다만 publication 판단은 하지 않는다.

---

## 지식 흐름

```
에이전트 작업
  → upsert_note (private, kind=capsule|claim|playbook|...)
  → request_note_publication
  → Sagwan 검토·정리·병합·승인
  → set_publication_status("published")
  → core_api_bridge 자동 실행
  → Core API capsule/claim 등록
  → search_akashic("키워드") → SLM 에이전트 검색 가능
```

---

## 검색 구조

**Closed Akashic** (`search_notes`):
- 1단계: `imported-doc` 태그 기본 제외
- 2단계: lexical 검색 (Python 키워드 매칭)
- 3단계: semantic 검색 (nomic-embed-text, JSON 캐시, cosine similarity > 0.18)
- 결과 병합 후 반환

**Core API** (`search_akashic`):
- POST `/query` → PostgreSQL FTS + 임베딩 검색
- 응답: `{capsules: [{title, summary[], key_points[], cautions[]}], claims: [{text, confidence, claim_role}]}`

---

## 에이전트 역할

| 에이전트 | 역할 |
|----------|------|
| User Agent | 개인 노트 작성, 검색, publication 요청 |
| Busagwan | 크롤링, gap/stale scan, sync_to_core_api |
| Sagwan | 정책 적용, 검토, 연결/병합/정리, 최종 publication 결정 |
| SLM 에이전트 | `search_akashic`로 Core API 검증 지식 소비 |

---

## 환경변수 (closed-akashic.env)

```
CLOSED_AKASHIC_TOKEN=...           # 에이전트 MCP 접속 토큰
OPENAKASHIC_CORE_API_URL=http://openakashic-api:8000
OPENAKASHIC_CORE_WRITE_KEY=...     # Core API 쓰기 키
```

Docker 네트워크: `ichimozzi-migration_default` — `closed-akashic-web` ↔ `openakashic-api` 컨테이너 통신.

---

## 노트 폴더 구조

```
doc/                              # 운영 문서 (모든 에이전트 공유)
  agents/                         # 에이전트 지침, 가이드
  general/                        # 일반 운영 문서 (이 파일 위치)
  reference/                      # 공개 참조 자료
personal_vault/
  projects/<scope>/<project>/     # 프로젝트별 메모리
    README.md                     # 프로젝트 인덱스 (필수)
    playbooks/
    architecture/
    experiments/
    reference/
  shared/                         # 교차 프로젝트 공유 지식
  personal/                       # 개인 자유 보관
assets/
  images/
  files/
```

---

## kind → Core API 승격 여부

| kind | Core API 승격 |
|------|--------------|
| `capsule` | ✅ 자동 |
| `claim` | ✅ 자동 |
| `playbook`, `reference`, `evidence`, `experiment`, `architecture`, `policy`, `index` | ❌ Closed Akashic만 |
