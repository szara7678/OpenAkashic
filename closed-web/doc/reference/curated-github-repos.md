---
title: curated-github-repos
kind: reference
project: openakashic
status: active
confidence: high
tags: []
related: []
visibility: private
created_by: aaron
owner: aaron
publication_status: rejected
updated_at: 2026-04-15T09:47:58Z
created_at: 2026-04-15T02:08:56Z
publication_requested_at: 2026-04-15T02:09:12Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:58Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
---

## Summary
개발자 필수 GitHub 레포지토리 큐레이션. 학습·도구·AI·보안·인프라 카테고리. "별 수"보다 "실제 실무 유용성"과 "2025 기준 활성 여부"를 기준으로 선별.

## Sources
- GitHub Trending (2025)
- "50 Best GitHub Repos Every Software Engineer Should Know" (Medium)
- "Top GitHub Repositories 2025" (GeeksforGeeks, LogicLense)
- 커뮤니티 추천

---

## 1. 학습·레퍼런스

| 레포 | URL | 설명 |
|---|---|---|
| **sindresorhus/awesome** | github.com/sindresorhus/awesome | 모든 Awesome List의 메타 목록. 기술별 최고 큐레이션 진입점. ★160k+ |
| **kamranahmedse/developer-roadmap** | github.com/kamranahmedse/developer-roadmap | roadmap.sh 원본. 직군별 시각화 학습 경로. ★300k+ |
| **EbookFoundation/free-programming-books** | github.com/EbookFoundation/free-programming-books | 무료 프로그래밍 서적·강의·자료 전체. ★340k+ |
| **donnemartin/system-design-primer** | github.com/donnemartin/system-design-primer | 시스템 설계 인터뷰 준비 최고 자료. 다이어그램+설명. ★280k+ |
| **jwasham/coding-interview-university** | github.com/jwasham/coding-interview-university | 알고리즘·CS 인터뷰 전체 커리큘럼. ★300k+ |
| **trekhleb/javascript-algorithms** | github.com/trekhleb/javascript-algorithms | JS로 구현한 알고리즘+자료구조. ★190k+ |
| **TheAlgorithms/Python** | github.com/TheAlgorithms/Python | Python 알고리즘 전체. ★185k+ |
| **ossu/computer-science** | github.com/ossu/computer-science | 무료 CS 학위 수준 커리큘럼. MIT/Stanford 강의 링크. |

---

## 2. AI / LLM 도구

| 레포 | URL | 설명 |
|---|---|---|
| **ollama/ollama** | github.com/ollama/ollama | 로컬 LLM 실행 가장 간단한 방법. macOS/Linux/Windows. ★100k+ |
| **ggerganov/llama.cpp** | github.com/ggerganov/llama.cpp | C++로 LLaMA 추론. CPU+GPU 혼합. 4bit 양자화. ★70k+ |
| **anthropics/claude-code** | github.com/anthropics/claude-code | Claude Code CLI 소스. Issues는 공식 피드백 채널. |
| **anthropics/anthropic-sdk-python** | github.com/anthropics/anthropic-sdk-python | Anthropic 공식 Python SDK. |
| **langchain-ai/langchain** | github.com/langchain-ai/langchain | LLM 앱 프레임워크. RAG·에이전트·체인. ★95k+ |
| **run-llama/llama_index** | github.com/run-llama/llama_index | RAG 특화. 데이터 커넥터+인덱싱. ★38k+ |
| **microsoft/autogen** | github.com/microsoft/autogen | 멀티에이전트 대화 프레임워크. ★35k+ |
| **modelcontextprotocol/servers** | github.com/modelcontextprotocol/servers | 공식 MCP 서버 예제 모음 (GitHub, Slack, Google Drive 등). |
| **luno-junyu/Awesome-Agent-Papers** | github.com/luo-junyu/Awesome-Agent-Papers | LLM 에이전트 논문 최신 목록. 지속 업데이트. |
| **openai/openai-python** | github.com/openai/openai-python | OpenAI 공식 Python SDK. |
| **huggingface/transformers** | github.com/huggingface/transformers | HF Transformers. 모델 로드·파인튜닝·추론 표준. ★135k+ |
| **vllm-project/vllm** | github.com/vllm-project/vllm | PagedAttention 기반 LLM 서빙. 높은 처리량. ★40k+ |
| **langfuse/langfuse** | github.com/langfuse/langfuse | LLM 관측·평가 오픈소스. Self-hosted 가능. |
| **brainlid/langchain** | github.com/brainlid/langchain | Elixir LangChain 구현. |

---

## 3. 개발 도구·프레임워크

| 레포 | URL | 설명 |
|---|---|---|
| **vercel/next.js** | github.com/vercel/next.js | React 풀스택 프레임워크. SSR/SSG/RSC. ★125k+ |
| **vitejs/vite** | github.com/vitejs/vite | 현대 프론트엔드 빌드 도구. HMR 최속. ★68k+ |
| **shadcn-ui/ui** | github.com/shadcn-ui/ui | Radix UI + Tailwind 컴포넌트 모음. Copy-paste 방식. |
| **trpc/trpc** | github.com/trpc/trpc | TypeScript 타입 안전 API. 클라이언트-서버 타입 공유. |
| **prisma/prisma** | github.com/prisma/prisma | TypeScript ORM. 스키마 우선 DB 접근. |
| **tiangolo/fastapi** | github.com/tiangolo/fastapi | Python 고성능 비동기 API. OpenAPI 자동 생성. ★78k+ |
| **tokio-rs/axum** | github.com/tokio-rs/axum | Rust 비동기 웹 프레임워크. Tower 기반. |
| **pocketbase/pocketbase** | github.com/pocketbase/pocketbase | Go 단일 파일 백엔드+DB+인증. 프로토타이핑 최적. |

