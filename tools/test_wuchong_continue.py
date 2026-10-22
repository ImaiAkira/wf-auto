# -*- coding: utf-8 -*-
"""离线单测（#72）：五重决战 GAMEOVER → 点【续关】（不是【放弃】）；续关次数由 user 指定。

不需要游戏 / 设备（判据全在内嵌的真机帧 OCR + pipeline 结构 / 引擎纯逻辑上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_wuchong_continue.py
    .venv\\Scripts\\python.exe tools\\test_wuchong_continue.py --prove-red

覆盖 #72 的验收（规格 docs/spec/wuchong-spec.md B3 / B6 / D3 / D6）：

  1. **数据声明**：``PubGameOverContinueBtn`` / ``PubGameOverContinue`` 在场，判据与
     ``scene.wuchong`` 一致，``And(横幅,「是否续关?」,【续关】) box_index=2`` →
     ``Click target:true``（点**续关框中心**、零死偏移）、叶子型、引用叶在场。
  2. **真机帧回放**（内嵌 #38 帧逐条 OCR）：GAMEOVER 帧命中且点【续关】框中心 (506,1061)；
     确认框 / 编队页 / 体力弹窗 / 「只有横幅」/「只有询问」都不命中。
  3. **续关费 ≠ 体力恢复**（D6）：GAMEOVER 帧上体力两步节点都 miss；体力弹窗帧上续关节点 miss；
     GAMEOVER 星导石的 y 中心在体力星导石行 ROI **之外**（ROI 承重）。并钉住 GAMEOVER 短语的
     唯一真源：``scene.wuchong`` 的短语 == ``side_impl.GAMEOVER_TITLE/GAMEOVER_PROMPT``。
  4. **五重点续关、不再点放弃**：``continue_refs()`` 顺序 + 都在 ``FLOW_EXCEPTIONS``（guard 在前）；
     流程链与 ``step_next``/``hub_next`` 同步；无『放弃』；``WuchongContinueGuard`` 是 ``StopTask``；
     全 pipeline 无固定续关坐标；``SpecialEntry.next`` 仍引用 #38 四节点（批量仍拒绝续关）。
  5. **续关次数可配置 + 有界**：驱动**真实** ``WuchongContinueGuardRecognition`` —— ``target=2``
     第 3 个 episode 收工并点名 2（cap 优先）、``target=0`` 不限、``target=1`` 第 2 个收工；
     每 episode 恰记一次（按**进入 GAMEOVER 屏的次数**结算，计数在点击之前 → 只保守）；
     ★有界卡住等待★同一屏超 ``CONTINUE_STUCK_SEC`` 带原因收工（点击无效 / 星导石不足）；
     账本 ``wuchong/continue/{n}``；非 GAMEOVER 帧不计。
  6. **GUI 接线**：任务挂「五重续关几次」（input）→ 覆盖 ``WuchongContinueGuard.target_continues``；
     既有「五重打几次」仍写 ``WuchongGiveUp``（两写者共存、不同节点）。
  7. **纯编辑 + 无漂移**：``special_dungeon.json`` 五条承重短语零丢失；``scene.drift.check_all() == []``。

``--prove-red``：七处破坏，要求守卫各自变红（见 hooks_72.prove_red）。

★诚实边界★：本文件是**离线**部分。**真机 leg 未在本机运行**（无设备）—— 「制造一次战斗失败、
验证真的点了【续关】并继续」这一步**未验证**，如实标注，绝不转述式声称已验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import hooks_72 as H  # noqa: E402
from scene import drift  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    print("=" * 74)
    print("五重 GAMEOVER 续关（#72）：声明 / 真机帧 / 续关费≠恢复 / 点续关不点放弃 / 次数可配置 / GUI")
    print("=" * 74)

    print("\n== 1. 数据声明（判据与配置一致 + 读后动零偏移 + 叶子型）==")
    check("两个公共节点在场、box_index=2 → Click target:true 零死偏移",
          H.probe_gameover_continue_nodes_declared() is True)

    print("\n== 2. 真机帧回放（内嵌 #38 帧逐条 OCR）==")
    check("GAMEOVER 帧点【续关】框中心 (506,1061)；反例都不命中",
          H.probe_gameover_continue_frame() is True)

    print("\n== 3. 续关费 ≠ 体力恢复（D6：两屏互不误命中）==")
    check("GAMEOVER 帧体力节点 miss、体力弹窗帧续关 miss、星导石 y 在 ROI 外",
          H.probe_gameover_not_stamina() is True)

    print("\n== 3b. GAMEOVER 短语唯一真源（scene ↔ side_impl ↔ common 三角）==")
    check("scene.wuchong 短语 == side_impl.GAMEOVER_TITLE/PROMPT，且 common 叶包含它们",
          H.probe_wuchong_continue_phrases_single_source() is True)

    print("\n== 4. 五重点续关、不再点放弃（数据/流水线同步 + 上限闸）==")
    check("continue_refs()/FLOW_EXCEPTIONS/流程链/无放弃/StopTask/无固定坐标",
          H.probe_wuchong_continues_on_gameover() is True)

    print("\n== 5. 续关次数可配置 + 有界卡住（驱动真实识别器）==")
    check("target=2 第 3 个收工点 2（cap 优先）；target=0 不限；target=1 第 2 个收工；"
          "卡住超 CONTINUE_STUCK_SEC 带原因收工；账本 wuchong/continue",
          H.probe_wuchong_continue_count_configurable() is True)

    print("\n== 6. GUI 选项「五重续关几次」接线 ==")
    check("任务挂载 + input + override 落到 WuchongContinueGuard.target_continues；打几次仍写 GiveUp",
          H.probe_wuchong_continue_option_wired() is True)

    print("\n== 7. 纯编辑 + 无漂移 ==")
    check("special_dungeon.json 五条承重短语零丢失", H.probe_wuchong_continue_declared() is True)
    drift_msgs = drift.check_all(repo_root=REPO_ROOT)
    check("scene.drift.check_all() == []", drift_msgs == [], f"{drift_msgs[:2]}")

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    if "--prove-red" in sys.argv[1:]:
        sys.exit(0 if H.prove_red() else 1)
    sys.exit(main())
