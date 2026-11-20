#!/usr/bin/env bash
# Run from anywhere: tilt/scripts/start-lichess.sh. ROOT is the monorepo root.
# Start lichess locally in WSL: MongoDB + Redis (system services), lila-ws, the tilt worker, a local fishnet
# (server analysis with the system Stockfish), then lila (with the AI Coach when ~/.ai-coach-key exists).
# Usage:  tilt/scripts/start-lichess.sh          (Ctrl+C stops lila and lila-ws)
#         tilt/scripts/start-lichess.sh --ui     (also rebuild the frontend on every change)
# Then open http://localhost:9663

set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGS="$HOME/.lichess-logs"
mkdir -p "$LOGS"

for svc in mongod redis-server; do
  if ! systemctl is-active --quiet "$svc"; then
    echo "$svc is not running. Start it with: sudo systemctl start $svc"
    exit 1
  fi
done

pids=()
cleanup() {
  echo "Stopping..."
  for pid in "${pids[@]}"; do kill -- -"$pid" 2>/dev/null; done
}
trap cleanup EXIT

if [[ "${1:-}" == "--ui" ]]; then
  echo "Starting frontend watcher (log: $LOGS/ui.log)"
  setsid bash -c "cd '$ROOT/lila' && ./ui/build --watch" > "$LOGS/ui.log" 2>&1 &
  pids+=($!)
fi

echo "Starting lila-ws (log: $LOGS/lila-ws.log)"
setsid bash -c "cd '$ROOT/lila-ws' && tail -f /dev/null | sbt run" > "$LOGS/lila-ws.log" 2>&1 &
pids+=($!)

# Tilt worker: scores finished games queued by lila (needs a trained model and the export salt)
if [[ -d "$ROOT/tilt/data/processed/models" && -f "$HOME/.tilt-salt" ]]; then
  echo "Starting tilt worker (log: $LOGS/tilt.log)"
  setsid bash -c "cd '$ROOT' && TILT_SALT=\"\$(cat ~/.tilt-salt)\" tilt/.venv/bin/python -m tilt lila-worker" \
    > "$LOGS/tilt.log" 2>&1 &
  pids+=($!)
else
  echo "Tilt worker not started: train a model into tilt/data/processed/models and keep the salt in ~/.tilt-salt"
fi

# AI Coach: Claude through the vnaipro gateway (Anthropic Messages API, https://api.vnaipro.app/v1/messages).
# The key stays in ~/.ai-coach-key (chmod 600), never in the repo. AI_COACH_* already set in the shell win.
if [[ -f "$HOME/.ai-coach-key" ]]; then
  export AI_COACH_PROVIDER="${AI_COACH_PROVIDER:-anthropic}"
  export AI_COACH_URL="${AI_COACH_URL:-https://api.vnaipro.app}"
  # Haiku 4.5: as right as Opus 5.5 on the coach evaluation (2026-11-18), about 2x faster and cheaper.
  export AI_COACH_MODEL="${AI_COACH_MODEL:-claude-haiku-4-5-20251001}"
  # Haiku 4.5 has no effort setting (Anthropic's API rejects it); Opus / Sonnet think less with low.
  # AI_COACH_EFFORT="" keeps the model default.
  if [[ $AI_COACH_MODEL == claude-haiku-4-5* ]]; then coach_effort=""; else coach_effort=low; fi
  export AI_COACH_EFFORT="${AI_COACH_EFFORT-$coach_effort}"
  export AI_COACH_API_KEY="${AI_COACH_API_KEY:-$(cat "$HOME/.ai-coach-key")}"
  echo "AI Coach: $AI_COACH_MODEL (effort ${AI_COACH_EFFORT:-model default}) via $AI_COACH_URL"
else
  echo "AI Coach off: put the API key in ~/.ai-coach-key"
fi

# Local fishnet: analyses the games queued for a server analysis (the analysis tab's button, or the AI Coach's
# first question on a game). lila in dev mode accepts it without a key. It waits for lila to come up.
if [[ -x /usr/games/stockfish && -x "$ROOT/tilt/.venv/bin/python" ]]; then
  echo "Starting local fishnet (log: $LOGS/fishnet.log)"
  setsid bash -c "cd '$ROOT' && exec tilt/.venv/bin/python -u tilt/scripts/fishnet-local.py" > "$LOGS/fishnet.log" 2>&1 &
  pids+=($!)
else
  echo "Local fishnet not started: needs /usr/games/stockfish and tilt/.venv"
fi

echo "Starting lila on http://localhost:9663 (the first page load compiles for about a minute)"
cd "$ROOT/lila"
tail -f /dev/null | ./lila.sh run
