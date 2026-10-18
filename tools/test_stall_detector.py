# -*- coding: utf-8 -*-
"""#23 守卫：卡死看门狗不得把「规律循环」判成卡死（真机帧实证）。

背景（#13 第 3 次真机运行，设备实证）
------------------------------------
::

    15:54:07 SpecialStallRecover
    [stall_recover] 画面连续 187.1s 无变化（阈值 180.0s）→ 判定卡死
    [restart_game] ... 强杀/重启游戏

可那 187 秒里画面每 ~3 秒就在 主城 / 领主战列表 / 详情页 之间规律轮转（#22 的循环）。
看门狗把「规律循环」看成「无变化」，触发了一次多余的强杀重启。

真实缺陷（debug/vision 实证）
------------------------------
看门狗实际收到的是**同一个 SpecialEntry 轮里先跑的那些 OCR 节点的整屏图**
（720x1280）。把它们按真机节奏（~11s 一轮）排出来，64x64 灰度特征两两比较：
**平均绝对差只有 1.20~2.10（全部 < 旧阈值 3.0），但显著变化格子占比 1.95%~3.44%**
—— 主城界面上有走动的小精灵 / 闪烁特效，是**局部小动**，被整帧平均稀释到 3.0 以下。
旧判据（只看平均差）因此对「规律循环」失明；而真·冻结（同一帧对自身）平均差 0、
占比 0，二者本可区分。

本守卫用的就是**那几帧真机图**（以 64x64 灰度内嵌在 ``_SAMPLES_B64``，见下方
``_BLOB_SOURCE`` 记录来源），在 180s 窗口内循环喂给**真正的**
``side_impl.StallRecoverRecognition.analyze``：

  · 用例一（regular-cycle）：真机循环帧序列 → **不得**判卡死；
  · 用例二（truly-static）：同一帧重复 → **必须**判卡死（真阳性路径不丢）；
  · 另外断言判据的**分离证据**：循环帧最大平均差 < 3.0（旧判据盲）且
    最小显著变化占比 > motion_frac（新判据可见）。

破坏实验（``--prove-red``）
---------------------------
把 ``agent/side_impl.py`` 的判据退回旧形态（只看平均差）→ 用例一变红。
红 = 可用信号。

真机帧（可选，存在才跑）：``<local>\\AppData\\Local\\Temp\\opencode\\rerun13b\\frames``
（3s 抓帧，15:50:48→15:54:06 主城/列表/详情循环）。这是「画面确实在动」的物理证据。

跑法::

    python tools\\test_stall_detector.py              # 绿
    python tools\\test_stall_detector.py --prove-red  # 退回旧判据 -> 用例一必须变红
"""

from __future__ import annotations
from portable_paths import TEMP_OPENCODE  # noqa: E402

import base64
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
AGENT_DIR = REPO_ROOT / "agent"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
# append（不是 insert）：prove-red 的坏副本靠 PYTHONPATH 抢先命中（见 hooks_22 同款）。
if str(AGENT_DIR) not in sys.path:
    sys.path.append(str(AGENT_DIR))

import numpy as np  # noqa: E402

# 判据默认参数（与 agent/side_impl.py 的 _STALL_MOTION_FRAC / diff_threshold 对齐）。
DIFF_THRESHOLD = 3.0
MOTION_FRAC = 0.004
MOTION_EPS = 8.0

# 真机证据来源（只读、不入库；两者都在设备上，见 #23 Evidence）：
_BLOB_SOURCE = (
    "debug/vision/2026.10.13-15.53.{11.746,22.896,34.63,45.135,56.220}-15.54.07.210_"
    "PubLevelUpText_*.jpg 的 64x64 灰度（MAA 喂给 stall 看门狗的同一轮整屏图）"
)

# 6 帧真机采样图的 64x64 灰度（uint8，zlib+base64 内嵌，离线可复现）。
# 由 tools 生成：读 debug/vision 的整屏图 -> _stall_feature(64x64) -> stack -> compress。
_SAMPLES_B64 = (
    "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"
)

# 可选的真机 3s 抓帧目录（存在则额外回放，验证「画面确实在动」）。
REAL_FRAMES_DIR = Path(str(TEMP_OPENCODE / "rerun13b/frames"))


# ---------------------------------------------------------------------------
# 把真机帧序列喂给真实识别器
# ---------------------------------------------------------------------------
def real_sample_frames():
    """内嵌的 6 帧真机采样（64x64 灰度），转成 HxWx3 供 _stall_feature 消费。"""
    raw = zlib.decompress(base64.b64decode(_SAMPLES_B64))
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 64, 64)
    return [np.stack([g, g, g], axis=-1) for g in arr]


