# -*- coding: utf-8 -*-
"""#41：详情页判据必须要求**真正的详情页标记**（``推荐编成``）—— 修 #39 的过松判据回归。

seam：``agent/side_impl.on_detail_page`` / ``classify_detail_difficulty`` /
``SpecialTargetFightRecognition``（运行时难度发现的「在不在详情页」门控）
      ↔ ``assets/resource/pipeline/special_dungeon.json``（``SpecialDetailGate`` 的
      ``推荐编成`` 判据；``SpecialEntry.next`` 里 ``SpecialFightTargetRow`` 的排位）
      ↔ ``scene.page_rules``「详情页」规则（同一标记，``scene.drift`` 把三者钉在一起）。

背景（#41，双账号真机实证）
---------------------------
#39 的实现报告称「gated by an on-detail-page marker（``推荐编成``）」，但代码是

    on_detail = bool(available) or '推荐编成' in texts

于是**任何出现过难度词的非详情页帧都被当成详情页**。主城轮播横幅会被 OCR 误读成
难度词（真机：``16448`` 横幅 ``地狱级`` @[33,240,53,20]；``16384`` ``超级`` @[37,154,41,20]），
⇒ ``available=['地狱级']`` ⇒ 声明的 ``中级`` 被判 ``absent`` ⇒ 成员在**导航开始之前**被假跳过
（``SpecialFightTargetRow`` 在 ``SpecialEntry.next`` 里排在 ``SpecialOpenLord`` 之前）。

守卫 ``difficulty-gate-requires-real-detail-marker``（真机主城帧，离线可复算）
------------------------------------------------------------------------------
用**两帧真机主城 OCR** 做夹具（逐条内嵌；帧来源见下），断言：

1. 两帧主城（都含被误读的难度词、都**没有** ``推荐编成``）上
   ``on_detail_page`` 为 False、``classify_detail_difficulty(..., 中级$)`` 为
   ``not_applicable``（**不是** ``absent``）—— 即**绝不假跳过**；
2. 上述帧确实含难度词（``discover_difficulties`` 非空）—— 这是破坏实验的依据：
   #39 的过松判据在这两帧上必给 ``absent``；
3. 真机**详情页**帧（复用 #39 的两个账号帧）仍照旧：声明 ``超级`` 在早期账号帧
   → ``absent``（**真跳过**仍成立）、声明 ``中级`` → ``present``；清关账号帧 ``超级`` → ``present``；
4. ``on_detail_page`` 的标记 == pipeline ``SpecialDetailGate`` 的 OCR 判据 ==
   ``scene.page_rules``「详情页」的判据（三处同源，不两写）；
5. ``SpecialFightTargetRow`` 上跑**主城帧**（用批量 override 的 ``中级$`` 参数）
   **不写下任何跳过交接状态**（``_take_detail_difficulty() is None``）——
   直接证明「主城帧上不会有跳过决定」；
6. 排位事实：``SpecialFightTargetRow`` 在 ``SpecialEntry.next`` 里排在 ``SpecialOpenLord``
   之前（本守卫的**前提**；门控修的是判据，不是顺序 —— 见报告）。

★诚实边界★：守卫用内嵌 OCR（真机逐字 / 编码复原），不重跑 MAA OCR；帧文件在证据目录，
不随仓，故**不**断言帧文件存在（避免把「素材不在本机」变成假红）。

prove-red 在文件末尾（``python tools\\contract_hooks\\hooks_41.py``）：
把 ``on_detail_page`` 退回 #39 的过松判据（``bool(available) or '推荐编成' in ...``）
-> 主城帧被判 ``absent`` -> 守卫必须变红。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE = REPO_ROOT / "assets" / "resource" / "pipeline" / "special_dungeon.json"

# 让 `from contract_hooks import hooks_39` 在【独立运行】本文件时也成立（append 到末尾，
# 避免 prove-red 子进程里抢先把副本路径盖掉）。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

HOOK_ID = "difficulty-gate-requires-real-detail-marker"

# ---------------------------------------------------------------------------
# 真机【主城】帧 OCR（720 空间，逐条内嵌）—— 携带被误读的难度词，且没有「推荐编成」。
#
# · MAIN_16448_ITEMS：设备 127.0.0.1:16448 / V2324HA / 账号B / RANK130 的主城帧
#   ``sweepjoss2/frames/joss_r5/f_0004.jpg``（= #41 报告里的误判帧）。横幅 OCR 成
#   ``地狱级`` @[33,240,53,20]（另有 ~10 条与本判据无关的长文本因原始转储编码损坏而略去，
#   它们既不是难度词也不是标记，略去不影响判定）。
# · MAIN_16384_ITEMS：设备 127.0.0.1:16384 / CET-AL00 的主城帧（``sweep_lord2/hell_m08.txt``
#   首个时间戳块，逐字）。含 ``地狱级`` @[31,69,53,20] 与 ``超级`` @[37,154,41,20]。
# 每条 = (text, [x, y, w, h])，与 OcrTask 的 box 同形。
# ---------------------------------------------------------------------------
MAIN_16448_ITEMS = [
    ("3,140,250", [509, 18, 95, 24]),
    ("999/101", [95, 20, 111, 28]),
    ("I 账号B", [0, 73, 90, 27]),
    ("IRANK", [3, 102, 67, 24]),
    ("130", [13, 122, 62, 38]),
    ("剑刃映出的脸骗不了人—一", [201, 125, 250, 27]),
    ("NEXT", [17, 190, 41, 20]),
    ("18760", [17, 206, 59, 24]),
    ("RP", [19, 228, 20, 13]),
    ("地狱级", [33, 240, 53, 20]),
    ("成长任务", [51, 368, 114, 33]),
    ("下一个推荐项", [612, 381, 101, 23]),
    ("公告", [631, 732, 46, 26]),
    ("邮件", [631, 841, 47, 25]),
    ("当前进度", [367, 928, 61, 20]),
    ("任务", [631, 949, 47, 25]),
    ("10-2", [438, 978, 59, 26]),
    ("关卡", [313, 1088, 93, 50]),
    ("活动", [80, 1120, 62, 34]),
    ("角色", [275, 1242, 47, 31]),
    ("城镇", [31, 1245, 47, 27]),
    ("商店", [395, 1245, 47, 27]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("主城", [156, 1246, 45, 27]),
    ("菜单", [636, 1246, 45, 27]),
]

MAIN_16384_ITEMS = [
    ("摇曳的迷宮", [0, 854, 242, 108]),
    ("修行之道", [22, 726, 150, 42]),
    ("主角色", [22, 1249, 61, 20]),
    ("地狱级", [31, 69, 53, 20]),
    ("超级", [37, 154, 41, 20]),
    ("成长任务", [50, 368, 116, 33]),
    ("活动", [82, 1122, 59, 31]),
    ("819/106", [93, 20, 114, 28]),
    ("崩坏域", [124, 932, 104, 61]),
    ("主城", [157, 1248, 44, 25]),
    ("角色", [275, 1244, 46, 29]),
    ("关卡", [313, 1088, 93, 50]),
    ("当前进度", [369, 928, 59, 20]),
    ("商店", [397, 1246, 43, 26]),
    ("第12章", [427, 957, 79, 28]),
    ("1-1", [442, 980, 47, 24]),
    ("2,779,415", [513, 17, 91, 27]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("Mw", [543, 925, 40, 40]),
    ("领主战", [569, 1121, 78, 29]),
    ("双", [573, 1058, 68, 68]),
    ("下一个推荐项", [612, 380, 101, 24]),
    ("公告", [631, 733, 46, 25]),
    ("邮件", [631, 841, 47, 25]),
    ("任务", [632, 949, 46, 25]),
    ("菜单", [636, 1248, 45, 25]),
]

MAIN_FRAMES = [
    {
        "name": "主城·16448（V2324HA 横幅被误读成「地狱级」）",
        "device": "127.0.0.1:16448",
        "items": MAIN_16448_ITEMS,
        "misread": {"地狱级"},
    },
    {
        "name": "主城·16384（CET-AL00 主城被误读成「地狱级」/「超级」）",
        "device": "127.0.0.1:16384",
        "items": MAIN_16384_ITEMS,
        "misread": {"地狱级", "超级"},
    },
]

#: 声明难度（与 #39 回归日志同一档）：主城帧上它既不在误读集里，也不该被拿来判缺席。
DECLARED = "中级"


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


def _load_pipeline(path: Path | None = None) -> dict:
    """读 special_dungeon.json（剥掉 // 行注释，与 hooks_35 同一做法）。"""
    p = path or PIPELINE
    text = p.read_text(encoding="utf-8")
    stripped = "\n".join(
        line.split("//", 1)[0] if line.lstrip().startswith("//") else line
        for line in text.splitlines()
    )
    return json.loads(stripped)


