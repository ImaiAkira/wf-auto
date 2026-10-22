#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库的 agent / resource 同步进 ``install/``，并逐文件做内容哈希校验（#138）。

为什么需要
----------
``install/`` 是 gitignored 的构建产物。``--as-gui`` 的语义是「资源从
``install/resource`` 读、代码从仓库 ``agent/`` 导入」——install 落后时就是
**旧流水线 + 新代码** 的最坏混合：日志里看到的修复与实际生效的修复不是同一份。

``tools/install.py`` 是**发布打包**入口（带 version/os/arch，会重装 deps、写
interface.json 版本），不适合日常同步；本脚本只做一件事：把源目录按内容哈希
同步进 ``install/``，并打印同步前后的差异/校验结果。

用法
----
::

    python tools/sync_install.py            # 同步 + 同步后校验（退出码 0/1/2）
    python tools/sync_install.py --check    # 只校验、不写盘（0 = 一致，1 = 落后）
    python tools/sync_install.py --no-prune # 不删除 install 里多出来的旧文件

同步范围（与 ``--as-gui`` 硬闸共用同一份 :data:`SCOPES`，避免两处范围漂移）
--------------------------------------------------------------------------
* ``agent/`` → ``install/agent``：全部源文件；忽略 ``__pycache__`` / ``*.pyc`` /
  ``*.pyo`` / ``debug``（与 ``tools/install.py`` 的 ignore 一致）
* ``assets/resource/pipeline/**/*.json`` → ``install/resource/pipeline``
* ``assets/resource/image/**/*.png`` → ``install/resource/image``
* ``assets/resource/model/`` → ``install/resource/model``（本地 OCR 模型，gitignored）

硬闸只比对前三项（票面 #138：pipeline ``*.json`` + ``image/**/*.png``）；model 只
同步，不参与 ``--as-gui`` 的放行/拦下判断，避免把「本机没下 OCR 模型」误判成
流水线落后。

退出码
------
* ``0`` —— 一致（或同步后一致）
* ``1`` —— 仍不一致（``--check`` 发现落后；或同步后仍有差异）
* ``2`` —— 源目录缺失 / 参数错误（不写盘）
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_ROOT = REPO_ROOT / "install"

#: 用户可直接复制的修法命令（--as-gui 硬闸与本文档共用同一条，避免文案漂移）。
FIX_COMMAND = "python tools/sync_install.py"
FIX_HINT = f"修法（在仓库根执行，可复制）：{FIX_COMMAND}"

_HASH_CHUNK = 1024 * 1024
_DISPLAY_LIMIT = 8


@dataclass(frozen=True)
class Scope:
    """一个「源目录 → install 子目录」的同步/比对范围。

    ``suffixes`` 为空表示全部文件；否则只收这些后缀（例如 pipeline 只比 ``*.json``）。
    ``ignore_dirs`` / ``ignore_suffixes`` 与 ``tools/install.py`` 的 agent ignore 对齐。
    """

    name: str
    src_rel: str
    dst_sub: str
    suffixes: tuple[str, ...] = ()
    gate: bool = True
    ignore_dirs: tuple[str, ...] = ()
    ignore_suffixes: tuple[str, ...] = ()

    @property
    def src_label(self) -> str:
        return self.src_rel.replace("\\", "/")

    @property
    def dst_label(self) -> str:
        return f"install/{self.dst_sub}"

    @property
    def label(self) -> str:
        return f"{self.dst_label} ↔ {self.src_label}"


#: ★唯一真源★：同步脚本、硬闸、守卫都从这里取范围。
SCOPES: tuple[Scope, ...] = (
    Scope(
        "agent",
        "agent",
        "agent",
        ignore_dirs=("__pycache__", "debug"),
        ignore_suffixes=(".pyc", ".pyo"),
    ),
    Scope("pipeline", "assets/resource/pipeline", "resource/pipeline", suffixes=(".json",)),
    Scope("image", "assets/resource/image", "resource/image", suffixes=(".png",)),
    Scope("model", "assets/resource/model", "resource/model", gate=False),
)

#: ``--as-gui`` 硬闸比对的范围（agent + pipeline + image）。
GATE_SCOPE_NAMES: tuple[str, ...] = tuple(s.name for s in SCOPES if s.gate)
#: 同步脚本写盘的范围（agent + pipeline + image + model）。
SYNC_SCOPE_NAMES: tuple[str, ...] = tuple(s.name for s in SCOPES)
#: 同步后「差异为 0」判据的范围（全部，含 model）；独立常量，方便破坏实验只改同步集合。
ALL_SCOPE_NAMES: tuple[str, ...] = tuple(s.name for s in SCOPES)


