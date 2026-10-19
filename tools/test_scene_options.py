# -*- coding: utf-8 -*-
"""离线单测：GUI 目标选项由配置生成（ticket #6）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_options.py

覆盖 ticket #6 的三条验收标准，外加注入机制的幂等/漂移：

  1. 选项数量与配置里的成员数一致（N 个成员 -> 恰 N 个选项）；
  2. 增删一个成员后重新生成，选项列表随之变化（纯数据驱动）；
  3. 手改选项使之与配置不一致时，套件变红（注入幂等 + 漂移检测）；
  4. 注入幂等：同一份 interface 文本注入两次，结果字节相同（ADR-0001）。

本文件只**读** ``assets/interface.json``（确认派生出的名字与今天手写的 46 个一致 ——
#32 真机行扫后为领主战 17 + 降临讨伐 29），
绝不写它 —— 真正的替换在迁移票 #9/#10/#11。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import options  # noqa: E402
from scene.config import FamilyConfig, member  # noqa: E402
from scene.lord_battle import FAMILY, JOSS, LORDS, LORD_BATTLE  # noqa: E402

import hooks_6  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"
FAILS: list[str] = []

# 注入用的最小 interface 骨架（顶层 "option": { 映射 + 一个既有条目 + 一条注释）。
SKELETON = (
    "{\n"
    '    "task": [],\n'
    '    "option": {\n'
    "        // 既有的手写条目\n"
    '        "抽哪个池": { "type": "select", "cases": [] }\n'
    "    }\n"
    "}\n"
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def real_interface_names(text: str) -> list[str]:
    """只读解析：抽出 interface.json 选项「打哪个副本」里今天手写的 case 名字。"""
    start = text.index('"打哪个副本": {')
    end = text.index('"打哪个难度": {')
    return re.findall(r'"name"\s*:\s*"([^"]+)"', text[start:end])


def interface_text() -> str:
    return INTERFACE.read_text(encoding="utf-8")


def test_count_and_names() -> None:
    print("\n== 1. 选项数量与成员数一致；选项名 = 成员行名 = 今天手写的 46 个 ==")
    cases = options.derive_target_options(LORD_BATTLE)
    check("derive 选项数 == 成员数", len(cases) == len(LORD_BATTLE.members),
          f"options={len(cases)} members={len(LORD_BATTLE.members)}")
    check("derive 选项数 == 46", len(cases) == 46, f"got={len(cases)}")
    check("选项名 == 成员行名（保持顺序）",
          [c["name"] for c in cases] == [m.行名 for m in LORD_BATTLE.members])

    block = options.derive_option_block(LORD_BATTLE)
    check("option 块是 select 且 case 数一致",
          block["type"] == "select" and len(block["cases"]) == len(cases))
    check("default_case = 第一个成员行名",
          block["default_case"] == cases[0]["name"] == LORD_BATTLE.members[0].行名)

    hand = real_interface_names(interface_text())
    check("派生出的选项名与 interface.json 今天手写的 46 个逐字一致（只读，不改）",
          hand == [c["name"] for c in cases], f"got={hand[:3]}.../{len(hand)}")

    # 子族拆分：领主战 17 + 降临讨伐 29（#32 真机行扫），顺序也与配置一致。
    lords = [c["name"] for c in cases[: len(LORDS)]]
    joss = [c["name"] for c in cases[len(LORDS):]]
    check("领主战 17 = 配置顺序", lords == [m.行名 for m in LORDS])
    check("降临讨伐 29 = 配置顺序", joss == [m.行名 for m in JOSS], f"got={len(joss)}")


def test_config_driven_add_remove() -> None:
    print("\n== 2. 增删一个成员 -> 选项列表随之变化（纯数据驱动，不改派生代码） ==")
    base = len(LORD_BATTLE.members)
    extra = member("领主战", "新成员·测试", "新成员·测试", ["初级"])
    added = FamilyConfig(family=FAMILY, members=[*LORD_BATTLE.members, extra],
                         overrides=list(LORD_BATTLE.overrides))
    removed = FamilyConfig(family=FAMILY, members=list(LORD_BATTLE.members[:-1]),
                           overrides=list(LORD_BATTLE.overrides))

    add_cases = options.derive_target_options(added)
    rm_cases = options.derive_target_options(removed)
    check("加一个成员 -> 选项 +1", len(add_cases) == base + 1, f"got={len(add_cases)}")
    check("新成员出现在选项末尾", add_cases[-1]["name"] == "新成员·测试")
    check("删一个成员 -> 选项 -1", len(rm_cases) == base - 1, f"got={len(rm_cases)}")
    check("删掉的成员不再出现",
          rm_cases and all(c["name"] != LORD_BATTLE.members[-1].行名 for c in rm_cases))


def test_injection_idempotent() -> None:
    print("\n== 3. 注入幂等：同一文本注入两次，结果字节相同（ADR-0001） ==")
    once = options.inject_option(SKELETON, LORD_BATTLE)
    twice = options.inject_option(once, LORD_BATTLE)
    check("骨架注入两次字节相同", once == twice)
    check("注入后骨架文本恰好是『本配置注入后』的样子",
          options.verify_injection(once, LORD_BATTLE))
    check("注入没有丢原有条目", '"抽哪个池"' in once)

    real = interface_text()
    before = INTERFACE.read_bytes()
    r_once = options.inject_option(real, LORD_BATTLE)
    r_twice = options.inject_option(r_once, LORD_BATTLE)
    check("真实 interface 文本注入两次字节相同", r_once == r_twice)
    check("真实 interface 文本注入后 verify 通过",
          options.verify_injection(r_once, LORD_BATTLE))
    check("注入只做内存操作：interface.json 磁盘字节未变",
          INTERFACE.read_bytes() == before)


def test_drift_detected() -> None:
    print("\n== 4. 手改选项使之与配置不一致 -> 判为漂移（verify=False -> 套件红） ==")
    real = interface_text()
    injected = options.inject_option(real, LORD_BATTLE)
    check("前提：未手改时 verify=True", options.verify_injection(injected, LORD_BATTLE))

    # (a) 手改一个 case 名
    hand_name = injected.replace('"name": "猩红巨熊讨伐"', '"name": "被手改了"', 1)
    check("手改 case 名被抓住（verify=False）",
          hand_name != injected and not options.verify_injection(hand_name, LORD_BATTLE))

    # (b) 手删一个 case（把生成区里那一行连同缩进删掉）
    hand_drop = re.sub(r'\s*"name": "不死王瑞西塔尔讨伐",\n', "\n", injected, count=1)
    check("手删一个 case 被抓住（verify=False）",
          hand_drop != injected and not options.verify_injection(hand_drop, LORD_BATTLE))

    # (c) 往生成区里手加一个 case
    hand_add = injected.replace(
        '"type": "select",',
        '"type": "select",\n        "extra": [{"name": "手加的"}]', 1,
    )
    check("手加一个 case 被抓住（verify=False）",
          hand_add != injected and not options.verify_injection(hand_add, LORD_BATTLE))


def test_subfamily_override_derived() -> None:
    print("\n== 5. 覆盖由配置派生：降临讨伐成员关掉全局「领主战页签」，领主战成员不关 ==")
    cases = {c["name"]: c for c in options.derive_target_options(LORD_BATTLE)}
    lord = cases[LORDS[0].行名]
    joss = cases[JOSS[0].行名]
    check("领主战成员只有目标行节点",
          options.TARGET_ROW_NODE in lord["pipeline_override"]
          and "SpecialTabLord" not in lord["pipeline_override"])
    check("降临讨伐成员额外关掉「领主战页签」（SpecialTabLord -> __NONE__）",
          joss["pipeline_override"].get("SpecialTabLord", {})
          .get("recognition", {}).get("param", {}).get("expected") == ["__NONE__"])

    # 去掉覆盖后，降临讨伐成员不再带 SpecialTabLord —— 证明它来自配置而非硬编码。
    no_ov = FamilyConfig(family=FAMILY, members=list(LORD_BATTLE.members))
    joss_plain = options.derive_target_options(no_ov)[len(LORDS)]["pipeline_override"]
    check("移除配置里的覆盖后 SpecialTabLord 消失（覆盖来自配置）",
          "SpecialTabLord" not in joss_plain)


def test_hook_reports_pass() -> None:
    print("\n== 6. 挂点 #6 已点亮（probe=True），且本模块自带的破坏实验成立 ==")
    check("probe_derive_gui_options() 返回 True", hooks_6.probe_derive_gui_options() is True)
    check("prove_red() 成立：derive 丢一个成员 -> 守卫变红", hooks_6.prove_red() is True)


def main() -> None:
    print("=" * 70)
    print("离线单测：GUI 目标选项由配置生成（scene.options / hooks_6）")
    print("=" * 70)
    test_count_and_names()
    test_config_driven_add_remove()
    test_injection_idempotent()
    test_drift_detected()
    test_subfamily_override_derived()
    test_hook_reports_pass()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
