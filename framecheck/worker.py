"""A fresh process per case prevents hangs/crashes contaminating later cases.

This is process fault containment, NOT a security sandbox for untrusted code.
"""

import contextlib
import json
import sys
from pathlib import Path

from .adapters import load_adapter


def execute(request, progress=None):
    if progress is None:
        progress = {}
    actual = []
    progress.update(stage="adapter_load", chunk_index=None, actual=actual)
    parser = load_adapter(request["adapter"])
    progress["stage"] = "reset"
    parser.reset()
    for index, chunk in enumerate(request["chunks_hex"]):
        progress.update(stage="feed", chunk_index=index)
        emitted = parser.feed(bytes.fromhex(chunk))
        progress["stage"] = "output_validate"
        if not isinstance(emitted, list) or any(not isinstance(item, dict) for item in emitted):
            raise ValueError("feed() must return a list of JSON objects")
        # Copy each emission at feed time: reusable mutable buffers must not rewrite history.
        snapshot = json.loads(json.dumps(emitted, allow_nan=False))
        if len(actual) + len(snapshot) > 10000:
            raise ValueError("parser emitted more than 10000 messages")
        actual.extend(snapshot)
    return actual


def main():
    response_path = Path(sys.argv[1])
    progress = {"stage": "request", "chunk_index": None, "actual": []}
    try:
        request = json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(sys.stderr):
            actual = execute(request, progress)
        response = {"actual": actual}
    except BaseException as exc:
        trace = exc.__traceback__
        while trace.tb_next is not None:
            trace = trace.tb_next
        code = trace.tb_frame.f_code
        detail = {"stage": progress["stage"], "chunk_index": progress["chunk_index"],
                  "exception_type": type(exc).__name__,
                  "location": {"file": Path(code.co_filename).name,
                               "line": trace.tb_lineno, "function": code.co_name}}
        response = {"error": f"{type(exc).__name__}: {exc}", "error_detail": detail,
                    "actual": progress["actual"]}
    response_path.write_text(json.dumps(response, ensure_ascii=True, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
