from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import struct
import time
from functools import lru_cache
from pathlib import Path

import onnxruntime as ort
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from model_store import ModelStore
from runtime import RVCEngine, StreamingProcessor

BASE = Path(__file__).resolve().parent
MODELS = Path(os.getenv("TVC_MODELS", BASE / "models"))
ASSETS = Path(os.getenv("TVC_ASSETS", BASE / "assets"))
THREADS = int(os.getenv("TVC_THREADS", "4"))
store = ModelStore(MODELS)
app = FastAPI(title="Termux VC ARM64 Server", version="0.1.0")

PACKET = struct.Struct("<4sIIHH")
MAGIC = b"TVC1"
logger = logging.getLogger("termux_vc.server")


@lru_cache(maxsize=3)
def load_engine(name: str) -> RVCEngine:
    return RVCEngine(store.path(name), ASSETS, threads=THREADS)


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "arch": platform.machine(),
        "platform": platform.platform(),
        "onnxruntime": ort.__version__,
        "providers": ort.get_available_providers(),
        "threads": THREADS,
        "assets": {
            "v2": (ASSETS / "vec-768-layer-12.onnx").is_file(),
            "v1": (ASSETS / "vec-256-layer-9.onnx").is_file(),
            "rmvpe": (ASSETS / "RMVPE.onnx").is_file(),
        },
        "active_model": store.active_name(),
        "models": store.list(),
    }


@app.get("/models")
def models():
    return store.list()


@app.post("/models/upload")
async def upload_model(
    name: str = Form(...),
    model: UploadFile = File(...),
    meta: UploadFile = File(...),
    index: UploadFile | None = File(None),
):
    name = store.safe_name(name)
    target = store.path(name)
    target.mkdir(parents=True, exist_ok=True)
    try:
        model_bytes = await model.read()
        meta_bytes = await meta.read()
        if len(model_bytes) < 1024:
            raise ValueError("ONNX file is unexpectedly small")
        json.loads(meta_bytes.decode("utf-8"))
        (target / "model.onnx").write_bytes(model_bytes)
        (target / "meta.json").write_bytes(meta_bytes)
        for old in target.glob("*.index"):
            old.unlink()
        if index is not None:
            idx_bytes = await index.read()
            if idx_bytes:
                (target / (Path(index.filename or "model.index").name)).write_bytes(idx_bytes)
        load_engine.cache_clear()
        store.activate(name)
        return {"ok": True, "name": name, "active": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/models/{name}/activate")
def activate(name: str):
    try:
        store.activate(name)
        load_engine.cache_clear()
        engine = load_engine(store.safe_name(name))
        return {
            "ok": True,
            "name": name,
            "meta": engine.meta.__dict__,
            "index": engine.retriever.enabled,
            "index_error": engine.retriever.error,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/models/{name}")
def delete(name: str):
    store.delete(name)
    load_engine.cache_clear()
    return {"ok": True}


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket):
    await ws.accept()
    try:
        first = await ws.receive_text()
        cfg = json.loads(first)
        model_name = store.safe_name(cfg.get("model") or store.active_name() or "")
        if not model_name:
            await ws.send_text(json.dumps({"type": "error", "message": "No model selected"}))
            await ws.close(code=1008)
            return

        engine = load_engine(model_name)
        input_rate = int(cfg.get("input_rate", 48000))
        output_rate = int(cfg.get("output_rate", 48000))
        context_ms = int(cfg.get("context_ms", 1200))
        processor = StreamingProcessor(
            engine,
            input_rate,
            output_rate,
            context_ms=context_ms,
        )
        await ws.send_text(json.dumps({
            "type": "ready",
            "model": model_name,
            "model_sr": engine.meta.tgt_sr,
            "version": engine.meta.version,
            "index": engine.retriever.enabled,
        }))

        while True:
            msg = await ws.receive()
            if msg.get("text") is not None:
                update = json.loads(msg["text"])
                if update.get("type") == "config":
                    cfg.update(update)
                continue

            raw = msg.get("bytes")
            if not raw or len(raw) < PACKET.size:
                continue

            magic, seq, sample_rate, channels, flags = PACKET.unpack_from(raw)
            if magic != MAGIC or channels != 1:
                continue

            if sample_rate != processor.input_rate:
                processor = StreamingProcessor(
                    engine,
                    sample_rate,
                    output_rate,
                    context_ms=context_ms,
                )

            started = time.perf_counter()
            audio = raw[PACKET.size:]
            out = await asyncio.to_thread(
                processor.process,
                audio,
                float(cfg.get("pitch", 0)),
                float(cfg.get("index_rate", 0.0)),
                float(cfg.get("protect", 0.33)),
                int(cfg.get("sid", 0)),
            )
            infer_ms = int((time.perf_counter() - started) * 1000)
            header = PACKET.pack(MAGIC, seq, output_rate, 1, min(infer_ms, 65535))
            await ws.send_bytes(header + out)

    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.exception("WebSocket voice session failed")
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        finally:
            await ws.close(code=1011)


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
