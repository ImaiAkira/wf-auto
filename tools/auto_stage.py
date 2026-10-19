"""自动推主线/打关卡的简易状态机（OCR 驱动）。

用法（项目根目录执行）:
    .venv\\Scripts\\python.exe tools\\auto_stage.py [--max-steps 200] [--max-minutes 12]

原理:
    每轮截屏 OCR -> 识别当前界面 -> 执行对应点击 -> 等待。覆盖状态:
    结算页(继续/OK)、获得道具页、初次报酬弹窗、剧情跳过及确认、
    战斗准备(挑战)、战斗中(等待)、主界面(关卡)、章节选择、关卡列表(进入关卡)。
    全过程记录到 auto_stage_log.txt，异常画面截图到 screenshots/auto_*.png。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

import vision  # 同目录工具：视觉定位关卡节点
import live_harness as ca  # #40：设备地址的唯一真源（身份发现），不再写死任何端口
from portable_paths import find_adb  # 脱敏：不把本机 adb 路径烧进默认值

DEFAULT_ADB = find_adb()

FALLBACK = {
    "result_next": (358, 1198),
    "close_popup": (359, 823),
    "skip_topright": (656, 47),
    "skip_confirm": (521, 868),
    "challenge": (337, 1092),
    "home_level": (359, 1112),
    "chapter_card": (62, 647),
    "stage_row": (351, 463),
    "back": (53, 1259),
}


class AutoStage:
    def __init__(self, project: Path, adb: str, address: str) -> None:
        self.project = project
        self.adb = adb
        self.address = address
        self.shots = project / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.log_path = project / "auto_stage_log.txt"
        self.lines: list[str] = []
        self.step = 0
        self.unknown_rounds = 0
        self.stage_retry = 0
        self.loading_rounds = 0
        self.last_sig = ""

        Toolkit.init_option(str(project))
        self.res = Resource()
        self.log(
            "resource load:",
            self.res.post_bundle(str(project / "assets" / "resource")).wait().succeeded,
        )
        self.ctrl = AdbController(adb, address)
        self.log("device connect:", self.ctrl.post_connection().wait().succeeded)
        self.tasker = Tasker()
        self.log("bind:", self.tasker.bind(self.res, self.ctrl))

    def log(self, *parts: object) -> None:
        text = " ".join(str(p) for p in parts)
        print(text, flush=True)
        self.lines.append(text)
        self.log_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def ocr(self) -> list[Any]:
        job = self.tasker.post_task("OcrTask")
        job.wait()
        detail = job.get()
        results: list[Any] = []
        if detail is not None:
            for node in detail.nodes:
                reco = node.recognition
                if reco:
                    results = list(reco.all_results or [])
        return results

    @staticmethod
    def find_center(results: list[Any], *candidates: str, exact: bool = False) -> Optional[tuple[int, int]]:
        for r in results:
            text = (getattr(r, "text", "") or "").strip()
            for cand in candidates:
                hit = text == cand if exact else cand in text
                if hit:
                    x = int(r.box[0] + r.box[2] / 2)
                    y = int(r.box[1] + r.box[3] / 2)
                    return (x, y)
        return None

    def click(self, pos: tuple[int, int], reason: str) -> None:
        self.log(f"  [{reason}] click {pos}")
        self.ctrl.post_click(int(pos[0]), int(pos[1])).wait()
        self.unknown_rounds = 0
        if reason != "关卡列表-进入关卡":
            self.stage_retry = 0

    def locate_stage_entry(self) -> Optional[tuple[int, int]]:
        """用视觉模型定位当前关卡节点/进入按钮；失败返回 None。"""
        self.ctrl.post_screencap().wait()
        img = self.ctrl.cached_image
        if img is None:
            return None
        snap = self.shots / f"auto_{self.step:03d}_locate.png"
        Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(snap)
        try:
            items = vision.locate(snap, "当前进度所在的关卡节点，或可点击进入关卡的圆形平台/按钮")
        except SystemExit as exc:
            self.log("  视觉定位失败:", exc)
            return None
        if not items:
            self.log("  视觉未找到关卡节点")
            return None
        name, x1, y1, x2, y2, _score = items[0]
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        self.log(f"  视觉定位: {name} bbox=({x1},{y1},{x2},{y2}) -> {center}")
        return center

    @staticmethod
    def locate_stage_entry_by_ocr(results: list[Any]) -> Optional[tuple[int, int]]:
        """用 OCR 找当前关卡节点：取离「当前进度」最近的「第N关」标签，点其上方节点区。"""
        progress: Optional[tuple[int, int]] = None
        stages: list[tuple[int, int]] = []
        for r in results:
            text = (getattr(r, "text", "") or "").strip()
            cx = int(r.box[0] + r.box[2] / 2)
            cy = int(r.box[1] + r.box[3] / 2)
            if "当前进度" in text:
                progress = (cx, cy)
            elif text.startswith("第") and text.endswith("关"):
                stages.append((cx, cy))
        if not stages:
            return None
        if progress is not None:
            stage = min(
                stages,
                key=lambda p: abs(p[0] - progress[0]) + abs(p[1] - progress[1]),
            )
        else:
            stage = stages[0]
        return (stage[0], max(0, stage[1] - 60))

    def restart_game(self, package: str = "com.leiting.wf") -> None:
        """强制重启游戏客户端（用于加载卡死恢复）。"""
        subprocess.run(
            [self.adb, "-s", self.address, "shell", "am", "force-stop", package],
            check=False,
            capture_output=True,
        )
        time.sleep(3)
        subprocess.run(
            [
                self.adb,
                "-s",
                self.address,
                "shell",
                "monkey",
                "-p",
                package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            check=False,
            capture_output=True,
        )
        time.sleep(25)

    def screenshot(self, tag: str) -> None:
        self.ctrl.post_screencap().wait()
        img = self.ctrl.cached_image
        if img is None:
            return
        stamp = dt.datetime.now().strftime("%H%M%S")
        path = self.shots / f"auto_{self.step:03d}_{stamp}_{tag}.png"
        Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(path)
        self.log("  截图:", path.name)

    def run(self, max_steps: int, max_minutes: float) -> None:
        start = time.time()
        battle_rounds = 0
        for _ in range(max_steps):
            self.step += 1
            if (time.time() - start) / 60 > max_minutes:
                self.log("达到时间上限，结束")
                break

            results = self.ocr()
            texts = [(getattr(r, "text", "") or "").strip() for r in results]
            joined = "\n".join(texts)
            # 用长度 >= 2 的文本集合做签名，避免单字符 OCR 噪声误判为界面变化
            signature = "|".join(sorted(t for t in texts if len(t) >= 2))[:400]
            if self.last_sig and signature != self.last_sig:
                # 界面发生变化说明上一步点击有效，重置重试计数
                self.stage_retry = 0
                self.unknown_rounds = 0
                self.loading_rounds = 0
            self.last_sig = signature
            self.log(f"== step {self.step} 状态判定")
            self.log("  OCR:", " / ".join(t for t in texts if t)[:300])

            if "继续游戏" in texts:
                pos = self.find_center(results, "继续游戏") or (359, 847)
                self.click(pos, "登录页-继续游戏")
                time.sleep(5)
                continue

            if "点击开始" in texts:
                pos = self.find_center(results, "点击开始") or (347, 1114)
                self.click(pos, "标题页-点击开始")
                time.sleep(8)
                continue

            if "请耐心等待" in joined:
                self.loading_rounds += 1
                self.log(f"  加载中…（连续 {self.loading_rounds} 次）")
                if self.loading_rounds >= 12:
                    self.log("  加载卡死，重启游戏客户端")
                    self.restart_game()
                    self.loading_rounds = 0
                else:
                    time.sleep(5)
                continue

            if "QUESTRESULT" in joined:
                pos = self.find_center(results, "继续", "OK") or FALLBACK["result_next"]
                self.click(pos, "结算页-继续/OK")
                time.sleep(2)
                continue

            if "获得道具" in joined:
                pos = self.find_center(results, "继续") or FALLBACK["result_next"]
                self.click(pos, "道具页-继续")
                time.sleep(2)
                continue

            if "获得初次报酬" in joined or "关闭" in texts:
                pos = self.find_center(results, "关闭") or FALLBACK["close_popup"]
                self.click(pos, "弹窗-关闭")
                time.sleep(2)
                continue

            if "点击【跳过】" in joined:
                pos = self.find_center(results, "跳过", exact=True) or FALLBACK["skip_confirm"]
                self.click(pos, "剧情-跳过确认")
                time.sleep(2)
                continue

            skip_pos: Optional[tuple[int, int]] = None
            for r in results:
                text = (getattr(r, "text", "") or "").strip()
                if "跳过" in text and r.box[1] < 120:  # 右上角跳过按钮（兼容"跳过 >"/"跳过>"）
                    skip_pos = (int(r.box[0] + r.box[2] / 2), int(r.box[1] + r.box[3] / 2))
                    break
            if skip_pos:
                self.click(skip_pos, "剧情-跳过")
                time.sleep(2)
                continue

            if "挑战" in texts:
                pos = self.find_center(results, "挑战") or FALLBACK["challenge"]
                self.click(pos, "准备页-挑战")
                time.sleep(3)
                continue

            if "技能自动" in joined or ("时间" in joined and "分数" in joined):
                battle_rounds += 1
                self.log(f"  战斗中，等待 20s（第 {battle_rounds} 次检查）")
                time.sleep(20)
                continue

            if "当前进度" in joined and "关卡" in texts:
                pos = self.find_center(results, "关卡", exact=True) or FALLBACK["home_level"]
                self.click(pos, "主界面-关卡")
                time.sleep(2)
                continue

            if "通关率" in joined:
                self.click(FALLBACK["chapter_card"], "章节选择-进入章节")
                time.sleep(2)
                continue

            if (
                "世界" in joined
                or "机人的行星" in joined
                or "当前进度" in joined
                or "COMPLETE!!" in joined
                or "推荐编成" in joined
                or "STORY" in joined
                or re.search(r"第\d+关", joined)
                or "OMPLETE" in joined
            ):
                self.stage_retry += 1
                pos: Optional[tuple[int, int]] = FALLBACK["stage_row"]
                if self.stage_retry > 2:
                    pos = (
                        self.locate_stage_entry()
                        or self.locate_stage_entry_by_ocr(results)
                        or FALLBACK["stage_row"]
                    )
                self.click(pos, "关卡列表-进入关卡")
                time.sleep(2)
                continue

            self.unknown_rounds += 1
            self.log(f"  未识别状态（连续 {self.unknown_rounds} 次），截屏并等待")
            self.screenshot("unknown")
            if self.unknown_rounds >= 4 and "返回" in texts:
                pos = self.find_center(results, "返回", exact=True) or FALLBACK["back"]
                self.click(pos, "未知状态-返回上级")
                time.sleep(3)
                continue
            time.sleep(5)

        self.screenshot("end")
        self.log("结束")


def main() -> None:
    parser = argparse.ArgumentParser(description="自动打关卡")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--max-minutes", type=float, default=12)
    parser.add_argument("--address", default=None, help="设备地址；缺省按【账号身份】发现（#40）")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    project = (
        Path(args.project).resolve()
        if args.project
        else Path(__file__).resolve().parent.parent
    )
    # #40：地址缺省按账号身份发现（不再写死端口）。
    # #130：身份**照读并打进日志**，但默认（WF_LIVE_EXPECT_* 全 unset）**不校验型号**。
    address = args.address or ca.resolve_address(DEFAULT_ADB, ca.expected_identity())
    identity = ca.read_identity(DEFAULT_ADB, address)
    ca.log_device_identity(identity, ca.expected_identity())
    problem = ca.identity_mismatch(identity, ca.expected_identity())
    if problem:
        raise SystemExit(problem)
    bot = AutoStage(project, DEFAULT_ADB, address)
    bot.run(args.max_steps, args.max_minutes)


if __name__ == "__main__":
    main()
