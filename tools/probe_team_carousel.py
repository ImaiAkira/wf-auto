# -*- coding: utf-8 -*-
"""⑦：把 A 类页的**真实交互模型**测出来（受控：连续同方向滑动，记录每一步读数）。

已确认（真机 384，``394eb66`` 入库）：
- 点 SET 页签中心/上方/左侧、点标签下方、``SET编辑``、``推荐编成`` —— 都不能改 SET
- **横向滑动**：左滑（600→200）= Party +1、右滑（200→600）= Party −1，逐步精确可逆
- SET 不变（那一行是队伍轮播）；战力随 Party 变（可当独立证据）

已确认（真机 384，2026-10-18 环形复核，#124 评论；**不要重测**）：
- Party **1..10 环形**：左滑 10→1、右滑 1→10，无「滑不动」的边界；两方向各走完整一圈都回原点；
- 边界画面无异常（SET 1 / 战力 10 队各不相同 / 两侧箭头 / 底部 10 个圆点）；
- 1..10 内最大 |Δ|=9 ≤ 上限 12 ⇒ 环形不影响 ``switch_party`` 的算法。

四种跑法
--------
1. **默认（无参数）**：复现 394eb66 的受控实验 —— 左滑×4 再右滑×6，每步打印读数。
2. ``--from A --to B``：**标定 Party 上下界与是否循环** —— 从 Party A 逐步滑到 B，每步打印读数；
   步子不到预期（被边界夹住 / 循环 / 动画没跟上）会当场标出来；``--from`` 缺省 = 当帧读数。
3. ``--target N``：直接调 ``agent/team_impl.switch_party(N)``（#124：横向滑动 + 三重校验），
   打印 ``[team_party]`` 日志。★这是 #124 算法的真机入口★（本票不碰 pipeline，这里用 adb 滑动
   当 ``swipe_hook``、用 ``Page.team_read`` 当 ``read_hook``）。
   ★越界目标（不在 1..10）会在 ``switch_party`` 里**一步不滑**就失败★（默认不夹紧）；确实要夹到
   1..10 请显式加 ``--clamp``（会打印夹紧结果）。
4. ``--sweep``：**标定 Party 上下界与是否循环（#124）** —— 从当帧 Party 左滑走**完整一圈**、
   再右滑走**完整一圈**；每步一行 ``(SET, Party, 战力)``，末尾给出下界 / 上界 / 是否循环的判词。
   它不需要知道目标值，专门回答「越界了会怎样」。

坐标：全部 **720 空间**；adb 侧 ×1.5 还原（与 ``live_harness.adb_tap`` 同口径）。
滑动行 y **优先取当帧 ``read_team`` 的 SET 框中心**（票面：不写死）；读不到才用兜底常量。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from verify_team_battle import Page  # noqa: E402

#: 真机 394eb66 的滑动几何（720 空间：手指起点 x → 终点 x）。
SWIPE_LEFT = (600, 200)   # 左滑 = Party +1
SWIPE_RIGHT = (200, 600)  # 右滑 = Party −1
#: 滑动行 y 的兜底（**只**在当帧读不到 SET 框时用；正常一律取 SET 框中心）。
FALLBACK_ROW_Y = 465


def _set_box(state):
    """从 ``read_team`` 的返回值里取 ``SET N`` 的框（兼容 dict / tuple / 裸号码）。"""
    if isinstance(state, dict):
        cur = state.get("set")
    elif isinstance(state, (tuple, list)) and state:
        cur = state[0]
    else:
        return None
    if isinstance(cur, (tuple, list)) and len(cur) > 1 and isinstance(cur[1], (tuple, list)):
        box = cur[1]
        if len(box) >= 4:
            return box
    return None


def read(page):
    """一次读数：``{"set", "party", "power", "y"}``（``y`` = SET 框中心，720 空间）。"""
    state, _items = page.team_read()
    no, party, power = Page._unpack(state)
    box = _set_box(state)
    y = int(round(box[1] + box[3] / 2.0)) if box else None
    return {"set": no, "party": party, "power": power, "y": y}


def adb_swipe(page, x_from, x_to, y, ms=450, settle=1.6):
    """720 空间横扫：adb 侧 ×1.5 还原（与 ``live_harness.adb_tap`` 同口径）。"""
    import subprocess  # noqa: PLC0415

    subprocess.run(
        [
            page.lh.ADB, "-s", page.address, "shell", "input", "swipe",
            str(int(x_from * 1.5)), str(int(y * 1.5)),
            str(int(x_to * 1.5)), str(int(y * 1.5)),
            str(int(ms)),
        ],
        check=False,
    )
    if settle:
        time.sleep(settle)


def _fmt(st):
    return f"SET={st['set']} Party={st['party']} 战力={st['power']}"


def _row_y(first):
    """滑动行 y：优先 SET 框中心；读不到才兜底（并明说用了兜底）。"""
    if first.get("y") is not None:
        return int(first["y"])
    print(f"! 读不到 SET 框的 y，用兜底 {FALLBACK_ROW_Y}（只影响本轮的标定读数）", flush=True)
    return FALLBACK_ROW_Y


def run_demo(page, ms=450):
    """复现 394eb66：左滑×4 再右滑×6，每步打印读数。"""
    first = read(page)
    y = _row_y(first)
    trace = [("起点", first)]
    for i in range(4):  # 左滑（手指从右往左 ⇒ Party +1）
        adb_swipe(page, SWIPE_LEFT[0], SWIPE_LEFT[1], y, ms)
        trace.append((f"左滑#{i + 1}", read(page)))
    for i in range(6):  # 再右滑
        adb_swipe(page, SWIPE_RIGHT[0], SWIPE_RIGHT[1], y, ms)
        trace.append((f"右滑#{i + 1}", read(page)))
    for tag, st in trace:
        print(f"{tag:10s} {_fmt(st)}", flush=True)
    print()
    print(json.dumps(trace, ensure_ascii=False), flush=True)
    return 0


def run_walk(page, start, end, ms=450):
    """``--from/--to``：从 start（缺省=当帧）逐步滑到 end，每步打印读数并标出异常。"""
    first = read(page)
    print(f"起点读数：{_fmt(first)}（滑动行 y={first['y']}）", flush=True)
    if first["set"] is None or first["party"] is None:
        print("x 读不到 SET / Party（不在 A 类战前编队页？）", flush=True)
        return 2
    if start is not None and int(first["party"]) != int(start):
        print(
            f"x 起点不符：当前 Party={first['party']}，--from={start}"
            f"（先把 Party 切到 {start} 再跑；绝不替你瞎滑）",
            flush=True,
        )
        return 3
    if end is None:
        print("x 缺少 --to", flush=True)
        return 2
    if int(end) == int(first["party"]):
        print(f"起点就是 --to={end}，没有要走的路", flush=True)
        return 0

    y = _row_y(first)
    direction = 1 if int(end) > int(first["party"]) else -1
    steps = abs(int(end) - int(first["party"]))
    x_from, x_to = SWIPE_LEFT if direction > 0 else SWIPE_RIGHT
    label = "左滑" if direction > 0 else "右滑"
    print(
        f"走法：{label}×{steps}（Party {first['party']} -> {end}；"
        f"每步 {x_from}->{x_to} @y={y}, {ms}ms）",
        flush=True,
    )

    trace = [("起点", first)]
    seen = {int(first["party"])}
    anomalies = []
    for i in range(1, steps + 1):
        adb_swipe(page, x_from, x_to, y, ms)
        cur = read(page)
        trace.append((f"{label}#{i}", cur))
        prev = trace[-2][1]["party"]
        if cur["party"] is None:
            print(f"! 第 {i} 步：Party 读不到了（SET={cur['set']}）", flush=True)
            anomalies.append(f"第{i}步读不到 Party")
            continue
        if prev is not None and int(cur["party"]) != int(prev) + direction:
            print(
                f"! 第 {i} 步：期望 Party={int(prev) + direction}，实际 {cur['party']}"
                f" —— 疑似到边界/循环/动画没跟上",
                flush=True,
            )
            anomalies.append(f"第{i}步 期望{int(prev) + direction}实际{cur['party']}")
        if int(cur["party"]) in seen and i > 1:
            print(
                f"! 第 {i} 步：Party={cur['party']} 又出现（已见 {sorted(seen)}）—— 疑似循环",
                flush=True,
            )
            anomalies.append(f"第{i}步循环回 {cur['party']}")
        seen.add(int(cur["party"]))
        if cur["set"] != first["set"]:
            print(
                f"! 第 {i} 步：SET 变了 {first['set']} -> {cur['set']}（不在同一页/换页了）",
                flush=True,
            )
            anomalies.append(f"第{i}步 SET 变 {first['set']}->{cur['set']}")

    print()
    for tag, st in trace:
        print(f"{tag:10s} {_fmt(st)}", flush=True)
    print()
    parties = [st["party"] for _tag, st in trace]
    sets = {st["set"] for _tag, st in trace}
    print(f"观测：Party 轨迹 {parties}", flush=True)
    if len(sets) == 1:
        print(f"观测：SET 始终 {first['set']}", flush=True)
    else:
        print(f"观测：SET 变过 {sorted(str(s) for s in sets)}", flush=True)
    print(f"观测：异常 {anomalies or '无（每一步都按方向 ±1）'}", flush=True)
    # ★bug 修复★ 以前无论有没有走到 --to 都 `return 0`：被边界夹住 / 中途回绕也报成功，
    #   调用方（人手 or 脚本）看不出「其实没到」。现在按终点读数判，没到就是非 0。
    final = trace[-1][1]["party"]
    reached = final is not None and int(final) == int(end)
    print(
        f"观测：终点 Party={final} / 目标 {end} -> {'✅ 到达' if reached else '✗ 没到目标'}"
        f"（SET {trace[-1][1]['set']} / 战力 {trace[-1][1]['power']}）",
        flush=True,
    )
    print(json.dumps(trace, ensure_ascii=False), flush=True)
    return 0 if reached else 1


def _sweep_one(page, y, direction, ms, max_steps, first_set, start):
    """单方向一路滑：返回 ``(steps, how, wraps)``。

    停条件（顺序）：**完整一圈**（回到本轮已见过的 Party -> ``cycle``）/
    **滑不动**（读数不变 -> ``clamped``）/ 读不到 Party / SET 变了 / 步数用尽。

    为什么不「一遇到回绕就停」：Party 是**环形**轮播时，10 左滑到 1 只是走到环的另一端，
    不是边界；要确认下界必须接着走 `1,2,...,10` 回到起点才能证明「1 就是最小的那个」。
    """
    label = "左滑" if direction > 0 else "右滑"
    x_from, x_to = SWIPE_LEFT if direction > 0 else SWIPE_RIGHT
    steps, wraps = [], []
    how = "max_steps"
    cur = start
    seen = {int(cur["party"])}
    for i in range(1, int(max_steps) + 1):
        adb_swipe(page, x_from, x_to, y, ms)
        nxt = read(page)
        tag = f"{label}#{i}"
        steps.append((tag, nxt))
        if nxt["set"] is None or nxt["party"] is None:
            print(f"{tag:<8} {_fmt(nxt)}  ← 读数不完整（SET/Party 读不到）", flush=True)
            how = "unreadable"
            break
        if nxt["set"] != first_set:
            print(f"{tag:<8} {_fmt(nxt)}  ← SET 变了 {first_set} -> {nxt['set']}（换页了）", flush=True)
            how = "set_changed"
            break
        delta = int(nxt["party"]) - int(cur["party"])
        note = f"({delta:+d})" if delta == direction else ""
        if delta == 0:
            print(f"{tag:<8} {_fmt(nxt)}  ← {label}不动：Party 停在 {cur['party']}（边界）", flush=True)
            how = "clamped"
            break
        if abs(delta) > 1:
            wraps.append((cur["party"], nxt["party"]))
            note = f"← 跳了 {delta:+d} 格 {cur['party']}->{nxt['party']}（绕过边界：循环）"
        elif delta != direction:
            note = f"← 未按方向 {delta:+d}"
        print(f"{tag:<8} {_fmt(nxt)}  {note}", flush=True)
        if int(nxt["party"]) in seen:
            how = "cycle"
            break
        seen.add(int(nxt["party"]))
        cur = nxt
    return steps, how, wraps


def run_sweep(page, ms=450, max_steps=20):
    """``--sweep``：左滑到底再右滑到底，标定 Party 的上下界与是否循环（#124）。"""
    first = read(page)
    print(f"起点读数：{_fmt(first)}（滑动行 y={first['y']}）", flush=True)
    if first["set"] is None or first["party"] is None:
        print("x 读不到 SET / Party（不在 A 类战前编队页？）", flush=True)
        return 2
    y = _row_y(first)

    trace = [("起点", first)]
    edge = {}
    all_wraps = []
    # 左滑（Party +1）走一圈看**上界**；右滑（Party −1）走一圈看**下界**。
    for phase, direction in (("上界", 1), ("下界", -1)):
        label = "左滑" if direction > 0 else "右滑"
        print(f"\n=== {phase}标定：一路{label}（Party {'+1' if direction > 0 else '−1'}）===", flush=True)
        cur = trace[-1][1]
        steps, how, wraps = _sweep_one(page, y, direction, ms, max_steps, first["set"], cur)
        trace.extend(steps)
        all_wraps.extend(wraps)
        edge[phase] = {"how": how, "party": steps[-1][1]["party"] if steps else cur["party"]}
        if how == "max_steps":
            print(f"（{label} {max_steps} 步仍未走完一圈 —— 用 --max-steps 加大再测）", flush=True)
        if how == "cycle":
            print(f"（{label}已走完一整圈，回到本轮起点 Party={cur['party']}）", flush=True)

    print("\n=== 全轨迹 ===", flush=True)
    for tag, st in trace:
        print(f"{tag:10s} SET={st['set']} Party={st['party']} 战力={st['power']}", flush=True)

    parties = [st["party"] for _tag, st in trace if st["party"] is not None]
    distinct = sorted(set(parties))
    sets = {st["set"] for _tag, st in trace}
    print(flush=True)
    print(f"观测：Party 轨迹 {parties}", flush=True)
    print(f"观测：单方向走过的取值 = {distinct}（共 {len(distinct)} 个）", flush=True)
    print(f"观测：下界 = {min(parties)}（右滑止于 {edge['下界']['how']}）", flush=True)
    print(f"观测：上界 = {max(parties)}（左滑止于 {edge['上界']['how']}）", flush=True)
    if all_wraps:
        print(f"观测：是否循环 = 是 —— 回绕点 {all_wraps}（越过边界直接回到另一端）", flush=True)
    else:
        print("观测：是否循环 = 否（没有回绕，到边就夹住）", flush=True)
    unreadable = [tag for tag, st in trace if st["party"] is None]
    print(f"观测：边界处读数 = {'读不到 Party 的步骤 ' + str(unreadable) if unreadable else '始终读得到 SET/Party（无异常）'}", flush=True)
    if len(sets) == 1:
        print(f"观测：SET 始终 {first['set']}", flush=True)
    else:
        print(f"观测：SET 变过 {sorted(str(s) for s in sets)}", flush=True)
    print(json.dumps(trace, ensure_ascii=False), flush=True)
    return 0


