# OpenAkashic

**상황과 목적에 맞는 노하우를 찾고, 정확한 방법 버전의 적용 결과·의견·정정을 함께 읽는 공개 노하우 아카이브**입니다.

일반 백과사전이나 뉴스 수집 서비스가 아닙니다. 공개 문서는 방법의 절차·조건·성공 기준·한계를 뒷받침하는 출처로 사용합니다. 출처의 설명, 운영자가 정리한 방법, 실행자의 결과 보고, 독립 검증을 구분합니다. 그래프의 연결이나 보고된 성공은 효과의 증명이 아닙니다.

사람은 [공개 서비스](https://knowledge.openakashic.com/)의 아틀라스에서 방법과 연결된 출처·경험을 살펴보고, [상황·목적 검색](https://knowledge.openakashic.com/research/methods/library/)에서 후보를 찾습니다. `/`와 `/graph`는 노하우 아틀라스 진입점입니다. 에이전트는 같은 방법 ID와 버전을 HTTP API로 읽습니다.

공개 서비스는 **익명 읽기·검색 전용**입니다. 가입, 공개 투고, 공개 리뷰 제출, claim 승인 절차는 제공하지 않습니다. 소유자만 별도 로컬·비공개 writer에 인증된 API로 방법·결과·의견·버전·정정을 기록합니다. Closed Akashic의 비공개 원문·개인 기억은 별도 시스템이며 이 서비스로 읽거나 동기화하지 않습니다.

## 지도로 탐험하기

첫 화면은 창 크기에 맞는 전체 그래프입니다. 노드를 선택하면 지도를 유지한 채 데스크톱에서는 오른쪽 패널, 모바일에서는 하단 패널이 열립니다.

- **둘러보기:** 관심 주제 칩을 고르거나 ‘다른 길 발견’으로 현재 조건에서 아직 읽지 않은 방법을 엽니다. 새 정보나 추천 근거를 만들어 내는 기능은 아닙니다.
- **따라가기:** 상세 패널의 연결된 기록과 ‘지나온 연결’을 누릅니다. 클릭만으로 전체 지도가 바뀌지 않으며 ‘이 주변만 보기’를 선택할 때만 연결 범위를 좁힙니다.
- **조작:** 휠·두 손가락으로 확대, 빈 공간을 끌어 이동, 점을 끌어 배치합니다. 화면 맞춤, 이름 표시, 움직임 끄기, 밝은 테마도 제공합니다.
- **키보드:** `/` 검색, Tab·Enter 노드 선택, 방향키 이동, `+`·`-` 확대, Home 화면 맞춤, Esc 패널 닫기. 모바일 상세 패널은 ‘크게 읽기’와 ‘지도와 함께’를 전환합니다.

주제 색과 선은 저장된 분류·관계를 표시합니다. 노드 배치나 가까운 거리가 의미적 동등성·효과·독립 검증을 뜻하지는 않습니다. 지도 조작은 브라우저 안에서만 이루어지며 서버 기록을 수정하지 않습니다.

## 먼저 사용하기

```sh
BASE=https://knowledge.openakashic.com
curl --fail --user-agent 'OpenAkashic-Reader/1.0' --get \
  "$BASE/research/api/methods/search" \
  --data-urlencode 'situation=SQLite 데이터베이스 백업' \
  --data-urlencode 'goal=원본을 보존하고 복구 확인' \
  --data-urlencode 'mode=lexical' --data 'limit=5'
curl --fail --user-agent 'OpenAkashic-Reader/1.0' \
  "$BASE/research/api/methods/catalog?limit=12"
```

검색 결과의 ID로 `GET /research/api/methods/{method_id}`를 읽고 조건·전체 절차·한계를 확인합니다. `context`는 짧은 참조 팩, `bundle`은 예산 내 완전한 방법 팩입니다. 생략·잘림 표시를 확인하고, 실제 적용은 별도로 승인된 작업에서 수행합니다. `semantic`·`hybrid`는 운영자 임베딩 서비스와 일치하는 인덱스가 있어야 합니다. 점수는 관련성 신호이며 성공 확률이 아닙니다.

- [에이전트 사용법](llms-install.md)
- [API 계약·운영 제한·과거 평가](docs/public-methods.md)
- [설치·소유자 쓰기·백업과 복구](docs/knowhow-operations.md)
- [완전한 방법 팩](docs/method-bundles.md), [선택적 원출처 근거](docs/method-evidence.md)

## 측정한 것과 남은 한계

별도 노하우 검색 프로토타입에서 같은 자료의 합성 32개 기록·10개 과제를 사용한 한 번의 비맹검 비교에서 full 조건의 성공은 **5/10 → 9/10**이었습니다. 모델 총 토큰 사용량은 **8,287 → 10,997토큰(+32.7%)**으로 늘었습니다. 이는 현재 배포 그래프나 실제 업무 효용의 검증이 아니며 독립 사용자 검증, 일반적 품질 향상, 비용 절감의 증거가 아닙니다. 원출처를 미리 제공한 별도 평가는 입력 조건과 비교 기준이 다르므로 이 수치와 합치지 않습니다.

기존 디자인·실행·검색 평가에는 동률과 실패도 있습니다. [방법 계약의 평가 기록](docs/public-methods.md), [디자인 평가](docs/method-design-evaluation.md), `benchmarks/`의 원래 프로토콜과 결과를 보존합니다. 저장량·HTTP 성공·테스트 통과를 사용자 효용이나 정확도로 환산하지 않습니다.

이전 일반 지식 그래프·뉴스·시간 조회·capsule/MCP 문서는 역사적 기록입니다. 현재 노하우 서비스의 설치·조회·입력 경로가 아닙니다. 2026-11-06 KST 운영 영수증은 공개 legacy 노트 1,652개·연결 1,816개 보관과 전체 SQLite 스냅샷 무결성 확인을 기록합니다. 새 활성 DB는 방법 61개·결과 10개·의견 10개를 담고 일반 지식을 복사하지 않았습니다. 원본·개인 vault는 별도로 보존합니다. 공개 첫 화면과 그래프 전환, 외부 쓰기 차단, 백업 노트 재구성 및 SQLite 복구 복사본의 무결성까지 확인했습니다. 옛 일반 지식 서비스를 다시 공개하는 복원은 수행하지 않았습니다.

## 로컬 실행

Python 3.11 이상, POSIX 셸 기준입니다. 배포받은 이 디렉터리에서 실행합니다. 공개 저장소가 모노레포라면 `public-methods/` 디렉터리입니다.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r api/requirements-public.txt
# 외부의 새 절대 경로를 지정합니다. DB와 키를 Git에 넣지 마세요.
export OPENAKASHIC_RESEARCH_DB=/absolute/external/path/methods.sqlite3
export OPENAKASHIC_RESEARCH_READ_ONLY=0
cd api
python -c 'from app.research_methods import method_store; method_store()'
OPENAKASHIC_RESEARCH_READ_ONLY=1 python -m uvicorn app.methods_main:app --host 127.0.0.1 --port 18184
```

브라우저에서 `http://127.0.0.1:18184/`를 엽니다. 새 DB는 비어 있습니다. 운영 자료·비밀키·모델 가중치는 포함하지 않습니다. 읽기 전용 모드는 이미 초기화된 스키마가 필요합니다. 자세한 쓰기 설정과 복구 순서는 [운영 가이드](docs/knowhow-operations.md)를 따릅니다. 기본 `api/Dockerfile`, `app.main`, 옛 설치 스크립트는 노하우 전용 실행 명령을 대신하지 않습니다.

## 저장소 작업

`api/app/methods_main.py`가 노하우 전용 진입점이고, `api/app/research_method*`가 방법 저장·검색 구현입니다. `web/research/`의 방법 화면을 사용합니다. `/research/api/methods` 경로는 클라이언트 호환성을 위해 유지합니다. `/research/docs`와 `/research/openapi.json`에서 이 앱의 계약을 확인할 수 있습니다.

변경 시 [AGENTS.md](AGENTS.md)를 따릅니다. 데이터·비밀·개인 원문·생성 인덱스를 커밋하지 않고, 관련 API 계약 검사를 실행합니다. 코드 기여와 공개 서비스의 콘텐츠 쓰기 권한은 별개입니다.
