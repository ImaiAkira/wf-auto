# -*- coding: utf-8 -*-
"""领主战「全难度解禁」的**判定真源**（#100）—— 纯逻辑、无 I/O。

本文件只回答三个问题，回答方式都是**可离线复核的纯函数**：

1. 列表页那一行写的 ``通关数 N/M`` 到底读出来是几？（:func:`parse_progress`）
2. 这一轮**该打谁、打哪一档**？是不是已经全通？（:func:`plan_round`）
3. 什么时候**必须收工**（含三条终结 + 防死循环）？（:func:`should_stop`）

循环语义（运维裁决 D6，判定口径 = **(a)**）来自 ``docs/spec/runner-delivery.md`` §4.4：

1. 进领主战列表 → 读**每一行**的 ``通关数 N/M``；
2. 打掉所有 ``N < M`` 的领主（每个领主从**最低未通关档**往上打）；
3. 回列表**重读**，重复；
4. 终结：**全 ``M/M``**（主）+ **连续 2 轮没有新解锁**（兜底）+ **场次上限 60**（兜底，带原因收工）；
5. ★防死循环★：每轮必须**至少打一场**才允许继续，否则带原因退出。

为什么判定用 (a)（每轮重开列表、看 ``M/M``）而不是「详情页数 COMPLETE!!」：
``docs/research/lord-battle-all-difficulty-unlock.md`` §1.3 给了真机证据 —— **列表页每行自带
``通关数 N/M``**（``tools/frames/lord_page_tab_lord.png``：``通关数1/4`` / ``3/4`` / ``1/4`` /
``4/4``，score 0.958~0.973），``M`` 就是该领主的总档数、``N`` 是已通关档数 ⇒ ``N == M`` 的
领主**连详情页都不用进**。同一趟读数也是「解禁到底」的**唯一正面对账物**。

★本文件**不**存、也**不**推断「某账号能打哪几档」★
----------------------------------------------------
那是**账号进度**，不是领主属性：同一成员（红嫉机兵）在已通关账号上 4 档、在早期账号上
只有 ``中级``（``tools/frames/lord_detail_redjoss_cleared.png`` vs ``_early.png``）。
本文件读的是**列表页当场给的 N/M**，静态侧只提供 ``M``（``max_tiers``）与**解锁链**
（``tier_chain``，逐档递进，见 ``scene/lords.py`` 的模块 docstring）。二者对不上时
本文件**报冲突、不猜**（:data:`PROBLEM_M_CONFLICT`）。

★本文件**不**碰设备、不 import ``maa``★：它被 ``agent/lords_impl.py``（运行期）、
``tools/test_lords_unlock.py``（单测）与 ``tools/contract_hooks/hooks_100.py``（守卫）共用。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .config import DIFFICULTIES
from .lords import LORDS, Lord

# ---------------------------------------------------------------------------
# 终结条件（D6 §4.4；数值是**运维裁决值**，不是随手取的）
# ---------------------------------------------------------------------------
#: 场次上限：整趟任务最多打多少场。超出 → 带原因收工（防止解禁把体力/时间烧光）。
SESSION_CAP: int = 60

#: 「连续 N 轮没有新解锁」的兜底阈值。= D6 原文的「连续 2 轮」。
IDLE_ROUND_LIMIT: int = 2

# ---------------------------------------------------------------------------
# 1. 列表页读数：通关数 N/M
# ---------------------------------------------------------------------------
#: 列表页进度标签的**唯一**字面量（真机：``通关数1/4``，见调研 §2.1）。
PROGRESS_LABEL: str = "通关数"

#: 解析正则（**在 NFKC 归一化之后**用 ``re.search``，见 :func:`parse_progress`）。
#:
#: 逐段说明：
#:
#: * ``通\s*关\s*数`` —— 标签本身容忍被 OCR 拆开（``通 关 数``）；
#: * ``[\s:·.．・\-—–_=全共满]*`` —— 标签与数字之间的**噪声**：空格 / 冒号 / 点 / 破折号，
#:   以及真机可能夹进来的 ``全``（``通关数 全5/5``）、``共``、``满``；
#: * ``(\d{1,2})`` —— N。**两位封顶**：难度档数（``M``）不会到 3 位，读成 ``100/120``
#:   一类必然是别的东西（时间/分数），宁可拒收也不当成档数；
#: * ``\s*[/|\\⁄╱]\s*`` —— 分隔符。真机只见过 ``/``，但 OCR 把它读成 ``|`` / ``\`` / ``⁄`` /
#:   ``╱`` 是常见的（调研 §6 #2 点名了 ``通关数1|4`` 这个风险）；
#: * ``(?!\s*[/|\\⁄╱]\s*\d)`` —— **右界**：后面不许再跟一个「分隔符 + 数字」。
#:   ``通关数 3/4/5`` 是**歧义读数**（到底是 3/4 还是 4/5？），必须拒收而不是取前两段。
PROGRESS_RE: str = (
    r"通\s*关\s*数"
    r"[\s:·.．・\-—–_=全共满]*"
    r"(\d{1,2})"
    r"\s*[/|\\⁄╱]\s*"
    r"(\d{1,2})"
    r"(?!\s*[/|\\⁄╱]\s*\d)"
)

#: 正例（``parse_progress`` 必须读对；每条都注明它防的是什么真机问题）。
POSITIVE_CASES: tuple[tuple[str, int, int, str], ...] = (
    ("通关数3/4", 3, 4, "真机原样（tools/frames/lord_page_tab_lord.png，score 0.958）"),
    ("通关数 3/4", 3, 4, "标签与数字之间多一个空格（OCR 把两段分开返回时常见）"),
    ("通关数 3 / 4", 3, 4, "数字与分隔符两侧都有空格"),
    ("通关数 全5/5", 5, 5, "标签后夹了「全」（真机「通关数」常与相邻字粘连成一段）"),
    ("通关数：4/4", 4, 4, "标签后是全角冒号"),
    ("通关数３／４", 3, 4, "全角数字 + 全角斜杠（NFKC 归一化）"),
    ("通关数1|4", 1, 4, "分隔符被读成竖线（调研 §6 #2 点名的风险）"),
    ("通关数5/5", 5, 5, "全通行（无猾机兵，tools/frames/lord_page_tab_joss.png 通关数5/5）"),
    ("通关数0/4", 0, 4, "一档都没打过（N=0 是合法读数，不能当成「读不到」）"),
)

#: 反例（``parse_progress`` 必须返回 ``None``；格式 = (输入, 为什么必须拒收)）。
REJECTED_CASES: tuple[tuple[str, str], ...] = (
    ("通关数", "只有标签没有数字"),
    ("通关数 3/", "缺分母"),
    ("通关数 3/4/5", "歧义读数（两个分母）—— 必须拒收而不是取前两段"),
    ("通关数 3 4", "缺分隔符"),
    ("角色数 3/4", "标签不对（别把别的计数当成进度）"),
    ("1234", "没有标签 —— 裸数字可能是时间/分数/评分"),
    ("通关数 100/120", "三位数：档数不会到 100，读成它必然是别的东西"),
    ("首次报酬", "详情页的未通关标记，不是进度读数"),
    ("更新列表", "列表页判据，不是进度读数"),
    ("", "空串"),
)


def parse_progress(text: str) -> tuple[int, int] | None:
    """从一段 OCR 文本里读 ``通关数 N/M``，返回 ``(N, M)``；读不到返回 ``None``。

    ★容忍什么★（全部来自真机或调研点名的抖动，见 :data:`PROGRESS_RE` 与
    :data:`POSITIVE_CASES`）：标签被拆开、标签与数字之间夹噪声、全角数字/全角斜杠、
    分隔符被读成 ``|`` / ``\\`` / ``⁄`` / ``╱``、数字两侧空格。

    ★拒收什么★（见 :data:`REJECTED_CASES`）：没有标签的裸数字、缺分母、
    **两个分母的歧义读数**（``3/4/5``）、三位数、标签不对。

    ★本函数只做**语法**判定★：``N > M`` 仍然返回 ``(N, M)``（例如 ``通关数4/3``）——
    那是**语义**脏数据，由 :func:`plan_round` 抛 :class:`LordsDataError` 报错。
    这里不先斩后奏，是为了让「读数异常」在守卫里能被**分别**验证（解析 vs 规划）。
    ``M == 0`` 属例外：分母为 0 在语法上毫无意义（档数至少 1），直接当作读错返回 ``None``。
    """
    if not text:
        return None
    # NFKC：全角数字/全角斜杠/全角冒号 → 半角（真机帧里两种都出现过，见调研 §6 #2）
    normalized = unicodedata.normalize("NFKC", str(text))
    match = _PROGRESS_RE.search(normalized)
    if match is None:
        return None
    n, m = int(match.group(1)), int(match.group(2))
    if m <= 0:
        return None
    return (n, m)


_PROGRESS_RE = re.compile(PROGRESS_RE)

# ---------------------------------------------------------------------------
# 列表页的「行」：把每个 通关数 挂到它所属的那一行行名上
# ---------------------------------------------------------------------------
#: 行名与进度的**最大纵向间距**（720 空间）。真机实测（1080 帧 ÷1.5 换算）：
#: 行名 ``艾基尔·嫉妒讨伐`` y=640（中心 654）与 ``通关数1/4`` y=688（中心 702）→ dy ≈ 48；
#: 相邻行行距 ≈ 144 ⇒ 取 60 既能容纳 48 的偏移，又不会跨到相邻行。
MAX_NAME_DY: int = 60

#: 不是行名的文本（列表页上的固定元素 / 徽标）。它们不参与「谁是我的行名」竞争。
NOT_A_ROW_NAME: tuple[str, ...] = (
    "更新列表",
    "NEW",
    "首次报酬",
    "通过房间号码参加",
)

#: 行名与进度之间的横向要求：进度必须在行名**右侧**至少这么多像素（720 空间）。
MIN_NAME_LEFT_GAP: int = 20


@dataclass(frozen=True)
class RowReading:
    """列表页**一行**的读数：行名 + ``通关数 N/M`` + 两个框（720 空间）。"""

    name: str
    n: int
    m: int
    name_box: tuple[int, int, int, int]
    progress_box: tuple[int, int, int, int]

    @property
    def pair(self) -> tuple[int, int]:
        """``(N, M)``。"""
        return (self.n, self.m)

    @property
    def complete(self) -> bool:
        """该领主是否已 ``M/M``（= 已解禁到底，连详情页都不用进）。"""
        return self.n == self.m


def _center(box: Sequence[int]) -> tuple[float, float]:
    x, y, w, h = box[0], box[1], box[2], box[3]
    return (x + w / 2.0, y + h / 2.0)


def _is_name_candidate(text: str) -> bool:
    """这段文本有没有资格当「领主行名」。"""
    stripped = (text or "").strip()
    if not stripped or stripped in NOT_A_ROW_NAME:
        return False
    if parse_progress(stripped) is not None:      # 进度自己不是行名
        return False
    if re.fullmatch(r"[\d\s/|\\⁄╱.,:：]+", stripped):  # 纯数字/纯符号不是行名
        return False
    return True


def group_progress_rows(
    items: Iterable[tuple[str, Sequence[int]]],
    *,
    max_dy: int = MAX_NAME_DY,
    min_left_gap: int = MIN_NAME_LEFT_GAP,
) -> tuple[tuple[RowReading, ...], tuple[tuple[str, tuple[int, int, int, int]], ...]]:
    """把一屏 OCR 项 ``[(text, box), ...]`` 归成「列表页行」。

    返回 ``(rows, orphans)``：

    * ``rows``：按纵向排序的 :class:`RowReading`（每个 ``通关数 N/M`` 都挂到了左边最近的
      行名上 —— 判据是**几何**：进度在行名右侧、纵向间距 ≤ ``max_dy``，取纵向最近的一个，
      并优先取横向更靠右的那个）；
    * ``orphans``：读到了 ``通关数``、但左边 ``max_dy`` 内没有行名可挂的项（``(text, box)``）。
      ★它们不会被静默丢掉★ —— 真机里 ``通关数1/1``（``五王连战`` 那种不属于花名册的行）
      就是这一类的真实样本（``tools/contract_hooks/hooks_106`` 的采集 CLI 也单独返回它）。

    为什么用几何而不是「行名必须出现在花名册里」：行名会被 OCR 读错（``红嫉族机兵``、
    ``降临过伐``），拿花名册过滤会**连带丢掉真行** —— 归属问题留给 :func:`plan_round`
    显式报 :data:`PROBLEM_UNKNOWN_ROW`，不在这里悄悄筛。
    """
    materialized: list[tuple[str, tuple[int, int, int, int]]] = []
    for text, box in items:
        box4 = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
        materialized.append((str(text or "").strip(), box4))

    names = [item for item in materialized if _is_name_candidate(item[0])]
    rows: list[RowReading] = []
    orphans: list[tuple[str, tuple[int, int, int, int]]] = []

    for text, box in materialized:
        parsed = parse_progress(text)
        if parsed is None:
            continue
        progress_cx, progress_cy = _center(box)
        best: tuple[float, float, tuple[str, tuple[int, int, int, int]]] | None = None
        for name_text, name_box in names:
            name_cx, name_cy = _center(name_box)
            if name_cx >= progress_cx:                     # 行名必须在进度左侧
                continue
            if progress_cx - (name_box[0] + name_box[2]) < min_left_gap:
                continue                                    # 太挤：不是「左名右进度」的版式
            dy = abs(progress_cy - name_cy)
            if dy > max_dy:
                continue
            # 先比纵向最近，再比横向更靠右（同一行内更贴近进度的那个）
            key = (dy, -name_cx)
            if best is None or key < best[0:2]:
                best = (dy, -name_cx, (name_text, name_box))
        if best is None:
            orphans.append((text, box))
            continue
        rows.append(
            RowReading(
                name=best[2][0],
                n=parsed[0],
                m=parsed[1],
                name_box=best[2][1],
                progress_box=box,
            )
        )

    rows.sort(key=lambda row: (row.name_box[1], row.name_box[0]))
    return (tuple(rows), tuple(orphans))


# ---------------------------------------------------------------------------
# 2. 一轮要打谁 / 打哪一档
# ---------------------------------------------------------------------------
#: ``RoundPlan.problems`` 的 kind 取值（★每一条都是「不静默」的姿态★）。
PROBLEM_UNKNOWN_ROW = "unknown_row"
PROBLEM_NO_CHAIN = "no_chain"
PROBLEM_M_CONFLICT = "m_conflict"
PROBLEM_DUPLICATE = "duplicate_row"


class LordsDataError(ValueError):
    """列表页读数**脏**到无法规划（例如 ``通关数4/3``）。★绝不静默跳过★。"""


@dataclass(frozen=True)
class Problem:
    """一行「读到了、但这一轮没法按它打」的原因（带行名，绝不吞）。"""

    kind: str
    row_name: str
    detail: str


@dataclass(frozen=True)
class Target:
    """本轮要打的**一个**目标：哪一行 + 哪一档。"""

    row_name: str
    #: 要打的难度档；``None`` = 静态链未采集（``tier_chain`` 为空），**必须到详情页**
    #: 按 ``NEW`` / ``首次报酬`` 定档（调研 §3.6 运行时判据），本文件不猜。
    difficulty: str | None
    n: int
    m: int

    @property
    def pair(self) -> tuple[str, str | None]:
        """``(行名, 档位)`` —— 本票要求的输出形状。"""
        return (self.row_name, self.difficulty)

    @property
    def tier_index(self) -> int:
        """该档在解锁链上的**位置**（0 = 起始档）。``N`` 个已通关 ⇒ 目标 = ``链[N]``。"""
        return self.n


@dataclass(frozen=True)
class RoundPlan:
    """一轮的规划结果（纯数据）。"""

    targets: tuple[Target, ...]
    all_done: bool
    rows: tuple[RowReading, ...]
    problems: tuple[Problem, ...] = ()

    @property
    def pairs(self) -> tuple[tuple[str, str | None], ...]:
        """本轮要打的 ``[(行名, 档位), ...]``（按列表页顺序）。"""
        return tuple(target.pair for target in self.targets)

    @property
    def needs_detail(self) -> tuple[Target, ...]:
        """档位待定的目标（静态链未采集）—— 到详情页按 ``NEW``/``首次报酬`` 定档。"""
        return tuple(t for t in self.targets if t.difficulty is None)


def _as_reading(row) -> tuple[str, int, int]:
    """把一行读数归一成 ``(行名, N, M)``（容忍 :class:`RowReading` / 三元组 / 映射）。"""
    if isinstance(row, RowReading):
        return (row.name, row.n, row.m)
    if isinstance(row, Mapping):
        return (str(row.get("name", "")), int(row["n"]), int(row["m"]))
    name, n, m = row
    return (str(name), int(n), int(m))


def _index_registry(registry: Sequence[Lord] | None) -> dict[str, Lord]:
    if registry is None:
        registry = LORDS
    return {entry.row_name: entry for entry in registry}


def plan_round(rows, registry: Sequence[Lord] | None = None) -> RoundPlan:
    """**本轮该打谁**：列表页读数 + 静态花名册 → 目标 + 是否全通。

    ``rows``：列表页**一趟**的读数，元素可以是 :class:`RowReading`、三元组 ``(行名, N, M)``
    或含 ``name``/``n``/``m`` 的映射（方便单测与真机注入）。

    ``registry``：静态花名册（缺省 ``scene.lords.LORDS``）。★只提供 ``M`` 与解锁链★ ——
    「哪几档可用」是账号状态，不在它里面（见 :mod:`scene.lords` 的 docstring）。

    规则（逐条都有真机/公告依据）：

    * ``N == M`` → 该领主已解禁到底，**不产生目标**；
    * ``N < M`` 且静态链完整且 ``len(链) == M`` → 目标档 = ``链[N]``
      （逐档递进：官方公告「需先通关高级与高级+才可参加超级」⇒ 已通关 ``N`` 档 ⇒
      下一个就是链上第 ``N`` 个）；
    * ``N < M`` 但静态链未采集 → 仍然**给出目标**（``difficulty=None``），并报
      :data:`PROBLEM_NO_CHAIN`：★绝不静默跳过★，由调用方到详情页按 ``NEW``/``首次报酬`` 定档；
    * 静态 ``M``/链长与列表页 ``M`` 冲突 → **不给目标**并报 :data:`PROBLEM_M_CONFLICT`
      （拿错的分母去取档 = 打错档；宁可这轮空着，让 :func:`should_stop` 带原因收工）；
    * 行名不在花名册 → 报 :data:`PROBLEM_UNKNOWN_ROW`（OCR 读错 / 新领主 / 活动行）；
    * ``N > M`` → 抛 :class:`LordsDataError`（**报错，不是静默跳过**）。

    ``all_done`` = 读到了行 **且** 每行都 ``N == M``。★零行不算全通★ —— 把「一屏都没读到」
    当成「全部解禁」是「转述式已验证」的另一种形态（``docs/spec/wuchong-spec.md:200``）。

    同一行名出现多次（调用方把多趟读数拼起来时）→ 只取**第一次**，并在 ``problems`` 里记
    :data:`PROBLEM_DUPLICATE`。
    """
    index = _index_registry(registry)
    targets: list[Target] = []
    problems: list[Problem] = []
    readings: list[RowReading | None] = []
    seen: dict[str, tuple[int, int]] = {}

    for raw in rows:
        name, n, m = _as_reading(raw)
        if m <= 0:
            raise LordsDataError(f"行「{name}」的 通关数 {n}/{m} 分母 ≤ 0 —— 这不是档数读数")
        if n > m:
            raise LordsDataError(
                f"行「{name}」的 通关数 {n}/{m} 分子大于分母 —— 脏数据（已通关档数不可能超过总档数）；"
                f"正常形态见 tools/frames/lord_page_tab_lord.png（1/4、3/4、1/4、4/4）。"
                f"★不当成 0 档、也不静默跳过★：读错就重读，别按错的读数去打。"
            )
        readings.append(raw if isinstance(raw, RowReading) else None)

        if name in seen:
            if seen[name] != (n, m):
                problems.append(
                    Problem(
                        PROBLEM_DUPLICATE,
                        name,
                        f"同一行读到两个不同的 通关数：先 {seen[name][0]}/{seen[name][1]}、"
                        f"后 {n}/{m} —— 只按第一次的读数规划（多趟拼接时请先去重）",
                    )
                )
            continue
        seen[name] = (n, m)

        if n == m:
            continue                              # 已解禁到底

        entry = index.get(name)
        if entry is None:
            problems.append(
                Problem(
                    PROBLEM_UNKNOWN_ROW,
                    name,
                    f"列表页读到「{name}」的通关数 {n}/{m}，但静态花名册（scene/lords.py）没有这一行 —— "
                    f"OCR 读错 / 新领主 / 活动行；按错的字去点行 = 点错人，故本轮不为它规划",
                )
            )
            continue

        chain = tuple(entry.tier_chain)
        static_m = entry.max_tiers if entry.max_tiers is not None else (len(chain) or None)
        if static_m is not None and static_m != m:
            problems.append(
                Problem(
                    PROBLEM_M_CONFLICT,
                    name,
                    f"列表页 M={m}，静态 max_tiers={entry.max_tiers} / 链长={len(chain)} —— "
                    f"两边对不上就不按任何一边取档（宁可不打，也不打错档）；"
                    f"需要一帧新的列表页或详情页读数来定谁对",
                )
            )
            continue

        if not chain:
            targets.append(Target(name, None, n, m))
            problems.append(
                Problem(
                    PROBLEM_NO_CHAIN,
                    name,
                    f"静态解锁链未采集（scene/lords.py 的 tier_chain 为空）⇒ 档位待定："
                    f"到详情页按 `NEW` / `首次报酬` 定档（不是跳过，是交给运行时判据）",
                )
            )
            continue

        if len(chain) != m:
            problems.append(
                Problem(
                    PROBLEM_M_CONFLICT,
                    name,
                    f"列表页 M={m}，静态链只有 {len(chain)} 档（{chain}）—— 链不完整，不取档",
                )
            )
            continue

        difficulty = chain[n]
        if difficulty not in DIFFICULTIES:
            problems.append(
                Problem(
                    PROBLEM_M_CONFLICT,
                    name,
                    f"链上第 {n} 档 {difficulty!r} 不在难度词表 {DIFFICULTIES} 里 —— 静态数据坏了",
                )
            )
            continue
        requires = entry.unlock_requires(difficulty)
        if len(requires) != n:
            problems.append(
                Problem(
                    PROBLEM_M_CONFLICT,
                    name,
                    f"已通关 {n} 档，但「打 {difficulty} 需先通关 {len(requires)} 档」"
                    f"（{requires}）—— 解锁链与 N 不自洽，不取档",
                )
            )
            continue
        targets.append(Target(name, difficulty, n, m))

    all_done = bool(seen) and all(n == m for (n, m) in seen.values())
    return RoundPlan(
        targets=tuple(targets),
        all_done=all_done,
        rows=tuple(r for r in readings if r is not None),
        problems=tuple(problems),
    )


def round_gained(
    previous: Mapping[str, int] | None, rows
) -> tuple[bool, tuple[str, ...]]:
    """本轮相比上一轮，**是否有任何领主新解锁**（D6 的「连续 2 轮无新解锁」靠它判定）。

    ``previous``：上一轮的 ``{行名: N}``（首次跑传 ``None``）。
    返回 ``(是否新解锁, 新解锁的行名)``：某行 ``N`` 比上一轮**大**即算（= 又通了一档）。
    首次见到的行也算（``N >= 0 > -1``），因为「第一次读到它」本身就是新信息，不该算进展停滞。
    """
    prev = dict(previous or {})
    gained: list[str] = []
    for raw in rows:
        name, n, _m = _as_reading(raw)
        if n > prev.get(name, -1):
            gained.append(name)
    return (bool(gained), tuple(gained))


# ---------------------------------------------------------------------------
# 3. 什么时候必须收工
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class UnlockState:
    """**一轮结束**时的状态（:func:`should_stop` 的输入）。

    字段语义（全部由调用方在每轮末尾填；本文件只做判定）：

    * ``all_done``：本轮读数是否已经「所有行 M/M」（来自 :attr:`RoundPlan.all_done`）；
    * ``rows_read``：本轮读到多少行 ★零行 + ``all_done=True`` 是「假收工」，必须拦★；
    * ``planned``：本轮计划打几个领主（= ``len(plan.targets)``，含档位待定的）；
    * ``played``：本轮**实际打掉的场次**（★防死循环的核心：必须是 0 才算停滞★）；
    * ``sessions``：整趟任务累计场次；
    * ``no_progress_rounds``：连续多少轮没有新解锁（:func:`round_gained` 的结果累积）。
    """

    all_done: bool = False
    rows_read: int = 0
    planned: int = 0
    played: int = 0
    sessions: int = 0
    no_progress_rounds: int = 0
    session_cap: int = SESSION_CAP
    idle_round_limit: int = IDLE_ROUND_LIMIT


def should_stop(state: UnlockState) -> tuple[bool, str]:
    """该收工吗？返回 ``(stop, reason)`` —— ``reason`` 是**运维口径的用户可见原因**（D4）。

    判定顺序（先主后兜底，且**每一条都是「带原因」**）：

    1. **全 ``M/M``（主）**：停，理由是「全部解禁」。★但 ``rows_read == 0`` 时不算成功★：
       零行读数却宣布全通 = 假收工，按失败收工（理由说清）。
    2. **场次上限（兜底）**：``sessions >= session_cap`` → 停，理由里写清「未全通」。
    3. **★防死循环★**：本轮``played <= 0`` → 停。``planned == 0`` 时是「零目标却未全通」，
       ``planned > 0`` 时是「计划了却一场没打」——两种都必须走人，绝不允许原地空转。
    4. **连续 N 轮无新解锁（兜底）**：``no_progress_rounds >= idle_round_limit`` → 停。

    都不成立 → ``(False, "")``，允许进入下一轮。
    """
    if state.all_done:
        if state.rows_read <= 0:
            # ★注意措辞★：这里**不许**出现「全部解禁」这四个字 —— 守卫 hooks_100 用
            # 「reason 里有没有『全部解禁』」来区分「真收工」与「假收工」，措辞混了守卫就瞎了。
            return (
                True,
                "收工（可疑）：判了「全通」却一行都没读到 —— "
                "把「零行」当全通就是假收工，按失败收工，绝不假记账",
            )
        return (
            True,
            f"全部解禁：本轮读到 {state.rows_read} 个领主，全部 `通关数 M/M`"
            f"（累计 {state.sessions} 场）",
        )

    if state.sessions >= state.session_cap:
        return (
            True,
            f"场次上限 {state.session_cap} 已用尽（累计 {state.sessions} 场，"
            f"本轮计划 {state.planned} 个）—— 尚未全通，带原因收工",
        )

    if state.played <= 0:
        if state.planned == 0:
            return (
                True,
                f"防死循环：本轮零目标（读到 {state.rows_read} 行，但没有一行 N<M 可打）"
                f"却未判全通 —— 继续下去只会空转，带原因收工",
            )
        return (
            True,
            f"防死循环：本轮计划 {state.planned} 个目标却一场没打（累计 {state.sessions} 场）"
            f"—— 每轮必须至少打一场才允许继续，带原因收工",
        )

    if state.no_progress_rounds >= state.idle_round_limit:
        return (
            True,
            f"连续 {state.no_progress_rounds} 轮没有新解锁（兜底阈值 "
            f"{state.idle_round_limit}，累计 {state.sessions} 场）—— 带原因收工",
        )

    return (False, "")
