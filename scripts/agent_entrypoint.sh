#!/usr/bin/env sh
# Entrypoint for the agent host image (Dockerfile.agent): run the local Ollama
# server on loopback, then serve the FastAPI app. Both processes are local — the
# model never reaches the public internet at request time.
set -e

# Start Ollama bound to loopback only (nothing leaves the host).
export OLLAMA_HOST="127.0.0.1:11434"
ollama serve &

# Wait for the model API before accepting chat traffic. Verification never waits
# on this — the button path is up the moment uvicorn binds.
echo "Waiting for Ollama to be ready..."
i=0
while [ "$i" -lt 30 ]; do
  if curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    echo "Ollama ready."
    break
  fi
  i=$((i + 1))
  sleep 1
done

# exec so uvicorn becomes PID 1 and receives container stop signals directly.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
