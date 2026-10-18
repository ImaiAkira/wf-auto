# -*- coding: utf-8 -*-
"""离线单测：批量副本清单解析 + 账本计数（不需要游戏、不需要 maa 运行时）。

直接跑：
    .venv\\Scripts\\python.exe tools\\test_batch_plan.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import batch_plan as bp  # noqa: E402
import progress as ledger  # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_parse_normal() -> None:
    print("\n== 1. 正常清单解析 ==")
    text = (
        "# 副本名,难度,次数\n"
        "猩红巨熊讨伐,中级,3\n"
        "\n"
        "背鳍三兄弟讨伐,高级,5\n"
        "不死王瑞西塔尔讨伐,超级,2\n"
    )
    items, errors = bp.parse_batch(text)
    check("无解析错误", errors == [], f"errors={errors}")
    check("解析出 3 条", len(items) == 3, f"got={len(items)}")
    names = [(i.dungeon, i.difficulty, i.times) for i in items]
    check("顺序与内容正确",
          names == [("猩红巨熊讨伐", "中级", 3),
                    ("背鳍三兄弟讨伐", "高级", 5),
                    ("不死王瑞西塔尔讨伐", "超级", 2)],
          f"got={names}")
    check("高级+ 需要原样保留（不误并到 高级）",
          bp.DIFF_REGEX["高级"] == r"高级$" and bp.DIFF_REGEX["高级+"] == r"高级\+$")


def test_parse_tolerance() -> None:
    print("\n== 2. 容错：中英文逗号 / 全角半角 / 空格 / 空行 / 分号 / 行内注释 ==")
    # 全角逗号 + 全角数字 + 全角加号 + 前后空格
    text = "  猩红巨熊讨伐，中级，３  \n背鳍三兄弟讨伐, 高级＋ ,5\n\n"
    items, errors = bp.parse_batch(text)
    check("全角转半角后无错误", errors == [], f"errors={errors}")
    check("全角数字/加号被规范化",
          [(i.dungeon, i.difficulty, i.times) for i in items]
          == [("猩红巨熊讨伐", "中级", 3), ("背鳍三兄弟讨伐", "高级+", 5)],
          f"got={[(i.dungeon,i.difficulty,i.times) for i in items]}")

    # 分号分隔（防止输入框吃换行）
    text = "猩红巨熊讨伐,中级,1;背鳍三兄弟讨伐,高级,2；不死王瑞西塔尔讨伐,超级,3"
    items, errors = bp.parse_batch(text)
    check("分号（英文/中文）可作条目分隔",
          errors == [] and len(items) == 3, f"items={len(items)} errors={errors}")

    # 行内注释
    items, errors = bp.parse_batch("猩红巨熊讨伐,中级,3   # 备注内容\n")
    check("行内 # 注释被忽略",
          errors == [] and len(items) == 1 and items[0].times == 3, f"errors={errors}")

    # 纯空清单
    for blank in ("", "   ", "\n\n", None):
        items, errors = bp.parse_batch(blank)
        check(f"空清单回退（{blank!r}）→ items/errors 均空",
              items == [] and errors == [], f"items={items} errors={errors}")

    # 只有注释
    items, errors = bp.parse_batch("# 只有注释\n# 还是注释\n")
    check("全注释清单 → 空且无错（=回退单目标）", items == [] and errors == [])


def test_parse_errors() -> None:
    print("\n== 3. 非法行必须明确报错（不静默跳过） ==")
    # 字段数不足
    items, errors = bp.parse_batch("猩红巨熊讨伐,中级\n")
    check("字段不足报错", len(errors) == 1 and items == [], f"errors={errors}")

    # 字段数过多
    _items, errors = bp.parse_batch("猩红巨熊讨伐,中级,3,多了一项\n")
    check("字段过多报错", len(errors) == 1, f"errors={errors}")

    # 难度非法
    _items, errors = bp.parse_batch("猩红巨熊讨伐,地狱,3\n")
    check("难度非法报错", len(errors) == 1 and "难度" in errors[0], f"errors={errors}")

    # 次数非法（0 / 负数 / 非数字）
    for bad in ("0", "-1", "abc", "", "3.5"):
        _items, errors = bp.parse_batch(f"猩红巨熊讨伐,中级,{bad}\n")
        check(f"次数非法「{bad}」报错", len(errors) == 1, f"errors={errors}")

    # 副本名为空
    _items, errors = bp.parse_batch(",中级,3\n")
    check("副本名为空报错", len(errors) == 1, f"errors={errors}")

    # 混合：合法 + 非法 → 非法被报出，且合法项仍被保留（调用方见 errors 即终止）
    items, errors = bp.parse_batch("猩红巨熊讨伐,中级,3\n坏行\n背鳍三兄弟讨伐,高级,5\n")
    check("混合清单：合法项保留 + 非法行 1 条报错",
          len(items) == 2 and len(errors) == 1, f"items={len(items)} errors={errors}")
    check("报错信息含行号与原因", "第 2 段" in errors[0] and "格式错误" in errors[0], f"{errors[0]}")


def test_dedupe() -> None:
    print("\n== 4. 同名同难度去重（次数相加，保留首次顺序） ==")
    text = "猩红巨熊讨伐,中级,3\n背鳍三兄弟讨伐,高级,1\n猩红巨熊讨伐,中级,2\n"
    items, errors = bp.parse_batch(text)
    check("去重后 2 条", errors == [] and len(items) == 2, f"items={len(items)}")
    check("同名同难度次数相加 = 5",
          items[0].dungeon == "猩红巨熊讨伐" and items[0].times == 5,
          f"got={items[0].times if items else None}")
    check("同名不同难度不合并",
          len(bp.parse_batch("猩红巨熊讨伐,中级,1\n猩红巨熊讨伐,高级,1\n")[0]) == 2)


def test_ledger_counts() -> None:
    print("\n== 5. 账本计数 / 续跑 / 不重复 ==")
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "batch_progress.json")
        items, errors = bp.parse_batch(
            "猩红巨熊讨伐,中级,2\n背鳍三兄弟讨伐,高级,3\n"
        )
        check("解析 2 条", errors == [] and len(items) == 2)

        a, b = items
        check("初始 next_item = 第 1 个", bp.next_item(items) is a)
        check("初始 remaining(第1) = 2", bp.remaining(a) == 2)
        check("初始 remaining(第2) = 3", bp.remaining(b) == 3)

        # 第一个目标打 2 次 → 应该跳到第二个
        ledger.mark_done(bp.item_key(a, 1))
        ledger.mark_done(bp.item_key(a, 2))
        check("第1个打够 2 次后 remaining=0", bp.remaining(a) == 0)
        check("next_item 前进到第 2 个", bp.next_item(items) is b)

        # 一个目标打够后，再跑 next_item 不应回到第 1 个（防重复）
        check("打够的目标不会被重复选中（账本生效）",
              bp.next_item(items) is b and a is not bp.next_item(items))

        ledger.mark_done(bp.item_key(b, 1))
        ledger.mark_done(bp.item_key(b, 2))
        ledger.mark_done(bp.item_key(b, 3))
        check("全部打够 next_item = None", bp.next_item(items) is None)

        # 持久化：新读一次账本仍记得
        check("账本落盘可续跑（scope 计数=目标次数）",
              bp.count_done(bp.item_prefix(a)) == 2 and bp.count_done(bp.item_prefix(b)) == 3)

        # 关键：key 规范化后，打第 3 次（越界）也不会算进第 1 个目标
        ledger.mark_done(bp.item_key(a, 3))
        check("同一个目标多记的场次也被正确统计", bp.count_done(bp.item_prefix(a)) == 3)

        # 关键：两个目标的账本前缀互不串台
        check("不同目标账本互不影响",
              bp.count_done(bp.item_prefix(b)) == 3)


def test_joss_tab() -> None:
    print("\n== 6. 降临讨伐 tab 识别 ==")
    check("降临副本被识别为 joss", bp.is_joss("不死王瑞西塔尔讨伐") is False and bp.is_joss("无猾机兵") is True)
    check("领主战副本不是 joss", bp.is_joss("猩红巨熊讨伐") is False)


def test_kind_detection() -> None:
    print("\n== 7. 副本「种类」判定（领主战/降临=farm/raid 合并核心） ==")
    check("猩红巨熊讨伐 → special", bp.detect_kind("猩红巨熊讨伐") == "special")
    check("无猾机兵 → special（降临讨伐）", bp.detect_kind("无猾机兵") == "special")
    check("光之迷宫 → farm", bp.detect_kind("光之迷宫") == "farm")
    check("光之迷宫初级（整名）→ farm", bp.detect_kind("光之迷宫初级") == "farm")
    check("战阵之宴 → raid", bp.detect_kind("战阵之宴") == "raid")
    check("is_farm / is_raid 一致",
          bp.is_farm("光之迷宫") and not bp.is_raid("光之迷宫")
          and bp.is_raid("战阵之宴") and not bp.is_farm("战阵之宴"))


def test_farm_raid_parse() -> None:
    print("\n== 8. farm / raid 清单解析（★#54 迷宫按「域 + 行名」选；raid 难度忽略） ==")
    # ★#54★ 迷宫清单 = `域,行名,次数`（第二字段是【行名】，须属于该域）；行名自含【元素】/Lv../层。
    a, ea = bp.parse_batch("崩坏域,临境域深渊之兽·极,1\n")
    b, eb = bp.parse_batch("幽玄域,幽玄域【1〜3层】,2\n")
    check("域+行名 都无错", ea == [] and eb == [], f"{ea} {eb}")
    check("farm dungeon=域、difficulty(行名)=行名",
          len(a) == 1 and len(b) == 1
          and (a[0].dungeon, a[0].difficulty) == ("崩坏域", "临境域深渊之兽·极")
          and (b[0].dungeon, b[0].difficulty) == ("幽玄域", "幽玄域【1〜3层】"),
          f"a={a} b={b}")
    check("farm 种类 + target=行名 + domain=域",
          a[0].kind == "farm" and a[0].target == "临境域深渊之兽·极" and a[0].domain == "崩坏域")
    check("不同域目标账本 key 不同",
          bp.item_prefix(a[0]) != bp.item_prefix(b[0]))

    # 三个「域」都判为 farm 且合法（用各域首行）；各域的行名都合法。
    for d in bp.MAZE_DOMAINS:
        row = bp.MAZE_ROWS[d][0]
        items, errors = bp.parse_batch(f"{d},{row},1\n")
        check(f"域「{d}」首行「{row}」合法且判为 farm",
              errors == [] and len(items) == 1 and items[0].kind == "farm", f"errors={errors}")
    for row in bp.MAZE_ROWS["崩坏域"]:
        items, errors = bp.parse_batch(f"崩坏域,{row},1\n")
        check(f"崩坏域行「{row}」合法", errors == [] and len(items) == 1, f"errors={errors}")

    # 混合清单：farm + raid + special 各归其类，顺序保留
    items, errors = bp.parse_batch(
        "猩红巨熊讨伐,中级,1\n崩坏域,临境域深渊之兽·极,2\n战阵之宴,-,5\n"
    )
    check("混合清单种类正确",
          errors == [] and [i.kind for i in items] == ["special", "farm", "raid"],
          f"got={[i.kind for i in items]}")

    # raid：难度位写 - 合法；写有效难度也接受（仅忽略）
    items, errors = bp.parse_batch("战阵之宴,-,5\n")
    check("raid 难度位 - 合法", errors == [] and items[0].kind == "raid")
    items, errors = bp.parse_batch("战阵之宴,超级,5\n")
    check("raid 有效难度也接受（忽略）", errors == [] and items[0].kind == "raid")
    # raid 非法难度仍报错（不静默）
    _items, errors = bp.parse_batch("战阵之宴,地狱,5\n")
    check("raid 非法难度报错", len(errors) == 1, f"errors={errors}")

    # ★#54★ farm 的第二字段是【行名】：写旧元素（风）/ 旧难度（中级）都应明确报错。
    _items, errors = bp.parse_batch("宝物域,中级,3\n")
    check("farm 第二字段必须是行名：写「中级」报错（#54：迷宫无难度档）",
          len(errors) == 1 and "行名" in errors[0], f"errors={errors}")
    _items, errors = bp.parse_batch("宝物域,风,3\n")
    check("farm 第二字段必须是行名：写旧元素「风」报错", len(errors) == 1, f"errors={errors}")
    _items, errors = bp.parse_batch("崩坏域,摇曳的迷宫宝物域【火】,3\n")
    check("跨域行名（崩坏域 + 宝物域的行）报错", len(errors) == 1, f"errors={errors}")
    # 旧「元素之迷宫<难度>」整名写法已作废（含难度档 → 非已知域）。
    _items, errors = bp.parse_batch("光之迷宫,中级,3\n")
    check("旧「光之迷宫,中级」写法已不合法（#54）", len(errors) == 1, f"errors={errors}")

    # 同域同行名去重相加
    items, errors = bp.parse_batch("崩坏域,临境域深渊之兽·极,2\n崩坏域,临境域深渊之兽·极,3\n")
    check("同域同行名去重相加 = 5",
          errors == [] and len(items) == 1 and items[0].times == 5, f"got={items}")


def test_orchestrator_offline() -> None:
    """用 stub context 验证 special_batch_plan 的状态机（不连设备、不点游戏）。"""
    print("\n== 9. 指挥官状态机（stub context） ==")
    import json

    import side_impl as si

    class _FakeJob:
        def wait(self):
            return True

    class _FakeController:
        def __init__(self):
            self.clicks = []

        def post_click(self, x, y):
            self.clicks.append((x, y))
            return _FakeJob()

    class _FakeTasker:
        def __init__(self):
            self.controller = _FakeController()

    class _FakeDetail:
        hit = False

    class _FakeContext:
        def __init__(self):
            self.tasker = _FakeTasker()
            self.overrides = []
            self.nexts = []
            self.actions = []   # run_action 记录（点走原生 Click，不再走 post_click）

        def run_recognition(self, entry, image):
            return _FakeDetail()

        def run_action(self, entry, box=None):
            self.actions.append((entry, box))
            return _FakeJob()

        def override_pipeline(self, d):
            self.overrides.append(d)
            return True

        def override_next(self, name, lst):
            self.nexts.append((name, list(lst)))
            return True

    class _FakeTaskDetail:
        def __init__(self, tid, entry="SpecialEntry"):
            self.task_id = tid
            self.entry = entry

    class _FakeArgv:
        def __init__(self, text, tid, box=None, entry="SpecialEntry", reco_param=None):
            if reco_param is not None:
                self.custom_recognition_param = json.dumps(reco_param)
            else:
                self.custom_recognition_param = json.dumps({"list": text})
            self.custom_action_param = "{}"
            self.task_detail = _FakeTaskDetail(tid, entry)
            self.image = None
            self.box = box

    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "orch_progress.json")
        rec = si.SpecialBatchPlanRecognition()
        act = si.SpecialBatchFightAction()

        # 7.1 空清单 → 永远不命中（回退单目标）
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("", 101))
        check("空清单：指挥官不命中（向后兼容）",
              r.box is None and not ctx.overrides, f"box={r.box}")

        # 7.2 非法行 → 明确走 SpecialBatchStop（终止），且打印报错
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("坏行内容", 102))
        nexts = [n for _name, n in ctx.nexts]
        check("非法行：命中并 override_next -> SpecialBatchStop",
              r.box == [0, 0, 0, 0] and ["SpecialBatchStop"] in nexts, f"nexts={nexts}")

        # 7.3 正常单目标：第一次命中即应用 override 并点主城归位
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103))
        check("首个目标：命中（点主城归位）", r.box == [0, 0, 0, 0], f"box={r.box}")
        check("首个目标：override_pipeline 应用了副本/难度",
              len(ctx.overrides) == 1
              and ctx.overrides[0]["SpecialEnterBoss"]["recognition"]["param"]["expected"] == ["猩红巨熊讨伐"]
              and ctx.overrides[0]["SpecialFightTargetRow"]["recognition"]["param"]
                  ["custom_recognition_param"]["difficulty"] == "中级$",
              f"ov={ctx.overrides}")
        check("首个目标：override_next 回 SpecialEntry",
              ctx.nexts and ctx.nexts[-1] == ("SpecialBatchPlan", ["SpecialEntry"]))

        # 7.4 归位后同一目标 → 不命中，交给 pipeline 正常刷
        r = rec.analyze(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103))
        check("归位后：目标未打够 → 不命中，正常刷", r.box is None, f"box={r.box}")

        # 7.5 开打 → 结算 生命周期：开打不计、结算才计，且战斗中绝不切目标
        # 构造真实形状的 box（Rect 兼容对象）
        class _Box:
            x, y, w, h = 180, 1050, 120, 60

        prefix = "special_dungeon_batch/猩红巨熊讨伐/中级"
        fin = si.SpecialBatchFinishAction()

        act.run(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103, box=_Box()))
        check("开打动作点击了战斗框中心（走原生 Click，规避 post_click 崩溃）",
              ctx.actions[-1] == ("PubClick", (180 + 60 - 1, 1050 + 30 - 1, 2, 2)),
              f"actions={ctx.actions}")
        check("开打动作【不】记账（避免未打完就计数）", bp.count_done(prefix) == 0)
        r = rec.analyze(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103))
        check("战斗中：指挥官不命中（绝不切目标/收工）", r.box is None, f"box={r.box}")

        fin.run(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103, box=_Box()))
        check("结算动作记了 1 场账本", bp.count_done(prefix) == 1)

        act.run(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103, box=_Box()))
        fin.run(ctx, _FakeArgv("猩红巨熊讨伐,中级,2", 103, box=_Box()))
        check("结算动作记了 2 场账本", bp.count_done(prefix) == 2)
        check("打够 2 次后 next_item = None", bp.next_item(bp.parse_batch("猩红巨熊讨伐,中级,2")[0]) is None)

        # 7.6 打够后（且已过结算缓冲）：归位主城并收工
        si._BATCH_LAST_FIGHT_TS = 0.0   # 跳过结算缓冲，模拟已结算
        ctx2 = _FakeContext()
        r = rec.analyze(ctx2, _FakeArgv("猩红巨熊讨伐,中级,2", 103))
        nexts = [n for _name, n in ctx2.nexts]
        check("全部打够：命中 + override_next -> SpecialBatchStop",
              r.box == [0, 0, 0, 0] and ["SpecialBatchStop"] in nexts, f"box={r.box} nexts={nexts}")

        # ---- 9.7 farm 清单：种类=farm，应用 farm override 且放行 farm 分派 ----
        si._BATCH_TASK_ID = None   # 强制换任务、重新解析
        si._BATCH_RAW = None
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("崩坏域,临境域深渊之兽·极,1", 201))
        check("farm 首个目标：命中（点主城归位）", r.box == [0, 0, 0, 0], f"box={r.box}")
        ov = ctx.overrides[0]
        # b00465f 起：FarmFight 改用 custom「special_target_fight」直接返回【战斗】框
        # （pair=below），不再写旧的 expected/target_offset（后者会误点推荐编成）。
        # #54 起：目标 = 【域 + 行名】——FarmFight 的 target = 行名、domain = 域（元素是行名的一部分）。
        check("farm override：FarmFight 用 special_target_fight 返回战斗框（pair=below）",
              ov["FarmFight"]["recognition"]["param"]["custom_recognition"] == "special_target_fight"
              and ov["FarmFight"]["recognition"]["param"]["custom_recognition_param"]["pair"] == "below"
              and ov["FarmFight"]["max_hit"] == 1,
              f"ov={ov.get('FarmFight')}")
        check("farm override：按【域 + 行名】选（target=临境域深渊之兽·极, domain=崩坏域）",
              ov["FarmFight"]["recognition"]["param"]["custom_recognition_param"]["target"] == "临境域深渊之兽·极"
              and ov["FarmFight"]["recognition"]["param"]["custom_recognition_param"]["domain"] == "崩坏域"
              and ov["FarmDomainPick"]["recognition"]["param"]["custom_recognition_param"]["domain"] == "崩坏域",
              f"ov={ov.get('FarmFight')}")
        check("farm override：FarmRetry 次数=1 且记账 record=always",
              ov["FarmRetry"]["max_hit"] == 1
              and ov["FarmRetry"]["action"]["param"]["custom_action_param"]["record"] == "always",
              f"ov={ov.get('FarmRetry')}")
        check("farm 模式写入 _BATCH_MODE=farm", si._BATCH_MODE == "farm", f"mode={si._BATCH_MODE}")
        bm = si.BatchModeRecognition()
        farm_argv = _FakeArgv("", 201, reco_param={"kind": "farm"})
        raid_argv = _FakeArgv("", 201, reco_param={"kind": "raid"})
        check("batch_mode(farm) 在 farm 模式命中", bm.analyze(ctx, farm_argv).box == [0, 0, 0, 0])
        check("batch_mode(raid) 在 farm 模式不命中", bm.analyze(ctx, raid_argv).box is None)

        # ---- 9.8 raid 清单：种类=raid，应用 raid override ----
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("战阵之宴,-,4", 202))
        check("raid 首个目标：命中", r.box == [0, 0, 0, 0], f"box={r.box}")
        ov = ctx.overrides[0]
        check("raid override：RaidContinueChallenge 次数=4 且记账 record=always",
              ov["RaidContinueChallenge"]["max_hit"] == 4
              and ov["RaidContinueChallenge"]["action"]["param"]["custom_action_param"]["record"] == "always",
              f"ov={ov.get('RaidContinueChallenge')}")
        check("raid 模式写入 _BATCH_MODE=raid", si._BATCH_MODE == "raid", f"mode={si._BATCH_MODE}")
        check("batch_mode(raid) 放行、batch_mode(farm) 不放行",
              bm.analyze(ctx, raid_argv).box == [0, 0, 0, 0] and bm.analyze(ctx, farm_argv).box is None)

        # ---- 9.9 清单为空 + 入口 FarmEntry：不覆盖、但放行 farm 分派（旧行为保持） ----
        ctx3 = _FakeContext()
        r = rec.analyze(ctx3, _FakeArgv("", 203, entry="FarmEntry"))
        check("空清单 FarmEntry：指挥官不命中且不 override", r.box is None and not ctx3.overrides, f"box={r.box}")
        check("空清单 FarmEntry：_BATCH_MODE=farm", si._BATCH_MODE == "farm", f"mode={si._BATCH_MODE}")
        check("batch_mode(farm) 放行", bm.analyze(ctx3, farm_argv).box == [0, 0, 0, 0])

        # ---- 9.10 清单为空 + 入口 SpecialEntry：special（两个分派器都不放行） ----
        ctx4 = _FakeContext()
        rec.analyze(ctx4, _FakeArgv("", 204, entry="SpecialEntry"))
        check("空清单 SpecialEntry：_BATCH_MODE=special", si._BATCH_MODE == "special", f"mode={si._BATCH_MODE}")
        check("batch_mode(farm/raid) 均不放行",
              bm.analyze(ctx4, farm_argv).box is None and bm.analyze(ctx4, raid_argv).box is None)


def test_phantom_kind_parse() -> None:
    print("\n== 10. 幻想连战并入清单：种类判定 + 解析 ==")
    check("幻想连战 → phantom", bp.detect_kind("幻想连战") == "phantom")
    check("幻想连战（含其它字）→ phantom", bp.detect_kind("幻想连战EX") == "phantom")
    check("is_phantom 一致", bp.is_phantom("幻想连战") and not bp.is_phantom("光之迷宫"))

    # 正例：难度位写 -，次数位 = 套数
    items, errors = bp.parse_batch("幻想连战,-,2\n")
    check("幻想连战,-,2 解析无错",
          errors == [] and len(items) == 1, f"errors={errors} items={items}")
    it = items[0]
    check("phantom 种类 + 次数=套数=2 + target=幻想连战",
          it.kind == "phantom" and it.times == 2 and it.dungeon == "幻想连战"
          and it.difficulty == "-" and it.target == "幻想连战",
          f"kind={it.kind} times={it.times} target={it.target}")
    check("phantom 账本沿用现有体系（不另造 key）",
          bp.item_prefix(it) == "special_dungeon_batch/幻想连战/-")

    # 有效难度也接受（仅忽略，镜像 raid）
    items, errors = bp.parse_batch("幻想连战,超级,1\n")
    check("幻想连战 写有效难度也接受（忽略）", errors == [] and items[0].kind == "phantom")
    # 非法难度仍报错
    _items, errors = bp.parse_batch("幻想连战,地狱,1\n")
    check("幻想连战 非法难度报错", len(errors) == 1 and "难度" in errors[0], f"errors={errors}")

    # 混合清单：special/farm/raid/phantom 各归其类、顺序保留
    items, errors = bp.parse_batch(
        "猩红巨熊讨伐,中级,1\n崩坏域,临境域深渊之兽·极,2\n战阵之宴,-,5\n幻想连战,-,3\n"
    )
    check("四种类混合清单正确",
          errors == [] and [i.kind for i in items] == ["special", "farm", "raid", "phantom"],
          f"got={[i.kind for i in items]}")


def test_phantom_ledger_count() -> None:
    print("\n== 11. phantom 记账：已完成套数 = 现有 phantom/set/* 体系 ==")
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "phantom_progress.json")
        items, _e = bp.parse_batch("幻想连战,-,3\n")
        it = items[0]
        check("初始 remaining=3（无账本）", bp.remaining(it) == 3 and bp.count_done(it) == 0)

        ledger.mark_done("phantom/set/1/completed")
        check("完成标记 → 已算 1 套", bp.count_done(it) == 1 and bp.remaining(it) == 2)
        ledger.mark_done("phantom/set/2/stage/15")
        check("旧账本 stage/15 → 也算 1 套", bp.count_done(it) == 2 and bp.remaining(it) == 1)
        ledger.mark_done("phantom/set/2/completed")   # 与 stage/15 同一套，不重复计
        check("同一套标记+15 关只算 1 套（并集）", bp.count_done(it) == 2, f"count={bp.count_done(it)}")
        ledger.mark_done("phantom/set/3/stage/7")
        check("只到第 7 关的套不算完成", bp.count_done(it) == 2, f"count={bp.count_done(it)}")
        ledger.mark_done("phantom/set/3/completed")
        check("第 3 套完成 → count=3, remaining=0",
              bp.count_done(it) == 3 and bp.remaining(it) == 0)
        check("打够后 next_item=None", bp.next_item([it]) is None)


def test_phantom_orchestrator_offline() -> None:
    """stub context 验证：清单里的幻想 → phantom 分派 + 刷够套数回指挥官（不 StopTask）。"""
    print("\n== 12. 指挥官×幻想：种类路由 + 刷完回指挥官 ==")
    import json

    import side_impl as si

    class _FakeJob:
        def wait(self):
            return True

    class _FakeController:
        def __init__(self):
            self.clicks = []

        def post_click(self, x, y):
            self.clicks.append((x, y))
            return _FakeJob()

    class _FakeTasker:
        def __init__(self):
            self.controller = _FakeController()

    class _FakeDetail:
        hit = False

    class _FakeContext:
        def __init__(self):
            self.tasker = _FakeTasker()
            self.overrides = []
            self.nexts = []

        def run_recognition(self, entry, image):
            return _FakeDetail()

        def override_pipeline(self, d):
            self.overrides.append(d)
            return True

        def override_next(self, name, lst):
            self.nexts.append((name, list(lst)))
            return True

    class _FakeTaskDetail:
        def __init__(self, tid, entry="SpecialEntry"):
            self.task_id = tid
            self.entry = entry

    class _FakeArgv:
        def __init__(self, text, tid, reco_param=None, entry="SpecialEntry"):
            if reco_param is not None:
                self.custom_recognition_param = json.dumps(reco_param)
            else:
                self.custom_recognition_param = json.dumps({"list": text})
            self.custom_action_param = "{}"
            self.task_detail = _FakeTaskDetail(tid, entry)
            self.image = None

    with tempfile.TemporaryDirectory() as d:
        # 每次测试前清 phantom 账本 + 强制重新解析清单
        ledger.set_file(Path(d) / "phantom_orch.json")
        si._BATCH_TASK_ID = None
        si._BATCH_RAW = None

        rec = si.SpecialBatchPlanRecognition()
        bm = si.BatchModeRecognition()
        phantom_argv = _FakeArgv("", 301, reco_param={"kind": "phantom"})
        farm_argv = _FakeArgv("", 301, reco_param={"kind": "farm"})
        raid_argv = _FakeArgv("", 301, reco_param={"kind": "raid"})

        # 12.1 只有幻想一条：首次命中即应用 override + 点主城归位
        ctx = _FakeContext()
        r = rec.analyze(ctx, _FakeArgv("幻想连战,-,2", 301))
        check("phantom 清单：指挥官命中（点主城归位）", r.box == [0, 0, 0, 0], f"box={r.box}")
        ov = ctx.overrides[0]
        pd = ov["PhantomDone"]["recognition"]["param"]["custom_recognition_param"]
        check("phantom override：PhantomDone target_sets=2 + mode=batch + 动作改 DoNothing",
              pd["target_sets"] == 2 and pd["mode"] == "batch"
              and ov["PhantomDone"]["action"]["type"] == "DoNothing",
              f"ov={ov.get('PhantomDone')}")
        pg = ov["PhantomGiveUp"]["recognition"]["param"]["custom_recognition_param"]
        check("phantom override：PhantomGiveUp target_sets=2 + mode=batch（动作仍 StopTask）",
              pg["target_sets"] == 2 and pg["mode"] == "batch", f"ov={ov.get('PhantomGiveUp')}")
        check("phantom override 不碰导航节点", "PhantomHubEnter" not in ov)
        # ★关卡上限（选项「打到第几关以后放弃」）在批量下也必须生效★：
        #   stage_cap 由 phantom_state 节点（关卡选择页/战斗/结算）注入会话；
        #   _phantom_override 只覆盖 PhantomDone / PhantomGiveUp，绝不能连这些
        #   承载 stage_cap 的节点一起覆盖掉，否则批量模式的上限会静默失效。
        check("phantom override 不碰承载关卡上限的节点（PhantomMainFight/BattleWait/SettleState）",
              not ({"PhantomMainFight", "PhantomBattleWait", "PhantomSettleState"} & set(ov)),
              f"ov_keys={list(ov)}")
        check("phantom 模式写入 _BATCH_MODE=phantom", si._BATCH_MODE == "phantom", f"mode={si._BATCH_MODE}")
        check("batch_mode(phantom) 放行、farm/raid 不放行",
              bm.analyze(ctx, phantom_argv).box == [0, 0, 0, 0]
              and bm.analyze(ctx, farm_argv).box is None
              and bm.analyze(ctx, raid_argv).box is None)

        # 12.2 归位后、套数未刷够 → 指挥官不命中（绝不切目标 / 战斗中途不打断）
        r = rec.analyze(ctx, _FakeArgv("幻想连战,-,2", 301))
        check("刷够前：指挥官不命中（不会中途切目标）", r.box is None, f"box={r.box}")
        ledger.mark_done("phantom/set/1/completed")
        r = rec.analyze(ctx, _FakeArgv("幻想连战,-,2", 301))
        check("已完成 1/2 套：仍不命中（继续刷第 2 套）", r.box is None, f"box={r.box}")

        # 12.3 刷够 2 套 → 全部完成 → 归位主城 + override_next -> SpecialBatchStop
        ledger.mark_done("phantom/set/2/completed")
        si._BATCH_LAST_FIGHT_TS = 0.0
        ctx2 = _FakeContext()
        r = rec.analyze(ctx2, _FakeArgv("幻想连战,-,2", 301))
        nexts = [n for _name, n in ctx2.nexts]
        check("刷够 2 套：命中 + override_next -> SpecialBatchStop（整任务收工）",
              r.box == [0, 0, 0, 0] and ["SpecialBatchStop"] in nexts, f"box={r.box} nexts={nexts}")
        check("batch 模式【不】写 phantom 收工标记（保留套数统计）",
              not ledger.is_done("phantom/run/completed"))

        # 12.4 多目标：幻想刷完 → 指挥官切到清单下一条 special（回 SpecialEntry 继续）
        ledger.set_file(Path(d) / "phantom_orch2.json")
        si._BATCH_TASK_ID = None
        si._BATCH_RAW = None
        ctx3 = _FakeContext()
        rec.analyze(ctx3, _FakeArgv("幻想连战,-,1\n猩红巨熊讨伐,中级,1\n", 302))
        ledger.mark_done("phantom/set/1/completed")   # 幻想这条刷够 1 套
        ctx4 = _FakeContext()
        r = rec.analyze(ctx4, _FakeArgv("幻想连战,-,1\n猩红巨熊讨伐,中级,1\n", 302))
        nexts4 = [n for _name, n in ctx4.nexts]
        check("幻想刷完 → 切到下一条 special，且 override_next 回 SpecialEntry",
              r.box == [0, 0, 0, 0] and ["SpecialEntry"] in nexts4, f"box={r.box} nexts={nexts4}")
        check("已切到 special：override 应用了副本名",
              ctx4.overrides
              and ctx4.overrides[0]["SpecialEnterBoss"]["recognition"]["param"]["expected"] == ["猩红巨熊讨伐"],
              f"ov={ctx4.overrides}")
        check("切到 special 后 _BATCH_MODE=special、phantom 分派不再放行",
              si._BATCH_MODE == "special"
              and bm.analyze(ctx4, phantom_argv).box is None, f"mode={si._BATCH_MODE}")


def main() -> None:
    print("=" * 70)
    print("离线单测：batch_plan.py（批量副本清单解析 / 账本计数 / 指挥官状态机）")
    print("=" * 70)
    test_parse_normal()
    test_parse_tolerance()
    test_parse_errors()
    test_dedupe()
    test_ledger_counts()
    test_joss_tab()
    test_kind_detection()
    test_farm_raid_parse()
    test_orchestrator_offline()
    test_phantom_kind_parse()
    test_phantom_ledger_count()
    test_phantom_orchestrator_offline()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
