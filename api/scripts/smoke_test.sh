#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://test.ichimozzi.com/openakashic}"

echo "Health:"
curl -fsS "$BASE_URL/health"
echo

echo "Query:"
curl -fsS "$BASE_URL/query" \
  -H 'content-type: application/json' \
  -d '{"query":"OpenAkashic v1 capsule claim evidence","top_k":5}' \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))'

echo "MCP tools:"
curl -fsS "$BASE_URL/mcp" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))'
