"""模板裁剪小工具：从截图中框选区域，按 MAA 目标分辨率缩放后保存为模板图。

用法:
    .venv\\Scripts\\python.exe tools\\crop_template.py <screenshot.png> --name 模板名

操作:
    鼠标拖动框选 -> Enter / S 保存，R 重选，Esc 取消

说明:
    MaaFramework 会把设备截图缩放为短边 720（例如 1920x1080 -> 1280x720）再做识别，
    因此模板图必须从同样缩放后的截图上裁剪，否则匹配会漂移。
    本工具会自动把输入截图缩放到短边 720 再让你裁剪。
"""

from __future__ import annotations

import argparse
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk


def load_scaled(path: Path, short_side: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    scale = short_side / min(img.size)
    if scale != 1:
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="从截图中裁剪 MAA 模板图")
    parser.add_argument("image", type=Path, help="输入截图路径")
    parser.add_argument("--name", default=None, help="模板名（默认 crop_<时间戳>）")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("assets/resource/image"),
        help="输出目录（默认 assets/resource/image）",
    )
    parser.add_argument("--short-side", type=int, default=720, help="目标短边（默认 720）")
    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"图片不存在: {args.image}")

    img = load_scaled(args.image, args.short_side)
    name = args.name or f"crop_{int(time.time())}"
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.png"

    root = tk.Tk()
    root.title(f"裁剪模板 -> {out_path}  ({img.width}x{img.height})")
    canvas = tk.Canvas(root, width=img.width, height=img.height, cursor="cross")
    canvas.pack()
    photo = ImageTk.PhotoImage(img)
    canvas.create_image(0, 0, anchor="nw", image=photo)

    rect_id: list[int | None] = [None]
    start = {"x": 0, "y": 0}
    selection: dict[str, tuple[int, int, int, int] | None] = {"box": None}

    def on_press(event: tk.Event) -> None:
        start["x"], start["y"] = event.x, event.y
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="red", width=2
        )

    def on_drag(event: tk.Event) -> None:
        if rect_id[0] is not None:
            canvas.coords(rect_id[0], start["x"], start["y"], event.x, event.y)

    def on_release(event: tk.Event) -> None:
        x1, y1 = min(start["x"], event.x), min(start["y"], event.y)
        x2, y2 = max(start["x"], event.x), max(start["y"], event.y)
        if x2 - x1 < 3 or y2 - y1 < 3:
            return
        selection["box"] = (x1, y1, x2, y2)
        print(f"选中区域: {selection['box']}")

    def save(event: tk.Event | None = None) -> None:
        box = selection["box"]
        if box is None:
            print("还没有框选区域，请先拖动框选")
            return
        crop = img.crop(box)
        crop.save(out_path)
        print(f"已保存: {out_path} ({crop.width}x{crop.height})")
        root.destroy()

    def reset(event: tk.Event | None = None) -> None:
        selection["box"] = None
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
            rect_id[0] = None

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", save)
    root.bind("s", save)
    root.bind("S", save)
    root.bind("r", reset)
    root.bind("R", reset)
    root.bind("<Escape>", lambda e: root.destroy())

    print(f"缩放后尺寸: {img.width}x{img.height}，输出: {out_path}")
    print("操作: 拖动框选 -> Enter 保存 / R 重选 / Esc 退出")
    root.mainloop()


if __name__ == "__main__":
    main()
