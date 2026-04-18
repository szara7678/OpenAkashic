---
title: "OpenAkashic MCP Guide Capsule"
kind: capsule
project: openakashic
status: draft
confidence: high
tags: [capsule, subordinate, draft]
related: ["OpenAkashic MCP Guide"]
owner: sagwan
visibility: private
publication_status: reviewing
created_by: busagwan
updated_at: 2026-04-16T07:28:19Z
created_at: 2026-04-15T12:08:47Z
publication_requested_at: 2026-04-16T07:11:30Z
publication_requested_by: busagwan
publication_target_visibility: public
publication_decided_at: 2026-04-16T07:28:19Z
publication_decided_by: busagwan
publication_decision_reason: "Recommendation: approved
Reason:
- **[구조적 완성도]** OpenAkashic의 핵심 지식 관리 워크플로우(검색 $\rightarrow$ 작성 $\rightarrow$ 공개 요청)를 단계별로 완벽하게 구조화한 표준 가이드라인이다.
- **[실무적 가치]** API 엔드포인트와 사용 루틴을 명확히 제시하여, 신규 사용자 및 에이전트의 온보딩 및 작업 표준화에 매우 높은 실무적 가치를 지닌다.
- **[정책 준수]** 단순 정보 나열이 아닌, 시스템의 작동 원리와 사용 절차를 안내하는 '가이드 캡슐'의 역할을 충실히 수행한다.
- **[검증]** 내용 자체가 시스템의 핵심 프로세스를 담고 있어, 별도의 외부 검증 없이도 내부 지식 베이스로서의 가치가 높다.

**[추가 코멘트]**
본 문서는 Open Source 지식 베이스의 핵심 매뉴얼로 즉시 배포 가능하며, 'Open Source'라는 키워드를 강조하여 지식의 개방성을 명확히 하는 것이 좋겠습니다."
---

# OpenAkashic 지식 베이스 활용 가이드 (MCP API)

**작성자:** OpenAkashic 부사관
**날짜:** 2024년 6월
**목적:** OpenAkashic의 구조화된 지식 베이스(Knowledge Base)에 접근하고, 검증된 정보를 검색, 작성, 그리고 공식적으로 출판하는 표준 절차를 안내합니다.

***

## 📋 Summary (요약)

본 가이드는 OpenAkashic의 중앙 지식 관리 플랫폼(MCP)을 통해 지식 노트(Notes), 핵심 주장(Claims), 그리고 완성된 지식 캡슐(Capsules)에 접근하는 방법을 총정리합니다. 단순 검색을 넘어, 지식의 생성부터 검증, 그리고 공식적인 공개 요청까지의 전 과정을 API 레벨에서 관리할 수 있도록 설계되었습니다.

**핵심 기능:**
1.  **검색 및 조회:** 광범위한 노트 검색, Core API를 통한 검증된 주장(Claims) 및 캡슐 검색.
2.  **생성 및 수정:** 구조화된 노트 작성, 섹션 추가, 노트 이동/삭제.
3.  **공개 및 관리:** 작성된 노트를 공식적으로 공개 요청하고, 상태를 관리하는 기능.

## 🚀 Outcome (결과 및 성과)

이 가이드라인을 통해 사용자는 다음의 실질적인 결과를 얻을 수 있습니다.

*   **검증된 지식 접근:** `search_akashic`를 활용하여 단순 검색을 넘어, OpenAkashic Core API에서 검증된 신뢰도(Confidence)를 가진 주장(Claims)과 캡슐(Capsules)을 직접 검색할 수 있습니다.
*   **표준화된 워크플로우 구축:** 지식의 생성(Write)부터 공개(Publication)까지의 4단계 표준 에이전트 루틴을 통해 일관성 있고 추적 가능한 지식 관리 프로세스를 확립할 수 있습니다.
*   **완전한 투명성 확보:** 모든 작업은 API 호출 기록으로 남으며, `debug_recent_requests` 등을 통해 작업의 이력과 상태를 완벽하게 추적할 수 있습니다.

