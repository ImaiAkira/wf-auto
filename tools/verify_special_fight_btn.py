# -*- coding: utf-8 -*-
"""P0 离线证据：详情页点【战斗】= 点击点落在【战斗】框内、且不在【推荐编成】框内。

为什么这是硬证明
----------------
旧实现（已删）：`SpecialFightTargetRow` = OCR 难度标题 + `target_offset [-185,36]`，
`SpecialFightNewRow` = NEW 徽标 + `[60,110]`。战斗(103,509) 与 推荐编成(104,545)
只差 36px，标题/徽标框抖几像素就会点进【推荐编成】→ 改掉用户队伍配置（破坏性）。

新实现：custom `special_target_fight` 直接返回【战斗】按钮自己 OCR 出来的框，
点击 = 框中心、零偏移。本脚本拿真实详情页截图跑真实 OCR，断言：
    1) 返回框的【中心点】落在该【战斗】OCR 框内（不是别的行、更不是推荐编成）；
    2) 返回框与任何【推荐编成】框都不相交（box 无重叠）；
    3) 每个难度都配到“自己那一行”的战斗（按实测坐标，容差 30px）；
    4) 难度名 OCR 漏认时宁可 no-hit，绝不用偏移去猜。

用法：
    .venv\\Scripts\\python.exe tools\\verify_special_fight_btn.py [截图.png]
默认截图：<local>\\AppData\\Local\\Temp\\opencode\\done_detail.png
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]   # <repo> ; 不写死绝对路径，仓库整体搬迁也不失效
sys.path.insert(0, str(PROJECT / "agent"))

from maa.controller import CustomController  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

import side_impl  # noqa: E402

DEFAULT_SHOT = Path(str(TEMP_OPENCODE / "done_detail.png"))
SHOT = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SHOT

BATTLE_RE = r"^战斗$"
RECOMMEND_RE = r"^推荐编成$"

# done_detail.png 实测：难度名(720) → 该行【战斗】(720) 中心（OCR 后人工核对）。
EXPECT = {
    "高级\\+$": (103, 508),
    "高级$": (103, 699),
    "中级$": (102, 890),
}

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def center(box) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def inside(point, box, pad: float = 0.0) -> bool:
    x, y, w, h = box
    px, py = point
    return (x - pad) <= px <= (x + w + pad) and (y - pad) <= py <= (y + h + pad)


def boxes_overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


class ImageController(CustomController):
    def __init__(self, img):
        super().__init__()
        self.img = img

    def connect(self) -> bool:
        return True

    def request_uuid(self) -> str:
        return "0"

    def screencap(self):
        return self.img


class _FakeContext:
    """把真实 OCR 结果回放给自定义识别器（不产生任何点击）。"""

    def __init__(self, reco_detail):
        self._detail = reco_detail

    def run_recognition(self, entry, image):
        return self._detail


class _FakeArgv:
    def __init__(self, image, param: dict):
        self.image = image
        self.custom_recognition_param = __import__("json").dumps(param)


def load_720(path: Path):
    pil = Image.open(path).convert("RGB")
    if pil.width != 720:
        pil = pil.resize((720, round(pil.height * 720 / pil.width)), Image.LANCZOS)
    return np.ascontiguousarray(np.array(pil)[:, :, ::-1])


def capture_ocr(path: Path):
    """用 MaaFramework 的 OcrTask 真跑一遍截图，返回 (720图, OCR 结果列表)。"""
    Toolkit.init_option(str(PROJECT))
    img = load_720(path)
    ctrl = ImageController(img)
    ctrl.set_screenshot_use_raw_size(True)
    ctrl.post_connection().wait()
    res = Resource()
    assert res.post_bundle(str(PROJECT / "assets" / "resource")).wait().succeeded
    tasker = Tasker()
    tasker.bind(res, ctrl)
    job = tasker.post_task("OcrTask", {})
    job.wait()
    detail = job.get()
    assert detail is not None and detail.nodes, "OcrTask 没有返回结果"
    reco = detail.nodes[0].recognition
    items = []
    for r in (reco.all_results or []):
        b = getattr(r, "box", None)
        if b is None:
            continue
        b = [int(v) for v in b]
        if len(b) == 4:
            items.append(((getattr(r, "text", "") or "").strip(), b))
    return img, reco, items


def main() -> None:
    if not SHOT.is_file():
        print(f"截图不存在：{SHOT}")
        sys.exit(2)
    print("=" * 74)
    print(f"P0 离线证据：{SHOT.name}")
    print("=" * 74)

    img, reco_detail, items = capture_ocr(SHOT)
    ctx = _FakeContext(reco_detail)

    battles = [(t, b) for t, b in items if re.search(BATTLE_RE, t)]
    recommends = [(t, b) for t, b in items if re.search(RECOMMEND_RE, t)]

    print(f"\n== 真实 OCR 结果（720 空间）==")
    print(f"  识别总文本 {len(items)} 条；【战斗】{len(battles)} 个；【推荐编成】{len(recommends)} 个")
    for t, b in battles:
        print(f"    战斗   box={b} 中心={tuple(map(int, center(b)))}")
    for t, b in recommends:
        print(f"    推荐编成 box={b} 中心={tuple(map(int, center(b)))}")

    check("详情页识别到多个【战斗】(每行一个)", len(battles) >= 2, f"n={len(battles)}")
    check("详情页识别到【推荐编成】(页面门控词仍在)", len(recommends) >= 1, f"n={len(recommends)}")

    # ---- 1/2/3：逐个难度断言 ----
    print("\n== 逐个难度：custom special_target_fight 配到“自己那一行”的战斗 ==")
    rec = side_impl.SpecialTargetFightRecognition()
    for difficulty, exp_center in EXPECT.items():
        r = rec.analyze(ctx, _FakeArgv(img, {"difficulty": difficulty}))
        box = r.box
        if box is None:
            check(f"{difficulty}: 命中并返回战斗框", False, f"detail={r.detail}")
            continue
        box = [int(v) for v in box]
        pt = center(box)

        # 1) 返回框必须就是某个【战斗】框（精确相等）
        is_battle = any(box == b for _t, b in battles)
        # 2) 返回框与所有【推荐编成】框都不相交
        no_overlap = all(not boxes_overlap(box, b) for _t, b in recommends)
        # 3) 点击点落在该战斗框内 且 不在任何推荐编成框内
        pt_in_battle = inside(pt, box, pad=0.5)
        pt_in_rec = any(inside(pt, b, pad=0.0) for _t, b in recommends)
        # 4) 配到“自己那一行”（实测坐标，容差 30）
        dx = abs(pt[0] - exp_center[0])
        dy = abs(pt[1] - exp_center[1])
        matched = dx <= 30 and dy <= 30

        check(f"{difficulty}: 返回框 = 某个战斗 OCR 框", is_battle, f"box={box}")
        check(f"{difficulty}: 与所有推荐编成框无重叠", no_overlap)
        check(f"{difficulty}: 点击点在战斗框内", pt_in_battle, f"point={tuple(map(int, pt))}")
        check(f"{difficulty}: 点击点不在推荐编成框内", not pt_in_rec)
        check(f"{difficulty}: 配到本难度行 {exp_center}", matched,
              f"picked={tuple(map(int, pt))} (dx={dx:.0f},dy={dy:.0f})")

    # ---- 4：漏认难度名 → no-hit（绝不猜） ----
    print("\n== 容错：难度名 OCR 漏认时宁可 no-hit ==")
    r = rec.analyze(ctx, _FakeArgv(img, {"difficulty": "初级$"}))
    check("初级$（该行名本图未被 OCR 识别到）→ 不命中、不猜偏移",
          r.box is None, f"box={r.box} detail={r.detail}")

    # ---- 5：无难度参数 → 取最上面的战斗（NEW 行永远在最上面） ----
    print("\n== 无难度参数：取最上面的【战斗】(未通关行在最上面) ==")
    top_box, detail = side_impl.pick_target_battle_box(items, None)
    top_y = center(top_box)[1] if top_box else None
    min_y = min(center(b)[1] for _t, b in battles)
    check("返回最上面的战斗框", top_box is not None and abs(top_y - min_y) < 1,
          f"picked_y={top_y} min_y={min_y}")
    check("该框与推荐编成无重叠",
          all(not boxes_overlap(top_box, b) for _t, b in recommends))

    # ---- 6：对照——旧“死偏移”会点到错误的行 ----
    print("\n== 对照：旧实现（标题 + (-185,+36) 死偏移）的落点 ==")
    old_hits_wrong = 0
    for difficulty, exp_center in EXPECT.items():
        names = [b for t, b in items if re.search(difficulty, t)]
        if not names:
            continue
        ncx, ncy = center(names[0])
        old_pt = (ncx - 185, ncy + 36)
        # 旧落点是否落在“错的”战斗框里（即不在自己这行的框内）
        own = [b for _t, b in battles if inside(old_pt, b)]
        own_ok = any(
            abs(center(b)[0] - exp_center[0]) <= 30 and abs(center(b)[1] - exp_center[1]) <= 30
            for b in own
        )
        print(f"    {difficulty}: 标题中心≈({ncx:.0f},{ncy:.0f}) 旧落点≈"
              f"({old_pt[0]:.0f},{old_pt[1]:.0f}) 落进的战斗框="
              f"{[tuple(map(int, center(b))) for b in own]} 是否本行={own_ok}")
        if own and not own_ok:
            old_hits_wrong += 1

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅（点击点恒在【战斗】框内，绝不在【推荐编成】框内）")


if __name__ == "__main__":
    main()
