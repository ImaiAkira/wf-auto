# -*- coding: utf-8 -*-
"""#86：五重「用户可见输出」与「门票用尽/错误弹窗」两条契约。

## 运维要求（逐字）

1. 「五重**门票如果用完了**，他会有**错误提示弹窗**…你可以从 448 上多打几次」
2. 「你的五重输出到用户的界面上有**很多乱七八糟的东西**，你只要告诉用户**要打几次、这是第几次**就好了」

## 真机事实（设备 16448 = 448）

- ★体例更正（2026-10-17 22:2x 只读核查）★：21:12–21:38 拉下的 `debug/wc448_*.png` 原始帧是
  **1080x1920**，那批 OCR box 是**原图像素**；只有 runner 的 `--dump-ocr` 才是 720 空间。
  本守卫的判据只比对**文本**（`今天剩余次数 [x×] N`），不依赖 box，所以不受影响。
- ★坐标系澄清（#99）★：本文件下面的 `_MODE_NO_TICKET` / `_MODE_TICKETS` 里那条
  `[381, 922, 319, 42]` 就是上面那批**原图像素**（1080 空间），**不是** 720 识别空间；
  按 ÷1.5 折过去是 `[254, 614.7, 212.7, 28]`。它们只是喂给 `_ocr` 桩的假 OCR 结果、
  判据又只比对文本，所以这里**保持原值**（改判据是另一张票的事）。
  换算真源见 `scene/pixels.py`（`box_to_base()` / `scale_factor()`）；`tools/ocr_image.py`
  因为 `set_screenshot_use_raw_size(True)` 固有地输出**原图** box，读它必须先归一。
  新写任何 OCR box 一律先标明/归一坐标空间（守卫 `hooks_99.*`）。
- 门票 = **`今天剩余次数 x N`**（OCR：模式页底部 `今天剩余次数x 3`，原图 box `[381,922,319,42]`）；
  该号 `体力 1859/101`（体力不是瓶颈）；每点一次【挑战】烧 1 次。

- ★会话归属（22:2x 更正）★：`install/logs/log-20261017.log` 与 `debug/wc_solo_*.log` 全部是
  **A（16384）**；B（16448）今晚只被读过门票数（`今天剩余次数x 3`，21:13），没有自动化跑过。
  所以「打 6 把后卡房 302s」那件事发生在 A 上。

## 契约

- **W1 门票用尽 → 带原因收工**：每轮判据解析 `今天剩余次数 [x×] N`；`N<=0` 立刻收工，
  原因含「剩余次数」；★绝不靠「点一次挑战再看弹窗」发现★（点一次白烧一张票）。
- **W2 认不出的错误弹窗 → 停手**：`unknown` **连续** ≥ `UNKNOWN_MODAL_LIMIT` 且画面含
  `剩余次数|不足|错误|失败|无法挑战|已达上限` → 带原因收工，**不点任何按钮**。
- **W3 用户可见输出只有 4 类**（`_say`）：`要打 N 次` / `第 i/N 次 开始` / `第 i/N 次 完成` / `收工 —— 原因`；
  机制日志走 `_log`（QUIET 时不进 stdout，落 `debug/wuchong_agent.log`）。
- **W4 GUI 走静音**：`assets/interface.json` 的 `agent.child_args` 必须带 `--quiet`；
  `agent/main.py` 见到 `--quiet` 就 `wuchong_impl.set_quiet(True)`。
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


def _iface() -> dict:
    import jsonc  # noqa: PLC0415

    with open(REPO_ROOT / "assets" / "interface.json", encoding="utf-8") as f:
        return jsonc.load(f)


class _RecArgv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


_ROOM_ITEMS = [("房间号码", [100, 300, 200, 40]), ("招募", [400, 900, 80, 40]), ("未进行招募", [200, 700, 160, 40])]
_MODE_NO_TICKET = [("今天剩余次数x 0", [381, 922, 319, 42]), ("单人游戏", [100, 700, 150, 40])]
_MODE_TICKETS = [("今天剩余次数x 3", [381, 922, 319, 42]), ("单人游戏", [100, 700, 150, 40])]


def _drive_giveup(mod, items, *, task_id=570_500_001, params=None, reset_streak=True, room_waited=0.0):
    """跑一次真实 wuchong_giveup 识别，返回 (hit, reason, stdout)。"""
    real_ocr = mod._ocr
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    td = tempfile.mkdtemp(prefix="wf_hook86_")
    mod.ledger.set_file(Path(td) / "p.json")
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(items)
        with mod._LOCK:
            mod._SESSION["task_id"] = task_id
            mod._SESSION["start_ts"] = time.monotonic()
            mod._SESSION["last_progress_ts"] = time.monotonic()
            mod._SESSION["room_first_ts"] = (time.monotonic() - float(room_waited)) if room_waited else 0.0
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
            mod._SESSION["unknown_count"] = 0
            if reset_streak:
                mod._SESSION["unknown_streak"] = 0
            mod._SESSION["fights_done"] = 0
            mod._SESSION["battle_had_continue"] = False
            mod._SESSION["in_fight"] = False
            mod._SESSION["remaining_plays"] = None
            mod._SESSION["said_target"] = False
            mod._SESSION["settle_said"] = False
            mod._SESSION["remote_beat_ts"] = 0.0
            mod._SESSION["room_beat_ts"] = 0.0
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = mod.WuchongGiveUpRecognition().analyze(
                None, _RecArgv(task_id, dict(params or {"ocr_entry": "OcrTask", "room_wait_sec": 300,
                                                       "no_progress_sec": 900}))
            )
        hit = res.box == [0, 0, 0, 0]
        return hit, str((res.detail or {}).get("reason") or ""), buf.getvalue()
    finally:
        mod._ocr = real_ocr
        mod.ledger.set_file(None)
        if saved_file is not None:
            mod.ledger._DEFAULT = saved_file


# ---------------------------------------------------------------------------
# W1：门票用尽 → 收工
# ---------------------------------------------------------------------------
def _ticket_failures(mod) -> list:
    msgs: list[str] = []
    hit0, reason0, _out0 = _drive_giveup(mod, _MODE_NO_TICKET)
    if not hit0:
        msgs.append("看到「今天剩余次数x 0」仍未收工（会白烧票 / 空等）")
    elif "剩余次数" not in reason0:
        msgs.append(f"收工原因没点明门票：{reason0!r}")
    hit3, _r3, _o3 = _drive_giveup(mod, _MODE_TICKETS, task_id=570_500_002)
    if hit3:
        msgs.append("「今天剩余次数x 3」还有票就收工了（误收工）")
    # W4：剩余次数要记进 session，供输出/后续使用
    with mod._LOCK:
        seen = mod._SESSION.get("remaining_plays")
    if seen != 3:
        msgs.append(f"剩余次数未记入 session：{seen!r}（应为 3）")
    return msgs


def probe_wuchong_ticket_exhausted() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _ticket_failures(impl) == []


# ---------------------------------------------------------------------------
# W2：认不出的错误弹窗 → 停手（不点击）
# ---------------------------------------------------------------------------
def _modal_failures(mod) -> list:
    msgs: list[str] = []
    popup = [("挑战次数不足", [200, 600, 300, 40]), ("OK", [330, 900, 80, 40])]
    hits = []
    for i in range(mod.UNKNOWN_MODAL_LIMIT + 1):
        hit, reason, _out = _drive_giveup(mod, popup, task_id=570_500_100, reset_streak=(i == 0))
        hits.append((hit, reason))
    if not any(h for h, _r in hits):
        msgs.append(
            f"连续 {mod.UNKNOWN_MODAL_LIMIT + 1} 次认不出画面且带「挑战次数不足」仍未收工"
            "（会一直空转/乱点）"
        )
    elif "错误提示" not in next(r for h, r in hits if h):
        msgs.append(f"收工原因没点明『错误提示』：{next(r for h, r in hits if h)!r}")
    # 没有错误关键词的 unknown → 不许收工（别把正常过场当弹窗）
    hits2 = []
    for i in range(mod.UNKNOWN_MODAL_LIMIT + 1):
        hit2, _r2, _o2 = _drive_giveup(
            mod, [("随便什么画面", [10, 10, 200, 40])], task_id=570_500_200, reset_streak=(i == 0)
        )
        hits2.append(hit2)
    if any(hits2):
        msgs.append("没有错误关键词的 unknown 画面也收工了（会把正常过场当弹窗）")
    return msgs


def probe_wuchong_error_modal() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _modal_failures(impl) == []


# ---------------------------------------------------------------------------
# W3 + W4：用户可见输出只有 4 类；GUI 走 --quiet
# ---------------------------------------------------------------------------
_USER_LINE = ("五重决战：",)


def _output_failures(mod) -> list:
    msgs: list[str] = []
    # W4 接线
    iface = _iface()
    args = list((iface.get("agent") or {}).get("child_args") or [])
    if "--quiet" not in args:
        msgs.append(f"interface.json 的 agent.child_args 没有 --quiet（GUI 会继续刷机制日志）：{args}")
    main_src = (REPO_ROOT / "agent" / "main.py").read_text(encoding="utf-8")
    if "--quiet" not in main_src or "set_quiet" not in main_src:
        msgs.append("agent/main.py 没有处理 --quiet（set_quiet）")

    # W3：静音模式下跑一轮判据，stdout 只能有用户行
    real_quiet = mod.QUIET
    try:
        mod.set_quiet(True)
        # 用房等心跳（``_log``）当探针：房间已等 40s → 非静音必打「共斗房等待中」，静音必须一个字都不进 stdout。
        _hit, _reason, out = _drive_giveup(mod, _ROOM_ITEMS, task_id=570_500_300, room_waited=40.0)
        bad = [
            ln for ln in out.splitlines()
            if ln.strip() and not any(ln.startswith(p) for p in _USER_LINE)
        ]
        if bad:
            msgs.append(f"静音模式下 stdout 仍有非用户行（应只剩『五重决战：…』）：{bad[:3]}")
        if "共斗房等待中" in out:
            msgs.append("静音模式下房等心跳仍进了 stdout（机制日志没被分流）")
    finally:
        mod.set_quiet(real_quiet)

    # 非静音：机制日志照旧可见（离线守卫/真机 runner 取证靠它）
    _hit2, _r2, out2 = _drive_giveup(mod, _ROOM_ITEMS, task_id=570_500_301, room_waited=40.0)
    if "共斗房等待中" not in out2:
        msgs.append("非静音模式下房等心跳没进 stdout（机制日志被吞 → 离线取证/真机 runner 会失明）")

    # 用户行文案：必须是「要打 N 次」
    _hit3, _r3, out3 = _drive_giveup(
        mod, _MODE_TICKETS, task_id=570_500_302,
        params={"ocr_entry": "OcrTask", "room_wait_sec": 300, "no_progress_sec": 900, "target_fights": 3},
    )
    if "五重决战：要打 3 次" not in out3:
        msgs.append(f"没有打出「要打 3 次」这一行：{out3.strip()[:120]!r}")
    return msgs


def probe_wuchong_user_output() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _output_failures(impl) == []


HOOKS = [
    (
        "wuchong-ticket-exhausted",
        "#86",
        "门票（今天剩余次数）用尽 → 立刻带原因收工（原因含『剩余次数』），并记进 session；"
        "有票（x3）绝不误收工 —— 绝不靠『点一次挑战再读弹窗』发现（点一次白烧一张票）",
        probe_wuchong_ticket_exhausted,
    ),
    (
        "wuchong-error-modal-stop",
        "#86",
        "认不出的错误弹窗（unknown 连续 ≥3 且含 剩余次数/不足/错误/失败/无法挑战/已达上限）→ 停手带原因收工、"
        "**不点任何按钮**；没有关键词的 unknown 绝不误判（正常过场不受影响）",
        probe_wuchong_error_modal,
    ),
    (
        "wuchong-user-output-quiet",
        "#86",
        "用户可见输出只有 4 类（`五重决战：要打 N 次 / 第 i/N 次 开始 / 第 i/N 次 完成 / 收工 —— 原因`）："
        "interface.json 的 agent.child_args 带 --quiet、main.py 处理它；静音下 stdout 无机制日志，非静音下仍有",
        probe_wuchong_user_output,
    ),
]


# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_86 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_wuchong_ticket_exhausted() is True
        and probe_wuchong_error_modal() is True
        and probe_wuchong_user_output() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三个守卫全绿")
    if not green:
        for m in (_ticket_failures(impl) + _modal_failures(impl) + _output_failures(impl))[:6]:
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    # ① 关掉门票检查（_remaining_plays 永远 None）→ W1 红
    real_remain = impl._remaining_plays
    try:
        impl._remaining_plays = lambda items: None
        m1 = _ticket_failures(impl)
        red1 = len(m1) > 0
        print(f"  [{'PASS' if red1 else 'FAIL'}] 关掉门票解析（永远读不到剩余次数）-> {'红' if red1 else '仍绿'}"
              + (f"  {m1[0]}" if m1 else ""))
    finally:
        impl._remaining_plays = real_remain
    checks.append(red1)

    # ② 关掉错误弹窗判据（关键词永远不命中）→ W2 红
    real_hint = impl._has_error_hint
    try:
        impl._has_error_hint = lambda items: False
        m2 = _modal_failures(impl)
        red2 = len(m2) > 0
        print(f"  [{'PASS' if red2 else 'FAIL'}] 关掉错误弹窗判据 -> {'红' if red2 else '仍绿'}"
              + (f"  {m2[0]}" if m2 else ""))
    finally:
        impl._has_error_hint = real_hint
    checks.append(red2)

    # ③ 静音失效（_log 无视 QUIET 永远 print）→ W3 红
    real_quiet_flag = impl.QUIET
    real_log = impl._log
    try:
        def _log_always(msg=""):  # noqa: ANN001
            print(msg, flush=True)

        impl._log = _log_always
        impl.set_quiet(True)
        m3 = _output_failures(impl)
        red3 = len(m3) > 0
        print(f"  [{'PASS' if red3 else 'FAIL'}] 静音失效（机制日志照旧进 stdout）-> {'红' if red3 else '仍绿'}"
              + (f"  {m3[0]}" if m3 else ""))
    finally:
        impl._log = real_log
        impl.set_quiet(real_quiet_flag)
    checks.append(red3)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
