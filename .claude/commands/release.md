# /release — 릴리즈 실행

**사용법**: `/release <version>`
예) `/release 1.2.0`

> `/release-check` 통과를 전제로 실행한다.
> develop → release/vX.X.X → main (tag) + develop (--no-ff 머지)

---

## Phase 0 — 사전 확인 (오케스트레이터 직접 실행)

```bash
# 현재 브랜치 확인 + 최신 동기화
git branch --show-current
git checkout develop && git pull origin develop
```

**release-check 미통과 상태에서 절대 진행하지 않는다.**

---

## Phase 1 — 릴리즈 브랜치 생성 (오케스트레이터 직접 실행)

```bash
git checkout -b release/v$VERSION
```

README.md 배지·버전 확인 후 필요 시 수정.

```bash
git add README.md
git commit -m "chore(release): v$VERSION 릴리즈 준비

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 2 — 최종 검증 (`subagent_type: general-purpose`, **foreground**)

```bash
cd /Users/grinvi04/project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff format --check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v --tb=short
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic current
```

- 전부 통과 + alembic current == heads → ✅ 리포트
- 실패 → ❌ 리포트 후 중단

---

## Phase 3 — main 머지 + 태그 + develop 반영 (오케스트레이터 직접 실행)

Phase 2 ✅인 경우에만 진행.

```bash
# 1. main 머지 + 태그
git checkout main && git pull origin main
git merge --no-ff release/v$VERSION -m "Merge release/v$VERSION into main"
git tag v$VERSION
git push origin main --tags

# 2. develop 반영
git checkout develop
git merge --no-ff release/v$VERSION -m "Merge release/v$VERSION into develop"
git push origin develop

# 3. 브랜치 정리
git branch -d release/v$VERSION
```

완료 후 출력:
```
✅ 릴리즈 완료
- 버전: v$VERSION
- main 태그: v$VERSION ✅
- develop 반영: 완료 ✅
```
