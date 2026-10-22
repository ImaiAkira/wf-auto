# -*- coding: utf-8 -*-
"""#58：列表导航的滚动 / 滑动手势必须【区域内竖直下滑】——
绝不横向（``dx != 0``）、绝不触到底部导航 / 左下「返回」ROI、绝不在列表体外起落。

运维口径（verbatim）
--------------------
「在导航寻找时……**只需要往下拉**就好了，因为他这个是**卡片式**的，**每行一个**，
**在区域内从上往下划**就能找到对应的 item，**不要从左往右**，也**不要点到最下面的 UI**。」

seam：``assets/resource/pipeline/*.json`` 里**全部** ``action.type == "Swipe"`` 的节点
（``PushStageAllDone`` / ``FarmEventScrollDown`` / ``FarmEventScrollUp`` / ``FarmScroll`` /
``FarmScrollUp`` / ``WuchongSwipe`` / ``WuchongScrollList`` / ``SpecialScrollList``）
+ ``agent/*.py`` 里程序化注入的 Swipe param（AST 扫描，非手列）
+ ``common.json``（底导 / 返回 ROI 的来源节点）。

几何（720 空间，与 ``agent/side_impl.ROW_BODY_TOP/BOTTOM`` 同源）
---------------------------------------------------------------
* **列表体** = ``y ∈ [440, 1180]``：上沿是固定条（活动栏 y≈302、页签行 y≈388~421）之下，
  下沿是底部导航带上沿；卡片式列表一行一张，屏内 4~5 行。
* **底部导航 / 左下返回带** = ``y ≥ 1180``（``common.json::PubReturnHomeText`` ROI
  ``[0,1180,720,100]`` / ``PubReturnHomeBackTab`` ROI ``[0,1180,110,100]``）。**列表体止于 1180**。
* **受控行程** = ``[200, 600]px``：太短不翻行、太长成「甩动」会跳过 / 甩到别的页。

守卫（一个断言覆盖全部 Swipe 节点，prove-red 也在本文件里）
---------------------------------------------------------
``scroll-rule-all-gestures-vertical`` —— 读产品里所有 Swipe 节点，对每个断言：

  0. **形态（★#58 补强，本次真正堵住的漏口★）**：``begin`` / ``end`` 必须是**两元素定点**
     ``[x, y]``，**绝不许四元素** ``[x, y, w, h]``。MAA 的四元素是【区域】——在矩形内
     随机取一点（越靠中心概率越高），且 ``w/h=0`` 时区域**延伸到屏幕边缘**
     （``[0,0,0,0]`` = 全屏）。所以旧写法 ``[360, 1040, 0, 0]`` 其实是
     ``[360,720]×[1040,1280]`` 的**随机斜向拖拽**（``dx≠0``）。**#58 原守卫只看
     前两分量（``begin[0]==end[0]``）→ 四元素陷阱整个穿过**，这就是运维看到的
     「斜向拉动 + 左右拉去找」的真身。真机日志实证：``SpecialScrollList`` 的
     ``begin.x ∈ [362,710]``、``end.x ∈ [360,714]``（同一次运行的 ``PubSwipe`` 两元素
     定点则严格 ``dx==0``）。
  1. **轴竖直**：``begin.x == end.x``（``dx == 0``）；
  2. 起、终点 ``x ∈ [0, 720]``；
  3. 起、终点都在**列表体** ``[0, 440, 720, band-440]`` 内；
  4. 起、终点都**不低于**底导带上沿（``y < 1180``）且**不落在**任何从产品枚举的底导 /
     返回 ROI 内（绝不点到最下面的 UI）；
  5. 行程 ``|begin.y - end.y| ∈ [200, 600]``。

并**扫描 agent 侧**（``agent/*.py`` 的 AST，不是手列节点名）：任何程序化注入的
``{"type": "Swipe", "param": ...}`` 的 ``begin`` / ``end`` 若是长度≠2 的列表字面量
（四元素区域陷阱）→ 报红。agent 侧唯一的一处程序化 Swipe 是 wuchong 手操战斗的
**技能手势**（left/up/right，横向是刻意的战斗手感，#58 明确保留），故 agent 扫描只拦
「区域陷阱」，不拦其横向——list 导航的竖直由上方 pipeline 全枚举保证。

并断言**必需节点都在枚举里**（``PushStageAllDone`` / ``FarmEventScrollDown`` /
``FarmEventScrollUp`` / ``FarmScroll`` / ``FarmScrollUp`` / ``WuchongSwipe`` /
``WuchongScrollList`` / ``SpecialScrollList`` —— ★#58 补强★：原集合漏了
``FarmEventScrollDown`` / ``FarmEventScrollUp`` / ``WuchongSwipe`` 三个 Swipe 节点）
—— 防止节点被改名 / 删除后守卫「静默豁免」。

★#36 意图保留★：``hooks_36.py`` 原样不动（``SpecialScrollList`` 起终点仍在列表体、
不压底导 / 返回 ROI）。本票是覆盖**全部** Swipe 节点的**更广**守卫，不取代 #36；
底导 ROI 枚举与列表体边界直接复用 ``hooks_36`` 的单一来源。

★prove-red★（``python tools\\contract_hooks\\hooks_58.py``）：
  ① 把 ``WuchongScrollList`` 改成**横向**（``begin`` x 360→200）→ 守卫变红（轴）；
  ② 把 ``SpecialScrollList`` 起点退回 ``y=1200``（压底导）→ 守卫变红（触到底部 UI）；
  ③ 把 ``SpecialScrollList`` 起点写成**非零 w/h 区域** ``[360,1040,120,40]`` → 红（形态）；
  ④ 把 ``FarmScroll`` 起点写回**真缺陷原形** ``[360,900,0,0]`` → 红（形态：w/h=0 区域）；
  ⑤ 把 ``PushStageAllDone`` 改成**斜向**（``begin`` ``[320,900]``、``end`` ``[360,620]``）
     → 红（轴）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = HOOKS_DIR.parent
REPO_ROOT = TOOLS_DIR.parent

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import hooks_36 as h36  # noqa: E402  —— 复用底导 ROI 枚举 / 列表体边界（单一来源）

_PIPELINE_REL = "assets/resource/pipeline"
_WUCHONG = "wuchong.json"
_SD = "special_dungeon.json"

# 受控行程区间（px）—— 与 hooks_36 同值（太短不翻行 / 太长成甩动会跳过目标）。
_SWIPE_MIN_TRAVEL = 200
_SWIPE_MAX_TRAVEL = 600

#: 必须被枚举到的滚动 / 滑动节点（防「改名 / 删除 → 守卫静默豁免」）。
#  ★#58 补强★：原集合漏了 ``FarmEventScrollDown`` / ``FarmEventScrollUp`` / ``WuchongSwipe``
#  （它们同样是 Swipe 节点）→ 一并纳入，改名 / 删除即报红。
REQUIRED_SCROLL_NODES = frozenset(
    {
        "PushStageAllDone",
        "FarmEventScrollDown",
        "FarmEventScrollUp",
        "FarmScroll",
        "FarmScrollUp",
        "WuchongSwipe",
        "WuchongScrollList",
        "SpecialScrollList",
    }
)

#: 屏幕宽度（720 空间）。
_SCREEN_W = 720


# ---------------------------------------------------------------------------
# 枚举产品里全部 Swipe 节点
# ---------------------------------------------------------------------------
def _swipe_nodes(files: dict) -> list[tuple[str, str, dict]]:
    """返回 ``[(文件名, 节点名, action.param), ...]``：产品里所有 ``type == "Swipe"`` 的节点。"""
    out: list[tuple[str, str, dict]] = []
    for fname, data in files.items():
        if not isinstance(data, dict):
            continue
        for name, spec in data.items():
            if not isinstance(spec, dict):
                continue
            action = spec.get("action") or {}
            if action.get("type") != "Swipe":
                continue
            param = action.get("param") or {}
            out.append((fname, name, param if isinstance(param, dict) else {}))
    return out


def swipe_inventory(root: Path | None = None) -> list[tuple[str, str, list[int], list[int]]]:
    """审计用：``[(文件, 节点, begin, end), ...]``（begin/end 取前两分量）。"""
    files = h36._files(root)
    rows: list[tuple[str, str, list[int], list[int]]] = []
    for fname, name, param in _swipe_nodes(files):
        b = h36._pt(param.get("begin"))
        e = h36._pt(param.get("end"))
        rows.append((fname, name, list(b) if b else [], list(e) if e else []))
    return rows


# ---------------------------------------------------------------------------
# agent 侧扫描：程序化注入的 Swipe param 也不许出现四元素「区域」形态
#
# list 导航的滚动全权委托给 pipeline 节点（上方 _swipe_nodes 已全枚举），agent 侧
# 唯一的一处程序化 Swipe 是 wuchong 手操战斗的【技能手势】（left/up/right，横向是
# 刻意的战斗手感，#58 明确保留）。所以此扫描【只】拦「四元素=区域」这个静默陷阱：
# 区域会在矩形内随机取点 → 随机斜向，无论节点本意如何。两元素定点则永远 dx≡0。
# 用 AST 遍历（不是手列节点名）：任何 agent 文件里 ``{"type": "Swipe", "param": ...}``
# 的 begin/end 若是长度≠2 的列表字面量 → 报红。
# ---------------------------------------------------------------------------
def _agent_swipe_failures() -> list[str]:
    import ast  # noqa: PLC0415

    def _get(dnode, key: str):
        for k, v in zip(dnode.keys, dnode.values):
            if isinstance(k, ast.Constant) and k.value == key:
                return v
        return None

    msgs: list[str] = []
    agent_dir = REPO_ROOT / "agent"
    if not agent_dir.is_dir():
        return msgs
    for py in sorted(agent_dir.glob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"agent 扫描：{py.name} 无法解析（{exc!r}）—— 守卫不愿静默跳过")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            typ = _get(node, "type")
            if not (isinstance(typ, ast.Constant) and typ.value == "Swipe"):
                continue
            param = _get(node, "param")
            if not isinstance(param, ast.Dict):
                continue
            for key in ("begin", "end"):
                val = _get(param, key)
                line = getattr(val, "lineno", node.lineno)
                if isinstance(val, ast.List) and len(val.elts) != 2:
                    msgs.append(
                        f"agent 扫描：{py.name}:{line} 注入的 Swipe.{key} 是 "
                        f"{len(val.elts)} 元素列表（四元素=区域→随机斜向；只许两元素定点）"
                    )
    return msgs


# ---------------------------------------------------------------------------
# 断言：全部 Swipe 节点都是「区域内竖直下滑」
# ---------------------------------------------------------------------------
def _failures(root: Path | None = None) -> list[str]:
    files = h36._files(root)
    msgs: list[str] = list(h36._binding_failures(files))

    nav = h36._nav_rois(files)
    if not nav:
        msgs.append("几何：产品里找不到任何「底部导航 / 返回」ROI（枚举规则失效了？）")
    band = h36._band_top(nav)
    body = h36._list_body(band)

    swipes = _swipe_nodes(files)
    names = {name for _f, name, _p in swipes}
    missing = sorted(REQUIRED_SCROLL_NODES - names)
    if missing:
        msgs.append(
            f"枚举：产品里找不到滚动节点 {missing}（被改名 / 删除？守卫不许静默豁免）"
        )

    for fname, name, param in swipes:
        # 0) 形态：begin / end 必须是【两元素定点】[x, y]。MAA 的四元素 [x, y, w, h]
        #    是【区域】——会在矩形内随机取一点（越靠中心概率越高）；w/h 为 0 时该区域
        #    【延伸到屏幕边缘】（[0, 0, 0, 0] 即全屏，见 pipeline.schema.json 的 Swipe.begin）。
        #    因此旧写法 [360, 1040, 0, 0] 其实是 [360,720]×[1040,1280] 的【随机斜向拖拽】：
        #    begin.x / end.x 各自乱跳 → dx≠0。这正是一次「#58 漏掉的真正缺陷」——
        #    #58 只看前两分量（begin[0]==end[0]），四元素陷阱整个穿过守卫。
        #    真机日志实证：SpecialScrollList 的 begin x∈[362,710]、end x∈[360,714]。
        for key in ("begin", "end"):
            val = param.get(key)
            if isinstance(val, (list, tuple)) and len(val) != 2:
                msgs.append(
                    f"形态：{name}（{fname}）的 Swipe.{key}={list(val)} 是 {len(val)} 元素"
                    f"—— 四元素=区域→随机斜向拖拽（dx≠0）；list 导航只许两元素定点 [x,y]"
                )

        begin = h36._pt(param.get("begin"))
        end = h36._pt(param.get("end"))
        if begin is None or end is None:
            msgs.append(f"几何：{name}（{fname}）的 Swipe 缺 begin / end，无法判几何")
            continue

        # 1) 轴必须竖直：dx == 0（绝不从左往右 / 从右往左）。
        if begin[0] != end[0]:
            msgs.append(
                f"轴：{name}（{fname}）是**横向**手势 dx={end[0] - begin[0]}"
                f"（begin={list(begin)} end={list(end)}）—— 列表导航只许竖直下滑"
            )

        # 2) x 在屏内。
        for label, pt in (("起点", begin), ("终点", end)):
            if not (0 <= pt[0] <= _SCREEN_W):
                msgs.append(f"几何：{name}（{fname}）手势{label} x={pt[0]} 不在 [0,{_SCREEN_W}]")

        # 3~4) 两端点在列表体内、且不在底导 / 返回 ROI（绝不点到最下面的 UI）。
        for label, pt in (("起点", begin), ("终点", end)):
            for src, roi in nav:
                if h36._inside(pt, roi):
                    msgs.append(
                        f"几何：{name}（{fname}）手势{label} {list(pt)} 落在底部导航 / 返回"
                        f" ROI {roi}（{src}）内 —— 会点到最下面的 UI（#18/#29/#36 同族病）"
                    )
            if pt[1] >= band:
                msgs.append(
                    f"几何：{name}（{fname}）手势{label} y={pt[1]} 不低于底导带上沿 y={band}"
                    f"（列表体止于 {band}，{label} 已触到底部 UI）"
                )
            if not h36._inside(pt, body):
                msgs.append(
                    f"几何：{name}（{fname}）手势{label} {list(pt)} 不在列表体 {body} 内"
                    f"（上沿是固定条，下沿是底导带）"
                )

        # 5) 行程受控（几行，不甩动）。
        travel = abs(begin[1] - end[1])
        if not (_SWIPE_MIN_TRAVEL <= travel <= _SWIPE_MAX_TRAVEL):
            msgs.append(
                f"行程：{name}（{fname}）{travel}px 不在 [{_SWIPE_MIN_TRAVEL}, {_SWIPE_MAX_TRAVEL}]"
                f"（太短不翻行 / 太长成甩动会跳过目标）"
            )

    # agent 侧：程序化注入的 Swipe param 同样不许四元素「区域」形态。
    msgs.extend(_agent_swipe_failures())
    return msgs


def probe_all_scroll_gestures_vertical() -> bool:
    """#58 守卫：产品里**全部** Swipe 节点都是区域内竖直下滑，且必备节点都枚举到。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_58.py`）
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook58_assets_"))
    (root / "assets" / "resource").mkdir(parents=True)
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


