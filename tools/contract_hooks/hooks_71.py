# -*- coding: utf-8 -*-
"""#71 的另一半：★手操持续到结算 / 关卡失败★ —— 契约挂点（自动发现，零改既有文件）。

本文件是 **#71 专属**的一张票守卫文件（``tools/contract_hooks/hooks_71.py``）；既有
``hooks_wuchong.py``（#56）不动，二者互不覆盖 —— 这正是「按票分文件 + 自动发现」的前提。

现场事实（真机帧实证，见 ``agent/battle_loop_core.py`` 的 #46 段）
----------------------------------------------------------------
GAMEOVER /「是否续关?」失败页**底部照样画着战斗 HUD 的「时间 / 分数」**，而失败页的
「放弃 / 续关」那一行（720 y≈1043）与手操弹板点 ``flipper=(360,1067)`` **同一行**。
故「只要还没停手，就会在失败页继续连点 = 真实误点」。所以手操的停止条件必须是
**正面页面判据**（结算 / 关卡失败 / 手操被关 / 认不出让位 / 框架停止），
**不能**是「点 N 秒就交出」（旧 ``duration_s``）—— 那会把长战斗（真机战报出现过
``时间 28:03``）在 25s 处腰斩，且失败页 / 长战斗都会被误处理。

五个守卫（对应本票硬要求；prove-red 见文末）：

1. ``wuchong-71-no-fixed-duration-truncation`` —— **没有固定时长截断**：``run_manual_battle``
   活代码无 ``deadline``、``Cadence`` 无 ``duration|timeout|deadline`` 字段、``impl`` 模块与
   ``scene/wuchong.py`` / ``assets/interface.json`` / ``wuchong.json`` / ``wuchong_impl.py``
   四个文件的**活代码 / 配置**里都不再出现 ``duration_s`` / ``手操连点时长``；离线假时钟推进到
   3600s 仍在点板（t=1800s 累计点击 > t=25s），``stopped`` 永不为 ``"duration"`` 且 ⊆ 四个合法值。
2. ``wuchong-71-verdict-is-positive-and-yields`` —— **判据是三值正面页面判据**（★2026-10-16
   运维裁决★：不再用战斗 HUD）：``page_verdict`` 对 真机双空格战斗帧→continue（继续点）/
   续关屏→over / 结算页→over / 加载页→continue / 编队页→left 逐条正判（续关屏**先于**
   「还在战斗」被接走 = 反回归；续关屏底部照样画着 HUD）；判据只有一份。
3. ``wuchong-71-hud-anchors-single-source`` —— **战斗 HUD 锚点单一真源**：
   ``scene.auto_switch.BATTLE_HUD_ANCHORS`` 与 ``battle_loop_core`` 的 ``BATTLE_HUD_TIME_RE`` /
   ``BATTLE_HUD_SCORE_RE`` **字面相等**（HUD 判据仍被别处如 ``SpecialBattleWait`` 使用，故不删）；
   ``is_battle_hud`` 对真机双空格帧 True、对结算样例（``战斗分数`` / ``最长滞空时间6秒``）False。
4. ``wuchong-71-long-battle-is-progress`` —— **长战斗是进展**（本票关键回归）：真机同屏出现过
   ``时间 28:03``，而 ``WuchongGiveUp.no_progress_sec=900`` 会把 15 分钟的战斗判成「无进展」→ 收工；
   驱动**真实** ``WuchongGiveUpRecognition``：观测战斗页刷新 ``last_progress_ts`` → 不收工；
   去掉「战斗算进展」→ 同一帧命中（守卫有灵敏度，可自证）。
5. ``wuchong-71-heartbeat-and-stopped-vocabulary`` —— **持续可观测的验收证据 + stopped 词表**：
   ``run_manual_battle`` 含「心跳」日志且活代码无 ``duration``/``deadline``；``stopped`` 的合法取值
   不含 ``"duration"``；跨越一个心跳周期 stdout 出现「心跳 t=+」并刷新 ``last_progress_ts``。

★关于静态文本扫描的口径（诚实交代）★
-----------------------------------
`duration_s` / `手操连点时长` 这两个字符串**确实**还出现在上列文件里，但**只在注释 / docstring**
（如「已删『手操连点时长』」这类交代历史的话），不是**被使用的字段 / 参数**。因此静态扫描先
去掉注释与 docstring（``ast.unparse`` 天然丢注释，再显式剔 docstring；JSON 走 ``//`` 注释剥离），
只对**活代码 / 真配置**下判断 —— 这既守住了「不得重新引入固定时长旋钮」的意图，又不会把
「说明它被删除」的注释误判成违规（``docs/spec/wuchong-spec.md`` 是历史规格，本就放过）。
真正的牙齿在**行为**断言（假时钟推进到 3600s / 心跳 / 长战斗），静态只是补充。

prove-red（``python tools\\contract_hooks\\hooks_71.py``）：逐一改坏实现，要求守卫各自变红。
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import inspect
import io
import json
import re
import sys
import textwrap
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

#: 「手操持续到结算 / 关卡失败」的**合法** ``stopped`` 取值（run_manual_battle 的正面出口）。
#: ★2026-10-16 运维裁决★：``hud_miss``（连续不见 HUD）与 ``yield``（认不出页面让位）**已删**
#: —— 认不出的帧一律继续点；新增 ``left``（被推出战斗）。
LEGAL_STOPPED = ("manual_off", "battle_over", "left", "stopped")

#: 静态扫描要「放过」的历史规格（#71 的旧规格照旧描述 duration 截断，必须放过）。
_EXEMPT_FILES = ("docs/spec/wuchong-spec.md",)

#: G1 要扫描的四个文件（活代码 / 配置口径）：不得再出现固定时长旋钮。
DURATION_WATCHED_FILES = (
    "scene/wuchong.py",
    "assets/interface.json",
    "assets/resource/pipeline/wuchong.json",
    "agent/wuchong_impl.py",
)


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


# ---------------------------------------------------------------------------
# 文本归一化：只留「活代码 / 真配置」，去掉注释与 docstring
# ---------------------------------------------------------------------------
def _py_code_text(src: str) -> str:
    """把 Python 源码归一成「活代码文本」：去掉注释（``ast`` 天然不产出）与 docstring。

    做法：``ast.parse`` 后把 模块 / 类 / 函数 体部的**首条字符串表达式**（docstring）剔除，
    再 ``ast.unparse``。注释在 AST 里本就不存在，故一并消失。这样「已删 duration_s」这类
    交代历史的注释不会误判成违规，而被真正**使用**的标识符 / 字符串字面量仍会被看到。
    """
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return ast.unparse(tree)


def _strip_jsonc(text: str) -> str:
    """剥掉 JSONC 的 ``//`` 行注释与 ``/* */`` 块注释（自带一份，不 import 别的守卫模块）。"""
    out: list[str] = []
    state = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i:i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i:i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i:i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def _file_active_text(rel: str) -> str:
    """读仓库内相对路径文件并归一成「活代码 / 真配置」文本（.py 去注释与 docstring，JSON 去注释）。"""
    path = REPO_ROOT / rel
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return _py_code_text(src)
    return _strip_jsonc(src)


