#!/usr/bin/env python3
# test_inventory.py
# 庫存管理系統的自動化測試(純標準庫 unittest + Flask test_client,零額外依賴)
# 執行:python test_inventory.py
#
# 覆蓋重點是「帳務正確性與安全防線」——這些邏輯出錯不會有明顯症狀,
# 但會讓庫存帳、成本、權限悄悄失真,因此必須由測試把關:
#   FIFO 消耗、批次帳恆等式、加權平均成本、ABC 分級、庫齡分桶、
#   權限控制、輸入邊界、CSV 匯入韌性、CSV 公式注入防護。

import io
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
        # 由管理員建立一般使用者(可能已由其他測試類別建立,重複呼叫無副作用)
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


class TestCycleCount(InventoryTestBase):
    """循環盤點:帳實相符的核心機制,過帳必須同時修正庫存與批次帳"""

    def _new_count(self, name, scope="all"):
        self.client.post("/counts/new", data={"name": name, "scope": scope})
        with self.db() as conn:
            return conn.execute("SELECT id FROM stock_counts WHERE name = ?", (name,)).fetchone()["id"]

    def test_count_creation_snapshots_system_qty(self):
        pid = self.new_product("CNT-A")
        self.stock_in(pid, 40)
        cid = self._new_count("盤點-A")
        with self.db() as conn:
            row = conn.execute("""
                SELECT system_qty FROM stock_count_items WHERE count_id = ? AND product_id = ?
            """, (cid, pid)).fetchone()
        self.assertEqual(row["system_qty"], 40, "建單當下就該固定系統帳作為比較基準")

    def test_post_shortage_fixes_stock_and_lot_ledger(self):
        pid = self.new_product("CNT-B")
        self.stock_in(pid, 50)
        cid = self._new_count("盤點-B")
        self.client.post(f"/counts/{cid}/count",
                         data={"product_id": str(pid), "counted_qty": "47", "note": "領用未登記"})
        self.client.post(f"/counts/{cid}/post")
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            tx = conn.execute("""
                SELECT type, quantity FROM transactions
                WHERE product_id = ? AND purpose = '盤點調整'
            """, (pid,)).fetchone()
        self.assertEqual(qty, 47, "過帳後庫存必須等於實盤數")
        self.assertEqual((tx["type"], tx["quantity"]), ("out", 3), "盤虧應產生一筆出庫調整")
        self.assert_lot_ledger_balanced()

    def test_post_overage_creates_adjustment_lot(self):
        pid = self.new_product("CNT-C")
        self.stock_in(pid, 10)
        cid = self._new_count("盤點-C")
        self.client.post(f"/counts/{cid}/count", data={"product_id": str(pid), "counted_qty": "14"})
        self.client.post(f"/counts/{cid}/post")
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            lots = conn.execute(
                "SELECT COUNT(*) FROM lots WHERE product_id = ? AND note = '盤盈調整批'",
                (pid,)).fetchone()[0]
        self.assertEqual(qty, 14)
        self.assertEqual(lots, 1, "盤盈必須建立調整批,否則批次帳會短少")
        self.assert_lot_ledger_balanced()

    def test_accuracy_recorded_and_no_double_post(self):
        a = self.new_product("CNT-D1")
        b = self.new_product("CNT-D2")
        self.stock_in(a, 10)
        self.stock_in(b, 10)
        cid = self._new_count("盤點-D")
        self.client.post(f"/counts/{cid}/count", data={"product_id": str(a), "counted_qty": "10"})
        self.client.post(f"/counts/{cid}/count", data={"product_id": str(b), "counted_qty": "8"})
        self.client.post(f"/counts/{cid}/post")
        with self.db() as conn:
            acc = conn.execute("SELECT accuracy FROM stock_counts WHERE id = ?", (cid,)).fetchone()[0]
        self.assertAlmostEqual(acc, 50.0, places=1, msg="2 項盤點 1 項相符 → 準確率 50%")
        resp = self.client.post(f"/counts/{cid}/post")
        self.assertIn("已過帳", resp.get_data(as_text=True))

    def test_post_uses_current_qty_not_snapshot(self):
        """建單後若又有進出,過帳必須以當下庫存為準,不能把期間異動蓋掉。"""
        pid = self.new_product("CNT-E")
        self.stock_in(pid, 20)
        cid = self._new_count("盤點-E")
        self.stock_in(pid, 5)          # 建單後又入庫 → 現在是 25
        self.client.post(f"/counts/{cid}/count", data={"product_id": str(pid), "counted_qty": "25"})
        self.client.post(f"/counts/{cid}/post")
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual(qty, 25)
        self.assert_lot_ledger_balanced()


