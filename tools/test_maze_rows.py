# -*- coding: utf-8 -*-
"""离线单测（#54）：摇曳的迷宫（farm）目标 = 【域 + 行名】（修订 #52 的「域 + 元素」）。

不需要游戏 / 设备，直接跑：

    .venv\\Scripts\\python.exe tools\\test_maze_rows.py

覆盖 #54 验收：
  1. **真源一致**：``scene.config.MAZE_ROWS``（域 → 异质行列表）== ``agent/batch_plan``
     （含安装态快照）；三域 = farm；行数 22 / 6 / 10。
  2. **配置为真源**：GUI「打哪个迷宫域 / 行」两份 case 与 ``scene.options`` 派生逐项一致
     （``scene.drift.maze_option_drift == []`` 且 ``check_all == []``）。
  3. **批量清单**：``域,行名,次数``（行名须属于该域）；旧「域,元素 / 域,难度」写法不合法。
  4. **行匹配**：滚动判据接受「的迷宫 / 迷宮」+ 三域标记；``FarmDomainPick`` 在场；
     ``_farm_override`` 写 行名 + 域。
  5. **真机帧**：定位各域各行【战斗】框并回指同一行；★绝不误选相邻行★；★丢片段容错★。
  6. **farm 不再是能力缺口**：``declared_unreachable("farm")`` 为 None（raid 仍声明）。
  7. **守卫 + 破坏实验**：``hooks_54`` 已点亮、自带 prove-red；``hooks_52`` 仍绿。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import batch_plan as bp  # noqa: E402
import side_impl as si  # noqa: E402
import hooks_52  # noqa: E402
import hooks_54  # noqa: E402
from scene import drift  # noqa: E402
from scene import options as sc_options  # noqa: E402
from scene.config import MAZE_DOMAINS, MAZE_ROWS  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"
FARM = REPO_ROOT / "assets" / "resource" / "pipeline" / "farm.json"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. 真源一致
# ---------------------------------------------------------------------------
def test_vocabulary_sync() -> None:
    print("\n== 1. 「域 → 行名列表」：scene 真源 == batch_plan（含安装态快照） ==")
    check("MAZE_DOMAINS == scene.config（三域）",
          tuple(bp.MAZE_DOMAINS) == tuple(MAZE_DOMAINS) == ("崩坏域", "宝物域", "幽玄域"),
          f"bp={bp.MAZE_DOMAINS}")
    for d in MAZE_DOMAINS:
        check(f"域 {d} 行列表 == scene.config",
              tuple(bp.MAZE_ROWS[d]) == tuple(MAZE_ROWS[d]),
              f"bp={bp.MAZE_ROWS[d][:2]}…")
    check("行数 22 / 6 / 10",
          {d: len(bp.MAZE_ROWS[d]) for d in bp.MAZE_DOMAINS}
          == {"崩坏域": 22, "宝物域": 6, "幽玄域": 10})
    for row in ("临境域深渊之兽·极", "深层域1【火】Lv50", "深层域3【暗】Lv70",
                "摇曳的迷宫宝物域【火】", "幽玄域【1〜3层】", "幽玄域【28〜30层】"):
        check(f"关键行 {row} 在场", bp.maze_domain_of(row) is not None)
    check("安装态快照与词表一致",
          {d: tuple(v) for d, v in bp._MAZE_ROWS_SNAPSHOT.items()}
          == {d: tuple(v) for d, v in bp.MAZE_ROWS.items()})
    for d in MAZE_DOMAINS:
        check(f"{d} → farm", bp.detect_kind(d) == "farm" and bp.is_farm(d))
    check("含「迷宫」的旧名仍判 farm（向后兼容）", bp.detect_kind("光之迷宫") == "farm")


# ---------------------------------------------------------------------------
# 2. 配置为真源（GUI 选项派生）
# ---------------------------------------------------------------------------
def test_gui_options_derived() -> None:
    print("\n== 2. GUI「打哪个迷宫域 / 行」= 配置派生（drift 空） ==")
    dom_block = sc_options.derive_maze_domain_block()
    row_block = sc_options.derive_maze_row_block()
    check("域 option：select，case 数 = 域数，default=宝物域",
          dom_block["type"] == "select" and len(dom_block["cases"]) == len(MAZE_DOMAINS)
          and dom_block["default_case"] == "宝物域")
    check("域 case 名 = 词表顺序",
          [c["name"] for c in dom_block["cases"]] == list(MAZE_DOMAINS))
    exp_rows = [r for d in MAZE_DOMAINS for r in MAZE_ROWS[d]]
    check("行 option：select，case = 全域行名（按域分组，顺序一致）",
          row_block["type"] == "select"
          and [c["name"] for c in row_block["cases"]] == exp_rows
          and row_block["default_case"] == "摇曳的迷宫宝物域【火】",
          f"n={len(row_block['cases'])}")
    dp = dom_block["cases"][0]["pipeline_override"]["FarmDomainPick"]["recognition"]["param"]
    check("域 case 落点 = FarmDomainPick（domain）",
          dp["custom_recognition"] == "special_target_fight"
          and dp["custom_recognition_param"]["domain"] == "崩坏域")
    ff = row_block["cases"][0]["pipeline_override"]["FarmFight"]["recognition"]["param"]
    check("行 case 落点 = FarmFight（target=行名, domain=域, pair=below）",
          ff["custom_recognition"] == "special_target_fight"
          and ff["custom_recognition_param"]["target"] == "临境域深渊之兽·极"
          and ff["custom_recognition_param"]["domain"] == "崩坏域"
          and ff["custom_recognition_param"]["pair"] == "below")
    check("drift.maze_option_drift(interface) == []",
          drift.maze_option_drift(INTERFACE) == [], f"{drift.maze_option_drift(INTERFACE)}")
    check("drift.check_all() == []", drift.check_all(repo_root=REPO_ROOT) == [],
          f"{drift.check_all(repo_root=REPO_ROOT)}")


# ---------------------------------------------------------------------------
# 3. 批量清单解析
# ---------------------------------------------------------------------------
def test_batch_parse() -> None:
    print("\n== 3. 批量清单：域,行名,次数（行名须属于该域） ==")
    items, errors = bp.parse_batch("崩坏域,临境域深渊之兽·极,1\n幽玄域,幽玄域【1〜3层】,2\n")
    check("两条都解析成功", errors == [] and len(items) == 2, f"errors={errors}")
    a, b = items
    check("域=崩坏域 行名=临境域深渊之兽·极 target=行名 domain=域",
          (a.kind, a.dungeon, a.target, a.domain)
          == ("farm", "崩坏域", "临境域深渊之兽·极", "崩坏域"))
    check("域=幽玄域 行名=幽玄域【1〜3层】",
          (b.dungeon, b.target) == ("幽玄域", "幽玄域【1〜3层】"))
    check("账本 key 用 域/行名",
          bp.item_prefix(a) == "special_dungeon_batch/崩坏域/临境域深渊之兽·极")
    for d in MAZE_DOMAINS:
        for row in MAZE_ROWS[d][:2]:
            _it, err = bp.parse_batch(f"{d},{row},1\n")
            check(f"合法行 {d}/{row}", err == [] and len(_it) == 1, f"errors={err}")
    _it, err = bp.parse_batch("崩坏域,摇曳的迷宫宝物域【火】,1\n")
    check("跨域行名（崩坏域 + 宝物域的行）报错", len(err) == 1, f"errors={err}")
    for text in ("宝物域,风,3\n", "宝物域,中级,3\n", "光之迷宫,中级,3\n"):
        _it, err = bp.parse_batch(text)
        check(f"旧写法 {text.strip()!r} 不合法（第二字段现在是行名）",
              len(err) == 1, f"errors={err}")
    _it, err = bp.parse_batch("深层域3【暗】Lv70,1\n")
    check("缺域（第一字段不是域）报错", len(err) == 1, f"errors={err}")


# ---------------------------------------------------------------------------
# 4. pipeline 行匹配 + override 落点
# ---------------------------------------------------------------------------
def test_pipeline_and_override() -> None:
    print("\n== 4. pipeline：滚动判据 + FarmDomainPick + override 落点 ==")
    farm = FARM.read_text(encoding="utf-8")
    check("farm.json 滚动判据接受「的迷宫」", '"的迷宫"' in farm)
    check("farm.json 滚动判据接受繁体「的迷宮」", '"的迷宮"' in farm)
    for marker in ("临境域", "深层域", "幽玄域"):
        check(f"farm.json 滚动判据接受域标记「{marker}」", f'"{marker}"' in farm)
    check("farm.json 有域落点节点 FarmDomainPick", '"FarmDomainPick"' in farm)
    check("farm.json 已移除元素落点 FarmElementPick", '"FarmElementPick"' not in farm)
    items, _e = bp.parse_batch("崩坏域,深层域3【暗】Lv70,1\n")
    ov = si._farm_override(items[0])
    p = ov["FarmFight"]["recognition"]["param"]["custom_recognition_param"]
    check("FarmFight override：target=行名, domain=域, pair=below, max_hit=1",
          p["target"] == "深层域3【暗】Lv70" and p["domain"] == "崩坏域" and p["pair"] == "below"
          and ov["FarmFight"]["max_hit"] == 1)
    check("FarmDomainPick override：domain=域",
          ov["FarmDomainPick"]["recognition"]["param"]
            ["custom_recognition_param"]["domain"] == "崩坏域")
    check("override 不再写 FarmElementPick", "FarmElementPick" not in ov)


# ---------------------------------------------------------------------------
# 5. 真机帧：定位战斗框 + 回指同一行 + 相邻行守护 + 丢片段容错
# ---------------------------------------------------------------------------
def test_row_match_on_frames() -> None:
    print("\n== 5. 真机帧（720）：定位战斗框 / 回指同一行 / 绝不误选相邻行 / 丢片段容错 ==")
    check("hooks_54 帧正证探针绿（含 崩坏域·深渊之兽·极 优先行）",
          hooks_54.probe_maze_rows() is True)
    # 优先行：崩坏域 临境域深渊之兽·极（体力 0）—— 命中其【战斗】框 y≈501。
    box, detail = hooks_54._pick(si, hooks_54.BENG_ITEMS, "临境域深渊之兽·极")
    check("优先行 临境域深渊之兽·极 → 战斗框 [87,501,…]",
          box is not None and list(box) == [87, 501, 32, 16], f"{box}")
    check("优先行回指同一行（#35 归属证明）",
          (detail.get("row_owner") or [None])[0] == "临境域深渊之兽·极", f"{detail.get('row_owner')}")
    # 相邻行：目标 深层域3【暗】Lv70 vs 屏上 深层域3【水】Lv70 -> 不得命中。
    b2, _d2 = hooks_54._pick(si, hooks_54.DEEP_ITEMS, "深层域3【暗】Lv70")
    check("目标 深层域3【暗】Lv70 不误选屏上的 深层域3【水】Lv70", b2 is None, f"{b2}")
    # 丢片段：深层域3【雷】Lv70 的 【雷】/Lv 被 OCR 丢掉 -> 仍命中本行。
    dropped = hooks_54._strip_fragments(hooks_54.DEEP_ITEMS)
    b3, _d3 = hooks_54._pick(si, dropped, "深层域3【雷】Lv70")
    check("丢片段后仍命中本行（深层域3【雷】Lv70）", b3 is not None, f"{b3}")


# ---------------------------------------------------------------------------
# 6. farm 不再是能力缺口；raid 仍声明
# ---------------------------------------------------------------------------
def test_not_declared() -> None:
    print("\n== 6. farm 不再是能力缺口（#54）；raid 仍声明（#45） ==")
    check("declared_unreachable('farm') is None", si.declared_unreachable("farm") is None)
    check("declared_unreachable('raid') 仍在", si.declared_unreachable("raid") is not None)
    check("_BATCH_NAV_TIMEOUT_BY_KIND == {'raid': 0.0}",
          si._BATCH_NAV_TIMEOUT_BY_KIND == {"raid": 0.0}, f"{si._BATCH_NAV_TIMEOUT_BY_KIND}")


# ---------------------------------------------------------------------------
# 7. 守卫 + 破坏实验
# ---------------------------------------------------------------------------
def test_guard_and_prove_red() -> None:
    print("\n== 7. 守卫 hooks_54 + prove-red（两处破坏各自变红）；hooks_52 仍绿 ==")
    check("hooks_54.probe_maze_rows() 绿", hooks_54.probe_maze_rows() is True)
    check("hooks_54.prove_red() 成立", hooks_54.prove_red() is True)
    check("hooks_52.probe_maze_by_domain() 仍绿（#54 修订后）",
          hooks_52.probe_maze_by_domain() is True)
    check("hooks_52.prove_red() 成立", hooks_52.prove_red() is True)


def main() -> int:
    print("=" * 76)
    print("#54：摇曳的迷宫（farm）目标 = 【域 + 行名】（修订 #52 的「域 + 元素」）")
    print("=" * 76)
    test_vocabulary_sync()
    test_gui_options_derived()
    test_batch_parse()
    test_pipeline_and_override()
    test_row_match_on_frames()
    test_not_declared()
    test_guard_and_prove_red()
    print("\n" + "=" * 76)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
