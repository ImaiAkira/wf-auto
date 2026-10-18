# -*- coding: utf-8 -*-
"""#103：五重**场景接口层**（B 方案 / MaaEnd 式）—— 契约挂点（自动发现，零改既有文件）。

## 本票做了什么（★R1b 修正后的形状★）

20 项异常前缀（``scene/wuchong.FLOW_EXCEPTIONS``）× 21 个业务节点（**带该前缀的节点其实是
22 个** = 21 业务 + 枢纽 ``WuchongEntry``）→ 收成两层：

```
业务节点（21 个，next = **真后继** + 末位兜底）
    [ "WuchongNavRow",                 // ① 本步真正的后继（FLOW_STEPS[i].next，★进度靠它★）
      "[JumpBack]SceneEnterWuchong" ]  // ② 万能跳转（DirectHit）★必须末位★
接口层（新文件 wuchong_scene.json，10 个节点）
    SceneEnterWuchong   (DirectHit) → [7 个验证器, [JumpBack]PubReturnHome, WuchongGuardChain]
    WuchongGuardChain   (DirectHit) → FLOW_EXCEPTIONS 的 20 项（**顺序一字不改**）+ WuchongGuardDone
    WuchongGuardDone    (DirectHit) → []      ← 弹栈的充要条件（★只有它允许空 next★）
    WuchongIn* × 7      (Custom/DoNothing) → ["WuchongEntry"]  ← 交回枢纽（★空 next = 任务流程终止★）
```

上位依据：``docs/spec/wuchong-scene-interface.md``（施工图）、``docs/spec/runner-delivery.md``
D5（选 B）、``docs/research/pipeline-exception-patterns.md`` §3.2 / §4.2。

## ★R1b：第一版为什么是错的（真机证据，本票的核心）★

第一版（#103 交付）把业务 next 收成 **2 项 = 验证器 + 跳转**。真机 2026-10-18 05:0x / A
（``--as-gui --mode 单人 --manual 手操 --set-file debug/wc_set_fights2.json``）**2.5 分钟内
11 个采样全是 ``state=wuchong_lord_list``、零进展、零战斗**。机制：

1. 枢纽按 ``FLOW_STEPS`` **声明序**分派，在列表页先派到 ``WuchongNavJoss``（识别 = 列表页
   state + 顶部『降临讨伐』页签文字 —— **页签文字永远可见**）；
2. 它的 next[0] 是验证器 ``WuchongInLordList`` —— **在列表页照样通过** ⇒ 动作（点页签）
   **永不发生**（零点击）；
3. 验证器交回枢纽 ⇒ 枢纽又派回 ``WuchongNavJoss`` ⇒ **死循环**（``WuchongScrollList`` 的
   ``state == wuchong_lord_list`` 也是恒真，同样永远轮不到正常节点 ``WuchongNavRow``）。

改造前不会打转，因为**线性 next 提供「进度」**（点完页签 → next 就是点行）。
⇒ 修法：业务 next 保留真后继，把 ``[JumpBack]SceneEnterWuchong`` 放**末位**。

## 七个守卫（票面 6 条 + 1 条保留的死循环守卫；破坏实验见 :func:`prove_red`）

1. ``wuchong-business-next-tail`` ①：21 个业务节点的 ``next`` **不许为空**，且**末项逐字**
   == ``STEP_TAIL``（``[JumpBack]SceneEnterWuchong``）、全文只出现一次；
2. ``wuchong-business-next-prefix`` ②：``next[:-1]``（真后继）**逐字** == ``FLOW_STEPS[i].next``
   （真后继被吞 / 被换 = 红），整串 == ``step_next()``（真源与投影双向同步），
   ``LEGACY_NEXT`` 必须是 False（逃生门没被偷偷翻开）；
3. ``wuchong-scene-enter-last`` ③：``SceneEnter*`` 出现在任何 ``next`` 里都必须是**最后一项**
   （DirectHit 永远命中，放前面 = 后续候选永不评估 = 在接口层里打转）；接口层入口自身
   必须是 DirectHit/DoNothing、``next == SCENE_ENTER_NEXT``、``on_error == [FLOW_HUB]``；
   ↳ ③b ``wuchong-guard-chain-no-backref``（#103 原有的第三条，保留）：中继不得回指接口层入口
   （两个 DirectHit 互指 = 零成本自环：一秒几百帧、零点击）；
4. ``wuchong-guard-chain-members`` ④：中继成员 == ``FLOW_EXCEPTIONS``（**集合 + 顺序**逐项比对），
   末位是 ``WuchongGuardDone`` 且它 ``next == []``；中继/验证器/入口**不得设 max_hit**
   （#79：任务级共享计数用尽即静默跳过）；
5. ``wuchong-scene-validators`` ⑤：7 个验证器**齐全**、``next == IN_NEXT``
   （**绝对**口径：``list(IN_NEXT) == ["WuchongEntry"]`` —— 空 next = 任务流程终止）、
   ``action == DoNothing``、识别 state 与 ``IN_STATES`` 逐字一致且都是既有 state 用过的值；
   ``IN_NODES`` 的键集 == 流程链节点集（每个流程步都登记了「动作落点页」）；
6. ``wuchong-recognition-terminates`` ⑥ ★R1b 的核心教训★：**识别必须可终结** —— 凡是证不出
   「动作成功后识别必然翻假」的业务节点（纯 state 识别 / 恒可见文字 / 动作不改判据 /
   raw 默认 ``__NONE__``），必须登记进 ``scene.wuchong.IDEMPOTENT_UNSAFE`` 并写明理由；
   未登记 = 红；反过来，**已能证明可终结却还赖在豁免表里**也红（豁免表不是藏污纳垢的地方）。

## 代价（B 方案唯一的实质代价，写给运维）

每轮多一次 ``SceneEnterWuchong``（DirectHit，~0.001s）+ 一到两次 ``WuchongIn*``（``Custom``
识别器内部跑 OCR，**不享受**框架 ``prefetch_batch_ocr`` 批量合并）⇒ **每轮 +0.1s 量级**。
★R1b 之后它**不再每轮发生**★：接口层只在「真后继全不命中」时才被走到（末位兜底），
比第一版（每步必走）频率低得多。劣化 >20% 仍可走 ``scene/wuchong.LEGACY_NEXT`` 逃生门回退。

## ★本票**不**声称的两件事（如实列出，避免假装绿灯就等于真机能跑）★

- **不验证运行时可达性**（离线没有设备）：本组守卫只钉**结构不变量**（不变量 ≠ 行为正确）。
- **不验证「R1b 形状下流程能连续跑完整场」**：真机必须按设计 §2 第 3 步**分批提测**
  （先 3 个节点），先看「任务是否还能连续跑完整场」，再看周期数字。这条风险写在这里，
  是因为它**不是守卫能替代的**。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
PIPELINE_DIR_REL = Path("assets") / "resource" / "pipeline"
WUCHONG_JSON = "wuchong.json"
SCENE_JSON = "wuchong_scene.json"

#: 接口层入口的合法前缀写法（``[JumpBack]`` 与否都算「引用了它」）。
_ENTER_PREFIXES = ("SceneEnter",)


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _wuchong():
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    return w


def _pipeline_dir(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else REPO_ROOT) / PIPELINE_DIR_REL


def _load(name: str, root: Path | None = None) -> dict:
    """读一个 pipeline 文件（JSONC）。★不吞异常★：坏 JSON 直接抛，套件因此变红。"""
    _paths()
    import jsonc  # noqa: PLC0415

    path = _pipeline_dir(root) / name
    with open(path, encoding="utf-8") as f:
        data = jsonc.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{name} 顶层不是对象")
    return data


def _load_all(root: Path | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(_pipeline_dir(root).glob("*.json")):
        out[path.name] = _load(path.name, root)
    return out


def _bare(ref) -> str:
    """去掉 ``[JumpBack]`` 前缀（其余原样返回；非字符串变成 repr 便于报错点名）。"""
    if not isinstance(ref, str):
        return repr(ref)
    return ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref


def _is_enter_ref(ref) -> bool:
    return _bare(ref).startswith(_ENTER_PREFIXES)


def _state_of(node: dict) -> str | None:
    """``recognition`` 是 ``Custom/wuchong_state`` 时返回它识别的 state 值。"""
    rec = node.get("recognition") or {}
    if rec.get("type") != "Custom":
        return None
    param = rec.get("param") or {}
    if param.get("custom_recognition") != "wuchong_state":
        return None
    return (param.get("custom_recognition_param") or {}).get("state")


def _refs(value) -> list:
    """把 ``next`` 里的字符串项挑出来（忽略内联对象）。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str)]
    return []


