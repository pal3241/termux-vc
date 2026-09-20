#!/usr/bin/env bash
set -euo pipefail

if [ "$(uname -m)" != "aarch64" ]; then
  echo "Warning: this installer is tuned for Linux aarch64; detected $(uname -m)."
fi

sudo_cmd=""
if command -v sudo >/dev/null 2>&1; then sudo_cmd="sudo"; fi

$sudo_cmd apt update
$sudo_cmd apt install -y python3 python3-venv python3-pip ffmpeg libsndfile1 git curl

cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt

echo
echo "Downloading RVC v2 runtime assets (ContentVec + RMVPE)."
python assets.py --v2

echo
echo "Install complete. Start with:"
echo "  source .venv/bin/activate"
echo "  ./run_server.sh"
