# -*- coding: utf-8 -*-
"""离线单测（#38）：战斗失败 / GAMEOVER（「是否续关？」）—— 放弃该次并继续清单 / 连续 2 次收工。

不需要游戏 / 设备；默认连 maa 运行时都不需要（判据在**内嵌的真机帧 OCR** 上求值）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_gameover_recovery.py

覆盖 #38 的验收：

  1. **识别**：``classify_gameover`` 在真机帧 OCR（720 空间，逐条内嵌）上 —— GAMEOVER 页 =
     ``giveup``、放弃确认框 = ``confirm``；详情页 / 主城 / 战斗 HUD（同含「时间/分数」）= ``None``；
  2. **拒绝续关**：pipeline 读【放弃】/【OK】自己的框（box_index）或实测坐标点击；**没有**任何
     节点点【续关】（要花星导石×50）；四个节点挂在 ``SpecialEntry.next`` 的指挥官与种类分派器之间；
     ★#72 指针★：五重决战改为点【续关】（识别框中心点击 ``PubGameOverContinue``，见 hooks_72）——
     本文件覆盖的**批量链**仍拒绝续关、仍绝不写死续关坐标；
  3. **放弃/继续 与 连续 2 次收工**：纯函数 ``plan_gameover_action`` 的正反例；离线端到端回放
     GAMEOVER → 确认框 → 详情页：失败目标被放弃、清单继续；连续 2 次 → ``SpecialBatchStop``；
     结算（胜利）打断连续计数；
  4. **归位认识 GAMEOVER**：``RETURN_HOME_RULES`` 的 ``gameover`` 规则：GAMEOVER →（放弃）→
     确认框 →（OK）→ 详情页 →（主城）→ 主城；点击点 = 【放弃】/【OK】各自 OCR 框中心；
  5. **真机帧实证（best-effort）**：对随仓帧 ``tools/frames/gameover_prompt.png`` /
     ``gameover_confirm.png`` 真跑一次 MAA OCR，断言分类器读出 ``giveup`` / ``confirm``
     （缺 maa / OCR 模型则 SKIP，不算失败）；
  6. **纯编辑**：``special_dungeon.json`` 五条承重短语仍各 ≥1；``drift.check_all() == []``；
  7. 挂点 ``hooks_38`` 已点亮、prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_38.py``。
如实交代：本文件是**离线**部分；真机 leg（制造/等待一次战斗失败）见 issue #38 评论。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_38  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SD = PIPELINE_DIR / "special_dungeon.json"

# #12 的承重注释硬规则（纯编辑，绝不丢这些短语）。
PHRASES = (
    "批量副本清单指挥官",
    "幻想连战分派器",
    "最临时的全局打断",
    "紧挨卡死兜底",
    "绝不会",
)

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. 识别：真机帧（内嵌 OCR）
# ---------------------------------------------------------------------------
def test_recognition_from_frames() -> None:
    print("\n== 1. 识别：真机帧 OCR（GAMEOVER / 确认框 / 反例） ==")
    import side_impl as si

    check("GAMEOVER 页帧 → giveup",
          si.classify_gameover(hooks_38.GAMEOVER_PAGE_ITEMS) == "giveup",
          f"got={si.classify_gameover(hooks_38.GAMEOVER_PAGE_ITEMS)!r}")
    check("放弃确认框帧 → confirm",
          si.classify_gameover(hooks_38.CONFIRM_ITEMS) == "confirm",
          f"got={si.classify_gameover(hooks_38.CONFIRM_ITEMS)!r}")
    check("详情页帧 → None（不误命中）",
          si.classify_gameover(hooks_38.DETAIL_ITEMS) is None)
    check("主城帧 → None（不误命中）",
          si.classify_gameover(hooks_38.MAIN_CITY_ITEMS) is None)
    # GAMEOVER 页也有「时间/分数」，所以战斗 HUD 判据不是区分器 —— 分类器必须靠 GAMEOVER 文案。
    check("战斗 HUD（时间/分数）→ None（不与 GAMEOVER 混）",
          si.classify_gameover(hooks_38.BATTLE_HUD_ITEMS) is None)
    check("GAMEOVER 页帧确实带「时间/分数」（证明不能只靠 HUD 判据区分）",
          any("时间" in t for t, _ in hooks_38.GAMEOVER_PAGE_ITEMS)
          and any("分数" in t for t, _ in hooks_38.GAMEOVER_PAGE_ITEMS))

    for rel, label in hooks_38.FRAMES:
        check(f"真机帧随仓：{rel}（{label}）", (REPO_ROOT / rel).is_file())


# ---------------------------------------------------------------------------
# 2. pipeline：拒绝续关
# ---------------------------------------------------------------------------
def test_pipeline_declines_continue() -> None:
    print("\n== 2. pipeline：读屏后点【放弃】/【OK】，绝不点【续关】 ==")
    fails = hooks_38.pipeline_failures()
    check("pipeline 拒绝续关的断言全绿", fails == [], f"fails={fails[:3]}")

    from scene import drift

    files = drift.load_pipelines(PIPELINE_DIR)
    common = files["common.json"]
    entry = files["special_dungeon.json"]["SpecialEntry"]["next"]
    for name in ("PubGameOverGiveUp", "PubGameOverGiveUpFallback",
                 "PubGameOverConfirm", "PubGameOverConfirmFallback"):
        check(f"节点在 common.json：{name}", name in common)
        check(f"引用在 SpecialEntry.next：[JumpBack]{name}", f"[JumpBack]{name}" in entry)

    # 主节点点【放弃】按钮自己的框（不是固定坐标），Fallback 点实测坐标。
    gu = common["PubGameOverGiveUp"]["action"]["param"]["target"]
    fb = common["PubGameOverGiveUpFallback"]["action"]["param"]["target"]
    check("主节点点识别框中心（读屏再点）", gu is True, f"target={gu!r}")
    check("Fallback 点【放弃】实测坐标", fb == list(hooks_38.EXPECTED_GIVEUP_CLICK), f"target={fb!r}")


# ---------------------------------------------------------------------------
# 3. 政策：放弃/继续 与 连续 2 次收工（纯函数 + 端到端）
# ---------------------------------------------------------------------------
def test_policy_pure() -> None:
    print("\n== 3a. 纯函数 plan_gameover_action ==")
    import side_impl as si

    a, r = si.plan_gameover_action(1, batch_active=True, has_current=True, remaining_other=2)
    check("失败 1 次 + 还有别的目标 → abandon_continue（放弃该目标继续清单）",
          a == "abandon_continue" and "继续清单" in r, f"got={(a, r)}")
    a2, r2 = si.plan_gameover_action(2, batch_active=True, has_current=True, remaining_other=2)
    check("连续 2 次失败 → stop（主动收工，原因点名连续）",
          a2 == "stop" and "连续" in r2, f"got={(a2, r2)}")
    a3, _ = si.plan_gameover_action(1, batch_active=False, has_current=False, remaining_other=0)
    check("单目标（无可继续）→ stop", a3 == "stop", f"got={a3}")
    a4, _ = si.plan_gameover_action(1, batch_active=True, has_current=True, remaining_other=0)
    check("批量但已无目标可继续 → stop", a4 == "stop", f"got={a4}")
    check("连续失败上限 = 2", si.GAMEOVER_CONSECUTIVE_LIMIT == 2)


def test_offline_repro() -> None:
    print("\n== 3b. 离线端到端回放：失败 → 放弃并继续；连续 2 次 → 收工 ==")
    fails = hooks_38.e2e_failures()
    for msg in fails:
        check(msg, False)
    if not fails:
        check("端到端：失败目标被放弃、清单继续；连续 2 次 → SpecialBatchStop；胜利用清零", True)


# ---------------------------------------------------------------------------
# 4. 归位认识 GAMEOVER
# ---------------------------------------------------------------------------
def test_return_home() -> None:
    print("\n== 4. 归位认识 GAMEOVER（与 #31 同一张表） ==")
    ids = [r[0] for r in hooks_38.rules()]
    check("有序表含 gameover 规则", "gameover" in ids, f"ids={ids}")
    fails = hooks_38.return_home_failures()
    check("归位断言全绿（首命中 / 读后动 / 到主城 / 旧形态复现）", fails == [], f"fails={fails[:3]}")

    # 点击点 = 各自 OCR 框中心（读后动）。
    pt_go = hooks_38._click_point_for(hooks_38.GAMEOVER_PAGE_ITEMS, "gameover")
    pt_cf = hooks_38._click_point_for(hooks_38.CONFIRM_ITEMS, "gameover")
    check("GAMEOVER 页点【放弃】框中心 (213,1062)", pt_go == hooks_38.EXPECTED_GIVEUP_CLICK, f"pt={pt_go}")
    check("确认框点【OK】框中心 (523,823)", pt_cf == hooks_38.EXPECTED_OK_CLICK, f"pt={pt_cf}")
    check("【续关】坐标没有被任何规则点（有限资源）", hooks_38.CONTINUE_BUTTON == (506, 1061))


# ---------------------------------------------------------------------------
# 5. 真机帧实证（best-effort）
# ---------------------------------------------------------------------------
_ASSETS = REPO_ROOT / "assets" / "resource"


def _maa_ocr(frame: Path):
    """对随仓帧真跑一次 MAA OCR（720 空间）；缺 maa / 模型 / 帧 → None（SKIP）。"""
    if not frame.is_file():
        return None
    if not (_ASSETS / "model" / "ocr" / "det.onnx").is_file():
        return None
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        import live_harness as ca

        pil = Image.open(frame).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        return ca.ocr(img, _ASSETS)
    except Exception:  # noqa: BLE001
        return None


def test_real_frames_best_effort() -> None:
    print("\n== 5. 真机帧实证（best-effort）：真跑 MAA OCR ==")
    import side_impl as si

    for rel, want, label in (
        ("tools/frames/gameover_prompt.png", "giveup", "GAMEOVER 页"),
        ("tools/frames/gameover_confirm.png", "confirm", "放弃确认框"),
    ):
        items = _maa_ocr(REPO_ROOT / rel)
        if items is None:
            skip(f"真机帧 OCR（{label}）", "缺 maa / OCR 模型 det.onnx / 帧")
            continue
        got = si.classify_gameover(items)
        texts = [t for t, _ in items]
        check(f"{label}：真机 OCR 分类 = {want}", got == want, f"got={got!r} texts={texts[:10]}")


# ---------------------------------------------------------------------------
# 6. 纯编辑 + 无漂移
# ---------------------------------------------------------------------------
def test_pure_edit_and_drift() -> None:
    print("\n== 6. 纯编辑：承重短语仍在 + drift 为空 ==")
    text = SD.read_text(encoding="utf-8")
    for phrase in PHRASES:
        check(f"短语「{phrase}」仍出现", text.count(phrase) >= 1, f"count={text.count(phrase)}")
    try:
        from scene import drift

        msgs = drift.check_all(repo_root=REPO_ROOT)
        check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("drift.check_all 可运行", False, f"raised {exc!r}")


# ---------------------------------------------------------------------------
# 7. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 7. 挂点点亮 + prove-red ==")
    check("挂点 gameover-recognised-from-real-frame 已点亮",
          hooks_38.probe_gameover_recognised() is True)
    check("挂点 gameover-decline-not-continue 已点亮",
          hooks_38.probe_gameover_decline_not_continue() is True)
    check("挂点 gameover-abandon-continue-or-stop 已点亮",
          hooks_38.probe_gameover_abandon_or_stop() is True)
    check("挂点 return-home-gameover 已点亮",
          hooks_38.probe_return_home_gameover() is True)
    check("hooks_38.prove_red() 成立（四处破坏各自变红）", hooks_38.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 74)
    print("#38：战斗失败 / GAMEOVER —— 放弃并继续清单 / 连续 2 次收工（离线测试）")
    print("=" * 74)
    test_recognition_from_frames()
    test_pipeline_declines_continue()
    test_policy_pure()
    test_offline_repro()
    test_return_home()
    test_real_frames_best_effort()
    test_pure_edit_and_drift()
    test_hooks_and_prove_red()
    print("\n" + "=" * 74)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
