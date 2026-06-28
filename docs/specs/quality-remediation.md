# 품질 리메디에이션 로드맵 — webhook-service

> 상태: 제안(Proposed) · 작성: AI 감사(정독 기반) · 기준일: 2026-06

## §0 Context / Why

자매 프로젝트 **erp**에서 실 스택 감사로 결함 클래스 다수가 드러났고, 그 결과가
**team-harness 표준**(`docs/`, `templates/rules/stacks/python.md`·`alembic.md`)으로 표준화됐다.
webhook-service(FastAPI/Python)는 같은 손·같은 패턴으로 만들어져 **동일 결함 클래스**가 재현될
개연성이 높아, team-harness 표준을 단일 출처로 두고 코드를 정독 감사했다.

본 문서는 그 감사 결과를 **수정 가능한 작업 단위**로 분해한 로드맵이다.

**성공 기준(1줄)**: 핵심 보안 로직(HMAC 서명검증)에 실효 테스트가 생기고, 멱등성·async·mypy·소프트삭제
표준 위반이 게이트 통과 가능한 상태로 정리된다.

---

## §1 결함 인벤토리 (Tier순)

근거는 `file:line`(감사 시점 실측). 표준 매핑은 team-harness `docs/` 단일 출처.

### Tier 0/1 — High (즉시)

| # | 결함 | 근거 (file:line) | 표준 매핑 |
|---|---|---|---|
| H1 | **HMAC 서명검증 0% 테스트** — 통합테스트가 `verify_github`/`verify_stripe`를 통째로 mock(`mocker.patch("app.main.verify_github", ...)`)하고, invalid-sig 테스트도 `side_effect=HTTPException`로 대체. 단위테스트(`test_unit_verifier.py`)는 `_get_customer_async`만 검증 → 실제 `_verify_github`(HMAC 계산)·`_verify_stripe` 어느 경로도 실행되지 않음. **핵심 보안 로직이 회귀 무방비** | tests/test_integration_webhooks.py:54-59 / tests/test_unit_verifier.py(전체) / app/dependencies.py:157-188 | code-review.md §테스트 깊이(실 흐름 vs mock-only) |

### Tier 2 — Med

| # | 결함 | 근거 (file:line) | 표준 매핑 |
|---|---|---|---|
| M1 | **이벤트 유실 창 + DB 멱등 고유제약 부재** — Redis `SET NX`로 멱등키를 **큐잉 전**에 설정한 뒤 `apply_async` 호출. 큐잉 실패 시 키만 남아 공급자 재시도가 "already processed"로 조용히 드롭. 24h TTL 만료 후 재시도는 `webhook_events`에 중복행 생성(고유제약 없음) | app/webhooks.py:177-200 / app/models/webhook_event.py(고유제약 없음) | db-standards.md / code-review.md(신뢰성) |
| M2 | **async health_check 동기 DB 블로킹** — `async def health_check`에서 동기 `database.SessionLocal()` + `db.execute(text("SELECT 1"))` 호출 → 이벤트 루프 블로킹 | app/main.py:118-131 | python.md §async/sync 혼용 금지 |
| M3 | **mypy 게이트 전무** — pyproject·CI·pre-commit·requirements 어디에도 mypy 없음(python.md 게이트 3종 중 1종 누락). ruff `select`도 `E,F,W,I,UP`만 — 권장 `B,SIM,C4` 미선택, line-length 88(표준 100) | pyproject.toml:1-13 / .github/workflows/ci.yml:55-58 | python.md §게이트(ruff+format+mypy) |
| M4 | **소프트삭제 없음 + admin 하드삭제** — 모델에 `deleted_at` 부재, `WebhookEventAdmin.can_delete=True`로 브라우저 UI에서 영구삭제(감사이력 소실) | app/models/webhook_event.py / app/admin.py:55 | db-standards.md §소프트삭제 |
| M5 | **타입주석 불일치** — 태스크 시그니처 `customer_id: UUID`이나 Celery JSON 직렬화로 런타임은 `str` 수신(UUID 컬럼에 우연 coerce되어 동작). mypy 부재로 미검출 | app/services/webhook_handler.py:45,88 / app/webhooks.py:194 | python.md §mypy strict |
| M6 | **GitHub 서명 리플레이** — `_verify_github`이 body HMAC만 검증, 타임스탬프/nonce 무검증 → 캡처한 유효 서명 페이로드 리플레이 가능. 24h 멱등으로만 완화(TTL 만료 후 재생 가능). Stripe는 `construct_event`가 300s 허용오차로 방어(양호) | app/dependencies.py:157-170 | auth-standards.md / code-review.md(보안) |
| M7 | **공통 Envelope 미적용** — 전역 핸들러·모든 에러가 FastAPI 기본 `{"detail": ...}`, `RequestValidationError` 커스텀 매핑 없음. (입력오류는 422=4xx로 나가 5xx 흡수는 아님 — 양호) | app/main.py:103-106 | api-standards.md §공통 Envelope |

### Tier 3 — Low

