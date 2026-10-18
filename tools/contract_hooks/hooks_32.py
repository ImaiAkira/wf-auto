# -*- coding: utf-8 -*-
"""#32（#111 降级）：领主战类【成员表 / 难度词表】+ 逐成员难度 = **账号快照**。

seam：``scene.lord_battle``（成员表 + 逐成员难度 = 数据真源，ADR-0001）↔
``scene.config.DIFFICULTIES``（难度词表）↔ ``scene.options``（派生的 GUI 选项：按行名 OCR 选行）
↔ **``scene.lords``（难度事实的唯一真源：M / 解锁链 / 认证文本 / 证据）**。

背景（#32 真机战役，2026-10-13，设备 127.0.0.1:16385）
----------------------------------------------------
真机「领主战 / 降临讨伐」两个页签做了**全量行扫**（scroll-sweep OCR），逐个成员进详情页
读出可用难度。结果：领主战 **17**、降临讨伐 **29**（旧配置 15 + 24 = 39）。旧配置漏了
``妖狐讨伐`` 与六名降临成员、把不存在的 ``石芯心六`` 当成员、并因 #21 误删了
``诅咒弧魔艾基尔讨伐``。逐成员难度在 2026-10-13 也读过一遍 —— ★但那份读数**只是账号快照**★
（#106 证伪：同一帧列表页 4 行里 3 行不符；无猾机兵实测 M=5 而旧表记 4），见下面的降级说明。

离线证据（内嵌；套件不碰设备、不读 ``%TEMP%``）
---------------------------------------------
``%TEMP%\\opencode\\`` 的冻结产物被作为**常量内嵌**在本文件里（与既有挂点内嵌真机 OCR 同一
思路），因此套件离线自足、可复算：

* 行名行扫：``sweep_lord_00..04.ocr.txt`` / ``sweep_joss_00..07.ocr.txt`` + ``sweep_result.json``；
* 逐成员难度（**快照**）：``diff_summary.json``（2026-10-13 清关账号的详情页读数）；
* 详情页旁证：``detail_report.json``（``石芯心六`` nav=False / diff=[]，从未打开）。

守卫 ``lord-roster-and-difficulties-on-device``（离线能求值的全部）
-----------------------------------------------------------------
1. 领主战成员**集合** == 真机 17 行；降临讨伐 == 真机 29 行（集合相等；顺序无业务含义 ——
   列表按【行名】OCR 选行，顺序不参与识别）；
2. 不存在的 ``石芯心六`` **不在**配置里；
3. #21 回归：``艾基尔·嫉妒讨伐`` 与 ``诅咒弧魔艾基尔讨伐`` **两者都在**（真机第 1 / 第 10 行）；
4. ``scene.config.DIFFICULTIES`` 含 ``地狱级``；
5. ★#111 改语义★ 逐成员难度是**账号快照**，不是「该成员支持哪些难度」（#106 用同一帧列表页
   证伪：4 行里 3 行不符；``无猾机兵`` 实测 M=5 而旧表记 4）。因此本节**不再**断言
   「配置 == 真机事实」（那是「两个错的东西互相证明对方对」，调研 §5.4 的原话），改成两条：
   (5a) **投影一致**：配置里的账号快照 == 本文件内嵌的快照（逐成员；夹具是配置的子集），
        谁单方面改了都红 —— 这是「两份快照对账」，不是「快照==关卡事实」；
   (5b) **不冲突**：快照与 ``scene.lords``（唯一事实源）**不冲突** —— 成员在花名册、
        每档 ∈ ``DIFFICULTIES``、``len(快照) <= M``、链已知时 ``快照 ⊆ 链``；
        ★这里不校验「本账号现在能打哪几档」★（账号状态，离线永远比不了）；
6. 真机事实：降临讨伐**无一成员**含 ``初级``（未测定成员亦然）；
7. 派生的 GUI 选项名 == 成员行名（N → N，不丢不重、不吞覆盖）；
8. 修正来源（帧 / 运行 / 产物名）必须在 ``scene/lord_battle.py`` 源码里在场。

★诚实边界★
本守卫只核「离线可求值」的部分：行名集合 / 难度集合 / 快照一致性。页面判据、链、事件层由
``scene.drift.check_all`` 的其他检查负责；真机**顺序**、OCR 字面由行扫帧本身负责
（本守卫不复算 OCR —— 冻结帧在 ``%TEMP%``，不进仓）。
★本守卫曾经守错了方向★：2026-10-13 那份「逐成员可用难度集」本身就是错的（#106 §2.4 证明
3/4 行不符），而老守卫断言「配置 == 这份夹具」—— 两个错的东西互相证明对方对。现在夹具被降级为
:data:`ACCOUNT_SNAPSHOTS`（带账号 / 时间 / 帧三要素），正确性交给 ``scene.lords`` 对账。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_32.py``）：
① 删掉成员 ``妖狐讨伐``（临时 scene 副本）-> 守卫必须变红；
② 给快照塞一个超出 M 的成员档数 -> (5b) 必须变红。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

HOOK_ID = "lord-roster-and-difficulties-on-device"

# ---------------------------------------------------------------------------
# 真机行扫：两个页签的全部行名（#32，2026-10-13 @127.0.0.1:16385）。
# 来源：sweep_lord_*/sweep_joss_*.ocr.txt + sweep_result.json（逐帧滚动链重建的行序）。
# ---------------------------------------------------------------------------
DEVICE_LORDS = frozenset({
    # 第 1 行（sweep_lord_00 / sweep_entry @y=640）
    "艾基尔·嫉妒讨伐",
    "猩红巨熊讨伐", "背鳍三兄弟讨伐", "八岐大蛇讨伐",
    # 第 5 行（sweep_lord_01 @y=565）——旧配置漏掉的一行
    "妖狐讨伐",
    "管理者讨伐", "Sec-5200Li讨伐", "白虎讨伐", "风将獠牙骑士讨伐",
    # 第 10 行（sweep_lord_02 @y=628）——#21 误删的一行
    "诅咒弧魔艾基尔讨伐",
    "寄居蟹船长讨伐", "潮汐巨妖讨伐", "废墟魔像讨伐", "废墟守卫·火讨伐",
    "不死王瑞西塔尔讨伐", "雷霆树妖讨伐", "维·索拉斯讨伐",
})

DEVICE_JOSS = frozenset({
    "无猾机兵", "红嫉机兵", "苍叹机兵", "橙悚机兵",
    "碧愁机兵",  # sweep_joss_01 @y=694
    "闪哭机兵", "暗凛机兵", "始龙之眼", "为你奏响的镇魂歌", "圣夜的淘气鬼",
    "怨炎精灵兽", "水狂精灵兽", "魁雷精灵兽", "威风精灵兽", "巫光精灵兽", "暗唤精灵兽",
    "方舟守护者讨伐", "赤之女王讨伐", "青之女王讨伐",
    "金之女王讨伐",  # sweep_joss_04 @y=889
    "碧之女王讨伐", "皓之女王讨伐", "墨之女王讨伐",
    "伊尔昂斯拉讨伐", "伊尔梅塔雷讨伐",
    "伊尔格拉乌讨伐",  # sweep_joss_05 @y=1092
    "伊劳德雷斯讨伐",  # sweep_joss_06 @y=782
    "伊萨巴迪卡讨伐",  # sweep_joss_06 @y=929
    "伊尔考普斯讨伐",  # sweep_joss_06 @y=1073
})

# 真机不存在、必须从配置里移除的成员。
NONEXISTENT_MEMBERS = ("石芯心六",)

# #21 回归修正：真机两行同时存在。
EKIEL_BOTH = ("艾基尔·嫉妒讨伐", "诅咒弧魔艾基尔讨伐")

# ---------------------------------------------------------------------------
# ★逐成员难度 = **账号快照**，不是「该成员支持哪些难度」★
#
# #111 降级（原名 ``DEVICE_DIFFICULTIES``）：这份表是**某账号某时刻**在详情页**看得见的档**，
# 不是关卡事实。理由有两条硬证据：
#   · 同一成员两个账号：红嫉机兵在清关账号 4 档、早期账号只有 中级
#     （tools/frames/lord_detail_redjoss_{cleared,early}.png 两张仓内帧直接对照）；
#   · 同一帧列表页证伪了整张表：艾基尔·嫉妒 1/4、背鳍三兄弟 1/4、八岐大蛇 4/4
#     （docs/research/lord-battle-difficulty-registry.md §2.4）；无猾机兵实测 M=5 而旧表记 4。
#
# ⇒ 语义 =「**离线兜底 / 回归基线**」，正确性由 ``scene.lords``（M / 解锁链）对账，
#   **不再**由「配置 == 这份夹具」证明。
# ---------------------------------------------------------------------------
#: 采集**账号**（快照三要素之一）。
ACCOUNT_SNAPSHOT_ACCOUNT = "CET-AL00 / RANK158（清关账号）/ 设备 127.0.0.1:16385"
#: 采集**时间**（快照三要素之二）。
ACCOUNT_SNAPSHOT_CAPTURED_AT = "2026-10-13"
#: 采集**帧 / 产物**（快照三要素之三）。``artifact:`` = 仓外产物（``%TEMP%`` 已不可得）。
ACCOUNT_SNAPSHOT_FRAMES: tuple[str, ...] = (
    "tools/frames/lord_detail_redjoss_cleared.png",
    "tools/frames/lord_detail_redjoss_early.png",
    "artifact:%TEMP%\\opencode\\diff_summary.json",
    "artifact:%TEMP%\\opencode\\det_*.ocr.txt",
)

#: 逐成员**观察**（内嵌自 ``diff_summary.json``，2026-10-13）。只列**战役矩阵覆盖到**的成员；
#: 未覆盖成员（赤之女王讨伐 / 妖狐讨伐 / 诅咒弧魔艾基尔讨伐 / 六名新增降临）不在此表。
#: ★它是快照，不是「支持难度集」★：换账号就变；M 的真源是 ``scene.lords``。
#: 值是 ``frozenset``（既有读者 ``tools/test_lord_data.py`` 直接拿它跟 ``frozenset(...)`` 比）。
ACCOUNT_SNAPSHOTS: dict[str, frozenset[str]] = {
    # ---- 领主战（15，旧配置成员）----
    "Sec-5200Li讨伐": frozenset({"中级"}),
    "不死王瑞西塔尔讨伐": frozenset({"超级", "高级+", "高级", "中级"}),
    "八岐大蛇讨伐": frozenset({"超级", "高级+", "高级"}),
    "寄居蟹船长讨伐": frozenset({"中级"}),
    "废墟守卫·火讨伐": frozenset({"中级"}),
    "废墟魔像讨伐": frozenset({"中级"}),
    "潮汐巨妖讨伐": frozenset({"超级", "高级", "中级", "高级+"}),
    "猩红巨熊讨伐": frozenset({"高级", "超级", "高级+", "中级"}),
    "白虎讨伐": frozenset({"超级", "高级+", "高级", "中级"}),
    "管理者讨伐": frozenset({"高级", "超级", "高级+", "中级"}),
    "维·索拉斯讨伐": frozenset({"初级", "超级", "高级+"}),
    "背鳍三兄弟讨伐": frozenset({"高级", "中级"}),
    "艾基尔·嫉妒讨伐": frozenset({"中级"}),
    "雷霆树妖讨伐": frozenset({"高级", "超级", "高级+", "中级"}),
    "风将獠牙骑士讨伐": frozenset({"高级+", "超级", "高级", "中级"}),
    # ---- 降临讨伐（22，旧配置成员里打开过详情页的）----
    "无猾机兵": frozenset({"超级", "地狱级", "高级+", "高级"}),
    "红嫉机兵": frozenset({"超级", "高级+", "高级", "中级"}),
    "苍叹机兵": frozenset({"高级+", "超级", "高级", "中级"}),
    "橙悚机兵": frozenset({"高级+", "超级", "高级", "中级"}),
    "闪哭机兵": frozenset({"高级", "超级", "高级+", "中级"}),
    "暗凛机兵": frozenset({"高级+", "超级", "高级", "中级"}),
    "始龙之眼": frozenset({"超级", "高级", "高级+", "中级"}),
    "为你奏响的镇魂歌": frozenset({"超级", "高级+", "高级", "中级"}),
    "圣夜的淘气鬼": frozenset({"高级+", "地狱级", "超级", "高级"}),
    "怨炎精灵兽": frozenset({"高级+", "高级", "地狱级", "超级"}),
    "水狂精灵兽": frozenset({"高级+", "地狱级", "超级", "高级"}),
    "魁雷精灵兽": frozenset({"高级+", "地狱级", "超级", "高级"}),
    "威风精灵兽": frozenset({"超级", "高级+", "地狱级", "高级"}),
    "巫光精灵兽": frozenset({"地狱级", "超级", "高级+", "高级"}),
    "暗唤精灵兽": frozenset({"高级+", "地狱级", "超级", "高级"}),
    "方舟守护者讨伐": frozenset({"中级"}),
    "青之女王讨伐": frozenset({"中级"}),
    "碧之女王讨伐": frozenset({"超级", "高级", "地狱级", "高级+"}),
    "皓之女王讨伐": frozenset({"超级", "高级+", "高级", "地狱级"}),
    "墨之女王讨伐": frozenset({"超级", "高级", "地狱级", "高级+"}),
    "伊尔昂斯拉讨伐": frozenset({"超级", "高级", "高级+", "中级"}),
    "伊尔梅塔雷讨伐": frozenset({"高级+", "高级", "中级", "超级"}),
}

#: ★旧名（仅为既有读者保留，**不要再新增读者**）★：
#: ``tools/test_lord_data.py`` 与 ``tools/contract_hooks/hooks_39.py`` 仍按这个名字读它，
#: 而那两张票不在 #111 的改动边界内 ⇒ 别名保留，语义**已降级**为账号快照（见上）。
#: 新代码请用 :data:`ACCOUNT_SNAPSHOTS`；「配置 == 它」不再被当作证明（见守卫第 5 条）。
DEVICE_DIFFICULTIES: dict[str, frozenset[str]] = ACCOUNT_SNAPSHOTS

# 必须出现在 scene/lord_battle.py 源码里的来源串（数据修正处记录来源，不得随改动被抹掉）。
EVIDENCE_STRINGS = (
    "sweep_lord_01.ocr.txt",
    "sweep_lord_02.ocr.txt",
    "sweep_joss_01.ocr.txt",
    "sweep_result.json",
    "diff_summary.json",
)


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _snapshot_conflict_failures(
    snapshots=None,
    entries=None,
    difficulties=None,
    label: str = "账号快照",
) -> list[str]:
    """★#111 的核心断言★：逐成员**账号快照**与 ``scene/lords.py``（唯一事实源）**不冲突**。

    可判定的四条（每条都只依赖仓内数据）：

    1. 快照里的行名必须是花名册成员（``scene.lords.LORDS``）；
    2. 每档 ∈ ``scene.config.DIFFICULTIES``；
    3. ``len(快照) <= M`` —— 快照是「那一刻看得见的档」，最多等于 M，**不可能多于 M**
       （多于 M 说明 M 或快照至少一个错了）；
    4. 链已知时 ``快照 ⊆ tier_chain``（链是全集/解锁顺序，快照不能出现链上没有的档）。

    ★不校验「本账号现在能打哪几档」★：账号状态，离线永远比不了
    （``scene/drift.py`` 已把这条明确列为不校验）。
    """
    scene_on_path()
    import scene.config as cfg  # noqa: PLC0415
    import scene.lord_battle as lb  # noqa: PLC0415
    import scene.lords as sl  # noqa: PLC0415

    snaps = dict(lb.ACCOUNT_SNAPSHOTS) if snapshots is None else dict(snapshots)
    by_name = {entry.row_name: entry for entry in sl.LORDS} if entries is None else dict(entries)
    diffs = tuple(cfg.DIFFICULTIES) if difficulties is None else tuple(difficulties)

    msgs: list[str] = []
    for row_name, tiers in sorted(snaps.items()):
        got = frozenset(tiers)
        entry = by_name.get(row_name)
        where = f"{label}[{row_name!r}]"
        if entry is None:
            msgs.append(
                f"{where}：成员不在 scene/lords.py 的花名册里 —— 快照只能记录花名册成员"
                f"（scene/lords.py 是难度事实的唯一真源）"
            )
            continue
        unknown = sorted(d for d in got if d not in diffs)
        if unknown:
            msgs.append(
                f"{where}：含词表里没有的难度 {unknown}（合法取值 {list(diffs)}）"
            )
        if entry.max_tiers is not None and len(got) > entry.max_tiers:
            msgs.append(
                f"{where}：快照有 {len(got)} 档，但 scene/lords.py 的 M={entry.max_tiers} "
                f"—— 快照是「那一刻看得见的档」，**不可能多于 M**；两者至少一个错了"
                f"（调研 §2.4：旧表就是把「可见档数」当成了 M）"
            )
        if entry.tier_chain:
            extra = sorted(d for d in got if d not in entry.tier_chain)
            if extra:
                msgs.append(
                    f"{where}：快照含解锁链上没有的档 {extra}（链 {list(entry.tier_chain)}）"
                    f" —— 链是全集/解锁顺序，快照不能出现链外的档"
                )
    return msgs


def _failures() -> list[str]:
    """#32 的全部离线断言；返回失败信息列表（空 = 绿）。"""
    scene_on_path()
    import scene.config as cfg  # noqa: PLC0415
    import scene.lord_battle as lb  # noqa: PLC0415
    import scene.options as so  # noqa: PLC0415

    msgs: list[str] = []

    lords = {m.行名 for m in lb.LORD_BATTLE.members if m.子族 == "领主战"}
    joss = {m.行名 for m in lb.LORD_BATTLE.members if m.子族 == "降临讨伐"}

    # (1) 成员集合 == 真机行扫。
    if lords != DEVICE_LORDS:
        msgs.append(
            f"成员表守卫：领主战成员集与真机行扫不一致 —— "
            f"配置多={sorted(lords - DEVICE_LORDS)} 配置缺={sorted(DEVICE_LORDS - lords)}"
            f"（真机 17 行，见 sweep_result.json / sweep_lord_*.ocr.txt）"
        )
    if joss != DEVICE_JOSS:
        msgs.append(
            f"成员表守卫：降临讨伐成员集与真机行扫不一致 —— "
            f"配置多={sorted(joss - DEVICE_JOSS)} 配置缺={sorted(DEVICE_JOSS - joss)}"
            f"（真机 29 行，见 sweep_result.json / sweep_joss_*.ocr.txt）"
        )

    # (2) 不存在的成员不得在配置里。
    all_names = {m.行名 for m in lb.LORD_BATTLE.members}
    for name in NONEXISTENT_MEMBERS:
        if name in all_names:
            msgs.append(f"成员表守卫：真机不存在的成员 {name!r} 仍被声明（应移除）")

    # (3) #21 回归：#32 前「两行」曾被并成一行、删掉了一个有效成员。
    for name in EKIEL_BOTH:
        if name not in all_names:
            msgs.append(
                f"成员表守卫：真机行扫里存在的成员 {name!r} 未声明"
                f"（#21 回归未修：真机第 1 行=艾基尔·嫉妒讨伐、第 10 行=诅咒弧魔艾基尔讨伐）"
            )

    # (4) 难度词表补上 地狱级。
    if "地狱级" not in cfg.DIFFICULTIES:
        msgs.append("难度守卫：scene.config.DIFFICULTIES 缺真机档位「地狱级」")

    # (5a) 投影一致：配置里的**账号快照** == 本文件内嵌的快照（夹具是配置的子集）。
    #      ★语义已降级（#111）★：这是「两份快照对账」，**不再**是「配置 == 真机事实」。
    #      配置可以多出本文件没采到的观察（例如 #39 单独复核的 诅咒弧魔艾基尔讨伐），故只查子集方向。
    for m in lb.LORD_BATTLE.members:
        want = ACCOUNT_SNAPSHOTS.get(m.行名)
        if want is None:
            continue
        got = frozenset(m.支持难度集)
        if got != want:
            msgs.append(
                f"快照守卫：成员 {m.行名!r} 的账号快照 {sorted(got)} != 本文件内嵌的快照 "
                f"{sorted(want)}（{ACCOUNT_SNAPSHOT_CAPTURED_AT} 的观察）—— "
                f"两份快照必须一致：要改就两边一起改，或走 scene/lords.py 的真源"
            )

    # (5b) ★#111 新语义★ 快照与 scene/lords.py（唯一事实源）**不冲突**。
    msgs.extend(_snapshot_conflict_failures())
    try:
        import scene.lords as sl  # noqa: PLC0415

        msgs.extend(
            _snapshot_conflict_failures(
                snapshots=ACCOUNT_SNAPSHOTS,
                entries={e.row_name: e for e in sl.LORDS},
                difficulties=cfg.DIFFICULTIES,
                label="本文件内嵌的快照",
            )
        )
    except Exception as exc:  # noqa: BLE001 - 读不到真源本身就是红
        msgs.append(f"快照守卫：读不到 scene/lords.py 以核对快照（{exc!r}）")

    # (6) 真机事实：降临讨伐无一成员含「初级」（快照与配置两侧都没见过）。
    for m in lb.LORD_BATTLE.members:
        if m.子族 == "降临讨伐" and "初级" in m.支持难度集:
            msgs.append(
                f"快照守卫：降临讨伐成员 {m.行名!r} 声明了「初级」，"
                f"但真机降临讨伐无一成员含初级（快照与配置都不该出现）"
            )

    # (7) 派生 GUI 选项名 == 成员行名（N -> N，不丢不重）。
    case_names = [c["name"] for c in so.derive_target_options(lb.LORD_BATTLE)]
    if case_names != [m.行名 for m in lb.LORD_BATTLE.members]:
        msgs.append(
            f"选项守卫：派生的 GUI 选项名与成员行名不一致（派生 {len(case_names)} 项 / "
            f"成员 {len(lb.LORD_BATTLE.members)} 个）"
        )

    # (8) 来源（帧 / 产物名）必须记录在数据修正处。
    try:
        src = Path(lb.__file__).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - 读不到源码本身就是红
        src = ""
        msgs.append(f"来源守卫：读不到 scene/lord_battle.py 源码以核对来源（{exc}）")
    missing = [s for s in EVIDENCE_STRINGS if s not in src]
    if missing:
        msgs.append(f"来源守卫：数据修正处没有记录来源（缺 {missing}）——来源必须可追溯")

    return msgs


