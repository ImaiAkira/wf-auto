# -*- coding: utf-8 -*-
"""#110：「挑战」按钮的**点击判据**收成一处真源（+ 兼容真机的箭头渲染）。

## 事实（真机帧 / 识别调研）
- 编队页底部【挑战】按钮有**两种渲染**：``挑战`` 与 ``挑战→``（带箭头）。
  识别调研（``docs/research/recognition-ocr-vs-template.md`` §1.2 例 1 / §1.3「两态」）
  统计 **8/17 帧**带箭头，且两种读法**各自像素稳定**（score 1.000 / 0.962 一字不差）
  ⇒ 这不是随机抖动，是两个稳定的视觉状态。
- 整串 ``^挑战$`` **不匹配** ``挑战→`` ⇒ 用它时约**一半的帧上点击判据不成立**
  （#109 修的是**页面**判据，本票修的是**点击**判据 —— 两件事，别混）。
- 点击判据原先**散在 7 处**、各写 ``^挑战$``：单人编队页 5 处 ——
  ``common.json::PubChallenge``、``wuchong.json::WuchongChallengeText`` /
  ``WuchongTeamChallenge``、``phantom.json::PhantomSoloChallenge``、
  ``abyss.json::AbyssSoloChallenge``；共斗房 2 处 ——
  ``wuchong.json::WuchongCoopChallenge``、``phantom.json::PhantomCoopChallenge``
  （字段有两种：OCR 的 ``recognition.param.expected`` 与自定义动作的
  ``custom_action_param.what`` —— 语义都是「点哪颗按钮」）。
  ★共斗房那两处凭什么算「本按钮」★：识别调研里带箭头样本的框 ``[297,905,156,47]`` 与
  共斗房「挑战」的 ``[297,906,81,46]`` **同高** ⇒ 箭头症状的现场很可能就是它；而五重多人
  （运维主用模式）开战走的正是 ``WuchongCoopChallenge`` —— 漏了它多人永远开不了战。

## 真源 / 派生（别猜）
- **真源 = ``scene/challenge.py``**（纯 Python 常量，人可读、可 import）。
- ``assets/resource/pipeline/*.json`` **不是**生成物（ADR-0001：pipeline 不被清空、也不被
  整体生成），所以 JSON 里的落地形式就是**同一个字面量** ``^挑战(→)?$``；
  ``scene/challenge.CLICK_CRITERIA`` 是那几处的机器可读清单。
- ★**agent 侧是逐字快照，不是 import**★：``agent/side_impl.py::_PUBCHALLENGE_ORIGINAL``
  在运行期用 ``pipeline_override`` 把 ``PubChallenge`` 收窄（phantom）/ 还原（其余种类），
  而 ``agent/`` 是**安装态的独立目录（没有 ``scene/``）** ⇒ 只能存快照，
  由本守卫钉「快照 == 真源」。★不同步它 = 修了 common.json 也在运行期被改回旧形状★。

## 契约
- **T1 单源形状**：上面 7 处**逐字**等于 ``scene.challenge.CHALLENGE_CLICK_PATTERNS``
  （列表逐项相等；不做语义等价 —— 「差不多」正是漂移的起点）。
- **T2 ratchet（只准多出同形，不准多出别的）**：仓里任何**活跃**的 ``expected`` / ``what``
  判据串，凡是**会命中「挑战」/「挑战→」这段文字**的（= 认的就是这颗按钮），必须是真源形状，
  或者登记在 :data:`OUT_OF_SCOPE_PENDING` 里（点名文件 + 节点 + 字段 + 理由）。
  新冒出来的没登记 → 红并**列出文件+节点**。
  ★为什么不是「凡含『挑战』二字就红」★：``再次挑战`` / ``继续挑战`` /
  ``挑战深渊连战EX`` / ``连续挑战次数`` 也含「挑战」，但它们是**别的控件**的正向判据 ——
  把它们判红等于逼人去改错的东西。判据用「会不会命中『挑战』这两字」而不是「含不含这两个字」；
  再用**肯定反例**（也命中同屏的『返回』/『再次挑战』= 通配抓字，例如 ``OcrTask`` 的 ``.*``）
  把「抓全屏文本框」的通用 OCR 入口排除在外（见 :func:`_is_universal`）。
- **T3 放宽封顶**：``再次挑战 / 继续挑战 / 挑战深渊连战 / 挑战深渊连战EX / 挑战→→ / →挑战``
  一个都不许被真源形状命中；而旧形状 ``^挑战$`` 必须**仍漏** ``挑战→``（本票的存在理由）。
- **T4 运行期 override 同步**：``agent/side_impl`` 的快照 == 真源，且收窄/还原**两种形态**
  都不得把判据改回 ``^挑战$``（否则设备上生效的还是旧形状）。
- **T5 两种渲染都点得中**：``挑战`` / ``挑战→`` 两种读法都能被 7 处判据定位到那颗按钮
  （按各自字段的语义离线求值：OCR 用 roi 面积可见率，``what`` 用 roi 中心判定）。

破坏实验（``python tools\\contract_hooks\\hooks_110.py``）在**临时副本**上做，绝不改真文件。
"""

