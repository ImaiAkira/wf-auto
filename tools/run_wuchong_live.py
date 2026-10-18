# -*- coding: utf-8 -*-
"""五重决战（wuchong）真机验证 runner —— 分步、可控、先读后动。

设计（#56 真机 lane）
---------------------
正常由 MFAAvalonia 拉起 AgentServer 注册自定义识别/动作。本 runner 直接把
``wuchong_impl``（以及 live_harness 里的 runner 侧等价实现）注册到**进程内 Resource**，
因此在没有 MFAAvalonia 的情况下也能对真机执行**本仓库真正的** pipeline 节点。

把一次性长跑拆成**可单独调用的子命令**，每次只做一件事、每步都先截图+OCR 再决定：

  recon            只读：抓屏 + OCR + classify（wuchong_impl.classify）+ 开关橙占比 + 身份
                   (主角色/RANK)。**不发任何输入**。
  state            只读：打印当前 classify 结果 + 保存一帧。
  home             归位到主城（ensure_main_city）。
  node NAME        跑**真实节点** NAME（把它的 ``next`` 清空 → 只执行它自己的识别+动作一次），
                   然后抓屏 classify。可用 ``--set``/``--set-file`` 追加 pipeline_override。
  nodes A,B,C      依次跑多个真实节点（各 next=[]）。每步抓屏。
  trace ENTRY      跑完整 ENTRY（默认 WuchongEntry）固定秒数，期间周期抓帧（不 save_draw）。
  switch WHICH     只读报告某开关的橙占比；``--toggle`` 才点一下 toggle 并复查。

★界面选项（#56 coop-fix2，审计 P0）★：``--mode 单人|多人`` / ``--manual 自动|手操`` /
``--cont 是|否`` / ``--cadence 字段=值`` 分别应用「游戏模式 / 是否手操 / 是否自动续战 /
手操节奏参数」；其余任务选项取 ``default_case``。**应用选项的缝 = tools/interface_options.py**
（与 MFAAvalonia 同一条路），所以 trace 跑出来的状态代表产品。生效覆盖会打印到 stdout
（``[options] …``）——保存 stdout 即可复核到底施加了什么。

★安全★：不设 save_draw（改由本脚本周期 post_screencap 采样，见 --interval）；坐标一律 720，
adb 侧按**设备实际分辨率**换算（``live_harness.device_scale()`` 读 ``wm size``，不写死 ×1.5）；
永远先读后动；本脚本自身不盲点。

★--as-gui（#138）★：启动时按内容哈希硬闸 ``install/agent ↔ agent/`` 与
``install/resource ↔ assets/resource``（pipeline ``*.json`` + ``image/**/*.png``）；
不一致默认**非零退出**（修法：``python tools/sync_install.py``），只有显式
``--allow-stale-install`` 才允许在旧包上验收（会警告「本次验的不是最新流水线」）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "agent"))
if str(TOOLS) not in sys.path:  # 以 module 方式被守卫 import 时，tools/ 不一定在 sys.path
    sys.path.append(str(TOOLS))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

import live_harness as ca  # noqa: E402
import interface_options as iopt  # noqa: E402
import wuchong_impl as wc  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"
from portable_paths import TEMP_OPENCODE  # noqa: E402

import sync_install  # noqa: E402  #138: install/ 与仓库的内容哈希比对 + 统一修法命令

WORK = TEMP_OPENCODE / "wc_live"
WORK.mkdir(parents=True, exist_ok=True)

#: ★无死默认地址（#25）★：地址只来自 --address / WF_LIVE_ADDRESS / 身份发现。
DEFAULT_ADDRESS = os.environ.get("WF_LIVE_ADDRESS", "")

#: `--mode 单人/多人` -> interface.json「游戏模式」的 case 名。
_MODE_CASE = {"单人": "单人游戏", "多人": "多人游戏"}

#: #138：`--as-gui` 硬闸的退出码（非零）。2 = install/ 与仓库不一致，本次拒绝真机验收。
STALE_INSTALL_EXIT = 2


def check_install_freshness(project: Path, *, allow_stale: bool = False) -> bool:
    """#138 硬闸：`--as-gui` 启动前证明 `install/` 与仓库同源（逐文件 sha256）。

    GUI 的语义是「资源读 ``install/resource``、代码从仓库 ``agent/`` 导入」；install 落后
    时就是**旧流水线 + 新代码**，日志里看到的修复与实际生效的修复不是同一份。原实现只
    对 ``install/agent`` 打印警告、且从不比 ``install/resource`` —— 这里两件事都改成硬闸：

    * ``install/agent`` ↔ ``agent/``（全部源文件；忽略 __pycache__/*.pyc/debug）；
    * ``install/resource`` ↔ ``assets/resource``（pipeline ``*.json`` + ``image/**/*.png``）。

    不一致时打印可复制的修法并 ``raise SystemExit(STALE_INSTALL_EXIT)``；只有显式
    ``allow_stale=True``（``--allow-stale-install``，默认关）才放行，且必须打一行
    「本次验的不是最新流水线」的警告。返回 True = 一致；False = 显式允许了落后。
    """
    report = sync_install.compare_install(project)
    if not report.gate_stale:
        print(
            "[as-gui] ✓ install/agent 与仓库一致（GUI 与本次验收跑同一份代码；逐文件 sha256）",
            flush=True,
        )
        print(
            "[as-gui] ✓ install/resource 与 assets/resource 一致"
            "（pipeline *.json + image/**/*.png 逐文件 sha256）",
            flush=True,
        )
        return True

    if allow_stale:
        print(
            "[as-gui] ★警告★ --allow-stale-install：本次验的不是最新流水线"
            "（install/ 落后于仓库，仍继续）",
            flush=True,
        )
    print(
        "[as-gui] ✗ install/ 落后于仓库 —— 拒绝在「旧流水线 + 新代码」上验收",
        flush=True,
    )
    print(
        "[as-gui]   （--as-gui 语义：资源读 install/resource、代码从仓库 agent/ 导入；两者必须同源）",
        flush=True,
    )
    for line in sync_install.format_lines(report, prefix="[as-gui] "):
        print(line, flush=True)
    print(f"[as-gui] {sync_install.FIX_HINT}", flush=True)
    if allow_stale:
        return False
    print(
        "[as-gui] 逃生阀（默认关，仅明确要验旧包时用）：--allow-stale-install",
        flush=True,
    )
    print(
        f"[as-gui] ✗ 退出码 {STALE_INSTALL_EXIT}：install/ 与仓库不一致，本次不跑（修完再验）",
        flush=True,
    )
    raise SystemExit(STALE_INSTALL_EXIT)



def wuchong_override(
    project: Path,
    *,
    mode: str | None = None,
    manual: str | None = None,
    cont: str | None = None,
    cadence: list[str] | None = None,
) -> dict:
    """算出**产品等价**的界面选项覆盖（#56 coop-fix2 审计 P0）。

    ★为什么★：本 runner 过去从不应用界面选项 → 「游戏模式 / 是否手操 / 是否自动续战 /
    手操节奏参数」全不生效（raw 默认）→ 跑出来的结果**不代表产品**。这里按任务 option 列表
    逐项取 case（未指定取 default_case）叠加，与 MFAAvalonia 走同一条缝。
    """
    sel: dict = {}
    if mode:
        sel["游戏模式"] = _MODE_CASE[mode]
    if manual:
        sel["是否手操"] = manual  # 「自动」/「手操」
    if cont:
        sel["是否自动续战"] = cont  # 「是」/「否」
    inputs: dict = {}
    for item in (cadence or []):
        k, _, v = item.partition("=")
        if not v:
            raise SystemExit(f"--cadence 需要 字段=值，收到 {item!r}")
        inputs[k.strip()] = v.strip()
    # 是否自动续战不在五重任务列表里，但产品运行态也把它设成「否」（ruling ③）——一并施加。
    return iopt.resolve_task_override(
        project, "五重决战", sel, inputs, extra_options=("是否自动续战",)
    )


class Ctx:
    def __init__(self) -> None:
        self.tasker: Tasker | None = None
        self.watcher: ca.TitleWatcher | None = None
        self.n = 0

    def grab_png(self, label: str):
        """抓屏，保存为 work/<label>.png（RGB 正确），返回 (path, rgb_pil, bgr_nd)."""
        assert self.watcher is not None
        img = self.watcher.grab()  # BGR ndarray per harness
        rgb = np.ascontiguousarray(img[:, :, ::-1])
        self.n += 1
        path = WORK / f"{self.n:03d}_{label}.png"
        Image.fromarray(rgb).save(path)
        return path, Image.fromarray(rgb), img

    def ocr(self, bgr) -> list:
        assert self.watcher is not None
        return self.watcher.ocr(bgr)


#: 当前进度（report_state 每轮更新；长跑监管的 state_fn 读它）。
_PROGRESS: dict = {"state": None, "label": None}


def report_state(ctx: Ctx, label: str, save: bool = True, dump_ocr: bool = False) -> tuple:
    assert ctx.watcher is not None
    img = ctx.watcher.grab()
    items = ctx.watcher.ocr(img)
    state, info = wc.classify(items)
    if save:
        rgb = np.ascontiguousarray(img[:, :, ::-1])
        ctx.n += 1
        path = WORK / f"{ctx.n:03d}_{label}.png"
        Image.fromarray(rgb).save(path)
        print(f"[state] {label}: state={state} info={info} frame={path.name}", flush=True)
    else:
        print(f"[state] {label}: state={state} info={info}", flush=True)
    # ★#98 集成★ 把 state 留给长跑监管的 state_fn（否则监管只靠画面 hash，
    #   战斗内长时间不换页会被误判成卡住）。全局槽由 runner 自己维护，不跨进程。
    _PROGRESS["state"] = state
    _PROGRESS["label"] = label
    return state, info
    if dump_ocr:
        for t, b in items:
            print(f"    OCR {t!r} {b}")
    return state, info, items


def orange_ratios(rgb_pil) -> dict:
    """按 scene.wuchong 的几何量报告「自动续战」探针橙占比（只读）。

    ★#56 二批★：「自动」按钮已改为**定位**（模板/OCR）——不再有固定探针，见 ``locate``。
    """
    sw = wc.CFG.WUCHONG_SWITCHES
    groups = {"cont": sw.cont_probes}

    def one(p):
        r = wc._orange_ratio(rgb_pil, p)
        return -1.0 if r is None else round(r, 4)

    out = {}
    for name, probes in groups.items():
        out[name] = [one(p) for p in probes]
    out["on_ratio"] = sw.on_ratio
    return out


def run_node(ctx: Ctx, name: str, extra: dict | None = None, timeout: float = 60.0) -> None:
    assert ctx.tasker is not None
    override = {name: {"next": []}}
    if extra:
        for k, v in extra.items():
            override.setdefault(k, {}).update(v)
    print(f"\n===== run node {name} override={json.dumps(override, ensure_ascii=False)} =====", flush=True)
    report_state(ctx, f"pre_{name}", save=True)
    job = ctx.tasker.post_task(name, override)
    status = ca.wait_job_bounded(ctx.tasker, job, timeout=timeout, label=name)
    print(f"[node] {name}: bounded-status={status}", flush=True)
    detail = job.get()
    if detail is not None:
        for node in detail.nodes:
            reco = node.recognition
            algo = getattr(reco, "algorithm", None) if reco is not None else None
            hit = getattr(reco, "hit", None) if reco is not None else None
            rbox = list(getattr(reco, "box", []) or []) if reco is not None else None
            best = getattr(reco, "best_result", None) if reco is not None else None
            box = list(getattr(best, "box", []) or []) if best is not None else None
            txt = getattr(best, "text", "") if best is not None else ""
            print(f"    node={node.name} algo={algo} hit={hit} reco.box={rbox} best.box={box} text={txt!r}", flush=True)
            act = getattr(node, "action", None)
            if act is not None:
                print(f"        action={act}", flush=True)
    time.sleep(1.0)
    report_state(ctx, f"post_{name}", save=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=None)
    ap.add_argument("--adb", default=ca.ADB)
    # ★#104★ 设备独占租约（D9）：被占默认**排队等**，显式 --steal 才强抢。
    ap.add_argument("--steal", action="store_true", help="强抢设备租约（默认排队等）")
    # ★#98★ 长跑监管：跑 trace/run 时自动起（20s 心跳 / 90s 卡住报警 / 证据落盘）。
    ap.add_argument("--monitor", action="store_true", help="同时开长跑监管")
    ap.add_argument("--monitor-stall", type=float, default=90.0, help="卡住阈值秒（默认 90）")
    ap.add_argument("--monitor-interval", type=float, default=20.0, help="心跳间隔秒（默认 20）")
    # ★Q1★ 与 GUI 等价的验收模式：用 install/resource + 静音 + 核对 install 是否落后。
    ap.add_argument("--as-gui", dest="as_gui", action="store_true",
                    help="GUI 等价模式：加载 install/resource、开 --quiet、按内容哈希硬闸 install/ 与仓库")
    # ★#138★ 逃生阀：默认关；用了必须显式警告「本次验的不是最新流水线」。
    ap.add_argument("--allow-stale-install", dest="allow_stale_install", action="store_true",
                    help="★逃生阀（默认关）★ 允许 --as-gui 在 install/ 落后时继续（会显式警告）")
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--recon", action="store_true")
    sub.add_argument("--home", action="store_true")
    sub.add_argument("--state", metavar="LABEL")
    sub.add_argument("--node", metavar="NAME")
    sub.add_argument("--nodes", metavar="A,B,C")
    sub.add_argument("--switch", metavar="WHICH")
    sub.add_argument("--tap-text", dest="tap_text", metavar="REGEX")
    sub.add_argument("--tap-roi", dest="tap_roi", default=None, help="x0,y0,x1,y1 (720)")
    sub.add_argument("--trace", metavar="ENTRY", nargs="?", const="WuchongEntry")
    ap.add_argument("--set", default=None, help="追加 pipeline_override（JSON 字符串）")
    ap.add_argument("--set-file", dest="set_file", default=None, help="追加 pipeline_override（JSON 文件）")
    ap.add_argument(
        "--mode", choices=["单人", "多人"], default=None,
        help="应用界面选项「游戏模式」=单人/多人（与产品同一条缝）",
    )
    ap.add_argument(
        "--manual", choices=["自动", "手操"], default=None,
        help="应用界面选项「是否手操」=自动/手操（与产品同一条缝）",
    )
    ap.add_argument(
        "--cont", choices=["是", "否"], default=None,
        help="应用界面选项「是否自动续战」=是/否（默认「否」；ruling ③）",
    )
    ap.add_argument(
        "--cadence", action="append", default=None, metavar="字段=值",
        help="应用「手操节奏参数」输入项（可重复）：弹板间隔/技能间隔/每几次弹板放技能/连点批量",
    )
    ap.add_argument(
        "--option", action="append", default=None, metavar="NAME=CASE",
        help="应用任意界面选项 case 的 pipeline_override（可重复）",
    )
    ap.add_argument("--toggle", action="store_true", help="switch 模式：真的点一下 toggle 并复查")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--dump-ocr", action="store_true")
    a = ap.parse_args()

    # ★#138 硬闸★：先证明 install/ 与仓库同源，再碰设备 —— 绝不在「旧流水线 + 新代码」
    #   上验收。比对范围 = install/agent ↔ agent/ + install/resource ↔ assets/resource
    #   （pipeline *.json + image/**/*.png），按内容哈希；不一致默认非零退出。
    if getattr(a, "as_gui", False):
        check_install_freshness(
            PROJECT, allow_stale=bool(getattr(a, "allow_stale_install", False))
        )

    raw_set = None
    if a.set_file:
        raw_set = Path(a.set_file).read_text(encoding="utf-8")
    elif a.set:
        raw_set = a.set

    # ★#56 coop-fix2 审计 P0★：先把界面选项（= 产品走的那条缝）算成 pipeline_override，
    #   再叠加 --option / --set（后者优先）。这样「游戏模式/是否手操/是否自动续战/节奏参数」
    #   真的生效 —— 否则跑出来的结果不代表产品。
    extra: dict = wuchong_override(
        PROJECT, mode=a.mode, manual=a.manual, cont=a.cont, cadence=a.cadence
    )
    _iface = iopt.load_interface(PROJECT)
    for item in (a.option or []):
        opt_name, _, case_name = item.partition("=")
        if not case_name:
            raise SystemExit(f"--option 需要 NAME=CASE，收到 {item!r}")
        iopt._deep_merge(extra, iopt.option_override(_iface, opt_name.strip(), case_name.strip()))
    if raw_set:
        iopt._deep_merge(extra, json.loads(raw_set))
    print("[options] mode=%s manual=%s cont=%s cadence=%s" %
          (a.mode, a.manual, a.cont, a.cadence), flush=True)
    print("[options] 生效的界面选项覆盖 = " + json.dumps(extra, ensure_ascii=False), flush=True)

    ca.apply_global_options(PROJECT)
    address = (
        a.address
        or os.environ.get("WF_LIVE_ADDRESS")
        or ca.resolve_address(a.adb, ca.expected_identity())
    )
    ca.assert_device_identity(a.adb, address, ca.expected_identity())
    ctrl = ca.connect_device(a.adb, address, steal=bool(getattr(a, "steal", False)))
    # ★#98★ 长跑监管（可选）：把「当前 state」喂给 state_fn，让战斗内长演出不被误判成卡住。
    _mon = None
    if getattr(a, "monitor", False):
        try:
            import longrun_monitor as _lm  # noqa: PLC0415

            def _state_fn():  # noqa: ANN202
                return _PROGRESS.get("state") or "unknown"


            _mon = _lm.monitor_for_serial(
                address,
                state_fn=_state_fn,
                interval=float(getattr(a, "monitor_interval", 20.0)),
                stall=float(getattr(a, "monitor_stall", 90.0)),
                out="debug/longrun",
            )
            _mon.start()
            print(f"[monitor] 长跑监管已启动（心跳 {getattr(a, 'monitor_interval', 20.0):.0f}s / "
                  f"卡住 {getattr(a, 'monitor_stall', 90.0):.0f}s）", flush=True)
            import atexit as _atexit  # noqa: PLC0415

            def _mon_stop_and_summary():  # noqa: ANN202
                try:
                    _mon.stop()
                    _mon.join(timeout=5.0)
                    print(f"[monitor] {_mon.summary.as_line()}", flush=True)
                except Exception:  # noqa: BLE001
                    pass

            _atexit.register(_mon_stop_and_summary)
        except Exception as exc:  # noqa: BLE001 监管失败绝不影响主流程
            print(f"[monitor] 启动失败（忽略）：{exc!r}", flush=True)
            _mon = None

    ctx = Ctx()

    res = Resource()
    assets_dir = ASSETS
    if getattr(a, "as_gui", False):
        inst_res = PROJECT / "install" / "resource"
        if inst_res.is_dir():
            assets_dir = inst_res
        else:
            print(
                f"[as-gui] ✗ 没找到 {inst_res} → 退回仓库 assets"
                "（只有 --allow-stale-install 才会走到这里）",
                flush=True,
            )
        # install/ 的代码+资源一致性已在入口的 check_install_freshness() 硬闸证明过：
        #   不一致时默认在碰设备之前就非零退出，这里只负责选资源目录 / 开静音。
        try:
            import wuchong_impl as _wi  # noqa: PLC0415

            _wi.set_quiet(True)
            print("[as-gui] 已开静音（与 GUI 的 --quiet 一致：只剩『要打几次 / 第 i/N 次 / 收工原因』）", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[as-gui] 静音未生效：{exc!r}", flush=True)
        print("[as-gui] 与 GUI 的唯一差异：agent 在本进程内注册（GUI 是独立子进程）。", flush=True)

    print("resource load:", res.post_bundle(str(assets_dir)).wait().succeeded, flush=True)
    ca.register_pipeline_customs(res)
    tasker = Tasker()
    print("bind:", tasker.bind(res, ctrl), flush=True)
    ctx.tasker = tasker
    ctx.watcher = ca.TitleWatcher(str(ASSETS))

    if a.recon:
        path, rgb, bgr = ctx.grab_png("recon")
        items = ctx.ocr(bgr)
        state, info = wc.classify(items)
        print(f"[recon] frame={path.name} state={state} info={info}", flush=True)
        print(f"[recon] orange={orange_ratios(rgb)}", flush=True)
        box = wc.auto_switch.locate_switch_label(items, wc.auto_switch.AUTO_LABEL)
        if box is not None:
            state = wc.auto_switch.read_switch_state(np.ascontiguousarray(bgr), wc.auto_switch.AUTO_LABEL, box)
            print(f"[recon] 「自动」定位 box={box} state={state} "
                  f"probe={wc.auto_switch.probe_for(wc.auto_switch.AUTO_LABEL, box)}", flush=True)
        else:
            print("[recon] 「自动」定位不到（无该按钮 / 非编队页）", flush=True)
        role, rank = ca.read_game_identity(np.ascontiguousarray(bgr), ASSETS)
        print(f"[recon] role={role!r} rank={rank!r}", flush=True)
        print("[recon] OCR 全文：")
        for t, b in items:
            print(f"    {t!r} {b}")
        return

    if a.home:
        ok = ca.ensure_main_city(ctx.watcher)
        print(f"[home] ensure_main_city -> {ok}", flush=True)
        report_state(ctx, "after_home", save=True)
        return

    if a.state:
        report_state(ctx, a.state, save=True, dump_ocr=a.dump_ocr)
        return

    if a.tap_text:
        import re as _re

        path, rgb, bgr = ctx.grab_png("tap_text")
        items = ctx.ocr(bgr)
        roi = [int(v) for v in a.tap_roi.split(",")] if a.tap_roi else None
        reg = _re.compile(a.tap_text)
        box = None
        for t, b in items:
            if not b or len(b) != 4 or not reg.search(t or ""):
                continue
            cx, cy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
            if roi and not (roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]):
                continue
            box = b
            break
        if box is None:
            print(f"[tap-text] 未找到 {a.tap_text!r}；可见={[t for t,_ in items][:20]}", flush=True)
            return
        cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
        print(f"[tap-text] 点击 {a.tap_text!r} box={box} 中心720=({cx:.0f},{cy:.0f})", flush=True)
        ca.adb_tap(cx, cy)
        time.sleep(2.0)
        report_state(ctx, "after_tap_text", save=True)
        return

    if a.switch:
        path, rgb, bgr = ctx.grab_png(f"switch_{a.switch}_before")
        label = wc.auto_switch.AUTO_LABEL if a.switch == "auto" else wc.auto_switch.CONT_LABEL
        box = wc.auto_switch.locate_switch_label(ctx.ocr(bgr), label)
        state = None if box is None else wc.auto_switch.read_switch_state(np.ascontiguousarray(bgr), label, box)
        probe = None if box is None else wc.auto_switch.probe_for(label, box)
        print(f"[switch] which={a.switch} 定位={box} probe={probe} on={state} on_ratio={wc.AUTO_ON_RATIO}", flush=True)
        if a.toggle:
            if box is None:
                print("[switch] 定位不到 → 不动（绝不猜坐标）")
            else:
                x, y = wc.auto_switch.click_point(box)
                print(f"[switch] 点识别框中心 720=({x},{y})", flush=True)
                ca.adb_tap(x, y)
                time.sleep(1.2)
                path2, rgb2, bgr2 = ctx.grab_png(f"switch_{a.switch}_after")
                b2 = wc.auto_switch.locate_switch_label(ctx.ocr(bgr2), label)
                st2 = None if b2 is None else wc.auto_switch.read_switch_state(np.ascontiguousarray(bgr2), label, b2)
                print(f"[switch] after 定位={b2} on={st2}", flush=True)
        return

    if a.node:
        run_node(ctx, a.node, extra or None, timeout=a.timeout)
        return

    if a.nodes:
        for name in [s.strip() for s in a.nodes.split(",") if s.strip()]:
            run_node(ctx, name, extra or None, timeout=a.timeout)
        return

    if a.trace:
        print(f"\n===== TRACE {a.trace} for {a.seconds}s override={json.dumps(extra, ensure_ascii=False)} =====", flush=True)
        job = tasker.post_task(a.trace, extra)
        end = time.time() + a.seconds
        i = 0
        while time.time() < end:
            time.sleep(a.interval)
            i += 1
            try:
                report_state(ctx, f"trace{i:02d}", save=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[trace] 抓帧异常：{exc}")
        print("[trace] stopping:", flush=True)
        ca._terminate_task(tasker, job, deadline=15.0)
        detail = job.get()
        try:
            for node in detail.nodes:
                print(f"    trace-node={node.name}", flush=True)
        except Exception:  # noqa: BLE001
            pass
        return


if __name__ == "__main__":
    main()
