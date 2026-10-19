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
8. **屏幕边界**（#100 回归：解禁 0 场）：``on_screen`` 必须整框落在 720x1280 内 ——
   合成帧第 7/8 行（y=1324 / 1468）**不在屏上**（旧实现据「找到了框」断言「行就在屏上」，
   扫完即误收工）；真机行 / y=740 对照行仍在屏内；x 越界、y+h 越界、解不开的框一律不在屏上。
9. **列表行 ROI**（#100 第二轮验收，真机 484）：``ROW_ROI`` **引用** ``scene.options.TARGET_ROW_ROI``
   （不写第三份数字）并与 ``SCROLL_PLAN.list_body`` / 页签几何对齐；真机行框在 ROI 内，
   而模式页顶部领主名（中心 (346.5,201)）/ 页签 / 底栏一律**不是**列表行。
10. **放闩证据**（#100 第 3 轮验收，真机 484，``debug/lords_accept4.log``）：
    ``challenge_release_evidence`` = ``page_state`` **正向**落在
    ``LORDS_CHALLENGE_RELEASE_STATES``（battle / settle / list / detail / city / mode）；
    ★编队页 / loading / unknown 一律不是证据★（还停在编队页 = 可能没生效；转场/认不出 = 猜）。
    这是「点过【挑战】」的闩的**主路径**（见到即放），180s 超时只作兜底。
11. **详情页逐档状态（D6，同轮验收 17:19–17:40）**：每一档旁边有 ``COMPLETE!!``（已通关，
    真机有 ``MPLETE!!`` 弱读）或 ``NEW``（未通关）；判据 = **难度词表整串锚定**的行名 +
    徽标在档名**左侧、上方 ≤120px**（实测 ≈70px、行距 ≈190px）。选档只选**未通关**那一档
    （最上面已通关时**不选它**；显式目标档是 NEW 才优先）；**一档状态都读不到 ⇒ 不选**
    （绝不回到「取最上面那个战斗框」的旧行为）；全档 COMPLETE!! ⇒ ``all_complete``
    （不点任何档，由 agent 产出【返回】回列表）。回列表的【返回】只在详情页成立
    （列表页最左槽也是【返回】，不能当「离开列表」）。
12. **每页开扫前「回顶部」**（#100 第 6 轮真机验收，``debug/lords_accept6.log`` 18:40–18:47）：
    战后列表停在**被点行/最后 5 行**、切页签也保留滚动位置 —— 「到底」是**相对滚动位置**的
    概念，不回顶部，第二轮的「到底」毫无意义（真机第 2 轮只读到 4 行 / 目标 0）。判据 =
    连续 ``stable_times`` 个**回顶部世代**都「无新行 ∧ 纵向上移位移 ≤ no_move_px」⇒ 已到顶部；
    预算 ``max_rewinds_per_page``（有界，用尽**带原因收工**）；回顶部**只记自己的账**，
    不推进向下扫的滚动世代。另含「本轮扫描完整性账」（被剔行 / 未回顶 / 页签没切）——
    零目标收工的正确原因靠它。
13. **被徽标剔掉的行算「见到行」**（同轮验收）：只要这一帧有被剔的行，就**不许判「到底」**
    （丢的那行可能正是 ``N<M``）；连续两代「滚不动」⇒ ``bottom_unprovable``（底不可证，
    按扫描不完整收尾），``at_end()`` 仍是 False；对照帧（无徽标）两代仍判到底。
14. **扫描完整性账的作用域**（真机 484 第 7 轮验收，``debug/lords_accept7.log``）：agent 把
    ``round_gained`` 挪到 ``mode=end`` 的交接帧上，判据是「这一轮扫描完不完整」——
    ``begin_round`` 清零、``complete_scan`` **不清**、``scan_incomplete_reason`` 点名徽标剔除。
15. **行名被读成徽标 ⇒ 几何修复真名**（真机 484 accept7：「全部解禁」检测不到的结构性原因）：
    徽标属于**下一张卡**，比本卡真名更贴近本卡的「通关数」（dy 45.5 vs 48）⇒ 真名被挤掉。
    ``recover_badge_row_name`` 排除徽标/进度/页签/固定元素后按**同一条几何**找回真名
    （``ROW_ROI`` 限定列表体；★候选不按花名册筛★—— 不然 ``五王连战 1/1`` 这种活动行永远
    找不回来）；真机 5 行全 M/M 帧上修复后 ``all_done`` 可达，混合帧里被抢走的
    ``碧愁机兵 1/4`` 回到读数；真名读不出 ⇒ ``None``（安全线不松）。
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

#: 编队页（判据 = ``^挑战(→)?$`` 在底部按钮 ROI + 三个正向锚之一）。
FRAME_TEAM: tuple = (
    ("自动续战", [20, 1060, 80, 24]),
    ("挑战", [297, 1069, 80, 47]),
)

#: 战斗 HUD（判据 = ``And(时间 \d+:\d+, 分数 \d)``；裸「时间」/「分数」不算）。
FRAME_BATTLE: tuple = (
    ("时间 09:53", [100, 60, 120, 30]),
    ("分数 00000082254", [300, 60, 160, 30]),
)

