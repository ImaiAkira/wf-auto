# -*- coding: utf-8 -*-
"""#20：真机 runner 必须注册 pipeline 引用的【全部】自定义识别 / 动作。

seam：``assets/resource/pipeline/*.json``（引用方）↔ ``tools/live_harness.py``
（runner 侧唯一注册源 ``CUSTOM_RECOGNITIONS`` / ``CUSTOM_ACTIONS``）。

背景（#13 真机实证）
--------------------
卡死看门狗**真的触发了**，但恢复动作却救不了：

    [stall_recover] 画面连续 182.4s 无变化（阈值 180.0s）→ 判定卡死
    [ERR][CustomAction::run] Action is null [node_name=SpecialStallRecover]
    [param.name=restart_game]

``run_special_live.py`` 只注册了 ``mark_done`` / ``special_batch_fight`` /
``special_batch_finish``，没有注册 ``restart_game`` → 命中后动作是 no-op，任务
直接 ``failed``。这类缺失是**静默的**：pipeline 引用了一个 runner 没注册的动作，
直到真机上真的走到那一步才暴露。

两个守卫（都在本文件里，prove-red 也在本文件里）：

1. ``runner-registers-all-pipeline-customs`` —— pipeline 引用的每个
   ``custom_action`` / ``custom_recognition`` 都能被 runner 的注册表解析；
   缺一个即红（并且每个注册名都要能解析到真实实现类）。
2. ``live-runners-use-canonical-registration`` —— 每个真机 runner 都走
   ``live_harness.register_pipeline_customs`` 这个唯一注册源，杜绝再手写
   「子集清单」而悄悄漏名。

★prove-red★（在文件末尾，``python tools\\contract_hooks\\hooks_20.py``）：
   * 从注册表里删掉一个被引用的动作（``restart_game``）-> 守卫 1 红；
   * 从一份 runner 副本里删掉唯一注册源调用 -> 守卫 2 红。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOOLS_DIR.parent
PIPELINE_DIR = REPO_ROOT / "assets" / "resource" / "pipeline"

# ★只 append 到 sys.path 末尾★：hooks_7 的 prove-red 会以 PYTHONPATH 抢先塞入一个
# 「坏 scene 副本」，若本模块把 REPO_ROOT 插到最前，真实 scene 会盖掉副本，
# 破坏实验就白做了（hooks_18 同样只在函数里 append）。PYTHONPATH 条目在 sys.path
# 里比 append 更靠前，因此副本仍然优先命中。
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)


# ---------------------------------------------------------------------------
# 引用名的【唯一来源】：直接扫 pipeline JSONC（与 scene.drift 同款解析）
# ---------------------------------------------------------------------------
def referenced_custom_names(pipeline_dir: Path = PIPELINE_DIR) -> tuple[set[str], set[str]]:
    """扫描 pipeline，返回 (被引用的 custom_recognition 名, custom_action 名)。"""
    from scene.drift import load_pipelines

    recos: set[str] = set()
    actions: set[str] = set()

    def walk(obj) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "custom_recognition" and isinstance(value, str):
                    recos.add(value)
                elif key == "custom_action" and isinstance(value, str):
                    actions.add(value)
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for data in load_pipelines(pipeline_dir).values():
        walk(data)
    return recos, actions


# ---------------------------------------------------------------------------
# 注册源的【唯一来源】：tools/live_harness.py
# ---------------------------------------------------------------------------
def _registry() -> tuple[dict[str, str], dict[str, str]]:
    """读 runner 侧唯一注册源（CUSTOM_RECOGNITIONS / CUSTOM_ACTIONS）。"""
    import live_harness as ca

    return dict(ca.CUSTOM_RECOGNITIONS), dict(ca.CUSTOM_ACTIONS)


def _resolve_ok(ca, spec: str) -> str | None:
    """返回 None 表示可解析；否则返回错误描述。"""
    try:
        ca._resolve_custom_class(spec)
    except Exception as exc:  # noqa: BLE001 -- 解析失败即红
        return f"{spec} 无法解析到实现类：{exc!r}"
    return None


def _missing_messages(
    registrations: tuple[dict[str, str], dict[str, str]],
    pipeline_dir: Path = PIPELINE_DIR,
) -> list[str]:
    """pipeline 引用了、但注册表没覆盖（或实现解析不了）的名字 -> 消息列表。"""
    reg_recos, reg_actions = registrations
    ref_recos, ref_actions = referenced_custom_names(pipeline_dir)

    msgs: list[str] = []
    miss_recos = sorted(ref_recos - set(reg_recos))
    miss_actions = sorted(ref_actions - set(reg_actions))
    if miss_recos:
        msgs.append(f"pipeline 引用但 runner 未注册的识别：{miss_recos}")
    if miss_actions:
        msgs.append(f"pipeline 引用但 runner 未注册的动作：{miss_actions}")

    import live_harness as ca

    for name, spec in {**reg_recos, **reg_actions}.items():
        err = _resolve_ok(ca, spec)
        if err:
            msgs.append(f"注册名 {name!r} 指向坏实现：{err}")
    return msgs


def probe_runner_registers_all_pipeline_customs() -> bool:
    """#20 守卫 1：pipeline 引用的全部自定义识别/动作都能被 runner 解析。"""
    return _missing_messages(_registry()) == []


