"""扭蛋（抽卡）的页面判据 —— **纯函数、不导入 maa**（离线测试可直接 import）。

判据真机来源（2026-10-19，127.0.0.1:16385 / 16448，1080x1920）：

* **池子页** = 「1次抽取」+「10连抽取」两个按钮同时在屏。
* **汇总页** = 「前往 / 扭蛋首页」—— ★这是汇总页唯一恒定的标志★。
  「继续 10连抽取」**不一定有**：券用完 / 池子不支持连抽时它就不显示
  （16448 装备扭蛋真机实测：抽完只剩「前往扭蛋首页」）。
* 揭示页只有「跳过」/「全部跳过」，两条判据都不命中 → 不计数、不误停。

★为什么要「1次抽取」★：池子页和汇总页**都**有「10连抽取」四个字，只认它会把汇总页
当成池子页误点。汇总页没有「1次抽取」，这一条把两页分开。
"""

from __future__ import annotations

import re

_RE_ONCE = re.compile(r"1\s*次抽\s*取")
_RE_TEN = re.compile(r"10\s*连抽\s*取")
#: 汇总页的恒定标志：右下角「前往 / 扭蛋首页」（两行字，OCR 给「扭蛋首页」那一行即可）。
_RE_HOME = re.compile(r"扭蛋首页")


def texts(items) -> list[str]:
    """OCR 结果 -> 纯文本列表（去掉空串/空白）。"""
    return [str(t or "").strip() for t, _b in (items or [])]


def is_summary_page(items) -> bool:
    """汇总页 = 屏上有「扭蛋首页」（★不要求「继续」—— 券用完时它不存在★）。"""
    ts = texts(items)
    return any(_RE_HOME.search(t) for t in ts)


def has_continue(items) -> bool:
    """汇总页上有没有「继续 10连抽取」这颗连抽按钮（没有就只能收工，绝不换池）。"""
    return any(str(t or "").strip() == "继续" for t, _b in (items or []))


def is_pool_page(items) -> bool:
    """池子页 = 「1次抽取」+「10连抽取」（汇总页没有「1次抽取」）。"""
    ts = texts(items)
    return any(_RE_ONCE.search(t) for t in ts) and any(_RE_TEN.search(t) for t in ts)


__all__ = ["has_continue", "is_pool_page", "is_summary_page", "texts"]
