from __future__ import annotations

import os
import shutil
import subprocess
from collections import deque
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / ".toolchain" / "rvc.onnx"
OFFICIAL_TOOLCHAIN = ROOT / ".toolchain" / "rvc-official"
CONVERTER_PY = ROOT / ".converter-venv" / "Scripts" / "python.exe"
FALLBACK_EXPORTER = Path(__file__).resolve().parent / "export_rvc_official.py"
CACHE = Path(os.getenv("LOCALAPPDATA", Path.home())) / "TermuxVC" / "models"


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str], code: int, tail: list[str]):
        self.cmd = cmd
        self.code = code
        self.tail = tail
        details = "\n".join(tail[-40:]).strip()
        message = f"Command failed with exit code {code}: {' '.join(cmd)}"
        if details:
            message += f"\n\nLast converter output:\n{details}"
        super().__init__(message)


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    log: Callable[[str], None] | None = None,
):
    recent: deque[str] = deque(maxlen=120)
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert p.stdout is not None
    for line in p.stdout:
        text = line.rstrip()
        recent.append(text)
        if log:
            log(text)
    code = p.wait()
    if code != 0:
        raise CommandError(cmd, code, list(recent))


def _clone_if_missing(
    target: Path,
    marker: Path,
    url: str,
    branch: str | None = None,
    log=None,
):
    if marker.is_file():
        return
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is required for the first model import.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    cmd = [git, "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(target)]
    _run(cmd, log=log)


def ensure_toolchain(log=None):
    if not CONVERTER_PY.is_file():
        raise RuntimeError(
            "Converter environment is missing. Run client\\install.ps1 first."
        )
    script = TOOLCHAIN / "scripts" / "convert_rvc_to_onnx.py"
    _clone_if_missing(
        TOOLCHAIN,
        script,
        "https://github.com/SUC-DriverOld/rvc.onnx.git",
        log=log,
    )
    return script


def ensure_official_toolchain(log=None):
    marker = OFFICIAL_TOOLCHAIN / "rvc" / "modules" / "onnx" / "export.py"
    _clone_if_missing(
        OFFICIAL_TOOLCHAIN,
        marker,
        "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion.git",
        branch="develop",
        log=log,
    )
    return marker


def _remove_partial(*paths: Path):
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def convert_pth(
    pth: Path,
    precision: str = "fp32",
    log=None,
) -> tuple[Path, Path]:
    pth = pth.resolve()
    if not pth.is_file() or pth.suffix.lower() != ".pth":
        raise ValueError("Select a valid RVC .pth model")
    if precision != "fp32":
        raise ValueError("Termux VC currently imports RVC checkpoints as fp32")

    script = ensure_toolchain(log)
    out_dir = CACHE / pth.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    onnx = out_dir / f"{pth.stem}_{precision}.onnx"
    meta = out_dir / f"{pth.stem}_{precision}.json"

    if (
        onnx.is_file()
        and meta.is_file()
        and onnx.stat().st_mtime >= pth.stat().st_mtime
        and onnx.stat().st_size > 1_000_000
    ):
        if log:
            log(f"Using cached ONNX: {onnx}")
        return onnx, meta

    _remove_partial(onnx, meta)

    primary_error: Exception | None = None
    try:
        if log:
            log("Converting .pth -> ONNX with realtime exporter...")
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
    except Exception as exc:
        primary_error = exc
        _remove_partial(onnx, meta)
        if log:
            log("Primary exporter failed; trying official RVC ONNX fallback...")
        ensure_official_toolchain(log)
        try:
            _run(
                [
                    str(CONVERTER_PY),
                    str(FALLBACK_EXPORTER),
                    "--toolchain",
                    str(OFFICIAL_TOOLCHAIN),
                    "--checkpoint",
                    str(pth),
                    "--output",
                    str(onnx),
                    "--meta",
                    str(meta),
                ],
                cwd=ROOT,
                log=log,
            )
        except Exception as fallback_error:
            raise RuntimeError(
                "Both RVC exporters failed.\n\n"
                "PRIMARY EXPORTER:\n"
                f"{primary_error}\n\n"
                "OFFICIAL FALLBACK:\n"
                f"{fallback_error}"
            ) from fallback_error

    if not onnx.is_file() or not meta.is_file():
        raise RuntimeError(
            "Converter finished but ONNX/meta output was not created"
        )
    if onnx.stat().st_size < 1_000_000:
        raise RuntimeError(
            f"Exported ONNX is unexpectedly small ({onnx.stat().st_size} bytes)"
        )

    if log:
        log(f"ONNX ready: {onnx}")
    return onnx, meta
