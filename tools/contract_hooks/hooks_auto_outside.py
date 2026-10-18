# -*- coding: utf-8 -*-
"""#56 二批：自动的切换移到「战斗外」（运维五大裁决）—— 契约挂点（自动发现，零改既有文件）。

seam：``scene/auto_switch.py``（数据）+ ``agent/auto_switch_impl.py``（定位/读状态/切换机制）+
``assets/resource/pipeline/{common,wuchong,special_dungeon,abyss}.json`` + ``assets/interface.json``
+ ``tools/live_harness.py``（归位有序表）。

本批对应运维五条裁决：

① 「续战」误匹配 —— ``WuchongResume`` 的 OCR 必须**整串锚定**（``^续战$``），绝不裸「续战」
   （否则误命中编队页的「自动续战」）。
② 自动的切换从「战斗内」挪到「战斗外」，且**不得假定固定坐标** —— 「自动」按钮一律**定位**
   （模板优先 / OCR 整串兜底）后读状态、点**识别框中心**；**覆盖所有模式的编队页**；战斗内不再切。
③ 「自动续战功能」确认框 —— 修流程但**功能不打开**（保持关 / 出现就按『取消』）。
④ 多人异常也是自动续战导致 —— 保持自动续战关（本批不启用）。
⑤ 归位不认识编队页 —— ``ensure_main_city`` 在编队页应**先点返回**，再走既有主城判据。

八个守卫（对应硬要求；prove-red 见文末）：

1. ``auto-outside-locates-auto-switch`` —— 「自动」按钮按**定位**（不是固定坐标）：OCR 整串
   ``^自动$`` 在不同位置（编队页左下 / 房间页右上）都定位到**它自己**的框；点击点 = 识别框中心；
   「自动」标签裁片入库。**绝不写死坐标**。
2. ``auto-outside-template-distinct`` —— ★#111 修正：改用**滑窗 ZNCC**（与 ``hooks_108`` 同一套
   实现），且兄弟窗口改成**实测尖峰**★：模板在真机帧上**命中**「自动」（滑窗尖峰 1.0000@x=142），
   同排兄弟「自动续战」的滑窗尖峰是 **0.8964@x=17**（也是尖峰，**同样过 0.75 阈值**）。
   ⇒ 模板**本身分不开**这对兄弟控件，distinctness 必须由 **roi + order_by** 提供；
   本守卫按真源 ``scene.auto_switch.AUTO_LABEL_ROI`` / ``AUTO_ORDER_BY`` 复算「框架会选哪个」。
   ★旧写法为什么「碰巧绿」★：它把兄弟窗口写成 ``x=18``（真机 OCR 框位置）并**只比那一个点** ——
   实测 ``x=18`` 只有 **0.4536**（< 0.75，于是「不误命中」成立）；而框架做的是**滑窗**，
   会跑到 **x=17 = 0.8964**。**点测一个偏 1px 的框**就把 bug 藏了（#108 已用滑窗口径钉过这条，
   #111 把本守卫也改成同一把尺）。
3. ``auto-outside-state-read-correct`` —— 由定位框推出的探针**读对开/关**（开=橙、关=灰）。
4. ``auto-outside-no-in-battle-switch`` —— **战斗内不再有自动切换**：无 ``WuchongBattleAutoGuard`` /
   ``pause_auto`` / ``open_pause`` / ``close_pause`` / ``battle_pause``。
   ★#71 **收窄**（裁决②原文**一字不删**，仅**收窄**；依据 ADR
   ``docs/adr/0004-battle-page-auto-off-manual-only.md`` / spec B1/D4）★：以上禁令**全部保留**
   （战斗内绝无**暂停式**自动切换）；**新增白名单例外** —— 战斗页关自动只允许**一个具名、只关不开、
   只对五重**的出口（``scene.wuchong.BATTLE_AUTO_NODE``；见守卫 4 的 ``_no_in_battle_failures`` 收窄段）。
5. ``auto-outside-cross-mode-team-auto`` —— 覆盖所有模式的编队页：``SpecialTeamAutoSet``（经
   SpecialEntry，覆盖领主战家族/幻想/raid/迷宫）+ ``AbyssTeamAutoSet``（深渊EX）；非五重一律夹回「开」。
6. ``auto-outside-cont-kept-off`` —— ruling ③：五重「自动续战」设成**关**；「是否自动续战」默认「否」
   且「否」= 不碰（节点关掉）。
7. ``auto-outside-return-home-back-first`` —— ruling ⑤：归位在编队页**先点返回**（点识别到的返回框中心）。
8. ``auto-outside-page-scoped`` —— ★三批根因修复★：「自动」只在**编队页/房间页**认（页面文本锚点 ∨
   开关探针内的 ``开``/``关`` 状态字）；**战斗 HUD 的「自动」**（真机帧 ``[15,193,55,19]``，与编队页
   ``[142,1062,43,26]`` 是两个不同控件/不同位置）**永不命中**；定位不到 = 可见失败
   （``[auto_switch][FAIL]``），绝不静默「不动」。

★#71（战斗页关自动 + 两处同名控件互不认领）新增三个守卫（``HOOKS`` 见文末）★：

9. ``auto-outside-battle-scope-mutex`` —— ★两处同名控件互不认领★：``is_battle_auto_control``（战斗页）
   与 ``is_team_auto_control``（编队页）**互斥** —— 战斗 HUD 的「自动」``[15,193,55,19]`` 只被战斗页认，
   同屏「技能自动」``[26,260,34,21]`` / 编队页位置 ``[142,1062,43,26]`` 都不认；编队页帧绝不进战斗页作用域；
   驱动真实 ``auto_switch_state``（``scope=battle``）：战斗 HUD 帧 + 合成图（探针涂青绿=开）**命中**，
   探针涂灰=关（``state:"on"``）**不命中**，编队页帧**不命中**。
10. ``auto-outside-battle-state-calibrated`` —— 战斗页读状态标定：真机 ON 帧
    ``tools/frames/auto_battle_hud_hit.png`` 读 ``True``；探针区涂灰读 ``False``；探针取不到读 ``None``
    （★判不出 ≠ 关★）。
11. ``auto-outside-snapshot-pinned`` —— ``agent/auto_switch_impl._Snapshot`` 的冻结快照与
    ``scene.auto_switch`` 真源**逐项**一致（既有 ``AUTO_LABEL``/``PROBE_OFFSETS``/``TEAM_PAGE_ANCHORS``…
    与 #71 的 ``BATTLE_*`` 全部 pin）。

★诚实缺口（#71）★（与 ADR ``docs/adr/0004-battle-page-auto-off-manual-only.md`` 一致，守卫 3 的 docstring 同述）：
   战斗页「自动 = **关**」的**真机帧仓库里一张都没有** —— 关态只按 ON 帧 + 合成反例标定，
   **真机校准待补 3 帧**（补到 ``tools/frames/`` 后把守卫 3 的判据换成真机帧即可）。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE_REL = "assets/resource/pipeline"
IMAGE_REL = "assets/resource/image"
INTERFACE_REL = "assets/interface.json"
FRAME_LORD_TEAM = "tools/frames/lord_team_page.png"
#: 三批根因证据帧（真机 127.0.0.1:16384）：战斗 HUD 命中帧 + 其后转场/加载失败帧。
FRAME_AUTO_BATTLE_HUD = "tools/frames/auto_battle_hud_hit.png"
FRAME_AUTO_BATTLE_ACTION = "tools/frames/auto_battle_hud_action.png"

#: 真机帧 720 空间里的关键框（相片自证见各守卫；来自 tools/frames/lord_team_page.png 的 OCR）。
AUTO_BOX_720 = [142, 1062, 43, 26]        # 编队页「自动」标签
#: 编队页「自动续战」的**同尺寸**窗口（错标签对照）。★#111 修正：写**实测滑窗尖峰** ``x=17``★
#: —— 真机 OCR 框是 ``[18,1062,79,24]``（那是**文字框**的左边界），但模板做**滑窗**时最高分
#: 落在 ``x=17``：``ZNCC(17)=0.8964``（尖峰，过 0.75 阈值）而 ``ZNCC(18)=0.4536``（掉了 0.44）。
#: 旧值 18 让本守卫「点测了一个偏 1px 的框」才绿 —— 框架真跑会到 17（#108 实测，见其 docstring 末）。
CONT_BOX_720 = [17, 1062, 43, 26]         # 编队页「自动续战」的**滑窗尖峰**（错标签对照）
ROOM_AUTO_BOX_720 = [630, 102, 43, 27]    # 共斗房间页「自动」标签（★不同位置★）
#: 战斗 HUD 的「自动」（#71）：真机 ON 帧 ``tools/frames/auto_battle_hud_hit.png`` 的 OCR 框。
BATTLE_AUTO_BOX_720 = [15, 193, 55, 19]


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


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


def _load_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


def _pipe(name: str, root: Path | None = None) -> dict:
    return _load_jsonc((Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL / name)


def _interface(root: Path | None = None) -> dict:
    return _load_jsonc((Path(root) if root is not None else REPO_ROOT) / INTERFACE_REL)


def _ac(node: dict) -> dict:
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


def _rc(node: dict) -> dict:
    return ((node.get("recognition") or {}).get("param") or {}).get("custom_recognition_param") or {}


# ---------------------------------------------------------------------------
# 守卫 1：「自动」按钮按【定位】（不是固定坐标）
# ---------------------------------------------------------------------------
def _locate_failures(locate_fn=None, click_fn=None, root: Path | None = None) -> list:
    _paths()
    import auto_switch_impl as sw  # noqa: PLC0415
    from scene import auto_switch as cfg  # noqa: PLC0415

    locate = locate_fn or sw.locate_switch_label
    click = click_fn or sw.click_point
    msgs: list[str] = []

    # (a) 两个不同位置：定位到的框必须**跟着 OCR 位置走**（证明不写死坐标）。
    for label, box in (("编队页", AUTO_BOX_720), ("房间页", ROOM_AUTO_BOX_720)):
        got = locate([("自动", list(box))], "自动")
        if got != list(box):
            msgs.append(f"「自动」定位未跟随位置（{label}）：给 {box} 得到 {got}")

    # (a2) ★模板必须经 OCR 校验★（真机实测：MAA 模板在领主战编队页把「自动」裁片命中了
    #      「自动续战」位置）。模板命中与 OCR 锚定矛盾 → 以 OCR 为准；模板命中处被「自动续战」
    #      覆盖 → 否决模板。
    conflict = locate([("自动", list(AUTO_BOX_720)), ("自动续战", list([18, 1062, 79, 24]))],
                      "自动", [17, 1062, 43, 26])
    if conflict != list(AUTO_BOX_720):
        msgs.append(f"模板与 OCR 矛盾时未以 OCR 为准：{conflict}（应 {AUTO_BOX_720}）")
    blind = locate([("自动续战", list([18, 1062, 79, 24]))], "自动", [17, 1062, 43, 26])
    if blind is not None:
        msgs.append(f"模板误命中「自动续战」未被否决：{blind}")

    # (b) 锚定：绝不命中「自动续战」。
    if locate([("自动续战", list(CONT_BOX_720))], "自动") is not None:
        msgs.append("「自动」定位误命中「自动续战」（未整串锚定）")
    if locate([("自动战斗", list(CONT_BOX_720))], "自动") is not None:
        msgs.append("「自动」定位误命中「自动战斗」（未整串锚定）")

    # (c) 点击点 = 识别框中心。
    if click(AUTO_BOX_720) != (142 + 43 // 2, 1062 + 26 // 2):
        msgs.append(f"点击点不是识别框中心：{click(AUTO_BOX_720)}")

    # (d) 真源里不得再为「自动」保留固定探针/落点（不得假定固定坐标）——用**数据属性**判定
    #     （不看注释文本，避免注释里的「已删除」字样误报）。
    from scene import wuchong as w  # noqa: PLC0415

    sw = w.WUCHONG_SWITCHES
    if hasattr(sw, "auto_probes") or hasattr(sw, "auto_toggles"):
        msgs.append("scene.wuchong.WUCHONG_SWITCHES 仍保留「自动」固定几何（应为定位）")
    if hasattr(sw, "pause_auto_probes") or hasattr(sw, "pause_auto_toggles"):
        msgs.append("scene.wuchong.WUCHONG_SWITCHES 仍保留暂停屏自动几何（战斗内不再切）")
    if hasattr(w.WUCHONG_BUTTONS, "battle_pause"):
        msgs.append("scene.wuchong.WUCHONG_BUTTONS 仍保留 battle_pause（战斗内不再切）")

    # (e) 「自动」标签裁片入库。
    for rel in cfg.AUTO_LABEL_TEMPLATES:
        if not (REPO_ROOT / IMAGE_REL / rel).is_file():
            msgs.append(f"「自动」标签裁片缺失：{IMAGE_REL}/{rel}")

    # (f) common.json 提供模板入口节点（模板优先）。
    common = _pipe("common.json", root)
    node = common.get(cfg.AUTO_TEMPLATE_NODE) or {}
    if ((node.get("recognition") or {}).get("param") or {}).get("template") != list(cfg.AUTO_LABEL_TEMPLATES):
        msgs.append(f"common.json::{cfg.AUTO_TEMPLATE_NODE} 缺模板（模板优先的入口）")
    return msgs


def probe_auto_switch_located() -> bool:
    return _locate_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2 / 3：模板的**滑窗**分数（框架做法）+ 状态读对
#
# ★#111：这里原来是**点测**（拿一个 box 裁出来算 ZNCC），而且兄弟窗口写的是 x=18。
# 点测一个偏 1px 的框 → 0.4536 < 0.75 → 「不误命中」成立 → 守卫**碰巧绿**；
# 框架做的是**滑窗**，会跑到 x=17 = 0.8964（照样过 0.75）。现在改成与 ``hooks_108`` 同一套
# 滑窗实现（``_zncc_map`` / ``_peaks`` / ``_select``），窗口值也改成实测尖峰。
# ---------------------------------------------------------------------------
def _frame_720():
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    im = Image.open(REPO_ROOT / FRAME_LORD_TEAM)
    if im.size == (1080, 1920):
        im = im.resize((720, 1280), Image.LANCZOS)
    return im.convert("RGB"), np


def _hooks_108():
    """同一套**滑窗 ZNCC** 实现（#111 要求复用，绝不另写一份分数口径）。"""
    for _p in (str(TOOLS_DIR / "contract_hooks"), str(TOOLS_DIR), str(REPO_ROOT)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import importlib  # noqa: PLC0415

    return importlib.import_module("hooks_108")


def _template_failures(
    tpl_rel: str | None = None,
    auto_box=None,
    cont_box=None,
    frame: str | None = None,
) -> list:
    """★滑窗口径★：模板在真机帧上的分数（不是点测一个框）。

    四条断言（每条都是「框架真跑会怎样」，不是「我们挑的那个点怎样」）：

    (a) 全屏滑窗**最像**的位置（``order_by: Score`` 语义）必须是真「自动」，且分 ≥ 阈值；
    (b) 兄弟「自动续战」的**滑窗尖峰**必须等于 :data:`CONT_BOX_720`（偏 1px 即红）——
        它 **0.8964 ≥ 阈值 0.75**，所以★模板本身分不开这对兄弟★（这是事实，不是缺陷）；
    (c) 真源的 ``AUTO_LABEL_ROI`` **不覆盖**兄弟尖峰窗口、覆盖真「自动」窗口 ——
        distinctness 由 roi 提供（这是 #108 的修法，#111 在这里复核）；
    (d) 按框架真语义复算（roi 内候选 + ``order_by`` + ``index:0``）选到的是真「自动」。
    """
    _paths()
    from scene import auto_switch as cfg  # noqa: PLC0415

    tpl_rel = tpl_rel or cfg.AUTO_LABEL_TEMPLATES[0]
    auto_box = list(auto_box or AUTO_BOX_720)
    cont_box = list(cont_box or CONT_BOX_720)
    frame = frame or FRAME_LORD_TEAM
    thr = float(cfg.AUTO_TEMPLATE_THRESHOLD)
    msgs: list[str] = []

    try:
        h108 = _hooks_108()
    except Exception as exc:  # noqa: BLE001 - 拿不到同一套实现 = 红，不静默降级
        return [f"拿不到 hooks_108 的滑窗 ZNCC 实现（{exc!r}）—— 本守卫禁止退回点测"]
    missing = h108._deps_missing()
    if missing:
        # ★#111：旧实现是 try/except pass —— 缺依赖就**静默绿**。假阳本来就是静默的，不能再静。
        return [missing]

    tpl_path = REPO_ROOT / IMAGE_REL / tpl_rel
    if not tpl_path.is_file():
        return [f"模板裁片缺失：{IMAGE_REL}/{tpl_rel}（没有裁片就没有假阳用例）"]
    if not (REPO_ROOT / frame).is_file():
        return [f"真机帧缺失：{frame}（已入库的证据帧被删 → 假阳用例失效）"]

    tpl, _rel = h108._template_gray(cfg)
    tpl_h, tpl_w = tpl.shape
    scores = h108._zncc_map(h108._frame_720(frame), tpl)
    cands = h108._peaks(scores, thr)

    # (a) 全屏最像的那一个 = 真「自动」。
    best = h108._select(cands, "Score", 0)
    if best is None or best[0] < thr or abs(best[1] - auto_box[0]) > 2 or abs(best[2] - auto_box[1]) > 2:
        msgs.append(
            f"{frame}：全屏滑窗最像的位置 {best} 不是真「自动」{auto_box[:2]}（阈值 {thr}）"
            f" —— 候选={cands[:4]}"
        )

    # (b) 兄弟「自动续战」的**滑窗尖峰**必须就是我们记下的那个窗口（偏 1px 即红）。
    left_peaks = [c for c in cands if c[1] < auto_box[0]]
    sib = h108._select(left_peaks, "Score", 0)
    if sib is None:
        msgs.append(
            f"{frame}：真「自动」左侧没有任何 ≥{thr} 的候选 —— 假阳前提消失了"
            f"（帧/模板/阈值变了，请重新标定本守卫的 AUTO_BOX_720 / CONT_BOX_720）"
        )
    else:
        if (sib[1], sib[2]) != (cont_box[0], cont_box[1]):
            msgs.append(
                f"{frame}：兄弟窗口写的是 {cont_box[:2]}，但实测滑窗尖峰在 {(sib[1], sib[2])}"
                f"（ZNCC={sib[0]}）—— 窗口必须等于**实测尖峰**：差 1px 就能把分数从 "
                f"{sib[0]} 掉到 {float(scores[cont_box[1], cont_box[0]]):.4f}，于是「点测」会骗人"
            )
        if sib[0] < thr:
            msgs.append(
                f"{frame}：兄弟尖峰 ZNCC={sib[0]} < 阈值 {thr} —— 本守卫的前提是「模板分不开这对"
                f"兄弟」，若分数掉下来了请重新标定（别让验收线失去意义）"
            )

    # (c) distinctness 由 roi 提供：兄弟尖峰在 roi 外、真「自动」在 roi 内。
    roi = tuple(cfg.AUTO_LABEL_ROI)
    if h108._inside(roi, (cont_box[0], cont_box[1], tpl_w, tpl_h)):
        msgs.append(
            f"{frame}：真源 AUTO_LABEL_ROI={list(roi)} **覆盖**了兄弟尖峰窗口 {cont_box}"
            f" —— roi 必须把「自动续战」整栏排除出候选池（#108）"
        )
    if not h108._inside(roi, (auto_box[0], auto_box[1], tpl_w, tpl_h)):
        msgs.append(
            f"{frame}：真源 AUTO_LABEL_ROI={list(roi)} **不含**真「自动」窗口 {auto_box}"
            f" —— 收窄过头会把该命中的也裁掉"
        )

    # (d) 按框架真语义复算：roi 内候选 + order_by + index:0 必须选到真「自动」。
    inside = [c for c in cands if h108._inside(roi, (c[1], c[2], tpl_w, tpl_h))]
    picked = h108._select(inside, cfg.AUTO_ORDER_BY, 0)
    if len(inside) != 1:
        msgs.append(
            f"{frame}：roi {list(roi)} 内 ≥{thr} 的候选有 {len(inside)} 个 {inside[:4]}"
            f" —— 期望**恰好 1 个**（「自动」那一栏），多了就会重新变成「排序决定选哪个」"
        )
    if picked is None or abs(picked[1] - auto_box[0]) > 2 or abs(picked[2] - auto_box[1]) > 2:
        msgs.append(
            f"{frame}：按框架语义（roi {list(roi)} + order_by={cfg.AUTO_ORDER_BY!r} + index 0）"
            f"选到 {picked}，不是真「自动」{auto_box[:2]} —— 这就是误点「自动续战」的那条路"
        )
    return msgs


def probe_auto_switch_template_distinct() -> bool:
    """#56 / #111：模板**滑窗**命中「自动」；兄弟「自动续战」的尖峰 0.8964@(17,1062) 也过阈值
    ⇒ 模板本身分不开，distinctness 由真源 roi + order_by 提供（按框架语义复算选到真「自动」）。"""
    return _template_failures() == []


def _state_failures(state_fn=None) -> list:
    _paths()
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    import auto_switch_impl as sw  # noqa: PLC0415
    from scene import auto_switch as cfg  # noqa: PLC0415

    read = state_fn or sw.read_switch_state
    rgb, _np = _frame_720()
    msgs: list[str] = []

    bx = AUTO_BOX_720
    if read(np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1]), cfg.AUTO_LABEL, bx) is not True:
        msgs.append("真机帧（自动=开）未读出「开」")

    # 把探针区涂灰 → 应读成「关」。
    probe = sw.probe_for(cfg.AUTO_LABEL, bx)
    off = rgb.copy()
    px = off.load()
    for y in range(probe[1], probe[3]):
        for x in range(probe[0], probe[2]):
            px[x, y] = (128, 128, 128)
    if read(off, cfg.AUTO_LABEL, bx) is not False:
        msgs.append("把探针区涂灰后未读出「关」")
    return msgs


