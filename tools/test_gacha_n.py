# -*- coding: utf-8 -*-
"""离线单测：扭蛋（抽卡）N 发 —— pipeline / GUI 选项 / 页面判据（#26）。

不需要游戏、不需要 maa 运行环境，直接跑：

    python tools/test_gacha_n.py

这里钉住的是**本票的承重假设**（改坏了就该红）：
1. 池名门 / 深渊停表 / max_hit 三样旧设计**不许回来**（它们是真机抽不动 + 永远空转的病根）；
2. 「跳过」节点必须是**无识别固定点**（运维口径：记死「全部跳过」位置一直点）；
3. 「一发」的口径是**汇总页出现**（点确认框可能被取消，不算抽）；
4. 池子页与汇总页**都**有「10连抽取」四个字 —— 判据必须靠「1次抽取」把两页分开；
5. 确认框两种文案（有券/没券）与**同一颗按钮坐标**都要在。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO / "agent"
sys.path.insert(0, str(AGENT_DIR))

import gacha_pages  # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _load_jsonc(path: Path) -> dict:
    """读带 // 注释的 JSON（优先真 jsonc，退化为去行注释）。"""
    raw = path.read_text(encoding="utf-8")
    try:
        import jsonc  # noqa: PLC0415

        return jsonc.loads(raw)
    except Exception:  # noqa: BLE001 - 没有 jsonc 时退化为朴素的 // 注释剥离
        stripped = re.sub(r"(?m)^\s*//.*$", "", raw)
        return json.loads(stripped)


PIPELINE = REPO / "assets" / "resource" / "pipeline" / "gacha.json"
INTERFACE = REPO / "assets" / "interface.json"
GLOSSARY = REPO / "GLOSSARY.md"
MY_RECO = REPO / "agent" / "my_reco.py"

gacha = _load_jsonc(PIPELINE)
interface = _load_jsonc(INTERFACE)

# ---------------------------------------------------------------------------
# 1. 旧设计不许回来
# ---------------------------------------------------------------------------
print("\n== 1. 旧设计已拆（池名门 / 深渊停表 / max_hit）==")
check("GachaPoolCheck 已删除", "GachaPoolCheck" not in gacha)
check("GachaForbidden 已删除", "GachaForbidden" not in gacha)
check(
    "gacha.json 里没有任何 max_hit",
    not any(isinstance(n, dict) and "max_hit" in n for n in gacha.values()),
    "max_hit 用光只让节点静默消失、结束不了任务",
)

