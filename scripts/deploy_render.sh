#!/usr/bin/env bash
# One-command Render deploy. Requires `render login` to have been run first
# (interactive browser auth), then this script creates the Docker web service
# from the GitHub repo and prints the live URL.
set -euo pipefail

REPO="https://github.com/jayceparabellum/TTB_AI_Label_Verification_Tool"
NAME="ttb-label-verification"

if ! render whoami >/dev/null 2>&1; then
  echo "Not authenticated. Run:  render login   (interactive browser), then re-run this script." >&2
  exit 1
fi

# Pick the first workspace if none is active.
render workspace current >/dev/null 2>&1 || render workspace set --confirm >/dev/null 2>&1 || true

echo "Creating web service '$NAME' from $REPO ..."
render services create \
  --name "$NAME" \
  --type web_service \
  --runtime docker \
  --repo "$REPO" \
  --branch main \
  --plan free \
  --health-check-path /health \
  --confirm \
  --output json

echo
echo "Deploy triggered. Watch logs with:  render logs --resources $NAME --tail"
echo "The live URL will be shown in the service details above (a *.onrender.com address)."
