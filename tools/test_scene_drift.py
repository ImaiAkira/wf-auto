# -*- coding: utf-8 -*-
"""离线单测：配置 ↔ 磁盘产物 的漂移校验（ticket #7）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_drift.py

覆盖 ticket #7 的四条验收标准：

  1. 两者一致 -> 绿（真实树 check_all() == []）；
  2. 只改配置不改 JSON -> 红（prove-red 在**临时副本**里改 scene：成员行名 / 页面判据）；
  3. 只改 JSON 不改配置 -> 红（本文件在**临时副本**里改 interface.json / pipeline JSON）；
  4. 校验报告点名声明的成员 / 规则（不是「mismatch」一句了事）。

本文件只**读**真实 ``assets/**``（只读断言保证磁盘字节不变）；所有破坏都发生在
``tempfile`` 副本里。挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_7.py``。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402
from scene.config import FamilyConfig  # noqa: E402
from scene.lord_battle import FAMILY, LORD_BATTLE  # noqa: E402

import hooks_7  # noqa: E402

INTERFACE = REPO_ROOT / "assets" / "interface.json"
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mentions(msgs: list[str], *needles: str) -> bool:
    """是否至少有一条消息同时点名全部 ``needles``（报告要能指出是谁）。"""
    return any(all(n in m for n in needles) for m in msgs)


def _temp_repo_with_assets() -> Path:
    """把真实 assets 的 interface.json + pipeline 复制到临时仓库根，返回该根。"""
    root = Path(tempfile.mkdtemp(prefix="wf_drift_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(INTERFACE, root / "assets" / "interface.json")
    shutil.copytree(PIPELINE_DIR, root / "assets" / "resource" / "pipeline")
    return root


# ---------------------------------------------------------------------------
# 1. 真实树：一致 -> 绿
# ---------------------------------------------------------------------------
def test_real_tree_green() -> None:
    print("\n== 1. 真实树：配置与磁盘产物一致 -> check_all() == [] ==")
    msgs = drift.check_all()
    check("真实树无漂移", msgs == [], f"drift={msgs}")
    check("挂点 config-json-drift 已点亮（probe=True）",
          hooks_7.probe_config_json_drift() is True)


# ---------------------------------------------------------------------------
# 2. 检查 1：只改 JSON（interface.json）-> 红并点名
# ---------------------------------------------------------------------------
def test_check1_json_side() -> None:
    print("\n== 2. 检查 1：只改 interface.json（配置不动）-> 红并点名成员 ==")
    text = _read(INTERFACE)

    # (a) 删掉一个成员的 case。
    removed = re.sub(r"[ \t]*\{ \"name\": \"猩红巨熊讨伐\"[^\n]*\n", "", text, count=1)
    check("前提：确实删掉了一行", removed != text)
    root = _temp_repo_with_assets()
    try:
        (root / "assets" / "interface.json").write_text(removed, encoding="utf-8")
        msgs = drift.option_drift(LORD_BATTLE, root / "assets" / "interface.json")
        check("删成员 -> 报红", msgs != [])
        check("报告点名被删的成员「猩红巨熊讨伐」", _mentions(msgs, "猩红巨熊讨伐"))
        check("报告说明是「配置改了 / JSON 没跟上」", _mentions(msgs, "猩红巨熊讨伐", "没有它"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 往「打哪个副本」的 cases 里塞一个凭空冒出的成员。
    idx = text.index('"cases": [', text.index('"打哪个副本": {'))
    at = text.index("[", idx) + 1
    added = (
        text[:at]
        + '\n                { "name": "凭空冒出的成员", "pipeline_override": {} },'
        + text[at:]
    )
    root = _temp_repo_with_assets()
    try:
        (root / "assets" / "interface.json").write_text(added, encoding="utf-8")
        msgs = drift.option_drift(LORD_BATTLE, root / "assets" / "interface.json")
        check("加成员 -> 报红", msgs != [])
        check("报告点名多出的成员「凭空冒出的成员」", _mentions(msgs, "凭空冒出的成员"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (c) 只改一个 case 的行名 OCR / ROI -> 报红并点名（override 漂移）。
    tampered = text.replace("[150, 440, 320, 800]", "[150, 441, 320, 800]", 1)
    check("前提：改到了 SpecialEnterBoss 的 ROI", tampered != text)
    root = _temp_repo_with_assets()
    try:
        (root / "assets" / "interface.json").write_text(tampered, encoding="utf-8")
        msgs = drift.option_drift(LORD_BATTLE, root / "assets" / "interface.json")
        check("改 JSON 里的 ROI -> 报红", msgs != [])
        check("报告点名第一个成员「猩红巨熊讨伐」", _mentions(msgs, "猩红巨熊讨伐", "pipeline_override"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. 检查 1：只改配置（增 / 删 / 改名 / 换序）-> 红并点名
# ---------------------------------------------------------------------------
def test_check1_config_side() -> None:
    print("\n== 3. 检查 1：只改配置（不改 JSON）-> 红并点名成员 ==")
    base = list(LORD_BATTLE.members)

    def with_members(members):
        return FamilyConfig(family=FAMILY, members=members, overrides=list(LORD_BATTLE.overrides))

    # (a) 删一个成员（配置少声明）。
    removed = with_members(base[:-1])
    msgs = drift.option_drift(removed, INTERFACE)
    check("配置删成员 -> 报红", msgs != [])
    check("报告点名 JSON 多出的成员", _mentions(msgs, base[-1].行名, "没有声明"))

    # (b) 加一个成员（配置多声明）。
    from scene.config import member

    extra = member("领主战", "新成员·测试", "新成员·测试", ["初级"])
    added = with_members([*base, extra])
    msgs = drift.option_drift(added, INTERFACE)
    check("配置加成员 -> 报红", msgs != [])
    check("报告点名新成员「新成员·测试」", _mentions(msgs, "新成员·测试", "没有它"))

    # (c) 改名一个成员。
    renamed_first = member(base[0].子族, base[0].id, base[0].行名 + "·改", base[0].支持难度集)
    renamed = with_members([renamed_first, *base[1:]])
    msgs = drift.option_drift(renamed, INTERFACE)
    check("配置改名一个成员 -> 报红", msgs != [])
    check("报告点名旧名与新名", _mentions(msgs, base[0].行名 + "·改") and _mentions(msgs, base[0].行名))

    # (d) 换序（集合相同、顺序不同）。
    swapped = with_members([base[1], base[0], *base[2:]])
    msgs = drift.option_drift(swapped, INTERFACE)
    check("配置换序 -> 报红", msgs != [])
    check("报告点名「顺序」", _mentions(msgs, "顺序"))


# ---------------------------------------------------------------------------
# 4. 检查 2：只改 pipeline JSON（配置不动）-> 红并点名规则
# ---------------------------------------------------------------------------
def test_check2_json_side() -> None:
    print("\n== 4. 检查 2：只改 pipeline JSON（配置不动）-> 红并点名规则 ==")

    def mutate(rel: str, old: str, new: str) -> list[str]:
        root = _temp_repo_with_assets()
        try:
            path = root / "assets" / "resource" / "pipeline" / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise RuntimeError(f"破坏点没找到：{old!r}")
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            return drift.recognition_drift(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # (a) 改 tab 判据的 OCR 串。
    msgs = mutate("special_dungeon.json", '"expected": ["^领主战$"]', '"expected": ["^领主战X$"]')
    check("改 SpecialTabLord 的 OCR -> 报红", msgs != [])
    check("报告点名规则「领主战页签」与节点 SpecialTabLord",
          _mentions(msgs, "领主战页签", "SpecialTabLord"))

    # (b) 改编队页挑战按钮的 ROI。
    msgs = mutate("special_dungeon.json", '"roi": [180, 1000, 400, 180]', '"roi": [180, 999, 400, 180]')
    check("改 SpecialChallenge 的 ROI -> 报红", msgs != [])
    check("报告点名规则「编队页」", _mentions(msgs, "编队页"))

    # (c) 改战斗 HUD 的公共叶子（common.json::PubBattleTime）。
    msgs = mutate("common.json", '"时间 \\\\d+:\\\\d+"', '"时间 \\\\d+:\\\\d+X"')
    check("改战斗 HUD 公共叶子 -> 报红", msgs != [])
    check("报告点名规则「战斗HUD」", _mentions(msgs, "战斗HUD"))

    # (d) 改列表页行节点的 ROI（scene.options.TARGET_ROW_ROI 对照）。
    msgs = mutate("special_dungeon.json", '"roi": [150, 440, 320, 800]', '"roi": [150, 442, 320, 800]')
    check("改 SpecialEnterBoss 的 ROI -> 报红", msgs != [])
    check("报告点名目标行 / SpecialEnterBoss", _mentions(msgs, "SpecialEnterBoss"))


# ---------------------------------------------------------------------------
# 5. prove-red：两个检查各自能红（破坏在 hooks_7 里，副本 + 子进程）
# ---------------------------------------------------------------------------
def test_prove_red_both_checks() -> None:
    print("\n== 5. prove-red：改坏配置层 -> 检查 1、检查 2 各自变红 ==")
    check("hooks_7.prove_red() 成立（两个检查都可红）", hooks_7.prove_red() is True)


# ---------------------------------------------------------------------------
# 6. 只读：跑完校验，真实 assets 字节不变
# ---------------------------------------------------------------------------
def test_read_only() -> None:
    print("\n== 6. 只读：跑完全部校验，真实 assets 字节不变 ==")
    watched = [INTERFACE, *sorted(PIPELINE_DIR.glob("*.json"))]
    before = {p: p.read_bytes() for p in watched}

    drift.check_all()
    hooks_7.probe_config_json_drift()

    after = {p: p.read_bytes() for p in watched}
    changed = [p.name for p in watched if before[p] != after[p]]
    check("assets/** 字节未变（校验全程只读）", changed == [], f"changed={changed}")


def main() -> None:
    print("=" * 70)
    print("离线单测：配置 ↔ pipeline JSON 漂移校验（scene.drift / hooks_7）")
    print("=" * 70)
    test_real_tree_green()
    test_check1_json_side()
    test_check1_config_side()
    test_check2_json_side()
    test_prove_red_both_checks()
    test_read_only()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
