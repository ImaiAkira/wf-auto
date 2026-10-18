# -*- coding: utf-8 -*-
"""坐标空间真源：1080P 原始帧 ↔ 720x1280 MaaFramework 识别空间（#99）。

★★三层「谁是谁」★★

1. **原图 / native** —— 设备截图的真实像素。当前设备跑 **1080x1920**
   （运维实测 720P 会乱码，所以**不要**把设备切回 720P，见 `docs/spec/runner-delivery.md` §3）。
   属于这一层的：`adb screencap` 出来的帧、`tools/frames/*.png`、以及
   **`tools/ocr_image.py` 打印的 OCR box** —— 该工具
   （`tools/ocr_image.py:59`）显式 `set_screenshot_use_raw_size(True)`，**不缩放**，
   所以它吐出来的 `box` 就是原图像素，**不是**识别空间。
2. **基准空间 / base** —— 固定 **720x1280**。MaaFramework 识别前把截图缩到「短边 720」，
   于是 pipeline 的 `roi` / `target`、模板裁片、以及 runner 里 OCR 出来的 `box` 与点击坐标，
   全都在这一层。`assets/resource/pipeline/*.json` 里写的数字**一律**是这一层。
3. **换算** —— 1080 → 720 是 **÷1.5**（1080/720 = 1920/1280 = 1.5）。
   native → base 用 :func:`to_base` / :func:`box_to_base`；base → native 用
   :func:`to_native` / :func:`box_to_native`。**别在别处手写 `/1.5`。**

★★为什么必须有一个真源★★

仓里已经因为「坐标没标空间」踩过两次：

* `tools/contract_hooks/hooks_86.py` 曾把 **1080 原图**的 OCR box 当成 720 用过 ——
  那批 `今天剩余次数` 的 box `[381, 922, 319, 42]` 至今是原图像素；
  因为判据只比对文本才没炸（详见该文件的体例更正段）。
* `scene/team.py` 的 `TEAM_SET_ROW_Y = 30` 是 **B 类编辑器页（角色 → 队伍编成）** 的
  SET 圆点行 y；**A 类战前编队页** 的 SET 条在 y≈457。同一个「SET 行」在两页不同 y，
  拿错就是点空 —— 坐标除了空间，还必须带**页面语境**（#91 / 决策 D10）。

所以：写坐标必须标明空间；跨空间换算只走本模块。

★★环境变量★★

* `WF_NATIVE_W` / `WF_NATIVE_H` 覆盖**原图**尺寸，默认 `1080` / `1920`。
  B（`127.0.0.1:16448`）在 2026-10-17 那晚先后被观察到 720x1280 与 1080x1920，
  分辨率变过（换实例/改过），所以原图尺寸不能写死成不可改的常量。
* **base 不可覆盖**：720x1280 由 MaaFramework 的缩放策略决定，改了必错。
* env 在**导入时**读取；要换尺寸得重新 `importlib.reload(scene.pixels)`
  （离线工具/测试里够用，真机 runner 请提前设好环境变量）。

票面旧称：`to720` / `assert_720_box` / `assert_720_xy`（#99 正文用的名字）在本模块里
分别是 :func:`to_base` / :func:`assert_base_box` / :func:`assert_base_xy` 的别名。
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence

# ---------------------------------------------------------------------------
# 常量：基准空间（不可覆盖）+ 原图（可被 env 覆盖）
# ---------------------------------------------------------------------------

#: 基准空间宽（MaaFramework 识别/点击空间，**不可覆盖**）。
BASE_W = 720

#: 基准空间高（同上）。
BASE_H = 1280

_DEFAULT_NATIVE_W = 1080
_DEFAULT_NATIVE_H = 1920
_ENV_W = "WF_NATIVE_W"
_ENV_H = "WF_NATIVE_H"


def _read_native_size() -> tuple[int, int]:
    """读 `WF_NATIVE_W` / `WF_NATIVE_H`（缺省 1080/1920），非法就当场抛。"""
    values: list[int] = []
    for env_name, default in ((_ENV_W, _DEFAULT_NATIVE_W), (_ENV_H, _DEFAULT_NATIVE_H)):
        raw = os.environ.get(env_name)
        if raw is None or not raw.strip():
            values.append(default)
            continue
        try:
            values.append(int(raw.strip()))
        except ValueError as exc:
            raise ValueError(
                f"{env_name}={raw!r} 不是整数像素：它要填的是**原图**尺寸（如 {default}），不是别的"
            ) from exc
    w, h = values
    if w < BASE_W or h < BASE_H:
        raise ValueError(
            f"原图尺寸 {w}x{h} 比基准空间 {BASE_W}x{BASE_H} 还小 —— {_ENV_W}/{_ENV_H} 填的是"
            "**原图像素**，别把 720x1280 的基准空间填进去"
        )
    return w, h


#: 原图宽（设备真实像素，默认 1080，可被 `WF_NATIVE_W` 覆盖）。
NATIVE_W, NATIVE_H = _read_native_size()


def native_size() -> tuple[int, int]:
    """原图尺寸 `(宽, 高)`；默认 `(1080, 1920)`，可被 env 覆盖（见模块 docstring）。"""
    return NATIVE_W, NATIVE_H


def base_size() -> tuple[int, int]:
    """基准空间尺寸 `(宽, 高)` = `(720, 1280)`；由框架决定，不可覆盖。"""
    return BASE_W, BASE_H


# ---------------------------------------------------------------------------
# 换算
# ---------------------------------------------------------------------------

def _factors() -> tuple[float, float]:
    """`(横向系数, 纵向系数)`；两者必须一致，否则像素无法等比换算。"""
    sx = NATIVE_W / BASE_W
    sy = NATIVE_H / BASE_H
    if abs(sx - sy) > 0.01:
        raise ValueError(
            f"原图 {NATIVE_W}x{NATIVE_H} 与基准 {BASE_W}x{BASE_H} 长宽比不同"
            f"（横向 ×{sx:.4f} / 纵向 ×{sy:.4f}）—— 像素坐标没法等比换算，先确认分辨率"
        )
    return sx, sy


def scale_factor() -> float:
    """native/base 的缩放系数（**默认 1.5**；长宽比不一致直接 `ValueError`）。

    1080x1920 对 720x1280 两个方向都是 1.5，所以「÷1.5」这句口决成立；
    写成函数是为了让 B 那种 720/1080 变来变去的设备也能被工具脚本自动跟上。
    """
    return _factors()[0]


def to_base(x: float, y: float) -> tuple[float, float]:
    """原图像素点 `(x, y)` → 720 基准点（**÷1.5**）。"""
    _check_number(x, "x")
    _check_number(y, "y")
    sx, sy = _factors()
    return x / sx, y / sy


def to_native(x: float, y: float) -> tuple[float, float]:
    """720 基准点 `(x, y)` → 原图像素点（**×1.5**）。"""
    _check_number(x, "x")
    _check_number(y, "y")
    sx, sy = _factors()
    return x * sx, y * sy


def box_to_base(box: Sequence[float]) -> list[float]:
    """原图 `[x, y, w, h]` → 720 基准 `[x, y, w, h]`（四项都 ÷1.5）。

    返回浮点列表：OCR 框本来就有小数（÷1.5 常常除不尽），要不要取整由调用方决定
    （点屏幕前请自己 `int(round(...))`，别在这里丢精度）。
    """
    values = _box_values(box, "box")
    sx, sy = _factors()
    return [values[0] / sx, values[1] / sy, values[2] / sx, values[3] / sy]


def box_to_native(box: Sequence[float]) -> list[float]:
    """720 基准 `[x, y, w, h]` → 原图 `[x, y, w, h]`（四项都 ×1.5）。"""
    values = _box_values(box, "box")
    sx, sy = _factors()
    return [values[0] * sx, values[1] * sy, values[2] * sx, values[3] * sy]


# ---------------------------------------------------------------------------
# 越界守卫（写死 720 空间的代码在入口处先过一遍，错了就当场抛）
# ---------------------------------------------------------------------------

def _scale_hint() -> str:
    """错误消息里的「你可能把原图像素当 720 了」提示。"""
    try:
        factor = scale_factor()
    except ValueError:  # 长宽比都不对时，别再往消息里塞一个失败
        return ""
    return f"；如果这是原图像素，先 ÷{factor:g}（box_to_base）再写"


def _bad(name: str, detail: str) -> ValueError:
    return ValueError(f"{name} 越出 **720 空间**（{BASE_W}x{BASE_H}）：{detail}{_scale_hint()}")


def _check_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数字，收到 {type(value).__name__}: {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} 必须是有限数，收到 {value!r}")
    return number


def _box_values(box: Sequence[float], name: str) -> list[float]:
    if isinstance(box, (str, bytes)) or not isinstance(box, Sequence):
        raise ValueError(f"{name} 必须是 [x, y, w, h] 序列，收到 {type(box).__name__}: {box!r}")
    if len(box) != 4:
        raise ValueError(f"{name} 必须是 [x, y, w, h] 四元组，收到 {len(box)} 个值：{box!r}")
    return [_check_number(v, f"{name}[{i}]") for i, v in enumerate(box)]


def assert_base_box(box: Sequence[float], *, name: str = "box") -> Sequence[float]:
    """断言 ``box`` 是**合法的 720 基准** `[x, y, w, h]`，越界直接 `ValueError`。

    合法 = 四个值有限、非负，且整框落在 `720x1280` 内（``x + w <= 720``、``y + h <= 1280``）。
    返回入参原样，方便链式使用。消息里写清「720 空间」，并提示 ÷1.5 —— 因为最可能的错法
    就是把 1080 原图框直接当成了 720 框。
    """
    values = _box_values(box, name)
    x, y, w, h = values
    if min(values) < 0:
        raise _bad(name, f"含负值 {list(values)}（坐标不该为负；偏移量请用 target_offset）")
    # 先查「单个值有没有超出自己的轴」：这是把原图像素当 720 用时的典型形状，
    # 也比后面 x+w 的合报更好定位（例如 y=1383 会明确说 y，而不是 y+h=1425）。
    if x > BASE_W:
        raise _bad(name, f"x = {x:g} > {BASE_W}")
    if w > BASE_W:
        raise _bad(name, f"w = {w:g} > {BASE_W}")
    if y > BASE_H:
        raise _bad(name, f"y = {y:g} > {BASE_H}")
    if h > BASE_H:
        raise _bad(name, f"h = {h:g} > {BASE_H}")
    if x + w > BASE_W:
        raise _bad(name, f"x + w = {x:g} + {w:g} = {x + w:g} > {BASE_W}")
    if y + h > BASE_H:
        raise _bad(name, f"y + h = {y:g} + {h:g} = {y + h:g} > {BASE_H}")
    return box


def assert_base_xy(x: float, y: float, *, name: str = "点") -> tuple[float, float]:
    """断言 ``(x, y)`` 是**合法的 720 基准**点，越界直接 `ValueError`。

    合法 = 有限、非负、``x <= 720``、``y <= 1280``。返回 `(x, y)` 原样。
    """
    px = _check_number(x, f"{name}.x")
    py = _check_number(y, f"{name}.y")
    if px < 0 or py < 0:
        raise _bad(name, f"含负值 ({px:g}, {py:g})")
    if px > BASE_W:
        raise _bad(name, f"x = {px:g} > {BASE_W}")
    if py > BASE_H:
        raise _bad(name, f"y = {py:g} > {BASE_H}")
    return px, py


# 票面旧称（#99 正文）：to720 / assert_720_box / assert_720_xy。
to720 = to_base
assert_720_box = assert_base_box
assert_720_xy = assert_base_xy

__all__ = [
    "BASE_W",
    "BASE_H",
    "NATIVE_W",
    "NATIVE_H",
    "assert_720_box",
    "assert_720_xy",
    "assert_base_box",
    "assert_base_xy",
    "base_size",
    "box_to_base",
    "box_to_native",
    "native_size",
    "scale_factor",
    "to720",
    "to_base",
    "to_native",
]
