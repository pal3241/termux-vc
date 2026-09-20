from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


def _sample_rate(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        table = {"32k": 32000, "40k": 40000, "48k": 48000}
        if value in table:
            return table[value]
        try:
            return int(value)
        except ValueError:
            pass
    raise ValueError(f"Unsupported sample-rate metadata: {value!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--meta", type=Path, required=True)
    args = parser.parse_args()

    toolchain = args.toolchain.resolve()
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    meta_path = args.meta.resolve()

    sys.path.insert(0, str(toolchain))

    from rvc.modules.onnx.export import export_onnx

    cpt = torch.load(str(checkpoint), map_location="cpu", weights_only=False)
    if "weight" not in cpt or "config" not in cpt:
        raise ValueError(
            "This .pth is not an inference-ready RVC checkpoint "
            "(missing 'weight' or 'config')."
        )

    version = str(cpt.get("version", "v1"))
    if_f0 = int(cpt.get("f0", 1))
    if if_f0 != 1:
        raise ValueError(
            "Official fallback exporter currently supports F0 RVC checkpoints only."
        )

    config = list(cpt["config"])
    n_spk = int(cpt["weight"]["emb_g.weight"].shape[0])
    config[-3] = n_spk
    inter_channels = int(config[2])
    tgt_sr = _sample_rate(config[-1])

    output.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Fallback exporter: version={version}, f0={if_f0}, "
        f"sr={tgt_sr}, speakers={n_spk}"
    )
    export_onnx(str(checkpoint), str(output))

    meta = {
        "version": version,
        "if_f0": if_f0,
        "tgt_sr": tgt_sr,
        "n_spk": n_spk,
        "inter_channels": inter_channels,
        "config": config,
        "exporter": "RVC-Project/Retrieval-based-Voice-Conversion",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Exported: {output}")
    print(f"Metadata: {meta_path}")


if __name__ == "__main__":
    main()
