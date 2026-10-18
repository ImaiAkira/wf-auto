# -*- coding: utf-8 -*-
"""配置层 ↔ 磁盘产物 的**漂移校验**（ticket #7 / ADR-0001 的「校验」职责）。

ADR-0001：Python 场景配置是唯一真源，pipeline / interface JSON **不被清空、也不被
整体生成**。既然 JSON 里**仍有手写的链与判据**，校验就不是可选的 ——
「配置改了、JSON 没跟上」或「JSON 改了、配置没跟上」，离线套件都必须**变红**，
每条报告都必须**点名**出错的成员 / 规则（绝不说「mismatch」了事）。

本模块实现的校验（其余见文末「本票不校验什么」）：

1. :func:`option_drift`（GUI 目标选项，ticket #1 检查 1）
   —— 从 ``scene.options`` 派生的目标选项（39 个名字 + 每个成员的
   ``pipeline_override``）对照 ``assets/interface.json`` 选项「打哪个副本」里**手写**的
   case。名字增 / 删 / 改 / 换序，或 override（行名 OCR / ROI）漂移，都报红并点名成员。

2. :func:`recognition_drift`（页面判据 ↔ 它们抄自的 pipeline 节点，ticket #1 检查 2）
   —— ``scene/page_rules.py`` 的每条判据都**照抄**自某个 pipeline 节点（见
   :data:`PAGE_RULE_SOURCES`，如 ``SpecialOpenLord`` / ``SpecialTabLord`` /
   ``SpecialTabJoss`` / ``SpecialScrollList`` / ``SpecialChallenge`` /
   ``SpecialDetailGate`` / ``SpecialModeSolo`` / ``SpecialBonusNo`` / ``SpecialBattleWait``
   及其引用的战斗 HUD 公共叶子），外加 ``scene.options.TARGET_ROW_ROI`` ↔ 列表页行节点
   ``SpecialEnterBoss``。只要 pipeline 里**改了某个 OCR 串或 ROII**，对应规则就报红。

3. :func:`event_def_drift` + :func:`event_injection_drift`（事件层落地，ticket #10 / #18）
   —— #5/#8 声明并注入的 ``Pub*`` 事件组（含归位 ``PubReturnHome``）在 #16 之前**只写
   候选集、不写节点定义**，故注入的 ``[JumpBack]PubReturnHome`` 引用会**悬空**。#10 把
   节点定义与候选集都写进 pipeline 后，本模块接管这两条校验：
   事件层声明的每个节点定义必须在 pipeline 里**在场且判据一致**；#18 起每个流程节点的
   候选集必须是「**打断型前缀** + 原有后继（末位除外）+ **兜底型后缀** + 末位恢复点」
   的规范形，两类各有自己的位置（打断型在前、兜底型在后、末位是真正的恢复边），
   任一位置被挪动 / 缺失 / 混入多余事件引用都点名声明的节点报红。

4. :func:`chain_drift`（页面锚定链落地，ticket #10）
   —— #4 把领主战类流程表达为**页面锚定 + 显式后继**的链式拓扑，但 pipeline 长期是
   中心分派表（每个流程节点的 ``next`` 一律回 ``SpecialEntry``）。#10 把链的前驱后继
   写进 ``special_dungeon.json`` 后，本模块对照 :data:`CHAIN_SUCCESSORS`：每个
   页面锚定节点的显式后继必须等于「链上下一节点 + 枢纽兜底」。手改任一后继即红。

5. :func:`chain_page_interrupt_drift`（链上页面 ∩ 打断型事件 = ∅，ticket #27）
   —— 已是链上一步的页面不得同时作为打断型事件注入：同一页上前缀优先级更高，会抢在
   链上那一步之前命中并吃掉该帧（#26 真机实证：「结算」页被 ``PubResultContinue`` 抢走，
   链上的 ``SpecialResultContinue`` 从不执行、#22 的收工闸永不触发）。本检查遍历每个流程
   节点，凡「打断型 ``[JumpBack]`` 引用」与「裸的链上页面节点」指向同一页面即报红
   （同节点自引用豁免，见 :func:`chain_page_interrupt_drift`）。

6. :func:`chain_page_fallback_drift`（兜底判据不得只凭底部导航，ticket #29）
   —— 兜底事件（归位）的判据曾是 ``And(主城底导, 返回)``，而领主战列表页 / 详情页同样
   同时具备这两者 → 归位在**链上步骤页面**自匹配（#29 真机实证：目标行在屏幕外时兜底
   抢跑，滚动找行的 ``SpecialScrollList`` 永不执行）。本检查要求归位的判据带一条
   **页面范围判别叶**（叶子不全为 OCR）；只剩底部导航两叶即报红。真机帧级判定见
   ``tools/contract_hooks/hooks_29.py``。

7. :func:`lords_snapshot_drift`（领主战**账号快照** ↔ 难度事实真源，ticket #111）
   —— 「每个成员支持哪些难度」不再被当成关卡事实：``scene/lords.py`` 的 **M + 解锁链** 才是
   唯一真源，``scene/lord_battle`` 里那份逐成员难度已降级为**账号快照**
   （:data:`scene.lord_battle.ACCOUNT_SNAPSHOTS`，必须写明**账号 / 时间 / 帧**）。
   本检查断言两者**不冲突**：成员在花名册、每档 ∈ 词表、``len(快照) <= M``、链已知时
   ``快照 ⊆ 链``；外加花名册一致与 ``verified`` 证据路径存在性。

``expected`` 的比法是**子集**、``roi`` 的比法是**相等**（理由见 :func:`_compare_recognition`）：
页面判据是「这个画面算哪个页面」的**更窄**断言，允许比源节点更严格（例如「结算页」只认
``^继续$``，而公共节点 ``PubResultContinueText`` 同时还认 ``^OK$``）；但判据依赖的任一串
若在源节点上被**改动 / 删除**，或 ROI 被移动，就会被抓住。往源节点**新增**串不改变
「判据仍被源节点支撑」这一事实，故不判红。

全离线、只读：本模块**只读** ``assets/**``，绝不写盘；破坏实验（prove-red）在**临时副本**
上进行，见 ``tools/contract_hooks/hooks_7.py``。

------------------------------------------------------------------------------
仍未校验什么（如实列出，避免假装能比）
------------------------------------------------------------------------------

- **成员「当前可打哪几档」**（账号进度）：按 #1 的 2026-10-13 修订 + #106 的证伪，这个数是
  **账号状态**、运行时从列表页 ``通关数 N/M`` / 详情页逐行读数得到，``interface.json`` 也没有
  任何按成员区分的难度数据，故**不可比对**（不是漏了，是真没有来源）。
  #111 起能校验的只是**结构侧**：配置里那份逐成员难度必须是「写明账号 / 时间 / 帧」的
  **账号快照**，且与 ``scene/lords.py`` 的 M / 解锁链不冲突（见 :func:`lords_snapshot_drift`）。
- **枢纽 ``SpecialEntry.next`` 的完整顺序**：它仍是「事件 + 指挥官 + 种类分派器」的入口
  分派表（farm/raid/phantom 三条既有路径靠它接线，#9 守卫钉死其顺序）。本模块只要求它的
  候选集以事件组开头、且其后不再混入事件引用（第 3 条），**不比对**它后半段的业务节点
  顺序——那段不是页面锚定链。
- **页面锚定链的「恢复边」语义**：:data:`CHAIN_SUCCESSORS` 只钉「显式后继 + 枢纽兜底」
  这两段；枢纽兜底之后 hub 如何分派由入口分派表决定，不在此校验。

★本模块（#7）在 #10 之后接管了链与事件两条校验★：#7 原先把这两条明确留给了迁移票，
现在迁移票（#10）已把链与事件写进 pipeline，故校验到位（见 :func:`check_all`）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - 仅供类型标注
    from .config import FamilyConfig

# repo 内的相对路径（校验对象）。
INTERFACE_REL = "assets/interface.json"
PIPELINE_REL = "assets/resource/pipeline"

# 页面判据名 -> 它抄自的 (pipeline 文件名, 节点名)。
#
# 这是本票检查 2 的**唯一映射表**：改这里的人，等于在声明「这条判据抄自哪个节点」。
# 未登记的页面判据会让校验报红（逼调用方补来源，而不是静默不校验）。
PAGE_RULE_SOURCES: dict[str, tuple[str, str]] = {
    "主城": ("special_dungeon.json", "SpecialOpenLord"),
    "领主战列表页": ("special_dungeon.json", "SpecialScrollList"),
    "领主战页签": ("special_dungeon.json", "SpecialTabLord"),
    "降临讨伐页签": ("special_dungeon.json", "SpecialTabJoss"),
    "详情页": ("special_dungeon.json", "SpecialDetailGate"),
    "模式选择页": ("special_dungeon.json", "SpecialModeSolo"),
    "加成弹窗": ("special_dungeon.json", "SpecialBonusNo"),
    "编队页": ("special_dungeon.json", "SpecialChallenge"),
    # 战斗 HUD：判据抄自 SpecialBattleWait，后者的 And.all_of 引用 common.json 的
    # PubBattleTime / PubBattleScore（本模块会把引用解析到叶子再比）。
    "战斗HUD": ("special_dungeon.json", "SpecialBattleWait"),
    # 结算页：判据抄自 common.json 的 PubResultContinueText（页面判据有意取更窄的子集）。
    "结算页": ("common.json", "PubResultContinueText"),
}

# 目标行节点名（scene.options 的常量）——本条校验也对照 pipeline。
_TARGET_ROW_FILE = "special_dungeon.json"

# ---------------------------------------------------------------------------
# 页面锚定链（#4）在 pipeline 上的落点（#10 校验）。
#
# 映射依据：``scene.chain.build_chain`` 的**主路径**（步骤动作 → pipeline 流程节点）。
# 链上「页签·选目标行」这一步在 pipeline 里由 ``SpecialEnterBoss``（按行名 OCR 点行）
# 承担，而「列表页·切页签」由 ``SpecialTabLord``/``SpecialTabJoss``（点 tab）承担 ——
# 因此这里是**按步骤动作**映射，不是按页面名一一映射（页面名 → 节点见
# ``PAGE_RULE_SOURCES``）。子族差异（领主战 → 降临讨伐）由选项覆盖关掉错的那一个 tab
# 节点表达，故 ``SpecialOpenLord`` 同时列出两个 tab 候选（顺序 = 链声明的先后）。
#
# 每个节点的显式后继 = ``CHAIN_SUCCESSORS[node] + [CHAIN_HUB]``：链的下一节点在前，
# 枢纽 ``SpecialEntry`` 作为**显式恢复边**殿后（ADR-0002 的后果：链式拓扑必须补回
# 中心枢纽的自恢复）。``SpecialEntry`` 不在映射里 —— 它是入口分派表，不是页面锚点。
# ---------------------------------------------------------------------------
CHAIN_FILE = "special_dungeon.json"
CHAIN_HUB = "SpecialEntry"

CHAIN_SUCCESSORS: dict[str, list[str]] = {
    "SpecialOpenLord": ["SpecialTabLord", "SpecialTabJoss"],
    # ★#29★ 列表页两个页签节点在「选目标行」之后必须接【滚动找行】(SpecialScrollList)，
    #   再接枢纽兜底 —— 否则目标行在屏幕外时没有路去滚列表，只会被兜底归位带回主城
    #   （15 个领主战成员只有首屏 3 个能打到）。滚动节点本身没有页面锚点后继，故只作为
    #   【后继值】出现，不作为本表的键（它的 next 仍由 check(4)/event_injection_drift 约束）。
    "SpecialTabLord": ["SpecialEnterBoss", "SpecialScrollList"],
    "SpecialTabJoss": ["SpecialEnterBoss", "SpecialScrollList"],
    "SpecialEnterBoss": ["SpecialFightTargetRow"],
    "SpecialFightTargetRow": ["SpecialModeSolo"],
    "SpecialModeSolo": ["SpecialBonusNo"],
    "SpecialBonusNo": ["SpecialChallenge"],
    "SpecialChallenge": ["SpecialBattleWait"],
    "SpecialBattleWait": ["SpecialResultContinue"],
    "SpecialResultContinue": [],
}


# ---------------------------------------------------------------------------
# JSONC（带 // 与 /* */ 注释）解析 —— 复用 validate_schema.py 同款状态机，自足一份，
# 这样 scene.drift 在临时副本里也能独立解析 assets，不依赖 tools/。
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    """移除 JSONC 注释，保持 JSON 结构与行号。"""
    out: list[str] = []
    state = 0  # 0=正常 1=字符串 2=转义
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i : i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
                if i < n:
                    out.append("\n")
                    i += 1
            elif text[i : i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i : i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> object:
    """读一个 JSONC 文件并解析；失败时点名文件（绝不静默）。"""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(_strip_jsonc(text))
    except json.JSONDecodeError as exc:  # pragma: no cover - 坏 JSON 由套件报红
        raise ValueError(f"无法解析 JSONC: {path}：{exc}") from exc


def default_repo_root() -> Path:
    """从本文件向上找到含 ``assets/interface.json`` 的目录（真实仓库根）。

    注意：prove-red 会在**临时副本**里导入本模块，那时 ``__file__`` 指向副本；
    因此需要真实根时，调用方（``hooks_7``）**显式传** ``repo_root``，不走本函数。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / INTERFACE_REL).is_file():
            return parent
    raise FileNotFoundError(f"找不到仓库根（含 {INTERFACE_REL}）")


