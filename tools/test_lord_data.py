# -*- coding: utf-8 -*-
"""离线单测：领主战类成员表 / 难度词表 / 逐成员可用难度（ticket #32）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_lord_data.py

覆盖 ticket #32 的验收标准，断言配置数据与**真机行扫**一致：

  1. 成员表按真机校正：领主战 17 / 降临讨伐 29（共 46），去掉了不存在的 ``石芯心六``；
  2. #21 回归：``艾基尔·嫉妒讨伐`` 与 ``诅咒弧魔艾基尔讨伐`` 两行都在（真机第 1 / 第 10 行）；
  3. ``DIFFICULTIES`` 含真机档位 ``地狱级``；
  4. 每个**实测**成员的可用难度集 == ``diff_summary.json``（内嵌于 hooks_32）；
  5. 真机事实：降临讨伐无一成员含 ``初级``；
  6. 每条修正处标注来源（帧 / 运行 / 产物）—— 源码里在场；
  7. 数据改动不破坏 drift / 校验：``scene.drift.check_all() == []``、``validate_config`` 通过；
  8. 挂点 #32 已点亮，且自带破坏实验（删成员 -> 变红）成立。

真机证据（2026-10-13）内嵌在 hooks_32（``sweep_lord_*.ocr.txt`` / ``sweep_joss_*.ocr.txt`` /
``sweep_result.json`` / ``diff_summary.json``）。本文件**只读**，绝不写盘。

注：``石芯心六`` 的证伪旁证在 ``detail_report.json``（``石芯心六`` nav=False / diff=[]）。
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

from scene import drift  # noqa: E402
from scene import options as opt  # noqa: E402
from scene.config import DIFFICULTIES, validate_config  # noqa: E402
from scene.lord_battle import JOSS, LORDS, LORD_BATTLE  # noqa: E402

import hooks_32  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_roster_counts_and_sets() -> None:
    print("\n== 1. 成员表按真机校正（领主战 17 / 降临讨伐 29 / 共 46） ==")
    check("派生成员数 = 46", len(LORD_BATTLE.members) == 46, f"got={len(LORD_BATTLE.members)}")
    check("领主战 = 17", len(LORDS) == 17, f"got={len(LORDS)}")
    check("降临讨伐 = 29", len(JOSS) == 29, f"got={len(JOSS)}")

    lords = {m.行名 for m in LORD_BATTLE.members if m.子族 == "领主战"}
    joss = {m.行名 for m in LORD_BATTLE.members if m.子族 == "降临讨伐"}
    check("领主战集合 == 真机行扫", lords == hooks_32.DEVICE_LORDS,
          f"多={sorted(lords - hooks_32.DEVICE_LORDS)} 缺={sorted(hooks_32.DEVICE_LORDS - lords)}")
    check("降临讨伐集合 == 真机行扫", joss == hooks_32.DEVICE_JOSS,
          f"多={sorted(joss - hooks_32.DEVICE_JOSS)} 缺={sorted(hooks_32.DEVICE_JOSS - joss)}")


def test_nonexistent_and_regression() -> None:
    print("\n== 2. 去掉真机不存在的成员；修 #21 回归（两行都在） ==")
    names = {m.行名 for m in LORD_BATTLE.members}
    for gone in hooks_32.NONEXISTENT_MEMBERS:
        check(f"真机不存在的 {gone!r} 已移除", gone not in names)
    for both in hooks_32.EKIEL_BOTH:
        check(f"#21 回归修正：{both!r} 在场", both in names)
    check("妖狐讨伐 已补回（真机第 5 行）", "妖狐讨伐" in names)


def test_difficulty_vocabulary() -> None:
    print("\n== 3. 难度词表含「地狱级」 ==")
    check("DIFFICULTIES 含 地狱级", "地狱级" in DIFFICULTIES, f"got={DIFFICULTIES}")


def test_per_member_difficulties() -> None:
    print("\n== 4. 逐成员可用难度 == 真机实测（diff_summary.json） ==")
    wrong = []
    for m in LORD_BATTLE.members:
        want = hooks_32.DEVICE_DIFFICULTIES.get(m.行名)
        if want is None:
            continue
        if frozenset(m.支持难度集) != want:
            wrong.append((m.行名, sorted(m.支持难度集), sorted(want)))
    check(f"实测成员（{len(hooks_32.DEVICE_DIFFICULTIES)} 个）难度集全部一致", wrong == [], f"不符={wrong}")

    check("未测定成员也非空（校验要求）", all(m.支持难度集 for m in LORD_BATTLE.members))
    no_rookie = [m.行名 for m in LORD_BATTLE.members if m.子族 == "降临讨伐" and "初级" in m.支持难度集]
    check("降临讨伐无一成员含「初级」（真机事实）", no_rookie == [], f"含初级={no_rookie}")
    check("「初级」只在 维·索拉斯讨伐 上声明",
          {m.行名 for m in LORD_BATTLE.members if "初级" in m.支持难度集} == {"维·索拉斯讨伐"})


def test_provenance_recorded() -> None:
    print("\n== 5. 每条修正处记录了来源（帧 / 运行 / 产物） ==")
    src = (REPO_ROOT / "scene" / "lord_battle.py").read_text(encoding="utf-8")
    for s in hooks_32.EVIDENCE_STRINGS:
        check(f"来源串在场：{s}", s in src)


def test_drift_and_validation() -> None:
    print("\n== 6. 数据改动不破坏 drift / 校验 ==")
    check("validate_config 通过", validate_config(LORD_BATTLE) == [], f"errors={validate_config(LORD_BATTLE)}")
    check("scene.drift.check_all() == []", drift.check_all() == [], f"drift={drift.check_all()}")
    case_names = [c["name"] for c in opt.derive_target_options(LORD_BATTLE)]
    check("派生 GUI 选项名 == 成员行名（N -> N）",
          case_names == [m.行名 for m in LORD_BATTLE.members])


def test_hook_and_prove_red() -> None:
    print("\n== 7. 挂点 #32 已点亮；破坏实验（删成员）成立 ==")
    check("probe_lord_roster_and_difficulties() 返回 True",
          hooks_32.probe_lord_roster_and_difficulties() is True)
    check("prove_red() 成立：删掉「妖狐讨伐」-> 守卫变红", hooks_32.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：领主战类成员表 / 难度词表 / 逐成员难度（scene.lord_battle / hooks_32）")
    print("=" * 70)
    test_roster_counts_and_sets()
    test_nonexistent_and_regression()
    test_difficulty_vocabulary()
    test_per_member_difficulties()
    test_provenance_recorded()
    test_drift_and_validation()
    test_hook_and_prove_red()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
