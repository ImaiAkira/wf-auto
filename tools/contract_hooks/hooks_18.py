# -*- coding: utf-8 -*-
"""#18：归位不再在「主城」自匹配 + 事件两类注入位置相反的挂点（已点亮）。

seam：``scene.events``（事件层）+ ``assets/resource/pipeline/special_dungeon.json``
+ ``assets/resource/pipeline/common.json``（ADR-0001 的「幂等注入 / 校验」）。

背景（#13 真机实证）：归位 ``PubReturnHome`` 的判据原本只认底部导航「主城」
（OCR ``^主城$`` + ROI ``[0,1180,720,100]``），而主城页常驻的底部导航标签「主城」
（720 ``box=[157,1248,44,25]``，中心 ``(179,1260)``）就在该 ROI 内 → 在主城上**恒命中**。
归位又被当**优先 ``[JumpBack]`` 前缀**注入每个流程节点 → 点空 → 重扫 → 再命中 → **死循环**。
整轮 370 节点全 ``PubReturnHome``、282 帧显示设备 7 分钟没离开主城。

两个守卫（都在本文件里，prove-red 也在本文件里）：

1. ``return-home-not-self-matching`` —— 归位**在 主城 上不命中**：
   * 判据必须是 ``And``，且除「主城底部导航可见」外**还有一条把主城排除掉**的叶子
     （底部导航最左槽的「返回」，主城页最左槽是「主角色」、没有「返回」）；
   * **在真机帧的 OCR 上求值**（离线内嵌：``MAIN_CITY_OCR`` = pre_shot.png 的 720 空间
     OCR，``SUB_PAGE_OCR`` = r1/r2/r3 列表 / 详情页的 720 空间 OCR）：
     主城帧上**不命中**。
   * ★#29 更新本条的【正例】★：#18 曾把「非主城子页（列表 / 详情）」当正例（要求归位命中
     它们）；#29 真机实证那样会让归位在**链上步骤页面**自匹配 → 目标行在屏幕外时抢跑、
     滚动找行永不执行。故现要求：归位在列表 / 详情页（``SUB_PAGE_OCR``，反例）**不命中**、
     在**漂到别的分区**的页（``GACHA_OCR`` + ``GACHA_ORANGE``，正例）**命中**。
     第三叶（页面范围判别叶）由 ``PubReturnHomeOtherSection`` 承担（见 #29 的 hooks_29）。
2. ``event-classes-opposite-positions`` —— 事件层两类注入位置相反且被锁死：
   * ``scene.events`` 里打断型（9 类异常）``kind="interrupt"``、兜底型（归位）
     ``kind="fallback"``；``FALLBACK_EVENTS == (归位,)``；
   * 真实 ``special_dungeon.json`` 里：每个流程节点 = **打断型前缀** + 原有后继 +
     **兜底型后缀（恰在末位 DirectHit 恢复边 / 终点之前）**；归位若被放回前缀即红。

★prove-red★（在文件末尾，`python tools\\contract_hooks\\hooks_18.py`）：
   * 把归位挪回前缀（临时副本上）-> 位置守卫红；
   * 把归位判据弱化回「只认主城」-> 自匹配守卫红。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

_PIPELINE_REL = "assets/resource/pipeline"
_SD = "special_dungeon.json"

# 真机帧的 720 空间 OCR（内嵌，离线可求值）——
# MAIN_CITY_OCR 来自 pre_shot.png（主城）；SUB_PAGE_OCR 来自 r1/r2/r3（列表 / 详情页）。
# 只保留与判据 / 主城锚点相关的条目；坐标是 MAA OCR 的原始 box=[x,y,w,h]（720 空间）。
MAIN_CITY_OCR: list[tuple[str, list[int]]] = [
    ("主城", [157, 1248, 44, 25]),      # 底部导航第二个标签（当前在「主城」页）
    ("主角色", [22, 1249, 61, 20]),     # 底部导航最左槽 = 主角色（★不是「返回」★）
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("菜单", [636, 1248, 45, 25]),
    ("领主战", [569, 1121, 79, 29]),    # 主城右下角入口（SpecialOpenLord ROI 内）
    ("关卡", [313, 1088, 93, 50]),
    ("活动", [82, 1122, 59, 31]),
]

# 非主城子页**形状**（领主战列表页 / 详情页）：底部导航最左槽是「返回」。
# ★#29 起这是【反例】★：#18 曾把它当正例（归位应命中列表 / 详情页），但 #29 真机实证
#   归位在这些**链上步骤页面**上自匹配 → 目标行在屏幕外时抢跑、滚动找行永不执行。
#   故现要求：归位在这类页面上【不命中】。
SUB_PAGE_OCR: list[tuple[str, list[int]]] = [
    ("返回", [32, 1247, 43, 24]),       # 底部导航最左槽 = 返回（★说明不是主城★）
    ("主城", [158, 1248, 42, 24]),
    ("角色", [277, 1247, 42, 25]),
    ("商店", [397, 1247, 43, 24]),
    ("扭蛋", [516, 1245, 45, 27]),
    ("菜单", [637, 1248, 42, 25]),
    ("更新列表", [903, 456, 96, 40]),
]

# ★#29 正例★：真正「该回主城」的页面 —— 漂到了**别的分区**（底导里另一个分区页签橙色高亮）。
# 真机帧 scope_gacha.png（扭蛋分区页）的 720 空间底导 OCR + 四个分区页签的橙色像素计数。
GACHA_OCR: list[tuple[str, list[int]]] = [
    ("返回", [31, 1247, 45, 25]),
    ("主城", [157, 1248, 43, 25]),      # 灰的（非选中），但 OCR 仍读得到文字
    ("角色", [275, 1244, 46, 29]),
    ("商店", [397, 1246, 43, 26]),
    ("扭蛋", [516, 1246, 45, 26]),
    ("菜单", [636, 1248, 45, 25]),
    ("1次抽取", [178, 1009, 133, 39]),
]
GACHA_ORANGE = {"角色": 0, "商店": 0, "扭蛋": 918, "菜单": 0}
_ZERO_ORANGE = {"角色": 0, "商店": 0, "扭蛋": 0, "菜单": 0}

# 底部导航四个「一级分区」页签标签框（720 空间）——与 #29 的 PubReturnHomeOtherSection 一致。
_TAB_ROIS = {
    "角色": [275, 1244, 46, 29],
    "商店": [397, 1246, 43, 26],
    "扭蛋": [516, 1246, 45, 26],
    "菜单": [636, 1248, 45, 25],
}

# 末位的 DirectHit 恢复边 / 终点（兜底事件插在它之前）。按 recognition 判定，不靠硬编码名字。
_DIRECT_HIT_TYPES = ("DirectHit",)


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 离线 recognition 求值器（只覆盖判据用到的类型；Custom / 未知 -> 视为不命中）
# ---------------------------------------------------------------------------
def _ocr_hit(rec: dict, items: list[tuple[str, list[int]]]) -> bool:
    param = rec.get("param") or {}
    pats = param.get("expected") or []
    roi = param.get("roi")
    for text, box in items:
        if not any(re.search(p, text or "") for p in pats):
            continue
        if roi is None:
            return True
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        if roi[0] <= cx <= roi[0] + roi[2] and roi[1] <= cy <= roi[1] + roi[3]:
            return True
    return False


def eval_recognition(
    rec: dict | None,
    items: list[tuple[str, list[int]]],
    resolve=None,
    orange=None,
) -> bool:
    """在给定 OCR 结果上求一条 recognition（OCR / And / Or / DirectHit / ColorMatch）。

    ``orange``：四个一级分区页签的橙色像素计数（#29 的 ColorMatch 叶用它求值）；
    缺省（None）时 ColorMatch 视为不命中（兼容 #18 原本的纯 OCR 用例）。
    """
    if not isinstance(rec, dict):
        return False
    kind = rec.get("type", "DirectHit")
    if kind == "DirectHit":
        return True
    if kind == "OCR":
        return _ocr_hit(rec, items)
    if kind == "ColorMatch":
        param = rec.get("param") or {}
        roi = list(param.get("roi") or [])
        key = next((k for k, r in _TAB_ROIS.items() if roi == r), None)
        if key is None or orange is None:
            return False
        return int(orange.get(key, 0)) >= int(param.get("count", 1))
    if kind in ("And", "Or"):
        leaves = (rec.get("param") or {}).get("all_of" if kind == "And" else "any_of") or []
        hits = []
        for leaf in leaves:
            leaf_rec = leaf
            if isinstance(leaf, str):
                leaf_rec = resolve(leaf) if resolve is not None else None
            hits.append(eval_recognition(leaf_rec, items, resolve, orange))
        return all(hits) if kind == "And" else any(hits)
    return False  # Custom / 其它：离线不臆测，视为不命中


def _resolver(files: dict):
    import scene.drift as drift  # noqa: PLC0415

    def resolve(name: str):
        return drift._resolve_recognition(name, files)

    return resolve


def candidate_hit(ref: str, items, files, overrides: dict | None = None) -> bool:
    """一个候选引用（可带 ``[JumpBack]`` 前缀）在给定画面上是否命中。"""
    name = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
    if overrides and name in overrides:
        rec = overrides[name]
    else:
        import scene.drift as drift  # noqa: PLC0415

        rec = drift._resolve_recognition(name, files)
    return eval_recognition(rec, items, _resolver(files))


def simulate(entry_next: list, items, files, max_steps: int = 12, overrides=None) -> list[str]:
    """模拟 MAA 的 ``next`` 语义：按序识别，取第一个命中的；``[JumpBack]`` 回到调用者重扫。

    返回依次命中的节点名序列（``max_steps`` 步上限）。``entry_next`` 是当前节点的候选集：
    每步都在它上面重扫（这正是死循环的机制：命中的节点不改变画面 -> 下一轮又命中它）。
    """
    seq: list[str] = []
    for _ in range(max_steps):
        hit = None
        for ref in entry_next:
            if candidate_hit(ref, items, files, overrides):
                hit = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
                break
        if hit is None:
            break
        seq.append(hit)
    return seq


# ---------------------------------------------------------------------------
# 守卫 1：归位不再自匹配「主城」
# ---------------------------------------------------------------------------
def _self_match_failures(recognition: dict | None = None) -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415
    from scene.events import RETURN_HOME_NODE_NAME, RETURN_HOME_NODE_SPEC  # noqa: PLC0415

    rec = RETURN_HOME_NODE_SPEC["recognition"] if recognition is None else recognition
    files = drift.load_pipelines(REPO_ROOT / _PIPELINE_REL)
    resolve = _resolver(files)
    msgs: list[str] = []

    if not isinstance(rec, dict) or rec.get("type") != "And":
        msgs.append(
            f"归位自匹配：{RETURN_HOME_NODE_NAME} 的判据不是 And（单条 OCR 无法排除主城）—— 实际 {rec!r}"
        )
    else:
        leaves = (rec.get("param") or {}).get("all_of") or []
        # ★#29 起要求 ≥3 叶★：前两叶只是底部导航（主城 + 返回），链上列表 / 详情页同样成立；
        #   必须有第三条【页面范围判别叶】才能把链上步骤页面排除。
        if len(leaves) < 3:
            msgs.append(
                f"归位自匹配：And 只有 {len(leaves)} 条叶子 —— 仅凭底部导航不足以排除链上步骤页面（#29）"
            )

    if eval_recognition(rec, MAIN_CITY_OCR, resolve, _ZERO_ORANGE):
        msgs.append(
            "归位自匹配：判据在【主城】真机帧 OCR 上仍然命中（归位会点空 -> 死循环）"
        )
    # ★#29：链上步骤页面（列表 / 详情）是【反例】—— 归位不得在此命中（否则抢跑、滚动永不执行）。
    if eval_recognition(rec, SUB_PAGE_OCR, resolve, _ZERO_ORANGE):
        msgs.append(
            "归位范围：判据在【链上步骤页面】(列表 / 详情) 真机帧上命中 —— 会抢跑、"
            "滚动找行永不执行（#29）"
        )
    # ★#29 正例★：真正该归位的页面（漂到别的分区）必须命中。
    if not eval_recognition(rec, GACHA_OCR, resolve, GACHA_ORANGE):
        msgs.append(
            "归位范围：判据在【真正该归位】的分区页真机帧上不命中（归位失去兜底能力）"
        )
    return msgs


def probe_return_home_not_self_matching() -> bool:
    """#18：归位判据在主城帧上不命中、在非主城子页帧上命中。"""
    return _self_match_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：两类事件注入位置相反且被锁死
