# -*- coding: utf-8 -*-
"""#99：统一坐标系 —— 写死的坐标必须落在 720x1280 基准空间（静态越界守卫）。

## 为什么（两次真实的混淆）

1. 设备跑 **1080x1920**（运维实测 720P 会乱码），而 MaaFramework 的识别/点击空间是
   **720x1280**，所以 **1080 → 720 是 ÷1.5**。谁把原图 OCR box 当 720 用，点出来的位置就偏 1.5 倍。
   `tools/contract_hooks/hooks_86.py` 的 docstring 记的就是这一次（那批 `今天剩余次数`
   的 box `[381, 922, 319, 42]` 至今是**原图像素**，只因判据只比对文本才没炸）。
2. `scene/team.py` 的 `TEAM_SET_ROW_Y = 30` 是 **B 类编辑器页**的值，**A 类战前编队页**是 y≈457 ——
   同一个「SET 行」在两页不同 y（#91 标定 / 决策 D10）。

坐标空间的**真源是 `scene/pixels.py`**（换算 + `assert_base_box` / `assert_base_xy`）；
本文件只做**静态越界守卫**，不换算、不改数据。

## 契约

- **P1 pipeline 坐标落在 720x1280**：`assets/resource/pipeline/*.json` 里每个节点下的
  `roi` / `box` / `target` 数字字面量都必须在基准空间内：
  `roi` / `box` 是 `[x, y, w, h]`（`x/w <= 720`、`y/h <= 1280`，且整框 `x+w <= 720`、`y+h <= 1280`），
  `target` 是 `[x, y]` 点（`x <= 720`、`y <= 1280`）。越界报「文件 + 节点 + 字段 + 数值」。
  `target_offset` 是**相对偏移**（可以为负），`target: true` 是「点识别框中心」、
  `target: "节点名"` 是引用 —— 三种都不是绝对坐标，跳过（见 `COORD_KEYS`）。
- **P2 scene 字面量不是原图像素**：`scene/*.py` 里形如 `[x, y, w, h]` / `(x, y, w, h)` 的
  四整数字面量，任一槽位超过自己的轴（第 1/3 槽 720，第 2/4 槽 1280）→ 红。
  这个判据**与写法约定无关**（写 `(x1,y1,x2,y2)` 的槽位上限也是同一组），所以不会因为
  「这是点还是框」而漏；**负数不判**（偏移量合法，如 `scene/auto_switch.py` 的
  `AUTO_LABEL = (-15, 41, 17, 70)`）。跨行书写的字面量也能抓到（整文件匹配后回算行号）。

## 已登记欠账（ratchet：只减不增）

#99 落地时全仓普查到 **19 处既存越界 roi**（pipeline 数据**不允许**在本票里改，所以登记在
:data:`KNOWN_BASE_OVERFLOW`，不是「通过」）。规则照 #84 的 `max_hit` ratchet：

- **新写**一个越界 → 无豁免 → 直接红；
- 登记的条目**治好了 / 节点删了** → 「账本陈旧」红，逼着删账；
- 登记的**数值与现状不符** → 红（有人改了数据但没对账）。

## 本票没做（写明，别当成已覆盖）

- 票 #99 正文的「注释里出现 `box=` 但没标空间 → 红」这一条**没实现**：仓里
  `scene/auto_switch.py` / `scene/lord_battle.py` / `scene/stamina.py` 现有若干 `box=` 注释
  本来就没标空间，一上就全红，属于又一次全仓注释普查，不属本票边界（本票只做坐标越界）。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SCENE_DIR = REPO_ROOT / "scene"

#: pipeline 里写死**绝对**像素的三个字段（`target_offset` / `box_index` 之类不在内）。
COORD_KEYS = ("roi", "box", "target")

#: 欠账分类（只影响报错措辞与自查输出）。
DEBT_OVER = "over"
DEBT_OUT = "out"
DEBT_CLASS_TEXT = {
    DEBT_OVER: "值越轴：某个值本身超过自己的轴（如 h=1300 > 1280）—— 写法就是错的，得收紧",
    DEBT_OUT: "框出界：各值都在轴内，但 x+w > 720 / y+h > 1280 —— 依赖框架把 roi 裁到帧内，应改成合法框",
}

#: 既存越界欠账：#99 普查结果（19 条）。**只减不增**，见模块 docstring。
#: 键 = (pipeline 文件名, 节点名, 节点内字段路径)；值 = (登记时的数值, 欠账分类)。
KNOWN_BASE_OVERFLOW: dict[tuple[str, str, str], tuple[tuple[int, ...], str]] = {
    # ---- 值越轴：h 写成 1300（整屏高也只有 1280，不是原图像素就是胡写）----
    ("side_story.json", "SideRoomCopyText", "recognition.param.roi"): ((430, 0, 290, 1300), DEBT_OVER),
    ("side_story.json", "SideRoomPowerText", "recognition.param.roi"): ((430, 0, 290, 1300), DEBT_OVER),
    ("special_dungeon.json", "SpecialRoomCopyText", "recognition.param.roi"): ((430, 0, 290, 1300), DEBT_OVER),
    ("special_dungeon.json", "SpecialRoomPowerText", "recognition.param.roi"): ((430, 0, 290, 1300), DEBT_OVER),
    # ---- 框出界：y/h 按「整屏」写（y+h 到 2430），或 x+w 到 750 ----
    ("abyss.json", "AbyssSoloChallenge", "action.param.custom_action_param.roi"): ((150, 980, 600, 1180), DEBT_OUT),
    ("abyss.json", "AbyssHubEnter", "action.param.custom_action_param.roi"): ((0, 600, 720, 1050), DEBT_OUT),
    ("phantom.json", "PhantomSoloChallenge", "action.param.custom_action_param.roi"): ((150, 980, 600, 1180), DEBT_OUT),
    ("phantom.json", "PhantomHubEnter", "action.param.custom_action_param.roi"): ((0, 600, 720, 1050), DEBT_OUT),
    ("side_story.json", "SideNavStoryTab", "recognition.param.roi"): ((430, 790, 320, 160), DEBT_OUT),
    ("team.json", "TeamEntry", "action.param.custom_action_param.roi"): ((0, 1180, 720, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongSettleDisband", "action.param.custom_action_param.roi"): ((0, 1150, 720, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongSettleReturnRoom", "action.param.custom_action_param.roi"): ((0, 1150, 720, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongContinueText", "recognition.param.roi"): ((0, 1150, 720, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongSettleContinue", "action.param.custom_action_param.roi"): ((0, 1150, 720, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongCoopChallenge", "action.param.custom_action_param.roi"): ((150, 820, 600, 980), DEBT_OUT),
    ("wuchong.json", "WuchongChallengeText", "recognition.param.roi"): ((150, 980, 600, 1180), DEBT_OUT),
    ("wuchong.json", "WuchongStaleTeam", "action.param.custom_action_param.roi"): ((0, 1180, 160, 1280), DEBT_OUT),
    ("wuchong.json", "WuchongTeamChallenge", "action.param.custom_action_param.roi"): ((150, 980, 600, 1180), DEBT_OUT),
    ("wuchong.json", "WuchongRoomLeave", "action.param.custom_action_param.roi"): ((0, 1180, 160, 1280), DEBT_OUT),
}

#: `scene/*.py` 里的四整数字面量：[x, y, w, h] 或 (x, y, w, h) / (x1, y1, x2, y2)。
_LITERAL4 = (
    re.compile(r"\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\]"),
    re.compile(r"\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)"),
)


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _base_bounds() -> tuple[int, int]:
    """基准空间尺寸 —— 从真源 `scene/pixels.py` 取，别在这里抄一份 720/1280。"""
    _paths()
    from scene import pixels  # noqa: PLC0415

    return pixels.BASE_W, pixels.BASE_H


# ---------------------------------------------------------------------------
# P1：pipeline 坐标必须落在 720x1280
# ---------------------------------------------------------------------------
def _is_number_list(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) > 0
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    )


def _walk(node, path: list, out: list) -> None:
    """收集节点下所有坐标字面量：``out`` 追加 ``(节点内字段路径, 字段名, 值)``。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in COORD_KEYS and _is_number_list(value):
                out.append((".".join([*path, key]), key, tuple(value)))
            _walk(value, [*path, key], out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            # 带上标号（`all_of.0.roi`）：同一个 And 下多个子识别各有 roi 时不至于撞键。
            _walk(item, [*path, str(index)], out)


def _violation(key: str, values: tuple) -> tuple[str, str] | None:
    """返回 ``(违规说明, 欠账分类)``；合法坐标返回 ``None``。"""
    width, height = _base_bounds()
    nums = [float(v) for v in values]
    if key == "target":
        if len(nums) != 2:
            return (f"target 应是 [x, y] 两点，实际 {len(nums)} 个值 {list(values)}", DEBT_OVER)
        x, y = nums
        if x < 0 or y < 0:
            return (f"负坐标 (x={x:g}, y={y:g})", DEBT_OVER)
        if x > width or y > height:
            return (f"点越界：x={x:g} y={y:g}（720 空间上限 {width}x{height}）", DEBT_OVER)
        return None
    # roi / box
    if len(nums) != 4:
        return (f"{key} 应是 [x, y, w, h] 四元组，实际 {len(nums)} 个值 {list(values)}", DEBT_OVER)
    x, y, w, h = nums
    if min(nums) < 0:
        return (f"含负值 {list(values)}（偏移请用 target_offset）", DEBT_OVER)
    over = []
    if x > width:
        over.append(f"x={x:g}>{width}")
    if w > width:
        over.append(f"w={w:g}>{width}")
    if y > height:
        over.append(f"y={y:g}>{height}")
    if h > height:
        over.append(f"h={h:g}>{height}")
    if over:
        return (f"值本身越轴：{', '.join(over)}", DEBT_OVER)
    if x + w > width:
        return (f"整框出界：x+w={x + w:g} > {width}", DEBT_OUT)
    if y + h > height:
        return (f"整框出界：y+h={y + h:g} > {height}", DEBT_OUT)
    return None


def _pipeline_failures(pipeline_dir=None, ledger=None) -> list:
    """P1 判定：返回违规列表（空 = 绿）。

    ``pipeline_dir`` / ``ledger`` 是为了破坏实验能在临时副本上跑（默认扫真仓库）。
    """
    _paths()
    import jsonc  # noqa: PLC0415

    directory = Path(pipeline_dir) if pipeline_dir is not None else PIPELINE_DIR
    book = KNOWN_BASE_OVERFLOW if ledger is None else ledger

    violations: dict[tuple[str, str, str], tuple[tuple, str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            data = jsonc.load(handle) or {}
        for node_name, node in data.items():
            if not isinstance(node, dict):
                continue
            literals: list = []
            _walk(node, [], literals)
            for rel, key, values in literals:
                got = _violation(key, values)
                if got is not None:
                    violations[(path.name, node_name, rel)] = (values, got[1], got[0])

    msgs: list[str] = []
    for ident, (values, cls, detail) in violations.items():
        if ident in book:
            continue
        fname, node_name, rel = ident
        msgs.append(
            f"{fname}::{node_name}.{rel} = {list(values)} 越出 720 空间：{detail}"
            "（原图像素请先 scene/pixels.box_to_base() / ÷1.5；既存欠账才允许登记进"
            " hooks_99.KNOWN_BASE_OVERFLOW，新写的一律要改）"
        )
    for ident, (registered, cls) in book.items():
        fname, node_name, rel = ident
        if ident not in violations:
            msgs.append(
                f"账本陈旧：{fname}::{node_name}.{rel} 已不再越界（或节点/字段没了）——"
                "请从 hooks_99.KNOWN_BASE_OVERFLOW 删掉这一条（欠账只减不增）"
            )
            continue
        values = violations[ident][0]
        if tuple(registered) != tuple(values):
            msgs.append(
                f"账本与现状不符：{fname}::{node_name}.{rel} 登记 {list(registered)}，"
                f"实际 {list(values)} —— 要么改回去，要么把这一条从 KNOWN_BASE_OVERFLOW 删掉"
            )
    return msgs


def probe_coord_pipeline_base_space() -> bool:
    return _pipeline_failures() == []


# ---------------------------------------------------------------------------
# P2：scene 字面量不是原图像素
# ---------------------------------------------------------------------------
def _scene_failures(scene_dir=None) -> list:
    """P2 判定：返回违规列表（空 = 绿）。"""
    directory = Path(scene_dir) if scene_dir is not None else SCENE_DIR
    width, height = _base_bounds()
    limits = (width, height, width, height)  # [x, y, w, h] 与 (x1, y1, x2, y2) 同组上限
    msgs: list[str] = []
    for path in sorted(directory.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in _LITERAL4:
            for match in pattern.finditer(text):
                values = [int(g) for g in match.groups()]
                over = [
                    f"第{i + 1}个值 {v} > {limits[i]}"
                    for i, v in enumerate(values)
                    if v > limits[i]
                ]
                if not over:
                    continue
                line_no = text.count("\n", 0, match.start()) + 1
                msgs.append(
                    f"{path.name}:{line_no} 的四整数字面量 {match.group(0)} 看着是原图像素："
                    f"{'；'.join(over)}（720 空间上限 {width}x{height}）——"
                    "原图 box 先 scene/pixels.box_to_base() / ÷1.5"
                )
    return msgs


def probe_coord_scene_literals() -> bool:
    return _scene_failures() == []


HOOKS = [
    (
        "coord-pipeline-base-space",
        "#99",
        "pipeline 坐标必须落在 720x1280：所有 roi/box 是 [x,y,w,h]、target 是 [x,y]，"
        "越界报「文件+节点+字段+数值」；既存 19 处越界登记在 hooks_99.KNOWN_BASE_OVERFLOW（只减不增）",
        probe_coord_pipeline_base_space,
    ),
    (
        "coord-scene-literals-base-space",
        "#99",
        "scene/*.py 的四整数字面量不许是原图像素：任一槽位超过自己的轴（x/w 720、y/h 1280）就红；"
        "负数不判（偏移量合法）。1080P 帧 ↔ 720 识别空间的换算真源是 scene/pixels.py（÷1.5）",
        probe_coord_scene_literals,
    ),
]


# ---------------------------------------------------------------------------
def prove_red() -> bool:
    _paths()
    print("hooks_99 prove-red：逐一破坏实现，要求守卫各自变红")
    p1 = _pipeline_failures()
    p2 = _scene_failures()
    green = not p1 and not p2
    print(
        f"  [{'PASS' if green else 'FAIL'}] 真实数据：P1 / P2 全绿"
        f"（P1 欠账 {len(KNOWN_BASE_OVERFLOW)} 条已登记："
        f"{sum(1 for _v, c in KNOWN_BASE_OVERFLOW.values() if c == DEBT_OVER)} 值越轴 + "
        f"{sum(1 for _v, c in KNOWN_BASE_OVERFLOW.values() if c == DEBT_OUT)} 框出界）"
    )
    if not green:
        for msg in (p1 + p2)[:8]:
            print(f"      - {msg}")
        if len(p1) + len(p2) > 8:
            print(f"      - …还有 {len(p1) + len(p2) - 8} 条")
        return False

    for cls, text in DEBT_CLASS_TEXT.items():
        count = sum(1 for _v, c in KNOWN_BASE_OVERFLOW.values() if c == cls)
        if count:
            print(f"      · 欠账 {count} 条 / {cls}：{text}")

    checks: list[bool] = []
    tmp = Path(tempfile.mkdtemp(prefix="wf_hook99_"))
    try:
        pipeline_copy = tmp / "pipeline"
        scene_copy = tmp / "scene"
        shutil.copytree(PIPELINE_DIR, pipeline_copy)
        shutil.copytree(SCENE_DIR, scene_copy)

        # ① 往 pipeline 副本里塞一个 1080 原图 roi（就是 hooks_86 那批 box 的形状）
        planted = pipeline_copy / "zz_prove_red.json"
        planted.write_text(
            json.dumps(
                {
                    "ProveRedNativeRoi": {
                        "recognition": {
                            "type": "OCR",
                            "param": {"expected": ["今天剩余次数"], "roi": [381, 1383, 319, 42]},
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        msgs = _pipeline_failures(pipeline_dir=pipeline_copy)
        red = any("ProveRedNativeRoi" in m and "1383" in m for m in msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 塞一个 1080 原图 roi [381,1383,319,42] -> "
              f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

        # ② 同一个文件里再把「1080 原图点击点」当 720 用（y=1383 > 1280）
        planted.write_text(
            json.dumps(
                {
                    "ProveRedNativeTarget": {
                        "action": {"type": "Click", "param": {"target": [572, 1383]}}
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        msgs = _pipeline_failures(pipeline_dir=pipeline_copy)
        red = any("ProveRedNativeTarget" in m and "1383" in m for m in msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 塞一个 1080 原图点击点 [572,1383] -> "
              f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

        # ③ 越界 roi 但**没登记**也要红（证明账本不是通行证，只认登记过的那几条）
        planted.write_text(
            json.dumps(
                {
                    "ProveRedOffByOne": {
                        "recognition": {"type": "OCR", "param": {"roi": [0, 1200, 720, 100]}}
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        msgs = _pipeline_failures(pipeline_dir=pipeline_copy)
        red = any("ProveRedOffByOne" in m and "y+h" in m for m in msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 塞一个「只越界 20px」的未登记 roi -> "
              f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

        # ④ 账本陈旧：登记一个已经不越界的条目 -> 红（逼着删账，ratchet 只减不增）
        stale = dict(KNOWN_BASE_OVERFLOW)
        stale[("wuchong.json", "WuchongRoomWait", "recognition.param.roi")] = ((0, 0, 10, 10), DEBT_OUT)
        msgs = _pipeline_failures(ledger=stale)
        red = any("账本陈旧" in m and "WuchongRoomWait" in m for m in msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 账本里塞一条不越界的登记 -> "
              f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

        # ⑤ 账本与现状不符：登记值被改过（有人动了数据却没对账）-> 红
        drifted = dict(KNOWN_BASE_OVERFLOW)
        ident = ("wuchong.json", "WuchongSettleContinue", "action.param.custom_action_param.roi")
        drifted[ident] = ((0, 1150, 720, 1281), DEBT_OUT)
        msgs = _pipeline_failures(ledger=drifted)
        red = any("账本与现状不符" in m and "WuchongSettleContinue" in m for m in msgs)
        print(f"  [{'PASS' if red else 'FAIL'}] 把账本登记的数值改一位 -> "
              f"{'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
        checks.append(red)

        # ⑥ 往 scene 副本里塞原图像素字面量 -> P2 红
        (scene_copy / "zz_prove_red.py").write_text(
            "# prove-red 临时文件\nNATIVE_BOX = [300, 1470, 900, 330]\nNATIVE_TUPLE = (203, 1288, 90, 40)\n",
            encoding="utf-8",
        )
        msgs = _scene_failures(scene_dir=scene_copy)
        red = (
            any("zz_prove_red.py:2" in m and "1470" in m for m in msgs)
            and any("zz_prove_red.py:3" in m and "1288" in m for m in msgs)
        )
        print(f"  [{'PASS' if red else 'FAIL'}] 往 scene 副本塞 [300,1470,900,330] + (203,1288,90,40) -> "
              f"{'红' if red else '仍绿'}")
        for msg in msgs[:2]:
            print(f"      - {msg}")
        checks.append(red)

        # ⑦ 反向证明不误报：负偏移量与合法 720 框不该被 P2 抓（否则守卫会被噪音淹没）
        clean_scene = tmp / "scene_clean"
        shutil.copytree(SCENE_DIR, clean_scene)
        (clean_scene / "zz_prove_green.py").write_text(
            "# 合法的写法：负偏移量（偏移可以为负）+ 720 空间内的框\n"
            "OFFSET = (-15, 41, 17, 70)\n"
            "BASE_BOX = [0, 1180, 720, 100]\n"
            "NATIVE_DIVIDED = [254.0, 614.667, 212.667, 28.0]\n",
            encoding="utf-8",
        )
        msgs = _scene_failures(scene_dir=clean_scene)
        keep_green = not any("zz_prove_green.py" in m for m in msgs)
        print(f"  [{'PASS' if keep_green else 'FAIL'}] 负偏移量与合法 720 框不被误报 -> "
              f"{'仍绿' if keep_green else '误红'}")
        checks.append(keep_green)
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
