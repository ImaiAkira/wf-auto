import json
import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from side_impl import (
    BatchModeRecognition,
    MarkDoneAction,
    SpecialBatchFightAction,
    SpecialBatchFinishAction,
)
from phantom_impl import (
    MAIN_CITY_ANCHORS,
    PhantomActAction,
    PhantomRestartAction,
    _click_box,
    _grab,
    _ocr,
    _pick,
)
from team_impl import (
    TeamSwitchAction,
    TeamSwitchBattleAction,
)
from abyss_impl import (
    AbyssActAction,
    AbyssBlockedAction,
    AbyssRecoverAction,
)
from wuchong_impl import (
    WuchongActAction,
    WuchongBattleAction,
    WuchongSwitchAction,
)
from auto_switch_impl import (
    AutoSwitchSetAction,
)
from lords_impl import (
    LordsUnlockAction,
)

# 账本记账动作：实现放在 side_impl（不依赖 AgentServer），这里注册。
MarkDoneAction = AgentServer.custom_action("mark_done")(MarkDoneAction)
# 批量副本：开打动作（点战斗 + 标记本局开始）与结算动作（点继续 + 记一场账本）。
SpecialBatchFightAction = AgentServer.custom_action("special_batch_fight")(SpecialBatchFightAction)
SpecialBatchFinishAction = AgentServer.custom_action("special_batch_finish")(SpecialBatchFinishAction)
# 种类分派开关（FarmDispatch / RaidDispatch 用）：实现同样在 side_impl。
# ★注册在 my_action.py 而不是 my_reco.py★：my_reco.py 归外传/幻想车道所有，避免冲突。
BatchModeRecognition = AgentServer.custom_recognition("batch_mode")(BatchModeRecognition)
# 幻想连战：OCR 按钮点击 + 动作后校验（phantom_act）；设备无关的重开（phantom_restart）。
PhantomActAction = AgentServer.custom_action("phantom_act")(PhantomActAction)
PhantomRestartAction = AgentServer.custom_action("phantom_restart")(PhantomRestartAction)
# 深渊EX：OCR 按钮点击 + 动作后校验（abyss_act，含数据驱动的二级页签搜索 step=tab）。
# 重开/卡死复用设备无关的 restart_game（已在本文件注册），不另造一套。
AbyssActAction = AgentServer.custom_action("abyss_act")(AbyssActAction)
# ★#21 / ADR 0005 第 4 条★ 迷路后归位：只在 abyss_recover_gate 命中（迷路 + 有预算 + 仍 unknown）
#   时被调用；点底导「主城」或左槽「返回」，点完回 AbyssEntry 走既有导航链重进。
AbyssRecoverAction = AgentServer.custom_action("abyss_recover")(AbyssRecoverAction)
# ★#27★ 「有正在挑战中的关卡」弹窗（盖住底导，归位点空的那个）：点「取消」离开后回
#   AbyssEntry 重新导航；连续 MAX_BLOCKED 次取消仍回不到已知页才请求收工。
AbyssBlockedAction = AgentServer.custom_action("abyss_blocked")(AbyssBlockedAction)

# 五重决战（#56 Phase 4）：OCR/模板按钮点击（wuchong_act）、★手操战斗★（wuchong_battle）、
# 开关（wuchong_switch：自动 / 自动续战 / 暂停屏自动，含跨模式「自动」规则）。
WuchongActAction = AgentServer.custom_action("wuchong_act")(WuchongActAction)
WuchongBattleAction = AgentServer.custom_action("wuchong_battle")(WuchongBattleAction)
WuchongSwitchAction = AgentServer.custom_action("wuchong_switch")(WuchongSwitchAction)

