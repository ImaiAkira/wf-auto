"""通用进度账本（progress ledger）—— 记录「已经打过哪些关」，跨运行持久化。

设计目标
--------
把 agent/my_reco.py 里 `stage_next` / `stage_all_done` 那套「进程内存里记一笔」的
做法，升级成 **落盘 + 通用** 的版本，供「外传 / 特殊副本」等任务复用：

    * 落盘位置：**agent 包所在目录的上一级**（= interface.json 所在目录，
      也就是 MFAAvalonia 的 ReplacePlaceholder 给 agent 子进程设置的工作目录）下的
      progress.json。**不再依赖进程 CWD**：无论 MFAAvalonia 把子进程的 CWD 设成什么，
      读写都是同一份账本（详见 ``_default_file``）。
    * key 形如 `{场景}/{副本}/{关卡}`，例如 `side_story/百兽王冠/前往圣地`。
      key 里的空白会被去掉，避免 OCR 把 "前往 圣地" 读成两条。
    * 跨运行持久：重开一次任务、甚至重开 MFAAvalonia，账本都还在。

与现有 stage_rows.py / stage_next 的关系
---------------------------------------
`stage_next` 用 `pick_next(rows, attempted)`：给定「可见关卡行」和「已打过集合」，
返回第一个没打过的行。本模块的 `next_of(keys)` 是完全相同的语义，只是把
「已打过集合」换成持久账本 `is_done`。换句话说：**本模块就是 stage_next 记录
机制的通用化落盘版**，没有另起一套算法。

对外 API（模块级函数，直接用）
-----------------------------
    is_done(key)        该 key 是否已完成
    mark_done(key)      标记完成（落盘）
    next_of(keys)       按给定顺序返回第一个「未完成」的 key；全完成返回 None
    scope(prefix)       返回以 prefix 开头的所有已完成 key（排序后）
    reset(prefix=None)  清空账本；给 prefix 时只清该前缀

「待记账」辅助（给 next_stage -> mark_done 用）
---------------------------------------------
    set_pending(scope, stage)   记住「刚刚选中、还没做完」的关卡
    get_pending(scope=None)     读取（scope 为空时取最近一次）
    pop_pending(scope=None)     读取并清除
    clear_pending(scope=None)

测试可以用 `Progress(path=...)` 直接操作临时文件，不受 CWD 影响。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

# 默认文件名（相对 CWD）。测试可用环境变量 MAA_PROGRESS_FILE 覆盖。
DEFAULT_FILENAME = "progress.json"

_LOCK = threading.RLock()
_DEFAULT: Optional["Progress"] = None


def normalize_key(key: str) -> str:
    """规范化 key：去空白、统一斜杠、去掉首尾斜杠。

    OCR 时 "前往 圣地" / "前往圣地" 必须落到同一条账目上。
    """
    if not key:
        return ""
    key = re.sub(r"\s+", "", str(key))
    key = key.replace("\\", "/")
    key = re.sub(r"/{2,}", "/", key)
    return key.strip("/")


def make_key(scene: str, scope: str, name: str) -> str:
    """拼出 `{场景}/{副本}/{关卡}` 形式的 key。"""
    return normalize_key(f"{scene}/{scope}/{name}")


def _default_file() -> Path:
    """账本默认落盘位置（★不依赖进程 CWD★）。

    · 环境变量 ``MAA_PROGRESS_FILE`` 优先（测试 / 调试用）；
    · 否则固定在 **agent 包所在目录的上一级**：
        - 用户安装态：``install/agent/progress.py`` → ``install/progress.json``
        - 开发仓库：  ``wf-auto/agent/progress.py``  → ``wf-auto/progress.json``

    ★为什么不用 ``Path("progress.json")``（CWD 相对）★
      此前按 CWD 落盘，而 CWD 由 MFAAvalonia 决定（理论上 = interface.json 所在目录）。
      一旦 CWD 与预期不一致（换启动方式 / 换工作目录 / 工具直接从别处拉起 agent），
      账本就会「写到 A、下轮从 B 读」→ 断点续跑读到空账本、已完成的套清零重打。
      改成相对【本模块位置】解析后，读写位置恒定且唯一，与 CWD 无关。
    """
    env = os.environ.get("MAA_PROGRESS_FILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / DEFAULT_FILENAME


class Progress:
    """一个 JSON 账本实例。线程安全（同一进程内）。"""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self.path = Path(path) if path is not None else _default_file()
        self._loaded = False
        self._done: set[str] = set()

    # ------------------------------------------------------------------ IO
    def _load(self) -> None:
        if self._loaded:
            return
        self._done = set()
        try:
            if self.path.is_file():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    done = raw.get("done") or []
                elif isinstance(raw, list):
                    done = raw
                else:
                    done = []
                if isinstance(done, list):
                    self._done = {normalize_key(k) for k in done if k}
        except (OSError, ValueError, TypeError) as exc:  # noqa: BLE001
            print(f"[progress] 读取 {self.path} 失败（按空账本处理）：{exc}")
            self._done = set()
        self._loaded = True

    def _save(self) -> None:
        data = {
            "version": 1,
            "done": sorted(self._done),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError as exc:  # noqa: BLE001
            print(f"[progress] 写入 {self.path} 失败：{exc}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ API
    def all_keys(self) -> list[str]:
        with _LOCK:
            self._load()
            return sorted(self._done)

    def is_done(self, key: str) -> bool:
        key = normalize_key(key)
        if not key:
            return False
        with _LOCK:
            self._load()
            return key in self._done

    def mark_done(self, key: str) -> bool:
        """标记完成。返回 True 表示这是新记的一笔。"""
        key = normalize_key(key)
        if not key:
            return False
        with _LOCK:
            self._load()
            if key in self._done:
                return False
            self._done.add(key)
            self._save()
            return True

    def next_of(self, keys) -> Optional[str]:
        """按给定顺序返回第一个未完成的 key；全部完成返回 None。

        这就是 stage_next 里 pick_next 的通用版（顺序即优先级）。
        """
        with _LOCK:
            self._load()
            for key in keys or []:
                nk = normalize_key(key)
                if nk and nk not in self._done:
                    return nk
            return None

    def scope(self, prefix: str) -> list[str]:
        """返回以 prefix 开头的已完成 key（排序）。"""
        prefix = normalize_key(prefix)
        with _LOCK:
            self._load()
            if not prefix:
                return sorted(self._done)
            p = prefix + "/"
            return sorted(k for k in self._done if k == prefix or k.startswith(p))

    def reset(self, prefix: Optional[str] = None) -> int:
        """清空账本；给定 prefix 时只清该前缀。返回清除的条数。"""
        prefix = normalize_key(prefix) if prefix else ""
        with _LOCK:
            self._load()
            if not prefix:
                n = len(self._done)
                self._done.clear()
            else:
                p = prefix + "/"
                keep = {k for k in self._done if not (k == prefix or k.startswith(p))}
                n = len(self._done) - len(keep)
                self._done = keep
            self._save()
            return n


# ===========================================================================
# 模块级默认实例（agent 正常运行用这个；CWD 即 interface.json 所在目录）
# ===========================================================================
def _prog() -> Progress:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = Progress()
        return _DEFAULT


def set_file(path: Optional[Path | str]) -> None:
    """测试/调试用：替换模块级默认账本文件。"""
    global _DEFAULT
    with _LOCK:
        _DEFAULT = Progress(path)


def all_keys() -> list[str]:
    return _prog().all_keys()


def is_done(key: str) -> bool:
    return _prog().is_done(key)


def mark_done(key: str) -> bool:
    return _prog().mark_done(key)


def next_of(keys) -> Optional[str]:
    return _prog().next_of(keys)


def scope(prefix: str) -> list[str]:
    return _prog().scope(prefix)


def reset(prefix: Optional[str] = None) -> int:
    return _prog().reset(prefix)


# ===========================================================================
# 待记账（pending）：next_stage 选中谁，mark_done 就记谁
# ===========================================================================
_PENDING_LOCK = threading.Lock()
_PENDING: dict[str, str] = {}
_PENDING_ORDER: list[str] = []


def set_pending(scope_name: str, stage: str) -> None:
    scope_name = normalize_key(scope_name)
    stage = normalize_key(stage)
    if not scope_name or not stage:
        return
    with _PENDING_LOCK:
        if scope_name in _PENDING_ORDER:
            _PENDING_ORDER.remove(scope_name)
        _PENDING_ORDER.append(scope_name)
        _PENDING[scope_name] = stage


def get_pending(scope_name: Optional[str] = None) -> Optional[tuple[str, str]]:
    """返回 (scope, stage)。scope 为空时取最近一次 set 的。"""
    with _PENDING_LOCK:
        if scope_name:
            s = normalize_key(scope_name)
            stage = _PENDING.get(s)
            return (s, stage) if stage else None
        if not _PENDING_ORDER:
            return None
        s = _PENDING_ORDER[-1]
        stage = _PENDING.get(s)
        return (s, stage) if stage else None


def pop_pending(scope_name: Optional[str] = None) -> Optional[tuple[str, str]]:
    with _PENDING_LOCK:
        if scope_name:
            s = normalize_key(scope_name)
        elif _PENDING_ORDER:
            s = _PENDING_ORDER[-1]
        else:
            return None
        stage = _PENDING.pop(s, None)
        if s in _PENDING_ORDER:
            _PENDING_ORDER.remove(s)
        return (s, stage) if stage else None


def clear_pending(scope_name: Optional[str] = None) -> None:
    with _PENDING_LOCK:
        if scope_name:
            s = normalize_key(scope_name)
            _PENDING.pop(s, None)
            if s in _PENDING_ORDER:
                _PENDING_ORDER.remove(s)
        else:
            _PENDING.clear()
            _PENDING_ORDER.clear()
