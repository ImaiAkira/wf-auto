# -*- coding: utf-8 -*-
"""#106：领主战 / 讨伐【难度静态数据】的**一次性**采集 CLI（显式运行；运行期不调用）。

本文件做三件事，**只在人显式跑它的时候发生**：

1. 把「仓库里已有的真机帧 OCR」读成结构化事实（``parse_list_frame`` / ``parse_detail_frame``）；
2. 归并成 :class:`scene.lords.Lord` 条目（``collect``）；
3. 渲染成两处产物并（用 ``--write``）落盘：
   * ``scene/lords.py`` 的**标记段**（``# ---- BEGIN GENERATED: LORDS`` … ``# ---- END GENERATED: LORDS``）；
   * ``assets/data/lords.json``（``scene/lords.py`` 的**投影**，不是第二真源）。

用法（Windows / 仓库根）::

    .venv\\Scripts\\python.exe tools\\gen_lord_registry.py            # 只读：打印采集摘要（不写盘）
    .venv\\Scripts\\python.exe tools\\gen_lord_registry.py --check    # 校验仓内产物 == 重新渲染的结果
    .venv\\Scripts\\python.exe tools\\gen_lord_registry.py --write    # 写入标记段 + assets/data/lords.json
    .venv\\Scripts\\python.exe tools\\gen_lord_registry.py --live     # 用 MaaFramework OcrTask 重跑帧 OCR（慢、不用设备）
    .venv\\Scripts\\python.exe tools\\gen_lord_registry.py --ocr-json ocr.json   # 换成预采集的 OCR 产物

★运行期不调用（#106 的硬约束）★
------------------------------
本模块**不得**被 ``agent/`` / ``scene/`` / ``assets/`` 任何运行期代码 import —— 守卫
``hooks_106.py`` 的 ``lord-collect-cli-not-on-runtime-path`` 会扫盘并变红。它也不 import
``maa`` / ``agent`` / ``adb`` 之类的东西（``--live`` 是**懒 import**），因此在没有设备、
没有 MaaFramework 的机器上照样能跑 ``--check``。

★OCR 注入点（为什么可测）★
--------------------------
全部采集逻辑只依赖一个可注入的 ``ocr_fn``：

* ``OcrFn = Callable[[Path], Sequence[OcrItem]]``，``OcrItem = (text, box, score)``，
  ``box`` 与 MaaFramework OcrTask 的 box 同形（``[x, y, w, h]``，**原始像素空间**，
  随帧的分辨率而定 —— 本仓同时有 1080×1920 的列表页帧与 720×1280 的详情页帧，
  **不要**把两种空间的坐标当同一种用）；
* 缺省实现 = :func:`corpus_ocr_fn` 套 :data:`FRAME_OCR`（**假 OCR**：仓库里这几张帧
  实跑 OCR 的逐条摘录，守卫与单测都走它，因此完全离线、可复算、无随机性）；
* ``--live`` 换成 :func:`maafw_ocr_fn`（同一个 ``OcrTask``，``tools/ocr_image.py`` 那套）；
* ``--ocr-json`` 换成 :func:`json_ocr_fn`（把预采集的 OCR 落成 JSON 再喂进来）。

★产物为什么有一份 JSON（与调研文档结论的差异，已权衡）★
--------------------------------------------------------
``docs/research/lord-battle-difficulty-registry.md`` §3.1 反对 ``assets/data/lords.json``，
理由是「会变成第二真源」+「assets 下的 JSON 会被 MAA 当 pipeline 打包」。本实现按
``docs/spec/runner-delivery.md`` §4.4（``scene/lords.py`` → 生成 ``assets/data/lords.json``）做，
并把那两条风险**用机制消掉**：

* **不是第二真源**：``assets/data/lords.json`` 只由 ``--write`` 从 ``scene/lords.py`` 的
  内存数据渲染；守卫断言「重新渲染 == 仓内文件」逐字相等（``lord-registry-derived-json-in-sync``），
  手改任何一边都会红；
* **不会被当 pipeline**：MAA 只加载 ``assets/resource/**``（``tools/ocr_image.py`` 的
  ``post_bundle(assets/resource)``、``tools/install.py`` 只拷 ``assets/resource`` +
  ``assets/interface.json``、``tools/validate_schema.py`` 的 ``--resource-dirs`` 默认也是
  ``assets/resource``）—— ``assets/data/`` 在资源包之外，既不进 schema 校验也不进安装产物。

它存在的唯一理由：给**不能 import Python** 的读者（pipeline 侧/外部脚本/人）一份同源的只读视图。

★数据从哪来（扩样的准确做法）★
-------------------------------
见 ``scene/lords.py`` 的模块 docstring（字段含义 + 证据格式 + 扩充步骤）。一句话：
拿新帧 → ``--live`` 或 ``--ocr-json`` 采集 → 在 :data:`FRAMES` 登记帧、在
:data:`DETAIL_PREFIXES` 登记**详情页认证前缀**（不登记就报错，绝不猜归属）→ ``--write``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
for _path in (str(REPO_ROOT), str(REPO_ROOT / "tools")):
    if _path not in sys.path:
        sys.path.append(_path)

from scene.config import DIFFICULTIES  # noqa: E402
from scene.lords import (  # noqa: E402
    GENERATED_BEGIN_PREFIX,
    GENERATED_END_PREFIX,
    Lord,
    NEED_MAX_TIERS,
    NEED_ROW_PREFIX,
    NEED_TIER_CHAIN,
    SOURCE_DETAIL,
    SOURCE_LIST,
    SOURCE_UNKNOWN,
    pending,
)

#: OCR 结果的形状（与 MaaFramework ``OcrTask`` 的 all_results 同形：text / box / score）。
OcrItem = tuple[str, tuple[int, int, int, int], float]
#: 采集的唯一外部依赖：给一张帧，回一串 OCR 结果。★测试/守卫从这里注入假 OCR★
OcrFn = Callable[[Path], Sequence[OcrItem]]

#: 本次采集的 OCR 实跑日期（写进证据串；重跑活 OCR 会得到不同的 score，属正常）。
OCR_DATE = "2026-10-17"

#: 子族 -> ``kind``。★类别只能用 kind 判，绝不能用「行名是否以『讨伐』结尾」★
#: （``无猾机兵`` / ``始龙之眼`` / ``圣夜的淘气鬼`` / ``碧愁机兵`` 都不带「讨伐」，见
#: ``docs/research/lord-battle-all-difficulty-unlock.md`` §1.4）。
KIND_BY_SUBFAMILY: dict[str, str] = {"领主战": "lord", "降临讨伐": "joss"}
SUBFAMILY_BY_KIND: dict[str, str] = {v: k for k, v in KIND_BY_SUBFAMILY.items()}

#: 列表页证据里的分类标签（详情页每行也带这个标签，用来交叉核对 kind）。
KIND_BY_CATEGORY_LABEL: dict[str, str] = {"领主战": "lord", "降临讨伐": "joss"}

#: 列表页每行自带 ``通关数 N/M``（★本仓最重要的进度读数★：M = 该成员总档数）。
PROGRESS_RE = re.compile(r"^通关数\s*(\d+)\s*[/|]\s*(\d+)$")
#: 「该档已通关」徽标。真机有**弱读**：``COMPLETE!!`` 丢首字母 → ``MPLETE!!``
#: （``tools/frames/lord_detail_redjoss_cleared.png`` 第 2 行 y=578，score 0.999）。
COMPLETE_MARK = "PLETE!!"
NEW_MARK = "NEW"
FIRST_REWARD_MARK = "首次报酬"

#: 难度行名正则：难度名**整串锚定**在后缀，长词优先（``高级+`` 必须排在 ``高级`` 前面，
#: 否则 ``妖狐高级+`` 会被切成年「妖狐高级」+ 尾巴「+」）。
_TIER_SUFFIX = "|".join(
    re.escape(d) for d in sorted(DIFFICULTIES, key=len, reverse=True)
)
TIER_LABEL_RE = re.compile(rf"^(?P<prefix>.+?)(?P<difficulty>{_TIER_SUFFIX})$")


class CollectError(Exception):
    """采集到的数据自相矛盾 / 缺登记（**绝不静默降级**，一律点名帧与读数）。"""


# ===========================================================================
# 帧清单（显式登记：新增一张帧 = 在这里 + FRAME_OCR 各加一条）
# ===========================================================================
#: 列表页帧 -> 它所在的页签（用于交叉核对：该帧里出现的行名必须都属于这个子族）。
LIST_FRAMES: dict[str, str] = {
    # 领主战页签：4 行，全部带 `通关数 N/M`（1080×1920 空间）
    "tools/frames/lord_page_tab_lord.png": "领主战",
    # 降临讨伐页签：五重决战/无猾机兵/红嫉机兵/苍叹机兵（1080×1920 空间）
    "tools/frames/lord_page_tab_joss.png": "降临讨伐",
}

#: 详情页帧（**认证前缀 -> 成员** 的登记，见 :data:`DETAIL_PREFIXES`）。
DETAIL_FRAMES: tuple[str, ...] = (
    "tools/frames/lord_detail_multidiff.png",
    "tools/frames/lord_detail_redjoss_cleared.png",
    "tools/frames/lord_detail_redjoss_early.png",
    "tools/frames/lord_detail_singlediff.png",
    "tools/frames/lord_detail_naught_robot_c1.jpg",
)

#: 采集清单（顺序 = 证据串的顺序，影响渲染结果，**别随手调换**）。
FRAMES: tuple[str, ...] = (*LIST_FRAMES, *DETAIL_FRAMES)

#: ★详情页「认证文本」前缀 -> 成员 slug★（= ``scene/lords.py`` 里 ``row_prefix`` 的登记源）。
#:
#: 为什么要它：详情页的行名 **不是** 列表页行名的拼接 —— ``红嫉机兵`` 的详情页行名是
#: ``红机兵海茵莱特中级``（前缀 = ``红机兵海茵莱特``，是 boss 名，不是行名）。而详情页帧本身
#: **不足以**自动判定归属：``tools/frames/lord_detail_redjoss_early.png`` 的标题被 OCR 读成
#: ``红嫉族机兵``（见 #39）。所以归属走**这张前缀登记表**：帧里读出的前缀必须在这里登记过，
#: 否则 :func:`parse_detail_frame` 直接报错 —— **不猜**。
DETAIL_PREFIXES: dict[str, str] = {
    "lord/妖狐讨伐": "妖狐",
    "lord/诅咒弧魔艾基尔讨伐": "诅咒弧魔艾基尔",
    "joss/红嫉机兵": "红机兵海茵莱特",
    "joss/无猾机兵": "机工神兵菲诺梅那",
}

#: 行名容错正则的人工覆盖（只放**真机实测出现过**的变体；没证据的一律 ``^行名$``）。
ROW_REGEX_OVERRIDES: dict[str, str] = {
    # 真机 OCR 把「红嫉机兵」读成「**红嫉族**机兵」—— **插了一个「族」字**，不是把「嫉」换掉
    # （tools/frames/lord_detail_redjoss_early.png 的标题框，score 0.862）。
    # 所以容错是 `族?`（可有可无），不是字符集 `[嫉族]`（那只能表达「二选一」）。
    "joss/红嫉机兵": r"^红嫉族?机兵$",
}


# ===========================================================================
# 帧 OCR 语料（假 OCR 的素材；逐条摘自 2026-10-17 实跑 OcrTask 的输出）
# ===========================================================================
# 说明：
# * 只摘**解析器真的会读**的行（行名 / 通关数 / 难度行名 / COMPLETE!! / NEW / 首次报酬 /
#   分类标签 / 标题）；完整输出可用 ``--live`` 或 ``tools/ocr_image.py tools/frames/<帧>`` 复现；
# * box 是**原始像素**空间（列表页帧 1080 宽、详情页帧 720 宽），不要混用；
# * score 保留 3 位小数（原值 6 位）；重跑活 OCR 的 score 会有第 4 位抖动，属正常。
FRAME_OCR: dict[str, tuple[OcrItem, ...]] = {
    # ---- 列表页 · 领主战（1080×1920）----
    "tools/frames/lord_page_tab_lord.png": (
        ("艾基尔·嫉妒讨伐", (303, 960, 296, 42), 0.997),
        ("通关数1/4", (821, 1032, 191, 42), 0.972),
        ("猩红巨熊讨伐", (301, 1174, 246, 42), 0.998),
        ("通关数3/4", (821, 1248, 189, 42), 0.958),
        ("背鳍三兄弟讨伐", (305, 1392, 286, 42), 0.999),
        ("通关数1/4", (821, 1464, 189, 42), 0.973),
        ("八岐大蛇讨伐", (301, 1608, 248, 42), 0.998),
        ("通关数4/4", (821, 1680, 189, 42), 0.959),
        ("COMPLETE!!", (23, 1534, 187, 36), 1.000),
    ),
    # ---- 列表页 · 降临讨伐（1080×1920）----
    # `五王连战` 不是本 family 的成员（是五重决战），它的 `通关数1/1` 因此**故意**留着：
    # 解析器必须容忍「配对不上的通关数」，只忽略、不报错（并有计数可查）。
    "tools/frames/lord_page_tab_joss.png": (
        ("五王连战", (301, 956, 173, 48), 1.000),
        ("通关数1/1", (821, 1032, 185, 42), 0.986),
        ("无猾机兵", (301, 1172, 171, 50), 1.000),
        ("通关数5/5", (821, 1248, 191, 42), 0.944),
        ("COMPLETE!!", (23, 1102, 183, 34), 1.000),
        ("红嫉机兵", (301, 1388, 171, 50), 0.999),
        ("通关数4/4", (821, 1464, 189, 42), 0.959),
        ("COMPLETE!!", (33, 1318, 173, 34), 0.998),
        ("苍叹机兵", (301, 1604, 171, 50), 0.999),
        ("通关数4/4", (821, 1680, 189, 42), 0.959),
        ("COMPLETE!!", (21, 1534, 187, 34), 1.000),
    ),
    # ---- 详情页 · 妖狐（720×1280；4 行全 COMPLETE!!）----
    "tools/frames/lord_detail_multidiff.png": (
        ("妖狐超级", (202, 456, 119, 33), 0.999),
        ("妖狐高级+", (201, 648, 139, 32), 1.000),
        ("妖狐高级", (202, 837, 119, 33), 0.999),
        ("妖狐中级", (201, 1028, 121, 33), 0.999),
        ("COMPLETE!!", (15, 388, 126, 22), 0.966),
        ("COMPLETE!!", (15, 578, 125, 23), 1.000),
        ("COMPLETE!!", (15, 769, 123, 24), 1.000),
        ("COMPLETE!!", (15, 960, 127, 22), 1.000),
        ("领主战", (202, 428, 70, 28), 1.000),
        ("妖狐", (289, 192, 137, 76), 1.000),
    ),
    # ---- 详情页 · 红嫉机兵（清关账号；4 行全 COMPLETE!!，第 2 行弱读成 MPLETE!!）----
    "tools/frames/lord_detail_redjoss_cleared.png": (
        ("红机兵海茵莱特超级", (203, 458, 253, 28), 0.999),
        ("红机兵海茵莱特高级+", (203, 649, 272, 28), 0.999),
        ("红机兵海茵莱特高级", (203, 840, 253, 28), 0.999),
        ("红机兵海茵莱特中级", (203, 1030, 253, 28), 0.998),
        ("COMPLETE!!", (17, 388, 120, 22), 0.952),
        ("MPLETE!!", (48, 578, 88, 23), 0.999),
        ("COMPLETE!!", (15, 769, 123, 23), 1.000),
        ("COMPLETE!!", (15, 960, 123, 22), 1.000),
        ("降临讨伐", (201, 428, 92, 28), 1.000),
        ("红嫉机兵", (191, 152, 380, 93), 0.925),
    ),
    # ---- 详情页 · 红嫉机兵（早期账号；只有 中级 + NEW + 首次报酬）----
    "tools/frames/lord_detail_redjoss_early.png": (
        ("红机兵海茵莱特中级", (203, 458, 253, 28), 0.998),
        ("NEW", (18, 389, 46, 20), 1.000),
        ("首次报酬", (542, 429, 82, 27), 1.000),
        ("降临讨伐", (202, 428, 91, 28), 0.999),
        ("红嫉族机兵", (191, 149, 382, 99), 0.862),
    ),
    # ---- 详情页 · 诅咒弧魔艾基尔（早期账号；只有 中级）----
    "tools/frames/lord_detail_singlediff.png": (
        ("诅咒弧魔艾基尔中级", (203, 458, 252, 28), 1.000),
        ("NEW", (14, 386, 53, 24), 1.000),
        ("首次报酬", (543, 433, 81, 23), 1.000),
        ("领主战", (201, 428, 71, 28), 1.000),
        ("诅咒弧魔艾基尔", (161, 200, 398, 60), 1.000),
    ),
    # ---- 详情页 · 无猾机兵（早期账号；列表页那个账号 M=5，详情只能看到起始档）----
    "tools/frames/lord_detail_naught_robot_c1.jpg": (
        ("机工神兵菲诺梅那中级", (203, 458, 280, 28), 0.994),
        ("NEW", (11, 384, 57, 29), 1.000),
        ("首次报酬", (542, 433, 82, 23), 1.000),
        ("降临讨伐", (202, 428, 91, 28), 0.999),
        ("无猾机兵", (160, 156, 374, 89), 0.981),
    ),
}


# ===========================================================================
# OCR 注入实现（假 OCR / 预采集 JSON / MaaFramework）
# ===========================================================================
def corpus_ocr_fn(corpus: dict[str, Sequence[OcrItem]] | None = None) -> OcrFn:
    """造一个**假 OCR**（:data:`FRAME_OCR` 或调用方给的语料）—— 守卫与单测的注入点。"""
    table = FRAME_OCR if corpus is None else corpus

    def _ocr(frame: Path) -> Sequence[OcrItem]:
        key = _rel(frame)
        if key not in table:
            raise CollectError(
                f"假 OCR 语料里没有帧 {key!r}（已登记 {sorted(table)}）——"
                f"新增帧必须同时补 FRAME_OCR 条目，绝不静默当「读不到」"
            )
        return tuple(table[key])

    return _ocr


def json_ocr_fn(mapping: dict[str, Sequence[Sequence]]) -> OcrFn:
    """把**预采集**的 OCR 产物（``{帧: [[text, [x,y,w,h], score], ...]}``）包成 ``OcrFn``。"""
    table = {
        str(frame): tuple(
            (str(item[0]), tuple(int(v) for v in item[1]), float(item[2]))
            for item in items
        )
        for frame, items in mapping.items()
    }
    return corpus_ocr_fn(table)


def maafw_ocr_fn(frame: Path) -> Sequence[OcrItem]:
    """真跑 MaaFramework ``OcrTask``（与 ``tools/ocr_image.py`` 同一套，**不需要设备**）。

    ★懒 import★：``maa`` 只在这里出现，模块 import 阶段不碰它 —— 因此没有 MaaFramework
    的环境照样能 ``--check``（守卫与单测都走假 OCR）。
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    from maa.controller import CustomController  # noqa: PLC0415
    from maa.resource import Resource  # noqa: PLC0415
    from maa.tasker import Tasker  # noqa: PLC0415
    from maa.toolkit import Toolkit  # noqa: PLC0415

    class _ImageController(CustomController):
        def __init__(self, img):  # noqa: D401, ANN001 - 与 ocr_image.py 同形
            super().__init__()
            self.img = img

        def connect(self) -> bool:
            return True

        def request_uuid(self) -> str:
            return "0"

        def screencap(self):  # noqa: ANN201
            return self.img

    Toolkit.init_option(str(REPO_ROOT))
    resource = Resource()
    if not resource.post_bundle(str(REPO_ROOT / "assets" / "resource")).wait().succeeded:
        raise CollectError("MaaFramework 资源包加载失败（assets/resource）")

    pil = Image.open(frame).convert("RGB")
    img_bgr = np.ascontiguousarray(np.array(pil)[:, :, ::-1])
    controller = _ImageController(img_bgr)
    controller.set_screenshot_use_raw_size(True)
    controller.post_connection().wait()

    tasker = Tasker()
    tasker.bind(resource, controller)
    job = tasker.post_task("OcrTask")
    detail = job.wait()
    if not detail.succeeded:
        raise CollectError(f"OcrTask 失败：{frame}")
    payload = job.get()
    items: list[OcrItem] = []
    for node in (payload.nodes if payload is not None else ()):
        reco = node.recognition
        for item in (reco.all_results or []) if reco is not None else ():
            box = list(item.box)
            items.append((str(item.text), (box[0], box[1], box[2], box[3]), float(item.score)))
    return tuple(items)