# ★自动的切换移到战斗外（#56 二批）★：场景无关的「自动」按钮开关动作 ——
#   定位（模板/OCR）→ 读状态 → 点识别框中心；非五重场景一律夹回「开」（跨模式硬规则）。
#   覆盖各模式编队页（special / abyss 的 *TeamAutoSet 节点用它）。
AutoSwitchSetAction = AgentServer.custom_action("auto_switch")(AutoSwitchSetAction)
TeamSwitchAction = AgentServer.custom_action("team_switch")(TeamSwitchAction)
TeamSwitchBattleAction = AgentServer.custom_action("team_switch_battle")(TeamSwitchBattleAction)

# 领主战「全难度解禁」（#100）：把 `lords_progress mode=pick` 选出的那一处点下去（一次只点一下）。
# ★只做「点到位」★：不打战斗、不判页面 —— 判定的真源在 scene/lords_unlock.py。
LordsUnlockAction = AgentServer.custom_action("lords_unlock_step")(LordsUnlockAction)


# ===========================================================================
# 设备无关：restart_game 走 MAA controller（★绝不写死 adb 路径 / serial★）。
#
# 历史 bug：旧实现写死了 MuMu 自带 adb 路径 + 127.0.0.1:16448，换任何一台机器
#   （包括用户自己）跑「唤醒/恢复」都会去重启【错误的设备】或直接失败。
# 现改为与 phantom_impl.PhantomRestartAction 完全同一套做法：
#   controller.post_stop_app / post_start_app + OCR 引导点击（点 OCR 到的按钮中心，
#   认不出才退回实测固定点）。因此可在任意实例上工作。
#   ★绝不使用 KeyEvent 4★（返回键会把游戏退回标题页）。
#
# 点位与 recover_game.py 完全一致（720 空间；仅当 OCR 认不出按钮时作为兜底）：
#   account_continue : 1080 (538,1270) → 720 (359,847)
#   title_start      : 1080 (520,1669) → 720 (347,1113)
#   nav_main_city    : 1080 (268,1890) → 720 (179,1260)
# ===========================================================================
DEFAULT_PKG = "com.leiting.wf"

TAP_720 = {
    "account": (359, 847),
    "title": (347, 1113),
    "nav": (179, 1260),
}


