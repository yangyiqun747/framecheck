"""Verify that guided entry works without adapters, dependencies, or source edits."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class InspectCliTests(unittest.TestCase):
    def invoke(self, args):
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "framecheck", "inspect", *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_project_path_is_sufficient_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base/"工程"
            project.mkdir()
            source = project/"receive.py"
            source.write_text("raise RuntimeError('must not import')\n\nFRAME_HEADER = b'\\xaa\\x55'\n\ndef parse_frame(data):\n    return data\n", encoding="utf-8")
            before = hashlib.sha256(source.read_bytes()).digest()
            out = base/"reports"
            result = self.invoke(["--project", str(project), "--out", str(out)])
            self.assertEqual(result.returncode, 0, result.stderr)
            intake = json.loads((out/"intake.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(intake["files_scanned"], 1)
            self.assertTrue(any(item["path"] == "receive.py" and item["line"] > 0 for item in intake["candidates"]))
            self.assertTrue((out/"intake.md").is_file())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
            self.assertEqual({path.name for path in project.iterdir()}, {"receive.py"})

    def test_nonexistent_project_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.invoke(["--project", str(Path(temporary)/"missing"), "--out", str(Path(temporary)/"out")])
            self.assertEqual(result.returncode, 2)

    def test_focus_cannot_leave_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base/"project"
            project.mkdir()
            (base/"other.c").write_text("void parse_frame(void) {}", encoding="utf-8")
            result = self.invoke(["--project", str(project), "--out", str(base/"out"), "--focus", "../other.c"])
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
