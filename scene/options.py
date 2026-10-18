# -*- coding: utf-8 -*-
"""GUI 目标选项由配置生成（ticket #6 / ADR-0001）。

领主战类的 GUI **目标选项**（当前手写在 ``assets/interface.json`` 的 option
「打哪个副本」）不再手写：**N 个成员 -> 恰好 N 个选项**。本模块只做两件事：

1. **派生（derive）** —— 从 :class:`scene.config.FamilyConfig` 生成 interface option 块：

   * :func:`derive_target_options` -> N 个选项 case（``list[dict]``，保持声明顺序）；
   * :func:`derive_option_block`   -> 完整的 option 块（``select`` + cases）。

2. **注入（inject）** —— 把派生出的块写进 interface JSON 文本，且**幂等**
   （同一份文本注入两次，结果字节相同，ADR-0001）：

   * :func:`inject_option`     -> 注入后的文本；
   * :func:`verify_injection`  -> 文本是否恰好是「本配置注入后」的样子（手改生成区即 False）。

明确**不做**：真正把 ``assets/interface.json`` 换掉 —— 那是迁移票 #9/#10/#11 的事。
本模块只提供机制，其守卫在 ``tools/contract_hooks/hooks_6.py`` 与
``tools/test_scene_options.py``。全离线、不碰设备。

术语沿用 ``GLOSSARY.md``：页面 / 场景 / 领主战类 / 开关 / 路由 / 任务 / 入口 /
归位 / 事件。这里生成的是「任务」的一个「选项」。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .config import (
    ConfigError,
    DIFFICULTIES,
    MAZE_DOMAINS,
    MAZE_ROWS,
    DEFAULT_MAZE_DOMAIN,
    DEFAULT_MAZE_ROW,
    maze_domain_template,
)

if TYPE_CHECKING:  # pragma: no cover - 仅供类型标注
    from .config import FamilyConfig, MemberDelta

# 目标选项块在 interface.json 里的名字（即当前手写的那一项）。
OPTION_NAME = "打哪个副本"

# 难度选项块在 interface.json 里的名字（#39：由 scene.config.DIFFICULTIES 派生）。
# ★#39★：难度**词表**是全局输入（scene.config.DIFFICULTIES，真源）；GUI 的「打哪个难度」
# 必须与它逐项一致（多一档 / 少一档 / 换正则都算漂移，见 scene.drift.difficulty_option_drift）。
DIFFICULTY_OPTION_NAME = "打哪个难度"

# 「打哪个难度」的缺省档（与 interface.json 现有 default_case 一致）。
DEFAULT_DIFFICULTY = "高级"

# 目标行节点：导航时在列表页按【行名】OCR 选中目标那一行。
# 节点名与 ROI 照抄 `assets/interface.json` 现存的手写 override（SpecialEnterBoss），
# 不是本地发明；#7（配置↔JSON 漂移）负责把它与 pipeline JSON 对齐。
TARGET_ROW_NODE = "SpecialEnterBoss"
TARGET_ROW_ROI = (150, 440, 320, 800)

# 页面判据名 -> pipeline 节点名：把配置里的【覆盖】（``Override.rule``）落到具体的
# pipeline 节点上。目前只有一条 —— 全局「领主战页签」判据对应 pipeline 节点
# ``SpecialTabLord``（后者是 interface.json / special_dungeon.json 里已存在的节点名）。
# 未列出的判据会让 derive 明确报错（ConfigError），逼调用方补映射，
# 而不是静默丢掉一条覆盖（ADR-0003：覆盖不得隐形）。
PAGE_RULE_TO_NODE = {
    "领主战页签": "SpecialTabLord",
}

# 生成区标记（JSONC 行注释）：注入是「替换标记之间」而不是「追加」，
# 因此重复注入不改变字节（ADR-0001：注入幂等）。
_BEGIN = "// >>> scene.options (#6) begin: 本块由配置生成，请勿手改 <<<"
_END = "// <<< scene.options (#6) end <<<"

# 顶层 ``"option": {`` 映射（注意与任务的 ``"option": [`` 区分：大括号 vs 方括号）。
_OPTION_MAP_RE = re.compile(r'"option"\s*:\s*\{')


def _overrides_for(cfg: "FamilyConfig", m: "MemberDelta") -> list:
    """适用于某个成员的覆盖：owner 是其子族名或成员 id（#3 的归属约定）。"""
    return [o for o in cfg.overrides if o.owner == m.子族 or o.owner == m.id]


