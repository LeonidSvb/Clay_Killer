#!/usr/bin/env bash
# Usage: scripts/utils/exa-search.sh "query" [numResults] [maxCharacters]
# Reads EXA_API_KEY from .env in project root.

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$DIR/.env"

QUERY="$1"
NUM="${2:-5}"
CHARS="${3:-1500}"

if [ -z "$QUERY" ]; then
  echo "Usage: exa-search.sh \"query\" [numResults] [maxCharacters]" >&2
  exit 1
fi

curl -s -X POST https://api.exa.ai/search \
  -H "x-api-key: $EXA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"query\": $(printf '%s' "$QUERY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'), \"numResults\": $NUM, \"contents\": {\"text\": {\"maxCharacters\": $CHARS}}}"
