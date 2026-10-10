"""Local parser checks, with a separate opt-in optional board metadata backend."""

import argparse
import html
import json
import sys
from pathlib import Path

from . import __version__
from .adapters import fingerprint
from .cases import demo_suite, read_suite
from .runner import run_suite

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = [("correct", "正确解析器", 0), ("fragment", "故障：分包丢失", 1),
            ("concat", "故障：连续帧丢失", 2), ("crc", "故障：漏验 CRC", 3),
            ("resync", "故障：噪声后无法恢复", 4)]


def summary_line(report, output):
    s = report["summary"]
    print(f"{report['adapter']['name']}: {s['passed']}/{s['total']} 通过，{s['failed']} 失败，{s['errors']} 错误")
    print(f"报告: {output.resolve() / 'report.html'}")


def add_adapter_args(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--python", type=Path, help="Python adapter with create_parser()")
    group.add_argument("--c-source", type=Path, help="C adapter source exporting fc_reset/fc_feed")
    group.add_argument("--library", type=Path, help="prebuilt C adapter shared library")
    parser.add_argument("--compiler", help="C compiler executable path")
    parser.add_argument("--bug", type=int, choices=range(5), default=0, help="FC_BUG macro for demo C source")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=3, help="seconds per case, includes worker startup")
    parser.add_argument("--record-source", type=Path, nargs="+", help="record relevant production source/dependency fingerprints")


def _select_adapter(args):
    path = args.python or args.c_source or args.library
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"文件不存在: {path}")
    if args.python:
        return {"kind": "python", "path": str(path), "name": path.name, "fingerprint": fingerprint(path)}
    if args.c_source:
        from .c_adapter import build_library
        lib = build_library(path, args.out.resolve()/"build", bug=args.bug, compiler=args.compiler)
        return {"kind": "c", "path": str(lib.resolve()), "name": path.name,
                "fingerprint": {"source": fingerprint(path), "library": fingerprint(lib), "bug": args.bug}}
    return {"kind": "c", "path": str(path), "name": path.name, "fingerprint": fingerprint(path)}


def select_adapter(args):
    # Resolve optional dependency evidence before compiling/running any adapter.
    sources = []
    for source in args.record_source or []:
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"待记录的源码不存在: {source}")
        sources.append(fingerprint(source))
    adapter = _select_adapter(args)
    if sources:
        adapter["fingerprint"]["recorded_sources"] = sources
    return adapter


