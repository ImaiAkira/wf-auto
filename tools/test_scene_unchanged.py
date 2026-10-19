# -*- coding: utf-8 -*-
"""离线不变守卫：幻想连战 / 战阵之宴 / 迷宫（#9）+ 离线测试自足（#14）。

本文件属于 test-guards lane，离线、无设备、确定性。它把三条**既有路径**在
场景级复用改造（#1）期间的可观测行为钉死，任何一处被静默改坏都要变红：

  #9 不变守卫
    1. **分派接线**：SpecialEntry 仍接入 FarmDispatch / RaidDispatch / PhantomDispatch，
       且三个分派器都排在 special 业务节点之前、指挥官之后（顺序=优先级）。
    2. **幻想连战**：PhantomEntry 是 DirectHit 别名入口 -> SpecialEntry；PhantomDispatch
       由 batch_mode(kind=phantom) 门控，链上 Done 先于 GiveUp、BattleWait 先于结算推进、
       链尾兜底；所有 Phantom* 节点 next 一律回 SpecialEntry（绝不回 PhantomEntry）。
       agent 侧：phantom_impl.classify / parse_stage 的正例与反例都断言。
    3. **战阵之宴**：RaidEntry 别名入口；RaidDispatch 门控 kind=raid；「再次挑战」先于
       「继续」、RaidBattleWait 必须倒数第二（只高于 RaidWait）；所有 Raid* 节点 next 回
       SpecialEntry。
    4. **迷宫**：FarmEntry 别名入口；FarmDispatch 门控 kind=farm；横幅入口 FarmMazeEntry
       必须排在 FarmScroll/FarmScrollUp 之前；已停用的旧导航节点不回链且 max_hit=1；
       所有 Farm* 节点 next 回 SpecialEntry。
    5. batch_plan.detect_kind / is_farm / is_raid / is_phantom 与 side_impl 的
       入口->种类映射不变。

  #14 离线自足守卫
    四个离线测试文件（test_batch_plan / test_phantom_sets / test_progress /
    test_offline_contract）必须**自己**把 stdout 强成 UTF-8：在【敌意】的 GBK 环境
    （模拟中文 Windows 默认 936 控制台）下单独跑仍须 exit 0，不得依赖外部
    PYTHONIOENCODING。否则末尾的 ✅ 会 UnicodeEncodeError → 假红。

跑法::

    python tools\\test_scene_unchanged.py              # 绿
    python tools\\test_scene_unchanged.py --prove-red  # 故意改坏每条守卫，必须各自变红

帧素材（诚实交代）：spec 的 Testing Decisions 把「页面判据的帧测试」并入主 seam；
本票守护的三条既有路径在 ``tools/frames/`` 里【没有任何真机帧】，因此这里只能对
**管线结构 + agent 纯判定（合成 OCR 项）** 断言，**无法做真机帧回放**。缺的素材是
幻想连战 / 战阵之宴 / 迷宫三条路径的真机页面帧（1080x1920）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"
AGENT_DIR = REPO_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import batch_plan as bp  # noqa: E402
import phantom_impl as ph  # noqa: E402
import side_impl as si  # noqa: E402

# #14-offline-utf8: force this file's own stdout to UTF-8, but ONLY when run as a script.
# It must not leak into importers (hooks_9 -> test_offline_contract), otherwise the #14
# guard would be fooled: test_offline_contract would "pass" the GBK check merely because
# importing this module reconfigured its stdout for it, not because it forced its own.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

# 与四个离线测试文件里逐字一致的自我强制片段（#14）——prove-red 靠它做删除点。
_UTF8_SNIPPET = (
    "# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).\n"
    "for _stream in (sys.stdout, sys.stderr):\n"
    '    if hasattr(_stream, "reconfigure"):\n'
    '        _stream.reconfigure(encoding="utf-8", errors="replace")\n'
)

UTF8_SELF_FORCED_FILES = (
    "test_batch_plan.py",
    "test_phantom_sets.py",
    "test_progress.py",
    "test_offline_contract.py",
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    """去掉 JSONC 的 // 与 /* */ 注释（保持字符串内容），供直接 json.loads。"""
    out: list[str] = []
    state = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i : i + 2] == "//":
                while i < len(text) and text[i] != "\n":
                    i += 1
            elif text[i : i + 2] == "/*":
                i += 2
                while i + 1 < len(text) and text[i : i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:  # 转义
            out.append(ch)
            state = 1
            i += 1
    return "".join(out)


def load_pipeline(name: str, pipeline_dir=None) -> dict:
    base = Path(pipeline_dir) if pipeline_dir else PIPELINE_DIR
    text = (base / name).read_text(encoding="utf-8")
    return json.loads(_strip_jsonc(text))


def _idx(seq, name):
    try:
        return list(seq).index(name)
    except ValueError:
        return None


def _guard_order(seq, before, after, fails, label) -> None:
    """before 必须出现在 after 之前（分派链顺序=优先级，改了会踩坑）。"""
    ib, ia = _idx(seq, before), _idx(seq, after)
    if ib is None:
        fails.append(f"{label}: 分派链缺少 {before}")
    if ia is None:
        fails.append(f"{label}: 分派链缺少 {after}")
    if ib is not None and ia is not None and not (ib < ia):
        fails.append(f"{label}: {before} 必须排在 {after} 之前（顺序=优先级）")


def _guard_alias_entry(pipe: dict, entry: str, fails, label) -> None:
    """别名入口：DirectHit + DoNothing，next 直回统一分派器 SpecialEntry。"""
    node = pipe.get(entry)
    if node is None:
        fails.append(f"{label}: 入口节点 {entry} 缺失（别名入口被删？）")
        return
    if node.get("next") != ["SpecialEntry"]:
        fails.append(f"{label}: {entry}.next 应为 ['SpecialEntry']，实际 {node.get('next')!r}")
    if node.get("recognition", {}).get("type") != "DirectHit":
        fails.append(f"{label}: {entry} 应为 DirectHit 别名入口")
    if node.get("action", {}).get("type") != "DoNothing":
        fails.append(f"{label}: {entry} 应为 DoNothing 别名入口")


def _guard_dispatch(sd: dict, name: str, kind: str, fails, label):
    """种类分派器：Custom batch_mode 门控 + DoNothing 动作；返回该节点。"""
    node = sd.get(name)
    if node is None:
        fails.append(f"{label}: 分派器 {name} 缺失（未接入 SpecialEntry？）")
        return None
    rec = node.get("recognition", {})
    param = rec.get("param", {})
    if rec.get("type") != "Custom" or param.get("custom_recognition") != "batch_mode":
        fails.append(f"{label}: {name} 应由 custom batch_mode 门控")
    if param.get("custom_recognition_param", {}).get("kind") != kind:
        fails.append(f"{label}: {name} kind 应为 {kind!r}")
    if node.get("action", {}).get("type") != "DoNothing":
        fails.append(f"{label}: {name} 应为 DoNothing 分派器")
    return node


def _guard_nexts_home(pipe: dict, prefix: str, fails, label, exclude=()) -> None:
    """所有 <prefix>* 业务节点的 next（若有）一律回 SpecialEntry。"""
    excl = set(exclude)
    for name, node in pipe.items():
        if not name.startswith(prefix) or name in excl:
            continue
        nxt = node.get("next")
        if nxt is None:
            continue  # 子识别 / 无 next 的辅助节点
        if nxt != ["SpecialEntry"]:
            fails.append(f"{label}: {name}.next 应回 ['SpecialEntry']，实际 {nxt!r}")


# ---------------------------------------------------------------------------
# 合成 OCR 帧（与 test_phantom_sets.py 同形状）
# ---------------------------------------------------------------------------
MAIN_ITEMS = [
    ("不可续战", [300, 980, 90, 30]),
    ("推荐编成", [55, 1105, 97, 29]),
    ("FANTASY ONSLAUGHT", [200, 400, 320, 40]),
    ("第3关", [345, 131, 90, 30]),
    ("战斗", [300, 700, 60, 30]),
]
BATTLE_ITEMS = [
    ("时间 09:53", [300, 1200, 80, 30]),
    ("分数 0000001", [430, 1200, 120, 30]),
]
SETTLE_ITEMS = [
    ("QUESTRESULT", [180, 380, 360, 60]),
    ("OK", [330, 640, 60, 30]),
]
# 反例帧：结算奖励条里同时含「战斗分数」「最长滞空时间6秒」（raid 老 bug 的来源）。
REWARD_LOOKALIKE_ITEMS = [
    ("QUESTRESULT", [190, 74, 703, 110]),
    ("战斗分数", [430, 1200, 120, 30]),
    ("最长滞空时间6秒", [300, 1210, 200, 30]),
]
LEVEL_GATE_ITEMS = [
    ("玩家等级达到130后，解锁幻想连战与深渊连战。", [100, 800, 500, 80]),
]


def _guard_classify(ph_mod, label) -> list:
    fails = []
    positives = [
        ("phantom_main", MAIN_ITEMS),
        ("phantom_battle", BATTLE_ITEMS),
        ("phantom_settle", SETTLE_ITEMS),
        ("phantom_level_required", LEVEL_GATE_ITEMS),
    ]
    for want, items in positives:
        got, _info = ph_mod.classify(list(items))
        if got != want:
            fails.append(f"{label}: classify() 对 {want} 正例得到 {got!r}（判据漂了）")

    # 反例必须【正判为结算】，不是靠 unknown/「没看到」蒙混。
    got, _info = ph_mod.classify(list(REWARD_LOOKALIKE_ITEMS))
    if got != "phantom_settle":
        fails.append(
            f"{label}: 含『战斗分数/最长滞空时间』的结算反例帧应正判为 phantom_settle，实际 {got!r}"
        )

    # 只有「分数」没有「时间」不得判成战斗中。
    got, _info = ph_mod.classify([("分数 0000001", [430, 1200, 120, 30])])
    if got == "phantom_battle":
        fails.append(f"{label}: 只有『分数』没有『时间』不得判为战斗中")

    # parse_stage：正例 + 反例。
    if ph_mod.parse_stage([("第3关", [345, 131, 90, 30])]) != 3:
        fails.append(f"{label}: parse_stage 解析『第3关』失败")
    if ph_mod.parse_stage([("推荐编成", [55, 1105, 97, 29])]) is not None:
        fails.append(f"{label}: parse_stage 不应从无关文本解析出关号")
    return fails


# ---------------------------------------------------------------------------
# #9 守卫
# ---------------------------------------------------------------------------
def guard_dispatch_wiring(pipeline_dir=None) -> list:
    fails = []
    label = "统一分派器接线"
    sd = load_pipeline("special_dungeon.json", pipeline_dir)
    entry = sd.get("SpecialEntry", {}).get("next") or []
    for disp in ("FarmDispatch", "RaidDispatch", "PhantomDispatch"):
        if disp not in entry:
            fails.append(f"{label}: SpecialEntry.next 缺少 {disp}（种类分派器未接入）")
        # 分派器必须在 special 业务节点之前，否则 farm/raid/phantom 模式会误走领主战导航。
        _guard_order(entry, disp, "SpecialBonusNo", fails, label)
    # 指挥官负责写 _BATCH_MODE，必须先于分派器。
    _guard_order(entry, "SpecialBatchPlan", "FarmDispatch", fails, label)
    return fails


def guard_phantom(pipeline_dir=None, ph_mod=ph, bp_mod=bp, si_mod=si) -> list:
    fails = []
    label = "幻想连战"
    phantom = load_pipeline("phantom.json", pipeline_dir)
    sd = load_pipeline("special_dungeon.json", pipeline_dir)

    _guard_alias_entry(phantom, "PhantomEntry", fails, label)
    disp = _guard_dispatch(sd, "PhantomDispatch", "phantom", fails, label)
    if disp is not None:
        chain = disp.get("next") or []
        for must in (
            "PhantomDone", "PhantomGiveUp", "PhantomMainFight", "PhantomHubEnter",
            "PhantomSettleContinueChallenge", "PhantomSettleFallback", "PhantomWait",
        ):
            if must not in chain:
                fails.append(f"{label}: PhantomDispatch 链缺少 {must}")
        _guard_order(chain, "PhantomDone", "PhantomGiveUp", fails, label)
        _guard_order(chain, "PhantomBattleWait", "PhantomSettleContinueChallenge", fails, label)
        if chain and chain[-1] != "PhantomWait":
            fails.append(f"{label}: PhantomDispatch 链尾应为 PhantomWait（兜底），实际 {chain[-1]!r}")
    _guard_nexts_home(phantom, "Phantom", fails, label)

    if si_mod._ENTRY_KIND.get("PhantomEntry") != "phantom":
        fails.append(f"{label}: side_impl 入口映射 PhantomEntry->phantom 变了")
    if bp_mod.detect_kind("幻想连战") != "phantom" or not bp_mod.is_phantom("幻想连战"):
        fails.append(f"{label}: detect_kind/is_phantom(幻想连战) 不再是 phantom")
    fails += _guard_classify(ph_mod, label)
    return fails


def guard_raid(pipeline_dir=None, bp_mod=bp, si_mod=si) -> list:
    fails = []
    label = "战阵之宴"
    raid = load_pipeline("raid.json", pipeline_dir)

    _guard_alias_entry(raid, "RaidEntry", fails, label)
    disp = _guard_dispatch(raid, "RaidDispatch", "raid", fails, label)
    if disp is not None:
        chain = disp.get("next") or []
        for must in ("RaidContinueChallenge", "RaidContinue", "RaidBattleWait", "RaidWait"):
            if must not in chain:
                fails.append(f"{label}: RaidDispatch 链缺少 {must}")
        if "[JumpBack]PubChallenge" not in chain:
            fails.append(f"{label}: RaidDispatch 链缺少 [JumpBack]PubChallenge")
        _guard_order(chain, "RaidContinueChallenge", "RaidContinue", fails, label)
        _guard_order(chain, "RaidContinue", "RaidBattleWait", fails, label)
        _guard_order(chain, "RaidBattleWait", "RaidWait", fails, label)
        # RaidBattleWait 必须倒数第二（结算页奖励条含「时间/分数」，排前面会空转死循环）。
        if _idx(chain, "RaidBattleWait") is not None and chain[-2:] != ["RaidBattleWait", "RaidWait"]:
            fails.append(f"{label}: RaidBattleWait 必须倒数第二（只高于 RaidWait），实际链尾 {chain[-2:]!r}")
    _guard_nexts_home(raid, "Raid", fails, label, exclude={"RaidDispatch"})

    if si_mod._ENTRY_KIND.get("RaidEntry") != "raid":
        fails.append(f"{label}: side_impl 入口映射 RaidEntry->raid 变了")
    if bp_mod.detect_kind("战阵之宴") != "raid" or not bp_mod.is_raid("战阵之宴"):
        fails.append(f"{label}: detect_kind/is_raid(战阵之宴) 不再是 raid")
    return fails


def guard_farm(pipeline_dir=None, bp_mod=bp, si_mod=si) -> list:
    fails = []
    label = "迷宫"
    farm = load_pipeline("farm.json", pipeline_dir)

    _guard_alias_entry(farm, "FarmEntry", fails, label)
    disp = _guard_dispatch(farm, "FarmDispatch", "farm", fails, label)
    chain = (disp.get("next") if disp is not None else None) or []
    for must in ("FarmMazeEntry", "FarmFight", "FarmScroll", "FarmScrollUp", "FarmRetry"):
        if must not in chain:
            fails.append(f"{label}: FarmDispatch 链缺少 {must}")
    # 横幅入口必须排在滚动之前，否则会在主城误命中「之迷宫」把主城往下滑。
    _guard_order(chain, "FarmMazeEntry", "FarmScroll", fails, label)
    _guard_order(chain, "FarmMazeEntry", "FarmScrollUp", fails, label)
    _guard_order(chain, "FarmFight", "FarmScroll", fails, label)
    _guard_nexts_home(farm, "Farm", fails, label, exclude={"FarmDispatch"})

    # 已停用的旧「主城→活动→培育道具」导航：不回链、max_hit=1（防空滚 25 次）。
    for dead in ("FarmGrowCard", "FarmEventScrollDown", "FarmEventScrollUp"):
        node = farm.get(dead)
        if node is None:
            continue
        if dead in chain:
            fails.append(f"{label}: 已停用的旧导航 {dead} 不应回到 FarmDispatch 链")
        if node.get("max_hit") != 1:
            fails.append(f"{label}: 已停用的 {dead} max_hit 应为 1（防空滚），实际 {node.get('max_hit')!r}")

    if si_mod._ENTRY_KIND.get("FarmEntry") != "farm":
        fails.append(f"{label}: side_impl 入口映射 FarmEntry->farm 变了")
    if bp_mod.detect_kind("光之迷宫") != "farm" or not bp_mod.is_farm("光之迷宫"):
        fails.append(f"{label}: detect_kind/is_farm(光之迷宫) 不再是 farm")
    return fails


def run_guards(pipeline_dir=None, ph_mod=ph, bp_mod=bp, si_mod=si) -> list:
    """#9 全部守卫；返回失败信息列表（空 = 绿）。供 hooks_9 与本文件复用。"""
    fails: list = []
    fails += guard_dispatch_wiring(pipeline_dir)
    fails += guard_phantom(pipeline_dir, ph_mod, bp_mod, si_mod)
    fails += guard_raid(pipeline_dir, bp_mod, si_mod)
    fails += guard_farm(pipeline_dir, bp_mod, si_mod)
    return fails


# ---------------------------------------------------------------------------
# #14 守卫
# ---------------------------------------------------------------------------
def guard_standalone_utf8(files=None, tools_dir=None) -> list:
    """每个离线测试文件在【敌意 GBK 环境】下单独跑必须 exit 0（不靠外部 env）。

    刻意用 PYTHONIOENCODING=gbk 而不是「删掉该 env」：宿主的默认 locale 可能是
    UTF-8（Linux CI / 开发机），直接删 env 会把缺陷掩盖掉；gbk 让判定与宿主 locale
    无关，且正是中文 Windows 控制台的默认行为。文件自我强制 UTF-8 才能活下来。
    """
    base = Path(tools_dir) if tools_dir else TOOLS_DIR
    names = list(files) if files else list(UTF8_SELF_FORCED_FILES)
    fails = []
    for name in names:
        path = base / name
        if not path.is_file():
            fails.append(f"#14: 找不到离线测试 {path}")
            continue
        env = dict(os.environ)
        env.pop("PYTHONUTF8", None)          # 别让 UTF-8 模式盖掉 gbk
        env.pop("PYTHONIOENCODING", None)
        env["PYTHONIOENCODING"] = "gbk"      # 敌意控制台：只有自我强制才活得下来
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            fails.append(
                f"#14: {name} 在 GBK 控制台单独跑 exit={proc.returncode}"
                f"（仍在依赖外部 PYTHONIOENCODING？）：{' | '.join(tail)}"
            )
    return fails


# ---------------------------------------------------------------------------
# prove-red：故意改坏每条守卫，必须各自变红
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_pipeline(label, mutate, run) -> bool:
    """复制整份 pipeline -> 施加一处破坏 -> 该守卫副本必须变红。"""
    tmp = Path(tempfile.mkdtemp(prefix="wf_guardbreak_"))
    try:
        shutil.copytree(PIPELINE_DIR, tmp / "pipeline")
        d = tmp / "pipeline"
        mutate(d)
        fails = run(d)
        red = len(fails) > 0
        tail = f"  {fails[0]}" if fails else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}{tail}")
        return red
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _broken_ph_module():
    """把 classify 改回「结算误判为战斗」的老 bug 的坏模块。"""
    def broken_classify(items, relogin_phrases=()):
        state, info = ph.classify(items, relogin_phrases)
        if state == "phantom_settle":
            return "phantom_battle", info
        return state, info

    return types.SimpleNamespace(classify=broken_classify, parse_stage=ph.parse_stage)


