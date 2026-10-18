# -*- coding: utf-8 -*-
"""#24：归位状态机必须【先账号确认页、后标题页】——顺序锁。

seam：``tools/live_harness.py`` 的 ``ensure_main_city`` 页面 -> 动作有序表
``RETURN_HOME_RULES``。

背景（#13 第 3 次运行、设备实证）
--------------------------------
账号确认页（「星点启程」弹窗）是一张**盖在标题页上的弹窗**：弹窗背后标题页的大字
「点击开始」会一起被 OCR 读到（#13 证据 ``10_acctconfirm_155418.png``：弹窗底部透出
「点击开始」，提示文案里也含「点击开始」）。旧实现先判标题页，于是点在弹窗挡住的
假「点击开始」上，归位 10 步全败、最后只能人工把设备拉回主城。

真机正确顺序（与 #20 ``phantom_restart`` 一致）：

    账号确认页 →「继续游戏」→ 标题页 →「点击开始」→ 主城

两个守卫（都在本文件里，prove-red 也在本文件里）：

1. ``return-home-account-confirm-before-title`` —— 有序表里 ``account_confirm`` 必须
   排在 ``title`` 之前，且两条判据确实分别绑定到「继续游戏」「点击开始」；再用真机语义的
   合成 OCR（账号确认页 = 同时含「继续游戏」与「点击开始」两框）跑一次「取首个命中」的
   分派，必须选中 ``account_confirm``（点「继续游戏」），绝不能选中 ``title``。
2. ``return-home-state-machine-driven-by-table`` —— ``ensure_main_city`` 确实按这张有序表
   分派（否则表只是装饰，顺序改了也没用）。

★prove-red★（``python tools\\contract_hooks\\hooks_24.py``）：
   * 把有序表整体颠倒 -> 守卫 1 变红（首个命中从 account_confirm 变成 title）；
   * 抹掉 ``ensure_main_city`` 对有序表的使用 -> 守卫 2 变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# ★只 append 到 sys.path 末尾★（同 hooks_20）：prove-red 用 PYTHONPATH 抢先塞坏副本时，
# 副本仍优先命中，不被真实的 live_harness 盖掉。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

#: 真机语义的合成 OCR：账号确认页**同时**含「继续游戏」（真按钮）与「点击开始」（弹窗背后
#: 标题页透出的假按钮）。这正是旧实现会点错的画面。
_BOX_ACCOUNT = [300, 820, 120, 60]   # 720 空间，弹窗里的「继续游戏」
_BOX_TITLE = [250, 1150, 220, 60]    # 720 空间，标题页的大字「点击开始」
ACCOUNT_CONFIRM_ITEMS = [("继续游戏", _BOX_ACCOUNT), ("点击开始", _BOX_TITLE)]
TITLE_ITEMS = [("点击开始", _BOX_TITLE)]
ONLY_ACCOUNT_ITEMS = [("继续游戏", _BOX_ACCOUNT)]


# ---------------------------------------------------------------------------
# 有序表的【唯一来源】：tools/live_harness.py
# ---------------------------------------------------------------------------
def rules() -> list:
    """返回 live_harness 的归位有序表 ``RETURN_HOME_RULES``（['rule_id', probe, act]）。"""
    import live_harness as ca

    return [tuple(item) for item in ca.RETURN_HOME_RULES]


def rule_ids() -> list[str]:
    return [rid for rid, _probe, _act in rules()]


def _probe_for(rules_, rid: str):
    for item in rules_:
        if item[0] == rid:
            return item[1]
    return None


def _first_rule(rules_, items) -> str | None:
    """模拟 ensure_main_city 的分派：按顺序取首个命中判据的 rule_id。"""
    for rid, probe, _act in rules_:
        if probe(items):
            return rid
    return None


def order_error(rules_) -> str | None:
    """有序表顺序 / 判据绑定的错误描述；None 表示正确（账号确认页先于标题页）。"""
    ids = [rid for rid, _p, _a in rules_]
    if "account_confirm" not in ids or "title" not in ids:
        return f"有序表缺少 account_confirm / title：{ids}"
    if ids.index("account_confirm") > ids.index("title"):
        return (
            f"账号确认页排在标题页之后：{ids}——弹窗背后的假「点击开始」会先被点到"
            "（#13 第 3 次运行归位全败的根因）"
        )

    acct = _probe_for(rules_, "account_confirm")
    title = _probe_for(rules_, "title")
    if acct is None or not acct(ONLY_ACCOUNT_ITEMS) or acct(TITLE_ITEMS):
        return "account_confirm 判据没有绑定到『继续游戏』"
    if title is None or not title(TITLE_ITEMS) or title(ONLY_ACCOUNT_ITEMS):
        return "title 判据没有绑定到『点击开始』"
    return None


def _ensure_source() -> str:
    import inspect

    import live_harness as ca

    return inspect.getsource(ca.ensure_main_city)


def _source_uses_table(source: str) -> bool:
    """源码是否真的用有序表分派（而不是又写回内联 if 链）。"""
    return "RETURN_HOME_RULES" in source


# ---------------------------------------------------------------------------
# 守卫 1：顺序锁
# ---------------------------------------------------------------------------
def probe_account_confirm_before_title() -> bool:
    """#24 守卫 1：account_confirm 先于 title，且真机语义下首个命中就是「继续游戏」。"""
    rules_ = rules()
    if order_error(rules_) is not None:
        return False
    return _first_rule(rules_, ACCOUNT_CONFIRM_ITEMS) == "account_confirm"


