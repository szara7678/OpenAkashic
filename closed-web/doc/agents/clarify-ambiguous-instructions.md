---
title: "Agent Guideline — 모호한 지시는 구체화 후 진행"
kind: playbook
project: openakashic
status: active
confidence: high
tags: [agent-guideline, collaboration, clarification, shared]
related: ["ARC Fleet Project"]
visibility: private
created_by: aaron
owner: aaron
publication_status: none
updated_at: 2026-04-16T01:07:45Z
created_at: 2026-04-16T01:07:45Z
---

## Summary
사용자(아론)의 지시가 모호하거나 꼭 필요한 정보가 빠져 있으면 **임의 가정으로 진행하지 말고 먼저 질문으로 구체화한 뒤에 실행**한다. 이 지침은 Codex, Cursor, Claude Code 등 모든 원격 에이전트에 공통 적용된다. (2026-04-16 확정)

## Rule
1. 새 기능/변경 요청을 받으면 먼저 다음을 짚는다:
   - **용어의 현재 코드 정의** (이미 있는 개념인지, 신규인지)
   - **영향 범위** (페이지/스키마/마이그레이션 대상)
   - **엣지 케이스** (기존 데이터 처리, 복수 허용 여부, 권한 분리 등)
2. **확인 가능한 사실은 먼저 코드·DB·로그로 조사**한 뒤, 조사해도 남는 모호함만 사용자에게 질문한다.
   - ❌ "기존에 X 데이터가 있다면 어떻게 처리할까요?" (가정 질문)
   - ✅ 조사 후 "현재 N건 존재합니다. ① 무효화 ② 유지 ③ 경고 중 어느 쪽이 좋을까요?" 또는 "조회해 보니 해당 데이터가 없어 마이그레이션은 필요 없습니다. 진행해도 될까요?"
3. 질문은 **번호로 분리**하고, 각 항목에 가능한 선택지 2~4개와 제 **추천 + 이유**를 함께 제시한다. 사용자가 빠르게 yes/no 또는 번호로 답할 수 있게 한다.
4. 이 규칙은 "확인하면 답을 알 수 있는 것"에만 적용한다. 사용자의 **의도·선호**(UI 폼팩터, 용어 선택, 정렬 의미)는 그대로 질문해도 된다.
5. 단순·국소 지시(파일 한 줄 수정, 타입 오류 수정 등)에는 과하게 적용하지 않는다. 작업 단위가 커지거나 여러 파일·스키마·외부 계약이 얽히면 반드시 적용한다.

## Why
- 과거 세션에서 임의 가정으로 진행 → 방향 틀어져 재작업 발생.
- 가정 기반 질문 ("있으면 어떻게?") → 사용자가 "그건 확인하고 물어봤어야지"라고 지적.
- 구체화 단계를 앞당기면 결정이 Akashic decision 노트로 남아 이후 세션이 재질문하지 않게 됨.

## How to Apply in Practice
1. 정찰: Grep/Glob/간단한 Read로 관련 파일·스키마·기존 패턴을 5~10분 이내로 파악.
2. 질문: 남은 모호함만 번호로 정리, 추천 포함.
3. 사용자 확정 → 결정사항을 **Akashic decision 노트**(`personal_vault/projects/<...>/decisions/<date>-<topic>.md`)로 저장 후 구현 시작.
4. 구현 중 새로운 모호함이 나오면 같은 절차 반복. 말없이 추정하지 않는다.

## Reuse
에이전트 세션 시작 시 이 노트 또는 프로젝트 `AGENTS.md`를 통해 본 규칙을 로드한다. Codex는 `~/.codex/AGENTS.md`, Cursor는 `.cursor/rules/*.mdc`, Claude Code는 세션별 CLAUDE.md·memory에서 각자 참조.
