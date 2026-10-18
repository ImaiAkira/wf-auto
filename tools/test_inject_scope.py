# -*- coding: utf-8 -*-
"""离线单测：#37 通用不变量「任何被注入的事件都不得命中链上步骤页面」+ 复现 + prove-red。

不需要游戏 / 设备（判据全在内嵌的**真机帧模型** + 列表屏状态机上）；真机帧 MAA 回放是
best-effort（缺 maa / OCR 模型 / 帧则 SKIP，不算失败）。直接跑：

    .venv\\Scripts\\python.exe tools\\test_inject_scope.py
    .venv\\Scripts\\python.exe tools\\test_inject_scope.py --prove-red

覆盖 #37 的验收：

  1. **通用不变量**（#18/#29/#37 的共同教训）：遍历 ``scene.events`` 里每个被注入的事件
     节点，在每张**链上步骤页真机帧**上求值——命中即红（唯一合法豁免：事件与链步同判据，
     会点名打印）。
  2. **#37 判据级正反例**：``PubNewCharTap`` 在**降临讨伐列表页**（含行 NEW 徽标）真机帧上
     **不命中**；在**真正该弹「新角色」**的大 NEW 徽标帧上**命中**。
  3. **离线复现本循环**（确定性）：屏幕 = 降临讨伐列表页。旧形态（ROI ``[0,800,400,340]``）
     → ``PubNewCharTap`` 抢跑、打开别人的详情页、**到不了目标详情**（循环到上限）；新形态
     （真实产物）→ 不命中、``SpecialEnterBoss`` 选目标行 → **到达目标详情**。
  4. **破坏实验**：改坏 ``PubNewCharText`` ROI → 守卫红；去掉归位判别叶（#29）→ 守卫红。
  5. **真机帧 MAA 回放（best-effort）**：对真实列表 / 详情 / 主城帧跑 ``PubNewCharTap``，
     断言不命中；对按设备实测大 NEW 徽标合成的帧，断言命中；缺 maa / 模型 / 帧则 SKIP。
  6. **无漂移 + #9 守卫仍绿 + 链上步骤页面都在全局判据注册表里**。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_37.py``。
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
from scene.page_rules import CHAIN_STEP_PAGES, chain_step_pages, page_rule, page_rules  # noqa: E402

import hooks_37  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

# 真机帧证据（#37；缺则 best-effort 段 SKIP）。
_JO = Path(os.environ.get("WF_R37_JO", str(TEMP_OPENCODE / "sweepjoss/recon_02_list_joss.png")))
_LO = Path(os.environ.get("WF_R37_LO", str(TEMP_OPENCODE / "sweepjoss/recon_01_list_lord.png")))
_DE = Path(os.environ.get("WF_R37_DE", str(TEMP_OPENCODE / "sweepjoss/recon_03_detail.png")))
_MC = Path(os.environ.get("WF_R37_MC", str(TEMP_OPENCODE / "sweepjoss/recon_00_maincity.png")))
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
    return drift.load_pipelines(REPO_ROOT / "assets" / "resource" / "pipeline")


# ---------------------------------------------------------------------------
# 1. 通用不变量：任何被注入事件 × 链上步骤页真机帧
# ---------------------------------------------------------------------------
def test_injected_events_guard() -> None:
    print("\n== 1. 通用不变量：被注入事件 ∩ 链上步骤页面 = ∅（真机帧模型） ==")
    check("挂点 injected-events-not-on-chain-pages 点亮（probe=True）",
          hooks_37.probe_injected_events_not_on_chain_pages() is True)

    files = _files()
    resolve = hooks_37._resolver(files)
    from scene.events import injected_event_nodes

    nodes = injected_event_nodes()
    check("被注入事件节点非空（枚举自 scene.events）", bool(nodes), f"nodes={list(nodes)}")

    print(f"     被注入事件 {len(nodes)} 个 × 链上步骤页帧 {len(hooks_37.CHAIN_PAGE_FRAMES)} 张：")
    checked = 0
    for node in nodes:
        rec = drift._resolve_recognition(node, files)
        for frame in hooks_37.CHAIN_PAGE_FRAMES:
            hit = hooks_37.eval_recognition(rec, frame["items"], resolve, frame["orange"])
            if not hit:
                continue
            exempt = hooks_37._exemption(files, node, frame["page"])
            checked += 1
            check(f"事件 {node} vs「{frame['name']}」：命中但" + ("同判据豁免" if exempt else "必须不命中"),
                  exempt is not None, exempt or "（应报红）")
    print(f"     （共 {checked} 处事件-页面命中，均需同判据豁免）")


# ---------------------------------------------------------------------------
# 2. #37 判据级正反例
# ---------------------------------------------------------------------------
def test_criterion_scope() -> None:
    print("\n== 2. #37 判据正反例：列表页不命中 / 大 NEW 徽标页命中 ==")
    check("挂点 new-char-tap-not-on-list 点亮（probe=True）",
          hooks_37.probe_new_char_criterion_scope() is True)

    files = _files()
    resolve = hooks_37._resolver(files)
    rec = drift._resolve_recognition("PubNewCharTap", files)

    for frame in hooks_37._LIST_FRAMES:
        hit = hooks_37.eval_recognition(rec, frame["items"], resolve, frame["orange"])
        check(f"反例帧「{frame['name']}」（含行 NEW 徽标）不命中", hit is False,
              f"src={frame['source']}")
    pos = hooks_37.NEWCHAR_POSITIVE_FRAME
    check(f"正例帧「{pos['name']}」命中",
          hooks_37.eval_recognition(rec, pos["items"], resolve, pos["orange"]) is True,
          f"src={pos['source']}")

    # 判据绑定的 ROI 必须与 pipeline 一致（防止产品改了、夹具没跟上）。
    newchar = drift._resolve_recognition("PubNewCharText", files) or {}
    roi = (newchar.get("param") or {}).get("roi")
    check("PubNewCharText 的 ROI 已收窄（左边界 > 0，不再圈住行小 NEW 徽标）",
          isinstance(roi, list) and roi[0] > 0, f"roi={roi}")


# ---------------------------------------------------------------------------
# 3. 离线复现本循环
# ---------------------------------------------------------------------------
def test_loop_repro() -> None:
    print("\n== 3. 离线复现 #37：列表页自匹配 → 打开别人的详情 → 到不了目标详情 ==")
    (new_reached, new_seq), (old_reached, old_seq) = hooks_37.loop_traces()
    print(f"     新形态到达目标详情={new_reached} 前 10 步={new_seq[:10]}")
    print(f"     旧形态到达目标详情={old_reached} 前 10 步={old_seq[:10]}")

    check("新形态不命中 PubNewCharTap（不在列表页抢跑）", "PubNewCharTap" not in new_seq)
    check("新形态经 SpecialEnterBoss 选目标行", "SpecialEnterBoss" in new_seq)
    check("新形态到达目标详情", new_reached is True)
    check("旧形态命中 PubNewCharTap（列表页抢跑）", "PubNewCharTap" in old_seq)
    check("旧形态到不了目标详情（循环到上限）", old_reached is False)
    check("旧形态复现循环（SpecialEntry 反复出现）", old_seq.count("SpecialEntry") >= 5)


# ---------------------------------------------------------------------------
# 4. 破坏实验
# ---------------------------------------------------------------------------
def test_prove_red() -> None:
    print("\n== 4. 破坏实验：改坏 #37 判据 / 去掉 #29 判别叶 -> 守卫各自变红 ==")
    check("hooks_37.prove_red() 成立", hooks_37.prove_red() is True)


# ---------------------------------------------------------------------------
# 5. 真机帧 MAA 回放（best-effort）
# ---------------------------------------------------------------------------
def _maa_matches(image_path: Path, node: str):
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


def _synth_big_new(path: Path) -> bool:
    """按设备实测大 NEW 徽标 box≈(13,845,252,153) 合成一帧；缺 PNG 支持则 False。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:  # noqa: BLE001
        return False
    try:
        im = Image.new("RGB", (720, 1280), (255, 255, 255))
        dr = ImageDraw.Draw(im)
        font = None
        _win = os.environ.get("WINDIR", r"C:\Windows")  # 不写死 `盘符:\Windows\Fonts\...`（脱敏 B 类）
        for candidate in tuple(os.path.join(_win, "Fonts", f) for f in ("arialbd.ttf", "msyhbd.ttc", "simhei.ttf")):
            if Path(candidate).is_file():
                for size in range(200, 60, -4):
                    f = ImageFont.truetype(candidate, size)
                    l, t, r, b = dr.textbbox((0, 0), "NEW", font=f)
                    if (r - l) <= 252:
                        font = f
                        break
                if font is not None:
                    dr.text((13 - l + 6, 845 - t + 20), "NEW", font=font, fill=(20, 20, 20))
                    break
        if font is None:
            return False
        im.save(path)
        return True
    except Exception:  # noqa: BLE001
        return False


