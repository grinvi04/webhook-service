#!/bin/bash
INPUT=$(cat)
TOOL=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)
COMMAND=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
if [[ "$TOOL" != "Bash" ]]; then exit 0; fi
if echo "$COMMAND" | grep -qE "git commit"; then
  CD_TARGET=$(echo "$COMMAND" | grep -oE 'cd [^ ;&]+' | head -1 | awk '{print $2}')
  if [[ -n "$CD_TARGET" ]]; then
    BRANCH=$(git -C "$CD_TARGET" branch --show-current 2>/dev/null)
  else
    BRANCH=$(git branch --show-current 2>/dev/null)
  fi
  if [[ "$BRANCH" == "main" || "$BRANCH" == "develop" ]]; then
    echo "⛔ main/develop 직접 커밋 금지 — feature/fix/hotfix/release 브랜치에서 작업하세요"
    exit 2
  fi
fi
if echo "$COMMAND" | grep -qE "git push.*(--force|-f)\b"; then
  if echo "$COMMAND" | grep -qE "\b(main|develop)\b|origin main|origin develop"; then
    echo "⛔ main/develop force push 금지 — 브랜치 히스토리 훼손 위험"
    exit 2
  fi
fi
if echo "$COMMAND" | grep -qE "git reset --hard"; then
  echo "⛔ git reset --hard — 미커밋 변경사항 전체 삭제 위험. 직접 실행하세요."
  exit 2
fi
if echo "$COMMAND" | grep -qE "alembic downgrade base"; then
  echo "⛔ alembic downgrade base — DB 전체 스키마 삭제 위험. 직접 실행하세요."
  exit 2
fi
if echo "$COMMAND" | grep -qiE "DROP\s+TABLE"; then
  echo "⛔ DROP TABLE 직접 실행 금지 — Alembic 마이그레이션을 통해 처리하세요."
  exit 2
fi
PROJECT_ROOT="/Users/grinvi04/project/webhook-service"
if echo "$COMMAND" | grep -qE "rm\s+-[rRf]{1,3}"; then
  if echo "$COMMAND" | grep -qE "($PROJECT_ROOT\s*$|/app[\s/]|/tests[\s/]|/alembic[\s/])"; then
    echo "⛔ 프로젝트 핵심 디렉토리 rm -rf 금지"
    exit 2
  fi
fi
exit 0
