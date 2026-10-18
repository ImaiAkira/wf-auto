# -*- coding: utf-8 -*-
"""#55（Phase 2）深渊EX 移植 —— 离线一键守卫入口（独立可跑）。

    .venv\\Scripts\\python.exe tools\\test_abyss.py

它把 hooks_abyss 的六个守卫集中跑一遍（便于单独定位），再加上「流水线自包含 / 单人 /
无套 / 30 层阶梯」的结构断言与 prove-red。契约入口（test_offline_contract）仍会通过
HOOKS 自动发现同一批守卫。

判据全在纯 Python + 配置数据 + pipeline JSON 上，**不需要游戏 / 设备**。
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

from contract_hooks import hooks_abyss as h55  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _pipe() -> dict:
    return h55._abyss_pipe()


def test_hooks_green() -> None:
    print("\n== 1. hooks_abyss 八个守卫点亮（probe=True） ==")
    check("配置权威", h55.probe_abyss_config_is_source_of_truth() is True)
    check("页签数据驱动", h55.probe_abyss_tab_search_data_driven() is True)
    check("全单人无共斗", h55.probe_abyss_solo_no_coop() is True)
    check("30 层无套", h55.probe_abyss_ladder_30_no_sets() is True)
    check("横幅可区分", h55.probe_abyss_banner_distinct() is True)
    check("classify 正例", h55.probe_abyss_classify_positives() is True)
    check("不污染全局判据表", h55.probe_abyss_no_global_table_growth() is True)
    check("普通深渊接线", h55.probe_abyss_plain_wired() is True)


def test_pipeline_structure() -> None:
    print("\n== 2. abyss.json 结构：自包含 / 单人 / 入口 / 导航顺序 ==")
    p = _pipe()
    entry = h55._node(p, "AbyssEntry").get("next") or []
    # 铁律 1：业务节点 next 一律回 AbyssEntry（叶型识别辅助节点 next=None 跳过）。
    leaf_like = {"AbyssClick", "AbyssZhongshiGate", "AbyssSettleState", "AbyssBannerEx",
                 "AbyssContinueChallengeText", "AbyssEnterConfirmText", "AbyssEnterConfirmOk",
                 "AbyssLevelGateLine1", "AbyssLevelGateLine2", "AbyssReconnectText", "AbyssReconnectBtn"}
    bad = []
    for name, node in p.items():
        if name == "AbyssEntry" or name in leaf_like:
            continue
        nxt = node.get("next") if isinstance(node, dict) else None
        if nxt is None:
            continue
        if nxt != ["AbyssEntry"]:
            bad.append((name, nxt))
    check("所有 Abyss* 业务节点 next 回 ['AbyssEntry']", bad == [], f"bad={bad[:3]}")

    for must in ("AbyssWait", "AbyssGiveUp", "AbyssStall", "AbyssMainFight", "AbyssSoloChallenge",
                 "AbyssEnterConfirm", "AbyssHubEnter", "AbyssNavBanner", "AbyssNavTab",
                 "AbyssNavZhongshi", "AbyssNavActivity"):
        check(f"AbyssEntry.next 含 {must}", must in entry)
    check("AbyssWait 是链尾兜底", entry and entry[-1] == "AbyssWait", f"tail={entry[-1:]!r}")
    check("无 max_hit 的万能兜底 AbyssWait 不含 max_hit", "max_hit" not in h55._node(p, "AbyssWait"))
    # 单人：不得有共斗节点。
    coop = [n for n in p if n.startswith("AbyssCoop") or n.startswith("AbyssRecruit")]
    check("无共斗节点", coop == [], f"coop={coop}")


def test_registrations_present() -> None:
    print("\n== 3. 注册接线：my_reco / my_action 指向 abyss_impl ==")
    for fname, needle in (
        ("my_reco.py", 'custom_recognition("abyss_state")'),
        ("my_reco.py", 'custom_recognition("abyss_giveup")'),
        ("my_reco.py", 'custom_recognition("abyss_scene")'),
        ("my_action.py", 'custom_action("abyss_act")'),
    ):
        text = (ROOT / "agent" / fname).read_text(encoding="utf-8")
        check(f"{fname} 含 {needle}", needle in text)
    iface = h55._load_jsonc(ROOT / "assets" / "interface.json")
    tasks = {t.get("name"): t for t in iface.get("task") or []}
    check("interface 有任务『自动刷深渊EX』", "自动刷深渊EX" in tasks)
    task = tasks.get("自动刷深渊EX") or {}
    check("任务入口 = AbyssEntry", task.get("entry") == "AbyssEntry")
    check("任务无「刷几套」选项", "option" not in task or "刷几套" not in (task.get("option") or []))


def test_plain_wired() -> None:
    print("\n== 3b. 普通深渊（#55 Phase 3）：同实现 + 数据（「只差导航」） ==")
    check("abyss-plain-wired 守卫", h55.probe_abyss_plain_wired() is True)
    iface = h55._load_jsonc(ROOT / "assets" / "interface.json")
    tasks = {t.get("name"): t for t in iface.get("task") or []}
    check("interface 有任务『自动刷深渊』", "自动刷深渊" in tasks)
    plain_task = tasks.get("自动刷深渊") or {}
    check("普通深渊任务入口 = AbyssPlainEntry", plain_task.get("entry") == "AbyssPlainEntry")
    p = _pipe()
    check(
        "AbyssEntry.next 接入 AbyssPlainNavBanner",
        "AbyssPlainNavBanner" in (h55._node(p, "AbyssEntry").get("next") or []),
    )
    check(
        "AbyssEntry.next 接入 AbyssPlainEnterConfirm",
        "AbyssPlainEnterConfirm" in (h55._node(p, "AbyssEntry").get("next") or []),
    )


def test_banner_assets() -> None:
    print("\n== 4. 横幅模板入库 + 可靠区分 ==")
    for tpl in ("banner_abyss_ex.png", "banner_abyss_plain.png"):
        check(f"{tpl} 入库", (ROOT / "assets" / "resource" / "image" / tpl).is_file())
    check("EX 横幅用 TemplateMatch",
          h55._node(_pipe(), "AbyssBannerEx").get("recognition", {}).get("type") == "TemplateMatch")
    check("普通深渊横幅用 TemplateMatch",
          h55._node(_pipe(), "AbyssBannerPlain").get("recognition", {}).get("type") == "TemplateMatch")


def test_prove_red() -> None:
    print("\n== 5. 破坏实验：逐一改坏实现，守卫必须各自变红 ==")
    check("hooks_abyss.prove_red()", h55.prove_red() is True)


def main() -> int:
    print("=" * 72)
    print("#55 Phase 2：深渊EX 移植（30 层线性阶梯 / 全单人无共斗 / 数据驱动搜页签）")
    print("=" * 72)
    test_hooks_green()
    test_pipeline_structure()
    test_registrations_present()
    test_plain_wired()
    test_banner_assets()
    test_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_abyss: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
