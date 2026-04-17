---
title: agent-design-patterns
kind: reference
project: openakashic
status: active
confidence: high
tags: []
related: []
visibility: private
created_by: aaron
owner: aaron
publication_status: rejected
updated_at: 2026-04-15T09:47:55Z
created_at: 2026-04-15T02:10:32Z
publication_requested_at: 2026-04-15T02:11:55Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:55Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
**Reason: "**"
*   **근거 부족: "** 요청서에 명시적인 배포 근거(Rationale)가 누락되었으며, 관련 증거 경로(Evidence Paths)가 없습니다. 이는 내부 정책 준수 측면에서 보완이 필요합니다."
*   **프로세스 미준수: "** 라이브러리 체크리스트에 따라, 사설 소스(private)를 직접 노출하기보다 반드시 공개용 캡슐(public capsule)을 생성하거나 업데이트하는 과정이 선행되어야 합니다."
*   **내용 품질: "** 문서 자체의 완성도와 전문성은 매우 높습니다. (워크플로우 vs 에이전트 구분, 5가지 패턴의 트레이드오프 분석 등) 따라서 내용 검토는 통과되었으나, 배포 프로세스 검증이 필요합니다."
**Review Summary: "**"
---

## Summary
LLM 에이전트 설계 패턴 레퍼런스. Anthropic "Building Effective Agents" 5가지 패턴 + 실전 적용 기준. 워크플로우 vs 에이전트 구분, 패턴별 트레이드오프, 프로덕션 배포 체크리스트. 2025 기준.

## Sources
- Anthropic "Building Effective Agents" (2024)
- Anthropic Claude Agent SDK 문서
- AI Engineer Summit 2024 발표 내용
- LLM Agent 실전 운영 경험 종합

---

## 1. 핵심 개념: 워크플로우 vs 에이전트

```
워크플로우 (Workflow)
  - LLM 호출 경로가 코드로 미리 정해져 있음
  - 예: A → B → C 순서 고정
  - 예측 가능, 디버그 쉬움
  - 단순·반복·고정 로직에 적합

에이전트 (Agent)
  - LLM이 스스로 다음 행동을 결정
  - 도구를 언제·어떻게 쓸지 모델이 판단
  - 유연하지만 비결정론적
  - 복잡·모호·탐색이 필요한 태스크에 적합
```

**선택 기준**: "LLM 없이도 같은 로직을 if/else로 표현할 수 있다면 워크플로우."

---

## 2. 5가지 설계 패턴

### 2-1. 프롬프트 체이닝 (Prompt Chaining)

```
Input → [LLM 1] → 중간 출력 → [LLM 2] → 최종 출력
```

**언제**: 태스크가 명확히 분리된 순차적 단계로 구성될 때.
- 글 초안 작성 → 문체 교정 → 번역
- 코드 생성 → 테스트 작성 → 문서화

**장점**: 단계별 검증 가능. 각 LLM 호출의 컨텍스트를 좁힐 수 있음.
**단점**: 오류가 하위 단계로 전파됨. 전체 지연 시간 = 각 단계 합산.

```python
def chain(input_text):
    draft = llm("초안 작성: " + input_text)
    edited = llm("문체 교정: " + draft)
    translated = llm("한국어 번역: " + edited)
    return translated
```

---

### 2-2. 라우팅 (Routing)

```
Input → [분류 LLM] → 경로 A / 경로 B / 경로 C
```

**언제**: 입력 타입에 따라 전혀 다른 처리가 필요할 때.
- 고객 문의 → 기술 지원 / 결제 문의 / 일반 문의
- 코드 → 언어별 특화 모델 (Python vs Go vs Rust)

**장점**: 각 경로를 독립적으로 최적화. 복잡한 시스템을 전문화된 서브시스템으로 분해.
**단점**: 분류 오류 시 전체 실패. 경계가 모호한 케이스 처리 필요.

```python
def route(input_text):
    category = llm(f"분류 (tech/billing/general): {input_text}")
    handlers = {
        "tech": handle_tech,
        "billing": handle_billing,
        "general": handle_general,
    }
    return handlers.get(category, handle_general)(input_text)
```

---

### 2-3. 병렬화 (Parallelization)

두 가지 하위 유형:

**섹셔닝 (Sectioning)**: 독립적인 서브태스크를 동시 실행
```
Input → [LLM A] ─┐
       → [LLM B] ─┤→ 집계 → Output
       → [LLM C] ─┘
```

**투표 (Voting)**: 동일 태스크를 여러 번 실행 후 다수결
```
Input → [LLM 1] ─┐
       → [LLM 2] ─┤→ Majority Vote → Output
       → [LLM 3] ─┘
```

**언제 섹셔닝**: 긴 문서를 청크별로 분석, 여러 관점(보안/성능/유지보수) 동시 평가.
**언제 투표**: 정확도가 중요한 분류, 코드 보안 검토, 의료 진단 보조.

**실전 주의**: 비용이 선형 증가. 투표는 홀수 개(3, 5) 실행이 다수결에 유리.

---

### 2-4. 오케스트레이터-서브에이전트 (Orchestrator-Subagents)

```
[오케스트레이터 LLM]
    ↓ 계획 수립
    ├→ [서브에이전트 1: 코드 작성]
    ├→ [서브에이전트 2: 테스트 실행]
    └→ [서브에이전트 3: 문서 생성]
    ↓ 결과 통합
```

**언제**: 복잡한 태스크가 여러 전문화된 능력을 요구할 때. 각 서브에이전트가 독립 컨텍스트/도구 집합을 사용.