def probe_auto_switch_state_read_correct() -> bool:
    return _state_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：战斗内不再有【暂停式】自动切换（#71 **收窄**为白名单）
# ---------------------------------------------------------------------------
# ★#71 收窄（裁决②原文不删，只收窄）★
#   二批的裁决②把自动的切换**移出战斗内**，本守卫原样断言「战斗内没有自动切换」。本票（#71 / spec
#   B1/D4 / ADR 0004）**不推翻**这条，只把它**收窄**成：「战斗内没有**暂停式**自动切换（原禁令全留），
#   且**战斗页关自动只有唯一一个具名、只关不开、只对五重**的出口」。原禁令（WuchongBattleAutoGuard /
#   pause_auto / open_pause / close_pause / battle_pause / SWITCH_WHICH_VALUES == ("auto","cont")）**一条不动**；
#   新出口必须满足：节点名**取自** ``scene.wuchong.BATTLE_AUTO_NODE``（绝不硬编码）、节点在
#   ``WuchongEntry.next``（否则够不着）、``which=="auto" ∧ scene=="wuchong" ∧ on is False``（★只关不开★）、
#   raw 识别 = ``scene.wuchong.BATTLE_DISABLED_EXPECTED``（手操引擎关 ⇔ 不被选中）、
#   「是否手操=手操」case 以 ``auto_switch_state`` + ``scope=="battle"`` + ``state=="on"`` 开启它
#   （只在读到「开」时才去关）、**不得设 max_hit**（整任务计数：设了会在整局里用尽 → 第二局不再关自动；
#   一场一次靠 agent 侧闩锁 ``BATTLE_AUTO_ONCE_KEY``），且 pipeline 里带 ``scope=="battle"`` 的节点
#   **恰为该节点一个**。
def _nodes_with_scope(pipe: dict, scope: str) -> set:
    """pipeline 里所有 custom_action / custom_recognition 参数带 ``scope == scope`` 的节点名集合。"""
    found: set[str] = set()
    for name, spec in (pipe or {}).items():
        if not isinstance(spec, dict):
            continue
        if _ac(spec).get("scope") == scope or _rc(spec).get("scope") == scope:
            found.add(name)
    return found