# ---------------------------------------------------------------------------
# 守卫 2：每个真机 runner 都走唯一注册源（不再手写子集清单）
# ---------------------------------------------------------------------------
def runner_files(tools_dir: Path = TOOLS_DIR) -> list[Path]:
    """需要注册自定义动作的真机 runner：``run_*live*.py`` + ``run_pipeline.py``。"""
    out = [
        p
        for p in sorted(tools_dir.glob("run_*.py"))
        if "live" in p.stem or p.stem == "run_pipeline"
    ]
    return out


def _runner_registration_messages(tools_dir: Path = TOOLS_DIR) -> list[str]:
    msgs: list[str] = []
    files = runner_files(tools_dir)
    if not files:
        return ["找不到任何 run_*live*.py / run_pipeline.py（守卫已与实现脱节）"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "register_pipeline_customs(" not in text:
            msgs.append(f"{path.name} 没有调用 live_harness.register_pipeline_customs(...)")
    return msgs


def probe_live_runners_use_canonical_registration() -> bool:
    """#20 守卫 2：每个真机 runner 都走唯一注册源。"""
    return _runner_registration_messages() == []


# ---------------------------------------------------------------------------
# 破坏实验（in-module，`python tools/contract_hooks/hooks_20.py`）
# ---------------------------------------------------------------------------
def _dropped_action_registry() -> tuple[dict[str, str], dict[str, str]]:
    """从注册表里删掉被引用的动作 restart_game（#13 的真实缺口）。"""
    reg_recos, reg_actions = _registry()
    reg_actions.pop("restart_game", None)
    return reg_recos, reg_actions


def _temp_runner_without_registration() -> Path:
    """复制一份 run_special_live.py，删掉唯一注册源调用（模拟手写子集 / 漏注册）。"""
    src = TOOLS_DIR / "run_special_live.py"
    broken = src.read_text(encoding="utf-8").replace("ca.register_pipeline_customs(res)", "pass  # broken")
    if broken == src.read_text(encoding="utf-8"):
        raise RuntimeError("破坏点没找到：run_special_live.py 里没有 register_pipeline_customs 调用")
    tmpdir = Path(tempfile.mkdtemp(prefix="wf_hook20_"))
    dst = tmpdir / src.name
    dst.write_text(broken, encoding="utf-8")
    return dst


def prove_red() -> bool:
    """真实绿；删掉被引用动作 -> 守卫 1 红；删掉 runner 的唯一注册源调用 -> 守卫 2 红。"""
    print("hooks_20 prove-red：改坏两处，要求两个守卫各自变红")
    green = (
        probe_runner_registers_all_pipeline_customs() is True
        and probe_live_runners_use_canonical_registration() is True
    )
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：pipeline 引用全覆盖 + runner 走唯一注册源（绿）")
    if not green:
        return False

    # (a) 删掉被引用的动作 restart_game -> 守卫 1 红。
    msgs = _missing_messages(_dropped_action_registry())
    red_action = len(msgs) > 0
    tail = f"  {msgs[0]}" if msgs else "  （守卫没抓到！）"
    print(f"  [{'PASS' if red_action else 'FAIL'}] 删掉 restart_game -> {'红' if red_action else '仍绿'}{tail}")

    # (b) runner 副本删掉唯一注册源调用 -> 守卫 2 红。
    tmpdir = _temp_runner_without_registration().parent
    try:
        msgs2 = _runner_registration_messages(tmpdir)
        red_runner = len(msgs2) > 0
        tail2 = f"  {msgs2[0]}" if msgs2 else "  （守卫没抓到！）"
        print(f"  [{'PASS' if red_runner else 'FAIL'}] runner 删掉唯一注册源调用 -> {'红' if red_runner else '仍绿'}{tail2}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    ok = green and red_action and red_runner
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


HOOKS = [
    (
        "runner-registers-all-pipeline-customs",
        "#20",
        "pipeline 引用的每个 custom_action / custom_recognition 都能被 runner 解析（缺一即红）",
        probe_runner_registers_all_pipeline_customs,
    ),
    (
        "live-runners-use-canonical-registration",
        "#20",
        "每个真机 runner 都走 live_harness 的唯一注册源，不再手写子集清单",
        probe_live_runners_use_canonical_registration,
    ),
]


if __name__ == "__main__":
    raise SystemExit(0 if prove_red() else 1)
