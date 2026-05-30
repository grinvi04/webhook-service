# /feature-modify — TDD 기반 기존 기능 수정

**사용법**: `/feature-modify <feature-name> "<변경 설명>"`
예) `/feature-modify webhook-handler "처리 실패 시 에러 메트릭 카운터 증가"`

> 변경된 동작만 RED로 만들고, 나머지는 GREEN을 유지한 채 구현한다.

---

## Phase 0 — 진입 전 사전 점검 (오케스트레이터 직접 실행)

```bash
# 최신 develop 기준으로 분기
git checkout develop && git pull origin develop
```

테스트 파일 존재 확인:
```bash
ls tests/test_$FEATURE_NAME*.py 2>/dev/null || echo "⚠️ 테스트 파일 없음 — 테스트 없이 작성된 기능"
```
- 테스트 파일 없음 → Phase 2에서 새로 작성
- 테스트 파일 있음 → 정상 흐름 진행

---

## Phase 1 — 영향 범위 분석 (오케스트레이터 직접 실행)

$ARGUMENTS에서 도출:
- 수정 범위: `app/`, `tests/` 중 영향받는 파일
- 기존 테스트 중 변경 필요한 것 vs 유지되는 것
- DB 스키마 변경 필요 여부 (필요 시 Alembic 마이그레이션)
- 브랜치 전략 결정:
  - 기능 확장 → `feature/$FEATURE_NAME-update` → 커밋 타입 `feat`
  - 버그 수정 → `fix/$FEATURE_NAME` → 커밋 타입 `fix`

```bash
git checkout -b <결정된 브랜치명>
```

**분석 결과(수정 범위·브랜치 타입·변경할 테스트 목록)를 Phase 2 프롬프트에 명시적으로 포함한다.**

---

## Phase 2 — 테스트 계약 갱신 (`subagent_type: general-purpose`, **foreground**)

> 변경의 기대 결과를 먼저 정의하고, 구현은 그것을 이행한다.

**⚠️ 중요**: 테스트 저장 시 PostToolUse hook이 `❌ [ruff lint 실패]`를 출력할 수 있다. 변경된 테스트의 실패는 **의도된 RED 상태**이므로 수정하지 않는다.

**프롬프트 (Phase 1 분석 결과 포함):**
- 변경 내용 + 영향 범위: [Phase 1 결과 붙여넣기]
- `CLAUDE.md` 테스트 패턴 준수 (dependency_overrides, Prometheus collect() 패턴)

**작업 순서:**
1. 테스트 파일이 없었다면: 새로 작성
2. 테스트 파일이 있다면:
   - 변경되는 동작 → 기존 케이스 수정 또는 새 케이스 추가
   - 유지되는 동작 → 기존 테스트 그대로 보존
3. 실행 후 **변경된 테스트만 FAIL, 유지 테스트는 PASS** 확인:
   ```bash
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
     DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
     .venv/bin/pytest tests/test_$FEATURE_NAME*.py -v
   ```

완료 후 변경된 테스트 목록·RED 확인 결과 리포트.

---

## Phase 3 — 수정 구현 (`subagent_type: general-purpose`, `run_in_background: true`)

**프롬프트 (Phase 1·2 결과 포함):**
- `CLAUDE.md` 패턴 준수 (순환 임포트 방지, metrics.py 위치 규칙 등)
- Phase 2 갱신 테스트를 **새 계약서**로 삼아 구현 수정

**작업 순서:**
1. DB 스키마 변경이 필요하면:
   ```bash
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
     DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
     .venv/bin/alembic revision --autogenerate -m "update-$FEATURE_NAME"
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
     DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
     .venv/bin/alembic upgrade head
   ```

2. **구현 → 테스트 루프 (최대 3회)**:
   ```bash
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
     DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
     .venv/bin/pytest tests/test_$FEATURE_NAME*.py -v
   ```
   - 3회 모두 실패 시: 에러·수정 이력·DB 상태 리포트 후 **즉시 중단**

3. **회귀 검사** (전체):
   ```bash
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
   DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
     DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
     .venv/bin/pytest tests/ -v
   ```

완료 후 수정 파일 목록·전체 테스트 결과·DB 변경 여부 리포트.

---

## Phase 4 — Refactor (오케스트레이터 직접 실행)

Phase 3 ✅인 경우에만 진행.

`CLAUDE.md` 기준으로 수정된 코드 검토:
- 순환 임포트 없는지 (`main.py` → `admin.py` → `main.py` 패턴)
- Prometheus 메트릭이 `metrics.py` 외 위치에 정의됐는지
- 변경 요청 외 코드 수정 없는지 (외과적 원칙 위반)

수정 후 테스트 재확인:
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v
```

---

## Phase 5 — 최종 검증 + 커밋 (오케스트레이터 직접 실행)

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v
```

커밋 (Phase 1에서 결정한 타입 사용):
```bash
git add app/ tests/
git commit -m "<타입>($FEATURE_NAME): $DESCRIPTION

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

브랜치는 develop에 머지하지 않는다 — 사용자가 확인 후 머지.

---

## Phase 6 — 회고·개선 (오케스트레이터 직접 실행)

아래 항목을 간략히 검토하고, 의미있는 인사이트만 기록한다:

**1. 이번 사이클 검토**
- 영향 범위 분석이 실제 변경 범위와 일치했는가?
- 회귀 테스트가 충분했는가?
- 반복된 패턴이 있었는가?

**2. 하네스 개선 제안**
- 이번 수정에서 발견된 `CLAUDE.md` 누락 패턴 → 업데이트 제안
- 커맨드 흐름에서 불필요하거나 빠진 단계 → 이 파일 수정 제안

> **원칙**: 회고는 짧게. 다음 사이클을 실질적으로 개선하는 내용만 남긴다.
