# -*- coding: utf-8 -*-
"""真机验收（★#26 扭蛋/抽卡★）：跑到任务**自己结束**，并把 agent 的进度线打出来。

与 ``tools/run_pipeline.py`` 的区别：那个是「跑固定秒数后 post_stop」（给不自结束的任务用）；
抽卡任务现在有显式出口（抽满 N 发 → StopTask），所以这里**等它自然结束**，
用 ``live_harness.wait_job_bounded`` 做上界，超时才强制停。

用法::

    python tools/run_gacha_live.py --address 127.0.0.1:16448 --times 2
    python tools/run_gacha_live.py --address 127.0.0.1:16448 --times 1 --entry GachaEntry

前置条件：游戏已经停在**某一个扭蛋池的池子页**（底部导航「扭蛋」高亮，中间是池子，
底部有「1次抽取 / 10连抽取」）。本工具不做导航。

退出码：0 = 任务自然结束（succeeded/failed 都算跑完，看 status）；1 = 超时被强制停。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "agent"))

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

import live_harness as ca  # noqa: E402
from portable_paths import find_adb  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="#26 扭蛋（抽卡）真机验收：抽 N 发后自然结束")
    parser.add_argument("--entry", default="GachaEntry")
    parser.add_argument("--times", type=int, default=2, help="抽几发（总数，含第一发）")
    parser.add_argument("--adb", default=find_adb())
    parser.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现")
    parser.add_argument("--timeout", type=float, default=300.0, help="上界秒数（超时强制停）")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    project = Path(args.project).resolve() if args.project else PROJECT
    ca.apply_global_options(project)

    ctrl = ca.connect_device(
        args.adb, args.address, require=True, expect=ca.expected_identity()
    )
    print(f"[gacha] 设备已连接：{args.address}（connected={ctrl.connected}）", flush=True)

    res = Resource()
    print("resource load:", res.post_bundle(str(project / "assets" / "resource")).wait().succeeded)
    ca.register_pipeline_customs(res)

    tasker = Tasker()
    print("bind:", tasker.bind(res, ctrl))

    override = {
        "GachaCount": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "gacha_count",
                    "custom_recognition_param": {"times": int(args.times), "ocr_entry": "OcrTask"},
                },
            }
        }
    }

    started = time.monotonic()
    job = tasker.post_task(args.entry, override)
    print(f"[gacha] 开跑：entry={args.entry} times={args.times}（等它自己结束，上界 {args.timeout:.0f}s）", flush=True)
    status = ca.wait_job_bounded(tasker, job, timeout=float(args.timeout), label="gacha")
    elapsed = time.monotonic() - started
    print(f"[gacha] 结束：status={status} 用时={elapsed:.1f}s", flush=True)

    detail = job.get()
    print(f"[gacha] detail={detail}", flush=True)

    ok = str(status) not in ("timeout", "stopped")
    print(f"[gacha] 自然结束 = {ok}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
