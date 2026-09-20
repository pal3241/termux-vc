from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_ADB = ROOT / ".toolchain" / "platform-tools" / "adb.exe"


def adb_exe() -> str:
    exe = shutil.which("adb")
    if exe:
        return exe
    if BUNDLED_ADB.is_file():
        return str(BUNDLED_ADB)
    raise RuntimeError(
        "adb.exe not found. Run client\\install.ps1 or install Android Platform Tools."
    )


def devices() -> list[str]:
    p = subprocess.run([adb_exe(), "devices"], text=True, capture_output=True, check=True)
    out = []
    for line in p.stdout.splitlines()[1:]:
        if "\tdevice" in line:
            out.append(line.split("\t", 1)[0])
    return out


def forward(port: int = 18888) -> str:
    devs = devices()
    if not devs:
        raise RuntimeError(
            "No authorized Android device found over USB. Enable USB debugging and accept the RSA prompt."
        )
    if len(devs) > 1:
        raise RuntimeError(
            "More than one Android device is connected. Disconnect the extra device first."
        )
    subprocess.run(
        [adb_exe(), "-s", devs[0], "forward", f"tcp:{port}", f"tcp:{port}"],
        check=True,
        capture_output=True,
    )
    return devs[0]
