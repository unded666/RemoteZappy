#!/usr/bin/env bash
set -euo pipefail

# Use SDL dummy driver to avoid X requirement. If you prefer Xvfb, install and start it instead.
export SDL_VIDEODRIVER=dummy

# Render provides $PORT; default to 8080 when not set
PORT=${PORT:-8080}

# Ensure the game uses the bridge on localhost
export FRAMEPIPE_URL="ws://127.0.0.1:${PORT}/framepipe"
export INPUT_LISTEN_PORT=${INPUT_LISTEN_PORT:-5001}

# Start the game in the background and capture logs
nohup python /app/main.py > /tmp/game.log 2>&1 &
GAME_PID=$!

echo "Started game (pid=$GAME_PID), logging to /tmp/game.log"

# Give the game a moment to initialize
sleep 2

# Start the bridge (bind to the provided PORT)
exec python /app/server/bridge.py --host 0.0.0.0 --port "$PORT"

