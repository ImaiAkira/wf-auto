# -*- coding: utf-8 -*-
"""#63：深渊EX 编队页被 ``abyss_state`` 误判成「主城」（主城锚点过松）—— 契约挂点。

seam：``agent/battle_loop_core.py``（主城判据的**唯一共享源**：独有锚点 ≥2）、
``agent/abyss_impl.py`` / ``agent/wuchong_impl.py`` / ``agent/side_impl.py``（各场景 classify）、
``tools/live_harness.py``（归位主城判据，与上述同源）。

缺口（真机设备实证，``127.0.0.1:16448``）
------------------------------------------
深渊EX 首跑里，``abyss_state`` 的主城判据用的是**六锚点宽松集**
（``修行之道/成长任务/当前进度/活动/关卡/领主战``，任意 ≥2）。其中 ``活动``（枢纽/列表页常驻
的「活动时间：…」会命中）、``关卡``、``领主战`` 在**别的页面**也有 —— 于是带两个这类词的画面
（#31 的领主战列表页 = 活动进行中 + 领主战；深渊/五重的编队页过渡帧）会被误判成主城，端到端
表现为 ``[!] 点击后 state=main_city`` → 空点击 → 重新导航。这与 ``#31`` 在 harness 里修过的
是同一个坑；深渊侧没跟上。

两个守卫（都在本文件里，prove-red 也在本文件里）
------------------------------------------------
* ``abyss-team-page-not-main-city`` —— 真机形态的**编队页**帧不得是 ``main_city``（正例：主城帧）；
* ``main-city-predicate-single-source`` —— 主城判据（独有锚点集 + 判据内核）**只有一份**，
  abyss / wuchong / phantom / side 与 harness 取的是同一份对象（复制即漂移，#63）。

★prove-red★（``python tools\\contract_hooks\\hooks_63.py``）：
  * 把主城判据倒回六锚点「任意 ≥2」-> 含「活动+领主战」两宽松锚点的帧被判成 ``main_city``
    （守卫 1 红）—— 证明收紧是必要而非装饰。

真机帧来源（内嵌其 720 空间 OCR，离线可求值）：
  * 主城：``abyss_16448c_00_start.ocr.txt``（修行之道 / 成长任务 / 当前进度 / 活动 / 关卡 / 领主战）；
  * 编队页：``abyss_cal/10_abyss_team.ocr.txt`` 与 ``abyss_cal/12_abyss_team_via_row.ocr.txt``；
  * 宽松危险帧：``#31`` 的领主战列表页真机帧（``活动进行中！`` + ``领主战``；零独有锚点）。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


# ---------------------------------------------------------------------------
# 真机帧（720 空间 OCR；坐标取自上面点名的 .ocr.txt / #31 的帧）
# ---------------------------------------------------------------------------
#: 主城（真机 ``abyss_16448c_00_start``）：三个主城【独有】锚点全中（+ 三个宽松锚点）。
MAIN_CITY_OCR: list[tuple[str, list[int]]] = [
    ("修行之道", [15, 725, 161, 45]),
    ("成长任务", [47, 368, 118, 33]),
    ("当前进度", [366, 928, 60, 20]),
    ("活动", [80, 1120, 62, 34]),
    ("关卡", [313, 1088, 93, 49]),
    ("领主战", [569, 1121, 78, 29]),
    ("主城", [157, 1248, 44, 25]),
]

#: 深渊EX 单人编队页（真机 ``abyss_cal/10_abyss_team``）：Party 卡 / 复制 / 返回 / 不可续战…
#: ★零主城独有锚点，也零宽松锚点★ —— 收紧前后都不是 main_city，但**必须**保持不是。
ABYSS_TEAM_OCR: list[tuple[str, list[int]]] = [
    ("返回", [30, 1246, 46, 26]),
    ("Party G", [39, 301, 98, 36]),
    ("Party F", [41, 537, 94, 33]),
    ("Party A", [39, 769, 97, 36]),
    ("不可续战", [219, 124, 93, 28]),
    ("深渊连战EX第1战", [222, 154, 231, 28]),
    ("推荐属性", [226, 205, 91, 23]),
    ("体力", [383, 205, 47, 25]),
    ("战斗", [104, 214, 32, 20]),
    ("复制", [557, 406, 86, 34]),
    ("战力", [530, 542, 39, 22]),
]

#: 深渊EX 编队页（经 boss 行进入的变体，真机 ``abyss_cal/12_abyss_team_via_row``）：
#: 本页**常驻**『活动时间：…』→ 命中宽松锚点 `活动`（1 个，故六锚点也还没到 ≥2，
#: 但一旦过渡帧再带上主城残留的『领主战/关卡』就会 ≥2 → 被误判）。
ABYSS_TEAM_ROW_OCR: list[tuple[str, list[int]]] = [
    ("返回", [30, 1246, 46, 26]),
    ("任务", [39, 144, 48, 26]),
    ("推荐编成", [56, 1114, 96, 30]),
    ("战斗", [87, 1082, 32, 20]),
    ("深渊连战EX", [127, 433, 454, 91]),
    ("活动时间：2000.01/0112:00-2099.12/29 23:59", [149, 72, 418, 22]),
    ("主城", [157, 1248, 44, 25]),
    ("深渊连战EX第1战", [201, 1040, 237, 32]),
    ("不可续战", [203, 1013, 90, 24]),
    ("推荐属性", [207, 1116, 88, 28]),
    ("角色", [275, 1244, 47, 29]),
    ("ABYSS", [313, 516, 73, 16]),
    ("ONSLAUGHT", [385, 518, 116, 14]),
    ("体力", [363, 1117, 47, 24]),
    ("商店", [397, 1246, 45, 26]),
    ("放弃", [431, 897, 46, 25]),
    ("战斗记录", [514, 894, 80, 32]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 宽松危险帧（真机领主战列表页，``#31`` 设备实证）：`活动进行中！`(→活动) + `领主战`，
#: 零主城独有锚点 —— 六锚点「任意 ≥2」会把它判成主城；三独有锚点不会。
#: 深渊/五重的编队页过渡帧是**同一类**画面（本页的『活动时间』+ 主城残留的『领主战/关卡』）。
LOOSE_DANGER_OCR: list[tuple[str, list[int]]] = [
    ("活动进行中！", [11, 301, 183, 32]),
    ("领主战", [135, 388, 90, 34]),
    ("领主战", [201, 453, 70, 28]),
    ("降临讨伐", [481, 389, 117, 32]),
    ("返回", [31, 1246, 45, 26]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [276, 1246, 45, 27]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [635, 1245, 47, 31]),
]

#: 五重编队页（真机形态，``hooks_auto_outside.TEAM_PAGE_ITEMS``）：SET/Party/自动/挑战/返回。
WUCHONG_TEAM_OCR: list[tuple[str, list[int]]] = [
    ("SET 1", [70, 457, 38, 15]),
    ("Party E", [92, 512, 97, 36]),
    ("自动续战", [18, 1062, 78, 24]),
    ("自动", [142, 1062, 43, 26]),
    ("挑战", [296, 1053, 82, 47]),
    ("返回", [30, 1246, 46, 26]),
]


def _texts(items) -> list[str]:
    return [(t or "").strip() for t, _ in items if (t or "").strip()]


def _loose_main_city(items) -> bool:
    """旧规则（#31 之前的六锚点「任意 ≥2」）—— 仅用于 prove-red 复现误判。"""
    import battle_loop_core as core  # noqa: PLC0415

    hits = [a for a in core.MAIN_CITY_ANCHORS if any(a in t for t in _texts(items))]
    return len(hits) >= 2


