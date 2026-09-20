from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import sounddevice as sd

from adb import forward as adb_forward
from api import ServerAPI
from audio_engine import AudioConfig, AudioEngine
from converter import convert_pth


class TermuxVCApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Termux VC — RVC over USB")
        self.geometry("840x650")
        self.minsize(780, 600)
        self.engine: AudioEngine | None = None
        self.devices = []

        self.server_url = tk.StringVar(value="http://127.0.0.1:18888")
        self.model_var = tk.StringVar()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.pitch = tk.DoubleVar(value=0)
        self.index_rate = tk.DoubleVar(value=0.65)
        self.protect = tk.DoubleVar(value=0.33)
        self.block_ms = tk.IntVar(value=240)
        self.context_ms = tk.IntVar(value=1200)
        self.sample_rate = tk.IntVar(value=48000)
        self.sid = tk.IntVar(value=0)
        self.status_var = tk.StringVar(value="Disconnected")
        self.latency_var = tk.StringVar(value="RTT -- ms | inference -- ms")
        self.log_var = tk.StringVar(value="Ready")

        self._build()
        self.refresh_devices()
        self.after(300, self.check_server)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    @property
    def api(self):
        return ServerAPI(self.server_url.get())

    def _build(self):
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=10)
        ttk.Label(
            top,
            text="Termux VC",
            font=("Segoe UI", 20, "bold"),
        ).pack(side="left")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        voice = ttk.Frame(nb)
        models = ttk.Frame(nb)
        server = ttk.Frame(nb)
        nb.add(voice, text="Voice Changer")
        nb.add(models, text="Models")
        nb.add(server, text="Server / USB")

        form = ttk.LabelFrame(voice, text="Audio")
        form.pack(fill="x", **pad)
        ttk.Label(form, text="Input (microphone)").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.input_combo = ttk.Combobox(
            form,
            textvariable=self.input_var,
            state="readonly",
            width=58,
        )
        self.input_combo.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(form, text="Output (VB-CABLE / headphones)").grid(
            row=1, column=0, sticky="w", **pad
        )
        self.output_combo = ttk.Combobox(
            form,
            textvariable=self.output_var,
            state="readonly",
            width=58,
        )
        self.output_combo.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(
            form,
            text="Refresh",
            command=self.refresh_devices,
        ).grid(row=0, column=2, rowspan=2, **pad)
        form.columnconfigure(1, weight=1)

        modelbox = ttk.LabelFrame(voice, text="RVC model")
        modelbox.pack(fill="x", **pad)
        ttk.Label(modelbox, text="Model").grid(
            row=0, column=0, sticky="w", **pad
        )
        self.model_combo = ttk.Combobox(
            modelbox,
            textvariable=self.model_var,
            state="readonly",
            width=42,
        )
        self.model_combo.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(
            modelbox,
            text="Import .pth + .index",
            command=self.import_model,
        ).grid(row=0, column=2, **pad)
        ttk.Button(
            modelbox,
            text="Refresh",
            command=self.refresh_models,
        ).grid(row=0, column=3, **pad)
        modelbox.columnconfigure(1, weight=1)

        controls = ttk.LabelFrame(voice, text="Conversion")
        controls.pack(fill="x", **pad)
        self._slider(controls, "Pitch (semitones)", self.pitch, -24, 24, 0)
        self._slider(controls, "Index rate", self.index_rate, 0, 1, 1)
        self._slider(controls, "Protect", self.protect, 0, 0.5, 2)

        ttk.Label(controls, text="Block").grid(
            row=3, column=0, sticky="w", **pad
        )
        ttk.Combobox(
            controls,
            textvariable=self.block_ms,
            values=[160, 200, 240, 320, 480],
            state="readonly",
            width=9,
        ).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(controls, text="Context").grid(
            row=3, column=2, sticky="w", **pad
        )
        ttk.Combobox(
            controls,
            textvariable=self.context_ms,
            values=[800, 1000, 1200, 1600, 2000],
            state="readonly",
            width=9,
        ).grid(row=3, column=3, sticky="w", **pad)
        ttk.Label(controls, text="Speaker ID").grid(
            row=3, column=4, sticky="w", **pad
        )
        ttk.Spinbox(
            controls,
            textvariable=self.sid,
            from_=0,
            to=255,
            width=6,
        ).grid(row=3, column=5, sticky="w", **pad)

        action = ttk.Frame(voice)
        action.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            action,
            text="START VOICE CHANGER",
            command=self.start_voice,
        )
        self.start_btn.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 5),
        )
        self.stop_btn = ttk.Button(
            action,
            text="STOP",
            command=self.stop_voice,
            state="disabled",
        )
        self.stop_btn.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(5, 0),
        )
        ttk.Label(
            voice,
            textvariable=self.latency_var,
            font=("Consolas", 11),
        ).pack(pady=8)

        model_page = ttk.Frame(models)
        model_page.pack(fill="both", expand=True, **pad)
        ttk.Label(
            model_page,
            text=(
                "Import model RVC biasa. Client mengubah .pth -> ONNX sekali, "
                "lalu mengirim ONNX + .index ke HP."
            ),
            wraplength=720,
        ).pack(anchor="w", pady=6)
        ttk.Button(
            model_page,
            text="Import .pth + .index",
            command=self.import_model,
        ).pack(anchor="w", pady=6)
        ttk.Button(
            model_page,
            text="Refresh model server",
            command=self.refresh_models,
        ).pack(anchor="w", pady=6)
        self.model_list = tk.Listbox(model_page, height=12)
        self.model_list.pack(fill="both", expand=True, pady=8)
        ttk.Label(
            model_page,
            textvariable=self.log_var,
            wraplength=720,
        ).pack(anchor="w", pady=8)

        server_page = ttk.Frame(server)
        server_page.pack(fill="both", expand=True, **pad)
        ttk.Label(server_page, text="Server URL").grid(
            row=0, column=0, sticky="w", **pad
        )
        ttk.Entry(
            server_page,
            textvariable=self.server_url,
            width=48,
        ).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(
            server_page,
            text="USB ADB Forward",
            command=self.usb_forward,
        ).grid(row=1, column=0, **pad)
        ttk.Button(
            server_page,
            text="Check server",
            command=self.check_server,
        ).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(
            server_page,
            text=(
                "ADB forwards PC localhost:18888 directly through USB to "
                "Android localhost:18888. Wi-Fi is not required."
            ),
            wraplength=680,
        ).grid(row=2, column=0, columnspan=2, sticky="w", **pad)
        server_page.columnconfigure(1, weight=1)

    def _slider(self, parent, label, var, lo, hi, row):
        ttk.Label(parent, text=label).grid(
            row=row,
            column=0,
            sticky="w",
            padx=10,
            pady=5,
        )
        scale = ttk.Scale(
            parent,
            variable=var,
            from_=lo,
            to=hi,
            orient="horizontal",
            command=lambda _=None: self.live_update(),
        )
        scale.grid(
            row=row,
            column=1,
            columnspan=4,
            sticky="ew",
            padx=10,
            pady=5,
        )
        value = ttk.Label(parent, width=7)
        value.grid(row=row, column=5, padx=10)

        def refresh(*_):
            value.configure(text=f"{var.get():.2f}")

        var.trace_add("write", refresh)
        refresh()
        parent.columnconfigure(1, weight=1)

    def log(self, text: str):
        self.after(0, lambda: self.log_var.set(text[-500:]))

    def refresh_devices(self):
        self.devices = list(sd.query_devices())
        inputs = []
        outputs = []
        for i, device in enumerate(self.devices):
            label = f"{i}: {device['name']}"
            if device["max_input_channels"] > 0:
                inputs.append(label)
            if device["max_output_channels"] > 0:
                outputs.append(label)

        self.input_combo["values"] = inputs
        self.output_combo["values"] = outputs

        if inputs and not self.input_var.get():
            self.input_var.set(inputs[0])
        if outputs and not self.output_var.get():
            cable = next(
                (x for x in outputs if "CABLE Input" in x),
                outputs[0],
            )
            self.output_var.set(cable)

    @staticmethod
    def _device_index(value: str) -> int:
        return int(value.split(":", 1)[0])

    def usb_forward(self):
        def job():
            try:
                dev = adb_forward(18888)
                self.log(
                    f"ADB USB tunnel ready: {dev} -> localhost:18888"
                )
                self.check_server()
            except Exception as exc:
                self.after(
                    0,
                    lambda: messagebox.showerror("ADB", str(exc)),
                )

        threading.Thread(target=job, daemon=True).start()

    def check_server(self):
        def job():
            try:
                health = self.api.health()
                text = (
                    f"Connected • {health.get('arch')} • "
                    f"ORT {health.get('onnxruntime')}"
                )
                self.after(0, lambda: self.status_var.set(text))
                self.after(0, self.refresh_models)
            except Exception as exc:
                self.after(
                    0,
                    lambda: self.status_var.set("Disconnected"),
                )
                self.log(str(exc))

        threading.Thread(target=job, daemon=True).start()

    def refresh_models(self):
        def job():
            try:
                items = self.api.models()
                names = [x["name"] for x in items]

                def apply():
                    self.model_combo["values"] = names
                    self.model_list.delete(0, tk.END)
                    for item in items:
                        active = "*" if item.get("active") else " "
                        has_index = "yes" if item.get("has_index") else "no"
                        self.model_list.insert(
                            tk.END,
                            f"{active} {item['name']}  index={has_index}",
                        )
                    if names and self.model_var.get() not in names:
                        self.model_var.set(names[0])

                self.after(0, apply)
            except Exception as exc:
                self.log(f"Model refresh: {exc}")

        threading.Thread(target=job, daemon=True).start()

    def import_model(self):
        pth = filedialog.askopenfilename(
            title="Select RVC .pth",
            filetypes=[("RVC model", "*.pth")],
        )
        if not pth:
            return

        folder = Path(pth).parent
        candidates = list(folder.glob("*.index"))
        initial_name = candidates[0].name if len(candidates) == 1 else ""
        idx = filedialog.askopenfilename(
            title="Select .index (optional; Cancel to skip)",
            initialdir=str(folder),
            initialfile=initial_name,
            filetypes=[("RVC index", "*.index")],
        )
        index = Path(idx) if idx else None
        model_name = Path(pth).stem

        def job():
            try:
                self.log("Preparing converter...")
                onnx, meta = convert_pth(
                    Path(pth),
                    precision="fp32",
                    log=self.log,
                )
                self.api.upload_model(
                    model_name,
                    onnx,
                    meta,
                    index,
                    progress=self.log,
                )
                self.log(f"Imported and activated: {model_name}")
                self.after(0, self.refresh_models)
                self.after(
                    0,
                    lambda: self.model_var.set(model_name),
                )
            except Exception as exc:
                error_text = str(exc)
                self.log(f"Import failed: {error_text}")
                self.after(
                    0,
                    lambda msg=error_text: messagebox.showerror(
                        "Model import failed",
                        msg,
                    ),
                )

        threading.Thread(target=job, daemon=True).start()

    def start_voice(self):
        if self.engine and self.engine.running.is_set():
            return
        if not self.model_var.get():
            messagebox.showwarning(
                "Model",
                "Import/select a model first.",
            )
            return

        try:
            in_dev = self._device_index(self.input_var.get())
            out_dev = self._device_index(self.output_var.get())
        except Exception:
            messagebox.showerror(
                "Audio",
                "Select input and output devices.",
            )
            return

        ws_url = (
            self.server_url.get()
            .replace("http://", "ws://")
            .replace("https://", "wss://")
            .rstrip("/")
            + "/ws/audio"
        )
        cfg = AudioConfig(
            ws_url=ws_url,
            model=self.model_var.get(),
            input_device=in_dev,
            output_device=out_dev,
            sample_rate=self.sample_rate.get(),
            block_ms=self.block_ms.get(),
            context_ms=self.context_ms.get(),
            pitch=self.pitch.get(),
            index_rate=self.index_rate.get(),
            protect=self.protect.get(),
            sid=self.sid.get(),
        )
        try:
            sd.check_input_settings(
                device=in_dev,
                channels=1,
                dtype="float32",
                samplerate=self.sample_rate.get(),
            )
            sd.check_output_settings(
                device=out_dev,
                channels=1,
                dtype="float32",
                samplerate=self.sample_rate.get(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Audio device error",
                f"Audio preflight failed:\n\n{exc}\n\n"
                "Try another microphone/output device or use 48000 Hz compatible devices.",
            )
            return

        self.engine = AudioEngine(cfg, status=self.audio_status)
        self.engine.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def stop_voice(self):
        if self.engine:
            self.engine.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("Stopped")

    def live_update(self):
        if self.engine:
            self.engine.update(
                pitch=self.pitch.get(),
                index_rate=self.index_rate.get(),
                protect=self.protect.get(),
                sid=self.sid.get(),
            )

    def audio_status(self, status: dict):
        def apply():
            state = status.get("state")
            if state == "running":
                self.status_var.set("Voice changer running")
                if "rtt_ms" in status:
                    self.latency_var.set(
                        f"RTT {status['rtt_ms']:.0f} ms | "
                        f"inference {status.get('infer_ms', 0)} ms | "
                        f"queue {status.get('queue', 0)}"
                    )
            elif state == "error":
                error_text = status.get("error", "unknown error")
                self.status_var.set("Error")
                self.latency_var.set(f"ERROR: {error_text}")
                self.log(error_text)
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                messagebox.showerror(
                    "Voice changer error",
                    error_text,
                )
            else:
                self.status_var.set(state or "...")

        self.after(0, apply)

    def on_close(self):
        if self.engine:
            self.engine.stop()
        self.destroy()


if __name__ == "__main__":
    TermuxVCApp().mainloop()