from __future__ import annotations

import importlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_REL = Path("assets") / "resource" / "pipeline"
AGENT_DIR = REPO_ROOT / "agent"

#: 真机「挑战」按钮的两种读法（受本守卫管辖的判据必须命中这两段文字）。
RENDERINGS: tuple[str, ...] = ("挑战", "挑战→")

#: 「这不是本按钮的判据」的**肯定反例**：同屏别的控件 / 别的正向判据的文字。
#: 一条判据若连这些都命中，说明它是**通配抓字**（如 ``common.json::OcrTask`` 的 ``.*``
#: = 「把整屏文本框都取回来」的通用节点），不是「点这颗按钮」的判据 —— 见 :func:`_is_universal`。
GENERIC_PROBES: tuple[str, ...] = ("返回", "再次挑战")

#: 真机 720 空间的**读法框**，按页面分两份 —— 同名的两颗「挑战」在屏幕上**不同位置**：
#: * ``solo_team``：单人编队页底部（#30 已入库的真机帧 ``SOLO_TEAM_ITEMS``，y≈1069）；
#:   箭头版把框向右放宽 40px（箭头在标签右侧）。
#: * ``coop_room``：共斗房间里那颗（#30 的 ``ROOM_ITEMS``，y≈906）；带箭头的样本就是识别调研
#:   §1.2 例 1 的 ``box=[297,905,156,47]`` —— 两种读法都在同一段长跑里出现过。
PAGE_READING_BOXES: dict[str, dict[str, list[int]]] = {
    "solo_team": {
        "挑战": [297, 1069, 80, 47],
        "挑战→": [297, 1069, 120, 47],
    },
    "coop_room": {
        "挑战": [297, 906, 81, 46],
        "挑战→": [297, 905, 156, 47],
    },
}

#: 「裁剪保读率」阈值（与 ``hooks_37.VISIBLE_MIN`` / ``hooks_109.VISIBLE_MIN`` 同值）。
VISIBLE_MIN = 0.7

#: ★本票不改、但同样承载「点挑战」的活跃旧判据 —— 逐条登记角色（子集门禁：新出现的没登记就红；
#: 哪天它们被改成同形，登记项会**主动报错**要求删掉，不留影子真源）。
#:
#: 目前**为空**：本票把共斗房那两处（``WuchongCoopChallenge`` / ``PhantomCoopChallenge``）
#: 也一并改成了真源形状 —— 识别调研里带箭头样本的框 ``[297,905,156,47]`` 与共斗房「挑战」的
#: ``[297,906,81,46]`` 同高，箭头症状的现场就是它，而五重多人（运维主用模式）开战走的正是
#: ``WuchongCoopChallenge``。⇒ **仓里所有「点挑战」的判据现在都是同一份形状**。
OUT_OF_SCOPE_PENDING: dict[tuple[str, str, str], str] = {}