# ---------------------------------------------------------------------------
# 守卫 1：编队页绝非主城
# ---------------------------------------------------------------------------
def _classify_failures(classify_fn) -> list[str]:
    msgs: list[str] = []

    if classify_fn(list(MAIN_CITY_OCR))[0] != "main_city":
        msgs.append("主城真机帧没有被判为主城（收紧过头）")

    for label, frame in (
        ("深渊EX 编队页(10_abyss_team)", ABYSS_TEAM_OCR),
        ("深渊EX 编队页(12_abyss_team_via_row)", ABYSS_TEAM_ROW_OCR),
    ):
        if classify_fn(list(frame))[0] == "main_city":
            msgs.append(f"{label} 被判成主城（#63 回归：编队页绝不能是 main_city）")

    if classify_fn(list(LOOSE_DANGER_OCR))[0] == "main_city":
        msgs.append(
            "含『活动+领主战』两宽松锚点、零独有锚点的帧被判成主城（六锚点判据回归，#63/#31）"
        )
    return msgs


def probe_abyss_team_not_main_city() -> bool:
    _paths()
    import abyss_impl as ab  # noqa: PLC0415

    return _classify_failures(ab.classify) == [] and _wuchong_failures() == []


def _wuchong_failures() -> list[str]:
    """五重 classify 同样不得把编队页 / 宽松危险帧判成主城（它与深渊同族）。"""
    import wuchong_impl as wc  # noqa: PLC0415

    msgs: list[str] = []
    if wc.classify(list(WUCHONG_TEAM_OCR))[0] == "main_city":
        msgs.append("五重编队页被判成主城（#63 回归：编队页绝不能是 main_city）")
    if wc.classify(list(LOOSE_DANGER_OCR))[0] == "main_city":
        msgs.append("五重 classify：含『活动+领主战』两宽松锚点的帧被判成主城（六锚点回归）")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 2：主城判据单源（防漂移）
