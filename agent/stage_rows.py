"""关卡列表解析 —— 纯逻辑，不依赖 maa，方便离线单测。

被 agent/my_reco.py 里的自定义识别 (stage_next / stage_all_done) 使用。
"""

from __future__ import annotations

import re
from typing import Optional

# 关卡编号格式，例如 "第6章大和之都 9 - 1" / "第6章大和之都9-2"
DEFAULT_STAGE_REGEX = r"第\s*\d+\s*章.*?\d+\s*-\s*\d+"
DEFAULT_FIGHT_TEXT = "战斗"
# 「战斗」按钮相对关卡编号的最大下移像素（同一行的判定范围）
DEFAULT_ROW_DY = 150

Box = list[int]
Row = tuple[str, Optional[Box]]


def normalize_key(text: str) -> str:
    """去掉所有空白，避免 OCR 把 "9-1" 读成 "9 - 1" 时同一关被记成两条。"""
    return re.sub(r"\s+", "", text or "")


def parse_stage_rows(
    items: list[tuple[str, Box]],
    stage_regex: str = DEFAULT_STAGE_REGEX,
    fight_text: str = DEFAULT_FIGHT_TEXT,
    row_dy: int = DEFAULT_ROW_DY,
) -> list[Row]:
    """把 OCR 结果整理成「关卡行」，按屏幕从上到下排序。

    items: [(text, box), ...]，box = [x, y, w, h]
    每行的「战斗」按钮判定：与关卡编号同一列、且在其下方 row_dy 像素内的 战斗 文本。

    返回 [(关卡编号文本, 该行战斗按钮 box 或 None), ...]
    """
    pattern = re.compile(stage_regex)
    stages: list[tuple[float, str]] = []
    fights: list[tuple[float, Box]] = []

    for text, box in items:
        if not box or len(box) != 4:
            continue
        cy = box[1] + box[3] / 2
        if pattern.search(text):
            stages.append((cy, text))
        elif text == fight_text:
            fights.append((cy, box))

    stages.sort(key=lambda item: item[0])
    fights.sort(key=lambda item: item[0])

    rows: list[Row] = []
    for cy, text in stages:
        fight_box: Optional[Box] = None
        for fy, fbox in fights:
            if cy <= fy <= cy + row_dy:
                fight_box = fbox
                break
        rows.append((text, fight_box))
    return rows


def pick_next(rows: list[Row], attempted: set[str]) -> Optional[Row]:
    """挑出第一个「有战斗按钮且还没打过」的关卡行；没有则返回 None。"""
    for text, fight_box in rows:
        if fight_box is None:
            continue
        if normalize_key(text) in attempted:
            continue
        return text, fight_box
    return None


def is_all_done(rows: list[Row], attempted: set[str]) -> bool:
    """所有可见关卡行都已打过（且都有关卡编号）时返回 True。"""
    if not rows:
        return False
    for text, fight_box in rows:
        if fight_box is not None and normalize_key(text) not in attempted:
            return False
    return True


# ===========================================================================
# 「外传 / 特殊副本」关卡列表解析（行结构与主线的 第N章N-N 不同，单独一套）
#
# 实测结构（720 空间，16448，见 ax6.png / st_after2.png）：
#
#   ┌ NEW ──────────────────────────────────────┐   ← 徽标在行左上（y 比标题高 50~110）
#   │        前往圣地        （标题，左对齐 x≈202）│
#   │  [特殊战斗]  推荐属性 水  体力 10          │   ← 行类型标签在标题【下方】dy≈37~55
#   └───────────────────────────────────────────┘
#
#   另一种「已通关的纯剧情行」没有 战斗/特殊战斗 标签，只有 STORY 字样，
#   且 STORY 在标题【上方】：
#   ┌ COMPLETE!! ───────────────────────────────┐
#   │        STORY                               │
#   │        提欧与玛格诺斯                       │
#   └───────────────────────────────────────────┘
#
# 所以：行类型 = 特殊战斗 / 战斗（标签在标题下方）或 STORY（STORY 在标题上方）。
# 这两条判据互相独立，天然把「剧情行」和「战斗行」区分开：
#   · 特殊战斗  -> 需要【长按】标题进入（普通点击无效）
#   · 战斗      -> 普通点击标题进入
#   · STORY     -> 普通点击标题进入
# ===========================================================================
# 行类型标签（小字号，x 在左边）
DEFAULT_SIDE_LABEL_REGEX = r"^(特殊战斗|战斗)$"
DEFAULT_SIDE_STORY_TAG = "STORY"
# 标题必须是横向较长的文本，避免把「推荐属性 / STORY / 体力」当成标题
DEFAULT_SIDE_TITLE_MIN_W = 80
DEFAULT_SIDE_TITLE_X = (170, 430)
# 标签在标题下方：标题中心比标签中心高 min_dy ~ max_dy
DEFAULT_SIDE_LABEL_DY = (15, 90)
# STORY 在标题上方：标题中心比 STORY 中心低 min_dy ~ max_dy
DEFAULT_SIDE_STORY_DY = (15, 115)

