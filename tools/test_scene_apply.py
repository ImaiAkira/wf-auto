# -*- coding: utf-8 -*-
"""离线单测：``scene.apply`` —— 派生内容落地 + 幂等撤销（ticket #16 / #10 返工）。

#10 返工后 ``scene.apply`` 的契约变了（本文件随之更新）：

* **真实树本身已是配置派生的规范形**（#10 把切换落进了真实产物），因此对真实树 ``apply``
  是**幂等 no-op**；写入能力由「``strip`` 去掉派生内容 ⇒ ``apply`` 逐字节还原」证明；
* pipeline 的事件组注入是**纯行插入**（不重渲染数组、不动原文一个字节），故候选集 ==
  「事件组 + strip 后的候选集」；没有 ``orig=`` 标记。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_apply.py

覆盖：

  1. 三类派生内容都在真实产物里（选项块 / 事件组前缀 / 事件层节点定义）；
  2. **strip ⇒ apply 逐字节可逆** + apply 幂等；
  3. 规范形无漂移（``scene.drift.check_all()`` 空）；
  4. apply 是**纯插入**：每个流程节点候选集 == 事件组 + strip 后的候选集；
  5. strip 对已 strip 的树是空操作；
  6. 跑完全程真实 ``assets/**`` 字节不变（只读断言）。

所有写入都发生在 ``tempfile`` 副本上；真实 ``assets/**`` 只被**读**。挂点本体与 prove-red
在 ``tools/contract_hooks/hooks_16.py``。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import apply as ap  # noqa: E402
from scene import drift  # noqa: E402
from scene import events as ev  # noqa: E402
from scene import options as opt  # noqa: E402
from scene.lord_battle import LORD_BATTLE  # noqa: E402

import hooks_16  # noqa: E402

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
    root = Path(tempfile.mkdtemp(prefix="wf_apply_test_"))
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


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _nodes(root: Path) -> dict:
    return json.loads(drift._strip_jsonc(_read(root / SD_REL)))


# ---------------------------------------------------------------------------
# 1. 三类派生内容都在真实产物里
# ---------------------------------------------------------------------------
def test_derived_content_present() -> None:
    print("\n== 1. 真实产物里：选项块 / 事件组前缀 / 事件层节点定义 都在场 ==")
    iface = json.loads(drift._strip_jsonc(_read(INTERFACE)))
    block = iface.get("option", {}).get(opt.OPTION_NAME)
    check("interface 的「打哪个副本」== 配置派生块",
          block == opt.derive_option_block(LORD_BATTLE), f"block={block!r}"[:200])
    check("「打哪个副本」键恰好一次（手写块已删）",
          _read(INTERFACE).count('"打哪个副本": {') == 1)

    common = _read(PIPELINE_DIR / "common.json")
    check(f"common.json 有事件层节点定义 {ap.RETURN_HOME_NODE_NAME}",
          f'"{ap.RETURN_HOME_NODE_NAME}"' in common)

    nodes = json.loads(drift._strip_jsonc(_read(PIPELINE_DIR / "special_dungeon.json")))
    refs = list(ev.interrupt_refs())
    own = {n for e in ev.EVENTS for n in e.nodes}
    bad = [n for n, s in nodes.items()
           if isinstance(s, dict) and s.get("next") and n not in own
           and s["next"][: len(refs)] != refs]
    check("每个流程节点候选集以打断型事件组开头", bad == [], f"bad={bad[:3]}")


# ---------------------------------------------------------------------------
# 2 + 3. strip ⇒ apply 逐字节可逆、幂等、无漂移
# ---------------------------------------------------------------------------
def test_strip_then_apply_reversible() -> None:
    print("\n== 2. strip 去掉派生内容 ⇒ apply 逐字节还原；apply 幂等 ==")
    root = _temp_copy()
    try:
        before = _snapshot(root)
        stripped = ap.strip(root)
        check("strip 确有派生内容可撤", stripped != [], f"stripped={stripped}")
        check("strip 后字节与规范形不同", _snapshot(root) != before)
        check("apply 逐字节还原规范形", ap.apply(root) != [] and _snapshot(root) == before)
        check("再 apply 幂等（报告空 + 字节不变）",
              ap.apply(root) == [] and _snapshot(root) == before)
        check("规范形无漂移", drift.check_all(repo_root=root) == [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. apply 是纯插入：候选集 == 事件组 + strip 后的候选集
# ---------------------------------------------------------------------------
def test_pure_insertion() -> None:
    print("\n== 4. apply 是纯插入：候选集 == 事件组 + strip 后的候选集（原文不动） ==")
    root = _temp_copy()
    try:
        ap.strip(root)
        stripped_nodes = _nodes(root)
        ap.apply(root)
        applied_nodes = _nodes(root)
        prefix = list(ev.interrupt_refs())
        suffix = list(ev.fallback_refs())
        own = {n for e in ev.EVENTS for n in e.nodes}
        mism = []
        for n, s in applied_nodes.items():
            if n in own or not isinstance(s, dict) or not s.get("next"):
                continue
            body = stripped_nodes[n]["next"]
            expected = [*prefix, *body[:-1], *suffix, *body[-1:]] if body else [*prefix, *suffix]
            if s["next"] != expected:
                mism.append(n)
        check("每个流程节点 == 打断型前缀 + 原文[:-1] + 兜底型后缀 + 原文末位",
              mism == [], f"mismatch={mism[:3]}")
        check("apply 不变节点集合", set(applied_nodes) == set(stripped_nodes))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. strip 对已 strip 的树是空操作
# ---------------------------------------------------------------------------
def test_strip_idempotent() -> None:
    print("\n== 5. strip 对已 strip 的树是空操作 ==")
    root = _temp_copy()
    try:
        ap.strip(root)
        once = _snapshot(root)
        check("第二次 strip 无改动", ap.strip(root) == [])
        check("字节不变", _snapshot(root) == once)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6. 挂点已点亮
# ---------------------------------------------------------------------------
def test_hook_reports_pass() -> None:
    print("\n== 6. 挂点 #16 已点亮（probe=True），且本模块自带的破坏实验成立 ==")
    check("probe_apply_strip() 返回 True", hooks_16.probe_apply_strip() is True)
    check("prove_red() 成立：非幂等 apply / 有损 strip -> 守卫变红",
          hooks_16.prove_red() is True)


# ---------------------------------------------------------------------------
# 7. 全程真实 assets/** 只读
# ---------------------------------------------------------------------------
def test_real_assets_untouched() -> None:
    print("\n== 7. 全程只读真实 assets/**：字节不变 ==")
    watched = [INTERFACE, *sorted(PIPELINE_DIR.glob("*.json"))]
    before = {p: p.read_bytes() for p in watched}
    root = _temp_copy()
    try:
        ap.strip(root)
        ap.apply(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    hooks_16.probe_apply_strip()
    hooks_16.prove_red()
    after = {p: p.read_bytes() for p in watched}
    changed = [p.name for p in watched if before[p] != after[p]]
    check("真实 assets/** 字节未变", changed == [], f"changed={changed}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：apply / strip —— 派生内容落地 + 幂等撤销（scene.apply / hooks_16）")
    print("=" * 70)
    test_derived_content_present()
    test_strip_then_apply_reversible()
    test_pure_insertion()
    test_strip_idempotent()
    test_hook_reports_pass()
    test_real_assets_untouched()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
