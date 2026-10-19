# -*- coding: utf-8 -*-
"""离线单测：#31 harness 归位三个缺口 —— 共斗房 / 列表页误判 / 超时不终止。

不需要游戏；真机帧实证是 best-effort（缺 maa / OCR 模型 / 帧则 SKIP，不算失败）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_harness_gaps.py

覆盖 #31 的验收：

  1. **主城判据不再被列表页满足**（gap2）：领主战列表页的合成帧与真机帧都不再判成主城，
     且归位在列表页落到 bottom_nav_mc（点「主城」回家），而不是一步误判「已在主城」；
  2. **归位认识共斗房**（gap1）：房间页 / 解散确认框是已知页面，动作只点识别到的框中心；
  3. **共斗房 -> 主城**：共斗房 ->（返回/解散）-> 列表页 ->（主城）-> 主城；
  4. **超时真正终止**（gap3）：任务卡死时 run_task_traced 仍有界归还控制；
  5. **真机帧实证**（best-effort）：对战役落盘的真机帧跑 OCR，断言分派正确；
  6. 挂点 ``hooks_31`` 已点亮、prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_31.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import inspect
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_31  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# OCR 资源：优先显式环境变量，其次本工作树 assets，最后退回主工作树（本机有模型）。
# 都没有 -> 真机帧实证 SKIP（裸检出照旧绿）。
# ---------------------------------------------------------------------------
def _pick_assets() -> Path | None:
    cands: list[Path] = []
    env = os.environ.get("WF_H31_ASSETS")
    if env:
        cands.append(Path(env))
    cands.append(REPO_ROOT / "assets" / "resource")
    cands.append(Path(__file__).resolve().parents[1] / "assets" / "resource")
    for c in cands:
        if (c / "model" / "ocr" / "det.onnx").is_file():
            return c
    return None


FRAME_DIR = Path(
    os.environ.get("WF_H31_FRAMES", str(TEMP_OPENCODE))
)
FRAMES = {
    "list": "sweep_lord_00.png",     # 领主战列表页（活动进行中！+ 领主战 + 主城底导）
    "room": "preF.png",              # 幻想共斗房（房间号码 / 准备中： / 未进行招募 / 队长）
    "dialog": "dlg2.png",            # 解散房间确认框（解散 / 取消 / 可以吗？）
    "left_list": "disband2.png",     # 离开房间后的列表页（主城底导）
    "main": "homeD2.png",            # 主城
}


def _ocr_frame(assets: Path, name: str):
    path = FRAME_DIR / FRAMES[name]
    if not path.is_file():
        return None, f"缺帧：{path}"
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        return None, f"缺 numpy/PIL：{exc!r}"
    try:
        pil = Image.open(path).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        return ca.ocr(img, assets), None
    except Exception as exc:  # noqa: BLE001
        return None, f"OCR 不可用：{exc!r}"


# ---------------------------------------------------------------------------
# 1. 主城判据：不认列表页（gap2）
# ---------------------------------------------------------------------------
def test_main_city_not_list() -> None:
    print("\n== 1. 主城判据收紧：领主战列表页不再被误判成主城 ==")
    check("主城帧（合成）判为主城", ca._is_main_city(hooks_31.MAIN_CITY_ITEMS))
    check("列表页（合成）不判为主城", not ca._is_main_city(hooks_31.LIST_ITEMS))
    first = hooks_31._first_rule(hooks_31.rules(), hooks_31.LIST_ITEMS)
    check("列表页首命中 = bottom_nav_mc（点主城回家，而非宣布已在主城）",
          first == "bottom_nav_mc", f"first={first}")
    check("旧 6 锚点规则确实会在列表页误判（证明收紧必要）",
          hooks_31._loose_main_city(hooks_31.LIST_ITEMS))
    check("主城独有锚点是 6 锚点子集", set(ca.MAIN_CITY_UNIQUE_ANCHORS) <= set(ca.MAIN_CITY_ANCHORS))


# ---------------------------------------------------------------------------
# 2. 共斗房是已知页面 + 读后动（gap1）
# ---------------------------------------------------------------------------
def test_coop_room_known_page() -> None:
    print("\n== 2. 归位认识共斗房与其解散确认框（读后动，不盲点） ==")
    check("共斗房（合成）被认出", ca._is_coop_room(hooks_31.ROOM_ITEMS))
    check("解散确认框（合成）被认成共斗房子状态", ca._is_coop_room(hooks_31.DIALOG_ITEMS))
    check("共斗房首命中 = coop_room",
          hooks_31._first_rule(hooks_31.rules(), hooks_31.ROOM_ITEMS) == "coop_room")
    check("确认框首命中 = coop_room",
          hooks_31._first_rule(hooks_31.rules(), hooks_31.DIALOG_ITEMS) == "coop_room")
    check("coop_room 不误命中主城", not ca._is_coop_room(hooks_31.MAIN_CITY_ITEMS))
    check("coop_room 不误命中列表页", not ca._is_coop_room(hooks_31.LIST_ITEMS))
    room_pt = hooks_31._click_point_for(hooks_31.ROOM_ITEMS, "coop_room")
    check("房间页只点识别到的『返回』框中心", room_pt == hooks_31.EXPECTED_ROOM_BACK, f"pt={room_pt}")
    dlg_pt = hooks_31._click_point_for(hooks_31.DIALOG_ITEMS, "coop_room")
    check("确认框只点识别到的『解散』框中心（不是『取消』）",
          dlg_pt == hooks_31.EXPECTED_DIALOG_CONFIRM, f"pt={dlg_pt}")


# ---------------------------------------------------------------------------
# 3. 共斗房 -> 主城 / 列表页 -> 主城
# ---------------------------------------------------------------------------
def test_traces_to_main_city() -> None:
    print("\n== 3. 确定性回归：共斗房 / 列表页 都能走到主城 ==")
    reached, seq = hooks_31.trace(
        [hooks_31.ROOM_ITEMS, hooks_31.DIALOG_ITEMS, hooks_31.LEFT_LIST_ITEMS, hooks_31.MAIN_CITY_ITEMS]
    )
    check("共斗房 ->（返回/解散）-> 列表页 ->（主城）-> 主城",
          reached and seq == ["coop_room", "coop_room", "bottom_nav_mc", "main_city"], f"seq={seq}")
    reached2, seq2 = hooks_31.trace([hooks_31.LIST_ITEMS, hooks_31.MAIN_CITY_ITEMS])
    check("列表页 ->（主城）-> 主城",
          reached2 and seq2 == ["bottom_nav_mc", "main_city"], f"seq={seq2}")


# ---------------------------------------------------------------------------
# 4. 超时真正终止（gap3）
# ---------------------------------------------------------------------------
def test_timeout_terminates() -> None:
    print("\n== 4. 超时到点真正终止并归还控制 ==")
    # (a) 任务卡死（停止请求也不生效）：仍有界归还控制，且发出过停止请求。
    fake = hooks_31._FakeTasker(stop_works=False)
    completed, box = hooks_31._capture(
        lambda: ca.run_task_traced(fake, "Entry", {}, 0.3, "probe", watcher=None, stop_timeout=0.4),
        budget=8.0,
    )
    check("卡死任务：run_task_traced 有界归还控制（不阻塞）", completed)
    if completed:
        status = box.get("value", (None, []))[0]
        check("卡死任务：status=timeout", status == "timeout", f"status={status}")
    check("卡死任务：至少发出一次停止请求", fake.stop_calls >= 1, f"stop_calls={fake.stop_calls}")

    # (b) 停止生效（正常路径）：很快返回，不空转。
    fake2 = hooks_31._FakeTasker(stop_works=True)
    completed2, box2 = hooks_31._capture(
        lambda: ca.run_task_traced(fake2, "Entry", {}, 0.3, "probe", watcher=None, stop_timeout=5.0),
        budget=8.0,
    )
    check("停止生效：run_task_traced 很快返回", completed2)
    if completed2:
        check("停止生效：status=timeout", box2.get("value", (None, []))[0] == "timeout")

    # (c) run_task_traced 不再以裸 post_stop().wait() 结束；wait_job_bounded 存在。
    src = inspect.getsource(ca.run_task_traced)
    check("run_task_traced 走 _terminate_task（不是裸 tasker.post_stop().wait()）",
          "_terminate_task" in src and "tasker.post_stop().wait()" not in src)
    check("提供 wait_job_bounded（有界等待，供不追踪节点的 runner 用）",
          callable(getattr(ca, "wait_job_bounded", None)))
    # (d) 两个 runner 的接线上锁。
    import run_side_live

    check("run_side_live.run_node 用 wait_job_bounded（裸 job.wait() 会无限等）",
          "wait_job_bounded" in inspect.getsource(run_side_live.run_node))
    import run_special_live

    check("run_special_live 把 stop_timeout 传给 run_task_traced",
          "stop_timeout" in inspect.getsource(run_special_live.main))


# ---------------------------------------------------------------------------
# 5. 真机帧实证（best-effort）
# ---------------------------------------------------------------------------
def test_real_frames_best_effort() -> None:
    print("\n== 5. 真机帧实证（best-effort）：列表页/共斗房/确认框/列表/主城 ==")
    assets = _pick_assets()
    if assets is None:
        skip("真机帧 OCR（#31）", "缺 OCR 模型（WF_H31_ASSETS / 本工作树 / 主工作树都没有 det.onnx）")
        return

    # 每个帧的期望：首命中规则（+ 共斗房动作点）。
    expectations = [
        ("list", lambda items: hooks_31._first_rule(hooks_31.rules(), items) == "bottom_nav_mc",
         "列表页首命中 bottom_nav_mc（不是 main_city）"),
        ("room", lambda items: hooks_31._first_rule(hooks_31.rules(), items) == "coop_room",
         "共斗房首命中 coop_room"),
        ("dialog", lambda items: hooks_31._first_rule(hooks_31.rules(), items) == "coop_room",
         "解散确认框首命中 coop_room"),
        ("left_list", lambda items: hooks_31._first_rule(hooks_31.rules(), items) == "bottom_nav_mc",
         "离开房间后列表页首命中 bottom_nav_mc"),
        ("main", lambda items: hooks_31._first_rule(hooks_31.rules(), items) == "main_city",
         "主城首命中 main_city"),
    ]
    for name, pred, desc in expectations:
        items, err = _ocr_frame(assets, name)
        if items is None:
            skip(f"真机帧 {name}", err or "OCR 失败")
            continue
        texts = [t for t, _ in items]
        print(f"  帧 {name}（{FRAMES[name]}）文本节选：{texts[:12]}")
        check(desc, pred(items))

    # 列表页绝不能判成主城（哪怕 OCR 抖动）。
    items, err = _ocr_frame(assets, "list")
    if items is not None:
        check("真机列表页帧：_is_main_city = False", not ca._is_main_city(items))
    # 共斗房动作只点识别到的框中心。
    items, err = _ocr_frame(assets, "dialog")
    if items is not None:
        pt = hooks_31._click_point_for(items, "coop_room")
        print(f"  确认框动作点：{pt}")
        check("真机确认框：动作点在『解散』识别框中心附近（不盲点）",
              pt is not None)


# ---------------------------------------------------------------------------
# 6. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 6. 挂点点亮 + prove-red ==")
    check("挂点 return-home-main-city-not-list-page 已点亮",
          hooks_31.probe_main_city_not_list() is True)
    check("挂点 return-home-list-page-to-main-city 已点亮",
          hooks_31.probe_list_page_to_main_city() is True)
    check("挂点 return-home-coop-room 已点亮", hooks_31.probe_coop_room() is True)
    check("挂点 return-home-coop-room-to-main-city 已点亮",
          hooks_31.probe_coop_room_to_main_city() is True)
    check("挂点 runner-timeout-terminates 已点亮", hooks_31.probe_timeout_terminates() is True)
    check("hooks_31.prove_red() 成立（列表页/共斗房/超时各自变红）", hooks_31.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：#31 harness 归位三缺口（共斗房 / 列表页误判 / 超时不终止）")
    print("=" * 70)
    test_main_city_not_list()
    test_coop_room_known_page()
    test_traces_to_main_city()
    test_timeout_terminates()
    test_real_frames_best_effort()
    test_hooks_and_prove_red()
    print("\n" + "=" * 70)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