def _stopped_literals(src: str) -> set:
    """从源码里收集**流进 ``stopped`` 的字符串字面量**（``stopped = "..."`` 或 dict 值 ``"stopped": "..."``）。

    精确到 ``stopped`` 的取值，是为了避免把 MAA Swipe 动作里合法的 ``"duration"`` 键
    （``{"duration": int(duration_ms)}``）误判成 ``stopped`` 的取值。
    """
    tree = ast.parse(textwrap.dedent(src))
    vals: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "stopped" and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str):
                        vals.add(node.value.value)
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "stopped"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                ):
                    vals.add(v.value)
    return vals


# ---------------------------------------------------------------------------
# 合成 OCR 帧（离线逐帧求值；形态取自真机帧）
# ---------------------------------------------------------------------------
#: ★真机双空格战斗帧★（来源：tools/contract_hooks/hooks_auto_outside.BATTLE_HUD_ITEMS 同形态）：
#: ``分数`` 后是**两个空格** + 一长串数字；``时间`` 在底部条带。
BATTLE_FRAME = [
    ("分数  00166756407", [195, 1222, 241, 36]),
    ("时间 09:55", [37, 1225, 128, 32]),
]

#: 失败页（#46 现场）：``GAMEOVER`` + 「是否续关?」，**底部照样有** 时间 / 分数（同 BATTLE_FRAME 的 HUD）。
FAIL_FRAME = [
    ("GAMEOVER", [300, 400, 200, 60]),
    ("是否续关?", [300, 700, 200, 50]),
    ("放弃", [250, 1043, 120, 50]),
    ("时间 09:55", [37, 1225, 128, 32]),
    ("分数  00166756407", [195, 1222, 241, 36]),
]

