# -*- coding: utf-8 -*-
"""#10：领主战类整族切到配置驱动的挂点（已点亮）。

seam：真实产物 ``assets/**`` + ``scene.apply`` + ``scene.drift``（ADR-0001 的
「注入 + 校验」两条职责在**整族**尺度上的落地）。

守卫 ``family-switch-landed`` 断言领主战类整族（39 个成员）已切到配置驱动，且落地物
真的在 pipeline 里：

1. **无漂移**：``scene.drift.check_all(repo_root=真实树) == []`` —— 选项块 / 页面判据 /
   事件层 / 页面锚定链四条都对得上；
2. **事件层节点定义在场**：``scene.events.EVENT_NODE_DEFS`` 声明的节点（含归位
   ``PubReturnHome``）都在 pipeline 里有定义、判据一致（#16 只写候选集不写定义，注入的
   ``[JumpBack]PubReturnHome`` 会**悬空** —— 这是 #10 的前置实测坑）；
3. **页面锚定链落地**：每个页面锚定节点的候选集 = 事件组 + ``CHAIN_SUCCESSORS[node]`` +
   枢纽兜底 ``SpecialEntry``；
4. **配置块真正生效**：``interface.json`` 里「打哪个副本」只剩**一个**有效块（手写块已删），
   且它就是配置派生的（``json.loads`` 不再被手写块覆盖）；
5. **落盘机制仍幂等可逆**：在临时副本上 apply 能把事件层节点定义写进去、strip 能逐字节撤销。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：逐一改坏真实产物，
守卫必须各自变红：

* 从生成块里**删一个成员** -> 选项漂移；
* 改**事件层节点定义**的判据 -> 事件节点漂移；
* 改**某个页面锚定节点的显式后继** -> 链漂移；
* 从流程节点候选集里**摘掉归位引用** -> 事件注入漂移。

直接运行::

    python tools\\contract_hooks\\hooks_10.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

HOOK_ID = "family-switch-landed"

_PIPELINE = "assets/resource/pipeline"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _copy_assets_temp() -> Path:
    """真实 assets 的一个临时副本（interface.json + pipeline/），供漂移/落盘演练。"""
    root = Path(tempfile.mkdtemp(prefix="wf_hook10_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    shutil.copytree(
        REPO_ROOT / "assets" / "resource" / "pipeline",
        root / "assets" / "resource" / "pipeline",
    )
    return root


def probe_family_switch() -> bool:
    """#10：整族已切到配置驱动，四条落地物都在场且无漂移；落盘机制幂等可逆。"""
    scene_on_path()
    import scene.apply as ap  # noqa: PLC0415
    import scene.drift as drift  # noqa: PLC0415
    from scene.drift import CHAIN_HUB, CHAIN_SUCCESSORS  # noqa: PLC0415
    from scene.events import (  # noqa: PLC0415
        EVENT_NODE_DEFS,
        EVENTS,
        event_refs,
        interrupt_refs,
    )

    # (1) 无漂移（四条校验的汇总）。
    if drift.check_all(repo_root=REPO_ROOT) != []:
        return False

    files = drift.load_pipelines(REPO_ROOT / _PIPELINE)

    def resolve(name: str):
        for data in files.values():
            if isinstance(data, dict) and name in data:
                return data[name]
        return None

    # (2) 事件层节点定义在场、判据一致。
    for name, spec in EVENT_NODE_DEFS.items():
        node = resolve(name)
        if not isinstance(node, dict):
            return False
        if node.get("recognition") != spec.get("recognition"):
            return False

    # (3) 页面锚定链落地：显式后继 + 枢纽兜底。
    sd = files.get("special_dungeon.json")
    if not isinstance(sd, dict):
        return False
    ref_set = set(event_refs())
    for node, successors in CHAIN_SUCCESSORS.items():
        spec = sd.get(node)
        if not isinstance(spec, dict) or not isinstance(spec.get("next"), list):
            return False
        rest = [x for x in spec["next"] if x not in ref_set]
        if rest != [*successors, CHAIN_HUB]:
            return False

    # (3b) 每个非事件层流程节点的候选集以【打断型】事件组开头（#18：兜底型在后缀）。
    refs = list(interrupt_refs())
    own = {n for e in EVENTS for n in e.nodes}
    for name, spec in sd.items():
        if not isinstance(spec, dict) or not spec.get("next") or name in own:
            continue
        if spec["next"][: len(refs)] != refs:
            return False

    # (4) 配置块真正生效：只剩一个有效块。
    iface = (REPO_ROOT / "assets" / "interface.json").read_text(encoding="utf-8")
    if iface.count('"打哪个副本": {') != 1:
        return False

    # (5) 落盘机制：事件层节点定义能写进去、能逐字节撤销。
    root = _copy_assets_temp()
    try:
        common = root / _PIPELINE / "common.json"
        text = common.read_text(encoding="utf-8")
        # 先剥掉（若无生成区则不动），再把定义删掉 -> apply 必须把它写回来。
        stripped = ap._strip_event_defs_from_text(text)
        needle = f'"{ap.RETURN_HOME_NODE_NAME}": {{'
        if needle not in stripped:
            return False
        removed = _remove_node_block(stripped, ap.RETURN_HOME_NODE_NAME)
        common.write_bytes(removed.encode("utf-8"))
        if ap.apply(root) == []:
            return False
        if f'"{ap.RETURN_HOME_NODE_NAME}"' not in common.read_text(encoding="utf-8"):
            return False
        if ap.strip(root) == []:
            return False
        if common.read_bytes().decode("utf-8") != removed:
            return False
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _remove_node_block(text: str, name: str) -> str:
    """删掉一份干净的（无标记）``"name": { ... },`` 定义块（prove-red 用）。"""
    tok = f'"{name}": {{'
    i = text.find(tok)
    if i == -1:
        raise RuntimeError(f"找不到节点定义 {name!r}（守卫已与实现脱节）")
    lb = text.find("{", i)
    rb = _match_brace(text, lb)
    line_start = text.rfind("\n", 0, i) + 1
    after = rb + 1
    if after < len(text) and text[after] == ",":
        after += 1
    return text[:line_start] + text[after:]


