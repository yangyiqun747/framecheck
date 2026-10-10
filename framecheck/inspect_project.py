"""Read-only, bounded evidence discovery for onboarding a real parser project.

This module does not import a target module, run a compiler, evaluate an expression,
or infer a protocol contract. Its output is a shortlist for human confirmation.
"""

import json
import os
import re
import stat
from collections import Counter
from pathlib import Path


MAX_FILE_BYTES = 500 * 1024
MAX_FILES = 2000
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 60
MAX_ENTRIES = 20000

_SKIP_DIRS = {
    "node_modules", "vendor", "vendors", "thirdparty", "third_party", "external",
    "drivers", "cmsis", "hal", "stm32cube", "middlewares", "middleware",
    "build", "builds", "dist", "out", "output", "outputs", "target", "debug",
    "release", "__pycache__", "venv", "env", "site-packages", "cmake-build-debug",
    "cmake-build-release", "coverage", "htmlcov", "generated", "objects", "obj",
}
_APPLICATION_DRIVER_DIRS = {"system", "bsp", "board"}
_TEXT_EXTENSIONS = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".ino", ".py",
    ".md", ".rst", ".txt", ".cmake", ".xml", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".pro", ".prj", ".uvprojx", ".ioc",
}
_BUILD_NAMES = {"cmakelists.txt", "makefile", "platformio.ini", "package.xml",
                "pyproject.toml", "setup.py", "setup.cfg", "meson.build"}
_SECRET_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer"}
_ENTRY = re.compile(r"parse|parser|decode|unpack|(?:^|_)feed(?:_|$)|(?:^|_)recv(?:_|$)|"
                    r"receive|(?:^|_)rx(?:_|$)|rx(?:_?event|cplt|complete)(?:callback)?|"
                    r"(?:^|_)on_(?:uart|serial)_data(?:_|$)|process_?byte|process_?frame", re.I)
_CHECKSUM = re.compile(r"crc(?:8|16|32|64)?|checksum|check_sum|fletcher|modbus_?crc", re.I)
_ENCODER = re.compile(r"encode|pack(?:et)?_?(?:frame|message)|frame_?pack|"
                      r"send_?(?:frame|packet|message)|serialize|build_?frame", re.I)
_FRAMING = re.compile(r"(?:\bSOF\b|\bEOF\b|HEADER|HEAD_BYTE|FRAME_HEAD|FRAME_START|"
                      r"SYNC_WORD|SYNC_BYTE|START_BYTE|END_BYTE|PREAMBLE|PAYLOAD_?LEN|"
                      r"FRAME_?(?:LEN|SIZE|MAX)|PACKET_?(?:LEN|SIZE|MAX)|LEN(?:GTH)?_?OFFSET|"
                      r"MAX_?(?:PAYLOAD|PACKET|FRAME)|TAIL_BYTE|CRC_?(?:LEN|SIZE)|"
                      r"\bUSART_(?:REC_LEN|RX_STA)\b)", re.I)
_CONSTANT = re.compile(r"#\s*define\b|\b(?:const|constexpr|enum)\b|\b[A-Z][A-Z0-9_]{2,}\s*=")
_SYMBOL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_REFERENCE = re.compile(r"golden|expected|fixture|assert|known.?good|sample|test.?vector|"
                        r"黄金|已知正确|期望|预期|样例|示例|测试向量|帧格式|协议格式", re.I)
_DOC_PROTOCOL = re.compile(r"protocol|frame|packet|checksum|crc|串口|协议|帧头|帧长|校验|报文", re.I)
_HEX = re.compile(r"(?:\b[0-9a-fA-F]{2}[ ,:]){3,}|0x[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}){6,}")
_CATEGORY_LABELS = {
    "entry": "接收与解析入口", "framing": "帧格式与长度线索", "checksum": "CRC／校验",
    "encoder": "发送与编码端", "reference": "已有样例、测试或协议文档", "build": "构建入口",
}


