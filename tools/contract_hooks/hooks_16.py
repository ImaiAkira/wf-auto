# -*- coding: utf-8 -*-
"""#16：``apply`` / ``strip`` 的挂点（已点亮）—— 写入幂等、撤销逐字节可逆。

seam：``scene.apply``（ADR-0001 的「注入」职责）。

★#10 返工后的契约变更（本文件随之改动）★
#16 原实现把整个 ``next`` 数组**重渲染**、并把原文编码进 ``orig=`` 标记 —— 那会丢掉数组里的
**承重注释**。返工后 ``apply`` 改为**纯行插入**（只把事件组引用作为新行插在第一个元素之前，
原数组一字节不动）、``strip`` 按内容删掉这些行、**没有 ``orig=`` 标记**。因此：
「apply 会把真实（已落地的）树写脏」这一条**不再成立** —— 真实树本身已是配置派生的**规范形**，
``apply`` 对它幂等（no-op）；写入 / 撤销由「``strip`` 去掉派生行 ⇒ ``apply`` 逐字节还原」来证明。

守卫 ``apply-strip-idempotent-reversible`` 在临时副本上断言：

1. **确有派生内容可撤**：``strip`` 之后 ``assets/**`` 与之前**不同**（不是空转）；
2. **可逆**：``apply`` 之后与 strip 前（规范形）**逐字节相同**；
3. **幂等**：连续 apply 两次，``assets/**`` **逐字节相同**（ADR-0001：重跑不假脏）；
4. **无漂移**：apply 后 ``scene.drift.check_all()`` 为空；
5. **内容忠实**：apply 后的每个流程节点候选集 == **打断型前缀 + 原文候选集[:-1] +
   兜底型后缀 + 原文末位**（#18 两类位置相反；「纯插入、原文不动」）。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：把 ``apply`` 改成**非幂等**
（每次多写一个字节）、或把 ``strip`` 改成**有损**（不还原），真实探针必须变红。
直接运行::

    python tools\\contract_hooks\\hooks_16.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

HOOK_ID = "apply-strip-idempotent-reversible"

_PIPELINE = "assets/resource/pipeline"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _temp_assets() -> Path:
    """真实 assets 的一个**临时副本**（interface.json + pipeline/），供 apply/strip 演练。"""
    root = Path(tempfile.mkdtemp(prefix="wf_hook16_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    shutil.copytree(REPO_ROOT / "assets" / "resource" / "pipeline", root / "assets" / "resource" / "pipeline")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(root)).replace("\\", "/")] = path.read_bytes()
    return files


def probe_apply_strip():
    """#16（#10 返工后）：strip 去掉派生内容、apply 逐字节还原、幂等、无漂移、纯插入。"""
    scene_on_path()
    import scene.apply as ap  # noqa: PLC0415
    import scene.drift as drift  # noqa: PLC0415
    import scene.events as ev  # noqa: PLC0415

    root = _temp_assets()
    try:
        before = _snapshot(root)
        pipeline_path = root / _PIPELINE / "special_dungeon.json"

        # (1) 真实树已是规范形 -> strip 确有派生内容可撤。
        stripped = ap.strip(root)
        if stripped == []:
            return False
        if _snapshot(root) == before:
            return False
        stripped_nodes = _load_jsonc(pipeline_path, drift)

        # (2) apply 逐字节还原到规范形。
        if ap.apply(root) == []:
            return False
        if _snapshot(root) != before:
            return False

        # (3) 幂等：再 apply 一次，逐字节相同。
        if ap.apply(root) != []:
            return False
        if _snapshot(root) != before:
            return False

        # (4) 规范形无漂移。
        if drift.check_all(repo_root=root) != []:
            return False

        # (5) 事件是【纯插入】且两类位置相反（#18）：每个流程节点 ==
        #     [打断型前缀] + 原文候选集[:-1] + [兜底型后缀] + 原文末位（原文不动）。
        applied_nodes = _load_jsonc(pipeline_path, drift)
        prefix = list(ev.interrupt_refs())
        suffix = list(ev.fallback_refs())
        own = {n for e in ev.EVENTS for n in e.nodes}
        for name, spec in applied_nodes.items():
            if name in own or not isinstance(spec, dict) or not spec.get("next"):
                continue
            body = stripped_nodes[name]["next"]
            expected = [*prefix, *body[:-1], *suffix, *body[-1:]] if body else [*prefix, *suffix]
            if spec["next"] != expected:
                return False
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _load_jsonc(path: Path, drift_module) -> dict:
    return drift_module._load_jsonc(Path(path))


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_16.py`）
# ---------------------------------------------------------------------------
def prove_red() -> bool:
    """把 apply 改成非幂等 / 把 strip 改成有损，守卫必须各自变红。不碰中央 prove-red 配方。"""
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    scene_on_path()
    import scene.apply as ap  # noqa: PLC0415

    real_apply, real_strip = ap.apply, ap.strip

    print("hooks_16 prove-red：把 apply 改成非幂等 / strip 改成有损，要求守卫变红")
    green = probe_apply_strip() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：apply 幂等、strip 逐字节可逆（绿）")
    if not green:
        return False

    # (a) 非幂等 apply：每次调用后多写一个字节 -> 两次 apply 不再字节相同。
    def non_idempotent_apply(repo_root, cfg=None, pipeline_files=None):
        real_apply(repo_root, cfg, pipeline_files=pipeline_files)
        iface = Path(repo_root) / ap.INTERFACE_REL
        iface.write_bytes(iface.read_bytes() + b"\n")
        return []

    ap.apply = non_idempotent_apply  # type: ignore[assignment]
    try:
        red_apply = probe_apply_strip() is False
    finally:
        ap.apply = real_apply  # type: ignore[assignment]

    # (b) 有损 strip：不还原任何东西 -> apply 后 strip 回不到 apply 前。
    ap.strip = lambda *a, **k: []  # type: ignore[assignment]
    try:
        red_strip = probe_apply_strip() is False
    finally:
        ap.strip = real_strip  # type: ignore[assignment]

    ok = green and red_apply and red_strip
    print(f"  [{'PASS' if red_apply else 'FAIL'}] 非幂等 apply -> 守卫变红")
    print(f"  [{'PASS' if red_strip else 'FAIL'}] 有损 strip -> 守卫变红")
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#16",
        "apply 幂等写真实 JSON、strip 逐字节可逆（选项块 + 事件注入）",
        probe_apply_strip,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
