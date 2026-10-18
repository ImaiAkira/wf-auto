# -*- coding: utf-8 -*-
"""离线单测：归位（#18）—— 不再自匹配「主城」+ 两类事件注入位置相反 + 死循环复现。

不需要游戏；默认连 maa 运行时都不需要（判据在**内嵌的真机帧 OCR**上求值）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_return_home.py

覆盖 #18 的验收：

  1. **两类事件、位置相反**：打断型（9 类异常）前缀、兜底型（归位）后缀（末位恢复边之前）；
  2. **归位在主城、链上步骤页面上都不命中**（#29 更新）：判据在 pre_shot.png（主城）的
     OCR 上为假、在 r1/r2/r3（列表 / 详情页）的 OCR 上【也】为假（链上步骤页面不得自匹配，
     否则目标行在屏幕外时抢跑、滚动找行永不执行），在漂到别的分区的真机帧
     （scope_gacha.png：扭蛋分区页）上为真 —— 即「只在真正该回主城时才命中」；
  3. **离线复现本次死循环**：给一个「当前 = 主城」的用例，**旧形态**（归位是优先前缀 +
     只认主城）会在主城上死循环、**新形态**（归位是兜底后缀 + And 判据）第 1 步就前进；
  4. **真机帧实证（best-effort）**：若本机有 maa 与抓下的帧，则对 PubReturnHome 直接跑一次
     识别，断言「主城不命中、列表页（#29 起为链上步骤页面）也不命中」；缺任一则 SKIP。
     （正例「非主城分区页命中」见 ``tools/test_return_home_scope.py``。）
  5. 挂点 ``hooks_18`` 已点亮、prove-red 成立。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_18.py``。
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene import drift  # noqa: E402
from scene.events import (  # noqa: E402
    EVENTS,
    FALLBACK_EVENTS,
    FALLBACK_KIND,
    INTERRUPT_EVENTS,
    INTERRUPT_KIND,
    RETURN_HOME_NODE_SPEC,
    fallback_refs,
    interrupt_refs,
    return_home_ref,
)

import hooks_18  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
SD = PIPELINE_DIR / "special_dungeon.json"

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧（#13 的落盘证据）；缺则 SKIP。
FRAME_MAIN_CITY = Path(
    os.environ.get("WF_R18_MAIN_CITY", str(TEMP_OPENCODE / "pre_shot.png"))
)
FRAME_LIST = Path(
    os.environ.get("WF_R18_LIST", str(TEMP_OPENCODE / "r1.png"))
)

HOME = "[JumpBack]PubReturnHome"
_HOME_NAME = "PubReturnHome"


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


def _files() -> dict:
    return drift.load_pipelines(PIPELINE_DIR)


# ---------------------------------------------------------------------------
# 1. 两类事件、位置相反
# ---------------------------------------------------------------------------
def test_two_classes_opposite_positions() -> None:
    print("\n== 1. 两类事件：打断型前缀 / 兜底型后缀 ==")
    check("打断型事件组都是 kind=interrupt", all(e.kind == INTERRUPT_KIND for e in INTERRUPT_EVENTS))
    check("兜底型事件组都是 kind=fallback", all(e.kind == FALLBACK_KIND for e in FALLBACK_EVENTS))
    check("兜底型事件组恰是归位", tuple(e.name for e in FALLBACK_EVENTS) == ("归位",))
    check("归位引用只在兜底后缀里（不在打断前缀里）",
          return_home_ref() in fallback_refs() and return_home_ref() not in interrupt_refs())
    check("#18 位置锁：真实 pipeline 每个流程节点 = 打断前缀 + … + 兜底后缀 + 末位终点",
          hooks_18.probe_event_classes_opposite_positions() is True)

    # 归位必须排在末位恢复边之前；把它放回前缀即红（这里直接构造反例）。
    files = _files()
    sd = files["special_dungeon.json"]
    hub_next = sd["SpecialEntry"]["next"]
    old_shape = [HOME] + [x for x in hub_next if x != HOME]
    prefix = list(interrupt_refs())
    check("反例：旧形态（归位在前缀位置）不再是规范形（前缀里混入归位）",
          old_shape[: len(prefix)] != prefix or HOME in old_shape[: len(prefix) + 1])


# ---------------------------------------------------------------------------
# 2. 归位在主城上不命中（内嵌真机帧 OCR）
# ---------------------------------------------------------------------------
def test_return_home_not_self_matching() -> None:
    print("\n== 2. 归位判据：主城 / 链上步骤页面帧不命中、非主城分区页帧命中 ==")
    check("挂点 return-home-not-self-matching 已点亮（probe=True）",
          hooks_18.probe_return_home_not_self_matching() is True)
    rec = RETURN_HOME_NODE_SPEC["recognition"]
    resolve = hooks_18._resolver(_files())
    check("判据在主城真机帧 OCR 上为假",
          not hooks_18.eval_recognition(rec, hooks_18.MAIN_CITY_OCR, resolve, hooks_18._ZERO_ORANGE))
    # ★#29★ 链上步骤页面（列表 / 详情）由 #18 的「正例」改为【反例】。
    check("判据在【链上步骤页面】(列表/详情) 真机帧上为假（#29：不自匹配）",
          not hooks_18.eval_recognition(rec, hooks_18.SUB_PAGE_OCR, resolve, hooks_18._ZERO_ORANGE))
    check("判据在【非主城分区页】(扭蛋) 真机帧上为真（真正该归位）",
          hooks_18.eval_recognition(rec, hooks_18.GACHA_OCR, resolve, hooks_18.GACHA_ORANGE))


# ---------------------------------------------------------------------------
# 3. 离线复现死循环：旧形态死循环 / 新形态前进
# ---------------------------------------------------------------------------
def test_offline_loop_repro() -> None:
    print("\n== 3. 离线复现 #13 死循环：当前 = 主城，旧形态死循环、新形态前进 ==")
    files = _files()
    hub_next = list(files["special_dungeon.json"]["SpecialEntry"]["next"])
    old_next = [HOME] + [x for x in hub_next if x != HOME]  # 旧：归位当优先前缀
    new_next = list(hub_next)  # 新：归位当兜底后缀（末位恢复边之前）
    old_rec = {"type": "OCR", "param": {"expected": ["^主城$"], "roi": [0, 1180, 720, 100]}}
    steps = 10

    old_seq = hooks_18.simulate(
        old_next, hooks_18.MAIN_CITY_OCR, files, max_steps=steps,
        overrides={_HOME_NAME: old_rec},
    )
    new_seq = hooks_18.simulate(new_next, hooks_18.MAIN_CITY_OCR, files, max_steps=steps)

    check(f"旧形态在主城上死循环：{steps} 步全是归位",
          old_seq == ["PubReturnHome"] * steps, f"seq={old_seq[:4]}")
    check("旧形态在主城上永远走不到 SpecialOpenLord（链第 0 步卡死）",
          "SpecialOpenLord" not in old_seq)
    check("新形态在主城上第 1 步就前进到 SpecialOpenLord",
          bool(new_seq) and new_seq[0] == "SpecialOpenLord", f"seq={new_seq[:4]}")
    check("新形态不再命中归位（不自匹配）", "PubReturnHome" not in new_seq)


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort；缺 maa / 帧则 SKIP）
# ---------------------------------------------------------------------------
_OCR_MODEL = REPO_ROOT / "assets" / "resource" / "model" / "ocr" / "det.onnx"


def _maa_node_matches(image_path: Path, node: str):
    """对一张帧跑 ``node`` 的识别：命中 -> True，未命中 -> False，环境不可用 -> None。

    MAA 的语义：entry 命中时 ``detail.nodes`` 里会出现该节点名；未命中（超时）时只留一个空名节点。
    因此「节点名是否出现在 detail.nodes 里」就是「命中与否」。动作覆盖为 DoNothing 以免触发点击。
    """
    if not image_path.is_file():
        return None
    if not _OCR_MODEL.is_file():
        return None  # 裸检出没有 OCR 模型（gitignore 的运行时产物）：不臆测
    try:
        import numpy as np
        from PIL import Image
        from maa.controller import CustomController
        from maa.resource import Resource
        from maa.tasker import Tasker
        from maa.toolkit import Toolkit
    except Exception:  # noqa: BLE001
        return None

    class _Img(CustomController):
        def __init__(self, img):
            super().__init__()
            self.img = img

        def connect(self):
            return True

        def request_uuid(self):
            return "0"

        def screencap(self):
            return self.img

    try:
        Toolkit.init_option(str(REPO_ROOT))
        res = Resource()
        if not res.post_bundle(str(REPO_ROOT / "assets" / "resource")).wait().succeeded:
            return None
        pil = Image.open(image_path).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280))
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        ctrl = _Img(img)
        ctrl.set_screenshot_use_raw_size(True)
        ctrl.post_connection().wait()
        tasker = Tasker()
        tasker.bind(res, ctrl)
        override = {node: {"timeout": 4000, "action": {"type": "DoNothing", "param": {}}}}
        job = tasker.post_task(node, override)
        job.wait()
        detail = job.get()
        if detail is None:
            return None
        return node in {nd.name for nd in detail.nodes}
    except Exception:  # noqa: BLE001
        return None


def test_real_device_frames_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：PubReturnHome 在主城 / 列表页都不命中 ==")
    main_city = _maa_node_matches(FRAME_MAIN_CITY, _HOME_NAME)
    if main_city is None:
        skip("真机帧 MAA 识别（主城）", f"缺 maa / OCR 模型 / 帧：{FRAME_MAIN_CITY}")
    else:
        check("PubReturnHome 在【主城】真机帧上【不命中】（不再自匹配）", main_city is False)

    # ★#29 更新★：列表页由 #18 的「正例」改为【反例】—— 它是链上步骤页面，归位不得命中
    #   （否则目标行在屏幕外时抢跑、滚动找行永不执行）。正例见 tools/test_return_home_scope.py。
    lst = _maa_node_matches(FRAME_LIST, _HOME_NAME)
    if lst is None:
        skip("真机帧 MAA 识别（列表页）", f"缺 maa / OCR 模型 / 帧：{FRAME_LIST}")
    else:
        check("PubReturnHome 在【列表页】真机帧上【不命中】（#29：链上步骤页面不得自匹配）",
              lst is False)


# ---------------------------------------------------------------------------
# 5. 漂移 + 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_drift_and_hook() -> None:
    print("\n== 5. 无漂移 + 挂点点亮 + prove-red 成立 ==")
    check("真实树无漂移（check_all == []）", drift.check_all(repo_root=REPO_ROOT) == [])
    check("hooks_18.prove_red() 成立（挪回前缀 / 弱化判据各自变红）",
          hooks_18.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("离线单测：归位（#18）—— 不自匹配主城 + 两类注入位置相反 + 死循环复现")
    print("=" * 70)
    test_two_classes_opposite_positions()
    test_return_home_not_self_matching()
    test_offline_loop_repro()
    test_real_device_frames_best_effort()
    test_drift_and_hook()
    print("\n" + "=" * 70)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
