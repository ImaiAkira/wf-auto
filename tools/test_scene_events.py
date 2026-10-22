# -*- coding: utf-8 -*-
"""离线单测：跨场景通用【事件】层（异常组 #5 + 归位 #8）。

不需要游戏、不需要 maa 运行时，直接跑：

    .venv\\Scripts\\python.exe tools\\test_scene_events.py

覆盖两条验收：

  #5 异常组单独定义 + 幂等注入
    1. 九类跨场景情况在一处定义；链的形状里看不到它们；
    2. 对同一份 JSON 连续注入两次，字节完全不变；
    3. 事件排在原有后继之前，剥壳能还原链的形状；
    4. 卡死兜底仍在事件层之外，作为独立看门狗。

  #8 归位提升为通用事件
    5. 归位出现在注入的异常组里；
    6. 归位可从任意已知页面在一步之内触发；
    7. 链尾不再各自实现回主城（链的形状里没有归位），且归位是单步事件。

再加一段构造证明（不改任何文件）：把注入改成非幂等 / 把归位从注入组拿掉，
本测试所用的判据必须当场变红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scene.events import (  # noqa: E402
    EVENTS,
    EXCEPTION_EVENT_NAMES,
    EXCEPTION_EVENTS,
    FALLBACK_EVENTS,
    FALLBACK_KIND,
    INTERRUPT_EVENTS,
    INTERRUPT_KIND,
    RETURN_HOME,
    RETURN_HOME_NODE_NAME,
    WATCHDOG_NODE_NAME,
    event_refs,
    exception_event_names,
    fallback_refs,
    inject_events,
    interrupt_refs,
    is_event_free,
    known_pages,
    return_home_ref,
    strip_events,
    validate_events,
    watchdog_in_event_layer,
)

FAILS = []

# 本票枚举的九类跨场景情况（照抄 ticket #5 的括号清单）。
EXPECTED_NINE = ["加载", "结算", "换日", "等级", "新角色", "剧情", "挑战", "加成弹窗", "招募"]


def check(name: str, cond: bool, extra: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def _bytes(x: object) -> bytes:
    """对同一份结构做「字节」比较（ADR-0001：重跑不改字节）。"""
    return json.dumps(x, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


# 探针链末位的 DirectHit「恢复边/终点」（与真实 pipeline 的 SpecialEntry/SpecialWait 同型）：
# 兜底型事件正是插在它【之前】（插在其后会被 DirectHit 恒命中遮蔽 = 死代码）。
_HUB = "ProbeHub"


def _chain(pages: list[str]) -> dict:
    """链的【形状】：每个节点锚在一个页面上，next = 显式后继 + DirectHit 终点。"""
    n = len(pages)
    chain = {
        p: {
            "recognition": {"type": "OCR", "param": {"expected": [p]}},
            "next": ([pages[i + 1], _HUB] if i + 1 < n else [_HUB]),
        }
        for i, p in enumerate(pages)
    }
    chain[_HUB] = {
        "recognition": {"type": "DirectHit", "param": {}},
        "action": {"type": "DoNothing", "param": {}},
        "next": [],
    }
    return chain


def test_nine_defined_in_one_place() -> None:
    print("\n== 1. 九类异常在一处定义；链的形状里看不到它们 ==")
    check("异常事件恰 9 条", len(EXCEPTION_EVENTS) == 9, f"got={len(EXCEPTION_EVENTS)}")
    check("命名集合 = 票 #5 枚举", sorted(exception_event_names()) == sorted(EXPECTED_NINE),
          f"got={list(exception_event_names())}")
    check("EXCEPTION_EVENT_NAMES 与之一致", set(EXCEPTION_EVENT_NAMES) == set(EXPECTED_NINE))
    check("事件层校验通过", validate_events() == [], f"errors={validate_events()}")

    chain = _chain(list(known_pages()))
    check("链的形状里看不到事件（is_event_free）", is_event_free(chain))
    check("链的 next 里没有任何事件引用",
          all("[JumpBack]" not in x for spec in chain.values() for x in spec["next"]))

    # 不臆造：九类异常只【引用】既有公共节点，节点名必须真的出现在 pipeline 里。
    pipeline_text = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (REPO_ROOT / "assets" / "resource" / "pipeline").glob("*.json")
    )
    missing = [n for e in EXCEPTION_EVENTS for n in e.nodes if n not in pipeline_text]
    check("九类异常的节点都是既有公共节点（非臆造）", missing == [], f"missing={missing}")


def test_injection_idempotent() -> None:
    print("\n== 2. 对同一份 JSON 连续注入两次，字节完全不变 ==")
    pages = list(known_pages())
    chain = _chain(pages)

    refs = event_refs()
    check("注入引用非空（不是空转）", refs != [], f"refs={refs}")

    once = inject_events(chain, flow_nodes=pages)
    twice = inject_events(once, flow_nodes=pages)
    check("注入确有发生（首轮 next 变长）", once[pages[0]]["next"] != chain[pages[0]]["next"])
    check("连续两次注入字节完全一致", _bytes(once) == _bytes(twice))
    check("幂等性对『注入后对象』再注入也成立",
          _bytes(inject_events(twice, flow_nodes=pages)) == _bytes(twice))


def test_events_ahead_of_successor_and_shape_preserved() -> None:
    print("\n== 3. 两类事件位置相反（#18）；剥壳还原链的形状 ==")
    pages = list(known_pages())
    chain = _chain(pages)
    prefix = list(interrupt_refs())
    suffix = list(fallback_refs())
    once = inject_events(chain, flow_nodes=pages)

    def canonical(entries: list) -> list:
        body = [x for x in entries if x not in set(prefix) | set(suffix)]
        return [*prefix, *body[:-1], *suffix, *body[-1:]] if body else [*prefix, *suffix]

    ok_order = all(once[p]["next"] == canonical(chain[p]["next"]) for p in pages)
    check("每个流程节点：打断型前缀在前 + 兜底型后缀在末位终点之前", ok_order,
          f"example={once[pages[0]]['next']}")
    # 兜底型（归位）确实排在显式后继【之后】（不是前缀）；只看确有显式后继的节点。
    with_succ = [p for p in pages if len(chain[p]["next"]) > 1]
    after_successor = all(
        once[p]["next"].index(return_home_ref()) > once[p]["next"].index(chain[p]["next"][0])
        for p in with_succ
    )
    check("归位排在显式后继之后（不是前缀）", after_successor and bool(with_succ))
    check("剥壳后回到链的形状（注入只加壳）", strip_events(once) == chain)
    check("剥壳结果事件免入", is_event_free(strip_events(once)))


def test_watchdog_stays_out() -> None:
    print("\n== 4. 卡死兜底仍在事件层之外，作为独立看门狗 ==")
    check("看门狗不在事件层（watchdog_in_event_layer=False）", watchdog_in_event_layer() is False)
    check("看门狗节点名不出现在任何事件的节点里",
          all(WATCHDOG_NODE_NAME not in e.nodes for e in EVENTS))
    check("看门狗节点名不出现在注入引用里",
          WATCHDOG_NODE_NAME not in "".join(event_refs()))
    check("看门狗是独立声明（名字非空且不是事件名）",
          bool(WATCHDOG_NODE_NAME) and WATCHDOG_NODE_NAME not in set(EXCEPTION_EVENT_NAMES))


def test_return_home_is_injected_group() -> None:
    print("\n== 5. 归位出现在注入组里，且是【兜底型】（#8 / #18） ==")
    home = return_home_ref()
    check("归位是事件层里的一个事件", RETURN_HOME.name == "归位")
    check("归位在 EVENTS（注入组）里", RETURN_HOME.name in [e.name for e in EVENTS])
    check("归位引用出现在 event_refs() 里", home in event_refs())
    check("归位是单步事件（一个节点）", len(RETURN_HOME.nodes) == 1,
          f"nodes={RETURN_HOME.nodes}")
    # #18 两类：九类异常是打断型（前缀），归位是兜底型（后缀）。
    check("九类异常都是打断型（kind=interrupt）",
          all(e.kind == INTERRUPT_KIND for e in INTERRUPT_EVENTS))
    check("归位是兜底型（kind=fallback）", RETURN_HOME.kind == FALLBACK_KIND)
    check("FALLBACK_EVENTS == (归位,)", tuple(e.name for e in FALLBACK_EVENTS) == ("归位",))
    check("归位引用只在兜底型后缀里（不在打断型前缀里）",
          home in fallback_refs() and home not in interrupt_refs())


def test_return_home_one_step_from_every_page() -> None:
    print("\n== 6. 归位可从任意已知页面在一步之内触发 ==")
    pages = list(known_pages())
    check("已知页面非空（来自全局判据注册表）", pages != [], f"pages={pages}")
    home = return_home_ref()
    injected = inject_events(_chain(pages), flow_nodes=pages)
    missing = [p for p in pages if home not in injected[p]["next"]]
    check("每个已知页面的候选集里都有归位（一步之内）", missing == [], f"missing={missing}")


def test_chain_tail_no_longer_owns_return_home() -> None:
    print("\n== 7. 链尾不再各自实现回主城（链形状里没有归位） ==")
    pages = list(known_pages())
    chain = _chain(pages)
    check("链的形状里没有归位节点", RETURN_HOME_NODE_NAME not in chain)
    check("链的形状事件免入（含归位引用）", is_event_free(chain))
    # 归位是【注入】带来的：注入前不在、注入后才在。
    check("归位节点由注入带来（注入前无、注入后有）",
          RETURN_HOME_NODE_NAME not in chain and RETURN_HOME_NODE_NAME in inject_events(chain, flow_nodes=pages))


def test_constructed_proof_of_red() -> None:
    print("\n== 8. 构造证明：把注入改坏 / 把归位拿掉，判据必须变红 ==")
    pages = list(known_pages())
    chain = _chain(pages)
    refs = event_refs()

    # (a) 非幂等注入（模拟「原样保留已有引用」的破坏）→ 字节比较必须抓到。
    def inject_naive(nodes: dict) -> dict:
        out = dict(nodes)
        for p in pages:
            out[p] = dict(out[p])
            out[p]["next"] = [*refs, *(out[p]["next"])]
        return out

    n1 = inject_naive(chain)
    n2 = inject_naive(n1)
    check("非幂等注入会被『字节一致』判据抓到", _bytes(n1) != _bytes(n2))
    check("真实注入不会被误判为红", _bytes(inject_events(chain, flow_nodes=pages))
          == _bytes(inject_events(inject_events(chain, flow_nodes=pages), flow_nodes=pages)))

    # (b) 把归位从注入组拿掉 → 归位判定必须变红。
    without_home = tuple(e for e in EVENTS if e.name != "归位")
    check("拿掉归位后：归位引用不在注入组里", return_home_ref() not in event_refs(without_home))
    injected_no_home = inject_events(chain, flow_nodes=pages, events=without_home)
    check("拿掉归位后：页面候选集里没有归位",
          all(return_home_ref() not in injected_no_home[p]["next"] for p in pages))


def main() -> None:
    print("=" * 70)
    print("离线单测：跨场景通用事件层（scene.events —— #5 异常组 / #8 归位）")
    print("=" * 70)
    test_nine_defined_in_one_place()
    test_injection_idempotent()
    test_events_ahead_of_successor_and_shape_preserved()
    test_watchdog_stays_out()
    test_return_home_is_injected_group()
    test_return_home_one_step_from_every_page()
    test_chain_tail_no_longer_owns_return_home()
    test_constructed_proof_of_red()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"结果：{len(FAILS)} 项失败 -> {FAILS}")
        sys.exit(1)
    print("结果：全部通过 ✅")


if __name__ == "__main__":
    main()
