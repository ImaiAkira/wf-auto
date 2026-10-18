# -*- coding: utf-8 -*-
"""离线定向测试（#114）：连不上服务器时自动重启客户端。

不需要游戏 / 设备。判据全部落在真机帧 OCR 文本 + ``scene.wuchong`` 数据 + pipeline 结构 +
真实自定义识别器（``WuchongNetGuardRecognition``）的离线驱动上。直接跑：

    .venv\\Scripts\\python.exe tools\\test_wuchong_net_restart.py
    .venv\\Scripts\\python.exe tools\\test_wuchong_net_restart.py --prove-red

覆盖 #114 的验收：

  1. **三种文案一份判据**：F2032 / A4050 / 暂时无法连接的文案表唯一真源在
     ``scene.wuchong.NET_DISCONNECT_TEXTS``；三张真机证据帧各自只命中自己，正常主城/战斗帧
     一个都不命中；pipeline 三个断连节点都走 ``wuchong_net``（不各写一份 OCR 列表）。
  2. **有界重启**：单次断连先按 ``SERVER_RETRY_COOLDOWN_S``=10s 冷却重试一次；仍失败 ⇒
     ``WuchongNetGuard`` 用 ``restart_game`` 重启客户端（等待 ``RELAUNCH_WAIT_SEC``=45s）；
     注入 4 次断连 ⇒ 前 3 次各重启一次，第 4 次由 ``WuchongGiveUp`` 带原因收工
     （``客户端重启 3 次仍连不上服务器（F2032/A4050/暂时无法连接）—— 带原因收工``）。
  3. **重启后必须过继续游戏**：重启动作 ``next=WuchongEntry``；枢纽保留
     ``WuchongResumeQuest`` / ``PubLoginContinue`` / ``PubTitleStart``；「有正在进行中的关卡」
     帧不得被 ``wuchong_net`` 当成断连。
  4. **冷却仍承重**：假时钟 t=0/5/9.9 只放行 retry、不重启；t=10 才允许重启；三个重试节点
     都挂 ``latch=server_retry``。

``--prove-red``：四处破坏（去掉上限 / 把重启换成点重试 / 重启后不走继续游戏 / 绕过冷却），
要求守卫各自变红（见 hooks_114.prove_red）。

★诚实边界★：本文件是**离线**部分。真机「断连后真的 force-stop + 拉起客户端并回到主城」
未在本机运行（无设备），如实标注，不转述式声称已验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = TOOLS_DIR / "contract_hooks"
for _p in (str(REPO_ROOT), str(TOOLS_DIR), str(HOOKS_DIR), str(REPO_ROOT / "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import hooks_114 as H  # noqa: E402
from scene import wuchong as W  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    print("=" * 78)
    print("五重断连（#114）：F2032/A4050/暂时无法连接 → 冷却重试 → 有界重启客户端 → 继续游戏")
    print("=" * 78)

    print("\n== 0. 策略常量（真源 scene.wuchong ②h）==")
    check("重启上限 = 3 次/任务", W.NET_RESTART_LIMIT == 3, f"{W.NET_RESTART_LIMIT}")
    check("重启等待 = 45s（真机 ≈40s 才回登录成功）", W.RELAUNCH_WAIT_SEC == 45.0,
          f"{W.RELAUNCH_WAIT_SEC}")
    check("重试冷却 = 10s（沿用 #113）", W.SERVER_RETRY_COOLDOWN_S == 10.0,
          f"{W.SERVER_RETRY_COOLDOWN_S}")
    check("三种文案种类齐全且互异",
          tuple(W.NET_DISCONNECT_KINDS) == ("F2032", "A4050", "UNREACHABLE"),
          f"{W.NET_DISCONNECT_KINDS}")

    print("\n== 1. 三种文案一份判据 + 互不混淆 ==")
    check("证据帧各自只命中自己 / 正常主城·战斗帧不命中 / 三节点都走 wuchong_net",
          H.probe_wuchong_net_texts_shared() is True)

    print("\n== 2. 有界重启（注入 4 次断连，第 3 次后收工）==")
    check("前 3 次各重启一次；第 4 次 WuchongGiveUp 带原因收工（原因含次数与三种文案）",
          H.probe_wuchong_net_restart_bounded() is True)

    print("\n== 3. 重启后必须过「继续游戏 / 点击开始 / 有正在进行中的关卡」==")
    check("WuchongNetGuard.next=WuchongEntry；恢复引用齐全；恢复帧不被误判为断连",
          H.probe_wuchong_net_restart_resumes_game() is True)

    print("\n== 4. 断连重试仍受 SERVER_RETRY_COOLDOWN_S 冷却约束 ==")
    check("t=0/5/9.9 只放行 retry、不重启；t=10 才重启；三个重试节点都挂 latch=server_retry",
          H.probe_wuchong_net_cooldown_preserved() is True)

    print("\n" + "=" * 78)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    if "--prove-red" in sys.argv[1:]:
        sys.exit(0 if H.prove_red() else 1)
    sys.exit(main())
