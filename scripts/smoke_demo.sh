#!/usr/bin/env bash
# End-to-end smoke test: demo analyze -> create job -> poll -> download -> verify.
set -uo pipefail

BACKEND="${BACKEND:-http://127.0.0.1:8000}"
DEMO_URL="$BACKEND/demo/playback/presentation/2.3/dem0recording0000000000000000000000000000000-1700000000000"
FORMAT="${1:-mp4}"

say() { printf "\n\033[1;35m== %s ==\033[0m\n" "$*"; }

say "health"
curl -sf "$BACKEND/api/health" | python3 -c "import json,sys; d=json.load(sys.stdin); print('status:', d['status'], '| ffmpeg:', d['ffmpeg_available'], '| demo:', d['demo_mode'])" || { echo "health FAILED"; exit 1; }

say "analyze demo recording"
ANALYSIS=$(curl -sf -X POST "$BACKEND/api/recordings/analyze" -H 'Content-Type: application/json' -d "{\"url\": \"$DEMO_URL\"}") || { echo "analyze FAILED"; exit 1; }
echo "$ANALYSIS" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('title:', d['title'], '| duration:', d['duration_seconds'], 's | strategy:', d['strategy']['id'])
print('assets:', {k: v.get('available') for k, v in d['assets'].items() if isinstance(v, dict)})
"

say "create $FORMAT conversion job"
JOB=$(curl -sf -X POST "$BACKEND/api/conversions" -H 'Content-Type: application/json' -d "{\"url\": \"$DEMO_URL\", \"format\": \"$FORMAT\"}") || { echo "create job FAILED"; exit 1; }
JOBID=$(echo "$JOB" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "job id: $JOBID"

say "poll progress"
for i in $(seq 1 60); do
  sleep 2
  ST=$(curl -s "$BACKEND/api/conversions/$JOBID")
  LINE=$(echo "$ST" | python3 -c "
import json,sys
d=json.load(sys.stdin)
err = d.get('error') or {}
print(d['status'], str(round(d['progress']*100)).rjust(3)+'%', d['stage'], '|', (d.get('progress_detail') or '')[:46], '|', (err.get('message') or '')[:60])
" 2>/dev/null || echo "parse-error")
  echo "  [$i] $LINE"
  case "$LINE" in
    completed*|failed*|canceled*) break ;;
  esac
done

say "result"
FINAL=$(curl -s "$BACKEND/api/conversions/$JOBID")
echo "$FINAL" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('status:', d['status'])
if d.get('output'): print('output:', d['output'])
if d.get('download'): print('download url (token signed):', d['download']['url'][:90]+'...')
if d.get('error'): print('error:', d['error'])
"
if echo "$FINAL" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('status')=='completed' else 1)"; then
  DL=$(echo "$FINAL" | python3 -c "import json,sys; print(json.load(sys.stdin)['download']['url'])")
  case "$DL" in http*) ;; *) DL="$BACKEND$DL" ;; esac
  say "download + verify"
  curl -sf -o /tmp/smoke_output.$FORMAT "$DL" && echo "downloaded: $(du -h /tmp/smoke_output.$FORMAT | cut -f1)"
  ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,codec_type -of default=noprint_wrappers=1 /tmp/smoke_output.$FORMAT
else
  echo "job did not complete successfully — smoke test FAILED"
  exit 1
fi

say "cleanup: delete job"
curl -s -X DELETE "$BACKEND/api/conversions/$JOBID" | head -c 200; echo
echo "SMOKE TEST PASSED"