#: 结算页：含「战斗分数」「最长滞空时间6秒」—— ★绝不能当战斗★（裸「时间/分数」会误判，见 core 注释）。
SETTLE_FRAME = [
    ("QUESTRESULT", [500, 300, 300, 60]),
    ("战斗分数", [300, 800, 200, 40]),
    ("最长滞空时间6秒", [400, 600, 200, 40]),
    ("返回房间", [400, 900, 150, 50]),
]

#: 加载 / 过场页。
LOADING_FRAME = [("请耐心等待", [200, 500, 300, 40])]

#: 编队页（单人 / 多人共用的队伍页）：``Party E`` 槽位 + 【挑战】。
TEAM_FRAME = [("Party E", [100, 400, 200, 40]), ("挑战", [300, 1100, 120, 50])]


class _RecArgv:
    """最小 ``CustomRecognition`` 入参桩（image + task_detail.task_id + custom_recognition_param）。"""

    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


# ---------------------------------------------------------------------------
# 守卫 1：没有固定时长截断（静态 + 行为）
# ---------------------------------------------------------------------------
def _duration_static_failures(mod) -> list:
    """静态：run_manual_battle / Cadence / impl 模块 / 四个文件的**活代码 / 配置**里无固定时长旋钮。"""
    msgs: list[str] = []

    code = _py_code_text(inspect.getsource(mod.run_manual_battle))
    if "deadline" in code:
        msgs.append("run_manual_battle 活代码里仍有 deadline（固定时长截断残留）")

    fields = [f.name for f in dataclasses.fields(mod.Cadence)]
    bad = [f for f in fields if re.search(r"duration|timeout|deadline", f)]
    if bad:
        msgs.append(f"Cadence 仍有固定时长字段（duration|timeout|deadline）：{bad}")

    impl_code = _py_code_text(Path(mod.__file__).read_text(encoding="utf-8"))
    if "duration_s" in impl_code:
        msgs.append("wuchong_impl 活代码里仍有 duration_s")

    for rel in DURATION_WATCHED_FILES:
        if rel in _EXEMPT_FILES:
            continue
        active = _file_active_text(rel)
        for needle in ("duration_s", "手操连点时长"):
            if needle in active:
                msgs.append(f"{rel} 的活代码 / 配置里仍出现 {needle!r}（固定时长截断残留）")
    return msgs