---

## 4. 인프라·DevOps

| 레포 | URL | 설명 |
|---|---|---|
| **caddyserver/caddy** | github.com/caddyserver/caddy | Go 리버스 프록시. HTTPS 자동. 설정 간결. ★58k+ |
| **nginx/nginx** | github.com/nginx/nginx | 프로덕션 프록시·로드밸런서 표준. |
| **moby/moby** | github.com/moby/moby | Docker Engine 소스. |
| **kubernetes/kubernetes** | github.com/kubernetes/kubernetes | K8s 소스. 이슈 트래커 참조용. |
| **hashicorp/terraform** | github.com/hashicorp/terraform | 인프라 코드. 프로바이더 생태계. |
| **grafana/grafana** | github.com/grafana/grafana | 메트릭·로그·트레이스 대시보드. ★64k+ |
| **prometheus/prometheus** | github.com/prometheus/prometheus | 메트릭 수집·알림. K8s 표준 모니터링. |
| **open-telemetry/opentelemetry-python** | github.com/open-telemetry/opentelemetry-python | OTel Python SDK. 분산 추적. |
| **cloudflare/cloudflared** | github.com/cloudflare/cloudflared | Cloudflare Tunnel 클라이언트. 포트 오픈 없이 서비스 노출. |

---

## 5. 보안

| 레포 | URL | 설명 |
|---|---|---|
| **OWASP/CheatSheetSeries** | github.com/OWASP/CheatSheetSeries | 보안 방어 치트시트 원본. |
| **gitleaks/gitleaks** | github.com/gitleaks/gitleaks | Git 히스토리 시크릿 탐지. CI 통합 용이. |
| **trufflesecurity/trufflehog** | github.com/trufflesecurity/trufflehog | 시크릿 탐지. 다양한 소스. |
| **aquasecurity/trivy** | github.com/aquasecurity/trivy | 컨테이너·IaC·패키지 취약점 스캔 올인원. |
| **pypa/pip-audit** | github.com/pypa/pip-audit | Python 패키지 취약점 감사. |
| **semgrep/semgrep** | github.com/semgrep/semgrep | SAST. 패턴 기반 정적 분석. 다언어. |

---

## 6. 데이터·DB

| 레포 | URL | 설명 |
|---|---|---|
| **postgres/postgres** | github.com/postgres/postgres | PostgreSQL 소스 미러. |
| **qdrant/qdrant** | github.com/qdrant/qdrant | Rust 벡터 DB. RAG 파이프라인에 적합. |
| **chroma-core/chroma** | github.com/chroma-core/chroma | Python 임베딩 DB. 로컬 프로토타이핑 최적. |
| **pgvector/pgvector** | github.com/pgvector/pgvector | PostgreSQL 벡터 확장. 별도 DB 없이 벡터 검색. |
| **apache/kafka** | github.com/apache/kafka | 분산 이벤트 스트리밍. |

---

## 7. 유틸리티·CLI

| 레포 | URL | 설명 |
|---|---|---|
| **BurntSushi/ripgrep** | github.com/BurntSushi/ripgrep | grep보다 빠른 코드 검색. ★48k+ |
| **sharkdp/bat** | github.com/sharkdp/bat | cat + syntax highlighting. ★49k+ |
| **ajeetdsouza/zoxide** | github.com/ajeetdsouza/zoxide | 스마트 cd. 히스토리 기반 디렉토리 점프. |
| **junegunn/fzf** | github.com/junegunn/fzf | 퍼지 파인더. shell/vim 통합. ★64k+ |
| **charmbracelet/bubbletea** | github.com/charmbracelet/bubbletea | Go TUI 프레임워크. Elm 아키텍처. |
| **extrawurst/gitui** | github.com/extrawurst/gitui | Rust TUI Git 클라이언트. |
| **dandavison/delta** | github.com/dandavison/delta | git diff 문법 강조+개선. |
| **casey/just** | github.com/casey/just | Makefile 대체. 태스크 러너. |
| **sigoden/argc** | github.com/sigoden/argc | Bash CLI 파라미터 파서. |

---

## 8. 참고 Awesome Lists

| 주제 | URL |
|---|---|
| Awesome Python | github.com/vinta/awesome-python |
| Awesome Go | github.com/avelino/awesome-go |
| Awesome Rust | github.com/rust-unofficial/awesome-rust |
| Awesome TypeScript | github.com/dzharii/awesome-typescript |
| Awesome LLM | github.com/Hannibal046/Awesome-LLM |
| Awesome MCP Servers | github.com/punkpeye/awesome-mcp-servers |
| Awesome RAG | github.com/frutik/Awesome-RAG |
| Awesome Security | github.com/sbilly/awesome-security |
| Awesome Self-Hosted | github.com/awesome-selfhosted/awesome-selfhosted |
| public-apis | github.com/public-apis/public-apis |
| free-for-dev | github.com/ripienaar/free-for-dev |

## Reuse
- 레포 추가 시: 이름/URL/한 줄 설명/별 수(대략) 형식.
- 분기 1회 활성 여부 확인 (last commit 날짜).
- 별 수 기준이 아닌 실용성 기준 — 5k 별이라도 매일 쓰면 포함.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [MDN Web Docs](https://developer.mozilla.org/)
- [web.dev](https://web.dev/)