def _is_link(path: Path) -> bool:
    """Also catches Windows directory junctions on Python versions before is_junction."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_components(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for component in relative.parts:
        current = current / component
        if _is_link(current):
            raise ValueError(f"focus must not follow a symlink or junction: {relative.as_posix()}")


def _focus_paths(root: Path, focus: list[str] | None) -> list[Path]:
    if not focus:
        return [root]
    result = []
    for value in focus:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("focus paths must be non-empty relative paths")
        # Treat both separators as path separators, including on non-Windows hosts.
        portable = value.replace("\\", "/")
        target = Path(portable)
        if target.is_absolute() or re.match(r"^[A-Za-z]:", portable) or ".." in target.parts:
            raise ValueError(f"focus must stay within the project: {value}")
        lexical = root / target
        if not lexical.exists():
            raise ValueError(f"focus does not exist: {value}")
        _check_components(lexical, root)
        resolved = lexical.resolve(strict=True)
        if not _inside(resolved, root):
            raise ValueError(f"focus must stay within the project: {value}")
        result.append(resolved)
    # Remove duplicates and descendants of another selected directory.
    unique = sorted(set(result), key=lambda item: (len(item.parts), item.as_posix().casefold(), item.as_posix()))
    kept = []
    for item in unique:
        if not any(parent.is_dir() and _inside(item, parent) for parent in kept):
            kept.append(item)
    return kept


def _skip_reason(path: Path, root: Path, output: Path) -> str | None:
    relative = path.relative_to(root)
    if output != root and _inside(path, output):
        return "scanner_output"
    if output == root and relative.as_posix() in {"intake.json", "intake.md"}:
        return "scanner_output"
    directory_parts = relative.parts[:-1] if not path.is_dir() else relative.parts
    for index, part in enumerate(directory_parts):
        name = part.casefold()
        if name.startswith("."):
            return "hidden_directory"
        if name == "drivers":
            # STM32 board projects commonly place application receive state
            # machines beside SDK drivers. Traverse the container, but only
            # inspect these known application/board subtrees beneath it.
            descendants = relative.parts[index + 1:]
            if descendants and descendants[0].casefold() not in _APPLICATION_DRIVER_DIRS:
                return "vendor_or_build_directory"
            continue
        if name in _SKIP_DIRS or name.startswith("cmake-build-"):
            return "vendor_or_build_directory"
        if name.startswith("stm32") and name.endswith("_hal_driver"):
            return "vendor_or_build_directory"
    if path.name.startswith("."):
        return "hidden_or_secret_file"
    if re.fullmatch(r"stm32.*_hal_conf\.h", path.name.casefold()):
        return "sdk_configuration"
    if path.suffix.casefold() in _SECRET_EXTENSIONS or path.name.casefold() in {
        "id_rsa", "id_ed25519", "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml"
    }:
        return "secret_or_certificate"
    return None


def _excerpt(lines: list[str], index: int) -> str:
    # No more than three lines, 180 characters per line and 540 total.
    start = max(0, index - 1)
    return "\n".join(line[:180] for line in lines[start:min(len(lines), index + 2)])[:540]


def _discover(text: str, relative: str) -> list[dict]:
    lines = text.splitlines()
    path_lower = relative.casefold()
    suffix = Path(relative).suffix.casefold()
    is_doc = suffix in {".md", ".rst", ".txt"}
    is_reference = bool(re.search(r"(?:^|[/_.-])(?:tests?|examples?|fixtures?|samples?)(?:[/_.-]|$)", path_lower))
    protocol_document = is_doc and bool(_DOC_PROTOCOL.search(relative) or _DOC_PROTOCOL.search(text))
    is_build = Path(relative).name.casefold() in _BUILD_NAMES or suffix == ".cmake"
    path_bonus = 12 if re.search(r"protocol|parser|serial|uart|usart|comm|串口|协议|解析", path_lower) else 0
    path_bonus += 5 if re.search(r"(?:^|/)(?:src|app|application|core)(?:/|$)", path_lower) else 0
    found = []
    seen = set()

    def add(index, category, score, symbol=None):
        key = (index, category, symbol)
        if key in seen:
            return
        seen.add(key)
        item = {"path": relative, "line": index + 1, "category": category,
                "excerpt": _excerpt(lines, index), "score": score + path_bonus}
        if symbol:
            item["symbol"] = symbol
        found.append(item)

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for match in _SYMBOL.finditer(line):
            symbol = match.group(1)
            if symbol.casefold() in {"if", "while", "for", "switch", "sizeof", "return", "assert"}:
                continue
            prefix = line[:match.start()].strip()
            declaration_prefix = bool(prefix and re.fullmatch(r"[\w\s:*&<>]+", prefix) and
                                      not re.match(r"(?:return|if|while|for|switch|case)\b", prefix))
            next_lines = [value.strip() for value in lines[index + 1:index + 4] if value.strip()]
            definition = bool(re.search(r"\bdef\s+" + re.escape(symbol) + r"\s*\(", line) or
                              (declaration_prefix and not stripped.startswith(("//", "/*", "*")) and
                               ("{" in line or (";" not in line and next_lines and next_lines[0] == "{"))))
            score = 85 if definition else (55 if declaration_prefix else 40)
            if _CHECKSUM.search(symbol):
                add(index, "checksum", score, symbol)
            elif _ENCODER.search(symbol):
                add(index, "encoder", score, symbol)
            elif _ENTRY.search(symbol):
                add(index, "entry", score, symbol)
        if _FRAMING.search(line) and (_CONSTANT.search(line) or is_doc):
            add(index, "framing", 80 if not is_doc else 65)
        if (is_reference and _REFERENCE.search(line)) or (
                protocol_document and (_REFERENCE.search(line) or _HEX.search(line))):
            add(index, "reference", 78 if is_reference else 68)
        if is_build and (index < 6 or re.search(r"project\s*\(|add_(?:library|executable)|target_sources|\[env:|name\s*=", line, re.I)):
            add(index, "build", 30)
        if len(found) >= 80:
            break
    # Bounded per-file candidates prevent a large generated parser monopolizing the report.
    return sorted(found, key=lambda item: (-item["score"], item["line"], item["category"]))[:18]


def _markdown(report: dict) -> str:
    def safe(value):
        return str(value).replace("`", "ˋ").replace("\r", " ").replace("\n", " ")

    rows = ["# FrameCheck 真实协议接入线索", "", f"项目：{safe(report['project_name'])}", "",
            f"已读取 {report['files_scanned']} 个文本文件，找到 {len(report['candidates'])} 条候选线索。",
            "这些线索来自静态文本匹配，可能包含误报；还不能当作已确认的协议规范。", "",
            "## 找到的文件与可分享的具体片段", "",
            "如果不方便开放整个项目，可只分享下列候选函数的完整定义、相关结构体和常量。行号指向命中位置，显示的三行只是定位线索。", ""]
    for category, label in _CATEGORY_LABELS.items():
        items = [item for item in report["candidates"] if item["category"] == category]
        if not items:
            continue
        rows.extend([f"### {label}", ""])
        for item in items:
            symbol = f"，符号 `{safe(item['symbol'])}`" if item.get("symbol") else ""
            rows.append(f"- `{safe(item['path'])}:{item['line']}`{symbol}")
            # A longer fence than any source backtick run keeps Markdown links,
            # images and embedded fences inert while preserving exact source text.
            runs = re.findall(r"`+", item["excerpt"])
            fence = "`" * max(3, max((len(run) + 1 for run in runs), default=3))
            rows.extend([fence + "text", item["excerpt"], fence])
            rows.append("")
    if not report["candidates"]:
        rows.extend(["没有找到足够明确的协议线索。可以用 --focus 指定解析器所在目录或文件，再扫描一次。", ""])
    rows.extend(["## 接下来由 Codex 继续", "",
                 "Codex 会读取相关片段并准备接入文件，只向你追问仍需确认的规则；下面是处理顺序，不是要求你填写的表格。", ""])
    rows.extend(f"{index}. {step}" for index, step in enumerate(report["next_steps"], 1))
    rows.extend(["", "## 扫描范围", "",
                 "扫描器只读取文本，不导入、执行或编译项目代码。默认跳过隐藏目录、依赖／芯片驱动目录、构建产物、密钥证书和链接。",
                 "扫描结果保存在本地；将代码或此报告交给 Codex 分析时，相应内容会进入模型上下文。", "",
                 f"扫描是否因资源上限截断：{'是' if report['truncated'] else '否'}。",
                 f"排除统计：`{json.dumps(report['exclusions'], ensure_ascii=False, sort_keys=True)}`", ""])
    return "\n".join(rows)


def inspect_project(project: Path, output_dir: Path, focus: list[str] | None = None) -> dict:
    """Write intake.json/intake.md from bounded static evidence; never execute code."""
    lexical_root = Path(project).absolute()
    if not lexical_root.exists() or not lexical_root.is_dir():
        raise ValueError("project must be an existing directory")
    if _is_link(lexical_root):
        raise ValueError("project must not be a symlink or junction")
    root = lexical_root.resolve(strict=True)
    output = Path(output_dir).absolute().resolve()
    if output == root:
        raise ValueError("output directory must be a dedicated directory, not the project root")
    # An output link could bypass the scope check or overwrite files elsewhere.
    cursor = Path(output_dir).absolute()
    while cursor != cursor.parent:
        if cursor.exists() and _is_link(cursor):
            raise ValueError("output directory must not follow a symlink or junction")
        cursor = cursor.parent
    selected = _focus_paths(root, focus)
    if focus:
        for item in selected:
            reason = _skip_reason(item, root, output)
            if reason:
                raise ValueError(f"focus is excluded ({reason}): {item.relative_to(root).as_posix()}")
    # Create only the explicitly requested report directory. Excluding it from the
    # first scan too keeps repeated scans stable when output is inside the project.
    output.mkdir(parents=True, exist_ok=True)
    for name in ("intake.json", "intake.md"):
        target = output / name
        try:
            info = target.lstat()
        except FileNotFoundError:
            continue
        if _is_link(target) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ValueError(f"output file must be a regular unlinked file: {name}")
    exclusions = Counter()
    candidates = []
    files_scanned = 0
    files_considered = 0
    total_bytes = 0
    entries = 0
    truncated = False

    def visit(path):
        nonlocal entries, truncated
        if truncated:
            return
        entries += 1
        if entries > MAX_ENTRIES:
            exclusions["entry_limit"] += 1
            truncated = True
            return
        try:
            if _is_link(path):
                exclusions["symlink_or_junction"] += 1
                return
            resolved = path.resolve(strict=True)
            if not _inside(resolved, root):
                exclusions["outside_project"] += 1
                return
            reason = _skip_reason(path, root, output)
            if reason:
                exclusions[reason] += 1
                return
            if path.is_dir():
                with os.scandir(path) as iterator:
                    children = []
                    for entry in iterator:
                        if len(children) >= MAX_ENTRIES:
                            exclusions["entry_limit"] += 1
                            truncated = True
                            return
                        children.append(Path(entry.path))
                for child in sorted(children, key=lambda item: (item.name.casefold(), item.name)):
                    yield from visit(child)
            elif path.is_file():
                yield path
            else:
                exclusions["not_regular_file"] += 1
        except (OSError, ValueError):
            exclusions["unreadable_or_changed"] += 1

    for start in selected:
        for path in visit(start):
            name = path.name.casefold()
            if path.suffix.casefold() not in _TEXT_EXTENSIONS and name not in _BUILD_NAMES:
                exclusions["unsupported_extension"] += 1
                continue
            if files_considered >= MAX_FILES:
                exclusions["file_limit"] += 1
                truncated = True
                break
            files_considered += 1
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    exclusions["file_too_large"] += 1
                    continue
                if total_bytes + size > MAX_TOTAL_BYTES:
                    exclusions["total_byte_limit"] += 1
                    truncated = True
                    break
                with path.open("rb") as handle:
                    raw = handle.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    exclusions["file_too_large"] += 1
                    continue
                if total_bytes + len(raw) > MAX_TOTAL_BYTES:
                    exclusions["total_byte_limit"] += 1
                    truncated = True
                    break
                # Binary or undecodable files still consumed the read budget.
                total_bytes += len(raw)
                if b"\x00" in raw:
                    exclusions["binary_content"] += 1
                    continue
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("gb18030")
            except UnicodeDecodeError:
                exclusions["unsupported_encoding"] += 1
                continue
            except OSError:
                exclusions["unreadable_or_changed"] += 1
                continue
            files_scanned += 1
            candidates.extend(_discover(text, path.relative_to(root).as_posix()))
            if len(candidates) > MAX_CANDIDATES * 6:
                candidates = sorted(candidates, key=_sort_key)[:MAX_CANDIDATES * 4]
        if truncated:
            break
    ranked = sorted(candidates, key=_sort_key)
    # Keep several distinct files/categories visible rather than pages of CRC calls.
    selected_candidates = []
    per_file = Counter()
    per_category = Counter()
    for candidate in ranked:
        if per_file[candidate["path"]] >= 8 or per_category[candidate["category"]] >= 18:
            continue
        selected_candidates.append(candidate)
        per_file[candidate["path"]] += 1
        per_category[candidate["category"]] += 1
        if len(selected_candidates) >= MAX_CANDIDATES:
            break
    next_steps = [
        "Codex 核对候选接收／解析入口，并按需读取相关函数、常量和结构体；范围不对时收窄到应用目录或解析文件。",
        "Codex 优先查找已有测试、发送端和协议文档中的独立正确报文与业务字段；只有缺少独立样例时，才请用户补充一条原始报文及期望结果。",
        "Codex 对照代码和文档形成协议草案，标出帧头、长度含义、校验覆盖范围、字节序及最大帧长，只追问证据尚不能确认的规则。",
        "Codex 核对字节流／完整报文输入、输出结构及复位方式后建立主机适配器；遇到 HAL／RTOS 依赖先说明，不改动产品代码。",
        "Codex 依据独立样例和已确认规则准备首条测试，再运行分包、连续帧、错误校验和恢复测试；不用被测解析器生成预期结果。",
    ]
    report = {"schema_version": 1, "project_name": root.name, "files_scanned": files_scanned,
              "files_considered": files_considered,
              "bytes_scanned": total_bytes, "candidates": selected_candidates,
              "next_steps": next_steps, "exclusions": dict(sorted(exclusions.items())),
              "truncated": truncated,
              "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_files": MAX_FILES,
                         "max_total_bytes": MAX_TOTAL_BYTES, "max_candidates": MAX_CANDIDATES},
              "focus": [item.relative_to(root).as_posix() or "." for item in selected]}
    (output / "intake.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "intake.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _sort_key(candidate):
    return (-candidate["score"], candidate["path"].casefold(), candidate["path"],
            candidate["line"], candidate["category"], candidate.get("symbol", ""))
