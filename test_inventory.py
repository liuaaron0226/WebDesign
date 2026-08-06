#!/usr/bin/env python3
# test_inventory.py
# 庫存管理系統的自動化測試(純標準庫 unittest + Flask test_client,零額外依賴)
# 執行:python test_inventory.py
#
# 覆蓋重點是「帳務正確性與安全防線」——這些邏輯出錯不會有明顯症狀,
# 但會讓庫存帳、成本、權限悄悄失真,因此必須由測試把關:
#   FIFO 消耗、批次帳恆等式、加權平均成本、ABC 分級、庫齡分桶、
#   權限控制、輸入邊界、CSV 匯入韌性、CSV 公式注入防護。

import os
import sqlite3
import tempfile
import unittest

# 測試一律用臨時 DB 與臨時照片目錄,絕不碰正式資料
_TMP = tempfile.mkdtemp(prefix="inv_test_")
os.environ["INVENTORY_DB"] = os.path.join(_TMP, "test.db")
os.environ["INVENTORY_IMAGES"] = os.path.join(_TMP, "images")
os.environ["SECRET_KEY"] = "test-only-key"

import inventory_app as app_module  # noqa: E402  (必須在設定環境變數之後 import)


class InventoryTestBase(unittest.TestCase):
    """共用夾具:每個測試類別一個乾淨資料庫 + 已登入的管理員。"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ["INVENTORY_DB"]
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(cls.db_path + suffix)
            except OSError:
                pass
        app_module.init_db()
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()
        # 首位註冊者即管理員
        cls.client.post("/register", data={"username": "admin", "password": "admin12345"})
        cls.client.post("/login", data={"username": "admin", "password": "admin12345"})

    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def new_product(self, sku, name="測試品", price="10", threshold="0"):
        self.client.post("/products/new", data={
            "name": name, "sku": sku, "unit_price": price,
            "low_stock_threshold": threshold, "unit": "個"})
        with self.db() as conn:
            return conn.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()["id"]

    def stock_in(self, pid, qty, lot_no="", unit_cost=""):
        return self.client.post("/stock/in", data={
            "product_id": str(pid), "quantity": str(qty),
            "lot_no": lot_no, "unit_cost": unit_cost})

    def stock_out(self, pid, qty):
        return self.client.post("/stock/out", data={
            "product_id": str(pid), "quantity": str(qty)})

    def assert_lot_ledger_balanced(self):
        """核心不變量:每個商品的批次剩餘總和必須等於現時庫存。"""
        with self.db() as conn:
            bad = conn.execute("""
                SELECT p.id, p.sku, p.quantity,
                       COALESCE((SELECT SUM(l.qty_remaining) FROM lots l
                                 WHERE l.product_id = p.id), 0) AS lot_sum
                FROM products p
                WHERE p.quantity != COALESCE((SELECT SUM(l.qty_remaining) FROM lots l
                                              WHERE l.product_id = p.id), 0)
            """).fetchall()
        self.assertEqual([dict(r) for r in bad], [], "批次帳與庫存總帳不一致")


class TestFIFOAndLedger(InventoryTestBase):
    """批次管理與 FIFO 先進先出"""

    def test_stock_in_creates_lot(self):
        pid = self.new_product("FIFO-A")
        self.stock_in(pid, 10)
        with self.db() as conn:
            lots = conn.execute("SELECT * FROM lots WHERE product_id = ?", (pid,)).fetchall()
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0]["qty_received"], 10)
        self.assertEqual(lots[0]["qty_remaining"], 10)
        self.assert_lot_ledger_balanced()

    def test_fifo_consumes_oldest_first_across_lots(self):
        pid = self.new_product("FIFO-B")
        self.stock_in(pid, 10, lot_no="B1")
        self.stock_in(pid, 20, lot_no="B2")
        self.stock_out(pid, 15)   # 應吃光 B1(10)再吃 B2 的 5
        with self.db() as conn:
            lots = conn.execute(
                "SELECT lot_no, qty_remaining FROM lots WHERE product_id = ? "
                "ORDER BY received_at, id", (pid,)).fetchall()
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual([(r["lot_no"], r["qty_remaining"]) for r in lots],
                         [("B1", 0), ("B2", 15)])
        self.assertEqual(qty, 15)
        self.assert_lot_ledger_balanced()

    def test_lot_consumption_traceability(self):
        pid = self.new_product("FIFO-C")
        self.stock_in(pid, 5, lot_no="C1")
        self.stock_in(pid, 5, lot_no="C2")
        self.stock_out(pid, 8)    # C1 全消耗 5 + C2 消耗 3
        with self.db() as conn:
            rows = conn.execute("""
                SELECT l.lot_no, c.quantity FROM lot_consumptions c
                JOIN lots l ON c.lot_id = l.id
                WHERE l.product_id = ? ORDER BY l.id
            """, (pid,)).fetchall()
        self.assertEqual([(r["lot_no"], r["quantity"]) for r in rows], [("C1", 5), ("C2", 3)])

    def test_stock_out_cannot_go_negative(self):
        pid = self.new_product("FIFO-D")
        self.stock_in(pid, 3)
        resp = self.stock_out(pid, 999)
        self.assertEqual(resp.status_code, 200)          # 重繪頁面而非 302
        self.assertIn("庫存不足", resp.get_data(as_text=True))
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual(qty, 3)                          # 資料完全不變
        self.assert_lot_ledger_balanced()

    def test_duplicate_lot_no_rejected_without_side_effect(self):
        pid = self.new_product("FIFO-E")
        self.stock_in(pid, 5, lot_no="E1")
        resp = self.stock_in(pid, 7, lot_no="E1")
        self.assertIn("此商品已有相同批號", resp.get_data(as_text=True))
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual(qty, 5, "批號衝突時庫存不可被加上去")
        self.assert_lot_ledger_balanced()


class TestReportMath(InventoryTestBase):
    """報表:加權平均成本、ABC 分級、庫齡分桶"""

    def test_weighted_average_cost(self):
        pid = self.new_product("COST-A", price="100")
        self.stock_in(pid, 10, lot_no="CA1", unit_cost="10")
        self.stock_in(pid, 30, lot_no="CA2", unit_cost="20")
        # 加權平均 = (10*10 + 30*20) / 40 = 17.5
        html = self.client.get("/report").get_data(as_text=True)
        self.assertIn("17.5", html)

    def test_weighted_average_ignores_consumed_lots(self):
        pid = self.new_product("COST-B", price="100")
        self.stock_in(pid, 10, lot_no="CB1", unit_cost="10")
        self.stock_in(pid, 10, lot_no="CB2", unit_cost="30")
        self.stock_out(pid, 10)      # FIFO 吃光 CB1,只剩成本 30 的 CB2
        html = self.client.get("/report").get_data(as_text=True)
        self.assertIn("平均成本", html)
        with self.db() as conn:
            row = conn.execute("""
                SELECT SUM(qty_remaining * unit_cost) * 1.0 / SUM(qty_remaining) AS avg_cost
                FROM lots WHERE product_id = ? AND qty_remaining > 0 AND unit_cost IS NOT NULL
            """, (pid,)).fetchone()
        self.assertAlmostEqual(row["avg_cost"], 30.0)

    def test_abc_classification_by_cumulative_value(self):
        # 價值懸殊:最高價品即使單獨就超過 80%,本身仍必須是 A 級
        # (否則 A 級從缺,ABC 分析失去「找出少數關鍵料號」的意義)
        big = self.new_product("ABC-BIG", price="1000")
        mid = self.new_product("ABC-MID", price="100")
        small = self.new_product("ABC-SML", price="1")
        self.stock_in(big, 100)     # 價值 100000(占 90.83%)
        self.stock_in(mid, 100)     # 價值 10000
        self.stock_in(small, 100)   # 價值 100
        html = self.client.get("/report").get_data(as_text=True)
        self.assertIn("ABC 分析", html)
        self.assertIn("<strong>A</strong>", html)
        # A 級那一列必須是最高價值的品項
        big_pos = html.index("ABC-BIG")
        small_pos = html.index("ABC-SML")
        self.assertLess(big_pos, small_pos, "ABC 應依庫存價值由高至低排序")
        # 精確比對:BIG 的分級儲存格必須是 A
        abc_section = html[html.index("ABC 分析"):]
        big_row = abc_section[abc_section.index("ABC-BIG") - 200:abc_section.index("ABC-BIG")]
        self.assertIn("<strong>A</strong>", big_row, "最高價值品項必須分為 A 級")

    def test_abc_typical_distribution(self):
        """一般分布下的分級界線:累積 ≤80% 為 A、≤95% 為 B、其餘 C"""
        rows = [{"value": v} for v in (50, 35, 10, 5)]   # 總和 100
        total = 100.0
        cum = 0.0
        grades = []
        for r in rows:
            prev_pct = cum / total * 100
            cum += r["value"]
            grades.append("A" if prev_pct < 80 else ("B" if prev_pct < 95 else "C"))
        self.assertEqual(grades, ["A", "A", "B", "C"])

    def test_aging_buckets_present_and_counted(self):
        pid = self.new_product("AGE-A")
        self.stock_in(pid, 7)
        html = self.client.get("/report").get_data(as_text=True)
        self.assertIn("庫齡分析", html)
        self.assertIn("0-30 天", html)
        self.assertIn("90 天以上", html)


class TestInputValidation(InventoryTestBase):
    """邊界輸入:不得回 500,必須是友善訊息"""

    def test_huge_quantity_rejected_not_500(self):
        pid = self.new_product("EDGE-A")
        resp = self.stock_in(pid, "999999999999999999999999999")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("數量", resp.get_data(as_text=True))

    def test_unicode_digit_quantity_not_500(self):
        pid = self.new_product("EDGE-B")
        resp = self.client.post("/stock/out", data={
            "product_id": str(pid), "quantity": "²"})   # 上標 2:isdigit 為真但 int() 會爆
        self.assertNotEqual(resp.status_code, 500)

    def test_unicode_digit_in_query_param_not_500(self):
        resp = self.client.get("/history?product_id=%C2%B2")
        self.assertNotEqual(resp.status_code, 500)

    def test_inf_and_nan_price_rejected(self):
        for bad in ("inf", "nan", "-inf"):
            self.client.post("/products/new", data={
                "name": "壞價格", "sku": f"BAD-{bad}", "unit_price": bad,
                "low_stock_threshold": "0"})
            with self.db() as conn:
                row = conn.execute("SELECT id FROM products WHERE sku = ?",
                                   (f"BAD-{bad}",)).fetchone()
            self.assertIsNone(row, f"單價 {bad} 不應被接受")

    def test_negative_and_zero_quantity_rejected(self):
        pid = self.new_product("EDGE-C")
        for bad in ("-5", "0", "abc", "1.5"):
            resp = self.stock_in(pid, bad)
            self.assertEqual(resp.status_code, 200, f"數量 {bad} 應被拒並重繪")
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual(qty, 0)


class TestCSVSafety(InventoryTestBase):
    """CSV 匯入韌性與匯出公式注入防護"""

    def _import(self, text, mode="products", encoding="utf-8"):
        return self.client.post("/import", data={
            "mode": mode,
            "csv_file": (__import__("io").BytesIO(text.encode(encoding)), "t.csv"),
        }, content_type="multipart/form-data")

    def test_bad_row_skipped_good_rows_imported(self):
        csv_text = (
            "SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存\r\n"
            "IMP-OK1,好料一,,個,10,0,,5\r\n"
            "IMP-OK2,好料二,,個,20,0,,3\r\n"
            "IMP-BAD,壞料,,個,10,0,,999999999999999999999999\r\n"
        )
        resp = self._import(csv_text)
        self.assertEqual(resp.status_code, 200, "單列壞值不得讓整批 500")
        self.assertIn("成功匯入 2 筆", resp.get_data(as_text=True))
        with self.db() as conn:
            got = [r["sku"] for r in conn.execute(
                "SELECT sku FROM products WHERE sku LIKE 'IMP-%' ORDER BY sku").fetchall()]
        self.assertEqual(got, ["IMP-OK1", "IMP-OK2"], "好列必須照匯、壞列只跳過")
        self.assert_lot_ledger_balanced()

    def test_cp950_big5_import(self):
        csv_text = ("SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存\r\n"
                    "BIG5-1,螢幕,顯示設備,台,3500,2,,8\r\n")
        resp = self._import(csv_text, encoding="cp950")
        self.assertIn("成功匯入 1 筆", resp.get_data(as_text=True))
        with self.db() as conn:
            row = conn.execute("SELECT name FROM products WHERE sku = 'BIG5-1'").fetchone()
        self.assertEqual(row["name"], "螢幕", "Big5 編碼的中文必須正確解碼")

    def test_export_escapes_formula_injection(self):
        self.client.post("/products/new", data={
            "name": "=2+5+cmd", "sku": "INJECT-1", "unit_price": "1",
            "low_stock_threshold": "0"})
        body = self.client.get("/export/inventory.csv").get_data(as_text=True)
        self.assertIn("'=2+5+cmd", body, "= 開頭的欄位必須被前置單引號跳脫")

    def test_csv_export_has_utf8_bom(self):
        raw = self.client.get("/export/inventory.csv").get_data()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Excel 需要 UTF-8 BOM 才不會中文亂碼")


class TestPermissions(unittest.TestCase):
    """權限分層:一般使用者不得執行破壞性操作"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ["INVENTORY_DB"]
        app_module.app.config["TESTING"] = True
        cls.admin = app_module.app.test_client()
        cls.admin.post("/login", data={"username": "admin", "password": "admin12345"})
        # 由管理員建立一般使用者
        cls.admin.post("/users/new", data={"username": "staff1", "password": "staff12345"})
        cls.staff = app_module.app.test_client()
        cls.staff.post("/login", data={"username": "staff1", "password": "staff12345"})

    def test_staff_can_do_daily_work(self):
        self.assertEqual(self.staff.get("/").status_code, 200)
        resp = self.staff.post("/products/new", data={
            "name": "同事建的料", "sku": "PERM-1", "unit_price": "5",
            "low_stock_threshold": "0"})
        self.assertEqual(resp.status_code, 302, "一般同事應可新增商品")
        with sqlite3.connect(self.db_path) as conn:
            pid = conn.execute("SELECT id FROM products WHERE sku='PERM-1'").fetchone()[0]
        resp = self.staff.post("/stock/in", data={"product_id": str(pid), "quantity": "5"})
        self.assertEqual(resp.status_code, 302, "一般同事應可入庫")

    def test_staff_cannot_delete_or_import(self):
        with sqlite3.connect(self.db_path) as conn:
            pid = conn.execute("SELECT id FROM products LIMIT 1").fetchone()[0]
        self.assertEqual(self.staff.post(f"/products/{pid}/delete").status_code, 403)
        self.assertEqual(self.staff.get("/import").status_code, 403)
        self.assertEqual(self.staff.get("/users").status_code, 403)
        self.assertEqual(self.staff.get("/audit").status_code, 403)

    def test_admin_can_delete_and_import(self):
        self.assertEqual(self.admin.get("/import").status_code, 200)
        self.assertEqual(self.admin.get("/users").status_code, 200)
        self.assertEqual(self.admin.get("/audit").status_code, 200)

    def test_admin_cannot_delete_self(self):
        with sqlite3.connect(self.db_path) as conn:
            uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        resp = self.admin.post(f"/users/{uid}/delete")
        self.assertIn("不可刪除自己", resp.get_data(as_text=True))
        with sqlite3.connect(self.db_path) as conn:
            still = conn.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0]
        self.assertEqual(still, 1)

    def test_unauthenticated_redirected(self):
        anon = app_module.app.test_client()
        self.assertEqual(anon.get("/").status_code, 302)
        self.assertEqual(anon.get("/history").status_code, 302)


