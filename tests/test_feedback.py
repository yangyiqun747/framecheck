"""Project-independent failure observations and real worker error evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from framecheck.feedback import comparison_feedback, error_feedback
from framecheck.runner import run_case, run_suite


class ComparisonFeedbackTests(unittest.TestCase):
    def test_arbitrary_nested_path_and_type_difference(self):
        expected = [{"轴/状态[]": [{"": True}]}]
        actual = [{"轴/状态[]": [{"": 1}]}]
        before = copy.deepcopy((expected, actual))
        feedback = comparison_feedback(expected, actual)
        self.assertEqual(feedback["code"], "type_mismatch")
        self.assertEqual(feedback["evidence"]["field_path"], ["轴/状态[]", 0, ""])
        self.assertEqual(feedback["evidence"]["expected_type"], "boolean")
        self.assertEqual(feedback["evidence"]["actual_type"], "number")
        self.assertEqual((expected, actual), before)

    def test_absence_is_distinct_from_null(self):
        for expected, actual, code, path, expected_present, actual_present in [
            ([{"x": None}], [{}], "missing_field", ["x"], True, False),
            ([{}], [{"x": None}], "unexpected_field", ["x"], False, True),
            ([{"x": [0, None]}], [{"x": [0]}], "missing_item", ["x", 1], True, False),
            ([{"x": []}], [{"x": [None]}], "unexpected_item", ["x", 0], False, True),
            ([{}], [], "missing_message", [], True, False),
            ([], [{}], "unexpected_message", [], False, True),
        ]:
            with self.subTest(code=code):
                feedback = comparison_feedback(expected, actual)
                evidence = feedback["evidence"]
                self.assertEqual(feedback["code"], code)
                self.assertEqual(evidence["field_path"], path)
                self.assertEqual(evidence["expected_present"], expected_present)
                self.assertEqual(evidence["actual_present"], actual_present)

    def test_numeric_equivalence_and_object_order_remain_compatible(self):
        self.assertIsNone(comparison_feedback([{"a": 1, "b": [2]}], [{"b": [2.0], "a": 1.0}]))

    def test_first_disagreement_is_stable_and_preview_is_bounded(self):
        feedback = comparison_feedback([{}, {"z": "x" * 100000, "a": 7}], [{}, {"z": "y", "a": 8}])
        self.assertEqual(feedback["code"], "value_mismatch")
        self.assertEqual(feedback["evidence"]["message_index"], 1)
        self.assertEqual(feedback["evidence"]["field_path"], ["z"])
        self.assertLessEqual(len(feedback["evidence"]["expected_preview"]), 181)
        self.assertIn("不能据此确定", feedback["limit"])

    def test_container_type_difference_does_not_copy_large_values(self):
        feedback = comparison_feedback([{"x": list(range(10000))}], [{"x": {}}])
        self.assertEqual(feedback["code"], "type_mismatch")
        self.assertLess(len(json.dumps(feedback, ensure_ascii=False)), 1000)

    def test_malformed_error_detail_cannot_override_incomplete_status(self):
        feedback = error_feedback("worker_response", "bad", {"stage": [], "chunk_index": True,
                                  "location": {"file": "x", "line": "1"}, "actual_complete": True})
        self.assertEqual(feedback["evidence"], {"stage": "unknown", "chunk_index": None,
                                               "actual_complete": False})


class ExecutionFeedbackTests(unittest.TestCase):
    case = {"id": "feedback", "title": "独立协议", "category": "custom",
            "chunks_hex": ["01", "02"], "expected": [{"value": 1}]}

    def run_source(self, source, timeout=3):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "user_parser.py"
            path.write_text(source, encoding="utf-8")
            return run_case({"kind": "python", "path": str(path)}, self.case, timeout)

    def test_feed_exception_preserves_partial_output_and_location(self):
        result = self.run_source("class P:\n def reset(self): pass\n def feed(self,data):\n  if data == b'\\x02': raise RuntimeError('specific failure')\n  return [{'value':1}]\ndef create_parser(): return P()\n")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["first_difference"])
        self.assertEqual(result["actual"], self.case["expected"])
        evidence = result["feedback"]["evidence"]
        self.assertEqual(evidence["stage"], "feed")
        self.assertEqual(evidence["chunk_index"], 1)
        self.assertFalse(evidence["actual_complete"])
        self.assertEqual(evidence["exception_type"], "RuntimeError")
        self.assertEqual(evidence["location"], {"file": "user_parser.py", "line": 4, "function": "feed"})

    def test_reset_and_load_exceptions_have_no_chunk(self):
        for source, stage in [
            ("def create_parser(): raise ImportError('dependency missing')\n", "adapter_load"),
            ("class P:\n def reset(self): raise ValueError('reset failed')\n def feed(self,data): return []\ndef create_parser(): return P()\n", "reset"),
        ]:
            with self.subTest(stage=stage):
                result = self.run_source(source)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["feedback"]["evidence"]["stage"], stage)
                self.assertIsNone(result["feedback"]["evidence"]["chunk_index"])

    def test_invalid_and_nonfinite_output_are_format_errors(self):
        for output in ("None", "[{'x': float('nan')}]", "[{'x': object()}]"):
            with self.subTest(output=output):
                result = self.run_source("class P:\n def reset(self): pass\n def feed(self,data): return " + output + "\ndef create_parser(): return P()\n")
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["feedback"]["evidence"]["stage"], "output_validate")
                self.assertEqual(result["feedback"]["evidence"]["chunk_index"], 0)

    def test_timeout_and_crash_do_not_guess_internal_position(self):
        for source, code in [("def create_parser():\n while True: pass\n", "timeout"),
                             ("import os\ndef create_parser(): os._exit(7)\n", "process_exit")]:
            with self.subTest(code=code):
                result = self.run_source(source, timeout=.5 if code == "timeout" else 3)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["feedback"]["code"], code)
                self.assertEqual(result["feedback"]["evidence"]["stage"], "unknown")
                self.assertIsNone(result["feedback"]["evidence"]["chunk_index"])

    def test_malformed_worker_response_remains_a_reportable_error(self):
        for response in [[], {"actual": "not a list"}, {"error": ""}, {},
                         {"actual": [{"x": float("nan")}]},
                         {"error": "bad", "actual": [], "error_detail": []}]:
            with self.subTest(response=response):
                def fake_worker(command, **kwargs):
                    from subprocess import CompletedProcess
                    Path(command[-1]).write_text(json.dumps(response), encoding="utf-8")
                    return CompletedProcess(command, 0)
                with patch("framecheck.runner.subprocess.run", side_effect=fake_worker):
                    result = run_case({"kind": "demo"}, self.case, 3)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["feedback"]["evidence"]["stage"], "unknown")
                self.assertFalse(result["feedback"]["evidence"]["actual_complete"])

    def test_repro_keeps_feedback_and_replay_recomputes_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "parser.py"
            path.write_text("class P:\n def reset(self): pass\n def feed(self,data): return [{'custom':0}]\ndef create_parser(): return P()\n", encoding="utf-8")
            suite = {"schema_version": 1, "cases": [dict(self.case, expected=[{"custom": 1}, {"custom": 1}])]}
            adapter = {"kind": "python", "path": str(path)}
            output = Path(temporary) / "bad"
            report = run_suite(adapter, suite, output)
            result = report["results"][0]
            repro = json.loads((output / result["repro_file"]).read_text(encoding="utf-8"))
            self.assertEqual(repro["observed"]["feedback"], result["feedback"])
            self.assertEqual(repro["cases"][0]["chunks_hex"], self.case["chunks_hex"])
            path.write_text(path.read_text(encoding="utf-8").replace("'custom':0", "'custom':1"), encoding="utf-8")
            fixed = run_suite(adapter, repro, Path(temporary) / "fixed")
            self.assertEqual(fixed["summary"]["passed"], 1)
            self.assertIsNone(fixed["results"][0]["feedback"])


if __name__ == "__main__":
    unittest.main()