# ---------------------------------------------------------------------------
# 检查 1：GUI 目标选项
# ---------------------------------------------------------------------------
def option_drift(cfg: "FamilyConfig", interface_path: Path) -> list[str]:
    """配置派生的「打哪个副本」选项 vs ``interface.json`` 手写选项。返回漂移列表。

    比对两样东西，任一不符都点名成员：

    * **case 名字集合与顺序**（增 / 删 / 改名 / 换序）；
    * **每个 case 的 ``pipeline_override``**（行名 OCR / ROI / 子族覆盖是否与派生一致）。
    """
    from .options import OPTION_NAME, derive_target_options

    data = _load_jsonc(Path(interface_path))
    option = data.get("option") if isinstance(data, dict) else None
    if not isinstance(option, dict) or OPTION_NAME not in option:
        return [
            f"选项漂移：interface.json 里找不到顶层 option「{OPTION_NAME}」"
            f"（GUI 目标选项被删 / 改名 / 挪走，配置派生的 N 个成员无处落地）"
        ]
    block = option[OPTION_NAME]
    cases = block.get("cases") if isinstance(block, dict) else None
    if not isinstance(cases, list):
        return [f"选项漂移：option「{OPTION_NAME}」没有 cases 列表（结构被改）"]

    actual = [c.get("name") if isinstance(c, dict) else None for c in cases]
    expected_cases = derive_target_options(cfg)
    expected = [c["name"] for c in expected_cases]

    msgs: list[str] = []
    exp_set = set(expected)
    act_set = set(actual)
    for name in expected:
        if name not in act_set:
            msgs.append(
                f"选项漂移：配置声明了成员 {name!r}，但 interface.json 选项"
                f"「{OPTION_NAME}」里没有它（配置改了、JSON 没跟上）"
            )
    for name in actual:
        if name not in exp_set:
            msgs.append(
                f"选项漂移：interface.json 选项「{OPTION_NAME}」里有 {name!r}，"
                f"但配置没有声明该成员（JSON 改了、配置没跟上）"
            )
    if not msgs and actual != expected:
        msgs.append(
            f"选项漂移：成员集合一致但顺序不同（配置={expected[:4]}… vs JSON={actual[:4]}…）"
        )

    # 每个 case 的 pipeline_override 必须与派生结果逐字节一致（名字相同才比）。
    actual_by_name = {
        c.get("name"): c for c in cases if isinstance(c, dict) and c.get("name") is not None
    }
    for exp_case in expected_cases:
        name = exp_case["name"]
        act_case = actual_by_name.get(name)
        if act_case is None:
            continue  # 名字漂移已在上面点过名
        if act_case.get("pipeline_override") != exp_case["pipeline_override"]:
            msgs.append(
                f"选项漂移：成员 {name!r} 的 pipeline_override 与配置派生的不一致："
                f"JSON={act_case.get('pipeline_override')!r} "
                f"配置={exp_case['pipeline_override']!r}"
            )
    return msgs


