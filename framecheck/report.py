"""Write an offline, self-contained FrameCheck result report.

The JSON file is the machine-readable source of truth. The HTML carries the same
data and only creates DOM text nodes for values supplied by a parser or user.
"""

from __future__ import annotations

import json
from pathlib import Path


def _script_json(value: dict) -> str:
    """JSON for a script data element, including protection from closing tags."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_report(report: dict, output_dir: Path) -> None:
    """Create readable JSON and an interactive offline HTML report.

    Serializing both representations first ensures invalid input cannot leave a
    new partial report, and no fields or nested values in ``report`` are changed.
    """
    raw_json = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    html = _HTML.replace("__FRAMECHECK_REPORT_DATA__", _script_json(report))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(raw_json, encoding="utf-8")
    (output_dir / "report.html").write_text(html, encoding="utf-8")


_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>FrameCheck · 解析器回归报告</title>
  <style>
    :root{color-scheme:dark;--bg:#10171c;--panel:#172129;--line:#2b3a44;--text:#e7f0f4;--muted:#9aafbc;--green:#71ddb0;--red:#ff8e88;--yellow:#f3c879;--accent:#8bc8ef}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}button,a{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:4px}main{max-width:1480px;margin:auto;padding:32px 40px 54px}.top{display:flex;gap:22px;justify-content:space-between;align-items:start;margin-bottom:26px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.15em}h1{font-size:clamp(24px,3vw,40px);line-height:1.2;margin:8px 0 12px;letter-spacing:-.03em}p{margin:0}.meta{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.links{display:flex;gap:16px;white-space:nowrap;padding-top:8px}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:24px 0}.metric{padding:20px 24px;background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric .label{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}.metric strong{font-size:46px;line-height:1.25;display:block;font-variant-numeric:tabular-nums;letter-spacing:-.04em}.green{color:var(--green)}.red{color:var(--red)}.yellow{color:var(--yellow)}.dot{height:7px;width:7px;border-radius:50%;display:inline-block;background:currentColor}.workspace{display:grid;grid-template-columns:320px minmax(0,1fr);gap:18px;align-items:start}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}.panel-head{padding:18px 20px;border-bottom:1px solid var(--line)}h2{font-size:17px;line-height:1.4;margin:0}.filters{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}.filter{background:transparent;border:1px solid var(--line);border-radius:7px;color:var(--muted);padding:5px 10px;font-size:12px}.filter.active{background:#263d4b;color:var(--text);border-color:#577a90}.case-list{max-height:730px;overflow:auto;padding:8px}.case{background:transparent;border:1px solid transparent;border-radius:9px;text-align:left;display:block;width:100%;color:var(--text);padding:13px 12px;margin-bottom:3px}.case:hover{background:#20303b}.case.selected{background:#253b48;border-color:#54778b}.case-title{display:block;font-weight:600;line-height:1.5;margin:5px 0;overflow-wrap:anywhere}.case-id{color:var(--muted);font:11px ui-monospace,Consolas,monospace}.case-meta{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--muted)}.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:650;white-space:nowrap}.badge.pass{color:var(--green)}.badge.fail{color:var(--red)}.badge.error{color:var(--yellow)}.detail{min-height:430px}.detail-head{padding:22px 24px;border-bottom:1px solid var(--line)}.detail-title-row{display:flex;align-items:start;justify-content:space-between;gap:20px}.detail-title-row h2{font-size:22px;overflow-wrap:anywhere}.detail-meta{margin-top:8px;color:var(--muted);font-size:12px}.reason{margin-top:18px;padding:12px 14px;border-left:3px solid var(--accent);background:#11202a;color:#d1e2eb;overflow-wrap:anywhere;white-space:pre-wrap}.reason.fail{border-color:var(--red)}.reason.error{border-color:var(--yellow)}.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.column{padding:23px 24px;min-width:0}.column+.column{border-left:1px solid var(--line)}h3{font-size:13px;font-weight:700;margin:0 0 15px;color:var(--muted)}.chunk{padding:12px 14px;border:1px solid #344753;background:#0e1a21;border-radius:9px;margin-bottom:10px}.chunk-label{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;margin-bottom:6px}.hex{font:14px/1.8 ui-monospace,"SFMono-Regular",Consolas,monospace;color:#b5ddf3;word-break:break-all;white-space:pre-wrap}.code{margin:0;background:#0e1a21;border:1px solid #344753;border-radius:9px;padding:14px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 ui-monospace,"SFMono-Regular",Consolas,monospace;max-height:450px}.output-block+.output-block{margin-top:20px}.diff{margin:0 24px 22px;padding:13px 15px;background:#11202a;border:1px solid #334a59;border-radius:9px;display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap;font-size:13px;overflow-wrap:anywhere}.detail-foot{display:flex;gap:18px;flex-wrap:wrap;align-items:center;padding:0 24px 24px;font-size:13px}.empty{padding:44px 24px;color:var(--muted);text-align:center}.empty strong{display:block;color:var(--text);font-size:18px;margin-bottom:8px}.protocol{margin-top:22px}details>summary{cursor:pointer;color:var(--muted);font-size:13px;padding:16px 20px}details .code{border:0;border-radius:0;border-top:1px solid var(--line);padding:20px}.footer{display:flex;justify-content:space-between;gap:12px;margin-top:22px;color:var(--muted);font-size:11px}.noscript{margin:20px 0;padding:15px;color:var(--yellow);border:1px solid var(--line);border-radius:8px}.count{color:var(--muted);font-size:12px;font-weight:400;margin-left:7px}@media(max-width:1100px){main{padding:26px 24px}.workspace{grid-template-columns:280px minmax(0,1fr)}.columns{grid-template-columns:1fr}.column+.column{border-left:0;border-top:1px solid var(--line)}}@media(max-width:760px){main{padding:22px 14px}.top{display:block}.links{margin-top:12px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric{padding:14px 18px}.metric strong{font-size:36px}.workspace{grid-template-columns:1fr}.case-list{max-height:300px}.detail-title-row{flex-direction:column;gap:8px}.footer{display:block}.detail-head,.column{padding:18px}.diff{margin:0 18px 18px}.detail-foot{padding:0 18px 18px}}
  </style>
</head>
<body>
<main>
  <header class="top">
    <div><div class="eyebrow">FRAMECHECK / PARSER REGRESSION</div><h1>每一段字节，都有可复测的结果。</h1><p id="run-meta" class="meta"></p></div>
    <nav class="links" aria-label="报告文件"><a href="report.json" download>下载 JSON</a></nav>
  </header>
  <noscript><p class="noscript">此报告需要启用 JavaScript 查看用例。完整原始结果可从「下载 JSON」读取。</p></noscript>
  <section class="metrics" aria-label="测试统计">
    <div class="metric"><span class="label">总用例</span><strong id="metric-total">—</strong></div>
    <div class="metric"><span class="label"><i class="dot green"></i>通过</span><strong id="metric-passed" class="green">—</strong></div>
    <div class="metric"><span class="label"><i class="dot red"></i>失败</span><strong id="metric-failed" class="red">—</strong></div>
    <div class="metric"><span class="label"><i class="dot yellow"></i>运行错误</span><strong id="metric-errors" class="yellow">—</strong></div>
  </section>
  <section class="workspace">
    <aside class="panel"><div class="panel-head"><h2>测试用例<span id="visible-count" class="count"></span></h2><div class="filters" role="group" aria-label="按结果筛选"><button class="filter active" type="button" data-filter="all" aria-pressed="true">全部</button><button class="filter" type="button" data-filter="fail" aria-pressed="false">失败</button><button class="filter" type="button" data-filter="error" aria-pressed="false">错误</button><button class="filter" type="button" data-filter="pass" aria-pressed="false">通过</button></div></div><div id="case-list" class="case-list" aria-label="选择测试用例"></div></aside>
    <article id="case-detail" class="panel detail" aria-live="polite"></article>
  </section>
  <details class="panel protocol"><summary>查看协议、种子与运行信息</summary><pre id="protocol-info" class="code"></pre></details>
  <footer class="footer"><span>本页由本次运行结果生成 · 无外部字体、脚本或网络请求</span><span id="version-info"></span></footer>
</main>
<script id="framecheck-data" type="application/json">__FRAMECHECK_REPORT_DATA__</script>
<script>
"use strict";
(() => {
  const report = JSON.parse(document.getElementById("framecheck-data").textContent);
  const results = Array.isArray(report.results) ? report.results : [];
  const statusNames = {pass: "通过", fail: "失败", error: "错误"};
  const categories = {basic:"正常报文",boundary:"边界输入",fragment:"拆分报文",resync:"噪声恢复",seeded:"固定种子分包",custom:"自定义协议",valid:"正常报文",split:"拆分报文",fragmentation:"拆分报文",concat:"连续多帧",coalescing:"连续多帧",noise:"噪声恢复",crc:"校验错误",checksum:"校验错误",truncated:"截断输入",recovery:"错误后恢复",random:"随机分块"};
  const stringify = value => JSON.stringify(value, null, 2);
  const display = value => value == null ? "—" : String(value);
  const node = (tag, className, text) => { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = display(text); return el; };
  const byId = id => document.getElementById(id);
  const labelFor = result => statusNames[result.status] || "未知状态";
  const statusClass = result => Object.hasOwn(statusNames, result.status) ? result.status : "error";
  const badgeFor = result => {const badge = node("span", "badge " + statusClass(result)); badge.append(node("i", "dot"), node("span", "", labelFor(result))); return badge;};
  const formatHex = raw => String(raw == null ? "" : raw).replace(/\s/g, "").replace(/(.{2})/g, "$1 ").trim();
  const summary = report.summary || {};
  ["total", "passed", "failed", "errors"].forEach(key => { byId("metric-" + key).textContent = display(summary[key]); });
  byId("run-meta").textContent = [report.adapter && report.adapter.name, report.suite && report.suite.name, report.generated_at].filter(value => value != null).join("  ·  ");
  byId("version-info").textContent = "FrameCheck " + display(report.tool_version) + " · " + display(report.run_id);
  byId("protocol-info").textContent = stringify({run_id:report.run_id, generated_at:report.generated_at, adapter:report.adapter, suite:report.suite});
  let filter = "all";
  let selected = results.find(result => result.status === "fail") || results.find(result => result.status === "error") || results[0] || null;
  function safeReproHref(value) {
    // Only a local relative file can be linked. Reject schemes, traversal,
    // Windows paths and URL control characters even in malformed reports.
    if (typeof value !== "string" || !value || /[\\\x00-\x20\x7f:#?]/.test(value) || value.startsWith("/") || value.split("/").some(part => part === "." || part === "..")) return null;
    return value.split("/").map(encodeURIComponent).join("/");
  }
  function renderDetail() {
    const detail = byId("case-detail");
    detail.replaceChildren();
    if (!selected) {const empty = node("div", "empty");empty.append(node("strong", "", "没有可展示的用例"), node("p", "", results.length ? "此筛选条件下暂无结果。" : "本次运行没有记录测试用例，请查看运行信息。"));detail.append(empty);return;}
    const head = node("div", "detail-head");
    const titleRow = node("div", "detail-title-row");
    titleRow.append(node("h2", "", selected.title), badgeFor(selected));
    head.append(titleRow, node("div", "detail-meta", [selected.id, categories[selected.category] || selected.category, display(selected.elapsed_ms) + " ms"].map(display).join("  ·  ")));
    if (selected.reason) head.append(node("p", "reason " + statusClass(selected), selected.reason));
    detail.append(head);
    const columns = node("div", "columns");
    const input = node("section", "column");
    const chunks = Array.isArray(selected.chunks_hex) ? selected.chunks_hex : [];
    input.append(node("h3", "", "输入 / 按实际投喂顺序"));
    if (!chunks.length) input.append(node("p", "meta", "无输入分块"));
    chunks.forEach((hex, i) => {const chunk = node("div", "chunk");const caption = node("div", "chunk-label");caption.append(node("span", "", "分块 " + (i + 1)), node("span", "", (String(hex).replace(/\s/g, "").length / 2) + " 字节"));chunk.append(caption, node("div", "hex", formatHex(hex) || "（空分块）"));input.append(chunk);});
    const fullStream = node("details");
    fullStream.append(node("summary", "", "查看完整字节流"), node("pre", "hex code", formatHex(selected.stream_hex) || "（空字节流）"));input.append(fullStream);
    const output = node("section", "column");
    [["预期输出", selected.expected], ["实际输出", selected.actual]].forEach(([label, value]) => {const block = node("div", "output-block");block.append(node("h3", "", label), node("pre", "code", stringify(value)));output.append(block);});
    columns.append(input, output);detail.append(columns);
    const diff = node("div", "diff");
    const index = selected.first_difference;
    diff.append(node("span", "", index == null ? (selected.status === "error" ? "首个分歧：未完成输出比较" : "首个分歧：无输出分歧") : "首个分歧：第 " + (Number(index) + 1) + " 条消息（索引 " + display(index) + "）"), node("span", "meta", "预期 " + (Array.isArray(selected.expected) ? selected.expected.length : 0) + " 条 · 实际 " + (Array.isArray(selected.actual) ? selected.actual.length : 0) + " 条"));
    detail.append(diff);
    const foot = node("div", "detail-foot");
    const href = safeReproHref(selected.repro_file);
    if (href) {const link = node("a", "", "下载此用例的复现文件 ↗");link.href = href;link.setAttribute("download", "");foot.append(link);}
    else if (selected.repro_file) foot.append(node("span", "meta", "复现文件路径无法作为本地链接使用：" + display(selected.repro_file)));
    else foot.append(node("span", "meta", "此用例未记录复现文件"));
    detail.append(foot);
  }
  function renderList() {
    const list = byId("case-list");list.replaceChildren();
    const visible = results.filter(result => filter === "all" || result.status === filter);
    byId("visible-count").textContent = "(" + visible.length + ")";
    if (!visible.includes(selected)) selected = visible[0] || null;
    if (!visible.length) list.append(node("p", "empty", "此筛选条件下暂无结果"));
    visible.forEach(result => {const button = node("button", "case" + (result === selected ? " selected" : ""));button.type = "button";button.setAttribute("aria-pressed", String(result === selected));button.append(node("span", "case-id", result.id), node("span", "case-title", result.title));const meta = node("span", "case-meta");meta.append(badgeFor(result), node("span", "", categories[result.category] || result.category));button.append(meta);button.addEventListener("click", () => { selected = result; renderList(); });list.append(button);});
    renderDetail();
  }
  document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
    filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach(other => {const active = other === button;other.classList.toggle("active", active);other.setAttribute("aria-pressed", String(active));});
    renderList();
  }));
  renderList();
})();
</script>
</body>
</html>
'''

