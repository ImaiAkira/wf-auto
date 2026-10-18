# -*- coding: utf-8 -*-
"""#7：配置 ↔ pipeline JSON 漂移可红的挂点（已点亮）。

seam：``scene.drift``（ADR-0001 的「校验」职责）。

守卫 ``config-json-drift`` 断言：配置层**期望**的产物与磁盘上**真实**的产物一致 ——
任一方向漂移都返回 False（套件红），且报告点名声明的成员 / 规则。

今天真实可比的两项（详见 ``scene/drift.py`` 的 docstring）：

1. GUI 目标选项（39 个名字 + 每个成员的 pipeline_override）↔ ``assets/interface.json``
   手写的 option「打哪个副本」；
2. 页面判据（``scene/page_rules.py``）↔ 它们抄自的 pipeline 节点
   （``SpecialOpenLord`` / ``SpecialTabLord`` / ``SpecialTabJoss`` / ``SpecialScrollList`` /
   ``SpecialChallenge`` / ``SpecialDetailGate`` / ``SpecialModeSolo`` / ``SpecialBonusNo`` /
   ``SpecialBattleWait`` 及其引用的战斗 HUD 公共叶子）+ 目标行 ROI ↔ ``SpecialEnterBoss``。

链的形状（#4）与注入的异常组（#5/#8）今天还没写进 pipeline，**不校验**；由迁移票
#9 / #10 / #11 落地后才能验（见 ``scene/drift.py`` 文末）。

★prove-red 就放在本文件里★（lane 不得改中心的破坏实验清单）：把 ``scene`` 包复制一份、
各施加一处破坏（① 改成员行名 → 检查 1 红；② 改页面判据 OCR 串 → 检查 2 红），真实探针必须
变红。直接运行::

    python tools\\contract_hooks\\hooks_7.py
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

HOOK_ID = "config-json-drift"


def scene_on_path() -> None:
    """把仓库根放到 sys.path【末尾】（--prove-red 的坏副本靠 PYTHONPATH 抢先命中）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))


def probe_config_json_drift() -> bool:
    """#7：真实树上配置 ↔ 磁盘产物无漂移（空 = 绿）。

    显式把真实 ``REPO_ROOT`` 传给 ``scene.drift``：prove-red 在临时副本里导入
    ``scene.drift`` 时，``__file__`` 会指向副本，但 ``assets`` 必须仍指真实仓库
    （配置层（副本里的坏 scene）对照真实 assets —— 这样「只改配置不改 JSON」才抓得到）。
    """
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    return drift.check_all(repo_root=REPO_ROOT) == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_7.py`）
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _break_check1(scene_dir: Path) -> None:
    """检查 1 破坏：把领主战一个成员的【行名】改掉，interface.json 不会跟上。

    ★#111 后调整锚点★：scene/lord_battle.py 里的成员声明已改成 _observed(子族, 行名) 形式
    （难度字面量收进 ACCOUNT_SNAPSHOTS 快照）。原破坏点
    '"领主战", "猩红巨熊讨伐", "猩红巨熊讨伐"' 随这次重构消失，改成改 _observed 的行名实参 ——
    破坏意图不变：**行名与 interface.json / 花名册对不上时，守卫必须红**。
    """
    _sub(
        scene_dir / "lord_battle.py",
        '_observed("领主战", "猩红巨熊讨伐"),',
        '_observed("领主战", "猩红巨熊讨伐·被改坏"),',
    )


def _break_check2(scene_dir: Path) -> None:
    """检查 2 破坏：把「主城」页面判据的 OCR 串改掉（pipeline 里仍是「领主战」）。"""
    _sub(
        scene_dir / "page_rules.py",
        '"expected": ["领主战"], "roi": [480, 1080, 240, 140]',
        '"expected": ["被改坏的领主战"], "roi": [480, 1080, 240, 140]',
    )


def _probe_in(root: Path):
    """子进程里、以 ``root`` 作为 ``scene`` 包来源跑本挂点探针，返回 True/False/None。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from contract_hooks import discover_hooks\n"
        f"probe = next(p for hid, _t, _w, p in discover_hooks() if hid == {HOOK_ID!r})\n"
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


def prove_red() -> bool:
    """本票自带的破坏实验：**两个检查各自**能红、真实树能绿。

    返回 ``True`` = 破坏实验成立（真实绿、两个破坏副本都红）。不碰中央 prove-red 配方。
    """
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    scene_on_path()
    import scene.drift as drift  # noqa: PLC0415

    print("hooks_7 prove-red：逐一改坏配置层，要求 config-json-drift 变红")
    green = drift.check_all(repo_root=REPO_ROOT) == []
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：配置 ↔ JSON 无漂移（绿）")
    if not green:
        return False

    ok = green
    for label, mutate in (
        ("检查 1：改成员行名（配置改了、JSON 没跟上）", _break_check1),
        ("检查 2：改页面判据 OCR 串（配置改了、pipeline 没跟上）", _break_check2),
    ):
        tmp = Path(tempfile.mkdtemp(prefix="wf_hook7_"))
        try:
            shutil.copytree(REPO_ROOT / "scene", tmp / "scene")
            mutate(tmp / "scene")
            red = _probe_in(tmp) is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"  [{'PASS' if red else 'FAIL'}] {label}：探针变红")
        ok = ok and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        HOOK_ID,
        "#7",
        "配置 ↔ pipeline JSON 漂移（GUI 目标选项 + 页面判据）必须变红",
        probe_config_json_drift,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
