#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check that ``assets/interface.json``'s ``version`` matches the release tag.

Contract (issue #133 / ``docs/spec/public-release.md`` D6 / G4):

    interface.json["version"] == git tag, with a leading "v" stripped

Tag source:

* default: ``git describe --tags --abbrev=0`` (exactly the command from the
  ticket), run in the repository root;
* ``--tag <tag>``: use the given tag instead. CI may only know the tag as a
  string (``${{ needs.meta.outputs.tag }}``) or the tag may be absent from a
  shallow local clone.

Exit codes:

* ``0`` -- version and tag agree;
* ``1`` -- they disagree (both values are printed);
* ``2`` -- one side could not be determined (missing file, bad JSON, no tag,
  git not available, ...).

Only the standard library plus ``json-with-comments`` (already listed in
``tools/requirements.txt``, imported as ``jsonc``) are used.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import jsonc

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTERFACE = REPO_ROOT / "assets" / "interface.json"


def read_interface_version(interface_path: Path) -> str:
    """Return the ``version`` string from an interface.json (comments allowed)."""
    with interface_path.open("r", encoding="utf-8-sig") as f:
        interface = jsonc.load(f)

    version = interface.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(
            f"{interface_path} has no non-empty string 'version' field "
            f"(got {version!r})"
        )
    return version.strip()


def git_describe_tag() -> str:
    """Return ``git describe --tags --abbrev=0`` for the repository root."""
    try:
        proc = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # git is not installed
        raise RuntimeError("git executable not found on PATH") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(
            "`git describe --tags --abbrev=0` failed"
            + (f": {detail}" if detail else "")
            + " (no tags in this clone? pass --tag <tag>)"
        )
    tag = proc.stdout.strip()
    if not tag:
        raise RuntimeError("`git describe --tags --abbrev=0` returned an empty tag")
    return tag


def strip_leading_v(tag: str) -> str:
    """Normalise a tag to the value interface.json is expected to hold."""
    tag = tag.strip()
    return tag[1:] if tag.startswith("v") else tag


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that assets/interface.json version equals the git tag "
            "(leading 'v' stripped)."
        )
    )
    parser.add_argument(
        "--tag",
        metavar="TAG",
        help=(
            "tag to compare against instead of `git describe --tags --abbrev=0` "
            "(e.g. v1.0.0; the leading 'v' is stripped before comparing)"
        ),
    )
    parser.add_argument(
        "--interface",
        metavar="PATH",
        default=str(DEFAULT_INTERFACE),
        help=f"interface.json to read (default: {DEFAULT_INTERFACE})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interface_path = Path(args.interface)

    try:
        version = read_interface_version(interface_path)
    except (OSError, ValueError, jsonc.JSONDecodeError) as exc:
        print(f"ERROR: cannot read version from {interface_path}: {exc}")
        return 2

    try:
        tag = args.tag if args.tag is not None else git_describe_tag()
    except RuntimeError as exc:
        print(f"ERROR: cannot determine git tag: {exc}")
        return 2

    expected = strip_leading_v(tag)
    if version == expected:
        print(f"OK: interface.json version '{version}' == tag '{tag}'")
        return 0

    print(
        "MISMATCH: interface.json version "
        f"'{version}' != tag '{tag}' (tag without leading 'v': '{expected}')"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
