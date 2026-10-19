import json
import threading

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition

from maa_util import ocr_all as _ocr_all, read_param as _read_param
from side_impl import (
    ListAllDoneRecognition,
    NextStageRecognition,
    NoListBadgeRecognition,
    PageDoneRepeatRecognition,
    SpecialBatchPlanRecognition,
    SpecialTargetFightRecognition,
    StallRecoverRecognition,
)
from phantom_impl import (
    PhantomDoneRecognition,
    PhantomGiveUpRecognition,
    PhantomStateRecognition,
)
from abyss_impl import (
    AbyssGiveUpRecognition,
    AbyssRecoverGateRecognition,
    AbyssSceneRecognition,
    AbyssStateRecognition,
)
from wuchong_impl import (
    WuchongContinueGuardRecognition,
    WuchongGiveUpRecognition,
    WuchongNetGuardRecognition,
    WuchongRenavRecognition,
    WuchongStateRecognition,
    WuchongSwitchStateRecognition,
)
from team_impl import (
    TeamStateRecognition,
)
from lords_impl import (
    LordsProgressRecognition,
)
from auto_switch_impl import (
    AutoContDialogRecognition,
    AutoSwitchStateRecognition,
)
from stage_rows import (
    DEFAULT_FIGHT_TEXT,
    DEFAULT_ROW_DY,
    DEFAULT_STAGE_REGEX,
    is_all_done,
    normalize_key,
    parse_stage_rows,
    pick_next,
)

# 把 side_impl 里的「外传账本 / 本页全清 / 收工防空转 / 卡死自恢复」识别器注册到 AgentServer。
# 实现放在 side_impl 是为了让离线/真机测试也能在不启动 AgentServer 的情况下
# 直接把这些类注册到进程内 Resource 上（见 tools/run_side_live.py、clear_all.py）。
NextStageRecognition = AgentServer.custom_recognition("next_stage")(NextStageRecognition)
NoListBadgeRecognition = AgentServer.custom_recognition("no_list_badge")(NoListBadgeRecognition)
ListAllDoneRecognition = AgentServer.custom_recognition("list_all_done")(ListAllDoneRecognition)
PageDoneRepeatRecognition = AgentServer.custom_recognition("page_done_repeat")(PageDoneRepeatRecognition)
StallRecoverRecognition = AgentServer.custom_recognition("stall_recover")(StallRecoverRecognition)
SpecialBatchPlanRecognition = AgentServer.custom_recognition("special_batch_plan")(SpecialBatchPlanRecognition)
# P0：详情页「战斗」按钮识别（返回战斗 OCR 框，绝不点推荐编成）。
SpecialTargetFightRecognition = AgentServer.custom_recognition("special_target_fight")(SpecialTargetFightRecognition)

# 幻想连战「自动刷幻想」状态机识别：
#   phantom_state  → 画面分类（phantom_main / phantom_solo_team / phantom_coop_room / ...）
#   phantom_done   → 出口：15 关完成且回到关卡选择页
#   phantom_giveup → 出口：未知画面过多 / 无新关卡超时 / 总时长超限
PhantomStateRecognition = AgentServer.custom_recognition("phantom_state")(PhantomStateRecognition)
PhantomDoneRecognition = AgentServer.custom_recognition("phantom_done")(PhantomDoneRecognition)
PhantomGiveUpRecognition = AgentServer.custom_recognition("phantom_giveup")(PhantomGiveUpRecognition)

# 深渊「自动化」状态机识别（#55 Phase 2 = EX / Phase 3 = 普通深渊，同一实现按场景 id 参数化）：
#   abyss_state  → 画面分类（abyss_hub / abyss_main / abyss_solo_team / abyss_settle / ...）
#   abyss_giveup → 兜底出口：未知画面过多 / 无新关卡超时 / 阶梯记账异常
#   abyss_scene  → 场景声明（入口节点 set=true）/ 门控（普通深渊任务不误点 EX 横幅）
# ★全单人、无共斗★；★没有「刷几套」★（30 层阶梯一直往下刷）；★EX 与普通深渊只差导航★。
AbyssStateRecognition = AgentServer.custom_recognition("abyss_state")(AbyssStateRecognition)
AbyssGiveUpRecognition = AgentServer.custom_recognition("abyss_giveup")(AbyssGiveUpRecognition)
AbyssSceneRecognition = AgentServer.custom_recognition("abyss_scene")(AbyssSceneRecognition)
# ★#21 / ADR 0005 第 4 条★ 迷路后归位闸门（旗标门控叶）：
#   abyss_recover_gate → 只有 abyss_giveup 刚置了 recover_pending、且当前帧仍 unknown 时命中，
#   命中后由紧邻的 AbyssRecover 节点执行 abyss_recover（点主城/返回）。正常帧恒不命中。
AbyssRecoverGateRecognition = AgentServer.custom_recognition("abyss_recover_gate")(
    AbyssRecoverGateRecognition
)

