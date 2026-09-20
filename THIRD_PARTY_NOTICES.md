# Third-party notices

Termux VC is an integration project. It does not bundle voice models or the large ContentVec/RMVPE runtime weights in Git.

- **RVC-Project / Retrieval-based-Voice-Conversion-WebUI** — MIT license. RVC architecture and compatibility target.
- **SUC-DriverOld/rvc.onnx** — MIT license. The Windows import path uses its RVC `.pth` → ONNX exporter as an external toolchain cloned during setup.
- **dev6699/rvc-onnx** — MIT license. The ARM64 runtime implementation is adapted from its ONNX ContentVec/RMVPE inference approach.
- **MoeSS-SUBModel runtime weights** — downloaded only when the user runs `server/assets.py`; the upstream model repository currently declares GPL-3.0. Review that repository's license before redistribution.
- **Android Platform Tools / ADB** — downloaded from Google's official Android repository by the Windows installer and kept outside Git.

Users are responsible for having permission to use any imported voice model and voice data.
