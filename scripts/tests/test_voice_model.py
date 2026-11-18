import hashlib
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.voice_model import repack_model


class VoiceModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "model.zip"
        self.target = self.root / "model.tar.gz"

    def archive(self, extra=None, missing=None):
        entries = {
            "am/final.mdl": b"acoustic",
            "conf/model.conf": b"--beam=10.0",
            "conf/mfcc.conf": b"--sample-frequency=16000",
            "graph/HCLr.fst": b"graph",
            "graph/Gr.fst": b"grammar",
            "graph/phones/word_boundary.int": b"phones",
            "README": b"Vietnamese model",
        }
        if missing:
            del entries[missing]
        entries.update(extra or {})
        with zipfile.ZipFile(self.source, "w") as archive:
            for name, data in entries.items():
                archive.writestr(f"vosk-model-small-vn-0.4/{name}", data)
        return hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_browser_layout_and_reproducible_bytes(self):
        checksum = self.archive()
        repack_model(self.source, self.target, checksum)
        self.assertTrue(self.target.is_file(), "browser archive must be produced")
        with tarfile.open(self.target, "r:gz") as archive:
            self.assertEqual(archive.extractfile("model/am/final.mdl").read(), b"acoustic")
            self.assertEqual(archive.extractfile("model/README").read(), b"Vietnamese model")
            self.assertTrue(all(item.name.startswith("model/") for item in archive))
        second = self.root / "second.tar.gz"
        repack_model(self.source, second, checksum)
        self.assertEqual(self.target.read_bytes(), second.read_bytes())

    def test_corrupt_download_does_not_replace_an_existing_model(self):
        self.archive()
        self.target.write_bytes(b"existing model")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            repack_model(self.source, self.target, "0" * 64)
        self.assertEqual(self.target.read_bytes(), b"existing model")

    def test_archive_path_traversal_is_rejected(self):
        checksum = self.archive({"../escaped": b"bad"})
        with self.assertRaisesRegex(ValueError, "path"):
            repack_model(self.source, self.target, checksum)
        self.assertFalse(self.target.exists())

    def test_missing_acoustic_model_is_rejected(self):
        checksum = self.archive(missing="am/final.mdl")
        with self.assertRaisesRegex(ValueError, "Missing"):
            repack_model(self.source, self.target, checksum)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
