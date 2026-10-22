# -*- coding: utf-8 -*-
"""页面判据全局唯一注册表（ADR-0003）。

「这个画面算哪个页面」是一条**判据**。本模块是它的【唯一一份】定义，放在共享层：
场景配置（``scene/lord_battle.py`` 这类）只**引用**这里的页面名；只有在确有差异时，
才在自己的配置里声明 ``Override``。任何覆盖都必须出现在 ``scene.config.override_report``
里 —— 否则覆盖就成了新的隐形分叉点（ADR-0003 后果）。

判据的形态刻意与 MAA pipeline 的 recognition 对象同形
（``{"type": ..., "param": {...}}``），这样 #5 的异常注入 / #7 的配置↔JSON 漂移校验
可以直接复用，不必再翻译一层。

所有判据的 ROI / expected 都**照抄** ``assets/resource/pipeline/special_dungeon.json``
的实测值，不另行发明。

★#58 / E1（Phase 0）★ 本模块同时是**页面判据注册表**（:class:`PageRuleRegistry`）：全局
判据表仍只有一份（:data:`PAGE_RULES`），场景只**按名有序选取**（:meth:`PageRuleRegistry.register`），
差异才以**具名显式** ``scene.config.Override``（owner + reason）覆盖并进 ``override_report``
（绝不隐形）；链上步骤页集（#37）由 :func:`chain_step_pages` **按场景派生**，绝不是各场景
页面的累积并集。全局唯一断言（:func:`duplicate_rule_names`）保留。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageRule:
    """一条页面判据：页面名 + recognition（pipeline 同形）+ 来源备注。"""

    name: str
    recognition: dict
    note: str = ""


# ---------------------------------------------------------------------------
# 全局唯一一份页面判据（领主战类页序上用到的那些页面）。
# ---------------------------------------------------------------------------
PAGE_RULES: list[PageRule] = [
    PageRule(
        "主城",
        {"type": "OCR", "param": {"expected": ["领主战"], "roi": [480, 1080, 240, 140]}},
        "主城右下角【领主战】入口（special_dungeon.json SpecialOpenLord 实测）",
    ),
    PageRule(
        "领主战列表页",
        {"type": "OCR", "param": {"expected": ["更新列表"]}},
        "列表页独有固定元素「更新列表」（SpecialScrollList；详情页没有）",
    ),
    PageRule(
        "领主战页签",
        {"type": "OCR", "param": {"expected": ["^领主战$"], "roi": [0, 375, 360, 60]}},
        "列表页顶部 tab【领主战】（SpecialTabLord；ROI 限 tab 行，避开列表行里的分类）",
    ),
    PageRule(
        "降临讨伐页签",
        {"type": "OCR", "param": {"expected": ["降临讨伐"], "roi": [360, 375, 360, 60]}},
        "列表页顶部 tab【降临讨伐】（SpecialTabJoss）",
    ),
    PageRule(
        "详情页",
        {"type": "OCR", "param": {"expected": ["推荐编成"]}},
        "副本详情页独有「推荐编成」（SpecialDetailGate）",
    ),
    PageRule(
        "模式选择页",
        {"type": "OCR", "param": {"expected": ["单人游戏"]}},
        "模式选择页（SpecialModeSolo 实测）",
    ),
    PageRule(
        "加成弹窗",
        {"type": "OCR", "param": {"expected": ["领主加成点数"]}},
        "领主加成点数弹窗（SpecialBonusNo / SpecialBonusYes 实测）",
    ),
    PageRule(
        "编队页",
        {"type": "OCR", "param": {"expected": ["^挑战(→)?$"], "roi": [180, 1000, 400, 180]}},
        "编队页底部【挑战】（SpecialChallenge；ROI 避开房间页灰按钮；"
        "#109 兼容带箭头的『挑战→』—— 该按钮两种渲染并存，实测 8/17 帧带箭头）",
    ),
    PageRule(
        "战斗HUD",
        {
            "type": "And",
            "param": {
                "all_of": [
                    {"type": "OCR", "param": {"expected": [r"时间 \d+:\d+"]}},
                    {"type": "OCR", "param": {"expected": [r"分数 \d"]}},
                ]
            },
        },
        "战斗 HUD：带格式的「时间 mm:ss」与「分数 N」（铁律4，防结算页奖励条误命中）",
    ),
    PageRule(
        "结算页",
        {"type": "OCR", "param": {"expected": ["^继续$"]}},
        "结算推进页【继续】（common.PubResultContinueText 的实测判据）",
    ),
]


# ---------------------------------------------------------------------------
# ★#37 通用不变量：链上步骤页面集合★
#
# 「任何被注入的事件都不得命中链上步骤页面」—— 这是 #18 / #29 / #37 三个同族事故
# 的共同教训，故在此登记「链上步骤页面」这一概念（页面层，不是节点层）：
#
#   * #18：归位（兜底型注入）在【主城】自匹配 → 点空 → 死循环；
#   * #29：归位在【列表页 / 详情页】自匹配 → 滚动找行永不执行 → 只打得到首屏 3 个；
#   * #37：新角色（打断型注入）在【降临讨伐列表页】自匹配（行 NEW 徽标）→ 点别人的
#     详情页 → 链无法恢复 → 14/14 循环到超时。
#
# 三者同构：一个被注入的事件，其判据命中了【链上本要执行另一步】的页面，于是抢在
# 那一步之前命中、吃掉这一帧。故不变量用「页面」表达，判据由
# ``tools/contract_hooks/hooks_37.py`` 用**真机帧模型**逐事件 × 逐页面验证。
#
# 上面这些名字都必须存在于 :data:`PAGE_RULES`（由测试断言，绝不静默）。
# ---------------------------------------------------------------------------
# ★#58 / E2★：下面这张表是【缺省场景（领主战族）】的链上步骤页集 —— 它是「按场景派生」
# 的**期望面**（守卫 :mod:`tools.contract_hooks.hooks_phase0` 用它核对派生结果，防配置改了
# 而文档没跟上）。运行时的链上步骤页集**不是**这张常量，而是 :func:`chain_step_pages`
# 按场景派生的结果；:data:`CHAIN_STEP_PAGES` 由模块 ``__getattr__`` 惰性给出（= 缺省场景
# 的派生结果），因此它**永不**变成各场景页面的累积并集（#37 不变量因此保住）。
_EXPECTED_DEFAULT_CHAIN_STEP_PAGES: tuple[str, ...] = (
    "主城",            # SpecialOpenLord 的入口页（#18：归位曾在此自匹配）
    "领主战列表页",    # SpecialScrollList / 页签所在的列表页（#29 / #37 的关键反例）
    "领主战页签",
    "降临讨伐页签",
    "详情页",          # SpecialDetailGate（#29）
    "模式选择页",      # SpecialModeSolo
    "加成弹窗",        # SpecialBonusNo（事件与链步同节点 —— 见 hooks_37 的同判据豁免）
    "编队页",          # SpecialChallenge（#29 反例之一）
    "战斗HUD",         # SpecialBattleWait
    "结算页",          # SpecialResultContinue（#27）
)


def chain_step_pages(scene: str | None = None) -> tuple[str, ...]:
    """链上步骤页面名（#37）：任何被注入的事件都不得命中这些页面。

    ``scene`` 缺省 = 缺省场景（当前唯一一个 = 领主战族），返回该场景**有序选取**的页面
    （见 :class:`PageRuleRegistry`）。**按场景派生** —— 绝不是各场景页面的累积并集：
    否则领主战被注入的事件会被拿去对别的场景的页面校验，正是 #18/#29/#37 要终结的状态。
    """
    return _ensure_scenes().chain_step_pages(scene)


def is_chain_step_page(name: str, scene: str | None = None) -> bool:
    """``name`` 是否为链上步骤页面（#37 通用不变量用）；``scene`` 缺省 = 缺省场景。"""
    return name in chain_step_pages(scene)


