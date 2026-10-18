# -*- coding: utf-8 -*-
"""#99 离线单测：`scene/pixels.py` 的坐标换算与越界守卫（纯函数，无设备、无 maa 运行时）。

    .venv\\Scripts\\python.exe tools\\test_pixels.py

覆盖票 #99 的四条要求：

1. **换算对**：1080P 原图 → 720 基准是 ÷1.5（`to_base` / `box_to_base`），反算回原图是 ×1.5；
2. **往返稳**：`to_base` → `to_native` 回到原点（误差 < 1e-9）；`box_to_base` → `box_to_native` 同理；
3. **中心不变**：box 缩放的几何性质 —— 换算后框的中心 = 原框中心的换算值；
   这正是「按 OCR 框中心点屏幕」能跨空间成立的前提；
4. **越界抛错**：`assert_base_box` / `assert_base_xy` 对超界值直接 `ValueError`，
   且消息里写清「720 空间」+ 提示 ÷1.5（`hooks_86` 那次把原图框当 720 用，就缺这一下）。

另外钉住 env 覆盖（`WF_NATIVE_W` / `WF_NATIVE_H`）：484 在 720/1080 之间变过，
所以默认 1080x1920 必须能被覆盖，且**非法值当场抛**，不许悄悄算错。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scene import pixels as px  # noqa: E402

FAILS: list[str] = []

#: `tools/ocr_image.py` 在 hooks_86 那次读到的**原图** box（1080 空间，÷1.5 后才是 720）。
NATIVE_TICKET_BOX = [381, 922, 319, 42]

#: 同比换算后的期望值（381/1.5=254, 922/1.5≈614.667, 319/1.5≈212.667, 42/1.5=28）。
EXPECTED_BASE_BOX = [254.0, 922 / 1.5, 319 / 1.5, 28.0]

EPS = 1e-9


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def close(a: float, b: float, eps: float = EPS) -> bool:
    return abs(float(a) - float(b)) <= eps


def close_box(a, b, eps: float = EPS) -> bool:
    return len(a) == len(b) and all(close(x, y, eps) for x, y in zip(a, b))


def raises(fn, *args, **kwargs) -> str | None:
    """跑一遍，返回 `ValueError` 的消息；没抛 → None；抛了别的类型 → 带前缀的消息。"""
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 -- 别的异常也算失败，但要让报错看得见
        return f"__WRONG_EXCEPTION__{type(exc).__name__}: {exc}"
    return None


# ---------------------------------------------------------------------------
# 1. 常量与系数
# ---------------------------------------------------------------------------
def test_constants() -> None:
    print("\n[1] 常量：base 固定 720x1280；native 默认 1080x1920、可被 env 覆盖")
    check("BASE_W / BASE_H = 720 / 1280", (px.BASE_W, px.BASE_H) == (720, 1280),
          f"实际 {(px.BASE_W, px.BASE_H)}")
    check("默认原图 1080x1920", (px.NATIVE_W, px.NATIVE_H) == (1080, 1920),
          f"实际 {(px.NATIVE_W, px.NATIVE_H)}（若环境里设了 WF_NATIVE_* 请先清掉）")
    check("scale_factor() = 1.5（1080/720 = 1920/1280）", close(px.scale_factor(), 1.5),
          f"实际 {px.scale_factor()}")
    check("native_size() / base_size() 与常量一致",
          px.native_size() == (px.NATIVE_W, px.NATIVE_H) and px.base_size() == (720, 1280))


# ---------------------------------------------------------------------------
# 2. 点换算 + 往返
# ---------------------------------------------------------------------------
def test_points() -> None:
    print("\n[2] 点换算：原图 → 720 是 ÷1.5，反算 ×1.5，往返回原点")
    cases = [
        ((0.0, 0.0), (0.0, 0.0)),
        ((1080.0, 1920.0), (720.0, 1280.0)),
        ((540.0, 960.0), (360.0, 640.0)),
        ((105.0, 1470.0), (70.0, 980.0)),
        ((1079.0, 1919.0), (1079 / 1.5, 1919 / 1.5)),
    ]
    ok = True
    for native, base in cases:
        got = px.to_base(*native)
        if not close_box(got, base):
            ok = False
            check(f"to_base{native} = {base}", False, f"实际 {got}")
    check("to_base 逐例正确（含 (105,1470) → (70,980) 这种 1080 秒变 720 的例子）", ok)

    back_ok = True
    for native in ((0.0, 0.0), (540.0, 960.0), (105.0, 1470.0), (1079.0, 1919.0), (1.0, 7.0)):
        got = px.to_native(*px.to_base(*native))
        if not close_box(got, native):
            back_ok = False
            check(f"to_base→to_native 往返 {native}", False, f"实际 {got}")
    check("to_base → to_native 往返回原点（误差 < 1e-9）", back_ok)
    check("to720 是 to_base 的别名（票面旧称）", px.to720 is px.to_base)


# ---------------------------------------------------------------------------
# 3. box 换算 + 中心不变
# ---------------------------------------------------------------------------
def test_boxes() -> None:
    print("\n[3] box 换算：÷1.5、中心不变、往返稳定")
    got = px.box_to_base(NATIVE_TICKET_BOX)
    check("hooks_86 那个原图 box [381,922,319,42] → 720 空间", close_box(got, EXPECTED_BASE_BOX),
          f"实际 {[round(v, 3) for v in got]}")

    # 中心不变：换算后框的中心 == 原框中心的换算值（点屏幕靠的就是这个性质）。
    ok = True
    for native in (NATIVE_TICKET_BOX, [0, 0, 720, 1280], [150, 1470, 330, 42], [53, 1259, 10, 10]):
        base = px.box_to_base(native)
        native_cx = native[0] + native[2] / 2.0
        native_cy = native[1] + native[3] / 2.0
        expect_cx, expect_cy = px.to_base(native_cx, native_cy)
        got_cx = base[0] + base[2] / 2.0
        got_cy = base[1] + base[3] / 2.0
        if not (close(got_cx, expect_cx) and close(got_cy, expect_cy)):
            ok = False
            check(f"box {native} 换算后中心不变", False,
                  f"中心 {got_cx:.3f},{got_cy:.3f} 应为 {expect_cx:.3f},{expect_cy:.3f}")
    check("box 换算后中心不变（4 例）", ok)

    ok = True
    for native in (NATIVE_TICKET_BOX, [0, 0, 720, 1280], [150, 1470, 330, 42]):
        back = px.box_to_native(px.box_to_base(native))
        if not close_box(back, native):
            ok = False
            check(f"box 往返 {native}", False, f"实际 {back}")
    check("box_to_base → box_to_native 往返回原值", ok)

    native = px.box_to_native([0, 1180, 720, 100])
    check("720 空间的底部导航框 [0,1180,720,100] → 原图 [0,1770,1080,150]",
          close_box(native, [0.0, 1770.0, 1080.0, 150.0]), f"实际 {native}")


# ---------------------------------------------------------------------------
# 4. 越界守卫（box）
# ---------------------------------------------------------------------------
def test_assert_base_box() -> None:
    print("\n[4] assert_base_box：合法的放过，越界的当场 ValueError 且说清「720 空间」")
    legal = [
        [0, 0, 720, 1280],
        [0, 1180, 720, 100],
        [150, 440, 570, 560],
        [26, 463, 671, 146],
        (0, 0, 0, 0),  # 空框（框架用来表示「没命中」）
    ]
    for box in legal:
        check(f"合法框 {list(box)} 不抛", raises(px.assert_base_box, box) is None)

    illegal = [
        ("1080 原图 y=1383 当 720", [381, 1383, 319, 42]),
        ("整框都是原图像素", [300, 1470, 900, 330]),
        ("框高写成整屏", [0, 1180, 720, 1280]),
        ("h 超 1280", [430, 0, 290, 1300]),
        ("x + w > 720", [700, 0, 40, 40]),
        ("负 x", [-10, 0, 40, 40]),
    ]
    for label, box in illegal:
        msg = raises(px.assert_base_box, box)
        ok = msg is not None and "720" in msg and "__WRONG_EXCEPTION__" not in msg
        check(f"越界框报错并点名 720 空间：{label} {box}", ok, f"{msg!r}")
        if msg is not None and "720" in msg:
            check(f"  报错里带 ÷1.5 的提示：{label}", "1.5" in msg or "box_to_base" in msg, msg)

    two = raises(px.assert_base_box, [1, 2, 3])
    check("非四元组 → ValueError", two is not None and "__WRONG_EXCEPTION__" not in two, f"{two!r}")
    check("非数字 → ValueError", raises(px.assert_base_box, ["a", 1, 2, 3]) is not None)
    check("bool 不当数字（True 是 int 的子类，必须挡住）",
          raises(px.assert_base_box, [True, 0, 1, 1]) is not None)
    check("NaN → ValueError", raises(px.assert_base_box, [float("nan"), 0, 1, 1]) is not None)
    check("字符串 → ValueError", raises(px.assert_base_box, "720") is not None)
    check("assert_720_box 是 assert_base_box 的别名", px.assert_720_box is px.assert_base_box)


# ---------------------------------------------------------------------------
# 5. 越界守卫（点）
# ---------------------------------------------------------------------------
def test_assert_base_xy() -> None:
    print("\n[5] assert_base_xy：点坐标守卫")
    for x, y in ((0, 0), (720, 1280), (358, 1198), (53, 1259), (720.0, 0.0)):
        check(f"合法点 ({x}, {y}) 不抛", raises(px.assert_base_xy, x, y) is None)

    bad = [
        ("x 超 720", (721, 0)),
        ("y 超 1280", (0, 1281)),
        ("负 x", (-1, 0)),
        ("1080 原图点当 720", (572, 1383)),
    ]
    for label, point in bad:
        msg = raises(px.assert_base_xy, *point)
        check(f"越界点报错并点名 720 空间：{label} {point}",
              msg is not None and "720" in msg and "__WRONG_EXCEPTION__" not in msg, f"{msg!r}")

    # 可检测性的边界要写进测试：1080 点里有一部分「恰好」落在 720 范围内，纯数值守卫抓不到。
    msg = raises(px.assert_base_xy, 538, 1270)
    check("(538,1270) 落在 720 范围内 → 守卫按设计放过（所以要靠 to_base，而不是靠范围猜）",
          msg is None, f"{msg!r}")
    check("assert_720_xy 是 assert_base_xy 的别名", px.assert_720_xy is px.assert_base_xy)


# ---------------------------------------------------------------------------
# 6. env 覆盖（484 曾在 720/1080 之间变过）
# ---------------------------------------------------------------------------
def test_env_override() -> None:
    print("\n[6] env 覆盖：WF_NATIVE_W/H 可改成 720x1280；非法值当场抛")
    saved = {k: os.environ.get(k) for k in (px._ENV_W, px._ENV_H)}
    try:
        os.environ[px._ENV_W] = "720"
        os.environ[px._ENV_H] = "1280"
        mod = importlib.reload(px)
        check("覆盖成 720x1280 后 scale_factor() = 1.0", close(mod.scale_factor(), 1.0),
              f"实际 {mod.scale_factor()}")
        check("覆盖成 720x1280 后 to_base 是恒等", close_box(mod.to_base(540, 960), (540.0, 960.0)),
              f"实际 {mod.to_base(540, 960)}")

        os.environ[px._ENV_W] = "1080"
        os.environ[px._ENV_H] = "1920"
        mod = importlib.reload(px)
        check("改回 1080x1920 后 scale_factor() = 1.5", close(mod.scale_factor(), 1.5),
              f"实际 {mod.scale_factor()}")

        os.environ[px._ENV_W] = "720x1280"
        check("非法 env（不是整数）→ 导入即 ValueError", raises(importlib.reload, px) is not None)

        os.environ[px._ENV_W] = "360"
        os.environ[px._ENV_H] = "640"
        check("原图比 base 还小 → 导入即 ValueError", raises(importlib.reload, px) is not None)

        # 1440x1920：横向 ×2.0 / 纵向 ×1.5，两个方向都对不上 → 只许抛，不许硬算。
        os.environ[px._ENV_W] = "1440"
        os.environ[px._ENV_H] = "1920"
        mod = importlib.reload(px)
        check("长宽比不一致 → scale_factor() 抛错（不硬算）", raises(mod.scale_factor) is not None,
              f"{raises(mod.scale_factor)!r}")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(px)
    check("恢复 env 后仍是默认 1080x1920 / ×1.5",
          (px.NATIVE_W, px.NATIVE_H) == (1080, 1920) and close(px.scale_factor(), 1.5),
          f"实际 {(px.NATIVE_W, px.NATIVE_H)} ×{px.scale_factor():g}")


# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 74)
    print("离线单测：#99 坐标空间真源（scene/pixels.py）—— 纯函数，无设备")
    print("=" * 74)
    test_constants()
    test_points()
    test_boxes()
    test_assert_base_box()
    test_assert_base_xy()
    test_env_override()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✓（换算 ÷1.5 / 往返 / 中心不变 / 越界抛错 / env 覆盖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