SideRow = dict  # {"name","type","title_box","anchor_box"}


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def parse_side_rows(
    items: list[tuple[str, Box]],
    label_regex: str = DEFAULT_SIDE_LABEL_REGEX,
    story_tag: str = DEFAULT_SIDE_STORY_TAG,
    title_min_w: int = DEFAULT_SIDE_TITLE_MIN_W,
    title_x: tuple[int, int] = DEFAULT_SIDE_TITLE_X,
    label_dy: tuple[int, int] = DEFAULT_SIDE_LABEL_DY,
    story_dy: tuple[int, int] = DEFAULT_SIDE_STORY_DY,
) -> list[SideRow]:
    """把 OCR 结果整理成「外传关卡行」，按屏幕从上到下排序。

    items: [(text, box), ...]，box = [x, y, w, h]

    返回 [{"name","type","title_box","anchor_box"}, ...]
    """
    pattern = re.compile(label_regex)
    labels: list[tuple[float, str, Box]] = []   # (cy, text, box)
    stories: list[tuple[float, Box]] = []        # (cy, box)
    badges: list[tuple[float, Box, str]] = []    # (cy, box, text) NEW / COMPLETE!!
    titles: list[tuple[float, float, int, Box, str]] = []  # (cy, cx, w, box, text)

    x_lo, x_hi = title_x
    for text, box in items:
        if not box or len(box) != 4:
            continue
        t = (text or "").strip()
        if not t:
            continue
        cx, cy = _center(box)
        w = box[2]
        if t.startswith("NEW") or t.startswith("COMPLETE"):
            badges.append((cy, box, t))
        if pattern.match(t) and w < 70:
            # 行类型标签：字号小、靠左
            labels.append((cy, t, box))
        elif t == story_tag:
            stories.append((cy, box))
        if w >= title_min_w and x_lo <= cx <= x_hi:
            titles.append((cy, cx, w, box, t))

    def _find_badge(title_box: Box, title_cy: float) -> str:
        """徽标在标题【左上】：x 比标题左边缘更靠左，y 比标题中心高 10~150。"""
        left = title_box[0]
        best = None
        for b_cy, b_box, b_text in badges:
            if _center(b_box)[0] >= left:
                continue
            dy = title_cy - b_cy
            if 10 <= dy <= 150:
                if best is None or dy < best[0]:
                    best = (dy, b_text)
        return best[1] if best else ""

    rows: list[SideRow] = []
    seen: set[str] = set()

    def _find_title(ref_cy: float, above: bool, dy_range: tuple[int, int]):
        best = None
        for cy, _cx, _w, box, t in titles:
            dy = (ref_cy - cy) if above else (cy - ref_cy)
            if dy_range[0] <= dy <= dy_range[1]:
                key = normalize_key(t)
                if key in seen:
                    continue
                if best is None or dy < best[0]:
                    best = (dy, t, box)
        return best

    # 先处理 战斗 / 特殊战斗 行（有明确行类型，优先级最高）
    for label_cy, label_text, label_box in labels:
        found = _find_title(label_cy, above=True, dy_range=label_dy)
        if not found:
            continue
        _dy, name, title_box = found
        seen.add(normalize_key(name))
        rows.append({
            "name": name,
            "type": label_text,
            "title_box": list(title_box),
            "anchor_box": list(label_box),
            "badge": _find_badge(title_box, _center(title_box)[1]),
        })

    # 再处理只有 STORY 的纯剧情行
    for story_cy, story_box in stories:
        found = _find_title(story_cy, above=False, dy_range=story_dy)
        if not found:
            continue
        _dy, name, title_box = found
        seen.add(normalize_key(name))
        rows.append({
            "name": name,
            "type": story_tag,
            "title_box": list(title_box),
            "anchor_box": list(story_box),
            "badge": _find_badge(title_box, _center(title_box)[1]),
        })

    rows.sort(key=lambda r: _center(r["title_box"])[1])
    return rows


