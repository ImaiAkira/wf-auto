# -*- coding: utf-8 -*-
"""#5：异常组【一处定义】+ 幂等注入的挂点（已点亮）。

seam：``scene.events``（ADR-0001 的「幂等注入」职责）。

守卫 ``inject-idempotent`` 断言：

* 九类跨场景异常在**一处**定义（数量与命名都对）；
* 对同一份 JSON 连续注入两次，序列化后**字节完全一致**；
* 事件排在原有后继**之前**，且剥壳能还原链的形状（注入只加壳、不改形状）；
* 卡死兜底**不在**事件层里（是独立看门狗）。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：把 ``scene/events.py``
复制一份、改掉「幂等」那一行，**真实探针必须变红**。直接运行::

    python tools\\contract_hooks\\hooks_5.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent

# 本票枚举的九类跨场景情况（用于核对「一处定义」的命名集合）。
_EXPECTED_NINE = ("加载", "结算", "换日", "等级", "新角色", "剧情", "挑战", "加成弹窗", "招募")

# 破坏点：把「先摘掉已有事件引用」换成「原样保留」→ 第二次注入会重复插入 → 非幂等。
_BREAK_OLD = "        body = [x for x in nxt if x not in ref_set]"
_BREAK_NEW = "        body = list(nxt)"

# 探针链末位放一个 DirectHit「恢复边/终点」（与真实 pipeline 的 SpecialEntry/SpecialWait
# 同型）——兜底型事件正是插在它【之前】。没有它，探针会把兜底误插到唯一后继之前。
_HUB = "ProbeHub"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（--prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def _bytes(x: object) -> bytes:
    return json.dumps(x, ensure_ascii=False, sort_keys=True).encode("utf-8")


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


def probe_inject_idempotent():
    """#5：异常组一处定义 + 幂等注入 + 打断型在候选集前 + 看门狗不在事件层。"""
    scene_on_path()
    import scene.events as ev  # noqa: PLC0415

    # (1) 九类情况在【一处】定义：数量与命名都对。
    if len(ev.EXCEPTION_EVENTS) != 9:
        return False
    if sorted(ev.exception_event_names()) != sorted(_EXPECTED_NINE):
        return False

    # (2) 链的形状里看不到事件（探针链是干净的）。
    pages = list(ev.known_pages())
    chain = _probe_chain(pages)
    if not ev.is_event_free(chain):
        return False

    # (3) 注入幂等：连续两次字节完全一致；且引用非空（不是空转的假绿）。
    prefix = list(ev.interrupt_refs())
    suffix = list(ev.fallback_refs())
    refs = ev.event_refs()
    if not refs or not prefix or not suffix:
        return False
    once = ev.inject_events(chain, flow_nodes=pages)
    twice = ev.inject_events(once, flow_nodes=pages)
    if _bytes(once) != _bytes(twice):
        return False

    # (4) 位置两类相反（#18）：打断型前缀在【原有后继之前】；兜底型后缀在原有后继之后、
    #     但在节点最后那条 DirectHit 终点【之前】。原后继仍在（形状不变）。
    for p in pages:
        body = chain[p]["next"]
        expected = [*prefix, *body[:-1], *suffix, *body[-1:]]
        if once[p]["next"] != expected:
            return False

    # (5) 剥壳回到链的形状 —— 注入只是加壳。
    if ev.strip_events(once) != chain:
        return False

    # (6) 卡死兜底不在事件层里（是独立看门狗）。
    if ev.watchdog_in_event_layer():
        return False

    return True


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_5.py`）
# ---------------------------------------------------------------------------
def _probe_in(root: Path):
    """子进程里、以 ``root`` 作为 ``scene`` 包来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import discover_hooks\n"
        "probe = next(p for hid, _t, _w, p in discover_hooks() if hid == 'inject-idempotent')\n"
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
    """复制 scene 包 → 改坏幂等那行 → 真实绿 / 坏副本红，二者缺一即失败。"""
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    scene_on_path()

    print("hooks_5 prove-red：故意让注入非幂等，要求 inject-idempotent 变红")
    green = probe_inject_idempotent() is True

    tmp = Path(tempfile.mkdtemp(prefix="wf_hook5_"))
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
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：注入幂等（绿）")
    print(f"  [{'PASS' if red else 'FAIL'}] 破坏后：注入非幂等被守卫抓到（红 = 可用信号）")
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return 0 if ok else 1


HOOKS = [
    ("inject-idempotent", "#5", "异常组注入幂等：重跑不改字节", probe_inject_idempotent),
]


if __name__ == "__main__":
    raise SystemExit(prove_red())