def _break_horizontal(root: Path) -> None:
    """产物级：把 WuchongScrollList 改成横向（begin x 360→200）。"""
    _sub(
        root / _PIPELINE_REL / _WUCHONG,
        '"begin": [360, 900], "end": [360, 520]',
        '"begin": [200, 900], "end": [360, 520]',
    )


def _break_into_nav_band(root: Path) -> None:
    """产物级：把 SpecialScrollList 起点退回 y=1200（又压在底部导航带上）。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '"begin": [360, 1040],',
        '"begin": [360, 1200],',
    )


def _break_region_box(root: Path) -> None:
    """产物级：把 SpecialScrollList 起点写成四元素【区域】（非零 w/h）→ 随机斜向。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '"begin": [360, 1040],',
        '"begin": [360, 1040, 120, 40],',
    )


def _break_region_zero(root: Path) -> None:
    """产物级：把 FarmScroll 起点写回**真缺陷原形** [x, y, 0, 0]（w/h=0 区域→延伸到屏边）。"""
    _sub(
        root / _PIPELINE_REL / "farm.json",
        '"param": { "begin": [360, 900], "end": [360, 700], "duration": 450 }',
        '"param": { "begin": [360, 900, 0, 0], "end": [360, 700], "duration": 450 }',
    )


def _break_diagonal(root: Path) -> None:
    """产物级：把 PushStageAllDone 改成【斜向】（dx≠0 且 dy≠0）。"""
    _sub(
        root / _PIPELINE_REL / "auto_push.json",
        '"param": { "begin": [360, 900], "end": [360, 620], "duration": 450 }',
        '"param": { "begin": [320, 900], "end": [360, 620], "duration": 450 }',
    )


