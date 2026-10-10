"""Bounded, fixture-driven serial exchanges. Dry-run never imports pyserial."""
from __future__ import annotations
import argparse
import hashlib
import json
import html
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 65536

class ConfigError(ValueError):
    pass

class VirtualClock:
    """Deterministic elapsed time for in-memory I/O; never waits in real time."""
    def __init__(self):
        self.now = 0.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += max(0.0, seconds)

class MemoryTransport:
    """Scripted I/O only; this is not a simulated parser or board."""
    def __init__(self, steps, banner=b"", clock=None):
        self.clock = clock if clock is not None else VirtualClock()
        self.steps = list(steps)
        self.buffer = bytearray(banner)
        self.writes = []
        self.closed = False
    @property
    def in_waiting(self):
        # Only bytes already released. Future scripted responses stay in steps.
        return len(self.buffer)
    @property
    def out_waiting(self):
        return 0
    def write(self, data):
        if not self.steps:
            raise RuntimeError("unexpected write")
        expected, response = self.steps.pop(0)
        if data != expected:
            raise RuntimeError("write order/data differs from script")
        self.writes.append(bytes(data))
        self.buffer.extend(response)
        return len(data)
    def read(self, size):
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data
    def close(self):
        self.closed = True


def hex_bytes(value, label):
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a hex string")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ConfigError(f"{label}: invalid hex") from exc


