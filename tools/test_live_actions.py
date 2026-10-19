# -*- coding: utf-8 -*-
"""离线单测：#20 真机 runner 注册覆盖 —— 与 pipeline 引用名对账 + 破坏实验。

不需要游戏 / 设备；默认连 maa 运行时都不需要（第 1~3 项只做纯集合对账）。
直接跑：

    .venv\\Scripts\\python.exe tools\\test_live_actions.py

覆盖 #20 的验收：

  1. **引用名 vs 注册名对照**：``assets/resource/pipeline/*.json`` 里被引用的每个
     ``custom_action`` / ``custom_recognition`` 都能在 ``tools/live_harness.py`` 的
     唯一注册源里找到；并打印完整对照表；
  2. **#13 缺口复现**：修复前 ``run_special_live.py`` 手写的那份注册集缺
     ``restart_game``（真机看门狗命中却救不了），现在已被覆盖；
  3. **挂点** ``hooks_20`` 已点亮（两个守卫都 True）、prove-red 成立；
  4. **best-effort**：真的建一个 Resource、加载 bundle 并注册全部名字（证明实现类
     能实例化/解析；缺 maa / bundle 则 SKIP，不算失败）。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_20.py``。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_20  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

# 修复前 run_special_live.py 手写的注册集（#13 缺口的来源，仅作对照证据）。
OLD_RUN_SPECIAL_LIVE = {
    "next_stage",
    "no_list_badge",
    "list_all_done",
    "page_done_repeat",
    "stall_recover",
    "special_batch_plan",
    "special_target_fight",
    "batch_mode",
    "mark_done",
    "special_batch_fight",
    "special_batch_finish",
}


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 1. 引用名 vs 注册名
# ---------------------------------------------------------------------------
def test_referenced_vs_registered() -> None:
    print("\n== 1. pipeline 引用名 vs runner 注册名 ==")
    import live_harness as ca

    ref_recos, ref_actions = hooks_20.referenced_custom_names()
    reg_recos, reg_actions = ca.registered_custom_names()

    print(f"  引用到的识别 ({len(ref_recos)}): {sorted(ref_recos)}")
    print(f"  引用到的动作 ({len(ref_actions)}): {sorted(ref_actions)}")
    print(f"  runner 注册的识别 ({len(reg_recos)}): {sorted(reg_recos)}")
    print(f"  runner 注册的动作 ({len(reg_actions)}): {sorted(reg_actions)}")

    miss_recos = sorted(ref_recos - reg_recos)
    miss_actions = sorted(ref_actions - reg_actions)
    check("引用到的每个自定义识别都被注册", not miss_recos, f"缺={miss_recos}")
    check("引用到的每个自定义动作都被注册", not miss_actions, f"缺={miss_actions}")

    # 每个注册名都要能解析到真实实现类（不是空壳名字）。
    bad = [
        name
        for name, spec in {**ca.CUSTOM_RECOGNITIONS, **ca.CUSTOM_ACTIONS}.items()
        if hooks_20._resolve_ok(ca, spec) is not None
    ]
    check("每个注册名都能解析到实现类", not bad, f"坏={bad}")


# ---------------------------------------------------------------------------
# 2. #13 缺口复现：旧子集缺 restart_game
# ---------------------------------------------------------------------------
def test_gap_repro() -> None:
    print("\n== 2. #13 缺口复现：旧 run_special_live 子集 vs 引用名 ==")
    ref_recos, ref_actions = hooks_20.referenced_custom_names()
    old = OLD_RUN_SPECIAL_LIVE
    gap_actions = sorted(ref_actions - old)
    gap_recos = sorted(ref_recos - old)
    print(f"  旧子集缺的动作: {gap_actions}")
    print(f"  旧子集缺的识别: {gap_recos}")
    check("旧子集确实缺 restart_game（真机看门狗救不了的原因）", "restart_game" in gap_actions)
    check("旧子集缺 wait_seconds（recover.json 也引用它）", "wait_seconds" in gap_actions)

    import live_harness as ca

    reg_recos, reg_actions = ca.registered_custom_names()
    check("新注册源已补上 restart_game", "restart_game" in reg_actions)


# ---------------------------------------------------------------------------
# 3. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 3. 挂点点亮 + prove-red ==")
    check(
        "挂点 runner-registers-all-pipeline-customs 已点亮",
        hooks_20.probe_runner_registers_all_pipeline_customs() is True,
    )
    check(
        "挂点 live-runners-use-canonical-registration 已点亮",
        hooks_20.probe_live_runners_use_canonical_registration() is True,
    )
    check("hooks_20.prove_red() 成立（删名 / 删调用各自变红）", hooks_20.prove_red() is True)


# ---------------------------------------------------------------------------
# 4. best-effort：真建 Resource 并注册全部名字
# ---------------------------------------------------------------------------
def test_real_resource_registration() -> None:
    print("\n== 4. best-effort：真建 Resource、加载 bundle 并注册全部名字 ==")
    assets = REPO_ROOT / "assets" / "resource"
    try:
        from maa.resource import Resource
        from maa.toolkit import Toolkit
    except Exception as exc:  # noqa: BLE001
        skip("Resource 注册全量自定义名", f"缺 maa：{exc}")
        return
    try:
        Toolkit.init_option(str(REPO_ROOT))
        res = Resource()
        if not res.post_bundle(str(assets)).wait().succeeded:
            skip("Resource 注册全量自定义名", "assets bundle 加载失败")
            return
        import live_harness as ca

        registered = ca.register_pipeline_customs(res)
        expected = set(ca.CUSTOM_RECOGNITIONS) | set(ca.CUSTOM_ACTIONS)
        check(
            f"register_pipeline_customs 注册了全部 {len(expected)} 个名字（含 restart_game）",
            set(registered) == expected,
            f"registered={len(registered)}",
        )
    except Exception as exc:  # noqa: BLE001
        skip("Resource 注册全量自定义名", f"资源/绑定不可用：{exc!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：#20 真机 runner 注册覆盖（引用名 vs 注册名 + 破坏实验）")
    print("=" * 70)
    test_referenced_vs_registered()
    test_gap_repro()
    test_hooks_and_prove_red()
    test_real_resource_registration()
    print("\n" + "=" * 70)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
