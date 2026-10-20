# -*- coding: utf-8 -*-
"""离线单测：领主战类链式拓扑 + 导航决策（ticket #4 / ADR-0002）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_chain.py
    .venv\\Scripts\\python.exe tools\\test_scene_chain.py --prove-red   # 破坏实验

覆盖 ticket #4 的验收标准：

  1. 链是**页面驱动**的：每个节点锚在一个全局页面判据上，每页恰好一个锚点，
     链的页面集 = family 页序 = 全局判据集（主路径覆盖全部已知页面）；
  2. ``decide`` 对每个已知页面给出正确的**显式后继**（页签由目标子族决定；
     错页签自恢复回列表页）；
  3. 从任意已知页面出发都能到达目标（含模式选择与加成弹窗两步）；
  4. 目标不可达 → **有界重试**后返回「收工」，不无限空转；
  5. 范围追加：详情页那一步**读该成员实际支持的难度档**；目标难度不在其中 → 收工；
  6. 结算 → 归位（通用事件）→ 主城；全程离线、无设备。

``--prove-red`` 复制一份 ``scene`` 包、施加一处破坏、再用子进程重跑本 lane 的
契约挂点（``tools/contract_hooks/hooks_4.py``），要求守卫变红。本 lane **不**改中央的
prove-red 配方清单（``test_offline_contract.py`` 归另一条 lane），破坏步骤留在本文件里。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from scene import chain as C  # noqa: E402
from scene.chain import (  # noqa: E402
    build_chain,
    found_difficulties,
    page_names,
    resolve_target,
    validate_chain,
    _占位目标,
)
from scene.config import FamilyConfig, member  # noqa: E402
from scene.lord_battle import FAMILY, LORD_BATTLE  # noqa: E402
from scene.navigation import decide, navigate  # noqa: E402

FAILS: list[str] = []

LORD = {"成员": "猩红巨熊讨伐", "难度": "高级"}
JOSS = {"成员": "苍叹机兵", "难度": "超级"}


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
def test_page_anchored() -> None:
    print("\n== 1. 页面驱动：每个节点锚在全局页面判据上，每页恰好一个锚点 ==")
    check("链校验通过", validate_chain(LORD_BATTLE) == [], f"errors={validate_chain(LORD_BATTLE)}")

    chain = build_chain(LORD_BATTLE, _占位目标(LORD_BATTLE))
    pages = chain.页面集()
    names = page_names()

    check("每个节点的页面都在全局判据注册表里", all(p in names for p in pages))
    check("每页恰好一个锚点（页面→节点是函数）", len(set(pages)) == len(pages),
          f"pages={pages}")
    check("链的页面集 = family 页序", set(pages) == set(FAMILY.页序),
          f"diff={set(pages) ^ set(FAMILY.页序)}")
    check("链的页面集 = 全局判据集（覆盖全部已知页面）", set(pages) == names,
          f"diff={set(pages) ^ names}")
    check("每个节点的下一步都能解析（节点或终点）",
          all(ref in {n.id for n in chain.nodes} | set(C.终端名称)
              for n in chain.nodes for ref in n.下一步))

    # 反例：直接构造一个页面越界的链（借 validate_chain 的页面解析分支）。
    from scene.chain import Chain, Node, Step  # noqa: PLC0415
    bad_chain = Chain(family_id="x", nodes=(Node("n", "根本不存在的页面", (Step("x"),), ("n",)),))
    check("构造证明：页面越界会被 validate_chain 抓到",
          any("根本不存在的页面" in e for e in _validate_chain_with(bad_chain)))


def _validate_chain_with(bad_chain) -> list[str]:
    """在 validate_chain 的页面解析分支上验证一个坏链（monkeypatch build_chain）。"""
    import scene.chain as cc  # noqa: PLC0415
    orig = cc.build_chain
    cc.build_chain = lambda cfg, tgt: bad_chain  # type: ignore[assignment]
    try:
        return cc.validate_chain(LORD_BATTLE)
    finally:
        cc.build_chain = orig  # type: ignore[assignment]


def test_decide_every_page() -> None:
    print("\n== 2. decide：每个已知页面 → 正确的显式后继 ==")
    找到 = {"初级", "中级", "高级", "高级+", "超级"}
    期望 = {
        "主城": C.NODE_列表,
        "领主战列表页": C.NODE_领主战页签,
        "领主战页签": C.NODE_详情,
        "降临讨伐页签": C.NODE_列表,  # 领主战目标站在降临页签上 → 自恢复回列表
        "详情页": C.NODE_模式,
        "模式选择页": C.NODE_加成,
        "加成弹窗": C.NODE_编队,
        "编队页": C.NODE_战斗,
        "战斗HUD": C.NODE_结算,
    }
    for page, want in 期望.items():
        got = decide(LORD_BATTLE, page, LORD, 发现难度集=找到)
        check(f"{page} → {want}", isinstance(got, C.Node) and got.id == want,
              f"got={getattr(got, 'id', getattr(got, '名称', got))}")

    settle = decide(LORD_BATTLE, "结算页", LORD)
    check("结算页 → 归位（通用事件）", isinstance(settle, C.Terminal) and settle.名称 == "归位",
          f"got={getattr(settle, '名称', settle)}")
    check("归位 → 回主城", getattr(settle, "到页面", "") == "主城")


def test_tab_branch_and_recovery() -> None:
    print("\n== 3. 页签由目标子族决定；错页签自恢复 ==")
    check("列表页 + 领主战目标 → 领主战页签",
          decide(LORD_BATTLE, "领主战列表页", LORD).id == C.NODE_领主战页签)
    check("列表页 + 降临讨伐目标 → 降临讨伐页签",
          decide(LORD_BATTLE, "领主战列表页", JOSS).id == C.NODE_降临讨伐页签)
    check("降临讨伐页签 + 降临讨伐目标 → 详情页",
          decide(LORD_BATTLE, "降临讨伐页签", JOSS).id == C.NODE_详情)
    check("降临讨伐页签 + 领主战目标 → 回列表页（自恢复）",
          decide(LORD_BATTLE, "降临讨伐页签", LORD).id == C.NODE_列表)
    check("领主战页签 + 降临讨伐目标 → 回列表页（自恢复）",
          decide(LORD_BATTLE, "领主战页签", JOSS).id == C.NODE_列表)


def test_detail_difficulty_gate() -> None:
    print("\n== 4. 详情页难度门：难度由详情页发现，不在其中 → 收工 ==")
    ok = decide(LORD_BATTLE, "详情页", LORD, 发现难度集={"初级", "中级", "高级"})
    check("目标难度在发现集内 → 下一步 = 模式选择页",
          isinstance(ok, C.Node) and ok.id == C.NODE_模式)
    bad = decide(LORD_BATTLE, "详情页", LORD, 发现难度集={"初级", "中级"})
    check("目标难度不在发现集内 → 收工",
          isinstance(bad, C.Terminal) and bad.名称 == "收工")
    check("收工点名目标难度与可用集",
          isinstance(bad, C.Terminal) and "高级" in bad.原因 and "初级" in bad.原因,
          f"原因={getattr(bad, '原因', '')}")

    # 详情页那一步确实产出一个「可用难度集」观测量（范围追加的落点）。
    chain = build_chain(LORD_BATTLE, _占位目标(LORD_BATTLE))
    详情 = chain.by_page("详情页")
    check("详情页节点含『读可用难度档』这一步",
          详情 is not None and any(s.观测 == "可用难度集" for s in 详情.步骤))

    # seam：成员显式覆盖支持难度集时，发现集取覆盖（#3 的可选覆盖）。
    覆盖配置 = FamilyConfig(
        family=FAMILY,
        members=[member("降临讨伐", "只打初级机兵", "只打初级机兵", ["初级"])],
    )
    tgt = resolve_target(覆盖配置, {"成员": "只打初级机兵", "难度": "初级"})
    check("显式覆盖的支持难度集 = 发现集", found_difficulties(覆盖配置, tgt) == frozenset({"初级"}))
    check("覆盖外的难度 → 收工",
          decide(覆盖配置, "详情页", {"成员": "只打初级机兵", "难度": "超级"}).名称 == "收工")


def test_unreachable_and_bounded_retry() -> None:
    print("\n== 5. 不可达 → 有界重试 → 收工（不无限空转） ==")
    # 目标行名在列表上始终看不到（模拟 OCR 认不出）→ 页签节点自恢复重试到上限。
    r = navigate(LORD_BATTLE, LORD, 可见行=set())
    check("目标行找不到 → 收工", r.结局 == "收工", f"结局={r.结局}")
    check("有界：路径长度受限（不无限空转）", len(r.路径) <= 20, f"len={len(r.路径)}")
    check("收工点名『有界重试』", "有界重试" in r.原因, f"原因={r.原因}")
    check("重试上限缺省 = 链上节点最大重试上限",
          navigate(LORD_BATTLE, LORD, 可见行=set()).原因
          == f"目标行【{resolve_target(LORD_BATTLE, LORD).行名}】未找到（有界重试 3 次后收工）")

    # 行可见 → 到达。
    r2 = navigate(LORD_BATTLE, LORD, 可见行={"猩红巨熊讨伐", "其它行"})
    check("目标行可见 → 到达", r2.结局 == "到达", f"结局={r2.结局}")

    # 难度不可达 → 收工（不重试）。
    r3 = navigate(LORD_BATTLE, LORD, 发现难度集={"初级"})
    check("难度不在发现集 → 收工", r3.结局 == "收工" and "可用难度集" in r3.原因)

    # 未知页面 / 未知成员 → 收工。
    check("未知页面 → 收工", decide(LORD_BATTLE, "不存在页", LORD).名称 == "收工")
    check("未知成员 → 收工", decide(LORD_BATTLE, "主城", {"成员": "幽灵", "难度": "高级"}).名称 == "收工")
    check("未知起始页面 → 收工", navigate(LORD_BATTLE, LORD, 起始页面="不存在页").结局 == "收工")


def test_reach_from_any_page() -> None:
    print("\n== 6. 从任意已知页面都能到达目标（含模式选择 / 加成弹窗） ==")
    for 目标, 名 in ((LORD, "领主战目标"), (JOSS, "降临讨伐目标")):
        chain = build_chain(LORD_BATTLE, resolve_target(LORD_BATTLE, 目标))
        bad = [p for p in chain.页面集() if navigate(LORD_BATTLE, 目标, 起始页面=p).结局 != "到达"]
        check(f"{名}：全部 {len(chain.页面集())} 个已知页面都能到达", bad == [], f"到不了={bad}")
    # 显式点名这两步。
    check("从模式选择页能到达", navigate(LORD_BATTLE, JOSS, 起始页面="模式选择页").结局 == "到达")
    check("从加成弹窗能到达", navigate(LORD_BATTLE, JOSS, 起始页面="加成弹窗").结局 == "到达")
    # 从结算页出发：归位 → 主城 → 再走到目标。
    r = navigate(LORD_BATTLE, JOSS, 起始页面="结算页")
    check("从结算页：归位后仍能到达", r.结局 == "到达" and "归位" in r.路径, f"路径={r.路径}")


def test_data_driven_target() -> None:
    print("\n== 7. 数据驱动：新增一个成员后链仍对它有解（只改数据） ==")
    新 = member("降临讨伐", "新成员·链测试", "新成员·链测试", ["初级", "中级"])
    扩展 = FamilyConfig(family=FAMILY, members=[*LORD_BATTLE.members, 新],
                        overrides=list(LORD_BATTLE.overrides))
    tgt = {"成员": "新成员·链测试", "难度": "中级"}
    check("新成员可解析为目标", resolve_target(扩展, tgt) is not None)
    check("新成员：从主城到达", navigate(扩展, tgt).结局 == "到达")
    check("新成员：从任意已知页面到达",
          all(navigate(扩展, tgt, 起始页面=p).结局 == "到达"
              for p in build_chain(扩展, resolve_target(扩展, tgt)).页面集()))
    check("新成员：难度门按其覆盖生效（超级不可用）",
          decide(扩展, "详情页", {"成员": "新成员·链测试", "难度": "超级"}).名称 == "收工")


def test_offline() -> None:
    print("\n== 8. 完全离线：无 adb / 无 maa 运行时 ==")
    # 决策只依赖页面标识，导入/决策过程不加载任何设备模块。
    banned = {"adb", "uiautomation", "maafw", "maa", "agent"}
    命中 = sorted(m for m in banned if m in sys.modules)
    check("决策未引入设备 / 网络模块", 命中 == [], f"命中={命中}")


# ---------------------------------------------------------------------------
# --prove-red：复制 scene 包 → 施加一处破坏 → 子进程重跑本 lane 的挂点，要求变红
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _run_probe_in(root: Path, probe_name: str):
    """在子进程里、以 ``root`` 作为 ``scene`` 包来源跑一个挂点；返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_4 import probe_chain_page_anchored, probe_decide_next_node\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
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


