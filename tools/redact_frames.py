# -*- coding: utf-8 -*-
"""脱敏 E（#122）：遮盖随仓截图里的玩家 ID / 昵称 —— 可复现、幂等、只涂 PII 矩形。

票面：GitHub issue #122《脱敏 E：截图里的玩家 ID 全部遮盖 + 同步 OCR 侧车》。
审计依据（人可复核）见 ``docs/recon/frame-pii-audit.md``，本文件的 :data:`SPEC` 是它的机器版。

## 用法

    .venv\\Scripts\\python.exe tools\\redact_frames.py             # 按 SPEC 遮盖（幂等）
    .venv\\Scripts\\python.exe tools\\redact_frames.py --check     # 只读：逐框报告已涂/未涂，有遗漏则退出码 1
    .venv\\Scripts\\python.exe tools\\redact_frames.py --sha256    # 打印相关文件 sha256（幂等复核用）
    .venv\\Scripts\\python.exe tools\\redact_frames.py --check-sidecars   # 7 个 .ocr.txt 与图像逐条比对（需 maa）
    .venv\\Scripts\\python.exe tools\\redact_frames.py --ocr-report       # 重新 OCR，报告红区里仍可读的文本（需 maa）
    .venv\\Scripts\\python.exe tools\\redact_frames.py --out DIR           # 不就地改：写镜像副本（沙箱写不了工作区时用）
    .venv\\Scripts\\python.exe tools\\redact_frames.py --root DIR          # 换一棵镜像树当根（幂等演练用）

## 设计要点（为什么这样写）

1. **SPEC 是唯一事实源，坐标都是图像原生像素**。仓库里帧有两种分辨率（720x1280 / 1080x1920），
   MaaFramework 的 OCR 在原生分辨率下跑就返回原生像素框，所以这里不做任何缩放换算（换算会引入取整误差，
   涂偏 1~2 px 就会留下可读的字边）。坐标来历：全帧 OCR → 墨迹列切分定位昵称尾巴（把「级别158 + 昵称」
   这种合并框切成只含昵称的子框）→ 再用 3x 放大 OCR 回读该框，确认读出来就是昵称/ID。

2. **只涂 PII 矩形，外扩 PAD=4 px，纯黑 #000**。不整图涂黑，也不涂同行的等级/名次/贡献度
   （合并框里那部分由墨迹列切分排除）。

3. **幂等**：目标矩形已经全黑 ⇒ 该文件不写盘（连 PNG 重编码都不做）。所以连跑两次 sha256 不变，
   第二次连 mtime 都不会动。

4. **不猜着涂**：可疑但判不了的区域不进 SPEC；判成「非身份信息」的写进 :data:`NOT_REDACTED`（带判定与依据），
   审计过程与坐标在审计文档里。

## 注意

- 只碰图片；``.ocr.txt`` 侧车由 ``--check-sidecars`` 校验（见审计文档「侧车同步」一节）：
  本次 7 个侧车所在帧都不含 PII，重跑 OCR 与侧车逐条一致，因此侧车不需要改写。
- 本文件不含任何 PII 原文（昵称/ID 一律写成「账号A/账号B/玩家 ID」），避免脱敏脚本自己变成泄漏源。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
#: 遮盖矩形外扩像素（票面要求 4px）
PAD = 4
#: 遮盖色：纯黑
BLACK = (0, 0, 0)


@dataclass(frozen=True)
class Box:
    """一个 PII 矩形（图像原生像素）。"""

    kind: str  # "nickname" / "player_id"
    x: int
    y: int
    w: int
    h: int
    note: str

    def rect(self, pad: int = PAD) -> tuple[int, int, int, int]:
        """外扩后的 (x0, y0, x1, y1)（Pillow rectangle 的右/下边界是含的）。"""
        return (self.x - pad, self.y - pad, self.x + self.w + pad - 1, self.y + self.h + pad - 1)


#: 要遮盖的帧 -> 框。坐标均为该图像原生像素；来历见模块 docstring 与审计文档。
SPEC: dict[str, tuple[Box, ...]] = {
    # 主城 HUD 左上角昵称（账号A）
    "tools/frames/lord_home_city.png": (
        Box("nickname", 15, 110, 72, 42, "主城 HUD 昵称 账号A"),
    ),
    "tools/frames/coop_result_home.png": (
        Box("nickname", 15, 110, 72, 42, "主城 HUD 昵称 账号A"),
    ),
    # 共斗排名结算页：三行各一个昵称（行内「级别158」名次部分不涂，由墨迹列切分排除）
    "tools/frames/coop_result_rankings.png": (
        Box("nickname", 471, 1068, 82, 48, "排名第1行昵称 账号A"),
        Box("nickname", 471, 1290, 247, 42, "排名第2行昵称 账号C（他人）"),
        Box("nickname", 470, 1510, 163, 42, "排名第3行昵称 账号D（他人）"),
    ),
    # 共斗「战斗结束」页：两行各一个昵称（他人）
    "tools/frames/coop_result_dissolve.png": (
        Box("nickname", 501, 1168, 243, 42, "共斗结束第1行昵称 账号C（他人）"),
        Box("nickname", 500, 1406, 165, 42, "共斗结束第2行昵称 账号D（他人）"),
    ),
    # 账号B 的主城 HUD 昵称（同一位置、另一个账号）
    "tools/frames/session_error_a4050.png": (
        Box("nickname", 3, 116, 130, 28, "主城 HUD 昵称 账号B"),
    ),
    # 登录页右下角「ID:xxxxxxxxx」玩家 ID
    "tools/frames/server_unreachable.png": (
        Box("player_id", 857, 1802, 209, 40, "登录页玩家 ID"),
    ),
    # 同一登录底版的另一张（连接中）：本帧 OCR 在该槽位读到的是「请耐心等待」加载提示，
    # 没有 ID 字样；但底版/槽位与 server_unreachable 相同，按位置兜底遮盖（隐私优先，
    # 会连带涂掉那条提示的一部分 —— 见审计文档「兜底」一节）。
    "tools/frames/net_error_f2032.png": (
        Box("player_id", 857, 1802, 209, 40, "登录页 ID 槽位（本帧未读出，按同一底版坐标兜底）"),
    ),
    # screenshots/ 两张主城截图（同一账号A）
    "screenshots/phantom_before.png": (
        Box("nickname", 3, 112, 82, 36, "主城 HUD 昵称 账号A"),
    ),
    "screenshots/phantom_after.png": (
        Box("nickname", 3, 112, 82, 36, "主城 HUD 昵称 账号A"),
    ),
}

#: 审计过、**判定为非身份信息**因而故意不涂的区域（与审计文档同一份）。
#: 只在 --check 里打印判定，不参与遮盖。裁决人：票 #122 的 review（2026-10-18）。
NOT_REDACTED: tuple[tuple[str, tuple[int, int, int, int], str, str], ...] = (
    (
        "tools/frames/abyss_ex_team_page_A_team.png",
        (385, 1388, 315, 34),
        "非身份信息（队伍代码/装饰串）",
        "编成页同一位置两次放大 OCR 读成 'Q00101010101000' / 'Q000101010'，连稳定读数都做不到；形态是 Q 前缀长串、"
        "位于「代码」按钮行，不是玩家 ID（本账号玩家 ID 是 9 位纯数字，见 server_unreachable）→ 不涂",
    ),
    (
        "tools/frames/phantom_team_page_A.png",
        (383, 1392, 315, 30),
        "非身份信息（队伍代码/装饰串）",
        "同一元素的第二次读数 'O O 010101000 O'（同一位置、同一宽度），读数不稳定且带前导 0，不是玩家 ID 形态 → 不涂",
    ),
    (
        "tools/frames/maze57_head_on_maincity.png",
        (183, 6, 64, 26),
        "非身份信息（角色名）",
        "读作「杰拉德」；同一 720 空间画面上还有 拉夫马诺/魔王/星川莉莉/稻穗/莉莉丝（角色与武器名，见 "
        "docs/research/device-facts-2026-10-17.md §1.3 的编成页 OCR 原文），且它位于台词框上方（角色名），"
        "不是主城 HUD 的玩家昵称槽位 → 不涂",
    ),
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
#: 生效的根目录：默认仓库根；``--root`` 可指向一棵镜像树（演练用：证明「已涂过再跑一次不改变像素」）。
ACTIVE_ROOT = ROOT


def resolve(rel: str) -> Path:
    root = ACTIVE_ROOT
    p = (root / rel).resolve()
    if root not in p.parents:
        raise SystemExit(f"路径越界（不在根目录内）：{rel}")
    return p


def is_black(img: Image.Image, rect: tuple[int, int, int, int]) -> bool:
    """矩形内是否已经全是 #000（幂等判据）。"""
    x0, y0, x1, y1 = rect
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width - 1, x1), min(img.height - 1, y1)
    if x1 < x0 or y1 < y0:
        return True
    crop = img.crop((x0, y0, x1 + 1, y1 + 1)).convert("RGB")
    return crop.getextrema() == ((0, 0), (0, 0), (0, 0))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 三个模式