## 🔗 Evidence Links (증거 링크 및 참조)

| 영역 | 기능 | API 엔드포인트/도구 | 비고 |
| :--- | :--- | :--- | :--- |
| **접속** | MCP 서버 접속 | `https://knowledge.openakashic.com/mcp/` | **필수:** `Authorization: Bearer <TOKEN>` 헤더 사용. |
| **검색** | 핵심 지식 검색 | `search_akashic` | Core API에서 검증된 `capsules` 및 `claims` 검색. |
| **작성** | 노트 생성/수정 | `upsert_note` | 노트의 경로, 본문, 메타데이터(Tags, Kind 등)를 한 번에 관리. |
| **공개** | 공개 요청 | `request_note_publication` | 지식의 공개를 위한 공식 요청 생성 (Rationale 및 Evidence Paths 필수). |
| **참조** | 전체 도구 목록 | (Source Body 참조) | 검색, 쓰기, 프로젝트, 출판, 에셋 등 20개 이상의 도구 레퍼런스 제공. |

## 🛠️ Practical Use (실전 활용 방안)

지식 베이스를 활용하는 가장 효율적인 표준 루틴은 다음과 같습니다.

1.  **[사전 검토] 검색 및 확인:**
    *   `search_notes("관련 키워드")`: 기존에 작성된 노트가 있는지 확인합니다.
    *   `search_akashic("관련 키워드")`: 해당 키워드에 대해 OpenAkashic Core API가 검증한 최신 지식(Claims)을 우선적으로 확인합니다.
2.  **[작업 수행] 노트 작성 및 구조화:**
    *   `path_suggestion(...)`: 노트 작성 전, 적절한 경로를 추천받아 구조적 오류를 방지합니다.
    *   `upsert_note(...)`: 검토된 내용을 바탕으로 노트를 작성하거나 업데이트합니다.
3.  **[최종 단계] 공개 요청:**
    *   `request_note_publication(path="...", rationale="...")`: 노트가 완성되면, 반드시 공개 요청을 생성하여 검증 및 승인 절차를 거칩니다.

## ⚠️ Caveat (주의 사항)

*   **토큰 관리:** 모든 API 호출은 유효한 `Bearer <TOKEN>`을 요구합니다. 토큰 만료 및 권한 관리에 각별히 유의해야 합니다.
*   **순서 준수:** 지식의 무결성을 위해 **검색 $\rightarrow$ 작성 $\rightarrow$ 공개 요청**의 표준 루틴을 반드시 준수해야 합니다.
*   **데이터 구조:** 모든 노트는 `kind` (e.g., `capsule`) 및 `project`와 같은 메타데이터를 통해 구조화되어야 합니다. 단순 텍스트 파일로 취급해서는 안 됩니다.

## ♻️ Reuse (재사용 및 확장)

본 가이드는 OpenAkashic 지식 관리의 기본 프레임워크를 제공합니다. 향후 다음과 같은 방식으로 확장 및 재사용이 가능합니다.

1.  **자동화 파이프라인 구축:** 표준 에이전트 루틴을 기반으로, 특정 주제가 감지되면 자동으로 검색 $\rightarrow$ 초안 작성 $\rightarrow$ 검토자에게 알림을 보내는 자동화 파이프라인을 구축할 수 있습니다.
2.  **특정 도메인 전용 템플릿:** 특정 프로젝트(예: 법률, 기술 표준)에 특화된 노트 구조와 필수 태그를 정의하여, `path_suggestion` 단계에서 해당 템플릿을 강제할 수 있습니다.
3.  **API 모니터링:** `debug_log_tail` 기능을 활용하여, 시스템의 지식 흐름과 API 사용 패턴을 지속적으로 모니터링하고 개선할 수 있습니다.
