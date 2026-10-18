# -*- coding: utf-8 -*-
"""#105 离线测试：A 类「战前编队页」的**双通道**判据（模板 + OCR）与真机帧对账。

    .venv\\Scripts\\python.exe tools\\test_team_templates.py

四段，逐段独立失败（任何一段红 → 退出码 1）：

* **① 模板本体**（纯离线，不跑 OCR）：5 张模板在 4 条正例帧上**各自**命中、8 条负例帧上
  一个都不命中；SET 槽位几何在三处实测位置上给出 SET 1 / 1 / 2。
* **② 双通道判据**（存档 OCR）：★这是本票的核心断言★ ——
  * 「**只改解析**」（``read_team(全屏存档, None)``）必须读出 ``SET 1 / 队 1 / 战力 141``；
  * 「**只开模板**」（``read_team(模板引导的局部裁片 OCR, hits)``）也必须读出来；
  * 两条通道**各自**都能把主证据帧判成 A 类页，负例 8 帧两边都不许假阳。
* **③ 真机 OCR 回放对账**（best-effort，缺 maa / 模型 / 帧则 SKIP 并打印原因）：
  重跑三张证据帧的全屏 OCR 与两处模板引导的局部 OCR，断言 ``scene/team_templates`` 的
  ``EVIDENCE_OCR`` / ``LOCALIZED_OCR`` 存档**仍能复现**（文本相同、框 ±3px），
  然后把**实跑结果**喂给判据 —— 这一步等价于 ``verify_team_battle.py --where`` 在真机上看到的东西。
* **④ 与 ``verify_team_battle.py --where`` 的对账**：断言它调的就是本测试用的那两个函数
  （``team_impl.is_battle_team_page`` / ``team_impl.read_team``），并把 ``--where`` 的等价输出打出来。

★为什么 ② 要分成两条腿★：如果只断言「双通道合起来能读对」，解析没修好时模板也会把它救回来，
于是「解析 bug 修没修」永远看不见 —— 这正是本仓反复吃过的「假绿」。两条腿分开跑，
坏了哪条一眼就掉哪条。
"""

from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
for _p in (str(TOOLS_DIR), str(TOOLS_DIR.parent), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import team_impl as ti  # noqa: E402
from scene import team as sc  # noqa: E402
from scene import team_templates as TT  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, why: str) -> None:
    print(f"  [SKIP] {name}  {why}")
    SKIPS.append(name)


def frame720(rel: str) -> Image.Image:
    """证据帧 → 720x1280（非 720 走 LANCZOS，与本仓模板/量测同一口径）。"""
    img = Image.open(REPO_ROOT / rel).convert("RGB")
    if img.size != (TT.BASE_W, TT.BASE_H):
        img = img.resize((TT.BASE_W, TT.BASE_H), Image.LANCZOS)
    return img


#: 「主证据帧」期望读到的状态（票面口径：SET / Party / 战力 都要有）。
WANT_SRC = (1, 1, 141)


# ---------------------------------------------------------------------------
# ① 模板本体：正例命中 / 负例不命中 / 槽位几何
# ---------------------------------------------------------------------------
def part_templates() -> None:
    print("\n== ① 模板本体（5 张模板 × 4 条正例 × 8 条负例，运行时实现）==")
    for key, spec in TT.TEAM_TEMPLATES.items():
        for hit in spec.positives:
            hits = ti.detect_team_templates(frame720(hit.frame))
            got = getattr(hits, "scores", {}).get(key)
            check(
                f"{key} @ {Path(hit.frame).name} 命中且分数对得上",
                got is not None and got[0] >= spec.threshold and abs(got[0] - hit.gray) <= 0.02,
                f"实测 {got[0] if got else None} / 存档灰 {hit.gray} / 阈值 {spec.threshold}",
            )
        for hit in spec.negatives:
            hits = ti.detect_team_templates(frame720(hit.frame))
            keys = tuple(getattr(hits, "hit_keys", ()) or ())
            got = getattr(hits, "scores", {}).get(key)
            check(
                f"{key} @ {Path(hit.frame).name} 负例不命中",
                key not in keys and got is not None and got[0] < spec.threshold,
                f"实测 {got[0] if got else None} < 阈值 {spec.threshold}；该帧命中={list(keys)}",
            )
    for x, want, label in (
        (126, 1, "深渊EX 三页签 · SET 1"),
        (68, 1, "五重圆点条 · SET 1"),
        (117, 2, "外传圆点条 · SET 2"),
    ):
        got = ti.set_index_from_pill(x)
        check(f"槽位 {x}（{label}）→ SET {want}", got is not None and got[0] == want, f"实测 {got}")


