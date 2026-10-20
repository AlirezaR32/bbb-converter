#!/usr/bin/env bash
# Watch conversion jobs (used during E2E verification).
BACKEND="${BACKEND:-http://127.0.0.1:8000}"
INTERVAL="${INTERVAL:-10}"
while true; do
  STAMP=$(date '+%H:%M:%S')
  ROWS=$(curl -s "$BACKEND/api/conversions" | python3 -c "
import json,sys
try:
    jobs = json.load(sys.stdin)['jobs']
except Exception:
    print('  (api unreachable)'); raise SystemExit
if not jobs: print('  (no jobs)')
for j in jobs[:5]:
    size = f\"{j['output']['size_bytes']/1e6:.1f}MB\" if j.get('output') else '-'
    err = (j.get('error') or {}).get('code', '')
    print(f\"  {j['id'][:8]} {j['format']:4} {j['status']:9} {str(round(j['progress']*100)).rjust(3)}% {j['stage']:12} {size:9} {err}\")
" 2>/dev/null)
  echo "[$STAMP]"
  echo "$ROWS"
  JOBS_JSON=$(curl -s "$BACKEND/api/conversions")
  ACTIVE=$(echo "$JOBS_JSON" | python3 -c "
import json,sys
jobs = json.load(sys.stdin)['jobs']
print(1 if any(j['status'] in ('queued','running') for j in jobs) else 0)" 2>/dev/null)
  [ "$ACTIVE" = "0" ] && break
  sleep "$INTERVAL"
done
echo "all jobs terminal"