def _run_long_battle(run_fn, mod, stop_at: float = 3600.0):
    """用假时钟 / 假副作用驱动一次手操战斗：verdict 恒 ``battle`` 直到 ``stop_at`` 秒后转 ``battle_over``。

    返回 ``(transcript, log)``；``log`` 是 ``(t, 累计点击数)`` 序列，供「t=1800s 累计 > t=25s」断言。
    """
    state = {"t": 0.0, "taps": 0}
    log: list = []

    def now():
        return state["t"]

    def burst_click(point, times, gap):
        # 一次原生连点：times 下 × gap 毫秒 / 下（进度条式推进假时钟）
        state["t"] += (int(times) * int(gap)) / 1000.0
        state["taps"] += int(times)
        log.append((state["t"], state["taps"]))

    def verdict():
        return mod.PAGE_CONTINUE if state["t"] < stop_at else mod.PAGE_OVER

    hooks = mod.BattleHooks(
        burst_click=burst_click,
        swipe=lambda begin, end, ms: None,
        verdict=verdict,
        manual_on=lambda: True,
        sleep=lambda sec: None,
        now=now,
        stopping=lambda: False,
    )
    cadence = mod.Cadence(
        center=(360, 600), flipper=(360, 1067), dist=160, swipe_ms=300,
        flipper_gap_ms=220, skill_gap_ms=0, skill_every=0, burst=10,
        check_min_gap_ms=2000,
    )
    # 长战斗驱动会打出大量心跳日志：这里静音（心跳本身另由 G5 的 _run_heartbeat 专门取证）。
    with contextlib.redirect_stdout(io.StringIO()):
        return run_fn(hooks, cadence), log


def _taps_at(log, t: float) -> int:
    """log 里 t 时刻（<= t）的累计点击数。"""
    val = 0
    for ts, taps in log:
        if ts <= t:
            val = taps
        else:
            break
    return val


def _duration_long_battle_failures(mod, run_fn=None, stop_at: float = 3600.0) -> list:
    """行为：推进到 3600s 仍在点板（t=1800s 累计 > t=25s），且 stopped 永不为 duration、⊆ 五合法值。"""
    run_fn = run_fn or mod.run_manual_battle
    result, log = _run_long_battle(run_fn, mod, stop_at=stop_at)
    msgs: list[str] = []

    stopped = result.get("stopped")
    if stopped == "duration":
        msgs.append('stopped == "duration"（固定时长截断仍在 —— 长战斗 / 失败页会被腰斩）')
    if stopped not in LEGAL_STOPPED:
        msgs.append(f"stopped={stopped!r} 不在合法取值 {list(LEGAL_STOPPED)} 内")

    taps_25 = _taps_at(log, 25.0)
    taps_1800 = _taps_at(log, 1800.0)
    if taps_25 <= 0:
        msgs.append("25s 前一次弹板都没点（驱动无效）")
    if not (taps_1800 > taps_25):
        msgs.append(
            f"t=1800s 累计点击 {taps_1800} 未 > t=25s 的 {taps_25}（仍被旧 25s 截断，手操未持续到结算）"
        )
    return msgs


def probe_wuchong_71_no_fixed_duration_truncation() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _duration_static_failures(impl) == [] and _duration_long_battle_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 2：判据是正面页面判据（三值）+ 与单源一致（含 F1 反回归）
# ---------------------------------------------------------------------------
def _verdict_failures(mod) -> list:
    _paths()
    import battle_loop_core as core  # noqa: PLC0415

    msgs: list[str] = []
    # ★2026-10-16 运维裁决★：判据三值 —— over（续关屏 / 结算页）/ left（被推出战斗）/ continue
    #   （其余一切，含真战斗帧 / unknown / loading → 继续点）。★不再用战斗 HUD 判据★。
    cases = (
        (BATTLE_FRAME, mod.PAGE_CONTINUE, "真机双空格战斗帧（→ 继续点）"),
        (FAIL_FRAME, mod.PAGE_OVER, "续关屏（GAMEOVER + 是否续关? + 底部时间/分数）"),
        (SETTLE_FRAME, mod.PAGE_OVER, "结算页（QUESTRESULT / 战斗分数 / 返回房间）"),
        (LOADING_FRAME, mod.PAGE_CONTINUE, "加载页（请耐心等待 → 继续点，绝不停手）"),
        (TEAM_FRAME, mod.PAGE_LEFT, "编队页（Party E + 挑战 → 被推出战斗）"),
    )
    for items, want, label in cases:
        got = mod.page_verdict(items)
        if got != want:
            msgs.append(f"{label} 判据错误：page_verdict={got!r}，期望 {want!r}")

    # ★反回归（承重）★：续关屏底部照样画着战斗 HUD（时间/分数）——「先判 HUD」的旧实现会把它
    #   当「还在战斗」→ 在续关屏继续连点（那一行与弹板点同一行）。续关屏必须最先被接走(=over)。
    if not core.is_battle_hud(FAIL_FRAME):
        msgs.append("续关屏样例：battle_loop_core.is_battle_hud 竟为 False（反回归样例失效）")
    if mod.page_verdict(FAIL_FRAME) != mod.PAGE_OVER:
        msgs.append("续关屏（底部有 HUD）竟未被判 over —— 「先判 HUD」回归（续关屏会被继续连点）")

    # ★语义一致性（判据只有一份）★：真机战斗帧上 is_battle_hud 与 classify 不得与 page_verdict 矛盾。
    if not core.is_battle_hud(BATTLE_FRAME):
        msgs.append("真机双空格战斗帧：battle_loop_core.is_battle_hud 竟为 False（判据分叉）")
    state, _info = mod.classify(BATTLE_FRAME)
    if state != "wuchong_battle":
        msgs.append(f"真机双空格战斗帧：impl.classify={state!r} != 'wuchong_battle'（与 page_verdict 矛盾）")
    if mod.page_verdict(BATTLE_FRAME) != mod.PAGE_CONTINUE:
        msgs.append("真机双空格战斗帧：page_verdict 不是 continue（引擎会误停手）")
    return msgs