# ---------------------------------------------------------------------------
# 守卫 ⑤：7 个页面验证器齐全 / next == IN_NEXT（空 next = 任务流程终止）/ 识别参数与真源一致
# ---------------------------------------------------------------------------
#: 验证器 next 的**绝对**口径（★绝对断言，不是相对断言★）：七个页面验证器命中后一律交回枢纽。
#: 为什么不能只断言「JSON == scene.wuchong.IN_NEXT」：真源把 ``IN_NEXT`` 改成空元组时**相对**
#: 断言会整体变绿 —— 而那正是「验证器 next=[] = 任务流程终止」的致命形态（真机一跑就在第一步
#: 「任务完成」）。所以口径钉死在这里，不跟着真源漂；破坏实验见 :func:`prove_red`。
IN_NEXT_EXPECTED: tuple = ("WuchongEntry",)


def _validator_failures(root: Path | None = None, wuchong=None) -> list[str]:
    w = _wuchong() if wuchong is None else wuchong
    msgs: list[str] = []
    scene = _load(SCENE_JSON, root)
    wz = _load(WUCHONG_JSON, root)

    # ★绝对断言★：IN_NEXT 必须**就是** ["WuchongEntry"]（交回枢纽）。
    # 空 next（或指向别处）= 任务流程终止 / 与枢纽分派抢方向，都是致命形态。
    in_next_expected = list(IN_NEXT_EXPECTED)
    if list(getattr(w, "IN_NEXT", None) or []) != in_next_expected:
        msgs.append(
            f"scene.wuchong.IN_NEXT = {list(getattr(w, 'IN_NEXT', None) or [])!r} != {in_next_expected!r} —— "
            f"验证器的后继必须交回枢纽 {IN_NEXT_EXPECTED[0]!r}；"
            f"★空 next 不是「纯闸门」，是**任务流程终止**★（MaaFramework 语义）"
        )

    declared = dict(w.IN_STATES)
    if len(declared) != 7:
        msgs.append(f"scene.wuchong.IN_STATES 应有 7 个页面验证器，实际 {len(declared)}：{list(declared)}")
    order = tuple(getattr(w, "IN_SCENE_ORDER", ()))
    if order != tuple(declared):
        msgs.append(f"IN_SCENE_ORDER={order} 与 IN_STATES 的键顺序不一致（SceneEnter.next 的顺序会漂）")

    # 既有 state 节点用过的值（证明验证器**复用**既有状态，没有发明新判定）。
    known_states = {s for s in (_state_of(n or {}) for n in wz.values()) if s}
    for name, state in declared.items():
        node = scene.get(name)
        if not isinstance(node, dict):
            msgs.append(f"验证器缺失：{SCENE_JSON} 里没有 {name}（漏一个 = 该页面在接口层里无候选）")
            continue
        # ★#103-R1 修正★ 验证器的后继**不是空**，而是交回枢纽：MaaFramework 里
        #   「next 为空且无 [JumpBack]」= **任务流程终止**（真机一跑就会「任务完成」在第一步）。
        #   枢纽 WuchongEntry 是按 FLOW_STEPS 声明序的分派表，交回它 = 状态机模型。
        if not hasattr(w, "IN_NEXT"):
            msgs.append(
                "scene/wuchong.py 没有 IN_NEXT —— R1 修正的真源常量必须是真源的一部分；"
                "守卫不许用 getattr 默认值给它兜底（那样真源缺失也能绿）"
            )
        in_next = list(getattr(w, "IN_NEXT", None) or [])
        if list(node.get("next") or []) != in_next:
            msgs.append(
                f"验证器 {name}.next 必须是 {in_next!r}（实际 {node.get('next')!r}）—— "
                f"空 next = 任务流程终止；指向别处 = 与枢纽分派抢方向"
            )
        if (node.get("action") or {}).get("type") != "DoNothing":
            msgs.append(f"验证器 {name} 的动作必须是 DoNothing（实际 {(node.get('action') or {}).get('type')!r}）")
        got_state = _state_of(node)
        if got_state != state:
            msgs.append(
                f"验证器 {name} 的识别参数 state={got_state!r} != 真源 scene.wuchong.IN_STATES[{name!r}]={state!r}"
                f"（识别必须复用既有 wuchong_state 的同一个值）"
            )
        cap = ((node.get("recognition") or {}).get("param") or {}).get("custom_recognition_param") or {}
        if cap.get("ocr_entry") != "OcrTask":
            msgs.append(f"验证器 {name} 缺 ocr_entry=OcrTask（与既有 state 节点不同形，OCR 入口会不一致）")
        if state not in known_states:
            msgs.append(
                f"验证器 {name} 的 state={state!r} 不是任何既有 state 节点用过的值"
                f"（既有：{sorted(known_states)}）—— 不许发明新状态"
            )

    extra = sorted(k for k in scene if k.startswith("WuchongIn") and k not in declared)
    if extra:
        msgs.append(f"接口层里有未登记的验证器 {extra}（真源没有它 → 谁在维护它？）")

    # ★R1b 后 IN_NODES 不进业务 next，但仍是必需数据★：它登记「这一步动作的落点页」，
    #   图论自检靠它证明「无死状态」，守卫 ⑥ 靠它算「动作后是否必然离开当前页」。
    steps = list(w.flow_step_nodes())
    in_nodes = dict(getattr(w, "IN_NODES", {}) or {})
    if set(in_nodes) != set(steps):
        msgs.append(
            f"IN_NODES 的键集 != 流程链节点集 —— 多={sorted(set(in_nodes) - set(steps))} "
            f"缺={sorted(set(steps) - set(in_nodes))}（新增流程步必须同时声明「它的动作落点页验证器」）"
        )
    bad_validator = sorted({v for v in in_nodes.values() if v not in declared})
    if bad_validator:
        msgs.append(f"IN_NODES 指向了未定义的验证器 {bad_validator}")
    return msgs


