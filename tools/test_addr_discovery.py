# -*- coding: utf-8 -*-
"""离线单测：#40 设备**端口会漂移** —— 工具按【账号身份】发现设备 + 连接身份守卫。

不需要游戏 / 设备；默认连 maa 运行时都不需要（纯函数 + 假 controller + 假 getprop）。

直接跑::

    .venv\\Scripts\\python.exe tools\\test_addr_discovery.py

覆盖 #40 的验收：

  1. **身份判据**（纯函数）：``DeviceIdentity.matches`` 归一化机型的大小写 / 连字符差异
     （``MODEL_A`` == ``MODEL-A``），产品名不符即不匹配；
  2. **身份读取**（假 getprop）：``read_identity`` 把 model/product/device/包名读成身份，
     不产生任何输入；
  3. **按身份解析地址**：单命中 -> 返回它；命中多个 TCP -> 报错（绝不随机赌一台）；
     无命中 -> 报错；``WF_LIVE_ADDRESS`` 显式覆盖优先；
  4. **连接身份守卫**：``connect_device(..., expect=...)`` 身份不符即抛 RuntimeError
     （防止误驱动别的账号），匹配则正常返回；
  5. **只读真机演示**（best-effort，需 ``WF_LIVE_DISCOVERY=1``）：枚举在线设备、打印每台
     身份（机型/产品名/包名，可选 OCR 主角色/RANK），**不发送任何输入**；
  6. 挂点 ``hooks_40`` 已点亮、prove-red 成立。

★#130（脱敏 D）★：型号**不是**必须匹配条件 —— ``expected_identity()`` 在 ``WF_LIVE_EXPECT_*``
全 unset 时返回**空期望**（= 不校验）。所以本文件里凡是「要按身份筛选 / 要拒绝」的用例都
**显式**构造期望身份，不再依赖任何写死的默认型号；三态本身由
``tools/test_device_model_optional.py`` 专门覆盖。

挂点本体与 prove-red 在 ``tools/contract_hooks/hooks_40.py``。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hooks_40  # noqa: E402
import live_harness as ca  # noqa: E402

FAILS: list[str] = []
SKIPS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  [SKIP] {name}  {reason}")
    SKIPS.append(name)


def _raises_runtime(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except RuntimeError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------------------
# 1. 身份判据（纯函数）
# ---------------------------------------------------------------------------
def test_identity_match() -> None:
    print("\n== 1. 身份判据：归一化机型 + 产品名 ==")
    expected = ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")
    check("机型大小写/连字符差异不算不同设备（MODEL_A == MODEL-A）",
          ca.DeviceIdentity(model="MODEL_A", product="PRODUCT-A").matches(expected))
    check("小写也不受影响", ca.DeviceIdentity(model="model-a", product="product-a").matches(expected))
    other = ca.DeviceIdentity(model="MODEL-B", product="PRODUCT-B")
    check("产品名不符即不匹配（另一台设备）", not other.matches(expected))
    check("仅机型相同也算匹配（期望只约束给了的字段）",
          ca.DeviceIdentity(model="MODEL-A", product="Whatever").matches(
              ca.DeviceIdentity(model="MODEL-A")))
    check("identity_mismatch：匹配 -> None", ca.identity_mismatch(
        ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A"), expected) is None)
    problem = ca.identity_mismatch(other, expected)
    check("identity_mismatch：不符 -> 有原因文本", bool(problem) and "不匹配" in problem)


# ---------------------------------------------------------------------------
# 2. 身份读取（假 getprop，无设备、无输入）
# ---------------------------------------------------------------------------
def test_read_identity_offline() -> None:
    print("\n== 2. read_identity：假 getprop -> 身份（只读，无输入） ==")
    props = {
        "ro.product.model": "MODEL-A",
        "ro.product.name": "PRODUCT-A",
        "ro.product.device": "PRODUCT-A",
    }
    calls: list[tuple] = []

    def fake_adb_serial(adb, serial, *args):
        calls.append((serial, *args))
        if args[:2] == ("shell", "getprop"):
            return subprocess.CompletedProcess([], 0, stdout=(props[args[2]] + "\n").encode())
        if args[:3] == ("shell", "pm", "list"):
            return subprocess.CompletedProcess([], 0, stdout=b"package:com.leiting.wf\n")
        return subprocess.CompletedProcess([], 0, stdout=b"")

    saved = ca._adb_serial
    try:
        ca._adb_serial = fake_adb_serial  # type: ignore[assignment]
        ident = ca.read_identity("fake-adb", "127.0.0.1:9")
    finally:
        ca._adb_serial = saved  # type: ignore[assignment]
    check("机型读出 MODEL-A", ident.model == "MODEL-A", ident.label())
    check("产品名读出 PRODUCT-A", ident.product == "PRODUCT-A")
    check("包名读出 com.leiting.wf", ident.package == "com.leiting.wf")
    # #130：这里必须给**显式**期望 —— 默认（WF_LIVE_EXPECT_* unset）是「不校验」，
    # 用 ca.expected_identity() 会拿到空期望（恒匹配），断言就失去意义。
    check("身份匹配显式期望", ident.matches(ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")))
    check("getprop 是只读查询（只有 shell getprop / pm list，没有 input）",
          all(c[1] == "shell" for c in calls) and not any("input" in c for c in calls))


def test_read_game_identity_offline() -> None:
    print("\n== 2b. read_game_identity：合成主城 OCR -> 主角色 / RANK（取最贴近标签的值） ==")
    # 真机主城左上角（720 空间，取自 #40 证据帧 start_home.png 的 OCR；OCR 把标签读成「I RANK」）。
    items = [
        ("I RANK", [6, 101, 65, 27]),
        ("账号A", [7, 73, 51, 28]),      # 主角色名（在 RANK 标签上方）
        ("158", [13, 121, 65, 39]),    # RANK 值（紧贴标签下方）
        ("RP", [14, 220, 29, 26]),
        ("12146", [19, 206, 57, 26]),  # RP/EXP 值，不得被当成 RANK
    ]
    saved = ca.ocr
    try:
        ca.ocr = lambda image, assets_dir: items  # type: ignore[assignment]
        role, rank = ca.read_game_identity(object(), object())
    finally:
        ca.ocr = saved  # type: ignore[assignment]
    check("主角色读出（RANK 标签上方）", role == "账号A", f"role={role!r}")
    check("RANK 读出紧贴标签的值 158（不是更下方的 12146）", rank == "158", f"rank={rank!r}")


# ---------------------------------------------------------------------------
# 3. 按身份解析地址
# ---------------------------------------------------------------------------
def _devices():
    """合成在线设备表：测试账号（两条 transport）+ 另一台设备。"""
    return [
        ("emulator-5554", ca.DeviceIdentity(address="emulator-5554", model="MODEL-A", product="PRODUCT-A")),
        ("127.0.0.1:16384", ca.DeviceIdentity(address="127.0.0.1:16384", model="MODEL-A", product="PRODUCT-A")),
        ("127.0.0.1:16448", ca.DeviceIdentity(address="127.0.0.1:16448", model="MODEL-B", product="PRODUCT-B")),
    ]


def test_resolve_address() -> None:
    print("\n== 3. resolve_address：按身份发现（端口不是真源；#130 期望必须显式） ==")
    # #130：默认（WF_LIVE_EXPECT_* unset）是「不校验」——这里要测「按身份筛选」，
    # 所以**显式**给出期望身份；不能再用 ca.expected_identity()（它现在默认为空）。
    account_a = ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")
    saved_env = os.environ.pop("WF_LIVE_ADDRESS", None)
    try:
        got = ca.resolve_address("fake-adb", account_a, devices=_devices())
        check("测试账号 -> 命中 TCP 端口（优先 host:port，非 emulator-*）",
              got == "127.0.0.1:16384", f"got={got}")
        other = ca.resolve_address(
            "fake-adb",
            ca.DeviceIdentity(model="MODEL-B", product="PRODUCT-B"),
            devices=_devices(),
        )
        check("另一台设备按其身份 -> 命中它自己的地址", other == "127.0.0.1:16448", f"got={other}")

        # 无命中 -> 报错（绝不回退到写死端口）
        check("没有设备匹配 -> 抛 RuntimeError",
              _raises_runtime(ca.resolve_address, "fake-adb",
                              ca.DeviceIdentity(model="NOPE", product="NOPE"), devices=[]))

        # 多个 TCP 都匹配 -> 报错（不随机赌一台）
        ambiguous = [
            ("127.0.0.1:1", ca.DeviceIdentity(address="127.0.0.1:1", model="MODEL-A", product="PRODUCT-A")),
            ("127.0.0.1:2", ca.DeviceIdentity(address="127.0.0.1:2", model="MODEL-A", product="PRODUCT-A")),
        ]
        check("多个 TCP 命中 -> 抛 RuntimeError（不赌）",
              _raises_runtime(ca.resolve_address, "fake-adb", account_a, devices=ambiguous))

        # 显式覆盖优先
        os.environ["WF_LIVE_ADDRESS"] = "9.9.9.9:1234"
        try:
            forced = ca.resolve_address("fake-adb", account_a, devices=_devices())
        finally:
            os.environ.pop("WF_LIVE_ADDRESS", None)
        check("WF_LIVE_ADDRESS 显式覆盖优先", forced == "9.9.9.9:1234", f"got={forced}")
    finally:
        if saved_env is not None:
            os.environ["WF_LIVE_ADDRESS"] = saved_env


# ---------------------------------------------------------------------------
# 4. 连接身份守卫
# ---------------------------------------------------------------------------
def test_connect_identity_guard() -> None:
    print("\n== 4. connect_device 身份守卫：**显式**期望不符即拒绝（#130） ==")
    # #130：默认（WF_LIVE_EXPECT_* unset）不校验；这里测「显式期望」这条腿，故固定给值。
    expected = ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A")
    saved = (ca.AdbController, ca.read_identity, ca.ADB, ca.ADDRESS, ca._ctrl_ref.get("ctrl"))
    try:
        ca.AdbController = hooks_40._FakeCtrl  # type: ignore[assignment]
        ca.read_identity = lambda adb, address, **kw: ca.DeviceIdentity(  # type: ignore[assignment]
            address=address, model="MODEL-B", product="PRODUCT-B")
        check("身份不符 -> 抛 RuntimeError（拒绝执行）",
              _raises_runtime(ca.connect_device, "fake-adb", "1.2.3.4:5", expect=expected))

        ca.read_identity = lambda adb, address, **kw: ca.DeviceIdentity(  # type: ignore[assignment]
            address=address, model="MODEL-A", product="PRODUCT-A")
        ctrl = ca.connect_device("fake-adb", "1.2.3.4:5", expect=expected)
        check("身份匹配 -> 正常连接并登记地址", isinstance(ctrl, hooks_40._FakeCtrl) and ca.ADDRESS == "1.2.3.4:5")
    finally:
        ca.AdbController, ca.read_identity, ca.ADB, ca.ADDRESS = saved[0], saved[1], saved[2], saved[3]  # type: ignore[assignment]
        ca._ctrl_ref["ctrl"] = saved[4]


# ---------------------------------------------------------------------------
# 5. 只读真机演示（best-effort，默认 SKIP；不发送任何输入）
# ---------------------------------------------------------------------------
def test_live_discovery_demo() -> None:
    print("\n== 5. 只读真机演示：身份发现报告在线设备（无输入） ==")
    if os.environ.get("WF_LIVE_DISCOVERY") not in ("1", "true", "yes"):
        skip("真机身份发现演示", "需 WF_LIVE_DISCOVERY=1（真机在线；本套件默认离线）")
        return
    try:
        found = ca.discover_devices(ca.ADB)
    except Exception as exc:  # noqa: BLE001
        skip("真机身份发现演示", f"adb 不可用：{exc!r}")
        return
    if not found:
        skip("真机身份发现演示", "没有在线设备")
        return
    print("  ---- 只读枚举（getprop / pm list，均不发送输入） ----")
    for addr, ident in found:
        print(f"    {addr:20} -> {ident.label()}")
    # #130：要「认出测试账号」必须给**显式**期望（默认不校验 = 恒匹配，测不出东西）。
    test_acct = [
        a for a, i in found
        if i.matches(ca.DeviceIdentity(model="MODEL-A", product="PRODUCT-A"))
    ]
    check("报告里能看到测试账号（MODEL-A / PRODUCT-A）", bool(test_acct), f"matches={test_acct}")
    if len(found) >= 2:
        models = {i.model for _, i in found}
        check("报告里能看到不同的机型（证明不是同一台）", len(models) >= 2, f"models={sorted(models)}")
    # 可选：对第一台截图做只读 OCR 读主角色/RANK（仍不发送输入）。
    if os.environ.get("WF_LIVE_DISCOVERY_OCR") in ("1", "true", "yes"):
        assets = _pick_assets()
        if assets is None:
            skip("只读 OCR 主角色/RANK", "缺 OCR 模型（本工作树 / 主工作树都没有 det.onnx）")
            return
        try:
            img = _grab_read_only(ca.ADB, test_acct[0] if test_acct else found[0][0])
            role, rank = ca.read_game_identity(img, assets)
            print(f"    OCR 游戏内身份：role={role!r} rank={rank!r}")
        except Exception as exc:  # noqa: BLE001
            skip("只读 OCR 主角色/RANK", f"截图/OCR 不可用：{exc!r}")


def _pick_assets() -> Path | None:
    """选一个带 OCR 模型（det.onnx）的 assets 目录：本工作树优先，其次主工作树。"""
    cands: list[Path] = []
    env = os.environ.get("WF_H31_ASSETS")
    if env:
        cands.append(Path(env))
    cands.append(REPO_ROOT / "assets" / "resource")
    cands.append(Path(__file__).resolve().parents[1] / "assets" / "resource")
    for c in cands:
        if (c / "model" / "ocr" / "det.onnx").is_file():
            return c
    return None


def _grab_read_only(adb: str, serial: str):
    """只读截图（exec-out screencap），返回 720 空间 BGR ndarray。不发送任何输入。"""
    import numpy as np
    from PIL import Image

    proc = subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("screencap 失败")
    import io

    pil = Image.open(io.BytesIO(proc.stdout)).convert("RGB")
    if pil.size != (720, 1280):
        pil = pil.resize((720, 1280))
    return np.ascontiguousarray(np.array(pil)[:, :, ::-1])


# ---------------------------------------------------------------------------
# 6. 挂点 + prove-red
# ---------------------------------------------------------------------------
def test_hooks_and_prove_red() -> None:
    print("\n== 6. 挂点点亮 + prove-red ==")
    check("挂点 addr-discovery-no-hardcoded-port 已点亮", hooks_40.probe_no_hardcoded_port() is True)
    check("挂点 addr-discovery-single-source 已点亮", hooks_40.probe_single_source() is True)
    check("挂点 addr-discovery-identity-guard 已点亮", hooks_40.probe_identity_guard() is True)
    check("hooks_40.prove_red() 成立（无端口/单源/守卫各自变红）", hooks_40.prove_red() is True)


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 72)
    print("离线单测：#40 设备端口漂移 -> 按账号身份发现 + 连接身份守卫")
    print("=" * 72)
    test_identity_match()
    test_read_identity_offline()
    test_read_game_identity_offline()
    test_resolve_address()
    test_connect_identity_guard()
    test_live_discovery_demo()
    test_hooks_and_prove_red()
    print("\n" + "=" * 72)
    if SKIPS:
        print(f"跳过 {len(SKIPS)} 项（best-effort，不算失败）：{SKIPS}")
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
