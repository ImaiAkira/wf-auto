# -*- coding: utf-8 -*-
"""离线单测（#46）：GAMEOVER 页不被 ``SpecialBattleWait`` 抢帧 —— #38 的恢复路径真正可达。

不需要游戏 / 设备；默认连 maa 运行时都不需要（判据在**内嵌的真机帧 OCR** 上求值）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_gameover_match.py

覆盖 #46 的验收：

  1. **失败页 vs 真战斗页（真机帧/合成帧，逐条内嵌 OCR）**：
     * GAMEOVER /「是否续关？」页底部【仍带】战斗 HUD「时间/分数」（复现缺陷的前提）；
     * ``SpecialBattleWait`` 的 HUD 判据在该页仍命中，但 **分派求值器的命中者不是它**；
     * GiveUp/GiveUpFallback 的 ``max_hit`` 用尽（#46 真机卡死点）后由 ``SpecialGameOverHold``
       接住，仍不是 ``SpecialBattleWait``；
     * 真正的战斗 HUD 帧上，命中者**仍是** ``SpecialBattleWait``（判别器不漏真正的战斗）。
  2. **失败画面可达（判别器）**：真机放弃确认框帧上，全局打断 ``[JumpBack]PubLevelUpContinue``
     **不再命中**（``PubLevelUpText`` 的「经验值」叶带负向前瞻），``PubGameOverConfirm``
     （读『OK』）**可达**。
  3. **#38 分支真正可执行**：复用 ``hooks_38.e2e_failures`` —— 失败目标被放弃、清单继续；
     连续 2 次 → ``SpecialBatchStop``。
  4. **守卫接线**：``SpecialGameOverHold`` 排在 ``SpecialBattleWait`` 之前、只认 GAMEOVER 页锚点、
     DoNothing、全 pipeline 绝不点【续关】坐标。
     ★#72 指针★：五重决战改为点【续关】（识别框中心点击 ``PubGameOverContinue``，见 hooks_72）——
     本文件仍断言全 pipeline **绝不写死续关坐标**（固定坐标那条不变量不变）。
  5. **纯编辑 + 无漂移**：``special_dungeon.json`` 五条承重短语仍各 ≥1；``drift.check_all() == []``；
     ``hooks_46.prove_red()`` 成立。
  6. **真机帧实证（best-effort）**：对随仓帧真跑一次 MAA OCR（缺 maa / OCR 模型则 SKIP）。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_46.py``。
如实交代：本文件是**离线**部分；真机 leg（制造/等待一次战斗失败）见 issue #46 评论。

★#46 调查：失败帧上的敌人名「不死王」★
真机帧 f_D_020_082139.png（维·索拉斯讨伐/超级 打输）上敌人名读作「不死王」。判定为
**关内加入（in-stage add）/ 该关敌人本身就叫「不死王」**，**不是打错了关**：同一次运行里
详情页身份校验（logs/D.log 第 61 行）对「维·索拉斯讨伐」判定 ``match``（标题『维·索拉斯』
相似度 1.0）后才点【战斗】；批量清单里另有一行独立的「不死王瑞西塔尔讨伐」（另一张图）。
既有日志/帧不足以 100% 排除「该关的多波敌人里出现名为不死王的敌人」这种更细的情形，
故按证据给出「关内加入」的结论并在报告里点名不确定处。
"""

from __future__ import annotations

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
import hooks_46  # noqa: E402

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
# 1. 失败页 vs 真战斗页
# ---------------------------------------------------------------------------
def test_failure_vs_battle() -> None:
    print("\n== 1. 失败页 vs 真战斗页：SpecialBattleWait 不得在 GAMEOVER 页命中 ==")
    import side_impl as si

    files = hooks_46._files()
    sd = files["special_dungeon.json"]
    entry = sd["SpecialEntry"]["next"]

    check("失败帧确实带战斗 HUD「时间/分数」（复现缺陷的前提）",
          si.is_battle_hud(hooks_46.FAILURE_ITEMS) is True)
    check("失败帧：battle_wait_should_hold = False（不得当战斗中）",
          si.battle_wait_should_hold(hooks_46.FAILURE_ITEMS) is False)
    check("真战斗帧：battle_wait_should_hold = True",
          si.battle_wait_should_hold(hooks_46.BATTLE_ITEMS) is True)

    # SpecialBattleWait 的 HUD 判据在失败帧上【仍会】命中（缺陷存在的前提）。
    sbw_rec = sd["SpecialBattleWait"].get("recognition")
    check("失败帧上 SpecialBattleWait 的 HUD 判据仍命中（缺陷存在的前提）",
          hooks_46.eval_recognition(sbw_rec, hooks_46.FAILURE_ITEMS, hooks_46._resolver(files)) is True)

    fresh = hooks_46.winner(entry, hooks_46.FAILURE_ITEMS, files)
    check("GAMEOVER 页：分派命中者不是 SpecialBattleWait",
          fresh != "SpecialBattleWait", f"winner={fresh!r}")
    check("GAMEOVER 页：由 GAMEOVER 节点接住（GiveUp）",
          isinstance(fresh, str) and "GameOver" in fresh, f"winner={fresh!r}")

    exhausted = {"PubGameOverGiveUp", "PubGameOverGiveUpFallback"}
    after = hooks_46.winner(entry, hooks_46.FAILURE_ITEMS, files, exhausted=exhausted)
    check("GiveUp/Fallback max_hit 用尽后仍不是 SpecialBattleWait",
          after != "SpecialBattleWait", f"winner={after!r}")
    check("用尽后由 SpecialGameOverHold 接住",
          after == "SpecialGameOverHold", f"winner={after!r}")

    battle = hooks_46.winner(entry, hooks_46.BATTLE_ITEMS, files)
    check("真战斗帧：命中者仍是 SpecialBattleWait（判别器不漏真正的战斗）",
          battle == "SpecialBattleWait", f"winner={battle!r}")


