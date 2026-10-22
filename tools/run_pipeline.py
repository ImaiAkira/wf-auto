"""运行 pipeline 任务指定秒数后停止（用于循环类任务的验证）。

用法:
    .venv\\Scripts\\python.exe tools\\run_pipeline.py [--entry AutoPush] [--seconds 60]

说明:
    像 AutoPush 这类自带 Wait 自循环的任务不会自然结束，本工具运行固定秒数后
    调用 post_stop 停止，并输出 debug/maa.log 末尾日志作为执行证据。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

import live_harness as ca
from portable_paths import find_adb  # 脱敏：不把本机 adb 路径烧进默认值

DEFAULT_ADB = find_adb()
# #25/#40：不再写死设备地址；地址由 --address / WF_LIVE_ADDRESS / 身份发现给出，
# 且必须经 ca.connect_device 登记。


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 pipeline 任务固定秒数后停止")
    parser.add_argument("--entry", default="AutoPush")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--adb", default=DEFAULT_ADB)
    parser.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    project = (
        Path(args.project).resolve()
        if args.project
        else Path(__file__).resolve().parent.parent
    )
    # #perf：启动入口收敛到 ca.apply_global_options（Toolkit.init_option + save_draw 默认关
    # + debug 产物上界）；与其它 run_*live* 同一条启动缝，避免本工具再单独长出一份。
    ca.apply_global_options(project)

    # #25/#40：唯一登记入口（构造 + 连接 + 同步 ADDRESS/_ctrl_ref），地址缺省按账号身份发现，
    # 并打印实际设备身份（日志首行）。#130：默认只记日志、**不校验型号**；显式设置
    # WF_LIVE_EXPECT_* 才严格比较。require=False 保持本工具既有语义：连接失败也
    # 继续，只打印结果。
    ctrl = ca.connect_device(args.adb, args.address, require=False, expect=ca.expected_identity())

    res = Resource()
    print("resource load:", res.post_bundle(str(project / "assets" / "resource")).wait().succeeded)
    print("nodes:", len(res.node_list))
    # #20：运行 pipeline 前先把其引用到的全部自定义识别/动作注册好（唯一注册源）。
    ca.register_pipeline_customs(res)

    print("device connect:", ctrl.connected)

    tasker = Tasker()
    print("bind:", tasker.bind(res, ctrl))

    job = tasker.post_task(args.entry)
    print(f"task started: {args.entry}, running {args.seconds}s ...", flush=True)
    try:
        time.sleep(args.seconds)
    finally:
        print("stopping:", tasker.post_stop().wait().succeeded)

    detail = job.get()
    print("detail:", detail)

    log_path = project / "debug" / "maa.log"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        print(f"---- {log_path} tail ----")
        for line in lines[-40:]:
            print(line)
    else:
        print("maa.log not found:", log_path)


if __name__ == "__main__":
    main()
