"""Prepare the pinned Vietnamese Vosk model for Lichess's browser recognizer."""

import argparse
import gzip
import hashlib
import io
import json
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "vosk-model-small-vn-0.4"
REQUIRED = {
    "am/final.mdl", "conf/model.conf", "conf/mfcc.conf", "graph/HCLr.fst",
    "graph/Gr.fst", "graph/phones/word_boundary.int", "README",
}


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def repack_model(source: Path, destination: Path, expected_sha256: str) -> None:
    if sha256(source) != expected_sha256:
        raise ValueError("Model source SHA256 mismatch; existing output was preserved")
    with zipfile.ZipFile(source) as archive:
        files = {}
        total = 0
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or not path.parts or path.parts[0] != PREFIX):
                raise ValueError(f"Invalid model archive path: {item.filename}")
            if item.is_dir():
                continue
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Invalid symlink path: {item.filename}")
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative in files or relative == ".":
                raise ValueError(f"Duplicate or invalid path: {item.filename}")
            files[relative] = item
            total += item.file_size
        if not REQUIRED.issubset(files):
            raise ValueError(f"Missing model files: {sorted(REQUIRED - files.keys())}")
        if total > 128 * 1024 * 1024:
            raise ValueError("Model archive exceeds the pinned model's size limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            try:
                # Fixed order, timestamps, owner and gzip header give reproducible output.
                with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                        for name, item in sorted(files.items()):
                            data = archive.read(item)
                            info = tarfile.TarInfo(f"model/{name}")
                            info.size = len(data)
                            info.mode = 0o644
                            tar.addfile(info, io.BytesIO(data))
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use an already downloaded official zip")
    parser.add_argument("--lila", type=Path, default=ROOT / "infra/lila-docker/repos/lila")
    args = parser.parse_args()
    lock = json.loads((ROOT / "voice-model-lock.json").read_text(encoding="utf-8"))
    source = args.source or ROOT / ".cache/voice" / f"{PREFIX}.zip"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        partial = source.with_suffix(".download")
        try:
            with urllib.request.urlopen(lock["source_url"], timeout=60) as response:
                with partial.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            if sha256(partial) != lock["source_sha256"]:
                raise ValueError("Downloaded model SHA256 mismatch")
            partial.replace(source)
        finally:
            partial.unlink(missing_ok=True)
    destination = args.lila / "public" / lock["asset_path"]
    repack_model(source, destination, lock["source_sha256"])
    digest = sha256(destination)
    if lock.get("archive_sha256") and digest != lock["archive_sha256"]:
        raise ValueError(f"Repacked model SHA256 mismatch: {digest}")
    print(json.dumps({"model": str(destination), "bytes": destination.stat().st_size,
                      "sha256": digest, "license": lock["license"]}))


if __name__ == "__main__":
    main()
