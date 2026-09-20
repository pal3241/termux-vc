# Third-party notices

Termux VC is an integration project. It does not bundle voice models or the large ContentVec/RMVPE runtime weights in Git.

- **RVC-Project / Retrieval-based-Voice-Conversion-WebUI** — MIT license. RVC architecture and compatibility target.
- **SUC-DriverOld/rvc.onnx** — MIT license. The Windows import path uses its RVC `.pth` → ONNX exporter as an external toolchain cloned during setup.
- **dev6699/rvc-onnx** — MIT license. The ARM64 runtime implementation is adapted from its ONNX ContentVec/RMVPE inference approach.
- **TigreGotico/voiceclonnx-rvc** — MIT license. Default RVC v2 ContentVec-768 and RMVPE INT8 ONNX runtime weights are downloaded during ARM64 setup, not stored in this repository.
- **MoeSS-SUBModel** — used only as the optional v1 ContentVec source; review the upstream model repository license before redistributing that asset.
- **Android Platform Tools / ADB** — downloaded from Google's official Android repository by the Windows installer and kept outside Git.

Users are responsible for having permission to use any imported voice model and voice data.
