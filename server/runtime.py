from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import onnxruntime as ort
from scipy import signal

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

SR_CONTENT = 16_000
WINDOW = 160


class MelSpectrogram:
    def __init__(self, n_mels=128, sr=16000, win_length=1024, hop_length=160, fmin=30, fmax=8000):
        self.win_length = win_length
        self.hop_length = hop_length
        self.n_fft = win_length
        self.mel_basis = librosa.filters.mel(
            sr=sr, n_fft=self.n_fft, n_mels=n_mels, fmin=fmin, fmax=fmax, htk=True
        ).astype(np.float32)

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        window = signal.windows.hann(self.win_length, sym=False)
        spec = librosa.stft(
            audio.astype(np.float32),
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.win_length,
            window=window,
            center=True,
        )
        mel = self.mel_basis @ np.abs(spec)
        return np.log(np.maximum(mel, 1e-5)).astype(np.float32)


class RMVPE:
    def __init__(self, model_path: Path, providers: list[str], sess_opts: ort.SessionOptions):
        self.mel = MelSpectrogram()
        self.session = ort.InferenceSession(str(model_path), sess_options=sess_opts, providers=providers)
        cents = 20 * np.arange(360) + 1997.3794084376191
        self.cents_mapping = np.pad(cents, (4, 4))

    def infer(self, audio: np.ndarray, threshold: float = 0.03) -> np.ndarray:
        mel = self.mel(audio)
        frames = mel.shape[-1]
        pad = 32 * ((frames - 1) // 32 + 1) - frames
        if pad > 0:
            mel = np.pad(mel, ((0, 0), (0, pad)), mode="constant")
        inp = mel[None, ...].astype(np.float32)
        name = self.session.get_inputs()[0].name
        out_name = self.session.get_outputs()[0].name
        hidden = self.session.run([out_name], {name: inp})[0][:, :, :frames].squeeze(0)

        center = np.argmax(hidden, axis=1)
        salience = np.pad(hidden, ((0, 0), (4, 4)))
        center += 4
        cents_out = np.zeros(hidden.shape[0], dtype=np.float32)
        confidence = np.max(hidden, axis=1)

        for i, c in enumerate(center):
            sl = salience[i, c - 4:c + 5]
            cm = self.cents_mapping[c - 4:c + 5]
            denom = float(sl.sum())
            cents_out[i] = float((sl * cm).sum() / denom) if denom > 1e-12 else 0.0

        cents_out[confidence <= threshold] = 0.0
        f0 = 10.0 * (2.0 ** (cents_out / 1200.0))
        f0[cents_out == 0] = 0.0
        return f0.astype(np.float32)


class ContentVec:
    def __init__(self, model_path: Path, providers: list[str], sess_opts: ort.SessionOptions):
        self.session = ort.InferenceSession(str(model_path), sess_options=sess_opts, providers=providers)

    def infer(self, audio: np.ndarray) -> np.ndarray:
        x = audio.astype(np.float32)
        if x.ndim == 2:
            x = x.mean(axis=-1)
        x = x[None, None, :]
        inp_name = self.session.get_inputs()[0].name
        y = self.session.run(None, {inp_name: x})[0]
        return y.transpose(0, 2, 1).astype(np.float32)


class IndexRetriever:
    def __init__(self, path: Optional[Path]):
        self.index = None
        self.vectors = None
        self.error: str | None = None
        if path and path.is_file():
            if faiss is None:
                self.error = "faiss-cpu is not installed; index retrieval is disabled"
                return
            try:
                self.index = faiss.read_index(str(path))
                self.vectors = self.index.reconstruct_n(0, self.index.ntotal)
            except Exception as exc:
                self.error = f"failed to load index: {exc}"

    @property
    def enabled(self) -> bool:
        return self.index is not None and self.vectors is not None

    def mix(self, feats: np.ndarray, rate: float) -> np.ndarray:
        if not self.enabled or rate <= 0:
            return feats
        base = feats[0].astype(np.float32)
        score, ix = self.index.search(base, k=8)
        score = np.maximum(score, 1e-6)
        weight = np.square(1.0 / score)
        weight /= np.maximum(weight.sum(axis=1, keepdims=True), 1e-12)
        retrieved = np.sum(self.vectors[ix] * weight[..., None], axis=1)
        return (retrieved[None, ...] * rate + feats * (1.0 - rate)).astype(np.float32)


def _pitch_bins(f0: np.ndarray, semitones: float) -> tuple[np.ndarray, np.ndarray]:
    shifted = f0.astype(np.float32) * (2.0 ** (float(semitones) / 12.0))
    coarse = shifted.copy()
    f0_min, f0_max = 50.0, 1100.0
    mel_min = 1127 * np.log(1 + f0_min / 700)
    mel_max = 1127 * np.log(1 + f0_max / 700)
    mel = 1127 * np.log(1 + coarse / 700)
    voiced = mel > 0
    mel[voiced] = (mel[voiced] - mel_min) * 254 / (mel_max - mel_min) + 1
    mel[mel <= 1] = 1
    mel[mel > 255] = 255
    return np.rint(mel).astype(np.int64), shifted.astype(np.float32)


@dataclass
class ModelMeta:
    version: str = "v2"
    if_f0: int = 1
    tgt_sr: int = 40000
    n_spk: int = 1
    inter_channels: int = 192

    @classmethod
    def from_path(cls, path: Path) -> "ModelMeta":
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=str(raw.get("version", "v2")),
            if_f0=int(raw.get("if_f0", raw.get("f0", 1))),
            tgt_sr=int(raw.get("tgt_sr", raw.get("sr", 40000))),
            n_spk=int(raw.get("n_spk", 1)),
            inter_channels=int(raw.get("inter_channels", 192)),
        )


