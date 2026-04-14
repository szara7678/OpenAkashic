---
title: Development Resource Map
kind: reference
project: closed-akashic
status: active
confidence: high
tags: [development, reference, mdn, fastapi, python, openai, cloudflare]
related: [Open and Closed Akashic Strategy, Agent Skills Contract]
owner: sagwan
visibility: public
publication_status: published
created_by: aaron
original_owner: aaron
created_at: 2026-04-14T00:00:00Z
updated_at: 2026-04-14T00:00:00Z
---

## Summary
OpenAkashic/Closed 통합 구조를 운영할 때 바로 이어서 볼 만한 개발 자료를 프론트엔드, Python 백엔드, 에이전트 API, 상태형 에이전트 쪽으로 묶은 지도다.

## Frontend Foundation
- MDN Learn Web Development: https://developer.mozilla.org/en-US/docs/Learn_web_development
- MDN은 프론트엔드 개발자가 알아야 할 핵심을 구조화해서 다루고, 학습 경로를 `Getting started`, `Core`, `Extension`으로 나눈다.
- 완전 초보부터 시작할 때는 Getting started를 먼저, 실전 HTML/CSS/JS는 Core를 먼저 끝내고, 그 다음 Extension으로 넓히는 흐름이 가장 자연스럽다.

## Python Backend Foundation
- Python `venv`: https://docs.python.org/3.14/tutorial/venv.html
- Python `pathlib`: https://docs.python.org/3/library/pathlib.html
- FastAPI Tutorial: https://fastapi.tiangolo.com/tutorial/
- Python 공식 문서는 라이브러리 충돌을 피하려면 virtual environment를 쓰고, `.venv` 같은 디렉터리를 관례로 두는 방식을 권장한다.
- `pathlib.Path`는 파일 경로를 문자열 대신 객체로 다룰 수 있게 해 주기 때문에, 현재 OpenAkashic 서버처럼 경로 정규화와 상대/절대 경계가 중요한 코드에서 특히 유용하다.
- FastAPI는 Tutorial - User Guide만으로도 완전한 앱을 만들 수 있게 구성하고, 이후 Advanced User Guide로 확장하는 방식을 권한다.

## Agent And API Runtime
- OpenAI Responses migration guide: https://developers.openai.com/api/docs/assistants/migration
- Cloudflare Agents docs: https://developers.cloudflare.com/agents/
- OpenAI는 Responses API를 더 단순하고 유연한 기본 모델로 두고, 예전 Assistants/Threads/Runs를 Prompts/Conversations/Responses로 옮기는 흐름을 권장한다.
- 이 가이드는 도구 루프를 애플리케이션 코드가 명시적으로 관리하는 방향을 강조하므로, 현재 Sagwan 운영면 설계와 잘 맞는다.
- Cloudflare Agents는 stateful agent를 Durable Object 위에서 돌리고, 스케줄, 웹소켓, MCP, 도구 호출을 한 타입스크립트 클래스 안에서 다루는 구조를 제시한다.

## How This Connects To OpenAkashic
- 문서/페이지 UI 개선: MDN
- FastAPI 서버/API 설계: Python docs + FastAPI tutorial
- Sagwan/OpenAI 도구 루프: Responses migration guide
- 장기 상태형 agent나 원격 MCP 확장: Cloudflare Agents

## Source Notes
- MDN은 structured tutorials, challenges, recommended resources를 제공하고, 초보자를 `beginner`에서 `comfortable` 단계까지 끌어올리는 것을 목표로 한다.
- Python docs는 `python -m venv .venv` 같은 격리 환경과 `python -m pip freeze > requirements.txt` 흐름을 기준선으로 삼는다.
- FastAPI tutorial은 Tutorial을 먼저 끝낸 뒤 Advanced guide로 확장하라고 안내한다.
- OpenAI migration guide는 Responses API가 deep research, MCP, computer use 같은 최신 기능을 포함하고, Assistants API는 2026-08-26에 종료된다고 명시한다.
- Cloudflare Agents docs는 stateful agent를 Durable Object와 연결하고, 스케줄링, 웹 브라우징, 워크플로, MCP를 같은 SDK 범위에서 다룬다.
