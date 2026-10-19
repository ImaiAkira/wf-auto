# -*- coding: utf-8 -*-
"""#120：maa v5 的 ``Rect`` 不是 list —— 框解包必须保留浮点，动作异常必须留痕。

真机现场（484，``--trace LordsEntry``）
---------------------------------------
::

    File "agent\\lords_impl.py", line 2465, in _tab_click
        if box is None or len(box) != 4:
    TypeError: object of type 'Rect' has no len()
    Exception ignored on calling ctypes callback function <function CustomAction._c_run_agent ...>

``maa.define.Rect`` 是 ``@dataclass(x, y, w, h)``：有 ``__iter__`` / ``__getitem__``，
**没有** ``__len__``。因此 ``len(box)`` 当场抛，而异常是从 **ctypes 回调**里冒出去的 ——
CPython 只记一行 ``Exception ignored ...`` 就把它丢掉，框架只知道「动作失败」。

后果链（症状离病因极远）：

1. 页签**根本没点下去**；
2. 框架不报错，流程「看起来在跑」；
3. 随后按 #19 正确收工（``页签未确认到「领主战」…可见行族=('joss',)``）——
   现场只能看到第 3 步，看到的是「识别/确认」问题，真因是第 1 步的一个 ``len``。

四个挂点
--------
1. ``lords-rect-box-unpack``
   ★假 Rect★（只有 ``.x/.y/.w/.h``，**没有** ``__len__`` / ``__iter__`` / ``__getitem__``）：
   ``_tab_click`` 必须算出**正确中心**并真的调用点击（注入 ``_click_hook`` 看它收到的实参），
   默认路径 ``run()`` → ``_click_box`` → ``PubClick`` 也必须落下（真机走的就是这条）。
2. ``lords-rect-float-center``
   ★浮点不丢★：``Rect(x=12.5, y=20.25, w=3.0, h=4.5)`` 解包后中心 ``(14.0, 22.5)`` ==
   手算值；奇数宽度（197）的中心是 ``300.5``，**不许**被截断成 300。
   取整只许发生在 ``_click_box``（真正发点击那一下）。
3. ``lords-action-error-trace``
   ★异常不许被吞★：注入一个必抛的 ``_click_hook`` ⇒ ``run()`` 如实返回 ``False``（而不是让
   异常冒进 ctypes 被丢掉），并且日志里有**一行醒目**的 ``★动作异常★`` + 异常类型 + 消息 + 栈。
4. ``lords-rect-no-len``
   **静态**：``agent/lords_impl.py`` 里不许再出现 ``len(<…box…>)`` 或对裸 ``box`` 的下标取值
   （AST 判 —— 注释/文档串里写 ``len(box)`` 是说明，不算）。

破坏实验（``python tools\\contract_hooks\\hooks_120.py``，全部在内存里做）
--------------------------------------------------------------------------
① 把 ``len(box)`` 改回来（解包退回「先 len 再下标」）→ 挂点 1 红；
② 解包里加 ``int()`` 截断 → 挂点 2 红；
③ 去掉 ``★动作异常★`` 留痕（只吞不喊 / 连兜都不兜）→ 挂点 3 红；
④ 让源码里重新出现 ``len(box)``（= 有人又写了一遍）→ 挂点 4 红。

★诚实边界★
* 本守卫**不碰设备**：它证的是「实现能正确处理 ``Rect`` 形状与浮点中心」，不是「今天真机上
  页签一定点得中」（后者是 #100 的 ``lords-tab-confirm`` 那一类真机标定）。
* 假 Rect **刻意比真 ``Rect`` 更严**（连 ``__iter__`` 都不给）：两条路都试的实现才能同时满足
  真机（``Rect``）与离线假 argv（``list``）—— 这是本票的教训，不是过度设计。
"""

from __future__ import annotations

import ast
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
AGENT_DIR = REPO_ROOT / "agent"
HOOKS_DIR = Path(__file__).resolve().parent
IMPL_PATH = AGENT_DIR / "lords_impl.py"

