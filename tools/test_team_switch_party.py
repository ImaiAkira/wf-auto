# -*- coding: utf-8 -*-
"""#124 定向离线测试：Party 横向滑动 + 三重校验（``switch_party``）。

    .venv\\Scripts\\python.exe tools\\test_team_switch_party.py

五段：

① **契约面**：签名（``target`` + 三个 keyword-only 钩子 + ``clamp``）、票面常量（几何 /
   ``|Δ| ≤ 12`` / 重试 ≤1）、真机 10 队（``TEAM_PARTY_COUNT`` / 字母表 A..J）、纯函数
   （方向几何 / 边界 / 越界零滑动 / 读数归一化 / 三重校验三票缺一即红）。
② **守卫面**：直接跑 ``tools/contract_hooks/hooks_124.py`` 的九个挂点（假设备 ``FakeScreen`` /
   ``FakeBattlePage``，不碰真机、不等 1.6s）。
③ **探针面**：``tools/probe_team_carousel.py`` 有 ``--from/--to``（标定 Party 上下界与是否循环）、
   ``--target``（#124 真机入口）、``--clamp``（显式夹紧），滑动行 y 取 SET 框（不写死），
   且 ``--help`` 能跑。
④ **接线面**（#124 收尾）：6 个常量已在真源 ``scene/team.py``（agent 侧逐字快照）、
   ``TeamSwitchBattleAction`` 在 A 类页走 ``switch_party``、非 A 类页/读不到编队 ⇒ 不动、
   ``party`` 参数缺席时保持旧「只切 SET」语义（向后兼容）。
⑤ **真机后续面**（2026-10-18）：越界目标（0/11/99）**零滑动**且日志含「一步没滑」、
   默认**绝不夹紧**（``switch_party(11)`` 不许 True）、显式 ``clamp=True`` 才夹并打印结果。

★为什么单独一个测试文件★：守卫（hooks_124）证明的是「算法对」；这个文件把「票面契约」也钉住
（签名/常量/探针参数/动作参数），免得实现里改了常量、探针或参数，守卫却仍绿。
"""

from __future__ import annotations

