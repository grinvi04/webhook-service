#!/bin/bash
# PostToolUse hook: Edit/Write 후 ruff lint 검사
# exit 2 → Claude Code가 오류를 Claude에게 전달 → 자동 수정 반복

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)

[[ "$FILE_PATH" != *.py ]] && exit 0

PROJECT_ROOT="/Users/grinvi04/project/webhook-service"
[[ "$FILE_PATH" != "$PROJECT_ROOT/app/"* && "$FILE_PATH" != "$PROJECT_ROOT/tests/"* ]] && exit 0

export DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib

RUFF_OUT=$("$PROJECT_ROOT/.venv/bin/ruff" check "$FILE_PATH" 2>&1)
if [ $? -ne 0 ]; then
  echo "❌ [ruff lint 실패] $FILE_PATH"
  echo "$RUFF_OUT"
  exit 2
fi

FORMAT_OUT=$("$PROJECT_ROOT/.venv/bin/ruff" format --check "$FILE_PATH" 2>&1)
if [ $? -ne 0 ]; then
  echo "❌ [ruff format 필요] $FILE_PATH"
  echo "$FORMAT_OUT"
  exit 2
fi

echo "✅ lint 통과: $FILE_PATH"
exit 0