def probe_wuchong_71_verdict_is_positive_and_yields() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _verdict_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 3：战斗 HUD 锚点单一真源
# ---------------------------------------------------------------------------
def _anchors_failures(scene_mod=None) -> list:
    _paths()
    import battle_loop_core as core  # noqa: PLC0415
    from scene import auto_switch as scene_auto  # noqa: PLC0415

    sm = scene_mod if scene_mod is not None else scene_auto
    msgs: list[str] = []

    expect = (core.BATTLE_HUD_TIME_RE, core.BATTLE_HUD_SCORE_RE)
    got = tuple(getattr(sm, "BATTLE_HUD_ANCHORS", ()))
    if got != expect:
        msgs.append(
            f"scene.auto_switch.BATTLE_HUD_ANCHORS={got!r} 与 battle_loop_core 的 "
            f"(TIME_RE, SCORE_RE)={expect!r} 不字面相等（判据分叉 = 两个真源）"
        )

    if not core.is_battle_hud(BATTLE_FRAME):
        msgs.append("is_battle_hud 对真机双空格战斗帧竟为 False")
    if core.is_battle_hud(SETTLE_FRAME):
        msgs.append("is_battle_hud 对结算页样例（战斗分数 / 最长滞空时间6秒）竟为 True（会把结算当战斗）")
    return msgs


def probe_wuchong_71_hud_anchors_single_source() -> bool:
    return _anchors_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：长战斗是进展（驱动真实 WuchongGiveUpRecognition）
# ---------------------------------------------------------------------------
def _reset_session(mod, tid, backdate: float) -> None:
    """把会话摆成「刚进战斗、已 901s 无进展」的现场（room_first_ts/unknown 清零，其余照既有守卫）。"""
    with mod._LOCK:
        mod._SESSION["task_id"] = tid
        mod._SESSION["start_ts"] = time.monotonic()
        mod._SESSION["last_progress_ts"] = time.monotonic() - float(backdate)
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["unknown_count"] = 0
        mod._SESSION["last_state"] = None
        mod._SESSION["last_observe_ts"] = 0.0
        mod._SESSION["fights_done"] = 0


def _run_giveup_once(mod, tid: str):
    """用战斗帧驱动真实收工识别器一次（不动会话其余字段）；返回 ``(是否命中, reason)``。"""
    real_ocr = mod._ocr
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(BATTLE_FRAME)
        res = mod.WuchongGiveUpRecognition().analyze(
            None, _RecArgv(tid, {"ocr_entry": "OcrTask", "no_progress_sec": 900})
        )
        return (res.box == [0, 0, 0, 0]), str((res.detail or {}).get("reason") or "")
    finally:
        mod._ocr = real_ocr