# ---------------------------------------------------------------------------
def _is_terminal(name: str, files: dict) -> bool:
    """``name`` 是否是 DirectHit 恢复边 / 终点（无 recognition 也算 DirectHit）。"""
    import scene.drift as drift  # noqa: PLC0415

    rec = drift._resolve_recognition(name, files)
    if rec is None:
        return False
    return rec.get("type", "DirectHit") in _DIRECT_HIT_TYPES


def _positions_failures(root: Path) -> list[str]:
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415
    from scene.events import (  # noqa: PLC0415
        EVENTS,
        FALLBACK_EVENTS,
        FALLBACK_KIND,
        fallback_refs,
        interrupt_refs,
        return_home_ref,
    )

    msgs: list[str] = []
    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    home = return_home_ref()

    # 类别本身。
    if any(e.kind != FALLBACK_KIND for e in FALLBACK_EVENTS):
        msgs.append("事件分类：兜底型事件组里混入了非兜底型事件")
    if home in prefix:
        msgs.append("事件分类：归位出现在打断型前缀里（应为兜底型后缀）")
    if home not in suffix:
        msgs.append("事件分类：归位不在兜底型后缀组里")

    files = drift.load_pipelines(Path(root) / _PIPELINE_REL)
    data = files.get(_SD)
    if not isinstance(data, dict):
        return msgs + [f"位置守卫：找不到 {_SD}"]

    own = {n for e in EVENTS for n in e.nodes}
    for name, spec in data.items():
        if not isinstance(spec, dict) or not spec.get("next") or name in own:
            continue
        nxt = spec["next"]
        # (a) 打断型前缀。
        if nxt[: len(prefix)] != prefix:
            msgs.append(f"{_SD}::{name}.next 没有以打断型事件组开头（前缀被挪动）")
        # (b) 归位恰在后缀位置：末位恢复边之前。
        if not suffix or len(nxt) <= len(suffix):
            msgs.append(f"{_SD}::{name}.next 太短，放不下兜底型后缀")
            continue
        mid = nxt[:-1]
        if mid[-len(suffix):] != suffix:
            msgs.append(
                f"{_SD}::{name}.next 的归位不在后缀位置（应在末位恢复边之前）—— 实际 {nxt}"
            )
        # (c) 末位必须是 DirectHit 恢复边 / 终点（否则兜底会死代码 / 或末位被事件占据）。
        if not _is_terminal(nxt[-1], files):
            msgs.append(
                f"{_SD}::{name}.next 末位 {nxt[-1]!r} 不是 DirectHit 恢复边 / 终点"
                f"（兜底事件应恰在它之前）"
            )
    return msgs