# ---------------------------------------------------------------------------
# 2. 失败画面可达（判别器）
# ---------------------------------------------------------------------------
def test_confirm_reachable() -> None:
    print("\n== 2. 放弃确认框可达（PubLevelUpContinue 不再抢占） ==")
    files = hooks_46._files()
    common = files["common.json"]
    lvl_rec = common["PubLevelUpText"].get("recognition")

    check("PubLevelUpText 不命中确认框「道具、RP、经验值、玛纳。」",
          hooks_46.eval_recognition(lvl_rec, hooks_46.CONFIRM_ITEMS, hooks_46._resolver(files)) is False)
    check("PubLevelUpText 仍命中真升级页「等级最大！」",
          hooks_46.eval_recognition(
              lvl_rec, [("等级最大！", [51, 774, 113, 34])], hooks_46._resolver(files)) is True)
    check("PubLevelUpText 仍命中「获得经验值 1200」（非清单项）",
          hooks_46.eval_recognition(
              lvl_rec, [("获得经验值 1200", [200, 800, 300, 30])], hooks_46._resolver(files)) is True)
    check("确认框帧上 [JumpBack]PubLevelUpContinue 不再命中",
          hooks_46.candidate_hit("[JumpBack]PubLevelUpContinue", hooks_46.CONFIRM_ITEMS, files) is False)
    check("确认框帧上 PubGameOverConfirm（读 OK）可达",
          hooks_46.winner(files["special_dungeon.json"]["SpecialEntry"]["next"],
                          hooks_46.CONFIRM_ITEMS, files) == "PubGameOverConfirm")


# ---------------------------------------------------------------------------
# 3. #38 分支真正可执行（失败目标被放弃、清单继续；连续 2 次收工）
# ---------------------------------------------------------------------------
def test_38_branch_runs() -> None:
    print("\n== 3. #38 分支真正可执行（放弃→记账→继续 / 连续 2 次收工） ==")
    fails = hooks_38.e2e_failures()
    for msg in fails:
        check(msg, False)
    if not fails:
        check("失败目标被放弃、清单继续；连续 2 次 → SpecialBatchStop；胜利用清零", True)


# ---------------------------------------------------------------------------
# 4. 守卫接线
# ---------------------------------------------------------------------------
def test_guard_wired() -> None:
    print("\n== 4. SpecialGameOverHold 守卫接线 ==")
    fails = hooks_46._hold_guard_failures()
    for msg in fails:
        check(msg, False)
    if not fails:
        check("SpecialGameOverHold 在 SpecialBattleWait 之前 / DoNothing / 绝不点续关", True)


# ---------------------------------------------------------------------------
# 5. 纯编辑 + 无漂移 + prove-red
# ---------------------------------------------------------------------------
def test_pure_edit_and_drift() -> None:
    print("\n== 5. 纯编辑：承重短语仍在 + drift 为空 ==")
    text = SD.read_text(encoding="utf-8")
    for phrase in PHRASES:
        check(f"短语「{phrase}」仍出现", text.count(phrase) >= 1, f"count={text.count(phrase)}")
    try:
        from scene import drift

        msgs = drift.check_all(repo_root=REPO_ROOT)
        check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    except Exception as exc:  # noqa: BLE001
        check("drift.check_all 可运行", False, f"raised {exc!r}")


def test_prove_red() -> None:
    print("\n== 6. hooks_46.prove_red() 成立 ==")
    check("hooks_46.prove_red()（两处破坏各自变红）", hooks_46.prove_red() is True)


# ---------------------------------------------------------------------------
# 7. 真机帧实证（best-effort）
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
    print("\n== 7. 真机帧实证（best-effort）：真跑 MAA OCR ==")
    import side_impl as si

    items = _maa_ocr(REPO_ROOT / "tools/frames/gameover_prompt.png")
    if items is None:
        skip("真机帧 OCR（GAMEOVER 页）", "缺 maa / OCR 模型 det.onnx / 帧")
    else:
        check("GAMEOVER 真机帧：classify_gameover = giveup",
              si.classify_gameover(items) == "giveup")
        check("GAMEOVER 真机帧：battle_wait_should_hold = False",
              si.battle_wait_should_hold(items) is False)

    bitems = _maa_ocr(REPO_ROOT / "tools/frames/lord_battle_hud.png")
    if bitems is None:
        skip("真机帧 OCR（战斗 HUD）", "缺 maa / OCR 模型 det.onnx / 帧")
    else:
        check("真战斗 HUD 真机帧：battle_wait_should_hold = True",
              si.battle_wait_should_hold(bitems) is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 74)
    print("#46：GAMEOVER 页不被 SpecialBattleWait 抢帧 —— #38 的恢复路径真正可达（离线测试）")
    print("=" * 74)
    test_failure_vs_battle()
    test_confirm_reachable()
    test_38_branch_runs()
    test_guard_wired()
    test_pure_edit_and_drift()
    test_prove_red()
    test_real_frames_best_effort()
    print("\n" + "=" * 74)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
