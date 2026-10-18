# -*- coding: utf-8 -*-
"""#105：A 类（战前编队页）就地切 SET —— 四道契约 + #124 收尾的 V5 接线契约。

## 真机标定（720x1280，帧 `tools/frames/33_wuchong_team.png`）
- A 类 SET 条：y≈**466**，圆点中心 164,213,262,311,360,409,457,506,555,604,653,698（**间距 49**，12 档）。
- B 类编辑器：y=**30**，间距 **55**（#91 标定）。
- ⇒ **两套坐标绝不混用**（拿 B 类坐标点 A 类页 = 点到标题栏）。
- 页面判据互斥：`自动续战`（A 独有）vs `^切换$`（B 独有）；`编成/SET编辑` 两类共有，不是判据。

## 契约
- **V1 坐标分离**：A/B 的 row_y 与 step 都必须不同，且 A 的档数与实测一致（12）。
- **V2 页判据互斥**：A 类帧 → True；B 类帧（含 `切换`）→ False。
- **V3 步进正确**：`battle_set_tap_plan` 按实测序列算（1→4 = 260，4→1 = 113），到目标 None，越界 None。
- **V4 接线**：`team_switch_battle` 已注册（my_action + live_harness），pipeline 有 `TeamSwitchBattle` 节点。
- **V5 接线 + 拒动**（#124 收尾）：A 类页 + 目标队 ⇒ 走 ``switch_party``（横向滑动 + **三重校验**），
  **成功判据只有三重校验全过**；**读不到编队 / 不在 A 类页 ⇒ 拒动**（零点击零滑动，只打印原因）。
  旧 V5 的「队不符 → 拒动」不再成立（本票把它接线了），保留下来的是「读不到就不动」这半。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"

#: 真机帧那一帧（720）的 OCR 项：A 类战前编队页。
A_FRAME = [
    ("SET 1", [90, 458, 60, 20]),
    ("1  Party A", [35, 520, 130, 24]),
    ("自动续战", [20, 1060, 80, 24]),
    ("战力 8,876", [500, 516, 130, 24]),
]
#: B 类编辑器帧（含「切换」，A 类没有）。
B_FRAME = [
    ("SET 1", [30, 14, 48, 19]),
    ("5 Party E", [78, 74, 96, 24]),
    ("切换", [633, 685, 40, 24]),
    ("战力 13,116", [560, 74, 140, 24]),
]


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _load():
    _paths()
    import team_impl as ti  # noqa: PLC0415
    from scene import team as sc  # noqa: PLC0415

    return sc, ti


def _submodule(name: str):
    """取 ``scene.<name>`` **子模块**（``scene/__init__`` 会把同名函数导出到包上，属性会被遮蔽）。"""
    _paths()
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"scene.{name}")


def _coords_failures() -> list:
    sc, ti = _load()
    msgs = []
    for name in (
        "TEAM_BATTLE_SET_ROW_Y",
        "TEAM_BATTLE_SET_STEP_PX",
        "TEAM_BATTLE_SET_MAX",
        "TEAM_BATTLE_SET_LABEL_X",
        "TEAM_PAGE_ANCHOR_A",
        "TEAM_PAGE_ANCHOR_B",
    ):
        a, b = getattr(sc, name, "<missing>"), getattr(ti, name, "<missing>")
        if a != b:
            msgs.append(f"{name} 漂移：scene={a!r} agent={b!r}")
    if sc.TEAM_BATTLE_SET_ROW_Y == sc.TEAM_SET_ROW_Y:
        msgs.append("A 类与 B 类用了同一个 row_y（会点错页面）")
    if sc.TEAM_BATTLE_SET_STEP_PX == sc.TEAM_SET_STEP_PX:
        msgs.append("A 类与 B 类用了同一个圆点间距（会点偏）")
    if sc.TEAM_BATTLE_SET_MAX != 12:
        msgs.append(f"A 类档数 {sc.TEAM_BATTLE_SET_MAX} ≠ 实测 12（真机帧 33_wuchong_team.png）")
    return msgs


def probe_team_battle_coords() -> bool:
    return _coords_failures() == []


def _predicate_failures() -> list:
    sc, ti = _load()
    msgs = []
    if not ti.is_battle_team_page(list(A_FRAME)):
        msgs.append("A 类帧被判成「不是战前编队页」（有「自动续战」应命中）")
    if ti.is_battle_team_page(list(B_FRAME)):
        msgs.append("B 类帧（含「切换」）被判成 A 类页 → 会按 A 类坐标点 B 类页")
    # 没有「自动续战」的帧不许判成 A 类
    if ti.is_battle_team_page([("SET 1", [30, 14, 48, 19])]):
        msgs.append("没有「自动续战」的帧被判成 A 类页")
    # scene 侧同名工具与 agent 侧一致
    if sc.is_battle_team_page(list(A_FRAME)) != ti.is_battle_team_page(list(A_FRAME)):
        msgs.append("scene 与 agent 的 A 类判据结果不一致")
    return msgs


def probe_team_battle_page_predicate() -> bool:
    return _predicate_failures() == []


def _step_failures() -> list:
    _sc, ti = _load()
    msgs = []
    got = ti.battle_set_tap_plan(1, 4)
    if got != (260, 1):
        msgs.append(f"1→4 步进算错：{got!r}（应 (260, 1) = 84 + 49×4 − 20）")
    got = ti.battle_set_tap_plan(4, 1)
    if got != (113, -1):
        msgs.append(f"4→1 步进算错：{got!r}（应 (113, -1) = 84 + 49×1 − 20）")
    if ti.battle_set_tap_plan(6, 6) is not None:
        msgs.append("已到目标仍给出点击（会白点）")
    if ti.battle_set_tap_plan(1, 13) is not None:
        msgs.append("越界目标仍给出点击（应 None）")
    return msgs


def probe_team_battle_step_plan() -> bool:
    return _step_failures() == []


def _wiring_failures() -> list:
    _paths()
    import jsonc  # noqa: PLC0415

    msgs = []
    nodes = jsonc.load(open(REPO_ROOT / "assets" / "resource" / "pipeline" / "team.json", encoding="utf-8"))
    node = nodes.get("TeamSwitchBattle") or {}
    act = ((node.get("action") or {}).get("param") or {}).get("custom_action")
    if act != "team_switch_battle":
        msgs.append(f"team.json::TeamSwitchBattle 的 custom_action 应为 team_switch_battle，实际 {act!r}")
    recopath = REPO_ROOT / "agent" / "my_action.py"
    if 'custom_action("team_switch_battle")' not in recopath.read_text(encoding="utf-8"):
        msgs.append("my_action.py 缺 team_switch_battle 注册")
    # 从模块读（而不是读文件文本）——这样「摘掉注册」才可被破坏实验验证，且检测力等价。
    import live_harness as _lh  # noqa: PLC0415

    if "team_switch_battle" not in getattr(_lh, "CUSTOM_ACTIONS", {}):
        msgs.append("live_harness 静态注册表缺 team_switch_battle")
    return msgs


def probe_team_battle_wiring() -> bool:
    return _wiring_failures() == []


# ===========================================================================
# ★#124 收尾★ V5：动作接进 switch_party（读不到编队就不动 + 切完必须三重校验）
# ===========================================================================
_H124 = None


def _h124():
    """复用 ``hooks_124`` 的假设备 / 动作跑器（**不抄第二份尺**：同一套假 IO 计数）。

    与本文件 ``_h102()`` 同一手法：按文件路径加载，不写 ``sys.modules``、不依赖 cwd。
    """
    global _H124
    if _H124 is None:
        import importlib.util  # noqa: PLC0415

        path = Path(__file__).with_name("hooks_124.py")
        spec = importlib.util.spec_from_file_location("_hooks_124_for_105", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _H124 = module
    return _H124


def _party_v5_failures() -> list:
    """V5：``TeamSwitchBattleAction`` 的队切换接线 + 两条硬底线。

    ★旧 V5 的两半★：旧断言是「队不符 → 拒动」。接线后**队不符时要动（横向滑动）**，
    所以旧断言的上半句必须换掉；但「**读不到编队就不动**」这半照旧 —— 下面 (a)(b) 就是它。
    (c) 钉住另一半：成功只能由 ``switch_party`` 的三重校验给出，「滑到目标」不算成功。
    """
    h124 = _h124()
    msgs: list = []

    # (a) 读不到编队（A 类页但 Party 读不到）⇒ 拒动：零调用、零滑动、零点击、日志点名
    blind = h124.FakeBattlePage(party=3, party_readable=False)
    out, calls = h124.run_battle_action(blind, {"set": 1, "party": 5})
    if calls["switch_party"]:
        msgs.append(f"读不到编队却调了 switch_party：{calls['switch_party']}（旧 V5 的「读不到就不动」被破坏）")
    if blind.swipes or blind.clicks:
        msgs.append(f"读不到编队却动了：swipes={blind.swipes} clicks={blind.clicks}")
    if "拒动" not in out:
        msgs.append(f"读不到编队没有明确「拒动」：{h124._tail(out)!r}")

    # (b) 不在 A 类页 ⇒ 拒动：零调用、零滑动
    b_page = h124.FakeBattlePage(party=3, page="B")
    out, calls = h124.run_battle_action(b_page, {"set": 1, "party": 5})
    if calls["switch_party"]:
        msgs.append(f"非 A 类页也调了 switch_party：{calls['switch_party']}（应拒动）")
    if b_page.swipes or b_page.clicks:
        msgs.append(f"非 A 类页上动了：swipes={b_page.swipes} clicks={b_page.clicks}")

    # (c) 切完必须三重校验：战力没变（第三票不过）⇒ 绝不宣称成功
    frozen = h124.FakeBattlePage(party=3, frozen_power=True)
    out, _calls = h124.run_battle_action(frozen, {"set": 1, "party": 5})
    if "✓ 收尾" in out:
        msgs.append(f"三重校验不过（战力没变）却打印成功收尾：{h124._tail(out, 3)!r}")
    if "切队成功" in out:
        msgs.append(f"三重校验不过却打印「切队成功」（假成功）：{h124._tail(out, 3)!r}")

    # (d) 正例：三重校验齐 ⇒ 成功，并且队真的到了目标
    page = h124.FakeBattlePage(party=3)
    out, calls = h124.run_battle_action(page, {"set": 1, "party": 5})
    if calls["switch_party"] != [5]:
        msgs.append(f"正例没走 switch_party（目标 5，调用记录 {calls['switch_party']}）")
    if page.party != 5:
        msgs.append(f"正例跑完 Party = {page.party}，应为 5")
    if "✓ 收尾" not in out:
        msgs.append(f"正例没有成功收尾：{h124._tail(out)!r}")
    return msgs


def probe_team_battle_party_switch() -> bool:
    """V5：A 类页 + 目标队 ⇒ switch_party（三重校验）；读不到编队 / 非 A 类页 ⇒ 拒动。"""
    return _party_v5_failures() == []


# ===========================================================================
# ★#105b 模板通道★：五张模板 / 双通道 / 逐像素 / 存档 ⇄ 实测
# ===========================================================================
#: 存档与实测的容差（票面要求 0.02）。
SCORE_TOL = 0.02
#: 正例保守分下限。实测最差正例 = ``side_team_page.png`` 的 ``set_selected`` 灰 0.9520 /
#: 彩 0.9456 ⇒ 取 0.94 只用来抓「模板被换 / 帧被换 / 模板被裁歪」，不是卡性能。
POSITIVE_MIN = 0.94
#: 正例余量下限（正例最差 − 阈值）：低于它 = 擦线，跨帧一抖就漏。
POSITIVE_MARGIN_MIN = 0.05
#: 负例余量下限（阈值 − 负例最高）：低于它 = 靠阈值擦屁股，不是靠 roi。
NEG_MARGIN_MIN = 0.05
#: roi 面积上限（占 720x1280 的比例）：收窄才算「主防线」。
ROI_AREA_MAX = 0.15
#: 正例窗口定位容差（滑窗是整数位置，允许 ±2px）。
WINDOW_TOL = 2
#: ★兄弟图形★：``SET编辑`` 按钮（720 空间实测框，从 ``33_wuchong_team.png`` 量的）。
#: 它同样含 ``SET`` 三字母 —— ``set_selected`` 的 roi 必须**装不下**它。这就是「roi 是主防线」
#: 的具体物证（而不是「模板天生不假阳」）。
SET_EDIT_BOX = (595, 950, 78, 28)

_H102 = None


def _h102():
    """复用 ``hooks_102`` 的量测原语（ZNCC / roi 裁剪 / 候选抑制）——**不抄第二份尺**。

    「同一把尺」是硬要求：#102 的 0.8964 / 0.470 / 0.8708 与本票的数字必须可比。
    """
    global _H102
    if _H102 is None:
        import importlib.util  # noqa: PLC0415

        path = Path(__file__).with_name("hooks_102.py")
        spec = importlib.util.spec_from_file_location("_hooks_102_for_105", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _H102 = module
    return _H102


def _tt():
    """``scene.team_templates``（模板真源）。"""
    return _submodule("team_templates")


def _agent():
    """``agent.team_impl``（运行时实现；仓库态走 scene，安装态走快照）。"""
    _paths()
    import team_impl  # noqa: PLC0415

    return team_impl


def _deps_missing() -> str | None:
    """缺 numpy / Pillow 时返回原因（**红**，不静默跳过：假阳用例是本票唯一的取证手段）。"""
    try:
        import numpy  # noqa: F401,PLC0415
        import PIL  # noqa: F401,PLC0415
    except Exception as exc:  # noqa: BLE001
        return (
            f"缺 numpy / Pillow（{type(exc).__name__}: {exc}）—— 本守卫要用真机帧算 ZNCC，"
            f"没有它们就无法取证；本守卫选择**红**而不是静默跳过（模板假阳本来就是静默的）"
        )
    return None


def _frame(rel: str):
    """一帧 → 720x1280 PIL（与 ``hooks_102`` / ``gen_templates_105`` 同一口径）。"""
    return _h102().frame_720(rel)


def _template_png(spec):
    """读模板 PNG（RGB PIL）。"""
    from PIL import Image  # noqa: PLC0415

    return Image.open(REPO_ROOT / spec.template_rel).convert("RGB")


def _template_recrop(spec):
    """按 ``window`` 从**裁剪源帧**重裁（模板必须逐像素等于它）。"""
    x, y, w, h = spec.window
    return _frame(spec.source_frame).crop((x, y, x + w, y + h))


#: 量测缓存：多条探针拿**同一份**数字（每个模板 12 帧 × 2 次卷积，别算两遍）。
_MEASURE_CACHE: dict = {}
#: 运行时模板通道的缓存（每个模板的正例都要跟运行时对一次数，别为同一帧跑 5 遍）。
_RUNTIME_CACHE: dict = {}


def _runtime_hits(rel: str):
    """``agent.detect_team_templates`` 对某一帧的结果（缓存；失败也缓存 None）。"""
    if rel not in _RUNTIME_CACHE:
        _RUNTIME_CACHE[rel] = _agent().detect_team_templates(_frame(rel))
    return _RUNTIME_CACHE[rel]


def measure(spec) -> dict:
    """一条模板的全部取证量测：``{frame: {"gray": (s,x,y), "color": (s,x,y), "cands": n}}``。"""
    H = _h102()
    path = REPO_ROOT / spec.template_rel
    stamp = (path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else None
    key = (
        str(REPO_ROOT),
        spec.key,
        spec.template,
        stamp,
        tuple(spec.roi),
        spec.threshold,
        spec.source_frame,
        tuple(spec.window),
        tuple(h.frame for h in spec.positives),
        tuple(h.frame for h in spec.negatives),
    )
    cached = _MEASURE_CACHE.get(key)
    if cached is not None:
        return cached
    tpl = _template_png(spec)
    out: dict = {}
    for rel in [h.frame for h in spec.positives] + [h.frame for h in spec.negatives]:
        if rel in out:
            continue
        maps = H.roi_scores(_frame(rel), tpl, spec.roi)
        if maps is None:
            out[rel] = {"gray": None, "color": None, "cands": 0}
            continue
        gray = H.roi_best(maps[0], maps[2], ())
        color = H.roi_best(maps[1], maps[2], ())
        out[rel] = {
            "gray": gray,
            "color": color,
            "cands": len(H.roi_candidates(maps[0], maps[2], spec.threshold)),
        }
    _MEASURE_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# T1 真源 ⇄ agent 快照 ⇄ scene.team 常量（三处必须逐项一致）
# ---------------------------------------------------------------------------
def _projection_failures() -> list:
    TT = _tt()
    ti = _agent()
    sc = _load()[0]
    px = _submodule("pixels")
    msgs: list = []

    if (TT.BASE_W, TT.BASE_H) != (px.BASE_W, px.BASE_H):
        msgs.append(
            f"scene/team_templates 的 BASE={TT.BASE_W}x{TT.BASE_H} != scene.pixels 的识别空间 "
            f"{px.BASE_W}x{px.BASE_H}（720 基准空间由框架决定，不可改）"
        )
    # ① 五张模板的 (key, template, roi, threshold, order_by, window) 逐项相等。
    scene_rows = {
        key: (s.template, tuple(s.roi), float(s.threshold), s.order_by, tuple(s.window))
        for key, s in TT.TEAM_TEMPLATES.items()
    }
    snap_rows = {
        key: (tpl, tuple(roi), float(thr), ob, tuple(win))
        for key, tpl, roi, thr, ob, win in ti._S_TEAM_TEMPLATES
    }
    if set(scene_rows) != set(snap_rows):
        msgs.append(
            f"模板清单不一致：scene={sorted(scene_rows)} / agent 快照={sorted(snap_rows)}"
            f"（安装态没有 scene/，快照漏一张就等于该模板在真机上不存在）"
        )
    for key in sorted(set(scene_rows) & set(snap_rows)):
        if scene_rows[key] != snap_rows[key]:
            msgs.append(
                f"[{key}] 真源⇄agent 快照不一致：scene={scene_rows[key]} / 快照={snap_rows[key]}"
                f"（安装态用快照跑模板通道；漂了 = 真机与离线不一样）"
            )
    # ② 其余常量。
    pairs = (
        ("PARTY_NO_CROP", TT.PARTY_NO_CROP, ti._S_PARTY_NO_CROP),
        ("POWER_ROW", TT.POWER_ROW, ti._S_POWER_ROW),
        ("POWER_ROW_DY", TT.POWER_ROW_DY, ti._S_POWER_ROW_DY),
        ("POWER_ROW_DX", TT.POWER_ROW_DX, ti._S_POWER_ROW_DX),
        ("SET_SLOT_TAB_X", TT.SET_SLOT_TAB_X, ti._S_SET_SLOT_TAB_X),
        ("SET_SLOT_BAR_X0", TT.SET_SLOT_BAR_X0, ti._S_SET_SLOT_BAR_X0),
        ("SET_SLOT_BAR_STEP", TT.SET_SLOT_BAR_STEP, ti._S_SET_SLOT_BAR_STEP),
        ("SET_SLOT_BAR_MAX", TT.SET_SLOT_BAR_MAX, ti._S_SET_SLOT_BAR_MAX),
        ("SET_SNAP_TOL", TT.SET_SNAP_TOL, ti._S_SET_SNAP_TOL),
        ("PAGE_KEYS", TT.PAGE_KEYS, ti._S_PAGE_KEYS),
    )
    for name, scene_value, snap_value in pairs:
        normal = (lambda v: tuple(v) if isinstance(v, (list, tuple)) else v)
        if normal(scene_value) != normal(snap_value):
            msgs.append(f"{name} 真源={scene_value!r} != agent 快照={snap_value!r}")
    # ③ 跨模块同源：SET 圆点间距 / 档数 / 页锚点 / 队名字母表。
    if (TT.SET_SLOT_BAR_STEP, TT.SET_SLOT_BAR_MAX) != (
        sc.TEAM_BATTLE_SET_STEP_PX,
        sc.TEAM_BATTLE_SET_MAX,
    ):
        msgs.append(
            f"SET 槽位几何「{TT.SET_SLOT_BAR_STEP}px / {TT.SET_SLOT_BAR_MAX} 档」与 "
            f"scene.team 的圆点标定「{sc.TEAM_BATTLE_SET_STEP_PX}px / {sc.TEAM_BATTLE_SET_MAX} 档」不一致"
        )
    if TT.PAGE_ANCHOR_A != sc.TEAM_PAGE_ANCHOR_A or TT.PAGE_ANCHOR_B != sc.TEAM_PAGE_ANCHOR_B:
        msgs.append("页锚点真源分叉：scene/team_templates 与 scene/team 的 A/B 锚点不一致")
    if ti.TEAM_PARTY_LETTERS != sc.TEAM_PARTY_LETTERS:
        msgs.append(
            f"队名字母表漂移：scene={sc.TEAM_PARTY_LETTERS!r} agent={ti.TEAM_PARTY_LETTERS!r}"
        )
    # ★#124 真机后续③★ 字母表长度必须 == 队数（真机 10 队 ⇒ A..J）：短了，OCR 吞掉队号大字时
    #   ``Party I`` / ``Party J`` 会退化成「读不到 Party」（编队页判定成立却读不出队）。
    if len(sc.TEAM_PARTY_LETTERS) != int(sc.TEAM_PARTY_COUNT):
        msgs.append(
            f"队名字母表长度 {len(sc.TEAM_PARTY_LETTERS)} != TEAM_PARTY_COUNT "
            f"{sc.TEAM_PARTY_COUNT}（真机 10 队 ⇒ A..J；短了 Party I/J 读不出）"
        )
    if len(ti.TEAM_PARTY_LETTERS) != int(ti.TEAM_PARTY_COUNT):
        msgs.append(
            f"agent 队名字母表长度 {len(ti.TEAM_PARTY_LETTERS)} != TEAM_PARTY_COUNT "
            f"{ti.TEAM_PARTY_COUNT}（安装态用这份表兜底队号）"
        )
    # ④ party_ordinal 两实现必须同结果（字母 → 队号）。
    for letter in list(sc.TEAM_PARTY_LETTERS) + ["", "Z", "AA"]:
        if sc.party_ordinal(letter) != ti.party_ordinal(letter):
            msgs.append(
                f"party_ordinal({letter!r}) 不一致：scene={sc.party_ordinal(letter)!r} "
                f"agent={ti.party_ordinal(letter)!r}"
            )
    # ⑤ 槽位几何两实现必须同结果。
    for x in (126, 68, 117, 549, 558, 200, None):
        if TT.set_index_from_pill(x) != ti.set_index_from_pill(x):
            msgs.append(
                f"set_index_from_pill({x!r}) 不一致：scene={TT.set_index_from_pill(x)!r} "
                f"agent={ti.set_index_from_pill(x)!r}"
            )
    # ⑥ 模板真源必须能被运行时读到（安装态/仓库态都要能定位 image 目录）。
    img_dir = ti.team_image_dir()
    if img_dir is None:
        msgs.append("agent.team_image_dir() 找不到 resource/image —— 运行时模板通道会是死代码")
    else:
        for key, spec in TT.TEAM_TEMPLATES.items():
            if not (img_dir / spec.template).is_file():
                msgs.append(f"[{key}] 模板 {spec.template} 不在 agent 能读到的 image 目录里")
    return msgs


def probe_team_battle_tpl_projection() -> bool:
    """T1：模板真源 ⇄ agent 快照 ⇄ scene.team 常量逐项一致（含两实现同结果）。"""
    return _projection_failures() == []


# ---------------------------------------------------------------------------
# T2 roi 必须收窄 + order_by 必须 Score（#108 的教训）
# ---------------------------------------------------------------------------
def _roi_failures() -> list:
    TT = _tt()
    msgs: list = []
    screen = float(TT.BASE_W * TT.BASE_H)
    for key, spec in TT.TEAM_TEMPLATES.items():
        where = f"[{key}]"
        x, y, w, h = (int(v) for v in spec.roi)
        if w <= 0 or h <= 0:
            msgs.append(f"{where} roi {list(spec.roi)} 的 w/h ≤ 0（协议里 0 = 延伸到边缘）")
            continue
        if x <= 0 and y <= 0 and x + w >= TT.BASE_W and y + h >= TT.BASE_H:
            msgs.append(
                f"{where} roi {list(spec.roi)} 等于全屏 {TT.BASE_W}x{TT.BASE_H}（= 等于没写 roi："
                f"全屏 = 把兄弟图形放进候选池，选哪个由 order_by 决定）"
            )
        area = w * h / screen
        if area > ROI_AREA_MAX:
            msgs.append(
                f"{where} roi {list(spec.roi)} 占屏 {area:.1%} > {ROI_AREA_MAX:.0%}"
                f"（模板只认一小块定版图形，roi 放大只会把兄弟控件拉进候选池）"
            )
        if not TT.window_fits(spec.roi, spec.window):
            msgs.append(
                f"{where} roi {list(spec.roi)} 装不下正例窗口 {list(spec.window)} 的**整窗**"
                f"（滑窗逐位置，装不下就永远命中不了 → 静默漏检）"
            )
        if spec.order_by != "Score":
            msgs.append(
                f"{where} order_by={spec.order_by!r}，应为 \"Score\" —— threshold 只是入闸门，"
                f"选哪个由 order_by + index 决定；默认 Horizontal + 0 = **取最左**，与「最像」无关"
            )
        # ★兄弟图形必须被 roi 排除★（`SET编辑` 与 `SET` 槽同字）。
        if key == "set_selected" and TT.window_fits(spec.roi, SET_EDIT_BOX):
            msgs.append(
                f"{where} roi {list(spec.roi)} **覆盖**了兄弟图形 `SET编辑` {list(SET_EDIT_BOX)}"
                f" —— 它同样含 SET 三字母，roi 是唯一能把它们分开的东西"
            )
    return msgs


def probe_team_battle_tpl_roi_scoped() -> bool:
    """T2：每张模板都有收窄 roi（装得下正例、装不下兄弟、不占满屏）+ 显式 order_by: Score。"""
    return _roi_failures() == []


# ---------------------------------------------------------------------------
# T3 真机帧：正例命中（候选唯一）/ 负例不假阳（余量 ≥0.05）
# ---------------------------------------------------------------------------
def _frame_failures() -> list:
    missing = _deps_missing()
    if missing:
        return [missing]
    TT = _tt()
    msgs: list = []
    for key, spec in TT.TEAM_TEMPLATES.items():
        where = f"[{key}]"
        tpl_path = REPO_ROOT / spec.template_rel
        if not tpl_path.is_file():
            msgs.append(f"{where} 模板裁片缺失：{spec.template_rel}")
            continue
        absent = [
            rel
            for rel in [h.frame for h in spec.positives] + [h.frame for h in spec.negatives]
            if not (REPO_ROOT / rel).is_file()
        ]
        if absent:
            msgs.extend(f"{where} 证据帧缺失：{rel}" for rel in absent)
            continue
        if len(spec.positives) < 2:
            msgs.append(
                f"{where} 只有 {len(spec.positives)} 张正例 —— 调研 §5.6 要求「正例 ≥2 张且"
                f"不是模板的裁剪源」；样本内自证（1.0000）不证明泛化"
            )
        if spec.positive_worst < POSITIVE_MIN:
            msgs.append(
                f"{where} 存档正例保守分 {spec.positive_worst:.4f} < {POSITIVE_MIN}"
            )
        if spec.positive_margin < POSITIVE_MARGIN_MIN:
            msgs.append(
                f"{where} 正例余量 {spec.positive_margin:.4f} < {POSITIVE_MARGIN_MIN}"
                f"（正例最差 {spec.positive_worst:.4f} − 阈值 {spec.threshold}：擦线，抖一下就漏）"
            )
        if spec.margin < NEG_MARGIN_MIN:
            msgs.append(
                f"{where} 负例余量 {spec.margin:.4f} < {NEG_MARGIN_MIN}"
                f"（阈值 {spec.threshold} − 负例最高 {spec.negative_worst:.4f}：靠阈值擦屁股）"
            )
        m = measure(spec)
        # ① 正例：每张都必须命中、落在存档位置、候选**恰好 1 个**。
        for hit in spec.positives:
            got = m.get(hit.frame) or {}
            for metric in ("gray", "color"):
                res = got.get(metric)
                if res is None:
                    msgs.append(f"{where} 正例 {hit.frame} 的 roi 内无法定位（{metric}）")
                    continue
                score, gx, gy = res
                if score < spec.threshold:
                    msgs.append(
                        f"{where} 正例 {hit.frame} 的 roi 内最高 {metric} 分 {score:.4f} < 阈值 "
                        f"{spec.threshold} —— **漏检**（模板/帧/roi 变了 → 重新标定）"
                    )
                if abs(gx - hit.x) > WINDOW_TOL or abs(gy - hit.y) > WINDOW_TOL:
                    msgs.append(
                        f"{where} 正例 {hit.frame} 的 {metric} 最高分在 ({gx},{gy})，不是存档 "
                        f"({hit.x},{hit.y})（±{WINDOW_TOL}px）—— 最高分换了个地方"
                    )
            if (got.get("cands") or 0) != 1:
                msgs.append(
                    f"{where} 正例 {hit.frame} 的 roi 内 ≥阈值 的候选有 {got.get('cands')} 个"
                    f"（期望**恰好 1 个**）—— 多了就重新落到「排序决定选哪个」"
                )
        # ② 负例：一个都不许命中，且余量够。
        for hit in spec.negatives:
            got = m.get(hit.frame) or {}
            worst = None
            for metric in ("gray", "color"):
                res = got.get(metric)
                if res is None:
                    continue
                if worst is None or res[0] > worst[0]:
                    worst = res + (metric,)
            if worst is None:
                msgs.append(f"{where} 负例 {hit.frame} 无法量测（roi 比模板还小）")
                continue
            if worst[0] >= spec.threshold:
                msgs.append(
                    f"{where} 负例 {hit.frame}：roi 内不该命中，却出现 {worst[0]:.4f}"
                    f"（{worst[3]}）≥ 阈值 {spec.threshold} @({worst[1]},{worst[2]}) —— **假阳**"
                )
            elif spec.threshold - worst[0] < NEG_MARGIN_MIN:
                msgs.append(
                    f"{where} 负例 {hit.frame}：roi 内最高 {worst[0]:.4f}（{worst[3]}），余量 "
                    f"{spec.threshold - worst[0]:.4f} < {NEG_MARGIN_MIN}"
                )
    return msgs


def probe_team_battle_tpl_frames() -> bool:
    """T3：真机帧全滑窗 ZNCC —— 正例逐帧命中（候选唯一），负例逐帧不命中且余量 ≥0.05。"""
    return _frame_failures() == []


# ---------------------------------------------------------------------------
# T4 存档 ⇄ 实测（容差 0.02，含位置）；运行时实现必须给同一个数
# ---------------------------------------------------------------------------
def _archive_failures() -> list:
    missing = _deps_missing()
    if missing:
        return [missing]
    TT = _tt()
    ti = _agent()
    msgs: list = []

    def cmp(where: str, what: str, measured: float, archived: float) -> None:
        if abs(measured - archived) > SCORE_TOL:
            msgs.append(
                f"{where}：{what} 实测 {measured:.4f} vs 存档 {archived:.4f}"
                f"（差 {abs(measured - archived):.4f} > 容差 {SCORE_TOL}）—— 帧/模板/roi 变了就要"
                f"重新标定并更新 scene/team_templates.py 的存档"
            )

    for key, spec in TT.TEAM_TEMPLATES.items():
        if not (REPO_ROOT / spec.template_rel).is_file():
            msgs.append(f"[{key}] 模板裁片缺失：{spec.template_rel}")
            continue
        m = measure(spec)
        for hit in list(spec.positives) + list(spec.negatives):
            got = m.get(hit.frame) or {}
            for metric in ("gray", "color"):
                res = got.get(metric)
                if res is None:
                    msgs.append(f"[{key}] {hit.frame} 无法量测（{metric}）")
                    continue
                cmp(f"[{key}] {hit.frame}", metric, res[0], getattr(hit, metric))
                # ★位置只比灰口径★：存档的 (x, y) 是**灰口径** argmax（与 hooks_102 同一约定），
                # 彩口径的最高分本来就可能在别处（彩色信息的 argmax 与灰度不同是常态）。
                if metric != "gray":
                    continue
                if abs(res[1] - hit.x) > WINDOW_TOL or abs(res[2] - hit.y) > WINDOW_TOL:
                    msgs.append(
                        f"[{key}] {hit.frame} 的 {metric} 最高分位置 ({res[1]},{res[2]}) != 存档 "
                        f"({hit.x},{hit.y}) —— 最高分换了个地方"
                    )
        # ★roi 外危险分★：放宽到全屏时会命中哪里（存档必须对上）。
        for hit in spec.global_watch:
            tpl = _template_png(spec)
            g = _h102().zncc_gray(_frame(hit.frame), tpl)
            c = _h102().zncc_color(_frame(hit.frame), tpl)
            cmp(f"[{key}] roi 外危险分 {hit.frame}", "gray 全屏", g[hit.y, hit.x], hit.gray)
            cmp(f"[{key}] roi 外危险分 {hit.frame}", "color@窗口", c[hit.y, hit.x], hit.color)
        # ★运行时实现 ⇄ 存档★：agent 的 PNG 解码 + numpy 滑窗必须给出同一个灰分数。
        for hit in spec.positives:
            hits = _runtime_hits(hit.frame)
            if hits is None:
                msgs.append(f"[{key}] 运行时 detect_team_templates({hit.frame}) 返回 None（模板通道死）")
                continue
            score = hits.scores.get(key)
            if score is None:
                msgs.append(f"[{key}] 运行时没有量到这张模板（{hit.frame}）")
                continue
            cmp(f"[{key}] 运行时 {hit.frame}", "gray", score[0], hit.gray)
    return msgs


def probe_team_battle_tpl_archive() -> bool:
    """T4：存档 ZNCC（正/负/roi 外）与实测一致（容差 0.02），且运行时实现给同一个数。"""
    return _archive_failures() == []


# ---------------------------------------------------------------------------
# T5 模板像素：PNG == 从源帧按 window 重裁；agent 的 PNG 解码器 == PIL
# ---------------------------------------------------------------------------
def _pixel_failures() -> list:
    missing = _deps_missing()
    if missing:
        return [missing]
    TT = _tt()
    ti = _agent()
    np = _h102()._np()
    msgs: list = []
    for key, spec in TT.TEAM_TEMPLATES.items():
        path = REPO_ROOT / spec.template_rel
        if not path.is_file():
            msgs.append(f"[{key}] 模板裁片缺失：{spec.template_rel}")
            continue
        want = _template_recrop(spec)
        got = _template_png(spec)
        if got.size != want.size:
            msgs.append(
                f"[{key}] 模板 {spec.template_rel} 尺寸 {got.size} != 按 window 重裁的 {want.size}"
                f"（window {list(spec.window)}）"
            )
            continue
        if got.tobytes() != want.tobytes():
            msgs.append(
                f"[{key}] 模板 {spec.template_rel} 的**像素**与「从 {spec.source_frame} 按 window "
                f"{list(spec.window)} 重裁」不一致 —— 模板被换成了别的图（或裁剪源帧换了）"
            )
        # 运行时的纯 numpy PNG 解码器必须与 PIL 逐字节一致（安装态没有 Pillow）。
        decoded = ti._decode_png(path)
        if decoded is None:
            msgs.append(f"[{key}] agent._decode_png 解不出 {spec.template_rel}（安装态模板通道会瞎）")
            continue
        pil_arr = np.asarray(got)
        if decoded.shape != pil_arr.shape or not np.array_equal(decoded, pil_arr):
            msgs.append(
                f"[{key}] agent._decode_png 与 PIL 解码结果不一致（shape {decoded.shape} vs "
                f"{pil_arr.shape}）—— 运行时拿到的像素与离线标定不是同一张图"
            )
    return msgs


def probe_team_battle_tpl_pixels() -> bool:
    """T5：模板 PNG 逐像素 == 从源帧按 window 重裁；agent 的 PNG 解码器 == PIL。"""
    return _pixel_failures() == []


# ---------------------------------------------------------------------------
# T6 双通道：真帧上两条通道**各自**都要读对；负例两通道都不许假阳
# ---------------------------------------------------------------------------
def _dual_channel_failures() -> list:
    TT = _tt()
    ti = _agent()
    msgs: list = []
    # ① 主证据帧：OCR 通道（存档 OCR）单独成立。
    src_items = list(TT.EVIDENCE_OCR[TT.SRC_FRAME])
    if not ti.is_battle_team_page(src_items):
        msgs.append(
            f"主证据帧 {TT.SRC_FRAME} 上 **OCR 通道**判不出 A 类页（IS_BATTLE_TEAM_PAGE=False）"
            f" —— 真机 OCR 明明读到「自动续战」，说明存档或判据被改了"
        )
    hits = _runtime_hits(TT.SRC_FRAME)
    if hits is None:
        msgs.append(f"主证据帧 {TT.SRC_FRAME} 上模板通道返回 None（模板通道死）")
        return msgs
    # ② 主证据帧：模板通道**单独**成立（把 OCR 喂空，只给命中的模板键）。
    if not ti.is_battle_team_page([], tuple(hits.hit_keys)):
        msgs.append(
            "把 OCR 通道喂空、只给模板命中时判不出 A 类页 —— 「模板兜底」不成立"
            "（模板通道只是装饰）"
        )
    # ③ 两条通道都关掉时必须 False（否则判据恒真）。
    if ti.is_battle_team_page([]):
        msgs.append("空 OCR 且无模板命中时仍判成 A 类页（判据恒真）")
    # ④ ★两个解析通道各自都能读对★
    parse_only = ti.read_team(src_items, None)
    want = ((1, None), 1, 141)
    if parse_only[0] is None or parse_only[0][0] != want[0][0]:
        msgs.append(
            f"★只改解析★时真帧 SET 读不出来：{parse_only!r}（应为 SET {want[0][0]}）"
            f" —— 解析两条 bug（队号被吞 / 战力数字分框）没有真的修好"
        )
    if parse_only[1] != want[1]:
        msgs.append(
            f"★只改解析★时真帧队号读不出来：{parse_only!r}（应为 {want[1]}）"
            f" —— `Party A` 的字母序号兜底没生效"
        )
    if parse_only[2] != want[2]:
        msgs.append(
            f"★只改解析★时真帧战力读不出来：{parse_only!r}（应为 {want[2]}）"
            f" —— 「战力框 + 同行数字框」绑定没生效"
        )
    template_only = ti.read_team(list(TT.LOCALIZED_OCR[TT.SRC_FRAME]), hits)
    if (
        template_only[0] is None
        or template_only[0][0] != want[0][0]
        or template_only[1] != want[1]
        or template_only[2] != want[2]
    ):
        msgs.append(
            f"★只开模板通道★（OCR 只给模板引导的局部裁片）时读不出 {want}：{template_only!r}"
            f" —— 双通道的模板那条腿不成立"
        )
    # ⑤ 跨页：五重 / 外传 也各自成立（SET 不同：1 / 2）。
    for rel, want_set in ((TT.WUCHONG_FRAME, 1), (TT.SIDE_FRAME, 2)):
        h = _runtime_hits(rel)
        keys = tuple(getattr(h, "hit_keys", ()) or ())
        if not ti.is_battle_team_page([], keys):
            msgs.append(f"{rel} 上模板通道判不出 A 类页")
        if getattr(h, "set_index", None) != want_set:
            msgs.append(
                f"{rel} 上模板推出的 SET={getattr(h, 'set_index', None)!r}，应为 {want_set}"
                f"（槽位几何在另一族布局上错了）"
            )
    # ⑥ 负例：两通道都不许假阳（票面点名的 4 张 + 4 张同族危险页）。
    for rel in TT.NEG_FRAMES:
        h = _runtime_hits(rel)
        keys = tuple(getattr(h, "hit_keys", ()) or ())
        items = list(TT.EVIDENCE_OCR_NEG.get(rel, ()))
        if keys:
            msgs.append(
                f"负例 {rel} 上有模板命中 {list(keys)} —— **假阳**（会在这页上按 A 类坐标点 SET 条）"
            )
        if ti.is_battle_team_page(items, keys):
            msgs.append(f"负例 {rel} 被判成 A 类页")
        state = ti.read_team(items, h)
        if state != (None, None, None):
            msgs.append(
                f"负例 {rel} 上 read_team={state!r}（期望 (None, None, None)）"
                f" —— 在不是编队页的画面上读出了编队状态"
            )
    # ⑦ B 类否决票：模板命中也不许翻案（拿 A 类坐标点 B 类页 = 点到标题栏）。
    if ti.is_battle_team_page([("切换", [633, 685, 40, 24])], tuple(hits.hit_keys)):
        msgs.append(
            "B 类锚点 `^切换$` 在场时仍判成 A 类页（模板通道翻掉了结构性的否定判据）"
            " —— 会按 A 类坐标点 B 类页"
        )
    return msgs


def probe_team_battle_dual_channel() -> bool:
    """T6：双通道 —— 真帧上「只改解析」「只开模板」各自都读对，负例两通道都不假阳。"""
    return _dual_channel_failures() == []


# ---------------------------------------------------------------------------
# T7 SET 槽位几何：已知位置 → SET 号；歧义/越界 → 拒绝
# ---------------------------------------------------------------------------
def _set_index_failures() -> list:
    TT = _tt()
    ti = _agent()
    msgs: list = []
    # ① 实测过的三个位置（三张不同页面）必须给出对应 SET 号。
    cases = (
        (126, (1, "tab3"), "深渊EX 三页签 · SET 1"),
        (68, (1, "barN"), "五重圆点条 · SET 1"),
        (117, (2, "barN"), "外传圆点条 · SET 2"),
    )
    for x, want, label in cases:
        got = TT.set_index_from_pill(x)
        if got is None or (got[0], got[1]) != want:
            msgs.append(f"槽位 {x}（{label}）→ {got!r}，应为 {want}")
        if ti.set_index_from_pill(x) != got:
            msgs.append(f"槽位 {x}（{label}）运行时与真源结果不一致")
    # ② 两族布局**不得互相顶掉**：L1 的 126 与 L2 的 117 差 9 > 容差 6。
    if TT.SET_SNAP_TOL >= 9:
        msgs.append(
            f"SET_SNAP_TOL={TT.SET_SNAP_TOL} ≥ 9 —— L1 的 126 与 L2 的 117 会互相顶掉，"
            f"槽位会吸附到错的 SET"
        )
    # ③ 够不着就拒绝（绝不猜）。
    for x in (200, 0, 700, None):
        if TT.set_index_from_pill(x) is not None:
            msgs.append(f"槽位 {x!r} 不该有解（离任何槽位都远），却给出 {TT.set_index_from_pill(x)!r}")
    # ④ L1 只有第 1 项是**实测**命中，其余是外推 —— 声明必须与取证现状一致。
    if TT.SET_SLOT_TAB_MEASURED != (0,):
        msgs.append(
            f"SET_SLOT_TAB_MEASURED={TT.SET_SLOT_TAB_MEASURED!r}：仓里只有「SET 1 被选中」的帧，"
            f"第 2/3 项是从未选中页签的文字位置外推的 —— 声明必须写 (0,)，不许假装实测过"
        )
    # ⑤ 两族布局的槽位间距必须是实测值（L1 211 / L2 49）。
    if TT.SET_SLOT_TAB_X[1] - TT.SET_SLOT_TAB_X[0] != 211:
        msgs.append(f"L1 槽位间距 {TT.SET_SLOT_TAB_X[1] - TT.SET_SLOT_TAB_X[0]} != 实测 211")
    if TT.SET_SLOT_BAR_STEP != 49:
        msgs.append(f"L2 槽位间距 {TT.SET_SLOT_BAR_STEP} != 实测 49")
    return msgs


def probe_team_battle_set_index() -> bool:
    """T7：SET 槽位几何（三处实测位置 / 两族不互相顶掉 / 歧义即拒 / 外推声明）。"""
    return _set_index_failures() == []


HOOKS = [
    (
        "team-battle-coords",
        "#105",
        "A 类（战前编队页）与 B 类（编辑器）坐标必须分离：A row_y=466 / step=49 / 12 档（真机帧实测），"
        "B 是 30 / 55；scene 与 agent 快照逐项一致",
        probe_team_battle_coords,
    ),
    (
        "team-battle-page-predicate",
        "#105",
        "A/B 页判据互斥：A 类帧（有「自动续战」）→ True；B 类帧（含「切换」）→ False；无「自动续战」不判 A",
        probe_team_battle_page_predicate,
    ),
    (
        "team-battle-step-plan",
        "#105",
        "A 类 SET 步进按实测圆点序列算（1→4=260 / 4→1=113），到目标 None、越界 None",
        probe_team_battle_step_plan,
    ),
    (
        "team-battle-wiring",
        "#105",
        "team_switch_battle 已注册（my_action + live_harness 静态表）且 team.json 有 TeamSwitchBattle 节点",
        probe_team_battle_wiring,
    ),
    (
        "team-battle-party-switch",
        "#105",
        "★V5 接线（#124）★A 类页 + 目标队 ⇒ 走 switch_party（横向滑动 + 三重校验）；"
        "读不到编队 / 不在 A 类页 ⇒ 拒动（零调用零滑动零点击，打印拒动原因）；"
        "三重校验不过 ⇒ 绝不宣称成功（旧 V5「读不到就不动」这半保留）",
        probe_team_battle_party_switch,
    ),
    (
        "team-battle-tpl-projection",
        "#105",
        "模板真源 scene/team_templates.py ⇄ agent 快照逐项一致（5 张模板 + 槽位几何 + 局部 OCR 窗口 + "
        "页锚点 + 队名字母表），字母表长度必须 == TEAM_PARTY_COUNT（#124 真机 10 队 ⇒ A..J），"
        "且两实现的 party_ordinal / set_index_from_pill 同结果",
        probe_team_battle_tpl_projection,
    ),
    (
        "team-battle-tpl-roi-scoped",
        "#105",
        "每张模板 roi 收窄（装得下正例整窗、装不下 `SET编辑` 兄弟图形、≤15% 屏幕）+ 显式 order_by: Score",
        probe_team_battle_tpl_roi_scoped,
    ),
    (
        "team-battle-tpl-frames",
        "#105",
        "真机帧全滑窗 ZNCC：每张模板在**每条**正例帧命中（候选恰好 1 个，位置 ±2px）、"
        "在每条负例帧不命中且余量 ≥0.05，正例余量 ≥0.05",
        probe_team_battle_tpl_frames,
    ),
    (
        "team-battle-tpl-archive",
        "#105",
        "存档 ZNCC（正例 / 负例逐帧 / roi 外危险分 / 位置）与实测一致（容差 0.02），"
        "且 agent 运行时模板通道给出同一个数",
        probe_team_battle_tpl_archive,
    ),
    (
        "team-battle-tpl-pixels",
        "#105",
        "模板 PNG 逐像素 == 从裁剪源帧按 window 重裁；agent 的纯 numpy PNG 解码器 == PIL 解码",
        probe_team_battle_tpl_pixels,
    ),
    (
        "team-battle-dual-channel",
        "#105",
        "双通道：主证据帧上「只改解析」与「只开模板」各自都要读对（SET/队号/战力），"
        "负例 8 帧两通道都不假阳，B 类锚点否决票不被模板通道翻案",
        probe_team_battle_dual_channel,
    ),
    (
        "team-battle-set-index",
        "#105",
        "SET 槽位几何：三处实测位置 → SET 1/1/2，两族布局不互相顶掉（容差 6 < 9），"
        "够不着即拒，L1 第 2/3 项是外推必须如实声明",
        probe_team_battle_set_index,
    ),
]


def _swap_templates(**replacements) -> None:
    """把真源里的某几张模板换成「坏件」（``dataclasses.replace``，frozen 也能换）。

    破坏实验用：改完立刻跑判据，跑完由调用方 ``finally`` 恢复原值。
    """
    import dataclasses  # noqa: PLC0415

    TT = _tt()
    saved = dict(TT.TEAM_TEMPLATES)
    new = dict(saved)
    for key, patch in replacements.items():
        new[key] = dataclasses.replace(saved[key], **patch)
    TT.TEAM_TEMPLATES = new
    _MEASURE_CACHE.clear()
    return saved


def _restore_templates(saved) -> None:
    _tt().TEAM_TEMPLATES = saved
    _MEASURE_CACHE.clear()


def prove_red() -> bool:
    print("hooks_105 prove-red：逐一破坏实现，要求守卫各自变红")
    green = all(
        f()
        for f in (
            probe_team_battle_coords,
            probe_team_battle_page_predicate,
            probe_team_battle_step_plan,
            probe_team_battle_wiring,
            probe_team_battle_party_switch,
            probe_team_battle_tpl_projection,
            probe_team_battle_tpl_roi_scoped,
            probe_team_battle_tpl_frames,
            probe_team_battle_tpl_archive,
            probe_team_battle_tpl_pixels,
            probe_team_battle_dual_channel,
            probe_team_battle_set_index,
        )
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：十二个守卫全绿")
    if not green:
        for m in (
            _coords_failures()
            + _predicate_failures()
            + _step_failures()
            + _wiring_failures()
            + _party_v5_failures()
            + _projection_failures()
            + _roi_failures()
            + _frame_failures()
            + _archive_failures()
            + _pixel_failures()
            + _dual_channel_failures()
            + _set_index_failures()
        ):
            print(f"      - {m}")
        return False

    sc, ti = _load()
    TT = _tt()
    checks: list[bool] = []

    old = ti.TEAM_BATTLE_SET_ROW_Y
    try:
        ti.TEAM_BATTLE_SET_ROW_Y = sc.TEAM_SET_ROW_Y
        m = _coords_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把 A 类 row_y 改成 B 类的 30 -> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
    finally:
        ti.TEAM_BATTLE_SET_ROW_Y = old
    checks.append(red)

    old_pred = ti.is_battle_team_page
    try:
        ti.is_battle_team_page = lambda items, hit_keys=(): True
        m = _predicate_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 让页判据恒真（B 类页也当 A 类）-> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
    finally:
        ti.is_battle_team_page = old_pred
    checks.append(red)

    old_plan = ti.battle_set_tap_plan
    try:
        ti.battle_set_tap_plan = lambda cur, tgt: (999, 1) if cur != tgt else None
        m = _step_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 步进写错（恒点 x=999）-> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
    finally:
        ti.battle_set_tap_plan = old_plan
    checks.append(red)

    try:
        # 模拟「静态注册表漏登记」
        import importlib

        h = importlib.import_module("live_harness")
        saved = dict(h.CUSTOM_ACTIONS)
        h.CUSTOM_ACTIONS.pop("team_switch_battle", None)
        m = _wiring_failures()
        # 该探针读文件，不读内存表，所以这里改用「读文件内容」的破坏：直接改内存不生效
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 摘掉接线 -> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
        h.CUSTOM_ACTIONS.update(saved)
    finally:
        pass
    checks.append(red)

    # ======================= V5（#124）：队切换接线的破坏实验 =======================
    # ① 让读数缝「一读就有值」—— 读不到编队也照样切（旧 V5 的「读不到就不动」被破坏）→ 必须红。
    v5_ti = _h124()._impl()
    real_read_team = v5_ti.read_team
    try:
        v5_ti.read_team = lambda items, hits=None: ((1, [90, 458, 60, 20]), 5, 12345)
        m = _party_v5_failures()
        red = any("读不到编队" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] V5：把读数缝改成「一读就有值」（读不到也动）-> "
              f"{'红' if red else '仍绿'}"
              + (f"  {next((x for x in m if '读不到编队' in x), '')}" if m else ""))
    finally:
        v5_ti.read_team = real_read_team
    checks.append(red)

    # ② 把队切换接回旧「拒动」（switch_party 恒 False、一步不动）→ 必须红。
    real_switch = v5_ti.switch_party
    try:
        v5_ti.switch_party = lambda _target, **_kwargs: False
        m = _party_v5_failures()
        red = any("Party = 3" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] V5：把队切换接回旧拒动（switch_party 恒 False）-> "
              f"{'红' if red else '仍绿'}"
              + (f"  {next((x for x in m if 'Party = 3' in x), '')}" if m else ""))
    finally:
        v5_ti.switch_party = real_switch
    checks.append(red)

    # ======================= #105b：模板通道的破坏实验 =======================
    # ① 删 roi（改成全屏）-> T2 必须红（全屏 = 把兄弟图形放进候选池）。
    saved = _swap_templates(set_selected={"roi": (0, 0, 720, 1280)})
    try:
        m = _roi_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把 set_selected 的 roi 改成全屏 -> "
              f"{'红' if red else '仍绿'}" + (f"  {m[0]}" if m else ""))
    finally:
        _restore_templates(saved)
    checks.append(red)

    # ② 放宽阈值吃掉负例 -> T3 必须红（假阳 / 余量不足）。
    #    真机负例最高是 power_label 的 0.6249 ⇒ 阈值 0.55 一定会把负例收进来。
    saved = _swap_templates(power_label={"threshold": 0.55})
    try:
        m = _frame_failures()
        red = any("假阳" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] 把 power_label 阈值放宽到 0.55（吃掉负例）-> "
              f"{'红' if red else '仍绿'}" + (f"  {next((x for x in m if '假阳' in x), '')}" if m else ""))
    finally:
        _restore_templates(saved)
    checks.append(red)

    # ③ 模板换错文件（把 set_selected 换成「挑战」那张的像素）-> T4/T5 必须红。
    import shutil
    import tempfile

    tpl_dir = REPO_ROOT / "assets" / "resource" / "image"
    victim = tpl_dir / TT.TEAM_TEMPLATES["set_selected"].template
    backup = Path(tempfile.mkdtemp(prefix="wf105_tpl_")) / victim.name
    try:
        shutil.copy2(victim, backup)
        shutil.copy2(tpl_dir / TT.TEAM_TEMPLATES["challenge_btn"].template, victim)
        _MEASURE_CACHE.clear()
        _RUNTIME_CACHE.clear()
        _agent()._TPL_CACHE.clear()
        m_pixels = _pixel_failures()
        m_archive = _archive_failures()
        red = len(m_pixels) > 0 and len(m_archive) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把 set_selected.png 换成 challenge_btn 的像素 -> "
              f"{'红' if red else '仍绿'}" + (f"  {m_pixels[0] if m_pixels else ''}"))
    finally:
        if backup.is_file():
            shutil.copy2(backup, victim)
        shutil.rmtree(backup.parent, ignore_errors=True)
        _MEASURE_CACHE.clear()
        _RUNTIME_CACHE.clear()
        _agent()._TPL_CACHE.clear()
    checks.append(red)

    # ④ 去掉模板通道（页判据忽略 hit_keys）-> T6 必须红。
    old_page = ti.is_battle_team_page

    def _page_ocr_only(items, hit_keys=()):
        return old_page(items, ())

    try:
        ti.is_battle_team_page = _page_ocr_only
        m = _dual_channel_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 去掉模板通道（页判据只认 OCR）-> "
              f"{'红' if red else '仍绿'}" + (f"  {m[0]}" if m else ""))
    finally:
        ti.is_battle_team_page = old_page
    checks.append(red)

    # ⑤ 存档分数改虚（正例 +0.10 / 负例 −0.10）-> T4 必须红。
    saved = _swap_templates(
        auto_continue={
            "positives": tuple(
                type(h)(h.frame, round(h.gray + 0.10, 4), round(h.color + 0.10, 4), h.x, h.y)
                for h in TT.TEAM_TEMPLATES["auto_continue"].positives
            )
        }
    )
    try:
        m = _archive_failures()
        red = any("容差" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] 把 auto_continue 的存档正例分抬高 0.10 -> "
              f"{'红' if red else '仍绿'}" + (f"  {next((x for x in m if '容差' in x), '')}" if m else ""))
    finally:
        _restore_templates(saved)
    checks.append(red)

    # ⑥ 解析没修（party 兜底恒 None）-> T6 的「只改解析」腿必须红。
    old_ordinal = ti.party_ordinal
    try:
        ti.party_ordinal = lambda letter: None
        m = _dual_channel_failures()
        red = any("队号" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] 把队名字母兜底改回恒 None（解析没修）-> "
              f"{'红' if red else '仍绿'}" + (f"  {next((x for x in m if '队号' in x), '')}" if m else ""))
    finally:
        ti.party_ordinal = old_ordinal
    checks.append(red)

    # ⑦ 槽位容差放到 10（两族布局互相顶掉）-> T7 必须红。
    saved_tol = TT.SET_SNAP_TOL
    try:
        TT.SET_SNAP_TOL = 10
        _agent().TEAM_SET_SNAP_TOL = 10
        m = _set_index_failures()
        red = any("互相顶掉" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] 把槽位吸附容差改成 10（两族布局互相顶掉）-> "
              f"{'红' if red else '仍绿'}" + (f"  {next((x for x in m if '互相顶掉' in x), '')}" if m else ""))
    finally:
        TT.SET_SNAP_TOL = saved_tol
        _agent().TEAM_SET_SNAP_TOL = saved_tol
    checks.append(red)

    # ⑧ 字母表退回 8 个（Party I/J 读不出）-> T1 投影必须红（#124 真机后续③）。
    saved_letters = sc.TEAM_PARTY_LETTERS
    try:
        sc.TEAM_PARTY_LETTERS = "ABCDEFGH"
        m = _projection_failures()
        red = any("字母表长度" in x for x in m)
        print(f"  [{'PASS' if red else 'FAIL'}] 把队名字母表退回 8 个（Party I/J 读不出）-> "
              f"{'红' if red else '仍绿'}"
              + (f"  {next((x for x in m if '字母表长度' in x), '')}" if m else ""))
    finally:
        sc.TEAM_PARTY_LETTERS = saved_letters
    checks.append(red)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