def _no_in_battle_failures(pipe: dict | None = None, impl=None, iface: dict | None = None) -> list:
    _paths()
    import wuchong_impl as impl_mod  # noqa: PLC0415
    from scene import wuchong as w  # noqa: PLC0415

    impl = impl or impl_mod
    pipe = _pipe("wuchong.json") if pipe is None else pipe
    iface = _interface() if iface is None else iface

    msgs: list[str] = []
    if "WuchongBattleAutoGuard" in pipe:
        msgs.append("wuchong.json 仍有「WuchongBattleAutoGuard」节点（战斗内自动切换应删除）")
    if "WuchongBattleAutoGuard" in (pipe.get("WuchongEntry", {}).get("next") or []):
        msgs.append("wuchong.json::WuchongEntry.next 仍引用 WuchongBattleAutoGuard")
    blob = json.dumps(pipe)  # 注释已被 JSONC 解析剥掉，只剩真实数据
    for banned in ("pause_auto", "open_pause", "close_pause"):
        if banned in blob:
            msgs.append(f"wuchong.json 仍含战斗内开关参数 {banned!r}")

    # 机制/数据侧：用属性/枚举判定（不看注释文本）。
    if hasattr(impl, "_battle_pause"):
        msgs.append("agent/wuchong_impl.py 仍有 _battle_pause（战斗内自动的暂停落点）")
    if "WuchongBattleAutoGuard" in w.FLOW_EXCEPTIONS:
        msgs.append("scene.wuchong.FLOW_EXCEPTIONS 仍含 WuchongBattleAutoGuard")
    if "WuchongBattleAutoGuard" in w.flow_step_nodes():
        msgs.append("scene.wuchong.flow_step_nodes() 仍含 WuchongBattleAutoGuard")
    if w.SWITCH_WHICH_VALUES != ("auto", "cont"):
        msgs.append(f"开关 which 取值仍含暂停屏自动：{w.SWITCH_WHICH_VALUES}")

    # ---- #71 收窄：白名单例外（唯一具名、只关不开、只对五重的战斗页出口）----
    node_name = w.BATTLE_AUTO_NODE          # ★绝不硬编码字符串★
    scope = w.BATTLE_AUTO_SCOPE
    node = pipe.get(node_name)
    if not node:
        msgs.append(f"wuchong.json 缺战斗页关自动节点 {node_name!r}"
                    f"（#71：手操必须在战斗页关自动 —— 编队页关不住）")
    else:
        if node_name not in (pipe.get("WuchongEntry", {}).get("next") or []):
            msgs.append(f"WuchongEntry.next 缺 {node_name}（手操时够不着 → 战斗页关自动形同没做）")
        ac = _ac(node)
        if ac.get("which") != "auto":
            msgs.append(f"{node_name} 的 which 应为 'auto'（实际 {ac.get('which')!r}）")
        if ac.get("scene") != "wuchong":
            msgs.append(f"{node_name} 的 scene 应为 'wuchong'（★只对五重★；实际 {ac.get('scene')!r}）")
        if ac.get("scope") != scope:
            msgs.append(f"{node_name} 的 scope 应为 {scope!r}（战斗页作用域；实际 {ac.get('scope')!r}）")
        if ac.get("on") is not False:
            msgs.append(f"{node_name} 必须★只关不开★（on 恒为 False；实际 {ac.get('on')!r}）")
        # raw 默认必须关（与 WuchongBattle 同形：手操引擎关 ⇔ 本节点不被选中）。
        raw_type = (node.get("recognition") or {}).get("type")
        raw_exp = ((node.get("recognition") or {}).get("param") or {}).get("expected")
        if raw_type != "OCR" or raw_exp != list(w.BATTLE_DISABLED_EXPECTED):
            msgs.append(f"{node_name} 的 raw 默认应为 OCR expected={list(w.BATTLE_DISABLED_EXPECTED)!r}"
                        f"（与 WuchongBattle 同形；实际 type={raw_type!r} expected={raw_exp!r}）")
        # ★不得设 max_hit★：max_hit 是【整任务】计数 —— 设了会在整局里用尽 → 第二局就不会再关自动了。
        #   一场战斗只尝试一次由 agent 侧闩锁（key=BATTLE_AUTO_ONCE_KEY）负责，不用 pipeline 计数。
        if "max_hit" in node:
            msgs.append(f"{node_name} 不得设 max_hit（整任务计数：设了会在整局里用尽 → 第二局不再关自动；"
                        f"一场一次靠 agent 侧闩锁 {w.BATTLE_AUTO_ONCE_KEY!r}）")

    # ★除这一个具名节点外★，pipeline 里不得再有任何节点带 ``scope == "battle"`` 的自动切换。
    scoped = _nodes_with_scope(pipe, scope)
    if scoped != {node_name}:
        msgs.append(f"带 scope={scope!r} 的自动切换节点应恰为 {{{node_name!r}}}，实际 {sorted(scoped)}")

    # 界面侧：「是否手操=手操」case 以战斗页作用域 + state=on 开启该节点（只在读到「开」时才去关）。
    manual_case = next((c for c in ((iface.get("option") or {}).get("是否手操") or {}).get("cases") or []
                        if c.get("name") == "手操"), None)
    if manual_case is None:
        msgs.append("选项「是否手操」缺 case「手操」（#71：手操时必须在战斗页关自动）")
    else:
        ov = (manual_case.get("pipeline_override") or {}).get(node_name) or {}
        ovrec = (ov.get("recognition") or {}).get("param") or {}
        if ovrec.get("custom_recognition") != "auto_switch_state":
            msgs.append(f"「是否手操=手操」未以 auto_switch_state 开启 {node_name}")
        else:
            rp = ovrec.get("custom_recognition_param") or {}
            if rp.get("scope") != scope:
                msgs.append(f"「是否手操=手操」的 {node_name} scope 应为 {scope!r}"
                            f"（实际 {rp.get('scope')!r}）")
            if rp.get("state") != "on":
                msgs.append(f"「是否手操=手操」的 {node_name} state 应为 'on'"
                            f"（只在读到「开」时才去关；实际 {rp.get('state')!r}）")
    return msgs