#: 结算页（判据 = ``^继续$``）。
FRAME_SETTLE: tuple = (("继续", [320, 1100, 80, 40]),)


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
    check(
        "★每页「回顶部」预算有界（8..60；46 位成员 / 一次上滚露 ~2 行 ≈ 23）★",
        8 <= plan.max_rewinds_per_page <= 60,
        f"{plan.max_rewinds_per_page} 次/页",
    )


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

    # ★本票 c（#100 第 6 轮真机验收）★：被徽标剔掉的行**算「见到行」** —— 这一帧不许判到底
    #   （真机 484：每帧 4~5 行读成 COMPLETE!!，修前剔完就判「连续两帧无新行」= 假到底）。
    st_badge = nav.NavState()
    st_badge.observe(page1)                             # 世代 0
    st_badge.note_scroll(40.0)                          # 世代 1
    at_end, why = st_badge.observe(page1, dropped=2)
    check(
        "★有被剔行的一帧（哪怕列表真没动）→ 不判到底★（原因点名「不许判到底」）",
        (not at_end) and "不许判到底" in why and st_badge.dropped_in_scan == 2,
        why,
    )
    at_end, _why = st_badge.observe(page1, dropped=2)
    check("同一世代重复读 → 仍不判到底（被剔行不会被「没新行」吃掉）", not at_end)
    st_badge.note_scroll(41.0)                          # 世代 2
    at_end, why = st_badge.observe(page1, dropped=2)
    check(
        "两代「滚不动 + 有被剔行」→ **底不可证**（不是「到底」），但本页可收尾",
        (not at_end) and st_badge.bottom_unprovable and st_badge.page_finished()
        and "底不可证" in why,
        why,
    )
    check("★底不可证时 at_end() 仍是 False★（绝不宣布「到底」）", st_badge.at_end() is False)
    check(
        "扫描完整性账点名「有行被徽标剔除 N 行」",
        "有行被徽标剔除" in st_badge.scan_incomplete_reason(),
        st_badge.scan_incomplete_reason(),
    )
    st_clean = nav.NavState()
    st_clean.observe(page1)
    st_clean.note_scroll(50.0)
    st_clean.observe(page1)
    st_clean.note_scroll(51.0)
    at_end, _why = st_clean.observe(page1)
    check("对照：没有被剔行时两代仍判到底（徽标守卫不许把正常到底挡掉）", at_end)

    # 尾部锚点（机制已接好；当前 END_ANCHORS 为空 = 仓内没有滚到底的帧，不猜文案）
    check("END_ANCHORS 当前为空（诚实空缺：仓内没有列表底部的真机帧）", nav.END_ANCHORS == ())
    st4 = nav.NavState()
    at_end, why = st4.observe(rows_of(FRAME_TAB_LORD), anchor_hit="已无更多")
    check("注入尾部锚点命中 → 立刻到底", at_end and "已无更多" in why, why)
    check("锚点命中不依赖「连续 2 次」", st4.at_end())

    # end_anchor_hit 的机制：END_ANCHORS 为空时恒 None（不猜不存在的文案）
    check("END_ANCHORS 为空 ⇒ end_anchor_hit 恒 None", nav.end_anchor_hit(FRAME_TAB_LORD) is None)


# ---------------------------------------------------------------------------
# 4b. 每页扫描前「回顶部」（#100 第 6 轮真机验收：战后列表停在底部）
# ---------------------------------------------------------------------------
def test_rewind_to_top() -> None:
    print("[4b] ★每页开扫前回顶部★（有界 + 可验证；真机 484 第 6 轮：第 2 轮只读到 4 行）")

    # (a) 每一页开始都要**重新武装**（真机：战后停在最后 5 行、切页签也停在上次位置）
    st = nav.NavState()
    check("新 NavState：还没回顶部（rewind_pending）", st.rewind_pending() and not st.rewind_done)
    st.begin_round(1.0)
    check("begin_round 重新武装回顶部", st.rewind_pending())
    st.rewind_done = True
    st.advance_tab(2.0)
    check("advance_tab 到下一页 → 重新武装回顶部（第二页也从头扫）", st.rewind_pending())
    st.rewind_done = True
    st.reset_page()
    check("切页签（reset_page）→ 重新武装回顶部（切页签会保留滚动位置）", st.rewind_pending())

    # (b) 判据：上滚出现新行 = 没到顶；同屏两代 = 到顶（带滚了几次）
    top = rows_of(FRAME_TAB_LORD)
    bottom = rows_of(FRAME_TAB_JOSS)          # 另一批行 = 「上面还有没读到的行」
    st2 = nav.NavState()
    st2.begin_round(1.0)
    at_top, why = st2.observe_rewind(bottom)
    check("底部帧（世代 0）→ 不算到顶、也不记账", (not at_top) and st2.rewind_stable == 0, why)
    st2.note_rewind_scroll(2.0)
    at_top, why = st2.observe_rewind(top)
    check("上滚后出现新行 → 未到顶（继续向上滚）", (not at_top) and "新行" in why, why)
    st2.note_rewind_scroll(3.0)
    at_top, why = st2.observe_rewind(top)
    check("同屏第 1 代 → 未到顶（一次可能是抖动）", not at_top, why)
    st2.note_rewind_scroll(4.0)
    at_top, why = st2.observe_rewind(top)
    check(
        "连续 2 代无新行 / 无位移 → **已到顶部**，原因带「滚了几次 + 上限」",
        at_top and "已到顶部" in why and "上限" in why,
        why,
    )
    check(
        "回顶部**只记自己的账**（不推进向下扫的 scrolls_in_page / scroll_gen）",
        st2.rewind_scrolls == 3 and st2.scrolls_in_page == 0 and st2.scroll_gen == 0,
        f"rewind={st2.rewind_scrolls} scrolls={st2.scrolls_in_page} gen={st2.scroll_gen}",
    )

    # (c) 时间闩 + 预算（有界，用尽必须带原因收工）
    st3 = nav.NavState()
    st3.begin_round(1.0)
    allowed, why = st3.may_rewind(1.0)
    check("首次回顶部 → 可以滚", allowed, why)
    st3.note_rewind_scroll(1.0)
    allowed, why = st3.may_rewind(1.0 + nav.SCROLL_PLAN.min_interval_sec - 0.1)
    check("回顶部也有时间闩（<1.2s 不许连甩）", (not allowed) and "时间闩" in why, why)
    st3.rewind_scrolls = nav.SCROLL_PLAN.max_rewinds_per_page
    allowed, why = st3.may_rewind(100.0)
    check(
        "回顶部预算用尽 → 拒绝，且要求**带原因收工**（绝不无限上滚）",
        (not allowed) and "收工" in why,
        why,
    )
    st3.note_rewind_scroll(101.0)
    check("预算用尽后 rewind_failed 置位、rewind_pending 变假（交给收工出口）",
          st3.rewind_failed and not st3.rewind_pending())

    # (d) 空帧判不了「到顶」
    st4 = nav.NavState()
    st4.begin_round(1.0)
    at_top, why = st4.observe_rewind(())
    check("空帧（一行都读不到）→ 判不了到顶，不记账", (not at_top) and st4.rewind_stable == 0, why)

    # (e) 本轮扫描的**完整性账**（零目标收工的正确原因靠它）
    st5 = nav.NavState()
    st5.begin_round(1.0)
    st5.advance_tab(2.0)                       # 没确认到顶就推进下一页
    check("没确认到顶就收尾 → top_unconfirmed 记 1 页", st5.top_unconfirmed == 1)
    check(
        "扫描不完整原因点名「未确认回到顶部」",
        "未确认回到顶部" in st5.scan_incomplete_reason(),
        st5.scan_incomplete_reason(),
    )
    st5.note_tab_switch_failed()
    check("页签没切成功也进完整性账", "页签未切换" in st5.scan_incomplete_reason())
    check("scan_complete() 为假（有未确认的页）", st5.scan_complete() is False)
    st5.begin_round(3.0)
    check("begin_round 清空完整性账（新一轮从零算）", st5.scan_complete())


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


