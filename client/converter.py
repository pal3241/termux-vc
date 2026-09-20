from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / ".toolchain" / "rvc.onnx"
CONVERTER_PY = ROOT / ".converter-venv" / "Scripts" / "python.exe"
CACHE = Path(os.getenv("LOCALAPPDATA", Path.home())) / "TermuxVC" / "models"


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    log: Callable[[str], None] | None = None,
):
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert p.stdout is not None
    for line in p.stdout:
        if log:
            log(line.rstrip())
    code = p.wait()
    if code != 0:
        raise RuntimeError(f"Command failed with exit code {code}: {' '.join(cmd)}")


def ensure_toolchain(log=None):
    if not CONVERTER_PY.is_file():
        raise RuntimeError("Converter environment is missing. Run client\\install.ps1 first.")
    script = TOOLCHAIN / "scripts" / "convert_rvc_to_onnx.py"
    if not script.is_file():
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git is required for the first model import.")
        TOOLCHAIN.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                git,
                "clone",
                "--depth",
                "1",
                "https://github.com/SUC-DriverOld/rvc.onnx.git",
                str(TOOLCHAIN),
            ],
            log=log,
        )
    return script


def convert_pth(
    pth: Path,
    precision: str = "fp32",
    log=None,
) -> tuple[Path, Path]:
    pth = pth.resolve()
    if not pth.is_file() or pth.suffix.lower() != ".pth":
        raise ValueError("Select a valid RVC .pth model")
    script = ensure_toolchain(log)
    out_dir = CACHE / pth.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx = out_dir / f"{pth.stem}_{precision}.onnx"
    meta = out_dir / f"{pth.stem}_{precision}.json"

    if (
        onnx.is_file()
        and meta.is_file()
        and onnx.stat().st_mtime >= pth.stat().st_mtime
    ):
        if log:
            log(f"Using cached ONNX: {onnx}")
        return onnx, meta

    if log:
        log("Converting .pth -> ONNX (first import can take a while)...")
    _run(
        [
            str(CONVERTER_PY),
            str(script),
            "--checkpoint",
            str(pth),
            "--output-dir",
            str(out_dir),
            "--precision",
            precision,
            "--opset",
            "17",
        ],
        cwd=TOOLCHAIN,
        log=log,
    )
    if not onnx.is_file() or not meta.is_file():
        raise RuntimeError("Converter finished but ONNX/meta output was not created")
    return onnx, meta
