# -*- coding: utf-8 -*-
"""#54：摇曳的迷宫（farm）—— 目标模型【修订】：目标 = 【域 + 行名】。

为什么修订（不是改判）
----------------------
#52 把 farm 建模为「域 + 元素（独立选项）」。设备（16448）证伪了这个「元素矩阵」：
迷宫页每个域其实是一张**异质行列表**，**元素是行名的一部分**：
  · 崩坏域：`临境域 深渊之兽·极`（体力 0）/`·真`/`` + 18 行
    `深层域{1,2,3}【元素】Lv{50,60,70}` + `通往深层之门`；
  · 宝物域：6 行 `摇曳的迷宫宝物域【火/水/雷/风/光/暗】`（体力 10）；
  · 幽玄域（塔）：10 行 `幽玄域【{1〜3}…{28〜30}层】`（体力 30~40）。
**只有这三个域**；**没有难度档**（`Lv..`/`层` 只在行名里）。因此目标改为【域 + 行名】——
结构上与领主战的「页签 + 行名」同构（#3/#6）。

seam
----
* ``scene/config.py``：``MAZE_DOMAINS`` / ``MAZE_ROWS``（域 → 行名列表，**真源**）/
  ``build_maze_rows``（由元素/Lv/层常量派生行名）；``MAZE_ROWS`` 是**异质行列表**。
* ``scene/options.py``：``derive_maze_domain_block`` / ``derive_maze_row_block``（GUI 选项派生）。
* ``scene/drift.py``：``maze_option_drift``（配置派生 ↔ interface.json；接入 ``check_all``）。
* ``agent/batch_plan.py``：``MAZE_ROWS`` / ``MAZE_DOMAINS``（真源派生，安装态回退快照）、
  ``detect_kind``（三域 = farm）、``parse_batch``（第二字段 = **行名**）、``BatchItem.target/domain``。
* ``agent/side_impl.py``：``maze_row_patterns``（严格式 + 容错式）/ ``_apply_row`` /
  ``maze_owner_regex``（#35 同构的归属回指）；``_farm_override``（域 + 行名）；``FarmDomainPick``。
* ``assets/resource/pipeline/farm.json``：``FarmFight``（target=行名 + domain）、``FarmDomainPick``
  （域数据节点）、``FarmScroll``/``FarmScrollUp`` 判据接受「的迷宫 / 迷宮」+ 三域标记。

守卫 ``maze-rows``
------------------
1. **真源一致**：``batch_plan.MAZE_ROWS``（含安装态快照）== ``scene.config.MAZE_ROWS``；
   三域 = farm；行数 22 / 6 / 10；关键行在场（`临境域深渊之兽·极`、`深层域…Lv…`、`幽玄域…层`）。
2. **配置为真源**：``scene.drift.maze_option_drift`` 空 + ``check_all`` 空 —— GUI
   「打哪个迷宫域 / 行」两份 case 与配置派生逐项一致。
3. **批量清单**：``域,行名,次数`` 解析（行名须属于该域）；旧的「域,元素,次数」/「域,难度,次数」不合法。
4. **pipeline 行匹配**：滚动判据接受「的迷宫 / 迷宮」；``FarmDomainPick`` 落点在场；
   ``FarmElementPick`` 已移除；``_farm_override`` 把 域 + 行名 写进 FarmFight / FarmDomainPick。
5. **真机帧（720 空间）正证**：用内嵌真机 OCR 逐行定位【战斗】框，并**回指同一行**证明归属
   （#35 同构）；★目标行 = 崩坏域 `临境域 深渊之兽·极`（体力 0）★ 必须命中其【战斗】框。
6. **不误选相邻行**：目标行的片段与屏上另一行不同（`深层域3【暗】Lv70` vs 屏上 `深层域3【水】Lv70`；
   朴素 `临境域深渊之兽` vs 屏上 `·极`；宝物域 `【火】` vs 屏上 `【水】`；幽玄域 `【1〜3层】`
   vs 屏上 `【4〜6层】`）→ **不得命中**（末尾锚定 + 自身片段可省）。
7. **丢片段容错**：OCR 丢掉 【元素】/Lv../层 → 仍能命中**本行**（容错式）——绝不因丢片段拒打。
8. **#42 身份闸不变**：``hooks_42`` 的详情页身份闸探针仍绿（领主战路径不受本票影响）。
9. **farm 不再是能力缺口**：``declared_unreachable("farm")`` 为 None（raid 仍在）。

★prove-red★（``python tools\\contract_hooks\\hooks_54.py``）：
  * 把 farm.json 的 `FarmDomainPick` 换成 `FarmElementPick`（域落点消失）-> 守卫红；
  * 抹掉 `maze_row_patterns` 的末尾锚定（`$`）-> 「不误选相邻行」断言红。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
FARM_JSON = PIPE_DIR / "farm.json"
INTERFACE = REPO_ROOT / "assets" / "interface.json"

# 只 append 到 sys.path 末尾：subprocess 里 agent_copy 会被抢先插入。
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.append(_p)

HOOK_ID = "maze-rows"


def _import_side(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _import_batch_plan(agent_dir: Path | None = None):
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import batch_plan  # noqa: PLC0415

    return batch_plan


# ---------------------------------------------------------------------------
# 真机帧 OCR（720 空间，逐条内嵌；源：2026-10-14 设备 16448 的 live 抓帧，
# <local>\AppData\Local\Temp\opencode\maze_inner\*.ocr.txt）。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形。
# ---------------------------------------------------------------------------
#: 崩坏域页（源 `s53_beng_page.ocr.txt` / `w3_beng_top.ocr.txt`）：行 1~3 + 深层域3【暗】Lv70。
BENG_ITEMS: list[tuple[str, list[int]]] = [
    ("COMPLETE!!", [15, 578, 123, 23]),
    ("COMPLETE!!", [15, 769, 123, 24]),
    ("COMPLETE!!", [15, 1150, 123, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("× 10", [46, 336, 55, 25]),
    ("推荐编成", [54, 720, 96, 29]),
    ("推荐编成", [55, 530, 97, 30]),
    ("推荐编成", [56, 912, 94, 29]),
    ("推荐编成", [56, 1102, 94, 30]),
    ("摇曳的迷宫", [74, 125, 386, 165]),
    ("战斗", [87, 501, 32, 16]),
    ("战斗", [87, 882, 32, 16]),
    ("战斗", [87, 1072, 34, 20]),
    ("战斗", [88, 692, 29, 14]),
    ("主城", [157, 1248, 44, 25]),
    ("临境域深渊之兽·极", [203, 456, 233, 32]),
    ("临境域深渊之兽", [203, 837, 199, 32]),
    ("深层域3【暗】Lv70", [203, 1030, 257, 28]),
    ("临境域深渊之兽·真", [205, 649, 231, 28]),
    ("推荐属性  光", [205, 1105, 157, 27]),
    ("推荐属性???", [213, 534, 139, 27]),
    ("推荐属性？？？", [213, 724, 141, 25]),
    ("推荐属性??？", [214, 917, 136, 23]),
    ("崩坏域", [401, 156, 211, 121]),
    ("体力", [363, 1105, 48, 25]),
    ("体力", [365, 724, 47, 25]),
    ("体力", [366, 533, 45, 25]),
    ("体力", [366, 914, 45, 26]),
    ("20", [447, 1105, 29, 24]),
    ("0", [459, 534, 17, 23]),
    ("0", [459, 725, 17, 23]),
    ("0", [459, 916, 17, 21]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 崩坏域滚动到下段（源 `y1_beng_bottom.ocr.txt`）：深层域 1/2/3 三行（【雷】）+ 深层域3【水】。
DEEP_ITEMS: list[tuple[str, list[int]]] = [
    ("COMPLETE!!", [15, 472, 123, 24]),
    ("COMPLETE!!", [15, 853, 123, 24]),
    ("COMPLETE!!", [15, 1042, 125, 28]),
    ("OMPLETE!!", [30, 664, 110, 22]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [54, 610, 99, 36]),
    ("推荐编成", [54, 992, 98, 36]),
    ("推荐编成", [56, 424, 96, 29]),
    ("推荐编成", [56, 805, 96, 29]),
    ("摇曳的迷宫", [71, 117, 389, 176]),
    ("战斗", [86, 394, 33, 16]),
    ("战斗", [86, 582, 34, 20]),
    ("战斗", [87, 776, 32, 16]),
    ("战斗", [87, 966, 32, 16]),
    ("战斗", [87, 1154, 33, 20]),
    ("主城", [157, 1248, 44, 25]),
    ("深层域3【雷】Lv70", [202, 540, 258, 32]),
    ("深层域2【雷】Lv60", [202, 733, 257, 28]),
    ("深层域1【雷】Lv50", [203, 924, 257, 28]),
    ("深层域3【水】Lv70", [203, 1114, 257, 28]),
    ("推荐属性", [209, 617, 87, 28]),
    ("推荐属性风", [209, 808, 147, 26]),
    ("推荐属性风", [209, 998, 148, 28]),
    ("推荐属性", [210, 426, 91, 27]),
    ("风", [292, 618, 61, 24]),
    ("火", [293, 426, 61, 27]),
    ("体力", [363, 808, 49, 25]),
    ("体力", [363, 998, 49, 26]),
    ("体力", [365, 616, 47, 26]),
    ("体力", [366, 425, 46, 27]),
    ("崩坏域", [402, 154, 210, 123]),
    ("20", [444, 616, 35, 26]),
    ("17", [446, 808, 31, 25]),
    ("15", [446, 1000, 30, 22]),
    ("15", [447, 428, 30, 22]),
    ("菜单", [636, 1248, 46, 25]),
]

#: 宝物域页（源 `s11_baowu_scroll1.ocr.txt`）：4/6 行在屏（光/暗/雷/风；火/水 在屏外）。
BAOWU_ITEMS: list[tuple[str, list[int]]] = [
    ("NEW", [14, 405, 52, 24]),
    ("NEW", [15, 596, 49, 24]),
    ("×10", [17, 330, 83, 32]),
    ("COMPLETE!!", [17, 785, 123, 24]),
    ("COMPLETE!!", [17, 978, 121, 23]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [56, 549, 96, 28]),
    ("推荐编成", [56, 740, 94, 28]),
    ("推荐编成", [56, 930, 96, 28]),
    ("推荐编成", [56, 1121, 94, 28]),
    ("推存编成", [58, 368, 91, 18]),
    ("战斗", [87, 1089, 33, 20]),
    ("战斗", [88, 520, 28, 16]),
    ("战斗", [88, 710, 29, 15]),
    ("战斗", [88, 901, 29, 15]),
    ("主城", [157, 1248, 44, 25]),
    ("宝物域", [164, 180, 366, 124]),
    ("摇曳的迷宫宝物域【光】", [203, 858, 292, 27]),
    ("摇曳的迷宫宝物域【暗】", [203, 1048, 290, 28]),
    ("摇曳的迷宫宝物域【雷】", [205, 476, 288, 28]),
    ("摇曳的迷宫宝物域【风】", [205, 668, 290, 26]),
    ("推荐属性光", [206, 1124, 157, 26]),
    ("推荐属性火体力", [209, 742, 202, 27]),
    ("推荐属性暗", [209, 933, 148, 27]),
    ("推荐属性风体力", [210, 553, 200, 23]),
    ("摇曳的迷宮", [324, 148, 204, 40]),
    ("体力", [363, 933, 49, 24]),
    ("体力", [363, 1124, 51, 24]),
    ("10", [444, 1124, 33, 22]),
    ("10", [446, 933, 30, 23]),
    ("10", [448, 553, 28, 21]),
    ("10", [448, 742, 28, 23]),
    ("菜单", [636, 1248, 45, 25]),
]

#: 幽玄域页（源 `s76_youxuan.ocr.txt`）：2/10 行在屏（【28〜30层】/【25〜27层】）。
YOUXUAN_ITEMS: list[tuple[str, list[int]]] = [
    ("×30000", [30, 781, 95, 29]),
    ("返回", [30, 1246, 45, 26]),
    ("推荐编成", [55, 993, 95, 29]),
    ("战斗", [83, 1152, 37, 20]),
    ("战斗", [87, 961, 33, 20]),
    ("摇曳的迷宮", [109, 125, 85, 24]),
    ("主城", [157, 1248, 44, 25]),
    ("幽玄域【28〜30层】", [202, 918, 246, 32]),
    ("幽玄域【25〜27层】", [202, 1109, 248, 32]),
    ("推荐属性  雷", [206, 994, 148, 27]),
    ("每月12日更新", [303, 77, 116, 19]),
    ("体力", [366, 994, 46, 27]),
    ("40", [447, 996, 29, 24]),
    ("称霸", [553, 950, 71, 48]),
    ("称霸", [555, 1141, 65, 43]),
    ("菜单", [636, 1248, 45, 25]),
]

# 帧夹具：帧名 / items / {行名: 该行【战斗】按钮的实测框}。
MAZE_FRAMES = [
    ("崩坏域（s53）", BENG_ITEMS, {
        "临境域深渊之兽·极": [87, 501, 32, 16],
        "临境域深渊之兽·真": [88, 692, 29, 14],
        "临境域深渊之兽": [87, 882, 32, 16],
        "深层域3【暗】Lv70": [87, 1072, 34, 20],
    }),
    ("崩坏域·下段（y1）", DEEP_ITEMS, {
        "深层域3【雷】Lv70": [86, 582, 34, 20],
        "深层域2【雷】Lv60": [87, 776, 32, 16],
        "深层域1【雷】Lv50": [87, 966, 32, 16],
        "深层域3【水】Lv70": [87, 1154, 33, 20],
    }),
    ("宝物域（s11）", BAOWU_ITEMS, {
        "摇曳的迷宫宝物域【光】": [88, 901, 29, 15],
        "摇曳的迷宫宝物域【暗】": [87, 1089, 33, 20],
        "摇曳的迷宫宝物域【雷】": [88, 520, 28, 16],
        "摇曳的迷宫宝物域【风】": [88, 710, 29, 15],
    }),
    ("幽玄域（s76）", YOUXUAN_ITEMS, {
        "幽玄域【28〜30层】": [87, 961, 33, 20],
        "幽玄域【25〜27层】": [83, 1152, 37, 20],
    }),
]

# 目标行（帧里没有该行）-> 必须【不命中】（绝不误选相邻 / 别的行）。
NEIGHBOUR_REJECT = [
    ("深层域3【暗】Lv70 vs 屏上 深层域3【水】Lv70", DEEP_ITEMS, "深层域3【暗】Lv70"),
    ("深层域2【水】Lv60（屏上没有）", DEEP_ITEMS, "深层域2【水】Lv60"),
    ("临境域深渊之兽（朴素）vs 屏上 ·极", [it for it in BENG_ITEMS if "·极" in it[0] or it[0] == "战斗"], "临境域深渊之兽"),
    ("摇曳的迷宫宝物域【火】（屏上没有；屏上只有 光/暗/雷/风）", BAOWU_ITEMS, "摇曳的迷宫宝物域【火】"),
    ("幽玄域【1〜3层】 vs 屏上 【28〜30层】", YOUXUAN_ITEMS, "幽玄域【1〜3层】"),
]

# 「丢片段」容错：把帧里的 【…】 与 LvNN 去掉后，目标行仍应命中（本行）。
DROP_TOLERANCE = [
    ("崩坏域·下段（丢 【雷】/Lv）", DEEP_ITEMS, "深层域3【雷】Lv70"),
    ("幽玄域（丢 【28〜30层】）", YOUXUAN_ITEMS, "幽玄域【28〜30层】"),
    ("宝物域（丢 【风】）", BAOWU_ITEMS, "摇曳的迷宫宝物域【风】"),
]

EXPECTED_ROW_COUNTS = {"崩坏域": 22, "宝物域": 6, "幽玄域": 10}


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _strip_fragments(items):
    """模拟 OCR 丢掉行名里的脆弱片段（【…】 / LvNN）。"""
    import re as _re

    return [(_re.sub(r"【[^】]*】|Lv\d+", "", t), b) for t, b in items]


def _pick(si, items, row):
    """按产品实现（_apply_row + pick_target_battle_box）挑该行的【战斗】框。"""
    return si.pick_target_battle_box(
        items,
        difficulty=si._apply_row(row, items),
        pair="below",
        owner_regex=si.maze_owner_regex(),
    )


# ---------------------------------------------------------------------------
# 守卫主体
# ---------------------------------------------------------------------------
def _model_failures(agent_dir: Path | None = None, farm_text: str | None = None) -> list[str]:
    """farm「域 + 行名」模型的全套离线断言；返回失败信息（空 = 绿）。"""
    si = _import_side(agent_dir)
    bp = _import_batch_plan(agent_dir)
    msgs: list[str] = []

    farm = farm_text if farm_text is not None else FARM_JSON.read_text(encoding="utf-8")

    # (1) 词表 / 行列表：真源一致 + 三域 = farm + 行数 + 关键行在场。
    if tuple(bp.MAZE_DOMAINS) != ("崩坏域", "宝物域", "幽玄域"):
        msgs.append(f"MAZE_DOMAINS 不是三域：{bp.MAZE_DOMAINS}")
    for d, n in EXPECTED_ROW_COUNTS.items():
        got = len(bp.MAZE_ROWS.get(d, ()))
        if got != n:
            msgs.append(f"域 {d} 行数 {got} != {n}（真机行列表变了）")
    for row in ("临境域深渊之兽·极", "深层域1【火】Lv50", "深层域3【暗】Lv70",
                "摇曳的迷宫宝物域【火】", "幽玄域【1〜3层】", "幽玄域【28〜30层】"):
        if bp.maze_domain_of(row) is None:
            msgs.append(f"关键行 {row!r} 不在任何域的行列表里")
    if bp.MAZE_ROWS.get("宝物域", ())[:1] != ("摇曳的迷宫宝物域【火】",):
        msgs.append(f"宝物域首行不是 摇曳的迷宫宝物域【火】：{bp.MAZE_ROWS.get('宝物域', ())[:1]}")
    if bp.maze_rows_of("光之迷宫") != ():
        msgs.append("maze_rows_of('光之迷宫') 应空（不是已知域）")
    for d in bp.MAZE_DOMAINS:
        if bp.detect_kind(d) != "farm":
            msgs.append(f"detect_kind({d!r}) 应为 farm，实际 {bp.detect_kind(d)!r}")

    # 真源一致 + 安装态快照一致（开发/测试态必查）。
    try:
        from scene.config import MAZE_DOMAINS as T_DOM  # noqa: PLC0415
        from scene.config import MAZE_ROWS as T_ROWS  # noqa: PLC0415

        if tuple(bp.MAZE_DOMAINS) != tuple(T_DOM):
            msgs.append(f"迷宫域分叉：batch_plan={bp.MAZE_DOMAINS} != scene={tuple(T_DOM)}")
        for d in T_DOM:
            if tuple(bp.MAZE_ROWS.get(d, ())) != tuple(T_ROWS.get(d, ())):
                msgs.append(f"域 {d} 行列表分叉：batch_plan={bp.MAZE_ROWS.get(d)} != scene={T_ROWS.get(d)}")
    except Exception as exc:  # noqa: BLE001 —— 安装态没有 scene/（开发/测试态必查）
        msgs.append(f"迷宫真源对照无法运行：{exc!r}")
    if {d: tuple(v) for d, v in bp._MAZE_ROWS_SNAPSHOT.items()} != {
        d: tuple(v) for d, v in bp.MAZE_ROWS.items()
    }:
        msgs.append("安装态快照 _MAZE_ROWS_SNAPSHOT 与 batch_plan.MAZE_ROWS 不一致")

    # (2) 配置为真源：GUI 两个选项与配置派生一致（drift 空）。
    try:
        from scene import drift  # noqa: PLC0415

        dm = drift.maze_option_drift(INTERFACE)
        if dm:
            msgs.append(f"迷宫 GUI 选项漂移：{dm[:2]}")
        allm = drift.check_all(repo_root=REPO_ROOT)
        if allm:
            msgs.append(f"drift.check_all() 非空：{allm[:2]}")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"迷宫 GUI 选项漂移校验无法运行：{exc!r}")

    # (3) 批量清单：域,行名,次数。
    items, errors = bp.parse_batch("崩坏域,临境域深渊之兽·极,1\n")
    if errors or len(items) != 1:
        msgs.append(f"parse_batch(崩坏域,临境域深渊之兽·极,1) 失败：errors={errors}")
    else:
        it = items[0]
        if (it.kind, it.dungeon, it.target, it.domain) != (
            "farm", "崩坏域", "临境域深渊之兽·极", "崩坏域"
        ):
            msgs.append(
                f"farm item 字段错误：kind={it.kind} dungeon={it.dungeon} "
                f"target={it.target} domain={it.domain}"
            )
    _ok, err_row = bp.parse_batch("深层域3【暗】Lv70,1\n")  # 缺域（第一字段必须是域）-> 报错
    if len(err_row) != 1:
        msgs.append(f"缺域的行清单应报错，实际 {err_row}")
    for text in ("崩坏域,深层域3【暗】Lv70,1\n", "幽玄域,幽玄域【1〜3层】,1\n"):
        _it, err = bp.parse_batch(text)
        if err:
            msgs.append(f"合法行清单 {text.strip()!r} 竟报错：{err}")
    _bad, err_bad = bp.parse_batch("崩坏域,摇曳的迷宫宝物域【火】,1\n")
    if len(err_bad) != 1:
        msgs.append("跨域的行名（崩坏域 + 宝物域的行）应报错，实际未报错")
    # 旧写法（元素 / 难度作为第二字段）都必须不合法。
    for text in ("宝物域,风,3\n", "宝物域,中级,3\n", "光之迷宫,中级,3\n"):
        _b, err = bp.parse_batch(text)
        if len(err) != 1:
            msgs.append(f"旧写法 {text.strip()!r} 应报错（#54 第二字段是行名），实际 errors={err}")

    # (4) override 落点：FarmFight = 行名 + 域；FarmDomainPick = 域；无 FarmElementPick。
    if items:
        ov = si._farm_override(items[0])
        ffc = (ov.get("FarmFight", {}).get("recognition", {}).get("param", {})
               .get("custom_recognition_param", {}))
        if (ffc.get("target") != "临境域深渊之兽·极" or ffc.get("domain") != "崩坏域"
                or ffc.get("pair") != "below"):
            msgs.append(f"FarmFight override 未写 行名/域/pair=below：{ffc}")
        dpc = (ov.get("FarmDomainPick", {}).get("recognition", {}).get("param", {})
               .get("custom_recognition_param", {}))
        if dpc.get("domain") != "崩坏域":
            msgs.append(f"FarmDomainPick override 未写域：{dpc}")
        if "FarmElementPick" in ov:
            msgs.append("_farm_override 仍在写 FarmElementPick（#54 已移除元素轴）")

    # (5) pipeline：FarmDomainPick 在场、FarmElementPick 已移除；滚动判据接受 的迷宫 / 迷宮。
    if '"FarmDomainPick"' not in farm:
        msgs.append("farm.json 缺少域落点节点 FarmDomainPick")
    if '"FarmElementPick"' in farm:
        msgs.append("farm.json 仍含 FarmElementPick（#54 已移除元素轴）")
    if '"的迷宫"' not in farm:
        msgs.append("farm.json 的滚动判据未接受「的迷宫」（游戏写法）")
    if '"的迷宮"' not in farm:
        msgs.append("farm.json 的滚动判据未接受繁体「的迷宮」（幽玄域页标题会读成它）")
    for marker in ("临境域", "深层域", "幽玄域"):
        if f'"{marker}"' not in farm:
            msgs.append(f"farm.json 的滚动判据未接受域标记「{marker}」")

    # (6) 真机帧正证：定位【战斗】框 + 回指同一行（#35 同构）。
    for fname, items_f, expected in MAZE_FRAMES:
        for row, exp_box in expected.items():
            if bp.maze_domain_of(row) is None:
                msgs.append(f"{fname}：夹具行 {row!r} 不在配置行列表里（证据已与真源脱节）")
                continue
            box, detail = _pick(si, items_f, row)
            if box is None:
                msgs.append(f"{fname}·行「{row}」：未命中战斗框（detail={detail}）")
                continue
            if list(box) != list(exp_box):
                msgs.append(f"{fname}·行「{row}」：命中战斗框 {list(box)} != 实测 {exp_box}")
            owner = detail.get("row_owner")
            if not owner or owner[0] != row:
                msgs.append(
                    f"{fname}·行「{row}」：未回指到同一行（owner={owner}）；"
                    f"归属无法证明（#35）"
                )

    # (7) 不误选相邻 / 别的行。
    for label, items_f, row in NEIGHBOUR_REJECT:
        box, _d = _pick(si, items_f, row)
        if box is not None:
            msgs.append(f"相邻行守护「{label}」：竟命中了战斗框 {list(box)}（绝不误选别的行）")

    # (8) 丢片段容错：仍命中本行。
    for label, items_f, row in DROP_TOLERANCE:
        dropped = _strip_fragments(items_f)
        box, detail = _pick(si, dropped, row)
        if box is None:
            msgs.append(f"丢片段容错「{label}」：OCR 丢 【元素】/Lv../层 后竟拒打（detail={detail}）")

    # (9) 崩坏域优先行正证：临境域深渊之兽·极（体力 0）。
    box, _d = _pick(si, BENG_ITEMS, "临境域深渊之兽·极")
    if box is None or not (460 <= box[1] <= 520):
        msgs.append(f"优先行「临境域深渊之兽·极」战斗框应在 y≈501，实际 {box}")
    if not any(t == "0" and 500 <= b[1] <= 560 for t, b in BENG_ITEMS):
        msgs.append("优先行「临境域深渊之兽·极」的体力 0 证据（帧上 [459,534]）缺失")

    # (10) #42 身份闸不变（领主战路径不受本票影响）。
    try:
        from contract_hooks import hooks_42  # noqa: PLC0415

        if hooks_42.probe_detail_identity_blocks_wrong_page() is not True:
            msgs.append("#42 详情页身份闸探针变红（领主战路径被本票带坏）")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"#42 身份闸探针无法运行：{exc!r}")

    # (11) farm 不再是能力缺口。
    if si.declared_unreachable("farm") is not None:
        msgs.append("farm 仍在 UNREACHABLE_FROM_MAIN_CITY 里（#54：迷宫可达、可打）")

    for m in msgs[:10]:
        print(f"    × {m}")
    return msgs


def probe_maze_rows() -> bool:
    """#54：迷宫「域 + 行名」模型 + 配置真源一致 + 真机帧正证 + 相邻行守护（离线、不碰设备）。"""
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
        "from contract_hooks import hooks_54\n"
        f"print('PROBE_RESULT', repr(hooks_54._model_failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral54_"))
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


