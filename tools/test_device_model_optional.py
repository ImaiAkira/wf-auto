# -*- coding: utf-8 -*-
"""离线单测：#130 脱敏 D —— 设备型号**不再作为必须匹配条件**（三态）。

运维裁决（原话）：用户手机型号不确定，**不许把型号写成必须匹配**；用户一跑就 red 是
不可接受的。例外：仍然要**读**型号用于日志与诊断，**只是不比较**。

不需要游戏 / 设备：全是纯函数 + 假 ``read_identity``（不产生任何 adb 调用）。

直接跑::

    .venv\\Scripts\\python.exe tools\\test_device_model_optional.py

三个用例（= 验收里点名的那三个）：

  1. **unset（默认）→ 通过**：``WF_LIVE_EXPECT_*`` 全清空时 ``expected_identity()`` 没有
     任何约束；``assert_device_identity`` 读到任意型号都**只记日志、不失败**，且日志里有
     ``[device] model=<实际> (未校验)``；``resolve_address`` 也不再因型号不符而 red。
  2. **set 且相等 → 通过**：显式设置期望，读到相同型号（大小写 / 连字符归一化后相等）
     → 通过，日志标出「校验」与期望值。
  2b. **只设一个 → 只比设了的那一个**：只设 ``WF_LIVE_EXPECT_MODEL`` 时，product 不同
     也照样匹配（空期望字段**不参与**比较）。
  3. **set 且不等 → 失败**：显式设置期望，读到别的型号 → ``RuntimeError``，且消息里
     **同时**有「期望」与「实际」。

另加第 4 节（同一张票的「分辨率同理」）：720 短边识别空间 → 原生像素的**换算**按
``wm size`` 读出的短边计算（1080p → ×1.5 / 720p → ×1.0 / 1440p → ×2.0；读不到则回退
×1.5 并打印警告），**没有任何「分辨率必须等于 X」的断言**。

``--prove-red``（票面要求 ≥3 处破坏）：(a) 默认改回严格 → 用例 1 红；(b) 设了期望却永远
匹配 → 用例 3 红；(c) 只设一个却全比 → 用例 2b 红。三处**各自**能让对应用例变红，
证明这些用例真的能抓住「型号被写成必须匹配 / 校验形同虚设」的回归。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
for _p in (str(TOOLS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_harness as ca  # noqa: E402

FAILS: list[str] = []
CHECKS = 0

#: 三态全部由这三个环境变量驱动（#130：全 unset = 不校验）。
ENV_KEYS = (ca.ENV_EXPECT_MODEL, ca.ENV_EXPECT_PRODUCT, ca.ENV_EXPECT_DEVICE)

#: 用例里用的「实际读到的设备」——刻意不是任何生产默认值（谁把默认写成型号都会露馅）。
ACTUAL = ca.DeviceIdentity(
    address="1.2.3.4:5", model="EXAMPLE-PHONE", product="EXAMPLE-PROD", device="example"
)


def check(name: str, cond: bool, extra: str = "") -> None:
    global CHECKS
    CHECKS += 1
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


@contextlib.contextmanager
def env(**values: str):
    """临时设置 ``WF_LIVE_EXPECT_*``：**先全部清空**，再套用 values（= 精确三态）。"""
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    for key, value in values.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_assert(identity: ca.DeviceIdentity) -> tuple[ca.DeviceIdentity | None, str, str | None]:
    """用假 ``read_identity`` 真调 ``assert_device_identity``，拿回 (身份, stdout, 错误文本)。"""
    saved = ca.read_identity
    ca.read_identity = lambda adb, address, **kw: identity  # type: ignore[assignment]
    buf = io.StringIO()
    got: ca.DeviceIdentity | None = None
    err: str | None = None
    try:
        with contextlib.redirect_stdout(buf):
            got = ca.assert_device_identity("fake-adb", identity.address or "1.2.3.4:5")
    except RuntimeError as exc:
        err = str(exc)
    finally:
        ca.read_identity = saved  # type: ignore[assignment]
    return got, buf.getvalue(), err


# ---------------------------------------------------------------------------
# 用例 1：unset（默认）→ 不校验，只记日志
# ---------------------------------------------------------------------------
def case_unset() -> None:
    print("\n== 1. unset（默认）：不校验型号，只把读到的值打进日志 ==")
    with env():  # WF_LIVE_EXPECT_* 全 unset
        expected = ca.expected_identity()
        check("unset：expected_identity() 没有任何约束（不校验）",
              not expected.constrained(), expected.describe())
        check("unset：任意型号 identity_mismatch 都返回 None（不比较）",
              ca.identity_mismatch(ACTUAL, expected) is None)

        got, out, err = _run_assert(ACTUAL)
        check("unset：读到任意型号都**不失败**", err is None and got is ACTUAL, err or "")
        check("unset：日志里有 `[device] model=EXAMPLE-PHONE (未校验)`",
              "[device] model=EXAMPLE-PHONE (未校验)" in out, out.strip())

        # resolve_address：型号不参与筛选 —— 唯一一台在线设备直接可用。
        one = [("emulator-5554", ACTUAL)]
        try:
            single = ca.resolve_address("fake-adb", expected, devices=one)
        except RuntimeError as exc:  # 旧行为（默认型号）下会走到这里 -> 记成 FAIL，而不是崩掉
            single = f"RuntimeError: {exc}"
        check("unset：单台在线设备直接可用（型号任意）", single == "emulator-5554", single)

        # 多台 -> 仍然拒绝（地址不唯一），但原因是「不唯一」，不是「型号不符」。
        two = one + [("127.0.0.1:5555", ca.DeviceIdentity(model="OTHER-PHONE"))]
        try:
            ca.resolve_address("fake-adb", expected, devices=two)
        except RuntimeError as exc:
            msg = str(exc)
        else:
            msg = ""
        check("unset：多台在线设备 -> 报错（地址不唯一），提示 WF_LIVE_ADDRESS",
              "WF_LIVE_ADDRESS" in msg, msg)
        check("unset：该报错**不是**「型号必须匹配」（没有把型号当条件）",
              "型号" not in msg or "不校验型号" in msg, msg)


# ---------------------------------------------------------------------------
# 用例 2：显式设置且相等 → 通过
# ---------------------------------------------------------------------------
def case_explicit_match() -> None:
    print("\n== 2. set 且相等：严格校验通过 ==")
    with env(WF_LIVE_EXPECT_MODEL="EXAMPLE-PHONE", WF_LIVE_EXPECT_PRODUCT="EXAMPLE-PROD"):
        expected = ca.expected_identity()
        check("set：期望被读到（model / product）",
              expected.model == "EXAMPLE-PHONE" and expected.product == "EXAMPLE-PROD",
              expected.describe())
        check("set 且相等：大小写 / 连字符归一化后仍匹配",
              ca.DeviceIdentity(model="example_phone", product="example-prod").matches(expected))
        check("set 且相等：identity_mismatch -> None",
              ca.identity_mismatch(ACTUAL, expected) is None)

        got, out, err = _run_assert(ACTUAL)
        check("set 且相等：assert_device_identity 通过", err is None and got is ACTUAL, err or "")
        check("set 且相等：日志标出「校验」且带期望值",
              "[device] model=EXAMPLE-PHONE (校验: 期望 model=EXAMPLE-PHONE" in out,
              out.strip())


# ---------------------------------------------------------------------------
# 用例 2b：只设一个 → 只比较设了的那一个（票面第 3 条守卫）
# ---------------------------------------------------------------------------
def case_only_one_set() -> None:
    print("\n== 2b. 只设一个：只比较设了的那一个 ==")
    with env(WF_LIVE_EXPECT_MODEL="EXAMPLE-PHONE"):
        expected = ca.expected_identity()
        check("只设 model：只有 model 有约束（product 空）",
              expected.model == "EXAMPLE-PHONE" and not expected.product,
              expected.describe())
        check("只设 model：product 不同也匹配（只比设了的）",
              ca.DeviceIdentity(model="EXAMPLE-PHONE", product="OTHER-PRODUCT").matches(expected))
        check("只设 model：model 不同则不匹配（设了就严格）",
              not ca.DeviceIdentity(model="OTHER-MODEL", product="EXAMPLE-PROD").matches(expected))
        check("只设 model：identity_mismatch 对「同 model」返回 None",
              ca.identity_mismatch(
                  ca.DeviceIdentity(model="example_phone", product="OTHER-PRODUCT"),
                  expected) is None)

    with env(WF_LIVE_EXPECT_PRODUCT="EXAMPLE-PROD"):
        expected = ca.expected_identity()
        check("只设 product：model 不同也匹配（只比设了的）",
              ca.DeviceIdentity(model="OTHER-MODEL", product="example-prod").matches(expected))


# ---------------------------------------------------------------------------
# 用例 3：显式设置且不等 → 失败，消息里有期望 vs 实际
# ---------------------------------------------------------------------------
def case_explicit_mismatch() -> None:
    print("\n== 3. set 且不等：必须失败，并打印期望 vs 实际 ==")
    with env(WF_LIVE_EXPECT_MODEL="EXPECTED-MODEL", WF_LIVE_EXPECT_PRODUCT="EXPECTED-PROD"):
        expected = ca.expected_identity()
        problem = ca.identity_mismatch(ACTUAL, expected)
        check("set 且不等：identity_mismatch 给出原因", bool(problem), problem or "")
        check("set 且不等：原因里有期望值", "EXPECTED-MODEL" in (problem or ""))
        check("set 且不等：原因里有实际值", "EXAMPLE-PHONE" in (problem or ""), problem or "")

        got, out, err = _run_assert(ACTUAL)
        check("set 且不等：assert_device_identity 抛 RuntimeError", err is not None, err or "")
        check("set 且不等：错误消息里有期望与实际",
              "EXPECTED-MODEL" in (err or "") and "EXAMPLE-PHONE" in (err or ""), err or "")


# ---------------------------------------------------------------------------
# 附加：分辨率只**换算**不断言（720 短边识别空间 -> 原生像素）
# ---------------------------------------------------------------------------
def case_scale_conversion() -> None:
    print("\n== 4. 分辨率：按 wm size 换算，不写死 1080x1920（也绝不是断言） ==")
    saved_adb = ca._adb
    saved_cache = dict(ca._DISPLAY_CACHE)
    saved_address = ca.ADDRESS

    class _Proc:
        def __init__(self, text: str) -> None:
            self.stdout = text.encode("utf-8")

    def use(wm_output: str) -> None:
        ca._adb = lambda *args, **kw: _Proc(wm_output)  # type: ignore[assignment]
        ca._DISPLAY_CACHE.update(address=None, size=None, scale=None)

    try:
        ca.ADDRESS = "fake:1080"
        use("Physical size: 1080x1920\n")
        check("1080x1920 -> ×1.5（与旧行为逐像素一致）",
              abs(ca.device_scale() - 1.5) < 1e-9, f"scale={ca.device_scale():g}")

        ca.ADDRESS = "fake:720"
        use("Physical size: 720x1280\n")
        check("720x1280 -> ×1.0（旧实现会错点 1.5 倍远）",
              abs(ca.device_scale() - 1.0) < 1e-9, f"scale={ca.device_scale():g}")

        ca.ADDRESS = "fake:1440"
        use("Physical size: 1440x2560\n")
        check("1440x2560 -> ×2.0（任何分辨率都只是系数不同）",
              abs(ca.device_scale() - 2.0) < 1e-9, f"scale={ca.device_scale():g}")

        ca.ADDRESS = "fake:unknown"
        use("garbage\n")
        check("读不到 wm size -> 回退 ×1.5（打印警告，不是断言失败）",
              abs(ca.device_scale() - ca.DEFAULT_SCALE) < 1e-9,
              f"scale={ca.device_scale():g}")
    finally:
        ca._adb = saved_adb  # type: ignore[assignment]
        ca._DISPLAY_CACHE.update(saved_cache)
        ca.ADDRESS = saved_address


# ---------------------------------------------------------------------------
# 破坏实验（≥3，对应票面第 4 条）：
#   (a) 默认改回严格        -> 用例 1（unset）必须红
#   (b) 设了也比不了        -> 用例 3（set 且不等）必须红
#   (c) 只设一个却全比      -> 用例 2b（只设一个）必须红
# ---------------------------------------------------------------------------
def _red_delta(fn) -> int:
    """跑一个用例，返回它新增的失败数（>0 = 该用例对这次破坏敏感）。"""
    before = len(FAILS)
    fn()
    return len(FAILS) - before


def _sabotage_default_strict() -> int:
    """(a) 模拟 #130 之前的实现：默认期望 = 一个写死的型号。"""
    saved = ca.expected_identity
    ca.expected_identity = lambda: ca.DeviceIdentity(  # type: ignore[assignment]
        model="HARDCODED-DEFAULT", product="HARDCODED-PRODUCT"
    )
    try:
        return _red_delta(case_unset)
    finally:
        ca.expected_identity = saved  # type: ignore[assignment]


