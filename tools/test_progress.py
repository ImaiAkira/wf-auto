# -*- coding: utf-8 -*-
"""离线单测：通用进度账本 + 外传关卡列表解析 + 「下一个该做什么」选择。

不需要游戏、不需要 maa 运行环境，直接跑：

    python tools/test_progress.py

里面用的 OCR 文本/坐标，来自真机截图 ax6.png（百兽王冠 关卡列表）的全量 OCR 转储。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import progress as ledger  # noqa: E402
import stage_rows as sr  # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# ax6.png（百兽王冠 关卡列表）的真实 OCR 结果
#   行1 NEW   前往圣地     特殊战斗（剧情/特殊行，需长按）
#   行2 COMPLETE!! 提欧与玛格诺斯 STORY（纯剧情行）
#   行3 COMPLETE!! 秘宝之力 战斗（战斗行）
# ---------------------------------------------------------------------------
AX6_ITEMS: list[tuple[str, list[int]]] = [
    ("1999/92", [115, 20, 80, 26]),
    ("597,835", [510, 18, 96, 28]),
    ("百兽王冠", [67, 261, 592, 176]),
    ("Crown of The Beast King", [283, 421, 358, 43]),
    ("领主战", [423, 606, 62, 26]),
    ("剧情", [532, 605, 45, 27]),
    ("道具", [633, 625, 44, 23]),
    ("兑换", [635, 605, 40, 21]),
    ("NEW", [14, 673, 54, 25]),
    ("首次报酬", [541, 688, 83, 26]),
    ("前往圣地", [202, 722, 114, 34]),
    ("特殊战斗", [78, 785, 53, 19]),
    ("推荐属性", [207, 774, 94, 24]),
    ("水", [320, 776, 33, 21]),
    ("体力", [367, 778, 41, 20]),
    ("10", [450, 777, 26, 23]),
    ("COMPLETE!!", [15, 818, 123, 23]),
    ("蘭", [66, 856, 72, 53]),
    ("STORY", [202, 844, 73, 18]),
    ("提欧与玛格诺斯", [202, 896, 200, 32]),
    ("COMPLETE!!", [15, 962, 123, 23]),
    ("秘宝之力", [201, 1030, 115, 34]),
    ("战斗", [87, 1076, 32, 16]),
    ("推荐编成", [55, 1105, 97, 29]),
    ("推荐属性", [209, 1109, 84, 24]),
    ("水", [324, 1110, 30, 22]),
    ("体力", [365, 1108, 46, 25]),
    ("8", [459, 1110, 17, 20]),
    ("COMPLETE!!", [14, 1153, 126, 23]),
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 45, 27]),
    ("商店", [397, 1245, 45, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
]


def test_ledger() -> None:
    print("\n== 1. 通用进度账本 progress.Progress ==")
    with tempfile.TemporaryDirectory() as d:
        p = ledger.Progress(Path(d) / "progress.json")
        keys = [
            "side_story/百兽王冠/前往圣地",
            "side_story/百兽王冠/提欧与玛格诺斯",
            "side_story/百兽王冠/秘宝之力",
        ]

        check("初始 next_of = 第 1 关", p.next_of(keys) == keys[0])
        check("初始 is_done 全 False", not any(p.is_done(k) for k in keys))

        check("mark_done 第 1 关返回新增 True", p.mark_done(keys[0]) is True)
        check("重复 mark_done 返回 False", p.mark_done(keys[0]) is False)
        check("done 后 next_of 前进到第 2 关", p.next_of(keys) == keys[1])

        # 持久化：新实例读同一文件必须记得
        p2 = ledger.Progress(Path(d) / "progress.json")
        check("跨实例持久：第 1 关仍为 done", p2.is_done(keys[0]) is True)
        check("跨实例持久：next_of 仍为第 2 关", p2.next_of(keys) == keys[1])

        p.mark_done(keys[1])
        p.mark_done(keys[2])
        check("全部 done 后 next_of = None", p.next_of(keys) is None)

        # 顺序语义：next_of 按传入顺序给第一个未完成
        p.reset()
        check("reset 后 next_of 回到第 1 关", p.next_of(["side_story/百兽王冠/秘宝之力", keys[0]]) == "side_story/百兽王冠/秘宝之力")

        # key 规范化：空白不能造成两条
        p.mark_done("side_story/百兽王冠/前往 圣地")
        check("含空格的 key 与无空格等价", p.is_done("side_story/百兽王冠/前往圣地") is True)
        check("scope() 前缀过滤", set(p.scope("side_story/百兽王冠")) == {keys[0]})

        n = p.reset("side_story/百兽王冠")
        check("reset(prefix) 只清该前缀", n == 1 and p.all_keys() == [])

        # pending：next_stage 选中谁，mark_done 就记谁
        ledger.set_pending("百兽王冠", "前往圣地")
        got = ledger.get_pending("百兽王冠")
        check("pending 往返", got == ("百兽王冠", "前往圣地"))
        popped = ledger.pop_pending("百兽王冠")
        check("pop_pending 读取并清除", popped == ("百兽王冠", "前往圣地") and ledger.get_pending("百兽王冠") is None)


def test_parse() -> None:
    print("\n== 2. 外传关卡列表解析 parse_side_rows(ax6) ==")
    rows = sr.parse_side_rows(AX6_ITEMS)
    names = [r["name"] for r in rows]
    types = {r["name"]: r["type"] for r in rows}
    badges = {r["name"]: r["badge"] for r in rows}
    print(f"   解析到 {len(rows)} 行：")
    for r in rows:
        print(f"     - {r['name']!r:24} type={r['type']!r:8} badge={r['badge']!r:12} box={r['title_box']}")

    check("解析出 3 行", len(rows) == 3)
    check("顺序：前往圣地 -> 提欧与玛格诺斯 -> 秘宝之力",
          names == ["前往圣地", "提欧与玛格诺斯", "秘宝之力"])
    check("前往圣地 = 特殊战斗", types.get("前往圣地") == "特殊战斗")
    check("提欧与玛格诺斯 = STORY", types.get("提欧与玛格诺斯") == "STORY")
    check("秘宝之力 = 战斗", types.get("秘宝之力") == "战斗")
    check("前往圣地徽标 = NEW", badges.get("前往圣地") == "NEW")
    check("秘宝之力徽标 = COMPLETE!!", badges.get("秘宝之力", "").startswith("COMPLETE"))
    check("前往圣地标题框正确", [r for r in rows if r["name"] == "前往圣地"][0]["title_box"] == [202, 722, 114, 34])


def _simulate_next_stage(rows, row_type, done, check_badge=True):
    """直接调用生产同款纯函数 select_side_stage（保证测试与运行不分叉）。"""
    return sr.select_side_stage(rows, row_type_regex=row_type, check_badge=check_badge,
                                is_done=lambda n: n in done)


def test_pick() -> None:
    print("\n== 3. 账本驱动选关（复刻 next_stage 逻辑） ==")
    rows = sr.parse_side_rows(AX6_ITEMS)

    # 场景 A：账本空 —— 剧情行节点应选中「前往圣地」
    r = _simulate_next_stage(rows, "特殊战斗", set())
    check("空账本：特殊战斗节点 -> 前往圣地", r is not None and r["name"] == "前往圣地")

    # 场景 B：账本已记「前往圣地」—— 剧情行节点不再返回它（不会重复长按）
    done = {sr.normalize_key("前往圣地")}
    r = _simulate_next_stage(rows, "特殊战斗", done)
    check("已记 前往圣地：特殊战斗节点 -> None（不再重复）", r is None)

    # 场景 C：负样本（关键）—— 账本已记「秘宝之力」完成时，战斗节点不得命中
    done = {sr.normalize_key("秘宝之力")}
    r = _simulate_next_stage(rows, "战斗", done, check_badge=True)
    check("已记 秘宝之力：战斗节点 -> None（防重复打同一关）", r is None)

    # 反证：如果【不】看账本，战斗节点本来会命中秘宝之力（说明防线确实是账本/徽标）
    r_no_ledger = _simulate_next_stage(rows, "战斗", set(), check_badge=True)
    check("不看账本、只在列表上：战斗行被 COMPLETE 徽标挡住 -> None",
          r_no_ledger is None)
    r_raw = sr.pick_side_next(rows, row_type_regex="战斗", is_done=None)
    check("完全不设防时战斗节点本会命中秘宝之力（反证）",
          r_raw is not None and r_raw["name"] == "秘宝之力")

    # 场景 D：纯账本防线（关掉徽标检查）—— 空账本命中，记账后不命中
    r = _simulate_next_stage(rows, "战斗", set(), check_badge=False)
    check("关徽标检查+空账本：战斗节点 -> 秘宝之力", r is not None and r["name"] == "秘宝之力")
    r = _simulate_next_stage(rows, "战斗", {sr.normalize_key("秘宝之力")}, check_badge=False)
    check("关徽标检查+已记账：战斗节点 -> None（账本这才是关键防线）", r is None)

    # 场景 E：STORY 行
    r = _simulate_next_stage(rows, "STORY", set(), check_badge=False)
    check("STORY 节点 -> 提欧与玛格诺斯", r is not None and r["name"] == "提欧与玛格诺斯")

    # 场景 F：徽标↔行配对失败（该行徽标为空）—— 绝不能当「该做」
    rows_badpair = [dict(r) for r in rows]
    for r in rows_badpair:
        if r["name"] == "前往圣地":
            r["badge"] = ""   # 模拟配对失败：NEW 行没配上任何徽标
    r = _simulate_next_stage(rows_badpair, "特殊战斗", set())
    check("★配对失败（NEW 行徽标为空）：节点 -> None（不把无徽标行当该做）", r is None)

    # 场景 G：徽标被误配成 COMPLETE（即使它其实是未完成行）—— 也必须被挡
    rows_wrong = [dict(r) for r in rows]
    for r in rows_wrong:
        if r["name"] == "前往圣地":
            r["badge"] = "COMPLETE!!"
    r = _simulate_next_stage(rows_wrong, "特殊战斗", set())
    check("★徽标读成 COMPLETE：节点 -> None（宁可漏也不重复打）", r is None)

    # 场景 H：账本落盘 + 稳定键 —— 手动标 done 后不再被选中（连徽标读错也挡得住）
    with tempfile.TemporaryDirectory() as d:
        led = ledger.Progress(Path(d) / "p.json")
        rows_new = [dict(r) for r in rows]
        for r in rows_new:  # 假装徽标全读错了：全部当成 NEW
            r["badge"] = "NEW"
        r0 = sr.select_side_stage(
            rows_new, row_type_regex="特殊战斗", check_badge=True,
            is_done=lambda n: led.is_done(sr.side_stage_key("side_story", n)))
        check("徽标全读错成 NEW + 空账本 -> 仍选中 前往圣地",
              r0 is not None and r0["name"] == "前往圣地")
        led.mark_done(sr.side_stage_key("side_story", "前往圣地"))
        r1 = sr.select_side_stage(
            rows_new, row_type_regex="特殊战斗", check_badge=True,
            is_done=lambda n: led.is_done(sr.side_stage_key("side_story", n)))
        check("★手动标 done 后（稳定键）-> None（连徽标读错也挡得住重复）", r1 is None)
        check("progress.json 真的落盘", (Path(d) / "p.json").is_file())
        check("稳定键不含 scope = side_story/前往圣地",
              sr.side_stage_key("side_story", "前往圣地") == "side_story/前往圣地")


def test_page_done() -> None:
    print("\n== 4. 「本页全清」判据 side_list_all_done ==")
    # ax6 = 有 NEW 的关卡列表（未清）-> False
    check("ax6（含 NEW）-> 未全清", sr.side_list_all_done(AX6_ITEMS) is False)
    # 去掉 NEW 徽标后（= 现场 stuck1 的结构：只有 COMPLETE）-> True
    no_new = [(t, b) for (t, b) in AX6_ITEMS if not t.startswith("NEW")]
    check("去掉 NEW 后（只剩 COMPLETE）-> 全清", sr.side_list_all_done(no_new) is True)
    # 普通页面（无任何徽标）-> False
    check("无徽标页面 -> 非全清（不会误触发出口）",
          sr.side_list_all_done([("修行之道", [10, 10, 80, 20])]) is False)


def test_default_ledger_path_is_stable() -> None:
    """账本默认落盘位置必须【与进程 CWD 无关】——否则断点续跑会读错文件。"""
    print("\n== 5. 默认账本路径：不依赖 CWD（固定 = agent 包上一级） ==")
    saved = os.environ.pop("MAA_PROGRESS_FILE", None)
    cwd0 = os.getcwd()
    try:
        p0 = ledger._default_file()
        expect = AGENT_DIR.parent / ledger.DEFAULT_FILENAME
        check("默认路径 = agent 包上一级 / progress.json", p0 == expect, f"{p0}")
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                p1 = ledger._default_file()
                check("切到临时 CWD 后路径不变（不会写到 CWD）", p1 == p0, f"{p1}")
                check("默认路径不是 CWD 下的 progress.json",
                      Path(os.getcwd()) / ledger.DEFAULT_FILENAME != p0)
            finally:
                # ★先切回原 CWD★：Windows 上 CWD 被占用时 TemporaryDirectory 清理会失败。
                os.chdir(cwd0)
        # 环境变量仍优先（测试/调试用）
        os.environ["MAA_PROGRESS_FILE"] = str(Path(tempfile.gettempdir()) / "ovr.json")
        check("MAA_PROGRESS_FILE 覆盖仍然生效",
              ledger._default_file() == Path(tempfile.gettempdir()) / "ovr.json")
    finally:
        os.chdir(cwd0)
        os.environ.pop("MAA_PROGRESS_FILE", None)
        if saved is not None:
            os.environ["MAA_PROGRESS_FILE"] = saved


def main() -> None:
    print("=" * 70)
    print("离线单测：progress.py / stage_rows.py（不依赖游戏与 maa runtime）")
    print("=" * 70)
    test_ledger()
    test_parse()
    test_pick()
    test_page_done()
    test_default_ledger_path_is_stable()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅  （账本『不重复打同一关』已被直接验证）")


if __name__ == "__main__":
    main()