HOOK_ID_RECT = "lords-rect-box-unpack"
HOOK_ID_FLOAT = "lords-rect-float-center"
HOOK_ID_TRACE = "lords-action-error-trace"
HOOK_ID_NOLEN = "lords-rect-no-len"

_TICKET = "#120"

#: 真机那条 ``TypeError`` 的原文（守卫按它认「这个坑还在不在」）。
RECT_TYPE_ERROR = "object of type 'Rect' has no len()"


# ---------------------------------------------------------------------------
# 惰性导入（与同目录其它 hooks 同一手法：挂点模块 import 期必须保持轻）
# ---------------------------------------------------------------------------
def _paths() -> None:
    for path in (str(REPO_ROOT), str(TOOLS_DIR), str(AGENT_DIR), str(HOOKS_DIR)):
        if path not in sys.path:
            sys.path.append(path)


def _impl():
    """``agent/lords_impl``（被守卫的实现）。"""
    _paths()
    import lords_impl

    return lords_impl


def _fakes():
    """假 argv / 假 context 借 ``hooks_100``（同一批真机帧读数与假 I/O，不抄第二份）。"""
    _paths()
    import hooks_100

    return hooks_100


# ---------------------------------------------------------------------------
# 假 Rect / 假点击 hook
# ---------------------------------------------------------------------------
class FakeRect:
    """★真机那个 ``maa.define.Rect`` 的替身★：只有 ``.x/.y/.w/.h``。

    ★刻意**连** ``__iter__`` / ``__getitem__`` 都不给★：真 ``Rect`` 有这两个、但没有
    ``__len__``；这里更严一档，逼实现必须走 ``.x/.y/.w/.h``。离线假 argv 给的是 ``list``
    （走下标），两边的形状**都被**覆盖到，才不会出现「离线全绿、真机第一下就炸」。
    """

    def __init__(self, x, y, w, h) -> None:
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def __repr__(self) -> str:  # noqa: D105
        return f"Rect(x={self.x!r}, y={self.y!r}, w={self.w!r}, h={self.h!r})"


class _Patched:
    """临时替换对象属性（破坏实验与注入都用它；退出必定恢复）。"""

    def __init__(self, owner, name: str, value) -> None:
        self.owner = owner
        self.name = name
        self.value = value
        self.saved = None

    def __enter__(self):
        self.saved = getattr(self.owner, self.name)
        setattr(self.owner, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.owner, self.name, self.saved)
        return False


