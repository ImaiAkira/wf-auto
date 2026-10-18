# -*- coding: utf-8 -*-
"""真机帧回放（#68 / #74）：用【真实 MaaFramework + 真 OCR】在真机截图上跑恢复判据。

不用设备、不产生任何点击：把已保存的截图缩到 720，喂给真实 MaaFramework
（CustomController 静态图 + 真 OCR 模型），把恢复节点改成「只识别不动作」（DoNothing + next:[]），
断言：
  · 弹窗帧 → ``PubStaminaUseStone`` 命中，且输出框 = 真机「星导石 × 50」框；
  · 真机A 帧（2026-10-16 体力不足）→ ``PubStaminaUseStone`` 命中，输出框 = 星导石行框
    [209,873,160,32]（★#74 重标 ROI 的依据★），且第二步 ``PubStaminaConfirmOk`` **不**命中；
  · 确认帧 → ``PubStaminaConfirmOk`` 命中，且输出框 = 真机【OK】框 [496,805,53,37]；
  · ★真机A 结果窗帧（第四跑「体力回复了！」= 第三态）→ ``PubStaminaDoneOk`` 命中，且输出框
    = 真机结果窗【OK】框 [333,805,53,37]（在中心左侧）；第一 / 二步在该帧都**不**命中；
  · 编队页（无弹窗）→ 三步都**不**命中；
  · 弹窗帧 / 确认帧 / 真机A 体力不足帧 问结果窗第三步 → **不**命中；弹窗帧问确认框 /
    确认帧问第一步 → **不**命中（与门 / ROI / 页面门承重）。

截图来源：旧线 ``<repo-旧线>`` 战阵之宴「回复体力」弹窗 + 本线真机A 帧
（``tools/frames/stamina_insufficient_wuchong_a.png``、
``tools/frames/stamina_recovered_done_wuchong_a.png``，均入库随仓）。
缺 maa / OCR 模型 / 截图则 **SKIP（exit 0）**——不算失败。

用法：
    .venv\\Scripts\\python.exe tools\\verify_stamina_frames.py
可用环境变量覆盖截图路径：
    WF_STAMINA_POPUP / WF_STAMINA_CONFIRM / WF_STAMINA_TEAM / WF_STAMINA_A / WF_STAMINA_DONE
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "agent"))

ON_ERROR = Path(
    r"<repo-旧线>\projects\wf-auto\.slim\worktrees\phantom-patch\debug\on_error"
)
POPUP = Path(os.environ.get(
    "WF_STAMINA_POPUP",
    str(ON_ERROR / "2026.10.08-00.08.14.450_RaidStaminaConfirm.png"),
))
CONFIRM = Path(os.environ.get(
    "WF_STAMINA_CONFIRM",
    str(ON_ERROR / "2026.10.08-00.08.55.775_RaidStaminaDone.png"),
))
TEAM = Path(os.environ.get(
    "WF_STAMINA_TEAM",
    str(ON_ERROR / "2026.10.08-00.07.53.789_RaidStaminaPickStar.png"),
))
#: ★本线真机A 帧（2026-10-16 第三次 run 的体力不足弹窗）★ —— 随仓入库（不是旧线临时目录）。
STAMINA_A = Path(os.environ.get(
    "WF_STAMINA_A",
    str(PROJECT / "tools" / "frames" / "stamina_insufficient_wuchong_a.png"),
))
#: ★本线真机A 帧（2026-10-16 第四 run 的「体力回复了！」结果窗 = 第三态）★ —— 随仓入库。
STAMINA_DONE_A = Path(os.environ.get(
    "WF_STAMINA_DONE",
    str(PROJECT / "tools" / "frames" / "stamina_recovered_done_wuchong_a.png"),
))

EXPECTED_STONE_BOX = [209, 934, 161, 32]
EXPECTED_OK_BOX = [496, 805, 53, 37]
#: 真机A 帧「星导石 × 50」框（720）—— PubStaminaUseStone 必须输出它（#74 ROI 重标的验收）。
EXPECTED_STONE_BOX_A = [209, 873, 160, 32]
#: 真机A 结果窗 OK 框（720）—— PubStaminaDoneOk 必须输出它（第三态承重验收）。
EXPECTED_DONE_OK_BOX_A = [333, 805, 53, 37]

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _skip(reason: str) -> int:
    print(f"[SKIP] {reason}")
    return 0


def main() -> int:
    model = PROJECT / "assets" / "resource" / "model" / "ocr" / "det.onnx"
    if not model.is_file():
        return _skip(f"OCR 模型缺失（{model}）；把 ppocr det/rec/keys 放进 assets/resource/model/ocr/")
    for p in (POPUP, CONFIRM, TEAM, STAMINA_A, STAMINA_DONE_A):
        if not p.is_file():
            return _skip(f"截图缺失：{p}（旧线帧随临时目录消失则跳过）")
    try:
        import numpy as np  # noqa: F401
        from PIL import Image
        from maa.controller import CustomController
        from maa.resource import Resource
        from maa.tasker import Tasker
        from maa.toolkit import Toolkit
    except Exception as exc:  # noqa: BLE001
        return _skip(f"maa / PIL / numpy 不可用：{exc}")

    class ImageController(CustomController):
        def __init__(self, img):
            super().__init__()
            self.img = img

        def connect(self):
            return True

        def request_uuid(self):
            return "0"

        def screencap(self):
            return self.img

    def load_720(path):
        pil = Image.open(path).convert("RGB")
        if pil.width != 720:
            pil = pil.resize((720, round(pil.height * 720 / pil.width)), Image.LANCZOS)
        return np.ascontiguousarray(np.array(pil)[:, :, ::-1])

    def run(frame: Path, entry: str):
        """在静态图上跑 entry（动作 DoNothing + next:[]），返回 (hit, box)。"""
        Toolkit.init_option(str(PROJECT))
        ctrl = ImageController(load_720(frame))
        ctrl.set_screenshot_use_raw_size(True)
        ctrl.post_connection().wait()
        res = Resource()
        assert res.post_bundle(str(PROJECT / "assets" / "resource")).wait().succeeded
        tasker = Tasker()
        tasker.bind(res, ctrl)
        override = {entry: {"action": {"type": "DoNothing", "param": {}}, "next": []}}
        job = tasker.post_task(entry, override)
        job.wait()
        detail = job.get()
        if not detail or not detail.nodes:
            return False, None
        reco = detail.nodes[0].recognition
        if reco is None:
            return False, None
        return bool(reco.hit), (list(reco.box) if reco.box else None)

    print("=" * 74)
    print("真机帧回放（#68 / #74）：体力不足 → 星岛石恢复（真实 MaaFramework + 真 OCR）")
    print("=" * 74)

    print("\n== 第一步：弹窗帧 → 点星导石行 ==")
    hit, box = run(POPUP, "PubStaminaUseStone")
    check("弹窗帧命中 PubStaminaUseStone", hit, f"hit={hit} box={box}")
    check("输出框 = 星导石行框", box == EXPECTED_STONE_BOX, f"box={box} want={EXPECTED_STONE_BOX}")

    print("\n== 第二步：确认帧 → 点 OK ==")
    hit, box = run(CONFIRM, "PubStaminaConfirmOk")
    check("确认帧命中 PubStaminaConfirmOk", hit, f"hit={hit} box={box}")
    check("输出框 = OK 框", box == EXPECTED_OK_BOX, f"box={box} want={EXPECTED_OK_BOX}")

    print("\n== ★真机A 帧（2026-10-16 体力不足弹窗；#74 ROI 重标验收）★ ==")
    hit_a, box_a = run(STAMINA_A, "PubStaminaUseStone")
    check("真机A 帧命中 PubStaminaUseStone", hit_a, f"hit={hit_a} box={box_a}")
    check(
        "真机A 输出框 = 星导石行框 [209,873,160,32]",
        box_a == EXPECTED_STONE_BOX_A,
        f"box={box_a} want={EXPECTED_STONE_BOX_A}",
    )
    h_a_c, _ = run(STAMINA_A, "PubStaminaConfirmOk")
    check("真机A 帧（无确认框）→ 第二步不命中", not h_a_c, f"hit={h_a_c}")

    print("\n== ★真机A 帧（2026-10-16 第四跑「体力回复了！」结果窗 = 第三态）★ ==")
    hd, boxd = run(STAMINA_DONE_A, "PubStaminaDoneOk")
    check("真机A 结果窗帧命中 PubStaminaDoneOk", hd, f"hit={hd} box={boxd}")
    check(
        "结果窗输出框 = OK 框 [333,805,53,37]",
        boxd == EXPECTED_DONE_OK_BOX_A,
        f"box={boxd} want={EXPECTED_DONE_OK_BOX_A}",
    )
    hd1, _ = run(STAMINA_DONE_A, "PubStaminaUseStone")
    check("结果窗帧（无弹窗正文）→ 第一步不命中", not hd1, f"hit={hd1}")
    hd2, _ = run(STAMINA_DONE_A, "PubStaminaConfirmOk")
    check("结果窗帧（无确认框）→ 第二步不命中", not hd2, f"hit={hd2}")

    print("\n== 反例：都不命中 ==")
    h5, _ = run(POPUP, "PubStaminaDoneOk")
    check("弹窗帧 → 第三步不命中（结果窗正文门承重）", not h5, f"hit={h5}")
    h6, _ = run(CONFIRM, "PubStaminaDoneOk")
    check("确认帧 → 第三步不命中（页面门 + OK ROI 承重）", not h6, f"hit={h6}")
    h7, _ = run(TEAM, "PubStaminaDoneOk")
    check("编队页（无结果窗）→ 第三步不命中", not h7, f"hit={h7}")
    h8, _ = run(STAMINA_A, "PubStaminaDoneOk")
    check("真机A 体力不足帧 → 第三步不命中", not h8, f"hit={h8}")
    h1, _ = run(TEAM, "PubStaminaUseStone")
    check("编队页（无弹窗）→ 第一步不命中", not h1, f"hit={h1}")
    h2, _ = run(TEAM, "PubStaminaConfirmOk")
    check("编队页（无弹窗）→ 第二步不命中", not h2, f"hit={h2}")
    h3, _ = run(CONFIRM, "PubStaminaUseStone")
    check("确认帧 → 第一步不命中（ROI 承重：标题里的星导石不算）", not h3, f"hit={h3}")
    h4, _ = run(POPUP, "PubStaminaConfirmOk")
    check("弹窗帧 → 第二步不命中", not h4, f"hit={h4}")

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅（点的是星导石行 / OK 框中心，读后动）")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())

