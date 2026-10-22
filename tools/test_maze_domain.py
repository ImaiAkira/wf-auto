# -*- coding: utf-8 -*-
"""离线单测（#57）：迷宫【域】的判定与进入 = 【图片/模板匹配】（不再用 OCR 判域）。

运维裁决（2026-10-14）：「迷宫域最好不要用 OCR，用模式识别/图片识别好一点。」

不需要游戏 / 设备，直接跑：

    .venv\\Scripts\\python.exe tools\\test_maze_domain.py

覆盖 #57 验收：
  1. **三个域各有模板**（横幅 + 页眉），文件确实提交在 ``assets/resource/image/maze/``。
  2. **进域 = 标题 ∧ 域的与门**：``FarmMazeEntry`` = ``And[FarmMazeDomain, FarmMazeTitle]``；
     域一律由 ``FarmMazeDomain`` / ``FarmDomainVerify`` 的 **TemplateMatch** 判（OCR 不作域判据）。
  3. **进域后复核**：``FarmScroll``/``FarmScrollUp`` = ``And[FarmDomainVerify, OCR(迷宫页标记)]``
     —— 复核不过绝不推进（拒绝在错的域上操作）。
  4. **真机帧正反例**：三域各自可稳定区分（自模板 ≥0.8；异域 / 负样本 / 跨 ROI 全 <0.8）。
  5. **OCR 误读韧性**：标题 OCR 判据容忍真机读法（摇电的迷宫 / 摇曳的迷宮 / 摇拽的迷宮），
     且判据里**不含任何域名**（域不由 OCR 判）。
  6. **批量路径**：``_farm_override`` 按域写对的两个模板；未知域不写模板（绝不静默进别的域）。
  7. **守卫 + 破坏实验**：``hooks_57.probe_maze_domain()`` 绿、``prove_red()`` 三处破坏各自变红；
     ``hooks_54``（域 + 行名）仍绿；``drift.check_all()`` 为空；farm 仍非能力缺口。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
AGENT_DIR = REPO_ROOT / "agent"
for _p in (str(TOOLS_DIR), str(REPO_ROOT), str(HOOKS_DIR), str(AGENT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import json  # noqa: E402
import re  # noqa: E402

import batch_plan as bp  # noqa: E402
import hooks_54  # noqa: E402
import hooks_57  # noqa: E402
import side_impl as si  # noqa: E402
from scene import drift  # noqa: E402
from scene import options as so  # noqa: E402
from scene.config import (  # noqa: E402
    DEFAULT_MAZE_DOMAIN,
    MAZE_DOMAIN_TEMPLATES,
    MAZE_DOMAINS,
    MAZE_ROWS,
    maze_domain_template,
)

INTERFACE = REPO_ROOT / "assets" / "interface.json"
FARM = REPO_ROOT / "assets" / "resource" / "pipeline" / "farm.json"
IMAGE_DIR = REPO_ROOT / "assets" / "resource" / "image"

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _farm() -> dict:
    return hooks_57._loads_jsonc(FARM.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. 三个域各有模板（横幅 + 页眉），文件已提交
# ---------------------------------------------------------------------------
def test_templates() -> None:
    print("\n== 1. 三个域各有模板（横幅门控 + 页眉复核），文件已提交 ==")
    check("模板真源覆盖 = 三域（崩坏域/宝物域/幽玄域）",
          tuple(MAZE_DOMAIN_TEMPLATES) == tuple(MAZE_DOMAINS) == ("崩坏域", "宝物域", "幽玄域"),
          f"{tuple(MAZE_DOMAIN_TEMPLATES)}")
    seen = set()
    for d in MAZE_DOMAINS:
        for role in ("banner", "head"):
            rel = maze_domain_template(d, role)
            p = IMAGE_DIR / rel
            check(f"{d}·{role} 模板在场（{rel}）", p.is_file(), f"{p}")
            check(f"{d}·{role} 模板未被其它域串用", rel not in seen, f"{rel}")
            seen.add(rel)
        check(f"{d} 的 banner ≠ head",
              maze_domain_template(d, "banner") != maze_domain_template(d, "head"))
    check("未知域报 KeyError（绝不静默回退到某个域）",
          _raises_key(lambda: maze_domain_template("不存在域", "banner")))
    check("未知角色报 KeyError", _raises_key(lambda: maze_domain_template("崩坏域", "???")))


def _raises_key(fn) -> bool:
    try:
        fn()
    except KeyError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------------------
# 2. 进域 = 标题 ∧ 域的与门；域由 TemplateMatch 判（OCR 不作域判据）
# ---------------------------------------------------------------------------
def test_entry_gate() -> None:
    print("\n== 2. 进域 = 标题 ∧ 域的与门；域判据 = TemplateMatch ==")
    farm = _farm()
    erec = farm["FarmMazeEntry"]["recognition"]
    check("FarmMazeEntry 是 And（标题 ∧ 域）", erec["type"] == "And", f"{erec.get('type')!r}")
    check("all_of = [FarmMazeDomain, FarmMazeTitle]",
          erec["param"]["all_of"] == ["FarmMazeDomain", "FarmMazeTitle"],
          f"{erec['param'].get('all_of')}")
    check("box_index = 0（点横幅域名美术字）", erec["param"]["box_index"] == 0)
    act = farm["FarmMazeEntry"]["action"]
    check("动作 = Click target:true（零偏移）",
          act["type"] == "Click" and act["param"].get("target") is True, f"{act}")

    dom = farm["FarmMazeDomain"]["recognition"]
    check("FarmMazeDomain 是 TemplateMatch（图片判域，非 OCR）",
          dom["type"] == "TemplateMatch", f"{dom.get('type')!r}")
    check("FarmMazeDomain 基线模板 = 缺省域（宝物域）横幅模板",
          dom["param"]["template"] == [maze_domain_template(DEFAULT_MAZE_DOMAIN, "banner")],
          f"{dom['param'].get('template')}")
    check("FarmMazeDomain roi = 左侧轮播位 [0,760,340,315]",
          dom["param"]["roi"] == [0, 760, 340, 315], f"{dom['param'].get('roi')}")
    check("FarmMazeDomain threshold = 0.8",
          dom["param"]["threshold"] == 0.8, f"{dom['param'].get('threshold')}")

    title = farm["FarmMazeTitle"]["recognition"]
    check("FarmMazeTitle 是 OCR（标题只是次要叶）", title["type"] == "OCR")
    check("FarmMazeTitle roi = 左侧轮播位", title["param"]["roi"] == [0, 760, 340, 315])


# ---------------------------------------------------------------------------
# 3. 进域后复核：滚动 = 域复核 ∧ 迷宫页标记
# ---------------------------------------------------------------------------
def test_verify_gate() -> None:
    print("\n== 3. 进域后复核：FarmScroll/FarmScrollUp = 域复核 ∧ 迷宫页标记 ==")
    farm = _farm()
    ver = farm["FarmDomainVerify"]["recognition"]
    check("FarmDomainVerify 是 TemplateMatch（页眉域名美术字）",
          ver["type"] == "TemplateMatch", f"{ver.get('type')!r}")
    check("FarmDomainVerify 基线模板 = 缺省域（宝物域）页眉模板",
          ver["param"]["template"] == [maze_domain_template(DEFAULT_MAZE_DOMAIN, "head")])
    check("FarmDomainVerify roi = 页眉带 [0,90,720,240]",
          ver["param"]["roi"] == [0, 90, 720, 240], f"{ver['param'].get('roi')}")
    for node in ("FarmScroll", "FarmScrollUp"):
        rec = farm[node]["recognition"]
        leaves = rec["param"]["all_of"] if rec["type"] == "And" else []
        check(f"{node} 是 And 且带 FarmDomainVerify 复核叶",
              rec["type"] == "And" and "FarmDomainVerify" in leaves, f"{rec.get('type')!r}")
        ocr = next((lf for lf in leaves if isinstance(lf, dict)), {})
        markers = ocr.get("recognition", {}).get("param", {}).get("expected", [])
        check(f"{node} 的迷宫页标记仍在（的迷宫/临境域/深层域/幽玄域）",
              all(m in markers for m in ("的迷宫", "临境域", "深层域", "幽玄域")), f"{markers}")


# ---------------------------------------------------------------------------
# 4. 真机帧正反例：三域各自可稳定区分
# ---------------------------------------------------------------------------
def test_real_frames() -> None:
    print("\n== 4. 真机帧正反例（720 裁片）：三域各自可稳定区分 ==")
    thr = so.MAZE_TEMPLATE_THRESHOLD
    img, fr = IMAGE_DIR, REPO_ROOT / "tools" / "frames"
    for role, pos, neg in (("banner", hooks_57.BANNER_POS, hooks_57.BANNER_NEG),
                           ("head", hooks_57.HEAD_POS, hooks_57.HEAD_NEG)):
        for d in MAZE_DOMAINS:
            tpl = img / maze_domain_template(d, role)
            s_pos = hooks_57._match(fr / pos[d], tpl)
            check(f"{role}·{d} 自模板命中 ≥ {thr}", s_pos >= thr, f"score={s_pos:.4f}")
            worst_other = max(hooks_57._match(fr / pos[o], tpl)
                              for o in MAZE_DOMAINS if o != d)
            check(f"{role}·{d} 异域全部 < {thr}", worst_other < thr, f"max_other={worst_other:.4f}")
            worst_neg = max(hooks_57._match(fr / n, tpl) for n in neg)
            check(f"{role}·{d} 负样本全部 < {thr}", worst_neg < thr, f"max_neg={worst_neg:.4f}")


# ---------------------------------------------------------------------------
# 5. OCR 误读韧性 + OCR 不作域判据
# ---------------------------------------------------------------------------
def test_ocr_misread_tolerance() -> None:
    print("\n== 5. OCR 误读韧性（标题次叶）+ OCR 不作域判据 ==")
    farm = _farm()
    expected = farm["FarmMazeTitle"]["recognition"]["param"]["expected"]
    for read in ("摇电的迷宫", "摇曳的迷宮", "摇拽的迷宮", "摇曳的迷宫"):
        check(f"标题 OCR 容忍真机读法 {read!r}",
              any(re.search(p, read) for p in expected), f"expected={expected}")
    for p in expected:
        check(f"标题判据 {p!r} 不含域名（OCR 不得判域）",
              not any(d in p for d in MAZE_DOMAINS))
    for node in ("FarmMazeDomain", "FarmDomainVerify"):
        txt = json.dumps(farm[node], ensure_ascii=False)
        check(f"{node} 里没有 OCR 误读串（崩环域/出立域…）",
              not any(m in txt for m in hooks_57.KNOWN_OCR_MISREADS))
    # 真机副标题 OCR 确实读坏（#57 的现场证据），而模板仍 100% 命中。
    check("现场证据：副标题 OCR 误读 崩坏域→崩环域 / 幽玄域→出立域 已登记",
          "崩环域" in hooks_57.KNOWN_OCR_MISREADS and "出立域" in hooks_57.KNOWN_OCR_MISREADS)

    # 域内【行】的定位：仍走 #54 的 OCR 行名 + 几何（pair=below），#54 已证末位锚定 + 丢片段容错。
    # 关键的「误读韧性」证据：真机**行列表**里的域标记**没有被读坏**（读坏发生在横幅副标题上，
    # 那是小号美术字）—— 故行名匹配不需要为误读放宽（放宽反而会命中相邻行）。
    rows = (hooks_54.BENG_ITEMS + hooks_54.DEEP_ITEMS
            + hooks_54.BAOWU_ITEMS + hooks_54.YOUXUAN_ITEMS)
    check("真机行列表里域标记读法正确（幽玄域【… 等行名在 fixture 里）",
          any("幽玄域【" in t for t, _ in hooks_54.YOUXUAN_ITEMS)
          and any("深层域" in t for t, _ in hooks_54.DEEP_ITEMS))
    check("行列表 fixture 里【没有】横幅副标题的误读串（出立域/崩环域）",
          not any(("出立域" in t or "崩环域" in t) for t, _ in rows))
    check("行匹配仍保留 #54 的末位锚定（绝不误选相邻行）",
          si.maze_row_patterns("深层域3【暗】Lv70")[0].endswith("$"))


# ---------------------------------------------------------------------------
# 6. 批量路径：按域写对模板；未知域不写
# ---------------------------------------------------------------------------
def test_batch_override() -> None:
    print("\n== 6. 批量 _farm_override：按域写对模板；未知域不写 ==")
    for d in MAZE_DOMAINS:
        row = MAZE_ROWS[d][0]
        ov = si._farm_override(bp.BatchItem(dungeon=d, difficulty=row, times=1, kind="farm"))
        for node, role in (("FarmMazeDomain", "banner"), ("FarmDomainVerify", "head")):
            rec = ov[node]["recognition"]
            check(f"override({d})·{node} = TemplateMatch/{maze_domain_template(d, role)}",
                  rec["type"] == "TemplateMatch"
                  and rec["param"]["template"] == [maze_domain_template(d, role)],
                  f"{rec['param'].get('template')}")
    check("优先行 崩坏域·临境域深渊之兽·极：FarmMazeDomain = 崩坏域横幅模板",
          si._farm_override(
              bp.BatchItem(dungeon="崩坏域", difficulty="临境域深渊之兽·极", times=1, kind="farm")
          )["FarmMazeDomain"]["recognition"]["param"]["template"]
          == ["maze/domain_beng_banner.png"])
    legacy = si._farm_override(bp.BatchItem(dungeon="光之迷宫", difficulty="光之迷宫",
                                            times=1, kind="farm"))
    check("未知域（光之迷宫）不写任何域模板（绝不静默进某个域）",
          "FarmMazeDomain" not in legacy and "FarmDomainVerify" not in legacy)


# ---------------------------------------------------------------------------
# 7. 守卫 + 破坏实验 + 回归
# ---------------------------------------------------------------------------
def test_guard_and_prove_red() -> None:
    print("\n== 7. 守卫 hooks_57 + 破坏实验；drift 空；#54 仍绿 ==")
    check("hooks_57.probe_maze_domain() 绿", hooks_57.probe_maze_domain() is True)
    check("hooks_57.prove_red() 成立（三处破坏各自变红）", hooks_57.prove_red() is True)
    check("drift.maze_option_drift(interface) == []",
          drift.maze_option_drift(INTERFACE) == [], f"{drift.maze_option_drift(INTERFACE)}")
    check("drift.check_all() == []", drift.check_all(repo_root=REPO_ROOT) == [],
          f"{drift.check_all(repo_root=REPO_ROOT)}")
    check("hooks_54.probe_maze_rows() 仍绿（域 + 行名模型未破）",
          hooks_54.probe_maze_rows() is True)
    check("declared_unreachable('farm') is None", si.declared_unreachable("farm") is None)


def main() -> int:
    print("=" * 76)
    print("#57：迷宫【域】的判定与进入 = 图片/模板匹配（不再用 OCR 判域）")
    print("=" * 76)
    test_templates()
    test_entry_gate()
    test_verify_gate()
    test_real_frames()
    test_ocr_misread_tolerance()
    test_batch_override()
    test_guard_and_prove_red()
    print("\n" + "=" * 76)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
