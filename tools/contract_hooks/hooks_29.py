# -*- coding: utf-8 -*-
"""#29：归位不得在【链上步骤页面】上自匹配 —— 目标行在屏幕外时必须去滚动找行。

seam：``scene.events.RETURN_HOME_NODE_SPEC``（归位判据）+ ``scene.drift``（链后继 + 兜底范围）
+ ``assets/resource/pipeline/common.json``（``PubReturnHome`` / ``PubReturnHomeOtherSection``）
+ ``assets/resource/pipeline/special_dungeon.json``（``SpecialTabLord`` / ``SpecialTabJoss``
  的显式后继 + ``SpecialScrollList``）。

背景（#29 真机实证）
--------------------
``归位`` 的判据（#18）是 ``And(^主城$ 在底部导航, ^返回$ 在底部最左槽)``。但领主战
**列表页与详情页同样同时具备这两者** → 归位在这些**链上步骤页面**上**自匹配**。
它的注入位置是**兜底后缀**，紧跟 ``SpecialEnterBoss`` 之后。于是：

    目标行在屏幕外 → SpecialEnterBoss 不命中 → 兜底归位先触发 → 点主城 → 回主城
    → 枢纽 SpecialEntry 重进 → …循环 → 超时。

而**负责滚动找行的 ``SpecialScrollList`` 只挂在枢纽的候选表里**，且枢纽里它排在两个
页签节点**之后** → 页签每轮抢先命中 → **滚动这条路永远轮不到**。
真机：15 个领主战成员只有首屏 3 个能打到，其余 12 个循环到超时（降临讨伐同样）。

本票两个守卫（prove-red 也在本文件里）
--------------------------------------
1. ``return-home-scope-not-chain-page`` —— 兜底归位的判据**在链上步骤页面上不命中**、
   在**真正该回主城**的页面上命中。用**真机帧**做正反例：
   * 反例（必须不命中）：领主战**列表页**（``lord_page_tab_lord.png`` / ``_joss.png``，
     也有 ``sweep_entry`` 的列表屏）、**详情页**（``afterC.png``）、编队页（``lord_team_page.png``）；
   * 正例（必须命中）：漂到的**非主城分区**页（``scope_gacha.png``：扭蛋分区页，底导「扭蛋」
     页签橙色高亮、其余灰）。
   判据：底导「主城」入口还在 + 最左槽「返回」+ **另一个一级分区页签橙色高亮**
   （``PubReturnHomeOtherSection``，MAA 无 Not，故用正向 Or 表达「不在主城分区」）。
2. ``list-scroll-path-reachable`` —— **离线复现本次死循环**（目标行在屏幕外，确定性）：
   * 旧形态（归位仍是两叶 And = 与列表页自匹配，且页签节点后继里没有滚动）：
     首命中 = ``PubReturnHome``（抢跑），``SpecialScrollList`` **永不执行** → 死循环；
   * 新形态（真实产物）：必经 ``SpecialScrollList``（滚动找行），且不再命中 ``PubReturnHome``。

★prove-red★（``python tools\\contract_hooks\\hooks_29.py``）：
   * 把第三叶（页面范围判别叶）从归位判据里去掉 -> 守卫 1 变红（归位又在列表页命中）；
   * 把滚动后继从页签节点后继里去掉 -> 守卫 2 变红（滚动不可达，被兜底抢跑）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

_PIPELINE_REL = "assets/resource/pipeline"
_SD = "special_dungeon.json"
_COMMON = "common.json"

# 底部导航四个「一级分区」页签标签框（720 空间，取自真机帧 OCR）。
# 主城分区的任何页面这几个都是灰的（橙色像素 0）；选中态是橙色（实测 ≈880~918 px）。
TAB_ROIS = {
    "角色": [275, 1244, 46, 29],
    "商店": [397, 1246, 43, 26],
    "扭蛋": [516, 1246, 45, 26],
    "菜单": [636, 1248, 45, 25],
}
# 选中态橙色（与 common.json::PubReturnHomeOtherSection 的 ColorMatch 一致）。
ORANGE_LOWER = [190, 90, 0]
ORANGE_UPPER = [255, 205, 115]
ORANGE_COUNT = 50


def _roi_key(roi) -> str | None:
    for name, r in TAB_ROIS.items():
        if list(roi or []) == list(r):
            return name
    return None


# ---------------------------------------------------------------------------
# 真机帧夹具（720 空间 OCR + 四个分区页签的橙色像素计数，均为实测值）
#
# 每条 = (frame 名, 来源文件, 该帧底导 OCR 条目, {分区: 橙色像素数}, 期望归位命中?)
# 橙色计数由真机帧 resize 到 720x1280 后在 TAB_ROIS 上按 ORANGE_LOWER/UPPER 统计得到
# （见本文件 _measure_orange，best-effort；离线夹具用这里的实测常量）。
# ---------------------------------------------------------------------------
_NAV_ALL = [
    ("返回", [30, 1246, 46, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("菜单", [636, 1248, 45, 25]),
]
_ZERO_ORANGE = {"角色": 0, "商店": 0, "扭蛋": 0, "菜单": 0}

FRAMES = [
    {
        "name": "列表页·领主战页签",
        "source": "tools/frames/lord_page_tab_lord.png",
        "items": [*_NAV_ALL, ("更新列表", [615, 328, 82, 28]), ("领主战", [100, 401, 60, 28])],
        "orange": dict(_ZERO_ORANGE),
        "expect_home": False,
    },
    {
        "name": "列表页·降临讨伐页签",
        "source": "tools/frames/lord_page_tab_joss.png",
        "items": [*_NAV_ALL, ("更新列表", [615, 328, 82, 28]), ("降临讨伐", [452, 401, 90, 28])],
        "orange": dict(_ZERO_ORANGE),
        "expect_home": False,
    },
    {
        "name": "详情页",
        "source": r"<local>\AppData\Local\Temp\opencode\afterC.png",
        "items": [*_NAV_ALL, ("推荐编成", [56, 530, 96, 30]), ("猩红巨熊", [228, 194, 260, 70])],
        "orange": dict(_ZERO_ORANGE),
        "expect_home": False,
    },
    {
        "name": "编队页",
        "source": "tools/frames/lord_team_page.png",
        # 编队页没有底部导航整条 tab 栏，只有最左的「返回」→ 连「主城」入口都不在。
        "items": [("返回", [31, 1247, 45, 25]), ("挑战", [296, 1055, 82, 45])],
        "orange": dict(_ZERO_ORANGE),
        "expect_home": False,
    },
    {
        "name": "扭蛋分区页（真正该归位）",
        "source": r"<local>\AppData\Local\Temp\opencode\scope_gacha.png",
        "items": [*_NAV_ALL, ("1次抽取", [178, 1009, 133, 39]), ("10连抽取", [403, 1009, 159, 41])],
        "orange": {"角色": 0, "商店": 0, "扭蛋": 918, "菜单": 0},
        "expect_home": True,
    },
]


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（OCR / And / Or / DirectHit / ColorMatch；Custom 视为不命中）
# ---------------------------------------------------------------------------
def _ocr_hit(rec: dict, items) -> bool:
    param = rec.get("param") or {}
    pats = param.get("expected") or []
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return True
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        if roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3]:
            return True
    return False


def eval_recognition(rec, items, resolve=None, orange=None) -> bool:
    """在给定真机帧模型（OCR 条目 + 分区橙色像素计数）上求一条 recognition。"""
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        return _ocr_hit(rec, items)
    if kind == "ColorMatch":
        param = rec.get("param") or {}
        key = _roi_key(param.get("roi"))
        if key is None or orange is None:
            return False  # 非「分区页签」ROI 的 ColorMatch 不在本夹具模型内
        return int(orange.get(key, 0)) >= int(param.get("count", 1))
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = resolve(leaf) if (isinstance(leaf, str) and resolve is not None) else leaf
            hits.append(eval_recognition(leaf_rec, items, resolve, orange))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测，视为不命中


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _home_node(files: dict) -> dict | None:
    import scene.drift as drift  # noqa: PLC0415

    return drift._resolve_recognition("PubReturnHome", files)


# ---------------------------------------------------------------------------
# 守卫 1：兜底归位在链上步骤页面上不命中、在真正该归位的页面上命中（真机帧）
# ---------------------------------------------------------------------------
_TAB_NODES = {
    "角色": "PubReturnHomeTabChar",
    "商店": "PubReturnHomeTabShop",
    "扭蛋": "PubReturnHomeTabGacha",
    "菜单": "PubReturnHomeTabMenu",
}


def _binding_failures(files: dict) -> list[str]:
    """判据绑定：产品里的四条 ColorMatch 必须与 hooks_29 的常量逐字段一致。

    防止「产品改了 ROI / 颜色 / 阈值、夹具却没跟上」——那样守卫就成了自说自话。
    """
    msgs: list[str] = []
    other = _node("PubReturnHomeOtherSection", files) or {}
    rec = other.get("recognition") or {}
    if rec.get("type") != "Or":
        msgs.append("归位范围：PubReturnHomeOtherSection 不是 Or")
        return msgs
    names = list((rec.get("param") or {}).get("any_of") or [])
    want_names = list(_TAB_NODES.values())
    if names != want_names:
        msgs.append(f"归位范围：PubReturnHomeOtherSection.any_of 应为 {want_names}，实际 {names}")
    for tab, node_name in _TAB_NODES.items():
        node = _node(node_name, files) or {}
        nrec = node.get("recognition") or {}
        if nrec.get("type") != "ColorMatch":
            msgs.append(f"归位范围：{node_name} 不是 ColorMatch")
            continue
        param = nrec.get("param") or {}
        if list(param.get("roi") or []) != list(TAB_ROIS[tab]):
            msgs.append(f"归位范围：{node_name} 的 ROI {param.get('roi')} != {TAB_ROIS[tab]}")
        if list(param.get("lower") or []) != ORANGE_LOWER or list(param.get("upper") or []) != ORANGE_UPPER:
            msgs.append(f"归位范围：{node_name} 的 lower/upper 与 hooks_29 常量不一致")
        if int(param.get("count", -1)) != ORANGE_COUNT:
            msgs.append(f"归位范围：{node_name} 的 count {param.get('count')} != {ORANGE_COUNT}")
    return msgs


def _scope_failures(root: Path | None = None) -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    files = drift.load_pipelines(base / _PIPELINE_REL)
    resolve = _resolver(files)
    rec = _home_node(files)
    msgs: list[str] = _binding_failures(files)
    if not isinstance(rec, dict):
        return msgs + ["归位范围：pipeline 里找不到 PubReturnHome 的 recognition"]

    for frame in FRAMES:
        hit = eval_recognition(rec, frame["items"], resolve, frame["orange"])
        want = frame["expect_home"]
        if hit != want:
            msgs.append(
                f"归位范围：真机帧「{frame['name']}」({frame['source']}) 的归位命中 {hit}，"
                f"应为 {want}"
                + ("（链上步骤页面不得命中归位）" if not want else "（真正该归位的页面应命中）")
            )
    return msgs


def probe_return_home_scope_not_chain_page() -> bool:
    """#29 守卫 1：归位在列表 / 详情 / 编队页不命中，在非主城分区页命中。"""
    return _scope_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：离线复现「目标行在屏幕外」的循环 —— 旧形态死循环 / 新形态走到滚动
