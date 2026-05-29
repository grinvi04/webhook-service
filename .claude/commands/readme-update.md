# /readme-update — README 최신화

**사용법**: `/readme-update`

## 제약조건 (할루시네이션 방지)
- 코드를 읽기 전에 README를 수정하지 말 것
- 실제 파일에서 확인된 내용만 문서화 — 추측으로 엔드포인트/환경변수 작성 금지
- 존재하지 않는 파일 경로 참조 금지 (`ls`로 확인 후 작성)
- 테스트 명령어는 실제 동작 확인된 명령어만 기재

## 실행 절차

### 1. 사전 검증 (직접 실행, 실패 시 중단)
```bash
cd /Users/grinvi04/Project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -q
```
실패 시 중단하고 "품질 검증 실패" 출력.

### 2. 병렬 분석 (동시에 background spawn)

**Agent A — 코드 스캔** (`subagent_type: Explore`, `run_in_background: true`)
Read 대상: `app/webhooks.py`, `app/webhook_registry.py`, `app/celery_worker.py`,
`app/config.py`, `app/main.py`, `docker-compose.yml`, `docs/examples/`
리포트: 실제 엔드포인트 목록, 프로바이더 목록, 환경변수 목록, 서비스 포트

**Agent B — README 분석** (`subagent_type: Explore`, `run_in_background: true`)
`README.md` Read → 코드와 불일치 항목 리포트:
- 잘못된 엔드포인트/포트/환경변수
- 존재하지 않는 파일 참조
- 구버전 명령어 (python -m venv vs python3.11 -m venv 등)

### 3. README 업데이트
Agent A·B 결과 기반으로 수정. 규칙:
- 기존 섹션 순서 유지
- 기술 스택 배지는 상단 유지 (채용담당자 고려)
- macOS 15 DYLD_LIBRARY_PATH 주의사항 유지
- 확인되지 않은 내용은 추가하지 않음

### 4. 커밋
`docs: README 최신화 — 엔드포인트·환경변수·프로바이더 현행화`

---

## 분석 체크리스트

### Agent A 확인 항목
- `app/main.py`: 모든 `@app.post`, `@app.get` 라우트 → README API 테이블과 대조
- `app/config.py`: 모든 `settings.*` 필드 → README 환경변수 테이블과 대조
- `docker-compose.yml`: 서비스명·포트 → README 서비스 접근 테이블과 대조
- `app/webhook_registry.py`: WEBHOOK_REGISTRY 키 → README 프로바이더 테이블과 대조
- `docs/examples/`: 파일 존재 여부 확인 후 README 표에 반영

### Agent B 확인 항목
- 아키텍처 다이어그램: Nginx(80), FastAPI(8000), Keycloak(8080), Prometheus(9090), Grafana(3000) 포트 일치
- Python/FastAPI 버전 배지: `requirements.txt` · `Dockerfile` 기준으로 일치 여부 확인
- rate limit 수치: `@limiter.limit()` 데코레이터 실제 값과 README 일치 여부
- Prometheus 메트릭 이름: `app/metrics.py` 실제 이름 → README 메트릭 테이블과 대조

### README 업데이트 규칙
- 배지(shields.io) 상단 3줄 유지 — CI 상태 확인 용이성 우선
- macOS 15 `DYLD_LIBRARY_PATH` 경고 섹션 반드시 유지
- `로컬 개발` 섹션 명령어: `.venv/bin/` 접두사 + `DYLD_LIBRARY_PATH` 형식 유지
- 삭제된 엔드포인트·환경변수는 README에서도 반드시 제거

### 커밋 전 최종 확인
```bash
grep -oE '\./[a-zA-Z0-9/_.-]+' README.md | while read f; do
  [ -e "$f" ] || echo "없는 경로: $f"
done
```