def _match_brace(text: str, lb: int) -> int:
    depth = 0
    i = lb
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            i = j + 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_10.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _drift_in_temp(label: str, mutate) -> bool:
    """复制真实 assets -> 施加一处破坏 -> check_all(临时根) 必须变红。"""
    root = _copy_assets_temp()
    try:
        mutate(root)
        msgs = drift_check_all_in(root)
        red = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}{tail}")
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


def drift_check_all_in(root: Path) -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    return drift.check_all(repo_root=root)


def _break_drop_member(root: Path) -> None:
    """从配置派生的选项块里删一个成员（模拟手改生成区 / 漏成员）。"""
    iface = root / "assets" / "interface.json"
    text = iface.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out = [ln for ln in lines if '"name": "猩红巨熊讨伐"' not in ln]
    iface.write_text("".join(out), encoding="utf-8")


def _break_event_def(root: Path) -> None:
    """改事件层节点定义（归位）的判据 —— #18 起归位是 And(...)，改它的 box_index 即判据漂移。

    注：子识别串（^返回$）的漂移由 #18 的自匹配守卫 ``hooks_18`` 负责抓（它会在真机帧 OCR
    上求值）；本步只验 ``event_def_drift`` 对归位节点 recognition 本身的漂移敏感。
    """
    _sub(
        root / _PIPELINE / "common.json",
        '"box_index": 0',
        '"box_index": 1',
    )


def _break_chain(root: Path) -> None:
    """改某个页面锚定节点的显式后继（SpecialEnterBoss 不再走向详情页）。

    #18 起该节点候选集结尾是 ``…SpecialFightTargetRow, [JumpBack]PubReturnHome, SpecialEntry``。
    """
    _sub(
        root / _PIPELINE / "special_dungeon.json",
        '            "SpecialFightTargetRow",\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialScrollList"',
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialScrollList"',
    )


def _break_event_injection(root: Path) -> None:
    """从某个流程节点候选集里摘掉归位引用。"""
    _sub(
        root / _PIPELINE / "special_dungeon.json",
        '            "[JumpBack]PubReturnHome",\n            "SpecialEntry"',
        '            "SpecialEntry"',
    )


def prove_red() -> bool:
    """本票自带的破坏实验：真实树绿、四种破坏各自变红。不碰中央 prove-red 配方。"""
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    print("hooks_10 prove-red：逐一改坏真实产物，要求 family-switch-landed 变红")
    green = drift.check_all(repo_root=REPO_ROOT) == []
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：整族已切到配置驱动、无漂移（绿）")
    if not green:
        return False

    checks = [
        _drift_in_temp("改坏 ①：从生成块删一个成员", _break_drop_member),
        _drift_in_temp("改坏 ②：改事件层节点定义（归位 ROI）", _break_event_def),
        _drift_in_temp("改坏 ③：改页面锚定节点的显式后继", _break_chain),
        _drift_in_temp("改坏 ④：摘掉候选集里的归位引用", _break_event_injection),
    ]
    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#10",
        "领主战类整族切到配置驱动：选项块 / 事件层 / 页面锚定链都在 pipeline 落地且无漂移",
        probe_family_switch,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
