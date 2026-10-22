# -*- coding: utf-8 -*-
"""#23 回归：把 2026-10-19 14:33「19 战全部正常完成 → 自杀」那次事故钉成夹具 + 两套口径。

## 事故

2026-10-19 12:45 起跑「自动刷深渊EX」，19 战全部正常记账，1h48m 后在第 20 战的结算转场帧上
以「未知画面累计 121 次」收工。决策见 ``docs/adr/0005-unknown-is-time-not-frames.md``：
「未知画面」是**时间**信号（连续认不出多久），不是**帧计数**（累计多少帧）。

夹具 = 那一轮的逐帧状态序列：``tools/frames/abyss_1019_state_seq.txt``（725 帧，来源日志
``<dist>/debug/maafw.bak.2026.10.19-13.12.50.89.log`` 与 ``…-17.34.37.153.log``，窗口
12:45:09~13:12:50 与 13:13:00~14:33:25；取数口径见夹具头注释）。

## 为什么这里「本地实现两套算法」而不是 import 业务代码

本票只做夹具与守卫，业务改动在别的 lane（#18 kernel / #19 深渊 / #24 五重）。测试一旦
``import abyss_impl``，就会变成「跟着业务一起漂」的假守卫：业务换成新口径后，旧口径那条
断言会凭空消失（或者更糟，被改成同义反复）。所以两套算法在这里各写一份最小实现：

* **旧口径**（``old_unknown_counter``）：``unknown`` 跳变计数 —— 相邻状态不同才 +1，累计值
  ``> 120`` 收工。这就是 ``agent/abyss_impl.py::_observe`` 当年的写法（``if changed: += 1``）
  与 ``AbyssGiveUpRecognition`` 的闸门（``elif unknown > unknown_limit``）。
* **新口径**（``local_lost_gate``）：最长**连续 unknown 秒数**，``>= 60s`` 触发；命中任一已知页
  （含 ``loading``）即清零。等价于 ADR 0005 的 ``LostClock``（``in_fight`` 期间不打点这一条属于
  动作层观测，夹具里没有战斗内帧，故这里不需要）。

## 只断言「同一量纲下的数值」

真机计数器读到的越线值是 **121**，而本夹具同口径算出来是 **110** —— 差的 11 次来自
**动作层点完按钮后的复查观测**：那些帧同样会被 ``abyss_state`` 分类，但它们不落在
``all_results_`` 结果行里（本夹具只由结果行重建）。所以这里断言的是「同一量纲下的数值」
（110，以及它 < 120 这个事实），**不是**逐字复刻 121。

## 跑法

    .venv\\Scripts\\python.exe tools\\test_abyss_lost.py

夹具缺失时明确 SKIP 并打印原因（退出码 0），绝不静默通过。
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
FIXTURE = TOOLS_DIR / "frames" / "abyss_1019_state_seq.txt"

#: 旧口径：``unknown`` 跳变累计上限（``AbyssGiveUp`` 的 ``unknown_limit`` 默认值）。生产是
#: ``unknown > unknown_limit``（严格大于）→ 读到 **121** 才收工，与日志里那句「累计 121 次」一致。
OLD_LIMIT = 120

#: 新口径：连续认不出画面的秒数上限（ADR 0005：深渊 60s，实测 p95 6s / 最长 16s → 3.75× 余量）。
NEW_LIMIT_SEC = 60.0

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print(f"  [SKIP] {name}  ({why})")
    SKIPS.append(name)


# ---------------------------------------------------------------------------
# 夹具读取
# ---------------------------------------------------------------------------
def _sec_of_day(hhmmss: str) -> int:
    hh, mm, ss = (int(x) for x in hhmmss.split(":"))
    return hh * 3600 + mm * 60 + ss


def parse_fixture(path: Path) -> list[tuple[int, str]]:
    """读夹具 → ``[(当日秒数, state), …]``；``#`` 头注释与空行跳过。"""
    frames: list[tuple[int, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"夹具行格式不是「HH:MM:SS<TAB>state」：{raw!r}")
        frames.append((_sec_of_day(parts[0]), parts[1]))
    return frames


# ---------------------------------------------------------------------------
# 旧口径：unknown 跳变计数（累计帧数）
# ---------------------------------------------------------------------------
def old_unknown_counter(frames: list[tuple[int, str]], limit: int = OLD_LIMIT) -> dict:
    """相邻状态不同且新状态是 ``unknown`` 时 +1；累计值 ``> limit`` 收工。

    返回 ``{"count", "fired_at", "fire_index", "reason"}``：``count`` 是全程累计，
    ``fired_at`` 是**第一次**越线时的累计值（没越线为 ``None``）。
    """
    count = 0
    fired_at = None
    fire_index = None
    if not frames:
        return {"count": 0, "fired_at": None, "fire_index": None, "reason": None}
    prev = frames[0][1]  # 首帧没有「上一帧」可比：夹具首帧就是 unknown，但它不算一次「进入」
    for i, (_t, state) in enumerate(frames[1:], start=1):
        if state == "unknown" and state != prev:
            count += 1
            if fired_at is None and count > limit:
                fired_at = count
                fire_index = i
        prev = state
    reason = None if fired_at is None else f"未知画面累计 {fired_at} 次"
    return {"count": count, "fired_at": fired_at, "fire_index": fire_index, "reason": reason}


# ---------------------------------------------------------------------------
# 新口径：最长连续 unknown 秒数（LostClock 等价物）
# ---------------------------------------------------------------------------
def local_lost_gate(frames: list[tuple[int, str]], limit_sec: float = NEW_LIMIT_SEC) -> dict:
    """连续 ``unknown`` 秒数 ``>= limit_sec`` 时触发（每段只触发一次），命中已知页即清零。

    返回 ``{"triggers": [(起始秒, 触发时秒数)], "worst_sec", "worst_at", "runs"}``。
    ``worst_sec`` 是**最长**一段连续 unknown 的时长（= 从进入 unknown 到认出下一个已知页，
    跨已知页即断），即使没触发也有值；``worst_at`` 是那一段的起始秒。
    """
    triggers: list[tuple[int, float]] = []
    runs: list[tuple[int, float]] = []
    start: int | None = None
    fired = False
    for t, state in frames:
        if state != "unknown":
            if start is not None:
                runs.append((start, float(t - start)))
            start, fired = None, False
            continue
        if start is None:
            start, fired = t, False
        elapsed = float(t - start)
        if not fired and elapsed >= limit_sec:
            triggers.append((start, elapsed))
            fired = True
    if start is not None:  # 结尾仍在 unknown：这段没有「下一个已知页」可以闭合
        runs.append((start, float(frames[-1][0] - start)))
    if not runs:
        return {"triggers": triggers, "worst_sec": 0.0, "worst_at": None, "runs": runs}
    worst_start, worst_sec = max(runs, key=lambda r: r[1])
    return {"triggers": triggers, "worst_sec": worst_sec, "worst_at": worst_start, "runs": runs}


def lost_reason(seconds: float, last_known: str | None) -> str:
    """ADR 0005 的收工原因文案（三处场景同一句）。"""
    return f"连续 {seconds:.0f}s 认不出画面（最后已知页：{last_known}）"


# ---------------------------------------------------------------------------
# 1. 夹具本身没导错（读数与 ADR 0005 里引用的那组数一致）
# ---------------------------------------------------------------------------
def test_fixture_shape(frames: list[tuple[int, str]]) -> None:
    print("\n== 1. 夹具读数（与 ADR 0005 引用值一致） ==")
    unknown = [st for _t, st in frames if st == "unknown"]
    share = len(unknown) / len(frames) * 100
    check("帧数 == 725", len(frames) == 725, f"实际 {len(frames)}")
    check("unknown 帧占 15.3%", abs(share - 15.3) < 0.05, f"实际 {len(unknown)}/{len(frames)} = {share:.1f}%")
    check(
        "最后一帧就是收工那一帧（14:33:21 unknown）",
        frames[-1] == (_sec_of_day("14:33:21"), "unknown"),
        f"实际 {frames[-1]}",
    )


# ---------------------------------------------------------------------------
# 2. 旧口径：夹具上累计 110（真机 121，差的 11 次来自动作层复查观测）
# ---------------------------------------------------------------------------
def test_old_metric_is_frame_count(frames: list[tuple[int, str]]) -> None:
    print("\n== 2. 旧口径（unknown 跳变计数）：夹具上累计 110 ==")
    got = old_unknown_counter(frames)
    check(
        "累计 == 110 段 unknown",
        got["count"] == 110,
        f"实际 {got['count']}（真机计数器读到 121：差的 11 次是动作层点完按钮后的复查观测，"
        f"不进 all_results_ 结果行 → 同一量纲，不逐字相等）",
    )
    check(
        "110 <= 120：在夹具口径下旧闸门本来就没越线（越线是那 11 次复查把它推过去的）",
        got["count"] <= OLD_LIMIT,
        f"{got['count']}/{OLD_LIMIT} = {got['count'] / OLD_LIMIT * 100:.0f}% 预算",
    )
    check("首帧即 unknown 不计「进入」（与参考实现/ADR 同口径）", frames[0][1] == "unknown")
    runs = local_lost_gate(frames)["runs"]
    check(
        "unknown 段数 111 = 进入 110 段 + 12:45:10 那一开局段",
        len(runs) == 111 and got["count"] == len(runs) - 1,
        f"段数 {len(runs)} / 进入 {got['count']}",
    )


# ---------------------------------------------------------------------------
# 3. 新口径：夹具最长 16s < 60s → 0 次触发
# ---------------------------------------------------------------------------
def test_new_metric_never_fires_on_fixture(frames: list[tuple[int, str]]) -> None:
    print("\n== 3. 新口径（最长连续 unknown 秒数）：夹具上 0 次触发 ==")
    got = local_lost_gate(frames)
    check("最长连续 unknown == 16s（12:46:22 那段）", got["worst_sec"] == 16.0, f"实际 {got['worst_sec']}s")
    check(
        "16s < 60s：整轮 19 战从未「迷路」",
        got["worst_sec"] < NEW_LIMIT_SEC,
        f"余量 {NEW_LIMIT_SEC / max(got['worst_sec'], 1):.2f}×",
    )
    check("触发次数 == 0", got["triggers"] == [], f"实际 {got['triggers']}")
    print(f"    诊断：旧口径已烧掉 {old_unknown_counter(frames)['count']}/{OLD_LIMIT} 预算，"
          f"新口径 0 次触发 —— 同一份夹具，两个量纲的差别就在这里。")


# ---------------------------------------------------------------------------
# 4. 新口径的灵敏度：合成 90s 连续 unknown 必须触发（59s 必须不触发）
# ---------------------------------------------------------------------------
def _synthetic(start: str, lost_sec: int, step: int = 10) -> list[tuple[int, str]]:
    """从 ``start`` 起造一段 ``lost_sec`` 秒的连续 unknown，随后跟一个已知页（``abyss_settle``）。

    「连续驻留」= 进入 unknown 到认出下一个已知页之间的时长，所以已知页落在 ``lost_sec`` 那一秒。
    """
    t0 = _sec_of_day(start)
    frames = [(t0 + off, "unknown") for off in range(0, lost_sec, step)]
    frames.append((t0 + lost_sec, "abyss_settle"))
    return frames


def test_new_metric_fires_on_long_lost() -> None:
    print("\n== 4. 新口径的灵敏度：合成 90s 连续 unknown 必触发、59s 不触发 ==")
    long_lost = _synthetic("08:00:00", 90)
    got = local_lost_gate(long_lost)
    check("90s 连续 unknown → 触发 1 次", len(got["triggers"]) == 1, f"实际 {got['triggers']}")
    check(
        "触发点是第 60s（不是第 90s：越线即报，不等到画面换页）",
        bool(got["triggers"]) and got["triggers"][0][1] == NEW_LIMIT_SEC,
        f"实际 {got['triggers']}",
    )
    check("收工原因文案 = ADR 0005 那句", lost_reason(got["worst_sec"], "abyss_settle")
          == "连续 90s 认不出画面（最后已知页：abyss_settle）")

    borderline = local_lost_gate(_synthetic("09:00:00", 59))
    check("59s 连续 unknown（差 1 秒）→ 不触发", borderline["triggers"] == [], f"实际 {borderline['triggers']}")


# ---------------------------------------------------------------------------
# 5. 量纲对照：无界会话 + 累计量 = 必然越线（ADR 0005 第 1 条结构判断）
# ---------------------------------------------------------------------------
def test_cumulative_gate_inevitable(frames: list[tuple[int, str]]) -> None:
    print("\n== 5. 量纲对照：同一轮动作再来一遍 → 旧口径必越线、新口径仍 0 ==")
    # 第二轮 = 第一轮原样再来一遍（夹具结尾停在 unknown，中间补一个已知页把两段断开，
    # 否则两段 unknown 会在拼接处连成一段假的 66s）。
    span = (frames[-1][0] - frames[0][0]) + 120
    doubled = (
        frames
        + [(frames[-1][0] + 15, "main_city")]
        + [(t + span, s) for t, s in frames]
    )
    old = old_unknown_counter(doubled)
    new = local_lost_gate(doubled)
    check(
        "旧口径（38 战）必越 120 → 以「未知画面累计 N 次」收工",
        old["fired_at"] is not None and old["fired_at"] > OLD_LIMIT,
        f"在累计 {old['fired_at']} 次时收工（{old['reason']!r}）",
    )
    check("新口径（同一序列）仍然 0 次触发", new["triggers"] == [], f"最长仍是 {new['worst_sec']}s")
    print("    结论：对「一直往下刷」的无界会话，累计量一定会越线，与机器人是否迷路无关。")


def main() -> int:
    print(f"夹具：{FIXTURE}")
    if not FIXTURE.is_file():
        skip(
            "事故夹具缺失 —— 本测试的全部断言",
            f"{FIXTURE} 不存在；先用 2026-10-19 的 debug/maafw*.log 重导（口径见夹具头注释）",
        )
        print("\nSKIPPED（夹具缺失，不算通过；退出码 0 只是为了让 run_all_tests.ps1 不误报红）")
        return 0

    frames = parse_fixture(FIXTURE)
    test_fixture_shape(frames)
    test_old_metric_is_frame_count(frames)
    test_new_metric_never_fires_on_fixture(frames)
    test_new_metric_fires_on_long_lost()
    test_cumulative_gate_inevitable(frames)

    print()
    if FAILS:
        print(f"FAILED: {FAILS}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