def scope_by_name(name: str) -> Scope:
    for scope in SCOPES:
        if scope.name == name:
            return scope
    raise KeyError(f"未知同步范围：{name!r}（可选 {[s.name for s in SCOPES]}）")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path, scope: Scope) -> dict[str, Path]:
    """``root`` 下属于 ``scope`` 的文件：``相对 posix 路径 -> Path``（已排序）。"""
    if not root.is_dir():
        return {}
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if scope.ignore_dirs and any(part in scope.ignore_dirs for part in rel.parts[:-1]):
            continue
        if scope.ignore_suffixes and path.suffix.lower() in scope.ignore_suffixes:
            continue
        if scope.suffixes and path.suffix.lower() not in scope.suffixes:
            continue
        found[rel.as_posix()] = path
    return found


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "?"


@dataclass(frozen=True)
class TreeDiff:
    """一个 Scope 的逐文件比对结果（路径都是相对各自根目录的 posix 串）。"""

    scope: str
    label: str
    src_label: str
    dst_label: str
    src_dir: Path
    dst_dir: Path
    source_count: int
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def is_fresh(self) -> bool:
        return not (self.missing or self.extra or self.changed)

    @property
    def diff_count(self) -> int:
        return len(self.missing) + len(self.extra) + len(self.changed)


@dataclass(frozen=True)
class InstallDiff:
    repo_root: Path
    install_root: Path
    trees: tuple[TreeDiff, ...]

    def tree(self, name: str) -> TreeDiff:
        for tree in self.trees:
            if tree.scope == name:
                return tree
        raise KeyError(name)

    def _gate_trees(self) -> tuple[TreeDiff, ...]:
        names = set(GATE_SCOPE_NAMES)
        return tuple(tree for tree in self.trees if tree.scope in names)

    @property
    def gate_stale(self) -> bool:
        """``--as-gui`` 是否必须拒绝启动（只看 GATE_SCOPE_NAMES）。"""
        return any(not tree.is_fresh for tree in self._gate_trees())

    @property
    def is_fresh(self) -> bool:
        return all(tree.is_fresh for tree in self.trees)

    @property
    def stale_trees(self) -> tuple[TreeDiff, ...]:
        return tuple(tree for tree in self.trees if not tree.is_fresh)


def compare_install(
    repo_root: Path | str | None = None,
    install_root: Path | str | None = None,
    *,
    scope_names: tuple[str, ...] | None = None,
) -> InstallDiff:
    """按内容哈希比对 ``install/`` 与仓库源；默认只比硬闸范围（agent/pipeline/image）。"""
    repo = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    install = (
        Path(install_root).resolve() if install_root is not None else (repo / "install")
    )
    names = GATE_SCOPE_NAMES if scope_names is None else tuple(scope_names)
    trees: list[TreeDiff] = []
    for name in names:
        scope = scope_by_name(name)
        src_dir = repo / scope.src_rel
        dst_dir = install / scope.dst_sub
        src_files = _files(src_dir, scope)
        dst_files = _files(dst_dir, scope)
        src_keys = set(src_files)
        dst_keys = set(dst_files)
        changed = tuple(
            rel
            for rel in sorted(src_keys & dst_keys)
            if _sha256(src_files[rel]) != _sha256(dst_files[rel])
        )
        trees.append(
            TreeDiff(
                scope=scope.name,
                label=scope.label,
                src_label=scope.src_label,
                dst_label=scope.dst_label,
                src_dir=src_dir,
                dst_dir=dst_dir,
                source_count=len(src_files),
                missing=tuple(sorted(src_keys - dst_keys)),
                extra=tuple(sorted(dst_keys - src_keys)),
                changed=changed,
            )
        )
    return InstallDiff(repo_root=repo, install_root=install, trees=tuple(trees))


def format_lines(
    report: InstallDiff,
    *,
    prefix: str = "",
    limit: int | None = _DISPLAY_LIMIT,
    include_model: bool = False,
) -> list[str]:
    """把差异渲染成可读行（``limit=None`` 打印全部；``✓ 一致`` 也在这里统一措辞）。"""
    lines: list[str] = []
    allowed = set(GATE_SCOPE_NAMES)
    if include_model:
        allowed = {scope.name for scope in SCOPES}
    for tree in report.trees:
        if tree.scope not in allowed:
            continue
        if tree.is_fresh:
            if tree.source_count == 0:
                continue  # 源与 install 都没有这个范围（如本机没下 model）——不刷「0 个文件一致」
            lines.append(
                f"{prefix}✓ {tree.label} 一致（{tree.source_count} 个文件，sha256 逐项相同）"
            )
            continue
        lines.append(
            f"{prefix}✗ {tree.label} 不一致：内容不同 {len(tree.changed)} / "
            f"install 缺失 {len(tree.missing)} / install 多余 {len(tree.extra)}"
        )
        for rel in tree.changed if limit is None else tree.changed[:limit]:
            lines.append(
                f"{prefix}  - 内容不同：{tree.dst_label}/{rel}"
                f"（仓库 {_mtime(tree.src_dir / rel)} / install {_mtime(tree.dst_dir / rel)}）"
            )
        for rel in tree.missing if limit is None else tree.missing[:limit]:
            lines.append(f"{prefix}  - install 缺失：{tree.dst_label}/{rel}")
        for rel in tree.extra if limit is None else tree.extra[:limit]:
            lines.append(f"{prefix}  - install 多余：{tree.dst_label}/{rel}")
        if limit is not None:
            for label, items in (
                ("内容不同", tree.changed),
                ("install 缺失", tree.missing),
                ("install 多余", tree.extra),
            ):
                if len(items) > limit:
                    lines.append(
                        f"{prefix}  - … {label}还有 {len(items) - limit} 项（完整清单："
                        f"{FIX_COMMAND} --check）"
                    )
    return lines


