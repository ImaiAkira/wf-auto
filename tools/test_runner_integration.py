# -*- coding: utf-8 -*-
"""#104 + #98 + #138 + #141 的 runner 集成契约（静态断言，不连设备、不起进程）。

为什么要有这个测试：租约与监管都是「基础设施」，一旦被谁改掉一行（少传 steal / 少起监管 /
少了退出时的小结），真机长跑出问题时排查成本极高。这里把它钉成文本契约。
#138 再钉一条：`--as-gui` 必须按内容哈希硬闸 install/（agent + resource），
不一致默认非零退出 —— 不许退回「只警告 install/agent」的旧行为。
#141 再钉三条：runner 必须把 agent 侧的动作计数 / 业务进展快照接进监管（否则「有动作无进展」
报警永不触发）；未接线必须显式喊出来；`summary.error` 必须变成非零退出码。
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNNER = REPO / "tools" / "run_wuchong_live.py"
HARNESS = REPO / "tools" / "live_harness.py"
SYNC = REPO / "tools" / "sync_install.py"
LORDS = REPO / "agent" / "lords_impl.py"

FAILS: list[str] = []


def check(name: str, ok: bool, msg: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {msg}" if msg and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    src = RUNNER.read_text(encoding="utf-8-sig")
    ast.parse(src)
    harness = HARNESS.read_text(encoding="utf-8-sig")

    check("runner 能解析（BOM 已处理）", True)
    check("runner 有 --steal 参数（D9：默认排队，显式抢）", "--steal" in src)
    check("runner 把 steal 传给 connect_device", 'steal=bool(getattr(a, "steal", False))' in src)
    check("runner 有 --monitor 参数（#98）", "--monitor" in src)
    check("runner 会起长跑监管", "monitor_for_serial" in src and "_mon.start()" in src)
    check("监管退出时停线程并打小结", "_atexit.register(_mon_stop_and_summary)" in src and "summary.as_line()" in src)
    # ★Q1 + #138★ --as-gui 等价验收模式：install 落后 = 硬失败（不再只警告，且资源也要比）
    check("runner 有 --as-gui（用 install/resource）", "--as-gui" in src and "install" in src)
    check("runner 有 --allow-stale-install 逃生阀（默认关）", "--allow-stale-install" in src)
    check("--as-gui 有硬闸函数 check_install_freshness", "def check_install_freshness(" in src)
    check(
        "硬闸用 sync_install 比对（agent + resource，不再只比 agent）",
        "sync_install.compare_install" in src and "gate_stale" in src,
    )
    check(
        "硬闸是不一致的 SystemExit 非零退出（不是警告后继续）",
        "STALE_INSTALL_EXIT = 2" in src and "raise SystemExit(STALE_INSTALL_EXIT)" in src,
    )
    check(
        "硬闸打印可复制的修法命令",
        "sync_install.FIX_HINT" in src,
    )
    check(
        "逃生阀会显式警告「本次验的不是最新流水线」",
        "本次验的不是最新流水线" in src,
    )
    gate_call = src.find("check_install_freshness(", src.find("def check_install_freshness(") + 1)
    check(
        "硬闸在碰设备（ca.connect_device）之前执行",
        0 <= gate_call < src.index("ca.connect_device("),
    )
    check("--as-gui 会开静音（等同 GUI 的 --quiet）", "set_quiet(True)" in src)
    check("tools/sync_install.py 存在", SYNC.is_file())
    sync_src = SYNC.read_text(encoding="utf-8-sig")
    ast.parse(sync_src)
    check(
        "sync_install 提供 compare_install / sync_project",
        "def compare_install(" in sync_src and "def sync_project(" in sync_src,
    )
    check(
        "修法命令就是 python tools/sync_install.py（可与硬闸共用）",
        'FIX_COMMAND = "python tools/sync_install.py"' in sync_src,
    )
    check(
        "sync_install 范围含 agent / pipeline / image / model",
        all(
            needle in sync_src
            for needle in ('"agent"', "assets/resource/pipeline", "assets/resource/image", "assets/resource/model")
        ),
    )
    check("harness 连设备前拿租约", "_acquire_device_lease" in harness)
    check("harness 连不上/抛错会还租（不霸占）", "release_device_lease" in harness)
    check("harness 进程退出兜底释放（atexit / TTL）", "atexit" in harness)

    # ★#141★ 动作计数 / 业务进展接进监管（否则「有动作无进展」报警真机永不触发）
    check(
        "runner 从 agent 侧取唯一喂料口径（monitor_feed）",
        "def monitor_feed(" in src and "lords_impl" in src,
    )
    check(
        "runner 把 actions_fn / progress_fn 真的传给监管",
        "actions_fn=actions_fn" in src and "progress_fn=progress_fn" in src and "def start_monitor(" in src,
    )
    check(
        "接线成功会打「已接线：actions_fn / progress_fn」",
        "已接线：actions_fn / progress_fn" in src,
    )
    check(
        "未接线必须显式喊出来（含后果，不许静默降级）",
        "未接线" in src and "有动作无进展报警不会触发" in src,
    )
    check(
        "收工 summary.error 非空 ⇒ 打印 ✗ + 非零退出码（monitor_exit_code）",
        "def monitor_exit_code(" in src
        and "MONITOR_ERROR_EXIT" in src
        and "summary.error" in src,
    )
    check(
        "main 包住早退路径：finally 里停监管并取 error",
        "def main(argv" in src and "finally:" in src and "finish_monitor()" in src,
    )
    check(
        "CLI 入口把 main 的退出码真的传出去",
        "raise SystemExit(main())" in src,
    )

    lords = LORDS.read_text(encoding="utf-8-sig")
    ast.parse(lords)
    check(
        "lords_impl 提供动作计数 + 业务进展快照（#141 唯一口径）",
        all(
            needle in lords
            for needle in (
                "def note_action(",
                "def actions_total(",
                "def progress_snapshot(",
                "def progress_marker(",
                "def note_rows(",
            )
        ),
    )
    check(
        "每次成功滚动都计数（3 条路径：扫描 / 找行 / 回顶部）",
        lords.count('note_action("scroll")') >= 2 and lords.count('note_action("scroll_top")') >= 1,
    )
    check(
        "点击计数挂在 _click_hook（成功才记：唯一出口）",
        "def _click_hook(" in lords and 'note_action("click")' in lords,
    )
    check(
        "业务进展快照格式 = rows/targets/round/played",
        'f"rows:{len(self.rows_seen)} targets:{len(self.targets)} "' in lords
        and 'f"round:{self.round_index} played:{self.sessions_played}"' in lords,
    )
    check(
        "两条页读路径都累加新行（mode=page / mode=read）",
        lords.count("session.note_rows(rows)") >= 2,
    )
    check(
        "动作计数单调不减（只增，不重置）",
        "_ACTION_TOTAL += step" in lords,
    )

    if FAILS:
        print(f"\nFAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("\nALL GREEN —— 租约 / 监管 / --as-gui 硬闸 / #141 喂料与失败语义的 runner 集成契约成立")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
