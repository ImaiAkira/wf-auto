# -*- coding: utf-8 -*-
"""离线单测：``agent/reporting.py``（用户可见输出 / 机制日志 / 进度行唯一出口）。

不需要游戏、不需要 maa 运行环境：

    python tools/test_reporting.py

覆盖四件事：
  ① 进度行格式只有一份（``format_progress``），三种形状 + note；
  ② ``Progress`` 单调去重、收工后不再出线；
  ③ quiet 是**一次** stdout 重定向：既有 ``print`` 进文件，``say`` 仍进面板；
  ④ 失败语义：日志打不开时不静音、不抛异常。
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

# #14-offline-utf8: force this file's own stdout to UTF-8 (no external PYTHONIOENCODING).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

import reporting  # noqa: E402


def _scratch() -> Path:
    """临时目录（与全仓其它离线测试同口径：``tempfile.mkdtemp``，跑完不回收也无所谓）。"""
    return Path(tempfile.mkdtemp(prefix="wf_reporting_"))

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


class _Capture:
    """把 ``reporting._REAL_STDOUT``（= 面板）换成可读缓冲，离开时还原。"""

    def __enter__(self):
        self._old = reporting._REAL_STDOUT
        self.buf = io.StringIO()
        reporting._REAL_STDOUT = self.buf
        return self

    def __exit__(self, *exc):
        reporting._REAL_STDOUT = self._old
        reporting.set_quiet(False)
        return False

    @property
    def text(self) -> str:
        return self.buf.getvalue()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
print("\n== 1. format_progress：进度行唯一真源 ==")
# ---------------------------------------------------------------------------
check(
    "有总量 → i/N + 单位",
    reporting.format_progress("深渊连战EX", 12, 30, "战") == "[进度] 深渊连战EX 12/30 战",
    reporting.format_progress("深渊连战EX", 12, 30, "战"),
)
check(
    "无总量 → 已 i",
    reporting.format_progress("领主战", 3, 0, "个目标") == "[进度] 领主战 已 3 个目标",
    reporting.format_progress("领主战", 3, 0, "个目标"),
)
check(
    "note → 括号后缀",
    reporting.format_progress("幻想连战", 4, 15, "关", "第 1/2 套")
    == "[进度] 幻想连战 4/15 关（第 1/2 套）",
    reporting.format_progress("幻想连战", 4, 15, "关", "第 1/2 套"),
)
check(
    "空 display 有兜底（不许出 '[进度]  1/3'）",
    reporting.format_progress("", 1, 3) == "[进度] 任务 1/3",
    reporting.format_progress("", 1, 3),
)
check(
    "负值 / 非数字不抛异常（日志坏不许影响跑图）",
    reporting.format_progress("X", -3, -1, "", None) == "[进度] X 已 0",
    reporting.format_progress("X", -3, -1, "", None),
)

# ---------------------------------------------------------------------------
print("\n== 2. Progress：单调、去重、收工后静默 ==")
# ---------------------------------------------------------------------------
with _Capture() as cap:
    p = reporting.Progress("深渊连战EX", total=30, unit="战")
    p.start()
    p.step(1)
    p.step(2)
    p.step(2)          # 重复：不出线
    p.step(1)          # 倒退：不出线
    p.step(3, note="第 2 圈")
    p.done("30 层全清")
    p.step(4)          # 收工后：不出线
    p.done("再来一次")   # 收工只说一次
    lines = p.lines
check("共 4 条（start + 1 + 2 + 3 + done），重复/倒退/收工后都不出线", len(lines) == 5, str(lines))
check("start 带总量", lines[0] == "[进度] 深渊连战EX 开始（共 30 战）", lines[0])
check("step 1 形状", lines[1] == "[进度] 深渊连战EX 1/30 战", lines[1])
check("step(3) 用本次 note 覆盖", lines[3] == "[进度] 深渊连战EX 3/30 战（第 2 圈）", lines[3])
check("done 带原因", lines[4] == "[进度] 深渊连战EX 收工：30 层全清", lines[4])
check("count 停在 3", p.count == 3, str(p.count))
check("全部出线都进了面板", all(l in cap.text for l in lines), cap.text[:120])

with _Capture() as cap2:
    q = reporting.Progress("五重决战", total=0, unit="次", note="打几次=2")
    q.step(1)
    q.step(2)
    q.done("已打够 2 次")
check(
    "无总量也带单位与固定 note",
    q.lines == ["[进度] 五重决战 已 1 次（打几次=2）", "[进度] 五重决战 已 2 次（打几次=2）",
                "[进度] 五重决战 收工：已打够 2 次"],
    str(q.lines),
)
check("start 可后置总量（选项先到/后到都行）",
      reporting.Progress("X", unit="次").start(total=3) == "[进度] X 开始（共 3 次）")

# ---------------------------------------------------------------------------
print("\n== 3. quiet：既有 print 进文件，say 仍进面板 ==")
# ---------------------------------------------------------------------------
tmp = _scratch() / "agent.log"
old_stdout = sys.stdout
with _Capture() as cap3:
    ok = reporting.set_quiet(True, tmp)
    during = sys.stdout
    quiet_during = reporting.is_quiet()
    print("[abyss] 点击 (360,600)")          # 场景里的既有机制输出，不改成 log()
    reporting.log("[abyss] 账本恢复：第 12 战")
    reporting.say("[进度] 深渊连战EX 12/30 战")
    body = _read(tmp)
    panel = cap3.text
check("set_quiet 生效", ok and quiet_during, f"ok={ok} quiet={quiet_during}")
check("sys.stdout 被换成 sink", during is not old_stdout, type(during).__name__)
check("机制 print 落盘", "[abyss] 点击 (360,600)" in body, body[:120])
check("log 落盘", "[abyss] 账本恢复：第 12 战" in body, body[:160])
check("★机制输出没漏进面板★", "[abyss]" not in panel, panel[:120])
check("★say 进面板★", "[进度] 深渊连战EX 12/30 战" in panel, panel[:120])
check("quiet 下 say 不重复落盘（面板与文件各一份）",
      body.count("[进度] 深渊连战EX 12/30 战") == 0, body[:160])
reporting.set_quiet(False)
check("set_quiet(False) 还原 stdout", sys.stdout is old_stdout, type(sys.stdout).__name__)
check("set_quiet(False) 后 is_quiet=False", not reporting.is_quiet())

# ---------------------------------------------------------------------------
print("\n== 4. 失败语义：日志打不开不静音、不抛异常 ==")
# ---------------------------------------------------------------------------
bad = _scratch() / "no-such-dir" 
bad.write_text("x", encoding="utf-8")          # 父路径是个**文件** → 建目录必失败
bad_child = bad / "agent.log"
with _Capture() as cap4:
    try:
        ok_bad = reporting.set_quiet(True, bad_child)
        raised = ""
    except Exception as exc:  # noqa: BLE001
        ok_bad, raised = None, repr(exc)
    try:
        reporting.log("[abyss] 机制照旧")      # 不静音时必须还能出线（不抛异常）
        log_raised = ""
    except Exception as exc:  # noqa: BLE001
        log_raised = repr(exc)
    panel4 = cap4.text
check("不抛异常", raised == "" and log_raised == "", f"{raised} {log_raised}")
check("打不开就不静音（宁可吵，不许丢日志）", ok_bad is False and not reporting.is_quiet(), f"ok={ok_bad}")
check("★面板里说明原因（say 通道没被吞）★", "[reporting] 日志打不开" in panel4, panel4[:200])

# ---------------------------------------------------------------------------
print("")
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL GREEN")
