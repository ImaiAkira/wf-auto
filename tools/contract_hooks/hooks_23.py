# -*- coding: utf-8 -*-
"""#23：卡死看门狗不得把「规律循环」判成卡死的挂点（已点亮）。

seam：``agent/side_impl.py`` 的 ``StallRecoverRecognition``（custom_recognition
``stall_recover``）——「画面在动」判据。

背景（#13 第 3 次真机运行，设备实证）
------------------------------------
::

    15:54:07 SpecialStallRecover
    [stall_recover] 画面连续 187.1s 无变化（阈值 180.0s）→ 判定卡死

可那 187 秒里画面每 ~3 秒就在 主城 / 领主战列表 / 详情页 之间规律轮转。旧判据只看
**全帧平均绝对差**（阈值 3.0），真机采样帧的平均差只有 1.20~2.10（< 3.0）→ 判成冻结；
而同一批帧的**显著变化格子占比是 1.95%~3.44%**（主城界面里走动的小精灵 / 闪烁特效），
局部小动被整帧平均稀释掉了。真·冻结（同一帧对自身）平均差 0、占比 0 —— 本可区分。

修复：判据升级为「平均差 > diff_threshold **或** 显著变化格子占比 > motion_frac」。
真·冻结（占比恒 0）依旧命中，规律循环不再误判。

两个守卫（真相见 ``tools/test_stall_detector.py``，本文件只做挂点，避免分叉）
----------------------------------------------------------------------------
1. ``stall-cycle-not-stall``    —— 真机「规律循环」帧序列 → **不得**判卡死；
2. ``stall-frozen-still-stalls``—— 真·冻结（同一帧重复）→ **必须**判卡死。

★prove-red★（``python tools\\contract_hooks\\hooks_23.py``）：把判据退回旧形态
（只看平均差）→ 用例一变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def probe_cycle_not_stall() -> bool:
    """#23：真机「规律循环」帧序列（真机采样帧内嵌）→ 不得判卡死。"""
    import test_stall_detector as tsd  # noqa: PLC0415

    return tsd.case_cycle_not_stall()


def probe_frozen_still_stalls() -> bool:
    """#23：真·冻结（同一帧重复）→ 必须判卡死（真阳性路径不丢）。"""
    import test_stall_detector as tsd  # noqa: PLC0415

    return tsd.case_frozen_still_stalls()


HOOKS = [
    (
        "stall-cycle-not-stall",
        "#23",
        "卡死看门狗：真机「规律循环」帧序列不得判卡死（局部小动可见，旧平均差判据盲）",
        probe_cycle_not_stall,
    ),
    (
        "stall-frozen-still-stalls",
        "#23",
        "卡死看门狗：真·冻结（同一帧重复）必须判卡死（真阳性路径不变）",
        probe_frozen_still_stalls,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    import test_stall_detector as tsd  # noqa: PLC0415

    raise SystemExit(0 if tsd.prove_red() else 1)
