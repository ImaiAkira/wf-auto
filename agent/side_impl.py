"""外传「账本驱动」自定义识别 / 动作的【实现】。

为什么单独放一个模块
--------------------
本模块只依赖 `maa.custom_recognition` / `maa.custom_action`（以及纯逻辑模块
stage_rows / progress / maa_util），**不导入 maa.agent.agent_server**。
这样：
  1. `agent/my_reco.py` / `agent/my_action.py` 在 AgentServer 进程里 import 本模块的类
     并注册（加 AgentServer 装饰器），生产照常工作；
  2. 离线/真机测试脚本（tools/verify_side_offline.py、tools/run_side_live.py）可以
     `import side_impl` 后直接在进程内 Resource 上 `register_custom_recognition(...)`，
     不必启动 AgentServer —— 一旦 import maa.agent，native 库会切换，Resource() 会创建失败。

包含：
  · NextStageRecognition  -> custom_recognition "next_stage"
  · NoListBadgeRecognition-> custom_recognition "no_list_badge"
  · ListAllDoneRecognition-> custom_recognition "list_all_done"
  · StallRecoverRecognition-> custom_recognition "stall_recover"
  · MarkDoneAction        -> custom_action     "mark_done"
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import numpy as np

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import progress as ledger

# ★#10 用户可见进度行★：唯一出口 = agent/reporting.py（规格 docs/spec/progress-visibility.md §B）。
#   本模块**不拼** `[进度]` 字符串（守卫 hooks_146 钉住），只负责「什么时候算一步」。
import reporting
from batch_plan import (
    DIFF_REGEX,
    BATCH_PREFIX,
    JOSS_NAMES,
    MAZE_DOMAINS,
    MAZE_ROWS,
    BatchItem,
    count_done,
    is_joss,
    item_key,
    item_prefix,
    maze_rows_of,
    next_item,
    parse_batch,
    remaining,
)
from maa_util import flag, int_pair, ocr_all, read_action_param, read_param
# ★#63：主城【独有】锚点从共享源取（与 harness / 深渊 / 五重 / 幻想 同一份，绝不复制值）。
# ★#71 / R8★：失败页（GAMEOVER/是否续关？）与战斗 HUD 的判据**唯一真源**已上提
#   ``agent/battle_loop_core``；这里**同名 re-export**，本文件与 hooks_38 / hooks_46
#   仍按老名字取（``import side_impl`` 后 ``side_impl.classify_gameover`` 等照旧），
#   绝不另写一份（grep 这些名字只有一个实现）。
from battle_loop_core import (  # noqa: F401
    BATTLE_GAME_CAP_SEC,
    BATTLE_HUD_SCORE_RE,
    BATTLE_HUD_TIME_RE,
    GAMEOVER_CONFIRM_MARKERS,
    GAMEOVER_GIVEUP,
    GAMEOVER_PROMPT,
    GAMEOVER_TITLE,
    MAIN_CITY_MIN_UNIQUE,
    MAIN_CITY_UNIQUE_ANCHORS,
    battle_wait_should_hold,
    classify_gameover,
    is_battle_hud,
)
from stage_rows import (
    DEFAULT_SIDE_LABEL_DY,
    DEFAULT_SIDE_LABEL_REGEX,
    DEFAULT_SIDE_STORY_TAG,
    DEFAULT_SIDE_TITLE_X,
    detect_scope,
    normalize_key,
    parse_side_rows,
    select_side_stage,
    side_list_all_done,
    side_stage_key,
)


class NextStageRecognition(CustomRecognition):
    """账本驱动的「外传 / 特殊副本」选关：返回第一个未完成关卡的标题框。

    可用参数（custom_recognition_param）：
        scope         : 副本名（如 百兽王冠）。留空 / "__AUTO__" 时自动从画面大标题读取
        scene         : 场景名，默认 side_story（key = {scene}/{scope}/{关卡}）
        row_type      : 只看某种行类型正则，如 "特殊战斗" / "战斗" / "STORY|战斗"
        require_badge : 是否要求画面上有 NEW/COMPLETE 徽标（列表页判据），默认 true
        forbid_badge  : 反过来：有徽标就不命中（详情页判据），默认 false
        check_badge   : 是否把画面上已标 COMPLETE!! 的行直接当完成跳过，默认 true
        box           : 返回哪个框，"title"（标题，默认）或 "anchor"（行类型标签）
        ocr_entry     : 用于 OCR 的节点名，默认 OcrTask
        其余：label_regex / story_tag / label_dy / story_dy / title_min_w / title_x
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        scene = param.get("scene") or "side_story"
        row_type = param.get("row_type") or None
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        label_regex = param.get("label_regex") or DEFAULT_SIDE_LABEL_REGEX
        story_tag = param.get("story_tag") or DEFAULT_SIDE_STORY_TAG
        title_min_w = int(param.get("title_min_w") or 80)
        title_x = int_pair(param.get("title_x"), DEFAULT_SIDE_TITLE_X)
        label_dy = int_pair(param.get("label_dy"), DEFAULT_SIDE_LABEL_DY)
        story_dy = int_pair(param.get("story_dy"), (15, 115))

        require_badge = flag(param.get("require_badge", True))
        forbid_badge = flag(param.get("forbid_badge", False), default=False)
        check_badge = flag(param.get("check_badge", True))
        box_field = param.get("box") or "title"  # title | anchor

        items = ocr_all(context, argv.image, ocr_entry)
        if not items:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "OCR 无结果（OcrTask 缺失或不在可识别页面）"},
            )

        has_badge = any(
            (t.startswith("NEW") or t.startswith("COMPLETE")) for t, _b in items
        )
        if require_badge and not has_badge:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "画面上没有 NEW/COMPLETE 徽标，判定不在外传关卡列表页"},
            )
        if forbid_badge and has_badge:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "画面上有 NEW/COMPLETE 徽标，判定这是关卡列表页（本节点只用于详情页）"},
            )

        scope = param.get("scope") or ""
        if not scope or scope == "__AUTO__":
            scope = detect_scope(items) or "default"

        rows = parse_side_rows(
            items,
            label_regex=label_regex,
            story_tag=story_tag,
            title_min_w=title_min_w,
            title_x=title_x,
            label_dy=label_dy,
            story_dy=story_dy,
        )
        if not rows:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "未解析出关卡行", "scope": scope},
            )

        # 自愈：上一轮选中的关卡已经不在画面上了 -> 补记一笔，避免它一直挂在 pending。
        pend = ledger.get_pending(scope)
        if pend:
            names = {normalize_key(r["name"]) for r in rows}
            if pend[1] not in names:
                ledger.mark_done(ledger.make_key(scene, scope, pend[1]))
                ledger.pop_pending(scope)
                print(f"[next_stage] 上一轮 {pend[1]} 已不在画面，补记完成")

        def _is_done(name: str) -> bool:
            # 主键：scene/关卡名（稳定键，不含 scope）—— 消除 scope OCR 抖动。
            if ledger.is_done(side_stage_key(scene, name)):
                return True
            # 兼容旧账本：仍按 {scene}/{scope}/{关卡} 精确查一次。
            if ledger.is_done(ledger.make_key(scene, scope, name)):
                return True
            # 兜底：同 scene 下、关卡名相同也算完成（兼容历史写入的任意 scope）。
            leaf = "/" + normalize_key(name)
            scene_prefix = normalize_key(scene) + "/"
            return any(
                k.startswith(scene_prefix) and k.endswith(leaf)
                for k in ledger.all_keys()
            )

        picked = select_side_stage(
            rows,
            row_type_regex=row_type,
            check_badge=check_badge,
            is_done=_is_done,
        )
        if picked is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "reason": "账本中该类型的关卡都已完成",
                    "scope": scope,
                    "rows": [{"name": r["name"], "type": r["type"]} for r in rows],
                },
            )

        out_box = picked["anchor_box"] if box_field == "anchor" else picked["title_box"]
        ledger.set_pending(scope, picked["name"])
        # ★#10 用户可见进度行★：账本真的开始推进（选中一关）⇒ 「外传 开始」+ note=副本名。
        # ★认不出副本名时不把内部兜底名 ``default`` 端给用户★（它只是账本 key 的占位）。
        start_progress("" if scope == "default" else scope, argv)
        print(
            f"[next_stage] scope={scope} 下一个未完成：{picked['name']} "
            f"({picked['type']}) box={out_box} (field={box_field})"
        )
        return CustomRecognition.AnalyzeResult(
            box=out_box,
            detail={
                "scope": scope,
                "stage": picked["name"],
                "type": picked["type"],
                "key": ledger.make_key(scene, scope, picked["name"]),
                "rows": [{"name": r["name"], "type": r["type"]} for r in rows],
            },
        )


class NoListBadgeRecognition(CustomRecognition):
    """画面上【没有】NEW / COMPLETE!! 徽标时命中。

    用途：把「关卡详情页」和「外传关卡列表页」区分开。
    外传列表页每行左上角都有 NEW / COMPLETE!!；详情页没有。
    这样详情页的『首次报酬 + 战斗』节点就不会在列表页上跨行误命中
    （旧 SideFight = And(首次报酬, 战斗) 正是因此反复去点已通关行）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        items = ocr_all(context, argv.image, ocr_entry)
        has_badge = any(
            (t.startswith("NEW") or t.startswith("COMPLETE")) for t, _b in items
        )
        if has_badge:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"no_badge": False, "reason": "有 NEW/COMPLETE 徽标，判定为列表页"},
            )
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 0, 0],
            detail={"no_badge": True},
        )


class ListAllDoneRecognition(CustomRecognition):
    """外传【关卡列表页·本页全清】识别（需求 #1）。

    命中条件：画面上存在 ≥1 个 COMPLETE!! 徽标，且【不存在任何 NEW 徽标】，
    且能解析出至少一个关卡行 —— 即这一页的关卡全部打完了。

    用途：某本外传的关卡列表全部 COMPLETE!! 后，next_stage 一个关卡都选不出来。
    若没有本节点，pipeline 既不退出也不收工 → 空转 41 分钟（现场根因）。
    命中本节点 ⇒ 退回「未通关」列表清下一个 / 收工。

    ★判据为什么不用「每行都 COMPLETE」★：现场截图（stuck1.png）里 4 个 COMPLETE!!
    徽标而只解析出 3 行（1 个徽标是滚出屏幕/未配对的），逐行判断会漏；用
    「有 COMPLETE + 无 NEW」这一条既覆盖完整，又不会把含 NEW 的未清页误判。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        items = ocr_all(context, argv.image, ocr_entry)
        if not items:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "OCR 无结果（OcrTask 缺失或不在可识别页面）"}
            )
        if side_list_all_done(items):
            n = _note_page_done()
            print(f"[list_all_done] 关卡列表已全部 COMPLETE!!（无 NEW）→ 本页全清（第 {n} 次）")
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"all_done": True, "page_done_count": n}
            )
        return CustomRecognition.AnalyzeResult(
            box=None, detail={"all_done": False}
        )


class PageDoneRepeatRecognition(CustomRecognition):
    """【收工判据·防空转】连续多次「本页全清」且其间没有任何关卡完成 → 命中。

    现场发现：某些外传的全部关卡都 COMPLETE!! 了，游戏却仍把它们留在「未通关」
    列表里（实测 5 张卡的关卡列表全是 COMPLETE!!、无 NEW）。这时：
        SidePageDone 退回列表 → SideClearEnterCard 又进第一张（还是全清页）→ 死循环。
    本节点在下一次进入全清页、且距上次「有实打实的关卡完成」(mark_done) 过近、
    已连续全清 N 次时命中 → 上层 StopTask 收工。对应需求「未通关列表也没有可进
    的卡片时，任务才结束」，保证绝不空转 41 分钟。

    计数与重置：
        · ListAllDoneRecognition 每次命中 +1（由 _note_page_done 维护）；
        · MarkDoneAction 每次真正记下一关时归零（_reset_page_done）——
          也就是说「全清 → 记账 → 全清 → 记账」这种正常推进不会被误判。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        try:
            threshold = int(param.get("threshold") or 3)
        except (TypeError, ValueError):
            threshold = 3
        items = ocr_all(context, argv.image, ocr_entry)
        if not side_list_all_done(items):
            return CustomRecognition.AnalyzeResult(box=None, detail={"repeat": False})
        count = _page_done_count()
        if count >= threshold:
            # ★#10 进度收工行★：这句**就是**既有收工文案（``SidePageDoneStop`` 的 StopTask），
            # 原样复用一份给 ``finish_progress`` —— 不造第二套 reason。
            reason = (
                f"连续 {count} 次全清页且其间无任何关卡完成 "
                f"→ 判定「未通关」无可进卡片，收工"
            )
            print(f"[page_done_repeat] {reason}")
            finish_progress(reason, argv)
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"repeat": True, "count": count}
            )
        return CustomRecognition.AnalyzeResult(
            box=None, detail={"repeat": False, "count": count}
        )


# 「本页全清」连续计数（给 PageDoneRepeatRecognition 用）。
_PAGE_DONE_LOCK = threading.Lock()
_PAGE_DONE_COUNT = 0
_PAGE_DONE_TS = 0.0
_PAGE_DONE_WINDOW = 300.0  # 超过这么久没有全清事件则重新计数


def _note_page_done() -> int:
    global _PAGE_DONE_COUNT, _PAGE_DONE_TS
    with _PAGE_DONE_LOCK:
        now = time.monotonic()
        if now - _PAGE_DONE_TS > _PAGE_DONE_WINDOW:
            _PAGE_DONE_COUNT = 0
        _PAGE_DONE_COUNT += 1
        _PAGE_DONE_TS = now
        return _PAGE_DONE_COUNT


def _page_done_count() -> int:
    with _PAGE_DONE_LOCK:
        return _PAGE_DONE_COUNT


def _reset_page_done() -> None:
    global _PAGE_DONE_COUNT
    with _PAGE_DONE_LOCK:
        _PAGE_DONE_COUNT = 0


# ===========================================================================
# ★#10 用户可见进度行（规格 docs/spec/progress-visibility.md §B/§C）★
# ===========================================================================
#: 进度行的显示名与单位（规格 §C 的 `外传` / 无固定上限 ⇒ ``total=0``）。
#: ★不许改成分母★：一本外传有几关由列表决定、打满为止，`i/N` 会编出一个假分母。
PROGRESS_DISPLAY = "外传"
PROGRESS_UNIT = "关"

_PROGRESS_LOCK = threading.Lock()
_PROGRESS = None            # 当前这条进度线（reporting.Progress）
_PROGRESS_TASK = None       # 它属于哪个 task_id（换任务即换新线，与 StallRecover 同口径）


def _task_id_of(argv):
    """``argv.task_detail.task_id``（拿不到返回 ``None`` = 不换线）。"""
    detail = getattr(argv, "task_detail", None)
    return getattr(detail, "task_id", None)


def _user_scope(scope) -> str:
    """给用户看的副本名：★内部兜底名（``default`` / ``__PENDING__``）不是副本名，别端上面板★。"""
    text = str(scope or "").strip()
    return "" if text.lower() in ("", "default", "__pending__", "none") else text


def progress_line(argv=None) -> reporting.Progress:
    """外传的进度行（★一任务一条；格式 / 去重 / 静音全在 :mod:`reporting`★）。

    ``total=0``：外传**没有固定分母**（列表是动态的、打满为止）—— 规格 §C 明确
    「total 未知就报 ``已 X <unit>``」，**不许为了凑 i/N 编分母**。
    """
    global _PROGRESS, _PROGRESS_TASK
    task_id = _task_id_of(argv)
    with _PROGRESS_LOCK:
        if _PROGRESS is None or (
            task_id is not None and _PROGRESS_TASK is not None and task_id != _PROGRESS_TASK
        ):
            _PROGRESS = reporting.Progress(PROGRESS_DISPLAY, total=0, unit=PROGRESS_UNIT)
            _PROGRESS_TASK = task_id
        elif task_id is not None and _PROGRESS_TASK is None:
            _PROGRESS_TASK = task_id
        return _PROGRESS


def start_progress(scope: str = "", argv=None) -> reporting.Progress:
    """开始打这本外传 ⇒ ``[进度] 外传 开始``（幂等）+ ``note=副本名``。

    调用点 = :class:`NextStageRecognition` **选中一关**的那一刻（= 账本真的开始推进）。
    ``start`` 幂等：一任务只出一条「开始」。
    """
    line = progress_line(argv)
    scope = _user_scope(scope)
    if scope:
        line.note = scope
    line.start()
    return line


def note_stage_done(scope: str = "", argv=None) -> str:
    """一关完成、**账本新增一笔** ⇒ ``[进度] 外传 已 X 关（副本名）``。

    步进的 ``X`` 由 :class:`reporting.Progress` 自己维护（单调去重）；★不借
    ``_PAGE_DONE_COUNT``★ —— 那是「本页连续全清」的防空转计数，不是「已打几关」。
    先 ``start()``（幂等）：保证「开始」永远排在第一条 step 之前。
    """
    line = progress_line(argv)
    scope = _user_scope(scope)
    if scope:
        line.note = scope
    line.start()
    return line.step()


def finish_progress(reason: str, argv=None) -> str:
    """收工出口（``SidePageDoneStop`` → ``StopTask`` 之前）⇒ ``[进度] 外传 收工：<既有文案>``。

    ``reason`` **必须**是既有收工原因原文（``page_done_repeat`` 打印的那一句），
    本函数不造第二套文案。``Progress.done`` 幂等 + 之后静默，多点调用安全。
    先 ``start()``（幂等）：保证面板上「开始」永远排在「收工」之前（顺序不倒）。
    """
    line = progress_line(argv)
    line.start()
    return line.done(str(reason or ""))


def reset_progress() -> None:
    """清空进度线（★只给测试 / 换任务用★；生产换任务由 ``task_id`` 自动换线）。"""
    global _PROGRESS, _PROGRESS_TASK
    with _PROGRESS_LOCK:
        _PROGRESS = None
        _PROGRESS_TASK = None


# ===========================================================================
# 「卡死自恢复」stall_recover（需求 #3）
#
# 用途：在【本该有进展】的流程里，判断画面是不是已经连续 N 秒没有变化了。
#       连续无变化达到阈值 ⇒ 命中（hit），上层据此收工 / 重开游戏。
#
# 算法（每次被调用时执行）：
#   1. 把当前图像缩成 <=64x64 的灰度特征（BGR 三通道取均值）。
#   2. 与「参考帧」（上一次判为「画面在动」时的画面）比较：
#        diff      = mean(|当前 - 参考|)            # 全帧平均差
#        moved_frac = mean(|当前 - 参考| > motion_eps)  # 显著变化格子占比
#      - diff > diff_threshold  或  moved_frac > motion_frac → 画面在动：
#        更新参考帧，重新计时。
#      - 否则 → 画面静止：沿用参考帧与计时起点。
#   3. 「距上次变化」的墙钟累计时间 >= threshold_sec → 命中。
#
# 为什么判据是「平均差 OR 显著变化占比」而不是只看平均差（#23 真机实证）
# --------------------------------------------------------------------
# 旧判据只看全帧平均差（默认阈值 3.0）。局部、持续的小动（主城界面里来回走动的
# 小精灵 / 闪烁特效）会被 4096 个下采样格子的平均稀释到 1~2，于是**画面明明在动、
# 规律循环**的流水线被误判成「连续 187.1s 无变化」→ 多余强杀重启（#13 第 3 次真机
# 运行，见 #23 Evidence）。真机拿到的帧（MAA debug/vision 里同一轮先跑的 OCR 整屏图，
# 720x1280）实证：
#   · 循环相邻两轮 64x64 灰度：平均差 1.20~2.10（全 < 3.0，旧判据漏判），
#     但显著变化格子占比 1.95%~3.44%（局部小动一目了然）；
#   · 真·冻结（同一帧对自身）：平均差 0、占比 0；
#   · 不同页面（主城↔列表↔详情，独立 3s 抓帧）：平均差 43~70、占比 56%~77%。
# 所以「只要有任何一块区域在动（占比 > motion_frac）就算画面在动」，而真·冻结
# （占比恒为 0）依旧会被抓到 —— 真阳性路径不变。
#
# 关键防误判：
#   - 调用间隔超过 gap_sec（例如中间执行了强杀重开这种阻塞动作）→ 视为新会话，
#     重新计时，绝不把「阻塞耗时」算成卡死时间。
#   - task_id 变化（重新开始一次任务）→ 清空状态。
#   - 首次调用永远只是「建立参考帧」，不会立刻命中。
#
# 实现放在 side_impl（不依赖 AgentServer），这样 MFAAvalonia 的 AgentServer 与
# clear_all/离线测试都能注册同一份。
# ===========================================================================
_STALL_LOCK = threading.Lock()
_STALL_TASK_ID = None
_STALL_LAST_CALL = None   # 上一次调用的单调时间
_STALL_REF = None         # 参考帧特征
_STALL_SINCE = None       # 参考帧最后一次变化的时间

# 「画面在动」判据的默认参数（可被 custom_recognition_param 覆盖）：
_STALL_MOTION_EPS = 8.0     # 单个格子算「显著变化」的灰度差（0-255）
_STALL_MOTION_FRAC = 0.004  # 显著变化格子占比超过它就算「画面在动」（0.4%）


def _stall_feature(image):
    """把图像转成 <=64x64 的灰度特征（float32）。"""
    a = np.asarray(image)
    if a is None:
        return np.zeros((1, 1), dtype=np.float32)
    if a.ndim == 3:
        a = a[:, :, :3].mean(axis=2)
    a = a.astype(np.float32)
    h, w = a.shape[:2]
    ys = np.linspace(0, h - 1, min(64, h)).astype(np.intp)
    xs = np.linspace(0, w - 1, min(64, w)).astype(np.intp)
    return a[np.ix_(ys, xs)]


def _stall_motion(feat, ref, motion_eps):
    """返回 (平均绝对差, 显著变化格子占比)。

    占比对「局部小动」敏感：一块区域在动时，平均差会被整帧稀释到 1~2，但占比
    会明显抬起来（真机实证 1.95%~3.44%），从而把「规律循环」与「画面停滞」分开。
    """
    d = np.abs(feat - ref)
    return float(np.mean(d)), float(np.mean(d > motion_eps))


class StallRecoverRecognition(CustomRecognition):
    """画面连续 N 秒无变化 → 命中。用于「点完没反应 / 卡死」的判定。

    参数（custom_recognition_param）：
        threshold_sec  : 连续无变化多少秒算卡死，默认 180
        diff_threshold : 全帧平均像素差阈值（0-255），默认 3.0
        motion_eps     : 单格算「显著变化」的灰度差（0-255），默认 8.0
        motion_frac    : 显著变化格子占比阈值，默认 0.004（0.4%）
        gap_sec        : 两次调用间隔超过该秒数就重新计时，默认 15
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        try:
            threshold = float(param.get("threshold_sec") or 180.0)
        except (TypeError, ValueError):
            threshold = 180.0
        try:
            diff_th = float(param.get("diff_threshold") or 3.0)
        except (TypeError, ValueError):
            diff_th = 3.0
        try:
            gap = float(param.get("gap_sec") or 15.0)
        except (TypeError, ValueError):
            gap = 15.0
        try:
            _me = param.get("motion_eps")
            motion_eps = float(_me) if _me is not None else _STALL_MOTION_EPS
        except (TypeError, ValueError):
            motion_eps = _STALL_MOTION_EPS
        try:
            _mf = param.get("motion_frac")
            motion_frac = float(_mf) if _mf is not None else _STALL_MOTION_FRAC
        except (TypeError, ValueError):
            motion_frac = _STALL_MOTION_FRAC

        now = time.monotonic()
        feat = _stall_feature(argv.image)
        task_id = getattr(argv.task_detail, "task_id", None)

        global _STALL_TASK_ID, _STALL_LAST_CALL, _STALL_REF, _STALL_SINCE
        with _STALL_LOCK:
            if task_id is not None and _STALL_TASK_ID is not None and task_id != _STALL_TASK_ID:
                _STALL_REF = None
                _STALL_SINCE = None
            if task_id is not None:
                _STALL_TASK_ID = task_id

            if (
                _STALL_REF is None
                or _STALL_LAST_CALL is None
                or (now - _STALL_LAST_CALL) > gap
                or _STALL_REF.shape != feat.shape
            ):
                _STALL_REF = feat
                _STALL_SINCE = now
                _STALL_LAST_CALL = now
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"stall": False, "reason": "reset", "elapsed": 0.0}
                )

            _STALL_LAST_CALL = now
            diff, moved_frac = _stall_motion(feat, _STALL_REF, motion_eps)
            # 画面在动 = 全帧平均差超阈值（大变化）**或**显著变化格子占比超阈值
            # （局部持续小动，如主城界面里走动的小精灵）——见文件头 #23 实证。
            if diff > diff_th or moved_frac > motion_frac:
                _STALL_REF = feat
                _STALL_SINCE = now
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={
                        "stall": False,
                        "reason": "changed",
                        "diff": round(diff, 2),
                        "moved_frac": round(moved_frac, 4),
                    },
                )

            elapsed = now - (_STALL_SINCE if _STALL_SINCE is not None else now)
            if elapsed >= threshold:
                _STALL_SINCE = now
                print(f"[stall_recover] 画面连续 {elapsed:.1f}s 无变化（阈值 {threshold}s）→ 判定卡死")
                return CustomRecognition.AnalyzeResult(
                    box=[0, 0, 0, 0],
                    detail={
                        "stall": True,
                        "elapsed": round(elapsed, 1),
                        "diff": round(diff, 2),
                        "moved_frac": round(moved_frac, 4),
                    },
                )

            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "stall": False,
                    "elapsed": round(elapsed, 1),
                    "diff": round(diff, 2),
                    "moved_frac": round(moved_frac, 4),
                },
            )