#
# 列表屏状态机：page ∈ {主城, 列表}；active_section = 当前一级分区（列表屏恒为主城分区）；
# 目标行是否在屏内。MAA ``next`` / ``max_hit`` 语义同 hooks_19。
# ---------------------------------------------------------------------------
_LIST_TAB_ITEMS = [
    ("领主战", [100, 401, 60, 28]),      # 中心 (130,415) ∈ SpecialTabLord ROI
    ("降临讨伐", [452, 401, 90, 28]),    # 中心 (497,415) ∈ SpecialTabJoss ROI
]
_MAIN_CITY_ENTRY = ("领主战", [569, 1121, 79, 29])  # 主城右下角入口（SpecialOpenLord ROI 内）


class _Screen:
    """列表屏（或主城屏）的可观测状态：底导 OCR + 分区橙色计数。"""

    def __init__(self, page: str, target_row: str, row_visible: bool):
        self.page = page            # "主城" | "列表"
        self.target_row = target_row
        self.row_visible = row_visible

    def items(self):
        if self.page == "主城":
            return [("主角色", [22, 1249, 61, 20]), *(_NAV_ALL[1:]), _MAIN_CITY_ENTRY]
        out = [*_NAV_ALL, ("更新列表", [615, 328, 82, 28]), *_LIST_TAB_ITEMS]
        if self.row_visible:
            out.append((self.target_row, [200, 650, 180, 36]))
        return out

    def orange(self):
        # 列表屏 / 主城屏都属主城分区 → 四个其它分区页签全灰。
        return dict(_ZERO_ORANGE)