# ---------------------------------------------------------------------------
def _shared_source_failures() -> list[str]:
    _paths()
    import battle_loop_core as core  # noqa: PLC0415

    msgs: list[str] = []
    mods = []
    import abyss_impl as ab  # noqa: PLC0415
    import phantom_impl as ph  # noqa: PLC0415
    import side_impl as si  # noqa: PLC0415
    import wuchong_impl as wc  # noqa: PLC0415

    mods = [("abyss_impl", ab), ("wuchong_impl", wc), ("phantom_impl", ph), ("side_impl", si)]
    for label, mod in mods:
        got = getattr(mod, "MAIN_CITY_UNIQUE_ANCHORS", None)
        if got is not core.MAIN_CITY_UNIQUE_ANCHORS:
            msgs.append(
                f"{label}.MAIN_CITY_UNIQUE_ANCHORS 不是共享源对象（各自复制一份即漂移，#63）"
            )

    # harness 的归位判据也必须与共享源一致（#31 收紧原样保留，只是改从共享源取）。
    try:
        import live_harness as ca  # noqa: PLC0415

        if tuple(getattr(ca, "MAIN_CITY_UNIQUE_ANCHORS", ())) != tuple(
            core.MAIN_CITY_UNIQUE_ANCHORS
        ):
            msgs.append("live_harness.MAIN_CITY_UNIQUE_ANCHORS 与共享源不一致（harness 会漂移）")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"无法导入 live_harness 对账共享源：{exc!r}")

    if tuple(core.MAIN_CITY_UNIQUE_ANCHORS) != ("修行之道", "成长任务", "当前进度"):
        msgs.append(f"共享主城独有锚点集被改：{core.MAIN_CITY_UNIQUE_ANCHORS!r}")
    return msgs


def probe_main_city_predicate_single_source() -> bool:
    return _shared_source_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_63.py`）
# ---------------------------------------------------------------------------
class _LooseClassify:
    """坏实现：主城判据倒回六锚点「任意 ≥2」（#31 之前的坑）；其余委托真实 classify。"""

    @staticmethod
    def classify(items, relogin_phrases=()):
        if _loose_main_city(items):
            import battle_loop_core as core  # noqa: PLC0415

            hits = [a for a in core.MAIN_CITY_ANCHORS if any(a in t for t in _texts(items))]
            return "main_city", {"anchors": hits}
        import abyss_impl as ab  # noqa: PLC0415

        return ab.classify(items, relogin_phrases)


def prove_red() -> bool:
    _paths()
    import abyss_impl as ab  # noqa: PLC0415

    print("hooks_63 prove-red：把主城判据倒回六锚点，要求守卫变红")
    green = probe_abyss_team_not_main_city() is True and probe_main_city_predicate_single_source() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：编队页非主城 + 判据单源（绿）")
    if not green:
        return False

    # (a) 宽松危险帧在真机上确实会被六锚点误判（证明收紧是必要的）。
    loose_hits = _loose_main_city(LOOSE_DANGER_OCR)
    print(f"  [{'PASS' if loose_hits else 'FAIL'}] 六锚点规则在『活动+领主战』帧上命中主城 -> "
          f"{'是' if loose_hits else '否'}")
    if not loose_hits:
        return False

    # (b) 把 classify 倒回六锚点 -> 守卫 1 红。
    red_classify = len(_classify_failures(_LooseClassify.classify)) > 0
    print(f"  [{'PASS' if red_classify else 'FAIL'}] 主城判据倒回六锚点 -> "
          f"{'红' if red_classify else '仍绿'}")
    return red_classify


HOOKS = [
    (
        "abyss-team-page-not-main-city",
        "#63",
        "深渊EX 编队页不得被判成主城（真机帧正反例）；六锚点宽松判据会把『活动+领主战』帧误判成主城",
        probe_abyss_team_not_main_city,
    ),
    (
        "main-city-predicate-single-source",
        "#63",
        "主城判据（独有锚点 ≥2）单源：abyss/wuchong/phantom/side 与 harness 取同一份，绝不漂移",
        probe_main_city_predicate_single_source,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
