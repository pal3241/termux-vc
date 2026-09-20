from __future__ import annotations

import argparse
from pathlib import Path
import requests

ASSETS = {
    "v2": ("vec-768-layer-12.onnx", "https://huggingface.co/NaruseMioShirakana/MoeSS-SUBModel/resolve/main/vec-768-layer-12.onnx?download=true"),
    "v1": ("vec-256-layer-9.onnx", "https://huggingface.co/NaruseMioShirakana/MoeSS-SUBModel/resolve/main/vec-256-layer-9.onnx?download=true"),
    "rmvpe": ("RMVPE.onnx", "https://huggingface.co/NaruseMioShirakana/MoeSS-SUBModel/resolve/main/RMVPE.onnx?download=true"),
}


def download(url: str, dest: Path):
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print(f"[skip] {dest.name} already exists")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"[download] {dest.name}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done/1024/1024:.1f}/{total/1024/1024:.1f} MiB", end="", flush=True)
    print()
    tmp.replace(dest)


def ensure(root: Path, versions=("v2",), include_rmvpe=True):
    keys = list(versions) + (["rmvpe"] if include_rmvpe else [])
    for key in keys:
        filename, url = ASSETS[key]
        download(url, root / filename)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent / "assets")
    p.add_argument("--v1", action="store_true")
    p.add_argument("--v2", action="store_true")
    args = p.parse_args()
    versions = []
    if args.v1:
        versions.append("v1")
    if args.v2 or not versions:
        versions.append("v2")
    ensure(args.dir, versions=versions, include_rmvpe=True)


if __name__ == "__main__":
    main()
