---
title: "Closed Akashic Plan"
kind: architecture
project: closed-akashic
status: active
confidence: high
tags: [plan, architecture, aws, mcp]
related: ["Agent Guide", "AWS Central Vault", "Vault Note Schema"]
created_at: 2026-04-11T00:00:00Z
updated_at: 2026-04-14T08:20:24Z
created_by: aaron
original_owner: aaron
visibility: public
publication_status: published
owner: sagwan
---

0. 한 줄 설계

AWS에 중앙 vault를 두고, 모든 개인 Codex/Cursor 에이전트는 MCP 서버를 통해 그 vault를 읽고 쓴다. 사람은 데스크탑에서 Obsidian으로 같은 vault의 동기화본을 열어 Graph, Bases, Canvas로 관리한다. Obsidian은 노트를 로컬 파일시스템의 Markdown plain text 파일로 저장하고, 외부 변경을 자동 반영한다. Bases는 notes와 properties의 database-like view를 제공하고, Graph view는 노트 간 내부 링크를 시각화한다. Codex는 AGENTS.md를 읽어 지침을 계층적으로 적용하고, Codex와 Cursor 모두 MCP 서버를 연결해 외부 도구와 컨텍스트를 사용할 수 있다.

1. 가장 먼저 정할 것

나는 정본은 AWS working tree, 백업/이력은 Git, 사람 편집은 데스크탑 동기화본으로 가겠다.

직접 원격 폴더를 Obsidian에 마운트해서 여는 것보다, 데스크탑에 동기화된 로컬 사본을 열게 하는 편이 낫다. 이유는 간단하다. Obsidian은 로컬 파일 폴더를 vault로 쓰는 구조라 네트워크 마운트보다 로컬 사본이 훨씬 안정적이고, Git 이력도 같이 가져가기 쉽다. 이 부분은 공식 기능 위에 얹는 운영 설계다.

AWS에는 이런 구조를 둬라.

/srv/akashic/
├─ vault-live/          # MCP가 실제로 읽고 쓰는 working tree
├─ vault-backup.git/    # bare repo 또는 미러용 local bare repo
├─ snapshots/           # tar.gz 일일 백업
├─ mcp-server/          # MCP 서버 코드
├─ indexer/             # 색인/임베딩 워커
└─ state/               # sqlite, 락파일, 로그

데스크탑에는:

~/vaults/akashic-vault/   # Obsidian으로 여는 로컬 동기화본
2. 구현 순서
1단계: AWS에 중앙 vault부터 만든다

먼저 AWS에 vault를 plain markdown 저장소로 만든다.

sudo mkdir -p /srv/akashic/{vault-live,vault-backup.git,snapshots,mcp-server,indexer,state}
sudo chown -R $USER:$USER /srv/akashic

cd /srv/akashic/vault-live
git init
mkdir -p 00_inbox 01_projects 02_concepts 03_entities 04_shared-patterns 05_shared-playbooks 06_daily 07_reviews 08_indexes 09_canvas 10_bases
touch README.md
git add .
git commit -m "init akashic vault"

그다음 이 저장소를 private GitHub repo에 push하거나, AWS 안에 bare repo를 따로 두고 데스크탑이 SSH로 pull/push 하게 해라. Obsidian의 데이터는 plain text 파일이므로 Git 기반 이력 관리와 궁합이 좋다.

2단계: 데스크탑에서 Obsidian으로 연다

데스크탑에서 vault를 clone하고 Obsidian으로 연다.

cd ~/vaults
git clone <your-private-repo-or-aws-ssh-url> akashic-vault

Obsidian에서 ~/vaults/akashic-vault를 vault로 열면 된다. Graph view, Canvas, Bases는 모두 core plugin이라 바로 켤 수 있다. Graph는 노트와 내부 링크를 시각화하고, Canvas는 2D 공간에 노트·첨부·웹페이지를 배치하고 연결하며, Bases는 properties 기반 view를 제공한다.

3단계: 노트 스키마를 먼저 고정한다

긴 README를 없앨 거면, 노트 타입과 frontmatter부터 고정해야 한다. Obsidian의 properties는 YAML frontmatter로 저장할 수 있고, 검색에서도 [property:value] 식으로 바로 질의할 수 있다.

추천 타입은 이 정도로 시작하면 된다.

project-overview
decision
incident
pattern
playbook
experiment
entity
concept

공통 템플릿은 이렇게 잡아라.

---
title: ""
kind: incident
project: japanese-app
status: draft
confidence: medium
tags: []
related: []
source_paths: []
created_at: 2026-04-11T00:00:00Z
updated_at: 2026-04-11T00:00:00Z
---

본문은 무조건 짧게 간다.

## Summary
한 줄 요약

## Details
무슨 일이 있었는지

## Fix / Outcome
어떻게 해결했는지

## Reuse
다른 프로젝트에도 재사용 가능한지
3. MCP 서버는 이렇게 만든다

