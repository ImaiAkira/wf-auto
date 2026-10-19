"""「批量副本清单」解析 + 计划模型（纯逻辑，不依赖 maa，离线可单测）。

清单文本格式（可由用户在界面里直接复制粘贴）：

     # 副本名,难度,次数        ← 以 # 开头是注释，空行忽略
     猩红巨熊讨伐,中级,3
     背鳍三兄弟讨伐,高级,5
     不死王瑞西塔尔讨伐,超级,2

    # 也支持「重复刷图 / 战阵之宴 / 幻想连战」并入同一份清单（按名字自动判种类）：
     崩坏域,临境域深渊之兽·极,1  ← 名字含【域】→ farm；第二字段是【行名】（域内合法行之一）
     幽玄域,幽玄域【1〜3层】,1    ← 迷宫按【域 + 行名】选；行名自含【元素】/Lv../层
     战阵之宴,-,5             ← 名字含「战阵之宴」→ raid（不做导航，难度忽略）
     幻想连战,-,2             ← 名字含「幻想」→ phantom；次数位 = 要刷几「套」
                               （幻想没有难度，难度位写 `-`；账本沿用 phantom/... 体系）

容错规则（需求 #2）：
  · 允许中英文逗号（, ，）、全角/半角数字与加号、前后空格、多余空行；
  · 也允许用英文/中文分号（; ；）分隔多条（防止某些输入框把换行吃掉）；
  · 行内 `#` 之后视为注释；
  · 无法解析的行【必须明确报错】（由调用方写到 agent stdout），绝不静默跳过；
  · 清单为空 → items 为空、errors 为空，调用方据此回退到「单目标」旧逻辑。

本模块只做「文本 → 计划」与「账本计数」两件事；真正的 pipeline 交互在
side_impl.SpecialBatchPlanRecognition / SpecialBatchFightAction 里。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

import progress as ledger

# ===========================================================================
# 单一真源：难度词表 / 降临讨伐成员表（ADR-0001：配置为真源）
#
# 「有哪些难度」「降临讨伐有哪些成员」这两样事实的**唯一一份**在 ``scene`` 包里：
# ``scene.config.DIFFICULTIES`` 与 ``scene.lord_battle`` 的成员表。本模块不再各写一份。
#
#   · 开发 / 测试态（仓库根有 ``scene/``）：直接**从真源派生** —— config 改了这里就
#     跟着变，不存在「同一件事写两遍」；
#   · 安装态（MFAAvalonia 便携包）：``tools/install.py`` 只把 ``agent/`` 随包发出
#     （见 install_agent），仓库根的 ``scene/`` **不在安装目录里**，客户端派生不到 ——
#     这时回退到下面的 ``_SNAPSHOT`` 冻结快照。快照由 ``tools/test_batch_plan_sync.py``
#     + ``tools/contract_hooks/hooks_34.py`` 离线钉死「必须与真源逐字一致」，漂移即变红。
# ===========================================================================
_REPO_ROOT = Path(__file__).resolve().parent.parent

# 安装态回退快照 —— 真源（scene.config / scene.lord_battle @2026-10-13）的冻结副本。
# ★改这里必须同时改 scene 真源★（别手改：hooks_34 会告诉你哪处漂了）。
_DIFFICULTIES_SNAPSHOT = ("初级", "中级", "高级", "高级+", "超级", "地狱级")
# 迷宫（farm）「域 → 行名列表」快照 —— 真源（scene.config.MAZE_ROWS / MAZE_DOMAINS
# @2026-10-14, #54）的冻结副本。安装态没有 scene/ 时回退到它；由 hooks_54（与 hooks_52）
# 钉死「必须与真源逐字一致」。行名里自含【元素】/Lv../层 —— 元素**不是**独立轴（#54 修订 #52）。
_MAZE_DOMAINS_SNAPSHOT = ("崩坏域", "宝物域", "幽玄域")
_MAZE_ELEMENTS_SNAPSHOT = ("火", "水", "雷", "风", "光", "暗")
_MAZE_DEEP_LV_SNAPSHOT = ((1, 50), (2, 60), (3, 70))
_MAZE_TOWER_FLOORS_SNAPSHOT = (
    (1, 3), (4, 6), (7, 9), (10, 12), (13, 15),
    (16, 18), (19, 21), (22, 24), (25, 27), (28, 30),
)
_MAZE_BENG_HEAD_ROWS_SNAPSHOT = ("临境域深渊之兽·极", "临境域深渊之兽·真", "临境域深渊之兽")
_MAZE_BENG_TAIL_ROW_SNAPSHOT = "通往深层之门"


def _snapshot_maze_rows() -> dict[str, tuple[str, ...]]:
    """安装态行列表快照（与 ``scene.config.build_maze_rows`` 同构），由上面的快照常量构造。"""
    beng: list[str] = list(_MAZE_BENG_HEAD_ROWS_SNAPSHOT)
    for tier, lv in _MAZE_DEEP_LV_SNAPSHOT:
        for e in _MAZE_ELEMENTS_SNAPSHOT:
            beng.append(f"深层域{tier}【{e}】Lv{lv}")
    beng.append(_MAZE_BENG_TAIL_ROW_SNAPSHOT)
    baowu = [f"摇曳的迷宫宝物域【{e}】" for e in _MAZE_ELEMENTS_SNAPSHOT]
    youxuan = [f"幽玄域【{a}〜{b}层】" for a, b in _MAZE_TOWER_FLOORS_SNAPSHOT]
    return {"崩坏域": tuple(beng), "宝物域": tuple(baowu), "幽玄域": tuple(youxuan)}


_MAZE_ROWS_SNAPSHOT = _snapshot_maze_rows()
_JOSS_NAMES_SNAPSHOT = frozenset({
    "无猾机兵", "红嫉机兵", "苍叹机兵", "橙悚机兵", "闪哭机兵", "暗凛机兵",
    "始龙之眼", "为你奏响的镇魂歌", "圣夜的淘气鬼", "怨炎精灵兽", "水狂精灵兽",
    "魁雷精灵兽", "威风精灵兽", "巫光精灵兽", "暗唤精灵兽", "方舟守护者讨伐",
    "赤之女王讨伐", "青之女王讨伐", "碧之女王讨伐", "皓之女王讨伐", "墨之女王讨伐",
    "伊尔昂斯拉讨伐", "伊尔梅塔雷讨伐", "碧愁机兵", "金之女王讨伐", "伊尔格拉乌讨伐",
    "伊劳德雷斯讨伐", "伊萨巴迪卡讨伐", "伊尔考普斯讨伐",
})


class _Facts(NamedTuple):
    """派生的真源事实：来源标记 + 难度词表 + 降临讨伐行名集 + 迷宫「域 → 行名列表」。"""

    source: str
    difficulties: tuple[str, ...]
    joss_names: frozenset[str]
    maze_rows: dict[str, tuple[str, ...]]


def _derive_facts_from_scene(root: Path):
    """从 ``root`` 下的 ``scene`` 包派生 (难度词表, 降临讨伐行名集, 迷宫「域→行名」)。

    ``root`` 没有 ``scene`` 包时抛 ``ModuleNotFoundError``（调用方回退快照）。
    **只读**：不动盘、不改游戏数据。
    """
    if not (root / "scene" / "__init__.py").is_file():
        raise ModuleNotFoundError(f"真源不在场：{root / 'scene'}")
    if str(root) not in sys.path:
        sys.path.append(str(root))
    from scene.config import DIFFICULTIES as _truth_difficulties  # noqa: PLC0415
    from scene.config import MAZE_ROWS as _truth_maze_rows  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE as _truth_members  # noqa: PLC0415

    joss = frozenset(
        m.行名 for m in _truth_members.members if m.子族 == "降临讨伐"
    )
    rows = {d: tuple(rs) for d, rs in _truth_maze_rows.items()}
    return (
        tuple(_truth_difficulties),
        joss,
        rows,
    )


def _load_facts() -> _Facts:
    """优先派生（单一真源）；派生不到才回退冻结快照（见上方说明）。"""
    try:
        difficulties, joss, maze_rows = _derive_facts_from_scene(_REPO_ROOT)
        return _Facts("scene", difficulties, joss, maze_rows)
    except Exception:  # noqa: BLE001 —— 安装态没有 scene/，回退快照（hooks_34/52/54 保证一致）
        return _Facts(
            "snapshot",
            _DIFFICULTIES_SNAPSHOT,
            _JOSS_NAMES_SNAPSHOT,
            _MAZE_ROWS_SNAPSHOT,
        )


_FACTS = _load_facts()
FACTS_SOURCE = _FACTS.source

# 难度取值（与 interface.json 的「打哪个难度」cases 一一对应）
DIFFICULTIES = _FACTS.difficulties

# 迷宫（farm）「域 → 行名列表」取值（#54；与 interface.json 的「打哪个迷宫域」/「打哪个
# 迷宫行」cases 一一对应）。★真源在 scene.config★：开发/测试态从这里派生，安装态用冻结快照
# （hooks_54 把「派生 / 快照 / 真源」三者钉死）。域内行序 = 声明/版式序。
MAZE_ROWS = _FACTS.maze_rows
MAZE_DOMAINS = tuple(MAZE_ROWS)
MAZE_ALL_ROWS = tuple(r for d in MAZE_DOMAINS for r in MAZE_ROWS[d])


def maze_rows_of(domain: str) -> tuple[str, ...]:
    """该【域】的合法行名列表（不存在返回空元组）。"""
    return tuple(MAZE_ROWS.get(domain, ()))


def maze_domain_of(row: str) -> str | None:
    """行名 -> 所属的域（行名全局唯一；找不到返回 None）。"""
    for d in MAZE_DOMAINS:
        if row in MAZE_ROWS[d]:
            return d
    return None

# ===========================================================================
# 副本「种类」判定（把「重复刷图 / 战阵之宴」吸收进「自动刷副本」）
#
#   · 名字含「战阵之宴」      → raid    （不做导航，只循环 挑战→结算→再次挑战）
#   · 名字含「幻想」          → phantom （主城→活动→终始之战→幻想连战，按「套」收工）
#   · 名字含「迷宫」或任一【域】 → farm  （主城横幅→迷宫页→按域选行→战斗→再次挑战）
#   · 其余                    → special （领主战 / 降临讨伐，原有逻辑）
#
# ★phantom 的「难度/次数」写法★
#   幻想连战没有难度：难度位填 `-`（也接受有效难度，仅被忽略）。
#   次数位 = 要刷几「套」（一整套 = 15 关）。例：`幻想连战,-,2` = 刷 2 套。
#   账本【沿用幻想现有的 phantom/... 体系】（phantom/set/{套}/completed 等），
#   绝不另造一套 key —— 见 phantom_sets_completed()。
#
# ★farm 的「域 / 行名」写法（#54，修订 #52）★
#   迷宫按【域】选（scene.config.MAZE_DOMAINS = 崩坏域 / 宝物域 / 幽玄域）；**第二字段是
#   【行名】**（不是元素、也不是难度）：`域,行名,次数`。行名必须属于该域（scene.config.MAZE_ROWS）；
#   行名里自含【元素】/Lv../层 —— ★元素不是独立轴★（#52 的「域,元素」写法已随 #54 作废）。
#   **本模式没有难度档**（真机迷宫页行名是「摇曳的迷宫<域>【<元素>】」/「深层域N【元素】LvNN」/
#   「幽玄域【a〜b层】」，无 初级/中级/高级）。
#   · 例：`崩坏域,临境域深渊之兽·极,1`（体力 0，真机优先目标）；
#         `崩坏域,深层域3【暗】Lv70,1`；`幽玄域,幽玄域【1〜3层】,1`；
#         `宝物域,摇曳的迷宫宝物域【风】,3`。
#   · 主目标 = FarmFight.target（行名）；域随行名一起写入（FarmFight.domain）。
#   · 账本 key = special_dungeon_batch/{域}/{行名}。
#   raid 不做导航、难度无意义，难度位建议写 `-`（也接受有效难度，仅被忽略）。
# ===========================================================================
FARM_KEYWORD = "迷宫"
FARM_KEYWORDS = (FARM_KEYWORD, *MAZE_DOMAINS)   # 「迷宫」+ 三个域都判为 farm
RAID_KEYWORD = "战阵之宴"
PHANTOM_KEYWORD = "幻想"
ANY_DIFFICULTY = "-"          # 难度占位：raid 不用难度 / farm 元素不限时填它

# phantom（幻想连战）账本沿用 phantom_impl 的现有体系：
#   phantom/set/{套号}/completed        显式「本套完整打通」标记（权威判据）
#   phantom/set/{套号}/stage/{关号}      该套内已完成的关卡；记到第 15 关也算一套完成
PHANTOM_PREFIX = "phantom"
PHANTOM_MAX_STAGES = 15        # 一整套 = 15 关（与 phantom_impl.MAX_STAGES 一致）

# ★#54★ farm 的「域 + 行名」模型见上方注释：目标是**某个域里的某一行**（行名自含
# 【元素】/Lv../层）。旧的「元素独立次轴」（#52）与更旧的「迷宫名后缀 → 难度」拆分
# （FARM_DIFF_SUFFIXES / _split_maze）都不再存在。


def detect_kind(dungeon: str) -> str:
    """按副本名判定种类：phantom / raid / farm / special。"""
    if PHANTOM_KEYWORD in dungeon:
        return "phantom"
    if RAID_KEYWORD in dungeon:
        return "raid"
    if any(k in dungeon for k in FARM_KEYWORDS):
        return "farm"
    return "special"

# 难度 → OCR 正则：★必须带 $ 锚定★，否则「高级」会误命中「高级+」。
# 由上面的难度词表（真源）派生，不再各写一份：新增一档难度只改 scene.config。
DIFF_REGEX = {d: re.escape(d) + "$" for d in DIFFICULTIES}

# 降临讨伐（另一个 tab）。这些副本在列表页需要切到「降临讨伐」tab，
# 并关掉「领主战」tab 的自动点击（领主战 tab 标签常驻，不关会一直切回领主战）。
# 名单来自真源 scene.lord_battle（子族 == 降临讨伐）；派生不到时用安装态冻结快照。
JOSS_NAMES = _FACTS.joss_names

# 账本 key 前缀：{BATCH_PREFIX}/{副本}/{难度}/{第几场}
BATCH_PREFIX = "special_dungeon_batch"


@dataclass
class BatchItem:
    dungeon: str
    difficulty: str
    times: int
    source: str = ""                 # 原始文本（报错/日志用）
    kind: str = "special"            # special / farm / raid / phantom（不破坏旧 API：有默认值）

    @property
    def target(self) -> str:
        """真正用于识别的目标名。

        ★#54★ farm 的目标是【域里的某一行】：``target`` = **行名**（= ``difficulty`` 字段；
        行名自含【元素】/Lv../层）；其余种类就是副本名本身（``dungeon``）。
        """
        return self.difficulty if self.kind == "farm" else self.dungeon

    @property
    def domain(self) -> Optional[str]:
        """farm 的【域】（``dungeon`` 字段在 farm 下承载域）；非 farm 返回 ``None``。"""
        return self.dungeon if self.kind == "farm" else None

    @property
    def label(self) -> str:
        return f"{self.dungeon},{self.difficulty},x{self.times}"


def _to_halfwidth(text: str) -> str:
    """全角 → 半角，主要是全角数字/逗号/加号/空格，方便统一比较。"""
    out = []
    for ch in text:
        o = ord(ch)
        if o == 0x3000:            # 全角空格
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:  # 全角 ASCII
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def parse_batch(text) -> tuple[list[BatchItem], list[str]]:
    """把清单文本解析成 (items, errors)。

    items 已去重（同名同难度合并，次数相加，保留首次出现顺序）。
    只要 errors 非空，调用方就应当终止批量任务并报错。
    """
    if text is None:
        return [], []
    raw = _to_halfwidth(str(text))
    if not raw.strip():
        return [], []

    # 条目分隔：换行 / 分号（中英文）。
    chunks = re.split(r"[\r\n;]+", raw)

    items: list[BatchItem] = []
    errors: list[str] = []
    seen: dict[tuple[str, str, str], BatchItem] = {}

    for idx, chunk in enumerate(chunks, start=1):
        line = chunk.strip()
        if not line:
            continue
        # 行内注释（# 之后全部丢弃）
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            errors.append(
                f"第 {idx} 段「{line}」格式错误：应为『副本名,难度,次数』"
                f"（英文/中文逗号分隔，共 3 项，实际 {len(parts)} 项）"
            )
            continue

        dungeon, difficulty, times_s = parts
        if not dungeon:
            errors.append(f"第 {idx} 段「{line}」副本名为空")
            continue

        kind = detect_kind(dungeon)
        if kind == "farm":
            # ★#54★ 第二字段是【行名】（不是元素、也不是难度）：必须是该域的行名之一
            # （scene.config.MAZE_ROWS[dungeon]）。行名里自含【元素】/Lv../层。
            rows = maze_rows_of(dungeon)
            if not rows:
                errors.append(
                    f"第 {idx} 段「{line}」域「{dungeon}」不是已知迷宫域；"
                    f"迷宫按【域 + 行名】选，域须用 {'/'.join(MAZE_DOMAINS)} 之一"
                )
                continue
            if difficulty not in rows:
                errors.append(
                    f"第 {idx} 段「{line}」行名「{difficulty}」不属于域「{dungeon}」；"
                    f"迷宫按【域 + 行名】选，行名须是 {'/'.join(rows)} 之一"
                    f"（元素是行名的一部分，不是独立字段；本模式没有难度档）"
                )
                continue
        elif kind == "raid":
            # 战阵之宴不做导航、难度无意义：接受 `-` 或任一有效难度（后者仅被忽略）。
            if difficulty != ANY_DIFFICULTY and difficulty not in DIFFICULTIES:
                errors.append(
                    f"第 {idx} 段「{line}」难度「{difficulty}」无效，"
                    f"战阵之宴请把难度位填 {ANY_DIFFICULTY}（不做导航，难度会被忽略）"
                )
                continue
        elif kind == "phantom":
            # 幻想连战没有难度：接受 `-` 或任一有效难度（后者仅被忽略）。
            # 次数位 = 套数（一整套 = 15 关），账本沿用 phantom/... 体系。
            if difficulty != ANY_DIFFICULTY and difficulty not in DIFFICULTIES:
                errors.append(
                    f"第 {idx} 段「{line}」难度「{difficulty}」无效，"
                    f"幻想连战请把难度位填 {ANY_DIFFICULTY}（幻想没有难度）"
                )
                continue
        elif difficulty not in DIFFICULTIES:
            errors.append(
                f"第 {idx} 段「{line}」难度「{difficulty}」无效，"
                f"必须是 {'/'.join(DIFFICULTIES)} 之一"
            )
            continue

        if not re.fullmatch(r"[0-9]+", times_s) or int(times_s) < 1:
            errors.append(
                f"第 {idx} 段「{line}」次数「{times_s}」无效，必须是正整数"
            )
            continue

        times = int(times_s)
        key = (kind, dungeon, difficulty)
        if key in seen:
            seen[key].times += times
            continue
        item = BatchItem(dungeon, difficulty, times, source=line, kind=kind)
        seen[key] = item
        items.append(item)

    return items, errors


def item_prefix(item: BatchItem) -> str:
    """该目标的账本前缀：BATCH_PREFIX/副本/难度。"""
    return f"{BATCH_PREFIX}/{item.dungeon}/{item.difficulty}"


def item_key(item_or_prefix, seq: int) -> str:
    """某一场的账本 key：前缀/{seq}。"""
    prefix = item_or_prefix if isinstance(item_or_prefix, str) else item_prefix(item_or_prefix)
    return f"{prefix}/{int(seq)}"


def phantom_sets_completed() -> int:
    """已完整打通的幻想连战「套」数（沿用 phantom/... 账本，不另造 key）。

    判据与 phantom_impl._scan_completed_sets 保持一致（取并集）：
      · phantom/set/{n}/completed           显式「本套完成」标记（权威）；
      · phantom/set/{n}/stage/15            旧账本里该套已记到第 15 关。
    被重置/打断的套会被 phantom_impl 按套清账，标记与关号一并清掉，故不会误计。
    """
    marker_re = re.compile(r"/set/(\d+)/completed$")
    stage_re = re.compile(r"/set/(\d+)/stage/(\d+)$")
    done: set[int] = set()
    for k in ledger.scope(f"{PHANTOM_PREFIX}/set"):
        m = marker_re.search(k)
        if m:
            done.add(int(m.group(1)))
            continue
        m = stage_re.search(k)
        if m and int(m.group(2)) >= PHANTOM_MAX_STAGES:
            done.add(int(m.group(1)))
    return len(done)


def count_done(item_or_prefix) -> int:
    """账本里已记录了多少场（用于续跑 / 避免重复打）。

    phantom 的「场」= 「套」：直接读幻想现有 phantom/... 体系的已完成套数。
    """
    if isinstance(item_or_prefix, BatchItem) and item_or_prefix.kind == "phantom":
        return phantom_sets_completed()
    prefix = item_or_prefix if isinstance(item_or_prefix, str) else item_prefix(item_or_prefix)
    return len(ledger.scope(prefix))


def remaining(item: BatchItem) -> int:
    return max(0, item.times - count_done(item))


def is_joss(dungeon: str) -> bool:
    return dungeon in JOSS_NAMES


def is_farm(dungeon: str) -> bool:
    return detect_kind(dungeon) == "farm"


def is_raid(dungeon: str) -> bool:
    return detect_kind(dungeon) == "raid"


def is_phantom(dungeon: str) -> bool:
    return detect_kind(dungeon) == "phantom"


def next_item(items: list[BatchItem]) -> Optional[BatchItem]:
    """按清单顺序返回第一个「还没打够次数」的目标；都打够返回 None。"""
    for it in items:
        if remaining(it) > 0:
            return it
    return None