# 五重决战「五重决战」状态机识别（#56 Phase 4）：
#   wuchong_state        → 画面分类（wuchong_lord_list / wuchong_detail / wuchong_mode /
#                          wuchong_room / wuchong_recruit_dialog / wuchong_team /
#                          wuchong_settle / wuchong_battle / ...）
#   wuchong_switch_state → 开关状态（编队页「自动」/「自动续战」/ 暂停屏「自动」）
#   wuchong_giveup       → 兜底出口：未知画面过多 / 无进展超时 / 总时长超限
#   wuchong_net          → 掉线有界收口（连续掉线超限）
#   wuchong_renav        → 重新导航有界收口（房间解散后重导失败超限）
#   wuchong_continue_guard → GAMEOVER 续关上限闸（#72）：已续关次数达上限即带原因收工
# ★只有五重决战允许「手动」，其余战斗一律「自动」★（跨模式规则，见 wuchong_impl）。
WuchongStateRecognition = AgentServer.custom_recognition("wuchong_state")(WuchongStateRecognition)
WuchongSwitchStateRecognition = AgentServer.custom_recognition("wuchong_switch_state")(WuchongSwitchStateRecognition)
WuchongGiveUpRecognition = AgentServer.custom_recognition("wuchong_giveup")(WuchongGiveUpRecognition)
WuchongNetGuardRecognition = AgentServer.custom_recognition("wuchong_net")(WuchongNetGuardRecognition)
WuchongRenavRecognition = AgentServer.custom_recognition("wuchong_renav")(WuchongRenavRecognition)
WuchongContinueGuardRecognition = AgentServer.custom_recognition("wuchong_continue_guard")(WuchongContinueGuardRecognition)

# ★自动的切换移到战斗外（#56 二批）★：场景无关的「自动」按钮识别 ——
#   auto_switch_state  → 定位（模板/OCR）+ 读开/关（可按期望态命中，供各模式编队页 gate）；
#   auto_cont_dialog   → 「自动续战功能」确认框（ruling ③：拒开，出现即点『取消』）。
AutoSwitchStateRecognition = AgentServer.custom_recognition("auto_switch_state")(AutoSwitchStateRecognition)
AutoContDialogRecognition = AgentServer.custom_recognition("auto_cont_dialog")(AutoContDialogRecognition)
TeamStateRecognition = AgentServer.custom_recognition("team_state")(TeamStateRecognition)

# 领主战「全难度解禁」（#100）：lords_progress 一个名字两个 mode ——
#   mode=read → 读列表页每一行的 `通关数 N/M`（detail 带结构化行列表 name/n/m/box）；
#   mode=pick → 选出「下一处该点的框」（目标行 / 该档【战斗】/ 编队页【挑战】）。
# ★判定真源是 scene/lords_unlock.py★（本模块只做 OCR 胶水 + 点哪一下，不打战斗）。
LordsProgressRecognition = AgentServer.custom_recognition("lords_progress")(LordsProgressRecognition)


# ===========================================================================
# 「已打过关卡」记录（主线）
#
# 用途：在关卡列表里挑「还没打过的那一行」，避免反复进出同一关（死循环）。
# 记录保存在 agent 进程内存中；task_id 变化（重新开始一次任务）时自动清空。
#
# 注：外传/特殊副本用的是落盘版通用账本 agent/progress.py（见 side_impl.next_stage）。
# ===========================================================================
_LOCK = threading.Lock()
_ATTEMPTED: set[str] = set()
_LAST_TASK_ID: int | None = None


def _sync_task(task_id: int | None) -> None:
    """换了一轮任务就清空记录，让新任务可以重新尝试之前失败的关卡。"""
    global _LAST_TASK_ID
    with _LOCK:
        if task_id is not None and _LAST_TASK_ID is not None and task_id != _LAST_TASK_ID:
            _ATTEMPTED.clear()
            print("[stage] task 变化，清空已打关卡记录")
        if task_id is not None:
            _LAST_TASK_ID = task_id