def _make_no_battle_observe(mod):
    """一份「等价但不含战斗进展」的 ``_observe``：除掉 ``WUCHONG_BATTLE`` 后，长战斗会被判无进展。

    用于 ② 反向自证与 prove-red 破坏实验 —— 证明「战斗算进展」正是这条守卫在守的东西。
    """

    def _observe(state, info, items):  # noqa: N802
        now = time.monotonic()
        with mod._LOCK:
            changed = state != mod._SESSION["last_state"]
            stale = (now - mod._SESSION["last_observe_ts"]) > 1.2
            if not changed and not stale:
                return
            mod._SESSION["last_observe_ts"] = now
            mod._SESSION["last_state"] = state
            # ★不含 WUCHONG_BATTLE★：战斗页不算「有进展」（= 回归形态）。
            if state in (mod.WUCHONG_SETTLE, mod.WUCHONG_TEAM):
                mod._SESSION["last_progress_ts"] = now

    return _observe


def _long_battle_failures(mod) -> list:
    """①观测战斗页刷新进度 → 不收工；②去掉战斗进展 → 同一帧必须收工（守卫有灵敏度）。"""
    msgs: list[str] = []
    tid = 710071

    # ① 连真机长战斗（时间 28:03）都会被 no_progress_sec=900 判无进展 —— 观测战斗页必须刷新进度。
    _reset_session(mod, tid, backdate=901.0)
    mod._observe(mod.WUCHONG_BATTLE, {}, BATTLE_FRAME)
    with mod._LOCK:
        lag = time.monotonic() - mod._SESSION["last_progress_ts"]
    if lag > 5.0:
        msgs.append(f"观测战斗页没有刷新 last_progress_ts（仍滞后约 {lag:.0f}s）")
    hit, reason = _run_giveup_once(mod, tid)
    if hit:
        msgs.append(f"观测到战斗页（真机长战斗 时间 28:03）仍被判「无进展」收工：{reason!r}")

    # ② 反向自证：把「战斗算进展」拿掉后，同一帧必须命中（否则守卫失去意义）。
    saved = mod._observe
    try:
        mod._observe = _make_no_battle_observe(mod)
        _reset_session(mod, tid, backdate=901.0)
        hit2, _r2 = _run_giveup_once(mod, tid)
        if not hit2:
            msgs.append("去掉「战斗算进展」后同一帧竟仍未收工（守卫失去灵敏度，无法自证）")
    finally:
        mod._observe = saved
    return msgs


def probe_wuchong_71_long_battle_is_progress() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _long_battle_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 5：心跳（持续可观测证据）+ stopped 词表
# ---------------------------------------------------------------------------
def _run_heartbeat(run_fn, mod):
    """用假时钟跨越一个心跳周期（BATTLE_HEARTBEAT_MS）驱动一次手操（verdict 恒 battle 到 120s）。"""
    state = {"t": 0.0}

    def now():
        return state["t"]

    def burst_click(point, times, gap):
        state["t"] += (int(times) * int(gap)) / 1000.0

    hooks = mod.BattleHooks(
        burst_click=burst_click,
        swipe=lambda begin, end, ms: None,
        verdict=lambda: mod.PAGE_CONTINUE if state["t"] < 120.0 else mod.PAGE_OVER,
        manual_on=lambda: True,
        sleep=lambda sec: None,
        now=now,
        stopping=lambda: False,
    )
    cadence = mod.Cadence(
        center=(360, 600), flipper=(360, 1067), dist=160, swipe_ms=300,
        flipper_gap_ms=500, skill_gap_ms=0, skill_every=0, burst=10,
        check_min_gap_ms=2000,
    )
    return run_fn(hooks, cadence)


