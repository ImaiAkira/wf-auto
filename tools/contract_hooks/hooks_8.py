# -*- coding: utf-8 -*-
"""#8：归位提升为【通用事件】的挂点（已点亮）。

seam：``scene.events``（与 #5 同一个事件层）。

守卫 ``return-home-generic`` 断言：

* 归位是事件层里的一个通用事件，**出现在注入的异常组里**（``event_refs()`` 含它）；
* 归位可从**任意已知页面**在**一步之内**触发（注入后每个页面锚定节点的候选集里都有它）；
* 链尾**不再各自实现**回主城：链的形状里没有归位节点（它只由注入带来）。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：把 ``scene/events.py``
复制一份、把归位从注入组里拿掉，**真实探针必须变红**。直接运行::

    python tools\\contract_hooks\\hooks_8.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# 破坏点：把归位从兜底型注入组里拿掉 → 归位不再被注入 → 守卫必须变红。
_BREAK_OLD = "FALLBACK_EVENTS: tuple[Event, ...] = (RETURN_HOME,)"
_BREAK_NEW = "FALLBACK_EVENTS: tuple[Event, ...] = ()"

# 探针链末位放一个 DirectHit「恢复边/终点」（与真实 pipeline 同型）；兜底型归位插在它之前。
_HUB = "ProbeHub"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（--prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _probe_chain(pages: list[str]) -> dict:
    """链的【形状】探针：每个节点锚在一个页面上，``next`` = 显式后继 + DirectHit 终点。"""
    n = len(pages)
    chain = {
        p: {
            "recognition": {"type": "OCR", "param": {"expected": [p]}},
            "next": ([pages[i + 1], _HUB] if i + 1 < n else [_HUB]),
        }
        for i, p in enumerate(pages)
    }
    chain[_HUB] = {
        "recognition": {"type": "DirectHit", "param": {}},
        "action": {"type": "DoNothing", "param": {}},
        "next": [],
    }
    return chain


def probe_return_home_generic():
    """#8：归位是通用事件、可从任意已知页面一步触发、不是链尾职责。"""
    scene_on_path()
    import scene.events as ev  # noqa: PLC0415

    home = ev.return_home_ref()

    # (1) 归位在注入的异常组里（默认 EVENTS = 九类异常 + 归位）。
    if home not in ev.event_refs():
        return False
    if ev.RETURN_HOME.name not in [e.name for e in ev.EVENTS]:
        return False

    # (2) 归位可从【任意已知页面】一步之内触发。
    pages = list(ev.known_pages())
    if not pages:
        return False
    chain = _probe_chain(pages)
    injected = ev.inject_events(chain, flow_nodes=pages)
    for p in pages:
        if home not in injected[p]["next"]:
            return False

    # (3) 链尾不再各自实现回主城：链的形状里看不到归位。
    if not ev.is_event_free(chain):
        return False
    if ev.RETURN_HOME_NODE_NAME in chain:
        return False

    # (4) 归位是单步事件（一个节点，叶子型）。
    if len(ev.RETURN_HOME.nodes) != 1:
        return False

    return True


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_8.py`）
# ---------------------------------------------------------------------------
def _probe_in(root: Path):
    """子进程里、以 ``root`` 作为 ``scene`` 包来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import discover_hooks\n"
        "probe = next(p for hid, _t, _w, p in discover_hooks() if hid == 'return-home-generic')\n"
        "print('PROBE_RESULT', repr(probe()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral_"))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            cwd=str(neutral),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "PROBE_RESULT True" in out:
        return True
    if "PROBE_RESULT False" in out:
        return False
    return None


def prove_red() -> int:
    """复制 scene 包 → 把归位从注入组拿掉 → 真实绿 / 坏副本红，二者缺一即失败。"""
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    scene_on_path()

    print("hooks_8 prove-red：故意把归位从注入组拿掉，要求 return-home-generic 变红")
    green = probe_return_home_generic() is True

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook8_"))
    try:
        shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
        src = tmp / "scene" / "events.py"
        text = src.read_text(encoding="utf-8")
        if _BREAK_OLD not in text:
            print(f"  [FAIL] 破坏点没找到：{_BREAK_OLD!r}（守卫已与实现脱节）")
            return 1
        src.write_text(text.replace(_BREAK_OLD, _BREAK_NEW, 1), encoding="utf-8")
        red = _probe_in(tmp) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = green and red
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：归位是注入的通用事件（绿）")
    print(f"  [{'PASS' if red else 'FAIL'}] 破坏后：归位不在注入组里被守卫抓到（红 = 可用信号）")
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return 0 if ok else 1


HOOKS = [
    ("return-home-generic", "#8", "归位是通用事件，不作为每个场景链的链尾职责", probe_return_home_generic),
]


if __name__ == "__main__":
    raise SystemExit(prove_red())
