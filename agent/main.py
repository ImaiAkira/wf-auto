import sys

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

import my_action
import my_reco


def main():
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    # ★#86★ 静音模式：GUI 里只留「进度行 / 收工原因」，机制日志写 debug/agent.log。
    #   由 assets/interface.json 的 agent.child_args 传入（离线守卫/真机 runner 不传，保持可观测）。
    # ★#142★ 静音现在是**一次 stdout 重定向**（:mod:`reporting`），所以深渊 / 幻想 / 领主战 /
    #   外传里既有的 print(...) 也自动归入机制日志 —— 不再是「只有五重听话」。
    if "--quiet" in sys.argv:
        try:
            import reporting

            if not reporting.set_quiet(True):
                print("[agent] --quiet 未生效：日志文件打不开（见上一条）")
        except Exception as exc:  # noqa: BLE001 —— 静音失败绝不影响启动
            print(f"[agent] --quiet 未生效：{exc!r}")
        # 五重自己那份「机制日志进 debug/wuchong_agent.log」的闩锁照旧保留（#86 的既有契约）。
        try:
            import wuchong_impl

            wuchong_impl.set_quiet(True)
        except Exception as exc:  # noqa: BLE001 —— 静音失败绝不影响启动
            print(f"[agent] --quiet 未生效（五重）：{exc!r}")

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