# ---------------------------------------------------------------------------
# 检查 1b：GUI 难度选项（#39）
# ---------------------------------------------------------------------------
def difficulty_option_drift(interface_path: Path) -> list[str]:
    """配置派生的「打哪个难度」选项 vs ``interface.json`` 手写选项。返回漂移列表。

    「有哪些难度」是全局输入、真源在 ``scene.config.DIFFICULTIES``；GUI 的「打哪个难度」
    是它的投影，必须逐项一致（#39：过去手写的这份**漏了 ``地狱级``**）。比对：

    * **case 名字集合与顺序**（增 / 删 / 改名 / 换序）；
    * **每个 case 的 ``pipeline_override``**（难度行名正则是否与派生一致，带 $ 锚定）。
    """
    from .options import DIFFICULTY_OPTION_NAME, derive_difficulty_block

    data = _load_jsonc(Path(interface_path))
    option = data.get("option") if isinstance(data, dict) else None
    if not isinstance(option, dict) or DIFFICULTY_OPTION_NAME not in option:
        return [
            f"难度选项漂移：interface.json 里找不到顶层 option「{DIFFICULTY_OPTION_NAME}」"
            f"（难度词表无处落地）"
        ]
    block = option[DIFFICULTY_OPTION_NAME]
    if not isinstance(block, dict):
        return [f"难度选项漂移：option「{DIFFICULTY_OPTION_NAME}」不是对象（结构被改）"]
    cases = block.get("cases")
    if not isinstance(cases, list):
        return [f"难度选项漂移：option「{DIFFICULTY_OPTION_NAME}」没有 cases 列表（结构被改）"]

    expected_block = derive_difficulty_block()
    expected_cases = expected_block["cases"]
    expected = [c["name"] for c in expected_cases]
    actual = [c.get("name") if isinstance(c, dict) else None for c in cases]

    msgs: list[str] = []
    if block.get("type") != "select":
        msgs.append(
            f"难度选项漂移：option「{DIFFICULTY_OPTION_NAME}」的 type={block.get('type')!r} 不是 select"
        )
    exp_set, act_set = set(expected), set(actual)
    for name in expected:
        if name not in act_set:
            msgs.append(
                f"难度选项漂移：配置词表里有难度 {name!r}，但 interface.json 选项"
                f"「{DIFFICULTY_OPTION_NAME}」里没有它（配置改了、JSON 没跟上）"
            )
    for name in actual:
        if name not in exp_set:
            msgs.append(
                f"难度选项漂移：interface.json 选项「{DIFFICULTY_OPTION_NAME}」里有 {name!r}，"
                f"但配置词表没有这一档（JSON 改了、配置没跟上）"
            )
    if not msgs and actual != expected:
        msgs.append(
            f"难度选项漂移：难度集合一致但顺序不同（配置={expected} vs JSON={actual}）"
        )
    if block.get("default_case") not in exp_set:
        msgs.append(
            f"难度选项漂移：option「{DIFFICULTY_OPTION_NAME}」的 default_case="
            f"{block.get('default_case')!r} 不在难度词表 {expected} 内"
        )

    actual_by_name = {
        c.get("name"): c for c in cases if isinstance(c, dict) and c.get("name") is not None
    }
    for exp_case in expected_cases:
        name = exp_case["name"]
        act_case = actual_by_name.get(name)
        if act_case is None:
            continue  # 名字漂移已在上面点过名
        if act_case.get("pipeline_override") != exp_case["pipeline_override"]:
            msgs.append(
                f"难度选项漂移：难度 {name!r} 的 pipeline_override 与配置派生的不一致："
                f"JSON={act_case.get('pipeline_override')!r} 配置={exp_case['pipeline_override']!r}"
            )
    return msgs


