#!/usr/bin/env python3
# tools/shoot_ui.py
# 對 tools/extract_ui.py 抽出的頁面截圖(桌面 1280px + 手機 390px),供設計迭代自我審視與交付附圖。
#
# 環境注意:本容器的 Chromium 在 /opt/pw-browsers/chromium-1194,
# 與 pip 安裝的 playwright 預期版本不同,所以一律用 executable_path 明確指定,
# 絕不執行 `playwright install`。
#
# 用法:
#   python tools/extract_ui.py                        # 先產生 ui_snapshot/
#   python tools/shoot_ui.py --out shots/before
#   python tools/shoot_ui.py --out shots/after --pages index,report,stock_in

import argparse
import os
import sys

CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 預設截這幾頁:資料密度最高、表單最多、KPI 色塊最多的代表頁
DEFAULT_PAGES = ["index", "report", "stock_in", "history", "login", "counts"]

VIEWPORTS = [("desktop", 1280, 900), ("mobile", 390, 844)]


def main():
    parser = argparse.ArgumentParser(description="對抽取出的頁面截圖(桌面 + 手機)")
    parser.add_argument("--out", required=True, help="輸出目錄")
    parser.add_argument("--src", default=os.path.join(REPO_ROOT, "ui_snapshot"),
                        help="extract_ui.py 的輸出目錄")
    parser.add_argument("--pages", default=",".join(DEFAULT_PAGES),
                        help="要截的頁面 slug,逗號分隔")
    parser.add_argument("--full", action="store_true", help="整頁截圖(預設只截首屏)")
    args = parser.parse_args()

    src_dir = os.path.abspath(args.src)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    missing = [p for p in pages if not os.path.exists(os.path.join(src_dir, f"{p}.html"))]
    if missing:
        print(f"❌ 找不到頁面:{', '.join(missing)}(先跑 python tools/extract_ui.py)")
        return 1

    if not os.path.exists(CHROMIUM):
        print(f"❌ 找不到 Chromium:{CHROMIUM}")
        return 1

    from playwright.sync_api import sync_playwright

    shot_count = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        try:
            for label, width, height in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": width, "height": height},
                                          device_scale_factor=2, locale="zh-TW")
                page = ctx.new_page()
                for slug in pages:
                    page.goto(f"file://{src_dir}/{slug}.html", wait_until="load")
                    page.wait_for_timeout(200)
                    dest = os.path.join(out_dir, f"{slug}-{label}.png")
                    page.screenshot(path=dest, full_page=args.full)
                    print(f"  📸 {os.path.relpath(dest, os.getcwd())}  ({width}×{height})")
                    shot_count += 1
                ctx.close()
        finally:
            browser.close()

    print(f"\n共 {shot_count} 張,輸出於 {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
