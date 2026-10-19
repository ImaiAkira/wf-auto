# -*- coding: utf-8 -*-
"""#59（Phase 1 引擎抽取）：战斗循环 / 账本 / 收工 / 重启机制抽到共享引擎 —— 契约挂点。

seam
----
* ``agent/battle_loop_core.py``（新）：场景无关的引擎（画面分类 / 进度账本 / 会话观察 /
  进度重置 / 出口判定 / 动作后校验 / 强杀重启）+ ``SceneConfig`` + ``make_*`` 工厂。
* ``agent/phantom_impl.py``：**瘦绑定**（常量 + ``partial(_CFG)`` + 类工厂），不再自带状态机逻辑。

三个守卫（对应本票的三条不变量；prove-red 见文末）：

1. ``engine-extracted-to-core``  —— 引擎在 ``battle_loop_core``；``phantom_impl`` 的
   ``classify`` / ``_observe`` / … 是 **core 对象的 ``partial(_CFG)`` 绑定**（同一份实现，
   ``partial.func is core.*``），``_SESSION`` / ``_LOCK`` 是 core 的按 scene 分槽对象
   （``is`` 同一对象），5 个类由 core 工厂生成（``__module__ == "battle_loop_core"``）。
2. ``phantom-impl-no-duplicated-engine-logic``  —— ``agent/phantom_impl.py`` 的**源码里
   不得再出现**引擎逻辑的实现（``def classify/_observe/_sync_task/_handle_possible_reset/
   _scan_sets/…``、``ledger.mark_done/scope/reset/is_done``、``_SESSION = {…}``、
   ``threading.Lock()``、手写的 ``class Phantom*Recognition(...)``）：这些只允许在 core。
   这条是「抽取」而非「复制」的机器可验证判据。
3. ``phantom-behaviour-delegates``  —— 行为仍走 core：``ph.classify(f) ==
   core.classify(ph._CFG, f)``（代表帧），``ph._stage_key`` / ``ph.parse_stage`` 判据一致。

prove-red（``python tools\\contract_hooks\\hooks_phase1.py``）：把引擎逻辑**复制回**
``phantom_impl`` 的源码副本 → 守卫 2 必须变红（红 = 可用信号）。这是 in-module、
确定性的破坏实验（不依赖子进程/网络）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：不抢其它 hook / 测试已经放好的路径。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)


def _phantom_src() -> str:
    return (AGENT_DIR / "phantom_impl.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 守卫 2 的判据（纯函数，便于 prove-red 直接喂坏源码）：这些「引擎实现」的痕迹
# 只许出现在 core，绝不许在薄壳里复现。
# ---------------------------------------------------------------------------
_IMPLEMENTATION_SIGNALS = (
    # 状态机 / 账本 / 观察 / 重置 / 出口：实现函数绝不在薄壳里重定义
    "def classify(",
    "def parse_stage(",
    "def _observe(",
    "def _sync_task(",
    "def _handle_possible_reset(",
    "def _scan_sets(",
    "def _scan_completed_sets(",
    "def _recover_counters(",
    "def _stage_key(",
    "def _set_done_key(",
    "def run_done_key(",
    "def _mark_run_done(",
    "def _set_target(",
    "def _read_target(",
    "def _read_stage_cap(",
    "def _set_stage_cap(",
    "def _read_mode(",
    "def _current_set_recorded_progress(",
    "def _is_level_gate(",
    "def _bottom_texts(",
    "def pick(",
    "def _pick(",
    # 账本读写：薄壳不得直接碰 ledger
    "import progress",
    "ledger.mark_done(",
    "ledger.reset(",
    "ledger.scope(",
    "ledger.is_done(",
    # 会话 / 锁：必须来自 core.session / core.lock，不得自建
    "_SESSION = {",
    "threading.Lock()",
    # 类：必须由 core.make_* 生成，不得手写
    "class PhantomStateRecognition(",
    "class PhantomDoneRecognition(",
    "class PhantomGiveUpRecognition(",
    "class PhantomActAction(",
    "class PhantomRestartAction(",
    "def analyze(",
    "def run(",
)


def _duplication_failures(src: str) -> list[str]:
    """返回薄壳源码里出现的「引擎实现」痕迹（空 = 干净 = 已抽取）。"""
    return [sig for sig in _IMPLEMENTATION_SIGNALS if sig in src]


def probe_phantom_no_duplication() -> bool:
    """#59：``phantom_impl.py`` 不再自带引擎逻辑（只在 core）。"""
    return _duplication_failures(_phantom_src()) == []