def positive(value, label, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    if not 0 <= value <= 60 or (not allow_zero and value == 0):
        raise ConfigError(f"{label} must be {'0..60' if allow_zero else '>0..60'} seconds")
    return float(value)


def load_inputs(profile_path, suite_path):
    def read(path):
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ConfigError("serial input JSON exceeds 2 MiB")
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise ConfigError(f"invalid JSON: {path}") from exc
        if not isinstance(obj, dict) or obj.get("schema_version") != 1:
            raise ConfigError(f"schema_version 1 object required: {path}")
        return obj, hashlib.sha256(raw).hexdigest()
    profile, profile_hash = read(profile_path)
    suite, suite_hash = read(suite_path)
    validate_inputs(profile, suite)
    return profile, suite, {"profile_sha256": profile_hash, "suite_sha256": suite_hash}


def validate_inputs(profile, suite):
    settings = profile.get("serial")
    if not isinstance(settings, dict):
        raise ConfigError("profile.serial must be an object")
    baud = settings.get("baudrate")
    if isinstance(baud, bool) or not isinstance(baud, int) or not 1 <= baud <= 4000000:
        raise ConfigError("serial.baudrate must be 1..4000000")
    if isinstance(settings.get("bytesize"), bool) or isinstance(settings.get("stopbits"), bool) or settings.get("bytesize") not in (5, 6, 7, 8) or settings.get("parity") not in ("N", "E", "O", "M", "S") or settings.get("stopbits") not in (1, 1.5, 2):
        raise ConfigError("invalid serial bytesize/parity/stopbits")
    for key in ("xonxoff", "rtscts", "dsrdtr"):
        if not isinstance(settings.get(key), bool):
            raise ConfigError(f"serial.{key} must be a boolean")
    for key in ("response_timeout_s", "ready_timeout_s", "quiet_s", "write_timeout_s"):
        positive(profile.get(key), key)
    if profile["quiet_s"] >= profile["response_timeout_s"]:
        raise ConfigError("quiet_s must be smaller than response_timeout_s")
    positive(profile.get("inter_chunk_s"), "inter_chunk_s", allow_zero=True)
    if profile.get("ready_policy") not in ("required", "optional", "skip"):
        raise ConfigError("ready_policy must be required/optional/skip")
    hex_bytes(profile.get("ready_banner_hex"), "ready_banner_hex")
    if profile["ready_policy"] != "skip" and not hex_bytes(profile["ready_banner_hex"], "ready_banner_hex"):
        raise ConfigError("a nonempty ready banner is required unless skipped")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("suite.cases must be a nonempty list")
    if len(cases) > 256:
        raise ConfigError("at most 256 cases per serial suite")
    ids = set()
    total_transactions = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or case["id"] in ids:
            raise ConfigError("case ids must be unique nonempty strings")
        ids.add(case["id"])
        transactions = case.get("transactions")
        if not isinstance(transactions, list) or not transactions:
            raise ConfigError("each case needs transactions")
        total_transactions += len(transactions)
        if total_transactions > 2048:
            raise ConfigError("at most 2048 transactions per serial suite")
        for transaction in transactions:
            if not isinstance(transaction, dict):
                raise ConfigError("transaction must be an object")
            chunks = transaction.get("chunks_hex")
            if not isinstance(chunks, list) or not chunks or any(not hex_bytes(x, "chunks_hex") for x in chunks):
                raise ConfigError("nonempty write chunks required")
            expected = hex_bytes(transaction.get("expected_hex"), "expected_hex")
            if len(expected) > MAX_RESPONSE_BYTES:
                raise ConfigError("expected response exceeds 65536 bytes")
            silence = transaction.get("expect_silence_s")
            if not expected:
                positive(silence, "expect_silence_s")
            elif silence is not None:
                raise ConfigError("expect_silence_s is only valid for an empty expected response")


def memory_for_suite(profile, suite):
    steps = []
    for case in suite["cases"]:
        for tx in case["transactions"]:
            chunks = [bytes.fromhex(x) for x in tx["chunks_hex"]]
            steps.extend((chunk, bytes.fromhex(tx["expected_hex"]) if i == len(chunks)-1 else b"") for i, chunk in enumerate(chunks))
    return MemoryTransport(steps, bytes.fromhex(profile["ready_banner_hex"]) if profile["ready_policy"] != "skip" else b"")


class Session:
    def __init__(self, transport, profile, simulated=False):
        self.transport = transport
        self.profile = profile
        self.pending = b""
        self.events = []
        self.clock = getattr(transport, "clock", time) if simulated else time
        self.start = self.clock.monotonic()
        self.simulated = simulated
    def event(self, kind, **fields):
        self.events.append({"kind": kind, "elapsed_s": round(self.clock.monotonic()-self.start, 6), **fields})
    def read(self, max_wait=None):
        data = self.pending
        self.pending = b""
        source = "prefetched" if data else "transport"
        if not data:
            old_timeout = getattr(self.transport, "timeout", None)
            limit_timeout = max_wait is not None and hasattr(self.transport, "timeout")
            if limit_timeout:
                self.transport.timeout = min(old_timeout, max_wait) if old_timeout is not None else max_wait
            try:
                data = self.transport.read(4096)
            finally:
                if limit_timeout:
                    self.transport.timeout = old_timeout
        if data:
            self.event("read", bytes_hex=data.hex(), source=source)
        else:
            self.clock.sleep(min(0.002, max_wait) if max_wait is not None else 0.002)
        return data
    def preexisting_rx(self):
        # Do not flush: retain stale bytes as evidence, before any request write.
        pending = self.pending
        self.pending = b""
        available = self.transport.in_waiting
        incoming = self.transport.read(min(available, 65536)) if available else b""
        if pending or incoming:
            self.event("preexisting_rx", pending_hex=pending.hex(), transport_hex=incoming.hex(), available_before_read=available)
        return pending + incoming
    def drain_output(self):
        # Bound driver-queue waiting; pySerial flush() itself has no portable timeout.
        deadline = self.clock.monotonic() + self.profile["write_timeout_s"]
        while self.transport.out_waiting:
            remaining = deadline - self.clock.monotonic()
            if remaining <= 0:
                raise TimeoutError("serial output queue did not drain within write_timeout_s")
            self.clock.sleep(min(0.002, remaining))
        self.event("write_queue_empty")
    def ready(self):
        policy = self.profile["ready_policy"]
        banner = bytes.fromhex(self.profile["ready_banner_hex"])
        result = {"policy": policy, "expected_hex": banner.hex(), "received_hex": "", "status": "skipped"}
        if policy == "skip":
            self.event("ready_skipped", reason="explicit profile/CLI choice; no reset requested")
            return result
        if not self.simulated:
            prompt = self.profile.get("ready_prompt", "Port open; waiting for the configured readiness marker.")
            print(f"{prompt} [policy={policy}, timeout={self.profile['ready_timeout_s']}s]", flush=True)
        deadline = self.clock.monotonic() + self.profile["ready_timeout_s"]
        data = bytearray()
        while self.clock.monotonic() < deadline:
            data.extend(self.read(max_wait=deadline-self.clock.monotonic()))
            at = data.find(banner)
            if at >= 0:
                self.pending = bytes(data[at+len(banner):])
                result.update(status="observed", received_hex=bytes(data[:at+len(banner)]).hex())
                self.event("ready_observed")
                return result
            if len(data) > 16384:
                break
        result.update(status="error" if policy == "required" else "not_observed_optional", received_hex=data.hex(), error="ready banner not observed within bounded wait")
        self.event("ready_timeout", policy=policy, received_hex=data.hex())
        return result
    def exchange(self, tx):
        expected = bytes.fromhex(tx["expected_hex"])
        result = {"chunks_hex": tx["chunks_hex"], "expected_hex": expected.hex(), "received_hex": "", "status": "error"}
        data = bytearray()
        event_start = len(self.events)
        try:
            stale = self.preexisting_rx()
            if stale:
                result.update(status="fail", failure="unsolicited bytes present before request; response ownership unknown", preexisting_rx_hex=stale.hex())
                result["events"] = self.events[event_start:]
                return result
            chunks = [bytes.fromhex(x) for x in tx["chunks_hex"]]
            for index, chunk in enumerate(chunks):
                written = self.transport.write(chunk)
                self.event("write", chunk_index=index, bytes_hex=chunk.hex(), written=written)
                if written != len(chunk):
                    raise IOError("incomplete write")
                self.drain_output()
                if index < len(chunks)-1:
                    self.clock.sleep(self.profile["inter_chunk_s"])
            if not expected:
                silence = tx["expect_silence_s"]
                result["expect_silence_s"] = silence
                deadline = self.clock.monotonic() + silence
                while self.clock.monotonic() < deadline:
                    data.extend(self.read(max_wait=deadline-self.clock.monotonic()))
                    if data:
                        result.update(status="fail", failure="unexpected bytes during required silence window")
                        self.event("unexpected_response", received_hex=data.hex())
                        break
                else:
                    result["status"] = "pass"
                    self.event("silence_observed", duration_s=silence)
                result["received_hex"] = data.hex()
                result["events"] = self.events[event_start:]
                return result
            deadline = self.clock.monotonic() + self.profile["response_timeout_s"]
            last_rx_at = None
            quiet_complete = False
            while self.clock.monotonic() < deadline:
                remaining = deadline-self.clock.monotonic()
                if last_rx_at is not None and len(data) >= len(expected):
                    remaining = min(remaining, max(0.0, last_rx_at+self.profile["quiet_s"]-self.clock.monotonic()))
                received = self.read(max_wait=remaining)
                now = self.clock.monotonic()
                if received:
                    data.extend(received)
                    last_rx_at = now
                    if len(data) > 65536:
                        break
                if last_rx_at is not None and len(data) >= len(expected) and now >= last_rx_at+self.profile["quiet_s"] and now <= deadline:
                    quiet_complete = True
                    self.event("quiet_observed", quiet_s=self.profile["quiet_s"])
                    break
            if len(data) < len(expected):
                result["error"] = "response timeout: incomplete or absent response"
                self.event("response_timeout", received_hex=data.hex())
            elif bytes(data) != expected:
                result.update(status="fail", failure="response byte mismatch")
                self.event("mismatch", expected_hex=expected.hex(), received_hex=data.hex())
            elif not quiet_complete:
                result["error"] = "response deadline reached before required quiet window completed"
                self.event("quiet_timeout", quiet_s=self.profile["quiet_s"], received_hex=data.hex())
            else:
                result["status"] = "pass"
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            self.event("io_error", detail=result["error"])
        result["received_hex"] = data.hex()
        result["events"] = self.events[event_start:]
        return result


def run_suite(transport, profile, suite, fingerprints, mode, port=None):
    if mode not in ("dry-run", "live"):
        raise ConfigError("serial mode must be dry-run or live")
    validate_inputs(profile, suite)
    session = Session(transport, profile, simulated=mode == "dry-run")
    report = {"schema_version": 1, "mode": mode, "is_board_validation": mode == "live", "scope": "ordered request/response checks for the supplied fixtures; not a stress or completeness proof", "started_utc": datetime.now(timezone.utc).isoformat(), "port": port, "fingerprints": fingerprints, "profile": profile, "cases": []}
    try:
        report["ready"] = session.ready()
    except Exception as exc:
        report["ready"] = {"status": "error", "policy": profile["ready_policy"], "error": f"{type(exc).__name__}: {exc}"}
        session.event("ready_io_error", detail=report["ready"]["error"])
    stopped = report["ready"]["status"] == "error"
    for case in suite["cases"]:
        item = {"id": case["id"], "name": case.get("name", case["id"]), "transactions": [], "status": "skipped"}
        if not stopped:
            for tx in case["transactions"]:
                result = session.exchange(tx)
                item["transactions"].append(result)
                if result["status"] != "pass":
                    stopped = True
                    break
            item["status"] = "error" if any(t["status"] == "error" for t in item["transactions"]) else "fail" if any(t["status"] == "fail" for t in item["transactions"]) else "pass"
        else:
            item["skip_reason"] = "earlier readiness/exchange error or mismatch; stop to avoid cascading failures"
        report["cases"].append(item)
    report["events"] = session.events
    report["counts"] = {state: sum(c["status"] == state for c in report["cases"]) for state in ("pass", "fail", "error", "skipped")}
    ok = not stopped and report["counts"]["pass"] == len(suite["cases"])
    report["verdict"] = ("self_check_passed" if ok else "self_check_failed") if mode == "dry-run" else ("board_cases_passed" if ok else "board_cases_not_passed")
    if mode == "dry-run":
        report["notice"] = "Runner fixture I/O self-check only. No pyserial import, port enumeration, board communication, parser or firmware validation."
    return report, 0 if ok else 1


def open_live(profile, port):
    try:
        import serial
    except ImportError as exc:
        raise ConfigError("pyserial unavailable; use a trusted Python with the optional serial extra (dry-run needs no dependency)") from exc
    settings = profile["serial"]
    transport = serial.Serial(port=None, baudrate=settings["baudrate"], bytesize=settings["bytesize"], parity=settings["parity"], stopbits=settings["stopbits"], timeout=0.05, write_timeout=profile["write_timeout_s"], xonxoff=settings["xonxoff"], rtscts=settings["rtscts"], dsrdtr=settings["dsrdtr"])
    transport.dtr = False
    transport.rts = False
    transport.port = port
    try:
        transport.open()
    except Exception:
        transport.close()
        raise
    return transport


def _markdown(value):
    text = html.escape(str(value), quote=True).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "|", "`", "[", "]", "*", "_"):
        text = text.replace(char, "\\" + char)
    return text


