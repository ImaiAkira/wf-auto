# -*- coding: utf-8 -*-
"""真机harness：把四个 live runner 需要的「设备连接 / 归位 / 标题页守护 / 任务追踪」
收敛到一处（重建自 #17；原实现 clear_all.py 曾只存在于 %TEMP%，已丢失）。

本模块【只做真机侧的事情】，不碰任何业务代码（agent/**、assets/**、scene/** 一律不改）：
  · connect_device(adb, address) —— 【唯一】登记设备的入口（#25）：构造 AdbController、
                               连接、并把地址同步进 ADDRESS + _ctrl_ref。设备地址因此
                               只有一个来源，runner 再不会「给了 controller 却漏给 harness」。
                               #40 起：address 可省略 —— 缺省时按【账号身份发现】设备
                               （机型 / 产品名 / 包名），不再依赖任何端口字面量；并可在连接
                               时校验身份（expect=...），不匹配即拒绝执行。
  · ADDRESS / ADB           —— 设备地址与 adb 路径（模块级；由 connect_device 写入）。
                               ★没有硬编码默认地址★：未登记时 _adb / adb_tap 立刻报错，
                               绝不静默打到已不存在的默认端口（#13/#24 的根因）。
  · DeviceIdentity / resolve_address / discover_devices —— #40：身份发现设备。端口会漂移，
                               身份不会；run_* 的默认地址来源就是这里（唯一真源）。
  · _ctrl_ref               —— 可变槽位：connect_device 赋值 ca._ctrl_ref["ctrl"] = ctrl，
                               本模块的 screencap / 归位从这里取当前 controller
  · 设备独占租约(#104/D9)   —— connect_device 在**连设备之前**拿 tools/device_lease.py 的独占
                               租约（被占排队等、持有者心跳过期可接管、steal 强抢）；runner 收尾
                               调 release_device_lease() 立刻让给排队的人，进程退出由 atexit 兜底。
  · TitleWatcher(assets_dir)—— 标题页守护（「标题页出现即停手」）+ 当前截图抓取 + OCR
  · ensure_main_city(watcher)—— 归位：从任意已知页面（含「游戏未启动」的 Android 桌面，
                                以及 #28 的结算 / 奖励 / 升级结算页）把游戏带回主城（见下）
  · run_task_traced(...)    —— 投递任务并追踪到结束，返回 (status, 节点序列)
  · adb_tap / screenshot / goto_side_story_list / SIDE_UNPASSED —— 零散工具

安全红线（本仓库的血泪，全部照抄既有实现）
------------------------------------------
1. **绝不 tap blind**：每个动作之前都先截屏 + OCR，确认「现在是什么页面 / 目标控件在不在」，
   再点【它自己的识别框中心】。认不出的画面只等待或直接放弃，绝不满屏乱点。
2. **绝不使用 KeyEvent 4（返回键）**：会把游戏一路退回标题页（已踩两次）。
   所有「退回」都用屏幕上左下角的返回箭头（实测 720 (53,1259)，见 side_story.json
   SideBack / SidePageDone / SideLeaveRoom）。
3. **主城判据用【主城独有】锚点，≥2 命中才算**（与 recover.json / phantom_impl 一致）；
   单看「领主战」「关卡」不算（详情页 / 列表页也有）。
4. 坐标一律 **720 空间**（MAA 把截图缩到短边 720 → 720x1280）；adb 点击走的是**设备原生
   像素**，所以进 adb 前按 ``原生短边 / 720`` 换算 —— 系数是 ``wm size`` **读**出来的
   （:func:`device_scale`），**不写死 1.5**，也不要求设备必须是某个分辨率。

为什么 OCR 走【离线自包含】而非 runner 的 tasker
------------------------------------------------
ensure_main_city(watcher) 的签名只拿到 watcher（历史调用如此），拿不到 runner 的 Tasker。
所以本模块自建一个「离线 OCR」引擎：自备 Resource（加载 assets_dir）+ 一个喂图的
CustomController + Tasker，用 pipeline 里的 OcrTask 节点对【已抓到的截图】做全屏 OCR
（与 tools/ocr_image.py 同一套做法）。这样 OCR 不占设备、不与 runner 的 tasker 抢控制器。
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
# agent 目录：page 判据（MAIN_CITY_ANCHORS）与 pipeline 定义都在这里复用，保持单源（ADR-0003）。
if str(PROJECT / "agent") not in sys.path:
    sys.path.insert(0, str(PROJECT / "agent"))

from maa.controller import AdbController, CustomController  # noqa: E402
from maa.custom_action import CustomAction  # noqa: E402
from maa.custom_recognition import CustomRecognition  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

# 主城锚点【唯一来源】：agent/phantom_impl.py（与 recover.json 一致的 6 个）。
from phantom_impl import MAIN_CITY_ANCHORS  # noqa: E402
# ★#63：主城**独有**锚点与判据也从上游单源取（不再在本文件复制一份）——
# 与 abyss_impl / wuchong_impl / 幻想 classify 取的是同一份对象，绝不漂移。
from phantom_impl import (  # noqa: E402
    MAIN_CITY_MIN_UNIQUE,
    MAIN_CITY_UNIQUE_ANCHORS,
    is_main_city_texts,
)
# ★#33：长战斗等待上限的单一真源（与 agent/side_impl 同取，绝不各自写死 300s）。
from battle_loop_core import BATTLE_GAME_CAP_SEC  # noqa: E402
# ★#104 / D9：设备独占租约（文件锁式，真源 tools/device_lease.py）★
# 同一台设备会被多个进程同时抢（真机验收 / 运维在 MFAAvalonia 里点 / 以后的子代理）。
# 租约把「连接设备」变成**独占操作**：被活租约占着就排队等（打印持有者），持有者心跳过期
# （默认 120s）视为死锁可接管，运维显式 --steal 可强抢。
# 为什么 import 放模块顶层而不是函数里：缺了 device_lease 必须**立刻**响亮失败，
# 而不是等 connect_device 跑到一半才发现这台设备根本没有独占保护。
try:  # tools/ 通常已在 sys.path（所有 runner / 测试都这么进）；被当路径导入时补一次。
    from device_lease import Lease, LeaseError  # noqa: E402
    from device_lease import acquire as _lease_acquire  # noqa: E402
except ImportError:  # pragma: no cover -- 只有「tools/ 不在 sys.path」的导入方式会走到
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from device_lease import Lease, LeaseError  # type: ignore[no-redef]  # noqa: E402
    from device_lease import acquire as _lease_acquire  # type: ignore[no-redef]  # noqa: E402

# ---------------------------------------------------------------------------
# 设备 / 坐标常量
# ---------------------------------------------------------------------------
from portable_paths import find_adb  # noqa: E402

ADB = find_adb()
# ★无默认地址★（#25）：由 connect_device 写入。留空而不是写死一个端口，是为了让
# 「忘了登记地址」变成立刻报错，而不是静默把归位点击打到已不存在的端口（#13/#24）。
ADDRESS = os.environ.get("WF_LIVE_ADDRESS", "")

# 可变槽位：runner 赋值 ca._ctrl_ref["ctrl"] = ctrl 后，本模块的一切截屏/点击都走它。
_ctrl_ref: dict[str, object] = {"ctrl": None}


# ---------------------------------------------------------------------------
# #40：按【账号身份】发现设备 —— 端口的唯一真源
# #130（脱敏 D）：型号**只用于诊断日志**，默认**不是**匹配条件
# ---------------------------------------------------------------------------
# 为什么不能再靠端口（#40 真机实证）
# ----------------------------------
# MUMA 实例会重编号，端口会漂移：任务书里假设的端口扫描首日已消失，而回归的端口上正是
# 同一台测试账号。任何写死端口的脚本都可能【连错设备】——而连错的代价可能是驱动
# 用户的真实账号。所以默认地址来源改成「按身份发现」：唯一真源就是本段，
# run_* / auto_stage / probe / live_check 一律从这里取地址。
#
# ★#130 三态（运维裁决 verbatim：用户手机型号不确定，**不许把型号写成必须匹配**）★
#   · **默认**（``WF_LIVE_EXPECT_*`` 全 unset）：**不校验**任何身份字段。型号照**读**
#     （getprop，只读），只打进诊断日志：``[device] model=<实际> (未校验)``。
#     用户一跑**不会**因为型号 red。
#   · **显式设置** ``WF_LIVE_EXPECT_MODEL`` / ``WF_LIVE_EXPECT_PRODUCT``（可选
#     ``WF_LIVE_EXPECT_DEVICE``）：归一化后**严格相等**校验；不等即抛错，并打印
#     「期望 vs 实际」（:func:`identity_mismatch`）。
#   · 环境变量名沿用 #40 的 ``WF_LIVE_EXPECT_*``（设过的机器行为不变 = 向后兼容）。
# 一句话：**读型号是为了让人看得见连到哪台，不是为了拒跑。**
#
# 身份字段用 ``getprop``（只读）读取：
#   · model   = ro.product.model      —— 机型（只读；默认不比较）
#   · product = ro.product.name       —— 产品/实例名
#   · device  = ro.product.device
# 另附只读的包名存在性（``pm list packages``）；主角色 / RANK 需 OCR 游戏画面，
# 作为 best-effort 附加字段（见 :func:`read_game_identity`），不入地址判据。

#: getprop 里构成设备身份的只读属性（字段名 -> 属性名）。
_IDENTITY_PROPS: tuple[tuple[str, str], ...] = (
    ("model", "ro.product.model"),
    ("product", "ro.product.name"),
    ("device", "ro.product.device"),
)

#: 显式期望身份的环境变量（#130）。**一个都没设 = 不校验 = 默认**。
#: 名字沿用 #40（向后兼容：以前设过它们的机器照旧严格校验）。
ENV_EXPECT_MODEL = "WF_LIVE_EXPECT_MODEL"
ENV_EXPECT_PRODUCT = "WF_LIVE_EXPECT_PRODUCT"
ENV_EXPECT_DEVICE = "WF_LIVE_EXPECT_DEVICE"

#: TCP 形态的 serial（host:port）。身份发现若命中多个，优先取它（历史 runner 用的就是它）。
_TCP_SERIAL = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d+$")
#: RANK 标签旁取数字/角色的搜索半径（720 空间，以 OCR 框为准）。
_RANK_LABEL = "RANK"


def _norm_identity(value: str) -> str:
    """归一化身份字段：大小写、连字符 / 下划线差异都不算不同设备（``A-100`` == ``A_100``）。"""
    return re.sub(r"[^0-9A-Za-z]+", "-", (value or "")).strip("-").upper()


@dataclass(frozen=True)
class DeviceIdentity:
    """一台设备的只读身份（#40）。

    核心字段（getprop，确定性）：``model`` / ``product`` / ``device``；``package`` 是
    包名存在性。``role`` / ``rank`` 是游戏内身份（主角色 / RANK），需 OCR，best-effort。
    """

    address: str = ""
    model: str = ""
    product: str = ""
    device: str = ""
    package: str | None = None
    role: str | None = None
    rank: str | None = None

    def key(self) -> str:
        """判据摘要（不含地址），用于错误信息。"""
        bits = [f"model={self.model or '?'}"]
        if self.product:
            bits.append(f"product={self.product}")
        return "/".join(bits)

    def label(self) -> str:
        """完整身份文本（日志首行用）。"""
        bits = [
            f"address={self.address or '?'}",
            f"model={self.model or '?'}",
            f"product={self.product or '?'}",
            f"device={self.device or '?'}",
            f"package={self.package or '?'}",
        ]
        if self.role:
            bits.append(f"role={self.role}")
        if self.rank:
            bits.append(f"rank={self.rank}")
        return " ".join(bits)

    def constrained(self) -> bool:
        """是否**显式**给了匹配条件（#130：默认一个都没有 = 不校验型号）。"""
        return bool(self.model or self.product or self.device)

    def describe(self) -> str:
        """把**给了的**字段写成 ``model=X / product=Y``（日志与「期望 vs 实际」用）。"""
        bits = [
            f"{name}={value}"
            for name, value in (
                ("model", self.model),
                ("product", self.product),
                ("device", self.device),
            )
            if value
        ]
        return " / ".join(bits) if bits else "（未设置，不校验）"

    def matches(self, expected: "DeviceIdentity") -> bool:
        """身份是否匹配期望：期望里**给了的**字段都必须相等；一个都没给 = 匹配（不校验）。

        #130：默认 ``expected`` 为空 → 恒 ``True`` —— **型号不是必须匹配条件**；
        只有显式设置 ``WF_LIVE_EXPECT_*`` 时才逐字段严格比较。
        """
        if expected.model and _norm_identity(self.model) != _norm_identity(expected.model):
            return False
        if expected.product and _norm_identity(self.product) != _norm_identity(expected.product):
            return False
        if expected.device and _norm_identity(self.device) != _norm_identity(expected.device):
            return False
        return True


def expected_identity() -> DeviceIdentity:
    """**显式**期望身份（#130）；一个字段都没设 = 空身份 = **不校验**（默认）。

    环境变量在**调用时**读取（不是导入时快照）：这样「跑之前 set、跑完 unset」的一次性
    显式校验可用，测试也能在同一进程里覆盖三态。
    ★这里绝不再有写死的型号默认值★ —— 那等于「型号必须匹配」，正是 #130 要拆掉的东西。
    """
    return DeviceIdentity(
        model=os.environ.get(ENV_EXPECT_MODEL, "").strip(),
        product=os.environ.get(ENV_EXPECT_PRODUCT, "").strip(),
        device=os.environ.get(ENV_EXPECT_DEVICE, "").strip(),
    )


def _adb_serial(adb: str, serial: str, *args: str) -> subprocess.CompletedProcess:
    """对【指定 serial】跑一条 adb 命令（不依赖模块级 ADDRESS，供身份发现用）。"""
    return subprocess.run([adb, "-s", serial, *args], capture_output=True)


