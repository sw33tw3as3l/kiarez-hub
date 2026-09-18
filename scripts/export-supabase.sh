#!/usr/bin/env bash
# One-time export of the Supabase `goals` and `tasks` tables to JSON.
# Reads credentials from .env; never prints them.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env found" >&2; exit 1; }
set -a; . ./.env; set +a

out="${1:-supabase-export.json}"
url="${NEXT_PUBLIC_SUPABASE_URL:?missing NEXT_PUBLIC_SUPABASE_URL}"
key="${NEXT_PUBLIC_SUPABASE_ANON_KEY:?missing NEXT_PUBLIC_SUPABASE_ANON_KEY}"

fetch() {
  curl -sS --fail-with-body \
    -H "apikey: $key" -H "Authorization: Bearer $key" \
    "$url/rest/v1/$1?select=*"
}

goals=$(fetch goals)
tasks=$(fetch tasks)

python3 - "$out" <<PY
import json, sys
json.dump({"goals": json.loads('''$goals'''), "tasks": json.loads('''$tasks''')},
          open(sys.argv[1], "w"), indent=2)
PY
echo "wrote $out"
