# /feature-merge — feature 브랜치를 develop에 머지

**사용법**: `/feature-merge`
현재 브랜치가 `feature/*` 또는 `fix/*`인 상태에서 실행한다.

> 코드 확인 후 사용자가 직접 실행하는 커맨드.
> 머지 전 품질 검증을 자동으로 수행한다.

---

## 중단 조건 (진입 전 즉시 판단)

| 상황 | 중단 사유 출력 |
|---|---|
| 현재 브랜치가 `feature/*` 또는 `fix/*`가 아님 | "feature/* 또는 fix/* 브랜치에서만 실행할 수 있습니다. 현재 브랜치: [브랜치명]" |
| 미커밋 변경사항 존재 | "미커밋 변경사항이 있습니다 — 커밋 또는 stash 후 재실행하세요." |

---

## 실행 절차

### 1. 브랜치 상태 확인 (직접 실행)

```bash
git branch --show-current
git status --short
```

### 2. 최종 품질 검증 (직접 실행)

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -q
```

실패 시 → **즉시 중단**. 품질 문제 해결 후 재실행.

### 3. develop 최신화 + 머지 (직접 실행)

```bash
FEATURE_BRANCH=$(git branch --show-current)

git checkout develop
git pull origin develop
git merge --no-ff "$FEATURE_BRANCH" -m "Merge $FEATURE_BRANCH into develop

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push origin develop
```

### 4. 브랜치 정리 (직접 실행)

```bash
git branch -d "$FEATURE_BRANCH"
```

완료 후 출력:
```
✅ 머지 완료
- 브랜치: [feature명] → develop
- develop push: 완료
- 로컬 브랜치 삭제: 완료
```
