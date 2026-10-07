# 품질 리메디에이션 로드맵 — webhook-service

> 2026-06 감사 원본(아래 §0–§6)을 보존한다. 현재 상태는 다음 재대조를 따른다.

## 2026-10-07 Keycloak SDK 전환 수용 계약 (구현 전 고정)

`python-keycloak==7.1.1`을 후보로 고정한다. [공식 PyPI](https://pypi.org/project/python-keycloak/)는
이 판이 Python 3.11과 Keycloak 22.X를 지원한다고 명시한다. 설치된 SDK 7.1.1 원본에서
`decode_token(token, validate=True, **kwargs)`는 `jwcrypto`의 JWK와 JWT 검사 옵션을 받는다.
PyPI의 배포 상태 classifier는 `3 - Alpha`이므로 이 지원 표기를 안정성 보증으로 해석하지 않는다.
기존 `options={...}`와 PEM 문자열을 넘기는 호출은 호환되지 않는다. 두 소비자(관리자 UI와
Replay API)가 하나의 검증 함수를 사용하도록 하고, realm 공개키를 JWK로 변환한 뒤
`algs=["RS256"]`, `leeway=0`, 만료 claim 필수 검사를 명시한다. 기존 audience 비검증
정책은 유지하며 issuer/audience의 실제 외부 설정은 **미확인**으로 둔다.

선행 RED와 최종 수용 범위: 설치된 SDK의 합성 HTTP Keycloak과 자체 RSA 키를 써서
root URL(끝 `/` 유무)·realm/key/certs/token·코드 교환을 확인한다. 관리자 UI와 Replay
API 모두 실제 서명된 미래 만료 admin 토큰을 허용하고 현재보다 10초·120초 지난 토큰,
만료 claim 누락, 잘못된 서명·다른 키·HS256/none 알고리즘을 교환/DB 조회 전에 거부한다.
`realm_access.roles`는 정확한 `admin` 문자열을 담은 목록만 허용한다. 기존 서명 세션과
Redis의 300초 atomic state 회수·다른 브라우저/이전 쿠키 재사용/공급자 오류 차단도 유지한다.
기존 시험을 건너뛰거나 거부 기대를 느슨하게 하지 않는다. 전체 런타임 의존성 감사와
개발 도구 의존성 검사를 분리해 기록하고, 외부 Keycloak 연결은 실행하지 않는다.

## 2026-10-07 현재 원본 재대조와 QA 범위

상태: **로컬 기능·품질 검사 PASS, 7.1.1의 해석된 런타임·개발 의존성 보안 검사 PASS,
시험 전용 실제 Keycloak 22 로그인/역할 검사 PASS, 원격 CI·리뷰·병합 미실행**.
남은 행동은 운영 Keycloak 설정·issuer/audience 정책을 확인하고 이 브랜치의 PR에서
CI/리뷰/required check를 확인하는 것이다. 시험용 realm의 성공을 운영 연동 완료로 확대하지 않는다.

기준: `origin/develop` 83cd3989298636436ad1f26e734d0678f88d7440에서 시작한
`fix/harness-qa-contract`. 아래의 '구현 확인'은 코드·검사 존재 판정이며, 이 브랜치의
CI·리뷰·병합·배포 완료를 뜻하지 않는다.

| 감사 항목 | 현재 원본과 남은 행동 |
|---|---|
| H1 | `tests/test_integration_webhooks.py`의 GitHub/Stripe 실서명 허용·거부와 `tests/test_unit_signatures.py` 확인. 이 브랜치 전체 pytest로 실행 판정. |
| M1, L4 | `app/main.py`가 tenant 포함 Redis NX 예약을 큐 실패 때 해제하고, `webhook_events`에 고유제약이 있다. 기존 `tests/test_idempotency.py`는 삭제 mock만 보았으므로 실제 PostgreSQL·Redis·worker 재시도 회귀를 이 브랜치에 추가. |
| M2 | `/health`가 비동기 DB 세션을 사용하고 `tests/test_health.py`가 유지 검사를 제공한다. |
| M3, M5 | CI에 Ruff format/lint와 mypy 게이트가 있고 Celery `customer_id`는 `str`이다. `pyproject.toml`의 mypy는 `strict=true`가 아니므로 §2의 strict 요구는 **미완료**다. 이 작업에서 기존 타입 정책을 확대하지 않는다. |
| M4, L3 | admin 하드삭제는 `can_delete=False`; 처리 태스크는 `PROCESSED`/`FAILED` 상태를 기록한다. `deleted_at`을 도입한 것은 아니다. |
| M6 | GitHub 프로토콜의 시간 정보 부재와 24시간 Redis TTL의 리플레이 한계는 §6의 미결정 그대로다. |
| M7 | `app/main.py`에 공통 에러 Envelope 핸들러가 있고 `tests/test_envelope.py`가 확인한다. |
| L1, L2 | 현재 CI는 GitHub 웹훅 시크릿을 참조하지 않고 현재 `app/config.py`에는 과거 전역 시크릿 설정이 없다. 과거 파일·라인 근거는 현재 결함 근거로 재사용하지 않는다. |

보안 감사에서 직접 고정 의존성의 `python-dotenv`, `Mako`, `SQLAdmin` 취약점이
나왔다. [dotenv](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94),
[Mako](https://github.com/sqlalchemy/mako/security/advisories/GHSA-2h4p-vjrc-8xpq),
[SQLAdmin 접근 제어](https://github.com/smithyhq/sqladmin/security/advisories/GHSA-54mc-gghv-4cfj)와
[정렬 검증](https://github.com/smithyhq/sqladmin/security/advisories/GHSA-ccg5-9c8w-xh6v)의
수정판으로 갱신했다. SQLAdmin 0.27.1은 Starlette 1.x를 요구하고 기존 FastAPI 0.117 및
Instrumentator 7.1은 이를 허용하지 않아, 공식 호환 범위인 FastAPI 0.133.0,
Starlette 1.3.1, Instrumentator 8.0.1 조합을 격리 resolver와 제품 회귀로 확인했다.
이 변경은 API 응답·admin 로그인·메트릭 경계를 다시 검사해야 하는 스택 변경이다.

### 이전 `eba4bfb` 후보의 의존성 실패 기록

이전 후보의 해석된 런타임 의존성 전체 감사에는 **남은 경고**가 있었다: `python-keycloak==2.0.0`이
`urllib3==1.26.20`과 `python-jose==3.5.0`(그 하위 `ecdsa==0.19.2`)을 끌어온다.
Keycloak은 `app/main.py`, `app/admin.py`, `app/dependencies.py`의 토큰 검증과
관리자 로그인에서 사용 중이다. `python-keycloak` 2.16.6은 resolver상 `urllib3` 제약을
풀지만 현 로컬 환경에서 `pkg_resources` import로 pytest 수집이 실패했다.
[공식 변경 기록](https://github.com/marcospereirampj/python-keycloak/blob/master/CHANGELOG.md)의
3.9.1은 `python-jose`를 교체하지만 major 인증 라이브러리 변경이다. 당시에는 실 Keycloak
연결·서명/만료/권한 회귀가 필요한 후속으로 남겼다. 그 후보의 시험은 자체 생성 RSA 키와
합성 Keycloak HTTP 응답으로 설치된 SDK 경로의 서명·만료·역할을 확인했지만 외부
Keycloak 서버와 issuer·audience 정책은 확인하지 않아 인증 연동 전체를 PASS로 판정하지 않는다.
그 당시 `python-keycloak` 2.0.0의 `decode_token` 기본값은 `algorithms=["RS256"]`이고
제품 호출부는 이를 넓히지 않는다. 따라서
[python-jose 알고리즘 혼동](https://github.com/advisories/GHSA-3qf3-8w2g-rqmx)의
"알고리즘을 제한하지 않는" 전제는 이 호출부에서는 관찰되지 않는다(코드 기반 추론).
`ecdsa`의 [별도 경고](https://github.com/tlsfuzzer/python-ecdsa/security/advisories/GHSA-wj6h-64fc-37mp)도
그 당시 RS256 검증 경로에서 사용 여부가 확인되지 않았다. 이 추론은 당시 라이브러리
감사의 FAIL을 지우지 않았다. 7.1.1 전환은 `python-jose`·`ecdsa` 경로를 제거하고
resolver가 `urllib3==2.8.0`을 선택했다. 새 전체 그래프 감사 결과는 QA 기록에 둔다.

이번 변경의 필수 QA 판정자는 다음과 같다. 실 서비스는 이 시험 전용
PostgreSQL 15(`127.0.0.1:55441`)과 Redis 7(`127.0.0.1:56381`)을 사용하며,
CI에서는 격리된 서비스 DB/Redis를 사용한다. 별도 로컬 검증은 loopback 시험용
Keycloak 22.0.5를 사용했고 운영 Keycloak·메일·운영 worker는 포함하지 않는다.

| 요구·위험 | 조건과 기대 결과 | 관찰 경계 | 필수 |
|---|---|---|---|
| 실패 후 유실 방지 | 유효 GitHub 서명 요청의 첫 broker 게시 실패 → 500, 실제 Redis 예약키 없음·큐 0건 | API + Redis | 예 |
| 같은 delivery 재시도 | 동일 요청 재시도 → 202, 예약키 1개·큐 1건; worker 처리 뒤 DB `PROCESSED` 1건 | API + Redis + 실제 worker + PostgreSQL | 예 |
| 중복 억제 | 같은 delivery 세 번째 요청 → 중복 응답, 큐/DB 추가 0건 | API + Redis + PostgreSQL | 예 |
| 유지 동작 | 실서명 허용·거부, 기존 멱등/DB 고유제약, 전체 pytest와 Ruff/mypy/Alembic 단일 head | 제품 검사 | 예 |
| 로컬 훅 격리 | 주입한 시험 DB/Redis 주소로 pre-commit 전체 훅 PASS, 기존 훅의 5433 강제 주입은 실패 재현, 다른 DB 주소는 연결 전 거부 | 훅 + 시험 환경 경계 | 예 |
| 실서비스 시험 진입 경계 | 관리자 DDL·큐 회귀 전에 공통 fixture가 환경 변수, 실제 DB engine, Redis URL, Celery broker 읽기/쓰기·result backend를 같은 `127.0.0.1` 격리 서비스로 확인; 다른 DB·broker·result·IPv6·호스트 접미사는 연결/게시 전에 거부 | fixture + 거부 회귀 | 예 |
| libpq 우회·출력 경계 | `PGHOSTADDR`·`PGSERVICE`·`PGSERVICEFILE`·`PGSYSCONFDIR`의 존재를 DDL 전 거부하고, URL·engine·Celery 비교 실패는 인증정보를 포함하지 않는 메시지만 출력 | fixture + libpq 주입/합성 userinfo 회귀 | 예 |
| dotenv 시험 경계 | `pytest.ini`가 `pytest-dotenv` 시작 단계 훅을 차단하고, pytest bootstrap이 앱 설정 최초 import 전에 Pydantic `_env_file=None`을 적용한다. 합성 dotenv 파일에서 플러그인 비활성·값 유입 없음·파일 읽기 호출 0을 확인 | 시작 단계 subprocess + bootstrap + 합성 파일 회귀 | 예 |
| Keycloak SDK URL·관리자 코드 교환 | 설치된 `python-keycloak==7.1.1`에 서버 root URL(끝 `/` 유무)을 전달하면 실제 SDK의 realm/key/certs/token 요청이 단일 `/realms/{realm}`로 간다. SQLAdmin mount 앞에 등록된 GET 로그인·callback은 실제 URL을 사용하고 SDK `token(code, grant_type="authorization_code", redirect_uri)`로 교환한다. 코드 누락·공급자 오류는 새 토큰을 저장하지 않는다 | 합성 HTTP + TestClient 및 loopback Keycloak 22/Chrome 실제 코드 교환 | 예 |
| 관리자 로그인 state·권한 | 로그인마다 암호학적 임의 state를 서명 세션과 기존 Redis에 300초 저장하고 callback에서 정확한 세션 일치·기한·원자적 GETDEL을 확인한다. 다른 브라우저·누락·불일치·만료·미래시각·이전 서명 쿠키 재사용은 교환 전 거부하며 Redis 실패도 닫힌다. 서명·만료가 유효한 `realm_access.roles` 목록의 정확한 `admin`만 관리자 UI 허용; 비관리자·형식 오류·서명 오류·만료는 세션을 지우고 목록 DB 질의 0. API Replay 역시 실제 SDK 서명 검증 후 정확한 admin 목록만 허용한다 | 합성 RSA·Keycloak HTTP + TestClient; 시험 전용 실제 Redis GETDEL 동시 두 소비자; 외부 Keycloak 없음 | 예 |
| CI 게시 경계 | PR·develop push는 게시 job 조건 불충족, main push에서만 품질 job 성공 후 게시; 기존 `build-and-test` 이름 유지 | workflow 정적 검사 | 예 |
| commitlint 신뢰 경계 | 기존 `commitlint.yml` 유지, 정본 `commitlint-trusted.yml` 파일 추가; 원격 required check 활성 여부 별도 확인 | 파일 비교 + GitHub 상태 | 파일 비교 예 / 원격 활성 미확인 |
| 관리자/메트릭 호환 | 익명 AJAX lookup 로그인 이동, 허용 정렬 200·숨긴 `payload` 정렬 400, `/metrics` 200과 요청 계수 | 실제 HTTP + PostgreSQL | 예 |
| 패키지 보안 | 런타임 전체 74개·개발 포함 전체 91개 해석 그래프 감사에서 취약점 0건. 이전 후보 15건 FAIL은 별도 과거 기록으로 유지 | `uv pip compile` 그래프 + `pip-audit --disable-pip --no-deps` 원문 | 예 |

실행 기록은 [2026-10-07 QA 기록](../qa/2026-10-07/README.md)에 기준 SHA·실행 환경·
명령·종료 코드·원문 로그와 함께 남긴다.

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

## 2026-10-07 원격 전달 단계

기존 로컬 후보 `2d082815`의 파일 트리를 보존하고, 미게시 커밋의 메시지 형식 오류를 해소하기 위해 원격 전달용 단일 커밋으로 묶었다. 기존 커밋은 `codex/evidence-webhook-2d08281`에 보존한다. 앱·시험·의존성·workflow 입력은 동일하며 기존 SDK 7.1.1 검증 원문은 당시 후보의 증거다. PR은 develop을 대상으로 기존 필수 `commitlint`를 유지한다. main/default trusted 검사 배치·필수 검사 전환·GHCR 게시·운영 배포는 이번 develop 인수의 완료 범위에 포함하지 않는다. 실제 원격 CI·리뷰·병합 결과는 전달 PR에서 확인하며 미실행을 PASS로 표시하지 않는다.