def page_rules() -> list[PageRule]:
    """返回全局判据的一份副本（调用方不得就地改注册表）。"""
    return list(PAGE_RULES)


def page_rule(name: str) -> PageRule:
    """按页面名取全局判据；未定义则 KeyError（调用方据此报错，绝不静默）。"""
    for rule in PAGE_RULES:
        if rule.name == name:
            return rule
    raise KeyError(f"未定义的页面判据：{name!r}")


def duplicate_rule_names() -> list[str]:
    """全局注册表里声明了多次的页面名。

    ADR-0003 要求判据全局唯一，因此这里**必须恒为空**。留着它，是为了让
    「有人往注册表里抄了第二份同名列」这件事能被离线守卫当场抓住，而不是静默地
    让后一份覆盖前一份。
    """
    return default_registry().duplicates()


# ---------------------------------------------------------------------------
# ★#58 / E1：页面判据【注册表】—— 全局唯一一份判据 + 每场景有序选取 + 显式覆盖★
#
# ADR-0003 要的是「判据全局唯一、场景只按名引用、差异才覆盖」。上面 :data:`PAGE_RULES`
# 仍是**唯一一份**全局判据表；本段把它包成 :class:`PageRuleRegistry`：
#
#   * :meth:`PageRuleRegistry.register` —— 登记一个场景：``pages`` 是它**有序选取**的
#     规则名（引用全局表、不复制判据）；``overrides`` 是该场景的**具名显式覆盖**
#     （``scene.config.Override``：owner + rule + reason）—— 覆盖进 ``override_report``、
#     被 drift 报告，绝不隐形；
#   * :meth:`PageRuleRegistry.chain_step_pages` —— **按场景派生**「链上步骤页面集合」
#     （#37 用）：即该场景的有序页面选取；**绝不是各场景页面的累积并集**（否则一个场景
#     的事件会被拿去对别的场景的页面校验 —— 正是 #18/#29/#37 要终结的状态）。
#
# 场景从 ``scene.lord_battle`` 这类**配置数据文件**惰性登记（:func:`_register_default_scenes`）：
# 本模块**不**在顶层 import 配置（``scene.config`` 依赖本模块，顶层 import 会成环），
# 只在真正需要 per-scene 视图时惰性取用。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneSelection:
    """一个场景对全局判据注册表的**有序选取** + 该场景的**具名覆盖**（ADR-0003）。

    * ``scene``     场景 id（= ``FamilyConfig.family.id``）；
    * ``pages``     有序页面名元组 —— **引用**全局注册表里的规则名（不复制判据）；
    * ``overrides`` 该场景的具名覆盖（``scene.config.Override``：owner + rule + reason）。
    """

    scene: str
    pages: tuple[str, ...]
    overrides: tuple = ()


