# -*- coding: utf-8 -*-
"""真机最小验证：SpecialEntry「幻想清单」路由 + 单目标别名兼容。

设备地址不再写死：缺省按【账号身份】发现（#40）；也可用 --address / WF_LIVE_ADDRESS 指定。

背景
----
本账号 RANK 114 < 130，点「终始之战」会弹「需要130级」限制，进不了幻想连战，
所以本脚本能验证的是：路由链路（SpecialEntry/PhantomEntry → PhantomDispatch →
幻想状态机导航 → 130级 StopTask），**无法**验证真正的进关/开打。

用法：
    python tools\\run_phantom_merge_live.py --mode batch  --seconds 120
    python tools\\run_phantom_merge_live.py --mode single --seconds 120

收尾一律走屏幕按钮回主城（ensure_main_city），★绝不使用 KeyEvent 4★。
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
from maa.toolkit import Toolkit  # noqa: E402

import live_harness as ca  # noqa: E402
import progress as ledger  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"
# #40：不再写死 adb 路径 / 端口 —— 统一走 ca.ADB + 身份发现（唯一真源 live_harness）。
LEDGER_FILE = ca.WORK_DIR / "phantom_merge_live_progress.json"

TRACE_NODES = {
    "PhantomEntry", "SpecialEntry", "PhantomDispatch",
    "PhantomNavActivity", "PhantomNavZhongshi", "PhantomNavTab", "PhantomNavBanner",
    "PhantomHubEnter", "PhantomMainFight", "PhantomSoloChallenge",
    "PhantomLevelRequired", "PhantomLevelRequiredNative",
    "PhantomDone", "PhantomGiveUp", "PhantomStall",
    "SpecialBatchPlan", "SpecialBatchStop",
}


def batch_override(text: str) -> dict:
    return {
        "SpecialBatchPlan": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "special_batch_plan",
                    "custom_recognition_param": {"list": text},
                },
            }
        }
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["batch", "single"], default="batch")
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    a = ap.parse_args()

    # #40：先连接并打印实际设备身份（日志首行），地址缺省时按账号身份发现。
    # #130：默认（WF_LIVE_EXPECT_* 全 unset）只记日志、**不校验型号**；显式设置才严格比较。
    # #perf：启动入口收敛到 ca.apply_global_options —— Toolkit.init_option + save_draw 默认关
    # （要临时抓帧设 WF_SAVE_DRAW=1）+ debug 产物上界（见 live_harness 里那一段的实测数字）。
    ca.apply_global_options(PROJECT)
    ctrl = ca.connect_device(ca.ADB, a.address, expect=ca.expected_identity())

    res = Resource()
    print("resource load:", res.post_bundle(str(ASSETS)).wait().succeeded, flush=True)
    # ★进程内注册 pipeline 用到的全部自定义识别/动作（唯一注册源 live_harness，#20）★
    ca.register_pipeline_customs(res)

    tasker = Tasker()
    print("bind:", tasker.bind(res, ctrl), flush=True)
    watcher = ca.TitleWatcher(str(ASSETS))

    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()
    ledger.set_file(LEDGER_FILE)

    if a.mode == "batch":
        entry = "SpecialEntry"
        override = batch_override("幻想连战,-,1")
        print("== 批量清单：SpecialEntry + 清单『幻想连战,-,1』 ==", flush=True)
    else:
        entry = "PhantomEntry"
        override = {}
        print("== 单目标：PhantomEntry（别名） ==", flush=True)

    job = tasker.post_task(entry, override)
    tid = job.job_id
    start = time.time()
    seen: dict[str, str] = {}
    prev = 0
    try:
        while True:
            time.sleep(2.0)
            try:
                detail = tasker.get_task_detail(tid)
                nodes = list(detail.nodes) if detail is not None else []
                for nd in nodes[prev:]:
                    name = getattr(nd, "name", "?")
                    reco = nd.recognition
                    hit = bool(getattr(reco, "hit", False)) if reco is not None else False
                    aname = getattr(nd.action, "action", "") if nd.action is not None else ""
                    if name in TRACE_NODES and hit:
                        raw = getattr(reco, "raw_detail", None)
                        seen[name] = f"action={aname} raw={raw}"
                        print(f"[HIT] {name} {seen[name]}", flush=True)
                prev = len(nodes)
            except Exception as exc:  # noqa: BLE001
                print("[trace] err:", exc, flush=True)

            if job.done:
                print("[EVENT] 任务自然结束", flush=True)
                break
            if (time.time() - start) > a.seconds:
                print(f"[EVENT] 到达 {a.seconds}s，停止", flush=True)
                break
    finally:
        try:
            tasker.post_stop().wait()
        except Exception as exc:  # noqa: BLE001
            print("post_stop:", exc, flush=True)
        try:
            print("== 收尾：回主城（屏幕按钮，绝不用 KeyEvent 4） ==", flush=True)
            ca.ensure_main_city(watcher)
        except Exception as exc:  # noqa: BLE001
            print("回主城异常:", exc, flush=True)

    print("========== 汇总 ==========", flush=True)
    print("entry:", entry, "override:", override, flush=True)
    print("命中节点:", seen, flush=True)
    print("路由结论: PhantomDispatch",
          "命中" if "PhantomDispatch" in seen else "未命中！", flush=True)
    print("130级出口: PhantomLevelRequired",
          "命中（已 StopTask，验证 130 限制保持）" if "PhantomLevelRequired" in seen
          else ("Native 命中" if "PhantomLevelRequiredNative" in seen else "未命中"), flush=True)


if __name__ == "__main__":
    main()
