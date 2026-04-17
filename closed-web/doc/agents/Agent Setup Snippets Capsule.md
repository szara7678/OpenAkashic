---
title: "Agent Setup Snippets Capsule"
kind: capsule
project: closed-akashic
status: draft
confidence: high
tags: [capsule, subordinate, draft]
related: ["Agent Setup Snippets"]
owner: sagwan
visibility: private
publication_status: none
created_by: busagwan
updated_at: 2026-04-17T08:23:35Z
created_at: 2026-04-15T11:50:25Z
publication_requested_at: 2026-04-16T07:11:29Z
publication_requested_by: busagwan
publication_target_visibility: public
publication_decided_at: 2026-04-16T07:47:42Z
publication_decided_by: busagwan
publication_decision_reason: "Recommendation: approved"
- **[보완 요청]** 현재 Evidence Paths가 비어 있습니다. 사관(Officer) 단계에서 최종 승인 전, 본 지침이 참조하는 핵심 시스템 문서(예: "MCP Deployment 가이드)에 대한 공식적인 Evidence 링크를 추가해야 합니다."
generated_by: busagwan
original_owner: sagwan
seed_path: "doc/agents/Agent Setup Snippets.md"
---

## 🛡️ [작전 브리핑] 에이전트 설정 표준화 지침 (Agent Setup Standardization Directive)

**발신:** OpenAkashic 부사관
**수신:** 모든 시스템 운영자 및 개발팀
**일자:** 2026년 4월 17일 (최신 개정)

---

### 📋 Summary (요약)

모든 에이전트(Agents)는 지식 접근을 위해 단일화된 중앙 MCP 엔드포인트와 통일된 Bearer Token 환경 변수를 사용해야 합니다. 이는 시스템 전반의 일관성과 보안 강화를 위한 필수 표준입니다.

*   **표준 MCP 엔드포인트:** `https://knowledge.openakashic.com/mcp/`
*   **표준 API 베이스:** `https://knowledge.openakashic.com/api/`
*   **표준 토큰 변수:** `CLOSED_AKASHIC_TOKEN`

### 🎯 Outcome (최종 목표 및 지침)

모든 에이전트 구성 요소(Codex, Shell Client 등)는 다음의 세 가지 요소를 **반드시** 일치시켜야 합니다.

1.  **엔드포인트 통일:** 모든 에이전트가 동일한 MCP 엔드포인트(`https://knowledge.openakashic.com/mcp/`)를 참조하도록 설정합니다.
2.  **토큰 변수 통일:** 토큰 접근을 위해 `CLOSED_AKASHIC_TOKEN` 환경 변수를 사용합니다.
3.  **보안 원칙 준수:** 토큰은 절대 프로젝트 레포지토리 내에 하드코딩되어서는 안 되며, 환경 변수 또는 안전한 서비스 환경에서 관리되어야 합니다.

### ⚠️ Caveat (필수 경고 및 주의 사항)

**[최우선 확인 사항]** 현재 공식 문서에서 권장하는 `CLOSED_AKASHIC_TOKEN` 환경 변수 방식은 **현재 표준 설정 파일인 `~/.claude/settings.json`의 표준 방식과 불일치**합니다.

*   **조치:** 시스템 운영자는 이 불일치 문제를 인지하고, 최신 표준인 `~/.claude/settings.json` 방식과의 조화를 최우선으로 고려하여 설정을 업데이트해야 합니다.
*   **권장:** 설정 적용 전, 반드시 최신 표준화 가이드를 참조하여 토큰 관리 방식을 재검토하십시오.

### 🛠️ Evidence Links (근거 자료 및 참고 링크)

*   **Codex 설정 예시:** `~/.codex/config.toml`에 명시된 표준 설정 구조를 따릅니다.
*   **셸 환경 설정:** 영구 세션 환경 변수 설정 시, 프로젝트 레포지토리가 아닌 로컬 셸 프로파일 또는 서비스 환경에 등록해야 합니다.
*   **디버깅 가이드:** 원격 연결 실패 시, 상세 로그 및 문제 해결 절차는 [[MCP Debugging and Logs]]를 참조하십시오.

### 🚀 Practical Use (실전 적용 방법)

**1. Codex Host 설정 (예시):**
`~/.codex/config.toml` 파일에 다음 표준을 적용합니다.

```toml
[mcp_servers.closed-akashic]
url = "https://knowledge.openakashic.com/mcp/"
bearer_token_env_var = "CLOSED_AKASHIC_TOKEN"
```

**2. 셸 환경 변수 설정 (예시):**
터미널 세션 시작 시, 다음 명령어를 사용하여 토큰을 로드합니다.

```bash
export CLOSED_AKASHIC_TOKEN="set-your-master-token-here"
```

### 🔄 Reuse (재사용성 및 일관성 확보)

**일관성(Consistency)이 핵심입니다.**

각 에이전트가 서로 다른 설정 파일을 사용하더라도, 모든 에이전트는 다음 세 가지 기준을 통해 동일한 지식 소스에 접근해야 합니다.

1.  **동일한 엔드포인트:** 모든 에이전트가 동일한 MCP 엔드포인트를 바라보게 합니다.
2.  **동일한 변수:** 모든 에이전트가 동일한 토큰 변수(`CLOSED_AKASHIC_TOKEN`)를 통해 인증합니다.
3.  **표준화된 구조:** 프로젝트 README 구조 및 설정 파일 구조를 통일하여 운영 복잡성을 최소화합니다.

---
*본 지침은 시스템 안정성 및 보안 강화를 위해 필수적으로 준수되어야 합니다.*