def test_challenge_release_evidence() -> None:
    print("[12] ★放闩证据★：点过【挑战】后见到 battle/settle 等正向页 ⇒ 立刻放（180s 只是兜底）")

    check(
        "证据集 = battle/settle/list/detail/city/mode（正向列举，不是「不是编队页」）",
        tuple(nav.LORDS_CHALLENGE_RELEASE_STATES)
        == (
            nav.LORDS_STATE_BATTLE,
            nav.LORDS_STATE_SETTLE,
            nav.LORDS_STATE_LIST,
            nav.LORDS_STATE_DETAIL,
            nav.LORDS_STATE_CITY,
            nav.LORDS_STATE_MODE,
        ),
        f"got={tuple(nav.LORDS_CHALLENGE_RELEASE_STATES)!r}",
    )
    check(
        "battle / settle 都在证据集里（本票点名的两条）",
        nav.LORDS_STATE_BATTLE in nav.LORDS_CHALLENGE_RELEASE_STATES
        and nav.LORDS_STATE_SETTLE in nav.LORDS_CHALLENGE_RELEASE_STATES,
    )
    check(
        "★team / loading / unknown 不在证据集里★（还停在编队页 / 转场 / 认不出 = 没有证据）",
        not (
            {nav.LORDS_STATE_TEAM, nav.LORDS_STATE_LOADING, nav.LORDS_STATE_UNKNOWN}
            & set(nav.LORDS_CHALLENGE_RELEASE_STATES)
        ),
        f"got={tuple(nav.LORDS_CHALLENGE_RELEASE_STATES)!r}",
    )

    check(
        "战斗帧 ⇒ lords_battle",
        nav.challenge_release_evidence(FRAME_BATTLE) == nav.LORDS_STATE_BATTLE,
        f"got={nav.challenge_release_evidence(FRAME_BATTLE)!r}",
    )
    check(
        "结算帧 ⇒ lords_settle",
        nav.challenge_release_evidence(FRAME_SETTLE) == nav.LORDS_STATE_SETTLE,
        f"got={nav.challenge_release_evidence(FRAME_SETTLE)!r}",
    )
    check(
        "点挑战后回到列表页 ⇒ lords_list（这一场早结束了）",
        nav.challenge_release_evidence(FRAME_TAB_LORD) == nav.LORDS_STATE_LIST,
        f"got={nav.challenge_release_evidence(FRAME_TAB_LORD)!r}",
    )
    check(
        "详情页 ⇒ lords_detail",
        nav.challenge_release_evidence(FRAME_DETAIL) == nav.LORDS_STATE_DETAIL,
        f"got={nav.challenge_release_evidence(FRAME_DETAIL)!r}",
    )
    check(
        "★编队页 ⇒ 空串★（这一下可能没生效，必须继续等；禁双击）",
        nav.challenge_release_evidence(FRAME_TEAM) == "",
        f"got={nav.challenge_release_evidence(FRAME_TEAM)!r}",
    )
    check(
        "★加载帧 / 认不出的帧 ⇒ 空串★（转场/未知不是「已离开编队页」的证据，宁可多等兜底）",
        nav.challenge_release_evidence(FRAME_LOADING) == ""
        and nav.challenge_release_evidence(FRAME_LOADING_PCT) == ""
        and nav.challenge_release_evidence(FRAME_UNKNOWN) == "",
        f"got={[nav.challenge_release_evidence(f) for f in (FRAME_LOADING, FRAME_UNKNOWN)]!r}",
    )
    check(
        "空帧 / None ⇒ 空串（不抛异常、不猜）",
        nav.challenge_release_evidence(()) == "" and nav.challenge_release_evidence(None) == "",
    )


def test_screen_bounds() -> None:
    print("[10] ★屏幕边界★：「行在屏上」必须整框落在 720x1280 内（#100 解禁 0 场的回归）")

    from scene.pixels import BASE_H, BASE_W

    check(
        "SCREEN_W / SCREEN_H 引用 scene/pixels 的基准空间（不是第二份数字）",
        (nav.SCREEN_W, nav.SCREEN_H) == (BASE_W, BASE_H),
        f"({nav.SCREEN_W}, {nav.SCREEN_H}) vs ({BASE_W}, {BASE_H})",
    )
    check(
        "真机列表行（202,640,197,28）在屏上",
        nav.on_screen((202, 640, 197, 28)) is True,
    )
    check(
        "★合成帧第 7 行（202,1324,197,28）不在屏上★（y+h > 1280）",
        nav.on_screen((202, 1324, 197, 28)) is False,
    )
    check(
        "★合成帧第 8 行（202,1468,197,28）不在屏上★（真机误判的那一行）",
        nav.on_screen((202, 1468, 197, 28)) is False,
    )
    check(
        "对照：y=740 的行在屏上（真的卡住时仍能说「行就在屏上」）",
        nav.on_screen((201, 740, 114, 33)) is True,
    )
    check(
        "x 越界（x<0 / x+w>720）一律不在屏上",
        nav.on_screen((-1, 640, 197, 28)) is False
        and nav.on_screen((600, 640, 197, 28)) is False,
    )
    check(
        "y+h > 1280 一律不在屏上（y=1200 + h=100）",
        nav.on_screen((202, 1200, 197, 100)) is False,
    )
    check(
        "整屏框 (0,0,720,1280) 恰好在边界上 ⇒ 在屏上（边界不许收紧 1px）",
        nav.on_screen((0, 0, 720, 1280)) is True,
    )
    check(
        "解不开的框（None / 不是四元）一律不在屏上（不拿「有框」冒充「在屏上」）",
        nav.on_screen(None) is False and nav.on_screen((202, 640)) is False,
    )


