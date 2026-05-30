---
paths: [".github/workflows/**"]
---

# CI/CD 규칙

## 절대 변경 금지
- `pytest` → `.venv/bin/pytest`로 변경 금지 (CI는 venv 활성화 후 실행)
- `DYLD_LIBRARY_PATH` — macOS 전용, CI(Linux)에서는 제거
- 환경변수 키 이름 변경 금지 — GitHub Secrets와 동기화 필요

## 브랜치별 동작
- `feature/*`, `fix/*` → CI 검증만 (배포 없음)
- `develop` → CI 검증 + 스테이징 검증
- `main` → CI 검증 + 프로덕션 배포 (추후 설정)

## CI 실패 시 체크리스트
1. `ruff check app/ tests/` 실행 후 푸시 (lint가 가장 흔한 원인)
2. `DATABASE_URL` 등 필수 env var 누락 확인
3. Alembic 마이그레이션 미적용 여부 확인 (`alembic current` vs `alembic heads`)
