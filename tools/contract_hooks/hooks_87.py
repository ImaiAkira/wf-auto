# -*- coding: utf-8 -*-
"""#87：「当前不满足出战条件」弹窗 —— 认得 + 带原因收工（别再当 unknown 空转）。

## 真机现场（设备 16448，帧 `debug/wc448_popup_ready.png`）

pipeline OCR（720 空间）：

```
'当前不满足出战条件。'                    [218, 501, 266, 32]
'请检查关卡开放状态、入场门票和队伍限制。'   [80, 540, 539, 32]
'幻想连战专属装备及魂珠仅限幻想连战使用，'   [79, 577, 543, 31]
'挑战其他关卡前请先卸下或更换。'           [148, 613, 405, 31]
'OK'                                    [334, 805, 51, 37]
```

判据取**整句**「当前不满足出战条件」（不用「不满足」这种宽串）；命中即 `wuchong_no_entry`，
由 `wuchong_giveup` 立刻带原因收工（`StopTask`，**不点 OK** —— 这框就是给运维看的）。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


#: ★#87★ 真机那一帧的 OCR 逐字（720 空间，来自 debug/wc448_popup_ready.png）。
POPUP_ITEMS = [
    ("幻想连战专属装备及魂珠仅限幻想连战使用，", [79, 577, 543, 31]),
    ("请检查关卡开放状态、入场门票和队伍限制。", [80, 540, 539, 32]),
    ("挑战其他关卡前请先卸下或更换。", [148, 613, 405, 31]),
    ("当前不满足出战条件。", [218, 501, 266, 32]),
    ("OK", [334, 805, 51, 37]),
]


class _RecArgv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


def _classify_failures(mod) -> list:
    msgs: list[str] = []
    state, _info = mod.classify(list(POPUP_ITEMS))
    if state != mod.WUCHONG_NO_ENTRY:
        msgs.append(f"真机弹窗帧没被认成 wuchong_no_entry（现 {state!r}）→ 会当 unknown 空转")
    # 反向：只有「不满足」三个字（别的句子）不得命中（宽串会误伤）
    other = [("背包不满足强化条件", [10, 10, 200, 30])]
    st2, _i2 = mod.classify(other)
    if st2 == mod.WUCHONG_NO_ENTRY:
        msgs.append("宽串误判：只有「不满足」三个字就当成 no_entry 弹窗（判据必须是整句）")
    # 弹窗也不能吞掉正常页
    battle = [("时间 29:30 分数 38629797530", [34, 1220, 400, 40])]
    st3, _i3 = mod.classify(battle)
    if st3 != mod.WUCHONG_BATTLE:
        msgs.append(f"战斗帧被 no_entry 判据影响（现 {st3!r}）")
    return msgs


def probe_wuchong_no_entry_popup() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _classify_failures(impl) == []


def _giveup_failures(mod) -> list:
    msgs: list[str] = []
    real_ocr = mod._ocr
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    td = tempfile.mkdtemp(prefix="wf_hook87_")
    mod.ledger.set_file(Path(td) / "p.json")
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(POPUP_ITEMS)
        with mod._LOCK:
            mod._SESSION["task_id"] = 570_600_001
            mod._SESSION["start_ts"] = time.monotonic()
            mod._SESSION["last_progress_ts"] = time.monotonic()
            mod._SESSION["room_first_ts"] = 0.0
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
            mod._SESSION["unknown_count"] = 0
            mod._SESSION["unknown_streak"] = 0
            mod._SESSION["fights_done"] = 0
            mod._SESSION["in_fight"] = False
            mod._SESSION["battle_had_continue"] = False
            mod._SESSION["remaining_plays"] = None
            mod._SESSION["said_target"] = False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = mod.WuchongGiveUpRecognition().analyze(
                None,
                _RecArgv(570_600_001, {"ocr_entry": "OcrTask", "room_wait_sec": 300,
                                        "no_progress_sec": 900, "target_fights": 0}),
            )
        hit = res.box == [0, 0, 0, 0]
        reason = str((res.detail or {}).get("reason") or "")
        out = buf.getvalue()
        if not hit:
            msgs.append("弹窗在屏时 wuchong_giveup 没命中 → 会继续空转（不会收工）")
        else:
            if "门票" not in reason:
                msgs.append(f"收工原因没点明『门票』：{reason!r}（运维裁决：这一屏一律当门票不够）")
            if len(reason) > 24:
                msgs.append(f"用户可见原因太长（运维要一句人话，细节进日志）：{reason!r}")
        if "五重决战：收工" not in out:
            msgs.append(f"用户可见行没打出来：{out.strip()[:120]!r}")
        if "门票不够了" not in out:
            msgs.append(f"用户可见行没说到『门票不够了』：{out.strip()[:120]!r}")
        # 细节不许刷用户界面（只有 _say 那行 + 非静音时的机制日志；这里断言 _say 行本身很短）
        said = [ln for ln in out.splitlines() if ln.startswith("五重决战：")]
        if said and any(len(ln) > 40 for ln in said):
            msgs.append(f"用户可见行过长（应只有一句）：{said}")
    finally:
        mod._ocr = real_ocr
        mod.ledger.set_file(None)
        if saved_file is not None:
            mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_no_entry_giveup() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _giveup_failures(impl) == []


HOOKS = [
    (
        "wuchong-no-entry-popup",
        "#87",
        "「当前不满足出战条件」弹窗认得（**整句**判据；只有『不满足』三字不误判；战斗帧不受影响）"
        "—— 真机帧 debug/wc448_popup_ready.png，旧实现判 unknown 会空转",
        probe_wuchong_no_entry_popup,
    ),
    (
        "wuchong-no-entry-giveup",
        "#87",
        "弹窗在屏 → wuchong_giveup 立刻命中并**中止任务**，用户可见只有一句『门票不够了』（细节进日志）；"
        "用户可见行『五重决战：收工 —— …』照常打出",
        probe_wuchong_no_entry_giveup,
    ),
]


# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_87 prove-red：逐一破坏实现，要求守卫各自变红")
    green = probe_wuchong_no_entry_popup() is True and probe_wuchong_no_entry_giveup() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：两个守卫全绿")
    if not green:
        for m in _classify_failures(impl) + _giveup_failures(impl):
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    def _set_no_entry_text(text):
        """改「弹窗整句」判据 —— ★#119★ 判据已收进 SceneConfig（classify 是薄封装），
        故破坏点从模块全局搬到配置字段（frozen dataclass 用 object.__setattr__ 绕过，
        与 prove-red「只造坏件、不改真文件」同一口径）。
        """
        object.__setattr__(impl._CLASSIFY_CFG, "no_entry_text", text)

    # ① 判据放宽成「不满足」→ 反向用例必红
    real_text = impl._CLASSIFY_CFG.no_entry_text
    try:
        _set_no_entry_text("不满足")
        m1 = _classify_failures(impl)
        red1 = len(m1) > 0
        print(f"  [{'PASS' if red1 else 'FAIL'}] 判据放宽成「不满足」（宽串）-> {'红' if red1 else '仍绿'}"
              + (f"  {m1[0]}" if m1 else ""))
    finally:
        _set_no_entry_text(real_text)
    checks.append(red1)

    # ② 判据写错（认不出来）→ 两个用例都红
    try:
        _set_no_entry_text("永远不会出现的句子")
        m2 = _classify_failures(impl)
        red2 = len(m2) > 0
        print(f"  [{'PASS' if red2 else 'FAIL'}] 判据写错（认不出弹窗）-> {'红' if red2 else '仍绿'}"
              + (f"  {m2[0]}" if m2 else ""))
    finally:
        _set_no_entry_text(real_text)
    checks.append(red2)

    # ③ 去掉「弹窗 → 收工原因」这条缝（等价于删掉 give-up 的 no_entry 分支）→ 必须红
    real_state = getattr(impl, "_no_entry_reason", None)
    try:
        impl._no_entry_reason = lambda: None
        m3 = _giveup_failures(impl)
        red3 = len(m3) > 0
        print(f"  [{'PASS' if red3 else 'FAIL'}] 去掉 giveup 的 no_entry 原因分支 -> {'红' if red3 else '仍绿'}"
              + (f"  {m3[0]}" if m3 else ""))
    finally:
        impl._no_entry_reason = real_state
    checks.append(red3)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
