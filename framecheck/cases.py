"""Expected messages come from fixture construction, never from the tested parser."""

import json
import random
import re
from pathlib import Path

from .protocol import DESCRIPTION, encode, message


def make_case(case_id, title, category, chunks, expected):
    return {"id": case_id, "title": title, "category": category,
            "chunks_hex": [part.hex() for part in chunks], "expected": expected}


def demo_suite(seed: int = 20261008) -> dict:
    a = encode(1, 0x10, bytes.fromhex("102030"))
    b = encode(2, 0x11, b"")
    c = encode(3, 0x12, bytes(range(64)))
    ma = message(1, 0x10, bytes.fromhex("102030"))
    mb = message(2, 0x11, b"")
    mc = message(3, 0x12, bytes(range(64)))
    cases = [
        make_case("golden", "完整帧", "basic", [a], [ma]),
        make_case("empty-payload", "零长度载荷", "boundary", [b], [mb]),
        make_case("max-payload", "64 字节载荷上限", "boundary", [c], [mc]),
        make_case("concat", "同一次输入包含三帧", "concat", [a+b+c], [ma, mb, mc]),
        make_case("bytewise", "逐字节输入", "fragment", [bytes([x]) for x in a+b], [ma, mb]),
        make_case("empty-feed", "分包之间出现空输入", "fragment", [a[:4], b"", a[4:]], [ma]),
        make_case("truncated", "末尾不完整帧不得提前输出", "boundary", [a[:-1]], []),
        make_case("header-only", "仅帧头不得输出", "boundary", [b"\xaa", b"\x55"], []),
        make_case("noise", "前导噪声后恢复", "resync", [b"\x00\x7f\x13"+a], [ma]),
        make_case("noise-between", "两帧之间有噪声", "resync", [a+b"\x00\xff\x13"+b], [ma, mb]),
        make_case("overlap-header", "AA AA 55 重叠帧头", "resync", [b"\xaa"+a], [ma]),
        make_case("invalid-length", "非法长度后恢复", "resync", [b"\xaa\x55\xff\x00\x00"+a], [ma]),
        make_case("payload-header", "载荷中的帧头保持原样", "boundary",
                  [encode(4, 0x13, b"\xaa\x55\x00\xaa\x55")], [message(4, 0x13, b"\xaa\x55\x00\xaa\x55")]),
    ]
    bad = a[:-1] + bytes([a[-1] ^ 0x80])
    cases += [make_case("bad-crc", "CRC 损坏不得输出", "crc", [bad], []),
              make_case("crc-recover", "坏 CRC 后接有效帧", "crc", [bad+b], [mb]),
              make_case("crc-fragment", "坏 CRC 分包后仍能恢复", "crc", [bad[:4], bad[4:]+b], [mb])]
    for i in range(1, len(a)):
        cases.append(make_case(f"split-{i:02d}", f"在第 {i} 字节处分包", "fragment", [a[:i], a[i:]], [ma]))
    rng = random.Random(seed)
    for i in range(20):
        count = rng.randint(1, 6)
        frames, expected = [], []
        for _ in range(count):
            payload = rng.randbytes(rng.randint(0, 64))
            seq, kind = rng.randrange(256), rng.randrange(256)
            frames.append(encode(seq, kind, payload))
            expected.append(message(seq, kind, payload))
        stream = b"".join(frames)
        chunks = []
        while stream:
            size = rng.randint(1, min(32, len(stream)))
            chunks.append(stream[:size])
            stream = stream[size:]
        cases.append(make_case(f"seeded-{i:02d}", f"固定种子随机分包 {i+1}", "seeded", chunks, expected))
    return {"schema_version": 1, "name": "示例协议回归用例", "seed": seed,
            "protocol": DESCRIPTION, "cases": cases}


def validate_suite(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("suite.schema_version must be 1")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("suite must be finite JSON data (NaN/Infinity are not allowed)") from exc
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 2000:
        raise ValueError("suite.cases must contain 1..2000 cases")
    ids = set()
    total_bytes = 0
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each case must be an object")
        key = case.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) or key in ids:
            raise ValueError("case id must be unique ASCII letters/digits/_/- (1..80)")
        ids.add(key)
        if not isinstance(case.get("title", key), str) or not isinstance(case.get("category", "custom"), str):
            raise ValueError(f"{key}: title/category must be strings")
        chunks = case.get("chunks_hex")
        if not isinstance(chunks, list) or not chunks or len(chunks) > 10000:
            raise ValueError(f"{key}: chunks_hex must contain 1..10000 strings")
        for chunk in chunks:
            if not isinstance(chunk, str):
                raise ValueError(f"{key}: hex chunks must be strings")
            try:
                total_bytes += len(bytes.fromhex(chunk))
            except ValueError as exc:
                raise ValueError(f"{key}: invalid hexadecimal input") from exc
        expected = case.get("expected")
        if not isinstance(expected, list) or any(not isinstance(m, dict) for m in expected):
            raise ValueError(f"{key}: expected must be a list of JSON objects")
        case.setdefault("title", key)
        case.setdefault("category", "custom")
    if total_bytes > 4 * 1024 * 1024:
        raise ValueError("suite exceeds 4 MiB input limit")
    value.setdefault("name", "自定义协议用例")
    value.setdefault("seed", 0)
    value.setdefault("protocol", {"name": "custom"})
    if not isinstance(value["name"], str) or type(value["seed"]) is not int or not isinstance(value["protocol"], dict):
        raise ValueError("suite name must be a string, seed an integer, and protocol an object")
    return value


def read_suite(path: Path) -> dict:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("suite JSON exceeds 16 MiB")
    return validate_suite(json.loads(path.read_text(encoding="utf-8-sig")))
