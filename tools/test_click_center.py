# -*- coding: utf-8 -*-
"""离线守卫（本票）：进编队页的卡片 / 【战斗】点击必须落在【识别框中心】。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_click_center.py

背景（operator 原话）
---------------------
    「还有就是 **点击卡片进入编队页** 时，**尽量点击中心**，**点击左下容易点到推荐编成**」

真机 recon（docs/recon/abyss-calibration.md §1.1 / §3.2 坑 4）独立复现了这个陷阱：
深渊EX 关卡选择页底部同时有【关卡条】(第N战) 与左下角的【推荐编成】；点【推荐编成】
弹的是 Party **选队伍层**（`10_abyss_team.png`），**不是编队页**。所以「进编队页」的
每一次点击都必须落在**识别到的控件框中心**，绝不能用「识别框 + 死偏移 / 死坐标」。

本守卫钉死三类事实
------------------
1. **pipeline**：六类模式下每一处「进卡 / 【战斗】/ 【挑战】」点击节点，动作要么是
   ``Click/LongPress target: true``（= 识别框中心），要么是点识别框中心的自定义动作
   （``special_batch_fight`` / ``abyss_act`` / ``wuchong_act`` / ``phantom_act``）。
   **不允许** ``target: [x, y]`` 固定点、**不允许**非零 ``target_offset``。
   唯一的例外是外传关卡列表的**行锚点**（``SideEnter`` / ``SideStoryNode``）：
   「该行卡片」本身没有 OCR 框，只有行内小标签 / NEW 徽标有框 → 必须由锚点偏移到
   行中心；这两个偏移**必要且有界**（见 :data:`BOUNDED_ANCHOR_NODES`），单独断言。
2. **agent**：所有点击落地辅助（``_center`` / ``_batch_box_center`` / ``_click_box`` /
   ``_batch_click`` / 各 impl 的 ``_pick`` / ``battle_loop_core.pick``+``click_box``）
   都必须把点击点算成**框中心**（功能断言，不是注释断言）。
3. **真机帧**：用随仓的详情页真机 OCR（``tools/contract_hooks/hooks_35`` 内嵌的
   ``lord_detail_multidiff.png`` 逐条 OCR），断言每个难度的【战斗】框中心**不在**
   任何【推荐编成】框内（并证明「左下偏移」会落进【推荐编成】→ 证明这套判据非空转）。

prove-red（内置，随套件一起跑）
------------------------------
把 ``SpecialFightTargetRow`` 的动作改成「框左下偏移」（`target_offset:[-16,+24]`）→
pipeline 守则必须变红；再加一个「固定点战斗」也必须变红；真机帧检查器在注入
「左下偏移」后也必须变红。三者任一抓不到 = 本测试红（红的含义可用）。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import side_impl as si  # noqa: E402
import abyss_impl as ab  # noqa: E402
import wuchong_impl as wc  # noqa: E402
import battle_loop_core as core  # noqa: E402
from batch_plan import DIFF_REGEX  # noqa: E402
import hooks_35  # noqa: E402  （真机详情页 OCR 夹具，随仓）

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 守卫集合：六类模式下「进卡 / 【战斗】/ 【挑战】」的点击节点（本票审计表）
#
#   CENTER_BOX_NODES   —— 动作是 Click / LongPress，目标 = 识别框中心（target: true）。
#   CENTER_CUSTOM_NODES—— 动作是自定义动作，实现内部点识别框中心。
#   BOUNDED_ANCHOR_NODES —— 外传关卡列表的「行锚点」：卡片无 OCR 框 → 锚点 + 有界偏移。
# ---------------------------------------------------------------------------
CENTER_BOX_NODES: dict[str, list[str]] = {
    # 领主战 / 降临讨伐（详情页【战斗】、主城入口）
    "special_dungeon.json": [
        "SpecialFightTargetRow",   # 详情页难度行的【战斗】（custom 识别返回战斗框 → 点框中心）
        "SpecialFightNewRow",      # 详情页 NEW 行的【战斗】（box_index=2 = SpecialBattleBtn）
        "SpecialFullFirstFight",   # 打满模式首发档【战斗】（覆盖后 box_index=2）
        "SpecialOpenLord",         # 主城【领主战】入口
    ],
    # 迷宫（farm）
    "farm.json": [
        "FarmFight",               # 迷宫行【战斗】（special_target_fight → 点框中心）
        "FarmMazeEntry",           # 主城横幅【摇曳的迷宫】入口（box_index=0 = 横幅域名框）
        "FarmItemConfirm",         # 道具确认框【是】（#60：box_index=1 = 【是】框 → 点框中心）
    ],
    # 五重（领主行）
    "wuchong.json": [
        "WuchongNavRow",           # 降临讨伐列表【五王连战】行（box_index=1 = 行模板框）
    ],
    # 外传（详情页【战斗】/ 账本选行）
    "side_story.json": [
        "SideFight",               # 关卡详情页【战斗】（box_index=1 = SideFightBtn）
        "SideNextStory",           # 账本选行：纯剧情行标题框（next_stage → 点框中心）
        "SideNextBattle",          # 账本选行：战斗行标题框
        "SideNextSpecial",         # 账本选行：特殊行标题框（长按，仍点框中心）
    ],
}

CENTER_CUSTOM_NODES: dict[str, dict[str, str]] = {
    "special_dungeon.json": {
        "SpecialRoomFight": "special_batch_fight",   # 房间页【战斗】
        "SpecialChallenge": "special_batch_fight",   # 编队页【挑战】
        "SpecialEnterBoss": "special_batch_fight",   # 列表【选行】（row_click → 复核后用新框中心）
    },
    "abyss.json": {
        "AbyssMainFight": "abyss_act",               # 关卡选择页【关卡条】→ 编队页
        "AbyssSoloChallenge": "abyss_act",           # 单人编队页【挑战】
        "AbyssHubEnter": "abyss_act",                # hub【战斗】
    },
    "wuchong.json": {
        "WuchongDetailFight": "wuchong_act",         # 详情页【战斗】
        "WuchongModeSolo": "wuchong_act",            # 模式页【单人游戏】
    },
    "phantom.json": {
        "PhantomMainFight": "phantom_act",           # 关卡选择页卡片【战斗】
    },
}

# 行锚点（必要且有界）：(文件, 节点) -> (最大 |dx|, 最大 |dy|)
BOUNDED_ANCHOR_NODES: dict[str, dict[str, tuple[int, int]]] = {
    "side_story.json": {
        "SideEnter": (300, 120),       # NEW 徽标框 → 关卡行中心
        "SideStoryNode": (300, 120),   # 特殊战斗 标签框 → 行标题中心
    },
}

# 允许「点识别框中心」的自定义动作名（实现已由第 2 节功能断言）。
CENTER_ACTIONS = {"special_batch_fight", "abyss_act", "wuchong_act", "phantom_act"}


def load_pipelines() -> dict:
    """读 pipeline JSONC（只剥整行 ``//`` 注释，保留行数不算漂移）。"""
    out = {}
    for p in sorted(PIPELINE_DIR.glob("*.json")):
        text = p.read_text(encoding="utf-8")
        stripped = "\n".join(
            line.split("//", 1)[0] if line.lstrip().startswith("//") else line
            for line in text.splitlines()
        )
        out[p.name] = json.loads(stripped)
    return out


