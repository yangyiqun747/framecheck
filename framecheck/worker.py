"""A fresh process per case prevents hangs/crashes contaminating later cases.

This is process fault containment, NOT a security sandbox for untrusted code.
"""

import contextlib
import json
import sys
from pathlib import Path

from .adapters import load_adapter


def execute(request):
    parser = load_adapter(request["adapter"])
    parser.reset()
    actual = []
    for chunk in request["chunks_hex"]:
        emitted = parser.feed(bytes.fromhex(chunk))
        if not isinstance(emitted, list) or any(not isinstance(item, dict) for item in emitted):
            raise ValueError("feed() must return a list of JSON objects")
        # Copy each emission at feed time: reusable mutable buffers must not rewrite history.
        actual.extend(json.loads(json.dumps(emitted, allow_nan=False)))
        if len(actual) > 10000:
            raise ValueError("parser emitted more than 10000 messages")
    return actual


def main():
    response_path = Path(sys.argv[1])
    try:
        request = json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(sys.stderr):
            actual = execute(request)
        response = {"actual": actual}
    except BaseException as exc:
        response = {"error": f"{type(exc).__name__}: {exc}"}
    response_path.write_text(json.dumps(response, ensure_ascii=True, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
