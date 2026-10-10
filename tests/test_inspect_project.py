import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from framecheck.inspect_project import _is_link, inspect_project


class InspectProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "机器人项目"
        self.project.mkdir()
        self.output = self.base / "intake"
        self.add("src/串口协议.c", """#include "protocol.h"
#define FRAME_HEADER 0xAA55
#define MAX_PAYLOAD_LEN 64
uint16_t protocol_crc16(const uint8_t *p, size_t n) {
    return calculate_ccitt(p, n);
}
void uart_protocol_feed(const uint8_t *p, size_t n) {
    parser_process(p, n);
}
size_t encode_message(uint8_t *out) {
    return 7;
}
""")
        self.add("src/protocol.h", "void uart_protocol_feed(const uint8_t *p, size_t n);\n")
        self.add("tests/test_protocol.c", """// golden known-good frame
const uint8_t sample[] = {0xAA, 0x55, 0x00, 0x01, 0x10, 0xAB, 0xCD};
assert(expected.seq == 1);
""")
        self.add("docs/协议.md", "帧格式示例：AA 55 00 01 10 AB CD\nCRC 覆盖范围仍需确认。\n")
        self.add("CMakeLists.txt", "project(robot)\nadd_library(protocol src/串口协议.c)\n")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_finds_real_entry_and_independent_evidence_with_exact_line(self):
        report = inspect_project(self.project, self.output)
        categories = {item["category"] for item in report["candidates"]}
        self.assertEqual(categories, {"entry", "framing", "checksum", "encoder", "reference", "build"})
        entry = next(item for item in report["candidates"]
                     if item.get("symbol") == "uart_protocol_feed" and item["path"].endswith(".c"))
        self.assertEqual(entry["line"], 7)
        self.assertIn("void uart_protocol_feed", entry["excerpt"])
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(json.loads((self.output / "intake.json").read_text(encoding="utf-8")), report)
        markdown = (self.output / "intake.md").read_text(encoding="utf-8")
        self.assertIn("src/串口协议.c:7", markdown)
        self.assertIn("仍需确认", markdown)
        self.assertIn("可能包含误报", markdown)
        self.assertIn("模型上下文", markdown)

    def test_excludes_vendor_secret_binary_and_never_executes_python(self):
        self.add("Drivers/STM32_HAL/uart.c", "void HAL_UART_RxCpltCallback() {}\n")
        self.add("ThirdParty/crc.c", "int vendor_crc16() { return 0; }\n")
        self.add(".git/crc.c", "int git_crc16() { return 0; }\n")
        self.add(".env", "TOKEN=do-not-read\nvoid secret_parser() {}\n")
        self.add("private.key", "void private_parser() {}\n")
        self.add("secrets.json", '{"token":"do-not-read"}')
        self.add("data.dat", "void binary_parser() {}\n")
        (self.project / "binary.c").write_bytes(b"\x00void binary_parser() {}")
        sentinel = self.base / "was_executed.txt"
        self.add("src/decoder.py", f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
                 "def decode_packet(data):\n    return []\n")
        report = inspect_project(self.project, self.output)
        paths = {item["path"] for item in report["candidates"]}
        self.assertIn("src/decoder.py", paths)
        self.assertFalse(any(path.startswith(("Drivers/", "ThirdParty/", ".git/")) for path in paths))
        self.assertFalse(sentinel.exists())
        self.assertEqual(report["exclusions"]["vendor_or_build_directory"], 2)
        self.assertEqual(report["exclusions"]["binary_content"], 1)
        self.assertNotIn("do-not-read", (self.output / "intake.md").read_text(encoding="utf-8"))

    def test_focus_is_scoped_and_rejects_escapes_missing_excluded_and_root_output(self):
        report = inspect_project(self.project, self.output, ["src/串口协议.c"])
        self.assertEqual(report["files_scanned"], 1)
        self.assertEqual({item["path"] for item in report["candidates"]}, {"src/串口协议.c"})
        for focus in ["../outside", "src/../../outside", "C:\\Windows", "/etc", "missing.c"]:
            with self.subTest(focus=focus), self.assertRaises(ValueError):
                inspect_project(self.project, self.output, [focus])
        self.add("Drivers/crc.c", "int crc16() {}\n")
        self.add(".env", "SECRET=yes")
        for focus in ["Drivers/crc.c", ".env"]:
            with self.subTest(focus=focus), self.assertRaisesRegex(ValueError, "focus is excluded"):
                inspect_project(self.project, self.output, [focus])
        with self.assertRaisesRegex(ValueError, "not the project root"):
            inspect_project(self.project, self.project)
        self.assertFalse((self.project / "intake.md").exists())

    def test_internal_output_is_excluded_and_repeated_scan_is_stable(self):
        output = self.project / "analysis-result"
        first = inspect_project(self.project, output)
        self.add("analysis-result/another_decode.py", "def decode_message(data): return []\n")
        second = inspect_project(self.project, output)
        self.assertEqual(first, second)
        self.assertEqual(second["exclusions"]["scanner_output"], 1)
        self.assertFalse(any("analysis-result" in item["path"] for item in second["candidates"]))

    def test_gb18030_and_limits_are_explicit(self):
        cn = self.project / "docs" / "旧协议.txt"
        cn.write_bytes("协议帧格式示例 AA 55 01 02\n".encode("gb18030"))
        self.add("oversize.c", "void parse_frame() {}\n" * 30)
        with patch("framecheck.inspect_project.MAX_FILE_BYTES", 400):
            report = inspect_project(self.project, self.output)
        self.assertEqual(report["exclusions"]["file_too_large"], 1)
        self.assertIn("docs/旧协议.txt", {item["path"] for item in report["candidates"]})
        with patch("framecheck.inspect_project.MAX_FILES", 1):
            limited = inspect_project(self.project, self.output)
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["files_scanned"], 1)
        self.assertEqual(limited["exclusions"]["file_limit"], 1)

    def test_symlink_files_dirs_and_focused_links_are_not_followed(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "escaped.c").write_text("void parse_escaped() {}", encoding="utf-8")
        try:
            os.symlink(outside, self.project / "linked", target_is_directory=True)
            os.symlink(outside / "escaped.c", self.project / "linked.c")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create symlinks: {exc}")
        report = inspect_project(self.project, self.output)
        self.assertEqual(report["exclusions"]["symlink_or_junction"], 2)
        self.assertFalse(any("linked" in item["path"] for item in report["candidates"]))
        for focus in ["linked", "linked.c", "linked/escaped.c"]:
            with self.subTest(focus=focus), self.assertRaisesRegex(ValueError, "symlink or junction"):
                inspect_project(self.project, self.output, [focus])

    def test_junction_and_symlink_metadata_detection_without_host_privilege(self):
        regular_dir = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        junction = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        symlink = SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        for info, expected in [(regular_dir, False), (junction, True), (symlink, True)]:
            with self.subTest(info=info), patch.object(Path, "lstat", return_value=info):
                self.assertEqual(_is_link(self.project), expected)

    def test_candidate_excerpt_and_total_byte_bounds(self):
        self.add("src/lots.c", "\n".join(f"void parse_frame_{i}() {{ /* {'X' * 600} */ }}" for i in range(100)))
        report = inspect_project(self.project, self.output)
        self.assertLessEqual(len(report["candidates"]), 60)
        self.assertTrue(all(len(item["excerpt"]) <= 540 for item in report["candidates"]))
        self.assertLessEqual(sum(item["path"] == "src/lots.c" for item in report["candidates"]), 8)
        with patch("framecheck.inspect_project.MAX_TOTAL_BYTES", 12):
            limited = inspect_project(self.project, self.output)
        self.assertTrue(limited["truncated"])
        self.assertLessEqual(limited["bytes_scanned"], 12)
        self.assertEqual(limited["exclusions"]["total_byte_limit"], 1)
        (self.project / "000.c").write_bytes(b"\x00abc")
        with patch("framecheck.inspect_project.MAX_TOTAL_BYTES", 8):
            binary_limited = inspect_project(self.project, self.output)
        self.assertEqual(binary_limited["bytes_scanned"], 4)
        self.assertTrue(binary_limited["truncated"])
        self.assertEqual(binary_limited["exclusions"]["binary_content"], 1)
        with patch("framecheck.inspect_project.MAX_FILES", 1):
            binary_file_limited = inspect_project(self.project, self.output)
        self.assertEqual(binary_file_limited["files_considered"], 1)
        self.assertEqual(binary_file_limited["files_scanned"], 0)
        self.assertTrue(binary_file_limited["truncated"])

    def test_uart_receive_events_and_inert_markdown_source(self):
        self.add("src/events.c", """void on_uart_data(const uint8_t *data, size_t n) {
    // ![example](https://example.com/image.png) [link](https://example.com) ```
}
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t size) {
    // receive callback
}
void unrelated() { HAL_UART_Init(huart); }
""")
        report = inspect_project(self.project, self.output)
        symbols = {item.get("symbol") for item in report["candidates"] if item["path"] == "src/events.c"}
        self.assertIn("on_uart_data", symbols)
        self.assertIn("HAL_UARTEx_RxEventCallback", symbols)
        self.assertNotIn("HAL_UART_Init", symbols)
        markdown = (self.output / "intake.md").read_text(encoding="utf-8")
        self.assertIn("````text\n", markdown)
        self.assertIn("![example](https://example.com/image.png)", markdown)

    def test_existing_linked_report_file_is_rejected_without_overwrite(self):
        # Exercise equivalent lexical/canonical paths (also seen with Windows 8.3 names).
        alias = self.base / "path-alias"
        alias.mkdir()
        self.output = alias / ".." / self.output.name
        self.output.mkdir()
        target = self.output.resolve() / "intake.md"
        target.write_text("keep original", encoding="utf-8")
        original_is_link = _is_link
        with patch("framecheck.inspect_project._is_link", side_effect=lambda path:
                   path == target or original_is_link(path)):
            with self.assertRaisesRegex(ValueError, "regular unlinked file"):
                inspect_project(self.project, self.output)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep original")
        self.assertFalse((self.output / "intake.json").exists())
        target.unlink()
        source = self.project / "README.md"
        source.write_text("keep source", encoding="utf-8")
        try:
            os.link(source, target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"host cannot create hardlinks: {exc}")
        with self.assertRaisesRegex(ValueError, "regular unlinked file"):
            inspect_project(self.project, self.output)
        self.assertEqual(source.read_text(encoding="utf-8"), "keep source")

    def test_packaged_c_example_keeps_function_definitions_above_hex_noise(self):
        package = Path(__file__).resolve().parents[1]
        report = inspect_project(package, self.output, ["examples/c"])
        definitions = {(item["path"], item.get("symbol")) for item in report["candidates"]}
        self.assertIn(("examples/c/parser.c", "fc_feed"), definitions)
        self.assertIn(("examples/c/parser.c", "crc16"), definitions)
        feed = next(item for item in report["candidates"] if item.get("symbol") == "fc_feed" and
                    item["path"] == "examples/c/parser.c")
        self.assertGreaterEqual(feed["score"], 85)

    def test_protocol_document_hex_line_need_not_repeat_protocol_keyword(self):
        self.add("protocol.md", "# 通信说明\n长度规则已经确认。\n"
                 "已经独立确认的消息：B5 62 02 07 41 42 06\n")
        report = inspect_project(self.project, self.output, ["protocol.md"])
        reference = next(item for item in report["candidates"] if item["category"] == "reference")
        self.assertEqual(reference["line"], 3)
        self.assertIn("B5 62", reference["excerpt"])

    def test_stm32_application_driver_subtrees_survive_sdk_exclusion(self):
        app = "project/Drivers/SYSTEM/usart/usart.c"
        self.add(app, """#define USART_REC_LEN 200
uint16_t USART_RX_STA = 0;
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    USART_RX_STA++;
}
""")
        self.add("project/Drivers/BSP/serial.c", "void on_uart_data(const uint8_t *data, size_t n) {}\n")
        self.add("project/Drivers/BOARD/serial.c", "void decode_packet(const uint8_t *data) {}\n")
        sdk = "project/Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c"
        self.add(sdk, "void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {}\n")
        self.add("project/Drivers/CMSIS/parser.h", "void decode_vendor_packet(void);\n")
        self.add("project/Drivers/unknown/parser.c", "void decode_unknown_packet(void) {}\n")
        self.add("project/Drivers/SYSTEM/.env", "void decode_secret_packet() {}\n")
        config = "project/User/stm32f1xx_hal_conf.h"
        self.add(config, "#define ETH_MAX_PACKET_SIZE 1524\n")
        report = inspect_project(self.project, self.output, ["project"])
        paths = {item["path"] for item in report["candidates"]}
        self.assertIn(app, paths)
        self.assertIn("project/Drivers/BSP/serial.c", paths)
        self.assertIn("project/Drivers/BOARD/serial.c", paths)
        self.assertNotIn(sdk, paths)
        self.assertNotIn(config, paths)
        self.assertFalse(any("unknown" in path or "CMSIS" in path for path in paths))
        self.assertEqual(report["exclusions"]["sdk_configuration"], 1)
        app_evidence = [item for item in report["candidates"] if item["path"] == app]
        self.assertIn(("entry", 3), {(item["category"], item["line"]) for item in app_evidence})
        self.assertIn(("framing", 1), {(item["category"], item["line"]) for item in app_evidence})
        focused = inspect_project(self.project, self.output, ["project/Drivers/SYSTEM"])
        self.assertEqual({item["path"] for item in focused["candidates"]}, {app})
        for focus in ["project/Drivers/STM32F1xx_HAL_Driver", "project/Drivers/unknown", "project/Drivers/SYSTEM/.env"]:
            with self.subTest(focus=focus), self.assertRaisesRegex(ValueError, "focus is excluded"):
                inspect_project(self.project, self.output, [focus])


if __name__ == "__main__":
    unittest.main()
