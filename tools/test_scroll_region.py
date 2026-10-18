# -*- coding: utf-8 -*-
"""离线单测：#58 补强 —— 四元素「区域」Swipe 陷阱 + agent 侧扫描（本次真正堵住的漏口）。

不需要游戏 / 设备（判据全在**产品 pipeline JSON** + **agent 源码 AST** 上）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scroll_region.py
    .venv\\Scripts\\python.exe tools\\test_scroll_region.py --prove-red

缺陷（运维直证 + 真机日志）
---------------------------
运维原话：「在导航到某一个讨伐作战的时候……是一个**斜向的拉动**，并且会**左右拉去找**」。
MAA 的 Swipe ``begin``/``end`` 四元素 ``[x, y, w, h]`` 是**【区域】**——会在矩形内随机取
一点（越靠中心概率越高）；``w/h=0`` 时区域**延伸到屏幕边缘**（``[0,0,0,0]`` = 全屏，见
``deps/tools/pipeline.schema.json`` 的 ``Swipe.begin`` 说明）。故旧写法
``[360, 1040, 0, 0] → [360, 640, 0, 0]`` 实为 ``[360,720]×[1040,1280] → [360,720]×[640,1280]``
的**随机斜向拖拽**：``begin.x`` / ``end.x`` 各自乱跳 → ``dx≠0``。

真机日志实证（``debug`` 下 maafw 日志，按节点聚合）：``SpecialScrollList`` 的
``begin.x ∈ [362,710]``、``begin.y ∈ [1201,1279]``、``end.x ∈ [360,714]``、``end.y ∈ [802,1270]``；
而同一次运行的 ``PubSwipe``（两元素定点）严格 ``dx==0`` 竖直、``WuchongSwipe``（两元素）亦然。
→ 四元素 = 随机斜向，两元素 = 定点。**#58 原守卫只看前两分量**，四元素陷阱整个穿过。

本测试断言：
  1. **pipeline**：全部 ``Swipe`` 节点的 ``begin``/``end`` 都是**两元素定点** ``[x,y]``，
     且轴竖直 ``dx==0``（四元素区域 = 随机斜向，必须为红）；
  2. **agent**：程序化注入的 ``{"type":"Swipe","param":...}`` 同样无四元素区域（AST 扫描）；
  3. **prove-red**：区域（非零 w/h）/ 区域（``[x,y,0,0]``）/ 斜向 / 横向 / 压底导 五例各自变红；
  4. **无漂移 + #9 守卫仍绿 + 五条承重短语零丢失**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_58.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402

import hooks_36  # noqa: E402
import hooks_58  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []
SKIPS: list[str] = []

# #12 的承重注释硬规则（纯编辑，绝不丢这些短语）。
_BEARING_PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _files() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)


# ---------------------------------------------------------------------------
# 1. pipeline：全部 Swipe 都是两元素定点、轴竖直
# ---------------------------------------------------------------------------
def test_pipeline_two_element_vertical() -> None:
    print("\n== 1. pipeline：全部 Swipe 的 begin/end 都是两元素定点 + dx==0 ==")
    files = _files()
    nodes = hooks_58._swipe_nodes(files)
    print(f"     共 {len(nodes)} 个 Swipe 节点：{[n for _f, n, _p in nodes]}")
    check("枚举到全部 Swipe 节点", len(nodes) > 0)

    region_bad = []
    axis_bad = []
    for fname, name, param in nodes:
        for key in ("begin", "end"):
            val = param.get(key)
            if not (isinstance(val, (list, tuple)) and len(val) == 2):
                region_bad.append(f"{name}({fname}).{key}={val}")
        b = hooks_36._pt(param.get("begin"))
        e = hooks_36._pt(param.get("end"))
        if b and e and b[0] != e[0]:
            axis_bad.append(f"{name}({fname}) dx={e[0] - b[0]}")

    check("无四元素「区域」形态（否则随机斜向）", region_bad == [], f"{region_bad[:3]}")
    check("全部轴竖直 dx==0", axis_bad == [], f"{axis_bad[:3]}")

    # 真缺陷原形已从产品里消失（guard 与实现绑定的最小证据）。
    for fname, name, param in nodes:
        for key in ("begin", "end"):
            val = param.get(key)
            check(f"{name}.{key} 非旧四元素原形 {list(val) if isinstance(val, list) else val}",
                  not (isinstance(val, (list, tuple)) and len(val) == 4),
                  f"{name}({fname})")


# ---------------------------------------------------------------------------
# 2. agent 侧：程序化注入的 Swipe 无四元素区域
# ---------------------------------------------------------------------------
def test_agent_side_no_region() -> None:
    print("\n== 2. agent 侧：程序化注入的 Swipe param 无四元素区域（AST 扫描）==")
    msgs = hooks_58._agent_swipe_failures()
    check("agent 侧无四元素区域陷阱", msgs == [], f"{msgs[:2]}")

    # 反向证据：agent 里确实存在一处程序化 Swipe（wuchong 手操战斗技能手势），
    # 且它是两元素定点（横向是刻意的战斗手感，不在「list 导航」红线内）。
    import ast  # noqa: PLC0415

    found = 0
    for py in sorted((REPO_ROOT / "agent").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "type" and \
                            isinstance(v, ast.Constant) and v.value == "Swipe":
                        found += 1
    check("agent 侧确有程序化 Swipe（扫描不是空转）", found >= 1, f"找到 {found} 处")


# ---------------------------------------------------------------------------
# 3. prove-red（含区域 / 斜向 / 横向 / 压底导五例）
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 3. prove-red：区域 / 斜向 / 横向 / 压底导 五例各自变红 ==")
    check("hooks_58.prove_red() 成立", hooks_58.prove_red() is True)


# ---------------------------------------------------------------------------
# 4. 无漂移 + #9 守卫 + 承重短语
# ---------------------------------------------------------------------------
def test_drift_guards_phrases() -> None:
    print("\n== 4. 无漂移 + #9 守卫仍绿 + 五条承重短语零丢失 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")

    text = (PIPELINE_DIR / "special_dungeon.json").read_text(encoding="utf-8")
    for phrase in _BEARING_PHRASES:
        check(f"仍含承重短语「{phrase}」", phrase in text)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    if "--prove-red" in sys.argv[1:]:
        test_prove_red()
        print("\n" + "=" * 72)
        if FAILS:
            print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
            sys.exit(1)
        print("结果：prove-red 成立 ✅")
        return

    print("=" * 72)
    print("离线单测：#58 补强 —— 四元素「区域」Swipe 陷阱 + agent 侧扫描")
    print("=" * 72)
    test_pipeline_two_element_vertical()
    test_agent_side_no_region()
    test_prove_red()
    test_drift_guards_phrases()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