def probe_auto_switch_no_in_battle() -> bool:
    return _no_in_battle_failures() == []


# ---------------------------------------------------------------------------
# 守卫 5：跨模式 —— 覆盖所有模式编队页的「自动」检查
# ---------------------------------------------------------------------------
def _cross_mode_failures(sd: dict | None = None, abyss: dict | None = None) -> list:
    _paths()
    import auto_switch_impl as sw  # noqa: PLC0415

    sd = _pipe("special_dungeon.json") if sd is None else sd
    abyss = _pipe("abyss.json") if abyss is None else abyss
    msgs: list[str] = []

    def check_team_node(pipes: dict, entry: str, node: str, scene: str) -> None:
        spec = pipes.get(node)
        if not spec:
            msgs.append(f"{entry} 覆盖的 {node} 节点缺失（编队页「自动」检查未接线）")
            return
        if node not in (pipes.get(entry, {}).get("next") or []):
            msgs.append(f"{entry}.next 缺 {node}（编队页「自动」检查够不着）")
        rec = (spec.get("recognition") or {}).get("param") or {}
        if rec.get("custom_recognition") != "auto_switch_state":
            msgs.append(f"{node} 不是 auto_switch_state 门控（应只在「关」时命中）")
        elif _rc(spec).get("state") != "off":
            msgs.append(f"{node} 的 state 应为 off（只在当前是关时去开）")
        act = (spec.get("action") or {}).get("param") or {}
        if act.get("custom_action") != "auto_switch":
            msgs.append(f"{node} 动作不是 auto_switch")
        elif _ac(spec).get("on") is not True:
            msgs.append(f"{node} 的 on 应为 true（其他战斗都要开自动）")
        elif _ac(spec).get("scene") != scene:
            msgs.append(f"{node} 的 scene 应为 {scene!r}")

    # special（领主战家族 / 幻想 / raid / 迷宫 都经 SpecialEntry 分派）。
    check_team_node(sd, "SpecialEntry", "SpecialTeamAutoSet", "special")
    # 深渊EX（自有 hub）。
    check_team_node(abyss, "AbyssEntry", "AbyssTeamAutoSet", "abyss")

    # 跨模式夹值：非五重一律夹回「开」；只有五重能关。
    if sw.effective_auto_state("phantom", False) is not True:
        msgs.append("auto_switch 未把非五重场景夹回「开」")
    if sw.effective_auto_state("abyss", False) is not True:
        msgs.append("auto_switch 未把深渊场景夹回「开」")
    if sw.effective_auto_state("wuchong", False) is not False:
        msgs.append("auto_switch 误把五重的手动夹掉")
    return msgs


def probe_auto_switch_cross_mode_team_auto() -> bool:
    return _cross_mode_failures() == []


# ---------------------------------------------------------------------------
# 守卫 6：自动续战保持「关」（ruling ③）
# ---------------------------------------------------------------------------
def _cont_off_failures(iface: dict | None = None, pipe_wuchong: dict | None = None) -> list:
    _paths()
    iface = _interface() if iface is None else iface
    pipe = _pipe("wuchong.json") if pipe_wuchong is None else pipe_wuchong
    msgs: list[str] = []

    node = pipe.get("WuchongTeamContSet") or {}
    if _ac(node).get("on") is not False:
        msgs.append("WuchongTeamContSet 未把「自动续战」设为**关**（ruling ③）")
    if _rc(node).get("label") != "自动续战" or _rc(node).get("state") != "on":
        msgs.append("WuchongTeamContSet 应以「自动续战」+ state=on 门控（只在开着时去关）")

    block = (iface.get("option") or {}).get("是否手操") or {}
    auto_case = next((c for c in block.get("cases") or [] if c.get("name") == "自动"), None)
    if auto_case is None:
        msgs.append("选项「是否手操」缺 case「自动」")
    else:
        ov = (auto_case.get("pipeline_override") or {}).get("WuchongTeamContSet") or {}
        on = (((ov.get("action") or {}).get("param") or {}).get("custom_action_param") or {}).get("on")
        if on is not False:
            msgs.append("「自动」case 仍把「自动续战」设为开（ruling ③：功能不要打开）")

    # 「自动续战功能」确认框必须在动作里先按『取消』处理（不 dead-end）。
    impl_src = (AGENT_DIR / "auto_switch_impl.py").read_text(encoding="utf-8")
    if "dismiss_cont_dialog" not in impl_src or "取消" not in impl_src:
        msgs.append("auto_switch 未处理「自动续战功能」确认框（应出现就按取消）")
    wc_src = (AGENT_DIR / "wuchong_impl.py").read_text(encoding="utf-8")
    if "dismiss_cont_dialog" not in wc_src:
        msgs.append("wuchong_switch 未先处理「自动续战功能」确认框")

    # 「是否自动续战」默认「否」，且「否」= 不碰（节点关掉），绝不打开功能。
    cont_opt = (iface.get("option") or {}).get("是否自动续战") or {}
    if cont_opt.get("default_case") != "否":
        msgs.append("选项「是否自动续战」默认应为「否」（ruling ③）")
    no_case = next((c for c in cont_opt.get("cases") or [] if c.get("name") == "否"), None)
    if no_case is not None:
        rec = ((no_case.get("pipeline_override") or {}).get("SpecialAutoContinueSet") or {}).get("recognition") or {}
        if rec.get("type") != "OCR" or "__NONE__" not in ((rec.get("param") or {}).get("expected") or []):
            msgs.append("「是否自动续战=否」应把节点关掉（绝不碰、绝不弹确认框）")
    return msgs


def probe_auto_switch_cont_kept_off() -> bool:
    return _cont_off_failures() == []


# ---------------------------------------------------------------------------
# 守卫 7：续战锚定（ruling ①）+ 归位先返回（ruling ⑤）
# ---------------------------------------------------------------------------
def _resume_failures(pipe_wuchong: dict | None = None) -> list:
    _paths()
    pipe = _pipe("wuchong.json") if pipe_wuchong is None else pipe_wuchong
    msgs: list[str] = []
    node = pipe.get("WuchongResume") or {}
    exp = ((node.get("recognition") or {}).get("param") or {}).get("expected") or []
    if exp != ["^续战$"]:
        msgs.append(f"WuchongResume 的 OCR 未整串锚定（expected={exp}）→ 会误命中「自动续战」")
    what = _ac(node).get("what") or []
    if what != ["^续战$"]:
        msgs.append(f"WuchongResume 的点击 what 未整串锚定（what={what}）")
    return msgs