def _break_and_check(label: str, mutate, probe_name: str) -> bool:
    """复制整个 scene 包 → 施加一处破坏 → 真实挂点须绿、坏副本挂点须红。"""
    tmp = Path(tempfile.mkdtemp(prefix="wf_chain_pr_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
        mutate(tmp)
        green_ok = _run_probe_in(REPO_ROOT, probe_name) is True
        red_ok = _run_probe_in(tmp, probe_name) is False
        print(f"  [{'PASS' if green_ok and red_ok else 'FAIL'}] {label}"
              f"  (真实探针绿={green_ok}, 破坏后变红={red_ok})")
        return green_ok and red_ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prove_red() -> int:
    print("\n--prove-red：逐一破坏链实现，要求本 lane 的挂点各自变红（红 = 可用信号）")
    checks = [
        _break_and_check(
            "破坏 chain-page-anchored（把一个节点锚到不存在的页面）",
            lambda t: _sub(
                t / "scene" / "chain.py",
                'NODE_主城,\n            "主城",',
                'NODE_主城,\n            "根本不存在的页面",',
            ),
            "probe_chain_page_anchored",
        ),
        _break_and_check(
            "破坏 decide-next-node（详情页难度门恒通过）",
            lambda t: _sub(
                t / "scene" / "navigation.py",
                "        if target.难度 not in 可用:",
                "        if False:",
            ),
            "probe_decide_next_node",
        ),
    ]
    ok = all(checks)
    print(f"  [{'PASS' if ok else 'FAIL'}] #4 挂点可绿可红、红的含义可用")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("离线单测：领主战类链式拓扑 + 导航决策（scene.chain / scene.navigation）")
    print("=" * 70)
    test_page_anchored()
    test_decide_every_page()
    test_tab_branch_and_recovery()
    test_detail_difficulty_gate()
    test_unreachable_and_bounded_retry()
    test_reach_from_any_page()
    test_data_driven_target()
    test_offline()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")

    if "--prove-red" in sys.argv[1:]:
        return prove_red()
    return 0


if __name__ == "__main__":
    sys.exit(main())