def save_report(report, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Serial exchange result", "", f"Mode: **{report['mode']}**; verdict: **{report['verdict']}**", "", report.get("notice", report["scope"]), "", f"Ready: `{report['ready']['status']}`", "", "| Case | Result |", "| --- | --- |"]
    lines.extend(f"| {_markdown(c['id'])} | {c['status']} |" for c in report["cases"])
    lines.extend(["", "Exact requested chunks, received bytes, bounded timeout/mismatch events and profile/suite SHA256 are in report.json.", ""])
    (out/"report.md").write_text("\n".join(lines), encoding="utf-8")


def add_arguments(parser):
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="scripted in-memory runner self-check; never board validation")
    mode.add_argument("--live", action="store_true", help="explicitly open --port")
    parser.add_argument("--port")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ready-policy", choices=("required", "optional", "skip"), help="explicit bounded handshake policy; never resets board")


def execute(args):
    if args.live and (not args.port or not args.port.strip()):
        print("--live requires an explicit --port", file=sys.stderr)
        return 2
    if args.dry_run and args.port:
        print("--port is only valid with --live", file=sys.stderr)
        return 2
    transport = None
    try:
        profile, suite, fingerprints = load_inputs(args.profile, args.suite)
        if args.ready_policy:
            profile = dict(profile, ready_policy=args.ready_policy)
        validate_inputs(profile, suite)  # Validate effective readiness override too.
        output = Path(args.out)
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise ConfigError("output directory must be empty; preserve earlier reports")
        fingerprints["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        fingerprints["effective_profile_sha256"] = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        try:
            transport = memory_for_suite(profile, suite) if args.dry_run else open_live(profile, args.port)
        except ConfigError:
            raise
        except Exception as exc:
            report = {"schema_version": 1, "mode": "live", "is_board_validation": False,
                      "scope": "live opening failed; no board case validated", "verdict": "board_cases_not_passed",
                      "started_utc": datetime.now(timezone.utc).isoformat(), "port": args.port,
                      "profile": profile, "fingerprints": fingerprints,
                      "ready": {"status": "error", "error": f"open failed: {type(exc).__name__}: {exc}"},
                      "cases": [{"id": case["id"], "status": "skipped", "transactions": [], "skip_reason": "port open failed"} for case in suite["cases"]],
                      "counts": {"pass": 0, "fail": 0, "error": 0, "skipped": len(suite["cases"])},
                      "events": [{"kind": "open_error", "detail": str(exc)}]}
            save_report(report, args.out)
            print(f"board_cases_not_passed: port open error -> {args.out}")
            return 1
        report, code = run_suite(transport, profile, suite, fingerprints, "dry-run" if args.dry_run else "live", args.port)
        try:
            transport.close()
        except Exception as exc:
            code = 1
            report["close_error"] = f"{type(exc).__name__}: {exc}"
            report["verdict"] = "self_check_failed" if args.dry_run else "board_cases_not_passed"
        transport = None
        save_report(report, args.out)
        print(f"{report['verdict']}: {report['counts']} -> {args.out}")
        return code
    except (ConfigError, OSError) as exc:
        print(f"preparation error: {exc}", file=sys.stderr)
        return 2
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return execute(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
