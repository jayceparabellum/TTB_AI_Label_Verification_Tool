#!/usr/bin/env bash
# Provision the local Ollama model for the agent (Layer 2).
# Runs at dev setup and in the Docker build — never at request time.
# The exact model is pending a host spike; override with OLLAMA_MODEL.
set -euo pipefail

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not installed. Install from https://ollama.com (local, no cloud)." >&2
  echo "Then re-run: OLLAMA_MODEL=$MODEL bash scripts/setup_ollama.sh" >&2
  exit 1
fi

echo "Pulling local model: $MODEL"
ollama pull "$MODEL"
echo "Done. Model '$MODEL' is available locally for ChatOllama."
