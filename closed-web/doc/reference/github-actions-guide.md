---
title: github-actions-guide
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
updated_at: 2026-04-15T09:47:57Z
created_at: 2026-04-15T02:08:58Z
publication_requested_at: 2026-04-15T02:09:15Z
publication_requested_by: aaron
publication_target_visibility: public
publication_decided_at: 2026-04-15T09:47:57Z
publication_decided_by: sagwan
publication_decision_reason: "구형 reference 노트 직접 공개 요청 — 설계 원칙상 캡슐화 없이 private 원본 직접 공개 불가. Private으로 유지."
**Recommendation: "** reviewing"
**Reason: "**"
**Review Summary: "**"
---

## Summary
GitHub Actions CI/CD 실무 레퍼런스. Workflow 구조·트리거·Reusable Workflow·보안·캐싱·배포 패턴. 2025 기준 모범 사례 중심. "재사용 가능한 워크플로우 + 최소 권한" 두 원칙이 핵심.

## Sources
- GitHub Actions 공식 문서 (docs.github.com/actions)
- github/awesome-copilot github-actions-ci-cd-best-practices
- Incredibuild "Best practices for reusable workflows"
- Octopus Deploy "GitHub Actions 2025 Guide"

---

## 1. Workflow 기본 구조
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:          # 수동 실행

permissions:
  contents: read              # 기본값을 최소 권한으로

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15       # 항상 설정 — 무한 루프 방지

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'        # 내장 캐시

      - run: npm ci
      - run: npm test
```

---

## 2. 트리거 패턴

```yaml
on:
  push:
    branches: [main, 'release/**']
    paths-ignore:             # 변경 없는 파일은 스킵
      - '**.md'
      - '.github/CODEOWNERS'

  pull_request:
    types: [opened, synchronize, reopened]

  schedule:
    - cron: '0 2 * * 1'      # 매주 월요일 02:00 UTC (의존성 감사 등)

  workflow_dispatch:
    inputs:
      environment:
        description: 'Target env'
        required: true
        default: 'staging'
        type: choice
        options: [staging, production]
```

---

## 3. Reusable Workflow (워크플로우 재사용)

### 호출받는 쪽 (`.github/workflows/ci-shared.yml`)
```yaml
name: Shared CI

on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
      node-version:
        required: false
        type: string
        default: '20'
    secrets:
      DEPLOY_TOKEN:
        required: true
    outputs:
      artifact-name:
        description: 'Built artifact name'
        value: ${{ jobs.build.outputs.artifact }}

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      artifact: ${{ steps.build.outputs.name }}
    steps:
      - uses: actions/checkout@v4
      - name: Build
        id: build
        run: |
          npm ci && npm run build
          echo "name=dist-${{ github.sha }}" >> $GITHUB_OUTPUT
```

### 호출하는 쪽
```yaml
jobs:
  ci:
    uses: org/shared-workflows/.github/workflows/ci-shared.yml@main
    with:
      environment: production
      node-version: '20'
    secrets:
      DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
```

**언제 Reusable Workflow vs Composite Action?**
- **Reusable Workflow**: 완전한 파이프라인(빌드+테스트+배포). 독립 실행 가능.
- **Composite Action**: 반복되는 step 묶음(setup, 캐시, 포맷). workflow 안에 삽입.

---

## 4. 보안 (최소 권한 원칙)

```yaml
permissions:
  contents: read        # 기본 최소
  # 필요한 것만 명시
  pull-requests: write  # PR 코멘트
  checks: write         # 체크 상태 업데이트
  packages: write       # ghcr.io 이미지 푸시
  id-token: write       # OIDC (AWS/GCP 비번 없는 인증)
```

### OIDC로 비밀번호 없이 AWS 인증
```yaml
- name: Configure AWS
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::123456789:role/github-actions
    aws-region: ap-northeast-1
```
시크릿에 AWS 키 저장 불필요. IAM Role이 GitHub OIDC 토큰을 신뢰하도록 설정.

### Actions 버전 고정 (공급망 보안)
```yaml
uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
# 태그보다 SHA로 고정 — 태그는 덮어쓰기 가능
```

---

## 5. 캐싱 전략

```yaml
# npm
- uses: actions/setup-node@v4
  with:
    node-version: '20'
    cache: 'npm'            # package-lock.json 기반 자동 캐시

# pip
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'
    cache: 'pip'

