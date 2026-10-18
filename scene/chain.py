# -*- coding: utf-8 -*-
"""领主战类流程的链式拓扑（页面驱动主路径）—— ticket #4（ADR-0002）。

本模块把领主战类的流程表达为**链式拓扑**（数据 + 目标解析 + 详情页难度 seam）：

* 每个节点锚在一个【页面】上；页面判据取全局唯一一份 ``scene.page_rules``（ADR-0003），
  节点**引用**它、不复制；
* 节点的 ``下一步`` 是**显式后继**（节点 id 或终点标记），不再是一张靠顺序携带知识、
  ``next`` 全指回入口的中心分派表；
* 目标（成员 + 难度 + 模式）由配置**声明**，本模块只负责把目标解析成链上的锚点。

决策 ``decide`` 与导航 ``navigate`` 在 ``scene.navigation``。

真机页序（已核实）：主城 → 领主战页（页签 领主战 │ 降临讨伐）→ 列表页 → 详情页 →
模式选择（单人 / 多人）→ 加成弹窗 → 编队页 → 挑战 → 战斗 HUD → 结算（三页）→ 归位。
链上节点与全局页面判据**一一对应**（10 个页面 = 10 个节点，每页恰好一个锚点）。

★未决 / 以真机为准（ticket #4 范围追加）★
「某成员实际支持哪些难度档」是**账号进度相关**的、必须**运行时从详情页读出来**，
不是配置里手写的（#39 真机实证：同一成员在已通关账号 4 档、早期账号只有 ``中级``）。
``read_detail_difficulties`` 是这条读取的**离线 seam**；真机实现 = 
``agent.side_impl.discover_difficulties`` 扫详情页 OCR 的难度行（``SpecialTargetFightRecognition``）。
离线时按「成员显式声明的支持难度集（#3 的**可选覆盖**，= 某账号实测的离线兜底）；
否则视为该成员支持全局全集」建模 —— 即缺省（无覆盖）时难度集来自运行时发现，
配置只提供可选覆盖（#39 起该列明确标注为「某账号实测、可能不适用」）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DIFFICULTIES, SUBFAMILIES, ConfigError, FamilyConfig
from .page_rules import page_rule, page_rules, selection_for

# ---------------------------------------------------------------------------
# 链上的节点 id（每个 = 一个页面锚点）
# ---------------------------------------------------------------------------
NODE_主城 = "主城·进领主战"
NODE_列表 = "列表页·切页签"
NODE_领主战页签 = "领主战页签·选目标行"
NODE_降临讨伐页签 = "降临讨伐页签·选目标行"
NODE_详情 = "详情页·读难度行"
NODE_模式 = "模式选择页·选模式"
NODE_加成 = "加成弹窗·选否"
NODE_编队 = "编队页·读开关并挑战"
NODE_战斗 = "战斗HUD·等战斗"
NODE_结算 = "结算页·推进并归位"

# 终点标记（不是页面节点）
TERMINAL_收工 = "收工"
TERMINAL_归位 = "归位"
终端名称 = (TERMINAL_收工, TERMINAL_归位)

# 链终点标记 → pipeline 上的**落地节点**（#22）。
#
# 「收工」不是一个页面锚点，而是**任务终止**：pipeline 里由 ``SpecialBatchStop``
# 承担（``DirectHit`` + ``StopTask``，``next`` 为空）。该节点原属批量清单路径，
# 单目标模式**复用它**，不另造一套并行终止机制（#22 的「复用而非另起炉灶」）。
# 单侧落点见 ``agent.side_impl``：结算动作在**结算帧**通过 ``override_next`` 把当前
# 结算节点指向它 —— 与批量路径「指挥官 override 到 SpecialBatchStop」同一机制。
终端pipeline节点: dict[str, str] = {TERMINAL_收工: "SpecialBatchStop"}

# 全局页面判据里，锚在「领主战列表页」这一物理屏上的两个页签页面名。
页签页面 = {"领主战": "领主战页签", "降临讨伐": "降临讨伐页签"}

# 目标子族 → 它在「领主战列表页」要走的页签节点（#19）。
# ★页签由目标子族决定，不靠 pipeline 里 SpecialTabLord/SpecialTabJoss 的 max_hit 竞速★：
# 同一张列表屏上锚着两个页签页面（领主战页签 / 降临讨伐页签），目标属于哪个子族就走哪一个。
页签节点_of: dict[str, str] = {
    "领主战": NODE_领主战页签,
    "降临讨伐": NODE_降临讨伐页签,
}

# 子族 → pipeline 里承担该页签动作的节点名（#19）。
# 页签页面 → pipeline 节点是已登记的事实（scene.drift.PAGE_RULE_SOURCES /
# scene.options.PAGE_RULE_TO_NODE）：领主战页签 ↔ SpecialTabLord、降临讨伐页签 ↔ SpecialTabJoss。
# 链上的 ``页签节点_of`` 用的是链节点 id，这里给出对应的 pipeline 节点名，供子族页签覆盖使用。
页签pipeline节点: dict[str, str] = {
    "领主战": "SpecialTabLord",
    "降临讨伐": "SpecialTabJoss",
}


@dataclass(frozen=True)
class Step:
    """链上一步里的一个动作（一个节点可含多个步骤，仍锚在同一个页面上）。"""

    动作: str
    观测: str = ""  # 这一步产出的观测量名（供门/后续步骤引用），无则空


@dataclass(frozen=True)
class Node:
    """链上一个节点：锚在一个【页面】上，``下一步`` 是显式后继。"""

    id: str
    页面: str
    步骤: tuple[Step, ...]
    下一步: tuple[str, ...] = ()  # 节点 id 或终点标记名
    重试上限: int = 3


@dataclass(frozen=True)
class Terminal:
    """链的终点标记。``归位`` 带 ``到页面``（回主城后链可继续）。"""

    名称: str
    到页面: str = ""
    原因: str = ""


def 收工(原因: str = "") -> Terminal:
    return Terminal(TERMINAL_收工, 原因=原因)


def 结算终点(目标次数: int | None = None, 已打次数: int = 0) -> Terminal:
    """结算页的终点（#22）：目标已打满**配置次数** → 收工；否则归位（通用事件）回主城。

    ★为什么需要它★：单目标模式此前**没有收工条件** —— ``SpecialFightTargetRow``
    （配置次数由它的 ``max_hit`` 承担）打满后只是「这一场不再从候选里命中」，
    没有任何东西把流程推向终止，于是只能在 主城 ↔ 列表 ↔ 详情 之间无限重进
    （#13 真机实证：15:50:48→15:54:06 约 60 轮，每轮 ~3s）。这里给出链上**显式**的
    收工边：``已打次数 >= 目标次数`` 时，结算页的下一步是 ``收工`` 而不是 ``归位``。

    ``目标次数`` 缺省 ``None`` = 「不限次」—— 与 pipeline 上 ``SpecialFightTargetRow``
    不带有限 ``max_hit`` 同义；此时恒返回「归位」，保持单目标旧行为与既有守卫不变。

    落地（pipeline 侧）：``收工`` → ``终端pipeline节点[TERMINAL_收工]`` = ``SpecialBatchStop``。
    """
    if 目标次数 is not None and 已打次数 >= 目标次数:
        return 收工(
            f"目标已打满配置次数（{已打次数}/{目标次数}）→ 收工，绝不重进同一目标"
        )
    return Terminal(TERMINAL_归位, 到页面="主城", 原因="归位回主城")


@dataclass(frozen=True)
class Target:
    """已解析的目标场景：打哪个成员、哪个难度，模式默认单人。"""

    成员: str
    行名: str
    子族: str
    页签: str
    难度: str
    模式: str = "单人"


@dataclass(frozen=True)
class Chain:
    """一条页面驱动的链：``nodes`` 每个锚在一个页面上。"""

    family_id: str
    nodes: tuple[Node, ...]

    def by_page(self, 页面: str) -> Node | None:
        """按页面名取锚点节点；未锚定则 None（调用方据此收工，绝不静默兜底）。"""
        for n in self.nodes:
            if n.页面 == 页面:
                return n
        return None

    def node(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def 页面集(self) -> tuple[str, ...]:
        return tuple(n.页面 for n in self.nodes)


def _member(cfg: FamilyConfig, 成员: str):
    for m in cfg.members:
        if m.id == 成员:
            return m
    return None


def resolve_target(cfg: FamilyConfig, 目标场景) -> Target | None:
    """把「目标场景」解析成链上锚点。

    接受 ``Target`` / ``{"成员","难度","模式"?}`` 字典 / ``(成员, 难度, 模式?)`` 元组 /
    ``成员`` 字符串（难度默认取全局全集最后一项）。任何无法解析的目标都返回 None ——
    调用方据此走「不可达 → 收工」，绝不臆造成员。
    """
    成员 = 难度 = 模式 = None
    if isinstance(目标场景, Target):
        return 目标场景 if _valid_target(cfg, 目标场景) else None
    if isinstance(目标场景, dict):
        成员, 难度, 模式 = 目标场景.get("成员"), 目标场景.get("难度"), 目标场景.get("模式")
    elif isinstance(目标场景, (tuple, list)) and 目标场景:
        成员 = 目标场景[0]
        难度 = 目标场景[1] if len(目标场景) > 1 else None
        模式 = 目标场景[2] if len(目标场景) > 2 else None
    elif isinstance(目标场景, str):
        成员, 难度 = 目标场景, None
    else:
        return None

    if not 成员:
        return None
    m = _member(cfg, 成员)
    if m is None or m.子族 not in cfg.family.子族:
        return None
    if not 难度:
        难度 = DIFFICULTIES[-1]
    if 难度 not in DIFFICULTIES:
        return None
    return Target(
        成员=m.id,
        行名=m.行名,
        子族=m.子族,
        页签=SUBFAMILIES[m.子族],
        难度=难度,
        模式=模式 or "单人",
    )


def _valid_target(cfg: FamilyConfig, t: Target) -> bool:
    if t.难度 not in DIFFICULTIES:
        return False
    m = _member(cfg, t.成员)
    return m is not None and m.子族 in cfg.family.子族


def _占位目标(cfg: FamilyConfig) -> Target:
    """校验用的样本目标（链的形状/页面锚定与目标无关，只依赖子族）。"""
    子族 = cfg.family.子族[0] if cfg.family.子族 else "领主战"
    try:
        页签 = cfg.family.页签_of(子族)
    except ConfigError:
        页签 = SUBFAMILIES.get(子族, 子族)
    return Target(成员="<样本>", 行名="<样本>", 子族=子族, 页签=页签, 难度=DIFFICULTIES[0])


def target_tab_node(target: Target) -> str:
    """目标子族决定它在列表页要走哪个页签节点（#19）。

    「领主战列表页」这一物理屏上锚着两个页签页面（``领主战页签`` / ``降临讨伐页签``）；
    同一个列表上该走哪一页，**只由目标的子族决定** —— 绝不依赖 pipeline 里
    ``SpecialTabLord`` / ``SpecialTabJoss`` 的 ``max_hit`` 竞速（那会让首轮消耗掉命中后、
    重进列表时被另一个子族的页签抢先 → 页签翻转、目标不可见 → 归位弹跳死循环）。
    未知子族 -> ``ConfigError``（绝不臆造页签）。
    """
    node = 页签节点_of.get(target.子族)
    if node is None:
        raise ConfigError(
            f"目标子族 {target.子族!r} 没有对应的页签节点（允许：{list(页签节点_of)}）"
        )
    return node


def tab_override_for(子族: str) -> dict[str, dict]:
    """该子族在列表页的「页签节点 → recognition」覆盖（#19：页签由目标子族决定）。

    只启用该子族自己的页签节点、把**另一个**子族的页签节点关成 ``__NONE__`` ——
    与 ``scene.options`` 的子族覆盖（GUI）和 ``agent.side_impl`` 的批量覆盖表达同一事实，
    供真机 runner / 批量指挥官复用，避免「两个 tab 都开」时基础 pipeline 靠 ``max_hit``
    竞速（首轮用尽后重进必被抢先 → 页签翻转死循环）。启用的那条 recognition **直接引用
    全局页面判据**（``scene.page_rules``），ROI / expected 不另写一份。
    """
    if 子族 not in 页签pipeline节点:
        raise ConfigError(f"目标子族 {子族!r} 没有对应的页签节点（允许：{list(页签pipeline节点)}）")
    out: dict[str, dict] = {}
    for sub, node in 页签pipeline节点.items():
        param = page_rule(页签页面[sub]).recognition.get("param") or {}
        expected = list(param.get("expected") or []) if sub == 子族 else ["__NONE__"]
        out[node] = {
            "recognition": {
                "type": "OCR",
                "param": {"expected": expected, "roi": list(param.get("roi") or [])},
            }
        }
    return out


def build_chain(
    cfg: FamilyConfig,
    target: Target,
    *,
    目标次数: int | None = None,
    已打次数: int = 0,
) -> Chain:
    """按目标解析出这条链的显式后继（页签分支 / 错页签自恢复都写死在后继里）。

    ``目标次数`` / ``已打次数`` 是 #22 的**结算终点 seam**：目标已打满配置次数时，
    结算节点的显式后继是 ``收工``（落在 ``SpecialBatchStop``），否则是 ``归位``。
    缺省（``目标次数=None``）＝ 不限次，链的形状与既有守卫完全一致。
    """
    页签节点 = target_tab_node(target)
    模式动作 = "多人游戏 / 建立房间" if target.模式 == "多人" else "单人游戏"
    结算下一步 = 结算终点(目标次数, 已打次数).名称

    nodes = (
        Node(
            NODE_主城,
            "主城",
            (Step("点主城右下角【领主战】入口"),),
            (NODE_列表,),
        ),
        Node(
            NODE_列表,
            "领主战列表页",
            (
                Step(f"切到目标子族【{target.子族}】的页签", "当前页签"),
                # #29：页签选中后若「选目标行」不命中（目标行在首屏之外），必须先**滚动列表**
                #   继续找（pipeline 的 ``SpecialScrollList``），而不是被兜底归位带回主城。
                #   落地：``SpecialTabLord`` / ``SpecialTabJoss`` 的显式后继 = 选行节点 +
                #   滚动节点 + 枢纽兜底（见 ``scene.drift.CHAIN_SUCCESSORS``）。
                Step("目标行不在屏内则滚动列表继续找", "已选行"),
            ),
            (页签节点,),
        ),
        Node(
            NODE_领主战页签,
            "领主战页签",
            (Step(f"在列表里按行名【{target.行名}】选中目标行", "已选行"),),
            # 错页签自恢复：目标不是领主战就退回列表页重选页签。
            (NODE_详情,) if target.子族 == "领主战" else (NODE_列表,),
        ),
        Node(
            NODE_降临讨伐页签,
            "降临讨伐页签",
            (Step(f"在列表里按行名【{target.行名}】选中目标行", "已选行"),),
            (NODE_详情,) if target.子族 == "降临讨伐" else (NODE_列表,),
        ),
        Node(
            NODE_详情,
            "详情页",
            (
                Step("读该成员【实际支持】的难度档（详情页难度行）", "可用难度集"),
                # #35 真机几何：详情页【难度名在上、战斗在其下方 ≈40px】——「点哪一行的战斗」
                # 由 agent.side_impl.pick_target_battle_box 按此几何配对（pair="below"），
                # 绝不再假设「战斗在难度名上方」（那会卡死单行成员 / 静默打错多行成员）。
                Step(f"点目标难度【{target.难度}】行的【战斗】"),
            ),
            (NODE_模式,),
        ),
        Node(
            NODE_模式,
            "模式选择页",
            (Step(f"选【{模式动作}】"),),
            (NODE_加成,),
        ),
        Node(
            NODE_加成,
            "加成弹窗",
            (Step("点【否】（不使用领主加成点数）"),),
            (NODE_编队,),
        ),
        Node(
            NODE_编队,
            "编队页",
            (
                Step("读【开关】：自动 / 自动续战 / 手操（画面探针）", "开关值"),
                Step("点【挑战】（开关区与挑战按钮互不重叠）"),
            ),
            (NODE_战斗,),
        ),
        Node(
            NODE_战斗,
            "战斗HUD",
            (Step("等待战斗结束（不做盲目点击）"),),
            (NODE_结算,),
        ),
        Node(
            NODE_结算,
            "结算页",
            (
                Step("推进结算三页：继续 → 继续 → OK"),
                Step("归位（通用事件）：回主城"),
            ),
            # #22：打满配置次数 → 收工（落 SpecialBatchStop）；否则归位回主城继续。
            (结算下一步,),
        ),
    )
    return Chain(family_id=cfg.family.id, nodes=nodes)


def scene_page_selection(cfg: FamilyConfig) -> tuple[str, ...]:
    """该 family/scene 声明的**有序页面选取**（per-scene；ADR-0003 注册表为准）。

    注册表里有该场景 → 用它的有序选取（= 配置在 ``scene.lord_battle`` 里声明的 ``页序``）；
    未登记（如测试里临时构造、尚未登记的 ``FamilyConfig``）→ 回落到 ``cfg.family.页序``。

    ★#58 / E2★：作用域是【这一个场景】，绝不是各场景页面的**累积并集** —— 后者会让别的
    场景的页面混进来、把「链页面集 == 本场景页面集」的相等校验冲淡（并会让 #37 的
    ``CHAIN_STEP_PAGES`` 退化成一张全局表）。
    """
    try:
        return tuple(selection_for(cfg.family.id).pages)
    except KeyError:
        return tuple(cfg.family.页序)


def validate_chain(cfg: FamilyConfig) -> list[str]:
    """校验链与配置/页面判据一致，返回错误列表（空 = 通过）。"""
    chain = build_chain(cfg, _占位目标(cfg))
    errors: list[str] = []

    # (1) 页面驱动：每个节点的页面必须是全局判据（引用而非复制；ADR-0003）。
    for n in chain.nodes:
        try:
            page_rule(n.页面)
        except KeyError:
            errors.append(f"节点 {n.id!r} 锚在了不存在的页面判据 {n.页面!r}（页面判据在 scene.page_rules）")

    # (2) 每个页面恰好一个锚点（页面 → 节点是函数，decide 才可能是纯函数）。
    seen: dict[str, int] = {}
    for n in chain.nodes:
        seen[n.页面] = seen.get(n.页面, 0) + 1
    for page, cnt in seen.items():
        if cnt > 1:
            errors.append(f"页面 {page!r} 上锚了 {cnt} 个节点（页面驱动的链要求每页至多一个锚点）")

    # (3) family 页序与链的页面集必须一致（引用了未覆盖的页面 / 多出无关页面都报）。
    # ★#58 / E2★ 相等校验按 family/scene **分域**（:func:`scene_page_selection`）：只对本
    #   场景的页面选取比对，绝不是各场景页面的累积并集（那会冲淡相等语义、并让 #37 退化）。
    页序 = set(scene_page_selection(cfg))
    链页 = set(chain.页面集())
    for p in sorted(页序 - 链页):
        errors.append(f"family 页序里的页面 {p!r} 在链上没有锚点")
    for p in sorted(链页 - 页序):
        errors.append(f"链上的页面 {p!r} 不在 family 页序里")

    # (4) 显式后继必须解析得到（节点或终点）；节点 id 唯一。
    ids: list[str] = [n.id for n in chain.nodes]
    for nid, cnt in {i: ids.count(i) for i in set(ids)}.items():
        if cnt > 1:
            errors.append(f"节点 id 重复：{nid!r}")
    known = set(ids) | set(终端名称)
    for n in chain.nodes:
        if not n.下一步:
            errors.append(f"节点 {n.id!r} 没有显式后继（链断了）")
        for ref in n.下一步:
            if ref not in known:
                errors.append(f"节点 {n.id!r} 的后继 {ref!r} 解析不到（既不是节点也不是终点）")

    return errors


# ---------------------------------------------------------------------------
# 详情页 seam：读该成员【实际支持】的难度档（运行时发现，非手写）
# ---------------------------------------------------------------------------
def read_detail_difficulties(cfg: FamilyConfig, target: Target) -> frozenset[str]:
    """详情页难度行 → 该成员当前可用难度集。

    ★离线 seam★：真机实现 = ``agent.side_impl.discover_difficulties`` 扫详情页 OCR 的
    难度行（``SpecialTargetFightRecognition`` 在详情页帧上调用）；这里按 #3 的语义建模 ——
    成员显式声明的 ``支持难度集`` 是**可选覆盖 / 某账号实测的离线兜底**，一旦它不是全局全集
    就用它；否则（缺省）由「运行时发现」给出全局全集。目标难度必须落在返回值内，否则不可达。
    """
    m = _member(cfg, target.成员)
    if m is not None and set(m.支持难度集) != set(DIFFICULTIES):
        return frozenset(m.支持难度集)
    return frozenset(DIFFICULTIES)


def found_difficulties(cfg: FamilyConfig, target: Target, 发现难度集=None) -> frozenset[str]:
    """门用的「可用难度集」：显式传入优先（真机把读到的值传进来），否则走 seam。"""
    if 发现难度集 is not None:
        return frozenset(发现难度集)
    return read_detail_difficulties(cfg, target)


def page_names() -> set[str]:
    """全局页面判据的全部页面名（链的锚点全集）。"""
    return {r.name for r in page_rules()}