#: 旧形状 ``^挑战$``（**运行时拼出来**，不写成字面量）：本守卫必须**点名**这条被废除的形状
#: （反例 / 破坏实验 / 报错文案都要说清「别写回它」），但 ``hooks_109`` 的「仓里不许有活跃
#: ``^挑战$``」ratchet 会把字面量算作一次「使用」—— 与 ``hooks_109.BLIND`` 同一手法：
#: 「点名一条被禁的模式」与「使用它」在纯文本扫描里必然长得一样，故拼出来。
_OLD_SHAPE = "^挑战" + "$"

#: 只扫 pipeline 的 JSON（判据都落在这里；agent 侧的逐字快照由 T4 单独钉）。
_PIPELINE_SUFFIX = ".json"

#: 判据字段 → 取值的路径（``recognition.param.expected`` / ``custom_action_param.what``）。
_FIELD_KEYS = ("expected", "what")


# ---------------------------------------------------------------------------
# 路径 / 惰性导入（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for p in (str(REPO_ROOT), str(REPO_ROOT / "tools"), str(AGENT_DIR)):
        if p not in sys.path:
            sys.path.append(p)


def _module(name: str):
    """取 ``scene.<name>`` **子模块**（别用 ``from scene import <name>``：``scene/__init__``
    把同名函数导出到了包上，属性会被遮蔽成函数，拿不到模块）。"""
    _paths()
    return importlib.import_module(f"scene.{name}")


def _challenge():
    return _module("challenge")


def _drift():
    return _module("drift")


def _side_impl():
    _paths()
    import side_impl  # noqa: PLC0415

    return side_impl


