# -*- coding: utf-8 -*-
"""离线单测（#45）：战阵之宴(raid) 从主城不可达 ⇒ 配置层【声明为能力缺口】。

★#52 起本测试只守 raid★：farm（摇曳的迷宫）曾在 #45 被一起声明为「无法开打」能力缺口；
#52 已按现版本迷宫页（行名「摇曳的迷宫<域>【<元素>】」）把 farm 的目标模型重定为「按【域】选
+【元素】独立选项」，farm 因此**不再是能力缺口**（可达 + 可打）。farm 的模型 / 选项 / 守卫
见 ``tools/contract_hooks/hooks_52.py`` 与 ``tools/test_maze_by_domain.py``。

不需要游戏 / 设备（判据与证据都在这份文件自带的**真机帧 OCR** 上求值）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_raid_farm_nav.py

覆盖：
  1. **raid 能力缺口已声明**：``agent/side_impl.py::UNREACHABLE_FROM_MAIN_CITY`` 含 raid、
     不含 farm；``raid.json`` / ``special_dungeon.json`` 的 #45 段仍写明「不做导航 → 不可达」。
     真机主城 OCR **没有**战阵之宴入口 —— raid 从主城不可达。
  2. **farm 不再被声明**（#52）：``declared_unreachable("farm")`` 为 None；派生宽限只剩 raid=0。
  3. **跳过不再依赖“超时”**：批量清单里遇到 raid，一确认中立页即明确跳过并记录原因，随后
     继续下一条；绝不假记账。对照：把宽限改回 45s，第二帧就不会跳过。
  4. **单目标行为不变**：清单为空（RaidEntry / FarmEntry）时指挥官不介入、不跳过。
  5. **守卫 + 破坏实验**：``hooks_45`` 已点亮、自带 prove-red。
  6. **不变量**：``special_dungeon.json`` 五条承重短语零丢失；``drift.check_all() == []``；
     #9 三条既有路径结构守卫仍绿；其它票挂点不因本票变红。
"""

from __future__ import annotations

import re
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

import side_impl as si  # noqa: E402
from scene import drift  # noqa: E402

import hooks_45  # noqa: E402
import hooks_52  # noqa: E402
from contract_hooks import discover_hooks  # noqa: E402

SD = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"
RAID = REPO_ROOT / "assets" / "resource" / "pipeline" / "raid.json"
FARM = REPO_ROOT / "assets" / "resource" / "pipeline" / "farm.json"

# #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

# 本票必须保持不变的挂点（#44 及更早）。
KEEP_TICKETS = ("#18", "#27", "#29", "#30", "#35", "#36", "#37", "#38", "#39", "#44")
OWN_TICKET = "#45"

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. raid 能力缺口“已声明” + farm 不再声明 + 真机 OCR 证据
# ---------------------------------------------------------------------------
def test_raid_declared_farm_not() -> None:
    print("\n== 1. raid 能力缺口已声明；farm 不再被声明（#52） ==")
    print("   真机主城 OCR（720 空间，找战阵之宴入口）：")
    for t, b in hooks_45.MAIN_CITY_ITEMS:
        if "战阵" in t or "迷宫" in t or "活动" in t or "领主战" in t:
            print(f"     · {t!r} {b}")

    check(
        "真机主城 OCR 里【没有】战阵之宴入口（raid 从主城不可达）",
        not any("战阵之宴" in t for t, _b in hooks_45.MAIN_CITY_ITEMS),
    )
    texts = [t for t, _b in hooks_45.MAZE_ITEMS]
    check(
        "真机迷宫页行名带现版本标记「的迷宫」+ 三域之一（#52 新模型有证据）",
        any("的迷宫" in t for t in texts)
        and any(any(d in t for d in hooks_45.MAZE_DOMAINS) for t in texts),
    )
    check(
        "真机迷宫页行名里【没有】难度档（初级/中级/高级）",
        not any(("初级" in t or "中级" in t or "高级" in t) for t in texts),
    )

    check("agent 声明表含 raid", bool(si.declared_unreachable("raid")),
          f"{sorted(si.UNREACHABLE_FROM_MAIN_CITY)}")
    check("agent 声明表【不含】farm（#52：迷宫可达、可打）",
          si.declared_unreachable("farm") is None)
    check("声明宽限 grace_sec = 0（raid 一确认中立页即判定，不再等超时）",
          si._BATCH_NAV_TIMEOUT_BY_KIND == {"raid": 0.0},
          f"{si._BATCH_NAV_TIMEOUT_BY_KIND}")
    r = si.unreachable_skip_reason(type("I", (), {"kind": "raid", "dungeon": "战阵之宴", "difficulty": "-"})())
    check("raid 的跳过原因来自声明且点名「从主城不可达」", "从主城不可达" in (r or ""), f"{r!r}")

    check("hooks_45 声明探针（raid 声明 + farm 不声明 + 真机 OCR）绿",
          hooks_45.probe_raid_unreachable_declared() is True)

    raid = RAID.read_text(encoding="utf-8")
    farm = FARM.read_text(encoding="utf-8")
    check("raid.json 的 #45 声明段在场（不做导航 → 不可达 → 能力缺口）",
          "#45" in raid and "不做任何导航" in raid and "能力缺口" in raid)
    check("farm.json 不再把 farm 声明成「无法开打 / 不可打」能力缺口",
          "不可打" not in farm)

    # #52：farm 现在是「可达 + 可打」的现版本模型 —— 由 hooks_52 正向证明。
    check("hooks_52 的 farm 模型探针绿（按域选 + 元素次轴 + 的迷宫 + 元素丢字容错）",
          hooks_52.probe_maze_by_domain() is True)