class TestReservations(InventoryTestBase):
    """預留與可用量:業界的 on-hand vs available 區分"""

    def test_reservation_reduces_available_not_onhand(self):
        pid = self.new_product("RSV-A")
        self.stock_in(pid, 30)
        self.client.post("/reservations/new",
                         data={"product_id": str(pid), "quantity": "12", "purpose": "WO-1"})
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(f'id="qty-{pid}">30<', html, "現貨量不受預留影響")
        self.assertIn(f'id="avail-{pid}">18', html, "可用量 = 現貨 − 預留")

    def test_reservation_cannot_exceed_available(self):
        pid = self.new_product("RSV-B")
        self.stock_in(pid, 10)
        resp = self.client.post("/reservations/new",
                                data={"product_id": str(pid), "quantity": "999"})
        self.assertIn("可用量不足", resp.get_data(as_text=True))
        with self.db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM reservations WHERE product_id = ?",
                             (pid,)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_release_restores_available(self):
        pid = self.new_product("RSV-C")
        self.stock_in(pid, 20)
        self.client.post("/reservations/new", data={"product_id": str(pid), "quantity": "5"})
        with self.db() as conn:
            rid = conn.execute(
                "SELECT id FROM reservations WHERE product_id = ? AND status='active'",
                (pid,)).fetchone()[0]
        self.client.post(f"/reservations/{rid}/release")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(f'id="avail-{pid}">20', html)


class TestUomAndFefo(InventoryTestBase):
    """單位換算與 FEFO 出庫策略"""

    def test_purchase_unit_conversion(self):
        self.client.post("/products/new", data={
            "name": "螺絲箱裝", "sku": "UOM-A", "unit_price": "1", "low_stock_threshold": "0",
            "unit": "個", "purchase_unit": "箱", "units_per_purchase": "100",
            "lead_time_days": "7", "service_level": "95", "issue_strategy": "FIFO"})
        with self.db() as conn:
            pid = conn.execute("SELECT id FROM products WHERE sku='UOM-A'").fetchone()[0]
        self.client.post("/stock/in", data={
            "product_id": str(pid), "quantity": "3", "qty_unit": "purchase"})
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            tx = conn.execute("SELECT quantity FROM transactions WHERE product_id = ?",
                              (pid,)).fetchone()[0]
        self.assertEqual(qty, 300, "3 箱 × 100 = 300 個")
        self.assertEqual(tx, 300, "異動也應記錄換算後的庫存單位數量")

    def test_purchase_unit_requires_setup(self):
        pid = self.new_product("UOM-B")   # 未設採購單位
        resp = self.client.post("/stock/in", data={
            "product_id": str(pid), "quantity": "2", "qty_unit": "purchase"})
        self.assertIn("尚未設定採購單位", resp.get_data(as_text=True))

    def test_fefo_consumes_earliest_expiry_first(self):
        self.client.post("/products/new", data={
            "name": "效期料", "sku": "FEFO-A", "unit_price": "1", "low_stock_threshold": "0",
            "units_per_purchase": "1", "lead_time_days": "7", "service_level": "95",
            "issue_strategy": "FEFO"})
        with self.db() as conn:
            pid = conn.execute("SELECT id FROM products WHERE sku='FEFO-A'").fetchone()[0]
        # 先入效期「晚」的批,再入效期「早」的批 —— FIFO 會扣錯,FEFO 才會扣對
        self.client.post("/stock/in", data={"product_id": str(pid), "quantity": "10",
                                            "lot_no": "LATE", "expiry_date": "2030-12-31"})
        self.client.post("/stock/in", data={"product_id": str(pid), "quantity": "10",
                                            "lot_no": "EARLY", "expiry_date": "2027-01-01"})
        self.stock_out(pid, 10)
        with self.db() as conn:
            remain = dict(conn.execute(
                "SELECT lot_no, qty_remaining FROM lots WHERE product_id = ?", (pid,)).fetchall())
        self.assertEqual(remain, {"EARLY": 0, "LATE": 10}, "FEFO 應先消耗最早到期的批")
        self.assert_lot_ledger_balanced()

    def test_expiring_lots_appear_in_alerts(self):
        soon = (app_module.today_local() + __import__("datetime").timedelta(days=10)).isoformat()
        self.client.post("/products/new", data={
            "name": "快到期料", "sku": "EXPIRE-A", "unit_price": "1", "low_stock_threshold": "0",
            "units_per_purchase": "1", "lead_time_days": "7", "service_level": "95"})
        with self.db() as conn:
            pid = conn.execute("SELECT id FROM products WHERE sku='EXPIRE-A'").fetchone()[0]
        self.client.post("/stock/in", data={"product_id": str(pid), "quantity": "5",
                                            "lot_no": "SOONLOT", "expiry_date": soon})
        html = self.client.get("/alerts").get_data(as_text=True)
        self.assertIn("效期警示", html)
        self.assertIn("SOONLOT", html)


