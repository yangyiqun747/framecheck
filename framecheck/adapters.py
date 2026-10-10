"""Adapter loading. All paths refer to user-selected local code."""

import hashlib
import importlib.util
import sys
from pathlib import Path

from .protocol import DemoParser


def fingerprint(path: Path) -> dict:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def load_adapter(spec: dict):
    kind = spec["kind"]
    if kind == "demo":
        return DemoParser(spec.get("bug", 0))
    path = Path(spec["path"]).resolve()
    if kind == "c":
        from .c_adapter import load_c_parser
        return load_c_parser(path)
    if kind != "python":
        raise ValueError(f"unknown adapter kind: {kind}")
    module_spec = importlib.util.spec_from_file_location("framecheck_user_adapter", path)
    if module_spec is None or module_spec.loader is None:
        raise ValueError("cannot load Python adapter")
    module = importlib.util.module_from_spec(module_spec)
    # Normal import semantics are required by dataclass annotation resolution.
    sys.modules[module_spec.name] = module
    sys.path.insert(0, str(path.parent))
    module_spec.loader.exec_module(module)
    parser = module.create_parser()
    if not callable(getattr(parser, "reset", None)) or not callable(getattr(parser, "feed", None)):
        raise ValueError("create_parser() must return an object with reset() and feed(bytes)")
    return parser
