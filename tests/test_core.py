import json
import tempfile
import unittest
from pathlib import Path

from framecheck.cases import demo_suite, read_suite, validate_suite
from framecheck.protocol import DemoParser, crc16, encode
from framecheck.runner import first_difference, run_case, run_suite


class ProtocolTests(unittest.TestCase):
    def test_crc_independent_check_vector(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_fixed_wire_vector(self):
        # CRC supplied by Python's independent standard-library binascii implementation.
        import binascii
        body = bytes.fromhex("030110102030")
        wire = bytes.fromhex("aa55") + body + binascii.crc_hqx(body, 0xFFFF).to_bytes(2, "little")
        self.assertEqual(encode(1, 16, bytes.fromhex("102030")), wire)

    def test_valid_parser_obeys_all_fixtures(self):
        for case in demo_suite()["cases"]:
            with self.subTest(case=case["id"]):
                parser = DemoParser()
                emitted = []
                for chunk in case["chunks_hex"]:
                    emitted += parser.feed(bytes.fromhex(chunk))
                self.assertEqual(case["expected"], emitted)

    def test_each_injected_fault_is_detected(self):
        for bug, key in [(1, "bytewise"), (2, "concat"), (3, "bad-crc"), (4, "noise")]:
            case = next(c for c in demo_suite()["cases"] if c["id"] == key)
            parser = DemoParser(bug)
            actual = sum((parser.feed(bytes.fromhex(x)) for x in case["chunks_hex"]), [])
            self.assertNotEqual(actual, case["expected"])

    def test_reset_removes_pending_data(self):
        parser = DemoParser()
        raw = encode(2, 3, b"a")
        parser.feed(raw[:5])
        parser.reset()
        self.assertEqual(parser.feed(raw[5:]), [])
        self.assertEqual(parser.feed(raw), [{"seq": 2, "type": 3, "payload_hex": "61"}])


class SuiteTests(unittest.TestCase):
    def test_seed_reproducibility(self):
        self.assertEqual(demo_suite(42), demo_suite(42))
        self.assertNotEqual(demo_suite(42)["cases"][-1], demo_suite(43)["cases"][-1])

    def test_reject_invalid_suite(self):
        for case in [{"id": "../outside", "chunks_hex": [""], "expected": []},
                     {"id": "bad", "chunks_hex": ["zz"], "expected": []}]:
            with self.assertRaises(ValueError):
                validate_suite({"schema_version": 1, "cases": [case]})
        suite = demo_suite()
        suite["cases"].append(suite["cases"][0])
        with self.assertRaises(ValueError):
            validate_suite(suite)

    def test_first_difference_includes_missing_messages(self):
        self.assertEqual(first_difference([{"a": 1}], []), 0)
        self.assertEqual(first_difference([{"a": 1}], [{"a": 1}, {"a": 2}]), 1)
        self.assertIsNone(first_difference([], []))

    def test_json_types_are_respected(self):
        self.assertEqual(first_difference([{"ok": True}], [{"ok": 1}]), 0)
        self.assertEqual(first_difference([{"nested": [False]}], [{"nested": [0]}]), 0)
        self.assertIsNone(first_difference([{"a": 1, "b": 2}], [{"b": 2, "a": 1.0}]))

    def test_nonfinite_fixture_is_invalid_configuration(self):
        suite = demo_suite()
        suite["cases"][0]["expected"] = [{"value": float("nan")}]
        with self.assertRaisesRegex(ValueError, "finite JSON"):
            validate_suite(suite)


class WorkerTests(unittest.TestCase):
    case = {"id": "x", "title": "x", "category": "custom", "chunks_hex": ["01"], "expected": []}

    def adapter(self, temp, source):
        path = Path(temp)/"adapter.py"
        path.write_text(source, encoding="utf-8")
        return {"kind": "python", "path": str(path)}

    def test_hanging_parser_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = self.adapter(temp, "def create_parser():\n while True: pass\n")
            result = run_case(spec, self.case, .3)
            self.assertEqual(result["status"], "error")
            self.assertIn("超时", result["reason"])

    def test_crashed_parser_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = self.adapter(temp, "import os\ndef create_parser():\n os._exit(7)\n")
            result = run_case(spec, self.case, 3)
            self.assertEqual(result["status"], "error")
            self.assertIn("7", result["reason"])

    def test_invalid_emission_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = self.adapter(temp, "class P:\n def reset(self): pass\n def feed(self,data): return None\ndef create_parser(): return P()\n")
            self.assertEqual(run_case(spec, self.case, 3)["status"], "error")

    def test_stdout_does_not_break_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = self.adapter(temp, "print('debug output')\nclass P:\n def reset(self): pass\n def feed(self,data): print('bytes', data); return []\ndef create_parser(): return P()\n")
            self.assertEqual(run_case(spec, self.case, 3)["status"], "pass")

    def test_adapter_dataclass_and_sibling_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"sibling.py").write_text("VALUE = 7\n", encoding="utf-8")
            spec = self.adapter(temp, "from __future__ import annotations\nfrom dataclasses import dataclass\nfrom sibling import VALUE\n@dataclass\nclass P:\n value: int = VALUE\n def reset(self): pass\n def feed(self,data): return [{'value':self.value}]\ndef create_parser(): return P()\n")
            case = dict(self.case, expected=[{"value": 7}])
            result = run_case(spec, case, 3)
            self.assertEqual(result["status"], "pass", result["reason"])

    def test_save_and_replay_failure_after_fix(self):
        case = next(c for c in demo_suite()["cases"] if c["id"] == "bytewise")
        suite = {"schema_version": 1, "name": "replay", "cases": [case]}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/"bad"
            report = run_suite({"kind": "demo", "bug": 1}, suite, out)
            self.assertEqual(report["summary"]["failed"], 1)
            repro = read_suite(out/report["results"][0]["repro_file"])
            self.assertEqual(repro["cases"][0]["chunks_hex"], case["chunks_hex"])
            fixed = run_suite({"kind": "demo", "bug": 0}, repro, Path(temp)/"fixed")
            self.assertEqual(fixed["summary"]["passed"], 1)

    def test_custom_protocol_schema(self):
        root = Path(__file__).resolve().parent.parent
        suite = read_suite(root/"examples/custom/suite.json")
        spec = {"kind": "python", "path": str(root/"examples/custom/parser.py")}
        with tempfile.TemporaryDirectory() as temp:
            report = run_suite(spec, suite, Path(temp))
            self.assertEqual(report["summary"]["passed"], 3)


if __name__ == "__main__":
    unittest.main()