def test_row_roi() -> None:
    print("[11] ★列表行 ROI★：行名只可能在列表体里（标题 / 页签 / 底栏一律不算）")

    from scene.options import TARGET_ROW_ROI

    check(
        "ROW_ROI 引用 scene.options.TARGET_ROW_ROI（★不写第三份数字★）",
        tuple(nav.ROW_ROI) == tuple(TARGET_ROW_ROI),
        f"{tuple(nav.ROW_ROI)} vs {tuple(TARGET_ROW_ROI)}",
    )
    x, y, w, h = nav.ROW_ROI
    check(
        "行 ROI 上边界 == 列表体起点（SCROLL_PLAN.list_body[0]，#36 的真机几何）",
        y == nav.SCROLL_PLAN.list_body[0],
        f"y={y} / list_body={nav.SCROLL_PLAN.list_body}",
    )
    tab_bottom = max(
        nav.TAB_ANCHORS[tab].roi[1] + nav.TAB_ANCHORS[tab].roi[3] for tab in nav.LORD_TABS
    )
    check(
        "行 ROI 在页签行之下（页签底边 = 两个页签 ROI 的下沿；页签不是列表行）",
        y >= tab_bottom,
        f"y={y} / 页签底边={tab_bottom}",
    )
    check(
        "行 ROI 整框落在 720x1280 屏内（不越过任何一条屏幕边）",
        0 <= x and 0 <= y and x + w <= nav.SCREEN_W and y + h <= nav.SCREEN_H,
        f"[{x},{y},{w},{h}] on {nav.SCREEN_W}x{nav.SCREEN_H}",
    )

    # 真机行框（列表页）在 ROI 内；模式页标题 / 页签 / 底栏都在外
    check(
        "真机列表行（202,748,197,28）⇒ 是列表行",
        nav.row_roi_hit((202, 748, 197, 28)) is True,
    )
    check(
        "真机列表行（201,1072,165,28）⇒ 仍是列表行（靠下，但还在列表体里）",
        nav.row_roi_hit((201, 1072, 165, 28)) is True,
    )
    check(
        "★模式页顶部领主名（157,154,379,94，中心 (346.5,201)）⇒ **不是**列表行★"
        "（真机连点 3 次的那个框）",
        nav.row_roi_hit((157, 154, 379, 94)) is False,
    )
    check(
        "页签标签框（135,388,90,35）⇒ 不是列表行",
        nav.row_roi_hit((135, 388, 90, 35)) is False,
    )
    check(
        "底栏「主城」（157,1248,44,26）⇒ 不是列表行",
        nav.row_roi_hit((157, 1248, 44, 26)) is False,
    )
    check(
        "贴到列表体下边界之外（202,1230,197,28，中心 y=1244）⇒ 不是列表行",
        nav.row_roi_hit((202, 1230, 197, 28)) is False,
    )
    check(
        "解不开的框（None / 不是四元）一律不是列表行（不拿「有框」冒充「列表行」）",
        nav.row_roi_hit(None) is False and nav.row_roi_hit((202, 640)) is False,
    )


#: 详情页逐档状态帧（720 空间；真机帧 ``lord_detail_multidiff.png`` 的逐条读数）。
#: 徽标在档名**上方 ≈70px**、档名行距 ≈190px、徽标在档名**左侧**（x≈15 vs 202）。
FRAME_DETAIL_ALL_COMPLETE: tuple = (
    ("推荐编成", [37, 353, 65, 20]),
    ("COMPLETE!!", [15, 388, 126, 22]), ("妖狐超级", [202, 456, 119, 33]),
    ("COMPLETE!!", [15, 578, 125, 23]), ("妖狐高级+", [201, 648, 139, 32]),
    ("COMPLETE!!", [15, 769, 123, 24]), ("妖狐高级", [202, 837, 119, 33]),
    ("COMPLETE!!", [15, 960, 127, 22]), ("妖狐中级", [201, 1028, 121, 33]),
)
#: 最上面那档（地狱级）已通关、未通关的是下面的超级 —— 真机 484 第 3 轮验收的形态。
FRAME_DETAIL_TOP_COMPLETE: tuple = (
    ("推荐编成", [37, 353, 65, 20]),
    ("COMPLETE!!", [15, 388, 126, 22]), ("机工神兵菲诺梅那地狱级", [202, 456, 308, 28]),
    ("NEW", [15, 578, 46, 20]), ("机工神兵菲诺梅那超级", [202, 648, 308, 28]),
    ("COMPLETE!!", [15, 769, 123, 24]), ("机工神兵菲诺梅那高级+", [202, 837, 308, 28]),
)
#: 早期账号（``lord_detail_redjoss_early.png``）：只有一档 + NEW + 首次报酬。
FRAME_DETAIL_EARLY: tuple = (
    ("推荐编成", [37, 353, 65, 20]),
    ("NEW", [18, 389, 46, 20]),
    ("红机兵海茵莱特中级", [203, 458, 253, 28]),
    ("首次报酬", [542, 429, 82, 27]),
)


