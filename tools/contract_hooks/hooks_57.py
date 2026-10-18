# -*- coding: utf-8 -*-
"""#57：迷宫【域】的判定与进入 = 【图片/模板匹配】（不再用 OCR 判域）。

缺陷（#57 真机）
----------------
``FarmMazeEntry`` 过去只以轮播**标题**（OCR「摇曳的迷宫」）为判据 → 点下去可能进**任意
一个域**（宝物域/崩坏域/幽玄域）；而横幅**副标题（域名）**的 OCR 在真机被读坏：
``崩坏域``→``崩环域``、``幽玄域``→``出立域``（连标题也常读成 ``摇电的迷宫``/``摇拽的迷宮``）。
结果：想打 ``崩坏域 · 临境域 深渊之兽·极`` 时，无法保证真进了崩坏域。

运维裁决（2026-10-14）
----------------------
> 「迷宫域最好不要用 OCR，用模式识别/图片识别好一点。」

seam（本票）
------------
* ``assets/resource/image/maze/domain_{beng,baowu,youxuan}_{banner,head}.png``：每个域的
  两张**真机 720 裁片** —— ``banner`` = 主城左侧轮播横幅上的域名美术字（进域门控）；
  ``head`` = 迷宫页页眉的域名美术字（进域后**复核**）。
* ``scene/config.py``：``MAZE_DOMAIN_TEMPLATES``（域 → 模板，**真源**）/``maze_domain_template``。
* ``scene/options.py``：``MAZE_DOMAIN_TEMPLATE_NODE`` / ``MAZE_DOMAIN_VERIFY_NODE`` /
  ``MAZE_ENTRY_ROI`` / ``MAZE_HEAD_ROI`` / ``MAZE_TEMPLATE_THRESHOLD`` /
  ``_maze_template_override``（域 / 行各 case 都写该域的两个模板落点）。
* ``assets/resource/pipeline/farm.json``：``FarmMazeEntry`` = ``And[FarmMazeDomain,
  FarmMazeTitle]``（★域由模板判、标题 OCR 只是次要叶★）；``FarmMazeDomain`` 横幅 TemplateMatch；
  ``FarmMazeTitle`` 标题 OCR（整句锚定「摇X的迷」，容忍误读）；``FarmDomainVerify`` 页眉
  TemplateMatch；``FarmScroll``/``FarmScrollUp`` = ``And[FarmDomainVerify, OCR(迷宫页标记)]``
  （复核不过 -> 不滚动，拒绝在错的域上推进）。
* ``agent/side_impl.py``：``MAZE_DOMAIN_TEMPLATES`` 快照 + ``_maze_domain_template_overrides``
  （批量路径按 item.domain 注入模板；未知域 -> {}，绝不静默进别的域）。

守卫 ``maze-domain-template``
-----------------------------
1. **模板真源**：``scene.config.MAZE_DOMAIN_TEMPLATES`` 覆盖三域、每个域 banner/head 两片、
   文件**确实存在**（且 banner ≠ head、不同域不共用同一张）。
2. **快照一致**：``side_impl.MAZE_DOMAIN_TEMPLATES`` == ``scene.config``；ROI / 阈值三处
   （scene.config 语义、scene.options、side_impl）逐项一致。
3. **GUI 派生**：域 / 行每个 case 都写 ``FarmMazeDomain``（banner）/``FarmDomainVerify``（head）
   两个 TemplateMatch，模板 = 该域的模板；``drift.maze_option_drift`` 与 ``check_all`` 为空。
4. **farm.json**：``FarmMazeEntry`` 是 ``And[FarmMazeDomain, FarmMazeTitle]``（box_index 0、
   Click target）；域判据节点**都是 TemplateMatch**（OCR 不作域判据）；标题 OCR 的 expected
   **容忍真机误读**（摇电的迷宫 / 摇曳的迷宮 / 摇拽的迷宮）、且**不含任何域名**；
   ``FarmScroll``/``FarmScrollUp`` 的 And 里带 ``FarmDomainVerify``。
5. **批量 override**：``_farm_override`` 为每个域写对的两个模板；跨域的模板绝不串
   （崩坏域的行 → 崩坏域模板；幽玄域的行 → 幽玄域模板）；未知域 → 不写模板。
6. **真机帧正反例（720）**：用 scipy 口径的 ZNCC（复刻 MAA TM_CCOEFF_NORMED）在**提交进
   仓库**的真机 ROI 裁片上打分 —— 每域的自模板 ≥ 阈值、**异域 / 负样本 / 跨 ROI 全部 < 阈值**；
   OCR 误读（崩环域 / 出立域）**不参与**判域。
7. **回归**：``hooks_54.probe_maze_rows()`` 仍绿（域 + 行名模型未破）；``declared_unreachable
   ("farm")`` 仍为 None。

★prove-red★（``python tools\\contract_hooks\\hooks_57.py``）：
  * 把 farm.json 的 ``FarmMazeDomain`` 默认模板换成别的域 -> 守卫红；
  * 把 ``side_impl.MAZE_TEMPLATE_THRESHOLD`` 压到 0.2 -> 真机帧「异域 < 阈值」断言红；
  * 把提交的 ``domain_beng_banner.png`` 换成别的域的像素 -> 真机帧正例断言红。

全离线、不碰设备（真机帧已经提交在 ``tools/frames/maze57_*.png``）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
FARM_JSON = PIPE_DIR / "farm.json"
INTERFACE = REPO_ROOT / "assets" / "interface.json"
IMAGE_DIR = REPO_ROOT / "assets" / "resource" / "image"
FRAMES_DIR = REPO_ROOT / "tools" / "frames"

# 只 append：subprocess 里 agent_copy 会被抢先插入（与 hooks_54 同做法）。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

HOOK_ID = "maze-domain-template"

#: 域 -> 已提交的真机 ROI 裁片（正例）。
BANNER_POS = {
    "崩坏域": "maze57_banner_beng.png",
    "宝物域": "maze57_banner_baowu.png",
    "幽玄域": "maze57_banner_youxuan.png",
}
HEAD_POS = {
    "崩坏域": "maze57_head_beng.png",
    "宝物域": "maze57_head_baowu.png",
    "幽玄域": "maze57_head_youxuan.png",
}
#: 负样本（不含任何迷宫横幅 / 迷宫页页眉）。
BANNER_NEG = (
    "maze57_banner_neg_gacha.png",
    "maze57_banner_neg_story.png",
    "maze57_banner_on_mazepage.png",  # 迷宫页的横幅位（行列表区）—— 入口不得在此误命中
)
HEAD_NEG = (
    "maze57_head_neg_home.png",
    "maze57_head_on_maincity.png",  # 主城的页眉位 —— 复核不得在此误命中
)

#: 真机误读（副标题/标题 OCR 实测），#57 的证据：这些**绝不能**作域判据。
KNOWN_OCR_MISREADS = ("崩环域", "出立域", "摇电的迷宫", "摇拽的迷宮")


# ---------------------------------------------------------------------------
# ZNCC（复刻 MAA 原生 TemplateMatch 的判据口径 TM_CCOEFF_NORMED）—— 纯 numpy（无 scipy）。
# ---------------------------------------------------------------------------
def _convolve_valid(image: np.ndarray, kernel: np.ndarray) -> np.ndarray | None:
    """mode='valid' 的二维卷积（FFT 实现），与 scipy.signal.fftconvolve 同口径。"""
    ih, iw = image.shape
    kh, kw = kernel.shape
    if kh > ih or kw > iw:
        return None
    shape = (ih + kh - 1, iw + kw - 1)
    spec = np.fft.rfft2(image, shape) * np.fft.rfft2(kernel[::-1, ::-1], shape)
    full = np.fft.irfft2(spec, shape)
    return full[kh - 1: kh - 1 + (ih - kh + 1), kw - 1: kw - 1 + (iw - kw + 1)]


def zncc(image_gray: np.ndarray, tpl_gray: np.ndarray) -> float:
    """零均值归一化互相关：返回最佳匹配得分（与 MAA TM_CCOEFF_NORMED 同口径）。"""
    I = image_gray.astype(np.float64)
    T = tpl_gray.astype(np.float64)
    th, tw = T.shape
    if th > I.shape[0] or tw > I.shape[1]:
        return -1.0
    Tz = T - T.mean()
    tss = float(np.sqrt((Tz ** 2).sum()))
    ones = np.ones((th, tw), dtype=np.float64)
    num = _convolve_valid(I, Tz)
    local_sum = _convolve_valid(I, ones)
    local_sq = _convolve_valid(I ** 2, ones)
    n = th * tw
    var = local_sq - (local_sum ** 2) / n
    var[var < 0] = 0.0
    denom = tss * np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        score = np.where(denom > 1e-6, num / denom, 0.0)
    return float(score.max())


def _gray(path: Path) -> np.ndarray:
    img = np.asarray(Image.open(path).convert("RGB")).astype(np.float64)
    b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    return 0.114 * b + 0.587 * g + 0.299 * r


def _match(frame_path: Path, tpl_path: Path) -> float:
    return zncc(_gray(frame_path), _gray(tpl_path))


# ---------------------------------------------------------------------------
# JSONC
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    """去掉 JSONC 注释（保持字符串内容）。"""
    out: list[str] = []
    state = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i: i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i: i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i: i + 2] != "*/":
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


def _loads_jsonc(text: str) -> dict:
    return json.loads(_strip_jsonc(text))


def _import_side(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _loads_farm(farm_text: str | None) -> dict:
    if farm_text is not None:
        return _loads_jsonc(farm_text)
    return _loads_jsonc(FARM_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 守卫主体
# ---------------------------------------------------------------------------
def _model_failures(
    agent_dir: Path | None = None,
    farm_text: str | None = None,
    image_dir: Path | None = None,
    frames_dir: Path | None = None,
    interface_path: Path | None = None,
) -> list[str]:
    """#57 迷宫域模板模型的全套离线断言；返回失败信息（空 = 绿）。"""
    si = _import_side(agent_dir)
    img_dir = Path(image_dir) if image_dir is not None else IMAGE_DIR
    fr_dir = Path(frames_dir) if frames_dir is not None else FRAMES_DIR
    iface = Path(interface_path) if interface_path is not None else INTERFACE
    msgs: list[str] = []

    from scene.config import (  # noqa: PLC0415
        MAZE_DOMAINS,
        MAZE_ROWS,
        MAZE_DOMAIN_TEMPLATES,
        DEFAULT_MAZE_DOMAIN,
        maze_domain_template,
    )
    from scene import drift  # noqa: PLC0415
    from scene import options as so  # noqa: PLC0415

    # (1) 模板真源：三域 × {banner,head}，文件在场、互不相同。
    if tuple(MAZE_DOMAIN_TEMPLATES) != tuple(MAZE_DOMAINS):
        msgs.append(
            f"模板真源的域与 MAZE_DOMAINS 不一致：{tuple(MAZE_DOMAIN_TEMPLATES)} != "
            f"{tuple(MAZE_DOMAINS)}"
        )
    seen: dict[str, str] = {}
    for d in MAZE_DOMAINS:
        for role in ("banner", "head"):
            try:
                rel = maze_domain_template(d, role)
            except KeyError:
                msgs.append(f"域 {d} 缺 {role} 模板（scene.config.MAZE_DOMAIN_TEMPLATES）")
                continue
            p = img_dir / rel
            if not p.is_file():
                msgs.append(f"模板文件不存在（{d}/{role}）：{p}")
            if rel in seen:
                msgs.append(f"模板串用：{rel} 同时被 {seen[rel]} 与 {d}/{role} 引用（域不可区分）")
            seen[rel] = f"{d}/{role}"
        b = MAZE_DOMAIN_TEMPLATES.get(d, {}).get("banner")
        h = MAZE_DOMAIN_TEMPLATES.get(d, {}).get("head")
        if b == h:
            msgs.append(f"域 {d} 的 banner / head 模板是同一张（进域与复核无法分辨）")

    # (2) 快照一致：side_impl == scene.config；ROI / 阈值三处一致。
    if getattr(si, "MAZE_DOMAIN_TEMPLATES", None) != MAZE_DOMAIN_TEMPLATES:
        msgs.append(
            "side_impl.MAZE_DOMAIN_TEMPLATES 与 scene.config 真源不一致："
            f"{getattr(si, 'MAZE_DOMAIN_TEMPLATES', None)}"
        )
    if list(getattr(si, "MAZE_ENTRY_ROI", [])) != list(so.MAZE_ENTRY_ROI):
        msgs.append(
            f"side_impl.MAZE_ENTRY_ROI {getattr(si, 'MAZE_ENTRY_ROI', None)} != "
            f"scene.options {list(so.MAZE_ENTRY_ROI)}"
        )
    if list(getattr(si, "MAZE_HEAD_ROI", [])) != list(so.MAZE_HEAD_ROI):
        msgs.append(
            f"side_impl.MAZE_HEAD_ROI {getattr(si, 'MAZE_HEAD_ROI', None)} != "
            f"scene.options {list(so.MAZE_HEAD_ROI)}"
        )
    if getattr(si, "MAZE_TEMPLATE_THRESHOLD", None) != so.MAZE_TEMPLATE_THRESHOLD:
        msgs.append(
            f"side_impl.MAZE_TEMPLATE_THRESHOLD {getattr(si, 'MAZE_TEMPLATE_THRESHOLD', None)} != "
            f"scene.options {so.MAZE_TEMPLATE_THRESHOLD}"
        )
    if (
        getattr(si, "MAZE_DOMAIN_TEMPLATE_NODE", None) != so.MAZE_DOMAIN_TEMPLATE_NODE
        or getattr(si, "MAZE_DOMAIN_VERIFY_NODE", None) != so.MAZE_DOMAIN_VERIFY_NODE
    ):
        msgs.append("side_impl 与 scene.options 的模板落点节点名不一致")

    # (3) GUI 派生：域 / 行每个 case 都写该域的两个模板落点。
    def _tpl_of(override: dict, node: str):
        rec = (override or {}).get(node, {}).get("recognition", {})
        param = rec.get("param", {})
        return rec.get("type"), (param.get("template") or [None])[0], param.get("roi"), param.get("threshold")

    for case in so.derive_maze_domain_cases():
        d = case["name"]
        ov = case["pipeline_override"]
        for node, role, roi in (
            (so.MAZE_DOMAIN_TEMPLATE_NODE, "banner", so.MAZE_ENTRY_ROI),
            (so.MAZE_DOMAIN_VERIFY_NODE, "head", so.MAZE_HEAD_ROI),
        ):
            typ, tpl, got_roi, thr = _tpl_of(ov, node)
            if typ != "TemplateMatch":
                msgs.append(f"域 case {d} 的 {node} 不是 TemplateMatch（{typ}）")
            if tpl != maze_domain_template(d, role):
                msgs.append(f"域 case {d} 的 {node} 模板 {tpl!r} != {maze_domain_template(d, role)!r}")
            if list(got_roi or []) != list(roi):
                msgs.append(f"域 case {d} 的 {node} roi {got_roi} != {list(roi)}")
            if thr != so.MAZE_TEMPLATE_THRESHOLD:
                msgs.append(f"域 case {d} 的 {node} threshold {thr} != {so.MAZE_TEMPLATE_THRESHOLD}")

    for case in so.derive_maze_row_cases():
        row = case["name"]
        ov = case["pipeline_override"]
        d = next((dd for dd, rows in MAZE_ROWS.items() if row in rows), None)
        if d is None:
            msgs.append(f"行 case {row!r} 不属于任何域（真源行列表已漂移）")
            continue
        for node, role in ((so.MAZE_DOMAIN_TEMPLATE_NODE, "banner"), (so.MAZE_DOMAIN_VERIFY_NODE, "head")):
            typ, tpl, _roi, _thr = _tpl_of(ov, node)
            if typ != "TemplateMatch" or tpl != maze_domain_template(d, role):
                msgs.append(
                    f"行 case {row!r}（域 {d}）的 {node} 应为 TemplateMatch/{maze_domain_template(d, role)}"
                    f"，实际 {typ}/{tpl!r}"
                )

    dm = drift.maze_option_drift(iface)
    if dm:
        msgs.append(f"迷宫 GUI 选项漂移：{dm[:2]}")
    allm = drift.check_all(repo_root=REPO_ROOT)
    if allm:
        msgs.append(f"drift.check_all() 非空：{allm[:2]}")

    # (4) farm.json 结构：入口 = 标题 ∧ 域；域判据都是 TemplateMatch；标题 OCR 容忍误读且不含域名。
    farm = _loads_farm(farm_text)
    entry = farm.get("FarmMazeEntry", {})
    erec = entry.get("recognition", {})
    if erec.get("type") != "And":
        msgs.append(f"FarmMazeEntry.recognition 不是 And（标题 ∧ 域 的与门），实际 {erec.get('type')!r}")
    else:
        ep = erec.get("param", {})
        if ep.get("all_of") != ["FarmMazeDomain", "FarmMazeTitle"]:
            msgs.append(f"FarmMazeEntry.all_of {ep.get('all_of')} != ['FarmMazeDomain','FarmMazeTitle']")
        if ep.get("box_index") != 0:
            msgs.append(f"FarmMazeEntry.box_index {ep.get('box_index')} != 0（应点横幅域名美术字）")
    if entry.get("action", {}).get("type") != "Click" or not entry.get("action", {}).get("param", {}).get("target"):
        msgs.append("FarmMazeEntry 动作应为 Click target:true（零偏移）")

    for node, role in (("FarmMazeDomain", "banner"), ("FarmDomainVerify", "head")):
        rec = farm.get(node, {}).get("recognition", {})
        if rec.get("type") != "TemplateMatch":
            msgs.append(f"{node} 的 recognition 不是 TemplateMatch（域判据必须用图片匹配）：{rec.get('type')!r}")
            continue
        param = rec.get("param", {})
        exp_tpl = maze_domain_template(DEFAULT_MAZE_DOMAIN, role)
        if (param.get("template") or [None])[0] != exp_tpl:
            msgs.append(f"{node} 基线模板 {(param.get('template') or [None])[0]!r} != 缺省域模板 {exp_tpl!r}")
        exp_roi = list(so.MAZE_ENTRY_ROI if role == "banner" else so.MAZE_HEAD_ROI)
        if list(param.get("roi") or []) != exp_roi:
            msgs.append(f"{node} roi {param.get('roi')} != {exp_roi}")
        if param.get("threshold") != so.MAZE_TEMPLATE_THRESHOLD:
            msgs.append(f"{node} threshold {param.get('threshold')} != {so.MAZE_TEMPLATE_THRESHOLD}")

    title = farm.get("FarmMazeTitle", {}).get("recognition", {})
    if title.get("type") != "OCR":
        msgs.append(f"FarmMazeTitle 应为标题 OCR 叶，实际 {title.get('type')!r}")
    else:
        expected = title.get("param", {}).get("expected") or []
        if list(title.get("param", {}).get("roi") or []) != list(so.MAZE_ENTRY_ROI):
            msgs.append(f"FarmMazeTitle roi {title.get('param', {}).get('roi')} != {list(so.MAZE_ENTRY_ROI)}")
        # 容忍真机误读：这四条真实读法都必须命中标题正则；且正则里**不得**出现任何域名。
        for read in ("摇电的迷宫", "摇曳的迷宮", "摇拽的迷宮", "摇曳的迷宫"):
            if not any(re.search(p, read) for p in expected):
                msgs.append(f"标题 OCR 判据 {expected} 不容忍真机读法 {read!r}（误读即不点：安全失败）")
        for p in expected:
            for dom in MAZE_DOMAINS:
                if dom in p:
                    msgs.append(f"标题 OCR 判据 {p!r} 含域名 {dom!r}（OCR 不得作域判据）")

    for node in ("FarmScroll", "FarmScrollUp"):
        rec = farm.get(node, {}).get("recognition", {})
        if rec.get("type") != "And":
            msgs.append(f"{node} 的 recognition 不是 And（应 = 域复核 ∧ 迷宫页标记），实际 {rec.get('type')!r}")
            continue
        leaves = rec.get("param", {}).get("all_of") or []
        if "FarmDomainVerify" not in leaves:
            msgs.append(f"{node} 的 And 未带 FarmDomainVerify（进域后未复核就滚动 = 会在错的域上推进）")
        ocr_leaf = next((lf for lf in leaves if isinstance(lf, dict)), None)
        markers = ((ocr_leaf or {}).get("recognition", {}).get("param", {}).get("expected") or [])
        for marker in ("的迷宫", "临境域", "深层域", "幽玄域"):
            if marker not in markers:
                msgs.append(f"{node} 的迷宫页标记丢了 {marker!r}（现 {markers}）")

    # (5) 批量 override：按域注入正确模板；跨域不串；未知域不写。
    from agent.batch_plan import BatchItem  # noqa: PLC0415

    for d in MAZE_DOMAINS:
        row = MAZE_ROWS[d][0]
        # BatchItem: dungeon 承载【域】、difficulty 承载【行名】(#54)；target/domain 是属性。
        item = BatchItem(dungeon=d, difficulty=row, times=1, kind="farm")
        ov = si._farm_override(item)
        for node, role in (("FarmMazeDomain", "banner"), ("FarmDomainVerify", "head")):
            rec = ov.get(node, {}).get("recognition", {})
            tpl = (rec.get("param", {}).get("template") or [None])[0]
            if rec.get("type") != "TemplateMatch" or tpl != maze_domain_template(d, role):
                msgs.append(f"_farm_override({d}) 的 {node} 应为 TemplateMatch/{maze_domain_template(d, role)}，实际 {tpl!r}")
        # 跨域：声明崩坏域的行，模板必须都是崩坏域的（绝不串到别的域）。
        other = next(dd for dd in MAZE_DOMAINS if dd != d)
        if (ov.get("FarmMazeDomain", {}).get("recognition", {}).get("param", {}).get("template")
                == [maze_domain_template(other, "banner")]):
            msgs.append(f"_farm_override({d}) 竟写入别的域({other})的横幅模板")
    legacy = si._farm_override(
        BatchItem(dungeon="光之迷宫", difficulty="光之迷宫", times=1, kind="farm")
    )
    if "FarmMazeDomain" in legacy or "FarmDomainVerify" in legacy:
        msgs.append("未知域（光之迷宫）不应写入任何域模板（绝不静默进某个域）")

    # (6) 真机帧正反例（720 裁片，已提交仓库）：自模板 ≥ 阈值；异域 / 负样本 / 跨 ROI < 阈值。
    thr = so.MAZE_TEMPLATE_THRESHOLD
    for role, pos, neg in (("banner", BANNER_POS, BANNER_NEG), ("head", HEAD_POS, HEAD_NEG)):
        for d in MAZE_DOMAINS:
            tpl = img_dir / maze_domain_template(d, role)
            frame = fr_dir / pos[d]
            if not tpl.is_file() or not frame.is_file():
                msgs.append(f"真机帧正例缺失（{d}/{role}）：{frame}")
                continue
            s_pos = _match(frame, tpl)
            if s_pos < thr:
                msgs.append(f"真机帧正例未达阈值（{d}/{role}）：自模板 {s_pos:.4f} < {thr}（{frame.name}）")
            for other in MAZE_DOMAINS:
                if other == d:
                    continue
                s_neg = _match(fr_dir / pos[other], tpl)
                if s_neg >= thr:
                    msgs.append(
                        f"真机帧【异域假阳】（{d}/{role} 模板 命中 {other} 帧）：{s_neg:.4f} >= {thr}"
                    )
            for n in neg:
                nf = fr_dir / n
                if not nf.is_file():
                    msgs.append(f"真机帧负样本缺失：{nf}")
                    continue
                s_n = _match(nf, tpl)
                if s_n >= thr:
                    msgs.append(f"真机帧【负样本假阳】（{d}/{role}）{n}：{s_n:.4f} >= {thr}")

    # (7) OCR 误读不参与判域：域判据节点（TemplateMatch）里绝不出现任何误读串；
    #     而在真机同域帧上，模板仍 100% 命中（域判定与 OCR 读坏无关）。
    domain_nodes_text = json.dumps(
        {n: farm.get(n, {}) for n in ("FarmMazeDomain", "FarmDomainVerify")}, ensure_ascii=False
    )
    for misread in KNOWN_OCR_MISREADS:
        if misread in domain_nodes_text:
            msgs.append(f"域判据节点里出现 OCR 误读串 {misread!r}（域不得由 OCR 判）")

    # (8) 回归：#54 域 + 行名模型仍绿；farm 仍非能力缺口。
    try:
        from contract_hooks import hooks_54  # noqa: PLC0415

        if hooks_54.probe_maze_rows() is not True:
            msgs.append("#54 迷宫「域 + 行名」探针变红（本票带坏了行名模型）")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"#54 探针无法运行：{exc!r}")
    if si.declared_unreachable("farm") is not None:
        msgs.append("farm 仍在 UNREACHABLE_FROM_MAIN_CITY 里（#54：迷宫可达、可打）")

    for m in msgs[:12]:
        print(f"    × {m}")
    return msgs