# ===========================================================================
# 「详情页战斗按钮」special_target_fight（P0 安全修复）
#
# 背景（用户实机看到的破坏性 bug）
# --------------------------------
# 旧实现是「OCR 认难度标题 → 按死偏移猜战斗按钮位置」：
#     SpecialFightTargetRow: 标题框中心 + (-185,+36)
#     SpecialFightNewRow   : NEW 徽标框中心 + (+60,+110)
# 实测详情页每行：难度名 720 (288,473)、【战斗】(103,509)、【推荐编成】(104,545)。
# 战斗与推荐编成只差 36px，标题 OCR 框只要低几像素，落点就掉进【推荐编成】——
# 这会把用户的队伍配置改掉（破坏性）。
#
# 修复思路
# --------
# 直接返回【战斗】按钮自己 OCR 出来的框（点击 = 框中心，零偏移），
# 用难度标题仅仅是为了「认哪一行」，不再用任何数值偏移去猜按钮位置。
# 这样点击点必然落在【战斗】框内，绝不可能落进【推荐编成】（已由离线断言证明）。
#
# 行的配对规则（无魔法偏移）：同一行里【战斗】按钮在难度名的【左侧】，
# 取「中心 x 更靠左、纵向落在同一行带内、且纵向间距最小」的那个【战斗】框。
# 这样对 OCR 漏认某行难度名也稳：漏认的行不会命中，其余行照样点对。
#
# ★#35 配对方向修正（真机几何）★
# --------------------------------
# 上面的「相对上下」在 #35 真机逐成员扫描里被证伪：详情页每行是
# 【难度名在上、战斗在其【下方 ≈40px】，且更靠左】——
#   recon_unm/recon.log 实测（720 空间）：
#     妖狐超级 y=456 → 战斗 y=501（+45）    妖狐高级+ y=648 → 战斗 y=689（+41）
#     妖狐高级 y=837 → 战斗 y=880（+43）    妖狐中级   y=1028 → 战斗 y=1068（+40）
#   单难度行成员（诅咒弧魔艾基尔讨伐 y=458 → 战斗 y=498）同样在下方。
# 旧默认 pair="above"（假设战斗在难度名【上方】）与真机相反，造成两类缺陷：
#   · 单难度行成员（屏幕上只有一行）上方没有任何战斗 → 永不命中 → SpecialEntry↔SpecialWait
#     卡死到超时（实测 6 个成员）；
#   · 多难度行成员配到【上一行】的战斗 → 静默打错难度（日志实证：中级行 y=1044 配到
#     y=890 的【高级】战斗，gap≈154）。
# 故默认改为真机几何：同行、更靠左、纵向最贴近的那一个战斗 —— 与「上/下」假设解耦。
# ===========================================================================

DEFAULT_BATTLE_REGEX = r"^战斗$"

# 真机几何默认：战斗在难度名【下方】（#35，recon_unm/recon.log）。
DEFAULT_PAIR = "below"
# 同一行「难度名 → 战斗」的纵向间距带（720）：实测 ≈36~45px（见上）。
BATTLE_ROW_DY = 40
# 允许的最大纵向间距：锁死「同一行」，绝不配到相邻难度行（相邻行间距实测 ≈190px）。
BATTLE_ROW_MAX_GAP = 120

# ★#43★ 单字 OCR 误差韧性（真机缺陷：MAA 原始帧重采样把【战斗】读成 `战三`）
# ---------------------------------------------------------------------------
# 现场（成员 `无猾机兵`，设备 16448）：详情页导航成功却 6.5 分钟卡死、未开打。
# 根因：MAA 调试日志 `debug\maafw.bak.*-04.37.29.7.log` 里 **85/85** 条 OcrTask
# 都把这一个【战斗】按钮读成 `战三`，而战斗按钮的匹配是严格 `^战斗$` → 永不命中
# → 详情页无法推进 → `SpecialWait ⇄ SpecialEntry` 循环到超时。
# ★同一帧存成 jpg 后离线 OCR 又能正确读出 `战斗`★ → 差异来自 MAA 原始帧重采样，
# 不是这一帧特例，所以必须让匹配对「单字字形读错」有韧性。
#
# 做法（只放宽字形，绝不放宽几何/归属）：
#   · 严格正则（:data:`DEFAULT_BATTLE_REGEX`）先判，命中即 "exact"（原行为不变）；
#   · 否则，若文本与某个规范文本（:data:`DEFAULT_BATTLE_TERMS`，默认 `战斗`）**等长**
#     且**只有一个字形不同**（= 单字替换误差，如 `战三`）→ "approx"。
#   · 近似候选**必须**照旧满足几何（声明的难度名同一行的左下方 ≈40px、≤max_gap）
#     并通过 :func:`_row_owner_name` 的「同一行难度名」回指证明 —— 因此 #35 的
#     「绝不点到相邻行的战斗」保证原样成立：近似只是让本行的战斗在字形读错时仍可
#     命中，绝不会因此窜到别的行（相邻行间距 ≈190px > max_gap，几何先挡掉）。
DEFAULT_BATTLE_TERMS = ("战斗",)
#: 允许的「单字替换」误差位数（1 = 只容忍一个字形读错；0 = 退化为纯严格匹配）。
BATTLE_APPROX_MAX_SUBST = 1

# ★#49★ 单字 OCR【截断】韧性（真机：文字检测把 `战斗` 塌缩成【单字框】 `战`）
# ---------------------------------------------------------------------------
# 现场（设备 16448，降临讨伐 Q1 全量扫描）：29 个成员里 25 个正常，**4 个**导航到
# **自己**的详情页（#42 身份 match）、却 **定位不到【战斗】按钮** → `special_target_fight`
# 找不到战斗框 → 详情页无法推进 → 空转到任务超时（**账本为空，无假记账**）。
# 真机帧离线 OCR 实证（同一 OcrTask：`assets/resource/model/ocr/{det,rec}.onnx`）：
#   · 赤之女王   s01  f_s01_015：战斗 → **`战`**（单字），框 [91, 505, 14, 9]（宽 14 ≈ 半宽）
#   · 方舟守护者 r4   f_r4_020 ：战斗 → **`战`**（单字），框 [88, 501, 19, 17]
#   · 青之女王   r5   f_r5_025 ：战斗 → **`战`**（单字），框 [92, 506,  9,  7]
#   · 伊尔梅塔雷 s06  f_s06_010：战斗 → `战头`（斗→头，单字替换 —— #43 通道可救）
# 而 25 个正常成员的同一按钮读作 `战斗`（框宽 ≈28~34）。差别只在**第二个字形「斗」**：
# 白字叠在 **Boss 立绘缩略图**（深色 / 高纹理）上，检测器把两字标签**塌缩成单字框**
#   （★注意：是【文字检测】塌缩、不是识别读错 —— 框宽只剩半字宽，读出的 `战` 本身是对的）。
# #43 的近似只覆盖「等长 + 单字替换」（`战三` / `战头`），**不覆盖「丢字」** → s01/r4/r5 仍不命中。
#
# 做法（只放宽字形长度，绝不放宽几何 / 归属）：
#   · 若文本是某个规范文本（默认 `战斗`）的**真前缀**，且**只少 ≤ max_missing 个尾字**
#     （默认 1，即单字 `战`）→ ``"approx_trunc"``；
#   · 截断候选**必须**照旧通过几何（同一行、声明难度名的左侧下方 ≈40px、≤max_gap）+
#     :func:`_row_owner_name` 的行主回指，且**必须**能回指到同一行难度名才放行 ——
#     因此「截断把战斗配错行」不可能发生（与 #43 同构，绝不重新引入 #35/#42 的风险）；
#   · **只在声明了难度时**才启用截断通道（topmost 无难度路径照旧）—— 截断读很弱，
#     必须由「声明难度行」的几何 + 行主证明兜底，绝不在无归属证明时放行。
#
# ★诚实边界★：若 OCR **连单字框都没有**（该行完全没检测到文本），**绝不**凭空造坐标 ——
#   战斗与【推荐编成】只差 ≈36px，凭空偏移会点到推荐编成（改队伍配置，破坏性，见 #35 背景）。
#   本通道只救「有框但丢尾字」，**不救「完全无框」**（那属于 OCR 模型下界，另行上报）。
#: 允许的「丢尾字」位数（1 = 容忍缺 1 个尾字，即单字 `战`；0 = 关掉截断通道）。
BATTLE_APPROX_MAX_MISSING = 1


def battle_text_match(
    text,
    battle_regex: str = DEFAULT_BATTLE_REGEX,
    terms=DEFAULT_BATTLE_TERMS,
    max_subst: int = BATTLE_APPROX_MAX_SUBST,
    max_missing: int = BATTLE_APPROX_MAX_MISSING,
):
    """【战斗】按钮文本判定：``"exact"`` / ``"approx"`` / ``"approx_trunc"`` / ``None``。

    * ``exact``       —— 命中 ``battle_regex``（原判据，行为不变）；
    * ``approx``      —— ★#43★ 与某个规范文本（默认 ``战斗``）**等长**且**只有 ≤ ``max_subst``
                         个字形不同**（单字替换误差，如真机 `战三` / `战头`）；``max_subst=0``
                         时不产生该通道；
    * ``approx_trunc``—— ★#49★ 文本是某个规范文本的**真前缀**，且**只少 ≤ ``max_missing``
                         个尾字**（丢字误差，如真机把 `战斗` 检测成单字 `战`）；``max_missing=0``
                         时不产生该通道；
    * ``None``        —— 都不是。

    只判字形，**不判位置**：位置/归属仍由 :func:`pick_target_battle_box` 的几何 +
    :func:`_row_owner_name` 回指负责（因此本函数可在离线守卫里单独断言）。
    """
    t = text or ""
    if re.search(battle_regex, t):
        return "exact"
    if max_subst > 0:
        for term in terms or ():
            if not term or len(t) != len(term):
                continue
            diff = sum(1 for a, b in zip(t, term) if a != b)
            if diff <= max_subst:
                return "approx"
    if max_missing > 0 and t:
        for term in terms or ():
            if not term or len(t) >= len(term):
                continue
            if len(term) - len(t) <= max_missing and term.startswith(t):
                return "approx_trunc"
    return None


def _center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _difficulty_name_regex() -> str:
    """任一难度档位的行名识别正则（由 :data:`batch_plan.DIFF_REGEX` 组合）。

    仅用于「把战斗框回指到同一行的难度名」——判据是**数据真源的难度词表**，
    不另写一份（ADR-0001）。
    """
    return "|".join(DIFF_REGEX.values())


def _row_owner_name(items, battle_box, difficulty_regex: str,
                    max_gap: int = BATTLE_ROW_MAX_GAP):
    """把某个【战斗】框回指到它【同一行】的难度名框（真机几何，见 #35）。

    判据（与「声明的难度」无关，纯几何 —— 因此可用于独立证明归属）：
      · 难度名在战斗的【右侧】（真机：名 x≈261~329 > 战斗 x≈103）；
      · 难度名在战斗的【上方 ≈40px】（真机：名 y=456 → 战斗 501，dy≈36~45）；
      · 纵向间距落在同一行带内（≤ :data:`BATTLE_ROW_MAX_GAP`，绝不跨到相邻行）。
    返回 ``(name_text, center, dy)``（取纵向最贴近的一个），或 None。
    """
    bcx, bcy = _center(battle_box)
    best = None
    for t, b in items:
        if not re.search(difficulty_regex, t or ""):
            continue
        ncx, ncy = _center(b)
        if ncx <= bcx:            # 难度名必须在战斗【右侧】
            continue
        dy = bcy - ncy
        if dy <= 0 or dy > max_gap:   # 且在同一行带内（#35 名在上、战斗在下）
            continue
        if best is None or dy < best[2]:
            best = (t, (ncx, ncy), dy)
    return best


def pick_target_battle_box(
    items,
    difficulty=None,
    battle_regex: str = DEFAULT_BATTLE_REGEX,
    max_gap: int | None = None,
    pair: str = DEFAULT_PAIR,
    battle_terms=DEFAULT_BATTLE_TERMS,
    battle_approx_max_subst: int = BATTLE_APPROX_MAX_SUBST,
    battle_approx_max_missing: int = BATTLE_APPROX_MAX_MISSING,
    owner_regex: str | None = None,
):
    """在 OCR 结果 items=[(text, box), ...] 里挑出目标行的【战斗】按钮框。

    · difficulty 给定（行名正则，如 "高级$" / "光之迷宫初级"）：找到该行名 →
      返回它所在行（纵向间距最小）的【战斗】按钮框；
    · difficulty 为空：返回最靠上的【战斗】按钮框（未通关的 NEW 行永远在最上面）。

    pair 决定「战斗」相对行名的位置（不同页面版式不同，★绝不靠数值偏移猜★）：
    · "below"（默认，真机几何 #35）：领主战 / 降临讨伐详情页、旅途的迷宫列表页 ——
      战斗在行名的【左下方】≈40px（见上方 #35 实测表）；
    · "above"：仅保留给历史/对照版式；详情页**不再**使用（真机证伪，见上）。

    max_gap 缺省（None）取同一行实测带 :data:`BATTLE_ROW_MAX_GAP`（120）—— 锁死
    「同一行」，绝不配到相邻难度行的战斗（相邻行间距 ≈190px）。

    ★#43★ battle_terms / battle_approx_max_subst：除严格匹配外，再接纳「与规范文本
    等长、且只有一个字形不同」的近似候选（真机把 `战斗` 读成 `战三`）。近似候选同样要过
    几何 + 行主证明，故不会窜到相邻行；``battle_approx_max_subst=0`` 即关掉替换通道。

    ★#49★ battle_approx_max_missing：再接纳「是规范文本真前缀、只少 ≤ 该位数尾字」的
    截断候选（真机把 `战斗` 检测成单字 `战`）。**只在声明了 difficulty 时启用**（弱读必须
    由声明难度行的几何 + 行主回指兜底；topmost 无难度路径照旧不放行），且截断框**必须**
    能回指到同一行难度名才返回 —— 故同样不会窜行（与 #43 同构）。``battle_approx_max_missing=0``
    即关掉截断通道。

    返回 (box | None, detail)。box 恒为【战斗】的 OCR 框，或 None。

    ★#54★ owner_regex：归属回指时「谁算一个行名」的候选正则（缺省 = 难度词表）。迷宫路径
    传 ``maze_owner_regex()``（全部迷宫行名），故回归证明的是「选中的战斗框属于**声明的那个
    行**」，绝不落到相邻 / 别的行。
    """
    below = str(pair or DEFAULT_PAIR).lower() == "below"
    if max_gap is None:
        max_gap = BATTLE_ROW_MAX_GAP

    # ★#43★ 候选 = 精确匹配（原判据）+ 单字 OCR 误差的近似匹配；精确恒排在近似之前
    #   （同分时精确胜出）。近似只放宽字形，几何与行主证明（见下）照旧 —— 所以
    #   「近似匹配把战斗配错行」不可能发生。
    # ★#49★ 截断通道只在**声明了难度**时启用：弱读必须由「声明难度行」的几何 + 行主
    #   回指兜底；topmost（无难度）路径照旧不放行。
    cand_max_missing = battle_approx_max_missing if difficulty else 0
    exact: list = []
    approx: list = []
    for t, b in items:
        kind = battle_text_match(
            t, battle_regex, battle_terms, battle_approx_max_subst, cand_max_missing
        )
        if kind == "exact":
            exact.append((t, list(b), kind))
        elif kind in ("approx", "approx_trunc"):
            approx.append((t, list(b), kind))
    battles = exact + approx
    if not battles:
        return None, {"reason": "未找到战斗按钮", "difficulty": difficulty, "pair": pair}

    if not difficulty:
        # 稳定排序：同 y 时保留「精确在前」的顺序（精确候选已有更高优先级）。
        battles.sort(key=lambda tb: _center(tb[1])[1])
        return battles[0][1], {
            "reason": "topmost",
            "picked": _center(battles[0][1]),
            "n_battles": len(battles),
            "battle_text": battles[0][0],
            "battle_match": battles[0][2],
        }

    names = [
        (t, list(b)) for t, b in items
        if re.search(difficulty, t or "")
    ]
    if not names:
        return None, {"reason": "未找到目标行名", "difficulty": difficulty,
                      "pair": pair, "n_battles": len(battles)}

    # 同屏通常只命中一行；多行时取最靠上的一行。
    names.sort(key=lambda tb: _center(tb[1])[1])
    name_text, name_box = names[0]
    ncx, ncy = _center(name_box)

    best = None
    best_gap = 0
    best_kind = None
    best_text = None
    best_key = None
    for _t, b, kind in battles:
        bcx, bcy = _center(b)
        gap = (bcy - ncy) if below else (ncy - bcy)
        if gap <= 0 or gap > max_gap:      # 战斗必须在行名的一侧、且不太远
            continue
        if bcx >= ncx:                      # 战斗按钮在行名左列
            continue
        # ★#43★ 同分时精确匹配优先（近似只在本行战斗字形读错时兜底）。
        # ★#49★ 单字截断（丢尾字）优先级最低：exact > approx（单字替换）> approx_trunc。
        rank = {"exact": 0, "approx": 1, "approx_trunc": 2}.get(kind, 2)
        key = (abs(gap), rank)
        if best is None or key < best_key:
            best, best_gap, best_kind, best_text, best_key = b, gap, kind, _t, key

    if best is None:
        return None, {"reason": "行名侧未找到战斗按钮",
                      "difficulty": difficulty, "pair": pair,
                      "name": (ncx, ncy), "name_text": name_text,
                      "n_battles": len(battles)}
    # ★#35 归属证明★：把「选中的战斗框」回指到它【同一行】的难度名（不分声明），
    # 用于日志/账本证明「打的是声明的难度」而不是「某一行的战斗」。
    # ★#54★ owner_regex 可覆盖「谁算一个行名」的候选宇宙：领主战 = 难度词表（默认）；
    #   迷宫 = 全部迷宫行名（maze_owner_regex），于是回指证明的是「声明的那一行」。
    owner = _row_owner_name(items, best, owner_regex or _difficulty_name_regex())
    if owner is not None and not re.search(difficulty, owner[0] or ""):
        # 选中的战斗框同一行的难度名【不是】声明的难度 → 宁可不打（绝不静默打错难度）。
        return None, {
            "reason": "战斗框所属难度名与声明不符",
            "difficulty": difficulty, "pair": pair,
            "name": (ncx, ncy), "name_text": name_text,
            "row_owner": owner, "picked": _center(best),
            "n_battles": len(battles),
        }
    # ★#49★ 截断读是最弱的证据（只读到半个标签）：**必须**能回指到同一行难度名才放行 ——
    #   无归属证明就不采用弱读（宁可超时，绝不凭弱读点错）。
    if best_kind == "approx_trunc" and owner is None:
        return None, {
            "reason": "截断读无法回指到同一行难度名（#49，不放行）",
            "difficulty": difficulty, "pair": pair,
            "name": (ncx, ncy), "name_text": name_text,
            "battle_text": best_text, "picked": _center(best),
            "n_battles": len(battles),
        }
    return best, {
        "reason": "paired",
        "pair": pair,
        "difficulty": difficulty,
        "name": (ncx, ncy),
        "name_text": name_text,
        "battle_text": best_text,
        "battle_match": best_kind,   # ★#43★ "exact" / "approx"（供日志/守卫核对误差通道）
        # ★#49★ 新增通道值 "approx_trunc"（单字截断，丢尾字，如真机 `战`）。
        "picked": _center(best),
        "gap": best_gap,
        "row_owner": owner,
        "n_battles": len(battles),
    }


@dataclass(frozen=True)
class _DiffOutcome:
    """详情页难度发现的纯结果（#39）：outcome + 声明难度 + 该成员实读可用集。

    ``outcome`` ∈ ``{"present", "absent", "undetermined", "not_applicable"}``。
    """

    outcome: str
    declared: str | None
    available: frozenset


def discover_difficulties(items):
    """详情页 OCR 结果 ``items=[(text, box), ...]`` -> 该成员【实际可用】的难度集（运行时发现）。

    ★这是 #39 的「真值」★：同一成员在不同账号进度下可用难度**不同**（已通关账号 4 档、
    早期账号只有 ``中级``），因此静态按成员难度表**按定义就会错** —— 真机必须以本函数
    读到的详情页难度行为准。

    判据：页面上出现了某难度档的**行名**（如「皓之女王超级」/「红机兵海茵莱特中级」）⇒
    该档可用。难度词表来自 ``batch_plan.DIFF_REGEX``（= ``scene.config.DIFFICULTIES``
    派生，ADR-0001 单一真源），不在本地另写一份。
    """
    found: set[str] = set()
    for text, _box in items:
        for d, rx in DIFF_REGEX.items():
            if re.search(rx, text or ""):
                found.add(d)
    return frozenset(found)


def declared_difficulty(row_regex):
    """把「声明的难度行名正则」还原成难度档（如 ``高级\\+$`` -> ``高级+``）；不认识则 None。

    只有**纯难度正则**（= :data:`DIFF_REGEX` 的某个值）才参与「运行时发现」的判定；farm 的
    ``target``（如 ``光之迷宫初级``）不是纯难度正则 → None → 不参与（保持旧行为不变）。
    """
    if not isinstance(row_regex, str):
        return None
    for d, rx in DIFF_REGEX.items():
        if row_regex == rx:
            return d
    return None


# 详情页独有元素（与 pipeline ``SpecialDetailGate`` 同源）：用来把「读不到难度」限定在详情页，
# 免得在主城 / 列表 / 编队页上把「本就没难度行」误判成「难度不可判定」。
#
# ★#41（#39 的回归）★：本标记是判定「当前在详情页」的【唯一】依据 —— 与
#   ``assets/resource/pipeline/special_dungeon.json::SpecialDetailGate`` 的 OCR 判据、
#   ``scene.page_rules`` 的「详情页」规则同源（``scene.drift`` 把三者钉在一起）。
#   绝不能退回「画面上出现过某个难度词 = 在详情页」：主城轮播横幅会被 OCR 误读成
#   难度词（真机 16448 横幅 ``地狱级`` @[33,240,53,20]；16384 ``超级`` @[37,154,41,20]），
#   而那种帧【不是】详情页 —— 松散判据会让成员在导航开始之前（主城帧上）被假判 absent。
_DETAIL_PAGE_MARKER = "推荐编成"


def on_detail_page(items) -> bool:
    """当前帧是否【副本详情页】。★纯函数★（离线可单测，不碰设备）。

    判据 = 画面上出现详情页独有标记 :data:`_DETAIL_PAGE_MARKER`（``推荐编成``，
    与 pipeline ``SpecialDetailGate`` 同源）。

    ★#41★ 绝不以「出现过某个难度词」为准（那是 #39 的过松判据，主城横幅会误读成
    难度词）—— 主城 / 关卡列表 / 页签 / 战斗 HUD / 结算等帧一律返回 ``False``，
    于是那些帧上的难度发现判为 ``not_applicable``，绝不触发跳过。
    """
    return any(re.search(_DETAIL_PAGE_MARKER, t or "") for t, _b in items)


