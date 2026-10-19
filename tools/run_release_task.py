"""用**发布包**真跑一个任务 —— V1「跑通一个任务」的最后一步。

走的是 **GUI 用的同一条缝**：`AgentClient` 按 `interface.json` 里的 `agent.child_exec` /
`child_args` **把 agent 起成独立子进程**，框架侧只做 Resource / Controller / Tasker。

为什么不能像 runner 那样在进程内注册自定义动作：`agent/my_action.py` 顶部
`from maa.agent.agent_server import AgentServer`，**import 它会把 native 库切成 MaaAgentServer**，
之后 `Resource()` / `AdbController()` 直接失败（`MaaAgentServer Not implement this API`）。
仓里 `agent/maa_util.py` 与 `tools/live_harness.py` 的注释都写明了这条。所以必须子进程。

它证明的：包里的 `resource/` + `agent/` + `python/` 在真设备上真的把游戏打成一次。
它不证明的：GUI 上的点选（那一格由 `tools/accept_release.py --launch-gui` 证「能起来」）。

用法（项目根目录）：

    .venv\\Scripts\\python.exe tools\\run_release_task.py ^
        --package "%TEMP%\\wf-accept-xxxx" --task WuchongEntry --address 127.0.0.1:16384 --timeout 900
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEV_TOOLS = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", required=True, type=Path, help="解压后的发布包根目录")
    ap.add_argument("--task", default="WuchongEntry", help="interface.json 里的 task entry")
    ap.add_argument("--address", default=None, help="设备地址；不给就走地址发现")
    ap.add_argument("--override", default=None, help="pipeline_override 的 JSON 字符串")
    ap.add_argument("--override-file", type=Path, default=None,
                    help="pipeline_override 的 JSON 文件（**推荐**：免掉 shell 引号被吃的问题）")
    ap.add_argument("--timeout", type=float, default=900.0, help="任务最长等待秒数")
    ap.add_argument("--dry-run", action="store_true", help="只起好 resource/controller/agent，不发任务")
    args = ap.parse_args()

    pkg = args.package.resolve()
    # ★必须在 os.chdir(pkg) 之前把相对路径钉成绝对路径★，否则 override 文件会相对包根去解析。
    if args.override_file:
        args.override_file = args.override_file.resolve()
    for need in ("resource", "agent", "python"):
        if not (pkg / need).is_dir():
            raise SystemExit(f"{pkg} 下没有 {need}/ —— 这不像发布包")

    sys.path.insert(1, str(DEV_TOOLS))
    import live_harness as ca  # noqa: E402
    from maa.agent_client import AgentClient  # noqa: E402
    from maa.resource import Resource  # noqa: E402
    from maa.tasker import Tasker  # noqa: E402
    from portable_paths import find_adb  # noqa: E402

    # ---- 从包里的 interface.json 读 agent 的启动方式（不硬编码）----
    import jsonc  # noqa: PLC0415

    iface = jsonc.load((pkg / "interface.json").open(encoding="utf-8-sig"))
    child_exec = iface["agent"]["child_exec"].replace("{PROJECT_DIR}", str(pkg))
    child_args = [a.replace("{PROJECT_DIR}", str(pkg)) for a in iface["agent"].get("child_args", [])]
    exe = Path(child_exec).resolve()
    if not str(exe).lower().startswith(str(pkg).lower()):
        raise SystemExit(f"child_exec 没指向包内：{exe}")
    if not exe.is_file():
        raise SystemExit(f"child_exec 不存在：{exe}")
    identifier = " ".join([f'"{exe}"'] + [f'"{a}"' for a in child_args])
    print(f"[pkg] {pkg}")
    print(f"[pkg] agent 启动命令 = {identifier}", flush=True)

    # ---- 设备 ----
    adb = getattr(ca, "ADB", None) or find_adb()
    address = args.address or os.environ.get("WF_LIVE_ADDRESS")
    if not address:
        address = ca.resolve_address(adb, ca.expected_identity())
    os.environ["WF_LIVE_ADDRESS"] = address
    print(f"[dev] 连接 {address} …", flush=True)
    ctrl = ca.connect_device(adb, address)
    ca.log_device_identity(ca.read_identity(adb, address))

    # ---- 资源（必须早于任何 agent 相关动作）----
    res = Resource()
    ok = res.post_bundle(str(pkg / "resource")).wait().succeeded
    print(f"[res] post_bundle -> {ok}", flush=True)
    if not ok:
        raise SystemExit("resource 加载失败")

    # ---- agent 子进程：GUI 走的就是这条路 ----
    # 协议（`agent/main.py` 的 usage 写明）：**先建 client 拿到 identifier，再自己把
    # `main.py <identifier>` 拉起来，最后 connect()**。identifier 不是命令行（传命令行
    # 会让 `MaaAgentClientCreateV2` 抛 C++ 异常 0xe06d7363），它是连接令牌。
    # cwd 设成包根，让 main.py 的 `Toolkit.init_option("./")` 找到配置。
    os.chdir(pkg)
    client = AgentClient()
    ident = client.identifier
    cmd = [str(exe), *child_args, ident]
    print(f"[agent] identifier = {ident}", flush=True)
    print(f"[agent] spawn = {cmd}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(pkg))
    print(f"[agent] 子进程 pid={proc.pid}", flush=True)

    print(f"[agent] bind(resource) -> {client.bind(res)}", flush=True)
    print("[agent] connect() …", flush=True)
    if not client.connect():
        proc.kill()
        raise SystemExit("AgentClient.connect() 失败 —— agent 子进程没起来")
    print(f"[agent] connected={client.connected}  "
          f"recognitions={len(client.custom_recognition_list)}  "
          f"actions={len(client.custom_action_list)}", flush=True)
    if not client.custom_action_list:
        proc.kill()
        raise SystemExit("agent 起来了但一个自定义动作都没注册 —— 不继续")

    tasker = Tasker()
    print(f"[task] bind -> {tasker.bind(res, ctrl)}", flush=True)

    if args.dry_run:
        print("[dry] 不发任务（resource + controller + agent 均已就绪）", flush=True)
        client.disconnect()
        return 0

    op = None
    if args.override_file:
        op = json.loads(args.override_file.read_text(encoding="utf-8"))
        print(f"[task] override 来自 {args.override_file}", flush=True)
    elif args.override:
        op = json.loads(args.override)
    t0 = time.time()
    job = tasker.post_task(args.task, op)
    print(f"[task] post_task({args.task}) 已提交，最多等 {args.timeout:.0f}s", flush=True)
    result = ca.wait_job_bounded(tasker, job, timeout=args.timeout, label=args.task)
    print(f"[task] 结果 = {result}（用时 {time.time() - t0:.0f}s）", flush=True)
    client.disconnect()
    return 0 if result in ("succeeded", "success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
