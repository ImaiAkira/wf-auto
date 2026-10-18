"""无头冒烟测试：验证资源（pipeline + OCR 模型）能加载，并对合成中文图执行 OCR 识别。

用法（在项目根目录执行）:
    .venv\\Scripts\\python.exe tools\\smoke_ocr.py

结果同时写入 smoke_report.txt（UTF-8），避免控制台编码问题。
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

TEST_TEXT = "世界弹射物语 测试"
REPORT = "smoke_report.txt"


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


def make_test_image() -> Image.Image:
    img = Image.new("RGB", (1280, 720), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Windows 目录从环境读；不写死 `盘符:\Windows\Fonts\...`（脱敏 B 类）。
    font_path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc")
    font = ImageFont.truetype(font_path, 64)
    draw.text((120, 300), TEST_TEXT, font=font, fill=(255, 255, 255))
    return img


def main() -> None:
    lines: list[str] = []

    def log(*parts: object) -> None:
        text = " ".join(str(p) for p in parts)
        print(text)
        lines.append(text)

    Toolkit.init_option("./")

    res = Resource()
    ok = res.post_bundle("assets/resource").wait().succeeded
    log("resource load:", ok)

    pil = make_test_image()
    img_bgr = np.ascontiguousarray(np.array(pil)[:, :, ::-1])

    ctrl = ImageController(img_bgr)
    ctrl.set_screenshot_use_raw_size(True)
    ctrl.post_connection().wait()

    tasker = Tasker()
    log("bind:", tasker.bind(res, ctrl))

    cases: list[tuple[str, dict]] = [
        ("OcrTask", {}),
        ("OcrTask", {"OcrTask": {"expected": "世界弹射"}}),
        ("OcrTask", {"OcrTask": {"expected": TEST_TEXT}}),
    ]
    for entry, override in cases:
        job = tasker.post_task(entry, override)
        ok = job.wait().succeeded
        log(f"== task {entry} override={override} succeeded={ok}")
        detail = job.get()
        if detail is None:
            continue
        for node in detail.nodes:
            reco = node.recognition
            hit = reco.hit if reco else None
            log(f"   node={node.name} completed={node.completed} hit={hit}")
            if reco is None:
                continue
            log(f"     best={reco.best_result!r}")
            for item in (reco.all_results or [])[:10]:
                log(f"       {item}")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log("report written:", REPORT)


if __name__ == "__main__":
    main()