def classify_detail_difficulty(items, row_regex) -> _DiffOutcome:
    """详情页 OCR -> :class:`_DiffOutcome`。★纯函数★（离线可单测，不碰设备）。

    * ``present``        : 声明难度在详情页读到的可用集内（正常开打）；
    * ``absent``         : 在详情页上，但声明难度**不在**可用集内（该成员此账号没有这一档）
                           → 由上层「跳过该目标 / 收工并记录原因」（绝不静默打错档）；
    * ``undetermined``   : 在详情页上，却**读不到任何难度档**（无法判定）→ 必须主动收工；
    * ``not_applicable`` : 不是详情页 / 声明的不是纯难度正则 → 交给旧配对逻辑（不新造行为）。

    ★#41★ 「在不在详情页」只认 :func:`on_detail_page`（``推荐编成`` 标记）；
    难度发现**只在详情页上评估**，非详情页一律 ``not_applicable``。
    """
    declared = declared_difficulty(row_regex)
    available = discover_difficulties(items)
    if declared is None or not on_detail_page(items):
        return _DiffOutcome("not_applicable", declared, available)
    if declared in available:
        return _DiffOutcome("present", declared, available)
    if not available:
        return _DiffOutcome("undetermined", declared, available)
    return _DiffOutcome("absent", declared, available)


def plan_absent_difficulty_action(
    outcome: str, declared, available, *, batch_active: bool, has_current: bool
):
    """★纯函数★：详情页难度发现（absent / undetermined）-> 指挥官该做什么。

    返回 ``(action, reason)``，``action`` ∈ ``{"skip", "stop", "none"}``：

    * ``absent`` 且批量激活且有当前目标 → ``skip``：**跳过该目标、继续批量**，原因写清楚；
    * ``absent`` 其它情况（单目标 / 无目标可继续）→ ``stop``：明确收工并记录原因；
    * ``undetermined`` → ``stop``：读不到任何难度档，无法判定 → **绝不盲目开打**；
    * 其余（present / not_applicable）→ ``none``（不介入）。

    ★选择说明★：单一账号不同成员都能复现「声明难度不存在」，而一个批量清单里往往还有别的
    目标 —— 因此**跳过并继续**是默认行为（不因一个目标把整批毁掉），但原因**必须**记录；
    只有在没有别的目标可继续（单目标 / 清单剩余为空）或**连难度都读不到**（无法可信判定）时
    才**主动收工**。两者都绝不「静默打错档」、也绝不「卡死」。
    """
    avail = "、".join(sorted(available)) or "（空）"
    if outcome == "absent":
        if batch_active and has_current:
            return "skip", (
                f"声明的难度「{declared}」在该成员详情页不存在"
                f"（此账号实读可用难度：{avail}）→ 跳过该目标、继续批量"
            )
        return "stop", (
            f"声明的难度「{declared}」在该成员详情页不存在"
            f"（此账号实读可用难度：{avail}）→ 收工（没有其他目标可继续）"
        )
    if outcome == "undetermined":
        return "stop", (
            f"详情页读不到任何难度档，无法判定「{declared}」是否可用 → 主动收工（绝不盲目开打）"
        )
    return "none", ""


def plan_undetermined_difficulty_action(
    declared, elapsed, *, limit=None,
    batch_active: bool, has_current: bool, remaining_other: int,
):
    """★纯函数★（#62 对 #39/#41 难度发现的协同）：详情页**读不到任何难度档**时的**有界**行为。

    返回 ``(action, reason)``，``action`` ∈ ``{"retry", "skip", "stop"}``：

    * ``elapsed < limit`` → ``retry``：这一帧多半是【详情页还在加载】—— 难度行尚未渲染、
      横幅标题被读成顶栏的「活动时间」（真机 chunk_62 实测：碧之女王 re-navigate 后第一帧
      就是这种）。给一个**有界**的重试窗口，绝不立刻收工、也绝不空转（超窗即处置）。
    * 超窗 + 批量且清单里还有别的目标 → ``skip``：**记明原因跳过该目标、继续清单**；
    * 超窗 + 单目标 / 无目标可继续 → ``stop``：**主动收工并记录原因**。

    ★与 #39 的分工★：``absent``（读得到别的难度行，只是缺声明的那一档）是**可信**结论，仍走
    :func:`plan_absent_difficulty_action`（立刻 skip/stop，不重试）；本函数只接管 ``undetermined``
    ——「一档都读不到」既可能是真没有，也可能只是**页面还没画完**，故必须有界重试后再处置。
    两者都绝不「盲目开打」、也绝不「无界重试」。
    """
    if limit is None:
        limit = _UNFIGHTABLE_DETAIL_SEC
    if elapsed < limit:
        return "retry", (
            f"详情页读不到任何难度档（声明「{declared}」）—— 已持续 {elapsed:.0f}s / 上限 "
            f"{limit:.0f}s，疑似详情页仍在加载 → 有界重试（#62：超窗即明确跳过/收工）"
        )
    if batch_active and has_current and remaining_other > 0:
        return "skip", (
            f"详情页 {elapsed:.0f}s 内始终读不到任何难度档（声明「{declared}」），无法判定该档"
            f"是否可用 → 记明原因跳过该目标、继续清单（还剩 {remaining_other} 个目标；"
            f"#39/#62：绝不盲目开打、绝不无界重试）"
        )
    return "stop", (
        f"详情页 {elapsed:.0f}s 内始终读不到任何难度档（声明「{declared}」），无法判定该档"
        f"是否可用 → 主动收工并记录原因（没有别的目标可继续；#39/#62：绝不盲目开打）"
    )


# ===========================================================================
# ★#42 列表选行「错位」→ 静默打了别的成员（请求 A、打开 B、还记成 A）★
#
# 现场（真机实证：本票的两个复现 + #36 的一次同形观察）
# ----------------------------------------------------
#   · r9：目标 `伊劳德雷斯讨伐`（中级）→ 打开的却是【碧之女王】的详情页
#     （帧 `joss_r9/f_0070.jpg` = 碧之女王高级/中级；该帧的难度行主 = `碧之女王中级`），
#     这一局仍被账本记成 `伊劳德雷斯讨伐` → 用户以为打了 A、实际打了 B、账本还记着 A。
#   · C3：目标 `水狂精灵兽`（中级）→ 打开的是【圣夜的淘气鬼】的详情页
#     （帧 `joss_C3/f_0010.jpg`：难度行 `圣夜的雪像G中级`），同样被记成 `水狂精灵兽`。
#   · #36 早先也见过一次同形（请求 `寄居蟹船长讨伐`、打开 `诅咒弧魔艾基尔讨伐`），
#     两种几何下都没复现 —— 那正是「只认难度行、不认成员」这套判据的盲区。
#
# 为什么此前是【静默】的
# ----------------------
#   `special_target_fight` 只用【难度行正则】（如 `中级$`）挑行 —— 而**每个成员的详情页
#   都有「中级」行** → 「谁的详情页都命中」；随后 `SpecialBatchFinishAction` 在结算帧
#   直接按「当前目标」记一场账本（`cur.dungeon`），**从不回头核对打开的是谁的页面**。
#   于是「打错成员」被完整地伪装成一次成功 —— 比卡死更糟（卡死看得出来，这个看不出来）。
#
# 本闸（两道，缺一不可）
# ----------------------
#   1) **选行点击复核**（`SpecialBatchFightAction` 的 `row_click` 分支）—— 点击前【立刻重抓
#      一帧】并在列表体内复核目标行：目标行还在 → 用【新框】点击（两次框的位移进日志 = 竞态
#      证据）；目标行不在 → **不点**（绝不按陈旧坐标点到别人的行上）。
#   2) **详情页身份校验**（`detail_page_identity`）—— 进入战斗前先读详情页横幅大标题，把它
#      归属到「最像它的那个已知成员」：归属结果必须是**目标成员**，否则不命中（`box=None`）
#      → 绝不在这页开打，也就绝不会被记成目标成员。指挥官见 `_wrong_detail_*`：**退回并
#      重新导航**；连续超限则把该目标记为**失败/跳过**并写明原因（绝不静默）。
#
# 判据都是纯函数（离线可单测）；真机帧实证 + 破坏实验见 `tools/contract_hooks/hooks_42.py`：
#   目标 A / 页面 B **必须被拒**（r9 的 伊劳德雷斯↔碧之女王、C3 的水狂↔圣夜的淘气鬼）。
# ===========================================================================

# 详情页横幅（大标题）所在竖直范围（720）：标题实测 y≈166~300（碧之女王 y=214、
# 圣夜的淘气鬼 y=166、妖狐 y=192），而「推荐编成」行 y≈530 —— 320 足够宽松地切在两者之间。
DETAIL_TITLE_MAX_Y = 320
# 标题框最小面积（720）：滤掉图标数字/小字；横排大标题实测面积 1.3 万~13 万。
DETAIL_TITLE_MIN_AREA = 1500
# 标题 OCR 置信度下限：低于它视为「读不准」（此时**不判错页**，避免因为 OCR 噪声误拒正确页面）。
DETAIL_TITLE_MIN_SCORE = 0.55
# 目标成员与标题的字符相似度达到它即认为「这页就是目标的」。
IDENTITY_MATCH_MIN = 0.5
# 另一个已知成员若以这个相似度「更像」标题，则判「错页」（无需再比目标）。
IDENTITY_DOMINANT_MIN = 0.8
# 目标相似度不足时，另一个已知成员以这个相似度「更解释得通横幅」→ 也判「错页」。
# （= 与 MATCH_MIN 同值：横幅要么归属目标、要么归属别人；都不归属才允许「无法判定」。）
IDENTITY_OWNER_MIN = 0.5
# 详情页横幅里一定不是标题的固定文案（列表页/详情页的常驻标签与数值）。
_IDENTITY_CHROME = (
    "降临讨伐",
    "领主战",
    "BOSS BATTLE",
    "兑换道具",
    "更新列表",
    "推荐编成",
    "活动进行中",
    "首次报酬",
    "体力",
    "推荐属性",
)
# 列表体（720）：上沿 = 固定条之下（真机 440），下沿 = 底导带上沿（真机 1180）。
# 选行复核只在【列表体】内找目标行 —— 绝不把底导标签 / 顶部固定条当成行。
ROW_BODY_TOP = 440
ROW_BODY_BOTTOM = 1180
# 「同一行」的纵向容差（720）：行高实测 ≈144px，取半行略多以防行内抖动误报竞态。
ROW_KEYLINE_BAND = 90


def _as3(items):
    """把 ``[(text, box)]`` / ``[(text, box, score)]`` 统一成 3 元组（容错）。"""
    out = []
    for it in items or []:
        if not it:
            continue
        text = it[0] if len(it) > 0 else ""
        box = it[1] if len(it) > 1 else None
        try:
            score = float(it[2]) if len(it) > 2 and it[2] is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        out.append(((text or "").strip(), box, score))
    return out