def derive_target_options(cfg: "FamilyConfig") -> list[dict]:
    """从配置派生 GUI 目标选项：**N 个成员 -> 恰好 N 个选项**（保持声明顺序）。

    每个选项 = ``{name: 行名, pipeline_override: ...}``：以【行名】OCR 选中目标行；
    再叠加适用于该成员的【覆盖】（例如「降临讨伐」关掉全局「领主战页签」）。
    """
    options: list[dict] = []
    for m in cfg.members:
        pipeline_override: dict = {
            TARGET_ROW_NODE: {
                "recognition": {
                    "type": "OCR",
                    "param": {"expected": [m.行名], "roi": list(TARGET_ROW_ROI)},
                }
            }
        }
        for o in _overrides_for(cfg, m):
            node = PAGE_RULE_TO_NODE.get(o.rule)
            if node is None:
                raise ConfigError(
                    f"成员 {m.id!r} 的覆盖引用了未映射到 pipeline 节点的判据 "
                    f"{o.rule!r}：请在 options.PAGE_RULE_TO_NODE 里补上它"
                )
            pipeline_override[node] = {"recognition": o.recognition}
        options.append({"name": m.行名, "pipeline_override": pipeline_override})
    return options


def derive_option_block(cfg: "FamilyConfig", name: str = OPTION_NAME) -> dict:
    """从配置派生一个完整的 interface option 块（``select`` + cases）。"""
    cases = derive_target_options(cfg)
    return {
        "type": "select",
        "default_case": cases[0]["name"] if cases else "",
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# 难度选项：从 scene.config.DIFFICULTIES 派生（#39）
#
# ★为什么难度选项也要派生★：「有哪些难度」是**全局输入**、真源在 ``scene.config.DIFFICULTIES``；
# GUI 的「打哪个难度」是它的投影，必须与真源逐项一致（否则用户选不到某档 / 选到不存在的档）。
# 过去这份 cases 是手写在 interface.json 里的，且**漏了 ``地狱级``**（真机确有该档）——#39
# 把它改为从真源派生，并由 ``scene.drift.difficulty_option_drift`` 把守。
# ---------------------------------------------------------------------------
def derive_difficulty_cases() -> list[dict]:
    """从难度词表（真源）派生「打哪个难度」的 cases（保持词表顺序）。

    每个难度 -> 一个 case：override ``SpecialFightTargetRow`` 的识别为 custom
    ``special_target_fight``、``difficulty`` = 该难度的**行名正则**（``re.escape(d) + "$"``）。
    ★必须带 ``$`` 锚定★：不加 $ 时「高级」会误命中「高级+」。与 ``agent.batch_plan.DIFF_REGEX``
    同源（后者同样由 ``scene.config.DIFFICULTIES`` 派生，见 hooks_34）。
    """
    return [
        {
            "name": d,
            "pipeline_override": {
                "SpecialFightTargetRow": {
                    "recognition": {
                        "type": "Custom",
                        "param": {
                            "custom_recognition": "special_target_fight",
                            "custom_recognition_param": {"difficulty": re.escape(d) + "$"},
                        },
                    }
                }
            },
        }
        for d in DIFFICULTIES
    ]


def derive_difficulty_block() -> dict:
    """派生完整的「打哪个难度」option 块（``select`` + cases + default_case）。"""
    cases = derive_difficulty_cases()
    names = [c["name"] for c in cases]
    default = DEFAULT_DIFFICULTY if DEFAULT_DIFFICULTY in names else (names[0] if names else "")
    return {"type": "select", "default_case": default, "cases": cases}


# ---------------------------------------------------------------------------
# 迷宫（摇曳的迷宫）选项：从 scene.config 的【域 + 行名】【真源】派生（#54，修订 #52）
#
# ★#54 模型★：迷宫**按「域」选**（崩坏域 / 宝物域 / 幽玄域），每个域是一张**异质行列表**；
#   目标 = 【域 + 行名】（结构上与领主战的「页签 + 行名」同构）。**元素是行名的一部分，
#   不是独立轴**（#52 的元素独立选项已被设备证伪并移除）。**本模式没有难度档**；
#   「Lv..」/「层」只在行名里。
#
# 落点（与 pipeline 节点对齐）：
#   · 「行」→ ``FarmFight``（custom ``special_target_fight``，``target`` = 行名，
#     ``domain`` = 该行所属域，``pair=below``）—— 主目标，直接返回该行【战斗】按钮的框；
#   · 「域」→ ``FarmDomainPick``（同 custom，``domain`` = 域名）—— 它只是个**数据节点**
#     （不在任何 next 里，永不执行）；与基础 pipeline 里 FarmFight 的 ``domain`` 互补，
#     说明「当前选的是哪个域」（GUI 域选项的落点）。
# ---------------------------------------------------------------------------
MAZE_DOMAIN_OPTION_NAME = "打哪个迷宫域"
MAZE_ROW_OPTION_NAME = "打哪个迷宫行"

# 迷宫落点节点（pipeline 里已存在 / 本票新增；见 farm.json）。
MAZE_FIGHT_NODE = "FarmFight"
MAZE_DOMAIN_NODE = "FarmDomainPick"

# ★#57★ 域判定改用图片匹配（运维：迷宫域不要用 OCR）★
# ---------------------------------------------------------------------------
# 「进的是哪个域」由**模板匹配**决定，OCR 不再作域判据（横幅副标题 OCR 在真机被读坏：
# 崩坏域→崩环域 / 幽玄域→出立域）。落点：
#   · FarmMazeDomain（横幅域名美术字模板）—— 进域门控：只有横幅正显示【声明的那个域】
#     时才命中 FarmMazeEntry（标题 ∧ 域的与门，见 farm.json）；
#   · FarmDomainVerify（迷宫页页眉域名美术字模板）—— 进域后【复核】：迷宫页滚动/FarmFight
#     只有在页眉确认「确实进了该域」时才推进（复核不过 → 拒绝推进，绝不误操作）。
# 模板路径来自 scene.config.MAZE_DOMAIN_TEMPLATES（真源，ADR-0001）；ROI / 阈值也在这里
# 与 agent.side_impl 的同名常量一致（守卫 hooks_57 把两处钉死）。
MAZE_DOMAIN_TEMPLATE_NODE = "FarmMazeDomain"
MAZE_DOMAIN_VERIFY_NODE = "FarmDomainVerify"
#: 主城左侧轮播横幅位（720）：与 farm.json::FarmMazeDomain 的 roi 一致（门控）。
MAZE_ENTRY_ROI = (0, 760, 340, 315)
#: 迷宫页页眉位（720）：与 farm.json::FarmDomainVerify 的 roi 一致（复核）。
MAZE_HEAD_ROI = (0, 90, 720, 240)
#: 模板匹配阈值（cv TM_CCOEFF_NORMED）：真机同模板得分 0.998+、异域/负样本 ≤ 0.41，余量充足。
MAZE_TEMPLATE_THRESHOLD = 0.8


def _maze_template_override(domain: str) -> dict:
    """域 -> 两个模板落点节点的 override（``FarmMazeDomain`` 门控 + ``FarmDomainVerify`` 复核）。

    与 agent.side_impl._maze_domain_template_overrides 同形（后者是运行时批量路径）；
    守卫 hooks_57 把两处逐字钉死。
    """
    def _node(role: str, roi) -> dict:
        return {
            "recognition": {
                "type": "TemplateMatch",
                "param": {
                    "template": [maze_domain_template(domain, role)],
                    "roi": list(roi),
                    "threshold": MAZE_TEMPLATE_THRESHOLD,
                },
            }
        }

    return {
        MAZE_DOMAIN_TEMPLATE_NODE: _node("banner", MAZE_ENTRY_ROI),
        MAZE_DOMAIN_VERIFY_NODE: _node("head", MAZE_HEAD_ROI),
    }


def derive_maze_domain_cases() -> list[dict]:
    """从域词表派生「打哪个迷宫域」cases：每个域 -> 一个 case。

    覆盖：``FarmDomainPick`` 的域偏好（#54）；★#57★ 再加上该域的两个**模板落点**
    （``FarmMazeDomain`` 横幅门控 + ``FarmDomainVerify`` 页眉复核）—— 于是「选哪个域」
    在 GUI 上直接决定「按哪个域的模板进域/复核」，不再靠 OCR 判域。
    """
    return [
        {
            "name": d,
            "pipeline_override": {
                MAZE_DOMAIN_NODE: {
                    "recognition": {
                        "type": "Custom",
                        "param": {
                            "custom_recognition": "special_target_fight",
                            "custom_recognition_param": {"domain": d, "pair": "below"},
                        },
                    }
                },
                **_maze_template_override(d),
            },
        }
        for d in MAZE_DOMAINS
    ]


def derive_maze_domain_block() -> dict:
    """派生完整的「打哪个迷宫域」option 块（``select`` + cases + default_case）。"""
    cases = derive_maze_domain_cases()
    names = [c["name"] for c in cases]
    default = DEFAULT_MAZE_DOMAIN if DEFAULT_MAZE_DOMAIN in names else (names[0] if names else "")
    return {"type": "select", "default_case": default, "cases": cases}


def derive_maze_row_cases() -> list[dict]:
    """从【域 → 行名】真源派生「打哪个迷宫行」cases：每个（域, 行名）-> 一个 case。

    行列表**按域分组**（崩坏域的行在前、其后宝物域、再幽玄域；域内保持真源顺序）——
    但仍是一条 flat select（MAA 的 option 不支持嵌套 select，见 interface schema）。
    每个 case 把【行名 + 所属域】写进 ``FarmFight``（主目标）。
    """
    return [
        {
            "name": row,
            "pipeline_override": {
                MAZE_FIGHT_NODE: {
                    "recognition": {
                        "type": "Custom",
                        "param": {
                            "custom_recognition": "special_target_fight",
                            "custom_recognition_param": {
                                "target": row,
                                "domain": d,
                                "pair": "below",
                            },
                        },
                    }
                },
                # ★#57★ 行名已暗含域 —— 同时写该域的两个模板落点（横幅门控 + 页眉复核）。
                **_maze_template_override(d),
            },
        }
        for d in MAZE_DOMAINS
        for row in MAZE_ROWS[d]
    ]


def derive_maze_row_block() -> dict:
    """派生完整的「打哪个迷宫行」option 块（``select`` + cases + default_case）。"""
    cases = derive_maze_row_cases()
    names = [c["name"] for c in cases]
    default = DEFAULT_MAZE_ROW if DEFAULT_MAZE_ROW in names else (names[0] if names else "")
    return {"type": "select", "default_case": default, "cases": cases}


def _next_significant(text: str, i: int) -> str:
    """跳过空白与 JSONC 注释，返回下一个有意义的字符（EOF -> ``"\\0"``）。"""
    n = len(text)
    while i < n:
        if text[i] in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            if j == -1:
                return "\0"
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            if j == -1:
                return "\0"
            i = j + 2
        else:
            return text[i]
    return "\0"


def _indent_block(obj: dict, indent: str) -> str:
    """确定性 JSON：固定 indent=4，再把每一行整体右移 ``indent``。"""
    raw = json.dumps(obj, ensure_ascii=False, indent=4)
    return raw.replace("\n", "\n" + indent)


def _render_region(cfg: "FamilyConfig", name: str, indent: str, with_comma: bool) -> str:
    """生成区文本（含两行标记）；``with_comma`` 由「本块之后是否还有条目」决定。"""
    body = _indent_block(derive_option_block(cfg, name=name), indent)
    entry = f'{indent}"{name}": {body}' + ("," if with_comma else "")
    return f"{indent}{_BEGIN}\n{entry}\n{indent}{_END}"


def inject_option(
    text: str,
    cfg: "FamilyConfig",
    name: str = OPTION_NAME,
    indent: str = "        ",
) -> str:
    """把派生出的 option 块注入 interface JSON 文本；**幂等**（重复注入字节不变）。

    * 生成区标记已存在 -> 只替换标记之间的内容；
    * 否则插到顶层 ``"option": {`` 映射的开口之后。

    逗号放在生成区**内部**、由「本块之后是否还有条目」决定 —— 因此重跑得到同一字节
    （ADR-0001：注入幂等，``git status`` 不假脏）。文本里的其它字节一律不碰。
    """
    begin_at = text.find(_BEGIN)
    end_at = text.find(_END)
    has_region = begin_at != -1 and end_at != -1 and end_at > begin_at

    if has_region:
        start = text.rfind("\n", 0, begin_at) + 1
        end = end_at + len(_END)
    else:
        m = _OPTION_MAP_RE.search(text)
        if not m:
            raise ValueError('interface 文本里找不到顶层 "option": { 映射，无法注入')
        start = end = m.end()

    with_comma = _next_significant(text, end) != "}"
    region = _render_region(cfg, name=name, indent=indent, with_comma=with_comma)

    if has_region:
        return text[:start] + region + text[end:]
    # 首次插入：紧跟在映射的 { 之后
    return text[:start] + "\n" + region + text[start:]


def verify_injection(
    text: str,
    cfg: "FamilyConfig",
    name: str = OPTION_NAME,
    indent: str = "        ",
) -> bool:
    """文本是否【恰好】是本配置幂等注入后的样子。

    手改生成区（改一个 case 名 / 加一个 case）都会让重生成结果与文本不一致 -> ``False``，
    对应 ticket 的「手改选项使之与配置不一致时，套件变红」。
    """
    return text == inject_option(text, cfg, name=name, indent=indent)