def _pipeline_detail_gate_marker(path: Path | None = None) -> list:
    """pipeline ``SpecialDetailGate`` 的 OCR 判据（expected 列表）。"""
    data = _load_pipeline(path)
    node = data.get("SpecialDetailGate") or {}
    param = (node.get("recognition") or {}).get("param") or {}
    return list(param.get("expected") or [])


def _entry_next(data: dict) -> list:
    return list((data.get("SpecialEntry") or {}).get("next") or [])


# ---------------------------------------------------------------------------
# 桩：回放内嵌真机 OCR（不碰设备）
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self, items=None):
        self._items = items

    def run_recognition(self, entry, image):
        items = self._items(entry) if callable(self._items) else self._items
        rows = [types.SimpleNamespace(box=list(b), text=t) for t, b in (items or [])]
        return types.SimpleNamespace(all_results=rows, hit=bool(rows))

    def run_action(self, *a, **k):  # pragma: no cover - 本守卫不触发动作
        return True


class _Argv:
    def __init__(self, image, param):
        self.image = image
        self.custom_recognition_param = json.dumps(param, ensure_ascii=False)


def _writes_skip_note(si, items) -> bool:
    """在主城帧上跑 SpecialFightTargetRow（批量 override 的中级$ 参数）看它是否写下跳过交接。"""
    si.reset_detail_difficulty()
    rec = si.SpecialTargetFightRecognition()
    res = rec.analyze(_Ctx(items), _Argv(items, {"difficulty": "中级$", "pair": "below"}))
    note = si._take_detail_difficulty()
    if note is None:
        return False
    return note.outcome in ("absent", "undetermined")


