---
title: "Agent Memory Workflow"
kind: playbook
project: personal/openakashic
status: active
confidence: high
tags: [agent, mcp, workflow]
related: ["AWS Central Vault", "Vault Note Schema", "LLM Maintained Wiki"]
created_at: 2026-04-11T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

## Summary
에이전트는 작업 시작 전에 기억을 검색하고, 작업 종료 후 경험을 짧은 구조화 노트로 남긴다.

## Steps
1. search_memory로 유사 사례를 찾는다.
2. 필요한 코드를 수정하고 검증한다.
3. append_experience로 incident, pattern, experiment 중 하나를 남긴다.

## Links
이 흐름은 [[AWS Central Vault]]와 [[LLM Maintained Wiki]]를 연결한다.