import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FAILS: list = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _load_hooks():
    """按文件路径加载 hooks_124（不写 sys.modules、不依赖当前工作目录）。"""
    path = HOOKS_DIR / "hooks_124.py"
    spec = importlib.util.spec_from_file_location("_hooks_124_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import team_impl as ti  # noqa: E402
from scene import team as sc  # noqa: E402

hooks = _load_hooks()


# ---------------------------------------------------------------------------
# ① 契约面
# ---------------------------------------------------------------------------
def part_contract() -> None:
    print("\n== ① 契约面：签名 / 常量 / 纯函数 ==")
    sig = inspect.signature(ti.switch_party)
    kinds = {name: p.kind for name, p in sig.parameters.items()}
    check(
        "签名是 switch_party(target, *, …)",
        list(sig.parameters)[0] == "target"
        and kinds.get("target") is inspect.Parameter.POSITIONAL_OR_KEYWORD,
        str(sig),
    )
    for name in ("tap_hook", "swipe_hook", "read_hook"):
        param = sig.parameters.get(name)
        check(
            f"钩子 {name} 是 keyword-only 且默认 None",
            param is not None
            and param.kind is inspect.Parameter.KEYWORD_ONLY
            and param.default is None,
        )
    clamp = sig.parameters.get("clamp")
    check(
        "clamp 是 keyword-only 且默认 False（绝不默认夹紧）",
        clamp is not None
        and clamp.kind is inspect.Parameter.KEYWORD_ONLY
        and clamp.default is False,
        f"{clamp}",
    )
    # 注意：team_impl 有 `from __future__ import annotations`，注解是字符串。
    check(
        "返回注解是 bool",
        sig.return_annotation in (bool, "bool"),
        f"{sig.return_annotation!r}",
    )

    check("左滑几何 (600,200)", tuple(ti.TEAM_PARTY_SWIPE_LEFT) == (600, 200))
    check("右滑几何 (200,600)", tuple(ti.TEAM_PARTY_SWIPE_RIGHT) == (200, 600))
    check("单次滑动时长 = 450ms（与入库探针同口径）", int(ti.TEAM_PARTY_SWIPE_MS) == 450)
    check("|Δ| 上限 = 12（票面建议值）", int(ti.TEAM_PARTY_SWIPE_MAX) == 12)
    check("重试上限 = 1（票面 ≤1）", int(ti.TEAM_PARTY_RETRIES) == 1)
    check("每步间隔 > 0（有节拍，不空转）", float(ti.TEAM_PARTY_STEP_SLEEP) > 0)

    # ★2026-10-18 真机后续★ Party 1..10（环形）；字母表 A..J 也必须是 10 个。
    check("真机队数 = 10（scene 真源）", int(sc.TEAM_PARTY_COUNT) == 10, f"{sc.TEAM_PARTY_COUNT}")
    check("真机队数 = 10（agent 运行时）", int(ti.TEAM_PARTY_COUNT) == 10, f"{ti.TEAM_PARTY_COUNT}")
    check(
        "字母表 = ABCDEFGHIJ 且长度 == 队数（真源 + agent 两侧）",
        sc.TEAM_PARTY_LETTERS == ti.TEAM_PARTY_LETTERS == "ABCDEFGHIJ"
        and len(sc.TEAM_PARTY_LETTERS) == int(sc.TEAM_PARTY_COUNT),
        f"scene={sc.TEAM_PARTY_LETTERS!r} agent={ti.TEAM_PARTY_LETTERS!r}",
    )
    check("party_ordinal('I') = 9", ti.party_ordinal("I") == 9, f"{ti.party_ordinal('I')}")
    check("party_ordinal('J') = 10", ti.party_ordinal("J") == 10, f"{ti.party_ordinal('J')}")
    check("party_ordinal('K') = None（越界字母绝不猜）", ti.party_ordinal("K") is None)
    check(
        "GUI 值域仍是 6 队（interface.json 只有 1..6；真机 10 队是另一件事）",
        int(sc.TEAM_OPTION_PARTIES) == 6 and len(sc.option_values()) == 7,
        f"TEAM_OPTION_PARTIES={sc.TEAM_OPTION_PARTIES} values={sc.option_values()}",
    )
    check(
        "party_target_ok：1..10 可，0 / 11 / 99 / None 不可",
        all(ti.party_target_ok(p) for p in range(1, 11))
        and not any(ti.party_target_ok(p) for p in (0, 11, 99, None)),
    )
    check(
        "clamp_party_target：11→10 / 0→1 / 99→10",
        ti.clamp_party_target(11) == 10
        and ti.clamp_party_target(0) == 1
        and ti.clamp_party_target(99) == 10,
    )

    # ★#124 收尾★ 6 个常量已搬进真源 scene/team.py：真源 == agent 逐字快照 == 运行时。
    for name in (
        "TEAM_PARTY_SWIPE_LEFT",
        "TEAM_PARTY_SWIPE_RIGHT",
        "TEAM_PARTY_SWIPE_MS",
        "TEAM_PARTY_STEP_SLEEP",
        "TEAM_PARTY_SWIPE_MAX",
        "TEAM_PARTY_RETRIES",
    ):
        src = getattr(sc, name, "<missing>")
        snap = getattr(ti, f"_{name}_SNAPSHOT", "<missing>")
        live = getattr(ti, name, "<missing>")
        check(
            f"{name}：真源 == 逐字快照 == 运行时",
            src != "<missing>" and snap != "<missing>" and src == snap and live == src,
            f"scene={src!r} snapshot={snap!r} runtime={live!r}",
        )

    check("方向 +1 -> 左滑", ti.party_swipe_geometry(1, 468)[:2] == (600, 200))
    check("方向 -1 -> 右滑", ti.party_swipe_geometry(-1, 468)[:2] == (200, 600))
    check("|Δ| = 12 在界内", ti.party_swipe_gap_ok(12) is True)
    check("|Δ| = 13 越界", ti.party_swipe_gap_ok(13) is False)
    check("|Δ| = -13 也越界", ti.party_swipe_gap_ok(-13) is False)

    # 读数归一化：tuple / dict / 坏形状
    a = ti.to_team_reading(((1, [90, 458, 60, 20]), 5, 1000))
    check(
        "tuple 读数归一化（SET 号 + 框 / Party / 战力）",
        (a.set_no, a.party, a.power, tuple(a.set_box)) == (1, 5, 1000, (90, 458, 60, 20)),
        f"{a}",
    )
    b = ti.to_team_reading({"set": (2, [1, 2, 3, 4]), "party": 3, "power": None})
    check("dict 读数归一化", (b.set_no, b.party, b.power) == (2, 3, None), f"{b}")
    check("坏形状 -> None", ti.to_team_reading("nope") is None)
    check("读不到 SET/Party 时 readable=False", ti.TeamReading(None, 3, 1).readable is False)

    good = ti.TeamReading(1, 3, 100, (90, 458, 60, 20))
    hit = ti.TeamReading(1, 5, 900, (90, 458, 60, 20))
    ok, _reasons = ti.verify_party_switch(good, hit, 5)
    check("三重校验：三票齐全 -> True", ok is True)
    for label, bad, needle in (
        ("SET 变了", ti.TeamReading(2, 5, 900, ()), "SET 变了"),
        ("Party 没到", ti.TeamReading(1, 4, 900, ()), "Party 没到位"),
        ("战力没变", ti.TeamReading(1, 5, 100, ()), "战力没变"),
    ):
        ok, reasons = ti.verify_party_switch(good, bad, 5)
        check(
            f"三重校验缺「{label}」-> False 且原因带量",
            ok is False and any(needle in reason for reason in reasons),
            f"{reasons}",
        )


# ---------------------------------------------------------------------------
# ⑤ 真机后续面：越界零滑动 / 不默认夹紧 / 显式夹紧
# ---------------------------------------------------------------------------
def part_target_bounds() -> None:
    print("\n== ⑤ 真机后续面：越界一步不滑 / 默认不夹紧 / clamp=True 才夹 ==")
    for bad in (0, 11, 99):
        screen = hooks.FakeScreen(party=10)
        ok, out = hooks._run(
            ti, screen, lambda s=screen, b=bad: ti.switch_party(b, swipe_hook=s.swipe)
        )
        check(f"switch_party({bad}) ⇒ False", ok is False, f"{ok}")
        check(
            f"switch_party({bad}) ⇒ 零滑动、零读数",
            screen.swipes == [] and screen.reads == 0,
            f"swipes={len(screen.swipes)} reads={screen.reads}",
        )
        check(
            f"switch_party({bad}) 日志含「一步没滑」",
            "一步没滑" in out and "不存在" in out,
            out.strip().splitlines()[-1][:160],
        )
        check(
            f"switch_party({bad}) 默认路径不打印夹紧",
            "夹紧" not in out,
            out.strip().splitlines()[-1][:160],
        )

    # 显式 clamp=True：打印夹紧结果并真的切过去（Party 3 → 夹到 10）
    screen = hooks.FakeScreen(party=3)
    ok, out = hooks._run(ti, screen, lambda: ti.switch_party(99, swipe_hook=screen.swipe, clamp=True))
    check("clamp=True 目标 99 ⇒ 夹到 10 并切成功", ok is True and screen.party == 10, f"{screen.party}")
    check(
        "clamp=True 打印「夹紧到 10」+ 原始目标 99",
        "夹紧到 10" in out and "目标 Party 99" in out,
        out.strip().splitlines()[0][:200],
    )

    # clamp=True 且夹到目标时：零滑动、幂等
    same = hooks.FakeScreen(party=10)
    ok, _out = hooks._run(ti, same, lambda: ti.switch_party(11, swipe_hook=same.swipe, clamp=True))
    check("clamp=True 目标 11 ⇒ 夹到已在的 10，零滑动", ok is True and same.swipes == [], f"{same.swipes}")


# ---------------------------------------------------------------------------
# ② 守卫面
# ---------------------------------------------------------------------------
def part_probes() -> None:
    print("\n== ② 守卫面：hooks_124 的九个挂点（假设备，不碰真机） ==")
    want_ids = [
        hooks.HOOK_ID_DIRECTION,
        hooks.HOOK_ID_TRIPLE,
        hooks.HOOK_ID_BOUND,
        hooks.HOOK_ID_SEAMS,
        hooks.HOOK_ID_CONSTANTS,
        hooks.HOOK_ID_WIRING,
        hooks.HOOK_ID_TARGET_BOUNDS,
        hooks.HOOK_ID_ALPHABET,
        hooks.HOOK_ID_COUNT_ACTIONS,
    ]
    check("九个挂点都在且顺序稳定", [h[0] for h in hooks.HOOKS] == want_ids, f"{[h[0] for h in hooks.HOOKS]}")
    for hook_id, ticket, _what, probe in hooks.HOOKS:
        check(f"{hook_id}（{ticket}）绿", probe() is True)


# ---------------------------------------------------------------------------
# ④ 接线面：动作层走 switch_party（A 类页）／不动（非 A 类页 / 读不到）
# ---------------------------------------------------------------------------
def part_action_wiring() -> None:
    print("\n== ④ 接线面：TeamSwitchBattleAction（A 类页 ⇒ switch_party；参数向后兼容） ==")

    # (a) A 类页 + party：调 switch_party，真滑到目标，零点击
    page = hooks.FakeBattlePage(party=3)
    out, calls = hooks.run_battle_action(page, {"set": 1, "party": 5})
    check("A 类页 + party=5 ⇒ 调用了 switch_party(5)", calls["switch_party"] == [5], f"{calls}")
    check("动作真的把 Party 滑到 5（不是只打印）", page.party == 5, f"party={page.party}")
    check("切队全程零点击（真机：只要横向滑动）", page.clicks == [], f"{page.clicks}")
    check("动作打印成功收尾", "✓ 收尾" in out, out[-160:])

    # (b) 非 A 类页：零调用
    b_page = hooks.FakeBattlePage(party=3, page="B")
    _out, calls = hooks.run_battle_action(b_page, {"set": 1, "party": 5})
    check("B 类页 ⇒ 不调用 switch_party", calls["switch_party"] == [], f"{calls}")
    check("B 类页 ⇒ 零滑动零点击", b_page.swipes == [] and b_page.clicks == [], f"{b_page.swipes} {b_page.clicks}")

    # (c) A 类页但读不到编队：零调用（旧「读不到就不动」）
    blind = hooks.FakeBattlePage(party=3, party_readable=False)
    out, calls = hooks.run_battle_action(blind, {"set": 1, "party": 5})
    check("读不到编队 ⇒ 不调用 switch_party", calls["switch_party"] == [], f"{calls}")
    check("读不到编队 ⇒ 打印「拒动」", "拒动" in out, out[-160:])

    # (d) party 参数缺席：保持旧「只切 SET」语义（不碰 switch_party）
    same = hooks.FakeBattlePage(party=5)
    out, calls = hooks.run_battle_action(same, {"set": 1})
    check("不给 party ⇒ 不调用 switch_party（向后兼容）", calls["switch_party"] == [], f"{calls}")
    check("不给 party ⇒ 旧成功行「✓ 收尾：SET 1 / 队 5」", "✓ 收尾：SET 1 / 队 5" in out, out[-160:])
    check("不给 party ⇒ 零滑动", same.swipes == [], f"{same.swipes}")

    # (e) ★真机后续③★ 显式 party=0 / 11 ⇒ 拒动（0 不是队号，真机 1..10）；7/10 放行
    for bad in (0, 11):
        page = hooks.FakeBattlePage(party=5)
        out, calls = hooks.run_battle_action(page, {"set": 1, "party": bad})
        check(f"显式 party={bad} ⇒ 拒动（不调 switch_party）", calls["switch_party"] == [], f"{calls}")
        check(f"显式 party={bad} ⇒ 零滑动", page.swipes == [], f"{page.swipes}")
        check(f"显式 party={bad} ⇒ 日志说「不存在」", "不存在" in out, out[-160:])
    for good in (7, 10):
        page = hooks.FakeBattlePage(party=good - 1)
        out, calls = hooks.run_battle_action(page, {"set": 1, "party": good})
        check(
            f"真机 10 队：party={good} 放行并切到",
            calls["switch_party"] == [good] and page.party == good,
            f"calls={calls} party={page.party}",
        )
        check(f"party={good} 打印成功收尾", "✓ 收尾" in out, out[-160:])


# ---------------------------------------------------------------------------
# ③ 探针面
# ---------------------------------------------------------------------------
def part_probe_tool() -> None:
    print("\n== ③ 探针面：--from/--to（标定）/ --target（真机入口）/ --clamp（显式夹紧） ==")
    probe = TOOLS_DIR / "probe_team_carousel.py"
    text = probe.read_text(encoding="utf-8")
    for needle in (
        '"--from"',
        '"--to"',
        '"--target"',
        '"--clamp"',
        "SWIPE_LEFT = (600, 200)",
        "SWIPE_RIGHT = (200, 600)",
        "switch_party",
        "clamp=a.clamp",
    ):
        check(f"probe_team_carousel 含 {needle}", needle in text)
    check(
        "滑动行 y 取自 SET 框（_set_box + 框中心），不是写死",
        "_set_box" in text and "box[1] + box[3] / 2.0" in text,
    )
    check("465 只作为兜底常量出现一次（没有第二处写死）", text.count("465") == 1, f"count={text.count('465')}")
    proc = subprocess.run(
        [sys.executable, str(probe), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    check(
        "probe --help 可运行（argparse 接线没坏，且列出 --from/--to/--target/--clamp）",
        proc.returncode == 0
        and "--from" in proc.stdout
        and "--to" in proc.stdout
        and "--target" in proc.stdout
        and "--clamp" in proc.stdout,
        (proc.stdout or proc.stderr or "").strip().splitlines()[-1][:160],
    )


def main() -> int:
    print("#124 Party 切换（横向滑动 + 三重校验）定向测试")
    print(f"真源：{Path(ti.__file__).resolve()}")
    print(f"守卫：{HOOKS_DIR / 'hooks_124.py'}")
    part_contract()
    part_target_bounds()
    part_probes()
    part_probe_tool()
    part_action_wiring()
    print()
    if FAILS:
        print(f"FAILED：{len(FAILS)} 项 —— " + "; ".join(FAILS[:8]))
        return 1
    print(
        "ALL GREEN —— 方向 / 三重校验 / 有界 / 接缝 / 常量真源 / 动作接线 / "
        "越界一步不滑 / 不默认夹紧 / 10 队与字母表 全绿"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
