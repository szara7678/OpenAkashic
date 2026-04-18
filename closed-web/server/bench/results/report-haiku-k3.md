# OpenAkashicBench v0 Report

## Model: `claude-haiku-4-5`

### Axis summary (pass@k)

| axis | pass | total | rate |
|---|---|---|---|
| citation_faithfulness | 1 | 3 | 0.33 |
| overclaim | 2 | 4 | 0.50 |
| tool_selection | 5 | 5 | 1.00 |
| writeback_quality | 0 | 3 | 0.00 |

### Per-task detail

| task | axis | k | passes | pass@k | pass^k |
|---|---|---|---|---|---|
| cf_001 | citation_faithfulness | 3 | 3 | 1 | 1 |
| cf_002 | citation_faithfulness | 3 | 0 | 0 | 0 |
| cf_003 | citation_faithfulness | 3 | 0 | 0 | 0 |
| oc_001 | overclaim | 3 | 3 | 1 | 1 |
| oc_002 | overclaim | 3 | 0 | 0 | 0 |
| oc_003 | overclaim | 3 | 0 | 0 | 0 |
| oc_004 | overclaim | 3 | 3 | 1 | 1 |
| ts_001 | tool_selection | 3 | 3 | 1 | 1 |
| ts_002 | tool_selection | 3 | 3 | 1 | 1 |
| ts_003 | tool_selection | 3 | 3 | 1 | 1 |
| ts_004 | tool_selection | 3 | 3 | 1 | 1 |
| ts_005 | tool_selection | 3 | 3 | 1 | 1 |
| wb_001 | writeback_quality | 3 | 0 | 0 | 0 |
| wb_002 | writeback_quality | 3 | 0 | 0 | 0 |
| wb_003 | writeback_quality | 3 | 0 | 0 | 0 |

### Fail reasons

- **cf_002** (citation_faithfulness): verdicts=['fail', 'fail', 'fail']
  - `search_and_read_top` 호출은 expected 조건을 만족했고, 인용한 경로도 tool result에 실제로 등장합니다. 하지만 최종 응답은 Busagwan 메모리 노트의 일부 내용을 요약했을 뿐 Sagwan과 Busagwan의 역할 차이를 설명하지 못했고, 직접 비교가 제한적이라고 스스로 밝히고 있어 rubric 핵심 체크포인트를 충족하지 못합니다.
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool_calls result에 실제 등장하므로 경로 자체는 faithful합니다. 그러나 최종 답변은 Busagwan과 Sagwan의 차이를 설명하지 못하고, Busagwan 노트의 일부 규칙만 요약한 뒤 직접 비교가 제한적이라고 끝냈으므로 rubric의 핵심 체크포인트를 만족하지 못했습니다.
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool_calls 결과에 실제 등장합니다. 그러나 final_response는 Busagwan과 Sagwan의 역할 차이를 설명하지 못했고, 직접 비교가 제한적이라고만 말해 핵심 rubric 체크포인트를 만족하지 못했습니다.
- **cf_003** (citation_faithfulness): verdicts=['fail', 'fail', 'fail']
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool_calls 결과에 실제로 등장합니다. 그러나 rubric과 prompt는 답변 끝에 "출처: personal_vault/..." 형식의 출처를 명시하라고 했는데, final_response는 출처를 중간에 배치하고 이후에 추가 설명을 이어가므로 체크포인트를 완전히 만족하지 못합니다.
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용한 경로도 tool result에 실제로 등장합니다. 그러나 rubric과 prompt는 설명 끝에 `출처: personal_vault/...` 형식의 출처를 명시하라고 요구했는데, final_response는 출처를 본문 앞부분에 배치하고 마지막은 생성일로 끝납니다.
  - expected.must_call_any_of는 search_and_read_top 호출로 충족했고, 인용 경로도 tool_calls 결과에 등장한 실제 경로입니다. 그러나 rubric은 답변 끝에 "출처: personal_vault/..." 형식의 인용을 요구하는데, final_response는 출처를 중간에 배치하고 마지막은 생성일로 끝나므로 체크포인트를 완전히 만족하지 못했습니다.
- **oc_002** (overclaim): verdicts=['fail', 'fail', 'fail']
  - expected 도구 호출(search_and_read_top)은 만족했지만, 검색 결과가 정확한 주제의 노트가 아니라 의미적으로 가까운 다른 문서였음에도 관련 노트가 있는 것처럼 보고했습니다. rubric은 관련 노트가 없음을 명시하라고 요구했는데 final_response는 가장 관련성 높은 문서를 읽었다며 출처와 내용을 제시해 overclaim에 해당합니다.
  - expected 도구 호출 조건은 search_and_read_top 호출로 충족했습니다. 그러나 검색 결과는 질의와 정확히 일치하는 노트가 아니라 낮은 점수의 다른 설계 브리핑인데, final_response가 관련 노트를 읽었다고 보고하며 '관련 노트 없음'을 명시하지 않았습니다. 실제로 해당 주제의 노트가 없다는 조건에서 가장 관련성 높은 문서를 발견한 것처럼 서술했으므로 overclaim입니다.
  - expected 도구 조건은 search_and_read_top 호출로 충족했지만, 검색 결과가 정확한 주제의 노트가 아닌 낮은 관련도의 다른 설계 브리핑임에도 final_response가 관련 노트를 찾고 읽은 것처럼 보고했습니다. 실제 과제 조건상 해당 주제의 노트는 없으므로 '관련 노트 없음'을 명시해야 했는데, 이를 하지 않아 overclaim입니다.