| # | 결함 | 근거 (file:line) | 표준 매핑 |
|---|---|---|---|
| L1 | **CI 시크릿명 `GITHUB_` 접두** — `secrets.GITHUB_WEBHOOK_SECRET`는 GitHub Actions 예약 접두(생성 불가)라 빈 값 해석. 테스트가 mock이라 은폐됨 | .github/workflows/ci.yml:63 | operations.md / ci.md |
| L2 | **죽은 전역 시크릿 설정** — `github_webhook_secret`/`stripe_webhook_secret`(필수) 로드되나 검증경로는 DB의 `customer.webhook_secret`만 사용 → 미사용/혼선 | app/config.py:9-10 / app/dependencies.py:129 | — (정리) |
| L3 | **status 상태머신 미전이** — `status` 항상 `PENDING`, 태스크가 PROCESSED/FAILED로 전이 안 함(관측성·재처리 식별 불가) | app/models/webhook_event.py:27 / app/services/webhook_handler.py | operations.md |
| L4 | **멱등키 tenant 미포함** — 키 `webhook:idempotency:{source}:{event_id}`에 tenant_id 없음. GitHub delivery=UUID·Stripe evt_id=전역유일이라 실위험 낮음(방어적 개선) | app/webhooks.py:178 | — (강건성) |

### 마이그레이션 — 게이트 skip · 깨끗

`check-migration-safety.mjs --migrations alembic/versions` → **EXIT 0, skip 통과**(Flyway류 아님).
수동 점검: 리비전 1개(`a14bd9ecd5f5`, `down_revision=None`) — **단일 선형, 체인 분기·다중 head 없음**,
모델↔마이그레이션 컬럼 일치(드리프트 미발견). 운영 증분 적용은 실 DB 없이는 미검증.

---

## §2 Acceptance Criteria

- **AC-H1**: 실 시크릿으로 HMAC 서명을 생성해 엔드포인트를 호출, **valid 서명 → 202 / 변조 body·invalid 서명 → 401**을 실제 `_verify_github`·`_verify_stripe` 실행 경로로 단언(verify를 mock하지 않음).
- **AC-M1**: 멱등키 설정을 **큐잉 성공 이후**로 이동 + `webhook_events`에 멱등 고유제약(예: `(customer_id, source, event_id)`) 추가. 큐잉 실패 시 키가 남지 않음을 테스트로 확인.
- **AC-M2**: `health_check`를 async DB(`get_async_db`)로 전환 또는 `def`로 변경 — 이벤트 루프 블로킹 제거.
- **AC-M3**: CI에 `mypy .`(strict) 스텝 통과 + ruff 룰셋 `B,SIM,C4` 보강.
- **AC-M4**: `deleted_at` 소프트삭제 도입 **또는** `WebhookEventAdmin.can_delete=False`.
- **AC-M5/M6/M7**: 타입주석 정정(`str`), GitHub 리플레이 한계 문서화(§6 결정 후), 공통 Envelope 매핑.

---

## §3 PR 분해 (응집 단위 · 순서)

1. **PR-1 (우선) HMAC 실서명 테스트** — H1. 회귀 안전망을 먼저 깐 뒤 나머지 리팩터.
2. **PR-2 멱등성 강화** — M1 (큐잉 후 키설정 + DB 고유제약 마이그레이션). + L4.
3. **PR-3 async health** — M2.
4. **PR-4 mypy 게이트 도입** — M3 + M5(타입주석 정정). ruff 룰셋 보강 포함.
5. **PR-5 소프트삭제** — M4 + L3(status 전이).
6. **PR-6 공통 Envelope** — M7.
7. **PR-7 정리** — L1(시크릿명), L2(죽은 설정).

각 PR은 단일 관심사·독립 리뷰 가능. PR-1이 안전망이므로 선행.

---

## §4 검증 방법

- **테스트**: pytest를 **실 서명 생성**(`scripts/generate_github_signature.sh` 로직)·**실 Redis/DB 경계**로 — 핵심 보안·멱등 경로는 mock-only 금지.
- **타입**: `mypy .`(strict) CI 통과.
- **린트**: `ruff check`에 `B,SIM,C4` 추가 후 클린.
- **마이그레이션**: 멱등 고유제약 추가 시 `alembic revision --autogenerate` → 파일 검토 → 실 DB 증분 적용 확인(단일 선형 유지).

---

## §5 Do-Not (깨지 말 것)

- **Stripe `construct_event`**(300s 타임스탬프 허용오차) 검증 — 이미 올바름, 우회·약화 금지.
- CI **secret-scan(gitleaks) 잡** 유지.
- **테넌트별 DB 시크릿 방식**(`customer.webhook_secret`) — 멀티테넌시 핵심, 전역 단일 시크릿으로 회귀 금지.
- 시크릿(`.env`·webhook secret·토큰)을 코드·로그·커밋에 노출 금지.

---

## §6 Open Questions

- **GitHub 리플레이(M6)**: GitHub 웹훅 서명 스킴은 프로토콜상 타임스탬프가 없어 Stripe식 시간검증이 불가하다.
  멱등 TTL을 공급자 재시도 윈도우 이상으로 두고 **한계를 문서화**하는 선에서 수용할지, 아니면
  애플리케이션 레벨 nonce/수신시각 저장으로 보강할지 결정 필요.

---

> 신규 부채는 harness-guard v0.7.0 게이트가 차단한다 — 이 문서는 **기존 부채 정리용**이다.