def probe_lord_roster_and_difficulties() -> bool:
    """#32（#111 降级）：成员表 / 难度词表 与真机行扫一致；逐成员难度 = **账号快照**，
    且快照与 ``scene/lords.py``（唯一事实源）不冲突。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_32.py`）
# ---------------------------------------------------------------------------
def _probe_in(root: Path):
    """子进程里、以 ``root`` 作为 ``scene`` 包来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import discover_hooks\n"
        f"probe = next(p for hid, _t, _w, p in discover_hooks() if hid == {HOOK_ID!r})\n"
        "print('PROBE_RESULT', repr(probe()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def _break_drop_yohu(scene_dir: Path) -> None:
    """破坏：删掉成员「妖狐讨伐」（成员集与真机行扫再次不符）。"""
    path = scene_dir / "lord_battle.py"
    text = path.read_text(encoding="utf-8")
    old = '    _observed("领主战", "妖狐讨伐"),\n'
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, "", 1), encoding="utf-8")


def _break_snapshot_over_max() -> list[str]:
    """破坏：给「无猾机兵」的快照塞到 6 档（超过 scene/lords.py 的 M=5）→ (5b) 必须红。

    ★这不是可选的刁难★：调研 §2.4 证明旧表的错法就是「把某账号可见档数当成全集」，
    所以「快照多于 M」必须是红，而不是被静默接受。
    """
    scene_on_path()
    import scene.config as cfg  # noqa: PLC0415
    import scene.lords as sl  # noqa: PLC0415

    snapped = {"无猾机兵": frozenset({"超级", "地狱级", "高级+", "高级", "中级", "初级"})}
    return _snapshot_conflict_failures(
        snapshots=snapped,
        entries={entry.row_name: entry for entry in sl.LORDS},
        difficulties=cfg.DIFFICULTIES,
    )


