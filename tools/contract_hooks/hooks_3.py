# -*- coding: utf-8 -*-
"""#3：场景配置面的契约挂点（family 模板 + 成员 delta + 页面判据全局唯一）。

对应 ADR-0001（配置为真源）/ ADR-0003（页面判据全局唯一）。已点亮。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def scene_on_path():
    """把仓库根放到 sys.path【末尾】。

    放末尾是有意的：--prove-red 会在子进程里用 PYTHONPATH 指向一份坏掉的
    ``scene`` 副本（其位置在 sys.path 里更靠前），这里的真实仓库根不会把它盖掉。
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def probe_cfg_member_unique():
    """#3：同一成员重复声明当场报错，不静默覆盖。"""
    scene_on_path()
    import scene.config as sc  # noqa: PLC0415

    fam = sc.FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    dup = [
        sc.member("领主战", "X", "X", ["初级"]),
        sc.member("领主战", "X", "X", ["超级"]),
    ]
    errs = sc.validate_config(sc.FamilyConfig(family=fam, members=dup))
    # 错误必须点名成员 X，且明确是「重复 / 覆盖」语义。
    return any("X" in e and "重复" in e and "覆盖" in e for e in errs)


def probe_cfg_difficulty_set():
    """#3：成员支持难度集为空必须报错；真实配置里确无空集。"""
    scene_on_path()
    import scene.config as sc  # noqa: PLC0415
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

    fam = sc.FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    empty = [sc.member("领主战", "空集机兵", "空集机兵", [])]
    errs = sc.validate_config(sc.FamilyConfig(family=fam, members=empty))
    real_ok = all(m.支持难度集 for m in LORD_BATTLE.members)
    return real_ok and any("空集机兵" in e and "难度集为空" in e for e in errs)


def probe_cfg_page_rules_report():
    """#3：页面判据全局唯一；任何覆盖都出现在覆盖报告里（ADR-0003）。"""
    scene_on_path()
    from scene.config import override_report  # noqa: PLC0415
    from scene.lord_battle import FAMILY, LORD_BATTLE  # noqa: PLC0415
    from scene.page_rules import duplicate_rule_names, page_rules  # noqa: PLC0415

    # 判据全局唯一。
    if duplicate_rule_names():
        return False
    # family 页序只【引用】全局判据，每个名字都必须可解析。
    names = {r.name for r in page_rules()}
    if any(p not in names for p in FAMILY.页序):
        return False
    # 覆盖报告：声明几条就报几条，逐条都在，且真实那条被正确归属。
    report = override_report(LORD_BATTLE)
    declared = list(LORD_BATTLE.overrides)
    if len(report) != len(declared):
        return False
    if not all(any(o is d for o in report) for d in declared):
        return False
    return any(o.owner == "降临讨伐" and o.rule == "领主战页签" for o in report)


HOOKS = [
    ("cfg-member-unique", "#3", "同一成员重复声明当场报错，不静默覆盖", probe_cfg_member_unique),
    ("cfg-difficulty-set", "#3", "成员支持难度集为空必须报错", probe_cfg_difficulty_set),
    ("cfg-page-rules-report", "#3", "页面判据全局唯一；任何覆盖都出现在覆盖报告里", probe_cfg_page_rules_report),
]