# ---------------------------------------------------------------------------
# 2. 跳过：只在真看见按钮时点（不许再「一路点」）
# ---------------------------------------------------------------------------
print("\n== 2. 跳过节点（OCR 门 + 固定落点）==")
skip_all = gacha.get("GachaSkipAll") or {}
skip = gacha.get("GachaSkip") or {}
check("GachaSkipAll（全部跳过）存在", bool(skip_all))
check(
    "GachaSkipAll 只认「全部跳过」、点 [673,184]",
    (skip_all.get("recognition") or {}).get("type") == "OCR"
    and "全部跳过" in str((skip_all.get("recognition") or {}).get("param", {}))
    and (skip_all.get("action") or {}).get("param", {}).get("target") == [673, 184],
)
check("GachaSkip 存在", bool(skip))
check(
    "★GachaSkip 不再是 DirectHit（历史上「一路点」会把顶部条/轮播点乱）★",
    (skip.get("recognition") or {}).get("type") == "OCR"
    and "跳过" in str((skip.get("recognition") or {}).get("param", {})),
)
check(
    "GachaSkip 点 [680,60]（同时落在角色池/武器系两颗「跳过」框内）",
    (skip.get("action") or {}).get("param", {}).get("target") == [680, 60],
)
entry_next = (gacha.get("GachaEntry") or {}).get("next") or []
check(
    "★跳过提到最前（#30 v2：揭示页帧不必先空试 9~10 个候选）★",
    entry_next.index("GachaSkipAll") >= 4
    and entry_next.index("GachaSkipAll") < entry_next.index("GachaConfirm")
    and entry_next.index("GachaSkip") < entry_next.index("GachaConfirm"),
    str(entry_next[:8]),
)
wait = gacha.get("GachaWait") or {}
check(
    "★纯等待兜底存在（DirectHit + DoNothing，排在最后）★",
    (wait.get("recognition") or {}).get("type") == "DirectHit"
    and (wait.get("action") or {}).get("type") == "DoNothing"
    and entry_next[-1:] == ["GachaWait"],
    "没有它时一帧全 miss 会让任务直接 FAILED（本轮真机 34.5s 失败即此）",
)
fallback = gacha.get("GachaSkipFallback") or {}
check(
    "★揭示页兜底在（★4+ 角色页没有「跳过」按钮，靠它推进）★",
    ((fallback.get("recognition") or {}).get("param") or {}).get("custom_recognition")
    == "gacha_skip_gate"
    and (fallback.get("action") or {}).get("param", {}).get("target") == [673, 184],
)
check(
    "兜底排在两颗 OCR 跳过之后、纯等待之前",
    entry_next.index("GachaSkip") < entry_next.index("GachaSkipFallback") < entry_next.index("GachaWait"),
)
check(
    "★抽卡/连抽/确认框的 OCR 都加了 ROI（#30 v2）★",
    ((gacha.get("GachaOnceBtn") or {}).get("recognition") or {}).get("param", {}).get("roi") == [0, 940, 720, 240]
    and ((gacha.get("GachaDraw10Btn") or {}).get("recognition") or {}).get("param", {}).get("roi") == [0, 940, 720, 240]
    and ((gacha.get("GachaContinueBtn") or {}).get("recognition") or {}).get("param", {}).get("roi") == [0, 940, 720, 240]
    and ((gacha.get("GachaConfirm") or {}).get("recognition") or {}).get("param", {}).get("roi") == [300, 740, 420, 160],
)
roi = ((skip_all.get("recognition") or {}).get("param") or {}).get("roi") or []
check(
    "跳过 ROI 盖住「全部跳过」实测框（720：x 627-719 / y 149-218）",
    len(roi) == 4
    and roi[0] <= 627
    and roi[0] + roi[2] >= 719
    and roi[1] <= 149
    and roi[1] + roi[3] >= 218,
    str(roi),
)

# ---------------------------------------------------------------------------
# 3. 池子页 / 汇总页 / 确认框
# ---------------------------------------------------------------------------
print("\n== 3. 页面与按钮 ==")
draw = gacha.get("GachaDraw10") or {}
draw_all_of = ((draw.get("recognition") or {}).get("param") or {}).get("all_of") or []
check(
    "GachaDraw10 同时要求「1次抽取」+「10连抽取」",
    set(draw_all_of) == {"GachaOnceBtn", "GachaDraw10Btn"},
    str(draw_all_of),
)
check(
    "GachaDraw10 点写死坐标 [571,1015]（And.box_index 不可信）",
    (draw.get("action") or {}).get("param", {}).get("target") == [571, 1015],
)
cont = gacha.get("GachaContinue10") or {}
check("继续节点没有 max_hit", "max_hit" not in cont)
check(
    "继续节点点 [360,1104]",
    (cont.get("action") or {}).get("param", {}).get("target") == [360, 1104],
)
back = gacha.get("GachaBackToPool") or {}
check("★没有「回扭蛋首页」的兜底节点（它会换池）★", not back)
count = gacha.get("GachaCount") or {}
check(
    "GachaCount 用 agent 的 gacha_count",
    ((count.get("recognition") or {}).get("param") or {}).get("custom_recognition") == "gacha_count",
)
check(
    "★抽满就地 StopTask、不做任何导航★",
    (count.get("action") or {}).get("type") == "StopTask" and (count.get("next") or []) == [],
)
check(
    "没有「前往扭蛋首页」的点击（629,1117 不该出现在 pipeline 里）",
    "629, 1117" not in str(gacha).replace("\n", ""),
)
stop = gacha.get("GachaStop") or {}
check("多余的 GachaStop 叶已删除（收工直接由 GachaCount/Stall 停）", not stop)
stall = gacha.get("GachaStall") or {}
check(
    "GachaStall 用 agent 的 gacha_stall 且有界",
    ((stall.get("recognition") or {}).get("param") or {}).get("custom_recognition") == "gacha_stall",
)
conf = gacha.get("GachaConfirm") or {}
conf_param = (conf.get("recognition") or {}).get("param") or {}
check(
    "★确认框合成一颗：一次 OCR 同时认「抽取扭蛋」与「购买并抽取」★",
    conf_param.get("expected") == ["^抽取扭蛋$", "^购买并抽取$"],
    str(conf_param),
)
check(
    "确认框点 [522,826] 且点完只等 500ms（#30 v4）",
    (conf.get("action") or {}).get("param", {}).get("target") == [522, 826]
    and conf.get("post_delay") == 500,
)
check(
    "旧的 GachaConfirmTicket / GachaBuyConfirm 已删除（不再每帧多一次 OCR）",
    "GachaConfirmTicket" not in gacha and "GachaBuyConfirm" not in gacha,
)