# ---------------------------------------------------------------------------
# 检查 1c：GUI 迷宫选项（域 + 行名，ticket #54 —— 修订 #52 的域+元素模型）
#
# ★#54★：迷宫按「域」选、每个域是一张**异质行列表**；目标 = 【域 + 行名】，行名里自含
# 【元素】/Lv../层（元素**不是**独立轴）。两个 option 都是**从 scene.config 的真源派生**
# 的投影（ADR-0001）：手改任一 case 名 / 换序 / 改 override 都要点名报红。
def _maze_block_drift(interface_path: Path, name: str, expected_block: dict) -> list[str]:
    """一个迷宫 option 块 vs interface.json：集合 / 顺序 / default_case / override 逐项比对。"""
    data = _load_jsonc(Path(interface_path))
    option = data.get("option") if isinstance(data, dict) else None
    if not isinstance(option, dict) or name not in option:
        return [
            f"迷宫选项漂移：interface.json 里找不到顶层 option「{name}」"
            f"（GUI 迷宫选项被删 / 改名 / 挪走，配置派生的词表无处落地）"
        ]
    block = option[name]
    if not isinstance(block, dict):
        return [f"迷宫选项漂移：option「{name}」不是对象（结构被改）"]
    cases = block.get("cases")
    if not isinstance(cases, list):
        return [f"迷宫选项漂移：option「{name}」没有 cases 列表（结构被改）"]

    expected_cases = expected_block["cases"]
    expected = [c["name"] for c in expected_cases]
    actual = [c.get("name") if isinstance(c, dict) else None for c in cases]

    msgs: list[str] = []
    if block.get("type") != "select":
        msgs.append(f"迷宫选项漂移：option「{name}」的 type={block.get('type')!r} 不是 select")
    exp_set, act_set = set(expected), set(actual)
    for n in expected:
        if n not in act_set:
            msgs.append(
                f"迷宫选项漂移：配置词表里有 {n!r}，但 interface.json 选项「{name}」里没有它"
                f"（配置改了、JSON 没跟上）"
            )
    for n in actual:
        if n not in exp_set:
            msgs.append(
                f"迷宫选项漂移：interface.json 选项「{name}」里有 {n!r}，但配置词表没有它"
                f"（JSON 改了、配置没跟上）"
            )
    if not msgs and actual != expected:
        msgs.append(f"迷宫选项漂移：{name} 集合一致但顺序不同（配置={expected} vs JSON={actual}）")
    if block.get("default_case") not in exp_set:
        msgs.append(
            f"迷宫选项漂移：option「{name}」的 default_case="
            f"{block.get('default_case')!r} 不在配置词表 {expected} 内"
        )

    actual_by_name = {
        c.get("name"): c for c in cases if isinstance(c, dict) and c.get("name") is not None
    }
    for exp_case in expected_cases:
        n = exp_case["name"]
        act_case = actual_by_name.get(n)
        if act_case is None:
            continue  # 名字漂移已在上面点过名
        if act_case.get("pipeline_override") != exp_case["pipeline_override"]:
            msgs.append(
                f"迷宫选项漂移：{n!r} 的 pipeline_override 与配置派生的不一致："
                f"JSON={act_case.get('pipeline_override')!r} 配置={exp_case['pipeline_override']!r}"
            )
    return msgs


def maze_option_drift(interface_path: Path) -> list[str]:
    """迷宫「域 / 行名」两个 GUI 选项 vs 配置派生的真源（#54，修订 #52）。返回漂移列表。"""
    from .options import (
        MAZE_DOMAIN_OPTION_NAME,
        MAZE_ROW_OPTION_NAME,
        derive_maze_domain_block,
        derive_maze_row_block,
    )

    msgs: list[str] = []
    msgs.extend(_maze_block_drift(interface_path, MAZE_DOMAIN_OPTION_NAME, derive_maze_domain_block()))
    msgs.extend(_maze_block_drift(interface_path, MAZE_ROW_OPTION_NAME, derive_maze_row_block()))
    return msgs


# ---------------------------------------------------------------------------
# 检查 2：页面判据 ↔ pipeline 节点
# ---------------------------------------------------------------------------
def load_pipelines(pipeline_dir: Path) -> dict[str, dict]:
    """加载目录下所有 ``*.json``（JSONC），返回 ``{文件名: 顶层对象}``。"""
    files: dict[str, dict] = {}
    for path in sorted(pipeline_dir.glob("*.json")):
        data = _load_jsonc(path)
        files[path.name] = data if isinstance(data, dict) else {}
    return files


def _resolve_recognition(name: str, files: dict[str, dict]) -> dict | None:
    """按节点名取 recognition（跨文件查找）；找不到返回 None。"""
    for data in files.values():
        node = data.get(name)
        if isinstance(node, dict):
            rec = node.get("recognition")
            return rec if isinstance(rec, dict) else {}
    return None


def _compare_recognition(
    rule: str,
    page_rec: dict,
    src_rec: dict,
    where: str,
    resolve: Callable[[str], dict | None],
) -> list[str]:
    """把一条页面判据的 recognition 与它抄自的源识别对照，返回漂移列表。

    语义（见模块 docstring 的诚实说明）：

    * ``type`` 必须相同；
    * OCR：判据的每个 ``expected`` 串都必须仍在源节点的 ``expected`` 里（**子集**），
      且 ``roi`` **完全相等**；
    * And：逐叶子对照（源叶子若是节点名，先解析成 recognition 再比）；
    * 其它类型：报红（校验器未覆盖的类型不许静默通过）。
    """
    if page_rec.get("type") != src_rec.get("type"):
        return [
            f"页面判据漂移：规则「{rule}」的 recognition.type "
            f"{page_rec.get('type')!r} != {where} 的 {src_rec.get('type')!r}"
        ]
    kind = page_rec.get("type")
    if kind == "OCR":
        return _compare_ocr(rule, page_rec, src_rec, where)
    if kind == "And":
        page_leaves = (page_rec.get("param") or {}).get("all_of") or []
        src_leaves = (src_rec.get("param") or {}).get("all_of") or []
        if len(page_leaves) != len(src_leaves):
            return [
                f"页面判据漂移：规则「{rule}」的 And 叶子数 {len(page_leaves)} "
                f"!= {where} 的 {len(src_leaves)}"
            ]
        msgs: list[str] = []
        for i, (a, b) in enumerate(zip(page_leaves, src_leaves)):
            b_rec = resolve(b) if isinstance(b, str) else b
            if not isinstance(b_rec, dict):
                msgs.append(
                    f"页面判据漂移：规则「{rule}」的 {where}:all_of[{i}] 引用了未知节点 {b!r}"
                )
                continue
            msgs.extend(
                _compare_recognition(rule, a, b_rec, f"{where}:all_of[{i}]", resolve)
            )
        return msgs
    return [
        f"页面判据漂移：规则「{rule}」的 recognition.type {kind!r} 暂未被校验器覆盖"
        f"（{where}）；请扩展 scene.drift 或登记来源，勿静默放过"
    ]


