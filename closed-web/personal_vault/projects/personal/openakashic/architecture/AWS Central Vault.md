---
title: AWS Central Vault
kind: architecture
project: personal/openakashic
status: active
confidence: high
tags: [aws, vault, mcp]
related: [Agent Memory Workflow, Obsidian Workflow, Vault Note Schema]
created_at: 2026-04-11T00:00:00Z
updated_at: 2026-04-11T00:00:00Z
---

## Summary
AWS에 중앙 vault를 두고 개인 Codex/Cursor 에이전트는 MCP 서버를 통해 읽고 쓴다.

## Details
정본은 AWS working tree, 백업과 이력은 Git, 사람 편집은 데스크탑 동기화본으로 둔다.

## Reuse
OpenAkashic 개인 창고의 기본 운영 모델이다. [[Agent Memory Workflow]]와 함께 사용한다.