def _failures(si=None, agent_dir: Path | None = None, pipeline: Path | None = None) -> list[str]:
    """#41 全部离线断言；返回失败信息列表（空 = 绿）。"""
    _scene_on_path()
    si = si or _import_side_impl(agent_dir)
    from batch_plan import DIFF_REGEX  # noqa: PLC0415

    msgs: list[str] = []
    mid = DIFF_REGEX[DECLARED]

    # (1) 真机主城帧：不得判成详情页，不得判 absent（假跳过）。
    for frame in MAIN_FRAMES:
        if si.on_detail_page(frame["items"]):
            msgs.append(f"「{frame['name']}」被判为【详情页】（#39 过松判据回归）")
        out = si.classify_detail_difficulty(frame["items"], mid)
        if out.outcome != "not_applicable":
            msgs.append(
                f"「{frame['name']}」声明难度 {DECLARED} → {out.outcome}"
                f"（应 not_applicable；absent 会在导航前假跳过该成员）"
            )
        # (2) 该帧确实含被误读的难度词（破坏实验的依据）。
        found = set(si.discover_difficulties(frame["items"]))
        want = set(frame["misread"])
        if not (want & found):
            msgs.append(
                f"「{frame['name']}」未读到任何预期误读难度词 {sorted(want)}"
                f"（实读 {sorted(found)}；破坏实验失去依据）"
            )

    # (5) 主城帧上跑真正的 SpecialFightTargetRow：不得写下跳过交接。
    for frame in MAIN_FRAMES:
        if _writes_skip_note(si, frame["items"]):
            msgs.append(
                f"「{frame['name']}」上 SpecialFightTargetRow 写下了跳过交接"
                f"（主城帧绝不能产生跳过决定）"
            )

    # (4) 标记同源：side_impl == pipeline SpecialDetailGate == scene.page_rules「详情页」。
    try:
        gate = _pipeline_detail_gate_marker(pipeline)
    except Exception as exc:  # noqa: BLE001
        gate = None
        msgs.append(f"读取 special_dungeon.json::SpecialDetailGate 失败：{exc}")
    if gate is not None and gate != [si._DETAIL_PAGE_MARKER]:
        msgs.append(
            f"详情页标记不同源：side_impl._DETAIL_PAGE_MARKER={si._DETAIL_PAGE_MARKER!r} "
            f"!= pipeline SpecialDetailGate.expected={gate}"
        )
    try:
        from scene.page_rules import page_rule  # noqa: PLC0415

        rule = page_rule("详情页")
        expected = ((rule.recognition or {}).get("param") or {}).get("expected")
        if list(expected or []) != [si._DETAIL_PAGE_MARKER]:
            msgs.append(
                f"scene.page_rules「详情页」判据 {expected} != 详情页标记 "
                f"{si._DETAIL_PAGE_MARKER!r}（页面判据应全局唯一）"
            )
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"读取 scene.page_rules「详情页」失败：{exc}")

    # (3) #39 的真行为仍成立：真机详情页帧上 present / absent 判定不变。
    try:
        from contract_hooks import hooks_39  # noqa: PLC0415

        early = hooks_39.EARLY_ITEMS
        cleared = hooks_39.CLEARED_ITEMS
        if si.classify_detail_difficulty(early, DIFF_REGEX["超级"]).outcome != "absent":
            msgs.append("早期账号详情页：声明「超级」应仍为 absent（真跳过不得被抹掉）")
        if si.classify_detail_difficulty(early, mid).outcome != "present":
            msgs.append("早期账号详情页：声明「中级」应为 present（真机该档存在）")
        if si.classify_detail_difficulty(cleared, DIFF_REGEX["超级"]).outcome != "present":
            msgs.append("清关账号详情页：声明「超级」应为 present")
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"复用 #39 详情页帧失败：{exc}")

    # (6) 排位事实：本守卫的前提（SpecialFightTargetRow 早于 SpecialOpenLord）。
    try:
        nxt = _entry_next(_load_pipeline(pipeline))
        if "SpecialFightTargetRow" not in nxt or "SpecialOpenLord" not in nxt:
            msgs.append("SpecialEntry.next 缺少 SpecialFightTargetRow / SpecialOpenLord（前提变化）")
        elif nxt.index("SpecialFightTargetRow") >= nxt.index("SpecialOpenLord"):
            msgs.append(
                "SpecialFightTargetRow 不再排在 SpecialOpenLord 之前 —— 本守卫的门控理由需复核"
            )
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"读取 SpecialEntry.next 失败：{exc}")

    return msgs