def _ocr_scored(context, image, entry: str = "OcrTask"):
    """借 pipeline 的 OcrTask 做全屏 OCR，返回 ``[(text, box, score)]``（box = 720 空间）。

    与 :func:`maa_util.ocr_all` 同一机制，只是**多带 score** —— 详情页标题的置信度是
    「可不可信」的判据（#42：读不准就不判错页，绝不因为 OCR 噪声误拒正确页面）。
    旧框架 / 离线 stub 读不到 ``all_results`` 时返回空表（绝不臆断）。
    """
    try:
        detail = context.run_recognition(entry, image)
    except Exception as exc:  # noqa: BLE001 —— 判页失败不是致命错误，但必须可见
        print(f"[#42] OCR 失败（{entry}）：{exc}")
        return []
    results = getattr(detail, "all_results", None) if detail is not None else None
    out = []
    for r in results or []:
        box = getattr(r, "box", None)
        if box is None:
            continue
        try:
            box = [int(v) for v in box]
        except (TypeError, ValueError):
            continue
        if len(box) != 4:
            continue
        try:
            score = float(getattr(r, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        out.append(((getattr(r, "text", "") or "").strip(), box, score))
    return out


def _norm_name(text) -> str:
    """归一化名字：去掉空白与常见装饰（比较用，不改原串）。"""
    return re.sub(r"[\s·・:：]", "", str(text or ""))


def _core_name(name) -> str:
    """成员行名 → 核心名（去掉结尾的「讨伐」；OCR 的横幅标题一般不带它）。"""
    return re.sub(r"讨伐$", "", _norm_name(name))


def _char_similarity(base, other) -> float:
    """以 ``base`` 为分母的字符集相似度：``|base ∩ other| / |base|``（去重；base 空为 0）。

    ★为什么按 base 归一★：要比较的是「这个标题能不能解释**这个成员**」——所以分母是
    成员名自己的字数。它对称地让「短名成员」（妖狐）与「长名成员」（圣夜的淘气鬼）
    各自有可比的 0~1 分；用 base 归一也正是 observed 数据的量纲（圣夜的淘气鬼 6 字中
    OCR 读出 3~4 个 → 0.5~0.67；碧之女王 4 字全读出 → 1.0）。
    """
    sb = set(_norm_name(base))
    if not sb:
        return 0.0
    so = set(_norm_name(other))
    return len(sb & so) / float(len(sb))


def _pick_detail_title(items, max_y: int = DETAIL_TITLE_MAX_Y):
    """详情页横幅大标题：y 在横幅带内、非固定文案、面积最大的那条 OCR。

    返回 ``{"text","box","score","area"}`` 或 ``None``（读不到就返回 None，绝不臆断）。
    """
    best = None
    for text, box, score in _as3(items):
        if not box or len(box) != 4:
            continue
        _x, y, w, h = box
        if w <= 0 or h <= 0 or (y + h / 2.0) > max_y:
            continue
        t = _norm_name(text)
        if not t or any(c in t for c in _IDENTITY_CHROME):
            continue
        if score and score < DETAIL_TITLE_MIN_SCORE:
            continue  # 有置信度且太低 → 不是可信的标题（拿它判错页只会误伤）
        area = w * h
        if area < DETAIL_TITLE_MIN_AREA:
            continue
        if best is None or area > best["area"]:
            best = {"text": text, "box": list(box), "score": score, "area": area}
    return best


def detail_page_identity(items, member, universe=None):
    """详情页 OCR → 该页是不是 ``member`` 的详情页。★纯函数★（离线可单测）。

    返回 ``(verdict, info)``，``verdict`` ∈ ``{"not_detail", "unknown", "match", "mismatch"}``：

    * ``not_detail`` 页面上没有详情页独有元素（``推荐编成``）→ 本闸**不介入**（列表页等）；
    * ``unknown``    在详情页，但横幅归属不了任何已知成员 → **无法判定**（不拒绝）；
    * ``match``      横幅归属到**目标成员** → 放行（这页可以开打）；
    * ``mismatch``   横幅明确归属【别的】已知成员 → **拒绝开打**。

    ★#42 真机实证（这条判据为什么必须「归属」而不是「比对标题」）★
      「列表行名」与「详情页横幅」**不是一回事**：同一台真机（机型A/RANK158）上
      列表行 ``伊劳德雷斯讨伐`` 的详情页横幅是 ``水蚀荒龙``；列表行 ``圣夜的淘气鬼`` 的
      详情页难度行是 ``圣夜的雪像G中级``（横幅 OCR 成 ``室淘气鬼``）。因此**不能**要求
      「横幅 == 目标名」，否则会把**正确的**页面误拒（本票第一次真机跑就是这样超时的）。
      正确做法：把横幅**归属**到「最像它的那个已知成员」，只有归属到**别人**才拒绝 ——
      于是 ``碧之女王``（= 另一行的名字）被判错页，而 ``水蚀荒龙``（谁也不像）判「无法判定」。

    ``universe`` = 已知成员行名宇宙：缺省 = ``batch_plan.JOSS_NAMES``（真源派生的降临讨伐
    成员表）；调用方（识别器 / 指挥官）传 ``known_row_names()`` = 它 ∪ **在列表页真的见到过
    的行名**（见 :func:`note_list_rows`）—— 于是领主战成员也判得动，且不必手写会漂移的表。
    """
    items3 = _as3(items)
    on_detail = any(re.search(_DETAIL_PAGE_MARKER, t) for t, _b, _s in items3)
    if not on_detail:
        return "not_detail", {"reason": "不是详情页（没有「推荐编成」）"}
    core = _core_name(member)
    if not core:
        return "unknown", {"reason": "目标成员为空"}
    title = _pick_detail_title(items3)
    if title is None:
        return "unknown", {"reason": "详情页横幅读不到标题"}
    target = _norm_name(member)
    scores = {target: _char_similarity(core, title["text"])}
    for other in (universe if universe is not None else JOSS_NAMES):
        if other and other != target:
            scores[other] = _char_similarity(_core_name(other), title["text"])
    best_member = max(scores, key=lambda m: scores[m])
    info = {
        "title": title["text"],
        "title_box": title["box"],
        "title_score": round(title["score"], 3),
        "core": core,
        "target": target,
        "target_sim": round(scores[target], 3),
        "best_member": best_member,
        "best_sim": round(scores[best_member], 3),
    }
    if best_member != target and scores[best_member] >= IDENTITY_DOMINANT_MIN:
        info["reason"] = f"横幅更像 {best_member!r} 的详情页"
        return "mismatch", info
    if scores[target] >= IDENTITY_MATCH_MIN:
        info["reason"] = "横幅归属目标成员"
        return "match", info
    if best_member != target and scores[best_member] >= IDENTITY_OWNER_MIN:
        info["reason"] = f"横幅归属到别的行 {best_member!r}（不是目标）"
        return "mismatch", info
    info["reason"] = "横幅归属不了任何已知成员，无法判定"
    return "unknown", info


# 「已知成员行名宇宙」的扩容源（#42）：把**在列表页真的见过**的行名收进来。
# 为什么从帧上学（而不是再写一份成员表）：列表行名与详情页横幅**不是一回事**
# （真机：行 `伊劳德雷斯讨伐` 的详情页横幅是 `水蚀荒龙`），身份校验要做的是
# 「横幅归属到哪一行」，而「行名长什么样」这件事**只有列表页那一帧最权威**。
_ROWS_LOCK = threading.Lock()
_ROWS_SEEN: set[str] = set()


def reset_rows_seen() -> None:
    """清空「见过的行名」（新任务 / 离线测试用）。"""
    with _ROWS_LOCK:
        _ROWS_SEEN.clear()


def note_list_rows(items) -> None:
    """把这一帧里【列表体内、行名列】的文本收进「见过的行名」（供身份校验归属用）。

    只在**列表页**（有列表页独有元素「更新列表」）上生效 —— 详情页的难度行也在同一片
    矩形里，混进来只会污染「行名宇宙」。
    """
    items3 = _as3(items)
    if not any(re.search("更新列表", t) for t, _b, _s in items3):
        return
    for text, box, _score in items3:
        if not box or len(box) != 4:
            continue
        cx, cy = _center(box)
        if not (150 <= cx <= 470 and ROW_BODY_TOP <= cy <= ROW_BODY_BOTTOM):
            continue
        t = _norm_name(text)
        if len(t) < 3 or any(c in t for c in _IDENTITY_CHROME):
            continue
        with _ROWS_LOCK:
            if len(_ROWS_SEEN) < 200:
                _ROWS_SEEN.add(str(text).strip())


def known_row_names() -> frozenset:
    """身份校验的「已知成员行名」宇宙 = 真源 JOSS_NAMES ∪ 列表页见过的行名。"""
    with _ROWS_LOCK:
        return frozenset(JOSS_NAMES) | frozenset(_ROWS_SEEN)


def _member_from_row_node(context, row_regex):
    """从【选行节点】``SpecialEnterBoss`` 当前 expected 里取目标成员（#42）。

    ★为什么不新加一个参数★：目标成员在 pipeline 上**唯一**的表达就是选行节点的行名
    （GUI 选项「打哪个副本」/ 批量指挥官 / 真机 runner 都覆盖它）→ 直接读它，
    绝不另写一份会漂移的副本（ADR-0001）。

    只在「声明的难度是**纯难度正则**」（= 领主战 / 降临讨伐详情页路径）时启用；
    迷宫（farm 的 ``target`` 是迷宫名）不受影响。读不到（旧框架 / stub）返回 None。
    """
    if declared_difficulty(row_regex) is None:
        return None
    try:
        data = context.get_node_data("SpecialEnterBoss") or {}
    except Exception as exc:  # noqa: BLE001 —— 读不到就不校验成员，绝不臆断
        print(f"[#42] 读取选行节点 SpecialEnterBoss 失败（不校验成员）：{exc}")
        return None
    if not isinstance(data, dict):
        return None
    expected = ((data.get("recognition") or {}).get("param") or {}).get("expected") or []
    if isinstance(expected, str):
        expected = [expected]
    for e in expected:
        if isinstance(e, str) and e.strip() and e.strip() != "__NONE__":
            return e.strip()
    return None


def verify_row_on_frame(items, pattern, ref_box=None):
    """在【列表体】内复核目标行（#42 选行点击用）。★纯函数★。

    返回 ``(box, dy)``：``box`` = 复核帧里目标行的框；``dy`` = 新框中心相对识别框中心的
    纵向位移（正 = 列表往下滚过 / 行往上走）。列表体内找不到 → ``None``。

    ``ref_box`` 给定时，取与识别框**同一行**（纵向最近）的那一个匹配框 —— 这正是
    「列表仍在滑动」时把落点从【陈旧坐标】纠正到【目标行现在的位置】的关键。
    """
    cands = []
    for text, box, _score in _as3(items):
        if not box or len(box) != 4:
            continue
        if not re.search(pattern, text or ""):
            continue
        cx, cy = _center(box)
        if not (ROW_BODY_TOP <= cy <= ROW_BODY_BOTTOM):
            continue  # 不在列表体内（底导标签 / 顶栏）→ 不是行
        cands.append(list(box))
    if not cands:
        return None
    if ref_box and len(ref_box) == 4:
        _rcx, rcy = _center(ref_box)
        cands.sort(key=lambda b: abs(_center(b)[1] - rcy))
    else:
        cands.sort(key=lambda b: _center(b)[1])
    chosen = cands[0]
    dy = (_center(chosen)[1] - _center(ref_box)[1]) if (ref_box and len(ref_box) == 4) else 0.0
    return chosen, dy


def _grab_frame(context):
    """立刻重抓一帧（与 pipeline 同一坐标空间 720x1280）；失败返回 None。"""
    try:
        return context.tasker.controller.post_screencap().wait().get()
    except Exception as exc:  # noqa: BLE001 —— 抓不到就当「复核不了」，走保守分支
        print(f"[#42] 重抓帧失败：{exc}")
        return None


def _click_box(context, box) -> bool:
    """用 pipeline 原生 Click 动作点击 720 空间的框中心（版本无关，见 _batch_click 注释）。"""
    if not box or len(box) != 4:
        print(f"[#42] 点击失败：非法框 {box!r}")
        return False
    cx, cy = _center(box)
    try:
        context.run_action("PubClick", box=(int(cx) - 1, int(cy) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[#42] 点击失败 {box}：{exc}")
        return False


# 「打开的详情页不是当前目标」→ 指挥官的处置（#42）。真机 r9/C3 就发生在这里：
# 目标 A 的页面 B 被当成 A 打了、还记成 A。策略：先【退回并重新导航】（点底部主城回主城，
# 由 pipeline 自己重新导航到下一个目标）；同一个成员连续超限 → 记为**失败/跳过**并写明原因。
WRONG_DETAIL_LIMIT = 3
_WRONG_DETAIL_LOCK = threading.Lock()
_WRONG_DETAIL_TASK = None
_WRONG_DETAIL_COUNT: dict[str, int] = {}


def _note_wrong_detail(member, task_id) -> int:
    """记一次「错页」，返回该成员在本任务里的累计次数（换任务清零）。"""
    global _WRONG_DETAIL_TASK
    with _WRONG_DETAIL_LOCK:
        if _WRONG_DETAIL_TASK != task_id:
            _WRONG_DETAIL_TASK = task_id
            _WRONG_DETAIL_COUNT.clear()
        _WRONG_DETAIL_COUNT[member] = _WRONG_DETAIL_COUNT.get(member, 0) + 1
        return _WRONG_DETAIL_COUNT[member]


def reset_wrong_detail_state() -> None:
    """清空「错页」计数（新任务 / 离线测试用）。"""
    global _WRONG_DETAIL_TASK
    with _WRONG_DETAIL_LOCK:
        _WRONG_DETAIL_TASK = None
        _WRONG_DETAIL_COUNT.clear()


def plan_wrong_detail_action(member, hit_count, *, limit: int = WRONG_DETAIL_LIMIT):
    """★纯函数★：错页第 N 次 → 指挥官该做什么。返回 ``(action, reason)``。

    * ``hit_count <= limit`` → ``("back_out", …)``：退回主城并重新导航该目标
      （一次错位不该毁掉整批，也不该在这里开打）；
    * 超过 limit → ``("skip", …)``：同一成员反复错位 → 记为**失败/跳过**并写明原因
      （绝不静默记成目标成员、也绝不死循环）。
    """
    if hit_count <= limit:
        return "back_out", (
            f"详情页身份校验失败（第 {hit_count} 次）：打开的详情页不是目标 {member!r}"
            f"→ 退回并重新导航（绝不在别人的页面开打）"
        )
    return "skip", (
        f"详情页身份校验连续 {hit_count} 次失败（>{limit}）：目标 {member!r} 反复打开到别人的"
        f"详情页 → 记为**失败/跳过**（绝不静默记成该成员）"
    )


def _current_target_member(context):
    """当前「正在刷的目标成员」（#42）：批量 → 当前清单项；单目标 → 选行节点行名。"""
    with _BATCH_LOCK:
        cur = _BATCH_CURRENT
    if cur is not None and getattr(cur, "kind", "special") == "special":
        return cur.dungeon
    return _member_from_row_node(context, "高级$")


def _identity_gate_active(context, argv) -> bool:
    """本任务此刻是否该做「详情页身份校验」（#42）。

    只在 **special 路径**（领主战 / 降临讨伐）启用：farm / raid / phantom 的导航页与
    详情页几何不同，套这一个闸只会误伤。单目标模式下还要求选行节点确实有目标行名。
    """
    with _BATCH_LOCK:
        cur = _BATCH_CURRENT
    if cur is not None:
        return getattr(cur, "kind", "special") == "special"
    if _entry_kind(argv) != "special":
        return False
    return bool(_member_from_row_node(context, "高级$"))


def _wrong_detail_state(context, argv, items):
    """这一帧若是「别人的详情页」→ 返回 ``(目标成员, identity info)``；否则 None。"""
    if not _identity_gate_active(context, argv):
        return None
    member = _current_target_member(context)
    if not member:
        return None
    verdict, ident = detail_page_identity(items, member, universe=known_row_names())
    if verdict != "mismatch":
        return None
    return member, ident


def log_row_selection(items, member):
    """★#42 仪器化★：把「目标行在这一帧的框/中心」打出来（逐节点框/坐标日志）。

    这条日志是「选行错位」的**根因证据**：它给出选行节点认到目标行的坐标；
    与随后详情页身份校验的标题一并看，就能直接证明「识别框 vs 实际打开页面」的错位，
    而不是靠猜（竞态 / 陈旧坐标 / 过宽 ROI 三者只能靠这条日志分辨）。
    目标行不在帧内时也打一行（说明「此刻不可点」）。
    """
    if not member:
        return
    try:
        pattern = re.escape(member)
    except Exception:  # noqa: BLE001
        pattern = member
    for text, box, score in _as3(items):
        if not re.search(pattern, text or ""):
            continue
        cx, cy = _center(box)
        in_body = ROW_BODY_TOP <= cy <= ROW_BODY_BOTTOM
        print(
            f"[rowsel] 目标行 {member!r} @ {box}（中心 ({cx:.0f},{cy:.0f})）score={score:.3f} "
            f"列表体内={in_body}"
        )
        return
    print(f"[rowsel] 目标行 {member!r} 本帧不在屏内（需继续滚动 / 尚未导航到列表页）")


# ===========================================================================
# ★#62 「能导航进详情页、却配不出战斗」的成员不得【无界】重试（有界跳过）★
#
# 现场（设备 16448，批量 chunk_j4：
#   list = 方舟守护者讨伐,中级,1;赤之女王讨伐,中级,1;青之女王讨伐,中级,1;
#          碧之女王讨伐,中级,1;皓之女王讨伐,中级,1）
# ----------------------------------------------------------------
#   · 单跑 `方舟守护者讨伐`：导航成功、详情页身份校验 match（`标题='方舟守护者'`），
#     但 `special_target_fight` 从此【再也没有输出 `row=…`】—— 该行【战斗】按钮在真机
#     那一帧被 OCR 读成单字 `5`（框 [93,506,7,7]，见 watch_ark_4.ocr.txt），既不是
#     `^战斗$`，也不是 #43 的「等长单字替换」/ #49 的「真前缀截断」可救的字形，
#     于是配不出战斗框 → 详情页无法推进。
#   · 批量里它排第一，于是整条清单在它身上空转到 1200s 超时（status=timeout，账本为空），
#     **后面 4 个成员一个都没被尝试**；单独重跑那 4 个（chunk_j4b.log）4/4 正常。
#   ⇒ 一个「能导航进去、却打不了」的成员【吃掉整个任务预算】并把后面的成员全部饿死。
#
# 为什么现有的有界安全网没接住它
# ----------------------------
#   · #50 的滚动预算用尽判定（:func:`scroll_budget_exhausted`）要求「滚动一直没把目标行
#     滚进屏」—— 本条目【行已经进了详情页】，根本不走滚动节点，故预算永不耗尽；
#   · #45 的导航宽限只对【被声明的种类】（raid）生效，special 的 `nav_timeout` 是 None；
#   · #44 的归位超时（``_BATCH_HOME_TIMEOUT``）只在【切条目归位】阶段计时，本条目早已归位。
#   ⇒ special 条目「导航之后、开打之前」这一段本来没有任何上限。本票补上它。
#
# 做法（两条，缺一不可）
# --------------------
#   1. 【详情页自己的上限】当前条目停在【自己的详情页】（#42 身份校验 match：有
#      `推荐编成` 标记 + 横幅归属当前目标），却【尚未走过自身导航/开打】
#      （``_BATCH_ITEM_ENGAGED`` 为假）—— 持续超过 :data:`_UNFIGHTABLE_DETAIL_SEC` 秒
#      即由指挥官【记明原因并跳过该目标、继续清单】（没有别的目标可继续则收工）。
#      这一条覆盖本票的实测形态（页对、战斗按钮读不出）。
#   2. 【兜底导航上限】special 条目从「开始导航」起，超过
#      :data:`_SPECIAL_NAV_DEADLINE_SEC` 秒仍没走到「自身开打」→ 同样明确跳过。
#      这一条覆盖「详情页连 `推荐编成` 标记都读不到」的形态（那种连身份校验都无从谈起，
#      正对应验收条件「详情页没有推荐编成标记 / 读不出难度行时必须走明确的跳过/收工分支」）。
#   ★两条都【只跳过该目标 / 按策略收工】，绝不静默空转、绝不假记账、绝不打错档★：
#   与 #39（难度发现）、#41（详情页门控）、#42（身份校验）、#45（声明式不可达）、
#   #50（滚动预算用尽）同一套「明确跳过 + 记录原因」语义，绝不无界重试。
#
# 判据都是纯函数（:func:`plan_unfightable_detail_action` 离线可单测，不碰设备）；
# 真机帧证据 + 破坏实验见 tools/contract_hooks/hooks_62.py。
# ===========================================================================
#: 条目停在【自己的详情页】却配不出战斗按钮的持续上限（秒）——超过即跳过该目标。
#: 取 20s：远大于「详情页正常一两帧内开打」的耗时，也远小于任务超时（1200s）。
_UNFIGHTABLE_DETAIL_SEC = 20.0
#: 条目「开始导航后始终没走到自身开打」的兜底上限（秒）。取 420s：深行成员经 #50 的
#: 【每条目 80 次受控滚动】最坏约 4~5 分钟，故不会误伤正常条目；又足以给「详情页连
#: `推荐编成` 标记都读不到」的形态封顶（远小于 1200s 的任务超时）。
_SPECIAL_NAV_DEADLINE_SEC = 420.0
#: ★#maze-entry★ farm（摇曳的迷宫）的兜底导航上限（秒）：主城横幅入口要等轮播转到
#: 声明的那个域（整条轮播约 30~40s）才可能命中，FarmMazeEntry 又是【有界】重试
#: （max_hit=6）。若到点仍没走到「自身开打」，就明确跳过该目标并打印原因，绝不空转
#: 到 1200s 任务超时。取 180s：> 3 个轮播周期（不误伤只是“等轮播”的正常目标），
#: 又远小于任务超时；是有限值，不随重试无限增长。
_FARM_NAV_DEADLINE_SEC = 180.0

# 「自己详情页配不出战斗」的交接状态：识别器侧的判据由指挥官用同一帧 OCR 复算
# （:func:`_own_detail_unfightable`），这里只负责计时（首次进入该状态到现在多久）。
_UNFIGHTABLE_LOCK = threading.Lock()
_UNFIGHTABLE_MEMBER = None
_UNFIGHTABLE_TASK = None
_UNFIGHTABLE_SINCE = 0.0


def plan_unfightable_detail_action(
    member, elapsed, *, limit=_UNFIGHTABLE_DETAIL_SEC,
    batch_active: bool, remaining_other: int,
):
    """★纯函数★：条目在自己的详情页配不出战斗按钮、持续 ``elapsed`` 秒 → 指挥官该做什么。

    返回 ``(action, reason)``，``action`` ∈ ``{"retry", "skip", "stop"}``：

    * ``elapsed < limit`` → ``retry``：再给一帧机会（防单帧 OCR 抖动误跳）；
    * 超过 ``limit`` 且批量里还有别的目标 → ``skip``：**记明原因跳过该目标、继续清单**；
    * 超过 ``limit`` 且没有别的目标可继续 → ``stop``：**明确收工并记录原因**。

    与 #39 的 :func:`plan_absent_difficulty_action` 同一形态：绝不静默空转、绝不假记账。
    """
    if elapsed < limit:
        return "retry", (
            f"条目 {member!r} 在自己的详情页配不出【战斗】按钮"
            f"（已持续 {elapsed:.0f}s / 上限 {limit:.0f}s）→ 再给一帧机会"
        )
    if batch_active and remaining_other > 0:
        return "skip", (
            f"条目 {member!r} 在自己的详情页 {elapsed:.0f}s 内始终配不出【战斗】按钮"
            f"（能导航进去、却开不了打）→ 记明原因跳过该目标、继续清单"
            f"（还剩 {remaining_other} 个目标；#62：绝不无界重试）"
        )
    return "stop", (
        f"条目 {member!r} 在自己的详情页 {elapsed:.0f}s 内始终配不出【战斗】按钮 → "
        f"主动收工并记录原因（没有别的目标可继续；#62：绝不无界重试）"
    )


def _note_unfightable_detail(member, task_id, now=None) -> float:
    """记一次「在【自己的】详情页配不出战斗」，返回该状态已持续的秒数。

    换成员 / 换任务 → 重新计时（同一成员连续多帧才算「卡住」）。``now`` 可注入（离线守卫）。
    """
    global _UNFIGHTABLE_MEMBER, _UNFIGHTABLE_TASK, _UNFIGHTABLE_SINCE
    t = time.monotonic() if now is None else float(now)
    with _UNFIGHTABLE_LOCK:
        if _UNFIGHTABLE_TASK != task_id or _UNFIGHTABLE_MEMBER != member:
            _UNFIGHTABLE_TASK = task_id
            _UNFIGHTABLE_MEMBER = member
            _UNFIGHTABLE_SINCE = t
        return max(0.0, t - _UNFIGHTABLE_SINCE)


def _clear_unfightable_detail() -> None:
    """离开「自己详情页配不出战斗」状态 → 复位计时（开打了 / 不在自己的详情页 / 切条目）。"""
    global _UNFIGHTABLE_MEMBER, _UNFIGHTABLE_SINCE
    with _UNFIGHTABLE_LOCK:
        _UNFIGHTABLE_MEMBER = None
        _UNFIGHTABLE_SINCE = 0.0


def reset_unfightable_detail(task_id=None) -> None:
    """新任务 / 离线测试复位（含任务 id）。"""
    global _UNFIGHTABLE_TASK
    with _UNFIGHTABLE_LOCK:
        _UNFIGHTABLE_TASK = task_id
        _UNFIGHTABLE_MEMBER = None
        _UNFIGHTABLE_SINCE = 0.0


def _own_detail_unfightable(context, argv, items):
    """这一帧是不是「当前目标【自己的】详情页、但还没开打」→ ``(member, ident)``；否则 ``None``。

    判据 = #42 的详情页身份校验判定为 ``match``（详情页独有标记 `推荐编成` + 横幅归属
    当前目标），且当前条目【尚未走过自身导航/开打】（``_BATCH_ITEM_ENGAGED`` 为假）。

    ★与 #42 的「错页」分工★：``mismatch``（打开的是别人的详情页）走 #42 的退回/跳过；
    本函数只认 ``match`` —— 即「页对、却配不出战斗」，交给 #62 的有界跳过处理。
    """
    if not _identity_gate_active(context, argv):
        return None
    with _BATCH_LOCK:
        if _BATCH_ITEM_ENGAGED:
            return None
    member = _current_target_member(context)
    if not member:
        return None
    verdict, ident = detail_page_identity(items, member, universe=known_row_names())
    if verdict != "match":
        return None
    return member, ident


# ===========================================================================
# ★#38 战斗失败 / GAMEOVER（「是否续关？」）—— 放弃该次战斗 → 记录原因 → 继续清单 ★
#
# 现场（真机扫描，#38）：魁雷精灵兽 战斗打输 → 进入 GAMEOVER /「是否续关？」→ pipeline
# 没有对应节点 → 任务卡死，且后续 3 个成员（威风 / 巫光 / 暗唤精灵兽）一个都没跑成。
# 一次战斗失败不该让整批任务死掉。
#
# 处置（已定）：**放弃该次战斗 → 记录原因 → 继续清单**（一个批量清单里往往还有别的
# 目标，输一场不该毁掉整批）；但**同一个失败连续发生 2 次**（其间没有任何胜利）时，
# **主动收工并说明原因** —— 连续失败说明是系统性问题，继续只会白烧资源。
#
# 分工：
#   · 画面识别与「拒绝续关」的点击 = pipeline 节点（common.json 的 PubGameOver*，
#     由 SpecialEntry.next 以 [JumpBack] 引用）—— 读屏再点，绝不盲点、绝不点『续关』；
#   · 「记一次失败 / 放弃该目标 / 连续 2 次收工」的决定 = 本指挥官（SpecialBatchPlan）。
#
# 为什么识别与决定分开：点击是**页面动作**（要在失败帧上发生），决定是**批量状态机**
# （要读写清单）。与 #39「详情页识别器写交接状态、指挥官读」同一分工。
# ===========================================================================

#: 连续失败到这个次数就**主动收工**（其间有任何胜利则计数清零）。
GAMEOVER_CONSECUTIVE_LIMIT = 2

# ★#71 / R8★：GAMEOVER_TITLE / GAMEOVER_PROMPT / GAMEOVER_GIVEUP /
#   GAMEOVER_CONFIRM_MARKERS / classify_gameover 已上提 agent/battle_loop_core.py ——
#   这里只是**同名转发**（本文件顶部已 re-export），绝不另写一份。
#   （GAMEOVER_CONSECUTIVE_LIMIT / plan_gameover_action 仍在本文件，未上提。）


def gameover_state(context, image) -> str | None:
    """对当前帧判「是否战斗失败画面」（OCR 走公共 OcrTask，与指挥官判忙闲同一套）。

    OCR 不可用（旧框架 / 离线 stub）时返回 ``None`` —— 视为非失败画面，绝不臆断；
    此时「拒绝续关」仍由 pipeline 节点承担（它自带 OCR 判据），只是指挥官不做记账/收工决定。
    """
    try:
        items = ocr_all(context, image, "OcrTask")
    except Exception as exc:  # noqa: BLE001 —— 判页失败不是致命错误，但必须可见
        print(f"[batch] GAMEOVER 判页 OCR 失败（视为非失败画面）：{exc}")
        return None
    return classify_gameover(items)


def plan_gameover_action(
    consecutive,
    *,
    limit: int = GAMEOVER_CONSECUTIVE_LIMIT,
    batch_active: bool,
    has_current: bool,
    remaining_other: int,
):
    """★纯函数★：一次战斗失败（已拒绝续关）→ 指挥官该做什么。

    返回 ``(action, reason)``，``action`` ∈ ``{"abandon_continue", "stop"}``：

    * 连续失败 ``>= limit``（默认 2）→ ``stop``：同一失败连续发生 = 系统性问题，
      **主动收工并记录原因**（继续只会白烧资源）；
    * 批量激活且有当前目标、且放弃它之后**还有别的目标** → ``abandon_continue``：
      **放弃该目标、继续清单**（原因写清第几次连续失败、还剩几个目标）；
    * 其余（单目标 / 没有别的目标可继续）→ ``stop``：明确收工并记录原因。

    ★选择说明★：一个批量清单里往往还有别的目标，输一场不该毁掉整批，故默认「放弃该
    目标并继续」；只有**连续 2 次失败**（系统性问题）或**已无目标可继续**时才主动收工。
    两者都绝不卡死、也绝不盲目重打已输的仗。
    """
    if consecutive >= limit:
        return "stop", (
            f"连续 {consecutive} 次战斗失败（≥{limit}）→ 判定系统性异常，"
            f"主动收工并记录原因（不再继续清单）"
        )
    if batch_active and has_current and remaining_other > 0:
        return "abandon_continue", (
            f"战斗失败（第 {consecutive} 次连续失败）：放弃该目标、继续清单"
            f"（还剩 {remaining_other} 个目标）"
        )
    return "stop", (
        f"战斗失败且没有其他目标可继续（连续 {consecutive} 次）→ 主动收工并记录原因"
    )


# ===========================================================================
# ★#46 战斗 HUD vs GAMEOVER 页 —— SpecialBattleWait 的「不该命中」判别（纯函数）★
#
# 现场（真机 127.0.0.1:16384，维·索拉斯讨伐/超级 打输）：GAMEOVER /「是否续关？」页
# **底部仍然画着战斗 HUD 的「时间/分数」**，于是 SpecialBattleWait 的 And(时间,分数)
# 在这一页也命中 → 它赢下这一帧、DoNothing、走自己的 next（无 GAMEOVER 打断）→
# `[JumpBack]PubGameOver*` 永不执行 → SpecialBattleWait ↔ SpecialEntry 空转到 1200s 超时。
#
# MAA 识别无 ``Not``（``And`` 也无法对子引用取反 —— 已用最小 pipeline 实测），故 pipeline
# 侧用【分派优先级】表达排他：``SpecialEntry.next`` 里在 SpecialBattleWait 之前放了
# ``SpecialGameOverHold``（只认『GAMEOVER』+「是否续关？」）。下面两个纯函数是这条规则的
# 【语义真源】，供离线真机帧复现/守卫（tools/contract_hooks/hooks_46.py）逐帧求值。
# ===========================================================================

# ★#71 / R8★：BATTLE_HUD_TIME_RE / BATTLE_HUD_SCORE_RE / is_battle_hud /
#   battle_wait_should_hold 已上提 agent/battle_loop_core.py —— 这里只是**同名转发**
#   （本文件顶部已 re-export），绝不另写一份。本文件收工路径仍用 ``is_battle_hud(...)``。
#: ★#46★ 真机失败帧的语义见 battle_loop_core 对应段落（HUD 会出现在 GAMEOVER 页底部）。


def reset_gameover_state() -> None:
    """清空战斗失败的连续计数与待处理标记（新任务 / 离线测试用）。"""
    global _BATCH_LOSSES, _GO_PENDING
    with _BATCH_LOCK:
        _BATCH_LOSSES = 0
        _GO_PENDING = False


# 详情页难度发现的**交接状态**：详情页上的识别器写、批量指挥官（SpecialBatchPlan）读。
# 两个识别器都在同一进程（同一 AgentServer / 同一 runner），故用模块级状态交接。
_DIFF_LOCK = threading.Lock()
_DIFF_NOTE: "_DiffOutcome | None" = None


def _note_detail_difficulty(note: _DiffOutcome) -> None:
    global _DIFF_NOTE
    with _DIFF_LOCK:
        _DIFF_NOTE = note


def _take_detail_difficulty():
    global _DIFF_NOTE
    with _DIFF_LOCK:
        note = _DIFF_NOTE
        _DIFF_NOTE = None
        return note


def reset_detail_difficulty() -> None:
    """清空详情页难度发现的交接状态（新任务 / 测试用）。"""
    global _DIFF_NOTE
    with _DIFF_LOCK:
        _DIFF_NOTE = None


# ===========================================================================
# ★#54 迷宫「域 + 行名」识别辅助（修订 #52 的「域 + 元素」）★
#
# 迷宫页每个域是一张**异质行列表**：行名自含【元素】/Lv../层（如「摇曳的迷宫宝物域【火】」/
# 「深层域3【暗】Lv70」/「幽玄域【1〜3层】」）。识别主目标 = **行名**（target），
# 域随行名一起声明（domain；落点数据节点 ``FarmDomainPick`` 供 GUI 域选项用）。
#
# ★OCR 常丢行名里的脆弱片段（【元素】/Lv../层）★：行名匹配对「片段被丢」容错，
#   但**绝不容错到别的行**——做法见 :func:`maze_row_patterns`：
#     · 严格式 = 整行原文 + `$`（末尾锚定，故「临境域深渊之兽」绝不会命中「…·极/·真」）；
#     · 容错式 = 行名骨架 + 每个**本行自己的**片段各自可省 + `$`——只命中「本行丢片段后的样子」，
#       绝不命中「另一行（片段不同）」（如 宝物域【火】 的容错式绝不命中 宝物域【水】）。
#   取用规则（:func:`_apply_row`）：屏上出现严格式就用严格式；否则退回容错式。
# ===========================================================================
MAZE_DOMAIN_NODE = "FarmDomainPick"
# 行名里的「脆弱片段」：【…】 与 LvNN（丢这些不影响归属；绝不放宽其它字形）。
_MAZE_FRAG_RE = re.compile(r"【[^】]*】|Lv\d+")

# ★#57★ 迷宫【域】的判定与进入改用【图片匹配】（运维 2026-10-14：迷宫域不要用 OCR）★
# ---------------------------------------------------------------------------
# 缺陷（#57）：入口只以轮播【标题】为判据 → 点下去可能进任意一个域；而横幅副标题（域名）的
# OCR 在真机被读坏（崩坏域→崩环域 / 幽玄域→出立域，标题也常读成 摇电的迷宫/摇拽的迷宮）。
# ⇒ 「进的是哪个域」绝不能靠 OCR。
#
# 做法：每个域两张【真机 720 裁片】（相对 assets/resource/image/，MAA TemplateMatch 口径）：
#   · banner：主城左侧轮播横幅上的域名美术字 —— 进域门控（横幅正显示该域才点）；
#   · head  ：迷宫页页眉的域名美术字       —— 进域后【复核】（复核不过绝不推进）。
# 本表是 scene.config.MAZE_DOMAIN_TEMPLATES 的运行时快照（安装态 agent/ 无 scene/）；
# 守卫 hooks_57 把两者与 scene.options 的 ROI / 阈值逐项钉死（ADR-0001：配置为真源）。
MAZE_DOMAIN_TEMPLATES: dict[str, dict[str, str]] = {
    "崩坏域": {"banner": "maze/domain_beng_banner.png", "head": "maze/domain_beng_head.png"},
    "宝物域": {"banner": "maze/domain_baowu_banner.png", "head": "maze/domain_baowu_head.png"},
    "幽玄域": {"banner": "maze/domain_youxuan_banner.png", "head": "maze/domain_youxuan_head.png"},
}
MAZE_DOMAIN_TEMPLATE_NODE = "FarmMazeDomain"
MAZE_DOMAIN_VERIFY_NODE = "FarmDomainVerify"
#: 主城左侧轮播横幅位（720）。
MAZE_ENTRY_ROI = [0, 760, 340, 315]
#: 迷宫页页眉位（720）。
MAZE_HEAD_ROI = [0, 90, 720, 240]
#: 模板匹配阈值（cv TM_CCOEFF_NORMED）：真机同模板 ≥0.998、异域/负样本 ≤0.41。
MAZE_TEMPLATE_THRESHOLD = 0.8


def maze_domain_template(domain: str, role: str = "banner") -> str:
    """域 + 角色（``banner`` / ``head``）-> 模板相对路径（#57）。未知域/角色报 KeyError。"""
    return MAZE_DOMAIN_TEMPLATES[domain][role]


def _maze_domain_template_overrides(domain) -> dict:
    """域 -> 两个模板落点节点的 override（``FarmMazeDomain`` 门控 + ``FarmDomainVerify`` 复核）。

    与 ``scene.options._maze_template_override`` 同形；**未知域返回 {}**（绝不把某个域的模板
    当作兜底 —— 那正是 #57 的缺陷：静默进了别的域）。
    """
    if domain not in MAZE_DOMAIN_TEMPLATES:
        return {}

    def _node(role: str, roi: list) -> dict:
        return {
            "recognition": {
                "type": "TemplateMatch",
                "param": {
                    "template": [maze_domain_template(domain, role)],
                    "roi": list(roi),
                    "threshold": MAZE_TEMPLATE_THRESHOLD,
                },
            }
        }

    return {
        MAZE_DOMAIN_TEMPLATE_NODE: _node("banner", MAZE_ENTRY_ROI),
        MAZE_DOMAIN_VERIFY_NODE: _node("head", MAZE_HEAD_ROI),
    }

#: 全部迷宫行名（含各域）——判断「这是不是一个迷宫行目标」用。
MAZE_ALL_ROWS_SET = frozenset(r for rows in MAZE_ROWS.values() for r in rows)


def is_maze_row(target) -> bool:
    """``target`` 是否是一个【迷宫行名】（#54）。★纯函数★。"""
    return isinstance(target, str) and target in MAZE_ALL_ROWS_SET


def maze_row_parts(row: str) -> tuple[str, list[str]]:
    """把行名拆成 (骨架, [脆弱片段…])：骨架 = 去掉 【…】 / LvNN；片段 = 被去掉的那些（有序）。"""
    frags = _MAZE_FRAG_RE.findall(row or "")
    stem = _MAZE_FRAG_RE.sub("", row or "")
    return stem, frags


def maze_row_patterns(row: str):
    """行名的 (严格式, 容错式|None)：末位锚定，故绝不命中别的行。★纯函数★。

    * 严格式：整行原文 + ``$``；
    * 容错式（行名含脆弱片段时）：骨架 + 每个**本行片段**各自可省（``(?:片段)?``）+ ``$``；
      行名没有脆弱片段（如 ``临境域深渊之兽·极``）时返回 ``None``（不做任何放宽）。
    """
    strict = re.escape(row or "") + "$"
    stem, frags = maze_row_parts(row)
    if not frags:
        return strict, None
    loose = re.escape(stem) + "".join(f"(?:{re.escape(f)})?" for f in frags) + "$"
    return strict, loose


def maze_owner_regex() -> str:
    """「谁算一个迷宫行名」的候选正则（供 :func:`_row_owner_name` 回指同一行）。

    含全部行的严格式与容错式 —— 与 :func:`pick_target_battle_box` 用**同一套** pattern 生成，
    因此回指证明的是「选中的战斗框落在**声明的那个行**上」，绝不落到相邻行（#35 同构）。
    """
    pats: list[str] = []
    for rows in MAZE_ROWS.values():
        for r in rows:
            strict, loose = maze_row_patterns(r)
            pats.append(strict)
            if loose:
                pats.append(loose)
    return "|".join(pats)


def _apply_row(row: str, items) -> str:
    """取该行的匹配正则：屏上有【严格式】就用严格式，否则退回【容错式】（#54）。★纯函数★。"""
    strict, loose = maze_row_patterns(row)
    if loose is None:
        return strict
    if any(re.search(strict, t or "") for t, _b in items):
        return strict
    return loose


class SpecialTargetFightRecognition(CustomRecognition):
    """详情页【战斗】按钮识别（P0 修复）：直接返回战斗按钮 OCR 框，绝不点推荐编成。

    ★#39★ 本识别器**同时承担运行时难度发现**：先读详情页实际可用的难度集，
    若声明的难度**不存在**（``absent``）或**读不到任何难度**（``undetermined``），
    则不命中（box=None）并把结果交接给批量指挥官 —— 由它「跳过该目标继续 / 主动收工」，
    绝不静默打错档、也绝不死循环卡住。

    可用参数（custom_recognition_param）：
        difficulty : 目标行名正则，如 "高级$"（领主角逐难度）或迷宫行名（#54）。
                     值为空 / "__NONE__" 时本节点不命中（用于「打满」模式关掉它）。
        target     : 与 difficulty 等价的更通用别名（★#54★ 迷宫**行名**用；二者取其一即可）。
                     若它正是一个【迷宫行名】（scene.config.MAZE_ROWS 之一），则本识别器按
                     行名匹配（严格式优先、容错式兜底：容忍 OCR 丢 【元素】/Lv../层 片段，
                     见 maze_row_patterns），并按**同一套 pattern**回指同一行（#35 同构），
                     ★绝不落到相邻行 / 别的行★。元素是行名的一部分，**不是**独立选项（#54）。
        pair       : 战斗按钮相对行名的位置："below"（默认；真机几何 #35 —— 领主战/
                     降临讨伐详情页与迷宫列表页都是「名在上、战斗在下方 ≈40px」）/
                     "above"（仅历史/对照版式，详情页已证伪，不再使用）。
        battle_regex : 战斗按钮文本正则，默认 "^战斗$"。
        max_gap    : 战斗按钮与行名的最大纵向间距（720 像素）。缺省（None）= 同一行实测带
                     BATTLE_ROW_MAX_GAP（120），锁死「同一行」，绝不配到相邻难度行的战斗。
        ocr_entry  : 截图用 OCR 节点，默认 "OcrTask"。
        member     : 目标成员名（行名，如 "伊劳德雷斯讨伐"）。给了它 → 本识别器**先校验
                     打开的详情页是不是该成员**（#42）：不是就 box=None（绝不在别人的
                     详情页开打，也就绝不会被账本记成目标成员）。缺省时自动从选行节点
                     ``SpecialEnterBoss`` 的 expected 取（只在「声明的是纯难度正则」
                     = 领主战 / 降临讨伐路径时启用；迷宫 farm 不受影响）。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        row_regex = param.get("target") or param.get("difficulty")
        if isinstance(row_regex, str) and row_regex.strip() in ("", "__NONE__"):
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "disabled", "difficulty": row_regex}
            )
        pair = param.get("pair") or DEFAULT_PAIR
        battle_regex = param.get("battle_regex") or DEFAULT_BATTLE_REGEX
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        # ★#54★ 迷宫行名目标（target = scene.config.MAZE_ROWS 之一）：按**行名**匹配。
        #   领主战 / 降临讨伐路径（行名是难度正则）完全不受影响。
        maze = is_maze_row(row_regex)
        _mg = param.get("max_gap")
        try:
            max_gap = int(_mg) if _mg not in (None, "") else None
        except (TypeError, ValueError):
            max_gap = None

        # ★#42★ 用**带 score** 的全屏 OCR（同一帧、同一 OcrTask 节点）：标题置信度是
        #   「读不准就不判错页」的判据；难度配对仍吃 2 元组形态（不改变 #35 行为）。
        items_scored = _ocr_scored(context, argv.image, ocr_entry)
        items = [(t, b) for t, b, _s in items_scored]
        if not items:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "OCR 无结果（不在可识别页面）"}
            )

        # ★#42 详情页身份校验（先于难度发现）★：打开的详情页不是目标成员 → 直接不命中。
        #   必须在 #39 的难度发现**之前**：错页上的「声明难度不存在」会把目标误判成
        #   「该成员没这一档」而跳过 —— 那会把「开错页」伪装成「账号没这一档」。
        member = param.get("member") or _member_from_row_node(context, row_regex)
        if member:
            verdict, ident = detail_page_identity(
                items_scored, member, universe=known_row_names()
            )
            if verdict != "not_detail":
                print(
                    f"[special_target_fight] 详情页身份校验：目标={member!r} 判定={verdict} "
                    f"标题={ident.get('title')!r}@{ident.get('title_box')} "
                    f"score={ident.get('title_score')} 归属={ident.get('best_member')!r}"
                    f"({ident.get('best_sim')}) 目标相似度={ident.get('target_sim')}"
                    f" → {ident.get('reason')}"
                )
            if verdict == "mismatch":
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={
                        "reason": "打开的详情页不是目标成员（#42，绝不开打）",
                        "member": member,
                        "identity": ident,
                    },
                )

        # ★#39 运行时难度发现★：先判定「声明难度在该成员详情页上是否存在」，
        #   不存在 / 读不到 → 交接给指挥官（跳过或收工），绝不静默打错档。
        found = classify_detail_difficulty(items, row_regex)
        if found.outcome in ("absent", "undetermined"):
            _note_detail_difficulty(found)
            reason = (
                "声明难度在详情页不存在" if found.outcome == "absent"
                else "详情页读不到任何难度档"
            )
            print(
                f"[special_target_fight] {reason}：声明={row_regex} "
                f"可用={sorted(found.available)}（#39，交由指挥官处理）"
            )
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "reason": reason,
                    "outcome": found.outcome,
                    "declared": row_regex,
                    "available": sorted(found.available),
                },
            )

        box, detail = pick_target_battle_box(
            items,
            difficulty=_apply_row(row_regex, items) if maze else row_regex,
            battle_regex=battle_regex, max_gap=max_gap, pair=pair,
            owner_regex=maze_owner_regex() if maze else None,
        )
        if box is None:
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)
        if detail.get("battle_match") == "approx":
            # ★#43★ 严格 `^战斗$` 未命中、但单字 OCR 误差候选仍落在声明难度行的按钮列、
            #   且已通过行主证明 —— 记一眼，便于真机排查「误差通道」何时被用到。
            print(
                f"[special_target_fight] 战斗按钮经『单字 OCR 误差』近似命中（#43）："
                f"实读 {detail.get('battle_text')!r}（未命中 {battle_regex}），"
                f"几何 + 行主已证明落在声明难度行"
            )
        elif detail.get("battle_match") == "approx_trunc":
            # ★#49★ 严格 `^战斗$` 未命中、检测只给出【单字框】（丢尾字，如真机 `战`），
            #   但该框的几何 + 行主回指已证明落在声明难度行 —— 记一眼（真机排查用）。
            print(
                f"[special_target_fight] 战斗按钮经『单字 OCR 截断』命中（#49）："
                f"实读 {detail.get('battle_text')!r}（未命中 {battle_regex}），"
                f"几何 + 行主已证明落在声明难度行"
            )
        # ★#44★：命中了【当前条目自己种类】的详情/迷宫页战斗按钮 = 本条目已走过自身导航，
        #   可以开始记账（record="always" 的前提）。见 side_impl #44 文件头铁律 1。
        _note_item_engaged()
        print(
            f"[special_target_fight] row={row_regex} pair={pair} "
            f"name={detail.get('name')}({detail.get('name_text')!r}) "
            f"战斗框={box} (gap={detail.get('gap')}) "
            f"match={detail.get('battle_match')} "
            f"行主={detail.get('row_owner')}"
        )
        return CustomRecognition.AnalyzeResult(box=box, detail=detail)


class MarkDoneAction(CustomAction):
    """往通用进度账本（agent/progress.py）里记一笔「这一关已完成」。

    与 next_stage 配套：next_stage 选中下一个未完成关卡时会把 (scope, 关卡名)
    记进 pending；本动作默认就把 pending 里的那一笔记掉。

    可用参数（custom_action_param）：
        key                  : 直接给完整 key，如 "side_story/百兽王冠/前往圣地"
        scope + stage        : 拼出 {scene}/{scope}/{stage}
        scope（不给 stage）  : 记下该 scope 当前 pending 的那一关
        （什么都不给）       : 记下最近一次 pending 的那一关
        scene                : 场景名，默认 side_story
        clear                : 记完后是否清 pending，默认 true
    """

    def run(self, context, argv):
        param = read_action_param(argv)
        scene = param.get("scene") or "side_story"
        key = param.get("key")
        scope = param.get("scope")
        stage = param.get("stage") or param.get("target") or param.get("name")
        clear = flag(param.get("clear", True))

        stage_text = stage
        #: ★#10★ 进度的 note（副本名）：取这次真的记账用的那个 scope（key 路径没有副本名）。
        scope_note = ""
        if key:
            full = str(key)
        elif scope and stage:
            full = ledger.make_key(scene, scope, stage)
            scope_note = str(scope)
        else:
            pend = ledger.pop_pending(scope if scope and scope != "__PENDING__" else None)
            if not pend:
                print(f"[mark_done] 没有可记的 pending（scope={scope}），跳过")
                return True
            p_scope, p_stage = pend
            stage_text = p_stage
            scope_note = str(p_scope)
            full = ledger.make_key(scene, p_scope, p_stage)
            if not clear:
                ledger.set_pending(p_scope, p_stage)

        newly = ledger.mark_done(full)
        # ★稳定键★ 再记一条 scene/关卡名（不含 scope）。scope 是 OCR 自动读的，
        # 跨运行会抖动（现场「哲黎明/哲黎叨/共世黎明」），只记 scoped key 会出现
        # 「同一关每次记到不同 key」→ 账本对不上。稳定键让完成判定与 scope 无关。
        if stage_text:
            stable = side_stage_key(scene, stage_text)
            if stable and stable != ledger.normalize_key(full):
                ledger.mark_done(stable)
        # 真正记下一关 = 有实质进展 → 复位「连续全清」计数（防空转收工判据不会误伤正常推进）。
        _reset_page_done()
        print(f"[mark_done] {'记账' if newly else '已存在'} {full}（稳定键 {side_stage_key(scene, stage_text) if stage_text else '-'}）")
        # ★#10 用户可见进度行★：账本**真的新增一笔**（``newly=True``）= 这一关完成 ⇒ 报一步
        # 「已 X 关」。★已存在不报★：同一次完成的多张结算帧 / 自愈补记都不该再算一步。
        if newly:
            note_stage_done(scope_note, argv)
        return True


# ===========================================================================
# 「批量副本清单」special_batch_plan / special_batch_fight（需求 #2）
#
# 目标：一次配置「要刷哪些副本、各刷多少次」，由 agent 解析清单后按顺序逐个执行。
#
# 与 pipeline 的分工
# ------------------
#   · pipeline 仍负责「导航 / 选难度 / 进战斗 / 结算」这些画面动作；
#   · 本识别器只做两件事：
#       1) 每次进入 SpecialEntry 分派时，判断「当前该打哪个目标」，
#          并用 context.override_pipeline(...) 把 SpecialEnterBoss（副本名）、
#          SpecialFightTargetRow（难度）等节点的识别参数改成目标值；
#       2) 一个目标打够次数后，点底部「主城」归位，让 pipeline 自己重新导航到
#          下一个副本（避免依赖返回键 / 避免连续 KeyEvent 4 的安全红线）。
#   · SpecialBatchFightAction 挂在「真正的开打」节点上（单人 SpecialChallenge /
#     多人 SpecialRoomFight）：点战斗，并标记「这一局已开打、还没结束」。
#   · SpecialBatchFinishAction 挂在结算推进节点上（SpecialResultContinue /
#     SpecialResultFallback / SpecialLevelUpContinue）：点继续/OK，并在
#     「开打中 → 看到结算」这一次转变时记一场账本。
#
# 计数判据为什么用「开打 → 结算」的状态机
# ----------------------------------------
#   结算页会连续出现多帧（QUESTRESULT / 继续 / 升级 / OK），按帧计数必然重复；
#   而只在「开打」那一刻计数，又会在战斗还没打完时就误判该目标已完成（实测踩过：
#   点完挑战立刻计数 → 归位/收工，战斗才刚开始）。
#   因此：开打置 in_fight=True；第一次看到结算页才 +1 并清 in_fight。
#   指挥官只有在「已计入本场、且不在战斗中、且不在结算/加载页」时才切目标/收工。
#
# 向后兼容
# --------
#   清单为空 / 未提供 → active=False：识别器永远 no-hit，两个动作都退化为
#   「原地点击」（与原 Click 完全一致），单目标旧逻辑不受影响。
#   ★#22 补充★：结算动作（special_batch_finish）在单目标模式下**额外**承担收工闸 ——
#   目标已打满配置次数时把当前结算节点指向 SpecialBatchStop（见 _single_target_finished）；
#   未配置有限次数（无 max_hit）的单目标流程行为完全不变。
# ===========================================================================

_BATCH_LOCK = threading.Lock()
_BATCH_TASK_ID = None            # 当前任务 id（换任务即重新解析）
_BATCH_RAW = None                # 上次解析用的原始清单文本
_BATCH_ITEMS: list[BatchItem] = []
_BATCH_ERRORS: list[str] = []
_BATCH_ACTIVE = False
_BATCH_CURRENT: BatchItem | None = None   # 当前正在执行的目标
_BATCH_NEEDS_HOME = False                 # 需要先点「主城」归位
_BATCH_FINISHED = False                   # 已收尾（防止重复 StopTask）
_BATCH_LAST_FIGHT_TS = 0.0                # 最近一次开打的单调时间
_BATCH_IN_FIGHT = False                   # 已开打、尚未看到结算
_BATCH_FIGHT_START_TS = 0.0               # 本局开打的单调时间（超时兜底用）
_BATCH_TARGET_START_TS = 0.0              # 当前目标「开始导航」的单调时间（farm 导航快速失败用）
_BATCH_MODE = None                        # 当前生效的「副本种类」：special / farm / raid / phantom
                                          # （被 BatchModeRecognition 读取，决定 FarmDispatch /
                                          #   RaidDispatch / PhantomDispatch 是否放行）
_BATCH_SKIPPED: list[str] = []            # #39：被「声明的难度不存在」跳过的目标（原因已记录）
_BATCH_LOSSES = 0                         # ★#38★ 连续（其间没有任何胜利打断）战斗失败次数
_GO_PENDING = False                       # ★#38★ 已记下一次战斗失败、尚未执行「放弃/收工」决定
_BATCH_ITEM_ENGAGED = False               # ★#44★ 当前条目是否已【走过自身种类的导航/开打】（记账前提）
_BATCH_BLOCK_DISPATCH = False             # ★#44★ 切种类未确认中立页时，封锁三个种类分派器
_BATCH_HOME_START_TS = 0.0                # ★#44★ 当前条目开始归位的单调时间（归位超时兜底）

# 任务入口 → 无清单时的默认种类。这样 FarmEntry / RaidEntry / PhantomEntry 这几个
# 「别名入口」即使清单为空，也能各自跑回原来的导航/循环（★保持向后兼容★）。
_ENTRY_KIND = {"FarmEntry": "farm", "RaidEntry": "raid", "PhantomEntry": "phantom"}


def _task_entry(argv) -> str | None:
    """取本次任务的入口节点名（MaaFramework TaskDetail.entry）。"""
    detail = getattr(argv, "task_detail", None)
    return getattr(detail, "entry", None)


def _entry_kind(argv) -> str:
    return _ENTRY_KIND.get(_task_entry(argv) or "", "special")


# 一个目标打完后，至少等这么久、且画面不忙，才允许切下一个 / 收工。
# ★保持 0：结算/战斗由 _batch_busy 判定；若在这里多等，pipeline 会在等待期间
#   自己又点一次「单人游戏→挑战」，导致多打一局（实测踩过）。★
_BATCH_MIN_SETTLE = 0.0

# 开打后多久仍没看到结算页，就强行认为本局结束（防止识别不到结算导致永久卡死）。
# ★#33 修订★：上面那句「强行结束」会把**仍在进行**的长战斗判成结束 —— 与运维裁决
#   「长战斗属正常等待，必须等 ✓ 不要跳过、不要收工」冲突（真机 127.0.0.1:16384 猩红巨熊
#   讨伐/中级 实证：设备被留在战斗中、N=2 的第二次被跳过、账本为空）。实测 209 场
#   min 5s / avg ~58s / **max 842s**；游戏自身把单局封顶在 ~14min。故等待上限改由
#   【游戏自身上限】派生（BATTLE_GAME_CAP_SEC，单一真源）+ 结算/加载裕度：长战斗是正常等待，
#   必须等；此值仅作「永挂」兜底 —— 到点仍未结算 = 真异常，记明原因并跳过该目标
#   （绝不无限挂起），且收尾归位负责离开战斗（见 live_harness.RETURN_HOME_RULES 的 live_battle）。
_BATCH_FIGHT_TIMEOUT = BATTLE_GAME_CAP_SEC + 120.0

# ===========================================================================
# ★#45 声明式「从主城不可达」能力缺口（DECLARATION）★
#
# 从主城出发的批量清单里，被本表声明的种类【不可能开打】。这是【设计】层面的能力缺口，
# 不是运行期故障 —— 因此：
#   · 用户【不该】再看到 45s / 120s 的「超时」（grace_sec = 0：一确认中立页即判定）；
#   · 跳过时写进 _BATCH_SKIPPED 的原因【直接来自本表】（reason 模板），而不是现场
#     拼一句超时文案。配置侧（raid.json / special_dungeon.json 的 #45 段）与本表是
#     【同一条声明】，守卫 tools/contract_hooks/hooks_45.py 把两边钉在一起。
#
#   · raid（战阵之宴）：raid.json 的设计就是【不做任何导航】（需用户先手动打开战阵之宴
#     页面）→ 主城没有入口 → 从主城不可达（by design，仍然成立）。
#
# ★#52 把 farm（摇曳的迷宫）从本表移除；#54 修订其模型★：迷宫**不是能力缺口** —— 真机
#   （16448）已证入口可达（主城左侧轮播横幅「摇曳的迷宫」被 FarmMazeEntry 命中并点击后
#   确实进迷宫页），且迷宫页**按「域 + 行名」选**（崩坏域 / 宝物域 / 幽玄域；行名自含
#   【元素】/Lv../层；**无难度档** —— 元素不是独立轴，#52 的写法已被 #54 修订）。
#   farm 走【真导航 + 真开打】，绝不再一确认中立页就跳过。
#   其模型 / 选项 / 守卫见 scene.config.MAZE_*、scene.options.derive_maze_*、
#   tools/contract_hooks/hooks_52.py 与 hooks_54.py。
#
# 真机证据：raid 侧见 #44 的 mixed.log（切到战阵之宴后从不出现战阵界面）；farm 侧见
# #45/#52/#54 评论与内嵌 OCR（主城横幅在、迷宫页行名如上）。帧 OCR 内嵌在
# tools/contract_hooks/hooks_45.py（raid）与 hooks_54.py（farm 域 + 行名版式）。
# ===========================================================================
UNREACHABLE_FROM_MAIN_CITY: dict[str, dict] = {
    "raid": {
        "grace_sec": 0.0,
        "reason": (
            "战阵之宴（{dungeon}）不做导航（raid.json 设计如此：需先手动打开战阵之宴页面）"
            "→ 从主城不可达（#45 声明的能力缺口，非运行期故障）→ 跳过该目标"
            "（绝不假记账、绝不空转）"
        ),
    },
}


def declared_unreachable(kind) -> dict | None:
    """★#45 纯函数★：该种类是否被声明为「从主城不可达 / 不可打」；是则返回声明项。

    ``kind`` 为 None / 未声明 → ``None``（不介入，保持旧行为）。
    """
    return UNREACHABLE_FROM_MAIN_CITY.get(kind or "")


def declared_grace_sec(kind) -> float | None:
    """★#45 纯函数★：该种类的「导航宽限秒数」；0 = 一确认中立页即判定（不再空等超时）。"""
    decl = declared_unreachable(kind)
    if decl is None:
        return None
    return float(decl["grace_sec"])


def unreachable_skip_reason(item) -> str | None:
    """★#45 纯函数★：把声明项渲染成该条目的跳过原因（未声明 → ``None``）。"""
    decl = declared_unreachable(getattr(item, "kind", "special"))
    if decl is None:
        return None
    return str(decl["reason"]).format(
        dungeon=getattr(item, "dungeon", "?"),
        difficulty=getattr(item, "difficulty", "?"),
    )


# 带自身「导航」的 kind → 导航宽限（秒）。**由上面的声明派生**（单一真源）：
#   · 被 #45 声明的 kind：grace_sec = 0 → 一确认中立页就【明确跳过】（不再空转超时）；
#   · 未声明的 kind：不在此表（.get 返回 None → 不介入，行为完全不变）。
_BATCH_NAV_TIMEOUT_BY_KIND = {
    kind: float(decl["grace_sec"]) for kind, decl in UNREACHABLE_FROM_MAIN_CITY.items()
}

# ★#44★ 归位「主城」多久仍未到中立页（画面可读且明确不是主城）→ 主动收工并记录原因，
#   绝不无限点「主城」空转。
_BATCH_HOME_TIMEOUT = 150.0

# 「画面还在忙」的判据：加载 / 战斗中 / 结算。这些页面上绝不能切目标或收工。
_BATCH_BUSY_NODES = (
    # 原 SpecialLoadingWait 已收敛到 common.json 的 PubLoadingWait（子识别 PubLoadingText）。
    "PubLoadingText",
    "SpecialBattleWait",
    "SpecialResultContinue",
    "SpecialResultFallback",
    "SpecialLevelUpContinue",
)


def _batch_busy(context, image) -> bool:
    for node in _BATCH_BUSY_NODES:
        try:
            detail = context.run_recognition(node, image)
        except Exception as exc:  # noqa: BLE001
            print(f"[batch] 忙闲检测 {node} 异常：{exc}")
            continue
        if detail is not None and getattr(detail, "hit", False):
            return True
    return False


def _batch_settled() -> bool:
    return (time.monotonic() - _BATCH_LAST_FIGHT_TS) >= _BATCH_MIN_SETTLE


# ===========================================================================
# ★#44 混排清单「假完成」—— 跨种类陈旧界面不得记账；切种类先回中立页★
#
# 现场（设备 16448 混排实测；证据：logs/mixed.log + frames/mixed/f_0088…f_0264）：
#   --list "碧之女王讨伐,中级,1;猩红巨熊讨伐,中级,1;战阵之宴,-,1;光之迷宫,中级,1;幻想连战,-,1"
#   · 前两条真打（开打 -> 结算）；
#   · 切到 战阵之宴 / 光之迷宫 后【没有「归位/开打」】却各记一笔「结算完成 1/1」= 假完成；
#   · 幻想连战**停在上一场残留的猩红巨熊详情页**上 PhantomDispatch<->PhantomWait 直到超时
#     （f_0088…f_0264 全部是那一张详情页；战阵之宴/迷宫/幻想界面从未出现）。
#
# 根因：切种类时指挥官只点了**一次**「主城」就假定已回中立页，随后
#   · RaidDispatch / FarmDispatch 的链在【上一场战斗的结算页】上跑，命中了残留的
#     「再次挑战」（RaidContinueChallenge / FarmRetry 的 action 带 record="always"）
#     -> 假记账（账本上 战阵之宴/光之迷宫 各自「完成」，实际没打）；
#   · PhantomDispatch 的幻想状态机在【陈旧详情页】上空转（phantom_act 甚至点了残留
#     结算页的 OK）。
#   => 没有把「当前在哪一页」与「当前该走哪个种类」对齐。
#
# 三条铁律（agent/side_impl.py + special_dungeon.json 两侧声明）：
#   1. 【自身导航才算数】一个条目只有在【走过它自己种类的导航/开打】之后才能记账；
#      别的种类的残留界面（陈旧「再次挑战」）绝不算 —— 由 _BATCH_ITEM_ENGAGED 把守：
#      record="always" 的结算动作在未经历自身导航前**既不点击也不记账**。
#   2. 【切种类先确认中立页】切换条目时若画面【可读且明确不是中立页（主城）】，
#      指挥官持续归位、并把三个种类分派器**封锁**（_BATCH_BLOCK_DISPATCH），
#      直到真正看到主城独有锚点才放行下一条（陈旧界面不得被别的种类的链动作碰到）。
#   3. 【无导航的种类明确跳过】战阵之宴不做导航，从主城到不了 -> 按导航超时**明确跳过
#      并记录原因**，绝不假记账、绝不空转。
# ===========================================================================
#: 主城【独有】锚点（与 tools/live_harness.MAIN_CITY_UNIQUE_ANCHORS 同源；#31 收紧为
#: 「三独有锚点」——「活动/领主战/关卡」会被领主战列表页/详情页命中，不能用）。
#: ★#63★：改从共享源 agent/battle_loop_core 取（与 harness / 深渊 / 五重 / 幻想 同一份对象）。
NEUTRAL_HOME_ANCHORS = MAIN_CITY_UNIQUE_ANCHORS
NEUTRAL_HOME_MIN = MAIN_CITY_MIN_UNIQUE


def is_neutral_home(items) -> bool:
    """画面 OCR 是否为主城（中立页）：主城【独有】锚点命中 >= :data:`NEUTRAL_HOME_MIN`。

    ★纯函数★（离线可单测，不碰设备）。主城独有锚点见上（#31 真机设备实证：放宽到
    六锚点会把领主战列表页误判成主城）。
    """
    if not items:
        return False
    texts = [t or "" for t, _b in items]
    hits = [a for a in NEUTRAL_HOME_ANCHORS if any(a in t for t in texts)]
    return len(hits) >= NEUTRAL_HOME_MIN


def classify_screen(items) -> str:
    """把一帧 OCR 归成 ``"unknown" / "neutral" / "other"``。★纯函数★

    · ``"unknown"``：读不到任何文字（items 为空 / None）-> 回退旧行为（不阻断），
      兼容离线 stub / OCR 不可用的场景，绝不凭「读不到」臆断；
    · ``"neutral"``：主城（中立页）-> 允许开始下一条；
    · ``"other"``  ：可读但明确不是主城（列表 / 详情 / 结算 / 幻想页…）->
      切种类时必须先归位（见文件头铁律 2）。
    """
    if not items:
        return "unknown"
    return "neutral" if is_neutral_home(items) else "other"


def _read_screen_items(context, image):
    """读一帧全屏 OCR（供 #44 的「当前是否中立页」判定用）。

    OCR 不可用（旧框架 / 离线 stub）返回 ``None`` —— 视为不可读，绝不臆断。
    """
    try:
        return ocr_all(context, image, "OcrTask")
    except Exception as exc:  # noqa: BLE001 —— 判页失败不是致命错误，但必须可见
        print(f"[batch] 屏幕 OCR 失败（视为不可读，回退旧行为）：{exc}")
        return None


def _note_item_engaged() -> None:
    """★#44★ 标记「当前条目已走过自身种类的导航/开打」——这是记账的前提（铁律 1）。

    由【该种类自己的】页面动作在批量激活时调用：详情/迷宫页的战斗按钮识别器
    （``special_target_fight``）与开打动作（``special_batch_fight``）。
    战阵之宴没有任何此类节点（它不做导航）-> 永远不 engaged -> 它的 record="always"
    结算动作既不点击也不记账，改由导航超时明确跳过（铁律 3）。
    """
    global _BATCH_ITEM_ENGAGED
    with _BATCH_LOCK:
        if _BATCH_ACTIVE:
            _BATCH_ITEM_ENGAGED = True


# ===========================================================================
# ★#22 单目标收工闸★
#
# 问题（#13 真机实证）：单目标模式（清单为空）**没有收工条件**。配置次数
# （选项「打几次」= 写成 ``SpecialFightTargetRow.max_hit``，「限制战斗开始次数」）
# 打满后，该节点只是「不再从候选里命中」，没有任何东西把流程推向终止 → 只能在
# 主城 ↔ 列表 ↔ 详情 之间无限重进（15:50:48→15:54:06 约 60 轮，每轮 ~3s）。
#
# 做法：**复用**批量路径已有的终止节点 ``SpecialBatchStop``（DirectHit + StopTask），
# 在**结算帧**把当前结算节点的 next 覆盖成它 —— 与批量指挥官「override_next 到
# SpecialBatchStop」是同一机制，不另造并行终止。
#
# 为什么在结算帧判定：配置次数由框架按任务维护的**命中计数**（context.get_hit_count）
# 承担；第 N 次命中发生在【点开打】那一刻，那一刻收工会丢掉最后一局（批量设计里
# 踩过的坑：「点完挑战立刻计数 → 归位/收工，战斗才刚开始」）。等到**本局的结算帧**
# 才收工，与 phantom 上限「打完才停（在第 N 关的结算帧收工）」同一约定。
# ===========================================================================
_SINGLE_TARGET_FIGHT_NODES = ("SpecialFightTargetRow",)
_SINGLE_TARGET_STOPPED = False  # 单目标已下单收工（防止多页结算里重复覆盖）


def _single_target_finished(context, argv) -> str | None:
    """单目标模式：配置次数是否已打满？返回用尽的战斗节点名，否则 ``None``。

    * 仅「单目标」（批量清单未激活）且入口种类 = ``special`` 时生效；
    * 配置次数 = 该战斗节点（``SpecialFightTargetRow``）被选项写死的**有限** ``max_hit``
      （缺省不写 = 不限次 → 没有收工条件，行为不变）；
    * 命中计数由框架按任务维护（任务重开清零），与 ``max_hit`` 同源，故可比较。

    读不到节点定义 / 计数（旧框架、离线 stub）一律返回 ``None`` —— 绝不臆测
    「已打满」而误停任务。
    """
    if _BATCH_ACTIVE or _SINGLE_TARGET_STOPPED:
        return None
    if _entry_kind(argv) != "special":
        return None
    for node in _SINGLE_TARGET_FIGHT_NODES:
        try:
            data = context.get_node_data(node) or {}
            max_hit = data.get("max_hit")
            if max_hit is None:
                continue
            max_hit = int(max_hit)
            if max_hit <= 0:
                continue
            if int(context.get_hit_count(node)) >= max_hit:
                return node
        except Exception as exc:  # noqa: BLE001 —— 读不到就当「未打满」，绝不误停
            print(f"[single] 读取 {node} 次数失败（视为未打满）：{exc}")
            continue
    return None


def _single_target_stop(context, argv) -> None:
    """已打满配置次数 → 把**当前结算节点**的 next 覆盖成 ``SpecialBatchStop``（结算帧收工）。"""
    global _SINGLE_TARGET_STOPPED
    fight = _single_target_finished(context, argv)
    if fight is None:
        return
    node = getattr(argv, "node_name", None) or "SpecialResultContinue"
    try:
        context.override_next(node, ["SpecialBatchStop"])
    except Exception as exc:  # noqa: BLE001
        print(f"[single] 收工 override_next({node}) 失败：{exc}")
        return
    with _BATCH_LOCK:
        _SINGLE_TARGET_STOPPED = True
    print(f"[single] 目标已打满配置次数（{fight}）→ 结算帧收工（SpecialBatchStop），不再重进同一目标")


# ===========================================================================
# ★#30 幻想共斗房 vs 公共「挑战」打断★
#
# 背景（真机 Stage D，`--list "幻想连战,-,1"`）：幻想连战的**协力关**点卡片「战斗」后
# 进入的是【共斗房】（房间号码 / 招募 / 队友），不是单人编队页。共斗房里「挑战」在没
# 招募到队友前是【灰的、不可用】。而公共打断 ``PubChallenge`` 的判据只是裸 OCR
# ``^挑战$`` + 盲点，且被注入在每个流程节点的**封锁的打断前缀**里（scene.events 的
# INTERRUPT_EVENTS，位置由 #18 锁死）—— 它排在幻想的门控节点（PhantomCoopRecruit /
# PhantomRecruitStart / PhantomCoopChallenge）之前，于是命中共斗房的「挑战」→ 点是灰的、
# 画面不变 → [JumpBack] 重扫前缀 → 再命中 → **死循环**，幻想的招募/收工节点永远轮不到。
#
# 修法（不动封锁的前缀、也不动共享的 common.json）：在种类分派器里**按种类**把
# PubChallenge 的判据收窄 —— phantom 时只认【单人编队页底部】的「挑战」（与 phantom.json
# 的 PhantomSoloChallenge 同一 ROI [150,980,600,1180]；真机实测单人编队「挑战」在
# 720 box≈[297,1069,80,47]，中心 y≈1092 落在带内；共斗房「挑战」在 box≈[297,906,81,46]，
# 中心 y≈929 落在带外）；非 phantom 时逐字还原成**真源形状** ``^挑战(→)?$``（全屏、无 ROI）。这样：
#   · 单人编队页：PubChallenge 照常点「挑战」（行为不变）；
#   · 共斗房：PubChallenge 不再命中 → 交给幻想的门控节点招募/挑战；若招募不到队友，
#     由 phantom_impl.PhantomGiveUpRecognition 的「共斗房停留上限」有界收工（带原因）。
# ===========================================================================
_PUBCHALLENGE_NODE = "PubChallenge"
# ★#110★ 「挑战」按钮的点击判据 = **真源 scene/challenge.py::CHALLENGE_CLICK_PATTERNS 的运行时快照**。
#   `^挑战(→)?$` = 整串锚定 + **至多一个箭头**（真机帧两种渲染：`挑战` / `挑战→`，识别调研
#  统计 8/17 帧带箭头）。★为什么不 import★：`agent/` 是安装态的**独立目录**（没有 `scene/`，
#  与 ``_TEAM_PAGE_ANCHORS_SNAPSHOT`` / 迷宫模板快照同理），所以这里存逐字快照，并由
#  ``tools/contract_hooks/hooks_110.py`` 钉「快照 == 真源」。★#110 之前这里是 `^挑战$`★：
#  运行期 override 会把 common.json 的判据**改回**旧形状 → 修了 common.json 也白修
#  （这正是本常量必须同步的理由）。
_PUBCHALLENGE_PATTERNS = [r"^挑战(→)?$"]
# common.json 里 PubChallenge 的原始判据（与真源同形、全屏、无 ROI）。还原时逐字一致。
_PUBCHALLENGE_ORIGINAL = {"expected": list(_PUBCHALLENGE_PATTERNS)}
# phantom 模式下「挑战」只认底部编队页按钮区（与 phantom.json::PhantomSoloChallenge 同 ROI）。
_PUBCHALLENGE_PHANTOM_ROI = [150, 980, 600, 1180]
# 已应用的形态：(task_id, scope)；scope ∈ {"phantom", "original"}。None = 尚未动过。
_pubchallenge_applied: tuple = (None, None)


def pubchallenge_override_for(kind: str) -> dict:
    """返回「按种类收窄/还原公共打断 PubChallenge」的 pipeline override。

    kind == "phantom" → 收窄到 :data:`_PUBCHALLENGE_PHANTOM_ROI`（不认共斗房的挑战）；
    其余（farm / raid / special）→ 逐字还原成 :data:`_PUBCHALLENGE_ORIGINAL`。
    这是 **纯函数**：离线守卫直接断言它的形状，不依赖真机 context。
    """
    if kind == "phantom":
        return {
            _PUBCHALLENGE_NODE: {
                "recognition": {
                    "type": "OCR",
                    "param": {
                        # ★#110★ 收窄的只是**页面带**，判据形状仍与真源一致（两种渲染都认）。
                        "expected": list(_PUBCHALLENGE_PATTERNS),
                        "roi": list(_PUBCHALLENGE_PHANTOM_ROI),
                    },
                }
            }
        }
    return {
        _PUBCHALLENGE_NODE: {
            "recognition": {"type": "OCR", "param": dict(_PUBCHALLENGE_ORIGINAL)}
        }
    }


def _ensure_pubchallenge_scope(context, scope: str, task_id) -> None:
    """把 PubChallenge 收窄/还原到 ``scope``；同一任务同一形态只应用一次（幂等）。

    task_id 变化（新任务）时强制重放：pipeline 会随新任务复位回 common.json 原形，
    若只靠内存标志就会漏掉。
    """
    global _pubchallenge_applied
    if context is None:
        return
    if _pubchallenge_applied == (task_id, scope):
        return
    try:
        context.override_pipeline(pubchallenge_override_for(scope))
    except Exception as exc:  # noqa: BLE001 —— 覆盖失败不致命（最坏是回到旧行为），但要可见
        print(f"[batch] 收窄 PubChallenge（{scope}）失败：{exc}")
        return
    _pubchallenge_applied = (task_id, scope)
    where = (
        "收窄到单人编队页底部（整串锚定 + 可选箭头）"
        if scope == "phantom"
        else "还原为全屏（整串锚定 + 可选箭头）"
    )
    print(f"[batch] 公共打断 PubChallenge 已{where}（#30）")


# ===========================================================================
# ★#50 滚动预算「每条目重置」 + 用尽时的有界停止★
#
# 现场（设备 16448，5 个【深行】成员的降临讨伐 chunk，原生日志）：
#   ``max_hit reached [data.name=SpecialScrollList] [current_hit=30] [data.max_hit=30]``
#   —— 框架的命中计数是**按任务**累计的（任务重开才清零），而一个批量 chunk =
#   一个任务，故按任务写死的 ``SpecialScrollList.max_hit`` 被整条清单**共享消费**：
#   5 个深行成员共用一个 30 次的预算，用尽后该节点被框架**静默跳过** → 目标行永远
#   滚不到 → 链只剩 ``SpecialEntry`` / ``SpecialTabJoss`` 互跳 → 空转到超时。
#   单个成员的 fresh task 里，整份预算都归它用，故同一个深行目标「找得到」。
#
# 修法（两条，缺一不可）：
#   1. 【每条目重置】切换条目、开始导航前，由指挥官把 ``SpecialScrollList`` 的命中上限
#      抬到「当前命中数 + 每条目预算」（见 :func:`restored_scroll_max_hit` 与
#      :func:`_ensure_scroll_budget`）。等价于每个条目都有一份完整预算；总量仍受
#      「条目数 × 预算」约束，**单条目滚动不超过一份预算 → 仍有界**。
#   2. 【用尽即有界停止】单条目把一份预算滚完仍未把目标行滚进屏幕（唯一原因：目标行
#      不在列表里，或一直滚错页）→ 指挥官**明确跳过该目标并记录原因**
#      （见 :func:`scroll_budget_exhausted` 与指挥官里的「滚动预算用尽」分支），
#      绝不静默空转、绝不假记账。这是「预算再大也可能不够」时的安全网。
#
# 单源：:data:`_PER_ITEM_SCROLL_BUDGET` 必须 == 产品
# ``special_dungeon.json::SpecialScrollList.max_hit``（守卫 hooks_50 逐字段断言）。
# ===========================================================================
SCROLL_NODE = "SpecialScrollList"
_PER_ITEM_SCROLL_BUDGET = 80
_BATCH_SCROLL_CEILING: int | None = None   # 当前条目的滚动命中上限（None = 未启用 / 单目标）


def per_item_scroll_budget(node_data) -> int | None:
    """节点数据里「声明的滚动预算」；未声明 / 不限次（缺 ``max_hit``）/ 非法 → ``None``。

    ★纯函数★（离线可单测，不碰设备）。``None`` = 无需重置（保持「不限次」的旧行为）。
    """
    if not isinstance(node_data, dict):
        return None
    mh = node_data.get("max_hit")
    if mh is None:
        return None
    try:
        mh = int(mh)
    except (TypeError, ValueError):
        return None
    return mh if mh > 0 else None


def restored_scroll_max_hit(current_hit, budget) -> int:
    """★纯函数★ 条目切换时滚动节点的新 ``max_hit`` = 当前命中数 + 每条目预算。

    框架计数器按任务累计、不会自减；把上限抬到「已用 + 一份预算」，就等价于
    「本条目重新得到一份完整预算」，且总量仍被「条目数 × 预算」封顶（有界）。
    """
    return int(current_hit) + int(budget)


def scroll_budget_exhausted(current_hit, ceiling) -> bool:
    """★纯函数★ 本条目滚动预算是否已用尽（命中数达到条目上限）。

    ``ceiling is None``（单目标 / 未启用）→ 永远 ``False``（绝不误判）。
    """
    if ceiling is None:
        return False
    return int(current_hit) >= int(ceiling)


def _ensure_scroll_budget(context, task_id) -> None:
    """★#50★ 条目切换后调用：把 ``SpecialScrollList`` 的命中预算按条目恢复一份。

    · 产品未声明有限 ``max_hit`` → 不动（保持「不限次」的旧行为）；
    · 读不到 context / 节点数据 / 命中计数（旧框架、离线 stub）→ 静默跳过
      （绝不臆断、绝不误重置，更不因此让流程失败）。
    """
    global _BATCH_SCROLL_CEILING
    if context is None:
        return
    try:
        node = context.get_node_data(SCROLL_NODE)
    except Exception as exc:  # noqa: BLE001 —— 读不到节点就当「无需重置」
        print(f"[batch] 读取 {SCROLL_NODE} 节点数据失败（跳过滚动预算重置）：{exc}")
        return
    if per_item_scroll_budget(node) is None:
        return
    try:
        hits = int(context.get_hit_count(SCROLL_NODE))
    except Exception as exc:  # noqa: BLE001
        print(f"[batch] 读取 {SCROLL_NODE} 命中计数失败（跳过滚动预算重置）：{exc}")
        return
    ceiling = restored_scroll_max_hit(hits, _PER_ITEM_SCROLL_BUDGET)
    try:
        context.override_pipeline({SCROLL_NODE: {"max_hit": ceiling}})
    except Exception as exc:  # noqa: BLE001
        print(f"[batch] 滚动预算重置失败：{exc}")
        return
    with _BATCH_LOCK:
        _BATCH_SCROLL_CEILING = ceiling
    print(
        f"[batch] 滚动预算按条目重置：{SCROLL_NODE}.max_hit={ceiling}"
        f"（本条已用 {hits}，每条预算 {_PER_ITEM_SCROLL_BUDGET}）(#50)"
    )


class BatchModeRecognition(CustomRecognition):
    """按「当前副本种类」放行/拦截的开关识别器（custom_recognition "batch_mode"）。

    挂在 FarmDispatch / RaidDispatch / PhantomDispatch 这三个「种类分派器」上：
        · 种类匹配 → box=[0,0,0,0] 命中，随后走该分派器 next 里的 farm/raid/phantom 节点链；
        · 不匹配   → box=None 不命中，SpecialEntry 继续走 special 节点链。

    ★为什么用「入口 + 清单」决定种类★
      · 清单非空：种类 = 当前目标 item.kind（由指挥官 SpecialBatchPlan 写入 _BATCH_MODE）；
      · 清单为空：种类 = 任务入口（FarmEntry→farm / RaidEntry→raid /
        PhantomEntry→phantom / SpecialEntry→special）。
    这样「自动刷副本」单目标流程（入口 SpecialEntry、清单为空）下三个分派器永远不命中，
    行为与合并前【完全一致】；而「重复刷图 / 战阵之宴 / 自动刷幻想」三个旧入口也能各自
    跑回原逻辑。

    ★#30 另承担一件按种类收窄公共打断的事★：这些分派器每轮都会被评估，是「当前是什么
    种类」的最早可靠信号 —— 于是在这里按种类把公共打断 ``PubChallenge`` 收窄/还原（见
    ``_PUBCHALLENGE_*`` 常量与 :func:`pubchallenge_override_for`）。它必须先于任何页面
    （尤其是幻想共斗房）发生，否则会来不及。

    参数（custom_recognition_param）：
        kind : 本分派器负责的种类，"farm" / "raid" / "phantom"。
    """

    def analyze(self, context, argv):
        param = read_param(argv)
        want = param.get("kind") or "farm"
        with _BATCH_LOCK:
            mode = _BATCH_MODE
        if mode is None:
            mode = _entry_kind(argv)
        # ★#30★：按种类收窄/还原公共打断 PubChallenge（每轮自纠，见 _ensure_pubchallenge_scope）。
        _ensure_pubchallenge_scope(
            context, "phantom" if mode == "phantom" else "original",
            getattr(getattr(argv, "task_detail", None), "task_id", None),
        )
        # ★#44★：切种类尚未确认回中立页（主城）时，封锁三个种类分派器 ——
        #   陈旧界面（上一场的详情/结算页）绝不能被「别的种类」的链动作或记账碰到。
        with _BATCH_LOCK:
            blocked = _BATCH_BLOCK_DISPATCH
        if blocked:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"batch_mode": mode, "dispatch": want, "blocked": "await_neutral"},
            )
        if mode == want:
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0], detail={"batch_mode": mode, "dispatch": want}
            )
        return CustomRecognition.AnalyzeResult(box=None, detail={"batch_mode": mode, "dispatch": want})


def _batch_override(item: BatchItem) -> dict:
    """为一个目标生成 runtime pipeline 覆盖（识别参数 + 必要的守门开关），按种类分派。"""
    if item.kind == "farm":
        return _farm_override(item)
    if item.kind == "raid":
        return _raid_override(item)
    if item.kind == "phantom":
        return _phantom_override(item)
    return _special_override(item)


def _phantom_override(item: BatchItem) -> dict:
    """幻想连战（phantom）：把「目标套数」写进幻想的出口识别，并把正常收工改成回指挥官。

    ★合并的关键语义★
      · PhantomDone = 幻想想的「跑够套数」正常出口。单目标时它 action=StopTask，把整个
        任务停掉；批量清单里的这一条幻想跑够套数后【不能停整个任务】，而应回 SpecialEntry
        让批量指挥官拿清单下一条。做法：把 action 改成 DoNothing（节点 next 已统一为
        SpecialEntry）→ 跑完这条幻想后自然回到指挥官。
      · target_sets = item.times（绝对套数，不是「剩余」）：幻想的 _recover_counters 会从
        phantom/set/* 账本恢复已完成套数，target 用绝对值才能在「中途重开」后正确续跑。
      · mode="batch" → PhantomDone/GiveUp 不再写 phantom/run/completed 收工标记，避免下一轮
        新任务把幻想账本清空（那样会丢掉「已完成几套」的统计）。单目标的默认 mode="single"
        行为与合并前完全一致。
      · PhantomGiveUp（超时/无进展/未知过多/记账异常）的 StopTask 保持不变：批量下遇到
        这类异常宁可整任务安全停止，绝不带病空转（★兜底出口不破坏★）。

    导航（主城→活动→终始之战→幻想连战）由 phantom.json 自己的状态机节点负责，
    由 special_dungeon.PhantomDispatch（batch_mode 门控 kind=phantom）放行；此处不碰导航。
    """
    return {
        "PhantomDone": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "phantom_done",
                    "custom_recognition_param": {
                        "ocr_entry": "OcrTask",
                        "target_sets": item.times,
                        "mode": "batch",
                    },
                },
            },
            # 跑够套数 → 不 StopTask，回 SpecialEntry（节点 next 已是 SpecialEntry）。
            "action": {"type": "DoNothing", "param": {}},
        },
        "PhantomGiveUp": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "phantom_giveup",
                    "custom_recognition_param": {
                        "ocr_entry": "OcrTask",
                        "max_task_sec": 7200,
                        "lost_sec": 60,
                        "no_progress_sec": 900,
                        "coop_room_sec": 120,
                        "target_sets": item.times,
                        "mode": "batch",
                    },
                },
            },
        },
    }


