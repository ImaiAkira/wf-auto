"""把已有真机帧补成「720 空间侧车 + 分类结论」（#25 需要的两张帧）。

仓库约定（见 tools/frames/abyss_zhongshi_tabs.ocr.txt）：帧保留 1080×1920 原图，
侧车 `text<TAB>[x,y,w,h]` 的坐标是 **720 空间**（宽 720）。本脚本跑 MAA OCR（1080 空间）
后把框 ×2/3 落盘，并用深渊/五重的 classify 复核该帧判成什么。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
FRAMES = ROOT / "tools" / "frames"
RESULT_RE = re.compile(r"OCRResult\(box=\[(\d+), (\d+), (\d+), (\d+)\], score=[\d.]+, text='(.*)'\)")

sys.path.insert(0, str(ROOT / "agent"))
import abyss_impl  # noqa: E402

TARGETS = ["lord_mode_select", "lord_home_city"]


def ocr_1080(path: Path) -> list[tuple[str, list[int]]]:
    out = subprocess.run(
        [str(PY), str(ROOT / "tools" / "ocr_image.py"), str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    items = []
    for line in out.splitlines():
        m = RESULT_RE.search(line.strip())
        if not m:
            continue
        x, y, w, h = (int(m.group(i)) for i in range(1, 5))
        text = m.group(5)
        if text.strip():
            items.append((text, [x, y, w, h]))
    return items


def to_720(box: list[int]) -> list[int]:
    return [round(v * 2 / 3) for v in box]


for name in TARGETS:
    png = FRAMES / f"{name}.png"
    if not png.is_file():
        print(f"[SKIP] {png} 不存在")
        continue
    items = ocr_1080(png)
    side = FRAMES / f"{name}.ocr.txt"
    lines = [f"{t}\t[{', '.join(str(v) for v in to_720(b))}]" for t, b in items]
    side.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state, info = abyss_impl.classify([(t, to_720(b)) for t, b in items])
    print(f"{name}: items={len(items)}  sidecar={side.name}  classify={state}  {info}")
