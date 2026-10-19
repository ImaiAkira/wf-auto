# -*- coding: utf-8 -*-
"""真机验证：幻想连战「按套数收工」——目标 1 套，证明跑完整套后会 StopTask 收工。

为什么这样跑
------------
本项目的自定义识别/动作由 AgentServer 注册（正常由 MFAAvalonia 拉起子进程）。
为了在没有 MFAAvalonia 的情况下做真机验证，这里直接把 phantom_impl 的类注册到
进程内 Resource 上 —— phantom_impl 刻意不导入 maa.agent，所以 Resource() 可正常创建。

本脚本用【真实 pipeline + 真实点击】跑 PhantomEntry（设备地址由 --address / WF_LIVE_ADDRESS 给出）：
  · pipeline_override 注入 target_sets=N（等价于界面选项「刷几套=N」）；
  · 使用独立账本文件（跑前清空），不污染正式 progress.json；
  · 实时轨迹：捕获出口节点 PhantomDone / PhantomGiveUp 是否命中、动作名、raw_detail；
  · 一旦账本出现收工标记 phantom/run/completed 即判定【已正常收工】→ 截图；
  · 跑完整套（第 15 关入账）会单独截一张 phantom_set1_done 作为「整套完成」证据；
  · 收尾导航回主城（绝不按返回键 KeyEvent 4）。

用法:
    python tools/run_phantom_live.py --address <host:port> --target 1
    python tools/run_phantom_live.py --smoke 120      # 只跑 120s 看节点轨迹
    python tools/run_phantom_live.py --target 2       # 目标 2 套
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
import phantom_impl as ph  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"
# #25/#40：不再写死设备地址。地址只有一个来源：--address / WF_LIVE_ADDRESS / 身份发现
# （ca.connect_device(address=None) 按账号身份发现；ca.ADDRESS 读同一环境变量）。
LEDGER_FILE = ca.WORK_DIR / "phantom_live_progress.json"

RUN_DONE_KEY = ph.RUN_DONE_KEY          # phantom/run/completed
SCENE = ph.SCENE                        # phantom
MAX_STAGES = ph.MAX_STAGES              # 15
# 出口节点：命中即为「任务要结束了」，分别代表正常收工 / 兜底收工。
EXIT_NODES = ("PhantomDone", "PhantomGiveUp", "PhantomLevelRequired", "PhantomStall")


def target_override(target: int) -> dict:
    """等价于界面选项「刷几套 = target」注入的 override。"""
    return {
        "PhantomDone": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "phantom_done",
                    "custom_recognition_param": {"ocr_entry": "OcrTask", "target_sets": target},
                },
            }
        },
        "PhantomGiveUp": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "phantom_giveup",
                    "custom_recognition_param": {
                        "ocr_entry": "OcrTask",
                        "max_task_sec": 7200,
                        "unknown_limit": 120,
                        "no_progress_sec": 900,
                        "target_sets": target,
                    },
                },
            }
        },
    }


def _session_desc() -> str:
    """从同进程的 phantom_impl._SESSION 读取「当前第几套 / 第几关 / 画面」。"""
    try:
        s = ph._SESSION
        return (
            f"set={s.get('cur_set')} stage={s.get('cur_stage')} "
            f"done_sets={s.get('completed_sets')} state={s.get('last_state')}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"<session读取失败 {exc}>"


def _ledger_sets(keys) -> dict:
    import re

    sets: dict[int, list[int]] = {}
    for k in keys:
        m = re.search(rf"/set/(\d+)/stage/(\d+)$", k)
        if m:
            sets.setdefault(int(m.group(1)), []).append(int(m.group(2)))
    return {s: sorted(st) for s, st in sets.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    ap.add_argument("--target", type=int, default=1)
    ap.add_argument("--smoke", type=float, default=0.0, help="只跑 N 秒看轨迹，0=跑到自收工")
    ap.add_argument("--max-minutes", type=float, default=90.0, help="整轮超时（分钟）")
    ap.add_argument("--shot-every", type=float, default=90.0, help="过程截图间隔（秒）")
    ap.add_argument(
        "--keep-ledger",
        action="store_true",
        help="保留下一次启动前的账本（用于验证「中断后重开接着打」的恢复路径）",
    )
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
    print("title watcher:", watcher.enabled, flush=True)

    # ★独立账本 + 跑前清空 phantom 账本★
    #   --keep-ledger 时保留上一次的账本（模拟「掉线后重开」：没有收工标记 → 应接着打）。
    if LEDGER_FILE.exists() and not a.keep_ledger:
        LEDGER_FILE.unlink()
    ledger.set_file(LEDGER_FILE)
    print(
        f"ledger file ({'kept' if a.keep_ledger else 'cleared'}): {LEDGER_FILE}",
        flush=True,
    )

    override = target_override(a.target)
    print(f"== 启动 PhantomEntry，目标 {a.target} 套 ==", flush=True)
    job = tasker.post_task("PhantomEntry", override)
    tid = job.job_id

    start = time.time()
    seen_set_done = {}          # 套号 -> 是否已报「该套 15 关完成」
    exit_hits: dict[str, str] = {}   # 出口节点名 -> raw_detail 文本（一旦命中就固定）
    marker_seen = False
    last_trace = 0.0
    last_ledger = None
    prev_nodes = 0

    try:
        while True:
            time.sleep(2.0)

            # --- 实时节点轨迹：抓出口节点命中 ---
            try:
                detail = tasker.get_task_detail(tid)
                nodes = list(detail.nodes) if detail is not None else []
                for nd in nodes[prev_nodes:]:
                    name = getattr(nd, "name", "?")
                    reco = nd.recognition
                    hit = bool(getattr(reco, "hit", False)) if reco is not None else False
                    raw = getattr(reco, "raw_detail", None) if reco is not None else None
                    if name in EXIT_NODES and hit and name not in exit_hits:
                        aname = ""
                        if nd.action is not None:
                            aname = getattr(nd.action, "action", "") or ""
                        exit_hits[name] = f"hit=True action={aname} raw_detail={raw}"
                        print(f"[EXIT-HIT] node={name} action={aname} raw_detail={raw}", flush=True)
                        ca.screenshot(f"phantom_exit_{name}")
                prev_nodes = len(nodes)
            except Exception as exc:  # noqa: BLE001
                print(f"[trace] 节点读取异常: {exc}", flush=True)

            # --- 账本轮询 ---
            keys = ledger.all_keys()
            if keys != last_ledger:
                last_ledger = keys
                print(f"[ledger] {keys}", flush=True)

            sets = _ledger_sets(keys)
            # 完整跑完一整套：某套已记到第 15 关
            for s, stages in sets.items():
                if MAX_STAGES in stages and not seen_set_done.get(s):
                    seen_set_done[s] = True
                    print(f"[EVENT] 第 {s} 套 {MAX_STAGES} 关已完成（phantom/set/{s}/stage/{MAX_STAGES} 入账）", flush=True)
                    ca.screenshot(f"phantom_set{s}_done")
                    print(f"[EVENT] 截图 clr_phantom_set{s}_done.png", flush=True)

            # 收工标记
            if RUN_DONE_KEY in keys and not marker_seen:
                marker_seen = True
                print(f"[EVENT] 收工标记已写入：{RUN_DONE_KEY}", flush=True)
                ca.screenshot("phantom_run_completed")
                print("[EVENT] 截图 clr_phantom_run_completed.png", flush=True)

            if job.done:
                print("[EVENT] 任务自然结束（job.done）", flush=True)
                break

            now = time.time()
            if a.smoke and (now - start) > a.smoke:
                print(f"[smoke] 到达 {a.smoke}s，停止", flush=True)
                break
            if (now - start) > a.max_minutes * 60:
                print(f"[EVENT] 整轮超时 {a.max_minutes} 分钟，停止", flush=True)
                break
            # 过程证据：每 shot-every 秒截一张，文件名带 套/关/画面
            if now - last_trace > a.shot_every:
                last_trace = now
                sess = _session_desc().replace(" ", "_")
                label = f"phantom_trace_{int(now - start)}s_{sess}"
                ca.screenshot(label)
                print(f"[trace] 截图 clr_{label}.png  session[{_session_desc()}]", flush=True)

        # 收尾：补读全部节点，确认出口
        try:
            detail = tasker.get_task_detail(tid)
            nodes = list(detail.nodes) if detail is not None else []
            for nd in nodes[prev_nodes:]:
                name = getattr(nd, "name", "?")
                reco = nd.recognition
                hit = bool(getattr(reco, "hit", False)) if reco is not None else False
                raw = getattr(reco, "raw_detail", None) if reco is not None else None
                if name in EXIT_NODES and hit and name not in exit_hits:
                    aname = getattr(nd.action, "action", "") if nd.action is not None else ""
                    exit_hits[name] = f"hit=True action={aname} raw_detail={raw}"
                    print(f"[EXIT-HIT] (final) node={name} action={aname} raw_detail={raw}", flush=True)
            tail = [getattr(n, "name", "?") for n in nodes[-25:]]
            print("[nodes-tail]", tail, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("[trace] 收尾节点读取异常:", exc, flush=True)
    finally:
        try:
            tasker.post_stop().wait()
        except Exception as exc:  # noqa: BLE001
            print("post_stop 异常:", exc, flush=True)
        try:
            print("== 收尾：导航回主城 ==", flush=True)
            ca.ensure_main_city(watcher)
        except Exception as exc:  # noqa: BLE001
            print("回主城异常:", exc, flush=True)

    # ------------------------------------------------------------------ 汇总
    keys = ledger.all_keys()
    sets = _ledger_sets(keys)
    marker = RUN_DONE_KEY in keys
    done_node = "PhantomDone" in exit_hits
    giveup_node = "PhantomGiveUp" in exit_hits
    full_sets = [s for s, st in sets.items() if MAX_STAGES in st]

    print("================= 汇总 =================", flush=True)
    print(f"用时: {time.time() - start:.0f}s", flush=True)
    print(f"账本全部 key ({len(keys)}): {keys}", flush=True)
    print(f"各套已完成关号: {sets}", flush=True)
    print(f"完整跑完的套: {full_sets}", flush=True)
    print(f"出口命中: {exit_hits}", flush=True)
    print(f"收工标记 {RUN_DONE_KEY}: {'存在' if marker else '不存在'}", flush=True)
    print(f"RESULT PhantomDone={done_node} PhantomGiveUp={giveup_node} completed_marker={marker} full_sets={full_sets}", flush=True)

    if done_node and marker and full_sets:
        print("PASS: 跑够目标套数 → PhantomDone 命中 → StopTask → 收工标记 phantom/run/completed 已写入", flush=True)
    elif a.smoke:
        print("SMOKE 结束（未跑到证明点）", flush=True)
    else:
        print("FAIL: 未观察到『PhantomDone + 收工标记』的完整收工证据", flush=True)


if __name__ == "__main__":
    main()
