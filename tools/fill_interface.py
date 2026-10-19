#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the release version into ``assets/interface.json`` without losing its JSONC comments.

Why this exists (issue #133 / ``docs/spec/public-release.md`` D6)
-----------------------------------------------------------------
The release model is "CI owns the version": the value committed in
``assets/interface.json`` is only the last released version (or a placeholder),
and the packaging pipeline overwrites it with the tag it is building.  This is
the MaaEnd model (``tools/fill_interface.py --version <tag>``); unlike MaaEnd we
*also* keep ``tools/check_version.py`` as a local self-check.

``assets/interface.json`` is JSON with ``//`` comments, so a
``jsonc.load``/``jsonc.dump`` round-trip would delete every comment and reformat
the whole file.  This tool instead patches only the version string literal:

* comments, key order, indentation and CRLF line endings are untouched;
* a leading ``v`` is stripped, so ``v1.2.3`` is written as ``1.2.3``;
* idempotent: running it twice with the same value leaves the file
  byte-identical (the second run does not even write);
* the patched text is re-parsed with ``jsonc`` before it is written, so a bad
  patch can never corrupt the file.

Usage
-----
    python tools/fill_interface.py --version v1.2.3
    python tools/fill_interface.py --version v1.2.3 --interface install/interface.json

Exit codes: ``0`` success, ``2`` error (missing key, bad JSON, IO failure).
Only the standard library plus ``json-with-comments`` are used.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import jsonc
except ModuleNotFoundError as e:  # pragma: no cover - environment guard
    raise ImportError(
        "Missing dependency 'json-with-comments' (imported as 'jsonc').\n"
        f"Install it with:\n  {sys.executable} -m pip install json-with-comments\n"
        "Or add it to your project's requirements."
    ) from e

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTERFACE = REPO_ROOT / "assets" / "interface.json"

# A line that assigns a string to a "version" key, e.g. `    "version": "1.0.0",`
_VERSION_RE = re.compile(
    r'^([ \t]*"version"[ \t]*:[ \t]*")((?:[^"\\]|\\.)*)(")',
    re.MULTILINE,
)


def normalize_version(value: str) -> str:
    """``v1.2.3`` -> ``1.2.3``; trailing/leading whitespace is dropped."""
    value = value.strip()
    if value.startswith("v"):
        value = value[1:]
    if not value:
        raise ValueError("version must not be empty")
    return value


def set_version(interface_path: Path, version: str) -> tuple[bool, str, str]:
    """Set the top-level ``version`` in ``interface_path`` in place.

    Returns ``(changed, old_value, new_value)``.  When the value already equals
    ``version`` nothing is written and ``changed`` is ``False``.
    """
    interface_path = Path(interface_path)
    new_value = normalize_version(version)

    raw_bytes = interface_path.read_bytes()
    bom = b"\xef\xbb\xbf"
    has_bom = raw_bytes.startswith(bom)
    # Decode the bytes directly (no text-mode newline translation) so CRLF
    # line endings survive untouched.
    raw = raw_bytes[len(bom) :].decode("utf-8") if has_bom else raw_bytes.decode("utf-8")
    matches = list(_VERSION_RE.finditer(raw))
    if not matches:
        raise ValueError(f'{interface_path}: no "version": "..." line found')
    if len(matches) > 1:
        raise ValueError(
            f'{interface_path}: found {len(matches)} "version" lines; '
            "refusing to guess which one is the project version"
        )

    match = matches[0]
    old_value = match.group(2)
    if old_value == new_value:
        return False, old_value, new_value

    escaped = new_value.replace("\\", "\\\\").replace('"', '\\"')
    patched = raw[: match.start(2)] + escaped + raw[match.end(2) :]

    # Never write a file we cannot parse back, and never write the wrong value.
    parsed = jsonc.loads(patched)
    if parsed.get("version") != new_value:
        raise ValueError(
            f"{interface_path}: patched JSON parses with version "
            f"{parsed.get('version')!r}, expected {new_value!r}; refusing to write"
        )

    interface_path.write_bytes((bom if has_bom else b"") + patched.encode("utf-8"))
    return True, old_value, new_value


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Write the release tag into an interface.json version field "
            "without losing JSONC comments (leading 'v' is stripped)."
        )
    )
    parser.add_argument(
        "--version",
        metavar="TAG",
        required=True,
        help="release tag, e.g. v1.2.3 (the leading 'v' is stripped before writing)",
    )
    parser.add_argument(
        "--interface",
        metavar="PATH",
        default=str(DEFAULT_INTERFACE),
        help=f"interface.json to patch (default: {DEFAULT_INTERFACE})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interface_path = Path(args.interface)
    try:
        changed, old_value, new_value = set_version(interface_path, args.version)
    except (OSError, ValueError, jsonc.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2

    if changed:
        print(f"OK: {interface_path}: version '{old_value}' -> '{new_value}'")
    else:
        print(f"OK: {interface_path}: version already '{new_value}' (unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
