# -*- coding: utf-8 -*-
"""离线单测：#60 迷宫道具确认框 + #64 归位认模态框（挂点/真机帧/prove-red 一体）。

不需要游戏 / 设备（判据全在**产品 pipeline JSON + 内嵌真机帧 OCR + 归位有序表**上）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_maze_item_confirm.py

覆盖：

  1. **#60 数据声明**：``farm.json::FarmItemConfirm`` = And[标题, 【是】]（box_index=1）、
     ``Click target:true``（点【是】框中心、零死偏移）；顺序排在 FarmFight/FarmScroll 之前；
  2. **#60 真机帧回放**：``阿尔戈罗盘`` / ``阿戈尔罗盘`` 两版标题都命中且点到 (522,823)；
     纯迷宫页不命中；
  3. **#60/#64 两处一致**：farm.json 判据 == live_harness.MAZE_ITEM_PROMPT；
  4. **#64 归位认弹框**：弹框帧首命中 = maze_item_confirm、只点【是】框中心、不抢主城/账号/标题；
     读不到【是】只等待（不盲点）；
  5. **#64 未知模态框带原因降级**：unknown 模态框帧被判为「疑似模态框」且 ensure_main_city
     有带原因的降级分支（不静默停手）；
  6. **无漂移 + #9 三条既有路径守卫仍绿**；hooks_60/hooks_64 的 prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_60.py`` / ``hooks_64.py``。
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

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from scene import drift  # noqa: E402

import hooks_60  # noqa: E402
import hooks_64  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> None:
    print("=" * 74)
    print("离线单测：#60 迷宫道具确认框 + #64 归位认模态框")
    print("=" * 74)

    print("\n== 1. #60 数据声明：And[标题,【是】] + box_index=1 + 零偏移中心点击 ==")
    farm = hooks_60.load_farm()
    check("maze-item-confirm-data-declared", hooks_60.probe_item_confirm_data_declared() is True,
          f"{hooks_60.pipeline_failures(farm)[:2]}")

    print("\n== 2. #60 顺序：先于 FarmFight / FarmScroll / FarmScrollUp ==")
    check("maze-item-confirm-before-fight-and-scroll",
          hooks_60.probe_item_confirm_before_fight_and_scroll() is True,
          f"{hooks_60.order_failures(farm)[:2]}")

    print("\n== 3. #60 真机帧回放：两版标题都命中、点 (522,823)；纯迷宫页不命中 ==")
    check("maze-item-confirm-real-frame", hooks_60.probe_item_confirm_real_frame() is True,
          f"{hooks_60.frame_failures(farm)[:2]}")

    print("\n== 4. #60/#64 两处落地判据逐字一致 ==")
    check("maze-item-confirm-both-landings-agree",
          hooks_60.probe_item_confirm_both_landings_agree() is True,
          f"{hooks_60.both_landings_failures(farm)[:2]}")

    print("\n== 5. #64 归位认弹框：首命中 maze_item_confirm、点【是】框中心、不抢别的页 ==")
    check("return-home-maze-item-confirm", hooks_64.probe_return_home_maze_item_confirm() is True,
          f"{hooks_64.maze_item_confirm_failures()[:2]}")

    print("\n== 6. #64 已知模态框读后动：读不到【是】只等待（不盲点） ==")
    check("return-home-known-modal-read-then-act",
          hooks_64.probe_return_home_known_modal_read_then_act() is True,
          f"{hooks_64.read_then_act_failures()[:2]}")

    print("\n== 7. #64 未知模态框：带原因降级（不静默停手） ==")
    check("return-home-unknown-modal-visible-degradation",
          hooks_64.probe_return_home_unknown_modal_visible_degradation() is True,
          f"{hooks_64.unknown_modal_failures()[:2]}")

    print("\n== 8. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [], f"{tsu.run_guards()[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")

    print("\n== 9. prove-red：hooks_60 / hooks_64 各自成立 ==")
    import contextlib
    import io

    buf60 = io.StringIO()
    with contextlib.redirect_stdout(buf60):
        ok60 = hooks_60.prove_red()
    buf64 = io.StringIO()
    with contextlib.redirect_stdout(buf64):
        ok64 = hooks_64.prove_red()
    check("hooks_60.prove_red() 成立（数据声明/顺序/box_index/变体 各自变红）", ok60 is True)
    check("hooks_64.prove_red() 成立（删规则/丢模态判据/抹降级分支 各自变红）", ok64 is True)

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
