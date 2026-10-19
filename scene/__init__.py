# -*- coding: utf-8 -*-
"""场景配置面（tickets #3 / #4 / #5 / #6 / #8）。

对外公开面，分四块：

* **配置数据**（#3）—— family 模板 / 成员 delta / 校验 / 页面判据 / 覆盖报告；
  领主战类的具体数据在 ``scene.lord_battle``。
* **链与导航**（#4）—— 页面锚定的链式拓扑 + ``decide`` / ``navigate``；
  含从「详情页」运行时读取可用难度档（ADR-0002）。
* **事件层**（#5 / #8）—— 异常组单独定义、统一幂等注入；**归位**是其中的通用事件；
  卡死兜底**不在**事件层（它是活性问题，见 ``WATCHDOG``）。
* **GUI 目标选项**（#6）—— 由配置派生并幂等注入，不再手写。
* **落盘机制**（#16）—— ``import scene.apply`` 使用（``apply`` / ``strip``）：把上面两块派生产物
  **幂等写进真实 JSON 并可逆**。**不在此处 re-export**：``apply`` 既是子模块名又是函数名，
  re-export 会让 ``scene.apply`` 变成函数，反而混淆。

ADR：0001 配置为真源（校验 + 幂等注入）/ 0002 目标声明式导航 / 0003 页面判据全局唯一。
"""

from __future__ import annotations

from .chain import (
    Chain,
    Node,
    Step,
    Target,
    Terminal,
    build_chain,
    found_difficulties,
    read_detail_difficulties,
    resolve_target,
    scene_page_selection,
    validate_chain,
    结算终点,
    终端pipeline节点,
)
from .config import (
    DIFFICULTIES,
    SUBFAMILIES,
    ConfigError,
    FamilyConfig,
    FamilyTemplate,
    MemberDelta,
    Override,
    assert_page_rules_globally_unique,
    derive_members,
    member,
    override_report,
    validate_config,
)
from .events import (
    EVENTS,
    EXCEPTION_EVENTS,
    RETURN_HOME,
    Event,
    inject_events,
    injection_report,
    is_event_free,
    strip_events,
    validate_events,
)
from .navigation import decide, navigate
from .drift import chain_drift, check_all, event_def_drift, event_injection_drift, option_drift, recognition_drift
from .options import (
    derive_option_block,
    derive_target_options,
    inject_option,
    verify_injection,
)
from .page_rules import (
    PAGE_RULES,
    PageRule,
    PageRuleRegistry,
    SceneSelection,
    chain_step_pages,
    default_registry,
    duplicate_rule_names,
    page_rule,
    page_rules,
    registered_scenes,
    scene_overrides,
    selection_for,
)

__all__ = [
    # 配置数据 (#3)
    "DIFFICULTIES",
    "SUBFAMILIES",
    "ConfigError",
    "FamilyConfig",
    "FamilyTemplate",
    "MemberDelta",
    "Override",
    "assert_page_rules_globally_unique",
    "derive_members",
    "member",
    "override_report",
    "validate_config",
    # 页面判据 (#3, ADR-0003)
    "PAGE_RULES",
    "PageRule",
    "PageRuleRegistry",
    "SceneSelection",
    "chain_step_pages",
    "default_registry",
    "duplicate_rule_names",
    "page_rule",
    "page_rules",
    "registered_scenes",
    "scene_overrides",
    "selection_for",
    # 链与导航 (#4, ADR-0002)
    "Chain",
    "Node",
    "Step",
    "Target",
    "Terminal",
    "build_chain",
    "found_difficulties",
    "read_detail_difficulties",
    "resolve_target",
    "scene_page_selection",
    "validate_chain",
    "结算终点",
    "终端pipeline节点",
    "decide",
    "navigate",
    # 事件层 (#5 / #8)
    "EVENTS",
    "EXCEPTION_EVENTS",
    "RETURN_HOME",
    "Event",
    "inject_events",
    "injection_report",
    "is_event_free",
    "strip_events",
    "validate_events",
    # GUI 目标选项 (#6)
    "derive_option_block",
    "derive_target_options",
    "inject_option",
    "verify_injection",
    # 漂移校验 (#7 / #10, ADR-0001 的「校验」职责)
    "check_all",
    "option_drift",
    "recognition_drift",
    "event_def_drift",
    "event_injection_drift",
    "chain_drift",
]
