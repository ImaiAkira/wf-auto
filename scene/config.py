# -*- coding: utf-8 -*-
"""场景配置面：family 模板 + 成员 delta + 校验 + 页面判据覆盖报告。

对应 ticket #3（配置面）/ ADR-0001（配置为真源）/ ADR-0002（目标声明式）/ ADR-0003（页面判据全局唯一）。

本模块只描述【领主战类这个 family 与它的成员】这一层**数据**：

* ``FamilyTemplate`` —— 所有领主战类成员共享的 shape（子族、页序、通用事件）；
* ``MemberDelta``    —— 每个成员只写差异：``id`` / ``行名`` / ``支持难度集``，
  外加所属 ``子族``；``页签`` 由 ``子族`` 决定，调用方**不能**单独设置页签；
* ``validate_config`` —— 校验，错误信息**点名**出错的成员；
* ``override_report`` —— 覆盖报告（ADR-0003：覆盖不得隐形）。

明确**不做**（属于后续 ticket）：链式拓扑与 ``decide``（#4）、异常组注入（#5）、
GUI 选项生成（#6）、配置↔JSON 漂移（#7）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .page_rules import duplicate_rule_names, page_rule

# 子族 → 页签（页签由子族决定；两族之间是一一对应，故页签不可单独设置）。
SUBFAMILIES: dict[str, str] = {
    "领主战": "领主战",
    "降临讨伐": "降临讨伐",
}

# 全局难度（「难度是全局输入而非成员属性」：用户选哪个，这里就列哪几个档）。
# #32：真机详情页还有一档「地狱级」（高难档，只有部分成员支持）—— 词表补上它，
# 逐成员的**实测**可用集见 scene/lord_battle.py（来源：diff_summary.json）。
DIFFICULTIES: tuple[str, ...] = ("初级", "中级", "高级", "高级+", "超级", "地狱级")

# 摇曳的迷宫（farm）目标模型【真源】（#54，**修订** #52）。
#
# ★#54 真机实测（设备 16448；帧 OCR 见 tools/contract_hooks/hooks_54.py）★：
#   迷宫**按「域」选**，而每个域是一张**异质行列表**（不是「元素矩阵」）——**元素是行名
#   的一部分，不是独立轴**（#52 曾把元素误设为独立选项；device 证伪，本票修订）。
#   **本模式没有 初级/中级/高级 难度档**；「Lv..」/「层」只出现在**行名内部**。
#   真机三域（据 s10/s11/s13（宝物域）、s53/w3/y1（崩坏域）、s76/s93（幽玄域）帧 OCR）：
#     · 崩坏域：`临境域 深渊之兽·极`（体力 0）/`·真`/``（行 1~3）+ 18 行
#       `深层域{1,2,3}【元素】Lv{50,60,70}`（体力 15~20）+ `通往深层之门`；
#     · 宝物域：6 行 `摇曳的迷宫 宝物域【火/水/雷/风/光/暗】`（体力 10）；
#     · 幽玄域（塔）：10 行 `幽玄域【{1〜3}…{28〜30}层】`（体力 30~40）。
#   GUI 选项与批量清单都从这两个词表派生（ADR-0001：配置为真源；
#   漂移由 scene.drift.maze_option_drift 把守）。
MAZE_DOMAINS: tuple[str, ...] = ("崩坏域", "宝物域", "幽玄域")

# 行名里的【元素】token 词表 —— ★只是行名的组成片段，**不是**独立选项轴★（#54）。
MAZE_ELEMENTS: tuple[str, ...] = ("火", "水", "雷", "风", "光", "暗")

# 崩坏域「深层域」：层号 -> Lv（真机：深层域1=Lv50 / 2=Lv60 / 3=Lv70）。
MAZE_DEEP_LV: tuple[tuple[int, int], ...] = ((1, 50), (2, 60), (3, 70))
# 幽玄域（塔）：10 段楼层（3 层一档）。
MAZE_TOWER_FLOORS: tuple[tuple[int, int], ...] = (
    (1, 3), (4, 6), (7, 9), (10, 12), (13, 15),
    (16, 18), (19, 21), (22, 24), (25, 27), (28, 30),
)
# 崩坏域行名里「临境域」那几行（行 1~3）与收尾行。
MAZE_BENG_HEAD_ROWS: tuple[str, ...] = (
    "临境域深渊之兽·极",
    "临境域深渊之兽·真",
    "临境域深渊之兽",
)
MAZE_BENG_TAIL_ROW = "通往深层之门"


def build_maze_rows(
    elements: Sequence[str] = MAZE_ELEMENTS,
    deep_lv: Sequence[tuple[int, int]] = MAZE_DEEP_LV,
    tower_floors: Sequence[tuple[int, int]] = MAZE_TOWER_FLOORS,
    beng_head: Sequence[str] = MAZE_BENG_HEAD_ROWS,
    beng_tail: str = MAZE_BENG_TAIL_ROW,
) -> dict[str, tuple[str, ...]]:
    """按「域 → 行名列表」构造真机异质行列表（#54；域内行序 = 声明/版式序）。"""
    beng: list[str] = list(beng_head)
    for tier, lv in deep_lv:
        for e in elements:
            beng.append(f"深层域{tier}【{e}】Lv{lv}")
    beng.append(beng_tail)

    baowu = [f"摇曳的迷宫宝物域【{e}】" for e in elements]
    youxuan = [f"幽玄域【{a}〜{b}层】" for a, b in tower_floors]
    return {"崩坏域": tuple(beng), "宝物域": tuple(baowu), "幽玄域": tuple(youxuan)}