def list_device_serials(adb: str) -> list[str]:
    """``adb devices`` 里处于 ``device`` 状态的 serial 列表（只读）。"""
    proc = subprocess.run([adb, "devices"], capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    serials: list[str] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def read_game_identity(image, assets_dir) -> tuple[str | None, str | None]:
    """从一张主城截图里 best-effort 读出 (主角色, RANK)。

    主城左上角有「主角色」名与 ``RANK`` + 数字（真机实证）。认不出就返回 (None, None)，
    绝不猜。只做 OCR，不产生任何输入。
    """
    try:
        items = ocr(image, assets_dir)
    except Exception:  # noqa: BLE001 -- 游戏内身份是附加信息，读不出不影响地址发现
        return None, None
    rank_box = None
    for text, box in items:
        # 真机 OCR 常把标签读成「I RANK」/「IRANK」（左侧图标被并进来），故取子串匹配。
        if _RANK_LABEL in re.sub(r"[^0-9A-Za-z]", "", (text or "")).upper():
            rank_box = box
            break
    if rank_box is None:
        return None, None
    rx, ry, rw, rh = rank_box
    rank = None
    best: tuple[str, list[int]] | None = None
    for text, box in items:
        t = (text or "").strip()
        if not t.isdigit():
            continue
        cx, _cy = _center(box)
        # RANK 值就贴在标签下方；再往下的 RP/EXP（如 12146）不算。取最靠近标签的那个。
        if ry <= box[1] <= ry + rh + 60 and abs(cx - (rx + rw / 2)) < 140:
            if best is None or box[1] < best[1][1]:
                best = (t, box)
    if best is not None:
        rank = best[0]
    role = None
    best_role: tuple[str, list[int]] | None = None
    for text, box in items:
        t = (text or "").strip()
        if not t:
            continue
        cx, cy = _center(box)
        if ry - 120 <= cy < ry and abs(cx - (rx + rw / 2)) < 180:
            if best_role is None or box[1] > best_role[1][1]:
                best_role = (t, box)
    if best_role is not None:
        role = best_role[0]
    return role, rank


def read_identity(adb: str, address: str, *, image=None, assets_dir=None) -> DeviceIdentity:
    """只读读取一台设备的身份：getprop（机型 / 产品名 / device）+ 包名（+ 可选 OCR 主角色/RANK）。"""
    fields: dict[str, str] = {}
    for name, prop in _IDENTITY_PROPS:
        proc = _adb_serial(adb, address, "shell", "getprop", prop)
        fields[name] = (proc.stdout or b"").decode("utf-8", "replace").strip()

    package: str | None = None
    proc = _adb_serial(adb, address, "shell", "pm", "list", "packages", PKG)
    if f"package:{PKG}" in (proc.stdout or b"").decode("utf-8", "replace"):
        package = PKG

    role = rank = None
    if image is not None and assets_dir is not None:
        role, rank = read_game_identity(image, assets_dir)

    return DeviceIdentity(
        address=address,
        model=fields.get("model", ""),
        product=fields.get("product", ""),
        device=fields.get("device", ""),
        package=package,
        role=role,
        rank=rank,
    )


def discover_devices(adb: str | None = None) -> list[tuple[str, DeviceIdentity]]:
    """枚举当前在线设备及其身份（只读：``adb devices`` + 逐台 getprop）。"""
    adb = adb or ADB
    return [(serial, read_identity(adb, serial)) for serial in list_device_serials(adb)]


def resolve_address(
    adb: str | None = None,
    expected: DeviceIdentity | None = None,
    *,
    devices: list[tuple[str, DeviceIdentity]] | None = None,
) -> str:
    """解析设备地址（#40 身份发现；#130 型号**默认不参与**）。

    优先级：
      1. 环境变量 ``WF_LIVE_ADDRESS``（显式覆盖，用户明确指定）；
      2. 身份发现：枚举在线设备。
         · **默认（``WF_LIVE_EXPECT_*`` 全 unset）**：型号/产品名**不参与**筛选 ——
           恰好一台在线设备就用它（地址唯一即可）；多台则**报错**请用 ``WF_LIVE_ADDRESS``
           指定（绝不随机赌一台）。★不会因为型号不符而 red★（运维裁决 #130）；
         · **显式设置**：只取匹配 ``expected`` 的那台（归一化后严格相等）；多个匹配时
           优先 TCP host:port，仍不唯一则**报错**（宁可拒绝，不赌一个）。

    任何情况下都**不**回退到写死的端口。
    """
    adb = adb or ADB
    env_addr = os.environ.get("WF_LIVE_ADDRESS", "").strip()
    if env_addr:
        return env_addr
    expected = expected or expected_identity()
    found = devices if devices is not None else discover_devices(adb)
    seen = [(a, i.key()) for a, i in found]

    if not expected.constrained():
        # #130 默认路径：**不比较型号**，只要求「能唯一确定一台设备」。
        if not found:
            raise RuntimeError(
                "身份发现失败：没有在线设备（adb devices 为空）。"
                " 请启动模拟器 / 连接手机，或用 WF_LIVE_ADDRESS 显式指定地址。"
            )
        if len(found) > 1:
            raise RuntimeError(
                f"发现 {len(found)} 台在线设备，但未设置 WF_LIVE_EXPECT_*"
                f"（默认不校验型号，无法按身份挑一台）：{seen}。"
                "请用 WF_LIVE_ADDRESS 明确指定要连哪一个（绝不随机赌一台）；"
                " 若确实想按型号 / 产品名筛选，再设置 WF_LIVE_EXPECT_MODEL / "
                "WF_LIVE_EXPECT_PRODUCT。"
            )
        address, identity = found[0]
        log_device_identity(identity, expected)  # 只读诊断：model=... (未校验)
        return address

    matched = [addr for addr, ident in found if ident.matches(expected)]
    if not matched:
        raise RuntimeError(
            f"身份发现失败：没有在线设备匹配显式期望 {expected.describe()}"
            f"（实际发现 {seen}）。请确认设备已启动；或用 WF_LIVE_ADDRESS 显式指定地址；"
            " 或 unset WF_LIVE_EXPECT_* 按「不校验型号」运行（#130 默认）。"
        )
    tcp = [a for a in matched if _TCP_SERIAL.match(a)]
    pool = tcp or matched
    if len(pool) > 1:
        raise RuntimeError(
            f"身份发现不唯一：{pool} 都匹配 {expected.describe()}；"
            " 请用 WF_LIVE_ADDRESS 明确指定要连哪一个（绝不随机赌一台）。"
        )
    return pool[0]


def log_device_identity(
    identity: DeviceIdentity, expected: DeviceIdentity | None = None
) -> None:
    """把读到的设备身份打进日志（#130：型号**读**出来只为诊断，默认**不比较**）。

    每次登记打印两行，分别照顾两类读者：
      · ``[harness] 设备身份 address=… model=… （未设置期望，不校验）``
        —— 票面要求的诊断行：「到底校没校验」一眼可见；
      · ``[device] model=<实际> (未校验)`` —— 型号短行（固定格式，便于 grep）。
    显式设置时同样两行，但标出「校验」与**期望值**；真正失败时
    :func:`identity_mismatch` 还会打印「期望 vs 实际」。
    """
    expected = expected or expected_identity()
    if expected.constrained():
        print(f"[harness] 设备身份 {identity.label()} （校验 {expected.describe()}）", flush=True)
        print(
            f"[device] model={identity.model or '?'} (校验: 期望 {expected.describe()})",
            flush=True,
        )
    else:
        print(f"[harness] 设备身份 {identity.label()} （未设置期望，不校验）", flush=True)
        print(f"[device] model={identity.model or '?'} (未校验)", flush=True)


def identity_mismatch(identity: DeviceIdentity, expected: DeviceIdentity) -> str | None:
    """返回不匹配的原因文本；匹配**或期望为空（不校验）**返回 ``None``。纯函数，便于离线断言。"""
    if not expected.constrained() or identity.matches(expected):
        return None
    return (
        f"设备身份与显式期望不匹配：期望 {expected.describe()}；实际 {identity.describe()}"
        f"（{identity.label()}）。拒绝执行（防止误驱动别的账号）。"
        " ★型号不是必须匹配条件（#130）★：想连这台而不校验，请 unset "
        f"{ENV_EXPECT_MODEL} / {ENV_EXPECT_PRODUCT}；"
        " 要校验就把它们设成上面「实际」里的值。"
    )


def assert_device_identity(
    adb: str, address: str, expected: DeviceIdentity | None = None
) -> DeviceIdentity:
    """只读读取设备身份并打印诊断日志；**只有显式期望非空时才校验**（#130）。

    默认（``WF_LIVE_EXPECT_*`` 全 unset）：读到什么就打印什么（``(未校验)``），**绝不**因
    型号不符而拒绝执行 —— 用户手机型号不确定（运维裁决）。
    显式设置：归一化后严格相等；不等即抛 ``RuntimeError``，并打印期望 vs 实际。

    与 :func:`connect_device` 的 ``expect=`` 是同一条守卫；独立成函数便于「先报身份再连」的
    runner 明确表达「这一步就是设备身份日志 + 可选守卫」。返回读到的身份。
    """
    expected = expected or expected_identity()
    identity = read_identity(adb, address)
    log_device_identity(identity, expected)
    problem = identity_mismatch(identity, expected)
    if problem:
        raise RuntimeError(problem)
    return identity


# ---------------------------------------------------------------------------
# 设备登记：【唯一】入口（#25）；#40 起带身份发现 + 身份守卫
# ---------------------------------------------------------------------------
def _require_address(address: str) -> str:
    """地址为空即报错：把「忘了同步地址」从静默空点变成响亮失败。

    #13/#24 的根因是 runner 只把地址给了 AdbController、没同步给本模块，归位 adb_tap
    于是打到一个写死的默认地址（早已不存在）——设备上没有任何反馈。
    """
    if not address:
        raise RuntimeError(
            "live_harness 未登记设备地址：请先调用 "
            "live_harness.connect_device(adb, address)（#25 取消了硬编码默认地址；"
            "#40 起 address 可省略，缺省按身份发现设备）"
        )
    return address


# ---------------------------------------------------------------------------
# #104 / D9：设备独占租约 —— 连接前必拿，退出必放
# ---------------------------------------------------------------------------
# 本进程当前持有的租约（None = 没拿）。★模块级唯一槽位★：connect_device 拿、
# release_device_lease 放。runner 的收尾 finally 里调 release_device_lease()，
# 让排队的人立刻能接；来不及（崩溃 / 被杀）则由 device_lease 的 atexit 与 TTL 兜底。
_DEVICE_LEASE: dict = {"lease": None}


def lease_owner() -> str:
    """本进程的租约 owner 文案（形如 ``runner:12345``）——排队的人看到的就是它。"""
    return f"runner:{os.getpid()}"


def held_device_lease() -> "Lease | None":
    """本进程当前持有的租约（没有则 ``None``）；只读，别拿它去 release（用 release_device_lease）。"""
    lease = _DEVICE_LEASE.get("lease")
    return lease if isinstance(lease, Lease) else None


def _acquire_device_lease(address: str, *, steal: bool = False) -> "Lease":
    """连接**之前**拿这台设备的独占租约（#104 / D9）。

    * 已有活租约占着（别人的 runner / 运维在 GUI 里跑）-> **排队等**，打印持有者；
    * 持有者心跳过期（默认 ttl=120s，``auto_heartbeat`` 每 ttl/3 自动续）-> 接管并打印；
    * ``steal=True``（运维显式 ``--steal``）-> 强抢活租约并打印被抢者。

    同一进程对**同一地址**重复登记（runner 先报身份再连、测试 patch 掉 AdbController 再连）
    只续租、不重复占 —— 否则会自己等自己等到天荒地老。
    """
    current = _DEVICE_LEASE.get("lease")
    if isinstance(current, Lease) and current.serial == address and current.is_mine():
        current.heartbeat()  # 同地址重复登记：续租即可
        print(f"[harness] 设备租约已在手（{address}），续租")
        return current
    if current is not None:
        release_device_lease()  # 换了设备：先把旧的还回去，绝不一人占两台
    lease = _lease_acquire(address, lease_owner(), steal=steal, auto_heartbeat=True)
    _DEVICE_LEASE["lease"] = lease
    return lease


def release_device_lease() -> bool:
    """放掉本进程持有的设备租约（幂等：没持有返回 ``False``）。

    runner 收尾（``finally``）调它 = 立刻把设备让给排队的人；不调也不会永久占着
    （atexit 兜底 + 心跳过期后排队者接管），但会让下一个人白等一个 TTL。
    """
    lease = _DEVICE_LEASE.get("lease")
    _DEVICE_LEASE["lease"] = None
    if not isinstance(lease, Lease):
        return False
    try:
        return bool(lease.release())
    except LeaseError as exc:  # 释放失败不该盖掉 runner 真正的收尾原因
        print(f"[harness] 释放设备租约失败（{exc}）：等心跳过期后由排队者接管")
        return False


def connect_device(
    adb: str,
    address: str | None = None,
    *,
    require: bool = True,
    expect: "DeviceIdentity | None" = None,
    steal: bool = False,
) -> "AdbController":
    """【唯一】登记设备的入口：构造 AdbController、连接、同步 ADDRESS + _ctrl_ref。

    ★为什么必须把这一步收敛成一个函数（#25）★
    runner 过去各自写「三件套」::

        ctrl = AdbController(adb, address)
        ca.ADDRESS = address          # ← 常常漏掉（#24 只补了 run_special_live 一处）
        ca._ctrl_ref["ctrl"] = ctrl

    漏掉中间那行时，AdbController 连的是真设备，但本模块 adb_tap（归位用）仍打模块级
    ADDRESS —— 过去它默认一个已不存在的端口，于是静默点到空设备上。现在设备地址
    **只有一个来源**，runner 只要调本函数就不可能再漏；`_adb` 还会在地址为空时立刻报错。

    #40：
      · ``address`` 可为 None —— 缺省时经 :func:`resolve_address` 按账号身份发现设备
        （不再有任何端口字面量）；
      · ``expect`` 非 None 时，连接前**只读**读取设备身份并打进**日志首行**。是否**校验**
        取决于它有没有字段（#130 三态）：
          - 传 ``expected_identity()`` 且 ``WF_LIVE_EXPECT_*`` 全 unset → 只打印
            ``[device] model=... (未校验)``，**绝不**拒绝执行（默认路径）；
          - 显式设置了环境变量（或调用方给了具体字段）→ 严格相等校验，不匹配即抛
            RuntimeError（拒绝执行，绝不误驱动别的账号）。

    require=True（默认）：连接失败即抛 RuntimeError（真机 runner 期望的行为）。
    require=False：仍登记地址，仅把连接结果留给调用方自行判断（如 run_pipeline.py）。

    #104 / D9（设备独占租约，见 :mod:`device_lease`）：
      · 连接**之前**先用 ``owner="runner:<pid>"`` 拿这台设备的独占租约；被活租约占着就
        **排队等**（打印持有者），持有者心跳过期（默认 120s）视为死锁可接管；
      · ``steal=True`` = 运维显式 ``--steal``：强抢活租约并打印被抢者（runner 把
        ``--steal`` 透传到这里即可）；缺省 False = 排队等，不抢；
      · 连不上 / 中途抛错立刻还租；进程退出由 ``atexit`` 兜底。runner 收尾的
        ``finally`` 里调 :func:`release_device_lease`，能让排队的人立刻接手。
    """
    global ADB, ADDRESS
    given = (address or "").strip()
    if given:
        source = "参数"
        address = given
    else:
        source = "身份发现"
        address = resolve_address(adb, expect)
    address = _require_address(address)
    ADB = adb
    ADDRESS = address

    if expect is not None:
        assert_device_identity(adb, address, expect)

    # ★#104 / D9：连接前先拿设备独占租约★ —— 同一台设备同时只能有一个驱动者。
    # 被活租约占着就排队等（打印持有者）；持有者心跳过期（默认 120s）视为死锁可接管；
    # 运维显式 --steal 可强抢。失败路径（连不上 / 中途抛错）立刻还租，绝不让排队的人
    # 干等一个根本没连上的持有者；进程退出的最后一道是 device_lease 的 atexit。
    _acquire_device_lease(address, steal=steal)

    ctrl = AdbController(adb, address)
    try:
        connected = ctrl.post_connection().wait().succeeded
    except BaseException:  # 连接被打断 / 框架抛错：先把租约还回去再让异常传播
        release_device_lease()
        raise
    if not connected:
        # 没连上 = 本进程没在用这台设备：立刻还租（require=False 时也还，ADDRESS 仍登记）。
        release_device_lease()
        if require:
            raise RuntimeError(f"设备连接失败：{address}")
    _ctrl_ref["ctrl"] = ctrl
    print(f"[harness] 设备已登记 address={address} source={source} connected={connected}")
    return ctrl

# 运行时产物目录（截图 / 独立账本 / 进度文件）。默认写系统临时目录，避免污染仓库工作树；
# runner 用 ca.WORK_DIR 取代原先硬编码的 %TEMP%\opencode 路径。
WORK_DIR = Path(os.environ.get("WF_LIVE_WORK", str(Path(tempfile.gettempdir()) / "opencode")))
# 截图输出目录（证据用）。
SHOT_DIR = Path(os.environ.get("WF_LIVE_SHOTS", str(WORK_DIR)))


# ---------------------------------------------------------------------------
# 启动期资源开关 + 运行期产物上界（#perf：内存 / CPU / 磁盘）
# ---------------------------------------------------------------------------
# ★为什么把这两件事收敛成一个入口（真机实测，不是猜）★
# live runner 过去各自写 ``Toolkit.init_option(str(PROJECT))``，于是「怎么跑」只能由
# ``config/maa_option.json`` 决定 —— 而那是**每个 checkout 一份、不进版本库**的运行期文件
# （``.gitignore`` 第 453 行 ``config``）。实测那台机器的副本里它是 ``save_draw: true``，
# 而**框架自己的默认值是 false**（用空目录调 init_option 复现过）。代价：
#   · 每一次识别都往 ``debug/vision`` 落一张约 290 KB 的 jpg（文件名形如
#     ``<ts>_OcrTask_<job>.jpg``——正是【全屏 OcrTask】那一类）；
#   · 实测 ``debug/vision`` = 59 760 个文件 / 13.5 GB；单次运行约 5 000 张/小时
#     ≈ 1.4 GB/小时（标题页守护每秒一次全屏 OcrTask + 各自定义识别复用同一节点）；
#   · 离线 A/B（同一张 1080p 帧、60 次 OcrTask，唯一变量是 save_draw）：
#     开 = 61 张帧 / 32.9 MB / 7.39 s CPU；关 = 0 张帧 / 8.14 s CPU（即 +10 ms CPU/次）。
# 轮转日志同样没有上界：``maafw.log`` 每 ~16 MB 轮成 ``maafw.bak.*``（实测 118 个 = 1.9 GB），
# ``debug/on_error`` 亦无上界（实测 237 个 / 127 MB）。
#
# ★设计原则（三条，都是为了「不改变行为」）★
#   · save_draw **默认关**（= 框架自己的默认）：要临时抓帧调试设 ``WF_SAVE_DRAW=1`` 即可，
#     不必再去改运行期配置文件；``save_on_error`` 完全不受影响，失败帧照留（
#     #20/#26 的排障能力不变）。
#   · 上界只删【最旧的】、保留最新 N 个（``WF_KEEP_VISION`` / ``WF_KEEP_LOG`` /
#     ``WF_KEEP_ON_ERROR``，填 0 = 完全不上界）：所以「先跑一遍、再回来翻刚才那几帧」
#     的流程仍然可用 —— 删掉的永远是最老的那些。
#   · 只在【启动时】调用一次（见 :func:`apply_global_options`）：此刻本次运行还没写任何帧，
#     因此绝不会删掉本次运行留下的证据。
VISION_KEEP_DEFAULT = 2000
LOG_KEEP_DEFAULT = 5
ON_ERROR_KEEP_DEFAULT = 50

#: 轮转日志的形态；``maafw.log`` 本体正在被框架写，★绝不碰★。
_BAK_LOG_PREFIX = "maafw.bak."


def _env_flag(name: str, default: bool = False) -> bool:
    """环境变量开关：``1/true/yes/on`` 为真，``0/false/no/off`` 为假，未设取 default。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int) -> int:
    """环境变量整数：非法/未设取 default；负数按 0（= 不上界）处理。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


def _prune_oldest(files: list[Path], keep: int, *, dry_run: bool) -> tuple[int, int]:
    """按 mtime 保留最新 ``keep`` 个、删除更旧的；返回 (删除数, 释放字节)。

    ``keep <= 0`` = 不上界（一个都不动）。统计失败按 0 处理，绝不因清理出错而中断启动。
    """
    if keep <= 0 or len(files) <= keep:
        return 0, 0
    try:
        ordered = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return 0, 0
    removed, freed = 0, 0
    for path in ordered[keep:]:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        removed += 1
        freed += size
    return removed, freed


def bound_debug_artifacts(
    project: str | Path,
    *,
    vision_keep: int | None = None,
    log_keep: int | None = None,
    on_error_keep: int | None = None,
    dry_run: bool = False,
) -> dict:
    """把 ``<project>/debug`` 下的排障产物收敛到【上界】（只删最旧的）。返回统计。

    上界（环境变量可覆盖；0 = 不上界 = 保留全部）：
      · ``debug/vision/*``         —— save_draw 的帧；默认留最新 2000 个（``WF_KEEP_VISION``）
      · ``debug/maafw.bak.*.log``  —— 轮转日志；默认留最新 5 个（``WF_KEEP_LOG``）
      · ``debug/on_error/*``       —— 失败帧；默认留最新 50 个（``WF_KEEP_ON_ERROR``）

    ``debug/maafw.log``（框架正在写）以及任何其他文件都【不动】。纯离线，可随时单跑：
    ``python tools/live_harness.py --bound-debug [--project DIR] [--dry-run]``。
    """
    debug = Path(project) / "debug"
    if not debug.is_dir():
        return {}
    plan = (
        ("vision", debug / "vision",
         vision_keep if vision_keep is not None else _env_int("WF_KEEP_VISION", VISION_KEEP_DEFAULT)),
        ("logs", debug,
         log_keep if log_keep is not None else _env_int("WF_KEEP_LOG", LOG_KEEP_DEFAULT)),
        ("on_error", debug / "on_error",
         on_error_keep if on_error_keep is not None else _env_int("WF_KEEP_ON_ERROR", ON_ERROR_KEEP_DEFAULT)),
    )
    stats: dict = {}
    for label, root, keep in plan:
        if not root.is_dir():
            continue
        files: list[Path] = []
        for path in root.iterdir():
            if not path.is_file():
                continue
            if label == "logs" and not path.name.startswith(_BAK_LOG_PREFIX):
                continue  # maafw.log / 其它文件绝不碰
            files.append(path)
        removed, freed = _prune_oldest(files, keep, dry_run=dry_run)
        stats[label] = {
            "seen": len(files),
            "kept": len(files) - removed,
            "removed": removed,
            "freed_mb": freed / (1024 * 1024),
            "dry_run": dry_run,
        }
    return stats


def apply_global_options(
    project: str | Path,
    *,
    save_draw: bool | None = None,
    bound_debug: bool = True,
) -> bool:
    """【唯一】启动入口：``Toolkit.init_option`` + save_draw 默认关 + debug 产物上界。

    与旧的 ``Toolkit.init_option(str(PROJECT))`` 同返回值（bool），runner 平移即可。
    本函数【只动资源开销】，不碰任何业务行为：不注册识别、不点屏幕、不决定流程。

    save_draw：
      · 缺省（``save_draw=None``）取环境变量 ``WF_SAVE_DRAW``（未设 = **关**）；
      · 显式传 True/False 可用于测试/嵌入方覆盖。
    要临时抓帧调试就 ``WF_SAVE_DRAW=1`` —— 不必去改 ``config/maa_option.json``
    （那是每个 checkout 一份、不进版本库的运行期文件）。
    """
    ok = Toolkit.init_option(str(project))
    want = _env_flag("WF_SAVE_DRAW", default=False) if save_draw is None else bool(save_draw)
    try:
        Tasker.set_save_draw(want)
    except Exception as exc:  # noqa: BLE001 -- 设置失败不阻断真机运行（保持框架当前值）
        print(f"[harness] set_save_draw({want}) 失败，保持框架当前值：{exc}")
    else:
        print(
            f"[harness] save_draw={'on' if want else 'off'}"
            "（要临时抓帧：WF_SAVE_DRAW=1；失败帧仍由 save_on_error 保留）"
        )
    if bound_debug:
        try:
            stats = bound_debug_artifacts(project)
        except Exception as exc:  # noqa: BLE001 -- 清理失败不阻断真机运行
            print(f"[harness] debug 产物上界失败（忽略）：{exc}")
        else:
            for label, s in stats.items():
                if s["removed"]:
                    print(
                        f"[harness] debug/{label} 上界：删最旧 {s['removed']} 个 / "
                        f"{s['freed_mb']:.1f} MB（留最新 {s['kept']}）"
                    )
    return ok


def _bound_debug_cli(argv: list[str]) -> int:
    """``python tools/live_harness.py --bound-debug [--project DIR] [--dry-run]``。

    离线维护入口：不连设备、不加载资源，只把 debug 产物收敛到上界（默认真删；
    ``--dry-run`` 只打印）。
    """
    project = PROJECT
    dry = "--dry-run" in argv
    if "--project" in argv:
        i = argv.index("--project")
        if i + 1 < len(argv):
            project = Path(argv[i + 1])
    stats = bound_debug_artifacts(project, dry_run=dry)
    if not stats:
        print(f"没有 debug 目录：{Path(project) / 'debug'}")
        return 0
    for label, s in stats.items():
        verb = "将删" if dry else "删"
        print(
            f"debug/{label}: 见 {s['seen']} 个，{verb} 最旧 {s['removed']} 个 / "
            f"{s['freed_mb']:.1f} MB，留 {s['kept']} 个"
            + ("（dry-run，未改动）" if dry else "")
        )
    return 0


#: MaaFramework 识别空间的**短边**（720 → 720x1280）。这是**换算基准**，不是对设备分辨率
#: 的要求：设备原生分辨率由 ``wm size`` 读出来再换算（见 :func:`device_scale`）。
BASE_SHORT_SIDE = 720
#: 读不到 ``wm size`` 时的历史回退系数（= 1080p）。**会打印警告**，绝不静默。
DEFAULT_SCALE = 1080.0 / 720.0

# 底部导航「主城」的 ROI（720 空间）——照抄 recover.json::RecoverTapMainCityNav。
BOTTOM_NAV_ROI = [0, 1180, 720, 100]
# 屏幕左下角「返回」箭头（720 空间）——照抄 side_story.json::SideBack/SidePageDone。
BACK_BUTTON = (53, 1259)
# 外传故事列表页「未通关」筛选 tab（720 空间）——照抄 side_story.json::SideClearPickTab。
SIDE_UNPASSED = (119, 405)

# ★#28 结算 / 奖励 / 升级结算页的可见文案★（照抄 common.json 的三条公共判据，单源不另造）：
#   · ^继续$ / ^OK$            —— PubResultContinueText（结算页【继续】/【OK】按钮）
#   · QUESTRE                  —— PubQuestResultText（结算页顶部横幅；OCR 常把 QUESTRESULT
#                                 截断成 QUESTRE，故用子串，不锚定）
#   · 等级提升 / 等级最大 / 经验值 —— PubLevelUpText（升级结算页；该页常常读不到「继续」二字）
# 这些页面【没有底部导航】（无「主城」/「返回」），所以下面的 bottom_nav_mc / back_page 两条
# 规则都够不着它——这正是 #26「收工停在结算页 → 归位 step0 未知页面，停手」的缺口。
SETTLEMENT_TEXTS = (r"^继续$", r"^OK$", r"QUESTRE", r"等级提升", r"等级最大", r"经验值")
# 升级结算页底部固定的「继续」按钮中心（720 空间）——照抄 common.json::PubLevelUpContinue
# 的 action.target（该页读不到按钮文字时靠这个【绝对坐标】推进，同 phantom/raid 已验证做法）。
LEVEL_UP_CONTINUE = (358, 1198)

# 游戏包名（冷启动 / 判活用）——与 #20 phantom_restart 同一默认（com.leiting.wf），
# 可被环境变量覆盖。归位在「游戏未启动（Android 桌面 / 崩溃）」时靠它确定性拉起。
PKG = os.environ.get("WF_LIVE_PKG", "com.leiting.wf")


# ---------------------------------------------------------------------------
# 底层：adb / 截屏
# ---------------------------------------------------------------------------
def _adb(*args: str) -> subprocess.CompletedProcess:
    # _require_address：未登记地址就报错，绝不静默把点击打到空设备（#25）。
    return subprocess.run([ADB, "-s", _require_address(ADDRESS), *args], capture_output=True)


# ---------------------------------------------------------------------------
# #130：坐标**换算**（720 短边识别空间 -> 设备原生像素）—— 不是分辨率**断言**
# ---------------------------------------------------------------------------
# 为什么需要换算：MaaFramework 的识别空间是「短边 720」（720x1280），而 ``adb shell input tap``
# 吃的是**原生像素**。所以 720 坐标进 adb 之前必须乘 ``原生短边 / 720``。
# 历史实现把系数写死成 ``1080 / 720 = 1.5`` —— 那是一个**隐含断言**「设备就是 1080p」：
# 720p 设备上会把点打到 1.5 倍远处（屏幕外），而没有任何报错。#130 起改成**读**一次
# ``wm size`` 再换算；1080p 设备的结果与旧行为逐像素一致（1.5），别的分辨率也各得其所。
# ★没有「分辨率必须等于 X」的校验★：换算不出来时只回退历史值并打印警告。
_DISPLAY_CACHE: dict = {"address": None, "size": None, "scale": None}


def read_display_size() -> tuple[int, int] | None:
    """只读读取设备显示分辨率（``adb shell wm size``）；读不到返回 ``None``。

    优先 ``Override size``（``wm size`` 覆盖后的逻辑尺寸，= adb input 的坐标系），
    其次 ``Physical size``。★只读：不修改任何显示设置★。
    """
    try:
        out = _adb("shell", "wm", "size").stdout.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 -- 读不到分辨率不该让点击直接失败（有回退）
        print(f"[device] wm size 读取失败：{exc}")
        return None
    m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(
        r"Physical size:\s*(\d+)x(\d+)", out
    )
    if m is None:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if w > 0 and h > 0 else None


def device_scale() -> float:
    """720 空间 -> 设备原生像素的**换算系数**（#130：读出来的，不是写死的断言）。

    ``scale = 原生短边 / 720``：竖屏 1080x1920 -> 1.5；720x1280 -> 1.0；1440x2560 -> 2.0。
    每台设备只读一次 ``wm size`` 并缓存；读不到时回退 :data:`DEFAULT_SCALE`（1080p 历史值）
    并**打印警告**（绝不静默）。
    """
    address = ADDRESS
    cached = _DISPLAY_CACHE
    if cached.get("address") == address and cached.get("scale") is not None:
        return float(cached["scale"])
    size = read_display_size()
    if size is None:
        scale = DEFAULT_SCALE
        print(
            f"[device] 读不到 wm size（address={address or '?'}）-> 按 1080p 假定换算 "
            f"×{scale:g}（回退，不是校验）"
        )
    else:
        scale = min(size) / BASE_SHORT_SIDE
        print(
            f"[device] 分辨率 {size[0]}x{size[1]} -> 720 空间换算 ×{scale:g}"
            "（换算，不是校验）"
        )
    _DISPLAY_CACHE.update(address=address, size=size, scale=scale)
    return scale


def adb_tap(x720: float, y720: float) -> None:
    """按 720 空间坐标点击设备（× **设备实际**换算系数还原到原生像素）。仅作确认后的落实动作。"""
    scale = device_scale()
    dx, dy = int(round(x720 * scale)), int(round(y720 * scale))
    _adb("shell", "input", "tap", str(dx), str(dy))
    print(f"[harness] adb_tap 720=({x720:.0f},{y720:.0f}) device=({dx},{dy}) scale={scale:g}")


def grab() -> np.ndarray:
    """抓当前屏幕，返回 BGR ndarray（720x1280x3）。"""
    ctrl = _ctrl_ref.get("ctrl")
    if ctrl is None:
        raise RuntimeError("harness 尚未拿到 controller（先调用 live_harness.connect_device(...)）")
    job = ctrl.post_screencap().wait()
    img = job.get()
    if img is None:
        img = getattr(ctrl, "cached_image", None)
    if img is None:
        raise RuntimeError("screencap 失败")
    return img


def screenshot(name: str) -> Path:
    """抓屏并落盘 clr_<name>.png（历史命名），返回路径。"""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"clr_{name}.png"
    img = grab()
    from PIL import Image

    Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(path)
    print(f"[harness] 截图 {path.name}")
    return path


# ---------------------------------------------------------------------------
# 离线 OCR（自包含；不占设备、不借 runner 的 tasker）
# ---------------------------------------------------------------------------
class _ImageController(CustomController):
    """把一张已抓到的图喂给 MAA 做识别（与 tools/ocr_image.py 同套）。"""

    def __init__(self) -> None:
        super().__init__()
        self.img: np.ndarray | None = None

    def connect(self) -> bool:  # noqa: D102
        return True

    def request_uuid(self) -> str:  # noqa: D102
        return "0"

    def screencap(self) -> np.ndarray:  # noqa: D102
        assert self.img is not None
        return self.img


_OCR_LOCK = threading.Lock()
_OCR_TASKER: Tasker | None = None
_OCR_CTRL: _ImageController | None = None
_OCR_ASSETS: Path | None = None


def _ensure_ocr(assets_dir: Path) -> tuple[Tasker, _ImageController]:
    global _OCR_TASKER, _OCR_CTRL, _OCR_ASSETS
    with _OCR_LOCK:
        if _OCR_TASKER is not None and _OCR_ASSETS == assets_dir:
            return _OCR_TASKER, _OCR_CTRL  # type: ignore[return-value]
        # ★这里曾经直写 Toolkit.init_option(str(PROJECT))★ —— 真机实证：那会【重新读一遍】
        # config/maa_option.json，把 runner 启动时已经关掉的 save_draw 又【打回 true】
        # （本函数是懒加载，在 TitleWatcher 构造时才第一次跑到，晚于 apply_global_options）。
        # 于是「启动时关掉」形同虚设：一次运行照旧落 ~600 张 ~20 MB 的帧。
        # 现在走同一条启动缝 apply_global_options（bound_debug=False：只重申开关，不重复清理）。
        apply_global_options(PROJECT, bound_debug=False)
        res = Resource()
        ok = res.post_bundle(str(assets_dir)).wait().succeeded
        if not ok:
            raise RuntimeError(f"离线 OCR 资源加载失败: {assets_dir}")
        ctrl = _ImageController()
        ctrl.set_screenshot_use_raw_size(True)
        ctrl.post_connection().wait()
        tasker = Tasker()
        tasker.bind(res, ctrl)
        _OCR_TASKER, _OCR_CTRL, _OCR_ASSETS = tasker, ctrl, assets_dir
        return tasker, ctrl


def ocr(image: np.ndarray, assets_dir: Path) -> list[tuple[str, list[int]]]:
    """对一张 720 空间 BGR 图做全屏 OCR（走 pipeline 的 OcrTask），返回 [(text, box720)]。"""
    tasker, ctrl = _ensure_ocr(assets_dir)
    ctrl.img = np.ascontiguousarray(image)
    job = tasker.post_task("OcrTask", {})
    job.wait()
    detail = job.get()
    items: list[tuple[str, list[int]]] = []
    if detail is None:
        return items
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        for r in reco.all_results or []:
            box = getattr(r, "box", None)
            if not box or len(box) != 4:
                continue
            items.append(((getattr(r, "text", "") or "").strip(), [int(v) for v in box]))
    return items


# ---------------------------------------------------------------------------
# 页面判据 / 小工具
# ---------------------------------------------------------------------------
def _center(box: list[int]) -> tuple[int, int]:
    x, y, w, h = box
    return int(x + w / 2), int(y + h / 2)


def _pick(
    items: list[tuple[str, list[int]]],
    patterns: str | list[str],
    roi: list[int] | None = None,
) -> list[int] | None:
    """在 OCR 结果里找第一个匹配 `patterns` 的框（可选限定在 roi 内）；返回 box720。"""
    pats = [patterns] if isinstance(patterns, str) else patterns
    regs = [re.compile(p) for p in pats]
    for text, box in items:
        if not any(r.search(text or "") for r in regs):
            continue
        if roi is not None:
            cx, cy = _center(box)
            rx, ry, rw, rh = roi
            if not (rx <= cx <= rx + rw and ry <= cy <= ry + rh):
                continue
        return box
    return None


def _has(items: list[tuple[str, list[int]]], patterns: str | list[str], roi=None) -> bool:
    return _pick(items, patterns, roi) is not None


def _texts(items: list[tuple[str, list[int]]]) -> list[str]:
    return [t for t, _ in items if t]


# ★主城判据：只用【主城独有】锚点（#31 危险误判的设备实证）★
#
# 上游单源 `phantom_impl.MAIN_CITY_ANCHORS` 的六个锚点里，只有三个是主城**独有**的：
#   · `活动`   —— 领主战列表页顶部有「活动进行中！」，会命中（真机帧 sweep_lord_02.ocr.txt）；
#   · `领主战` —— 领主战列表页的成员行前缀 / 主城右下入口（两处都有）；
#   · `关卡`   —— 关卡列表 / 详情页也有。
# 若仍按「六锚点里任意 ≥2」判定，**领主战列表页**（活动 + 领主战）会被当成主城：
# 归位在【没到家】时直接报「已在主城」返回 True、不点「主城」——下一个任务随即起不来
# （#31 gap2，真机 Stage 战役实证，危险）。故收紧为「三独有锚点 ≥2」。
# ★#63：这两个常量不再在本文件复制 —— 从上游单源 agent/battle_loop_core import（经
# phantom_impl re-export），与 abyss_impl / wuchong_impl 取同一份对象（#31 harness 守卫
# 原样保留，只是改从共享源取，绝不各自复制一份 —— 复制即漂移）。

# 与上游单源对账：独有集必须是 MAIN_CITY_ANCHORS 的子集（上游改名 -> 立刻响亮失败，
# 不静默收紧到空集而永远判不出主城）。
assert set(MAIN_CITY_UNIQUE_ANCHORS) <= set(MAIN_CITY_ANCHORS), (
    f"主城独有锚点 {MAIN_CITY_UNIQUE_ANCHORS} 不在 MAIN_CITY_ANCHORS={MAIN_CITY_ANCHORS} 里"
)


def _is_main_city(items: list[tuple[str, list[int]]]) -> bool:
    """主城：**主城独有**锚点 ≥2 命中（#31 收紧；不再用会被列表页命中的六锚点规则）。

    只用 `修行之道` / `成长任务` / `当前进度` 这三个主城独有判据（见上）。这样领主战列表页
    （活动 + 领主战）不再被误判成主城，而归位会落到 `bottom_nav_mc` 去点「主城」真正回家。
    """
    # ★#63：判据内核委托给上游共享源（与 abyss_impl / wuchong_impl 同一份）。
    return is_main_city_texts(_texts(items))


def _is_title(items: list[tuple[str, list[int]]]) -> bool:
    # 标题页判据：两端锚定的「点击开始」（common.json::PubTitleStartText，从不宽匹配）。
    return _has(items, r"^点击开始$")


def _is_account_confirm(items: list[tuple[str, list[int]]]) -> bool:
    return _has(items, r"^继续游戏$")


def _is_loading(items: list[tuple[str, list[int]]]) -> bool:
    return _has(items, [r"^请耐心等待$", r"耐心等待"]) or _has(items, r"健康游戏忠告")


# 识别不出文字的「子页面/关卡列表」——用它们自己的可见标题确认后，再按左下返回箭头。
# （绝不盲按：必须有这些锚点之一，才认为「当前页适用固定返回点」。）
_BACK_PAGE_MARKERS = (
    r"外传故事列表",
    r"^STORY$",
    r"^外传故事$",
    r"^小传故事$",
    r"关卡列表",
    r"选择关卡",
)


# ---------------------------------------------------------------------------
# TitleWatcher：标题页守护 + 抓屏 + OCR（assets_dir 既是模板来源，也是 OCR 资源）
# ---------------------------------------------------------------------------
class TitleWatcher:
    """标题页守护。

    · grab()   —— 抓当前屏幕（720 空间 BGR）。side_live 的 grab 用法依赖它。
    · detect() —— 当前是否在【标题页】（OCR「^点击开始$」）。命中即应停手。
    · ocr(img) —— 对给定图做全屏 OCR（离线，不占设备）。
    · enabled  —— 守护是否可用。本实现走 OCR，恒为 True（比模板更稳，无需标题模板）。
    """

    def __init__(self, assets_dir: str | Path) -> None:
        self.assets_dir = Path(assets_dir)
        # OCR 引擎预加载：把 Resource 加载一次（后续 detect/ocr 直接复用）。
        try:
            _ensure_ocr(self.assets_dir)
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            print(f"[harness] TitleWatcher OCR 初始化失败，守护关闭：{exc}")
            self.enabled = False

    def grab(self) -> np.ndarray:
        return grab()

    def ocr(self, image: np.ndarray) -> list[tuple[str, list[int]]]:
        return ocr(image, self.assets_dir)

    def detect(self) -> bool:
        try:
            return _is_title(self.ocr(self.grab()))
        except Exception as exc:  # noqa: BLE001
            print(f"[harness] TitleWatcher.detect 异常：{exc}")
            return False


# ---------------------------------------------------------------------------
# 归位 ensure_main_city
# ---------------------------------------------------------------------------
# ★归位状态机：页面 -> 动作 的【有序表】，顺序即匹配优先级——这是安全属性，不是实现细节★
#
# 真机实测的正确顺序（与 #20 phantom_restart 一致）：
#     账号确认页（「星点启程」弹窗）→「继续游戏」→ 标题页 →「点击开始」→ 主城
#
# 为什么顺序不能颠倒（#13 第 3 次运行、设备实证）：
#   账号确认页是一张**盖在标题页上的弹窗**——弹窗背后标题页的大字「点击开始」会一起被
#   OCR 读到（见 #13 证据 10_acctconfirm_155418.png：弹窗底部透出「点击开始」，且提示
#   文案里也含「点击开始」三个字）。若先判标题页（旧实现），就会点在弹窗挡住的假
#   「点击开始」上：点不动、也回不到主城，于是归位 10 步全败、最终人工恢复设备。
#   因此必须：**先账号确认页「继续游戏」，后标题页「点击开始」**。
#
# 每条 = (rule_id, 判据(items)->bool, 动作(items, step)->bool)：
#   动作返回 True 表示「已到主城，结束」；返回 False 表示「已出手 / 已等待，继续下一步」。
# 顺序由守卫 tools/contract_hooks/hooks_24.py 锁死（account_confirm 必须早于 title）。
def _is_bottom_nav_mc(items: list[tuple[str, list[int]]]) -> bool:
    """底部导航「主城」可见（有底部导航的页面，如角色 / 商店页）。"""
    return _pick(items, r"^主城$", roi=BOTTOM_NAV_ROI) is not None


def _is_back_page(items: list[tuple[str, list[int]]]) -> bool:
    """带左下返回箭头的已知子页面（外传故事列表 / 外传关卡页等）。"""
    return _has(items, list(_BACK_PAGE_MARKERS))


def _act_main_city(items: list[tuple[str, list[int]]], step: int) -> bool:
    texts = _texts(items)
    hits = [a for a in MAIN_CITY_UNIQUE_ANCHORS if any(a in t for t in texts)]
    print(f"[归位] step{step}: 已在主城（独有锚点 {hits}）")
    return True


def _act_account_confirm(items: list[tuple[str, list[int]]], step: int) -> bool:
    box = _pick(items, r"^继续游戏$")
    cx, cy = _center(box)
    print(f"[归位] step{step}: 账号确认页 -> 点『继续游戏』@{cx,cy}")
    adb_tap(cx, cy)
    time.sleep(6.0)
    return False


def _act_title(items: list[tuple[str, list[int]]], step: int) -> bool:
    box = _pick(items, r"^点击开始$")
    cx, cy = _center(box)
    print(f"[归位] step{step}: 标题页 -> 点『点击开始』@{cx,cy}")
    adb_tap(cx, cy)
    time.sleep(6.0)
    return False


def _act_bottom_nav_mc(items: list[tuple[str, list[int]]], step: int) -> bool:
    box = _pick(items, r"^主城$", roi=BOTTOM_NAV_ROI)
    cx, cy = _center(box)
    print(f"[归位] step{step}: 底部导航『主城』@{cx,cy}")
    adb_tap(cx, cy)
    time.sleep(3.0)
    return False


def _act_back_page(items: list[tuple[str, list[int]]], step: int) -> bool:
    print(f"[归位] step{step}: 子页面 -> 点左下返回 {BACK_BUTTON}")
    adb_tap(*BACK_BUTTON)
    time.sleep(3.0)
    return False


# ---------------------------------------------------------------------------
# #31 gap1：共斗房（多人房间页）——归位必须认识它，才能从「前一阶段留下的房间」回主城
# ---------------------------------------------------------------------------
# 缺陷（真机战役 Stage F 实证；tools/run_side_live.py 接力）：
#   前一阶段把游戏留在【幻想共斗房】，`ensure_main_city` 认不出该页 ->
#   `[归位] step0: 未知页面，停手` -> 没回主城 -> 第二个任务起不来。
#
# 房间页【独有】文案（照抄真机帧 preF.png / disband.png / home_00.png；
# 该页没有底部导航，只有左下『返回』= BACK_BUTTON）：
#   房间号码 / 准备中： / 未进行招募 / 队长。≥2 命中才认，避免与普通页混淆。
COOP_ROOM_ANCHORS = (r"^房间号码$", r"^准备中：$", r"^未进行招募$", r"^队长$")
COOP_ROOM_MIN_HITS = 2
# 离开房间会弹出「解散房间 可以吗？」确认框（真机帧 dlg2.png / home_05.png）——
# 它仍带『房间号码』，属共斗房的一种子状态，必须一起处理（否则点「返回」后卡在确认框）。
COOP_DISBAND_MARKERS = (r"解散房间", r"^可以吗？$")
# 确认框里的【确认】按钮文案（读后动；绝不点『取消』，也绝不盲点标题）。
COOP_CONFIRM_TAPS = (r"^解散$", r"^确定$", r"^是$")


def _is_coop_room(items: list[tuple[str, list[int]]]) -> bool:
    """共斗房（多人房间页）或其「解散房间」确认框（#31 gap1）。"""
    if _has(items, list(COOP_DISBAND_MARKERS)):
        return True
    hits = [p for p in COOP_ROOM_ANCHORS if _has(items, p)]
    return len(hits) >= COOP_ROOM_MIN_HITS


def _act_coop_room(items: list[tuple[str, list[int]]], step: int) -> bool:
    """从共斗房回退：确认框 -> 点『解散』（读它自己的框）；房间页 -> 点左下『返回』。

    绝不点『取消』、绝不点标题、绝不盲点：每一步都先 OCR 读到目标框再点它的中心。
    """
    dialog = _has(items, list(COOP_DISBAND_MARKERS))
    if dialog:
        box = _pick(items, list(COOP_CONFIRM_TAPS))
        if box is not None:
            cx, cy = _center(box)
            print(f"[归位] step{step}: 共斗房·解散确认 -> 点『解散』@{cx,cy}")
            adb_tap(cx, cy)
            time.sleep(2.5)
            return False
        # 确认框里没读到确认按钮：只等待，绝不盲点（尤其不能点『取消』）。
        print(f"[归位] step{step}: 共斗房·解散确认框未读到确认按钮，等待…")
        time.sleep(2.0)
        return False

    box = _pick(items, r"^返回$", roi=[0, 1180, 200, 100])
    if box is None:
        box = _pick(items, r"^返回$")
    if box is not None:
        cx, cy = _center(box)
        print(f"[归位] step{step}: 共斗房 -> 点左下『返回』@{cx,cy}")
        adb_tap(cx, cy)
        time.sleep(2.5)
        return False

    # 房间页却没有可点的『返回』：保守等待（绝不盲点）。
    print(f"[归位] step{step}: 共斗房 -> 未读到『返回』，等待…")
    time.sleep(2.0)
    return False


# ---------------------------------------------------------------------------
# #48：幻想共斗「战斗结束」QUEST RESULT 页（【解散】/【返回房间】）——归位必须认识它
# ---------------------------------------------------------------------------
# 缺陷（真机战役 #48 实证；s_stuck.png）：一场 幻想连战 共斗打完后，收工把设备留在共斗
# 的 **QUEST RESULT** 页 —— 该页只有底部两个按钮【解散】/【返回房间】，**没有** 继续 / OK，
# 也没有带底部导航（bottom_nav_mc / back_page 都够不着它）。
#
# 而页顶那条大字横幅 **QUEST RESULT** 会被 `settlement` 规则的 `QUESTRE` 子串命中 →
# `settlement` 去点【继续】/【OK】找不到，就退回 `_pick(r"QUESTRE")` **点顶部横幅**；
# 横幅是纯装饰、点了画面不变 → 状态机原地空转 `max_steps`（10 步）仍回不了主城。真机
# 只能人工恢复（recover_coop.py），下一个任务起不来 —— 这正是 #48 要堵的洞。
#
# 该页【独有】判据（照抄真机帧 s_stuck.png 的 OCR）：底部【返回房间】@[444,1184,118,33]。
#   用【返回房间】作**唯一必需**锚点：它只出现在共斗「战斗结束」页（`coop_room` 的「解散房间
#   可以吗？」确认框、主城、排名结算页都没有它）—— 既够独特、又**不依赖【解散】两个字**，
#   这样即便 OCR 把【解散】读丢、只剩【返回房间】，归位仍认得这一页（避免退回 settlement 的
#   横幅死路）。★注意：不能反过来只认【解散】★ —— 那会把共斗房确认框误判成本页。
#
# ★读后动，绝不盲点★：只点【自己识别到的】按钮框中心。优先点【解散】@[183,1182,63,36]
#   （离开共斗房间 —— 与真机人工恢复 recover_coop.py 一致）；读不到【解散】才退回点
#   【返回房间】（回共斗房，再由 `coop_room` 规则接管回退）。两个都读不到时只等待。
#   **绝不点顶部 QUEST RESULT 横幅**（那是 `settlement` 在本页失败的根因），也绝不用写死坐标兜底。
#
# ★顺序（安全属性）★：本规则必须排在 `settlement`【之前】。否则 `settlement` 会因本页
#   顶部横幅含 `QUESTRE` 而抢先命中并点横幅（#48 实证的失败路径）。
COOP_RESULT_DISBAND = r"^解散$"
COOP_RESULT_RETURN_ROOM = r"^返回房间$"
#: 页面【唯一必需】锚点（共斗「战斗结束」页独有）。
COOP_RESULT_ANCHOR = COOP_RESULT_RETURN_ROOM


def _is_coop_result(items: list[tuple[str, list[int]]]) -> bool:
    """共斗「战斗结束」QUEST RESULT 页（#48）：底部【返回房间】可见（本页独有锚点）。"""
    return _has(items, COOP_RESULT_ANCHOR)


def _act_coop_result(items: list[tuple[str, list[int]]], step: int) -> bool:
    """从共斗结算页离开：读【解散】框中心点击（读不到才退回【返回房间】），绝不盲点。

    返回 False（已出手 / 已等待），由状态机继续判页（最终落到主城或带底部导航的页面）。
    """
    box = _pick(items, COOP_RESULT_DISBAND)
    label = "解散"
    if box is None:
        box = _pick(items, COOP_RESULT_RETURN_ROOM)
        label = "返回房间"
    if box is None:
        # 判据命中了却没有可点按钮：只等待，绝不点顶部横幅、绝不盲点。
        print(f"[归位] step{step}: 共斗结算页 -> 未读到【解散】/【返回房间】，等待…")
        time.sleep(2.0)
        return False

    cx, cy = _center(box)
    print(f"[归位] step{step}: 共斗结算页 -> 点『{label}』@{cx,cy}（读后动，绝不点顶部横幅）")
    adb_tap(cx, cy)
    time.sleep(3.0)
    return False


# ---------------------------------------------------------------------------
# #38：战斗失败 / GAMEOVER（「是否续关？」）——归位必须认识它，才能从失败画面回主城
# ---------------------------------------------------------------------------
# 缺陷（#38 真机扫描，与 #31 gap1 同一类）：`魁雷精灵兽` 战斗打输 → 进入
# GAMEOVER /「是否续关？」→ `[归位] step0: 未知页面，停手` → 没回主城 → 后面 3 个成员
# （威风 / 巫光 / 暗唤精灵兽）一个都没跑成（设备被留在 GAMEOVER 页）。
#
# 该页**没有底部导航、也没有左下『返回』**（只有【放弃】左下 + 【续关】右下，后者要花
# 星导石×50）；所以 bottom_nav_mc / back_page 都够不着它。归位的正确处置 = **拒绝续关**：
#   1. GAMEOVER 页 → 读【放弃】框中心点击（绝不点【续关】：有限资源）；
#   2. 放弃确认框「放弃时 无法获得…」→ 读【OK】框中心点击（绝不点【取消】：会退回 GAMEOVER）；
#   3. 之后落到详情页（有「返回 + 主城底导」）→ 由 bottom_nav_mc 点『主城』回家。
# 真机帧：gameover_prompt.png（GAMEOVER 页）/ gameover_confirm.png（放弃确认框）。
# 与 #31 的共斗房同一套「特殊页面 -> 自己的子状态 -> 再接回主城」处理（读后动，绝不盲点）。
GAMEOVER_TITLE = "GAMEOVER"
GAMEOVER_PROMPT = r"是否续关"
GAMEOVER_GIVEUP = r"^放弃$"
GAMEOVER_CONFIRM_MARKERS = (r"放弃时", r"无法获得该关卡内已获得的")
GAMEOVER_CONFIRM_OK = r"^OK$"


def _is_gameover(items: list[tuple[str, list[int]]]) -> bool:
    """GAMEOVER 战斗失败页（#38）或其「放弃」确认框。"""
    if _has(items, list(GAMEOVER_CONFIRM_MARKERS)):
        return True
    return _has(items, GAMEOVER_TITLE) and _has(items, GAMEOVER_PROMPT)


def _act_gameover(items: list[tuple[str, list[int]]], step: int) -> bool:
    """从 GAMEOVER 回退：拒绝续关 —— 确认框点『OK』；GAMEOVER 页点『放弃』。

    绝不点『续关』（花星导石×50）、绝不点『取消』（退回 GAMEOVER）；读不到目标按钮时只等待，
    绝不盲点。返回 False（已出手 / 已等待），由状态机继续判页（最终经详情页的『主城』回家）。
    """
    if _has(items, list(GAMEOVER_CONFIRM_MARKERS)):
        box = _pick(items, GAMEOVER_CONFIRM_OK)
        if box is not None:
            cx, cy = _center(box)
            print(f"[归位] step{step}: GAMEOVER·放弃确认 -> 点『OK』@{cx,cy}（绝不点『取消』）")
            adb_tap(cx, cy)
            time.sleep(2.5)
            return False
        print(f"[归位] step{step}: GAMEOVER·放弃确认框未读到『OK』，等待…")
        time.sleep(2.0)
        return False

    box = _pick(items, GAMEOVER_GIVEUP)
    if box is not None:
        cx, cy = _center(box)
        print(f"[归位] step{step}: GAMEOVER -> 点『放弃』@{cx,cy}（拒绝续关，绝不点『续关』）")
        adb_tap(cx, cy)
        time.sleep(2.5)
        return False

    print(f"[归位] step{step}: GAMEOVER 页未读到『放弃』，等待…")
    time.sleep(2.0)
    return False


# ---------------------------------------------------------------------------
# #33：归位必须认识【实时战斗页】——「长战斗属正常等待」（运维裁决 verbatim）
# ---------------------------------------------------------------------------
# 缺陷（真机 127.0.0.1:16384，猩红巨熊讨伐/中级）：
#   `[归位] step0: 未知页面，停手。可见文本=['11','自动','时间 09:55','分数 00000527167','FEVER','猩红巨熊',…]`
#   → 设备被留在战斗中，运维只能人工 放弃/OK 恢复（下一个任务起不来）。
# 处置：认【战斗中 HUD】（「时间 mm:ss」+「分数 N」，与 pipeline 的
#   common.json::PubBattleTime/PubBattleScore 同一判据）→ 按运维裁决「长战斗属正常等待，
#   必须等」**等待它自己打完**（有界），绝不静默停手：
#     · 战斗 HUD 一消失（本局结束）→ 返回 False，由状态机继续判页（结算页 / bottom_nav_mc / 主城）；
#     · 超过 LIVE_BATTLE_WAIT_SEC（游戏自身上限 + 裕度）仍未结束 → **带原因**停手（绝不静默、
#       绝不盲点、绝不按返回键）。
#   ★读后动★：本规则**不点击**——战斗页没有已登记的「离场」可读按钮，盲点风险高（且可能点掉
#   技能 / 花资源）；与运维裁决一致，先等。战斗页无底部导航，对 bottom_nav_mc / back_page 无影响。
#   ★顺序（安全属性）★：本规则排在 gameover【之后】——GAMEOVER /「是否续关？」页底部**也画着**
#   战斗 HUD（#46 实证），必须让 gameover 先接走；另排在 bottom_nav_mc / back_page 之后。
BATTLE_HUD_TIME_RE = r"时间 \d+:\d+"
BATTLE_HUD_SCORE_RE = r"分数 \d"
#: 归位等待实时战斗页的上限（秒）：游戏自身上限 + 结算/加载裕度。★有界★。
LIVE_BATTLE_WAIT_SEC = BATTLE_GAME_CAP_SEC + 120.0
#: live_battle 规则的「超长战斗 → 带原因停手」一次性信号（act 置位，ensure_main_city 消费后停手）。
_LIVE_BATTLE_STOP: dict = {"stop": False, "reason": ""}


def _is_live_battle(items: list[tuple[str, list[int]]]) -> bool:
    """实时战斗页（#33）：底部战斗 HUD「时间 mm:ss」+「分数 N」（与 pipeline 同判据）。

    ★排除 GAMEOVER /「是否续关？」页★：该页底部**也画着**战斗 HUD（#46 实证），语义上由更早的
    ``gameover`` 规则接走 —— 本条只认【真的在打】的战斗页，绝不在失败页上「等它打完」。
    """
    if _is_gameover(items):
        return False
    return _has(items, BATTLE_HUD_TIME_RE) and _has(items, BATTLE_HUD_SCORE_RE)


def _grab_items() -> list[tuple[str, list[int]]] | None:
    """抓当前一帧并 OCR 成 items（归位内部用）；抓帧/OCR 失败返回 ``None``（保守：不据此判离场）。"""
    try:
        img = grab()
        if _OCR_ASSETS is None:
            return None
        return ocr(img, _OCR_ASSETS)
    except Exception as exc:  # noqa: BLE001 -- 抓帧失败不致命：视为「还不能判离场」，继续等
        print(f"[归位] 战斗页抓帧/OCR 失败（继续等待）：{exc}")
        return None


def _act_live_battle(items: list[tuple[str, list[int]]], step: int) -> bool:
    """实时战斗页 -> **等它自己打完**（长战斗属正常等待，运维裁决）；★有界、绝不静默停手★。

    读后动：不点击。每 3s 抓一帧重判；战斗 HUD 一消失即返回 False（由状态机继续判页）。
    超过 :data:`LIVE_BATTLE_WAIT_SEC` 仍未结束 → 置 :data:`_LIVE_BATTLE_STOP` 并带原因停手。
    """
    deadline = time.monotonic() + LIVE_BATTLE_WAIT_SEC
    while True:
        time.sleep(3.0)
        fresh = _grab_items()
        if fresh is not None and not _is_live_battle(fresh):
            print(f"[归位] step{step}: 实时战斗页 -> 已离开战斗 HUD，继续归位")
            return False
        if time.monotonic() >= deadline:
            reason = (
                f"实时战斗页持续超过 {LIVE_BATTLE_WAIT_SEC:.0f}s（游戏自身上限 "
                f"~{BATTLE_GAME_CAP_SEC:.0f}s + 裕度）仍未结束 → 带原因停手"
                f"（绝不静默、绝不盲点、绝不按返回键）"
            )
            _LIVE_BATTLE_STOP["stop"] = True
            _LIVE_BATTLE_STOP["reason"] = reason
            print(f"[归位] step{step}: ★{reason}★")
            return False


def _act_loading(items: list[tuple[str, list[int]]], step: int) -> bool:
    print(f"[归位] step{step}: 加载中，等待…")
    time.sleep(3.0)
    return False


# ---------------------------------------------------------------------------
# #28：结算 / 奖励 / 升级结算页（归位必须能穿过它们回主城）
# ---------------------------------------------------------------------------
# 缺陷（#26 真机实证）：单目标打满后收工【就停在结算帧】——#22 的收工闸在结算页把任务
# StopTask 掉，游戏停在 QUESTRESULT / 结算页（证据：v26/shot_015_164900.png，OCR 读到
# 「继续」@[328,1181,63,36] + 「QUESTRESULT」+「等级最大！」）。而本状态机【不认识】
# 这一页（它的「继续」不是任何一条规则的判据）→ `[归位] step0: 未知页面，停手` → 设备
# 留在结算页。归位的定义是「从任意【已知】页面回主城」，**结算 / 奖励页就是一处已知页面**，
# 只是此前没有对应规则。本条补齐它：点【继续】/【OK】/顶部横幅把它推进过奖励页，直到
# 落到有底部导航的页面（由 bottom_nav_mc 点「主城」回家）或直接回到主城。
#
# ★绝不盲点★：只点【自己识别到的框中心】；读不到「继续 / OK」时退回照抄 pipeline 的
#   升级结算页固定继续点 [358,1198]（common.json::PubLevelUpContinue 已验证的做法）。
#
# ★顺序（安全属性）★：本规则排在 bottom_nav_mc / back_page【之后】。理由：角色 / 成长
#   等主城子页也会读到大字「经验值」，但它们【有底部导航】→ 先被 bottom_nav_mc 接走，
#   永远不会落到本条；只有【没有底部导航】的结算 / 奖励页才会命中本条。结算页实测无
#   底部导航（bottom nav「主城」= None），故本规则既够得着它、又不会误伤子页。
def _is_settlement(items: list[tuple[str, list[int]]]) -> bool:
    """结算 / 奖励 / 升级结算页（契约 `_settlement`；见 SETTLEMENT_TEXTS）。"""
    return _has(items, list(SETTLEMENT_TEXTS))


def _act_settlement(items: list[tuple[str, list[int]]], step: int) -> bool:
    """结算 / 奖励页 -> 点【继续】/【OK】(优先按钮识别框中心) 或顶部横幅 / 升级继续固定点。

    推进过奖励页后画面往下走（最终落到带底部导航的页面或主城），返回 False 表示
    「已出手，继续判页」。
    """
    box = _pick(items, [r"^继续$", r"^OK$"])
    if box is None:
        box = _pick(items, r"QUESTRE")  # 横幅快进（顶部，远离底部按钮）
    if box is not None:
        cx, cy = _center(box)
    else:
        cx, cy = LEVEL_UP_CONTINUE  # 升级结算页常常读不到「继续」二字
    print(f"[归位] step{step}: 结算/奖励页 -> 推进（点 ({cx},{cy})）")
    adb_tap(cx, cy)
    time.sleep(2.0)
    return False


# ---------------------------------------------------------------------------
# #56 二批（运维裁决⑤）：编队页 —— 归位必须**先点『返回』**，主城底导才会出现
# ---------------------------------------------------------------------------
# 运维原话：「这里应该要**先点击返回**，然后才有主城按键」。
# 编队页（领主战成员 / 深渊EX / 五重 / 迷宫……）**没有底部导航**（连「主城」入口都不在），
# 所以 bottom_nav_mc 够不着它；而它也不是 `_BACK_PAGE_MARKERS` 里的「外传/关卡列表」。
# 正确处置 = 读后动：点**识别到的『返回』框中心**（绝不盲点左下固定点），退出后底部导航
# 「主城」才出现 → 再由 bottom_nav_mc 点『主城』回家。
# 编队页【独有】判据 = 「挑战」（前缀，兼容 OCR 把箭头并进来的『挑战→』）+ 下列任一：
#   SET N / Party X / 自动续战 / 自动 / SET编辑（共斗房间页同样满足，但它在表里更靠前、
#   由 coop_room 先接走 —— 两条都点『返回』，不冲突）。
TEAM_CHALLENGE = r"^挑战"
TEAM_MARKERS = (r"^SET ?\d+$", r"Party\s*[A-Za-z]", r"^自动续战$", r"^自动$", r"^SET编辑$")


def _is_team_page(items: list[tuple[str, list[int]]]) -> bool:
    """编队页（单人 / 共斗房间页共用队伍页）：有『挑战』且带任一编队页标记。"""
    if not _has(items, TEAM_CHALLENGE):
        return False
    return any(_has(items, p) for p in TEAM_MARKERS)


def _act_team_page(items: list[tuple[str, list[int]]], step: int) -> bool:
    """编队页 -> 读【自己识别到的『返回』框】点其中心（绝不按返回键、绝不盲点固定点）。"""
    box = _pick(items, r"^返回$", roi=[0, 1180, 200, 100])
    if box is None:
        box = _pick(items, r"^返回$")
    if box is None:
        print(f"[归位] step{step}: 编队页 -> 未读到『返回』，等待…")
        time.sleep(2.0)
        return False
    cx, cy = _center(box)
    print(f"[归位] step{step}: 编队页 -> 点『返回』@{cx},{cy}（读后动；退出后主城底导才出现）")
    adb_tap(cx, cy)
    time.sleep(3.0)
    return False


# ---------------------------------------------------------------------------
# ★#60/#64 迷宫【道具确认框】（是否使用阿尔戈罗盘 / 阿戈尔罗盘）——归位必须认识它★
# ---------------------------------------------------------------------------
# 缺陷（#64 真机实证，证据即 #60 的弹框帧 mazeA_beng_ji_99_end）：
#   迷宫行【战斗】点下去会弹一张**模态确认框**：
#       「是否使用阿尔戈罗盘」/「挑战临境域 深渊之兽·极？」   否@[178,806]  是@[504,805]
#   它把底部「主城」标签压暗/遮挡 → `bottom_nav_mc` 认不出「主城」→
#   `[归位] step0: 未知页面，停手` → 任务收尾与「接力」（下一个任务从主城起跑）都卡住。
#
# 处置（#60 运维裁决 verbatim：「阿尔戈罗盘的可以点确认，无所谓道具消耗」）：
#   读弹框 → 点它【是】按钮**自己的** OCR 框中心（读后动，绝不盲点、绝不用死坐标）。
#   ★OCR 变体★：设备把该道具读成 `阿尔戈罗盘` 与 `阿戈尔罗盘` 两种 —— 判据用
#   `是否使用阿[尔戈]{1,2}罗盘`（中间两字的顺序/多寡都容忍），仍是本弹框独有的词。
#
# 与 pipeline 侧是【同一事实的两处落地】：farm.json::FarmItemConfirm（流程内开打前）
#   与这里的 `maze_item_confirm`（收尾/接力时的归位）。两处判据逐字一致 ——
#   hooks_60/hooks_64 把二者与真机帧钉死（改一处、另一处不一致即红）。
MAZE_ITEM_PROMPT = r"是否使用阿[尔戈]{1,2}罗盘"
MAZE_ITEM_YES = r"^是$"


def _is_maze_item_confirm(items: list[tuple[str, list[int]]]) -> bool:
    """迷宫道具确认框（#60/#64）：弹框标题可见。★读后动★——不点标题，点它自己的【是】。"""
    return _has(items, MAZE_ITEM_PROMPT)


def _act_maze_item_confirm(items: list[tuple[str, list[int]]], step: int) -> bool:
    """读弹框 -> 点它【是】按钮识别框中心（#60 授权：可消耗道具）。

    读不到【是】只等待，**绝不盲点**（尤其不点【否】、不点标题）。返回 False（已出手/已等待），
    由状态机继续判页（点【是】后弹框消失，画面回到迷宫页 → 由 bottom_nav_mc / back_page 等接走）。
    """
    box = _pick(items, MAZE_ITEM_YES)
    if box is None:
        print(f"[归位] step{step}: 迷宫道具确认框 -> 未读到【是】，等待…（绝不盲点）")
        time.sleep(2.0)
        return False
    cx, cy = _center(box)
    print(f"[归位] step{step}: 迷宫道具确认框 -> 点『是』@{cx,cy}（#60 授权：可消耗道具）")
    adb_tap(cx, cy)
    time.sleep(3.0)
    return False


# ---------------------------------------------------------------------------
# ★#64 未知模态框的【可见、带原因】降级（绝不静默停手）★
# ---------------------------------------------------------------------------
# 归位的「已知页面」由 RETURN_HOME_RULES 逐页认识；但**没登记过的模态框**仍可能盖在任意
# 页上。此时归位不能只说一句 `未知页面，停手` 就走 —— 那让人无从判断是「模态框」还是
# 「真的漂到不认识的分区」。本段给出一条**看得见、带原因**的降级：
#   · 画面有**模态框信号**（成对的【是/否】·【确定/取消】·【OK/取消】，或以问号结尾的提示行）
#     → 明确打印「疑似【未知模态框】…带原因停手」；
#   · 否则 → 沿用原来的「未知页面，停手」。
# 两种都是**停手**（绝不盲点、绝不按返回键），区别只在**原因可读**。
MODAL_BUTTON_PAIRS: tuple[tuple[str, str], ...] = (
    (r"^是$", r"^否$"),
    (r"^确定$", r"^取消$"),
    (r"^OK$", r"^取消$"),
)
MODAL_PROMPT_RE = r"[?？]$"


def _looks_like_modal(items: list[tuple[str, list[int]]]) -> bool:
    """画面是否**疑似模态框**（未知模态框的带原因降级用；★纯判据，不做任何动作★）。"""
    for yes, no in MODAL_BUTTON_PAIRS:
        if _has(items, yes) and _has(items, no):
            return True
    return _has(items, MODAL_PROMPT_RE)


#: 归位状态机【唯一来源】。顺序 = 匹配优先级（★account_confirm 必须早于 title★，见上）。
#: #28 起新增 settlement（结算 / 奖励页推进）——排在 bottom_nav_mc / back_page 之后（见上
#: 「顺序（安全属性）」）：只接住【没有底部导航】的结算 / 奖励页，绝不误伤主城子页。
#: #31 起新增 coop_room（共斗房 / 解散确认框回退）——同样排在有底部导航的页面之后。
#: #38 起新增 gameover（战斗失败 /「是否续关？」拒绝续关 + 放弃确认框）——同一张表。
#: #48 起新增 coop_result（共斗战斗结束 QUEST RESULT 页 /【解散】·【返回房间】）——★必须排在
#: settlement 之前★：该页顶部横幅含 `QUESTRE`，否则 settlement 会抢先命中并点横幅空转（#48）。
#: #56 二批起新增 team_page（编队页 / 共斗房间页）——排在 coop_room 之后（房间页由 coop_room
#: 先接走，两条都点『返回』）；★归位在编队页必须先点『返回』，主城底导才会出现★（运维裁决⑤）。
#: #60/#64 起新增 maze_item_confirm（迷宫道具确认框 / 读后点【是】框中心）——排在有底导的
#: 页面之后（弹框压暗底导时 bottom_nav_mc 认不出，正是它要接住的那一帧）。
RETURN_HOME_RULES = (
    ("main_city", _is_main_city, _act_main_city),
    ("account_confirm", _is_account_confirm, _act_account_confirm),
    ("title", _is_title, _act_title),
    ("bottom_nav_mc", _is_bottom_nav_mc, _act_bottom_nav_mc),
    ("back_page", _is_back_page, _act_back_page),
    ("maze_item_confirm", _is_maze_item_confirm, _act_maze_item_confirm),
    ("coop_room", _is_coop_room, _act_coop_room),
    ("coop_result", _is_coop_result, _act_coop_result),
    ("gameover", _is_gameover, _act_gameover),
    # #33 起新增 live_battle（实时战斗页 / 等它打完）——★必须排在 gameover 之后★：GAMEOVER
    # 页底部也画着战斗 HUD（#46 实证），须先由 gameover 接走；战斗页无底导，不影响前面的规则。
    ("live_battle", _is_live_battle, _act_live_battle),
    ("team_page", _is_team_page, _act_team_page),
    ("settlement", _is_settlement, _act_settlement),
    ("loading", _is_loading, _act_loading),
)


def _game_running() -> bool:
    """游戏进程是否在跑（``pidof``，走与 adb_tap 同一条 adb 直连）。

    查询失败时保守返回 True（不误启动）。注意：不用 ``ctrl.post_shell().get()``——该
    JobWithResult 在本机 binding 上会抛 ``OverflowError: int too long to convert``（#24
    真机实测），而 ``_adb`` 与 adb_tap 同源、地址已由 runner 同步，稳且一致。
    """
    try:
        out = _adb("shell", "pidof", PKG).stdout.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 -- 判活失败按「在跑」处理，绝不擅自拉起
        print(f"[归位] pidof 查询失败（按在跑处理）：{exc}")
        return True
    return bool(out.strip())


def _start_app() -> None:
    """把游戏从 Android 桌面 / 崩溃状态冷启动起来（确定性动作，非盲点）。"""
    ctrl = _ctrl_ref.get("ctrl")
    if ctrl is None:
        raise RuntimeError("harness 尚未拿到 controller，无法启动游戏")
    print(f"[归位] 游戏未运行 -> 冷启动 {PKG}")
    ctrl.post_start_app(PKG).wait()


def ensure_main_city(
    watcher: "TitleWatcher", max_steps: int = 10, start_if_closed: bool = True
) -> bool:
    """归位：从任意【已知】页面（含「游戏未启动」的 Android 桌面、#28 的结算 / 奖励页）
    把游戏带回主城。

    每一步都【先截屏 + OCR 判页】，再按 ``RETURN_HOME_RULES`` 的【有序表】取首个命中的
    页面出手（顺序 = 优先级，账号确认页先于标题页）。只对确认过的判据出手；认不出的画面
    停手返回 False，绝不满屏乱点、绝不按返回键。游戏根本没在跑（桌面 / 崩溃）时，先做一次
    确定性冷启动（``start_if_closed``）再继续判页。

    #28：结算 / 奖励 / 升级结算页也是【已知】页面——收工若停在结算帧（#22 的收工闸就在
    结算帧 StopTask），归位会点掉它的【继续】/【OK】/顶部横幅，推进过奖励页再回主城；
    此前没有这条规则，等价于「未知页面，停手」→ 设备留在结算页（#26 实证）。
    """
    launched = False
    # #33：每次归位开始，清掉上一次「超长战斗 → 带原因停手」的一次性信号。
    _LIVE_BATTLE_STOP["stop"] = False
    _LIVE_BATTLE_STOP["reason"] = ""
    for step in range(max_steps):
        img = watcher.grab()
        items = watcher.ocr(img)

        handled = False
        for _rid, probe, act in RETURN_HOME_RULES:
            if probe(items):
                if act(items, step):
                    return True
                # #33：实时战斗页等待超过有界上限 -> 带原因停手（原因已由 act 打印/置位）。
                if _LIVE_BATTLE_STOP["stop"]:
                    print(f"[归位] 停手原因：{_LIVE_BATTLE_STOP['reason']}")
                    return False
                handled = True
                break
        if handled:
            continue

        # 认不出画面：若游戏没在跑（Android 桌面 / 崩溃），先确定性冷启动再继续；否则停手。
        if start_if_closed and not _game_running():
            if not launched:
                _start_app()
                launched = True
            else:
                print(f"[归位] step{step}: 冷启动后仍认不出（等待中…）")
            time.sleep(8.0)
            continue

        # ★#64★ 未知【模态框】：**看得见、带原因**地降级（绝不静默停手）——
        #   认出模态框信号（是/否 等成对按钮 / 以问号结尾的提示）就明确点名它是「未知模态框」，
        #   让人一眼知道卡在弹框而不是漂到陌生分区。仍然**不盲点、不按返回键**。
        if _looks_like_modal(items):
            print(
                f"[归位] step{step}: 疑似【未知模态框】—— 无已知规则可处理，带原因停手（不盲点、"
                f"不按返回键）。可见文本={_texts(items)[:12]}"
            )
            return False
        print(f"[归位] step{step}: 未知页面，停手。可见文本={_texts(items)[:12]}")
        return False

    print("[归位] 超过最大步数，仍未回到主城")
    return False


# ---------------------------------------------------------------------------
# 导航：主城 -> 外传故事列表（识别驱动，照抄 side_story.json SideNavStage/StoryTab）
# ---------------------------------------------------------------------------
def goto_side_story_list(watcher: "TitleWatcher", max_steps: int = 8) -> bool:
    """从主城导航到「外传故事列表」：主城点【关卡】→ 关卡页点【外传故事】。

    两步都「看到才点」（点各自 OCR 框中心）；已在目标页则直接返回 True。
    """
    for step in range(max_steps):
        img = watcher.grab()
        items = watcher.ocr(img)

        if _has(items, r"^外传故事列表$"):
            print(f"[导航] step{step}: 已在外传故事列表")
            return True

        box = _pick(items, r"^关卡$", roi=[280, 1050, 180, 130])
        if box is not None:
            cx, cy = _center(box)
            print(f"[导航] step{step}: 主城 -> 点『关卡』@{cx,cy}")
            adb_tap(cx, cy)
            time.sleep(2.5)
            continue

        box = _pick(items, [r"^小传故事$", r"^外传故事$"], roi=[430, 790, 320, 160])
        if box is not None:
            cx, cy = _center(box)
            print(f"[导航] step{step}: 关卡页 -> 点『外传故事』@{cx,cy}")
            adb_tap(cx, cy)
            time.sleep(2.5)
            continue

        print(f"[导航] step{step}: 未命中导航判据（可见={_texts(items)[:10]}）")
        return False
    return False


# ---------------------------------------------------------------------------
# 任务追踪 run_task_traced
# ---------------------------------------------------------------------------
def _job_status(job) -> str:
    """把 MAA 的 Status 对象转成可读字符串（Status 无公开的 name）。"""
    st = job.status
    for name in ("succeeded", "failed", "running", "pending"):
        if getattr(st, name, False):
            return name
    return "done" if getattr(st, "done", False) else "unknown"


def _tasker_active(tasker) -> bool:
    """tasker 是否还在运行 / 停止中（读它自己的 running / stopping 标志）。"""
    for name in ("running", "stopping"):
        try:
            if getattr(tasker, name, False):
                return True
        except Exception:  # noqa: BLE001 -- 查询失败按「不在跑」处理，避免空转
            pass
    return False


def _terminate_task(tasker, job, deadline: float = 15.0) -> bool:
    """请求停止任务，并在【有界】时间内确认它真的停下；绝不阻塞在 post_stop().wait()。

    ★为什么不能 `.wait()`（#31 gap3，真机 Stage D 实证）★
    `tasker.post_stop()` 返回的 Job 在任务卡死时**永不返回**：旧实现 `post_stop().wait()`
    因此把 runner 卡死在 finally 里 —— `--timeout 900` 到点后任务还在跑、控制权也没归还，
    只能人工 kill。停止是「请求 + 有界轮询」：把请求发出（不 wait），再按 tasker 自己的
    running/stopping 标志轮询到 deadline；**到期即归还控制**（迟到好过永远不到）。
    """
    end = time.time() + max(0.0, deadline)
    while True:
        if job.done or not _tasker_active(tasker):
            return True
        try:
            tasker.post_stop()  # 只发请求；绝不 .wait()（可能永不返回，#31）
        except Exception as exc:  # noqa: BLE001
            print(f"[追踪] post_stop 异常：{exc}")
        if time.time() >= end:
            print(
                f"[追踪] 停止请求后 {deadline:.1f}s 仍未确认停止，放弃等待（归还控制）"
            )
            return False
        time.sleep(0.5)


def wait_job_bounded(tasker, job, timeout: float = 120.0, label: str = "") -> str:
    """有界等待一个 post_task job 完成；超时则请求停止并归还控制（绝不无限 wait）。

    供不追踪节点的 runner（如 run_side_live 的单节点验证）使用。返回
    ``_job_status`` 文案，或 ``"timeout"``。
    """
    start = time.time()
    while True:
        if job.done:
            return _job_status(job)
        if timeout and (time.time() - start) > timeout:
            print(f"[追踪] {label or 'job'} 超时 {timeout:.0f}s -> 请求停止")
            _terminate_task(tasker, job, deadline=min(15.0, max(5.0, timeout)))
            return "timeout"
        time.sleep(0.5)


def run_task_traced(
    tasker: Tasker,
    entry: str,
    override: dict,
    timeout: float,
    label: str,
    watcher: "TitleWatcher | None" = None,
    stall_timeout: float = 0.0,
    stop_timeout: float = 15.0,
) -> tuple[str, list[str]]:
    """投递任务 `entry`（应用 `override`）并追踪到结束。

    返回 (status, executed)：
      · status   —— "succeeded" / "failed" / "timeout" / "stalled" / "title"（标题页出现即停手）
      · executed —— 依次命中的节点名列表。

    每秒轮询：① 抓任务节点轨迹；② 若 watcher 报标题页则停手；③ timeout / stall 兜底。
    绝不按返回键、绝不盲点（追踪期间不发任何输入）。

    #31 gap3：结束（尤其 timeout / stall / title）时改用 :func:`_terminate_task` —— 停止是
    「请求 + 有界轮询」，绝不阻塞在 ``post_stop().wait()``（任务卡死时它永不返回）。
    ``stop_timeout`` 是确认停止的上限；到期即归还控制。
    """
    job = tasker.post_task(entry, override)
    tid = job.job_id
    start = time.time()
    executed: list[str] = []
    prev = 0
    last_progress = start
    status = "timeout"

    print(f"[追踪] 投递 {entry}（job={tid}，超时 {timeout}s，stall {stall_timeout}s）")
    try:
        while True:
            time.sleep(1.0)

            # 标题页守护：出现标题页即停手
            if watcher is not None and watcher.enabled and watcher.detect():
                status = "title"
                print("[追踪] 检测到标题页，停手")
                break

            try:
                detail = tasker.get_task_detail(tid)
                nodes = list(detail.nodes) if detail is not None else []
                for nd in nodes[prev:]:
                    executed.append(getattr(nd, "name", "?"))
                if len(nodes) != prev:
                    last_progress = time.time()
                prev = len(nodes)
            except Exception as exc:  # noqa: BLE001
                print(f"[追踪] 节点读取异常：{exc}")

            if job.done:
                status = _job_status(job)
                break

            now = time.time()
            if timeout and (now - start) > timeout:
                status = "timeout"
                break
            if stall_timeout and (now - last_progress) > stall_timeout:
                status = "stalled"
                print(f"[追踪] 节点 {stall_timeout}s 无新增，判定 stall")
                break
    finally:
        if not job.done:
            _terminate_task(tasker, job, deadline=stop_timeout)

    print(f"[追踪] 结束 status={status}，节点数={len(executed)}")
    return status, executed


# ---------------------------------------------------------------------------
# #20：pipeline 自定义识别 / 动作的【唯一注册源】
# ---------------------------------------------------------------------------
# 真机 runner 过去各自手写一份注册清单，漏注册 pipeline 引用的动作在真机上会静默
# 变成 no-op（#13 实证）：
#     [ERR][CustomAction::run] Action is null [node_name=SpecialStallRecover]
#     [param.name=restart_game]
# 看门狗命中了 stall_recover，却因为 runner 没注册 restart_game 而救不了。
#
# 这里把「pipeline 引用到的全部自定义名 -> 进程内可导入的实现」收敛成一张表；
# runner 只调 register_pipeline_customs(res)。守卫 tools/contract_hooks/hooks_20.py
# 拿它跟 pipeline 实际引用名对账，缺一个即红（不必等真机走到那一步）。
#
# 实现来源与 agent 侧（agent/my_action.py / agent/my_reco.py）的注册一致：
#   · side_impl / phantom_impl —— 设备无关实现（刻意不导入 maa.agent）；
#   · 本模块 —— 仅 agent 侧才有的名在 runner 侧的等价实现
#     （restart_game / wait_seconds / stage_next / stage_all_done）。
# ---------------------------------------------------------------------------

_STAGE_LOCK = threading.Lock()
_STAGE_ATTEMPTED: set[str] = set()
_STAGE_LAST_TASK_ID: "int | None" = None


def _stage_sync_task(task_id) -> None:
    """换了一轮任务就清空「已打过关卡」记录（镜像 agent/my_reco.py）。"""
    global _STAGE_LAST_TASK_ID
    with _STAGE_LOCK:
        if (
            task_id is not None
            and _STAGE_LAST_TASK_ID is not None
            and task_id != _STAGE_LAST_TASK_ID
        ):
            _STAGE_ATTEMPTED.clear()
            print("[stage] task 变化，清空已打关卡记录")
        if task_id is not None:
            _STAGE_LAST_TASK_ID = task_id


def _stage_analyze_rows(context, argv):
    """镜像 agent/my_reco.py::_analyze_rows（纯逻辑单源仍在 stage_rows）。"""
    from maa_util import ocr_all, read_param
    from stage_rows import (
        DEFAULT_FIGHT_TEXT,
        DEFAULT_ROW_DY,
        DEFAULT_STAGE_REGEX,
        parse_stage_rows,
    )

    param = read_param(argv)
    stage_regex = param.get("stage_regex") or DEFAULT_STAGE_REGEX
    fight_text = param.get("fight_text") or DEFAULT_FIGHT_TEXT
    row_dy = int(param.get("row_dy") or DEFAULT_ROW_DY)
    ocr_entry = param.get("ocr_entry") or "OcrTask"

    _stage_sync_task(getattr(argv.task_detail, "task_id", None))
    items = ocr_all(context, argv.image, ocr_entry)
    return parse_stage_rows(items, stage_regex, fight_text, row_dy)


class StageNextRecognition(CustomRecognition):
    """runner 侧镜像 agent/my_reco.py::StageNextRecognition（"stage_next"）。

    ★为什么在本模块再登一份★：my_reco 顶层 `import maa.agent`，一旦导入会切换
    native 库、Resource() 直接创建失败，真机 runner 无法复用它。实现逻辑仍【单源】
    在 stage_rows；本类只是把它包成 runner 可注册的 CustomRecognition。
    """

    def analyze(self, context, argv):  # noqa: D102
        from stage_rows import normalize_key, pick_next

        rows = _stage_analyze_rows(context, argv)
        if not rows:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "未找到关卡行（可能不在关卡列表页）"}
            )
        with _STAGE_LOCK:
            attempted = set(_STAGE_ATTEMPTED)
        picked = pick_next(rows, attempted)
        if picked is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "可见关卡都已打过", "rows": [r[0] for r in rows]},
            )
        text, fight_box = picked
        with _STAGE_LOCK:
            _STAGE_ATTEMPTED.add(normalize_key(text))
            total = len(_STAGE_ATTEMPTED)
        print(f"[stage_next] 选中 {text} -> 点战斗 {fight_box}（累计已记录 {total} 关）")
        return CustomRecognition.AnalyzeResult(
            box=fight_box, detail={"stage": text, "attempted": total}
        )