핵심은 에이전트에게 vault 파일시스템을 직접 열어주지 말고, 표준화된 MCP 도구만 열어주는 것이다. 네 에이전트들이 전부 개인용이어도, raw file edit를 풀어버리면 포맷이 깨지고 동일 노트 충돌이 늘어난다. 그래서 “읽기/쓰기 허용”은 하되, 파일 단위가 아니라 도구 단위로 허용해라.

처음 버전에서 꼭 필요한 도구는 8개면 충분하다.

search_memory(query, project?, kind?, status?, tags?, limit?)
get_note(path)
create_note(kind, project, title, properties, body)
update_note(path, expected_rev, patch)
append_experience(project, title, payload)
link_notes(from_path, to_path)
list_recent(project?, days?)
move_note(path, new_folder)

여기서 중요한 건 expected_rev다.
노트마다 frontmatter에 rev: 12 같은 정수를 두고, 수정할 때 현재 revision이 일치할 때만 update하게 해라. 이러면 같은 노트를 두 에이전트가 동시에 수정할 때 덮어쓰기를 막을 수 있다.

노트 예시:

---
title: mobile build failure after schema change
kind: incident
project: japanese-app
status: draft
rev: 3
confidence: medium
created_at: 2026-04-11T09:10:00Z
updated_at: 2026-04-11T09:12:00Z
---
MCP 구현 언어

Python으로 만드는 게 제일 무난하다.
이 서버는 크게 3가지만 하면 된다.

frontmatter 파싱
markdown 파일 CRUD
검색 인덱스 질의

처음엔 MCP 서버 하나에 다 넣고, 나중에 indexer를 분리해도 된다.

4. 검색은 2단계로 나눠서 붙여라

여기서 무리하지 않는 게 중요하다.

1차: 바로 쓸 수 있는 검색

처음엔 파일 검색 + 메타데이터 검색만으로 충분하다.

제목 검색
본문 키워드 검색
properties 필터
backlinks / related note 조회

Obsidian 자체도 property 검색과 graph 탐색이 가능하니, 사람은 이걸로 충분히 관리할 수 있다. [property:value] 같은 검색 문법도 공식 지원한다.

서버 쪽은 이렇게 가면 된다.

SQLite에 note metadata 저장
본문은 FTS5 또는 ripgrep 기반 키워드 검색
related는 markdown 내부 링크 파싱으로 해결

이걸로도 “유사 incident”, “같은 project의 pattern”, “draft 상태만 조회”는 충분하다.

2차: 하이브리드 검색

그다음에 Qdrant를 붙여라.

Qdrant는 dense+sparse 하이브리드 검색, payload 기반 필터링, 실시간 업데이트를 지원한다. 또 벡터 엔진이지만 knowledge graph 자체를 내장하려는 방향은 아니라고 밝히고 있다. 네 상황처럼 “Neo4j는 빼고 의미 검색 + 필터 검색만” 하려면 딱 맞다.

그래서 검색 구조는 이렇게 가져가면 된다.

query
 ├─ keyword search (sqlite/ripgrep)
 ├─ vector search (Qdrant)
 └─ metadata filters (project, kind, status, tags, updated_at)
      ↓
   merged + reranked result

Qdrant payload에는 최소한 이것만 넣어라.

{
  "path": "01_projects/japanese-app/incidents/mobile-build-failure.md",
  "project": "japanese-app",
  "kind": "incident",
  "status": "reviewed",
  "tags": ["build", "schema"],
  "updated_at": "2026-04-11T09:12:00Z"
}
5. 인덱서 워커는 별도 프로세스로 둬라

MCP 서버가 노트를 고칠 때마다 직접 임베딩까지 만들면 느려진다.
그래서 색인은 비동기 워커로 분리해라.

흐름은 이렇게 간다.

MCP create/update
  → markdown 파일 저장
  → changed_paths 큐에 적재
  → indexer-worker가 변경 파일 읽음
  → frontmatter 파싱
  → markdown chunk 분할
  → sqlite metadata 업데이트
  → Qdrant upsert

청크 단위는 처음엔 단순하게:

제목 단위 분할
500~800토큰 수준
각 청크에 path, heading, project, kind payload 부여

이렇게만 해도 충분하다.

6. 에이전트가 실제로 어떻게 쓰게 할지

각 프로젝트 repo에는 긴 문서 대신 얇은 AGENTS.md만 남겨라. Codex는 AGENTS.md를 읽어 작업 지침을 적용하고, MCP 서버는 CLI와 IDE 확장 모두에서 연결할 수 있다. Cursor도 MCP로 외부 시스템과 데이터를 붙일 수 있다.

예시는 이 정도면 된다.

# AGENTS.md

## Project
japanese-app

## Build / Test
- backend: pnpm test
- mobile: pnpm lint

