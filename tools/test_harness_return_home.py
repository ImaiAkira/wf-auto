# -*- coding: utf-8 -*-
"""离线单测：归位状态机（#24）—— 账号确认页先「继续游戏」、标题页再「点击开始」。

不需要游戏 / 设备；默认连 maa 运行时都不需要（顺序锁是纯数据 + 合成 OCR 求值）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_harness_return_home.py

覆盖 #24 的验收：

  1. **顺序正确**：``RETURN_HOME_RULES`` 里 account_confirm 排在 title 之前；真机语义的
     合成账号确认页（同时含「继续游戏」与「点击开始」）首个命中就是 account_confirm；
  2. **旧顺序会错**（回归复现）：把顺序颠倒 -> 同一个账号确认页画面会先命中 title
     （点弹窗背后挡住的假「点击开始」）——正是 #13 第 3 次运行归位全败的根因；
  3. **锁在有序表上**：ensure_main_city 按 ``RETURN_HOME_RULES`` 分派，且支持
     「游戏未启动（Android 桌面）」的确定性冷启动；
  4. **真机帧实证（best-effort）**：对 #13 落盘的账号确认页截图跑一次 OCR，断言首个命中
     是 account_confirm（缺 maa / OCR 模型 / 帧则 SKIP，不算失败）；
  5. 挂点 ``hooks_24`` 已点亮、prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_24.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import inspect
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_24  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

# OCR 资源（含 gitignore 的 det.onnx 运行期模型）；裸检出没有则真机帧实证 SKIP。
ASSETS = Path(os.environ.get("WF_H24_ASSETS", str(REPO_ROOT / "assets" / "resource")))
# #13 第 3 次运行、跑失败时抓下的账号确认页（弹窗背后透出「点击开始」）。
FRAME_ACCT = Path(
    os.environ.get(
        "WF_H24_ACCT_FRAME",
        str(TEMP_OPENCODE / "rerun13b/evidence/10_acctconfirm_155418.png"),
    )
)


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. 顺序正确
# ---------------------------------------------------------------------------
def test_order_correct() -> None:
    print("\n== 1. 有序表：账号确认页先于标题页 ==")
    ids = hooks_24.rule_ids()
    print(f"  RETURN_HOME_RULES = {ids}")
    check("有序表含 account_confirm 与 title", {"account_confirm", "title"} <= set(ids))
    check(
        "account_confirm 排在 title 之前",
        ids.index("account_confirm") < ids.index("title"),
        f"acct@{ids.index('account_confirm')} < title@{ids.index('title')}",
    )
    check("order_error 无（判据绑定正确）", hooks_24.order_error(hooks_24.rules()) is None)

    rules = hooks_24.rules()
    pick = hooks_24._first_rule(rules, hooks_24.ACCOUNT_CONFIRM_ITEMS)
    check("账号确认页（含两个框）首个命中 = account_confirm", pick == "account_confirm", f"pick={pick}")
    check(
        "标题页（只有「点击开始」）首个命中 = title",
        hooks_24._first_rule(rules, hooks_24.TITLE_ITEMS) == "title",
    )


# ---------------------------------------------------------------------------
# 2. 旧顺序会错（回归复现）
# ---------------------------------------------------------------------------
def test_old_order_regresses() -> None:
    print("\n== 2. 回归复现：顺序颠倒 -> 账号确认页会先点到假「点击开始」 ==")
    reversed_rules = list(reversed(hooks_24.rules()))
    pick = hooks_24._first_rule(reversed_rules, hooks_24.ACCOUNT_CONFIRM_ITEMS)
    check("颠倒后首个命中变成 title（旧实现的错）", pick == "title", f"pick={pick}")
    check("order_error 在颠倒顺序下变红（守卫能抓到）", hooks_24.order_error(reversed_rules) is not None)


# ---------------------------------------------------------------------------
# 3. 锁在有序表上 + 冷启动分支
# ---------------------------------------------------------------------------
def test_state_machine_wiring() -> None:
    print("\n== 3. ensure_main_city 按有序表分派 + 支持「游戏未启动」冷启动 ==")
    src = inspect.getsource(ca.ensure_main_city)
    check("ensure_main_city 消费 RETURN_HOME_RULES（不是内联 if 链）", "RETURN_HOME_RULES" in src)
    check("ensure_main_city 暴露 start_if_closed 参数（可从桌面冷启动归位）",
          "start_if_closed" in inspect.signature(ca.ensure_main_city).parameters)
    check("harness 有 _game_running / _start_app（确定性冷启动，非盲点）",
          hasattr(ca, "_game_running") and hasattr(ca, "_start_app"))
    check("游戏包名默认与 phantom_restart 一致", ca.PKG == "com.leiting.wf", f"PKG={ca.PKG}")


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort；缺 maa / 模型 / 帧则 SKIP）
# ---------------------------------------------------------------------------
def test_real_frame_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：#13 账号确认页首个命中 = account_confirm ==")
    model = ASSETS / "model" / "ocr" / "det.onnx"
    if not FRAME_ACCT.is_file():
        skip("真机帧 OCR（账号确认页）", f"缺帧：{FRAME_ACCT}")
        return
    if not model.is_file():
        skip("真机帧 OCR（账号确认页）", f"缺 OCR 模型：{model}")
        return
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        skip("真机帧 OCR（账号确认页）", f"缺 numpy/PIL：{exc!r}")
        return
    try:
        pil = Image.open(FRAME_ACCT).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        items = ca.ocr(img, ASSETS)
    except Exception as exc:  # noqa: BLE001
        skip("真机帧 OCR（账号确认页）", f"OCR 不可用：{exc!r}")
        return

    texts = [t for t, _ in items]
    has_continue = any(t == "继续游戏" for t in texts)
    has_start = any(t == "点击开始" for t in texts)
    print(f"  帧 OCR 文本（截断）：{texts[:20]}")
    check("账号确认页帧里 OCR 到「继续游戏」", has_continue)
    # 弹窗背后标题页的「点击开始」通常也在（这正是旧实现会误判的原因）。
    print(f"  （参考）该帧也 OCR 到「点击开始」：{has_start} —— 旧实现会先命中它")
    pick = hooks_24._first_rule(hooks_24.rules(), items)
    check("真机账号确认页帧上首个命中 = account_confirm", pick == "account_confirm", f"pick={pick}")


# ---------------------------------------------------------------------------
# 5. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 5. 挂点点亮 + prove-red ==")
    check(
        "挂点 return-home-account-confirm-before-title 已点亮",
        hooks_24.probe_account_confirm_before_title() is True,
    )
    check(
        "挂点 return-home-state-machine-driven-by-table 已点亮",
        hooks_24.probe_state_machine_driven_by_table() is True,
    )
    check("hooks_24.prove_red() 成立（颠倒顺序 / 丢表各自变红）", hooks_24.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：归位状态机（#24）—— 账号确认页先「继续游戏」、标题页再「点击开始」")
    print("=" * 70)
    test_order_correct()
    test_old_order_regresses()
    test_state_machine_wiring()
    test_real_frame_best_effort()
    test_hooks_and_prove_red()
    print("\n" + "=" * 70)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