def _sabotage_never_compare() -> int:
    """(b) 设了期望却「永远匹配」：校验形同虚设。"""
    saved = ca.identity_mismatch
    ca.identity_mismatch = lambda identity, expected: None  # type: ignore[assignment]
    try:
        return _red_delta(case_explicit_mismatch)
    finally:
        ca.identity_mismatch = saved  # type: ignore[assignment]


def _sabotage_compare_all_fields() -> int:
    """(c) 只设了一个字段，却把空字段也拿去比（= 「只设一个却全比」）。"""

    def strict_all(self, expected):  # noqa: ANN001 -- 故意把空期望字段也拿来比
        return (
            ca._norm_identity(self.model) == ca._norm_identity(expected.model)
            and ca._norm_identity(self.product) == ca._norm_identity(expected.product)
            and ca._norm_identity(self.device) == ca._norm_identity(expected.device)
        )

    saved = ca.DeviceIdentity.matches
    ca.DeviceIdentity.matches = strict_all  # type: ignore[assignment]
    try:
        return _red_delta(case_only_one_set)
    finally:
        ca.DeviceIdentity.matches = saved  # type: ignore[assignment]


def prove_red() -> int:
    print("=" * 72)
    print("#130 prove-red：三处破坏，要求对应用例各自变红")
    print("=" * 72)
    a = _sabotage_default_strict()
    print(f"  [{'PASS' if a else 'FAIL'}] (a) 默认改回硬编码型号 -> 用例 1 "
          f"{'红（%d 项失败）' % a if a else '仍绿（用例没保护力！）'}")
    b = _sabotage_never_compare()
    print(f"  [{'PASS' if b else 'FAIL'}] (b) 设了期望却永远匹配 -> 用例 3 "
          f"{'红（%d 项失败）' % b if b else '仍绿（用例没保护力！）'}")
    c = _sabotage_compare_all_fields()
    print(f"  [{'PASS' if c else 'FAIL'}] (c) 只设一个却全比 -> 用例 2b "
          f"{'红（%d 项失败）' % c if c else '仍绿（用例没保护力！）'}")
    ok = a > 0 and b > 0 and c > 0
    print("\n" + "-" * 72)
    if ok:
        print("prove-red 成功：三处破坏各自能让对应用例变红 -> 用例有保护力。")
        return 0
    print("prove-red 失败：至少一处破坏没让用例变红 —— 用例没有保护力！")
    return 1


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    if "--prove-red" in sys.argv:
        return prove_red()

    print("=" * 72)
    print("离线单测：#130 设备型号只用于诊断日志，默认不作匹配条件（三态）")
    print("=" * 72)
    case_unset()
    case_explicit_match()
    case_only_one_set()
    case_explicit_mismatch()
    case_scale_conversion()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"结果：{len(FAILS)}/{CHECKS} 项失败 -> {FAILS}")
        return 1
    print(f"结果：{CHECKS} 项全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
