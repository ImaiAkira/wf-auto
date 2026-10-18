from pathlib import Path

import os
import shutil
import sys

import fill_interface
from configure import configure_ocr_model


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"

# the first parameter is self name
if sys.argv.__len__() < 4:
    print("Usage: python install.py <version> <os> <arch>")
    print("Example: python install.py v1.0.0 win x86_64")
    sys.exit(1)

os_name = sys.argv[2]
arch = sys.argv[3]


def get_dotnet_platform_tag():
    """自动检测当前平台并返回对应的dotnet平台标签"""
    if os_name == "win" and arch == "x86_64":
        platform_tag = "win-x64"
    elif os_name == "win" and arch == "aarch64":
        platform_tag = "win-arm64"
    elif os_name == "macos" and arch == "x86_64":
        platform_tag = "osx-x64"
    elif os_name == "macos" and arch == "aarch64":
        platform_tag = "osx-arm64"
    elif os_name == "linux" and arch == "x86_64":
        platform_tag = "linux-x64"
    elif os_name == "linux" and arch == "aarch64":
        platform_tag = "linux-arm64"
    else:
        print("Unsupported OS or architecture.")
        print("available parameters:")
        print("version: e.g., v1.0.0")
        print("os: [win, macos, linux, android]")
        print("arch: [aarch64, x86_64]")
        sys.exit(1)

    return platform_tag


def install_deps():
    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

    if os_name == "android":
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path,
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
    else:
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path / "runtimes" / get_dotnet_platform_tag() / "native",
            ignore=shutil.ignore_patterns(
                "*MaaDbgControlUnit*",
                "*MaaThriftControlUnit*",
                "*MaaRpc*",
                "*MaaHttp*",
                "plugins",
                "*.node",
                "*MaaPiCli*",
                # Runtime droppings created when the deps/ binaries were run
                # locally (MaaFramework creates these next to the DLLs); they
                # must not leak into the release package.
                "config",
                "debug",
            ),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "libs" / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "bin" / "plugins",
            install_path / "plugins" / get_dotnet_platform_tag(),
            dirs_exist_ok=True,
        )



def install_resource():

    configure_ocr_model()

    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    shutil.copy2(
        working_dir / "assets" / "interface.json",
        install_path,
    )

    # Write the version with a comment-preserving text patch instead of a
    # jsonc load/dump round-trip: interface.json carries // comments that a
    # round-trip would delete. fill_interface also strips a leading "v".
    changed, old_value, new_value = fill_interface.set_version(
        install_path / "interface.json", version
    )
    if changed:
        print(f"interface.json version: {old_value} -> {new_value}")
    else:
        print(f"interface.json version: {new_value} (unchanged)")


def install_chores():
    shutil.copy2(
        working_dir / "README.md",
        install_path,
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
    )
    # 零思考入口：用户双击的就是它。缺了这一步，发布包里没有启动器，
    # 「解压 → 双击」这条主路径就断了。用 glob 兜一层，避免文件被改名后静默丢失。
    launchers = sorted(working_dir.glob("双击启动.bat"))
    if not launchers:
        raise FileNotFoundError(
            "找不到启动器 双击启动.bat —— 发布包必须带它，否则用户没有可双击的入口"
        )
    for launcher in launchers:
        shutil.copy2(launcher, install_path)


def install_agent():
    shutil.copytree(
        working_dir / "agent",
        install_path / "agent",
        # Local runs leave __pycache__ and MaaFramework logs behind; never ship them.
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "debug"),
        dirs_exist_ok=True,
    )


def install_python():
    """Keep/stage the portable Python that the agent runs on.

    ``assets/interface.json`` sets ``agent.child_exec`` to
    ``{PROJECT_DIR}/python/python.exe``.  That interpreter is a build input,
    not source: roughly 170 MB, gitignored, and it must not be the developer
    ``.venv`` (a venv bakes absolute paths into ``Scripts/*.exe``; see the
    comment next to ``agent`` in interface.json).

    Order:
      1. ``install/python/python.exe`` already staged -> keep it untouched;
      2. ``$WF_PORTABLE_PYTHON`` or ``<repo>/python`` -> copy into
         ``install/python``;
      3. otherwise fail on Windows: a package without it ships an agent that
         cannot start.  Other platforms only warn (the release target is
         Windows, see docs/spec/public-release.md D5).

    CI must provide the interpreter around install.py; until it does, the
    packaging pipeline has no source for it (see docs/recon/install-manifest.md).
    """
    target = install_path / "python"
    if (target / "python.exe").exists():
        print(f"Portable Python: kept {target}")
        return

    source = None
    env_source = os.environ.get("WF_PORTABLE_PYTHON")
    if env_source:
        source = Path(env_source)
    elif (working_dir / "python").is_dir():
        source = working_dir / "python"

    if source is not None and (source / "python.exe").is_file():
        if source.resolve() != target.resolve():
            shutil.copytree(source, target, dirs_exist_ok=True)
            print(f"Portable Python: copied {source} -> {target}")
        else:
            print(f"Portable Python: kept {target}")
        return

    message = (
        "portable Python missing: install/python/python.exe not found.\n"
        "  assets/interface.json sets agent.child_exec to "
        "{PROJECT_DIR}/python/python.exe, so the agent cannot start.\n"
        "  Stage a portable CPython (maafw + numpy + StrEnum) into "
        "install/python or point WF_PORTABLE_PYTHON at it."
    )
    if os_name == "win":
        print(f"ERROR: {message}")
        sys.exit(1)
    print(f"WARNING: {message}")


def install_config():
    """Ship an empty user-config directory (MFAAvalonia writes config.json there)."""
    config_path = install_path / "config"
    config_path.mkdir(parents=True, exist_ok=True)
    (config_path / ".gitkeep").touch(exist_ok=True)


if __name__ == "__main__":
    install_deps()
    install_python()
    install_resource()
    install_chores()
    install_agent()
    install_config()

    print(f"Install to {install_path} successfully.")
