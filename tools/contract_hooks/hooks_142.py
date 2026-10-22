# -*- coding: utf-8 -*-
"""#142：全仓唯一的「用户可见输出 / 机制日志 / 进度行」出口（``agent/reporting.py``）。

## 为什么有这张票

#86 只把**五重**的输出分成两路（``_say`` 进面板 / ``_log`` 进文件）；深渊连战、深渊连战EX、
幻想连战、领主战、外传的机制日志与进度混在同一个 stdout 里 → MFAAvalonia 面板被点击/校验/
心跳刷满，用户看不到「打到哪了」。

本票的答案是**一个模块**（:mod:`reporting`）：``say`` / ``log`` / ``Progress``。
quiet 靠**一次** ``sys.stdout`` 重定向实现，所以场景里几百个既有 ``print(...)`` 全部自动
归入机制日志 —— 不需要逐行改，也就没有「第 87 个 print 忘了改」这种漏点。

## 契约（守卫口径）

- **H1 一个出口**（``progress-quiet-single-seam``）：quiet 打开后，场景里的既有 ``print``
  必须落盘且**不进面板**；``say`` 必须进面板且**不落盘**（面板与文件各一份，不重复）。
- **H2 面板不丢**（``progress-say-never-swallowed``）：``say`` 走真实 stdout，与 quiet 无关。
  静音把面板也吞掉 = 用户彻底看不见进度（本仓最不该出现的失败形态）。
- **H3 格式唯一**（``progress-format-single-source``）：``Progress.step`` 的文本必须
  == ``format_progress(...)`` 的返回 == 固定字面量；场景里**不许**自己拼 ``[进度]``。
- **H4 单调去重**（``progress-step-dedupe``）：同一步重复报只出一条、倒退不出线、收工后静默。
- **H5 失败开放**（``progress-log-fail-open``）：日志打不开 → **不静音**（宁可吵不许丢日志）、
  不抛异常，并且面板里要说明原因。

## prove-red（破坏实验 5 条，全部在内存里）

1. 把 ``format_progress`` 换成旧格式 → **H3 红**；
2. 让 ``set_quiet`` 只置标志不重定向 → **H1 红**（机制 print 漏进面板）；
3. 让 ``say`` 写 ``sys.stdout``（被 sink 吞）→ **H2 红**；
4. 去掉 ``Progress.step`` 的去重/单调 → **H4 红**；
5. 让 ``_open_log`` 抛异常 / 失败也静音 → **H5 红**。

跑法::

    .venv\\Scripts\\python.exe tools\\contract_hooks\\hooks_142.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
for _path in (str(TOOLS_DIR), str(AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import reporting  # noqa: E402

HOOK_ID_SEAM = "progress-quiet-single-seam"
HOOK_ID_SAY = "progress-say-never-swallowed"
HOOK_ID_FORMAT = "progress-format-single-source"
HOOK_ID_DEDUPE = "progress-step-dedupe"
HOOK_ID_FAIL_OPEN = "progress-log-fail-open"

#: H3 的固定字面量（**故意写死**：场景/测试都不许自己拼，这里就是那份字面量）。
EXPECTED_LINE = "[进度] 深渊连战EX 2/30 战"


def _mod(mod):
    return mod if mod is not None else reporting


@contextlib.contextmanager
def _panel(mod):
    """把「面板」换成可读缓冲（生产里它就是进程真实 stdout）。"""
    old = mod._REAL_STDOUT
    buf = io.StringIO()
    mod._REAL_STDOUT = buf
    try:
        yield buf
    finally:
        mod._REAL_STDOUT = old


@contextlib.contextmanager
def _quiet(mod, path=None):
    """打开 quiet，离开时**必定**关掉（否则后续 probe 看到的是静音态）。"""
    mod.set_quiet(True, path) if path is not None else mod.set_quiet(True)
    try:
        yield
    finally:
        mod.set_quiet(False)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _scratch(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix="hooks_142_")) / name


# ---------------------------------------------------------------------------
# 判据（每条 = 一个探针，返回 True 才算过）
# ---------------------------------------------------------------------------
def probe_quiet_seam(mod=None) -> bool:
    """H1：quiet 之后既有 print 落盘、不进面板；say 进面板、不落盘。"""
    m = _mod(mod)
    log = _scratch("agent.log")
    with _panel(m) as buf:
        with _quiet(m, log):
            print("[abyss] 点击 (360,600)")
            m.say("[进度] 深渊连战EX 12/30 战")
        body, panel = _read(log), buf.getvalue()
    return (
        "[abyss] 点击 (360,600)" in body
        and "[abyss]" not in panel
        and "[进度] 深渊连战EX 12/30 战" in panel
        and "[进度] 深渊连战EX 12/30 战" not in body
    )


def probe_say_visible(mod=None) -> bool:
    """H2：``say`` 与 quiet 无关，永远进面板。"""
    m = _mod(mod)
    with _panel(m) as buf:
        m.say("before-quiet")
        with _quiet(m, _scratch("agent.log")):
            m.say("inside-quiet")
        m.say("after-quiet")
    text = buf.getvalue()
    return all(k in text for k in ("before-quiet", "inside-quiet", "after-quiet"))


def probe_format_single_source(mod=None) -> bool:
    """H3：Progress.step 的文本 == format_progress(...) == 固定字面量。"""
    m = _mod(mod)
    with _panel(m):
        p = m.Progress("深渊连战EX", total=30, unit="战")
        got = p.step(2)
    pure = m.format_progress("深渊连战EX", 2, 30, "战")
    return got == pure == EXPECTED_LINE


def probe_step_dedupe(mod=None) -> bool:
    """H4：重复不出线、倒退不出线、收工后静默。"""
    m = _mod(mod)
    with _panel(m):
        p = m.Progress("幻想连战", total=15, unit="关")
        p.step(1)
        p.step(2)
        p.step(2)
        p.step(1)
        p.step(3)
        p.done("打够 3 关")
        p.step(4)
    return [line for line in p.lines] == [
        "[进度] 幻想连战 1/15 关",
        "[进度] 幻想连战 2/15 关",
        "[进度] 幻想连战 3/15 关",
        "[进度] 幻想连战 收工：打够 3 关",
    ]


def probe_log_fail_open(mod=None) -> bool:
    """H5：日志打不开 → 不静音、不抛异常、面板说明原因。"""
    m = _mod(mod)
    blocker = _scratch("blocker")
    blocker.write_text("x", encoding="utf-8")      # 父路径是**文件** → 建目录必失败
    with _panel(m) as buf:
        try:
            ok = m.set_quiet(True, blocker / "agent.log")
            raised = False
        except Exception:  # noqa: BLE001
            ok, raised = None, True
        quiet_after = m.is_quiet()
        m.set_quiet(False)
    panel = buf.getvalue()
    return raised is False and ok is False and quiet_after is False and "[reporting]" in panel


#: 探针清单（H1..H5）。**prove_red 只读这一份**，所以 hooks_115 打瞎探针后必红。
PROBES = (
    (HOOK_ID_SEAM, probe_quiet_seam),
    (HOOK_ID_SAY, probe_say_visible),
    (HOOK_ID_FORMAT, probe_format_single_source),
    (HOOK_ID_DEDUPE, probe_step_dedupe),
    (HOOK_ID_FAIL_OPEN, probe_log_fail_open),
)


def probe_all_failures(mod=None) -> list[str]:
    """真实实现上跑全部探针（``main`` 用；名字带 failure，不会被当成判据打瞎）。"""
    return [hook_id for hook_id, fn in PROBES if not fn(mod)]


#: ★聚合器契约★：``tools/contract_hooks/__init__.py`` 要求每个 ``hooks_<票号>.py`` 导出
#: ``HOOKS``（``(hook_id, ticket, 说明, probe)``）；缺了它 ``discover_hooks()`` 会抛异常，
#: **别的票的守卫会连带变红**（本票第一次跑套件就是这么踩的）。
HOOKS = [
    (HOOK_ID_SEAM, "#142", "quiet 是一次 stdout 重定向：既有 print 落盘、不进面板", probe_quiet_seam),
    (HOOK_ID_SAY, "#142", "say 永远进面板（静音吞不掉）", probe_say_visible),
    (HOOK_ID_FORMAT, "#142", "进度行只有一个格式实现（Progress.step == format_progress）", probe_format_single_source),
    (HOOK_ID_DEDUPE, "#142", "Progress 单调去重、收工后静默", probe_step_dedupe),
    (HOOK_ID_FAIL_OPEN, "#142", "日志打不开不静音、不抛异常、面板说明原因", probe_log_fail_open),
]


# ---------------------------------------------------------------------------
# prove-red：把实现换坏，探针必须变红
# ---------------------------------------------------------------------------
def _leg(name: str, broken, probe, failures: list[str]) -> bool:
    """把 ``broken`` 装进实现后跑 ``probe``；返回「探针确实变红」= 破坏实验成立。"""
    ok = not probe()             # 探针应报红（返回 False）
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {'红（守卫有灵敏度）' if ok else '仍绿（守卫是假的）'}")
    if not ok:
        failures.append(name)
    return ok


def prove_red() -> bool:
    """五条破坏实验（全部在内存里改属性，跑完还原）。"""
    failures: list[str] = []

    module = reporting
    real_format = module.format_progress
    real_step = module.Progress.step
    real_say = module.say
    real_set_quiet = module.set_quiet
    real_open_log = module._open_log
    real_stdout_obj = sys.stdout

    print("破坏实验：" + str(len(PROBES)) + " 条")
    try:
        # ① 旧格式（第二份格式）→ H3 红
        module.format_progress = lambda display, index=0, total=0, unit="", note="": (
            f"进度: {display} {index}/{total}（旧格式）"
        )
        _leg("格式换成旧写法", None, probe_format_single_source, failures)
        module.format_progress = real_format

        # ② quiet 只置标志、不重定向 → H1 红（机制 print 漏进面板）
        def _quiet_flag_only(on=True, path=None):  # noqa: ANN001
            module._QUIET = bool(on)
            return True

        module.set_quiet = _quiet_flag_only
        _leg("set_quiet 不重定向", None, probe_quiet_seam, failures)
        module.set_quiet = real_set_quiet

        # ③ say 写 sys.stdout（会被 sink 吞）→ H2 红
        module.say = lambda text="": print(text, flush=True)
        _leg("say 写 sys.stdout（静音即吞）", None, probe_say_visible, failures)
        module.say = real_say

        # ④ step 不去重不单调 → H4 红
        def _step_no_dedupe(self, index=None, note=None):  # noqa: ANN001
            n = self._last + 1 if index is None else int(index)
            self._last = n
            return module.format_progress(self.display, n, self.total, self.unit, self.note if note is None else note)

        module.Progress.step = _step_no_dedupe
        _leg("去掉 step 去重/单调", None, probe_step_dedupe, failures)
        module.Progress.step = real_step

        # ⑤ 日志打不开也静音（且抛异常）→ H5 红
        def _open_log_raises(path):  # noqa: ANN001
            raise OSError("注入的坏日志路径")

        module._open_log = _open_log_raises

        def _quiet_regardless(on=True, path=None):  # noqa: ANN001
            """坏件：打不开也照样静音（把失败伪装成成功），且 off 时能还原 stdout。"""
            module._QUIET = bool(on)
            if on:
                module._SAVED_STDOUT = sys.stdout
                sys.stdout = io.StringIO()
            elif module._SAVED_STDOUT is not None:
                sys.stdout = module._SAVED_STDOUT
                module._SAVED_STDOUT = None
            return bool(on)

        module.set_quiet = _quiet_regardless
        _leg("日志打不开仍然静音", None, probe_log_fail_open, failures)
        module.set_quiet = real_set_quiet
    finally:
        module.format_progress = real_format
        module.Progress.step = real_step
        module.say = real_say
        module.set_quiet = real_set_quiet
        module._open_log = real_open_log
        try:
            module.set_quiet(False)
        except Exception:  # noqa: BLE001
            pass
        sys.stdout = real_stdout_obj

    ok = not failures
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★ " + ", ".join(failures)))
    return ok


def main() -> int:
    print("真实实现（agent/reporting.py）：")
    bad = probe_all_failures()
    for hook_id, _fn in PROBES:
        mark = "PASS" if hook_id not in bad else "FAIL"
        print(f"  [{mark}] {hook_id}")
    if bad:
        print("结果：★守卫失败★ " + ", ".join(bad))
        return 1
    return 0 if prove_red() else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
