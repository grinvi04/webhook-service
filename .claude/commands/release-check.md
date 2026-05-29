# /release-check — 릴리즈 전 품질 검증

**사용법**: `/release-check`

## 제약조건
- 실제 명령어 출력 결과만 리포트할 것 — 추측 금지
- 에러 메시지는 원문 그대로 포함할 것 (요약 금지)
- 보안 항목은 코드에서 직접 grep한 결과만 보고할 것

## 3개 에이전트 동시 background spawn

**Agent A — Lint** (`subagent_type: general-purpose`, `run_in_background: true`)
```bash
cd /Users/grinvi04/Project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff format --check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
```
- 자동 수정 가능하면 `--fix` + `ruff format` 실행 후 재확인
- 규칙: E501(88자), F401(미사용 import), UP007(str|None), I(import 정렬)
- alembic/versions/는 E501·E402 무시 (pyproject.toml per-file-ignores 적용)

**Agent B — 테스트** (`subagent_type: general-purpose`, `run_in_background: true`)
```bash
cd /Users/grinvi04/Project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v --tb=short
```
- 실패 시: 테스트명, 에러 타입, assert 실패 라인 리포트
- Prometheus: `REGISTRY.get_sample_value` 패턴 정상 여부 확인

**Agent C — 보안** (`subagent_type: Explore`, `run_in_background: true`)
아래 항목을 grep으로 직접 탐색:
- `app/dependencies.py`: `hmac.compare_digest` 사용 여부 (== 비교시 타이밍 공격 경고)
- `app/` 전체: 하드코딩 시크릿 (`secret\s*=\s*["']`, `password\s*=\s*["']`)
- `app/` 전체: raw SQL (`text(`, `execute(`) → SQLAlchemy ORM 우회 여부
- `.env`가 `.gitignore`에 포함되어 있는지
- `requirements.txt`: 버전 핀 여부 (>= 만 있으면 경고)

## 집계

| 항목 | 결과 | 비고 |
|---|---|---|
| ruff lint | ✅/❌ | 에러 수 |
| ruff format | ✅/❌ | |
| pytest | ✅/❌ | N/14 통과 |
| 보안 | ✅/⚠️ | 건수 |

모두 ✅ → "배포 준비 완료"

---

## 추가 검증 항목 (Agent C 확장)

### Alembic 마이그레이션 상태
```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic current
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic heads
```
`current` ≠ `heads`이면 미적용 마이그레이션 경고.

### Docker 빌드 검증
```bash
docker build -t webhook-service:test . --no-cache 2>&1 | tail -5
```
빌드 실패 시 에러 원문 포함하여 리포트.

### 환경변수 완전성 체크
```bash
grep -oE '^[A-Z_]+' .env.example | sort > /tmp/env_example_keys.txt
grep -oE 'settings\.[a-z_]+' app/config.py | sort -u > /tmp/config_keys.txt
```
`.env.example`에 없는 `settings.*` 항목 경고.

### 보안 grep 상세
```bash
# timing-safe 비교 미사용 위치 탐색
grep -rn "==" app/ | grep -i "signature\|secret\|token\|hmac"

# 하드코딩 크리덴셜 패턴
grep -rn -E "(password|secret|api_key)\s*=\s*['\"][^{]" app/

# raw SQL (ORM 우회 위험)
grep -rn "execute\(\"" app/

# .env gitignore 확인
grep -c "^\.env$" .gitignore || echo "⚠️ .env not in .gitignore"
```

### 릴리즈 게이트 기준
| 게이트 | 기준 |
|---|---|
| lint | 에러 0건 (warning 0건) |
| format | 변경사항 없음 |
| pytest | 전체 통과 (skip 허용) |
| 보안 | hmac.compare_digest 사용, 하드코딩 없음 |
| alembic | current == heads |
