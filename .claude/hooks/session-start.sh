#!/bin/bash
# SessionStart hook: 세션 시작 시 Git 컨텍스트 + Docker 서비스 상태 확인

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [[ -z "$PROJECT_ROOT" ]]; then exit 0; fi

# Git 컨텍스트
BRANCH=$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null)
LAST_COMMITS=$(git -C "$PROJECT_ROOT" log --oneline -3 2>/dev/null)
UNCOMMITTED=$(git -C "$PROJECT_ROOT" status --short 2>/dev/null | wc -l | tr -d ' ')

echo "## 세션 시작 컨텍스트"
echo "🌿 브랜치: $BRANCH"
echo "📝 최근 커밋:"
echo "$LAST_COMMITS" | sed 's/^/   /'
if [ "$UNCOMMITTED" -gt "0" ]; then
  echo "⚠️  미커밋 파일: ${UNCOMMITTED}개 (git status로 확인)"
else
  echo "✅ 미커밋 변경 없음"
fi
echo ""

# .env 파일 확인
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  echo "✅ .env: 존재"
else
  echo "⚠️  .env 없음 — cp .env.example .env 후 값 설정 필요"
fi

# Docker 서비스 상태 확인
DB_STATUS=$(docker-compose -f "$PROJECT_ROOT/docker-compose.yml" ps db 2>/dev/null | grep -E "Up|running" | wc -l | tr -d ' ')
REDIS_STATUS=$(docker-compose -f "$PROJECT_ROOT/docker-compose.yml" ps redis 2>/dev/null | grep -E "Up|running" | wc -l | tr -d ' ')

if [ "$DB_STATUS" -gt "0" ]; then
  echo "🐘 PostgreSQL: 실행 중 (localhost:5433)"
else
  echo "⚠️  PostgreSQL 미실행 — docker-compose up -d db"
fi

if [ "$REDIS_STATUS" -gt "0" ]; then
  echo "🔴 Redis: 실행 중 (localhost:6379)"
else
  echo "⚠️  Redis 미실행 — docker-compose up -d redis"
fi

echo ""
echo "전체 작업 현황은 /release-check 실행"
