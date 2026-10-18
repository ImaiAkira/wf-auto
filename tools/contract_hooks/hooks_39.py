# -*- coding: utf-8 -*-
"""#39：难度集**运行时从详情页发现**（同一成员在不同账号进度下可用难度不同）。

seam：``agent/side_impl.discover_difficulties`` / ``classify_detail_difficulty`` /
``plan_absent_difficulty_action``（运行时发现 + 不存在时的明确行为）
      ↔ ``scene.lord_battle``（静态按成员难度表 = 某账号实测、可能不适用）
      ↔ ``scene.drift``（GUI 难度选项与词表一致）。

背景（#39）
----------
「某成员支持哪些难度」是**账号进度相关**的，因此**静态按成员难度表按定义就会错**：
同一成员（``红嫉机兵``）在
  · 已通关账号（``机型A``/RANK158，设备 127.0.0.1:16385）详情页读 4 档
    （``超级 / 高级+ / 高级 / 中级``，见 ``det_降临讨伐_红嫉机兵.ocr.txt``）；
  · 早期账号（``账号B``/RANK130，设备 127.0.0.1:16448）详情页**只有** ``中级``
    （见 ``sweepjoss/recon_03_detail.png`` / ``recon_detail_ocr.json``）。
静态表若照搬「4 档」，在早期账号上会去打一个**不存在的** ``超级``（静默打错档 / 卡死）。

守卫 ``difficulty-discovered-from-detail-page``（真机帧，离线可复算）
------------------------------------------------------------------
用**同一成员、两个账号**的两帧真机详情页 OCR 做夹具（逐条内嵌；帧文件随仓）：
* ``tools/frames/lord_detail_redjoss_cleared.png``（清关账号，4 档）；
* ``tools/frames/lord_detail_redjoss_early.png``（早期账号，1 档）。

断言：
1. ``discover_difficulties`` 分别读出 ``{超级,高级+,高级,中级}`` / ``{中级}``（**发现**通过）；
2. 清关账号：声明 ``超级`` → ``present`` 且命中的战斗框 = 该难度行的战斗框；
3. 早期账号：声明 ``超级`` → ``absent``（**静态表会去打的档，真机并不存在**）；
   声明 ``中级`` → ``present`` 且命中 ``中级`` 行的战斗框；
4. ``plan_absent_difficulty_action``：批量 → ``skip``（跳过并继续），单目标 → ``stop``
   （明确收工），``undetermined`` → ``stop``；两者都**不静默打错档、不卡死**；
5. **静态必然失败**：静态表（``hooks_32.DEVICE_DIFFICULTIES[红嫉机兵]``）说 ``超级`` 可用，
   而早期账号帧的发现结果是 ``absent`` —— 两者直接矛盾，证明静态做法必错；
6. 配置：#39 已删除「未测定占位」常量（``scene/lord_battle.py`` 源码里不再出现该符号）；
   ``诅咒弧魔艾基尔讨伐`` 的难度集 = ``("中级",)``（真机实读）；
7. ``drift``：#39 起 GUI「打哪个难度」由 ``scene.config.DIFFICULTIES`` 派生并受
   ``scene.drift`` 把守（``check_all()`` 为空）。

★诚实边界★：守卫用内嵌 OCR（真机逐字），不重跑 MAA OCR（重跑是 verify_* 的活）；帧文件
本身随仓，供交叉核对。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_39.py``）：把
``discover_difficulties`` 换成「返回静态表」的实现（临时 agent 副本）-> 守卫必须变红。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"

HOOK_ID = "difficulty-discovered-from-detail-page"

# ---------------------------------------------------------------------------
# 真机详情页帧（同一成员「红嫉机兵」，两个账号）——OCR 逐条内嵌。
# 清关账号：``det_降临讨伐_红嫉机兵.ocr.txt``（设备 127.0.0.1:16385）；
# 早期账号：``sweepjoss/recon_detail_ocr.json``（设备 127.0.0.1:16448）。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形（720 空间）。
# ---------------------------------------------------------------------------
CLEARED_ITEMS = [
    ("COMPLETE!!", [15, 769, 123, 23]),
    ("COMPLETE!!", [15, 960, 123, 22]),
    ("COMPLETE!!", [17, 388, 120, 22]),
    ("返回", [30, 1246, 46, 26]),
    ("×10,562", [45, 332, 99, 30]),
    ("×400", [48, 301, 65, 25]),
    ("MPLETE!!", [48, 578, 88, 23]),
    ("推荐编成", [56, 530, 96, 30]),
    ("推荐编成", [56, 721, 96, 29]),
    ("推荐编成", [56, 913, 96, 28]),
    ("推荐编成", [56, 1102, 94, 30]),
    ("战斗", [87, 501, 32, 16]),
    ("战斗", [90, 692, 27, 16]),
    ("战斗", [90, 1073, 27, 16]),
    ("5", [93, 888, 7, 6]),
    ("894/106", [95, 20, 112, 28]),
    ("主城", [157, 1248, 44, 25]),
    ("红嫉机兵", [191, 152, 380, 93]),
    ("降临讨伐", [199, 618, 93, 28]),
    ("降临讨伐", [201, 428, 92, 28]),
    ("降临讨伐", [201, 1000, 94, 28]),
    ("降临讨伐", [202, 809, 93, 28]),
    ("降临讨伐", [203, 128, 143, 28]),
    ("红机兵海茵莱特超级", [203, 458, 253, 28]),
    ("红机兵海茵莱特高级+", [203, 649, 272, 28]),
    ("红机兵海茵莱特高级", [203, 840, 253, 28]),
    ("红机兵海茵莱特中级", [203, 1030, 253, 28]),
    ("推荐属性", [207, 914, 89, 28]),
    ("推荐属性", [209, 532, 86, 28]),
    ("推荐属性", [209, 725, 86, 24]),
    ("推荐属性", [210, 1106, 91, 24]),
    ("STE", [231, 240, 39, 13]),
    ("角色", [275, 1244, 47, 29]),
    ("M-ROBOT", [277, 241, 94, 15]),
    ("O水", [297, 1106, 59, 24]),
    (")水", [316, 534, 38, 26]),
    ("水", [317, 726, 37, 22]),
    ("水", [317, 917, 36, 21]),
    ("体力", [365, 533, 47, 25]),
    ("体力", [365, 724, 47, 25]),
    ("体力", [365, 914, 47, 26]),
    ("体力", [365, 1105, 47, 25]),
    ("O", [379, 244, 10, 9]),
    ("E", [389, 242, 13, 11]),
    ("商店", [397, 1246, 43, 26]),
    ("INFERNO", [399, 240, 107, 17]),
    ("20", [446, 534, 30, 23]),
    ("16", [446, 725, 30, 23]),
    ("14", [447, 916, 30, 22]),
    ("10", [447, 1106, 30, 23]),
    ("2,779,425", [510, 18, 94, 24]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("兑换道具", [614, 328, 82, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

EARLY_ITEMS = [
    ("NEW", [18, 389, 46, 20]),
    ("返回", [30, 1246, 46, 26]),
    ("×3,961", [46, 300, 83, 28]),
    ("×10,739", [46, 336, 95, 24]),
    ("×1,080", [47, 266, 85, 28]),
    ("推荐编成", [55, 530, 97, 30]),
    ("战斗", [88, 501, 29, 16]),
    ("999/101", [93, 17, 110, 31]),
    ("主城", [157, 1248, 44, 25]),
    ("红嫉族机兵", [191, 149, 382, 99]),
    ("降临讨伐", [202, 428, 91, 28]),
    ("降临过伐", [203, 128, 145, 28]),
    ("红机兵海茵莱特中级", [203, 458, 253, 28]),
    ("推荐属性", [206, 533, 94, 28]),
    ("STEAM-ROBO", [227, 240, 133, 17]),
    ("角色", [276, 1246, 45, 26]),
    ("O水", [301, 534, 61, 24]),
    ("体力", [361, 534, 50, 24]),
    ("o", [379, 244, 7, 8]),
    ("S", [390, 245, 9, 5]),
    ("商店", [397, 1245, 43, 27]),
    ("INFERNO", [402, 240, 104, 17]),
    ("10", [450, 534, 26, 22]),
    ("3,140,055", [509, 18, 95, 24]),
    ("扭蛋", [514, 1244, 47, 28]),
    ("首次报酬", [542, 429, 82, 27]),
    ("兑换道具", [614, 328, 82, 28]),
    ("菜单", [636, 1248, 45, 25]),
]

FRAMES = [
    {
        "name": "详情页·红嫉机兵（清关账号）",
        "source": "tools/frames/lord_detail_redjoss_cleared.png",
        "items": CLEARED_ITEMS,
        "available": {"超级", "高级+", "高级", "中级"},
    },
    {
        "name": "详情页·红嫉机兵（早期账号）",
        "source": "tools/frames/lord_detail_redjoss_early.png",
        "items": EARLY_ITEMS,
        "available": {"中级"},
    },
]

MEMBER = "红嫉机兵"

# 静态表（清关账号实测）——``hooks_32.DEVICE_DIFFICULTIES`` 的同一值；守卫内联一份以
# 便独立证明「静态必然失败」，并断言二者一致（避免两处漂移）。
STATIC_CLEARED_SET = frozenset({"超级", "高级+", "高级", "中级"})

# 清关账号帧里「超级」行的战斗框（实测）。
CLEARED_SUPER_BOX = [87, 501, 32, 16]
# 早期账号帧里「中级」行的战斗框（实测）。
EARLY_MID_BOX = [88, 501, 29, 16]


def _import_side_impl(agent_dir: Path | None = None):
    """导入 ``agent/side_impl``（可指定副本目录，供 prove-red）。"""
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _scene_on_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _static_matches_hooks32() -> bool:
    """静态表副本 == hooks_32 里的真机实测集（同一成员）。返回是否一致。"""
    try:
        from contract_hooks import hooks_32  # noqa: PLC0415
    except Exception:  # noqa: BLE001 -- 独立场景（子进程）拿不到包时跳过这条
        return True
    return frozenset(hooks_32.DEVICE_DIFFICULTIES.get(MEMBER, ())) == STATIC_CLEARED_SET


def _failures(si=None, agent_dir: Path | None = None) -> list[str]:
    """#39 全部离线断言；返回失败信息列表（空 = 绿）。"""
    _scene_on_path()
    si = si or _import_side_impl(agent_dir)
    from batch_plan import DIFF_REGEX  # noqa: PLC0415

    msgs: list[str] = []

    # (0) 帧文件在场（守卫的证据）。
    for frame in FRAMES:
        if not (REPO_ROOT / frame["source"]).is_file():
            msgs.append(f"真机帧缺失：{frame['source']}（守卫失去证据）")

    # (0b) 内联静态表与 hooks_32 真机实测一致（同一事实不两写）。
    if agent_dir is None and not _static_matches_hooks32():
        msgs.append(
            f"静态表副本 {sorted(STATIC_CLEARED_SET)} != hooks_32.DEVICE_DIFFICULTIES[{MEMBER!r}]"
        )

    # (1) 运行时发现：两账号各读出实际的可用集。
    for frame in FRAMES:
        got = set(si.discover_difficulties(frame["items"]))
        if got != frame["available"]:
            msgs.append(
                f"运行时发现「{frame['name']}」：discover_difficulties={sorted(got)} "
                f"!= 详情页实读 {sorted(frame['available'])}"
            )

    # (2) 清关账号：声明「超级」= present，且命中超级行的战斗框。
    cl = si.classify_detail_difficulty(FRAMES[0]["items"], DIFF_REGEX["超级"])
    if cl.outcome != "present":
        msgs.append(f"清关账号：声明「超级」应为 present，实际 {cl.outcome}")
    box, _d = si.pick_target_battle_box(FRAMES[0]["items"], difficulty=DIFF_REGEX["超级"])
    if box is None or list(box) != CLEARED_SUPER_BOX:
        msgs.append(f"清关账号：声明「超级」命中战斗框 {box} != 实测 {CLEARED_SUPER_BOX}")

    # (3) 早期账号：声明「超级」= absent（静态表会去打的档，真机并不存在）；
    #     声明「中级」= present 且命中中级行战斗框。
    ab = si.classify_detail_difficulty(FRAMES[1]["items"], DIFF_REGEX["超级"])
    if ab.outcome != "absent":
        msgs.append(f"早期账号：声明「超级」应为 absent，实际 {ab.outcome}（会静默打错档）")
    mid = si.classify_detail_difficulty(FRAMES[1]["items"], DIFF_REGEX["中级"])
    if mid.outcome != "present":
        msgs.append(f"早期账号：声明「中级」应为 present，实际 {mid.outcome}")
    mbox, _d = si.pick_target_battle_box(FRAMES[1]["items"], difficulty=DIFF_REGEX["中级"])
    if mbox is None or list(mbox) != EARLY_MID_BOX:
        msgs.append(f"早期账号：声明「中级」命中战斗框 {mbox} != 实测 {EARLY_MID_BOX}")

    # (4) 不存在 / 不可判定时的**明确行为**：批量跳过并继续；单目标 / 不可判定 → 收工。
    skip_a, skip_r = si.plan_absent_difficulty_action(
        "absent", "超级", {"中级"}, batch_active=True, has_current=True)
    if skip_a != "skip" or not skip_r:
        msgs.append(f"absent+批量：应为 skip 且带原因，实际 {(skip_a, skip_r)}")
    stop_a, _r = si.plan_absent_difficulty_action(
        "absent", "超级", {"中级"}, batch_active=False, has_current=False)
    if stop_a != "stop":
        msgs.append(f"absent+单目标：应为 stop，实际 {stop_a}")
    und_a, _r = si.plan_absent_difficulty_action(
        "undetermined", "超级", frozenset(), batch_active=True, has_current=True)
    if und_a != "stop":
        msgs.append(f"undetermined：应为 stop，实际 {und_a}")

    # (5) ★静态必然失败★：静态表说「超级」可用，而早期账号帧的发现结果是 absent。
    if "超级" not in STATIC_CLEARED_SET:
        msgs.append("静态表副本应含「超级」（清关账号实测），否则破坏实验失去依据")
    if ab.outcome == "absent":
        pass  # 与静态表矛盾 → 静态做法必错（这就是本守卫要证明的）
    else:
        msgs.append("已无法用早期账号帧证伪静态表（ab.outcome != absent）")

    # (6) 配置：#39 删除「未测定占位」；修正 诅咒弧魔艾基尔讨伐。
    try:
        from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

        src = (REPO_ROOT / "scene" / "lord_battle.py").read_text(encoding="utf-8")
        if "_UNMEASURED" in src:
            msgs.append("scene/lord_battle.py 里仍出现「未测定占位」常量名（#39 要求删除）")
        by_name = {m.行名: tuple(m.支持难度集) for m in LORD_BATTLE.members}
        if by_name.get("诅咒弧魔艾基尔讨伐") != ("中级",):
            msgs.append(
                f"诅咒弧魔艾基尔讨伐 的难度集应为 ('中级',)（真机实读），"
                f"实际 {by_name.get('诅咒弧魔艾基尔讨伐')}"
            )
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"读取配置失败：{exc}")

    # (7) drift 为空（含 #39 新增的「打哪个难度」选项守卫）。
    try:
        from scene import drift  # noqa: PLC0415

        drift_msgs = drift.check_all(repo_root=REPO_ROOT)
        if drift_msgs:
            msgs.append(f"drift 非空：{drift_msgs}")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"drift 校验失败：{exc}")

    return msgs


