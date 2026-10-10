"""CLI results must survive consoles that cannot encode Chinese output."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConsoleEncodingTests(unittest.TestCase):
    def invoke(self, *args):
        environment = os.environ.copy()
        environment.update(PYTHONIOENCODING="ascii:strict", PYTHONUTF8="0")
        return subprocess.run(
            [sys.executable, "-m", "framecheck", *map(str, args)], cwd=ROOT,
            env=environment, capture_output=True, timeout=15)

    def test_successful_export_survives_ascii_console(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "用例.json"
            result = self.invoke("export-suite", "--out", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"\\u7528", result.stdout)
            self.assertEqual(result.stderr, b"")
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["cases"])

    def test_configuration_error_survives_ascii_console(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke("inspect", "--project", Path(directory)/"missing",
                                 "--out", Path(directory)/"reports")
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"\\u914d", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