def probe_difficulty_gate_requires_real_detail_marker() -> bool:
    """#41：详情页判据只认「推荐编成」；主城帧（含误读难度词）永不假跳过。"""
    return _failures() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools\\contract_hooks\\hooks_41.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_loose_gate(agent_dir: Path) -> None:
    """破坏：把 on_detail_page 退回 #39 的过松判据（出现过难度词就算在详情页）。"""
    old = '    return any(re.search(_DETAIL_PAGE_MARKER, t or "") for t, _b in items)'
    new = (
        "    return bool(discover_difficulties(items)) or any(\n"
        '        re.search(_DETAIL_PAGE_MARKER, t or "") for t, _b in items\n'
        "    )"
    )
    _sub(agent_dir / "side_impl.py", old, new)


def _probe_in(agent_copy: Path):
    """子进程里、以 ``agent_copy`` 作为 side_impl 来源跑本挂点探针。返回 True/False/None。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(agent_copy)!r})\n"
        f"sys.path.insert(1, {str(REPO_ROOT)!r})\n"
        f"sys.path.insert(2, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import hooks_41\n"
        f"print('PROBE_RESULT', repr(hooks_41._failures(agent_dir={str(agent_copy)!r}) == []))\n"
    )
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral41_"))
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
    """真实绿；把 on_detail_page 退回 #39 的过松判据 -> 主城帧被判 absent -> 守卫变红。"""
    print("hooks_41 prove-red：把 on_detail_page 退回 #39 过松判据（难度词就算详情页），"
          "要求 difficulty-gate-requires-real-detail-marker 变红")
    green = probe_difficulty_gate_requires_real_detail_marker() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：主城帧 not_applicable（绿）")
    if not green:
        return False

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook41_"))
    try:
        shutil.copytree(AGENT_DIR, tmp / "agent")
        _break_loose_gate(tmp / "agent")
        red = _probe_in(tmp / "agent") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [{'PASS' if red else 'FAIL'}] 退回松散判据 -> 探针变红（主城帧被假判 absent）")
    ok = green and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#41",
        "详情页判据只认「推荐编成」标记（与 pipeline SpecialDetailGate 同源）；"
        "主城帧（含被误读的地狱级/超级）判 not_applicable、绝不假跳过成员",
        probe_difficulty_gate_requires_real_detail_marker,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
