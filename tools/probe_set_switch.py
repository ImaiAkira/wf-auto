# -*- coding: utf-8 -*-
"""⑦ 的剩余候选：在 A 类战前编队页上，**逐候选**试「切 SET」，每次只改一个变量。

已排除（真机A，10:0x）：
- 点 SET 页签中心（先按步长、再按 OCR 实测框）→ 无效
- 点 SET 标签下方 40px → 无效
- `SET编辑` → 那是「狂热激战用SET编辑」页，不是切战斗 SET 的入口（且 `read_team` 会误读 `● SETn`）

本轮候选（都没试过）：
  C  在 SET 条上**左右滑动**
  D  先关「自动续战」再点 SET 页签
  E  点 `推荐编成`
  F  点 SET 标签**左上/右上** 20px（热区可能是整块 tab 区域而不是文字）
  G  点页签**数字/圆点**（标签左侧那个小圆点）

每次：先读 `read_team`（含 SET），再动手，再读；变了就停并保存截图。
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "tools")
sys.path.insert(0, ".")

from verify_team_battle import Page  # noqa: E402


def read(page):
    state, items = page.team_read()
    no, party, power = Page._unpack(state)
    return no, party, power, items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default="127.0.0.1:16384")
    ap.add_argument("--target", type=int, default=2)
    a = ap.parse_args()

    page = Page(a.address)
    try:
        from PIL import Image  # noqa: PLC0415
        import team_impl  # noqa: PLC0415

        # 先在 A 类页上（goto/continue 由调用方保证）
        img, items = page.items()
        if not team_impl.is_battle_team_page(items):
            print("❌ 不在 A 类战前编队页，先跑 debug/continue_to_team.py", flush=True)
            return 2
        tabs = team_impl.find_set_tabs(items)
        cur = team_impl.read_team(items)
        print(f"起点：SET 页签 {tabs} / read_team={cur}", flush=True)
        if a.target not in tabs:
            print("抽不到目标 SET 的框", flush=True)
            return 3
        tx, ty = tabs[a.target]

        def attempt(name, fn):
            no0, _p0, _pw0, _ = read(page)
            fn()
            time.sleep(1.8)
            no1, p1, pw1, _ = read(page)
            moved = no1 == a.target
            img2, _ = page.items()
            Image.fromarray(img2).save(f"debug/set_probe_{name}.png")
            print(f"候选 {name}: SET {no0} -> {no1} / Party={p1} 战力={pw1} => "
                  f"{'✅ 切过去了' if moved else '❌ 没变'}", flush=True)
            return moved

        def swipe_bar():
            import subprocess  # noqa: PLC0415
            import live_harness as lh  # noqa: PLC0415
            adb = lh.ADB
            serial = lh.ADDRESS
            subprocess.run([adb, "-s", serial, "shell", "input", "swipe",
                            str(int(tx * 1.5)), str(int(ty * 1.5)),
                            str(int((tx - 260) * 1.5)), str(int(ty * 1.5)), "450"], check=False)

        if attempt("C_swipe_bar", swipe_bar):
            return 0

        def auto_off_then_tap():
            h = page.find(r"自动续战")
            if h:
                page.tap(h[0][0] - 70, h[0][1])   # 开关在文字左侧
                time.sleep(1.2)
            page.tap(tx, ty)

        if attempt("D_auto_off_then_tap", auto_off_then_tap):
            return 0

        h = page.find(r"推荐编成")
        if h:
            if attempt("E_recommend", lambda: page.tap(*h[0])):
                return 0

        if attempt("F_label_up20", lambda: page.tap(tx, ty - 20)):
            return 0
        if attempt("G_label_left15", lambda: page.tap(tx - 15, ty)):
            return 0

        print("\n❌ 五个候选全灭；截图见 debug/set_probe_*.png", flush=True)
        return 1
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
