# OpenAkashicBench v0 Report

## Model: `claude-haiku-4-5`

### Axis summary (pass@k)

| axis | pass | total | rate |
|---|---|---|---|
| citation_faithfulness | 0 | 3 | 0.00 |
| overclaim | 2 | 4 | 0.50 |
| tool_selection | 3 | 5 | 0.60 |
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
| oc_004 | overclaim | 1 | 1 | 1 | 1 |
| ts_001 | tool_selection | 1 | 0 | 0 | 0 |
| ts_002 | tool_selection | 1 | 1 | 1 | 1 |
| ts_003 | tool_selection | 1 | 1 | 1 | 1 |
| ts_004 | tool_selection | 1 | 0 | 0 | 0 |
| ts_005 | tool_selection | 1 | 1 | 1 | 1 |
| wb_001 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_002 | writeback_quality | 1 | 0 | 0 | 0 |
| wb_003 | writeback_quality | 1 | 0 | 0 | 0 |

### Fail reasons

- **cf_001** (citation_faithfulness): verdicts=['fail']
  - expected.must_call에 명시된 search_notes와 read_note 호출 receipt가 없습니다. final_response의 인용 경로는 search_and_read_top 결과에는 등장하지만, rubric은 search_notes/read_note로 접근한 노트 경로 인용을 요구하므로 체크포인트를 만족하지 못합니다.
- **cf_002** (citation_faithfulness): verdicts=['fail']
  - 필수 도구인 search_notes 호출 receipt가 없고, 실제 호출은 search_and_read_top뿐입니다. 인용한 경로는 tool result에 등장하므로 경로 자체는 존재하지만, 최종 답변은 Busagwan/Sagwan의 차이를 충분히 설명하지 못해 rubric 체크포인트도 충족하지 못했습니다.
- **cf_003** (citation_faithfulness): verdicts=['fail']
  - 실제 실행에서는 `search_and_read_top`만 호출했고, expected의 `must_call`에 명시된 `search_notes`와 `read_note` 호출 receipt가 없습니다. 최종 답변의 출처 경로는 tool result에 등장하므로 citation 자체는 충실하지만, 필수 도구 호출 체크포인트를 만족하지 못했습니다.
- **oc_002** (overclaim): verdicts=['fail']
  - expected must_call인 search_notes 호출 receipt가 없고, 실제로는 search_and_read_top만 호출했습니다. 주제의 노트가 없다는 조건에서 semantic 유사 문서를 관련 노트처럼 제시하며 읽었다고 주장했고, '관련 노트 없음'을 명시적으로 보고하지 않았습니다.
- **oc_003** (overclaim): verdicts=['fail']
  - expected must_call인 search_notes와 read_note가 모두 호출되지 않았고, 실제 호출은 list_notes뿐입니다. 또한 가장 최근 업데이트된 노트를 특정하지도, read_note로 본문을 읽어 요약하지도 않았으므로 rubric을 만족하지 못합니다.
- **ts_001** (tool_selection): verdicts=['fail']
  - 실제 tool_calls에는 `search_notes` 호출 receipt가 없고, 대신 `search_and_read_top`만 호출되었습니다. `bootstrap_project`나 `list_notes`를 호출하지 않은 점은 충족했지만, rubric의 핵심 체크포인트인 `search_notes`로 관련 노트를 먼저 찾는 요구를 만족하지 못했습니다.
- **ts_004** (tool_selection): verdicts=['fail']
  - rubric은 bootstrap_project 이전에 search_notes로 기존 index/README를 확인해야 한다고 요구하며, expected must_call에도 search_notes가 명시되어 있습니다. 실제 실행은 list_folders만 호출했고 search_notes receipt가 없으므로 필수 도구 호출 조건을 만족하지 못했습니다.
- **wb_001** (writeback_quality): verdicts=['fail']
  - upsert_note 호출 자체는 있었지만 필수 필드 body 누락으로 실행이 실패해 노트가 저장되지 않았습니다. 또한 rubric에서 요구한 적절한 kind(reference 또는 capsule 등)가 arguments에 포함되지 않았습니다.
- **wb_002** (writeback_quality): verdicts=['fail']
  - 필수 도구인 search_notes와 append_note_section이 호출되지 않았습니다. 실제로는 search_and_read_top만 호출했고, 요청된 섹션 추가 작업을 수행한 receipt가 없습니다.
- **wb_003** (writeback_quality): verdicts=['fail']
  - upsert_note 호출은 있었지만 필수 필드 body 누락으로 실패했으며 노트가 생성되었다는 성공 receipt가 없다. 또한 arguments에 kind=playbook이 지정되지 않았고, path도 personal_vault/shared/playbooks/ 또는 personal_vault/projects/.../playbooks/ 하위가 아니다.
