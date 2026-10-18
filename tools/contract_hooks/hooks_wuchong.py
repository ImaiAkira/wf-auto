# -*- coding: utf-8 -*-
"""#56（Phase 4）：五重决战 移植 —— 契约挂点（自动发现，零改既有文件）。

seam：``scene/wuchong.py``（导航关键词 / 模板 / 开关几何 / ★手操节奏参数★ / 流程链 /
★跨模式自动规则★ —— 配置权威）+ ``agent/wuchong_impl.py``（状态机 + 手操战斗引擎 + 开关，
纯机制）+ ``assets/resource/pipeline/wuchong.json``（自包含流水线）+ ``assets/interface.json``
（任务「五重决战」+ 选项）。

七个守卫（对应本票的硬要求；prove-red 见文末）：

1. ``wuchong-config-is-source-of-truth`` —— 配置权威在 ``scene.wuchong``：``wuchong_impl`` 的
   冻结快照 / ``wuchong.json`` 的行·详情模板 / 阈值 / 手操动作 / 开关都从它派生（漂移即红）；
2. ``wuchong-manual-cadence-parameterised`` —— **手操战斗节奏可参数化**：``run_manual_battle``
   真的用了弹板间隔 / 技能间隔 / 每几次弹板放技能 / 连点批量（离线驱动）；★#71★ 手操**持续到正面
   终止点才交还、无固定时长上限**（四个参数，已删「手操连点时长」截断旋钮）；★2026-10-16 运维
   裁决★：不再用战斗 HUD 做判据（已删 ``hud_miss_limit``）—— 认不出的帧一律继续点，只在续关屏 /
   结算页 / 被推出战斗停手；
3. ``wuchong-cross-mode-auto`` —— **跨模式「自动」规则**：只有五重允许手动，其余战斗一律自动
   （``effective_auto_state`` 夹值 + GUI 只有五重任务挂「是否手操」）；
4. ``wuchong-flow-materialised`` —— 流程链在 pipeline 上**按数据落地**：每个流程节点
   ``next`` == 异常前缀 + 本步后继（``scene.wuchong.step_next``），枢纽 == ``hub_next()``，链尾
   DirectHit 兜底且**不设 max_hit**；
5. ``wuchong-banner-distinct`` —— 行 / 详情页用**模板匹配**且两张裁片可靠区分（自证≈1.0，互比 <
   阈值），裁片在仓库资源树下；
6. ``wuchong-classify-positives`` —— ``wuchong_impl.classify`` 对真机形态的合成 OCR 帧正判
   （列表 / 详情 / 模式 / 房间 / 招募弹窗 / 编队 / 结算 / 战斗 / 主城 / 加载）；
7. ``wuchong-no-global-table-growth`` —— **不污染全局页面判据表**：五重只**引用**全局判据、
   绝不往 ``PAGE_RULES`` 塞页面（用注册表 API 证明；#37 的链页集仍是按场景派生）。

prove-red（``python tools\\contract_hooks\\hooks_wuchong.py``）：逐一改坏实现，要求守卫各自变红。
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import shutil
import sys
import tempfile
import textwrap
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
PIPELINE_REL = "assets/resource/pipeline"
WUCHONG_JSON = "wuchong.json"
INTERFACE_REL = "assets/interface.json"
IMAGE_REL = "assets/resource/image"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(AGENT_DIR), str(TOOLS_DIR)):
        if p not in sys.path:
            sys.path.append(p)


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    state = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch); state = 1; i += 1
            elif text[i:i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i:i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i:i + 2] != "*/":
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
            else:
                out.append(ch); i += 1
        elif state == 1:
            out.append(ch)
            if ch == "\\":
                state = 2
            elif ch == '"':
                state = 0
            i += 1
        else:
            out.append(ch); state = 1; i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


def _pipe(root: Path | None = None) -> dict:
    base = (Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL / WUCHONG_JSON
    return _load_jsonc(base)


def _interface(root: Path | None = None) -> dict:
    base = (Path(root) if root is not None else REPO_ROOT) / INTERFACE_REL
    return _load_jsonc(base)


def _node(pipes: dict, name: str) -> dict:
    return pipes.get(name) or {}


def _action_param(node: dict) -> dict:
    return ((node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}


def _tpl_param(node: dict) -> dict:
    return (node.get("recognition") or {}).get("param") or {}


def _param_field_default(p):
    """把一个节奏参数（BattleParam dataclass **或** 纯 tuple）归一成 (field, default)。

    ``scene.wuchong.BATTLE_PARAMS`` 是 BattleParam（field/default 属性）；
    ``wuchong_impl._BATTLE_PARAMS_SNAPSHOT`` 是纯 tuple（field, option, default）。
    """
    field = getattr(p, "field", None)
    default = getattr(p, "default", None)
    if field is None:
        field = p[0]
    if default is None:
        default = p[-1]
    return (field, default)


# ---------------------------------------------------------------------------
# 守卫 1：配置权威在 scene.wuchong
# ---------------------------------------------------------------------------
def _config_failures(root: Path | None = None, impl=None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    if impl is None:
        import wuchong_impl as impl  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _pipe(root)

    for name, snap, truth in (
        ("LORD_TAB", impl._LORD_TAB_SNAPSHOT, w.LORD_TAB),
        ("JOVEN_TAB", impl._JOVEN_TAB_SNAPSHOT, w.JOVEN_TAB),
        ("JOVEN_TAB_Y_MAX", impl._JOVEN_TAB_Y_MAX_SNAPSHOT, w.JOVEN_TAB_Y_MAX),
        ("ROW_NAME", impl._ROW_NAME_SNAPSHOT, w.ROW_NAME),
        ("ROW_TEMPLATE", impl._ROW_TEMPLATE_SNAPSHOT, w.ROW_TEMPLATE),
        ("DETAIL_TEMPLATE", impl._DETAIL_TEMPLATE_SNAPSHOT, w.DETAIL_TEMPLATE),
        ("TEMPLATE_THRESHOLD", impl._TEMPLATE_THRESHOLD_SNAPSHOT, w.TEMPLATE_THRESHOLD),
        ("MANUAL_ALLOWED_SCENES", tuple(impl._MANUAL_ALLOWED_SNAPSHOT), tuple(w.MANUAL_ALLOWED_SCENES)),
        ("AUTO_REQUIRED_SCENES", tuple(impl._AUTO_REQUIRED_SNAPSHOT), tuple(w.AUTO_REQUIRED_SCENES)),
        ("AUTO_ON_RATIO", impl._AUTO_ON_RATIO_SNAPSHOT, w.AUTO_ON_RATIO),
        ("RECRUIT_OPEN_MAX_HIT", impl._RECRUIT_OPEN_MAX_HIT_SNAPSHOT, w.RECRUIT_OPEN_MAX_HIT),
        ("ROOM_WAIT_SEC", impl._ROOM_WAIT_SEC_SNAPSHOT, w.ROOM_WAIT_SEC),
        ("ROOM_SEQUENCE_STATES", tuple(impl._ROOM_SEQUENCE_STATES_SNAPSHOT), tuple(w.ROOM_SEQUENCE_STATES)),
        ("ROOM_LEAVE_STATES", tuple(impl._ROOM_LEAVE_STATES_SNAPSHOT), tuple(w.ROOM_LEAVE_STATES)),
        ("MODAL_BLOCK_STATES", tuple(impl._MODAL_BLOCK_STATES_SNAPSHOT), tuple(w.MODAL_BLOCK_STATES)),
        ("BATTLE_MANUAL_FIELD", impl._BATTLE_MANUAL_FIELD_SNAPSHOT, w.BATTLE_MANUAL_FIELD),
        ("BATTLE_DISABLED_EXPECTED", tuple(impl._BATTLE_DISABLED_EXPECTED_SNAPSHOT), tuple(w.BATTLE_DISABLED_EXPECTED)),
        ("FIGHT_LEDGER_PREFIX", impl._FIGHT_LEDGER_PREFIX_SNAPSHOT, w.FIGHT_LEDGER_PREFIX),
        ("TARGET_FIGHTS_FIELD", impl._TARGET_FIGHTS_FIELD_SNAPSHOT, w.TARGET_FIGHTS_FIELD),
        ("TARGET_FIGHTS_DEFAULT", impl._TARGET_FIGHTS_DEFAULT_SNAPSHOT, w.TARGET_FIGHTS_DEFAULT),
        # ★#72 GAMEOVER 续关（真源 scene.wuchong ②f）★
        ("CONTINUE_LEDGER_PREFIX", impl._CONTINUE_LEDGER_PREFIX_SNAPSHOT, w.CONTINUE_LEDGER_PREFIX),
        ("TARGET_CONTINUES_FIELD", impl._TARGET_CONTINUES_FIELD_SNAPSHOT, w.TARGET_CONTINUES_FIELD),
        ("TARGET_CONTINUES_DEFAULT", impl._TARGET_CONTINUES_DEFAULT_SNAPSHOT, w.TARGET_CONTINUES_DEFAULT),
        ("CONTINUE_TITLE_TEXT", impl._CONTINUE_TITLE_SNAPSHOT, w.CONTINUE_TITLE_TEXT),
        ("CONTINUE_PROMPT_TEXT", impl._CONTINUE_PROMPT_SNAPSHOT, w.CONTINUE_PROMPT_TEXT),
        ("CONTINUE_BTN_TEXT", impl._CONTINUE_BTN_TEXT_SNAPSHOT, w.CONTINUE_BTN_TEXT),
        ("CONTINUE_BTN_ROI", tuple(impl._CONTINUE_BTN_ROI_SNAPSHOT), tuple(w.CONTINUE_BTN_ROI)),
        ("CONTINUE_STUCK_SEC", impl._CONTINUE_STUCK_SEC_SNAPSHOT, w.CONTINUE_STUCK_SEC),
        # ★#71 pin★：手操节奏参数表 / 采样与安全阀常量此前**全仓无人 pin**（快照可漂移不响）。
        #   这里照同口径补：快照/常量必须与真源一致（值从 impl/w 逐项取，绝不硬编码）。
        #   ``_BATTLE_PARAMS_SNAPSHOT`` 是纯 tuple（field, option, default），故按位置取；
        #   ``w.BATTLE_PARAMS`` 是 BattleParam dataclass（field/default 属性）——统一成 (field, default)。
        ("BATTLE_PARAMS", tuple(_param_field_default(p) for p in impl._BATTLE_PARAMS_SNAPSHOT),
         tuple(_param_field_default(p) for p in w.BATTLE_PARAMS)),
        ("CHECK_MIN_GAP_MS", impl.CHECK_MIN_GAP_MS, w.CHECK_MIN_GAP_MS),
        # ★2026-10-16 运维裁决★：HUD_MISS_LIMIT（连续不见 HUD 就停手）已从真源与快照一并删除，
        #   不再有这条 pin（手操不再用战斗 HUD 做判据）。
        ("BATTLE_HEARTBEAT_MS", impl.BATTLE_HEARTBEAT_MS, w.BATTLE_HEARTBEAT_MS),
    ):
        if snap != truth:
            msgs.append(f"配置漂移：wuchong_impl 快照 {name}={snap!r} != scene.wuchong 真源 {truth!r}")

    # ★#71 pin★：BATTLE_AUTO_* 必须与「实际使用」一致。
    #   · 闩锁键：agent 侧 ``_SESSION`` 里**必须**真的有真源键（A1 用字面量 "battle_auto_off_tried"
    #     作 key，故这里断言「字面量键 == 真源键」）。
    if w.BATTLE_AUTO_ONCE_KEY not in impl._SESSION:
        msgs.append(
            f"配置漂移：agent.wuchong_impl._SESSION 缺真源闩锁键 {w.BATTLE_AUTO_ONCE_KEY!r}"
            f"（BATTLE_AUTO_ONCE_KEY 与实现脱节）"
        )
    #   · 节点名：真源声明的节点**必须**在流程链里落地（否则声明了一个从不被走的出口）。
    #     （pipeline/界面接线由 hooks_auto_outside 的新守卫负责，这里**不重复**。）
    if w.BATTLE_AUTO_NODE not in w.flow_step_nodes():
        msgs.append(
            f"配置漂移：scene.wuchong.BATTLE_AUTO_NODE={w.BATTLE_AUTO_NODE!r} 不在流程链里"
            f"（声明的战斗页关自动节点未接线）"
        )
    #   · 作用域标记：与闩锁键互相印证（"battle" ∈ "battle_auto_off_tried"）——两个真源常量不得脱节。
    if not (isinstance(w.BATTLE_AUTO_SCOPE, str) and w.BATTLE_AUTO_SCOPE):
        msgs.append("配置漂移：scene.wuchong.BATTLE_AUTO_SCOPE 必须是非空字符串")
    elif w.BATTLE_AUTO_SCOPE not in w.BATTLE_AUTO_ONCE_KEY:
        msgs.append(
            f"配置漂移：BATTLE_AUTO_SCOPE={w.BATTLE_AUTO_SCOPE!r} 未体现在闩锁键 "
            f"{w.BATTLE_AUTO_ONCE_KEY!r} 里（真源常量互相脱节）"
        )

    # pipeline 的行/详情模板 + 阈值必须来自配置。
    row = _tpl_param(_node(pipes, "WuchongRowBanner"))
    if list(row.get("template") or []) != [w.ROW_TEMPLATE]:
        msgs.append(f"配置漂移：wuchong.json::WuchongRowBanner.template={row.get('template')!r} != {[w.ROW_TEMPLATE]!r}")
    det = _tpl_param(_node(pipes, "WuchongDetailBanner"))
    if list(det.get("template") or []) != [w.DETAIL_TEMPLATE]:
        msgs.append(f"配置漂移：wuchong.json::WuchongDetailBanner.template={det.get('template')!r} != {[w.DETAIL_TEMPLATE]!r}")

    # 手操动作节点必须指向 wuchong_battle；开关节点必须指向 wuchong_switch。
    if ((_node(pipes, "WuchongBattle").get("action") or {}).get("param") or {}).get("custom_action") != "wuchong_battle":
        msgs.append("配置漂移：wuchong.json::WuchongBattle 未指向 custom_action=wuchong_battle")
    if _action_param(_node(pipes, "WuchongTeamAutoSet")).get("which") != "auto":
        msgs.append("配置漂移：wuchong.json::WuchongTeamAutoSet 不是 which=auto")
    return msgs


def probe_wuchong_config_is_source_of_truth() -> bool:
    return _config_failures() == []


# ---------------------------------------------------------------------------
# 守卫 2：手操战斗节奏可参数化
# ---------------------------------------------------------------------------
def _invoke(spec, t):
    """把「常量 / 零参 callable / 单参 callable(假时钟)」统一成一个无参取值。"""
    if callable(spec):
        try:
            return spec()
        except TypeError:
            return spec(t)
    return spec


def _run_core(mod, cadence_kw):
    """用**假时钟/假副作用**驱动 run_manual_battle，返回 transcript + 观测记录。

    ★#71★：hooks 改用新契约的 7 个关键字（``verdict`` / ``manual_on`` / ``stopping``，
    **不再有** ``is_battle``）—— 停止由**正面页面判据**驱动。``cadence_kw`` 里以 ``_`` 开头
    的键是**驱动开关**（不进 Cadence）：``_verdict``（str 或 callable(t)）、``_manual_on``、
    ``_stopping``。``obs["burst_ts"]`` 记下每串连点的**假时刻** —— 守卫据此断言
    「t=1800s 的点击数 > t=25s（旧截断点）」，证明**没有固定时长截断**。
    """
    obs = {"bursts": [], "swipes": [], "sleeps": [], "burst_ts": [], "t": 0.0}

    def now():
        return obs["t"]

    def burst_click(point, times, gap):
        obs["burst_ts"].append(obs["t"])
        obs["bursts"].append((tuple(point), int(times), int(gap)))
        obs["t"] += 0.05

    def swipe(begin, end, ms):
        obs["swipes"].append((tuple(begin), tuple(end), int(ms)))
        obs["t"] += 0.0

    def verdict():
        return _invoke(cadence_kw.get("_verdict", "battle"), obs["t"])

    def manual_on():
        return bool(_invoke(cadence_kw.get("_manual_on", True), obs["t"]))

    def stopping():
        return bool(_invoke(cadence_kw.get("_stopping", lambda: False), obs["t"]))

    def sleep(sec):
        obs["sleeps"].append(float(sec))
        obs["t"] += float(sec)

    hooks = mod.BattleHooks(
        burst_click=burst_click, swipe=swipe, verdict=verdict,
        manual_on=manual_on, sleep=sleep, now=now, stopping=stopping,
    )
    cadence = mod.Cadence(**{k: v for k, v in cadence_kw.items() if not k.startswith("_")})
    result = mod.run_manual_battle(hooks, cadence)
    result["obs"] = obs
    return result


def _cadence_base(**over):
    """9 字段基线（★#71★：已去 ``duration_s``、``check_every`` → ``check_min_gap_ms``；
    ★2026-10-16 运维裁决★：再去 ``hud_miss_limit`` —— 判据不再依赖 HUD）。

    ★#71★：因为循环**无固定时长上限**，基线必须用一个**正面判据**收尾（否则离线忙等）：
    默认 ``_verdict`` 在假时钟 2s 处转 ``over``；需要更长/更短的驱动各自覆盖它。
    """
    base = dict(
        center=(360, 600), flipper=(360, 1067), dist=160, swipe_ms=300,
        flipper_gap_ms=220, skill_gap_ms=0, skill_every=6, burst=10,
        check_min_gap_ms=2,
        _verdict=lambda t: "continue" if t < 2.0 else "over",
    )
    base.update(over)
    return base


#: 新契约里 ``stopped`` 的**合法取值集**（★2026-10-16 运维裁决★：``hud_miss``/``yield`` 已删，
#: 新增 ``left`` = 被推出战斗；绝无 "duration"）。
_STOPPED_ALLOWED = {"manual_off", "battle_over", "left", "stopped"}

#: ★#71★ 已删的固定时长截断旋钮（活代码/数据里再出现即红）。
_TRUNCATION_KNOB_RE = re.compile(r"duration_s|手操连点时长")
_TRUNCATION_NAME_RE = re.compile(r"duration|timeout|deadline")


def _live_py_names(tree):
    """AST 里的「活」标识（Name/Attr/arg/keyword/**非 docstring** 的字符串常量）。

    注释不在 AST 里、docstring 被显式跳过 —— 故「解释为什么删掉 duration_s」的注释不算
    违规，而**真的把旋钮写回去**（字段名/键/参数）会命中。
    """
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skip.add(id(body[0].value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, ast.arg):
            out.append(node.arg)
        elif isinstance(node, ast.keyword):
            out.append(node.arg or "")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append(node.value)
    return out


def _truncation_static_failures(mod) -> list:
    """★#71 (d)-静态★：实现里不得残留任何「固定时长截断」的墙钟上限。"""
    msgs: list[str] = []
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(mod.run_manual_battle)))
        live = _live_py_names(tree)
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"无法解析 run_manual_battle 源码：{exc!r}")
    else:
        bad = sorted({n for n in live if _TRUNCATION_NAME_RE.search(n)})
        if bad:
            msgs.append(f"run_manual_battle 仍含墙钟上限标识 {bad}（#71 要求持续到结算/失败、无截断）")
    fields = getattr(getattr(mod, "Cadence", None), "__dataclass_fields__", {}) or {}
    bad_fields = sorted(f for f in fields if _TRUNCATION_NAME_RE.search(f))
    if bad_fields:
        msgs.append(f"Cadence 仍含截断字段 {bad_fields}（应只有节奏/安全阀字段）")
    return msgs


def _knob_file_failures(root: Path | None = None) -> list:
    """★#71 (d)-静态★：四份真源文件里不得再出现已删旋钮 ``duration_s`` / ``手操连点时长``。

    ★``docs/spec/wuchong-spec.md`` 是**历史规格**（记录 D1 的旧行为），**必须放过**★。
    ``.py`` 走 AST（跳过注释/docstring、只看活代码/数据）；``.json`` 去 JSONC 注释后按文本查。
    """
    base = Path(root) if root is not None else REPO_ROOT
    msgs: list[str] = []
    targets = (
        (base / "scene" / "wuchong.py", True),
        (base / "agent" / "wuchong_impl.py", True),
        (base / INTERFACE_REL, False),
        (base / PIPELINE_REL / WUCHONG_JSON, False),
    )
    for path, is_py in targets:
        if not path.is_file():
            msgs.append(f"截断旋钮检查目标缺失：{path}")
            continue
        text = path.read_text(encoding="utf-8")
        if is_py:
            try:
                names = _live_py_names(ast.parse(text))
            except SyntaxError as exc:
                msgs.append(f"{path.name} 解析失败：{exc!r}")
                continue
            hits = sorted({n for n in names if _TRUNCATION_KNOB_RE.search(n)})
        else:
            hits = sorted({m.group(0) for m in _TRUNCATION_KNOB_RE.finditer(_strip_jsonc(text))})
        if hits:
            msgs.append(f"{path.name} 仍含已删的截断旋钮 {hits}（#71：手操无固定时长截断）")
    return msgs


#: ★#71 (h)★ page_verdict 正判/反判用的合成 OCR 帧（720 空间）。
#: 纯战斗 HUD：含**真机双空格**那条分数（帧 auto_battle_hud_hit.png）。
_BATTLE_HUD_ITEMS = [
    ("时间 28:03", [300, 1180, 120, 40]),
    ("分数  00166756407", [300, 1180, 220, 40]),
]
#: 关卡失败页：GAMEOVER +「是否续关？」+ **底部照样画着**时间/分数（★F1/F2 反回归★：
#: 失败页的「放弃/续关」那一行与弹板点 (360,1067) 同一行，绝不能被判成「还在战斗」）。
_GAMEOVER_ITEMS = [
    ("GAMEOVER", [280, 300, 160, 50]),
    ("是否续关?", [300, 520, 120, 40]),
    ("时间 12:34", [300, 1180, 120, 40]),
    ("分数  00166756407", [300, 1180, 220, 40]),
]
_SETTLE_ITEMS = [
    ("QUESTRESULT", [280, 200, 220, 50]),
    ("获得道具", [300, 420, 100, 40]),
    ("OK", [360, 900, 60, 40]),
]
_LOADING_ITEMS = [("请耐心等待", [300, 600, 200, 40])]
_TEAM_PAGE_ITEMS = [
    ("Party 1", [100, 200, 90, 30]),
    ("SET 1", [100, 260, 70, 30]),
    ("挑战", [360, 1092, 70, 40]),
]


def _verdict_failures(mod) -> list:
    """★#71 (h)★ ★2026-10-16 运维裁决★：``page_verdict`` 的三值正面判据（离线逐帧求值）。

    ``over``（续关屏 / 结算页）、``left``（被推出战斗 = 任一已知非战斗页）、``continue``（其余一切，
    含真战斗帧 / 认不出 / 加载 → **继续点**）。★判据不再依赖战斗 HUD★。
    """
    msgs: list[str] = []
    cases = (
        ("纯战斗 HUD（真机双空格 `分数  00166756407`）", _BATTLE_HUD_ITEMS, mod.PAGE_CONTINUE),
        ("GAMEOVER 续关屏（含底部时间/分数）", _GAMEOVER_ITEMS, mod.PAGE_OVER),
        ("结算页", _SETTLE_ITEMS, mod.PAGE_OVER),
        ("加载页（→ 继续点，绝不停手）", _LOADING_ITEMS, mod.PAGE_CONTINUE),
        ("编队页（→ 被推出战斗）", _TEAM_PAGE_ITEMS, mod.PAGE_LEFT),
    )
    for label, items, want in cases:
        got = mod.page_verdict(items)
        if got != want:
            msgs.append(f"page_verdict 误判：{label} → {got!r}（期望 {want!r}）")
    return msgs


def _cadence_failures(mod) -> list:
    msgs: list[str] = []

    # (a) burst 真的作为「一次原生连点几下」传下去；flipper_gap 真的作为间隔传下去。
    r = _run_core(mod, _cadence_base(burst=4, flipper_gap_ms=250, skill_every=100))
    for _p, times, gap in r["obs"]["bursts"]:
        if times != 4:
            msgs.append(f"节奏参数未生效：burst=4 但 burst_click times={times}")
            break
    for _p, times, gap in r["obs"]["bursts"]:
        if gap != 250:
            msgs.append(f"节奏参数未生效：flipper_gap_ms=250 但 burst_click gap={gap}")
            break
    if not r["obs"]["bursts"]:
        msgs.append("手操未连点弹板（bursts 为空）")

    # (b) 每几次弹板放技能：skill_every=3、burst=1 → 技能发数 = floor(总点数/3)。
    r2 = _run_core(mod, _cadence_base(burst=1, skill_every=3, skill_gap_ms=0))
    taps = r2["taps"]
    expect = taps // 3
    if len(r2["swipes"]) != expect:
        msgs.append(f"技能节奏未按 skill_every 触发：taps={taps} 期望 {expect} 发，实际 {len(r2['swipes'])}")
    # 三向轮换：技能1左 / 技能2上 / 技能3右。
    if r2["swipes"]:
        d0 = r2["swipes"][0][1]
        if d0 != (360 - 160, 600):
            msgs.append(f"技能1应为左滑 {(360 - 160, 600)}，实际 {d0}")
        if len(r2["swipes"]) >= 2 and r2["swipes"][1][1] != (360, 600 - 160):
            msgs.append("技能2应为上滑 (360,440)")
        if len(r2["swipes"]) >= 3 and r2["swipes"][2][1] != (360 + 160, 600):
            msgs.append("技能3应为右滑 (520,600)")

    # (c) 技能间隔：skill_gap_ms=500 → 每次技能后 sleep(0.5)。
    r3 = _run_core(mod, _cadence_base(burst=1, skill_every=2, skill_gap_ms=500))
    if not r3["obs"]["sleeps"] or abs(r3["obs"]["sleeps"][0] - 0.5) > 1e-9:
        msgs.append(f"技能间隔未生效：期望 sleep(0.5)，实际 {r3['obs']['sleeps'][:2]}")

    # ★#71 (d)★：把「连点时长生效」换成「★无固定时长截断★」——旧实现（duration_s 到点交出）
    #   的反面。四道子检查都用**新契约的正面判据**驱动（不再有 duration_s / check_every /
    #   hud_miss_limit）：
    #   (d-1 行为) verdict 恒 continue、假时钟推进到 ≥1800s（旧截断点 25s 的 72 倍）→ 断言
    #            t=1800s 的**累计点击数 > t=25s 的**；3600s 后 verdict 转 over 收尾
    #            （证明引擎是被**正面判据**收的，不是被时间上限收的）；stopped 绝不为 "duration"。
    r_long = _run_core(
        mod,
        _cadence_base(burst=1, skill_every=100,
                      _verdict=lambda t: "continue" if t < 3600.0 else "over"),
    )

    def _taps_by(cut):
        return sum(
            times
            for ts, (_p, times, _g) in zip(r_long["obs"]["burst_ts"], r_long["obs"]["bursts"])
            if ts <= cut
        )

    n25, n1800 = _taps_by(25.0), _taps_by(1800.0)
    if not n1800 > n25:
        msgs.append(
            f"手操被固定时长截断：t=1800s 累计点击数 {n1800} 未 > t=25s 的 {n25}"
            f"（旧截断点 25s 之后就停了 = 没有「持续到正面终止点」）"
        )
    if r_long["stopped"] == "duration":
        msgs.append(
            f"手操以固定时长截断收尾（stopped='duration'，应到续关屏/结算页/被推出战斗才交还）：{r_long!r}"
        )

    #   (d-2 静态) run_manual_battle 活代码无 duration/timeout/deadline；Cadence 字段名同；
    #            四份真源（scene/agent/界面/流水线）不得再出现 duration_s / 手操连点时长。
    msgs.extend(_truncation_static_failures(mod))
    msgs.extend(_knob_file_failures())

    #   (d-3 词表) 若干驱动下收集的 stopped 取值集合 ⊆ 合法集，且绝不含 "duration"。
    #   ★2026-10-16 运维裁决★：合法集 = {manual_off, battle_over, left, stopped}；旧 hud_miss/yield 已删。
    seen_stops = set()
    for kw in (
        _cadence_base(),
        _cadence_base(_verdict="left"),
        _cadence_base(_verdict="continue", check_min_gap_ms=5, _stopping=lambda t: t >= 1.0),
        _cadence_base(_verdict="continue", _manual_on=lambda t: t < 5.0),
        _cadence_base(_verdict="continue", _stopping=lambda t: True),
    ):
        seen_stops.add(_run_core(mod, kw)["stopped"])
    if seen_stops - _STOPPED_ALLOWED:
        msgs.append(
            f"stopped 出现新契约外的取值 {sorted(seen_stops - _STOPPED_ALLOWED)}"
            f"（合法集 {sorted(_STOPPED_ALLOWED)}）"
        )
    if "duration" in seen_stops:
        msgs.append("stopped 出现 'duration'（#71 已删固定时长截断，绝不允许再以它收尾）")

    # (e) ★2026-10-16 运维裁决★：HUD 缺失 / unknown / loading 帧（= 判据 continue）→ **继续点**，
    #   绝不 yield / hud_miss（旧安全阀已删）。用「continue 到 3s 后转 over」驱动：断言引擎在
    #   继续点（taps > 0），停手是 over（而非 hud_miss/yield），且停手后零新增点击（先判据后点击）。
    r_cont = _run_core(mod, _cadence_base(burst=1, skill_every=100, check_min_gap_ms=5,
                                          _verdict=lambda t: "continue" if t < 3.0 else "over"))
    if r_cont["stopped"] not in (None, "battle_over"):
        msgs.append(f"认不出的帧竟停手（应继续点直到正面终止点）：stopped={r_cont['stopped']!r}")
    if r_cont["taps"] == 0:
        msgs.append("continue 帧驱动下未点板（应继续点 —— 驱动无效）")
    if any(ts >= 3.0 for ts in r_cont["obs"]["burst_ts"]):
        msgs.append("判出 over 后仍有新增点击（先判据后点击失败）")

    # ★三个正面终止点各自命中即停、且停手时零新增点击（先判据后点击 = 承重安全属性）★：
    for want_v, want_stop, label in (
        ("over", "battle_over", "续关屏/结算页"),
        ("left", "left", "被推出战斗"),
    ):
        rr = _run_core(mod, _cadence_base(burst=1, skill_every=100, check_min_gap_ms=5,
                                          _verdict=lambda t, w=want_v: "continue" if t < 2.0 else w))
        if rr["stopped"] != want_stop:
            msgs.append(f"{label} 未按正面终止点停手：stopped={rr['stopped']!r}（期望 {want_stop!r}）")
        if rr["taps"] == 0:
            msgs.append(f"{label} 之前一次弹板都没点（驱动无效）")
        if any(ts >= 2.0 for ts in rr["obs"]["burst_ts"]):
            msgs.append(f"{label} 停手后仍有新增点击（先判据后点击失败 = 真机误点风险）")

    # (f) 可切换：manual=False 时手操动作不点任何东西。
    msgs.extend(_manual_off_failures(mod))
    # ★#71 续 (f)★：战斗中「切回自动」（manual_on() 转假）→ 立刻停手、此后**零新增点击**。
    r_off = _run_core(mod, _cadence_base(burst=1, skill_every=100, _verdict="continue",
                                         _manual_on=lambda t: t < 5.0))
    if r_off["stopped"] != "manual_off":
        msgs.append(f"战斗中切回自动未立刻停手：stopped={r_off['stopped']!r}（期望 manual_off）")
    if any(ts >= 5.0 for ts in r_off["obs"]["burst_ts"]):
        msgs.append("切回自动后仍有新增点击（manual_off 应在下一轮立即生效、此后零点击）")

    # ★#71 (g)★：框架请求停止任务（stopping() 真）→ stopped="stopped" 且**立即停**（零点击）。
    r_stop = _run_core(mod, _cadence_base(burst=1, skill_every=100, _verdict="continue",
                                          _stopping=lambda t: True))
    if r_stop["stopped"] != "stopped":
        msgs.append(f"stopping() 真未立即停：stopped={r_stop['stopped']!r}（期望 stopped）")
    if r_stop["taps"] != 0:
        msgs.append(f"stopping() 真后仍落点击（taps={r_stop['taps']}，应立即交还）")

    # ★#71 (h)★：page_verdict 三值正判 / 反判（合成 OCR items；续关屏与弹板点同一行的反回归）。
    msgs.extend(_verdict_failures(mod))
    return msgs


def _manual_off_failures(mod, action_cls=None) -> list:
    """自动模式（manual=False）下手操动作绝不连点。"""
    msgs: list[str] = []
    fired = {"live": 0}

    real_live = getattr(mod, "_run_battle_live", None)
    if real_live is None:
        return ["wuchong_impl 缺 _run_battle_live（手操入口被改名）"]

    class _Argv:
        custom_action_param = json.dumps({"manual": False})

    class _Ctx:
        pass

    factory = action_cls or mod.WuchongBattleAction
    try:
        mod._run_battle_live = lambda context, cadence: fired.__setitem__("live", fired["live"] + 1)
        factory().run(_Ctx(), _Argv())
    finally:
        mod._run_battle_live = real_live
    if fired["live"] != 0:
        msgs.append("自动模式（manual=False）仍启动了手操引擎（应不点任何东西）")
    return msgs


def probe_wuchong_manual_cadence_parameterised() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _cadence_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 3：跨模式「自动」规则
# ---------------------------------------------------------------------------
def _cross_mode_failures(effective_fn=None, manual_fn=None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    eff = effective_fn or w.effective_auto_state
    man = manual_fn or w.manual_allowed
    msgs: list[str] = []

    # 只有五重允许手动；其余一律夹回「开」。
    if eff("wuchong", False) is not False:
        msgs.append("五重决战应允许关自动（手动=自动关）")
    if eff("wuchong", True) is not True:
        msgs.append("五重决战开自动应被尊重")
    for s in w.AUTO_REQUIRED_SCENES:
        if eff(s, False) is not True:
            msgs.append(f"场景 {s!r} 关自动应被强制夹回「开」（其他所有战斗都要勾选自动）")
        if man(s):
            msgs.append(f"场景 {s!r} 不应允许手动（只有五重）")
    if set(w.MANUAL_ALLOWED_SCENES) & set(w.AUTO_REQUIRED_SCENES):
        msgs.append("MANUAL_ALLOWED_SCENES 与 AUTO_REQUIRED_SCENES 不应有交集")

    # GUI：只有「五重决战」任务挂「是否手操」。
    iface = _interface()
    tasks = {t.get("name"): (t.get("option") or []) for t in iface.get("task") or []}
    for name, opts in tasks.items():
        if "是否手操" in opts and name != "五重决战":
            msgs.append(f"任务 {name!r} 不应挂「是否手操」（只有五重决战允许手动）")
    if "是否手操" not in tasks.get("五重决战", []):
        msgs.append("任务「五重决战」缺「是否手操」选项")

    # 选项「是否手操」的手操 case 必须真的把编队页自动设成关（on=false）。
    block = (iface.get("option") or {}).get("是否手操") or {}
    hand = next((c for c in block.get("cases") or [] if c.get("name") == "手操"), None)
    if hand is None:
        msgs.append("选项「是否手操」缺 case「手操」")
    else:
        ov = hand.get("pipeline_override") or {}
        p = (((ov.get("WuchongTeamAutoSet") or {}).get("action") or {}).get("param") or {}).get("custom_action_param") or {}
        if p.get("on") is not False:
            msgs.append("「手操」case 未把 WuchongTeamAutoSet 的自动设为关（on=false）")

    # 机制侧开关动作也必须尊重规则。
    msgs.extend(_switch_clamp_failures())
    return msgs


def _switch_clamp_failures() -> list:
    """wuchong_switch 对非五重场景的关自动意图必须被夹回「开」。"""
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    msgs: list[str] = []
    if impl.effective_auto_state("phantom", False) is not True:
        msgs.append("wuchong_impl.effective_auto_state 未把非五重场景夹回「开」")
    if impl.effective_auto_state("wuchong", False) is not False:
        msgs.append("wuchong_impl.effective_auto_state 误把五重的手动夹掉")
    return msgs


def probe_wuchong_cross_mode_auto() -> bool:
    return _cross_mode_failures() == []


# ---------------------------------------------------------------------------
# 守卫 4：流程链在 pipeline 上按数据落地
# ---------------------------------------------------------------------------
def _flow_failures(root: Path | None = None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    pipes = _pipe(root)
    msgs: list[str] = []

    hub = _node(pipes, "WuchongEntry").get("next")
    if list(hub or []) != list(w.hub_next()):
        msgs.append(f"枢纽漂移：WuchongEntry.next != scene.wuchong.hub_next()（实际前 6={list(hub or [])[:6]}）")

    for step in w.FLOW_STEPS:
        node = _node(pipes, step.node)
        if not node:
            msgs.append(f"流程节点缺失：{step.node}")
            continue
        expect = list(w.step_next(step.node) or [])
        if list(node.get("next") or []) != expect:
            msgs.append(
                f"流程节点漂移：{step.node}.next != 异常前缀+本步后继"
                f"（实际前 4={list(node.get('next') or [])[:4]}）"
            )

    # 每个异常引用都必须有定义（不在本文件就在 common.json）。
    files = {}
    for p in sorted(((Path(root) if root is not None else REPO_ROOT) / PIPELINE_REL).glob("*.json")):
        files[p.name] = _load_jsonc(p)
    known = set()
    for data in files.values():
        known |= set(data.keys())
    for ref in w.FLOW_EXCEPTIONS:
        name = ref[len("[JumpBack]"):] if ref.startswith("[JumpBack]") else ref
        if name not in known:
            msgs.append(f"异常引用悬空：{ref} 在 pipeline 里没有定义")

    # 链尾 DirectHit 兜底且不设 max_hit。
    tail = _node(pipes, "WuchongWait")
    if (tail.get("recognition") or {}).get("type") != "DirectHit":
        msgs.append("链尾 WuchongWait 不是 DirectHit（枢纽会因全不命中而失败）")
    if "max_hit" in tail:
        msgs.append("链尾 WuchongWait 不应设 max_hit（用尽后会被永久跳过）")

    # 业务节点 next 一律回 WuchongEntry（除 StopTask 出口）。
    for name, node in pipes.items():
        if name in ("WuchongClick", "WuchongSwipe"):
            continue
        nxt = node.get("next")
        if nxt is None:
            continue
        if (node.get("action") or {}).get("type") == "StopTask":
            if nxt != []:
                msgs.append(f"{name} 是 StopTask 出口，next 应为 []")
            continue
        if name in ("WuchongEntry",):
            continue
        if name not in set(w.flow_step_nodes()) | {"WuchongWait"}:
            # 辅助/事件节点必须回 WuchongEntry。
            if nxt != ["WuchongEntry"]:
                msgs.append(f"{name}.next 应回 ['WuchongEntry']，实际 {nxt!r}")
    return msgs


def probe_wuchong_flow_materialised() -> bool:
    return _flow_failures() == []


# ---------------------------------------------------------------------------
# 守卫 5：行 / 详情页用模板匹配且两张裁片可靠区分
# ---------------------------------------------------------------------------
def _zncc(a, b) -> float:
    import numpy as np

    a = a - a.mean(); b = b - b.mean()
    den = float(((a * a).sum() * (b * b).sum()) ** 0.5)
    return float((a * b).sum() / den) if den else 0.0


def _banner_failures(tpl_pair=None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    row_rel, det_rel = tpl_pair or (w.ROW_TEMPLATE, w.DETAIL_TEMPLATE)
    for rel in (row_rel, det_rel):
        if not (REPO_ROOT / IMAGE_REL / rel).is_file():
            msgs.append(f"裁片缺失：{IMAGE_REL}/{rel} 不在仓库资源树下")

    for node_name in ("WuchongRowBanner", "WuchongDetailBanner"):
        rec = _node(_pipe(), node_name).get("recognition") or {}
        if rec.get("type") != "TemplateMatch":
            msgs.append(f"{node_name} 必须用模板匹配（TemplateMatch），不得用 OCR")
        thr = (rec.get("param") or {}).get("threshold")
        if not isinstance(thr, (int, float)):
            msgs.append(f"{node_name} 缺阈值")

    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        def gray(rel):
            im = Image.open(REPO_ROOT / IMAGE_REL / rel).convert("L")
            return np.asarray(im, dtype=np.float64)

        cross = abs(_zncc(gray(row_rel), gray(det_rel)))
        thr = w.TEMPLATE_THRESHOLD
        if cross >= thr:
            msgs.append(f"裁片不可区分：{row_rel} vs {det_rel} ZNCC={cross:.4f} >= 阈值 {thr}")
        if cross > 0.95:
            msgs.append(f"裁片几乎相同：{row_rel} vs {det_rel} ZNCC={cross:.4f}（裁片选错？）")
        # 非空白断言（模板不能是纯色块）。
        for rel in (row_rel, det_rel):
            g = gray(rel)
            if float(g.std()) < 3.0:
                msgs.append(f"裁片疑似空白：{IMAGE_REL}/{rel} std={float(g.std()):.2f}")
    except Exception:  # noqa: BLE001
        pass
    return msgs


def probe_wuchong_banner_distinct() -> bool:
    return _banner_failures() == []


# ---------------------------------------------------------------------------
# 守卫 6：classify 正例
# ---------------------------------------------------------------------------
def _classify_failures(mod) -> list:
    msgs: list[str] = []
    cases = [
        ("wuchong_lord_list", [
            ("更新列表", [600, 470, 110, 40]),
            ("降临讨伐", [760, 600, 180, 50]),
            ("五重决战", [300, 930, 140, 40]),
            ("五王连战", [300, 990, 150, 45]),
        ]),
        ("wuchong_detail", [
            ("五重决战 超级", [310, 690, 300, 45]),
            ("推荐编成", [60, 1110, 100, 30]),
            ("战斗", [90, 750, 40, 20]),
        ]),
        ("wuchong_mode", [("单人游戏", [180, 790, 260, 50]), ("多人游戏", [560, 1270, 280, 50])]),
        ("wuchong_room", [("房间号码", [100, 300, 200, 40]), ("招募", [400, 900, 80, 40]), ("复制", [500, 900, 80, 40])]),
        ("wuchong_recruit_dialog", [("招募方式", [200, 700, 200, 40]), ("开始招募", [522, 919, 120, 40])]),
        ("wuchong_team", [("Party E", [120, 900, 120, 40]), ("挑战", [300, 1600, 120, 60])]),
        ("wuchong_settle", [("QUESTRESULT", [180, 380, 360, 60]), ("返回房间", [446, 1183, 117, 33])]),
        ("wuchong_battle", [("时间 09:53", [300, 1200, 80, 30]), ("分数 0000001", [430, 1200, 120, 30])]),
        ("main_city", [("修行之道", [15, 725, 161, 45]), ("成长任务", [47, 368, 118, 33]), ("当前进度", [366, 928, 60, 20]), ("活动", [80, 1120, 62, 34]), ("领主战", [569, 1121, 78, 29])]),
        ("loading", [("请耐心等待", [100, 600, 200, 40])]),
    ]
    for want, items in cases:
        got, _info = mod.classify([(t, b) for t, b in items])
        if got != want:
            msgs.append(f"classify 正例：{want!r} 得到 {got!r}")

    # 反例：结算奖励条的「战斗分数」不得判成战斗中。
    got, _ = mod.classify([("战斗分数", [430, 1200, 120, 30]), ("最长滞空时间6秒", [300, 1210, 200, 30])])
    if got == "wuchong_battle":
        msgs.append("classify：只有『战斗分数』不得判为战斗中")
    # 反例：领主战列表页含「房间号码」字样，但无「复制/招募」→ 不判成房间。
    got, _ = mod.classify([("房间号码", [400, 850, 200, 40]), ("更新列表", [600, 470, 110, 40]), ("五王连战", [300, 990, 150, 45])])
    if got == "wuchong_room":
        msgs.append("classify：领主战列表页不得判成共斗房间页")
    return msgs


def probe_wuchong_classify_positives() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _classify_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 7：不污染全局页面判据表
# ---------------------------------------------------------------------------
def _growth_failures(names) -> list:
    return [f"五重不得把页面判据加进全局表：{n!r}" for n in names if ("五重" in n or "wuchong" in n)]


def _no_global_growth_failures() -> list:
    _paths()
    from scene.page_rules import (  # noqa: PLC0415
        PAGE_RULES,
        PageRuleRegistry,
        _EXPECTED_DEFAULT_CHAIN_STEP_PAGES,
        chain_step_pages,
        duplicate_rule_names,
    )
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415
    from scene import wuchong as w  # noqa: PLC0415

    msgs = _growth_failures([r.name for r in PAGE_RULES])
    if duplicate_rule_names():
        msgs.append(f"全局判据表出现重名：{duplicate_rule_names()}")
    if tuple(chain_step_pages()) != tuple(_EXPECTED_DEFAULT_CHAIN_STEP_PAGES):
        msgs.append("缺省场景（领主战族）的链上步骤页集被五重污染（应为派生结果，不是累积并集）")

    # 用**新注册表**证明：五重只引用全局判据、不新增页面；且 per-scene 派生不累积。
    reg = PageRuleRegistry(list(PAGE_RULES))
    reg.register(LORD_BATTLE.family.id, LORD_BATTLE.family.页序, LORD_BATTLE.overrides)
    sel = w.register_wuchong(reg)
    known = {r.name for r in PAGE_RULES}
    if any(p not in known for p in sel.pages):
        msgs.append("五重选取了全局注册表里不存在的页面判据（场景不得发明页面）")
    if tuple(reg.chain_step_pages(w.MANUAL_SCENE)) != tuple(w.SCENE_PAGES):
        msgs.append("五重的链上页集 != 它自己的选取（per-scene 派生被改成累积并集？）")
    # 登记五重【不得】改变缺省场景（领主战族）的页集（不累积、不互相污染）。
    if tuple(reg.chain_step_pages()) != tuple(LORD_BATTLE.family.页序):
        msgs.append("登记五重后缺省场景（领主战族）的页集被改变（场景互相污染）")
    # 五重的具名覆盖必须 owner + reason 非空（ADR-0003：覆盖不得隐形）。
    for o in sel.overrides:
        if not getattr(o, "owner", "") or not getattr(o, "reason", ""):
            msgs.append("五重的覆盖缺 owner/reason（覆盖必须具名显式）")
    return msgs


def probe_wuchong_no_global_table_growth() -> bool:
    return _no_global_growth_failures() == []


# ---------------------------------------------------------------------------
# 守卫 8：招募方式弹窗在屏 → 先走「开始招募」，绝不先走「自动」开关（coop-fix2 P0）
# ---------------------------------------------------------------------------
#: 合成 OCR 帧（离线可求值，形同真机 005_trace05 招募方式弹窗 / 房间页 / 加载）。
_RECRUIT_DIALOG_ITEMS = [("招募方式", [200, 700, 200, 40]), ("开始招募", [522, 919, 120, 40])]
_ROOM_ITEMS = [
    ("房间号码", [100, 300, 200, 40]),
    ("招募", [400, 900, 80, 40]),
    ("复制", [500, 900, 80, 40]),
    ("未进行招募", [200, 700, 160, 40]),
]
_ROOM_RECRUITING_ITEMS = [
    ("房间号码", [100, 300, 200, 40]),
    ("招募", [400, 900, 80, 40]),
    ("复制", [500, 900, 80, 40]),
]
_LOADING_ITEMS = [("健康游戏忠告", [200, 500, 300, 40])]
_ITEMS_BY_STATE = {
    "wuchong_room": _ROOM_ITEMS,
    "wuchong_recruit_dialog": _RECRUIT_DIALOG_ITEMS,
    "loading": _LOADING_ITEMS,
}


class _CtxStub:
    """最小 context 桩（动作只经 monkeypatch 的抓屏/OCR/点击，不真正触设备）。"""


class _ActArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param)


class _RecArgv:
    def __init__(self, task_id, param):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": task_id})()
        self.custom_recognition_param = json.dumps(param)


def _recruit_order_failures(root: Path | None = None) -> list:
    """弹窗在屏时必须先走 RecruitStart（P0 顺序）。

    ★#103 改口径（B 方案）★：业务节点的 next 只剩 2 项
    （``[WuchongInXxx, [JumpBack]SceneEnterWuchong]``），后继不再写在业务节点上 ——
    「谁先被评估」改由**枢纽 ``WuchongEntry.next`` 的候选顺序**决定，而它 = 
    ``scene.wuchong.hub_next()`` = ``FLOW_STEPS`` 的**声明顺序**。
    故本守卫改钉**真源的声明顺序**（JSON 与真源是否一致由 :func:`_flow_failures` 负责）。
    """
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    pipes = _pipe(root)
    msgs: list[str] = []
    hub = list(w.hub_next())
    need = ("WuchongRecruitOpen", "WuchongRecruitStart", "WuchongTeamAutoSet")
    missing = [n for n in need if n not in hub]
    if missing:
        msgs.append(f"枢纽候选里缺 {missing}（招募弹窗没有出路 / 房间开关不在候选里）")
    elif hub.index("WuchongTeamAutoSet") < hub.index("WuchongRecruitStart"):
        msgs.append(
            "枢纽候选里 WuchongTeamAutoSet 排在 WuchongRecruitStart 之前 → "
            "招募方式弹窗一出现就被自动开关点掉（P0 回归）"
        )
    if list(_node(pipes, "WuchongRecruitOpen").get("next") or []) != list(
        w.step_next("WuchongRecruitOpen") or []
    ):
        msgs.append("WuchongRecruitOpen.next != scene.wuchong.step_next（数据/流水线不同步）")
    return msgs


def _switch_modal_guard_failures(mod) -> list:
    """驱动真实 WuchongSwitchAction：弹窗在屏时必须【拒绝点击】（点背板 = 点错东西）。

    stub 化抓屏/OCR/定位/点击：OCR 帧 = 招募方式弹窗（classify → wuchong_recruit_dialog）。
    """
    msgs: list[str] = []
    clicks: list = []
    saved = {k: getattr(mod, k) for k in ("_grab", "ocr_all", "MODAL_BLOCK_STATES")}
    sw = mod.auto_switch
    saved_sw = {k: getattr(sw, k) for k in
                ("dismiss_cont_dialog", "template_box", "locate_switch_label", "read_switch_state", "_click_box")}
    try:
        mod._grab = lambda context: object()
        mod.ocr_all = lambda context, image, entry="OcrTask": list(_RECRUIT_DIALOG_ITEMS)
        sw.dismiss_cont_dialog = lambda *a, **k: False
        sw.template_box = lambda *a, **k: None
        sw.locate_switch_label = lambda items, label, tbox=None: [630, 102, 43, 27]
        sw.read_switch_state = lambda image, label, box: False  # 当前 off，期望 on → 会点
        sw._click_box = lambda context, action, x, y: (clicks.append((int(x), int(y))) or True)
        mod.WuchongSwitchAction().run(_CtxStub(), _ActArgv({"which": "auto", "on": True}))
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        for k, v in saved_sw.items():
            setattr(sw, k, v)
    if clicks:
        msgs.append(f"弹窗在屏时开关动作仍点击了 {clicks}（点位落在弹窗背板上 = 点错东西）")
    return msgs


def probe_wuchong_recruit_dialog_before_auto() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _recruit_order_failures() == [] and _switch_modal_guard_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 9：共斗房有出路 —— 有界重试 + 有界收工（coop-fix2 P0）
# ---------------------------------------------------------------------------
def _room_exit_failures(root: Path | None = None) -> list:
    """共斗房必须有出路 —— 有界重试 + 有界收工（coop-fix2 P0）。

    ★#103 改口径（B 方案）★：出路的候选挂在**枢纽**（``hub_next()``）上，不再写在
    ``WuchongRoomWait.next`` 里；本守卫改为钉「枢纽候选集里有房间的三条出路」+ 形状同步。
    """
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    pipes = _pipe(root)
    msgs: list[str] = []
    hub = list(w.hub_next())
    for name in ("WuchongRecruitOpen", "WuchongRecruitStart", "WuchongTeamChallenge", "WuchongCoopChallenge"):
        if name not in hub:
            msgs.append(f"枢纽候选里缺 {name}（房间没有出路 / 招募无法开启 / 人齐无动作 / 多人开不了战）")
    room = _node(pipes, "WuchongRoomWait") or {}
    if list(room.get("next") or []) != list(w.step_next("WuchongRoomWait") or []):
        msgs.append("WuchongRoomWait.next != scene.wuchong.step_next（数据/流水线不同步）")

    ro_node = _node(pipes, "WuchongRecruitOpen") or {}
    # ★#79 反转★：以前这里要求「必须有界 max_hit」—— 那是**错的设计**：MAA 的 `max_hit` 是
    #   **整任务共享**计数，真机 18:33:45 / 18:45:44 / 19:06:16 恰好点满 3 次后，第 4 间房起
    #   `WuchongRecruitOpen` 被静默跳过 → 房间再也招不到人 → 干等 room_wait_sec 收工
    #   （运维看到的就是「打了几把画面卡死」）。现在要求：**不许 max_hit** + 必须有时间闩锁。
    mh = ro_node.get("max_hit")
    if mh is not None:
        msgs.append(
            f"WuchongRecruitOpen 带了任务级 max_hit={mh!r}（整任务共享计数 → 第 4 间房起本节点静默失效，"
            "房间永远招不到人 = 打几把就卡死）；应改用时间闩锁 latch=recruit_open"
        )
    ro_latch = (((ro_node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}).get("latch")
    if ro_latch != "recruit_open":
        msgs.append(f"WuchongRecruitOpen 缺时间闩锁（latch={ro_latch!r}，应为 'recruit_open'）")
    st_node = _node(pipes, "WuchongStaleTeam") or {}
    if st_node.get("max_hit") is not None:
        msgs.append(
            f"WuchongStaleTeam 带了任务级 max_hit={st_node.get('max_hit')!r}（烧完就不再点「返回」→ 卡在 stale 编队页）"
        )

    gp_param = ((_node(pipes, "WuchongGiveUp").get("recognition") or {}).get("param") or {}).get(
        "custom_recognition_param"
    ) or {}
    rws = gp_param.get("room_wait_sec")
    if not isinstance(rws, (int, float)) or rws <= 0:
        msgs.append(f"WuchongGiveUp 未声明正数 room_wait_sec（房间没有有界出口）：{rws!r}")
    elif float(rws) != float(w.ROOM_WAIT_SEC):
        msgs.append(f"WuchongGiveUp.room_wait_sec={rws} != scene.ROOM_WAIT_SEC={w.ROOM_WAIT_SEC}")
    return msgs


def _room_clock_failures(mod) -> list:
    """共斗房停留时钟：进房起算；loading/弹窗不清零；真正离开才清零。"""
    msgs: list[str] = []
    with mod._LOCK:
        mod._SESSION["task_id"] = 560047
        mod._SESSION["room_first_ts"] = 0.0
        mod._SESSION["last_state"] = None
        mod._SESSION["last_observe_ts"] = 0.0

    def feed(state: str) -> None:
        with mod._LOCK:
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
        mod._observe(state, {}, _ITEMS_BY_STATE.get(state, []))

    feed("wuchong_room")
    t0 = mod._SESSION["room_first_ts"]
    if not t0:
        msgs.append("进入共斗房后停留时钟没有起算（room_first_ts 仍为 0）")
    for st in ("loading", "wuchong_room", "wuchong_recruit_dialog", "wuchong_room", "unknown"):
        feed(st)
        if mod._SESSION["room_first_ts"] != t0:
            msgs.append(f"过渡帧 state={st} 把共斗房停留时钟清零了（{t0} -> {mod._SESSION['room_first_ts']}）")
            break
    for st in mod.ROOM_LEAVE_STATES:
        with mod._LOCK:
            mod._SESSION["room_first_ts"] = 0.0
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
        feed("wuchong_room")
        feed(st)
        if mod._SESSION["room_first_ts"] != 0.0:
            msgs.append(f"真正离开的房间状态 state={st} 没有清零停留时钟")
    for st in ("loading", "unknown"):
        if st in mod.ROOM_LEAVE_STATES:
            msgs.append(f"过渡帧 {st} 被当成「已离开房间」（ROOM_LEAVE_STATES）")
    return msgs


def _room_bounded_stop_failures(mod) -> list:
    """离线复现：房间死等 → 倒拨到超过 room_wait_sec → 真实 wuchong_giveup 命中并点名共斗房。"""
    msgs: list[str] = []

    def drive(state: str, backdate: float):
        real = mod._ocr
        try:
            mod._ocr = lambda context, image, entry="OcrTask": list(_ITEMS_BY_STATE[state])
            with mod._LOCK:
                mod._SESSION["task_id"] = 560047
                mod._SESSION["start_ts"] = time.monotonic()
                mod._SESSION["last_progress_ts"] = time.monotonic()
                mod._SESSION["room_first_ts"] = time.monotonic() - float(backdate)
                mod._SESSION["last_state"] = None
                mod._SESSION["last_observe_ts"] = 0.0
                mod._SESSION["unknown_count"] = 0
            res = mod.WuchongGiveUpRecognition().analyze(
                None, _RecArgv(560047, {"ocr_entry": "OcrTask", "room_wait_sec": 300})
            )
            return (res.box == [0, 0, 0, 0]), str((res.detail or {}).get("reason") or "")
        finally:
            mod._ocr = real

    hit, reason = drive("wuchong_room", backdate=400.0)
    if not hit:
        msgs.append("共斗房停留 400s（>300s）仍未命中收工（房间长时间开不了战却不收工 = 空转）")
    if "共斗房" not in reason:
        msgs.append(f"收工原因未点明『共斗房』：{reason!r}")

    hit_fresh, reason_fresh = drive("wuchong_room", backdate=1.0)
    if hit_fresh:
        msgs.append(f"刚进共斗房就误收工：{reason_fresh!r}")
    return msgs


def probe_wuchong_room_has_exit() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return (
        _room_exit_failures() == []
        and _room_clock_failures(impl) == []
        and _room_bounded_stop_failures(impl) == []
    )


# ---------------------------------------------------------------------------
# 守卫 10：手操引擎关 ⇒ WuchongBattle 绝不被选中 + 动作只用场景几何 / 带原因停（coop-fix2 P0）
# ---------------------------------------------------------------------------
def _expected_of(rec: dict):
    return ((rec.get("param") or {}).get("expected"))


def _battle_gate_failures(root: Path | None = None) -> list:
    """raw 默认 WuchongBattle 关闭；「自动」case 关它、「手操」case 开启且 manual=true。"""
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    pipes = _pipe(root)
    msgs: list[str] = []
    raw = (_node(pipes, "WuchongBattle").get("recognition") or {})
    if _expected_of(raw) != list(w.BATTLE_DISABLED_EXPECTED):
        msgs.append(
            f"raw WuchongBattle 未关闭（手操引擎关时会被反复重选）：recognition={raw!r}，"
            f"应为 expected={list(w.BATTLE_DISABLED_EXPECTED)!r}"
        )

    iface = _interface(root)
    block = (iface.get("option") or {}).get("是否手操") or {}
    cases = {c.get("name"): c for c in block.get("cases") or []}
    auto = (cases.get("自动") or {}).get("pipeline_override") or {}
    hand = (cases.get("手操") or {}).get("pipeline_override") or {}

    auto_rec = ((auto.get("WuchongBattle") or {}).get("recognition") or {})
    if _expected_of(auto_rec) != list(w.BATTLE_DISABLED_EXPECTED):
        msgs.append("「自动」case 未关闭 WuchongBattle（手操引擎关时应 __NONE__）")

    hand_node = hand.get("WuchongBattle") or {}
    hand_rec = hand_node.get("recognition") or {}
    if _expected_of(hand_rec) == list(w.BATTLE_DISABLED_EXPECTED) or not hand_rec:
        msgs.append("「手操」case 未开启 WuchongBattle（手操引擎启用 = 识别应回到 wuchong_state）")
    cap = ((hand_node.get("action") or {}).get("param") or {}).get("custom_action_param") or {}
    if cap.get(w.BATTLE_MANUAL_FIELD) is not True:
        msgs.append(
            f"「手操」case 未把 WuchongBattle 动作 {w.BATTLE_MANUAL_FIELD!r} 设为 true"
            f"（手动应确定性来自选项）：{cap!r}"
        )
    return msgs


def _battle_geometry_action_failures(mod) -> list:
    """驱动真实动作：manual=True 只用场景几何；manual=False 带原因停下（不启动引擎）。"""
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    helper = getattr(mod, "battle_geometry", None)
    if helper is None:
        return ["wuchong_impl 缺 battle_geometry（动作几何真源被删）"]
    c, f = helper()
    if tuple(c) != tuple(w.WUCHONG_BATTLE.center):
        msgs.append(f"battle_geometry 中心 {c} != scene.WUCHONG_BATTLE.center {w.WUCHONG_BATTLE.center}")
    if tuple(f) != tuple(w.WUCHONG_BATTLE.flipper):
        msgs.append(f"battle_geometry 弹板点 {f} != scene.WUCHONG_BATTLE.flipper {w.WUCHONG_BATTLE.flipper}")

    seen: dict = {}
    real = mod._run_battle_live
    try:
        def _capture(context, cadence):
            seen["center"] = tuple(cadence.center)
            seen["flipper"] = tuple(cadence.flipper)
            # ★#71★：stopped 必须是新契约的合法值（旧写死 "duration" 已随截断删除）。
            return {"taps": 0, "swipes": [], "checks": 0, "stopped": "battle_over"}

        with mod._LOCK:
            mod._SESSION["manual"] = False  # 会话手动关；动作必须靠选项 param=manual:true
        mod._run_battle_live = _capture
        mod.WuchongBattleAction().run(_CtxStub(), _ActArgv({w.BATTLE_MANUAL_FIELD: True}))
    finally:
        mod._run_battle_live = real
    if seen.get("center") != tuple(w.WUCHONG_BATTLE.center):
        msgs.append(f"manual=True 动作未用场景中心（center={seen.get('center')}）")
    if seen.get("flipper") != tuple(w.WUCHONG_BATTLE.flipper):
        msgs.append(f"manual=True 动作未用场景弹板点（flipper={seen.get('flipper')}）")

    fired = {"live": 0}
    try:
        mod._run_battle_live = lambda context, cadence: fired.__setitem__("live", fired["live"] + 1)
        with mod._LOCK:
            mod._SESSION["manual"] = False
        mod.WuchongBattleAction().run(_CtxStub(), _ActArgv({w.BATTLE_MANUAL_FIELD: False}))
    finally:
        mod._run_battle_live = real
    if fired["live"] != 0:
        msgs.append("manual=off 仍启动了手操引擎（应带原因停下、不点任何东西）")
    return msgs


def probe_wuchong_battle_engine_gated() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _battle_gate_failures() == [] and _battle_geometry_action_failures(impl) == []


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _temp_assets() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook56_"))
    (root / "assets").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "assets" / "resource", root / "assets" / "resource")
    shutil.copy2(REPO_ROOT / INTERFACE_REL, root / INTERFACE_REL)
    return root


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_and_check(label: str, mutate, run) -> bool:
    root = _temp_assets()
    try:
        mutate(root)
        red = len(run(root)) > 0
        print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}")
        return red
    finally:
        shutil.rmtree(root, ignore_errors=True)


class _BrokenCadence:
    """★#71 破坏实验★：把【固定时长截断】加回去的坏手操。

    本坏实现 = 真实实现 **+ 一行** ``deadline = now + 1s``，到点就 ``stopped="duration"``
    （正是 #71 从真源 / 快照 / 界面一并删掉的截断旋钮）。其余节奏（burst / flipper_gap /
    skill_every / skill_gap / 三值页面判据 / 手动开关优先）逐字照抄 —— 故**只有「无截断」这一条**
    会变红，破坏点单一、可归因。（★2026-10-16★：判据已换成三值 ``page_verdict``，本坏实现同步。）
    """

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def run_manual_battle(self, hooks, cadence):  # noqa: N802
        burst = max(1, int(cadence.burst))
        gap = max(20, int(cadence.flipper_gap_ms))
        skill_every = int(cadence.skill_every)
        cx, cy = tuple(cadence.center)
        dirs = (
            (cx - int(cadence.dist), cy),
            (cx, cy - int(cadence.dist)),
            (cx + int(cadence.dist), cy),
        )
        check_gap = max(0.0, int(cadence.check_min_gap_ms) / 1000.0)
        t0 = hooks.now()
        deadline = t0 + 1.0            # ★坏：加回固定时长截断（#71 已删）★
        last_check = t0 - check_gap
        taps = 0
        swipes: list = []
        checks = 0
        skill_i = 0
        next_skill_at = skill_every if skill_every > 0 else 0

        def _stop(reason_value, reason_text):
            return {"taps": taps, "swipes": swipes, "checks": checks,
                    "stopped": reason_value, "reason": reason_text}

        while True:
            if hooks.now() >= deadline:            # ★坏：到点即交出（正确实现没有这一行）★
                return _stop("duration", "坏：固定时长截断")
            if hooks.stopping():
                return _stop("stopped", "框架请求停止任务")
            if not hooks.manual_on():
                return _stop("manual_off", "手操已关（切回自动）")
            now = hooks.now()
            if now - last_check >= check_gap:
                last_check = now
                checks += 1
                v = hooks.verdict()
                if v == self._mod.PAGE_OVER:
                    return _stop("battle_over", "续关屏 / 结算页")
                if v == self._mod.PAGE_LEFT:
                    return _stop("left", "被推出战斗")
                # PAGE_CONTINUE → 继续点。
            hooks.burst_click(tuple(cadence.flipper), burst, gap)
            taps += burst
            if next_skill_at and taps >= next_skill_at:
                next_skill_at += skill_every
                end = dirs[skill_i % 3]
                hooks.swipe((cx, cy), end, int(cadence.swipe_ms))
                swipes.append(((cx, cy), end))
                skill_i += 1
                hooks.sleep(max(0.0, int(cadence.skill_gap_ms) / 1000.0))


class _BrokenSkillCadence:
    """破坏实验（#56 守卫 2(b) 的牙齿，★#71 保留★）：忽略 ``skill_every`` 的坏手操。

    永远不放技能（``skill_every`` 被忽略）—— 正确的实现会按 ``skill_every`` 发技能。
    #71 把 ``_BrokenCadence`` 改成了「加回固定时长截断」（守卫 2(d) 的牙齿），
    本条**不能一起丢**：否则「每几次弹板放技能」这条参数化断言就没有反例了。
    """

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def run_manual_battle(self, hooks, cadence):  # noqa: N802
        # 永远不放技能（skill_every 被忽略）—— 正确的实现会按 skill_every 发技能。
        return {"taps": 3, "swipes": [], "checks": 0, "stopped": "battle_over",
                "reason": "坏：忽略 skill_every"}


#: prove-red 锚点（coop-fix2）：真机 P0 修复前后的两种形态。
#: ★#103 起 RecruitOpen / RoomWait 的 next 已被收进接口层（业务 next 只有 2 项），
#:   那两条 prove-red 改为**改真源声明顺序**（见 prove_red 里对 w.FLOW_STEPS 的猴子补丁），
#:   故原来的文本锚点 ``_RECRUIT_ORDER_ANCHOR`` / ``_ROOM_EXIT_ANCHOR`` 已删除。★
_BATTLE_RAW_ANCHOR = (
    '        "recognition": { "type": "OCR", "param": { "expected": ["__NONE__"] } },\n'
    '        "action": {\n'
    '            "type": "Custom",\n'
    '            "param": { "custom_action": "wuchong_battle", "custom_action_param": {} }\n'
    '        },'
)
_BATTLE_RAW_BROKEN = (
    '        "recognition": { "type": "Custom", "param": { "custom_recognition": "wuchong_state", '
    '"custom_recognition_param": { "state": "wuchong_battle", "ocr_entry": "OcrTask" } } },\n'
    '        "action": {\n'
    '            "type": "Custom",\n'
    '            "param": { "custom_action": "wuchong_battle", "custom_action_param": {} }\n'
    '        },'
)


def prove_red() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_wuchong prove-red：逐一破坏实现，要求守卫各自变红")
    green = (
        probe_wuchong_config_is_source_of_truth() is True
        and probe_wuchong_manual_cadence_parameterised() is True
        and probe_wuchong_cross_mode_auto() is True
        and probe_wuchong_flow_materialised() is True
        and probe_wuchong_banner_distinct() is True
        and probe_wuchong_classify_positives() is True
        and probe_wuchong_no_global_table_growth() is True
        and probe_wuchong_recruit_dialog_before_auto() is True
        and probe_wuchong_room_has_exit() is True
        and probe_wuchong_battle_engine_gated() is True
        and probe_wuchong_mode_gates() is True
        and probe_wuchong_room_before_battle() is True
        and probe_wuchong_switch_readable_without_pil() is True
        and probe_wuchong_manual_survives_option_merge() is True
        and probe_wuchong_fight_count() is True
        and probe_wuchong_interface_no_duplicate_keys() is True
        and probe_wuchong_latch_retries() is True
        and probe_wuchong_mode_default_multi() is True
        and probe_wuchong_giveup_out_of_fight() is True
        and probe_wuchong_unknown_not_counted_in_fight() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：二十个守卫全绿")
    if not green:
        return False

    pipe = lambda r: r / PIPELINE_REL / WUCHONG_JSON  # noqa: E731
    iface = lambda r: r / INTERFACE_REL  # noqa: E731

    checks = [
        _break_and_check(
            "配置漂移：改 wuchong.json 的行模板名",
            lambda r: _sub(pipe(r), '"wuchong/row_wuwang.png"', '"wuchong/wrong.png"'),
            lambda r: _config_failures(r),
        ),
        _break_and_check(
            "流程漂移：把枢纽的链尾 WuchongWait 换掉",
            lambda r: _sub(pipe(r), '            "WuchongWait"\n', '            "WuchongNavLord"\n'),
            lambda r: _flow_failures(r),
        ),
        _break_and_check(
            "跨模式：把「是否手操」选项挂到别的任务上",
            lambda r: _sub(iface(r), '"name": "自动过主线",\n            "entry": "AutoPush",\n            "option": [',
                           '"name": "自动过主线",\n            "entry": "AutoPush",\n            "option": [\n                "是否手操",'),
            lambda r: _cross_mode_failures_for(r),
        ),
    ]

    # CADENCE：坏实现（忽略 skill_every）必须被抓到。
    # ★#71★：本票把坏实现换成「把 #71 删掉的【固定时长截断】加回去」（_BrokenCadence 新实现
    #   = 真实现 + deadline=now+1s）—— 破坏点正是「无截断」，故 red 必须仍成立。
    red_cadence = len(_cadence_failures(_BrokenCadence(impl))) > 0
    print(f"  [{'PASS' if red_cadence else 'FAIL'}] 节奏参数：加回固定时长截断（duration）-> "
          f"{'红' if red_cadence else '仍绿'}")
    checks.append(red_cadence)

    # ★#71 保留（原 #56 的牙齿，别丢）★：忽略 skill_every 的坏手操 → 守卫 2(b) 必须变红。
    red_skill = len(_cadence_failures(_BrokenSkillCadence(impl))) > 0
    print(f"  [{'PASS' if red_skill else 'FAIL'}] 节奏参数：忽略 skill_every -> "
          f"{'红' if red_skill else '仍绿'}")
    checks.append(red_skill)

    # CADENCE 可切换：坏实现（自动模式仍启动手操）必须被抓到。
    red_manual = len(
        _manual_off_failures(impl, action_cls=lambda: _BrokenManualAction(impl))
    ) > 0
    print(f"  [{'PASS' if red_manual else 'FAIL'}] 可切换：自动模式仍启动手操 -> "
          f"{'红' if red_manual else '仍绿'}")
    checks.append(red_manual)

    # 裁片可区分：拿自己跟自己比（几乎相同）必须被点出。
    red_banner = len(_banner_failures(tpl_pair=(impl._ROW_TEMPLATE_SNAPSHOT, impl._ROW_TEMPLATE_SNAPSHOT))) > 0
    print(f"  [{'PASS' if red_banner else 'FAIL'}] 裁片：行模板 vs 自身（几乎相同）-> "
          f"{'红' if red_banner else '仍绿'}")
    checks.append(red_banner)

    # classify：把结算误判为战斗中必须被抓到。
    red_classify = len(_classify_failures(_BrokenClassify(impl))) > 0
    print(f"  [{'PASS' if red_classify else 'FAIL'}] classify：把结算误判为战斗中 -> "
          f"{'红' if red_classify else '仍绿'}")
    checks.append(red_classify)

    # 全局表污染：往全局判据表塞一条五重页面 -> 红。
    red_growth = len(_growth_failures(["五重枢纽"])) > 0
    print(f"  [{'PASS' if red_growth else 'FAIL'}] 全局表污染：塞一条五重页面 -> "
          f"{'红' if red_growth else '仍绿'}")
    checks.append(red_growth)

    # ★#103 改口径★ 弹窗顺序回归：把 FLOW_STEPS 里 RecruitStart / TeamAutoSet 的**声明顺序**
    #   调回旧序（枢纽候选顺序随之翻转 → 弹窗会被自动开关点掉 = 真机 P0）→ 守卫变红。
    from scene import wuchong as w  # noqa: PLC0415

    saved_steps = w.FLOW_STEPS
    steps = list(saved_steps)
    try:
        i = next(i for i, s in enumerate(steps) if s.node == "WuchongRecruitStart")
        j = next(i for i, s in enumerate(steps) if s.node == "WuchongTeamAutoSet")
        steps[i], steps[j] = steps[j], steps[i]
        w.FLOW_STEPS = tuple(steps)
        msgs = _recruit_order_failures()
        red_order = len(msgs) > 0
        print(
            f"  [{'PASS' if red_order else 'FAIL'}] 弹窗顺序回归（枢纽候选里 TeamAutoSet 排在 RecruitStart 前）-> "
            f"{'红' if red_order else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        w.FLOW_STEPS = saved_steps
    checks.append(red_order)

    # ★#103 改口径★ 房间死胡同回归：把 WuchongRecruitOpen 从流程链里拿掉（枢纽候选里没有它）
    #   → 守卫变红。
    try:
        w.FLOW_STEPS = tuple(s for s in saved_steps if s.node != "WuchongRecruitOpen")
        msgs = _room_exit_failures()
        red_exit = len(msgs) > 0
        print(
            f"  [{'PASS' if red_exit else 'FAIL'}] 房间死胡同回归（枢纽候选里没有 WuchongRecruitOpen）-> "
            f"{'红' if red_exit else '仍绿'}" + (f"  {msgs[0]}" if msgs else "")
        )
    finally:
        w.FLOW_STEPS = saved_steps
    checks.append(red_exit)

    # 机制侧弹窗拒点被拿掉（MODAL_BLOCK_STATES 清空）→ 守卫变红。
    saved_modal = impl.MODAL_BLOCK_STATES
    try:
        impl.MODAL_BLOCK_STATES = ()
        msgs = _switch_modal_guard_failures(impl)
        red_modal = len(msgs) > 0
        print(f"  [{'PASS' if red_modal else 'FAIL'}] 机制拒点被拿掉（弹窗在屏仍点击）-> "
              f"{'红' if red_modal else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
    finally:
        impl.MODAL_BLOCK_STATES = saved_modal
    checks.append(red_modal)

    # 手操引擎关仍被重选（raw WuchongBattle 未关）→ 守卫变红。
    root = _temp_assets()
    try:
        _sub(pipe(root), _BATTLE_RAW_ANCHOR, _BATTLE_RAW_BROKEN)
        msgs = _battle_gate_failures(root)
        red_gate = len(msgs) > 0
        print(f"  [{'PASS' if red_gate else 'FAIL'}] 手操引擎关仍重选（raw WuchongBattle 未关）-> "
              f"{'红' if red_gate else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checks.append(red_gate)

    # ★coop-fix2 守卫 11/12 的 prove-red★：把「多人游戏」case 里 WuchongTeamChallenge 的
    #   room_seen 门控拿掉（退回裸 WuchongTeamState）→ 守卫 11/12 必须变红（会先战斗后房间）。
    root = _temp_assets()
    try:
        _sub(
            iface(root),
            '"state": "wuchong_team", "room_seen": true, "ocr_entry": "OcrTask"',
            '"state": "wuchong_team", "ocr_entry": "OcrTask"',
        )
        m_gate = _mode_gate_failures(root)
        m_before = _room_before_battle_failures(impl, root)
        red_mode = len(m_gate) > 0
        red_before = len(m_before) > 0
        msg = (m_gate + m_before)
        print(f"  [{'PASS' if (red_mode and red_before) else 'FAIL'}] 多人去掉 room_seen 门控"
              f"（回退到「先战斗后房间」）-> {'红' if (red_mode and red_before) else '仍绿'}"
              + (f"  {msg[0]}" if msg else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checks.append(red_mode and red_before)

    # ★#75★：把默认（不选「游戏模式」）退回旧值「单人游戏」→ 默认=多人守卫必须变红。
    checks.append(
        _break_and_check(
            "默认「游戏模式」退回单人（default_case=单人游戏）",
            lambda r: _sub(
                iface(r),
                '        "游戏模式": {\n            "type": "select",\n            "default_case": "多人游戏",',
                '        "游戏模式": {\n            "type": "select",\n            "default_case": "单人游戏",',
            ),
            lambda r: _mode_default_failures(r),
        )
    )

    # ★本票 prove-red ①★：把 _orange_ratio 换回 **PIL-only**（模拟旧实现 / 安装态无 Pillow）
    #   → 「开关读数不依赖 PIL」守卫必须变红。
    import auto_switch_impl as sw  # noqa: PLC0415

    real_ratio = sw._orange_ratio

    def _pil_only(image, probe):  # noqa: ANN001
        try:
            import numpy as np  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415

            rgb = image if isinstance(image, Image.Image) else Image.fromarray(np.asarray(image))
            x0, y0, x1, y1 = (int(v) for v in probe)
            crop = np.asarray(rgb.convert("RGB").crop((x0, y0, x1, y1)), dtype=np.int16)
            r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
            return float(((r > 150) & (r - b > 80) & (r - g > 20) & (g < 210)).mean())
        except Exception:  # noqa: BLE001
            return None

    try:
        sw._orange_ratio = _pil_only
        msgs_pil = _switch_readable_without_pil_failures(sw=sw)
        red_pil = len(msgs_pil) > 0
        print(f"  [{'PASS' if red_pil else 'FAIL'}] 开关读数依赖 PIL（旧实现 / 无 Pillow）-> "
              f"{'红' if red_pil else '仍绿'}" + (f"  {msgs_pil[0]}" if msgs_pil else ""))
    finally:
        sw._orange_ratio = real_ratio
    checks.append(red_pil)

    # ★本票 prove-red ②★：把「手操节奏参数」里那份 manual:true 拿掉（回到被整体替换丢掉的形态）
    #   → 「手操确定性不被选项合并吃掉」守卫变红。
    root = _temp_assets()
    try:
        _sub(
            iface(root),
            '"manual": true,\n                                "flipper_gap_ms": "{弹板间隔}",',
            '"flipper_gap_ms": "{弹板间隔}",',
        )
        m_merge = _manual_survives_option_merge_failures(root)
        red_merge = len(m_merge) > 0
        print(f"  [{'PASS' if red_merge else 'FAIL'}] 手操确定性被选项合并吃掉（节奏 override 无 manual）-> "
              f"{'红' if red_merge else '仍绿'}" + (f"  {m_merge[0]}" if m_merge else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checks.append(red_merge)

    # ★本票 prove-red ③★：把「打几次」override 的字段名改坏（次数落不到 giveup）→ 次数守卫变红。
    root = _temp_assets()
    try:
        _sub(iface(root), '"target_fights": "{次数}"', '"target_fights_x": "{次数}"')
        m_count = _fight_count_failures(impl, root)
        red_count = len(m_count) > 0
        print(f"  [{'PASS' if red_count else 'FAIL'}] 「打几次」次数落不到 wuchong_giveup -> "
              f"{'红' if red_count else '仍绿'}" + (f"  {m_count[0]}" if m_count else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checks.append(red_count)

    # ★本票 prove-red ④（真机外修复）★：往 interface.json 造一个**重复键**（同名键后者覆盖前者）
    #   → 「选项命名空间无重复键」守卫必须变红（早先「五重打几次」误写成裸「打几次」，
    #   与「自动刷副本」的同名选项撞键，那个功能的 max_hit 被静默吃掉）。
    root = _temp_assets()
    try:
        _sub(iface(root), '"version": "1.0.0",', '"version": "1.0.0",\n    "version": "dup",')
        m_dup = _duplicate_interface_keys(root)
        red_dup = len(m_dup) > 0
        print(f"  [{'PASS' if red_dup else 'FAIL'}] interface.json 造重复键（同名键后者覆盖前者）-> "
              f"{'红' if red_dup else '仍绿'}" + (f"  {m_dup[0]}" if m_dup else ""))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    checks.append(red_dup)

    # ★本票 prove-red ⑤★：把「开始类」闩锁重试窗口设成「无限」（= 旧「永不再点」）→
    #   重试窗口守卫必须变红（单人第二局点不到「挑战」= 只打一局）。
    real_retry = impl.LATCH_RETRY_S
    try:
        impl.LATCH_RETRY_S = float("inf")
        m_latch = _latch_retry_failures(impl)
        red_latch = len(m_latch) > 0
        print(f"  [{'PASS' if red_latch else 'FAIL'}] 闩锁退回「永不再点」（重试窗口=inf）-> "
              f"{'红' if red_latch else '仍绿'}" + (f"  {m_latch[0]}" if m_latch else ""))
    finally:
        impl.LATCH_RETRY_S = real_retry
    checks.append(red_latch)

    # ★#76 prove-red ①★：把「未知画面」判据退回**旧语义**（战斗中照计）→
    #   「战斗内 unknown 不计」守卫必须变红。
    real_counts = impl.counts_as_unknown
    try:
        impl.counts_as_unknown = lambda state, in_fight: state == "unknown"  # noqa: ARG005
        m_unknown = _unknown_not_counted_in_fight_failures(impl)
        red_unknown = len(m_unknown) > 0
        print(f"  [{'PASS' if red_unknown else 'FAIL'}] 战斗内 unknown 照计（旧语义）-> "
              f"{'红' if red_unknown else '仍绿'}" + (f"  {m_unknown[0]}" if m_unknown else ""))
    finally:
        impl.counts_as_unknown = real_counts
    checks.append(red_unknown)

    # ★#76 prove-red ②★：把「已打够 N 次」退回**旧语义**（战斗 episode 内也放行）→
    #   「打够次数不许在战斗内收工」守卫必须变红。
    real_reached = impl.fight_target_reached
    try:
        impl.fight_target_reached = lambda t, d, in_fight: int(t) > 0 and int(d) >= int(t)  # noqa: ARG005
        m_giveup = _giveup_out_of_fight_failures(impl)
        red_giveup = len(m_giveup) > 0
        print(f"  [{'PASS' if red_giveup else 'FAIL'}] 打够次数在战斗内也收工（旧语义）-> "
              f"{'红' if red_giveup else '仍绿'}" + (f"  {m_giveup[0]}" if m_giveup else ""))
    finally:
        impl.fight_target_reached = real_reached
    checks.append(red_giveup)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


class _BrokenManualAction:
    """坏实现：无视 manual 直接跑手操（模拟「取消不了手打」）。"""

    def __init__(self, mod):
        self._mod = mod

    def run(self, context, argv):  # noqa: N802
        self._mod._run_battle_live(context, None)
        return True


class _BrokenClassify:
    """把结算误判为战斗中的坏模块。"""

    def __init__(self, mod):
        self._mod = mod

    def __getattr__(self, item):
        return getattr(self._mod, item)

    def classify(self, items, relogin_phrases=()):
        state, info = self._mod.classify(items, relogin_phrases)
        if state == "wuchong_settle":
            return "wuchong_battle", info
        return state, info


def _cross_mode_failures_for(root: Path | None = None) -> list:
    """在给定 assets 根上跑跨模式守卫（仅 GUI 部分需要 root）。"""
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    iface = _interface(root)
    tasks = {t.get("name"): (t.get("option") or []) for t in iface.get("task") or []}
    for name, opts in tasks.items():
        if "是否手操" in opts and name != "五重决战":
            msgs.append(f"任务 {name!r} 不应挂「是否手操」（只有五重决战允许手动）")
    if "是否手操" not in tasks.get("五重决战", []):
        msgs.append("任务「五重决战」缺「是否手操」选项")
    return msgs


# ---------------------------------------------------------------------------
# 守卫 11：★游戏模式 = 有效流水线的门控★（coop-fix2 P0）
#
# 真机 07:45 leg_b（`--mode 多人`）复盘：`WuchongModeSolo` 确实被选项关掉了，但**流程根本没
# 走到模式页** —— 设备停在上一轮单人留下的**编队页**，入口枢纽直接把它的「挑战」点了 → 又打
# 一局单人。「关一张模式卡」不足以让多人成立；多人在**有效流水线**上还须：
#   · WuchongTeamChallenge（编队页→挑战）要求 room_seen=true（本轮进过共斗房），否则不点火；
#   · WuchongCoopChallenge（共斗房的「挑战」，raw 默认关）打开 —— 多人真正的开战点；
#   · WuchongStaleTeam（stale 单人编队页 → 返回重选，raw 默认关）打开。
# ---------------------------------------------------------------------------
_TID = 560156


def _effective_mode_override(case: str, root: Path | None = None) -> dict:
    """按**产品同一条缝**（tools/interface_options）解析「游戏模式」= case 的有效覆盖。"""
    _paths()
    import interface_options as iopt  # noqa: PLC0415

    proj = Path(root) if root is not None else REPO_ROOT
    return iopt.resolve_task_override(proj, "五重决战", {"游戏模式": case})


def _rec_disabled(node) -> bool:
    return (((node or {}).get("recognition") or {}).get("param") or {}).get("expected") == ["__NONE__"]


def _rec_custom_param(node) -> dict:
    """recognition = Custom 时取其 custom_recognition_param（否则 {}）。"""
    rec = (node or {}).get("recognition") or {}
    if rec.get("type") != "Custom":
        return {}
    return (rec.get("param") or {}).get("custom_recognition_param") or {}


def _inline_custom_param(node) -> dict:
    """recognition = And 时取其中**内联** Custom 叶子的 custom_recognition_param（否则 {}）。"""
    rec = (node or {}).get("recognition") or {}
    if rec.get("type") != "And":
        return {}
    for leaf in ((rec.get("param") or {}).get("all_of") or []):
        if not isinstance(leaf, dict):
            continue
        lr = leaf.get("recognition") or {}
        if lr.get("type") == "Custom":
            return (lr.get("param") or {}).get("custom_recognition_param") or {}
    return {}


def _mode_gate_failures(root: Path | None = None) -> list:
    msgs: list[str] = []
    multi = _effective_mode_override("多人游戏", root)
    solo = _effective_mode_override("单人游戏", root)

    # 模式卡互斥（任务要求：「多人 ⇒ ModeSolo 关」（反之亦然））。
    if not _rec_disabled(multi.get("WuchongModeSolo")):
        msgs.append("游戏模式=多人游戏：WuchongModeSolo 未被关（单人卡仍可能先命中）")
    if not _rec_disabled(solo.get("WuchongModeMulti")):
        msgs.append("游戏模式=单人游戏：WuchongModeMulti 未被关")

    # 多人：编队页→挑战 必须**进过共斗房**才允许。
    tcp = _inline_custom_param(multi.get("WuchongTeamChallenge"))
    if tcp.get("room_seen") is not True:
        msgs.append(
            "游戏模式=多人游戏：WuchongTeamChallenge 未要求 room_seen=true"
            f"（会从 stale 单人编队页直接开战）：{tcp!r}"
        )
    # 单人：不改 WuchongTeamChallenge（单人编队页合法）。
    if _inline_custom_param(solo.get("WuchongTeamChallenge")):
        msgs.append("游戏模式=单人游戏：不该给 WuchongTeamChallenge 加 room_seen 门控")

    # 多人：共斗房挑战节点必须打开且门控在**房间（已招募）**。
    cp = _rec_custom_param(multi.get("WuchongCoopChallenge"))
    if cp.get("state") != "wuchong_room" or cp.get("recruit_state") != "started":
        msgs.append(
            "游戏模式=多人游戏：WuchongCoopChallenge 未门控在共斗房（已招募）"
            f"（多人开不了战）：{cp!r}"
        )
    if not _rec_disabled(solo.get("WuchongCoopChallenge")):
        msgs.append("游戏模式=单人游戏：WuchongCoopChallenge 应保持关（单人没有共斗房）")

    # 多人：stale 编队页出口必须打开且只在**未进过房**时命中。
    sp = _rec_custom_param(multi.get("WuchongStaleTeam"))
    if sp.get("state") != "wuchong_team" or sp.get("room_seen") is not False:
        msgs.append(
            "游戏模式=多人游戏：WuchongStaleTeam 未门控在 stale 编队页"
            f"（room_seen=false）：{sp!r}"
        )
    if not _rec_disabled(solo.get("WuchongStaleTeam")):
        msgs.append("游戏模式=单人游戏：WuchongStaleTeam 应保持关（单人编队页合法）")
    return msgs


def probe_wuchong_mode_gates() -> bool:
    return _mode_gate_failures() == []


# ---------------------------------------------------------------------------
# 守卫 12：★房间先于战斗★（coop-fix2 验收判据 —— 「点了多人卡」不算证据，落脚点才算）
#
# 用真机形态的合成 OCR 帧驱动**真实**的 WuchongStateRecognition：
#   · 单人编队页帧（Party/SET + 底部挑战）—— 多人 + 未进房**绝不**认同「挑战」（不先战斗）；
#   · 共斗房帧（房间号码 + 招募 + 复制 + 挑战，去掉「未进行招募」= 已招募）—— 才允许开战。
# ---------------------------------------------------------------------------
_STALE_TEAM_ITEMS = [
    ("SET 1", [300, 300, 80, 30]),
    ("Party E", [120, 900, 120, 40]),
    ("挑战", [297, 1069, 80, 47]),      # 单人编队页的挑战（可用）
    ("返回", [30, 1246, 46, 26]),
]
_ROOM_RECRUITED_ITEMS = [
    ("房间号码", [276, 1184, 94, 28]),
    ("招募", [352, 808, 72, 41]),
    ("复制", [540, 1230, 48, 31]),
    ("挑战", [297, 906, 81, 46]),       # 共斗房的挑战（人齐后可用）
    ("返回", [30, 1246, 46, 26]),
]


class _RecArgv56:
    def __init__(self, param: dict):
        self.image = object()
        self.task_detail = type("TD", (), {"task_id": _TID})()
        self.custom_recognition_param = json.dumps(param)


def _recog_hit(mod, param: dict, items, room_seen: bool) -> bool:
    """驱动真实 WuchongStateRecognition 一帧，返回是否命中（box==[0,0,0,0]）。"""
    real_ocr = mod._ocr
    try:
        mod._ocr = lambda context, image, entry="OcrTask": list(items)
        with mod._LOCK:
            mod._SESSION["task_id"] = _TID
            mod._SESSION["room_seen"] = bool(room_seen)
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
        res = mod.WuchongStateRecognition().analyze(None, _RecArgv56(param))
        return res.box == [0, 0, 0, 0]
    finally:
        mod._ocr = real_ocr


def _room_before_battle_failures(mod, root: Path | None = None) -> list:
    msgs: list[str] = []
    multi = _effective_mode_override("多人游戏", root)
    tc_param = _inline_custom_param(multi.get("WuchongTeamChallenge"))
    coop_param = _rec_custom_param(multi.get("WuchongCoopChallenge"))
    stale_param = _rec_custom_param(multi.get("WuchongStaleTeam"))

    # A) 多人 + 未进过房：绝不能认单人编队页的「挑战」（= 房间之前**无战斗**）。
    if _recog_hit(mod, tc_param, _STALE_TEAM_ITEMS, room_seen=False):
        msgs.append("多人 + 未进房：WuchongTeamChallenge 仍认单人编队页的挑战（会先打单人）")
    # B) 多人 + 进过房：人齐后的编队页才允许开战。
    if not _recog_hit(mod, tc_param, _STALE_TEAM_ITEMS, room_seen=True):
        msgs.append("多人 + 进过房：WuchongTeamChallenge 不认编队页的挑战（人齐后开不了战）")

    # C) stale 出口：未进房命中；进过房不命中（绝不把人齐后的战点掉）。
    if not _recog_hit(mod, stale_param, _STALE_TEAM_ITEMS, room_seen=False):
        msgs.append("多人 + 未进房：WuchongStaleTeam 不命中 stale 编队页（无出口 → 卡死）")
    if _recog_hit(mod, stale_param, _STALE_TEAM_ITEMS, room_seen=True):
        msgs.append("多人 + 进过房：WuchongStaleTeam 竟命中（会把人齐后要开的战点掉）")

    # D) 房间挑战：只在共斗房（已招募）命中；在编队页不命中（「房间先于战斗」的唯一开战点）。
    if not _recog_hit(mod, coop_param, _ROOM_RECRUITED_ITEMS, room_seen=True):
        msgs.append("多人：WuchongCoopChallenge 不认共斗房（已招募）的挑战（多人永远开不了战）")
    if _recog_hit(mod, coop_param, _STALE_TEAM_ITEMS, room_seen=False):
        msgs.append("WuchongCoopChallenge 在编队页也命中（房间判据泄漏 → 可能先战斗）")
    return msgs


def probe_wuchong_room_before_battle() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _room_before_battle_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 13：★开关读数不得依赖 PIL★（本票真机 P0：「手操但仍自动」的根因之一）
#
# 真机证据（install/debug/maafw.log 2026-10-16 01:16:17）：
#   WuchongTeamAutoSet 的 auto_switch_state detail =
#   {"box":[630,102,43,27],"found":true,"on":null,"reason":"state_unknown","source":"template"}
# → 模板命中了「自动」，却**读不出开/关** → 识别不命中 → 「手操」case 的 WuchongTeamAutoSet
#   永不执行 → 编队页/房间页的「自动」**从来没被关过** → 进战斗仍是自动。
# 根因：随包便携 Python（interface.json child_exec = install/python/python.exe，install.py 只装
# maafw+numpy+StrEnum）**没有 Pillow**；旧 `_orange_ratio` 里 `from PIL import Image` 必抛
# ImportError 被吞 → 恒返回 None。守卫：**屏蔽 PIL** 后读数仍须正确。
# ---------------------------------------------------------------------------
def _switch_readable_without_pil_failures(mod=None, sw=None) -> list:
    _paths()
    import builtins  # noqa: PLC0415

    if sw is None:
        import auto_switch_impl as sw  # noqa: PLC0415
    if mod is None:
        import wuchong_impl as mod  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    msgs: list[str] = []
    # 合成帧：BGR 橙色块正好落在「自动」标签(142,1062,43,26)的探针区里。
    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    img[1103:1132, 127:202] = [0, 120, 255]  # BGR = 橙（高 R / 低 B）
    probe = (127, 1103, 202, 1132)

    real_import = builtins.__import__
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "PIL" or k.startswith("PIL.")}

    def blocked(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("blocked PIL (simulate install/python without Pillow)")
        return real_import(name, *a, **k)

    builtins.__import__ = blocked
    try:
        r_sw = sw._orange_ratio(img, probe)
        r_wc = mod._orange_ratio(img, probe)
        st = sw.read_switch_state(img, sw.AUTO_LABEL, [142, 1062, 43, 26])
    finally:
        builtins.__import__ = real_import
        sys.modules.update(saved)

    if r_sw is None or r_sw <= float(sw.AUTO_ON_RATIO):
        msgs.append(
            f"无 PIL 时 auto_switch._orange_ratio 读不出橙色（{r_sw!r}）→ 「自动」开关永远读不出/关不掉"
        )
    if r_wc is None or r_wc <= 0.5:
        msgs.append(f"无 PIL 时 wuchong_impl._orange_ratio 读不出橙色（{r_wc!r}）")
    if st is not True:
        msgs.append(f"无 PIL 时 read_switch_state 未读成「开」（{st!r}）→ 开关门控恒不命")
    return msgs


def probe_wuchong_switch_readable_without_pil() -> bool:
    return _switch_readable_without_pil_failures() == []


# ---------------------------------------------------------------------------
# 守卫 14：★手操确定性不得被选项合并吃掉★（本票真机 P0：「手操但仍自动」的根因之二）
#
# 真机证据（install/debug/maafw.log 2026-10-16 01:15:56 post_task）：
#   MFAAvalonia 把每个选项的 pipeline_override **分别**放进一个**列表**交给 MaaFramework
#   （不是深合并！）；框架逐条覆盖，同一节点的 action.param 被**后写者整体替换**。实测最终
#   WuchongBattle 的 custom_action_param = {"burst":10,"duration_s":25,"flipper_gap_ms":220,
#   "skill_every":6,"skill_gap_ms":800} —— **没有 manual**（「手操」case 写的 manual:true 被
#   排在最后的「手操节奏参数」整体盖掉）。于是动作按会话回退 manual=False → **一次都不点**。
# 守卫：按真机语义（后写者整体替换）求有效参数，手操时必须仍带 manual=true。
# （离线 `tools/interface_options.resolve_task_override` 是**深合并**，这条缝查不出来 —— 见
#  本守卫为何另算一遍。）
# ---------------------------------------------------------------------------
def _effective_battle_action_param(selections: dict, inputs: dict | None = None,
                                   root: Path | None = None) -> dict:
    _paths()
    import interface_options as iopt  # noqa: PLC0415

    iface = _interface(root)
    task = next((t for t in iface.get("task") or [] if t.get("name") == "五重决战"), None)
    if task is None:
        return {}
    eff: dict = {}
    for opt in task.get("option") or []:
        ov = iopt.option_override(iface, opt, (selections or {}).get(opt), inputs)
        node = ov.get("WuchongBattle") or {}
        ap = (node.get("action") or {}).get("param")
        if isinstance(ap, dict):
            # 真机语义：后写者**整体替换** action.param；这里取其中的 custom_action_param
            # （= 动作真正读到的 `argv.custom_action_param`）。
            cap = ap.get("custom_action_param")
            if isinstance(cap, dict):
                eff = dict(cap)
    return eff


def _manual_survives_option_merge_failures(root: Path | None = None) -> list:
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    eff = _effective_battle_action_param({"是否手操": "手操"}, {"弹板间隔": "500"}, root)
    if eff.get(w.BATTLE_MANUAL_FIELD) is not True:
        msgs.append(
            f"真机选项语义下 WuchongBattle 最终参数丢失 {w.BATTLE_MANUAL_FIELD!r}"
            f"（手操引擎一次都不点）：{eff!r}"
        )
    if eff.get("flipper_gap_ms") != 500:
        msgs.append(f"手操节奏参数未落进最终动作参数：flipper_gap_ms={eff.get('flipper_gap_ms')!r}")
    # 「自动」时结点必须仍是关的（manual 只对启用的手操结点生效，绝不误开手操）。
    eff_auto = _effective_battle_action_param({"是否手操": "自动"}, None, root)
    if eff_auto.get("flipper_gap_ms") not in (None, 220):
        msgs.append(f"「自动」下节奏参数异常：{eff_auto!r}")
    return msgs


def probe_wuchong_manual_survives_option_merge() -> bool:
    return _manual_survives_option_merge_failures() == []


# ---------------------------------------------------------------------------
# 守卫 15：★「打几次」= 打够 N 次走既有收工出口★（本票功能 A）
#
# 数据：GUI 选项「打几次」（input，次数）覆盖 WuchongGiveUp.recognition.target_fights。
# 机制：★#74 更新（规格 B2/D2）★ 每**进入一场战斗**（战斗 HUD 首次出现）→ 账本记一笔
#   wuchong/fight/{n}（**不是**结算页；续关后回到战斗不算新的一场）；打够 N 次 →
#   wuchong_giveup 按同一理由收工（StopTask + wuchong/run/completed），与深渊/幻想同口径。
# ---------------------------------------------------------------------------
def _fight_count_failures(mod, root: Path | None = None) -> list:
    _paths()
    import tempfile  # noqa: PLC0415

    from scene import wuchong as w  # noqa: PLC0415
    import interface_options as iopt  # noqa: PLC0415

    msgs: list[str] = []
    iface = _interface(root)
    task = next((t for t in iface.get("task") or [] if t.get("name") == "五重决战"), None)
    if task is None or w.TARGET_FIGHTS_OPTION not in (task.get("option") or []):
        msgs.append(f"任务「五重决战」缺「{w.TARGET_FIGHTS_OPTION}」选项")
    block = (iface.get("option") or {}).get(w.TARGET_FIGHTS_OPTION) or {}
    if block.get("type") != "input":
        msgs.append(f"「{w.TARGET_FIGHTS_OPTION}」应为 input 选项（type={block.get('type')!r}）")

    # 选项 → WuchongGiveUp.target_fights
    ov = iopt.option_override(iface, w.TARGET_FIGHTS_OPTION, None, {"次数": "3"})
    gp = (((ov.get("WuchongGiveUp") or {}).get("recognition") or {}).get("param") or {}).get(
        "custom_recognition_param"
    ) or {}
    if int(gp.get(w.TARGET_FIGHTS_FIELD) or 0) != 3:
        msgs.append(
            f"「{w.TARGET_FIGHTS_OPTION}=3」未落到 WuchongGiveUp.{w.TARGET_FIGHTS_FIELD}："
            f"{gp.get(w.TARGET_FIGHTS_FIELD)!r}"
        )
    # 其余既有字段必须仍在（override 整体替换 recognition，写全才不丢）。
    for key in ("ocr_entry", "room_wait_sec", "no_progress_sec", "unknown_limit", "max_task_sec"):
        if key not in gp:
            msgs.append(f"「{w.TARGET_FIGHTS_OPTION}」override 丢了 WuchongGiveUp 的 {key}（整体替换必须写全）")

    # 引擎：驱动真实 WuchongGiveUpRecognition（既有收工出口）。
    def drive(fights_done: int, target: int):
        real_ocr = mod._ocr
        tid = 560_900_000 + int(target) * 100 + int(fights_done)
        try:
            mod._ocr = lambda context, image, entry="OcrTask": list(_ROOM_ITEMS)
            with mod._LOCK:
                mod._SESSION["task_id"] = tid
                mod._SESSION["fights_done"] = int(fights_done)
                mod._SESSION["start_ts"] = time.monotonic()
                mod._SESSION["last_progress_ts"] = time.monotonic()
                mod._SESSION["room_first_ts"] = 0.0
                mod._SESSION["last_state"] = None
                mod._SESSION["last_observe_ts"] = 0.0
                mod._SESSION["unknown_count"] = 0
            res = mod.WuchongGiveUpRecognition().analyze(
                None,
                _RecArgv(tid, {"ocr_entry": "OcrTask", w.TARGET_FIGHTS_FIELD: target,
                               "room_wait_sec": 300, "no_progress_sec": 900}),
            )
            return (res.box == [0, 0, 0, 0]), str((res.detail or {}).get("reason") or "")
        finally:
            mod._ocr = real_ocr

    with tempfile.TemporaryDirectory() as td:
        saved_file = getattr(mod.ledger, "_DEFAULT", None)
        mod.ledger.set_file(Path(td) / "p.json")
        try:
            # ★#74 更新（规格 B2/D2）★ 计数点 = **跃变进入战斗**（战斗 HUD 首次出现）：
            #   进入战斗恰好记一笔（同状态持续帧不重复计）；结算页不再计。
            with mod._LOCK:
                mod._SESSION["fights_done"] = 0
                mod._SESSION["battle_had_continue"] = False
                mod._SESSION["last_state"] = None
                mod._SESSION["last_observe_ts"] = 0.0
            mod._observe("wuchong_battle", {}, [])
            mod._observe("wuchong_battle", {}, [])
            with mod._LOCK:
                n = mod._SESSION["fights_done"]
            if n != 1:
                msgs.append(f"跃变进入战斗应恰好记 1 场，实际 {n}")
            if mod.ledger.scope(mod.FIGHT_LEDGER_PREFIX) != [f"{mod.FIGHT_LEDGER_PREFIX}/1"]:
                msgs.append(f"场次未落账本：{mod.ledger.scope(mod.FIGHT_LEDGER_PREFIX)}")
            # ★#74 更新★：结算页**不再**是计数点（旧语义已被规格 B2/D2 取代）。
            mod._observe("wuchong_settle", {}, [])
            with mod._LOCK:
                n_after_settle = mod._SESSION["fights_done"]
            if n_after_settle != 1:
                msgs.append(f"结算页不得再计数（应仍 1 场），实际 {n_after_settle}")
            # ★#74 更新★：续关后回到战斗**不得**再 +1（续关不算新的一场）——GAMEOVER 屏置标记，
            #   经 loading 过渡帧回到战斗，场次必须不变。
            mod._observe("wuchong_battle", {}, _GAMEOVER_ITEMS)
            mod._observe("loading", {}, [])
            mod._observe("wuchong_battle", {}, [])
            with mod._LOCK:
                n_after_continue = mod._SESSION["fights_done"]
            if n_after_continue != 1:
                msgs.append(f"续关后回到战斗不得再计（应仍 1 场），实际 {n_after_continue}")

            hit, reason = drive(2, 3)
            if hit:
                msgs.append(f"只打 2 场（目标 3）就收工了：{reason!r}")
            hit3, reason3 = drive(3, 3)
            if not hit3:
                msgs.append("打够 3 场（目标 3）仍未收工（次数不被引擎承认）")
            if "3" not in reason3 or "次" not in reason3:
                msgs.append(f"收工原因未点明次数：{reason3!r}")
            hit0, _r0 = drive(9, 0)
            if hit0:
                msgs.append("target_fights=0（不限制）竟收工（旧行为被破坏）")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_fight_count() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _fight_count_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 19：★「已打够 N 次」不许在【战斗 episode 内】收工★（#76；单人真机复现）
#
# 真机（2026-10-17，127.0.0.1:16384 / CET-AL00，单人 + 手操，打几次=2，`debug/wc_solo_02.log`）：
#   `已进入第 2 场战斗（账本 wuchong/fight/2）` → 立刻 `写入收工标记 wuchong/run/completed` →
#   `触发收工兜底：已打够 2 次（打几次=2）（state=wuchong_battle）` → 任务停止。
#   现场帧 `063_trace63.png`：新战斗停在「点击」提示（时间 30:00 / 分数 00000000000，球不动）——
#   这就是运维原话「不点板子我的任务死了」。打几次 = GUI 默认 1 时更狠：**手操引擎一次都没进来**
#   （run1 全日志没有 `info:[wuchong_battle] 手操开始`，同一次识别里记一场 + 立刻收工）。
# 落地：收工时机 = 纯函数 `fight_target_reached(target, done, in_fight)`（★计数点/理由文案/账本不变★）。
# ---------------------------------------------------------------------------
#: ★#76★ 合成 OCR 帧：真机战斗 HUD（**合并框**形态，同 `tools/frames/wuchong74_battle_hud_merged.png`）。
_BATTLE_HUD_ITEMS_76 = [("时间 29:30 分数 38629797530", [34, 1220, 400, 40])]
#: ★#76★ 合成 OCR 帧：结算页（`classify` → `wuchong_settle`，判据见 classify 第 12 条）。
_SETTLE_ITEMS_76 = [("QUESTRESULT", [200, 300, 300, 40]), ("继续", [340, 1190, 80, 40])]
#: ★#76★ 合成 OCR 帧：编队页（`classify` → `wuchong_team`，∈ `_FIGHT_LEAVE_STATES`）。
_TEAM_ITEMS_76 = [("Party A", [60, 200, 120, 30]), ("挑战", [300, 1060, 80, 40])]


def _giveup_out_of_fight_failures(mod) -> list:
    """★#76★：打够次数只能在**战斗外**收工；战斗内绝不收工；战斗外必须收工。"""
    _paths()
    import tempfile  # noqa: PLC0415

    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []

    def drive(items, fights_done: int, target: int):
        """按真机语义驱动真实 WuchongGiveUpRecognition（fights_done 为**此前已记**的场次）。"""
        real_ocr = mod._ocr
        tid = 570_000_000 + int(target) * 1000 + int(fights_done)
        try:
            mod._ocr = lambda context, image, entry="OcrTask": list(items)
            with mod._LOCK:
                mod._SESSION["task_id"] = tid
                mod._SESSION["fights_done"] = int(fights_done)
                mod._SESSION["start_ts"] = time.monotonic()
                mod._SESSION["last_progress_ts"] = time.monotonic()
                mod._SESSION["room_first_ts"] = 0.0
                mod._SESSION["last_state"] = None
                mod._SESSION["last_observe_ts"] = 0.0
                mod._SESSION["unknown_count"] = 0
                mod._SESSION["battle_had_continue"] = False
                mod._SESSION["in_fight"] = False
            res = mod.WuchongGiveUpRecognition().analyze(
                None,
                _RecArgv(tid, {"ocr_entry": "OcrTask", w.TARGET_FIGHTS_FIELD: target,
                               "room_wait_sec": 300, "no_progress_sec": 900}),
            )
            return (res.box == [0, 0, 0, 0]), str((res.detail or {}).get("reason") or "")
        finally:
            mod._ocr = real_ocr

    with tempfile.TemporaryDirectory() as td:
        saved_file = getattr(mod.ledger, "_DEFAULT", None)
        mod.ledger.set_file(Path(td) / "p.json")
        try:
            # ① 缺陷 A 本体（真机 run1/run2 现场）：战斗帧 + 目标场次刚好打够（含"这一帧才记满"）
            #    → **绝不收工**（收工 = 角色原地不动、本场必输）。
            hit_battle, reason_battle = drive(_BATTLE_HUD_ITEMS_76, 1, 2)
            if hit_battle:
                msgs.append(f"战斗 episode 内（打够次数）竟收工：{reason_battle!r} → 游戏停在『点击』不动")
            # ② 同一帧序列下 in_fight 必须为真（证明①不是"判据没跑"而是真的进了战斗 episode）。
            with mod._LOCK:
                latched = bool(mod._SESSION["in_fight"])
            if not latched:
                msgs.append("战斗 HUD 帧未置 in_fight 闩锁（本守卫测不到缺陷 A 的场景）")
            # ③ 本场收场（结算页）后**必须**收工 —— 否则「打几次」永不收工（无界空转）。
            hit_settle, reason_settle = drive(_SETTLE_ITEMS_76, 2, 2)
            if not hit_settle:
                msgs.append("本场收场（结算页）后仍未按『已打够 N 次』收工 → 永不收工")
            elif "2" not in reason_settle or "次" not in reason_settle:
                msgs.append(f"收工原因未点明次数：{reason_settle!r}")
            # ④ 被推出战斗（回到编队页）同样属于「战斗已收场」→ 必须收工。
            hit_team, _r = drive(_TEAM_ITEMS_76, 2, 2)
            if not hit_team:
                msgs.append("被推出战斗（编队页）后仍未按『已打够 N 次』收工")
            # ⑤ 战斗帧 + 目标未打够 → 当然不收工（既有语义不许被本票改坏）。
            hit_notyet, _r2 = drive(_BATTLE_HUD_ITEMS_76, 0, 2)
            if hit_notyet:
                msgs.append("只打 0 场（目标 2）就收工了")
            # ⑥ target=0（不限制）在结算页也不收工（旧行为）。
            hit_unlimited, _r3 = drive(_SETTLE_ITEMS_76, 9, 0)
            if hit_unlimited:
                msgs.append("target_fights=0（不限制）竟收工（旧行为被破坏）")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_giveup_out_of_fight() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _giveup_out_of_fight_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 20：★战斗 episode 内的 `unknown` 帧不计「未知画面」★（#76）
#
# 真机逐帧（2026-10-17 单人 run）：同一场真战斗里 `wuchong_battle` 与 `unknown` 每 2~3 秒来回，
# 一次换波过渡连出 8 帧 ≈ 45s `unknown`。手操引擎每 2s 采一帧判据（`_verdict_live` → `_observe`）
# → 一场 5 分钟的战斗把 `unknown_count` 推到 ~80，8 分钟以上必越过 `unknown_limit`（默认 120）；
# 越线那一刻正好是**本场收场**（引擎交还、管线才重新扫节点）→ 任务以「未知画面累计 121 次」收工
# = 手操打完一场就死（历史同形缺陷：旧合并框判据恒判 unknown → 573s 早亡，见 classify 的 #74 注释）。
# 落地：计数判据 = 纯函数 `counts_as_unknown(state, in_fight)`。
# ---------------------------------------------------------------------------
def _unknown_not_counted_in_fight_failures(mod) -> list:
    """★#76★：战斗内 unknown 不计；进战斗前 / 离开战斗后照旧计（否则「迷路」抓不到）。"""
    _paths()
    import tempfile  # noqa: PLC0415

    msgs: list[str] = []

    def drive(seq: list[str]) -> tuple:
        with mod._LOCK:
            mod._SESSION["task_id"] = 570_100_000 + len(seq)
            mod._SESSION["fights_done"] = 0
            mod._SESSION["last_state"] = None
            mod._SESSION["last_observe_ts"] = 0.0
            mod._SESSION["unknown_count"] = 0
            mod._SESSION["battle_had_continue"] = False
            mod._SESSION["in_fight"] = False
        for state in seq:
            mod._observe(state, {}, _BATTLE_HUD_ITEMS_76 if state == "wuchong_battle" else [])
        with mod._LOCK:
            return mod._SESSION["unknown_count"], bool(mod._SESSION["in_fight"])

    with tempfile.TemporaryDirectory() as td:
        saved_file = getattr(mod.ledger, "_DEFAULT", None)
        mod.ledger.set_file(Path(td) / "p.json")
        try:
            # ① 战斗内 battle/unknown 交替闪烁 6 轮 —— 一次都不许计。
            flicker: list[str] = []
            for _ in range(6):
                flicker += ["wuchong_battle", "unknown"]
            n_flicker, in_fight = drive(flicker)
            if n_flicker != 0:
                msgs.append(f"战斗 episode 内的 unknown 被计入未知画面（{n_flicker} 次）→ 长战斗必被收工兜底掐死")
            if not in_fight:
                msgs.append("battle/unknown 交替后 in_fight 未置真（守卫测不到战斗 episode）")
            # ② 离开本场（编队页）后的 unknown **照旧计**（否则机器人真迷路了也不收工）。
            n_after, in_after = drive(["wuchong_battle", "unknown", "wuchong_team", "unknown"])
            if n_after != 1:
                msgs.append(f"离开本场后的 unknown 未被计数（应 1 次，实际 {n_after}）")
            if in_after:
                msgs.append("编队页（∈ _FIGHT_LEAVE_STATES）未清 in_fight 闩锁")
            # ③ 还没进战斗时的 unknown 照旧计（loading / 认不出的非战斗页 = 真·迷路）。
            n_before, _inf = drive(["unknown", "wuchong_battle"])
            if n_before != 1:
                msgs.append(f"进战斗前的 unknown 未被计数（应 1 次，实际 {n_before}）")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_unknown_not_counted_in_fight() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _unknown_not_counted_in_fight_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 16：★interface.json 选项命名空间不得有重复键★（真机外修复）
#
# 背景（真机外缺陷，本票功能 A 的落地瑕疵）：``option`` 是**全局命名空间**（按名索引，
# ``tools/interface_options.load_interface`` 与 MFAAvalonia 都按名取块）。早先把五重「打几次」
# 写成裸名「打几次」，与「自动刷副本」任务既有的同名选项**撞键**；同名 JSON 键在
# ``json.loads`` / ``jsonc.load`` 下**后者覆盖前者**（不报错）→「自动刷副本」的「打几次」
# （写 ``SpecialFightTargetRow.max_hit``）被整体顶掉，功能**静默失效**。
# ★既有守卫查不出★：``scene.drift`` 与 ``validate_schema`` 也只看到「去重后」的结果；
#   落盘的 ``install/interface.json`` 只剩 WuchongGiveUp 一份，可复核。
# 守卫：直接对原文做「重复键探测」（object_pairs_hook 记录被覆盖的键名）。
# ---------------------------------------------------------------------------
def _duplicate_interface_keys(root: Path | None = None) -> list:
    """interface.json 里被「同名键后者覆盖前者」吃掉的重复键（空 = 无重复）。"""
    path = (Path(root) if root is not None else REPO_ROOT) / INTERFACE_REL
    text = _strip_jsonc(path.read_text(encoding="utf-8"))
    dups: list = []

    def hook(pairs):
        seen: set = set()
        for k, _v in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)

    try:
        json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        return [f"interface.json 无法解析：{exc}"]
    return [
        f"interface.json 有重复键 {k!r}（同名键后者覆盖前者，前一份被静默吃掉；"
        f"option 是全局命名空间，五重的次数项须用带前缀的键名）"
        for k in dict.fromkeys(dups)
    ]


def probe_wuchong_interface_no_duplicate_keys() -> bool:
    return _duplicate_interface_keys() == []


# ---------------------------------------------------------------------------
# 守卫 17：★「开始类」闩锁 = 【重试窗口】，不是「永不再点」★（本票缺陷 1、3 的同一根因）
#
# 真源 scene.wuchong ②e。本票线索「五重没有次数 → 记一次就收工 → 没打几分钟就结束」的
# 机制侧真凶：单人链路每一局都要在编队页**重新点「挑战」**（``WuchongSettleContinue.next``
# 首项 = ``WuchongTeamChallenge``）；若闩锁是「永不再点」，第一局之后本节点永不点火 →
# **只打得动一局**（与「打几次」无关地提前收工）。用**真实** ``WuchongActAction`` 驱动编队页帧：
#   · 第一次点「挑战」→ 落地 + 记时间戳；
#   · 紧接着再驱动 → 窗口内**不重复点**（防连击）；
#   · 把时间戳倒拨成「很久以前」（模拟上一局打完、回到编队页）→ **必须重新点**；
#   · 换任务（新 task_id）→ 时间戳清零（绝不把上一局的闩锁带进新任务）。
# ---------------------------------------------------------------------------
_TEAM_ITEMS_LATCH = [
    ("SET 1", [300, 300, 80, 30]),
    ("Party E", [120, 900, 120, 40]),
    ("挑战", [300, 1073, 120, 44]),   # 单人编队页的挑战（落在 roi [150,980,600,1180] 内）
]
#: 「很久以前」的时间戳倒退量（秒）；**独立于** ``LATCH_RETRY_S``，好让「把窗口设大」的
#: 破坏实验能被抓到（真值 8s → 3600s 早过窗；若窗口被改成 1e9/inf → 3600s 仍在窗内 → 守卫红）。
_LATCH_STALE_SEC = 3600.0


def _latch_retry_failures(mod) -> list:
    _paths()
    msgs: list[str] = []
    clicks: list = []
    saved = {k: mod.__dict__[k] for k in ("_grab", "_ocr", "_click_box")}
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    param = {
        "what": ["^挑战$"], "roi": [150, 980, 600, 1180],
        "latch": "battle_start", "expect": ["wuchong_battle"], "wait_ms": 200,
    }
    try:
        mod._grab = lambda context: object()
        mod._ocr = lambda context, image, entry="OcrTask": list(_TEAM_ITEMS_LATCH)
        mod._click_box = lambda context, cx, cy: (clicks.append((int(cx), int(cy))) or True)
        act = mod.WuchongActAction()

        with mod._LOCK:
            mod._SESSION["task_id"] = 560156
            mod._SESSION["latch_ts_battle_start"] = 0.0

        act.run(_CtxStub(), _ActArgv(param))
        first = len(clicks)
        act.run(_CtxStub(), _ActArgv(param))
        second = len(clicks)
        # 模拟「上一局打完、回到编队页」：闩锁时间戳已成「很久以前」→ 必须重新点。
        with mod._LOCK:
            mod._SESSION["latch_ts_battle_start"] = time.monotonic() - _LATCH_STALE_SEC
        act.run(_CtxStub(), _ActArgv(param))
        third = len(clicks)

        if first != 1:
            msgs.append(f"首次点「挑战」未落地（clicks={first}）")
        if second != 1:
            msgs.append(f"闩锁窗口内重复点了「挑战」（防连击失效）：clicks={second}")
        if third != 2:
            msgs.append(
                "超过闩锁窗口仍未重新点「挑战」（=「永不再点」→ 单人第二局点不到挑战 = 只打一局）："
                f"clicks={third}"
            )

        # 换任务必须清零闩锁时间戳（用临时账本，绝不碰真实 progress.json）。
        with tempfile.TemporaryDirectory() as td:
            mod.ledger.set_file(Path(td) / "p.json")
            with mod._LOCK:
                mod._SESSION["task_id"] = 560156
                mod._SESSION["latch_ts_battle_start"] = time.monotonic()
            mod._sync_task(561561)
            with mod._LOCK:
                ts = float(mod._SESSION.get("latch_ts_battle_start") or 0.0)
            if ts != 0.0:
                msgs.append(f"换任务（新 task_id）未清零 battle_start 闩锁时间戳（残留 {ts!r}）")
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        mod.ledger.set_file(None)
        if saved_file is not None:
            mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_latch_retries() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _latch_retry_failures(impl) == []


# ---------------------------------------------------------------------------
# 守卫 18：★「游戏模式」默认值 = 多人★（#75 / 规格 B5「默认多人」）
#
# 规格 B5：单人 / 多人 都要支持，由「游戏模式」选项决定，**默认多人**。
# 实测（本票开票时）：不选时的行为等价于「单人游戏」（DEFAULT equals solo-override: True）
# —— 与规格相反。这里把「不选 = 多人那一套」钉死：默认有效覆盖在五个模式相关节点上
# 必须与显式选「多人游戏」**逐字节相同**。
# ---------------------------------------------------------------------------
_MODE_NODES = (
    "WuchongModeSolo", "WuchongModeMulti", "WuchongTeamChallenge",
    "WuchongCoopChallenge", "WuchongStaleTeam",
)


def _mode_default_failures(root: Path | None = None) -> list:
    """默认（不选「游戏模式」）必须 = 「多人游戏」（规格 B5「默认多人」）。"""
    _paths()
    import interface_options as iopt  # noqa: PLC0415

    proj = Path(root) if root is not None else REPO_ROOT
    default = iopt.resolve_task_override(proj, "五重决战", {})
    multi = iopt.resolve_task_override(proj, "五重决战", {"游戏模式": "多人游戏"})
    msgs: list[str] = []
    for node in _MODE_NODES:
        if default.get(node) != multi.get(node):
            msgs.append(
                f"「游戏模式」默认值不是多人：{node} default={default.get(node)!r} multi={multi.get(node)!r}"
            )
    return msgs


def probe_wuchong_mode_default_multi() -> bool:
    return _mode_default_failures() == []


HOOKS = [
    (
        "wuchong-config-is-source-of-truth",
        "#56",
        "五重配置权威在 scene.wuchong：wuchong_impl 快照 + wuchong.json 模板/阈值/手操动作/开关均派生自它",
        probe_wuchong_config_is_source_of_truth,
    ),
    (
        "wuchong-manual-cadence-parameterised",
        "#56",
        "手操战斗节奏可参数化：弹板间隔/技能间隔/每几次弹板放技能/连点批量 全部真的被使用；"
        "★#71 手操持续到正面终止点才交还、无固定时长上限★（2026-10-16：不用 HUD 判据，认不出的帧继续点；"
        "stopped 合法集 {manual_off,battle_over,left,stopped}）；自动模式不点",
        probe_wuchong_manual_cadence_parameterised,
    ),
    (
        "wuchong-cross-mode-auto",
        "#56",
        "跨模式「自动」规则：只有五重允许手动，其余战斗一律自动（夹值 + 只五重任务挂是否手操）",
        probe_wuchong_cross_mode_auto,
    ),
    (
        "wuchong-flow-materialised",
        "#56",
        "流程链在 pipeline 上按数据落地：每步 next=异常前缀+后继、枢纽=hub_next()、链尾 DirectHit 无 max_hit",
        probe_wuchong_flow_materialised,
    ),
    (
        "wuchong-banner-distinct",
        "#56",
        "行/详情页用模板匹配且两张裁片可靠区分（自证≈1.0，互比<阈值；裁片入库、非空白）",
        probe_wuchong_banner_distinct,
    ),
    (
        "wuchong-classify-positives",
        "#56",
        "wuchong_impl.classify 对 列表/详情/模式/房间/招募弹窗/编队/结算/战斗/主城/加载 正判 + 反例",
        probe_wuchong_classify_positives,
    ),
    (
        "wuchong-no-global-table-growth",
        "#56",
        "五重不污染全局页面判据表（注册表 API 证明：无重名、无五重页面、缺省链页集未污染、per-scene 不累积）",
        probe_wuchong_no_global_table_growth,
    ),
    (
        "wuchong-recruit-dialog-before-auto",
        "#56",
        "招募方式弹窗在屏 → 先走「开始招募」：RecruitOpen.next 把 RecruitStart 排在 TeamAutoSet 之前，"
        "且机制侧开关动作见到弹窗画面一律拒绝点击（绝不点在弹窗背板上）",
        probe_wuchong_recruit_dialog_before_auto,
    ),
    (
        "wuchong-room-has-exit",
        "#56",
        "共斗房有出路：RoomWait.next 含 RecruitOpen/TeamChallenge，RecruitOpen 有界 max_hit，"
        "停留时钟不被过渡帧清零，停留过久由 wuchong_giveup 有理由收工（绝不无限死等）",
        probe_wuchong_room_has_exit,
    ),
    (
        "wuchong-battle-engine-gated",
        "#56",
        "手操引擎关 ⇒ WuchongBattle 绝不被选中（raw/自动 = __NONE__；手操 case 显式开启 + manual=true）；"
        "动作只用场景几何、manual=off 带原因停下（绝不空框空转）",
        probe_wuchong_battle_engine_gated,
    ),
    (
        "wuchong-mode-gates",
        "#56",
        "游戏模式门控有效流水线：多人 ⇒ ModeSolo 关 **且** TeamChallenge 要求 room_seen=true、"
        "CoopChallenge/StaleTeam 打开；单人 ⇒ ModeMulti 关 且二者保持关（关一张卡不足以让多人成立）",
        probe_wuchong_mode_gates,
    ),
    (
        "wuchong-room-before-battle",
        "#56",
        "房间先于战斗（验收判据）：多人 + 未进房 → 绝不认单人编队页的「挑战」；进过房才允许；"
        "共斗房的挑战只在房间（已招募）命中；stale 编队页有「返回」出口（真实识别器 + 真机形态帧）",
        probe_wuchong_room_before_battle,
    ),
    (
        "wuchong-switch-readable-without-pil",
        "#56",
        "开关读数不依赖 PIL：屏蔽 PIL（模拟随包便携 Python 无 Pillow）后 _orange_ratio/read_switch_state "
        "仍读得出「开」—— 否则编队页/房间页「自动」永远关不掉（真机 on=null reason=state_unknown）",
        probe_wuchong_switch_readable_without_pil,
    ),
    (
        "wuchong-manual-survives-option-merge",
        "#56",
        "手操确定性不被选项合并吃掉：按真机语义（各选项 override 先后整体替换 action.param）求有效参数，"
        "手操时 WuchongBattle.custom_action_param.manual 仍须为 true（否则引擎一次都不点）",
        probe_wuchong_manual_survives_option_merge,
    ),
    (
        "wuchong-fight-count",
        "#56",
        "「打几次」：GUI 选项覆盖 WuchongGiveUp.target_fights；每**进入一场战斗**（战斗 HUD 首次"
        "出现，规格 B2/D2）记一笔账本 wuchong/fight/{n}；续关后回到战斗不再计、结算页不再计；"
        "打够 N 次由既有 wuchong_giveup 收工；0=不限制、未够不放行、同状态帧不重复计",
        probe_wuchong_fight_count,
    ),
    (
        "wuchong-interface-no-duplicate-keys",
        "#56",
        "interface.json 无重复键：option 是全局命名空间，同名键后者覆盖前者会静默吃掉前一份；"
        "五重次数项须用带「五重」前缀的键名，绝不与「自动刷副本」的「打几次」撞键",
        probe_wuchong_interface_no_duplicate_keys,
    ),
    (
        "wuchong-latch-retries",
        "#56",
        "「开始类」闩锁 = 重试窗口（不是「永不再点」）：窗口内不连点、超窗可重试、换任务清零"
        "—— 否则单人第二局点不到「挑战」= 只打一局（本票「记一次就收工 / 没打几分钟就结束」的机制真凶）",
        probe_wuchong_latch_retries,
    ),
    (
        "wuchong-mode-default-multi",
        "#75",
        "「游戏模式」默认 = 多人（规格 B5）：不选时有效覆盖在 ModeSolo/ModeMulti/TeamChallenge/"
        "CoopChallenge/StaleTeam 五个节点上必须与显式『多人游戏』逐字节相同",
        probe_wuchong_mode_default_multi,
    ),
    (
        "wuchong-giveup-out-of-fight",
        "#76",
        "「已打够 N 次」不许在**战斗 episode 内**收工（收工时机 = fight_target_reached，计数点不变）："
        "战斗帧打够不收工、结算/编队页（战斗已收场）必收工、未打够不收工、0=不限制不收工",
        probe_wuchong_giveup_out_of_fight,
    ),
    (
        "wuchong-unknown-not-counted-in-fight",
        "#76",
        "战斗 episode 内的 `unknown` 帧不计「未知画面」（判据 = counts_as_unknown）："
        "battle/unknown 闪烁 6 轮仍为 0；离开本场 / 进战斗前照旧计数（真·迷路仍会被收工兜底接走）",
        probe_wuchong_unknown_not_counted_in_fight,
    ),
]


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
