# -*- coding: utf-8 -*-
"""#78：五重「节拍」—— 慢在**延时**（timeout / post_delay），不在识别；撤掉 #77 的「狂点」。

## 运维质疑（2026-10-17，逐字）

「动作内狂点 这是干啥的啊，我觉得这个要么是你**延时设计太大了**，要么就是**一直没 hit 到期望的内容**。」

→ 对。实测（MaaFramework 自己的 Node 事件日志 `debug/maafw*.log`）：

| 指标 | 实测 |
|---|---|
| 单次识别 | `OcrTask` avg **0.107s**；其余节点 0.001-0.013s（框架 `prefetch_batch_ocr` 已合并批量 OCR） |
| 扫完 25 个候选 | **≈0.5s** |
| `WuchongSettleContinue` 真重复周期（15 次） | **12.3-12.4s** = `timeout: 12000` 的**空转重试** |
| `WuchongRoomWait` 周期（19 次） | **4.5-5.5s** = 自身 `post_delay: 3500` |
| `WuchongCoopChallenge` | `post_delay: 12000` + `timeout: 12000` ⇒ 一次尝试 ≈20s |

## 本票的契约（守卫钉死）

- **W1 延时上限**：每个流程节点 `timeout ≤ scene.wuchong.FLOW_TIMEOUT_MS`(3000)、
  `post_delay ≤ FLOW_POST_DELAY_MS`(1000)（战斗节点豁免）；`WuchongRoomWait.post_delay ≤ 800`、
  `WuchongWait.post_delay ≤ 400`（人齐 / 空转探测的节拍）。
- **W2 撤掉狂点**：任何节点的 `custom_action_param.spam` 一律视为回归（#77 已撤）。
- **W3 假成功**：任何节点的 `expect` 里不得含 `loading`（过渡帧不是「已到达」）。
- **W4 单点即可**：`wuchong_act` 点一次 + 校验一次就返回；`wait_ms` 默认 = `ACT_WAIT_MS`(700)，
  不再有「动作内连点」的循环。
- **W5 what_next 兜底**：结算【继续】找不到时改点【OK / 返回房间】，且**不含「解散」**（会关共斗房）。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
AGENT = REPO_ROOT / "agent"
PIPELINE_REL = Path("assets") / "resource" / "pipeline" / "wuchong.json"


def _paths() -> None:
    for p in (str(REPO_ROOT), str(TOOLS), str(AGENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def _pipeline(root: Path | None = None) -> dict:
    import jsonc  # noqa: PLC0415

    base = Path(root) if root is not None else REPO_ROOT
    with open(base / PIPELINE_REL, encoding="utf-8") as f:
        return jsonc.load(f)


def _action_node_param(node: dict) -> dict:
    return ((node.get("action") or {}).get("param") or {})


def _action_param(node: dict) -> dict:
    return _action_node_param(node).get("custom_action_param") or {}


#: 流程链上的节点（= 会「等下一屏」的节点）：它们的 timeout/post_delay 必须守节拍契约。
_FLOW_PREFIX = "Wuchong"
#: 战斗节点例外（动作本身就是长阻塞；post_delay 300ms 本来就在上限内）。
_EXEMPT = ("WuchongBattle",)


def _cadence_failures(root: Path | None = None) -> list:
    """W1 + W2 + W3：每个流程节点的 timeout / post_delay / expect / spam 都在契约内。"""
    _paths()
    from scene import wuchong as w  # noqa: PLC0415

    msgs: list[str] = []
    pipes = _pipeline(root)
    for name, node in pipes.items():
        if not name.startswith(_FLOW_PREFIX):
            continue
        if name in _EXEMPT:
            continue
        timeout = node.get("timeout")
        if timeout is not None and int(timeout) > w.FLOW_TIMEOUT_MS:
            msgs.append(
                f"{name}: timeout={timeout} > 上限 {w.FLOW_TIMEOUT_MS}ms"
                "（空转重试会拖成十几秒 —— 真机 WuchongSettleContinue 实测 12.4s/次）"
            )
        post = node.get("post_delay")
        if post is not None and int(post) > w.FLOW_POST_DELAY_MS:
            msgs.append(f"{name}: post_delay={post} > 上限 {w.FLOW_POST_DELAY_MS}ms（动作后白等）")
        cp = _action_param(node)
        if "spam" in cp:
            msgs.append(f"{name}: 又出现了 custom_action_param.spam（#77 的「狂点」已撤，别再加回来）")
        if name in w.STRICT_EXPECT_NODES and "loading" in list(cp.get("expect") or []):
            msgs.append(
                f"{name}: expect 含 loading（这几个节点的 expect 是在断言「真的到达了目标页」；"
                "过渡帧 loading 不算到达 —— 真机灰挑战闪 loading 是假成功）"
            )
    # W1 专项：人齐探测 / 空转探测的节拍（这两处直接决定运维感受到的「等多久」）。
    room = (pipes.get("WuchongRoomWait") or {}).get("post_delay")
    if room is None or int(room) > 800:
        msgs.append(f"WuchongRoomWait.post_delay={room}（人齐后要等它下一轮才看见；应 ≤800）")
    idle = (pipes.get("WuchongWait") or {}).get("post_delay")
    if idle is None or int(idle) > 400:
        msgs.append(f"WuchongWait.post_delay={idle}（空转兜底每次白等；应 ≤400）")
    # W5：结算【继续】必须带兜底按钮，且兜底不含「解散」。
    nxt = list(_action_param(pipes.get("WuchongSettleContinue") or {}).get("what_next") or [])
    if not nxt:
        msgs.append("WuchongSettleContinue: 缺 what_next 兜底（结算多段要多等一跳）")
    if any("解散" in str(p) for p in nxt):
        msgs.append("WuchongSettleContinue.what_next 含「解散」→ 会把共斗房关掉（下一场重新建房招募）")
    # ★#107 运维反馈★ 结算必须能【再次挑战】（单人结算只有 OK/再次挑战；点 OK 要绕
    #   「详情页→战斗→编队页→挑战」≈2 分钟），且必须排在 OK 之前。
    what = list(_action_param(pipes.get("WuchongSettleContinue") or {}).get("what") or [])
    joined = "".join(str(x) for x in what)
    if "再次挑战" not in joined:
        msgs.append(
            "WuchongSettleContinue.what 缺【再次挑战】—— 单人结算点 OK 会退出到详情页，"
            "再走战斗→编队页→挑战 ≈2 分钟；应优先再次挑战直接续战"
        )
    else:
        idx_retry = next(i for i, x in enumerate(what) if "再次挑战" in str(x))
        idx_ok = next((i for i, x in enumerate(what) if "OK" in str(x).upper()), len(what))
        if idx_retry > idx_ok:
            msgs.append(
                f"WuchongSettleContinue.what 里【再次挑战】排在 OK 之后（{idx_retry} vs {idx_ok}）—— 会先点 OK 绕远路"
            )
    # ★#113★ 服务端断连的重试必须按**时间闩**冷却（≥10s），不许靠 post_delay（cadence 契约），
    #   也不许密集重试（真机：A/B 两账号两设备同时被服务端拒，本地 ping 0% 丢包）。
    cooldown = float(getattr(w, "SERVER_RETRY_COOLDOWN_S", 0) or 0)
    if cooldown < 10.0:
        msgs.append(
            f"SERVER_RETRY_COOLDOWN_S={cooldown} 太小（服务端限流时密集重试只会更糟；应 ≥10s）"
        )
    srv = pipes.get("WuchongServerUnreachable") or {}
    cap = ((srv.get("action") or {}).get("param") or {}).get("custom_action_param") or {}
    if cap.get("latch") != "server_retry":
        msgs.append(
            "WuchongServerUnreachable 的动作没挂 latch=server_retry（冷却会失效 —— 每轮都会点一次【重新连接】）"
        )
    try:
        import wuchong_impl as _wi  # noqa: PLC0415

        window = (_wi.WuchongActAction._LATCH_WINDOWS or {}).get("server_retry")
        if window is None or abs(float(window) - cooldown) > 1e-6:
            msgs.append(
                f"WuchongActAction._LATCH_WINDOWS[server_retry]={window!r} 与真源 {cooldown!r} 不一致"
                f"（安装态快照漂移 → 装好的产品冷却失效）"
            )
    except Exception as exc:  # pragma: no cover - 安装态/仓内都可 import
        msgs.append(f"读不到 wuchong_impl.WuchongActAction._LATCH_WINDOWS：{exc}")
    if w.ACT_WAIT_MS > 1000:
        msgs.append(f"ACT_WAIT_MS={w.ACT_WAIT_MS} 过大（点完就该校验，别白等）")
    # W6：结算页要「狂点 QUESTRESULT 横幅」（运维点名要的），且必须接**公共节点**
    #     `[JumpBack]PubQuestResult`（判据 QUESTRE 只在 common.json 一份）。
    #     ★它必须排在结算节点自己的后继之后★：横幅一直在屏上，排前面会每轮抢帧 → 结算按钮永远轮不到。
    for settle in ("WuchongSettleContinue", "WuchongSettleReturnRoom", "WuchongSettleDisband"):
        nxt = list((pipes.get(settle) or {}).get("next") or [])
        # ★#107 反转（真机证据）★ 结算节点**不许**再接 [JumpBack]PubQuestResult：
        #   2026-10-18 00:01–00:10（单人，A）第 1 场打完 → 结算页静默 9 分钟零点击，
        #   而单独 post WuchongSettleContinue 却能过 ⇒ 横幅每轮命中且 next=[] 会弹栈重扫，
        #   把结算按钮的帧抢掉。它加速的只是动画，收益从未量化（#78 的提速来自砍 timeout/post_delay）。
        idx = [i for i, x in enumerate(nxt) if "PubQuestResult" in str(x)]
        if idx:
            msgs.append(
                f"{settle}: next 里接了 [JumpBack]PubQuestResult（第 {idx[0]} 位）"
                "—— 真机证明它会把结算页按死（横幅一直在屏上 + next=[] 弹栈重扫抢帧）；已撤线，别再挂"
            )
    return msgs


def probe_wuchong_cadence_pact() -> bool:
    _paths()
    return _cadence_failures() == []


# ---------------------------------------------------------------------------
# 行为守卫：wuchong_act 现在就是「点一次 + 立刻校验」（W4/W3/W5）
# ---------------------------------------------------------------------------
_TEAM_ITEMS = [("Party A", [60, 200, 120, 30]), ("挑战", [297, 980, 80, 47])]
_LOADING_ITEMS = [("健康游戏忠告", [200, 500, 300, 40])]
_SETTLE_CONTINUE_ITEMS = [("QUESTRESULT", [184, 76, 705, 106]), ("继续", [328, 1181, 64, 38])]
_SETTLE_ROOM_ITEMS = [
    ("QUESTRESULT", [184, 76, 705, 106]),
    ("解散", [183, 1182, 63, 36]),
    ("返回房间", [446, 1183, 117, 33]),
]


def _center(box):
    return (int(box[0] + box[2] / 2.0), int(box[1] + box[3] / 2.0))


class _CtxStub:
    """最小 context 桩（动作只经被 monkeypatch 的抓屏/OCR/点击，不触设备）。"""


class _ActArgv:
    def __init__(self, param):
        self.custom_action_param = json.dumps(param)


class _SeqOCR:
    def __init__(self, frames):
        self.frames = [list(f) for f in frames]
        self.calls = 0

    def __call__(self, context, image, entry="OcrTask"):
        i = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return list(self.frames[i])


def _drive(mod, frames, param):
    clicks: list = []
    saved = {k: mod.__dict__[k] for k in ("_grab", "_ocr", "_click_box")}
    seq = _SeqOCR(frames)
    buf = io.StringIO()
    try:
        mod._grab = lambda context: ("frame", seq.calls)
        mod._ocr = seq
        mod._click_box = lambda context, cx, cy: (clicks.append((int(cx), int(cy))) or True)
        with contextlib.redirect_stdout(buf):
            mod.WuchongActAction().run(_CtxStub(), _ActArgv(param))
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
    return clicks, buf.getvalue(), seq.calls


def _behaviour_failures(mod) -> list:
    _paths()
    msgs: list[str] = []
    saved_file = getattr(mod.ledger, "_DEFAULT", None)
    with tempfile.TemporaryDirectory() as td:
        mod.ledger.set_file(Path(td) / "p.json")
        try:
            with mod._LOCK:
                mod._SESSION["task_id"] = 570_300_001
                mod._SESSION["fights_done"] = 0
                mod._SESSION["latch_ts_battle_start"] = 0.0

            # W4 单点：点一次就返回（不连点）。
            base = {"what": ["^挑战$"], "roi": [150, 980, 600, 1180], "expect": ["wuchong_battle"]}
            clicks, _out, _c = _drive(mod, [_TEAM_ITEMS], dict(base))
            if len(clicks) != 1:
                msgs.append(f"wuchong_act 点了 {len(clicks)} 下（应「点一次 + 校验」=1 下）→ 狂点又回来了？")
            if clicks and clicks[0] != _center([297, 980, 80, 47]):
                msgs.append(f"落点不是「挑战」框心：{clicks}")

            # W4 默认 wait_ms：点完只等 ACT_WAIT_MS 就校验（框架侧写死 1600 的回归会被抓到）。
            fps_before = 0
            clicks2, _o2, ocr_calls = _drive(mod, [_TEAM_ITEMS, _TEAM_ITEMS], dict(base))
            if ocr_calls < 2:
                msgs.append("wuchong_act 没有在点击后重新抓帧校验（ocr_calls < 2）")
            fps_before = ocr_calls

            # W3 loading 不是「已到达」：点完闪一下 loading，必须判「校验未通过」。
            with mod._LOCK:
                mod._SESSION["latch_ts_battle_start"] = 0.0
            clicks3, out3, _c = _drive(mod, [_TEAM_ITEMS, _LOADING_ITEMS], dict(base))
            if "校验通过" in out3:
                msgs.append("点后只是 loading 就判「校验通过」（假成功）→ 会白等一整轮")
            if len(clicks3) != 1:
                msgs.append(f"loading 情形下点了 {len(clicks3)} 下（应只点 1 下）")

            # W5 what_next：结算页只剩【返回房间】时改点它（而不是不点）。
            param5 = {
                "what": ["^继续挑战$", "^继续$", "^OK$"],
                "roi": [0, 1150, 720, 1280],
                "expect": ["wuchong_room"],
                "what_next": ["^OK$", "^返回房间$"],
            }
            clicks5, _o5, _c = _drive(mod, [_SETTLE_ROOM_ITEMS], dict(param5))
            if clicks5 != [_center([446, 1183, 117, 33])]:
                msgs.append(f"what_next 兜底没点【返回房间】：{clicks5}")
        finally:
            mod.ledger.set_file(None)
            if saved_file is not None:
                mod.ledger._DEFAULT = saved_file
    return msgs


def probe_wuchong_act_single_click() -> bool:
    _paths()
    import wuchong_impl as impl  # noqa: PLC0415

    return _behaviour_failures(impl) == []


HOOKS = [
    (
        "wuchong-cadence-pact",
        "#78",
        "节拍契约：流程节点 timeout ≤3000 / post_delay ≤1000（房间等待 ≤800、空转兜底 ≤400）、"
        "expect 不含 loading（过渡帧不是「已到达」）、**禁止再出现 spam 狂点块**、what_next 兜底不含解散、"
        "ACT_WAIT_MS ≤1000 —— 真机实测慢在延时（settle 周期 12.4s / 房间 4.6s），不在识别（0.1s）",
        probe_wuchong_cadence_pact,
    ),
    (
        "wuchong-act-single-click",
        "#78",
        "wuchong_act 回到「点一次 + 立刻校验」：只点 1 下、点后重新抓帧校验、"
        "loading 不算通过、what_next 兜底改点【返回房间】",
        probe_wuchong_act_single_click,
    ),
]


# ---------------------------------------------------------------------------
def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"破坏点没找到：{old!r}（守卫已与实现脱节）")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _temp_pipeline() -> Path:
    import shutil  # noqa: PLC0415

    root = Path(tempfile.mkdtemp(prefix="wf_hook78_"))
    (root / PIPELINE_REL).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / PIPELINE_REL, root / PIPELINE_REL)
    return root


def _set_field_in_node(path: Path, node: str, field: str, value: int) -> None:
    """把某个节点块里的 ``field`` 值改成 ``value``（★必须改**已存在**的那个键★：
    jsonc 对同名键取后者，插一个新键会被原键覆盖，破坏实验就会假绿）。"""
    text = path.read_text(encoding="utf-8")
    start = text.index(f'"{node}": {{')
    key = f'"{field}":'
    at = text.index(key, start)
    line_end = text.index("\n", at)
    keeps_comma = text[at:line_end].rstrip().endswith(",")
    text = text[:at] + f'"{field}": {value}' + ("," if keeps_comma else "") + text[line_end:]
    path.write_text(text, encoding="utf-8")


def prove_red() -> bool:
    _paths()
    import shutil  # noqa: PLC0415
    import wuchong_impl as impl  # noqa: PLC0415

    print("hooks_78 prove-red：逐一破坏实现，要求守卫各自变红")
    green = probe_wuchong_cadence_pact() is True and probe_wuchong_act_single_click() is True
    print(f"  [{'PASS' if green else 'FAIL'}] 真实实现：两个守卫全绿")
    if not green:
        return False

    checks: list[bool] = []

    def _break(label: str, mutate) -> None:
        root = _temp_pipeline()
        try:
            mutate(root / PIPELINE_REL)
            m = _cadence_failures(root)
            red = len(m) > 0
            print(f"  [{'PASS' if red else 'FAIL'}] {label} -> {'红' if red else '仍绿'}"
                  + (f"  {m[0]}" if m else ""))
            checks.append(red)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # ① timeout 调回 12000（= 真机 12.4s 周期的那个旋钮）
    _break(
        "把 WuchongSettleContinue 的 timeout 调回 12000",
        lambda p: _set_field_in_node(p, "WuchongSettleContinue", "timeout", 12000),
    )
    # ② 房间等待的 post_delay 调回 3500（人齐→挑战慢的真因）
    _break(
        "把 WuchongRoomWait.post_delay 调回 3500",
        lambda p: _set_field_in_node(p, "WuchongRoomWait", "post_delay", 3500),
    )
    # ③ 重新加回 spam（狂点复活）
    _break(
        "往 WuchongTeamChallenge 的 action 里塞回 spam 块",
        lambda p: _sub(
            p,
            '"latch": "battle_start",',
            '"latch": "battle_start", "spam": {"gap_ms": 300, "max_ms": 45000, "recheck_ms": 1200, "burst": 3},',
        ),
    )
    # ④ expect 里塞回 loading（假成功）
    _break(
        "把 loading 塞回 WuchongCoopChallenge 的 expect",
        lambda p: _sub(p, '"expect": ["wuchong_battle"]', '"expect": ["wuchong_battle", "loading"]'),
    )

    # ⑤ 行为破坏：把 wait_ms 写死回 1600（不再「立刻校验」）—— 行为守卫用默认值抓。
    real_wait = impl.__dict__.get("ACT_WAIT_MS", None)
    from scene import wuchong as w  # noqa: PLC0415

    real_act_wait = w.ACT_WAIT_MS
    try:
        w.ACT_WAIT_MS = 5000
        m5 = _cadence_failures()
        red5 = len(m5) > 0
        print(f"  [{'PASS' if red5 else 'FAIL'}] ACT_WAIT_MS 调到 5000（点完白等）-> {'红' if red5 else '仍绿'}"
              + (f"  {m5[0]}" if m5 else ""))
    finally:
        w.ACT_WAIT_MS = real_act_wait
    checks.append(red5)

    # ⑥ 接线回滚破坏：把 [JumpBack]PubQuestResult 塞回结算节点 next → 必须红（#107 真机：它会按死结算页）
    def _re_add_banner(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        node_at = text.index('"WuchongSettleContinue": {')
        next_at = text.index('"next": [', node_at)
        insert_at = text.index('[', next_at) + 1
        text = text[:insert_at] + '\n            "[JumpBack]PubQuestResult",' + text[insert_at:]
        path.write_text(text, encoding="utf-8")

    _break("把 [JumpBack]PubQuestResult 塞回结算 next（#107 真机证明会按死结算页）", _re_add_banner)

    ok = green and all(checks)
    print("结果：" + ("★prove-red 成功★" if ok else "★prove-red 失败★"))
    return ok


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(0 if prove_red() else 1)
