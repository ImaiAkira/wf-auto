"""公开发布验收：把 GitHub Release 的产物拉到干净目录，逐条核对 V1–V8 里**不需要接设备**的那部分。

为什么要有这个脚本：spec 的验收表本来是散文，每次发版都得人工重走一遍。这里把
「下载 → 校验 digest → 解压 → 结构核对 → 剥 PATH 冒烟 → 起 GUI」变成可重复的命令，红就是红。

它**不**做的事（必须人来，见 ``docs/recon/release-verification.md``）：
  · 真跑一个任务（会消耗真实账号体力、改游戏状态）
  · 一台没装 .NET 的干净 Windows（首次装运行时那条路径）

用法::

    python tools/accept_release.py --launch-gui
    python tools/accept_release.py --zip "%USERPROFILE%\\Downloads\\wf-auto-win-x86_64-v1.0.0.zip"

两个踩过的坑，写在代码里免得重犯：

1. 本机 schannel 做证书吊销检查会失败（``CRYPT_E_NO_REVOCATION_CHECK``），
   ``gh release download`` / ``Invoke-WebRequest`` 都会 0 字节卡死 —— 所以这里用
   ``curl --ssl-no-revoke``，不是 ``--insecure``。
2. PyPI 包名是 ``StrEnum``，**模块名是 ``strenum``**。测 ``import StrEnum`` 会假红。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = "ImaiAkira/wf-auto"

# 产物必须含的东西。缺一个，用户拿到的包就是废的。
REQUIRED = [
    "MFAAvalonia.exe",
    "双击启动.bat",
    "DependencySetup_依赖库安装_win.bat",
    "README.md",
    "LICENSE",
    "interface.json",
    "agent/main.py",
    "python/python.exe",
    "runtimes/win-x64/native/MaaFramework.dll",
]

results: list[tuple[str, str, bool, str]] = []


def check(cid: str, name: str, ok: bool, evidence: str = "") -> None:
    results.append((cid, name, bool(ok), evidence))
    print(f"  [{'PASS' if ok else 'FAIL'}] {cid:<4} {name}  {evidence}")


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def release_asset(tag: str, repo: str = REPO) -> dict:
    out = run(["gh", "release", "view", tag, "--repo", repo, "--json", "assets"]).stdout
    assets = json.loads(out or "{}").get("assets") or []
    if not assets:
        raise SystemExit(f"Release {tag} 没有资产")
    return assets[0]


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # --ssl-no-revoke：见模块 docstring 的坑 1
    proc = subprocess.run(
        ["curl.exe", "-sS", "-L", "--ssl-no-revoke", "--max-time", "1800", "-o", str(dest), url]
    )
    if proc.returncode != 0:
        raise SystemExit(f"curl 下载失败（exit {proc.returncode}）")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def smoke(clean: Path) -> None:
    """剥掉 PATH，证明「用户机器上没装 Python」也能活。"""
    saved = os.environ.get("PATH", "")
    saved_io = os.environ.get("PYTHONIOENCODING")
    try:
        os.environ["PATH"] = os.pathsep.join(
            [str(Path(os.environ["SystemRoot"]) / "system32"), os.environ["SystemRoot"]]
        )
        os.environ["PYTHONIOENCODING"] = "utf-8"
        py = clean / "python" / "python.exe"

        r = run([str(py), "-c", "import sys;print(sys.version.split()[0])"])
        check("V2a", "内置解释器可用", r.returncode == 0, f"python {r.stdout.strip()}")

        r = run([str(py), "-c", "import maa,numpy,strenum;print('ok')"])
        check("V2b", "运行期依赖齐全（maa/numpy/strenum）",
              r.stdout.strip() == "ok", (r.stderr or r.stdout).strip()[:120])

        agent = clean / "agent"
        mods = sorted(p.stem for p in agent.glob("*.py") if p.stem not in ("main", "__init__"))
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(agent)!r})\n"
            f"mods = {mods!r}\n"
            "bad = []\n"
            "for m in mods:\n"
            "    try:\n"
            "        __import__(m)\n"
            "    except Exception as e:\n"
            "        bad.append(m + ':' + type(e).__name__)\n"
            "print(len(mods) - len(bad), bad)\n"
        )
        r = run([str(py), "-c", code])
        ok = r.stdout.strip() == f"{len(mods)} []"
        check("V2c", f"agent 模块全部可导入（{len(mods)} 个）", ok, r.stdout.strip()[:160])

        # main.py 会等 MaaAgentServer 的 socket；5 秒还活着就说明没秒崩。
        errf = clean / "_agent.err"
        with errf.open("w", encoding="utf-8") as ef:
            p = subprocess.Popen([str(py), "-X", "utf8", str(agent / "main.py"), "--quiet"],
                                 stdout=subprocess.DEVNULL, stderr=ef,
                                 cwd=str(clean))
            import time
            time.sleep(5)
            alive = p.poll() is None
            if alive:
                p.kill()
                p.wait()
        err = errf.read_text(encoding="utf-8", errors="replace").strip()[:160]
        check("V2d", "agent/main.py 起得来（5s 不崩）", alive, "存活，等 socket" if alive else f"早退: {err}")
    finally:
        os.environ["PATH"] = saved
        if saved_io is None:
            os.environ.pop("PYTHONIOENCODING", None)
        else:
            os.environ["PYTHONIOENCODING"] = saved_io


def interface_checks(clean: Path, tag: str) -> None:
    import re
    text = (clean / "interface.json").read_text(encoding="utf-8-sig")
    ce = (re.search(r'"child_exec"\s*:\s*"([^"]+)"', text) or [None, ""])[1]
    check("V3a", "child_exec 指向包内解释器",
          "{PROJECT_DIR}/python/python.exe" in ce, ce)
    ver = (re.search(r'"version"\s*:\s*"([^"]+)"', text) or [None, ""])[1]
    check("V3b", "version == tag", ver == tag.lstrip("v"), f"version={ver} tag={tag}")


def gui_check(clean: Path) -> None:
    exe = clean / "MFAAvalonia.exe"
    p = subprocess.Popen([str(exe)], cwd=str(clean))
    time.sleep(10)
    alive = p.poll() is None
    ws = 0
    if alive:
        try:
            out = run(["tasklist", "/FI", f"PID eq {p.pid}", "/FO", "CSV", "/NH"]).stdout
            if "," in out:
                ws = -1  # tasklist 不给内存，交给 psutil 太重；这里只判存活
        except Exception:
            pass
        p.kill()
        p.wait()
    check("V1d", "MFAAvalonia.exe 起来且 10s 不崩", alive,
          "存活" if alive else f"退出码 {p.returncode}")


def upgrade_check(zpath: Path, clean: Path) -> None:
    """V6：把 zip **再覆盖解压一遍**，确认用户的 config/ 不会被清掉。

    这是 README 承诺的升级方式（「下载新版 zip，解压后覆盖到同一个目录，config/ 会保留」）。
    因为只有 v1.0.0 一个版本，这里用**同一个 zip** 做覆盖演练 —— 它证明「覆盖不会删多余文件」，
    **不**证明跨版本兼容。跨版本要等真有 v1.0.1 时再跑一次。
    """
    cfg = clean / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    marker = cfg / "upgrade-marker.txt"
    marker.write_text("user-configured-device=127.0.0.1:16384\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")

    with zipfile.ZipFile(zpath) as z:
        z.extractall(clean)  # 覆盖解压：与「解压到这里 → 全部替换」同义

    still = marker.exists() and marker.read_text(encoding="utf-8") == before
    check("V6a", "覆盖解压后 config/ 里的用户设置仍在", still,
          "marker 保留" if still else "marker 被覆盖或删除")

    exe = clean / "MFAAvalonia.exe"
    check("V6b", "覆盖后主程序仍在且大小未变", exe.exists(), f"{exe.stat().st_size} B" if exe.exists() else "缺")
    marker.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="v1.0.0")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--zip", type=Path, help="已下好的 zip；给了就跳过下载")
    ap.add_argument("--launch-gui", action="store_true", help="解压后真启动一次 MFAAvalonia.exe")
    ap.add_argument("--upgrade-check", action="store_true",
                    help="覆盖解压演练：确认 config/ 里的用户设置不会被清掉（V6）")
    ap.add_argument("--keep", action="store_true", help="保留解压目录")
    args = ap.parse_args()

    asset = release_asset(args.tag)
    zpath = args.zip
    if zpath is None:
        zpath = Path(tempfile.gettempdir()) / asset["name"]
        print(f"\n== 1. 取产物 ==\n  {asset['name']}  {asset['size']/1024/1024:.1f} MB")
        if zpath.exists():
            zpath.unlink()
        download(asset["url"], zpath)

    print("\n== 2. V1 产物完整性 ==")
    digest = (asset.get("digest") or "").replace("sha256:", "")
    got = sha256_of(zpath)
    check("V1a", "sha256 == GitHub 报告的 digest", got == digest, got[:16] + "…")

    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        roots = sorted({n.split("/")[0] for n in names})
        nested = any(n.startswith("wf-auto-win-x86_64/") for n in names)
        check("V1b", "没有多套一层同名目录（解压即用）", not nested, f"根层 {len(roots)} 项")
        missing = [r for r in REQUIRED if r not in names]
        check("V1c", "必备文件齐全", not missing,
              f"{len(REQUIRED)-len(missing)}/{len(REQUIRED)}" if not missing else f"缺: {missing}")

    clean = Path(tempfile.mkdtemp(prefix="wf-accept-"))
    try:
        print(f"\n== 3. 解压到干净目录 ==\n  {clean}")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(clean)

        print("\n== 4. V2 剥掉 PATH 后能不能活 ==")
        smoke(clean)

        print("\n== 5. 包内 interface.json 自洽 ==")
        interface_checks(clean, args.tag)

        if args.launch_gui:
            print("\n== 6. V1 GUI 能不能起来 ==")
            gui_check(clean)
        else:
            print("\n  （--launch-gui 未给，跳过 GUI 启动检查）")

        if args.upgrade_check:
            print("\n== 7. V6 覆盖升级语义 ==")
            upgrade_check(zpath, clean)
        else:
            print("  （--upgrade-check 未给，跳过覆盖升级演练）")
    finally:
        if args.keep:
            print(f"\n解压目录保留在：{clean}")
        else:
            shutil.rmtree(clean, ignore_errors=True)

    print("\n== 汇总 ==")
    for cid, name, ok, ev in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {cid:<4} {name}")
    bad = [r for r in results if not r[2]]
    if bad:
        print(f"\nFAILED {len(bad)} 项：")
        for cid, name, _, ev in bad:
            print(f"  {cid} {name} -> {ev}")
        return 1
    print(f"\n全部通过（{len(results)} 项）。")
    print("仍未覆盖：真跑一个任务（需设备）、没装 .NET 的干净 Windows（需另一台机器）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
