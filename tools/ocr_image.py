"""对本地截图运行 OCR（离线，走 MaaFramework 的 OcrTask，不消耗视觉 API 额度）。

用法:
    .venv\\Scripts\\python.exe tools\\ocr_image.py <截图路径> [--entry OcrTask]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit


class ImageController(CustomController):
    def __init__(self, img_bgr: np.ndarray):
        super().__init__()
        self.img = img_bgr

    def connect(self) -> bool:
        return True

    def request_uuid(self) -> str:
        return "0"

    def screencap(self) -> np.ndarray:
        return self.img


def main() -> None:
    parser = argparse.ArgumentParser(description="对本地截图运行 OCR")
    parser.add_argument("image", type=Path)
    parser.add_argument("--entry", default="OcrTask")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    project = (
        Path(args.project).resolve()
        if args.project
        else Path(__file__).resolve().parent.parent
    )
    if not args.image.is_file():
        raise SystemExit(f"图片不存在: {args.image}")

    Toolkit.init_option(str(project))

    res = Resource()
    print("resource load:", res.post_bundle(str(project / "assets" / "resource")).wait().succeeded)

    pil = Image.open(args.image).convert("RGB")
    img_bgr = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
    ctrl = ImageController(img_bgr)
    ctrl.set_screenshot_use_raw_size(True)
    ctrl.post_connection().wait()

    tasker = Tasker()
    tasker.bind(res, ctrl)
    job = tasker.post_task(args.entry)
    ok = job.wait().succeeded
    print(f"entry={args.entry} succeeded={ok}")

    detail = job.get()
    if detail is None:
        return
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        print("hit:", reco.hit)
        for item in reco.all_results or []:
            print(f"  {item}")


if __name__ == "__main__":
    main()
