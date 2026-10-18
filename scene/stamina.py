# -*- coding: utf-8 -*-
"""「体力不足 → 星导石恢复」场景配置【数据】—— 全项目唯一一处真源。

运维裁决（settled，逐字）
------------------------
「需要补的，因为**五重会消耗体力**。不过如果你在五重做过体力不够以后自动回复的逻辑，
就不需要了」；「**只用星岛石恢复**」。
⇒ 五重决战（单人/共斗「挑战」）、战阵之宴（「挑战」）、领主战族（详情页「战斗」）、深渊
连战EX/普通深渊（关卡条「挑战」）在开打时**都消耗体力**；体力不足时游戏弹出**回复体力
弹窗**（标题「回复体力/体力不足」，副标题「请选择要使用的道具」，选项：
体力回复药（小）/（中）/（大）/ ★星导石 × 50（回复 100 体力）★，底部红条「取消」）。
此前 pipeline **没有任何节点认它** → 流程停在该弹窗上空等，直到各场景自己的有界收工把它
停掉。★本层按裁决**只用星导石恢复**★：识别到弹窗即点「星导石 × 50」那一行，再在二次确认
框点 OK（这两步都真的扣星导石、体力 +100，随后关卡开打）。

真机证据（旧线 = ``<repo-旧线>``，战阵之宴「回复体力」弹窗；逐条 OCR 见本票 verify）
------------------------------------------------------------------------------------
来源帧（720 空间 OCR，1080 截图缩放）：

* **回复体力弹窗** ``…\\merge-to-main\\…\\debug\\on_error\\2026.10.08-00.08.14.450_RaidStaminaConfirm.png``
  与 ``…00.07.26.298_RaidStaminaCheck.png``：
  ``回复体力``[300,108,118,37] / ``请选择要使用的道具``[234,149,250,28] /
  ``体力回复药（小）``[209,500,207,32] / ``体力回复药（中）``[209,645,…] /
  ``体力回复药（大）``[210,789,…] / ★``星导石 × 50``[209,934,161,32]★ / ``取消``[326,1088,67,41]。
* **二次确认框** ``…\\debug\\on_error\\2026.10.08-00.08.55.775_RaidStaminaDone.png``：
  ``是否消耗星导石回复体力?``[191,486,322,28] / ``取消``[164,805,63,37] /
  ★``OK``[496,805,53,37]（中心 (522,823)）★。

旧线实现（作对照，**不照搬其架构**）：``merge-to-main/agent/raid_impl.py`` 的
``RaidStaminaRecognition``（自定义识别，读左上角体力「当前/上限」+ 阈值闸）+
``raid.json`` 的 ``RaidStaminaPickStar``（模板 ``RaidStaminaStar.png``）/``RaidStaminaConfirm``
（模板 ``RaidStaminaConfirm.png``）/``RaidStaminaDone``（模板 ``RaidStaminaDone.png``）/
``RaidStaminaCheck``。旧线用**模板匹配**且对 OK/取消用**固定坐标**（❌ 本项目红线：绝不
「识别框 + 死偏移」猜按钮）。二次确认那一步是**运维指出的漏项**（旧线 commit msg
``<repo-旧线>\\docs\\migration\\commit-msgs\\8-stamina-ok.txt``：「点完星导石图标之后【还要点 OK】
才真的恢复体力」；真机实测 星导石 2777605→2777555、体力 35→135、关卡直接开打）。

★恢复策略（本文件是【唯一真源】）★
----------------------------------
* **只用星导石恢复**（运维裁决）：恢复链 = 点「星导石 × 50」那一行 → 点二次确认框 OK →
  点「体力回复了！」结果窗 OK（第三态仅在该结果窗出现时命中 —— 真机A 第四跑
  实测它**确实**出现，见下「诚实边界」的历史更正）。
  **不定义免费道具路径**（「只用星岛石」= 不引入体力回复药分支）。
* ★第一步是**双通道**（#102 P0-1）★：行判据有两条 —— **图标模板**（``PubStaminaStoneRow`` =
  ``Or(图标模板, 行名 OCR)``，真源 ``scene/templates.py``）在前、**行名 OCR**（星导石 / 星岛石）
  在后。两条都是「点该行框中心」，语义完全相同；模板在前 ⇒ 每轮先给模板一次机会，不中才落到
  OCR。声明顺序见 :data:`RECOVERY_STEPS`（**本文件是唯一真源**，各枢纽 ``next`` 从
  :func:`recovery_refs()` 派生，逐项 pin 在 ``tools/contract_hooks/hooks_stamina.py``）。
* **读后动、点识别框自己的中心**：动作节点用 ``And(弹窗, 该行/该按钮) + box_index=1`` →
  ``Click target:true``，点的是那一行 / 那个按钮**识别框中心**，**绝不用固定死坐标**
  （旧线用 (525,812)/(359,812) 死点，本项目禁止）。
* **绝不点「取消」**：取消只会退回上一页、下一轮再弹；本层用 OCR 找**目标行 / OK** 来点。
* **容忍 OCR 变体**：星导石 / 星岛石 两种写法都认（``星导石|星岛石``）。
* 若某一步读不到目标（星导石行 / OK 都认不出），本层**不动**，交给各场景**已有的有界收工**
  带原因停（绝不盲点、绝不静默）。

共享性
------
「体力不足/回复体力」是**跨场景**弹窗：五重 / 战阵之宴 / 领主战族 / 深渊**共用同一份**
判据与动作。故节点定义只写一份（``common.json`` 的 ``PubStamina*``），各链只以 ``[JumpBack]``
引用（ADR-0003：同一事实不得有第二份拷贝）。本文件只描述**数据**（短语 / 节点名 / 策略 /
需要接线的链），不导入 ``maa``、不跑逻辑（``scene/`` 离线可导入、是配置权威）。

诚实边界（旧说法被真机证伪，如实更正文）
--------------------------------------
* 判据（OCR 串 / 动作）取自**旧线真机帧**（上列三张）+ **本线真机A 帧**（体力不足弹窗、
  「体力回复了！」结果窗）；★本线仍未在真机上**主动制造**「体力不足」（账号体力接近上限，
  抽干账号未经许可不做）★ —— 但**第四跑真机A 已自然到达**该流程、覆盖到第三态（见下）。
  → 只做**离线**验证（判据 / 接线 / 策略 + prove-red + 真机帧回放）。
* ★历史更正（supersede，不删除）★：旧说法「旧线第三态『体力回复了！』结果窗本票**未处理它**
  —— 五重真机实测点 OK 后关卡**直接开打**，无该结果窗（见 8-stamina-ok.txt）；若出现属
  **已知未覆盖**」**已被真机A 第四跑（2026-10-16）证伪**：星导石恢复的二次确认 OK 之后，
  游戏**确实**弹出「体力回复了！」结果窗（带一个 OK 按钮），此前 pipeline **无任何节点认它**
  → 五重枢纽空转 ``WuchongEntry`` / ``WuchongWait`` 数分钟、``state`` 恒 ``unknown``，最终
  由「未知画面累计 121 次」兜底收工（零战斗）。→ 现作为恢复链**第一类参与的第三态**处理
  （结果窗正文叶 + OK 叶 + 动作节点 ``PubStaminaDone*``，排在确认步之后，见上「★恢复策略★」）。
  证据帧：``tools/frames/stamina_recovered_done_wuchong_a.png``（同屏亦见
  ``…\\wc74\\frames\\00007_team.png``）；逐条 OCR：``…stamina_recovered_done_wuchong_a.ocr.txt``
  （实测「体力回复了！」``[267,424,168,36]``、结果窗 ``OK`` ``[333,805,53,37]`` —— 在中心
  左侧；★与确认框 OK（x≈496）**不同屏、不同 ROI**，两套节点互不误命中★）。
* 旧线第三态用**模板匹配** ``RaidStaminaDone.png`` + 死坐标 (359,812) 点 OK（旧线实现）；本层
  沿用**读后动**：结果窗正文叶 + OK 叶 + 动作节点 ``And`` box_index=1 → ``Click target:true``，
  点的是 OK **识别框中心**、零死偏移（本项目红线）。
"""

