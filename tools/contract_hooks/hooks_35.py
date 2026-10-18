# -*- coding: utf-8 -*-
"""#35：详情页【难度名 ↔ 战斗按钮】按真机几何配对，且命中的战斗框隶属于【声明的难度名】。

seam：``agent/side_impl.pick_target_battle_box`` / ``SpecialTargetFightRecognition``
      ↔ ``assets/resource/pipeline/special_dungeon.json``（``SpecialFightTargetRow``）。

背景（#35 真机逐成员扫描，设备 127.0.0.1:16384 / CET-AL00 / RANK158）
---------------------------------------------------------------------
旧默认 ``pair="above"`` 假设【战斗】在难度名【上方】。真机详情页恰恰相反 ——
**难度名在上、战斗在其下方 ≈40px（且更靠左）**（``recon_unm/recon.log`` 直接 OCR）：

    妖狐超级 y=456 → 战斗 y=501    妖狐高级+ y=648 → 战斗 y=689
    妖狐高级 y=837 → 战斗 y=880    妖狐中级   y=1028 → 战斗 y=1068
    诅咒弧魔艾基尔中级 y=458 → 战斗 y=498（单难度行成员）

两类后果：
1. **单难度行成员确定性卡死** —— 上方没有任何战斗 → 永不命中 → ``SpecialEntry`` ↔
   ``SpecialWait`` 循环到超时（实测 6 个：Sec-5200Li讨伐 / 艾基尔·嫉妒讨伐 /
   寄居蟹船长讨伐 / 废墟魔像讨伐 / 废墟守卫·火讨伐 / 诅咒弧魔艾基尔讨伐）；
2. **多难度行成员静默打错难度** —— 点到上一行的战斗（日志实证：中级 y=1044 配到
   y=890 的【高级】战斗，gap≈154）。

守卫 ``detail-battle-box-pairs-declared-difficulty``（真机帧，离线可复算）
-----------------------------------------------------------------------
用**一对真机详情页帧**做夹具（OCR 逐条内嵌，帧文件随仓）：
* 多行帧 ``tools/frames/lord_detail_multidiff.png``（妖狐讨伐，4 个难度行）；
* 单行帧 ``tools/frames/lord_detail_singlediff.png``（诅咒弧魔艾基尔讨伐，1 行）。

对每个「声明的难度」断言：
1. **命中的战斗框 = 该难度名所在行的战斗框**（与实测框逐值相等）；
2. **归属证明**：选中的战斗框回指到的「同一行难度名」逐字匹配声明的难度
   （``detail["row_owner"]`` 的文本能被声明的难度正则命中）—— 证明打的是**声明的难度**，
   不是「某一行的战斗」；
3. **单行成员不再卡死**：单行帧里唯一的难度行必须命中（返回非 None）；
4. 产物绑定：``special_dungeon.json::SpecialFightTargetRow`` 的
   ``custom_recognition_param`` 编码了真机几何（``pair="below"``）。

★诚实边界★：守卫用内嵌 OCR（真机逐字），不重跑 MAA OCR（重跑是 verify_* 的活，
套件里跳过）；帧文件本身随仓，供交叉核对。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_35.py``）：
把配对默认值退回 ``above``（临时副本）-> 守卫必须变红。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

HOOK_ID = "detail-battle-box-pairs-declared-difficulty"

# ---------------------------------------------------------------------------
# 一对真机详情页帧（OCR 逐条内嵌自 recon_unm/recon.log，720 空间）。
# 帧文件已随仓：tools/frames/lord_detail_multidiff.png / _singlediff.png。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形。
# ---------------------------------------------------------------------------
MULTI_ITEMS = [
    ("COMPLETE!!", [15, 388, 126, 22]),
    ("COMPLETE!!", [15, 578, 125, 23]),
    ("COMPLETE!!", [15, 769, 123, 24]),
    ("COMPLETE!!", [15, 960, 127, 22]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [56, 530, 96, 30]),
    ("推荐编成", [56, 721, 94, 29]),
    ("推荐编成", [56, 912, 94, 29]),
    ("推荐编成", [56, 1102, 94, 30]),
    # 四个难度行的【战斗】按钮（真机实测 y=501/689/880/1068）。
    ("战斗", [88, 501, 31, 16]),
    ("战斗", [87, 689, 32, 20]),
    ("战斗", [87, 880, 32, 20]),
    ("战斗", [86, 1068, 35, 24]),
    ("领主战", [201, 618, 71, 28]),
    ("妖狐高级+", [201, 648, 139, 32]),
    ("领主战", [201, 808, 72, 29]),
    ("领主战", [201, 998, 72, 30]),
    ("妖狐中级", [201, 1028, 121, 33]),
    ("领主战", [202, 428, 70, 28]),
    ("妖狐超级", [202, 456, 119, 33]),
    ("妖狐高级", [202, 837, 119, 33]),
]

SINGLE_ITEMS = [
    ("NEW", [14, 386, 53, 24]),
    ("返回", [30, 1246, 46, 26]),
    ("推荐编成", [55, 530, 97, 30]),
    # 单难度行成员唯一的一行（名 y=458 → 战斗 y=498）。
    ("战斗", [86, 498, 33, 20]),
    ("诅咒弧魔艾基尔", [161, 200, 398, 60]),
    ("领主战", [201, 428, 71, 28]),
    ("诅咒弧魔艾基尔中级", [203, 458, 252, 28]),
]

# 帧夹具：每条 = 帧名 / 来源文件 / OCR 条目 / {声明的难度: 该行战斗框（实测）}。
FRAMES = [
    {
        "name": "详情页·多难度行（妖狐讨伐）",
        "source": "tools/frames/lord_detail_multidiff.png",
        "items": MULTI_ITEMS,
        "expected": {
            "超级": [88, 501, 31, 16],
            "高级+": [87, 689, 32, 20],
            "高级": [87, 880, 32, 20],
            "中级": [86, 1068, 35, 24],
        },
    },
    {
        "name": "详情页·单难度行（诅咒弧魔艾基尔讨伐）",
        "source": "tools/frames/lord_detail_singlediff.png",
        "items": SINGLE_ITEMS,
        "expected": {
            "中级": [86, 498, 33, 20],
        },
    },
]


def _import_side_impl(agent_dir: Path | None = None):
    """导入 agent/side_impl（可指定副本目录，供 prove-red）。"""
    d = str(agent_dir or AGENT_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    import side_impl  # noqa: PLC0415

    return side_impl


def _diff_regex(declared: str) -> str:
    """声明的难度 → 行名正则（与 batch_plan.DIFF_REGEX 同源，绝不另写一份）。"""
    from batch_plan import DIFF_REGEX  # noqa: PLC0415

    return DIFF_REGEX[declared]


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _frame_failures(si=None, agent_dir: Path | None = None) -> list[str]:
    """真机帧断言：命中的战斗框隶属【声明的难度名】。返回失败信息（空 = 绿）。"""
    si = si or _import_side_impl(agent_dir)
    msgs: list[str] = []

    if getattr(si, "DEFAULT_PAIR", None) != "below":
        msgs.append(
            f"配对默认值 DEFAULT_PAIR={getattr(si, 'DEFAULT_PAIR', None)!r} 不是真机几何 'below'"
            f"（#35：难度名在上、战斗在下方 ≈40px）"
        )

    for frame in FRAMES:
        src = REPO_ROOT / frame["source"]
        if not src.is_file():
            msgs.append(f"真机帧缺失：{frame['source']}（守卫失去证据）")
        for declared, exp_box in frame["expected"].items():
            rx = _diff_regex(declared)
            box, detail = si.pick_target_battle_box(frame["items"], difficulty=rx)
            tag = f"真机帧「{frame['name']}」声明难度「{declared}」"
            if box is None:
                msgs.append(f"{tag}：未命中任何战斗框（单行成员卡死 / 多行配错）detail={detail}")
                continue
            if list(box) != list(exp_box):
                msgs.append(
                    f"{tag}：命中战斗框 {list(box)} != 该难度行的实测战斗框 {exp_box}"
                    f"（配对到了别的难度行）"
                )
            owner = detail.get("row_owner")
            owner_text = owner[0] if owner else None
            if owner_text is None:
                msgs.append(f"{tag}：未能把战斗框回指到同一行难度名（归属无法证明）")
            elif not re.search(rx, owner_text):
                msgs.append(
                    f"{tag}：命中战斗框同一行的难度名是 {owner_text!r}，不是声明的难度"
                    f"（静默打错难度）"
                )
            # 独立几何复核：战斗框中心与声明的难度名中心纵向差必须 ≈40px（同一行）。
            names = [b for t, b in frame["items"] if re.search(rx, t or "")]
            if names:
                dy = _center(box)[1] - _center(names[0])[1]
                if not (0 < dy <= si.BATTLE_ROW_MAX_GAP):
                    msgs.append(
                        f"{tag}：战斗框在难度名的上方或过远（dy={dy:.0f}），不是真机几何（下方 ≈40px）"
                    )
    return msgs


def _pipeline_failures(path: Path | None = None) -> list[str]:
    """产物绑定：special_dungeon.json 的 SpecialFightTargetRow 编码真机几何配对。"""
    msgs: list[str] = []
    p = path or PIPELINE
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"读不到 {p}：{exc}"]
    # 去 JSONC 注释（只去掉行注释即可，本文件用 //）。
    stripped = "\n".join(
        line.split("//", 1)[0] if line.lstrip().startswith("//") else line
        for line in text.splitlines()
    )
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return [f"解析 special_dungeon.json 失败：{exc}"]
    node = data.get("SpecialFightTargetRow") or {}
    param = ((node.get("recognition") or {}).get("param") or {})
    crp = param.get("custom_recognition_param") or {}
    if param.get("custom_recognition") != "special_target_fight":
        msgs.append("SpecialFightTargetRow 不再是 custom special_target_fight")
    if crp.get("pair") != "below":
        msgs.append(
            f"SpecialFightTargetRow 的 pair={crp.get('pair')!r} 不是真机几何 'below'（#35）"
        )
    return msgs


def _pair_failures(agent_dir: Path | None = None, pipeline: Path | None = None) -> list[str]:
    """#35 全部离线断言：真机帧配对 + 产物绑定。"""
    return _frame_failures(agent_dir=agent_dir) + _pipeline_failures(pipeline)


def probe_battle_box_pairs_declared_difficulty() -> bool:
    """#35：详情页战斗框按真机几何配对，且隶属声明的难度名（真机帧）。"""
    return _pair_failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\contract_hooks\hooks_35.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_pair_above(agent_dir: Path) -> None:
    """破坏：把配对默认值退回旧的「战斗在难度名上方」假设。"""
    _sub(agent_dir / "side_impl.py", 'DEFAULT_PAIR = "below"', 'DEFAULT_PAIR = "above"')


def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_35\n"
        f"print('PROBE_RESULT', repr(hooks_35._pair_failures({str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral35_"))
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
    """真实绿；把配对默认值退回 ``above`` -> 守卫变红。"""
    print("hooks_35 prove-red：把配对默认值退回 above，要求 "
          "detail-battle-box-pairs-declared-difficulty 变红")
    green = probe_battle_box_pairs_declared_difficulty() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：按真机几何配对、命中声明难度（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook35_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_pair_above(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 退回 above -> 探针变红")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#35",
        "详情页【难度名↔战斗按钮】按真机几何配对（名在上、战斗下方 ≈40px），命中框隶属声明的难度名；"
        "单行成员不再卡死（真机帧）",
        probe_battle_box_pairs_declared_difficulty,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