def _compare_ocr(rule: str, page_rec: dict, src_rec: dict, where: str) -> list[str]:
    msgs: list[str] = []
    page_param = page_rec.get("param") or {}
    src_param = src_rec.get("param") or {}
    page_exp = page_param.get("expected") or []
    src_exp = src_param.get("expected") or []
    for pat in page_exp:
        if pat not in src_exp:
            msgs.append(
                f"页面判据漂移：规则「{rule}」断言能认出 {pat!r}，但 {where} "
                f"已不识别它（现为 {src_exp}）"
            )
    page_roi = page_param.get("roi")
    src_roi = src_param.get("roi")
    if page_roi != src_roi:
        msgs.append(
            f"页面判据漂移：规则「{rule}」的 ROI {page_roi} 与 {where} 的 {src_roi} 不一致"
        )
    return msgs


def recognition_drift(repo_root: Path) -> list[str]:
    """页面判据 ↔ pipeline 节点（+ 目标行 ROI）的漂移。返回漂移列表。"""
    from .options import TARGET_ROW_NODE, TARGET_ROW_ROI
    from .page_rules import page_rules

    files = load_pipelines(Path(repo_root) / PIPELINE_REL)

    def resolve(name: str) -> dict | None:
        return _resolve_recognition(name, files)

    msgs: list[str] = []
    for rule_obj in page_rules():
        rule = rule_obj.name
        source = PAGE_RULE_SOURCES.get(rule)
        if source is None:
            msgs.append(
                f"页面判据漂移：规则「{rule}」在 scene.drift.PAGE_RULE_SOURCES 里没有登记来源，"
                f"无法与 pipeline 对照"
            )
            continue
        fname, node_name = source
        data = files.get(fname)
        if data is None:
            msgs.append(
                f"页面判据漂移：规则「{rule}」的来源文件 {fname} 不存在"
                f"（无法对照节点 {node_name}）"
            )
            continue
        node = data.get(node_name)
        if not isinstance(node, dict) or not isinstance(node.get("recognition"), dict):
            msgs.append(
                f"页面判据漂移：规则「{rule}」抄自的节点 {fname}::{node_name} 不存在或没有 recognition"
            )
            continue
        msgs.extend(
            _compare_recognition(
                rule,
                rule_obj.recognition,
                node["recognition"],
                f"{fname}::{node_name}",
                resolve,
            )
        )

    # 目标行节点：scene.options.TARGET_ROW_ROI 必须等于 SpecialEnterBoss 的 roi。
    sd = files.get(_TARGET_ROW_FILE)
    row = sd.get(TARGET_ROW_NODE) if isinstance(sd, dict) else None
    row_rec = row.get("recognition") if isinstance(row, dict) else None
    if not isinstance(row_rec, dict):
        msgs.append(
            f"目标行漂移：{_TARGET_ROW_FILE}::{TARGET_ROW_NODE} 不存在或没有 recognition"
        )
    else:
        src_roi = (row_rec.get("param") or {}).get("roi")
        if list(TARGET_ROW_ROI) != src_roi:
            msgs.append(
                f"目标行漂移：scene.options.TARGET_ROW_ROI {list(TARGET_ROW_ROI)} 与 "
                f"{_TARGET_ROW_FILE}::{TARGET_ROW_NODE} 的 roi {src_roi} 不一致"
            )
    return msgs


# ---------------------------------------------------------------------------
# 检查 3：事件层落地（节点定义 + 幂等注入的候选集）—— #10
# ---------------------------------------------------------------------------
def event_def_drift(repo_root: Path) -> list[str]:
    """事件层声明的节点定义是否都在 pipeline 里在场、且判据一致。

    #16 的 ``apply`` 只写候选集不写节点定义，于是注入的 ``[JumpBack]PubReturnHome``
    引用会**悬空**（#10 前置实测确认）。本检查把「事件层声明的每个节点定义」
    （``scene.events.EVENT_NODE_DEFS``，含 ``PubReturnHome``）与 pipeline 对照：
    缺定义 / 判据漂移都点名报红。
    """
    from .events import EVENT_NODE_DEFS

    files = load_pipelines(Path(repo_root) / PIPELINE_REL)
    msgs: list[str] = []
    for name, spec in EVENT_NODE_DEFS.items():
        found = _resolve_recognition(name, files)
        if found is None:
            msgs.append(
                f"事件节点漂移：事件层声明的节点 {name!r} 在 pipeline 里没有定义"
                f"（注入的 [JumpBack]{name} 引用会悬空 —— 请把节点定义写进 pipeline）"
            )
            continue
        expected = spec.get("recognition")
        if found != expected:
            msgs.append(
                f"事件节点漂移：{name!r} 的 recognition {found!r} 与事件层声明的 "
                f"{expected!r} 不一致"
            )
    return msgs


def event_injection_drift(repo_root: Path) -> list[str]:
    """``special_dungeon.json`` 每个流程节点的候选集必须是「两类事件、两种位置」（#18）。

    #10 的注入是**纯行插入**（不重渲染数组、不动原文一个字节，见 ``scene.apply`` 的
    docstring）。#18 把事件分成两类、位置相反，本检查据此收紧为**规范形**：

    ``next = [打断型前缀] + [原有后继…（最后一个除外）] + [兜底型后缀] + [最后一个原有后继]``

    * **打断型前缀**：``next[:len(interrupt_refs)]`` 必须 == ``scene.events.interrupt_refs()``
      （九类异常，顺序即注入顺序）—— 没注入 / 被挪走 / 被换序，红；
    * **兜底型后缀**：``scene.events.fallback_refs()``（归位）必须恰好作为
      「最后一个原有后继（DirectHit 恢复边 / 终点）」**之前**的连续块出现 —— 归位被放回
      前缀、或挪到末位、或缺失，红；
    * **其后不得再混入任何事件引用**（重复的旧手写候选残留，或手塞一个中间事件引用），红；
    * **末位（恢复点）不得是事件引用**（DirectHit 恢复边必须是该节点真正的终点），红。

    事件层自带节点（``SpecialBonusNo`` / ``SpecialRecruitOpen`` 等）不注入自身，跳过。
    """
    from .events import EVENTS, fallback_refs, interrupt_refs

    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    all_refs = set(prefix) | set(suffix)
    own = {n for e in EVENTS for n in e.nodes}

    files = load_pipelines(Path(repo_root) / PIPELINE_REL)
    data = files.get(CHAIN_FILE)
    msgs: list[str] = []
    if not isinstance(data, dict):
        return [f"事件注入漂移：找不到 {CHAIN_FILE}（无法校验事件组候选集）"]

    for name, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("next"):
            continue
        if name in own:
            continue
        nxt = spec["next"]

        # (1) 打断型必须在最前。
        if nxt[: len(prefix)] != prefix:
            msgs.append(
                f"事件注入漂移：{CHAIN_FILE}::{name} 的候选集没有以打断型事件组开头"
                f"（前缀={prefix[:2]}…；实际={nxt[:3]}…）"
            )
            continue
        rest = nxt[len(prefix):]
        if not rest:
            msgs.append(f"事件注入漂移：{CHAIN_FILE}::{name} 只有事件前缀、没有原有后继")
            continue

        # (2) 末位是恢复边 / 终点，不得是事件引用。
        if rest[-1] in all_refs:
            msgs.append(
                f"事件注入漂移：{CHAIN_FILE}::{name} 的候选集末位 {rest[-1]!r} 是事件引用"
                f"（末位应是该节点真正的 DirectHit 恢复边 / 终点）"
            )
            continue
        mid = rest[:-1]

        # (3) 兜底型必须恰好是「末位之前」的连续块。
        if suffix:
            if len(mid) < len(suffix) or mid[-len(suffix):] != suffix:
                msgs.append(
                    f"事件注入漂移：{CHAIN_FILE}::{name} 的兜底型事件 {suffix} 不在后缀位置"
                    f"（应在最后一个原有后继之前；实际候选集={nxt}）"
                )
                continue
            body = mid[: -len(suffix)]
        else:
            body = mid

        # (4) 其余位置不得再混入任何事件引用。
        stray = [x for x in body if x in all_refs]
        if stray:
            msgs.append(
                f"事件注入漂移：{CHAIN_FILE}::{name} 的事件组之后又混入了事件引用 {stray}"
                f"（事件引用只应作为前缀 + 末位前后缀各出现一次）"
            )
    return msgs


