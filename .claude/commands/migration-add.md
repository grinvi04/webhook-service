# /migration-add — Alembic 마이그레이션 생성

**사용법**: `/migration-add "<설명>"`  예) `/migration-add "webhook_event retry_count 컬럼 추가"`

## 제약조건 (할루시네이션 방지)
- 마이그레이션 생성 전 `app/models/` 전체를 Read하여 실제 모델 구조 확인
- 컬럼 타입은 SQLAlchemy 2.0 타입 시스템 사용 (`String`, `Integer`, `DateTime` 등)
- `alembic revision --autogenerate` 결과 파일을 반드시 검토 후 적용
- nullable 변경, 컬럼 삭제는 데이터 손실 위험 — 반드시 사용자 확인 후 진행
- 생성된 마이그레이션 파일은 ruff E501·E402 무시됨 (pyproject.toml 설정)

## 실행 절차

### 1. 현재 상태 확인
```bash
cd /Users/grinvi04/project/webhook-service
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic current
```

### 1-1. 중단 조건 (현재 상태 확인 후 즉시 판단)

아래 상황이면 즉시 중단하고 사유를 출력한다. 모델 수정으로 진행하지 않는다.

| 상황 | 중단 사유 출력 |
|---|---|
| `alembic current` 실행 오류 (DB 연결 실패 등) | "DB에 연결할 수 없습니다 — docker-compose up -d db 후 재시도해 주세요." |
| `alembic current` ≠ `alembic heads` (미적용 마이그레이션 존재) | "미적용 마이그레이션이 있습니다 — alembic upgrade head 실행 후 재시도해 주세요." |
| `NOT NULL` 컬럼 추가인데 `server_default` 또는 backfill 전략이 없음 | "기존 데이터 처리 전략이 필요합니다 — server_default 값 또는 backfill SQL을 알려주세요." |

### 2. 모델 수정
`app/models/` Read → SQLAlchemy 2.0 패턴으로 수정:
- `Column(String)` → `mapped_column(String)` (SQLAlchemy 2.0 권장)
- `relationship()` 양방향은 `back_populates` 필수 (backref 사용 금지)
- 순환 임포트 방지: `app/models/__init__.py`에서 직접 import 금지

### 3. 마이그레이션 생성
```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic revision --autogenerate -m "$ARGUMENTS"
```

### 4. 생성 파일 검토 (필수)
`alembic/versions/` 최신 파일 Read → upgrade/downgrade 확인:
- 불필요한 index 재생성 제거
- nullable=False 추가 시 server_default 또는 기존 데이터 처리 확인

### 5. 적용 및 검증
```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic upgrade head
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -q
```

### 6. 롤백 검증
```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic downgrade -1
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/alembic upgrade head
```
`downgrade -1` 실패 시 → **즉시 중단**. `downgrade()` 함수 미구현 원인 리포트 후 사용자 확인 요청. upgrade head는 실행하지 않는다.

### 7. 커밋
`feat(db): $ARGUMENTS`

---

## 패턴 레퍼런스

### SQLAlchemy 2.0 컬럼 선언
```python
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, Integer, DateTime, func

class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

### nullable=False 컬럼 추가 (기존 데이터 보존)
```python
def upgrade():
    op.add_column("t", sa.Column("col", sa.String, nullable=True))
    op.execute("UPDATE t SET col = 'default_value' WHERE col IS NULL")
    op.alter_column("t", "col", nullable=False)
```

### 컬럼 이름 변경 (add+copy+drop)
```python
def upgrade():
    op.add_column("webhook_events", sa.Column("new_name", sa.String(50)))
    op.execute("UPDATE webhook_events SET new_name = old_name")
    op.drop_column("webhook_events", "old_name")
```

### 대용량 테이블 주의사항
- `ADD COLUMN ... DEFAULT` 는 PostgreSQL에서 rewrite 없이 즉시 완료
- `NOT NULL` 동시 적용 시 full scan 발생 → 위 3단계 패턴 사용
- 인덱스 추가: `CREATE INDEX CONCURRENTLY` → `op.execute()` 로 처리
