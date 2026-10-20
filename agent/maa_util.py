"""自定义识别/动作的公共小工具。

刻意【不导入 maa.agent】（也不导入 numpy / Context）：
这样既能在 AgentServer 进程里用，也能被离线/真机测试脚本安全导入
（一旦 import maa.agent，native 库会切到 MaaAgentServer，Resource() 直接创建失败）。
"""

from __future__ import annotations

import json


def read_param(argv) -> dict:
    """解析 custom_recognition_param / custom_action_param（JSON 字符串）。"""
    try:
        return json.loads(getattr(argv, "custom_recognition_param", None) or "{}") or {}
    except (TypeError, ValueError):
        return {}


def read_action_param(argv) -> dict:
    try:
        return json.loads(getattr(argv, "custom_action_param", None) or "{}") or {}
    except (TypeError, ValueError):
        return {}


def ocr_all(context, image, entry: str = "OcrTask") -> list[tuple[str, list[int]]]:
    """借用 pipeline 里的 OcrTask 节点做全屏 OCR，返回 [(text, box), ...]。

    box = [x, y, w, h]（720 空间）。
    """
    detail = context.run_recognition(entry, image)
    if detail is None:
        return []
    items: list[tuple[str, list[int]]] = []
    for r in detail.all_results or []:
        box = getattr(r, "box", None)
        if box is None:
            continue
        box = [int(v) for v in box]
        if len(box) != 4:
            continue
        items.append(((getattr(r, "text", "") or "").strip(), box))
    return items


def int_pair(value, default):
    try:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (int(value[0]), int(value[1]))
    except (TypeError, ValueError):
        pass
    return default


def flag(value, default: bool = True) -> bool:
    """把 "0"/"false"/"no"/False 等都当成 False。"""
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "", "off")
    if value is None:
        return default
    return bool(value)