def _special_override(item: BatchItem) -> dict:
    """领主战 / 降临讨伐：改副本名与难度行，走原有 special 导航链。"""
    diff = DIFF_REGEX.get(item.difficulty, r"高级$")
    joss = is_joss(item.dungeon)
    return {
        "SpecialEnterBoss": {
            "recognition": {
                "type": "OCR",
                "param": {"expected": [item.dungeon], "roi": [150, 440, 320, 800]},
            }
        },
        "SpecialFightTargetRow": {
            # ★P0★ 直接返回该难度行【战斗】按钮的 OCR 框（零偏移），绝不误点推荐编成。
            # ★#35★ pair="below"：按真机几何（难度名在上、战斗在下方 ≈40px）配对，
            #   否则会配到上一行的战斗（静默打错难度）或单行成员无处可配（卡死）。
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "special_target_fight",
                    "custom_recognition_param": {"difficulty": diff, "pair": "below"},
                },
            },
            # 关掉「打几次」对难度行的次数上限，次数改由账本按目标统计。
            "max_hit": 999999,
        },
        # 批量模式一律「指定难度」，关掉「打满 / NEW 行」相关节点，避免打错档。
        "SpecialNewBadge": {
            "recognition": {"type": "OCR", "param": {"expected": ["__NONE__"], "roi": [0, 380, 120, 600]}}
        },
        "SpecialFullFirstFight": {"recognition": {"type": "OCR", "param": {"expected": ["__NONE__"]}}},
        "SpecialFullNoNew": {"recognition": {"type": "OCR", "param": {"expected": ["__NONE__"]}}},
        "SpecialFullStop": {"recognition": {"type": "OCR", "param": {"expected": ["__NONE__"]}}},
        # tab：领主战副本开「领主战」tab；降临讨伐副本开「降临讨伐」tab。
        # max_hit 抬高，允许一个任务里跨 tab 多次切换。
        "SpecialTabLord": {
            "recognition": {
                "type": "OCR",
                "param": {"expected": ["__NONE__"] if joss else ["^领主战$"], "roi": [0, 375, 360, 60]},
            },
            "max_hit": 200,
        },
        "SpecialTabJoss": {
            "recognition": {
                "type": "OCR",
                "param": {"expected": ["降临讨伐"] if joss else ["__NONE__"], "roi": [360, 375, 360, 60]},
            },
            "max_hit": 200,
        },
    }


