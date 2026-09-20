#!/usr/bin/env bash
set -euo pipefail

# ONNX Runtime wheels used by this project target glibc Linux aarch64.
# Native Termux uses Android/Bionic, so install must run inside Ubuntu PRoot.
if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]]; then
  cat <<'EOF'
ERROR: install_arm64.sh was started in native Termux.

This server must run inside Ubuntu PRoot because ONNX Runtime for this project
uses glibc/manylinux aarch64 wheels, while native Termux uses Android/Bionic.

Run this from native Termux instead:

  cd ~/termux-vc
  bash termux_bootstrap.sh

Or enter Ubuntu manually:

  proot-distro login ubuntu
  cd ~
  git clone https://github.com/pal3241/termux-vc.git
  cd termux-vc/server
  bash install_arm64.sh
EOF
  exit 2
fi

if [ "$(uname -m)" != "aarch64" ]; then
  echo "Warning: this installer is tuned for Linux aarch64; detected $(uname -m)."
fi

if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "Detected Linux: ${PRETTY_NAME:-${ID:-unknown}}"
fi

sudo_cmd=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  sudo_cmd="sudo"
fi

$sudo_cmd apt update
$sudo_cmd apt install -y python3 python3-venv python3-pip ffmpeg libsndfile1 git curl

cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt

echo
echo "Trying optional FAISS support for .index retrieval..."
if ! python -m pip install "faiss-cpu>=1.9"; then
  echo "WARNING: faiss-cpu wheel is unavailable for this environment."
  echo "         Voice conversion still works; set index rate to 0."
fi

echo
echo "Downloading RVC v2 runtime assets (ContentVec + RMVPE)."
python assets.py --v2

echo
echo "Install complete. Start with:"
echo "  source .venv/bin/activate"
echo "  ./run_server.sh"