class ClickRecorder:
    """替换 ``lords_impl._click_hook``：把动作算出的中心**原样**记下来（浮点不丢才有意义）。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.saved = None

    def __enter__(self):
        impl = _impl()
        self.saved = impl._click_hook
        impl._click_hook = self
        impl.reset_sessions()
        return self

    def __call__(self, context, cx, cy) -> bool:
        self.calls.append((cx, cy))
        return True

    def __exit__(self, *exc):
        impl = _impl()
        impl._click_hook = self.saved
        impl.reset_sessions()
        return False

    def centers(self) -> list:
        return list(self.calls)


def _fake_rect_is_faithful() -> list:
    """假 Rect 与真 ``Rect`` 都**必须**没有 ``__len__``（否则本守卫就是假绿）。"""
    msgs: list = []
    try:
        len(FakeRect(0, 0, 1, 1))
    except TypeError:
        pass
    else:
        msgs.append("FakeRect 竟然有 __len__ —— 它不再像 maa v5 的 Rect，守卫会假绿")
    try:
        from maa.define import Rect as MaaRect
    except Exception as exc:  # noqa: BLE001 - 取不到病因对象就没法断言，如实说
        msgs.append(f"取不到 maa.define.Rect（#120 的病因就是它没有 __len__）：{exc!r}")
    else:
        try:
            len(MaaRect())
        except TypeError as exc:
            if RECT_TYPE_ERROR.split(" has ")[0] not in str(exc):
                msgs.append(f"len(Rect()) 的报错形状变了（{exc}）—— #120 的病因判断要复核")
        else:
            msgs.append("maa.define.Rect 竟然有 __len__ —— #120 的病因判断要复核")
    return msgs


# ---------------------------------------------------------------------------
# 挂点 1：假 Rect 走 _tab_click / run
# ---------------------------------------------------------------------------
#: 页签框（720 空间，"降临讨伐" 那一档；= ``hooks_100.LIST_FRAME`` 的同名读数）。
TAB_BOX = (481, 389, 117, 33)
#: 列表行名框（720 空间；奇数宽度 197 ⇒ 中心带 .5，#120 的浮点断言用它）。
ROW_BOX = (202, 640, 197, 28)


def _tab_rect_failures() -> list:
    """假 Rect：中心算对 + 真的点了（注入 ``_click_hook`` 看实参；再走一遍真 ``PubClick``）。"""
    impl = _impl()
    fake = _fakes()
    msgs: list = list(_fake_rect_is_faithful())
    rect = FakeRect(*TAB_BOX)
    want_center = (TAB_BOX[0] + TAB_BOX[2] / 2.0, TAB_BOX[1] + TAB_BOX[3] / 2.0)  # (539.5, 405.5)

    # (a) 解包：不许 int() 截断、不许 len()
    try:
        unpacked = impl._box_xywh(rect)
        center = impl._box_center(rect)
    except Exception as exc:  # noqa: BLE001 - 解包自己抛 = 真机那个 TypeError，记成失败
        msgs.append(
            f"_box_xywh/_box_center 在假 Rect 上抛了 {type(exc).__name__}: {exc} —— "
            f"这就是真机页签点不下去的那一下（{RECT_TYPE_ERROR}）"
        )
        return msgs
    if unpacked != TAB_BOX:
        msgs.append(f"_box_xywh(Rect) 应给 {TAB_BOX}，实际 {unpacked!r}")
    if center != want_center:
        msgs.append(f"_box_center(Rect) 应是手算中心 {want_center}，实际 {center!r}")

    # (b) _tab_click：必须算出中心并真的调用注入的 _click_hook（浮点原样）
    action = impl.LordsUnlockAction()
    task = 1201
    with ClickRecorder() as recorder:
        session = impl._session(task)
        try:
            ok = action._tab_click(
                fake.FakeContext(),
                fake.FakeArgv(task_id=task, box=rect, act_param={"do": "tab"}),
                session,
            )
        except Exception as exc:  # noqa: BLE001 - 这里抛 = ctypes 会把它静默丢掉（#120 现场）
            msgs.append(
                f"_tab_click 在假 Rect 上抛了 {type(exc).__name__}: {exc} —— "
                f"真机上这一下会被 ctypes 回调吞掉，页签根本不会点下去"
            )
            return msgs
        if ok is not True:
            msgs.append(f"_tab_click 用假 Rect 时应成功，实际返回 {ok!r}（页签没点下去）")
        if recorder.centers() != [want_center]:
            msgs.append(
                f"_tab_click 传出的中心应是 {want_center}，实际 {recorder.centers()!r}（{RECT_TYPE_ERROR}）"
            )
        if session.attempts_since_read != 0:
            msgs.append("点页签被记成了「一次目标点击」（attempts_since_read != 0）—— 会误判本轮结束")

    # (c) 整条默认路径：run() → _click_box() → PubClick（真机走的就是这条）
    impl.reset_sessions()
    ctx = fake.FakeContext()
    task = 1202
    try:
        ok = action.run(
            ctx, fake.FakeArgv(task_id=task, box=FakeRect(*TAB_BOX), act_param={"do": "tab"})
        )
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"run(do=tab) 在假 Rect 上抛了 {type(exc).__name__}: {exc}")
        return msgs
    if ok is not True:
        msgs.append(f"run(do=tab) 用假 Rect 时应成功，实际 {ok!r}")
    clicked = ctx.clicked_centers()
    want_click = (int(want_center[0]), int(want_center[1]))    # 取整只发生在 _click_box
    if clicked != [want_click]:
        msgs.append(f"真机那条路（PubClick）应落在 {want_click}，实际 {clicked!r}")

    # (d) 默认 do=click：框架给的 Rect 也要能点（同一类崩溃的第二个入口）
    ctx2 = fake.FakeContext()
    task = 1203
    try:
        ok = action.run(ctx2, fake.FakeArgv(task_id=task, box=FakeRect(*ROW_BOX)))
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"run(do=click) 在假 Rect 上抛了 {type(exc).__name__}: {exc}")
        return msgs
    if ok is not True:
        msgs.append(f"run(do=click) 用假 Rect 时应成功，实际 {ok!r}")
    want_row_click = (int(ROW_BOX[0] + ROW_BOX[2] / 2.0), int(ROW_BOX[1] + ROW_BOX[3] / 2.0))
    if ctx2.clicked_centers() != [want_row_click]:
        msgs.append(f"run(do=click) 应落在 {want_row_click}，实际 {ctx2.clicked_centers()!r}")
    impl.reset_sessions()
    return msgs


# ---------------------------------------------------------------------------
# 挂点 2：浮点不丢
# ---------------------------------------------------------------------------
def _float_failures() -> list:
    """解包保留浮点：中心 == 手算值，半像素不许被截断。"""
    impl = _impl()
    fake = _fakes()
    msgs: list = []

    rect = FakeRect(12.5, 20.25, 3.0, 4.5)
    want = (14.0, 22.5)                     # 12.5 + 3.0/2 , 20.25 + 4.5/2
    try:
        got_rect = impl._box_center(rect)
        got_list = impl._box_center([12.5, 20.25, 3.0, 4.5])
        odd = impl._box_center(list(ROW_BOX))
    except Exception as exc:  # noqa: BLE001 - 解包自己抛 = 失败（不让守卫崩掉整套）
        msgs.append(f"_box_center 在这些框上抛了 {type(exc).__name__}: {exc}")
        return msgs
    if got_rect != want:
        msgs.append(f"Rect(12.5,20.25,3.0,4.5) 的中心应是 {want}，实际 {got_rect!r}")
    if got_list != want:
        msgs.append(f"list 形态（[12.5,20.25,3.0,4.5]）的中心应是 {want}，实际 {got_list!r}")

    # 奇数宽度：中心必须是 x.5（int() 截断会丢掉那半个像素）
    if odd != (300.5, 654.0):
        msgs.append(f"{ROW_BOX} 的中心应是 (300.5, 654.0)（不许 int() 截断），实际 {odd!r}")

    # 注入 hook：_tab_click 传出去的中心必须是浮点原值
    action = impl.LordsUnlockAction()
    task = 1211
    with ClickRecorder() as recorder:
        try:
            ok = action._tab_click(
                fake.FakeContext(),
                fake.FakeArgv(task_id=task, box=rect, act_param={"do": "tab"}),
                impl._session(task),
            )
        except Exception as exc:  # noqa: BLE001
            msgs.append(f"_tab_click（浮点 Rect）抛了 {type(exc).__name__}: {exc}")
            return msgs
        if ok is not True:
            msgs.append(f"_tab_click（浮点 Rect）应成功，实际 {ok!r}")
        if recorder.centers() != [want]:
            msgs.append(f"_tab_click 传出的应是浮点中心 {want}，实际 {recorder.centers()!r}（被截断了）")

    # ★取整只许发生在 _click_box★：真发出去的点击 = int(中心)，两者都得对
    ctx = fake.FakeContext()
    task = 1212
    try:
        action.run(ctx, fake.FakeArgv(task_id=task, box=rect, act_param={"do": "tab"}))
    except Exception as exc:  # noqa: BLE001
        msgs.append(f"run(do=tab)（浮点 Rect）抛了 {type(exc).__name__}: {exc}")
        return msgs
    if ctx.clicked_centers() != [(int(want[0]), int(want[1]))]:
        msgs.append(
            f"真正发出去的点击应只在 _click_box 里取整为 {(int(want[0]), int(want[1]))}，"
            f"实际 {ctx.clicked_centers()!r}"
        )
    impl.reset_sessions()
    return msgs


# ---------------------------------------------------------------------------
# 挂点 3：异常留痕
# ---------------------------------------------------------------------------
def _boom(context, cx, cy) -> bool:
    """注入的**必抛**点击 hook（模拟 #120 现场那种「动作里冒出一个 TypeError」）。"""
    raise RuntimeError("注入的必抛点击（#120 守卫）")


