from __future__ import annotations

import shutil
import subprocess


def adb_exe() -> str:
    exe = shutil.which("adb")
    if not exe:
        raise RuntimeError("adb.exe not found. Install Android Platform Tools and add adb to PATH.")
    return exe


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
        raise RuntimeError("No authorized Android device found over USB.")
    if len(devs) > 1:
        raise RuntimeError("More than one Android device is connected. Disconnect the extra device first.")
    subprocess.run(
        [adb_exe(), "-s", devs[0], "forward", f"tcp:{port}", f"tcp:{port}"],
        check=True,
        capture_output=True,
    )
    return devs[0]
