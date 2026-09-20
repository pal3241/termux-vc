# Termux VC

A two-device **real-time RVC voice changer**:

- **Android / Linux aarch64** = inference server (ONNX Runtime, ContentVec, RMVPE, optional FAISS `.index`)
- **Windows** = W-Okada-style control client (microphone, model import, pitch/index/protect, audio output)
- **USB/ADB** = direct PC ↔ Android transport; Wi-Fi is not required

The Windows UI accepts normal RVC **`.pth` + `.index`** files. On first import it automatically converts the `.pth` to an ONNX inference graph on Windows, uploads the graph + metadata + index to the phone, activates it, and then streams live PCM audio over USB.

> Status: **v0.1 MVP**. The full path is implemented. Real-time performance still depends heavily on the phone, so start with conservative buffers and tune downward.

## Architecture

```text
Windows microphone
      |
      v
Termux VC client ---- ADB USB ----> ARM64 server
      ^                              | ContentVec
      |                              | RMVPE
      |                              | FAISS index (optional)
      |                              | RVC ONNX
      +----------- converted PCM <---+
      |
      v
VB-CABLE / headphones / OBS / Discord
```

## 1. Android / Termux / Ubuntu ARM64

From native Termux, the easiest path is:

```bash
cd ~/termux-vc
git pull
bash termux_bootstrap.sh
```

The bootstrap installs/checks Ubuntu PRoot, clones or updates `termux-vc` inside Ubuntu, and runs the ARM64 installer there.

Manual equivalent:

```bash
pkg update
pkg install -y proot-distro git
proot-distro install ubuntu   # only if Ubuntu is not installed
proot-distro login ubuntu
```

Then inside Ubuntu:

```bash
cd ~
git clone https://github.com/pal3241/termux-vc.git   # first time only
cd termux-vc/server
bash install_arm64.sh
```

Do **not** run `server/install_arm64.sh` in native Termux. Native Termux uses Android/Bionic and does not provide the Ubuntu package set or the glibc ONNX Runtime environment expected by this server.

`install_arm64.sh` creates `server/.venv`, installs the ARM64 server dependencies, tries to install optional FAISS support, and downloads **INT8 RVC v2 ContentVec + RMVPE ONNX assets** for a lighter ARM64 CPU runtime. Runtime weights are intentionally not committed to Git.

Start the server:

```bash
cd ~/termux-vc/server
./run_server.sh
```

The server intentionally binds only to:

```text
127.0.0.1:18888
```

ADB exposes that local port to Windows through USB, so the server does not need to listen on your LAN.

For an RVC v1 model, download the v1 ContentVec asset too:

```bash
source .venv/bin/activate
python assets.py --v1
```

### CPU threads

Default:

```bash
TVC_THREADS=4 ./run_server.sh
```

Do not blindly use every core. On phones, more threads can increase heat and thermal throttling.

## 2. Windows client

Requirements:

- Python 3.11 or 3.12
- Git for Windows
- USB debugging enabled on Android
- VB-CABLE only if you want the converted voice to appear as a virtual microphone

Clone and install:

```powershell
git clone https://github.com/pal3241/termux-vc.git
cd termux-vc
Set-ExecutionPolicy -Scope Process Bypass
.\client\install.ps1
.\client\run.ps1
```

The installer creates:

- `.venv` — lightweight real-time Windows client
- `.converter-venv` — PyTorch/ONNX environment used only when importing `.pth`
- `.toolchain/rvc.onnx` — external RVC ONNX exporter
- `.toolchain/platform-tools` — official Android Platform Tools / `adb.exe`

PyTorch is deliberately kept out of the live audio path.

## 3. USB connection

1. Enable **Developer options → USB debugging** on Android.
2. Connect the phone by USB.
3. Accept Android's RSA debugging prompt.
4. Start the ARM64 server on the phone.
5. In the Windows app click **USB ADB Forward**.

The client forwards:

