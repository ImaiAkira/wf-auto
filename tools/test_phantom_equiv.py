# -*- coding: utf-8 -*-
"""离线等价性探针：在 main 与特性分支上各跑一次，对比「除新功能外」的判定输出。

用法（两个 worktree 各跑一次，再 diff 输出）：
    .venv\\Scripts\\python.exe tools\\test_phantom_equiv.py

它只覆盖【旧行为】：(1) 单目标：正常逐关 -> 套数收工；(2) 会话内进度重置；
(3) 进入下一套第 1 关不误判；(4) 批量 override 的结构。
★刻意不覆盖「中途接管 + 旧账本更靠后」与「关卡上限」——那正是本次新功能，预期不同。★
输出为确定性 JSON（排序键），跨版本可直接 diff。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
sys.path.insert(0, str(AGENT_DIR))

import progress as ledger  # noqa: E402
import phantom_impl as ph  # noqa: E402

OUT: dict = {}


class _TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class _Argv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = _TaskDetail(task_id)
        self.custom_recognition_param = json.dumps(param)


def _main_items(stage: int):
    return [
        ("不可续战", [300, 980, 90, 30]),
        ("推荐编成", [55, 1105, 97, 29]),
        ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
        (f"第{stage}关", [345, 131, 90, 30]),
        ("战斗", [300, 700, 60, 30]),
    ]


def _force_observe():
    with ph._LOCK:
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0


def _observe_main(task_id, stage):
    _force_observe()
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(stage))
    return ph.PhantomStateRecognition().analyze(None, _Argv(task_id, {"ocr_entry": "OcrTask"}))


def _play_stage(task_id, stage):
    _observe_main(task_id, stage)
    with ph._LOCK:
        ph._SESSION["in_fight"] = True
        ph._SESSION["cur_stage"] = stage
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0
    ph._observe("phantom_settle", {}, [])


def _snap():
    with ph._LOCK:
        s = {
            "cur_set": ph._SESSION["cur_set"],
            "cur_stage": ph._SESSION["cur_stage"],
            "max_done": ph._SESSION["max_done"],
            "completed_sets": ph._SESSION["completed_sets"],
            "in_fight": ph._SESSION["in_fight"],
        }
    return {"session": s, "set_keys": ledger.scope("phantom/set")}


def _done_hit(task_id, target):
    ph._ocr = lambda context, image, entry="OcrTask": list(_main_items(3))
    res = ph.PhantomDoneRecognition().analyze(
        None, _Argv(task_id, {"ocr_entry": "OcrTask", "target_sets": target})
    )
    return {"box": res.box, "detail": res.detail}


def probe() -> None:
    # ---- 1) 单目标：空账本逐关 1..15 -> 一套完成 -> 目标 1 命中 ----
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "p.json")
        ph._SESSION["task_id"] = None
        for st in range(1, 16):
            _play_stage(1001, st)
        OUT["s1_after_15"] = _snap()
        OUT["s1_done_target1"] = _done_hit(1001, 1)
        OUT["s1_done_target3"] = _done_hit(1001, 3)

    # ---- 2) 会话内进度重置：空账本打到 7 -> 回第 1 关 -> 清当前套 ----
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "p.json")
        ph._SESSION["task_id"] = None
        for st in range(1, 8):
            _play_stage(2002, st)
        OUT["s2_before_reset"] = _snap()
        _observe_main(2002, 1)
        OUT["s2_after_reset"] = _snap()

    # ---- 3) 进入下一套第 1 关不误判（残留 15 帧 -> set2 第 1 关）----
    with tempfile.TemporaryDirectory() as d:
        ledger.set_file(Path(d) / "p.json")
        ph._SESSION["task_id"] = None
        for st in range(1, 16):
            _play_stage(3003, st)
        _observe_main(3003, 15)   # 残留帧
        OUT["s3_residual15"] = _snap()
        _observe_main(3003, 1)    # 正常进入 set2 第 1 关
        OUT["s3_set2_stage1"] = _snap()

    # ---- 4) 批量 override 结构（纯函数，应与合并后一致）----
    try:
        import side_impl as si  # noqa: E402
        import batch_plan as bp  # noqa: E402

        item = bp.BatchItem("幻想连战", "-", 2, kind="phantom")
        OUT["s4_phantom_override"] = si._phantom_override(item)
    except Exception as exc:  # noqa: BLE001
        OUT["s4_error"] = repr(exc)


if __name__ == "__main__":
    probe()
    print(json.dumps(OUT, ensure_ascii=False, sort_keys=True, indent=2))