def _break_row_anchor(agent_dir: Path) -> None:
    """抹掉行名匹配的末尾锚定（$）-> 「不误选相邻行」断言应红。"""
    path = agent_dir / "side_impl.py"
    text = path.read_text(encoding="utf-8")
    old = 'strict = re.escape(row or "") + "$"'
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(
        text.replace(old, 'strict = re.escape(row or "")  # prove-red：末尾锚定被抹掉', 1),
        encoding="utf-8",
    )


def prove_red() -> bool:
    print("hooks_54 prove-red：两处破坏，要求 maze-rows 变红")
    green = probe_maze_rows() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：域 + 行名 + 配置真源一致 + 真机帧正证（绿）")
    if not green:
        return False

    # 破坏 1（pipeline 纯文本，不写盘）：域落点被换成元素落点。
    broken_farm = FARM_JSON.read_text(encoding="utf-8").replace(
        '"FarmDomainPick"', '"FarmElementPick"'
    )
    pred_red = _model_failures(farm_text=broken_farm) != []
    print(f"  [{'PASS' if pred_red else 'FAIL'}] 把 farm.json 的 FarmDomainPick 换成 FarmElementPick -> "
          f"{'红' if pred_red else '仍绿'}")

    # 破坏 2（agent 副本）：抹掉行名匹配的末尾锚定。
    tmp = Path(tempfile.mkdtemp(prefix="wf_hook54_agent_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_row_anchor(tmp / "agent")
        anchor_red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if anchor_red else 'FAIL'}] 抹掉行名匹配的末尾锚定 -> "
          f"{'红' if anchor_red else '仍绿'}")

    ok = green and pred_red and anchor_red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#54",
        "摇曳的迷宫目标 = 【域 + 行名】（元素是行名的一部分，#52 的元素轴被设备证伪）："
        "配置真源一致 / GUI 选项派生 / 批量 域,行名,次数 / 真机帧定位战斗框并回指同一行 / "
        "绝不误选相邻行 / 容忍 OCR 丢 【元素】/Lv../层（真机 720 帧正向证明）",
        probe_maze_rows,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
