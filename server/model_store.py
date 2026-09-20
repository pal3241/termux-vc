from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ModelStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.active_file = self.root / ".active"

    @staticmethod
    def safe_name(name: str) -> str:
        clean = _SAFE.sub("_", name.strip()).strip("._")
        if not clean:
            raise ValueError("invalid model name")
        return clean[:80]

    def path(self, name: str) -> Path:
        return self.root / self.safe_name(name)

    def list(self) -> list[dict]:
        out = []
        active = self.active_name()
        for p in sorted(self.root.iterdir()):
            if not p.is_dir() or not (p / "model.onnx").is_file():
                continue
            meta = {}
            if (p / "meta.json").is_file():
                try:
                    meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
            out.append({"name": p.name, "active": p.name == active, "has_index": any(p.glob("*.index")), "meta": meta})
        return out

    def active_name(self) -> Optional[str]:
        if not self.active_file.is_file():
            return None
        value = self.active_file.read_text(encoding="utf-8").strip()
        return value or None

    def activate(self, name: str) -> str:
        name = self.safe_name(name)
        if not (self.path(name) / "model.onnx").is_file():
            raise FileNotFoundError(name)
        self.active_file.write_text(name, encoding="utf-8")
        return name

    def delete(self, name: str) -> None:
        name = self.safe_name(name)
        p = self.path(name)
        if p.is_dir():
            shutil.rmtree(p)
        if self.active_name() == name and self.active_file.exists():
            self.active_file.unlink()
