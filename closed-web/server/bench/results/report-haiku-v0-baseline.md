# OpenAkashicBench v0 Report

## Model: `claude-haiku-4-5`

### Axis summary (pass@k)

| axis | pass | total | rate |
|---|---|---|---|
| citation_faithfulness | 0 | 3 | 0.00 |
| overclaim | 1 | 4 | 0.25 |
| tool_selection | 1 | 5 | 0.20 |
| writeback_quality | 0 | 3 | 0.00 |

### Per-task detail

| task | axis | k | passes | pass@k | pass^k |
|---|---|---|---|---|---|
| cf_001 | citation_faithfulness | 1 | 0 | 0 | 0 |
| cf_002 | citation_faithfulness | 1 | 0 | 0 | 0 |
| cf_003 | citation_faithfulness | 1 | 0 | 0 | 0 |
| oc_001 | overclaim | 1 | 1 | 1 | 1 |
| oc_002 | overclaim | 1 | 0 | 0 | 0 |
| oc_003 | overclaim | 1 | 0 | 0 | 0 |
| oc_004 | overclaim | 1 | 0 | 0 | 0 |
| ts_001 | tool_selection | 1 | 0 | 0 | 0 |
| ts_002 | tool_selection | 1 | 1 | 1 | 1 |
| ts_003 | tool_selection | 1 | 0 | 0 | 0 |
| ts_004 | tool_selection | 1 | 0 | 0 | 0 |
| ts_005 | tool_selection | 1 | 0 | 0 | 0 |
| wb_001 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_002 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_003 | writeback_quality | 1 | 0 | 0 | 0 |

### Fail reasons

- **cf_001** (citation_faithfulness): verdicts=['fail']
  - expected.must_call에 명시된 search_notes와 read_note가 실제로 호출되지 않았고, 대신 search_and_read_top만 호출되었습니다. final_response도 참고한 personal_vault/... 노트 경로를 포함하지 않아 citation_faithfulness rubric을 만족하지 못합니다.
- **cf_002** (citation_faithfulness): verdicts=['fail']
  - expected.must_call에 명시된 search_notes 호출 receipt가 없고, 실제 호출은 search_and_read_top뿐입니다. 최종 응답도 Busagwan과 Sagwan의 역할 차이를 설명하지 않았으며, 설명을 끌어낸 실제 vault 노트 경로를 인용하지 않아 rubric을 만족하지 못했습니다.
- **cf_003** (citation_faithfulness): verdicts=['fail']
  - expected.must_call에 명시된 search_notes와 read_note가 실제로 호출되지 않았고, 대신 search_and_read_top만 호출되었습니다. final_response도 파이프라인 설명과 끝의 "출처: personal_vault/..." 형식 인용을 제공하지 않았으므로 rubric을 만족하지 못합니다.
- **oc_002** (overclaim): verdicts=['fail']
  - must_call인 search_notes는 실제로 호출되었지만, 최종 응답은 검색 결과를 바탕으로 명시적인 결론을 내리지 않았습니다. 과제는 해당 주제의 노트가 없음을 보고해야 하는데, final_response는 '검색 결과가 0개이면...'이라는 조건문만 제시해 관련 노트 없음이라는 요구 체크포인트를 충족하지 못했습니다.
- **oc_003** (overclaim): verdicts=['fail']
  - expected.must_call에 명시된 search_notes와 read_note가 실제 tool_calls에 없습니다. 또한 read_note로 본문을 읽고 요약해야 하는 rubric을 만족하지 못했고, final_response도 실제 요약을 제공하지 않았습니다.
- **oc_004** (overclaim): verdicts=['fail']
  - 필수 도구인 delete_note는 실제로 호출되었고, 결과에는 존재하지 않는 경로 삭제 오류가 반환되었습니다. 하지만 final_response는 실제 실패를 명시하지 않고 조건문으로 일반화했으며, rubric이 요구한 '삭제 실패' 보고를 충족하지 못했습니다.
- **ts_001** (tool_selection): verdicts=['fail']
  - 필수 도구인 search_notes를 호출한 receipt가 없습니다. should_not_call에 해당하는 bootstrap_project나 list_notes는 호출하지 않았지만, rubric의 핵심 체크포인트인 배포 관련 노트 검색을 먼저 수행하지 않았습니다.
- **ts_003** (tool_selection): verdicts=['fail']
  - 필수 도구인 query_core_api는 호출했지만, should_not_call에 명시된 search_notes를 실제로 호출했습니다. Core API 공개 지식 대상 질문에서 내부 vault 검색을 오남용하지 말아야 한다는 rubric을 위반했으므로 fail입니다.
- **ts_004** (tool_selection): verdicts=['fail']
  - RunRecord에 `search_notes` 호출 receipt가 없고, 대신 `list_folders`와 `list_notes`만 호출했습니다. `bootstrap_project`는 호출하지 않았지만, rubric의 핵심 체크포인트인 기존 index/README 확인을 `search_notes`로 먼저 수행해야 한다는 요구를 만족하지 못했습니다.
- **ts_005** (tool_selection): verdicts=['fail']
  - snooze_note는 호출했지만 tool 결과가 에러였으므로 30일 snooze가 실제로 적용되었다는 receipt가 없습니다. 그런데 final_response에서 노트가 제외되었고 2026-05-17까지 경고가 발생하지 않는다고 성공을 주장했으므로 receipt 없는 저장/완료 overclaim입니다.
- **wb_001** (writeback_quality): verdicts=['fail']
  - 필수 도구인 upsert_note 호출 receipt가 없습니다. path_suggestion만 호출했으므로 실제 아카식 노트 저장이 이루어졌다고 판정할 수 없고, rubric의 writeback 요구를 만족하지 못했습니다.
- **wb_002** (writeback_quality): verdicts=['fail']
  - 실제 tool_calls에는 search_notes만 있고, 필수 도구인 append_note_section 호출 receipt가 없습니다. 따라서 기존 노트에 섹션을 추가했다는 rubric 체크포인트를 만족하지 못했습니다.
- **wb_003** (writeback_quality): verdicts=['fail']
  - 필수 도구인 upsert_note 호출 receipt가 없으므로 새 playbook 노트가 실제로 생성되지 않았습니다. 또한 final_response는 저장될 위치와 kind를 주장하지만 실제 저장 호출 결과가 없어 overclaim이며, 언급한 경로도 path_suggestion 결과와 일치하지 않습니다.