def probe_difficulty_discovered_from_detail_page() -> bool:
    """#39：难度运行时从详情页发现；声明难度不存在时有明确行为；静态表必错。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_39.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_static_discovery(agent_dir: Path) -> None:
    """破坏：把「运行时发现」换成「返回静态表（清关账号实测）」——早期账号上必错。"""
    _sub(
        agent_dir / "side_impl.py",
        "    found: set[str] = set()\n",
        '    return frozenset({"超级", "高级+", "高级", "中级"})  # 静态表（清关账号实测）\n'
        "    found: set[str] = set()\n",
    )


def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针。返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_39\n"
        f"print('PROBE_RESULT', repr(hooks_39._failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral39_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def prove_red() -> bool:
    """真实绿；把「运行时发现」换成「返回静态表」-> 守卫变红（静态做法必错）。"""
    print("hooks_39 prove-red：把 discover_difficulties 换成「返回静态表」，要求 "
          "difficulty-discovered-from-detail-page 变红")
    green = probe_difficulty_discovered_from_detail_page() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：详情页发现 + 明确行为（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook39_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_static_discovery(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 换成静态表 -> 探针变红（早期账号上必错）")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#39",
        "难度运行时从详情页发现（同一成员两账号难度集不同 → 静态表必错）；声明难度不存在时"
        "跳过并继续 / 主动收工（真机帧 + 纯函数行为）",
        probe_difficulty_discovered_from_detail_page,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
