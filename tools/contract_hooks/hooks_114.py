# -*- coding: utf-8 -*-
"""#114：连不上服务器时自动重启客户端 —— 契约挂点。

现场（docs/spec/runner-delivery.md R1，真机 2026-10-18 夜，A/B 两账号两设备同时被拒）：
三种断连文案（F2032 / A4050 / 暂时无法连接），点【重试】**无效**，`am force-stop` + 重新拉起
客户端才能恢复（重启后 ≈40s 回到「登录成功」→【继续游戏】→ 主城）。

本文件把「能自动重启」拆成四个可判属性（每题一个挂点；prove-red 见文末）：

1. ``wuchong-net-texts-shared-distinct`` —— **三种文案一份判据**且**互不混淆**：
   - 文案表唯一真源 ``scene.wuchong.NET_DISCONNECT_TEXTS``，agent 快照逐字一致；
   - 三张真机证据帧的 OCR 文本分别只命中自己（F2032 / A4050 / UNREACHABLE）；
   - 正常主城 / 战斗帧**一个都不命中**；
   - 三个 pipeline 断连节点都走 ``wuchong_net``（不再各写一份 OCR expected 列表）；
   - ``wuchong_net`` 返回的 detail 里 kind/label 能区分三者。
2. ``wuchong-net-restart-bounded`` —— **重启上限生效**：
   - 常量有界（1..5，实际 3），pipeline 的 ``WuchongNetGuard`` 用 ``restart_game`` 且
     ``limit`` / ``restart_wait`` 与真源一致；
   - 驱动真实识别器：注入 4 个断连 episode ⇒ 前 3 个各重启 1 次，第 4 个**不再重启**，
     由既有 ``WuchongGiveUp`` 命中并带原因收工（原因含次数 + 三种文案）。
3. ``wuchong-net-restart-resumes-game`` —— **重启后必须走「继续游戏」**：
   - ``WuchongNetGuard.next == ["WuchongEntry"]``（回枢纽，绝不自己点屏幕）；
   - 枢纽里仍有 ``WuchongResumeQuest`` / ``[JumpBack]PubLoginContinue`` / ``[JumpBack]PubTitleStart``；
   - ``WuchongResumeQuest`` 的识别文案 == 真源 ``RESUME_QUEST_TEXTS``；
   - 「有正在进行中的关卡」帧上 ``wuchong_net`` 一律 miss（不会把恢复模态误当断连去重启）。
4. ``wuchong-net-cooldown-preserved`` —— **重试冷却仍承重**：
   - ``SERVER_RETRY_COOLDOWN_S ≥10`` 且动作闩窗口与真源一致；
   - 三个重试节点的动作都挂 ``latch=server_retry``；
   - 假时钟驱动真实识别器：t=0/5/9.9 只放行 retry、不重启；t=10 才允许重启。

prove-red（``python tools\\contract_hooks\\hooks_114.py``）做 ≥3 个破坏实验：
去掉上限 / 把重启换成点重试 / 重启后不走继续游戏 / 绕过冷却。
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
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


def _node(pipes: dict, name: str) -> dict:
    return pipes.get(name) or {}


def _custom_rec(node: dict) -> dict:
    return ((node.get("recognition") or {}).get("param") or {})


def _action_raw(node: dict) -> dict:
    return ((node.get("action") or {}).get("param") or {})


def _action_param(node: dict) -> dict:
    return _action_raw(node).get("custom_action_param") or {}


# ---------------------------------------------------------------------------
# 真机证据帧的 OCR 文本（来自 tools/frames/*.png 的整屏 OCR；识别只用文本，不需要像素）
# ---------------------------------------------------------------------------
FRAME_F2032 = [
    ("未能连网", [448, 772, 179, 60]),
    ("请确认", [470, 834, 139, 52]),
    ("(No.F2032)", [440, 894, 197, 48]),
    ("OK", [500, 1208, 79, 56]),
]
FRAME_A4050 = [
    ("发生意想不到的错误", [351, 780, 379, 48]),
    ("回到登录界面", [410, 836, 257, 48]),
    ("(No.A4050)", [438, 898, 199, 42]),
    ("OK", [500, 1208, 77, 56]),
]
FRAME_UNREACHABLE = [
    ("星点启程", [452, 538, 302, 84]),
    ("暂时无法连接", [361, 764, 355, 62]),
    ("暂时连接不上服务器，请稍后重试。", [258, 1040, 540, 40]),
    ("重新连接", [430, 1228, 221, 62]),
    ("点击开始", [406, 1640, 231, 64]),
]
FRAME_RESUME_QUEST = [
    ("有正在进行中的关卡", [200, 700, 300, 40]),
    ("是否继续关卡？", [240, 760, 240, 40]),
    ("放弃", [180, 804, 66, 39]),
    ("继续", [489, 804, 66, 39]),
]
NORMAL_MAIN_CITY = [
    ("修行之道", [15, 725, 161, 45]),
    ("成长任务", [47, 368, 118, 33]),
    ("当前进度", [366, 928, 60, 20]),
    ("活动", [80, 1120, 62, 34]),
    ("领主战", [569, 1121, 78, 29]),
]
NORMAL_BATTLE = [
    ("时间 28:03", [300, 1180, 120, 40]),
    ("分数  00166756407", [300, 1180, 220, 40]),
]

#: 2. 重启上限的行为测试参数（有界且与真源一致）。
_GIVEUP_PARAM = {
    "ocr_entry": "OcrTask",
    "max_task_sec": 0,
    "unknown_limit": 120,
    "no_progress_sec": 900,
    "room_wait_sec": 300,
    "target_fights": 0,
}


class _RecArgv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


class _Clock:
    def __init__(self, t: float = 0.0):
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def __enter__(self) -> "_Clock":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


@contextlib.contextmanager
def _ledger_isolated(mod):
    """把账本/机制日志指到临时文件，并静音 ``_log``（避免污染 debug/ 下的真实日志）。"""
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    saved_log = getattr(mod, "_LOG_PATH", None)
    saved_quiet = getattr(mod, "QUIET", False)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p114_progress.json")
        mod._LOG_PATH = Path(td) / "wuchong_agent.log"
        mod.QUIET = True
        try:
            mod.ledger.reset(mod.LEDGER_SCOPE)
            yield
        finally:
            mod.QUIET = saved_quiet
            mod._LOG_PATH = saved_log
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file


def _reset_task(mod, tid: int) -> None:
    with mod._LOCK:
        mod._SESSION["task_id"] = None
    mod._sync_task(tid)


def _drive(mod, frame, param: dict, clock: _Clock, tid: int):
    """驱动**真实** ``WuchongNetGuardRecognition``（只 monkeypatch 抓屏/OCR/时钟）。"""
    saved_ocr = mod._ocr
    saved_clock = mod._NET_CLOCK
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(frame)
        mod._NET_CLOCK = clock
        return mod.WuchongNetGuardRecognition().analyze(None, _RecArgv(tid, param))
    finally:
        mod._ocr = saved_ocr
        mod._NET_CLOCK = saved_clock


def _drive_giveup(mod, frame, tid: int):
    """驱动**真实** ``WuchongGiveUpRecognition``（重启上限的带原因收工出口）。"""
    saved_ocr = mod._ocr
    buf = io.StringIO()
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(frame)
        with contextlib.redirect_stdout(buf):
            res = mod.WuchongGiveUpRecognition().analyze(None, _RecArgv(tid, _GIVEUP_PARAM))
        return res, buf.getvalue()
    finally:
        mod._ocr = saved_ocr


def _hit(res) -> bool:
    return list(getattr(res, "box", None) or []) == [0, 0, 0, 0]


def _restarts(mod) -> int:
    with mod._LOCK:
        return int(mod._SESSION.get("net_restarts") or 0)


# ---------------------------------------------------------------------------
# 守卫 1：三种文案一份判据 + 互不混淆
# ---------------------------------------------------------------------------
def text_failures(mod=None, scene=None, pipes: dict | None = None) -> list[str]:
    _paths()
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    if scene is None:
        from scene import wuchong as scene  # noqa: PLC0415
    if pipes is None:
        pipes = _pipeline()

    msgs: list[str] = []

    # (a) 共享判据 = 一份：agent 快照必须与 scene 真源逐字一致。
    for name in (
        "NET_DISCONNECT_KINDS",
        "NET_DISCONNECT_TEXTS",
        "NET_DISCONNECT_LABELS",
        "NET_DISCONNECT_LABEL",
        "NET_ERROR_OK_KINDS",
        "NET_RECONNECT_KINDS",
        "NET_RESTART_LIMIT",
        "RELAUNCH_WAIT_SEC",
        "NET_RESTART_EXHAUSTED_REASON",
        "RESUME_QUEST_TEXTS",
    ):
        snap = getattr(mod, name, None)
        truth = getattr(scene, name, None)
        if snap != truth:
            msgs.append(f"配置漂移：wuchong_impl.{name}={snap!r} != scene.wuchong.{name}={truth!r}")

    # (b) 三张真机证据帧：各自**只**命中自己；正常帧一个都不命中。
    cases = (
        ("F2032 证据帧 net_error_f2032.png", FRAME_F2032, scene.NET_DISCONNECT_F2032),
        ("A4050 证据帧 session_error_a4050.png", FRAME_A4050, scene.NET_DISCONNECT_A4050),
        ("暂时无法连接证据帧 server_unreachable.png", FRAME_UNREACHABLE, scene.NET_DISCONNECT_UNREACHABLE),
        ("正常主城帧（负例）", NORMAL_MAIN_CITY, None),
        ("正常战斗帧（负例）", NORMAL_BATTLE, None),
        ("«有正在进行中的关卡» 恢复帧（负例）", FRAME_RESUME_QUEST, None),
        # 「请确认」/「回到登录界面」是通用词：单独出现**不许**判成断连（身份靠标题句/错误码）。
        ("普通确认框（只有『请确认』，负例）", [("请确认", [0, 0, 100, 40])], None),
        ("普通错误框（只有『回到登录界面』，负例）", [("回到登录界面", [0, 0, 100, 40])], None),
    )
    for label, frame, want in cases:
        got = mod.net_disconnect_kinds(frame)
        if want is None:
            if got:
                msgs.append(f"{label} 被误判为断连：{got}")
        elif got != [want]:
            msgs.append(f"{label} 应只命中 {want!r}，实际 {got!r}（三种文案互相混淆）")

    # (c) pipeline：两个重试节点都必须走共享判据（不能再各写一份 OCR 列表）。
    for node_name, want_kinds in (
        ("WuchongNetError", list(scene.NET_ERROR_OK_KINDS)),
        ("WuchongServerUnreachable", list(scene.NET_RECONNECT_KINDS)),
        # 旧 #107 的重复节点也统一到共享判据（否则「暂时无法连接」会存在第二份 OCR 列表）。
        ("WuchongNetDisconnect", list(scene.NET_RECONNECT_KINDS)),
    ):
        rec = _custom_rec(_node(pipes, node_name))
        if rec.get("custom_recognition") != "wuchong_net":
            msgs.append(f"{node_name} 没走共享判据 wuchong_net（各自写 OCR 列表会漂移）")
            continue
        param = rec.get("custom_recognition_param") or {}
        if str(param.get("mode")) != mod.NET_RETRY_MODE:
            msgs.append(f"{node_name}.mode={param.get('mode')!r}（应为 retry）")
        if list(param.get("kinds") or []) != want_kinds:
            msgs.append(f"{node_name}.kinds={param.get('kinds')!r}（应为 {want_kinds!r}）")

    # (d) 行为：识别器返回的 detail 能区分三种（便于日志定位）。
    for kind, frame in (
        (scene.NET_DISCONNECT_F2032, FRAME_F2032),
        (scene.NET_DISCONNECT_A4050, FRAME_A4050),
        (scene.NET_DISCONNECT_UNREACHABLE, FRAME_UNREACHABLE),
    ):
        with _ledger_isolated(mod):
            tid = 114_000 + list(scene.NET_DISCONNECT_KINDS).index(kind)
            _reset_task(mod, tid)
            res = _drive(mod, frame, {"mode": "retry", "kinds": [kind]}, _Clock(0.0), tid)
            detail = res.detail or {}
            if not _hit(res):
                msgs.append(f"{kind}：首帧应放行去点重试，实际 miss（detail={detail!r}）")
            if detail.get("kind") != kind or detail.get("net") != kind:
                msgs.append(f"{kind}：识别器 detail 未区分种类（{detail!r}）")
    labels = {scene.NET_DISCONNECT_LABELS.get(k) for k in scene.NET_DISCONNECT_KINDS}
    if len(labels) != len(scene.NET_DISCONNECT_KINDS):
        msgs.append(f"三种断连的可读名不互异：{labels!r}")
    return msgs


def probe_wuchong_net_texts_shared() -> bool:
    return text_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：重启次数上限（驱动真实识别器 + 真实 WuchongGiveUp 出口）
# ---------------------------------------------------------------------------
def restart_failures(mod=None, scene=None, pipes: dict | None = None) -> list[str]:
    _paths()
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    if scene is None:
        from scene import wuchong as scene  # noqa: PLC0415
    if pipes is None:
        pipes = _pipeline()

    msgs: list[str] = []

    # (a) 常量有界 + pipeline 接线（节点 / 动作 / 等待 / 上限）。
    limit = int(getattr(scene, "NET_RESTART_LIMIT", 0) or 0)
    mod_limit = int(getattr(mod, "NET_RESTART_LIMIT", -1))
    if not (1 <= limit <= 5):
        msgs.append(f"NET_RESTART_LIMIT={limit} 不是有界小整数（重启必须有上限）")
    if mod_limit != limit:
        msgs.append(
            f"wuchong_impl.NET_RESTART_LIMIT={mod_limit} != scene.wuchong.NET_RESTART_LIMIT={limit}"
            "（安装态/真源重启上限漂移）"
        )
    if float(getattr(scene, "RELAUNCH_WAIT_SEC", 0) or 0) < 40:
        msgs.append(
            f"RELAUNCH_WAIT_SEC={getattr(scene, 'RELAUNCH_WAIT_SEC', None)!r} 太短"
            "（真机重启后 ≈40s 才回到登录成功）"
        )
    guard = _node(pipes, scene.NET_RESTART_NODE)
    rec = _custom_rec(guard)
    param = rec.get("custom_recognition_param") or {}
    if rec.get("custom_recognition") != "wuchong_net":
        msgs.append(f"{scene.NET_RESTART_NODE} 没走共享判据 wuchong_net")
    if str(param.get("mode")) != mod.NET_RESTART_MODE:
        msgs.append(f"{scene.NET_RESTART_NODE}.mode={param.get('mode')!r}（应为 restart）")
    if int(param.get("limit") or 0) != limit:
        msgs.append(
            f"{scene.NET_RESTART_NODE}.limit={param.get('limit')!r} != 真源 NET_RESTART_LIMIT={limit}"
            "（上限被 pipeline 改写 = 可在不改变真源的情况下绕过）"
        )
    action = _action_raw(guard)
    if action.get("custom_action") != scene.NET_RESTART_ACTION:
        msgs.append(
            f"{scene.NET_RESTART_NODE} 的动作是 {action.get('custom_action')!r}，"
            f"不是 {scene.NET_RESTART_ACTION!r}（把点重试当恢复 = 治不好断连）"
        )
    waits = action.get("custom_action_param") or {}
    if float(waits.get("restart_wait") or 0) != float(scene.RELAUNCH_WAIT_SEC):
        msgs.append(
            f"{scene.NET_RESTART_NODE}.restart_wait={waits.get('restart_wait')!r} "
            f"!= RELAUNCH_WAIT_SEC={scene.RELAUNCH_WAIT_SEC!r}"
        )
    if waits.get("pkg") != "com.leiting.wf":
        msgs.append(f"{scene.NET_RESTART_NODE}.pkg={waits.get('pkg')!r}（应为 com.leiting.wf）")

    # (b) 行为：4 个断连 episode（三种文案轮换）⇒ 前 3 个各重启一次，第 4 个由 WuchongGiveUp 收工。
    with _ledger_isolated(mod), _Clock(0.0) as clock:
        tid = 114_100
        _reset_task(mod, tid)
        restart_param = {"mode": "restart", "limit": limit}
        episodes = (
            (scene.NET_DISCONNECT_F2032, FRAME_F2032, 0.0),
            (scene.NET_DISCONNECT_A4050, FRAME_A4050, 10.0),
            (scene.NET_DISCONNECT_UNREACHABLE, FRAME_UNREACHABLE, 20.0),
        )
        for index, (kind, frame, t0) in enumerate(episodes, start=1):
            clock.t = t0
            first = _drive(mod, frame, restart_param, clock, tid)
            if _hit(first):
                msgs.append(f"{kind}：首个断连帧就重启（应先冷却重试一次）")
            clock.t = t0 + 5.0
            mid = _drive(mod, frame, restart_param, clock, tid)
            if _hit(mid):
                msgs.append(f"{kind}：冷却未满 {clock.t:.1f}s 就重启（绕过 SERVER_RETRY_COOLDOWN_S）")
            clock.t = t0 + 10.0
            due = _drive(mod, frame, restart_param, clock, tid)
            detail = due.detail or {}
            if not _hit(due):
                msgs.append(f"{kind}：冷却已满仍不重启（第 {index} 次重启丢失）")
            elif int(detail.get("restart") or 0) != index:
                msgs.append(f"{kind}：重启计数 detail={detail!r}（应为第 {index} 次）")

        if _restarts(mod) != limit:
            msgs.append(f"3 个 episode 后 net_restarts={_restarts(mod)} != {limit}")

        # 第 4 次断连：识别器不再重启（有界），交给 WuchongGiveUp 带原因收工。
        clock.t = 35.0
        fourth = _drive(mod, FRAME_F2032, restart_param, clock, tid)
        if _hit(fourth):
            msgs.append(f"第 {limit + 1} 次断连仍在重启（上限失效）")
        if not (fourth.detail or {}).get("net_exhausted"):
            msgs.append(f"超限时 detail 未标记 net_exhausted：{fourth.detail!r}")
        giveup, out = _drive_giveup(mod, FRAME_F2032, tid)
        if not _hit(giveup):
            msgs.append("重启次数用尽后 WuchongGiveUp 未命中（不会带原因收工，会空转）")
        reason = str((giveup.detail or {}).get("reason") or "")
        for needle in (
            f"客户端重启 {limit} 次仍连不上服务器",
            "带原因收工",
            "F2032/A4050/暂时无法连接",
        ):
            if needle not in reason:
                msgs.append(f"超限收工原因缺 {needle!r}（实际 {reason!r}）")
        if _restarts(mod) != limit:
            msgs.append(f"超限收工不应再增加重启次数（实际 {_restarts(mod)}，期望 {limit}）")
        if "客户端重启" not in out:
            msgs.append(f"收工原因没有进用户可见输出（stdout={out[:120]!r}）")

    # (c) 换任务清零（上限是「3 次/任务」，不是一辈子 3 次）。
    with _ledger_isolated(mod), _Clock(0.0) as clock:
        _reset_task(mod, 114_101)
        clock.t = 0.0
        _drive(mod, FRAME_F2032, restart_param, clock, 114_101)
        clock.t = 10.0
        _drive(mod, FRAME_F2032, restart_param, clock, 114_101)
        if _restarts(mod) != 1:
            msgs.append("新任务的首个 episode 未从 1 开始计")
        _reset_task(mod, 114_102)
        if _restarts(mod) != 0:
            msgs.append(f"换 task_id 后 net_restarts={_restarts(mod)} 未清零（上限跨任务累积）")
    return msgs


def probe_wuchong_net_restart_bounded() -> bool:
    return restart_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：重启后必须走「继续游戏 / 点击开始 / 有正在进行中的关卡」
# ---------------------------------------------------------------------------
def resume_after_restart_failures(mod=None, scene=None, pipes: dict | None = None) -> list[str]:
    _paths()
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    if scene is None:
        from scene import wuchong as scene  # noqa: PLC0415
    if pipes is None:
        pipes = _pipeline()

    msgs: list[str] = []

    # (a) 重启动作回枢纽，不自己点屏幕；恢复引用必须都在枢纽里。
    restart = _node(pipes, scene.NET_RESTART_NODE)
    if list(restart.get("next") or []) != ["WuchongEntry"]:
        msgs.append(
            f"{scene.NET_RESTART_NODE}.next={list(restart.get('next') or [])!r}"
            "（重启后必须回枢纽重新分派，绝不许直接点屏幕乱点）"
        )
    if list(restart.get("on_error") or []) != ["WuchongEntry"]:
        msgs.append(f"{scene.NET_RESTART_NODE}.on_error 必须回 WuchongEntry")
    hub = list(_node(pipes, "WuchongEntry").get("next") or [])
    for ref in ("WuchongResumeQuest", "[JumpBack]PubLoginContinue", "[JumpBack]PubTitleStart"):
        if ref not in hub:
            msgs.append(f"枢纽里缺恢复引用 {ref!r}（重启后无法过「继续游戏 / 点击开始」）")

    # (b) 继续游戏/点击开始复用既有节点：WuchongResumeQuest 的判据 == 真源 RESUME_QUEST_TEXTS。
    resume = _node(pipes, "WuchongResumeQuest")
    rec = resume.get("recognition") or {}
    param = rec.get("param") or {}
    all_of = list(param.get("all_of") or [])
    if rec.get("type") != "And" or "WuchongResumeQuestText" not in all_of:
        msgs.append("WuchongResumeQuest 的识别被改掉（恢复模态必须复用既有 And 判据）")
    text_node = _node(pipes, "WuchongResumeQuestText")
    expected = list(((text_node.get("recognition") or {}).get("param") or {}).get("expected") or [])
    if expected != list(scene.RESUME_QUEST_TEXTS):
        msgs.append(
            f"WuchongResumeQuestText.expected={expected!r} != RESUME_QUEST_TEXTS={list(scene.RESUME_QUEST_TEXTS)!r}"
            "（重启后的恢复判据漂移）"
        )

    # (c) 行为：恢复模态帧上 wuchong_net 一律 miss（否则会把它当断连去重启，而不是点【继续】）。
    with _ledger_isolated(mod), _Clock(0.0) as clock:
        tid = 114_200
        _reset_task(mod, tid)
        for mode, param2 in (
            ("restart", {"mode": "restart"}),
            ("retry", {"mode": "retry", "kinds": [scene.NET_DISCONNECT_F2032]}),
        ):
            clock.t = 0.0
            res = _drive(mod, FRAME_RESUME_QUEST, param2, clock, tid)
            if _hit(res):
                msgs.append(f"「有正在进行中的关卡」帧被 wuchong_net({mode}) 命中（会去重启而不是点【继续】）")
            if (res.detail or {}).get("net") is not None:
                msgs.append(f"恢复模态帧的 net detail={res.detail!r}（应 None）")
    return msgs


def probe_wuchong_net_restart_resumes_game() -> bool:
    return resume_after_restart_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：断连重试仍受 SERVER_RETRY_COOLDOWN_S 冷却约束
# ---------------------------------------------------------------------------
def cooldown_failures(mod=None, scene=None, pipes: dict | None = None) -> list[str]:
    _paths()
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    if scene is None:
        from scene import wuchong as scene  # noqa: PLC0415
    if pipes is None:
        pipes = _pipeline()

    msgs: list[str] = []
    cooldown = float(getattr(scene, "SERVER_RETRY_COOLDOWN_S", 0) or 0)
    if cooldown < 10.0:
        msgs.append(f"SERVER_RETRY_COOLDOWN_S={cooldown} < 10s（服务端限流时密集重试只会更糟）")
    if abs(float(getattr(mod, "SERVER_RETRY_COOLDOWN_S", -1)) - cooldown) > 1e-9:
        msgs.append(
            f"wuchong_impl.SERVER_RETRY_COOLDOWN_S={getattr(mod, 'SERVER_RETRY_COOLDOWN_S', None)!r} "
            f"!= scene.wuchong.SERVER_RETRY_COOLDOWN_S={cooldown!r}"
        )
    window = (getattr(getattr(mod, "WuchongActAction", None), "_LATCH_WINDOWS", {}) or {}).get("server_retry")
    if window is None or abs(float(window) - cooldown) > 1e-9:
        msgs.append(f"WuchongActAction._LATCH_WINDOWS[server_retry]={window!r} 与真源 {cooldown!r} 不一致")

    # (a) 三个重试节点都必须挂动作侧时间闩（不许用 post_delay / 直接点）。
    for node_name in ("WuchongNetError", "WuchongServerUnreachable", "WuchongNetDisconnect"):
        action = _action_raw(_node(pipes, node_name))
        cp = action.get("custom_action_param") or {}
        if action.get("custom_action") != "wuchong_act":
            msgs.append(f"{node_name} 的动作不是 wuchong_act（无法按时间闩冷却）")
        if cp.get("latch") != "server_retry":
            msgs.append(f"{node_name}.latch={cp.get('latch')!r}（应 server_retry）")

    # (b) 假时钟：冷却窗口内只放行 retry；窗口外 retry 必须 miss、restart 才命中。
    with _ledger_isolated(mod), _Clock(0.0) as clock:
        tid = 114_300
        _reset_task(mod, tid)
        retry_param = {"mode": "retry", "kinds": [scene.NET_DISCONNECT_F2032]}
        restart_param = {"mode": "restart"}
        checks = (
            (0.0, "首次断连"),
            (5.0, "冷却中"),
            (9.9, "冷却将满"),
        )
        for t, label in checks:
            clock.t = t
            retry = _drive(mod, FRAME_F2032, retry_param, clock, tid)
            restart = _drive(mod, FRAME_F2032, restart_param, clock, tid)
            if not _hit(retry):
                msgs.append(f"{label}（t={t}s）retry 未命中 → 会跳过冷却直接重启")
            if _hit(restart):
                msgs.append(f"{label}（t={t}s）restart 命中 → 绕过了 SERVER_RETRY_COOLDOWN_S")
        clock.t = cooldown
        retry = _drive(mod, FRAME_F2032, retry_param, clock, tid)
        restart = _drive(mod, FRAME_F2032, restart_param, clock, tid)
        if _hit(retry):
            msgs.append(f"冷却满（t={cooldown}s）retry 仍命中 → 会每轮狂点【重试】")
        if not _hit(restart):
            msgs.append(f"冷却满（t={cooldown}s）restart 未命中 → 断连永远等不到重启")
    return msgs


def probe_wuchong_net_cooldown_preserved() -> bool:
    return cooldown_failures() == []


HOOKS = [
    (
        "wuchong-net-texts-shared-distinct",
        "#114",
        "三种断连文案（F2032/A4050/暂时无法连接）走**同一份**判据且互不混淆："
        "真机证据帧各自只命中自己、正常主城/战斗帧不命中、pipeline 三个节点都走 wuchong_net",
        probe_wuchong_net_texts_shared,
    ),
    (
        "wuchong-net-restart-bounded",
        "#114",
        "断连冷却重试仍失败 → 有界重启客户端（最多 3 次/任务）：注入 4 个断连 episode，"
        "前 3 个各重启一次、第 4 个由既有 WuchongGiveUp 带原因收工（原因含次数与三种文案）",
        probe_wuchong_net_restart_bounded,
    ),
    (
        "wuchong-net-restart-resumes-game",
        "#114",
        "重启后必须回枢纽走「继续游戏 / 点击开始 / 有正在进行中的关卡」（复用 WuchongResumeQuest、"
        "PubLoginContinue、PubTitleStart），绝不许重启动作自己点屏幕；恢复模态帧不得被判成断连",
        probe_wuchong_net_restart_resumes_game,
    ),
    (
        "wuchong-net-cooldown-preserved",
        "#114",
        "断连重试仍受 SERVER_RETRY_COOLDOWN_S(10s) 约束：冷却内只放行 retry、不重启；"
        "冷却满才允许重启（加了重启也不许绕过冷却）",
        probe_wuchong_net_cooldown_preserved,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（prove-red）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook114_"))
    (root / PIPELINE_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / PIPELINE_REL, root / PIPELINE_REL)
    return root


def _replace_in_node(path: Path, node: str, old: str, new: str) -> None:
    """在指定节点块内做一次文本替换（★jsonc 注释/顺序原样保留★）。"""
    text = path.read_text(encoding="utf-8")
    start = text.index(f'"{node}": {{')
    end = text.index("\n    }", start)
    block = text[start:end]
    if old not in block:
        raise RuntimeError(f"破坏点没找到：{node} 里没有 {old!r}")
    text = text[:start] + block.replace(old, new, 1) + text[end:]
    path.write_text(text, encoding="utf-8")


def _remove_hub_ref(path: Path, ref: str) -> None:
    """从枢纽 next 里摘掉一个恢复引用（模拟「重启后不走继续游戏」）。"""
    text = path.read_text(encoding="utf-8")
    needle = f'            "{ref}",\n'
    if needle not in text:
        raise RuntimeError(f"破坏点没找到：枢纽里没有 {needle!r}")
    path.write_text(text.replace(needle, "", 1), encoding="utf-8")


def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_114 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_wuchong_net_texts_shared()
        and probe_wuchong_net_restart_bounded()
        and probe_wuchong_net_restart_resumes_game()
        and probe_wuchong_net_cooldown_preserved()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：四个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # ① 去掉重启上限（把真源常量改成 0 = 不限）→ 守卫 2 必须红。
    real_limit = impl.NET_RESTART_LIMIT
    try:
        impl.NET_RESTART_LIMIT = 0
        msgs = restart_failures()
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 去掉重启上限 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)
    finally:
        impl.NET_RESTART_LIMIT = real_limit

    # ② 把「重启」换成「点重试」（治不好断连）→ 守卫 2 必须红。
    root = _temp_pipeline()
    try:
        _replace_in_node(
            root / PIPELINE_REL,
            "WuchongNetGuard",
            '"custom_action": "restart_game"',
            '"custom_action": "wuchong_act"',
        )
        msgs = restart_failures(pipes=_pipeline(root))
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 把重启换成点重试 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ③ 重启后不走「继续游戏」路径（从枢纽摘掉 WuchongResumeQuest）→ 守卫 3 必须红。
    root = _temp_pipeline()
    try:
        _remove_hub_ref(root / PIPELINE_REL, "WuchongResumeQuest")
        msgs = resume_after_restart_failures(pipes=_pipeline(root))
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 重启后不走继续游戏 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ④ 绕过冷却（把冷却改成 0）→ 守卫 4 必须红。
    real_cooldown = impl.SERVER_RETRY_COOLDOWN_S
    try:
        impl.SERVER_RETRY_COOLDOWN_S = 0.0
        msgs = cooldown_failures()
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 绕过 SERVER_RETRY 冷却 -> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)
    finally:
        impl.SERVER_RETRY_COOLDOWN_S = real_cooldown

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