def probe_maze_domain() -> bool:
    """#57：迷宫域 = 图片模板匹配（进域门控 + 进域复核 + 真机帧正反例）。离线、不碰设备。"""
    return _model_failures() == []


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def _probe_in(agent_copy: Path) -> bool | None:
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        f"sys.path.insert(1, {str(agent_copy)!r})\n"
        "from contract_hooks import hooks_57\n"
        f"print('PROBE_RESULT', repr(hooks_57._model_failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral57_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def _break_threshold(agent_dir: Path) -> None:
    """把模板匹配阈值压到 0.2 -> 真机帧「异域 < 阈值」断言应红。"""
    path = agent_dir / "side_impl.py"
    text = path.read_text(encoding="utf-8")
    old = "MAZE_TEMPLATE_THRESHOLD = 0.8"
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, "MAZE_TEMPLATE_THRESHOLD = 0.2  # prove-red", 1), encoding="utf-8")


def prove_red() -> bool:
    print("hooks_57 prove-red：三处破坏，要求 maze-domain-template 变红")
    green = probe_maze_domain() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：三域模板 + 进域门控/复核 + 真机帧正反例（绿）")
    if not green:
        return False

    # 破坏 1（pipeline 纯文本，不写盘）：把 FarmMazeDomain 的缺省域模板换成别的域。
    broken_farm = FARM_JSON.read_text(encoding="utf-8").replace(
        '"maze/domain_baowu_banner.png"', '"maze/domain_youxuan_banner.png"'
    )
    pred_red = _model_failures(farm_text=broken_farm) != []
    print(f"  [{'PASS' if pred_red else 'FAIL'}] 把 FarmMazeDomain 缺省模板换成幽玄域 -> "
          f"{'红' if pred_red else '仍绿'}")

    # 破坏 2（agent 副本）：把匹配阈值压到 0.2 -> 真机帧异域假阳被抓住。
    tmp2 = Path(tempfile.mkdtemp(prefix="wf_hook57_agent_"))
    try:
        shutil.copytree(AGENT_DIR, tmp2 / "agent")
        _break_threshold(tmp2 / "agent")
        thr_red = _probe_in(tmp2 / "agent") is False
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)
    print(f"  [{'PASS' if thr_red else 'FAIL'}] 把模板匹配阈值压到 0.2 -> "
          f"{'红' if thr_red else '仍绿'}")

    # 破坏 3（模板像素副本）：把 崩坏域 横幅模板换成 幽玄域 的像素 -> 真机帧正例断言红。
    tmp3 = Path(tempfile.mkdtemp(prefix="wf_hook57_img_"))
    img_red = False
    try:
        shutil.copytree(IMAGE_DIR, tmp3 / "image")
        shutil.copyfile(
            tmp3 / "image" / "maze" / "domain_youxuan_banner.png",
            tmp3 / "image" / "maze" / "domain_beng_banner.png",
        )
        img_red = _model_failures(image_dir=tmp3 / "image") != []
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)
    print(f"  [{'PASS' if img_red else 'FAIL'}] 把 崩坏域 横幅模板换成幽玄域像素 -> "
          f"{'红' if img_red else '仍绿'}")

    ok = green and pred_red and thr_red and img_red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#57",
        "迷宫【域】的判定与进入 = 图片模板匹配（运维：迷宫域不要用 OCR）：每个域两张真机裁片"
        "（横幅门控 + 页眉复核）/ 进域 = 标题 ∧ 域的与门 / 进域后复核不过不推进 / "
        "真机帧正反例区分三域（异域与负样本 < 阈值）/ OCR 误读不参与判域",
        probe_maze_domain,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