def probe_wuchong_scene_validators() -> bool:
    return _validator_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ①：21 个业务节点 next 的末项必须是 [JumpBack]SceneEnterWuchong，且**不许为空**
# ---------------------------------------------------------------------------
def _tail_failures(root: Path | None = None, wuchong=None) -> list[str]:
    w = _wuchong() if wuchong is None else wuchong
    msgs: list[str] = []
    wz = _load(WUCHONG_JSON, root)

    tail = getattr(w, "STEP_TAIL", None)
    if tail != f"[JumpBack]{w.SCENE_ENTER}":
        msgs.append(
            f"scene.wuchong.STEP_TAIL={tail!r} != '[JumpBack]' + SCENE_ENTER "
            f"（末位兜底的**唯一合法写法**是带 [JumpBack] 的那一个）"
        )
        return msgs

    for node in w.flow_step_nodes():
        nxt = _refs((wz.get(node) or {}).get("next"))
        if not nxt:
            msgs.append(
                f"{node}.next 为空 —— 业务节点**至少要有末位 {tail}**"
                f"（空 next = 任务流程终止；R1b 之后真后继也在里面，绝不允许空）"
            )
            continue
        if nxt[-1] != tail:
            msgs.append(
                f"{node}.next 末项 = {nxt[-1]!r} != {tail!r} —— "
                f"末位必须是万能跳转（★R1b：真后继在前、兜底在末位★；放前面 = 后续候选永不评估）"
            )
        hits = [i for i, ref in enumerate(nxt) if _bare(ref) == w.SCENE_ENTER]
        if len(hits) != 1:
            msgs.append(
                f"{node}.next 里 {w.SCENE_ENTER} 出现 {len(hits)} 次（位置 {hits}）—— 只能有一项，且必须是末项"
            )
    return msgs


def probe_wuchong_business_next_tail() -> bool:
    return _tail_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ②：真后继没被吞 —— next[:-1] 逐字 == FLOW_STEPS[i].next；整串 == step_next()
# ---------------------------------------------------------------------------
def _prefix_failures(root: Path | None = None, wuchong=None) -> list[str]:
    w = _wuchong() if wuchong is None else wuchong
    msgs: list[str] = []
    wz = _load(WUCHONG_JSON, root)

    if getattr(w, "LEGACY_NEXT", None) is not False:
        msgs.append(
            f"scene.wuchong.LEGACY_NEXT={w.LEGACY_NEXT!r}（迁移未生效）—— 它是**逃生门**，"
            f"翻成 True 的同时必须把 21 个业务 next 改回旧形状，别让半迁移上线"
        )

    successors = dict(getattr(w, "step_successors", lambda: {})() or {})
    for node in w.flow_step_nodes():
        nxt = _refs((wz.get(node) or {}).get("next"))
        want_prefix = list(successors.get(node) or ())
        got_prefix = nxt[:-1]
        if got_prefix != want_prefix:
            msgs.append(
                f"{node}.next 的真后继被吞/被换：{got_prefix} != {want_prefix}"
                f"（FLOW_STEPS 声明的**真后继**必须逐字出现在末位兜底之前 —— "
                f"★进度就靠它★；R1b 真机：真后继一没，动作永不发生、枢纽反复派回本节点）"
            )
            continue
        want = list(w.step_next(node) or ())
        if nxt != want:
            msgs.append(
                f"{node}.next={nxt} 应为 {want}（真源 scene.wuchong.step_next；"
                f"改了真源没投影，或投影改了没真源）"
            )
    return msgs


def probe_wuchong_business_next_prefix() -> bool:
    return _prefix_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ③：SceneEnter* 只能出现在 next 的最后一项（死循环风险 R1）
# ---------------------------------------------------------------------------
def _enter_position_failures(root: Path | None = None) -> list[str]:
    w = _wuchong()
    msgs: list[str] = []
    files = _load_all(root)
    wired = 0
    for fname, data in files.items():
        for name, node in data.items():
            if not isinstance(node, dict):
                continue
            nxt = node.get("next")
            if not isinstance(nxt, list):
                continue
            hits = [i for i, ref in enumerate(nxt) if _is_enter_ref(ref)]
            if not hits:
                continue
            wired += len(hits)
            for i in hits:
                if i != len(nxt) - 1:
                    msgs.append(
                        f"{fname}::{name}.next[{i}]={nxt[i]!r} 不是最后一项（末项={nxt[-1]!r}）—— "
                        f"SceneEnter* 是 DirectHit，放前面 = 后续候选永不评估 = 在接口层里打转"
                    )
            if len(hits) > 1:
                msgs.append(
                    f"{fname}::{name}.next 里出现了 {len(hits)} 次 SceneEnter* "
                    f"（{hits}）—— 只能有一项，且必须是末项"
                )
    if not wired:
        msgs.append(
            f"没有任何节点引用 {w.SCENE_ENTER}（接口层没接线：21 个业务节点都应把它放末项）"
        )

    # 接口层入口自身的形状（R1b 之后它是**低频兜底**，更不容许漂）。
    scene = _load(SCENE_JSON, root)
    enter = scene.get(w.SCENE_ENTER)
    if not isinstance(enter, dict):
        msgs.append(f"{SCENE_JSON} 里没有接口层入口 {w.SCENE_ENTER}")
    else:
        if (enter.get("recognition") or {}).get("type") != "DirectHit":
            msgs.append(f"{w.SCENE_ENTER} 必须是 DirectHit（它只做分派，不做识别）")
        if (enter.get("action") or {}).get("type") != "DoNothing":
            msgs.append(f"{w.SCENE_ENTER} 的动作必须是 DoNothing（点位只属于业务/异常节点）")
        if _refs(enter.get("next")) != list(w.SCENE_ENTER_NEXT):
            msgs.append(
                f"{w.SCENE_ENTER}.next={_refs(enter.get('next'))} 应为 {list(w.SCENE_ENTER_NEXT)}"
                f"（7 个验证器 → 回主城 → 中继）"
            )
        if _refs(enter.get("on_error")) != [w.FLOW_HUB]:
            msgs.append(f"{w.SCENE_ENTER}.on_error 应为 [{w.FLOW_HUB!r}]（扫超时也回枢纽，绝不悬空）")
    return msgs


def probe_wuchong_scene_enter_last() -> bool:
    return _enter_position_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ③b：中继不得回指接口层入口（DirectHit ↔ DirectHit = 零成本自环）