def test_real_frames_best_effort() -> None:
    print("\n== 5. 真机帧 MAA 回放（best-effort）：PubNewCharTap 列表不命中、大 NEW 帧命中 ==")
    negatives = [(_JO, "降临讨伐列表页"), (_LO, "领主战列表页"), (_DE, "详情页"), (_MC, "主城")]
    any_frame = False
    for frame, label in negatives:
        got = _maa_matches(frame, "PubNewCharTap")
        if got is None:
            skip(f"真机帧 MAA 回放（{label}）", f"缺 maa / OCR 模型 / 帧：{frame}")
            continue
        any_frame = True
        check(f"PubNewCharTap 在【{label}】帧上不命中", got is False, f"got={got}")

    synth = Path(os.environ.get("WF_R37_SYNTH", str(TEMP_OPENCODE / "sweepjoss/synth_big_new.png")))
    if not synth.is_file():
        synth.parent.mkdir(parents=True, exist_ok=True)
        if not _synth_big_new(synth):
            skip("大 NEW 徽标帧合成", "缺 PIL / 字体")
            synth = None
    if synth is not None:
        got = _maa_matches(synth, "PubNewCharTap")
        if got is None:
            skip("真机帧 MAA 回放（大 NEW 徽标正例）", "缺 maa / OCR 模型")
        else:
            any_frame = True
            check("PubNewCharTap 在大 NEW 徽标（正例）帧上命中", got is True, f"got={got}")
    if not any_frame:
        skip("真机帧 MAA 回放", "本机没有 maa + OCR 模型 + 候选帧")


