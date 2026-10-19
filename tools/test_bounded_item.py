# -*- coding: utf-8 -*-
"""离线单测：#62 单个「能导航进详情页、却配不出战斗」的成员必须【有界跳过】。

直接跑：
    .venv\\Scripts\\python.exe tools\\test_bounded_item.py

覆盖（不需要游戏、不需要 maa 运行时；真机帧 OCR 内嵌在 hooks_62）：
1. 缺陷帧被识别（难度 present + 配不出战斗 + 自己的详情页且未开打）；
2. 有界语义 + 离线复现（旧形态坏成员饿死后面全部 / 新形态明确跳过并跑完后 4 个）+ 指挥官接线；
3. special 兜底导航上限（有限、区间内）；
4. 纯编辑：``special_dungeon.json`` 五条承重短语零丢失 + #62 声明注释在场。
"""

from __future__ import annotations

import sys
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_62  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def test_detected() -> None:
    print("\n== 1. 真机缺陷帧被识别（自己的详情页、配不出战斗、尚未开打） ==")
    check("special-unfightable-detected", hooks_62.probe_special_unfightable_detected() is True)


def test_bounded() -> None:
    print("\n== 2. 有界语义 + 离线复现 + 指挥官接线 ==")
    check("special-unfightable-bounded", hooks_62.probe_special_unfightable_bounded() is True)


def test_undetermined_bounded() -> None:
    print("\n== 2b. 协同 #39/#41：undetermined 有界重试后再处置 ==")
    check("special-undetermined-bounded", hooks_62.probe_special_undetermined_bounded() is True)


def test_nav_backstop() -> None:
    print("\n== 3. special 兜底导航上限（有限、区间内） ==")
    check("special-nav-deadline-backstop",
          hooks_62.probe_special_nav_deadline_backstop() is True)


def test_declared() -> None:
    print("\n== 4. 纯编辑：承重短语 + #62 声明注释 ==")
    check("special-unfightable-declared",
          hooks_62.probe_special_unfightable_declared() is True)


def test_prove_red() -> None:
    print("\n== 5. prove-red：去掉上限 / 摘掉接线 / 删掉声明 → 守卫变红 ==")
    check("hooks_62.prove_red() 成立", hooks_62.prove_red() is True)


def main() -> None:
    print("=" * 70)
    print("离线单测：#62 单个「能导航进详情页、却配不出战斗」的成员有界跳过")
    print("=" * 70)
    test_detected()
    test_bounded()
    test_undetermined_bounded()
    test_nav_backstop()
    test_declared()
    test_prove_red()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