def _farm_override(item: BatchItem) -> dict:
    """摇曳的迷宫（farm）：把「目标行名 + 所属域」写进 farm 目标节点，并设「剩余次数」。

    导航（主城→主城左侧轮播横幅「摇曳的迷宫」→迷宫页；见 FarmMazeEntry）由 FarmDispatch
    那条 farm 链负责，此处不碰。旧的「主城→活动→培育道具」导航已停用（见下）。

    ★迷宫行【战斗】按钮：与领主战详情页同一套 custom「special_target_fight」★
      pair="below"：在迷宫列表页里，【战斗】在迷宫名的【左下方】；识别器直接返回
      【战斗】自己的 OCR 框（点击=框中心、零偏移）。绝不用旧 FarmFight 的
      `target_offset [-185,37]`——那会因迷宫名 OCR 框抖几像素而落到只低 36px 的
      【推荐编成】上，改掉用户队伍（本项目踩过的破坏性坑）。

    ★#54 目标 = 【域 + 行名】★
      · ``target`` = 行名（``item.target``，行名自含【元素】/Lv../层）；``domain`` = 域
        （``item.domain``）随行名一起声明。**元素不再是独立字段**（#52 已随本票作废）。
      · ``FarmDomainPick``（纯数据节点，不在任何 next 里、永不执行）= GUI「打哪个迷宫域」
        选项的落点，与 FarmFight 的 domain 互补。

    ★次数与记账★
      · FarmFight 点迷宫列表的【战斗】进入本局（动作/识别见上）。
      · FarmRetry（结算页【再次挑战】）动作换成 custom「special_batch_finish」且
        record="always"：每点一次 = 又打完一局 → 记一笔账本；max_hit 设成该目标的
        剩余次数，点满即停（与旧「刷几次」的 max_hit 语义一致）。
      · 点满后再多出的那一局结算页，由 farm 链里的 SpecialResult* / FarmWait 收尾
        （它们不记账），随后指挥官归位主城、切下一个目标。

    ★导航节点的 max_hit（滚动终止条件）★
      · 活动页向下滚动（FarmEventScrollDown）每次只滑一小段，实测 1~3 次即露出
        「培育道具」；批量一个任务跑多个迷宫目标时每个目标都要重滚一次，故给一个
        【有限但够用】的上限 40（绝不是 200/无限；到不了也会停，不会空转）。
      · 迷宫页滚动（FarmScroll/FarmScrollUp）同理设 40。
    """
    return {
        "FarmFight": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "special_target_fight",
                    "custom_recognition_param": {
                        # ★#54★ 目标行 = 行名（target）+ 所属域（domain）；域内行名自含
                        #   【元素】/Lv../层。识别器按行名匹配（严格式优先、容错式兜底），
                        #   并回指同一行证明归属（绝不落到相邻行）。
                        "target": item.target,
                        "domain": item.domain,
                        "pair": "below",
                    },
                },
            },
            "max_hit": 1,
        },
        # ★#54★ 域节点（纯数据，不在任何 next 里、永不执行）：落点与 GUI「打哪个迷宫域」
        #   一致，与 FarmFight 的 domain 互补（批量路径把域直接写进 FarmFight.domain）。
        "FarmDomainPick": {
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "special_target_fight",
                    "custom_recognition_param": {
                        "domain": item.domain,
                        "pair": "below",
                    },
                },
            },
        },
        # ★#57★ 域判定 = 图片匹配（batch 路径）：把声明的域的**横幅模板**写进 FarmMazeEntry
        #   的门控叶（FarmMazeDomain）—— 于是只有当主城横幅正显示【该域】时才会点进去；
        #   并把**页眉模板**写进复核叶（FarmDomainVerify）—— 进域后由迷宫页滚动/FarmFight
        #   复核「确实进了该域」才推进。未知域 -> {}（保持基线默认，绝不静默进别的域）。
        **_maze_domain_template_overrides(item.domain),
        "FarmRetry": {
            "recognition": {"type": "OCR", "param": {"expected": ["再次挑战"]}},
            "action": {
                "type": "Custom",
                "param": {
                    "custom_action": "special_batch_finish",
                    "custom_action_param": {"record": "always"},
                },
            },
            "max_hit": remaining(item),
        },
        # ★迷宫页滚动（FarmScroll/FarmScrollUp）★：批量一个任务里可能要滚多次，
        # 给一个【有限但够用】的上限 40（绝不是 200/无限；到不了也会停，不会空转）。
        "FarmScroll": {
            "max_hit": 40,
        },
        "FarmScrollUp": {
            "max_hit": 40,
        },
        # ★已停用的旧「主城→活动→培育道具」导航★（farm 链已移除这些节点）：
        # max_hit 一律收到 1（过去被抬到 40 → 活动页空滚 25 次的元凶）。
        # 保留 override 只为旧配置兼容；识别不到就停，绝不空转。
        "FarmGrowCard": {
            "max_hit": 1,
        },
        "FarmEventScrollDown": {
            "max_hit": 1,
        },
        "FarmEventScrollUp": {
            "max_hit": 1,
        },
    }