# ---------------------------------------------------------------------------
# 2. 跳过不再依赖“超时”（声明驱动；不假记账；继续下一条）
# ---------------------------------------------------------------------------
def test_skip_without_timeout() -> None:
    print("\n== 2. 批量清单里 raid：一确认中立页即明确跳过（不等 45s） ==")
    check("hooks_45 跳过探针（含 45s 对照实验）绿",
          hooks_45.probe_raid_skip_without_timeout() is True)
    print("       复现：主城帧1 放行 -> 主城帧2【不做计时器回拨】即跳过 -> 继续下一条 special")
    print("       对照：把宽限改回 45s -> 帧2 不跳过（证明跳过由声明驱动，不是别的原因）")


# ---------------------------------------------------------------------------
# 3. 单目标行为不变
# ---------------------------------------------------------------------------
def test_single_target_unchanged() -> None:
    print("\n== 3. 单目标（清单为空，RaidEntry / FarmEntry）行为不变 ==")
    check("hooks_45 单目标探针绿（指挥官不介入、不跳过）",
          hooks_45.probe_raid_single_target_unchanged() is True)


# ---------------------------------------------------------------------------
# 4. 守卫 / 破坏实验
# ---------------------------------------------------------------------------
def test_guard_and_prove_red() -> None:
    print("\n== 4. 守卫 hooks_45 + prove-red（两处破坏各自变红） ==")
    check("声明齐备 探针绿", hooks_45.probe_raid_unreachable_declared() is True)
    check("一确认中立页即跳过 探针绿", hooks_45.probe_raid_skip_without_timeout() is True)
    check("单目标不变 探针绿", hooks_45.probe_raid_single_target_unchanged() is True)
    check("hooks_45.prove_red() 成立（两处破坏各自变红）", hooks_45.prove_red() is True)


# ---------------------------------------------------------------------------
# 5. 纯编辑不变量 + 其它票挂点不因本票变红
# ---------------------------------------------------------------------------
def _hook_probes(tickets):
    rows = []
    for hook_id, ticket, _what, probe in discover_hooks():
        if ticket in tickets:
            try:
                rows.append((hook_id, ticket, probe()))
            except Exception as exc:  # noqa: BLE001
                rows.append((hook_id, ticket, f"raised {exc!r}"))
    return rows


def test_pure_edit_invariants() -> None:
    print("\n== 5. 纯编辑：五条承重短语 + drift + #9 守卫 + 其它票挂点不因本票变红 ==")
    text = SD.read_text(encoding="utf-8")
    for phrase in PHRASES:
        check(f"短语「{phrase}」仍出现", text.count(phrase) >= 1, f"count={text.count(phrase)}")
    check("special_dungeon.json 带 #45 声明段", "#45" in text and "能力缺口" in text)
    check("drift.check_all() == []", drift.check_all(repo_root=REPO_ROOT) == [],
          f"{drift.check_all(repo_root=REPO_ROOT)}")

    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")

    rows = _hook_probes(KEEP_TICKETS)
    red = [(h, t, v) for h, t, v in rows if v is False]
    check(f"#18/#27/#29/#30/#35/#36/#37/#38/#39/#44 挂点不因本票变红（共 {len(rows)} 个）",
          red == [], f"red={red}")


def main() -> int:
    print("=" * 76)
    print("#45：战阵之宴(raid) 从主城不可达 ⇒ 配置层声明为能力缺口（#52 起 farm 走真导航/开打）")
    print("=" * 76)
    test_raid_declared_farm_not()
    test_skip_without_timeout()
    test_single_target_unchanged()
    test_guard_and_prove_red()
    test_pure_edit_invariants()
    print("\n" + "=" * 76)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
