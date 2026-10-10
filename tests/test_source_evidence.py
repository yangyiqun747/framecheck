import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class SourceEvidenceTests(unittest.TestCase):
    def test_same_size_same_timestamp_edit_ignores_existing_bytecode(self):
        from framecheck.runner import run_case
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            production = base / "production.py"
            production.write_text("VALUE=1\n", encoding="utf-8")
            adapter = base / "adapter.py"
            adapter.write_text("from production import VALUE\nclass P:\n def reset(self): pass\n def feed(self,data): return [{'value':VALUE}]\ndef create_parser(): return P()\n", encoding="utf-8")
            # Deliberately seed valid timestamp caches before the same-size edit.
            py_compile.compile(str(production), doraise=True)
            py_compile.compile(str(adapter), doraise=True)
            stat = production.stat()
            production.write_text("VALUE=2\n", encoding="utf-8")
            os.utime(production, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            case = {"id": "fresh", "title": "fresh", "category": "custom",
                    "chunks_hex": ["01"], "expected": [{"value": 2}]}
            result = run_case({"kind": "python", "path": str(adapter)}, case, 3)
            self.assertEqual(result["status"], "pass", result["reason"])
            self.assertEqual(result["actual"], [{"value": 2}])

    def test_changed_production_dependency_is_recorded_and_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            production = base/"production_module.py"
            production.write_text("VALUE=1\n", encoding="utf-8")
            adapter = base/"adapter.py"
            adapter.write_text("from production_module import VALUE\nclass P:\n def reset(self): pass\n def feed(self,data): return [{'value':VALUE}]\ndef create_parser(): return P()\n", encoding="utf-8")
            suite = base/"suite.json"
            suite.write_text(json.dumps({"schema_version": 1, "cases": [{"id": "value", "chunks_hex": ["01"], "expected": [{"value": 1}]}]}), encoding="utf-8")

            def run(out):
                result = subprocess.run([sys.executable, "-X", "utf8", "-m", "framecheck", "run", "--python", str(adapter),
                    "--suite", str(suite), "--record-source", str(production), "--out", str(out)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15)
                return result, json.loads((out/"report.json").read_text(encoding="utf-8"))

            before_result, before = run(base/"before")
            self.assertEqual(before_result.returncode, 0, before_result.stderr)
            production.write_text("VALUE=2000\n", encoding="utf-8")
            after_result, after = run(base/"after")
            self.assertEqual(after_result.returncode, 1, after_result.stderr)
            self.assertEqual(after["results"][0]["actual"], [{"value": 2000}])
            self.assertEqual(before["adapter"]["fingerprint"]["sha256"], after["adapter"]["fingerprint"]["sha256"])
            self.assertNotEqual(before["adapter"]["fingerprint"]["recorded_sources"], after["adapter"]["fingerprint"]["recorded_sources"])
            self.assertEqual(before["suite"]["sha256"], after["suite"]["sha256"])


if __name__ == "__main__":
    unittest.main()