def _raid_override(item: BatchItem) -> dict:
    """战阵之宴（raid）：不做导航的现状保持，只设「该目标的剩余次数」。

    RaidContinueChallenge（结算页【再次挑战 / 继续挑战】）是 raid 循环的核心：
    动作换成 custom「special_batch_finish」且 record="always"（每点一次 = 打完一局，
    记一笔账本），max_hit 设成该目标的剩余次数。首局由 raid 链里的 [JumpBack]PubChallenge
    开打（不记账），其结算由第一次「再次挑战」点击记账。
    """
    return {
        "RaidContinueChallenge": {
            "recognition": {"type": "OCR", "param": {"expected": ["再次挑战", "继续挑战"]}},
            "action": {
                "type": "Custom",
                "param": {
                    "custom_action": "special_batch_finish",
                    "custom_action_param": {"record": "always"},
                },
            },
            "max_hit": remaining(item),
        },
    }


class SpecialBatchPlanRecognition(CustomRecognition):
    """批量副本清单的「指挥官」。

    参数（custom_recognition_param）：
        list : 多行清单文本（interface「要刷的副本清单」注入）。

    返回：
        · box=None   → 不命中（清单为空/未激活，或当前目标还在正常推进）；
        · box=[0,0,0,0] → 命中：本节点 action（点底部「主城」）执行，随后 next 决定
          是回 SpecialEntry 继续，还是走 SpecialBatchStop 收工。
    """

    def analyze(self, context, argv):
        global _BATCH_TASK_ID, _BATCH_RAW, _BATCH_ACTIVE, _BATCH_CURRENT
        global _BATCH_NEEDS_HOME, _BATCH_FINISHED, _BATCH_IN_FIGHT, _BATCH_FIGHT_START_TS
        global _BATCH_TARGET_START_TS
        global _BATCH_MODE
        global _SINGLE_TARGET_STOPPED
        global _BATCH_LOSSES, _GO_PENDING
        global _BATCH_ITEM_ENGAGED, _BATCH_BLOCK_DISPATCH, _BATCH_HOME_START_TS
        global _BATCH_SCROLL_CEILING
        param = read_param(argv)
        raw = param.get("list")
        if raw is None:
            raw = param.get("清单") or ""
        raw = str(raw)
        task_id = getattr(argv.task_detail, "task_id", None)

        with _BATCH_LOCK:
            if task_id != _BATCH_TASK_ID or raw != _BATCH_RAW:
                _BATCH_TASK_ID = task_id
                _BATCH_RAW = raw
                items, errors = parse_batch(raw)
                _BATCH_ITEMS.clear()
                _BATCH_ITEMS.extend(items)
                _BATCH_ERRORS.clear()
                _BATCH_ERRORS.extend(errors)
                _BATCH_CURRENT = None
                _BATCH_NEEDS_HOME = False
                _BATCH_FINISHED = False
                _BATCH_IN_FIGHT = False
                _BATCH_FIGHT_START_TS = 0.0
                _BATCH_TARGET_START_TS = 0.0
                _BATCH_MODE = None
                _SINGLE_TARGET_STOPPED = False
                _BATCH_SKIPPED.clear()
                _BATCH_LOSSES = 0
                _GO_PENDING = False
                _BATCH_ITEM_ENGAGED = False
                _BATCH_BLOCK_DISPATCH = False
                _BATCH_HOME_START_TS = 0.0
                _BATCH_SCROLL_CEILING = None
                reset_detail_difficulty()
                reset_wrong_detail_state()
                reset_rows_seen()
                # ★#62★ 新任务：复位「自己详情页配不出战斗」的计时。
                reset_unfightable_detail(task_id)
                _BATCH_ACTIVE = bool(items) and not errors
                if items:
                    print(f"[batch] 清单解析成功：{len(items)} 个目标")
                    for it in items:
                        print(f"[batch]   - {it.label}")
                for err in errors:
                    print(f"[batch] 解析错误：{err}")
            items = list(_BATCH_ITEMS)
            errors = list(_BATCH_ERRORS)
            active = _BATCH_ACTIVE
            finished = _BATCH_FINISHED

        # 有解析错误：明确报错并终止批量（绝不静默跳过非法行）。
        if errors:
            if not finished:
                with _BATCH_LOCK:
                    _BATCH_FINISHED = True
                print("[batch] 清单存在无法解析的行 → 终止批量任务，请修正后重试")
                context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"batch": "error", "errors": errors})
            return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "error"})

        # ★#38 战斗失败 / GAMEOVER★（在 #39 难度发现之前处理：失败画面更紧急）
        #   · 画面 = GAMEOVER/是否续关？：**只记一次**连续失败、清 in_fight（这一局已失败
        #     结束），随后交由 [JumpBack]PubGameOverGiveUp 读『放弃』框点击（拒绝续关）；
        #   · 画面 = 放弃确认框：不动作，交由 [JumpBack]PubGameOverConfirm 读『OK』框推进；
        #   · 已离开失败画面且不在忙（非加载/战斗/结算）：按 plan_gameover_action 决定
        #     ——「放弃该目标继续清单」或（连续 2 次 / 无目标可继续）「主动收工」。
        #   识别与决定分家的理由见 classify_gameover / plan_gameover_action 上方注释。
        # ???? OCR?#42 ?????#44 ??????????? GAMEOVER ??????????
        #   ??????? OCR ???items2 = (text, box) ???classify_gameover / classify_screen ???
        items_raw = _ocr_scored(context, argv.image)
        items2 = [(t, b) for t, b, _s in items_raw] if items_raw else None
        if items2:
            # #42?????????? ? ?????????????????????????????????
            note_list_rows(items_raw)
        screen_items = items2
        go_state = classify_gameover(items2) if items2 else None
        with _BATCH_LOCK:
            go_pending = _GO_PENDING
        if go_state == "giveup":
            if not go_pending:
                with _BATCH_LOCK:
                    _BATCH_LOSSES += 1
                    _GO_PENDING = True
                    # 这一局已经失败结束：清 in_fight，否则指挥官会一直「战斗中」等到超时。
                    _BATCH_IN_FIGHT = False
                    consecutive = _BATCH_LOSSES
                print(
                    f"[batch] 战斗失败（GAMEOVER/是否续关？）连续第 {consecutive} 次 → 拒绝续关"
                    f"（交由 SpecialGameOverGiveUp 读『放弃』框点击），随后按策略处理"
                )
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"batch": "gameover_giveup", "pending": True}
            )
        if go_state == "confirm":
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"batch": "gameover_confirm"}
            )
        if go_pending and not _batch_busy(context, argv.image):
            with _BATCH_LOCK:
                consecutive = _BATCH_LOSSES
                active_now = _BATCH_ACTIVE
                running_now = _BATCH_CURRENT
                others = [it for it in _BATCH_ITEMS if it is not running_now]
            action, reason = plan_gameover_action(
                consecutive,
                limit=GAMEOVER_CONSECUTIVE_LIMIT,
                batch_active=active_now,
                has_current=running_now is not None,
                remaining_other=len(others),
            )
            if action == "abandon_continue":
                with _BATCH_LOCK:
                    if running_now is not None:
                        _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running_now]
                    _BATCH_CURRENT = None
                    _BATCH_NEEDS_HOME = False
                    _BATCH_TARGET_START_TS = 0.0
                    _GO_PENDING = False
                    _BATCH_SKIPPED.append(reason)
                print(f"[batch] {reason}")
                items = list(_BATCH_ITEMS)
                # 落到下面的正常流程：next_item 会挑下一个目标并归位主城（绝不卡死在失败画面）。
            else:
                if not finished:
                    with _BATCH_LOCK:
                        _BATCH_FINISHED = True
                        _GO_PENDING = False
                    print(f"[batch] {reason}")
                    context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
                    return CustomRecognition.AnalyzeResult(
                        box=[0, 0, 0, 0],
                        detail={
                            "batch": "gameover_stop",
                            "consecutive": consecutive,
                            "reason": reason,
                        },
                    )
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"batch": "gameover_stop"}
                )

        # ★#42 详情页身份校验★：这一帧若是「别人的详情页」，**绝不在这里开打/记账**：
        #   · 第 1..N 次 → 退回并重新导航（本节点 action 点底部「主城」回主城，pipeline 重进）；
        #   · 连续超限  → 把该目标记为**失败/跳过**并写明原因（绝不静默记成目标成员）。
        #   与识别器 SpecialTargetFightRecognition 里的同一判定**互为双保险**：
        #   识别器那一份保证「战斗按钮不会被点」（= 不会静默记账），这一份负责**恢复**，
        #   否则错页上「没有目标行 / 也没有更新列表」会让链空转（#36 说过的互跳）。
        wrong = _wrong_detail_state(context, argv, items_raw)
        if wrong is not None:
            member, ident = wrong
            hit_n = _note_wrong_detail(member, task_id)
            action, reason = plan_wrong_detail_action(member, hit_n)
            print(
                f"[batch] 详情页身份校验：目标={member!r} 打开的是 {ident.get('title')!r}"
                f"（横幅归属 {ident.get('best_member')!r}/{ident.get('best_sim')}，"
                f"目标相似度 {ident.get('target_sim')}）→ {reason}"
            )
            with _BATCH_LOCK:
                running_now = _BATCH_CURRENT
                batch_running = (
                    _BATCH_ACTIVE
                    and running_now is not None
                    and getattr(running_now, "kind", "special") == "special"
                )
                if action == "skip":
                    if batch_running:
                        _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running_now]
                        _BATCH_CURRENT = None
                        _BATCH_NEEDS_HOME = False
                        _BATCH_TARGET_START_TS = 0.0
                    _BATCH_SKIPPED.append(reason)
                finished_now = _BATCH_FINISHED
            if action == "skip" and not batch_running:
                # 单目标 / 无目标可继续 → 收工并记录原因（绝不静默、绝不死循环）。
                if not finished_now:
                    with _BATCH_LOCK:
                        _BATCH_FINISHED = True
                    context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0],
                detail={
                    "batch": "wrong_detail_skip" if action == "skip" else "wrong_detail",
                    "member": member,
                    "identity": ident,
                    "reason": reason,
                },
            )

        # ★#39★ 详情页难度发现的交接结果：详情页上「声明的难度不存在」（absent）或
        #   「读不到任何难度档」（undetermined）→ 由本指挥官执行**明确、可理解**的收尾：
        #     · absent + 批量且有当前目标 → 跳过该目标、继续下一个（原因记录）；
        #     · absent + 单目标 / 无目标可继续 → 主动收工（原因记录）；
        #     · undetermined → 主动收工（绝不盲目开打）。
        #   判定是纯函数 plan_absent_difficulty_action（离线可单测）。
        #   ★#62 修订★：undetermined（一档都读不到）先【有界重试】再处置（批量且还有别的目标
        #      → 跳过并继续；否则收工）—— 覆盖「详情页还在加载」造成的瞬时误判
        #      （真机 chunk_62 的碧之女王：re-navigate 后第一帧只读到顶栏「活动时间」）。
        note = _take_detail_difficulty()
        if note is not None and note.outcome in ("absent", "undetermined"):
            with _BATCH_LOCK:
                active_now = _BATCH_ACTIVE
                running_now = _BATCH_CURRENT
                others_n = len([it for it in _BATCH_ITEMS if it is not running_now])
            if note.outcome == "undetermined":
                # ★#62★ 「一档都读不到」既可能是真没有，也可能只是【详情页还没加载完】——
                #   在【有界】窗口内重试（复用 _UNFIGHTABLE_DETAIL_SEC 时钟），超窗才处置：
                #   批量里还有别的目标 → 跳过该目标、继续清单；否则主动收工。绝不空转。
                member_u = getattr(running_now, "dungeon", None) or "?"
                elapsed = _note_unfightable_detail(member_u, task_id)
                action, reason = plan_undetermined_difficulty_action(
                    note.declared, elapsed,
                    batch_active=active_now, has_current=running_now is not None,
                    remaining_other=others_n,
                )
            else:
                action, reason = plan_absent_difficulty_action(
                    note.outcome, note.declared, note.available,
                    batch_active=active_now, has_current=running_now is not None,
                )
            if action == "retry":
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={
                        "batch": "difficulty_retry",
                        "outcome": note.outcome,
                        "declared": note.declared,
                        "elapsed": round(elapsed, 1),
                    },
                )
            _clear_unfightable_detail()
            if action == "skip":
                with _BATCH_LOCK:
                    _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running_now]
                    _BATCH_CURRENT = None
                    _BATCH_NEEDS_HOME = False
                    _BATCH_TARGET_START_TS = 0.0
                    _BATCH_SKIPPED.append(reason)
                print(f"[batch] {reason}（跳过 {getattr(running_now, 'dungeon', '?')}）")
                items = list(_BATCH_ITEMS)
                errors = list(_BATCH_ERRORS)
                if not items:  # 唯一目标被跳过 → 没有可继续的目标 → 收工并记录原因
                    action = "stop"
                    reason = reason + "（清单已无剩余目标 → 收工）"
            if action == "stop":
                if not finished:
                    with _BATCH_LOCK:
                        _BATCH_FINISHED = True
                    print(f"[batch] {reason}")
                    context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
                    return CustomRecognition.AnalyzeResult(
                        box=[0, 0, 0, 0],
                        detail={
                            "batch": "difficulty_stop",
                            "outcome": note.outcome,
                            "declared": note.declared,
                            "available": sorted(note.available),
                            "reason": reason,
                        },
                    )
                return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "difficulty_stop"})

        # ★#62★ 「能导航进详情页、却配不出战斗」的成员不得【无界】重试 ★
        #   判据与上限见 _own_detail_unfightable / _UNFIGHTABLE_DETAIL_SEC 上方的 #62 段。
        #   与 #39/#42/#44 同一分工：识别器/纯函数给结论，指挥官读写清单并决定跳过/收工。
        #   必须在【归位阶段之前】判：本条目早已归位完、正停在【自己的详情页】上空转。
        with _BATCH_LOCK:
            home_now = _BATCH_NEEDS_HOME
        unstuck = None
        if items_raw and not home_now and not _batch_busy(context, argv.image):
            unstuck = _own_detail_unfightable(context, argv, items_raw)
        if unstuck is not None:
            member, _ident = unstuck
            elapsed = _note_unfightable_detail(member, task_id)
            with _BATCH_LOCK:
                active_now = _BATCH_ACTIVE
                running_now = _BATCH_CURRENT
                others = [it for it in _BATCH_ITEMS if it is not running_now]
            action, reason = plan_unfightable_detail_action(
                member, elapsed,
                batch_active=active_now, remaining_other=len(others),
            )
            if action == "retry":
                return CustomRecognition.AnalyzeResult(
                    box=None,
                    detail={
                        "batch": "detail_unfightable_retry",
                        "member": member,
                        "elapsed": round(elapsed, 1),
                    },
                )
            if action == "skip":
                with _BATCH_LOCK:
                    _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running_now]
                    _BATCH_CURRENT = None
                    _BATCH_NEEDS_HOME = False
                    _BATCH_TARGET_START_TS = 0.0
                    _BATCH_ITEM_ENGAGED = False
                    _BATCH_SCROLL_CEILING = None
                    _BATCH_SKIPPED.append(reason)
                _clear_unfightable_detail()
                print(f"[batch] {reason}")
                items = list(_BATCH_ITEMS)
                if not items:     # 唯一目标被跳过 → 没有可继续的目标 → 收工并记录原因
                    action = "stop"
                    reason = reason + "（清单已无剩余目标 → 收工）"
            if action == "stop":
                if not finished:
                    with _BATCH_LOCK:
                        _BATCH_FINISHED = True
                    print(f"[batch] {reason}")
                    context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
                    return CustomRecognition.AnalyzeResult(
                        box=[0, 0, 0, 0],
                        detail={
                            "batch": "detail_unfightable_stop",
                            "member": member,
                            "elapsed": round(elapsed, 1),
                            "reason": reason,
                        },
                    )
                return CustomRecognition.AnalyzeResult(
                    box=None, detail={"batch": "detail_unfightable_stop"}
                )
        else:
            _clear_unfightable_detail()

        # 清单为空 → 向后兼容：不激活，交给原单目标逻辑。
        # 但仍要把「任务入口」对应的种类写进 _BATCH_MODE：
        # FarmEntry / RaidEntry 两个别名入口据此放行各自的 FarmDispatch / RaidDispatch。
        if not items:
            with _BATCH_LOCK:
                _BATCH_MODE = _entry_kind(argv)
            return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "inactive"})

        # 战局状态：本局已开打但还没看到结算 → 绝不切目标/收工。
        # ★#33★ 长战斗属正常等待：下面的等待上限由游戏自身上限派生（BATTLE_GAME_CAP_SEC），
        #   不是任意 300s；只有超过上限（≈16min）的异常才记因跳过。
        with _BATCH_LOCK:
            in_fight = _BATCH_IN_FIGHT
            fight_start = _BATCH_FIGHT_START_TS
        if in_fight and (time.monotonic() - fight_start) > _BATCH_FIGHT_TIMEOUT:
            # ★#33：只有超过【游戏自身上限 + 裕度】才视为真异常——绝不无限挂起。
            #   到此必须【记明原因】并跳过该目标（绝不静默），且绝不把设备留在战斗中：
            #   下面的收工路径受 _batch_busy / is_battle_hud 把守，收尾归位另有 live_battle 规则离场。
            with _BATCH_LOCK:
                stuck = _BATCH_CURRENT
                if stuck is not None:
                    reason = (
                        f"{stuck.dungeon}/{stuck.difficulty} 开打已超过 {_BATCH_FIGHT_TIMEOUT:.0f}s"
                        f"（游戏自身上限 ~{BATTLE_GAME_CAP_SEC:.0f}s + 裕度）仍未见结算 → 记为异常"
                        f"并跳过该目标（绝不无限挂起；收尾归位负责离开战斗，绝不把设备留在战斗中）"
                    )
                    _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not stuck]
                    _BATCH_CURRENT = None
                    _BATCH_NEEDS_HOME = False
                    _BATCH_ITEM_ENGAGED = False
                    _BATCH_BLOCK_DISPATCH = False
                    _BATCH_SCROLL_CEILING = None
                else:
                    reason = (
                        f"开打已超过 {_BATCH_FIGHT_TIMEOUT:.0f}s（游戏自身上限 "
                        f"~{BATTLE_GAME_CAP_SEC:.0f}s + 裕度）仍未见结算 → 记为异常"
                        f"（绝不无限挂起）"
                    )
                _BATCH_SKIPPED.append(reason)
                _BATCH_IN_FIGHT = False
                items = list(_BATCH_ITEMS)
            print(f"[batch] {reason}")
            in_fight = False
        if in_fight:
            return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "in_fight"})

        cur = next_item(items)

        # ★#45 声明的能力缺口（绝不空转、绝不假记账）★：被判为「从主城不可达 / 不可打」
        #   的目标（raid / farm，见 UNREACHABLE_FROM_MAIN_CITY）在【一确认中立页】后
        #   即由本块明确跳过 —— 宽限 grace_sec = 0，故不再是 45s / 120s 的“超时”。
        #   · 画面忙（加载/战斗/结算）时不计入（那是正常推进，不是空转）；
        #   · 未声明的种类不在此表 → nav_timeout = None → 行为完全不变；
        #   · 跳过原因【直接来自声明表】（unreachable_skip_reason），不是现场拼的超时文案。
        #   归位阶段（home_pending）不计入——判定从「确认中立页、真正开始导航」起算。
        with _BATCH_LOCK:
            running = _BATCH_CURRENT
            nav_started = _BATCH_TARGET_START_TS
            home_pending = _BATCH_NEEDS_HOME
        nav_timeout = (
            _BATCH_NAV_TIMEOUT_BY_KIND.get(running.kind)
            if running is not None and not home_pending
            else None
        )
        # ★#62★ special 条目也要有【兜底导航上限】：special 本不在 _BATCH_NAV_TIMEOUT_BY_KIND
        #   （那是 #45 的声明表）里，于是「导航之后、开打之前」本来没有任何上限 —— 本票给它
        #   一个有限兜底，覆盖「详情页连 `推荐编成` 标记都读不到」的形态（连身份校验都无从谈起）。
        #   已声明的种类（raid）仍用声明值，行为完全不变。
        if (
            nav_timeout is None
            and running is not None
            and not home_pending
            and getattr(running, "kind", "special") == "special"
        ):
            nav_timeout = _SPECIAL_NAV_DEADLINE_SEC
        # ★#maze-entry★ farm（摇曳的迷宫）同样要有【兜底导航上限】：farm 被 #54 移出
        #   _BATCH_NAV_TIMEOUT_BY_KIND（那是 #45 的声明表）后，「导航之后、开打之前」就
        #   没有任何上限了 —— 若 FarmMazeEntry 的**有界重试用尽**仍没进迷宫页，指挥官会
        #   空转到任务超时（第 3 条现场根因）。这里给它一个有限兜底：超时即走下面同一套
        #   「明确跳过 + 打印原因」（farm 未被声明 -> 用通用文案），绝不静默空转、绝不
        #   假记账。已声明的种类（raid）/ special 的分支都在上面，行为完全不变。
        if (
            nav_timeout is None
            and running is not None
            and not home_pending
            and getattr(running, "kind", "special") == "farm"
        ):
            nav_timeout = _FARM_NAV_DEADLINE_SEC
        if (
            running is not None
            and nav_timeout is not None
            and nav_started
            and (time.monotonic() - nav_started) > nav_timeout
            and not _batch_busy(context, argv.image)
        ):
            # #45：原因取自声明表（配置与实现同一条声明）；未声明 → 退回通用文案（旧行为）。
            reason = unreachable_skip_reason(running)
            if reason is None:
                reason = (
                    f"{running.dungeon}/{running.difficulty} 在 {nav_timeout:.0f}s 内未走到自身"
                    f"导航/开打 → 跳过该目标（绝不空转）"
                )
            with _BATCH_LOCK:
                _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running]
                _BATCH_TARGET_START_TS = 0.0
                _BATCH_CURRENT = None
                _BATCH_NEEDS_HOME = False
                _BATCH_ITEM_ENGAGED = False
                _BATCH_BLOCK_DISPATCH = False
                _BATCH_SKIPPED.append(reason)
            print(f"[batch] {reason}")
            items = list(_BATCH_ITEMS)
            cur = next_item(items)

        # ★#50★ 滚动预算用尽 → 本条目有界停止（明确跳过 + 记录原因）。
        #
        #   判据链（全部成立才跳过）：
        #     · 当前条目种类 = special，且已由指挥官为它重置过滚动预算（ceiling 非 None）；
        #     · 不在归位阶段、尚未「走过自身导航/开打」（_BATCH_ITEM_ENGAGED 为假）；
        #     · 画面不忙（加载/战斗/结算 → 绝不打断）；
        #     · 命中数已达本条目上限（= 框架已开始跳过滚动节点 → 列表被冻住）；
        #     · 且【这一帧目标行确实不在屏内】—— 否则 SpecialEnterBoss（排在滚动节点之前）
        #       会接手选行，绝不能抢先跳过（那会丢掉一个本来可达的目标）。
        #   通过则记录原因并跳过该目标（与 farm/raid 导航超时同一套「明确跳过」语义）。
        with _BATCH_LOCK:
            running = _BATCH_CURRENT
            ceiling = _BATCH_SCROLL_CEILING
            engaged = _BATCH_ITEM_ENGAGED
        if (
            running is not None
            and getattr(running, "kind", "special") == "special"
            and ceiling is not None
            and not engaged
            and not home_pending
            and not _batch_busy(context, argv.image)
        ):
            try:
                hits = int(context.get_hit_count(SCROLL_NODE))
            except Exception:  # noqa: BLE001 —— 读不到计数就不做此判定，绝不误跳
                hits = -1
            if hits >= 0 and scroll_budget_exhausted(hits, ceiling):
                row_visible = False
                try:
                    detail = context.run_recognition("SpecialEnterBoss", argv.image)
                    row_visible = detail is not None and bool(getattr(detail, "hit", False))
                except Exception as exc:  # noqa: BLE001 —— 复核失败按「行可见」保守处理（不跳）
                    print(f"[batch] 滚动预算用尽复核目标行失败（保守不跳过）：{exc}")
                    row_visible = True
                if not row_visible:
                    reason = (
                        f"{running.dungeon}/{running.difficulty} 在 {_PER_ITEM_SCROLL_BUDGET} 次"
                        f"滚动预算内仍未把目标行滚进列表 → 跳过该目标并记录原因"
                        f"（预算用尽；绝不空转/假记账）"
                    )
                    with _BATCH_LOCK:
                        _BATCH_ITEMS[:] = [it for it in _BATCH_ITEMS if it is not running]
                        _BATCH_TARGET_START_TS = 0.0
                        _BATCH_CURRENT = None
                        _BATCH_NEEDS_HOME = False
                        _BATCH_ITEM_ENGAGED = False
                        _BATCH_BLOCK_DISPATCH = False
                        _BATCH_SCROLL_CEILING = None
                        _BATCH_SKIPPED.append(reason)
                    print(f"[batch] {reason}")
                    items = list(_BATCH_ITEMS)
                    cur = next_item(items)

        with _BATCH_LOCK:
            current = _BATCH_CURRENT
            needs_home = _BATCH_NEEDS_HOME
            finished = _BATCH_FINISHED
            # 当前目标的种类 → 决定 FarmDispatch / RaidDispatch 谁放行（每轮都刷新）。
            if cur is not None:
                _BATCH_MODE = cur.kind
            elif current is not None:
                _BATCH_MODE = current.kind
            else:
                _BATCH_MODE = _entry_kind(argv)

        # 全部目标打够 → 归位主城并收工。
        if cur is None:
            if finished:
                return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "done"})
            if _batch_busy(context, argv.image) or not _batch_settled():
                return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "wait_finish"})
            # ★#33★ 绝不在【战斗画面】上收工：那一帧的战斗 HUD（时间 mm:ss + 分数 N）就是
            #   「本局还没打完」的证据（真机 16384 实证：收工判定赶在战斗帧上 → 设备被留在
            #   战斗中，运维只能人工恢复）。等它打完（SpecialBattleWait 在等），下一轮再判。
            if screen_items and is_battle_hud(screen_items):
                print("[batch] 收工前画面仍是战斗 HUD → 等本局打完再收工（#33：绝不把设备留在战斗中）")
                return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "wait_battle"})
            with _BATCH_LOCK:
                _BATCH_FINISHED = True
            print("[batch] 清单全部完成 → 回主城并收工")
            context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"batch": "done"})

        # 切换到下一个目标：先改识别参数，再（在画面不忙且已结算后）点主城归位。
        if cur is not current:
            rem = remaining(cur)
            print(f"[batch] 切换目标：{cur.dungeon} / {cur.difficulty}（剩余 {rem} 次）")
            try:
                context.override_pipeline(_batch_override(cur))
            except Exception as exc:  # noqa: BLE001
                print(f"[batch] override_pipeline 失败：{exc}")
            # ★#50★ 每个条目开始导航前，把滚动节点的命中预算按条目恢复一份
            #   （框架计数按任务累计、不会自减；这里抬上限即「每条目重置」）。
            _ensure_scroll_budget(context, task_id)
            now = time.monotonic()
            with _BATCH_LOCK:
                _BATCH_CURRENT = cur
                _BATCH_NEEDS_HOME = True
                _BATCH_TARGET_START_TS = now
                _BATCH_HOME_START_TS = now
                # ★#44★：新条目尚未「走过自身导航」-> 记账前提为假；切种类需先确认中立页，
                #   故先封锁种类分派（下面的 needs_home 分支按画面解除：中立 / 不可读时放行）。
                _BATCH_ITEM_ENGAGED = False
                _BATCH_BLOCK_DISPATCH = True
                needs_home = True

        # ★#44★ 归位阶段：先确认已回到中立页（主城）再开始下一条。
        #   画面【可读且明确不是主城】（陈旧详情 / 结算 / 列表 / 幻想页）-> 封锁种类分派并
        #   持续归位，绝不把「上一场的残留界面」当成下一条的进度（假完成）；
        #   画面不可读（离线 stub / OCR 不可用）-> 回退旧行为（点一次主城即放行）。
        if needs_home:
            screen = classify_screen(screen_items)
            if screen == "other":
                with _BATCH_LOCK:
                    _BATCH_BLOCK_DISPATCH = True
                    home_started = _BATCH_HOME_START_TS
                if home_started and (time.monotonic() - home_started) > _BATCH_HOME_TIMEOUT:
                    if not finished:
                        with _BATCH_LOCK:
                            _BATCH_FINISHED = True
                        reason = (
                            f"归位主城超过 {_BATCH_HOME_TIMEOUT:.0f}s 仍不在中立页"
                            f"（当前画面可读且不是主城）→ 主动收工并记录原因（绝不无限点主城）"
                        )
                        print(f"[batch] {reason}")
                        context.override_next("SpecialBatchPlan", ["SpecialBatchStop"])
                        return CustomRecognition.AnalyzeResult(
                            box=[0, 0, 0, 0],
                            detail={"batch": "home_timeout_stop", "reason": reason},
                        )
                    return CustomRecognition.AnalyzeResult(
                        box=None, detail={"batch": "home_timeout_stop"}
                    )
            else:
                with _BATCH_LOCK:
                    _BATCH_BLOCK_DISPATCH = False

            if _batch_busy(context, argv.image) or not _batch_settled():
                return CustomRecognition.AnalyzeResult(box=None, detail={"batch": "wait_busy"})

            if screen == "other":
                # 仍在中立页之外：点底部「主城」归位（needs_home 保持 True，下一轮再判），
                # 期间种类分派保持封锁（见 BatchModeRecognition 的 #44 分支）。
                context.override_next("SpecialBatchPlan", ["SpecialEntry"])
                print(
                    f"[batch] 尚未回到中立页（主城），先归位再开始刷 "
                    f"{cur.dungeon} / {cur.difficulty}（#44）"
                )
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"batch": "home_retry"})

            with _BATCH_LOCK:
                _BATCH_NEEDS_HOME = False
                _BATCH_BLOCK_DISPATCH = False
                # 归位结束才算「开始导航」：导航超时从此刻起算（不把归位耗时算进去）。
                _BATCH_TARGET_START_TS = time.monotonic()
            context.override_next("SpecialBatchPlan", ["SpecialEntry"])
            print(f"[batch] 已确认中立页（主城），开始刷 {cur.dungeon} / {cur.difficulty}")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"batch": "home"})

        # ★#42 仪器化（逐节点框/坐标日志）★：目标正在导航时，把「目标行此刻在这一帧的框」
        #   打进日志 —— 这是「选行错位」的根因证据（与随后详情页横幅标题一起看，就能分辨
        #   「列表还在滑动 / 陈旧坐标 / ROI 过宽」，而不是猜）。仅 special 路径、每轮一行。
        if getattr(cur, "kind", "special") == "special":
            log_row_selection(items_raw, cur.dungeon)

        return CustomRecognition.AnalyzeResult(
            box=None,
            detail={"batch": "running", "target": f"{cur.dungeon}/{cur.difficulty}", "remaining": remaining(cur)},
        )


