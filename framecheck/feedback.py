"""Evidence-based feedback for arbitrary JSON message contracts.

Field paths are arrays relative to one message, not expressions to evaluate.
These observations locate a disagreement; they do not diagnose protocol causes.
"""

import json


def same_json(left, right):
    if type(left) is not type(right):
        return type(left) in (int, float) and type(right) in (int, float) and left == right
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


def _preview(value):
    # Bound the rendered preview without serializing a whole large subtree.
    if isinstance(value, dict):
        return f"对象（{len(value)} 个字段）"
    if isinstance(value, list):
        return f"数组（{len(value)} 项）"
    if isinstance(value, str) and len(value) > 120:
        return json.dumps(value[:120], ensure_ascii=False)[:180] + "…"
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return text if len(text) <= 180 else text[:180] + "…"


def _type(value):
    return {dict: "object", list: "array", str: "string", bool: "boolean",
            int: "number", float: "number", type(None): "null"}[type(value)]


def _field_difference(left, right, path):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in left:
            if key not in right:
                return "missing_field", path + [key], True, left[key], False, None
            if not same_json(left[key], right[key]):
                return _field_difference(left[key], right[key], path + [key])
        for key in right:
            if key not in left:
                return "unexpected_field", path + [key], False, None, True, right[key]
    if isinstance(left, list) and isinstance(right, list):
        for index, (a, b) in enumerate(zip(left, right)):
            if not same_json(a, b):
                return _field_difference(a, b, path + [index])
        index = min(len(left), len(right))
        if len(left) > len(right):
            return "missing_item", path + [index], True, left[index], False, None
        if len(right) > len(left):
            return "unexpected_item", path + [index], False, None, True, right[index]
    code = "type_mismatch" if _type(left) != _type(right) else "value_mismatch"
    return code, path, True, left, True, right


def comparison_feedback(expected, actual):
    index = first_difference(expected, actual)
    if index is None:
        return None
    if index >= len(actual):
        diff = "missing_message", [], True, expected[index], False, None
    elif index >= len(expected):
        diff = "unexpected_message", [], False, None, True, actual[index]
    else:
        diff = _field_difference(expected[index], actual[index], [])
    code, path, has_expected, left, has_actual, right = diff
    evidence = {"message_index": index, "field_path": path,
                "expected_present": has_expected, "actual_present": has_actual}
    for side, present, value in [("expected", has_expected, left), ("actual", has_actual, right)]:
        if present:
            evidence[side + "_type"] = _type(value)
            evidence[side + "_preview"] = _preview(value)
    location = f"第 {index + 1} 条消息"
    if path:
        location += "，字段路径 " + json.dumps(path, ensure_ascii=False)
    observation = (location + "：预期 " + (evidence.get("expected_preview", "不存在"))
                   + "；实际 " + evidence.get("actual_preview", "不存在"))
    if code == "type_mismatch":
        observation += f"（类型 {evidence['expected_type']} → {evidence['actual_type']}）"
    return {"code": code, "observation": observation, "evidence": evidence,
            "next_steps": ["先核对该用例的独立协议依据与预期输出。",
                           "检查适配器的字段映射，再用保存的原始分块重放并检查解析状态。"],
            "limit": "这里只定位首个可观察差异，不能据此确定协议缺陷的根因；不检查每次 feed 的输出时机。"}


def error_feedback(code, reason, detail=None):
    evidence = {"stage": "unknown", "chunk_index": None, "actual_complete": False}
    stages = {"request": "读取运行请求", "adapter_load": "加载适配器或创建解析器",
              "reset": "重置解析器", "feed": "投喂输入", "output_validate": "检查输出格式"}
    if isinstance(detail, dict):
        if isinstance(detail.get("stage"), str) and detail["stage"] in stages:
            evidence["stage"] = detail["stage"]
        chunk = detail.get("chunk_index")
        if type(chunk) is int and chunk >= 0:
            evidence["chunk_index"] = chunk
        if isinstance(detail.get("exception_type"), str):
            evidence["exception_type"] = detail["exception_type"]
        location = detail.get("location")
        if (isinstance(location, dict) and isinstance(location.get("file"), str)
                and isinstance(location.get("function"), str)
                and type(location.get("line")) is int and location["line"] > 0):
            evidence["location"] = {key: location[key] for key in ("file", "line", "function")}
    observation = reason
    if evidence["stage"] in stages:
        observation += "；阶段：" + stages[evidence["stage"]]
    if evidence["chunk_index"] is not None:
        observation += f"；输入分块 {evidence['chunk_index'] + 1}"
    location = evidence.get("location")
    if location:
        observation += f"；位置 {location['file']}:{location['line']}（{location['function']}）"
    if code == "timeout":
        steps = ["在保存的输入上检查适配器初始化、reset 和 feed 是否存在等待或死循环；确认耗时依据后再调整超时。"]
    elif code == "process_exit":
        steps = ["用保存的输入在本地调试适配器或原生库，检查进程退出原因。"]
    elif evidence["stage"] == "output_validate":
        steps = ["检查 feed 返回值：应为 JSON 对象列表，数值必须有限，累计输出不超过 10000 条。"]
    else:
        steps = ["按上述阶段与位置检查适配器、依赖和原解析器，再用同一输入重放。"]
    return {"code": code, "observation": observation, "evidence": evidence,
            "next_steps": steps,
            "limit": "运行未完成；已记录的输出可能只有一部分，不能作为通过依据。超时或进程退出时无法确定内部阶段与分块。"}
