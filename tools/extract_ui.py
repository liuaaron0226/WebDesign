#!/usr/bin/env python3
# tools/extract_ui.py
# 把 inventory_app 實際算繪出來的頁面抽成獨立 HTML,餵給 Impeccable 設計偵測器。
#
# 為什麼需要這支程式:
#   Impeccable 偵測器只認得 .html/.css/.jsx/.tsx/.vue/... 這些副檔名
#   (見 .claude/skills/impeccable/scripts/detector/node/file-system.mjs 的
#    SCANNABLE_EXTENSIONS),完全不認得 .py。
#   本專案的 UI 全部寫在 inventory_app.py 的 LAYOUT 字串裡(含約 320 行 inline CSS),
#   所以直接對 repo 掃描會得到「0 個檔案、0 個問題」——看起來全部通過,
#   實際上根本沒檢查。這支程式就是補上那一層。
#
# 用法:
#   python tools/extract_ui.py                  # 輸出到 ui_snapshot/
#   python tools/extract_ui.py --out <dir>
#
# 輸出的 HTML 是自包含的(inline <style>),可直接用瀏覽器等級的偵測:
#   npx impeccable@3.5.0 detect "file://$PWD/ui_snapshot/index.html" --viewport 1280x800

import argparse
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# 一律用臨時 DB 與臨時照片目錄,絕不碰正式資料(與 test_inventory.py 同慣例)
_TMP = tempfile.mkdtemp(prefix="ui_snapshot_")
os.environ["INVENTORY_DB"] = os.path.join(_TMP, "snapshot.db")
os.environ["INVENTORY_IMAGES"] = os.path.join(_TMP, "images")
os.environ["BACKUP_DIR"] = ""
os.environ.setdefault("SECRET_KEY", "ui-snapshot-only-key")

import inventory_app as app_module  # noqa: E402  (必須在設定環境變數之後 import)

ADMIN = {"username": "snapshot_admin", "password": "snapshot12345"}

# 要抽取的頁面。空資料的頁面看不出排版問題,所以下面 seed_data() 會先塞入
# 有意義的樣本(低庫存、快到期批次、預留、盤點單、多筆交易)。
PAGES = [
    ("login", "/login", "登入頁(未登入)"),
    ("index", "/", "首頁 / 庫存總覽"),
    ("alerts", "/alerts", "警示(低庫存 + 效期)"),
    ("product_new", "/products/new", "新增商品表單"),
    ("product_detail", "/products/1", "商品明細"),
    ("stock_in", "/stock/in", "入庫作業"),
    ("stock_out", "/stock/out", "出庫作業"),
    ("history", "/history", "異動歷史"),
    ("suppliers", "/suppliers", "供應商列表"),
    ("report", "/report", "分析報表"),
    ("planning", "/planning", "安全庫存規劃"),
    ("counts", "/counts", "循環盤點"),
    ("count_detail", "/counts/1", "盤點單明細"),
    ("reservations", "/reservations", "預留管理"),
    ("receipts", "/receipts", "收貨單 / ASN"),
    ("labels", "/labels", "QR 貨架標籤"),
    ("users", "/users", "帳號管理"),
    ("audit", "/audit", "稽核紀錄"),
    ("import", "/import", "CSV 匯入"),
    ("search_image", "/search/image", "以圖搜圖"),
]