from __future__ import annotations

# ★#102 P0-1：模板优先通道的动作节点名**只有一个真源**（``scene/templates.py``）★ ——
# 这里 import 而不是再抄一份字面量（ADR-0003：同一事实不得有第二份拷贝）。
# ``scene/templates.py`` 是纯数据模块（只 import ``scene.auto_switch`` 的几何判据，不碰 PIL /
# numpy / maa），故本文件的「离线可导入」不受影响。
from .templates import NODE_USE_STONE_TPL  # noqa: F401  (本模块对外是 stamina.NODE_USE_STONE_TPL)

# ---------------------------------------------------------------------------
# ① 弹窗 / 按钮的判据短语（真机帧 OCR）—— 全项目唯一一处
# ---------------------------------------------------------------------------
#: 弹窗正文（旧线真机帧：回复体力弹窗的稳定副标题；该串在「体力不足」变体里同样出现）。
POPUP_TEXT = "请选择要使用的道具"
#: 弹窗标题变体（部分场景/旧帧的标题是「体力不足」，新帧是「回复体力」）——两个都认。
POPUP_TITLE_TEXT = "体力不足"
#: 星导石那一行的行名（★容忍 OCR 变体：星导石 / 星岛石★；行名形如「星导石 × 50」）。
STONE_ROW_TEXTS: tuple[str, ...] = ("星导石", "星岛石")
#: 二次确认框标题（旧线实测「点星导石 × 50 → 弹窗 → 点 OK 才生效」；★同样容忍 星岛石★）。
CONFIRM_TEXT = "是否消耗星(导|岛)石回复体力"
#: 确认框【OK】按钮（两端锚定；左侧【取消】绝不点）。
OK_TEXT = "^OK$"
#: 取消按钮（**绝不点**，此处只列出以免误用）。
CANCEL_TEXT = "^取消$"
#: 星导石行所在 ROI（720 空间）——圈定弹窗选项区那一行，避开确认框标题 / 其它页同名文字。
#:
#: ★真机A 重新标定（2026-10-16，第三次 run；这是本条 ROI 的承重证据）★
#: 旧值 ``(180, 900, 420, 80)``（y 900..980）取自**旧线**战阵之宴帧（那里星导石行在 y≈934）；
#: 但本线真机A 的弹窗里「星导石 × 50」实测 ``box=[209, 873, 160, 32]``（行跨 y 873..905，
#: 中心 y≈889）→ **整行跨在旧 ROI 上边界之外**（低于 y=900）→ MaaFramework 先按 ROI 裁剪再 OCR，
#: 该行被裁掉、``PubStaminaStoneText`` 永不命中 → ``And[PubStaminaInsufficientText,
#: PubStaminaStoneText]`` 永不命中 → ``PubStaminaUseStone`` 永不点 → 体力永不恢复 → 五重枢纽空转
#: ``WuchongEntry ×121`` / ``WuchongWait ×120`` 共 432s、``state`` 恒 ``unknown``，最终由
#: 「未知画面累计 121 次」兜底收工（账本只剩 ``wuchong/run/completed``，零战斗、零点击）。
#: 证据帧：``tools/frames/stamina_insufficient_wuchong_a.png``（同屏亦见
#: ``…\\wc74\\frames\\00306_stamina.png``）；逐条 OCR：``…\\stamina_insufficient_wuchong_a.ocr.txt``
#: （实测「星导石×50」``[209,873,160,32]``、「请选择要使用的道具」``[234,185,250,28]``、
#: 「体力不足」``[300,144,118,37]``、「取消」``[325,1053,68,41]``）。
#:
#: ★故意放宽 y（840..1000，而非只挪 ~30px）★：弹窗正文门（``PubStaminaInsufficientText``：
#: 体力不足 / 请选择要使用的道具）已保证「此刻就在这唯一一屏体力弹窗上」，而「星导石 / 星岛石」
#: 只出现在该行，故放宽 y 不引入误命中；却能让布局 / 内边距变化导致的 ±几十 px 漂移仍落在 ROI 内
#: （旧值正是「差 30px 就全盘失效」，教训）。x 维持 ``180..600``：行名起于 x≈209，星导石数量
#: （真机 x≈518..645）仍被排除。★此常量与 ``common.json`` 的 ``PubStaminaStoneText.roi`` 必须相等★
#: （由 ``tools/contract_hooks/hooks_stamina.py`` + ``hooks_74_stamina.py`` 钉住）。
STONE_ROW_ROI = (180, 840, 420, 160)
#: 确认框 OK 所在 ROI（720 空间）——圈定右侧按钮，避开左侧【取消】与弹窗标题。
OK_BTN_ROI = (430, 770, 290, 90)
#: 结果窗「体力回复了！」正文短语（第三步：星导石恢复后游戏弹的结果窗）—— 容忍 OCR 尾标点。
DONE_TEXT = "体力回复了"
#: 结果窗【OK】所在 ROI（720 空间）—— ★与确认框 OK 各用各的 ROI★：结果窗 OK 真机A 实测
#: ``[333,805,53,37]``（x 333..386），在**中心左侧**；而确认框 OK（``OK_BTN_ROI`` 那一屏）
#: 在 x≈496（右侧）—— 两屏 OK 的 x 区间**不重叠**，各自用门（见下）钉死，互不误命中。
#: 这里圈定 x 290..450 / y 770..860：完整包含结果窗 OK 框、排除确认框 OK（x≥430..496 起）
#: 与结果窗左侧其它文字；★此常量与 ``common.json`` 的 ``PubStaminaDoneOkText.roi`` 必须相等★
#: （由 ``tools/contract_hooks/hooks_stamina.py`` + ``hooks_stamina_done.py`` 钉住）。
DONE_OK_ROI = (290, 770, 160, 90)