# 수동 캐시 (cargo, Go 모듈 등)
- uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/registry
      ~/.cargo/git
      target/
    key: ${{ runner.os }}-cargo-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: |
      ${{ runner.os }}-cargo-
```

**캐시 키 전략**: `OS + 의존성 lock 파일 해시`. 히트율 높이려면 `restore-keys` 계층화.

---

## 6. 매트릭스 빌드

```yaml
jobs:
  test:
    strategy:
      fail-fast: false        # 하나 실패해도 나머지 계속
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        node: [18, 20, 22]
        exclude:
          - os: windows-latest
            node: 18           # 특정 조합 제외

    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
```

---

## 7. 환경 보호 (Environment Protection)

```yaml
jobs:
  deploy-production:
    environment:
      name: production
      url: https://example.com
    runs-on: ubuntu-latest
    steps:
      - name: Deploy
        env:
          DEPLOY_TOKEN: ${{ secrets.PROD_DEPLOY_TOKEN }}
        run: ./scripts/deploy.sh
```

`production` 환경에 Reviewer 필수, 특정 브랜치만 허용 설정 → GitHub UI에서 설정.

---

## 8. 아티팩트 & 릴리스

```yaml
# 아티팩트 업로드
- uses: actions/upload-artifact@v4
  with:
    name: dist-${{ github.sha }}
    path: dist/
    retention-days: 7

# 다음 job에서 다운로드
- uses: actions/download-artifact@v4
  with:
    name: dist-${{ github.sha }}

# GitHub Release 자동화
- name: Create Release
  uses: softprops/action-gh-release@v2
  if: startsWith(github.ref, 'refs/tags/')
  with:
    files: dist/*.tar.gz
    generate_release_notes: true
```

---

## 9. Docker 이미지 빌드·푸시

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Login to GHCR
  uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- name: Build and push
  uses: docker/build-push-action@v5
  with:
    context: .
    push: ${{ github.ref == 'refs/heads/main' }}
    tags: ghcr.io/${{ github.repository }}:latest
    cache-from: type=gha
    cache-to: type=gha,mode=max   # GitHub Actions 캐시 사용
```

---

## 10. 자주 쓰는 액션 모음

| 액션 | 용도 |
|---|---|
| `actions/checkout@v4` | 소스 체크아웃 |
| `actions/setup-node@v4` | Node.js 설치 |
| `actions/setup-python@v5` | Python 설치 |
| `actions/setup-go@v5` | Go 설치 |
| `actions/cache@v4` | 수동 캐시 |
| `actions/upload-artifact@v4` | 아티팩트 저장 |
| `actions/download-artifact@v4` | 아티팩트 불러오기 |
| `docker/build-push-action@v5` | Docker 빌드+푸시 |
| `docker/login-action@v3` | 컨테이너 레지스트리 로그인 |
| `aws-actions/configure-aws-credentials@v4` | OIDC AWS 인증 |
| `softprops/action-gh-release@v2` | GitHub Release 생성 |
| `github/codeql-action@v3` | CodeQL SAST |
| `aquasecurity/trivy-action@master` | 컨테이너 취약점 스캔 |
| `peter-evans/create-pull-request@v6` | PR 자동 생성 |

---

## 11. 흔한 함정

- **`GITHUB_TOKEN` 권한**: 기본 read-all. `permissions` 명시해야 최소 권한.
- **`actions/checkout` shallow clone**: 기본 fetch-depth=1. `git log` 필요하면 `fetch-depth: 0`.
- **secrets in forks**: PR에서 fork 워크플로우는 시크릿 접근 불가. `pull_request_target` 주의.
- **`workflow_dispatch` 없이 수동 실행 불가**: 디버그용으로 항상 추가 권장.
- **self-hosted runner 보안**: 공개 레포에서 self-hosted는 코드 실행 공격 위험 — 격리 환경 필수.

## Reuse
- 모든 워크플로우에 `timeout-minutes` 필수.
- Actions 버전은 SHA로 고정 (공급망 보안).
- 시크릿은 Environment에 저장하고 환경 보호 Rules 설정.
- 재사용 가능한 것은 reusable workflow 또는 composite action으로 분리.

## 참고 자료 (References)
이 문서는 아래 공식 문서·표준·원저 논문을 근거로 작성되었습니다.

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Semantic Versioning](https://semver.org/)
- [Conventional Commits](https://www.conventionalcommits.org/)
