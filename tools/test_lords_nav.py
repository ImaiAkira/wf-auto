# -*- coding: utf-8 -*-
"""离线单测：领主战「全难度解禁」的**导航真源** ``scene/lords_nav.py``（#100 第 1、2 条缺口）。

跑：

    .venv\\Scripts\\python.exe tools\\test_lords_nav.py

★纯单测★：不碰设备、不读 pipeline、不 import ``maa``；只用**仓内真机帧的逐条读数**
（720 空间）当注入样例。覆盖：

1. **数据出处**：``LORD_TABS`` 与 ``scene.lords.SUBFAMILY_BY_KIND`` 同一个词表；
   页签判据 === ``scene.page_rules`` 的对应规则（ADR-0003：引用不复制）；
   **点击点 = 真机帧里标签框的中心**（1080 → 720 ÷1.5，与 ``SpecialTab*`` 的实测点击点对账）；
   滚动几何 = ``SpecialScrollList`` 的真机数字（400px / 800ms / 2600ms / 列表体 440~1180）；
   时间闩 ≥1.2s；每页滚动上限有界。
2. **页签确认**：★两个标签常驻同屏 ⇒ 「读得到标签」不算确认★；确认只认**行族身份证据**
   （真源 ``kind`` + ``row_regex``）。正例 / 矛盾 / 证据不足 / 详情页 / 未知行逐条覆盖。
3. **页签切换判决**：已在目标页签 → ``ok``；需要切 → ``click``（点当帧框）；**只许点 1 次**
   （第二次起 ``give_up`` → 回枢纽；再下一次 ``stop`` → 带原因收工，= #19 的反面）；
   不在列表页 / 读不到标签框 → ``cannot``（不盲点）；确认后重试计数清零。
4. **到底判定**：★「连续 2 次」= 连续 2 个**滚动世代**★（同一世代只记一次、没真的滚过不记账、
   空帧不算）：滚动后「没有新行 ∧ 纵向位移 ≤4px」连续 2 个世代 → 到底；
   有新行 / 有位移 / 同屏重复读 / 一次没滚过 → 不算；尾部锚点命中 → 立刻到底。
5. **滚动闸**：时间闩（≥1.2s）、到底、每页上限（用尽**带原因收工**，不是静默跳过）、
   页签未确认不许滚、目标行已在屏上不许滚（#29：选行先于滚动）。
6. **累计读数（R1）**：键 = ``(行名, N/M)`` 只用于「本帧新不新」，累计表按**行名**留**最新**
   读数；喂 ``1/4`` + ``2/4`` ⇒ 目标**不得**是已通关的「高级」；含一条破坏实验
   （退回按 ``row_key`` 累计 → 目标落回「高级」、报 duplicate_row = 必须被抓到）。
7. **扫描进度（R2）**：页签顺序推进 → 两个扫完 → ``sweep_done``；下一轮（``round_index`` 前进）
   ``begin_round`` 必须**重新武装**（``desired_tab() == LORD_TABS[0]``、累计清空），
   含一条破坏实验（``begin_round`` 只 ``reset_page`` → ``desired_tab() is None``、
   ``advance_tab`` 立刻谎报「两个都扫到底」= 必须被抓到）；
   「无进展死线」给出带原因的收工理由。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scene import lords_nav as nav  # noqa: E402
from scene.lords import LORDS, SUBFAMILY_BY_KIND  # noqa: E402
from scene.lords_unlock import RowReading, group_progress_rows, plan_round  # noqa: E402
from scene.page_rules import page_rule  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 注入样例：真机帧的逐条 OCR 读数（720 空间）
# ---------------------------------------------------------------------------
#: 领主战页签帧（``tools/frames/lord_page_tab_lord.png``，1080 空间 ÷1.5）。
#: 页签标签的原始读数（1080 空间，逐字照抄 docs/research/lord-battle-difficulty-registry.md §2.1）：
#:   领主战（页签）[202, 582, 135, 52] score 0.9998 / 降临讨伐（页签）[722, 584, 175, 50] score 0.9997
FRAME_TAB_LORD: tuple = (
    ("领主战", [135, 388, 90, 35]),
    ("降临讨伐", [481, 389, 117, 33]),
    ("更新列表", [615, 328, 82, 28]),
    ("通过房间号码参加", [187, 508, 259, 32]),
    ("艾基尔·嫉妒讨伐", [202, 640, 197, 28]), ("通关数1/4", [547, 688, 127, 28]),
    ("猩红巨熊讨伐", [201, 783, 164, 28]), ("通关数3/4", [547, 832, 126, 28]),
    ("背鳍三兄弟讨伐", [203, 928, 190, 28]), ("通关数1/4", [547, 976, 126, 28]),
    ("八岐大蛇讨伐", [201, 1072, 165, 28]), ("通关数4/4", [547, 1120, 126, 28]),
)

#: 降临讨伐页签帧（``tools/frames/lord_page_tab_joss.png``，÷1.5）。
#: ★``五王连战`` 不是本 family 的成员（它是五重决战）⇒ 只能进 ``unknown_rows``，不参与确认★。
FRAME_TAB_JOSS: tuple = (
    ("领主战", [135, 388, 90, 35]),
    ("降临讨伐", [481, 389, 117, 33]),
    ("更新列表", [615, 328, 82, 28]),
    ("五王连战", [201, 637, 115, 32]), ("通关数1/1", [547, 688, 123, 28]),
    ("无猾机兵", [201, 781, 114, 33]), ("通关数5/5", [547, 832, 127, 28]),
    ("红嫉机兵", [201, 925, 114, 33]), ("通关数4/4", [547, 976, 126, 28]),
    ("苍叹机兵", [201, 1069, 114, 33]), ("通关数4/4", [547, 1120, 126, 28]),
)

#: 详情页（判据 ``推荐编成``；★没有 ``更新列表``★ ⇒ 不是列表页）。
FRAME_DETAIL: tuple = (
    ("推荐编成", [37, 353, 65, 20]),
    ("妖狐超级", [135, 305, 169, 19]), ("战斗", [58, 334, 21, 11]),
    ("妖狐中级", [135, 687, 169, 19]), ("战斗", [60, 715, 18, 11]),
)

#: ★加载 / 过场帧★（真机 484，14:5x）：``--home`` 把设备送回主城后**立刻**跑
#: ``--trace LordsEntry``，刚回主城那几秒读到的就是它。判据与 ``common.json::PubLoadingText``
#: 同一条文案（「请耐心等待」，``PubLoadingWait`` 的子识别）。
FRAME_LOADING: tuple = (("请耐心等待", [300, 600, 200, 40]),)

#: 带百分比的加载页（另一帧真机读数 ``请耐心等待 79.28%``，见 ``scene/auto_switch.py``）——
#: 锚点是**子串**，所以这一帧也必须认。
FRAME_LOADING_PCT: tuple = (("请耐心等待 79.28%", [300, 600, 260, 40]),)

#: ★认不出的帧★（半渲染 / 转场）：必须还是 ``lords_unknown``（不猜）。
FRAME_UNKNOWN: tuple = (("Foo", [10, 10, 20, 20]),)


def rows_of(frame) -> tuple:
    """一帧 OCR 项 → 行读数（走真源 ``group_progress_rows``，与运行期同一个入口）。"""
    rows, _orphans = group_progress_rows(frame)
    return rows


def shifted(frame, dy: int) -> tuple:
    """把一帧的**框整体上移** ``dy`` 像素（模拟「列表真的滚下去了」）。"""
    return tuple((text, [box[0], box[1] - dy, box[2], box[3]]) for text, box in frame)


def reading(name: str, n: int, m: int) -> RowReading:
    """一条行读数（框是同尺寸占位；本文件只关心 name/n/m 与「有没有框」）。"""
    return RowReading(name, n, m, (0, 0, 1, 1), (0, 0, 1, 1))


# ---------------------------------------------------------------------------
# 1. 数据出处
# ---------------------------------------------------------------------------
def test_provenance() -> None:
    print("[1] 数据出处（判据/数字都是从仓内引用的，不是发明的）")

    check(
        "LORD_TABS == SUBFAMILY_BY_KIND 的值域（同一个词表，不是第二份）",
        set(nav.LORD_TABS) == set(SUBFAMILY_BY_KIND.values()),
        f"{nav.LORD_TABS} vs {tuple(SUBFAMILY_BY_KIND.values())}",
    )
    check(
        "LORD_TABS 顺序 = 界面从左到右（领主战 在 降临讨伐 左边）",
        nav.LORD_TABS.index("领主战") < nav.LORD_TABS.index("降临讨伐"),
    )

    # 页签判据必须**逐字段等于** page_rules（ADR-0003：引用不复制）
    for tab, page in (("领主战", "领主战页签"), ("降临讨伐", "降临讨伐页签")):
        rule = page_rule(page)
        param = rule.recognition.get("param") or {}
        anchor = nav.TAB_ANCHORS[tab]
        check(
            f"「{tab}」判据 == scene.page_rules::{page}",
            tuple(param.get("expected") or ()) == anchor.expected
            and tuple(param.get("roi") or ()) == anchor.roi,
            f"expected={anchor.expected} roi={anchor.roi}",
        )

    # ★点击点 = 真机帧里标签框的中心★（1080 → 720 ÷1.5；与 SpecialTab* 的实测点击点对账）
    frame_1080 = {
        "领主战": (202, 582, 135, 52),        # docs/research/lord-battle-difficulty-registry.md §2.1
        "降临讨伐": (722, 584, 175, 50),
    }
    for tab, (x, y, w, h) in frame_1080.items():
        cx, cy = (x + w / 2.0) / 1.5, (y + h / 2.0) / 1.5
        hx, hy = nav.TAB_ANCHORS[tab].click_hint
        check(
            f"「{tab}」点击点 == 真机帧标签框中心（÷1.5）",
            abs(cx - hx) <= 2.5 and abs(cy - hy) <= 2.5,
            f"帧中心 ({cx:.1f},{cy:.1f}) vs click_hint ({hx},{hy})",
        )
        rx, ry, rw, rh = nav.TAB_ANCHORS[tab].roi
        check(
            f"「{tab}」帧框中心落在它的 ROI 内",
            rx <= cx <= rx + rw and ry <= cy <= ry + rh,
            f"({cx:.1f},{cy:.1f}) ∈ [{rx},{ry},{rw},{rh}]",
        )

    # 两个标签在真机帧里**常驻同屏** —— 这条数据本身就是「标签不算确认」的依据
    check(
        "真机帧里两个页签标签同屏（⇒「读得到标签」不能当确认）",
        nav.tab_labels(FRAME_TAB_LORD) == frozenset({"领主战", "降临讨伐"})
        and nav.tab_labels(FRAME_TAB_JOSS) == frozenset({"领主战", "降临讨伐"})
        and nav.TAB_LABELS_ALWAYS_PRESENT,
    )

    plan = nav.SCROLL_PLAN
    check("滚动行程 = end.y - begin.y = 400px（SpecialScrollList 实测）", plan.begin[1] - plan.end[1] == plan.travel_px == 400)
    check("滚动**严格竖直**（dx=0；四元素写法会变成随机区域 = #42 真机事故）", plan.begin[0] == plan.end[0])
    check(
        "手势两端都落在列表体内（列表体 440~1180，#36）",
        plan.geometry_ok,
        f"begin={plan.begin} end={plan.end} body={plan.list_body}",
    )
    check("手势 800ms = 拖拽而不是甩动（#42）", plan.duration_ms == 800)
    check("滚完稳定等待 2600ms（= SpecialScrollList.post_delay，#42 惯性）", plan.settle_ms == 2600)
    check(
        "时间闩 ≥ 1.2s（本票硬要求）",
        plan.min_interval_sec >= 1.2,
        f"{plan.min_interval_sec}s",
    )
    check(
        "每页滚动上限有界且不荒谬（8..200）",
        8 <= plan.max_scrolls_per_page <= 200,
        f"{plan.max_scrolls_per_page} 次/页，整趟 {plan.max_scrolls_total}",
    )
    check("到底判据要求**连续 ≥2 次**无变化（一次可能是加载抖动）", plan.stable_times >= 2)
    check("「没动」阈值 4px（真机一次滚 400px，OCR 抖动 ≤2px，量级差 100 倍）", plan.no_move_px == 4)


# ---------------------------------------------------------------------------
# 2. 页签确认（只认行族身份证据）
# ---------------------------------------------------------------------------
def test_tab_state() -> None:
    print("[2] 页签确认（★两个标签常驻 ⇒ 只认行族身份证据★）")

    ev = nav.tab_state(FRAME_TAB_LORD)
    check("领主战帧 → confirmed=领主战", ev.confirmed == "领主战", f"{ev}")
    check("领主战帧 → 行族只有 lord", ev.kinds == ("lord",), f"{ev.kinds}")
    check("领主战帧 → 是列表页", ev.list_page)

    ev = nav.tab_state(FRAME_TAB_JOSS)
    check("降临讨伐帧 → confirmed=降临讨伐", ev.confirmed == "降临讨伐", f"{ev}")
    check("降临讨伐帧 → 行族只有 joss", ev.kinds == ("joss",), f"{ev.kinds}")
    check("五王连战（不是本 family 的成员）只进 unknown_rows", "五王连战" in ev.unknown_rows, f"{ev.unknown_rows}")

    # ★最关键的负例★：标签都在，但一行族证据都没有 ⇒ 不能确认（#19 的自我欺骗就在这里）
    labels_only = [item for item in FRAME_TAB_LORD if item[0] not in ("艾基尔·嫉妒讨伐", "猩红巨熊讨伐",
                                                                     "背鳍三兄弟讨伐", "八岐大蛇讨伐",
                                                                     "通关数1/4", "通关数3/4", "通关数4/4")]
    ev = nav.tab_state(labels_only)
    check(
        "只有页签标签 + 更新列表 → confirmed=None（★读得到标签 ≠ 选中它★）",
        ev.confirmed is None and ev.list_page and ev.labels == frozenset({"领主战", "降临讨伐"}),
        f"{ev}",
    )

    # 两族同屏 = 矛盾 ⇒ 不确认（宁可回枢纽，也不按猜的页签去点行）
    mixed = tuple(FRAME_TAB_LORD) + tuple(FRAME_TAB_JOSS)
    ev = nav.tab_state(mixed)
    check("两族行同屏（矛盾）→ confirmed=None", ev.confirmed is None, f"{ev}")

    ev = nav.tab_state(FRAME_DETAIL)
    check("详情页 → 不是列表页、也不确认", (not ev.list_page) and ev.confirmed is None, f"{ev}")

    ev = nav.tab_state([])
    check("空帧 → 什么都不确认", (not ev.list_page) and ev.confirmed is None and not ev.labels)

    only_unknown = (("更新列表", [615, 328, 82, 28]), ("某个新活动讨伐", [201, 783, 164, 28]))
    ev = nav.tab_state(only_unknown)
    check("只有花名册外的行 → confirmed=None + unknown 点名", ev.confirmed is None and "某个新活动讨伐" in ev.unknown_rows, f"{ev}")

    # 行名容错：真机把「红嫉机兵」读成「红嫉族机兵」（scene/lords.py 的 row_regex）
    check("行名容错 ^红嫉族?机兵$ 在归属时也生效", nav.tab_of_row("红嫉族机兵") == "降临讨伐")
    check("行名容错 ^红嫉族?机兵$ 反向同样成立", nav.tab_of_row("红嫉机兵") == "降临讨伐")
    check("花名册外的行 → 不猜页签", nav.tab_of_row("降临过伐") is None)


# ---------------------------------------------------------------------------
# 3. 页签切换判决（含切后确认 + 只许点 1 次）
# ---------------------------------------------------------------------------
def test_switch_decision() -> None:
    print("[3] 页签切换判决（★切后必须确认；失败只许 1 次，不重试★）")

    ev_lord = nav.tab_state(FRAME_TAB_LORD)
    box_joss = nav.label_box(FRAME_TAB_JOSS, nav.TAB_ANCHORS["降临讨伐"])

    # (a) 已在目标页签 → ok（且不动手）
    st = nav.NavState()
    dec = st.switch_decision(ev_lord, "领主战", None, 100.0)
    check("已在领主战 + 确认成立 → ok（不点）", dec.action == nav.ACTION_OK and dec.box is None, f"{dec}")

    # (b) 需要切：领主战帧上要降临讨伐 → click，点**当帧标签框**
    dec = st.switch_decision(ev_lord, "降临讨伐", box_joss, 101.0)
    check(
        "要切页签 → click，框 = 当帧标签框（不写死坐标）",
        dec.action == nav.ACTION_CLICK and dec.box == box_joss,
        f"{dec}",
    )
    check("点一次后 attempts=1（= 上限，不许再来一次）", st.switch_attempts == nav.TAB_SWITCH_MAX_ATTEMPTS)

    # (c) 仍未确认（同一帧再判一次）→ give_up（回枢纽，不重试）
    dec = st.switch_decision(ev_lord, "降临讨伐", box_joss, 102.0)
    check(
        "点过 1 次仍未确认 → give_up（回枢纽，不重试，= #19 的反面）",
        dec.action == nav.ACTION_GIVE_UP and dec.box is None and "不重试" in dec.reason,
        f"{dec.action} / {dec.reason}",
    )
    check(
        "宽限期内（<4s）连判几次都不累计「未确认」—— 慢帧不许把任务判死",
        st.unconfirmed == 0,
        f"unconfirmed={st.unconfirmed}",
    )

    # (d) 宽限期过后仍不确认 → 计数；连续 2 次 → stop（带原因收工，防 #19 竞速空转）
    t = 101.0 + nav.TAB_CONFIRM_GRACE_SEC + 0.5
    dec = st.switch_decision(ev_lord, "降临讨伐", box_joss, t)
    check("宽限期后仍未确认 → 记 1 次，仍是 give_up（回枢纽）",
          dec.action == nav.ACTION_GIVE_UP and st.unconfirmed == 1, f"{dec.action} / {st.unconfirmed}")
    dec = st.switch_decision(ev_lord, "降临讨伐", box_joss, t + 1.0)
    check(
        "连续 2 次未确认 → stop（带原因收工）",
        dec.action == nav.ACTION_STOP and "收工" in dec.reason,
        f"{dec.action} / {dec.reason}",
    )

    # (e) 确认之后计数清零（下一轮该切的时候还能切一次）
    st2 = nav.NavState()
    st2.switch_decision(ev_lord, "降临讨伐", box_joss, 100.0)          # 点一次
    st2.switch_decision(nav.tab_state(FRAME_TAB_JOSS), "降临讨伐", None, 101.0)  # 确认上了
    check("确认成功后 attempts 归零（下一轮还能切一次）", st2.switch_attempts == 0 and st2.unconfirmed == 0)

    # (f) 不在列表页 → cannot（绝不盲点：主城/详情页的同名标签位置完全不同）
    st3 = nav.NavState()
    dec = st3.switch_decision(nav.tab_state(FRAME_DETAIL), "降临讨伐", box_joss, 100.0)
    check("不在列表页 → cannot，且**不消耗**尝试次数", dec.action == nav.ACTION_CANNOT and st3.switch_attempts == 0, f"{dec}")

    # (g) 读不到标签框 → cannot（不盲点）
    st4 = nav.NavState()
    dec = st4.switch_decision(ev_lord, "降临讨伐", None, 100.0)
    check("读不到标签框 → cannot（不盲点）", dec.action == nav.ACTION_CANNOT and st4.switch_attempts == 0, f"{dec}")

    # (h) 没有目标页签 → cannot
    st5 = nav.NavState()
    dec = st5.switch_decision(ev_lord, None, None, 100.0)
    check("没有目标页签 → cannot", dec.action == nav.ACTION_CANNOT, f"{dec}")


# ---------------------------------------------------------------------------
# 4. 到底判定
# ---------------------------------------------------------------------------
def test_list_end() -> None:
    print("[4] 到底判定（「末行下方不再有新行」+ 纵向不动，连续 2 个**滚动世代**）")

    st = nav.NavState()
    page1 = rows_of(FRAME_TAB_LORD)
    at_end, why = st.observe(page1)
    check("首帧（上一帧为空）→ 不算到底", not at_end, why)

    # ★Item 7 的复现★：一次都没滚过时，「同一屏再读一遍」不许攒计数
    # （LordsScanPage 的 next 里有 [JumpBack]PubLoadingWait / PubDailyPopup，会把扫描节点弹回来重读）
    at_end, why = st.observe(page1)
    check(
        "同一屏重读（本页一次都没滚过）→ 不算到底，也不攒计数（修前：两帧就判到底）",
        (not at_end) and st.stable_scrolls == 0,
        why,
    )

    st.note_scroll(1.0)                                 # 真的滚了第 1 次 ⇒ 世代 1
    at_end, why = st.observe(page1)
    check("滚过 1 次后同屏（无新行、无位移）→ 第 1 个世代计数，还不算到底", not at_end and st.stable_scrolls == 1, why)
    at_end, why = st.observe(page1)
    check(
        "同一世代再读同一屏 → **不重复记账**（弹窗/加载把扫描节点弹回来也不会凑数）",
        (not at_end) and st.stable_scrolls == 1,
        why,
    )
    st.note_scroll(2.0)                                 # 第 2 次真的滚 ⇒ 世代 2
    at_end, why = st.observe(page1)
    check(
        "连续 2 个滚动世代都无变化 → 到底，且原因里带量（可复核）",
        at_end and "新行" in why and "位移" in why,
        why,
    )

    # 真的滚了（整屏上移 400px = 换了内容）→ 不能判到底
    st2 = nav.NavState()
    st2.observe(page1)
    st2.note_scroll(10.0)
    shifted_frame = tuple(
        (text, [box[0], box[1] - 400, box[2], box[3]]) for text, box in FRAME_TAB_LORD
    )
    # ★#100 真机改判（2026-10-18，484）★
    #   真机日志：`本帧 5 行（新 0 / 重复 5，累计 6）… 纵向位移 432px（连续无变化 0/2 次）`，
    #   连滚 39 次都这样。同样的 5 行 + 零新行 + 位移恒定 = **到底后的橡皮筋回弹**
    #   （真实长列表滚 400px 必然带出新行，所以「同样的行」只能意味着没内容了）。
    #   旧断言「位移太大 ⇒ 不算到底」把这个状态永远判成「没到底」⇒ 无限滚动。
    at_end1, why1 = st2.observe(rows_of(shifted_frame))   # 第 1 代：只记 1 次
    st2.note_scroll(11.0)
    at_end2, why2 = st2.observe(rows_of(shifted_frame))   # 第 2 代：达 stable_times
    check(
        "同样的行整体上移但**零新行**（= 到底回弹）→ 连 2 代算到底，原因里带位移",
        (not at_end1) and at_end2 and "位移" in why2,
        why2,
    )

    # 滚动了一次但它只是「滑了一点点」：有新行 ⇒ 也不算到底
    st3 = nav.NavState()
    st3.observe(page1)
    st3.note_scroll(20.0)
    partial = tuple(FRAME_TAB_LORD) + (
        ("妖狐讨伐", [201, 1216, 165, 28]),
        ("通关数2/4", [547, 1264, 126, 28]),
    )
    at_end, _why = st3.observe(rows_of(partial))
    check("滚出 1 个新行 → 不算到底（还有没读到的行）", not at_end)

    # 尾行还在往下走（出现新行）→ 一直不算到底
    check("出现新行就重置「无变化」计数", st3.stable_scrolls == 0)

    # 空帧：一行都读不到时判不了「列表没动」（那一帧可能根本不是列表页）
    st_empty = nav.NavState()
    st_empty.observe(page1)
    st_empty.note_scroll(30.0)
    at_end, why = st_empty.observe(())
    check("空帧（一行 `通关数` 都没读到）→ 不能当「列表没动」", (not at_end) and st_empty.stable_scrolls == 0, why)

    # 尾部锚点（机制已接好；当前 END_ANCHORS 为空 = 仓内没有滚到底的帧，不猜文案）
    check("END_ANCHORS 当前为空（诚实空缺：仓内没有列表底部的真机帧）", nav.END_ANCHORS == ())
    st4 = nav.NavState()
    at_end, why = st4.observe(rows_of(FRAME_TAB_LORD), anchor_hit="已无更多")
    check("注入尾部锚点命中 → 立刻到底", at_end and "已无更多" in why, why)
    check("锚点命中不依赖「连续 2 次」", st4.at_end())

    # end_anchor_hit 的机制：END_ANCHORS 为空时恒 None（不猜不存在的文案）
    check("END_ANCHORS 为空 ⇒ end_anchor_hit 恒 None", nav.end_anchor_hit(FRAME_TAB_LORD) is None)


# ---------------------------------------------------------------------------
# 5. 滚动闸（时间闩 / 到底 / 上限 / 页签 / 选行优先）
# ---------------------------------------------------------------------------
def test_scroll_gate() -> None:
    print("[5] 滚动闸（时间闩 + 到底判据 + 上限兜底 + 页签确认 + 选行优先）")

    plan = nav.SCROLL_PLAN
    rows = rows_of(FRAME_TAB_LORD)
    ok_args = dict(confirmed="领主战", desired="领主战", target_visible=False, scanning=True)

    st = nav.NavState()
    st.observe(rows)
    allowed, why = st.may_scroll(1000.0, **ok_args)
    check("首次（还没滚过）→ 可以滚", allowed, why)
    st.note_scroll(1000.0)
    allowed, why = st.may_scroll(1000.0 + plan.min_interval_sec - 0.1, **ok_args)
    check(
        "时间闩未到（<1.2s）→ 拒绝，且原因带「时间闩」",
        (not allowed) and "时间闩" in why,
        why,
    )
    allowed, why = st.may_scroll(1000.0 + plan.min_interval_sec + 0.01, **ok_args)
    check("时间闩满足 → 可以滚", allowed, why)

    # 到底 → 不再滚（★必须真的滚过 2 个世代★：同屏重读不算，见 item 7）
    st_end = nav.NavState()
    st_end.observe(rows)
    st_end.note_scroll(1990.0)
    st_end.observe(rows)
    st_end.note_scroll(1991.0)
    st_end.observe(rows)
    check("两个滚动世代都无变化 → 到底判据已成立（may_scroll 之前的前提）", st_end.at_end())
    allowed, why = st_end.may_scroll(2000.0, **ok_args)
    check("已到底 → 拒绝滚动（原因说「已到底」）", (not allowed) and "已到底" in why, why)

    # 页签未确认 → 先切页签（#19：在错的页签上滚 = 滚错列表）
    st_tab = nav.NavState()
    st_tab.observe(rows)
    allowed, why = st_tab.may_scroll(2000.0, **{**ok_args, "confirmed": "降临讨伐"})
    check("页签没确认到目标 → 拒绝滚动（先切页签）", (not allowed) and "页签" in why, why)

    # 目标行已在屏上 → 先选行（#29）
    st_pick = nav.NavState()
    st_pick.observe(rows)
    allowed, why = st_pick.may_scroll(2000.0, **{**ok_args, "scanning": False, "target_visible": True})
    check("目标行已在屏上 → 拒绝滚动（选行先于滚动，#29）", (not allowed) and "选行" in why, why)
    allowed, _why = st_pick.may_scroll(2000.0, **{**ok_args, "scanning": False, "target_visible": False})
    check("目标行不在屏上、非扫描期 → 允许滚（躲进列表找行）", allowed)

    # ★上限兜底★：用尽 → 明确要求「带原因收工」，不是静默跳过（#50 的反面）
    st_budget = nav.NavState()
    st_budget.observe(rows)
    st_budget.scrolls_in_page = plan.max_scrolls_per_page
    allowed, why = st_budget.may_scroll(3000.0, **ok_args)
    check(
        "每页滚动上限用尽 → 拒绝，且要求带原因收工（不是静默跳过）",
        (not allowed) and "收工" in why and "静默" in why,
        why,
    )
    check("上限 = 80 次/页，整趟 160 次（有界）", plan.max_scrolls_per_page == 80 and plan.max_scrolls_total == 160)


# ---------------------------------------------------------------------------
# 6. 去重
# ---------------------------------------------------------------------------
def test_dedup() -> None:
    print("[6] 去重（键 = 行名 + N/M；同一页里同一行只读一次）")

    st = nav.NavState()
    page1 = rows_of(FRAME_TAB_LORD)                     # 4 行（领主战页签）
    new, dup = st.add_rows(page1)
    check("首屏 4 行全部是新读数", len(new) == 4 and dup == (), f"new={new} dup={dup}")
    check("累计 4 行", len(st.rows()) == 4)

    # 滚动后上一屏的行还在屏上（重叠）→ 重复的必须被认出来
    overlap = rows_of(FRAME_TAB_LORD) + rows_of(FRAME_TAB_JOSS)[1:]
    new, dup = st.add_rows(overlap)
    check(
        "重叠帧：领主战那 4 行算重复，降临讨伐的 3 行（五王连战之后）算新",
        len(dup) == 4 and len(new) == 3,
        f"new={new} dup={dup}",
    )
    check("累计 7 行（领主战 4 + 降临讨伐 3；五王连战不在这张表里）", len(st.rows()) == 7)

    # 再喂一遍完全相同的两屏 → 全是重复，累计不变（★否则 plan_round 会把同一行读两遍★）
    new, dup = st.add_rows(tuple(page1) + rows_of(FRAME_TAB_JOSS)[1:])
    check("同样的两屏再读一遍 → 全部重复、累计不涨", new == () and len(dup) == 7 and len(st.rows()) == 7)

    # 键包含了 N/M：进度变了 = 本帧的新读数（真·新信息，不能吞）
    key_same = nav.row_key(RowReading("妖狐讨伐", 1, 4, (0, 0, 1, 1), (0, 0, 1, 1)))
    key_more = nav.row_key(RowReading("妖狐讨伐", 2, 4, (0, 0, 1, 1), (0, 0, 1, 1)))
    check("去重键 = (行名, N/M)", key_same == ("妖狐讨伐", "1/4"), f"{key_same}")
    check("N 变了 → 键不同（进度变化是真·新信息）", key_same != key_more, f"{key_same} vs {key_more}")
    check("容忍三元组输入", nav.row_key(("妖狐讨伐", 3, 4)) == ("妖狐讨伐", "3/4"))
    check("容忍映射输入", nav.row_key({"name": "妖狐讨伐", "n": 4, "m": 4}) == ("妖狐讨伐", "4/4"))

    # ------------------------------------------------------------------
    # ★R1 复现（修前这条是 FAIL）★：累计表按**行名**留**最新**读数，不是按 row_key 存多条
    # ------------------------------------------------------------------
    st2 = nav.NavState()
    st2.add_rows([reading("妖狐讨伐", 1, 4)])
    new, dup = st2.add_rows([reading("妖狐讨伐", 2, 4)])
    check(
        "同一行读到更高的进度 → **覆盖**成最新一条（累计里只有 1 条，别让 plan_round 取到旧的）",
        len(new) == 1 and dup == () and len(st2.rows()) == 1,
        f"new={new} dup={dup} rows={[(r.name, r.n, r.m) for r in st2.rows()]}",
    )
    check(
        "…留着的是**新**读数 2/4",
        (st2.rows()[0].n, st2.rows()[0].m) == (2, 4),
        f"{[(r.n, r.m) for r in st2.rows()]}",
    )
    new, dup = st2.add_rows([reading("妖狐讨伐", 1, 4)])
    check(
        "回读到更旧的读数（N 没变大）→ 算重复、**不覆盖**最新值",
        new == () and len(dup) == 1 and st2.rows()[0].n == 2,
        f"new={new} dup={dup} n={st2.rows()[0].n}",
    )

    # ★R1 的后果复现★：喂 1/4 + 2/4 → 目标**不得**是「高级」（那是已经通关的档）
    plan = plan_round(st2.rows(), LORDS)
    check(
        "★R1 复现★ 喂 1/4 + 2/4 → 本轮目标是「高级+」，**不是**已通关的「高级」",
        plan.pairs == (("妖狐讨伐", "高级+"),),
        f"{plan.pairs}",
    )
    check(
        "…且不报 duplicate_row（同一行不该有两个读数被一起喂进规划）",
        "duplicate_row" not in {p.kind for p in plan.problems},
        f"{[(p.kind, p.row_name) for p in plan.problems]}",
    )


class _ByRowKeyCumulative(nav.NavState):
    """★破坏实验 R1★：把累计退回**修前**的「按 ``row_key`` 存多条」形状（故意坏的）。

    它必须让上面那条「目标是高级+」的断言变红 —— 否则那条断言抓不住 R1 回归
    （旧形状下 ``plan_round`` 对同名行只取第一条 = 1/4 ⇒ 目标落回「高级」= 反复打刚打完的档）。
    """

    def add_rows(self, rows, *, now=None) -> tuple:
        new, dup = [], []
        for row in rows or ():
            key = nav.row_key(row)
            if key in self.seen:
                dup.append(key)
                continue
            self.seen[key] = row
            new.append(key)
        return (tuple(new), tuple(dup))


def test_breaker_r1() -> None:
    print("[6b] ★破坏实验 R1★：退回按 row_key 累计 → 目标落回已通关档（必须被抓到）")

    legacy = _ByRowKeyCumulative()
    legacy.add_rows([reading("妖狐讨伐", 1, 4)])
    legacy.add_rows([reading("妖狐讨伐", 2, 4)])
    legacy_plan = plan_round(legacy.rows(), LORDS)
    check(
        "破坏实验 R1：累计里留下 1/4 与 2/4 两条（这正是修前的形状）",
        len(legacy.rows()) == 2,
        f"{[(r.n, r.m) for r in legacy.rows()]}",
    )
    check(
        "破坏实验 R1：plan_round 取第一条 ⇒ 目标落回**已通关**的「高级」+ 报 duplicate_row"
        "（⇒ 上面 test_dedup 的断言抓得住这类回归）",
        legacy_plan.pairs == (("妖狐讨伐", "高级"),)
        and "duplicate_row" in {p.kind for p in legacy_plan.problems},
        f"{legacy_plan.pairs} / {[(p.kind, p.row_name) for p in legacy_plan.problems]}",
    )


# ---------------------------------------------------------------------------
# 7. 扫描进度 + 无进展死线
# ---------------------------------------------------------------------------
def test_sweep_and_stuck() -> None:
    print("[7] 扫描进度（两页签顺序推进）与无进展死线")

    st = nav.NavState()
    check("初始：该扫页（page_pending(0)）", st.page_pending(0))
    check("初始：目标页签 = 领主战", st.desired_tab() == "领主战")
    check("有目标行时：目标页签由**目标行族**决定（#19）", st.desired_tab("红嫉机兵") == "降临讨伐")

    done, why = st.advance_tab(10.0)
    check("领主战扫完 → 轮到降临讨伐", (not done) and st.desired_tab() == "降临讨伐" and "轮到" in why, why)
    check("换页签会清页内计数（切完视为新的一页；★待真机标定是否保留滚动位置★）",
          st.scrolls_in_page == 0 and st.stable_scrolls == 0 and st.last_rows == ())

    done, why = st.advance_tab(11.0)
    check("两个页签都扫完 → 扫描阶段结束", done and st.sweep_done and "扫描阶段结束" in why, why)
    check("扫描结束后没有目标页签", st.desired_tab() is None)

    st.complete_scan(0, 12.0)
    check("扫完一轮后：同一轮不再重扫（page_pending(0) 为假）", not st.page_pending(0))
    check("扫完一轮后：下一轮（round_index 前进）**该**重扫（D6「每轮重开列表」）", st.page_pending(1))

    # ★R2 复现（修前这条是 FAIL）★：page_pending(1) 为真但同时 desired_tab() 是 None
    # ⇒ 不切页签、页签闸被跳过、advance_tab 立刻谎报「两个页签都扫到底」。
    check(
        "★R2 前提★ 扫完一轮后扫描不进任何页签（desired_tab() 为空 = 修前的坑）",
        st.desired_tab() is None,
        f"{st.desired_tab()!r}",
    )
    st.seen["妖狐讨伐"] = reading("妖狐讨伐", 1, 4)
    st.begin_round(13.0)
    check(
        "★R2 复现★ 新一轮开始 → 扫描**重新武装**：desired_tab() == LORD_TABS[0]",
        st.desired_tab() == nav.LORD_TABS[0],
        f"{st.desired_tab()!r}",
    )
    check("…且这一轮确实要重扫（page_pending(1) 仍为真）", st.page_pending(1))
    check("…且累计读数被清空（R1 的「新一轮清累计」）", st.rows() == (), f"{st.rows()!r}")
    check("…且页内计数清零（begin_round 会 reset_page）", st.scrolls_in_page == 0 and st.stable_scrolls == 0)

    # 无进展死线
    st2 = nav.NavState()
    check("还没开始（last_progress_at=0）→ 不判卡死", st2.stuck_reason(100.0) == "")
    st2.note_progress(100.0)
    check("刚有进展 → 不判卡死", st2.stuck_reason(100.0 + nav.NAV_STUCK_SEC - 1) == "")
    reason = st2.stuck_reason(100.0 + nav.NAV_STUCK_SEC + 1)
    check("超过死线 → 给出带原因的收工理由", bool(reason) and "带原因收工" in reason, reason)

    st3 = nav.NavState()
    st3.observe(rows_of(FRAME_TAB_LORD))
    st3.note_scroll(500.0)
    check("滚动算「有进展」（会重置死线基准）", st3.stuck_reason(500.0 + nav.NAV_STUCK_SEC - 1) == "")


# ---------------------------------------------------------------------------
# 8. 花名册全量（页签归属对 46 个成员都成立）
# ---------------------------------------------------------------------------
def test_full_registry() -> None:
    print("[8] 全量扫描：46 个成员的页签归属都算得出来（且只用真源的 kind）")

    bad: list[str] = []
    for entry in LORDS:
        tab = nav.tab_of_row(entry.row_name)
        want = SUBFAMILY_BY_KIND.get(entry.kind)
        if tab != want:
            bad.append(f"{entry.row_name}:{tab}!={want}")
    check(f"全部 {len(LORDS)} 个成员的页签归属 = SUBFAMILY_BY_KIND[kind]", not bad, "；".join(bad[:5]))


class _NoRearmSweep(nav.NavState):
    """★破坏实验 R2★：``begin_round`` 只做 ``reset_page``（= **修前**形状：扫描不重新武装）。

    它必须让「``desired_tab() == LORD_TABS[0]``」那条断言变红 —— 否则那条断言抓不住 R2 回归
    （旧形状下第 2 轮 ``page_pending`` 为真、``desired_tab()`` 却是 None：不切页签、页签闸被
    跳过，``advance_tab`` 立刻宣布「两个页签都扫到底」，其实一个都没扫）。
    """

    def begin_round(self, now=None) -> None:
        self.reset_page()


def test_breaker_r2() -> None:
    print("[7b] ★破坏实验 R2★：扫描不复位 → 第 2 轮不切页签却「两个都扫完」（必须被抓到）")

    bad = _NoRearmSweep()
    bad.advance_tab(10.0)
    bad.advance_tab(11.0)
    bad.complete_scan(0, 12.0)
    bad.begin_round(13.0)
    check(
        "破坏实验 R2：扫描不复位 ⇒ 第 2 轮 desired_tab() 仍是 None（不切页签 = 页签闸被跳过）",
        bad.desired_tab() is None,
        f"{bad.desired_tab()!r}",
    )
    done, why = bad.advance_tab(14.0)
    check(
        "破坏实验 R2：…⇒ advance_tab 立刻谎报「两个页签都扫到底」"
        "（⇒ 上面 test_sweep_and_stuck 的 desired_tab 断言抓得住这类回归）",
        done and "两个页签都扫到底" in why,
        why,
    )


def test_loading_transition() -> None:
    print("[9] ★过渡态★加载 / 过场帧有自己的名字（lords_loading），不进「无进展」死线的计时")

    check(
        "lords_loading 在状态词表里（词表仍全部 lords_*）",
        nav.LORDS_STATE_LOADING == "lords_loading"
        and nav.LORDS_STATE_LOADING in nav.LORDS_STATES
        and all(str(name).startswith("lords_") for name in nav.LORDS_STATES),
        f"{nav.LORDS_STATES!r}",
    )
    check(
        "加载帧 → lords_loading（不是 lords_unknown）",
        nav.page_state(FRAME_LOADING) == nav.LORDS_STATE_LOADING,
        f"got={nav.page_state(FRAME_LOADING)!r}",
    )
    check(
        "带百分比的加载帧也算（锚点是子串：请耐心等待 79.28%）",
        nav.page_state(FRAME_LOADING_PCT) == nav.LORDS_STATE_LOADING,
        f"got={nav.page_state(FRAME_LOADING_PCT)!r}",
    )
    check(
        "loading_frame() 判据对两帧都成立、对普通帧不成立",
        nav.loading_frame(FRAME_LOADING)
        and nav.loading_frame(FRAME_LOADING_PCT)
        and not nav.loading_frame(FRAME_TAB_LORD)
        and not nav.loading_frame(FRAME_DETAIL),
        f"anchors={nav.LORDS_LOADING_ANCHORS!r}",
    )
    check(
        "锚点与项目唯一一份画面分类同口径（请耐心等待 = PubLoadingText；健康游戏忠告 = #119）",
        tuple(nav.LORDS_LOADING_ANCHORS) == ("请耐心等待", "健康游戏忠告"),
        f"got={nav.LORDS_LOADING_ANCHORS!r}",
    )
    check(
        "★认不出的帧仍是 lords_unknown★（不猜：半渲染帧不许被当成过渡态）",
        nav.page_state(FRAME_UNKNOWN) == nav.LORDS_STATE_UNKNOWN,
        f"got={nav.page_state(FRAME_UNKNOWN)!r}",
    )
    check(
        "过渡集 = (lords_loading, loading, relogin)",
        tuple(nav.LORDS_TRANSITION_STATES) == ("lords_loading", "loading", "relogin"),
        f"got={nav.LORDS_TRANSITION_STATES!r}",
    )
    check(
        "★lords_unknown / lords_list 都不在过渡集里★（未知画面与列表页的死线必须保留）",
        nav.LORDS_STATE_UNKNOWN not in nav.LORDS_TRANSITION_STATES
        and nav.LORDS_STATE_LIST not in nav.LORDS_TRANSITION_STATES,
        f"got={nav.LORDS_TRANSITION_STATES!r}",
    )
    check(
        "过渡集与 LORDS_ACTIVE_STATES（battle/settle）不相交 —— 两套排除口径分开",
        not (set(nav.LORDS_TRANSITION_STATES) & set(nav.LORDS_ACTIVE_STATES))
        and tuple(nav.LORDS_ACTIVE_STATES) == (nav.LORDS_STATE_BATTLE, nav.LORDS_STATE_SETTLE),
        f"{nav.LORDS_ACTIVE_STATES!r}",
    )
    check(
        "其它页面的判据没被加载判据抢走（列表页/详情页仍各自认得出）",
        nav.page_state(FRAME_TAB_LORD) == nav.LORDS_STATE_LIST
        and nav.page_state(FRAME_DETAIL) == nav.LORDS_STATE_DETAIL,
        f"{nav.page_state(FRAME_TAB_LORD)!r} / {nav.page_state(FRAME_DETAIL)!r}",
    )


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 72)
    print("scene/lords_nav.py 纯单测（#100 页签切换 + 列表滚动）")
    print("=" * 72)
    test_provenance()
    test_tab_state()
    test_switch_decision()
    test_list_end()
    test_scroll_gate()
    test_dedup()
    test_breaker_r1()
    test_sweep_and_stuck()
    test_breaker_r2()
    test_full_registry()
    test_loading_transition()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