def seed_data(client):
    """塞入足以暴露排版問題的樣本資料:長中文品名、多筆列、各種狀態徽章。"""
    client.post("/suppliers/new", data={
        "name": "得盛工業材料股份有限公司", "contact": "陳先生",
        "phone": "04-2345-6789", "note": "主要供應商,月結 60 天"})
    client.post("/suppliers/new", data={
        "name": "日盛電子", "contact": "林小姐", "phone": "02-2712-3456", "note": ""})

    products = [
        # (sku, 品名, 分類, 單位, 單價, 門檻, 櫃位, 進貨單位, 每單位數)
        ("BL-0001", "耐熱矽膠管 φ8×12mm 透明", "管材", "米", "125", "50", "防潮箱3層", "捲", "50"),
        ("BL-0002", "不鏽鋼六角螺絲 M6×20 SUS304", "五金", "個", "3.5", "500", "A區2排", "包", "100"),
        ("BL-0003", "環氧樹脂接著劑 AB膠 50ml", "耗材", "組", "280", "10", "桌上", "", "1"),
        ("BL-0004", "無塵擦拭布 9×9吋(300張/包)", "耗材", "包", "450", "20", "B區1排", "箱", "10"),
        ("BL-0005", "熱縮套管 φ3.0 黑色", "電材", "米", "8", "100", "防潮箱1層", "捲", "100"),
        ("TMP-00017", "壓克力板 3mm(未編料號)", "板材", "片", "0", "5", "無庫存", "", "1"),
    ]
    for sku, name, cat, unit, price, thr, loc, punit, upp in products:
        client.post("/products/new", data={
            "name": name, "sku": sku, "category": cat, "unit": unit,
            "unit_price": price, "low_stock_threshold": thr, "supplier_id": "1",
            "location": loc, "purchase_unit": punit, "units_per_purchase": upp,
            "lead_time_days": "14", "service_level": "95", "issue_strategy": "FIFO"})

    # 入庫:製造出各種批次狀態(有成本、有效期、快到期)
    stock_ins = [
        (1, "200", "L20260701-A", "120", "2026-09-05"),   # 快到期
        (1, "150", "L20260801-B", "128", "2027-01-31"),
        (2, "3000", "", "3.2", ""),
        (3, "40", "AB-2026Q3", "265", "2026-08-20"),      # 快到期
        (4, "60", "", "430", ""),
        (5, "800", "", "7.5", ""),
    ]
    for pid, qty, lot, cost, exp in stock_ins:
        client.post("/stock/in", data={
            "product_id": str(pid), "quantity": qty, "lot_no": lot,
            "unit_cost": cost, "expiry_date": exp, "note": "採購入庫"})

    # 出庫:製造用量歷史,讓報表 / 規劃頁有資料可算
    for pid, qty, purpose in [(1, "30", "工單 WO-2601"), (2, "800", "工單 WO-2602"),
                              (1, "45", "生產部"), (5, "120", "工單 WO-2603"),
                              (2, "1200", "生產部"), (4, "12", "品保部")]:
        client.post("/stock/out", data={
            "product_id": str(pid), "quantity": qty, "purpose": purpose})

    # 讓 BL-0003 掉到低庫存門檻以下,首頁警示橫幅才會出現
    client.post("/stock/out", data={"product_id": "3", "quantity": "35",
                                    "purpose": "工單 WO-2604"})
    # 預留(可用量 = 現有量 − 預留)
    client.post("/reservations/new", data={"product_id": "1", "quantity": "40",
                                           "purpose": "工單 WO-2610 預留"})
    # 盤點單
    client.post("/counts/new", data={"name": "2026 年 8 月循環盤點(全品項)", "scope": "all"})


def extract_css(html, out_dir):
    """把 LAYOUT 的 inline <style> 另存為 app.css,讓純 CSS 規則也能被掃到。"""
    match = re.search(r"<style>(.*?)</style>", html, re.S)
    if not match:
        return None
    css_path = os.path.join(out_dir, "app.css")
    with open(css_path, "w", encoding="utf-8") as fh:
        fh.write(match.group(1).strip() + "\n")
    return css_path


def main():
    parser = argparse.ArgumentParser(description="抽取 inventory_app 的算繪頁面供設計偵測器掃描")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "ui_snapshot"),
                        help="輸出目錄(預設 ui_snapshot/)")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    app_module.init_db()
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()

    client.post("/register", data=ADMIN)
    client.post("/login", data=ADMIN)
    seed_data(client)

    # 登入頁要用「另一個未登入的 client」抽,而且必須在管理員建立之後——
    # 系統還沒有任何帳號時 /login 會 302 轉去 /register,抽到的會是轉址頁不是登入頁。
    anon = app_module.app.test_client()
    login_html = anon.get("/login").get_data(as_text=True)

    written, skipped = [], []
    for slug, path, label in PAGES:
        if slug == "login":
            html, status = login_html, 200
        else:
            resp = client.get(path, follow_redirects=True)
            html, status = resp.get_data(as_text=True), resp.status_code
        if status != 200 or "<html" not in html:
            skipped.append((slug, path, status))
            continue
        with open(os.path.join(out_dir, f"{slug}.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        written.append((slug, path, label, len(html)))

    css_path = extract_css(written and open(
        os.path.join(out_dir, f"{written[0][0]}.html"), encoding="utf-8").read() or "", out_dir)

    print(f"輸出目錄:{out_dir}")
    for slug, path, label, size in written:
        print(f"  ✅ {slug + '.html':<24} {path:<20} {label}  ({size:,} bytes)")
    for slug, path, status in skipped:
        print(f"  ⚠️  {slug:<24} {path:<20} HTTP {status} — 略過")
    if css_path:
        print(f"  ✅ {'app.css':<24} 從 LAYOUT 的 <style> 抽出")
    print(f"\n共 {len(written)} 個頁面。掃描指令:")
    print(f"  npx impeccable@3.5.0 detect {os.path.relpath(out_dir, os.getcwd())}/")
    print(f"  npx impeccable@3.5.0 detect \"file://{out_dir}/index.html\" --viewport 1280x800")

    if not written:
        print("\n❌ 沒有抽到任何頁面 — 偵測器將無事可掃,請先修正上面的錯誤。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