#: 域 → 行名列表（**真源**；每个域是一张异质行列表，不是元素矩阵）—— #54。
MAZE_ROWS: dict[str, tuple[str, ...]] = build_maze_rows()

#: 所有域的全部行名（批量清单第二字段 / 行选择的合法取值宇宙）。
MAZE_ALL_ROWS: tuple[str, ...] = tuple(r for d in MAZE_DOMAINS for r in MAZE_ROWS[d])

#: 域的缺省行（GUI 默认落在第一行；真机演示停在 宝物域）。
DEFAULT_MAZE_DOMAIN = "宝物域"
DEFAULT_MAZE_ROW = MAZE_ROWS[DEFAULT_MAZE_DOMAIN][0]


# ---------------------------------------------------------------------------
# ★#57★ 迷宫【域】的判定与进入改用【图片匹配】（运维 2026-10-14：迷宫域不要用 OCR）★
# ---------------------------------------------------------------------------
# 真机缺陷（#57）：FarmMazeEntry 过去只以轮播【标题】为判据 → 点下去可能进**任意一个域**；
# 而横幅副标题（域名）的 OCR 在真机被读坏（`崩坏域`→`崩环域`、`幽玄域`→`出立域`，
# 连标题都被读成 `摇电的迷宫`/`摇拽的迷宮`）—— 因此「进的是哪个域」绝不能靠 OCR。
#
# 做法：每个域各有一张【真机 720 裁片】（相对 ``assets/resource/image/``，MAA TemplateMatch
# 口径），分两个角色：
#   · ``banner``：主城左侧轮播横幅上的**域名美术字** —— 进域门控（只有横幅正显示该域时才点）；
#   · ``head``  ：迷宫页**页眉**的域名美术字 —— 进域后【复核】确实进了该域（复核不过则不推进）。
# 裁片来自 720 空间真机帧（设备 16448；见 tools/frames/maze57_*.png 的同一批帧），
# 判据（threshold）见 scene.options.MAZE_TEMPLATE_THRESHOLD 与 agent.side_impl 的同名常量。
MAZE_DOMAIN_TEMPLATES: dict[str, dict[str, str]] = {
    "崩坏域": {"banner": "maze/domain_beng_banner.png", "head": "maze/domain_beng_head.png"},
    "宝物域": {"banner": "maze/domain_baowu_banner.png", "head": "maze/domain_baowu_head.png"},
    "幽玄域": {"banner": "maze/domain_youxuan_banner.png", "head": "maze/domain_youxuan_head.png"},
}


def maze_domain_template(domain: str, role: str = "banner") -> str:
    """域 + 角色（``banner`` / ``head``）-> 模板相对路径（#57）。★纯函数★。

    未知域 / 未知角色**报 KeyError**（绝不静默回退到某个域的模板 —— 那正是 #57 的缺陷）。
    """
    return MAZE_DOMAIN_TEMPLATES[domain][role]


def maze_row_ok(domain: str, row: str) -> bool:
    """该「行名」是否属于该【域】（#54：行名必须落在域的合法行列表里）。"""
    return row in MAZE_ROWS.get(domain, ())


def maze_domain_of(row: str) -> str | None:
    """行名 -> 它所属的域（行名全局唯一；找不到返回 None）。"""
    for d in MAZE_DOMAINS:
        if row in MAZE_ROWS[d]:
            return d
    return None


class ConfigError(Exception):
    """配置本身非法（结构化错误，调用方据此中止并报错）。"""


@dataclass(frozen=True)
class FamilyTemplate:
    """领主战类家族模板：所有成员共有的 shape。"""

    id: str
    显示名: str
    子族: tuple[str, ...]
    页序: tuple[str, ...] = ()              # 按顺序引用的页面判据名（全局注册表里）
    通用事件: tuple[str, ...] = ()           # 跨场景事件（Pub*；#5 负责注入，这里只声明）
    必须难度: tuple[str, ...] = DIFFICULTIES

    def 页签_of(self, 子族: str) -> str:
        if 子族 not in self.子族:
            raise ConfigError(
                f"子族 {子族!r} 不属于 family {self.id!r}（允许：{list(self.子族)}）"
            )
        return SUBFAMILIES[子族]