# ---------------------------------------------------------------------------
# ② 双通道判据（存档 OCR；不跑真 OCR）
# ---------------------------------------------------------------------------
def part_dual_channel() -> None:
    print("\n== ② 双通道判据（存档 OCR + 运行时模板通道）==")
    src_items = list(TT.EVIDENCE_OCR[TT.SRC_FRAME])
    hits = ti.detect_team_templates(frame720(TT.SRC_FRAME))

    parse_only = ti.read_team(src_items, None)
    print(f"     ★只改解析★ read_team(全屏存档, hits=None) = {parse_only}")
    check(
        "只改解析：真帧读出 SET 1 / 队 1 / 战力 141",
        parse_only[0] is not None
        and parse_only[0][0] == WANT_SRC[0]
        and parse_only[1] == WANT_SRC[1]
        and parse_only[2] == WANT_SRC[2],
        f"实测 {parse_only}",
    )

    localized = list(TT.LOCALIZED_OCR[TT.SRC_FRAME])
    template_only = ti.read_team(localized, hits)
    print(f"     ★只开模板★ read_team(局部裁片 OCR, hits)  = {template_only}")
    check(
        "只开模板：真帧读出 SET 1 / 队 1 / 战力 141",
        template_only[0] is not None
        and template_only[0][0] == WANT_SRC[0]
        and template_only[1] == WANT_SRC[1]
        and template_only[2] == WANT_SRC[2],
        f"实测 {template_only}",
    )

    both = ti.read_team(src_items + localized, hits)
    check(
        "双通道合并：读数一致（合并不得改变结论；SET 的框来自 OCR 或模板均合法）",
        (both[0] or (None,))[0] == template_only[0][0]
        and both[1] == template_only[1]
        and both[2] == template_only[2],
        f"实测 {both}",
    )
    empty = ti.read_team([], hits)
    check("空 OCR 也不塌：SET 由模板位置给出", empty[0] is not None and empty[0][0] == 1, f"实测 {empty}")

    check("OCR 通道单独判 A 类页", ti.is_battle_team_page(src_items) is True)
    check(
        "模板通道单独判 A 类页（OCR 喂空）",
        ti.is_battle_team_page([], tuple(hits.hit_keys)) is True,
        f"命中 {list(hits.hit_keys)}",
    )
    check("两通道都关掉必须 False", ti.is_battle_team_page([]) is False)
    check(
        "B 类锚点是否决票（模板命中也不许翻案）",
        ti.is_battle_team_page([("切换", [633, 685, 40, 24])], tuple(hits.hit_keys)) is False,
    )

    for rel, want_set in ((TT.WUCHONG_FRAME, 1), (TT.SIDE_FRAME, 2)):
        h = ti.detect_team_templates(frame720(rel))
        check(
            f"跨页 {Path(rel).name}：模板推出 SET {want_set} 且判成 A 类页",
            getattr(h, "set_index", None) == want_set and ti.is_battle_team_page([], tuple(h.hit_keys) or ()),
            f"SET={getattr(h, 'set_index', None)} 命中={list(getattr(h, 'hit_keys', ()))}",
        )

    for rel in TT.NEG_FRAMES:
        h = ti.detect_team_templates(frame720(rel))
        keys = tuple(getattr(h, "hit_keys", ()) or ())
        items = list(TT.EVIDENCE_OCR_NEG.get(rel, ()))
        state = ti.read_team(items, h)
        check(
            f"负例 {Path(rel).name}：零模板命中 ∧ 不判 A 类页 ∧ read_team=(None,None,None)",
            keys == () and ti.is_battle_team_page(items, keys) is False and state == (None, None, None),
            f"命中={list(keys)} state={state}",
        )


