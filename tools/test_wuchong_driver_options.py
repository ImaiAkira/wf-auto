# -*- coding: utf-8 -*-
"""#56 coop-fix2：真机 driver 的界面选项**代表产品**（审计 P0）。

审计结论：「从一个不应用界面选项的 driver 跑出来的任何一次，都不具代表性」——
``run_wuchong_live.py`` 过去只把任务名交给 Tasker，「游戏模式 / 是否手操 / 是否自动续战 /
手操节奏参数」全不生效。本测试钉死：

  · ``tools/interface_options.py`` 与 MFAAvalonia 同一条缝（按任务 option 列表顺序叠加 case）；
  · 产品默认（不指定选项）→ 多人游戏（规格 B5「默认多人」）+ 自动 + 自动续战关 + 手操引擎关（raw WuchongBattle=__NONE__）；
  · ``--mode 多人`` / ``--manual 手操`` / ``--cont`` / ``--cadence`` 各自真的改到对应节点；
  · ``--manual 手操`` 把手操**确定性**打开（WuchongBattle 识别开启 + 动作 manual=true）；
  · ``run_wuchong_live.py`` 真的挂了这些 flag 并调用解析器。

纯离线、不触设备。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import interface_options as iopt  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _rec(node: dict) -> dict:
    return (node or {}).get("recognition") or {}


def _expected(rec: dict):
    return ((rec.get("param") or {}).get("expected"))


def _cap(node: dict) -> dict:
    return (((node or {}).get("action") or {}).get("param") or {}).get("custom_action_param") or {}


def test_product_default() -> None:
    print("\n== 1. 产品默认（不指定选项） ==")
    ov = iopt.resolve_task_override(ROOT, "五重决战", {}, extra_options=("是否自动续战",))
    # 默认「游戏模式=多人游戏」（规格 B5「默认多人」）→ 关掉单人卡 + 门控多人开战路径。
    check("默认关掉 WuchongModeSolo（多人游戏）",
          _expected(_rec(ov.get("WuchongModeSolo") or {})) == ["__NONE__"],
          f"{_rec(ov.get('WuchongModeSolo') or {})}")
    check("默认不关 WuchongModeMulti（多人游戏）",
          _expected(_rec(ov.get("WuchongModeMulti") or {})) != ["__NONE__"],
          f"{_rec(ov.get('WuchongModeMulti') or {})}")
    all_of = (((ov.get("WuchongTeamChallenge") or {}).get("recognition") or {}).get("param") or {}).get("all_of") or []
    room_seen = None
    for leaf in all_of:
        if isinstance(leaf, dict):
            lr = leaf.get("recognition") or {}
            if lr.get("type") == "Custom":
                room_seen = ((lr.get("param") or {}).get("custom_recognition_param") or {}).get("room_seen")
    check("默认 → WuchongTeamChallenge 要求 room_seen=true（不先战斗）", room_seen is True, f"room_seen={room_seen!r}")
    check("默认打开 WuchongCoopChallenge / WuchongStaleTeam（多人开战路径）",
          _expected(_rec(ov.get("WuchongCoopChallenge") or {})) != ["__NONE__"]
          and _expected(_rec(ov.get("WuchongStaleTeam") or {})) != ["__NONE__"])
    # 默认「是否手操=自动」→ 编队页自动=开（on=True）+ 手操引擎关。
    on = _cap(ov.get("WuchongTeamAutoSet") or {}).get("on")
    check("默认「是否手操=自动」→ 自动=开（on=True）", on is True, f"on={on!r}")
    check("默认关掉手操引擎 WuchongBattle",
          _expected(_rec(ov.get("WuchongBattle") or {})) == ["__NONE__"])
    # 默认「是否自动续战=否」→ 关掉 SpecialAutoContinueSet。
    check("默认关掉 SpecialAutoContinueSet（自动续战=否）",
          _expected(_rec(ov.get("SpecialAutoContinueSet") or {})) == ["__NONE__"])


def test_raw_battle_disabled() -> None:
    print("\n== 1b. raw 默认 WuchongBattle 关闭（手操引擎关 = 结点不被选中） ==")
    text = iopt.strip_jsonc(
        (ROOT / "assets" / "resource" / "pipeline" / "wuchong.json").read_text(encoding="utf-8")
    )
    pipes = json.loads(text)
    raw = _rec(pipes.get("WuchongBattle") or {})
    check("raw WuchongBattle 识别 = __NONE__",
          _expected(raw) == ["__NONE__"], f"{raw}")
    # 「手操」case 必须显式开启它。
    iface = iopt.load_interface(ROOT)
    cases = {c.get("name"): c for c in ((iface.get("option") or {}).get("是否手操") or {}).get("cases") or []}
    hand = ((cases.get("手操") or {}).get("pipeline_override") or {}).get("WuchongBattle") or {}
    check("「手操」case 开启 WuchongBattle（识别非 __NONE__）",
          _expected(_rec(hand)) != ["__NONE__"], f"{_rec(hand)}")


def test_mode_multi() -> None:
    print("\n== 2. --mode 多人 → 关掉单人卡 + 门控多人开战路径 ==")
    ov = iopt.resolve_task_override(ROOT, "五重决战", {"游戏模式": "多人游戏"})
    check("多人 → WuchongModeSolo 关",
          _expected(_rec(ov.get("WuchongModeSolo") or {})) == ["__NONE__"],
          f"{_rec(ov.get('WuchongModeSolo') or {})}")
    check("多人 → WuchongModeMulti 不被关",
          _expected(_rec(ov.get("WuchongModeMulti") or {})) != ["__NONE__"])

    # ★coop-fix2★：关一张模式卡不足以让多人成立（真机 07:45：入口从 stale 单人编队页直接开战）。
    #   多人还须：编队页→挑战 要求「进过共斗房」；打开共斗房挑战；打开 stale 编队页出口。
    all_of = (((ov.get("WuchongTeamChallenge") or {}).get("recognition") or {}).get("param") or {}).get("all_of") or []
    room_seen = None
    for leaf in all_of:
        if isinstance(leaf, dict):
            lr = leaf.get("recognition") or {}
            if lr.get("type") == "Custom":
                room_seen = ((lr.get("param") or {}).get("custom_recognition_param") or {}).get("room_seen")
    check("多人 → WuchongTeamChallenge 要求 room_seen=true（不先战斗）", room_seen is True, f"room_seen={room_seen!r}")

    cpp = (((ov.get("WuchongCoopChallenge") or {}).get("recognition") or {}).get("param") or {}).get("custom_recognition_param") or {}
    check("多人 → 打开共斗房挑战（房间 + 已招募）",
          cpp.get("state") == "wuchong_room" and cpp.get("recruit_state") == "started", f"{cpp}")

    spp = (((ov.get("WuchongStaleTeam") or {}).get("recognition") or {}).get("param") or {}).get("custom_recognition_param") or {}
    check("多人 → 打开 stale 编队页出口（room_seen=false）",
          spp.get("state") == "wuchong_team" and spp.get("room_seen") is False, f"{spp}")


def test_mode_solo() -> None:
    print("\n== 2b. --mode 单人 → 关掉多人卡 + 多人专用节点保持关 ==")
    ov = iopt.resolve_task_override(ROOT, "五重决战", {"游戏模式": "单人游戏"})
    check("单人 → WuchongModeMulti 关",
          _expected(_rec(ov.get("WuchongModeMulti") or {})) == ["__NONE__"])
    check("单人 → WuchongCoopChallenge / WuchongStaleTeam 保持关",
          _expected(_rec(ov.get("WuchongCoopChallenge") or {})) == ["__NONE__"]
          and _expected(_rec(ov.get("WuchongStaleTeam") or {})) == ["__NONE__"])


def test_manual() -> None:
    print("\n== 3. --manual 手操 → 编队页自动=关 + 手操确定性开启 ==")
    ov = iopt.resolve_task_override(ROOT, "五重决战", {"是否手操": "手操"})
    on = _cap(ov.get("WuchongTeamAutoSet") or {}).get("on")
    check("手操 → 自动=关（on=False）", on is False, f"on={on!r}")
    check("手操 → WuchongBattle 不被关（手操引擎启用）",
          _expected(_rec(ov.get("WuchongBattle") or {})) != ["__NONE__"])
    check("手操 → WuchongBattle 动作 manual=true（确定性手动）",
          _cap(ov.get("WuchongBattle") or {}).get("manual") is True,
          f"{_cap(ov.get('WuchongBattle') or {})}")


def test_cadence() -> None:
    print("\n== 4. --cadence 真的落进 WuchongBattle.custom_action_param ==")
    from scene import wuchong as w  # noqa: PLC0415

    ov = iopt.resolve_task_override(ROOT, "五重决战", {})
    cap = _cap(ov.get("WuchongBattle") or {})
    # ★#71★：默认节奏 = scene.wuchong.BATTLE_PARAMS（**四个**字段；已删「手操连点时长」）。
    #   从真源**派生**断言，绝不再硬编码 tuple（漂移即红）。
    for p in w.BATTLE_PARAMS:
        check(f"默认节奏 {p.field}={p.default}", cap.get(p.field) == p.default, f"{cap.get(p.field)!r}")
    check("已删的截断旋钮 duration_s 不在默认参数里", "duration_s" not in cap, f"{cap!r}")
    ov2 = iopt.resolve_task_override(
        ROOT, "五重决战", {}, {"弹板间隔": "500", "连点批量": "3"}
    )
    cap2 = _cap(ov2.get("WuchongBattle") or {})
    check("覆盖 弹板间隔=500（int 定型）", cap2.get("flipper_gap_ms") == 500, f"{cap2.get('flipper_gap_ms')!r}")
    check("覆盖 连点批量=3（int 定型）", cap2.get("burst") == 3, f"{cap2.get('burst')!r}")


def test_manual_keeps_cadence() -> None:
    print("\n== 4b. 手操 + 节奏参数 叠加：manual 与节奏同时在场（顺序无关） ==")
    from scene import wuchong as w  # noqa: PLC0415

    ov = iopt.resolve_task_override(
        ROOT, "五重决战", {"是否手操": "手操"}, {"弹板间隔": "500"}
    )
    cap = _cap(ov.get("WuchongBattle") or {})
    check("叠加后 manual 仍为 true", cap.get("manual") is True, f"{cap}")
    check("叠加后 弹板间隔=500 仍在", cap.get("flipper_gap_ms") == 500, f"{cap}")
    # ★#71★：叠加后参数集仍等于真源四字段（无 duration_s；节奏参数真源派生）。
    check("叠加后仍无 duration_s（手操无固定时长截断）", "duration_s" not in cap, f"{cap}")
    check("叠加后字段集 == BATTLE_PARAMS 四字段",
          {p.field for p in w.BATTLE_PARAMS} <= set(cap), f"{sorted(set(cap))}")


def test_driver_wires_flags() -> None:
    print("\n== 5. run_wuchong_live.py 真的挂了选项 flag 并调用解析器 ==")
    text = (TOOLS / "run_wuchong_live.py").read_text(encoding="utf-8")
    for needle in ('"--mode"', '"--manual"', '"--cont"', '"--cadence"', "wuchong_override",
                   "import interface_options", "[options] 生效的界面选项覆盖"):
        check(f"driver 含 {needle}", needle in text)


def main() -> int:
    print("=" * 72)
    print("#56 coop-fix2：driver 界面选项代表性（与产品同一条缝）")
    print("=" * 72)
    test_product_default()
    test_raw_battle_disabled()
    test_mode_multi()
    test_mode_solo()
    test_manual()
    test_cadence()
    test_manual_keeps_cadence()
    test_driver_wires_flags()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_wuchong_driver_options: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
