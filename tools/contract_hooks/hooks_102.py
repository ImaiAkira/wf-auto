# -*- coding: utf-8 -*-
"""#102：模板识别 P0 三项（星导石行 / 是·否按钮 / NEW 徽标）—— 契约与假阳用例。

## 为什么这张票的门槛是「负例不假阳 + 滑窗 ZNCC 数字」

本仓出过两次**模板假阳**（``docs/research/recognition-ocr-vs-template.md`` §2.4）：
``auto/switch_label`` 在「自动续战」的**0.470** 位置被原生 ``TemplateMatch`` 选中、
``banner_abyss_ex`` 对纯深渊横幅假阳 **0.8708``。假阳比 OCR 误读**更难发现**（OCR 会打乱码，
假阳是静默点错）。所以每一项都必须：正例命中 ∧ 负例不假阳 ∧ 分数**存档** ∧ 与实测**一致**。

## 机制（协议语义，行号指本仓离线镜像 ``.research/3.1-pipeline.md``）

* ``TemplateMatch.threshold`` 是**入闸门**（「这个位置算不算命中」），**不是**「取最高分」。
* 多结果时选哪个由 ``order_by`` + ``index``；**默认 ``Horizontal`` + ``0`` = 最左**。
* ``roi`` 缺省 = 全屏（``[0,0,0,0]``）⇒ 候选池 = 整屏。
* ``Or.any_of`` = 「命中第一个即成功，后续不再识别」（``:858-860``）⇒ 顺序即优先级，
  :data:`scene.templates` 用它表达「模板优先、OCR 兜底」。

## 九个契约

* **C1 ``p0-roi-scoped``** —— 每个 P0 模板节点都必须有**收窄**的 roi，并且：
  ① 能**整窗**装下正例窗口（滑窗是逐位置的，装不下就永远命中不了）；
  ② **装不下同帧兄弟控件**（底框同款的另一个按钮 / 另一个徽标）—— 这才是把「否/是」分开的东西
     （两枚底框像素级同款：灰互评 **0.5840**，阈值挡不住）；
  ③ 不是全屏、w/h 不为 0（= 没有 roi）。
* **C2 ``p0-order-by-score``** —— 每个 P0 模板节点都**显式** ``order_by: "Score"``：要「最像」，
  绝不吃默认 ``Horizontal``（取最左）。
* **C3 ``p0-projection-synced``** —— ADR-0001：``scene/templates.py`` 是**真源**，pipeline 是
  手写投影；``template`` / ``threshold`` / ``roi`` / ``order_by`` 必须**逐项相等**。
  另外钉住**OCR 兜底仍在场且没被改坏**（``^否$`` / ``^是$`` / 星导石行名 + 原 roi）。
* **C4 ``p0-frame-no-false-positive``** —— 在**已入库真机帧**上按框架的做法跑**全滑窗 ZNCC**：
  正例帧 roi 内 ≥threshold 的候选**恰好 1 个**且落在正例窗口（±2px）；**跨帧正例**（未参与裁图的
  其它真机帧）在同一窗口仍 ≥ 阈值 + 0.05 且 argmax 不漂 —— 这一条专治「样本内 1.0000 自证」；
  负例帧 roi 内最高分 **< threshold**，且余量 ≥ :data:`NEGATIVE_MARGIN_MIN`。
* **C5 ``p0-archive-scores-match-measured``** —— 存档分数与实测一致（容差
  :data:`SCORE_TOL`）；含**roi 外的危险高分**（:attr:`TemplateSpec.global_watch`）与**同帧兄弟**
  的分数。帧 / 模板 / roi 一换，这条就红 —— 逼人重新标定，而不是把存档放烂。
* **C6 ``p0-template-pixels-from-evidence``** —— 模板是二进制资产、diff 看不见（RK4）⇒
  逐像素复核「模板 == 从正例帧按 ``window`` 重裁」。放进别的像素、或换了正例帧立刻红。
* **C7 ``p0-wiring-declared``** —— 接线现状与声明一致：``[JumpBack]PubStaminaUseStoneTpl`` 只出现在
  **声明过的**枢纽里（``scene.templates.STONE_TPL_WIRED_HUBS`` ∪ ``scene.stamina.STAMINA_CONSUMING_CHAINS``
  —— #102 起「哪些枢纽要恢复链」的唯一真源是后者，前者是本票**只读**的历史声明）；NEW 徽标已接线
  **1 处**（:data:`scene.templates.NEW_BADGE_WIRED` 为 True ⇔ ``SpecialNewBadge`` =
  ``Or([模板, OCR])``、模板被声明的 ``NEW_BADGE_NODES`` 引用），**声明几处就只许几处**。
  偷偷多接一处、偷偷断线、或声明仍写未接线都红。
* **C8 ``p0-stone-row-hubs``** —— ★本票「四个枢纽未接」那一条的验收★：``WuchongEntry`` /
  ``RaidDispatch`` / ``SpecialEntry`` / ``AbyssEntry``（以及 ``scene.stamina.STAMINA_CONSUMING_CHAINS``
  里的**每一个**枢纽）的 ``next`` 都必须挂**模板优先通道** ``[JumpBack]PubStaminaUseStoneTpl``
  ——它的判据就是双通道行 ``PubStaminaStoneRow``（``Or(图标模板, 行名 OCR)``）——且必须**排在**
  OCR 版 ``[JumpBack]PubStaminaUseStone`` **之前**：``next`` 是**有序候选**、先命中先执行，
  反了就 OCR 先吃掉该帧、模板通道永远轮不到（= 白接一条通道）。接线清单从
  ``scene.stamina.recovery_refs()`` 派生，这里的字面量只用来钉住「票面点名的四个枢纽一个都不能少」。
* **C9 ``p0-threshold-floor``** —— ★阈值不许低于门槛★：每个 P0 模板的 ``threshold`` 必须
  ≥ :data:`THRESHOLD_FLOOR`（**0.85** = 调研 §5.6 的硬下限 0.80 + 0.05 余量；三张裁片实测负例
  最高 0.7615 / 0.5609 / 0.2779，0.85 同时满足「≥0.80」与「≥负例 +0.05」）。把阈值调松到 0.4
  这类「省事」改动当场红 —— 本仓的 **0.470** 事故正是阈值语义被当成「调松更稳」来的。

## 本票**不改**、但必须点名

* ``PubStaminaStoneText`` / ``PubStaminaUseStone`` 的判据与 box 语义**一字未动** —— 它们被
  ``hooks_stamina.node_failures``（all_of 逐项）与 ``tools/verify_stamina_frames.py``（输出框
  == 真机行框 ``[209,873,160,32]``）钉死。所以模板通道走**新节点** + 候选顺序，而不是改它们。
* ``scene.stamina.STAMINA_NODES`` 追加了三个新节点名（``PubStaminaStoneIcon`` /
  ``PubStaminaStoneRow`` / ``PubStaminaUseStoneTpl``）：``hooks_stamina.stamina-stone-only-policy``
  要求任何 ``PubStamina*`` 节点都被该元组声明，否则视为「第二份免费恢复路径」。它们是同一条
  恢复链的**第二判据**，不是第二条路径。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
IMAGE_DIR = REPO_ROOT / "assets" / "resource" / "image"

#: 存档与实测的容差（票面要求 0.02）。浮点跨平台漂移远小于这个数。
SCORE_TOL = 0.02
#: 正例保守分下限（自裁模板自证 = 1.0000；0.99 只用来抓「模板换错 / 帧换了」）。
POSITIVE_MIN = 0.99
#: ★跨帧正例下限★：未参与裁图的真机帧不可能像自裁源那样 1.0000（截图时刻/渲染差异），
#: 但必须**高过阈值 0.05 以上**（= threshold + NEGATIVE_MARGIN_MIN，本票 = 0.90）。
CROSS_POSITIVE_MIN = 0.90
#: 负例余量下限（``threshold - 负例最高分``）：低于它 = 靠阈值擦屁股，不是靠 roi。
NEGATIVE_MARGIN_MIN = 0.05
#: ★P0 阈值门槛★：调研 §5.6 的硬下限 0.80 + 0.05 余量 = 0.85；低于它一律红（C9）。
THRESHOLD_FLOOR = 0.85
#: 正例窗口定位容差（滑窗是整数位置，允许 ±2px）。
WINDOW_TOL = 2
#: 「分数有意义」的门槛：低于它的区域整片平坦（方差 ≈ 0），argmax 在一堆并列 0.0000 里是谁
#: 纯属 numpy 实现细节 ⇒ 位置比对对它没有意义（会发生「分数一致但位置不同」的假红）。
FLAT_SCORE = 0.05


# ---------------------------------------------------------------------------
# 路径 / 惰性导入（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _submodule(name: str):
    """取 ``scene.<name>`` **子模块**（``scene/__init__`` 会把同名函数导出到包上，属性会被遮蔽）。"""
    _paths()
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"scene.{name}")


def _templates():
    return _submodule("templates")


def _drift():
    return _submodule("drift")


def _pixels():
    return _submodule("pixels")


def _pipelines(root: Path | None = None) -> dict[str, dict]:
    """``{文件名: 顶层对象}``（JSONC）。``root`` 指向临时副本时只影响 pipeline 的读取。"""
    drift = _drift()
    base = (Path(root) if root is not None else REPO_ROOT) / "assets" / "resource" / "pipeline"
    out: dict[str, dict] = {}
    for path in sorted(base.glob("*.json")):
        data = drift._load_jsonc(path)
        out[path.name] = data if isinstance(data, dict) else {}
    return out


def _nodes_by_name(root: Path | None = None) -> dict[str, dict]:
    """全仓 ``节点名 -> 节点``（节点名在 pipeline 里全局唯一）。"""
    out: dict[str, dict] = {}
    for data in _pipelines(root).values():
        for name, spec in data.items():
            if isinstance(spec, dict):
                out[name] = spec
    return out


def _rec(node: dict | None) -> dict:
    if not isinstance(node, dict):
        return {}
    rec = node.get("recognition")
    return rec if isinstance(rec, dict) else {}


def _param(node: dict | None) -> dict:
    param = _rec(node).get("param")
    return param if isinstance(param, dict) else {}


def _file_of(name: str, root: Path | None = None) -> str | None:
    """节点名所在的 pipeline 文件名（找不到返回 None；破坏实验与排障用）。"""
    for fname, data in _pipelines(root).items():
        if isinstance(data.get(name), dict):
            return fname
    return None


# ---------------------------------------------------------------------------
# P0 的「模板节点」清单：真源 scene/templates.py → (节点名, 模板键, 文件)
# ---------------------------------------------------------------------------
def template_nodes() -> list[tuple[str, str, str]]:
    """``[(pipeline 节点名, scene.templates 的模板键, pipeline 文件名), …]``。

    ★只列**已接线**的模板叶★：P0-3 的 NEW 徽标在 2026-10-19 已接线 1 处（小行徽标，
    ``special_dungeon.json::SpecialNewBadge``），参与 C1/C2 的节点扫描；大徽标 / 列表行两处
    仍是 OCR，不在本清单里（它们的模板尚未交付，见 ``scene/templates.py`` 的 P0-3 段）。
    """
    T = _templates()
    pairs = [
        (T.NODE_STONE_ICON, T.STONE_ICON.key, "common.json"),
        (T.NODE_BONUS_NO_TPL, T.BONUS_NO.key, "wuchong.json"),
        (T.NODE_BONUS_YES_TPL, T.BONUS_YES.key, "wuchong.json"),
    ]
    if T.NEW_BADGE_WIRED:
        pairs.extend(
            (name, T.NEW_BADGE.key, T.NEW_BADGE_NODE_FILE) for name in T.NEW_BADGE_NODES
        )
    return pairs


# ---------------------------------------------------------------------------
# C1：roi 必须收窄 —— 装得下正例窗口、装不下兄弟控件、不是全屏
# ---------------------------------------------------------------------------
def _roi_missing_reason(param: dict) -> str | None:
    """``None`` = 有**有效** roi；否则返回「为什么等于没有 roi」。"""
    path = _pixels()
    if "roi" not in param:
        return "没有 roi（协议缺省 [0,0,0,0] = 全屏，候选池 = 整屏）"
    roi = param.get("roi")
    if isinstance(roi, str):
        return f"roi 是节点/锚点引用（{roi!r}）—— 本节点是被引用的叶子，没有可解析的前置锚点"
    if (
        not isinstance(roi, (list, tuple))
        or len(roi) != 4
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in roi)
    ):
        return f"roi 不是四个整数：[x, y, w, h]，实际 {roi!r}"
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        return f"roi {list(roi)} 的 w/h ≤ 0（协议里 0 = 延伸到边缘 = 全屏）"
    if x <= 0 and y <= 0 and x + w >= path.BASE_W and y + h >= path.BASE_H:
        return f"roi {list(roi)} 等于全屏 {path.BASE_W}x{path.BASE_H}（等于没写）"
    return None


def _roi_scoped_failures(root: Path | None = None) -> list[str]:
    T = _templates()
    path = _pixels()
    nodes = _nodes_by_name(root)
    msgs: list[str] = []
    # 0) ``scene/templates`` 为了不 import pixels 抄了一份 720 别名 —— 抄的那份就要被钉住，
    #    否则它会在没人看的地方悄悄漂（本仓 #99 的教训：坐标空间没钉住就错两次）。
    if (T.BASE_W, T.BASE_H) != (path.BASE_W, path.BASE_H):
        msgs.append(
            f"scene/templates 的 BASE={T.BASE_W}x{T.BASE_H} != scene.pixels 的识别空间 "
            f"{path.BASE_W}x{path.BASE_H}（720 基准空间由框架决定，不可改）"
        )
    for node_name, key, fname in template_nodes():
        spec = T.TEMPLATES[key]
        where = f"{fname}::{node_name}（{key}）"
        node = nodes.get(node_name)
        if node is None:
            msgs.append(f"{where} 在 pipeline 里**不存在**（模板节点被删/改名 → 整条模板通道静默失效）")
            continue
        param = _param(node)
        why = _roi_missing_reason(param)
        if why:
            msgs.append(f"{where}：{why} —— P0 模板节点必须写**收窄**的 roi（#108：全屏 = 把兄弟控件放进候选池）")
            continue
        roi = tuple(int(v) for v in param["roi"])
        if not T.window_fits(roi, spec.window):
            msgs.append(
                f"{where}：roi {list(roi)} 装不下正例窗口 {list(spec.window)} 的**整窗**"
                f"（滑窗是逐位置的，装不下就永远命中不了 → 静默漏检）"
            )
        if spec.sibling_window is not None and T.window_fits(roi, spec.sibling_window):
            msgs.append(
                f"{where}：roi {list(roi)} **覆盖**了同帧兄弟控件窗口 {list(spec.sibling_window)}"
                f" —— 两枚底框像素级同款（灰互评 {spec.sibling_gray:.4f}），roi 是唯一能把它们分开的东西"
                f"（阈值挡不住：任何 < {spec.sibling_gray:.2f} 的阈值也会把真按钮挡掉）"
            )
    return msgs


def probe_p0_roi_scoped() -> bool:
    """C1：每个 P0 模板节点的 roi 都收窄、装得下正例、装不下兄弟控件。"""
    return _roi_scoped_failures() == []


# ---------------------------------------------------------------------------
# C2：order_by 必须显式 Score
# ---------------------------------------------------------------------------
def _order_by_failures(root: Path | None = None) -> list[str]:
    nodes = _nodes_by_name(root)
    msgs: list[str] = []
    for node_name, key, fname in template_nodes():
        where = f"{fname}::{node_name}（{key}）"
        node = nodes.get(node_name)
        if node is None:
            msgs.append(f"{where} 在 pipeline 里不存在（无法核对 order_by）")
            continue
        if _rec(node).get("type") != "TemplateMatch":
            continue  # C3 会点名 type 漂移
        got = _param(node).get("order_by")
        if got != "Score":
            msgs.append(
                f"{where}：order_by={got!r}，应为 \"Score\" —— threshold 只是入闸门，"
                f"选哪个由 order_by + index 决定；默认 Horizontal + 0 = **取最左**，与「最像」无关"
            )
    return msgs


def probe_p0_order_by_score() -> bool:
    """C2：每个 P0 模板节点都显式 ``order_by: "Score"``。"""
    return _order_by_failures() == []


# ---------------------------------------------------------------------------
# C9：阈值不许低于门槛（0.85）——「调松一点更稳」是假阳的起点
# ---------------------------------------------------------------------------
def _threshold_floor_failures(root: Path | None = None) -> list[str]:
    """每个 P0 模板的 ``threshold`` 必须 ≥ :data:`THRESHOLD_FLOOR`。

    为什么单独一条：C4 只能抓「负例 ≥ 当前阈值」的**已经假阳**；把阈值从 0.85 调到 0.50 时，
    星导石这类负例最高只有 0.2779 的模板仍然不会红。阈值本身要有**绝对下界**，否则
    「重新标定」会被当成「把数字改小到能过」。``root`` 参数只为与其它守卫签名一致。
    """
    del root
    T = _templates()
    return [
        f"[{key}] threshold {spec.threshold} < {THRESHOLD_FLOOR}"
        f"（P0 绝对门槛 = 调研 §5.6 的 0.80 + 0.05 余量；低于它 = 把假阳口子重新打开）"
        for key, spec in T.TEMPLATES.items()
        if spec.threshold < THRESHOLD_FLOOR
    ]


def probe_p0_threshold_floor() -> bool:
    """C9：每个 P0 模板 threshold ≥ 0.85。"""
    return _threshold_floor_failures() == []


# ---------------------------------------------------------------------------
# C3：真源 ⇄ 投影逐项一致 + OCR 兜底没被删/改坏
# ---------------------------------------------------------------------------
def _projection_pairs(spec) -> tuple[tuple[str, object], ...]:
    """投影必须逐项等于的真源值（加字段/改字段名就在这里改，别在别处抄第二份）。"""
    return (
        ("template", [spec.template]),
        ("threshold", spec.threshold),
        ("roi", list(spec.roi)),
        ("order_by", spec.order_by),
    )


def _ocr_fallback_failures(root: Path | None = None) -> list[str]:
    """★双通道的另一半★：OCR 兜底必须在场、且没有被偷偷改坏。"""
    T = _templates()
    nodes = _nodes_by_name(root)
    msgs: list[str] = []

    def expect_ocr(node_name: str, expected: list[str], roi=None) -> None:
        node = nodes.get(node_name)
        if node is None:
            msgs.append(
                f"{node_name} 不存在 —— 「模板优先、OCR 兜底」的**兜底**被删了"
                f"（模板一旦不命中就静默不再识别）"
            )
            return
        if _rec(node).get("type") != "OCR":
            msgs.append(f"{node_name} 应为 OCR（兜底叶），实际 {_rec(node).get('type')!r}")
            return
        got = _param(node).get("expected")
        if got != expected:
            msgs.append(f"{node_name}.expected={got!r}，应为 {expected!r}（兜底判据被改）")
        if roi is not None and _param(node).get("roi") != list(roi):
            msgs.append(f"{node_name}.roi={_param(node).get('roi')!r}，应为 {list(roi)!r}（兜底 ROI 被改）")

    from scene import stamina as S  # noqa: PLC0415

    expect_ocr(S.NODE_STONE, ["星导石", "星岛石"], S.STONE_ROW_ROI)
    expect_ocr(T.NODE_BONUS_NO_OCR, ["^否$"])
    expect_ocr(T.NODE_BONUS_YES_OCR, ["^是$"])
    if T.NEW_BADGE_WIRED:
        expect_ocr(T.NODE_NEW_BADGE_OCR, ["^NEW$"], T.NEW_BADGE.roi)

    # 「双通道」的形状也要钉住：Or 的第一个叶子是模板、OCR 在它之后（顺序 = 优先级）。
    pairs = [
        (T.NODE_STONE_ROW, T.NODE_STONE_ICON, S.NODE_STONE),
        (T.NODE_BONUS_NO, T.NODE_BONUS_NO_TPL, T.NODE_BONUS_NO_OCR),
        (T.NODE_BONUS_YES, T.NODE_BONUS_YES_TPL, T.NODE_BONUS_YES_OCR),
    ]
    if T.NEW_BADGE_WIRED:
        pairs.append((T.NODE_NEW_BADGE, T.NODE_NEW_BADGE_TPL, T.NODE_NEW_BADGE_OCR))
    for or_name, tpl_name, ocr_name in pairs:
        node = nodes.get(or_name)
        if node is None:
            msgs.append(f"{or_name} 不存在 —— 双通道叶被删了（模板通道没有入口）")
            continue
        if _rec(node).get("type") != "Or":
            msgs.append(f"{or_name} 应为 Or（双通道），实际 {_rec(node).get('type')!r}")
            continue
        got = _param(node).get("any_of")
        if got != [tpl_name, ocr_name]:
            msgs.append(
                f"{or_name}.any_of={got!r}，应为 [{tpl_name!r}, {ocr_name!r}] —— "
                f"Or 是「命中第一个即成功」，顺序即优先级；模板必须在前、OCR 兜底在后"
            )
    return msgs


def _projection_failures(root: Path | None = None) -> list[str]:
    T = _templates()
    nodes = _nodes_by_name(root)
    msgs: list[str] = []
    for node_name, key, fname in template_nodes():
        spec = T.TEMPLATES[key]
        where = f"{fname}::{node_name}（{key}）"
        node = nodes.get(node_name)
        if node is None:
            msgs.append(f"{where} 不存在（真源声明了这张模板，pipeline 里却没有节点用它）")
            continue
        if _rec(node).get("type") != "TemplateMatch":
            msgs.append(
                f"{where} 的 recognition.type 不是 TemplateMatch（实际 {_rec(node).get('type')!r}）"
                f" —— 模板通道的定位语义被换掉了"
            )
            continue
        param = _param(node)
        msgs.extend(
            f"{where} 真源⇄投影不一致：{field} 投影={param.get(field)!r} 真源={want!r}"
            f"（ADR-0001：scene/templates.py 是真源，pipeline 是手写投影；两处必须一起改）"
            for field, want in _projection_pairs(spec)
            if param.get(field) != want
        )
    msgs.extend(_ocr_fallback_failures(root))
    return msgs


def probe_p0_projection_synced() -> bool:
    """C3：模板节点的 template/threshold/roi/order_by 逐项 == 真源；OCR 兜底仍在场且未变。"""
    return _projection_failures() == []


# ---------------------------------------------------------------------------
# 量测：从**真机帧**算全滑窗 ZNCC（框架的做法：滑窗，不是点测一个框）
# ---------------------------------------------------------------------------
def _np():
    _paths()
    import numpy as np  # noqa: PLC0415

    return np


def _deps_missing() -> str | None:
    """缺 numpy / PIL 时返回原因（**红**，不静默跳过：假阳用例是本票唯一的取证手段）。"""
    try:
        _np()
        import PIL  # noqa: F401,PLC0415
    except Exception as exc:  # noqa: BLE001
        return (
            f"缺 numpy / Pillow（{type(exc).__name__}: {exc}）—— 本守卫要用真机帧算 ZNCC 假阳用例，"
            f"没有它们就无法取证；本守卫选择**红**而不是静默跳过（模板假阳本来就是静默的）"
        )
    return None


def frame_720(rel: str):
    """读一帧并归一到 **720x1280 基准空间**（非 720 原图 LANCZOS，与模板裁片同一口径）。"""
    from PIL import Image  # noqa: PLC0415

    path = _pixels()
    img = Image.open(REPO_ROOT / rel).convert("RGB")
    if img.size != (path.BASE_W, path.BASE_H):
        img = img.resize((path.BASE_W, path.BASE_H), Image.LANCZOS)
    return img


def template_image(spec):
    """读模板 PNG（RGB）。"""
    from PIL import Image  # noqa: PLC0415

    return Image.open(REPO_ROOT / spec.template_rel).convert("RGB")


def template_image_from(path: Path):
    """读指定路径的模板 PNG（RGB；破坏实验用临时副本时走这里）。"""
    from PIL import Image  # noqa: PLC0415

    return Image.open(path).convert("RGB")


def _corr(plane, kernel):
    """二维**互相关** ``mode="valid"``：``out[y, x] = Σ f[y+u, x+v] · k[u, v]``（FFT，纯 numpy）。

    推导（别乱改下标）：频域相乘 = **线性卷积**；取 ``k' = k[::-1, ::-1]`` 后 valid 段从
    ``(h-1, w-1)`` 起才能与上式对齐 —— 与 ``hooks_108._conv_valid`` 同一手法。
    """
    np = _np()
    big_h, big_w = plane.shape
    h, w = kernel.shape
    if h > big_h or w > big_w:
        raise ValueError(f"模板 {kernel.shape} 比帧 {plane.shape} 还大")
    sh, sw = big_h + h - 1, big_w + w - 1
    full = np.fft.irfft2(
        np.fft.rfft2(plane, s=(sh, sw)) * np.fft.rfft2(kernel, s=(sh, sw)), s=(sh, sw)
    )
    return full[h - 1 : h - 1 + (big_h - h + 1), w - 1 : w - 1 + (big_w - w + 1)]


def zncc_gray(frame, template):
    """灰度 ``TM_CCOEFF_NORMED`` 全滑窗分数图（与本仓既有存档 0.8964 / 0.470 / 0.8708 可比）。"""
    np = _np()
    f = np.asarray(frame.convert("L"), dtype=np.float64)
    t = np.asarray(template.convert("L"), dtype=np.float64)
    h, w = t.shape
    tz = t - t.mean()
    ones = np.ones((h, w), dtype=np.float64)
    num = _corr(f, tz[::-1, ::-1])
    s1 = _corr(f, ones[::-1, ::-1])
    s2 = _corr(f * f, ones[::-1, ::-1])
    var = s2 - s1 * s1 / float(h * w)
    den = np.sqrt(np.maximum(var, 1e-12) * float((tz * tz).sum()))
    return num / np.maximum(den, 1e-12)


def zncc_color(frame, template):
    """三通道展平 ``TM_CCOEFF_NORMED`` —— **框架真正的口径**。

    协议没有「转灰度」开关，模板是彩色 PNG ⇒ ``cv::matchTemplate(…, TM_CCOEFF_NORMED)`` 在
    8UC3 上用**跨通道的单一均值**（``T' = T - 1/(w·h·cn)·ΣT``）。本函数按同一式子算：
    ``num = Σ_c Σ_p f_c(p)·(t_c(p) − m_t)``、``var_f`` 与 ``Σ t'^2`` 都跨通道求和。
    """
    np = _np()
    fa = np.asarray(frame, dtype=np.float64)
    ta = np.asarray(template, dtype=np.float64)
    h, w = ta.shape[:2]
    n = float(h * w * ta.shape[2])
    chans = ta.transpose(2, 0, 1)
    m_t = float(chans.sum()) / n
    ones = np.ones((h, w), dtype=np.float64)
    shape = (fa.shape[0] - h + 1, fa.shape[1] - w + 1)
    num = np.zeros(shape)
    sum_a = np.zeros(shape)
    sum_b = np.zeros(shape)
    den_t = 0.0
    for c in range(fa.shape[2]):
        plane = fa[:, :, c]
        tc = chans[c]
        num += _corr(plane, tc[::-1, ::-1]) - m_t * _corr(plane, ones[::-1, ::-1])
        sum_a += _corr(plane, ones[::-1, ::-1])
        sum_b += _corr(plane * plane, ones[::-1, ::-1])
        den_t += float(((tc - m_t) ** 2).sum())
    var = sum_b - sum_a * sum_a / n
    den = np.sqrt(np.maximum(var, 1e-12) * den_t)
    return num / np.maximum(den, 1e-12)


def global_best(scores) -> tuple[float, int, int]:
    """全屏最高分及其左上角坐标（``x``/``y`` 是模板左上角，720 空间）。"""
    np = _np()
    idx = int(np.argmax(scores))
    y, x = divmod(idx, scores.shape[1])
    return round(float(scores[y, x]), 4), int(x), int(y)


def roi_scores(frame, template, roi):
    """★按 roi **先裁剪再匹配**★（框架就是这么做的，见 ``common.json`` 的 #37 注释）→
    ``(gray_map, color_map, (x0, y0))``；坐标要加回 ``(x0, y0)`` 才是 720 空间。

    roi 比模板还小时返回 ``None``（= 滑窗一个位置都跑不到 ⇒ 必然漏检）。
    """
    x0, y0, rw, rh = (int(v) for v in roi)
    tw, th = template.size
    if rw < tw or rh < th:
        return None
    crop = frame.crop((x0, y0, x0 + rw, y0 + rh))
    return zncc_gray(crop, template), zncc_color(crop, template), (x0, y0)


def roi_best(scores, origin, shape) -> tuple[float, int, int] | None:
    """roi 内（已裁好的分数图）最高分位置，坐标加回 ``origin``。"""
    np = _np()
    del shape  # 分数图本身已经是「roi 内所有整窗位置」
    if scores.size == 0:
        return None
    idx = int(np.argmax(scores))
    yy, xx = divmod(idx, scores.shape[1])
    return round(float(scores[yy, xx]), 4), int(origin[0] + xx), int(origin[1] + yy)


def roi_candidates(scores, origin, threshold: float, radius: int = 20, limit: int = 20):
    """roi 内 ≥ ``threshold`` 的候选（逐次取最大 + 抑制邻域）→ ``[(score, x, y), …]``。"""
    np = _np()
    if scores.size == 0:
        return []
    s = scores.copy()
    out: list[tuple[float, int, int]] = []
    for _ in range(limit):
        idx = int(np.argmax(s))
        yy, xx = divmod(idx, s.shape[1])
        value = float(s[yy, xx])
        if value < threshold:
            break
        out.append((round(value, 4), int(origin[0] + xx), int(origin[1] + yy)))
        s[max(0, yy - radius) : yy + radius + 1, max(0, xx - radius) : xx + radius + 1] = -1.0
    return out


#: 量测缓存：C4 与 C5 拿到的是**同一份**数字，别为同一批帧算两遍（每个模板 7 帧 × 12 次卷积）。
_MEASURE_CACHE: dict[tuple, dict] = {}


def _spec_key(spec) -> tuple:
    """缓存键：真源里凡是会改变量测结果的字段都要进键（含模板文件的 mtime/size）。"""
    path = REPO_ROOT / spec.template_rel
    stamp = (path.stat().st_mtime_ns, path.stat().st_size) if path.is_file() else None
    return (
        str(REPO_ROOT),
        spec.template,
        stamp,
        spec.roi,
        spec.threshold,
        spec.positive_frame,
        tuple((h.frame, h.x, h.y, h.gray, h.color) for h in spec.negatives),
        tuple((h.frame, h.x, h.y, h.gray, h.color) for h in spec.cross_positives),
        spec.sibling_window,
        tuple((h.frame, h.x, h.y) for h in spec.global_watch),
    )


def measure(spec) -> dict:
    """对一条 :class:`TemplateSpec` 跑**全部**取证量测（正例 / 负例 / 兄弟 / roi 外危险分）。

    返回 ``{"positive": {...}, "negatives": {帧: {...}}, "cross": {帧: {...}},
    "sibling": {...}, "watch": {帧: {...}}}``；两口径（``gray`` / ``color``）都给。
    守卫与 ``tools/test_template_p0.py`` 都走这里，所以「存档 vs 实测」的比法只有一份。
    """
    key = _spec_key(spec)
    cached = _MEASURE_CACHE.get(key)
    if cached is not None:
        return cached

    tpl = template_image(spec)
    frames: dict[str, object] = {}

    def frame_of(rel: str):
        if rel not in frames:
            frames[rel] = frame_720(rel)
        return frames[rel]

    def _roi_maps(rel: str):
        return roi_scores(frame_of(rel), tpl, spec.roi)

    pos_maps = _roi_maps(spec.positive_frame)
    pos = {
        "frame": spec.positive_frame,
        "gray": roi_best(pos_maps[0], pos_maps[2], ()) if pos_maps else None,
        "color": roi_best(pos_maps[1], pos_maps[2], ()) if pos_maps else None,
        "candidates": len(roi_candidates(pos_maps[0], pos_maps[2], spec.threshold)) if pos_maps else 0,
        "template_size": (tpl.size[1], tpl.size[0]),
        "fits": pos_maps is not None,
    }
    negatives = {}
    for hit in spec.negatives:
        maps = pos_maps if hit.frame == spec.positive_frame else _roi_maps(hit.frame)
        negatives[hit.frame] = {
            "gray": roi_best(maps[0], maps[2], ()) if maps else None,
            "color": roi_best(maps[1], maps[2], ()) if maps else None,
            "fits": maps is not None,
        }
    # ★跨帧正例★：分数取「**同一个正例窗口**处的值」（与存档口径一致），同时记 roi 内 argmax
    # 与候选数 —— 只有 argmax 也落回该窗口、且候选唯一，才说明模板在新帧上仍「指哪儿打哪儿」。
    cross = {}
    for hit in spec.cross_positives:
        maps = _roi_maps(hit.frame)
        entry = {
            "frame": hit.frame,
            "fits": maps is not None,
            "gray_at": None,
            "color_at": None,
            "gray": roi_best(maps[0], maps[2], ()) if maps else None,
            "color": roi_best(maps[1], maps[2], ()) if maps else None,
            "candidates": len(roi_candidates(maps[0], maps[2], spec.threshold)) if maps else 0,
        }
        if maps:
            ix, iy = hit.x - spec.roi[0], hit.y - spec.roi[1]
            if 0 <= ix < maps[0].shape[1] and 0 <= iy < maps[0].shape[0]:
                entry["gray_at"] = round(float(maps[0][iy, ix]), 4)
                entry["color_at"] = round(float(maps[1][iy, ix]), 4)
        cross[hit.frame] = entry
    sibling = None
    if spec.sibling_window is not None:
        x, y = spec.sibling_window[0], spec.sibling_window[1]
        g = zncc_gray(frame_of(spec.positive_frame), tpl)
        c = zncc_color(frame_of(spec.positive_frame), tpl)
        sibling = {
            "window": list(spec.sibling_window),
            "gray": round(float(g[y, x]), 4),
            "color": round(float(c[y, x]), 4),
        }
    watch = {}
    for hit in spec.global_watch:
        g = zncc_gray(frame_of(hit.frame), tpl)
        c = zncc_color(frame_of(hit.frame), tpl)
        watch[hit.frame] = {
            "gray_global": global_best(g),
            "color_global": global_best(c),
            "gray_at": round(float(g[hit.y, hit.x]), 4),
            "color_at": round(float(c[hit.y, hit.x]), 4),
        }
    result = {"positive": pos, "negatives": negatives, "cross": cross, "sibling": sibling, "watch": watch}
    _MEASURE_CACHE[key] = result
    return result


# ---------------------------------------------------------------------------
# C4：真机帧假阳用例（正例命中 + 负例不假阳）
# ---------------------------------------------------------------------------
def _frame_failures(root: Path | None = None) -> list[str]:
    missing = _deps_missing()
    if missing:
        return [missing]
    T = _templates()
    msgs: list[str] = []
    for key, spec in T.TEMPLATES.items():
        tpl_path = REPO_ROOT / spec.template_rel
        if not tpl_path.is_file():
            msgs.append(f"[{key}] 模板裁片缺失：{spec.template_rel}（没有裁片就没有假阳用例）")
            continue
        absent = [
            frame
            for frame in (
                spec.positive_frame,
                *(h.frame for h in spec.negatives),
                *(h.frame for h in spec.cross_positives),
            )
            if not (REPO_ROOT / frame).is_file()
        ]
        if absent:
            msgs.extend(
                f"[{key}] 证据帧缺失：{frame}（已入库的取证帧被删 → 假阳用例失效）" for frame in absent
            )
            continue
        # 0) **存档数据本身**先要合格：正例保守分够高、余量够。存档就不合格时，下面的实测比对
        #    再准也没有意义（这条也让「有人把存档数字调成好看的样子」当场露出来）。
        if spec.positive_worst < POSITIVE_MIN:
            msgs.append(
                f"[{key}] 存档正例保守分 {spec.positive_worst:.4f} < {POSITIVE_MIN}"
                f"（正例取灰/彩较低者；真源数据本身不合格）"
            )
        if spec.margin < NEGATIVE_MARGIN_MIN:
            msgs.append(
                f"[{key}] 存档余量 {spec.margin:.4f} < {NEGATIVE_MARGIN_MIN}"
                f"（阈值 {spec.threshold} − 负例最高 {spec.negative_worst:.4f}；靠阈值擦屁股）"
            )
        m = measure(spec)
        pos = m["positive"]
        if not pos["fits"]:
            msgs.append(
                f"[{key}] 正例帧 {spec.positive_frame}：roi {list(spec.roi)} 比模板 {pos['template_size']} 还小"
                f"（滑窗一个位置都跑不到）"
            )
            continue
        # ① 正例：roi 内必须命中、落在正例窗口、分数够高、且**候选唯一**。
        for metric in ("gray", "color"):
            got = pos[metric]
            if got is None:
                msgs.append(f"[{key}] 正例帧 {spec.positive_frame} 的 roi 内无法定位（{metric}）")
                continue
            score, x, y = got
            if score < POSITIVE_MIN:
                msgs.append(
                    f"[{key}] 正例帧 {spec.positive_frame} 的 roi 内最高 {metric} 分只有 {score:.4f}"
                    f" < {POSITIVE_MIN}（模板/帧/roi 变了 → 重新标定）"
                )
            if abs(x - spec.window[0]) > WINDOW_TOL or abs(y - spec.window[1]) > WINDOW_TOL:
                msgs.append(
                    f"[{key}] 正例帧 {spec.positive_frame} 的 roi 内最高 {metric} 分在 ({x},{y})，"
                    f"不是正例窗口 {list(spec.window[:2])}（±{WINDOW_TOL}px）"
                )
        if pos["candidates"] != 1:
            msgs.append(
                f"[{key}] 正例帧 {spec.positive_frame} 的 roi 内 ≥threshold 的候选有 "
                f"{pos['candidates']} 个（期望**恰好 1 个**）—— 多了就重新落到「排序决定选哪个」"
            )
        # ①b ★跨帧正例★：未参与裁图的真机帧上，**同一个窗口**仍要够分，argmax 不漂、候选唯一。
        #     只有这一条能反驳「1.0000 是样本内自证」（调研 §5.3 第 3 条）。
        for hit in spec.cross_positives:
            got = m["cross"][hit.frame]
            where = f"[{key}] 跨帧正例 {hit.frame}"
            if not got["fits"]:
                msgs.append(f"{where}：roi 比模板还小（无法取证）")
                continue
            need = max(CROSS_POSITIVE_MIN, spec.threshold + NEGATIVE_MARGIN_MIN)
            for metric in ("gray", "color"):
                at = got[f"{metric}_at"]
                if at is None:
                    msgs.append(
                        f"{where}：存档窗口 {list(spec.window[:2])} 不在 roi {list(spec.roi)} 内"
                        f"（跨帧正例无从量测）"
                    )
                elif at < need:
                    msgs.append(
                        f"{where}：窗口 {list(spec.window[:2])} 处 {metric} 分只有 {at:.4f} < {need:.4f}"
                        f"（阈值 {spec.threshold} + 余量 {NEGATIVE_MARGIN_MIN}；模板没有跨帧泛化）"
                    )
                best = got[metric]
                if best is not None:
                    score, x, y = best
                    if abs(x - hit.x) > WINDOW_TOL or abs(y - hit.y) > WINDOW_TOL:
                        msgs.append(
                            f"{where}：roi 内最高 {metric} 分 {score:.4f} 在 ({x},{y})，"
                            f"不是存档窗口 {list((hit.x, hit.y))}（±{WINDOW_TOL}px）—— argmax 漂了"
                        )
            if got["candidates"] != 1:
                msgs.append(
                    f"{where}：roi 内 ≥threshold 的候选有 {got['candidates']} 个（期望恰好 1 个）"
                )
        # ② 负例：roi 内**一个都不许命中**，且余量够。
        for frame, got in m["negatives"].items():
            if not got["fits"]:
                msgs.append(f"[{key}] 负例帧 {frame}：roi 比模板还小（无法取证）")
                continue
            worst = max(
                (v for v in (got["gray"], got["color"]) if v is not None),
                key=lambda r: r[0],
                default=None,
            )
            if worst is None:
                msgs.append(f"[{key}] 负例帧 {frame} 的 roi 内无法定位")
                continue
            if worst[0] >= spec.threshold:
                msgs.append(
                    f"[{key}] 负例帧 {frame}：roi 内不该命中，却出现 {worst[0]:.4f} ≥ 阈值 "
                    f"{spec.threshold} @({worst[1]},{worst[2]}) —— **假阳**"
                )
            elif spec.threshold - worst[0] < NEGATIVE_MARGIN_MIN:
                msgs.append(
                    f"[{key}] 负例帧 {frame}：roi 内最高 {worst[0]:.4f}，余量只有 "
                    f"{spec.threshold - worst[0]:.4f} < {NEGATIVE_MARGIN_MIN}"
                    f"（靠阈值擦屁股，不是靠 roi）"
                )
        # ③ 兄弟控件必须落在 roi **外**（否则「选哪个」又变成排序问题）。
        if spec.sibling_window is not None and T.window_fits(spec.roi, spec.sibling_window):
            msgs.append(
                f"[{key}] 兄弟控件窗口 {list(spec.sibling_window)} 整窗落在 roi {list(spec.roi)} 内"
                f"（roi 必须把它排除出候选池）"
            )
    return msgs


def probe_p0_frame_no_false_positive() -> bool:
    """C4：真机帧全滑窗 ZNCC —— 正例命中（候选唯一）且负例 roi 内不命中。"""
    return _frame_failures() == []


# ---------------------------------------------------------------------------
# C5：存档分数 ⇄ 实测（容差 0.02，含 roi 外的危险高分与同帧兄弟）
# ---------------------------------------------------------------------------
def _archive_failures(root: Path | None = None) -> list[str]:
    missing = _deps_missing()
    if missing:
        return [missing]
    T = _templates()
    msgs: list[str] = []

    def cmp(where: str, what: str, measured: float, archived: float) -> None:
        if abs(measured - archived) > SCORE_TOL:
            msgs.append(
                f"{where}：{what} 实测 {measured:.4f} vs 存档 {archived:.4f}"
                f"（差 {abs(measured - archived):.4f} > 容差 {SCORE_TOL}）—— "
                f"帧/模板/roi 变了就要重新标定并更新 scene/templates.py 的存档"
            )

    for key, spec in T.TEMPLATES.items():
        if not (REPO_ROOT / spec.template_rel).is_file():
            msgs.append(f"[{key}] 模板裁片缺失：{spec.template_rel}")
            continue
        m = measure(spec)
        pos = m["positive"]
        if pos["gray"] is None or pos["color"] is None:
            msgs.append(f"[{key}] 正例帧 {spec.positive_frame} 无法量测（roi 比模板还小）")
            continue
        cmp(f"[{key}] 正例 {spec.positive_frame}", "gray", pos["gray"][0], spec.positive_gray)
        cmp(f"[{key}] 正例 {spec.positive_frame}", "color", pos["color"][0], spec.positive_color)
        for hit in spec.cross_positives:
            got = m["cross"][hit.frame]
            if got["gray_at"] is None or got["color_at"] is None:
                msgs.append(f"[{key}] 跨帧正例 {hit.frame} 无法量测（窗口不在 roi 内）")
                continue
            cmp(f"[{key}] 跨帧正例 {hit.frame}@窗口{list(spec.window[:2])}", "gray", got["gray_at"], hit.gray)
            cmp(f"[{key}] 跨帧正例 {hit.frame}@窗口{list(spec.window[:2])}", "color", got["color_at"], hit.color)
        for hit in spec.negatives:
            got = m["negatives"][hit.frame]
            if got["gray"] is None or got["color"] is None:
                msgs.append(f"[{key}] 负例 {hit.frame} 无法量测（roi 比模板还小）")
                continue
            cmp(f"[{key}] 负例 {hit.frame}", "gray", got["gray"][0], hit.gray)
            cmp(f"[{key}] 负例 {hit.frame}", "color", got["color"][0], hit.color)
            # ★位置也要对上★（存档的 x/y 是**灰口径** argmax）：分数相同但位置漂了，说明
            # 「最高分换了个地方」—— 比分数漂更危险（下次可能就漂进真按钮所在的位置）。
            # ★只在分数**有意义**时比★：接近 0 的分说明该处整片平坦（方差 ≈ 0），此时 argmax
            # 在一堆并列 0.0000 里是谁纯属 numpy 实现细节，比它没有意义（会制造假红）。
            if hit.gray >= FLAT_SCORE and got["gray"][0] >= FLAT_SCORE:
                if (got["gray"][1], got["gray"][2]) != (hit.x, hit.y):
                    msgs.append(
                        f"[{key}] 负例 {hit.frame} 的灰口径最高分位置 ({got['gray'][1]},{got['gray'][2]})"
                        f" != 存档 ({hit.x},{hit.y}) —— 最高分换了个地方"
                    )
        if m["sibling"] is not None:
            cmp(f"[{key}] 同帧兄弟控件 {list(spec.sibling_window)}", "gray", m["sibling"]["gray"], spec.sibling_gray)
            cmp(f"[{key}] 同帧兄弟控件 {list(spec.sibling_window)}", "color", m["sibling"]["color"], spec.sibling_color)
        for hit in spec.global_watch:
            got = m["watch"][hit.frame]
            cmp(f"[{key}] roi 外危险分 {hit.frame}", "gray@窗口", got["gray_at"], hit.gray)
            cmp(f"[{key}] roi 外危险分 {hit.frame}", "color@窗口", got["color_at"], hit.color)
            # 全屏最高分也要**报出来并且对上**：这就是「全屏 roi = 直接假阳」的量化证据
            #（存档的窗口就是全屏灰口径 argmax 的位置 ⇒ 放宽 roi 就会命中那里）。
            cmp(f"[{key}] roi 外危险分 {hit.frame}", "gray 全屏最高", got["gray_global"][0], hit.gray)
    return msgs


def probe_p0_archive_scores_match_measured() -> bool:
    """C5：存档分数（正例 / 负例 / 兄弟 / roi 外危险分）与实测一致，容差 0.02。"""
    return _archive_failures() == []


# ---------------------------------------------------------------------------
# C6：模板像素 == 从正例帧按 window 重裁（二进制资产不可 review，只能逐像素）
# ---------------------------------------------------------------------------
def _pixel_failures(image_root: Path | None = None) -> list[str]:
    """``image_root`` 默认 ``assets/resource/image``；破坏实验传临时副本（帧仍从真仓读）。"""
    missing = _deps_missing()
    if missing:
        return [missing]
    T = _templates()
    base = Path(image_root) if image_root is not None else IMAGE_DIR
    msgs: list[str] = []
    for key, spec in T.TEMPLATES.items():
        path = base / spec.template
        if not path.is_file():
            msgs.append(f"[{key}] 模板裁片缺失：{spec.template_rel}")
            continue
        if not (REPO_ROOT / spec.positive_frame).is_file():
            msgs.append(f"[{key}] 正例帧缺失：{spec.positive_frame}（无法复核裁片来源）")
            continue
        want = frame_720(spec.positive_frame).crop(
            (
                spec.window[0],
                spec.window[1],
                spec.window[0] + spec.window[2],
                spec.window[1] + spec.window[3],
            )
        )
        got = template_image_from(path)
        if got.size != want.size:
            msgs.append(
                f"[{key}] 模板 {spec.template_rel} 尺寸 {got.size} != 按 window 重裁的 {want.size}"
                f"（window {list(spec.window)}）"
            )
            continue
        if got.tobytes() != want.tobytes():
            msgs.append(
                f"[{key}] 模板 {spec.template_rel} 的**像素**与「从 {spec.positive_frame} 按 window "
                f"{list(spec.window)} 重裁」不一致 —— 模板被换成了别的图（或正例帧换了）"
            )
    return msgs


def probe_p0_template_pixels_from_evidence() -> bool:
    """C6：每个模板 PNG 逐像素等于「从正例帧按 window 重裁」。"""
    return _pixel_failures() == []


# ---------------------------------------------------------------------------
# C7：接线现状 ⇄ 声明（P0-1 已接两个枢纽；P0-3 未接线）
# ---------------------------------------------------------------------------
def _referenced_templates(root: Path | None = None) -> set[str]:
    """pipeline 里被 ``TemplateMatch.template`` 引用到的模板相对路径。"""
    out: set[str] = set()
    for data in _pipelines(root).values():
        for node in data.values():
            param = _param(node)
            tpl = param.get("template")
            if isinstance(tpl, str):
                out.add(tpl)
            elif isinstance(tpl, (list, tuple)):
                out.update(x for x in tpl if isinstance(x, str))
    return out


def _template_nodes_using(tpl: str, root: Path | None = None) -> set[str]:
    """pipeline 里 ``template`` 引用了 ``tpl`` 的节点名（用于「声明了几处用这张裁片」对账）。"""
    out: set[str] = set()
    for data in _pipelines(root).values():
        for name, node in data.items():
            got = _param(node).get("template")
            if got == tpl or (isinstance(got, (list, tuple)) and tpl in got):
                out.add(name)
    return out


def _wiring_failures(root: Path | None = None) -> list[str]:
    T = _templates()
    S = _submodule("stamina")
    W = _submodule("wuchong")
    files = _pipelines(root)
    nodes = _nodes_by_name(root)
    msgs: list[str] = []

    # (a) P0-1 模板动作节点：只许出现在**声明过的**枢纽里，且排在 OCR 版之前。
    # ★#102 起「哪些枢纽要恢复链」的真源是 scene.stamina.STAMINA_CONSUMING_CHAINS★（本票只读
    #   scene/templates.py，那份 STONE_TPL_WIRED_HUBS 是派生前只接了两个外传入口的**历史声明**）。
    #   并上五重的**中继**（#103 起流程节点经它拿恢复引用 = FLOW_EXCEPTIONS 的投影），
    #   三处合起来 = 「允许出现」的白名单；既不误伤新接的四个枢纽，也不放行乱接的第五个。
    declared = {(f, hub) for f, hub in T.STONE_TPL_WIRED_HUBS}
    derived = {(file, hub) for _scene, file, hub in S.STAMINA_CONSUMING_CHAINS}
    relay = {
        (getattr(W, "SCENE_FILE", "wuchong_scene.json"), getattr(W, "SCENE_GUARD_CHAIN", "WuchongGuardChain"))
    }
    allowed = declared | derived | relay
    for fname, data in files.items():
        for hub, node in data.items():
            nxt = node.get("next") if isinstance(node, dict) else None
            if not isinstance(nxt, list) or T.STONE_TPL_REF not in nxt:
                continue
            if (fname, hub) not in allowed:
                msgs.append(
                    f"{fname}::{hub}.next 出现了 {T.STONE_TPL_REF}，但 scene/stamina 的 "
                    f"STAMINA_CONSUMING_CHAINS 与 scene/templates.py 的 STONE_TPL_WIRED_HUBS 都没声明它"
                    f"（接线改了就要改声明）"
                )
                continue
            ocr_ref = f"[JumpBack]{T.NODE_USE_STONE_OCR}"
            if ocr_ref in nxt and nxt.index(T.STONE_TPL_REF) > nxt.index(ocr_ref):
                msgs.append(
                    f"{fname}::{hub}.next 里 {T.STONE_TPL_REF} 排在 {ocr_ref} **之后** —— "
                    f"候选是**按顺序**识别的，「模板优先、OCR 兜底」要求模板在前"
                )
    for fname, hub in T.STONE_TPL_WIRED_HUBS:
        nxt = (files.get(fname) or {}).get(hub, {})
        nxt = nxt.get("next") if isinstance(nxt, dict) else None
        if not isinstance(nxt, list) or T.STONE_TPL_REF not in nxt:
            msgs.append(
                f"{fname}::{hub}.next 没有 {T.STONE_TPL_REF}（声明为已接线的枢纽）—— "
                f"模板通道在这条链上不可达，等于没接"
            )
    # 两个入口分派表必须仍然逐项一致（既有不变式，别被这次插入打破）。
    a = (files.get("side_story.json") or {}).get("SideStoryEntry", {}).get("next")
    b = (files.get("side_story.json") or {}).get("SideClearEntry", {}).get("next")
    if isinstance(a, list) and isinstance(b, list) and a != b:
        msgs.append("side_story.json 的 SideStoryEntry / SideClearEntry 分派表不再逐项一致（本次插桩打破了不变式）")

    # (b) P0-3：小行 NEW 徽标已接线（双通道）—— 声明几处，pipeline 就只许几处。
    badge_ref = T.NEW_BADGE.template
    referenced = _referenced_templates(root)
    if T.NEW_BADGE_WIRED:
        if badge_ref not in referenced:
            msgs.append(
                f"scene/templates.py 声明 NEW 徽标**已接线**（NEW_BADGE_WIRED=True），但 pipeline 里"
                f"没有任何节点引用 {badge_ref} —— 声明与现状不符（模板通道被悄悄摘掉）"
            )
        if not T.NEW_BADGE_NODES:
            msgs.append("NEW_BADGE_WIRED=True 但 NEW_BADGE_NODES 为空（没有节点名可核对）")
        else:
            missing = [name for name in T.NEW_BADGE_NODES if name not in nodes]
            if missing:
                msgs.append(
                    f"声明为已接线的 NEW 模板叶在 pipeline 里不存在：{missing} —— "
                    f"「模板优先」通道没有入口"
                )
            extra = sorted(_template_nodes_using(badge_ref, root) - set(T.NEW_BADGE_NODES))
            if extra:
                msgs.append(
                    f"pipeline 里除了声明的 {list(T.NEW_BADGE_NODES)}，还有节点在用 {badge_ref}："
                    f"{extra} —— 用了这张裁片就要在 scene/templates.py 的 NEW_BADGE_NODES 里声明"
                    f"（接线改了就要改声明）"
                )
        if T.NEW_BADGE.evidence != "ok":
            msgs.append(
                f"NEW_BADGE_WIRED=True 时 NEW_BADGE.evidence 应为 'ok'（正例 + 跨帧正例已在库），"
                f"实际 {T.NEW_BADGE.evidence!r}"
            )
        wrapper = nodes.get(T.NODE_NEW_BADGE)
        if wrapper is None or _rec(wrapper).get("type") != "Or":
            msgs.append(
                f"{T.NODE_NEW_BADGE} 应为 Or（模板优先、OCR 兜底），实际 "
                f"{(wrapper or {}).get('recognition')!r} —— 双通道叶被换成单通道"
            )
    else:
        if badge_ref in referenced:
            msgs.append(
                f"pipeline 里已经有节点引用 {badge_ref}，但 scene/templates.py 仍写着 "
                f"NEW_BADGE_WIRED=False（声明与现状不符：要么补声明，要么别偷偷接线）"
            )
        if T.NEW_BADGE.evidence != "pending":
            msgs.append(
                f"NEW_BADGE_WIRED=False 时 NEW_BADGE.evidence 必须仍是 'pending'（说明待取证原因），"
                f"实际 {T.NEW_BADGE.evidence!r}"
            )
        if not T.NEW_BADGE.evidence_note.strip():
            msgs.append("NEW_BADGE.evidence_note 为空 —— 待取证必须写明缺什么、为什么缺")
    return msgs


def probe_p0_wiring_declared() -> bool:
    """C7：P0-1 模板通道接线 ⇄ 声明；P0-3 NEW 徽标未接线 ⇄ 声明。"""
    return _wiring_failures() == []


# ---------------------------------------------------------------------------
# C8：★本票「四个枢纽未接」那一条★ —— 每个消费链枢纽都挂模板优先通道，且在 OCR 版之前
# ---------------------------------------------------------------------------
#: ★票面点名的四个枢纽★（#102 的「剩下四个枢纽」）：模板优先通道必须逐个挂上。
#: 顺序 = 票面点名顺序；集合**不许悄悄缩小**（删一条就红 —— 这就是那张票本身）。
#: 真源仍是 ``scene.stamina.STAMINA_CONSUMING_CHAINS`` / ``recovery_refs()``：下面的
#: :func:`_stone_hub_failures` 会把「这张名单 ∪ 消费链名单」全都核一遍。
STONE_TPL_REQUIRED_HUBS: tuple[tuple[str, str], ...] = (
    ("wuchong.json", "WuchongEntry"),
    ("raid.json", "RaidDispatch"),
    ("special_dungeon.json", "SpecialEntry"),
    ("abyss.json", "AbyssEntry"),
)


def _stone_hub_failures(root: Path | None = None) -> list[str]:
    """C8：模板优先通道必须挂在**每个**消费链枢纽上，且排在 OCR 版之前。

    两件事，缺一不可：

    * **挂上了**：``[JumpBack]PubStaminaUseStoneTpl`` 出现在该枢纽 ``next`` 里 —— 它的判据 =
      双通道行 ``PubStaminaStoneRow``（``Or(图标模板, 行名 OCR)``），所以「挂模板优先通道」
      不是挂一个同名的壳（动作节点的 ``all_of`` 也一并核对）；
    * **排在 OCR 版之前**：``next`` 是**有序候选**、先命中先执行。反了就是 OCR 先吃掉该帧、
      模板通道永远轮不到 —— 那条通道等于没接（这是最容易「看起来接好了」的坏法）。
    """
    T = _templates()
    S = _submodule("stamina")
    files = _pipelines(root)
    nodes = _nodes_by_name(root)
    tpl_ref = T.STONE_TPL_REF
    ocr_ref = f"[JumpBack]{T.NODE_USE_STONE_OCR}"
    msgs: list[str] = []

    # ① 模板优先通道的**动作**节点必须真的以双通道行为判据（否则只是名字对上了）。
    action = nodes.get(T.NODE_USE_STONE_TPL)
    if action is None:
        msgs.append(
            f"{T.NODE_USE_STONE_TPL} 在 pipeline 里不存在（模板优先通道没有动作节点 → 枢纽里挂的是悬空引用）"
        )
    elif _rec(action).get("type") != "And":
        msgs.append(
            f"{T.NODE_USE_STONE_TPL} 的识别应为 And（弹窗正文 ∧ 双通道行），实际 "
            f"{_rec(action).get('type')!r}"
        )
    else:
        all_of = list(_param(action).get("all_of") or [])
        if T.NODE_STONE_ROW not in all_of:
            msgs.append(
                f"{T.NODE_USE_STONE_TPL}.all_of={all_of!r} 里没有双通道行 {T.NODE_STONE_ROW} —— "
                f"「模板优先」的判据没被这条通道用上"
            )

    # ② 票面的四个枢纽 ∪ 消费链名单：逐个核对「挂了 + 在 OCR 版之前」。
    required: list[tuple[str, str]] = list(STONE_TPL_REQUIRED_HUBS)
    for _scene, file, hub in S.STAMINA_CONSUMING_CHAINS:
        if (file, hub) not in required:
            required.append((file, hub))
    for fname, hub in required:
        nxt = ((files.get(fname) or {}).get(hub) or {}).get("next")
        if not isinstance(nxt, list):
            msgs.append(f"{fname}::{hub} 不存在或没有 next（模板优先通道无处挂）")
            continue
        if tpl_ref not in nxt:
            msgs.append(
                f"{fname}::{hub}.next 没有 {tpl_ref} —— 模板优先通道没接进这个枢纽："
                f"体力不足弹窗只能靠行名 OCR 判据（OCR 会把「星导石」读成「星岛石」/ 丢字）"
            )
            continue
        if ocr_ref in nxt and nxt.index(tpl_ref) > nxt.index(ocr_ref):
            msgs.append(
                f"{fname}::{hub}.next 把 {tpl_ref} 排在 {ocr_ref} **之后** —— 候选是**按顺序**识别的，"
                f"OCR 会先吃掉该帧 → 模板通道永远轮不到（模板优先在这条链上不成立）"
            )
    return msgs


def probe_p0_stone_row_hubs() -> bool:
    """C8：四个枢纽（+ 全部消费链枢纽）都挂模板优先通道，且排在 OCR 版之前。"""
    return _stone_hub_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        "p0-roi-scoped",
        "#102",
        "P0 模板节点的 roi 必须收窄：整窗装得下正例窗口、装不下同帧兄弟控件、不是全屏"
        "（「否/是」底框像素级同款，灰互评 0.5840 —— roi 是唯一能把它们分开的东西）",
        probe_p0_roi_scoped,
    ),
    (
        "p0-order-by-score",
        "#102",
        "P0 模板节点必须显式 order_by: \"Score\"：threshold 只是入闸门，"
        "选哪个由 order_by + index 决定，默认 Horizontal + 0 = 取最左",
        probe_p0_order_by_score,
    ),
    (
        "p0-projection-synced",
        "#102",
        "真源 scene/templates.py ⇄ pipeline 投影逐项一致（template/threshold/roi/order_by），"
        "且 OCR 兜底仍在场、Or 的顺序是「模板在前、OCR 在后」",
        probe_p0_projection_synced,
    ),
    (
        "p0-frame-no-false-positive",
        "#102",
        "真机帧全滑窗 ZNCC：正例 roi 内候选恰好 1 个且落在正例窗口，**跨帧正例**在同一窗口仍 ≥"
        "阈值+0.05 且 argmax 不漂，负例 roi 内不命中且余量 ≥0.05",
        probe_p0_frame_no_false_positive,
    ),
    (
        "p0-archive-scores-match-measured",
        "#102",
        "存档 ZNCC（正例 / 负例逐帧 / 同帧兄弟 / roi 外危险分）与实测一致，容差 0.02",
        probe_p0_archive_scores_match_measured,
    ),
    (
        "p0-template-pixels-from-evidence",
        "#102",
        "每个模板 PNG 逐像素等于「从正例帧按 window 重裁」（模板是二进制资产，diff 看不见）",
        probe_p0_template_pixels_from_evidence,
    ),
    (
        "p0-wiring-declared",
        "#102",
        "P0-1 模板动作节点只出现在**声明过的**枢纽里（scene.stamina 的消费链 ∪ scene/templates 的 "
        "历史声明）且排在 OCR 版之前；P0-3 小行 NEW 徽标已接线（SpecialNewBadge = Or），"
        "声明几处就只许几处 —— 偷偷接线 / 偷偷断线都红",
        probe_p0_wiring_declared,
    ),
    (
        "p0-stone-row-hubs",
        "#102",
        "四个枢纽（WuchongEntry / RaidDispatch / SpecialEntry / AbyssEntry）+ 全部消费链枢纽都必须挂"
        "模板优先通道 [JumpBack]PubStaminaUseStoneTpl（判据 = 双通道行 PubStaminaStoneRow），且**排在** "
        "OCR 版 [JumpBack]PubStaminaUseStone **之前**（next 是有序候选，先命中先执行）",
        probe_p0_stone_row_hubs,
    ),
    (
        "p0-threshold-floor",
        "#102",
        "每个 P0 模板的 threshold 必须 ≥ 0.85（调研 §5.6 的 0.80 硬下限 + 0.05 余量）："
        "调松阈值是假阳的起点（本仓 0.470 事故的同类）；C4 抓不到「负例本来就低」的调松",
        probe_p0_threshold_floor,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（删 roi、roi 放宽吃掉兄弟、roi 放宽 + 放宽阈值吃负例、删 order_by、
#          模板换错文件、删 OCR 兜底、断掉一处接线、偷偷多接一处 NEW、
#          ★#102 四个枢纽：摘掉模板项 / 把模板项挪到 OCR 版之后★、
#          ★P0-3：阈值 0.4 / 删 OCR 兜底 / 删模板资产 / 双通道只剩一条 / 删模板叶 / 删 roi★）
# ---------------------------------------------------------------------------
def _tmp_root(mutate_pipeline=None, mutate_templates=None) -> Path:
    """复制 ``assets/resource/{pipeline,image}`` 到临时根，按需改动，返回临时根。

    破坏实验走**临时副本**（同 ``hooks_7`` / ``hooks_108`` 的手法）：真源与真数据一个字节都不动，
    但守卫读的是「真的会被读的那份配置 / 那张图」。
    """
    tmp = Path(tempfile.mkdtemp(prefix="hooks102_"))
    drift = _drift()
    dst_pipe = tmp / "assets" / "resource" / "pipeline"
    dst_pipe.mkdir(parents=True)
    for path in sorted(PIPELINE_DIR.glob("*.json")):
        data = drift._load_jsonc(path)
        if mutate_pipeline is not None and isinstance(data, dict):
            mutate_pipeline(path.name, data)
        with (dst_pipe / path.name).open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
    dst_img = tmp / "assets" / "resource" / "image"
    shutil.copytree(IMAGE_DIR, dst_img)
    if mutate_templates is not None:
        mutate_templates(dst_img)
    return tmp


def prove_red() -> bool:
    print("hooks_102 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_p0_roi_scoped()
        and probe_p0_order_by_score()
        and probe_p0_threshold_floor()
        and probe_p0_projection_synced()
        and probe_p0_frame_no_false_positive()
        and probe_p0_archive_scores_match_measured()
        and probe_p0_template_pixels_from_evidence()
        and probe_p0_wiring_declared()
        and probe_p0_stone_row_hubs()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：九个契约全绿")
    if not green:
        for m in (
            _roi_scoped_failures()
            + _order_by_failures()
            + _threshold_floor_failures()
            + _projection_failures()
            + _frame_failures()
            + _archive_failures()
            + _pixel_failures()
            + _wiring_failures()
            + _stone_hub_failures()
        ):
            print(f"      - {m}")
        return False

    T = _templates()
    checks: list[bool] = []

    def _case(name: str, mutate, expect) -> None:
        """跑一个 pipeline 破坏实验：``expect(root)`` 返回失败列表。"""
        tmp = _tmp_root(mutate)
        try:
            msgs = expect(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

    def _with_temp_truth(images: dict, fn) -> list[str]:
        """临时替换 ``scene.templates.TEMPLATES`` 里的真源条目（内存），跑 ``fn()``，然后**一定**恢复。

        ★必须改 ``TEMPLATES`` 字典本身★：守卫全部遍历 ``T.TEMPLATES``（而不是逐个模块属性），
        只换 ``T.STONE_ICON`` 这类属性对守卫没有任何影响（那样破坏实验会假绿）。
        """
        saved = {k: T.TEMPLATES[k] for k in images}
        try:
            for k, v in images.items():
                T.TEMPLATES[k] = v
            return fn()
        finally:
            for k, v in saved.items():
                T.TEMPLATES[k] = v

    def _replace(spec, **changes):
        """:class:`scene.templates.TemplateSpec` 的不可变副本（frozen dataclass 用 replace）。"""
        import dataclasses  # noqa: PLC0415

        return dataclasses.replace(spec, **changes)

    def _truth_case(name: str, images: dict, fn) -> None:
        msgs = _with_temp_truth(images, fn)
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

    # ① 删掉模板节点的 roi（= #108 修之前的形态）→ C1 红 + C3 红
    def _drop_stone_roi(fname, data):
        if fname == "common.json":
            data[T.NODE_STONE_ICON]["recognition"]["param"].pop("roi", None)

    _case("删掉 PubStaminaStoneIcon 的 roi", _drop_stone_roi, lambda root: _roi_scoped_failures(root))
    _case("删掉 PubStaminaStoneIcon 的 roi → 真源⇄投影不一致", _drop_stone_roi, lambda root: _projection_failures(root))

    # ② 把「否」的 roi 放宽到覆盖兄弟按钮 → C1 红（兄弟整窗进了候选池）
    def _widen_no_roi(fname, data):
        if fname == "wuchong.json":
            data[T.NODE_BONUS_NO_TPL]["recognition"]["param"]["roi"] = [0, 760, 700, 140]

    _case("「否」的 roi 放宽到 [0,760,700,140]（兄弟按钮重新进候选池）", _widen_no_roi,
          lambda root: _roi_scoped_failures(root))
    _case("「否」的 roi 放宽 → 真源⇄投影不一致", _widen_no_roi, lambda root: _projection_failures(root))

    # ③ ★放宽阈值 + 放宽 roi = 吃掉负例★：星导石模板对 ark62 的【首次报酬】彩虹球
    #   全屏灰 0.7734 / 彩 0.8014；roi 放到全屏 + 阈值降到 0.70 → 负例真被命中（C4 红）。
    _truth_case(
        "星导石 roi 全屏 + 阈值 0.70（吃掉 ark62 首次报酬的彩虹球）",
        {T.STONE_ICON.key: _replace(T.STONE_ICON, roi=(0, 0, 720, 1280), threshold=0.70)},
        _frame_failures,
    )

    # ④ 删掉 order_by（回到默认 Horizontal = 最左）→ C2 红
    def _drop_order_by(fname, data):
        if fname == "common.json":
            data[T.NODE_STONE_ICON]["recognition"]["param"].pop("order_by", None)

    _case("删掉 PubStaminaStoneIcon 的 order_by（回到默认 Horizontal）", _drop_order_by,
          lambda root: _order_by_failures(root))

    # ⑤ 模板换错文件：「否」节点指向「是」的模板 → C3 红（投影不一致）+ C4 红（正例 miss）
    def _swap_template(fname, data):
        if fname == "wuchong.json":
            data[T.NODE_BONUS_NO_TPL]["recognition"]["param"]["template"] = [T.BONUS_YES.template]

    _case("「否」节点的模板换成「是」那张", _swap_template, lambda root: _projection_failures(root))
    _truth_case(
        "真源里「否」的模板换成「是」那张 → 正例帧 roi 内找不到",
        {T.BONUS_NO.key: _replace(T.BONUS_NO, template=T.BONUS_YES.template)},
        _frame_failures,
    )

    # ⑥ 删掉 OCR 兜底叶 → C3 红（「双通道」只剩一条）
    def _drop_ocr(fname, data):
        if fname == "wuchong.json":
            data.pop(T.NODE_BONUS_NO_OCR, None)

    _case("删掉 WuchongBonusNoBtnOcr（OCR 兜底）", _drop_ocr, lambda root: _projection_failures(root))

    # ⑥b Or 的顺序反过来（OCR 在前 = 模板通道永不生效）→ C3 红
    def _reverse_or(fname, data):
        if fname == "common.json":
            param = data[T.NODE_STONE_ROW]["recognition"]["param"]
            param["any_of"] = list(reversed(param["any_of"]))

    _case("PubStaminaStoneRow 的 any_of 顺序反过来（OCR 抢在模板前）", _reverse_or,
          lambda root: _projection_failures(root))

    # ⑦ 模板换成别的像素（拿一张 maze 横幅盖进裁片路径）→ C6 红
    other = IMAGE_DIR / "maze" / "domain_beng_banner.png"
    if other.is_file():
        tmp_img = Path(tempfile.mkdtemp(prefix="hooks102_img_"))
        try:
            shutil.copytree(IMAGE_DIR, tmp_img / "image")
            shutil.copyfile(other, tmp_img / "image" / T.STONE_ICON.template)
            msgs = _pixel_failures(tmp_img / "image")
        finally:
            shutil.rmtree(tmp_img, ignore_errors=True)
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] 模板文件换成别的像素（maze 横幅）-> {'红' if red else '仍绿'}"
              + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)
    else:
        print("  [SKIP] 模板像素破坏实验：缺 assets/resource/image/maze/domain_beng_banner.png")

    # ⑧ 断掉一处接线（删掉 SideClearEntry 里的模板引用）→ C7 红
    def _drop_wire(fname, data):
        if fname == "side_story.json":
            nxt = (data.get("SideClearEntry") or {}).get("next")
            if isinstance(nxt, list) and T.STONE_TPL_REF in nxt:
                nxt.remove(T.STONE_TPL_REF)

    _case("删掉 SideClearEntry 里的 [JumpBack]PubStaminaUseStoneTpl", _drop_wire,
          lambda root: _wiring_failures(root))

    # ⑨ 把模板引用挪到候选列表末尾（OCR 版之前 → 之后）→ C7 红
    def _reorder_wire(fname, data):
        if fname != "side_story.json":
            return
        for hub in ("SideStoryEntry", "SideClearEntry"):
            nxt = (data.get(hub) or {}).get("next")
            if isinstance(nxt, list) and T.STONE_TPL_REF in nxt:
                nxt.remove(T.STONE_TPL_REF)
                nxt.append(T.STONE_TPL_REF)

    _case("把模板引用挪到候选列表末尾（掉到 OCR 版之后）", _reorder_wire, lambda root: _wiring_failures(root))

    # ⑩ 偷偷给 NEW 徽标再接一处（声明只写 SpecialNewBadgeTpl）→ C7 红
    #    （模板可以共享，但「几处用这张裁片」必须与 scene/templates.py 的 NEW_BADGE_NODES 对账）
    def _sneak_badge(fname, data):
        if fname == "common.json":
            data["PubSneakBadge"] = {
                "recognition": {
                    "type": "TemplateMatch",
                    "param": {
                        "template": [T.NEW_BADGE.template],
                        "threshold": T.NEW_BADGE.threshold,
                        "roi": list(T.NEW_BADGE.roi),
                        "order_by": "Score",
                    },
                }
            }

    _case("偷偷给 NEW 徽标再接一处（声明只写了 SpecialNewBadgeTpl）", _sneak_badge,
          lambda root: _wiring_failures(root))

    # ⑬ ★P0-3 的验收破坏实验（票面点名的三项 + 双通道只剩一条）★

    # (a) 阈值调到 0.4 → 负例 0.7615 直接穿过 → C4 红
    #     （本仓血泪：0.470 仍被选中过；把阈值当「调松一点更稳」就是假阳的起点）
    _truth_case(
        "把 NEW 徽标阈值调到 0.4（负例最高 0.7615 直接穿过）",
        {T.NEW_BADGE.key: _replace(T.NEW_BADGE, threshold=0.4)},
        _frame_failures,
    )
    # (a2) 同一个 0.4 也要被 C9 的**绝对门槛**抓住：C4 只能抓「负例 ≥ 当前阈值」，
    #      星导石负例最高 0.2779 —— 把阈值调到 0.50 时 C4 不会红，C9 会。
    _truth_case(
        "把 NEW 徽标阈值调到 0.4 → 低于 P0 绝对门槛 0.85",
        {T.NEW_BADGE.key: _replace(T.NEW_BADGE, threshold=0.4)},
        _threshold_floor_failures,
    )

    # (b) 删掉 OCR 兜底叶 → C3 红（双通道只剩模板一条；模板一旦漏检就静默不再识别）
    def _drop_badge_ocr(fname, data):
        if fname == T.NEW_BADGE_NODE_FILE:
            data.pop(T.NODE_NEW_BADGE_OCR, None)

    _case("删掉 SpecialNewBadgeOcr（NEW 徽标的 OCR 兜底）", _drop_badge_ocr,
          lambda root: _projection_failures(root))

    # (b2) 把 OCR 从 any_of 里摘掉（节点还在，但双通道只剩一条）→ C3 红
    def _badge_single_channel(fname, data):
        if fname == T.NEW_BADGE_NODE_FILE:
            data[T.NODE_NEW_BADGE]["recognition"]["param"]["any_of"] = [T.NODE_NEW_BADGE_TPL]

    _case("SpecialNewBadge 的 any_of 只剩模板叶（OCR 兜底被摘掉）", _badge_single_channel,
          lambda root: _projection_failures(root))

    # (c) 删掉模板资产 → C6 红（连「模板存在且逐像素可复核」都没有了）
    tmp_img = Path(tempfile.mkdtemp(prefix="hooks102_asset_"))
    try:
        shutil.copytree(IMAGE_DIR, tmp_img / "image")
        (tmp_img / "image" / T.NEW_BADGE.template).unlink()
        msgs = _pixel_failures(tmp_img / "image")
    finally:
        shutil.rmtree(tmp_img, ignore_errors=True)
    red = len(msgs) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 删掉模板资产 {T.NEW_BADGE.template} -> {'红' if red else '仍绿'}"
          + (f"  {msgs[0]}" if msgs else ""))
    checks.append(red)

    # (d) 删掉 NEW 模板叶节点（Or 指向一个不存在的名字）→ C7 红（声明与现状不符）
    def _drop_badge_tpl(fname, data):
        if fname == T.NEW_BADGE_NODE_FILE:
            data.pop(T.NODE_NEW_BADGE_TPL, None)

    _case("删掉 SpecialNewBadgeTpl（声明仍写已接线的模板叶）", _drop_badge_tpl,
          lambda root: _wiring_failures(root))

    # (e) 删掉 NEW 模板叶的 roi（回到全屏候选池）→ C1 红
    def _drop_badge_roi(fname, data):
        if fname == T.NEW_BADGE_NODE_FILE:
            data[T.NODE_NEW_BADGE_TPL]["recognition"]["param"].pop("roi", None)

    _case("删掉 SpecialNewBadgeTpl 的 roi（全屏 = 兄弟控件重回候选池）", _drop_badge_roi,
          lambda root: _roi_scoped_failures(root))

    # ⑪ ★本票的验收破坏实验★：把某个枢纽（AbyssEntry）的模板优先项摘掉 → C8 红
    #    （= 那条链又只能靠行名 OCR 判据 → #102 说的「四个枢纽未接」复发）
    def _drop_hub_wire(fname, data):
        if fname != "abyss.json":
            return
        nxt = (data.get("AbyssEntry") or {}).get("next")
        if isinstance(nxt, list) and T.STONE_TPL_REF in nxt:
            nxt.remove(T.STONE_TPL_REF)

    _case("把 AbyssEntry 的模板优先项摘掉（四个枢纽又缺一个）", _drop_hub_wire,
          lambda root: _stone_hub_failures(root))

    # ⑫ 把某个枢纽（SpecialEntry）的模板项挪到 OCR 版**之后** → 模板通道永远轮不到 → C8 红
    def _reorder_hub_wire(fname, data):
        if fname != "special_dungeon.json":
            return
        nxt = (data.get("SpecialEntry") or {}).get("next")
        if not isinstance(nxt, list) or T.STONE_TPL_REF not in nxt:
            return
        nxt.remove(T.STONE_TPL_REF)
        ocr_ref = f"[JumpBack]{T.NODE_USE_STONE_OCR}"
        nxt.insert(nxt.index(ocr_ref) + 1 if ocr_ref in nxt else len(nxt), T.STONE_TPL_REF)

    _case("把 SpecialEntry 的模板项挪到 OCR 版之后（模板优先不成立）", _reorder_hub_wire,
          lambda root: _stone_hub_failures(root))

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