# ---------------------------------------------------------------------------
# ② 共享节点名（定义在 ``common.json``，各链以 [JumpBack] 引用）
# ---------------------------------------------------------------------------
NODE_INSUFFICIENT = "PubStaminaInsufficientText"  # 弹窗正文叶（请选择要使用的道具 / 体力不足）
NODE_STONE = "PubStaminaStoneText"               # 星导石行叶（星导石 / 星岛石 + ROI）
NODE_USE_STONE = "PubStaminaUseStone"            # 第一步【OCR 兜底】：点星导石行（行名 OCR）
NODE_CONFIRM = "PubStaminaConfirmText"           # 二次确认框标题叶
NODE_OK = "PubStaminaOkText"                     # 二次确认框 OK 叶
NODE_CONFIRM_OK = "PubStaminaConfirmOk"          # 第二步：点确认框 OK
NODE_DONE_TEXT = "PubStaminaDoneText"            # 结果窗正文叶（体力回复了！——第三步）
NODE_DONE_OK_TEXT = "PubStaminaDoneOkText"       # 结果窗 OK 叶（x 中心左侧，自有 ROI）
NODE_DONE_OK = "PubStaminaDoneOk"                # 第三步：点结果窗 OK
#: 第一步【模板优先】：点星导石行（**图标模板**判据）。名字来自 ``scene/templates.py``（上面 import）。
#: 它与 :data:`NODE_USE_STONE` 是**同一动作、同一落点**（都点行框中心），只差行判据：
#: 模板通道更稳（图标不经 OCR），OCR 通道是兜底（换皮 / 换分辨率导致图标裁片不匹配时仍能命中）。
NODE_STONE_TPL = NODE_USE_STONE_TPL  # = "PubStaminaUseStoneTpl"