def prove_red() -> bool:
    """真实绿；① 删掉成员「妖狐讨伐」、② 快照超出 M -> 守卫必须各自变红。"""
    print("hooks_32 prove-red：删掉成员「妖狐讨伐」/ 快照超出 M，要求"
          " lord-roster-and-difficulties-on-device 变红")
    green = probe_lord_roster_and_difficulties() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：成员表一致 + 快照与 scene/lords.py 不冲突（绿）")
    if not green:
        for msg in _failures():
            print(f"      - {msg}")
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook32_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
        _break_drop_yohu(tmp / "scene")
        red = _probe_in(tmp) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 删掉「妖狐讨伐」-> 探针变红")

    # ② 快照超出 M（旧表的错法：把「可见档数」当全集）。
    msgs = _break_snapshot_over_max()
    red2 = len(msgs) > 0
    print(f"  [{'PASS' if red2 else 'FAIL'}] 快照塞到 6 档（M=5）-> 快照冲突变红"
          + (f"  {msgs[0]}" if msgs else ""))

    ok = green and red and red2
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#32 / #111",
        "领主战类成员表 / 难度词表与真机行扫一致（修 #21 回归 + 补 地狱级）；"
        "逐成员难度★降级为账号快照★（#111）：与本文件内嵌快照逐成员对账，且与 scene/lords.py"
        "（唯一事实源）不冲突 —— 仅当 成员在花名册 / 档 ∈ 词表 / len(快照) ≤ M / 快照 ⊆ 链",
        probe_lord_roster_and_difficulties,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