# ---------------------------------------------------------------------------
# 守卫 2：状态机确实按有序表分派（顺序改了才有效）
# ---------------------------------------------------------------------------
def probe_state_machine_driven_by_table() -> bool:
    """#24 守卫 2：ensure_main_city 确实消费 RETURN_HOME_RULES，否则顺序锁是装饰。"""
    return _source_uses_table(_ensure_source())


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_24.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """真实绿；把有序表颠倒 -> 守卫 1 红；抹掉对有序表的使用 -> 守卫 2 红。"""
    print("hooks_24 prove-red：两处破坏，要求两个守卫各自变红")
    green = (
        probe_account_confirm_before_title() is True
        and probe_state_machine_driven_by_table() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：账号确认页先于标题页 + 按表分派（绿）")
    if not green:
        return False

    # (a) 顺序颠倒 -> 守卫 1 红（首个命中变成 title）。
    reversed_rules = list(reversed(rules()))
    err = order_error(reversed_rules)
    first = _first_rule(reversed_rules, ACCOUNT_CONFIRM_ITEMS)
    red_order = err is not None and first == "title"
    tail = f"  {err}" if err else "  （守卫没抓到！）"
    print(f"  [{'PASS' if red_order else 'FAIL'}] 有序表颠倒 -> {'红' if red_order else '仍绿'}"
          f"（首个命中={first}）{tail}")

    # (b) 抹掉 ensure_main_city 对有序表的使用 -> 守卫 2 红。
    stripped = "def ensure_main_city(watcher, max_steps=10):\n    return False\n"
    red_source = _source_uses_table(stripped) is False
    print(f"  [{'PASS' if red_source else 'FAIL'}] 状态机不再走有序表 -> "
          f"{'红' if red_source else '仍绿'}")

    ok = green and red_order and red_source
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-account-confirm-before-title",
        "#24",
        "归位有序表里 account_confirm（继续游戏）必须排在 title（点击开始）之前（缺一即红）",
        probe_account_confirm_before_title,
    ),
    (
        "return-home-state-machine-driven-by-table",
        "#24",
        "ensure_main_city 按 RETURN_HOME_RULES 有序表分派（顺序改了才有效）",
        probe_state_machine_driven_by_table,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