**핵심 설계 원칙**:
- 오케스트레이터는 계획·통합에 집중, 실행은 서브에이전트에 위임
- 서브에이전트 간 의존성 최소화 (병렬 가능하게)
- 각 서브에이전트에게 명확한 성공 기준 제공

```python
class Orchestrator:
    def run(self, task):
        plan = self.llm(f"태스크를 서브태스크로 분해: {task}")
        results = {}
        for subtask in plan.subtasks:
            agent = self.get_agent(subtask.type)
            results[subtask.id] = agent.execute(subtask)
        return self.llm(f"결과 통합: {results}")
```

---

### 2-5. 평가-최적화 루프 (Evaluator-Optimizer)

```
[생성 LLM] → 출력
     ↑            ↓
     └── [평가 LLM] ← 기준
```

**언제**: "충분히 좋은" 출력을 얻기까지 반복이 필요할 때. 명확한 품질 기준이 존재할 때.

**실전 패턴**:
```python
def generate_with_eval(task, max_iterations=3):
    output = generator_llm(task)
    for i in range(max_iterations):
        evaluation = evaluator_llm(
            f"출력: {output}\n기준: {CRITERIA}\n합격 여부 + 개선점:"
        )
        if evaluation.passed:
            return output
        output = generator_llm(f"개선 지시: {evaluation.feedback}\n원본: {output}")
    return output  # 최대 반복 후 반환
```

**주의**: 무한 루프 방지를 위해 반드시 `max_iterations` 설정. 평가 LLM이 생성 LLM보다 강력해야 의미 있음.

---

## 3. 패턴 선택 가이드

| 상황 | 추천 패턴 |
|---|---|
| 단계가 명확히 분리된 파이프라인 | 체이닝 |
| 입력 타입에 따라 처리 분기 | 라우팅 |
| 독립 서브태스크 병렬 처리 | 병렬화 (섹셔닝) |
| 정확도 중요한 단일 태스크 | 병렬화 (투표) |
| 복잡한 목표, 여러 전문 도구 필요 | 오케스트레이터 |
| 출력 품질 반복 개선 필요 | 평가-최적화 루프 |
| 실시간 상호작용, 미지의 단계 수 | 풀 에이전트 |

---

## 4. 에이전트 루프 (Full Agent)

```
사용자 입력
    ↓
[LLM — Think]
    ↓ tool_use 블록
[도구 실행]
    ↓ tool_result
[LLM — Think again]
    ↓ (반복) 또는 text 응답
최종 출력
```

**Claude tool_use 흐름**:
```python
messages = [{"role": "user", "content": task}]
while True:
    response = client.messages.create(
        model="claude-opus-4-6",
        tools=TOOLS,
        messages=messages,
    )
    if response.stop_reason == "end_turn":
        break
    # 도구 호출 처리
    tool_results = execute_tools(response.content)
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})
```

**핵심 설계 결정**:
- **도구 granularity**: 너무 세분화 → 많은 반복. 너무 큰 도구 → 유연성 손실.
- **컨텍스트 관리**: 긴 루프에서 오래된 tool_result를 요약/제거.
- **탈출 조건**: end_turn 외에 max_steps, timeout 필수.
- **에러 처리**: 도구 실패 시 재시도 vs 포기 전략 명시.

---

## 5. 프로덕션 에이전트 체크리스트

### 안전성
- [ ] 최대 반복 횟수 (max_steps) 설정
- [ ] 실행 시간 타임아웃 설정
- [ ] 되돌릴 수 없는 작업(삭제·결제·이메일 발송)에 인간 확인 게이트
- [ ] 도구 권한 최소화 (필요한 것만)

### 관찰 가능성
- [ ] 모든 LLM 호출 로깅 (입력·출력·지연·비용)
- [ ] 도구 호출 추적 (어떤 도구를 몇 번 사용했는가)
- [ ] 실패 유형 분류 (도구 오류 / 논리 오류 / 지시 불이행)
- [ ] Langfuse 또는 동등 도구로 트레이스 수집

### 평가
- [ ] 골든 셋 정의 (입력-기대 출력 쌍)
- [ ] 정확도 외 효율성 지표 (평균 단계 수, 평균 비용)
- [ ] 회귀 테스트 자동화

### 비용 관리
- [ ] 모델 계층화: 라우팅·평가는 Haiku, 복잡 추론은 Opus
- [ ] 캐싱: 시스템 프롬프트·도구 정의에 prompt caching 적용
- [ ] 컨텍스트 압축: 긴 루프에서 중간 요약 삽입

---

## 6. 흔한 실수

| 실수 | 결과 | 해결 |
|---|---|---|
| 에이전트를 너무 일찍 도입 | 복잡성 폭증, 디버그 불가 | 워크플로우로 시작, 필요할 때만 에이전트화 |
| 도구 설명 불충분 | 잘못된 도구 선택 | 도구마다 파라미터·예제·실패 조건 명시 |
| 컨텍스트 무한 증가 | 토큰 한도 초과, 성능 저하 | 중간 요약 또는 sliding window |
| 에러 핸들링 없음 | 단일 도구 실패로 전체 루프 붕괴 | 각 도구에 재시도·fallback 로직 |
| 인간 개입 없음 | 되돌릴 수 없는 작업 수행 | 위험 행동에 human-in-the-loop |

---

## Reuse
- 새 에이전트 설계 시: 패턴 선택 가이드 표부터 확인.
- "에이전트가 필요한가?" 판단 기준: 단계 수를 미리 알 수 없거나, 필요한 도구가 동적으로 결정될 때만 진짜 에이전트.
- 항상 가장 단순한 패턴에서 시작해서 실제 한계를 만났을 때 복잡도를 높일 것.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [Anthropic — Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- [ReAct paper](https://arxiv.org/abs/2210.03629)
