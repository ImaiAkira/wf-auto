# -*- coding: utf-8 -*-
"""外传「账本驱动选关」离线验证（真 OCR + 生产同款纯函数，无需游戏 / agent 进程）。

做什么
------
1. 加载项目的 pipeline 资源，用新增的 `OcrTask` 节点对截图做**真实 OCR**；
2. 用 stage_rows.parse_side_rows + stage_rows.select_side_stage（= agent/my_reco.py
   里 next_stage 调用的同一份纯函数）挑关，打印命中框 / 未命中；
3. 用 pipeline 里的现有节点（PubSkipStory / SideSkipConfirmText / SideSkipConfirmBtn
   / SideNewCharTap）直接跑识别，报告是否命中（action 覆盖为 DoNothing，不产生点击）。
   ★注★：跳过剧情原 SideSkipStory 已在概念收敛中删除，改为公共节点 common.PubSkipStory；
   「挑战」原 SideChallenge 已删除，改为 common.PubChallenge（见下方分派回归的负样本名单）。

为什么不用 verify_entry.py 跑自定义识别节点
------------------------------------------
verify_entry.py 走的是「进程内 Resource + Tasker」，而 agent 的自定义识别器是通过
MaaAgentServer 注册的；一旦 import agent 模块，native 库会切到 MaaAgentServer，
`Resource()` 直接创建失败（实测）。所以这里保持「纯函数 + 真 OCR」的验证方式，
和生产共用 select_side_stage，不会与运行逻辑分叉。

用法:
    python tools/verify_side_offline.py
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
AGENT = PROJECT / "agent"
TMP = Path(str(TEMP_OPENCODE))
sys.path.insert(0, str(AGENT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from maa.controller import CustomController  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

import jsonc  # noqa: E402

import progress as ledger  # noqa: E402
import stage_rows as sr  # noqa: E402

PIPE_DIR = PROJECT / "assets" / "resource" / "pipeline"


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


def load_img(path: Path) -> np.ndarray:
    pil = Image.open(path).convert("RGB")
    if pil.width != 720:
        pil = pil.resize((720, round(pil.height * 720 / pil.width)), Image.LANCZOS)
    return np.ascontiguousarray(np.array(pil)[:, :, ::-1])


def bind(res: Resource, path: Path) -> Tasker:
    ctrl = ImageController(load_img(path))
    ctrl.set_screenshot_use_raw_size(True)
    ctrl.post_connection().wait()
    tasker = Tasker()
    tasker.bind(res, ctrl)
    return tasker


def ocr_items(tasker: Tasker) -> list[tuple[str, list[int]]]:
    job = tasker.post_task("OcrTask", {})
    job.wait()
    detail = job.get()
    items = []
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        for r in reco.all_results or []:
            box = getattr(r, "box", None)
            if box is None:
                continue
            items.append(((getattr(r, "text", "") or "").strip(), [int(v) for v in box]))
    return items


def run_node(tasker: Tasker, name: str) -> bool:
    job = tasker.post_task(name, {name: {"action": {"type": "DoNothing", "param": {}}, "next": []}})
    job.wait()
    detail = job.get()
    if detail is None:
        return False
    for node in detail.nodes:
        reco = node.recognition
        if reco is not None and reco.hit:
            best = getattr(reco, "best_result", None)
            txt = (getattr(best, "text", "") or "") if best is not None else ""
            print(f"      >>> 命中 {name}  OCR='{txt}'")
            return True
    print(f"      --- 未命中 {name}")
    return False


def collect_names() -> list[str]:
    """收集 pipeline 里所有节点名（用于把非入口节点覆盖成 DoNothing + next=[]）。"""
    names: list[str] = []
    for f in sorted(PIPE_DIR.glob("*.json")):
        d = jsonc.load(open(f, encoding="utf-8"))
        if isinstance(d, dict):
            names += list(d.keys())
    return names


def first_hit(tasker: Tasker, entry: str, all_nodes: list[str]) -> list[tuple[str, str]]:
    """跑入口的 next 分派一轮，返回命中的 [(节点名, OCR文本), ...]。

    除入口外所有节点的 action 覆盖成 DoNothing、next 清空（不产生任何点击），
    这样 MaaFramework 只会执行入口 next 里【第一个命中】的节点。
    """
    override = {
        n: {"action": {"type": "DoNothing", "param": {}}, "next": []}
        for n in all_nodes
        if n != entry
    }
    job = tasker.post_task(entry, override)
    job.wait()
    detail = job.get()
    hits: list[tuple[str, str]] = []
    if detail is None:
        return hits
    for node in detail.nodes:
        reco = node.recognition
        if reco is None or not reco.hit:
            continue
        best = getattr(reco, "best_result", None)
        txt = (getattr(best, "text", "") or "") if best is not None else ""
        hits.append((getattr(node, "name", "?"), txt))
    return hits


FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> None:
    Toolkit.init_option(str(PROJECT))
    res = Resource()
    ok = res.post_bundle(str(PROJECT / "assets" / "resource")).wait().succeeded
    print("resource load:", ok)
    if not ok:
        print("!!! pipeline 加载失败")
        sys.exit(1)

    # ★把 side_impl 的自定义识别/动作注册到进程内 Resource★（离线也能跑 next_stage /
    #   no_list_badge / list_all_done / stall_recover / mark_done，与生产同一份实现）。
    import side_impl  # noqa: E402
    res.register_custom_recognition("next_stage", side_impl.NextStageRecognition())
    res.register_custom_recognition("no_list_badge", side_impl.NoListBadgeRecognition())
    res.register_custom_recognition("list_all_done", side_impl.ListAllDoneRecognition())
    res.register_custom_recognition("page_done_repeat", side_impl.PageDoneRepeatRecognition())
    res.register_custom_recognition("stall_recover", side_impl.StallRecoverRecognition())
    res.register_custom_action("mark_done", side_impl.MarkDoneAction())
    print("已注册 side_impl 自定义识别/动作 (next_stage / no_list_badge / list_all_done / page_done_repeat / stall_recover / mark_done)")

    # ============ 1. ax6.png：关卡列表 + 账本选拔 ============
    ax6 = TMP / "ax6.png"
    print("\n" + "=" * 74)
    print("1. ax6.png（百兽王冠 关卡列表：剧情行 前往圣地 + 战斗行 秘宝之力）")
    print("=" * 74)
    tasker = bind(res, ax6)
    items = ocr_items(tasker)
    print(f"   OcrTask 真实 OCR 得到 {len(items)} 条")
    rows = sr.parse_side_rows(items)
    scope = sr.detect_scope(items)
    print(f"   自动识别副本名 scope = {scope!r}")
    for r in rows:
        print(f"     - {r['name']!r:24} type={r['type']!r:8} badge={r['badge']!r:12} box={r['title_box']}")

    check("解析出 3 行", len(rows) == 3)
    check("scope 自动识别为 百兽王冠", scope == "百兽王冠", f"got={scope!r}")

    tmpdir = Path(tempfile.mkdtemp(prefix="wf_verify_"))
    pfile = tmpdir / "progress.json"

    def pick(row_type, done_names, check_badge=True):
        led = ledger.Progress(pfile)
        led.reset()
        for n in done_names:
            led.mark_done(ledger.make_key("side_story", scope or "百兽王冠", n))
        return sr.select_side_stage(
            rows,
            row_type_regex=row_type,
            check_badge=check_badge,
            is_done=lambda n: led.is_done(ledger.make_key("side_story", scope or "百兽王冠", n)),
        )

    r = pick("特殊战斗", [])
    check("空账本：剧情行节点 -> 前往圣地", r is not None and r["name"] == "前往圣地",
          f"box={r['title_box'] if r else None}")

    r = pick("特殊战斗", ["前往圣地"])
    check("账本已记 前往圣地：剧情行节点 -> None（不会重复长按）", r is None)

    # 负样本（关键）：账本已记 秘宝之力 完成 -> 战斗节点不得命中
    r = pick("战斗", ["秘宝之力"], check_badge=False)
    check("★负样本：账本已记 秘宝之力：战斗节点 -> None（防重复打同一关）", r is None)

    r_before = pick("战斗", [], check_badge=False)
    check("反证：同样条件下账本为空时战斗节点本会命中 秘宝之力",
          r_before is not None and r_before["name"] == "秘宝之力",
          f"box={r_before['title_box'] if r_before else None}")

    r = pick("战斗", [], check_badge=True)
    check("默认防线：秘宝之力画面已标 COMPLETE!! -> 战斗节点 -> None", r is None)

    r = pick("STORY", [])
    check("STORY 行节点 -> 提欧与玛格诺斯（画面 COMPLETE 被挡时 -> None 亦可接受）",
          r is None or r["name"] == "提欧与玛格诺斯", f"got={r['name'] if r else None}")

    # ============ 2. cs0 / cs1 / cs3：剧情流程现有节点 ============
    print("\n" + "=" * 74)
    print("2. 剧情流程节点（pipeline 现有 SideSkip* / SideNewCharTap，真 OCR）")
    print("=" * 74)
    print("   cs0.png（剧情页）")
    t0 = bind(res, TMP / "cs0.png")
    check("PubSkipStory 命中剧情页「跳过」", run_node(t0, "PubSkipStory"))

    print("   cs1.png（跳过确认框）")
    t1 = bind(res, TMP / "cs1.png")
    hit_txt = run_node(t1, "SideSkipConfirmText")
    hit_btn = run_node(t1, "SideSkipConfirmBtn")
    check("SideSkipConfirmText 命中「点击【跳过】」", hit_txt)
    check("SideSkipConfirmBtn 命中「跳过」按钮", hit_btn)

    print("   cs3.png（新角色画面）")
    t3 = bind(res, TMP / "cs3.png")
    check("SideNewCharTap 命中大 NEW 徽标", run_node(t3, "SideNewCharTap"))

    # ============ 3. 分派回归：本页全清出口（需求 #1 核心）============
    print("\n" + "=" * 74)
    print("3. 分派回归：SideClearEntry 首命中（真 OCR + 生产同款自定义识别）")
    print("=" * 74)
    # next_stage 会写 pending，用临时账本文件，别污染正式 progress.json。
    ledger.set_file(pfile)
    names = collect_names()

    print("   stuck1.png（大海遗产 关卡列表：4 个 COMPLETE!!，无 NEW）")
    hits = first_hit(bind(res, TMP / "stuck1.png"), "SideClearEntry", names)
    print(f"      命中序列: {hits}")
    first = next((n for n, _t in hits if n != "SideClearEntry"), None)
    check("★全清页首命中 = SidePageDone（本页全清出口）", first == "SidePageDone", f"got={first!r}")
    check("全清页绝不命中任何选关/战斗节点",
          not any(n in ("SideNextSpecial", "SideNextStory", "SideNextBattle",
                        "SideStoryNode", "SideEnter", "SideFight", "PubChallenge")
                  for n, _t in hits),
          f"hits={hits}")

    print("   ax6.png（百兽王冠 关卡列表：NEW 前往圣地 + 2 个 COMPLETE）")
    hits2 = first_hit(bind(res, TMP / "ax6.png"), "SideClearEntry", names)
    print(f"      命中序列: {hits2}")
    first2 = next((n for n, _t in hits2 if n != "SideClearEntry"), None)
    check("★含 NEW 的列表仍能选关（首命中为选关/进入节点，不是 SidePageDone）",
          first2 in ("SideNextSpecial", "SideNextStory", "SideNextBattle",
                     "SideStoryNode", "SideEnter"),
          f"got={first2!r}")
    check("含 NEW 的列表不得命中 SidePageDone",
          "SidePageDone" not in [n for n, _t in hits2], f"hits={hits2}")

    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
