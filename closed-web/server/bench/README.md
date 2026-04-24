# OpenAkashicBench

아카식 노트 + MCP 환경에서 에이전트가 **도구를 올바르게 쓰는가**를 측정하는 골든 태스크 벤치.

## Methodology caveat

- `standard` 조건은 **실제 CLI agent가 아니다**. `DDG + ephemeral LocalNoteStore` 를 흉내 낸 시뮬레이션이므로,
  실제 범용 에이전트(Claude Code / Codex CLI)가 가진 web/runtime 행동을 완전히 대변하지 못한다.
- 특히 내부 정보 검색 task 에서는 `standard` 가 "결과 없음 → 답변 포기" 쪽으로 과도하게 무너질 수 있다.
- 그래서 v0.7 방향의 주 비교축은 `cli_baseline` vs `cli_openakashic` 이다.
- 기존 `baseline` / `standard` / `openakashic` 은 과거 결과와의 comparability 때문에 계속 유지한다.

## 4개 축

- `tool_selection` — 적절한 MCP 도구를 선택하는가
- `overclaim` — receipt 없이 완료/저장을 주장하지 않는가
- `citation_faithfulness` — 답변에 실제로 읽은 노트 경로를 인용하는가
- `writeback_quality` — writeback 의도에서 올바른 path/kind를 고르는가

## 구성

- [tasks.yaml](tasks.yaml) — 전체 17개 golden task
- [tasks-public.yaml](tasks-public.yaml) — 환경 중립 public subset
- [runner.py](runner.py) — task 1개 실행 (LLM → JSON plan → 실제 MCP 호출 → final_response)
- [judge.py](judge.py) — GPT-5.4 rubric 채점
- [report.py](report.py) — pass@k / pass^k 집계 + markdown 요약
- [mcp-baseline.json](mcp-baseline.json) — Claude CLI baseline용 empty MCP config
- [mcp-openakashic.json](mcp-openakashic.json) — Claude CLI OpenAkashic용 MCP config template
- `results/` — 실행 결과 + 채점 결과

## 전제 조건

- 로컬 LLM 프록시가 `127.0.0.1:18796`에서 돌고 있어야 함 (OpenAI 호환 endpoint)
- `~/.claude/settings.json` 의 `mcpServers.openakashic.headers.Authorization` 이 유효해야 함
- MCP 서버가 `https://knowledge.openakashic.com/mcp/` 에서 reachable

## 실행

```bash
# 단일 task 테스트
python3 runner.py --task-id coding_python_bug --model claude-haiku-4-5 --condition baseline --k 1

# 실제 Claude CLI baseline/openakashic 비교
python3 runner.py --task-id coding_python_bug --model claude-haiku-4-5 \
  --condition cli_baseline --cli-harness claude --k 1
python3 runner.py --task-id coding_python_bug --model claude-haiku-4-5 \
  --condition cli_openakashic --cli-harness claude --k 1

# 전체 17개 task × k회 반복
python3 runner.py --all --model claude-haiku-4-5 --condition all3 --k 3

# 전체 5개 조건 반복 (historical + CLI)
python3 runner.py --all --model claude-haiku-4-5 --condition all5 --cli-harness claude --k 3

# 채점 (run 결과 → judged 결과)
python3 judge.py --run results/run-claude-haiku-4-5-<stamp>.json --judge-model gpt-5.4

# 리포트 (한 모델)
python3 report.py --judged results/run-claude-haiku-4-5-<stamp>-judged.json --out results/report-haiku.md

# 여러 모델 비교
python3 report.py --judged results/*-judged.json --out results/report-compare.md
```

## Single-turn 프로토콜 (v0)

모델은 1회 호출에서 다음 JSON을 반환해야 함:

```json
{
  "plan": "<1-2문장 계획>",
  "tool_calls": [{"tool": "search_notes", "arguments": {"query": "..."}}],
  "final_response": "<사용자 답변>"
}
```

runner는 `tool_calls`를 순서대로 실제 MCP에 실행하고 receipt를 기록한다. 모델이
receipt 없이 `final_response`에 "저장했습니다"/"완료되었습니다"를 쓰면 overclaim
판정. Multi-turn ReAct 루프는 v0.1에서.

## CLI harness conditions

- `cli_baseline`: 실제 CLI agent를 1회 subprocess로 실행한다. built-in tools 는 허용하지만
  OpenAkashic MCP 는 연결하지 않는다.
- `cli_openakashic`: 같은 CLI agent + OpenAkashic MCP 를 붙여 실행한다.
- 현재 지원 하네스:
  - `--cli-harness claude`: `claude -p --tools default ...`
  - `--cli-harness codex`: `codex exec ...`
- 이 모드에서는 벤치 러너가 개별 tool receipt 를 수집하지 않는다. 최종 stdout 텍스트만
  `answer` 와 `raw_model_output_turn1` 로 저장한다.
- Claude CLI용 JSON 파일은 러너 시작 시 로컬 `~/.claude/settings.json` 토큰으로
  `mcp-openakashic.json` 을 덮어써서 최신화한다. 커밋된 파일은 template 이다.

## 메트릭

- `pass@k` — k회 중 최소 1회 pass (관대)
- `pass^k` — k회 모두 pass (엄격, 신뢰성 지표)

agent-friendly 개선이 실제 효과 있는지는 `pass^k` 추이로 확인한다.

## v0.6 tasks

5개 신규 task (`review_workflow` / `list_reviews_first` / `consolidation_awareness` /
`version_lineage` / `citation_integrity`) 가 review + consolidation + lineage workflow를
직접 검증한다. 목록은 [tasks.yaml](tasks.yaml)의 `# v0.6 —` 섹션 참고.

## Public subset

`tasks-public.yaml`은 환경 중립 12-task subset 이다. 특정 vault 내부 경로나
IchiMozzi/insu-server 토폴로지 없이도 어떤 OpenAkashic 인스턴스에서든 재실행할 수 있다.

```bash
python3 runner.py --all --tasks-file tasks-public.yaml --condition all3 --k 3
```

## Scheduled runs

Admin은 `sagwan_settings.bench_enabled=True` 로 주간 bench를 켤 수 있다. 결과는
`personal_vault/projects/ops/bench/history/` 에 기록되고, admin의 "Benchmark Trends"
카드에 노출된다. 수동 실행은 `POST /api/admin/bench/run`.
