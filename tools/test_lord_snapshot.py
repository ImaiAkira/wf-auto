# -*- coding: utf-8 -*-
"""离线单测：#111 账号快照降级 + 「自动」兄弟窗口（纯单测，不碰设备、不写盘）。

跑：

    .venv\\Scripts\\python.exe tools\\test_lord_snapshot.py

覆盖两张票落地的两件事：

**A. 「支持难度集」被证伪 → 降级成「账号快照」**
  1. ``scene/lord_battle.py`` 的逐成员难度只存在于 ``ACCOUNT_SNAPSHOTS``，且**三要素齐全**
     （账号 / 时间 / 帧；仓外产物写成 ``artifact:``）；
  2. #106 的**证伪回归钉**：艾基尔·嫉妒 ``1/4``、背鳍三兄弟 ``1/4``、八岐大蛇 ``4/4``、
     无猾机兵 ``5/5`` —— 快照档数**都小于** M（旧表就是把可见档数当成了 M）；
  3. ``hooks_32.ACCOUNT_SNAPSHOTS``（旧名 ``DEVICE_DIFFICULTIES`` 仍是它的别名）与
     ``scene/lords.py`` **不冲突**：成员在花名册 / 档 ∈ 词表 / ``len(快照) <= M`` / ``快照 ⊆ 链``；
  4. ``scene.drift.lords_snapshot_drift() == []`` 且 ``drift.check_all() == []``；
  5. ``GLOSSARY.md`` 把「支持难度集」写成**被证伪的概念**、事实源指向 ``scene/lords.py``。

**B. 「自动」的兄弟窗口 = 实测滑窗尖峰**
  6. ``hooks_auto_outside.CONT_BOX_720`` == ``(17,1062)``（实测尖峰），``AUTO_BOX_720`` == ``(142,1062)``；
  7. 滑窗复算：兄弟尖峰 ≈0.8964（既是尖峰、**也过阈值** 0.75），偏 1px 只剩 ≈0.4536；
  8. 真源 ``AUTO_LABEL_ROI`` 排除兄弟尖峰、覆盖真「自动」；
  9. ``hooks_auto_outside.probe_auto_switch_template_distinct()`` 绿，且它对**偏 1px 的窗口**红
     （点测会骗人 ⇒ 这条是「碰巧绿」的判别式）。

**C. 守卫**
 10. ``hooks_111`` 两个挂点探针为 True，且各自 prove-red 成立（7 条破坏实验）。

诚实边界：本文件**不**判断「某账号现在能打哪几档」——那是账号状态，真机以列表页
``通关数 N/M`` / 详情页 ``NEW``/``首次报酬``/``COMPLETE!!`` 为准。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402
from scene.config import DIFFICULTIES  # noqa: E402
from scene.lord_battle import (  # noqa: E402
    ACCOUNT_SNAPSHOT_ACCOUNT,
    ACCOUNT_SNAPSHOT_CAPTURED_AT,
    ACCOUNT_SNAPSHOT_FRAMES,
    ACCOUNT_SNAPSHOTS,
    LORD_BATTLE,
)
from scene.lords import BY_ROW_NAME  # noqa: E402

import hooks_32  # noqa: E402
import hooks_108  # noqa: E402
import hooks_111  # noqa: E402

FAILS: list[str] = []

#: #106 的**证伪现场**：列表页同一帧实读的 ``通关数 N/M`` 的分母 = M；
#: 旧静态表记的档数（= 某账号那一刻可见的档）= ``tier``。（来源：调研 §2.4 + 两张列表页帧）
FALSIFIED: dict[str, tuple[int, int]] = {
    "艾基尔·嫉妒讨伐": (1, 4),
    "背鳍三兄弟讨伐": (2, 4),
    "八岐大蛇讨伐": (3, 4),
    "无猾机兵": (4, 5),   # ★旧表记 4，实测 M=5★
}


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _auto():
    return importlib.import_module("scene.auto_switch")


# ---------------------------------------------------------------------------
# A. 账号快照
# ---------------------------------------------------------------------------
def test_snapshot_provenance() -> None:
    print("\n== A1. 快照三要素（账号 / 时间 / 帧） ==")
    check("ACCOUNT_SNAPSHOT_ACCOUNT 非空", bool(ACCOUNT_SNAPSHOT_ACCOUNT.strip()), ACCOUNT_SNAPSHOT_ACCOUNT)
    check("ACCOUNT_SNAPSHOT_CAPTURED_AT 非空", bool(ACCOUNT_SNAPSHOT_CAPTURED_AT.strip()),
          ACCOUNT_SNAPSHOT_CAPTURED_AT)
    check("ACCOUNT_SNAPSHOT_FRAMES 非空", bool(ACCOUNT_SNAPSHOT_FRAMES), f"共 {len(ACCOUNT_SNAPSHOT_FRAMES)} 项")
    missing = [
        frame for frame in ACCOUNT_SNAPSHOT_FRAMES
        if not frame.startswith(hooks_111.ARTIFACT_PREFIX) and not (REPO_ROOT / frame).is_file()
    ]
    check("仓内帧都真实存在（仓外产物用 artifact: 前缀）", missing == [], f"缺={missing}")
    artifacts = [f for f in ACCOUNT_SNAPSHOT_FRAMES if f.startswith(hooks_111.ARTIFACT_PREFIX)]
    check("仓外产物明确标成 artifact:（不假装它还在仓里）", len(artifacts) >= 1, f"{artifacts}")

    print(f"\n  快照覆盖 {len(ACCOUNT_SNAPSHOTS)} 个成员 / 花名册 {len(LORD_BATTLE.members)} 个：")
    for row_name in sorted(ACCOUNT_SNAPSHOTS)[:6]:
        entry = BY_ROW_NAME.get(row_name)
        m = "?" if entry is None or entry.max_tiers is None else entry.max_tiers
        print(f"    · {row_name:<16} 快照 {len(ACCOUNT_SNAPSHOTS[row_name])} 档 / M={m}")


def test_falsified_pins() -> None:
    print("\n== A2. #106 证伪回归钉：快照档数 < M（旧表把可见档数当成了 M） ==")
    for row_name, (old_tiers, frame_m) in FALSIFIED.items():
        entry = BY_ROW_NAME.get(row_name)
        check(f"{row_name} 在 scene/lords.py 里有登记", entry is not None)
        if entry is None:
            continue
        check(f"{row_name} 的 M == {frame_m}（列表页 通关数 N/M 的分母）", entry.max_tiers == frame_m,
              f"got={entry.max_tiers}")
        snap = ACCOUNT_SNAPSHOTS.get(row_name)
        check(f"{row_name} 有账号快照", snap is not None)
        if snap is None:
            continue
        check(f"{row_name} 快照 {len(snap)} 档 < M {frame_m}", len(snap) < frame_m, f"{len(snap)} vs {frame_m}")
        check(f"{row_name} 快照档数 == 旧表记的 {old_tiers} 档（同一份观察）", len(snap) == old_tiers,
              f"got={len(snap)}")


def test_snapshot_conflict() -> None:
    print("\n== A3. 快照与 scene/lords.py（唯一事实源）不冲突 ==")
    check("hooks_32 的旧名别名仍指向同一份快照",
          hooks_32.DEVICE_DIFFICULTIES is hooks_32.ACCOUNT_SNAPSHOTS)
    check("hooks_32._snapshot_conflict_failures() 空",
          hooks_32._snapshot_conflict_failures() == [],
          f"{hooks_32._snapshot_conflict_failures()}")
    entries = {entry.row_name: entry for entry in BY_ROW_NAME.values()}
    msgs = hooks_32._snapshot_conflict_failures(
        snapshots=hooks_32.ACCOUNT_SNAPSHOTS, entries=entries, difficulties=DIFFICULTIES)
    check("内嵌夹具（37 个成员）与事实源不冲突", msgs == [], f"{msgs[:2]}")
    check("drift.lords_snapshot_drift() == []", drift.lords_snapshot_drift() == [],
          f"{drift.lords_snapshot_drift()}")
    check("drift.check_all() == []", drift.check_all() == [], f"{drift.check_all()[:3]}")


def test_glossary() -> None:
    print("\n== A4. GLOSSARY.md：概念被证伪 + 事实源指向 scene/lords.py ==")
    text = (REPO_ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    check("写明了「支持难度集」是被证伪的概念", "被证伪的概念" in text)
    check("事实源指向 scene/lords.py 的 M + 解锁链", "scene/lords.py" in text and "解锁链" in text)
    check("不再声称难度数据的唯一来源是 scene/lord_battle.py 的逐成员集合",
          "每个成员支持哪些**难度**" not in text)


# ---------------------------------------------------------------------------
# B. 兄弟窗口
# ---------------------------------------------------------------------------
def test_window_is_measured_spike() -> None:
    print("\n== B1. 兄弟窗口 == 实测滑窗尖峰 ==")
    outer = importlib.import_module("hooks_auto_outside")
    cfg = _auto()
    tpl, rel = hooks_108._template_gray(cfg)
    check("模板裁片可读", tpl is not None, rel)
    if tpl is None:
        return
    thr = float(cfg.AUTO_TEMPLATE_THRESHOLD)
    scores = hooks_108._zncc_map(hooks_108._frame_720(outer.FRAME_LORD_TEAM), tpl)
    peaks = hooks_108._peaks(scores, thr)
    best = hooks_108._select(peaks, "Score", 0)
    left = [c for c in peaks if c[1] < outer.AUTO_BOX_720[0]]
    sibling = hooks_108._select(left, "Score", 0)

    check("真「自动」窗口 == (142,1062)", outer.AUTO_BOX_720[:2] == [142, 1062], f"{outer.AUTO_BOX_720[:2]}")
    check("兄弟窗口 == (17,1062)（实测尖峰，不是 OCR 框的 x=18）",
          outer.CONT_BOX_720[:2] == [17, 1062], f"{outer.CONT_BOX_720[:2]}")
    check("滑窗尖峰就是这两个位置",
          best is not None and (best[1], best[2]) == (142, 1062)
          and sibling is not None and (sibling[1], sibling[2]) == (17, 1062),
          f"best={best} sibling={sibling}")
    if sibling is None:
        return
    z_spike = float(scores[sibling[2], sibling[1]])
    z_off = float(scores[sibling[2], sibling[1] + 1])
    check("兄弟尖峰 ZNCC 在 0.85~0.95（实测 0.8964）", 0.85 <= z_spike <= 0.95, f"{z_spike:.4f}")
    check("偏 1px（x=18）掉到 0.35~0.55（实测 0.4536）", 0.35 <= z_off <= 0.55, f"{z_off:.4f}")
    check("「点测会骗人」的落差 ≥ 0.30", (z_spike - z_off) >= 0.30, f"drop={z_spike - z_off:.4f}")
    check("兄弟尖峰**也过阈值**（模板本身分不开 ⇒ distinctness 必须由 roi 提供）", z_spike >= thr,
          f"{z_spike:.4f} vs thr {thr}")

    roi = tuple(cfg.AUTO_LABEL_ROI)
    check("真源 roi 排除兄弟尖峰", not hooks_108._inside(roi, (17, 1062, tpl.shape[1], tpl.shape[0])),
          f"roi={list(roi)}")
    check("真源 roi 覆盖真「自动」", hooks_108._inside(roi, (142, 1062, tpl.shape[1], tpl.shape[0])),
          f"roi={list(roi)}")
    check("hooks_auto_outside 的模板检查是滑窗口径（绿）",
          outer.probe_auto_switch_template_distinct() is True)
    check("喂偏 1px 的窗口它必须红（点测实现会判绿）",
          len(outer._template_failures(cont_box=[18, 1062, 43, 26])) > 0)


# ---------------------------------------------------------------------------
# C. 守卫
# ---------------------------------------------------------------------------
def test_hooks() -> None:
    print("\n== C. 守卫探针 + 破坏实验 ==")
    check("hooks_111 快照形态探针 True", hooks_111.probe_lord_difficulty_snapshot_only() is True,
          f"{hooks_111._snapshot_only_failures()[:2]}")
    check("hooks_111 兄弟窗口探针 True", hooks_111.probe_auto_sibling_window_is_measured_spike() is True,
          f"{hooks_111._window_failures()[:2]}")
    check("hooks_32 探针 True（快照与真源不冲突）",
          hooks_32.probe_lord_roster_and_difficulties() is True)


def test_prove_red() -> None:
    print("\n== C2. 破坏实验（prove-red） ==")
    check("hooks_111.prove_red()（7 条）", hooks_111.prove_red() is True)
    check("hooks_32.prove_red()（删成员 + 快照超 M）", hooks_32.prove_red() is True)


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 74)
    print("#111 账号快照降级（支持难度集被证伪）+ 「自动」兄弟窗口 = 实测滑窗尖峰")
    print("=" * 74)
    test_snapshot_provenance()
    test_falsified_pins()
    test_snapshot_conflict()
    test_glossary()
    test_window_is_measured_spike()
    test_hooks()
    test_prove_red()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_lord_snapshot: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