# ---------------------------------------------------------------------------
def cmd_apply(out_dir: Path | None = None) -> int:
    """按 SPEC 遮盖。``out_dir=None`` → 就地改；给了 ``out_dir`` → 写镜像副本（不碰原图）。

    ``out_dir`` 模式存在的原因：某些 sandbox（低完整性令牌）写不了工作区里的既有文件，
    这时可以先把涂好的副本生成到可写目录，再由能写的一方一条命令装回去（见末尾提示）。
    """
    changed, skipped, same = [], [], []
    for rel, boxes in SPEC.items():
        path = resolve(rel)
        if not path.is_file():
            print(f"!! 缺文件：{rel}")
            return 1
        img = Image.open(path)
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        todo = [b for b in boxes if not is_black(img, b.rect())]
        dst = (out_dir / rel) if out_dir is not None else path
        if not todo:
            skipped.append(rel)
            if out_dir is None:
                print(f"= {rel}: {len(boxes)} 框已全黑，跳过（不改像素、不重编码）")
            else:
                same.append(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                import shutil  # noqa: PLC0415

                shutil.copyfile(path, dst)  # 只复制字节，不 move（源图必须原封不动）
                print(f"= {rel}: 源图已全黑，原样复制 -> {dst}")
            continue
        draw = ImageDraw.Draw(img)
        for b in todo:
            draw.rectangle(b.rect(), fill=BLACK)
        before = path.stat().st_size
        if out_dir is not None:
            dst.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in (".jpg", ".jpeg"):
            img.save(dst, quality=95, subsampling=0)
        else:
            img.save(dst)
        after = dst.stat().st_size
        changed.append(rel)
        verb = "生成副本" if out_dir is not None else "涂黑"
        print(f"+ {rel}: {verb} {len(todo)}/{len(boxes)} 框（{before} -> {after} bytes -> {dst}）")
    print(f"\n结果：{('生成副本' if out_dir is not None else '涂黑')} {len(changed)} 张 / "
          f"跳过 {len(skipped)} 张（幂等）")
    if changed:
        print(("written: " if out_dir is not None else "changed: ") + ", ".join(changed))
    if out_dir is not None and changed:
        print("\n装回去（把镜像副本覆盖到仓库）：")
        for rel in changed:
            print(f'  Copy-Item -LiteralPath "{out_dir / rel}" -Destination "{resolve(rel)}" -Force')
    return 0


def cmd_check() -> int:
    bad = 0
    for rel, boxes in SPEC.items():
        path = resolve(rel)
        if not path.is_file():
            print(f"!! 缺文件：{rel}")
            bad += 1
            continue
        img = Image.open(path)
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        for b in boxes:
            ok = is_black(img, b.rect())
            if not ok:
                bad += 1
            print(f"{'OK ' if ok else 'XX '} {rel} {b.kind} rect={b.rect()} {b.note}")
    print("\n审计过、判定为非身份信息（故意不涂）:")
    for rel, rect, verdict, why in NOT_REDACTED:
        print(f"   ·  {rel} rect={rect} 判定={verdict}")
        print(f"      依据：{why}")
    print(f"\n结果：{'全部已遮盖' if bad == 0 else f'{bad} 个框未遮盖'}；SPEC 覆盖 {len(SPEC)} 张图 / "
          f"{sum(len(v) for v in SPEC.values())} 个框")
    return 0 if bad == 0 else 1


def cmd_sha256() -> int:
    for rel in SPEC:
        p = resolve(rel)
        print(f"{sha256(p)}  {rel}")
    return 0


# ---------------------------------------------------------------------------
# 需要 MaaFramework OCR 的复核模式（可选；缺 maa / 模型时明确 SKIP，不算失败）
# ---------------------------------------------------------------------------
def _ocr_engine():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import live_harness as lh  # noqa: PLC0415

        assets = ROOT / "assets" / "resource"
        if not (assets / "model" / "ocr" / "det.onnx").is_file():
            return None, "缺 OCR 模型 assets/resource/model/ocr/det.onnx"
        lh._ensure_ocr(assets)  # noqa: SLF001  提前把资源/模型加载失败暴露成 SKIP
        return lh, None
    except Exception as exc:  # noqa: BLE001
        return None, f"maa OCR 不可用：{exc!r}"


def _ocr_image(lh, pil: Image.Image, resize_720: bool = False):
    import numpy as np  # noqa: PLC0415

    if resize_720 and pil.size != (720, 1280):
        pil = pil.resize((720, 1280), Image.LANCZOS)
    return lh.ocr(np.ascontiguousarray(np.array(pil.convert("RGB"))[:, :, ::-1]), ROOT / "assets" / "resource")


def cmd_ocr_report() -> int:
    lh, err = _ocr_engine()
    if lh is None:
        print(f"SKIP --ocr-report：{err}")
        return 0
    problems = 0
    for rel, boxes in SPEC.items():
        path = resolve(rel)
        items = _ocr_image(lh, Image.open(path))
        hits = 0
        for b in boxes:
            x0, y0, x1, y1 = b.rect()
            area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
            leaks = []
            for t, bx in items:
                if not t:
                    continue
                ix0, iy0 = max(x0, bx[0]), max(y0, bx[1])
                ix1, iy1 = min(x1, bx[0] + bx[2] - 1), min(y1, bx[1] + bx[3] - 1)
                inter = max(0, ix1 - ix0 + 1) * max(0, iy1 - iy0 + 1)
                cx, cy = bx[0] + bx[2] / 2, bx[1] + bx[3] / 2
                box_area = max(1, bx[2] * bx[3])
                # 泄漏判据：文本中心落在红区内，或该文本自身 ≥75% 的面积被红区覆盖。
                # （红区是纯黑，涂干净后 OCR 不可能从红区里读出成规模的字；
                #   相邻行被 OCR 框的留白捎带到的低比例重叠，不算泄漏。）
                if (x0 <= cx <= x1 and y0 <= cy <= y1) or inter / box_area >= 0.75:
                    leaks.append((t, bx))
            if leaks:
                hits += 1
                problems += 1
                print(f"XX {rel} {b.kind} rect={b.rect()} 红区里仍可读到文本：{leaks}")
        print(f"{'OK ' if hits == 0 else '-- '} {rel}: OCR {len(items)} 条，{len(boxes)} 个红区"
              f"{'全部干净' if hits == 0 else f'，{hits} 处泄漏'}")
    print(f"\n结果：{'红区干净' if problems == 0 else f'{problems} 个红区仍有可读文本'}")
    return 0 if problems == 0 else 1


SIDECARS = (
    "abyss_zhongshi_tabs",
    "ark62_detail_unpairable",
    "stamina_insufficient_wuchong_a",
    "stamina_recovered_done_wuchong_a",
    "wuchong76_giveup_left_idle_fight",
    "wuchong76_manual_fight_working",
    "wuchong76_settle_giveup_after_fight",
)


def _parse_sidecar(path: Path) -> list[str]:
    """侧车里的文本行（两种格式都吃：``text\\t[x,y,w,h]`` 与 ``OCRResult(... text='..')``）。"""
    import re  # noqa: PLC0415

    tsv = re.compile(r"^(?P<text>.*?)\t\[[-\d,\s]+\]$")
    dump = re.compile(r"OCRResult\(box=\[[-\d,\s]+\], score=[\d.]+, text='(?P<text>.*)'\)$")
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = dump.match(line) or tsv.match(line)
        if m and m.group("text"):
            out.append(m.group("text"))
    return out


def cmd_check_sidecars() -> int:
    lh, err = _ocr_engine()
    if lh is None:
        print(f"SKIP --check-sidecars：{err}")
        return 0
    bad = 0
    for name in SIDECARS:
        png = resolve(f"tools/frames/{name}.png")
        side = resolve(f"tools/frames/{name}.ocr.txt")
        old = _parse_sidecar(side)
        pil = Image.open(png)
        fresh = [t for t, _b in _ocr_image(lh, pil, resize_720=True) if t]
        stale = [t for t in old if t not in fresh]
        added = [t for t in fresh if t not in old]
        status = "IN-SYNC" if not stale else "STALE"
        if stale:
            bad += 1
        print(f"{status:8s} {name}: 侧车 {len(old)} 条 / 重跑 {len(fresh)} 条；侧车有而图像没有 {len(stale)} 条；"
              f"图像有而侧车没有 {len(added)} 条")
        if stale:
            print(f"         侧车已过期（这些文本图像里读不到了，必须重写侧车）：{stale[:8]}")
    print(f"\n结果：{'7 个侧车与图像一致' if bad == 0 else f'{bad} 个侧车过期'}")
    return 0 if bad == 0 else 1


def main() -> int:
    global ACTIVE_ROOT
    ap = argparse.ArgumentParser(description="脱敏 E（#122）：遮盖截图里的玩家 ID / 昵称")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="只读检查：逐框报告已涂/未涂")
    g.add_argument("--sha256", action="store_true", help="打印 SPEC 内文件 sha256")
    g.add_argument("--check-sidecars", action="store_true", help="7 个 .ocr.txt 与图像逐条比对（需 maa）")
    g.add_argument("--ocr-report", action="store_true", help="重新 OCR，报告红区里仍可读到的文本（需 maa）")
    ap.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="不就地改：把涂好的镜像副本写到 DIR（给写不了工作区的 sandbox 用）",
    )
    ap.add_argument(
        "--root",
        default=None,
        metavar="DIR",
        help="改用另一棵镜像树当根（演练/校验幂等用；默认仓库根）",
    )
    args = ap.parse_args()
    if args.root:
        ACTIVE_ROOT = Path(args.root).resolve()
        print(f"root = {ACTIVE_ROOT}")
    if args.check:
        return cmd_check()
    if args.sha256:
        return cmd_sha256()
    if args.check_sidecars:
        return cmd_check_sidecars()
    if args.ocr_report:
        return cmd_ocr_report()
    return cmd_apply(Path(args.out).resolve() if args.out else None)


if __name__ == "__main__":
    raise SystemExit(main())