# ---------------------------------------------------------------------------
def _relay_backref_failures(root: Path | None = None) -> list[str]:
    w = _wuchong()
    msgs: list[str] = []
    scene = _load(SCENE_JSON, root)
    relay = scene.get(w.SCENE_GUARD_CHAIN)
    if not isinstance(relay, dict):
        return [f"{SCENE_JSON} 里没有中继 {w.SCENE_GUARD_CHAIN}（20 项异常无处安放）"]
    nxt = _refs(relay.get("next"))
    for i, ref in enumerate(nxt):
        if _is_enter_ref(ref):
            msgs.append(
                f"{w.SCENE_GUARD_CHAIN}.next[{i}]={ref!r} 回指了接口层入口 —— "
                f"中继(DirectHit) ↔ 入口(DirectHit) 互指 = 零成本自环（一秒几百帧、零点击）"
            )
        if _bare(ref) in (w.SCENE_GUARD_CHAIN, w.SCENE_GUARD_DONE) and i != len(nxt) - 1:
            msgs.append(
                f"{w.SCENE_GUARD_CHAIN}.next[{i}]={ref!r} 只能是末项（回跳闩先命中就没人扫异常阶梯了）"
            )
    # 接口层入口自己也不得自指 / 回指中继两次（会多压一层栈）。
    enter = scene.get(w.SCENE_ENTER) or {}
    enext = _refs(enter.get("next"))
    if any(_bare(r) == w.SCENE_ENTER for r in enext):
        msgs.append(f"{w.SCENE_ENTER}.next 自指（DirectHit 自环）")
    if [_bare(r) for r in enext].count(w.SCENE_GUARD_CHAIN) > 1:
        msgs.append(f"{w.SCENE_ENTER}.next 里 {w.SCENE_GUARD_CHAIN} 出现多次（会重复扫阶梯、重复压栈）")
    return msgs


def probe_wuchong_guard_chain_no_backref() -> bool:
    return _relay_backref_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ④：中继成员 == FLOW_EXCEPTIONS（集合 + 顺序），末位是回跳闩
# ---------------------------------------------------------------------------
def _relay_member_failures(root: Path | None = None) -> list[str]:
    w = _wuchong()
    msgs: list[str] = []
    scene = _load(SCENE_JSON, root)
    relay = scene.get(w.SCENE_GUARD_CHAIN)
    if not isinstance(relay, dict):
        return [f"{SCENE_JSON} 里没有中继 {w.SCENE_GUARD_CHAIN}（20 项异常无处安放）"]
    got = _refs(relay.get("next"))
    want = list(w.GUARD_CHAIN_NEXT)
    exceptions = list(w.FLOW_EXCEPTIONS)

    missing = [r for r in exceptions if r not in got]
    if missing:
        msgs.append(
            f"中继漏了异常节点 {missing}（一条都不能少：它是这些异常**唯一**的挂载点）"
        )
    extra = [r for r in got if r not in exceptions and r != w.SCENE_GUARD_DONE]
    if extra:
        msgs.append(f"中继里有多余成员 {extra}（真源 FLOW_EXCEPTIONS 里没有它们）")
    if not missing and not extra and got != want:
        msgs.append(
            f"中继成员集合对但**顺序**不符（顺序承重：如 WuchongContinueGuard 必须在 "
            f"[JumpBack]PubGameOverContinue 之前，否则超限那一帧会先点一次续关）\n"
            f"      期望={want}\n      实际={got}"
        )
    if not got or got[-1] != w.SCENE_GUARD_DONE:
        msgs.append(
            f"中继末位必须是回跳闩 {w.SCENE_GUARD_DONE}（实际末项 {got[-1] if got else None!r}）—— "
            f"阶梯扫不到东西时要能立刻弹栈，而不是空转到 timeout"
        )
    done = scene.get(w.SCENE_GUARD_DONE)
    if not isinstance(done, dict):
        msgs.append(f"缺回跳闩 {w.SCENE_GUARD_DONE}")
    elif done.get("next") != []:
        msgs.append(f"{w.SCENE_GUARD_DONE}.next 必须为 []（那是**弹栈的充要条件**）")
    # DirectHit 中继/入口/验证器一律不得设 max_hit（#79：任务级共享计数，用尽即静默跳过）。
    for name in (w.SCENE_ENTER, w.SCENE_GUARD_CHAIN, w.SCENE_GUARD_DONE, *w.IN_STATES):
        if isinstance(scene.get(name), dict) and "max_hit" in scene[name]:
            msgs.append(
                f"{name} 带了 max_hit={scene[name]['max_hit']!r} —— 中继/验证器会被静默跳过"
                f"（#79 真机：打几把之后异常彻底失守），改用时间闩锁或交给 agent 侧"
            )
    return msgs


def probe_wuchong_guard_chain_members() -> bool:
    return _relay_member_failures() == []


# ---------------------------------------------------------------------------
# 守卫 ⑥：★识别必须可终结★（R1b 的核心教训）—— 证不出就必须登记豁免 + 理由
# ---------------------------------------------------------------------------
def _rec_leaves(node, wz: dict, seen: set | None = None):
    """把一个节点的识别递归展开成叶子列表（``And.all_of`` 里的**字符串是节点引用**，要解析）。

    返回 ``[recognition_dict, ...]``：``Custom/wuchong_state``、``OCR``、``TemplateMatch``…
    逐个叶子原样返回，交给调用方按类型判断（不在这里猜语义）。
    """
    if seen is None:
        seen = set()
    out: list = []
    if not isinstance(node, dict):
        return out
    rec = node.get("recognition")
    if not isinstance(rec, dict):
        return out
    typ = rec.get("type")
    param = rec.get("param") or {}
    if typ == "And":
        for leaf in param.get("all_of") or []:
            if isinstance(leaf, dict):
                inner = leaf.get("recognition")
                if isinstance(inner, dict):
                    out.extend(_rec_leaves({"recognition": inner}, wz, seen))
                elif leaf.get("type"):
                    out.extend(_rec_leaves({"recognition": leaf}, wz, seen))
            elif isinstance(leaf, str):
                ref = wz.get(leaf)
                if isinstance(ref, dict) and leaf not in seen:
                    seen.add(leaf)
                    out.extend(_rec_leaves(ref, wz, seen))
    else:
        out.append(rec)
    return out


def _custom_param(rec: dict) -> tuple[str | None, dict]:
    if not isinstance(rec, dict) or rec.get("type") != "Custom":
        return (None, {})
    param = rec.get("param") or {}
    return (param.get("custom_recognition"), param.get("custom_recognition_param") or {})


def _terminate_proof(w, node: str, wz: dict) -> str | None:
    """能证明「动作成功后本节点的识别必然翻假」就返回证明（'page' / 'switch'），否则 None。

    两条证明（都从 pipeline **静态**算出来，不读豁免表 —— 否则守卫会自证）：

    * ``page``：识别引用的 ``wuchong_state`` 里**没有**本节点动作的落点页（``IN_NODES``）——
      动作成功 ⇒ 离开该 state ⇒ 识别翻假（例：``WuchongNavLord`` 认主城、落点列表页）；
    * ``switch``：识别是 ``auto_switch_state`` 且要求的态与本节点动作写下去的态**相反** ——
      动作成功 ⇒ 开关读数变为目标态 ⇒ 识别翻假（例：``WuchongTeamAutoSet`` 认 off、写 on）。
    """
    node_dict = wz.get(node) or {}
    leaves = _rec_leaves(node_dict, wz)

    # (a) 页面变化
    states = {
        cap.get("state")
        for rec in leaves
        for kind, cap in [_custom_param(rec)]
        if kind == "wuchong_state" and cap.get("state")
    }
    landing = (w.IN_STATES or {}).get((w.IN_NODES or {}).get(node))
    if states and landing and landing not in states:
        return "page"

    # (b) 开关翻转
    action = node_dict.get("action") or {}
    aparam = (action.get("param") or {}) if action.get("type") == "Custom" else {}
    if aparam.get("custom_action") == "wuchong_switch":
        cap = aparam.get("custom_action_param") or {}
        if isinstance(cap.get("on"), bool):
            target = "on" if cap["on"] else "off"
            for rec in leaves:
                kind, rcap = _custom_param(rec)
                if kind == "auto_switch_state" and rcap.get("state") in ("on", "off"):
                    if rcap["state"] != target:
                        return "switch"
    return None