def _apply_action(name: str, screen: _Screen) -> None:
    if name == "SpecialOpenLord":
        screen.page = "列表"
    elif name in ("SpecialTabLord", "SpecialTabJoss"):
        screen.page = "列表"
    elif name == "PubReturnHome":
        screen.page = "主城"


def simulate(entry: str, screen: _Screen, files: dict, *, rec_overrides=None,
             next_overrides=None, max_steps: int = 400):
    """从 ``entry`` 出发按 MAA ``next`` / ``max_hit`` / ``[JumpBack]`` 语义走。"""
    resolve = _resolver(files)
    counters: dict[str, int] = {}
    seq: list[str] = []
    state = {"steps": 0}

    def node_next(name: str):
        if next_overrides and name in next_overrides:
            return list(next_overrides[name])
        spec = _node(name, files)
        return list((spec or {}).get("next") or [])

    def node_spec(name: str):
        return _node(name, files) or {}

    def matches(name: str) -> bool:
        rec = (rec_overrides or {}).get(name)
        if rec is None:
            import scene.drift as drift  # noqa: PLC0415

            rec = drift._resolve_recognition(name, files)
        return eval_recognition(rec, screen.items(), resolve, screen.orange())

    def dispatch(node_name: str):
        for ref in node_next(node_name):
            if state["steps"] >= max_steps:
                return "LIMIT"
            jb = isinstance(ref, str) and ref.startswith("[JumpBack]")
            name = ref[len("[JumpBack]"):] if jb else ref
            spec = node_spec(name)
            mh = spec.get("max_hit")
            if mh is not None and counters.get(name, 0) >= mh:
                continue
            if not matches(name):
                continue
            state["steps"] += 1
            seq.append(name)
            _apply_action(name, screen)
            counters[name] = counters.get(name, 0) + 1
            r = dispatch(name)
            if r is not None:
                return r
            if jb:
                continue
        return None

    result = dispatch(entry)
    return result, seq