def _act_param(node) -> dict:
    return ((node or {}).get("action") or {}).get("param") or {}


def pipeline_center_failures(files: dict) -> list[str]:
    """纯函数：六类模式的进卡点击是否全部落到【识别框中心】。返回失败信息（空 = 绿）。"""
    msgs: list[str] = []

    # (A) Click / LongPress：必须 target: true（识别框中心），不得有固定点 / 偏移。
    for fn, names in CENTER_BOX_NODES.items():
        data = files.get(fn) or {}
        for name in names:
            node = data.get(name)
            if node is None:
                msgs.append(f"{fn}::{name} 缺失（守卫与实现脱节）")
                continue
            act = node.get("action") or {}
            if act.get("type") not in ("Click", "LongPress"):
                msgs.append(f"{fn}::{name} 动作类型 {act.get('type')!r} 不是 Click/LongPress")
            param = _act_param(node)
            tgt = param.get("target")
            if tgt is not None and tgt is not True:
                msgs.append(
                    f"{fn}::{name} 用固定点 target={tgt!r}（要求 target: true = 识别框中心）"
                )
            off = param.get("target_offset")
            if isinstance(off, (list, tuple)) and any(float(v or 0) != 0.0 for v in off):
                msgs.append(
                    f"{fn}::{name} 用死偏移 target_offset={list(off)!r}"
                    f"（要求落点 = 识别框中心，零偏移）"
                )

    # (B) 自定义动作：点名必须是「点识别框中心」的已证动作，且动作参数里无固定点。
    for fn, mapping in CENTER_CUSTOM_NODES.items():
        data = files.get(fn) or {}
        for name, expect_action in mapping.items():
            node = data.get(name)
            if node is None:
                msgs.append(f"{fn}::{name} 缺失（守卫与实现脱节）")
                continue
            act = node.get("action") or {}
            if act.get("type") != "Custom":
                msgs.append(f"{fn}::{name} 动作类型 {act.get('type')!r} 不是 Custom")
                continue
            param = act.get("param") or {}
            action_name = param.get("custom_action")
            if action_name != expect_action:
                msgs.append(
                    f"{fn}::{name} custom_action={action_name!r} != 期望 {expect_action!r}"
                )
            if action_name not in CENTER_ACTIONS:
                msgs.append(f"{fn}::{name} custom_action={action_name!r} 不在「点框中心」白名单")
            inner = param.get("custom_action_param") or {}
            if "target" in inner:
                msgs.append(
                    f"{fn}::{name} 自定义动作里带了固定点 target={inner['target']!r}"
                    f"（要求点 argv.box 的中心）"
                )

    # (C) 有界的行锚点偏移（外传关卡列表：卡片无 OCR 框 → 锚点 + 偏移到行中心）。
    for fn, mapping in BOUNDED_ANCHOR_NODES.items():
        data = files.get(fn) or {}
        for name, (max_dx, max_dy) in mapping.items():
            node = data.get(name)
            if node is None:
                msgs.append(f"{fn}::{name} 缺失（守卫与实现脱节）")
                continue
            act = node.get("action") or {}
            if act.get("type") not in ("Click", "LongPress"):
                msgs.append(f"{fn}::{name} 动作类型 {act.get('type')!r} 不是 Click/LongPress")
            param = _act_param(node)
            if param.get("target") is not True:
                msgs.append(
                    f"{fn}::{name} 行锚点必须以 target: true 为基准再偏移"
                    f"（得到 target={param.get('target')!r}）"
                )
            off = param.get("target_offset")
            if not (isinstance(off, (list, tuple)) and len(off) == 4):
                msgs.append(f"{fn}::{name} 行锚点缺少 4 元素 target_offset={off!r}")
                continue
            dx, dy = float(off[0] or 0), float(off[1] or 0)
            if abs(dx) > max_dx or abs(dy) > max_dy:
                msgs.append(
                    f"{fn}::{name} 行锚点偏移 ({dx:.0f},{dy:.0f}) 超界 "
                    f"(|dx|≤{max_dx}, |dy|≤{max_dy}) —— 抖几像素就会离开行中心"
                )
            if float(off[2] or 0) != 0.0 or float(off[3] or 0) != 0.0:
                msgs.append(f"{fn}::{name} 行锚点偏移第 3/4 位必须为 0：{list(off)!r}")
    return msgs


