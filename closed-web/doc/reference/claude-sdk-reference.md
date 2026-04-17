---
title: claude-sdk-reference
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
created_at: 2026-04-15T02:14:04Z
publication_requested_at: 2026-04-15T02:14:11Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:55Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
**Recommendation: "** reviewing"
**Reason: "**"
1.  **[필수] 근거 및 목적 명시: "** 요청서 본문에 작성 이유(Rationale)가 전무합니다. 해당 문서가 왜 필요한지, 어떤 문제를 해결하는지 명확히 작성해야 합니다."
2.  **[필수] 증거 경로 확보: "** `Evidence Paths`가 비어 있습니다. 문서의 신뢰성을 뒷받침하는 구체적인 출처(API 스펙, 공식 문서 링크 등)를 명시적으로 연결해야 합니다."
3.  **[프로세스] 아카이브 준수: "** 내용 자체는 매우 훌륭하고 실용적이지만, 요청서가 `private` 소스를 `public`으로 노출하는 방식이므로, 반드시 **파생된 공개 캡슐(derived public capsule)**을 생성하는 절차를 거쳐야 합니다. (Librarian Checklist 항목 준수 필요)"
---

## Summary
Anthropic Claude SDK 실전 레퍼런스. Python SDK 중심. 기본 호출·스트리밍·tool_use·멀티턴·prompt caching·토큰 제어·에러 처리 패턴. 2025 기준 claude-sdk-python v0.40+.

## Sources
- Anthropic Python SDK (github.com/anthropics/anthropic-sdk-python)
- Anthropic API 공식 문서 (docs.anthropic.com)
- claude-code-sdk 문서

---

## 1. 설치 & 초기화

```bash
pip install anthropic
```

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-ant-...",  # 또는 ANTHROPIC_API_KEY 환경변수
)
```

---

## 2. 기본 메시지 생성

```python
message = client.messages.create(
    model="claude-opus-4-6",        # 최신 최고 성능
    # model="claude-sonnet-4-6",    # 균형 (비용·속도·품질)
    # model="claude-haiku-4-5-20251001",  # 경량·저비용
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Explain MCP in one paragraph."}
    ]
)

print(message.content[0].text)
print(f"Input tokens: {message.usage.input_tokens}")
print(f"Output tokens: {message.usage.output_tokens}")
```

---

## 3. 시스템 프롬프트

```python
message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    system="You are a senior Go engineer. Respond only in Go code examples.",
    messages=[{"role": "user", "content": "Show me a concurrent HTTP server."}]
)
```

---

## 4. 멀티턴 대화

```python
messages = []

def chat(user_input: str) -> str:
    messages.append({"role": "user", "content": user_input})
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=messages,
    )
    assistant_msg = resp.content[0].text
    messages.append({"role": "assistant", "content": assistant_msg})
    return assistant_msg
```

---

## 5. 스트리밍

```python
with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Write a haiku about async Rust."}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
    print()  # 줄바꿈

# 최종 메시지 (사용량 포함)
final_message = stream.get_final_message()
print(f"Total tokens: {final_message.usage.input_tokens + final_message.usage.output_tokens}")
```

---

## 6. Tool Use (Function Calling)

### 6-1. 도구 정의 & 기본 루프

```python
import json

TOOLS = [
    {
        "name": "get_weather",
        "description": "주어진 도시의 현재 날씨를 반환한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "도시 이름 (영문)"},
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "온도 단위",
                    "default": "celsius"
                }
            },
            "required": ["city"]
        }
    }
]

def get_weather(city: str, unit: str = "celsius") -> dict:
    # 실제 API 호출 대신 더미 반환
    return {"city": city, "temp": 22, "unit": unit, "condition": "맑음"}

messages = [{"role": "user", "content": "서울 날씨 알려줘"}]

while True:
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=TOOLS,
        messages=messages,
    )

    messages.append({"role": "assistant", "content": resp.content})

    if resp.stop_reason == "end_turn":
        # 최종 텍스트 응답
        for block in resp.content:
            if block.type == "text":
                print(block.text)
        break

    # tool_use 블록 처리
    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            fn = {"get_weather": get_weather}.get(block.name)
            result = fn(**block.input) if fn else {"error": "unknown tool"}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    messages.append({"role": "user", "content": tool_results})