def _trace_failures(entry=None) -> list:
    """注入必抛 hook ⇒ run 如实返回 False 且日志里有 ``★动作异常★`` + 类型 + 消息 + 栈。"""
    impl = _impl()
    fake = _fakes()
    msgs: list = []
    mark = getattr(impl, "ACTION_ERROR_MARK", None)
    if mark != "★动作异常★":
        msgs.append(f"lords_impl.ACTION_ERROR_MARK 应是「★动作异常★」，实际 {mark!r}（logcat 里不好认）")
        mark = mark or "★动作异常★"

    action = impl.LordsUnlockAction()
    entry = entry if entry is not None else action.run
    impl.reset_sessions()                   # 每次都从干净会话开始（不吃上一条挂点的残留）
    out, err = io.StringIO(), io.StringIO()
    with _Patched(impl, "_click_hook", _boom), redirect_stdout(out), redirect_stderr(err):
        try:
            ok = entry(
                fake.FakeContext(),
                fake.FakeArgv(task_id=1221, box=FakeRect(*TAB_BOX), act_param={"do": "tab"}),
            )
        except Exception as exc:  # noqa: BLE001 - 漏出去 = ctypes 会把栈丢掉
            msgs.append(
                f"动作异常没有被兜住（直接抛 {type(exc).__name__}: {exc}）—— "
                f"ctypes 回调会把它静默丢掉，现场只剩「页签没确认」这种远因"
            )
            return msgs
    impl.reset_sessions()
    if ok is not False:
        msgs.append(f"动作异常时必须如实返回 False，实际 {ok!r}（假成功：流程看起来还在跑）")
    text = out.getvalue() + err.getvalue()
    if mark not in text:
        msgs.append(f"日志里没有醒目的 {mark} 那一行 —— 现场无法把它跟「识别失败」区分开；输出={text[-400:]!r}")
    if "RuntimeError" not in text:
        msgs.append(f"日志里没有异常类型（RuntimeError）；输出={text[-400:]!r}")
    if "注入的必抛点击" not in text:
        msgs.append(f"日志里没有异常消息；输出={text[-400:]!r}")
    if "Traceback (most recent call last)" not in text:
        msgs.append(f"日志里没有完整栈 —— 只有一行说明定位不了；输出={text[-400:]!r}")
    return msgs