class RVCEngine:
    """Stateful ONNX RVC engine optimized for repeated streaming windows."""

    def __init__(self, model_dir: Path, assets_dir: Path, threads: int = 4):
        self.model_dir = model_dir
        self.meta = ModelMeta.from_path(model_dir / "meta.json")
        self.lock = threading.Lock()

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = max(1, int(threads))
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.log_severity_level = 3
        providers = ["CPUExecutionProvider"]

        model_path = model_dir / "model.onnx"
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        self.rvc = ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)

        vec_name = "vec-768-layer-12.onnx" if self.meta.version == "v2" else "vec-256-layer-9.onnx"
        vec_path = assets_dir / vec_name
        rmvpe_path = assets_dir / "RMVPE.onnx"

        if not vec_path.is_file():
            raise FileNotFoundError(f"Missing runtime asset: {vec_path}")
        if self.meta.if_f0 and not rmvpe_path.is_file():
            raise FileNotFoundError(f"Missing runtime asset: {rmvpe_path}")

        self.vec = ContentVec(vec_path, providers, opts)
        self.rmvpe = RMVPE(rmvpe_path, providers, opts) if self.meta.if_f0 else None
        idx = next(model_dir.glob("*.index"), None)
        self.retriever = IndexRetriever(idx)
        self._bh, self._ah = signal.butter(5, 48, btype="high", fs=SR_CONTENT)

    def infer(self, audio16: np.ndarray, pitch: float, index_rate: float, protect: float, sid: int) -> np.ndarray:
        if audio16.size < 2048:
            audio16 = np.pad(audio16, (0, 2048 - audio16.size))

        peak = np.max(np.abs(audio16)) / 0.95
        if peak > 1:
            audio16 = audio16 / peak

        try:
            filtered = signal.filtfilt(self._bh, self._ah, audio16).astype(np.float32)
        except ValueError:
            filtered = audio16.astype(np.float32)

        with self.lock:
            feats = self.vec.infer(filtered)
            feats0 = feats.copy()
            feats = self.retriever.mix(feats, float(index_rate))

            feats = np.repeat(feats, 2, axis=1)
            feats0 = np.repeat(feats0, 2, axis=1)
            p_len = min(feats.shape[1], filtered.shape[0] // WINDOW)
            feats = feats[:, :p_len, :]
            feats0 = feats0[:, :p_len, :]

            feed: dict[str, np.ndarray] = {
                "phone": np.ascontiguousarray(feats, dtype=np.float32),
                "lengths": np.array([p_len], dtype=np.int64),
                "sid": np.array([max(0, min(int(sid), self.meta.n_spk - 1))], dtype=np.int64),
                "noise": np.random.randn(1, self.meta.inter_channels, p_len).astype(np.float32),
            }

            if self.meta.if_f0:
                assert self.rmvpe is not None
                f0 = self.rmvpe.infer(filtered)
                if f0.size < p_len:
                    f0 = np.pad(f0, (0, p_len - f0.size))
                f0 = f0[:p_len]

                coarse, fine = _pitch_bins(f0, pitch)
                coarse = coarse[None, :]
                fine = fine[None, :]

                if protect < 0.5:
                    gate = np.where(fine > 0, 1.0, float(protect)).astype(np.float32)[..., None]
                    feats = feats * gate + feats0 * (1.0 - gate)
                    feed["phone"] = np.ascontiguousarray(feats, dtype=np.float32)

                feed["pitch"] = np.ascontiguousarray(coarse, dtype=np.int64)
                feed["nsff0"] = np.ascontiguousarray(fine, dtype=np.float32)

            actual = [i.name for i in self.rvc.get_inputs()]
            if not set(feed).issubset(set(actual)):
                canonical = (
                    ["phone", "lengths", "pitch", "nsff0", "sid", "noise"]
                    if self.meta.if_f0
                    else ["phone", "lengths", "sid", "noise"]
                )
                ordered = [feed[k] for k in canonical]
                feed = {name: value for name, value in zip(actual, ordered)}

            y = self.rvc.run(None, feed)[0]

        y = np.asarray(y).squeeze().astype(np.float32)
        peak = np.max(np.abs(y)) if y.size else 0.0
        if peak > 0.99:
            y = y / peak * 0.99
        return y


class StreamingProcessor:
    def __init__(
        self,
        engine: RVCEngine,
        input_rate: int,
        output_rate: int,
        context_ms: int = 1200,
        crossfade_ms: int = 20,
    ):
        self.engine = engine
        self.input_rate = int(input_rate)
        self.output_rate = int(output_rate)
        self.context_samples = max(3200, int(SR_CONTENT * context_ms / 1000))
        self.buffer = np.zeros(self.context_samples, dtype=np.float32)
        self.crossfade_samples = max(0, int(self.output_rate * crossfade_ms / 1000))
        self.prev_tail = np.zeros(self.crossfade_samples, dtype=np.float32)

    @staticmethod
    def _resample(x: np.ndarray, orig: int, target: int) -> np.ndarray:
        if orig == target:
            return x.astype(np.float32, copy=False)
        g = math.gcd(orig, target)
        return signal.resample_poly(x, target // g, orig // g).astype(np.float32)

    def process(self, pcm16: bytes, pitch: float, index_rate: float, protect: float, sid: int) -> bytes:
        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        x16 = self._resample(x, self.input_rate, SR_CONTENT)

        if x16.size >= self.context_samples:
            self.buffer = x16[-self.context_samples:].copy()
        else:
            self.buffer = np.roll(self.buffer, -x16.size)
            self.buffer[-x16.size:] = x16

        y = self.engine.infer(
            self.buffer,
            pitch=pitch,
            index_rate=index_rate,
            protect=protect,
            sid=sid,
        )

        wanted_model = max(1, round(len(x) / self.input_rate * self.engine.meta.tgt_sr))
        tail = y[-wanted_model:] if y.size >= wanted_model else np.pad(y, (wanted_model - y.size, 0))
        out = self._resample(tail, self.engine.meta.tgt_sr, self.output_rate)

        wanted_out = max(1, round(len(x) / self.input_rate * self.output_rate))
        if out.size > wanted_out:
            out = out[-wanted_out:]
        elif out.size < wanted_out:
            out = np.pad(out, (wanted_out - out.size, 0))

        n = min(self.crossfade_samples, out.size, self.prev_tail.size)
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
            out[:n] = self.prev_tail[-n:] * (1.0 - ramp) + out[:n] * ramp
            self.prev_tail = out[-self.crossfade_samples:].copy()

        out = np.clip(out, -1.0, 1.0)
        return (out * 32767.0).astype("<i2").tobytes()