def _rel(path: Path | str) -> str:
    """仓库相对路径（posix 风格）。**相对路径按「已相对仓库根」处理**（与 CWD 无关）。

    为什么强调后者：``Path("tools/frames/x.png").resolve()`` 会拼上**当前工作目录**，
    于是从别的目录跑 CLI 时帧键就对不上了 —— 采集绝不能依赖 CWD。
    """
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


# ===========================================================================
# 解析：列表页
# ===========================================================================
@dataclass(frozen=True)
class ListRow:
    """列表页读到的一行：行名 + ``通关数 N/M`` + 是否有 ``COMPLETE!!`` 徽标。"""

    row_name: str
    cleared: int
    total: int
    has_complete_badge: bool
    row_y: int
    progress_y: int
    score: float
    frame: str


#: 行名 -> 它正下方 ``通关数`` 的最大纵向距离（像素，1080 空间实测 ≈ +72）。
PROGRESS_MAX_DY = 200
#: ``COMPLETE!!`` 徽标 -> 它所属行的纵向距离区间（实测 -70 ~ -74，即徽标在行名**上方**）。
BADGE_DY = (-140, -10)


def parse_list_frame(
    items: Sequence[OcrItem],
    roster_kinds: dict[str, str],
    frame: str = "",
    tab: str | None = None,
) -> tuple[tuple[ListRow, ...], tuple[str, ...]]:
    """解析一屏列表页；返回 ``(配对上的行, 配对不上的通关数文本)``。

    * **行名候选 = 花名册里的行名**（精确相等）。列表页上还有很多别的文字（活动栏、页签、
      其它玩法的行），只有花名册里的名字才算本 family 的行 —— 不靠 ROI，也不靠「像不像一个名字」；
    * 每行配**它正下方最近**的 ``通关数 N/M``（``0 < dy <= PROGRESS_MAX_DY``）；
    * 配不上的 ``通关数`` **不报错**（列表页里还有五重决战等非本 family 的行），但会**计数返回**，
      由调用方决定是否打印 —— 静默丢掉会掩盖「帧与花名册不同步」。
    """
    names: list[tuple[str, int]] = []
    progresses: list[tuple[int, int, int, float, int]] = []
    badges: list[int] = []
    for idx, (text, box, score) in enumerate(items):
        clean = text.strip()
        match = PROGRESS_RE.match(clean)
        if match:
            progresses.append((int(match.group(1)), int(match.group(2)), box[1], score, idx))
        elif clean in roster_kinds:
            names.append((clean, box[1]))
        elif COMPLETE_MARK in clean:
            badges.append(box[1])

    kind = KIND_BY_SUBFAMILY.get(tab) if tab is not None else None
    if kind is not None:
        wrong = sorted({name for name, _y in names if roster_kinds[name] != kind})
        if wrong:
            raise CollectError(
                f"列表页帧的页签登记是 {tab!r}（kind={kind}），但帧里出现不属于它的行名 {wrong} "
                f"—— 帧与页签登记对不上，先核对再采集"
            )

    paired: list[ListRow] = []
    used_progress: set[int] = set()
    for row_name, row_y in names:
        candidates = sorted(
            (p[2] - row_y, p) for p in progresses if 0 < p[2] - row_y <= PROGRESS_MAX_DY
        )
        if not candidates:
            raise CollectError(
                f"行 {row_name!r}（y={row_y}）下方 {PROGRESS_MAX_DY}px 内没有 "
                f"`通关数 N/M` —— 该帧不完整或版式变了，拒绝猜 M"
            )
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            raise CollectError(
                f"行 {row_name!r} 下方有两条等距的 `通关数`（y={candidates[0][1][2]} / "
                f"{candidates[1][1][2]}）—— 配对不对，拒绝猜"
            )
        cleared, total, progress_y, score, progress_idx = candidates[0][1]
        used_progress.add(progress_idx)
        badge = any(BADGE_DY[0] <= y - row_y <= BADGE_DY[1] for y in badges)
        if badge and cleared != total:
            raise CollectError(
                f"行 {row_name!r} 有 COMPLETE!! 徽标，但读到的通关数是 {cleared}/{total} "
                f"—— 两者矛盾（徽标 = 已满），拒绝采信"
            )
        paired.append(
            ListRow(
                row_name=row_name,
                cleared=cleared,
                total=total,
                has_complete_badge=badge,
                row_y=row_y,
                progress_y=progress_y,
                score=score,
                frame=frame,
            )
        )

    leftover = tuple(f"通关数{p[0]}/{p[1]}" for p in progresses if p[4] not in used_progress)
    return tuple(paired), leftover