def test_detail_tier_status() -> None:
    """★D6-①★ 详情页逐档状态（COMPLETE!! / NEW）→ 只选**未通关**的那一档（不按位置）。"""
    print("\n[详情页逐档状态] 徽标配对 / 选档 / 不盲点 / 回列表【返回】")

    # (a) 档名解析：难度词表**整串锚定**（长词优先：「高级+」不许被切成「高级」+尾巴「+」）
    check("档名 → (前缀, 难度)：机工神兵菲诺梅那超级",
          nav.detail_tier_name("机工神兵菲诺梅那超级") == ("机工神兵菲诺梅那", "超级"))
    check("档名 → (前缀, 难度)：妖狐高级+（长词优先）",
          nav.detail_tier_name("妖狐高级+") == ("妖狐", "高级+"),
          f"got={nav.detail_tier_name('妖狐高级+')!r}")
    check("不是档名的文字一律返回 None（列表行名 / 页签 / 提示语）",
          all(nav.detail_tier_name(t) is None
              for t in ("妖狐讨伐", "推荐编成", "更新列表", "首次报酬", "COMPLETE!!", "")))

    # (b) 徽标判据：COMPLETE!! 的弱读（MPLETE!!）也算已通关；NEW 是未通关
    check("COMPLETE!! / MPLETE!!（弱读）都判「已通关」",
          nav.detail_mark_status("COMPLETE!!") == nav.DETAIL_STATUS_COMPLETE
          and nav.detail_mark_status("MPLETE!!") == nav.DETAIL_STATUS_COMPLETE)
    check("缺字太多的坏读不算已通关（不猜）", nav.detail_mark_status("PLETE!") is None)
    check("NEW 判「未通关」", nav.detail_mark_status("NEW") == nav.DETAIL_STATUS_NEW)
    check("别的文字不是徽标（首次报酬 / SS / 空）",
          all(nav.detail_mark_status(t) is None for t in ("首次报酬", "SS", "", None)))

    # (c) 配对：4 档全 COMPLETE!!（真机帧）——每档都拿到**自己那一行**的徽标
    rows = nav.detail_tier_rows(FRAME_DETAIL_ALL_COMPLETE)
    check("详情页 4 档全读出、按从上到下排序",
          [(row.difficulty, row.status) for row in rows]
          == [("超级", nav.DETAIL_STATUS_COMPLETE), ("高级+", nav.DETAIL_STATUS_COMPLETE),
              ("高级", nav.DETAIL_STATUS_COMPLETE), ("中级", nav.DETAIL_STATUS_COMPLETE)],
          f"got={[(row.difficulty, row.status) for row in rows]}")
    check("每档都配到了徽标框（不是 None）", all(row.mark_box for row in rows))

    # (d) 配对是**几何**而不是「第几行」：徽标偏太远 / 在档名右边 ⇒ 该档「读不到」
    shifted = tuple(
        (text, [box[0], box[1] + 130, box[2], box[3]]) if "COMPLETE" in text else (text, box)
        for text, box in FRAME_DETAIL_ALL_COMPLETE
    )
    check("徽标离档名 >120px（跨行带）⇒ 该档状态读不到（不瞎配）",
          all(row.status is None for row in nav.detail_tier_rows(shifted)))
    right_side = tuple(
        (text, [300, box[1], box[2], box[3]]) if "COMPLETE" in text else (text, box)
        for text, box in FRAME_DETAIL_ALL_COMPLETE
    )
    check("徽标在档名右边 ⇒ 不算这一档的（真机徽标在左侧）",
          all(row.status is None for row in nav.detail_tier_rows(right_side)))

    # (e) 选档：最上面那档已通关 ⇒ 选下面的 NEW；绝不选最上面
    choice = nav.pick_uncleared_tier(FRAME_DETAIL_TOP_COMPLETE)
    check("最上面（地狱级）已 COMPLETE!! ⇒ 选「超级」（NEW）",
          choice.picked and choice.difficulty == "超级", f"got={choice.difficulty!r}")
    check("选档判决带人读理由（现场能看出为什么选它）",
          "NEW" in choice.reason and "超级" in choice.reason, f"reason={choice.reason!r}")
    check("summary 按详情页顺序列出每档状态",
          choice.summary() == "地狱级=COMPLETE!! / 超级=NEW / 高级+=COMPLETE!!",
          f"got={choice.summary()!r}")
    check("显式目标档已 COMPLETE!! ⇒ 不点它（改选第一个 NEW）",
          nav.pick_uncleared_tier(FRAME_DETAIL_TOP_COMPLETE, "地狱级").difficulty == "超级")
    check("显式目标档是 NEW ⇒ 指定档优先",
          nav.pick_uncleared_tier(FRAME_DETAIL_TOP_COMPLETE, "超级").difficulty == "超级")

    # (f) 全档 COMPLETE!! / 一档状态都读不到 / 没有档 ⇒ 三种结论分得开
    all_done = nav.pick_uncleared_tier(FRAME_DETAIL_ALL_COMPLETE)
    check("全档 COMPLETE!! ⇒ all_complete 且不选任何档",
          all_done.status == nav.DETAIL_PICK_ALL_COMPLETE and not all_done.picked,
          f"got={all_done.status!r} picked={all_done.picked}")
    check("全档 COMPLETE!! 的理由说「不点任何档 + 回列表」",
          "不点任何档" in all_done.reason and "回列表" in all_done.reason,
          f"reason={all_done.reason!r}")
    no_marks = tuple((t, b) for t, b in FRAME_DETAIL_ALL_COMPLETE if "COMPLETE" not in t)
    no_status = nav.pick_uncleared_tier(no_marks)
    check("★读不到任何档状态 ⇒ no_status 且不选（绝不取最上面）★",
          no_status.status == nav.DETAIL_PICK_NO_STATUS and not no_status.picked,
          f"got={no_status.status!r} difficulty={no_status.difficulty!r}")
    check("读不到状态的理由点名「不盲点」（现场可查）",
          "不盲点" in no_status.reason and "取最上面" in no_status.reason,
          f"reason={no_status.reason!r}")
    check("一档难度行名都没有 ⇒ no_tiers（不是「全通」）",
          nav.pick_uncleared_tier((("推荐编成", [37, 353, 65, 20]),)).status
          == nav.DETAIL_PICK_NO_TIERS)
    partial = tuple((t, b) for t, b in FRAME_DETAIL_TOP_COMPLETE if t != "NEW")
    check("★有档读不到状态（且有档 COMPLETE）⇒ 不当全通、也不盲点★",
          nav.pick_uncleared_tier(partial).status == nav.DETAIL_PICK_NO_STATUS,
          f"got={nav.pick_uncleared_tier(partial).status!r}")

    # (g) 早期账号：只有「中级 + NEW」一档 ⇒ 就选它（不能因为「没有第二档」就跳过）
    early = nav.pick_uncleared_tier(FRAME_DETAIL_EARLY)
    check("早期账号（中级 NEW）⇒ 选中级", early.picked and early.difficulty == "中级",
          f"got={early.difficulty!r}")

    # (h) 回列表【返回】：只在详情页成立（列表页最左槽也是【返回】，不能当「离开列表」）
    with_back = FRAME_DETAIL_ALL_COMPLETE + (("返回", [30, 1246, 46, 26]),)
    check("详情页 + 【返回】⇒ 返回它的当帧 OCR 框",
          nav.detail_back_box(with_back) == (30, 1246, 46, 26),
          f"got={nav.detail_back_box(with_back)!r}")
    check("详情页但读不到【返回】⇒ None（不盲点）", nav.detail_back_box(FRAME_DETAIL_ALL_COMPLETE) is None)
    check("列表页上的【返回】不算详情页的（判据 = page_state == lords_detail）",
          nav.detail_back_box(FRAME_TAB_JOSS + (("返回", [30, 1246, 46, 26]),)) is None)
    check("【返回】只在底部导航最左槽 = DETAIL_BACK_ROI 内才算",
          nav.detail_back_box(FRAME_DETAIL_ALL_COMPLETE + (("返回", [300, 600, 46, 26]),)) is None,
          f"roi={list(nav.DETAIL_BACK_ROI)}")