@dataclass(frozen=True)
class MemberDelta:
    """一个领主战类成员相对 family 模板的差异。

    差异字段：``id`` / ``行名`` / ``支持难度集``，外加所属 ``子族``。
    ``页签`` 是**派生**属性 —— 由 ``子族`` 决定，构造函数不接受它，因此调用方
    无法把页签设成与子族不一致的值。
    """

    id: str
    子族: str
    行名: str
    支持难度集: tuple[str, ...]

    @property
    def 页签(self) -> str:
        return SUBFAMILIES[self.子族]

    def as_record(self) -> dict:
        """对外记录形如 ``{id, 页签, 行名, 支持难度集}``（含派生的页签）。"""
        return {
            "id": self.id,
            "页签": self.页签,
            "行名": self.行名,
            "子族": self.子族,
            "支持难度集": list(self.支持难度集),
        }


def member(子族: str, id: str, 行名: str, 支持难度集: Sequence[str]) -> MemberDelta:
    """构造一个成员 delta。

    页签由 ``子族`` 决定，调用方【不能】单独传页签 —— 因此这里没有 ``页签`` 形参。
    """
    return MemberDelta(id=id, 子族=子族, 行名=行名, 支持难度集=tuple(支持难度集))


@dataclass(frozen=True)
class Override:
    """场景对某条全局页面判据的**覆盖**（ADR-0003：只在确有差异时声明）。

    ``owner`` 是覆盖的归属：成员 id 或子族名 —— 覆盖报告据此回答「谁覆盖了、为什么」。
    """

    rule: str
    recognition: dict
    owner: str
    reason: str = ""


@dataclass
class FamilyConfig:
    """一个 family 的完整配置：模板 + 成员 delta 列表 + 覆盖声明。"""

    family: FamilyTemplate
    members: list[MemberDelta] = field(default_factory=list)
    overrides: list[Override] = field(default_factory=list)


def validate_config(cfg: FamilyConfig) -> list[str]:
    """校验配置，返回错误列表（空 = 通过）。

    每条错误都**点名**出错的成员 / 覆盖；只要有一条错误，调用方就应当中止，
    绝不静默采用「后声明的那个」。
    """
    errors: list[str] = []

    # (0) 子族必须属于本 family
    for m in cfg.members:
        if m.子族 not in cfg.family.子族:
            errors.append(
                f"成员 {m.id!r} 的子族 {m.子族!r} 不属于 family {cfg.family.id!r}"
                f"（允许：{list(cfg.family.子族)}）"
            )

    # (1) 成员 id 全局唯一 —— 重复当场报错，不静默覆盖
    counts: dict[str, int] = {}
    for m in cfg.members:
        counts[m.id] = counts.get(m.id, 0) + 1
    for mid, n in counts.items():
        if n > 1:
            errors.append(
                f"成员 id 重复：{mid!r} 被声明了 {n} 次"
                f"（一个成员只能在一处声明，不得静默后者覆盖前者）"
            )

    # (2) 行名非空
    for m in cfg.members:
        if not str(m.行名).strip():
            errors.append(f"成员 {m.id!r} 的行名为空（列表页要按行名 OCR 选中目标行）")

    # (3) 支持难度集：非空，且取值合法
    for m in cfg.members:
        if not m.支持难度集:
            errors.append(f"成员 {m.id!r} 的支持难度集为空（必须至少声明一个难度）")
            continue
        bad = [d for d in m.支持难度集 if d not in DIFFICULTIES]
        if bad:
            errors.append(
                f"成员 {m.id!r} 的支持难度集含未知难度 {bad}"
                f"（合法取值：{list(DIFFICULTIES)}）"
            )

    # (4) 覆盖必须引用一个存在的全局判据
    for o in cfg.overrides:
        try:
            page_rule(o.rule)
        except KeyError:
            errors.append(f"覆盖 owner={o.owner!r} 引用了不存在的页面判据 {o.rule!r}")

    return errors


def derive_members(cfg: FamilyConfig) -> list[dict]:
    """data → 派生的成员记录（保持声明顺序；``页签`` 由子族决定）。

    这是「39 个成员可由配置声明」的落点：#3 只派生到成员这一层，
    GUI 选项（#6）/ 链式拓扑（#4）在后续 ticket 接着做。
    """
    return [m.as_record() for m in cfg.members]


def override_report(cfg: FamilyConfig) -> list[Override]:
    """覆盖报告：列出该配置声明的**全部**覆盖（ADR-0003：不得有隐形覆盖）。"""
    return list(cfg.overrides)


def assert_page_rules_globally_unique() -> None:
    """ADR-0003 断言：全局页面判据必须唯一，否则 ConfigError。"""
    dups = duplicate_rule_names()
    if dups:
        raise ConfigError(f"页面判据不唯一（全局注册表里出现了多次）：{dups}")
