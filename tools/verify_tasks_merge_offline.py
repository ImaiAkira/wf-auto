# -*- coding: utf-8 -*-
"""离线回归：SpecialEntry 分派器「改动前 vs 改动后」首命中对比（真 OCR，无需游戏）。

用途
----
把「重复刷图 / 战阵之宴」吸收进 SpecialEntry 后，必须保证：清单为空、入口为
SpecialEntry 时，分派行为与合并前【完全一致】。本脚本对一组 fixture 截图跑
SpecialEntry 的 next 分派一轮（除入口外所有节点覆盖成 DoNothing+next=[]，不点击），
打印首命中节点 + OCR 文本，可用 --project 指向 baseline worktree 做逐图 diff。

用法（项目根目录）：
    .venv\\Scripts\\python.exe tools\\verify_tasks_merge_offline.py \
        --project . --images b1.png,stage_list.png,chk_16384.png

    # baseline 对比（git worktree 拉到临时目录后）
    .venv\\Scripts\\python.exe tools\\verify_tasks_merge_offline.py --project <baseline>
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import argparse
import sys
from pathlib import Path

TMP = Path(str(TEMP_OPENCODE))


def load_img(path: Path):
    import numpy as np
    from PIL import Image

    pil = Image.open(path).convert("RGB")
    if pil.width != 720:
        pil = pil.resize((720, round(pil.height * 720 / pil.width)), Image.LANCZOS)
    return np.ascontiguousarray(np.array(pil)[:, :, ::-1])


class ImageController:
    """按 project 的 maa CustomController 动态构造，避免 import 顺序问题。"""

    def __new__(cls, img):
        from maa.controller import CustomController

        class _C(CustomController):
            def __init__(self, image):
                super().__init__()
                self.img = image

            def connect(self) -> bool:
                return True

            def request_uuid(self) -> str:
                return "0"

            def screencap(self):
                return self.img

        return _C(img)


def register_customs(res, si) -> list[str]:
    names = []
    for attr, kind in [
        ("NextStageRecognition", "next_stage"),
        ("NoListBadgeRecognition", "no_list_badge"),
        ("ListAllDoneRecognition", "list_all_done"),
        ("PageDoneRepeatRecognition", "page_done_repeat"),
        ("StallRecoverRecognition", "stall_recover"),
        ("SpecialBatchPlanRecognition", "special_batch_plan"),
        ("SpecialTargetFightRecognition", "special_target_fight"),
        ("BatchModeRecognition", "batch_mode"),
    ]:
        cls = getattr(si, attr, None)
        if cls is not None:
            res.register_custom_recognition(kind, cls())
            names.append(kind)
    for attr, kind in [
        ("MarkDoneAction", "mark_done"),
        ("SpecialBatchFightAction", "special_batch_fight"),
        ("SpecialBatchFinishAction", "special_batch_finish"),
    ]:
        cls = getattr(si, attr, None)
        if cls is not None:
            res.register_custom_action(kind, cls())
    return names


def collect_names(pipe_dir: Path) -> list[str]:
    import jsonc

    names: list[str] = []
    for f in sorted(pipe_dir.glob("*.json")):
        d = jsonc.load(open(f, encoding="utf-8"))
        if isinstance(d, dict):
            names += list(d.keys())
    return names


def run_first_hit(tasker, entry: str, all_nodes: list[str]):
    override = {
        n: {"action": {"type": "DoNothing", "param": {}}, "next": []}
        for n in all_nodes
        if n != entry
    }
    job = tasker.post_task(entry, override)
    job.wait()
    detail = job.get()
    hits = []
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--entry", default="SpecialEntry")
    ap.add_argument("--images", default="b1.png,stage_list.png,chk_16384.png")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    agent = project / "agent"
    sys.path.insert(0, str(agent))

    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    import side_impl as si  # noqa: E402

    resource_dir = project / "assets" / "resource"
    pipe_dir = resource_dir / "pipeline"

    Toolkit.init_option(str(project))
    res = Resource()
    ok = res.post_bundle(str(resource_dir)).wait().succeeded
    print(f"# project={project}")
    print(f"# resource load={ok}")
    if not ok:
        sys.exit(1)
    regd = register_customs(res, si)
    print(f"# custom recognitions registered: {regd}")
    all_nodes = collect_names(pipe_dir)

    for img_name in [s.strip() for s in a.images.split(",") if s.strip()]:
        img_path = TMP / img_name
        if not img_path.exists():
            print(f"  [MISS] {img_name}")
            continue
        ctrl = ImageController(load_img(img_path))
        ctrl.set_screenshot_use_raw_size(True)
        ctrl.post_connection().wait()
        tasker = Tasker()
        tasker.bind(res, ctrl)
        hits = run_first_hit(tasker, a.entry, all_nodes)
        first = next((n for n, _t in hits if n != a.entry), None)
        txt = next((t for n, t in hits if n != a.entry), "")
        print(f"  {img_name}: first={first!r} text={txt!r} seq={hits}")


if __name__ == "__main__":
    main()
