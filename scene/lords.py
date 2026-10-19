# -*- coding: utf-8 -*-
"""领主战 / 降临讨伐的【难度静态数据真源】（#106）。

本文件回答四个问题，回答的方式都是**可复核的数据**而不是注释里的说法：

1. 每个领主**一共有几档**（``max_tiers`` = M）；
2. 这 M 档的**解锁链**（谁先谁后，``tier_chain``）；
3. 认它用哪串字（列表页 ``row_name`` / 详情页 ``row_prefix``）；
4. 凭什么（``evidence`` 里每条都是仓内真实文件的逐条 OCR 读数）。

事实来源（本文件的每个结论都来自这几处，不凭空设计）：

* ``docs/research/lord-battle-difficulty-registry.md`` —— schema 与**证伪结论**（§2.4：旧静态表 4 行里 3 行不符）；
* ``docs/research/lord-battle-all-difficulty-unlock.md`` —— 解锁机制（§1.2 官方公告原文：逐档递进、按领主逐个算）；
* ``docs/spec/runner-delivery.md`` D6 / D7 / §4.4 —— 解禁判定用列表页 ``通关数 M/M``；难度数据**纯静态**，允许一次性 CLI 采集。

⚠ **这里没有、也永远不许有「每个领主支持哪些难度」这个字段** ⚠
--------------------------------------------------------------
「某领主当前可用哪几档」是**账号进度**，不是领主属性：
同一成员（红嫉机兵）在已通关账号上 4 档、在早期账号上**只有 ``中级``** —— 两张仓内帧直接对照：
``tools/frames/lord_detail_redjoss_cleared.png``（4 行全 COMPLETE!!）vs
``tools/frames/lord_detail_redjoss_early.png``（1 行 + NEW + 首次报酬）。
更狠的是**同一帧列表页证伪了整张旧表**（``tools/frames/lord_page_tab_lord.png``）：

============================  ==================  ==============================  ========
成员（列表页行）               列表页实读           旧静态 ``支持难度集``            判定
============================  ==================  ==============================  ========
猩红巨熊讨伐                   ``通关数3/4`` M=4    4 档                            ✅
艾基尔·嫉妒讨伐                ``通关数1/4`` M=4    ``("中级",)`` 1 档              ❌
背鳍三兄弟讨伐                 ``通关数1/4`` M=4    ``("高级","中级")`` 2 档        ❌
八岐大蛇讨伐                   ``通关数4/4`` M=4    ``("超级","高级+","高级")`` 3 档  ❌
============================  ==================  ==============================  ========

⇒ 存「支持难度集」= 存某账号某时刻的快照，换账号就是错的。**能静态化的只有 M + 解锁链 + 认证文本**。
调用方要判「本账号能打哪几档」时，读**列表页 ``通关数 N/M``**（或详情页的 ``COMPLETE!!`` /
``首次报酬`` / ``NEW``），**不要**把本文件的任何一个 tuple 当成「可用集」——
``tier_chain`` 是全集的**解锁顺序**，不是「已解锁的档」。

字段（:class:`Lord`）
--------------------
``slug``
    稳定 id，形如 ``{kind}/{行名}``（如 ``lord/妖狐讨伐``、``joss/红嫉机兵``）。
    账本 key 的原料（``agent/progress.py`` 的 ``normalize_key`` 会去空白、``\\``→``/``、合并重复 ``/``），
    **发布后不许改**：一改老账本全部失配。所以用「kind/行名」而不是「kind/序号」。
``kind``
    ``"lord"`` = 领主战页签、``"joss"`` = 降临讨伐页签。
    ★不要用「行名是否以『讨伐』结尾」判类别★：``无猾机兵`` / ``始龙之眼`` / ``圣夜的淘气鬼`` /
    ``碧愁机兵`` 都不带「讨伐」，而它们都是降临讨伐成员。
``row_name``
    列表页行名 = 点它的锚点，必须与真机**逐字**一致（真机行扫校正过，见 ``scene/lord_battle.py``）。
``row_regex``
    行名容错正则（OCR 会漏字/换字）。只放**真机实测出现过**的变体，例如
    ``^红[嫉族]机兵$``（早期帧把「红嫉机兵」读成「红嫉族机兵」）。
``row_prefix``
    **详情页认证文本前缀**（``None`` = 未实测）。详情页每行的行名 = ``row_prefix`` + 难度名，
    而它**不是**列表行名的拼接：``红嫉机兵`` 的详情页行名是 ``红机兵海茵莱特中级``（boss 名）。
    因此「进详情页是不是进了目标成员」要用前缀 + 难度词判，不能用行名。
``max_tiers`` / ``max_tiers_source`` / ``max_tiers_verified``
    **M**（总档数）/ 它从哪来 / 是否已有仓内证据。
    ``max_tiers_source`` 取值：``"list_page_n_of_m"``（列表页 ``通关数 N/M`` 的分母，**首选**）、
    ``"detail_page_rows"``（详情页「可见档全 COMPLETE!!」的档数）、``"unknown"``（未采集，M 为 ``None``）。
``tier_chain``
    **解锁链，升序**（低档 → 高档），如 ``("中级", "高级", "高级+", "超级")``。
    语义来自官方公告原文：「需先通关『潮汐巨妖 高级』与『潮汐巨妖 高级+』，才可参加『潮汐巨妖 超级』」
    ⇒ **逐档递进、按领主逐个算**（不是「打一次全开」，也不是按日期轮换）。
    ``()`` = 未采集。**完整时长度必须 == ``max_tiers``**（守卫强制）。
``row_labels``
    ``(难度, 详情页行名)`` 的逐行实测（可以只覆盖部分档）。``()`` = 未实测。
``evidence``
    证据串，格式 ``<仓库相对路径>|<读数/时间/score>``：
    ``|`` **前**必须是仓内真实文件（``hooks_106`` 校验存在性，缺文件即红 —— 这条直接补上了「注释里
    写着来源、但仓里没有那个东西」的老毛病，见调研 §4.1）；
    ``|`` **后**是人读摘录（采集日期 / OCR 原文 / box / score），不参与校验。
``verified``
    **全条目已验证** = M 已定 **且** 链完整（``len(tier_chain) == max_tiers``）**且** 每一档都有行名。
    它不表示「该账号能打这些档」——那件事本文件不表达（见上）。
``needs``
    还缺什么（``verified=False`` 时必须非空，守卫强制）。这些字符串由采集 CLI **派生**，别手写。

怎么扩充（拿新数据 → 落盘）
--------------------------
1. 采一帧真机：列表页（滚动到目标行，让 ``通关数 N/M`` 与该行同屏）或详情页（整屏，含全部难度行）；
2. 跑 ``.venv\\Scripts\\python.exe tools\\gen_lord_registry.py --live``，或把预采集的 OCR
   落成 JSON 后 ``--ocr-json <file>``（两者都**不用设备**、不消耗视觉额度）；
3. 在 ``tools/gen_lord_registry.py`` 里登记：``FRAMES``（帧清单）、``FRAME_OCR``（该帧 OCR 条目，
   假 OCR 用）；详情页帧还要在 ``DETAIL_PREFIXES`` 里登记**认证前缀 → 成员 slug**
   （没登记就报错，**绝不猜归属**——详情页标题会被 OCR 读错）；
4. ``--write`` 落盘：本文件的标记段 + ``assets/data/lords.json``（同一次渲染，两处不会不一致）；
5. 跑 ``tools/contract_hooks/hooks_106.py`` 与 ``tools/test_lord_registry.py``。

生成段纪律
----------
``LORDS`` 由标记段包住，**唯一写者**是 ``tools/gen_lord_registry.py --write``：

    # ---- BEGIN GENERATED: LORDS ----
    LORDS: tuple[Lord, ...] = (
        ...
    )
    # ---- END GENERATED: LORDS ----

手改标记段里的数据会被 ``hooks_106`` 打红（守卫用假 OCR 重跑一遍采集，要求**逐字一致**）。
想改数据：改采集侧（帧 / 登记表）或改 ``needs`` 的派生规则，然后 ``--write``。
标记段**之外**的部分（本 docstring、:class:`Lord`、:func:`pending`、查询函数）是手写的。

ADR-0001（配置为真源）：本文件是**人读真源**；``assets/data/lords.json`` 是它的**投影**
（给不能 import Python 的读者），由守卫钉成逐字相等，所以不是第二真源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .config import DIFFICULTIES

# ---------------------------------------------------------------------------
# 标记段（唯一写者 = tools/gen_lord_registry.py --write；hooks_106 校验逐字一致）
# ---------------------------------------------------------------------------
GENERATED_BEGIN_PREFIX = "# ---- BEGIN GENERATED: LORDS"
GENERATED_END_PREFIX = "# ---- END GENERATED: LORDS"

# ---------------------------------------------------------------------------
# 枚举值（守卫逐条校验；新增取值必须同时改守卫与 CLI）
# ---------------------------------------------------------------------------
#: ``kind``：领主战页签 / 降临讨伐页签。★类别只能用它判，不能看行名后缀★
KIND_LORD = "lord"
KIND_JOSS = "joss"
KINDS: tuple[str, ...] = (KIND_LORD, KIND_JOSS)

#: ``kind`` <-> ``scene.config.SUBFAMILIES`` 的子族名（一一对应）。
SUBFAMILY_BY_KIND: dict[str, str] = {KIND_LORD: "领主战", KIND_JOSS: "降临讨伐"}

#: ``max_tiers_source`` 的合法取值。
SOURCE_LIST = "list_page_n_of_m"
SOURCE_DETAIL = "detail_page_rows"
SOURCE_UNKNOWN = "unknown"
MAX_TIERS_SOURCES: tuple[str, ...] = (SOURCE_LIST, SOURCE_DETAIL, SOURCE_UNKNOWN)

#: 解锁链的**起始档**只能是这两档（真机：绝大多数是 ``中级``，``初级`` 只在 ``维·索拉斯讨伐``）。
ENTRY_DIFFICULTIES: tuple[str, ...] = ("初级", "中级")

#: 还缺什么的三条标准说法（``pending`` 用它，守卫也按它们判「缺什么必须写清」）。
NEED_MAX_TIERS = "缺 M（总档数）：需要列表页该行的 `通关数 N/M` 帧 OCR（分母 = M）"
NEED_TIER_CHAIN = "缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR"
NEED_ROW_PREFIX = "缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）"
NEED_TEXTS: tuple[str, ...] = (NEED_MAX_TIERS, NEED_TIER_CHAIN, NEED_ROW_PREFIX)


@dataclass(frozen=True)
class Lord:
    """一位领主战 / 降临讨伐成员的**难度静态事实**（详见模块 docstring 的字段表）。

    ★它不是「可用难度集」★：``tier_chain`` 是全集解锁顺序，不含任何账号进度。
    """

    slug: str
    kind: str
    row_name: str
    row_regex: str
    row_prefix: str | None
    max_tiers: int | None
    max_tiers_source: str
    max_tiers_verified: bool
    tier_chain: tuple[str, ...]
    row_labels: tuple[tuple[str, str], ...]
    evidence: tuple[str, ...]
    verified: bool
    needs: tuple[str, ...]

    # -- 派生查询（**不新增字段**：能算出来的一律算，避免两处打架）--------------
    @property
    def entry_difficulty(self) -> str | None:
        """**起始档**（解锁链首 = 最低档）。链未采集时取已实测行名里最低的那档。"""
        if self.tier_chain:
            return self.tier_chain[0]
        if self.row_labels:
            return min((d for d, _ in self.row_labels), key=DIFFICULTIES.index)
        return None

    @property
    def top_difficulty(self) -> str | None:
        """**最高档**（解锁链尾）。链未采集时返回 ``None``（不拿行名猜）。"""
        return self.tier_chain[-1] if self.tier_chain else None

    def unlock_edges(self) -> tuple[tuple[str, str], ...]:
        """解锁链的**边**（前档 → 后档），如 ``(("中级","高级"), ("高级","高级+"), …)``。"""
        return tuple(zip(self.tier_chain, self.tier_chain[1:]))

    def unlock_requires(self, difficulty: str) -> tuple[str, ...]:
        """打 ``difficulty`` 这一档**必须先通关**的档（= 链上所有更低的档）。

        依据官方公告：超级 requires (高级, 高级+) —— 是**全部更低档**，不是只差一档。
        该难度不在链上（或链未采集）→ 返回 ``()``（**不代表没有前置**，只代表本文件没有这条事实）。
        """
        if difficulty not in self.tier_chain:
            return ()
        return tuple(self.tier_chain[: self.tier_chain.index(difficulty)])

    def tier_position(self, difficulty: str) -> int | None:
        """详情页**纵向位置**（1 = 最上一行）。实测行序是**降序**（顶 = 最高档），故 1 = 最高档。"""
        if difficulty not in self.tier_chain:
            return None
        return len(self.tier_chain) - self.tier_chain.index(difficulty)

    def detail_row_label(self, difficulty: str) -> str | None:
        """该档在详情页的**整串行名**（未实测 → ``None``；调用方应退回难度词正则）。"""
        for name, label in self.row_labels:
            if name == difficulty:
                return label
        return None


def pending(kind: str, row_name: str) -> Lord:
    """**占位**条目：还没有任何仓内证据的成员（M / 链 / 认证文本全缺）。

    刻意做成函数而不是 37 份重复字面量：占位条目**没有信息**，重复只会掩盖「这里其实没数据」。
    """
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {KINDS} 之一，收到 {kind!r}")
    return Lord(
        slug=f"{kind}/{row_name}",
        kind=kind,
        row_name=row_name,
        row_regex=f"^{row_name}$",
        row_prefix=None,
        max_tiers=None,
        max_tiers_source=SOURCE_UNKNOWN,
        max_tiers_verified=False,
        tier_chain=(),
        row_labels=(),
        evidence=(),
        verified=False,
        needs=(NEED_MAX_TIERS, NEED_TIER_CHAIN),
    )


# ---- BEGIN GENERATED: LORDS（唯一写者 = tools/gen_lord_registry.py --write；手改会被 hooks_106 打红）----
LORDS: tuple[Lord, ...] = (
    # ==== 已采集：字段来自仓内真机帧，`evidence` 里每个 `|` 前路径由 hooks_106 校验存在性 ====
    Lord(
        slug='lord/猩红巨熊讨伐',
        kind='lord',
        row_name='猩红巨熊讨伐',
        row_regex='^猩红巨熊讨伐$',
        row_prefix=None,
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(),
        evidence=(
            'tools/frames/lord_page_tab_lord.png|2026-10-17 OCR: 行「猩红巨熊讨伐」y=1174 + `通关数3/4` y=1248 score=0.958',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    Lord(
        slug='lord/背鳍三兄弟讨伐',
        kind='lord',
        row_name='背鳍三兄弟讨伐',
        row_regex='^背鳍三兄弟讨伐$',
        row_prefix=None,
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(),
        evidence=(
            'tools/frames/lord_page_tab_lord.png|2026-10-17 OCR: 行「背鳍三兄弟讨伐」y=1392 + `通关数1/4` y=1464 score=0.973',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    Lord(
        slug='lord/八岐大蛇讨伐',
        kind='lord',
        row_name='八岐大蛇讨伐',
        row_regex='^八岐大蛇讨伐$',
        row_prefix=None,
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(),
        evidence=(
            'tools/frames/lord_page_tab_lord.png|2026-10-17 OCR: 行「八岐大蛇讨伐」y=1608 + `通关数4/4` y=1680 score=0.959，同行 COMPLETE!! 徽标',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    Lord(
        slug='lord/艾基尔·嫉妒讨伐',
        kind='lord',
        row_name='艾基尔·嫉妒讨伐',
        row_regex='^艾基尔·嫉妒讨伐$',
        row_prefix=None,
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(),
        evidence=(
            'tools/frames/lord_page_tab_lord.png|2026-10-17 OCR: 行「艾基尔·嫉妒讨伐」y=960 + `通关数1/4` y=1032 score=0.972',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    Lord(
        slug='lord/妖狐讨伐',
        kind='lord',
        row_name='妖狐讨伐',
        row_regex='^妖狐讨伐$',
        row_prefix='妖狐',
        max_tiers=4,
        max_tiers_source='detail_page_rows',
        max_tiers_verified=True,
        tier_chain=('中级', '高级', '高级+', '超级'),
        row_labels=(
            ('中级', '妖狐中级'),
            ('高级', '妖狐高级'),
            ('高级+', '妖狐高级+'),
            ('超级', '妖狐超级'),
        ),
        evidence=(
            'tools/frames/lord_detail_multidiff.png|2026-10-17 OCR: 4 行 妖狐中级 / 妖狐高级 / 妖狐高级+ / 妖狐超级（纵向 y=456/648/837/1028，自上而下 = 难度降序）；全 COMPLETE!!（该账号已清空可见档）；分类「领主战」；标题 OCR「妖狐」',
        ),
        verified=True,
        needs=(
            '⚠ 单帧单账号：M 由详情页「可见档全 COMPLETE!!」推得；若某档（如 地狱级）是活动期开关，M 可能被低估 —— 需第二账号 / 活动期对照复算（调研 §6 #1/#6）',
            '⚠ 地狱级是否属于该成员未实测（真机 46 成员里 11 个有；出现条件未证实，调研 §1.3 / §6 #6）',
        ),
    ),
    Lord(
        slug='lord/诅咒弧魔艾基尔讨伐',
        kind='lord',
        row_name='诅咒弧魔艾基尔讨伐',
        row_regex='^诅咒弧魔艾基尔讨伐$',
        row_prefix='诅咒弧魔艾基尔',
        max_tiers=None,
        max_tiers_source='unknown',
        max_tiers_verified=False,
        tier_chain=(),
        row_labels=(
            ('中级', '诅咒弧魔艾基尔中级'),
        ),
        evidence=(
            'tools/frames/lord_detail_singlediff.png|2026-10-17 OCR: 1 行 诅咒弧魔艾基尔中级（纵向 y=458，自上而下 = 难度降序）；含未通关行（NEW / 首次报酬 在场）；分类「领主战」；标题 OCR「诅咒弧魔艾基尔」',
        ),
        verified=False,
        needs=(
            '缺 M（总档数）：需要列表页该行的 `通关数 N/M` 帧 OCR（分母 = M）',
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
        ),
    ),
    Lord(
        slug='joss/无猾机兵',
        kind='joss',
        row_name='无猾机兵',
        row_regex='^无猾机兵$',
        row_prefix='机工神兵菲诺梅那',
        max_tiers=5,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(
            ('中级', '机工神兵菲诺梅那中级'),
        ),
        evidence=(
            'tools/frames/lord_page_tab_joss.png|2026-10-17 OCR: 行「无猾机兵」y=1172 + `通关数5/5` y=1248 score=0.944，同行 COMPLETE!! 徽标',
            'tools/frames/lord_detail_naught_robot_c1.jpg|2026-10-17 OCR: 1 行 机工神兵菲诺梅那中级（纵向 y=458，自上而下 = 难度降序）；含未通关行（NEW / 首次报酬 在场）；分类「降临讨伐」；标题 OCR「无猾机兵」',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    Lord(
        slug='joss/红嫉机兵',
        kind='joss',
        row_name='红嫉机兵',
        row_regex='^红嫉族?机兵$',
        row_prefix='红机兵海茵莱特',
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=('中级', '高级', '高级+', '超级'),
        row_labels=(
            ('中级', '红机兵海茵莱特中级'),
            ('高级', '红机兵海茵莱特高级'),
            ('高级+', '红机兵海茵莱特高级+'),
            ('超级', '红机兵海茵莱特超级'),
        ),
        evidence=(
            'tools/frames/lord_page_tab_joss.png|2026-10-17 OCR: 行「红嫉机兵」y=1388 + `通关数4/4` y=1464 score=0.959，同行 COMPLETE!! 徽标',
            'tools/frames/lord_detail_redjoss_cleared.png|2026-10-17 OCR: 4 行 红机兵海茵莱特中级 / 红机兵海茵莱特高级 / 红机兵海茵莱特高级+ / 红机兵海茵莱特超级（纵向 y=458/649/840/1030，自上而下 = 难度降序）；全 COMPLETE!!（该账号已清空可见档）；分类「降临讨伐」；标题 OCR「红嫉机兵」',
            'tools/frames/lord_detail_redjoss_early.png|2026-10-17 OCR: 1 行 红机兵海茵莱特中级（纵向 y=458，自上而下 = 难度降序）；含未通关行（NEW / 首次报酬 在场）；分类「降临讨伐」；标题 OCR「红嫉族机兵」',
        ),
        verified=True,
        needs=(
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
            '⚠ 地狱级是否属于该成员未实测（真机 46 成员里 11 个有；出现条件未证实，调研 §1.3 / §6 #6）',
        ),
    ),
    Lord(
        slug='joss/苍叹机兵',
        kind='joss',
        row_name='苍叹机兵',
        row_regex='^苍叹机兵$',
        row_prefix=None,
        max_tiers=4,
        max_tiers_source='list_page_n_of_m',
        max_tiers_verified=True,
        tier_chain=(),
        row_labels=(),
        evidence=(
            'tools/frames/lord_page_tab_joss.png|2026-10-17 OCR: 行「苍叹机兵」y=1604 + `通关数4/4` y=1680 score=0.959，同行 COMPLETE!! 徽标',
        ),
        verified=False,
        needs=(
            '缺解锁链 / 认证文本：需要该成员详情页整屏的逐档行名帧 OCR',
            '缺详情页认证文本前缀（详情页行名 = 前缀 + 难度名）',
            '⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）',
        ),
    ),
    # ==== 未采集（占位）：M / 解锁链 / 认证文本都还没有仓内证据，`needs` 写清缺什么 ====
    pending('lord', '管理者讨伐'),
    pending('lord', 'Sec-5200Li讨伐'),
    pending('lord', '白虎讨伐'),
    pending('lord', '风将獠牙骑士讨伐'),
    pending('lord', '寄居蟹船长讨伐'),
    pending('lord', '潮汐巨妖讨伐'),
    pending('lord', '废墟魔像讨伐'),
    pending('lord', '废墟守卫·火讨伐'),
    pending('lord', '雷霆树妖讨伐'),
    pending('lord', '维·索拉斯讨伐'),
    pending('lord', '不死王瑞西塔尔讨伐'),
    pending('joss', '橙悚机兵'),
    pending('joss', '闪哭机兵'),
    pending('joss', '暗凛机兵'),
    pending('joss', '始龙之眼'),
    pending('joss', '为你奏响的镇魂歌'),
    pending('joss', '圣夜的淘气鬼'),
    pending('joss', '怨炎精灵兽'),
    pending('joss', '水狂精灵兽'),
    pending('joss', '魁雷精灵兽'),
    pending('joss', '威风精灵兽'),
    pending('joss', '巫光精灵兽'),
    pending('joss', '暗唤精灵兽'),
    pending('joss', '方舟守护者讨伐'),
    pending('joss', '赤之女王讨伐'),
    pending('joss', '青之女王讨伐'),
    pending('joss', '碧之女王讨伐'),
    pending('joss', '皓之女王讨伐'),
    pending('joss', '墨之女王讨伐'),
    pending('joss', '伊尔昂斯拉讨伐'),
    pending('joss', '伊尔梅塔雷讨伐'),
    pending('joss', '碧愁机兵'),
    pending('joss', '金之女王讨伐'),
    pending('joss', '伊尔格拉乌讨伐'),
    pending('joss', '伊劳德雷斯讨伐'),
    pending('joss', '伊萨巴迪卡讨伐'),
    pending('joss', '伊尔考普斯讨伐'),
)
# ---- END GENERATED: LORDS ----

#: slug -> 条目 / 行名 -> 条目（重复即视为数据错误，构造时当场炸，不静默取后者）。
def _index(entries: Sequence[Lord]) -> tuple[dict[str, Lord], dict[str, Lord]]:
    by_slug: dict[str, Lord] = {}
    by_row_name: dict[str, Lord] = {}
    for entry in entries:
        if entry.slug in by_slug:
            raise ValueError(f"scene/lords.py：slug 重复 {entry.slug!r}")
        if entry.row_name in by_row_name:
            raise ValueError(f"scene/lords.py：行名重复 {entry.row_name!r}")
        by_slug[entry.slug] = entry
        by_row_name[entry.row_name] = entry
    return by_slug, by_row_name


BY_SLUG, BY_ROW_NAME = _index(LORDS)


def by_slug(slug: str) -> Lord | None:
    """按 ``slug`` 取条目（账本里存的就是它）。"""
    return BY_SLUG.get(slug)


def by_row_name(row_name: str) -> Lord | None:
    """按**列表页行名**取条目（详情页选行后回查用）。"""
    return BY_ROW_NAME.get(row_name)


def coverage() -> dict[str, int]:
    """覆盖统计（报告/测试用）：总条目 / 有证据 / 全链验证 / 纯占位。"""
    return {
        "lords": len(LORDS),
        "with_evidence": sum(1 for entry in LORDS if entry.evidence),
        "fully_verified": sum(1 for entry in LORDS if entry.verified),
        "placeholders": sum(1 for entry in LORDS if not entry.evidence),
    }
