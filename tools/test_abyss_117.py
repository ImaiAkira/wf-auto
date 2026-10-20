# -*- coding: utf-8 -*-
"""#117：深渊终始之战「页签校验自证 + 空态不收工」—— 离线正负例 + 端到端（零设备）。

    .venv\\Scripts\\python.exe tools\\test_abyss_117.py

三块：

1. **入库证据帧正例**：``tools/frames/abyss_zhongshi_tabs.png``（真机 384，2026-10-18 08:0x，
   终始之战页，中间写「没有相关的活动」）必须被识别为**空态**。两条路各证一次：
   * 侧车 ``.ocr.txt``（入库的 720 空间 OCR）→ ``classify`` = zhongshi + ``has_empty_anchor`` = True；
   * **真跑一次 MaaFramework OCR**（``OcrTask``，帧缩放到 720 基准空间）→ 同一个结论
     （缺 maa / OCR 模型时 SKIP，不算失败 —— 与 ``test_gameover_match`` 同一口径）。
2. **负例**：一屏**有内容**的终始之战帧不得被判空态。★诚实交代★：入库帧里没有任何一张
   **有内容**的终始之战页（已扫 ``tools/frames/`` 全部帧），所以这条负例按
   ``docs/recon/abyss-calibration.md`` 对 ``04_zhongshi_tab_wancheng.png`` 的读数**合成**
   （横幅 + 剩余天数），不冒充真机帧；另外用两张**随仓真机帧**（领主战列表 / 外传故事列表）
   证「空态锚点不会随便假阳」。
3. **端到端**：三个页签全空时，真实 ``AbyssActAction`` 点满三个页签后请求收工，真实
   ``AbyssGiveUpRecognition`` 把原因报出来 —— 原因就是给运维的那一句话。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
for _p in (str(TOOLS), str(ROOT), str(ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from contract_hooks import hooks_117 as h117  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []

_ASSETS = ROOT / "assets" / "resource"


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print(f"  [SKIP] {name}  ({why})")
    SKIPS.append(name)


def _impl():
    return h117._impl()


def _maa_ocr(frame: Path):
    """对随仓帧真跑一次 MAA OCR（720 空间）；缺 maa / 模型 / 帧 → None（SKIP）。"""
    if not frame.is_file():
        return None
    if not (_ASSETS / "model" / "ocr" / "det.onnx").is_file():
        return None
    try:
        import numpy as np
        from PIL import Image

        import live_harness as ca
    except Exception:  # noqa: BLE001
        return None
    try:
        pil = Image.open(frame).convert("RGB")
        if pil.size != (720, 1280):
            pil = pil.resize((720, 1280), Image.LANCZOS)
        img = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
        return ca.ocr(img, _ASSETS)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# 1. 入库证据帧 = 空态（侧车 + 真 OCR 两条路）
# ---------------------------------------------------------------------------
def test_evidence_frame_is_empty() -> None:
    print("\n== 1. 入库证据帧：abyss_zhongshi_tabs.png 必须被识别为「空态」 ==")
    impl = _impl()
    scene_abyss = h117._scene()

    check("证据帧入库", h117.EVIDENCE_FRAME.is_file(), str(h117.EVIDENCE_FRAME.relative_to(ROOT)))
    check("证据帧侧车入库", h117.EVIDENCE_OCR.is_file(), str(h117.EVIDENCE_OCR.relative_to(ROOT)))
    items = h117.EMPTY_FRAME
    check("侧车读得出 OCR 项", len(items) >= 8, f"n={len(items)}")

    anchor = str(scene_abyss.ZHONGSHI_EMPTY_ANCHOR)
    hits = [(t, b) for t, b in items if anchor in t]
    check(f"侧车里读到空态锚点 {anchor!r}", len(hits) == 1, f"{hits!r}")
    check("证据帧 classify = zhongshi", impl.classify(items)[0] == "zhongshi", impl.classify(items)[0])
    check("证据帧 has_empty_anchor = True", impl.has_empty_anchor(items, anchor) is True)
    sig = impl.content_signature(items)
    check("内容区签名只剩空态锚点（页签栏/底导带都被排除）", sig == (anchor,), f"{sig!r}")

    # 真跑一次 MAA OCR：侧车 != 现算的话，说明帧/侧车/模型三者漂了。
    real = _maa_ocr(h117.EVIDENCE_FRAME)
    if real is None:
        skip("真机帧真 OCR（空态）", "缺 maa / OCR 模型 det.onnx / 帧")
    else:
        state, _ = impl.classify(real)
        check("真 OCR：证据帧 classify = zhongshi", state == "zhongshi", state)
        check("真 OCR：证据帧 has_empty_anchor = True", impl.has_empty_anchor(real, anchor) is True)
        check(
            "真 OCR：证据帧内容区签名 = (空态锚点,)",
            impl.content_signature(real) == (anchor,),
            f"{impl.content_signature(real)!r}",
        )
        have = {t for t, _b in real}
        want = {t for t, _b in items}
        missing = sorted(want - have)
        check("真 OCR 与侧车一致（侧车不是手写的）", missing == [], f"缺={missing[:4]}")


# ---------------------------------------------------------------------------
# 2. 负例：有内容的终始之战帧 / 其它随仓帧不得判空态
# ---------------------------------------------------------------------------
def test_populated_not_empty() -> None:
    print("\n== 2. 负例：有内容的终始之战帧不得被判空态 ==")
    impl = _impl()
    populated = h117._content_tab_frame()
    anchor = impl.ZHONGSHI_EMPTY_ANCHOR
    check("有内容帧 has_empty_anchor = False", impl.has_empty_anchor(populated, anchor) is False)
    check("有内容帧 classify = zhongshi", impl.classify(populated)[0] == "zhongshi")
    check(
        "有内容帧的内容区签名 != 空态帧签名",
        impl.content_signature(populated) != impl.content_signature(h117.EMPTY_FRAME),
        f"{impl.content_signature(populated)!r}",
    )
    # 内容区若被写窄（比如把横幅行排除掉），这条就会红 —— 它在钉「内容区覆盖横幅行」。
    banner = [b for t, b in populated if t == "深渊连战"][0]
    cy = banner[1] + banner[3] / 2.0
    box = impl.ZHONGSHI_CONTENT_BOX
    check(f"横幅行中心 y={cy:.0f} 落在内容区 {box} 内", box[1] <= cy <= box[3])

    print("  —— 随仓真机帧（非终始之战页）不得被认成空态 ——")
    for name in ("lord_page_tab_lord.png", "side_story_list.png"):
        frame = ROOT / "tools" / "frames" / name
        real = _maa_ocr(frame)
        if real is None:
            skip(f"真 OCR：{name}", "缺 maa / OCR 模型 det.onnx / 帧")
            continue
        check(f"{name}: 不判空态", impl.has_empty_anchor(real, anchor) is False)
        check(f"{name}: 不判 zhongshi", impl.classify(real)[0] != "zhongshi", impl.classify(real)[0])


# ---------------------------------------------------------------------------
# 3. 端到端：三页签全空 ⇒ 那句话就是给运维的收工原因
# ---------------------------------------------------------------------------
def test_empty_giveup_end_to_end() -> None:
    print("\n== 3. 端到端：三个页签全空 ⇒ 走 abyss_giveup 收工（原因给运维） ==")
    impl = _impl()
    pipes = h117._pipeline()
    param = h117._tab_param(pipes)
    tabs = h117._tabs_of(impl, param)

    h117._reset_session(impl)
    with h117._sandbox(impl):
        screen = h117._TabScreen(
            {name: h117._empty_tab_frame() for name in tabs}, start=tabs[-1]
        )
        clicks, log, reason = h117._drive(impl, screen, param, max_runs=len(tabs) + 3)
        check("三页签各点一次就停", len(clicks) == len(tabs), f"clicks={len(clicks)}")
        check("收工原因 = 真源那句话", reason == impl.ZHONGSHI_EMPTY_REASON, f"{reason!r}")
        check(
            "原因文案就是给运维的那句",
            reason == "终始之战没有可打的关卡（三个页签均无内容）",
            f"{reason!r}",
        )
        check("三个页签都记了空态", sorted(impl._SESSION["tab_empty"]) == sorted(tabs))
        check("日志里有『请求收工』", "请求收工" in log)

        # 真实 giveup 识别：把原因取走并打用户可见那一行。
        with impl._LOCK:
            impl._SESSION["giveup_reason"] = reason
        saved = impl._ocr
        impl._ocr = lambda context, image, entry="OcrTask": list(h117._empty_tab_frame())
        try:
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()) as buf:
                got = impl.AbyssGiveUpRecognition().analyze(
                    h117._CtxStub(), h117._RecoArgv({"empty_anchor": impl.ZHONGSHI_EMPTY_ANCHOR})
                )
        finally:
            impl._ocr = saved
        detail = getattr(got, "detail", None) or {}
        check("abyss_giveup 命中", getattr(got, "box", None) == [0, 0, 0, 0], f"{getattr(got, 'box', None)!r}")
        check("abyss_giveup 报出的原因一致", detail.get("reason") == reason, f"{detail.get('reason')!r}")
        check("用户可见行 =『[abyss] 收工 —— <原因>』", "收工 —— 终始之战没有可打的关卡" in buf.getvalue())
        check(
            "写了收工标记（下一轮清账）",
            impl.ledger.is_done(f"{impl._cfg().ledger_scope}/run/completed") is True,
        )


# ---------------------------------------------------------------------------
# 4. 守卫接线（三条都在聚合器里，别只活在文件里）
# ---------------------------------------------------------------------------
def test_hooks_wired() -> None:
    print("\n== 4. 守卫接线：hooks_117 的三条挂点都被 discover_hooks 收进来 ==")
    from contract_hooks import discover_hooks

    ids = {hook_id for hook_id, _t, _w, _p in discover_hooks()}
    for hook_id in (
        "abyss-tab-switch-observable",
        "abyss-tab-retry-capped",
        "abyss-zhongshi-empty-giveup",
    ):
        check(f"挂点 {hook_id} 被发现", hook_id in ids)
    check("三条守卫探针都绿", all(p() is True for _i, _t, _w, p in h117.HOOKS))


def main() -> int:
    print("=" * 74)
    print("#117：终始之战页签校验（内容区变化）+ 空态收工（没有相关的活动）—— 离线正负例")
    print("=" * 74)
    test_evidence_frame_is_empty()
    test_populated_not_empty()
    test_empty_giveup_end_to_end()
    test_hooks_wired()
    print("\n" + "=" * 74)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 -> {FAILS}")
        return 1
    print("test_abyss_117: ALL PASS ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
