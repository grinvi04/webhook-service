#!/usr/bin/env bash
# GitHub HMAC-SHA256 웹훅 서명 생성
#
# 사용법:
#   ./scripts/generate_github_signature.sh '<JSON_PAYLOAD>' '<SECRET>'
#
# 예시:
#   PAYLOAD='{"action":"opened","sender":{"login":"octocat"},"repository":{"full_name":"octocat/hello-world"}}'
#   ./scripts/generate_github_signature.sh "$PAYLOAD" "my-super-secret-key"
#
# 출력:
#   sha256=abc123...   ← X-Hub-Signature-256 헤더에 그대로 사용

set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 '<json_payload>' '<secret>'" >&2
  exit 1
fi

PAYLOAD="$1"
SECRET="$2"

SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print "sha256="$2}')
echo "$SIGNATURE"
