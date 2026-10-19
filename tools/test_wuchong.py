# -*- coding: utf-8 -*-
"""#56（Phase 4）五重决战 移植 —— 离线一键守卫入口（独立可跑）。

    .venv\\Scripts\\python.exe tools\\test_wuchong.py

它把 hooks_wuchong 的七个守卫集中跑一遍（便于单独定位），再加上「流水线自包含 / 手操节奏 /
跨模式自动 / 模板入库」的结构断言与 prove-red。契约入口（test_offline_contract）仍会通过
HOOKS 自动发现同一批守卫。

判据全在纯 Python + 配置数据 + pipeline JSON + 已入库裁片上，**不需要游戏 / 设备**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent"), str(TOOLS / "contract_hooks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from contract_hooks import hooks_wuchong as h56  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _pipe() -> dict:
    return h56._pipe()


def test_hooks_green() -> None:
    print("\n== 1. hooks_wuchong 二十一个守卫点亮（probe=True） ==")
    check("配置权威", h56.probe_wuchong_config_is_source_of_truth() is True)
    check("手操节奏参数化", h56.probe_wuchong_manual_cadence_parameterised() is True)
    check("跨模式自动", h56.probe_wuchong_cross_mode_auto() is True)
    check("流程按数据落地", h56.probe_wuchong_flow_materialised() is True)
    check("裁片可区分", h56.probe_wuchong_banner_distinct() is True)
    check("classify 正例", h56.probe_wuchong_classify_positives() is True)
    check("不污染全局判据表", h56.probe_wuchong_no_global_table_growth() is True)
    check("弹窗先走开始招募", h56.probe_wuchong_recruit_dialog_before_auto() is True)
    check("共斗房有出路", h56.probe_wuchong_room_has_exit() is True)
    check("手操引擎关不重选", h56.probe_wuchong_battle_engine_gated() is True)
    check("游戏模式门控有效流水线", h56.probe_wuchong_mode_gates() is True)
    check("游戏模式默认 = 多人", h56.probe_wuchong_mode_default_multi() is True)
    check("房间先于战斗", h56.probe_wuchong_room_before_battle() is True)
    check("开关读数不依赖 PIL", h56.probe_wuchong_switch_readable_without_pil() is True)
    check("手操确定性不被选项合并吃掉", h56.probe_wuchong_manual_survives_option_merge() is True)
    check("「打几次」打够 N 次收工", h56.probe_wuchong_fight_count() is True)
    check("interface.json 无重复键", h56.probe_wuchong_interface_no_duplicate_keys() is True)
    check("开始类闩锁 = 重试窗口", h56.probe_wuchong_latch_retries() is True)
    check("打够后不在战斗内收工", h56.probe_wuchong_giveup_out_of_fight() is True)
    check("战斗内 unknown 不计未知画面", h56.probe_wuchong_unknown_not_counted_in_fight() is True)
    check("打够后先结算收尾再收工", h56.probe_wuchong_finish_settle_cleanup() is True)


def test_pipeline_structure() -> None:
    print("\n== 2. wuchong.json 结构：自包含 / 入口 / 导航顺序 / 手操闸 ==")
    p = _pipe()
    entry = h56._node(p, "WuchongEntry").get("next") or []
    leaf_like = {
        "WuchongClick", "WuchongSwipe", "WuchongLordState", "WuchongDetailState", "WuchongModeState",
        "WuchongRoomState", "WuchongRecruitDialogState", "WuchongTeamState", "WuchongSettleState",
        "WuchongBattleState", "WuchongRowBanner", "WuchongDetailBanner", "WuchongReconnectText",
        "WuchongReconnectBtn", "WuchongBonusText", "WuchongBonusNoBtn", "WuchongBonusYesBtn",
        "WuchongDisbandText", "WuchongReturnRoomText", "WuchongContinueText", "WuchongChallengeText",
        "WuchongStartText", "WuchongJossTabText",
    }
    flow_like = {
        "WuchongNavLord", "WuchongNavJoss", "WuchongNavRow", "WuchongScrollList",
        "WuchongDetailFight", "WuchongModeSolo", "WuchongModeMulti", "WuchongRecruitOpen",
        "WuchongRecruitStart", "WuchongCoopChallenge", "WuchongStaleTeam",
        #   ↓ #83 单人模式的房间出口（流程步：next = 异常前缀 + WuchongEntry）。
        "WuchongRoomLeave",
        "WuchongTeamAutoSet", "WuchongTeamContSet",
        "WuchongTeamChallenge", "WuchongRoomWait", "WuchongBattleAutoGuard",
        #   ↑ WuchongBattleAutoGuard 是 #56 二批**已删除**的死名（保留此项只为不把历史节点误判成辅助节点）；
        #   ↓ WuchongBattleAutoOff 是 #71 的**具名例外**（战斗页关自动；流程节点，next = 异常前缀 + 后继）。
        "WuchongBattleAutoOff",
        "WuchongBattle", "WuchongSettleContinue", "WuchongSettleReturnRoom",
        "WuchongSettleDisband", "WuchongWait",
    }
    bad = []
    for name, node in p.items():
        if name == "WuchongEntry" or name in leaf_like or name in flow_like:
            continue
        nxt = node.get("next") if isinstance(node, dict) else None
        if nxt is None:
            continue
        if (node.get("action") or {}).get("type") == "StopTask":
            if nxt != []:
                bad.append((name, nxt))
            continue
        if nxt != ["WuchongEntry"]:
            bad.append((name, nxt))
    check("辅助/事件节点 next 回 ['WuchongEntry']（StopTask 出口 = []）", bad == [], f"bad={bad[:3]}")

    for must in ("WuchongNavLord", "WuchongNavJoss", "WuchongNavRow", "WuchongScrollList",
                 "WuchongDetailFight", "WuchongModeSolo", "WuchongModeMulti", "WuchongRecruitOpen",
                 "WuchongRecruitStart", "WuchongTeamAutoSet", "WuchongTeamContSet",
                 "WuchongTeamChallenge", "WuchongRoomWait", "WuchongBattleAutoOff",
                 "WuchongBattle", "WuchongSettleContinue",
                 "WuchongSettleReturnRoom", "WuchongSettleDisband"):
        check(f"WuchongEntry.next 含 {must}", must in entry)
    check("WuchongWait 是链尾兜底", entry and entry[-1] == "WuchongWait", f"tail={entry[-1:]!r}")
    check("无 max_hit 的万能兜底 WuchongWait 不含 max_hit", "max_hit" not in h56._node(p, "WuchongWait"))

    # 手操闸：WuchongBattle 的动作 = wuchong_battle。
    check("WuchongBattle 动作 = wuchong_battle",
          ((h56._node(p, "WuchongBattle").get("action") or {}).get("param") or {}).get("custom_action") == "wuchong_battle")


def test_registrations_present() -> None:
    print("\n== 3. 注册接线：my_reco / my_action 指向 wuchong_impl ==")
    for fname, needle in (
        ("my_reco.py", 'custom_recognition("wuchong_state")'),
        ("my_reco.py", 'custom_recognition("wuchong_giveup")'),
        ("my_reco.py", 'custom_recognition("wuchong_switch_state")'),
        ("my_action.py", 'custom_action("wuchong_battle")'),
        ("my_action.py", 'custom_action("wuchong_switch")'),
        ("my_action.py", 'custom_action("wuchong_act")'),
    ):
        text = (ROOT / "agent" / fname).read_text(encoding="utf-8")
        check(f"{fname} 含 {needle}", needle in text)
    iface = h56._interface()
    tasks = {t.get("name"): t for t in iface.get("task") or []}
    check("interface 有任务『五重决战』", "五重决战" in tasks)
    task = tasks.get("五重决战") or {}
    check("任务入口 = WuchongEntry", task.get("entry") == "WuchongEntry")
    from scene import wuchong as w  # noqa: PLC0415

    for opt in ("是否手操", "游戏模式", "使用领主加成点数", "手操节奏参数", w.TARGET_FIGHTS_OPTION):
        check(f"任务挂选项「{opt}」", opt in (task.get("option") or []))


def test_cross_mode_option_scope() -> None:
    print("\n== 4. 跨模式：只有五重挂「是否手操」 ==")
    iface = h56._interface()
    holders = [t.get("name") for t in iface.get("task") or [] if "是否手操" in (t.get("option") or [])]
    check("只有「五重决战」挂「是否手操」", holders == ["五重决战"], f"holders={holders}")


def test_banner_assets() -> None:
    print("\n== 5. 模板入库 + 可靠区分 ==")
    from scene import wuchong as w  # noqa: PLC0415

    for tpl in (w.ROW_TEMPLATE, w.DETAIL_TEMPLATE):
        check(f"{tpl} 入库", (ROOT / "assets" / "resource" / "image" / tpl).is_file())
    check("行用 TemplateMatch",
          h56._node(_pipe(), "WuchongRowBanner").get("recognition", {}).get("type") == "TemplateMatch")
    check("详情用 TemplateMatch",
          h56._node(_pipe(), "WuchongDetailBanner").get("recognition", {}).get("type") == "TemplateMatch")


SKIPS: list[str] = []


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


def _pick_ocr_assets() -> Path | None:
    """真机帧 OCR 需要的资源目录（含 model/ocr/det.onnx）；缺模型 → SKIP（不算失败）。"""
    import os  # noqa: PLC0415

    cands = [ROOT / "assets" / "resource", Path(os.environ.get("WF_H48_ASSETS", "")) if os.environ.get("WF_H48_ASSETS") else None]
    for d in cands:
        if d is not None and (d / "model" / "ocr" / "det.onnx").is_file():
            return d
    return None


def _ocr_frame(assets: Path, name: str):
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return None, f"缺 numpy/PIL：{exc!r}"
    path = ROOT / "tools" / "frames" / name
    if not path.is_file():
        return None, f"缺帧：{path}"
    try:
        import live_harness as ca  # noqa: PLC0415

        pil = Image.open(path).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        return ca.ocr(img, assets), None
    except Exception as exc:  # noqa: BLE001
        return None, f"OCR 不可用：{exc!r}"


def test_finish_real_frames() -> None:
    """★2026-10-19 收尾★ 真机帧回放（best-effort）：打够次数后，共斗结算页应点【解散】回主城。

    证据帧 = #48 已入库的 ``coop_result_dissolve.png``（共斗结算第三屏，【解散】/【返回房间】）
    + ``coop_result_home.png``（点【解散】后的主城）。缺 OCR 模型时 SKIP。
    """
    print("\n== 6. 真机帧回放：收尾点【解散】→ 主城（best-effort） ==")
    assets = _pick_ocr_assets()
    if assets is None:
        skip("真机帧回放（2026-10-19 收尾）", "缺 OCR 模型 model/ocr/det.onnx")
        return
    try:
        import sys as _sys  # noqa: PLC0415

        if str(ROOT / "agent") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "agent"))
        import wuchong_impl as wc  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        skip("真机帧回放（2026-10-19 收尾）", f"wuchong_impl 不可导入：{exc!r}")
        return

    skip_pat = ["^再次挑战$", "^继续挑战$"]
    prefer = ["^解散$"]
    items, err = _ocr_frame(assets, "coop_result_dissolve.png")
    if items is None:
        skip("真机共斗结算帧", err or "OCR 失败")
    else:
        state, _info = wc.classify(items)
        check("真机共斗结算帧 → wuchong_settle", state == "wuchong_settle", f"state={state}")
        wait, started = wc.finish_settle_wait(state, False, True, 0.0, 100.0)
        check("打够次数 + 结算帧 → 先收尾", wait is True)
        what, _nxt, prefer_now = wc.finish_adjust_targets(
            ["^再次挑战$", "^继续挑战$", "^继续$", "^OK$"], ["^OK$", "^返回房间$"], True,
            skip_pat, prefer,
        )
        check("收尾剔除【再次挑战】/【继续挑战】", "^再次挑战$" not in what and "^继续挑战$" not in what,
              f"what={what}")
        target = wc.locate_button(items, prefer_now, roi=(0, 1150, 720, 1280))
        check("真机帧上定位到【解散】（读后动）", target is not None, f"target={target}")
        if target is not None:
            _t, _cx, cy = target
            banner = wc.locate_button(items, ["QUESTRE"])
            check("绝不点顶部 QUESTRESULT 横幅",
                  banner is not None and abs(cy - banner[2]) > 400,
                  f"banner_y={banner[2] if banner else None}")
        home, err2 = _ocr_frame(assets, "coop_result_home.png")
        if home is None:
            skip("真机主城帧", err2 or "OCR 失败")
        else:
            state_home, _ = wc.classify(home)
            check("【解散】落点帧 = 主城", state_home == "main_city", f"state={state_home}")
            wait_home, _s = wc.finish_settle_wait(state_home, False, True, started, 200.0)
            check("主城 → 立刻收工", wait_home is False)


def test_prove_red() -> None:
    print("\n== 7. 破坏实验：逐一改坏实现，守卫必须各自变红 ==")
    check("hooks_wuchong.prove_red()", h56.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("#56 Phase 4：五重决战 移植（导航复用 + ★手操战斗★ + 跨模式自动规则）")
    print("=" * 72)
    test_hooks_green()
    test_pipeline_structure()
    test_registrations_present()
    test_cross_mode_option_scope()
    test_banner_assets()
    test_finish_real_frames()
    test_prove_red()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"SKIP {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_wuchong: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