# ---------------------------------------------------------------------------
# 4. 计数与收工出口
# ---------------------------------------------------------------------------
print("\n== 4. 计数与收工 ==")
check("gacha.json 里没有 PubReturnHome（★收尾不回主城★）", "PubReturnHome" not in PIPELINE.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# 4b. 提速（#30）：只 OCR 底部条带 + 延迟上限
# ---------------------------------------------------------------------------
print("\n== 4b. 提速（底部条带 OCR + 延迟）==")
ocr_bottom = gacha.get("GachaOcrBottom") or {}
bparam = (ocr_bottom.get("recognition") or {}).get("param") or {}
check(
    "GachaOcrBottom 只扫底部条带 roi=[0,940,720,240]",
    (ocr_bottom.get("recognition") or {}).get("type") == "OCR"
    and bparam.get("roi") == [0, 940, 720, 240],
    str(bparam),
)
roi_b = bparam.get("roi") or []
check(
    "该 ROI 盖住池子页按钮(y≈1044)与汇总页按钮(y≈1104/1117)",
    len(roi_b) == 4 and roi_b[1] <= 1000 and roi_b[1] + roi_b[3] >= 1130,
)
count_param = ((gacha.get("GachaCount") or {}).get("recognition") or {}).get("param") or {}
check(
    "GachaCount 用底部条带 OCR",
    (count_param.get("custom_recognition_param") or {}).get("ocr_entry") == "GachaOcrBottom",
)
fb_param = ((gacha.get("GachaSkipFallback") or {}).get("recognition") or {}).get("param") or {}
check(
    "GachaSkipFallback 用底部条带 OCR",
    (fb_param.get("custom_recognition_param") or {}).get("ocr_entry") == "GachaOcrBottom",
)
_delays = {
    k: v.get("post_delay")
    for k, v in gacha.items()
    if isinstance(v, dict) and v.get("post_delay")
}
check("所有 post_delay ≤ 1200（砍掉 2.5s 那一档）", max(_delays.values()) <= 1200, str(_delays))

# ---------------------------------------------------------------------------
# 5. GUI 选项
# ---------------------------------------------------------------------------
print("\n== 5. GUI（interface.json）==")
tasks = {t.get("name"): t for t in (interface.get("task") or [])}
task = tasks.get("扭蛋（抽卡）") or {}
check("任务还在（改老任务，不新开）", bool(task))
check("任务只挂「抽几发」", task.get("option") == ["抽几发"], str(task.get("option")))
opts = interface.get("option") or {}
check("选项「抽哪个池」已删除", "抽哪个池" not in opts)
check("选项「继续抽几次」已删除", "继续抽几次" not in opts)
opt = opts.get("抽几发") or {}
inputs = (opt.get("inputs") or [{}])[0]
check("「抽几发」默认 1、正整数校验", inputs.get("default") == "1" and inputs.get("verify") == "^[1-9][0-9]*$")
override = (opt.get("pipeline_override") or {}).get("GachaCount") or {}
cparam = ((override.get("recognition") or {}).get("param") or {}).get("custom_recognition_param") or {}
check(
    "「抽几发」落到 GachaCount.times（不是 max_hit）",
    cparam.get("times") == "{次数}" and "max_hit" not in str(override),
    str(cparam),
)

# ---------------------------------------------------------------------------
# 6. agent 注册
# ---------------------------------------------------------------------------
print("\n== 6. agent 注册 ==")
reco_src = MY_RECO.read_text(encoding="utf-8")
check('my_reco 注册了 "gacha_count"', 'custom_recognition("gacha_count")' in reco_src)
check('my_reco 注册了 "gacha_stall"', 'custom_recognition("gacha_stall")' in reco_src)
check('my_reco 注册了 "gacha_skip_gate"', 'custom_recognition("gacha_skip_gate")' in reco_src)

# ---------------------------------------------------------------------------
# 7. 页面判据（真机 OCR 文本）
# ---------------------------------------------------------------------------
print("\n== 7. 页面判据（真机 OCR 原文）==")
POOL_ITEMS = [
    ("武器扭蛋", [300, 120, 240, 60]),
    ("1次抽取", [240, 1044, 120, 40]),
    ("10连抽取", [479, 1044, 120, 40]),
    ("扭蛋券", [120, 1140, 60, 30]),
    ("10连券", [480, 1140, 60, 30]),
]
REVEAL_ITEMS = [("跳过", [656, 46, 60, 30]), ("全部跳过", [673, 184, 90, 30])]
SUMMARY_ITEMS = [
    ("获得了印第安战斧！", [60, 980, 300, 40]),
    ("继续", [355, 1050, 40, 30]),
    ("10连抽取", [400, 1075, 120, 40]),
    ("前往", [600, 1050, 60, 30]),
    ("扭蛋首页", [600, 1085, 120, 30]),
]
#: ★16448 装备扭蛋真机★：券用完的汇总页**没有「继续」**，只剩「前往 / 扭蛋首页」。
SUMMARY_NO_CONTINUE = [
    ("获得了野营刀！", [60, 980, 300, 40]),
    ("前往", [620, 1440, 60, 30]),
    ("扭蛋首页", [620, 1490, 120, 30]),
]
check("池子页判据命中", gacha_pages.is_pool_page(POOL_ITEMS))
check("池子页不被误判成汇总页", not gacha_pages.is_summary_page(POOL_ITEMS))
check("汇总页判据命中", gacha_pages.is_summary_page(SUMMARY_ITEMS))
check("汇总页不被误判成池子页（没有「1次抽取」）", not gacha_pages.is_pool_page(SUMMARY_ITEMS))
check(
    "★没有「继续」的汇总页也认得出（装备池真机：券用完就只剩「前往扭蛋首页」）★",
    gacha_pages.is_summary_page(SUMMARY_NO_CONTINUE)
    and not gacha_pages.is_pool_page(SUMMARY_NO_CONTINUE),
)
check("汇总页有「继续」→ has_continue=True", gacha_pages.has_continue(SUMMARY_ITEMS))
check(
    "没有「继续」的汇总页 → has_continue=False（→ 就地收工，绝不换池）",
    not gacha_pages.has_continue(SUMMARY_NO_CONTINUE),
)
check(
    "揭示页两条判据都不命中（不计数、不误点）",
    not gacha_pages.is_pool_page(REVEAL_ITEMS) and not gacha_pages.is_summary_page(REVEAL_ITEMS),
)
check(
    "容错：OCR 在字间插空格仍能认「10连抽取」",
    gacha_pages.is_pool_page([("1 次抽取", [0, 0, 10, 10]), ("10 连抽取", [0, 0, 10, 10])]),
)

# ---------------------------------------------------------------------------
# 8. 词汇表
# ---------------------------------------------------------------------------
print("\n== 8. GLOSSARY ==")
g = GLOSSARY.read_text(encoding="utf-8")
for term in ("池子 (pool)", "十连 (ten-pull)", "十连券 (ten-pull ticket)", "跳过 (skip)", "汇总页 (result summary)"):
    check(f"GLOSSARY 收录「{term}」", term in g)

# ---------------------------------------------------------------------------
print()
if FAILS:
    print(f"FAILED ({len(FAILS)})：")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASS")
