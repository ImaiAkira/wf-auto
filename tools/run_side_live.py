# -*- coding: utf-8 -*-
"""真机验证：外传「账本驱动选关」next_stage / mark_done（在进程内注册，不启动 AgentServer）。

为什么要这样跑
--------------
本项目的自定义识别/动作由 AgentServer 注册（正常由 MFAAvalonia 拉起子进程）。
为了能在没有 MFAAvalonia 的情况下做真机验证，这里直接把 side_impl 里的类注册到
进程内 Resource 上 —— 所以 side_impl【不导入 maa.agent】，否则 native 库会切换、
Resource() 直接创建失败。

本脚本做的是【只读识别验证】（动作覆盖为 DoNothing，不点击游戏）：
  1. 从主城导航到「外传故事列表」→「未通关」→ 第一张卡 → 该外传的关卡列表；
  2. 把 SideNextSpecial / SideNextStory / SideNextBattle 三个节点各跑一次识别，
     打印它们选中的关卡名与标题框；
  3. 把选中的那一关写进账本（mark_done），再跑一次，确认【不会再返回同一关】；
  4. 导航回主城收尾。

用法:
    python tools/run_side_live.py            # 只读验证（安全，不点游戏关卡）
    python tools/run_side_live.py --back     # 验证完回主城（默认就回）

#51 起（读后动 + 明确收工；见下方 entry_decision 的说明）：
  · 点「未通关」后先读列表：空（未找到符合的外传故事）-> 明确收工并给出原因（不静默、不盲点）；
  · 非空 -> 点【识别到的第一张卡标记框中心】进入，并复核画面确有 NEW/COMPLETE!! 徽标
    （= 真在外传关卡列表）才对三个账本节点取证；记账只在真正从关卡列表选出一关之后
    （与 #44 同一条纪律：绝不用陈旧页面记账）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "agent"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

import live_harness as ca  # noqa: E402
import progress as ledger  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"

# ===========================================================================
# ★#51★ 外传「进入卡片」的读后动纯函数（不碰设备，离线可单测）
#
# 真机 relayB（16448，见 tools/frames/side_story_list_empty.png / live_stage_list.png）：
#   导航到「外传故事列表」-> 点「未通关」-> 旧代码**盲点固定坐标** (540,720) -> 什么都没进
#   -> 三个账本节点（SideNextSpecial/Story/Battle）当然 hit=False，任务却「静默地什么都没做」
#   （随后干净回主城）。根因【不是】关卡列表结构不匹配 —— 实测该账号「未通关」列表为空
#   （画面显示「未找到符合的外传故事」），因此根本没有卡片可进。
#
# 真实结构（真机帧 tools/frames/）：
#   · 外传故事列表：三张卡（虚假的人偶公主 / 幻彩摩天楼 / 情人节盛典），每张卡右侧有
#     「角色加入/装备获得」标记 -> SideClearEnterCard 的 And(列表标题, 第一张卡标记) 命中；
#   · 点第一张卡 -> 外传关卡列表（大标题 = 该外传名；行带 NEW/COMPLETE!! 徽标 + STORY /
#     战斗 / 特殊战斗 标签 + 关卡标题）-> parse_side_rows / select_side_stage 正确解析，
#     SideNextStory 命中（真机帧 tools/frames/event_stage_list.png 已证）。
#
# 因此本文件的处置是【读后动 + 明确收工】：
#   1. 先读「未通关」列表：空（「未找到符合的外传故事」）-> **明确收工并给出原因**
#      （绝不静默 hit=False、绝不盲点固定坐标）；
#   2. 非空 -> 点【识别到的第一张卡标记框中心】进入；
#   3. 进入后复核画面确有 NEW/COMPLETE!! 徽标（= 真是外传关卡列表）才对三个节点取证；
#   4. 记账只在【真正从关卡列表里选出一关】之后发生（与 #44 同一条纪律：绝不用陈旧页面记账）。
# ===========================================================================
SIDE_LIST_TITLE = "外传故事列表"
# 列表为空时游戏给的明确文案（照抄 side_story.json::SideClearDone 的收工判据，单源不另造）。
SIDE_LIST_EMPTY = "未找到符合的外传故事"
# 卡片标记（照抄 side_story.json::SideClearCardMark，单源不另造）。
SIDE_CARD_MARK = "角色加入/装备获得"
# 卡片标记 ROI（720）——照抄 side_story.json::SideClearCardMark（只认第一张卡带 y 430~600）。
SIDE_CARD_MARK_ROI = (0, 430, 720, 170)


def _center(box) -> tuple:
    """OCR 框 [x, y, w, h] -> 中心 (cx, cy)（720 空间）。"""
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _in_roi(box, roi) -> bool:
    cx, cy = _center(box)
    x, y, w, h = roi
    return x <= cx <= x + w and y <= cy <= y + h


def list_is_empty(items) -> bool:
    """「未通关」外传列表是否为空（画面有「未找到符合的外传故事」）。★纯函数★"""
    return any(SIDE_LIST_EMPTY in (t or "") for t, _b in items)


def first_card_box(items):
    """第一张外传卡的标记框（y 最靠上的「角色加入/装备获得」，限卡片 ROI）；没有则 None。

    ★读后动★：返回的是【识别到的框】，调用方点它的中心 —— 绝不写死 (540,720) 之类固定坐标。
    """
    cands = [
        list(b)
        for t, b in items
        if SIDE_CARD_MARK in (t or "") and b and len(b) == 4 and _in_roi(b, SIDE_CARD_MARK_ROI)
    ]
    if not cands:
        return None
    cands.sort(key=lambda b: _center(b)[1])
    return cands[0]


def has_stage_badge(items) -> bool:
    """画面上是否有 NEW/COMPLETE!! 徽标（= 这是外传【关卡列表】页，与 next_stage 的
    require_badge 同判据，单源不另造）。★纯函数★"""
    return any(
        (t or "").startswith("NEW") or (t or "").startswith("COMPLETE") for t, _b in items
    )


def entry_decision(items) -> tuple:
    """外传「进入第一张卡」的决策（★纯函数★，离线可单测，不碰设备）：

    返回 ``(decision, payload, reason)``，``decision`` ∈ ``{"enter", "stop"}``：
      · ``enter`` —— ``payload`` = 第一张卡标记框（点它的中心进入）；
      · ``stop``  —— ``payload`` = None，``reason`` 写明为什么【明确收工】（不静默、不盲点）。
    """
    if list_is_empty(items):
        return (
            "stop",
            None,
            f"「未通关」外传列表为空（画面：{SIDE_LIST_EMPTY}）→ 没有可进入的卡片 → "
            f"外传任务在此账号上无可推进，明确收工（绝不静默 hit=False、绝不盲点固定坐标）",
        )
    if not any(SIDE_LIST_TITLE in (t or "") for t, _b in items):
        return "stop", None, "当前不在「外传故事列表」页（缺列表标题）→ 明确收工（不盲点）"
    box = first_card_box(items)
    if box is None:
        return (
            "stop",
            None,
            f"外传故事列表上没有『{SIDE_CARD_MARK}』卡片标记（第一张卡带为空）→ "
            f"没有可点击的卡片 → 明确收工（绝不盲点固定坐标）",
        )
    return "enter", box, ""


def run_node(tasker: Tasker, name: str, timeout: float = 120.0) -> dict:
    """跑一个节点（动作 DoNothing、next 清空），返回识别结果摘要。

    #31 gap3：用有界的 ``ca.wait_job_bounded`` 取代裸 ``job.wait()`` —— 节点卡住时
    超时即请求停止并归还控制，绝不无限等待。
    """
    override = {name: {"action": {"type": "DoNothing", "param": {}}, "next": []}}
    job = tasker.post_task(name, override)
    ca.wait_job_bounded(tasker, job, timeout=timeout, label=name)
    detail = job.get()
    out = {"node": name, "hit": False, "box": None, "text": "", "raw_detail": None}
    if detail is None:
        return out
    for node in detail.nodes:
        reco = node.recognition
        if reco is None or not reco.hit:
            continue
        out["hit"] = True
        best = getattr(reco, "best_result", None)
        if best is not None:
            out["box"] = list(getattr(best, "box", []) or [])
            out["text"] = getattr(best, "text", "") or ""
        d = getattr(reco, "raw_detail", None)
        out["raw_detail"] = d if isinstance(d, dict) else None
        break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    ap.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="单个验证节点的等待上限秒数（#31：超时请求停止并归还控制，不无限等）",
    )
    a = ap.parse_args()

    # #40：先解析地址（缺省按账号身份发现）并打印实际设备身份（日志首行）+ 身份守卫；
    # #130：默认（WF_LIVE_EXPECT_* 全 unset）只记日志、**不校验型号**；显式设置才严格比较。
    # 连接仍走 #25 的唯一登记入口 connect_device(...)。
    # #perf：启动入口收敛到 ca.apply_global_options —— Toolkit.init_option + save_draw 默认关
    # （要临时抓帧设 WF_SAVE_DRAW=1）+ debug 产物上界（见 live_harness 里那一段的实测数字）。
    ca.apply_global_options(PROJECT)
    address = a.address or ca.resolve_address(ca.ADB, ca.expected_identity())
    ca.assert_device_identity(ca.ADB, address, ca.expected_identity())
    ctrl = ca.connect_device(ca.ADB, a.address)

    res = Resource()
    print("resource load:", res.post_bundle(str(ASSETS)).wait().succeeded)
    # ★ 进程内注册 pipeline 用到的全部自定义识别/动作（唯一注册源 live_harness，#20）
    ca.register_pipeline_customs(res)

    tasker = Tasker()
    tasker.bind(res, ctrl)
    watcher = ca.TitleWatcher(str(ASSETS))

    # 真机测试用独立的账本文件，避免污染正式 progress.json。
    pf = ca.WORK_DIR / "live_progress.json"
    if pf.exists():
        pf.unlink()
    ledger.set_file(pf)
    print("ledger file:", pf)

    try:
        if not ca.ensure_main_city(watcher):
            print("!! 未回主城")
            sys.exit(1)
        if not ca.goto_side_story_list(watcher):
            print("!! 导航到外传故事列表失败")
            sys.exit(1)
        print("== 点「未通关」==")
        ca.adb_tap(*ca.SIDE_UNPASSED)
        time.sleep(2.0)

        # ★#51★ 读后动：先看「未通关」列表到底是什么，再决定点哪张卡。
        # 空列表（未找到符合的外传故事）-> entry_decision 返回 stop + 原因 -> 明确收工。
        img0 = watcher.grab()
        items0 = watcher.ocr(img0)
        decision, payload, reason = entry_decision(items0)
        if decision != "enter":
            print("\n!! " + reason)
            print("!! 明确收工：绝不静默 hit=False、绝不盲点固定坐标")
            return
        card_box = payload

        print("== 进第一张外传卡（SideClearEnterCard）==")
        r = run_node(tasker, "SideClearEnterCard", a.timeout)
        # SideClearEnterCard 的 action 被覆盖成 DoNothing，这里需要真实点击卡片，
        # 所以直接点第一张卡固定位置（实测 720 (360,480) → 1080 (540,720)）。
        # ★#51★ 上面「固定坐标」的点击已【被取代】：改为点【识别到的第一张卡标记框中心】
        #   —— 真机 relayB 证明盲点 (540,720) 什么都进不去，任务却静默地什么都没做。
        ccx, ccy = _center(card_box)
        print(f"   读到第一张卡标记 @{card_box}（中心 ({ccx:.0f},{ccy:.0f})）-> 点它")
        ca.adb_tap(ccx, ccy)
        time.sleep(3.0)

        img = watcher.grab()
        Image.fromarray(img[:, :, ::-1]).save(ca.WORK_DIR / "live_stage_list.png")
        print("已抓屏 live_stage_list.png")
        # ★#51★ 进入后复核：画面确有 NEW/COMPLETE!! 徽标才说明真在【外传关卡列表】；
        #   否则明确收工（绝不把「没进到关卡列表」伪装成「三个节点 hit=False」）。
        items1 = watcher.ocr(img)
        if not has_stage_badge(items1):
            print("\n!! 进入卡片后画面没有 NEW/COMPLETE 徽标 = 不是外传关卡列表")
            print("!! 明确收工（绝不静默 hit=False、绝不对陈旧/非列表页取证）")
            return

        print("\n---- 三个账本驱动节点在【真实关卡列表】上的识别结果 ----")
        results = {}
        for name in ("SideNextSpecial", "SideNextStory", "SideNextBattle"):
            r = run_node(tasker, name, a.timeout)
            results[name] = r
            print(f"  {name:16} hit={r['hit']} box={r['box']} text={r['text']!r}")
            if isinstance(r["raw_detail"], dict):
                print(f"      detail: scope={r['raw_detail'].get('scope')!r} stage={r['raw_detail'].get('stage')!r} "
                      f"type={r['raw_detail'].get('type')!r}")

        # 找到一个命中的关卡 -> 记账 -> 复跑，确认不重复。
        # next_stage 的 detail 通过 raw_detail 结构不稳定，这里用「命中框 -> 重新 OCR
        # 解析出关卡名 + scope」的方式拿准确目标，保证演示可信。
        from stage_rows import detect_scope, parse_side_rows

        def derive(box):
            job = tasker.post_task("OcrTask", {})
            job.wait()
            det = job.get()
            items = []
            for n in det.nodes:
                r = n.recognition
                if r is None:
                    continue
                for x in (r.all_results or []):
                    items.append((x.text.strip(), [int(v) for v in x.box]))
            for row in parse_side_rows(items):
                if list(row["title_box"]) == list(box):
                    return detect_scope(items), row["name"], row["type"]
            return detect_scope(items), None, None

        picked = None
        for name in ("SideNextSpecial", "SideNextStory", "SideNextBattle"):
            if results[name]["hit"] and results[name]["box"]:
                scope, stage, typ = derive(results[name]["box"])
                picked = (name, scope, stage, typ)
                break

        if not picked or picked[2] is None:
            print("\n!! 三个节点都没命中可解析的关卡行（该外传列表结构与预期不同）")
            # ★#51★ 已确认「进入了外传关卡列表」（有 NEW/COMPLETE 徽标）却仍选不出一关 ->
            #   按票面要求【明确停下并给出原因】，绝不静默 hit=False、绝不对陈旧页记账。
            print("!! 明确收工：已在关卡列表但账本驱动选关未命中（原因见上），不静默、不记账")
        else:
            name, scope, stage, typ = picked
            print(f"\n---- 账本防重复：把 {scope}/{stage}（{typ}）记为完成，再跑 {name} ----")
            ledger.mark_done(ledger.make_key("side_story", scope, stage))
            ledger.clear_pending()
            r2 = run_node(tasker, name, a.timeout)
            same_box = r2["hit"] and list(r2["box"]) == list(results[name]["box"])
            print(f"  记账后再跑: hit={r2['hit']} box={r2['box']}（原 box={results[name]['box']}）")
            if same_box:
                print("  [FAIL] 仍然返回同一关！")
            else:
                print("  [PASS] 不再返回同一关（账本生效）")
            print("  账本内容:", ledger.all_keys())

    finally:
        print("\n== 收尾：导航回主城 ==")
        try:
            ca.ensure_main_city(watcher)
        except Exception as exc:  # noqa: BLE001
            print("回主城异常:", exc)


if __name__ == "__main__":
    main()