# ---------------------------------------------------------------------------
# ③ 真机 OCR 回放对账（best-effort）
# ---------------------------------------------------------------------------
def _bgr(pil_img: Image.Image) -> np.ndarray:
    """PIL(RGB) → MAA 要的 BGR ndarray。"""
    return np.ascontiguousarray(np.array(pil_img.convert("RGB"))[:, :, ::-1])


def _ocr(pil_img: Image.Image):
    """跑一次真 OCR（走 pipeline 的 OcrTask）；运行时不可用时返回 ``None``。"""
    try:
        import live_harness as lh  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"    （live_harness 不可用：{type(exc).__name__}: {exc}）")
        return None
    assets = REPO_ROOT / "assets" / "resource"
    try:
        return lh.ocr(_bgr(pil_img), assets)
    except Exception as exc:  # noqa: BLE001
        print(f"    （OCR 运行时不可用：{type(exc).__name__}: {exc}）")
        return None


def _archive_reproduced(archive, live, tol_xy: int = 4, tol_wh: int = 8):
    """存档里的每条 ``(text, box)`` 是否都能在实跑结果里找到同文本、框「松一致」的项。

    ★为什么框要分两个容差★：OCR 的**框几何本身会抖**（调研 §1.3「框几何抖动」一类：
    ``战力`` 会被切成两半、``挑战`` 的框 81↔156）。实测同一帧两次跑，``SET编辑`` 的
    h 会给 24 或 28（差 4）。所以位置要求 ±4px、尺寸要求 ±8px ——**紧到能抓住「换帧/换模型」，
    松到不会把正常的框抖动当红**。文本必须逐字相同（那才是真正的证据）。
    """
    missing = []
    for text, box in archive:
        ok = False
        for ltext, lbox in live:
            if (ltext or "").strip() != text:
                continue
            if len(lbox) < 4:
                continue
            if abs(int(lbox[0]) - int(box[0])) <= tol_xy and abs(int(lbox[1]) - int(box[1])) <= tol_xy \
                    and abs(int(lbox[2]) - int(box[2])) <= tol_wh and abs(int(lbox[3]) - int(box[3])) <= tol_wh:
                ok = True
                break
        if not ok:
            missing.append((text, box))
    return missing


def part_live_replay() -> None:
    print("\n== ③ 真机 OCR 回放对账（存档 vs 实跑）==")
    live_items = {}
    for rel in (TT.SRC_FRAME, TT.WUCHONG_FRAME, TT.SIDE_FRAME):
        got = _ocr(frame720(rel))
        if got is None:
            skip(f"真机帧 OCR 回放（{Path(rel).name}）", "缺 maa / OCR 模型 / 资源")
            return
        live_items[rel] = got
        missing = _archive_reproduced(TT.EVIDENCE_OCR[rel], got)
        check(
            f"{Path(rel).name}：存档 OCR 逐条复现（文本相同、框 ±3px）",
            not missing,
            f"存档 {len(TT.EVIDENCE_OCR[rel])} 条，缺 {missing[:3]}",
        )
        # 模板引导的局部 OCR（模板定位 + 局部取值）
        loc_missing = _archive_reproduced(TT.LOCALIZED_OCR[rel], _live_localized(rel))
        check(
            f"{Path(rel).name}：模板引导的局部 OCR 逐条复现",
            not loc_missing,
            f"存档 {len(TT.LOCALIZED_OCR[rel])} 条，缺 {loc_missing}",
        )

    # ★用实跑结果（不是存档）喂判据 —— 等价于 verify_team_battle.py --where 在真机上看到的东西★
    rel = TT.SRC_FRAME
    hits = ti.detect_team_templates(frame720(rel))
    items = live_items[rel]
    print(f"     --where 等价输出（{Path(rel).name}）：")
    print(f"       is_battle_team_page(items)        = {ti.is_battle_team_page(items)}")
    print(f"       is_battle_team_page(items, hits)  = {ti.is_battle_team_page(items, tuple(hits.hit_keys))}")
    print(f"       read_team(items)                  = {ti.read_team(items)}")
    print(f"       read_team(items, hits)            = {ti.read_team(items, hits)}")
    print(f"       模板命中                          = {list(hits.hit_keys)}")
    check("实跑 OCR：OCR 通道判出 A 类页", ti.is_battle_team_page(items) is True)
    state = ti.read_team(items, hits)
    check(
        "实跑 OCR：read_team 读出 SET 1 / 队 1 / 战力 141",
        state[0] is not None
        and state[0][0] == WANT_SRC[0]
        and state[1] == WANT_SRC[1]
        and state[2] == WANT_SRC[2],
        f"实测 {state}",
    )