def run_switch_party(page, target, clamp=False):
    """``--target N``：#124 的 ``switch_party`` 真机入口（adb 滑动 + 当帧 OCR 读数）。

    ★``clamp=False``（默认）时越界目标在 ``switch_party`` 里**一步不滑**就失败★（存在性判断在
    任何读帧 / 滑动之前）；真要把 11 夹成 10，必须人显式加 ``--clamp``，日志会打印夹紧结果。
    """
    import team_impl as ti  # noqa: PLC0415

    def read_hook():
        state, _items = page.team_read()
        return state

    def swipe_hook(x_from, x_to, y, ms):
        # 节拍（每步 1.6s）由 switch_party 统一管，这里只负责把 adb 命令发出去。
        adb_swipe(page, x_from, x_to, y, ms, settle=0)

    if not clamp and not ti.party_target_ok(target):
        # 连设备都不用碰：先把「目标不存在」说清楚（真机 1..10 环形轮播）。
        print(
            f"x 目标 Party {target} 不存在（真机轮播 1..{ti.TEAM_PARTY_COUNT}）—— 一步没滑"
            f"（确实要夹紧请显式加 --clamp）",
            flush=True,
        )
        return 2
    print(
        f"执行 team_impl.switch_party({target}"
        f"{', clamp=True' if clamp else ''})（横向滑动 + 三重校验）……",
        flush=True,
    )
    ok = ti.switch_party(target, swipe_hook=swipe_hook, read_hook=read_hook, clamp=clamp)
    print(f"\nswitch_party({target}) = {ok}", flush=True)
    return 0 if ok else 1


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default="127.0.0.1:16384")
    ap.add_argument(
        "--from",
        dest="pfrom",
        type=int,
        default=None,
        help="标定起点 Party（缺省=当帧读数；只和 --to 一起用）",
    )
    ap.add_argument(
        "--to",
        type=int,
        default=None,
        help="标定终点 Party：从起点逐步滑过去，每步打印读数（测上下界 / 是否循环）",
    )
    ap.add_argument(
        "--target",
        type=int,
        default=None,
        help="直接跑 team_impl.switch_party(target)：横向滑动 + 三重校验（#124 真机入口）",
    )
    ap.add_argument(
        "--clamp",
        action="store_true",
        help="显式请求把越界目标夹到 1..10（默认关：越界直接失败、一步不滑）",
    )
    ap.add_argument("--ms", type=int, default=450, help="单次 adb swipe 时长（毫秒）")
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="标定 Party 上下界 / 是否循环：从当帧左滑走一圈，再右滑走一圈",
    )
    ap.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="--sweep 单方向最多滑几次（默认 20；没到边会提示加大）",
    )
    a = ap.parse_args()
    if a.pfrom is not None and a.to is None and a.target is None and not a.sweep:
        print("x --from 需要和 --to 一起用（只给起点不知道往哪走）", flush=True)
        return 2
    if a.target is not None and not a.clamp:
        # ★#124 真机后续①★ 越界目标**连设备都不连**：先判存在性（真机 1..10 环形轮播），
        #   默认绝不夹紧。要夹紧请显式 --clamp（会打印夹紧结果）。
        import team_impl as ti  # noqa: PLC0415

        if not ti.party_target_ok(a.target):
            print(
                f"x 目标 Party {a.target} 不存在（真机轮播 1..{ti.TEAM_PARTY_COUNT}）—— 一步没滑"
                f"（确实要夹紧请显式加 --clamp）",
                flush=True,
            )
            return 2
    page = Page(a.address)
    try:
        if a.sweep:
            return run_sweep(page, a.ms, a.max_steps)
        if a.target is not None:
            return run_switch_party(page, a.target, clamp=a.clamp)
        if a.to is not None:
            return run_walk(page, a.pfrom, a.to, a.ms)
        return run_demo(page, a.ms)
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
