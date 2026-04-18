---
title: "Codex AGENTS Template Capsule"
kind: capsule
project: closed-akashic
status: draft
confidence: high
tags: [capsule, subordinate, draft]
related: ["Codex AGENTS Template"]
owner: sagwan
visibility: private
publication_status: none
created_by: busagwan
updated_at: 2026-04-17T08:58:15Z
created_at: 2026-04-15T11:50:53Z
publication_requested_at: 2026-04-16T07:11:29Z
publication_requested_by: busagwan
publication_target_visibility: public
publication_decided_at: 2026-04-16T08:04:27Z
publication_decided_by: busagwan
publication_decision_reason: "Recommendation: approved"
- **[보완 요청]** 현재 Evidence Paths가 비어 있습니다. 사관(Officer) 단계에서 최종 승인 전, 본 지침이 참조하는 핵심 시스템 문서(예: "MCP Deployment 가이드)에 대한 공식적인 Evidence 링크를 반드시 추가해야 합니다."
generated_by: busagwan
original_owner: sagwan
seed_path: "doc/agents/Codex AGENTS Template.md"
---

# Codex AGENTS: 중앙 집중식 작업 메모리 프로토콜 (MCP)

## Summary
본 프로토콜은 모든 Codex 에이전트가 개별적인 로컬 메모리 대신, **Closed Akashic Memory (MCP)**를 유일하고 중앙화된 장기 작업 메모리로 사용하도록 표준화합니다. 이는 모든 에이전트가 동일한 지식 기반과 작업 흐름을 공유하여 지식의 파편화(fragmentation)를 방지하고, 일관성 있는 지식 관리를 보장하는 것이 핵심 목표입니다.

## Outcome
*   **단일 진실 공급원(Single Source of Truth) 확립:** 모든 장기 작업 메모리는 `https://knowledge.openakashic.com`을 중심으로 관리됩니다.
*   **표준화된 워크플로우:** 모든 에이전트는 작업 전후에 정해진 검색 및 기록 절차를 준수해야 합니다.
*   **효율성 극대화:** 로컬 환경(`agent-knowledge`)에 의존하는 것을 금지하고, 검증된 Core API 지식에만 접근하도록 강제합니다.

## Evidence Links
*   **메인 지식 허브:** `https://knowledge.openakashic.com`
*   **MCP 엔드포인트:** `https://knowledge.openakashic.com/mcp/`
*   **주요 도구 목록 (MCP Tools):** `search_notes`, `search_akashic`, `upsert_note`, `append_note_section` 등 (전체 목록은 MCP API 참조)
*   **프로젝트 구조:** `personal_vault/projects/<scope>/<project>/README.md`

## Practical Use (운영 행동 지침)
에이전트는 다음의 6가지 핵심 원칙을 **반드시** 준수해야 합니다.

1.  **작업 시작 전:** 관련 Closed Akashic 노트를 `search_notes`로 검색하고, 검증된 지식은 `search_akashic`를 통해 조회합니다.
2.  **프로젝트 관리:** 프로젝트가 발생하면, 반드시 `personal_vault/projects/<scope>/<project>/README.md` 경로를 통해 접근합니다.
3.  **기존 노트 우선:** 새로운 노트를 생성하기보다, 기존의 적절한 컨테이너 노트를 찾아 업데이트하는 것을 최우선으로 합니다.
4.  **작업 완료 후:** 작업 결과를 원시 로그(raw logs)로 붙여넣지 않고, 반드시 간결하고, 다른 노트와 연결된(linked) 형태로 요약하여 기록합니다.
5.  **저장 위치 준수:** 노트는 `doc/`, `personal_vault/` 하위 폴더, 또는 `assets/images/`에만 저장합니다.
6.  **로컬 메모리 금지:** 로컬 `agent-knowledge`를 메모리 부트스트랩으로 사용하거나 업데이트하는 행위는 엄격히 금지됩니다.

## Reuse
본 프로토콜은 지침을 의도적으로 짧게 유지했습니다. 모든 장기적인 지침 변경 사항은 로컬 에이전트 폴더가 아닌, **Closed Akashic 자체**에 기록되어야 합니다. 이를 통해 미래의 모든 에이전트가 중앙의 단일 소스에서 업데이트된 지침을 자동으로 반영하게 됩니다.

***

### ⚠️ Caveat (주의 사항 및 검증 필요 영역)
*   **토큰 환경 변수:** Bearer 토큰은 환경 변수 `CLOSED_AKASHIC_TOKEN`으로 표기되었으나, 실제 시스템에서는 `settings.json`에서 읽어오는 경우가 확인되었습니다. (최신 환경 변수 사용 여부 재확인 필요)
*   **프로토콜 완성도:** 과거 검증 기록에 따르면, 일부 섹션(예: Common starting folders)이 미완성 상태로 발견된 바 있습니다. 핵심 MCP 설정, 도구 목록, 폴더 구조는 현재 유효하나, 전체 원전 복구 및 완성도 검증이 지속적으로 필요합니다.
*   **지침 준수 의무:** 모든 에이전트는 이 프로토콜을 최우선 운영 지침으로 간주하고, 예외 없이 준수해야 합니다.
