# -*- coding: utf-8 -*-
"""#91：「切换编队」数据/识别/动作/接线 的四道契约。

## 真机标定（2026-10-17，384 = 127.0.0.1:16384，720x1280）
- 编队页 = 主城「角色」→「队伍编成」；顶部一排圆点是 SET 选择器，选中项浮 `SET N` 标签，
  标签 x 随选中项移动（SET 1 → x=30，SET 10 → x=525，SET 11 → x=578），相邻圆点距 ≈55px。
- 圆点行会滚动：同一次标定里 x=109 读到 `SET 1`、x=178 读到 `SET 3` ⇒ **固定坐标不可用**，
  只能「读 → 点标签邻居 → 再读」闭环（:func:`set_tap_plan`）。
- 队标签形如 `5 Party E`；队箭头几何未真机确认 ⇒ 动作里每次点击后复查，没变化就放弃。

## 契约
- **T1 数据单一真源**：`scene/team.py` 是唯一真源，`agent/team_impl.py` 的快照必须逐项相等
  （安装态没有 `scene/`，只能靠快照；漂移就是真机坐标走错的开始）。
- **T2 闭环步进**：`set_tap_plan` 必须「按标签框算邻居 + 夹边界 + 到目标返回 None」，
  不许出现「固定坐标一步到位」的用法。
- **T3 读得对**：`read_team` 能从真机那一帧的 OCR 项读出 `SET 10 / 队 5 / 战力 13116`。
- **T4 接线**：`interface.json` 有「切换编队」选项与任务；`assets/resource/pipeline/team.json`
  有 3 个节点且 custom 名就是 `team_state` / `team_switch`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"

#: 真机那一帧（debug/wc384_set1_back.png → pipeline OCR）的逐字文本。
FRAME_ITEMS = [
    ("SET 1", [30, 14, 48, 19]),
    ("5 Party E", [78, 74, 96, 24]),
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


# ---------------------------------------------------------------------------
# T1 数据单一真源（scene ⇄ agent 快照）
# ---------------------------------------------------------------------------
_NAMES = (
    "TEAM_SET_ROW_Y",
    "TEAM_SET_STEP_PX",
    "TEAM_MAX_SETS",
    "TEAM_PARTY_COUNT",
    "TEAM_SET_RE",
    "TEAM_PARTY_RE",
    "TEAM_POWER_RE",
    "TEAM_MAX_STEPS",
    "TEAM_TAP_MIN_X",
    "TEAM_TAP_MAX_X",
    "TEAM_OPTION_NONE",
    "TEAM_PRESET_384",
    "TEAM_PRESET_484",
)


def _drift_failures() -> list:
    sc, ti = _load()
    msgs = []
    for name in _NAMES:
        a, b = getattr(sc, name, "<missing>"), getattr(ti, name, "<missing>")
        if a != b:
            msgs.append(f"{name} 漂移：scene={a!r} agent={b!r}（安装态用的是 agent 快照，漂移=真机坐标错）")
    if ti.CFG_SOURCE != "scene":
        msgs.append(f"team_impl 没读到 scene（CFG_SOURCE={ti.CFG_SOURCE!r}）—— 仓库态应当 import 到真源")
    return msgs


def probe_team_source_of_truth() -> bool:
    return _drift_failures() == []


# ---------------------------------------------------------------------------
# T2 闭环步进
# ---------------------------------------------------------------------------
def _plan_failures() -> list:
    _sc, ti = _load()
    msgs = []
    # 往右走：标签在左端 (30,14,48,19) → 下一跳 = 30+48+55 = 133
    got = ti.set_tap_plan(1, 3, [30, 14, 48, 19])
    if got != (133, 1):
        msgs.append(f"往右一步算错：{got!r}（应 (133, 1) = 标签右边 + 55）")
    # 往左走：标签在 x=525 宽 57 → 525-55 = 470
    got = ti.set_tap_plan(10, 1, [525, 14, 57, 20])
    if got != (470, -1):
        msgs.append(f"往左一步算错：{got!r}（应 (470, -1) = 标签左边 - 55）")
    # 到目标不动
    if ti.set_tap_plan(5, 5, [200, 14, 50, 20]) is not None:
        msgs.append("已到目标还给出点击计划（会白点）")
    # 边界夹住
    x, _d = ti.set_tap_plan(2, 1, [20, 14, 40, 20])
    if not (ti.TEAM_TAP_MIN_X <= x <= ti.TEAM_TAP_MAX_X):
        msgs.append(f"边界没夹住：{x}（应在 {ti.TEAM_TAP_MIN_X}..{ti.TEAM_TAP_MAX_X}）")
    # 标签框缺失 → 不许瞎点
    if ti.set_tap_plan(1, 4, None) is not None:
        msgs.append("没有标签框还给出点击计划（会瞎点）")
    return msgs


def probe_team_closed_loop_plan() -> bool:
    return _plan_failures() == []


# ---------------------------------------------------------------------------
# T3 读得对（真机那一帧）
# ---------------------------------------------------------------------------
def _read_failures() -> list:
    _sc, ti = _load()
    msgs = []
    set_no, party, power = ti.read_team(list(FRAME_ITEMS))
    if not set_no or set_no[0] != 1:
        msgs.append(f"SET 读错：{set_no!r}（真机帧是 SET 1）")
    if party != 5:
        msgs.append(f"队号读错：{party!r}（真机帧是 5 Party E → 5）")
    if power != 13116:
        msgs.append(f"战力读错：{power!r}（真机帧是 13,116）")
    # 空输入不许抛
    if ti.read_team([]) != (None, None, None):
        msgs.append("空 OCR 输入没有返回三个 None")
    # 噪声不误判
    if ti.read_team([("随便什么", [1, 2, 3, 4])])[0] is not None:
        msgs.append("噪声文本被误判成 SET 标签")
    return msgs


def probe_team_reads_real_frame() -> bool:
    return _read_failures() == []


# ---------------------------------------------------------------------------
# T4 接线（选项 + 任务 + pipeline 节点）
# ---------------------------------------------------------------------------
def _wiring_failures() -> list:
    _paths()
    import jsonc  # noqa: PLC0415

    from scene import team as sc  # noqa: PLC0415

    msgs = []
    iface = jsonc.load(open(REPO_ROOT / "assets" / "interface.json", encoding="utf-8"))
    opt = (iface.get("option") or {}).get("切换编队")
    if not opt:
        msgs.append("interface.json 缺「切换编队」选项")
    else:
        names = [c.get("name") for c in opt.get("cases") or []]
        want = sc.option_values()
        if names != want:
            msgs.append(f"选项值域与 scene.team.option_values() 不一致：{names} vs {want}")
        if opt.get("default_case") not in names:
            msgs.append(f"default_case 不在值域里：{opt.get('default_case')!r}")
        for n in names:
            try:
                sc.parse_option(n)
            except ValueError as exc:  # noqa: PERF203
                msgs.append(f"选项 {n!r} 解析失败：{exc}")
    if not any((t or {}).get("entry") == "TeamEntry" for t in iface.get("task") or []):
        msgs.append("interface.json 缺「切换编队」任务（entry=TeamEntry）")
    nodes = jsonc.load(open(REPO_ROOT / "assets" / "resource" / "pipeline" / "team.json", encoding="utf-8"))
    for name in ("TeamEntry", "TeamOpenEditor", "TeamSwitch"):
        if name not in nodes:
            msgs.append(f"pipeline/team.json 缺节点 {name}")
    sw = nodes.get("TeamSwitch") or {}
    reco = ((sw.get("recognition") or {}).get("param") or {}).get("custom_recognition")
    act = ((sw.get("action") or {}).get("param") or {}).get("custom_action")
    if reco != "team_state":
        msgs.append(f"TeamSwitch.recognition 应为 team_state，实际 {reco!r}")
    if act != "team_switch":
        msgs.append(f"TeamSwitch.action 应为 team_switch，实际 {act!r}")
    # 注册（安装态靠这两行把 custom 名字接上）
    for path, need in (
        (REPO_ROOT / "agent" / "my_reco.py", 'custom_recognition("team_state")'),
        (REPO_ROOT / "agent" / "my_action.py", 'custom_action("team_switch")'),
    ):
        text = path.read_text(encoding="utf-8")
        if need not in text:
            msgs.append(f"{path.name} 缺注册：{need}")
    return msgs


def probe_team_wiring() -> bool:
    return _wiring_failures() == []


HOOKS = [
    (
        "team-source-of-truth",
        "#91",
        "切换编队数据单一真源：scene/team.py 的 13 个常量必须与 agent/team_impl.py 的快照逐项相等"
        "（安装态没有 scene/，只能靠快照；漂移=真机坐标走错）",
        probe_team_source_of_truth,
    ),
    (
        "team-closed-loop-plan",
        "#91",
        "切 SET 必须闭环：按标签框算邻居 + 夹边界 + 到目标不动 + 无标签框不瞎点"
        "（真机：圆点行会滚动，固定坐标点几次就偏一位）",
        probe_team_closed_loop_plan,
    ),
    (
        "team-reads-real-frame",
        "#91",
        "从真机那一帧的 OCR 读出 SET / 队 / 战力（SET 1 / 队 5 / 13,116）；空输入不抛、噪声不误判",
        probe_team_reads_real_frame,
    ),
    (
        "team-wiring",
        "#91",
        "接线完整：interface 选项值域 == scene.team.option_values()、任务 entry=TeamEntry、"
        "pipeline/team.json 三节点、custom 名 team_state/team_switch 且已注册",
        probe_team_wiring,
    ),
]


# ---------------------------------------------------------------------------
def prove_red() -> bool:
    sc, ti = _load()
    print("hooks_91 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_team_source_of_truth()
        and probe_team_closed_loop_plan()
        and probe_team_reads_real_frame()
        and probe_team_wiring()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：四个守卫全绿")
    if not green:
        for m in _drift_failures() + _plan_failures() + _read_failures() + _wiring_failures():
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    # ① 快照漂移 → T1 红
    old = ti.TEAM_SET_STEP_PX
    try:
        ti.TEAM_SET_STEP_PX = old + 7
        m = _drift_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 让 agent 快照的圆点间距漂 +7px -> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
    finally:
        ti.TEAM_SET_STEP_PX = old
    checks.append(red)

    # ② 步进方向写反 → T2 红
    real_plan = ti.set_tap_plan
    try:
        def _reversed(current, target, box):
            got = real_plan(current, target, box)
            return (got[0], -got[1]) if got else got

        ti.set_tap_plan = _reversed
        m = _plan_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把步进方向写反 -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else ""))
    finally:
        ti.set_tap_plan = real_plan
    checks.append(red)

    # ③ 队号解析错位 → T3 红
    real_read = ti.read_team
    try:
        def _bad_read(items):
            s, _p, pw = real_read(items)
            return s, (2 if s else None), pw

        ti.read_team = _bad_read
        m = _read_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 让队号恒读成 2 -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else ""))
    finally:
        ti.read_team = real_read
    checks.append(red)

    # ④ 选项值域与真源脱钩 → T4 红
    real_values = sc.option_values
    try:
        sc.option_values = lambda sets=1, parties=6: ["不切换", "Set1第1队"]
        m = _wiring_failures()
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 让选项值域与 interface 脱钩 -> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
    finally:
        sc.option_values = real_values
    checks.append(red)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
