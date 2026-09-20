from __future__ import annotations

from pathlib import Path
import requests


class ServerAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        r = requests.get(f"{self.base_url}/health", timeout=5)
        r.raise_for_status()
        return r.json()

    def models(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/models", timeout=5)
        r.raise_for_status()
        return r.json()

    def activate(self, name: str) -> dict:
        r = requests.post(f"{self.base_url}/models/{name}/activate", timeout=60)
        if not r.ok:
            raise RuntimeError(_detail(r))
        return r.json()

    def upload_model(
        self,
        name: str,
        onnx_path: Path,
        meta_path: Path,
        index_path: Path | None = None,
        progress=None,
    ) -> dict:
        files = {
            "model": (onnx_path.name, onnx_path.open("rb"), "application/octet-stream"),
            "meta": (meta_path.name, meta_path.open("rb"), "application/json"),
        }
        if index_path:
            files["index"] = (
                index_path.name,
                index_path.open("rb"),
                "application/octet-stream",
            )
        try:
            if progress:
                progress("Uploading model to ARM64 server...")
            r = requests.post(
                f"{self.base_url}/models/upload",
                data={"name": name},
                files=files,
                timeout=600,
            )
            if not r.ok:
                raise RuntimeError(_detail(r))
            return r.json()
        finally:
            for _, item in files.items():
                item[1].close()


def _detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("detail", payload))
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:500]}"
