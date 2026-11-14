# SQLite 온라인 백업의 시점 경계 재현

일반 웹 검색과 OpenAkashic을 비교한 LLM 실험과 분리된, 운영자가 직접 실행한 합성 fixture 두 건이다. 모델 응답 품질이나 도구의 우열을 평가하지 않는다. 원래 v2 문장의 반례와 v3 정정 후 같은 조건의 재관찰을 보존한다.

Python 3.12.3, SQLite 3.45.1에서 512행의 WAL 데이터베이스를 새로 만들었다. `backup(..., pages=1)`의 네 번째 progress callback에서 다른 연결이 id1을 한 번 수정하고 commit했다. 이후 원본에는 추가 쓰기가 없었다. 두 실행 모두 remaining이 510에서 513으로 증가했고, 그 commit이 최종 사본에 포함됐다. 원본과 백업 파일, main 파일만 별도 복사한 독립 사본의 스키마와 512개 ordered rows가 일치했고, 각 실행의 12개 검사가 통과했다. 임시 데이터베이스는 제거했다.

이 결과는 v2의 무조건적인 시작 시점 고정 문장이 해당 구성에서 너무 강함을 보여준다. v3은 증분 복사 사이 쓰기로 재시작하거나 이후 변경을 포함할 수 있음을 명시한다. 스키마와 행의 일치는 동일한 관찰 시점 또는 고정된 읽기 범위가 보장된 비교에만 요구한다. 이 fixture는 commit 한 번 뒤 source가 더 변하지 않는 통제 범위에서 비교했다. 계속 변하는 운영 원본과 항상 같아야 한다는 보장은 검증하지 않았다. 해당 동시 쓰기 경계는 [SQLite 공식 API](https://www.sqlite.org/c3ref/backup_finish.html)에 설명돼 있다.

`v3-corrected/report.json`의 `counterexample_observed=true`는 `claim_under_test`에 인용한 **과거 v2 문장**을 가리킨다. 현재 v3이 틀렸다는 표시가 아니다. v3 원본 report의 의미 검토 필드는 null로 유지하고, 사후 해석은 `v3-corrected/semantic-review.json`에 따로 저장했다.

## 공개 기록과 원본

공개 방법 ID는 `method_5af91cc7219a4130a3a2cf2d7630b031`이다. [v2 스냅샷](https://knowledge.openakashic.com/research/api/methods/method_5af91cc7219a4130a3a2cf2d7630b031/versions/2)과 [v3 스냅샷](https://knowledge.openakashic.com/research/api/methods/method_5af91cc7219a4130a3a2cf2d7630b031/versions/3)은 각각 보존됐다.

- v2 실제 operator 부분 적용: `outcome_eb439c2bff3d41669ed891f828b78d50`
- v3 revision은 위 v2 결과를 정확히 참조한다.
- v3 fresh 재검증 부분 적용: `outcome_e10b3f2302bd49e49e313f89fe6f52d7`

두 outcome의 `partial`은 백업의 제한된 검사와 설명 검토를 기록한다. 모든 운영 조건, 복잡한 외래 키 복구, 임의 시점의 고정성이나 일반적 효과를 검증했다는 뜻이 아니다. 앞선 LLM 후보가 코드를 완성하지 못한 원인으로 이 별도 fixture를 연결하지 않는다.

`v2-original/`과 `v3-corrected/`의 코드, method snapshot, progress, report, artifact manifest는 각 실제 실행의 원본 바이트를 그대로 복사했다. 두 실행의 코드 SHA-256은 `dc524e82a5c2bee004236071cd17b0af8b63c2c4dd008fa96e522638ad0a9f27`로 같다. 원래 시각과 결과를 소급 수정하지 않았다. `public-outcome.json`은 실제 공개 API 결과의 복사본이다. `manifest.json`과 `SHA256SUMS`로 파일을 확인할 수 있다.

## 파일 검증과 새 실행

Python 표준 라이브러리만 필요하다. 파일 검증은 fixture를 실행하지 않는다.

```sh
python verify_pack.py
```

새 실행은 이 pack과 Git checkout 밖의 존재하지 않는 경로를 명시한다. launcher가 원본 코드를 외부 workspace로 그대로 복사한 후 새 합성 데이터만 만든다. 원래 결과 디렉터리를 덮어쓰지 않는다.

```sh
python run_fixture.py --version 2 --output PATH_OUTSIDE_CHECKOUT_FOR_V2
python run_fixture.py --version 3 --output PATH_OUTSIDE_CHECKOUT_FOR_V3
```

실제 관찰이 다르면 그대로 남겨야 한다. 반례가 관찰되지 않았거나 fixture 검증에 실패한 실행으로 failure 또는 correction 연결을 만들어서는 안 된다. API 쓰기, 모델 호출, 실제 서비스 DB와 자격정보 접근은 없다. 새 실행의 Python과 SQLite 버전도 report에 기록된다.
