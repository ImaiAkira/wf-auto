# -*- coding: utf-8 -*-
"""离线回归：幻想连战「合并前 vs 合并后」分派首命中对比（真 OCR，无需游戏）。

用途
----
把「自动刷幻想」并入「自动刷副本」(SpecialEntry) 后，必须保证：给定同一帧幻想画面，
**幻想状态机链上第一个命中的业务节点与合并前完全一致**（即 PhantomDispatch.next 与
原 PhantomEntry.next 逐项等价）。

做法
----
对 ph_test1 目录下每张真机帧截图跑一次分派（除分派链本身外，所有节点覆盖成
DoNothing+next=[]，不点击、不动作），打印「第一个命中的分派目标节点」。

  · baseline（f091c90）：entry=PhantomEntry，直接命中 PhantomEntry.next 里的节点；
  · 合并后：entry=PhantomEntry（别名→SpecialEntry），把 SpecialEntry.next 收敛成
    ["PhantomDispatch"]，命中 PhantomDispatch.next 里的节点。
  两者都只走「分派表」，故可直接逐图 diff。

用法（项目根目录，两个 worktree 各跑一次后 diff）：
    .venv\\Scripts\\python.exe tools\\verify_phantom_merge_offline.py \
        --project <worktree> --out <out.txt>

    # 只跑前 N 张（快速自检）：
    .venv\\Scripts\\python.exe tools\\verify_phantom_merge_offline.py --project . --limit 8
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import argparse
import sys
from pathlib import Path

TMP = Path(str(TEMP_OPENCODE))
DEFAULT_IMAGES_DIR = TMP / "ph_test1"


def load_img(path: Path):
    import numpy as np
    from PIL import Image

    pil = Image.open(path).convert("RGB")
    if pil.width != 720:
        pil = pil.resize((720, round(pil.height * 720 / pil.width)), Image.LANCZOS)
    return np.ascontiguousarray(np.array(pil)[:, :, ::-1])


class ImageController:
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


def register_customs(res, si, ph) -> list[str]:
    names = []
    for attr, kind in [
        ("StallRecoverRecognition", "stall_recover"),
        ("SpecialBatchPlanRecognition", "special_batch_plan"),
        ("BatchModeRecognition", "batch_mode"),
    ]:
        cls = getattr(si, attr, None)
        if cls is not None:
            res.register_custom_recognition(kind, cls())
            names.append(kind)
    for attr, kind in [
        ("PhantomStateRecognition", "phantom_state"),
        ("PhantomDoneRecognition", "phantom_done"),
        ("PhantomGiveUpRecognition", "phantom_giveup"),
    ]:
        cls = getattr(ph, attr, None)
        if cls is not None:
            res.register_custom_recognition(kind, cls())
            names.append(kind)
    for attr, kind in [
        ("PhantomActAction", "phantom_act"),
        ("PhantomRestartAction", "phantom_restart"),
        ("SpecialBatchFightAction", "special_batch_fight"),
        ("SpecialBatchFinishAction", "special_batch_finish"),
        ("MarkDoneAction", "mark_done"),
    ]:
        cls = getattr(ph, attr, None) or getattr(si, attr, None)
        if cls is not None:
            res.register_custom_action(kind, cls())
    return names


def load_pipelines(pipe_dir: Path) -> dict:
    import jsonc

    nodes: dict = {}
    for f in sorted(pipe_dir.glob("*.json")):
        d = jsonc.load(open(f, encoding="utf-8"))
        if isinstance(d, dict):
            nodes.update(d)
    return nodes


def dispatch_names(nodes: dict) -> list[str]:
    """取本次分派表：合并后看 PhantomDispatch.next，合并前看 PhantomEntry.next。"""
    if isinstance(nodes.get("PhantomDispatch"), dict):
        return list(nodes["PhantomDispatch"].get("next") or [])
    return list(nodes.get("PhantomEntry", {}).get("next") or [])


def build_override(keep: dict, all_nodes: list[str]) -> dict:
    override = {
        n: {"action": {"type": "DoNothing", "param": {}}, "next": []}
        for n in all_nodes
        if n not in keep
    }
    # keep 里可带「节点→覆盖」的额外收敛（如把 SpecialEntry.next 收成 [PhantomDispatch]）。
    for n, ov in keep.items():
        if ov is not None:
            override[n] = ov
    return override


def run_first_hit(tasker, entry: str, override: dict):
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
    ap.add_argument("--images-dir", default=str(DEFAULT_IMAGES_DIR))
    ap.add_argument("--entry", default="PhantomEntry")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 张（0=全部）")
    ap.add_argument("--stride", type=int, default=1, help="每隔 N 张取一张（抽样加速）")
    ap.add_argument("--out", default="", help="把结果写到该文件")
    ap.add_argument("--verbose", action="store_true", help="打印每张图的完整命中序列")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    agent = project / "agent"
    sys.path.insert(0, str(agent))

    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    import phantom_impl as ph  # noqa: E402
    import side_impl as si  # noqa: E402

    resource_dir = project / "assets" / "resource"
    pipe_dir = resource_dir / "pipeline"

    Toolkit.init_option(str(project))
    res = Resource()
    ok = res.post_bundle(str(resource_dir)).wait().succeeded
    lines: list[str] = []
    lines.append(f"# project={project}")
    lines.append(f"# resource load={ok}")
    if not ok:
        print("\n".join(lines))
        sys.exit(1)
    regd = register_customs(res, si, ph)
    lines.append(f"# custom registered: {regd}")

    nodes = load_pipelines(pipe_dir)
    dnames = dispatch_names(nodes)
    lines.append(f"# dispatch nodes ({len(dnames)}): {dnames}")
    dset = set(dnames)

    # keep：entry 必留；合并后额外保留 SpecialEntry（收敛 next）与 PhantomDispatch。
    keep: dict = {a.entry: None}
    if "PhantomDispatch" in nodes:
        keep["SpecialEntry"] = {"next": ["PhantomDispatch"]}
        keep["PhantomDispatch"] = None
    lines.append(f"# keep={list(keep)}")

    all_nodes = list(nodes.keys())
    override = build_override(keep, all_nodes)

    images = sorted(Path(a.images_dir).glob("ph_run_s*.png"))
    if a.stride and a.stride > 1:
        images = images[:: a.stride]
    if a.limit:
        images = images[: a.limit]
    lines.append(f"# images={len(images)}")

    # 复用同一个 controller/tasker：每张图只换 img，省掉反复建连接的开销。
    ctrl = ImageController(load_img(images[0]))
    ctrl.set_screenshot_use_raw_size(True)
    ctrl.post_connection().wait()
    tasker = Tasker()
    tasker.bind(res, ctrl)

    matched = 0
    total = 0
    for img_path in images:
        ctrl.img = load_img(img_path)
        hits = run_first_hit(tasker, a.entry, override)
        first = next((n for n, _t in hits if n in dset), None)
        total += 1
        if first is not None:
            matched += 1
        lines.append(f"{img_path.name}\t{first}")
        if a.verbose:
            lines.append(f"    seq={hits}")

    lines.append(f"# hit={matched}/{total}")

    out = "\n".join(lines)
    print(out)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
