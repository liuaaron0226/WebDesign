#!/usr/bin/env python3
# tools/design_check.py
# 設計檢查一鍵流程:抽取畫面 → 跑 Impeccable 偵測器 → 印出分類統計。
# 凡是動到介面的修改,合併前都要跑這支。
#
# 用法:
#   python tools/design_check.py                 # 抽取 + 偵測
#   python tools/design_check.py --shots         # 順便截圖到 shots/current/
#   python tools/design_check.py --json out.json # 另存完整結果
#
# 為什麼不用上游的 PostToolUse / Stop hook:
#   1. hook 只檢查「剛剛被編輯的那個檔案」。本專案的 UI 在 inventory_app.py 裡,
#      偵測器不認得 .py,所以 hook 對本 repo 的實際編輯永遠是靜默 no-op。
#   2. vendored 的 hook 缺少 htmlparser2 / css-select / css-tree / domutils 這幾個
#      npm 相依,會退化成 regex 比對。它自己會警告「findings are an undercount,
#      not a clean bill of health」,但結論那行印的是「No issues found」——
#      也就是會產生「假通過」。本專案寧可用一支要手動跑、但結果正確的指令。
#   這支腳本走 `npx impeccable@<PINNED>`,套件自帶相依,是完整而非退化的掃描。

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(REPO_ROOT, "ui_snapshot")
# 與 .claude/skills/impeccable/VENDORED.md 釘住的 commit 同一版,避免上游改版後結果漂移
PINNED = "impeccable@3.5.0"

# 本專案已審視並決定保留的規則。每一條都必須寫得出理由,不可以只是為了讓數字歸零。
# 這裡的說明會直接印在報告上,讓看報告的人知道「不是沒檢查,是檢查過後決定這樣」。
ACCEPTED = {
    "flat-type-hierarchy":
        "字級已從 13 種收斂為 6 種(12/13/15/18/23/28,無半像素)。規則要求每階間距 ≥1.25,"
        "但那是行銷頁的尺度;密集資料表需要「內文 15 / 次要 13」這種近階,"
        "GitHub、Linear、Jira 皆同。硬拉開會讓表格列高暴增,違反使用者「列高不可被撐爆」的要求。",
}


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, **kw)


def app_css():
    """回傳 inventory_app.py 的 <style> 內容,並剝掉 CSS 註解。

    剝註解是必要的:本專案的 CSS 註解會把「不要這樣寫」的反例原文寫出來
    (例如「不要對所有 td 下 overflow-wrap: anywhere」),
    naive 的 grep 會把註解裡的反例當成真的宣告,產生假失敗。
    """
    lines = open(os.path.join(REPO_ROOT, "inventory_app.py"), encoding="utf-8").read().split("\n")
    a = next(i for i, l in enumerate(lines) if "<style>" in l)
    b = next(i for i, l in enumerate(lines) if "</style>" in l)
    return re.sub(r"/\*.*?\*/", "", "\n".join(lines[a:b + 1]), flags=re.S)


def source_checks():
    """對 CSS 原始碼做結構檢查(偵測器看不出來、但 DESIGN.md 有規定的項目)。"""
    css = app_css()
    checks = [
        ("字級一律走代幣,CSS 內不寫死 px",
         not re.search(r"font-size:\s*[0-9.]+px", css),
         "寫死字級 %d 處" % len(re.findall(r"font-size:\s*[0-9.]+px", css))),
        ("無半套深色模式(核心色票沒有深色版就不要開 media query)",
         "@media (prefers-color-scheme" not in css,
         "prefers-color-scheme media query 未出現"),
        ("未對全域 td 下 overflow-wrap: anywhere(會把 1000 拆成 100/0)",
         "overflow-wrap: anywhere" not in css,
         "全域 anywhere 未出現"),
        ("短欄不換行:分類欄有 nowrap",
         'td[data-label="分類"]' in css and "nowrap" in css,
         "分類欄 nowrap 已設"),
        ("不載外部字體 / CDN(內網不保證有外網)",
         not re.search(r"fonts\.googleapis|@import\s+url|cdn\.", css),
         "無外部字體來源"),
    ]
    return checks


def main():
    parser = argparse.ArgumentParser(description="抽取畫面並執行 Impeccable 設計偵測")
    parser.add_argument("--shots", action="store_true", help="順便截圖到 shots/current/")
    parser.add_argument("--json", dest="json_out", help="另存完整 JSON 結果")
    args = parser.parse_args()

    if shutil.which("npx") is None:
        print("❌ 找不到 npx(需要 Node.js 22+)。設計偵測無法執行。")
        return 2

    print("① 抽取畫面 …")
    r = run([sys.executable, os.path.join("tools", "extract_ui.py")])
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        print("❌ 抽取失敗,偵測器將無事可掃。")
        return 1
    pages = sum(1 for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".html"))
    print(f"   {pages} 個頁面")

    print(f"② 執行 {PINNED} detect …")
    r = run(["npx", "--yes", PINNED, "detect", "ui_snapshot/", "--json"])
    try:
        findings = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(r.stdout[-2000:] + r.stderr[-2000:])
        print("❌ 偵測器沒有回傳有效 JSON。")
        return 1

    if "DEGRADED" in r.stderr:
        print("   ⚠️  偵測器回報 DEGRADED — 結果是低估值,不可當作通過。")

    scanned = {f["file"] for f in findings}
    counts = collections.Counter(f["antipattern"] for f in findings)

    # 這是最重要的一行:掃到 0 個檔案代表根本沒檢查,不是「全部通過」
    print(f"\n掃描 {pages} 個頁面,命中 {len(scanned)} 個檔案,共 {len(findings)} 筆")
    if pages and not findings:
        print("   (0 筆——請確認 ui_snapshot/ 內確實有內容,不要把「沒掃到」當成「沒問題」)")

    open_items = {r_: n for r_, n in counts.items() if r_ not in ACCEPTED}
    print("\n── 待處理 ──")
    if open_items:
        for rule, n in sorted(open_items.items(), key=lambda kv: -kv[1]):
            example = next(f for f in findings if f["antipattern"] == rule)
            print(f"  {n:>4}×  {rule}")
            print(f"        {example['description'][:100]}")
    else:
        print("  無")

    print("\n── 已審視並決定保留 ──")
    for rule, why in ACCEPTED.items():
        print(f"  {counts.get(rule, 0):>4}×  {rule}")
        for line in [why[i:i + 76] for i in range(0, len(why), 76)]:
            print(f"        {line}")

    print("\n── 原始碼結構檢查 ──")
    src_fail = 0
    for name, ok, evidence in source_checks():
        print(f"  {'✅' if ok else '❌'} {name}")
        print(f"       {evidence}")
        src_fail += 0 if ok else 1

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(findings, fh, ensure_ascii=False, indent=2)
        print(f"\n完整結果:{args.json_out}")

    if args.shots:
        print("\n③ 截圖 …")
        r = run([sys.executable, os.path.join("tools", "shoot_ui.py"),
                 "--out", os.path.join("shots", "current")])
        print(r.stdout.strip() or r.stderr.strip())

    return 1 if (open_items or src_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
