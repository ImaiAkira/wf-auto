# -*- coding: utf-8 -*-
"""离线单测：#22 单目标打满配置次数后**明确收工**（复用 ``SpecialBatchStop``）。

不需要游戏、不需要 maa 运行时（判定全在链 / pipeline 结构 / 结算动作的 stub 上）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_settle_stop.py

覆盖 #22 的验收：

  1. **收工边在场**：链 ``终端pipeline节点[收工] == "SpecialBatchStop"``；``结算终点``
     在 ``已打次数 >= 目标次数`` 时给出「收工」、否则「归位」；``decide`` / ``navigate``
     对结算页一致（缺省不限次 = 旧行为不变）；
  2. **pipeline 落点**：``SpecialBatchStop`` 是 ``DirectHit + StopTask``、``next`` 为空；
     结算节点 ``SpecialResultContinue`` 的动作是 custom ``special_batch_finish``（收工闸落点）；
  3. **单目标收工闸（agent）**：stub context 下，单目标 + 打满 → ``override_next`` 指向
     ``SpecialBatchStop``；未打满 / 不限次 / 批量 / 非 special / 读不到节点定义 → 绝不覆盖；
  4. **确定性复现**：用例「目标已打满」—— 接线态必经 ``SpecialBatchStop`` 收工；
     旧形态（去掉收工边）走回无限重进（死循环）。两条都作为断言固化；
  5. 无漂移 + #9 守卫仍绿 + ``hooks_22.prove_red()`` 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_22.py``。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_22  # noqa: E402
from scene import chain as C  # noqa: E402
from scene import drift  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402
from scene.navigation import decide, navigate  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 链上的收工边
# ---------------------------------------------------------------------------
def test_chain_settle_terminal() -> None:
    print("\n== 1. 链上的收工边：打满配置次数 → 结算终点 = 收工 ==")
    check("终端映射：收工 → SpecialBatchStop",
          C.终端pipeline节点.get(C.TERMINAL_收工) == "SpecialBatchStop",
          f"map={C.终端pipeline节点}")

    check("不限次（目标次数=None）→ 归位（旧行为不变）",
          C.结算终点(None, 99).名称 == C.TERMINAL_归位)
    check("未打满（1/2）→ 归位", C.结算终点(2, 1).名称 == C.TERMINAL_归位)
    check("打满（2/2）→ 收工", C.结算终点(2, 2).名称 == C.TERMINAL_收工)
    check("超出（5/1，防累计越界）→ 收工", C.结算终点(1, 5).名称 == C.TERMINAL_收工)
    check("收工原因点名次数（不吞掉依据）", "次数" in C.结算终点(1, 1).原因,
          f"原因={C.结算终点(1, 1).原因!r}")

    check("decide(结算页) 缺省 → 归位",
          getattr(decide(LORD_BATTLE, "结算页", hooks_22.LORD), "名称", None) == C.TERMINAL_归位)
    check("decide(结算页, 打满) → 收工",
          getattr(decide(LORD_BATTLE, "结算页", hooks_22.LORD, 目标次数=1, 已打次数=1),
                  "名称", None) == C.TERMINAL_收工)

    done = navigate(LORD_BATTLE, hooks_22.LORD, 起始页面="结算页", 目标次数=1, 已打次数=1)
    check("navigate(从结算页, 打满) → 收工", done.结局 == "收工", f"结局={done.结局}")
    live = navigate(LORD_BATTLE, hooks_22.LORD, 起始页面="结算页")
    check("navigate(从结算页, 不限次) → 归位后仍到达",
          live.结局 == "到达" and "归位" in live.路径, f"结局={live.结局} 路径={live.路径}")

    # 链的形状校验仍通过（结算下一步在两种情形下都解析得到）。
    check("validate_chain 仍通过", C.validate_chain(LORD_BATTLE) == [],
          f"errors={C.validate_chain(LORD_BATTLE)}")


# ---------------------------------------------------------------------------
# 2. pipeline 落点
# ---------------------------------------------------------------------------
def test_pipeline_terminal() -> None:
    print("\n== 2. pipeline 落点：SpecialBatchStop 在场（DirectHit + StopTask + next 空） ==")
    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    node = sd.get("SpecialBatchStop")
    check("SpecialBatchStop 在场", isinstance(node, dict))
    if isinstance(node, dict):
        check("SpecialBatchStop = DirectHit", (node.get("recognition") or {}).get("type") == "DirectHit")
        check("SpecialBatchStop 动作 = StopTask", (node.get("action") or {}).get("type") == "StopTask")
        check("SpecialBatchStop.next 为空（终止）", node.get("next") == [], f"next={node.get('next')!r}")
    action = (sd.get("SpecialResultContinue") or {}).get("action") or {}
    check("结算节点动作 = custom special_batch_finish（收工闸落点）",
          action.get("param", {}).get("custom_action") == "special_batch_finish", f"action={action}")
    check("配置次数节点 SpecialFightTargetRow 在场（收工闸判据来源）",
          isinstance(sd.get("SpecialFightTargetRow"), dict))
    for src, dst in hooks_22.REQUIRED_EDGES:
        check(f"复现模型边 {src} → {dst}", dst in ((sd.get(src) or {}).get("next") or []))


# ---------------------------------------------------------------------------
# 3. 单目标收工闸（agent，stub context）
# ---------------------------------------------------------------------------
def test_agent_gauge() -> None:
    print("\n== 3. 单目标收工闸：打满 → override_next 指向 SpecialBatchStop ==")
    check("接线检查（链 + pipeline + agent）全绿", hooks_22.settle_stop_failures() == [],
          f"fails={hooks_22.settle_stop_failures()[:2]}")
    check("挂点 single-target-settle-stop 已点亮",
          hooks_22.probe_single_target_settle_stop() is True)


# ---------------------------------------------------------------------------
# 4. 确定性复现：目标已打满
# ---------------------------------------------------------------------------
def test_offline_repro() -> None:
    print("\n== 4. 确定性复现「目标已打满」：新形态收工 / 旧形态无限重进 ==")
    new = hooks_22.settle_trace(configured=1, fought=1)
    print("     新形态（收工边在场）：")
    print("       " + " → ".join(new))
    check("新形态末尾走到收工", new[-1] == hooks_22.STOP_TERMINAL, f"末尾={new[-1]!r}")
    check("新形态必经 SpecialBatchStop", hooks_22.STOP_NODE in new)
    check("新形态不再出现「详情页无开打 → 归位弹回」的重进环",
          new.count("SpecialOpenLord") == 0, f"trace={new}")

    old = hooks_22.settle_trace(configured=1, fought=1, stop_wired=False)
    print("     旧形态（去掉收工边）：")
    print("       " + " → ".join(old[:12]) + " …")
    check("旧形态走到步数上限 = 无限重进（复现本票缺陷）", old[-1] == "…(无限重进)")
    check("旧形态永远到不了 SpecialBatchStop", hooks_22.STOP_NODE not in old)
    check("旧形态复现 #13 的环（重进 → 详情页 → 归位弹回）",
          "详情页" in old and old.count("SpecialOpenLord") >= 2)

    # 把「去掉收工边」做成真实的产物改动（临时 scene 副本），同一用例必须复现死循环。
    scene_root = hooks_22._temp_scene_copy()
    try:
        hooks_22._sub(
            scene_root / "scene" / "chain.py",
            "    if 目标次数 is not None and 已打次数 >= 目标次数:",
            "    if False:  # #22 收工边被摘掉（复现旧行为）",
        )
        red = hooks_22._run_probe_in(scene_root, "probe_single_target_no_reenter") is False
        check("产物级反证：摘掉收工边的副本上，同一用例复现无限重进（守卫红）", red)
    finally:
        shutil.rmtree(scene_root, ignore_errors=True)

    check("挂点 single-target-no-reenter 已点亮",
          hooks_22.probe_single_target_no_reenter() is True)


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫仍绿 + prove-red
# ---------------------------------------------------------------------------
def test_drift_guards_prove_red() -> None:
    print("\n== 5. 无漂移 + #9 守卫仍绿 + prove-red 成立 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")
    check("hooks_22.prove_red() 成立（摘掉收工接线 / 去掉链的收工边各自变红）",
          hooks_22.prove_red() is True)


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测：#22 单目标打满配置次数后明确收工（复用 SpecialBatchStop）")
    print("=" * 72)
    test_chain_settle_terminal()
    test_pipeline_terminal()
    test_agent_gauge()
    test_offline_repro()
    test_drift_guards_prove_red()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
