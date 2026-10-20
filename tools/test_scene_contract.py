# -*- coding: utf-8 -*-
"""离线单测：领主战族「遗留手写接线」收尾（ticket #12）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_contract.py

覆盖 ticket #12（重新界定后）的验收标准 —— **只**清领主战族的遗留手写接线，不删枢纽
``SpecialEntry``（它仍是恢复边，幻想 / 战阵 / 迷宫三条既有路径靠它分派）：

  1. **整族无漂移**：真实产物 ``scene.drift.check_all() == []``（选项 / 页面判据 / 事件层 /
     页面锚定链四条）；
  2. **无重复候选**：``SpecialEntry.next`` / ``PhantomDispatch.next`` 里每个引用只出现一次
     （#10 残留的旧手写 ``[JumpBack]`` 副本已收敛）；
  3. **强注入校验**：``event_injection_drift`` 收紧回强形式 —— 事件组只作前缀、其后零事件
     引用；「中间塞一个额外事件引用」必红（prove-red）；
  4. **选项块唯一且配置派生**：``interface.json`` 的「打哪个副本」只剩一个块且 == 配置派生；
  5. **无被链取代的旧后继**：非链、非事件、非枢纽流程节点候选集剥掉事件组后只剩枢纽；
  6. **承重注释仍在**：``special_dungeon.json`` 里五条特征短语各 ≥1（纯编辑不丢注释）；
  7. **三条既有路径不被越界**：幻想 / 战阵 / 迷宫的分派文件不在写入集合里，且 #9 结构守卫
     在切换后仍绿（``tools/test_scene_unchanged.py`` 一行未改）；
  8. **落盘机制仍幂等可逆**：strip ⇒ apply 逐字节还原；跑完全程真实 ``assets/**`` 字节不变。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_12.py``。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import apply as ap  # noqa: E402
from scene import drift  # noqa: E402
from scene import options as opt  # noqa: E402
from scene.events import EVENTS, event_refs, fallback_refs, interrupt_refs  # noqa: E402

import hooks_12  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SD = PIPELINE_DIR / "special_dungeon.json"
SD_REL = "assets/resource/pipeline/special_dungeon.json"

# #12 的承重注释硬规则：纯编辑，绝不丢这些短语。
PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _temp_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_contract_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(INTERFACE, root / "assets" / "interface.json")
    shutil.copytree(PIPELINE_DIR, root / "assets" / "resource" / "pipeline")
    return root


def _snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# 1. 真实树：无漂移 + 挂点点亮
# ---------------------------------------------------------------------------
def test_real_tree_green() -> None:
    print("\n== 1. 真实产物：领主战族遗留接线已收敛、check_all() == [] ==")
    msgs = drift.check_all()
    check("真实树无漂移", msgs == [], f"drift={msgs}")
    check("挂点 lord-family-no-leftover-wiring 已点亮（probe=True）",
          hooks_12.probe_lord_contract() is True)


# ---------------------------------------------------------------------------
# 2. 无重复候选
# ---------------------------------------------------------------------------
def test_no_duplicate_candidates() -> None:
    print("\n== 2. 枢纽候选集无重复（事件组在前，旧手写副本已删） ==")
    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    for hub in ("SpecialEntry", "PhantomDispatch"):
        nxt = (sd.get(hub) or {}).get("next") or []
        seen: dict = {}
        for x in nxt:
            seen[x] = seen.get(x, 0) + 1
        dups = {k: v for k, v in seen.items() if v > 1}
        check(f"{hub}.next 每个引用只出现一次", dups == {}, f"dups={dups}")
    # 打断型事件组仍是前缀；兜底型归位是后缀（#18：末位恢复边之前）。
    refs = list(interrupt_refs())
    suffix = list(fallback_refs())
    for hub in ("SpecialEntry", "PhantomDispatch"):
        nxt = (sd.get(hub) or {}).get("next") or []
        check(f"{hub}.next 以打断型事件组开头", nxt[: len(refs)] == refs)
        rest = nxt[len(refs):]
        check(f"{hub}.next 的兜底型后缀在末位恢复边之前",
              bool(rest) and rest[-len(suffix) - 1 : -1] == suffix)


# ---------------------------------------------------------------------------
# 3. 强注入校验
# ---------------------------------------------------------------------------
def test_strong_injection() -> None:
    print("\n== 3. event_injection_drift 是强形式：事件组只作前缀、其后零事件引用 ==")
    check("event_injection_drift(真实树) == []",
          drift.event_injection_drift(REPO_ROOT) == [])
    ref_set = set(event_refs())
    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    own = {n for e in EVENTS for n in e.nodes}
    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    stray = []
    for name, spec in sd.items():
        if not isinstance(spec, dict) or not spec.get("next") or name in own:
            continue
        nxt = spec["next"]
        if nxt[: len(prefix)] != prefix:
            continue
        rest = nxt[len(prefix):]
        if not rest or rest[-1] in ref_set:
            stray.append(name)
            continue
        mid = rest[:-1]
        body = mid[: -len(suffix)] if suffix and mid[-len(suffix):] == suffix else mid
        if [x for x in body if x in ref_set]:
            stray.append(name)
    check("没有任何流程节点在事件组之后再混事件引用", stray == [], f"stray={stray}")


# ---------------------------------------------------------------------------
# 4. 选项块唯一且配置派生
# ---------------------------------------------------------------------------
def test_option_block_unique_and_derived() -> None:
    print("\n== 4. 「打哪个副本」只剩一个块，且 == 配置派生 ==")
    from scene.lord_battle import LORD_BATTLE

    text = INTERFACE.read_text(encoding="utf-8")
    check("interface 里「打哪个副本」键恰好出现一次", text.count('"打哪个副本": {') == 1)
    iface = drift._load_jsonc(INTERFACE)
    block = (iface.get("option") or {}).get(opt.OPTION_NAME)
    check("「打哪个副本」== 配置派生块", block == opt.derive_option_block(LORD_BATTLE),
          f"block={block!r}"[:200])


# ---------------------------------------------------------------------------
# 5. 无被链取代的旧后继
# ---------------------------------------------------------------------------
def test_no_superseded_successors() -> None:
    print("\n== 5. 非链 / 非事件 / 非枢纽节点：候选集剥掉事件组后只剩枢纽 ==")
    from scene.drift import CHAIN_HUB, CHAIN_SUCCESSORS

    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    ref_set = set(event_refs())
    own = {n for e in EVENTS for n in e.nodes}
    skip = {"SpecialEntry", "PhantomDispatch", "SpecialStallRecover", "SpecialBatchPlan"} \
        | set(CHAIN_SUCCESSORS) | own
    bad = {}
    for name, spec in sd.items():
        if name in skip or not isinstance(spec, dict):
            continue
        nxt = spec.get("next")
        if not isinstance(nxt, list) or not nxt:
            continue
        rest = [x for x in nxt if x not in ref_set]
        if rest != [CHAIN_HUB]:
            bad[name] = rest
    check("无被链取代的旧后继残留", bad == {}, f"bad={bad}")
    check("chain_drift(真实树) == []", drift.chain_drift(REPO_ROOT) == [])


# ---------------------------------------------------------------------------
# 6. 承重注释仍在（纯编辑硬规则）
# ---------------------------------------------------------------------------
def test_load_bearing_comments() -> None:
    print("\n== 6. 承重注释短语仍各 ≥1（纯编辑，绝不丢注释） ==")
    text = SD.read_text(encoding="utf-8")
    for phrase in PHRASES:
        check(f"短语「{phrase}」仍出现", text.count(phrase) >= 1, f"count={text.count(phrase)}")


# ---------------------------------------------------------------------------
# 7. 三条既有路径不被越界 + #9 守卫未改且仍绿
# ---------------------------------------------------------------------------
def test_three_paths_untouched() -> None:
    print("\n== 7. 幻想 / 战阵 / 迷宫：分派文件不在写入集合、#9 守卫仍绿 ==")
    check("apply 默认只写 special_dungeon.json 的候选集",
          ap.PIPELINE_FILES == ("special_dungeon.json",), f"{ap.PIPELINE_FILES}")
    root = _temp_copy()
    try:
        watched = [root / "assets/resource/pipeline" / n
                   for n in ("farm.json", "raid.json", "phantom.json")]
        before = {p: p.read_bytes() for p in watched}
        ap.apply(root)
        changed = [p.name for p in watched if before[p] != p.read_bytes()]
        check("apply 不改分派文件 farm/raid/phantom", changed == [], f"changed={changed}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        fails = tsu.run_guards()
        check("#9 三条既有路径结构守卫仍绿", fails == [], f"fails={fails[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


# ---------------------------------------------------------------------------
# 8. 落盘机制仍幂等可逆
# ---------------------------------------------------------------------------
def test_apply_round_trip() -> None:
    print("\n== 8. 落盘机制仍幂等可逆：strip ⇒ apply 逐字节还原 ==")
    root = _temp_copy()
    try:
        before = _snapshot(root)
        stripped = ap.strip(root)
        check("strip 确有派生内容可撤", stripped != [] and SD_REL in stripped, f"stripped={stripped}")
        check("apply 逐字节还原规范形", ap.apply(root) != [] and _snapshot(root) == before)
        check("再 apply 幂等", ap.apply(root) == [] and _snapshot(root) == before)
        check("规范形无漂移", drift.check_all(repo_root=root) == [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 9. prove-red
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 9. prove-red：改坏真实产物副本 -> 守卫变红（含「中间塞事件引用」） ==")
    check("hooks_12.prove_red() 成立（四类破坏各自变红）",
          hooks_12.prove_red() is True)


# ---------------------------------------------------------------------------
# 10. 全程只读真实 assets/**
# ---------------------------------------------------------------------------
def test_real_assets_read_only() -> None:
    print("\n== 10. 全程只读真实 assets/**：字节不变 ==")
    watched = [INTERFACE, *sorted(PIPELINE_DIR.glob("*.json"))]
    before = {p: p.read_bytes() for p in watched}
    drift.check_all()
    hooks_12.probe_lord_contract()
    root = _temp_copy()
    try:
        ap.apply(root)
        ap.strip(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    after = {p: p.read_bytes() for p in watched}
    changed = [p.name for p in watched if before[p] != after[p]]
    check("真实 assets/** 字节未变", changed == [], f"changed={changed}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：领主战族遗留手写接线收尾（scene.drift / scene.apply / hooks_12）")
    print("=" * 70)
    test_real_tree_green()
    test_no_duplicate_candidates()
    test_strong_injection()
    test_option_block_unique_and_derived()
    test_no_superseded_successors()
    test_load_bearing_comments()
    test_three_paths_untouched()
    test_apply_round_trip()
    test_prove_red()
    test_real_assets_read_only()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
