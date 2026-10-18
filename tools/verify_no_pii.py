#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脱敏守卫：一条命令检查**将要发布的东西**里是否还有 A/B/C/F 四类可识别信息。

用法::

    python tools/verify_no_pii.py                     # 闸门：只扫发布白名单（tools/publish_public.py）
    python tools/verify_no_pii.py --all               # 全仓体检（人工用；不进 CI 闸门）
    python tools/verify_no_pii.py --rev <rev>         # 扫某个 revision 的 tree（发布产物 / 将要推送的 tree）
    python tools/verify_no_pii.py --print-hash <text> # 打印黑名单词哈希（维护本文件用）
    python tools/verify_no_pii.py --explain           # 命中行附上匹配词的 sha256 前 8 位

判定（完整口径见 docs/recon/pii-audit.md）：

    [A] 本机用户名：``X:\\Users\\<真实段>``，或裸用户名（4 字母、L 开头、大小写敏感）
    [B] 盘符绝对路径：``X:\\`` 后跟 >=2 段真实目录名（``X:\\...`` 这类占位不算）
    [C] 游戏账号名黑名单（两个真名）
    [E] 截图侧车里的玩家 ID 残留（``ID:<6 位以上数字>``）
    [F] 其它：``MAA23/*`` 这类失效旧指向

模板残留（``MaaXXX`` / ``MaaPracticeBoilerplate``）**不在这里判**：它们不是个人信息，
属于 #135 的验收项（README/LICENSE 里的「基于上游模板」署名是正当引用）。
守卫只回答一个问题：**我要推出去的东西里有没有我的个人信息**。

为什么默认只扫发布白名单：闸门的语义是「**我要推出去的东西干不干净**」。
`docs/spec` / `docs/recon` / `docs/research` / `docs/zh_cn` 等内部资料按
``tools/publish_public.py`` 的 EXCLUDE 不发布，不该让闸门变红；全仓体检用 ``--all``。

设计取舍：

* **A/C 的敏感词不写明文，只存 SHA-256**。本文件会随 ``tools/`` 进公开仓，
  写明文等于守卫自己泄漏；只存哈希后，扫描器扫到自己时也天然干净，
  不需要“豁免自己”这种会漏掉后续改动的洞。
* **B 的“真实段”排除占位符与单字符片段**：``...``、``<...>``、``%...%`` 不算；
  单字符段用于过滤源码里的正则转义（例如 ``d:\\d`` 会被切成 ``d``/``d``）。
* 黑名单是**大小写敏感**的（Windows 用户名/账号名按原样匹配）。
* 命中时摘录会**隐去敏感片段**：CI 日志在公开仓是公开的，不能把 PII 再打印一遍。
* 豁免只有两处，见 ``EXEMPT_RULES``，每条都写了理由。

退出码：0 = 干净；1 = 有命中；2 = 环境/参数错误（git 不可用等）。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# 发布口径只有一份：直接用 publish_public 的白名单/黑名单，不在这里抄第二份。
# 这样“发布什么”和“检查什么”永远同源（改口径只改 publish_public.py）。
from publish_public import tracked_files, wanted

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 黑名单（敏感词只存 SHA-256，理由见模块 docstring）
# ---------------------------------------------------------------------------
# A：本机用户名。4 字母、L 开头、大小写敏感。更换机器时用
#    ``python tools/verify_no_pii.py --print-hash <新用户名>`` 重算后替换。
LOCAL_USER_SHA256 = "ab70e8a91550f6dd16b51a4e8c6c8f55e4dbe649c7caefa9f6e6f082e152cf6c"
LOCAL_USER_LEN = 4

# C：两个游戏账号名。key = SHA-256，value = 字符长度（用来切候选窗口）。
ACCOUNT_SHA256 = {
    "aba7dbd9c12efbd4c44e3b91fe8ed89d7cebb119156d707c58a98a9823f68449": 2,  # 2 个汉字
    "741b9c4b18bcf6c7b8d30ac91dc3eebd1ae251b8a5654f6c2d2899b56288c821": 6,  # 6 位 ASCII
}

# F：非秘密的“身份残留”标记。字符串拆成片段拼接，避免扫描器扫到自己时自伤
#    （这些词本身不是隐私，只是“本项目不该再这样自称”）。
#    模板名（MaaXXX / MaaPracticeBoilerplate）不在此列：它们不是个人信息，
#    合理署名（README/LICENSE 的「基于上游模板」）不该被隐私闸门判红。
F_NEEDLES = (
    ("MAA" + "23/wf-auto", "失效旧指向"),
)

# ---------------------------------------------------------------------------
# 白名单 / 豁免（必须显式，且每条写理由）
# ---------------------------------------------------------------------------
# (路径前缀, 豁免的类别集合, 理由)
EXEMPT_RULES = (
    (
        "deps/tools/",
        {"A", "B", "C", "F"},
        "上游 MaaFramework 的 JSON schema（第三方文件，不由本项目维护；"
        "schema 里可能出现示例路径/占位词）",
    ),
)

# 目录级跳过：这些要么是已忽略的本地产物，要么是第三方依赖。
SKIP_DIR_PREFIXES = (
    ".git/",
    ".venv/",
    "install/",
    "node_modules/",
    "deps/",  # 例外：deps/tools/*.schema.json 仍会扫（见 _should_scan）
    "logs/",
)

# 二进制后缀：直接跳过（内容里出现 PII 也不该以文本文件方式判）。
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff",
    ".onnx", ".dll", ".exe", ".pyd", ".so", ".dylib", ".a", ".lib",
    ".zip", ".7z", ".gz", ".tar", ".rar", ".pdf", ".docx", ".xlsx", ".pptx",
    ".ttf", ".ttc", ".otf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyo", ".class", ".jar", ".mp3", ".wav", ".mp4", ".avi", ".mov",
    ".bin", ".dat", ".db", ".sqlite", ".pkl", ".npy", ".npz",
}

# ---------------------------------------------------------------------------
# 正则 / 判定
# ---------------------------------------------------------------------------
# A：``C:\Users\<段>`` / ``C:/Users/<段>``（Windows 路径不区分大小写）。
_USERS_DIR_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])([A-Za-z]):[\\/]+Users[\\/]+([^\\/\s\"'<>|:*?]+)"
)

# 占位符段：``<local>`` / ``%USERNAME%`` / ``{user}`` / ``$USER`` / ``...`` / ``…`` / 常见泛称。
_WRAPPED_PLACEHOLDER_RE = re.compile(r"^(?:<[^>]*>|%[^%]*%|\{[^}]*\}|\$[^$]*|\.{2,}|…+)$")
_PLACEHOLDER_WORDS = {
    "user",
    "username",
    "name",
    "local",
    "me",
    "example",
    "placeholder",
    "yourname",
    "your_name",
    "your-name",
    "xxx",
    "xxxx",
}

# B：盘符 + 反斜杠/正斜杠开头的路径。``(?<![A-Za-z0-9_])`` 避免把 URL 里的
#    ``https:``、正则里的 ``\\d:`` 之类当成盘符。允许段内空格（``Program Files``）。
_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]):([\\/][^\"'`<>|*?\r\n]*)")

# 真实路径段的形状：不能带 ``:{}[]()$%<>"'`` 这类字符。
# 这条同时过滤源码里的正则转义（例如 ``d:\d`` 切出来的 ``d:\d`` 段）——
# 它们看起来像路径，实际是 ``\d\d:\d\d`` 这样的正则字面量。
_REAL_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_\u3400-\u9fff][A-Za-z0-9_.\- \u3400-\u9fff]*$")

# 裸 token：A/C 的 ASCII 黑名单按“整词”比较，避免长单词里的短 token 被误命中。
_ASCII_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9_]+(?![A-Za-z0-9_])")
# 连续汉字串：C 的 2 字账号名在其中滑窗。
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
# E：标题画面/侧车里的玩家 ID（``ID:<数字>``）。全 0 视为占位符。
_OCR_ID_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])ID\s*[:：]\s*(\d{6,})(?![0-9])")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_placeholder_segment(seg: str) -> bool:
    if not seg:
        return True
    if _WRAPPED_PLACEHOLDER_RE.match(seg):
        return True
    return seg.lower() in _PLACEHOLDER_WORDS


def _is_real_segment(seg: str) -> bool:
    """B 的“真实目录名”判定：排除占位符、单字符片段与不像文件名的片段。"""
    if len(seg) < 2:
        return False
    if _is_placeholder_segment(seg):
        return False
    return bool(_REAL_SEGMENT_RE.match(seg))


def _split_path_segments(tail: str) -> list[str]:
    # 只去掉行文标点；**不要**去掉点号，否则 ``C:\Users\...\AppData\...`` 里的
    # 占位段 ``...`` 会被误当成不存在，示例路径反而变成“真实路径”。
    tail = tail.rstrip("，。；：、）】,;:)]}>")
    segs = [s.strip() for s in re.split(r"[\\/]+", tail) if s.strip()]
    if segs:
        segs[-1] = segs[-1].rstrip("，。；：、）】,;:)]}>+*")
        if not segs[-1]:
            segs.pop()
    return segs


def _is_exempt(path: str, category: str) -> bool:
    return any(
        path.startswith(prefix) and category in categories
        for prefix, categories, _reason in EXEMPT_RULES
    )


def _should_scan(path: str) -> bool:
    """目录/后缀过滤。deps/ 只放行 deps/tools/*.schema.json（上游 schema）。"""
    p = path.replace("\\", "/")
    if p.startswith("deps/"):
        return p.startswith("deps/tools/") and p.endswith(".schema.json")
    for prefix in SKIP_DIR_PREFIXES:
        if p.startswith(prefix):
            return False
    return Path(p).suffix.lower() not in BINARY_SUFFIXES


def _text_of(blob: bytes) -> str | None:
    """解成文本；二进制返回 None。UTF-16 BOM 单独处理（内容含 NUL 是正常的）。"""
    if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return blob.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in blob[:8192]:
        return None
    try:
        return blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        return blob.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 规则实现：返回 ``(类别, 规则名, start, end, 遮蔽后的整行, 命中词哈希前 8 位)``
# ---------------------------------------------------------------------------
def _scan_line(line: str) -> list[tuple[str, str, int, int, str, str | None]]:
    hits: list[tuple[str, str, int, int, str, str | None]] = []

    def add(cat: str, rule: str, start: int, end: int, digest: str | None = None) -> None:
        masked = line[:start] + "***" + line[end:]
        hits.append((cat, rule, start, end, masked, digest))

    # --- A：C:\Users\<真实段> -------------------------------------------------
    for m in _USERS_DIR_RE.finditer(line):
        seg = m.group(2)
        if _is_placeholder_segment(seg):
            continue
        add("A", "users-dir", m.start(2), m.end(2), _sha256(seg)[:8])

    # --- A：裸用户名（整词、大小写敏感、按哈希比较） -------------------------
    for m in _ASCII_TOKEN_RE.finditer(line):
        tok = m.group(0)
        if len(tok) == LOCAL_USER_LEN and _sha256(tok) == LOCAL_USER_SHA256:
            add("A", "bare-user", m.start(), m.end(), _sha256(tok)[:8])

    # --- B：盘符绝对路径（>=2 段、且每段都是真实目录名） -------------------
    for m in _DRIVE_PATH_RE.finditer(line):
        # 一段里可能连着两条路径（``X:\a\b Y:\c\d``）；在下一个盘符前截断，
        # 避免第二条路径的盘符粘进第一段的目录名里。
        tail = re.split(r"\s+(?=[A-Za-z]:[\\/])", m.group(2), maxsplit=1)[0]
        segs = _split_path_segments(tail)
        if len(segs) < 2:
            continue
        # 只要有一段是占位符（``...`` / ``<user>`` / ``%X%``），整条就是示例路径，
        # 不是本机泄漏（spec 的判定口径：``C:\...`` 这种占位不算）。
        if any(not _is_real_segment(s) for s in segs):
            continue
        # 至少一段不是纯数字（``1:\2\3`` 这类坐标/时间不算路径）。
        if not any(re.search(r"[A-Za-z\u3400-\u9fff]", s) for s in segs):
            continue
        masked = f"{m.group(1)}:" + "\\".join(["***"] * len(segs))
        hits.append(("B", "drive-path", m.start(), m.end(), masked, None))

    # --- C：账号名黑名单（ASCII 整词 + 汉字滑窗） ---------------------------
    for m in _ASCII_TOKEN_RE.finditer(line):
        tok = m.group(0)
        if len(tok) == ACCOUNT_SHA256.get(_sha256(tok)):
            add("C", "account-ascii", m.start(), m.end(), _sha256(tok)[:8])
    for m in _CJK_RUN_RE.finditer(line):
        run = m.group(0)
        for width in (2, 3, 4):
            if len(run) < width:
                continue
            for i in range(len(run) - width + 1):
                digest = _sha256(run[i : i + width])
                if digest in ACCOUNT_SHA256:
                    add("C", "account-cjk", m.start() + i, m.start() + i + width, digest[:8])
                    break

    # --- E：截图侧车里的玩家 ID 残留 ---------------------------------------
    for m in _OCR_ID_RE.finditer(line):
        digits = m.group(1)
        if set(digits) == {"0"}:
            continue  # ``ID:000000000`` 是占位符，不是残留
        add("E", "ocr-id", m.start(1), m.end(1))

    # --- F：身份残留（非秘密，不遮蔽） --------------------------------------
    for needle, reason in F_NEEDLES:
        start = line.find(needle)
        while start != -1:
            hits.append(("F", reason, start, start + len(needle), line, None))
            start = line.find(needle, start + 1)

    return hits


def _scan_text(path: str, text: str, explain: bool) -> list[str]:
    out: list[str] = []
    seen: set[tuple[str, int, str, str]] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        for cat, _rule, _start, _end, masked, digest in _scan_line(line):
            if _is_exempt(path, cat):
                continue
            excerpt = " ".join(masked.strip().split())[:160]
            key = (path, lineno, cat, excerpt)
            if key in seen:
                continue
            seen.add(key)
            suffix = f" [sha256:{digest}]" if explain and digest else ""
            out.append(f"{path}:{lineno}: [{cat}] {excerpt}{suffix}")
    return out


# ---------------------------------------------------------------------------
# 取文件
# ---------------------------------------------------------------------------
def _git(*args: str, input_bytes: bytes | None = None) -> bytes:
    import subprocess  # 局部导入：--print-hash 不需要 git

    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        input=input_bytes,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} 失败：{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def _apply_scope(paths: list[str], scan_all: bool) -> list[str]:
    """默认只留发布白名单；--all 才保留全仓。"""
    keep = paths if scan_all else wanted(paths)
    return sorted({p.replace("\\", "/") for p in keep if _should_scan(p)})


def _scan_worktree(scan_all: bool) -> tuple[list[str], int]:
    # tracked_files() 来自 publish_public：默认就是 `git ls-files -c -o --exclude-standard`
    # （已跟踪 + 未跟踪但没被 ignore），这样新加、还没 add 的文件也在闸门里。
    hits: list[str] = []
    scanned = 0
    for rel in _apply_scope(tracked_files(), scan_all):
        try:
            blob = (REPO_ROOT / rel).read_bytes()
        except OSError:
            continue
        text = _text_of(blob)
        if text is None:
            continue
        scanned += 1
        hits.extend(_scan_text(rel, text, explain=EXPLAIN))
    return hits, scanned


def _scan_rev(rev: str, scan_all: bool) -> tuple[list[str], int]:
    raw = _git("ls-tree", "-r", "-z", "--full-tree", rev)
    entries: list[tuple[str, str]] = []  # (path, blob sha)
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, _, path_b = item.partition(b"\t")
        parts = meta.split(b" ")
        if len(parts) < 3 or parts[1] != b"blob":
            continue
        rel = path_b.decode("utf-8", "surrogateescape").replace("\\", "/")
        if not _should_scan(rel):
            continue
        entries.append((rel, parts[2].decode("ascii")))

    scope = set(_apply_scope([rel for rel, _sha in entries], scan_all))
    entries = [(rel, sha) for rel, sha in entries if rel in scope]
    if not entries:
        return [], 0

    # 一次 cat-file --batch 读完整个 tree（避免每文件起一个 git 进程）。
    payload = ("\n".join(sha for _rel, sha in entries) + "\n").encode("ascii")
    data = _git("cat-file", "--batch", input_bytes=payload)

    hits: list[str] = []
    scanned = 0
    pos = 0
    for rel, _sha in entries:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        blob = data[pos : pos + size]
        pos += size + 1  # blob 内容后有一个换行
        text = _text_of(blob)
        if text is None:
            continue
        scanned += 1
        hits.extend(_scan_text(rel, text, explain=EXPLAIN))
    return hits, scanned


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
EXPLAIN = False


def main(argv: list[str] | None = None) -> int:
    global EXPLAIN
    parser = argparse.ArgumentParser(
        description="脱敏守卫：检查发布白名单里的 A/B/C/F 四类信息（详见模块 docstring）"
    )
    parser.add_argument("--rev", help="扫描该 revision 的 tree（例如 HEAD / 发布产物 commit）")
    parser.add_argument(
        "--all",
        action="store_true",
        help="扫全仓而不是只扫发布白名单（人工体检用；CI 闸门不加这个）",
    )
    parser.add_argument(
        "--print-hash",
        metavar="TEXT",
        help="打印 TEXT 的 SHA-256（维护黑名单常量用；不会扫描仓库）",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="命中行附上匹配词的 sha256 前 8 位，便于对照是哪条黑名单",
    )
    args = parser.parse_args(argv)

    EXPLAIN = args.explain

    if args.print_hash is not None:
        print(_sha256(args.print_hash))
        return 0

    if args.rev:
        hits, scanned = _scan_rev(args.rev, args.all)
        scope = f"rev {args.rev}" + (", 全仓" if args.all else ", 发布白名单")
    else:
        hits, scanned = _scan_worktree(args.all)
        scope = "working tree" + (", 全仓" if args.all else ", 发布白名单")

    if hits:
        for line in hits:
            print(line)
        print(f"PII FOUND ({len(hits)} hits in {scanned} files scanned, {scope})", file=sys.stderr)
        return 1

    print(f"PII CLEAN ({scanned} files scanned, {scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