# ---------------------------------------------------------------------------
# 真机帧：详情页【战斗】框中心绝不在【推荐编成】框内（帧数据来自 hooks_35，随仓）。
# ---------------------------------------------------------------------------
RECOMMEND_RE = r"^推荐编成$"


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _inside(pt, box) -> bool:
    x, y, w, h = box
    return x <= pt[0] <= x + w and y <= pt[1] <= y + h


def frame_center_failures(items, recommend_shift=(0, 0)) -> list[str]:
    """纯函数：逐难度断言「点的战斗框中心」不在【推荐编成】框内。

    ``recommend_shift`` 只给 prove-red 用：把点击点人为挪到「框左下」——
    若这样就能落进【推荐编成】，说明本判据真的能抓住「点左下 = 点到推荐编成」。
    """
    msgs: list[str] = []
    recommends = [b for t, b in items if re.search(RECOMMEND_RE, t or "")]
    for declared, rx in DIFF_REGEX.items():
        box, detail = si.pick_target_battle_box(items, difficulty=rx)
        if box is None:
            # 该帧只含部分难度（如单难度帧），跳过而不是误报。
            continue
        cx, cy = _center(box)
        pt = (cx + recommend_shift[0], cy + recommend_shift[1])
        for rb in recommends:
            if _inside(pt, rb):
                msgs.append(
                    f"难度「{declared}」：点击点 {tuple(round(v) for v in pt)} 落在"
                    f"【推荐编成】框 {list(rb)} 内（会弹 Party 选择层，不改队伍就是错）"
                )
    return msgs


