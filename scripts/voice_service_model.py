"""Verify the serving model, or reproduce its pinned conversion on a fresh workspace."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / ".cache/voice/PhoWhisper-small-ct2-f32"


def verify():
    lock = json.loads(
        (ROOT / "services/voice/model-lock.json").read_text(encoding="utf-8")
    )
    for name, expected in lock["files_sha256"].items():
        with (MODEL / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"Serving model checksum mismatch: {name}")
    print("Verified pinned PhoWhisper serving model.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if MODEL.exists():
        verify()
        return
    if args.check:
        raise SystemExit(2)
    from huggingface_hub import snapshot_download
    from ctranslate2.converters import TransformersConverter
    from scripts.voice_benchmark import verify_model

    lock = json.loads((ROOT / "voice-benchmark-lock.json").read_text(encoding="utf-8"))
    source = ROOT / ".cache/voice/PhoWhisper-small"
    snapshot_download(
        lock["model"],
        revision=lock["revision"],
        local_dir=source,
        cache_dir=ROOT / ".cache/huggingface",
        token=False,
        allow_patterns=[item["file"] for item in lock["files"]],
    )
    verify_model("phowhisper")
    TransformersConverter(
        str(source),
        copy_files=["tokenizer.json", "preprocessor_config.json"],
        load_as_float16=False,
    ).convert(str(MODEL), quantization="float32", force=False)
    verify()


if __name__ == "__main__":
    main()