# ---------------------------------------------------------------------------
# 检查 4：页面锚定链落地（显式后继 + 枢纽兜底）—— #10
# ---------------------------------------------------------------------------
def chain_drift(repo_root: Path) -> list[str]:
    """领主战类页面锚定节点在 pipeline 上的显式后继 vs :data:`CHAIN_SUCCESSORS`。

    每个页面锚定流程节点的候选集，剥掉注入的事件引用后，必须恰好等于
    ``CHAIN_SUCCESSORS[node] + [CHAIN_HUB]``（链的显式后继在前、枢纽兜底在后）。
    手改任一后继 / 删掉枢纽兜底 / 锚点节点被删，都点名报红。
    """
    from .events import event_refs

    ref_set = set(event_refs())
    files = load_pipelines(Path(repo_root) / PIPELINE_REL)
    data = files.get(CHAIN_FILE)
    msgs: list[str] = []
    if not isinstance(data, dict):
        return [f"链漂移：找不到 {CHAIN_FILE}（无法校验页面锚定链）"]

    for node, successors in CHAIN_SUCCESSORS.items():
        spec = data.get(node)
        if not isinstance(spec, dict) or not isinstance(spec.get("next"), list):
            msgs.append(f"链漂移：{CHAIN_FILE}::{node} 不存在或没有 next 候选集（链上的锚点被删）")
            continue
        rest = [x for x in spec["next"] if x not in ref_set]
        expected = [*successors, CHAIN_HUB]
        if rest != expected:
            msgs.append(
                f"链漂移：{CHAIN_FILE}::{node} 的显式后继应为 {expected}"
                f"（scene.chain 的页面锚定链 + 枢纽兜底），实际 {rest}"
            )
    return msgs


# ---------------------------------------------------------------------------
# 检查 5：链上页面 ∩ 打断型事件 = ∅（#27）
#
# 机制（#26 真机实证）：``SpecialEntry.next`` 与每个流程节点的**前缀**里有
# ``[JumpBack]PubResultContinue`` / ``[JumpBack]PubQuestResult``（被注入的「结算」
# 打断型事件），而链上「结算」这一步是 ``SpecialResultContinue``。结算帧一到，前缀的
# ``PubResultContinue`` 先命中并**吃掉这一帧** → ``[JumpBack]`` 回当前节点重扫 → 链上的
# 结算节点**从未被评估**（#22 的收工闸挂在那里，故永不执行）。
#
# 守卫：遍历 ``special_dungeon.json`` 每个流程节点，若候选集里同时有
#   * 一个 ``[JumpBack]X`` 引用（打断型注入），与
#   * 一个**裸的链上页面节点** ``Y``（``CHAIN_SUCCESSORS``，链的一步），
# 且 ``X`` 与 ``Y`` **指向同一页面**（``X`` 的识别引用了该页面的判据来源节点，或就是它），
# 则 ``X`` 会在该页上抢在 ``Y`` 之前命中 → 链上的那一步被遮蔽 → 报红并点名。
#
# 同一节点的 ``X == Y``（例如 ``[JumpBack]SpecialBonusNo`` 与裸 ``SpecialBonusNo``）不算
# 冲突：链的顺序已由同一执行体承载，注入与链步不是两条路，不存在遮蔽。
# ---------------------------------------------------------------------------
def _recognition_refs(rec: object) -> set[str]:
    """一条 recognition 里以【节点名】形式引用的子识别（``all_of`` / ``any_of`` 的字符串叶子）。"""
    refs: set[str] = set()
    if isinstance(rec, dict):
        param = rec.get("param")
        if isinstance(param, dict):
            for key in ("all_of", "any_of"):
                for leaf in param.get(key) or []:
                    if isinstance(leaf, str):
                        refs.add(leaf)
                    else:
                        refs |= _recognition_refs(leaf)
        for key, value in rec.items():
            if key == "param":
                continue
            if isinstance(value, (dict, list)):
                refs |= _recognition_refs(value)
    elif isinstance(rec, list):
        for value in rec:
            refs |= _recognition_refs(value)
    return refs


def _node_pages(files: dict[str, dict]) -> dict[str, set[str]]:
    """pipeline 节点 → 它「认得出」的链上页面（与页面判据同一份：来源节点或其引用者）。"""
    node_pages: dict[str, set[str]] = {}
    for page, (_fname, src) in PAGE_RULE_SOURCES.items():
        node_pages.setdefault(src, set()).add(page)
    for data in files.values():
        if not isinstance(data, dict):
            continue
        for name, node in data.items():
            if not isinstance(node, dict):
                continue
            refs = _recognition_refs(node.get("recognition"))
            for page, (_fname, src) in PAGE_RULE_SOURCES.items():
                if src in refs:
                    node_pages.setdefault(name, set()).add(page)
    return node_pages