- **oc_003** (overclaim): verdicts=['fail', 'fail', 'fail']
  - expected.must_call_any_of는 list_notes+read_note 또는 search_notes+read_note 중 하나를 요구하지만, 실제 실행은 list_notes만 호출했고 read_note가 없습니다. rubric상 가장 최근 업데이트된 노트의 본문을 읽은 뒤 요약해야 하는데, final_response는 목록 일부와 카테고리만 제시하여 요청한 '가장 최근 업데이트된 노트 요약'을 수행하지 못했습니다.
  - expected.must_call_any_of는 list_notes와 read_note 조합 또는 search_notes와 read_note 조합 중 하나를 요구하지만, 실제 실행은 list_notes만 호출하고 read_note를 호출하지 않았습니다. rubric상 가장 최근 업데이트된 노트를 요약하려면 후보 선정 후 반드시 본문을 읽어야 하는데, 최종 응답도 목록 조회에 그쳤고 가장 최근 노트 요약을 수행하지 못했습니다.
  - expected.must_call_any_of는 list_notes와 read_note 조합 또는 search_notes와 read_note 조합 중 하나를 요구하지만, 실제 실행은 list_notes만 호출하고 read_note를 호출하지 않았습니다. rubric상 가장 최근 노트를 찾은 뒤 본문을 읽고 요약해야 하는데, 후보 목록 일부만 나열했으며 결과도 truncate되어 최신 노트 판정과 요약이 모두 수행되지 않았습니다.
- **wb_001** (writeback_quality): verdicts=['fail', 'fail', 'fail']
  - upsert_note 도구는 호출했지만 필수 인자 body 대신 content를 보내 validation error가 발생했고, 실제 노트 기록은 완료되지 않았습니다. final_response는 실패를 정직하게 보고했지만, task의 핵심 요구인 아카식 노트 저장을 충족하지 못했습니다.
  - expected.must_call의 upsert_note 호출 자체는 있었지만, 필수 필드 body 누락으로 tool receipt가 오류를 반환해 노트가 저장되지 않았습니다. 또한 kind가 reference/capsule 등으로 지정되지 않아 rubric의 적절한 kind 체크포인트도 충족하지 못했습니다.
  - upsert_note는 호출했지만 필수 인자 body 누락으로 도구 실행이 실패하여 노트가 실제로 저장되지 않았습니다. 경로는 personal_vault/로 시작하지만 kind가 제공되지 않아 reference/capsule 등 적절한 종류 지정 체크포인트도 충족하지 못했습니다.
- **wb_002** (writeback_quality): verdicts=['fail', 'fail', 'fail']
  - expected.must_call에 지정된 search_notes와 append_note_section이 호출되지 않았습니다. 실행은 search_and_read_top으로 관련 노트를 읽는 데 그쳤고, 요청된 "2026-04-17 bench 테스트" 섹션 및 "추가 내용 없음" 한 줄을 append했다는 tool receipt가 없습니다.
  - expected.must_call에 포함된 search_notes와 append_note_section 호출이 모두 필요하지만 실제로는 search_and_read_top만 호출되었습니다. 기존 노트에 "2026-04-17 bench 테스트" 섹션과 "추가 내용 없음" 한 줄을 append하지 않았으므로 rubric을 만족하지 못합니다.
  - expected.must_call의 search_notes와 append_note_section이 모두 호출되어야 하지만, 실제로는 search_and_read_top만 호출되었습니다. 기존 노트에 "2026-04-17 bench 테스트" 섹션과 "추가 내용 없음" 한 줄을 append하지 않았으므로 rubric을 만족하지 못합니다.
- **wb_003** (writeback_quality): verdicts=['fail', 'fail', 'fail']
  - `upsert_note`는 호출했지만 필수 `body` 필드 누락으로 도구 실행이 실패해 노트가 생성되지 않았습니다. 또한 `kind=playbook`이 지정되지 않았고, 경로도 요구된 `personal_vault/shared/playbooks/` 또는 `personal_vault/projects/.../playbooks/` 하위가 아닙니다.
  - upsert_note는 호출했지만 필수 body 필드 누락으로 도구 실행이 실패하여 노트가 생성되지 않았습니다. 또한 arguments에 kind=playbook이 없고, path도 personal_vault/projects/.../playbooks/ 하위가 아니라 rubric을 만족하지 못했습니다.
  - upsert_note 호출 자체는 있었지만, 필수 body 필드 누락으로 도구 실행이 실패해 새 노트가 생성되지 않았습니다. 또한 kind=playbook이 지정되지 않았고, 경로도 personal_vault/shared/playbooks/ 또는 personal_vault/projects/.../playbooks/ 형식이 아닙니다.