# ---------------------------------------------------------------------------
# 守卫 1：引擎在 core；薄壳是 partial 绑定 / 同一对象 / 工厂类
# ---------------------------------------------------------------------------
def probe_engine_extracted_to_core() -> bool:
    import functools  # noqa: PLC0415

    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415

    # core 必须真的提供引擎（不是把逻辑留在薄壳）。
    for name in (
        "classify", "parse_stage", "observe", "sync_task", "handle_possible_reset",
        "scan_sets", "scan_completed_sets", "recover_counters", "stage_key",
        "set_done_key", "pick", "session", "lock", "ocr", "grab", "click_box",
        "make_state_reco", "make_done_reco", "make_giveup_reco", "make_act_action",
        "make_restart_action", "SceneConfig",
    ):
        if not hasattr(core, name):
            return False

    # 场景绑定：薄壳函数必须是 core 同名对象的 functools.partial（同一份实现，签名不变）。
    for attr, target in (
        ("classify", core.classify),
        ("parse_stage", core.parse_stage),
        ("_observe", core.observe),
        ("_sync_task", core.sync_task),
        ("_handle_possible_reset", core.handle_possible_reset),
        ("_scan_sets", core.scan_sets),
        ("_scan_completed_sets", core.scan_completed_sets),
        ("_recover_counters", core.recover_counters),
        ("_stage_key", core.stage_key),
        ("_set_done_key", core.set_done_key),
        ("_mark_run_done", core.mark_run_done),
        ("_read_target", core.read_target),
        ("_read_stage_cap", core.read_stage_cap),
        ("_set_stage_cap", core.set_stage_cap),
        ("_set_target", core.set_target),
    ):
        got = getattr(ph, attr)
        if not isinstance(got, functools.partial) or got.func is not target:
            return False
        if got.args != (ph._CFG,):
            return False

    # 纯直通：同一对象（不是又包一层）。
    if ph._pick is not core.pick:
        return False
    if ph._grab is not core.grab:
        return False

    # 会话 / 锁：与 core 内部使用的是同一对象（测试可直接改键）。
    if ph._SESSION is not core.session(ph._CFG):
        return False
    if ph._LOCK is not core.lock(ph._CFG):
        return False

    # 类：由 core 工厂生成（定义在 battle_loop_core），名字保持旧名。
    for attr, old_name in (
        ("PhantomStateRecognition", "PhantomStateRecognition"),
        ("PhantomDoneRecognition", "PhantomDoneRecognition"),
        ("PhantomGiveUpRecognition", "PhantomGiveUpRecognition"),
        ("PhantomActAction", "PhantomActAction"),
        ("PhantomRestartAction", "PhantomRestartAction"),
    ):
        cls = getattr(ph, attr, None)
        if cls is None or cls.__module__ != "battle_loop_core" or cls.__name__ != old_name:
            return False
    return True


# ---------------------------------------------------------------------------
# 守卫 3：行为仍走 core（代表帧判据一致 + 账本 key 判据一致）
# ---------------------------------------------------------------------------
def probe_behaviour_delegates() -> bool:
    import battle_loop_core as core  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415

    frames = [
        [
            ("不可续战", [300, 980, 90, 30]),
            ("推荐编成", [55, 1105, 97, 29]),
            ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
            ("第3关", [345, 131, 90, 30]),
            ("战斗", [300, 700, 60, 30]),
        ],
        [("时间 09:53", [300, 1200, 80, 30]), ("分数 0000001", [430, 1200, 120, 30])],
        [("QUESTRESULT", [180, 380, 360, 60]), ("OK", [330, 640, 60, 30])],
        [("房间号码", [276, 1184, 94, 28]), ("招募", [352, 808, 72, 41]), ("复制", [540, 1230, 48, 31])],
        [("玩家等级达到130后，解锁幻想连战与深渊连战。", [100, 800, 500, 80])],
    ]
    for f in frames:
        if ph.classify(list(f)) != core.classify(ph._CFG, list(f)):
            return False
    # 账本 key / 关卡解析判据。
    if ph._stage_key(3, 7) != "phantom/set/3/stage/7":
        return False
    if ph._set_done_key(2) != "phantom/set/2/completed":
        return False
    if ph.parse_stage([("第3关", [345, 131, 90, 30])]) != 3:
        return False
    if ph.parse_stage([("推荐编成", [55, 1105, 97, 29])]) is not None:
        return False
    return True


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_phase1.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    print("hooks_phase1 prove-red：把引擎逻辑复制回 phantom_impl 源码副本 → 守卫 2 必须变红")
    green = (
        probe_engine_extracted_to_core() is True
        and probe_phantom_no_duplication() is True
        and probe_behaviour_delegates() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：引擎在 core + 薄壳无重复 + 行为委派（绿）")
    if not green:
        return False

    real_src = _phantom_src()
    ok = green and _duplication_failures(real_src) == []
    print(f"  [{'PASS' if ok else 'FAIL'}] 真实 phantom_impl.py 源码无引擎实现痕迹（绿）")

    # 把一段引擎实现（账本 + def）复制回薄壳 → 守卫 2 必须抓到。
    broken_src = real_src + (
        "\n\n"
        "def _sync_task(task_id):\n"
        "    import progress as ledger\n"
        "    ledger.reset('phantom')\n"
        "    _SESSION = {}\n"
    )
    bad = _duplication_failures(broken_src)
    red = bool(bad)
    tail = f"  抓到={bad[:3]}" if bad else "  （守卫没抓到！）"
    print(f"  [{'PASS' if red else 'FAIL'}] 复制回引擎逻辑 → {'红' if red else '仍绿'}{tail}")

    result = green and red
    print("结果：" + ("★prove-red 成功★" if result else "★prove-red 失败★"))
    return result


HOOKS = [
    (
        "engine-extracted-to-core",
        "#59",
        "战斗循环/账本/收工/重启机制在 battle_loop_core；phantom_impl 的 classify/_observe/… "
        "是 core 对象的 partial(_CFG) 绑定，_SESSION/_LOCK 同一对象，5 个类由 core 工厂生成",
        probe_engine_extracted_to_core,
    ),
    (
        "phantom-impl-no-duplicated-engine-logic",
        "#59",
        "phantom_impl.py 源码里不再出现引擎逻辑实现（def 状态机/账本读写/_SESSION 字面量/"
        "threading.Lock()/手写 Phantom* 类）—— 只有抽取、没有复制",
        probe_phantom_no_duplication,
    ),
    (
        "phantom-behaviour-delegates",
        "#59",
        "行为仍走 core：ph.classify(代表帧) == core.classify(cfg, 帧)；账本 key / 关卡解析判据一致",
        probe_behaviour_delegates,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
