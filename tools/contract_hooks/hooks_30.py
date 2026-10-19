# -*- coding: utf-8 -*-
"""#30：幻想连战协力关落入共斗房 → 公共打断盲点「挑战」死循环 → 有界收工。

seam
----
* ``assets/resource/pipeline/phantom.json``：
  ``PhantomCoopRecruit`` / ``PhantomRecruitStart`` / ``PhantomCoopChallenge``（门控的共斗房
  节点）与 ``PhantomGiveUp`` 的 ``coop_room_sec``（共斗房停留上限）。
* ``assets/resource/pipeline/special_dungeon.json``：``PhantomDispatch.next`` 里的共斗房节点
  与封锁的打断前缀（``[JumpBack]PubChallenge`` …）。
* ``agent/side_impl.py``：``pubchallenge_override_for`` —— 按种类把公共打断 ``PubChallenge``
  收窄（phantom）／还原（farm/raid/special）。
* ``agent/phantom_impl.py``：``PhantomGiveUpRecognition`` 的共斗房有界出口 + ``classify``。

诊断（真机 Stage D，`--list "幻想连战,-,1"`，127.0.0.1:16385）
------------------------------------------------------------
1. 幻想连战的**协力关**点卡片「战斗」后进入的是【共斗房】（房间号码 / 招募 / 队友），
   不是单人编队页。真机帧 ``disband.png``：两个槽位「未进行招募」、底栏「房间号码」、
   左下「返回」，标题「幻想连战·首战」；关卡选择页帧 ``disband2.png`` 显示
   「第5关协力首领·火精灵兽奥尔塔尼亚」。
2. **共斗房的「挑战」是灰的**（没招募到队友前不可用）。真机帧里「挑战」在 720
   ``box≈[297,906,81,46]``（中心 y≈929），而单人编队页的「挑战」在 ``box≈[297,1069,80,47]``
   （中心 y≈1092）—— 关掉那个灰按钮点什么都不变。
3. 公共打断 ``PubChallenge`` 的判据只是裸 OCR ``^挑战$`` + 盲点，且被注入在每个流程节点的
   **封锁的打断前缀**里（scene.events 的 INTERRUPT_EVENTS，位置由 #18 锁死），排在幻想的
   门控节点**之前** → 它命中共斗房的「挑战」→ 点灰按钮、画面不变 → ``[JumpBack]`` 重扫前缀
   → 再命中 → **死循环**（真机节点序列：``PubChallenge`` 每 ~3s 一次，中间只有 ``OcrTask``）。
   循环发生在**前缀**里，幻想的招募 / 收工节点永远轮不到 → 既推不动、也不收工。

修法
----
* **不再让 PubChallenge 抓共斗房**：``BatchModeRecognition``（种类分派器，每轮都评估，
  是最早的种类信号）按种类 ``override_pipeline`` 把 PubChallenge 收窄到单人编队页底部
  （phantom）／还原全屏 ``^挑战$``（其余种类）。这样共斗房落到 ``SpecialRecruitOpen``
  （招募）/ ``PhantomRecruitStart`` / ``PhantomCoopChallenge`` 上，能招募就推进到开战。
* **开不了战就有界收工**：``PhantomGiveUpRecognition`` 增加「共斗房停留超过 ``coop_room_sec``
  → 收工」并给出明确原因（未招募到队友 / 挑战不可用），绝不空转。

三个守卫（prove-red 在本文件末尾）
----------------------------------
1. ``phantom-coop-room-not-pubchallenge`` —— 收窄后的 PubChallenge 判据**不命中共斗房**
   的挑战、仍命中单人编队页的挑战；收窄/还原两种形态的 expected 都必须等于**真源形状**
   （``scene/challenge.CHALLENGE_CLICK_PATTERNS`` = ``^挑战(→)?$``，兼容真机两种渲染；
   #110 之前这里逐字写死 ``^挑战$``），还原形态还不得带 ROI；共斗房节点在
   PhantomDispatch 里在场。
2. ``phantom-coop-room-loop-repro`` —— 离线复现：旧形态（PubChallenge 全屏）在共斗房上
   ``PubChallenge`` 自锁死循环、招募/挑战节点永不执行；新形态（收窄后）必经
   ``SpecialRecruitOpen`` → ``PhantomRecruitStart`` → ``PhantomCoopChallenge`` 到开战。
3. ``phantom-coop-room-bounded-stop`` —— 房间长时间开不了战 → PhantomGiveUp 命中、原因点名
   共斗房；刚进房间不误收工；``PhantomGiveUp`` 节点声明了 ``coop_room_sec``。

★prove-red★（``python tools\\contract_hooks\\hooks_30.py``）：
  * 把 PubChallenge 倒回全屏 ``^挑战$`` → 守卫 1/2 变红（复现死循环）；
  * 去掉 ``PhantomGiveUp`` 的 ``coop_room_sec`` → 守卫 3 变红（共斗房失去有界出口）。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red / 子进程用 PYTHONPATH 抢先塞坏副本时仍能命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

_PIPELINE_REL = "assets/resource/pipeline"
_PHANTOM = "phantom.json"
_SD = "special_dungeon.json"
_COMMON = "common.json"

# ---------------------------------------------------------------------------
# 真机帧的 720 空间 OCR（内嵌，离线可求值）
# ---------------------------------------------------------------------------
#: 共斗房（未招募）—— 真机帧 disband.ocr.txt：房间号码 / 未进行招募 / 招募 / 挑战 / 返回。
ROOM_ITEMS: list[tuple[str, list[int]]] = [
    ("等级100", [26, 656, 94, 37]),
    ("返回", [30, 1246, 46, 26]),
    ("队长", [31, 410, 35, 20]),
    ("准备中：", [75, 274, 71, 28]),
    ("未进行招募", [307, 286, 104, 28]),
    ("挑战", [297, 906, 81, 46]),          # 共斗房的挑战（灰的、不可用）
    ("招募", [352, 808, 72, 41]),
    ("房间号码", [276, 1184, 94, 28]),
    ("复制", [540, 1230, 48, 31]),
    ("自动续战", [491, 100, 82, 28]),
]
#: 同一房间但已招募到队友（挑战可用）—— 去掉「未进行招募」。
ROOM_RECRUITED_ITEMS: list[tuple[str, list[int]]] = [
    (t, b) for (t, b) in ROOM_ITEMS if t != "未进行招募"
]
#: 「招募方式」弹窗（点「招募」后）：招募方式 / 开始招募。
DIALOG_ITEMS: list[tuple[str, list[int]]] = [
    ("招募方式", [300, 560, 120, 40]),
    ("开始招募", [300, 700, 140, 44]),
    ("取消", [164, 805, 63, 36]),
]
#: 单人编队页 —— 真机帧 720 box [297,1069,80,47]：挑战在底部按钮区。
SOLO_TEAM_ITEMS: list[tuple[str, list[int]]] = [
    ("SET 1", [300, 300, 80, 30]),
    ("挑战", [297, 1069, 80, 47]),          # 单人编队页的挑战（可用）
    ("返回", [30, 1246, 46, 26]),
]
#: 战斗中 HUD：底部条带「时间 HH:MM」+「分数 N」。
BATTLE_ITEMS: list[tuple[str, list[int]]] = [
    ("时间", [600, 1180, 60, 30]),
    ("09:53", [665, 1180, 70, 30]),
    ("分数", [600, 1230, 60, 30]),
    ("000082254", [665, 1230, 130, 30]),
]

#: 真机实测：共斗房挑战 / 单人编队挑战 的 720 框。
ROOM_CHALLENGE_BOX = [297, 906, 81, 46]
SOLO_CHALLENGE_BOX = [297, 1069, 80, 47]
#: #30 收窄后的 PubChallenge ROI（与 phantom.json::PhantomSoloChallenge 同 ROI）。
PHANTOM_ROI = [150, 980, 600, 1180]


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（OCR / And / Or / DirectHit；roi 用 [x,y,w,h]）
# ---------------------------------------------------------------------------
def _ocr_hit(rec: dict, items) -> bool:
    param = rec.get("param") or {}
    pats = param.get("expected") or []
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return True
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        if roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3]:
            return True
    return False


def eval_recognition(rec, items, resolve=None) -> bool:
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        return _ocr_hit(rec, items)
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            hits.append(eval_recognition(leaf_rec, items, resolve))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测


def scene_on_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _pipeline_dir() -> Path:
    return REPO_ROOT / _PIPELINE_REL


def load_files(pipeline_dir=None) -> dict:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(pipeline_dir) if pipeline_dir else _pipeline_dir()
    return drift.load_pipelines(base)


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def _node(name: str, files: dict):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


# ---------------------------------------------------------------------------
# agent 侧接口
# ---------------------------------------------------------------------------
def _pubchallenge_override(kind: str) -> dict:
    scene_on_path()
    import side_impl as si  # noqa: PLC0415

    return si.pubchallenge_override_for(kind)


def _phantom_classify(items):
    scene_on_path()
    import phantom_impl as ph  # noqa: PLC0415

    return ph.classify(items)


def _challenge_click_patterns() -> list[str]:
    """「挑战」按钮点击判据的**真源形状**（#110：``scene/challenge.CHALLENGE_CLICK_PATTERNS``）。

    ★这条断言为什么在 #110 里被改（原来是逐字写死 ``["^挑战$"]``）★
    旧断言把「运行期 override 的判据」钉在一个**已知错误**的形状上：真机帧把底部【挑战】
    读成 ``挑战`` 与 ``挑战→`` 两种（识别调研 ``docs/research/recognition-ocr-vs-template.md``
    §1.2 例 1 / §1.3「两态」：8/17 帧带箭头，两种读法 score 各自稳定 1.000 / 0.962），
    而 ``^挑战$`` **不匹配** ``挑战→`` —— 即旧形状在约一半帧上点不中那颗按钮。
    #109（commit 08024f9）当时正因为这行逐字断言没敢动 ``agent/side_impl`` 的判据；
    #110 把来源改成真源常量：现在断言的是「**必须与真源同形**」，
    既要容忍一个箭头，也**不许**再回退成只认 ``挑战`` 的旧形状。
    """
    scene_on_path()
    from scene.challenge import CHALLENGE_CLICK_PATTERNS  # noqa: PLC0415

    return list(CHALLENGE_CLICK_PATTERNS)


# ---------------------------------------------------------------------------
# 守卫 1：收窄后的 PubChallenge 不抓共斗房
# ---------------------------------------------------------------------------
def _pubchallenge_scope_failures() -> list[str]:
    msgs: list[str] = []
    phantom_ov = _pubchallenge_override("phantom")
    other_ov = _pubchallenge_override("special")
    want = _challenge_click_patterns()

    pnode = (phantom_ov or {}).get("PubChallenge") or {}
    prec = (pnode.get("recognition") or {})
    pparam = prec.get("param") or {}
    if prec.get("type") != "OCR":
        msgs.append("PubChallenge 收窄：phantom 形态不是 OCR")
    if pparam.get("expected") != want:
        msgs.append(
            f"PubChallenge 收窄：phantom 形态 expected 应为 {want!r}（真源 scene/challenge.py，"
            f"兼容 `挑战` / `挑战→` 两种渲染），实际 {pparam.get('expected')!r}"
        )
    if list(pparam.get("roi") or []) != PHANTOM_ROI:
        msgs.append(f"PubChallenge 收窄：phantom 形态 ROI 应为 {PHANTOM_ROI}，实际 {pparam.get('roi')!r}")

    # 收窄后的判据：不命中共斗房挑战、仍命中单人编队挑战（用真机框求值）。
    if _ocr_hit(prec, ROOM_ITEMS):
        msgs.append("PubChallenge 收窄后仍命中共斗房的『挑战』（灰按钮 -> 死循环未修）")
    if not _ocr_hit(prec, SOLO_TEAM_ITEMS):
        msgs.append("PubChallenge 收窄后不认单人编队页的『挑战』（会把单人流程也打坏）")

    onode = (other_ov or {}).get("PubChallenge") or {}
    orec = onode.get("recognition") or {}
    oparam = orec.get("param") or {}
    if oparam.get("roi") is not None:
        msgs.append(f"PubChallenge 还原：非 phantom 形态不该带 ROI，实际 {oparam.get('roi')!r}")
    if oparam.get("expected") != want:
        msgs.append(
            f"PubChallenge 还原：非 phantom 形态 expected 应为 {want!r}（真源 scene/challenge.py，"
            f"兼容 `挑战` / `挑战→` 两种渲染），实际 {oparam.get('expected')!r}"
        )
    if not _ocr_hit(orec, ROOM_ITEMS):
        msgs.append("PubChallenge 还原形态竟不认共斗房的『挑战』（prove-red 前提不成立）")

    # 共斗房节点必须在 PhantomDispatch 链上（否则收窄后也无人接管）。
    files = load_files()
    disp = _node("PhantomDispatch", files) or {}
    nxt = list(disp.get("next") or [])
    for name in ("PhantomCoopRecruit", "PhantomRecruitStart", "PhantomCoopChallenge"):
        if name not in nxt:
            msgs.append(f"共斗房节点 {name} 不在 PhantomDispatch.next 里（无人接管房间）")

    # 通用「招募」打断 SpecialRecruitOpen 必须是 max_hit:1 —— 它只负责【打开一次】招募方式页，
    # 之后交给门控节点；若改成无限命中，共斗房里灰掉的「招募」会让它自锁（换了一条死循环）。
    sro = _node("SpecialRecruitOpen", files) or {}
    if int(sro.get("max_hit", 0) or 0) != 1:
        msgs.append(
            f"SpecialRecruitOpen.max_hit 应为 1（打开一次招募方式页即止），实际 {sro.get('max_hit')!r}"
        )
    return msgs


def probe_coop_room_not_pubchallenge() -> bool:
    return _pubchallenge_scope_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：离线复现共斗房死循环（旧形态）/ 收窄后可开战（新形态）
#
# 语义（与真机一致）：一个父节点的 next 按序识别，取第一个命中的执行；
#   [JumpBack] 打断命中后跳回父节点、**从候选表顶部重扫**（这正是死循环的机制：
#   命中的节点不改变画面 -> 下一轮又命中它）；普通引用执行后进入它自己的 next。
# 循环 = 同一段候选反复命中到步数上限仍无进展。
# ---------------------------------------------------------------------------
def _custom(node) -> str | None:
    rec = (node or {}).get("recognition") or {}
    return (rec.get("param") or {}).get("custom_recognition")


def _custom_param(node) -> dict:
    rec = (node or {}).get("recognition") or {}
    return (rec.get("param") or {}).get("custom_recognition_param") or {}


class _Screen:
    """共斗房序列的可观测状态：room（未招募）/ dialog（招募方式）/ room_recruited / battle。"""

    def __init__(self, state: str = "room", solvable: bool = True):
        self.state = state
        self.solvable = solvable

    @property
    def items(self):
        return {
            "room": ROOM_ITEMS,
            "dialog": DIALOG_ITEMS,
            "room_recruited": ROOM_RECRUITED_ITEMS,
            "battle": BATTLE_ITEMS,
        }[self.state]

    @property
    def phantom_state(self) -> str:
        return _phantom_classify(self.items)[0]

    @property
    def recruited(self) -> bool:
        return self.state in ("room_recruited", "battle")


def _hit(name: str, screen: _Screen, files: dict, resolve, pubchallenge_roi) -> bool:
    node = _node(name, files)
    if node is None:
        return False
    c = _custom(node)
    if c == "batch_mode":
        return (_custom_param(node).get("kind") or "farm") == "phantom"
    if c == "phantom_state":
        cp = _custom_param(node)
        want = (cp.get("state") or "").strip()
        st = screen.phantom_state
        if want and st != want:
            return False
        if want == "phantom_coop_room" and cp.get("need_recruit") and screen.recruited:
            return False
        return True
    if c == "phantom_done":
        return screen.phantom_state == "phantom_main"
    if c == "phantom_giveup":
        return False  # 共斗房出口由守卫 3 直接驱真实识别器验证，此处不模拟
    if name == "PubChallenge" and pubchallenge_roi is not None:
        return _ocr_hit(
            {"type": "OCR", "param": {"expected": ["^挑战$"], "roi": list(pubchallenge_roi)}},
            screen.items,
        )
    return eval_recognition(resolve(name), screen.items, resolve)


def _apply(name: str, screen: _Screen) -> None:
    if name in ("SpecialRecruitOpen", "PhantomCoopRecruit"):
        screen.state = "dialog"
    elif name == "PhantomRecruitStart":
        screen.state = "room_recruited"
    elif name == "PhantomCoopChallenge":
        # 共斗房的挑战：招募到队友（可用）才开战；否则灰按钮点了不推进。
        if screen.state == "room_recruited" and screen.solvable:
            screen.state = "battle"
    elif name == "PhantomBattleWait":
        screen.state = "battle"


def simulate_room(pubchallenge_roi=None, *, solvable: bool = True, max_steps: int = 80):
    """从 SpecialEntry 出发走共斗房；返回 (命中序列, 终态, 是否死循环)。

    遵守 MAA 的 ``max_hit``：命中数用尽的候选被跳过（例如 ``SpecialRecruitOpen`` 实测
    ``max_hit: 1`` —— 通用「招募」打断只打开一次招募方式页，之后交给门控节点）。
    """
    files = load_files()
    resolve = _resolver(files)
    screen = _Screen("room", solvable=solvable)
    seq: list[str] = []
    counters: dict[str, int] = {}
    parent = "SpecialEntry"

    def can_hit(name: str) -> bool:
        mh = (_node(name, files) or {}).get("max_hit")
        if mh is None:
            return True
        return counters.get(name, 0) < int(mh)

    for _ in range(max_steps):
        refs = list((_node(parent, files) or {}).get("next") or [])
        hit = None
        for ref in refs:
            jb = isinstance(ref, str) and ref.startswith("[JumpBack]")
            name = ref[len("[JumpBack]"):] if jb else ref
            if not can_hit(name):
                continue
            if _hit(name, screen, files, resolve, pubchallenge_roi):
                hit = (name, jb)
                break
        if hit is None:
            return seq, screen.state, False
        name, jb = hit
        seq.append(name)
        counters[name] = counters.get(name, 0) + 1
        _apply(name, screen)
        if screen.state == "battle":
            return seq, screen.state, False
        parent = parent if jb else name
    return seq, screen.state, True


def _loop_repro_failures() -> list[str]:
    msgs: list[str] = []
    # 旧形态（PubChallenge 全屏 ^挑战$）：PubChallenge 自锁死循环，招募/挑战节点永不执行。
    old_seq, old_state, old_loop = simulate_room(None)
    if not old_loop:
        msgs.append(f"旧形态未复现死循环（{old_seq[:6]} -> {old_state}）")
    if "PubChallenge" not in old_seq[:3]:
        msgs.append(f"旧形态死循环不是 PubChallenge 自锁（{old_seq[:6]}）")
    if any(n in old_seq for n in ("SpecialRecruitOpen", "PhantomCoopChallenge", "PhantomRecruitStart")):
        msgs.append(f"旧形态竟执行了招募/挑战节点（prove-red 前提不成立）：{old_seq[:8]}")

    # 新形态（收窄后）：经历招募 -> 开始招募 -> 挑战 -> 开战。
    new_seq, new_state, new_loop = simulate_room(PHANTOM_ROI)
    if new_loop or new_state != "battle":
        msgs.append(f"收窄后仍未开战（{new_seq[:8]} -> {new_state}, loop={new_loop}）")
    if "PhantomCoopChallenge" not in new_seq:
        msgs.append(f"收窄后没有走到 PhantomCoopChallenge：{new_seq[:8]}")
    if not any(n in new_seq for n in ("SpecialRecruitOpen", "PhantomCoopRecruit")):
        msgs.append(f"收窄后没有走到招募节点：{new_seq[:8]}")
    return msgs


def probe_coop_room_loop_repro() -> bool:
    return _loop_repro_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：共斗房长时间开不了战 -> 有界收工（原因点名共斗房）+ 刚进房不误收工
# ---------------------------------------------------------------------------
class _TaskDetail:
    def __init__(self, task_id):
        self.task_id = task_id


class _Argv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = _TaskDetail(task_id)
        self.custom_recognition_param = json.dumps(param)


def _coop_giveup_hit(age_sec: float, coop_room_sec: float | None = None):
    """驱动真实的 PhantomGiveUpRecognition 跑一帧共斗房，返回 (是否命中, reason)。"""
    scene_on_path()
    import phantom_impl as ph  # noqa: PLC0415

    real_ocr = ph._ocr
    try:
        ph._ocr = lambda context, image, entry="OcrTask": list(ROOM_ITEMS)
        tid = 424242
        with ph._LOCK:
            # 让 _sync_task 视作「同一任务」，避免复位计时。
            ph._SESSION["task_id"] = tid
            ph._SESSION["start_ts"] = time.monotonic()
            ph._SESSION["last_progress_ts"] = time.monotonic()
            ph._SESSION["coop_room_first_ts"] = time.monotonic() - float(age_sec)
            ph._SESSION["last_state"] = None
            ph._SESSION["last_observe_ts"] = 0.0
            # 归零无关计数，保证本守卫只看「共斗房停留」这条规则（确定性）。
            ph._SESSION["unknown_count"] = 0
            ph._SESSION["total_marks"] = 0
            ph._SESSION["max_done"] = 0
            ph._SESSION["completed_sets"] = 0
        param = {"ocr_entry": "OcrTask"}
        if coop_room_sec is not None:
            param["coop_room_sec"] = coop_room_sec
        res = ph.PhantomGiveUpRecognition().analyze(None, _Argv(tid, param))
        detail = res.detail or {}
        return (res.box == [0, 0, 0, 0]), str(detail.get("reason") or "")
    finally:
        ph._ocr = real_ocr


def _pipeline_bound_failures(root: Path | None = None) -> list[str]:
    """PhantomGiveUp 节点必须声明正的 coop_room_sec（有界出口的接线）。"""
    if root is None:
        files = load_files()
        node = _node("PhantomGiveUp", files) or {}
    else:
        files = load_files(Path(root) / _PIPELINE_REL)
        node = _node("PhantomGiveUp", files) or {}
    cn = _custom(node)
    cp = _custom_param(node)
    msgs: list[str] = []
    if cn != "phantom_giveup":
        msgs.append(f"PhantomGiveUp 的 custom_recognition 应为 phantom_giveup，实际 {cn!r}")
        return msgs
    try:
        sec = float(cp.get("coop_room_sec"))
    except (TypeError, ValueError):
        msgs.append(f"PhantomGiveUp 未声明 coop_room_sec（共斗房没有有界出口）：{cp.get('coop_room_sec')!r}")
        return msgs
    if sec <= 0:
        msgs.append(f"PhantomGiveUp 的 coop_room_sec 应为正数，实际 {sec}")
    return msgs


def _bounded_stop_failures() -> list[str]:
    msgs = _pipeline_bound_failures()
    hit_long, reason_long = _coop_giveup_hit(age_sec=300.0, coop_room_sec=120.0)
    if not hit_long:
        msgs.append("共斗房停留 300s（>120s）未命中收工（房间长时间开不了战却不收工 = 空转）")
    if "共斗房" not in reason_long:
        msgs.append(f"收工原因未点名共斗房：{reason_long!r}")
    hit_fresh, reason_fresh = _coop_giveup_hit(age_sec=1.0, coop_room_sec=120.0)
    if hit_fresh:
        msgs.append(f"刚进共斗房就误收工：{reason_fresh!r}")
    return msgs


def probe_coop_room_bounded_stop() -> bool:
    return _bounded_stop_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_30.py`）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook30_"))
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
    print("hooks_30 prove-red：两处破坏，要求守卫各自变红")
    green = (
        probe_coop_room_not_pubchallenge() is True
        and probe_coop_room_loop_repro() is True
        and probe_coop_room_bounded_stop() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：收窄 PubChallenge + 可开战 + 有界收工（绿）")
    if not green:
        return False

    # (a) 把 PubChallenge 倒回全屏 ^挑战$ -> 守卫 1/2 变红（复现死循环）。
    old_seq, old_state, old_loop = simulate_room(None)
    red_a_loop = old_loop and "PubChallenge" in old_seq[:3]
    # 直接用「全屏」判据求值：命中共斗房（守卫 1 的反例）
    red_a_scope = _ocr_hit(
        {"type": "OCR", "param": {"expected": ["^挑战$"]}}, ROOM_ITEMS
    )
    red_a = red_a_loop and red_a_scope
    print(f"  [{'PASS' if red_a else 'FAIL'}] PubChallenge 倒回全屏 -> "
          f"{'红（共斗房 PubChallenge 自锁死循环）' if red_a else '仍绿'}  seq={old_seq[:4]} loop={old_loop}")

    # (b) 去掉 PhantomGiveUp 的 coop_room_sec -> 守卫 3 变红（共斗房失去有界出口）。
    root = _temp_assets()
    try:
        _sub(
            root / _PIPELINE_REL / _PHANTOM,
            '                    "coop_room_sec": 120,\n',
            "",
        )
        msgs = _pipeline_bound_failures(root)
        red_b = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_b else 'FAIL'}] 去掉 phantom.json 的 coop_room_sec -> "
              f"{'红' if red_b else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "phantom-coop-room-not-pubchallenge",
        "#30",
        "收窄后的 PubChallenge 不抓幻想共斗房（灰挑战）、仍认单人编队页的挑战；"
        "共斗房节点在 PhantomDispatch 链上（真机帧正反例）",
        probe_coop_room_not_pubchallenge,
    ),
    (
        "phantom-coop-room-loop-repro",
        "#30",
        "离线复现：旧形态 PubChallenge 在共斗房自锁死循环；收窄后必经招募→开始招募→挑战开战",
        probe_coop_room_loop_repro,
    ),
    (
        "phantom-coop-room-bounded-stop",
        "#30",
        "共斗房长时间开不了战 → PhantomGiveUp 有界收工并点名共斗房；刚进房不误收工",
        probe_coop_room_bounded_stop,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
