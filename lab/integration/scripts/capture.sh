#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $# -gt 0 ]] || { echo '사용법: bash scripts/capture.sh <실행할 명령과 인수>'; exit 2; }
mkdir -p runs
run_dir=$(mktemp -d "$PWD/runs/run-XXXXXXXX")
git rev-parse HEAD > "$run_dir/commit.txt"
git status --short > "$run_dir/status.txt"
git diff --binary HEAD > "$run_dir/changes.patch"
docker compose config > "$run_dir/compose.yml"
curl -fsS http://localhost:8082/control/fault > "$run_dir/fault-before.json"
curl -fsS http://localhost:8081/control/worker > "$run_dir/worker-before.json"
printf '%q ' "$@" > "$run_dir/command.txt"
date -u > "$run_dir/start.txt"
set +e
"$@" 2>&1 | tee "$run_dir/output.txt"
result=${PIPESTATUS[0]}
set -e
date -u > "$run_dir/end.txt"
docker compose logs --no-color > "$run_dir/services.log"
curl -fsS http://localhost:8081/reviews > "$run_dir/reviews.json" || true
curl -fsS http://localhost:8082/grants > "$run_dir/grants.json" || true
printf '%s\n' "$result" > "$run_dir/exit-code.txt"
echo "원본 저장: $run_dir (exit=$result)"
exit "$result"
