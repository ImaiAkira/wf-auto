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

    # ★#86★ 静音模式：GUI 里只留「要打几次 / 第几次 / 收工原因」，机制日志写 debug/wuchong_agent.log。
    #   由 assets/interface.json 的 agent.child_args 传入（离线守卫/真机 runner 不传，保持可观测）。
    if "--quiet" in sys.argv:
        try:
            import wuchong_impl

            wuchong_impl.set_quiet(True)
        except Exception as exc:  # noqa: BLE001 —— 静音失败绝不影响启动
            print(f"[agent] --quiet 未生效：{exc!r}")

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