def _heartbeat_failures(mod, run_fn=None) -> list:
    msgs: list[str] = []
    run_fn = run_fn or mod.run_manual_battle

    src = inspect.getsource(mod.run_manual_battle)
    code = _py_code_text(src)
    if "心跳" not in code:
        msgs.append("run_manual_battle 活代码里没有「心跳」日志（持续可观测的验收证据来源缺失）")
    if "duration" in code or "deadline" in code:
        msgs.append("run_manual_battle 活代码里仍含 duration / deadline（固定时长截断残留）")

    stopped_lits = _stopped_literals(src)
    if "duration" in stopped_lits:
        msgs.append('stopped 的合法取值里出现了 "duration"')
    if 'stopped = "duration"' in code:
        msgs.append('impl 源码里仍写死 stopped = "duration"')
    unexpected = stopped_lits - set(LEGAL_STOPPED)
    if unexpected:
        msgs.append(f"stopped 出现非法取值：{sorted(unexpected)}（合法仅 {list(LEGAL_STOPPED)}）")

    # 行为：跨过一个心跳周期，stdout 必须出现「心跳 t=+」，且刷新 last_progress_ts。
    with mod._LOCK:
        mod._SESSION["last_progress_ts"] = 0.0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _run_heartbeat(run_fn, mod)
    out = buf.getvalue()
    if "心跳 t=+" not in out:
        msgs.append("跨越一个心跳周期后 stdout 仍无「心跳 t=+」（无法证明手操持续到结算/失败）")
    with mod._LOCK:
        refreshed = mod._SESSION["last_progress_ts"]
    if not refreshed or (time.monotonic() - refreshed) > 5.0:
        msgs.append("心跳未刷新 _SESSION['last_progress_ts']（长战斗会被收工兜底掐死）")
    return msgs


def probe_wuchong_71_heartbeat_and_stopped_vocabulary() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _heartbeat_failures(impl) == []


# ---------------------------------------------------------------------------
# 破坏件（prove-red 用；自带一份，绝不 import 别的守卫模块的私有类）
# ---------------------------------------------------------------------------
class _BrokenDeadlineBattle:
    """坏实现：按旧「固定时长 25s 截断」交出（``stopped="duration"``）—— 守卫必须抓到。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def run_manual_battle(self, hooks, cadence):  # noqa: N802
        t0 = hooks.now()
        taps = 0
        while hooks.now() - t0 < 25.0:
            hooks.burst_click(tuple(cadence.flipper), max(1, int(cadence.burst)),
                              max(20, int(cadence.flipper_gap_ms)))
            taps += max(1, int(cadence.burst))
        return {"taps": taps, "swipes": [], "checks": 0,
                "stopped": "duration", "reason": "固定时长截断（旧行为）"}


class _BrokenVerdictBattle:
    """坏实现：**先判 HUD**（续关屏底部也有时间/分数 → 被当成「还在战斗」→ continue）= F1 回归。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def page_verdict(self, items):  # noqa: N802
        _paths()
        import battle_loop_core as core  # noqa: PLC0415

        if core.is_battle_hud(items):
            return self._mod.PAGE_CONTINUE
        return self._mod.page_verdict(items)


class _BrokenHudAnchors:
    """坏实现：把战斗 HUD 锚点换成别的串（真源分叉）。"""

    BATTLE_HUD_ANCHORS = (r"时间", r"分数")