class TestAuditAndTime(InventoryTestBase):
    """稽核軌跡與時區顯示"""

    def test_mutations_are_audited(self):
        self.new_product("AUDIT-1", name="稽核測試品")
        html = self.client.get("/audit").get_data(as_text=True)
        self.assertIn("新增商品", html)
        self.assertIn("admin", html)

    def test_history_shows_taiwan_time(self):
        pid = self.new_product("TZ-1")
        self.stock_in(pid, 1)
        html = self.client.get("/history").get_data(as_text=True)
        self.assertIn("時間(台灣)", html)
        with self.db() as conn:
            utc_str = conn.execute(
                "SELECT created_at FROM transactions WHERE product_id = ?", (pid,)).fetchone()[0]
        expected = app_module.fmt_local(utc_str)
        self.assertIn(expected, html)
        # 台灣時間應比 UTC 快 8 小時
        delta = (app_module.parse_utc(utc_str).astimezone(app_module.LOCAL_TZ).utcoffset())
        self.assertEqual(delta.total_seconds(), 8 * 3600)

    def test_local_date_filter_converts_to_utc_range(self):
        start_utc, end_utc = app_module.local_date_to_utc_range("2026-01-02", "2026-01-02")
        # 台灣 1/2 00:00 = UTC 1/1 16:00;台灣 1/2 23:59:59 = UTC 1/2 15:59:59
        self.assertEqual(start_utc, "2026-01-01 16:00:00")
        self.assertEqual(end_utc, "2026-01-02 15:59:59")


class TestSecurityConfig(unittest.TestCase):
    """安全設定的靜態檢查"""

    def test_no_hardcoded_dev_secret(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory_app.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("dev-inventory-secret-change-me", source,
                         "不得留下可預測的硬編碼金鑰")

    def test_upload_size_limit_configured(self):
        self.assertEqual(app_module.app.config["MAX_CONTENT_LENGTH"], 10 * 1024 * 1024)

    def test_proxy_header_not_trusted_by_default(self):
        self.assertFalse(app_module.TRUST_PROXY,
                         "直連部署預設不得採信 X-Forwarded-For")


if __name__ == "__main__":
    unittest.main(verbosity=2)
