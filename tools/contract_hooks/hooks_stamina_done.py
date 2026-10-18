# -*- coding: utf-8 -*-
"""★#68 第三态：体力恢复的「体力回复了！」结果窗（真机 384 第四跑，2026-10-16）★

现场事实（真机 384，第四跑；逐条见 ``tools/frames/stamina_recovered_done_wuchong384.ocr.txt``）
----------------------------------------------------------------------------------------------
真机已经**证伪**旧的「已知未覆盖」说法：星导石恢复的二次确认 OK 之后，游戏**确实**弹出
「体力回复了！」结果窗（带一个 OK 按钮），此前 pipeline **无任何节点认它** → 五重枢纽空转
``WuchongEntry`` / ``WuchongWait`` 数分钟、``state`` 恒 ``unknown``，最终由「未知画面累计
121 次」兜底收工（零战斗）。本文件把它作为恢复链**第一类参与的第三态**把守。

seam
----
* ``scene/stamina.py``：唯一声明处 —— 新增正文短语 ``DONE_TEXT`` / 自有 ROI ``DONE_OK_ROI`` /
  三个节点名（``PubStaminaDone*``），并把第三步引用 ``[JumpBack]PubStaminaDoneOk`` 追加到
  :func:`scene.stamina.recovery_refs`（⇒ 每个携带恢复引用的链都自动带上它）。
* ``assets/resource/pipeline/common.json``：三个公共节点定义（正文叶 / OK 叶 / 动作）。
* 各链（wuchong / raid / special_dungeon / abyss / auto_push / side_story）：把
  ``[JumpBack]PubStaminaDoneOk`` 插在确认步 ``[JumpBack]PubStaminaConfirmOk`` 之后。

守卫（本文件；prove-red 见文末）
-------------------------------
1. ``stamina-done-wired`` —— 第三态节点**存在**且**在** :func:`scene.stamina.recovery_refs` 里，
   因而**每个**携带恢复引用的链都带上它：具体断言复用既有
   ``hooks_stamina.node_failures`` / ``hooks_stamina.wiring_failures``（**不抄第二份**接线守卫）。
2. ``stamina-done-ok-roi-calibrated`` —— ★承重★：``scene.stamina.DONE_OK_ROI`` 必须**完整包含**
   真机 384 结果窗 OK 框 ``[333,805,53,37]``，且与 ``common.json`` 的 ``PubStaminaDoneOkText.roi``
   **相等**（相等这一段复用既有 ``hooks_stamina.node_failures``）；并自证**确认框 OK 的 ROI**
   （``OK_BTN_ROI``）**不**包含它 —— 两屏 OK 各用各的 ROI 才是承重的。
3. ``stamina-done-mutual-non-hit`` —— **三屏互不误命中**（真机帧逐条 OCR，与门/ROI/页面门承重）：
   * 结果窗帧 → 第三步命中且输出 = 真机 OK 框 ``[333,805,53,37]``；
   * 结果窗节点在【体力不足弹窗帧 / 二次确认帧 / 编队页】都**不**命中；
   * 反过来，第一步 / 第二步在**结果窗帧**都不命中；
   * 两道门**各自承重**：结果窗正文叶 / OK 叶单独喂【弹窗帧 / 确认帧】都**不**命中。

★诚实边界★
----------
真机 leg（在真机上观察点了结果窗 OK 后结果窗消失）**未在本机运行**（无设备授权）—— 本文件只做
**离线**断言（逐条 OCR 回放）；另由 ``tools/verify_stamina_frames.py`` 用**真实 MaaFramework + 真
OCR** 回放本仓真机帧（已把该帧纳入默认语料）。

prove-red（``python tools\\contract_hooks\\hooks_stamina_done.py``）：三处破坏各自变红 ——
  (a) 从某条链摘掉第三态引用 -> 接线守卫红；(b) ``DONE_OK_ROI`` 倒回确认框那一侧的 ROI
  （放不进真机 OK 框）-> ROI 承重守卫红；(c) 页面门 / ROI 任一放宽（正文叶改成愿配弹窗标题、
  OK 叶 ROI 放宽到含确认框 OK）-> 互不误命中守卫红。
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
HOOKS_DIR = Path(__file__).resolve().parent

#: ★只 append 到 sys.path 末尾★（与 hooks_74_stamina 同法）。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

from contract_hooks import hooks_stamina  # noqa: E402

#: 真机 384 第四跑（2026-10-16）结果窗「体力回复了！」帧 —— 随仓入库（标定证据）。
REAL_DONE_FRAME = "tools/frames/stamina_recovered_done_wuchong384.png"
#: 该帧逐条 OCR（720 空间；见同名 ``.ocr.txt``）里结果窗 OK 的框。
REAL_DONE_OK_BOX_384 = [333, 805, 53, 37]
#: 结果窗正文「体力回复了！」框（同帧 OCR）。
REAL_DONE_TEXT_BOX_384 = [267, 424, 168, 36]

#: 结果窗帧的逐条 OCR（只列判据相关 + 同屏承重文字；与 .ocr.txt 逐字一致）。
DONE_FRAME: list[tuple[str, list[int]]] = [
    ("体力回复了！", [267, 424, 168, 36]),
    ("OK", [333, 805, 53, 37]),
    ("五重決战", [226, 265, 270, 80]),
    ("所持", [125, 628, 69, 34]),
    ("体力", [127, 593, 62, 37]),
    ("119", [533, 593, 61, 39]),
    ("16", [374, 596, 69, 34]),
    ("游戏", [250, 898, 74, 36]),
    ("建立房间", [341, 913, 107, 32]),
    ("召集同伴挑战领主", [345, 942, 202, 28]),
    ("领主性能和可获得的报酬", [248, 1104, 247, 26]),
    ("可能随挑战人数有所不同", [247, 1130, 249, 30]),
]


def _contains(roi, box) -> bool:
    """``box``（x,y,w,h）是否**完整**落在 ``roi``（x,y,w,h）内（含边界）。"""
    if not roi or not box:
        return False
    rx, ry, rw, rh = roi
    x, y, w, h = box
    return rx <= x and ry <= y and (x + w) <= (rx + rw) and (y + h) <= (ry + rh)


def _stamina():
    from scene import stamina  # noqa: PLC0415

    return stamina


# ---------------------------------------------------------------------------
# 守卫 1：第三态在恢复链声明里，且每个携带恢复引用的链都带上它
# ---------------------------------------------------------------------------
def wired_failures(common=None, root: Path | None = None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    common = hooks_stamina.load_common(root) if common is None else common

    done_ref = f"[JumpBack]{S.NODE_DONE_OK}"
    refs = tuple(S.recovery_refs())
    if done_ref not in refs:
        msgs.append(
            f"scene.stamina.recovery_refs()={refs!r} 缺第三态 {done_ref!r}"
            "（结果窗又变『无人处理』= 真机 384 第四跑空转根因）"
        )
    if not any(S.NODE_DONE_OK in r for r in refs):
        msgs.append(f"recovery_refs()={refs!r} 里没有任何引用指向 {S.NODE_DONE_OK!r}")
    if S.NODE_DONE_OK not in S.RECOVERY_NODES:
        msgs.append(f"scene.stamina.RECOVERY_NODES={S.RECOVERY_NODES!r} 缺 {S.NODE_DONE_OK!r}")
    if S.NODE_DONE_OK not in S.STAMINA_NODES:
        msgs.append(f"scene.stamina.STAMINA_NODES={S.STAMINA_NODES!r} 缺 {S.NODE_DONE_OK!r}")

    # ★复用既有声明守卫（第三态三节点在场 / 判据一致 / 动作形状），不抄第二份★。
    msgs.extend(hooks_stamina.node_failures(common))
    # ★复用既有接线守卫（每个携带恢复引用的链都包含 recovery_refs() 的每一项 + 五重 FLOW_EXCEPTIONS），
    #   不抄第二份★。这就是「因而每个链都带上它」的机械证明。
    msgs.extend(hooks_stamina.wiring_failures(root))
    return msgs


def probe_stamina_done_wired() -> bool:
    return wired_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：结果窗 OK 的 ROI 按真机重新标定（承重）
# ---------------------------------------------------------------------------
def roi_calibration_failures(common=None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    common = hooks_stamina.load_common() if common is None else common

    # (a) 真机标定证据帧在场。
    if not (REPO_ROOT / REAL_DONE_FRAME).is_file():
        msgs.append(f"真机标定帧未入库：{REAL_DONE_FRAME}（守卫失去真机证据）")

    # (b) ★承重★：DONE_OK_ROI 必须完整包含真机 384 结果窗 OK 框。
    roi = tuple(S.DONE_OK_ROI)
    if not _contains(roi, REAL_DONE_OK_BOX_384):
        msgs.append(
            f"DONE_OK_ROI={list(roi)} 未完整包含真机 384 结果窗 OK 框 {REAL_DONE_OK_BOX_384}"
            " —— OK 会被 ROI 裁剪、PubStaminaDoneOk 永不命中（结果窗无人处理）"
        )
    # (c) 与 common.json 的 PubStaminaDoneOkText.roi 相等（★复用既有相等守卫，不抄第二份★）。
    msgs.extend(hooks_stamina.node_failures(common))
    # (d) 承重自证：确认框 OK 的 ROI（OK_BTN_ROI）必须【不】包含结果窗 OK 框，
    #     否则两屏 OK 无法靠 ROI 分离（结果窗自有 ROI 才是有意义的标定）。
    if _contains(tuple(S.OK_BTN_ROI), REAL_DONE_OK_BOX_384):
        msgs.append(
            f"OK_BTN_ROI={list(S.OK_BTN_ROI)} 竟包含结果窗 OK 框 {REAL_DONE_OK_BOX_384} —— "
            "两屏 OK 无法靠 ROI 分离（结果窗自有 ROI 不再承重）"
        )
    # (e) 反向自证：结果窗 ROI 也【不】可包含确认框 OK 框（确认框 OK 真机 [496,805,53,37]）。
    confirm_ok_box = [496, 805, 53, 37]
    if _contains(roi, confirm_ok_box):
        msgs.append(
            f"DONE_OK_ROI={list(roi)} 竟包含确认框 OK 框 {confirm_ok_box} —— 结果窗节点会误命中确认屏"
        )
    return msgs


def probe_stamina_done_ok_roi_calibrated() -> bool:
    return roi_calibration_failures() == []


# ---------------------------------------------------------------------------
# 守卫 3：三屏（体力不足弹窗 / 二次确认 / 体力回复了结果窗）互不误命中
# ---------------------------------------------------------------------------
def mutual_non_hit_failures(common=None) -> list[str]:
    from scene import stamina as S  # noqa: PLC0415

    msgs: list[str] = []
    common = hooks_stamina.load_common() if common is None else common

    # (1) 结果窗帧：第三步命中，输出 = 真机 OK 框。
    hit, box, _ = hooks_stamina.and_eval(common, S.NODE_DONE_OK, DONE_FRAME)
    if not hit or box is None:
        msgs.append("真机 384 结果窗帧（体力回复了！+ OK）未命中第三步 PubStaminaDoneOk（结果窗无人处理）")
    elif list(box) != REAL_DONE_OK_BOX_384:
        msgs.append(f"结果窗帧输出框应为 {REAL_DONE_OK_BOX_384}，实际 {list(box)}")

    # (2) 三屏 + 编队页互不误命中（与门 / ROI / 页面门承重）。
    negatives = [
        ("体力不足弹窗帧", S.NODE_DONE_OK, hooks_stamina.POPUP_FRAME),
        ("二次确认帧", S.NODE_DONE_OK, hooks_stamina.CONFIRM_FRAME),
        ("编队页（无弹窗）", S.NODE_DONE_OK, hooks_stamina.TEAM_FRAME),
        ("结果窗帧（第一步不得命中）", S.NODE_USE_STONE, DONE_FRAME),
        ("结果窗帧（第二步不得命中）", S.NODE_CONFIRM_OK, DONE_FRAME),
    ]
    for label, node, items in negatives:
        h, _b, _bs = hooks_stamina.and_eval(common, node, items)
        if h:
            msgs.append(f"{label} 误命中 {node} —— 与门 / ROI / 页面门过宽（三屏必须互不误命中）")

    # (3) 两道门各自承重：结果窗正文叶 / OK 叶单独喂【弹窗帧 / 确认帧】都【不】命中。
    for label, items in (
        ("体力不足弹窗帧", hooks_stamina.POPUP_FRAME),
        ("二次确认帧", hooks_stamina.CONFIRM_FRAME),
        ("编队页", hooks_stamina.TEAM_FRAME),
    ):
        for leaf_name in (S.NODE_DONE_TEXT, S.NODE_DONE_OK_TEXT):
            leaf_box = hooks_stamina._ocr_first(items, common.get(leaf_name) or {})
            if leaf_box is not None:
                msgs.append(
                    f"{label} 单独命中结果窗叶 {leaf_name}={leaf_box}（页面门 / ROI 不承重）"
                )
    return msgs


def probe_stamina_done_mutual_non_hit() -> bool:
    return mutual_non_hit_failures() == []


# ---------------------------------------------------------------------------
# prove-red
# ---------------------------------------------------------------------------
def _red(check, *args) -> tuple[bool, str]:
    msgs = check(*args)
    return bool(msgs), (msgs[0] if msgs else "（守卫没抓到！）")


def prove_red() -> bool:
    from scene import stamina as S  # noqa: PLC0415

    print("hooks_stamina_done prove-red：三处破坏，要求守卫各自变红")

    green = (
        probe_stamina_done_wired() is True
        and probe_stamina_done_ok_roi_calibrated() is True
        and probe_stamina_done_mutual_non_hit() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：接线 + ROI + 互不误命中（绿）")
    if not green:
        return False

    checks: list[bool] = []

    # (a) 从某条链（abyss.json::AbyssEntry.next）摘掉第三态引用 -> 接线守卫红。
    root = Path(tempfile.mkdtemp(prefix="wf_stamina_done_"))
    try:
        shutil.copytree(hooks_stamina.PIPE_DIR, root / "assets" / "resource" / "pipeline")
        data = hooks_stamina.load_chain("abyss.json", root)
        nxt = data["AbyssEntry"]["next"]
        done_ref = f"[JumpBack]{S.NODE_DONE_OK}"
        if done_ref in nxt:
            nxt.remove(done_ref)
        (root / "assets" / "resource" / "pipeline" / "abyss.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8"
        )
        red_a, tail_a = _red(wired_failures, None, root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"  [{'PASS' if red_a else 'FAIL'}] 从 AbyssEntry.next 摘掉第三态引用（结果窗又无人处理）-> "
          f"{'红' if red_a else '仍绿'}  {tail_a}")
    checks.append(red_a)

    # (b) DONE_OK_ROI 倒回确认框那一侧的 ROI（放不进真机结果窗 OK 框）-> ROI 承重守卫红。
    orig_roi = S.DONE_OK_ROI
    broken = copy.deepcopy(hooks_stamina.load_common())
    broken[S.NODE_DONE_OK_TEXT]["recognition"]["param"]["roi"] = [430, 770, 290, 90]
    try:
        S.DONE_OK_ROI = (430, 770, 290, 90)
        red_b, tail_b = _red(roi_calibration_failures, broken)
    finally:
        S.DONE_OK_ROI = orig_roi
    print(f"  [{'PASS' if red_b else 'FAIL'}] DONE_OK_ROI 倒回确认框那一侧（放不进真机 OK 框）-> "
          f"{'红' if red_b else '仍绿'}  {tail_b}")
    checks.append(red_b)

    # (c1) 页面门放宽：正文叶页面门加认愿配弹窗标题「回复体力」-> 弹窗帧单独命中正文叶
    #      -> 互不误命中守卫红（结果窗帧仍命中，故红的正是三屏互不误命中那一段）。
    broken1 = copy.deepcopy(hooks_stamina.load_common())
    broken1[S.NODE_DONE_TEXT]["recognition"]["param"]["expected"] = ["体力回复了", "回复体力"]
    red_c1, tail_c1 = _red(mutual_non_hit_failures, broken1)
    print(f"  [{'PASS' if red_c1 else 'FAIL'}] 结果窗正文叶页面门放宽（加认『回复体力』）-> "
          f"{'红' if red_c1 else '仍绿'}  {tail_c1}")
    checks.append(red_c1)

    # (c2) ROI 放宽：OK 叶 ROI 放宽到含确认框 OK（x≈496）-> 确认帧单独命中 OK 叶 -> 互不误命中守卫红。
    broken2 = copy.deepcopy(hooks_stamina.load_common())
    broken2[S.NODE_DONE_OK_TEXT]["recognition"]["param"]["roi"] = [290, 770, 310, 90]
    red_c2, tail_c2 = _red(mutual_non_hit_failures, broken2)
    print(f"  [{'PASS' if red_c2 else 'FAIL'}] 结果窗 OK 叶 ROI 放宽到含确认框 OK -> "
          f"{'红' if red_c2 else '仍绿'}  {tail_c2}")
    checks.append(red_c2)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "stamina-done-wired",
        "#68",
        "第三态「体力回复了！」结果窗节点存在且在 scene.stamina.recovery_refs() 里，因而每个携带恢复"
        "引用的链都带上它（复用既有声明/接线守卫，不抄第二份）",
        probe_stamina_done_wired,
    ),
    (
        "stamina-done-ok-roi-calibrated",
        "#68",
        "结果窗 OK 的 ROI 按真机 384 重标（2026-10-16 第四跑）：DONE_OK_ROI 必须完整包含真机 OK 框 "
        "[333,805,53,37] 且与 common.json 的 PubStaminaDoneOkText.roi 相等；确认框 OK 的 ROI 必须"
        "不含它（两屏 OK 各用各的 ROI 才承重）",
        probe_stamina_done_ok_roi_calibrated,
    ),
    (
        "stamina-done-mutual-non-hit",
        "#68",
        "三屏互不误命中（真机帧）：结果窗帧命中第三步且输出 OK 框 [333,805,53,37]；结果窗节点在"
        "体力不足弹窗帧/确认帧/编队页都不命中；第一/二步在结果窗帧都不命中；两道门（页面门/ROI）"
        "各自承重",
        probe_stamina_done_mutual_non_hit,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