# ---------------------------------------------------------------------------
# 6. 无漂移 + #9 守卫 + 页面注册表
# ---------------------------------------------------------------------------
def test_drift_and_guards() -> None:
    print("\n== 6. 无漂移 + #9 守卫仍绿 + 链上步骤页都在全局判据注册表 ==")
    msgs = drift.check_all(repo_root=REPO_ROOT)
    check("真实树无漂移（check_all == []）", msgs == [], f"drift={msgs[:2]}")

    names = {r.name for r in page_rules()}
    missing = [p for p in CHAIN_STEP_PAGES if p not in names]
    check("CHAIN_STEP_PAGES 每个名字都在 PAGE_RULES 里（绝不静默）", missing == [], f"missing={missing}")
    check("chain_step_pages() 与常量一致", tuple(chain_step_pages()) == CHAIN_STEP_PAGES)
    check("主城 是链上步骤页（#18）", page_rule("主城").name in CHAIN_STEP_PAGES)
    check("详情页 是链上步骤页（#29）", page_rule("详情页").name in CHAIN_STEP_PAGES)

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
    print("离线单测：#37 通用不变量「被注入事件 ∩ 链上步骤页面 = ∅」+ 复现 + prove-red")
    print("=" * 72)
    test_injected_events_guard()
    test_criterion_scope()
    test_loop_repro()
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