#: ★本票最后一个阻塞点 ②（真机 484 第 5 轮验收，18:12–18:18）★
#: 关轮后重读的那一屏：``rows: COMPLETE!! 4/4、COMPLETE!! 4/4、八岐大蛇讨伐 4/4、妖狐讨伐 1/4``
#: —— 徽标与行名在同一行带，几何分组把更贴近「通关数」的徽标挂成了行名。
def test_badge_text() -> None:
    print("[12] ★徽标不是行名★：COMPLETE!! / PLETE!! / NEW / 首次报酬 / SS 一律不是行名")

    check(
        "徽标词表是**可扩展的元组**且都在（COMPLETE!! / PLETE!! / NEW / 首次报酬 / SS）",
        isinstance(nav.LIST_BADGE_MARKS, tuple)
        and {
            "COMPLETE!!",
            nav.DETAIL_MARK_COMPLETE,
            nav.DETAIL_MARK_NEW,
            "首次报酬",
            "SS",
        }
        <= set(nav.LIST_BADGE_MARKS),
        f"{nav.LIST_BADGE_MARKS}",
    )
    for text in (
        "COMPLETE!!",
        "MPLETE!!",            # 弱读（丢首字母）
        "PLETE!!",             # = DETAIL_MARK_COMPLETE
        "NEW",                 # 未通关徽标
        "首次报酬",
        "SS",                  # 评分徽标
        "COMPLETE!! SS",       # 连成一串
        " COMPLETE!! ",        # 带空白
    ):
        check(f"徽标 {text!r} ⇒ is_badge_text=True", nav.is_badge_text(text) is True)
    for text in ("", "   ", "妖狐讨伐", "无猾机兵", "八岐大蛇讨伐", "艾基尔·嫉妒讨伐"):
        check(f"不是徽标 {text!r} ⇒ False", nav.is_badge_text(text) is False)
    # ★收得不能太宽★：花名册里的真行名一个都不许被当成徽标
    bad = [entry.row_name for entry in LORDS if nav.is_badge_text(entry.row_name)]
    check("花名册的**每一个**真行名都不是徽标（过滤不许误杀真行）", bad == [], f"{bad}")
    check("解不开的值（None）⇒ False（不抛）", nav.is_badge_text(None) is False)


