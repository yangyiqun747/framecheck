"""Opt-in, bounded board metadata collection through an isolated optional SDK."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

PROFILES = ("cortex-m", "stm32f1-high-density")
BACKEND = Path(__file__).with_name("board_backend.py")


def validate_request(connect, probe_id, profile, timeout):
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("board-info timeout must be finite and in (0, 60] seconds")
    if connect != bool(probe_id and profile) or (not connect and (probe_id or profile)):
        raise ValueError("读取芯片必须同时指定 --connect、完整 --probe-id 和 --profile")
    if profile is not None and profile not in PROFILES:
        raise ValueError("不支持的芯片读取配置")
    if probe_id is not None and (len(probe_id) > 512 or not probe_id.strip()):
        raise ValueError("下载器 ID 无效")


def run_backend(python, connect, probe_id, profile, timeout):
    executable = Path(python).resolve(strict=True)
    if not executable.is_file():
        raise ValueError("backend Python executable is not a file")
    command = [str(executable), "-I", "-B", "-X", "utf8", str(BACKEND)]
    if connect:
        command += ["--connect", "--probe-id", probe_id, "--profile", profile]
    with tempfile.TemporaryDirectory(prefix="framecheck-board-cli-") as cwd:
        process = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
    if len(process.stdout) > 512 * 1024:
        raise RuntimeError("board metadata response exceeded 512 KiB")
    data = json.loads(process.stdout.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("board metadata response must be an object")
    if process.returncode or data.get("backend_error"):
        raise RuntimeError(data.get("backend_error") or f"board backend exited {process.returncode}")
    return data, process.stderr.decode("utf-8", errors="replace")[-8192:]


def _valid_inventory(value):
    if not isinstance(value, dict) or value.get("status") not in ("ok", "unavailable", "error") or not isinstance(value.get("items"), list):
        return False
    return (isinstance(value.get("provider"), str) and
            isinstance(value.get("truncated", False), bool) and
            all(isinstance(item, dict) for item in value["items"]))


def validate_response(data, connect):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError("invalid board metadata envelope")
    if not _valid_inventory(data.get("probe_inventory")) or not _valid_inventory(data.get("serial_inventory")):
        raise RuntimeError("invalid board inventory")
    chip = data.get("chip")
    if not isinstance(chip, dict) or chip.get("status") not in ("ok", "not_requested", "unsupported", "error"):
        raise RuntimeError("invalid chip metadata")
    if not isinstance(chip.get("target_connected"), bool):
        raise RuntimeError("missing chip connection evidence")
    if not connect and (chip["status"] != "not_requested" or chip["target_connected"]):
        raise RuntimeError("inventory response unexpectedly connected to a target")
    if connect and chip["status"] == "ok" and not chip["target_connected"]:
        raise RuntimeError("chip success is missing a target connection")
    expected = {"target_connection_requested": connect, "serial_opened": False,
                "reset_requested": False, "halt_requested": False, "firmware_read": False,
                "firmware_written": False, "unlock_requested": False}
    actions = data.get("actions")
    if not isinstance(actions, dict) or any(actions.get(k) is not v for k, v in expected.items()):
        raise RuntimeError("invalid board action evidence")


def collect_board_info(out, backend_python=None, connect=False, probe_id=None, profile=None, timeout=10):
    validate_request(connect, probe_id, profile, timeout)
    python = backend_python or sys.executable
    report = {"schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "chip_metadata" if connect else "inventory", "status": "error",
              "is_parser_validation": False, "protocol_rules": None,
              "request": {"connect": connect, "probe_id": probe_id, "profile": profile, "timeout_s": timeout},
              "backend_sha256": hashlib.sha256(BACKEND.read_bytes()).hexdigest(), "suggestions": []}
    try:
        data, diagnostics = run_backend(python, connect, probe_id, profile, timeout)
        validate_response(data, connect)
        report.update({key: data[key] for key in ("probe_inventory", "serial_inventory", "chip", "actions")})
        report["backend_diagnostics"] = diagnostics
        statuses = [data[k]["status"] for k in ("probe_inventory", "serial_inventory")]
        chip_ok = data["chip"]["status"] == ("ok" if connect else "not_requested")
        report["status"] = "ok" if statuses == ["ok", "ok"] and chip_ok and not any(data[k].get("truncated") for k in ("probe_inventory", "serial_inventory")) else "partial" if chip_ok else "error"
        for key in ("probe_inventory", "serial_inventory"):
            if data[key]["status"] == "unavailable":
                report["suggestions"].append(f"{data[key]['provider']} 依赖不可用；选择已有板卡工具 Python，或单独安装可选 board 依赖。")
            elif data[key]["status"] == "error":
                report["suggestions"].append(f"{key} 读取失败，查看诊断；不能据此认定没有设备。")
        if any(data[k].get("truncated") for k in ("probe_inventory", "serial_inventory")):
            report["suggestions"].append("设备列表达到显示上限，报告仅包含部分条目；不能视为完整设备清单。")
        if data["probe_inventory"]["status"] == "ok" and not data["probe_inventory"]["items"]:
            report["suggestions"].append("未发现下载器：检查 USB 数据线、USB 口、供电和驱动，再复查。")
        if len(data["serial_inventory"]["items"]) > 1:
            report["suggestions"].append("发现多个串口；根据板卡接线确认业务串口，不能仅凭端口号自动选择。")
        if data["chip"]["status"] == "unsupported":
            report["suggestions"].append("芯片与所选读取配置不匹配；保留未知状态，根据板上标识和工程选择配置。")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["suggestions"].append("波特率、UART 引脚和接收上限需结合工程；CRC、帧格式与异常恢复仍需独立协议依据或用户确认。")
    report["notice"] = "此报告只识别连接与芯片元信息，不代表串口通信或解析器验收通过。连接调试口可能改变调试寄存器。"
    output = Path(out)
    output.mkdir(parents=True, exist_ok=True)
    (output/"board-info.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    write_markdown(report, output/"board-info.md")
    return report


def _cell(value):
    text = html.escape(str(value if value is not None else "未知"), quote=True).replace("\n", " ").replace("\r", " ")
    for character in ("\\", "|", "`", "[", "]", "*", "_"):
        text = text.replace(character, "\\" + character)
    return text



def write_markdown(report, path):
    lines = ["# FrameCheck 接板信息", "", f"模式：`{report['mode']}`；状态：`{report['status']}`", "", report["notice"], ""]
    if report.get("error"):
        lines += [f"错误：{_cell(report['error'])}", ""]
    for key, title, columns in (
        ("probe_inventory", "下载器", [("unique_id", "完整 ID"), ("vendor", "厂家"), ("product", "名称")]),
        ("serial_inventory", "串口", [("port", "端口"), ("description", "名称"), ("hwid", "硬件标识")]),
    ):
        inventory = report.get(key, {})
        lines += [f"## {title}", "", f"读取状态：`{inventory.get('status', '未完成')}`", ""]
        if inventory.get("error"):
            lines += [_cell(inventory["error"]), ""]
        if inventory.get("items"):
            lines += ["| " + " | ".join(label for _, label in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
            lines += ["| " + " | ".join(_cell(item.get(key)) for key, _ in columns) + " |" for item in inventory["items"]]
            lines.append("")
    chip = report.get("chip", {})
    lines += ["## 芯片信息", "", f"读取状态：`{chip.get('status', '未完成')}`", ""]
    for key in ("profile", "cpuid", "dbg_idcode", "device_id", "flash_kib", "family_hint", "core_state_before", "core_state_after", "error"):
        if key in chip:
            lines.append(f"- {key}: {_cell(chip[key])}")
    lines += ["", "具体料号与封装：未自动确定，请对照板上标识与工程。", "", "## 接入建议", ""]
    lines += [f"- {_cell(text)}" for text in report["suggestions"]]
    lines += ["", "默认仅枚举，不打开串口。显式芯片读取不请求复位、暂停、解锁、固件读取或写入；原始读取地址与数值见 JSON。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
