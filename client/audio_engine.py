from __future__ import annotations

import json
import queue
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import sounddevice as sd
import websocket

PACKET = struct.Struct("<4sIIHH")
MAGIC = b"TVC1"


@dataclass
class AudioConfig:
    ws_url: str
    model: str
    input_device: int
    output_device: int
    sample_rate: int = 48000
    block_ms: int = 240
    context_ms: int = 1200
    pitch: float = 0.0
    index_rate: float = 0.0
    protect: float = 0.33
    sid: int = 0


class AudioEngine:
    def __init__(
        self,
        cfg: AudioConfig,
        status: Callable[[dict], None] | None = None,
    ):
        self.cfg = cfg
        self.status = status or (lambda _: None)
        self.running = threading.Event()
        self.in_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=2)
        self.out_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=6)
        self.thread: threading.Thread | None = None
        self.ws = None
        self.seq = 0
        self.sent_at: dict[int, float] = {}
        self.input_stream = None
        self.output_stream = None

    @property
    def block_samples(self) -> int:
        return max(256, int(self.cfg.sample_rate * self.cfg.block_ms / 1000))

    def start(self):
        if self.running.is_set():
            return
        self.running.set()
        self.thread = threading.Thread(target=self._network_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running.clear()
        for stream in (self.input_stream, self.output_stream):
            try:
                if stream:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self.cfg, key):
                setattr(self.cfg, key, value)
        try:
            if self.ws:
                self.ws.send(
                    json.dumps(
                        {
                            "type": "config",
                            "pitch": self.cfg.pitch,
                            "index_rate": self.cfg.index_rate,
                            "protect": self.cfg.protect,
                            "sid": self.cfg.sid,
                        }
                    )
                )
        except Exception:
            pass

    def _input_cb(self, indata, frames, time_info, status):
        if not self.running.is_set():
            return
        x = np.asarray(indata[:, 0], dtype=np.float32).copy()
        try:
            self.in_q.put_nowait(x)
        except queue.Full:
            # Drop the oldest unprocessed block instead of building latency forever.
            try:
                self.in_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.in_q.put_nowait(x)
            except queue.Full:
                pass

    def _output_cb(self, outdata, frames, time_info, status):
        try:
            x = self.out_q.get_nowait()
        except queue.Empty:
            outdata.fill(0)
            return
        if x.size < frames:
            x = np.pad(x, (0, frames - x.size))
        outdata[:, 0] = x[:frames]

    def _open_audio(self):
        self.input_stream = sd.InputStream(
            device=self.cfg.input_device,
            samplerate=self.cfg.sample_rate,
            blocksize=self.block_samples,
            channels=1,
            dtype="float32",
            callback=self._input_cb,
        )
        self.output_stream = sd.OutputStream(
            device=self.cfg.output_device,
            samplerate=self.cfg.sample_rate,
            blocksize=self.block_samples,
            channels=1,
            dtype="float32",
            callback=self._output_cb,
        )
        self.output_stream.start()
        self.input_stream.start()

    def _network_loop(self):
        try:
            self.status({"state": "connecting"})
            self.ws = websocket.create_connection(
                self.cfg.ws_url,
                timeout=30,
                enable_multithread=True,
            )
            self.ws.send(
                json.dumps(
                    {
                        "model": self.cfg.model,
                        "input_rate": self.cfg.sample_rate,
                        "output_rate": self.cfg.sample_rate,
                        "context_ms": self.cfg.context_ms,
                        "pitch": self.cfg.pitch,
                        "index_rate": self.cfg.index_rate,
                        "protect": self.cfg.protect,
                        "sid": self.cfg.sid,
                    }
                )
            )
            hello = self.ws.recv()
            if not isinstance(hello, str):
                raise RuntimeError("Server did not send a ready response")
            payload = json.loads(hello)
            if payload.get("type") == "error":
                raise RuntimeError(payload.get("message", "server error"))

            self._open_audio()
            self.status({"state": "running", "server": payload})

            while self.running.is_set():
                try:
                    x = self.in_q.get(timeout=0.5)
                except queue.Empty:
                    continue

                pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
                self.seq = (self.seq + 1) & 0xFFFFFFFF
                seq = self.seq
                self.sent_at[seq] = time.perf_counter()
                packet = PACKET.pack(
                    MAGIC,
                    seq,
                    self.cfg.sample_rate,
                    1,
                    0,
                ) + pcm
                self.ws.send_binary(packet)

                resp = self.ws.recv()
                if isinstance(resp, str):
                    obj = json.loads(resp)
                    if obj.get("type") == "error":
                        raise RuntimeError(obj.get("message", "server error"))
                    continue
                if len(resp) < PACKET.size:
                    continue

                magic, rseq, sr, channels, infer_ms = PACKET.unpack_from(resp)
                if magic != MAGIC or channels != 1:
                    continue

                audio = (
                    np.frombuffer(resp[PACKET.size:], dtype="<i2").astype(np.float32)
                    / 32768.0
                )
                try:
                    self.out_q.put_nowait(audio)
                except queue.Full:
                    try:
                        self.out_q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.out_q.put_nowait(audio)
                    except queue.Full:
                        pass

                rtt = (
                    time.perf_counter()
                    - self.sent_at.pop(rseq, time.perf_counter())
                ) * 1000
                self.status(
                    {
                        "state": "running",
                        "rtt_ms": rtt,
                        "infer_ms": infer_ms,
                        "queue": self.in_q.qsize(),
                    }
                )

        except Exception as exc:
            self.status({"state": "error", "error": str(exc)})
        finally:
            self.running.clear()
            try:
                if self.ws:
                    self.ws.close()
            except Exception:
                pass
            for stream in (self.input_stream, self.output_stream):
                try:
                    if stream:
                        stream.stop()
                        stream.close()
                except Exception:
                    pass