# ---------------------------------------------------------------------------
# pipeline 读取 / 判据定位
# ---------------------------------------------------------------------------
def _pipeline_files(root: Path | None = None) -> dict[str, dict]:
    base = (Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL
    return _drift().load_pipelines(base)


def _criterion_value(node: dict, field: str):
    """从节点里取某字段的判据列表（取不到返回 ``None``，绝不臆造空列表）。"""
    if not isinstance(node, dict):
        return None
    if field == "expected":
        rec = node.get("recognition")
        if not isinstance(rec, dict):
            return None
        param = rec.get("param")
        if not isinstance(param, dict):
            return None
        return param.get("expected")
    if field == "what":
        action = node.get("action")
        if not isinstance(action, dict):
            return None
        param = action.get("param")
        if not isinstance(param, dict):
            return None
        cap = param.get("custom_action_param")
        if not isinstance(cap, dict):
            return None
        return cap.get("what")
    raise ValueError(f"未知判据字段：{field!r}（只支持 {_FIELD_KEYS}）")


def _roi_of(node: dict, field: str):
    """某字段判据的 roi（两种字段的 roi **语义不同**，见 :func:`_click_hit`）。"""
    if field == "expected":
        return ((node.get("recognition") or {}).get("param") or {}).get("roi")
    param = (node.get("action") or {}).get("param") or {}
    cap = param.get("custom_action_param") or {}
    return cap.get("roi") if isinstance(cap, dict) else None


# ---------------------------------------------------------------------------
# 离线点击求值：判据能否定位到 (text, box) 那颗按钮
# ---------------------------------------------------------------------------
def _visible_fraction(box, roi) -> float:
    """框落在 OCR roi（``[x,y,w,h]``）内的**面积占比**（真机 MAA 先裁剪再 OCR）。"""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    ix0, iy0 = max(x, roi[0]), max(y, roi[1])
    ix1, iy1 = min(x + w, roi[0] + roi[2]), min(y + h, roi[1] + roi[3])
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    return (iw * ih) / float(w * h)


def _click_hit(node: dict, field: str, text: str, box) -> bool:
    """把一条判据喂给真机 ``(text, box)``，判断它会不会点这颗按钮。

    * ``expected``（MAA OCR）：``re.search`` + roi ``[x,y,w,h]`` 的**面积可见率**；
    * ``what``（自定义动作挑按钮）：``re.search`` + roi ``[x0,y0,x1,y1]`` 的**中心**判定
      （与 ``abyss_impl._pick`` / ``wuchong_impl.locate_button`` / ``phantom_impl._pick`` 同口径）。
    """
    pats = _criterion_value(node, field)
    if not isinstance(pats, list):
        return False
    roi = _roi_of(node, field)
    if field == "expected":
        if not any(re.search(p, (text or "").strip()) for p in pats):
            return False
        return True if roi is None else _visible_fraction(box, roi) >= VISIBLE_MIN
    cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
    for p in pats:
        if not re.search(p, text or ""):
            continue
        if roi is None:
            return True
        if roi[0] <= cx <= roi[2] and roi[1] <= cy <= roi[3]:
            return True
    return False


# ---------------------------------------------------------------------------
# T1：7 处点击判据逐字等于真源
# ---------------------------------------------------------------------------
def _single_source_failures(root: Path | None = None) -> list[str]:
    ch = _challenge()
    files = _pipeline_files(root)
    msgs: list[str] = []
    want = list(ch.CHALLENGE_CLICK_PATTERNS)

    for crit in ch.CLICK_CRITERIA:
        data = files.get(crit.file)
        if not isinstance(data, dict):
            msgs.append(f"点击判据真源清单登记了 {crit.path()}，但文件 {crit.file} 不存在")
            continue
        node = data.get(crit.node)
        if not isinstance(node, dict):
            msgs.append(
                f"点击判据真源清单登记了 {crit.path()}，但该节点不存在"
                f"（节点被删/改名 ⇒ 真源与 pipeline 脱节）"
            )
            continue
        got = _criterion_value(node, crit.field)
        if got != want:
            msgs.append(
                f"{crit.path()}.{crit.field} = {got!r}，应为真源 "
                f"scene.challenge.CHALLENGE_CLICK_PATTERNS = {want!r}"
                f"（整串锚定 + 至多一个箭头；改判据先改真源，再逐字同步到 JSON）"
            )
    return msgs


def probe_challenge_click_single_source() -> bool:
    """T1：7 处点击判据（PubChallenge / WuchongChallengeText / WuchongTeamChallenge /
    WuchongCoopChallenge / PhantomSoloChallenge / PhantomCoopChallenge / AbyssSoloChallenge）
    逐字等于 ``scene.challenge`` 的真源形状。"""
    return _single_source_failures() == []


# ---------------------------------------------------------------------------
# T2：ratchet —— 仓里任何「会认这颗按钮」的活跃判据都必须是真源形状
# ---------------------------------------------------------------------------
def _iter_criteria(obj, path: str = ""):
    """递归产出 ``(字段, 判据串, 取值路径)`` —— 覆盖嵌套的 inline 识别/动作。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else key
            if key in _FIELD_KEYS and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        yield key, item, f"{here}[{i}]"
            else:
                yield from _iter_criteria(value, here)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _iter_criteria(value, f"{path}[{i}]")


def _is_this_button(pattern: str) -> bool:
    """这条判据会不会命中「挑战」/「挑战→」这两段文字（= 认的就是这颗按钮）。

    正则写坏了（编译失败）→ 也算受管辖（它是活跃判据，必须被看见）。
    """
    try:
        compiled = re.compile(pattern)
    except re.error:
        return "挑战" in pattern
    return any(compiled.search(t) for t in RENDERINGS)


def _is_universal(pattern: str) -> bool:
    """这条判据是不是**通配抓字**（连别的控件文字都命中）—— 那它不是「点挑战」的判据。

    存在的理由：``common.json::OcrTask`` 的 ``expected: [".*"]`` 是「把整屏文本框都取回来」
    的通用 OCR 入口（agent 侧 ``run_recognition`` 用它取图），``.*`` 当然也命中「挑战」，
    但它认的不是这颗按钮。用**肯定反例**（同屏别的控件 / 别的正向判据）把通配排除掉，
    比维护一份「哪些节点不算」的黑名单诚实（黑名单会随新增节点腐烂）。
    """
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    return any(compiled.search(t) for t in GENERIC_PROBES)


def _ratchet_failures(root: Path | None = None) -> list[str]:
    ch = _challenge()
    base = (Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL
    want = ch.CHALLENGE_CLICK_PATTERN
    msgs: list[str] = []

    for path in sorted(base.glob("*" + _PIPELINE_SUFFIX)):
        rel = path.name
        try:
            data = _drift()._load_jsonc(path)
        except (OSError, ValueError) as exc:
            msgs.append(f"{rel} 解析失败，无法审计「挑战」点击判据：{exc}")
            continue
        if not isinstance(data, dict):
            continue
        for node_name, node in data.items():
            if not isinstance(node, dict):
                continue
            for field, pattern, where in _iter_criteria(node):
                if not _is_this_button(pattern):
                    continue
                if pattern == want:
                    continue
                if _is_universal(pattern):
                    # 通配抓字（例如 OcrTask 的 ``.*``）不是「点这颗按钮」的判据。
                    continue
                key = (rel, node_name, field)
                if key in OUT_OF_SCOPE_PENDING:
                    continue
                hint = ""
                if pattern == _OLD_SHAPE:
                    hint = "（旧形状：整串锚定但**漏掉带箭头的『挑战→』**，约一半帧上点不中）"
                msgs.append(
                    f"{rel}::{node_name}.{field}（{where}）的判据 {pattern!r} 会命中『挑战』这段文字，"
                    f"但不是真源形状 {want!r}{hint} —— 点击判据只准这一个形状"
                    f"（真源 scene/challenge.py；若是别的控件请改成不命中『挑战』的正向判据）"
                )

    # 登记项必须仍然「指得到东西」：节点/字段没了还留着登记 = 影子真源（会掩盖新漂移）。
    for (fname, node_name, field), _reason in OUT_OF_SCOPE_PENDING.items():
        try:
            data = _drift()._load_jsonc(base / fname)
        except (OSError, ValueError):
            continue
        node = data.get(node_name) if isinstance(data, dict) else None
        value = _criterion_value(node, field)
        if value == list(ch.CHALLENGE_CLICK_PATTERNS):
            msgs.append(
                f"OUT_OF_SCOPE_PENDING 里 {(fname, node_name, field)} 已经改成真源形状了 —— "
                f"把它从登记表删掉（过期的 pending 会让人以为还有债）"
            )
    return msgs


def probe_challenge_click_ratchet() -> bool:
    """T2：仓里任何「会认这颗按钮」的活跃判据都是真源形状（或逐条登记过角色）。"""
    return _ratchet_failures() == []


# ---------------------------------------------------------------------------
# T3：放宽封顶 —— 反例一个都不许中；旧形状必须仍漏箭头
# ---------------------------------------------------------------------------
def _anchoring_failures() -> list[str]:
    ch = _challenge()
    msgs: list[str] = []
    for text in ch.REJECTED_TEXTS:
        if ch.matches(text):
            msgs.append(
                f"真源形状 {ch.CHALLENGE_CLICK_PATTERN!r} 命中了反例『{text}』"
                f"（整串锚定被破坏 / 箭头被放成 `(→)*` 或 `.*`）"
            )
    for text in RENDERINGS:
        if not ch.matches(text):
            msgs.append(f"真源形状漏了『{text}』（本票要修的正是这颗按钮的两种渲染）")
    # 旧形状必须**仍**漏箭头：否则「本票到底修了什么」就无法自证（守卫会变成恒绿）。
    if re.search(_OLD_SHAPE, "挑战→"):
        msgs.append(f"旧形状 {_OLD_SHAPE!r} 竟然命中『挑战→』—— 本票的前提不成立（真机证据需重核）")
    return msgs


def probe_challenge_click_anchored() -> bool:
    """T3：反例（再次挑战/继续挑战/挑战深渊连战EX/挑战→→/→挑战…）一个都不中。"""
    return _anchoring_failures() == []


# ---------------------------------------------------------------------------
# T4：运行期 override（agent/side_impl.py 的快照）必须与真源同形
# ---------------------------------------------------------------------------
def _override_failures() -> list[str]:
    ch = _challenge()
    si = _side_impl()
    want = list(ch.CHALLENGE_CLICK_PATTERNS)
    msgs: list[str] = []

    snapshot = list(getattr(si, "_PUBCHALLENGE_PATTERNS", []) or [])
    if snapshot != want:
        msgs.append(
            f"agent/side_impl._PUBCHALLENGE_PATTERNS = {snapshot!r} 与真源 {want!r} 不一致"
            f"（安装态没有 scene/，这里是**逐字快照**；不同步 = 运行期 pipeline_override "
            f"会把 PubChallenge 改回旧形状，修了 common.json 也白修）"
        )

    for kind in ("phantom", "special", "farm", "raid"):
        ov = si.pubchallenge_override_for(kind) or {}
        node = ov.get("PubChallenge") or {}
        got = ((node.get("recognition") or {}).get("param") or {}).get("expected")
        if got != want:
            msgs.append(
                f"agent/side_impl.pubchallenge_override_for({kind!r}) 的 PubChallenge.expected "
                f"= {got!r}，运行时会把判据改成它（应为真源 {want!r}）"
            )
        if got is not None and _OLD_SHAPE in got:
            msgs.append(
                f"agent/side_impl.pubchallenge_override_for({kind!r}) 仍把它改回 {_OLD_SHAPE!r}"
                f"（#110 的★坑★：这一处不同步，设备上生效的就还是旧形状）"
            )
    return msgs


def probe_challenge_click_runtime_override() -> bool:
    """T4：agent/side_impl 的运行期 override 快照 == 真源，收窄/还原两种形态都不回 ``^挑战$``。"""
    return _override_failures() == []


# ---------------------------------------------------------------------------
# T5：两种渲染都能被 7 处判据点到那颗按钮
# ---------------------------------------------------------------------------
def _both_renderings_failures(root: Path | None = None) -> list[str]:
    ch = _challenge()
    files = _pipeline_files(root)
    msgs: list[str] = []
    for crit in ch.CLICK_CRITERIA:
        node = (files.get(crit.file) or {}).get(crit.node)
        if not isinstance(node, dict):
            msgs.append(f"{crit.path()} 不存在，无法验证两种渲染（节点被删/改名）")
            continue
        boxes = PAGE_READING_BOXES.get(crit.page)
        if boxes is None:
            msgs.append(
                f"{crit.path()} 的 page={crit.page!r} 没在 PAGE_READING_BOXES 里登记"
                f"（新增落点必须说明它在哪个页面、用哪份真机框求值）"
            )
            continue
        for text in RENDERINGS:
            box = list(boxes[text])
            if not _click_hit(node, crit.field, text, box):
                msgs.append(
                    f"{crit.path()}.{crit.field} 点不中『{text}』"
                    f"（page={crit.page} box={box} roi={_roi_of(node, crit.field)!r}）—— "
                    f"带箭头的那一半帧会漏点"
                )
    return msgs


def probe_challenge_click_both_renderings() -> bool:
    """T5：``挑战`` / ``挑战→`` 两种渲染都能被 7 处判据定位到（roi 语义按字段区分）。"""
    return _both_renderings_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        "challenge-click-single-source",
        "#110",
        "7 处「挑战」点击判据（PubChallenge / WuchongChallengeText / WuchongTeamChallenge / "
        "WuchongCoopChallenge / PhantomSoloChallenge / PhantomCoopChallenge / AbyssSoloChallenge）"
        "逐字等于真源 scene.challenge",
        probe_challenge_click_single_source,
    ),
    (
        "challenge-click-ratchet",
        "#110",
        "ratchet：仓里任何会命中『挑战』文字的活跃 expected/what 都必须是真源形状"
        "（或逐条登记过角色），新增/回退即红并点名文件+节点",
        probe_challenge_click_ratchet,
    ),
    (
        "challenge-click-anchored",
        "#110",
        "放宽封顶：再次挑战/继续挑战/挑战深渊连战EX/挑战→→/→挑战 一个都不中；"
        f"旧形状 {_OLD_SHAPE!r} 仍漏『挑战→』",
        probe_challenge_click_anchored,
    ),
    (
        "challenge-click-runtime-override",
        "#110",
        "agent/side_impl 的运行期 pipeline_override 快照 == 真源"
        f"（收窄/还原都不许改回 {_OLD_SHAPE!r}）",
        probe_challenge_click_runtime_override,
    ),
    (
        "challenge-click-both-renderings",
        "#110",
        "两种渲染（挑战 / 挑战→）都能被 7 处判据点中那颗按钮（OCR 走 roi 面积、what 走 roi 中心）",
        probe_challenge_click_both_renderings,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（≥3；本票做了 4 条，全部在临时副本 / 模块内存上做）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook110_"))
    (root / PIPELINE_REL).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / PIPELINE_REL, root / PIPELINE_REL)
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def prove_red() -> bool:
    ch = _challenge()
    print("hooks_110 prove-red：四条破坏，要求守卫各自变红")
    green = (
        probe_challenge_click_single_source()
        and probe_challenge_click_ratchet()
        and probe_challenge_click_anchored()
        and probe_challenge_click_runtime_override()
        and probe_challenge_click_both_renderings()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：五个守卫全绿")
    if not green:
        for m in (
            _single_source_failures()
            + _ratchet_failures()
            + _anchoring_failures()
            + _override_failures()
            + _both_renderings_failures()
        ):
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    # ① 只把一处点击判据改回旧形状（= 只修了一半 / 有人手改回去）→ T1 + T2 红
    tmp = _temp_pipeline()
    try:
        target = tmp / PIPELINE_REL / "common.json"
        _sub(
            target,
            '"expected": ["^挑战(→)?$"]',
            '"expected": ["' + _OLD_SHAPE + '"]',
        )
        m = _single_source_failures(tmp) + _ratchet_failures(tmp)
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 common.json::PubChallenge 改回 {_OLD_SHAPE!r}"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ② 把一处放宽成裸「挑战」（整串锚定被破坏）→ T1 + T2 红，反例也会中
    tmp = _temp_pipeline()
    try:
        target = tmp / PIPELINE_REL / "abyss.json"
        _sub(target, '"what": ["^挑战(→)?$"]', '"what": ["挑战"]')
        m = _single_source_failures(tmp) + _ratchet_failures(tmp)
        bare_hits = [t for t in ch.REJECTED_TEXTS if re.search("挑战", t)]
        red = len(m) > 0 and bool(bare_hits)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 abyss.json::AbyssSoloChallenge 放宽成裸「挑战」"
            f" -> {'红' if red else '仍绿'}"
            + (f"  {m[0]}" if m else "")
            + (f"（裸形状还会命中 {len(bare_hits)} 个反例）" if bare_hits else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ③ 去掉 agent 侧同步（快照改回旧形状）→ T4 红
    si = _side_impl()
    real_patterns = getattr(si, "_PUBCHALLENGE_PATTERNS", None)
    real_original = getattr(si, "_PUBCHALLENGE_ORIGINAL", None)
    try:
        si._PUBCHALLENGE_PATTERNS = [_OLD_SHAPE]
        si._PUBCHALLENGE_ORIGINAL = {"expected": [_OLD_SHAPE]}
        m = _override_failures()
        red = len(m) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] 把 agent/side_impl 的快照改回 {_OLD_SHAPE!r}（去掉同步）"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        si._PUBCHALLENGE_PATTERNS = real_patterns
        si._PUBCHALLENGE_ORIGINAL = real_original

    # ④ 在**别的节点**上写回旧形状（= 多出一处未登记的点击判据）→ T2 ratchet 红
    tmp = _temp_pipeline()
    try:
        target = tmp / PIPELINE_REL / "wuchong.json"
        _sub(target, '"what": ["^返回$"]', '"what": ["' + _OLD_SHAPE + '"]')
        m = _ratchet_failures(tmp)
        red = len(m) > 0 and any("WuchongStaleTeam" in x for x in m)
        print(
            f"  [{'PASS' if red else 'FAIL'}] 给 wuchong.json::WuchongStaleTeam 塞一个 {_OLD_SHAPE!r}"
            f"（多一处未登记的点挑战判据）"
            f" -> {'红' if red else '仍绿'}" + (f"  {m[0]}" if m else "")
        )
        checks.append(red)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
