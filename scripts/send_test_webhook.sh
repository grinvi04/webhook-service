#!/usr/bin/env bash
# 테스트 GitHub 웹훅을 서명과 함께 전송합니다.
# scripts/seed_tenant.sh 실행 후 사용하세요.
#
# 사용법:
#   ./scripts/send_test_webhook.sh
#   ./scripts/send_test_webhook.sh stripe   # Stripe 웹훅

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
TENANT_ID="${TENANT_ID:-demo-tenant}"
SECRET="${WEBHOOK_SECRET:-my-super-secret-key}"
SOURCE="${1:-github}"

if [ "$SOURCE" = "github" ]; then
  PAYLOAD=$(cat <<'JSON'
{
  "action": "opened",
  "sender": {"login": "octocat"},
  "repository": {"full_name": "octocat/hello-world"}
}
JSON
)
  PAYLOAD_COMPACT=$(echo "$PAYLOAD" | tr -d '\n ' | sed 's/  */ /g')
  SIG=$(echo -n "$PAYLOAD_COMPACT" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print "sha256="$2}')

  echo "→ GitHub 웹훅 전송: $BASE_URL/webhooks/$TENANT_ID/github"
  echo "  서명: $SIG"
  curl -s -w "\n상태코드: %{http_code}\n" \
    -X POST "$BASE_URL/webhooks/$TENANT_ID/github" \
    -H "Content-Type: application/json" \
    -H "X-Hub-Signature-256: $SIG" \
    -d "$PAYLOAD_COMPACT"

elif [ "$SOURCE" = "stripe" ]; then
  echo "→ Stripe 테스트는 Stripe CLI를 사용하세요:"
  echo "   stripe listen --forward-to $BASE_URL/webhooks/$TENANT_ID/stripe"
  echo "   stripe trigger customer.created"
  exit 0

else
  echo "지원하지 않는 소스: $SOURCE (github | stripe)" >&2
  exit 1
fi