def _idempotent_failures(root: Path | None = None, wuchong=None) -> list[str]:
    w = _wuchong() if wuchong is None else wuchong
    msgs: list[str] = []
    wz = _load(WUCHONG_JSON, root)
    table = dict(getattr(w, "IDEMPOTENT_UNSAFE", {}) or {})
    steps = list(w.flow_step_nodes())

    if not table:
        msgs.append(
            "scene.wuchong.IDEMPOTENT_UNSAFE 不存在或为空 —— 守卫 ⑥「识别必须可终结」的真源就是它；"
            "没有它，恒真识别（R1b 的两个同谋）只能靠人自觉"
        )
        return msgs

    for node in steps:
        proof = _terminate_proof(w, node, wz)
        reason = table.get(node)
        if proof is None:
            if reason is None:
                msgs.append(
                    f"{node} 的识别**不随屏幕内容翻转**（证不出「动作成功后它必然翻假」），"
                    f"却没登记进 scene.wuchong.IDEMPOTENT_UNSAFE —— 枢纽按声明序派发时会被反复派中"
                    f"（R1b 真机：2.5 分钟零进展、零点击）；必须登记并写明「为什么动作后它不会再次命中」"
                )
            elif not isinstance(reason, str) or len(reason.strip()) < 20:
                msgs.append(
                    f"IDEMPOTENT_UNSAFE[{node!r}] 的理由太短/为空（{reason!r}）—— "
                    f"必须是「为什么动作后它不会再次命中」这句设计结论，不是占位符"
                )
        elif reason is not None:
            msgs.append(
                f"{node} 已被静态证明可终结（proof={proof}），却还登记在 IDEMPOTENT_UNSAFE —— "
                f"豁免表只装**今天证不出**的节点（否则它会变成藏污纳垢的地方，恒真识别就混在里面了）"
            )

    unknown = sorted(set(table) - set(steps))
    if unknown:
        msgs.append(f"IDEMPOTENT_UNSAFE 里有非流程节点 {unknown}（拼错节点名？真源里没有它们）")
    return msgs


def probe_wuchong_recognition_terminates() -> bool:
    return _idempotent_failures() == []


# ---------------------------------------------------------------------------
# 前后对照表（票里要贴的证据）：**脚本统计**，不是手抄
# ---------------------------------------------------------------------------
#: 设计文档（``docs/spec/wuchong-scene-interface.md`` 开头）写的基线数字（★已过期，留着做对照★）。
DOC_BASELINE = {"nodes": 55, "next": 443, "prefix_len": 16, "prefix_nodes": 22}

#: **票面数字的基线 commit**：``17a05c6``（``feat(#103)`` 落地那一次）。
#: 票里写的 **509 → 92（-81.9%）** 就是在这个提交上、按「全仓 wuchong.json」口径算的。
#: ★为什么今天复算不出 509/92★：两处口径漂移都已写成本表的算术，:func:`print_stats` 会打印
#: 「票面 → 今日」的复算过程，别再让票面数字变成没人能复现的传说。
TICKET_BASELINE_COMMIT = "17a05c6"
TICKET_BASELINE = {
    "commit": TICKET_BASELINE_COMMIT,
    #: #103 当时 ``FLOW_EXCEPTIONS`` 是 19 项（#102 之后才是 20）⇒ 21 个业务节点各少 1 条前缀
    "prefix_len": 19,
    #: 票面全仓口径（wuchong.json；legacy_step_next 反推 / 当前投影）
    "before_next": 509,
    "after_next": 92,
    #: ★B 方案第一版（#103 交付 / 已被 R1b 取代）★：21 个业务节点一律 2 项。
    "v1_step_len": 2,
}


def stats(root: Path | None = None) -> dict:
    """统计改造前后（**同一脚本**算两边，故可比）。

    * ``after``  = 直接读 ``wuchong.json``（当前投影，R1b 形状）；
    * ``before`` = 用 ``scene/wuchong`` 的**旧形状派生**（``legacy_step_next`` = 异常前缀 + 本步）
      算出「若把 21 个业务节点的前缀还原回去，会是多少」—— 非业务节点两边相同。
    """
    w = _wuchong()
    wz = _load(WUCHONG_JSON, root)
    exceptions = list(w.FLOW_EXCEPTIONS)
    flow = list(w.flow_step_nodes())
    successors = dict(getattr(w, "step_successors", lambda: {})() or {})

    after = {k: list((v or {}).get("next") or []) for k, v in wz.items() if isinstance(v, dict)}
    before = dict(after)
    for node in flow:
        legacy = w.legacy_step_next(node)
        if legacy is not None:
            before[node] = list(legacy)

    def _sum(d: dict) -> int:
        return sum(len(v) for v in d.values())

    def _count_prefix(d: dict) -> int:
        return sum(1 for v in d.values() if v[: len(exceptions)] == exceptions)

    b_tot, a_tot = _sum(before), _sum(after)
    b_step = sum(len(before[s]) for s in flow)
    a_step = sum(len(after[s]) for s in flow)
    n = len(after)
    lens = [len(after[s]) for s in flow]
    # 接口层是**新文件**（#103 之前不存在）：它的 next 条目在「改造前」口径里是 0。
    try:
        scene = _load(SCENE_JSON, root)
    except OSError:
        scene = {}
    iface_next = sum(
        len((v or {}).get("next") or []) for v in scene.values() if isinstance(v, dict)
    )
    return {
        "nodes": n,
        "before_next": b_tot,
        "after_next": a_tot,
        # ★两种口径★：① 只算 21 个 FLOW_STEPS 业务节点；② 全仓含接口层（wuchong.json + wuchong_scene.json）
        "before_step_next": b_step,
        "after_step_next": a_step,
        "before_all_next": b_tot,                 # 接口层改造前不存在 ⇒ 0
        "after_all_next": a_tot + iface_next,
        "interface_next": iface_next,
        "before_prefix_nodes": _count_prefix(before),
        "after_prefix_nodes": _count_prefix(after),
        "prefix_len": len(exceptions),
        "before_avg": (b_tot / n) if n else 0.0,
        "after_avg": (a_tot / n) if n else 0.0,
        "before_step_avg": (b_step / len(flow)) if flow else 0.0,
        "after_step_avg": (a_step / len(flow)) if flow else 0.0,
        "interface_nodes": len(w.IN_STATES) + 3,  # 7 个验证器 + 入口/中继/回跳闩
        "flow_nodes": len(flow),
        # ★R1b 的三方对照（每个业务节点一行）★
        "steps": [
            (
                node,
                len(before[node]),
                TICKET_BASELINE["v1_step_len"],
                len(after[node]),
                len(successors.get(node) or ()) + 1,
            )
            for node in flow
        ],
        "step_len_min": min(lens) if lens else 0,
        "step_len_max": max(lens) if lens else 0,
        "step_len_hist": {k: lens.count(k) for k in sorted(set(lens))},
        "successor_total": sum(len(v) for v in successors.values()),
        "exemptions": sorted(getattr(w, "IDEMPOTENT_UNSAFE", {}) or {}),
        "doc_baseline": dict(DOC_BASELINE),
        "ticket_baseline": dict(TICKET_BASELINE),
    }


