# -*- coding: utf-8 -*-
"""离线单测（#68）：体力不足 → 星岛石恢复 —— 五重 / 战阵之宴 / 领主战族 / 深渊共用一份。

不需要游戏 / 设备（判据全在内嵌的真机帧 OCR + pipeline 结构上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_stamina.py
    .venv\\Scripts\\python.exe tools\\test_stamina.py --prove-red

覆盖 #68 的验收：

  1. **数据声明**：六个公共节点 ``PubStamina*`` 在场，判据与 ``scene.stamina`` 一致，
     动作是 ``And + box_index=1`` → ``Click target:true``（点识别框中心、零死偏移）、叶子型。
  2. **接线**：五重 / 战阵之宴 / 领主战族 / 深渊四个消耗体力的场景都携带恢复链引用；
     五重经 ``FLOW_EXCEPTIONS`` 注入每个流程节点；引用节点确有定义。
  3. **策略**：只用星岛石（``RECOVER_WITH_STONE``）；无第二份免费道具路径；容忍 星导石/星岛石；【取消】绝不点。
  4. **真机帧回放**（内嵌旧线帧逐条 OCR）：弹窗帧点星导石行框中心、确认帧点 OK 框中心；反例都不命中。
  5. **纯编辑 + 无漂移**：special_dungeon.json 五条承重短语零丢失；``scene.drift.check_all()`` 为空。

``--prove-red``：四处破坏，要求守卫各自变红（见 hooks_stamina.prove_red）。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import hooks_stamina as H  # noqa: E402
from scene import drift  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    print("=" * 74)
    print("体力不足 → 星岛石恢复（#68）：声明 / 接线 / 策略 / 真机帧 / 纯编辑")
    print("=" * 74)

    print("\n== 1. 数据声明（判据与配置一致 + 读后动零偏移 + 叶子型）==")
    check("六个公共节点在场、判据一致、零死偏移", H.probe_stamina_nodes_declared() is True)

    print("\n== 2. 接线（每个消耗体力的场景都带恢复链）==")
    check("五重/战阵之宴/领主战族/深渊都接线", H.probe_stamina_wired_every_consumer() is True)

    print("\n== 3. 策略（只用星岛石；无第二份道具路径；取消不点）==")
    check("只用星岛石、零死偏移、容忍变体", H.probe_stamina_stone_only_policy() is True)

    print("\n== 4. 真机帧回放（内嵌旧线帧逐条 OCR）==")
    check("弹窗帧点星导石行框中心 / 确认帧点 OK 框中心；反例不命中",
          H.probe_stamina_real_frame() is True)

    print("\n== 5. 纯编辑 + 无漂移 ==")
    check("special_dungeon.json 五条承重短语零丢失", H.probe_stamina_declared() is True)
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