class StageAllDoneRecognition(CustomRecognition):
    """runner 侧镜像 agent/my_reco.py::StageAllDoneRecognition（"stage_all_done"）。"""

    def analyze(self, context, argv):  # noqa: D102
        from stage_rows import is_all_done

        rows = _stage_analyze_rows(context, argv)
        if not rows:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "未找到关卡行（可能不在关卡列表页）"}
            )
        with _STAGE_LOCK:
            attempted = set(_STAGE_ATTEMPTED)
        if not is_all_done(rows, attempted):
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"reason": "还有未打过的关卡，交给 stage_next 处理"}
            )
        print(f"[stage_all_done] 可见关卡全部打过：{[r[0] for r in rows]}")
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 0, 0], detail={"all_done": [r[0] for r in rows]}
        )


class WaitSecondsAction(CustomAction):
    """runner 侧镜像 agent/my_action.py::WaitSecondsAction（"wait_seconds"）。"""

    def run(self, context, argv):  # noqa: D102
        import json as _json

        param = _json.loads(getattr(argv, "custom_action_param", None) or "{}") or {}
        try:
            seconds = float(param.get("seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        seconds = max(0.0, min(seconds, 300.0))
        print(f"[wait_seconds] 等待 {seconds}s")
        time.sleep(seconds)
        return True


class RestartGameAction(CustomAction):
    """runner 侧实现 custom_action "restart_game"（#20 的核心缺口）。

    与 agent/my_action.py::RestartGameAction 是【同一套设备无关流程】——
    phantom_impl.PhantomRestartAction 就是它的实现（my_action.py 自己的注释亦如此说：
    "与 phantom_impl.PhantomRestartAction 完全同一套做法"）。这里直接委派，
    保证真机上 SpecialStallRecover 命中后能真的强杀重开、把游戏拉回主城。
    ★绝不使用 KeyEvent 4★。
    """

    def run(self, context, argv):  # noqa: D102
        print("[restart_game] 委派 phantom_impl.PhantomRestartAction（同一套强杀重开流程）")
        return _resolve_custom_class("phantom_impl:PhantomRestartAction")().run(context, argv)


#: 自定义识别名 -> "<module>:<Class>"（进程内可实现、与 agent 侧注册一致）。
CUSTOM_RECOGNITIONS: dict[str, str] = {
    # side_impl（外传 / 特殊副本 / 主线）
    "next_stage": "side_impl:NextStageRecognition",
    "no_list_badge": "side_impl:NoListBadgeRecognition",
    "list_all_done": "side_impl:ListAllDoneRecognition",
    "page_done_repeat": "side_impl:PageDoneRepeatRecognition",
    "stall_recover": "side_impl:StallRecoverRecognition",
    # team_impl（#91 切换编队）：读 `SET N` / `N Party X` / 战力
    "team_state": "team_impl:TeamStateRecognition",
    # lords_impl（#100 领主战全难度解禁）：读列表页 `通关数 N/M` / 选出下一处该点的框。
    #   判定真源在 scene/lords_unlock.py；本项只让 runner 的唯一注册源覆盖 pipeline 的引用（hooks_20）。
    "lords_progress": "lords_impl:LordsProgressRecognition",
    "special_batch_plan": "side_impl:SpecialBatchPlanRecognition",
    "special_target_fight": "side_impl:SpecialTargetFightRecognition",
    "batch_mode": "side_impl:BatchModeRecognition",
    # phantom_impl（幻想连战）
    "phantom_state": "phantom_impl:PhantomStateRecognition",
    "phantom_done": "phantom_impl:PhantomDoneRecognition",
    "phantom_giveup": "phantom_impl:PhantomGiveUpRecognition",
    # abyss_impl（深渊连战EX #55 Phase 2 / 普通深渊 #55 Phase 3：同一实现按场景 id 参数化）
    "abyss_state": "abyss_impl:AbyssStateRecognition",
    "abyss_giveup": "abyss_impl:AbyssGiveUpRecognition",
    "abyss_scene": "abyss_impl:AbyssSceneRecognition",
    # wuchong_impl（五重决战，#56 Phase 4：共斗开房 + ★手操战斗★ + 跨模式自动规则）
    # ★additive★ 仅为让 runner 的唯一注册源覆盖 pipeline 引用的新自定义名（hooks_20 守卫）。
    "wuchong_state": "wuchong_impl:WuchongStateRecognition",
    "wuchong_switch_state": "wuchong_impl:WuchongSwitchStateRecognition",
    "wuchong_giveup": "wuchong_impl:WuchongGiveUpRecognition",
    "wuchong_net": "wuchong_impl:WuchongNetGuardRecognition",
    "wuchong_renav": "wuchong_impl:WuchongRenavRecognition",
    # ★#72★ GAMEOVER 续关上限闸（五重在 GAMEOVER 屏点【续关】，不是【放弃】）。
    "wuchong_continue_guard": "wuchong_impl:WuchongContinueGuardRecognition",
    # 场景无关「自动」按钮（#56 二批：自动的切换移到战斗外）：
    #   auto_switch_state → 定位（模板/OCR）+ 读开/关；auto_cont_dialog → 「自动续战功能」框。
    "auto_switch_state": "auto_switch_impl:AutoSwitchStateRecognition",
    "auto_cont_dialog": "auto_switch_impl:AutoContDialogRecognition",
    # 本模块（agent 侧在 my_reco，无法导入 —— 见 StageNextRecognition 注释）
    "stage_next": "live_harness:StageNextRecognition",
    "stage_all_done": "live_harness:StageAllDoneRecognition",
}

#: 自定义动作名 -> "<module>:<Class>"。
CUSTOM_ACTIONS: dict[str, str] = {
    "mark_done": "side_impl:MarkDoneAction",
    # team_impl（#91）：闭环切 SET/队（读→点邻居→再读）
    "team_switch": "team_impl:TeamSwitchAction",
    # ★#105★ A 类战前编队页就地切 SET（队切换未标定 → 拒动）
    "team_switch_battle": "team_impl:TeamSwitchBattleAction",
    "special_batch_fight": "side_impl:SpecialBatchFightAction",
    "special_batch_finish": "side_impl:SpecialBatchFinishAction",
    # lords_impl（#100 领主战全难度解禁）：把识别选出的那一处点下去（一次只点一下，不打战斗）。
    "lords_unlock_step": "lords_impl:LordsUnlockAction",
    "phantom_act": "phantom_impl:PhantomActAction",
    "phantom_restart": "phantom_impl:PhantomRestartAction",
    # abyss_impl（深渊连战EX，#55 Phase 2）：OCR 按钮点击 + 数据驱动页签搜索（step=tab）。
    "abyss_act": "abyss_impl:AbyssActAction",
    # wuchong_impl（五重决战，#56 Phase 4）：OCR/模板点击 + ★手操战斗★ + 开关（含跨模式自动规则）。
    # ★additive★ 仅为覆盖 pipeline 引用的新自定义动作名（hooks_20 守卫）。
    "wuchong_act": "wuchong_impl:WuchongActAction",
    "wuchong_battle": "wuchong_impl:WuchongBattleAction",
    "wuchong_switch": "wuchong_impl:WuchongSwitchAction",
    # 场景无关「自动」按钮开关动作（#56 二批）：定位 + 读状态 + 点识别框中心；非五重夹回「开」。
    "auto_switch": "auto_switch_impl:AutoSwitchSetAction",
    # 本模块（agent 侧在 my_action，无法导入 —— 见 RestartGameAction 注释）
    "restart_game": "live_harness:RestartGameAction",
    "wait_seconds": "live_harness:WaitSecondsAction",
}


def _resolve_custom_class(spec: str):
    """把 ``"<module>:<Class>"`` 解析成类（本模块用 globals，其余用 importlib）。"""
    mod_name, _, cls_name = spec.partition(":")
    if mod_name in (__name__, __name__.rsplit(".", 1)[-1]):
        return globals()[cls_name]
    return getattr(importlib.import_module(mod_name), cls_name)


def registered_custom_names() -> tuple[set[str], set[str]]:
    """返回本注册表覆盖的 (识别名集合, 动作名集合)（离线对账用，不需要设备）。"""
    return set(CUSTOM_RECOGNITIONS), set(CUSTOM_ACTIONS)


def register_pipeline_customs(res) -> list[str]:
    """把 pipeline 引用到的【全部】自定义识别 / 动作注册到 Resource（#20）。

    返回已注册的名字列表（识别在前、动作在后），供调用方打印/断言。
    """
    done: list[str] = []
    for name, spec in CUSTOM_RECOGNITIONS.items():
        res.register_custom_recognition(name, _resolve_custom_class(spec)())
        done.append(name)
    for name, spec in CUSTOM_ACTIONS.items():
        res.register_custom_action(name, _resolve_custom_class(spec)())
        done.append(name)
    print(f"[harness] 已注册 {len(done)} 个 pipeline 自定义识别/动作：{done}")
    return done


if __name__ == "__main__":  # noqa: D401 -- 离线维护入口（不连设备、不加载资源）
    # 用法：
    #   python tools/live_harness.py --bound-debug [--project DIR] [--dry-run]
    # 只做一件事：把 <project>/debug 下的排障产物收敛到上界（见 bound_debug_artifacts）。
    # 之所以做成显式 CLI，是因为 runner 侧已自动调用（apply_global_options）；
    # 这里给「先跑一遍、再统一清理」的操作者一个不动设备的手动入口。
    if "--bound-debug" in sys.argv:
        raise SystemExit(_bound_debug_cli(sys.argv[1:]))
    print(__doc__.strip().splitlines()[0])
    print("离线维护用法：python tools/live_harness.py --bound-debug [--project DIR] [--dry-run]")
