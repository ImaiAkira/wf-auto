# -*- coding: utf-8 -*-
"""#102 模板裁片生成器（**显式运行，产物提交**；只写 ``assets/resource/image/`` 下四个 PNG）。

    .venv\\Scripts\\python.exe tools\\gen_templates_102.py           # 生成 / 覆盖
    .venv\\Scripts\\python.exe tools\\gen_templates_102.py --check   # 只核对，不改盘（CI 用）

★为什么必须有一个生成器★（本仓 RK4：模板是二进制资产，diff 看不见）——
模板的**裁片口径**必须可重现、可复核：源帧 → 720 基准空间（LANCZOS）→ 裁 ``window``。
``hooks_102`` 的 ``p0-template-pixels-from-evidence`` 会用**同一口径**重裁一遍并逐像素比对，
所以生成器与守卫任何一方漂了都会当场红。

★口径★（与 ``hooks_108._frame_720`` / 调研 §5.2 第一步同一手法）
* 源帧非 720x1280 的（``lord_bonus_dialog.png`` 是 1080x1920 原图）→ **LANCZOS** 下采样到
  ``scene.pixels.BASE_W x BASE_H``（= 720x1280，MaaFramework 的识别空间）；
* 已经是 720x1280 的帧（``stamina_insufficient_wuchong_a.png`` / ``ark62_detail_unpairable.png``）
  **不缩放**（缩放一次就多一次插值误差）；
* 裁片一律 ``RGB``（既有模板全是 RGB：``auto/switch_label.png`` / ``wuchong/row_wuwang.png`` …）。

★只裁「状态无关」的部分★（调研 §4.2 第 2 步）
* 星导石：只裁**物品图标**，不含 ``星导石 × 50`` 的文字、也不含 ``×50`` 数量（数量会变）；
* 是/否：裁**按钮底框 + 字**，不含弹窗正文；
* NEW：只裁**徽标本体**，不含所在行的底色（不同页面行底色不同）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from scene import pixels  # noqa: E402
from scene import templates as T  # noqa: E402


def frame_720(path: Path) -> Image.Image:
    """读一帧并归一到 **720x1280 基准空间**（非 720 原图走 LANCZOS，见模块 docstring 的口径）。"""
    img = Image.open(path).convert("RGB")
    if img.size != (pixels.BASE_W, pixels.BASE_H):
        img = img.resize((pixels.BASE_W, pixels.BASE_H), Image.LANCZOS)
    return img


def crop_of(spec: T.TemplateSpec) -> Image.Image:
    """按 :attr:`TemplateSpec.window` 从**正例帧**裁出模板（720 空间）。"""
    x, y, w, h = spec.window
    return frame_720(ROOT / spec.positive_frame).crop((x, y, x + w, y + h))


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    rc = 0
    for spec in T.TEMPLATES.values():
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
                f"{crop.size[0]}x{crop.size[1]}  源={spec.positive_frame} window={list(spec.window)}"
            )
            rc = rc or (0 if same else 1)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dst)
        print(
            f"[WROTE] {spec.template} {crop.size[0]}x{crop.size[1]}  "
            f"源={spec.positive_frame} window={list(spec.window)}"
        )
    return rc


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
