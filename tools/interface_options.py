# -*- coding: utf-8 -*-
"""界面选项 → pipeline_override 的**产品等价**解析（#56 coop-fix2）。

为什么需要它（审计 P0）
-----------------------
``tools/run_wuchong_live.py`` 过去**从不应用界面选项** —— 直接把任务名交给 Tasker，
于是「游戏模式」「是否手操」「是否自动续战」「手操节奏参数」全都不生效：
pipeline 只能用 **raw 默认**（两张模式卡都开着、自动节点是 raw 的 off→on、手操引擎
按 raw 定义跑）。审计的结论是**「从一个不应用选项的 driver 跑出来的任何一次，都不具
代表性」**（那次跑成了单人；手操引擎「跑了但没点」，因为 ``manual`` 恒为 off）。

MFAAvalonia 拉起任务时，按任务的 ``option`` 列表**逐项**选中 case，把每个 case 的
``pipeline_override`` 叠加到运行覆盖里（``input`` 选项额外做 ``{字段}`` 替换 + 按
``pipeline_type`` 定型）。本模块把这条缝**原样**实现，供真机 runner 与产品走同一条路。

只读 ``assets/interface.json``；不导入 maa / 不触设备（离线可单测）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def strip_jsonc(text: str) -> str:
    """去掉 JSONC 的 ``//`` 与 ``/* */`` 注释（保持字符串内容），供读 interface.json。"""
    out: list[str] = []
    state = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i:i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i:i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i:i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def load_interface(project: str | Path) -> dict:
    path = Path(project) / "assets" / "interface.json"
    return json.loads(strip_jsonc(path.read_text(encoding="utf-8")))


def _deep_merge(dst: dict, src: dict) -> dict:
    """把 ``src`` 深合并进 ``dst``（src 优先，dict 递归）；返回 ``dst``。"""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _subst(obj, values: dict, kinds: dict):
    """把 ``"{字段}"`` 整串占位符替换为输入值；``int`` 型按 int 定型。"""
    if isinstance(obj, dict):
        return {k: _subst(v, values, kinds) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, values, kinds) for v in obj]
    if isinstance(obj, str):
        m = re.fullmatch(r"\{([^{}]+)\}", obj)
        if m:
            key = m.group(1)
            val = values.get(key, obj)
            if kinds.get(key) == "int":
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return val
            return val
        return obj
    return obj


def option_override(iface: dict, option: str, case: str | None = None,
                    inputs: dict | None = None) -> dict:
    """解析某选项的 pipeline_override（``select`` 取 case，``input`` 取 inputs + 替换）。

    ``case=None`` → 取该选项的 ``default_case``（产品的默认选中项）。
    """
    block = (iface.get("option") or {}).get(option)
    if block is None:
        raise SystemExit(f"interface.json 里没有选项 {option!r}")
    if block.get("type") == "input" or block.get("inputs"):
        values = {i["name"]: str(i.get("default")) for i in block.get("inputs") or []}
        kinds = {i["name"]: (i.get("pipeline_type") or "") for i in block.get("inputs") or []}
        values.update({k: str(v) for k, v in (inputs or {}).items()})
        return dict(_subst(block.get("pipeline_override") or {}, values, kinds))
    cases = {c.get("name"): c for c in block.get("cases") or []}
    name = case or block.get("default_case")
    if name not in cases:
        raise SystemExit(f"选项 {option!r} 没有 case {name!r}（有：{sorted(cases)}）")
    return dict(cases[name].get("pipeline_override") or {})


def resolve_task_override(
    project: str | Path,
    task: str,
    selections: dict | None = None,
    inputs: dict | None = None,
    extra_options: tuple[str, ...] = (),
) -> dict:
    """按任务的 ``option`` 列表**顺序**叠加各选项 case 的 pipeline_override（= 产品的行为）。

    selections：{option 名 -> case 名}；未列出的选项取 ``default_case``（产品默认选中）。
    inputs：{字段名 -> 值} 供 ``input`` 型选项替换。
    extra_options：任务列表之外、但产品运行态也会施加的**全局**选项（本线：是否自动续战）。
    返回合并后的 override（可直接喂 ``Tasker.post_task``）。
    """
    iface = load_interface(project)
    tasks = {t.get("name"): t for t in iface.get("task") or []}
    if task not in tasks:
        raise SystemExit(f"interface.json 里没有任务 {task!r}")
    selections = dict(selections or {})
    listed = list(tasks[task].get("option") or [])
    order = listed + [o for o in extra_options if o not in listed]
    out: dict = {}
    for opt_name in order:
        case = selections.get(opt_name)
        _deep_merge(out, option_override(iface, opt_name, case, inputs))
    return out