```

### 6-2. tool_choice 제어

```python
# 특정 도구 강제 사용
client.messages.create(
    ...,
    tool_choice={"type": "tool", "name": "get_weather"}
)

# 도구 자동 선택 (기본)
tool_choice={"type": "auto"}

# 도구 사용 금지
tool_choice={"type": "none"}
```

---

## 7. Prompt Caching

자주 재사용되는 긴 콘텐츠(시스템 프롬프트, 문서)에 cache_control을 붙이면 약 90% 비용 절감.

```python
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "당신은 전문 Python 엔지니어입니다. " + LONG_CODEBASE_CONTEXT,
            "cache_control": {"type": "ephemeral"},  # 5분 TTL 캐시
        }
    ],
    messages=[{"role": "user", "content": "버그를 찾아줘"}]
)

# cache_creation_input_tokens, cache_read_input_tokens 확인
print(message.usage)
```

**캐시 조건**: 1024 토큰 이상이어야 캐시 대상. 대화 중 변하지 않는 내용에 사용.

---

## 8. 이미지 입력

```python
import base64

with open("diagram.png", "rb") as f:
    image_data = base64.b64encode(f.read()).decode()

message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[{
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_data,
                }
            },
            {"type": "text", "text": "이 다이어그램을 설명해줘"}
        ]
    }]
)
```

---

## 9. 구조화된 출력 (JSON)

```python
from pydantic import BaseModel
import json

class AnalysisResult(BaseModel):
    sentiment: str
    confidence: float
    keywords: list[str]
    summary: str

resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=512,
    system="항상 JSON으로만 응답한다. 스키마: {sentiment, confidence, keywords, summary}",
    messages=[{"role": "user", "content": f"분석: {text}"}]
)

result = AnalysisResult(**json.loads(resp.content[0].text))
```

**더 안정적인 방법**: tool_use를 "강제 JSON 파서"로 활용
```python
# tool_choice로 특정 도구를 강제하면 항상 input_schema 구조로 출력
resp = client.messages.create(
    tools=[analysis_tool],
    tool_choice={"type": "tool", "name": "analyze"},
    ...
)
result = resp.content[0].input  # 이미 dict
```

---

## 10. 에러 처리

```python
from anthropic import APIError, RateLimitError, APIConnectionError
import time

def safe_create(client, **kwargs):
    for attempt in range(3):
        try:
            return client.messages.create(**kwargs)
        except RateLimitError:
            time.sleep(2 ** attempt)
        except APIConnectionError:
            time.sleep(1)
        except APIError as e:
            if e.status_code == 529:  # Overloaded
                time.sleep(5)
            else:
                raise
    raise RuntimeError("Max retries exceeded")
```

---

## 11. Async 사용

```python
import asyncio
import anthropic

async def main():
    client = anthropic.AsyncAnthropic()
    
    # 병렬 호출
    tasks = [
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": q}]
        )
        for q in questions
    ]
    results = await asyncio.gather(*tasks)
    return [r.content[0].text for r in results]

asyncio.run(main())
```

---

## 12. 모델 선택 기준 (2025)

| 모델 | ID | 용도 | 비용 |
|---|---|---|---|
| Claude Opus 4.6 | `claude-opus-4-6` | 복잡한 추론·코드·에이전트 | 높음 |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 균형, 대부분의 프로덕션 | 중간 |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 빠른 분류·라우팅·간단 태스크 | 낮음 |

**계층화 전략**: 라우팅은 Haiku → 복잡 태스크는 Sonnet → 정밀 추론은 Opus.

---

## 13. 토큰 추정 (사전 계산)

```python
# 실제 API 호출 전 토큰 수 확인
response = client.messages.count_tokens(
    model="claude-sonnet-4-6",
    system="system prompt",
    messages=[{"role": "user", "content": "your message"}]
)
print(f"예상 입력 토큰: {response.input_tokens}")
```

---

## Reuse
- 도구 정의는 `input_schema`를 JSON Schema 형식으로 정확히 작성해야 모델이 올바르게 사용.
- 프롬프트 캐싱은 시스템 프롬프트 + 긴 문서를 함께 캐시하는 것이 비용 효과 최대.
- 에이전트 루프에서 `stop_reason == "tool_use"`가 될 때까지만 도구를 처리, `end_turn`에서 종료.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Claude Agent SDK](https://docs.anthropic.com/en/api/agent-sdk)
