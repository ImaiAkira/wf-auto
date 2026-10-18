#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""#105 真机验证：走到 A 类战前编队页 → 就地切 SET → 断言 SET/战力真的变了 → 切回。

为什么要有这个脚本：2026-10-18 夜我**手动**导航到战前编队页错了两次（把主线的「第12章 1-1」
当成战斗关，进了剧情对话；又在主城误点）。一次性手工操作必须脚本化，而且**每一步都要有识别证据**：
点完必须确认到达预期页，否则立刻停，绝不在未知页面上继续点。

用法：
    python tools\\verify_team_battle.py --address 127.0.0.1:16384 --where
    python tools\\verify_team_battle.py --address 127.0.0.1:16384 --dry-run
    python tools\\verify_team_battle.py --address 127.0.0.1:16384 --target-set 2

退出码 0 = 通过；1 = 某步没过（打印卡在哪一步 + 存失败帧）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

WORK = Path("debug")
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS.parent / "agent"))


def now() -> str:
    return time.strftime("%H:%M:%S")


class Page:
    """带识别证据的导航原语（每一步都先看再点、点完再看）。"""

    def __init__(self, address: str, *, steal: bool = False):
        import live_harness as lh  # noqa: PLC0415

        self.lh = lh
        self.address = address
        # ★唯一登记入口（#25）★：connect_device 内部会拿租约 + 同步 ADDRESS + 设 ctrl，
        #   不要自己再写「三件套」（历史上漏 ADDRESS 出过事）。
        self.ctrl = lh.connect_device(lh.ADB, address, steal=steal)
        # OCR 的 resource bundle = assets/resource（与 run_wuchong_live 的 ASSETS 一致）
        self.assets = Path(__file__).resolve().parent.parent / "assets" / "resource"

    # ---- 基础 ----
    def items(self):
        img = self.lh.grab()
        return img, self.lh.ocr(img, self.assets)

    def tap(self, x720: float, y720: float):
        self.lh.adb_tap(x720, y720)
        time.sleep(0.7)

    def find(self, pattern: str, roi=None):
        _img, items = self.items()
        import re  # noqa: PLC0415

        rx = re.compile(pattern)
        for text, box in items:
            if rx.search((text or "").strip()):
                if roi:
                    x0, y0, x1, y1 = roi
                    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
                    if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                        continue
                return (box[0] + box[2] / 2, box[1] + box[3] / 2), (text, box)
        return None

    def wait_idle(self, timeout: float = 12.0) -> None:
        """等列表加载完（真机见过「搜索中……」）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            hit = self.find(r"搜索中")
            if hit is None:
                return
            time.sleep(1.0)

    def team_read(self):
        import team_impl  # noqa: PLC0415

        img, items = self.items()
        hits = None
        try:
            hits = team_impl.detect_team_templates(img)
        except Exception:  # noqa: BLE001
            hits = None
        state = team_impl.read_team(items, hits=hits)
        return state, items

    # ---- 步骤 ----
    def goto_team_page(self) -> bool:
        """主城 → 领主战 → 首个「…讨伐」行 → 详情【战斗】 → A 类战前编队页。"""
        import team_impl  # noqa: PLC0415

        _img, items = self.items()
        if team_impl.is_battle_team_page(items):
            print(f"[{now()}] 已经在 A 类战前编队页", flush=True)
            return True

        # 1) 主城：右下【领主战】
        hit = self.find(r"^领主战$")
        if hit is None:
            print(f"[{now()}] ❌ 当前不在主城（找不到【领主战】）；先让它回主城", flush=True)
            return False
        print(f"[{now()}] ▶ 点【领主战】@720({hit[0][0]:.0f},{hit[0][1]:.0f})", flush=True)
        self.tap(*hit[0])
        time.sleep(3)
        self.wait_idle()

        # 2) 列表：找第一个「…讨伐」
        # ★真机教训（两次误点）★ 行不能用「讨伐$」找 —— 页签「降临讨伐」也以它结尾。
        #   改用 `通关数` 作锚：它**只出现在列表行**（页签/标题/按钮都没有），
        #   拿它的 y 当行高、点行左侧 x=180（整行可点）。
        anchor = self.find(r"^通关数")
        hit = ((180.0, anchor[0][1]), ("<row>", anchor[1][1])) if anchor else None
        if hit is None:
            print(f"[{now()}] ❌ 列表里没有「…讨伐」行（可能需要切页签/滚动）", flush=True)
            return False
        print(f"[{now()}] ▶ 点领主行 {hit[1][0]!r}", flush=True)
        self.tap(*hit[0])
        time.sleep(3)

        # 3) 详情页【战斗】
        # ★真机教训★ 详情页顶部有「- 战斗 -」标题横幅（y≈130），按钮在下面（y>900）
        hit = self.find(r"^战斗$", roi=(0, 900, 720, 1280))
        if hit is None:
            print(f"[{now()}] ❌ 详情页没有【战斗】", flush=True)
            return False
        print(f"[{now()}] ▶ 点【战斗】", flush=True)
        self.tap(*hit[0])
        time.sleep(3)

        # 4) 确认到了 A 类页
        _img, items = self.items()
        ok = team_impl.is_battle_team_page(items)
        state = team_impl.read_team(items)
        print(f"[{now()}] 到达判定 is_battle_team_page={ok} 读数={state}", flush=True)
        return ok

    @staticmethod
    def _unpack(state):
        """★#105★ `read_team` 返回 `(set, party, power)`（set 可能是 `(no, box)`）。

        旧 `switch_set` 按 dict 取键 ⇒ 真机切队直接 AttributeError。这里统一解包，
        同时兼容旧的 dict 形状（历史上有一版返回 dict）。
        """
        if isinstance(state, dict):
            cur, party, power = state.get("set"), state.get("party"), state.get("power")
        elif isinstance(state, (tuple, list)) and len(state) == 3:
            cur, party, power = state
        else:
            cur, party, power = state, None, None
        no = cur[0] if isinstance(cur, (tuple, list)) and cur else cur
        return no, party, power

    def switch_set(self, target: int) -> bool:
        import team_impl  # noqa: PLC0415

        state, items = self.team_read()
        cur_no, party0, power0 = self._unpack(state)
        print(f"[{now()}] 切前：SET={cur_no} Party={party0} 战力={power0}", flush=True)
        # ★#105 真机★ 优先用 OCR 读到的 `SET N` 框直接点（固定步长在两个页面上都不准）。
        tabs = team_impl.find_set_tabs(items)
        if target in tabs:
            tap_x, y = tabs[target]
            print(f"[{now()}] ▶ 按 OCR 框点 SET{target} @({tap_x:.0f},{y:.0f})（实测步长不可靠）", flush=True)
            self.tap(tap_x, y)
            for _ in range(3):
                time.sleep(1.0)
                state2, _i2 = self.team_read()
                cur2_no, _p2, pw2 = self._unpack(state2)
                if cur2_no == target:
                    print(f"[{now()}] ✅ SET 已到 {target}，战力={pw2}", flush=True)
                    return True
            state3, _ = self.team_read()
            print(f"[{now()}] ❌ 按 OCR 框点也没切过去，仍在 {state3}", flush=True)
            return False

        plan = team_impl.battle_set_tap_plan(cur_no or 1, target)
        if plan is None:
            print(f"[{now()}] 已经就在 SET{target}（或目标越界）", flush=True)
            return True
        tap_x, direction = plan
        y = team_impl.TEAM_BATTLE_SET_ROW_Y
        print(f"[{now()}] ▶ A 类 SET 条点 ({tap_x},{y}) 方向={direction}", flush=True)
        self.tap(tap_x, y)
        # 等待并确认（最多 3 次轮询）
        for _ in range(3):
            time.sleep(1.0)
            state2, _items2 = self.team_read()
            cur2_no, _p2, pw2 = self._unpack(state2)
            if cur2_no == target:
                print(f"[{now()}] ✅ SET 已到 {target}，战力={pw2}", flush=True)
                return True
        state3, _ = self.team_read()
        print(f"[{now()}] ❌ 切 SET 未生效，仍在 {state3}", flush=True)
        return False

    def close(self):
        try:
            self.lh.release_device_lease()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", required=True)
    ap.add_argument("--target-set", type=int, default=2)
    ap.add_argument("--back-to", type=int, default=0, help="切完再切回（0 = 不切）")
    ap.add_argument("--where", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--steal", action="store_true")
    a = ap.parse_args()

    page = Page(a.address, steal=a.steal)
    try:
        if a.where:
            import team_impl  # noqa: PLC0415

            img, items = page.items()
            # ★#105★ 把模板命中一起传进去：只走 OCR 通道会看不到模板兜底的效果
            #   （真页上 OCR 本就能读，所以不传不误导，但少一半排查信息）。
            hits = None
            try:
                hits = team_impl.detect_team_templates(img)
            except Exception as exc:  # noqa: BLE001
                print(f"（模板通道不可用：{exc}）", flush=True)
            print("is_battle_team_page =", team_impl.is_battle_team_page(items), flush=True)
            print("模板命中 =", sorted(getattr(hits, "hit_keys", ()) or ()), flush=True)
            print("read_team =", team_impl.read_team(items, hits=hits), flush=True)
            return 0

        if not page.goto_team_page():
            return 1
        if a.dry_run:
            print(f"[{now()}] --dry-run：导航成功，不切队", flush=True)
            return 0

        before, _ = page.team_read()
        if not page.switch_set(a.target_set):
            return 1
        after, _ = page.team_read()
        b_set = ((before or {}).get("set") or [None])[0] if isinstance((before or {}).get("set"), tuple) else (before or {}).get("set")
        a_set = ((after or {}).get("set") or [None])[0] if isinstance((after or {}).get("set"), tuple) else (after or {}).get("set")
        if b_set == a_set and (before or {}).get("power") == (after or {}).get("power"):
            print(f"[{now()}] ❌ SET 与战力都没变 —— 切队没生效", flush=True)
            return 1
        print(f"[{now()}] ✅ 切队生效：SET {b_set}→{a_set}，战力 "
              f"{(before or {}).get('power')}→{(after or {}).get('power')}", flush=True)

        if a.back_to:
            page.switch_set(a.back_to)
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
