# -*- coding: utf-8 -*-
"""#47：幻想连战共斗房「停留时钟」被 loading 过渡帧清零 → 120s 有界收工永不触发 → 被 180s 卡死兜底强杀重启。

seam
----
* ``agent/phantom_impl.py``：
  - ``_observe`` 的共斗房停留计时归零规则（``_COOP_ROOM_STATES`` / ``_COOP_LEAVE_STATES``）；
  - ``PhantomGiveUpRecognition`` 的共斗房有界出口（reason 明说「共斗房停留 N 秒 仍未能开战」）。
* ``assets/resource/pipeline/phantom.json``：
  ``PhantomGiveUp``（动作 ``StopTask`` = 优雅收工）与 ``PhantomStall``（``phantom_restart`` = 强杀重启）。

诊断（真机 Q2，127.0.0.1:16384，`--list "幻想连战,-,1"`，`final_lord/logs/Q2.log`）
-------------------------------------------------------------------------------
1. 第 11 关正常打到第 15 关结算（账本 ``phantom/set/1/stage/11``），随后第 15 关是**协力关**，
   点卡片「战斗」进入【共斗房】（招募队友）。
2. 共斗房里点「招募」→「开始招募」→ 回到房间 → 点「挑战」（没队友时是灰的）：
   真机日志反复出现
   ``state=phantom_coop_room 点击按钮 '挑战' -> 校验通过：loading`` **8 次**，
   每次都夹着一句 ``[phantom] 进入共斗房：…`` —— 说明 ``coop_room_first_ts`` 每次都从 0 重新起算：
   点挑战后的 ``loading`` 过渡帧把它清零了。
3. 于是 ``coop_room_sec=120`` **永远到不了** → 最后 ``[stall_recover] 画面连续 180.7s 无变化``
   命中 ``PhantomStall`` → ``phantom_restart`` 强杀重启游戏 → 标题页 → 任务停手。

修法
----
* ``_observe`` 的共斗房时钟**只在【真正离开房间】的状态清零**（``_COOP_LEAVE_STATES``：
  开战 / 结算 / 回关卡选择页 / 单人编队 / 活动入口 / 主城 / 活动页 / 终始之战 / 换日 / 等级弹窗）；
  点「挑战」后的 ``loading``、OCR 抖动导致的 ``unknown`` 等**过渡帧保持时钟不动**，不再清零。
* 超时后由 ``PhantomGiveUp``（``StopTask``）**优雅收工**并给出原因「共斗房停留 N 秒 仍未能开战…」；
  ``PhantomGiveUp`` 排在 ``PhantomStall`` **之前**，因此绝不会让 180s 的强杀重启抢先命中。
* 另一条分支保持连通：队友到了 / 挑战可用 → 点挑战进入 ``phantom_battle``（是「离开」状态 →
  时钟清零）→ ``PhantomBattleWait`` → 正常推进，不会被误判成「停留超时」。

守卫（prove-red 在本文件末尾）
------------------------------
1. ``phantom-coop-room-dwell-clock-sticky`` —— 用真实 ``_observe`` 喂真机 Q2 的
   ``房间→挑战→loading→房间``（含 ``unknown``）序列，断言停留时钟**不变**；真正离开的房间状态
   必须清零；``loading``/``unknown`` 不得出现在 leave 集里。
2. ``phantom-coop-room-bounded-stop-repro`` —— 离线复现：房间起算 → 8 次过渡帧不清零 →
   把时钟倒拨到 >120s 再喂一帧「挑战后的 loading」**仍不清零** → 房间帧上真实
   ``PhantomGiveUpRecognition`` 命中并点名共斗房；刚进房不误收工。
3. ``phantom-coop-room-stop-not-restart`` —— 接线：``PhantomGiveUp`` 动作为 ``StopTask``、
   声明了正的 ``coop_room_sec``、且排在 ``PhantomStall``（``phantom_restart``）**之前**。
4. ``phantom-coop-room-advance-path-intact`` —— 另一条分支连通：``PhantomCoopChallenge``
   的 expect 仍含 ``phantom_battle``/``loading``，``PhantomBattleWait`` 在场，开战帧清零时钟。

★prove-red★（``python tools\\contract_hooks\\hooks_47.py``）：
  * 把 ``_observe`` 的时钟规则倒回「非房间即清零」的旧形态 → 守卫 1/2 变红（复现缺陷）；
  * 把 ``PhantomDispatch.next`` 里的 ``PhantomGiveUp``/``PhantomStall`` 调换顺序 → 守卫 3 变红
    （卡死兜底会先强杀重启）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red 子进程用 PYTHONPATH 抢先塞坏副本时仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

_PIPELINE_REL = "assets/resource/pipeline"
_PHANTOM = "phantom.json"
_SD = "special_dungeon.json"

# 真机帧 OCR（共斗房 / 加载）—— 内嵌，离线可求值（值取自 #30 的真机帧 disband.ocr.txt）。
#: 共斗房：房间号码 / 招募 / 复制 / 挑战 / 返回 → classify = phantom_coop_room。
ROOM_ITEMS: list[tuple[str, list[int]]] = [
    ("返回", [30, 1246, 46, 26]),
    ("挑战", [297, 906, 81, 46]),
    ("招募", [352, 808, 72, 41]),
    ("房间号码", [276, 1184, 94, 28]),
    ("复制", [540, 1230, 48, 31]),
]
#: 招募方式弹窗：招募方式 / 开始招募 → classify = phantom_recruit_dialog。
DIALOG_ITEMS: list[tuple[str, list[int]]] = [
    ("招募方式", [300, 560, 120, 40]),
    ("开始招募", [300, 700, 140, 44]),
]
#: 加载 / 过场：健康游戏忠告 → classify = loading（点「挑战」后的过渡帧形态）。
LOADING_ITEMS: list[tuple[str, list[int]]] = [
    ("健康游戏忠告", [200, 500, 300, 40]),
]
_ITEMS_BY_STATE = {
    "phantom_coop_room": ROOM_ITEMS,
    "phantom_recruit_dialog": DIALOG_ITEMS,
    "loading": LOADING_ITEMS,
}


# ---------------------------------------------------------------------------
# pipeline 载入 / 求值（复用 scene.drift，与 hooks_30 同一套）
# ---------------------------------------------------------------------------
def scene_on_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _pipeline_dir() -> Path:
    return REPO_ROOT / _PIPELINE_REL


def load_files(root: Path | None = None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = (root / _PIPELINE_REL) if root is not None else _pipeline_dir()
    return drift.load_pipelines(base)


def _node(name: str, files: dict):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


def _custom(node) -> str | None:
    rec = (node or {}).get("recognition") or {}
    return (rec.get("param") or {}).get("custom_recognition")


def _custom_param(node) -> dict:
    rec = (node or {}).get("recognition") or {}
    return (rec.get("param") or {}).get("custom_recognition_param") or {}


# ---------------------------------------------------------------------------
# 真实 phantom_impl 的驱动工具
# ---------------------------------------------------------------------------
def phantom_module():
    scene_on_path()
    import phantom_impl as ph  # noqa: PLC0415

    return ph


def _fresh_session(ph, tid: int = 470047) -> None:
    """把会话复位到「刚进共斗房前」的干净状态（确定性）。"""
    with ph._LOCK:
        ph._SESSION["task_id"] = tid
        ph._SESSION["coop_room_first_ts"] = 0.0
        ph._SESSION["cur_stage"] = None
        ph._SESSION["in_fight"] = False
        ph._SESSION["completed_sets"] = 0
        ph._SESSION["cur_set"] = 1
        ph._SESSION["max_done"] = 0
        ph._SESSION["session_max_done"] = 0
        ph._SESSION["total_marks"] = 0
        ph._SESSION["target_sets"] = 1
        ph._SESSION["unknown_count"] = 0
        ph._SESSION["start_ts"] = time.monotonic()
        ph._SESSION["last_progress_ts"] = time.monotonic()
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0


def _feed(ph, state: str, items=None) -> None:
    """喂一帧给真实 ``_observe``（绕过「同状态 1.2s 内只记一次」的合并，保证每帧都被观察）。"""
    with ph._LOCK:
        ph._SESSION["last_state"] = None
        ph._SESSION["last_observe_ts"] = 0.0
    ph._observe(state, {}, items if items is not None else _ITEMS_BY_STATE.get(state, []))


def _clock(ph) -> float:
    with ph._LOCK:
        return float(ph._SESSION["coop_room_first_ts"])


class _TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class _Argv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = _TaskDetail(task_id)
        self.custom_recognition_param = json.dumps(param)


def _drive_giveup(ph, *, state: str, coop_room_sec: float, backdate: float, tid: int = 470047):
    """驱动真实 ``PhantomGiveUpRecognition`` 跑一帧，返回 (是否命中, reason)。

    ``backdate`` = 把共斗房停留时钟倒拨的秒数（模拟「已经停留了这么久」）。
    """
    items = _ITEMS_BY_STATE[state]
    real_ocr = ph._ocr
    try:
        ph._ocr = lambda context, image, entry="OcrTask": list(items)
        with ph._LOCK:
            ph._SESSION["task_id"] = tid
            ph._SESSION["start_ts"] = time.monotonic()
            ph._SESSION["last_progress_ts"] = time.monotonic()
            ph._SESSION["coop_room_first_ts"] = time.monotonic() - float(backdate)
            ph._SESSION["last_state"] = None
            ph._SESSION["last_observe_ts"] = 0.0
            ph._SESSION["unknown_count"] = 0
            ph._SESSION["total_marks"] = 0
            ph._SESSION["max_done"] = 0
            ph._SESSION["completed_sets"] = 0
            ph._SESSION["target_sets"] = 1
        param = {"ocr_entry": "OcrTask", "coop_room_sec": coop_room_sec}
        res = ph.PhantomGiveUpRecognition().analyze(None, _Argv(tid, param))
        detail = res.detail or {}
        return (res.box == [0, 0, 0, 0]), str(detail.get("reason") or "")
    finally:
        ph._ocr = real_ocr


# ---------------------------------------------------------------------------
# 守卫 1：共斗房停留时钟不被 loading/unknown 过渡帧清零
# ---------------------------------------------------------------------------
def _clock_failures(ph) -> list[str]:
    msgs: list[str] = []

    # (a) 真机 Q2 序列：房间 → 挑战 → loading → 房间（反复，夹 unknown）→ 时钟必须【不变】。
    _fresh_session(ph)
    _feed(ph, "phantom_coop_room")
    t0 = _clock(ph)
    if not t0:
        msgs.append("进入共斗房后停留时钟没有起算（coop_room_first_ts 仍为 0）")
    for st in (
        "loading",
        "phantom_coop_room",
        "loading",
        "phantom_coop_room",
        "loading",
        "unknown",
        "phantom_coop_room",
    ):
        _feed(ph, st)
        cur = _clock(ph)
        if cur != t0:
            msgs.append(
                f"过渡帧 state={st} 把共斗房停留时钟清零了（{t0} -> {cur}）："
                f"点挑战后的 loading/unknown 不得清零（#47 缺陷）"
            )
            t0 = cur

    # (b) 房间 ↔ 招募弹窗 来回：都算「仍在共斗房序列里」，时钟不变。
    _fresh_session(ph)
    _feed(ph, "phantom_coop_room")
    t0 = _clock(ph)
    _feed(ph, "phantom_recruit_dialog")
    if _clock(ph) != t0:
        msgs.append("房间→招募弹窗 切换把停留时钟清零了（应算仍在共斗房序列里）")
    _feed(ph, "phantom_coop_room")
    if _clock(ph) != t0:
        msgs.append("招募弹窗→房间 切换把停留时钟清零了（应算仍在共斗房序列里）")

    # (c) 真正离开的房间状态【必须】清零（否则队友到了、开了战还判「停留超时」会误收工）。
    for st in ph._COOP_LEAVE_STATES:
        _fresh_session(ph)
        _feed(ph, "phantom_coop_room")
        if not _clock(ph):
            msgs.append(f"state={st}: 前置房间帧没有起算时钟（守卫前提不成立）")
            continue
        _feed(ph, st)
        if _clock(ph) != 0.0:
            msgs.append(
                f"真正离开的房间状态 state={st} 没有清零停留时钟"
                f"（正常推进的协力关会被误判成停留超时）"
            )

    # (d) 过渡帧绝不能出现在 leave 集里（否则 #47 缺陷复发）。
    for st in ("loading", "unknown"):
        if st in ph._COOP_LEAVE_STATES:
            msgs.append(f"过渡帧 {st} 被当成「已离开房间」（_COOP_LEAVE_STATES）→ #47 缺陷复发")
    return msgs


def probe_coop_dwell_clock_sticky() -> bool:
    return _clock_failures(phantom_module()) == []


# ---------------------------------------------------------------------------
# 守卫 2：离线复现 Q2 循环 → 有界收工真的会触发（且刚进房不误收工）
# ---------------------------------------------------------------------------
def _bounded_stop_repro_failures(ph) -> list[str]:
    msgs: list[str] = []

    # (a) 复现 Q2：房间起算 → 8 次 (挑战 -> loading -> 房间) → 时钟【一次都不能被清零】。
    _fresh_session(ph)
    _feed(ph, "phantom_coop_room")
    t0 = _clock(ph)
    for _ in range(8):
        _feed(ph, "loading")
        _feed(ph, "phantom_coop_room")
    if _clock(ph) != t0:
        msgs.append("8 次『房间→挑战→loading→房间』中有一次把停留时钟清零了（#47 缺陷未修）")

    # (b) 把时钟倒拨到已超过 coop_room_sec，再喂一帧「挑战后的 loading」——
    #     旧实现会在这一帧清零 → 永远收不了工；新实现必须保持 → 下一帧房间上命中收工。
    with ph._LOCK:
        ph._SESSION["coop_room_first_ts"] = time.monotonic() - 300.0
    _feed(ph, "loading")  # ← 就是这一帧把旧实现打败了
    after = _clock(ph)
    if after == 0.0 or after > time.monotonic() - 250.0:
        msgs.append(
            "已超时的共斗房时钟被『挑战后的 loading』帧清零/重置 → 有界收工永远到不了"
            "（会被 180s 的 PhantomStall 抢走并强杀重启）"
        )

    # (c) 现在在房间帧上驱动真实 PhantomGiveUpRecognition → 必须命中、且点名共斗房。
    hit, reason = _drive_giveup(ph, state="phantom_coop_room", coop_room_sec=120.0, backdate=300.0)
    if not hit:
        msgs.append("共斗房停留 300s（>120s）仍未命中收工（房间长时间开不了战却不收工 = 空转）")
    if "共斗房" not in reason or "仍未能开战" not in reason:
        msgs.append(f"收工原因未点明『共斗房…仍未能开战』：{reason!r}")

    # (d) 反例：刚进房不久不得误收工。
    hit_fresh, reason_fresh = _drive_giveup(
        ph, state="phantom_coop_room", coop_room_sec=120.0, backdate=1.0
    )
    if hit_fresh:
        msgs.append(f"刚进共斗房就误收工：{reason_fresh!r}")

    # (e) 另一条分支：开战后（房间帧之后紧跟战斗帧）时钟被清零 → 不误收工。
    _fresh_session(ph)
    _feed(ph, "phantom_coop_room")
    _feed(ph, "phantom_battle")  # 队友到了、挑战可用 → 开战
    if _clock(ph) != 0.0:
        msgs.append("开战（phantom_battle）后停留时钟没有清零 → 正常协力关会被误判成停留超时")
    return msgs


def probe_coop_bounded_stop_repro() -> bool:
    return _bounded_stop_repro_failures(phantom_module()) == []


# ---------------------------------------------------------------------------
# 守卫 3：超时是【优雅收工】(StopTask)，且绝不落在 phantom_restart 强杀重启上
# ---------------------------------------------------------------------------
def _stop_not_restart_failures(root: Path | None = None) -> list[str]:
    files = load_files(root)
    msgs: list[str] = []

    node = _node("PhantomGiveUp", files) or {}
    if _custom(node) != "phantom_giveup":
        msgs.append(f"PhantomGiveUp.custom_recognition 应为 phantom_giveup，实际 {_custom(node)!r}")
    action = node.get("action") or {}
    if action.get("type") != "StopTask":
        msgs.append(f"PhantomGiveUp 的动作应为 StopTask（优雅收工），实际 {action.get('type')!r}")
    cp = _custom_param(node)
    try:
        sec = float(cp.get("coop_room_sec"))
    except (TypeError, ValueError):
        msgs.append(f"PhantomGiveUp 未声明 coop_room_sec（共斗房没有有界出口）：{cp.get('coop_room_sec')!r}")
    else:
        if sec <= 0:
            msgs.append(f"PhantomGiveUp 的 coop_room_sec 应为正数，实际 {sec}")

    disp = _node("PhantomDispatch", files) or {}
    nxt = list(disp.get("next") or [])
    if "PhantomGiveUp" not in nxt or "PhantomStall" not in nxt:
        msgs.append("PhantomDispatch.next 缺少 PhantomGiveUp / PhantomStall")
    elif nxt.index("PhantomGiveUp") > nxt.index("PhantomStall"):
        msgs.append(
            "PhantomGiveUp 排在 PhantomStall 之后 → 180s 的卡死兜底会先命中并强杀重启（#47）"
        )

    stall = _node("PhantomStall", files) or {}
    stall_action = ((stall.get("action") or {}).get("param") or {}).get("custom_action")
    if stall_action != "phantom_restart":
        msgs.append(
            f"PhantomStall 不再是 phantom_restart（prove-red 前提不成立）：{stall_action!r}"
        )
    return msgs


def probe_coop_stop_not_restart() -> bool:
    return _stop_not_restart_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：另一条分支（队友到了 → 开战 → 推进）保持连通
# ---------------------------------------------------------------------------
def _advance_path_failures(root: Path | None = None) -> list[str]:
    files = load_files(root)
    msgs: list[str] = []

    node = _node("PhantomCoopChallenge", files) or {}
    act = (node.get("action") or {}).get("param") or {}
    cp = act.get("custom_action_param") or {}
    expect = list(cp.get("expect") or [])
    if "phantom_battle" not in expect:
        msgs.append(f"PhantomCoopChallenge.expect 丢了 phantom_battle（开了战也不认）：{expect}")
    if "loading" not in expect:
        msgs.append(f"PhantomCoopChallenge.expect 丢了 loading（点挑战后的过渡帧）：{expect}")
    if "phantom_coop_room" in expect:
        msgs.append(f"PhantomCoopChallenge.expect 又把 phantom_coop_room 当成功（#30 修过的回退）：{expect}")

    for name in ("PhantomBattleWait", "PhantomCoopRecruit", "PhantomRecruitStart"):
        if _node(name, files) is None:
            msgs.append(f"共斗房推进链缺节点 {name}")

    disp = _node("PhantomDispatch", files) or {}
    nxt = list(disp.get("next") or [])
    for name in ("PhantomCoopRecruit", "PhantomRecruitStart", "PhantomCoopChallenge", "PhantomBattleWait"):
        if name not in nxt:
            msgs.append(f"{name} 不在 PhantomDispatch.next 里（另一条分支走不到）")
    return msgs


def probe_coop_advance_path_intact() -> bool:
    return _advance_path_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_47.py`）
# ---------------------------------------------------------------------------
#: 修好后的时钟规则片段（prove-red 把它换成旧形态）。
_FIX_ANCHOR = "    elif state in _COOP_LEAVE_STATES:"
_BREAK_ANCHOR = "    else:"


def _module_from_source(src: str, name: str):
    mod = types.ModuleType(name)
    mod.__file__ = str(AGENT_DIR / "phantom_impl.py")
    mod.__package__ = ""
    sys.modules[name] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)  # noqa: S102
    return mod


def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook47_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    shutil.copytree(
        REPO_ROOT / "assets" / "resource" / "pipeline",
        root / "assets" / "resource" / "pipeline",
    )
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prove_red() -> bool:
    print("hooks_47 prove-red：两处破坏，要求守卫各自变红")
    green = (
        probe_coop_dwell_clock_sticky() is True
        and probe_coop_bounded_stop_repro() is True
        and probe_coop_stop_not_restart() is True
        and probe_coop_advance_path_intact() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：时钟不被过渡帧清零 + 有界收工 + 不重启 + 推进链连通（绿）")
    if not green:
        return False

    # (a) 把时钟规则倒回旧形态（非房间即清零）→ 守卫 1/2 变红（复现 #47）。
    src = (AGENT_DIR / "phantom_impl.py").read_text(encoding="utf-8")
    if _FIX_ANCHOR not in src:
        print(f"  [FAIL] 找不到修复锚点（守卫已与实现脱节）：{_FIX_ANCHOR!r}")
        return False
    broken_src = src.replace(_FIX_ANCHOR, _BREAK_ANCHOR, 1)
    broken = _module_from_source(broken_src, "_phantom_impl_hook47_broken")
    msgs1 = _clock_failures(broken)
    msgs2 = _bounded_stop_repro_failures(broken)
    red_a = bool(msgs1) and bool(msgs2)
    tail = f"  {msgs1[0] if msgs1 else (msgs2[0] if msgs2 else '（守卫没抓到！）')}"
    print(
        f"  [{'PASS' if red_a else 'FAIL'}] 时钟倒回『非房间即清零』旧形态 -> "
        f"{'红（loading 帧清零 = #47 复现）' if red_a else '仍绿'}{tail}"
    )

    # (b) 把 PhantomDispatch.next 里的 GiveUp/Stall 调换顺序 → 守卫 3 变红（卡死兜底先强杀）。
    root = _temp_assets()
    try:
        _sub(
            root / _PIPELINE_REL / _SD,
            '            "PhantomGiveUp",\n            "PhantomStall",\n',
            '            "PhantomStall",\n            "PhantomGiveUp",\n',
        )
        msgs3 = _stop_not_restart_failures(root)
        red_b = len(msgs3) > 0
        tail_b = f"  {msgs3[0]}" if msgs3 else "  （守卫没抓到！）"
        print(
            f"  [{'PASS' if red_b else 'FAIL'}] 调换 PhantomGiveUp/PhantomStall 顺序 -> "
            f"{'红' if red_b else '仍绿'}{tail_b}"
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "phantom-coop-room-dwell-clock-sticky",
        "#47",
        "共斗房停留时钟不被『挑战后的 loading / unknown』过渡帧清零；房间↔招募弹窗来回不清零；"
        "真正离开（开战/结算/回关卡页…）才清零",
        probe_coop_dwell_clock_sticky,
    ),
    (
        "phantom-coop-room-bounded-stop-repro",
        "#47",
        "离线复现 Q2 循环（房间→挑战→loading→房间×8）：时钟不被清零，倒拨>120s 后真实 "
        "PhantomGiveUp 命中并点名共斗房；刚进房不误收工；开战清零",
        probe_coop_bounded_stop_repro,
    ),
    (
        "phantom-coop-room-stop-not-restart",
        "#47",
        "共斗房超时是 StopTask 优雅收工，且 PhantomGiveUp 排在 PhantomStall（phantom_restart）之前，"
        "绝不重启游戏",
        probe_coop_stop_not_restart,
    ),
    (
        "phantom-coop-room-advance-path-intact",
        "#47",
        "另一条分支连通：PhantomCoopChallenge 仍认 battle/loading，招募/开战节点在链上，"
        "队友到了能开战推进",
        probe_coop_advance_path_intact,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
