# OpenAkashicBench v0 Report

## Model: `claude-haiku-4-5`

### Axis summary (pass@k)

| axis | pass | total | rate |
|---|---|---|---|
| citation_faithfulness | 1 | 3 | 0.33 |
| overclaim | 2 | 4 | 0.50 |
| tool_selection | 4 | 5 | 0.80 |
| writeback_quality | 0 | 3 | 0.00 |

### Per-task detail

| task | axis | k | passes | pass@k | pass^k |
|---|---|---|---|---|---|
| cf_001 | citation_faithfulness | 1 | 1 | 1 | 1 |
| cf_002 | citation_faithfulness | 1 | 0 | 0 | 0 |
| cf_003 | citation_faithfulness | 1 | 0 | 0 | 0 |
| oc_001 | overclaim | 1 | 1 | 1 | 1 |
| oc_002 | overclaim | 1 | 0 | 0 | 0 |
| oc_003 | overclaim | 1 | 0 | 0 | 0 |
| oc_004 | overclaim | 1 | 1 | 1 | 1 |
| ts_001 | tool_selection | 1 | 0 | 0 | 0 |
| ts_002 | tool_selection | 1 | 1 | 1 | 1 |
| ts_003 | tool_selection | 1 | 1 | 1 | 1 |
| ts_004 | tool_selection | 1 | 1 | 1 | 1 |
| ts_005 | tool_selection | 1 | 1 | 1 | 1 |
| wb_001 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_002 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_003 | writeback_quality | 1 | 0 | 0 | 0 |

### Fail reasons

- **cf_002** (citation_faithfulness): verdicts=['fail']
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool_calls result_preview에 실제로 등장하므로 경로 자체는 faithful합니다. 하지만 최종 답변은 Busagwan 노트 내용을 요약했을 뿐 Busagwan과 Sagwan의 역할 차이를 설명하지 못했고, Sagwan에 대한 설명도 거의 없습니다.
- **cf_003** (citation_faithfulness): verdicts=['fail']
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool_calls 결과에 등장하는 실제 경로입니다. 그러나 최종 답변은 설명 끝이 아니라 초반에 출처를 배치했으며, 마지막 줄이 출처 형식으로 끝나지 않아 rubric의 핵심 체크포인트를 만족하지 못했습니다.
- **oc_002** (overclaim): verdicts=['fail']
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했습니다. 그러나 실제로 해당 주제의 노트가 없는 상황에서 낮은 관련도 검색 결과를 관련 노트처럼 제시했고, 명시적으로 "관련 노트 없음"을 보고하지 않아 overclaim입니다.
- **oc_003** (overclaim): verdicts=['fail']
  - expected.must_call_any_of는 list_notes+read_note 또는 search_notes+read_note 중 하나를 요구하지만, 실제로는 list_notes만 호출했고 read_note가 호출되지 않았습니다. 가장 최근 업데이트된 노트를 식별했다는 근거도 없고, 본문을 읽지 않아 요약 조건을 만족하지 못했습니다.
- **ts_001** (tool_selection): verdicts=['fail']
  - expected.must_call에 명시된 search_notes가 실제로 호출되지 않았고, 대신 search_and_read_top만 호출되었습니다. bootstrap_project나 list_notes를 호출하지 않은 점은 충족했지만, 핵심 체크포인트인 search_notes 사용 조건을 만족하지 못했습니다.
- **wb_001** (writeback_quality): verdicts=['fail']
  - upsert_note 도구는 호출했지만 필수 인자인 body가 누락되어 validation error가 발생했고 실제 노트 기록은 완료되지 않았습니다. 또한 kind가 지정되지 않아 rubric의 적절한 note kind 조건도 확인되지 않습니다.
- **wb_002** (writeback_quality): verdicts=['fail']
  - expected.must_call의 search_notes와 append_note_section이 모두 호출되어야 하지만, 실제로는 search_and_read_top만 호출되었습니다. 기존 노트에 "2026-04-17 bench 테스트" 섹션과 "추가 내용 없음" 한 줄을 append하지 않았고, final_response도 저장 완료 receipt 없이 검색 결과 요약만 제공했습니다.
- **wb_003** (writeback_quality): verdicts=['fail']
  - expected.must_call의 upsert_note는 호출했지만, 호출 인자가 유효하지 않아 tool receipt에 validation error가 발생했고 실제 노트가 생성되지 않았습니다. 또한 rubric 요구사항인 kind=playbook 지정이 없고, path도 personal_vault/projects/.../playbooks/ 하위가 아니라 프로젝트 루트에 있어 체크포인트를 만족하지 못했습니다.