def chain_page_interrupt_drift(repo_root: Path) -> list[str]:
    """链上页面不得再被**打断型事件前缀**遮蔽（#27）。返回冲突列表（空 = 通过）。

    见本段上方说明；每条消息点名节点 / 页面 / 抢跑引用。
    """
    files = load_pipelines(Path(repo_root) / PIPELINE_REL)
    data = files.get(CHAIN_FILE)
    if not isinstance(data, dict):
        return [f"链上页面守卫：找不到 {CHAIN_FILE}（无法校验链上页面 ∩ 打断型事件）"]

    node_pages = _node_pages(files)
    chain_steps = set(CHAIN_SUCCESSORS)
    jump = "[JumpBack]"

    msgs: list[str] = []
    for name, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("next"):
            continue
        nxt = spec["next"]
        for ref in nxt:
            if not isinstance(ref, str) or not ref.startswith(jump):
                continue
            intr = ref[len(jump):]
            for other in nxt:
                if not isinstance(other, str) or other == ref:
                    continue
                step = other[len(jump):] if other.startswith(jump) else other
                if step not in chain_steps or step == intr:
                    continue
                shared = node_pages.get(intr, set()) & node_pages.get(step, set())
                if shared:
                    pages = "、".join(sorted(shared))
                    msgs.append(
                        f"链上页面遮蔽：{CHAIN_FILE}::{name}.next 的 {ref!r} 会在页面「{pages}」上"
                        f"抢在链上节点 {other!r} 之前命中（链上这一步永不执行）——"
                        f"链上已有的页面不得同时作为打断型事件注入（#27）"
                    )
    return msgs


# ---------------------------------------------------------------------------
# 检查 6：兜底型事件的判据不得自匹配【链上步骤页面】（#29）
#
# 机制（#29 真机实证）：归位（兜底型）的判据曾是 And(主城底导, 返回左下)，而领主战
# 列表页 / 详情页同样同时具备这两者 → 归位在这些链上步骤页面上**自匹配**。因它的注入
# 位置是兜底后缀（紧跟 SpecialEnterBoss），目标行在屏幕外时 SpecialEnterBoss 不命中 →
# 兜底归位抢跑 → 点主城 → 回主城 → 枢纽重进；而滚动找行的 SpecialScrollList 永不执行
# → 15 个领主战成员只有首屏 3 个能打到、其余循环到超时。
#
# 守卫（结构层）：兜底事件的判据必须带一条【页面范围判别叶】—— 不能只是底部导航的两个
# OCR 叶（「有主城底导 + 有返回」= 半个游戏的子页面都成立）。若归位 recognition 的 And
# 叶子（递归）**全是 OCR**，即视为「仅凭底部导航」→ 报红并点名。
# 真机帧级判定见 ``tools/contract_hooks/hooks_29.py``（把真实帧的 OCR / 橙色像素喂进判据）。
# ---------------------------------------------------------------------------
def _leaf_recognition_types(rec: object, resolve: Callable[[str], dict | None]) -> list[str]:
    """展开一条 recognition 的叶子类型（And/Or 递归；字符串叶子先解析成子识别）。"""
    if not isinstance(rec, dict):
        return []
    kind = rec.get("type", "DirectHit")
    if kind in ("And", "Or"):
        key = "all_of" if kind == "And" else "any_of"
        types: list[str] = []
        for leaf in (rec.get("param") or {}).get(key) or []:
            sub = resolve(leaf) if isinstance(leaf, str) else leaf
            types.extend(_leaf_recognition_types(sub, resolve))
        return types
    return [kind]


def chain_page_fallback_drift(repo_root: Path) -> list[str]:
    """兜底事件（归位）的判据不得只凭底部导航 —— 否则会在链上步骤页面自匹配（#29）。

    返回冲突列表（空 = 通过）。判据取 ``pipeline`` 里归位的 recognition（与
    ``scene.events.RETURN_HOME_NODE_SPEC`` 的一致性由 :func:`event_def_drift` 把守）。
    """
    from .events import RETURN_HOME_NODE_NAME, RETURN_HOME_NODE_SPEC

    files = load_pipelines(Path(repo_root) / PIPELINE_REL)

    def resolve(name: str) -> dict | None:
        return _resolve_recognition(name, files)

    rec = resolve(RETURN_HOME_NODE_NAME)
    if rec is None:
        rec = RETURN_HOME_NODE_SPEC.get("recognition")
    msgs: list[str] = []
    if not isinstance(rec, dict) or rec.get("type") != "And":
        msgs.append(
            f"兜底事件自匹配：{RETURN_HOME_NODE_NAME} 的判据不是 And（无法表达多段范围）—— 实际 {rec!r}"
        )
        return msgs

    leaves = (rec.get("param") or {}).get("all_of") or []
    if len(leaves) < 3:
        msgs.append(
            f"兜底事件自匹配：{RETURN_HOME_NODE_NAME} 的 And 只有 {len(leaves)} 条叶子 —— "
            f"仅凭底部导航（主城 + 返回）会在半个游戏的子页面成立（含链上列表 / 详情页），"
            f"必须带一条【页面范围判别叶】（#29）"
        )
    types = _leaf_recognition_types(rec, resolve)
    if types and all(t == "OCR" for t in types):
        msgs.append(
            f"兜底事件自匹配：{RETURN_HOME_NODE_NAME} 的判据叶子全是 OCR（仅凭底部导航文字）—— "
            f"会在链上步骤页面（列表 / 详情页）自匹配；必须有一条页面范围判别叶（#29）"
        )
    return msgs


# ---------------------------------------------------------------------------
# 检查 7（#111）：领主战【账号快照】↔ 难度事实源（scene/lords.py）
# ---------------------------------------------------------------------------
#: 快照证据里「**仓外**产物」的前缀：``%TEMP%\\opencode\\*`` 已不可得（调研 §4.1），
#: 明写成 artifact 而不是假装它还在仓里。
SNAPSHOT_ARTIFACT_PREFIX = "artifact:"


