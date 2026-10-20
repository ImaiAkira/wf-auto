# -*- coding: utf-8 -*-
"""离线单测：#106 领主战/讨伐难度静态数据 + 一次性采集 CLI + 守卫（纯单测，不碰设备）。

跑：

    .venv\\Scripts\\python.exe tools\\test_lord_registry.py

覆盖：

1. **schema**：``scene.lords.LORDS`` 的必填字段 / M 正整数 / 难度 ∈ 词表 / slug 格式与唯一 /
   行名集合 == 花名册（46）/ ``verified`` 与 ``needs`` 的互斥要求 / 每条证据的路径**在仓内真实存在**；
2. **解锁链**：升序、首尾与 M 一致、``unlock_edges`` == 「前档→后档」、
   ``unlock_requires(超级) == (中级,高级,高级+)``（官方公告口径：全部更低档）、
   ``tier_position`` 1 = 最上一行 = 最高档（实测降序）；
3. **CLI（可注入 ocr_fn）**：假 OCR 重跑 == ``scene/lords.py``；标记段与 ``assets/data/lords.json``
   逐字一致；``--check`` 退出码 0；``--ocr-json`` 注入路径可用；缺帧 / 未登记前缀 / 来源冲突
   各自**报错并点名**（绝不静默猜）；
4. **守卫**：四个挂点探针为 True（含 prove-red 成立）。

不校验的东西（诚实边界）：本文件**不**判断「某账号能打哪几档」—— 那是账号状态，
真机以列表页 ``通关数 N/M`` / 详情页 ``NEW``/``首次报酬``/``COMPLETE!!`` 为准。
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scene.config import DIFFICULTIES, member  # noqa: E402
from scene.lords import (  # noqa: E402
    BY_ROW_NAME,
    BY_SLUG,
    KINDS,
    LORDS,
    MAX_TIERS_SOURCES,
    NEED_MAX_TIERS,
    NEED_TIER_CHAIN,
    Lord,
    by_row_name,
    by_slug,
    coverage,
    pending,
)

import gen_lord_registry as gen  # noqa: E402
import hooks_106  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _roster_names() -> set[str]:
    lord_battle = importlib.import_module("scene.lord_battle")
    return {m.行名 for m in lord_battle.LORD_BATTLE.members}


# ---------------------------------------------------------------------------
# 1. schema
# ---------------------------------------------------------------------------
def test_schema() -> None:
    print("\n== 1. schema：必填 / M / 词表 / slug / 花名册 / 证据存在性 ==")
    check("条目数 = 花名册 46", len(LORDS) == 46, f"got={len(LORDS)}")
    check("行名集合 == 花名册", {e.row_name for e in LORDS} == _roster_names())
    check("slug 唯一", len({e.slug for e in LORDS}) == len(LORDS))
    check("slug 形如 kind/行名", all(e.slug == f"{e.kind}/{e.row_name}" for e in LORDS))
    check("kind 都是 lord/joss", {e.kind for e in LORDS} == set(KINDS), f"got={sorted({e.kind for e in LORDS})}")
    check("kind 与花名册子族一致",
          all(e.kind == ("lord" if e.kind == "lord" else "joss") for e in LORDS))

    bad_m = [e.slug for e in LORDS if e.max_tiers is not None and (not isinstance(e.max_tiers, int) or e.max_tiers <= 0)]
    check("M 都是正整数或 None", bad_m == [], f"bad={bad_m}")
    bad_src = [e.slug for e in LORDS if e.max_tiers_source not in MAX_TIERS_SOURCES]
    check("max_tiers_source 取值合法", bad_src == [], f"bad={bad_src}")
    check("unknown 来源 ⇔ M=None",
          all((e.max_tiers_source == "unknown") == (e.max_tiers is None) for e in LORDS))
    check("M 已验证 ⇒ M 非空", all(e.max_tiers is not None for e in LORDS if e.max_tiers_verified))

    bad_diff = [(e.slug, d) for e in LORDS for d in e.tier_chain if d not in DIFFICULTIES]
    check("链上难度都在 scene.config.DIFFICULTIES 里", bad_diff == [], f"bad={bad_diff}")
    bad_len = [e.slug for e in LORDS if e.tier_chain and len(e.tier_chain) != e.max_tiers]
    check("链非空 ⇒ len(链) == M（首尾与 M 一致）", bad_len == [], f"bad={bad_len}")
    bad_entry = [e.slug for e in LORDS if e.tier_chain and e.tier_chain[0] not in ("初级", "中级")]
    check("链首（起始档）只有 初级/中级", bad_entry == [], f"bad={bad_entry}")

    bad_verified = [
        e.slug
        for e in LORDS
        if e.verified
        and (
            not e.evidence
            or not e.max_tiers_verified
            or len(e.tier_chain) != (e.max_tiers or 0)
            or any(d not in {k for k, _lab in e.row_labels} for d in e.tier_chain)
        )
    ]
    check("verified ⇒ 有证据 + M 已验证 + 链完整 + 每档有行名", bad_verified == [], f"bad={bad_verified}")
    check("verified=False ⇒ needs 非空", all(e.needs for e in LORDS if not e.verified))

    missing_evidence: list[str] = []
    no_note: list[str] = []
    for entry in LORDS:
        for item in entry.evidence:
            path_part, sep, note = item.partition("|")
            if not sep or not note:
                no_note.append(item)
            if not (REPO_ROOT / path_part).is_file():
                missing_evidence.append(path_part)
    check("证据串都带 `|` 后的读数摘录", no_note == [], f"bad={no_note}")
    check("证据路径都在仓里真实存在", missing_evidence == [], f"缺={sorted(set(missing_evidence))}")

    stats = coverage()
    check("覆盖统计：46 / 有证据 9 / 全链验证 2 / 占位 37",
          stats == {"lords": 46, "with_evidence": 9, "fully_verified": 2, "placeholders": 37}, f"got={stats}")


def test_derived_queries() -> None:
    print("\n== 2. 查询 / 占位条目 / 索引 ==")
    entry = by_slug("lord/妖狐讨伐")
    check("by_slug 命中", entry is not None)
    check("by_row_name 与 by_slug 指向同一条", by_row_name("妖狐讨伐") is entry)
    check("未知 slug -> None", by_slug("lord/不存在") is None)
    check("BY_SLUG / BY_ROW_NAME 大小 = 46", len(BY_SLUG) == len(BY_ROW_NAME) == 46)

    placeholder = pending("joss", "某个未来成员")
    check("pending：M=None / 链空 / 无证据 / verified=False",
          placeholder.max_tiers is None and placeholder.tier_chain == () and not placeholder.evidence
          and placeholder.verified is False)
    check("pending：needs 写清缺 M 与缺链",
          placeholder.needs == (NEED_MAX_TIERS, NEED_TIER_CHAIN), f"got={placeholder.needs}")
    check("pending：slug = kind/行名", placeholder.slug == "joss/某个未来成员")
    check("pending：行名正则整串锚定", placeholder.row_regex == "^某个未来成员$")
    try:
        pending("boss", "x")
    except ValueError:
        raised = True
    else:
        raised = False
    check("pending 拒绝未知 kind", raised)

    real = by_row_name("诅咒弧魔艾基尔讨伐")
    check("只有起始档行名的条目：entry_difficulty 取最低已实测档",
          real is not None and real.entry_difficulty == "中级", f"got={real.entry_difficulty if real else None}")
    check("链未采集时 top_difficulty 为 None（不拿行名猜）", real is not None and real.top_difficulty is None)
    check("链未采集时 tier_position 为 None", real is not None and real.tier_position("中级") is None)


# ---------------------------------------------------------------------------
# 3. 解锁链语义
# ---------------------------------------------------------------------------
def test_unlock_chain_semantics() -> None:
    print("\n== 3. 解锁链：逐档递进 =「全部更低档」，位置 1 = 最高档 ==")
    for slug in ("lord/妖狐讨伐", "joss/红嫉机兵"):
        entry = by_slug(slug)
        check(f"{slug} 链 = 中级→高级→高级+→超级",
              entry is not None and entry.tier_chain == ("中级", "高级", "高级+", "超级"),
              f"got={entry.tier_chain if entry else None}")
        check(f"{slug} M=4 且 verified", entry is not None and entry.max_tiers == 4 and entry.verified)
        check(f"{slug} 解锁边（前档→后档）",
              entry is not None and entry.unlock_edges()
              == (("中级", "高级"), ("高级", "高级+"), ("高级+", "超级")),
              f"got={entry.unlock_edges() if entry else None}")
        check(f"{slug} 超级 requires 全部更低档（不只是差一档）",
              entry is not None and entry.unlock_requires("超级") == ("中级", "高级", "高级+"),
              f"got={entry.unlock_requires('超级') if entry else None}")
        check(f"{slug} 中级 requires 空（起始档）", entry is not None and entry.unlock_requires("中级") == ())
        check(f"{slug} 纵向位置：1=超级（最上）… 4=中级",
              entry is not None
              and [entry.tier_position(d) for d in ("超级", "高级+", "高级", "中级")] == [1, 2, 3, 4])
        check(f"{slug} 不在链上的难度 -> 无记录（不是「没有前置」）",
              entry is not None and entry.unlock_requires("地狱级") == ())

    redjoss = by_slug("joss/红嫉机兵")
    check("详情页认证文本 ≠ 列表行名（红机兵海茵莱特 vs 红嫉机兵）",
          redjoss is not None and redjoss.row_prefix == "红机兵海茵莱特"
          and redjoss.detail_row_label("中级") == "红机兵海茵莱特中级",
          f"got={redjoss.row_prefix if redjoss else None}")
    check("行名容错正则收录了真机变体 红嫉族机兵",
          redjoss is not None and bool(__import__("re").search(redjoss.row_regex, "红嫉族机兵")))

    noho = by_slug("joss/无猾机兵")
    check("无猾机兵 M=5（列表页 通关数5/5 —— 旧静态表记 4 档是错的）",
          noho is not None and noho.max_tiers == 5 and noho.max_tiers_verified, )
    check("无猾机兵 链未采集 -> verified=False 且 needs 非空",
          noho is not None and noho.verified is False and bool(noho.needs))


# ---------------------------------------------------------------------------
# 4. 采集 CLI（可注入 ocr_fn）
# ---------------------------------------------------------------------------
def test_cli_injection_and_parse() -> None:
    print("\n== 4. 采集 CLI：注入点 / 解析 / 一致 ==")
    check("帧清单 = 列表页 2 + 详情页 5", len(gen.FRAMES) == 7 and len(gen.LIST_FRAMES) == 2
          and len(gen.DETAIL_FRAMES) == 5)

    # 假 OCR：缺帧必须点名报错，不当成「读不到」
    ocr = gen.corpus_ocr_fn({k: v for k, v in gen.FRAME_OCR.items() if k != gen.DETAIL_FRAMES[0]})
    try:
        gen.collect(ocr)
    except gen.CollectError as exc:
        check("缺帧 -> CollectError 且点名帧", gen.DETAIL_FRAMES[0] in str(exc), f"msg={exc}")
    else:
        check("缺帧 -> CollectError 且点名帧", False, "没有报错")

    # 列表页解析：行名来自花名册；配不上的「通关数」(五王连战) 被容忍
    roster = gen.default_roster()
    kinds = {m.行名: gen.KIND_BY_SUBFAMILY[m.子族] for m in roster}
    frame = "tools/frames/lord_page_tab_joss.png"
    rows, leftover = gen.parse_list_frame(gen.FRAME_OCR[frame], kinds, frame, "降临讨伐")
    by_name = {row.row_name: row for row in rows}
    check("列表页读到 3 个本 family 的行（五王连战不属于花名册）",
          set(by_name) == {"无猾机兵", "红嫉机兵", "苍叹机兵"}, f"got={sorted(by_name)}")
    check("无猾机兵 通关数 5/5", (by_name["无猾机兵"].cleared, by_name["无猾机兵"].total) == (5, 5))
    check("红嫉机兵 通关数 4/4 且有 COMPLETE!! 徽标",
          (by_name["红嫉机兵"].cleared, by_name["红嫉机兵"].total) == (4, 4)
          and by_name["红嫉机兵"].has_complete_badge)
    check("配不上的通关数被计数返回、不报错", leftover == ("通关数1/1",), f"got={leftover}")

    # 详情页解析：归属靠登记前缀（不靠标题 OCR）
    detail_items = gen.FRAME_OCR["tools/frames/lord_detail_multidiff.png"]
    reading = gen.parse_detail_frame(detail_items, frame="x.png")
    check("详情页归属 = lord/妖狐讨伐（按认证前缀）", reading.slug == "lord/妖狐讨伐", f"got={reading.slug}")
    check("详情页链（升序）= 中级→高级→高级+→超级", reading.chain == ("中级", "高级", "高级+", "超级"))
    check("详情页 4 行全 COMPLETE!! ⇒ all_cleared", reading.all_cleared is True)
    check("详情页纵向位置实测降序（超级 y 最小）",
          dict(reading.positions)["超级"] < dict(reading.positions)["中级"])
    try:
        gen.parse_detail_frame(detail_items, frame="x.png", prefixes={"lord/别人": "别的名字"})
    except gen.CollectError as exc:
        check("未登记前缀 -> CollectError（绝不猜归属）", "没在 DETAIL_PREFIXES" in str(exc), f"msg={exc}")
    else:
        check("未登记前缀 -> CollectError（绝不猜归属）", False, "没有报错")

    # 完整采集 == 仓内真源
    collected = gen.collect()
    check("假 OCR 重跑 collect() == scene.lords.LORDS", tuple(collected) == tuple(LORDS))
    check("collect() 顺序稳定（两次一致）", tuple(gen.collect()) == tuple(gen.collect()))

    source = (REPO_ROOT / "scene" / "lords.py").read_text(encoding="utf-8")
    check("标记段 == render_block()",
          gen.read_block(source).rstrip("\n") == gen.render_block(collected).rstrip("\n"))
    on_disk = (REPO_ROOT / "assets" / "data" / "lords.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    check("assets/data/lords.json == render_json()",
          on_disk.rstrip("\n") == gen.render_json(collected).rstrip("\n"))
    payload = json.loads(on_disk)
    check("JSON 是投影：条目数与真源一致 + 声明 source",
          len(payload["lords"]) == len(LORDS) and payload["_generated"]["source"] == "scene/lords.py")
    check("JSON 里没有「支持难度集」形状的键",
          hooks_106._scan_forbidden(payload) == [], f"got={hooks_106._scan_forbidden(payload)}")

    # CLI 端到端：--check 绿、--ocr-json 注入可用
    check("CLI --check 退出码 0", gen.main(["--check"]) == 0)
    corpus_json = {
        frame: [[text, list(box), score] for text, box, score in items]
        for frame, items in gen.FRAME_OCR.items()
    }
    with tempfile.TemporaryDirectory(prefix="wf_lord_registry_") as tmp:
        path = Path(tmp) / "ocr.json"
        path.write_text(json.dumps(corpus_json, ensure_ascii=False), encoding="utf-8")
        check("CLI --ocr-json 注入可用（退出码 0）", gen.main(["--ocr-json", str(path)]) == 0)
        assert gen.json_ocr_fn(corpus_json)(Path(gen.FRAMES[0])) == tuple(gen.FRAME_OCR[gen.FRAMES[0]])


def test_cli_conflicts_are_loud() -> None:
    print("\n== 5. 采集冲突：一律报错点名（绝不静默取一个） ==")
    member_lord = member("领主战", "某领主", "某领主", ("中级",))
    list_row = gen.ListRow(
        row_name="某领主", cleared=4, total=5, has_complete_badge=False,
        row_y=900, progress_y=972, score=0.9, frame="tools/frames/lord_page_tab_lord.png",
    )
    cleared = gen.DetailReading(
        frame="tools/frames/lord_detail_redjoss_cleared.png",
        slug="lord/某领主", kind="lord", row_prefix="某前缀", category="领主战",
        chain=("中级", "高级", "高级+", "超级"),
        row_labels=(("中级", "某前缀中级"), ("高级", "某前缀高级"),
                    ("高级+", "某前缀高级+"), ("超级", "某前缀超级")),
        positions=(("超级", 456), ("高级+", 648), ("高级", 837), ("中级", 1030)),
        all_cleared=True, has_new=False, has_first_reward=False, title="某领主",
    )
    try:
        gen.build_entry(member_lord, list_row, (cleared,))
    except gen.CollectError as exc:
        check("列表页 M 与详情页行数冲突 -> CollectError", "冲突" in str(exc), f"msg={exc}")
    else:
        check("列表页 M 与详情页行数冲突 -> CollectError", False, "没有报错")

    entry = gen.build_entry(member_lord, dataclasses.replace(list_row, total=4), (cleared,))
    check("对得上时：M 取列表页（首选来源）+ 链完整 + verified",
          entry.max_tiers == 4 and entry.max_tiers_source == gen.SOURCE_LIST
          and entry.tier_chain == ("中级", "高级", "高级+", "超级") and entry.verified,
          f"got=M{entry.max_tiers}/{entry.max_tiers_source}/verified={entry.verified}")

    early = gen.DetailReading(
        frame="early.png", slug="lord/某领主", kind="lord", row_prefix="某前缀", category="领主战",
        chain=("高级",), row_labels=(("高级", "某前缀高级"),), positions=(("高级", 458),),
        all_cleared=False, has_new=True, has_first_reward=True, title="某领主",
    )
    try:
        gen.build_entry(member_lord, dataclasses.replace(list_row, total=4), (cleared, early))
    except gen.CollectError as exc:
        check("早期可见档不是完整链的前缀 -> CollectError（证伪「逐档递进」时拒绝归并）",
              "前缀" in str(exc), f"msg={exc}")
    else:
        check("早期可见档不是完整链的前缀 -> CollectError（证伪「逐档递进」时拒绝归并）", False, "没有报错")


# ---------------------------------------------------------------------------
# 6. 守卫
# ---------------------------------------------------------------------------
def test_hooks() -> None:
    print("\n== 6. 挂点 #106：四个探针为 True + prove-red 成立 ==")
    check("lord-registry-schema 绿", hooks_106.probe_lord_registry_schema() is True)
    check("lord-registry-no-supported-set 绿", hooks_106.probe_lord_registry_no_supported_set() is True)
    check("lord-registry-cli-consistent 绿", hooks_106.probe_lord_registry_cli_consistent() is True)
    check("lord-collect-cli-not-on-runtime-path 绿",
          hooks_106.probe_lord_collect_cli_not_on_runtime_path() is True)

    # 禁止字段：三条路都要能变红（不靠 prove-red 也能单测）
    doctored = (REPO_ROOT / "scene" / "lords.py").read_text(encoding="utf-8") + (
        "\n\nclass _Broken(Lord):\n    支持难度集: tuple[str, ...] = ()\n"
    )
    red = hooks_106._forbidden_failures(source_text=doctored, json_text="{}")
    check("「支持难度集」字段 -> 守卫变红（并说明证伪理由）",
          bool(red) and any("证伪" in msg or "账号进度" in msg for msg in red), f"msg={red[:1]}")

    # 运行期探测：现存点已登记，多一个就红
    sites = hooks_106._collect_probe_sites(REPO_ROOT, "discover_difficulties")
    check("现存 discover_difficulties 出现点与登记一致",
          sites == hooks_106.RUNTIME_PROBES, f"got={sites} / 登记={hooks_106.RUNTIME_PROBES}")
    check("多一个未登记探测点 -> 守卫变红",
          bool(hooks_106._probe_site_failures(sites={**sites, "agent/x.py": 1})))

    check("prove_red() 成立（6 条破坏实验各自变红）", hooks_106.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 74)
    print("离线单测：#106 领主战/讨伐难度静态数据（scene/lords.py + gen_lord_registry + hooks_106）")
    print("=" * 74)
    test_schema()
    test_derived_queries()
    test_unlock_chain_semantics()
    test_cli_injection_and_parse()
    test_cli_conflicts_are_loud()
    test_hooks()
    print("\n" + "=" * 74)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
