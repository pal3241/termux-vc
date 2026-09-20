#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "${TERMUX_VERSION:-}" ] && [[ "${PREFIX:-}" != *"com.termux"* ]]; then
  echo "This script is intended to be run from native Termux."
  exit 2
fi

echo "[1/4] Installing Termux host dependencies..."
pkg update -y
pkg install -y proot-distro git

echo "[2/4] Checking Ubuntu PRoot..."
if ! proot-distro login ubuntu -- /bin/true >/dev/null 2>&1; then
  echo "Ubuntu is not installed yet; installing it..."
  proot-distro install ubuntu
fi

echo "[3/4] Preparing termux-vc inside Ubuntu..."
proot-distro login ubuntu -- bash -lc '
set -e
cd ~
if [ -d termux-vc/.git ]; then
  cd termux-vc
  git pull --ff-only
else
  git clone https://github.com/pal3241/termux-vc.git
  cd termux-vc
fi
cd server
bash install_arm64.sh
'

echo "[4/4] Done."
cat <<'EOF'

Start the server with:

  proot-distro login ubuntu
  cd ~/termux-vc/server
  ./run_server.sh

Keep that Ubuntu session running while the Windows client is connected.
EOF
