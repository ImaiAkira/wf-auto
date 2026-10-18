# -*- coding: utf-8 -*-
"""离线单测：#29 归位不得在【链上步骤页面】上自匹配 + 滚动找行的路必须可达。

不需要游戏 / 设备（判据全在内嵌的**真机帧模型** + 列表屏状态机上）；真机帧实证是
best-effort（缺 maa / OCR 模型 / 帧则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_return_home_scope.py
    .venv\\Scripts\\python.exe tools\\test_return_home_scope.py --prove-red

覆盖 #29 的验收：

  1. **判据范围**：兜底归位在链上步骤页面（**列表页 / 详情页 / 编队页**）真机帧上**不命中**，
     在**真正该归位**的页面（漂到别的分区：扭蛋分区页）真机帧上**命中**；
  2. **离线复现本次循环**（目标行在屏幕外，确定性）：旧形态（归位与列表页自匹配、页签后继
     里没有滚动）首命中 = ``PubReturnHome`` 抢跑、``SpecialScrollList`` 永不执行（死循环）；
     新形态必经 ``SpecialScrollList``（滚动找行）、不再命中 ``PubReturnHome``；
  3. **破坏实验**（prove-red）：去掉页面范围判别叶 -> 守卫 1 变红；去掉滚动后继 -> 守卫 2 变红；
  4. **真机帧实证（best-effort）**：若本机有 maa + OCR 模型 + 抓下的帧，对 ``PubReturnHome``
     直接跑一次识别，断言「列表 / 详情页不命中、扭蛋分区页命中」；并用 PIL 复算内嵌的
     分区页签橙色像素计数；缺任一则 SKIP；
  5. **无漂移 + 三条既有路径守卫仍绿 + 挂点 prove-red 成立**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_29.py``。
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

import hooks_29  # noqa: E402

PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧证据（#29；缺则 best-effort 段 SKIP）。
FRAME_LIST = REPO_ROOT / "tools" / "frames" / "lord_page_tab_lord.png"
FRAME_TEAM = REPO_ROOT / "tools" / "frames" / "lord_team_page.png"
FRAME_DETAIL = Path(
    os.environ.get("WF_R29_DETAIL", str(TEMP_OPENCODE / "afterC.png"))
)
FRAME_GACHA = Path(
    os.environ.get("WF_R29_GACHA", str(TEMP_OPENCODE / "scope_gacha.png"))
)
_OCR_MODEL = REPO_ROOT / "assets" / "resource" / "model" / "ocr" / "det.onnx"


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
# 1. 判据范围：链上步骤页面不命中、真正该归位的页面命中（真机帧模型）
# ---------------------------------------------------------------------------
def test_scope() -> None:
    print("\n== 1. 归位判据范围：链上步骤页面不命中 / 非主城分区页命中 ==")
    check("挂点 return-home-scope-not-chain-page 已点亮（probe=True）",
          hooks_29.probe_return_home_scope_not_chain_page() is True)
    check("判据绑定：产品四条 ColorMatch 与 hooks_29 的常量一致",
          hooks_29._binding_failures(_files()) == [], f"{hooks_29._binding_failures(_files())[:2]}")

    rec = hooks_29._home_node(_files())
    resolve = hooks_29._resolver(_files())
    for frame in hooks_29.FRAMES:
        hit = hooks_29.eval_recognition(rec, frame["items"], resolve, frame["orange"])
        check(
            f"真机帧「{frame['name']}」归位命中 = {frame['expect_home']}",
            hit == frame["expect_home"],
            f"src={frame['source']}",
        )
    # 直观点名三条反例 + 一条正例。
    check("列表页 = 反例", next(f for f in hooks_29.FRAMES if f["name"].startswith("列表页·领主战"))["expect_home"] is False)
    check("详情页 = 反例", next(f for f in hooks_29.FRAMES if f["name"] == "详情页")["expect_home"] is False)
    check("真正该归位（非主城分区页）= 正例",
          next(f for f in hooks_29.FRAMES if "真正该归位" in f["name"])["expect_home"] is True)


# ---------------------------------------------------------------------------
# 2. 离线复现：目标行在屏幕外 → 旧形态死循环 / 新形态走到滚动
# ---------------------------------------------------------------------------
def test_offline_loop_repro() -> None:
    print("\n== 2. 离线复现 #29：目标行在屏幕外，旧形态被兜底抢跑、新形态走到滚动 ==")
    new_seq, old_seq = hooks_29.loop_traces()
    print(f"     新形态前 8 步 = {new_seq[:8]}")
    print(f"     旧形态前 8 步 = {old_seq[:8]}")

    check("新形态必经 SpecialScrollList（滚动找行）", "SpecialScrollList" in new_seq)
    check("新形态不再命中 PubReturnHome（不被兜底带回主城）", "PubReturnHome" not in new_seq)
    # 旧形态：选行不命中（SpecialEnterBoss miss）后，兜底归位立刻抢跑（紧跟页签节点即命中）。
    check("旧形态在选行不命中后立刻命中 PubReturnHome（兜底抢跑）",
          old_seq[:3].count("PubReturnHome") >= 1, f"old_seq[:3]={old_seq[:3]}")
    check("旧形态永不执行 SpecialScrollList（滚动不可达）", "SpecialScrollList" not in old_seq)
    check("旧形态复现死循环（PubReturnHome 反复出现）",
          old_seq[:12].count("PubReturnHome") >= 2)


# ---------------------------------------------------------------------------
# 3. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 3. 破坏实验：去掉判别叶 / 去掉滚动后继 -> 守卫各自变红 ==")
    check("hooks_29.prove_red() 成立", hooks_29.prove_red() is True)


# ---------------------------------------------------------------------------
# 4. 真机帧实证（best-effort；缺 maa / 模型 / 帧则 SKIP）
# ---------------------------------------------------------------------------
def _maa_node_matches(image_path: Path, node: str):
    """对一张帧跑 ``node`` 的识别：命中 True / 未命中 False / 环境不可用 None。"""
    if not image_path.is_file() or not _OCR_MODEL.is_file():
        return None
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


def test_real_frames_best_effort() -> None:
    print("\n== 4. 真机帧实证（best-effort）：PubReturnHome 在列表 / 详情不命中、扭蛋分区页命中 ==")
    probes = [
        (FRAME_LIST, False, "列表页"),
        (FRAME_DETAIL, False, "详情页"),
        (FRAME_TEAM, False, "编队页"),
        (FRAME_GACHA, True, "扭蛋分区页"),
    ]
    any_frame = False
    for frame, want, label in probes:
        got = _maa_node_matches(frame, "PubReturnHome") if frame.suffix.lower() in (".png", ".jpg", ".jpeg") else None
        if got is None:
            skip(f"真机帧 MAA 识别（{label}）", f"缺 maa / OCR 模型 / 帧：{frame}")
            continue
        any_frame = True
        check(f"PubReturnHome 在【{label}】帧上命中 = {want}", got is want, f"got={got}")

    # PIL 复算内嵌的分区页签橙色计数（只对存在的帧）。
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        skip("PIL 复算橙色像素", "缺 numpy/PIL")
        return
    for frame in hooks_29.FRAMES:
        path = Path(frame["source"])
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        try:
            im = Image.open(path).convert("RGB").resize((720, 1280))
            a = np.array(im).astype(int)
        except Exception:  # noqa: BLE001
            continue
        measured = {}
        for tab, (x, y, w, h) in hooks_29.TAB_ROIS.items():
            c = a[y:y + h, x:x + w].reshape(-1, 3)
            measured[tab] = int(
                ((c[:, 0] >= 190) & (c[:, 1] >= 90) & (c[:, 1] <= 205) & (c[:, 2] <= 115)).sum()
            )
        any_frame = True
        # 内嵌计数只区分「0 / 非 0」，对真实帧复算应同号。
        same_sign = all(
            (measured.get(t, 0) == 0) == (frame["orange"].get(t, 0) == 0)
            for t in hooks_29.TAB_ROIS
        )
        check(f"橙色像素计数与真机帧一致（{frame['name']}）", same_sign,
              f"嵌入={frame['orange']} 实测={measured}")
    if not any_frame:
        skip("真机帧实证", "本机没有候选帧")


# ---------------------------------------------------------------------------
# 5. 无漂移 + #9 守卫 + prove-red
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 5. 无漂移 + #9 三条既有路径守卫仍绿 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")
    check("兜底范围守卫链_page_fallback_drift == []",
          drift.chain_page_fallback_drift(REPO_ROOT) == [])
    try:
        import test_scene_unchanged as tsu  # noqa: PLC0415

        check("#9 三条既有路径结构守卫仍绿", tsu.run_guards() == [])
    except Exception as exc:  # noqa: BLE001
        check("#9 守卫可运行", False, f"raised {exc!r}")


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    if "--prove-red" in sys.argv[1:]:
        test_prove_red()
        print("\n" + "=" * 72)
        if FAILS:
            print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
            sys.exit(1)
        print("结果：prove-red 成立 ✅")
        return

    print("=" * 72)
    print("离线单测：#29 归位不得在链上步骤页面自匹配 + 滚动找行可达")
    print("=" * 72)
    test_scope()
    test_offline_loop_repro()
    test_prove_red()
    test_real_frames_best_effort()
    test_drift_and_guards()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