def lords_snapshot_drift(repo_root: Path | None = None) -> list[str]:
    """``scene/lord_battle`` 的**账号快照**与 ``scene/lords``（难度事实唯一真源）不冲突（#111）。

    为什么需要这条：「每个成员支持哪些难度」曾经是生产真源里的一张静态表，被 #106 用**同一帧
    列表页**证伪（4 行里 3 行不符；``无猾机兵`` 实测 M=5 而旧表记 4）。现在它被降级为
    :data:`scene.lord_battle.ACCOUNT_SNAPSHOTS` ——「某账号某时刻看得见的档」，并且必须与
    ``scene/lords.py`` 的 **M** 与**解锁链**对得上。

    可判定的六条（全部离线、只读）：

    (a) 三要素齐全：账号 / 时间 / 帧（:data:`SNAPSHOT_ARTIFACT_PREFIX` 之外的帧必须在仓里真实存在）；
    (b) 快照的成员必须在花名册里（``scene.lords.LORDS``）；
    (c) 每档 ∈ ``scene.config.DIFFICULTIES``；
    (d) ``len(快照) <= M`` —— 快照是「那一刻看得见的档」，**不可能多于 M**；
    (e) 链已知时 ``快照 ⊆ tier_chain``；
    (f) 花名册 / 证据一致：``scene.lord_battle`` 的成员集 == ``scene.lords`` 的行名集；
        ``verified=True`` 的每条证据，``|`` 前的路径必须在仓里真实存在。

    ★不校验什么★：「本账号现在能打哪几档」——账号状态，离线永远比不了（见本模块文末
    「仍未校验什么」）。也不校验 M 本身对不对（那是 ``hooks_106`` 的 schema + 真机复算的活）。
    """
    root = Path(repo_root) if repo_root is not None else default_repo_root()
    from . import config as cfg_mod  # noqa: PLC0415
    from . import lord_battle as lb  # noqa: PLC0415
    from . import lords as lords_mod  # noqa: PLC0415

    msgs: list[str] = []

    snapshots = getattr(lb, "ACCOUNT_SNAPSHOTS", None)
    if not isinstance(snapshots, dict) or not snapshots:
        return [
            "scene/lord_battle.py 没有 ACCOUNT_SNAPSHOTS —— 逐成员难度必须是一份带 "
            "账号/时间/帧 provenance 的**账号快照**（#111；不能再是「支持难度集」那样的生产真源）"
        ]

    # (a) 三要素。
    for attr in ("ACCOUNT_SNAPSHOT_ACCOUNT", "ACCOUNT_SNAPSHOT_CAPTURED_AT"):
        value = getattr(lb, attr, "")
        if not isinstance(value, str) or not value.strip():
            msgs.append(
                f"scene/lord_battle.{attr} 为空 —— 账号快照必须写明**账号 + 时间 + 帧**三要素"
                f"（#111：没有采集条件的观察等于无法复核）"
            )
    # ★#111 修（跨线）★ 证据帧的存在性只在「根里确实带证据目录」时可判。
    #   `hooks_16` 的探针只把 `assets/**` 复制到临时副本（ADR-0001 的 apply/strip 演练），
    #   那里没有 `tools/frames/` —— 那种情况不是「帧丢了」，是「副本不带证据」。
    #   若在这里判红，会制造一个**与环境无关的假红**（#16 就这么被 #111 打红过一次）。
    _frames_dir = root / "tools" / "frames"
    _can_check_frames = _frames_dir.is_dir()

    frames = tuple(getattr(lb, "ACCOUNT_SNAPSHOT_FRAMES", ()) or ())
    if not frames:
        msgs.append(
            "scene/lord_battle.ACCOUNT_SNAPSHOT_FRAMES 为空 —— 快照必须指向具体帧/产物，"
            f"仓外产物请写成 {SNAPSHOT_ARTIFACT_PREFIX}<路径>"
        )
    for frame in frames:
        if not isinstance(frame, str) or not frame.strip():
            msgs.append("ACCOUNT_SNAPSHOT_FRAMES 里有空串 —— 帧必须可点名")
            continue
        if frame.startswith(SNAPSHOT_ARTIFACT_PREFIX):
            continue
        if not _can_check_frames:
            continue  # 临时副本不带证据目录（如 hooks_16 只复制 assets/**）→ 不判存在性
        if not (root / frame).is_file():
            msgs.append(
                f"账号快照的帧 {frame!r} 在仓库里**不存在** —— 仓内帧必须真实存在；"
                f"仓外产物请写 {SNAPSHOT_ARTIFACT_PREFIX}<路径>（不要假装它还在仓里）"
            )

    by_name = {entry.row_name: entry for entry in lords_mod.LORDS}
    difficulties = tuple(cfg_mod.DIFFICULTIES)

    # (b)(c)(d)(e) 快照 vs 事实源。
    for row_name, tiers in sorted(snapshots.items()):
        got = frozenset(tiers)
        entry = by_name.get(row_name)
        if entry is None:
            msgs.append(
                f"账号快照[{row_name!r}]：成员不在 scene/lords.py 的花名册里 —— "
                f"难度事实的唯一真源是 scene/lords.py"
            )
            continue
        unknown = sorted(d for d in got if d not in difficulties)
        if unknown:
            msgs.append(f"账号快照[{row_name!r}]：含词表里没有的难度 {unknown}（{list(difficulties)}）")
        if entry.max_tiers is not None and len(got) > entry.max_tiers:
            msgs.append(
                f"账号快照[{row_name!r}]：{len(got)} 档 > scene/lords.py 的 M={entry.max_tiers} —— "
                f"快照是「那一刻看得见的档」，**不可能多于 M**；两者至少一个错了"
                f"（旧表就是把「可见档数」当成了 M，见调研 §2.4）"
            )
        if entry.tier_chain:
            extra = sorted(d for d in got if d not in entry.tier_chain)
            if extra:
                msgs.append(
                    f"账号快照[{row_name!r}]：含解锁链上没有的档 {extra}"
                    f"（链 {list(entry.tier_chain)}）"
                )

    # (f) 花名册 / 证据一致性。
    roster = {member.行名 for member in lb.LORD_BATTLE.members}
    registry = {entry.row_name for entry in lords_mod.LORDS}
    if roster != registry:
        msgs.append(
            f"花名册漂移：scene/lord_battle 的成员集 != scene/lords 的行名集 —— "
            f"多={sorted(roster - registry)} 缺={sorted(registry - roster)}"
            f"（新增成员必须同时补一条难度登记，哪怕只是 pending 占位）"
        )
    for entry in lords_mod.LORDS:
        if not entry.verified:
            continue
        for item in entry.evidence:
            path_part = item.partition("|")[0]
            raw = Path(path_part)
            is_rel = not raw.is_absolute()
            if is_rel and not _can_check_frames:
                continue  # 副本不带 tools/frames/（hooks_16 只复制 assets/**）→ 无从判定，别造假红
            candidate = (root / raw) if is_rel else raw
            if not candidate.is_file():
                msgs.append(
                    f"{entry.slug}：verified=True 的证据 {path_part!r} 在仓库里不存在 —— "
                    f"证据必须可复核（不能只是注释里的来源名）"
                )
    return msgs


# ---------------------------------------------------------------------------
# 汇总入口
# ---------------------------------------------------------------------------
def check_all(
    repo_root: Path | None = None,
    cfg: "FamilyConfig" | None = None,
) -> list[str]:
    """跑全部校验，返回**全部**漂移（空 = 一致）。

    每条消息都点名声明的成员 / 规则 / 节点；空列表是唯一的「绿」。
    """
    root = Path(repo_root) if repo_root is not None else default_repo_root()
    if cfg is None:
        from .lord_battle import LORD_BATTLE

        cfg = LORD_BATTLE
    msgs: list[str] = []
    msgs.extend(option_drift(cfg, root / INTERFACE_REL))
    msgs.extend(difficulty_option_drift(root / INTERFACE_REL))
    msgs.extend(maze_option_drift(root / INTERFACE_REL))
    msgs.extend(recognition_drift(root))
    msgs.extend(event_def_drift(root))
    msgs.extend(event_injection_drift(root))
    msgs.extend(chain_drift(root))
    msgs.extend(chain_page_interrupt_drift(root))
    msgs.extend(chain_page_fallback_drift(root))
    msgs.extend(lords_snapshot_drift(root))
    return msgs
