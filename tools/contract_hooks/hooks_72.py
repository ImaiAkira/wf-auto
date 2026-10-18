# -*- coding: utf-8 -*-
"""#72：五重决战 GAMEOVER → 点【续关】（不是【放弃】）；续关次数由 user 指定、用尽即带原因收工。

规格 ``docs/spec/wuchong-spec.md`` B3 / B6 / D3 / D6。

seam
----
* ``scene/wuchong.py``：续关短语 / 节点名 / ROI / 账本前缀 / 上限字段 / ``continue_refs()``
  （唯一真源；``FLOW_EXCEPTIONS`` 已用它替换 #38 的「放弃」引用）；
* ``assets/resource/pipeline/common.json``：``PubGameOverContinueBtn`` / ``PubGameOverContinue``
  （公共节点：``And(横幅,「是否续关?」,【续关】) box_index=2`` → ``Click target:true``，
  点**续关按钮识别框中心**；叶子型 ``next=[]``）；
* ``assets/resource/pipeline/wuchong.json``：``WuchongContinueGuard``（``StopTask`` 上限闸，
  排在 ``[JumpBack]PubGameOverContinue`` 之前）+ 每个流程节点的 ``next`` 注入续关链；
* ``agent/wuchong_impl.py``：``WuchongContinueGuardRecognition`` + 续关账本 ``wuchong/continue/{n}``
  + ``is_gameover_page``；
* ``assets/interface.json``：选项「五重续关几次」（input，字段 ``次数``）整体替换
  ``WuchongContinueGuard.recognition``。

★关键事实★
----------
* GAMEOVER 页底部**仍画战斗 HUD**（时间/分数），五重 ``classify`` 本就判 ``wuchong_battle``
  —— **不改 classify**；续关由挂在每个流程节点的异常前缀里的识别节点处理。
* 真机 720：``GAMEOVER`` [65,463,589,73] /「是否续关?」[300,820,130,33] /
  【放弃】[180,1043,66,39]（中心 (213,1062)）/【续关】[473,1043,65,36]（中心 (506,1061)）/
  ``使用星导石×50`` [275,864,171,23]。
* ★此屏 ``使用星导石×50`` 是【续关费】，与体力不足恢复**不是同一屏**★（D6）：两屏的真实分界是
  体力恢复 ``And`` 的【弹窗正文】叶（「请选择要使用的道具 / 体力不足」）—— GAMEOVER 屏缺它，
  故第一步必然 miss。★注意（#74，真机A/2026-10-16）★：体力弹窗星导石行 ROI 已从旧值
  y 900-980 放宽到 y 840-1000，与 GAMEOVER 屏星导石（y≈864-887）在 y 上**已交叠**，故 ROI
  **不再**单独分离两屏；承重的是正文叶（「本屏星导石在 y≈875 在 ROI 之上」的说法随标定作废）。

守卫（本文件；prove-red 见文末）
------------------------------
1. ``gameover-continue-nodes-declared`` —— 两个公共节点在场、判据与 ``scene.wuchong`` 一致、
   ``And + box_index=2`` → ``Click target:true``（点识别框中心、零死偏移）、叶子型、引用叶在场。
2. ``gameover-continue-frame`` —— **真机帧回放**（内嵌 #38 帧逐条 OCR）：GAMEOVER 帧命中且
   点【续关】框中心 (506,1061)；确认框 / 编队页 / 体力弹窗 / 「只有横幅」/「只有询问」都不命中。
3. ``gameover-not-stamina-and-vice-versa`` —— 续关费与体力恢复**互不误命中**：GAMEOVER 帧上
   体力两节点都 miss；体力弹窗帧上续关节点 miss；并断言 GAMEOVER 帧缺体力弹窗**正文叶**
   （#74 后 ROI 不再单独分离两屏，承重的是正文叶「请选择要使用的道具 / 体力不足」）。
4. ``wuchong-continues-on-gameover`` —— (a) ``continue_refs()`` 顺序 + 都在 ``FLOW_EXCEPTIONS``
   且 guard 在前；(b) 流程链与 ``step_next``/``hub_next`` 同步、且**没有任何五重流程边/异常前缀**
   含「放弃」；(c) ``WuchongContinueGuard`` 是 ``StopTask`` 出口；(d) 全 pipeline 无固定续关坐标；
   (e) ``SpecialEntry.next`` 仍引用 #38 的四个 ``PubGameOver*`` 节点（批量仍放弃续关）。
5. ``wuchong-continue-count-configurable`` —— 驱动**真实** ``WuchongContinueGuardRecognition``：
   ``target=2`` 第 1/2 个 episode miss、第 3 个 hit 且原因点名 2（★cap 优先于卡住★）；``target=0``
   永不由此停；``target=1`` 第 1 个 miss、第 2 个 hit；每 episode 恰记一次（连帧只算一次）；
   ★有界卡住等待★同一屏超 ``CONTINUE_STUCK_SEC`` 带原因收工；账本 ``wuchong/continue/1..``；
   非 GAMEOVER 帧 miss 且不计。★计数口径★：按**进入 GAMEOVER 屏的次数**结算（运维原话「按进去的
   次数结算」），计数发生在 episode 进入时、点击之前 → 只会保守（绝不漏计）。
6. ``wuchong-continue-option-wired`` —— 任务挂载该选项、``type=input``、override 落到
   ``WuchongContinueGuard.target_continues``；既有「五重打几次」仍写 ``WuchongGiveUp``（两写者共存）。
6b. ``wuchong-continue-phrases-single-source`` —— GAMEOVER 短语唯一真源：``scene.wuchong`` 的
   ``CONTINUE_TITLE_TEXT``/``CONTINUE_PROMPT_TEXT`` == ``side_impl.GAMEOVER_TITLE/GAMEOVER_PROMPT``，
   且 ``common.json`` 横幅/询问叶包含它们（闭合 scene ↔ side_impl ↔ common 三角）。
7. ``wuchong-continue-declared`` —— 承重短语零丢失（special_dungeon.json 五条各 ≥1）+ ``drift`` 空。

★诚实边界★：真机 leg（制造一次战斗失败、验证真的点了【续关】并继续）**未在本机运行**
（无设备）—— 本文件只做离线断言（判据 / 接线 / 计数 / 上限 / 卡住上界 / 互不误命中 / 真机帧回放）。

★prove-red★（``python tools\\contract_hooks\\hooks_72.py``）七处破坏，要求守卫各自变红：
    * 从五重数据/流水线摘掉 ``[JumpBack]PubGameOverContinue`` -> 守卫 4 红；
    * 把续关节点指向固定坐标 ``[506,1061]`` -> 守卫 1（及 4d）红；
    * 把 guard 的动作从 ``StopTask`` 改成 ``Click`` -> 守卫 4c 红；
    * 放宽上限语义（收工 -> 放行，等价 ``n>=target+99``）-> 守卫 5 红；
    * 拆掉有界卡住等待（``CONTINUE_STUCK_SEC = inf``）-> 守卫 5 红；
    * 从 interface.json 去掉选项的 ``target_continues`` 字段 -> 守卫 6 红；
    * 让 scene.wuchong 的 GAMEOVER 短语与 side_impl 分叉 -> 守卫 6b 红。
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = Path(__file__).resolve().parent
AGENT_DIR = REPO_ROOT / "agent"

# ★只 append 到 sys.path 末尾★：prove-red 用 PYTHONPATH 抢先塞坏副本时副本仍优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

# 真机帧数据取**单一真源**（不复制）：#38 的 GAMEOVER / 确认框帧；#68 的体力弹窗 / 编队页帧。
from contract_hooks import hooks_38, hooks_stamina  # noqa: E402

#: 真机 GAMEOVER 续关页帧（#38 单源）。
GAMEOVER_ITEMS = hooks_38.GAMEOVER_PAGE_ITEMS
#: 真机「放弃」确认框帧（#38 单源）——续关节点**不得**命中它。
CONFIRM_ITEMS = hooks_38.CONFIRM_ITEMS
#: 真机「回复体力」弹窗帧（#68 单源）——续关节点**不得**命中它。
POPUP_FRAME = hooks_stamina.POPUP_FRAME
#: 真机编队页帧（#68 单源）——续关节点**不得**命中它。
TEAM_FRAME = hooks_stamina.TEAM_FRAME

#: 复用 #38 的公共叶子名（不复制短语）。
_TITLE_NODE = "PubGameOverTitle"
_PROMPT_NODE = "PubGameOverPrompt"
#: 期望点击点（720，＝【续关】按钮 [473,1043,65,36] 的识别框中心，= #38 的 CONTINUE_BUTTON）。
EXPECTED_CONTINUE_BOX = [473, 1043, 65, 36]
EXPECTED_CONTINUE_CENTER = (506, 1061)
#: #38 的四个「放弃」公共节点（special_dungeon 批量链仍引用；此处断言未被本票动到）。
_GAMEOVER_DECLINE_NODES = (
    "PubGameOverGiveUp",
    "PubGameOverGiveUpFallback",
    "PubGameOverConfirm",
    "PubGameOverConfirmFallback",
)
#: 五重链**禁止**出现的「放弃」节点片段（本票后不再引用）。
_BANNED_FRAGMENTS = ("PubGameOverGiveUp", "PubGameOverConfirm")
#: 禁止的固定续关坐标（应当点识别框中心，绝不点死坐标）。
FIXED_CONTINUE_COORD = (506, 1061)
#: 保读率阈值：与 hooks_stamina 同模型（走它自己的 and_eval，这里只做框/中心对账）。
VISIBLE_MIN = hooks_stamina.VISIBLE_MIN


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _wuchong():
    from scene import wuchong as W  # noqa: PLC0415

    return W


def _load_common(root: Path | None = None) -> dict:
    return hooks_stamina.load_common(root)


def _load_chain(file: str, root: Path | None = None) -> dict:
    return hooks_stamina.load_chain(file, root)


def _load_pipelines(root: Path | None = None) -> dict:
    from scene import drift  # noqa: PLC0415

    base = (Path(root) if root is not None else REPO_ROOT) / "assets" / "resource" / "pipeline"
    return drift.load_pipelines(base)


def _box_center(box) -> tuple[int, int]:
    """识别框中心（四舍五入；【续关】[473,1043,65,36] -> (506,1061)）。"""
    x, y, w, h = box
    return (round(x + w / 2.0), round(y + h / 2.0))


def _target_of(node) -> object:
    return (((node or {}).get("action") or {}).get("param") or {}).get("target")


# ---------------------------------------------------------------------------
# 守卫 1：数据声明（判据与配置一致 + 读后动零偏移 + 叶子型 + 引用叶在场）
# ---------------------------------------------------------------------------
def node_failures(common: dict | None = None) -> list[str]:
    W = _wuchong()
    common = _load_common() if common is None else common
    msgs: list[str] = []

    btn = common.get(W.CONTINUE_BTN_NODE)
    if not isinstance(btn, dict):
        msgs.append(f"common.json 缺公共叶子 {W.CONTINUE_BTN_NODE}（续关按钮未被声明）")
    else:
        rec = btn.get("recognition") or {}
        param = rec.get("param") or {}
        if rec.get("type") != "OCR":
            msgs.append(f"{W.CONTINUE_BTN_NODE} 应为 OCR（续关按钮叶），实际 {rec.get('type')!r}")
        if list(param.get("expected") or []) != [W.CONTINUE_BTN_TEXT]:
            msgs.append(
                f"{W.CONTINUE_BTN_NODE}.expected={param.get('expected')!r} 应为 "
                f"[{W.CONTINUE_BTN_TEXT!r}]"
            )
        if list(param.get("roi") or []) != list(W.CONTINUE_BTN_ROI):
            msgs.append(
                f"{W.CONTINUE_BTN_NODE}.roi={param.get('roi')!r} != scene.wuchong.CONTINUE_BTN_ROI "
                f"{list(W.CONTINUE_BTN_ROI)!r}（配置/产物不同步；ROI 避开左侧【放弃】）"
            )

    node = common.get(W.CONTINUE_NODE)
    if not isinstance(node, dict):
        msgs.append(f"common.json 缺动作节点 {W.CONTINUE_NODE}（续关点击未被声明）")
    else:
        rec = node.get("recognition") or {}
        param = rec.get("param") or {}
        if rec.get("type") != "And":
            msgs.append(f"{W.CONTINUE_NODE} 识别应为 And（横幅 ∧ 询问 ∧ 续关按钮），实际 {rec.get('type')!r}")
        want_leaves = [_TITLE_NODE, _PROMPT_NODE, W.CONTINUE_BTN_NODE]
        if list(param.get("all_of") or []) != want_leaves:
            msgs.append(f"{W.CONTINUE_NODE}.all_of 应为 {want_leaves!r}，实际 {param.get('all_of')!r}")
        if int(param.get("box_index", 0)) != 2:
            msgs.append(
                f"{W.CONTINUE_NODE}.box_index 应为 2（输出【续关】框），实际 {param.get('box_index')!r}"
                " —— 否则会点到横幅/询问框而不是续关按钮"
            )
        act = node.get("action") or {}
        ap = act.get("param") or {}
        if act.get("type") != "Click" or ap.get("target") is not True:
            msgs.append(
                f"{W.CONTINUE_NODE} 动作应为 Click target:true（点识别框中心、零死偏移），实际 "
                f"{act.get('type')!r}/{ap.get('target')!r}"
            )
        if isinstance(ap.get("target_offset"), (list, tuple)) and any(
            float(v or 0) != 0.0 for v in ap["target_offset"]
        ):
            msgs.append(f"{W.CONTINUE_NODE} 用了死偏移 target_offset={ap.get('target_offset')!r}")
        if node.get("next") != []:
            msgs.append(f"{W.CONTINUE_NODE}.next 应为 []（叶子型），实际 {node.get('next')!r}")

    # 引用的叶子必须在场（复用既有 PubGameOverTitle / PubGameOverPrompt）。
    for leaf in (_TITLE_NODE, _PROMPT_NODE):
        if not isinstance(common.get(leaf), dict):
            msgs.append(f"{W.CONTINUE_NODE} 引用的叶子 {leaf!r} 不在 common.json（悬空引用）")
    return msgs


def probe_gameover_continue_nodes_declared() -> bool:
    return node_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：真机帧回放（内嵌 #38 帧逐条 OCR）
# ---------------------------------------------------------------------------
def frame_failures(common: dict | None = None) -> list[str]:
    W = _wuchong()
    common = _load_common() if common is None else common
    msgs: list[str] = []

    hit, box, _boxes = hooks_stamina.and_eval(common, W.CONTINUE_NODE, GAMEOVER_ITEMS)
    if not hit or box is None:
        msgs.append("真机 GAMEOVER 帧（GAMEOVER + 是否续关? + 续关）未命中续关节点（点不到续关）")
    else:
        if list(box) != EXPECTED_CONTINUE_BOX:
            msgs.append(f"GAMEOVER 帧输出框应为【续关】{EXPECTED_CONTINUE_BOX}，实际 {list(box)}")
        if _box_center(box) != EXPECTED_CONTINUE_CENTER:
            msgs.append(
                f"GAMEOVER 帧点到 {_box_center(box)}，应为【续关】框中心 {EXPECTED_CONTINUE_CENTER}"
                f"（box={list(box)}）"
            )

    # 反例（与门 / ROI 承重）：这些都必须【不命中】。
    negatives = [
        ("放弃确认框", W.CONTINUE_NODE, CONFIRM_ITEMS),
        ("编队页", W.CONTINUE_NODE, TEAM_FRAME),
        ("体力弹窗", W.CONTINUE_NODE, POPUP_FRAME),
        ("只有横幅没有询问", W.CONTINUE_NODE, [("GAMEOVER", [65, 463, 589, 73])]),
        ("只有询问没有横幅", W.CONTINUE_NODE, [("是否续关?", [300, 820, 130, 33])]),
        (
            "横幅+询问但没有续关按钮",
            W.CONTINUE_NODE,
            [("GAMEOVER", [65, 463, 589, 73]), ("是否续关?", [300, 820, 130, 33])],
        ),
    ]
    for label, node, items in negatives:
        h, _b, _bs = hooks_stamina.and_eval(common, node, items)
        if h:
            msgs.append(f"{label} 误命中 {node} —— 与门 / ROI 过宽（应只认完整 GAMEOVER 续关页）")
    return msgs


def probe_gameover_continue_frame() -> bool:
    return frame_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：续关费 vs 体力恢复 —— 互不误命中（D6）
# ---------------------------------------------------------------------------
def stamina_cross_failures(common: dict | None = None) -> list[str]:
    W = _wuchong()
    from scene import stamina as S  # noqa: PLC0415

    common = _load_common() if common is None else common
    msgs: list[str] = []

    # GAMEOVER 帧上：体力两步节点都【不得】命中（本屏的「使用星导石×50」是续关费，不是恢复弹窗）。
    for node in (S.NODE_USE_STONE, S.NODE_CONFIRM_OK):
        h, _b, _bs = hooks_stamina.and_eval(common, node, GAMEOVER_ITEMS)
        if h:
            msgs.append(
                f"GAMEOVER 帧误命中体力恢复节点 {node} —— 续关费与恢复体力两屏交叉匹配（D6）"
            )

    # 体力弹窗帧上：续关节点【不得】命中。
    h, _b, _bs = hooks_stamina.and_eval(common, W.CONTINUE_NODE, POPUP_FRAME)
    if h:
        msgs.append(f"体力弹窗帧误命中 {W.CONTINUE_NODE} —— 两屏交叉匹配（D6）")

    # ★承重证据（D6，2026-10-16 真机A 重标后更新）★：两屏的真实分界是 AND 的【弹窗正文】叶，
    # 不是 ROI。星导石行 ROI 放宽到 y 840-1000 后，已与 GAMEOVER 屏「使用星导石×50」
    # （y≈864-887）在 y 上交叠 —— 承重的是正文（请选择要使用的道具 / 体力不足）：GAMEOVER 屏缺它，
    # 故第一步必然 miss。这里直接钉住「正文叶在 GAMEOVER 帧上 miss」（上面已断言第一步整节点 miss）。
    body = hooks_stamina._ocr_first(GAMEOVER_ITEMS, common.get(S.NODE_INSUFFICIENT) or {})
    if body is not None:
        msgs.append(
            "GAMEOVER 帧竟命中体力弹窗正文叶（请选择要使用的道具 / 体力不足）—— "
            "与门不再分离两屏（D6 的承重前提被破坏）"
        )
    return msgs


def probe_gameover_not_stamina() -> bool:
    return stamina_cross_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3b：GAMEOVER 短语唯一真源（闭合 scene ↔ side_impl ↔ common.json 三角）
#
# ``scene.wuchong.CONTINUE_TITLE_TEXT`` / ``CONTINUE_PROMPT_TEXT`` 是**本场景声明的意图**
# （配置权威的一部分，故**不删**这两个字面量）；其**规范真源**是 ``agent/side_impl``
# 的 ``GAMEOVER_TITLE`` / ``GAMEOVER_PROMPT``（#38 已把它与 ``common.json`` 对账）。
# 此前没有任何东西钉住 scene ↔ side_impl —— 将来改一处会**静默分叉**。本守卫闭合这个三角：
# scene.wuchong 的短语必须与 side_impl 一致，且 ``common.json`` 的横幅/询问叶确实包含它们。
# ---------------------------------------------------------------------------
def phrases_single_source_failures(common: dict | None = None) -> list[str]:
    import side_impl  # noqa: PLC0415

    W = _wuchong()
    common = _load_common() if common is None else common
    msgs: list[str] = []

    if W.CONTINUE_TITLE_TEXT != side_impl.GAMEOVER_TITLE:
        msgs.append(
            f"scene.wuchong.CONTINUE_TITLE_TEXT={W.CONTINUE_TITLE_TEXT!r} != "
            f"side_impl.GAMEOVER_TITLE={side_impl.GAMEOVER_TITLE!r}（GAMEOVER 短语真源分叉）"
        )
    if W.CONTINUE_PROMPT_TEXT != side_impl.GAMEOVER_PROMPT:
        msgs.append(
            f"scene.wuchong.CONTINUE_PROMPT_TEXT={W.CONTINUE_PROMPT_TEXT!r} != "
            f"side_impl.GAMEOVER_PROMPT={side_impl.GAMEOVER_PROMPT!r}（续关询问短语真源分叉）"
        )

    title_pats = ((common.get(_TITLE_NODE) or {}).get("recognition") or {}).get("param") or {}
    prompt_pats = ((common.get(_PROMPT_NODE) or {}).get("recognition") or {}).get("param") or {}
    title_exp = list(title_pats.get("expected") or [])
    prompt_exp = list(prompt_pats.get("expected") or [])
    if not any(W.CONTINUE_TITLE_TEXT == p or W.CONTINUE_TITLE_TEXT in p for p in title_exp):
        msgs.append(f"{_TITLE_NODE}.expected={title_exp!r} 未包含续关横幅 {W.CONTINUE_TITLE_TEXT!r}")
    if not any(W.CONTINUE_PROMPT_TEXT == p or W.CONTINUE_PROMPT_TEXT in p for p in prompt_exp):
        msgs.append(f"{_PROMPT_NODE}.expected={prompt_exp!r} 未包含续关询问 {W.CONTINUE_PROMPT_TEXT!r}")
    return msgs


def probe_wuchong_continue_phrases_single_source() -> bool:
    return phrases_single_source_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：五重在 GAMEOVER 屏点续关（数据/流水线同步 + 不再点放弃 + 无固定坐标）
# ---------------------------------------------------------------------------
def chain_failures(files: dict | None = None) -> list[str]:
    W = _wuchong()
    files = _load_pipelines() if files is None else files
    wz = files.get("wuchong.json") or {}
    common = files.get("common.json") or {}
    sd = files.get("special_dungeon.json") or {}
    msgs: list[str] = []

    # (a) 数据层：continue_refs() 顺序 + 都在 FLOW_EXCEPTIONS，且 guard 严格在前。
    want_refs = (W.CONTINUE_GUARD_NODE, f"[JumpBack]{W.CONTINUE_NODE}")
    refs = tuple(W.continue_refs())
    if refs != want_refs:
        msgs.append(f"scene.wuchong.continue_refs()={refs!r} 应为 {want_refs!r}")
    for r in refs:
        if r not in W.FLOW_EXCEPTIONS:
            msgs.append(f"scene.wuchong.FLOW_EXCEPTIONS 缺续关引用 {r!r}")
    if W.CONTINUE_GUARD_NODE in W.FLOW_EXCEPTIONS and refs[1] in W.FLOW_EXCEPTIONS:
        if W.FLOW_EXCEPTIONS.index(W.CONTINUE_GUARD_NODE) >= W.FLOW_EXCEPTIONS.index(refs[1]):
            msgs.append("FLOW_EXCEPTIONS 里 guard 未排在 [JumpBack]PubGameOverContinue 之前（上限闸失效）")

    # (b) 流水线按数据落地：枢纽 == hub_next()，每步 next == step_next()。
    hub = (wz.get("WuchongEntry") or {}).get("next")
    if list(hub or []) != list(W.hub_next()):
        msgs.append("枢纽漂移：WuchongEntry.next != scene.wuchong.hub_next()（数据/流水线不同步）")
    for node in W.flow_step_nodes():
        got = list((wz.get(node) or {}).get("next") or [])
        expect = list(W.step_next(node) or [])
        if got != expect:
            msgs.append(f"流程节点漂移：{node}.next != 异常前缀+本步后继（数据/流水线不同步）")

    # 显式：五重链的任何流程边 / 异常前缀都不得再含「放弃」节点。
    for i, r in enumerate(W.FLOW_EXCEPTIONS):
        if any(b in r for b in _BANNED_FRAGMENTS):
            msgs.append(f"FLOW_EXCEPTIONS[{i}]={r!r} 仍含『放弃』节点（五重不该再点放弃）")
    for node in W.flow_step_nodes():
        for r in list((wz.get(node) or {}).get("next") or []):
            if any(b in r for b in _BANNED_FRAGMENTS):
                msgs.append(f"{node}.next 仍含『放弃』节点 {r!r}（五重不该再点放弃）")

    # (c) 上限闸：WuchongContinueGuard 是 StopTask 出口、叶子型。
    guard = wz.get(W.CONTINUE_GUARD_NODE)
    if not isinstance(guard, dict):
        msgs.append(f"wuchong.json 缺 {W.CONTINUE_GUARD_NODE}（续关上限闸未落地）")
    else:
        if (guard.get("action") or {}).get("type") != "StopTask":
            msgs.append(
                f"{W.CONTINUE_GUARD_NODE} 动作应为 StopTask（带原因收工），实际 "
                f"{(guard.get('action') or {}).get('type')!r}"
            )
        if guard.get("next") != []:
            msgs.append(f"{W.CONTINUE_GUARD_NODE}.next 应为 []，实际 {guard.get('next')!r}")

    # (d) 全 pipeline 绝不用固定坐标点【续关】（应点识别框中心）。
    for fname, data in files.items():
        if not isinstance(data, dict):
            continue
        for node, spec in data.items():
            tgt = _target_of(spec) if isinstance(spec, dict) else None
            if isinstance(tgt, list) and len(tgt) == 2 and tuple(tgt) == FIXED_CONTINUE_COORD:
                msgs.append(f"{fname}::{node} 点了【续关】固定坐标 {FIXED_CONTINUE_COORD}（应点识别框中心）")

    # (e) 批量（special_dungeon）仍拒绝续关：SpecialEntry.next 仍引用 #38 的四个节点。
    entry = (sd.get("SpecialEntry") or {}).get("next") or []
    for name in _GAMEOVER_DECLINE_NODES:
        if f"[JumpBack]{name}" not in entry:
            msgs.append(f"SpecialEntry.next 缺 {name}（批量链的「放弃续关」被本票动坏了）")
    # 且 common.json 里 #38 的四个节点仍定义。
    for name in _GAMEOVER_DECLINE_NODES:
        if not isinstance(common.get(name), dict):
            msgs.append(f"common.json 缺 #38 节点 {name!r}（批量链引用悬空）")
    return msgs


def probe_wuchong_continues_on_gameover() -> bool:
    return chain_failures() == []


# ---------------------------------------------------------------------------
# 守卫 5：续关次数可配置（驱动**真实** WuchongContinueGuardRecognition）
# ---------------------------------------------------------------------------
def count_failures(mod=None, rec_factory=None) -> list[str]:
    """守卫 5：驱动**真实** ``WuchongContinueGuardRecognition`` 证明「次数可配置 + 有界」。
    ★计数口径★：按**进入 GAMEOVER 屏的次数**结算（运维原话「按进去的次数结算」）；计数在
    **episode 进入时、点击之前**发生 → 只可能**保守**（绝不漏计、绝不少于实际点中的续关次数）。
    ★两条带原因收工出口★：①上限用尽（cap 优先）；②同一 GAMEOVER 屏卡住超过 ``CONTINUE_STUCK_SEC``。
    """
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    from contract_hooks import hooks_wuchong as HW  # noqa: PLC0415

    _RecArgv = HW._RecArgv
    rec_cls = rec_factory or mod.WuchongContinueGuardRecognition
    msgs: list[str] = []

    def guard(param: dict, items, tid: int):
        real = mod._ocr
        try:
            mod._ocr = lambda context, image, entry="OcrTask": list(items)
            return rec_cls().analyze(None, _RecArgv(tid, param))
        finally:
            mod._ocr = real

    def hit(res) -> bool:
        return res.box == [0, 0, 0, 0]

    def reason(res) -> str:
        return str((res.detail or {}).get("reason") or "")

    def continues() -> int:
        with mod._LOCK:
            return int(mod._SESSION["continues_done"])

    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p72_progress.json")
        try:
            # ---- 场景 A：target=2 → 前两 episode 放行、第 3 个收工 ----
            mod.ledger.reset(mod.LEDGER_SCOPE)
            pa = {"ocr_entry": "OcrTask", "target_continues": 2}
            a1 = guard(pa, GAMEOVER_ITEMS, 720_001)          # episode 1 → n=1，放行
            a1b = guard(pa, GAMEOVER_ITEMS, 720_001)         # 同一 episode 的连帧 → 不重复计
            guard(pa, TEAM_FRAME, 720_001)                   # 离屏 → 清 episode 标记
            a2 = guard(pa, GAMEOVER_ITEMS, 720_001)          # episode 2 → n=2，放行
            guard(pa, TEAM_FRAME, 720_001)
            a3 = guard(pa, GAMEOVER_ITEMS, 720_001)          # episode 3 → n=3 > 2，收工
            if hit(a1) or hit(a1b) or hit(a2):
                msgs.append(f"target=2：前两个 episode 不应收工（应放行让续关点击）")
            if continues() != 3:
                msgs.append(f"target=2：每 episode 恰记一次（连帧只算一次），期望 3，实际 {continues()}")
            if not hit(a3):
                msgs.append("target=2：第 3 个 GAMEOVER episode 应收工（上限闸未触发）")
            elif "2" not in reason(a3):
                msgs.append(f"target=2：收工原因未点名上限 2：{reason(a3)!r}")
            sc = mod.ledger.scope(mod.CONTINUE_LEDGER_PREFIX)
            expect_ledger = [f"{mod.CONTINUE_LEDGER_PREFIX}/{i}" for i in (1, 2, 3)]
            if sc != expect_ledger:
                msgs.append(f"续关账本不对：{sc}（期望 {expect_ledger}）")

            # ---- 场景 B：target=0（不限）→ 多个 episode 永不由此停 ----
            mod.ledger.reset(mod.LEDGER_SCOPE)
            pb = {"ocr_entry": "OcrTask", "target_continues": 0}
            for _ in range(4):
                rb = guard(pb, GAMEOVER_ITEMS, 720_002)
                if hit(rb):
                    msgs.append("target=0（不限）竟收工（规格：续关无限）")
                    break
                guard(pb, TEAM_FRAME, 720_002)
            if continues() != 4:
                msgs.append(f"target=0：4 个 episode 应记 4 次，实际 {continues()}")

            # ---- 场景 C：target=1 → 第 1 个放行、第 2 个收工 ----
            mod.ledger.reset(mod.LEDGER_SCOPE)
            pc = {"ocr_entry": "OcrTask", "target_continues": 1}
            c1 = guard(pc, GAMEOVER_ITEMS, 720_003)
            guard(pc, TEAM_FRAME, 720_003)
            c2 = guard(pc, GAMEOVER_ITEMS, 720_003)
            if hit(c1):
                msgs.append("target=1：第 1 个 episode 不应收工")
            if not hit(c2):
                msgs.append("target=1：第 2 个 episode 应收工（恰好允许 1 次）")

            # ---- 场景 D：非 GAMEOVER 帧 → miss 且不计数 ----
            mod.ledger.reset(mod.LEDGER_SCOPE)
            pd = {"ocr_entry": "OcrTask", "target_continues": 5}
            d0 = guard(pd, POPUP_FRAME, 720_004)
            d1 = guard(pd, GAMEOVER_ITEMS, 720_004)          # 建一个 episode（n=1）
            guard(pd, POPUP_FRAME, 720_004)                  # 非 GAMEOVER → 清标记、不计
            if hit(d0):
                msgs.append("非 GAMEOVER 帧（体力弹窗）误命中续关守卫")
            if continues() != 1:
                msgs.append(f"非 GAMEOVER 帧不应计数（期望 1，实际 {continues()}）")
            _ = d1

            # ---- 场景 E：★有界卡住等待★ 同一 GAMEOVER 屏超 CONTINUE_STUCK_SEC 未推进 → 收工 ----
            #   （cap 未耗尽；模拟「续关点了但没生效 / 星导石不足，屏又弹回」→ 绝不重敲到 900s。）
            mod.ledger.reset(mod.LEDGER_SCOPE)
            pe = {"ocr_entry": "OcrTask", "target_continues": 5}
            e1 = guard(pe, GAMEOVER_ITEMS, 720_005)          # 建立 episode（n=1，cap 远未耗尽）
            if hit(e1):
                msgs.append("target=5：首个 episode 不应收工（cap 未耗尽）")
            with mod._LOCK:
                mod._SESSION["gameover_first_ts"] = mod.time.monotonic() - (
                    float(mod.CONTINUE_STUCK_SEC) + 5.0
                )
            e2 = guard(pe, GAMEOVER_ITEMS, 720_005)          # 同一 episode 卡住超时 → 收工
            if not hit(e2):
                msgs.append(
                    "GAMEOVER 屏卡住超过 CONTINUE_STUCK_SEC 仍未收工"
                    "（会重敲续关空转到通用 900s 兜底）"
                )
            elif "停留" not in reason(e2):
                msgs.append(f"卡住收工原因未点名停留时长：{reason(e2)!r}")
            if continues() != 1:
                msgs.append(f"卡住收工不应额外计数（同一 episode，期望 1，实际 {continues()}）")

            # ---- 结构性断言：★有界窗口必须为正★ + ★cap 优先于卡住★（cap reason 仍点名上限）----
            if not (isinstance(mod.CONTINUE_STUCK_SEC, (int, float)) and float(mod.CONTINUE_STUCK_SEC) > 0):
                msgs.append(f"CONTINUE_STUCK_SEC 应为正数（有界），实际 {mod.CONTINUE_STUCK_SEC!r}")
            if "续关次数用尽" not in reason(a3):
                msgs.append(
                    f"cap 优先性被破坏：target=2 第 3 个 episode 的收工原因应为『续关次数用尽…』，"
                    f"实际 {reason(a3)!r}"
                )
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_continue_count_configurable() -> bool:
    return count_failures() == []


# ---------------------------------------------------------------------------
# 守卫 6：GUI 选项「五重续关几次」接线（与「五重打几次」写不同节点、可共存）
# ---------------------------------------------------------------------------
def option_failures(root: Path | None = None) -> list[str]:
    W = _wuchong()
    import interface_options as iopt  # noqa: PLC0415

    proj = Path(root) if root is not None else REPO_ROOT
    iface = iopt.load_interface(proj)
    msgs: list[str] = []

    task = next((t for t in iface.get("task") or [] if t.get("name") == "五重决战"), None)
    if task is None or W.TARGET_CONTINUES_OPTION not in (task.get("option") or []):
        msgs.append(f"任务「五重决战」缺「{W.TARGET_CONTINUES_OPTION}」选项")

    block = (iface.get("option") or {}).get(W.TARGET_CONTINUES_OPTION) or {}
    if block.get("type") != "input":
        msgs.append(f"「{W.TARGET_CONTINUES_OPTION}」应为 input 选项（type={block.get('type')!r}）")

    ov = iopt.option_override(iface, W.TARGET_CONTINUES_OPTION, None, {"次数": "2"})
    rec_param = ((ov.get(W.CONTINUE_GUARD_NODE) or {}).get("recognition") or {}).get("param") or {}
    cp = rec_param.get("custom_recognition_param") or {}
    if rec_param.get("custom_recognition") != "wuchong_continue_guard":
        msgs.append(
            f"「{W.TARGET_CONTINUES_OPTION}」override 未写全 custom_recognition（整体替换 recognition）："
            f"{rec_param.get('custom_recognition')!r}"
        )
    if int(cp.get(W.TARGET_CONTINUES_FIELD) or 0) != 2:
        msgs.append(
            f"「{W.TARGET_CONTINUES_OPTION}=2」未落到 {W.CONTINUE_GUARD_NODE}."
            f"{W.TARGET_CONTINUES_FIELD}：{cp.get(W.TARGET_CONTINUES_FIELD)!r}"
        )

    # 既有「五重打几次」仍写 WuchongGiveUp（两写者共存、不同节点）。
    ov2 = iopt.option_override(iface, W.TARGET_FIGHTS_OPTION, None, {"次数": "3"})
    gp = (
        (((ov2.get("WuchongGiveUp") or {}).get("recognition") or {}).get("param") or {})
        .get("custom_recognition_param")
        or {}
    )
    if int(gp.get(W.TARGET_FIGHTS_FIELD) or 0) != 3:
        msgs.append(
            f"「{W.TARGET_FIGHTS_OPTION}=3」未落到 WuchongGiveUp.{W.TARGET_FIGHTS_FIELD}"
            f"（与续关选项撞车？）：{gp.get(W.TARGET_FIGHTS_FIELD)!r}"
        )
    return msgs


def probe_wuchong_continue_option_wired() -> bool:
    return option_failures() == []


# ---------------------------------------------------------------------------
# 守卫 7：承重短语零丢失 + 无漂移
# ---------------------------------------------------------------------------
def declared_failures(root: Path | None = None) -> list[str]:
    from scene import drift  # noqa: PLC0415

    proj = Path(root) if root is not None else REPO_ROOT
    text = (proj / "assets" / "resource" / "pipeline" / "special_dungeon.json").read_text(
        encoding="utf-8"
    )
    msgs = [
        f"承重短语「{p}」丢失（#12 硬规则：纯编辑不得丢注释）"
        for p in hooks_stamina.BEARING_PHRASES
        if text.count(p) < 1
    ]
    msgs.extend(drift.check_all(repo_root=proj))
    return msgs


def probe_wuchong_continue_declared() -> bool:
    return declared_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，``python tools\\contract_hooks\\hooks_72.py``）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook72_"))
    (root / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "assets" / "resource", root / "assets" / "resource")
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class _BrokenCapRecognizer:
    """坏实现：把「续关次数用尽即收工」放宽成永不收工（等价 ``n >= target+99``）。"""

    def __init__(self, mod):
        self._mod = mod
        self._real = mod.WuchongContinueGuardRecognition()

    def analyze(self, context, argv):  # noqa: N802
        res = self._real.analyze(context, argv)
        if res.box == [0, 0, 0, 0]:
            # 本该收工的一帧被放行（上限永不触发）。
            return self._mod.CustomRecognition.AnalyzeResult(
                box=None, detail={"continue": False, "broken_cap": True}
            )
        return res


def prove_red() -> bool:
    W = _wuchong()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_72 prove-red：七处破坏，要求守卫各自变红")
    green = (
        probe_gameover_continue_nodes_declared() is True
        and probe_gameover_continue_frame() is True
        and probe_gameover_not_stamina() is True
        and probe_wuchong_continue_phrases_single_source() is True
        and probe_wuchong_continues_on_gameover() is True
        and probe_wuchong_continue_count_configurable() is True
        and probe_wuchong_continue_option_wired() is True
        and probe_wuchong_continue_declared() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：八个守卫全绿")
    if not green:
        return False

    common = _load_common()
    files = _load_pipelines()

    # (a) 从五重数据/流水线摘掉 [JumpBack]PubGameOverContinue -> 守卫 4 红。
    saved_flow = W.FLOW_EXCEPTIONS
    try:
        W.FLOW_EXCEPTIONS = tuple(x for x in saved_flow if x != f"[JumpBack]{W.CONTINUE_NODE}")
        msgs = chain_failures(files)
        red_a = len(msgs) > 0
        print(f"  [{'PASS' if red_a else 'FAIL'}] 摘掉 [JumpBack]PubGameOverContinue（五重不再点续关）-> "
              f"{'红' if red_a else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
    finally:
        W.FLOW_EXCEPTIONS = saved_flow

    # (b) 把续关节点指向固定坐标 [506,1061] -> 守卫 1（及 4d）红。
    broken = copy.deepcopy(common)
    broken[W.CONTINUE_NODE]["action"]["param"]["target"] = [506, 1061]
    m1 = node_failures(broken)
    red_b1 = len(m1) > 0
    bfiles = dict(files)
    bcommon = copy.deepcopy(common)
    bcommon[W.CONTINUE_NODE]["action"]["param"]["target"] = [506, 1061]
    bfiles["common.json"] = bcommon
    m4 = chain_failures(bfiles)
    red_b4 = len(m4) > 0
    print(f"  [{'PASS' if (red_b1 and red_b4) else 'FAIL'}] 续关节点改成固定坐标 -> "
          f"守卫1 {'红' if red_b1 else '仍绿'}；守卫4d {'红' if red_b4 else '仍绿'}"
          + (f"  {(m1 + m4)[0]}" if (m1 or m4) else ""))
    red_b = red_b1 and red_b4

    # (c) guard 动作从 StopTask 改成 Click -> 守卫 4c 红。
    bz = copy.deepcopy(files.get("wuchong.json") or {})
    bz.setdefault(W.CONTINUE_GUARD_NODE, {})["action"] = {"type": "Click", "param": {}}
    cfiles = dict(files)
    cfiles["wuchong.json"] = bz
    m_c = chain_failures(cfiles)
    red_c = len(m_c) > 0
    print(f"  [{'PASS' if red_c else 'FAIL'}] guard 动作 StopTask 改 Click -> "
          f"{'红' if red_c else '仍绿'}" + (f"  {m_c[0]}" if m_c else ""))

    # (d) 放宽上限语义（收工 -> 放行）-> 守卫 5 红。
    m_d = count_failures(impl, rec_factory=lambda: _BrokenCapRecognizer(impl))
    red_d = len(m_d) > 0
    print(f"  [{'PASS' if red_d else 'FAIL'}] 放宽续关上限（收工 -> 放行）-> "
          f"{'红' if red_d else '仍绿'}" + (f"  {m_d[0]}" if m_d else ""))

    # (d2) 把「有界卡住等待」拆掉（CONTINUE_STUCK_SEC = inf）-> 守卫 5 红（卡住不再收工）。
    saved_stuck = impl.CONTINUE_STUCK_SEC
    try:
        impl.CONTINUE_STUCK_SEC = float("inf")
        m_d2 = count_failures(impl)
        red_stuck = len(m_d2) > 0
        print(f"  [{'PASS' if red_stuck else 'FAIL'}] 拆掉卡住上界（CONTINUE_STUCK_SEC=inf）-> "
              f"{'红' if red_stuck else '仍绿'}" + (f"  {m_d2[0]}" if m_d2 else ""))
    finally:
        impl.CONTINUE_STUCK_SEC = saved_stuck

    # (e) 从 interface.json 去掉选项的 target_continues 字段 -> 守卫 6 红。
    root = _temp_assets()
    try:
        _sub(
            root / "assets" / "interface.json",
            '"target_continues": "{次数}"',
            '"target_continues_x": "{次数}"',
        )
        m_e = option_failures(root)
        red_e = len(m_e) > 0
        print(f"  [{'PASS' if red_e else 'FAIL'}] interface 去掉 target_continues 字段 -> "
              f"{'红' if red_e else '仍绿'}" + (f"  {m_e[0]}" if m_e else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (f) 让 scene.wuchong 的 GAMEOVER 短语与 side_impl 分叉 -> 守卫 3b 红。
    saved_prompt = W.CONTINUE_PROMPT_TEXT
    try:
        W.CONTINUE_PROMPT_TEXT = "x"
        m_f = phrases_single_source_failures()
        red_f = len(m_f) > 0
        print(f"  [{'PASS' if red_f else 'FAIL'}] scene.wuchong 续关短语与 side_impl 分叉 -> "
              f"{'红' if red_f else '仍绿'}" + (f"  {m_f[0]}" if m_f else ""))
    finally:
        W.CONTINUE_PROMPT_TEXT = saved_prompt

    ok = green and red_a and red_b and red_c and red_d and red_stuck and red_e and red_f
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "gameover-continue-nodes-declared",
        "#72",
        "两个公共节点 PubGameOverContinueBtn/PubGameOverContinue 在场；Btn=OCR+^续关$+ROI；"
        "动作=And(横幅,询问,续关) box_index=2 → Click target:true（点识别框中心、零死偏移）、叶子型",
        probe_gameover_continue_nodes_declared,
    ),
    (
        "gameover-continue-frame",
        "#72",
        "真机 GAMEOVER 帧命中且点【续关】框中心 (506,1061)；确认框/编队页/体力弹窗/缺叶 都不命中",
        probe_gameover_continue_frame,
    ),
    (
        "gameover-not-stamina-and-vice-versa",
        "#72",
        "续关费与体力恢复互不误命中：GAMEOVER 帧上体力两步 miss、体力弹窗帧上续关 miss；"
        "两屏分界是体力 And 的【弹窗正文】叶（#74 后 ROI 已与 GAMEOVER 星导石 y 交叠，不再单独承重）",
        probe_gameover_not_stamina,
    ),
    (
        "wuchong-continue-phrases-single-source",
        "#72",
        "GAMEOVER 短语唯一真源：scene.wuchong.CONTINUE_TITLE_TEXT/CONTINUE_PROMPT_TEXT "
        "== side_impl.GAMEOVER_TITLE/GAMEOVER_PROMPT，且 common.json 横幅/询问叶包含它们",
        probe_wuchong_continue_phrases_single_source,
    ),
    (
        "wuchong-continues-on-gameover",
        "#72",
        "五重在 GAMEOVER 屏点续关：FLOW_EXCEPTIONS 用 continue_refs()（guard 在前）、"
        "流程链与 step_next/hub_next 同步、无『放弃』、guard=StopTask、无固定续关坐标；"
        "批量 SpecialEntry.next 仍引用 #38 四节点（仍拒绝续关）",
        probe_wuchong_continues_on_gameover,
    ),
    (
        "wuchong-continue-count-configurable",
        "#72",
        "续关次数可配置 + 有界：驱动真实 WuchongContinueGuardRecognition —— target=2 第 3 个 episode 收工并点名 2"
        "（cap 优先于卡住）、target=0 不限、target=1 第 2 个收工；每 episode 恰记一次（按进入 GAMEOVER 屏次数结算）；"
        "同一屏卡住超 CONTINUE_STUCK_SEC 带原因收工；账本 wuchong/continue/{n}；非 GAMEOVER 不计",
        probe_wuchong_continue_count_configurable,
    ),
    (
        "wuchong-continue-option-wired",
        "#72",
        "GUI「五重续关几次」（input）覆盖 WuchongContinueGuard.target_continues；"
        "既有「五重打几次」仍写 WuchongGiveUp（两写者共存、不同节点）",
        probe_wuchong_continue_option_wired,
    ),
    (
        "wuchong-continue-declared",
        "#72",
        "承重短语零丢失（special_dungeon.json 五条各 ≥1）+ scene.drift.check_all() == []",
        probe_wuchong_continue_declared,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
