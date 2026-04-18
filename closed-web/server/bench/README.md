# OpenAkashicBench v0

아카식 노트 + MCP 환경에서 에이전트가 **도구를 올바르게 쓰는가**를 측정하는 골든 태스크 벤치.

## 4개 축

- `tool_selection` — 적절한 MCP 도구를 선택하는가
- `overclaim` — receipt 없이 완료/저장을 주장하지 않는가
- `citation_faithfulness` — 답변에 실제로 읽은 노트 경로를 인용하는가
- `writeback_quality` — writeback 의도에서 올바른 path/kind를 고르는가

## 구성

- [tasks.yaml](tasks.yaml) — 15개 golden task (axis × 3~5)
- [runner.py](runner.py) — task 1개 실행 (LLM → JSON plan → 실제 MCP 호출 → final_response)
- [judge.py](judge.py) — GPT-5.4 rubric 채점
- [report.py](report.py) — pass@k / pass^k 집계 + markdown 요약
- `results/` — 실행 결과 + 채점 결과

## 전제 조건

- 로컬 LLM 프록시가 `127.0.0.1:18796`에서 돌고 있어야 함 (OpenAI 호환 endpoint)
- `~/.claude/settings.json` 의 `mcpServers.openakashic.headers.Authorization` 이 유효해야 함
- MCP 서버가 `https://knowledge.openakashic.com/mcp/` 에서 reachable

## 실행

```bash
# 단일 task 테스트
python3 runner.py --task-id ts_001 --model claude-haiku-4-5 --k 1

# 전체 15개 task × k회 반복
python3 runner.py --all --model claude-haiku-4-5 --k 3

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

## 메트릭

- `pass@k` — k회 중 최소 1회 pass (관대)
- `pass^k` — k회 모두 pass (엄격, 신뢰성 지표)

agent-friendly 개선이 실제 효과 있는지는 `pass^k` 추이로 확인한다.