def _analyze_rows(context: Context, argv: CustomRecognition.AnalyzeArg):
    param = _read_param(argv)
    stage_regex = param.get("stage_regex") or DEFAULT_STAGE_REGEX
    fight_text = param.get("fight_text") or DEFAULT_FIGHT_TEXT
    row_dy = int(param.get("row_dy") or DEFAULT_ROW_DY)
    ocr_entry = param.get("ocr_entry") or "OcrTask"

    _sync_task(getattr(argv.task_detail, "task_id", None))

    items = _ocr_all(context, argv.image, ocr_entry)
    return parse_stage_rows(items, stage_regex, fight_text, row_dy)


@AgentServer.custom_recognition("stage_next")
class StageNextRecognition(CustomRecognition):
    """挑选「第一个还没打过的关卡」，返回它那一行「战斗」按钮的框。

    识别成功的同时会把这关记入「已打过」集合，所以下一轮自动跳过，
    不会再出现「反复进出同一个最上面的关卡」。

    可用参数（custom_recognition_param）：
        stage_regex : 关卡编号正则，默认 第N章…N-N
        fight_text  : 战斗按钮文本，默认「战斗」
        row_dy      : 战斗按钮相对关卡编号的最大下移像素，默认 150
        ocr_entry   : 用于 OCR 的节点名，默认 OcrTask
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        rows = _analyze_rows(context, argv)
        if not rows:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "未找到关卡行（可能不在关卡列表页）"},
            )

        with _LOCK:
            attempted = set(_ATTEMPTED)

        picked = pick_next(rows, attempted)
        if picked is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "可见关卡都已打过", "rows": [row[0] for row in rows]},
            )

        text, fight_box = picked
        with _LOCK:
            _ATTEMPTED.add(normalize_key(text))
            total = len(_ATTEMPTED)
        print(f"[stage_next] 选中 {text} -> 点战斗 {fight_box}（累计已记录 {total} 关）")
        return CustomRecognition.AnalyzeResult(
            box=fight_box,
            detail={"stage": text, "attempted": total},
        )


@AgentServer.custom_recognition("stage_all_done")
class StageAllDoneRecognition(CustomRecognition):
    """可见的关卡行全部已打过时命中 —— 让上层去滚动列表 / 翻页找新关卡。

    只要还有一行没打过（且有战斗按钮），就不命中。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        rows = _analyze_rows(context, argv)
        if not rows:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "未找到关卡行（可能不在关卡列表页）"},
            )

        with _LOCK:
            attempted = set(_ATTEMPTED)

        if not is_all_done(rows, attempted):
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "还有未打过的关卡，交给 stage_next 处理"},
            )

        print(f"[stage_all_done] 可见关卡全部打过：{[row[0] for row in rows]}")
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 0, 0],
            detail={"all_done": [row[0] for row in rows]},
        )


# ===========================================================================
# 「卡死检测」stall_recover
# 实现已移到 side_impl.StallRecoverRecognition（不依赖 AgentServer），
# 顶部 import + 注册；此处不再重复定义。
# ===========================================================================


# ===========================================================================
# 下面是模板自带的自定义识别示例
# ===========================================================================
@AgentServer.custom_recognition("find_smallest_number")
class SmallestNumberRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:

        param = json.loads(argv.custom_recognition_param or "{}") or {}
        rois = param.get("candidate_rois")
        if not isinstance(rois, list) or not rois:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"error": "candidate_rois 不能为空"},
            )

        res = []

        for roi in rois:
            # 找到 pipeline 中名为 "RecognizeNumber" 的节点，并执行它的识别逻辑
            reco_detail = context.run_recognition(
                "RecognizeNumber",
                argv.image,  # 使用当前获取到的图片
                pipeline_override={  # 临时覆盖节点参数
                    "RecognizeNumber": {  # 要覆盖的节点的名称
                        "roi": roi,  # 覆盖识别区域
                        "only_rec": True,  # 不进行文本检测，直接进行识别
                    }
                },
            )

            if reco_detail is None or not reco_detail.hit:
                print(f"无法读取到内容 {roi}")
                res.append(None)
                continue

            text = str(reco_detail.best_result.text)
            try:
                number = float(text)
            except ValueError:
                print(f"{text} 不是数字!")
                res.append(None)
                continue

            res.append(number)

        if not res or None in res:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"error": "存在无法读取到内容"},
            )

        min_index = res.index(min(res))
        return CustomRecognition.AnalyzeResult(
            box=rois[min_index],
            detail={"smallest_number": res[min_index]},
        )