def prove_red_9() -> int:
    print("\n--prove-red（#9）：逐一改坏三条既有路径 + agent 判定，守卫必须各自变红")
    checks = [
        _break_pipeline(
            "接线：把 PhantomDispatch 从 SpecialEntry.next 摘掉",
            lambda d: _sub(d / "special_dungeon.json", '            "PhantomDispatch",\n', ""),
            lambda d: guard_dispatch_wiring(d),
        ),
        _break_pipeline(
            "幻想：把 PhantomDone 挪到 PhantomGiveUp 之后",
            lambda d: _sub(
                d / "special_dungeon.json",
                '            "PhantomDone",\n            "PhantomGiveUp",',
                '            "PhantomGiveUp",\n            "PhantomDone",',
            ),
            lambda d: guard_phantom(d),
        ),
        _break_pipeline(
            "战阵：把 RaidBattleWait 挪到 RaidContinue 之前（破坏倒数第二）",
            lambda d: _sub(
                d / "raid.json",
                '            "RaidContinue",\n            // 公共结算继续',
                '            "RaidBattleWait",\n            "RaidContinue",\n            // 公共结算继续',
            ),
            lambda d: guard_raid(d),
        ),
        _break_pipeline(
            "迷宫：把横幅入口 FarmMazeEntry 从链里删掉",
            lambda d: _sub(d / "farm.json", '            "FarmMazeEntry",\n', ""),
            lambda d: guard_farm(d),
        ),
    ]
    # agent 判定：注入「结算误判为战斗」的坏模块。
    broken_fails = guard_phantom(None, _broken_ph_module())
    agent_red = len(broken_fails) > 0
    print(f"  [{'PASS' if agent_red else 'FAIL'}] 幻想 agent：把结算误判为战斗中 -> "
          f"{'红' if agent_red else '仍绿'}"
          + (f"  {broken_fails[0]}" if broken_fails else "  （守卫没抓到！）"))
    checks.append(agent_red)

    ok = all(checks)
    print(f"  [{'PASS' if ok else 'FAIL'}] #9 每条守卫都能被打红（红 = 可用信号）")
    return 0 if ok else 1