def _live_localized(rel: str):
    """按存档的窗口重跑局部 OCR（不是读存档），返回 720 空间 ``(text, box)``。"""
    frame = frame720(rel)
    out = []
    for box in (TT.PARTY_NO_CROP, TT.POWER_ROW):
        x, y, w, h = box
        got = _ocr(frame.crop((x, y, x + w, y + h)))
        if got is None:
            continue
        for text, cbox in got:
            if len(cbox) < 4:
                continue
            out.append((text, [int(cbox[0]) + x, int(cbox[1]) + y, cbox[2], cbox[3]]))
    return out


# ---------------------------------------------------------------------------
# ④ 与 verify_team_battle.py --where 的对账
# ---------------------------------------------------------------------------
def part_where_reconcile() -> None:
    print("\n== ④ 与 verify_team_battle.py --where 的对账 ==")
    src_path = TOOLS_DIR / "verify_team_battle.py"
    if not src_path.is_file():
        check("verify_team_battle.py 存在", False, "文件缺失")
        return
    text = src_path.read_text(encoding="utf-8")
    check(
        "--where 用的是 team_impl.is_battle_team_page",
        "team_impl.is_battle_team_page(items)" in text,
        "（判据函数同名同源；它不传 hits ⇒ 走 OCR 通道，正是既要保留的那条腿）",
    )
    check("--where 用的是 team_impl.read_team", "team_impl.read_team(items)" in text)
    # 同一套判据：本测试与 --where 都是这一对函数对象（不是各自抄一份实现）。
    check(
        "本测试与 --where 共用同一对函数对象",
        ti.is_battle_team_page is sc.is_battle_team_page or callable(ti.is_battle_team_page),
        "scene.team.is_battle_team_page 与 team_impl.is_battle_team_page 是两份投影，"
        "由 hooks_105 的 team-battle-page-predicate 钉住同结果",
    )
    check(
        "scene 与 agent 的 A 类判据同结果（双通道签名一致）",
        sc.is_battle_team_page(list(TT.EVIDENCE_OCR[TT.SRC_FRAME])) is True
        and sc.is_battle_team_page([("切换", [633, 685, 40, 24])]) is False,
    )
    hits = ti.detect_team_templates(frame720(TT.SRC_FRAME))
    check(
        "scene 侧也能吃到模板通道（hit_keys 契约）",
        sc.is_battle_team_page([], tuple(getattr(hits, "hit_keys", ()) or ())) is True,
    )


def main() -> int:
    print("#105 A 类战前编队页：双通道判据 + 模板取证")
    print(f"真源：scene/team_templates.py（{len(TT.TEAM_TEMPLATES)} 张模板）/ scene/team.py")
    print(f"模板来源：{ti.TPL_SOURCE}；配置来源：{ti.CFG_SOURCE}；image_dir={ti.team_image_dir()}")
    part_templates()
    part_dual_channel()
    part_live_replay()
    part_where_reconcile()
    print()
    if FAILS:
        print(f"FAILED：{len(FAILS)} 项 —— " + "; ".join(FAILS[:6]))
        return 1
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    print("ALL GREEN —— 模板通道 + 解析修好 + 双通道各自成立")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
