# -*- coding: utf-8 -*-
"""真机验证：自动刷副本（SpecialEntry）—— 批量清单 / 单目标 / 多人路径。

在进程内注册 pipeline 引用到的全部自定义识别/动作（唯一注册源 tools/live_harness.py，
不走 MFAAvalonia / AgentServer），用 tasker.post_task 跑真实 SpecialEntry，覆盖成与界面选项等价的一组参数。

用法示例（项目根目录执行）：
    # 批量清单（2 个副本，各 1 次），单人
    .venv\\Scripts\\python.exe tools\\run_special_live.py \
        --list "猩红巨熊讨伐,中级,1;背鳍三兄弟讨伐,中级,1" --timeout 600

    # 单目标
    .venv\\Scripts\\python.exe tools\\run_special_live.py \
        --dungeon 猩红巨熊讨伐 --difficulty 中级 --timeout 300

    # 多人（建立房间 → 随机招募 → 战斗），开自动续战
    .venv\\Scripts\\python.exe tools\\run_special_live.py --multi --recruit random \
        --dungeon 猩红巨熊讨伐 --difficulty 中级 --timeout 600

安全：全程不使用 KeyEvent 4；结束时导航回主城；标题页出现即停手。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "agent"))

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

import live_harness as ca  # noqa: E402
import progress as ledger  # noqa: E402

ASSETS = PROJECT / "assets" / "resource"

DIFFICULTY_REGEX = {
    "初级": "初级$",
    "中级": "中级$",
    "高级": "高级$",
    "高级+": r"高级\+$",
    "超级": "超级$",
}


def register_customs(res: Resource) -> None:
    # #20：注册 pipeline 引用到的【全部】自定义识别/动作（唯一注册源在 live_harness）。
    # 过去这里手写子集，漏了 restart_game —— 真机卡死看门狗命中 stall_recover 后
    # 却执行不了恢复动作（Action is null），任务直接 failed。
    ca.register_pipeline_customs(res)


def _apply_target_tab_override(ov: dict, dungeon: str) -> None:
    """按目标子族关掉非目标子族的页签（#19：页签由目标子族决定，不靠 max_hit 竞速）。

    复用 ``scene.chain.tab_override_for`` —— 与 GUI 选项（``scene.options``）和批量指挥官
    （``agent.side_impl._special_override``）表达同一事实。本 runner 若不带这条覆盖，就会用
    「两个 tab 都开」的旧竞速形态跑真机：基础 pipeline 里「领主战」tab 标签常驻且排在
    ``SpecialTabJoss`` 之前，降临讨伐目标会永远找不到、直到 stall（#13 结算后死循环的根因）。
    """
    try:
        sys.path.insert(0, str(PROJECT))
        from scene.chain import resolve_target, tab_override_for
        from scene.lord_battle import LORD_BATTLE
    except Exception:  # noqa: BLE001 -- 缺 scene 时退回旧行为，不阻断真机 runner
        return
    t = resolve_target(LORD_BATTLE, {"成员": dungeon})
    if t is None:
        return
    ov.update(tab_override_for(t.子族))


def build_override(a) -> dict:
    ov: dict = {}

    # ---- 批量清单指挥官 ----
    ov["SpecialBatchPlan"] = {
        "recognition": {
            "type": "Custom",
            "param": {
                "custom_recognition": "special_batch_plan",
                "custom_recognition_param": {"list": a.list or ""},
            },
        }
    }

    # ---- 单目标（清单为空时生效） ----
    if a.dungeon:
        ov["SpecialEnterBoss"] = {
            "recognition": {"type": "OCR", "param": {"expected": [a.dungeon], "roi": [150, 440, 320, 800]}}
        }
        # #19：页签由目标子族决定 —— 关掉非目标子族的 tab，绝不靠 max_hit 竞速。
        _apply_target_tab_override(ov, a.dungeon)
    if a.difficulty:
        ov["SpecialFightTargetRow"] = {
            # P0：直接返回该难度行【战斗】按钮 OCR 框（零偏移，绝不误点推荐编成）。
            "recognition": {
                "type": "Custom",
                "param": {
                    "custom_recognition": "special_target_fight",
                    "custom_recognition_param": {"difficulty": DIFFICULTY_REGEX[a.difficulty]},
                },
            },
            "max_hit": a.times,
        }

    # ---- 单人 / 多人 ----
    none_rec = {"recognition": {"type": "OCR", "param": {"expected": ["__NONE__"]}}}
    if a.multi:
        ov["SpecialModeSolo"] = none_rec
        # 多人的开打是房间页「战斗」；关掉编队页「挑战」，避免重复计数
        ov["SpecialChallenge"] = none_rec
    else:
        ov["SpecialModeMulti"] = none_rec
        # 单人的开打是编队页「挑战」；关掉房间页「战斗」（其 ROI 会误命中详情页最低档行内战斗）
        ov["SpecialRoomFight"] = none_rec
        # 单人兜底：误入房间页时点返回退出（与 interface「单人」一致）
        ov["SpecialLeaveRoom"] = {
            "recognition": {
                "type": "And",
                "param": {
                    "all_of": ["SpecialPartyText", "SpecialRoomCopyText", "SpecialRoomPowerText"],
                    "box_index": 0,
                },
            }
        }

    # ---- 多人招募方式 ----
    recruit = (a.recruit or "random").lower()
    if a.multi:
        recruit_nodes = ["SpecialRecruitOpen", "SpecialRecruitRandom", "SpecialRecruitFans",
                         "SpecialRecruitMutual", "SpecialStartRecruit"]
        if recruit == "random":
            ov["SpecialRecruitFans"] = none_rec
            ov["SpecialRecruitMutual"] = none_rec
        elif recruit == "fans":
            ov["SpecialRecruitRandom"] = none_rec
            ov["SpecialRecruitMutual"] = none_rec
        elif recruit == "mutual":
            ov["SpecialRecruitRandom"] = none_rec
            ov["SpecialRecruitFans"] = none_rec
        elif recruit == "none":
            for n in recruit_nodes:
                ov[n] = none_rec

    # ---- 自动续战 ----
    if a.autocontinue in ("on", "off"):
        target = [640, 158] if a.autocontinue == "on" else [545, 157]
        ov["SpecialAutoContinueSet"] = {
            "action": {"type": "Click", "param": {"target": target}},
            "max_hit": 1,
        }

    return ov


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="", help="批量清单文本（分号/换行分隔）")
    ap.add_argument("--dungeon", default="", help="单目标副本名")
    ap.add_argument("--difficulty", default="", choices=["", "初级", "中级", "高级", "高级+", "超级"])
    ap.add_argument("--times", type=int, default=1, help="单目标次数（max_hit）")
    ap.add_argument("--multi", action="store_true", help="走多人（建立房间）")
    ap.add_argument("--recruit", default="random", choices=["random", "fans", "mutual", "none"])
    ap.add_argument("--autocontinue", default="on", choices=["on", "off"])
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument(
        "--stop-timeout",
        type=float,
        default=15.0,
        help="超时/停手后确认任务真正停止的上限秒数（#31：到期即归还控制，绝不无限等）",
    )
    ap.add_argument("--stall", type=int, default=0, help="stall 秒数（0=关）")
    ap.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    ap.add_argument("--progress", default=str(ca.WORK_DIR / "live_batch_progress.json"))
    a = ap.parse_args()

    # #40：先连接并打印实际设备身份（日志首行），地址缺省时按账号身份发现。
    # #130：默认（WF_LIVE_EXPECT_* 全 unset）只记日志、**不校验型号**；显式设置才严格比较。
    # #perf：启动入口收敛到 ca.apply_global_options —— Toolkit.init_option + save_draw 默认关
    # （要临时抓帧设 WF_SAVE_DRAW=1）+ debug 产物上界（见 live_harness 里那一段的实测数字）。
    ca.apply_global_options(PROJECT)
    ctrl = ca.connect_device(ca.ADB, a.address, expect=ca.expected_identity())

    res = Resource()
    ok = res.post_bundle(str(ASSETS)).wait().succeeded
    print("resource load:", ok)
    if not ok:
        sys.exit(1)
    register_customs(res)

    # #25：唯一登记入口 —— 构造 + 连接 + 同步 ADDRESS/_ctrl_ref 一步完成（见 connect_device）。
    tasker = Tasker()
    tasker.bind(res, ctrl)
    watcher = ca.TitleWatcher(str(ASSETS))
    print("标题页守护:", "启用" if watcher.enabled else "不启用")

    pf = Path(a.progress)
    ledger.set_file(pf)
    print("账本文件:", pf)

    override = build_override(a)
    print("override =", json.dumps(override, ensure_ascii=False))

    try:
        if not ca.ensure_main_city(watcher):
            print("!! 未回主城，放弃")
            return
        if watcher.enabled and watcher.detect():
            print("!! 启动即在标题页，放弃")
            return
        status, executed = ca.run_task_traced(
            tasker, "SpecialEntry", override, a.timeout,
            "special", watcher, stall_timeout=a.stall, stop_timeout=a.stop_timeout,
        )
        print("\n==== 结果 status =", status, flush=True)
        print("节点序列(尾 40):", executed[-40:], flush=True)
        print("账本:", ledger.all_keys(), flush=True)
    finally:
        print("\n== 收尾：导航回主城 ==", flush=True)
        try:
            ca.ensure_main_city(watcher)
        except Exception as exc:  # noqa: BLE001
            print("回主城异常:", exc)


if __name__ == "__main__":
    main()
