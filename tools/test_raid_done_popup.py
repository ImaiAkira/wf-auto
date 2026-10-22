# -*- coding: utf-8 -*-
"""离线单测：#67 领主战页面上的「讨伐完成」奖励弹窗（挂点/真机帧/prove-red 一体）。

不需要游戏 / 设备（判据全在**产品 pipeline JSON + 内嵌真机帧 OCR**上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_raid_done_popup.py

覆盖：

  1. **#67 数据声明**：``common.json::PubRewardDoneClose`` = And[标题,【关闭】]（box_index=1）、
     ``Click target:true``（点【关闭】框中心、零死偏移）；
  2. **#67 领主战枢纽可达**：``special_dungeon.json::SpecialEntry.next`` 含
     ``[JumpBack]PubRewardDoneClose``，且排在 ``SpecialStallRecover`` 之前；
  3. **#67 真机帧回放**：真实帧（讨伐完成 + 关闭）命中且点到【关闭】框中心 (359,976)；
     领主战列表页 / 只有标题 / 只有按钮 都不命中；
  4. **#67 与战阵之宴链共用一份判据**：``raid.json::RaidPopupClose`` 是与门薄包装，
     没有第二份 ``^关闭$``；
  5. **无漂移 + #9 三条既有路径守卫仍绿**；
  6. **prove-red**：``hooks_raid_done_popup.prove_red()`` 成立（摘引用/死点/box_index/去标题/第二份拷贝 各自变红）。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_raid_done_popup.py``。
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

import hooks_raid_done_popup as h  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> None:
    print("=" * 74)
    print("离线单测：#67 领主战「讨伐完成」奖励弹窗")
    print("=" * 74)

    print("\n== 1. 数据声明：And[标题,【关闭】] + box_index=1 + 零偏移中心点击 ==")
    common = h.load_common()
    check("raid-done-popup-data-declared", h.probe_raid_done_popup_data_declared() is True,
          f"{h.pipeline_failures(common)[:2]}")

    print("\n== 2. 领主战枢纽可达（且先于卡死看门狗） ==")
    check("raid-done-popup-reachable-from-hub", h.probe_raid_done_popup_reachable_from_hub() is True,
          f"{h.reachability_failures(h.load_sd(), common)[:2]}")

    print("\n== 3. 真机帧回放：命中并点【关闭】框中心 (359,976)；三个反例都不命中 ==")
    check("raid-done-popup-real-frame", h.probe_raid_done_popup_real_frame() is True,
          f"{h.frame_failures(common)[:2]}")

    print("\n== 4. 与战阵之宴链共用一份判据（无第二份 ^关闭$） ==")
    check("raid-done-popup-shared-with-raid", h.probe_raid_done_popup_shared_with_raid() is True,
          f"{h.shared_failures(h.load_raid(), common)[:2]}")

    print("\n== 5. 声明注释 + 五条承重短语（纯编辑） ==")
    check("raid-done-popup-declared", h.probe_raid_done_popup_declared() is True,
          f"{h.declaration_failures()[:2]}")

    print("\n== 6. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    check("#9 守卫未改且仍绿：run_guards() == []",
          __import__("test_scene_unchanged").run_guards() == [])

    print("\n== 7. prove-red：hooks_raid_done_popup 成立 ==")
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = h.prove_red()
    check("hooks_raid_done_popup.prove_red() 成立（五处破坏各自变红）", ok is True)

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
