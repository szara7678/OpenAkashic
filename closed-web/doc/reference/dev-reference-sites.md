---
title: dev-reference-sites
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
created_at: 2026-04-15T02:08:51Z
publication_requested_at: 2026-04-15T02:09:08Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:58Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
---

## Summary
개발자 필수 참조 사이트 큐레이션. 공식 문서·학습 플랫폼·도구·커뮤니티·뉴스 카테고리로 분류. "북마크 대신 이 노트만 참조" 목표.

## Sources
- roadmap.sh, MDN, 각 공식 문서
- 커뮤니티 추천 종합 (GitHub discussions, Reddit r/webdev, r/programming)

---

## 1. 공식 문서 (언어·런타임)

| 언어/런타임 | URL | 비고 |
|---|---|---|
| Python | docs.python.org/3/ | 표준 라이브러리 포함 |
| Go | go.dev/doc/ | Tour of Go로 입문 |
| Rust | doc.rust-lang.org/book/ | The Book. 공식 무료 |
| TypeScript | typescriptlang.org/docs/ | Handbook + Playground |
| Node.js | nodejs.org/api/ | API 레퍼런스 |
| Deno | docs.deno.com | Web-first TS 런타임 |
| Bun | bun.sh/docs | 빠른 JS 올인원 툴킷 |

---

## 2. 웹·프레임워크

| 주제 | URL | 비고 |
|---|---|---|
| MDN Web Docs | developer.mozilla.org | HTML/CSS/JS 최우선 참조 |
| React | react.dev | 공식 Docs (Hooks 중심) |
| Next.js | nextjs.org/docs | App Router 중심 |
| Astro | docs.astro.build | 정적+하이브리드 |
| Svelte | svelte.dev/docs | 컴파일러 기반 UI |
| Tailwind CSS | tailwindcss.com/docs | Utility-first CSS |
| Vite | vitejs.dev/guide | 현대 번들러 |

---

## 3. 백엔드·API

| 주제 | URL | 비고 |
|---|---|---|
| FastAPI | fastapi.tiangolo.com | Python async API |
| Django REST | django-rest-framework.org | 배터리 포함 |
| Hono | hono.dev | Edge-first TS 프레임워크 |
| Axum | docs.rs/axum | Rust 웹 프레임워크 |
| gRPC | grpc.io/docs/ | 프로토콜 버퍼 기반 RPC |
| OpenAPI | spec.openapis.org | REST API 명세 표준 |
| Swagger UI | swagger.io/tools/swagger-ui | API 문서화 |

---

## 4. AI / LLM 개발

| 주제 | URL | 비고 |
|---|---|---|
| Anthropic API | docs.anthropic.com | Claude API 공식 |
| Claude Code Docs | code.claude.com/docs | Claude Code CLI |
| MCP (Model Context Protocol) | modelcontextprotocol.io | MCP 스펙·예제 |
| OpenAI API | platform.openai.com/docs | GPT·o-series |
| Hugging Face | huggingface.co/docs | 모델·데이터셋·Spaces |
| LangChain | python.langchain.com | LLM 애플리케이션 프레임워크 |
| LlamaIndex | docs.llamaindex.ai | RAG·에이전트 |
| Ollama | ollama.ai | 로컬 LLM 실행 |
| vLLM | docs.vllm.ai | 고성능 LLM 서빙 |
| Langfuse | langfuse.com/docs | LLM Observability |
| arXiv CS.AI | arxiv.org/list/cs.AI/new | 최신 AI 논문 |
| alphaXiv | alphaxiv.org | arXiv + 토론 |
| Ahead of AI | magazine.sebastianraschka.com | Sebastian Raschka 주간 AI 리뷰 |

---

## 5. 데이터베이스·인프라

| 주제 | URL | 비고 |
|---|---|---|
| PostgreSQL | postgresql.org/docs/current/ | 공식 문서 완전체 |
| SQLite | sqlite.org/docs.html | 임베디드 DB |
| Redis | redis.io/docs | 캐시·큐·세션 |
| MongoDB | mongodb.com/docs | NoSQL Document |
| Prisma | prisma.io/docs | TypeScript ORM |
| Docker | docs.docker.com | 컨테이너 공식 |
| Kubernetes | kubernetes.io/docs | k8s 공식 |
| Terraform | developer.hashicorp.com/terraform | IaC |
| Caddy | caddyserver.com/docs | 리버스 프록시·HTTPS 자동 |