def _batch_click(context, x: int, y: int, what: str) -> bool:
    """按 720 空间坐标 (x,y) 点击。

    ★为什么走 run_action 而不是 controller.post_click★
      部分 MaaFramework 原生库（MFAAvalonia 随包）未导出 ``MaaControllerPostClickV2``，
      Python binding 的 ``post_click`` 会直接 ACCESS_VIOLATION（真机 2026-09-28
      log-20260928 里 18 连崩的堆栈：controller.py:86）。
      改用框架原生 Click 动作（common.json 的 PubClick，target=true 点框中心）→
      版本无关，且不经过 ctypes 直连。phantom 的 ``_click_box`` 是同一做法。
    """
    try:
        context.run_action("PubClick", box=(int(x) - 1, int(y) - 1, 2, 2))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[batch] 点击{what}失败 ({x},{y})：{exc}")
        return False


def _batch_box_center(box) -> tuple[int, int]:
    try:
        return int(box.x + box.w / 2), int(box.y + box.h / 2)
    except Exception:  # noqa: BLE001
        return int(box[0] + box[2] / 2), int(box[1] + box[3] / 2)


class SpecialBatchFightAction(CustomAction):
    """「开打」动作：原地点击战斗按钮（保持原行为）。

    批量模式下仅标记「本局已开打、还没看到结算」——真正的 +1 在
    SpecialBatchFinishAction（结算推进节点）里做，避免战斗没打完就误判完成。

    ★#42：带 ``row_click: true`` 时本动作退化为【选行点击】（挂在 ``SpecialEnterBoss`` 上）★
    ----------------------------------------------------------------
    列表页选行是「识别框 → 点击」两步，而 MAA 的点击发生在**识别那一帧之后**：多次滑动后的
    列表若仍在惯性滑动，按识别框点下去就可能落到**相邻的行**上（真机 r9：目标「伊劳德雷斯讨伐」
    却打开了「碧之女王」的详情页）。故 row_click 分支**点击前立刻重抓一帧复核**：
      · 目标行还在这帧的列表体内 → 用【新框】点击（把两次框的位移打进日志 = 竞态证据）；
      · 目标行不在 → **不点**（宁可让 pipeline 重新滑动/重试，也绝不按陈旧坐标点别人的行）。
    ★为什么复用本动作名★：#20 把 runner 侧注册表锁死在 ``live_harness.CUSTOM_*``（本泳道
    不可改），新增自定义名会让套件变红；故用显式参数（``row_click``）区分语义，并在
    ``tools/contract_hooks/hooks_42.py`` 里守卫「SpecialEnterBoss 必须走这条分支」。
    """

    def _row_click(self, context, argv, param) -> bool:
        """#42 选行点击：按【立刻重抓的一帧】上目标行的位置点击（复核不过就不点）。"""
        ocr_entry = param.get("ocr_entry") or "OcrTask"
        rec_box = list(getattr(argv, "box", None) or [])
        member = param.get("member") or _member_from_row_node(context, "高级$")
        if not member:
            print(f"[rowclick] 读不到选行目标（SpecialEnterBoss.expected）→ 按识别框点击 {rec_box}")
            return _click_box(context, rec_box)
        frame = _grab_frame(context)
        if frame is None:
            print(f"[rowclick] 重抓帧失败 → 按识别框点击 {rec_box}（保守退回旧行为）")
            return _click_box(context, rec_box)
        fresh = _ocr_scored(context, frame, ocr_entry)
        picked = verify_row_on_frame(fresh, re.escape(member), ref_box=rec_box)
        if picked is None:
            print(
                f"[rowclick] 目标 {member!r} 在重抓帧的列表体内【不复现】→ 放弃本次点击"
                f"（识别框 {rec_box}；列表仍在动 / 目标已移出屏 —— 绝不按陈旧坐标点别人的行）"
            )
            return False
        fresh_box, dy = picked
        verdict = "竞态：识别框已过期" if abs(dy) > ROW_KEYLINE_BAND else "稳定"
        print(
            f"[rowclick] node=SpecialEnterBoss 目标={member!r} 识别框={rec_box} → "
            f"重抓框={fresh_box} dy={dy:.0f}（{verdict}）；点击中心 {_center(fresh_box)}"
        )
        return _click_box(context, fresh_box)

    def run(self, context, argv):
        global _BATCH_IN_FIGHT, _BATCH_FIGHT_START_TS, _BATCH_ITEM_ENGAGED
        param = read_action_param(argv)
        if flag(param.get("row_click", False)):
            # ????????????? True ?? ?????**????**?? pipeline ??/
            # ???????????? FAILED?
            self._row_click(context, argv, param)
            return True
        box = getattr(argv, "box", None)
        if box is None:
            print("[batch] 开打动作没有识别框，无法点击")
            return False
        x, y = _batch_box_center(box)
        if not _batch_click(context, x, y, "开打"):
            return False

        with _BATCH_LOCK:
            active = _BATCH_ACTIVE
            cur = _BATCH_CURRENT
        if active and cur is not None:
            now = time.monotonic()
            with _BATCH_LOCK:
                _BATCH_IN_FIGHT = True
                _BATCH_FIGHT_START_TS = now
                _BATCH_LAST_FIGHT_TS = now
                # ★#44★：真的开打了 = 本条目已走过自身种类的导航（记账前提，铁律 1）。
                _BATCH_ITEM_ENGAGED = True
            print(f"[batch] 开打 {cur.dungeon}/{cur.difficulty}（等待结算计数）")
        return True


class SpecialBatchFinishAction(CustomAction):
    """结算推进动作：点「继续 / OK / QUESTRESULT / 升级继续」，并在本局结算时记一场账本。

    可用参数（custom_action_param）：
        target : 可选固定点击点 [x,y]；不给则点识别框中心。
        record : "in_fight"（默认）只在「开打→结算」状态转变时记一笔；
                 "always" 每次执行都记一笔（farm/raid 的循环节点用：点一次=又打完一局）。

    ★#22★ 单目标模式（清单为空）额外承担**收工闸**：目标已打满配置次数
    （``SpecialFightTargetRow`` 的有限 ``max_hit`` 被命中计数用尽）时，把**当前结算
    节点**的 next 覆盖成 ``SpecialBatchStop`` —— 结算帧明确收工，不再重进同一目标。
    判定与复用理由见 ``_single_target_finished`` / ``_single_target_stop`` 上方的注释。
    """

    def run(self, context, argv):
        global _BATCH_IN_FIGHT, _BATCH_LAST_FIGHT_TS, _BATCH_TARGET_START_TS
        global _BATCH_LOSSES
        param = read_action_param(argv)
        target = param.get("target")
        record = param.get("record") or "in_fight"
        # ★#44★ record="always"（farm/raid 的「再次挑战」循环）必须建立在【本条目自身导航】
        #   之上：尚未走过自身导航时，命中的多半是【上一场战斗结算页】残留的「再次挑战」——
        #   既不该点（会重开上一场）、更不该记账（假完成）。宁可不动，交给指挥官归位/跳过。
        #   单目标模式（未激活）不受影响；record="in_fight"（special 结算）也不受影响。
        with _BATCH_LOCK:
            _active0 = _BATCH_ACTIVE
            _cur0 = _BATCH_CURRENT
            _engaged0 = _BATCH_ITEM_ENGAGED
        if _active0 and _cur0 is not None and record == "always" and not _engaged0:
            print(
                f"[batch] 忽略跨种类陈旧结算页的『再次挑战』：{_cur0.dungeon}/{_cur0.difficulty} "
                f"尚未经过自身导航（#44：不点击、不记账）"
            )
            return True
        if isinstance(target, (list, tuple)) and len(target) >= 2:
            x, y = int(target[0]), int(target[1])
        else:
            box = getattr(argv, "box", None)
            if box is None:
                print("[batch] 结算动作没有识别框，无法点击")
                return False
            x, y = _batch_box_center(box)
        if not _batch_click(context, x, y, "结算"):
            return False

        with _BATCH_LOCK:
            active = _BATCH_ACTIVE
            cur = _BATCH_CURRENT
            in_fight = _BATCH_IN_FIGHT
        if active and cur is not None and (record == "always" or in_fight):
            prefix = item_prefix(cur)
            seq = count_done(prefix) + 1
            ledger.mark_done(item_key(prefix, seq))
            with _BATCH_LOCK:
                _BATCH_IN_FIGHT = False
                _BATCH_LAST_FIGHT_TS = time.monotonic()
                # 有实质进展 → 复位 farm 导航计时（导航快速失败不会误伤正在推进的目标）。
                _BATCH_TARGET_START_TS = _BATCH_LAST_FIGHT_TS
                # ★#38★ 真的打完了（结算）= 胜利 → 打断「连续失败」计数（#38：连续 2 次才收工）。
                _BATCH_LOSSES = 0
            print(f"[batch] 结算完成 {cur.dungeon}/{cur.difficulty} 第 {seq}/{cur.times} 次")

        # ★#22★ 单目标打满配置次数 → 结算帧明确收工（复用 SpecialBatchStop）。
        #   批量模式由指挥官负责收工，这里只在单目标模式下动作（见 _single_target_stop）。
        _single_target_stop(context, argv)
        return True