class _BrokenNoHeartbeatBattle:
    """坏实现：手操循环去掉心跳打印（也无 _touch_progress）—— 守卫必须抓到。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def run_manual_battle(self, hooks, cadence):  # noqa: N802
        return {"taps": 0, "swipes": [], "checks": 0, "stopped": "battle_over", "reason": ""}


def _destroy_no_battle_progress(impl) -> bool:
    """破坏实验 G4：monkeypatch 掉「战斗算进展」，期望守卫变红（返回 True = 红）。"""
    saved = impl._observe
    impl._observe = _make_no_battle_observe(impl)
    try:
        return len(_long_battle_failures(impl)) > 0
    finally:
        impl._observe = saved


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_71 prove-red：逐一破坏实现，要求守卫各自变红")

    green = (
        probe_wuchong_71_no_fixed_duration_truncation() is True
        and probe_wuchong_71_verdict_is_positive_and_yields() is True
        and probe_wuchong_71_hud_anchors_single_source() is True
        and probe_wuchong_71_long_battle_is_progress() is True
        and probe_wuchong_71_heartbeat_and_stopped_vocabulary() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：五个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # G1：按 deadline 返回 stopped="duration" 的坏手操。
    red = len(_duration_long_battle_failures(
        impl, run_fn=_BrokenDeadlineBattle(impl).run_manual_battle)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 固定时长截断："
          f"25s 处 stopped=\"duration\" -> {'红' if red else '仍绿'}")
    checks.append(red)

    # G2：续关屏也判「还在战斗 / continue」（先判 HUD 的 F1 回归）。
    red = len(_verdict_failures(_BrokenVerdictBattle(impl))) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 判据正面化：续关屏也判 continue（先判 HUD 的 F1 回归）-> "
          f"{'红' if red else '仍绿'}")
    checks.append(red)

    # G3：把战斗 HUD 锚点换成别的串。
    red = len(_anchors_failures(_BrokenHudAnchors)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] HUD 锚点单一真源：换成别的串 -> {'红' if red else '仍绿'}")
    checks.append(red)

    # G4：去掉「战斗算进展」。
    red = _destroy_no_battle_progress(impl)
    print(f"  [{'PASS' if red else 'FAIL'}] 长战斗是进展："
          f"去掉战斗进展 -> {'红' if red else '仍绿'}")
    checks.append(red)

    # G5：手操循环去掉心跳打印。
    red = len(_heartbeat_failures(
        impl, run_fn=_BrokenNoHeartbeatBattle(impl).run_manual_battle)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 心跳 / stopped 词表："
          f"去掉心跳打印 -> {'红' if red else '仍绿'}")
    checks.append(red)

    ok = green and all(checks)
    print("结果：★prove-red 成功★" if ok else "结果：★prove-red 失败★")
    return ok


HOOKS = [
    (
        "wuchong-71-no-fixed-duration-truncation",
        "#71",
        "手操无固定时长截断：run_manual_battle/Cadence/四个文件的活代码与配置里均无 duration_s/手操连点时长；"
        "假时钟推进到 3600s 仍在点（t=1800s 累计 > t=25s），stopped 永不为 duration 且 ⊆ 四合法值",
        probe_wuchong_71_no_fixed_duration_truncation,
    ),
    (
        "wuchong-71-verdict-is-positive-and-yields",
        "#71",
        "手操判据是三值正面页面判据（2026-10-16 运维裁决：不再用战斗 HUD）：续关屏(GAMEOVER/是否续关?，"
        "底部照样有 HUD)→over、结算页→over、加载页→continue（继续点）、编队页→left（被推出战斗）、"
        "真机双空格战斗帧→continue；续关屏最先被接走（反回归）；判据只一份",
        probe_wuchong_71_verdict_is_positive_and_yields,
    ),
    (
        "wuchong-71-hud-anchors-single-source",
        "#71",
        "战斗 HUD 锚点单一真源：scene.auto_switch.BATTLE_HUD_ANCHORS 与 battle_loop_core 的 "
        "TIME/SCORE 正则字面相等；is_battle_hud 对真机双空格帧 True、对结算样例（战斗分数/最长滞空时间）False",
        probe_wuchong_71_hud_anchors_single_source,
    ),
    (
        "wuchong-71-long-battle-is-progress",
        "#71",
        "长战斗是进展：观测战斗页刷新 last_progress_ts，故 28:03 的长战斗不被 no_progress_sec=900 兜底收工；"
        "去掉「战斗算进展」则同一帧命中（守卫有灵敏度、可自证）",
        probe_wuchong_71_long_battle_is_progress,
    ),
    (
        "wuchong-71-heartbeat-and-stopped-vocabulary",
        "#71",
        "持续可观测证据 + stopped 词表：run_manual_battle 含「心跳」日志且活代码无 duration/deadline；"
        "stopped 合法取值不含 duration；跨一个心跳周期 stdout 出现「心跳 t=+」并刷新 last_progress_ts",
        probe_wuchong_71_heartbeat_and_stopped_vocabulary,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
