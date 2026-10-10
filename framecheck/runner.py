"""Compare observable emissions and preserve exact input chunks on failure."""

import json
import hashlib
import math
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .cases import validate_suite


def same_json(left, right):
    # JSON booleans and numbers are distinct even though Python True == 1.
    if type(left) is not type(right):
        return (type(left) in (int, float) and type(right) in (int, float) and left == right)
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


def first_difference(expected, actual):
    for index, (left, right) in enumerate(zip(expected, actual)):
        if not same_json(left, right):
            return index
    return min(len(expected), len(actual)) if len(expected) != len(actual) else None


def run_case(adapter, case, timeout):
    started = time.perf_counter()
    actual, error = [], None
    with tempfile.TemporaryDirectory(prefix="framecheck-") as tmp:
        response = Path(tmp) / "response.json"
        env = os.environ.copy()
        root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        request = json.dumps({"adapter": adapter, "chunks_hex": case["chunks_hex"]}, ensure_ascii=True)
        try:
            child = subprocess.run([sys.executable, "-m", "framecheck.worker", str(response)],
                                   input=request, text=True, encoding="utf-8", env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            if child.returncode != 0:
                error = f"解析器进程退出，代码 {child.returncode}"
            elif not response.exists():
                error = "解析器未返回结果"
            elif response.stat().st_size > 16 * 1024 * 1024:
                error = "解析器结果超过 16 MiB"
            else:
                data = json.loads(response.read_text(encoding="utf-8"))
                error = data.get("error")
                actual = data.get("actual", [])
        except subprocess.TimeoutExpired:
            error = f"解析器超时（{timeout:g} 秒）"
        except (OSError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    difference = first_difference(case["expected"], actual)
    status = "error" if error else "pass" if difference is None else "fail"
    reason = error or ("输出与预期一致" if status == "pass" else f"第 {difference + 1} 条消息开始不同；预期 {len(case['expected'])} 条，实际 {len(actual)} 条")
    return {"id": case["id"], "title": case["title"], "category": case["category"],
            "status": status, "chunks_hex": case["chunks_hex"],
            "stream_hex": "".join(bytes.fromhex(chunk).hex() for chunk in case["chunks_hex"]),
            "expected": case["expected"], "actual": actual, "reason": reason,
            "first_difference": None if error else difference,
            "elapsed_ms": round((time.perf_counter()-started)*1000, 2), "repro_file": None}


def run_suite(adapter: dict, suite: dict, output_dir: Path, timeout: float = 3) -> dict:
    suite = validate_suite(suite)
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
        raise ValueError("timeout must be finite and in (0, 300] seconds")
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "tool_version": __version__, "run_id": uuid.uuid4().hex[:12],
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "adapter": {"name": adapter.get("name", adapter["kind"]), "kind": adapter["kind"],
                          "fingerprint": adapter.get("fingerprint", {})},
              "suite": {key: suite[key] for key in ("name", "seed", "protocol")},
              "summary": {"passed": 0, "failed": 0, "errors": 0, "total": len(suite["cases"])}, "results": []}
    contract = {key: suite[key] for key in ("schema_version", "name", "seed", "protocol", "cases")}
    report["suite"]["sha256"] = hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
    for case in suite["cases"]:
        result = run_case(adapter, case, timeout)
        report["summary"][{"pass": "passed", "fail": "failed", "error": "errors"}[result["status"]]] += 1
        if result["status"] != "pass":
            rel = f"repros/{case['id']}.json"
            target = output_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            repro = {"schema_version": 1, "name": "失败用例重放", "seed": suite["seed"],
                     "protocol": suite["protocol"], "cases": [case],
                     "observed": {"status": result["status"], "actual": result["actual"], "reason": result["reason"]},
                     "original_adapter": report["adapter"]}
            target.write_text(json.dumps(repro, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
            result["repro_file"] = rel
        report["results"].append(result)
    from .report import write_report
    write_report(report, output_dir)
    return report