#: 全部「体力恢复」共享节点名（守卫据此核对定义在场 / 判据一致）。
STAMINA_NODES: tuple[str, ...] = (
    NODE_INSUFFICIENT,
    NODE_STONE,
    NODE_USE_STONE,
    NODE_CONFIRM,
    NODE_OK,
    NODE_CONFIRM_OK,
    NODE_DONE_TEXT,
    NODE_DONE_OK_TEXT,
    NODE_DONE_OK,
    # ★#102 P0-1★ 「星导石行」的**模板通道**三节点（真源 = ``scene/templates.py``）：
    #   · ``PubStaminaStoneIcon``    —— 行图标 TemplateMatch（模板优先）
    #   · ``PubStaminaStoneRow``     —— Or(图标模板, 行名 OCR) = 模板优先 / OCR 兜底
    #   · ``PubStaminaUseStoneTpl``  —— 动作节点（And 弹窗正文 + 双通道行 → 点行框中心）
    # 为什么必须登记在这里：``hooks_stamina.stamina-stone-only-policy`` 会把任何
    # 「``PubStamina*`` 但没被本元组声明」的节点当成**第二份免费恢复路径**报红（ADR-0003：
    # 同一事实不得有第二份拷贝）。这三个是**同一条恢复链**的第二判据，不是第二条路径，
    # 故在此声明 —— 名字真源仍是 ``scene/templates.py``，这里只做**归属登记**（不复制数值）。
    "PubStaminaStoneIcon",
    "PubStaminaStoneRow",
    NODE_STONE_TPL,
)