# ---------------------------------------------------------------------------
# agent 侧：点击落地辅助必须算「框中心」。
# ---------------------------------------------------------------------------
class _FakeCtx:
    def __init__(self):
        self.calls = []

    def run_action(self, name, box=None):
        self.calls.append((name, box))
        return None


class _Box:
    """模拟 MAA box（x/y/w/h 属性 + 可索引）。"""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        self._t = (x, y, w, h)

    def __getitem__(self, i):
        return self._t[i]


def agent_center_failures() -> list[str]:
    msgs: list[str] = []

    # side_impl._center / _batch_box_center
    if si._center([10, 20, 30, 40]) != (25.0, 40.0):
        msgs.append(f"side_impl._center 不是框中心：{si._center([10, 20, 30, 40])!r}")
    if si._batch_box_center(_Box(10, 20, 30, 40)) != (25, 40):
        msgs.append("side_impl._batch_box_center 不是框中心")

    # side_impl._click_box：应点给定框中心（PubClick + 2x2 框）
    ctx = _FakeCtx()
    ok = si._click_box(ctx, [10, 20, 30, 40])
    want = ("PubClick", (25 - 1, 40 - 1, 2, 2))
    if not ok or (ctx.calls[-1] if ctx.calls else None) != want:
        msgs.append(f"side_impl._click_box 未点框中心：{ctx.calls!r}")

    # side_impl._batch_click：按 (x,y) 点
    ctx = _FakeCtx()
    si._batch_click(ctx, 25, 40, "开打")
    if (ctx.calls[-1] if ctx.calls else None) != want:
        msgs.append(f"side_impl._batch_click 未点 (x,y)：{ctx.calls!r}")

    # abyss_impl._pick：返回框中心
    got = ab._pick([("第1战", [10, 20, 100, 40])], [r"第\s*\d+\s*战"])
    if not got or (round(got[1]), round(got[2])) != (60, 40):
        msgs.append(f"abyss_impl._pick 不是框中心：{got!r}")
    ctx = _FakeCtx()
    ab._click_box(ctx, 60, 40)
    if (ctx.calls[-1] if ctx.calls else None) != ("AbyssClick", (59, 39, 2, 2)):
        msgs.append(f"abyss_impl._click_box 未点 (x,y)：{ctx.calls!r}")

    # wuchong_impl._pick：返回框中心
    got = wc._pick([("战斗", [10, 20, 30, 40])], [r"^战斗$"])
    if not got or (round(got[1]), round(got[2])) != (25, 40):
        msgs.append(f"wuchong_impl._pick 不是框中心：{got!r}")
    ctx = _FakeCtx()
    wc._click_box(ctx, 25, 40)
    if (ctx.calls[-1] if ctx.calls else None) != ("WuchongClick", (24, 39, 2, 2)):
        msgs.append(f"wuchong_impl._click_box 未点 (x,y)：{ctx.calls!r}")

    # battle_loop_core.pick / click_box（phantom 走这套）
    got = core.pick([("战斗", [10, 20, 30, 40])], [r"^战斗$"])
    if not got or (round(got[1]), round(got[2])) != (25, 40):
        msgs.append(f"battle_loop_core.pick 不是框中心：{got!r}")

    class _Scene:
        click_action = "PhantomClick"
        log_tag = "phantom"

    ctx = _FakeCtx()
    core.click_box(_Scene(), ctx, 25, 40)
    if (ctx.calls[-1] if ctx.calls else None) != ("PhantomClick", (24, 39, 2, 2)):
        msgs.append(f"battle_loop_core.click_box 未点 (x,y)：{ctx.calls!r}")

    return msgs


