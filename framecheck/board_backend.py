"""Optional board metadata backend. No serial opening, reset or flash operations."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, redirect_stdout
import json
import os
import sys
import tempfile

PROFILES = ("cortex-m", "stm32f1-high-density")


def _text(value):
    return None if value is None else str(value)[:512]


def _load_pyocd():
    import pyocd
    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.session import Session
    return ConnectHelper, Session, pyocd.__version__


def _load_serial_ports():
    import serial
    from serial.tools.list_ports import comports
    return comports, serial.__version__


def probe_inventory():
    probes = []
    try:
        helper, session_type, version = _load_pyocd()
        probes = helper.get_all_connected_probes(blocking=False)
        items = [{"unique_id": _text(p.unique_id), "vendor": _text(p.vendor_name),
                  "product": _text(p.product_name)} for p in probes[:64]]
        result = {"status": "ok", "provider": "pyocd", "version": version,
                  "items": items, "truncated": len(probes) > 64}
        return result, probes, session_type
    except ImportError as exc:
        return {"status": "unavailable", "provider": "pyocd", "items": [], "error": _text(exc)}, [], None
    except Exception as exc:
        return {"status": "error", "provider": "pyocd", "items": [], "error": _text(exc)}, [], None


def serial_inventory():
    try:
        comports, version = _load_serial_ports()
        ports = sorted(comports(), key=lambda p: str(p.device))
        return {"status": "ok", "provider": "pyserial", "version": version,
                "items": [{"port": _text(p.device), "description": _text(p.description),
                           "hwid": _text(p.hwid)} for p in ports[:128]], "truncated": len(ports) > 128}
    except ImportError as exc:
        return {"status": "unavailable", "provider": "pyserial", "items": [], "error": _text(exc)}
    except Exception as exc:
        return {"status": "error", "provider": "pyserial", "items": [], "error": _text(exc)}


@contextmanager
def _restore_cwd():
    # pyOCD Session changes process cwd and does not restore it on close.
    # Restore before TemporaryDirectory cleanup, including constructor failures.
    previous = os.getcwd()
    try:
        yield
    finally:
        os.chdir(previous)


def read_chip(probes, session_type, probe_id, profile):
    result = {"status": "error", "profile": profile, "selected_probe_id": probe_id,
              "exact_part_number": None, "reads": [], "target_connected": False}
    if profile not in PROFILES or not probe_id:
        result["error"] = "an explicit supported profile and full probe ID are required"
        return result
    matches = [p for p in probes if p.unique_id == probe_id]
    if len(matches) != 1 or session_type is None:
        result["error"] = "full probe ID must match exactly one available probe; no automatic selection"
        return result
    try:
        with tempfile.TemporaryDirectory(prefix="framecheck-board-") as project:
            with _restore_cwd(), session_type(matches[0], target_override="cortex_m", frequency=1000000,
                              connect_mode="attach", auto_unlock=False, resume_on_disconnect=False,
                              no_config=True, project_dir=project) as session:
                target = session.target
                result["target_connected"] = True
                result["core_state_before"] = target.get_state().name
                def read(address, width):
                    value = target.read32(address) if width == 32 else target.read16(address)
                    result["reads"].append({"address": f"0x{address:08x}", "width_bits": width, "value": value})
                    return value
                cpuid = read(0xE000ED00, 32)
                result["cpuid"] = f"0x{cpuid:08x}"
                result["core_part_number"] = f"0x{(cpuid >> 4) & 0xfff:03x}"
                result["status"] = "ok"
                if profile == "stm32f1-high-density":
                    if (cpuid >> 24) != 0x41 or ((cpuid >> 4) & 0xfff) != 0xc23:
                        result.update(status="unsupported", error="selected STM32F1 profile requires an Arm Cortex-M3 signature")
                    else:
                        identity = read(0xE0042000, 32)
                        result.update(dbg_idcode=f"0x{identity:08x}", device_id=f"0x{identity & 0xfff:03x}")
                        if identity & 0xfff != 0x414:
                            result.update(status="unsupported", error="device ID does not match the selected high-density profile")
                        else:
                            size = read(0x1FFFF7E0, 16)
                            if size not in (256, 384, 512):
                                result.update(status="unsupported", error="capacity register is inconsistent with the selected profile")
                            else:
                                result.update(flash_kib=size, family_hint="STM32F1 high-density signature; exact part/package is not identified")
                result["core_state_after"] = target.get_state().name
                if result["core_state_after"] != result["core_state_before"]:
                    result.update(status="error", error="core state changed during metadata observation; no corrective reset/resume attempted")
    except Exception as exc:
        result.update(status="error", error=_text(f"{type(exc).__name__}: {exc}"))
    return result


def collect(connect=False, probe_id=None, profile=None):
    # This validation also protects direct callers, before any enumeration.
    if connect != bool(probe_id and profile) or (not connect and (probe_id or profile)):
        raise ValueError("chip reads require --connect, --probe-id and --profile together")
    if profile is not None and profile not in PROFILES:
        raise ValueError("unsupported read profile")
    probe_result, probes, session_type = probe_inventory()
    ports = serial_inventory()
    chip = read_chip(probes, session_type, probe_id, profile) if connect else {"status": "not_requested", "target_connected": False}
    return {"schema_version": 1, "probe_inventory": probe_result, "serial_inventory": ports, "chip": chip,
            "actions": {"target_connection_requested": connect, "serial_opened": False,
                        "reset_requested": False, "halt_requested": False, "firmware_read": False,
                        "firmware_written": False, "unlock_requested": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--probe-id")
    parser.add_argument("--profile", choices=PROFILES)
    args = parser.parse_args(argv)
    try:
        # Keep machine JSON separate from optional SDK diagnostics.
        with redirect_stdout(sys.stderr):
            result = collect(args.connect, args.probe_id, args.profile)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({"schema_version": 1, "backend_error": _text(f"{type(exc).__name__}: {exc}")}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