class PageRuleRegistry:
    """页面判据注册表：全局唯一一份判据 + 每场景按名选取的有序子集 + 显式覆盖。

    刻意**不复制** ``rules``：注册表与 :data:`PAGE_RULES` 是同一批对象（同一份真源），
    因此「有人往全局表里抄了第二份同名列」当场对 :meth:`duplicates` 可见。
    """

    def __init__(self, rules: list[PageRule]):
        self._rules = rules            # 同一份对象（不复制；见类文档）
        self._scenes: dict[str, SceneSelection] = {}
        self._order: list[str] = []

    @property
    def rules(self) -> list[PageRule]:
        """全局判据表的一份副本（调用方不得就地改注册表）。"""
        return list(self._rules)

    def rule(self, name: str) -> PageRule:
        """按页面名取判据；未定义则 ``KeyError``（调用方据此报错，绝不静默）。"""
        for rule in self._rules:
            if rule.name == name:
                return rule
        raise KeyError(f"未定义的页面判据：{name!r}")

    def duplicates(self) -> list[str]:
        """注册表里声明了多次的页面名（ADR-0003：必须恒为空；非空 = 判据不唯一）。"""
        counts: dict[str, int] = {}
        for rule in self._rules:
            counts[rule.name] = counts.get(rule.name, 0) + 1
        return sorted(n for n, c in counts.items() if c > 1)

    def register(self, scene: str, pages, overrides=()) -> SceneSelection:
        """登记一个场景的有序选取（+ 具名覆盖），校验后返回 :class:`SceneSelection`。

        校验（任一条不满足即 ``ConfigError``，绝不静默接受）：

        * ``pages`` 里每个名字必须是全局注册表里的判据（场景只引用、不发明页面）；
        * 每个覆盖必须是**具名显式**的：``rule`` 存在、``owner`` 与 ``reason`` 非空
          （ADR-0003：覆盖不得隐形）。
        """
        from .config import ConfigError  # 惰性：避免 config ↔ page_rules 顶层环形导入

        pages = tuple(pages)
        overrides = tuple(overrides)
        known = {r.name for r in self._rules}
        for p in pages:
            if p not in known:
                raise ConfigError(
                    f"场景 {scene!r} 选取了未登记的页面判据 {p!r}（判据只在全局注册表里定义）"
                )
        for o in overrides:
            rule = getattr(o, "rule", None)
            owner = getattr(o, "owner", "")
            reason = getattr(o, "reason", "")
            if not rule or rule not in known:
                raise ConfigError(f"场景 {scene!r} 的覆盖引用了不存在的页面判据 {rule!r}")
            if not owner:
                raise ConfigError(
                    f"场景 {scene!r} 对页面 {rule!r} 的覆盖没有 owner（覆盖必须具名，不得隐形）"
                )
            if not reason:
                raise ConfigError(
                    f"场景 {scene!r} 对页面 {rule!r} 的覆盖没有 reason（覆盖必须显式说明为什么）"
                )
        sel = SceneSelection(scene, pages, overrides)
        if scene not in self._scenes:
            self._order.append(scene)
        self._scenes[scene] = sel
        return sel

    def scenes(self) -> tuple[str, ...]:
        """已登记场景 id（按登记顺序）。"""
        return tuple(self._order)

    @property
    def default_scene(self) -> str | None:
        """缺省场景 = 第一个登记的场景（当前唯一一个 = 领主战族）。"""
        return self._order[0] if self._order else None

    def selection(self, scene: str) -> SceneSelection:
        """取某场景的有序选取；未登记则 ``KeyError``（绝不臆造）。"""
        try:
            return self._scenes[scene]
        except KeyError:
            raise KeyError(f"未登记的场景：{scene!r}（已登记：{self._order}）") from None

    def selection_default(self) -> SceneSelection:
        """取缺省场景的有序选取；一个场景都没登记则 ``KeyError``。"""
        scene = self.default_scene
        if scene is None:
            raise KeyError("注册表里还没有登记任何场景")
        return self._scenes[scene]

    def chain_step_pages(self, scene: str | None = None) -> tuple[str, ...]:
        """该场景的链上步骤页集（#37）——**按场景派生**，不是各场景页面的累积并集。"""
        sel = self.selection_default() if scene is None else self.selection(scene)
        return tuple(sel.pages)

    def overrides(self, scene: str | None = None) -> list:
        """该场景声明的具名覆盖（ADR-0003：覆盖不得隐形；由 ``override_report`` 报告）。"""
        sel = self.selection_default() if scene is None else self.selection(scene)
        return list(sel.overrides)