def main() -> int:
    files = load_pipelines()

    print("=" * 74)
    print("守卫：进编队页的卡片 / 【战斗】点击必须落在【识别框中心】")
    print("=" * 74)

    # ---- 1. pipeline ----
    print("\n== 1. pipeline：六类模式的进卡点击 = 识别框中心 ==")
    msgs = pipeline_center_failures(files)
    check("每处进卡点击都落到识别框中心（无死点 / 无死偏移）", not msgs, "; ".join(msgs))

    print("\n   —— 审计表（打印，供人核对）——")
    for fn, names in CENTER_BOX_NODES.items():
        for name in names:
            p = _act_param((files.get(fn) or {}).get(name) or {})
            print(f"     {fn:24s} {name:22s} Click  target={p.get('target', '(默认=框中心)')!r}"
                  f" offset={p.get('target_offset', None)!r}")
    for fn, mapping in CENTER_CUSTOM_NODES.items():
        for name, action in mapping.items():
            print(f"     {fn:24s} {name:22s} custom {action}  (点 argv.box 中心)")
    for fn, mapping in BOUNDED_ANCHOR_NODES.items():
        for name in mapping:
            p = _act_param((files.get(fn) or {}).get(name) or {})
            print(f"     {fn:24s} {name:22s} Click  target=true  offset={p.get('target_offset')!r}"
                  f"  (行锚点，有界)")

    # ---- 2. agent ----
    print("\n== 2. agent：点击落地辅助都算框中心 ==")
    amsgs = agent_center_failures()
    check("_center / _batch_box_center / _click_box / _pick 均取框中心",
          not amsgs, "; ".join(amsgs))

    # ---- 3. 真机帧 ----
    print("\n== 3. 真机详情页帧：【战斗】框中心不在【推荐编成】框内 ==")
    fmsgs = frame_center_failures(hooks_35.MULTI_ITEMS)
    check("多难度帧：各难度【战斗】框中心避开拓【推荐编成】", not fmsgs, "; ".join(fmsgs))
    fmsgs2 = frame_center_failures(hooks_35.SINGLE_ITEMS)
    check("单难度帧：唯一【战斗】框中心避开【推荐编成】", not fmsgs2, "; ".join(fmsgs2))

    # ---- 4. prove-red ----
    print("\n== 4. prove-red：注入「点左下 / 死点」必须变红 ==")
    broken = copy.deepcopy(files)
    # (a) 详情页【战斗】改成「框左下偏移」（左 16px、下 24px → 落进推荐编成）。
    broken["special_dungeon.json"]["SpecialFightTargetRow"]["action"]["param"]["target_offset"] = [
        -16, 24, 0, 0,
    ]
    red_a = bool(pipeline_center_failures(broken))
    check("注入 SpecialFightTargetRow 左下偏移 → pipeline 守则变红", red_a)

    # (b) 另一节点改用固定死点。
    broken2 = copy.deepcopy(files)
    broken2["farm.json"]["FarmFight"]["action"]["param"] = {"target": [88, 908]}
    red_b = bool(pipeline_center_failures(broken2))
    check("注入 FarmFight 固定死点 → pipeline 守则变红", red_b)

    # (c) 真机帧：把点击点挪到「框左下」→ 必须落进【推荐编成】→ 检查器变红。
    red_c = bool(frame_center_failures(hooks_35.MULTI_ITEMS, recommend_shift=(-16, 24)))
    check("真机帧：点【战斗】框左下 → 落进【推荐编成】被抓住", red_c)

    # (d) 行锚点偏移超界 → 变红。
    broken3 = copy.deepcopy(files)
    broken3["side_story.json"]["SideEnter"]["action"]["param"]["target_offset"] = [999, 999, 0, 0]
    red_d = bool(pipeline_center_failures(broken3))
    check("注入 SideEnter 超界锚点偏移 → 守则变红", red_d)

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅（进卡点击恒在识别框中心；左下/死点/超界偏移都会被抓住）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