# ===========================================================================
# 解析：详情页
# ===========================================================================
@dataclass(frozen=True)
class DetailReading:
    """详情页读到的一屏：可见档（升序）、逐档行名、是否全通关、NEW / 首次报酬 是否在。"""

    frame: str
    slug: str
    kind: str
    row_prefix: str
    category: str
    chain: tuple[str, ...]              # 可见档，**升序**（低 -> 高）
    row_labels: tuple[tuple[str, str], ...]
    positions: tuple[tuple[str, int], ...]   # (难度, y)：实测纵向位置
    all_cleared: bool
    has_new: bool
    has_first_reward: bool
    title: str


def parse_detail_frame(
    items: Sequence[OcrItem],
    frame: str = "",
    prefixes: dict[str, str] | None = None,
) -> DetailReading:
    """解析一屏详情页。**归属靠 :data:`DETAIL_PREFIXES` 登记的前缀，不靠标题 OCR**（标题会读错）。"""
    table = DETAIL_PREFIXES if prefixes is None else prefixes
    by_prefix = {prefix: slug for slug, prefix in table.items()}

    labels: list[tuple[str, str, int]] = []   # (难度, 整串行名, y)
    for text, box, _score in items:
        match = TIER_LABEL_RE.match(text.strip())
        if match:
            labels.append((match.group("difficulty"), text.strip(), box[1]))
    if not labels:
        raise CollectError(
            "详情页帧里一行难度行名都没读到（该帧不是详情页，或 `<成员前缀><难度>` 版式变了）"
        )

    prefixes_seen = {TIER_LABEL_RE.match(lab).group("prefix") for _d, lab, _y in labels}  # type: ignore[union-attr]
    if len(prefixes_seen) != 1:
        raise CollectError(
            f"同一帧里读到多个详情页前缀 {sorted(prefixes_seen)} —— 一帧只允许一个成员，拒绝切分"
        )
    row_prefix = prefixes_seen.pop()
    slug = by_prefix.get(row_prefix)
    if slug is None:
        raise CollectError(
            f"详情页认证前缀 {row_prefix!r} 没在 DETAIL_PREFIXES 里登记（已登记 {sorted(by_prefix)}）"
            f" —— 先人工核对这是哪个成员，**绝不猜归属**"
        )
    kind = slug.split("/", 1)[0]

    difficulties = [d for d, _lab, _y in labels]
    if len(set(difficulties)) != len(difficulties):
        raise CollectError(f"详情页同一帧里读到重复的难度行 {difficulties} —— 配对不对，拒绝采信")

    # 纵向顺序：实测**降序**（顶 = 最高档，两帧互证）。链升序 = 自下而上。
    top_to_bottom = sorted(labels, key=lambda x: x[2])
    ascending = tuple(reversed([d for d, _lab, _y in top_to_bottom]))
    order_idx = [DIFFICULTIES.index(d) for d in ascending]
    if order_idx != sorted(order_idx):
        raise CollectError(
            f"难度行的纵向顺序与词表顺序不一致：自下而上读到 {ascending}"
            f"（词表升序 {DIFFICULTIES}）—— 版式或行序变了，拒绝用旧的降序假设"
        )

    positions = tuple((d, y) for d, _lab, y in top_to_bottom)
    mapped = {d: y for d, y in positions}
    badges = [
        box[1]
        for text, box, _s in items
        if COMPLETE_MARK in text.strip()
    ]
    cleared = {
        d: any(BADGE_DY[0] <= y - mapped[d] <= BADGE_DY[1] for y in badges) for d in difficulties
    }

    categories = {
        text.strip()
        for text, _box, _s in items
        if text.strip() in KIND_BY_CATEGORY_LABEL
    }
    if len(categories) != 1:
        raise CollectError(
            f"详情页帧里读到 {sorted(categories)} 个分类标签（{sorted(categories)}）——"
            f" 需要**恰好一个**（每行左侧那个「领主战 / 降临讨伐」标签），拒绝采信"
        )
    category = categories.pop()
    if KIND_BY_CATEGORY_LABEL[category] != kind:
        raise CollectError(
            f"详情页分类标签 {category!r} 与登记前缀 {row_prefix!r} 所属成员 {slug!r} "
            f"的 kind 不一致 —— 前缀登记错了，先核对"
        )

    titles = [
        (box[2], text.strip()) for text, box, _s in items if box[1] < 260 and box[2] >= 60
    ]
    title = max(titles)[1] if titles else ""

    return DetailReading(
        frame=frame,
        slug=slug,
        kind=kind,
        row_prefix=row_prefix,
        category=category,
        chain=ascending,
        row_labels=tuple((d, lab) for d, lab, _y in ascending_labels(labels)),
        positions=positions,
        all_cleared=all(cleared.values()),
        has_new=any(text.strip() == NEW_MARK for text, _b, _s in items),
        has_first_reward=any(FIRST_REWARD_MARK in text for text, _b, _s in items),
        title=title,
    )