def _node(name: str, files: dict):
    for data in files.values():
        if isinstance(data, dict) and isinstance(data.get(name), dict):
            return data[name]
    return None


def _old_home_rec() -> dict:
    """旧形态判据：只有两叶（底导主城 + 左下返回）——会在列表 / 详情页自匹配。"""
    return {
        "type": "And",
        "param": {
            "all_of": ["PubReturnHomeText", "PubReturnHomeBackTab"],
            "box_index": 0,
        },
    }


def _old_tab_next(files: dict, tab: str) -> list:
    """旧形态页签节点后继：去掉后来才加的滚动后继 SpecialScrollList。"""
    spec = _node(tab, files) or {}
    return [x for x in (spec.get("next") or []) if x != "SpecialScrollList"]


def loop_traces(root: Path | None = None):
    """返回 (新形态序列, 旧形态序列) —— 屏幕 = 列表页、目标行在屏幕外。"""
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    files = drift.load_pipelines(base / _PIPELINE_REL)

    def run(rec_overrides, next_overrides):
        screen = _Screen("列表", "猩红巨熊讨伐", row_visible=False)
        _result, seq = simulate(
            "SpecialEntry", screen, files,
            rec_overrides=rec_overrides, next_overrides=next_overrides, max_steps=400,
        )
        return seq

    new_seq = run(None, None)
    old_next = {
        "SpecialTabLord": _old_tab_next(files, "SpecialTabLord"),
        "SpecialTabJoss": _old_tab_next(files, "SpecialTabJoss"),
    }
    old_seq = run({"PubReturnHome": _old_home_rec()}, old_next)
    return new_seq, old_seq


