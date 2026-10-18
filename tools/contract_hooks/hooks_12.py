# -*- coding: utf-8 -*-
"""#12：领主战类「遗留手写接线」收尾的挂点（已点亮）。

seam：``assets/resource/pipeline/special_dungeon.json`` + ``assets/interface.json``
+ ``scene.drift``（ADR-0001 的「注入 / 校验」在**领主战族**尺度上的收尾）。

#10 把领主战类整族切到配置驱动后，留下两处**残余手写接线**（#12 收尾）：

1. ``SpecialEntry.next`` / ``PhantomDispatch.next`` 里**事件组（前缀）与旧手写副本并存**
   —— 同一个 ``[JumpBack]`` 引用出现两次（死候选）；
2. 为容忍这些重复，``scene.drift.event_injection_drift`` 被弱化成「只查前缀」。

★范围（重新界定后的 #12）★ **不**删枢纽 ``SpecialEntry``（它仍是恢复边，且幻想 / 战阵 /
迷宫三条既有路径靠它分派，见 ADR-0002 与 #9 守卫）；本票只清掉**领主战族的遗留手写接线**。

守卫 ``lord-family-no-leftover-wiring`` 断言收尾后的**收敛状态**：

1. **无重复候选**：``SpecialEntry.next`` / ``PhantomDispatch.next`` 里每个引用只出现一次；
2. **强注入校验**：``event_injection_drift`` 是强形式（#18 起分两类）—— 每个流程节点 =
   打断型**前缀** + 原有后继 + 兜底型**后缀**（末位恢复边之前），其余位置**零**事件引用；
   「中间塞一个额外事件引用」能让它变红（见本文件 prove-red）；
3. **选项块唯一且配置派生**：``interface.json`` 里「打哪个副本」只剩**一个**块，且它 == 配置派生；
4. **无被链取代的旧后继**：非链、非事件、非枢纽的流程节点候选集剥掉事件组后只剩枢纽
   ``SpecialEntry``（页面锚定节点由 ``scene.drift.chain_drift`` 把守）；
5. **整族无漂移**：``scene.drift.check_all(repo_root=真实树) == []``。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：逐一改坏真实产物的副本，
上面每条守卫必须各自变红 —— 含 **「往候选集中间塞一个额外事件引用」** 这个 #12 专门要求的情形。

直接运行::

    python tools\\contract_hooks\\hooks_12.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

HOOK_ID = "lord-family-no-leftover-wiring"

_PIPELINE = "assets/resource/pipeline"
_INTERFACE = "assets/interface.json"

# 枢纽 / 入口分派节点：它们的候选集**故意**不是「事件组 + SpecialEntry」形（枢纽要列业务
# 节点做恢复分派；PhantomDispatch 要走幻想状态机链），故 check(4) 跳过它们。
_HUBS = ("SpecialEntry", "PhantomDispatch")
# 其它带自洽 next 的入口/看门狗节点（非页面锚定链的一部分，剥掉事件组后回枢纽即可）。
_NON_CHAIN_HUBS = ("SpecialStallRecover", "SpecialBatchPlan")


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 契约检查（对任意 ``root``：含 assets/interface.json + assets/resource/pipeline/）
# ---------------------------------------------------------------------------
def _failures(root: Path, cfg=None) -> list[str]:
    """在 ``root`` 上跑领主战族收尾契约；返回失败信息列表（空 = 绿）。"""
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415
    import scene.options as opt  # noqa: PLC0415
    from scene.drift import CHAIN_FILE, CHAIN_HUB, CHAIN_SUCCESSORS  # noqa: PLC0415
    from scene.events import (  # noqa: PLC0415
        EVENTS,
        event_refs,
        fallback_refs,
        interrupt_refs,
    )
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

    if cfg is None:
        cfg = LORD_BATTLE

    fails: list[str] = []

    # (0) 整族无漂移（选项 / 页面判据 / 事件层 / 页面锚定链四条）。
    fails += drift.check_all(repo_root=root, cfg=cfg)

    files = drift.load_pipelines(Path(root) / _PIPELINE)
    sd = files.get(CHAIN_FILE)
    if not isinstance(sd, dict):
        fails.append(f"找不到 {CHAIN_FILE}（无法校验领主战族收尾契约）")
        return fails

    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    ref_set = set(event_refs())
    own = {n for e in EVENTS for n in e.nodes}

    # (1) 无重复候选：枢纽里每个引用只出现一次（事件组在前，旧手写副本已删）。
    for hub in _HUBS:
        nxt = (sd.get(hub) or {}).get("next")
        if not isinstance(nxt, list):
            fails.append(f"{hub} 没有 next 候选集")
            continue
        seen: dict = {}
        for x in nxt:
            seen[x] = seen.get(x, 0) + 1
        dups = {k: v for k, v in seen.items() if v > 1}
        if dups:
            fails.append(f"{CHAIN_FILE}::{hub}.next 仍有重复候选 {dups}（应各只一份、事件组在前）")

    # (2) 两类位置（#18）：打断型前缀 + 兜底型后缀（末位终点之前），其余零事件引用。
    for name, spec in sd.items():
        if not isinstance(spec, dict) or not spec.get("next") or name in own:
            continue
        nxt = spec["next"]
        if nxt[: len(prefix)] != prefix:
            fails.append(f"{CHAIN_FILE}::{name}.next 没有以打断型事件组开头")
            continue
        rest = nxt[len(prefix):]
        if not rest or rest[-1] in ref_set:
            fails.append(f"{CHAIN_FILE}::{name}.next 末位是事件引用（应是恢复边 / 终点）")
            continue
        mid = rest[:-1]
        if suffix:
            if len(mid) < len(suffix) or mid[-len(suffix):] != suffix:
                fails.append(
                    f"{CHAIN_FILE}::{name}.next 的兜底型事件 {suffix} 不在后缀位置"
                    f"（应在最后一个原有后继之前）"
                )
                continue
            body = mid[: -len(suffix)]
        else:
            body = mid
        extra = [x for x in body if x in ref_set]
        if extra:
            fails.append(
                f"{CHAIN_FILE}::{name}.next 的事件组之后又混入事件引用 {extra}"
                f"（事件引用只应作为前缀 + 末位前后缀各出现一次）"
            )

    # (3) 选项块唯一，且 == 配置派生（「只剩配置生成的那一份」）。
    iface_path = Path(root) / _INTERFACE
    iface_text = iface_path.read_text(encoding="utf-8")
    if iface_text.count('"打哪个副本": {') != 1:
        fails.append(
            f"{_INTERFACE} 的「打哪个副本」不是恰好一个块"
            f"（count={iface_text.count(chr(34) + '打哪个副本' + chr(34) + ': {')}）"
        )
    try:
        data = drift._load_jsonc(iface_path)
        block = (data.get("option") or {}).get(opt.OPTION_NAME)
        if block != opt.derive_option_block(cfg):
            fails.append(f"{_INTERFACE} 的「打哪个副本」!= 配置派生块")
    except Exception as exc:  # noqa: BLE001 -- 坏 JSON 必须变红，不静默
        fails.append(f"读 {_INTERFACE} 失败：{exc!r}")

    # (4) 无被页面锚定链取代的旧后继：非链 / 非事件 / 非枢纽节点 = 事件组 + 枢纽兜底。
    skip = set(_HUBS) | set(_NON_CHAIN_HUBS) | set(CHAIN_SUCCESSORS) | own
    for name, spec in sd.items():
        if name in skip or not isinstance(spec, dict):
            continue
        nxt = spec.get("next")
        if not isinstance(nxt, list) or not nxt:
            continue
        rest = [x for x in nxt if x not in ref_set]
        if rest != [CHAIN_HUB]:
            fails.append(
                f"{CHAIN_FILE}::{name}.next 剥掉事件组后应为 ['{CHAIN_HUB}']，实际 {rest}"
            )
    return fails


def probe_lord_contract() -> bool:
    """#12：领主战族的遗留手写接线已收敛、整族无漂移。"""
    return _failures(REPO_ROOT) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_12.py`）
# ---------------------------------------------------------------------------
def _copy_assets_temp() -> Path:
    """真实 assets 的一个临时副本（interface.json + pipeline/）。"""
    root = Path(tempfile.mkdtemp(prefix="wf_hook12_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / _INTERFACE, root / _INTERFACE)
    shutil.copytree(REPO_ROOT / _PIPELINE, root / _PIPELINE)
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_midlist_event_ref(root: Path) -> None:
    """★#12 专门要求★：往某个流程节点候选集的**中间**塞一个事件引用（#18：塞在兜底后缀之前）。"""
    _sub(
        root / _PIPELINE / "special_dungeon.json",
        '            "SpecialBonusNo",\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialModeMulti": {',
        '            "SpecialBonusNo",\n'
        '            "[JumpBack]PubLoadingWait",\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialModeMulti": {',
    )


def _break_duplicate_candidate(root: Path) -> None:
    """往枢纽候选集里塞一个**重复**的业务候选（旧手写副本残留）。

    #18 起 SpecialEntry.next 结尾是 ``…SpecialBattleWait, [JumpBack]PubReturnHome, SpecialWait``。
    """
    _sub(
        root / _PIPELINE / "special_dungeon.json",
        '            "SpecialBattleWait",\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialWait"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialStallRecover": {',
        '            "SpecialBattleWait",\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialWait",\n'
        '            "SpecialWait"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialStallRecover": {',
    )


def _break_second_option_block(root: Path) -> None:
    """在 option 映射里再塞一个「打哪个副本」块（手写残留 / 双份）。"""
    _sub(
        root / _INTERFACE,
        '    "option": {\n        "抽哪个池": {',
        '    "option": {\n'
        '        "打哪个副本": {"type": "select", "default_case": "猩红巨熊讨伐", "cases": []},\n'
        '        "抽哪个池": {',
    )


def _break_old_successor(root: Path) -> None:
    """给一个非链节点塞一个被链取代的旧后继。"""
    _sub(
        root / _PIPELINE / "special_dungeon.json",
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialPartyText": {',
        '            "[JumpBack]PubReturnHome",\n'
        '            "SpecialChallenge",\n'
        '            "SpecialEntry"\n'
        '        ]\n'
        '    },\n'
        '    "SpecialPartyText": {',
    )


def _fail_in(label: str, mutate) -> bool:
    """复制真实 assets -> 施加一处破坏 -> ``_failures`` 必须变红。"""
    root = _copy_assets_temp()
    try:
        mutate(root)
        msgs = _failures(root)
        red = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}{tail}")
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


def prove_red() -> bool:
    """本票自带的破坏实验：真实树绿、四类破坏各自变红。不碰中央 prove-red 配方。"""
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    print("hooks_12 prove-red：逐一改坏真实产物的副本，要求 lord-family-no-leftover-wiring 变红")
    green = drift.check_all(repo_root=REPO_ROOT) == []
    print(f"  [{'PASS' if green else 'FAIL'}] 真实产物：领主战族遗留接线已收敛、无漂移（绿）")
    if not green:
        return False

    checks = [
        _fail_in("改坏 ①：往候选集中间塞一个额外事件引用（#12 专门要求）", _break_midlist_event_ref),
        _fail_in("改坏 ②：往枢纽候选集塞一个重复候选", _break_duplicate_candidate),
        _fail_in("改坏 ③：再塞一个「打哪个副本」选项块", _break_second_option_block),
        _fail_in("改坏 ④：给非链节点塞一个被链取代的旧后继", _break_old_successor),
    ]
    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#12",
        "领主战族遗留手写接线已收敛：无重复候选 / 强注入校验 / 选项块唯一 / 无旧后继",
        probe_lord_contract,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