def ascending_labels(labels: Sequence[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    """``(难度, 行名, y)`` 按难度词表升序排（用于 ``row_labels`` 的稳定顺序）。"""
    return sorted(labels, key=lambda x: DIFFICULTIES.index(x[0]))


# ===========================================================================
# 归并：帧读数 -> Lord 条目
# ===========================================================================
def default_roster() -> tuple:
    """花名册（``scene.lord_battle.LORD_BATTLE.members``，懒 import：采集时才需要它）。"""
    from scene.lord_battle import LORD_BATTLE  # noqa: PLC0415

    return tuple(LORD_BATTLE.members)


def _evidence_list(row: ListRow, frame: str) -> str:
    note = (
        f"{OCR_DATE} OCR: 行「{row.row_name}」y={row.row_y} + `通关数{row.cleared}/{row.total}` "
        f"y={row.progress_y} score={row.score:.3f}"
    )
    if row.has_complete_badge:
        note += "，同行 COMPLETE!! 徽标"
    return f"{frame}|{note}"


def _evidence_detail(reading: DetailReading) -> str:
    labels = " / ".join(lab for _d, lab in reading.row_labels)
    ys = "/".join(str(y) for _d, y in reading.positions)
    if reading.all_cleared:
        state = "全 COMPLETE!!（该账号已清空可见档）"
    else:
        state = "含未通关行（NEW / 首次报酬 在场）"
    return (
        f"{reading.frame}|{OCR_DATE} OCR: {len(reading.chain)} 行 {labels}"
        f"（纵向 y={ys}，自上而下 = 难度降序）；{state}；分类「{reading.category}」；标题 OCR「{reading.title}」"
    )


def _row_regex(slug: str, row_name: str) -> str:
    override = ROW_REGEX_OVERRIDES.get(slug)
    return override if override is not None else f"^{re.escape(row_name)}$"


def _needs_for(
    *,
    max_tiers: int | None,
    source: str,
    row_prefix: str | None,
    chain: tuple[str, ...],
    labelled: int,
) -> tuple[str, ...]:
    """还缺什么（**派生**，不许手写：保证 CLI 重跑与仓内文件逐字一致）。"""
    needs: list[str] = []
    if max_tiers is None:
        needs.append(NEED_MAX_TIERS)
    if not chain:
        needs.append(NEED_TIER_CHAIN)
    elif max_tiers is not None and len(chain) != max_tiers:
        needs.append(
            f"缺 {max_tiers - len(chain)} 档行名：M={max_tiers} 已定，链只采到 {len(chain)} 档"
            f"（{ '→'.join(chain) }）—— 需要该成员详情页整屏帧"
        )
    if row_prefix is None:
        needs.append(NEED_ROW_PREFIX)
    elif labelled < len(chain):
        needs.append(
            f"缺 {len(chain) - labelled} 档行名：链已有 {len(chain)} 档，逐行实测只有 {labelled} 档"
        )
    if max_tiers is not None and source == SOURCE_DETAIL:
        needs.append(
            "⚠ 单帧单账号：M 由详情页「可见档全 COMPLETE!!」推得；若某档（如 地狱级）是活动期开关，"
            "M 可能被低估 —— 需第二账号 / 活动期对照复算（调研 §6 #1/#6）"
        )
    elif max_tiers is not None and source == SOURCE_LIST:
        needs.append(
            "⚠ 单帧单账号：M 由列表页 `通关数 N/M` 的分母读得 —— 需第二账号复算（调研 §6 #1）"
        )
    if row_prefix is not None and len(chain) and len(chain) == max_tiers:
        if "地狱级" not in chain:
            needs.append(
                "⚠ 地狱级是否属于该成员未实测（真机 46 成员里 11 个有；出现条件未证实，"
                "调研 §1.3 / §6 #6）"
            )
    return tuple(needs)


def build_entry(member, row: ListRow | None, readings: Sequence[DetailReading]) -> Lord:
    """一位成员的读数 -> :class:`scene.lords.Lord`（**唯一**的归属/冲突判定点）。"""
    kind = KIND_BY_SUBFAMILY[member.子族]
    slug = f"{kind}/{member.行名}"
    if row is not None and row.total <= 0:
        raise CollectError(f"{member.行名!r} 的 `通关数 {row.cleared}/{row.total}` 分母非正 —— 读数坏了")

    prefixes = {r.row_prefix for r in readings}
    if len(prefixes) > 1:
        raise CollectError(
            f"{member.行名!r} 的多个详情页帧读到不同前缀 {sorted(prefixes)} —— 归属冲突"
        )
    row_prefix = prefixes.pop() if prefixes else None

    # 链：只认「可见档全通关」（此时可见 = 全集）或「可见档数 == M」（M 已由列表页定）。
    list_m = row.total if row is not None else None
    chains = [r.chain for r in readings if r.all_cleared]
    for reading in readings:
        if not reading.all_cleared and list_m is not None and len(reading.chain) == list_m:
            chains.append(reading.chain)
    chain: tuple[str, ...] = ()
    if chains:
        chain = max(chains, key=len)
        if len({len(c) for c in chains}) > 1:
            raise CollectError(f"{member.行名!r} 的多个详情页帧给出不同长度的完整链 {chains}")
        # 早期账号只应看到**最低的那几档**（逐档递进）：可见链必须是完整链的前缀。
        for reading in readings:
            if reading.all_cleared:
                continue
            if list(chain[: len(reading.chain)]) != list(reading.chain):
                raise CollectError(
                    f"{member.行名!r}：帧 {reading.frame} 可见档 {reading.chain} 不是完整链 "
                    f"{chain} 的前缀 —— 「逐档递进（通关低档才开高档）」假设被这帧证伪，拒绝归并"
                )

    detail_m = max((len(r.chain) for r in readings if r.all_cleared), default=None)
    if list_m is not None and detail_m is not None and list_m != detail_m:
        raise CollectError(
            f"{member.行名!r}：列表页 `通关数` 分母 M={list_m}，详情页全通关帧读到 {detail_m} 行 "
            f"—— 两个来源冲突，两个帧都要复核（调研 §4.2 ②「冲突告警」）"
        )
    max_tiers = list_m if list_m is not None else detail_m
    source = SOURCE_LIST if list_m is not None else (
        SOURCE_DETAIL if detail_m is not None else SOURCE_UNKNOWN
    )

    labels = {d: lab for r in readings for d, lab in r.row_labels}
    ordered_labels = tuple(
        sorted(labels.items(), key=lambda kv: DIFFICULTIES.index(kv[0]))
    )

    evidence: list[str] = []
    if row is not None:
        evidence.append(_evidence_list(row, row.frame))
    evidence.extend(_evidence_detail(r) for r in readings)

    max_tiers_verified = max_tiers is not None
    verified = (
        max_tiers_verified
        and bool(chain)
        and len(chain) == max_tiers
        and all(d in labels for d in chain)
    )

    return Lord(
        slug=slug,
        kind=kind,
        row_name=member.行名,
        row_regex=_row_regex(slug, member.行名),
        row_prefix=row_prefix,
        max_tiers=max_tiers,
        max_tiers_source=source,
        max_tiers_verified=max_tiers_verified,
        tier_chain=chain,
        row_labels=ordered_labels,
        evidence=tuple(evidence),
        verified=verified,
        needs=_needs_for(
            max_tiers=max_tiers,
            source=source,
            row_prefix=row_prefix,
            chain=chain,
            labelled=sum(1 for d in chain if d in labels),
        ),
    )


def collect(
    ocr_fn: OcrFn | None = None,
    roster: Sequence | None = None,
) -> tuple[Lord, ...]:
    """★采集入口★：``ocr_fn`` + 花名册 -> 全部 :class:`Lord`（顺序 = 花名册顺序）。"""
    members = tuple(roster) if roster is not None else default_roster()
    ocr = ocr_fn if ocr_fn is not None else corpus_ocr_fn(FRAME_OCR)

    roster_kinds: dict[str, str] = {}
    for member in members:
        if member.子族 not in KIND_BY_SUBFAMILY:
            raise CollectError(
                f"成员 {member.行名!r} 的子族 {member.子族!r} 没有 kind 映射"
                f"（已知 {sorted(KIND_BY_SUBFAMILY)}）—— 新增子族必须先登记到这里"
            )
        roster_kinds[member.行名] = KIND_BY_SUBFAMILY[member.子族]

    by_name: dict[str, ListRow] = {}
    for frame, tab in LIST_FRAMES.items():
        rows, _unmatched = parse_list_frame(ocr(Path(frame)), roster_kinds, frame, tab)
        for row in rows:
            previous = by_name.get(row.row_name)
            if previous is not None and previous != row:
                raise CollectError(
                    f"{row.row_name!r} 在两帧列表页上读到不一致的进度 "
                    f"{previous.cleared}/{previous.total} vs {row.cleared}/{row.total}"
                )
            by_name[row.row_name] = row

    by_slug: dict[str, list[DetailReading]] = {}
    for frame in DETAIL_FRAMES:
        reading = parse_detail_frame(ocr(Path(frame)), frame=frame)
        by_slug.setdefault(reading.slug, []).append(reading)

    known_slugs = {f"{KIND_BY_SUBFAMILY[m.子族]}/{m.行名}" for m in members}
    stray = sorted(set(by_slug) - known_slugs)
    if stray:
        raise CollectError(
            f"详情页前缀登记指向了花名册里没有的成员 {stray} —— DETAIL_PREFIXES 与成员表不同步"
        )

    out: list[Lord] = []
    for member in members:
        kind = KIND_BY_SUBFAMILY[member.子族]
        slug = f"{kind}/{member.行名}"
        row = by_name.get(member.行名)
        readings = tuple(by_slug.get(slug, ()))
        if row is None and not readings:
            out.append(pending(kind, member.行名))
            continue
        out.append(build_entry(member, row, readings))
    # 顺序 = **渲染顺序**（先「已采集」、再「占位」，各组内按花名册顺序）。
    # 这样 ``render_block`` 可以是保序纯函数，``--check`` 才能直接逐条比对。
    roster_order = {member.行名: idx for idx, member in enumerate(members)}
    out.sort(key=lambda entry: (0 if entry.evidence else 1, roster_order[entry.row_name]))
    return tuple(out)


# ===========================================================================
# 渲染
# ===========================================================================
def render_block(lords: Sequence[Lord]) -> str:
    """渲染 ``scene/lords.py`` 的**标记段**（``LORDS: tuple[Lord, ...] = (...)`` 整段）。"""
    measured = [entry for entry in lords if entry.evidence]
    placeholders = [entry for entry in lords if not entry.evidence]
    lines = ["LORDS: tuple[Lord, ...] = ("]
    lines.append(
        "    # ==== 已采集：字段来自仓内真机帧，`evidence` 里每个 `|` 前路径由 hooks_106 校验存在性 ===="
    )
    for entry in measured:
        lines.extend(_render_lord(entry))
    lines.append(
        "    # ==== 未采集（占位）：M / 解锁链 / 认证文本都还没有仓内证据，`needs` 写清缺什么 ===="
    )
    for entry in placeholders:
        lines.append(f"    pending({entry.kind!r}, {entry.row_name!r}),")
    lines.append(")")
    return "\n".join(lines) + "\n"


def _tuple_literal(values: Iterable[str]) -> str:
    items = [repr(v) for v in values]
    if not items:
        return "()"
    return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"


def _render_lord(entry: Lord) -> list[str]:
    out = [
        "    Lord(",
        f"        slug={entry.slug!r},",
        f"        kind={entry.kind!r},",
        f"        row_name={entry.row_name!r},",
        f"        row_regex={entry.row_regex!r},",
        f"        row_prefix={entry.row_prefix!r},",
        f"        max_tiers={entry.max_tiers!r},",
        f"        max_tiers_source={entry.max_tiers_source!r},",
        f"        max_tiers_verified={entry.max_tiers_verified!r},",
        f"        tier_chain={_tuple_literal(entry.tier_chain)},",
    ]
    if entry.row_labels:
        out.append("        row_labels=(")
        out.extend(f"            ({d!r}, {lab!r})," for d, lab in entry.row_labels)
        out.append("        ),")
    else:
        out.append("        row_labels=(),")
    out.append("        evidence=(")
    out.extend(f"            {item!r}," for item in entry.evidence)
    out.append("        ),")
    out.append(f"        verified={entry.verified!r},")
    if entry.needs:
        out.append("        needs=(")
        out.extend(f"            {need!r}," for need in entry.needs)
        out.append("        ),")
    else:
        out.append("        needs=(),")
    out.append("    ),")
    return out


def render_json(lords: Sequence[Lord]) -> str:
    """渲染 ``assets/data/lords.json``（``scene/lords.py`` 的**投影**，不是第二真源）。"""
    payload = {
        "_generated": {
            "by": "tools/gen_lord_registry.py --write",
            "source": "scene/lords.py",
            "note": (
                "投影，不是第二真源：内容 = scene/lords.py 的 LORDS。"
                "hooks_106 断言本文件与重新渲染的结果逐字相等，手改任何一边都会红。"
                "MAA 只加载 assets/resource/**，本文件在资源包之外（不进 pipeline、不进安装产物）。"
            ),
            "ocr_date": OCR_DATE,
            "schema_version": 1,
        },
        # 键名刻意叫 `difficulty_vocabulary`（不是 `difficulties`）：后者是**逐成员可用难度集**
        # 的经典字段名，被 hooks_106 明令禁止（见 scene/lords.py docstring 的证伪段）。
        "difficulty_vocabulary": list(DIFFICULTIES),
        "lords": [
            {
                "slug": entry.slug,
                "kind": entry.kind,
                "row_name": entry.row_name,
                "row_regex": entry.row_regex,
                "row_prefix": entry.row_prefix,
                "max_tiers": entry.max_tiers,
                "max_tiers_source": entry.max_tiers_source,
                "max_tiers_verified": entry.max_tiers_verified,
                "unlock_chain": list(entry.tier_chain),
                "unlock_edges": [list(edge) for edge in entry.unlock_edges()],
                "row_labels": {d: lab for d, lab in entry.row_labels},
                "verified": entry.verified,
                "needs": list(entry.needs),
                "evidence": list(entry.evidence),
            }
            for entry in lords
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def read_block(source_text: str) -> str:
    """从 ``scene/lords.py`` 的源码里取出标记段（**不含**两行标记本身）。"""
    begin = end = None
    for idx, line in enumerate(source_text.splitlines()):
        if line.startswith(GENERATED_BEGIN_PREFIX):
            begin = idx
        elif line.startswith(GENERATED_END_PREFIX) and begin is not None:
            end = idx
            break
    if begin is None or end is None:
        raise CollectError(
            f"scene/lords.py 里找不到标记段（需要一行以 {GENERATED_BEGIN_PREFIX!r} 开头、"
            f"另一行以 {GENERATED_END_PREFIX!r} 开头）"
        )
    return "\n".join(source_text.splitlines()[begin + 1 : end]) + "\n"


# ===========================================================================
# 落盘 / 校验
# ===========================================================================
LORDS_PY = REPO_ROOT / "scene" / "lords.py"
LORDS_JSON = REPO_ROOT / "assets" / "data" / "lords.json"


def write_all(lords: Sequence[Lord], repo_root: Path | None = None) -> tuple[Path, Path]:
    """把渲染结果写回 ``scene/lords.py`` 的标记段 + ``assets/data/lords.json``。"""
    root = REPO_ROOT if repo_root is None else Path(repo_root)
    py_path = root / "scene" / "lords.py"
    json_path = root / "assets" / "data" / "lords.json"

    source = py_path.read_text(encoding="utf-8")
    block = render_block(lords)
    lines = source.splitlines()
    begin = end = None
    for idx, line in enumerate(lines):
        if line.startswith(GENERATED_BEGIN_PREFIX):
            begin = idx
        elif line.startswith(GENERATED_END_PREFIX) and begin is not None:
            end = idx
            break
    if begin is None or end is None:
        raise CollectError(f"{py_path} 里找不到标记段，拒绝盲写")
    rebuilt = "\n".join([*lines[: begin + 1], *block.rstrip("\n").splitlines(), *lines[end:]])
    py_path.write_text(rebuilt + "\n", encoding="utf-8")

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_json(lords), encoding="utf-8")
    return py_path, json_path


def check_all(repo_root: Path | None = None) -> list[str]:
    """校验仓内产物 == 重新采集/渲染的结果；返回失败信息（空 = 一致）。"""
    root = REPO_ROOT if repo_root is None else Path(repo_root)
    msgs: list[str] = []
    collected = collect()

    # 用 importlib 而不是 ``from scene import lords``：``scene/__init__`` 把不少同名**函数**
    # 导出到了包上（``scene.apply`` 就是这么被遮蔽的），拿子模块一律走 import_module。
    import importlib  # noqa: PLC0415

    lords_mod = importlib.import_module("scene.lords")

    if tuple(lords_mod.LORDS) != collected:
        msgs.append(
            "scene/lords.py 的 LORDS 与采集 CLI 重跑的结果不一致"
            f"（仓内 {len(lords_mod.LORDS)} 条 / 重跑 {len(collected)} 条）"
        )
        for disk, fresh in zip(lords_mod.LORDS, collected):
            if disk != fresh:
                msgs.append(f"  第一条不一致：仓内 slug={disk.slug!r} / 重跑 slug={fresh.slug!r}")
                break

    block = render_block(collected)
    try:
        on_disk = read_block((root / "scene" / "lords.py").read_text(encoding="utf-8"))
    except (OSError, CollectError) as exc:
        msgs.append(f"读不到 scene/lords.py 的标记段：{exc}")
    else:
        if on_disk.rstrip("\n") != block.rstrip("\n"):
            msgs.append("scene/lords.py 标记段 != 重新渲染的文本（手改过 / 没重跑 --write）")

    json_path = root / "assets" / "data" / "lords.json"
    try:
        on_disk_json = json_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as exc:
        msgs.append(f"读不到 assets/data/lords.json：{exc}")
    else:
        if on_disk_json.rstrip("\n") != render_json(collected).rstrip("\n"):
            msgs.append("assets/data/lords.json != 重新渲染的投影（手改过 / 没重跑 --write）")
    return msgs


def summarize(lords: Sequence[Lord]) -> str:
    """人读摘要（CLI 默认模式的输出）。"""
    verified = [e for e in lords if e.verified]
    measured = [e for e in lords if e.evidence]
    lines = [
        f"帧 {len(FRAMES)} 张（列表页 {len(LIST_FRAMES)} / 详情页 {len(DETAIL_FRAMES)}）"
        f" · 成员 {len(lords)} 个 · 有证据 {len(measured)} · 全链验证 {len(verified)}",
    ]
    for entry in measured:
        chain = "→".join(entry.tier_chain) if entry.tier_chain else "（链未采集）"
        lines.append(
            f"  {entry.slug:<28} M={entry.max_tiers} [{entry.max_tiers_source}]"
            f" verified={entry.verified} 链={chain}"
        )
    return "\n".join(lines)


# ===========================================================================
# CLI
# ===========================================================================
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_lord_registry.py",
        description="#106 领主战/讨伐难度静态数据的一次性采集 CLI（运行期不调用）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="写入 scene/lords.py 标记段 + assets/data/lords.json")
    mode.add_argument("--check", action="store_true", help="校验仓内产物 == 重新渲染的结果（不写盘）")
    parser.add_argument("--live", action="store_true", help="用 MaaFramework OcrTask 重跑帧 OCR（不用设备）")
    parser.add_argument("--ocr-json", type=Path, default=None, help="预采集的 OCR 产物（{帧: [[text, box, score]]}）")
    args = parser.parse_args(argv)

    if sum(bool(x) for x in (args.live, args.ocr_json is not None)) > 1:
        parser.error("--live 与 --ocr-json 只能二选一")

    try:
        if args.ocr_json is not None:
            raw = json.loads(args.ocr_json.read_text(encoding="utf-8"))
            ocr_fn: OcrFn = json_ocr_fn(raw)
        elif args.live:
            ocr_fn = maafw_ocr_fn
        else:
            ocr_fn = corpus_ocr_fn(FRAME_OCR)

        if args.check:
            msgs = check_all()
            for msg in msgs:
                print(f"  [FAIL] {msg}")
            print("结果：" + ("一致 ✅" if not msgs else f"{len(msgs)} 处不一致"))
            return 0 if not msgs else 1

        lords = collect(ocr_fn)
        print(summarize(lords))
        if args.write:
            py_path, json_path = write_all(lords)
            print(f"已写入：{_rel(py_path)} 与 {_rel(json_path)}")
        else:
            print("（只读：未写盘；要落盘加 --write）")
        return 0
    except CollectError as exc:
        print(f"采集失败：{exc}")
        return 2


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