# ---------------------------------------------------------------------------
# 挂点 4：静态（源码里不许再有 len(box) / box[...]）
# ---------------------------------------------------------------------------
def _no_len_failures(source=None) -> list:
    """AST 判：``agent/lords_impl.py`` 里不许 ``len(<…box…>)``，也不许对裸 ``box`` 取下标。

    用 AST 而不是字符串搜索：文档里写「不许用 ``len(box)``」是**说明**，不是违规。
    """
    text = IMPL_PATH.read_text(encoding="utf-8") if source is None else source
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"agent/lords_impl.py 无法解析（{exc}）—— 静态守卫失效"]
    msgs: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
            for arg in node.args:
                rendered = ast.unparse(arg)
                if "box" in rendered:
                    msgs.append(
                        f"第 {node.lineno} 行 len({rendered}) —— maa v5 的 Rect 没有 __len__"
                        f"（{RECT_TYPE_ERROR}）；一律走 _box_xywh / _box4_int / _box_center"
                    )
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "box":
            msgs.append(
                f"第 {node.lineno} 行 box[...] 下标取值 —— 框架给的是 Rect，一律先用 "
                f"_box_xywh 解包（保留浮点）"
            )
    return msgs


# ---------------------------------------------------------------------------
# 四个挂点
# ---------------------------------------------------------------------------
def probe_lords_rect_box_unpack() -> bool:
    """假 Rect 走 ``_tab_click`` / ``run``：中心算对，且真的点下去（真机那条路）。"""
    msgs = _tab_rect_failures()
    if msgs:
        print(f"  [120] {HOOK_ID_RECT} 不成立：")
        for msg in msgs:
            print(f"    - {msg}")
        return False
    print(f"  [120] {HOOK_ID_RECT} 成立：假 Rect（无 __len__）也能点中 (539.5, 405.5) 与 (300.5, 654.0)")
    return True


