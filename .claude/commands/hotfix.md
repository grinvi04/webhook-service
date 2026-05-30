# /hotfix — 운영 긴급 수정

**사용법**: `/hotfix <fix-name> "<증상 설명>"`
예) `/hotfix signature-verify "GitHub 웹훅 서명 검증이 항상 401을 반환하는 문제"`

> 운영(main)에서 직접 분기. 반드시 main과 develop 양쪽에 머지한다.
> develop 머지 누락 시 코드 분기 발생 — 가장 흔한 hotfix 실수.

---

## Phase 0 — 진입 전 점검 (오케스트레이터 직접 실행)

```bash
# main 최신 상태 확인
git checkout main && git pull origin main

# 브랜치 생성
git checkout -b hotfix/$FIX_NAME
```

---

## Phase 1 — 버그 재현 + 회귀 테스트 작성 (`subagent_type: general-purpose`, **foreground**)

> 버그를 먼저 테스트로 증명한다. 테스트가 통과하면 버그가 사라진 것이다.

**⚠️ 중요**: 테스트 저장 시 PostToolUse hook이 `❌ [ruff lint 실패]` 또는 `❌` 를 출력할 수 있다. 버그 재현 테스트의 실패는 **의도된 RED 상태**이므로 수정하지 않는다.

**프롬프트:**
- 증상: $ARGUMENTS
- 영향받는 서비스·파일 파악
- 버그를 재현하는 **회귀 테스트 1개** 작성 (`tests/` 내 관련 파일에 추가):
  - 테스트 이름: `test_hotfix_<증상_한_줄>`
  - 버그가 있는 현재 상태에서 FAIL 확인:
    ```bash
    DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
      DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
      .venv/bin/pytest tests/ -k "hotfix" -v
    ```
- RED 확인 완료 후 리포트

---

## Phase 2 — 수정 (`subagent_type: general-purpose`, `run_in_background: true`)

**프롬프트:**
- 증상 + Phase 1 회귀 테스트: [Phase 1 결과 붙여넣기]
- `CLAUDE.md` 패턴 준수
- **외과적 수정**: 증상과 직접 관련된 코드만 수정

- **수정 → 테스트 루프 (최대 3회)**:
  ```bash
  DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
    .venv/bin/pytest tests/ -k "hotfix" -v
  ```
  - 회귀 테스트 PASS + 기존 테스트 전부 PASS 확인
  - 3회 실패 시: 에러 리포트 후 **즉시 중단**

- **전체 회귀 검사**:
  ```bash
  DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
  DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
    .venv/bin/pytest tests/ -v
  ```

완료 후 수정 파일 목록·전체 테스트 결과 리포트.

---

## Phase 3 — 릴리즈 + 양방향 머지 (오케스트레이터 직접 실행)

Phase 2 ✅인 경우에만 진행. ❌이면 리포트 출력 후 종료.

```bash
# 1. main에 머지 + 태그 (패치 버전 수동 입력)
git checkout main
git merge --no-ff hotfix/$FIX_NAME -m "Merge hotfix/$FIX_NAME into main"
git tag v<현재버전+패치>
git push origin main --tags

# 2. develop에도 머지 ← 반드시 실행
git checkout develop
git merge --no-ff hotfix/$FIX_NAME -m "Merge hotfix/$FIX_NAME into develop"
git push origin develop

# 3. 브랜치 정리
git branch -d hotfix/$FIX_NAME
```

> ⚠️ develop 머지를 건너뛰면 다음 릴리즈 시 수정이 사라진다.

완료 후 "✅ hotfix 완료 — main 태그: vX.X.X, develop 반영 완료" 출력.