## Memory
- 장기 지식과 과거 경험은 중앙 akashic vault MCP에서 조회한다.
- 긴 프로젝트 문서는 repo 안에 만들지 않는다.
- 작업 종료 후 incident / pattern / experiment 중 하나를 append_experience로 남긴다.

## Preferred workflow
1. search_memory()로 유사 사례 찾기
2. 코드 수정
3. 검증 실행
4. append_experience()로 경험 저장

Codex global 설정이나 Cursor 설정에는 같은 MCP 서버를 등록하면 된다. Codex 문서상 CLI와 IDE 확장 간 MCP 설정을 공유할 수 있다.

7. “경험 축적”은 이렇게 자동화해라

여기가 제일 중요하다.

에이전트가 작업을 끝내면 긴 보고서 대신 짧은 구조화 경험 레코드를 남기게 해라.

예:

{
  "kind": "incident",
  "project": "japanese-app",
  "title": "mobile build failure after schema change",
  "summary": "schema 변경 후 mobile build 실패",
  "cause_guess": "codegen 미실행",
  "fix": "generate 실행 후 rebuild",
  "verification": "pnpm build 성공",
  "source_paths": ["backend/schema.graphql", "mobile/package.json"],
  "related": ["[[API schema]]", "[[codegen]]"]
}

MCP의 append_experience()는 이 JSON을 받아서:

새 노트로 만들고
frontmatter 채우고
관련 링크 붙이고
00_inbox/agent-drafts/ 또는 프로젝트 incidents/ 아래 저장하게 하면 된다.

즉 덮어쓰기보다 새 노트 생성이 기본이다.
이 방식이면 여러 에이전트가 동시에 써도 충돌이 훨씬 적다.

8. 사람이 Obsidian에서 관리하는 화면

사람은 Obsidian을 “편집기”보다 운영 콘솔처럼 쓰면 된다.

Bases

10_bases/review.base

kind == "incident" and status == "draft"
project == "japanese-app" and confidence != "high"
kind == "pattern" and status == "candidate"

Bases는 notes와 properties를 정렬·필터·편집하는 database-like view라서 이런 검토 큐에 딱 맞다.

Graph
프로젝트별 로컬 그래프 보기
고립된 문서 찾기
incident ↔ pattern ↔ playbook 연결 확인

Graph view는 노트를 노드, 내부 링크를 선으로 보여준다.

Canvas
프로젝트 구조도
장애 흐름도
공통 패턴 맵

Canvas는 노트, 첨부, 웹페이지를 2D 공간에 배치하고 연결하며, .canvas 파일로 저장된다.

9. 운영 규칙은 이것만 지켜라

이 5개만 지키면 안 망가진다.

정본은 AWS vault-live 하나
에이전트는 MCP 도구로만 수정
같은 노트 직접 덮어쓰기보다 새 노트 생성
모든 변경은 Git 커밋 + 일일 스냅샷
사람은 Bases에서 draft를 주기적으로 정리

Git 자동 커밋은 이렇게 해라.

cd /srv/akashic/vault-live
git add .
git commit -m "auto: vault update $(date -Iseconds)" || true
git push origin main

cron이나 systemd timer로:

10분마다 auto-commit
하루 1회 tar.gz snapshot
하루 1회 index consistency check

이 정도면 충분하다.

10. 최소 구현 스택

지금 네 장비 기준으로는 이렇게 가면 된다.

AWS medium
Python MCP 서버
SQLite metadata DB
Qdrant 1개 컨테이너
Git auto-backup
systemd 또는 Docker Compose
RTX3060 데스크탑
Obsidian
로컬 vault clone
필요하면 임베딩 재생성 배치
사람이 review / promote

처음엔 SQLite + Markdown + MCP만으로 시작하고,
검색 품질이 아쉬워질 때 Qdrant를 붙여라.
처음부터 모든 걸 다 올리면 오히려 유지보수가 힘들다.

11. 네가 바로 시작할 순서

오늘 당장 할 일만 뽑으면 이거다.

AWS에 /srv/akashic/vault-live 만든다.
vault 폴더 구조 만든다.
데스크탑에 clone해서 Obsidian으로 연다.
공통 frontmatter 템플릿 만든다.
MCP 서버에 search_memory, get_note, create_note, append_experience, update_note 5개만 먼저 구현한다.
각 프로젝트 repo에 얇은 AGENTS.md를 넣는다.
에이전트가 작업 끝날 때 append_experience()를 무조건 호출하게 한다.
일단 1주일은 수동 review만 한다.
그다음 Qdrant를 붙인다.
12. 내 추천 최종안

네 목표에는 이게 제일 맞다.

중앙 기억 저장소: AWS Markdown vault
사람 UI: Obsidian
에이전트 진입점: MCP 서버
초기 검색: SQLite/키워드 + metadata
확장 검색: Qdrant hybrid search
경험 축적 방식: append 중심의 작은 note 생성
복구 수단: Git + snapshots