```text
Windows 127.0.0.1:18888
          ||
          || USB / ADB
          \/
Android 127.0.0.1:18888
```

No Wi-Fi or router is required.

## 4. Import `.pth` + `.index`

Open **Models → Import .pth + .index**.

The user-facing flow stays simple:

```text
model.pth
   |
   | one-time automatic export on Windows
   v
model.onnx + metadata
   |
model.index (optional)
   |
   +---------- upload over USB ---------> Android ARM64 server
                                           |
                                           v
                                      activate model
```

The original `.pth` is not used in the real-time server process. This avoids installing PyTorch on the phone.

The exporter detects RVC v1/v2 and F0/non-F0 metadata. The current import path uses the external MIT-licensed `SUC-DriverOld/rvc.onnx` exporter.

### `.index`

If the ARM64 environment has `faiss-cpu`, the server loads the uploaded RVC `.index` and exposes **Index rate** just like a normal RVC UI.

If FAISS is unavailable on a particular ARM64/Python combination, conversion still works. Set:

```text
Index rate = 0
```

and install/compile FAISS separately later.

## 5. Audio routing

For Discord + VB-CABLE:

```text
Termux VC output device -> CABLE Input
Discord input device    -> CABLE Output
```

Select your real microphone as **Input** in Termux VC. The GUI tries to select **CABLE Input** automatically when it exists.

## Controls

- **Pitch** — semitone shift
- **Index rate** — FAISS retrieval blend; `0` disables index retrieval
- **Protect** — consonant/unvoiced protection; RVC-style default `0.33`
- **Block** — audio packet duration
- **Context** — rolling context used by ContentVec/RMVPE/RVC
- **Speaker ID** — multi-speaker checkpoint selector
- **RTT / inference** — live timing shown in the GUI

### Starting values for Snapdragon-class phones

```text
Block:      240 or 320 ms
Context:    1200 ms
Threads:    4
Index rate: 0 first, then 0.5–0.75
Protect:    0.33
```

If **inference ms** is consistently greater than the selected block duration, the phone cannot keep up at that setting. First disable index retrieval or increase block size; do not immediately max out CPU threads.

## Server API

```text
GET    /health
GET    /models
POST   /models/upload
POST   /models/{name}/activate
DELETE /models/{name}
WS     /ws/audio
```

The WebSocket protocol uses a small binary header followed by mono signed 16-bit PCM. The server:

```text
PCM from PC
  -> resample 16 kHz
  -> rolling context
  -> ContentVec
  -> optional FAISS retrieval
  -> RMVPE F0
  -> RVC ONNX
  -> crop newest output
  -> resample to PC rate
  -> crossfade
  -> PCM back to Windows
```

## Build Windows GUI

For a convenience GUI build:

```powershell
.\client\build.ps1
```

Current output:

```text
dist\TermuxVC\TermuxVC.exe
```

The v0.1 EXE is not yet a completely self-contained installer: automatic first-time `.pth` conversion still relies on the converter environment/toolchain created by `client/install.ps1`.

## Known v0.1 limitations

- It is not a byte-for-byte W-Okada clone. It is a dedicated PC ↔ ARM64 RVC system with a similar workflow.
- ARM64 CPU inference may be too slow for tiny buffers. USB transport is normally not the main bottleneck; neural inference is.
- The current streaming backend re-runs inference over a rolling context for quality/stability. A split-graph/cached backend can reduce repeated work in a later version.
- Runtime ContentVec/RMVPE weights are downloaded during server setup; v2 defaults to the smaller INT8 variants.
- `.index` retrieval depends on FAISS availability on ARM64.
- This first commit is syntax-checked, but actual latency and model compatibility must still be benchmarked on the target phone.

## Development

Syntax check:

```bash
python -m compileall client server
bash -n server/install_arm64.sh server/run_server.sh
```

See `THIRD_PARTY_NOTICES.md` for upstream components and model-weight licensing notes.