def _red_case(label: str, breaker) -> bool:
    root = _temp_pipeline()
    try:
        breaker(root)
        msgs = _failures(root)
        red = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}{tail}")
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


def prove_red() -> bool:
    """真实绿；横向 / 压底导 / 非零 w,h 区域 / [x,y,0,0] 区域 / 斜向 → 各自变红。"""
    h36.scene_on_path()
    print(
        "hooks_58 prove-red：① WuchongScrollList 改横向 ② SpecialScrollList 起点退回 y=1200 "
        "③ SpecialScrollList 起点写成非零 w/h 区域 ④ FarmScroll 起点写回 [x,y,0,0] ⑤ PushStageAllDone 改斜向"
    )
    green = probe_all_scroll_gestures_vertical() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：全部 Swipe 竖直且不触底导（绿）")
    if not green:
        return False

    red_a = _red_case("① WuchongScrollList 改横向（dx≠0）", _break_horizontal)
    red_b = _red_case("② SpecialScrollList 起点退回 y=1200（压底导）", _break_into_nav_band)
    red_c = _red_case("③ SpecialScrollList 起点写成非零 w/h 区域（四元素）", _break_region_box)
    red_d = _red_case("④ FarmScroll 起点写回 [x,y,0,0]（w/h=0 区域→延伸到屏边）", _break_region_zero)
    red_e = _red_case("⑤ PushStageAllDone 改斜向（dx≠0 且 dy≠0）", _break_diagonal)

    ok = green and red_a and red_b and red_c and red_d and red_e
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "scroll-rule-all-gestures-vertical",
        "#58",
        "列表导航的全部 Swipe 手势：轴竖直（dx==0）、起终点在列表体 [440,1180] 内、"
        "不落在底导 / 返回 ROI、行程受控 [200,600]（含必备节点枚举防静默豁免）",
        probe_all_scroll_gestures_vertical,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