def probe_lords_rect_float_center() -> bool:
    """解包保留浮点：中心 == 手算值；取整只在 ``_click_box`` 那一下。"""
    msgs = _float_failures()
    if msgs:
        print(f"  [120] {HOOK_ID_FLOAT} 不成立：")
        for msg in msgs:
            print(f"    - {msg}")
        return False
    print(f"  [120] {HOOK_ID_FLOAT} 成立：Rect(12.5,20.25,3.0,4.5) 中心 (14.0, 22.5)；奇数宽度中心 300.5 未被截断")
    return True


def probe_lords_action_error_trace() -> bool:
    """动作异常必须留痕：返回 False + 一行 ``★动作异常★`` + 类型 + 消息 + 栈。"""
    msgs = _trace_failures()
    if msgs:
        print(f"  [120] {HOOK_ID_TRACE} 不成立：")
        for msg in msgs:
            print(f"    - {msg}")
        return False
    print(f"  [120] {HOOK_ID_TRACE} 成立：注入必抛 hook ⇒ run 返回 False，日志有「★动作异常★ RuntimeError」+ 栈")
    return True


def probe_lords_rect_no_len() -> bool:
    """静态：源里没有 ``len(<…box…>)`` / 裸 ``box[...]``。"""
    msgs = _no_len_failures()
    if msgs:
        print(f"  [120] {HOOK_ID_NOLEN} 不成立：")
        for msg in msgs:
            print(f"    - {msg}")
        return False
    print(f"  [120] {HOOK_ID_NOLEN} 成立：agent/lords_impl.py 里没有 len(box) / box[...]（AST 判）")
    return True


HOOKS = [
    (
        HOOK_ID_RECT,
        _TICKET,
        "★假 Rect★（只有 .x/.y/.w/.h，无 __len__）：_tab_click / run 必须算出正确中心并真的点下去"
        "（注入 _click_hook 看实参 + 真 PubClick 落点），不许 len(box) —— #120 真机 TypeError",
        probe_lords_rect_box_unpack,
    ),
    (
        HOOK_ID_FLOAT,
        _TICKET,
        "★浮点不丢★：Rect(12.5,20.25,3.0,4.5) 解包后中心 == 手算 (14.0,22.5)；奇数宽度中心 300.5 "
        "不许被 int() 截断 —— 取整只许发生在 _click_box（真正发点击那一下）",
        probe_lords_rect_float_center,
    ),
    (
        HOOK_ID_TRACE,
        _TICKET,
        "★动作异常不许被吞★：注入必抛 hook ⇒ run 如实返回 False，且日志有一行「★动作异常★」"
        "+ 异常类型 + 消息 + 完整栈（ctypes 回调会把异常静默丢掉，症状离病因极远）",
        probe_lords_action_error_trace,
    ),
    (
        HOOK_ID_NOLEN,
        _TICKET,
        "静态：agent/lords_impl.py 不许再出现 len(<…box…>) 或裸 box[...]"
        "（AST 判，注释/文档串里写 len(box) 是说明不算违规）",
        probe_lords_rect_no_len,
    ),
]


