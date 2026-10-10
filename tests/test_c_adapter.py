"""Integration checks for compiling/loading the C ABI, when a compiler exists."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from framecheck.c_adapter import BuildError, _find_compiler, build_library, load_c_parser
from framecheck.cases import demo_suite


try:
    COMPILER = _find_compiler(os.environ.get("FRAMECHECK_CC"))
except BuildError:
    COMPILER = None
SOURCE = Path(__file__).resolve().parents[1] / "examples" / "c" / "parser.c"


class BuildValidationTests(unittest.TestCase):
    def test_missing_source_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            build_library(Path("nonexistent_parser.c"), Path("unused"))

    def test_invalid_bug_is_rejected(self):
        with self.assertRaises(ValueError):
            build_library(SOURCE, Path("unused"), bug=5)

    def test_missing_explicit_compiler_is_reported(self):
        with self.assertRaises(BuildError):
            build_library(SOURCE, Path("unused"), compiler="framecheck_no_such_compiler_9173")


@unittest.skipUnless(COMPILER, "No C compiler available; set FRAMECHECK_CC to enable C integration tests")
class CAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="framecheck-c-")
        cls.library = build_library(SOURCE, Path(cls.directory.name), compiler=COMPILER)
        cls.parser = load_c_parser(cls.library)

    @classmethod
    def tearDownClass(cls):
        # Windows keeps the loaded DLL locked until process exit. Leave that
        # temporary directory for the OS cleanup if it cannot be removed.
        try:
            cls.directory.cleanup()
        except PermissionError:
            pass

    def setUp(self):
        self.parser.reset()

    def test_golden_crc_vector_and_callback(self):
        # Pinned using Python's independent binascii.crc_hqx reference:
        # len=3, seq=1, type=2, payload=10 20 30, CRC=f41f (little-endian).
        frame = bytes.fromhex("aa550301021020301ff4")
        self.assertEqual(self.parser.feed(frame), [{"seq": 1, "type": 2, "payload_hex": "102030"}])

    def test_bad_crc_is_rejected(self):
        frame = bytes.fromhex("aa550301021020301ef4")
        self.assertEqual(self.parser.feed(frame), [])

    def test_empty_feed(self):
        self.assertEqual(self.parser.feed(b""), [])

    def test_reset_discards_partial_state(self):
        frame = bytes.fromhex("aa550301021020301ff4")
        self.assertEqual(self.parser.feed(frame[:5]), [])
        self.parser.reset()
        self.assertEqual(self.parser.feed(frame[5:]), [])

    def test_full_suite_and_all_known_faults(self):
        suite = demo_suite()
        expected_failure = {1: "bytewise", 2: "concat", 3: "bad-crc", 4: "noise"}
        for bug in range(5):
            with self.subTest(bug=bug):
                library = build_library(SOURCE, Path(self.directory.name), bug=bug, compiler=COMPILER) if bug else self.library
                parser = load_c_parser(library)
                failed = []
                for case in suite["cases"]:
                    parser.reset()
                    actual = []
                    for chunk in case["chunks_hex"]:
                        actual.extend(parser.feed(bytes.fromhex(chunk)))
                    if actual != case["expected"]:
                        failed.append(case["id"])
                if bug == 0:
                    self.assertEqual(failed, [])
                else:
                    self.assertIn(expected_failure[bug], failed)


if __name__ == "__main__":
    unittest.main()