def print_stats(root: Path | None = None) -> None:
    s = stats(root)
    w = _wuchong()

    def _width(text: str) -> int:
        """显示宽度（CJK / 全角算 2 列）—— 表格对齐用。"""
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)

    def _pad(text: str, width: int, right: bool = False) -> str:
        gap = max(0, width - _width(text))
        return (" " * gap + text) if right else (text + " " * gap)

    print("== #103 前后对照（脚本统计）==")
    print(
        f"  基线 commit：{TICKET_BASELINE_COMMIT}（#103 落地；票面 "
        f"{TICKET_BASELINE['before_next']}→{TICKET_BASELINE['after_next']} 就是在它上面算的，"
        f"{TICKET_BASELINE['prefix_len']} 项异常前缀）"
    )
    print("  「改造前」= scene.wuchong.legacy_step_next() 反推（异常前缀 + 本步后继），不是某个提交的实测快照")
    print(
        f"  今日 = 当前工作树（{s['nodes']} 节点，{s['prefix_len']} 项异常前缀；"
        f"接口层另在 {SCENE_JSON}，{s['interface_nodes']} 个节点）"
    )
    print(
        "  ★两种口径★ ① 本步业务节点（21 个 FLOW_STEPS 节点，只算业务 next）"
        " ② 全仓含接口层（wuchong.json 全部节点 + wuchong_scene.json 的接口层）"
    )
    print(
        "  "
        + _pad("指标", 40)
        + _pad("改造前", 10, True)
        + _pad("改造后", 10, True)
        + _pad("变化", 22, True)
    )
    rows = [
        (f"{WUCHONG_JSON} 节点数", s["nodes"], s["nodes"]),
        (f"① 本步业务节点 next 条目（{s['flow_nodes']} 个）", s["before_step_next"], s["after_step_next"]),
        ("② 全仓含接口层 next 条目", s["before_all_next"], s["after_all_next"]),
        (f"（票面口径）{WUCHONG_JSON} 全仓 next 条目", s["before_next"], s["after_next"]),
        (f"带 {s['prefix_len']} 项异常前缀的节点", s["before_prefix_nodes"], s["after_prefix_nodes"]),
        ("业务节点 next 平均长度", round(s["before_step_avg"], 2), round(s["after_step_avg"], 2)),
        ("全节点 next 平均长度", round(s["before_avg"], 3), round(s["after_avg"], 3)),
        (f"接口层节点 / next 条目（{SCENE_JSON}）", 0, f"{s['interface_nodes']} / {s['interface_next']}"),
    ]
    for label, b, a in rows:
        if isinstance(b, int) and isinstance(a, int):
            delta = f"{a - b:+d}"
            if b:
                delta += f" ({(a - b) / b * 100:+.1f}%)"
        elif isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta = f"{a - b:+.3f}"
            if b:
                delta += f" ({(a - b) / b * 100:+.1f}%)"
        else:
            delta = f"{a} 新增"
        print(
            "  "
            + _pad(label, 40)
            + _pad(str(b), 10, True)
            + _pad(str(a), 10, True)
            + _pad(delta, 22, True)
        )
    # ★票面复算★：把「票面数字 → 今日数字」的每一步都打出来（口径漂移必须可算，不许是传说）。
    # ★R1b★ 之后「改造后」多了**一项形状增量**：业务 next 由第一版的 2 项×21 变成「真后继 + 末位」，
    #   故今日 = 票面 92 + 基线后的新增引用 + 形状增量；三者相加必须精确等于实测，否则有人只改了一边。
    t = s["ticket_baseline"]
    prefix_gain = (s["prefix_len"] - t["prefix_len"]) * s["flow_nodes"]
    expected_before = t["before_next"] + prefix_gain
    drift = s["before_next"] - expected_before          # 基线之后在 wuchong.json 新增的 next 引用
    v1_step_total = t["v1_step_len"] * s["flow_nodes"]   # 第一版业务 next 条目 = 2×21 = 42
    shape_gain = s["after_step_next"] - v1_step_total    # R1b：真后继回到业务 next 带来的增量
    expected_after = t["after_next"] + drift + shape_gain
    print(
        f"  票面复算（「票面口径」= {WUCHONG_JSON} 全仓，@ {t['commit']}）："
        f"改造前 {t['before_next']} = {t['before_next']} + "
        f"({s['prefix_len']}−{t['prefix_len']} 项前缀)×{s['flow_nodes']} 个业务节点 = {expected_before}"
        f"，其余 {drift:+d}（基线之后在 {WUCHONG_JSON} 新增的 next 引用）⇒ 今日 {s['before_next']}"
    )
    print(
        f"    改造后 {t['after_next']}（第一版 2 项×{s['flow_nodes']}）"
        f" + {drift:+d}（同一条新增引用）"
        f" + {shape_gain:+d}（★R1b：真后继回到业务 next，{v1_step_total} → {s['after_step_next']} 项★）"
        f" = {expected_after} ⇒ 今日实测 {s['after_next']}"
        f"　{'一致 ✅' if expected_after == s['after_next'] else '不一致 ❌ 有人只改了一边'}★"
    )
    d = s["doc_baseline"]
    print(
        f"  设计文档写的基线：{d['nodes']} 节点 / {d['next']} 条 next / {d['prefix_len']} 项前缀 —— "
        f"★已过期★：实测 {s['nodes']} 节点 / {s['before_next']} 条 / {s['prefix_len']} 项"
        f"（#72 续关链 2 项 + #107 三个掉线/重连节点把 16 撑到 19；#102 再撑到 20；节点数也涨了）"
    )
    print(
        f"  业务节点 = {s['flow_nodes']} 个（FLOW_STEPS 步数）；"
        f"枢纽 WuchongEntry 的 {len(w.hub_next())} 项不变（它本来就是分派表）"
    )
    # ★R1b 口径：业务 next 长度三方对照 + 分布★（票面要的就是这一行）。
    print(
        f"  业务 next 长度：★改造前 {min(b for _n, b, _v, _a, _w in s['steps'])}–"
        f"{max(b for _n, b, _v, _a, _w in s['steps'])} 项（异常前缀 + 本步后继） / "
        f"第一版 {TICKET_BASELINE['v1_step_len']} 项 × {s['flow_nodes']}（验证器 + 跳转，真机打转） / "
        f"现在 {s['step_len_min']}–{s['step_len_max']} 项★"
        f"（= 真后继 {s['successor_total']} 条摊到 {s['flow_nodes']} 步 + 每步 1 项末位兜底）"
    )
    print(
        "  现在长度的分布："
        + "  ".join(f"{k} 项×{v}" for k, v in s["step_len_hist"].items())
        + f"　（平均 {round(s['after_step_avg'], 2)} 项）"
    )
    # 逐节点三方对照（★= 设计 §2 第 3 步点名先提测的 3 个节点）。
    batch1 = ("WuchongNavLord", "WuchongDetailFight", "WuchongTeamChallenge")
    print("  逐节点 next 长度（改造前 / 第一版 / 现在；★ = 第一批提测的 3 个）：")
    for node, b, v1, a, want in s["steps"]:
        star = "★" if node in batch1 else " "
        flag = "" if want == a else f"  ← 应为 {want}"
        print(f"   {star} {node:<26}{b:>4} /{v1:>3} /{a:>3}{flag}")
    print(
        f"  流程推进边的形状：业务 next 的前 {s['after_step_avg'] - 1:.1f} 项是**真后继**"
        f"（{s['successor_total']} 条），末项恒为 {w.STEP_TAIL}"
    )
    print(
        f"  识别可终结性（守卫 ⑥）：{len(s['exemptions'])}/{s['flow_nodes']} 个业务节点登记在豁免表 —— "
        + "、".join(s["exemptions"])
    )


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _temp_pipeline() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook103_"))
    shutil.copytree(_pipeline_dir(), root / PIPELINE_DIR_REL)
    return root


