---
paths: ["alembic/**", "app/models/**"]
---

# Alembic 마이그레이션 규칙

## 마이그레이션 안전 순서
```bash
# 1. app/models/ 수정
# 2. 마이그레이션 생성 (이름을 명확하게)
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic revision --autogenerate -m "<설명적인_이름>"
# 3. 생성된 파일 내용 반드시 검토 후 적용
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic upgrade head
# 4. lint 확인
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check alembic/
```

## 절대 금지
- `alembic downgrade base` — 전체 스키마 삭제 (PreToolUse hook이 차단)
- 마이그레이션 파일 직접 수정 — `alembic revision`으로만 생성
- `text()` / `execute()` raw SQL — SQLAlchemy ORM 또는 `sa.text()` + 파라미터 바인딩 사용

## 마이그레이션 실패 시
- DB 스키마와 모델 불일치 시 앱 기동 불가
- 롤백: `alembic downgrade -1` (한 단계씩)
- 현재 상태 확인: `alembic current` / `alembic history`
