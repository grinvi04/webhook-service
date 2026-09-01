---
paths: ["**/*.py"]
---

# Python / FastAPI 작업 규칙

## 포맷·린트·타입은 게이트가 강제 (prose 아님)
- **ruff(린트) + `ruff format`(Black 호환 포맷) + mypy(타입)이 빌드 게이트**다. CI가 어긋난 코드를 차단한다.
- 자동수정: `ruff check --fix .` + `ruff format .` (커밋 전). 손으로 포맷 맞추지 말 것.
- `pyproject.toml`에 넣을 설정 (line-length 100, mypy strict 권장):

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
# E,F=pyflakes/pycodestyle · I=isort · UP=pyupgrade · B=bugbear · SIM=simplify · C4=comprehensions
select = ["E", "F", "I", "UP", "B", "SIM", "C4"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true
```

- CI(ci-gate)에 세 스텝: `ruff check .` · `ruff format --check .` · `mypy .` (셋 다 통과해야 머지).

## async / sync 혼용 금지
- `async def` 엔드포인트에서 동기 DB 호출(`db.query`, `db.commit`) 직접 호출 금지 — 이벤트 루프 블로킹.
- 동기 유지(`def`)하거나 AsyncSession으로 완전 전환 중 하나.

## 절대 금지
```python
==  # HMAC 비교 → hmac.compare_digest() 필수 (타이밍 공격)
$queryRaw / text() 직접 SQL  # → ORM 또는 파라미터 바인딩 사용
```

## 입력 오류는 4xx (단일 출처: `docs/api-standards.md`)
- Pydantic 검증 실패는 FastAPI가 422로 매핑하지만, 커스텀 검증·핸들러 미매핑 예외는 500으로 흡수된다 —
  잘못된 입력은 `@app.exception_handler`로 4xx + 공통 Envelope에 매핑(`docs/api-standards.md`).

## 테스트
- FastAPI 의존성 mock: `app.dependency_overrides[get_db] = ...` 필수 (`mocker.patch` 동작 안 함)
- 테스트 후 반드시 `app.dependency_overrides.clear()`

## lint
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
```
