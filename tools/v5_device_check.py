"""V5（型号不敏感）的无副作用现场检查。

只读：只做 adb 的 `getprop` / `wm size` / `dumpsys` 这类读取，**不点击、不启动游戏、不改游戏状态**。
它验证的是 #130 的语义——而不是「跑一次任务」：

1. `WF_LIVE_EXPECT_*` 全不设时，`expected_identity()` 是**空身份**（不校验）；
2. 多台设备在线时，`resolve_address()` 报的是「**地址不唯一**」，**不是**「型号不匹配」；
3. 指定地址后，身份只被**记录**（日志打 `(未校验)`），不会被拒。

用法（项目根目录）：
    .venv\\Scripts\\python.exe tools\\v5_device_check.py [--address 127.0.0.1:16384]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_harness as ca  # noqa: E402
from portable_paths import find_adb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--address", default=None, help="不给就走地址发现")
    args = ap.parse_args()

    # 关键：把三个期望变量**全部**清掉，模拟用户什么都不设。
    for k in ("WF_LIVE_EXPECT_MODEL", "WF_LIVE_EXPECT_PRODUCT", "WF_LIVE_EXPECT_DEVICE"):
        os.environ.pop(k, None)
    os.environ.pop("WF_LIVE_ADDRESS", None)

    ok = True

    # 1) 空身份 = 不校验
    exp = ca.expected_identity()
    constrained = exp.constrained()
    print(f"[1] expected_identity().constrained() = {constrained}  (期望 False)")
    if constrained:
        ok = False

    # 2) 地址发现：多台时应当报「不唯一」，不是拿型号筛
    addr = args.address
    if addr is None:
        try:
            addr = ca.resolve_address()
            print(f"[2] 地址发现 -> {addr}（只有一台在线，未用型号筛选）")
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # 真正的病是「拿型号当条件拒绝」——它的措辞是「没有在线设备匹配显式期望」。
            # 注意：报错里**提到**「型号」不算病（说明「默认不校验型号」时一定会提到）。
            bad = "没有在线设备匹配" in msg or "不匹配" in msg
            print(f"[2] 地址发现失败（多台在线，拒绝随机挑）：{msg}")
            print(f"    是不是拿型号当条件拒的：{bad}（期望 False）")
            if bad:
                ok = False
            # 报错不是我们要的结果；用参数重来一次，把第 3 步验完
            addr = None
    else:
        print(f"[2] 跳过发现（用了 --address {addr}）")

    if addr is None:
        print("[3] 跳过身份读取（没有可用地址）")
        return 0 if ok else 1

    # 3) 指定地址：身份只读、只记录，不校验
    os.environ["WF_LIVE_ADDRESS"] = addr
    adb = getattr(ca, "ADB", None) or find_adb()
    # read_display_size() 走模块级地址（#25 起不再硬编码），所以先登记一次。
    try:
        ca.connect_device(adb, addr)
    except Exception as e:  # noqa: BLE001
        print(f"[3] connect_device 警告：{e}")
    ident = ca.read_identity(adb, addr)
    print(f"[3] 读到身份：{ident.label()}")
    ca.log_device_identity(ident, exp)

    mm = ca.identity_mismatch(ident, exp)
    print(f"[3] identity_mismatch = {mm}  (期望 None：空期望不比较)")
    if mm is not None:
        ok = False

    size = ca.read_display_size()
    print(f"[3] read_display_size = {size}  (只读，不是断言)")
    if size:
        print(f"[3] device_scale = {ca.device_scale()}  （按 wm size 换算，不写死 1.5）")

    print("\nV5 现场检查：", "PASS" if ok else "FAIL")
    print("注意：这只证明「型号不构成硬门槛」；「跑一次任务仍绿」仍需要真跑。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