# ---------------------------------------------------------------------------
# 本模块自己的破坏实验
# ---------------------------------------------------------------------------
def _record(name: str, msgs: list, checks: list) -> None:
    """记一条破坏实验：``msgs`` 非空 = 守卫成功变红。"""
    red = bool(msgs)
    checks.append((name, red, msgs[0] if msgs else ""))
    print(f"  [{'PASS' if red else 'FAIL'}] {name} -> {'红' if red else '仍绿'}" + (f"  {msgs[0]}" if msgs else ""))


def _prove_red_checks() -> list:
    """三条行为破坏 + 一条静态破坏（每次都在内存里做，退出必定还原实现）。"""
    impl = _impl()
    checks: list = []

    # ① 把 len(box) 改回来（#120 的原始形状）
    def _broken_len_unpack(box):
        if box is None or len(box) != 4:      # ← 真机就是这一行抛的（Rect 没有 __len__）
            return None
        return (box[0], box[1], box[2], box[3])

    with _Patched(impl, "_box_xywh", _broken_len_unpack):
        _record("① 解包退回 len(box)（#120 原始形状）", _tab_rect_failures(), checks)

    # ② 解包里加 int() 截断（浮点中心被压扁）
    def _broken_int_unpack(box):
        if box is None:
            return None
        if getattr(box, "x", None) is not None:
            values = (box.x, box.y, box.w, box.h)
        else:
            values = tuple(box)
        if len(values) != 4:
            return None
        return (int(values[0]), int(values[1]), int(values[2]), int(values[3]))

    with _Patched(impl, "_box_xywh", _broken_int_unpack):
        _record("② 解包里加 int() 截断（中心丢半像素）", _float_failures(), checks)

    # ③ 去掉 ★动作异常★ 留痕：只吞不喊
    def _silent_run(self, context, argv):
        try:
            return self._dispatch(context, argv)
        except Exception:  # noqa: BLE001 - 坏实现：吞掉了，谁也不知道
            return False

    with _Patched(impl.LordsUnlockAction, "run", _silent_run):
        _record("③a 异常只吞不喊（没有 ★动作异常★ 那一行）", _trace_failures(), checks)

    # ③b 连兜都不兜（异常直接漏进 ctypes 回调 = 真机现场）
    action = impl.LordsUnlockAction()
    _record("③b 连 try/except 都摘掉（异常漏进 ctypes）", _trace_failures(entry=action._dispatch), checks)

    # ④ 静态：源码副本里重新出现 len(box)
    source = IMPL_PATH.read_text(encoding="utf-8")
    broken_source = source + (
        "\n\ndef _regression_len_box(box):\n"
        "    return box is None or len(box) != 4\n"
    )
    _record("④ 源码里重新出现 len(box)（静态挂点）", _no_len_failures(source=broken_source), checks)
    return checks


def prove_red() -> bool:
    """真实绿；四条破坏实验各自如愿变红。"""
    print("hooks_120 prove-red：逐一破坏实现，要求四个挂点各自变红")
    green = (
        probe_lords_rect_box_unpack()
        and probe_lords_rect_float_center()
        and probe_lords_action_error_trace()
        and probe_lords_rect_no_len()
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：Rect 兼容 / 浮点中心 / 异常留痕 / 无 len(box)（绿）")
    if not green:
        for msg in (
            _fake_rect_is_faithful()
            + _tab_rect_failures()
            + _float_failures()
            + _trace_failures()
            + _no_len_failures()
        ):
            print(f"      - {msg}")
        return False

    checks = _prove_red_checks()
    ok = green and all(red for _name, red, _first in checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
