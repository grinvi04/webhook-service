# 2026-10-07 webhook-service 로컬 QA 기록

## `eba4bfb` 이후 python-keycloak 7.1.1 전환 후보

기준은 로컬 부모 `eba4bfb2b27358ac4aca399548712c1eb39d5d4c`다.
[공식 PyPI](https://pypi.org/project/python-keycloak/)는 7.1.1의 Python 3.11·Keycloak
22.X 지원을 명시한다. 실제 설치된 7.1.1은 `decode_token(token, validate=True, **kwargs)`와
`jwcrypto` JWK를 사용한다. 기존 PEM/`options` 인자는 [첫 RED](keycloak711-red.txt)에서
정상 관리자·Replay까지 5건 실패했다. [확장 RED](keycloak711-contract-red.txt)는
추가 거부 반례와 함께 7건 FAIL·24건 PASS였다. 여기서 HS256 합성 키가 256비트 미만이라
시험 자료 생성 자체가 실패한 2건도 구분했다. [초기 GREEN 시도](keycloak711-focused-green.txt)는
테스트 파일 들여쓰기 오류로 수집 실패했고 곧바로 교정했다. 이들은 최종 PASS로 소급하지 않는다.
PyPI의 배포 상태 classifier는 `3 - Alpha`다. 따라서 공식 지원 범위와 이 로컬 회귀의
통과를 라이브러리 전반의 안정성 보증으로 확대하지 않는다.

공유 검증 함수는 realm `public_key`를 JWK로 변환해 SDK에 `algs=["RS256"]`,
`leeway=0`을 전달한다. 설치된 `jwcrypto 1.6.1`은 `check_claims=None`일 때 존재하는
`exp`와 `nbf`를 검증하므로, SDK 검증 후 `exp` 존재를 추가로 요구한다. 관리자 UI와
Replay API가 같은 함수로 검증한다. 자체 RSA의 정상 admin은 허용하고 비관리자·
문자열 역할·잘못된 서명/키·HS256/none·만료 10초/120초·`exp` 누락은 거부한다.
[집중 시험](keycloak711-focused-green.txt)은 교정 후 같은 이름으로 재실행되어
31건 PASS다. 최초 수집 실패 원문은 대화의 도구 출력에 남았으나 동일 파일 경로를
재사용해 파일 원문은 보존되지 않았다. 이 한계를 지문 manifest에서 숨기지 않는다.

시험 전용 PostgreSQL 15·Redis 7(`127.0.0.1:55441/56381`)과 Python 3.11의 새
`/tmp/webhook-keycloak711-candidate/fullvenv`를 사용했다. 모든 pytest·pre-commit
자식에는 `/tmp/webhook_auth_qa_runner.py`로 네 서비스 URL과 합성 세션 키를 명시
주입하고 `PGHOSTADDR`·`PGSERVICE`·`PGSERVICEFILE`·`PGSYSCONFDIR` 및
`PYTEST_ADDOPTS`를 제거했다. 제품 `.env`를 직접 열지 않았으며 시험 bootstrap의
Pydantic `_env_file=None`과 `pytest.ini`의 `-p no:dotenv`는 유지했다.
macOS Python은 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`로 실행했다.

| 실행 명령·대상 | 원문 | 결과 |
|---|---|---|
| 새 venv `pytest -q --tb=short` | [전체](keycloak711-full-fresh.txt) | 종료 0, 110 PASS·경고 3건 |
| `.venv/bin/ruff format --check .`, `ruff check .`, `mypy app`, `alembic heads` | [format](keycloak711-format.txt), [lint](keycloak711-lint.txt), [mypy](keycloak711-mypy.txt), [Alembic](keycloak711-alembic.txt) | 모두 종료 0, 단일 head `634bbf55b755` |
| `.venv/bin/pre-commit run --all-files` | [초기](keycloak711-precommit.txt), [최종](keycloak711-precommit-final.txt) | 초기 1: formatter가 시험 파일을 수정; 최종 0: Ruff·mypy·pytest 전체 PASS |
| `uv pip compile requirements.txt`로 고정한 [런타임 74패키지](keycloak711-runtime-resolved.txt) → `pip-audit --disable-pip --no-deps -r` | [감사](keycloak711-runtime-audit.txt) | 종료 0, 알려진 취약점 0 |
| `uv pip compile requirements.txt requirements-dev.txt`로 고정한 [개발 포함 91패키지 그래프](keycloak711-dev-resolved.txt) → 같은 `pip-audit` | [감사](keycloak711-dev-audit.txt) | 종료 0, 알려진 취약점 0 |
| 직접 `pip-audit -r requirements.txt` | [환경 실패](keycloak711-audit.txt) | 종료 1: macOS 임시 venv `ensurepip` SIGABRT; resolver 전체 pin으로 대체 검사. 직접 pin만의 성공으로 확대하지 않음 |

추가로 공식 `quay.io/keycloak/keycloak:22.0.5`를 자체 새 컨테이너의
`127.0.0.1:58080`에 띄워 `qa-realm`·`qa-client`·시험용 admin/viewer를 만들었다.
[SDK/실서비스 probe](keycloak711-provider-probe.txt)는 실제 well-known·certs·realm
공개키·password-grant token 후 관리자 Replay 404(인증·역할 통과 후 시험 고객 없음),
viewer 403, 관리자 UI 200, viewer UI 302를 확인했다. 별도 FastAPI 서버는
`127.0.0.1:58081`이고 앱 import 전에 시험 전용 `_env_file=None`을 적용했다.
[Chrome probe](keycloak711-browser-probe.txt)는 두 사용자 각각 GET `/admin/login`
→ 실제 Keycloak 로그인 → authorization code callback → admin 200/viewer 302를 확인했다.
callback의 300초 state는 기존 시험용 Redis의 원자적 `GETDEL`을 사용했다.
[바인딩 증거](keycloak711-service-binding.txt)는 DB/Redis/Keycloak와 앱 서버가 모두
loopback이라는 것을 보인다. [종료 증거](keycloak711-service-stopped.txt)는
세 컨테이너와 앱 서버가 멈춘 상태를 확인한다. Chrome 첫 시도에서 viewer는 보호 경로가 로그인으로
재이동해 단일 URL 대기가 실패했다(도구 출력 관찰; 최초 파일은 덮어써 미보존).
수정 probe는 callback 응답과 그 후 보호 경로 상태를 따로 확인해 두 사용자 모두 통과했다.
새 Keycloak 컨테이너는 [제거 기록](keycloak711-service-removed.txt) 후 없앴고
시험 사용자 비밀번호 파일도 삭제했다. 기존 시험용 PostgreSQL·Redis는 멈춘 채 보존했다.

운영 Keycloak realm·redirect URI·issuer/audience 정책·키 회전은 **UNVERIFIED**다.
새 SDK로도 기존 issuer/audience 비검증 의미를 유지했으며 이 정책을 검증 완료로
표현하지 않는다. 원격 CI·리뷰·병합·배포도 아직 실행하지 않았다. 이전 후보의
15개 advisory FAIL과 2.16.6/3.9.1 비교 원문은 아래 과거 기록으로 보존한다.

아래 초기 후보 표는 `origin/develop`의 `83cd3989298636436ad1f26e734d0678f88d7440`에서 분기한
`fix/harness-qa-contract`의 초기 커밋 `2c4158a1ffc507fce7d260e23214ddac7c476684` 후보 기록이다.
실행은 macOS, Python 3.11 `.venv`,
격리 PostgreSQL 15(`127.0.0.1:55441/webhook_qa`)과 Redis 7(`127.0.0.1:56381/0`)
에서 했다. 모든 Python 실행은 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`를
설정했다. DB·Redis·Celery URL, 세션 비밀, Keycloak 주소는 시험 전용 환경 변수로 주입했다.
AI는 제품 `.env` 내용을 직접 열람하거나 출력하지 않았다. 다만 초기 `2c4158a`·`d098aa7`
후보에는 Pydantic 자동 dotenv 로딩 차단이 없었으므로 앱 설정 생성 시 파일 읽기 여부는
**미확인**이다. 시험의 DB·Redis·Celery URL은 명시 환경 변수였고 실제 운영 목적지
연결 증거는 없지만, 그 사실만으로 dotenv 파일 읽기 부재를 소급해 단언하지 않는다.
외부 Keycloak·메일·운영 worker는 호출하지 않았다.

## `5fd2213` 이후 관리자 OAuth·Keycloak SDK 경계 (이전 후보 기록)

실제 설치된 `python-keycloak==2.0.0`의 URL 합성·`token` API와 SQLAdmin 라우트
mount 순서를 대조했다. 이전 구현은 서버 URL에 realm을 중복 붙이고, mount 뒤에
callback을 등록해 404로 가렸으며, 존재하지 않는 `exchange_code_for_token`을
호출했다. 관리자의 GET 로그인도 SQLAdmin의 로그인 폼(200)으로 들어갔다.
[최초 RED](keycloak-sdk-red.txt)는 5개 실패로 이 불일치를 고정한다.

현재 후보는 root URL에서 SDK가 realm/key/certs/token 경로를 한 번 구성한다.
로그인·callback을 mount 전에 등록해 정확한 callback URL을 사용하고, SDK가 생성한
auth URL 끝 공백을 제거한다. 서명된 세션 state와 300초 Redis 예약을 생성한 뒤,
callback에서 세션 일치·시각·원자적 `GETDEL`을 검사하고 코드 교환 전에 소비한다.
이전 서명 쿠키로의 재호출도 새 토큰 교환 0건이다. 공급자 오류와 Redis 오류는
새 토큰을 저장하지 않는다. 새 로그인은 과거 세션 토큰을 제거한다.

공유 공개키 helper는 Keycloak realm 응답의 base64 DER를 PEM으로 정규화해
관리자 UI와 API Replay의 실제 SDK `decode_token`이 같은 키를 사용한다.
관리자 UI와 Replay는 `realm_access.roles`가 목록이고 정확한 `admin`이 있을 때만
허용한다. 이 시험에서 유효 서명 admin UI 대시보드는 200, 비관리자·누락·형식
오류·서명 오류·만료·HS256은 거부되었고, UI 거부 때 목록 DB 연결은 0건이었다.
Replay의 admin은 인증·역할 통과 뒤 합성 고객 조회까지 도달한 404이고, 비관리자는
403, 잘못된 서명·만료는 401이다. callback은 토큰 교환 후 `/admin`으로 이동하며,
역할 검사는 그 다음 보호된 관리자 경로에서 실행된다.

아래 원문은 `5fd22130c58df45cbec5c37653bfa792a4550eaf`에서 수정한 파일을
대상으로 했다. 실행 시 Docker 시험 컨테이너 메타데이터의 DB 자격증명을 출력하지 않고
`DATABASE_URL`에 주입했고, Redis 세 URL은 `127.0.0.1:56381/0`, Keycloak URL은
`https://qa-keycloak.invalid`로 지정했다. `SESSION_SECRET`은 합성값이며
`PGHOSTADDR`·`PGSERVICE`·`PGSERVICEFILE`·`PGSYSCONFDIR`과 `PYTEST_ADDOPTS`는
자식 실행에서 제거했다. 명령은 `.venv`와
`/tmp/webhook-qa-venv-20261007` 각 환경의 `pytest tests/ -q --tb=short`,
`pytest tests/test_keycloak_contract.py -q --tb=short`, `.venv/bin/ruff check .`,
`.venv/bin/ruff format --check .`, `.venv/bin/mypy`, `.venv/bin/alembic heads`,
`.venv/bin/pre-commit run --all-files`다. macOS Python에는
`DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`를 설정했다.

| 주장 / 명령(명시 시험 URL·합성 Keycloak 주소) | 원문 | 판정 |
|---|---|---|
| 최초 SDK·라우팅 RED | [keycloak-sdk-red.txt](keycloak-sdk-red.txt) | 종료 1, 5 FAILED |
| state·역할 확장 중 시험 fixture/허용 경계 실패 | [keycloak-state-role-candidate.txt](keycloak-state-role-candidate.txt) | 종료 1, 8 FAILED·5 PASS; 수동 쿠키 도메인/마운트 앱 참조 문제를 찾아 교정. 실패 assertion의 합성 JWT 값만 문서 저장 전에 가렸다 |
| 관리자·API 경계 25건 + 실제 Redis `GETDEL` 동시 두 소비자 | [keycloak-auth-target-final.txt](keycloak-auth-target-final.txt) | 종료 0, 25 PASS |
| 전체 제품 pytest·새 Python 환경 전체 pytest | [pytest-auth-full-final.txt](pytest-auth-full-final.txt), [pytest-auth-fresh-final.txt](pytest-auth-fresh-final.txt) | 각각 종료 0, 104 PASS |
| Ruff lint·format·mypy·Alembic head | [lint](ruff-check-auth-final.txt), [format](ruff-format-auth-final.txt), [타입](mypy-auth-final.txt), [마이그레이션](alembic-auth-final.txt) | 모두 종료 0; head `634bbf55b755` 하나 |
| 격리 환경 주입 `.venv/bin/pre-commit run --all-files` | [precommit-auth-final.txt](precommit-auth-final.txt) | 종료 0; Ruff·mypy·pytest 훅 전체 PASS |
| 시험 전용 서비스 | [시작 바인딩](service-binding-auth-final.txt), [최종 종료](service-stopped-auth-final.txt) | PostgreSQL·Redis 모두 `127.0.0.1` 전용 바인딩 후 `exited` |

이는 **자체 생성 RSA·합성 HTTP와 시험 전용 로컬 Redis**에 한정한다. 외부
Keycloak 실제 realm·redirect 설정·issuer·audience·키 회전·브라우저 상호 운용성은
**UNVERIFIED**다. Python-keycloak의 나머지 의존성 감사 15건도 기존 FAIL 그대로이며
원격 CI/required check·게시 결과를 로컬 성공으로 대체하지 않는다. 이전 후보의
pytest 시작 단계 dotenv 차단은 유지했고 제품 `.env` 내용은 열거나 출력하지 않았다.

## `096bdfd` 검토 후 pytest 시작 단계 dotenv 차단 (이전 후보)

이전 `096bdfd` 후보는 Pydantic 설정의 dotenv provider만 차단했다. 설치된
`pytest-dotenv==0.5.2`는 `pytest.ini`의 `env_files=.env`를 읽고,
`pytest_load_initial_conftests`에서 `tests/conftest.py`보다 먼저
`find_dotenv`·`load_dotenv`를 호출할 수 있었다. 따라서 이전 후보의
“제품 `.env` 자동 읽기 차단” 완료 판정은 **잘못됐으며**, 그 당시 실제 파일의
읽기 여부는 확인하지 않았다. 제품 `.env` 내용을 열거나 출력하지 않았다.

[pytest 공식 플러그인 문서](https://docs.pytest.org/en/latest/how-to/plugins.html)는
프로젝트 설정의 `addopts = -p no:NAME`으로 설치된 플러그인을 시작 단계에서
비활성화할 수 있다고 명시한다. `pytest.ini`는 `-p no:dotenv`를 적용하고
오래된 `env_files=.env`를 제거했다. `requirements-dev.txt`의 패키지는
비활성화 회귀를 검증하기 위해 그대로 설치한다. 새로운 subprocess 회귀는
시험 소유 임시 디렉터리의 합성 `.env`만 사용하며 Python `sitecustomize`로
`find_dotenv`·`load_dotenv` 호출을 실패로 바꾼다. 플러그인 entry point가
설치돼 있는 상태에서 자식 pytest의 플러그인 비활성, 합성 환경값 미유입,
계측 코드 실행, 탐색·로드 호출 0을 확인한다.

| 주장 / 명령(격리 환경 변수 적용) | 원문 로그 | 종료 코드 / 판정 |
|---|---|---|
| 첫 회귀 시도 | [환경 누락 원문](pytest-startup-red.txt) | 4 / Pydantic bootstrap의 명시 서비스 URL이 없어 수집 실패; dotenv 반례 판정 전 환경 오류 |
| 이전 설정에서 바깥 pytest만 `-p no:dotenv`로 보호하고 합성 `.env` 자식 실행 | [시작 훅 RED](pytest-startup-red-explicit-env.txt) | 1 / 자식의 `pytest_load_initial_conftests`가 `find_dotenv` 호출을 시도해 실패 |
| 현재 `pytest.ini`로 같은 합성 `.env` 자식 실행 | [시작 훅 GREEN](pytest-startup-green.txt) | 0 / PASS, 플러그인 비활성·값 미유입·탐색/로드 호출 0 |
| QA 컨테이너 HostIp·HostPort와 종료 | [연결 범위](service-binding-startup-final.txt), [종료](service-stopped-startup-final.txt) | 각 0 / PostgreSQL·Redis는 `127.0.0.1` 전용 바인딩, 검사 후 `exited` |
| 기존 환경·새 Python 환경 `pytest tests/ -q` | [전체](pytest-startup-full-final.txt), [새 환경 전체](pytest-startup-fresh-final.txt) | 각 0 / PASS, 각각 79개 |
| Ruff·format·mypy·Alembic head·pre-commit 전체 훅 | [lint](ruff-check-startup-final.txt), [format](ruff-format-startup-final.txt), [타입](mypy-startup-final.txt), [마이그레이션](alembic-startup-final.txt), [훅](precommit-startup-final.txt) | 모두 0 / PASS |

이 결과는 현재 로컬 후보의 pytest 시작·Pydantic 설정·실서비스 시험 경계에
한정한다. 전체 의존성 감사 15개 경고와 실 Keycloak·원격 CI 미확인은 그대로다.

## `d098aa7` 검토 후 dotenv bootstrap 보완 (`096bdfd` 후보 기록)

제품 `app/config.py`의 `model_config.env_file='.env'`는 그대로 둔다.
[Pydantic 공식 문서](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#dotenv-env-support)는
생성자 `_env_file=None`이 class config의 파일 로딩도 비활성화한다고 명시한다.
설치된 pydantic-settings 2.10.1의 `main.py:368`은 `DotEnvSettingsSource`를
`settings_customise_sources` 호출(`main.py:385`) **전에 생성**하고,
`sources/providers/dotenv.py:89`에서 파일 읽기 경로를 결정한다. 따라서
`tests/conftest.py`가 `app.config` 최초 import 전에 시험 전용 `BaseSettings.__init__`
wrapper로 `_env_file=None`을 주입하고, 이미 import됐거나 명시 파일 인자가 있으면
고정 메시지로 실패시킨다. 합성 dotenv 파일은 임시 시험 디렉터리에만 만들었다.

| 주장 / 명령(격리 환경 변수 적용) | 원문 로그 | 종료 코드 / 판정 |
|---|---|---|
| 합성 dotenv 파일 시험 | [최초](pytest-dotenv-candidate.txt), [최종](pytest-dotenv-bootstrap-final.txt) | 각 0 / PASS; 파일 값 fallback 없음, provider `_read_env_file` 호출 0, 명시 파일 인자 거부 |
| `.venv/bin/pytest tests/ -q` | [전체](pytest-dotenv-full-final.txt) | 0 / PASS, 78개 |
| 새 Python 환경 `/tmp/webhook-qa-venv-20261007/bin/pytest tests/ -q` | [새 환경 전체](pytest-dotenv-fresh-final.txt) | 0 / PASS, 78개 |
| Ruff·format·mypy·pre-commit 전체 훅 | [lint](ruff-check-dotenv-final.txt), [format](ruff-format-dotenv-final.txt), [타입](mypy-dotenv-final.txt), [훅](precommit-dotenv-final.txt), [정확한 DB 계정으로 재검증한 훅](precommit-dotenv-commit-credential-final.txt) | 모두 0 / PASS |
| 시험 전용 컨테이너 종료 확인 | [종료 원문](service-stopped-final.txt) | 0 / PostgreSQL·Redis 두 컨테이너 모두 `exited` |
| 커밋 훅 첫 실행의 임시 DB 인증 실패 확인 | [진단](qa-auth-metadata-probe.txt) | 처음에는 시험 컨테이너 사용자를 `postgres`로 잘못 가정해 76 PASS·2 인증 오류로 훅 실패; 컨테이너 메타데이터의 실제 사용자·비밀번호·DB 조합은 직접 드라이버 연결 PASS. 첫 훅의 전체 stdout은 파일로 남기지 못했으며 당시 도구 출력에서 결과를 확인했다. DB 자격증명은 변경하지 않았다. |

이 시험은 당시 후보의 Pydantic 설정 경로만 확인했다. pytest 시작 플러그인 경로는
확인하지 못했으며 위의 새 후보에서 차단했다. 제품 설정 자체와 과거 후보의 실행
결과는 변경하지 않는다. libpq·출력 경계의 77개 검사는 아래 당시 후보로 보존하고,
같은 회귀 17개는 당시 78개 전체 시험에 포함됐다.

## `d098aa7` 검토 후 libpq·출력 경계 보완 (dotenv 차단 이전 후보)

[PostgreSQL libpq 환경 변수 문서](https://www.postgresql.org/docs/current/libpq-envars.html)는
`PGHOSTADDR`와 서비스 설정 변수를 연결 기본값으로 정의한다.
[libpq 접속 문서](https://www.postgresql.org/docs/current/libpq-connect.html)는 URL의 `host`와
`hostaddr`가 함께 있으면 실제 서버 주소에 `hostaddr`를 사용한다고 명시한다.
따라서 공통 fixture는 `PGHOSTADDR`·`PGSERVICE`·`PGSERVICEFILE`·`PGSYSCONFDIR`의
**존재 자체**를 DB DDL 전에 거부한다. 변수 값은 읽거나 출력하지 않았다.
기존 URL·engine·Celery 비교도 실패할 때 인증정보가 아닌 고정 문구만 출력한다.

| 주장 / 명령(격리 환경 변수 적용) | 원문 로그 | 종료 코드 / 판정 |
|---|---|---|
| QA 컨테이너 HostIp·HostPort 확인 | [service-binding-followup.txt](service-binding-followup.txt) | 0 / PostgreSQL 15은 `127.0.0.1:55441`, Redis 7은 `127.0.0.1:56381`에 바인딩 확인 |
| `pytest tests/test_qa_isolation.py -v` | [libpq·출력 17건](pytest-libpq-userinfo-final.txt) | 0 / PASS; `PGHOSTADDR=127.0.0.2` 등 4개 변수 주입 시 DDL·engine/libpq connect·Celery 게시 0, 합성 userinfo 3경로 실패 출력 비노출 및 기존 누출형 assertion을 검출하는 대조군 포함 |
| 두 실서비스 시험에 `PGHOSTADDR=127.0.0.2` 주입 | [fixture 거부](pytest-pghostaddr-live-reject.txt) | 1 / 기대한 거부, 두 시험 모두 fixture setup에서 중단하고 `OperationalError`·접속 호출 없음 |
| `.venv/bin/pytest tests/ -q` | [전체](pytest-libpq-full-final.txt) | 0 / PASS, 77개 |
| 새 Python 환경 `/tmp/webhook-qa-venv-20261007/bin/pytest tests/ -q` | [새 환경 전체](pytest-libpq-fresh-final.txt) | 0 / PASS, 77개 |
| `ruff check .` 최초 실패와 수정 후 실행 | [최초](ruff-check-libpq-final.txt), [통과](ruff-check-libpq-passed.txt) | 1 → 0, 대조군 assertion의 좌우 순서만 교정 |
| `ruff format --check .`, `mypy` | [format](ruff-format-libpq-final.txt), [타입](mypy-libpq-final.txt) | 모두 0 / PASS |
| 격리 DB·Redis 환경을 주입한 `.venv/bin/pre-commit run --all-files` | [훅](precommit-libpq-final.txt) | 0 / PASS, 당시 77개 회귀 포함 |

여기서 실제 libpq driver로 `127.0.0.2` 수신기에 접속하는 시험은 수행하지 않았다.
공식 우선순위 문서와, 그 변수가 있을 때 공통 fixture가 `psycopg2.connect` 전에
거부한다는 회귀가 이 변경의 근거다. 아래 의존성 그래프 감사의 15개 경고와 원격
Keycloak·CI 미확인은 그대로다.

## `2c4158a` 독립 검토 후 격리 경계 보완 (`d098aa7` 후보 기록)

두 실서비스 시험은 `tests/conftest.py`의 공통 fixture가 `DATABASE_URL`, `REDIS_URL`,
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`의 명시값·실제 settings·DB engine·Celery
읽기/쓰기 broker·result backend를 확인한 뒤에만 PostgreSQL DDL을 실행한다. 로컬에서는
DB `127.0.0.1:55441/webhook_qa`, Redis 세 경로 모두 `127.0.0.1:56381/0`만,
GitHub Actions에서는 각각 `127.0.0.1:5432/test_db`, `127.0.0.1:6379/0`만 허용한다.
기존 mocked 단위 시험은 이 fixture에 의존하지 않는다.

| 주장 / 명령(위 환경 변수 적용) | 원문 로그 | 종료 코드 / 판정 |
|---|---|---|
| `pytest tests/test_qa_isolation.py -q` | [거부 9건](pytest-isolation-reject-final.txt) | 0 / PASS; 다른 DB·broker·result·Redis DB·IPv6·호스트 접미사·Celery 읽기/쓰기 override·환경 미설정에서 DDL/연결/게시 호출 0 |
| 관리자 DDL 시험 + 실제 Redis/DB/worker 회복 시험 | [실서비스 2건](pytest-isolation-services-final.txt) | 0 / PASS |
| 두 실서비스 시험에 `5433/webhook_db` 주입 | [진입 거부](pytest-isolation-live-reject-final.txt) | 1 / 기대한 거부; 두 fixture setup 모두 DDL 전 assertion, 연결 시도 없음 |
| `.venv/bin/pytest tests/ -q` | [전체](pytest-followup-final.txt) | 0 / PASS, 69개 |
| 새 Python 환경 `/tmp/webhook-qa-venv-20261007/bin/pytest tests/ -q` | [새 환경 전체](pytest-fresh-env-followup-final.txt) | 0 / PASS, 69개 |
| `ruff check .`, `ruff format --check .`, `mypy`, `alembic heads` | [lint](ruff-check-followup-final.txt), [format](ruff-format-followup-final.txt), [타입](mypy-followup-final.txt), [마이그레이션](alembic-followup-final.txt) | 모두 0 / PASS, 단일 head |
| 격리 DB·Redis 환경을 주입한 `.venv/bin/pre-commit run --all-files` | [precommit-followup-final.txt](precommit-followup-final.txt) | 0 / PASS, Ruff·mypy·pytest 훅 모두 실행 |
| CI workflow 파싱·시험 URL·게시 조건·권한·commitlint 정본 비교 | [workflow-followup-final.txt](workflow-followup-final.txt) | 0 / PASS, 원격 실행은 미확인 |

거부 시험의 첫 구현은 pytest-mock의 읽기 전용 `AsyncEngine.connect` 패치와 Celery
설정 복원이 잘못돼 실패했다([최초 원문](pytest-isolation-candidate.txt),
[중간 원문](pytest-isolation-fixed.txt)). 실제 Celery `broker_url` 속성은 환경 변수를
우선하므로 읽기/쓰기 override를 직접 주입하는 회귀로 수정했다. 이 실패는 시험 장치
문제이며 실제 서비스의 실패로 해석하지 않는다. 요구와 의존성은 그대로라 아래 초기
의존성 감사 결과가 현재 후보에도 적용된다.

## 초기 후보 기록 (60개 시험)

| 주장 / 명령(위 환경 변수 적용) | 원문 로그 | 종료 코드 / 판정 |
|---|---|---|
| `ruff check .` | [ruff-check-final.txt](ruff-check-final.txt) | 0 / PASS |
| `ruff format --check .` | [ruff-format-final.txt](ruff-format-final.txt) | 0 / PASS |
| `mypy` | [mypy-final.txt](mypy-final.txt) | 0 / PASS (설정된 `app` 범위; strict 아님) |
| `alembic heads` | [alembic-final.txt](alembic-final.txt) | 0 / PASS, 단일 head `634bbf55b755` |
| `pytest tests/ -q` | [pytest-final.txt](pytest-final.txt) | 0 / PASS, 60개. 실제 Redis 예약 해제·동일 delivery 재시도·실제 Celery worker의 PostgreSQL `PROCESSED` 1건, HMAC 허용·거부, admin 접근/정렬, `/metrics` 포함 |
| 새 `/tmp` Python 3.11 환경에 `requirements.txt`·`requirements-dev.txt` 설치 후 `pytest tests/ -q` | [환경 생성](fresh-env-create.txt), [설치](fresh-env-install.txt), [pytest](pytest-fresh-env.txt) | 각 0 / PASS, 새 의존성 설치에서도 60개 |
| 격리 DB·Redis 환경을 주입한 `.venv/bin/pre-commit run --all-files` | [precommit-final.txt](precommit-final.txt) | 0 / PASS, Ruff·mypy·pytest 훅 모두 실행 |
| 허용하지 않은 로컬 DB(`5433/webhook_db`)로 실제 DB 회복 회귀 실행 | [pytest-isolation-reject.txt](pytest-isolation-reject.txt) | 1 / 기대한 거부, DB 연결 전 시험 경계 assertion 실패 |
| `origin/develop`의 원래 훅 설정으로 같은 격리 환경에서 `.venv/bin/pre-commit run --config … --all-files` | [precommit-base-hook-repro.txt](precommit-base-hook-repro.txt) | 1 / 재현, 원래 훅이 DB URL을 `5433/webhook_db`로 덮어써 pytest 2 FAIL·58 PASS |
| PyYAML workflow 파싱·게시 조건·권한·정본 commitlint 파일 동일성 | [workflow-final.txt](workflow-final.txt) | 0 / PASS. PR·develop의 GHCR 게시 비실행은 정적 조건 판정이며 GitHub 실행 증거가 아님 |
| `uv pip compile requirements.txt --python-version 3.11` | [dependency-resolve-final.txt](dependency-resolve-final.txt) | 0 / PASS, 70개 런타임 패키지 해석 |
| `pip-audit --no-deps --disable-pip -r requirements.txt` | [dependency-audit-direct-final.txt](dependency-audit-direct-final.txt) | 0 / PASS, 직접 고정 패키지 범위만 |
| `pip-audit --no-deps --disable-pip -r dependency-resolved-pins.txt` | [dependency-audit-final.txt](dependency-audit-final.txt) | 1 / FAIL, 해석된 런타임 그래프에서 3개 패키지·15개 advisory 항목(중복 ID 포함) |
| `pip-audit --path /tmp/webhook-qa-venv-20261007/lib/python3.11/site-packages` | [dependency-audit-fresh-env.txt](dependency-audit-fresh-env.txt) | 1 / FAIL, 새 설치본에서도 같은 3개 패키지·15개 항목 |

실제 PostgreSQL·Redis·worker 회귀는 첫 실행에서 1 PASS였고,
최종 전체 pytest에서도 PASS였다. 최종 pytest 경고 두 개는 Starlette의 `httpx`
TestClient 사용 중단 예정 안내와 Redis `close()` 사용 중단 예정 안내다. 이 작업의
실패·복구 검사가 실제 종결 상태를 단언하므로 이 경고가 결과를 숨기지는 않는다.

초기 Ruff 검사는 새 시험의 import 순서·포맷을 지적해 실패했다. 해당 파일에만
`ruff check --fix`와 `ruff format`을 적용했고 [최종 Ruff 결과](ruff-check-final.txt)를
다시 확인했다. 최초 직접 의존 감사는 `python-dotenv==1.1.1`, `Mako==1.3.10`,
`sqladmin==0.21.0`에서 7개 항목을 보고했다([원문](dependency-audit-direct.txt)).
기본 `pip-audit -r requirements.txt`는 macOS `ensurepip`의 SIGABRT로 실패했고,
DYLD prefix를 추가해 재시도해도 동일했다([최초](dependency-audit.txt),
[재시도](dependency-audit-retry.txt)). 이후 pip 설치가 필요 없는 `--no-deps
--disable-pip`으로 직접 pin과 resolver가 만든 전체 pin 집합을 각각 감사했다.

보안 호환성 시험의 조건 변경과 실패도 보존한다.

- SQLAdmin 0.27.1만 올리면 기존 FastAPI 0.117.1의 Starlette `<0.49`와 충돌해
  resolver가 종료 코드 1을 반환했다([원문](dependency-install.txt)).
- FastAPI 0.121.3·SQLAdmin 0.27.1 조합은 해석·59개 회귀를 통과했지만
  Starlette 0.50.0의 알려진 경고가 있어 최종 후보로 사용하지 않았다
  ([해석](dependency-resolve-compatible.txt), [당시 검사](pytest-patched-deps.txt)).
- Starlette 1.3.1은 기존 Instrumentator 7.1.0의 `<1.0` 제약과 충돌했다
  ([원문](dependency-resolve-safe-starlette.txt)). 공식 8.0.1 호환 조합에서
  FastAPI 0.133.0·SQLAdmin 0.27.1·Starlette 1.3.1을 해석·검사했다.
- `python-keycloak` 2.16.6 후보는 urllib3 2.8.0까지 해석됐지만,
  현재 패키지의 `pkg_resources` import가 실패해 pytest 수집이 종료 코드 2가
  되었다([해석](dependency-resolve-keycloak2.txt),
  [실행 실패](pytest-keycloak2-fail.txt)). 2.0.0으로 되돌리고 최종 회귀를 재실행했다.

해석된 런타임 그래프의 남은 경고는 `python-keycloak==2.0.0`의
`urllib3==1.26.20`, `python-jose==3.5.0`, 그 하위 `ecdsa==0.19.2`다.
직접 의존 감사의 PASS를 전체 의존성 안전으로 해석하지 않는다. 기존 `.venv`에는
과거 설치 패키지가 남아 있어 [기존 설치본 감사](dependency-audit-installed-starlette1.txt)와
새 설치본 감사를 구분했다. 새 환경은 CI와 같은 requirements 두 파일을 새로 설치했다.
실 Keycloak 서명·만료·관리자 역할 연동, 원격 CI, required check 변경과 이미지 게시
결과는 **UNVERIFIED**다. 이 로컬 작업의 전체 보안 완료 판정은 **NOT VERIFIED**다.

[manifest.json](manifest.json)은 기준 SHA, 최종 후보의 주요 소스 SHA-256,
실행 원문별 SHA-256·종료 코드를 연결한다. 원래 훅 재현은 최초 커밋 훅 실패와
같은 원인(`5433` 강제 주입)을 보존한다. 수정한 훅은 주입된 QA URL을 존중하며,
포트 거부 시험과 실제 서비스 통과가 모두 확인됐다.

### 원격 전달 후보

원격 전달용 이력은 기존 `2d082815`와 같은 앱·시험·의존성 입력으로 정리한다. 원래 후보와 이 문서의 과거 결과는 보존하며, develop PR의 실제 CI·리뷰·병합 결과가 추가 인수 근거다. trusted 검사의 기본 브랜치 배치와 GHCR 게시·운영 배포는 별도 단계다.


### 현재 원격 인수와 v1.5.0 준비

위 원문과 manifest는 당시 후보·실행 결과를 보존한다. SDK 7.1.1 최종 인증/권한·실 Keycloak·감사 결과의 후속을 quality-remediation 스펙에서 연결하며 초기 SDK 2.0.0 경고를 현재 결과로 쓰지 않는다. [PR #71](https://github.com/grinvi04/webhook-service/pull/71)은 현재 develop `c42142483fb1b95e88f6af5e16872c3c26f294e0`로 병합됐고 같은 SHA의 [push CI](https://github.com/grinvi04/webhook-service/actions/runs/37570548035)도 품질·단일 head·secret-scan PASS, publish SKIPPED다. 기존 고정 후보 독립 인수는 Harness 소비 기록 PR #498에 연결돼 있다.

v1.5.0 준비는 버전·설치 안내만 바꾸며 기존 인증/의존성/마이그레이션 입력은 유지한다. 새 로컬 전체 110 PASS와 native commit 훅 PASS, 격리 DB 암호를 잘못 가정한 최초 107 PASS/3 ERROR 및 수정 이유를 `$HOME/Documents/Codex/2026-10-07/webhook-release-v1.5.0/`에 보존한다. 배포 예제에서 REDIS_URL이 누락돼 컨테이너 localhost가 선택되는 반례를 확인하고 Docker Redis 서비스 주소를 명시한다. main 릴리즈·이미지·역병합·trusted 활성화 결과는 아직 진행 중이며 운영 배포와 구분한다.


### v1.5.0 main·이미지·develop 인수 결과

[main PR #72](https://github.com/grinvi04/webhook-service/pull/72)는 후보 `e2587a8`의 required5 PASS·미해결 스레드0 후 `661ee4fda9a78002383eeb38e0d7e49c1cbd0e59`로 병합됐다. 같은 main SHA에 v1.5.0 태그를 발행하고 원격 ref를 확인했다. [main push CI](https://github.com/grinvi04/webhook-service/actions/runs/37622110609)는 build-and-test·alembic-heads·secret-scan·publish-image 모두 SUCCESS다. GHCR `ghcr.io/grinvi04/webhook-service:latest`의 build-push 완료 로그와 action metadata가 보고한 manifest digest는 `sha256:79c2df3f934428cf7ac8a1a6f741cde7833d165b24636e27061a4f84785c4124`다. 비인증 registry 조회는 401, 현재 PAT의 package metadata 조회는 403으로 실제 레지스트리 pull/readback은 UNVERIFIED다. 추가 토큰 권한이나 package 공개 설정은 변경하지 않았다. [역병합 PR #73](https://github.com/grinvi04/webhook-service/pull/73)도 기존 required5 통과 후 develop `c872bc63e3863058575b66ef986233ff5840c49a`로 병합했다.

새 version/env/docs 고정 후보의 독립 읽기 전용 검토에서 Keycloak localhost 설치 안내 P2를 발견했고, e2587a8의 공통 주소/placeholder 안내 보완 뒤 승인된 이미지 릴리즈 범위의 추가 P1/P2·필수 누락은 없었다. 최초 인증 작성자의 재대조는 독립 보안 승인으로 쓰지 않는다. 기존 고정 인증 후보의 독립 인수는 변경 없는 입력 범위로 재사용한다. 로컬 fresh110·커밋 훅4·Docker build/nonroot app·실제 이미지 runtime pin 감사0 및 예제 REDIS_URL RED→GREEN을 확인했다. 최초 격리 DB 암호 오류와 SVG checkout mtime 오탐(생성 내용 동일)도 과거 기록으로 보존한다.

이미지 게시와 운영 배포는 구분한다. 실제 운영 IdP·redirect/issuer/audience/키 회전·운영 endpoint health는 UNVERIFIED이며 운영 DB/배포는 변경하지 않았다. 신뢰 검사 workflow는 main에 배치됐고 역병합 target 이벤트도 실행됐지만, 일반 후속 PR의 고정 head 검사·app-bound required context 전환은 아직 인수 중이다. 기존 commitlint·다른 CI·strict·관리자 보호는 유지한다. 후속 PR/서버 readback과 이 문서의 다음 결과로 최종 상태를 연결한다.


### 신뢰 원본 필수 검사 전환

[일반 PR #74](https://github.com/grinvi04/webhook-service/pull/74)의 고정 head `2ae5c20fa1aedcf2d2e85d6c370f0d003da7aafa`에서 [target 실행](https://github.com/grinvi04/webhook-service/actions/runs/37622858614)의 HEAD_SHA 일치·commitlint-trusted SUCCESS를 확인했다. 같은 이름의 GitHub check-run도 해당 head·App 15368·SUCCESS다. PR #74는 required5와 독립 문서 대조 후 develop `81e82927ccb7105a88e56770f70d5d8454e181e7`로 병합됐다.

main·develop 모두 기존 app-bound 검사에 trusted를 먼저 추가하고 서버 전체 readback을 확인한 뒤 기존 commitlint 요구만 제거했다. 현재 required5는 alembic-heads/build-and-test/secret-scan/commitlint-trusted/destructive-ddl, App 15368·strict true다. 승인·관리자 강제·대화 해결·force/delete 등 다른 보호 설정은 전후 동일하다. 이번 후속은 develop의 중복 legacy workflow만 제거한다. main의 legacy 파일은 v1.5.0 역사에 남고 다음 정상 릴리즈에서 제거 내용을 전달한다. 새 검사는 이미 main에 있으며 두 브랜치에 서버 강제된다.

공개 target 이벤트의 향후 경로별 Actions policy 예외는 이번에 적용하지 않았다. 별도 운영자 승인 범위를 확인하고 실제 정책·정상 이벤트를 다시 인수해야 한다. 미확인 이벤트 정책·운영 IdP·운영 배포와 실제 registry pull/readback은 완료로 표시하지 않는다. 이 문서의 과거 진행 표현은 당시 후보 기록이다.