---

## 6. 클라우드

| 주제 | URL | 비고 |
|---|---|---|
| AWS Docs | docs.aws.amazon.com | 서비스별 상세 |
| GCP Docs | cloud.google.com/docs | Vertex AI 포함 |
| Cloudflare Docs | developers.cloudflare.com | Tunnel·R2·Workers·D1 |
| Fly.io | fly.io/docs | 간단 배포 (소규모) |
| Railway | docs.railway.app | 풀스택 PaaS |
| Hetzner | docs.hetzner.com | 가성비 VPS/전용서버 |

---

## 7. 보안

| 주제 | URL | 비고 |
|---|---|---|
| OWASP Top 10 | owasp.org/Top10 | 웹 취약점 10선 |
| OWASP Cheat Sheets | cheatsheetseries.owasp.org | 주제별 방어 가이드 |
| Mozilla SecGuide | infosec.mozilla.org/guidelines/web_security | 헤더·TLS 기준 |
| NIST 800-63B | pages.nist.gov/800-63-3/sp800-63b | 인증 가이드라인 |
| CVE DB | cve.org | 취약점 DB |
| Snyk | snyk.io | 의존성 취약점 스캔 |

---

## 8. 학습·로드맵

| 주제 | URL | 비고 |
|---|---|---|
| roadmap.sh | roadmap.sh | 직군별 학습 로드맵 |
| MDN Learn | developer.mozilla.org/en-US/docs/Learn | 웹 기초 |
| The Odin Project | theodinproject.com | 풀스택 무료 커리큘럼 |
| freeCodeCamp | freecodecamp.org | 무료 인증 과정 |
| CS50 | cs50.harvard.edu | 하버드 CS 입문 (무료) |
| MIT OpenCourseWare | ocw.mit.edu | MIT 강의 무료 |
| fast.ai | fast.ai | 실용 딥러닝 무료 |
| Andrej Karpathy | karpathy.ai | LLM from scratch 시리즈 |

---

## 9. 뉴스·커뮤니티

| 주제 | URL | 비고 |
|---|---|---|
| Hacker News | news.ycombinator.com | 개발·스타트업 뉴스 |
| Reddit r/programming | reddit.com/r/programming | 개발 일반 |
| Reddit r/MachineLearning | reddit.com/r/MachineLearning | ML 커뮤니티 |
| The Pragmatic Engineer | newsletter.pragmaticengineer.com | 시니어 엔지니어링 뉴스레터 |
| Bytes (JS 뉴스) | bytes.dev | JavaScript 주간 |
| TLDR Newsletter | tldrnewsletter.com | 기술 뉴스 요약 |
| GitHub Trending | github.com/trending | 주간 트렌딩 레포 |
| Papers With Code | paperswithcode.com | 논문 + 코드 |

---

## 10. 도구·유틸리티

| 도구 | URL | 용도 |
|---|---|---|
| Excalidraw | excalidraw.com | 빠른 다이어그램·스케치 |
| dbdiagram.io | dbdiagram.io | DB ERD 작성 |
| regex101 | regex101.com | 정규식 테스트·설명 |
| cron.help | cron.help | cron 표현식 |
| httpbin | httpbin.org | HTTP 테스트 |
| jwt.io | jwt.io | JWT 디코더 |
| tldr.sh | tldr.sh | man 페이지 요약 |
| explainshell | explainshell.com | shell 명령어 설명 |
| Devdocs | devdocs.io | 다중 언어 문서 통합 |
| Caniuse | caniuse.com | 브라우저 지원 확인 |

## Reuse
- 사이트 추가 시 URL + 한 줄 용도 필수.
- 404 또는 서비스 종료 의심 시 확인 후 제거.
- AI/LLM 섹션은 빠르게 변하므로 분기 1회 리뷰 권장.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [MDN Web Docs](https://developer.mozilla.org/)
- [web.dev](https://web.dev/)
