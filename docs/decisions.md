# 의사결정 기록 (Decision Log)

이 프로젝트의 확정된 기술·프로세스 결정과 **비자명한 도메인 지식**의 단일 출처.
"무엇이 왜 이렇게 됐나"를 한 곳에 — 로컬 AI 메모리가 아니라 여기 누적한다(다른 PC·세션·사람이 보게).
(공통 정책: team-harness `ai-collaboration.md` — 결정·지식은 repo docs, 로컬 메모리 최소.)

## 규약
- 새 결정 확정 시 이 표에 행 추가(영향 문서 갱신을 같은 PR에서).
- 결정 변경 시 행을 지우지 않고 상태를 `대체됨(→新행)`으로 — 이력 보존.

## 결정 목록 (CLAUDE.md·AGENTS.md 핵심 결정 시드 이관)

| 결정 | 시점 | 정본/관련 |
|---|---|---|
| **HMAC 비교는 `hmac.compare_digest()` 필수**(`==` 금지 — 타이밍 공격). 새 provider 서명 검증: 헤더 없음→400, 불일치→401 구분 | 2026-06 | AGENTS.md(보안) |
| **async/sync 혼용 금지**: `async def` 엔드포인트에서 동기 `db.query`/`db.commit` 직접 호출 금지(이벤트 루프 블로킹) → `def`로 변경(스레드풀 위임) 또는 AsyncSession | 2026-06 | AGENTS.md, CLAUDE.md |
| **순환 임포트 방지**: Prometheus 메트릭은 `app/metrics.py`에만 정의. `admin.py`에서 `main.py` import 금지(`request.app.state` 사용). `services/`에서 `main.py` import 금지 | 2026-06 | AGENTS.md, CLAUDE.md |
| **Celery 재시도**: `max_retries`만으론 재시도 0회 — `autoretry_for=(SQLAlchemyError,…)` + `retry_backoff` 또는 `self.retry(exc=e)` 필수. DLQ는 `on_failure`에서 실제 호출 | 2026-06 | AGENTS.md(Celery) |
| **SessionMiddleware 등록 필수**: `admin.py`가 `request.session` 사용 — `app/main.py`에 미등록 시 런타임 에러 | 2026-06 | CLAUDE.md |
| **테스트**: FastAPI 의존성 mock은 `app.dependency_overrides` 필수(`mocker.patch` 무효). Prometheus 검증은 `.collect()` 패턴(`get_sample_value`는 `None` 가능). delta 비교(절대값 금지) | 2026-06 | AGENTS.md(테스트) |
| **로컬 환경**: macOS 15 — 모든 Python 명령에 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` prefix. 로컬 DB 호스트 포트 **5433**(컨테이너 5432) | 2026-06 | CLAUDE.md, AGENTS.md |
| 스택: FastAPI 0.117 + Celery 5.5(Redis) + PostgreSQL 15(SQLAlchemy 2.0 동기 + Alembic) + Keycloak 22(JWT). 마이그레이션 forward-only | 2026-06 | AGENTS.md(개요) |

> 위는 기존 CLAUDE.md·AGENTS.md의 핵심 결정을 시드로 이관한 것. 새 설계 결정·도메인 지식은 여기 계속 누적한다.