class SyncError(RuntimeError):
    """源目录缺失等无法继续同步的错误（CLI 以退出码 2 报）。"""


def _copy_scope(repo: Path, install: Path, scope: Scope, *, prune: bool) -> tuple[int, int]:
    """把一个 Scope 从仓库复制进 install；返回 ``(复制数, 删除数)``。"""
    src_dir = repo / scope.src_rel
    if not src_dir.is_dir():
        if scope.name == "model":
            # OCR 模型目录是 gitignored 的本地构建输入，允许缺失（硬闸也不比它）。
            if (install / scope.dst_sub).is_dir():
                print(
                    f"[sync-install] ! 源目录 {scope.src_rel} 不存在：保留 install 里已有的 model"
                    "（不删旧模型）"
                )
            return (0, 0)
        raise SyncError(f"源目录不存在：{scope.src_rel}（在 {repo} 下）")
    dst_dir = install / scope.dst_sub
    src_files = _files(src_dir, scope)
    copied = 0
    for rel, src_path in src_files.items():
        dst_path = dst_dir / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        copied += 1
    deleted = 0
    if prune:
        for rel, dst_path in _files(dst_dir, scope).items():
            if rel not in src_files:
                dst_path.unlink()
                deleted += 1
    return copied, deleted


def sync_project(
    repo_root: Path | str | None = None,
    install_root: Path | str | None = None,
    *,
    prune: bool = True,
    quiet: bool = False,
) -> InstallDiff:
    """把仓库源目录同步进 ``install/``，打印同步前后校验，返回**同步后**的比对结果。

    ``SYNC_SCOPE_NAMES`` 决定写盘范围；同步后的「差异为 0」判据固定用
    :data:`ALL_SCOPE_NAMES` —— 这样「只拷了 agent」这种半截同步会当场露出来。
    """
    repo = Path(repo_root).resolve() if repo_root is not None else REPO_ROOT
    install = (
        Path(install_root).resolve() if install_root is not None else (repo / "install")
    )
    before = compare_install(repo, install, scope_names=ALL_SCOPE_NAMES)
    if not quiet:
        print("[sync-install] 同步前：")
        for line in format_lines(before, prefix="[sync-install] ", include_model=True):
            print(line)
    copied = 0
    deleted = 0
    for name in SYNC_SCOPE_NAMES:
        scope = scope_by_name(name)
        c, d = _copy_scope(repo, install, scope, prune=prune)
        copied += c
        deleted += d
    after = compare_install(repo, install, scope_names=ALL_SCOPE_NAMES)
    if not quiet:
        print(f"[sync-install] 同步完成：复制 {copied} 个文件 / 删除 {deleted} 个旧文件")
        print("[sync-install] 同步后：")
        for line in format_lines(after, prefix="[sync-install] ", include_model=True):
            print(line)
    if after.is_fresh:
        if not quiet:
            print(f"[sync-install] ✓ install 与仓库一致（{FIX_COMMAND} 可重复执行，幂等）")
    else:
        if not quiet:
            print("[sync-install] ✗ 同步后仍不一致，见上面的差异清单")
    return after


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 agent / assets/resource 同步进 install/，并打印逐文件哈希校验（#138）"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验不写盘：0 = 一致，1 = 落后",
    )
    parser.add_argument(
        "--no-prune",
        dest="no_prune",
        action="store_true",
        help="保留 install 里多出来的旧文件（默认删除，保证同步后差异为 0）",
    )
    parser.add_argument("--repo-root", default=None, help="仓库根（默认本文件上一级）")
    parser.add_argument("--install-root", default=None, help="install 目录（默认 <repo>/install）")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT
    install = Path(args.install_root).resolve() if args.install_root else (repo / "install")

    if args.check:
        report = compare_install(repo, install)
        for line in format_lines(report, prefix="[sync-install] ", limit=None):
            print(line)
        if report.gate_stale:
            print(f"[sync-install] ✗ install 落后于仓库。{FIX_HINT}")
            return 1
        print("[sync-install] ✓ install 与仓库一致（--as-gui 硬闸会放行）")
        return 0

    try:
        after = sync_project(repo, install, prune=not args.no_prune)
    except SyncError as exc:
        print(f"[sync-install] ✗ {exc}")
        return 2
    return 0 if after.is_fresh else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
