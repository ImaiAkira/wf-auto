# -*- coding: utf-8 -*-
"""#79：五重「打几把就卡死」—— 任务级 `max_hit` 是元凶，改时间闩锁 + 房等心跳。

## 真机现场（`install/logs/log-20261017.log`，18:32–19:18，一次任务 6 把）

```
18:33:45  点击 '招募'   ← 第 1 间房
18:45:44  点击 '招募'   ← 第 2 间房
19:06:16  点击 '招募'   ← 第 3 间房
19:13:03  点击 '多人游戏'  ← 第 4 间房
（此后 302 秒一行日志都没有，画面停在共斗房）
19:18:16  触发收工兜底：共斗房停留 302s 仍未能开战（state=wuchong_room）
```

**`招募` 恰好 3 次后彻底消失** —— 因为 `WuchongRecruitOpen` 上挂着 `max_hit: 3`，而 MAA 的
`max_hit` 是**整任务共享**计数（#50 教训），用光即**静默跳过**（不报错、不打印）。

## 本票契约

- **W1 禁任务级 max_hit**：`WuchongRecruitOpen` / `WuchongStaleTeam` 上**不许**有 `max_hit`
  （它们在一局里会按「每间房 / 每次落错页」反复命中）；替换为**时间闩锁**
  `latch: recruit_open` / `latch: stale_team`（`LATCH_RETRY_S=8s` 窗口内不重复点，永不失效）。
- **W2 闩锁名单一真源**：`scene.wuchong.LATCH_RETRY_NAMES` ⊇ 上述两个名字，且与
  `agent/wuchong_impl.WuchongActAction._LATCHES` 一致。
- **W3 房等心跳**：`WuchongGiveUpRecognition` 在共斗房里每 `ROOM_BEAT_SEC`(15s) 打一行
  「共斗房等待中：已等 Xs（招募中/未进行招募）」—— 画面不动时也能看出任务活着
  （运维这次的「卡死」观感有一半来自 302s 静默）。
- **W4 有界不变**：`room_wait_sec` 仍在（超时带原因收工），`WuchongStall` 的 8 次强杀重开是**刻意**
  的每任务上限（≈12 分钟重启尝试；再往后由 giveup 兜底）。
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
PIPELINE_REL = Path("assets") / "resource" / "pipeline" / "wuchong.json"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _pipeline(root: Path | None = None) -> dict:
    import jsonc  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    with open(base / PIPELINE_REL, encoding="utf-8") as f:
        return jsonc.load(f)


def _cp(node: dict) -> dict:
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


# ---------------------------------------------------------------------------
# W1 + W2
# ---------------------------------------------------------------------------
def _maxhit_failures(root: Path | None = None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _pipeline(root)
    for name, latch in (("WuchongRecruitOpen", "recruit_open"), ("WuchongStaleTeam", "stale_team")):
        node = pipes.get(name) or {}
        if node.get("max_hit") is not None:
            msgs.append(
                f"{name}: 带任务级 max_hit={node.get('max_hit')!r} —— 整任务共享计数，用光后节点静默跳过"
                "（真机：3 次招募后第 4 间房再也不招募 → 302s 卡死）"
            )
        got = _cp(node).get("latch")
        if got != latch:
            msgs.append(f"{name}: latch={got!r}（应为 {latch!r}：时间闩锁替代任务级计数）")
        if latch not in w.LATCH_RETRY_NAMES:
            msgs.append(f"scene.wuchong.LATCH_RETRY_NAMES 缺 {latch!r}（真源与 pipeline 不一致）")
    return msgs


def probe_wuchong_no_task_scoped_maxhit() -> bool:
    _paths()
    return _maxhit_failures() == []


# ---------------------------------------------------------------------------
# W3：房等心跳（驱动真实 wuchong_giveup 识别，把房间时钟倒拨）
# ---------------------------------------------------------------------------
_ROOM_ITEMS = [("房间号码", [100, 300, 200, 40]), ("招募", [400, 900, 80, 40]), ("未进行招募", [200, 700, 160, 40])]


class _RecArgv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


def _beat_failures(mod) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    real_ocr = mod._ocr
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p.json")
        try:
            mod._ocr = lambda context, image, entry="OcrTask": list(_ROOM_ITEMS)
            with mod._LOCK:
                mod._SESSION["task_id"] = 570_400_001
                mod._SESSION["start_ts"] = time.monotonic()
                mod._SESSION["last_progress_ts"] = time.monotonic()
                mod._SESSION["room_first_ts"] = time.monotonic() - 40.0      # 已在房里 40s
                mod._SESSION["room_beat_ts"] = 0.0
                mod._SESSION["last_state"] = None
                mod._SESSION["last_observe_ts"] = 0.0
                mod._SESSION["unknown_count"] = 0
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.WuchongGiveUpRecognition().analyze(
                    None,
                    _RecArgv(570_400_001, {"ocr_entry": "OcrTask", "room_wait_sec": 300, "no_progress_sec": 900}),
                )
            out = buf.getvalue()
            if "共斗房等待中" not in out:
                msgs.append(f"共斗房停留 40s 却没有「等待中」心跳（画面不动时看不出任务活着）；stdout={out[:120]!r}")
            if "已等" not in out:
                msgs.append("心跳行没有报已等秒数（运维无法判断是卡死还是在等人）")
            # 心跳节流：立刻再跑一次，不应重复刷屏
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                mod.WuchongGiveUpRecognition().analyze(
                    None,
                    _RecArgv(570_400_001, {"ocr_entry": "OcrTask", "room_wait_sec": 300, "no_progress_sec": 900}),
                )
            if "共斗房等待中" in buf2.getvalue():
                msgs.append("心跳没有按 ROOM_BEAT_SEC 节流（每个判据周期都刷屏）")
        finally:
            mod._ocr = real_ocr
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_room_beat() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _beat_failures(impl) == []


HOOKS = [
    (
        "wuchong-no-task-scoped-maxhit",
        "#79",
        "禁任务级 max_hit：WuchongRecruitOpen / WuchongStaleTeam 改用时间闩锁"
        "（recruit_open / stale_team，≤1 次/8s，永不失效）—— 真机 3 次招募后第 4 间房节点静默失效 → 302s 卡死",
        probe_wuchong_no_task_scoped_maxhit,
    ),
    (
        "wuchong-room-wait-beat",
        "#79",
        "共斗房等待心跳：房里每 15s 打一行「共斗房等待中：已等 Xs（招募中/未进行招募）」且按 ROOM_BEAT_SEC 节流"
        "—— 画面不动时也能看出任务活着（不是卡死）",
        probe_wuchong_room_beat,
    ),
]


# ---------------------------------------------------------------------------
def _set_field_in_node(path: Path, node: str, field: str, value) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.index(f'"{node}": {{')
    key = f'"{field}":'
    at = text.index(key, start)
    line_end = text.index("\n", at)
    keeps_comma = text[at:line_end].rstrip().endswith(",")
    raw = json.dumps(value) if not isinstance(value, (int, float)) else str(value)
    text = text[:at] + f'"{field}": {raw}' + ("," if keeps_comma else "") + text[line_end:]
    path.write_text(text, encoding="utf-8")


def _temp_pipeline() -> Path:
    import shutil  # noqa: PLC0415

    root = Path(tempfile.mkdtemp(prefix="wf_hook79_"))
    (root / PIPELINE_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / PIPELINE_REL, root / PIPELINE_REL)
    return root


def prove_red() -> bool:
    _paths()
    import shutil  # noqa: PLC0415
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_79 prove-red：逐一破坏实现，要求守卫各自变红")
    green = probe_wuchong_no_task_scoped_maxhit() is True and probe_wuchong_room_beat() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：两个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # ① 把 max_hit 加回 WuchongRecruitOpen（就是在真机上卡死的那一刀）
    root = _temp_pipeline()
    try:
        text = (root / PIPELINE_REL).read_text(encoding="utf-8")
        start = text.index('"WuchongRecruitOpen": {')
        anchor = text.index('        "post_delay":', start)
        text = text[:anchor] + '        "max_hit": 3,\n' + text[anchor:]
        (root / PIPELINE_REL).write_text(text, encoding="utf-8")
        m = _maxhit_failures(root)
        red = len(m) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把 max_hit:3 加回 WuchongRecruitOpen -> {'红' if red else '仍绿'}"
              + (f"  {m[0]}" if m else ""))
        checks.append(red)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ② 去掉 WuchongStaleTeam 的闩锁（回到「点了就永远不再点」或「无限点」的旧形态）
    root = _temp_pipeline()
    try:
        text = (root / PIPELINE_REL).read_text(encoding="utf-8")
        text = text.replace('                    "latch": "stale_team",\n', "", 1)
        (root / PIPELINE_REL).write_text(text, encoding="utf-8")
        m2 = _maxhit_failures(root)
        red2 = len(m2) > 0
        print(f"  [{'PASS' if red2 else 'FAIL'}] 摘掉 WuchongStaleTeam 的 stale_team 闩锁 -> {'红' if red2 else '仍绿'}"
              + (f"  {m2[0]}" if m2 else ""))
        checks.append(red2)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ③ 关掉房等心跳（把 ROOM_BEAT_SEC 调到极大 = 永不打印）
    real_beat = impl.ROOM_BEAT_SEC
    try:
        impl.ROOM_BEAT_SEC = 10_000.0
        m3 = _beat_failures(impl)
        red3 = len(m3) > 0
        print(f"  [{'PASS' if red3 else 'FAIL'}] 关掉房等心跳（ROOM_BEAT_SEC=10000）-> {'红' if red3 else '仍绿'}"
              + (f"  {m3[0]}" if m3 else ""))
        checks.append(red3)
    finally:
        impl.ROOM_BEAT_SEC = real_beat

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