def test_badge_recover() -> None:
    """[13] ★行名被读成徽标 ⇒ 用几何把真名找回来★（真机 484 accept7 真机数据）。

    ``screenshots/accept6_lords_list_bottom_MM.png``（领主战，5 行全 M/M，720 空间 OCR 原值）::

        COMPLETE!! [13,735,127,27]   领主战 [201,755,70,28]
        不死王瑞西塔尔讨伐 [203,787,245,28]   通关数4/4 [547,833,126,28]

    病因 = **配对**（徽标属于下一张卡，却比本卡真名更贴近本卡的「通关数」：dy 45.5 vs 48）——
    真名在帧里、OCR 也读出来了 ⇒ 排除徽标后按同一条几何找回来即可：

    * 该帧原始分组**确实复现** 4 个 ``COMPLETE!!`` 假行名（守卫不空转）；
    * 修复后每个进度都挂回自己的真名（``dropped`` 归零）⇒ ``plan_round.all_done`` 可达；
    * 混合进度帧里被抢走的 ``碧愁机兵 1/4`` 回到读数 / 目标（不只是少读一行，而是**漏规划**）；
    * 真名不在帧里 ⇒ ``None``（安全线：调用方整行不读）；坏框 / 空帧 ⇒ ``None``；
    * ★花名册外的活动行也要修★：``accept6_jianglin`` 的 ``五王连战 1/1`` 不在 ``LORDS`` 里，
      只认花名册会让它永远被剔 ⇒ ``dropped_in_scan`` 压住 ``all_done``；
    * ★确定不是行名的文本不许捡回来★：副标题（= 页签名）离进度更近时也必须被排除。
    """
    print("[13] ★行名被读成徽标 ⇒ 几何修复真名★（真机 accept6/accept7 的 OCR 原值）")
    known = tuple(entry.row_name for entry in LORDS)

    # 真机帧：5 行全 M/M（accept6_lords_list_bottom_MM.png，逐条 OCR 原值）
    frame_mm = (
        ("领主战", [135, 388, 90, 35]),
        ("降临讨伐", [481, 389, 117, 33]),
        ("更新列表", [617, 331, 79, 24]),
        ("COMPLETE!!", [15, 448, 121, 24]), ("领主战", [201, 467, 70, 28]),
        ("废墟魔像讨伐", [202, 496, 165, 32]), ("通关数4/4", [547, 545, 127, 28]),
        ("COMPLETE!!", [14, 592, 127, 24]), ("领主战", [201, 611, 70, 28]),
        ("废墟守卫·火讨伐", [203, 641, 197, 28]), ("通关数4/4", [547, 689, 126, 28]),
        ("COMPLETE!!", [13, 735, 127, 27]), ("领主战", [201, 755, 70, 28]),
        ("不死王瑞西塔尔讨伐", [203, 787, 245, 28]), ("通关数4/4", [547, 833, 126, 28]),
        ("COMPLETE!!", [15, 880, 125, 23]), ("领主战", [201, 899, 70, 29]),
        ("雷霆树妖讨伐", [202, 928, 165, 32]), ("通关数4/4", [547, 977, 126, 28]),
        ("COMPLETE!!", [13, 1023, 127, 27]), ("领主战", [201, 1043, 70, 29]),
        ("维·索拉斯讨伐", [202, 1072, 173, 32]), ("通关数3/3", [549, 1124, 125, 24]),
    )
    raw_rows, _orphans = group_progress_rows(frame_mm)
    raw_names = [row.name for row in raw_rows]
    check("前提：真机帧上原始分组确实把徽标挂成行名（4 个 COMPLETE!!）",
          raw_names.count("COMPLETE!!") == 4, f"raw={raw_names}")

    want = {
        (547, 545): "废墟魔像讨伐",
        (547, 689): "废墟守卫·火讨伐",
        (547, 833): "不死王瑞西塔尔讨伐",
        (547, 977): "雷霆树妖讨伐",
        (549, 1124): "维·索拉斯讨伐",
    }
    recovered_rows: list = []
    for row in raw_rows:
        found = nav.recover_badge_row_name(frame_mm, row.progress_box)
        box = tuple(row.progress_box[:2])
        check(f"进度 {box} 修复出真名 {want.get(box)!r}",
              found is not None and found[0] == want.get(box),
              f"got={None if found is None else found[0]!r}")
        if found is not None:
            recovered_rows.append(RowReading(found[0], row.n, row.m, found[1], row.progress_box))

    plan = plan_round(recovered_rows, LORDS)
    check("★修复后 5 行全是真名且都 M/M ⇒ plan_round.all_done=True（全部解禁可达）★",
          plan.all_done is True and len(recovered_rows) == 5,
          f"all_done={plan.all_done!r} rows={[(r.name, r.n, r.m) for r in recovered_rows]}")
    check("修复后没有假行名（徽标/花名册外文本一律不出现）",
          all(not nav.is_badge_text(row.name) and row.name in known for row in recovered_rows),
          f"{[row.name for row in recovered_rows]}")

    # 混合进度帧（accept7_list_2.png）：被徽标抢走的是 **碧愁机兵 1/4**（漏的是「该打谁」）
    frame_mixed = (
        ("领主战", [136, 388, 89, 35]),
        ("降临讨伐", [481, 389, 117, 32]),
        ("更新列表", [615, 328, 82, 28]),
        ("降临讨伐", [201, 501, 91, 28]), ("橙悚机兵", [199, 529, 115, 32]),
        ("通关数3/4", [549, 581, 126, 24]),
        ("降临讨伐", [201, 645, 91, 28]), ("碧愁机兵", [201, 673, 114, 32]),
        ("通关数1/4", [549, 723, 126, 28]),
        ("COMPLETE!!", [14, 769, 125, 24]), ("降临讨伐", [201, 789, 91, 28]),
        ("闪哭机兵", [201, 817, 114, 32]), ("通关数4/4", [547, 867, 127, 28]),
        ("降临讨伐", [201, 933, 91, 28]), ("暗凛机兵", [201, 961, 115, 32]),
        ("通关数2/4", [549, 1011, 126, 28]),
        ("降临讨伐", [202, 1079, 89, 24]), ("始龙之眼", [201, 1105, 114, 32]),
        ("通关数1/4", [546, 1156, 127, 24]),
    )
    raw_mixed, _ = group_progress_rows(frame_mixed)
    check("前提：混合帧上 碧愁机兵 1/4 的行名被徽标抢走",
          "碧愁机兵" not in [row.name for row in raw_mixed]
          and "COMPLETE!!" in [row.name for row in raw_mixed],
          f"raw={[(r.name, r.n, r.m) for r in raw_mixed]}")
    fixed = None
    for row in raw_mixed:
        if nav.is_badge_text(row.name) and (row.n, row.m) == (1, 4):
            fixed = nav.recover_badge_row_name(frame_mixed, row.progress_box)
    check("★被抢走的未通关行修好了★（碧愁机兵 1/4 回到读数 / 目标）",
          fixed is not None and fixed[0] == "碧愁机兵"
          and "碧愁机兵" in [
              target.row_name
              for target in plan_round(
                  (RowReading("碧愁机兵", 1, 4, fixed[1] if fixed else (0, 0, 1, 1),
                              (549, 723, 126, 28)),),
                  LORDS,
              ).targets
          ],
          f"got={None if fixed is None else fixed[0]!r}")

    # 安全线 / 排除判据
    only_badge = (
        ("领主战", [135, 388, 90, 35]),
        ("降临讨伐", [481, 389, 117, 33]),
        ("更新列表", [615, 328, 82, 28]),
        ("COMPLETE!!", [15, 640, 124, 24]), ("通关数4/4", [547, 688, 127, 28]),
    )
    check("真名不在帧里 ⇒ None（调用方必须整行不读，绝不猜名字）",
          nav.recover_badge_row_name(only_badge, [547, 688, 127, 28]) is None)
    check("坏框 / 空帧 ⇒ None（不抛）",
          nav.recover_badge_row_name(only_badge, None) is None
          and nav.recover_badge_row_name((), [1, 2, 3, 4]) is None
          and nav.recover_badge_row_name(only_badge, (0, 0, 0, 0)) is None)
    # ★花名册外的活动行也要修★（accept6_jianglin_hongji_cangtan_1of4.png，逐条 OCR 原值）
    frame_jianglin = (
        ("领主战", [135, 388, 90, 35]),
        ("降临讨伐", [481, 389, 117, 32]),
        ("更新列表", [615, 328, 82, 28]),
        ("通过房间号码参加", [187, 508, 259, 32]),
        ("五重决战", [198, 609, 93, 28]), ("五王连战", [201, 637, 115, 32]),
        ("通关数1/1", [547, 688, 123, 28]),
        ("COMPLETE!!", [15, 735, 122, 23]), ("降临讨伐", [201, 753, 91, 28]),
        ("无猾机兵", [201, 781, 114, 33]), ("通关数5/5", [547, 831, 127, 28]),
        ("降临讨伐", [199, 897, 93, 28]), ("红嫉机兵", [199, 925, 115, 33]),
        ("通关数1/4", [547, 976, 127, 28]),
        ("降临讨伐", [199, 1041, 91, 28]), ("苍叹机兵", [201, 1069, 114, 33]),
        ("通关数1/4", [547, 1120, 127, 28]),
    )
    raw_jl, _ = group_progress_rows(frame_jianglin)
    check("前提：降临讨伐帧上 五王连战 1/1 的行名被徽标抢走",
          "五王连战" not in [row.name for row in raw_jl]
          and "COMPLETE!!" in [row.name for row in raw_jl],
          f"raw={[(r.name, r.n, r.m) for r in raw_jl]}")
    jl = nav.recover_badge_row_name(frame_jianglin, [547, 688, 123, 28])
    check("★花名册外的活动行（五王连战）也修得回来★（只认花名册会每帧被剔）",
          jl is not None and jl[0] == "五王连战" and "五王连战" not in known,
          f"got={None if jl is None else jl[0]!r}")
    chrome = (
        ("领主战", [135, 388, 90, 35]),
        ("降临讨伐", [481, 389, 117, 33]),
        ("更新列表", [615, 328, 82, 28]),
        ("COMPLETE!!", [15, 676, 124, 24]), ("降临讨伐", [201, 660, 91, 28]),
        ("通关数4/4", [547, 688, 127, 28]),
    )
    check("★确定不是行名的文本不许被捡回来★（副标题/进度/页签即使更近也排除）",
          nav.recover_badge_row_name(chrome, [547, 688, 127, 28]) is None)
    check("进度/页签/固定元素不会被当行名",
          nav.recover_badge_row_name(
              (("通关数4/4", [202, 660, 100, 28]), ("领主战", [201, 660, 70, 28]),
               ("更新列表", [201, 660, 82, 28]), ("通关数4/4", [547, 688, 127, 28])),
              [547, 688, 127, 28]) is None)