def prove_red_14() -> int:
    print("\n--prove-red（#14）：去掉某文件的自我 UTF-8 强制，守卫必须变红")
    # 坏副本放在真实 tools/ 下（相对导入仍可用），但名字不以 test_/verify_ 开头，
    # 因此 run_all_tests 的扫描不会把它当成一个测试文件。
    broken = TOOLS_DIR / f"_utf8_prove_red_{os.getpid()}.py"
    src = (TOOLS_DIR / "test_progress.py").read_text(encoding="utf-8")
    if _UTF8_SNIPPET not in src:
        print("  [FAIL] test_progress.py 里找不到 #14 自我强制片段 -- 守卫已与实现脱节")
        return 1
    broken.write_text(
        src.replace(_UTF8_SNIPPET, "# #14 self-forcing deliberately removed (prove-red)\n"),
        encoding="utf-8",
    )
    try:
        green = guard_standalone_utf8(["test_progress.py"]) == []
        red_fails = guard_standalone_utf8([broken.name])
        red = len(red_fails) > 0
        print(f"  [{'PASS' if green else 'FAIL'}] 真实 test_progress.py 通过守卫（绿）")
        print(f"  [{'PASS' if red else 'FAIL'}] 去掉自我强制后守卫变红"
              + (f"  {red_fails[0]}" if red_fails else "  （守卫没抓到！）"))
        ok = green and red
        print(f"  [{'PASS' if ok else 'FAIL'}] #14 守卫既能绿也能红")
        return 0 if ok else 1
    finally:
        try:
            broken.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    if "--prove-red" in sys.argv[1:]:
        rc9 = prove_red_9()
        rc14 = prove_red_14()
        return 0 if (rc9 == 0 and rc14 == 0) else 1

    print("=" * 72)
    print("离线不变守卫：幻想连战 / 战阵之宴 / 迷宫（#9）+ 离线自足（#14）")
    print("=" * 72)

    fails: list = []
    sections = [
        ("#9 统一分派器接线", lambda: guard_dispatch_wiring()),
        ("#9 幻想连战（结构 + agent 判定）", lambda: guard_phantom()),
        ("#9 战阵之宴（结构 + agent 判定）", lambda: guard_raid()),
        ("#9 迷宫（结构 + agent 判定）", lambda: guard_farm()),
        ("#14 四个离线测试自足（GBK 单独跑 exit 0）", lambda: guard_standalone_utf8()),
    ]
    for label, fn in sections:
        sub = fn()
        print(f"  [{'PASS' if not sub else 'FAIL'}] {label}")
        for msg in sub:
            print(f"        {msg}")
        fails += sub

    print("\n" + "=" * 72)
    if fails:
        print(f"结果：★{len(fails)} 项失败★")
        return 1
    print("结果：三条既有路径行为不变、四个离线测试自足 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