class _TaskDetail:
    task_id = 1


class _Argv:
    """analyze 需要的最小 argv：image + custom_recognition_param + task_detail。"""

    def __init__(self, image, param="{}"):
        self.image = image
        self.custom_recognition_param = param
        self.task_detail = _TaskDetail()
        self.node_name = "SpecialStallRecover"
        self.custom_recognition_name = "stall_recover"
        self.roi = (0, 0, 0, 0)


class _Clock:
    """受控单调时钟，替换 side_impl.time（只影响 stall 的墙钟计时）。"""

    def __init__(self, t=1000.0):
        self.t = t

    def monotonic(self):
        return self.t


def _reset_stall(side):
    side._STALL_REF = None
    side._STALL_TASK_ID = None
    side._STALL_LAST_CALL = None
    side._STALL_SINCE = None


def drive(frames, *, cadence=3.0, seconds=210.0, param="{}"):
    """按 cadence 把 frames 循环喂给真实识别器，返回 (是否判过卡死, 每条 detail)。"""
    side = importlib.import_module("side_impl")
    rec = side.StallRecoverRecognition()
    clock = _Clock()
    real_time = side.time
    side.time = clock
    records = []
    stalled = False
    try:
        _reset_stall(side)
        n = int(seconds // cadence) + 1
        for i in range(n):
            clock.t = 1000.0 + i * cadence
            res = rec.analyze(None, _Argv(frames[i % len(frames)], param))
            det = dict(res.detail)
            records.append(det)
            if det.get("stall"):
                stalled = True
        return stalled, records
    finally:
        side.time = real_time
        _reset_stall(side)


# ---------------------------------------------------------------------------
# 旧 / 新判据的分离证据（直接在真机采样帧上算）
# ---------------------------------------------------------------------------
def _consecutive_metrics(frames):
    out = []
    for i in range(len(frames) - 1):
        a = frames[i].astype(np.float32)
        b = frames[i + 1].astype(np.float32)
        d = np.abs(a - b)
        out.append((float(np.mean(d)), float(np.mean(d > MOTION_EPS))))
    return out


def evidence_failures() -> list:
    """循环帧：旧判据盲（<3.0）/ 新判据可见（>motion_frac）；冻结：全 0。"""
    msgs = []
    frames = real_sample_frames()
    metrics = _consecutive_metrics(frames)
    max_mean = max(m for m, _ in metrics)
    min_frac = min(f for _, f in metrics)
    if not (max_mean < DIFF_THRESHOLD):
        msgs.append(f"循环帧的最大平均差 {max_mean:.2f} 应 < {DIFF_THRESHOLD}（旧判据才会漏判）")
    if not (min_frac > MOTION_FRAC):
        msgs.append(f"循环帧的最小显著变化占比 {min_frac:.4f} 应 > {MOTION_FRAC}（新判据才看得见）")
    zero = np.abs(frames[0].astype(np.float32) - frames[0].astype(np.float32))
    if float(np.mean(zero)) != 0.0 or float(np.mean(zero > MOTION_EPS)) != 0.0:
        msgs.append("冻结帧（自比）必须全 0")
    return msgs


# ---------------------------------------------------------------------------
# 两个用例
# ---------------------------------------------------------------------------
def case_cycle_not_stall() -> bool:
    """用例一：真机「规律循环」帧序列 → 不得判卡死。"""
    frames = real_sample_frames()
    stalled, _ = drive(frames, seconds=210.0)
    return not stalled


def case_frozen_still_stalls() -> bool:
    """用例二：真·冻结（同一帧重复）→ 必须判卡死（真阳性不丢）。"""
    frames = real_sample_frames()[:1]
    stalled, _ = drive(frames, seconds=210.0)
    return stalled


def probe_stall_detector() -> bool:
    """两用例 + 分离证据全部成立才算绿。"""
    return run_guards() == []


def run_guards() -> list:
    msgs = []
    msgs += evidence_failures()
    if not case_cycle_not_stall():
        msgs.append("regular-cycle（规律循环）被判成卡死（旧误判复现）")
    if not case_frozen_still_stalls():
        msgs.append("truly-static（真·冻结）未被判卡死（真阳性丢失）")
    return msgs


# ---------------------------------------------------------------------------
# 破坏实验
# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _temp_agent_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="wf_hook23_agent_"))
    shutil.copytree(AGENT_DIR, root / "agent")
    return root / "agent"


def _run_probe_in(root: Path, probe_name: str):
    """以 ``root`` 作为 side_impl 包来源（PYTHONPATH 抢先）跑一个探针。"""
    code = (
        "import sys\n"
        "sys.path[:] = [p for p in sys.path if p not in ('', '.')]\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from test_stall_detector import " + probe_name + "\n"
        f"print('PROBE_RESULT', repr({probe_name}()))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    neutral = Path(tempfile.mkdtemp(prefix="wf_neutral23_"))
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
    """真实绿；把判据退回旧形态（只看平均差）→ 用例一变红。"""
    print("test_stall_detector prove-red：退回旧判据，要求「规律循环」用例变红")
    real = case_cycle_not_stall()
    print(f"  [{'PASS' if real else 'FAIL'}] 真实实现：规律循环帧序列不判卡死（绿）")

    agent_dir = _temp_agent_copy()
    try:
        _sub(
            agent_dir / "side_impl.py",
            "            if diff > diff_th or moved_frac > motion_frac:",
            "            if diff > diff_th:  # #23 prove-red：退回旧判据（只看平均差）",
        )
        broken = _run_probe_in(agent_dir, "probe_stall_detector")
        red = broken is False
        print(
            f"  [{'PASS' if red else 'FAIL'}] 退回旧判据 -> 规律循环{'被判卡死（红）' if red else '仍绿'}"
        )
    finally:
        shutil.rmtree(agent_dir.parent, ignore_errors=True)

    ok = real and red
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


# ---------------------------------------------------------------------------
# 真机 3s 抓帧（可选）
# ---------------------------------------------------------------------------
def _load_real_frame(path: Path):
    from PIL import Image

    a = np.asarray(Image.open(path).convert("RGB"))
    return np.ascontiguousarray(a)


def device_frame_cycle_evidence() -> list:
    """可选：真机 3s 抓帧的循环窗口 → 不得判卡死（设备在才跑）。"""
    msgs = []
    if not REAL_FRAMES_DIR.is_dir():
        print(f"  [SKIP] 真机抓帧目录不存在：{REAL_FRAMES_DIR}")
        return msgs
    try:
        import PIL  # noqa: F401,PLC0415
    except ImportError:
        print("  [SKIP] 无 PIL，跳过真机抓帧回放")
        return msgs
    try:
        names = sorted(f for f in os.listdir(REAL_FRAMES_DIR) if f.endswith(".png"))
    except OSError:
        return msgs
    lo, hi = "155048", "155405"
    win = [n for n in names if lo <= n.split("_")[-1].split(".")[0] <= hi]
    if len(win) < 10:
        print("  [SKIP] 真机抓帧窗口不足")
        return msgs
    frames = [_load_real_frame(REAL_FRAMES_DIR / n) for n in win]
    stalled, _ = drive(frames, cadence=3.0, seconds=210.0)
    print(
        f"  真机 3s 抓帧 {len(win)} 帧（{win[0]} → {win[-1]}）："
        f"{'判成卡死 (FAIL)' if stalled else '未判卡死 (OK)'}"
    )
    if stalled:
        msgs.append("真机循环抓帧被判成卡死")
    return msgs


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    if "--prove-red" in sys.argv[1:]:
        return 0 if prove_red() else 1

    ev = evidence_failures()
    cyc = case_cycle_not_stall()
    froz = case_frozen_still_stalls()
    print("=" * 74)
    print("#23 卡死看门狗：「规律循环」不得判卡死")
    print("=" * 74)
    print(f"  [{'PASS' if ev == [] else 'FAIL'}] 判据分离证据（旧盲 / 新可见 / 冻结全 0）")
    print(f"  [{'PASS' if cyc else 'FAIL'}] 用例一：规律循环 → 不判卡死")
    print(f"  [{'PASS' if froz else 'FAIL'}] 用例二：真·冻结 → 判卡死")

    fails = list(ev)
    if not cyc:
        fails.append("regular-cycle（规律循环）被判成卡死（旧误判复现）")
    if not froz:
        fails.append("truly-static（真·冻结）未被判卡死（真阳性丢失）")
    fails += device_frame_cycle_evidence()

    if fails:
        print("\n结果：★不通过★ -> " + "; ".join(fails))
        return 1
    print("\n结果：#23 守卫就绪 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
