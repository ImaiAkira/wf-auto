# -*- coding: utf-8 -*-
"""#105 模板裁片生成器（**显式运行，产物提交**；只写 ``assets/resource/image/team/`` 下五个 PNG）。

    .venv\\Scripts\\python.exe tools\\gen_templates_105.py           # 生成 / 覆盖
    .venv\\Scripts\\python.exe tools\\gen_templates_105.py --check   # 只核对，不改盘（CI 用）

★为什么必须有一个生成器★（本仓 RK4：模板是二进制资产，diff 看不见）——
模板的**裁片口径**必须可重现、可复核：源帧 → 720 基准空间（LANCZOS）→ 裁 ``window``。
``hooks_105`` 的 ``team-battle-tpl-pixels`` 会用**同一口径**重裁一遍并逐像素比对，
所以生成器与守卫任何一方漂了都会当场红。

★口径★（与 ``hooks_102`` / 调研 §5.2 第一步同一手法）
* 源帧非 720x1280 的（``abyss_ex_team_page_A_team.png`` 是 1080x1920 原图）→ **LANCZOS**
  下采样到 ``scene.pixels.BASE_W x BASE_H``（= 720x1280，MaaFramework 的识别空间）；
* 已经是 720x1280 的帧不缩放（缩放一次就多一次插值误差）；
* 裁片一律 ``RGB``（既有模板全是 RGB：``auto/switch_label.png`` / ``wuchong/row_wuwang.png`` …）。

★只裁「状态无关」的部分★（调研 §4.2 第 2 步）
* ``set_selected``：只裁选中槽的 ``SET`` 三字母，**不含数字**（N 是内容，1..12 都会出现）；
* ``party_label``：只裁 ``Party`` 五字母，不含队号（1..6）与字母名（A..H）；
* ``power_label``：只裁 ``战力`` 二字，数值走 OCR（141 / 8,876 / 12,205 每帧在变）；
* ``auto_continue`` / ``challenge_btn``：整词裁（``挑战`` 不含箭头 —— 箭头的 y 在两族页面
  之间差 16px，裁进去会把跨帧最差正例压掉 0.03）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from scene import pixels  # noqa: E402
from scene import team_templates as TT  # noqa: E402


def frame_720(path: Path) -> Image.Image:
    """读一帧并归一到 **720x1280 基准空间**（非 720 原图走 LANCZOS，见模块 docstring）。"""
    img = Image.open(path).convert("RGB")
    if img.size != (pixels.BASE_W, pixels.BASE_H):
        img = img.resize((pixels.BASE_W, pixels.BASE_H), Image.LANCZOS)
    return img


def crop_of(spec: TT.TeamTemplateSpec) -> Image.Image:
    """按 :attr:`TeamTemplateSpec.window` 从**裁剪源帧**裁出模板（720 空间）。"""
    x, y, w, h = spec.window
    return frame_720(ROOT / spec.source_frame).crop((x, y, x + w, y + h))


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    rc = 0
    for spec in TT.TEAM_TEMPLATES.values():
        dst = ROOT / spec.template_rel
        crop = crop_of(spec)
        if check_only:
            if not dst.is_file():
                print(f"[MISSING] {spec.template}（{spec.key}）—— 跑一次本工具生成")
                rc = 1
                continue
            cur = Image.open(dst).convert("RGB")
            same = cur.size == crop.size and cur.tobytes() == crop.tobytes()
            print(
                f"[{'OK' if same else 'DIFF'}] {spec.template} "
                f"{crop.size[0]}x{crop.size[1]}  源={spec.source_frame} window={list(spec.window)}"
            )
            rc = rc or (0 if same else 1)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dst)
        print(
            f"[WROTE] {spec.template} {crop.size[0]}x{crop.size[1]}  "
            f"源={spec.source_frame} window={list(spec.window)}"
        )
    return rc


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
