# -*- coding: utf-8 -*-
"""``apply`` / ``strip`` —— 把配置层的派生产物**幂等**写进真实 JSON，且可**逐字节撤销**（ticket #16）。

ADR-0001 的「注入」职责在此落地：#3/#4/#5/#6 能**派生**、#7 能**校验**，但在此之前
**没有任何东西把派生产物写进真实 JSON**（#7 明确把「落盘」留给了迁移票，而迁移票里
没有这一项）。本模块补上这个洞，**只做机制**：

* :func:`apply` —— 三类写入：
  1. GUI 目标选项块 → ``assets/interface.json`` 的 option「打哪个副本」：内容已与配置
     一致时不重复注入；缺失 / 不一致时用 #6 的 :func:`scene.options.inject_option`
     注入一份**带成对标记**的生成块（``strip`` 可剥离）；
  2. 事件组注入 → ``special_dungeon.json`` 里**每个流程节点** ``next`` 的候选集：
     #18 起**两类位置不同** —— **打断型**（九类异常）作前缀、
     **兜底型**（归位）作后缀（在原有后继之后、DirectHit 恢复边之前）；顺序 =
     :data:`scene.events.EVENTS`；
  3. **事件层节点定义**（含归位 ``PubReturnHome``）→ ``common.json``（#10 前置实测：
     #16 只写候选集不写定义，注入的 ``[JumpBack]PubReturnHome`` 会**悬空**）；
* :func:`strip` —— 把上面三类写入**逐字节**还原。

不变量（验收标准）：

* **幂等**：``apply`` 连续两次，``assets/**`` 字节不变（ADR-0001：重跑不假脏）；
* **可逆**：``apply`` 后 ``strip``，整棵树与 apply 前**逐字节一致**；
* ``scene.drift.check_all()`` 在 apply 后为空（无漂移）。

做法（为什么能逐字节可逆，且**不丢注释**）
------------------------------------------
* **pipeline（#10 返工）**：pipeline JSON 里**有大量 ``//`` 注释**，`本项目把「顺序 /
  分派的理由」当语义，注释是承重的`。因此**绝不可**用 ``json.dumps`` 重渲染数组
  （会丢注释），也**不留 ``orig=`` 标记**（那会在文件里放两份内容，破坏 ADR-0001 的
  「人类可读」）。改为**纯行插入**：``apply`` 只把事件组引用**作为新行插在第一个元素
  之前**，原数组的每一个字节（含注释、缩进、顺序）**原地不动**；``strip`` **只删掉这些
  被插入的行**。是否已注入按**内容**判定（候选集前缀 == 配置的事件组），故重跑字节不变。
* **interface**：复用 #6 ``inject_option`` 的**成对标记**；已生效块 == 配置派生块时不注入。
* **common.json**：事件层节点定义用成对标记；定义已在场则不写。

★范围★ #10 起本模块**不再**是「只加壳」：它把事件层节点定义**写进** common.json。
但**页面锚定链的形状**（#4）仍是 pipeline 里**手写**的（ADR-0001：JSON 保留人类可读的
链；配置只**校验**它 —— 见 ``scene.drift.chain_drift``），本模块只把事件组注入到
**已经写好的链**上。

默认只写 ``assets/resource/pipeline/special_dungeon.json``（本 family 的流程文件）的
候选集，节点定义写 ``EVENT_DEFS_REL``；文件集合可经 ``pipeline_files`` 参数扩展。
默认**不碰** ``agent/**``：真实 ``assets/**`` 只有在调用方**显式** ``apply`` 时才会被改动
（套件 / 挂点一律在 ``tempfile`` 副本上演练）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from . import options as _options
from .events import (
    EVENT_NODE_DEFS,
    EVENTS,
    RETURN_HOME_NODE_NAME,
    event_refs,
    fallback_refs,
    interrupt_refs,
)

if TYPE_CHECKING:  # pragma: no cover - 仅供类型标注
    from .config import FamilyConfig

# repo 内的相对路径。
INTERFACE_REL = "assets/interface.json"
PIPELINE_DIR_REL = "assets/resource/pipeline"

# 默认写入的 pipeline 文件（本 family 的流程文件）。可经 ``pipeline_files`` 扩展。
PIPELINE_FILES: tuple[str, ...] = ("special_dungeon.json",)

# #6 的 interface 生成区标记（成对；由 scene.options 拥有，这里只引用）。
_OPTION_BEGIN = _options._BEGIN
_OPTION_END = _options._END

# #10：事件层节点定义写进 common.json（注入的 [JumpBack]PubReturnHome 必须有定义，
# 否则悬空；见 ticket #10 的前置实测）。GUI 选项块由 ``scene.options.inject_option``
# 负责（内容已与配置一致时 apply 不重复注入）。
_EVDEF_BEGIN = "// >>> scene.apply (#10) event-defs begin: 事件层节点定义由配置注入，请勿手改 <<<"
_EVDEF_END = "// <<< scene.apply (#10) event-defs end <<<"

# 事件层节点定义写进哪个 pipeline 文件：事件层是**跨场景**的，归位是通用事件，
# 故与 common.json 里那些 ``Pub*`` 同处一地（ADR-0003：事件只引用公共节点）。
EVENT_DEFS_REL = "assets/resource/pipeline/common.json"

_INDENT = "    "  # 4 空格（与仓库 pipeline 缩进风格一致）

# 一行 JSONC 文本「不是候选集元素」时返回的哨兵（区别于合法的 JSON 值 None/[]）。
_NOT_ELEM = object()


# ---------------------------------------------------------------------------
# 小工具：JSONC 注释剥离 / 文本扫描（自足一份，不整体重写 JSON）
# ---------------------------------------------------------------------------
def _strip_jsonc(text: str) -> str:
    """移除 JSONC 注释，保持 JSON 结构（供 json.loads 一个数组文本）。"""
    out: list[str] = []
    state = 0  # 0=正常 1=字符串 2=转义
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if state == 0:
            if ch == '"':
                out.append(ch)
                state = 1
                i += 1
            elif text[i : i + 2] == "//":
                while i < n and text[i] != "\n":
                    i += 1
            elif text[i : i + 2] == "/*":
                i += 2
                while i + 1 < n and text[i : i + 2] != "*/":
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


def _skip_ws_comments(text: str, i: int) -> int:
    """跳过空白与 JSONC 注释，返回下一个有意义字符的下标（EOF -> len）。"""
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            if j == -1:
                return n
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                return n
            i = j + 2
        else:
            return i
    return n


def _match_bracket(text: str, lb: int) -> int:
    """从 ``[`` 出发，跳过字符串与注释，返回配对的 ``]`` 下标（找不到 -> -1）。"""
    n = len(text)
    depth = 0
    i = lb
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            i = j + 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _scan_next_arrays(text: str) -> list[dict]:
    """扫出所有「节点对象里的 ``next`` 数组」（文本级，不解析整份 JSON）。

    返回每项的 ``{node, key_start, lb, rb}``：``node`` 顶层节点名、``key_start`` 是
    ``"next"`` 键引号的起点、``lb``/``rb`` 是数组方括号（闭区间，都是下标）。
    仅在深度恰为「节点对象内」时识别，故不会误认嵌套结构里的同名键。
    """
    out: list[dict] = []
    i = 0
    n = len(text)
    depth = 0
    pending_key = None
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            token = text[i : j + 1]
            if depth == 1:
                try:
                    pending_key = json.loads(token)
                except json.JSONDecodeError:
                    pending_key = None
            elif depth == 2 and token == '"next"':
                k = _skip_ws_comments(text, j + 1)
                if k < n and text[k] == ":":  # 跳过分隔冒号，再看是不是数组
                    k = _skip_ws_comments(text, k + 1)
                if k < n and text[k] == "[" and pending_key is not None:
                    rb = _match_bracket(text, k)
                    if rb != -1:
                        out.append(
                            {"node": pending_key, "key_start": i, "lb": k, "rb": rb}
                        )
                        i = rb + 1
                        continue
            i = j + 1
            continue
        if ch in "{[":
            depth += 1
            i += 1
            continue
        if ch in "}]":
            depth -= 1
            i += 1
            continue
        i += 1
    return out


def _shell_lines(refs: list[str], indent: str) -> str:
    """事件组引用行（每行一个、带尾逗号；缩进 = ``indent``）。"""
    return "".join(f"{indent}{json.dumps(r, ensure_ascii=False)},\n" for r in refs)


# ---------------------------------------------------------------------------
# 注入的引用来源（单独一个函数，便于证明「改坏即变红」）
# ---------------------------------------------------------------------------
def _event_own_nodes() -> set[str]:
    """事件层自带节点名（不向它们注入事件，避免自引用）——与 inject_events 默认一致。"""
    return {node for e in EVENTS for node in e.nodes}


# ---------------------------------------------------------------------------
# 文本级变换：pipeline（#5/#8 / #10 / #18） —— **纯行插入 / 纯行删除**，绝不重渲染数组。
#
# #10 的返工点：#16 原实现把整个 ``next`` 数组重渲染、并把原文编码进 ``orig=`` 标记，
# 那会**丢掉数组里的注释**（本项目把「顺序/分派的理由」当语义，注释是承重的），
# 也会在文件里留下两份内容。现改为**逐行**处理：
#   * ``apply`` 只把事件组引用**作为新行**插入：**打断型前缀**插在 ``[`` 那一行之后、
#     **兜底型后缀**插在最后一个原有候选行（DirectHit 恢复边 / 终点）之前；
#     原数组的每一个字节（含注释、顺序）原地不动；
#   * ``strip`` 只删掉这些被插入的行（按内容判定，无标记、无 orig）；
#   * 「是否已注入」按内容判定：候选集 == 规范形（[前缀] + 原有后继[:-1] + [后缀] + 原末位）
#     即视为已注入（幂等）。
# ---------------------------------------------------------------------------
def _jsonc_line_value(line: str):
    """把一行 JSONC 文本解成它的 JSON 值；不是「候选集元素行」时返回 ``_NOT_ELEM``。"""
    s = _strip_jsonc(line).strip()
    if not s or s in ("[", "]"):
        return _NOT_ELEM
    core = s.rstrip(",").strip()
    if not core or core in ("[", "]"):
        return _NOT_ELEM
    try:
        return json.loads(core)
    except json.JSONDecodeError:
        return _NOT_ELEM


def _is_event_ref_line(line: str, ref_set: set[str]) -> bool:
    value = _jsonc_line_value(line)
    return isinstance(value, str) and value in ref_set


def _line_indent(line: str) -> str:
    """一行的行首空白。"""
    return line[: len(line) - len(line.lstrip(" \t"))]


def _remove_event_lines(arr: str, ref_set: set[str]) -> str:
    """删掉数组文本里所有事件引用行（纯行删除，其它字节原地不动）。"""
    lines = arr.splitlines(keepends=True)
    return "".join(ln for ln in lines if not _is_event_ref_line(ln, ref_set))


def _transform_next_array(arr: str, prefix: list[str], suffix: list[str]) -> str:
    """把一个 ``next`` 数组文本重排为规范形（纯行插入 / 删除，绝不重渲染）。

    步骤：① 删掉全部事件引用行；② 在 ``[`` 行之后插入打断型前缀行；
    ③ 在最后一个原有候选行之前插入兜底型后缀行。
    """
    ref_set = set(prefix) | set(suffix)
    lines = arr.splitlines(keepends=True)
    kept = [ln for ln in lines if not _is_event_ref_line(ln, ref_set)]

    last_idx = None
    for i, ln in enumerate(kept):
        if i == 0 or i == len(kept) - 1:
            continue  # 首行是 ``[``、末行是 ``]``
        if _jsonc_line_value(ln) is not _NOT_ELEM:
            last_idx = i
    if last_idx is None:
        return "".join(kept)

    prefix_indent = _line_indent(kept[1]) if len(kept) > 1 else _INDENT
    suffix_indent = _line_indent(kept[last_idx])
    prefix_lines = _shell_lines(prefix, prefix_indent)
    suffix_lines = _shell_lines(suffix, suffix_indent)

    out: list[str] = []
    for i, ln in enumerate(kept):
        if i == last_idx:
            out.append(suffix_lines)
        out.append(ln)
        if i == 0:
            out.append(prefix_lines)
    return "".join(out)


def _canonical_next(entries: list, prefix: list[str], suffix: list[str]) -> list:
    """规范形：``[前缀] + 原有后继[:-1] + [后缀] + 原有末位``。"""
    ref_set = set(prefix) | set(suffix)
    body = [x for x in entries if x not in ref_set]
    if not body:
        return [*prefix, *suffix]
    return [*prefix, *body[:-1], *suffix, *body[-1]]


def _apply_events_to_text(text: str) -> str:
    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    own = _event_own_nodes()
    edits: list[tuple[int, int, str]] = []
    for span in _scan_next_arrays(text):
        if span["node"] in own:
            continue
        lb, rb = span["lb"], span["rb"]
        arr = text[lb : rb + 1]
        entries = json.loads(_strip_jsonc(arr))
        if not entries:
            continue
        if entries == _canonical_next(entries, prefix, suffix):
            continue  # 已是规范形（按内容判定；重跑字节不变）
        edits.append((lb, rb, _transform_next_array(arr, prefix, suffix)))
    for lb, rb, new_arr in sorted(edits, key=lambda t: t[0], reverse=True):
        text = text[:lb] + new_arr + text[rb + 1 :]
    return text


def _strip_events_from_text(text: str) -> str:
    ref_set = set(event_refs())
    own = _event_own_nodes()
    edits: list[tuple[int, int, str]] = []
    for span in _scan_next_arrays(text):
        if span["node"] in own:
            continue
        lb, rb = span["lb"], span["rb"]
        arr = text[lb : rb + 1]
        stripped = _remove_event_lines(arr, ref_set)
        if stripped != arr:
            edits.append((lb, rb, stripped))
    for lb, rb, new_arr in sorted(edits, key=lambda t: t[0], reverse=True):
        text = text[:lb] + new_arr + text[rb + 1 :]
    return text


def _indent_json(obj: object, indent: str) -> str:
    """确定性 JSON：固定 indent=4，再把每一行整体右移 ``indent``。"""
    raw = json.dumps(obj, ensure_ascii=False, indent=4)
    return raw.replace("\n", "\n" + indent)


def _option_block_matches(text: str, cfg: "FamilyConfig") -> bool:
    """interface 里**生效**（json.loads 后写者胜）的「打哪个副本」块是否已等于配置派生块。"""
    try:
        data = json.loads(_strip_jsonc(text))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    option = data.get("option")
    if not isinstance(option, dict):
        return False
    return option.get(_options.OPTION_NAME) == _options.derive_option_block(cfg)


def _apply_option_to_text(text: str, cfg: "FamilyConfig") -> str:
    """GUI 目标选项：派生的「打哪个副本」块。

    已生效块 == 配置派生块 -> 不重复注入（幂等，且不假脏）；否则用 #6 的
    :func:`scene.options.inject_option` 注入一份带成对标记的生成块（strip 可逐字节剥离）。
    """
    if _option_block_matches(text, cfg):
        return text
    return _options.inject_option(text, cfg)


def _strip_option_from_text(text: str) -> str:
    """剥离 :func:`scene.options.inject_option` 写入的生成区（成对标记）。"""
    bi = text.find(_OPTION_BEGIN)
    ei = text.find(_OPTION_END)
    if bi == -1 or ei == -1 or ei < bi:
        return text
    s = text.rfind("\n", 0, bi)
    if s == -1:
        return text
    return text[:s] + text[ei + len(_OPTION_END):]


# ---------------------------------------------------------------------------
# 检查 3 的写入：事件层节点定义（#10 前置的悬空引用修复）
# ---------------------------------------------------------------------------
def _render_event_defs_region() -> str:
    name = RETURN_HOME_NODE_NAME
    spec = EVENT_NODE_DEFS[name]
    body = _indent_json(spec, _INDENT)
    return (
        f"{_INDENT}{_EVDEF_BEGIN}\n"
        f'{_INDENT}"{name}": {body},\n'
        f"{_INDENT}{_EVDEF_END}"
    )


def _apply_event_defs_to_text(text: str) -> str:
    """把事件层节点定义写进 common.json 文本（幂等、可剥离）。

    * 生成区已存在 -> 重渲染（字节不变）；
    * 否则若定义**已在场**（手写）-> 不写（避免重复键；手写的定义由 drift 校验）；
    * 否则插到顶层对象的 ``{`` 之后。
    """
    bi = text.find(_EVDEF_BEGIN)
    if bi != -1:
        ei = text.find(_EVDEF_END, bi)
        if ei != -1:
            line_start = text.rfind("\n", 0, bi) + 1
            region = _render_event_defs_region()
            return text[:line_start] + region + text[ei + len(_EVDEF_END):]

    if f'"{RETURN_HOME_NODE_NAME}"' in text:
        return text

    lb = text.find("{")
    if lb == -1:
        raise ValueError("common.json 文本里找不到顶层 {，无法写入事件层节点定义")
    region = _render_event_defs_region()
    return text[: lb + 1] + "\n" + region + text[lb + 1:]


def _strip_event_defs_from_text(text: str) -> str:
    """去除事件层节点定义的生成区（逐字节还原到写入前）。"""
    bi = text.find(_EVDEF_BEGIN)
    if bi == -1:
        return text
    ei = text.find(_EVDEF_END, bi)
    if ei == -1:
        return text
    s = text.rfind("\n", 0, bi)
    if s == -1:
        s = bi
    return text[:s] + text[ei + len(_EVDEF_END):]


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def _pipeline_paths(repo_root: Path, pipeline_files) -> list[Path]:
    base = Path(repo_root) / PIPELINE_DIR_REL
    names = PIPELINE_FILES if pipeline_files is None else tuple(pipeline_files)
    return [base / name for name in names]


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _read(path: Path) -> str:
    """按 UTF-8 读取，**不做换行翻译**（保证逐字节可逆）。"""
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    """按 UTF-8 写回，**不做换行翻译**（保证逐字节可逆）。"""
    path.write_bytes(text.encode("utf-8"))


def apply(
    repo_root: str | Path,
    cfg: "FamilyConfig | None" = None,
    *,
    pipeline_files=None,
) -> list[str]:
    """把配置派生的两条加性写入落进 ``repo_root`` 下的真实 JSON；返回被改动的相对路径。

    幂等：对已 apply 过的树再调一次，字节不变（返回空列表）。
    """
    root = Path(repo_root)
    if cfg is None:
        from .lord_battle import LORD_BATTLE

        cfg = LORD_BATTLE

    changed: list[str] = []

    interface = root / INTERFACE_REL
    text = _read(interface)
    new_text = _apply_option_to_text(text, cfg)
    if new_text != text:
        _write(interface, new_text)
        changed.append(INTERFACE_REL)

    for path in _pipeline_paths(root, pipeline_files):
        text = _read(path)
        new_text = _apply_events_to_text(text)
        if new_text != text:
            _write(path, new_text)
            changed.append(_rel(root, path))

    # #10：事件层节点定义（含归位）写进其公共所在地，修复悬空引用。
    evdefs = root / EVENT_DEFS_REL
    text = _read(evdefs)
    new_text = _apply_event_defs_to_text(text)
    if new_text != text:
        _write(evdefs, new_text)
        changed.append(EVENT_DEFS_REL)

    return changed


def strip(repo_root: str | Path, *, pipeline_files=None) -> list[str]:
    """把 :func:`apply` 的写入逐字节撤销；返回被还原的相对路径。"""
    root = Path(repo_root)
    changed: list[str] = []

    for path in _pipeline_paths(root, pipeline_files):
        text = _read(path)
        new_text = _strip_events_from_text(text)
        if new_text != text:
            _write(path, new_text)
            changed.append(_rel(root, path))

    interface = root / INTERFACE_REL
    text = _read(interface)
    new_text = _strip_option_from_text(text)
    if new_text != text:
        _write(interface, new_text)
        changed.append(INTERFACE_REL)

    evdefs = root / EVENT_DEFS_REL
    text = _read(evdefs)
    new_text = _strip_event_defs_from_text(text)
    if new_text != text:
        _write(evdefs, new_text)
        changed.append(EVENT_DEFS_REL)

    return changed