# ---------------------------------------------------------------------------
# ③ ★策略（唯一声明处）★ —— 运维裁决：只用星岛石恢复
# ---------------------------------------------------------------------------
#: 体力不足时是否用**星岛石（星导石，付费货币）**恢复。运维裁决 settled：**只用它**。
#: （本项置真 = 恢复链为 :data:`RECOVERY_STEPS` 的四项；关掉则 :func:`recovery_refs` 返回空 = 不恢复。）
RECOVER_WITH_STONE = True

#: ★恢复链的**声明顺序 = 唯一真源**★（:func:`recovery_refs` 只是它的 ``[JumpBack]`` 投影；
#: ``hooks_stamina`` 的 ①③ 对着这张表断言，② ——「每个消费链枢纽的 ``next`` 都含全部这些项」——
#: 由同文件的 ``stamina-wired-every-consumer`` 核）。
#:
#: ★为什么是这个顺序（每条都有理由，别随手调）★
#:
#: 1. :data:`NODE_STONE_TPL` —— **模板优先**。第一步的行判据在 #102 起是双通道
#:    （``PubStaminaStoneRow`` = ``Or(图标模板, 行名 OCR)``，真源 ``scene/templates.py``）。
#:    图标是**画进图里**的固定图形，不经过 OCR ⇒ 不吃 OCR 抖动（本仓实测该行名会被读成
#:    「星岛石」、还会丢字；见 ``STONE_ROW_TEXTS`` 的多写法兜底 = 「我们知道它会读错」的证据）。
#: 2. :data:`NODE_USE_STONE` —— **OCR 兜底**。模板不中（换皮 / 换分辨率 / 图标裁片不匹配 /
#:    roi 被布局挪走）时，仍用行名 OCR 命中同一行。两者是**同一动作、同一落点**
#:    （``And(弹窗正文, 行) + box_index=1 → Click target:true`` = 点行框中心），
#:    所以并列成一前一后是安全的：命中哪个都点对了行。
#: 3. :data:`NODE_CONFIRM_OK` —— 二次确认框 OK。★第二步才真扣星导石、体力 +100★；
#:    它只在「已经点过那一行」之后才在屏上（自有 ROI，与行不同屏），排前面只会白扫两屏。
#: 4. :data:`NODE_DONE_OK` —— 「体力回复了！」结果窗 OK（第三步，**幂等叶子**：点掉即消失）。
#:    同理必须在确认步之后（真机A 第四跑实测该结果窗确实出现，此前无节点认它 → 五重
#:    空转到「未知画面 121 次」兜底；见本文件头「诚实边界」更正）。
#:
#: ★为什么模板项必须排在 OCR 项**之前**★：``next`` 是**有序候选**，MaaFramework 每轮从头逐项
#: 识别、先命中先执行 ⇒ 排前面才是「模板优先」；反过来（OCR 在前）OCR 会先吃掉该帧，
#: 模板通道永远轮不到（= 白接一条通道，被 ``hooks_stamina`` 的 ③ 与 ``hooks_102`` 的 C8 钉死）。
RECOVERY_STEPS: tuple[str, ...] = (
    NODE_STONE_TPL,
    NODE_USE_STONE,
    NODE_CONFIRM_OK,
    NODE_DONE_OK,
)