def pick_side_next(
    rows: list[SideRow],
    row_type_regex: Optional[str] = None,
    is_done=None,
) -> Optional[SideRow]:
    """按屏幕顺序挑出第一个「未完成」的外传关卡行。

    rows            : parse_side_rows 的结果
    row_type_regex  : 只看某种类型（如 "特殊战斗" / "战斗" / "STORY" / "STORY|战斗"）；
                      为 None 表示所有类型
    is_done         : 回调 key_name -> bool（key_name 已 normalize_key）；为 None 表示全未完成
    """
    # 用 fullmatch：「战斗」不能匹配到「特殊战斗」（search/substring 会误命中）。
    pattern = re.compile(row_type_regex) if row_type_regex else None
    for row in rows:
        if pattern is not None and not pattern.fullmatch(row.get("type", "")):
            continue
        name = normalize_key(row.get("name", ""))
        row["key_name"] = name
        if is_done is not None and is_done(name):
            continue
        return row
    return None


def detect_scope(items: list[tuple[str, Box]], y_range: tuple[int, int] = (180, 520)):
    """从画面顶部的大标题里读副本名（外传列表页的「百兽王冠」）。

    取含中文、且中心 y 落在 y_range 内、面积最大的那个文本框；
    找不到返回 None。
    """
    best = None
    for text, box in items:
        if not text or not box or len(box) != 4:
            continue
        # 至少 2 个汉字，避免把单字（如 OCR 噪声「共」「兰」）当标题。
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if cjk < 2:
            continue
        _cx, cy = _center(box)
        if not (y_range[0] <= cy <= y_range[1]):
            continue
        area = box[2] * box[3]
        if best is None or area > best[0]:
            best = (area, text)
    return normalize_key(best[1]) if best else None


def select_side_stage(
    rows: list[SideRow],
    row_type_regex: Optional[str] = None,
    check_badge: bool = True,
    is_done=None,
) -> Optional[SideRow]:
    """next_stage 的完整挑选逻辑（纯函数，生产与离线验证共用同一份）：

    1. check_badge=True 时，【只保留带 NEW 徽标的行】：
         · COMPLETE!! 的行 = 已通关，直接排除；
         · 徽标为空的「孤儿行」也排除 —— 万一徽标↔行配对失败（现场截图里
           4 个徽标 + 多行标题），空徽标的行既可能是 COMPLETE 也可能是别的，
           绝不能当成「该做」。实测关卡列表里「下一个该做」的行必定带 NEW，
           所以「只认 NEW」既可靠又最保守，从根上保证 COMPLETE 行绝不会被选中。
    2. 再按 row_type_regex 过滤行类型；
    3. 最后按屏幕顺序取第一个 is_done() 为假的。
    """
    work = list(rows)
    if check_badge:
        work = [r for r in work if str(r.get("badge", "")).startswith("NEW")]
    return pick_side_next(work, row_type_regex=row_type_regex, is_done=is_done)


def side_stage_key(scene: str, name: str) -> str:
    """外传关卡的【稳定账本键】：只用 scene + 关卡名，【不含 scope】。

    scope 是 OCR 从画面大标题读出来的，跨运行会抖动（现场实测
    「哲黎明」/「哲黎叨」/「共世黎明」、「大海遗产」被读成「电的遗产」），
    把 scope 拼进 key 会导致「同一关每次记到不同 key」→ 账本对不上。
    而 next_stage 的完成判定本来就是「同 scene 下关卡名相同即算完成」，
    所以直接以 scene/关卡名 作键最稳，彻底消除 scope OCR 抖动的影响。
    """
    return normalize_key(f"{scene}/{name}")


def side_list_all_done(items: list[tuple[str, Box]]) -> bool:
    """外传【关卡列表页】是否已全部 COMPLETE（没有任何未完成行）。

    判据（需求 #1「本页全清」）：
      · 画面上存在 ≥1 个 COMPLETE!! 徽标（证明这是有已通关行的关卡列表页）；
      · 画面上【不存在】任何 NEW 徽标 —— NEW 标记「下一个未通关行」，
        没有 NEW 就没有未完成行；
      · 至少能解析出 1 个关卡行（避免把恰好含 COMPLETE 字样的其它页面误判）。

    命中 ⇒ 这本外传本页已全清，应退回「未通关」列表清下一个，绝不空转。
    """
    complete = 0
    new = 0
    for text, box in items or []:
        if not box or len(box) != 4:
            continue
        t = (text or "").strip()
        if t.startswith("COMPLETE"):
            complete += 1
        elif t.startswith("NEW"):
            new += 1
    if complete < 1 or new > 0:
        return False
    return bool(parse_side_rows(items))