def probe_event_classes_opposite_positions() -> bool:
    """#18：真实 pipeline 里两类事件位置相反（打断前缀 / 兜底后缀），且归位不是前缀。"""
    return _positions_failures(REPO_ROOT) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_18.py`）
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook18_"))
    (root / "assets" / "resource").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "assets" / "interface.json", root / "assets" / "interface.json")
    shutil.copytree(
        REPO_ROOT / "assets" / "resource" / "pipeline",
        root / "assets" / "resource" / "pipeline",
    )
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_move_home_to_prefix(root: Path) -> None:
    """把归位挪回【前缀】（SpecialEntry.next 第一个候选）——旧死循环形态。"""
    _sub(
        root / _PIPELINE_REL / _SD,
        '        "next": [\n            "[JumpBack]PubLoadingWait",',
        '        "next": [\n'
        '            "[JumpBack]PubReturnHome",\n'
        '            "[JumpBack]PubLoadingWait",',
    )


def _weakened_self_match() -> dict:
    """把归位判据弱化回「只认主城」（去掉把主城排除掉的那条叶子）。"""
    return {"type": "OCR", "param": {"expected": ["^主城$"], "roi": [0, 1180, 720, 100]}}


def prove_red() -> bool:
    """真实绿；把归位挪回前缀 -> 位置守卫红；弱化自匹配判据 -> 自匹配守卫红。"""
    scene_on_path()

    print("hooks_18 prove-red：改坏两处，要求两个守卫各自变红")
    green = (
        probe_return_home_not_self_matching() is True
        and probe_event_classes_opposite_positions() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：归位不自匹配 + 两类位置相反（绿）")
    if not green:
        return False

    # (a) 把归位挪回前缀 -> 位置守卫红。
    root = _temp_assets()
    try:
        _break_move_home_to_prefix(root)
        msgs = _positions_failures(root)
        red_prefix = len(msgs) > 0
        tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_prefix else 'FAIL'}] 归位挪回前缀 -> {'红' if red_prefix else '仍绿'}{tail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # (b) 弱化自匹配判据 -> 自匹配守卫红。
    msgs = _self_match_failures(_weakened_self_match())
    red_self = len(msgs) > 0
    tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
    print(f"  [{'PASS' if red_self else 'FAIL'}] 弱化判据回「只认主城」-> {'红' if red_self else '仍绿'}{tail}")

    ok = green and red_prefix and red_self
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "return-home-not-self-matching",
        "#18",
        "归位判据不再自匹配「主城」：主城真机帧不命中、非主城子页命中",
        probe_return_home_not_self_matching,
    ),
    (
        "event-classes-opposite-positions",
        "#18",
        "事件两类注入位置相反：打断型前缀 / 兜底型（归位）后缀（末位恢复边之前）",
        probe_event_classes_opposite_positions,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