def test_scan_integrity_scope() -> None:
    """[14] ★扫描完整性账的作用域★（真机 484 第 7 轮验收的判据靠它）。

    agent 的「关轮只认整轮扫描帧」把 ``round_gained`` 挪到 ``mode=end`` 的交接帧上，
    判据是 ``NavState`` 的两条**作用域**约定（真源在这里钉住，改坏了 agent 会拿脏读数判进展）：

    1. ``begin_round``（新一轮开扫）清空 ``dropped_in_scan`` / ``top_unconfirmed`` /
       ``tab_switch_failed`` —— 这些账只算**这一轮**的扫描；
    2. ``complete_scan``（扫完交接）**不清**它们 —— 交接帧读到的正是刚扫完这一轮的完整性；
    3. ``scan_incomplete_reason`` 必须点名「有行被徽标剔除」—— 现场据此说「为什么没法判断」。
    """
    print("[14] ★扫描完整性账的作用域★：每轮清零 / 交接时仍在（关轮判据的输入）")
    st = nav.NavState()
    st.begin_round(1.0)
    check("begin_round 后完整性账是干净的", st.scan_complete() is True,
          f"reason={st.scan_incomplete_reason()!r}")
    st.observe((), dropped=2)                     # 扫描期间两行被徽标剔除
    st.top_unconfirmed = 1
    st.note_tab_switch_failed()
    check("扫描期记账：dropped/top/tab 都记上了",
          st.dropped_in_scan == 2 and st.top_unconfirmed == 1 and st.tab_switch_failed is True,
          f"{st.dropped_in_scan}/{st.top_unconfirmed}/{st.tab_switch_failed}")
    check("scan_complete() 为 False（这一轮扫描不完整）", st.scan_complete() is False)
    check("scan_incomplete_reason 点名「有行被徽标剔除」",
          "有行被徽标剔除" in st.scan_incomplete_reason(),
          st.scan_incomplete_reason())
    st.complete_scan(1, 2.0)
    check("★complete_scan（交接）不许清完整性账★（交接帧就靠它判「无法判断」）",
          st.dropped_in_scan == 2 and st.scan_complete() is False,
          f"dropped={st.dropped_in_scan} reason={st.scan_incomplete_reason()!r}")
    st.begin_round(3.0)
    check("★begin_round（新一轮）必须清完整性账★（不能拿上一轮的脏账判这一轮）",
          st.dropped_in_scan == 0 and st.top_unconfirmed == 0
          and st.tab_switch_failed is False and st.scan_complete() is True,
          f"dropped={st.dropped_in_scan} top={st.top_unconfirmed} tab={st.tab_switch_failed}")


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
    test_rewind_to_top()
    test_scroll_gate()
    test_dedup()
    test_breaker_r1()
    test_sweep_and_stuck()
    test_breaker_r2()
    test_full_registry()
    test_loading_transition()
    test_screen_bounds()
    test_row_roi()
    test_challenge_release_evidence()
    test_detail_tier_status()
    test_badge_text()
    test_badge_recover()
    test_scan_integrity_scope()
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
