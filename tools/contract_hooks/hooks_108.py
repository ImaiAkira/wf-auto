# -*- coding: utf-8 -*-
"""#108：``AutoSwitchLabel`` 缺 ``roi`` + 默认 ``order_by`` → 真机必点错「自动续战」。

## 机制（协议语义，不是推测；行号指本仓离线镜像 ``.research/3.1-pipeline.md``）

* ``TemplateMatch.threshold`` 是**入闸门**（「这个位置算不算命中」），**不是「取最高分」**（`:497-499`）。
* 多结果时选哪个由 ``order_by`` + ``index`` 决定：**默认 ``Horizontal`` + ``0`` = 最左**（`:501-508`）。
* ``roi`` 缺省 = 全屏（``[0,0,0,0]``，`:471-474`）⇒ 全屏候选池 = 把**同排兄弟控件**「自动续战」
  也放进池子。

## 真机实测（两张**已入库**帧；720 空间，1080 原图 LANCZOS 下采样，灰度 ZNCC = ``TM_CCOEFF_NORMED``）

| 帧（原图尺寸） | 真「自动」 | 假「自动续战」 | 阈值 0.75 |
|---|---|---|---|
| ``tools/frames/lord_team_page.png``（1080x1920） | **1.0000 @(142,1062)** | **0.8964 @(17,1062)** | 两者都过 |
| ``tools/frames/side_team_page.png``（1080x1920） | **1.0000 @(142,1062)** | **0.8964 @(17,1062)** | 两者都过 |

⇒ 全屏 + 默认排序 = 取 x=17（**错的**）。这正是 ``scene/auto_switch.py`` 记的 ``box=[17,1062,43,26]``
那次误点 —— 不需要「阈值调高」就能解释，也不该靠调阈值修（见该模块 ``AUTO_TEMPLATE_THRESHOLD``）。

## 契约

* **T1 ``template-match-roi-required``** —— 每个 ``TemplateMatch`` 节点都必须写 ``roi``；
  缺省 / 非四整数 / ``w|h <= 0``（协议里 0 = 延伸到边缘）/ 等于全屏，**一律算没有 roi**，点名节点。
* **T2 ``template-match-order-by-explicit``** —— 多结果 / 多模板的 ``TemplateMatch`` 必须显式
  ``order_by``：多模板 = ``template`` 不止一张（默认排序会**跨模板取最左**，而不是最匹配的那张）；
  多结果 = 登记在 :data:`MULTI_RESULT_EVIDENCE` 里、且**被 T4 实测复核过**的节点。
* **T3 ``auto-label-projection-synced``** —— ADR-0001：``scene/auto_switch.py`` 是**真源**，
  ``common.json::AutoSwitchLabel`` 是**手写投影**；``template`` / ``threshold`` / ``roi`` /
  ``order_by`` 必须**逐项相等**。另外钉住 OCR 兜底**不变**：``AUTO_LABEL_PATTERNS`` 仍是**整串**
  锚定（裸「自动」会命中「自动续战」）。
* **T4 ``auto-label-no-sibling-pick``** —— 用真机帧滑窗算 ZNCC（框架的做法，不是点测一个框）：
  ① 全屏候选**确实 ≥2 个**且默认排序取到兄弟（= 假阳前提仍在，守卫没退化成空转）；
  ② 兄弟窗口分数 ≥ :data:`SIBLING_MIN`（危险量级没变）；
  ③ 投影的 ``roi`` **不覆盖**兄弟窗口；
  ④ 按投影语义（roi 内候选 + ``order_by`` + ``index:0``）选出来**必须**是真「自动」框；
  ⑤ 负例帧（战斗页 / 弹窗 / 空列表）在 roi 内**一个都不许命中**。

## 本票**不改**、但必须点名（边界：``agent/*`` 与别的守卫不在本票范围）

* ``agent/auto_switch_impl.py`` 里有同样的**模板参数快照**（``_AUTO_LABEL_TEMPLATES_SNAPSHOT`` /
  ``_AUTO_TEMPLATE_THRESHOLD_SNAPSHOT`` / ``_AUTO_TEMPLATE_NODE_SNAPSHOT``）。本票**没有**改阈值、
  没有改模板列表 ⇒ 快照仍逐项一致（``hooks_auto_outside.auto-outside-snapshot-pinned`` 继续绿）。
  新增的 ``AUTO_LABEL_ROI`` / ``AUTO_ORDER_BY`` **只投影到 pipeline**（roi 由框架自己裁，agent 不读），
  故**不进快照**；真要进快照是另一张票。
* ``hooks_auto_outside.auto-outside-template-distinct`` 的兄弟窗口写在 ``x=18``（``CONT_BOX_720``，
  真机 OCR 框位置）：实测 **x=17 是 0.8964、x=18 只有 0.4536** ⇒ 那条守卫是「点测了一个偏 1px
  的框」才绿的；框架做的是**滑窗**，会跑到 x=17。本票用滑窗口径把这件事钉在这里（本票不改那张
  守卫，见报告）。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
IMAGE_DIR = REPO_ROOT / "assets" / "resource" / "image"

#: 被本票改的那个节点（真源 ``scene.auto_switch.AUTO_TEMPLATE_NODE``，改名前两边一起改）。
NODE_FILE = "common.json"
NODE_NAME = "AutoSwitchLabel"

#: 正例帧（**已入库**，1080x1920 原图 → 720 基准空间 LANCZOS）。两张来自不同页面/不同会话：
#: 领主战成员编队页 / 外传编队页 —— 「自动」标签都在同一处 (142,1062)。
POSITIVE_FRAMES: tuple[str, ...] = (
    "tools/frames/lord_team_page.png",
    "tools/frames/side_team_page.png",
)

#: 负例帧（**已入库**，720）：战斗页（同屏另有战斗 HUD 的「自动」，位置完全不同）/ 弹窗 / 空列表。
NEGATIVE_FRAMES: tuple[str, ...] = (
    "tools/frames/auto_battle_hud_hit.png",
    "tools/frames/stamina_insufficient_wuchong384.png",
    "tools/frames/side_story_list_empty.png",
)

#: 真「自动」标签的**最佳对齐窗口**（720 空间 ``(x, y, w, h)``）—— 两张正例帧都是 1.0000。
AUTO_WINDOW: tuple[int, int, int, int] = (142, 1062, 43, 26)
#: 同排兄弟「自动续战」的**最佳对齐窗口**（720）—— 0.8964，**高于**阈值 0.75。
#: ★注意 x=17 是尖峰★：x=18 只有 0.4536（这就是「点测会骗人」的地方，见模块 docstring 末）。
SIBLING_WINDOW: tuple[int, int, int, int] = (17, 1062, 43, 26)
#: 兄弟「自动续战」的**真机 OCR 框**（720；同 ``hooks_auto_outside.CONT_BOX_720`` 的来源
#: ``[18,1062,79,24]``）→ 它的右边界是 **97**。roi 左边界要越过这条线才算「把整栏排除」，
#: 只越过 60（= 窗口右边）不够：那还留着「续战」两个字在候选池里。
SIBLING_LABEL_RIGHT = 18 + 79

#: 正例/兄弟/负例的验收线（都留余量；数字来自本文件实测，帧或模板一换就该重新标定）。
POSITIVE_MIN = 0.99
SIBLING_MIN = 0.85
NEGATIVE_MAX = 0.60

#: 候选去重半径（逐次取最大 + 抑制邻域，与 ``docs/research/recognition-ocr-vs-template.md``
#: §5.2 同口径）。协议没写框架的去重半径，但结论只依赖「x=17 与 x=142 相距 125px」，
#: 任何 ≥26px 的半径都不改变结论。
PEAK_RADIUS = 20

#: 「多结果风险」登记表：实测**同一帧里 ≥threshold 的候选不止一个**的节点 ⇒ 必须显式 ``order_by``。
#: 登记不是免罪牌：:func:`_false_positive_failures` 每次都按帧复核这条证据，帧/模板一变就红
#: （逼人重新标定，而不是把登记表放烂）。
MULTI_RESULT_EVIDENCE: dict[str, str] = {
    "common.json::AutoSwitchLabel": (
        "同一帧实测 2 个 ≥threshold 候选：真「自动」1.0000@(142,1062) / 假「自动续战」"
        "0.8964@(17,1062)（lord_team_page.png 与 side_team_page.png 两帧一致）"
    ),
}


# ---------------------------------------------------------------------------
# 路径 / 惰性导入（与同目录其它 hooks 同一手法）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _submodule(name: str):
    """取 ``scene.<name>`` **子模块**（别用 ``from scene import <name>``：``scene/__init__``
    把同名**函数**导出到了包上，属性会被遮蔽成函数，拿不到模块）。"""
    _paths()
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"scene.{name}")


def _drift():
    _paths()
    import scene.drift as drift  # noqa: PLC0415

    return drift


def _pixels():
    return _submodule("pixels")


def _repo(root: Path | None = None) -> Path:
    return Path(root) if root is not None else REPO_ROOT


def _pipelines(root: Path | None = None) -> dict[str, dict]:
    """``{文件名: 顶层对象}``（JSONC）。``root`` 指向临时副本时只影响 pipeline 的读取。"""
    drift = _drift()
    base = _repo(root) / "assets" / "resource" / "pipeline"
    out: dict[str, dict] = {}
    for path in sorted(base.glob("*.json")):
        data = drift._load_jsonc(path)
        out[path.name] = data if isinstance(data, dict) else {}
    return out


def _node_param(root: Path | None = None) -> dict | None:
    """``common.json::AutoSwitchLabel`` 的 recognition.param（读不到返回 None）。"""
    data = _pipelines(root).get(NODE_FILE) or {}
    node = data.get(NODE_NAME)
    if not isinstance(node, dict):
        return None
    rec = node.get("recognition")
    if not isinstance(rec, dict):
        return None
    param = rec.get("param")
    return param if isinstance(param, dict) else None


# ---------------------------------------------------------------------------
# T1：每个 TemplateMatch 节点都必须写 roi
# ---------------------------------------------------------------------------
def _template_matches(rec, where: str, out: list) -> None:
    """递归收集 ``TemplateMatch`` 的 ``(where, param)``（``And`` / ``Or`` 的内联叶也算）。"""
    if not isinstance(rec, dict):
        return
    kind = rec.get("type")
    param = rec.get("param") or {}
    if kind == "TemplateMatch":
        out.append((where, param if isinstance(param, dict) else {}))
    if kind in ("And", "Or"):
        key = "all_of" if kind == "And" else "any_of"
        for i, leaf in enumerate(param.get(key) or []):
            if isinstance(leaf, dict):
                _template_matches(leaf, f"{where}:{key}[{i}]", out)


def _all_template_matches(root: Path | None = None) -> list[tuple[str, dict]]:
    """全仓（13 个 pipeline 文件）的 ``TemplateMatch`` 节点清单。"""
    out: list[tuple[str, dict]] = []
    for fname, data in _pipelines(root).items():
        for node_name, spec in data.items():
            if isinstance(spec, dict):
                _template_matches(spec.get("recognition"), f"{fname}::{node_name}", out)
    return out


def _roi_missing_reason(param: dict) -> str | None:
    """``None`` = 有**有效** roi；否则返回「为什么等于没有 roi」。"""
    path = _pixels()
    if "roi" not in param:
        return "没有 roi（协议缺省 [0,0,0,0] = 全屏，候选池 = 整屏）"
    roi = param.get("roi")
    if isinstance(roi, str):
        return f"roi 是节点/锚点引用（{roi!r}）—— 本节点是被 run_recognition 直接调用的入口，没有前置节点，引用必然空"
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


def _roi_required_failures(root: Path | None = None) -> list[str]:
    msgs: list[str] = []
    for where, param in _all_template_matches(root):
        why = _roi_missing_reason(param)
        if why:
            msgs.append(
                f"{where}：{why} —— TemplateMatch 必须写 roi（#108：全屏 = 把同排兄弟控件"
                f"「自动续战」也放进候选池，而默认 order_by:Horizontal 取最左 → 必点错）"
            )
    return msgs


def probe_template_match_roi_required() -> bool:
    """T1：所有 ``TemplateMatch`` 节点都有**有效** roi（缺省/全屏/零尺寸都算没有）。"""
    return _roi_required_failures() == []


# ---------------------------------------------------------------------------
# T2：多结果 / 多模板的 TemplateMatch 必须显式 order_by
# ---------------------------------------------------------------------------
def _order_by_failures(root: Path | None = None) -> list[str]:
    found = dict(_all_template_matches(root))
    msgs: list[str] = []
    for where, param in found.items():
        tpl = param.get("template")
        multi_tpl = isinstance(tpl, (list, tuple)) and len(tpl) > 1
        registered = where in MULTI_RESULT_EVIDENCE
        if not (multi_tpl or registered):
            continue
        if param.get("order_by") is not None:
            continue
        if multi_tpl:
            why = (
                f"有 {len(tpl)} 张模板 —— 默认 Horizontal 会**跨模板**取最左，"
                f"而不是最匹配的那一张（想要「最像」就写 \"Score\"）"
            )
        else:
            why = f"已登记为多结果风险（{MULTI_RESULT_EVIDENCE[where]}）"
        msgs.append(f"{where}：没有显式 order_by —— {why}")
    for where in MULTI_RESULT_EVIDENCE:
        if where not in found:
            msgs.append(
                f"MULTI_RESULT_EVIDENCE 登记的 {where} 在 pipeline 里找不到（节点被删/改名）—— "
                f"对账后删除或更新登记，别让登记表锈在一边"
            )
    return msgs


def probe_template_match_order_by_explicit() -> bool:
    """T2：多模板 / 已实测多结果的 ``TemplateMatch`` 都显式写了 ``order_by``。"""
    return _order_by_failures() == []


# ---------------------------------------------------------------------------
# T3：真源（scene/auto_switch.py）⇄ 投影（common.json::AutoSwitchLabel）逐项一致
# ---------------------------------------------------------------------------
def _ocr_fallback_failures(cfg=None) -> list[str]:
    """OCR 兜底必须**不变**：整串锚定（裸/半锚定会命中「自动续战」）。"""
    cfg = cfg or _submodule("auto_switch")
    msgs: list[str] = []
    pats = getattr(cfg, "AUTO_LABEL_PATTERNS", ())
    if not pats:
        return ["AUTO_LABEL_PATTERNS 为空 —— 「自动」定位没有 OCR 兜底了（#108 要求保留）"]
    for p in pats:
        if not (p.startswith("^") and p.endswith("$")):
            msgs.append(
                f"OCR 兜底不是整串锚定：{p!r} —— 裸/半锚定会命中「自动续战」"
                f"（真机事故：WuchongResume 的裸「续战」把「自动续战」点掉了）"
            )
    if not any(re.search(p, cfg.AUTO_LABEL) for p in pats):
        msgs.append(f"OCR 兜底锚不住「{cfg.AUTO_LABEL}」本身：{list(pats)!r}")
    for bad in ("自动续战", "自动战斗", "技能自动", "自动续战功能"):
        for p in pats:
            if re.search(p, bad):
                msgs.append(f"OCR 兜底放宽过头：{p!r} 会命中『{bad}』（整串锚定被破坏）")
                break
    return msgs


def _projection_pairs(cfg) -> tuple[tuple[str, object], ...]:
    """投影必须逐项等于的真源值（加字段/改字段名就在这里改，别在别处抄第二份）。"""
    return (
        ("template", list(cfg.AUTO_LABEL_TEMPLATES)),
        ("threshold", cfg.AUTO_TEMPLATE_THRESHOLD),
        ("roi", list(cfg.AUTO_LABEL_ROI)),
        ("order_by", cfg.AUTO_ORDER_BY),
    )


def _projection_failures(root: Path | None = None) -> list[str]:
    cfg = _submodule("auto_switch")
    where = f"{NODE_FILE}::{NODE_NAME}"
    param = _node_param(root)
    if param is None:
        return [f"{where} 不存在或没有 recognition.param（模板入口节点被删/改名）"]
    msgs: list[str] = [
        f"{where} 真源⇄投影不一致：{key} 投影={param.get(key)!r} 真源={want!r}"
        f"（ADR-0001：scene/auto_switch.py 是真源，pipeline 是手写投影；两处必须一起改）"
        for key, want in _projection_pairs(cfg)
        if param.get(key) != want
    ]
    node = ((_pipelines(root).get(NODE_FILE) or {}).get(NODE_NAME) or {})
    if ((node.get("recognition") or {}).get("type")) != "TemplateMatch":
        msgs.append(
            f"{where} 的 recognition.type 不是 TemplateMatch（实际 "
            f"{((node.get('recognition') or {}).get('type'))!r}）—— 模板入口的定位语义被换掉了"
        )
    msgs.extend(_ocr_fallback_failures(cfg))
    return msgs


def probe_auto_label_projection_synced() -> bool:
    """T3：``common.json::AutoSwitchLabel`` 的 template/threshold/roi/order_by 逐项等于
    ``scene.auto_switch`` 真源；OCR 兜底仍是整串 ``^自动$``。"""
    return _projection_failures() == []


# ---------------------------------------------------------------------------
# T4：真机帧假阳用例（滑窗口径 = 框架的做法）
# ---------------------------------------------------------------------------
def _np():
    """numpy —— 本守卫唯一的第三方依赖（**纯 numpy**，不引 scipy：``tools/requirements.txt``
    里没有它，同在 ``tools/contract_hooks/`` 的 ``hooks_57`` 也是手搓 FFT 卷积）。"""
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


def _frame_720(rel: str):
    """读一帧并按 `scene.pixels` 口径归一：非 720 原图用 LANCZOS 下采样到 720x1280。

    ★口径★：本仓模板 ``auto/switch_label.png`` 就是「1080 原图 LANCZOS 下采样到 720」的裁片
    （调研 §5.2 第一步：与 LANCZOS 裁片逐像素差 0.00 / BILINEAR 4.75 / NEAREST 7.80），
    所以离线分数只有锁定「720 空间 + LANCZOS」才和框架可比。
    """
    from PIL import Image  # noqa: PLC0415

    path = _pixels()
    im = Image.open(REPO_ROOT / rel)
    if im.size != (path.BASE_W, path.BASE_H):
        im = im.resize((path.BASE_W, path.BASE_H), Image.LANCZOS)
    return im.convert("RGB")


def _gray(img):
    np = _np()
    return np.asarray(img.convert("L"), dtype=np.float64)


def _conv_valid(f, k):
    """二维**互相关**的 ``mode="valid"`` 结果（FFT，纯 numpy）：
    ``out[y, x] = Σ_{u,v} f[y+u, x+v] · k[u, v]``；``k`` 比 ``f`` 大时抛 ``ValueError``。

    推导（别乱改下标）：频域相乘 = **线性卷积**。令 ``k' = k[::-1, ::-1]``，
    ``conv(f, k')[a, b] = Σ_{i,j} f[i,j]·k[h-1-a+i, w-1-b+j]`` ⇒ 与
    ``out[y,x] = Σ_{i,j} f[i,j]·k[i-y, j-x]`` 对齐需要 ``a = y+h-1``、``b = x+w-1``
    ⇒ valid 段从 ``(h-1, w-1)`` 起。
    """
    np = _np()
    big_h, big_w = f.shape
    h, w = k.shape
    if h > big_h or w > big_w:
        raise ValueError(f"模板 {k.shape} 比帧 {f.shape} 还大")
    sh, sw = big_h + h - 1, big_w + w - 1
    # 零填充到 (sh, sw) 后，循环卷积 == 线性卷积。
    full = np.fft.irfft2(np.fft.rfft2(f, s=(sh, sw)) * np.fft.rfft2(k, s=(sh, sw)), s=(sh, sw))
    return full[h - 1:h - 1 + (big_h - h + 1), w - 1:w - 1 + (big_w - w + 1)]


def _zncc_map(frame_rgb, tpl_gray):
    """``TM_CCOEFF_NORMED`` 的**全滑窗**分数图（形状 ``(H-h+1, W-w+1)``，与框架同度量）。"""
    np = _np()
    f = _gray(frame_rgb)
    tz = tpl_gray - tpl_gray.mean()
    h, w = tpl_gray.shape
    ones = np.ones((h, w), dtype=np.float64)
    num = _conv_valid(f, tz[::-1, ::-1])
    s1 = _conv_valid(f, ones[::-1, ::-1])
    s2 = _conv_valid(f * f, ones[::-1, ::-1])
    var = s2 - s1 * s1 / float(h * w)
    den = np.sqrt(np.maximum(var, 1e-12) * float((tz * tz).sum()))
    return num / np.maximum(den, 1e-12)


def _peaks(scores, min_score: float, radius: int = PEAK_RADIUS, limit: int = 20) -> list[tuple[float, int, int]]:
    """逐次取全局最大 + 抑制邻域 → ``[(score, x, y)]``（``x``/``y`` 是模板左上角，720 空间）。"""
    np = _np()
    s = scores.copy()
    out: list[tuple[float, int, int]] = []
    for _ in range(limit):
        idx = int(np.argmax(s))
        y, x = divmod(idx, s.shape[1])
        value = float(s[y, x])
        if value < min_score:
            break
        out.append((round(value, 4), int(x), int(y)))
        s[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1] = -1.0
    return out


def _select(cands, order_by, index: int = 0):
    """按 MaaFramework 的语义从候选取一个（**未写 order_by → 默认 Horizontal**）。"""
    if not cands:
        return None
    ob = (order_by or "Horizontal").lower() if isinstance(order_by, str) else "horizontal"
    if ob == "score":
        ordered = sorted(cands, key=lambda c: (-c[0], c[2], c[1]))
    elif ob == "vertical":
        ordered = sorted(cands, key=lambda c: (c[2], c[1], -c[0]))
    else:  # horizontal / random / 未知一律按默认（Horizontal）处理：x 升序
        ordered = sorted(cands, key=lambda c: (c[1], c[2], -c[0]))
    if not -len(ordered) <= index < len(ordered):
        return None
    return ordered[index]


def _inside(roi, window) -> bool:
    """窗口是否**完整**落在 roi 内（走真源 :func:`scene.auto_switch.box_fully_inside`）。"""
    return _submodule("auto_switch").box_fully_inside(roi, window)


def _max_inside(scores, roi, tpl_shape) -> tuple[float, int, int] | None:
    """roi 内（要求整窗在内）的最高分位置；roi 太小放不下一份模板时返回 None。"""
    if roi is None:
        return None
    h, w = tpl_shape
    x0, y0, rw, rh = roi
    sub = scores[y0:y0 + rh - h + 1, x0:x0 + rw - w + 1]
    if sub.size == 0:
        return None
    np = _np()
    idx = int(np.argmax(sub))
    yy, xx = divmod(idx, sub.shape[1])
    return (round(float(sub[yy, xx]), 4), int(x0 + xx), int(y0 + yy))


def _projection_roi(root: Path | None = None):
    """投影里**真正生效**的 roi（tuple）或 None（= 全屏）。T3 已钉住它 == 真源。"""
    param = _node_param(root)
    if not param:
        return None
    if _roi_missing_reason(param) is not None:
        return None
    return tuple(int(v) for v in param["roi"])


def _template_gray(cfg):
    from PIL import Image  # noqa: PLC0415

    rel = cfg.AUTO_LABEL_TEMPLATES[0]
    path = IMAGE_DIR / rel
    if not path.is_file():
        return None, rel
    return _gray(Image.open(path)), rel


def _false_positive_failures(root: Path | None = None) -> list[str]:
    missing = _deps_missing()
    if missing:
        return [missing]
    cfg = _submodule("auto_switch")
    tpl, rel = _template_gray(cfg)
    if tpl is None:
        return [f"模板裁片缺失：assets/resource/image/{rel}（没有裁片就没有假阳用例）"]
    thr = float(cfg.AUTO_TEMPLATE_THRESHOLD)
    tpl_h, tpl_w = tpl.shape
    roi = _projection_roi(root)
    param = _node_param(root) or {}
    order_by = param.get("order_by")
    msgs: list[str] = []

    for frame in POSITIVE_FRAMES:
        if not (REPO_ROOT / frame).is_file():
            msgs.append(f"正例帧缺失：{frame}（已入库的证据帧被删 → 假阳用例失效）")
            continue
        scores = _zncc_map(_frame_720(frame), tpl)
        cands = _peaks(scores, thr)

        # ① 假阳前提仍在：全屏 ≥2 个候选，且**默认排序**取到的是兄弟（复现 bug 的语义）。
        blind = _select(cands, "Horizontal", 0)
        if len(cands) < 2 or blind is None or not (
            abs(blind[1] - SIBLING_WINDOW[0]) <= 2 and abs(blind[2] - SIBLING_WINDOW[1]) <= 2
        ):
            msgs.append(
                f"{frame}：假阳前提不成立（全屏候选={cands[:3]}，默认 Horizontal 取到 {blind}）—— "
                f"帧/模板变了，请重新标定本守卫的 AUTO_WINDOW / SIBLING_WINDOW 与验收线"
            )

        # ② 兄弟窗口分数仍在危险量级。
        z_sib = float(scores[SIBLING_WINDOW[1], SIBLING_WINDOW[0]])
        if z_sib < SIBLING_MIN:
            msgs.append(
                f"{frame}：「自动续战」窗口 {list(SIBLING_WINDOW)} 的 ZNCC={z_sib:.4f} < {SIBLING_MIN}"
                f"（危险量级变了 → 重新标定，别让验收线失去意义）"
            )

        # ③ 投影的 roi 不许覆盖兄弟窗口（覆盖了 = 选哪个又取决于排序）。
        if roi is not None and _inside(roi, SIBLING_WINDOW):
            msgs.append(
                f"{frame}：投影 roi {list(roi)} **覆盖**了「自动续战」窗口 {list(SIBLING_WINDOW)}"
                f" —— roi 必须只框「自动」那一栏：左边界要 > {SIBLING_LABEL_RIGHT}"
                f"（「自动续战」标签右边界），至少也要 > {SIBLING_WINDOW[0] + SIBLING_WINDOW[2]}"
            )

        # ④ 按投影语义（roi 内候选 + order_by + index:0）选出来必须是真的「自动」。
        if roi is None:
            msgs.append(
                f"{frame}：投影没有有效 roi → 候选池 = 全屏，order_by 再对也只是碰巧对"
                f"（T1/T3 已点名；这里再钉一次：没有 roi 就没有本守卫的结论）"
            )
            continue
        inside = [
            c for c in cands
            if _inside(roi, (c[1], c[2], tpl_w, tpl_h))
        ]
        if len(inside) != 1:
            msgs.append(
                f"{frame}：roi {list(roi)} 内 ≥{thr} 的候选有 {len(inside)} 个 {inside[:4]} —— "
                f"期望**恰好 1 个**（「自动」那一栏），多了就会重新落到「排序决定选哪个」"
            )
        picked = _select(inside, order_by, 0)
        if picked is None or not (
            abs(picked[1] - AUTO_WINDOW[0]) <= 2 and abs(picked[2] - AUTO_WINDOW[1]) <= 2
        ):
            msgs.append(
                f"{frame}：按投影语义（roi {list(roi)} + order_by={order_by!r} + index 0）选到 "
                f"{picked}，不是真「自动」{list(AUTO_WINDOW[:2])}"
            )
        if picked is not None and abs(picked[1] - SIBLING_WINDOW[0]) <= 2:
            msgs.append(f"{frame}：选中了「自动续战」位置 {picked}（x≈{SIBLING_WINDOW[0]}）—— 这正是 #108 要修的误点")

    for frame in NEGATIVE_FRAMES:
        if not (REPO_ROOT / frame).is_file():
            msgs.append(f"负例帧缺失：{frame}（已入库的证据帧被删 → 假阳用例失效）")
            continue
        scores = _zncc_map(_frame_720(frame), tpl)
        best = _max_inside(scores, roi, tpl.shape) if roi is not None else None
        if best is None:
            continue  # 没有 roi 的情形已在上面的正例循环里点过名
        if best[0] >= thr:
            msgs.append(
                f"{frame}：roi {list(roi)} 内不该命中，却出现 {best[0]:.4f} ≥ 阈值 {thr} @({best[1]},{best[2]})"
            )
        elif best[0] > NEGATIVE_MAX:
            msgs.append(
                f"{frame}：roi 内最高分 {best[0]:.4f} > 负例上限 {NEGATIVE_MAX}（余量不足 "
                f"{thr - best[0]:.4f}）—— 负例余量应在 0.05 以上"
            )
    return msgs


def probe_auto_label_no_sibling_pick() -> bool:
    """T4：真机帧滑窗 —— roi 内候选唯一且是真「自动」，兄弟「自动续战」**绝不会被选中**；
    负例帧 roi 内不命中。"""
    return _false_positive_failures() == []


# ---------------------------------------------------------------------------
# 挂点
# ---------------------------------------------------------------------------
HOOKS = [
    (
        "template-match-roi-required",
        "#108",
        "每个 TemplateMatch 节点都必须写 roi（缺省/全屏/w|h≤0 都算没有）："
        "全屏 = 把同排兄弟控件放进候选池，而默认 order_by:Horizontal 取最左",
        probe_template_match_roi_required,
    ),
    (
        "template-match-order-by-explicit",
        "#108",
        "多模板 / 已实测多结果（MULTI_RESULT_EVIDENCE）的 TemplateMatch 必须显式 order_by："
        "threshold 只是入闸门，选哪个由 order_by + index 决定，默认 Horizontal 取最左",
        probe_template_match_order_by_explicit,
    ),
    (
        "auto-label-projection-synced",
        "#108",
        "真源⇄投影逐项一致：scene/auto_switch.py 的 template/threshold/roi/order_by == "
        "common.json::AutoSwitchLabel 的四个字段；OCR 兜底仍是整串 ^自动$",
        probe_auto_label_projection_synced,
    ),
    (
        "auto-label-no-sibling-pick",
        "#108",
        "真机帧滑窗（ZNCC）假阳用例：假「自动续战」0.8964@x=17 ≥ 阈值但落在 roi 外，"
        "按投影语义选出来必是真「自动」1.0000@(142,1062)；负例帧 roi 内不命中",
        probe_auto_label_no_sibling_pick,
    ),
]


# ---------------------------------------------------------------------------
# 破坏实验（5 类 / 9 条：删 roi、删 order_by、放宽 roi、放宽+默认排序、兜底不锚定）
# ---------------------------------------------------------------------------
def _tmp_pipeline(mutate) -> Path:
    """复制整份 pipeline 到临时根，按 ``mutate(JSON dict)`` 改 ``common.json``，返回临时根。

    破坏实验走**临时副本**（同 ``hooks_7`` / ``hooks_109`` 的手法）：真源与真数据一个字节都不动，
    但守卫读的是"真的会被读的那份配置"（``_pipelines(root)`` 的 root 换成副本）。
    """
    tmp = Path(tempfile.mkdtemp(prefix="hooks108_"))
    dst = tmp / "assets" / "resource" / "pipeline"
    dst.mkdir(parents=True)
    drift = _drift()
    for path in sorted(PIPELINE_DIR.glob("*.json")):
        data = drift._load_jsonc(path)
        if path.name == NODE_FILE and isinstance(data, dict):
            mutate(data)
        with (dst / path.name).open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
    return tmp


def prove_red() -> bool:
    print("hooks_108 prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_template_match_roi_required()
        and probe_template_match_order_by_explicit()
        and probe_auto_label_projection_synced()
        and probe_auto_label_no_sibling_pick()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：四个守卫全绿")
    if not green:
        for m in (
            _roi_required_failures()
            + _order_by_failures()
            + _projection_failures()
            + _false_positive_failures()
        ):
            print(f"      - {m}")
        return False

    checks: list[bool] = []

    def _case(name: str, mutate, expect) -> None:
        """跑一个破坏实验：``expect`` = 受影响的失败列表函数。"""
        tmp = _tmp_pipeline(mutate)
        try:
            msgs = expect(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        red = len(msgs) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

    def _drop_roi(data) -> None:
        data[NODE_NAME]["recognition"]["param"].pop("roi", None)

    def _drop_order_by(data) -> None:
        data[NODE_NAME]["recognition"]["param"].pop("order_by", None)

    def _widen_roi(data) -> None:
        # 左边界放到 0：把「自动续战」整栏（标签 x≈17..97）重新放进候选池 —— 这是最容易犯的"放宽修法"。
        data[NODE_NAME]["recognition"]["param"]["roi"] = [0, 1030, 230, 90]

    def _widen_and_unorder(data) -> None:
        # ★最坏形态★：#108 修之前的那一版（全屏候选 + 默认 Horizontal）—— 真机就是它把「自动续战」点开的。
        _widen_roi(data)
        _drop_order_by(data)

    # ① 删掉 roi（回到本票修之前的形态）→ T1 红（无 roi）+ T3 红（投影≠真源）
    _case("投影删掉 roi（= #108 修之前的形态）", _drop_roi, lambda root: _roi_required_failures(root))
    _case("投影删掉 roi → 真源⇄投影不一致", _drop_roi, lambda root: _projection_failures(root))
    _case("投影删掉 roi → 候选池回到全屏，假阳用例失效", _drop_roi,
          lambda root: _false_positive_failures(root))

    # ② 删掉 order_by（回到默认 Horizontal = 最左）→ T2 红 + T3 红
    _case("删掉 order_by（回到默认 Horizontal）", _drop_order_by,
          lambda root: _order_by_failures(root))
    _case("删掉 order_by → 真源⇄投影不一致", _drop_order_by,
          lambda root: _projection_failures(root))

    # ③ 把 roi 放宽到覆盖兄弟那一栏 → T4 红（选出来的候选变成 x=17）+ T3 红
    _case("把 roi 放宽到 [0,1030,230,90]（重新覆盖「自动续战」那一栏）", _widen_roi,
          lambda root: _false_positive_failures(root))
    _case("把 roi 放宽 → 真源⇄投影不一致", _widen_roi, lambda root: _projection_failures(root))

    # ③b ★最坏形态★：roi 放宽 + 默认排序 = 真机误点的那一版 → 必须点名「选中了兄弟位置」。
    _case("roi 放宽 + 默认排序（= 真机误点的那一版）", _widen_and_unorder,
          lambda root: _false_positive_failures(root))

    # ④ OCR 兜底退化成裸「自动」（真源内存改动，恢复现场）→ T3 红
    cfg = _submodule("auto_switch")
    real_pats = cfg.AUTO_LABEL_PATTERNS
    try:
        cfg.AUTO_LABEL_PATTERNS = ("自动",)
        msgs = _projection_failures()
        red = len(msgs) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] OCR 兜底退化成裸「自动」 -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
        checks.append(red)
    finally:
        cfg.AUTO_LABEL_PATTERNS = real_pats

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