# ---------------------------------------------------------------------------
# 缺省注册表 + 惰性场景登记（#58 / E1）
# ---------------------------------------------------------------------------
_REGISTRY: "PageRuleRegistry | None" = None


def default_registry() -> PageRuleRegistry:
    """全局缺省注册表（进程内单例；判据表 = :data:`PAGE_RULES` 本身，不复制）。

    **不**触发场景登记（那是 :func:`_ensure_scenes` 的事）—— 保证仅在真正需要 per-scene
    视图时才惰性 import 配置数据。
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = PageRuleRegistry(PAGE_RULES)
    return _REGISTRY


def register_family_config(reg: PageRuleRegistry, cfg) -> SceneSelection:
    """把一个 ``FamilyConfig`` 登记为一个场景：选取 = ``family.页序``，覆盖 = ``cfg.overrides``。"""
    return reg.register(cfg.family.id, cfg.family.页序, cfg.overrides)


def _register_default_scenes(reg: PageRuleRegistry) -> None:
    """登记缺省场景 = 领主战族（配置数据在 ``scene.lord_battle``）。

    惰性 import：``scene.config`` 依赖本模块，顶层 import 会成环。新增一个场景时在此追加
    （或由调用方用 :func:`register_family_config` 显式登记）——与 ``scene.drift`` 缺省取
    ``LORD_BATTLE`` 同一手法。
    """
    from .lord_battle import LORD_BATTLE  # 惰性：配置数据文件（避免顶层环形导入）

    register_family_config(reg, LORD_BATTLE)


def _ensure_scenes() -> PageRuleRegistry:
    """确保缺省注册表已登记场景后返回它（惰性；只在 per-scene 视图需要时取配置）。"""
    reg = default_registry()
    if not reg.scenes():
        _register_default_scenes(reg)
    return reg


def registered_scenes() -> tuple[str, ...]:
    """已登记的场景 id（惰性触发缺省场景登记）。"""
    return _ensure_scenes().scenes()


def selection_for(scene: str) -> SceneSelection:
    """取某场景的有序选取（惰性触发缺省场景登记）；未登记则 ``KeyError``。"""
    return _ensure_scenes().selection(scene)


def scene_overrides(scene: str | None = None) -> list:
    """某场景（缺省 = 缺省场景）声明的具名覆盖。"""
    return _ensure_scenes().overrides(scene)


def __getattr__(name: str):
    """模块级惰性属性（PEP 562）。

    :data:`CHAIN_STEP_PAGES` 不再是一张手写的全局常量，而是**按场景派生**的缺省场景
    链上步骤页集（= :func:`chain_step_pages`）；首次访问时才惰性派生（届时配置已可导入，
    不会成环）。这样它**永不**变成各场景页面的累积并集 —— #37 不变量因此保住。
    """
    if name == "CHAIN_STEP_PAGES":
        return chain_step_pages()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