@AgentServer.custom_action("restart_game")
class RestartGameAction(CustomAction):
    """按实测流程强杀并重启游戏，拉回「主城」（★设备无关★）。

    走 MAA controller（不写死 adb 路径 / serial），与 PhantomRestartAction 同一套。

    步骤（★绝不使用 KeyEvent 4★）：
        1. controller.post_stop_app(pkg)，等 force_stop_wait 秒
        2. controller.post_start_app(pkg)，等 restart_wait 秒
        3. 账号确认页点「继续游戏」（OCR 命中即点其框中心；认不出退回固定点），等 login_wait 秒
        4. 标题页点「点击开始」，等 start_wait 秒
        5. 底部导航点「主城」，等 nav_wait 秒
        6. 主城锚点校验（仅打印；最终由 pipeline 锚点判定）

    可用参数（custom_action_param，语义与旧版完全兼容）：
        pkg            : 包名，默认 com.leiting.wf
        force_stop_wait: 强杀后等待秒数，默认 3
        restart_wait   : 重启后等待秒数，默认 35
        login_wait     : 点「继续游戏」后等待秒数，默认 20
        start_wait     : 点「点击开始」后等待秒数，默认 35
        nav_wait       : 点底部「主城」后等待秒数，默认 4
        ※ 旧的 adb / serial 参数已【移除】：点击一律走当前 controller 绑定的设备，
          换机器不会再重启错设备。
    """

    def _click_ocr_or(self, context: Context, patterns, fallback) -> None:
        """优先点 OCR 命中的按钮中心，认不出才退回实测固定点。"""
        img = _grab(context)
        items = _ocr(context, img)
        target = _pick(items, patterns)
        if target:
            print(
                f"[restart_game] OCR 命中 '{target[0]}' "
                f"@720({int(target[1])},{int(target[2])})"
            )
            _click_box(context, target[1], target[2])
        else:
            print(f"[restart_game] 未 OCR 到 {patterns}，退回实测固定点 {fallback}")
            _click_box(context, fallback[0], fallback[1])

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        param = json.loads(argv.custom_action_param or "{}") or {}
        pkg = param.get("pkg") or DEFAULT_PKG

        def sec(name: str, default: float) -> float:
            try:
                return max(0.0, float(param.get(name, default)))
            except (TypeError, ValueError):
                return float(default)

        force_stop_wait = sec("force_stop_wait", 3)
        restart_wait = sec("restart_wait", 35)
        login_wait = sec("login_wait", 20)
        start_wait = sec("start_wait", 35)
        nav_wait = sec("nav_wait", 4)

        print(
            f"[restart_game] pkg={pkg} "
            f"waits(force={force_stop_wait}, restart={restart_wait}, "
            f"login={login_wait}, start={start_wait}, nav={nav_wait})"
        )

        ctrl = context.tasker.controller
        try:
            print("[restart_game] 1) 强杀游戏")
            ctrl.post_stop_app(pkg).wait()
            time.sleep(force_stop_wait)

            print("[restart_game] 2) 启动游戏")
            ctrl.post_start_app(pkg).wait()
            time.sleep(restart_wait)

            print("[restart_game] 3) 账号确认页 -> 继续游戏")
            self._click_ocr_or(context, [r"^继续游戏$"], TAP_720["account"])
            time.sleep(login_wait)

            print("[restart_game] 4) 标题页 -> 点击开始")
            self._click_ocr_or(context, [r"^点击开始$"], TAP_720["title"])
            time.sleep(start_wait)

            print("[restart_game] 5) 底部导航 -> 主城")
            self._click_ocr_or(context, [r"^主城$"], TAP_720["nav"])
            time.sleep(nav_wait)
        except Exception as exc:  # noqa: BLE001
            print(f"[restart_game] 异常：{exc}")
            return False

        # 主城锚点校验（主城独有锚点 ≥2；仅打印，最终由 pipeline 锚点判定）。
        try:
            img = _grab(context)
            items = _ocr(context, img)
            city = [a for a in MAIN_CITY_ANCHORS if any(a in (t or "") for t, _ in items)]
            print(f"[restart_game] 主城锚点命中 {len(city)} 个：{city}")
        except Exception as exc:  # noqa: BLE001
            print(f"[restart_game] 主城校验失败：{exc}")

        print("[restart_game] 完成（最终是否在主城由 pipeline 锚点校验）")
        return True


@AgentServer.custom_action("wait_seconds")
class WaitSecondsAction(CustomAction):
    """按秒数阻塞等待。用于让 pipeline 的「等待」复用设置里的秒数选项。

    可用参数（custom_action_param）：
        seconds : 等待秒数（0-300），默认 0
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        param = json.loads(argv.custom_action_param or "{}") or {}
        try:
            seconds = float(param.get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        seconds = max(0.0, min(seconds, 300.0))
        print(f"[wait_seconds] 等待 {seconds}s")
        time.sleep(seconds)
        return True


# mark_done 的实现见 side_impl.MarkDoneAction（已在文件顶部 import + 注册）。


@AgentServer.custom_action("click_target")
class ClickTargetAction(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("ClickTargetAction is running!")

        param = json.loads(argv.custom_action_param or "{}") or {}
        target = param.get("target")
        if not isinstance(target, list) or len(target) != 2:
            return False

        # 执行点击。
        # ★走 run_action 原生 Click★：部分 MaaFramework（MFAAvalonia 随包）未导出
        #   MaaControllerPostClickV2，controller.post_click 会 ACCESS_VIOLATION；
        #   PubClick（common.json，target=true 点框中心）版本无关。
        context.run_action(
            "PubClick",
            box=(int(target[0]) - 1, int(target[1]) - 1, 2, 2),
        )

        return True
