"""对连接的设备做一次完整检查：连接 -> 截图 -> 跑指定 pipeline 节点 -> 输出识别结果。

用法（项目根目录执行）:
    .venv\\Scripts\\python.exe tools\\live_check.py [--entry OcrTask] [--launch com.leiting.wf]

产物:
    screenshots/live_<时间戳>.png        本次截图
    screenshots/draw_<reco_id>_<i>.png   识别可视化（若框架生成了 draw）
    live_report.txt                      UTF-8 文本报告
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

import live_harness as ca  # #40：设备地址的唯一真源（身份发现），不再写死任何端口
from portable_paths import find_adb  # 脱敏：不把本机 adb 路径烧进默认值

DEFAULT_ADB = find_adb()


def launch_app(adb: str, address: str, package: str) -> None:
    subprocess.run(
        [
            adb,
            "-s",
            address,
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        check=False,
        capture_output=True,
    )
    time.sleep(12)


def main() -> None:
    parser = argparse.ArgumentParser(description="设备端 pipeline 节点检查")
    parser.add_argument("--entry", default="OcrTask", help="要运行的 pipeline 节点，逗号分隔可跑多个")
    parser.add_argument("--adb", default=DEFAULT_ADB)
    parser.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    parser.add_argument("--launch", default=None, help="先启动的包名，如 com.leiting.wf")
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
    shots = project / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    report = project / "live_report.txt"

    lines: list[str] = []

    def log(*parts: object) -> None:
        text = " ".join(str(p) for p in parts)
        print(text)
        lines.append(text)

    def write_report() -> None:
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("report written:", report)

    if args.launch:
        log("launching app:", args.launch)
        launch_app(args.adb, address, args.launch)

    Toolkit.init_option(str(project))

    res = Resource()
    log("resource load:", res.post_bundle(str(project / "assets" / "resource")).wait().succeeded)

    ctrl = AdbController(args.adb, address)
    log("device connect:", ctrl.post_connection().wait().succeeded)

    cap = ctrl.post_screencap().wait()
    img = ctrl.cached_image
    log("screencap:", cap.succeeded, getattr(img, "shape", None))

    if img is not None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        live_png = shots / f"live_{stamp}.png"
        Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(live_png)
        log("screenshot saved:", live_png)

    tasker = Tasker()
    log("bind:", tasker.bind(res, ctrl))

    entries = [e.strip() for e in args.entry.split(",") if e.strip()]
    for entry in entries:
        job = tasker.post_task(entry)
        log(f"entry={entry} succeeded={job.wait().succeeded}")

        detail = job.get()
        if detail is None:
            continue
        for node in detail.nodes:
            reco = node.recognition
            hit = None if reco is None else reco.hit
            log(f"  node={node.name} completed={node.completed} hit={hit}")
            if reco is None:
                continue
            log(f"    best={reco.best_result!r}")
            for item in (reco.all_results or [])[:30]:
                log(f"      {item}")
            for i, draw in enumerate(reco.draw_images or []):
                draw_png = shots / f"draw_{reco.reco_id}_{i}.png"
                Image.fromarray(np.ascontiguousarray(draw[:, :, ::-1])).save(draw_png)
                log("    draw saved:", draw_png)

    write_report()


if __name__ == "__main__":
    main()
