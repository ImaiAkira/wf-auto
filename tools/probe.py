"""按步骤脚本探测游戏界面：OCR 读屏、按文本/坐标点击、逐步截图与报告。

用法（项目根目录执行）:
    .venv\\Scripts\\python.exe tools\\probe.py [--steps-file probe_steps.json]

步骤文件为 UTF-8 JSON（避免命令行中文参数编码问题）:
{
    "dry_run": false,
    "steps": [
        {"action": "ocr"},
        {"action": "click_text", "text": "关卡"},
        {"action": "sleep", "seconds": 3},
        {"action": "ocr"},
        {"action": "click_xy", "x": 100, "y": 200},
        {"action": "back"},
        {"action": "screenshot", "tag": "after"}
    ]
}

动作说明:
    ocr                截图并 OCR，记录全部文本+坐标（并保存识别可视化 draw 图）
    click_text         从上一次 OCR 结果中找匹配文本并点击中心; 可选 index/region
    click_xy           直接点击坐标
    back               发送 BACK 键
    sleep              等待
    screenshot         保存当前截图

产物:
    screenshots/probe_<步号>_*.png     各步骤截图或识别可视化
    probe_report.txt                   UTF-8 文本报告
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

import live_harness as ca  # #40：设备地址的唯一真源（身份发现），不再写死任何端口
from portable_paths import find_adb  # 脱敏：不把本机 adb 路径烧进默认值

DEFAULT_ADB = find_adb()


class Probe:
    def __init__(self, project: Path, adb: str, address: str, dry_run: bool) -> None:
        self.project = project
        self.adb = adb
        self.address = address
        self.dry_run = dry_run
        self.shots = project / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.lines: list[str] = []
        self.last_results: list[Any] = []
        self.step_no = 0

        Toolkit.init_option(str(project))

        self.res = Resource()
        self.log(
            "resource load:",
            self.res.post_bundle(str(project / "assets" / "resource")).wait().succeeded,
        )

        self.ctrl = AdbController(adb, address)
        self.log("device connect:", self.ctrl.post_connection().wait().succeeded)

        self.tasker = Tasker()
        self.log("bind:", self.tasker.bind(self.res, self.ctrl))

    def log(self, *parts: object) -> None:
        text = " ".join(str(p) for p in parts)
        print(text)
        self.lines.append(text)

    def save_screen(self, tag: str) -> None:
        self.ctrl.post_screencap().wait()
        img = self.ctrl.cached_image
        if img is None:
            self.log("  screencap failed")
            return
        path = self.shots / f"probe_{self.step_no:02d}_{tag}.png"
        Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(path)
        self.log("  screenshot:", path.name)

    def ocr(self) -> None:
        job = self.tasker.post_task("OcrTask")
        ok = job.wait().succeeded
        detail = job.get()
        results: list[Any] = []
        if detail is not None:
            for node in detail.nodes:
                reco = node.recognition
                if reco is None:
                    continue
                results = list(reco.all_results or [])
                for i, draw in enumerate(reco.draw_images or []):
                    draw_path = self.shots / f"probe_{self.step_no:02d}_draw_{i}.png"
                    Image.fromarray(np.ascontiguousarray(draw[:, :, ::-1])).save(draw_path)
                    self.log("  draw:", draw_path.name)
        self.last_results = results
        self.log("  ocr ok:", ok, "results:", len(results))
        for item in results[:60]:
            self.log(f"    {item}")

    def click_text(
        self,
        text: str,
        index: int = 0,
        region: Optional[list[int]] = None,
    ) -> None:
        pattern = re.compile(text)
        matches = [r for r in self.last_results if pattern.search(getattr(r, "text", "") or "")]
        if region:
            rx, ry, rw, rh = region
            matches = [
                m
                for m in matches
                if rx <= m.box[0] + m.box[2] / 2 <= rx + rw
                and ry <= m.box[1] + m.box[3] / 2 <= ry + rh
            ]
        if not matches:
            self.log(f"  click_text '{text}' NOT FOUND")
            return
        if index >= len(matches):
            self.log(f"  click_text '{text}' index {index} out of range ({len(matches)})")
            return
        m = matches[index]
        x = int(m.box[0] + m.box[2] / 2)
        y = int(m.box[1] + m.box[3] / 2)
        self.log(f"  click_text '{text}' -> '{m.text}' at ({x},{y}) score={m.score:.3f}")
        if self.dry_run:
            self.log("  dry_run: click skipped")
            return
        ok = self.ctrl.post_click(x, y).wait().succeeded
        self.log("  click ok:", ok)

    def click_xy(self, x: int, y: int) -> None:
        self.log(f"  click_xy ({x},{y})")
        if self.dry_run:
            self.log("  dry_run: click skipped")
            return
        ok = self.ctrl.post_click(int(x), int(y)).wait().succeeded
        self.log("  click ok:", ok)

    def swipe(self, begin: list[int], end: list[int], duration: int = 450) -> None:
        self.log(f"  swipe {begin[:2]} -> {end[:2]} ({duration}ms)")
        if self.dry_run:
            self.log("  dry_run: swipe skipped")
            return
        subprocess.run(
            [
                self.adb, "-s", self.address, "shell", "input", "swipe",
                str(int(begin[0])), str(int(begin[1])),
                str(int(end[0])), str(int(end[1])), str(int(duration)),
            ],
            check=False,
            capture_output=True,
        )

    def back(self) -> None:
        self.log("  back keyevent")
        if self.dry_run:
            self.log("  dry_run: back skipped")
            return
        subprocess.run(
            [self.adb, "-s", self.address, "shell", "input", "keyevent", "4"],
            check=False,
            capture_output=True,
        )

    def run(self, steps: list[dict[str, Any]]) -> None:
        for i, step in enumerate(steps, 1):
            self.step_no = i
            action = step.get("action", "")
            self.log(f"== step {i}: {action} {json.dumps(step, ensure_ascii=False)}")
            if action == "ocr":
                self.ocr()
            elif action == "click_text":
                self.click_text(step.get("text", ""), int(step.get("index", 0)), step.get("region"))
            elif action == "click_xy":
                self.click_xy(step.get("x", 0), step.get("y", 0))
            elif action == "swipe":
                self.swipe(step.get("begin", [360, 850]), step.get("end", [360, 700]), int(step.get("duration", 450)))
            elif action == "back":
                self.back()
            elif action == "sleep":
                seconds = float(step.get("seconds", 1))
                self.log(f"  sleep {seconds}s")
                time.sleep(seconds)
            elif action == "screenshot":
                self.save_screen(step.get("tag", "shot"))
            else:
                self.log("  unknown action")

    def write_report(self) -> None:
        path = self.project / "probe_report.txt"
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        print("report written:", path)


def parse_dsl(dsl: str) -> list[dict[str, Any]]:
    """把 `ocr;xy:100,200;sleep:2;ocr` 形式的步骤串解析为步骤列表（仅限 ASCII）。"""
    steps: list[dict[str, Any]] = []
    for raw in dsl.split(";"):
        token = raw.strip()
        if not token:
            continue
        name, _, arg = token.partition(":")
        if name == "ocr":
            steps.append({"action": "ocr"})
        elif name == "shot":
            steps.append({"action": "screenshot", "tag": arg or "shot"})
        elif name in ("xy", "tap"):
            x_str, y_str = arg.split(",")
            steps.append({"action": "click_xy", "x": int(x_str), "y": int(y_str)})
        elif name == "swipe":
            v = [int(t) for t in arg.split(",")]
            steps.append(
                {
                    "action": "swipe",
                    "begin": v[:2],
                    "end": v[2:4],
                    "duration": v[4] if len(v) > 4 else 450,
                }
            )
        elif name == "text":
            steps.append({"action": "click_text", "text": arg})
        elif name == "sleep":
            steps.append({"action": "sleep", "seconds": float(arg)})
        elif name == "back":
            steps.append({"action": "back"})
        else:
            raise SystemExit(f"unknown step token: {token}")
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description="按步骤探测游戏界面")
    parser.add_argument("--steps-file", default="probe_steps.json")
    parser.add_argument(
        "--steps",
        default=None,
        help="内联步骤串，如 'ocr;xy:100,200;sleep:2;ocr'（分号分隔，仅限 ASCII）",
    )
    parser.add_argument("--adb", default=DEFAULT_ADB)
    parser.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    project = (
        Path(args.project).resolve()
        if args.project
        else Path(__file__).resolve().parent.parent
    )
    # #40：地址缺省按账号身份发现（不再写死端口）。
    # #130：身份**照读并打进日志**，但默认（WF_LIVE_EXPECT_* 全 unset）**不校验型号**。
    address = args.address or ca.resolve_address(args.adb, ca.expected_identity())
    identity = ca.read_identity(args.adb, address)
    ca.log_device_identity(identity, ca.expected_identity())
    problem = ca.identity_mismatch(identity, ca.expected_identity())
    if problem:
        raise SystemExit(problem)
    if args.steps:
        spec = {"steps": parse_dsl(args.steps)}
    else:
        steps_file = Path(args.steps_file)
        if not steps_file.is_absolute():
            steps_file = project / steps_file
        spec = json.loads(steps_file.read_text(encoding="utf-8"))

    probe = Probe(project, args.adb, address, bool(spec.get("dry_run", False)))
    try:
        probe.run(spec.get("steps", []))
    finally:
        probe.write_report()


if __name__ == "__main__":
    main()