def _reachable_failures(root: Path | None = None) -> list[str]:
    new_seq, old_seq = loop_traces(root)
    msgs: list[str] = []

    if "SpecialScrollList" not in new_seq:
        msgs.append(f"滚动路径不可达：新形态在「目标行在屏幕外」时从未执行 SpecialScrollList：{new_seq[:12]}")
    if "PubReturnHome" in new_seq:
        msgs.append(f"兜底抢跑：新形态仍命中 PubReturnHome（目标行在屏幕外时不该被带回主城）：{new_seq[:12]}")
    if "SpecialScrollList" not in new_seq[:2]:
        msgs.append(
            f"新形态应在选行不命中后【先去滚】(SpecialScrollList 在前两步内)，实际 {new_seq[:3]}"
        )

    if "SpecialScrollList" in old_seq:
        msgs.append(f"旧形态竟执行了 SpecialScrollList（不应发生）：{old_seq[:12]}")
    if "PubReturnHome" not in old_seq:
        msgs.append(f"旧形态未复现「兜底抢跑」：{old_seq[:12]}")
    return msgs


def probe_list_scroll_path_reachable() -> bool:
    """#29 守卫 2：目标行在屏幕外 → 新形态走到滚动、旧形态被兜底抢跑（死循环）。"""
    return _reachable_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_29.py`）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook29_assets_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
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


def _break_drop_discriminator(root: Path) -> None:
    """产物级：把第三叶（页面范围判别叶）从归位判据里去掉 —— 回到 #18 的两叶形态。"""
    _sub(
        root / _PIPELINE_REL / _COMMON,
        '                    "PubReturnHomeBackTab",\n'
        '                    "PubReturnHomeOtherSection"\n',
        '                    "PubReturnHomeBackTab"\n',
    )


def _break_drop_scroll(root: Path) -> None:
    """产物级：把滚动后继 SpecialScrollList 从两个页签节点后继里去掉。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '            "SpecialScrollList",\n'
        '            "[JumpBack]PubReturnHome",\n',
        '            "[JumpBack]PubReturnHome",\n',
    )


def _run_probe_in(root: Path, probe_name: str):
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks.hooks_29 import " + probe_name + "\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral29_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
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


def prove_red() -> bool:
    """真实绿；去掉判别叶 / 去掉滚动后继 -> 守卫各自变红。"""
    scene_on_path()
    print("hooks_29 prove-red：去掉页面范围判别叶 / 去掉滚动后继，要求守卫各自变红")
    green = (
        probe_return_home_scope_not_chain_page() is True
        and probe_list_scroll_path_reachable() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：归位不在链上页面命中 + 滚动可达（绿）")
    if not green:
        return False

    # (a) 去掉第三叶 -> 归位又在列表 / 详情页命中。
    root = _temp_assets()
    try:
        _break_drop_discriminator(root)
        msgs = _scope_failures(root)
        red_a = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_a else 'FAIL'}] 去掉页面范围判别叶 -> "
              f"{'红' if red_a else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 去掉滚动后继 -> 滚动不可达、被兜底抢跑。
    root = _temp_assets()
    try:
        _break_drop_scroll(root)
        msgs = _reachable_failures(root)
        red_b = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_b else 'FAIL'}] 去掉滚动后继 -> "
              f"{'红' if red_b else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ok = green and red_a and red_b
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-scope-not-chain-page",
        "#29",
        "兜底归位不在链上步骤页面（列表页 / 详情页 / 编队页）命中，只在非主城分区页命中"
        "（真机帧正反例）",
        probe_return_home_scope_not_chain_page,
    ),
    (
        "list-scroll-path-reachable",
        "#29",
        "离线复现：目标行在屏幕外时旧形态被兜底抢跑死循环 / 新形态走到 SpecialScrollList 滚动找行",
        probe_list_scroll_path_reachable,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
