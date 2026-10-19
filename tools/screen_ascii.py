"""把截图渲染成终端字符画，用于无视觉环境下粗看界面布局。

用法（项目根目录执行）:
    .venv\\Scripts\\python.exe tools\\screen_ascii.py <截图路径> [--cols 72]

字符含义（近似）:
    空格/'.' = 深色背景      '#' = 明亮/白色(文字、图标)
    '*'/':'  = 灰白          'O' = 橙红(常见按钮色)
    'R'      = 红            'Y' = 黄
    'G'      = 绿            'B' = 蓝
    'P'      = 粉/紫         '?' = 其它

提示: 输出每行左侧是像素行号，按缩放比例可换算回截图坐标。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def classify(r: int, g: int, b: int) -> str:
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx < 50:
        return " "
    if mx < 100:
        return "."
    if mn > 190:
        return "#"
    sat = mx - mn
    if sat < 35:
        return ":" if mx < 160 else "*"
    if r > 150 and g < 80 and b < 80:
        return "R"
    if r > 150 and 60 <= g <= 170 and b < 110 and (r - g) > 40:
        return "O"
    if r > 180 and g > 160 and b < 130:
        return "Y"
    if g > r + 25 and g > b + 25:
        return "G"
    if b > r + 25 and b > g + 25:
        return "B"
    if r > 140 and b > 140 and g < 130:
        return "P"
    return "?"


def main() -> None:
    parser = argparse.ArgumentParser(description="截图转字符画")
    parser.add_argument("image", type=Path)
    parser.add_argument("--cols", type=int, default=72, help="输出宽度（字符数）")
    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"图片不存在: {args.image}")

    img = Image.open(args.image).convert("RGB")
    w, h = img.size
    cols = args.cols
    rows = max(1, round(cols * h / w * 0.5))
    small = img.resize((cols, rows), Image.Resampling.BILINEAR)
    arr = np.asarray(small)

    print(f"# {args.image} 原图 {w}x{h} -> 字符画 {cols}x{rows}")
    print(f"# 1 字符列 ≈ {w / cols:.1f}px, 1 字符行 ≈ {h / rows:.1f}px")
    ruler = "".join(str((i // 10) % 10) if i % 10 == 0 else " " for i in range(cols))
    print("    " + ruler)
    for y in range(rows):
        line = "".join(classify(int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])) for x in range(cols))
        print(f"{y:3d} " + line)


if __name__ == "__main__":
    main()