def probe_auto_switch_resume_anchored() -> bool:
    return _resume_failures() == []


#: 编队页合成 OCR（真机帧框）：SET/Party/自动续战/自动/挑战/返回。
TEAM_PAGE_ITEMS = [
    ("SET 1", [70, 457, 38, 15]),
    ("Party E", [92, 512, 97, 36]),
    ("自动续战", [18, 1062, 78, 24]),
    ("自动", [142, 1062, 43, 26]),
    ("挑战", [296, 1053, 82, 47]),
    ("返回", [30, 1246, 46, 26]),
]
EXPECTED_BACK = (30 + 46 // 2, 1246 + 26 // 2)  # [30,1246,46,26] 的中心


def _return_home_failures(rules_=None) -> list:
    _paths()
    import live_harness as ca  # noqa: PLC0415

    rules_ = rules_ if rules_ is not None else ca.RETURN_HOME_RULES
    msgs: list[str] = []
    first = None
    for rid, probe, _act in rules_:
        if probe(TEAM_PAGE_ITEMS):
            first = rid
            break
    if first != "team_page":
        msgs.append(f"编队页首命中应为 team_page（先点返回），实际 {first!r}")
        return msgs

    # 动作：读【自己识别到的『返回』框】点其中心（绝不按返回键/绝不盲点）。
    captured: list[tuple[int, int]] = []
    real_tap, real_time = ca.adb_tap, ca.time

    class _NoSleep:
        @staticmethod
        def sleep(_s):
            return None

    try:
        ca.adb_tap = lambda x, y: captured.append((int(round(x)), int(round(y))))
        ca.time = _NoSleep
        for rid, _probe, act in rules_:
            if rid == "team_page":
                act(TEAM_PAGE_ITEMS, 0)
                break
    finally:
        ca.adb_tap, ca.time = real_tap, real_time
    if not captured or captured[-1] != EXPECTED_BACK:
        msgs.append(f"编队页『返回』应点识别框中心 {EXPECTED_BACK}，实际 {captured[-1:]!r}")

    # 编队页不得被主城 / 结算抢走。
    for bad in ("main_city", "settlement"):
        for rid, probe, _act in rules_:
            if rid == bad and probe(TEAM_PAGE_ITEMS):
                msgs.append(f"编队页被 {bad} 抢走（应先点返回）")
                break
    return msgs


def probe_auto_switch_return_home_back_first() -> bool:
    return _return_home_failures() == []


# ---------------------------------------------------------------------------
# 守卫 8（三批新增）：页面范围 —— 「自动」只在【编队页 / 房间页】认，绝不在战斗 HUD 误命中
# ---------------------------------------------------------------------------
#: 真机战斗/结算画面的 OCR（720 空间；来自 tools/frames/auto_battle_hud_hit.png 的 MAA OCR）。
#: ★战斗 HUD 的「自动」[15,193,55,19] 与编队页底栏的「自动」[142,1062,43,26] 是两个不同控件★。
BATTLE_HUD_ITEMS = [
    ("自动", [15, 193, 55, 19]),
    ("×2", [50, 177, 28, 19]),
    ("技能", [25, 245, 35, 21]),
    ("自动", [26, 260, 34, 21]),
    ("开", [33, 280, 18, 18]),
    ("时间 09:55", [37, 1225, 128, 32]),
    ("分数  00166756407", [195, 1222, 241, 36]),
    ("CLEAR", [150, 486, 416, 132]),
    ("100%", [215, 28, 78, 24]),
]
#: 编队页 OCR（720 空间；来自真机领主战成员编队页）：「自动」[142,1062,43,26] + 开关状态字 开。
TEAM_PAGE_AUTO_ITEMS = [
    ("Party E", [92, 512, 95, 36]),
    ("自动续战", [15, 1061, 82, 28]),
    ("自动", [142, 1062, 43, 26]),
    ("开", [140, 1105, 24, 24]),
    ("挑战", [296, 1053, 82, 47]),
    ("编成", [513, 952, 46, 26]),
    ("SET编辑", [596, 952, 76, 24]),
    ("返回", [30, 1246, 46, 26]),
]


class _RecoCtx:
    """最小 `context`：只满足 ``run_recognition`` —— OcrTask → 给定 items；模板 → 不命中。"""

    def __init__(self, items):
        self._items = list(items)

    def run_recognition(self, entry, image):
        if entry == "OcrTask":
            return types.SimpleNamespace(
                hit=bool(self._items),
                all_results=[types.SimpleNamespace(text=t, box=list(b)) for t, b in self._items],
                best_result=None,
            )
        return None  # AutoSwitchLabel：战斗 HUD 帧没有裁片


def _page_scope_failures() -> list:
    _paths()
    import numpy as np  # noqa: PLC0415

    import auto_switch_impl as sw  # noqa: PLC0415

    msgs: list[str] = []

    # (a) 战斗 HUD 的「自动」（两处）都不是编队页开关 → 两条判据都不成立。
    for box in ([15, 193, 55, 19], [26, 260, 34, 21]):
        if sw.is_team_auto_control(BATTLE_HUD_ITEMS, sw.AUTO_LABEL, box):
            msgs.append(f"战斗 HUD 的「自动」{box} 被当成编队页开关（门控未限定页面）")
    if sw.page_is_team(BATTLE_HUD_ITEMS):
        msgs.append("战斗/结算画面被认成编队页（页面锚点判据太宽）")

    # (b) 编队页的「自动」必须被认成开关。
    if not sw.is_team_auto_control(TEAM_PAGE_AUTO_ITEMS, sw.AUTO_LABEL, [142, 1062, 43, 26]):
        msgs.append("编队页的「自动」未被认成开关（页面范围判据太严）")

    # (c) 行为：战斗 HUD 帧上 `auto_switch_state`（state=off）**不得命中**；
    #     编队页帧上必须命中（编队页帧的探针读成「关」）。
    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    argv = types.SimpleNamespace(
        image=img, custom_recognition_param='{"label":"自动","state":"off","ocr_entry":"OcrTask"}')
    rec = sw.AutoSwitchStateRecognition()
    hud_res = rec.analyze(_RecoCtx(BATTLE_HUD_ITEMS), argv)
    if getattr(hud_res, "box", None) is not None:
        msgs.append("战斗 HUD 帧上 auto_switch_state 仍命中（应在页面范围外返回未命中）")
    team_res = rec.analyze(_RecoCtx(TEAM_PAGE_AUTO_ITEMS), argv)
    if getattr(team_res, "box", None) is None:
        msgs.append("编队页帧上 auto_switch_state 未命中（state=off 时应命中）")

    # (d) 定位不到必须【可见失败】：动作里存在 [auto_switch][FAIL] 标记，旧「→ 不动」静默返回已消除。
    impl_src = (AGENT_DIR / "auto_switch_impl.py").read_text(encoding="utf-8")
    if "[auto_switch][FAIL]" not in impl_src:
        msgs.append("定位不到未可见失败（缺 [auto_switch][FAIL] 标记）")
    if "均未命中）→ 不动" in impl_src:
        msgs.append("定位不到仍是静默「→ 不动」（应改为可见失败）")

    # (e) 根因证据帧留档。
    for rel in (FRAME_AUTO_BATTLE_HUD, FRAME_AUTO_BATTLE_ACTION):
        if not (REPO_ROOT / rel).is_file():
            msgs.append(f"根因证据帧缺失：{rel}")
    return msgs


def probe_auto_switch_page_scoped() -> bool:
    return _page_scope_failures() == []


# ---------------------------------------------------------------------------
# 守卫 9（#71 新增）：★两处同名控件互不认领★ —— 战斗 HUD 的「自动」与编队页的「自动」
# ---------------------------------------------------------------------------
# ★这是本票最该防的回归★：战斗 HUD 的「自动」``[15,193,55,19]``、同屏「技能自动」
# ``[26,260,34,21]``、编队页底栏的「自动」``[142,1062,43,26]`` —— 文字同名、位置各异。
# 若哪个作用域判据放宽，就会**互相认领**：要么编队页作用域去点战斗 HUD（二批 P0 回归），
# 要么战斗页作用域去点编队页/技能自动（本票新风险）。逐条钉死。
def _synthetic_battle_frame(on: bool):
    """合成一张 720×1280 的战斗 HUD 帧（**按 MAA 约定喂 BGR**）：探针区涂青绿（开）或灰（关）。

    真机 ON 帧的按钮填充实测均值 RGB ≈ (93,191,183) → BGR 存 (183,191,93)；
    灰 = 三通道同值 128（青绿判据 ``g-r>40 ∧ b-r>40`` 必不成立 → 读数=关）。
    """
    import numpy as np  # noqa: PLC0415

    import auto_switch_impl as sw  # noqa: PLC0415

    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    x0, y0, x1, y1 = sw.battle_probe_for(sw.BATTLE_AUTO_LABEL, BATTLE_AUTO_BOX_720)
    img[y0:y1, x0:x1] = (183, 191, 93) if on else (128, 128, 128)
    return img


def _battle_scope_mutex_failures() -> list:
    """两处同名控件互不认领（战斗页 ``[15,193,55,19]`` ↔ 编队页 ``[142,1062,43,26]``）。"""
    _paths()
    import auto_switch_impl as sw  # noqa: PLC0415

    msgs: list[str] = []
    label = sw.BATTLE_AUTO_LABEL
    battle_box = list(BATTLE_AUTO_BOX_720)
    skill_box = [26, 260, 34, 21]     # 战斗 HUD 同屏「技能自动」
    team_box = [142, 1062, 43, 26]    # 编队页底栏「自动」

    # (a) 战斗页作用域：只认战斗 HUD 的那一个「自动」。
    if sw.is_battle_auto_control(BATTLE_HUD_ITEMS, label, battle_box) is not True:
        msgs.append("战斗 HUD 的「自动」未被战斗页作用域认（两处同名控件之一漏掉）")
    if sw.is_battle_auto_control(BATTLE_HUD_ITEMS, label, skill_box):
        msgs.append("同屏「技能自动」被当成战斗页「自动」（BATTLE_AUTO_LABEL_ROI 未排开）")
    if sw.is_battle_auto_control(BATTLE_HUD_ITEMS, label, team_box):
        msgs.append("编队页位置的「自动」在战斗 HUD 帧上被战斗页作用域认（ROI 太宽）")
    if sw.is_battle_auto_control(TEAM_PAGE_AUTO_ITEMS, label, team_box):
        msgs.append("编队页帧被战斗页作用域认（无战斗 HUD 锚点却命中）")

    # (b) 编队页作用域：绝不认战斗 HUD 的「自动」（既有页面范围守卫的语义，别退化）。
    if sw.is_team_auto_control(BATTLE_HUD_ITEMS, label, battle_box):
        msgs.append("战斗 HUD 的「自动」被编队页作用域认（页面判据退化）")
    if not sw.is_team_auto_control(TEAM_PAGE_AUTO_ITEMS, label, team_box):
        msgs.append("编队页的「自动」未被编队页作用域认（页面判据退化）")

    # (c) 页面判别本身：两条锚点判据各管各的。
    if not sw.battle_hud_is_present(BATTLE_HUD_ITEMS):
        msgs.append("战斗 HUD 帧未被认成战斗页（BATTLE_HUD_ANCHORS 判据太严）")
    if sw.battle_hud_is_present(TEAM_PAGE_AUTO_ITEMS):
        msgs.append("编队页帧被认成战斗页（BATTLE_HUD_ANCHORS 判据太宽）")

    # (d) 行为：驱动**真实** AutoSwitchStateRecognition（scope=battle）。
    rec = sw.AutoSwitchStateRecognition()
    param = json.dumps({"label": label, "state": "on", "scope": "battle", "ocr_entry": "OcrTask"})
    hit = rec.analyze(_RecoCtx(BATTLE_HUD_ITEMS), types.SimpleNamespace(
        image=_synthetic_battle_frame(True), custom_recognition_param=param))
    if getattr(hit, "box", None) is None:
        msgs.append("战斗 HUD 帧 + 探针涂青绿（读数=开）上 scope=battle 未命中（该命中）")
    miss = rec.analyze(_RecoCtx(BATTLE_HUD_ITEMS), types.SimpleNamespace(
        image=_synthetic_battle_frame(False), custom_recognition_param=param))
    if getattr(miss, "box", None) is not None:
        msgs.append("战斗 HUD 帧 + 探针涂灰（读数=关）上 scope=battle 误命中（state=on 时不该命中）")
    team_res = rec.analyze(_RecoCtx(TEAM_PAGE_AUTO_ITEMS), types.SimpleNamespace(
        image=_synthetic_battle_frame(True), custom_recognition_param=param))
    if getattr(team_res, "box", None) is not None:
        msgs.append("编队页帧上 scope=battle 误命中（战斗页作用域未与编队页互斥）")
    return msgs


def probe_auto_switch_battle_scope_mutex() -> bool:
    return _battle_scope_mutex_failures() == []


# ---------------------------------------------------------------------------
# 守卫 10（#71 新增）：★战斗页读状态的标定★（真机 ON 帧 + 合成反例）
# ---------------------------------------------------------------------------
def _battle_frame_720():
    """加载真机战斗 ON 帧并归一到 720×1280，**按 MAA 约定返回 BGR** ndarray。

    MAA 原生 screencap 是 BGR（见 ``agent/auto_switch_impl.to_rgb_array`` 的通道序说明），
    所以喂给 ``read_battle_auto_state`` 前必须 ``[:, :, ::-1]``（照 :func:`_frame_720` 的写法）。
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    im = Image.open(REPO_ROOT / FRAME_AUTO_BATTLE_HUD)
    if im.size == (1080, 1920):
        im = im.resize((720, 1280), Image.LANCZOS)
    rgb = im.convert("RGB")
    return np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])


def _battle_state_calibrated_failures(state_fn=None) -> list:
    """★诚实缺口★：战斗页「自动=关」的真机帧**仓库里一张都没有** —— 关态只按 ON 帧 + 合成反例标定，
    真机校准待补 3 帧（见 ADR ``docs/adr/0004-battle-page-auto-off-manual-only.md``）。本守卫**不假装已校准**：
    它只钉「ON 帧读开 ∧ 涂灰读关 ∧ 取不到读 None」，不因缺帧变红。
    """
    _paths()
    import auto_switch_impl as sw  # noqa: PLC0415

    frame = REPO_ROOT / FRAME_AUTO_BATTLE_HUD
    if not frame.is_file():
        # ★根因证据帧留档★（照 _page_scope_failures 的写法）：缺帧 = 红（无 ON 帧则标定无从谈起）。
        return [f"根因证据帧缺失：{FRAME_AUTO_BATTLE_HUD}（战斗页读状态标定唯一真机证据）"]

    read = state_fn or sw.read_battle_auto_state
    msgs: list[str] = []
    img = _battle_frame_720()
    box = list(BATTLE_AUTO_BOX_720)

    if read(img, sw.BATTLE_AUTO_LABEL, box) is not True:
        msgs.append("真机战斗 ON 帧未读出「开」（青绿探针判据对不上真机帧）")

    # 合成反例：把探针区涂灰 → 必须读成「关」（照既有 state-read 守卫的写法）。
    probe = sw.battle_probe_for(sw.BATTLE_AUTO_LABEL, box)
    off = img.copy()
    x0, y0, x1, y1 = probe
    off[max(0, y0):y1, max(0, x0):x1] = 128
    if read(off, sw.BATTLE_AUTO_LABEL, box) is not False:
        msgs.append("把战斗页探针区涂灰后未读出「关」（合成反例）")

    # 探针取不到（框在画面外 → 裁剪为空）→ 必须 None：★判不出 ≠ 关★。
    if read(img, sw.BATTLE_AUTO_LABEL, [2000, 2000, 43, 26]) is not None:
        msgs.append("探针区取不到时未返回 None（「判不出」被错当成开/关）")
    return msgs


def probe_auto_switch_battle_state_calibrated() -> bool:
    return _battle_state_calibrated_failures() == []


# ---------------------------------------------------------------------------
# 守卫 11（#71 新增）：★快照 ↔ 真源 pin★ —— ``_Snapshot`` 里的冻结值不得与 ``scene.auto_switch`` 漂移
# ---------------------------------------------------------------------------
#: (``scene.auto_switch`` 属性名, ``agent/auto_switch_impl`` 模块级快照常量名)。既有的与 #71 的一并 pin。
SNAPSHOT_PAIRS: tuple[tuple[str, str], ...] = (
    ("AUTO_LABEL", "_AUTO_LABEL_SNAPSHOT"),
    ("AUTO_LABEL_PATTERNS", "_AUTO_LABEL_PATTERNS_SNAPSHOT"),
    ("AUTO_LABEL_TEMPLATES", "_AUTO_LABEL_TEMPLATES_SNAPSHOT"),
    ("AUTO_TEMPLATE_THRESHOLD", "_AUTO_TEMPLATE_THRESHOLD_SNAPSHOT"),
    ("AUTO_TEMPLATE_NODE", "_AUTO_TEMPLATE_NODE_SNAPSHOT"),
    ("CONT_LABEL", "_CONT_LABEL_SNAPSHOT"),
    ("AUTO_ON_RATIO", "_AUTO_ON_RATIO_SNAPSHOT"),
    ("PROBE_OFFSETS", "_PROBE_OFFSETS_SNAPSHOT"),
    ("CONT_DIALOG_TITLE", "_CONT_DIALOG_TITLE_SNAPSHOT"),
    ("CONT_DIALOG_PATTERNS", "_CONT_DIALOG_PATTERNS_SNAPSHOT"),
    ("CONT_DIALOG_CANCEL_PATTERNS", "_CONT_DIALOG_CANCEL_SNAPSHOT"),
    ("TEAM_PAGE_ANCHORS", "_TEAM_PAGE_ANCHORS_SNAPSHOT"),
    ("SWITCH_STATE_PATTERNS", "_SWITCH_STATE_PATTERNS_SNAPSHOT"),
    ("BATTLE_HUD_ANCHORS", "_BATTLE_HUD_ANCHORS_SNAPSHOT"),
    ("BATTLE_AUTO_LABEL", "_BATTLE_AUTO_LABEL_SNAPSHOT"),
    ("BATTLE_AUTO_LABEL_ROI", "_BATTLE_AUTO_LABEL_ROI_SNAPSHOT"),
    ("BATTLE_AUTO_PROBE_OFFSETS", "_BATTLE_AUTO_PROBE_OFFSETS_SNAPSHOT"),
    ("BATTLE_AUTO_ON_RATIO", "_BATTLE_AUTO_ON_RATIO_SNAPSHOT"),
    ("BATTLE_AUTO_FILL_DR", "_BATTLE_AUTO_FILL_DR_SNAPSHOT"),
    ("BATTLE_AUTO_TEMPLATES", "_BATTLE_AUTO_TEMPLATES_SNAPSHOT"),
)
#: ``_Snapshot`` 类属性名（与 ``scene.auto_switch`` 同名）—— 安装态回退用的另一处副本，也要 pin。
SNAPSHOT_CLASS_ATTRS: tuple[str, ...] = (
    "AUTO_LABEL", "AUTO_LABEL_PATTERNS", "AUTO_LABEL_TEMPLATES", "AUTO_TEMPLATE_THRESHOLD",
    "AUTO_TEMPLATE_NODE", "CONT_LABEL", "AUTO_ON_RATIO", "PROBE_OFFSETS", "CONT_DIALOG_TITLE",
    "CONT_DIALOG_PATTERNS", "CONT_DIALOG_CANCEL_PATTERNS", "TEAM_PAGE_ANCHORS", "SWITCH_STATE_PATTERNS",
    "BATTLE_HUD_ANCHORS", "BATTLE_AUTO_LABEL", "BATTLE_AUTO_LABEL_ROI", "BATTLE_AUTO_PROBE_OFFSETS",
    "BATTLE_AUTO_ON_RATIO", "BATTLE_AUTO_FILL_DR", "BATTLE_AUTO_TEMPLATES",
)


def _snapshot_pinned_failures() -> list:
    """``agent/auto_switch_impl._Snapshot``（安装态回退）必须与 ``scene.auto_switch`` 真源**逐项**一致。"""
    _paths()
    import auto_switch_impl as impl  # noqa: PLC0415
    from scene import auto_switch as cfg  # noqa: PLC0415

    msgs: list[str] = []
    for cfg_name, snap_name in SNAPSHOT_PAIRS:
        if not hasattr(impl, snap_name):
            msgs.append(f"agent/auto_switch_impl 缺快照常量 {snap_name}（真源 {cfg_name} 无回退）")
            continue
        snap = getattr(impl, snap_name)
        real = getattr(cfg, cfg_name, None)
        if snap != real:
            msgs.append(f"快照漂移：impl.{snap_name} = {snap!r} ≠ scene.auto_switch.{cfg_name} = {real!r}")

    snapshot_cls = getattr(impl, "_Snapshot", None)
    if snapshot_cls is None:
        msgs.append("agent/auto_switch_impl 缺 _Snapshot（安装态回退类）")
    else:
        for attr in SNAPSHOT_CLASS_ATTRS:
            if not hasattr(snapshot_cls, attr):
                msgs.append(f"_Snapshot 缺属性 {attr}（与 scene.auto_switch 不同源）")
                continue
            cls_val = getattr(snapshot_cls, attr)
            real = getattr(cfg, attr, None)
            if cls_val != real:
                msgs.append(f"快照漂移：impl._Snapshot.{attr} = {cls_val!r} "
                            f"≠ scene.auto_switch.{attr} = {real!r}")
    return msgs


def probe_auto_switch_snapshot_pinned() -> bool:
    return _snapshot_pinned_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _broken_locate_fixed(items, label=None, template_box=None):
    """坏实现：永远返回编队页的固定框（模拟「假定固定坐标」）。"""
    return list(AUTO_BOX_720)


def _broken_locate_trusts_template(items, label=None, template_box=None):
    """坏实现：盲信模板命中（不校验是否被「自动续战」覆盖 / 是否与 OCR 矛盾）。"""
    return list(template_box) if template_box is not None else None


def _broken_state_always_on(image, label, box):
    """坏实现：状态永远读成「开」。"""
    return True


def prove_red() -> bool:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    print("hooks_auto_outside prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_auto_switch_located() is True
        and probe_auto_switch_template_distinct() is True
        and probe_auto_switch_state_read_correct() is True
        and probe_auto_switch_no_in_battle() is True
        and probe_auto_switch_cross_mode_team_auto() is True
        and probe_auto_switch_cont_kept_off() is True
        and probe_auto_switch_resume_anchored() is True
        and probe_auto_switch_return_home_back_first() is True
        and probe_auto_switch_page_scoped() is True
        and probe_auto_switch_battle_scope_mutex() is True
        and probe_auto_switch_battle_state_calibrated() is True
        and probe_auto_switch_snapshot_pinned() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：十二个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    # ①定位：坏实现（固定坐标）必须被抓到（房间页位置对不上）。
    red = len(_locate_failures(locate_fn=_broken_locate_fixed)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 定位：固定坐标（房间页位置对不上）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ①b 定位：坏实现（盲信模板，不校验「自动续战」误命中）必须被抓到。
    red = len(_locate_failures(locate_fn=_broken_locate_trusts_template)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 定位：盲信模板（不校验误命中）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ②模板：把「自动」位置换成「自动续战」位置（错标签）必须被抓到。
    red = len(_template_failures(auto_box=CONT_BOX_720)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 模板：拿「自动续战」位置当命中点 -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ②b ★#111★ 兄弟窗口写回「真机 OCR 框」x=18（偏 1px）必须被抓到 ——
    #     这正是旧守卫**碰巧绿**的原因（x=18 点测 0.4536 < 0.75，而滑窗尖峰在 x=17 = 0.8964）。
    red = len(_template_failures(cont_box=[18, 1062, 43, 26])) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 模板：兄弟窗口写回 x=18（偏 1px，点测口径）"
          f"-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ②c ★#111★ 把 roi 放宽到覆盖兄弟那一栏（真实源内存改动，恢复现场）必须被抓到 ——
    #     证明本守卫真的在按「框架语义」复算，而不是只比两个点。
    from scene import auto_switch as cfg_auto  # noqa: PLC0415

    real_roi = cfg_auto.AUTO_LABEL_ROI
    try:
        cfg_auto.AUTO_LABEL_ROI = (0, 1030, 230, 90)
        red = len(_template_failures()) > 0
    finally:
        cfg_auto.AUTO_LABEL_ROI = real_roi
    print(f"  [{'PASS' if red else 'FAIL'}] 模板：roi 放宽到覆盖「自动续战」那一栏"
          f"-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ③状态：坏实现（永远读成开）必须被抓到。
    red = len(_state_failures(state_fn=_broken_state_always_on)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 状态：永远读成「开」-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ④战斗内自动：把 AutoGuard 塞回 hub 必须被抓到。
    pipe = _pipe("wuchong.json")
    tainted = dict(pipe)
    tainted["WuchongBattleAutoGuard"] = {"recognition": {"type": "DirectHit", "param": {}}}
    red = len(_no_in_battle_failures(pipe=tainted)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 战斗内自动：塞回 AutoGuard 节点 -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑤跨模式：把 SpecialTeamAutoSet 从 SpecialEntry.next 摘掉必须被抓到。
    sd = _pipe("special_dungeon.json")
    sd_broken = json.loads(json.dumps(sd))
    sd_broken["SpecialEntry"]["next"] = [x for x in sd_broken["SpecialEntry"]["next"] if x != "SpecialTeamAutoSet"]
    red = len(_cross_mode_failures(sd=sd_broken)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 跨模式：摘掉 SpecialTeamAutoSet -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑥自动续战：把 WuchongTeamContSet 改回「开」必须被抓到。
    pipe2 = json.loads(json.dumps(pipe))
    pipe2["WuchongTeamContSet"]["action"]["param"]["custom_action_param"]["on"] = True
    red = len(_cont_off_failures(pipe_wuchong=pipe2)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 自动续战：改回「开」-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑦续战锚定：把 WuchongResume 改回裸「续战」必须被抓到。
    pipe3 = json.loads(json.dumps(pipe))
    pipe3["WuchongResume"]["recognition"]["param"]["expected"] = ["续战"]
    red = len(_resume_failures(pipe_wuchong=pipe3)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 续战锚定：改回裸「续战」-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑧归位先返回：把 team_page 从有序表摘掉必须被抓到。
    _paths()
    import live_harness as ca  # noqa: PLC0415

    no_team = tuple(item for item in ca.RETURN_HOME_RULES if item[0] != "team_page")
    red = len(_return_home_failures(rules_=no_team)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] 归位：摘掉 team_page 规则 -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑨页面范围：把页面判据改成「处处是编队页」（= 回到三批前的全屏形态）必须被抓到。
    import auto_switch_impl as sw  # noqa: PLC0415

    real_is = sw.is_team_auto_control
    real_page = sw.page_is_team
    try:
        sw.is_team_auto_control = lambda *a, **k: True
        sw.page_is_team = lambda *a, **k: True
        red = len(_page_scope_failures()) > 0
    finally:
        sw.is_team_auto_control = real_is
        sw.page_is_team = real_page
    print(f"  [{'PASS' if red else 'FAIL'}] 页面范围：取消页面判据（全屏认自动）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑩#71 收窄（a）：把 WuchongBattleAutoOff 的 on 改成 true（★只关不开被破★）必须被抓到。
    auto_node = w.BATTLE_AUTO_NODE
    pipe_on = json.loads(json.dumps(pipe))
    pipe_on[auto_node]["action"]["param"]["custom_action_param"]["on"] = True
    red = len(_no_in_battle_failures(pipe=pipe_on)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] #71：战斗页关自动改成 on=true（开了自动）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑩b #71 收窄（b）：从 WuchongEntry.next 摘掉战斗页关自动节点（手操时够不着）必须被抓到。
    pipe_next = json.loads(json.dumps(pipe))
    pipe_next["WuchongEntry"]["next"] = [
        x for x in pipe_next["WuchongEntry"]["next"] if x != auto_node]
    red = len(_no_in_battle_failures(pipe=pipe_next)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] #71：摘掉 {auto_node}（够不着）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑩c #71 收窄（c）：把节点 recognition 从战斗页 raw 默认改回 wuchong_state（非 __NONE__）必须被抓到。
    pipe_rec = json.loads(json.dumps(pipe))
    pipe_rec[auto_node]["recognition"] = {"type": "Custom", "param": {
        "custom_recognition": "wuchong_state",
        "custom_recognition_param": {"state": "wuchong_battle", "ocr_entry": "OcrTask"}}}
    red = len(_no_in_battle_failures(pipe=pipe_rec)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] #71：raw 默认改回 wuchong_state（非 __NONE__）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑩d #71 收窄（d）：给它加 max_hit: 1（整任务计数 → 第二局不再关）必须被抓到。
    pipe_hit = json.loads(json.dumps(pipe))
    pipe_hit[auto_node]["max_hit"] = 1
    red = len(_no_in_battle_failures(pipe=pipe_hit)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] #71：给战斗页关自动加 max_hit -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑩e #71 收窄（e）：把「是否手操=手操」的 scope 改回 team（不在战斗页作用域）必须被抓到。
    iface = _interface()
    iface_team = json.loads(json.dumps(iface))
    manual_case = next(c for c in iface_team["option"]["是否手操"]["cases"] if c["name"] == "手操")
    manual_case["pipeline_override"][auto_node]["recognition"]["param"][
        "custom_recognition_param"]["scope"] = "team"
    red = len(_no_in_battle_failures(iface=iface_team)) > 0
    print(f"  [{'PASS' if red else 'FAIL'}] #71：手操 case 的 scope 改回 team -> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑪#71 两处同名控件：让 is_battle_auto_control 恒真（战斗页作用域不再排开）必须被抓到。
    import auto_switch_impl as sw2  # noqa: PLC0415

    real_battle = sw2.is_battle_auto_control
    try:
        sw2.is_battle_auto_control = lambda *a, **k: True
        red = len(_battle_scope_mutex_failures()) > 0
    finally:
        sw2.is_battle_auto_control = real_battle
    print(f"  [{'PASS' if red else 'FAIL'}] #71：is_battle_auto_control 恒真（乱认战斗页自动）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑪b #71 两处同名控件：让 is_team_auto_control 对战斗 HUD 也恒真（= 三批前的全屏形态）必须被抓到。
    real_team = sw2.is_team_auto_control
    try:
        sw2.is_team_auto_control = lambda *a, **k: True
        red = len(_battle_scope_mutex_failures()) > 0
    finally:
        sw2.is_team_auto_control = real_team
    print(f"  [{'PASS' if red else 'FAIL'}] #71：is_team_auto_control 恒真（认领战斗 HUD）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑫#71 读状态标定：让 read_battle_auto_state 恒返回 True（合成反例那条被破）必须被抓到。
    real_read = sw2.read_battle_auto_state
    try:
        sw2.read_battle_auto_state = lambda *a, **k: True
        red = len(_battle_state_calibrated_failures()) > 0
    finally:
        sw2.read_battle_auto_state = real_read
    print(f"  [{'PASS' if red else 'FAIL'}] #71：read_battle_auto_state 恒 True（灰也读成开）-> {'红' if red else '仍绿'}")
    checks.append(red)

    # ⑬#71 快照 pin：把快照常量故意改坏（与真源漂移）必须被抓到。
    real_ratio_snap = sw2._BATTLE_AUTO_ON_RATIO_SNAPSHOT
    try:
        sw2._BATTLE_AUTO_ON_RATIO_SNAPSHOT = 0.99
        red = len(_snapshot_pinned_failures()) > 0
    finally:
        sw2._BATTLE_AUTO_ON_RATIO_SNAPSHOT = real_ratio_snap
    print(f"  [{'PASS' if red else 'FAIL'}] #71：快照常量与真源漂移 -> {'红' if red else '仍绿'}")
    checks.append(red)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "auto-outside-locates-auto-switch",
        "#56",
        "「自动」按钮按【定位】（模板/OCR 整串）而非固定坐标；不同页面位置都定位到自己的框；点识别框中心",
        probe_auto_switch_located,
    ),
    (
        "auto-outside-template-distinct",
        "#56 / #111",
        "「自动」标签裁片在真机帧上**滑窗**命中「自动」（1.0000@x=142）；兄弟「自动续战」的滑窗"
        "尖峰 **0.8964@x=17**（★窗口值必须是实测尖峰，旧值 x=18 只有 0.4536 → 点测会骗人★）"
        "也过 0.75 阈值 ⇒ 模板本身分不开，distinctness 由真源 roi+order_by 提供："
        "按框架语义（roi 内唯一候选 + order_by + index:0）复算必须选到真「自动」",
        probe_auto_switch_template_distinct,
    ),
    (
        "auto-outside-state-read-correct",
        "#56",
        "由定位框推出的探针读对开/关（开=橙、关=灰）",
        probe_auto_switch_state_read_correct,
    ),
    (
        "auto-outside-no-in-battle-switch",
        "#56 / #71",
        "战斗内不再有自动切换（无 AutoGuard / pause_auto / open_pause / close_pause / battle_pause）"
        "；★#71 收窄★：禁令全留，另加白名单 —— 战斗页关自动只允许【一个具名、只关不开、只对五重】的出口"
        "（scene.wuchong.BATTLE_AUTO_NODE 在 WuchongEntry.next、on=False、raw=__NONE__、无 max_hit；"
        "且 pipeline 里带 scope=battle 的节点恰为该节点一个）",
        probe_auto_switch_no_in_battle,
    ),
    (
        "auto-outside-cross-mode-team-auto",
        "#56",
        "覆盖所有模式编队页：SpecialTeamAutoSet（special 分派）+ AbyssTeamAutoSet（深渊EX）；非五重夹回「开」",
        probe_auto_switch_cross_mode_team_auto,
    ),
    (
        "auto-outside-cont-kept-off",
        "#56",
        "自动续战保持「关」（ruling ③）：五重设关 + 是否自动续战默认「否」+ 确认框出现即按取消",
        probe_auto_switch_cont_kept_off,
    ),
    (
        "auto-outside-resume-anchored",
        "#56",
        "「续战」OCR 整串锚定（ruling ①），绝不误命中「自动续战」",
        probe_auto_switch_resume_anchored,
    ),
    (
        "auto-outside-return-home-back-first",
        "#56",
        "归位在编队页先点返回（点识别到的返回框中心），再走既有主城判据（ruling ⑤）",
        probe_auto_switch_return_home_back_first,
    ),
    (
        "auto-outside-page-scoped",
        "#56",
        "「自动」只在【编队页/房间页】认（页面锚点 ∨ 开关状态字）；战斗 HUD 的「自动」"
        "（不同控件、不同位置）永不命中；定位不到可见失败（[auto_switch][FAIL]）",
        probe_auto_switch_page_scoped,
    ),
    (
        "auto-outside-battle-scope-mutex",
        "#71",
        "★两处同名控件互不认领★：战斗页作用域只认战斗 HUD 的「自动」[15,193,55,19]（不认同屏"
        "「技能自动」/编队页位置），编队页作用域只认编队页「自动」[142,1062,43,26]（不认战斗 HUD）；"
        "驱动真实 auto_switch_state(scope=battle)：战斗 HUD 帧 + 合成图涂青绿=开→命中、涂灰=关(state=on)"
        "→不命中、编队页帧→不命中",
        probe_auto_switch_battle_scope_mutex,
    ),
    (
        "auto-outside-battle-state-calibrated",
        "#71",
        "战斗页读状态标定：真机 ON 帧 tools/frames/auto_battle_hud_hit.png 读 True；探针区涂灰读 False；"
        "探针取不到读 None（判不出≠关）。★诚实缺口★：战斗页「自动=关」的真机帧仓库里一张都没有，"
        "关态只按 ON 帧 + 合成反例标定，真机校准待补 3 帧（见 ADR 0004）",
        probe_auto_switch_battle_state_calibrated,
    ),
    (
        "auto-outside-snapshot-pinned",
        "#71",
        "agent/auto_switch_impl._Snapshot 冻结快照与 scene.auto_switch 真源逐项一致"
        "（既有 AUTO_LABEL/PROBE_OFFSETS/TEAM_PAGE_ANCHORS… 与 #71 的 BATTLE_* 全部 pin）",
        probe_auto_switch_snapshot_pinned,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