def _mutate(root: Path, mutate) -> None:
    """把临时副本读成纯 dict → 交给 ``mutate`` 改 → 写回纯 JSON（注释丢弃，只求可判）。

    ★为什么不改文本★：本文件的新形状写得**一模一样**（21 个节点都是同一对字符串），
    文本替换会改错节点；dict 级改动可以精确点名，且守卫只按 dict 读。
    """
    data = {name: _load(name, root) for name in (WUCHONG_JSON, SCENE_JSON)}
    mutate(data)
    # 其余文件原样保留（守卫 ③ 会扫全部文件）。
    for name, blob in data.items():
        path = root / PIPELINE_DIR_REL / name
        path.write_text(json.dumps(blob, ensure_ascii=False, indent=4), encoding="utf-8")


def _break_and_check(label: str, mutate, run) -> bool:
    root = _temp_pipeline()
    try:
        _mutate(root, mutate)
        msgs = run(root)
        red = len(msgs) > 0
        print(
            f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}"
            + (f"  {msgs[0]}" if msgs else "")
        )
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


def prove_red() -> bool:
    w = _wuchong()
    print("hooks_103 prove-red：逐一破坏接口层，要求七个守卫各自变红")
    green = (
        probe_wuchong_scene_validators() is True
        and probe_wuchong_business_next_tail() is True
        and probe_wuchong_business_next_prefix() is True
        and probe_wuchong_scene_enter_last() is True
        and probe_wuchong_guard_chain_no_backref() is True
        and probe_wuchong_guard_chain_members() is True
        and probe_wuchong_recognition_terminates() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：七个守卫全绿")
    if not green:
        return False

    print_stats()

    checks: list[bool] = []
    scene = SCENE_JSON
    wz = WUCHONG_JSON

    def _drop_validator(data):
        data[scene].pop("WuchongInSettle", None)

    checks.append(
        _break_and_check("⑤ 验证器漏一个（删掉 WuchongInSettle）", _drop_validator, _validator_failures)
    )

    def _validator_next(data):
        # ★#103-R1★ 致命形态：验证器 next 为空 -> MaaFramework 认为流程结束（任务在这一步「完成」）
        data[scene]["WuchongInTeam"]["next"] = []

    checks.append(
        _break_and_check(
            "⑤ 验证器 next 写成空（#103-R1 的致命形态：任务流程直接终止）", _validator_next, _validator_failures
        )
    )

    # ★⑤ 的破坏实验★：**真源**把 IN_NEXT 改成空元组 / 把 IN_NODES 挖一个洞。
    # 相对断言（JSON == IN_NEXT）在这一步会整体变绿 —— 绝对断言必须把它抓住。
    def _fake_wuchong(**overrides):
        ns = {
            name: getattr(w, name)
            for name in dir(w)
            if not name.startswith("__")
        }
        ns.update(overrides)
        return types.SimpleNamespace(**ns)

    #: 真源侧破坏实验**不改 pipeline**（IN_NEXT / IN_NODES / 豁免表都在 scene/wuchong.py 里）。
    def _noop(data):
        pass

    checks.append(
        _break_and_check(
            "⑤ 真源 IN_NEXT 改成 ()（相对断言会绿；绝对断言必须红 —— 空 next = 任务流程终止）",
            _noop,
            lambda root: _validator_failures(root, wuchong=_fake_wuchong(IN_NEXT=())),
        )
    )

    in_nodes_hole = {k: v for k, v in w.IN_NODES.items() if k != "WuchongNavRow"}
    checks.append(
        _break_and_check(
            "⑤ 真源 IN_NODES 少一条（WuchongNavRow 没登记落点页 → 无死状态/可终结性都判不了）",
            _noop,
            lambda root: _validator_failures(root, wuchong=_fake_wuchong(IN_NODES=in_nodes_hole)),
        )
    )

    def _wrong_state(data):
        cap = data[scene]["WuchongInFight"]["recognition"]["param"]["custom_recognition_param"]
        cap["state"] = "wuchong_lord_list"

    checks.append(
        _break_and_check(
            "⑤ 验证器识别参数漂移（WuchongInFight.state 改成 lord_list）", _wrong_state, _validator_failures
        )
    )

    # ---- ① 末项不是 SceneEnter（R1b 新增的两条之一）----
    def _tail_missing(data):
        data[wz]["WuchongNavLord"]["next"] = ["WuchongNavJoss"]

    checks.append(
        _break_and_check(
            "① 业务 next 末项不是 SceneEnter（WuchongNavLord 只留真后继）",
            _tail_missing,
            _tail_failures,
        )
    )

    def _tail_empty(data):
        data[wz]["WuchongSettleDisband"]["next"] = []

    checks.append(
        _break_and_check("① 业务 next 写成空（末位兜底被删）", _tail_empty, _tail_failures)
    )

    # ---- ② 真后继被吞 ----
    def _successor_swallowed(data):
        # 只剩末位兜底：真后继没了 = 进度全丢（R1b 的成因反向再现）
        data[wz]["WuchongTeamChallenge"]["next"] = [w.STEP_TAIL]

    checks.append(
        _break_and_check(
            "② 真后继被吞（WuchongTeamChallenge 只剩 [JumpBack]SceneEnterWuchong）",
            _successor_swallowed,
            _prefix_failures,
        )
    )

    def _successor_swapped(data):
        # 真后继被换成**别的**节点：推进边方向错（不是缺失，是错），也必须抓
        data[wz]["WuchongNavRow"]["next"] = ["WuchongScrollList", "WuchongDetailFight", "WuchongNavLord", w.STEP_TAIL]

    checks.append(
        _break_and_check(
            "② 真后继里混进一个多余节点（WuchongNavRow 的 next 多一条 WuchongNavLord）",
            _successor_swapped,
            _prefix_failures,
        )
    )

    # ---- ③ SceneEnter 挪位 / 入口形状漂移 ----
    def _enter_first(data):
        data[wz]["WuchongNavLord"]["next"] = [
            "[JumpBack]SceneEnterWuchong",
            "WuchongNavJoss",
        ]

    checks.append(
        _break_and_check(
            "③ SceneEnter 挪到首位（DirectHit 永远命中 = 打转）", _enter_first, _enter_position_failures
        )
    )

    def _enter_next(data):
        data[scene][w.SCENE_ENTER]["next"] = ["WuchongInLordList", "WuchongGuardChain"]

    checks.append(
        _break_and_check(
            f"③ {w.SCENE_ENTER}.next 少了验证器/归位（入口形状漂移）", _enter_next, _enter_position_failures
        )
    )

    # ---- ③b 中继回指 ----
    def _relay_backref(data):
        data[scene][w.SCENE_GUARD_CHAIN]["next"].insert(0, w.SCENE_ENTER)

    checks.append(
        _break_and_check(
            "③b 中继回指 SceneEnterWuchong（DirectHit ↔ DirectHit 自环）",
            _relay_backref,
            _relay_backref_failures,
        )
    )

    # ---- ④ 中继成员 / 顺序 ----
    def _relay_missing(data):
        nxt = data[scene][w.SCENE_GUARD_CHAIN]["next"]
        nxt.remove("[JumpBack]PubReturnHome")

    checks.append(
        _break_and_check(
            "④ 中继漏一个异常节点（拿掉 [JumpBack]PubReturnHome）",
            _relay_missing,
            _relay_member_failures,
        )
    )

    def _relay_reorder(data):
        nxt = data[scene][w.SCENE_GUARD_CHAIN]["next"]
        i = nxt.index(w.CONTINUE_GUARD_NODE)
        j = nxt.index(f"[JumpBack]{w.CONTINUE_NODE}")
        nxt[i], nxt[j] = nxt[j], nxt[i]

    checks.append(
        _break_and_check(
            "④ 中继顺序被换（续关上限闸排到点击之后 = 超限那一帧会先花一颗星导石）",
            _relay_reorder,
            _relay_member_failures,
        )
    )

    # ---- ⑥ 识别必须可终结（R1b 的核心教训）----
    # 这四条破坏实验**一个字节都不动 pipeline**：豁免表（scene.wuchong.IDEMPOTENT_UNSAFE）在真源里，
    # 故用命名空间里的假表跑同一个守卫 —— 破坏点单一、可归因。
    def _with_table(table):
        return lambda root: _idempotent_failures(root, wuchong=_fake_wuchong(IDEMPOTENT_UNSAFE=table))

    for node, why in (
        ("WuchongScrollList", "恒真 state 识别（R1b 同谋之一）"),
        ("WuchongNavJoss", "页签文字永远可见（R1b 另一个同谋）"),
    ):
        checks.append(
            _break_and_check(
                f"⑥ 给 {node} 去掉豁免（{why}）—— 未登记必须红",
                _noop,
                _with_table({k: v for k, v in w.IDEMPOTENT_UNSAFE.items() if k != node}),
            )
        )

    table_safe = dict(w.IDEMPOTENT_UNSAFE)
    table_safe["WuchongTeamChallenge"] = "（假理由：这个节点已经被静态证明可终结，赖在表里就是藏污纳垢）"
    checks.append(
        _break_and_check(
            "⑥ 把已证明可终结的节点塞进豁免表（豁免表不是藏污纳垢的地方）",
            _noop,
            _with_table(table_safe),
        )
    )

    table_short = dict(w.IDEMPOTENT_UNSAFE)
    table_short["WuchongRoomWait"] = "等待"
    checks.append(
        _break_and_check(
            "⑥ 豁免理由写成占位符（『等待』= 没说清为什么不会再命中）",
            _noop,
            _with_table(table_short),
        )
    )

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "wuchong-business-next-tail",
        "#103",
        "①R1b：21 个业务节点 next **不许为空**，且**末项逐字** == scene.wuchong.STEP_TAIL"
        "（[JumpBack]SceneEnterWuchong）、全文只出现一次 —— 末位兜底是「迷路了先确认我在哪一页」的唯一入口",
        probe_wuchong_business_next_tail,
    ),
    (
        "wuchong-business-next-prefix",
        "#103",
        "②R1b：业务 next 的**前缀**（末位之前）逐字 == FLOW_STEPS[i].next —— "
        "★真后继没被吞★（进度靠它；吞了就是 R1b：动作永不发生、枢纽反复派回本节点）；"
        "整串 == step_next()，LEGACY_NEXT 必须是 False",
        probe_wuchong_business_next_prefix,
    ),
    (
        "wuchong-recognition-terminates",
        "#103",
        "⑥R1b（本票核心教训）：**识别必须可终结** —— 证不出「动作成功后识别必然翻假」的业务节点"
        "（纯 state 识别 / 恒可见文字 / 动作不改判据 / raw 默认 __NONE__）必须登记进 "
        "scene.wuchong.IDEMPOTENT_UNSAFE 并写明理由；未登记 = 红；已证明可终结却还赖在表里也红",
        probe_wuchong_recognition_terminates,
    ),
    (
        "wuchong-scene-validators",
        "#103",
        "⑤场景接口层：7 个页面验证器 WuchongIn* 齐全、next == IN_NEXT（绝对口径 "
        "list(IN_NEXT) == [\"WuchongEntry\"]，★空 next = 任务流程终止★，不是「纯闸门」）、"
        "动作 DoNothing、识别 = wuchong_state 且 state 与 scene/wuchong.IN_STATES 逐字一致"
        "（并且是既有 state 节点用过的值，不发明新状态）；IN_NODES 键集 == 流程链节点集",
        probe_wuchong_scene_validators,
    ),
    (
        "wuchong-scene-enter-last",
        "#103",
        "③死循环守卫：SceneEnter* 出现在任何 next 里都必须是**最后一项**（DirectHit 永远命中，放前面 = "
        "后续候选永不评估 = 在接口层里打转）；接口层入口自身 DirectHit/DoNothing、"
        "next == SCENE_ENTER_NEXT、on_error 回枢纽",
        probe_wuchong_scene_enter_last,
    ),
    (
        "wuchong-guard-chain-no-backref",
        "#103",
        "③b 死循环守卫：中继 WuchongGuardChain 内部不得回指 SceneEnter* / 自身（DirectHit ↔ DirectHit = "
        "零成本自环：一秒几百帧、一次点击都没有）",
        probe_wuchong_guard_chain_no_backref,
    ),
    (
        "wuchong-guard-chain-members",
        "#103",
        "④中继成员 == scene.wuchong.FLOW_EXCEPTIONS（集合 + **顺序**逐项比对），末位是 WuchongGuardDone 且它 "
        "next=[]（★只有这个回跳闩允许空 next★）；中继/验证器/入口不得设 max_hit（#79：用尽即静默跳过）",
        probe_wuchong_guard_chain_members,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
