# -*- coding: utf-8 -*-
"""离线单测：场景配置面（family 模板 + 成员 delta + 页面判据全局唯一）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_config.py

覆盖 ticket #3 的四条验收标准：

  1. 46 个成员可由配置声明（领主战 17 / 降临讨伐 29，据 #32 真机行扫），且名单照抄
     assets/interface.json 的选项「打哪个副本」——不臆造；
  2. 同一成员重复声明时当场报错，不静默覆盖；
  3. 页面判据只有一份；任何覆盖都出现在覆盖报告里（ADR-0003）；
  4. 增删一个成员只改数据、不改 agent 代码（数据驱动，本测试直接演示）。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scene.config import (  # noqa: E402
    ConfigError,
    FamilyConfig,
    FamilyTemplate,
    assert_page_rules_globally_unique,
    derive_members,
    member,
    override_report,
    validate_config,
)
from scene.lord_battle import FAMILY, JOSS, LORDS, LORD_BATTLE  # noqa: E402
from scene.page_rules import (  # noqa: E402
    PAGE_RULES,
    duplicate_rule_names,
    page_rule,
    page_rules,
)

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# 照抄 assets/interface.json 选项「打哪个副本」的两节（领主战 17 / 降临讨伐 29，据 #32 真机行扫）。
EXPECTED_LORDS = [
    "猩红巨熊讨伐", "背鳍三兄弟讨伐", "八岐大蛇讨伐", "管理者讨伐", "Sec-5200Li讨伐",
    "白虎讨伐", "风将獠牙骑士讨伐", "艾基尔·嫉妒讨伐", "寄居蟹船长讨伐", "潮汐巨妖讨伐",
    "废墟魔像讨伐", "废墟守卫·火讨伐", "雷霆树妖讨伐", "维·索拉斯讨伐", "不死王瑞西塔尔讨伐",
    # #32 真机行扫补回的两行（第 5 行 妖狐讨伐 / 第 10 行 诅咒弧魔艾基尔讨伐）。
    "妖狐讨伐", "诅咒弧魔艾基尔讨伐",
]
EXPECTED_JOSS = [
    "无猾机兵", "红嫉机兵", "苍叹机兵", "橙悚机兵", "闪哭机兵", "暗凛机兵",
    "始龙之眼", "为你奏响的镇魂歌", "圣夜的淘气鬼", "怨炎精灵兽", "水狂精灵兽",
    "魁雷精灵兽", "威风精灵兽", "巫光精灵兽", "暗唤精灵兽", "方舟守护者讨伐",
    "赤之女王讨伐", "青之女王讨伐", "碧之女王讨伐", "皓之女王讨伐", "墨之女王讨伐",
    "伊尔昂斯拉讨伐", "伊尔梅塔雷讨伐",
    # #32 真机行扫新增的六名（旧配置没有；石芯心六 被移除，真机无此行）。
    "碧愁机兵", "金之女王讨伐", "伊尔格拉乌讨伐", "伊劳德雷斯讨伐", "伊萨巴迪卡讨伐",
    "伊尔考普斯讨伐",
]


def test_members_declared() -> None:
    print("\n== 1. 46 个成员可由配置声明（领主战 17 / 降临讨伐 29，据 #32 真机行扫） ==")
    records = derive_members(LORD_BATTLE)
    check("派生成员数 = 46", len(records) == 46, f"got={len(records)}")
    check("领主战 = 17", len(LORDS) == 17, f"got={len(LORDS)}")
    check("降临讨伐 = 29", len(JOSS) == 29, f"got={len(JOSS)}")

    lords = [r["行名"] for r in records if r["子族"] == "领主战"]
    joss = [r["行名"] for r in records if r["子族"] == "降临讨伐"]
    check("领主战名单与 interface.json 一致（顺序）", lords == EXPECTED_LORDS, f"got={lords}")
    check("降临讨伐名单与 interface.json 一致（顺序）", joss == EXPECTED_JOSS, f"got={joss}")

    ids = [r["id"] for r in records]
    check("成员 id 全局唯一", len(ids) == len(set(ids)), f"dup={[i for i in ids if ids.count(i) > 1]}")

    # 不臆造：每个行名都必须真的出现在 interface.json 文本里。
    interface_text = (REPO_ROOT / "assets" / "interface.json").read_text(
        encoding="utf-8", errors="replace"
    )
    missing = [r["行名"] for r in records if r["行名"] not in interface_text]
    check("每个成员行名都能在 interface.json 里找到（非臆造）", missing == [], f"missing={missing}")

    errs = validate_config(LORD_BATTLE)
    check("真实配置自身校验通过", errs == [], f"errors={errs}")


def test_tab_from_subfamily() -> None:
    print("\n== 2. 页签由子族决定，调用方不能单独设置 ==")
    for r in derive_members(LORD_BATTLE):
        if r["子族"] == "领主战":
            assert r["页签"] == "领主战"
        else:
            assert r["页签"] == "降临讨伐"
    check("每个成员的页签 = 其子族决定的页签",
          all((r["页签"] == "领主战") == (r["子族"] == "领主战")
              and (r["页签"] == "降临讨伐") == (r["子族"] == "降临讨伐")
              for r in derive_members(LORD_BATTLE)))

    # member() / MemberDelta 不接受 页签= 形参 —— 页签不可与子族脱钩。
    try:
        member("领主战", "X", "X", ["初级"], 页签="降临讨伐")  # type: ignore[call-arg]
        raised = False
    except TypeError:
        raised = True
    check("member() 不接受独立的 页签 形参（TypeError）", raised)

    try:
        # 直接构造也不行
        from scene.config import MemberDelta
        MemberDelta(id="X", 子族="领主战", 行名="X", 支持难度集=("初级",), 页签="降临讨伐")  # type: ignore[call-arg]
        raised2 = False
    except TypeError:
        raised2 = True
    check("MemberDelta 不接受独立的 页签 形参（TypeError）", raised2)


def test_duplicate_member_rejected() -> None:
    print("\n== 3. 重复成员声明当场报错（不静默覆盖） ==")
    fam = FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    # 同名、不同难度 —— 若静默覆盖，会悄悄丢掉一个支持难度集。
    dup = [member("领主战", "猩红巨熊讨伐", "猩红巨熊讨伐", ["初级"]),
           member("领主战", "猩红巨熊讨伐", "猩红巨熊讨伐", ["超级"])]
    errs = validate_config(FamilyConfig(family=fam, members=dup))
    check("重复 id 报错", len(errs) == 1, f"errors={errs}")
    check("错误点名重复的成员", errs and "猩红巨熊讨伐" in errs[0], f"errors={errs}")
    check("错误明说『重复』/『覆盖』语义",
          errs and ("重复" in errs[0]) and ("覆盖" in errs[0]), f"errors={errs}")

    # 三连重复也报（按出现次数）
    tri = dup + [member("领主战", "猩红巨熊讨伐", "猩红巨熊讨伐", ["中级"])]
    errs3 = validate_config(FamilyConfig(family=fam, members=tri))
    check("三连重复仍只报一条（按成员）", len(errs3) == 1 and "3 次" in errs3[0], f"errors={errs3}")


def test_difficulty_set_rejected() -> None:
    print("\n== 4. 支持难度集为空必须报错 ==")
    fam = FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    empty = [member("领主战", "空集机兵", "空集机兵", [])]
    errs = validate_config(FamilyConfig(family=fam, members=empty))
    check("空难度集报错", len(errs) == 1, f"errors={errs}")
    check("错误点名成员", errs and "空集机兵" in errs[0], f"errors={errs}")
    check("错误说明难度集为空", errs and "难度集为空" in errs[0], f"errors={errs}")

    # 未知难度也要报错（同样点名）
    bad = [member("领主战", "怪难度机兵", "怪难度机兵", ["地狱"])]
    errs2 = validate_config(FamilyConfig(family=fam, members=bad))
    check("未知难度报错并点名", len(errs2) == 1 and "怪难度机兵" in errs2[0], f"errors={errs2}")

    # 真实配置里没有空难度集
    check("真实配置无空难度集", all(m.支持难度集 for m in LORD_BATTLE.members))


def test_other_validation_errors() -> None:
    print("\n== 5. 其它校验：空行名 / 未知子族 / 覆盖引用不存在的判据 ==")
    fam = FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    errs = validate_config(FamilyConfig(family=fam, members=[
        member("领主战", "空白行", "  ", ["初级"]),
    ]))
    check("空行名报错并点名", any("空白行" in e and "行名" in e for e in errs), f"errors={errs}")

    errs2 = validate_config(FamilyConfig(family=fam, members=[
        member("不存在族", "越界机兵", "越界机兵", ["初级"]),
    ]))
    check("未知子族报错并点名", any("越界机兵" in e and "子族" in e for e in errs2), f"errors={errs2}")

    from scene.config import Override
    cfg = FamilyConfig(family=fam, members=[], overrides=[
        Override(rule="根本不存在的页面", recognition={}, owner="X"),
    ])
    errs3 = validate_config(cfg)
    check("覆盖引用不存在的判据报错", any("根本不存在的页面" in e for e in errs3), f"errors={errs3}")


def test_page_rules_globally_unique() -> None:
    print("\n== 6. 页面判据全局唯一；family 页序只引用、不复制 ==")
    check("全局注册表无重名", duplicate_rule_names() == [], f"dup={duplicate_rule_names()}")
    check("assert_page_rules_globally_unique 不抛", _no_raise(assert_page_rules_globally_unique))
    names = [r.name for r in page_rules()]
    check("页面名唯一", len(names) == len(set(names)), f"names={names}")

    # family 页序里每个页面名都必须在全局注册表里解析得到（引用而非本地副本）
    unresolved = [p for p in FAMILY.页序 if _rule_missing(p)]
    check("family 页序里的页面判据全部可解析", unresolved == [], f"unresolved={unresolved}")

    # 判据对象是同一份（引用全局，不是各抄一份）：page_rule 返回的就是注册表里的对象
    check("page_rule 返回注册表中的同一条判据",
          any(page_rule("编队页") is r for r in PAGE_RULES))

    # 有人往注册表里抄第二份同名列 → duplicate_rule_names 必须抓得到
    dup = PAGE_RULES + [PAGE_RULES[0]]
    counts: dict[str, int] = {}
    for r in dup:
        counts[r.name] = counts.get(r.name, 0) + 1
    dupnames = sorted(n for n, c in counts.items() if c > 1)
    check("重复注册会被识别（构造证明）", dupnames == [PAGE_RULES[0].name], f"got={dupnames}")


def test_override_report() -> None:
    print("\n== 7. 任何覆盖都出现在覆盖报告里（ADR-0003） ==")
    report = override_report(LORD_BATTLE)
    declared = list(LORD_BATTLE.overrides)
    check("覆盖条数 = 声明条数（无隐形、无遗漏）", len(report) == len(declared),
          f"report={len(report)} declared={len(declared)}")
    check("报告里逐条包含声明", all(any(o is d for o in report) for d in declared))

    joss_ov = [o for o in report if o.owner == "降临讨伐" and o.rule == "领主战页签"]
    check("真实覆盖：降临讨伐 覆盖 领主战页签", len(joss_ov) == 1, f"got={joss_ov}")
    check("覆盖带 reason（回答『为什么覆盖』）", joss_ov and joss_ov[0].reason.strip() != "")

    # 无覆盖的配置 → 空报告（覆盖是例外，不是默认）
    fam = FamilyTemplate(id="probe", 显示名="probe", 子族=("领主战",))
    check("无覆盖的配置 → 空报告", override_report(FamilyConfig(family=fam)) == [])

    # 多场景各自覆盖同一条判据 → 两条都出现（不合并、不丢）
    from scene.config import Override
    cfg = FamilyConfig(family=fam, members=[], overrides=[
        Override(rule="编队页", recognition={"type": "OCR"}, owner="A"),
        Override(rule="编队页", recognition={"type": "OCR"}, owner="B"),
    ])
    rep2 = override_report(cfg)
    check("多个 owner 覆盖同一判据都保留", len(rep2) == 2 and {o.owner for o in rep2} == {"A", "B"})


def test_data_driven_add_remove() -> None:
    print("\n== 8. 增删一个成员只改数据、不改 agent 代码（数据驱动） ==")
    base = LORD_BATTLE.members
    extra = member("领主战", "新成员·测试", "新成员·测试", ["初级"])
    added = FamilyConfig(family=FAMILY, members=[*base, extra], overrides=list(LORD_BATTLE.overrides))
    check("加一个成员 → 派生 47 个", len(derive_members(added)) == 47)
    check("加成员后仍校验通过", validate_config(added) == [], f"errors={validate_config(added)}")
    check("新成员出现在派生记录末尾",
          derive_members(added)[-1]["id"] == "新成员·测试")

    removed = FamilyConfig(family=FAMILY, members=list(base[:-1]), overrides=list(LORD_BATTLE.overrides))
    check("删一个成员 → 派生 45 个", len(derive_members(removed)) == 45)
    check("删成员后仍校验通过", validate_config(removed) == [])

    # 空配置也能被处理（模板驱动；不依赖任何具体成员名）
    empty = FamilyConfig(family=FAMILY)
    check("空配置：0 成员、0 错误、空报告",
          derive_members(empty) == [] and validate_config(empty) == [] and override_report(empty) == [])


def _no_raise(fn) -> bool:
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001
        return False


def _rule_missing(name: str) -> bool:
    try:
        page_rule(name)
        return False
    except KeyError:
        return True


def main() -> None:
    print("=" * 70)
    print("离线单测：场景配置面（scene.lord_battle / scene.config / scene.page_rules）")
    print("=" * 70)
    test_members_declared()
    test_tab_from_subfamily()
    test_duplicate_member_rejected()
    test_difficulty_set_rejected()
    test_other_validation_errors()
    test_page_rules_globally_unique()
    test_override_report()
    test_data_driven_add_remove()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
