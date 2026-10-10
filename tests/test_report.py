"""Regression checks for offline report data safety and edge cases."""

import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from framecheck.report import write_report


class ReportDocument(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.scripts = []
        self.elements = []
        self.data_json = []
        self.reading_data = False
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
        if tag == "script":
            self.scripts.append(attrs)
            self.reading_data = attrs.get("id") == "framecheck-data"

    def handle_endtag(self, tag):
        if tag == "script":
            self.reading_data = False

    def handle_data(self, data):
        if self.reading_data:
            self.data_json.append(data)


class ReportTests(unittest.TestCase):
    def report(self, statuses=("pass", "fail", "error")):
        results = []
        for index, status in enumerate(statuses):
            results.append({
                "id": "case-" + str(index), "title": "输入分块 " + str(index),
                "category": "split", "status": status,
                "chunks_hex": ["AA55", "010203"], "stream_hex": "AA55010203",
                "expected": [{"type": 1, "payload_hex": "02"}],
                "actual": [] if status != "pass" else [{"type": 1, "payload_hex": "02"}],
                "reason": "正常" if status == "pass" else "错误后的第一帧未恢复",
                "first_difference": None if status == "pass" else 0,
                "elapsed_ms": 1.25,
                "repro_file": None if status == "pass" else "repros/case-" + str(index) + ".json",
            })
        return {
            "schema_version": 1, "tool_version": "0.1.0", "run_id": "test-run",
            "generated_at": "2026-10-08T00:00:00Z",
            "adapter": {"name": "测试解析器", "kind": "python", "fingerprint": {"sha256": "abc"}},
            "suite": {"name": "串口回归", "seed": 42, "protocol": {"sync_hex": "AA55"}},
            "summary": {
                "passed": statuses.count("pass"), "failed": statuses.count("fail"),
                "errors": statuses.count("error"), "total": len(statuses),
            },
            "results": results,
        }

    def test_roundtrip_does_not_modify_input_and_preserves_real_results(self):
        report = self.report()
        before = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "report"
            write_report(report, output)
            raw = (output / "report.json").read_text(encoding="utf-8")
            html = (output / "report.html").read_text(encoding="utf-8")
            self.assertEqual(json.loads(raw), report)
            self.assertIn("\n  ", raw)
            self.assertIn("测试解析器", raw)
            document = ReportDocument(html)
            self.assertEqual(json.loads("".join(document.data_json)), report)
            self.assertEqual(report, before)
            self.assertIn('data-filter="pass"', html)
            self.assertIn('data-filter="fail"', html)
            self.assertIn('data-filter="error"', html)

    def test_hostile_strings_remain_json_data_instead_of_executable_markup(self):
        hostile = '</script><script>window.pwned=1</script><img src="x" onerror="window.pwned=1">&\u2028\u2029'
        report = self.report(("fail",))
        report["adapter"]["name"] = hostile
        report["suite"]["protocol"][hostile] = hostile
        report["results"][0].update({
            "title": hostile, "reason": hostile, "chunks_hex": [hostile],
            "expected": [{hostile: hostile}], "actual": [{"message": hostile}],
            "repro_file": "javascript:alert(1)",
            "feedback": {"observation": hostile, "next_steps": [hostile], "limit": hostile,
                         "evidence": {"field_path": [hostile], "actual_preview": hostile}},
        })
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_report(report, output)
            html = (output / "report.html").read_text(encoding="utf-8")
            document = ReportDocument(html)
            self.assertEqual(len(document.scripts), 2)
            self.assertEqual(json.loads("".join(document.data_json)), report)
            self.assertNotIn(hostile, html)
            self.assertNotIn("<img", html)
            self.assertIn(r"\u003c/script\u003e", html)
            self.assertIn(r"\u0026\u2028\u2029", html)
            self.assertFalse(any(name.lower().startswith("on") for _, attrs in document.elements for name in attrs))
            self.assertFalse(any("src" in attrs for _, attrs in document.elements))
            self.assertNotIn(".innerHTML", html)
            self.assertNotIn("insertAdjacentHTML", html)
            self.assertIn("el.textContent = display(text)", html)
            self.assertIn('connect-src \'none\'', html)
            self.assertIn('node("p", "", feedback.observation)', html)
            self.assertIn('node("li", "", step)', html)

    def test_empty_report_and_each_status_are_valid_standalone_documents(self):
        for statuses in [(), ("pass",), ("fail",), ("error",)]:
            with self.subTest(statuses=statuses), tempfile.TemporaryDirectory() as temporary:
                report = self.report(statuses)
                write_report(report, Path(temporary))
                html = (Path(temporary) / "report.html").read_text(encoding="utf-8")
                document = ReportDocument(html)
                self.assertEqual(len(document.scripts), 2)
                self.assertEqual(json.loads("".join(document.data_json))["summary"]["total"], len(statuses))
                self.assertIn("没有可展示的用例", html)
                self.assertIn('charset="utf-8"', html)
                self.assertFalse(any("src" in attrs for _, attrs in document.elements))

    def test_non_json_number_does_not_create_partial_report(self):
        report = self.report()
        report["results"][0]["elapsed_ms"] = float("nan")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            with self.assertRaises(ValueError):
                write_report(report, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
