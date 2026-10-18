# -*- coding: utf-8 -*-
"""离线单测：领主战类整族切到配置驱动（ticket #10）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_family_switch.py

覆盖 ticket #10 的验收标准：

  1. **无漂移**：真实产物 ``scene.drift.check_all() == []``（选项 / 页面判据 / 事件层 /
     页面锚定链四条）；
  2. **事件层节点定义在场**：``scene.events.EVENT_NODE_DEFS``（含归位 ``PubReturnHome``）
     都在 pipeline 里有定义、判据一致 —— 修复 #16「只写候选集不写定义」的悬空引用；
  3. **页面锚定链落地**：每个页面锚定节点的 ``next`` = 事件组 + 显式后继 + 枢纽兜底；
  4. **配置块真正生效**：``interface.json`` 的「打哪个副本」只剩一个有效块（手写案例已删）；
  5. **落盘机制幂等可逆**：apply 写事件层节点定义、strip 逐字节撤销；跑完全程真实
     ``assets/**`` 字节不变（只读断言）；
  6. **三条既有路径不被越界**：幻想连战 / 战阵之宴 / 迷宫的分派文件不在写入集合里，
     且 #9 的结构守卫在切换后仍绿。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_10.py``。
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
from scene.drift import CHAIN_HUB, CHAIN_SUCCESSORS  # noqa: E402
from scene.events import EVENT_NODE_DEFS, EVENTS, event_refs, interrupt_refs  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402

import hooks_10  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SD_REL = "assets/resource/pipeline/special_dungeon.json"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _temp_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_family_"))
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
# 1. 真实树：四条校验全绿
# ---------------------------------------------------------------------------
def test_real_tree_green() -> None:
    print("\n== 1. 真实产物：整族已切到配置驱动、check_all() == [] ==")
    msgs = drift.check_all()
    check("真实树无漂移", msgs == [], f"drift={msgs}")
    check("挂点 family-switch-landed 已点亮（probe=True）",
          hooks_10.probe_family_switch() is True)


# ---------------------------------------------------------------------------
# 2. 事件层节点定义在场
# ---------------------------------------------------------------------------
def test_event_defs_present() -> None:
    print("\n== 2. 事件层节点定义（含归位 PubReturnHome）写进了 pipeline ==")
    files = drift.load_pipelines(PIPELINE_DIR)
    for name, spec in EVENT_NODE_DEFS.items():
        node = next((d[name] for d in files.values()
                     if isinstance(d, dict) and name in d), None)
        check(f"节点 {name} 有定义且判据一致",
              isinstance(node, dict) and node.get("recognition") == spec.get("recognition"))
    refs = event_refs()
    check("归位引用出现在注入事件组里", f"[JumpBack]{ap.RETURN_HOME_NODE_NAME}" in refs)


# ---------------------------------------------------------------------------
# 3. 页面锚定链落地
# ---------------------------------------------------------------------------
def test_chain_landed() -> None:
    print("\n== 3. 页面锚定链：显式后继 + 枢纽兜底 ==")
    sd = drift.load_pipelines(PIPELINE_DIR)["special_dungeon.json"]
    ref_set = set(event_refs())
    for node, successors in CHAIN_SUCCESSORS.items():
        rest = [x for x in (sd.get(node, {}) or {}).get("next", []) if x not in ref_set]
        check(f"{node} 的显式后继 = {[*successors, CHAIN_HUB]}",
              rest == [*successors, CHAIN_HUB], f"实际={rest}")
    # 每个非事件层流程节点都以【打断型】事件组开头（#18：兜底型归位在后缀）。
    refs = list(interrupt_refs())
    own = {n for e in EVENTS for n in e.nodes}
    bad = [n for n, s in sd.items()
           if isinstance(s, dict) and s.get("next") and n not in own
           and s["next"][: len(refs)] != refs]
    check("每个流程节点候选集以打断型事件组开头（前缀在前）", bad == [], f"bad={bad}")


# ---------------------------------------------------------------------------
# 4. 配置块真正生效
# ---------------------------------------------------------------------------
def test_option_block_effective() -> None:
    print("\n== 4. 「打哪个副本」只剩一个有效块（手写案例已删、配置块生效） ==")
    text = INTERFACE.read_text(encoding="utf-8")
    check("interface 里「打哪个副本」键恰好出现一次", text.count('"打哪个副本": {') == 1,
          f"count={text.count(chr(34) + '打哪个副本' + chr(34) + ': {')}")
    check("option_drift 无漂移",
          drift.option_drift(LORD_BATTLE, INTERFACE) == [])


# ---------------------------------------------------------------------------
# 5. 落盘机制：幂等可逆 + 事件层节点定义可写可剥
# ---------------------------------------------------------------------------
def test_apply_round_trip() -> None:
    print("\n== 5. 真实树是规范形：strip 去派生行 ⇒ apply 逐字节还原；事件层节点定义可写可剥 ==")
    root = _temp_copy()
    try:
        before = _snapshot(root)
        stripped_paths = ap.strip(root)
        check("strip 去掉了 special_dungeon 的派生行", SD_REL in stripped_paths,
              f"stripped={stripped_paths}")
        check("strip 后字节与规范形不同", _snapshot(root) != before)
        check("apply 逐字节还原规范形", ap.apply(root) != [] and _snapshot(root) == before)
        check("再 apply 幂等", ap.apply(root) == [] and _snapshot(root) == before)
        check("规范形无漂移", drift.check_all(repo_root=root) == [])

        # 事件层节点定义：删掉 -> apply 写回 -> strip 剥掉。
        common = root / ap.EVENT_DEFS_REL
        stripped = ap._strip_event_defs_from_text(common.read_text(encoding="utf-8"))
        removed = hooks_10._remove_node_block(stripped, ap.RETURN_HOME_NODE_NAME)
        common.write_bytes(removed.encode("utf-8"))
        ap.apply(root)
        check("apply 把缺失的事件层节点定义写回",
              f'"{ap.RETURN_HOME_NODE_NAME}"' in common.read_text(encoding="utf-8"))
        ap.strip(root)
        check("strip 把事件层节点定义逐字节撤销",
              common.read_bytes().decode("utf-8") == removed)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6. 三条既有路径不被越界
# ---------------------------------------------------------------------------
def test_three_paths_untouched() -> None:
    print("\n== 6. 幻想 / 战阵 / 迷宫：分派文件不在写入集合、结构守卫仍绿 ==")
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
# 7. prove-red
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 7. prove-red：改坏真实产物 -> 守卫变红 ==")
    check("hooks_10.prove_red() 成立（四类破坏各自变红）",
          hooks_10.prove_red() is True)


# ---------------------------------------------------------------------------
# 8. 全程只读真实 assets/**
# ---------------------------------------------------------------------------
def test_real_assets_read_only() -> None:
    print("\n== 8. 全程只读真实 assets/**：字节不变 ==")
    watched = [INTERFACE, *sorted(PIPELINE_DIR.glob("*.json"))]
    before = {p: p.read_bytes() for p in watched}
    drift.check_all()
    hooks_10.probe_family_switch()
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
    print("离线单测：领主战类整族切到配置驱动（scene.drift / scene.apply / hooks_10）")
    print("=" * 70)
    test_real_tree_green()
    test_event_defs_present()
    test_chain_landed()
    test_option_block_effective()
    test_apply_round_trip()
    test_three_paths_untouched()
    test_prove_red()
    test_real_assets_read_only()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