def recovery_refs() -> tuple[str, ...]:
    """各链要注入的**恢复链引用**（有序，``[JumpBack]`` 形式；判据见本文件头）。

    顺序 = :data:`RECOVERY_STEPS`（**那里写着为什么**）：模板优先通道 → OCR 兜底通道 →
    二次确认框 OK（第二步才真扣星导石、体力 +100）→ 「体力回复了！」结果窗 OK（第三步，幂等叶子）。
    策略关掉（``RECOVER_WITH_STONE = False``）时返回空元组 —— 于是「不做恢复」这件事在
    数据层就成立，不依赖运行期判断。

    ★各枢纽的 ``next`` 一律从这里**派生**（``assets/resource/pipeline/*.json`` 是手写投影，
    真源是本文件）★：``hooks_stamina.stamina-wired-every-consumer`` 要求每个消费链的枢纽 ``next``
    含**全部**这些项（缺一个 = 该步处理不了体力弹窗），``stamina-stone-only-policy`` 还要求
    模板项在 OCR 项之前。
    """
    if not RECOVER_WITH_STONE:
        return ()
    return tuple(f"[JumpBack]{name}" for name in RECOVERY_STEPS)


#: 恢复链引用的裸节点名（守卫据此核对各链接线 / 与恢复链一致）。
#: ★与 :data:`RECOVERY_STEPS` 是同一份东西★（不是抄第二份）：引用就是这几项的 ``[JumpBack]`` 投影。
RECOVERY_NODES: tuple[str, ...] = RECOVERY_STEPS

# ---------------------------------------------------------------------------
# ④ 需要携带恢复链的场景（场景名, pipeline 文件, 携带恢复引用的枢纽节点）
# ---------------------------------------------------------------------------
#: 每个消耗体力的场景：守卫逐个核对恢复链已接入该枢纽。
#: 五重的恢复引用注入到 ``FLOW_EXCEPTIONS``（⇒ 每个流程节点都带；见 scene.wuchong），
#: 其余各自把引用插在自己的入口 / 分派表 ``next`` 里（外传两个别名入口分派表逐项一致，两处都插）。
#: ★迷宫（farm）/ 幻想连战（phantom）不单列★：它们经 ``SpecialEntry`` 分派，
#:   而恢复引用已注入 ``SpecialEntry.next`` → 自然覆盖（不复制第二份引用）。
STAMINA_CONSUMING_CHAINS: tuple[tuple[str, str, str], ...] = (
    ("五重决战", "wuchong.json", "WuchongEntry"),
    ("战阵之宴", "raid.json", "RaidDispatch"),
    ("领主战族（领主战/降临讨伐/幻想连战/战阵之宴/摇曳的迷宫 批量）", "special_dungeon.json", "SpecialEntry"),
    ("深渊连战EX / 普通深渊", "abyss.json", "AbyssEntry"),
    ("自动过主线", "auto_push.json", "AutoPush"),
    ("外传（故事 / 全清）", "side_story.json", "SideStoryEntry"),
    ("外传（故事 / 全清）", "side_story.json", "SideClearEntry"),
)
