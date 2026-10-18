# -*- coding: utf-8 -*-
"""离线单测：#100 领主战「全难度解禁」的离线可测部分（纯单测，不碰设备）。

跑：

    .venv\\Scripts\\python.exe tools\\test_lords_unlock.py

覆盖：

1. **``parse_progress``**：真机原样 / 空格 / 全角 / 分隔符抖动 / 夹「全」都读对；
   歧义 ``3/4/5``、裸数字、三位数、错标签、缺分母一律拒收；
   ``N>M`` **语法上通过**（语义脏数据交给 ``plan_round`` 抛异常）—— 这条分界必须显式。
2. **``group_progress_rows``**：把列表页一屏 OCR 归成「行」（真机 720 几何）；
   读不出归属的 ``通关数`` 进 ``orphans``（★不静默丢★）。
3. **``plan_round``**：全部 M/M → 无目标；``N<M`` → ``链[N]``；链未采集 → ``difficulty=None``
   + ``no_chain``；``N>M`` → 抛；未知行 / M 冲突 / 重复行 → 点名；零行 ≠ 全通。
4. **``should_stop`` / ``round_gained``**：三条终结 + 防死循环 + 优先级 + 用户可见原因。
5. **循环语义（D6）端到端模拟**：用纯逻辑把「读 → 打 → 重读」跑起来，证明
   ①全 M/M 收工、②连续 2 轮无新解锁收工、③场次上限收工、④打不动就当场收工（不死循环）。
6. **``agent/lords_impl`` 行为**（假 OCR + 假点击）：读完给结构化 name/n/m/box、三跳点中心、
   点下挑战记一场、禁双击、20s 死线带原因收工、全 M/M 当场收工、安装态不假成功。
7. **守卫**：``tools/contract_hooks/hooks_100.py`` 六个挂点全绿 + prove-red 成立。
8. **#120 ``Rect`` 兼容**：maa v5 的 ``argv.box`` 是 ``Rect``（只有 ``.x/.y/.w/.h``，**没有**
   ``__len__``）—— 假 Rect 走 ``_tab_click`` / ``run`` 必须点得下去；解包**保留浮点**
   （中心 == 手算值，奇数宽度 300.5 不许被 ``int()`` 截断）；动作里的异常必须**留痕**
   （一行 ``★动作异常★`` + 栈，绝不被 ctypes 回调吞掉）。守卫在 ``hooks_120``。
9. **#100 第 3 条缺口**：pick 前先对页签、再上下找、三种失败原因分开（``hooks_121``）。
10. **#100 第 7/8 条缺口**：模式页复核**只认正向证据**（编队页 = 挑战 + SET/Party/自动续战 之一；
    「点完 → 瞬时 unknown → 又回模式页」必须判失败）、**换点阶梯**（中心 → 下方100 → 右侧120 →
   下方180，每次等 ≥2.5s，最多 4 次）、**盲点 (0,0) 拒绝**（框缺失 / 尺寸 0 ⇒ 点击函数不被调用）。
   守卫在 ``hooks_122``（三个新挂点 + 十条破坏实验）。

不校验的东西（诚实边界）：本文件**不**判断「某账号能打哪几档」（账号状态），
也**不**碰设备；假 OCR 用的是 ``tools/frames/`` 那几帧的逐条读数。
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene.config import DIFFICULTIES  # noqa: E402
from scene.lords import LORDS, by_row_name  # noqa: E402
from scene.lords_unlock import (  # noqa: E402
    IDLE_ROUND_LIMIT,
    MAX_NAME_DY,
    POSITIVE_CASES,
    PROBLEM_DUPLICATE,
    PROBLEM_M_CONFLICT,
    PROBLEM_NO_CHAIN,
    PROBLEM_UNKNOWN_ROW,
    REJECTED_CASES,
    SESSION_CAP,
    LordsDataError,
    RoundPlan,
    RowReading,
    Target,
    UnlockState,
    group_progress_rows,
    parse_progress,
    plan_round,
    round_gained,
    should_stop,
)

import hooks_100  # noqa: E402
import hooks_120  # noqa: E402  （#120：Rect 兼容 + 动作异常留痕）
import hooks_121  # noqa: E402  （#100 第 3 条真机缺口：pick 前先对页签、再上下找、三原因分开）
import hooks_122  # noqa: E402  （#100 第 4/5/7/8 条真机缺口：模式页 / 降噪 / 正向复核 / 盲点）

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. parse_progress
# ---------------------------------------------------------------------------
def test_parse_progress() -> None:
    print("\n== 1. parse_progress：正则 + 正反例 ==")
    for text, n, m, why in POSITIVE_CASES:
        check(f"正例 {text!r} -> ({n},{m})  （{why}）", parse_progress(text) == (n, m),
              f"got={parse_progress(text)!r}")
    for text, why in REJECTED_CASES:
        check(f"反例 {text!r} 拒收  （{why}）", parse_progress(text) is None,
              f"got={parse_progress(text)!r}")

    # 本票点名的三条（真机原样 / 无空格 / 夹「全」）
    check("点名：通关数 3/4", parse_progress("通关数 3/4") == (3, 4))
    check("点名：通关数3/4", parse_progress("通关数3/4") == (3, 4))
    check("点名：通关数 全5/5", parse_progress("通关数 全5/5") == (5, 5))

    # 语法 vs 语义的分界：N>M 语法上成立（语义由 plan_round 抛错）
    check("N>M 在 parse 层**不**拦（语法成立）", parse_progress("通关数4/3") == (4, 3))
    check("M==0 在 parse 层就当读错（分母 0 无意义）", parse_progress("通关数3/0") is None)
    # 前后夹着别的文字也能读出来（真机 OCR 会把整行拼成一串）
    check("前后夹字仍能读", parse_progress("艾基尔·嫉妒讨伐 通关数1/4") == (1, 4))
    check("两段读数时取第一段（不让拼接帧产生歧义）", parse_progress("通关数1/4通关数2/4") == (1, 4))


# ---------------------------------------------------------------------------
# 2. group_progress_rows
# ---------------------------------------------------------------------------
def test_group_rows() -> None:
    print("\n== 2. group_progress_rows：列表页一屏 → 行（真机 720 几何）==")
    rows, orphans = group_progress_rows(hooks_100.LIST_FRAME)
    names = [row.name for row in rows]
    check("读出 3 行", len(rows) == 3, f"got={names}")
    check("行名与进度配对正确", names == ["艾基尔·嫉妒讨伐", "猩红巨熊讨伐", "八岐大蛇讨伐"], f"got={names}")
    by_name = {row.name: row for row in rows}
    check("艾基尔 1/4", by_name["艾基尔·嫉妒讨伐"].pair == (1, 4))
    check("猩红巨熊 3/4", by_name["猩红巨熊讨伐"].pair == (3, 4))
    check("八岐大蛇 4/4 且 complete", by_name["八岐大蛇讨伐"].pair == (4, 4)
          and by_name["八岐大蛇讨伐"].complete)
    check("按纵向排序（y 递增）",
          [row.name_box[1] for row in rows] == sorted(row.name_box[1] for row in rows))
    check("没有 orphans（这一屏每行都配得上）", orphans == (), f"got={orphans}")

    # 归属不上的 通关数 → orphans（★不静默丢★）。真机样本：五王连战那类不在花名册的行
    orphan_items = [("更新列表", [615, 328, 82, 28]), ("通关数1/1", [547, 688, 127, 28])]
    rows2, orphans2 = group_progress_rows(orphan_items)
    check("没有行名可挂 → 进 orphans 而不是消失", rows2 == () and len(orphans2) == 1,
          f"rows={rows2} orphans={orphans2}")

    # 徽标（COMPLETE!! / NEW）不抢行名：真机 八岐大蛇 那行左上就有 COMPLETE!!
    badge_items = list(hooks_100.LIST_FRAME) + [("COMPLETE!!", [15, 1022, 124, 24])]
    rows3, _orphans3 = group_progress_rows(badge_items)
    check("COMPLETE!! 徽标不会被当成行名",
          sorted(row.name for row in rows3) == ["八岐大蛇讨伐", "猩红巨熊讨伐", "艾基尔·嫉妒讨伐"],
          f"got={[row.name for row in rows3]}")

    # 纵向太远 / 横向在左 → 都不配对（几何判据，不是「随便找个最近的」）
    far_items = [("艾基尔·嫉妒讨伐", [202, 300, 197, 28]), ("通关数1/4", [547, 688, 127, 28])]
    _rows4, orphans4 = group_progress_rows(far_items)
    check(f"纵向超过 {MAX_NAME_DY}px 不配对", len(orphans4) == 1)

    # RowReading 结构：name/n/m + 两个框（detail 要用它）
    row = rows[0]
    check("RowReading 带 name_box / progress_box",
          len(row.name_box) == 4 and len(row.progress_box) == 4, f"got={row}")


# ---------------------------------------------------------------------------
# 3. plan_round
# ---------------------------------------------------------------------------
def test_plan_round() -> None:
    print("\n== 3. plan_round：该打谁 / 打哪一档 / 是不是全通 ==")
    # 全部 M/M → 无目标
    plan = plan_round([("八岐大蛇讨伐", 4, 4), ("无猾机兵", 5, 5)])
    check("全部 M/M → 无目标", plan.targets == (), f"got={plan.pairs}")
    check("全部 M/M → all_done", plan.all_done is True)

    # 完整链 → 链[N]
    plan = plan_round([("妖狐讨伐", 1, 4)])
    check("妖狐讨伐 1/4 → (妖狐讨伐, 高级)", plan.pairs == (("妖狐讨伐", "高级"),), f"got={plan.pairs}")
    check("链上第 N 档就是目标档（N 从 0 起）",
          [plan_round([("妖狐讨伐", n, 4)]).pairs for n in range(4)]
          == [(("妖狐讨伐", d),) for d in ("中级", "高级", "高级+", "超级")])
    check("还有 N<M → 不是 all_done", plan.all_done is False)

    # 链未采集 → difficulty=None + no_chain（★不是静默跳过★）
    plan = plan_round([("艾基尔·嫉妒讨伐", 1, 4)])
    check("链未采集 → 目标 difficulty=None", plan.pairs == (("艾基尔·嫉妒讨伐", None),), f"got={plan.pairs}")
    check("链未采集 → 报 no_chain", [p.kind for p in plan.problems] == [PROBLEM_NO_CHAIN],
          f"got={plan.problems}")
    check("链未采集 → 进 needs_detail", len(plan.needs_detail) == 1)

    # N>M 脏数据 → 抛（报错不是静默跳过）
    try:
        plan_round([("妖狐讨伐", 4, 3)])
    except LordsDataError as exc:
        check("N>M → 抛 LordsDataError 且点名行", "妖狐讨伐" in str(exc), f"msg={exc}")
    else:
        check("N>M → 抛 LordsDataError 且点名行", False, "没有报错")
    try:
        plan_round([("妖狐讨伐", 1, 0)])
    except LordsDataError:
        check("M=0 → 抛 LordsDataError", True)
    else:
        check("M=0 → 抛 LordsDataError", False, "没有报错")

    # 未知行 / M 冲突
    plan = plan_round([("降临过伐", 1, 4)])
    check("花名册外的行 → 不规划 + unknown_row",
          plan.targets == () and any(p.kind == PROBLEM_UNKNOWN_ROW for p in plan.problems),
          f"got={plan.targets} / {plan.problems}")
    plan = plan_round([("妖狐讨伐", 1, 3)])
    check("列表页 M=3 与静态 M=4 冲突 → 不取档 + m_conflict",
          plan.targets == () and any(p.kind == PROBLEM_M_CONFLICT for p in plan.problems),
          f"got={plan.targets} / {plan.problems}")

    # 重复行
    plan = plan_round([("妖狐讨伐", 1, 4), ("妖狐讨伐", 2, 4)])
    check("同一行两个读数 → 只按第一份规划 + 记 duplicate",
          plan.pairs == (("妖狐讨伐", "高级"),) and any(p.kind == PROBLEM_DUPLICATE for p in plan.problems),
          f"got={plan.pairs} / {plan.problems}")

    # 零行 ≠ 全通
    plan = plan_round([])
    check("零行 → all_done=False（零行当全通 = 假收工）", plan.all_done is False)
    check("零行 → 无目标", plan.targets == ())

    # 输入形态：三元组 / RowReading 都认
    reading = RowReading("妖狐讨伐", 2, 4, (0, 0, 0, 0), (0, 0, 0, 0))
    check("接受 RowReading 输入", plan_round([reading]).pairs == (("妖狐讨伐", "高级+"),))
    check("接受映射输入", plan_round([{"name": "妖狐讨伐", "n": 2, "m": 4}]).pairs
          == (("妖狐讨伐", "高级+"),))
    check("registry 可注入（缺省 scene.lords.LORDS）",
          plan_round([("妖狐讨伐", 1, 4)], LORDS).pairs == (("妖狐讨伐", "高级"),))

    # 全量扫描：每个有完整链的领主，N 在 0..M-1 上都要算出 链[N]
    bad = []
    for entry in LORDS:
        chain = tuple(entry.tier_chain)
        if not chain or entry.max_tiers != len(chain):
            continue
        for n in range(len(chain)):
            if plan_round([(entry.row_name, n, len(chain))]).pairs != ((entry.row_name, chain[n]),):
                bad.append((entry.row_name, n))
    check("全量扫描：所有已采集链的领主都按 链[N] 取档", bad == [], f"bad={bad}")

    # 目标档必须在难度词表里，且 unlock_requires 是前缀（逐档递进的语义）
    entry = by_row_name("妖狐讨伐")
    check("目标档 ∈ DIFFICULTIES", all(d in DIFFICULTIES for d in entry.tier_chain))
    check("超级 requires 全部更低档（不是只差一档）",
          entry.unlock_requires("超级") == ("中级", "高级", "高级+"))


# ---------------------------------------------------------------------------
# 4. 终结条件
# ---------------------------------------------------------------------------
def test_should_stop() -> None:
    print("\n== 4. should_stop：三条终结 + 防死循环 ==")
    # 主：全 M/M
    stop, reason = should_stop(UnlockState(all_done=True, rows_read=4, planned=0, played=1, sessions=3))
    check("全 M/M → 停", stop is True)
    check("全 M/M 的原因说清「全部解禁」+ M/M", "全部解禁" in reason and "M/M" in reason, f"reason={reason}")

    # 零行却判全通 → 停，但**不是**成功
    stop, reason = should_stop(UnlockState(all_done=True, rows_read=0))
    check("零行 + all_done → 也停（不许假成功）", stop is True)
    check("零行 + all_done 的原因**不**说「全部解禁」", "全部解禁" not in reason, f"reason={reason}")

    # 兜底一：连续 2 轮无新解锁
    stop, reason = should_stop(UnlockState(rows_read=4, planned=1, played=2, sessions=8,
                                           no_progress_rounds=IDLE_ROUND_LIMIT))
    check(f"连续 {IDLE_ROUND_LIMIT} 轮无新解锁 → 停", stop is True)
    check("原因里带轮数与「收工」", "2" in reason and "收工" in reason, f"reason={reason}")
    stop, _reason = should_stop(UnlockState(rows_read=4, planned=1, played=2, sessions=8,
                                            no_progress_rounds=IDLE_ROUND_LIMIT - 1))
    check("未到阈值不停", stop is False)

    # 兜底二：场次上限
    stop, reason = should_stop(UnlockState(rows_read=4, planned=2, played=2, sessions=SESSION_CAP))
    check(f"场次 {SESSION_CAP} → 停", stop is True)
    check("原因带上限值 + 尚未全通", str(SESSION_CAP) in reason and "未" in reason, f"reason={reason}")
    stop, _reason = should_stop(UnlockState(rows_read=4, planned=2, played=2, sessions=SESSION_CAP - 1))
    check("差一场不停", stop is False)

    # ★防死循环★：本轮零场 → 必须停
    for planned in (0, 1, 5):
        stop, reason = should_stop(UnlockState(rows_read=4, planned=planned, played=0, sessions=0))
        check(f"计划 {planned} 个却零场 → 停（防死循环）", stop is True and bool(reason), f"reason={reason}")
    _s0, r0 = should_stop(UnlockState(rows_read=4, planned=0, played=0))
    _s1, r1 = should_stop(UnlockState(rows_read=4, planned=3, played=0))
    check("零目标 vs 计划了没打：原因必须不同", r0 != r1, f"{r0!r} vs {r1!r}")

    # 真打了就不拦
    stop, _reason = should_stop(UnlockState(rows_read=4, planned=3, played=1, sessions=1))
    check("打了 1 场 → 不停", stop is False)

    # 正向：三条都不成立
    check("正常推进 → (False, '')",
          should_stop(UnlockState(rows_read=4, planned=2, played=2, sessions=5)) == (False, ""))

    # 优先级：全通 > 场次上限（全通时说成功，不说「上限用尽」）
    _stop, reason = should_stop(UnlockState(all_done=True, rows_read=4, played=1, sessions=SESSION_CAP))
    check("全通与上限同时成立时，先说「全部解禁」", "全部解禁" in reason, f"reason={reason}")


def test_round_gained() -> None:
    print("\n== 4b. round_gained：这一轮有没有新解锁 ==")
    gained, names = round_gained({"妖狐讨伐": 1, "猩红巨熊讨伐": 3}, [("妖狐讨伐", 2, 4), ("猩红巨熊讨伐", 3, 4)])
    check("N 增长 → 有新解锁", gained is True and names == ("妖狐讨伐",), f"got={(gained, names)}")
    gained, names = round_gained({"妖狐讨伐": 2, "猩红巨熊讨伐": 3}, [("妖狐讨伐", 2, 4), ("猩红巨熊讨伐", 3, 4)])
    check("都不长 → 无新解锁", gained is False and names == (), f"got={(gained, names)}")
    gained, names = round_gained(None, [("妖狐讨伐", 0, 4)])
    check("首次读数算「有信息」（不算进展停滞）", gained is True and names == ("妖狐讨伐",))
    gained, names = round_gained({"妖狐讨伐": 2}, [("妖狐讨伐", 1, 4)])
    check("N 倒退（换账号/脏读数）→ 不算新解锁", gained is False, f"got={(gained, names)}")


# ---------------------------------------------------------------------------
# 5. 循环语义（D6）端到端模拟
# ---------------------------------------------------------------------------
def simulate(world, *, registry=None, session_cap=SESSION_CAP, idle_round_limit=IDLE_ROUND_LIMIT,
             unplayable=(), fights_without_unlock=False, max_rounds=40):
    """纯逻辑版 D6 循环：读 → 规划 → 打 → 回列表重读 → 判终结。

    ``world``：``{行名: [N, M]}``（原地推进，模拟「通关一档」）。
    ``unplayable``：这些行名**打不动**（点了没反应）—— 用来验证防死循环。
    ``fights_without_unlock``：打了但不涨 N（模拟打输了）—— 用来验证「连续 N 轮无新解锁」。
    返回 ``(rounds, sessions, reason, world)``。
    """
    if registry is None:
        registry = LORDS
    rounds = 0
    sessions = 0
    no_progress = 0
    prev = {}
    played_this_round = 0
    while True:
        rows = [(name, n, m) for name, (n, m) in world.items()]
        plan = plan_round(rows, registry)
        closed = rounds > 0
        if closed:
            gained, _names = round_gained(prev, rows)
            no_progress = 0 if gained else no_progress + 1
        if plan.all_done or closed or not plan.targets:
            stop, reason = should_stop(
                UnlockState(
                    all_done=plan.all_done,
                    rows_read=len(rows),
                    planned=len(plan.targets),
                    played=played_this_round,
                    sessions=sessions,
                    no_progress_rounds=no_progress,
                    session_cap=session_cap,
                    idle_round_limit=idle_round_limit,
                )
            )
            if stop:
                return rounds, sessions, reason, world
        if rounds >= max_rounds:
            return rounds, sessions, "（模拟达到轮数上限，未收工）", world
        prev = {name: n for name, (n, m) in world.items()}
        played_this_round = 0
        for target in plan.targets:
            if target.row_name in unplayable:
                continue
            n, m = world[target.row_name]
            if n >= m:
                continue
            if not fights_without_unlock:
                world[target.row_name] = [n + 1, m]
            sessions += 1
            played_this_round += 1
        rounds += 1


def test_loop_semantics() -> None:
    print("\n== 5. 循环语义（D6）端到端：读 → 打 → 重读 → 判终结 ==")
    # ① 全 M/M 主线收工：3 个领主 × 4 档（链未采集 → 每轮每个领主打一档）
    world = {"艾基尔·嫉妒讨伐": [0, 4], "猩红巨熊讨伐": [0, 4], "八岐大蛇讨伐": [4, 4]}
    rounds, sessions, reason, world = simulate(world)
    check("①全 M/M 收工：4 轮打完", rounds == 4, f"rounds={rounds}")
    check("①每轮 2 场（八岐大蛇已满，不重复打）→ 共 8 场", sessions == 8, f"sessions={sessions}")
    check("①收工原因 = 全部解禁", "全部解禁" in reason, f"reason={reason}")
    check("①收工时全部 M/M", all(n == m for n, m in world.values()), f"world={world}")

    # ② 完整链的领主：同样 4 轮，但每轮的目标档是 链[N]
    world = {"妖狐讨伐": [0, 4]}
    rounds, sessions, reason, world = simulate(world)
    check("②已采集链的领主也是 4 轮 4 场", (rounds, sessions) == (4, 4), f"got={(rounds, sessions)}")
    check("②收工原因 = 全部解禁", "全部解禁" in reason, f"reason={reason}")

    # ③ 连续 2 轮无新解锁（打输了）→ 兜底收工
    world = {"妖狐讨伐": [1, 4]}
    rounds, sessions, reason, world = simulate(world, fights_without_unlock=True)
    check("③连续 2 轮无新解锁就收工（不是永远打下去）", rounds == 2, f"rounds={rounds}")
    check("③原因点到「连续」与轮数", "连续" in reason and str(IDLE_ROUND_LIMIT) in reason, f"reason={reason}")
    check("③这两轮确实在打（不是零场）", sessions == 2, f"sessions={sessions}")
    check("③世界没变（打输了）", world["妖狐讨伐"] == [1, 4])

    # ④ 场次上限兜底
    world = {"妖狐讨伐": [0, 4], "艾基尔·嫉妒讨伐": [0, 4]}
    rounds, sessions, reason, _world = simulate(world, session_cap=3)
    check("④场次上限 3 → 收工", sessions >= 3 and "场次上限" in reason, f"sessions={sessions} reason={reason}")

    # ⑤ 打不动（点了没反应）→ 本轮零场 → 收工，绝不空转。
    #   ★轮数 = 1 而不是 0 是**设计如此**★：第一轮读列表时还没打过，不能判（否则一场不打就退）；
    #   等这一轮关闭（回来了）才判 —— 所以最多浪费一个轮次，不会无限空转。
    world = {"妖狐讨伐": [0, 4]}
    rounds, sessions, reason, _world = simulate(world, unplayable=("妖狐讨伐",))
    check("⑤打不动 → 一个轮次后就收工", rounds == 1, f"rounds={rounds}")
    check("⑤一场没打", sessions == 0)
    check("⑤原因说「防死循环」", "防死循环" in reason, f"reason={reason}")

    # ⑥ 全通 + 场次上限同时到：先说全解禁
    world = {"妖狐讨伐": [3, 4]}
    _rounds, _sessions, reason, _world = simulate(world, session_cap=1)
    check("⑥全通优先于场次上限", "全部解禁" in reason, f"reason={reason}")


# ---------------------------------------------------------------------------
# 6. agent 行为（假 OCR + 假点击）
# ---------------------------------------------------------------------------
def test_agent() -> None:
    print("\n== 6. agent/lords_impl：读完给行、三跳点到位、禁双击、死线、安装态 ==")
    impl = hooks_100._impl()
    reco = impl.LordsProgressRecognition()
    action = impl.LordsUnlockAction()

    with hooks_100.FakeOcr(frame=hooks_100.LIST_FRAME):
        ctx = hooks_100.FakeContext()
        res = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=201))
        detail = res.detail or {}
        check("read 命中列表页", res.box is not None)
        check("detail.rows 每行带 name/n/m/box",
              len(detail.get("rows") or []) == 3
              and all(set(("name", "n", "m", "name_box", "progress_box")) <= set(row) for row in detail["rows"]),
              f"rows={detail.get('rows')}")
        check("detail.targets 是 [(行名, 档位)] 形状",
              all(isinstance(t, list) and len(t) == 2 for t in detail.get("targets") or []),
              f"targets={detail.get('targets')}")
        check("第一轮不收工（还没打）", detail.get("stop") is False)

    with hooks_100.FakeOcr(frames=[hooks_100.LIST_FRAME, hooks_100.LIST_FRAME,
                                   hooks_100.DETAIL_FRAME, hooks_100.TEAM_FRAME]):
        ctx = hooks_100.FakeContext()
        task = 202
        reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=task))
        for want_what, want_box in (
            (impl.WHAT_ROW, [202, 640, 197, 28]),
            (impl.WHAT_TIER, [58, 334, 21, 11]),
            (impl.WHAT_CHALLENGE, [297, 1069, 80, 47]),
        ):
            step = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "pick"}, task_id=task,
                                                        node_name="LordsPickTarget"))
            check(f"三跳之一 = {want_what}（框 {want_box}）",
                  (step.detail or {}).get("what") == want_what and step.box == want_box,
                  f"got={(step.detail or {}).get('what')!r} {step.box}")
            check(f"动作点下去成功（{want_what}）", action.run(ctx, hooks_100.FakeArgv(task_id=task, box=step.box)))
        session = impl._session(task)
        check("点一次【挑战】记 1 场", session.sessions_played == 1, f"got={session.sessions_played}")
        check("点过挑战后置「禁双击」闩", session.challenge_pending is True)
        check("三次点击 = 三个框中心",
              ctx.clicked_centers() == [(300, 654), (68, 339), (337, 1092)], f"got={ctx.clicked_centers()}")

    with hooks_100.FakeOcr(frame=hooks_100.TEAM_FRAME):
        ctx = hooks_100.FakeContext()
        task = 203
        session = impl._session(task)
        session.targets = [Target("妖狐讨伐", None, 0, 4)]
        first = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "pick"}, task_id=task,
                                                     node_name="LordsPickTarget"))
        action.run(ctx, hooks_100.FakeArgv(task_id=task, box=first.box))
        again = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "pick"}, task_id=task,
                                                     node_name="LordsPickTarget"))
        check("点过【挑战】后同一编队页不再给出可点框（禁双击）", again.box is None, f"got={again.box}")

    with hooks_100.FakeOcr(frame=hooks_100.LIST_FRAME), hooks_100.FakeClock() as clock:
        ctx = hooks_100.FakeContext()
        task = 204
        reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=task))
        reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "pick"}, task_id=task, node_name="LordsPickTarget"))
        clock.advance(impl.STUCK_SEC + 1)
        detail = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=task)).detail or {}
        check(f"{impl.STUCK_SEC:.0f}s 点不出去 → 收工", detail.get("stop") is True, f"got={detail.get('stop')}")
        check("收工原因说「点不出去」", "点不出去" in str(detail.get("reason")), f"reason={detail.get('reason')}")
        check("收工走 override_next(LordsStop)",
              ("LordsReadProgress", [impl.STOP_NODE]) in [(n, list(x)) for n, x in ctx.overrides],
              f"overrides={ctx.overrides}")

    # 全 M/M 当场收工
    all_done_frame = [
        ("更新列表", [615, 328, 82, 28]),
        ("八岐大蛇讨伐", [201, 1072, 165, 28]), ("通关数4/4", [547, 1120, 126, 28]),
    ]
    with hooks_100.FakeOcr(frame=all_done_frame):
        ctx = hooks_100.FakeContext()
        detail = reco.analyze(ctx, hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=205)).detail or {}
        check("全 M/M → 当场收工", detail.get("stop") is True)
        check("全 M/M → 原因「全部解禁」", "全部解禁" in str(detail.get("reason")), f"reason={detail.get('reason')}")

    # 不在列表页 → 不命中（不是随便返回个框）
    with hooks_100.FakeOcr(frame=hooks_100.DETAIL_FRAME):
        res = reco.analyze(hooks_100.FakeContext(), hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=206))
        check("详情页帧上 read 不命中", res.box is None, f"got={res.box}")

    # 安装态：取不到 scene/ → 不命中、不假成功
    saved = impl._logic
    try:
        impl._logic = lambda: None
        res = reco.analyze(hooks_100.FakeContext(), hooks_100.FakeArgv(reco_param={"mode": "read"}, task_id=207))
        check("安装态（无 scene/）read 不命中", res.box is None)
        check("安装态不命中时说明原因", impl.INSTALL_STATE_REASON in str((res.detail or {}).get("reason")))
    finally:
        impl._logic = saved
        impl.reset_sessions()

    # 动作在没有框时如实失败（不静默成功）
    check("没有可点框时动作返回 False",
          action.run(hooks_100.FakeContext(), hooks_100.FakeArgv(task_id=208, box=None)) is False)


# ---------------------------------------------------------------------------
# 7. 守卫 / 接线
# ---------------------------------------------------------------------------
def test_hooks() -> None:
    print("\n== 7. 挂点 #100：六个探针为 True + prove-red 成立 ==")
    check("lords-progress-parse 绿", hooks_100.probe_lords_progress_parse() is True)
    check("lords-plan-round 绿", hooks_100.probe_lords_plan_round() is True)
    check("lords-stop-conditions 绿", hooks_100.probe_lords_stop_conditions() is True)
    check("lords-no-deadloop 绿", hooks_100.probe_lords_no_deadloop() is True)
    check("lords-pipeline-wiring 绿", hooks_100.probe_lords_pipeline_wiring() is True)
    check("lords-agent-offline 绿", hooks_100.probe_lords_agent_offline() is True)

    # 每个挂点都要能变红（不靠 prove-red 也能单测）
    check("放宽 parse → 红", bool(hooks_100._parse_failures(parse=lambda t: (0, 0))))
    check("plan 恒给空目标 → 红", bool(hooks_100._plan_failures(
        plan=lambda rows, registry=None: RoundPlan(targets=(), all_done=True, rows=(), problems=()))))
    check("should_stop 恒 False → 红", bool(hooks_100._stop_failures(stop=lambda state: (False, ""))))
    check("摘掉注册表 → 红", bool(hooks_100._wiring_failures(reco_registry={}, action_registry={})))

    # pipeline：四个业务节点 + 收工出口都在
    files = hooks_100._pipelines()
    nodes = files.get(hooks_100.LORDS_FILE) or {}
    check("lords.json 在仓里且解析成对象", isinstance(nodes, dict) and bool(nodes))
    for name in hooks_100.REQUIRED_NODES + hooks_100.SUPPORT_NODES:
        check(f"节点 {name} 存在", isinstance(nodes.get(name), dict))

    check("prove_red() 成立（6 条破坏实验各自变红）", hooks_100.prove_red() is True)


# ---------------------------------------------------------------------------
# 8. #120：maa v5 的 Rect 不是 list（框解包保留浮点 + 动作异常必须留痕）
# ---------------------------------------------------------------------------
def _has_no_len(obj) -> bool:
    """这个对象是不是「没有 ``__len__``」的形状（真机 maa v5 的 ``Rect`` 就是这样）。"""
    try:
        len(obj)
    except TypeError:
        return True
    return False


def test_rect_compat() -> None:
    print("\n== 8. #120：假 Rect 也能点（浮点不丢）+ 动作异常留痕 ==")
    impl = hooks_100._impl()
    action = impl.LordsUnlockAction()

    # ① 假 Rect：只有 .x/.y/.w/.h，**没有** __len__（真机 TypeError: object of type 'Rect' has no len()）
    rect = hooks_120.FakeRect(481, 389, 117, 33)      # = LIST_FRAME 的「降临讨伐」页签框
    check("假 Rect 没有 __len__（真机那个 Rect 的替身）", _has_no_len(rect) is True)
    check("真 maa.define.Rect 也没有 __len__（本票的病因）", _has_no_len_maa_rect())
    check("_box_xywh(Rect) 解出四个分量",
          impl._box_xywh(rect) == (481, 389, 117, 33), f"got={impl._box_xywh(rect)!r}")
    check("_box_center(Rect) == 手算中心（浮点）",
          impl._box_center(rect) == (539.5, 405.5), f"got={impl._box_center(rect)!r}")

    # 注入的点击 hook：中心必须是**浮点原值**（不许被截断）
    verdict = {}
    with hooks_120.ClickRecorder() as recorder:
        verdict["ok"] = action._tab_click(
            hooks_100.FakeContext(),
            hooks_100.FakeArgv(task_id=9201, box=rect, act_param={"do": "tab"}),
            impl._session(9201),
        )
    check("_tab_click 用假 Rect 成功（页签真的点下去了，不再 TypeError）", verdict["ok"] is True,
          f"got={verdict['ok']!r}")
    check("_tab_click 传出的中心 = 框中心（浮点不丢）",
          recorder.centers() == [(539.5, 405.5)], f"got={recorder.centers()!r}")

    # 真机那条路：run → _click_box → PubClick（取整只许发生在 _click_box）
    ctx = hooks_100.FakeContext()
    ok = action.run(ctx, hooks_100.FakeArgv(task_id=9202, box=hooks_120.FakeRect(481, 389, 117, 33),
                                            act_param={"do": "tab"}))
    check("run(do=tab) 用假 Rect 成功并真的点了", ok is True and ctx.clicked_centers() == [(539, 405)],
          f"got={ctx.clicked_centers()!r}")

    # 默认 do=click 那条路也必须认 Rect（同一类崩溃的第二个入口）
    ctx2 = hooks_100.FakeContext()
    ok = action.run(ctx2, hooks_100.FakeArgv(task_id=9203, box=hooks_120.FakeRect(202, 640, 197, 28)))
    check("run(do=click) 用假 Rect 成功并被点下去",
          ok is True and ctx2.clicked_centers() == [(300, 654)], f"got={ctx2.clicked_centers()!r}")

    # ② 浮点不丢：Rect(12.5, 20.25, 3.0, 4.5) → 手算 (14.0, 22.5)；奇数宽度 197 → 300.5
    frac = hooks_120.FakeRect(12.5, 20.25, 3.0, 4.5)
    check("Rect(12.5,20.25,3.0,4.5) 的中心 == 手算 (14.0, 22.5)",
          impl._box_center(frac) == (14.0, 22.5), f"got={impl._box_center(frac)!r}")
    check("list 形态走同一条解包",
          impl._box_center([12.5, 20.25, 3.0, 4.5]) == (14.0, 22.5),
          f"got={impl._box_center([12.5, 20.25, 3.0, 4.5])!r}")
    check("奇数宽度 197 的中心 300.5 没被 int() 截断",
          impl._box_center([202, 640, 197, 28]) == (300.5, 654.0),
          f"got={impl._box_center([202, 640, 197, 28])!r}")

    # ③ 异常留痕：注入必抛 hook ⇒ 如实返回 False + 一行 ★动作异常★ + 类型 + 消息 + 栈
    log = io.StringIO()
    with hooks_120._Patched(impl, "_click_hook", hooks_120._boom), \
            redirect_stdout(log), redirect_stderr(log):
        ok = action.run(hooks_100.FakeContext(),
                        hooks_100.FakeArgv(task_id=9204, box=rect, act_param={"do": "tab"}))
    text = log.getvalue()
    check("必抛 hook ⇒ 动作如实返回 False（绝不假成功）", ok is False, f"got={ok!r}")
    check("日志有一行醒目的 ★动作异常★", impl.ACTION_ERROR_MARK in text,
          f"mark={impl.ACTION_ERROR_MARK!r}")
    check("日志带异常类型 + 消息", "RuntimeError" in text and "注入的必抛点击" in text)
    check("日志带完整栈（不是只有一行说明）", "Traceback (most recent call last)" in text,
          f"log={text[-200:]!r}")
    impl.reset_sessions()

    # ④ 守卫 hooks_120 四个挂点 + 破坏实验
    check("挂点 lords-rect-box-unpack 绿", hooks_120.probe_lords_rect_box_unpack() is True)
    check("挂点 lords-rect-float-center 绿", hooks_120.probe_lords_rect_float_center() is True)
    check("挂点 lords-action-error-trace 绿", hooks_120.probe_lords_action_error_trace() is True)
    check("挂点 lords-rect-no-len 绿（源码里没有 len(box)）", hooks_120.probe_lords_rect_no_len() is True)
    legs = hooks_120._prove_red_checks()
    check("破坏实验 ≥3 且每条都变红",
          len(legs) >= 3 and all(red for _name, red, _first in legs),
          f"got={[(n, r) for n, r, _f in legs]}")
    check("hooks_120.prove_red() 成立", hooks_120.prove_red() is True)


def _has_no_len_maa_rect() -> bool:
    """真 ``maa.define.Rect`` 是不是也没有 ``__len__``（本票的病因断言）。"""
    try:
        from maa.define import Rect as MaaRect
    except Exception:  # noqa: BLE001 - 取不到就说不成立（不静默跳过）
        return False
    return _has_no_len(MaaRect())


# ---------------------------------------------------------------------------
# 9. #100 第 3 条真机缺口：pick 前先对页签、再上下找（三原因分开）
# ---------------------------------------------------------------------------
def test_pick_locate() -> None:
    print("\n== 9. #100-3：pick 前先对页签 / 再上下找 / 三种原因分开 ==")
    impl = hooks_100._impl()
    nav = hooks_100._lords_nav()
    fakes = hooks_100

    # ① 前提：票面说「无猾机兵在领主战页签」——仓内静态数据说的是**降临讨伐**
    check(
        f"前提：{hooks_121.PICK_TARGET_ROW} 的页签 = {hooks_121.PICK_TARGET_TAB}（scene/lords.py 的 kind）",
        nav.tab_of_row(hooks_121.PICK_TARGET_ROW) == hooks_121.PICK_TARGET_TAB,
        f"got={nav.tab_of_row(hooks_121.PICK_TARGET_ROW)!r}",
    )
    ev = nav.tab_state(hooks_121.PICK_FRAME_JOSS_BOTTOM)
    check("证据帧（lords_pick_stuck_on_joss_tab.png）确认页签 = 降临讨伐", ev.confirmed == hooks_121.PICK_TARGET_TAB,
          f"confirmed={ev.confirmed!r} kinds={ev.kinds}")
    rows, _orphans = group_progress_rows(hooks_121.PICK_FRAME_JOSS_BOTTOM)
    check("证据帧读到 5 行", len(rows) == 5, f"got={[r.name for r in rows]}")
    check("证据帧里没有目标行（它被滚出屏幕了）",
          all(row.name != hooks_121.PICK_TARGET_ROW for row in rows), f"got={[r.name for r in rows]}")

    # ② 页签先行：目标 joss、当前 lord ⇒ 先点页签，且不消耗死线
    with fakes.FakeOcr(frames=[fakes.LIST_FRAME, fakes.TAB_FRAME_JOSS]), \
            fakes.FakeClock(1000.0) as clock, fakes.FakeSleeper():
        ctx = hooks_121.PickContext()
        task = 9501
        session, _state = hooks_121._ready_session(impl, nav, task, now=clock.now)
        session.last_click_at = clock.now - (impl.STUCK_SEC - 1.0)
        step = hooks_121._pick(impl, ctx, task)
        detail = dict(step.detail or {})
        want = nav.label_box(fakes.LIST_FRAME, nav.TAB_ANCHORS[hooks_121.PICK_TARGET_TAB])
        check("pick 先给页签框（what=tab）", detail.get("what") == impl.WHAT_TAB, f"got={detail.get('what')!r}")
        check("页签框 = 当帧标签框", list(step.box or []) == list(want), f"got={step.box!r} want={list(want)}")
        check("动作点下去成功", impl.LordsUnlockAction().run(
            ctx, fakes.FakeArgv(task_id=task, box=step.box)) is True)
        check("点页签不算「点了一次目标」", session.attempts_since_read == 0,
              f"got={session.attempts_since_read}")
        check("点页签刷新了「点不出去」死线基准（导航不消耗死线）",
              session.last_click_at > clock.now - (impl.STUCK_SEC - 1.0), f"got={session.last_click_at}")
        nxt = hooks_121._pick(impl, ctx, task)
        check("页签确认后直接点目标行", (nxt.detail or {}).get("what") == impl.WHAT_ROW,
              f"got={(nxt.detail or {}).get('what')!r}")

    # ③ 上下找：「行在第 3 屏」⇒ 滚 2 次后找到（不是直接放弃）
    frames = hooks_121._ScreenFrames
    with fakes.FakeOcr(frames=[frames.FIRST, frames.SECOND, frames.FOUND]), \
            fakes.FakeClock(3000.0) as clock, fakes.FakeSleeper() as sleeper:
        ctx = hooks_121.PickContext()
        task = 9502
        session, _state = hooks_121._ready_session(impl, nav, task, now=clock.now)
        whats = []
        for _ in range(3):
            res = hooks_121._pick(impl, ctx, task)
            whats.append((res.detail or {}).get("what"))
            if session.pending is not None:
                impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
                clock.advance(float(nav.SCROLL_PLAN.min_interval_sec) + 0.5)
        check("「行在第 3 屏」= 连滚 2 次向下再点行",
              whats == [impl.WHAT_SCROLL_DOWN, impl.WHAT_SCROLL_DOWN, impl.WHAT_ROW], f"got={whats}")
        check("滚动补足了 settle_ms 的稳定等待（#42 惯性）",
              float(nav.SCROLL_PLAN.settle_ms) / 1000.0 in sleeper.calls, f"got={sleeper.calls!r}")

    # ④ 向下到底 ⇒ 反向向上找（同一个手势反向）
    with fakes.FakeOcr(frames=[frames.FIRST] * 3 + [frames.FOUND]), \
            fakes.FakeClock(4000.0) as clock, fakes.FakeSleeper():
        ctx = hooks_121.PickContext()
        task = 9503
        session, _state = hooks_121._ready_session(impl, nav, task, now=clock.now)
        whats = []
        for _ in range(4):
            res = hooks_121._pick(impl, ctx, task)
            whats.append((res.detail or {}).get("what"))
            if session.pending is not None:
                impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
                clock.advance(float(nav.SCROLL_PLAN.min_interval_sec) + 0.5)
        check("向下到底后改向上找，找到再点行",
              whats[:3] == [impl.WHAT_SCROLL_DOWN, impl.WHAT_SCROLL_DOWN, impl.WHAT_SCROLL_UP]
              and whats[-1] == impl.WHAT_ROW, f"got={whats}")
        ups = [
            ((override or {}).get(impl.SCROLL_NODE) or {}).get("action", {}).get("param", {})
            for node, override in ctx.gestures()
            if node == impl.SCROLL_NODE
            and list((((override or {}).get(node) or {}).get("action", {}).get("param", {}) or {}).get("end") or [])
            == list(nav.SCROLL_PLAN.up_end)
        ]
        check("向上滚 = 同一个手势反向（几何只有 SCROLL_PLAN 一份）",
              bool(ups) and list(ups[0].get("begin") or []) == list(nav.SCROLL_PLAN.up_begin),
              f"got={ups!r}")

    # ⑤ 三个挂点 + 破坏实验
    check("挂点 lords-pick-tab-first 绿", hooks_121.probe_lords_pick_tab_first() is True)
    check("挂点 lords-pick-scroll-search 绿", hooks_121.probe_lords_pick_scroll_search() is True)
    check("挂点 lords-pick-reasons 绿", hooks_121.probe_lords_pick_reasons() is True)
    check("挂点 lords-pick-nav-snapshot-parity 绿", hooks_121.probe_lords_pick_nav_snapshot_parity() is True)
    legs = hooks_121._prove_red_checks()
    check("破坏实验 ≥3 且每条都变红", len(legs) >= 3 and all(red for _n, red, _f in legs),
          f"got={[(n, r) for n, r, _f in legs]}")
    check("hooks_121.prove_red() 成立", hooks_121.prove_red() is True)

    # ⑥ 三种原因的文案必须能一眼分开（逐字子串，运维口径）
    reasons = {
        "tab": nav.PICK_REASON_TAB,
        "not_found": nav.PICK_REASON_NOT_FOUND,
        "click": nav.PICK_REASON_CLICK,
    }
    check("三种失败原因文案互不相同", len(set(reasons.values())) == 3, f"got={reasons}")
    check("三种文案分别含「不在这个页签」/「滚到底也没找到」/「点不动」",
          "不在这个页签" in reasons["tab"]
          and "滚到底也没找到" in reasons["not_found"]
          and "点不动" in reasons["click"], f"got={reasons}")


# ---------------------------------------------------------------------------
# 10. #100 缺口 7/8：模式页正向复核 + 换点阶梯 + 盲点 (0,0) 拒绝
# ---------------------------------------------------------------------------
def test_mode_ladder() -> None:
    print("\n== 10. #100-7/8：正向复核（不再「离开模式页即成功」）+ 换点阶梯 + 盲点拒绝 ==")
    impl = hooks_100._impl()
    nav = hooks_100._lords_nav()
    fakes = hooks_100

    # ① 数据 = 票面（四点 / 每点轮询 / 最多 4 个点 / 加成确认框）
    check(
        "换点阶梯 = 中心 → 下方100 → 右侧120 → 下方180（票面顺序）",
        tuple(nav.LORDS_MODE_CLICK_LADDER)
        == (("中心", 0, 0), ("下方", 0, 100), ("右侧", 120, 0), ("底部", 0, 180)),
        f"got={tuple(nav.LORDS_MODE_CLICK_LADDER)!r}",
    )
    check(
        "每个点轮询读帧（间隔 0.4s / 单点 ≤8s）",
        0.2 <= float(nav.LORDS_MODE_POLL_INTERVAL_SEC) <= 0.5
        and float(nav.LORDS_MODE_POLL_TIMEOUT_SEC) <= 8.0,
        f"got={nav.LORDS_MODE_POLL_INTERVAL_SEC!r}/{nav.LORDS_MODE_POLL_TIMEOUT_SEC!r}",
    )
    check("最多 4 个点（含首次）", int(nav.LORDS_MODE_MAX_ATTEMPTS) == 4,
          f"got={nav.LORDS_MODE_MAX_ATTEMPTS!r}")
    reason = nav.mode_click_exhausted_reason("lords_unknown", None)
    check(
        "全失败收工原因**只写读数**（含「4 个点都试过」/ state=… / 不是编队页；不写「画面仍是模式页」）",
        all(needle in reason for needle in ("4 个点都试过", "state=lords_unknown", "不是编队页"))
        and "画面仍是模式页" not in reason,
        f"got={reason!r}",
    )
    dialog = nav.bonus_dialog(hooks_122.BONUS_DIALOG_FRAME)
    check(
        "加成确认框：问题锚 + 「否」按钮框都来自当帧 OCR，默认点「否」",
        dialog.is_dialog
        and tuple(dialog.decline) == (178, 805, 37, 37)
        and tuple(dialog.accept) == (504, 805, 36, 36)
        and nav.LORDS_MODE_BONUS_CHOICE == "否",
        f"got={dialog.summary()}/{nav.LORDS_MODE_BONUS_CHOICE!r}",
    )
    check(
        "加成确认框：读不到「否」按钮框 ⇒ 不算确认框（不盲点）",
        nav.bonus_dialog(hooks_122.BONUS_DIALOG_NO_DECLINE_FRAME).is_dialog is False,
    )
    points = tuple(nav.mode_click_points(hooks_122.SOLO_BOX))
    check("单人框中心 = 阶梯第 1 点 (170,523)",
          points and points[0] == ("中心", 170.0, 523.0), f"got={points!r}")
    check("第 2 点 = 下方 100px / 第 3 点 = 右侧 120px / 第 4 点 = 下方 180px",
          points == (
              ("中心", 170.0, 523.0),
              ("下方", 170.0, 623.0),
              ("右侧", 290.0, 523.0),
              ("底部", 170.0, 703.0),
          ), f"got={points!r}")
    check("无效框算不出换点阶梯（不会点出 (0,0)）",
          tuple(nav.mode_click_points((0, 0, 0, 0))) == ()
          and tuple(nav.mode_click_points(None)) == ())

    # ② 正向证据：编队页 = 挑战 + SET/Party/自动续战 之一
    check("真机编队页帧（挑战 + 自动续战）⇒ 明确是编队页",
          nav.team_page_confirmed(fakes.TEAM_FRAME) is True)
    check("只有【挑战】、没有三个锚 ⇒ 不算编队页（正向证据缺一半）",
          nav.team_page_confirmed((("挑战", [297, 1069, 80, 47]),)) is False)
    check("瞬时 unknown 帧 ⇒ 不算编队页", nav.team_page_confirmed(hooks_122.UNKNOWN_FRAME) is False)

    # ③ 「点完 → 瞬时 unknown → 又回到模式页」：必须判失败（旧判据会判成功）
    session = impl.Session(task_id=9971)
    session.mode_clicks = 1
    unknown = impl._note_mode_result(session, nav.LORDS_STATE_UNKNOWN, nav, hooks_122.UNKNOWN_FRAME)
    check("点完 → 瞬时 unknown：unconfirmed（不是成功、不清账）",
          unknown == "unconfirmed:lords_unknown" and session.mode_clicks == 1, f"got={unknown!r}")
    still = impl._note_mode_result(session, nav.LORDS_STATE_MODE, nav, hooks_122.MODE_FRAME_A)
    check("又回到模式页：still_mode（点击没生效）",
          still == "still_mode" and session.mode_clicks == 1, f"got={still!r}")
    team = impl._note_mode_result(session, nav.LORDS_STATE_TEAM, nav, fakes.TEAM_FRAME)
    check("只有编队页才 team_page 并清掉点击账",
          team == "team_page" and session.mode_clicks == 0, f"got={team!r}")

    # ③b 真机 484（2026-10-18 夜）：点「单人游戏」→ **加成点数确认框** → 点「否」→ 编队页
    impl.reset_sessions()
    task = 9974
    with fakes.FakeOcr(frame=hooks_122.MODE_FRAME_A), fakes.FakeClock(12000.0), fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        res = impl.LordsProgressRecognition().analyze(
            ctx,
            fakes.FakeArgv(reco_param={"mode": "solo"}, task_id=task, node_name="LordsModeSolo"),
        )
        with hooks_122._ladder_env(
            impl, [hooks_122.BONUS_DIALOG_FRAME, fakes.TEAM_FRAME]
        ) as calls:
            ok = impl.LordsUnlockAction().run(ctx, fakes.FakeArgv(task_id=task, box=res.box))
        session = impl._session(task)
        check(
            "加成确认框 → 点「否」（OCR 框中心）→ 编队页：这一跳成功",
            ok is True
            and len(calls) == 2
            and abs(calls[1][0] - 196.5) <= 1
            and abs(calls[1][1] - 823.5) <= 1,
            f"ok={ok!r} calls={calls!r}",
        )
        check(
            "确认框点击记 1 次、同一次跳只记 1 次目标点击",
            session.mode_dialog_clicks == 1 and session.attempts_since_read == 1,
            f"got={session.mode_dialog_clicks}/{session.attempts_since_read}",
        )
    impl.reset_sessions()

    # ④ 盲点 (0,0)：框无效 ⇒ 点击函数不被调用（注入 _click_hook 计数）
    for label, box in (("box=[0,0,0,0]", (0, 0, 0, 0)), ("box 缺失", None)):
        with hooks_120.ClickRecorder() as recorder:
            ok = impl.LordsUnlockAction().run(
                hooks_100.FakeContext(), hooks_100.FakeArgv(task_id=9972, box=box)
            )
        check(f"{label} ⇒ 拒绝点击（_click_hook 0 次调用）",
              ok is False and recorder.centers() == [], f"ok={ok!r} calls={recorder.centers()!r}")
    check("_box_center 对无效框返回 None（(0,0) 不再被当成可点中心）",
          impl._box_center((0, 0, 0, 0)) is None
          and impl._box_center(None) is None
          and impl._box_center([202, 640, 197, 28]) == (300.5, 654.0))

    # ⑤ 收工命中：动作必须「成功但不点」（否则 on_error 回枢纽，override 的 LordsStop 作废）
    with hooks_120.ClickRecorder() as recorder:
        impl._session(9973).stop_requested = True
        ok = impl.LordsUnlockAction().run(
            hooks_100.FakeContext(), hooks_100.FakeArgv(task_id=9973, box=(0, 0, 0, 0))
        )
    check("已判收工 ⇒ 动作成功但不点（收工不会被 on_error 打回枢纽）",
          ok is True and recorder.centers() == [], f"ok={ok!r} calls={recorder.centers()!r}")
    impl.reset_sessions()

    # ⑥ 守卫（hooks_122 的新挂点 + 十六条破坏实验）
    check("挂点 lords-mode-positive-verify 绿", hooks_122.probe_lords_mode_positive_verify() is True)
    check("挂点 lords-mode-click-ladder 绿", hooks_122.probe_lords_mode_click_ladder() is True)
    check("挂点 lords-mode-bonus-dialog 绿", hooks_122.probe_lords_mode_bonus_dialog() is True)
    check("挂点 lords-pick-diag-rate-limit 绿", hooks_122.probe_lords_pick_diag_rate_limit() is True)
    check("挂点 lords-click-no-blind-point 绿", hooks_122.probe_lords_click_no_blind_point() is True)
    legs = hooks_122._prove_red_checks()
    check("破坏实验 ≥16 且每条都变红",
          len(legs) >= 16 and all(red for _name, red, _first in legs),
          f"got={[(n, r) for n, r, _f in legs]}")
    check("hooks_122.prove_red() 成立", hooks_122.prove_red() is True)


# ---------------------------------------------------------------------------
# 11. #100 补充（真机 484，14:5x）：过渡态（loading）不累加「无进展」计时
# ---------------------------------------------------------------------------
def test_transition_frame() -> None:
    print("\n== 11. #100 补充：过渡态（loading）不许被「非列表页死线」误杀 ==")
    impl = hooks_100._impl()
    nav = hooks_100._lords_nav()
    fakes = hooks_100

    # ① 判据：加载帧有自己的名字，认不出的帧仍是 lords_unknown（不猜）
    check("加载帧 → lords_loading（判据 = 请耐心等待 / 健康游戏忠告）",
          impl.classify(hooks_122.LOADING_FRAME) == nav.LORDS_STATE_LOADING,
          f"got={impl.classify(hooks_122.LOADING_FRAME)!r}")
    check("带百分比的加载帧也算（请耐心等待 79.28%）",
          impl.classify(hooks_122.LOADING_FRAME_PCT) == nav.LORDS_STATE_LOADING,
          f"got={impl.classify(hooks_122.LOADING_FRAME_PCT)!r}")
    check("认不出的帧仍是 lords_unknown（半渲染帧不许被当成过渡态）",
          impl.classify(hooks_122.UNKNOWN_FRAME) == nav.LORDS_STATE_UNKNOWN,
          f"got={impl.classify(hooks_122.UNKNOWN_FRAME)!r}")

    # ② 真机形状：unknown(2s) → loading(3s) → unknown(2s) ⇒ 不许收工
    with fakes.FakeOcr(frames=[
        hooks_122.UNKNOWN_FRAME, hooks_122.LOADING_FRAME,
        hooks_122.UNKNOWN_FRAME, hooks_122.UNKNOWN_FRAME,
    ]), fakes.FakeClock(11000.0) as clock, fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        task = 9981
        seen = []
        stops = []
        for seconds in (2.0, 3.0, 2.0, 2.0):
            detail = dict(hooks_122._tab(impl, ctx, task).detail or {})
            seen.append(detail.get("state"))
            if detail.get("stop"):
                stops.append((detail.get("state"), detail.get("reason")))
            clock.advance(seconds)
        check("帧序列的 state = unknown → loading → unknown → unknown",
              seen == [nav.LORDS_STATE_UNKNOWN, nav.LORDS_STATE_LOADING,
                       nav.LORDS_STATE_UNKNOWN, nav.LORDS_STATE_UNKNOWN],
              f"got={seen!r}")
        check("★过渡帧序列不收工★（真机 14:5x 的误杀形状）", stops == [], f"got={stops!r}")

    # ③ 连续 15s 的加载帧 ⇒ 仍不收工（loading 可以久到几十秒）
    impl.reset_sessions()
    with fakes.FakeOcr(frame=hooks_122.LOADING_FRAME), fakes.FakeClock(12000.0) as clock, \
            fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        task = 9982
        stops = []
        for index in range(6):
            detail = dict(hooks_122._tab(impl, ctx, task).detail or {})
            if detail.get("stop"):
                stops.append((3 * index, detail.get("reason")))
                break
            clock.advance(3.0)
        check("连续 15s 的加载帧不收工（过渡态不累加「没有进展」）", stops == [], f"got={stops!r}")

    # ④ 对照：lords_unknown 连续 12s（没有 loading 打断）⇒ **必须**收工（没放行过头）
    impl.reset_sessions()
    with fakes.FakeOcr(frame=hooks_122.UNKNOWN_FRAME), fakes.FakeClock(13000.0) as clock, \
            fakes.FakeSleeper():
        ctx = fakes.FakeContext()
        task = 9983
        hooks_122._tab(impl, ctx, task)
        clock.advance(float(nav.NON_LIST_STUCK_SEC) + 3.0)
        detail = dict(hooks_122._tab(impl, ctx, task).detail or {})
        check("lords_unknown 连续 12s ⇒ 收工且原因带状态名（未知画面的死线仍在）",
              bool(detail.get("stop")) and nav.LORDS_STATE_UNKNOWN in str(detail.get("reason") or ""),
              f"got={detail.get('reason')!r}")

    # ⑤ 守卫：两个新挂点 + 三条新破坏实验
    check("挂点 lords-transition-not-stuck 绿",
          hooks_122.probe_lords_transition_not_stuck() is True)
    check("挂点 lords-unknown-still-bounded 绿",
          hooks_122.probe_lords_unknown_still_bounded() is True)
    legs = hooks_122._prove_red_checks()
    reds = [name for name, red, _first in legs if red]
    check("破坏实验 ≥13 且每条都变红",
          len(legs) >= 13 and len(reds) == len(legs),
          f"got={[(n, r) for n, r, _f in legs]}")
    check("破坏实验 ⑪（把 loading 移出过渡集）/ ⑫（unknown 也当过渡）/ ⑬（不再认加载页）都在",
          any("⑪" in name for name in reds)
          and any("⑫" in name for name in reds)
          and any("⑬" in name for name in reds),
          f"got={reds[-3:]!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 74)
    print("离线单测：#100 领主战「全难度解禁」—— scene/lords_unlock + agent/lords_impl + lords.json + hooks_100")
    print("=" * 74)
    test_parse_progress()
    test_group_rows()
    test_plan_round()
    test_should_stop()
    test_round_gained()
    test_loop_semantics()
    test_agent()
    test_hooks()
    test_rect_compat()
    test_pick_locate()
    test_mode_ladder()
    test_transition_frame()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
