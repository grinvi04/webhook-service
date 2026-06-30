# Webhook Service — Claude Code 작업 규칙

@AGENTS.md

> 프로젝트 공통 규약(개요·로컬개발·아키텍처·Celery·테스트·보안·Git Flow·커밋)은 `AGENTS.md` 참조

---

## Claude Code 전용 지침

- git-flow 작업은 harness-guard 플러그인 커맨드 사용: `/feature-merge`, `/hotfix`, `/release-check`, `/release` (그 외 계획 `/plan`, 개발 `/feature-add`·`/feature-modify`, repo 로컬 `/provider-add`·`/migration-add`·`/api-test`·`/readme-update` 제공)
- PR 머지 전 게이트는 `pr-review-gate` 스킬 절차를 따른다 (단일 출처)
- 릴리즈 전 보안 검토는 `security-reviewer` 에이전트를 spawn한다
- `main`·`develop` 직접 커밋 금지, PR·승인·CI 통과 강제는 GitHub branch protection이 담당한다 (Git Flow는 `AGENTS.md` 참조)
- `.claude/settings.json`만 커밋(dev 권한 단일출처), 나머지 `.claude/`는 추적 제외 — 커맨드/훅 변경은 harness 원본 수정 후 동기화

---

## Compact Instructions

컨텍스트 압축 후에도 반드시 유지해야 할 핵심 규칙:

1. **Git Flow**: `main`, `develop` 직접 커밋 금지 (branch protection으로 강제). feature/fix/hotfix/release 브랜치 → PR 경유.
2. **macOS 15 필수 prefix**: 모든 Python 명령 앞에 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` 추가.
3. **로컬 DB 포트**: 호스트 **5433** (Docker 내부 서비스 간은 `db:5432` 그대로).
4. **순환 임포트 방지**: Prometheus 메트릭은 `app/metrics.py`에만 정의. `admin.py`에서 `main.py` import 금지.
5. **HMAC 비교**: 반드시 `hmac.compare_digest()` 사용 (`==` 금지 — 타이밍 공격).
6. **테스트 규칙**: FastAPI 의존성 모킹 시 `dependency_overrides` 사용 필수. Prometheus 메트릭 검증 시 `collect()` 패턴 사용 필수.
7. **async/sync 혼용 금지**: `async def` 엔드포인트에서 동기 `db.query`/`db.commit` 직접 호출 금지 — 이벤트 루프 블로킹.
8. **Celery retry 필수**: `max_retries`만으론 재시도 0회 — `autoretry_for=(SQLAlchemyError, ...)` 또는 `self.retry(exc=e)` 필수.
9. **SessionMiddleware 등록 필수**: `admin.py`가 `request.session` 사용 — `app/main.py`에 `SessionMiddleware` 등록 없으면 런타임 에러.
