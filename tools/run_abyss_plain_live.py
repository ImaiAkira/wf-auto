# -*- coding: utf-8 -*-
"""真机验证：普通深渊（#55 Phase 3）—— 「同实现 + 数据」（运维：只差导航）。

驱动任务 ``AbyssPlainEntry``（普通深渊入口）走完整链路，并**只读监控**：
    主城 → 活动 → 终始之战 →（数据驱动搜三个二级页签）→ 普通深渊横幅 → hub
    → 确认框 OK → 关卡选择页（第N战）→ 单人编队 → 挑战 → 战斗 →（时间够则到结算）。

★安全性（与仓库既定纪律一致）★：
  · **绝不 save_draw**（启动走 ``live_harness.apply_global_options``：默认关；本脚本不设
    ``WF_SAVE_DRAW``）；失败帧仍由框架的 save_on_error 保留。
  · 任务本身**先读后动**：每个动作节点由 ``abyss_state`` / ``abyss_scene`` 门控，动作由
    ``abyss_act`` 先截图 OCR 再点 OCR 到的按钮中心（绝不识别框 + 死偏移）。
  · 监控**只做 screencap + OCR + 状态打印**（不点屏幕、不按返回键）；硬上限 / 无进展即停。
  · 深渊「第1战」为 **体力 0**、不消耗任何付费 / 有限资源（校准 §4）。

横幅可区分性（校准 §3.2 坑 1）：监控在终始之战列表页会同时算两个模板对当前帧
（720 ROI 26,463,671,146）的 ZNCC —— 普通深渊横幅下 plain≈1.0、ex≈0.87（< 0.90 阈值，
故 EX 模板**不会**交叉命中）；EX 横幅下反之。

用法（#130：**型号不是必须匹配** —— 默认一个都不校验，只把读到的型号打进诊断日志；
只有显式设置 ``WF_LIVE_EXPECT_MODEL`` / ``WF_LIVE_EXPECT_PRODUCT`` 时才严格比较、相等才跑）::

    .venv\\Scripts\\python.exe tools\\run_abyss_plain_live.py --address 127.0.0.1:16448 --seconds 900

退出码：0 = 观察到普通深渊链路推进（至少到 hub/关卡选择页）；1 = 未观察到（看 stdout）。
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "agent"))
sys.path.insert(0, str(PROJECT / "tools"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

import live_harness as ca  # noqa: E402
import progress as ledger  # noqa: E402
import abyss_impl as ab  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"
IMAGE_DIR = ASSETS / "image"

#: 横幅 ROI（720 空间；与 abyss.json 的 AbyssBannerEx/AbyssBannerPlain roi 同源）。
BANNER_ROI = (26, 463, 671, 146)
EX_TPL = "banner_abyss_ex.png"
PLAIN_TPL = "banner_abyss_plain.png"


# ---------------------------------------------------------------------------
# 模板匹配（复刻 MAA 原生 TemplateMatch 的判据口径：ZNCC 灰度、原生尺度、roi 内滑窗）
# ---------------------------------------------------------------------------
def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = float(((a * a).sum() * (b * b).sum()) ** 0.5)
    return float((a * b).sum() / den) if den else 0.0


def _gray(img: np.ndarray) -> np.ndarray:
    """720x1280 BGR -> 灰度 float64。"""
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    return np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.float64)


def _template(name: str) -> np.ndarray:
    return np.asarray(Image.open(IMAGE_DIR / name).convert("L"), dtype=np.float64)


def match_in_roi(gray: np.ndarray, tpl: np.ndarray, roi, margin: int = 8) -> float:
    """在 roi 附近（±margin）滑窗取 ZNCC 最大值。"""
    x, y, w, h = roi
    th, tw = tpl.shape
    best = 0.0
    for dy in range(-margin, margin + 1):
        for dx in range(-margin, margin + 1):
            x0, y0 = x + dx, y + dy
            if x0 < 0 or y0 < 0 or x0 + tw > gray.shape[1] or y0 + th > gray.shape[0]:
                continue
            patch = gray[y0 : y0 + th, x0 : x0 + tw]
            s = _zncc(patch, tpl)
            if s > best:
                best = s
    return best


def banner_scores(gray: np.ndarray) -> dict[str, float]:
    return {
        EX_TPL: match_in_roi(gray, _template(EX_TPL), BANNER_ROI),
        PLAIN_TPL: match_in_roi(gray, _template(PLAIN_TPL), BANNER_ROI),
    }


# ---------------------------------------------------------------------------
# 只读抓屏（走 adb exec-out，独立于 MAA controller；不干扰正在跑的任务）
# ---------------------------------------------------------------------------
def screencap_720() -> np.ndarray:
    proc = subprocess.run(
        [ca.ADB, "-s", ca.ADDRESS, "exec-out", "screencap", "-p"],
        capture_output=True,
    )
    im = Image.open(io.BytesIO(proc.stdout))
    if im.size != (720, 1280):
        im = im.resize((720, 1280))
    return np.ascontiguousarray(np.asarray(im.convert("RGB"))[:, :, ::-1])


def save_frame(img: np.ndarray, name: str) -> Path:
    ca.SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = ca.SHOT_DIR / name
    Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(path)
    return path


def _tap_ocr(watcher, pattern, roi=None, tries: int = 6, wait: float = 2.0) -> bool:
    """只读导航的一步：OCR 到 ``pattern`` 的按钮框就点它的中心（绝不盲点固定坐标）。"""
    for _ in range(tries):
        img = screencap_720()
        items = watcher.ocr(img)
        box = ca._pick(items, pattern, roi)
        if box:
            cx, cy = ca._center(box)
            print(f"[banner-probe] 点 {pattern!r} @720({cx},{cy})", flush=True)
            ca.adb_tap(cx, cy)
            time.sleep(wait)
            return True
        time.sleep(wait)
    print(f"[banner-probe] 未 OCR 到 {pattern!r}（停手，不盲点）", flush=True)
    return False


def banner_only(watcher) -> int:
    """只读横幅探针：主城 → 活动 → 终始之战 → 逐页签截帧 + 算两条模板 ZNCC。

    ★零玩法、零点击盲点★：只点 OCR 到的「活动 / 终始之战 / 页签」框中心；不开任何战斗。
    用途：给出「普通深渊横幅」上 plain vs ex 两条模板的**真机分数**（校准 §3.2 坑 1 复核）。
    """
    if not ca.ensure_main_city(watcher):
        print("!! 未回主城")
        return 1
    if not _tap_ocr(watcher, r"^活动$"):
        return 1
    if not _tap_ocr(watcher, r"终始之战"):
        return 1
    found = False
    for tab in ("未通关", "已通关", "完成"):
        img = screencap_720()
        items = watcher.ocr(img)
        if not _tap_ocr(watcher, f"^{tab}$", tries=2):
            print(f"[banner-probe] 页签 {tab!r} 不在场，跳过", flush=True)
            continue
        img = screencap_720()
        g = _gray(img)
        sc = banner_scores(g)
        print(
            f"[banner-probe] 页签={tab} 横幅 ZNCC（ROI {BANNER_ROI}）: "
            f"ex={sc[EX_TPL]:.4f} plain={sc[PLAIN_TPL]:.4f} （阈值 {ab.BANNER_THRESHOLD}）",
            flush=True,
        )
        save_frame(img, f"abyss_plain_probe_tab_{tab}.png")
        if sc[PLAIN_TPL] >= 0.90:
            found = True
    return 0 if found else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default="127.0.0.1:16448")
    ap.add_argument("--entry", default="AbyssPlainEntry")
    ap.add_argument("--seconds", type=float, default=900.0, help="硬上限（秒）")
    ap.add_argument("--stall", type=float, default=120.0, help="无新节点超过它即停（秒）")
    ap.add_argument("--interval", type=float, default=10.0, help="监控打印 / 抓屏间隔（秒）")
    ap.add_argument("--poll", type=float, default=1.0, help="节点轨迹轮询间隔（秒）")
    ap.add_argument(
        "--banner-only",
        action="store_true",
        help="只读横幅探针：主城→活动→终始之战→逐页签算两条模板 ZNCC（不开战、不盲点）",
    )
    args = ap.parse_args()

    # #perf：唯一启动缝（save_draw 默认关 + debug 产物上界）。★本脚本绝不设 WF_SAVE_DRAW★。
    ca.apply_global_options(PROJECT)

    address = args.address
    ca.assert_device_identity(ca.ADB, address, ca.expected_identity())  # 身份守卫（#40）
    ctrl = ca.connect_device(ca.ADB, address)
    print("device connect:", ctrl.connected, flush=True)

    res = Resource()
    print("resource load:", res.post_bundle(str(ASSETS)).wait().succeeded)
    print("nodes:", len(res.node_list))
    ca.register_pipeline_customs(res)  # 唯一注册源（#20）

    tasker = Tasker()
    print("bind:", tasker.bind(res, ctrl), flush=True)

    watcher = ca.TitleWatcher(str(ASSETS))

    # 真机测试用独立账本文件，避免污染正式 progress.json。
    pf = ca.WORK_DIR / "abyss_plain_live_progress.json"
    ledger.set_file(pf)
    print("ledger file:", pf, flush=True)

    if args.banner_only:
        return banner_only(watcher)

    if not ca.ensure_main_city(watcher):
        print("!! 未回主城，停手")
        return 1

    job = tasker.post_task(args.entry)
    tid = job.job_id
    print(f"[driver] 投递 {args.entry}（job={tid}）", flush=True)

    start = time.time()
    last_progress = start
    last_print = 0.0
    prev = 0
    executed: list[str] = []
    best_plain = 0.0
    reached = False
    status = "timeout"

    try:
        while True:
            time.sleep(max(0.3, args.poll))
            now = time.time()

            try:
                detail = tasker.get_task_detail(tid)
                nodes = list(detail.nodes) if detail is not None else []
            except Exception as exc:  # noqa: BLE001
                nodes = []
                print(f"[driver] 节点读取异常：{exc}", flush=True)
            if len(nodes) != prev:
                for nd in nodes[prev:]:
                    executed.append(getattr(nd, "name", "?"))
                prev = len(nodes)
                last_progress = now

            if job.done:
                status = ca._job_status(job)
                break
            if (now - start) > args.seconds:
                status = "hard-cap"
                break
            if (now - last_progress) > args.stall:
                status = "stalled"
                break

            if (now - last_print) >= args.interval:
                last_print = now
                img = screencap_720()
                items = watcher.ocr(img)
                state, _info = ab.classify(items)
                line = (
                    f"[monitor] t={now - start:6.1f}s state={state} "
                    f"scene={ab._cfg().scene} ledger={ab._cfg().ledger_scope} "
                    f"nodes={len(nodes)} 最近={executed[-4:]}"
                )
                print(line, flush=True)
                if state == "zhongshi":
                    g = _gray(img)
                    sc = banner_scores(g)
                    print(
                        f"[monitor] 横幅 ZNCC（ROI {BANNER_ROI}）: "
                        f"ex={sc[EX_TPL]:.4f} plain={sc[PLAIN_TPL]:.4f} "
                        f"（阈值 {ab.BANNER_THRESHOLD}）",
                        flush=True,
                    )
                    if sc[PLAIN_TPL] > best_plain:
                        best_plain = sc[PLAIN_TPL]
                        p = save_frame(img, "abyss_plain_banner_frame.png")
                        print(f"[monitor] 普通深渊横幅帧已存 {p}", flush=True)
                if state in ("abyss_hub", "abyss_main", "abyss_solo_team", "abyss_battle", "abyss_settle"):
                    reached = True
                    p = save_frame(img, f"abyss_plain_{state}.png")
                    print(f"[monitor] 状态 {state} 帧已存 {p}", flush=True)
    finally:
        if not job.done:
            ca._terminate_task(tasker, job, deadline=15.0)

    print("\n[driver] 执行节点轨迹（按命中顺序）:", executed, flush=True)
    print(
        f"[driver] status={status} 最佳普通深渊横幅 ZNCC={best_plain:.4f} "
        f"（EX 模板 THRESHOLD={ab.BANNER_THRESHOLD}）",
        flush=True,
    )
    return 0 if reached else 1


if __name__ == "__main__":
    raise SystemExit(main())
