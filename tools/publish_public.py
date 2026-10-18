"""把当前仓库裁剪成「公开快照」的 git tree，**不动工作区、不动真实 index**。

为什么要这么绕：脱敏/交付链可能有好几条并行线在改工作区。用 `git checkout --orphan`
会切分支、动工作树，直接把并行的活搅坏。这里改用临时 index：

    GIT_INDEX_FILE=<临时文件> git read-tree --empty
    GIT_INDEX_FILE=<临时文件> git add -- <白名单路径>
    tree = git write-tree
    commit = git commit-tree tree -m "..."

产物是一个 tree/commit 对象，工作区一个字节都不变。推送由调用方（发布流程）负责。

## 唯一出口：不要 `git merge` 开发线进公开仓

2026-10-18 真出过一次事故：有人为了让公开仓拿到最新代码，直接把整条 dev 线 merge 进 public 的
`main`，一次带进 **47 个白名单外文件**（19 张未脱敏真机截图 + `docs/research` + `docs/recon` …）。
历史本身是干净的，被带进去的是**文件**。

正确做法只有一个：**改完 dev → 重跑本脚本生成新快照 → 推快照**。
`git merge` 会绕过白名单；本脚本不会。闸门侧也补了形状校验（`verify_no_pii.py --rev` 现在会报
`SHAPE DRIFT`），但那只是第二道网。

用法：

    python tools/publish_public.py --dry-run     # 只列清单与体积，不写对象
    python tools/publish_public.py               # 写 tree + commit，打印 sha
    python tools/publish_public.py --verify <commit>   # 对产物跑脱敏检查

白名单/黑名单就是 spec D7。**改这个文件等于改发布口径**，要同步改 spec。

## 发布流程（不可逆动作，顺序不能颠倒）

    1. python tools/publish_public.py            # 建 tree + commit，本地分支 public-main
    2. python tools/publish_public.py --verify <commit>   # 闸门：零命中才许往下走
    3. gh repo rename wf-auto-dev                # 旧仓改名，历史与 issue 全留在它里面
    4. gh repo create ImaiAkira/wf-auto --public # 新建空仓（名字刚释放）
    5. git push <新 remote> public-main:main     # 只推一个提交，不推 tag、不推其它分支
    6. gh repo edit --description/--add-topic …  # 元数据
    7. git push <新 remote> v<version>           # 触发 install 流水线出 Release

失败可回滚：第 4 步若因名字未释放而失败，先 `gh repo rename wf-auto`（把旧仓名改回来）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 发布口径（spec D7）
# ---------------------------------------------------------------------------

# 收：产品与它的构建输入、面向用户的文档、CI、根级元数据。
INCLUDE = [
    "agent",
    "assets",
    "scene",
    "tools",
    "deps",
    "docs/adr",
    "docs/guide",
    "docs/agents",
    "docs/.markdownlint.yaml",
    ".github",
    "README.md",
    "LICENSE",
    "双击启动.bat",
    "GLOSSARY.md",
    "AGENTS.md",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".prettierrc",
    ".prettierignore",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "maatools.config.mts",
]

# 不收：开发噪声、本机产物、内部标定记录、与产品无关的调研。
# 这里的路径若同时被 INCLUDE 覆盖，以 EXCLUDE 为准。
EXCLUDE = [
    # 内部标定 / 调研：真机事实、设备-账号对照、OCR 对比实验
    "docs/recon",
    "docs/research",
    # 内部工程 spec：含真机会话考古、设备↔账号对照 —— 对用户没有价值，且是 A/D 类风险面
    "docs/spec",
    # 模板的开发文档：教人「用本模板建项目」，对产品用户没意义（README 才是入口）
    "docs/zh_cn",
    # 开发证据截图（ID 遮盖另有专门票；这些不是用户需要的东西）
    "screenshots",
    # 模板遗留的 submodule 声明（index 里其实没有 gitlink，留着只会让用户困惑）
    ".gitmodules",
    # 本机产物 / 运行态（多数已在 .gitignore，这里再兜一层）
    "install",
    "config",
    "debug",
    "logs",
    "progress.json",
    ".venv",
    ".nicegui",
    ".slim",
    ".research",
    "_research",
    ".acl-repair",
]

# 这些目录里就算被 INCLUDE 命中，也不收（当前为空，留作口子）
EXCLUDE_PREFIX_INSIDE = [
    # 例："tools/frames",
]

TARGET_BRANCH = "public-main"
COMMIT_MSG = "initial public release"


def run(args: list[str], env: dict[str, str] | None = None) -> str:
    """跑一条命令，返回 stdout（去尾空白）；失败直接抛，别静默。"""
    proc = subprocess.run(
        args,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"命令失败（exit {proc.returncode}）：{' '.join(args)}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc.stdout.strip()


def tracked_files() -> list[str]:
    """已跟踪 + 未跟踪但**没被 ignore** 的文件。

    只用 `git ls-files`（只有已跟踪）会漏掉这一轮新建、还没来得及 add 的文件
    （`verify_no_pii.py` / `fill_interface.py` / `双击启动.bat` …）。
    而 `.git/` 在某些沙箱下不可写，根本没法 add，所以必须把 `-o` 带上：
    `-c` 已跟踪 + `-o` untracked，`--exclude-standard` 尊重 .gitignore。
    """
    out = run(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"])
    return sorted({p for p in out.split("\0") if p})


def wanted(paths: list[str]) -> list[str]:
    """按白名单/黑名单过滤已跟踪文件。"""
    keep: list[str] = []
    for path in paths:
        posix = path.replace("\\", "/")
        if not any(posix == p or posix.startswith(p + "/") for p in INCLUDE):
            continue
        if any(posix == p or posix.startswith(p + "/") for p in EXCLUDE):
            continue
        if any(posix == p or posix.startswith(p + "/") for p in EXCLUDE_PREFIX_INSIDE):
            continue
        keep.append(posix)
    return keep


def build_tree(files: list[str], index_file: Path) -> str:
    env = {"GIT_INDEX_FILE": str(index_file)}
    run(["git", "read-tree", "--empty"], env=env)
    # 分批传路径（命令行长度有上限），`--` 显式分隔，避免文件名被当成选项
    batch = 200
    for i in range(0, len(files), batch):
        run(["git", "add", "-f", "--", *files[i:i + batch]], env=env)
    return run(["git", "write-tree"], env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只列清单与体积，不写 git 对象")
    ap.add_argument("--verify", metavar="REV", help="对某个 commit/tree 跑脱敏检查后退出")
    args = ap.parse_args()

    if args.verify:
        return verify(args.verify)

    files = wanted(tracked_files())
    total = sum((REPO / f).stat().st_size for f in files if (REPO / f).exists())
    print(f"公开快照：{len(files)} 个文件，{total / 1024 / 1024:.1f} MB")
    print(f"白名单目录：{', '.join(INCLUDE)}")
    print(f"排除：{', '.join(EXCLUDE)}")

    if args.dry_run:
        for f in files:
            print(f"  {f}")
        return 0

    # 临时 index 放在 .git/ 里：沙箱下 %TEMP% 的清理会被拒（chmod 拒绝访问），
    # 而 .git/ 既在可写区、又永远不会被发布。
    index_file = REPO / ".git" / "wf-public-index"
    try:
        index_file.unlink(missing_ok=True)
        tree = build_tree(files, index_file)
    finally:
        try:
            index_file.unlink(missing_ok=True)
        except OSError:
            pass

    commit = run(["git", "commit-tree", tree, "-m", COMMIT_MSG])
    # 只建/挪本地分支，不碰 HEAD、不碰远端
    run(["git", "branch", "-f", TARGET_BRANCH, commit])
    print(f"tree   = {tree}")
    print(f"commit = {commit}")
    print(f"branch = {TARGET_BRANCH}（本地，未推送）")
    print("下一步：python tools/publish_public.py --verify %s" % commit)
    return 0


def verify(rev: str) -> int:
    """对产物跑脱敏检查——**发布闸门**，红就不许推。"""
    checker = REPO / "tools" / "verify_no_pii.py"
    if not checker.exists():
        print("闸门缺失：tools/verify_no_pii.py 还不存在（#132 未完成）", file=sys.stderr)
        return 2
    proc = subprocess.run(
        [sys.executable, str(checker), "--rev", rev],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout.strip())
    if proc.returncode != 0:
        print("闸门未通过：产物里有脱敏命中，**不许推送**。", file=sys.stderr)
        print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode
    print("闸门通过：产物零命中。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
