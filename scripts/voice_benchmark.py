"""Paired CPU speech benchmark; heavy dependencies are isolated from gameplay.

prepare/score: node scripts/voice-compare.mjs
inference: .cache/voice-benchmark-venv/Scripts/python.exe scripts/voice_benchmark.py
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import statistics
import time
import unicodedata
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize(text, canonical=False):
    text = unicodedata.normalize("NFC", text).lower()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    if canonical:
        # Only equivalent notation. Do not strip unknown words, negation or accents,
        # or guess a rank from legal moves. Apply identically to both systems.
        text = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", text)
        aliases = dict(
            zip(
                "012345678",
                ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám"],
            )
        )
        aliases["f"] = "ép"
        text = " ".join(aliases.get(word, word) for word in text.split())
    return " ".join(text.split())


def word_errors(reference, hypothesis):
    left, right = reference.split(), hypothesis.split()
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    return row[-1]


def accuracy(rows, canonical=False):
    pairs = [(normalize(a, canonical), normalize(b, canonical)) for a, b in rows]
    words = sum(len(a.split()) for a, _ in pairs)
    errors = sum(word_errors(a, b) for a, b in pairs)
    exact = sum(a == b for a, b in pairs)
    return {
        "total": len(pairs),
        "exact": exact,
        "exact_rate": exact / len(pairs) if pairs else None,
        "ref_words": words,
        "word_errors": errors,
        "wer": errors / words if words else None,
    }


def latency(rows):
    times = sorted(row["total_s"] * 1000 for row in rows)
    p = (len(times) - 1) * 0.95
    p95 = times[math.floor(p)] * (1 - p % 1) + times[math.ceil(p)] * (p % 1)
    return {
        "count": len(times),
        "median_ms": statistics.median(times),
        "mean_ms": statistics.mean(times),
        "p95_ms": p95,
        "rtf": sum(r["total_s"] for r in rows) / sum(r["duration_s"] for r in rows),
    }


def verify_model(engine):
    """Bind each run to the official pinned source, without remote model code."""
    if engine == "phowhisper":
        lock = json.loads(
            (ROOT / "voice-benchmark-lock.json").read_text(encoding="utf-8")
        )
        directory = ROOT / ".cache/voice/PhoWhisper-small"
        files = {}
        for item in lock["files"]:
            path = directory / item["file"]
            assert path.stat().st_size == item["bytes"], (
                f"Wrong model file size: {path}"
            )
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            if "sha256" in item:
                assert sha == item["sha256"], f"Wrong model checksum: {path}"
            else:
                data = path.read_bytes()
                blob = hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()
                assert blob == item["git_blob_sha1"], f"Wrong model Git blob: {path}"
            files[item["file"]] = sha
        return {
            "model": lock["model"],
            "revision": lock["revision"],
            "files_sha256": files,
        }
    source = ROOT / ".cache/voice/vosk-model-small-vn-0.4.zip"
    lock = json.loads((ROOT / "voice-model-lock.json").read_text(encoding="utf-8"))
    with source.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    assert sha == lock["source_sha256"], "Wrong Vosk source archive"
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            if not item.is_dir():
                path = ROOT / ".cache/voice" / item.filename
                assert path.read_bytes() == archive.read(item), (
                    f"Extracted Vosk differs: {path}"
                )
    return {"model": "vosk-model-small-vn-0.4", "source_sha256": sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine", choices=["vosk-open", "vosk-position", "phowhisper"], required=True
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/voice-comparison/dataset.json",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--limit",
        type=int,
        help="Diagnostic prefix only; never mix with the full report",
    )
    args = parser.parse_args()
    if args.repeats < 1 or args.threads < 1:
        parser.error("repeats and threads must be positive")
    for key in [
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ]:
        os.environ[key] = str(args.threads)
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import numpy as np
    import psutil

    dataset = json.loads(args.manifest.read_text(encoding="utf-8"))
    provenance = verify_model(args.engine)
    audios = {}
    for item in dataset["audio"]:
        source = args.manifest.parent / item["pcm_file"]
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["pcm_sha256"]:
            raise ValueError(f"PCM checksum mismatch: {source}")
        audios[item["id"]] = np.frombuffer(raw, dtype="<f4").copy()
    work = dataset["scenarios"] + dataset["diagnostics"]
    if args.limit:
        work = work[: args.limit]
    process = psutil.Process()
    initial_memory = process.memory_info().rss
    loaded_at = time.perf_counter()
    if args.engine.startswith("vosk"):
        from vosk import KaldiRecognizer, Model, SetLogLevel, _c, _ffi

        SetLogLevel(-1)
        model = Model(str(ROOT / ".cache/voice/vosk-model-small-vn-0.4"))

        def transcribe(item):
            started = time.perf_counter()
            if args.engine == "vosk-position":
                rec = KaldiRecognizer(
                    model,
                    16000,
                    json.dumps(
                        dataset["grammars"][item["grammar_id"]], ensure_ascii=False
                    ),
                )
            else:
                rec = KaldiRecognizer(model, 16000)
            scaled = np.ascontiguousarray(
                audios[item.get("audio_id", item["id"])] * 32768, dtype=np.float32
            )
            setup_done = time.perf_counter()
            chunks = []
            for offset in range(0, len(scaled), 2048):
                frame = scaled[offset : offset + 2048]
                if _c.vosk_recognizer_accept_waveform_f(
                    rec._handle, _ffi.cast("float *", frame.ctypes.data), len(frame)
                ):
                    chunks.append(json.loads(rec.Result())["text"])
            chunks.append(json.loads(rec.FinalResult())["text"])
            text = " ".join(t for t in chunks if t)
            finished = time.perf_counter()
            return {
                "text": text,
                "fragments": chunks,
                "setup_s": setup_done - started,
                "decode_s": finished - setup_done,
                "total_s": finished - started,
            }
    else:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        model_dir = ROOT / ".cache/voice/PhoWhisper-small"
        processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
        model = WhisperForConditionalGeneration.from_pretrained(
            model_dir,
            local_files_only=True,
            torch_dtype=torch.float32,
            attn_implementation="sdpa",
            weights_only=True,
        ).eval()
        model.generation_config.forced_decoder_ids = None

        def transcribe(item):
            started = time.perf_counter()
            features = processor(
                audios[item["audio_id"]],
                sampling_rate=16000,
                return_tensors="pt",
                return_attention_mask=True,
            )
            setup_done = time.perf_counter()
            with torch.inference_mode():
                ids = model.generate(
                    **features,
                    language="vi",
                    task="transcribe",
                    do_sample=False,
                    num_beams=1,
                    max_new_tokens=64,
                    return_timestamps=False,
                )
            text = processor.batch_decode(ids, skip_special_tokens=True)[0]
            finished = time.perf_counter()
            return {
                "text": text,
                "tokens": ids.shape[-1],
                "ended_with_eos": ids[0, -1].item() == model.config.eos_token_id,
                "setup_s": setup_done - started,
                "decode_s": finished - setup_done,
                "total_s": finished - started,
            }

    load_s = time.perf_counter() - loaded_at
    ready_memory = process.memory_info().rss
    warmup = transcribe(work[0])
    print(
        f"{args.engine}: loaded in {load_s:.3f}s; warmup {warmup['total_s']:.3f}s",
        flush=True,
    )
    results = []
    for repeat in range(args.repeats):
        order = list(work)
        random.Random(1711 + repeat).shuffle(order)
        for n, item in enumerate(order):
            answer = transcribe(item)
            audio_id = item.get("audio_id", item["id"])
            answer.update(
                id=item["id"],
                audio_id=audio_id,
                repeat=repeat,
                reference=item["text"],
                duration_s=len(audios[audio_id]) / 16000,
                profile=item["profile"],
                diagnostic=bool(item.get("diagnostic")),
            )
            answer["canonical_text"] = normalize(answer["text"], canonical=True)
            if "fragments" in answer:
                answer["canonical_fragments"] = [
                    normalize(t, canonical=True) for t in answer["fragments"]
                ]
            results.append(answer)
            if n % 10 == 0 or n + 1 == len(order):
                print(
                    f"{args.engine} repeat {repeat + 1}/{args.repeats}: {n + 1}/{len(order)}",
                    flush=True,
                )
    primary = [r for r in results if r["repeat"] == 0 and not r["diagnostic"]]
    measured = [r for r in results if not r["diagnostic"]]
    report = {
        "recorded_utc": datetime.now(UTC).isoformat(),
        "engine": args.engine,
        "model_provenance": provenance,
        "dataset_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "configuration": {
            "device": "cpu",
            "thread_cap": args.threads,
            "repeats": args.repeats,
            "diagnostic_limit": args.limit,
            "precision": "float32",
            "sample_rate_hz": 16000,
            "phowhisper": {
                "language": "vi",
                "task": "transcribe",
                "beams": 1,
                "max_new_tokens": 64,
                "prompts": False,
            },
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "logical_cpus": psutil.cpu_count(),
            "physical_cpus": psutil.cpu_count(logical=False),
            "ram_bytes": psutil.virtual_memory().total,
            "packages": {
                name: importlib.metadata.version(name)
                for name in ["torch", "transformers", "numpy", "vosk", "psutil"]
            },
        },
        "startup": {
            "imports_and_model_load_s": load_s,
            "warmup_s": warmup["total_s"],
            "rss_before_model_bytes": initial_memory,
            "rss_ready_bytes": ready_memory,
            "rss_after_inference_bytes": process.memory_info().rss,
        },
        "accuracy": {
            "normalized": accuracy([(r["reference"], r["text"]) for r in primary]),
            "canonical": accuracy(
                [(r["reference"], r["text"]) for r in primary], canonical=True
            ),
        },
        "latency": latency(measured),
        "rows": results,
        "varied_transcripts": sum(
            len({r["text"] for r in results if r["id"] == item["id"]}) > 1
            for item in work
        ),
    }
    suffix = "-diagnostic" if args.limit else ""
    target = args.manifest.parent / f"{args.engine}{suffix}.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "engine": args.engine,
                "accuracy": report["accuracy"],
                "latency": report["latency"],
                "startup": report["startup"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