def write_demo_index(reports, output, native):
    rows = []
    for key, report in reports:
        s = report["summary"]
        rows.append(f'<a class="row" href="{key}/report.html"><span>{html.escape(report["adapter"]["name"])}</span>'
                    f'<strong>{s["passed"]} / {s["total"]} 通过</strong><span>{s["failed"]} 失败 · {s["errors"]} 错误 →</span></a>')
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FrameCheck · 解析器回归演示</title><style>
*{box-sizing:border-box}body{margin:0;background:#10141d;color:#e6edf6;font:16px/1.6 system-ui,sans-serif}
main{max-width:980px;margin:6vh auto;padding:30px}small{color:#6ce3c3;letter-spacing:.15em}h1{font-size:42px;margin:8px 0 12px}
p{color:#aab8cc;max-width:760px}.badge{border:1px solid #3a5961;border-radius:30px;padding:6px 14px;color:#91e6d0;display:inline-block;margin:10px 0 25px}
.row{display:grid;grid-template-columns:2fr 1fr 1.2fr;gap:20px;color:inherit;text-decoration:none;background:#1a2230;border:1px solid #2b374c;padding:24px;margin:12px 0;border-radius:12px}
.row:hover{border-color:#6ce3c3}.row span:last-child{color:#aab8cc}footer{margin-top:30px;color:#8795a9;font-size:14px}
@media(max-width:650px){h1{font-size:30px}.row{grid-template-columns:1fr;gap:8px}main{padding:20px}}
</style><main><small>FRAMECHECK / LOCAL REGRESSION</small><h1>让解析器的错误有据可查</h1>
<p>给五个解析器输入完全相同的测试数据。正确实现应全部通过；四个故障版本分别暴露分包丢失、连续帧丢失、漏验 CRC 和噪声恢复问题。点击报告查看字节、预期输出和可重跑的失败用例。</p>
<div class="badge">MODE</div>ROWS
<footer>演示协议 · 固定随机种子 · 本地主机执行<br>这份报告只覆盖列出的输入与语义约定，尚未验证真实串口时序、DMA、中断或板卡行为。</footer></main></html>'''
    document = document.replace("MODE", "已编译并执行 C 解析器" if native else "Python 解析器演示 · 无编译器也可运行").replace("ROWS", "".join(rows))
    (output / "index.html").write_text(document, encoding="utf-8")
    (output / "summary.json").write_text(json.dumps({key: report["summary"] for key, report in reports}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def demo(args):
    args.out.mkdir(parents=True, exist_ok=True)
    suite = demo_suite(args.seed)
    reports = []
    for key, title, bug in VARIANTS:
        if args.native:
            from .c_adapter import build_library
            source = ROOT/"examples"/"c"/"parser.c"
            if not source.exists():
                raise ValueError("native demo needs a source checkout containing examples/c/parser.c")
            lib = build_library(source, args.out.resolve()/"build", bug=bug, compiler=args.compiler)
            adapter = {"kind": "c", "path": str(lib.resolve()), "name": title,
                       "fingerprint": {"source": fingerprint(source), "library": fingerprint(lib), "bug": bug}}
        else:
            adapter = {"kind": "demo", "bug": bug, "name": title,
                       "fingerprint": {"implementation": "framecheck.protocol.DemoParser", "bug": bug}}
        report = run_suite(adapter, suite, args.out/key, args.timeout)
        reports.append((key, report))
        summary_line(report, args.out/key)
    write_demo_index(reports, args.out, args.native)
    expected_failures = ["fragment", "concat", "crc", "resync"]
    ok = reports[0][1]["summary"]["passed"] == len(suite["cases"])
    for (_, report), category in zip(reports[1:], expected_failures):
        ok = ok and report["summary"]["errors"] == 0 and any(
            result["category"] == category and result["status"] == "fail" for result in report["results"])
    print(f"演示自检: {'通过' if ok else '未通过'}；入口: {args.out.resolve() / 'index.html'}")
    return 0 if ok else 1


def main(argv=None):
    # Preserve the chosen console encoding; escape unsupported characters instead
    # of turning a successful run into an encoding error on redirected Windows I/O.
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="framecheck", description="流式通信协议解析器回归验收")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run fixtures against a local adapter")
    add_adapter_args(run)
    run.add_argument("--suite", type=Path, help="custom JSON suite (default: demonstration protocol)")
    run.add_argument("--seed", type=int, default=20261008)
    replay = commands.add_parser("replay", help="replay exact failing chunks against any adapter")
    replay.add_argument("repro", type=Path)
    add_adapter_args(replay)
    showcase = commands.add_parser("demo", help="correct implementation and four deliberately faulty implementations")
    showcase.add_argument("--out", type=Path, required=True)
    showcase.add_argument("--native", action="store_true", help="compile and execute C variants")
    showcase.add_argument("--compiler")
    showcase.add_argument("--seed", type=int, default=20261008)
    showcase.add_argument("--timeout", type=float, default=3)
    export = commands.add_parser("export-suite", help="write a deterministic demonstration suite")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--seed", type=int, default=20261008)
    inspect = commands.add_parser("inspect", help="只读查找项目中的解析入口、帧定义和校验代码")
    inspect.add_argument("--project", type=Path, required=True, help="user-selected project directory")
    inspect.add_argument("--out", type=Path, required=True, help="directory for intake.md and intake.json")
    inspect.add_argument("--focus", nargs="+", help="relative files/directories to inspect within the project")
    board = commands.add_parser("board-info", help="可选：枚举设备，或显式读取芯片元信息；不做解析器验收")
    board.add_argument("--out", type=Path, required=True)
    board.add_argument("--backend-python", type=Path, help="Python with optional board SDK installed")
    board.add_argument("--connect", action="store_true", help="explicitly connect to the selected probe")
    board.add_argument("--probe-id", help="complete, exact probe ID from inventory")
    board.add_argument("--profile", choices=("cortex-m", "stm32f1-high-density"))
    board.add_argument("--timeout", type=float, default=10, help="metadata process timeout, at most 60 seconds")
    serial = commands.add_parser("serial-run", help="显式执行项目串口用例，或离线自检；不复位或烧录")
    from .serial_runner import add_arguments as add_serial_arguments
    add_serial_arguments(serial)
    args = parser.parse_args(argv)
    try:
        if args.command == "serial-run":
            from .serial_runner import execute
            return execute(args)
        if args.command == "board-info":
            from .board_info import collect_board_info
            report = collect_board_info(args.out, args.backend_python, args.connect, args.probe_id, args.profile, args.timeout)
            print(f"接板信息: {report['status']}；这不是解析器验收结果。")
            print(f"报告: {args.out.resolve() / 'board-info.md'}")
            return 0 if report["status"] == "ok" else 1
        if args.command == "inspect":
            from .inspect_project import inspect_project
            intake = inspect_project(args.project, args.out, focus=args.focus)
            print(f"已只读检查 {intake['files_scanned']} 个文件，找到 {len(intake['candidates'])} 处相关线索。")
            print(f"引导清单: {args.out.resolve() / 'intake.md'}")
            print("这些是代码线索；请结合协议说明或已确认报文确定预期行为，再运行验收。")
            return 0
        if args.command == "demo":
            return demo(args)
        if args.command == "export-suite":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(demo_suite(args.seed), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            print(f"用例: {args.out.resolve()}")
            return 0
        suite_path = args.repro if args.command == "replay" else args.suite
        suite = read_suite(suite_path) if suite_path else demo_suite(args.seed)
        adapter = select_adapter(args)
        report = run_suite(adapter, suite, args.out, args.timeout)
        summary_line(report, args.out)
        return 0 if report["summary"]["passed"] == report["summary"]["total"] else 1
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"配置或执行准备失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
