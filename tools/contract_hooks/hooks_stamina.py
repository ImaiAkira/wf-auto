# -*- coding: utf-8 -*-
"""#68：体力不足 → 星岛石恢复 —— 五重 / 战阵之宴 / 领主战族 / 深渊共用一份（数据声明）。

seam
----
* ``scene/stamina.py``：判据短语 / 节点名 / 策略（**只用星岛石恢复**）/ 需要接线的链 —— 唯一真源。
* ``assets/resource/pipeline/common.json``：九个公共节点（``PubStamina*``；★#68 的六 + 第三态
  结果窗三个★）—— 与其它 ``Pub*`` 同处一地，各链只以 ``[JumpBack]`` 引用
  （ADR-0003：同一事实不得有第二份拷贝）。
* ``assets/resource/pipeline/{wuchong,raid,special_dungeon,abyss,auto_push,side_story}.json``：每个
  消耗体力的场景各自在枢纽 / 分派表 ``next`` 里引用恢复链（五重经 ``scene.wuchong.FLOW_EXCEPTIONS``
  注入每个流程节点；迷宫/幻想经 ``SpecialEntry`` 分派 → 由 ``SpecialEntry.next`` 覆盖）。

诊断（真机 —— 旧线 ``<repo-旧线>`` 战阵之宴「回复体力」弹窗；逐条 OCR 见 ``POPUP_FRAME`` / ``CONFIRM_FRAME``）
------------------------------------------------------------------------------------
体力不足时游戏弹出「回复体力」弹窗（副标题「请选择要使用的道具」，选项里有 **星导石 × 50**），
点它弹「是否消耗星导石回复体力?」二次确认框，点 ``OK`` 才真扣星导石、体力 +100、关卡开打。
此前 pipeline **没有任何节点认这些弹窗** → 流程停在弹窗上空等，直到各场景有界收工把它停掉。
运维裁决（settled）：「需要补的，因为五重会消耗体力」；「**只用星岛石恢复**」。

守卫（本文件；prove-red 见文末）
-------------------------------
1. ``stamina-nodes-declared`` —— 九个公共节点在场、判据与 ``scene.stamina`` 一致、动作是
   ``And(...) + box_index=1`` → ``Click target:true``（**点识别框中心、零死偏移**）、叶子型。
   ★第三态结果窗★：``PubStaminaDoneText``（正文「体力回复了！」）/ ``PubStaminaDoneOkText``
   （OK 叶，roi == ``DONE_OK_ROI``）/ ``PubStaminaDoneOk``（动作：And box_index=1）。
2. ``stamina-wired-every-consumer`` —— **②「每个流程节点的 next 都含全部这些项」**：每个消耗体力
   的场景（五重 / 战阵之宴 / 领主战族 / 深渊 / 主线 / 外传两个入口）的枢纽 ``next`` 都必须含
   :func:`scene.stamina.recovery_refs` 的**每一项**（缺一个 = 那一步处理不了体力弹窗），且被引用
   的节点确有定义；五重经 ``FLOW_EXCEPTIONS`` → 中继 ``WuchongGuardChain`` 注入每个流程节点，
   故等价断言三条（真源里有 / 中继投影里有 / 每个流程节点仍挂着通往中继的跳转）。
3. ``stamina-stone-only-policy`` —— **①「``recovery_refs()`` 的集合与顺序 == ``scene/stamina.py``
   的声明」**（唯一真源 = ``RECOVERY_STEPS``：#102 起是**四项** —— 模板优先行 → OCR 兜底行 →
   确认框 OK → 结果窗 OK，每一步的理由写在该常量上方）+ **③「模板优先项排在 OCR 版之前」**
   （每个消费链枢纽 + 五重中继：``next`` 是**有序候选**，先命中先执行，反过来模板通道永远轮不到）；
   外加策略：只用星岛石（``RECOVER_WITH_STONE``）；**没有第二份免费道具路径**；容忍
   ``星导石 / 星岛石`` 两种写法；【取消】绝不被点。
4. ``stamina-real-frame`` —— **真机帧回放**（内嵌旧线三张帧 + 本线真机 384 帧的逐条 OCR）：
   弹窗帧命中且**点的是「星导石 × 50」框中心**、确认帧命中且**点的是 OK 框中心**；准备页 /
   只有弹窗没有星导石行 / 只有星导石行没有弹窗正文 / 弹窗帧问确认框 都**不**命中（与门/ROI
   是承重的）。★第三态结果窗★的互不误命中由 ``hooks_stamina_done`` 单独把守（本文件不复制）。

★prove-red★（``python tools\\contract_hooks\\hooks_stamina.py``）七处破坏，要求守卫各自变红：
  * 从某条链（``AbyssEntry.next``）摘掉恢复引用（= 该场景「无人处理」）-> 守卫 2 红；
  * 从 ``scene.wuchong.FLOW_EXCEPTIONS`` 摘掉恢复引用 -> 守卫 2 红（每个流程节点都丢）；
  * 把动作换成固定死点 ``target:[522,823]`` -> 守卫 1 红（不许死偏移）；
  * 把 ``box_index`` 改成 0（点弹窗正文框 / 确认框标题框）-> 守卫 4 红（没点到目标框中心）；
  * 去掉星导石行 ROI（判据与 scene.stamina 的 ROI 不同步）-> 守卫 1 红；
  * ★#102★ 把模板优先项挪到 OCR 版**之后**（模板通道永远轮不到）-> 守卫 3 红（③）；
  * ★#102★ 把 ``RECOVERY_STEPS`` 的两条通道对调（真源与守卫的声明顺序不符）-> 守卫 3 红（①）。

诚实边界
--------
真机帧（旧线临时目录）随运行消失；这里内嵌**逐条 OCR**（与 hooks_44 / hooks_38 / hooks_60 /
hooks_raid_done_popup 同做法），不重跑 MAA OCR。``tools/verify_stamina_frames.py`` 另做一次
**真 MAA 回放**（直接读旧线 PNG + 本仓真机 384 帧；缺 maa / 模型 / 帧则 SKIP）。本线**未主动**
在真机制造过「体力不足」状态（账号体力接近上限），但**第四跑真机 384 已自然到达**该流程并
覆盖到第三态。
★历史更正（supersede）★：旧说法「旧线第三态「体力回复了！」结果窗本票未覆盖（五重点 OK 后
关卡直接开打，见 8-stamina-ok.txt）」**已被真机 384 第四跑（2026-10-16）证伪** —— 该结果窗
**确实**出现且此前无节点认它（五重空转到「未知画面累计 121 次」兜底）。现作为恢复链第一类
参与的第三态处理；真机证据见 ``tools/frames/stamina_recovered_done_wuchong384.png``。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
PIPE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

#: 承重短语（#12 硬规则：纯编辑不得丢这些注释）—— special_dungeon.json 里各须 ≥1。
BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

#: ★恢复链的**声明顺序**（#102 口径，逐项 pin）★ —— ``scene.stamina.RECOVERY_STEPS`` /
#: ``RECOVERY_NODES`` / ``recovery_refs()`` 三者都必须与它逐项相等（①）。
#:
#: ★为什么在守卫里**再写一遍字面量**（而不是直接读 scene.stamina）★：这是「第二见证人」——
#: 改顺序就必须同时改这里，于是「为什么是这个顺序」会被重新问一次。顺序是**承重**的：
#: ``next`` 是有序候选、先命中先执行，模板优先项必须真的排在 OCR 版之前（③）；
#: 确认框 / 结果窗必须在两条行判据之后（它们只在「已经点过这一行」之后才在屏上）。
RECOVERY_ORDER: tuple[str, ...] = (
    "PubStaminaUseStoneTpl",   # 第一步·模板优先（行图标模板，见 scene/templates.py）
    "PubStaminaUseStone",      # 第一步·OCR 兜底（行名 星导石/星岛石）
    "PubStaminaConfirmOk",     # 第二步·二次确认框 OK（★真扣星导石、体力 +100★）
    "PubStaminaDoneOk",        # 第三步·「体力回复了！」结果窗 OK（幂等叶子）
)

# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；源：旧线 <repo-旧线> 战阵之宴「回复体力」弹窗）
# ---------------------------------------------------------------------------
#: 弹窗帧（``…\debug\on_error\2026.10.08-00.08.14.450_RaidStaminaConfirm.png``）。
POPUP_FRAME: list[tuple[str, list[int]]] = [
    ("回复体力", [300, 108, 118, 37]),
    ("请选择要使用的道具", [234, 149, 250, 28]),
    ("体力", [230, 249, 83, 40]),
    ("675/103", [379, 250, 122, 32]),
    ("体力回复药（小）", [209, 500, 207, 32]),
    ("体力回复药（中）", [209, 645, 208, 32]),
    ("体力回复药（大）", [210, 789, 208, 32]),
    ("星导石 × 50", [209, 934, 161, 32]),
    ("取消", [326, 1088, 67, 41]),
]
#: 二次确认框帧（``…\debug\on_error\2026.10.08-00.08.55.775_RaidStaminaDone.png``）。
CONFIRM_FRAME: list[tuple[str, list[int]]] = [
    ("是否消耗星导石回复体力?", [191, 486, 322, 28]),
    ("取消", [164, 805, 63, 37]),
    ("OK", [496, 805, 53, 37]),
    ("五重决战超级", [219, 116, 172, 32]),
    ("挑战", [297, 1050, 155, 50]),
]
#: 反例帧：编队页（有「挑战」但**没有**弹窗）。
TEAM_FRAME: list[tuple[str, list[int]]] = [
    ("挑战", [297, 1054, 81, 46]),
    ("体力", [389, 168, 46, 25]),
    ("35", [472, 169, 30, 23]),
    ("编成", [513, 952, 46, 25]),
    ("自动续战", [17, 1062, 79, 24]),
]

#: 真机「星导石 × 50」框 [209,934,161,32] → 中心。
EXPECTED_STONE_BOX = [209, 934, 161, 32]
EXPECTED_STONE_CENTER = (289, 950)
#: 真机确认框【OK】框 [496,805,53,37] → 中心 (522,823)。
EXPECTED_OK_BOX = [496, 805, 53, 37]
EXPECTED_OK_CENTER = (522, 823)

#: 裁剪保读率阈值（真实 MAA：先按 roi 裁剪再 OCR）——与 hooks_37 同模型。
VISIBLE_MIN = 0.7


# ---------------------------------------------------------------------------
# JSONC 读取 / 小工具
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    state = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch); state = 1; i += 1
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
                out.append(ch); i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch); state = 1; i += 1
    return "".join(out)


def load_json(path: Path) -> dict:
    data = json.loads(_strip_jsonc(Path(path).read_text(encoding="utf-8")))
    return data if isinstance(data, dict) else {}


def load_common(root: Path | None = None) -> dict:
    base = Path(root) / "assets" / "resource" / "pipeline" if root is not None else PIPE_DIR
    return load_json(base / "common.json")


def load_chain(file: str, root: Path | None = None) -> dict:
    base = Path(root) / "assets" / "resource" / "pipeline" if root is not None else PIPE_DIR
    return load_json(base / file)


def _all_pipeline_files(root: Path | None = None) -> dict:
    base = Path(root) / "assets" / "resource" / "pipeline" if root is not None else PIPE_DIR
    out: dict = {}
    for p in sorted(base.glob("*.json")):
        for k, v in load_json(p).items():
            out.setdefault(k, v)
    return out


def _sd_text(root: Path | None = None) -> str:
    base = Path(root) / "assets" / "resource" / "pipeline" if root is not None else PIPE_DIR
    return (base / "special_dungeon.json").read_text(encoding="utf-8")


def _center(box) -> tuple[int, int]:
    x, y, w, h = box
    return int(x + w / 2), int(y + h / 2)


def _box_visible_fraction(box, roi) -> float:
    x, y, w, h = box
    if w <= 0 or h <= 0 or roi is None:
        return 0.0
    ix0, iy0 = max(x, roi[0]), max(y, roi[1])
    ix1, iy1 = min(x + w, roi[0] + roi[2]), min(y + h, roi[1] + roi[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    return (iw * ih) / float(w * h)


def _ocr_first(items, node: dict):
    """按节点的 expected + roi（裁剪保读率模型）取第一个命中框；无命中返回 None。"""
    param = (node.get("recognition") or {}).get("param") or {}
    pats = param.get("expected") or []
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return list(box)
        if _box_visible_fraction(box, roi) >= VISIBLE_MIN:
            return list(box)
    return None


def and_eval(common: dict, action_node: str, items):
    """模拟 MAA ``And(all_of=..., box_index=...)``：返回 (命中?, 输出框, 各叶框)。"""
    node = common.get(action_node) or {}
    param = (node.get("recognition") or {}).get("param") or {}
    leaves = list(param.get("all_of") or [])
    bi = int(param.get("box_index", 0))
    boxes: list[list[int]] = []
    for name in leaves:
        leaf = common.get(name) or {}
        box = _ocr_first(items, leaf)
        if box is None:
            return False, None, boxes
        boxes.append(box)
    if not boxes:
        return False, None, boxes
    idx = bi if 0 <= bi < len(boxes) else 0
    return True, boxes[idx], boxes


def _stamina():
    if "scene" not in sys.modules:
        pass
    from scene import stamina  # noqa: PLC0415

    return stamina


# ---------------------------------------------------------------------------
# 守卫 1：数据声明（判据与配置一致 + 读后动零偏移 + 叶子型）
# ---------------------------------------------------------------------------
def node_failures(common: dict) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    nodes = S.STAMINA_NODES
    for name in nodes:
        if not isinstance(common.get(name), dict):
            msgs.append(f"common.json 缺少公共节点 {name!r}（体力恢复未被数据声明地处理）")
    if msgs:
        return msgs

    def rec(name):
        return common[name].get("recognition") or {}

    def param(name):
        return rec(name).get("param") or {}

    # 正文叶：OCR + 认得出弹窗副标题 / 标题变体。
    if rec(S.NODE_INSUFFICIENT).get("type") != "OCR":
        msgs.append(f"{S.NODE_INSUFFICIENT} 应为 OCR（弹窗正文叶）")
    exp = param(S.NODE_INSUFFICIENT).get("expected") or []
    if not any(re.search(p, S.POPUP_TEXT) for p in exp):
        msgs.append(f"{S.NODE_INSUFFICIENT}.expected={exp!r} 认不出弹窗副标题 {S.POPUP_TEXT!r}")

    # 星导石行叶：OCR + 容忍变体 + ROI 与配置一致。
    if rec(S.NODE_STONE).get("type") != "OCR":
        msgs.append(f"{S.NODE_STONE} 应为 OCR（星导石行叶）")
    stone_exp = param(S.NODE_STONE).get("expected") or []
    for variant in S.STONE_ROW_TEXTS:
        if not any(re.search(p, variant) for p in stone_exp):
            msgs.append(f"{S.NODE_STONE}.expected={stone_exp!r} 认不出变体 {variant!r}")
    if list(param(S.NODE_STONE).get("roi") or []) != list(S.STONE_ROW_ROI):
        msgs.append(
            f"{S.NODE_STONE}.roi={param(S.NODE_STONE).get('roi')!r} != scene.stamina.STONE_ROW_ROI "
            f"{list(S.STONE_ROW_ROI)!r}（配置/产物不同步）"
        )

    # 确认框标题叶：OCR + 认得出真机标题 + 容忍变体。
    if rec(S.NODE_CONFIRM).get("type") != "OCR":
        msgs.append(f"{S.NODE_CONFIRM} 应为 OCR（确认框标题叶）")
    conf_exp = param(S.NODE_CONFIRM).get("expected") or []
    if not any(
        re.search(p, "是否消耗星导石回复体力") and re.search(p, "是否消耗星岛石回复体力")
        for p in conf_exp
    ):
        msgs.append(
            f"{S.NODE_CONFIRM}.expected={conf_exp!r} 未同时容忍 星导石/星岛石 的确认框标题"
        )

    # OK 按钮叶：OCR + ^OK$ + ROI 与配置一致（避开【取消】）。
    if rec(S.NODE_OK).get("type") != "OCR":
        msgs.append(f"{S.NODE_OK} 应为 OCR（OK 按钮叶）")
    if param(S.NODE_OK).get("expected") != [S.OK_TEXT]:
        msgs.append(f"{S.NODE_OK}.expected={param(S.NODE_OK).get('expected')!r} 应为 [{S.OK_TEXT!r}]")
    if list(param(S.NODE_OK).get("roi") or []) != list(S.OK_BTN_ROI):
        msgs.append(
            f"{S.NODE_OK}.roi={param(S.NODE_OK).get('roi')!r} != scene.stamina.OK_BTN_ROI "
            f"{list(S.OK_BTN_ROI)!r}"
        )

    # ★第三态结果窗★正文叶：OCR + 认得出「体力回复了！」。
    if rec(S.NODE_DONE_TEXT).get("type") != "OCR":
        msgs.append(f"{S.NODE_DONE_TEXT} 应为 OCR（结果窗正文叶）")
    done_exp = param(S.NODE_DONE_TEXT).get("expected") or []
    if not any(re.search(p, S.DONE_TEXT) for p in done_exp):
        msgs.append(f"{S.NODE_DONE_TEXT}.expected={done_exp!r} 认不出结果窗正文 {S.DONE_TEXT!r}")

    # ★第三态结果窗★ OK 叶：OCR + ^OK$ + ROI 与配置一致（自有 ROI，排除确认框 OK）。
    if rec(S.NODE_DONE_OK_TEXT).get("type") != "OCR":
        msgs.append(f"{S.NODE_DONE_OK_TEXT} 应为 OCR（结果窗 OK 叶）")
    if param(S.NODE_DONE_OK_TEXT).get("expected") != [S.OK_TEXT]:
        msgs.append(
            f"{S.NODE_DONE_OK_TEXT}.expected={param(S.NODE_DONE_OK_TEXT).get('expected')!r} "
            f"应为 [{S.OK_TEXT!r}]"
        )
    if list(param(S.NODE_DONE_OK_TEXT).get("roi") or []) != list(S.DONE_OK_ROI):
        msgs.append(
            f"{S.NODE_DONE_OK_TEXT}.roi={param(S.NODE_DONE_OK_TEXT).get('roi')!r} != "
            f"scene.stamina.DONE_OK_ROI {list(S.DONE_OK_ROI)!r}"
        )

    # 三个动作节点：And + box_index=1 + Click target:true（零死偏移）+ 叶子型。
    for name, leaves in (
        (S.NODE_USE_STONE, [S.NODE_INSUFFICIENT, S.NODE_STONE]),
        (S.NODE_CONFIRM_OK, [S.NODE_CONFIRM, S.NODE_OK]),
        (S.NODE_DONE_OK, [S.NODE_DONE_TEXT, S.NODE_DONE_OK_TEXT]),
    ):
        node = common[name]
        if rec(name).get("type") != "And":
            msgs.append(f"{name} 识别应为 And（弹窗 ∧ 目标），实际 {rec(name).get('type')!r}")
        if list(param(name).get("all_of") or []) != leaves:
            msgs.append(f"{name}.all_of 应为 {leaves!r}，实际 {param(name).get('all_of')!r}")
        if int(param(name).get("box_index", 0)) != 1:
            msgs.append(
                f"{name}.box_index 应为 1（输出【目标】框 = 星导石行 / OK），实际 "
                f"{param(name).get('box_index')!r} —— 否则会点到弹窗正文/标题而不是目标"
            )
        act = node.get("action") or {}
        ap = act.get("param") or {}
        if act.get("type") != "Click" or ap.get("target") is not True:
            msgs.append(
                f"{name} 动作应为 Click target:true（点识别框中心、零死偏移），实际 "
                f"{act.get('type')!r}/{ap.get('target')!r}"
            )
        if isinstance(ap.get("target_offset"), (list, tuple)) and any(
            float(v or 0) != 0.0 for v in ap["target_offset"]
        ):
            msgs.append(f"{name} 用了死偏移 target_offset={ap.get('target_offset')!r}（要求零偏移）")
        if node.get("next") != []:
            msgs.append(f"{name}.next 应为 []（叶子型：点掉后弹窗消失、自然不再命中），实际 {node.get('next')!r}")
    return msgs


def probe_stamina_nodes_declared() -> bool:
    return node_failures(load_common()) == []


# ---------------------------------------------------------------------------
# 守卫 2：每个消耗体力的场景都接线（配置 ↔ 产物同步）
# ---------------------------------------------------------------------------
def wiring_failures(root: Path | None = None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    refs = list(S.recovery_refs())
    if not refs:
        return ["scene.stamina.recovery_refs() 为空（策略关掉了恢复，五重等场景又变『无人处理』）"]

    known = _all_pipeline_files(root)
    for name in S.RECOVERY_NODES:
        if name not in known:
            msgs.append(f"恢复链引用的节点 {name!r} 在 pipeline 里没有定义（悬空引用）")

    # ② 各场景枢纽 / 分派表 next 必须携带**全部**恢复引用（缺一项 = 那一步处理不了体力弹窗）。
    for scene, file, hub in S.STAMINA_CONSUMING_CHAINS:
        data = load_chain(file, root)
        node = data.get(hub)
        if not isinstance(node, dict):
            msgs.append(f"[{scene}] {file}::{hub} 不存在（消耗体力的场景找不到接线点）")
            continue
        nxt = list(node.get("next") or [])
        missing = [r for r in refs if r not in nxt]
        if missing:
            msgs.append(
                f"[{scene}] {file}::{hub}.next 缺恢复引用 {missing} —— 体力不足弹窗在该场景"
                f"『无人处理』（停到有界收工）"
            )

    # ②（续）五重：经 FLOW_EXCEPTIONS 注入 —— ★#103 起**注入点搬到场景接口层的中继**★
    #   （业务节点 next 只剩 ``[验证器, [JumpBack]SceneEnterWuchong]``，20 项异常收进
    #   ``WuchongGuardChain``）。等价断言三条（intent 不变：**每一步**都能处理体力不足弹窗）：
    #     2a 恢复引用仍在 ``FLOW_EXCEPTIONS``（真源）；
    #     2b 中继节点里带着它们（投影同步）；
    #     2c 每个流程节点仍挂着通往中继的那条跳转（否则那一步就漏掉了体力弹窗处理）。
    from scene import wuchong as W  # noqa: PLC0415

    for r in refs:
        if r not in W.FLOW_EXCEPTIONS:
            msgs.append(f"[五重] scene.wuchong.FLOW_EXCEPTIONS 缺恢复引用 {r!r}（流程节点不会处理弹窗）")
    scene_file = getattr(W, "SCENE_FILE", "wuchong_scene.json")
    relay_name = getattr(W, "SCENE_GUARD_CHAIN", "WuchongGuardChain")
    relay = load_chain(scene_file, root).get(relay_name) or {}
    relay_next = list(relay.get("next") or [])
    for r in refs:
        if r not in relay_next:
            msgs.append(
                f"[五重] {scene_file}::{relay_name}.next 缺恢复引用 {r!r}"
                f"（= FLOW_EXCEPTIONS 与产物不同步）"
            )
    wdata = load_chain("wuchong.json", root)
    enter_ref = f"[JumpBack]{getattr(W, 'SCENE_ENTER', 'SceneEnterWuchong')}"
    for s in list(W.flow_step_nodes()):
        nxt = list((wdata.get(s) or {}).get("next") or [])
        if enter_ref not in nxt:
            msgs.append(
                f"[五重] {s}.next 没有 {enter_ref}（该步不再通往中继 → 体力不足弹窗无人处理）"
            )
    return msgs


def probe_stamina_wired_every_consumer() -> bool:
    return wiring_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：策略 —— 只用星岛石；① 声明顺序；③ 模板优先项在 OCR 版之前；取消绝不点
# ---------------------------------------------------------------------------
def _stamina_hub_nexts(root: Path | None = None) -> list[tuple[str, str, list[str]]]:
    """每个消费链枢纽的 ``(文件, 枢纽, next)`` —— ③ 的遍历入口（② 的遍历在 wiring_failures）。"""
    from scene import stamina as S  # noqa: PLC0415

    out: list[tuple[str, str, list[str]]] = []
    for _scene, file, hub in S.STAMINA_CONSUMING_CHAINS:
        node = load_chain(file, root).get(hub)
        out.append((file, hub, list((node or {}).get("next") or [])))
    return out


def _declared_order_failures() -> list[str]:
    """① ``recovery_refs()`` 的**集合与顺序** == ``scene/stamina.py`` 的声明（= :data:`RECOVERY_ORDER`）。"""
    from scene import stamina as S  # noqa: PLC0415

    from scene import templates as T  # noqa: PLC0415

    msgs: list[str] = []
    want_refs = tuple(f"[JumpBack]{name}" for name in RECOVERY_ORDER)
    if tuple(S.RECOVERY_STEPS) != RECOVERY_ORDER:
        msgs.append(
            f"scene.stamina.RECOVERY_STEPS={tuple(S.RECOVERY_STEPS)!r} != 声明顺序 "
            f"{RECOVERY_ORDER!r}（恢复链的顺序是承重的：模板优先行 → OCR 兜底行 → 确认框 → 结果窗）"
        )
    if tuple(S.RECOVERY_NODES) != RECOVERY_ORDER:
        msgs.append(
            f"scene.stamina.RECOVERY_NODES={tuple(S.RECOVERY_NODES)!r} != {RECOVERY_ORDER!r}"
            f"（裸节点名与恢复链不是同一份东西了）"
        )
    if tuple(S.recovery_refs()) != want_refs:
        msgs.append(
            f"recovery_refs()={tuple(S.recovery_refs())!r} != {want_refs!r}"
            f"（引用是声明的 [JumpBack] 投影；不许在别处另行拼一份）"
        )
    # 模板优先那一项的名字只有**一个**真源（scene/templates.py）—— 抄错名字 = 整条通道静默失效。
    if S.NODE_STONE_TPL != T.NODE_USE_STONE_TPL:
        msgs.append(
            f"scene.stamina.NODE_STONE_TPL={S.NODE_STONE_TPL!r} != scene.templates.NODE_USE_STONE_TPL "
            f"{T.NODE_USE_STONE_TPL!r}（模板通道的节点名漂了）"
        )
    if S.NODE_STONE_TPL != RECOVERY_ORDER[0]:
        msgs.append(
            f"RECOVERY_ORDER 的首项应为模板优先通道 {S.NODE_STONE_TPL!r}，实际 {RECOVERY_ORDER[0]!r}"
            f"（模板优先 = 必须先被评估）"
        )
    return msgs


def _template_first_failures(root: Path | None = None) -> list[str]:
    """③ 模板优先项必须排在 OCR 版**之前**（每个消费链枢纽 + 五重中继）。

    缺项（②）由 :func:`wiring_failures` 点名，本函数只管**顺序**：两项都在、但模板在后时报红。
    五重中继（``WuchongGuardChain``）单列：``#103`` 起流程节点的 ``next`` 只剩
    ``[验证器, [JumpBack]SceneEnterWuchong]``，它们**只能**经中继拿到这些引用。
    """
    from scene import stamina as S  # noqa: PLC0415

    tpl_ref = f"[JumpBack]{S.NODE_STONE_TPL}"
    ocr_ref = f"[JumpBack]{S.NODE_USE_STONE}"
    msgs: list[str] = []

    def check(where: str, nxt: list[str]) -> None:
        if tpl_ref not in nxt or ocr_ref not in nxt:
            return  # 缺项 → wiring_failures 报（那里说的是「该步处理不了体力弹窗」）
        if nxt.index(tpl_ref) > nxt.index(ocr_ref):
            msgs.append(
                f"{where} 里 {tpl_ref} 排在 {ocr_ref} **之后** —— 候选是**按顺序**识别的，"
                f"OCR 会先吃掉该帧 → 模板通道永远轮不到（= #102 的模板优先白接）"
            )

    for file, hub, nxt in _stamina_hub_nexts(root):
        check(f"{file}::{hub}.next", nxt)

    from scene import wuchong as W  # noqa: PLC0415

    scene_file = getattr(W, "SCENE_FILE", "wuchong_scene.json")
    relay_name = getattr(W, "SCENE_GUARD_CHAIN", "WuchongGuardChain")
    relay = load_chain(scene_file, root).get(relay_name) or {}
    check(f"{scene_file}::{relay_name}.next", list(relay.get("next") or []))
    return msgs


def policy_failures(root: Path | None = None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    if S.RECOVER_WITH_STONE is not True:
        msgs.append("scene.stamina.RECOVER_WITH_STONE 应为 True（运维裁决：只用星岛石恢复）")

    # ★① 声明顺序 ⇄ recovery_refs()（唯一真源 = scene/stamina.py 的 RECOVERY_STEPS）★
    msgs.extend(_declared_order_failures())
    # ★③ 模板优先项排在 OCR 版之前（每个消费链枢纽 + 五重中继）★
    msgs.extend(_template_first_failures(root))

    # 无第二份免费道具路径：pipeline 里不得出现免费恢复道具节点（用工单规则：同一事实无第二拷贝）。
    known = _all_pipeline_files(root)
    stray = [n for n in known if n.startswith("PubStamina") and n not in S.STAMINA_NODES]
    if stray:
        msgs.append(f"pipeline 出现 scene.stamina 未声明的 PubStamina* 节点 {stray!r}（可能是第二份路径）")

    # 「取消」绝不被点：任何 PubStamina* 节点的动作不得 target 到取消框 / 不得用 CANCEL_TEXT 当目标。
    for name in S.STAMINA_NODES:
        node = known.get(name) or {}
        act = node.get("action") or {}
        ap = act.get("param") or {}
        tgt = ap.get("target")
        if act.get("type") == "Click" and isinstance(tgt, (list, tuple)):
            msgs.append(f"{name} 用固定坐标点 {tgt!r}（本项目红线：绝不「识别框 + 死偏移」猜按钮）")
    # 容忍变体：星导石 / 星岛石 都在判据里。
    if set(S.STONE_ROW_TEXTS) != {"星导石", "星岛石"}:
        msgs.append(f"STONE_ROW_TEXTS={S.STONE_ROW_TEXTS!r} 应同时含 星导石 / 星岛石（容忍 OCR 变体）")
    return msgs


def probe_stamina_stone_only_policy() -> bool:
    return policy_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：真机帧回放（内嵌旧线帧逐条 OCR）
# ---------------------------------------------------------------------------
def frame_failures(common: dict) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []

    # 第一步：弹窗帧命中且点【星导石 × 50】框中心。
    hit, box, _ = and_eval(common, S.NODE_USE_STONE, POPUP_FRAME)
    if not hit or box is None:
        msgs.append("真机弹窗帧（回复体力 + 星导石 × 50）未命中第一步（体力不足又变『无人处理』）")
    else:
        if list(box) != EXPECTED_STONE_BOX:
            msgs.append(f"弹窗帧输出框应为星导石行 {EXPECTED_STONE_BOX}，实际 {list(box)}")
        if _center(box) != EXPECTED_STONE_CENTER:
            msgs.append(
                f"弹窗帧点到 {_center(box)}，应为星导石行框中心 {EXPECTED_STONE_CENTER}（box={box}）"
            )

    # 第二步：确认帧命中且点【OK】框中心。
    hit2, box2, _ = and_eval(common, S.NODE_CONFIRM_OK, CONFIRM_FRAME)
    if not hit2 or box2 is None:
        msgs.append("真机确认帧（是否消耗星导石回复体力? + OK）未命中第二步（星导石扣不成就白点）")
    else:
        if list(box2) != EXPECTED_OK_BOX:
            msgs.append(f"确认帧输出框应为 OK 框 {EXPECTED_OK_BOX}，实际 {list(box2)}")
        if _center(box2) != EXPECTED_OK_CENTER:
            msgs.append(f"确认帧点到 {_center(box2)}，应为 OK 框中心 {EXPECTED_OK_CENTER}（box={box2}）")

    # 反例（与门/ROI 承重）：这些都必须【不命中】。
    negatives = [
        ("编队页（无弹窗）", S.NODE_USE_STONE, TEAM_FRAME),
        ("编队页（无弹窗）", S.NODE_CONFIRM_OK, TEAM_FRAME),
        ("确认帧（第一步不得命中）", S.NODE_USE_STONE, CONFIRM_FRAME),
        ("弹窗帧（第二步不得命中）", S.NODE_CONFIRM_OK, POPUP_FRAME),
    ]
    for label, node, items in negatives:
        h, _b, _bs = and_eval(common, node, items)
        if h:
            msgs.append(f"{label} 误命中 {node} —— 与门 / ROI 过宽（应只认完整弹窗 / 确认框）")

    # 只有弹窗正文、没有星导石行 -> 第一步不命中（与门承重，不是「见弹窗就点」）。
    popup_no_stone = [it for it in POPUP_FRAME if "星导石" not in it[0]]
    h, _b, _bs = and_eval(common, S.NODE_USE_STONE, popup_no_stone)
    if h:
        msgs.append("只有弹窗正文、没有星导石行 误命中第一步 —— 与门不承重")
    return msgs


def probe_stamina_real_frame() -> bool:
    return frame_failures(load_common()) == []


# ---------------------------------------------------------------------------
# 守卫 5：纯编辑 —— 承重短语仍在（special_dungeon.json 被改动，五条注释一条都不能丢）
# ---------------------------------------------------------------------------
def declaration_failures(sd_text: str | None = None) -> list[str]:
    text = _sd_text() if sd_text is None else sd_text
    msgs: list[str] = []
    for phrase in BEARING_PHRASES:
        if text.count(phrase) < 1:
            msgs.append(f"承重短语「{phrase}」丢失（#12 硬规则：纯编辑不得丢注释）")
    return msgs


def probe_stamina_declared() -> bool:
    return declaration_failures() == []


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def all_failures(*, common=None, root: Path | None = None) -> list[str]:
    common = load_common(root) if common is None else common
    return (
        node_failures(common)
        + wiring_failures(root)
        + policy_failures(root)
        + frame_failures(common)
        + declaration_failures(_sd_text(root) if root is not None else None)
    )


# ---------------------------------------------------------------------------
# 探针（供 test_offline_contract 自动聚合）
# ---------------------------------------------------------------------------
# （探针函数即上面的 probe_stamina_* ；此处不再另设别名。）


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_stamina.py`）
# ---------------------------------------------------------------------------
def _red(check, *args) -> tuple[bool, str]:
    msgs = check(*args)
    return bool(msgs), (msgs[0] if msgs else "（守卫没抓到！）")


def prove_red() -> bool:
    from scene import stamina as S  # noqa: PLC0415

    print("hooks_stamina prove-red：七处破坏，要求守卫各自变红")
    common = load_common()
    green = (
        probe_stamina_nodes_declared() is True
        and probe_stamina_wired_every_consumer() is True
        and probe_stamina_stone_only_policy() is True
        and probe_stamina_real_frame() is True
        and probe_stamina_declared() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：声明 + 接线 + 策略 + 真机帧 + 承重短语（绿）")
    if not green:
        return False

    # (a) 从 AbyssEntry.next 摘掉恢复引用 -> 该场景又『无人处理』。
    red_a = red_b = red_c = red_d = False
    tail_a = tail_b = tail_c = tail_d = ""
    # wiring_failures 从磁盘读 —— 用临时副本承载「摘掉引用」的产物。
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="wf_stamina_"))
    try:
        shutil.copytree(PIPE_DIR, root / "assets" / "resource" / "pipeline")
        data = load_chain("abyss.json", root)
        nxt = data["AbyssEntry"]["next"]
        for r in list(S.recovery_refs()):
            if r in nxt:
                nxt.remove(r)
        (root / "assets" / "resource" / "pipeline" / "abyss.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8"
        )
        red_a, tail_a = _red(wiring_failures, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 从 FLOW_EXCEPTIONS 摘掉恢复引用 -> 每个五重流程节点都丢（守卫 2 红）。
    from scene import wuchong as W  # noqa: PLC0415

    saved_wc = W.FLOW_EXCEPTIONS
    try:
        W.FLOW_EXCEPTIONS = tuple(x for x in saved_wc if x not in S.recovery_refs())
        red_b, tail_b = _red(wiring_failures)
    finally:
        W.FLOW_EXCEPTIONS = saved_wc

    # (c) 动作换成固定死点 -> 守卫 1 红（不许死偏移）。
    broken = copy.deepcopy(common)
    broken[S.NODE_USE_STONE]["action"]["param"]["target"] = [289, 950]
    red_c, tail_c = _red(node_failures, broken)

    # (d) box_index 改成 0 -> 真机帧守卫红（点到弹窗正文框 / 确认框标题框）。
    broken2 = copy.deepcopy(common)
    broken2[S.NODE_USE_STONE]["recognition"]["param"]["box_index"] = 0
    red_d, tail_d = _red(frame_failures, broken2)

    # (e) 去掉星导石行的 ROI -> 守卫 1 红（判据与 scene.stamina 的 ROI 不同步）。
    red_e = False
    tail_e = ""
    broken3 = copy.deepcopy(common)
    broken3[S.NODE_STONE]["recognition"]["param"].pop("roi", None)
    red_e, tail_e = _red(node_failures, broken3)

    # (f) ★#102 ③★ 把模板优先项挪到 OCR 版**之后**（模板通道永远轮不到）-> 守卫 3 红。
    red_f = False
    tail_f = ""
    tpl_ref = f"[JumpBack]{S.NODE_STONE_TPL}"
    ocr_ref = f"[JumpBack]{S.NODE_USE_STONE}"
    root_f = Path(tempfile.mkdtemp(prefix="wf_stamina_order_"))
    try:
        shutil.copytree(PIPE_DIR, root_f / "assets" / "resource" / "pipeline")
        data = load_chain("special_dungeon.json", root_f)
        nxt = data["SpecialEntry"]["next"]
        nxt.remove(tpl_ref)
        nxt.insert(nxt.index(ocr_ref) + 1, tpl_ref)
        (root_f / "assets" / "resource" / "pipeline" / "special_dungeon.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8"
        )
        red_f, tail_f = _red(policy_failures, root_f)
    finally:
        shutil.rmtree(root_f, ignore_errors=True)

    # (g) ★#102 ①★ 把声明顺序里的两条通道对调（真源与守卫的 pin 不符）-> 守卫 3 红。
    red_g = False
    tail_g = ""
    saved_steps = S.RECOVERY_STEPS
    try:
        S.RECOVERY_STEPS = (S.NODE_USE_STONE, S.NODE_STONE_TPL) + tuple(saved_steps[2:])
        red_g, tail_g = _red(policy_failures)
    finally:
        S.RECOVERY_STEPS = saved_steps

    for label, red, tail in (
        ("从 AbyssEntry.next 摘掉恢复引用（深渊又无人处理）", red_a, tail_a),
        ("从 FLOW_EXCEPTIONS 摘掉恢复引用（五个五重流程节点全丢）", red_b, tail_b),
        ("动作改成固定死点", red_c, tail_c),
        ("box_index 改成 0（点错框）", red_d, tail_d),
        ("去掉星导石行 ROI（判据/ROI 不同步）", red_e, tail_e),
        ("把模板优先项挪到 OCR 版之后（模板通道永远轮不到）", red_f, tail_f),
        ("把 RECOVERY_STEPS 的两条通道对调（声明顺序不符）", red_g, tail_g),
    ):
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}  {tail}")

    ok = green and red_a and red_b and red_c and red_d and red_e and red_f and red_g
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "stamina-nodes-declared",
        "#68",
        "九个公共节点 PubStamina*（含第三态结果窗三叶/动作）在场、判据与 scene.stamina 一致、And+box_index=1、Click target:true 零偏移",
        probe_stamina_nodes_declared,
    ),
    (
        "stamina-wired-every-consumer",
        "#68",
        "②每个消耗体力的场景（五重/战阵之宴/领主战族/深渊/主线/外传×2）的枢纽 next 都含 recovery_refs() "
        "的**全部**项（缺一个 = 那一步处理不了体力弹窗），引用节点确有定义；五重经 FLOW_EXCEPTIONS → "
        "中继 WuchongGuardChain 注入每个流程节点",
        probe_stamina_wired_every_consumer,
    ),
    (
        "stamina-stone-only-policy",
        "#68",
        "①recovery_refs() 的项目集合与顺序 == scene.stamina.RECOVERY_STEPS（模板优先行 → OCR 兜底行 → "
        "确认框 OK → 结果窗 OK）；③模板优先项排在 OCR 版之前（每个消费链枢纽 + 五重中继）；"
        "策略只用星岛石（RECOVER_WITH_STONE）；无第二份免费道具路径；容忍 星导石/星岛石；【取消】绝不点",
        probe_stamina_stone_only_policy,
    ),
    (
        "stamina-real-frame",
        "#68",
        "真机帧回放：弹窗帧点星导石行框中心 (289,950)、确认帧点 OK 框中心 (522,823)；准备页/缺叶/跨步都不命中",
        probe_stamina_real_frame,
    ),
    (
        "stamina-declared",
        "#68",
        "承重短语零丢失（special_dungeon.json 纯编辑）—— 五条各 ≥1",
        probe_stamina_declared,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