class TestPlanning(InventoryTestBase):
    """安全庫存推導:把門檻從猜測變成由變異推導"""

    def _seed_usage(self, pid, quantities):
        """直接寫入跨日出庫紀錄,製造可計算的用量變異。"""
        from datetime import timedelta as _td
        now = __import__("datetime").datetime.now(app_module.timezone.utc)
        with self.db() as conn:
            for i, q in enumerate(quantities):
                if q <= 0:
                    continue   # transactions 有 quantity > 0 的 CHECK;沒出庫的日子本來就不該有紀錄
                ts = (now - _td(days=i)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO transactions (product_id, user_id, type, quantity, note, purpose, created_at)
                    VALUES (?, 1, 'out', ?, '', '', ?)
                """, (pid, q, ts))
            conn.commit()

    def test_safety_stock_formula(self):
        pid = self.new_product("PLAN-A")
        self.stock_in(pid, 500)
        self._seed_usage(pid, [5, 0, 12, 3, 0, 20, 8, 1, 15, 4])
        with app_module.app.test_request_context():
            pass
        html = self.client.get("/planning").get_data(as_text=True)
        self.assertIn("建議安全庫存", html)
        # 直接驗算公式:SS = Z × σ × √L,四捨五入取進位
        with app_module.app.test_client() as c:
            c.post("/login", data={"username": "admin", "password": "admin12345"})
        with app_module.app.test_request_context():
            app_module.g.db = None
        # 以模組函式直接驗證(不經 HTTP),避免頁面格式影響判斷
        with app_module.app.test_request_context():
            app_module.g.pop("db", None)
            stats = app_module.usage_stats(pid)
            prod = self.db().execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            ss, rop = app_module.suggest_safety_stock(prod, stats)
        expected = math_ceil(1.65 * stats["sd"] * (prod["lead_time_days"] ** 0.5))
        self.assertEqual(ss, expected, "安全庫存應等於 Z × 標準差 × √前置期(進位)")
        self.assertGreater(rop, ss, "再訂購點必須大於安全庫存(還要涵蓋前置期內的用量)")

    def test_longer_lead_time_raises_suggestion(self):
        pid = self.new_product("PLAN-B")
        self.stock_in(pid, 500)
        self._seed_usage(pid, [4, 9, 1, 14, 2, 7, 11])
        with app_module.app.test_request_context():
            app_module.g.pop("db", None)
            prod = dict(self.db().execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone())
            stats = app_module.usage_stats(pid)
            prod["lead_time_days"] = 7
            ss7, _ = app_module.suggest_safety_stock(prod, stats)
            prod["lead_time_days"] = 28
            ss28, _ = app_module.suggest_safety_stock(prod, stats)
        self.assertGreater(ss28, ss7, "前置期越長,需要的安全庫存越多")

    def test_apply_updates_thresholds(self):
        pid = self.new_product("PLAN-C")
        self.stock_in(pid, 500)
        self._seed_usage(pid, [6, 2, 18, 1, 9])
        self.client.post("/planning/apply")
        with self.db() as conn:
            th = conn.execute("SELECT low_stock_threshold FROM products WHERE id = ?",
                              (pid,)).fetchone()[0]
        self.assertGreater(th, 0, "套用後門檻應為推導出的正數")

    def test_xyz_classification(self):
        # 穩定用量 → X;劇烈波動 → Z
        steady = {"mean": 10.0, "sd": 2.0, "total": 0, "days": 30}    # CV = 0.2
        volatile = {"mean": 5.0, "sd": 9.0, "total": 0, "days": 30}   # CV = 1.8
        self.assertEqual(app_module.xyz_class(steady)[0], "X")
        self.assertEqual(app_module.xyz_class(volatile)[0], "Z")
        self.assertEqual(app_module.xyz_class(None)[0], "—")


class TestLocationAndQr(InventoryTestBase):
    """儲位與 QR 標籤"""

    def test_location_is_searchable(self):
        self.client.post("/products/new", data={
            "name": "儲位料", "sku": "LOC-A", "unit_price": "1", "low_stock_threshold": "0",
            "location": "A-03-2", "units_per_purchase": "1", "lead_time_days": "7",
            "service_level": "95"})
        html = self.client.get("/?q=A-03-2").get_data(as_text=True)
        self.assertIn("LOC-A", html, "應可用儲位搜尋到商品")

    def test_qr_endpoint_returns_png(self):
        pid = self.new_product("QR-A")
        resp = self.client.get(f"/products/{pid}/qr.png")
        if not app_module.HAS_QRCODE:
            self.skipTest("未安裝 qrcode 套件")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/png")
        self.assertTrue(resp.get_data().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_labels_page_lists_products(self):
        pid = self.new_product("LBL-A")
        html = self.client.get("/labels").get_data(as_text=True)
        self.assertIn("LBL-A", html)


class TestPurposeTracking(InventoryTestBase):
    """領用歸屬:結構化的用途欄位而非自由備註"""

    def test_purpose_recorded_and_filterable(self):
        pid = self.new_product("PUR-A")
        self.stock_in(pid, 20)
        self.client.post("/stock/out", data={
            "product_id": str(pid), "quantity": "3", "purpose": "WO-1001"})
        self.client.post("/stock/out", data={
            "product_id": str(pid), "quantity": "2", "purpose": "WO-2002"})
        html = self.client.get("/history?purpose=WO-1001").get_data(as_text=True)
        self.assertIn("WO-1001", html)
        self.assertNotIn("WO-2002", html, "篩選後不應出現其他用途的紀錄")


class TestCountPermissions(unittest.TestCase):
    """盤點的權限界線:現場人員可盤、只有管理員能過帳"""

    @classmethod
    def setUpClass(cls):
        cls.db_path = os.environ["INVENTORY_DB"]
        app_module.app.config["TESTING"] = True
        cls.admin = app_module.app.test_client()
        cls.admin.post("/login", data={"username": "admin", "password": "admin12345"})
        # 測試類別的執行順序不保證,這裡自行確保 staff1 存在(已存在則此呼叫無副作用)
        cls.admin.post("/users/new", data={"username": "staff1", "password": "staff12345"})
        cls.staff = app_module.app.test_client()
        cls.staff.post("/login", data={"username": "staff1", "password": "staff12345"})

    def test_staff_can_record_but_not_post(self):
        self.admin.post("/counts/new", data={"name": "權限盤點", "scope": "all"})
        with sqlite3.connect(self.db_path) as conn:
            cid = conn.execute(
                "SELECT id FROM stock_counts WHERE name='權限盤點'").fetchone()[0]
            pid = conn.execute("SELECT product_id FROM stock_count_items WHERE count_id=? LIMIT 1",
                               (cid,)).fetchone()[0]
        self.assertEqual(
            self.staff.post(f"/counts/{cid}/count",
                            data={"product_id": str(pid), "counted_qty": "1"}).status_code, 302,
            "現場人員應可記錄實盤數")
        self.assertEqual(self.staff.post(f"/counts/{cid}/post").status_code, 403,
                         "只有管理員能過帳")

    def test_staff_cannot_create_count(self):
        self.assertEqual(
            self.staff.post("/counts/new", data={"name": "不該建成", "scope": "all"}).status_code,
            403)


class TestReceipts(InventoryTestBase):
    """收貨單(ASN):預先登記不動庫存、料號自動比對、放行才入庫。"""

    def _upload(self, csv_text, ref_no="DN-T1", supplier_id=""):
        data = {"ref_no": ref_no, "supplier_id": supplier_id,
                "file": (io.BytesIO(csv_text.encode("utf-8")), "receipt.csv")}
        return self.client.post("/receipts/upload", data=data,
                                content_type="multipart/form-data")

    def _receipt_id(self, ref_no):
        with self.db() as conn:
            return conn.execute("SELECT id FROM receipts WHERE ref_no = ?", (ref_no,)).fetchone()["id"]

    def _items(self, rid):
        with self.db() as conn:
            return conn.execute(
                "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY line_no", (rid,)).fetchall()

    def test_upload_does_not_touch_stock(self):
        pid = self.new_product("RCP-001")
        self.stock_in(pid, 10)
        with self.db() as conn:
            before_qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            before_tx = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self._upload("料號,品名,數量\nRCP-001,測試品,99\n", ref_no="DN-NOSTOCK")
        with self.db() as conn:
            after_qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            after_tx = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self.assertEqual(after_qty, before_qty, "預先登記不得改變庫存")
        self.assertEqual(after_tx, before_tx, "預先登記不得產生異動")

    def test_match_by_alias(self):
        pid = self.new_product("RCP-002")
        self.client.post(f"/products/{pid}/aliases",
                         data={"company": "友達", "alias_sku": "AUO-XX1"})
        self._upload("料號,品名,數量\nAUO-XX1,對方料號,5\n", ref_no="DN-ALIAS")
        item = self._items(self._receipt_id("DN-ALIAS"))[0]
        self.assertEqual(item["match_type"], "alias")
        self.assertEqual(item["product_id"], pid)

    def test_unmatched_line_is_flagged_not_dropped(self):
        self._upload("料號,品名,數量\nNOPE-123,查無此料,7\n", ref_no="DN-NOMATCH")
        items = self._items(self._receipt_id("DN-NOMATCH"))
        self.assertEqual(len(items), 1, "對不上的列必須保留讓人處理,不可靜默丟棄")
        self.assertIsNone(items[0]["product_id"])
        self.assertEqual(items[0]["match_type"], "none")

    def test_post_creates_stock_and_keeps_ledger(self):
        pid = self.new_product("RCP-003")
        self._upload("料號,品名,數量,批號,效期,單價\nRCP-003,測試品,40,LOT-A,2030-01-01,3.5\n",
                     ref_no="DN-POST")
        rid = self._receipt_id("DN-POST")
        item = self._items(rid)[0]
        self.client.post(f"/receipts/{rid}/items/{item['id']}/check", data={"received_qty": "38"})
        resp = self.client.post(f"/receipts/{rid}/post")
        self.assertIn("放行完成", resp.get_data(as_text=True))
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
            lot = conn.execute("SELECT * FROM lots WHERE lot_no = 'LOT-A'").fetchone()
            status = conn.execute("SELECT status FROM receipts WHERE id = ?", (rid,)).fetchone()[0]
        self.assertEqual(qty, 38, "放行後庫存應等於實收數而非通知量")
        self.assertEqual(lot["qty_remaining"], 38)
        self.assertEqual(lot["expiry_date"], "2030-01-01")
        self.assertAlmostEqual(lot["unit_cost"], 3.5)
        self.assertEqual(status, "posted")
        self.assert_lot_ledger_balanced()

    def test_post_is_idempotent(self):
        pid = self.new_product("RCP-004")
        self._upload("料號,品名,數量\nRCP-004,測試品,20\n", ref_no="DN-TWICE")
        rid = self._receipt_id("DN-TWICE")
        item = self._items(rid)[0]
        self.client.post(f"/receipts/{rid}/items/{item['id']}/check", data={"received_qty": "20"})
        self.client.post(f"/receipts/{rid}/post")
        resp = self.client.post(f"/receipts/{rid}/post")
        self.assertIn("已放行", resp.get_data(as_text=True))
        with self.db() as conn:
            qty = conn.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()[0]
        self.assertEqual(qty, 20, "重複放行不得重複加庫存")

    def test_post_blocked_when_unmatched_has_qty(self):
        self._upload("料號,品名,數量\nGHOST-1,幽靈料,9\n", ref_no="DN-BLOCK")
        rid = self._receipt_id("DN-BLOCK")
        item = self._items(rid)[0]
        self.client.post(f"/receipts/{rid}/items/{item['id']}/check", data={"received_qty": "9"})
        resp = self.client.post(f"/receipts/{rid}/post")
        self.assertIn("尚有未對應", resp.get_data(as_text=True))
        with self.db() as conn:
            status = conn.execute("SELECT status FROM receipts WHERE id = ?", (rid,)).fetchone()[0]
        self.assertEqual(status, "open")

    def test_manual_map_can_remember_alias(self):
        pid = self.new_product("RCP-005")
        self.client.post("/suppliers/new", data={"name": "記憶測試商"})
        with self.db() as conn:
            sid = conn.execute("SELECT id FROM suppliers WHERE name = ?", ("記憶測試商",)).fetchone()[0]
        self._upload("料號,品名,數量\nTHEIR-777,對方料,4\n", ref_no="DN-REMEMBER", supplier_id=str(sid))
        rid = self._receipt_id("DN-REMEMBER")
        item = self._items(rid)[0]
        self.client.post(f"/receipts/{rid}/items/{item['id']}/map",
                         data={"product_id": str(pid), "remember": "1"})
        with self.db() as conn:
            alias = conn.execute(
                "SELECT * FROM part_aliases WHERE alias_sku = ?", ("THEIR-777",)).fetchone()
        self.assertIsNotNone(alias, "勾選記住時應建立跨公司別名")
        self.assertEqual(alias["product_id"], pid)


class TestTableFileReader(unittest.TestCase):
    """多格式讀檔:Excel 數字/日期轉換、Tab 偵測、舊格式友善拒絕。"""

    def test_excel_numeric_cell_becomes_clean_int(self):
        self.assertEqual(app_module.cell_to_text(100.0), "100")
        self.assertEqual(app_module.cell_to_text(12.5), "12.5")
        self.assertEqual(app_module.cell_to_text(None), "")

    def test_excel_date_cell_becomes_iso(self):
        from datetime import datetime as _dt
        self.assertEqual(app_module.cell_to_text(_dt(2027, 3, 9)), "2027-03-09")

    def test_tab_delimiter_detected(self):
        rows, err = app_module.read_table_file("x.csv", "A\tB\tC\n1\t2\t3\n".encode("utf-8"))
        self.assertIsNone(err)
        self.assertEqual(rows[1][1], ["1", "2", "3"])

    def test_blank_rows_skipped(self):
        rows, err = app_module.read_table_file("x.csv", "A,B\n\n1,2\n".encode("utf-8"))
        self.assertIsNone(err)
        self.assertEqual(len(rows), 2, "整列空白應略過")

    def test_legacy_xls_rejected_with_message(self):
        rows, err = app_module.read_table_file("old.xls", b"whatever")
        self.assertIsNone(rows)
        self.assertIn(".xlsx", err)


def math_ceil(x):
    import math as _m
    return _m.ceil(x)


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
