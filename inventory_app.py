# inventory_app.py
# 庫存管理系統(完整版)— 單檔 Flask 應用
# 功能:多使用者帳號、商品管理、供應商管理、入庫/出庫、庫存查詢與搜尋、
#       低庫存警示、異動歷史、進出統計報表、CSV 匯出、
#       跨公司料號對照(別名)、物料照片、以圖搜圖(dHash)、CSV 匯入、內網 IP 白名單
# 與 patrick_method_solver.py 完全獨立,互不 import。

import csv
import io
import math
import os
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, Response, g, redirect, render_template_string,
                   request, send_from_directory, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

# Pillow 供以圖搜圖使用;缺席時 app 仍可啟動,僅該功能停用
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# qrcode 供料架標籤使用;同樣採優雅停用
try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

app = Flask(__name__)

# 資料庫路徑可用環境變數覆蓋,驗收測試用 /tmp 下的乾淨 DB
DB_PATH = os.environ.get("INVENTORY_DB", "inventory.db")
DATA_DIR = os.path.dirname(os.path.abspath(DB_PATH))

# 物料照片存放目錄(gitignored),同樣可用環境變數覆蓋
IMAGE_DIR = os.path.abspath(os.environ.get("INVENTORY_IMAGES", "inventory_images"))

# 備份目錄:本機固定備到 DB 旁的 backups/;另可設 BACKUP_DIR 同步複製到共用槽/NAS
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
EXTRA_BACKUP_DIR = os.environ.get("BACKUP_DIR", "").strip()
BACKUP_KEEP = 14              # 本機保留份數
BACKUP_INTERVAL_SEC = 24 * 3600

ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

# 上傳大小上限 10MB:照片與 CSV 皆足夠,可擋下把記憶體吃滿的超大檔
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# 數值合理上限:避免超大整數在寫入 SQLite 時丟 OverflowError 造成 500
MAX_QUANTITY = 1_000_000_000

# 顯示時區:資料庫一律存 UTC(正確做法),顯示時轉台灣時間 UTC+8
LOCAL_TZ = timezone(timedelta(hours=8))

# 內網白名單:設定 ALLOWED_IPS(逗號分隔)後,只有名單內來源可存取。
# 未設定 = 功能關閉(內網部署靠網路隔離本身,不需要此機制)。
ALLOWED_IPS = {ip.strip() for ip in os.environ.get("ALLOWED_IPS", "").split(",") if ip.strip()}
# 只有確實部署在可信反向代理後方(如 Render)才可開啟;直連部署務必維持關閉,
# 否則任何人都能自行送出 X-Forwarded-For 標頭假冒白名單 IP。
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").strip().lower() in ("1", "true", "yes", "on")


def load_secret_key():
    # 絕不使用可預測的硬編碼金鑰(否則任何人都能離線偽造 session)。
    # 優先讀環境變數;否則在資料目錄產生一把持久隨機金鑰,達成零設定又不可預測。
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_path = os.path.join(DATA_DIR, "secret_key.txt")
    try:
        with open(key_path, "r", encoding="ascii") as fh:
            key = fh.read().strip()
            if key:
                return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(key_path, "w", encoding="ascii") as fh:
            fh.write(key)
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # 無法寫檔時仍以本次隨機金鑰運行(重啟後 session 失效,但不可偽造)
    return key


app.secret_key = load_secret_key()


@app.before_request
def restrict_to_allowed_ips():
    # 來源 IP 預設取實際連線位址;唯有明確設定 TRUST_PROXY 才採信
    # X-Forwarded-For(且取最後一段,即最靠近本機的代理所填入的值)。
    if not ALLOWED_IPS:
        return None
    client_ip = request.remote_addr or ""
    if TRUST_PROXY:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            client_ip = xff.split(",")[-1].strip()
    if client_ip not in ALLOWED_IPS:
        return Response(
            "<h1>403 禁止存取</h1><p>此系統僅限公司內部網路使用。</p>",
            status=403, mimetype="text/html")
    return None


@app.errorhandler(413)
def handle_too_large(err):
    return Response(
        "<h1>413 檔案過大</h1><p>上傳檔案不可超過 10MB,請縮小檔案後再試。</p>",
        status=413, mimetype="text/html")


# ---------------------------------------------------------------------------
# 資料庫連線與初始化
# ---------------------------------------------------------------------------

def get_db():
    # 每個 request 一條連線,存在 flask.g,teardown 時關閉
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL:讀取不再阻塞寫入。修正前「有人開歷史頁時他人入庫噴 500 掉資料」
        # 的並發問題;busy_timeout 讓寫入排隊而非立刻報錯。
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 15000")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    # CREATE TABLE IF NOT EXISTS 為冪等操作,啟動時自動建表
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode = WAL")  # WAL 是 DB 持久屬性,設一次即可
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            contact    TEXT DEFAULT '',
            phone      TEXT DEFAULT '',
            note       TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT NOT NULL,
            sku                 TEXT NOT NULL UNIQUE,
            category            TEXT DEFAULT '',
            unit                TEXT DEFAULT '個',
            unit_price          REAL NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER NOT NULL DEFAULT 0,
            quantity            INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            supplier_id         INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
            created_at          TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id),
            user_id    INTEGER NOT NULL REFERENCES users(id),
            type       TEXT NOT NULL CHECK (type IN ('in','out')),
            quantity   INTEGER NOT NULL CHECK (quantity > 0),
            note       TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tx_product ON transactions(product_id);
        CREATE INDEX IF NOT EXISTS idx_tx_created ON transactions(created_at);
        CREATE TABLE IF NOT EXISTS part_aliases (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            company    TEXT NOT NULL,
            alias_sku  TEXT NOT NULL,
            note       TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(company, alias_sku)
        );
        CREATE INDEX IF NOT EXISTS idx_alias_sku ON part_aliases(alias_sku);
        CREATE INDEX IF NOT EXISTS idx_alias_product ON part_aliases(product_id);
        CREATE TABLE IF NOT EXISTS product_images (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            phash         TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_img_product ON product_images(product_id);
        -- 批次管理(Lot Tracking):每筆入庫一批,出庫依 FIFO 消耗並記錄追溯
        CREATE TABLE IF NOT EXISTS lots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            transaction_id INTEGER REFERENCES transactions(id),
            lot_no         TEXT NOT NULL,
            qty_received   INTEGER NOT NULL CHECK (qty_received > 0),
            qty_remaining  INTEGER NOT NULL CHECK (qty_remaining >= 0),
            unit_cost      REAL,
            note           TEXT DEFAULT '',
            received_at    TEXT NOT NULL,
            UNIQUE(product_id, lot_no)
        );
        CREATE INDEX IF NOT EXISTS idx_lots_product ON lots(product_id);
        CREATE TABLE IF NOT EXISTS lot_consumptions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL REFERENCES transactions(id),
            lot_id         INTEGER NOT NULL REFERENCES lots(id),
            quantity       INTEGER NOT NULL CHECK (quantity > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_lc_tx ON lot_consumptions(transaction_id);
        -- 異動歷史每筆 in 都要回查建立的批號,無此索引在兩萬筆時會全表掃描(實測 6 秒)
        CREATE INDEX IF NOT EXISTS idx_lots_tx ON lots(transaction_id);
        -- 稽核軌跡:誰在什麼時候改了什麼(建檔維護與管理操作皆留痕)
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id),
            username    TEXT DEFAULT '',
            action      TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id   TEXT DEFAULT '',
            detail      TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
        -- 預留:現貨量之外的第二個數字,可用量 = 現貨 − 有效預留
        CREATE TABLE IF NOT EXISTS reservations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            quantity    INTEGER NOT NULL CHECK (quantity > 0),
            purpose     TEXT DEFAULT '',
            username    TEXT DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','released')),
            created_at  TEXT NOT NULL,
            released_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_resv_product ON reservations(product_id, status);
        -- 循環盤點:盤點單 + 逐項實盤數,過帳後產生調整異動修正帳
        CREATE TABLE IF NOT EXISTS stock_counts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            scope      TEXT DEFAULT '',
            status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','posted')),
            username   TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            posted_at  TEXT DEFAULT '',
            accuracy   REAL
        );
        CREATE TABLE IF NOT EXISTS stock_count_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            count_id    INTEGER NOT NULL REFERENCES stock_counts(id) ON DELETE CASCADE,
            product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            system_qty  INTEGER NOT NULL DEFAULT 0,
            counted_qty INTEGER,
            note        TEXT DEFAULT '',
            counted_at  TEXT DEFAULT '',
            UNIQUE(count_id, product_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sci_count ON stock_count_items(count_id);
    """)
    # 既有資料庫的欄位擴充(SQLite 的 ADD COLUMN 重複執行會報錯,故先檢查)
    ensure_column(conn, "products", "location", "TEXT DEFAULT ''")
    ensure_column(conn, "products", "purchase_unit", "TEXT DEFAULT ''")
    ensure_column(conn, "products", "units_per_purchase", "INTEGER DEFAULT 1")
    ensure_column(conn, "products", "lead_time_days", "INTEGER DEFAULT 7")
    ensure_column(conn, "products", "service_level", "REAL DEFAULT 95")
    ensure_column(conn, "products", "issue_strategy", "TEXT DEFAULT 'FIFO'")
    ensure_column(conn, "lots", "expiry_date", "TEXT DEFAULT ''")
    ensure_column(conn, "transactions", "purpose", "TEXT DEFAULT ''")
    conn.commit()
    conn.close()
    os.makedirs(IMAGE_DIR, exist_ok=True)
    reconcile_lots()


def ensure_column(conn, table, column, decl):
    # 冪等地新增欄位:舊資料庫升級時自動補上,已存在則略過
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def audit(action, target_type="", target_id="", detail=""):
    # 寫入稽核軌跡;必須在呼叫端的交易內(由呼叫端 commit),失敗不可影響主流程
    try:
        get_db().execute("""
            INSERT INTO audit_log (user_id, username, action, target_type, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session.get("user_id"), session.get("username", ""), action,
              target_type, str(target_id), detail, now_str()))
    except Exception:
        pass


def backup_db():
    # 用 sqlite3 的 backup API 取得一致性快照(WAL 模式下直接複製檔案並不安全)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"inventory_{stamp}.db"
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        target = os.path.join(BACKUP_DIR, name)
        src = sqlite3.connect(DB_PATH, timeout=15)
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        # 只保留最近 BACKUP_KEEP 份,避免磁碟被無限佔用
        backups = sorted(f for f in os.listdir(BACKUP_DIR)
                         if f.startswith("inventory_") and f.endswith(".db"))
        for old in backups[:-BACKUP_KEEP]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except OSError:
                pass
        # 另備一份到共用槽/NAS(設了 BACKUP_DIR 才做);失敗不影響本機備份
        if EXTRA_BACKUP_DIR:
            try:
                os.makedirs(EXTRA_BACKUP_DIR, exist_ok=True)
                shutil.copy2(target, os.path.join(EXTRA_BACKUP_DIR, name))
            except OSError as exc:
                print(f"[備份] 共用槽備份失敗({EXTRA_BACKUP_DIR}):{exc}")
        return target
    except Exception as exc:
        print(f"[備份] 失敗:{exc}")
        return None


def start_backup_thread():
    # 啟動時先備一份,之後每 24 小時一次(daemon thread,關閉服務即結束)
    def loop():
        while True:
            time.sleep(BACKUP_INTERVAL_SEC)
            backup_db()
    backup_db()
    threading.Thread(target=loop, daemon=True).start()


def reconcile_lots():
    # 期初自動補批:舊資料庫升級時,若商品現時庫存大於批次剩餘總和,
    # 以「期初批」補齊缺口,確保批次帳與總帳恆一致(批次剩餘總和 = quantity)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.id, p.quantity,
               COALESCE((SELECT SUM(l.qty_remaining) FROM lots l WHERE l.product_id = p.id), 0) AS lot_sum
        FROM products p
    """).fetchall()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        gap = r["quantity"] - r["lot_sum"]
        if gap > 0:
            conn.execute("""
                INSERT OR IGNORE INTO lots (product_id, lot_no, qty_received, qty_remaining, note, received_at)
                VALUES (?, ?, ?, ?, '期初庫存自動補批', ?)
            """, (r["id"], f"INIT-{r['id']}", gap, gap, stamp))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 以圖搜圖:dHash 感知雜湊(9x8 灰階縮圖 → 64-bit 指紋)+ Hamming 距離
# ---------------------------------------------------------------------------

def compute_dhash(stream):
    # 回傳 16 位 hex 字串;讀不出圖片時丟出例外由呼叫端處理
    img = Image.open(stream).convert("L").resize((9, 8), Image.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return f"{bits:016x}"


def hamming_distance(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def now_str():
    # 資料庫一律存 UTC 字串(跨時區正確、可直接字串比較);顯示時才轉台灣時間
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(s):
    # 把 DB 內的 UTC 字串轉成有時區資訊的 datetime
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fmt_local(s):
    # UTC 字串 → 台灣時間顯示字串(給頁面與 CSV 用)
    if not s:
        return ""
    try:
        return parse_utc(s).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return s


def local_date_to_utc_range(start_date, end_date):
    # 使用者輸入的是台灣日期,DB 存 UTC:把 [start 00:00, end 23:59:59] 台灣時間
    # 換算成對應的 UTC 字串區間,日期篩選才不會整體偏移 8 小時
    start_utc = end_utc = None
    try:
        if start_date:
            local_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            start_utc = local_start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if end_date:
            local_end = (datetime.strptime(end_date, "%Y-%m-%d")
                         .replace(hour=23, minute=59, second=59, tzinfo=LOCAL_TZ))
            end_utc = local_end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None, None
    return start_utc, end_utc


def safe_int(value, default=None):
    # 取代「先 isdigit() 再 int()」:isdigit 對上標²等 Unicode 數字為真但 int() 會爆
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def today_local():
    return datetime.now(LOCAL_TZ).date()


# ---------------------------------------------------------------------------
# 存貨規劃:安全庫存推導、XYZ 分級
# 業界系統不讓使用者憑印象填低庫存門檻,而是由用量變異、前置期與目標服務水準推導。
# ---------------------------------------------------------------------------

# 服務水準對應的常態分位數 Z(業界常用檔位)
Z_TABLE = {80: 0.84, 85: 1.04, 90: 1.28, 95: 1.65, 97: 1.88, 98: 2.05, 99: 2.33}

USAGE_WINDOW_DAYS = 90   # 統計用量的回溯天數


def z_for_service_level(level):
    # 取最接近的檔位,避免使用者填了非標準值就算不出來
    try:
        lv = float(level)
    except (TypeError, ValueError):
        lv = 95.0
    return Z_TABLE[min(Z_TABLE, key=lambda k: abs(k - lv))]


def usage_stats(product_id, window_days=USAGE_WINDOW_DAYS):
    """回傳期間內的日用量平均與標準差(只看出庫,那才是真正的消耗)。"""
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = get_db().execute("""
        SELECT created_at, quantity FROM transactions
        WHERE product_id = ? AND type = 'out' AND created_at >= ?
    """, (product_id, since)).fetchall()
    if not rows:
        return None
    # 先彙總成每日用量,沒有出庫的日子算 0(否則會嚴重高估日均)
    per_day = {}
    for r in rows:
        day = r["created_at"][:10]
        per_day[day] = per_day.get(day, 0) + r["quantity"]
    series = [per_day.get(
        (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
        for i in range(window_days)]
    n = len(series)
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    return {"mean": mean, "sd": math.sqrt(var), "total": sum(series), "days": n}


def suggest_safety_stock(product, stats):
    """SS = Z × σ_d × √L(僅需求變異版本;前置期變異未知時的標準做法)。
    回傳 (建議安全庫存, 再訂購點) — 皆無條件進位為整數,寧多勿少。"""
    if not stats or stats["mean"] <= 0:
        return None, None
    lead = max(1, product["lead_time_days"] or 7)
    z = z_for_service_level(product["service_level"])
    ss = z * stats["sd"] * math.sqrt(lead)
    rop = stats["mean"] * lead + ss
    return math.ceil(ss), math.ceil(rop)


def xyz_class(stats):
    """依變異係數 CV 分級:X 穩定、Y 中等、Z 高度波動(業界常用門檻 0.5 / 1.0)。"""
    if not stats or stats["mean"] <= 0:
        return "—", None
    cv = stats["sd"] / stats["mean"]
    return ("X" if cv < 0.5 else "Y" if cv < 1.0 else "Z"), cv


# ---------------------------------------------------------------------------
# 預留:可用量 = 現貨 − 有效預留(業界的 on-hand vs available 區分)
# ---------------------------------------------------------------------------

def reserved_map():
    return {r["product_id"]: r["qty"] for r in get_db().execute("""
        SELECT product_id, SUM(quantity) AS qty FROM reservations
        WHERE status = 'active' GROUP BY product_id
    """).fetchall()}


def reserved_qty(product_id):
    row = get_db().execute("""
        SELECT COALESCE(SUM(quantity), 0) AS qty FROM reservations
        WHERE product_id = ? AND status = 'active'
    """, (product_id,)).fetchone()
    return row["qty"]


# ---------------------------------------------------------------------------
# 批次消耗:FIFO / FEFO(出庫與盤虧調整共用,確保批次帳恆等式在兩條路徑都成立)
# ---------------------------------------------------------------------------

def consume_lots(db, pid, qty, tx_id, ts):
    """依商品的出庫策略消耗批次並記錄追溯明細。
    FIFO = 先進先出(依入庫時間);FEFO = 先到期先出(依有效期,無效期者排最後)。"""
    strategy = (db.execute("SELECT issue_strategy FROM products WHERE id = ?",
                           (pid,)).fetchone() or {"issue_strategy": "FIFO"})["issue_strategy"]
    if strategy == "FEFO":
        # 有效期空字串排最後,同效期再依入庫順序
        order = "CASE WHEN expiry_date = '' THEN 1 ELSE 0 END, expiry_date, received_at, id"
    else:
        order = "received_at, id"
    remaining = qty
    lots = db.execute(f"""
        SELECT id, qty_remaining FROM lots
        WHERE product_id = ? AND qty_remaining > 0
        ORDER BY {order}
    """, (pid,)).fetchall()
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["qty_remaining"], remaining)
        db.execute("UPDATE lots SET qty_remaining = qty_remaining - ? WHERE id = ?",
                   (take, lot["id"]))
        db.execute("""
            INSERT INTO lot_consumptions (transaction_id, lot_id, quantity)
            VALUES (?, ?, ?)
        """, (tx_id, lot["id"], take))
        remaining -= take
    if remaining > 0:
        # 防禦:批次帳有缺口時建調整批補齊(正常流程不會發生)
        cur = db.execute("""
            INSERT INTO lots (product_id, transaction_id, lot_no, qty_received,
                              qty_remaining, note, received_at)
            VALUES (?, ?, ?, ?, 0, '缺口調整批', ?)
        """, (pid, tx_id, f"ADJ-{tx_id}", remaining, ts))
        db.execute("""
            INSERT INTO lot_consumptions (transaction_id, lot_id, quantity)
            VALUES (?, ?, ?)
        """, (tx_id, cur.lastrowid, remaining))
        # 正常流程不該走到這裡:留下明確告警供人工稽核,不靜默吸收
        audit("批次帳異常", "商品", pid,
              f"消耗 {qty} 時批次剩餘不足 {remaining},已建立缺口調整批 ADJ-{tx_id}")
        print(f"[警告] 商品 {pid} 批次帳出現缺口 {remaining},已記錄稽核軌跡")


def fmt_num(value):
    # 數字(無千分位):整數不帶小數點,小數去尾零(125.0 → 125、25.5 → 25.5)
    # 用於表單值與 CSV(千分位會讓 float() 與 Excel 數值欄位解析失敗)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_money(value):
    # 金額顯示(含千分位,僅供頁面顯示):12000 → 12,000
    return f"{value:,.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# 登入保護
# ---------------------------------------------------------------------------

def forbidden(msg="您沒有執行此操作的權限,請洽管理員。"):
    return Response(f"<h1>403 權限不足</h1><p>{msg}</p>"
                    f"<p><a href='/'>返回庫存總覽</a></p>",
                    status=403, mimetype="text/html")


def admin_required(view):
    # 破壞性操作(刪除、整批匯入、帳號管理)限管理員
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return forbidden()
        return view(*args, **kwargs)
    return wrapped


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# 版面模板:共用 LAYOUT + 各頁 body 片段,render_page() 組裝
# ---------------------------------------------------------------------------

LAYOUT = """
<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>庫存管理系統</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #eef2f6; color: #1e293b; font-size: 15px; line-height: 1.55;
               font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans TC", "Microsoft JhengHei", sans-serif; }
        nav { position: sticky; top: 0; z-index: 10; background: #1e293b; display: flex; align-items: center;
              gap: 2px; padding: 0 12px; overflow-x: auto; white-space: nowrap; box-shadow: 0 1px 4px rgba(15,23,42,.25); }
        nav a { color: #cbd5e1; text-decoration: none; padding: 13px 10px; font-size: 14px; border-bottom: 2px solid transparent; }
        nav a:hover { color: #fff; border-bottom-color: #60a5fa; }
        nav a.active { color: #fff; border-bottom-color: #3b82f6; }
        nav .user-info { margin-left: auto; color: #94a3b8; font-size: 13px; padding-left: 12px; }
        .container { max-width: 1080px; margin: 22px auto; background: #fff; padding: 22px 26px 26px;
                     border-radius: 14px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(15,23,42,.05); }
        h1 { font-size: 21px; margin: 0 0 14px; color: #0f172a; }
        h2 { font-size: 16px; margin: 0 0 10px; color: #0f172a; padding-left: 10px; border-left: 4px solid #2563eb; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 14px; }
        th, td { border: 1px solid #e2e8f0; padding: 9px 11px; text-align: left; vertical-align: middle; }
        th { background: #f1f5f9; color: #334155; font-size: 13px; }
        tr:not(.low-stock):hover td { background: #f8fafc; }
        td[id^="qty-"] { font-weight: 700; font-size: 16px; color: #0f172a; }
        th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
        tr.low-stock td { background: #fef2f2; }
        tr.lot-empty td { color: #94a3b8; }
        .badge-low { display: inline-block; background: #fee2e2; color: #b91c1c; font-size: 12px; font-weight: 700;
                     padding: 1px 8px; border-radius: 999px; margin-left: 4px; white-space: nowrap; }
        .msg { padding: 11px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 14px; }
        .msg.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
        .msg.ok { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
        .banner { background: #fffbeb; border: 1px solid #fde68a; color: #92400e; padding: 11px 14px;
                  border-radius: 10px; margin-bottom: 14px; }
        .banner a { display: inline-block; padding: 4px 0; }
        .note { color: #64748b; font-size: 13px; }
        .pager { margin-top: 14px; font-size: 14px; }
        /* 第五階段:盤點、預留、規劃、標籤 */
        .loc-cell { font-family: ui-monospace, monospace; font-size: 13px; color: #334155; white-space: nowrap; }
        .resv-note { font-size: 11px; color: #b45309; font-weight: 600; white-space: nowrap; }
        .chip-open { background: #fef3c7; color: #92400e; font-size: 12px; font-weight: 700;
                     padding: 2px 9px; border-radius: 999px; }
        .chip-posted { background: #dcfce7; color: #15803d; font-size: 12px; font-weight: 700;
                       padding: 2px 9px; border-radius: 999px; }
        tr.has-diff td { background: #fffbeb; }
        @media (prefers-color-scheme: dark) {
            .loc-cell { color: #cbd5e1; }
            .stat-box { background: #1e293b; border-color: #334155; }
            .stat-num { color: #f1f5f9; }
            .stat-cap { color: #94a3b8; }
            tr.has-diff td { background: #292417; }
            .label, .qr-img { background: #fff; }
        }
        .stat-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 14px 0 18px; }
        .stat-box { flex: 1 1 130px; background: #f8fafc; border: 1px solid #e2e8f0;
                    border-radius: 10px; padding: 12px 16px; }
        .stat-num { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums;
                    letter-spacing: -.02em; color: #0f172a; }
        .stat-cap { font-size: 12.5px; color: #64748b; margin-top: 2px; }
        .count-form { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .count-input { width: 90px !important; margin-top: 0 !important; text-align: right; }
        .count-note { width: 130px !important; margin-top: 0 !important; font-size: 13px; }
        .qr-row { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 16px 0 4px; }
        .qr-img { width: 120px; height: 120px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
        .qr-cap { font-weight: 700; font-size: 14px; margin-bottom: 2px; }
        .label-sheet { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
        .label { display: flex; gap: 10px; align-items: center; border: 1px solid #cbd5e1;
                 border-radius: 8px; padding: 10px; background: #fff; break-inside: avoid; }
        .label img { width: 84px; height: 84px; flex-shrink: 0; }
        .label-text { min-width: 0; }
        .label-sku { font-family: ui-monospace, monospace; font-weight: 700; font-size: 14px; }
        .label-name { font-size: 13px; margin: 1px 0; word-break: break-word; }
        .label-loc { font-size: 12px; color: #475569; }
        @media print {
            nav, footer, .no-print, .filters, form { display: none !important; }
            .container { box-shadow: none; border: none; margin: 0; padding: 0; max-width: none; }
            body { background: #fff; }
            .label { border-color: #999; }
        }
        .pager .page-no { color: #64748b; }
        form.inline { display: inline; }
        label { display: block; margin-top: 12px; font-weight: 600; font-size: 14px; color: #334155; }
        input[type=text], input[type=password], input[type=number], input[type=date], select {
            width: 100%; max-width: 420px; padding: 9px 11px; margin-top: 5px; font-size: 16px;
            border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; }
        input:focus, select:focus { outline: 2px solid #bfdbfe; border-color: #2563eb; }
        input[type=file] { margin-top: 6px; font-size: 14px; }
        input[type=submit], button { display: block; padding: 10px 20px; margin-top: 14px; font-size: 15px; font-weight: 600;
            color: #fff; background: #2563eb; border: none; border-radius: 8px; cursor: pointer; }
        input[type=submit]:hover, button:hover { background: #1d4ed8; }
        .small-btn { display: inline-block; padding: 4px 10px; margin: 0; font-size: 12px; font-weight: 600;
                     color: #b91c1c; background: transparent; border: 1px solid transparent; border-radius: 6px; }
        .small-btn:hover { background: #fef2f2; color: #b91c1c; border-color: #fca5a5; }
        /* 盤點的「記錄」是儲存動作,不該長得像刪除;定義於 .small-btn 之後才蓋得過紅色 */
        .small-btn.ok-btn { color: #1d4ed8; border-color: #93c5fd; }
        .small-btn.ok-btn:hover { background: #eff6ff; color: #1d4ed8; border-color: #60a5fa; }
        .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0 4px; }
        .filters input, .filters select { width: auto; margin-top: 0; }
        .filters input[type=submit] { margin-top: 0; padding: 9px 16px; }
        footer { text-align: center; color: #94a3b8; padding: 16px; font-size: 12px; }
        a.plain { color: #2563eb; text-decoration: none; }
        a.plain:hover { text-decoration: underline; }
        .alias-cell { font-size: 12px; color: #475569; }
        .photo-wall { display: flex; flex-wrap: wrap; gap: 12px; margin: 10px 0; }
        .photo-wall .photo-item { text-align: center; }
        .photo-wall img, img.thumb { max-width: 150px; max-height: 150px; border: 1px solid #e2e8f0;
                                     border-radius: 10px; display: block; }
        .photo-wall .photo-item form { margin-top: 4px; }
        .detail-section { margin-top: 26px; border-top: 1px solid #eef2f6; padding-top: 16px; }
        .import-help { background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px 16px;
                       border-radius: 10px; font-size: 13px; color: #334155; }
        .import-help code { background: #eef2f6; padding: 1px 6px; border-radius: 5px; }
        .hero-search { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 12px; }
        .hero-search input[type=text] { flex: 1 1 240px; max-width: none; margin-top: 0; padding: 12px 16px;
                                        font-size: 16px; border-radius: 10px; }
        .hero-search select { width: auto; margin-top: 0; border-radius: 10px; }
        .hero-search input[type=submit] { margin-top: 0; padding: 12px 22px; border-radius: 10px; }
        .sub-links { margin: 0 0 14px; font-size: 13px; color: #94a3b8; }
        .quick-actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr));
                         gap: 10px; margin-bottom: 16px; }
        .quick-actions a { display: block; text-align: center; background: #f8fafc; border: 1px solid #e2e8f0;
                           border-radius: 12px; padding: 12px 6px; text-decoration: none; color: #1e293b;
                           font-size: 13px; font-weight: 600; }
        .quick-actions a:hover { border-color: #93c5fd; background: #eff6ff; }
        .quick-actions .qa-icon { display: block; font-size: 22px; margin-bottom: 4px; }
        .qa-in { color: #15803d; font-weight: 700; }
        .qa-out { color: #b45309; font-weight: 700; }
        .action-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 4px; }
        .action-links a { display: inline-block; padding: 9px 14px; border: 1px solid #cbd5e1; border-radius: 8px;
                          text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px; }
        .action-links a:hover { border-color: #93c5fd; background: #eff6ff; }
        .action-links a.primary { border-color: #93c5fd; color: #1d4ed8; }
        .auth-box { max-width: 380px; margin: 0 auto; }
        .container:has(.auth-box) { max-width: 440px; margin-top: 9vh; }
        @media (max-width: 760px) {
            .container { margin: 10px; padding: 16px 14px 20px; border-radius: 12px; }
            /* 導覽列換行完整顯示,不靠橫向捲動(使用者才找得到全部功能與登出) */
            nav { flex-wrap: wrap; white-space: normal; overflow-x: visible; position: static; padding: 2px 10px; }
            nav a { padding: 9px 8px; }
            nav .user-info { flex-basis: 100%; padding: 2px 0 8px; }
            /* 一般表格:tbody 撐滿寬度、必要時橫向捲動 */
            table { display: block; overflow-x: auto; }
            table:not(.cards) tbody { display: table; width: 100%; }
            table:not(.cards) th { white-space: nowrap; }
            /* 卡片式表格:名稱當標題、庫存緊隨,次要欄位縮小 */
            table.cards { display: block; overflow: visible; }
            table.cards tbody { display: block; width: 100%; }
            table.cards tr:first-child { display: none; }
            table.cards tr { display: flex; flex-direction: column; border: 1px solid #e2e8f0; border-radius: 12px;
                             margin-bottom: 10px; padding: 8px 14px; background: #fff; }
            table.cards tr.low-stock { border-color: #fecaca; background: #fef2f2; }
            table.cards tr.low-stock td { background: transparent; }
            table.cards td { display: flex; justify-content: space-between; align-items: center; gap: 12px;
                             border: none; padding: 7px 0; text-align: right;
                             border-bottom: 1px dashed #eef2f6; }
            table.cards td:last-child { border-bottom: none; }
            table.cards td::before { content: attr(data-label); font-weight: 600; color: #64748b;
                                     font-size: 13px; text-align: left; flex-shrink: 0; }
            table.cards td[data-label="名稱"] { order: -2; font-size: 17px; font-weight: 700;
                                                justify-content: flex-start; text-align: left; }
            table.cards td[data-label="名稱"]::before { content: none; }
            table.cards td[data-label="庫存"], table.cards td[data-label="目前庫存"] { order: -1; }
            table.cards td[data-label="別名料號"], table.cards td[data-label="單價"],
            table.cards td[data-label="低庫存門檻"] { font-size: 12px; color: #64748b; }
            /* 觸控目標:操作連結與刪除鈕加大 */
            table.cards td[data-label="操作"] a.plain { display: inline-block; padding: 8px 12px; }
            .small-btn { min-height: 40px; padding: 8px 14px; font-size: 13px; border-color: #fca5a5; }
            input[type=submit], button { min-height: 44px; }
            .filters input[type=submit], .hero-search input[type=submit] { min-height: auto; }
            /* 直式表單的主要送出鈕滿版好按(篩選列與搜尋列除外) */
            form:not(.filters):not(.hero-search):not(.inline) > input[type=submit] { width: 100%; }
            /* 盤點輸入:手機上整列堆疊,輸入框與按鈕都放大好按 */
            table.cards td[data-label="實盤數"] { flex-direction: column; align-items: stretch; }
            table.cards td[data-label="實盤數"]::before { margin-bottom: 6px; }
            .count-form { width: 100%; }
            .count-input, .count-note { width: 100% !important; flex: 1 1 100%; }
            .count-form .small-btn { width: 100%; margin-top: 4px; }
        }
    </style>
</head>
<body>
    {% if session.get('user_id') %}
    <nav>
        <a {% if request.path == '/' %}class="active" {% endif %}href="{{ url_for('index') }}">庫存總覽</a>
        <a {% if request.path == '/alerts' %}class="active" {% endif %}href="{{ url_for('alerts') }}">低庫存警示</a>
        <a {% if request.path == '/stock/in' %}class="active" {% endif %}href="{{ url_for('stock_in') }}">入庫</a>
        <a {% if request.path == '/stock/out' %}class="active" {% endif %}href="{{ url_for('stock_out') }}">出庫</a>
        <a {% if request.path == '/history' %}class="active" {% endif %}href="{{ url_for('history') }}">異動歷史</a>
        <a {% if request.path.startswith('/suppliers') %}class="active" {% endif %}href="{{ url_for('suppliers') }}">供應商</a>
        <a {% if request.path == '/report' %}class="active" {% endif %}href="{{ url_for('report') }}">報表</a>
        <a {% if request.path == '/products/new' %}class="active" {% endif %}href="{{ url_for('product_new') }}">新增商品</a>
        <a {% if request.path == '/search/image' %}class="active" {% endif %}href="{{ url_for('image_search') }}">以圖搜圖</a>
        <a {% if request.path.startswith('/counts') %}class="active" {% endif %}href="{{ url_for('counts_page') }}">盤點</a>
        <a {% if request.path.startswith('/reservations') %}class="active" {% endif %}href="{{ url_for('reservations_page') }}">預留</a>
        <a {% if request.path.startswith('/planning') %}class="active" {% endif %}href="{{ url_for('planning_page') }}">存貨規劃</a>
        <a {% if request.path == '/labels' %}class="active" {% endif %}href="{{ url_for('labels_page') }}">料架標籤</a>
        {% if session.get('is_admin') %}
        <a {% if request.path == '/import' %}class="active" {% endif %}href="{{ url_for('csv_import') }}">CSV 匯入</a>
        <a {% if request.path == '/audit' %}class="active" {% endif %}href="{{ url_for('audit_page') }}">稽核軌跡</a>
        <a {% if request.path.startswith('/users') %}class="active" {% endif %}href="{{ url_for('users_page') }}">帳號管理</a>
        {% endif %}
        <span class="user-info">使用者:{{ session.get('username') }}{% if session.get('is_admin') %}(管理員){% endif %}&nbsp;|&nbsp;<a href="{{ url_for('logout') }}">登出</a></span>
    </nav>
    {% endif %}
    <div class="container">
        {% if error %}<div class="msg error">{{ error }}</div>{% endif %}
        {% if msg %}<div class="msg ok">{{ msg }}</div>{% endif %}
        __BODY__
    </div>
    <footer>庫存管理系統 &copy; {{ year }}</footer>
</body>
</html>
"""


def build_pager(endpoint, page, has_next, **params):
    # 純連結分頁(零 JS);保留目前的搜尋/篩選參數。
    # 回傳 Markup 讓 Jinja2 直接輸出 HTML(否則會被自動跳脫成字面文字)
    parts = []
    if page > 1:
        prev_url = escape(url_for(endpoint, page=page - 1, **params))
        parts.append(f'<a class="plain" href="{prev_url}">← 上一頁</a>')
    parts.append(f'<span class="page-no">第 {page} 頁</span>')
    if has_next:
        next_url = escape(url_for(endpoint, page=page + 1, **params))
        parts.append(f'<a class="plain" href="{next_url}">下一頁 →</a>')
    return Markup('<p class="pager">' + '　'.join(parts) + '</p>')


def render_page(body, **ctx):
    ctx.setdefault("error", None)
    ctx.setdefault("msg", None)
    ctx.setdefault("year", datetime.now().year)
    return render_template_string(LAYOUT.replace("__BODY__", body), **ctx)


PAGE_REGISTER = """
<div class="auth-box">
{% if closed %}
<h1>不開放自助註冊</h1>
<p>本系統已完成初始設定。為了資料安全,新帳號一律由管理員建立。</p>
<p><a class="plain" href="{{ url_for('login') }}">前往登入</a></p>
{% else %}
<h1>建立管理員帳號</h1>
<p class="note">這是系統的第一個帳號,將自動成為管理員(可管理帳號、刪除資料、CSV 匯入)。建立後系統即關閉自助註冊。</p>
<form method="post">
    <label>帳號</label><input type="text" name="username" value="{{ username or '' }}">
    <label>密碼(至少 8 碼)</label><input type="password" name="password">
    <input type="submit" value="建立管理員帳號">
</form>
<p>已有帳號?<a class="plain" href="{{ url_for('login') }}">前往登入</a></p>
{% endif %}
</div>
"""

PAGE_LOGIN = """
<div class="auth-box">
<h1>登入庫存管理系統</h1>
<form method="post">
    <label>帳號</label><input type="text" name="username" value="{{ username or '' }}">
    <label>密碼</label><input type="password" name="password">
    <input type="submit" value="登入">
</form>
<p>還沒有帳號?<a class="plain" href="{{ url_for('register') }}">前往註冊</a></p>
</div>
"""

PAGE_INDEX = """
<h1>庫存總覽</h1>
{% if low_count > 0 %}
<div class="banner">⚠ 目前有 {{ low_count }} 項商品低於庫存門檻,<a class="plain" href="{{ url_for('alerts') }}">查看低庫存警示</a></div>
{% endif %}
<form method="get" class="hero-search">
    <input type="text" name="q" placeholder="輸入料號、品名或任一公司的別名料號" value="{{ q }}">
    <select name="category">
        <option value="">全部分類</option>
        {% for c in categories %}
        <option value="{{ c }}" {% if c == category %}selected{% endif %}>{{ c }}</option>
        {% endfor %}
    </select>
    <input type="submit" value="搜尋">
</form>
<p class="sub-links">
    <a class="plain" href="{{ url_for('index') }}">清除搜尋</a> ・
    <a class="plain" href="{{ url_for('export_inventory') }}">匯出庫存 CSV</a>
</p>
<div class="quick-actions">
    <a href="{{ url_for('stock_in') }}"><span class="qa-icon qa-in">⬇</span>入庫登記</a>
    <a href="{{ url_for('stock_out') }}"><span class="qa-icon qa-out">⬆</span>出庫登記</a>
    <a href="{{ url_for('image_search') }}"><span class="qa-icon">📷</span>以圖搜圖</a>
    <a href="{{ url_for('counts_page') }}"><span class="qa-icon">📋</span>循環盤點</a>
    {% if session.get('is_admin') %}
    <a href="{{ url_for('csv_import') }}"><span class="qa-icon">📄</span>CSV 匯入</a>
    {% endif %}
    <a href="{{ url_for('product_new') }}"><span class="qa-icon">➕</span>新增商品</a>
</div>
{% if products %}
<table class="cards">
    <tr><th>SKU</th><th>名稱</th><th>儲位</th><th>別名料號</th><th>分類</th><th class="num">現貨</th><th class="num">可用</th><th>單位</th><th class="num">單價</th><th class="num">低庫存門檻</th><th>供應商</th><th>操作</th></tr>
    {% for p in products %}
    <tr{% if p['low_stock_threshold'] > 0 and p['available'] <= p['low_stock_threshold'] %} class="low-stock"{% endif %}>
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">{{ p['name'] }}</a>{% if p['low_stock_threshold'] > 0 and p['available'] <= p['low_stock_threshold'] %} <span class="badge-low">⚠ 低庫存</span>{% endif %}</td>
        <td data-label="儲位" class="loc-cell">{{ p['location'] or '—' }}</td>
        <td data-label="別名料號" class="alias-cell">{{ p['alias_text'] or '—' }}</td>
        <td data-label="分類">{{ p['category'] }}</td>
        <td data-label="現貨" class="num" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="可用" class="num" id="avail-{{ p['id'] }}">{{ p['available'] }}{% if p['reserved'] %} <span class="resv-note">(預留 {{ p['reserved'] }})</span>{% endif %}</td>
        <td data-label="單位">{{ p['unit'] }}</td>
        <td data-label="單價" class="num">{{ p['unit_price_str'] }}</td>
        <td data-label="低庫存門檻" class="num">{{ p['low_stock_threshold'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
        <td data-label="操作">
            <a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">詳細</a>
            <a class="plain" href="{{ url_for('product_edit', pid=p['id']) }}">編輯</a>
            {% if session.get('is_admin') %}
            <form class="inline" method="post" action="{{ url_for('product_delete', pid=p['id']) }}"
                  onsubmit="return confirm('確定刪除商品「{{ p['name'] }}」?');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
            {% endif %}
        </td>
    </tr>
    {% endfor %}
</table>
{{ pager }}
{% elif q or category %}
<p>查無商品:找不到符合條件的資料。可以試試改用其他公司的別名料號搜尋,或確認關鍵字是否正確。</p>
{% else %}
<p>目前沒有任何商品。<a class="plain" href="{{ url_for('product_new') }}">新增第一筆商品</a>,或用 <a class="plain" href="{{ url_for('csv_import') }}">CSV 匯入</a>整批建檔。</p>
{% endif %}
"""

PAGE_ALERTS = """
<h1>低庫存警示</h1>
{% if products %}
<p>下列商品庫存已達到或低於門檻,請儘快補貨:</p>
<table class="cards">
    <tr><th>SKU</th><th>名稱</th><th>儲位</th><th class="num">現貨</th><th class="num">可用</th><th class="num">低庫存門檻</th><th>單位</th><th>供應商</th></tr>
    {% for p in products %}
    <tr class="low-stock">
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">{{ p['name'] }}</a></td>
        <td data-label="儲位">{{ p['location'] or '—' }}</td>
        <td data-label="現貨" class="num" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="可用" class="num">{{ p['available'] }}{% if p['reserved'] %} <span class="resv-note">(預留 {{ p['reserved'] }})</span>{% endif %}</td>
        <td data-label="低庫存門檻" class="num">{{ p['low_stock_threshold'] }}</td>
        <td data-label="單位">{{ p['unit'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p>目前沒有低庫存商品。</p>
{% endif %}

<div class="detail-section">
    <h2>效期警示</h2>
    {% if expiring %}
    <p class="note">下列批次已過期或將在 30 天內到期,請優先使用或處理:</p>
    <table class="cards">
        <tr><th>批號</th><th>商品</th><th>SKU</th><th class="num">剩餘</th><th>有效期</th><th class="num">剩餘天數</th></tr>
        {% for l in expiring %}
        <tr{% if l['expired'] %} class="low-stock"{% endif %}>
            <td data-label="批號">{{ l['lot_no'] }}</td>
            <td data-label="商品"><a class="plain" href="{{ url_for('product_detail', pid=l['product_id']) }}">{{ l['name'] }}</a></td>
            <td data-label="SKU">{{ l['sku'] }}</td>
            <td data-label="剩餘" class="num">{{ l['qty_remaining'] }} {{ l['unit'] }}</td>
            <td data-label="有效期">{{ l['expiry_date'] }}</td>
            <td data-label="剩餘天數" class="num">{% if l['expired'] %}<strong style="color:#b91c1c">已過期</strong>{% else %}{{ l['days_left'] }} 天{% endif %}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>沒有即將到期的批次(僅統計有設定有效期的批次)。</p>
    {% endif %}
</div>
"""

PAGE_PRODUCT_FORM = """
<h1>{{ title }}</h1>
<form method="post">
    <label>商品名稱 *</label><input type="text" name="name" value="{{ f['name'] }}">
    <label>SKU(商品編號)*</label><input type="text" name="sku" value="{{ f['sku'] }}">
    <label>分類</label><input type="text" name="category" value="{{ f['category'] }}">
    <label>單位</label><input type="text" name="unit" value="{{ f['unit'] }}">
    <label>單價</label><input type="text" name="unit_price" value="{{ f['unit_price'] }}">
    <label>低庫存門檻(0 = 不警示)</label><input type="number" name="low_stock_threshold" min="0" value="{{ f['low_stock_threshold'] }}">
    <label>儲位(料放在哪一架/格)</label><input type="text" name="location" value="{{ f['location'] }}" placeholder="例:A-03-2">
    <label>採購單位(選填,如「箱」)</label><input type="text" name="purchase_unit" value="{{ f['purchase_unit'] }}">
    <label>每採購單位含幾個庫存單位</label><input type="number" name="units_per_purchase" min="1" value="{{ f['units_per_purchase'] }}">
    <label>採購前置期(天,供安全庫存推導)</label><input type="number" name="lead_time_days" min="1" value="{{ f['lead_time_days'] }}">
    <label>目標服務水準(%)</label>
    <select name="service_level">
        {% for lv in [80, 85, 90, 95, 97, 98, 99] %}
        <option value="{{ lv }}" {% if f['service_level']|string == lv|string %}selected{% endif %}>{{ lv }}%</option>
        {% endfor %}
    </select>
    <label>出庫策略</label>
    <select name="issue_strategy">
        <option value="FIFO" {% if f['issue_strategy'] == 'FIFO' %}selected{% endif %}>FIFO 先進先出(依入庫時間)</option>
        <option value="FEFO" {% if f['issue_strategy'] == 'FEFO' %}selected{% endif %}>FEFO 先到期先出(有保存期限的料件)</option>
    </select>
    <label>供應商</label>
    <select name="supplier_id">
        <option value="">(不指定)</option>
        {% for s in supplier_list %}
        <option value="{{ s['id'] }}" {% if f['supplier_id']|string == s['id']|string %}selected{% endif %}>{{ s['name'] }}</option>
        {% endfor %}
    </select>
    <input type="submit" value="儲存">
</form>
<p class="note">庫存數量不在此處修改,請透過「入庫 / 出庫」登記異動。</p>
"""

PAGE_STOCK_FORM = """
<h1>{{ title }}</h1>
{% if product_list %}
<form method="post">
    <label>商品</label>
    <select name="product_id">
        {% for p in product_list %}
        <option value="{{ p['id'] }}" {% if f['product_id']|string == p['id']|string %}selected{% endif %}>{{ p['name'] }}({{ p['sku'] }},目前庫存 {{ p['quantity'] }} {{ p['unit'] }})</option>
        {% endfor %}
    </select>
    <label>數量</label><input type="number" name="quantity" min="1" inputmode="numeric" value="{{ f['quantity'] }}">
    {% if is_in %}
    <label>數量單位</label>
    <select name="qty_unit">
        <option value="stock" {% if f['qty_unit'] != 'purchase' %}selected{% endif %}>庫存單位(直接輸入實際數量)</option>
        <option value="purchase" {% if f['qty_unit'] == 'purchase' %}selected{% endif %}>採購單位(依商品設定的換算率自動換算)</option>
    </select>
    <label>批號(選填,未填自動編號)</label><input type="text" name="lot_no" value="{{ f['lot_no'] }}" placeholder="例:供應商批號">
    <label>有效期(選填,設定後可做 FEFO 與到期警示)</label><input type="date" name="expiry_date" value="{{ f['expiry_date'] }}">
    <label>成本單價(選填,供加權平均成本報表)</label><input type="text" name="unit_cost" value="{{ f['unit_cost'] }}" inputmode="decimal">
    {% endif %}
    <label>用途 / 工單(選填,可於歷史篩選)</label><input type="text" name="purpose" value="{{ f['purpose'] }}" placeholder="例:WO-1001、產線A、維修">
    <label>備註</label><input type="text" name="note" value="{{ f['note'] }}">
    <input type="submit" value="{{ title }}">
    {% if not is_in %}
    <p class="note">出庫依 FIFO 先進先出原則,自動從最早入庫的批次扣減,消耗明細記錄於異動歷史。</p>
    {% endif %}
</form>
{% else %}
<p>目前沒有任何商品,請先<a class="plain" href="{{ url_for('product_new') }}">新增商品</a>。</p>
{% endif %}
"""

PAGE_HISTORY = """
<h1>異動歷史</h1>
<form method="get" class="filters">
    <select name="product_id">
        <option value="">全部商品</option>
        {% for p in product_list %}
        <option value="{{ p['id'] }}" {% if filters['product_id']|string == p['id']|string %}selected{% endif %}>{{ p['name'] }}({{ p['sku'] }})</option>
        {% endfor %}
    </select>
    <select name="type">
        <option value="">入庫+出庫</option>
        <option value="in" {% if filters['type'] == 'in' %}selected{% endif %}>只看入庫</option>
        <option value="out" {% if filters['type'] == 'out' %}selected{% endif %}>只看出庫</option>
    </select>
    起 <input type="date" name="start" value="{{ filters['start'] }}">
    迄 <input type="date" name="end" value="{{ filters['end'] }}">
    <input type="text" name="purpose" placeholder="用途／工單" value="{{ filters['purpose'] }}">
    <input type="submit" value="篩選">
    <a class="plain" href="{{ url_for('history') }}">清除</a>
    &nbsp;|&nbsp;
    <a class="plain" href="{{ url_for('export_transactions', **filters) }}">匯出異動 CSV</a>
</form>
{% if rows %}
<table>
    <tr><th>時間(台灣)</th><th>類型</th><th>商品</th><th>SKU</th><th class="num">數量</th><th>批次</th><th>用途／工單</th><th>備註</th><th>操作人員</th></tr>
    {% for r in rows %}
    <tr>
        <td>{{ r['created_local'] }}</td>
        <td>{% if r['type'] == 'in' %}入庫{% else %}出庫{% endif %}</td>
        <td>{{ r['product_name'] }}</td>
        <td>{{ r['sku'] }}</td>
        <td class="num">{{ r['quantity'] }}</td>
        <td class="alias-cell">{{ r['lot_info'] or '—' }}</td>
        <td>{{ r['purpose'] or '—' }}</td>
        <td>{{ r['note'] }}</td>
        <td>{{ r['username'] }}</td>
    </tr>
    {% endfor %}
</table>
{{ pager }}
{% else %}
<p>沒有符合條件的異動紀錄。</p>
{% endif %}
"""

PAGE_SUPPLIERS = """
<h1>供應商管理</h1>
<p><a class="plain" href="{{ url_for('supplier_new') }}">＋ 新增供應商</a></p>
{% if rows %}
<table>
    <tr><th>名稱</th><th>聯絡人</th><th>電話</th><th>備註</th><th>商品數</th><th>操作</th></tr>
    {% for s in rows %}
    <tr>
        <td>{{ s['name'] }}</td>
        <td>{{ s['contact'] }}</td>
        <td>{{ s['phone'] }}</td>
        <td>{{ s['note'] }}</td>
        <td>{{ s['product_count'] }}</td>
        <td>
            <a class="plain" href="{{ url_for('supplier_edit', sid=s['id']) }}">編輯</a>
            {% if session.get('is_admin') %}
            <form class="inline" method="post" action="{{ url_for('supplier_delete', sid=s['id']) }}"
                  onsubmit="return confirm('確定刪除供應商「{{ s['name'] }}」?其商品的供應商欄位將被清空。');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
            {% endif %}
        </td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p>目前沒有供應商資料。</p>
{% endif %}
"""

PAGE_SUPPLIER_FORM = """
<h1>{{ title }}</h1>
<form method="post">
    <label>供應商名稱 *</label><input type="text" name="name" value="{{ f['name'] }}">
    <label>聯絡人</label><input type="text" name="contact" value="{{ f['contact'] }}">
    <label>電話</label><input type="text" name="phone" value="{{ f['phone'] }}">
    <label>備註</label><input type="text" name="note" value="{{ f['note'] }}">
    <input type="submit" value="儲存">
</form>
"""

PAGE_REPORT = """
<h1>庫存報表</h1>
<form method="get" class="filters">
    起 <input type="date" name="start" value="{{ start }}">
    迄 <input type="date" name="end" value="{{ end }}">
    <input type="submit" value="套用區間">
    <a class="plain" href="{{ url_for('report') }}">清除</a>
</form>
<p class="note">入庫/出庫總量統計{% if start or end %}套用上方日期區間{% else %}為全部期間{% endif %};「目前庫存」「庫存價值」「平均成本」一律為現時狀態。</p>
<table>
    <tr><th>SKU</th><th>名稱</th><th class="num">入庫總量</th><th class="num">出庫總量</th><th class="num">淨變動</th><th class="num">目前庫存</th><th class="num">單價</th><th class="num">平均成本</th><th class="num">庫存價值</th></tr>
    {% for r in rows %}
    <tr>
        <td>{{ r['sku'] }}</td>
        <td>{{ r['name'] }}</td>
        <td class="num" id="in-{{ r['id'] }}">{{ r['total_in'] }}</td>
        <td class="num" id="out-{{ r['id'] }}">{{ r['total_out'] }}</td>
        <td class="num">{{ r['net'] }}</td>
        <td class="num" id="qty-{{ r['id'] }}">{{ r['quantity'] }}</td>
        <td class="num">{{ r['unit_price_str'] }}</td>
        <td class="num">{{ r['avg_cost_str'] }}</td>
        <td class="num" id="value-{{ r['id'] }}">{{ r['value_str'] }}</td>
    </tr>
    {% endfor %}
    <tr>
        <th colspan="2">總計</th>
        <th class="num" id="total-in">{{ total_in }}</th>
        <th class="num" id="total-out">{{ total_out }}</th>
        <th class="num">{{ total_net }}</th>
        <th class="num" id="total-qty">{{ total_qty }}</th>
        <th></th>
        <th></th>
        <th class="num" id="total-value">{{ total_value_str }}</th>
    </tr>
</table>
<p class="note">平均成本為加權平均成本(存貨計價):僅以尚有剩餘且有登記成本的批次計算,「—」表示無成本資料。</p>

<div class="detail-section">
    <h2>庫齡分析(Inventory Aging)</h2>
    <table>
        <tr><th>庫齡區間</th><th class="num">在庫數量</th><th class="num">占比</th></tr>
        {% for b in aging %}
        <tr>
            <td>{{ b['label'] }}</td>
            <td class="num">{{ b['qty'] }}</td>
            <td class="num">{{ b['pct_str'] }}%</td>
        </tr>
        {% endfor %}
    </table>
    <p class="note">依各批次入庫時間計算;90 天以上的在庫批次通常代表呆滯風險,建議優先檢視與去化。</p>
</div>

<div class="detail-section">
    <h2>ABC 分析(柏拉圖法則)</h2>
    <table>
        <tr><th>ABC</th><th>XYZ</th><th>組合</th><th>SKU</th><th>名稱</th><th class="num">庫存價值</th><th class="num">價值占比</th><th class="num">累積占比</th><th class="num">變異係數</th></tr>
        {% for r in abc_rows %}
        <tr>
            <td><strong>{{ r['abc'] }}</strong></td>
            <td>{{ r['xyz'] }}</td>
            <td><strong>{{ r['abc_xyz'] }}</strong></td>
            <td>{{ r['sku'] }}</td>
            <td>{{ r['name'] }}</td>
            <td class="num">{{ r['value_str'] }}</td>
            <td class="num">{{ r['pct_str'] }}%</td>
            <td class="num">{{ r['cum_pct_str'] }}%</td>
            <td class="num">{{ r['cv_str'] }}</td>
        </tr>
        {% endfor %}
    </table>
    <p class="note">
        A 級(累積價值 ≤80%)是最該重點盤點與控管的少數關鍵料號;B 級(≤95%)次之;C 級數量多但價值低,可放寬管理頻率。<br>
        XYZ 依需求變異係數分級:X 穩定(CV&lt;0.5)、Y 中等(0.5–1.0)、Z 高度波動(&gt;1.0)。
        組合的用法:<strong>AX</strong> 可壓低庫存高頻補貨,<strong>AZ</strong> 最棘手(要備量又怕呆滯),
        <strong>CZ</strong> 乾脆多備一點——管理成本高於料件本身。
    </p>
</div>

<div class="detail-section">
    <h2>庫存準確率(帳實相符)</h2>
    {% if accuracy_info %}
    <div class="stat-row">
        <div class="stat-box">
            <div class="stat-num" id="accuracy-value">{{ accuracy_info['accuracy_str'] }}%</div>
            <div class="stat-cap">最近一次盤點的相符比例</div>
        </div>
        <div class="stat-box">
            <div class="stat-num" style="font-size:16px">{{ accuracy_info['name'] }}</div>
            <div class="stat-cap">過帳於 {{ accuracy_info['posted_local'] }}</div>
        </div>
    </div>
    <p class="note">業界基準為 95–99%。低於此區間代表現場作業與系統登記之間有系統性落差,應提高盤點頻率並追查原因。</p>
    {% else %}
    <p>尚無已過帳的盤點單。<a class="plain" href="{{ url_for('counts_page') }}">建立第一張盤點單</a>後,這裡會顯示庫存準確率。</p>
    {% endif %}
</div>
"""

PAGE_PRODUCT_DETAIL = """
<h1>商品詳細:{{ p['name'] }}</h1>
<table class="cards">
    <tr><th>SKU</th><th>儲位</th><th>分類</th><th class="num">現貨</th><th class="num">可用</th><th>單位</th><th class="num">單價</th><th class="num">低庫存門檻</th><th>出庫策略</th><th>供應商</th></tr>
    <tr>
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="儲位">{{ p['location'] or '—' }}</td>
        <td data-label="分類">{{ p['category'] }}</td>
        <td data-label="現貨" class="num" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="可用" class="num">{{ p['available'] }}{% if p['reserved'] %} <span class="resv-note">(預留 {{ p['reserved'] }})</span>{% endif %}</td>
        <td data-label="單位">{{ p['unit'] }}{% if p['purchase_unit'] %}(採購:1 {{ p['purchase_unit'] }} = {{ p['units_per_purchase'] }} {{ p['unit'] }}){% endif %}</td>
        <td data-label="單價" class="num">{{ p['unit_price_str'] }}</td>
        <td data-label="低庫存門檻" class="num">{{ p['low_stock_threshold'] }}</td>
        <td data-label="出庫策略">{{ p['issue_strategy'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
    </tr>
</table>
<div class="qr-row">
    <img class="qr-img" src="{{ url_for('product_qr', pid=p['id']) }}" alt="料號 QR">
    <div>
        <div class="qr-cap">料架標籤 QR</div>
        <p class="note">列印貼在料架上,手機掃碼即可直接開啟本頁登記進出。
        <a class="plain" href="{{ url_for('labels_page') }}">批次列印所有標籤</a></p>
    </div>
</div>
<div class="action-links">
    <a class="primary" href="{{ url_for('stock_in', product_id=p['id']) }}"><span class="qa-in">⬇</span> 入庫</a>
    <a class="primary" href="{{ url_for('stock_out', product_id=p['id']) }}"><span class="qa-out">⬆</span> 出庫</a>
    <a href="{{ url_for('product_edit', pid=p['id']) }}">編輯基本資料</a>
    <a href="{{ url_for('history', product_id=p['id']) }}">完整異動歷史</a>
</div>

<div class="detail-section">
    <h2>照片</h2>
    {% if images %}
    <div class="photo-wall">
        {% for img in images %}
        <div class="photo-item">
            <img src="{{ url_for('serve_image', filename=img['filename']) }}" alt="{{ p['name'] }}">
            {% if session.get('is_admin') %}
            <form class="inline" method="post" action="{{ url_for('image_delete', pid=p['id'], img_id=img['id']) }}"
                  onsubmit="return confirm('確定刪除這張照片?');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p>尚未上傳照片。</p>
    {% endif %}
    <form method="post" enctype="multipart/form-data" action="{{ url_for('image_upload', pid=p['id']) }}">
        <input type="file" name="photo" accept="image/*">
        <input type="submit" value="上傳照片">
    </form>
</div>

<div class="detail-section">
    <h2>跨公司料號對照</h2>
    {% if aliases %}
    <table>
        <tr><th>公司</th><th>該公司料號</th><th>備註</th><th>操作</th></tr>
        {% for a in aliases %}
        <tr>
            <td>{{ a['company'] }}</td>
            <td>{{ a['alias_sku'] }}</td>
            <td>{{ a['note'] }}</td>
            <td>
                {% if session.get('is_admin') %}
                <form class="inline" method="post" action="{{ url_for('alias_delete', pid=p['id'], aid=a['id']) }}"
                      onsubmit="return confirm('確定刪除別名「{{ a['company'] }}:{{ a['alias_sku'] }}」?');">
                    <button class="small-btn" type="submit">刪除</button>
                </form>
                {% else %}—{% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>尚無別名料號。不同公司對同一物料的料號都可以登記在這裡,搜尋時任一料號都找得到。</p>
    {% endif %}
    <form method="post" action="{{ url_for('alias_add', pid=p['id']) }}">
        <label>公司名稱</label><input type="text" name="company">
        <label>該公司料號</label><input type="text" name="alias_sku">
        <label>備註</label><input type="text" name="note">
        <input type="submit" value="新增別名">
    </form>
</div>

<div class="detail-section">
    <h2>批次庫存(FIFO 先進先出)</h2>
    {% if lots %}
    <table class="cards">
        <tr><th>批號</th><th>入庫時間(台灣)</th><th class="num">庫齡(天)</th><th>有效期</th><th class="num">剩餘 / 原始</th><th class="num">成本單價</th><th>備註</th></tr>
        {% for l in lots %}
        <tr{% if l['qty_remaining'] == 0 %} class="lot-empty"{% endif %}>
            <td data-label="批號">{{ l['lot_no'] }}</td>
            <td data-label="入庫時間">{{ l['received_local'] }}</td>
            <td data-label="庫齡(天)" class="num">{{ l['age_days'] }}</td>
            <td data-label="有效期">{{ l['expiry_date'] or '—' }}</td>
            <td data-label="剩餘/原始" class="num">{{ l['qty_remaining'] }} / {{ l['qty_received'] }}</td>
            <td data-label="成本單價" class="num">{{ l['cost_str'] }}</td>
            <td data-label="備註">{{ l['note'] }}</td>
        </tr>
        {% endfor %}
    </table>
    <p class="note">出庫依 FIFO 先進先出原則自動從最早批次扣減;各筆出庫的批次消耗明細見異動歷史。</p>
    {% else %}
    <p>尚無批次紀錄,入庫後會自動建立批次。</p>
    {% endif %}
</div>

<div class="detail-section">
    <h2>近期異動</h2>
    {% if recent_tx %}
    <table>
        <tr><th>時間(台灣)</th><th>類型</th><th>數量</th><th>備註</th><th>操作人員</th></tr>
        {% for r in recent_tx %}
        <tr>
            <td>{{ r['created_local'] }}</td>
            <td>{% if r['type'] == 'in' %}入庫{% else %}出庫{% endif %}</td>
            <td>{{ r['quantity'] }}</td>
            <td>{{ r['note'] }}</td>
            <td>{{ r['username'] }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>尚無異動紀錄。</p>
    {% endif %}
</div>
"""

PAGE_USERS = """
<h1>帳號管理</h1>
<table class="cards">
    <tr><th>帳號</th><th>角色</th><th>建立時間</th><th>操作</th></tr>
    {% for u in users %}
    <tr>
        <td data-label="帳號">{{ u['username'] }}</td>
        <td data-label="角色">{% if u['is_admin'] %}管理員{% else %}一般使用者{% endif %}</td>
        <td data-label="建立時間">{{ u['created_local'] }}</td>
        <td data-label="操作">
            <form class="inline" method="post" action="{{ url_for('user_delete', uid=u['id']) }}"
                  onsubmit="return confirm('確定刪除帳號「{{ u['username'] }}」?');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
        </td>
    </tr>
    {% endfor %}
</table>

<div class="detail-section">
    <h2>新增帳號</h2>
    <form method="post" action="{{ url_for('user_new') }}">
        <label>帳號</label><input type="text" name="username">
        <label>密碼(至少 8 碼)</label><input type="password" name="password">
        <label><input type="checkbox" name="is_admin" value="1"> 設為管理員(可刪除資料、CSV 匯入、管理帳號)</label>
        <input type="submit" value="建立帳號">
    </form>
</div>

<div class="detail-section">
    <h2>重設密碼</h2>
    <form method="post" action="{{ url_for('user_password') }}">
        <label>選擇帳號</label>
        <select name="user_id">
            {% for u in users %}
            <option value="{{ u['id'] }}">{{ u['username'] }}</option>
            {% endfor %}
        </select>
        <label>新密碼(至少 8 碼)</label><input type="password" name="password">
        <input type="submit" value="重設密碼">
    </form>
    <p class="note">同事忘記密碼時由管理員在此重設。系統不開放自助註冊,新同事的帳號請用上方表單建立。</p>
</div>
"""

PAGE_AUDIT = """
<h1>稽核軌跡</h1>
<p class="note">記錄商品、供應商、別名、照片的建檔維護,以及 CSV 匯入與帳號管理等操作,供事後追查。</p>
<form method="get" class="filters">
    <input type="text" name="q" placeholder="搜尋操作者或內容" value="{{ q }}">
    <input type="submit" value="搜尋">
    <a class="plain" href="{{ url_for('audit_page') }}">清除</a>
</form>
{% if rows %}
<table>
    <tr><th>時間(台灣)</th><th>操作者</th><th>動作</th><th>對象</th><th>內容</th></tr>
    {% for r in rows %}
    <tr>
        <td>{{ r['created_local'] }}</td>
        <td>{{ r['username'] }}</td>
        <td>{{ r['action'] }}</td>
        <td>{{ r['target_type'] }}{% if r['target_id'] %} #{{ r['target_id'] }}{% endif %}</td>
        <td>{{ r['detail'] }}</td>
    </tr>
    {% endfor %}
</table>
{{ pager }}
{% else %}
<p>目前沒有稽核紀錄。</p>
{% endif %}
"""

PAGE_COUNTS = """
<h1>循環盤點</h1>
<p class="note">
    業界實務:依 ABC 分級滾動盤點(A 類每週、B 類每月、C 類每季),而非一年一次大盤。
    研究顯示未持續盤點的系統,帳面會單向偏離且不會自行修正。
</p>

{% if session.get('is_admin') %}
<div class="detail-section">
    <h2>建立盤點單</h2>
    <form method="post" action="{{ url_for('count_new') }}">
        <label>盤點單名稱</label><input type="text" name="name" placeholder="例:{{ today }} A類週盤">
        <label>盤點範圍</label>
        <select name="scope">
            <option value="all">全部商品</option>
            <option value="A">僅 A 類(高價值,建議每週)</option>
            <option value="B">僅 B 類(建議每月)</option>
            <option value="C">僅 C 類(建議每季)</option>
            <option value="category">指定分類</option>
        </select>
        <label>分類(範圍選「指定分類」時適用)</label>
        <select name="category">
            <option value="">(不指定)</option>
            {% for c in categories %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
        </select>
        <input type="submit" value="建立盤點單">
    </form>
</div>
{% endif %}

<div class="detail-section">
    <h2>盤點單列表</h2>
    {% if rows %}
    <table class="cards">
        <tr><th>名稱</th><th>範圍</th><th>建立時間</th><th>建立者</th><th>狀態</th><th class="num">準確率</th><th>操作</th></tr>
        {% for r in rows %}
        <tr>
            <td data-label="名稱">{{ r['name'] }}</td>
            <td data-label="範圍">{{ r['scope'] }}</td>
            <td data-label="建立時間">{{ r['created_local'] }}</td>
            <td data-label="建立者">{{ r['username'] }}</td>
            <td data-label="狀態">{% if r['status'] == 'posted' %}<span class="chip-posted">已過帳</span>{% else %}<span class="chip-open">盤點中</span>{% endif %}</td>
            <td data-label="準確率" class="num">{% if r['accuracy'] is not none %}{{ r['accuracy_str'] }}%{% else %}—{% endif %}</td>
            <td data-label="操作"><a class="plain" href="{{ url_for('count_detail', cid=r['id']) }}">開啟</a></td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>尚無盤點單。{% if session.get('is_admin') %}用上方表單建立第一張。{% else %}請洽管理員建立。{% endif %}</p>
    {% endif %}
</div>
"""

PAGE_COUNT_DETAIL = """
<h1>盤點單:{{ c['name'] }}</h1>
<p class="note">
    範圍 {{ c['scope'] }}・建立於 {{ c['created_local'] }}({{ c['username'] }})・
    {% if c['status'] == 'posted' %}<strong>已於 {{ c['posted_local'] }} 過帳,準確率 {{ c['accuracy_str'] }}%</strong>
    {% else %}狀態:盤點中(輸入實盤數後由管理員過帳修正庫存){% endif %}
</p>

<div class="stat-row">
    <div class="stat-box"><div class="stat-num">{{ total }}</div><div class="stat-cap">盤點品項</div></div>
    <div class="stat-box"><div class="stat-num">{{ counted }}</div><div class="stat-cap">已盤</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#b91c1c">{{ diff_count }}</div><div class="stat-cap">有差異</div></div>
</div>

<table class="cards">
    <tr><th>SKU</th><th>名稱</th><th>儲位</th><th class="num">系統帳</th><th class="num">實盤數</th><th class="num">差異</th><th>備註</th></tr>
    {% for i in items %}
    <tr{% if i['diff'] is not none and i['diff'] != 0 %} class="has-diff"{% endif %}>
        <td data-label="SKU">{{ i['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=i['product_id']) }}">{{ i['name'] }}</a></td>
        <td data-label="儲位">{{ i['location'] or '—' }}</td>
        <td data-label="系統帳" class="num">{{ i['system_qty'] }}</td>
        <td data-label="實盤數" class="num">
            {% if c['status'] == 'posted' %}{{ i['counted_qty'] if i['counted_qty'] is not none else '—' }}
            {% else %}
            <form class="inline count-form" method="post" action="{{ url_for('count_record', cid=c['id']) }}">
                <input type="hidden" name="product_id" value="{{ i['product_id'] }}">
                <input type="number" name="counted_qty" min="0" inputmode="numeric" class="count-input"
                       value="{{ i['counted_qty'] if i['counted_qty'] is not none else '' }}">
                <input type="text" name="note" class="count-note" placeholder="差異原因" value="{{ i['note'] }}">
                <button class="small-btn ok-btn" type="submit">記錄</button>
            </form>
            {% endif %}
        </td>
        <td data-label="差異" class="num">{% if i['diff'] is not none %}{{ '%+d' % i['diff'] }}{% else %}—{% endif %}</td>
        <td data-label="備註">{{ i['note'] }}</td>
    </tr>
    {% endfor %}
</table>

{% if c['status'] != 'posted' and session.get('is_admin') %}
<div class="detail-section">
    <h2>過帳</h2>
    <p class="note">
        過帳會依實盤數修正庫存:盤虧依出庫策略消耗批次、盤盈建立調整批,並產生「盤點調整」異動與稽核紀錄。
        未填實盤數的品項會被略過。過帳後不可再修改。
    </p>
    <form method="post" action="{{ url_for('count_post', cid=c['id']) }}"
          onsubmit="return confirm('確定過帳?將依實盤數修正 {{ diff_count }} 項商品的庫存,且不可復原。');">
        <input type="submit" value="過帳並修正庫存">
    </form>
</div>
{% endif %}
"""

PAGE_RESERVATIONS = """
<h1>庫存預留</h1>
<p class="note">
    預留讓「已被承諾出去」的數量從可用量中扣除,避免兩個人同時把同一批料承諾給不同用途。
    現貨量不受影響——實際領走時才走出庫。
</p>

<div class="detail-section">
    <h2>建立預留</h2>
    <form method="post" action="{{ url_for('reservation_new') }}">
        <label>商品</label>
        <select name="product_id">
            {% for p in product_list %}
            <option value="{{ p['id'] }}">{{ p['name'] }}({{ p['sku'] }},可用 {{ p['available'] }} {{ p['unit'] }})</option>
            {% endfor %}
        </select>
        <label>預留數量</label><input type="number" name="quantity" min="1" inputmode="numeric">
        <label>用途(工單／專案／客戶)</label><input type="text" name="purpose" placeholder="例:WO-1001">
        <input type="submit" value="建立預留">
    </form>
</div>

<div class="detail-section">
    <h2>有效預留</h2>
    {% if rows %}
    <table class="cards">
        <tr><th>商品</th><th>SKU</th><th class="num">預留量</th><th>用途</th><th>建立者</th><th>建立時間</th><th>操作</th></tr>
        {% for r in rows %}
        <tr>
            <td data-label="商品">{{ r['name'] }}</td>
            <td data-label="SKU">{{ r['sku'] }}</td>
            <td data-label="預留量" class="num">{{ r['quantity'] }}</td>
            <td data-label="用途">{{ r['purpose'] or '—' }}</td>
            <td data-label="建立者">{{ r['username'] }}</td>
            <td data-label="建立時間">{{ r['created_local'] }}</td>
            <td data-label="操作">
                <form class="inline" method="post" action="{{ url_for('reservation_release', rid=r['id']) }}">
                    <button class="small-btn ok-btn" type="submit">釋放</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>目前沒有有效的預留。</p>
    {% endif %}
</div>
"""

PAGE_PLANNING = """
<h1>存貨規劃:安全庫存建議</h1>
<div class="import-help">
    <p>
        低庫存門檻不該憑印象填。系統以最近 {{ window }} 天的實際出庫資料算出<strong>日均用量</strong>與
        <strong>標準差</strong>,套安全庫存公式推導建議值:
    </p>
    <p><code>安全庫存 = Z × 用量標準差 × √前置期</code>,<code>再訂購點 = 日均用量 × 前置期 + 安全庫存</code></p>
    <p>
        Z 由該商品的<strong>目標服務水準</strong>決定(95% → Z=1.65),前置期與服務水準可在商品編輯頁調整。
        沒有出庫歷史的商品無法推導,顯示「—」。
    </p>
</div>

<table class="cards">
    <tr>
        <th>SKU</th><th>名稱</th><th class="num">日均用量</th><th class="num">標準差</th>
        <th class="num">前置期</th><th class="num">服務水準</th>
        <th class="num">建議安全庫存</th><th class="num">再訂購點</th><th class="num">目前門檻</th><th>XYZ</th>
    </tr>
    {% for r in rows %}
    <tr>
        <td data-label="SKU">{{ r['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=r['id']) }}">{{ r['name'] }}</a></td>
        <td data-label="日均用量" class="num">{{ r['mean_str'] }}</td>
        <td data-label="標準差" class="num">{{ r['sd_str'] }}</td>
        <td data-label="前置期" class="num">{{ r['lead_time_days'] }} 天</td>
        <td data-label="服務水準" class="num">{{ r['service_level_str'] }}%</td>
        <td data-label="建議安全庫存" class="num"><strong>{{ r['ss_str'] }}</strong></td>
        <td data-label="再訂購點" class="num">{{ r['rop_str'] }}</td>
        <td data-label="目前門檻" class="num">{{ r['low_stock_threshold'] }}</td>
        <td data-label="XYZ">{{ r['xyz'] }}</td>
    </tr>
    {% endfor %}
</table>

{% if has_suggestion and session.get('is_admin') %}
<div class="detail-section">
    <h2>套用建議</h2>
    <p class="note">將所有可推導商品的低庫存門檻,一次更新為上表的建議安全庫存。個別商品仍可在編輯頁手動調整。</p>
    <form method="post" action="{{ url_for('planning_apply') }}"
          onsubmit="return confirm('確定將建議值套用到所有可推導的商品門檻?');">
        <input type="submit" value="一鍵套用建議門檻">
    </form>
</div>
{% endif %}
"""

PAGE_LABELS = """
<h1>料架標籤列印</h1>
<p class="note no-print">
    列印後貼在料架上,現場用手機掃 QR 即可直接開啟該料號頁面登記進出,不必打字找料號。
    按瀏覽器的列印功能(Ctrl+P / 手機分享選單)即可輸出。
</p>
{% if not has_qrcode %}
<div class="msg error">此功能需要安裝 qrcode 套件(pip install qrcode)後重新啟動系統。</div>
{% else %}
<div class="label-sheet">
    {% for p in products %}
    <div class="label">
        <img src="{{ url_for('product_qr', pid=p['id']) }}" alt="QR">
        <div class="label-text">
            <div class="label-sku">{{ p['sku'] }}</div>
            <div class="label-name">{{ p['name'] }}</div>
            <div class="label-loc">儲位:{{ p['location'] or '未設定' }}</div>
        </div>
    </div>
    {% endfor %}
</div>
{% endif %}
"""

PAGE_IMAGE_SEARCH = """
<h1>以圖搜圖</h1>
<p>上傳一張物料照片,系統會比對庫內所有照片,列出外觀最相似的料號。</p>
{% if not has_pil %}
<div class="msg error">此功能需要安裝 Pillow 套件(pip install Pillow)後重新啟動系統。</div>
{% else %}
<form method="post" enctype="multipart/form-data">
    <input type="file" name="photo" accept="image/*">
    <input type="submit" value="搜尋相似物料">
</form>
{% endif %}
{% if results is not none %}
<div class="detail-section">
    <h2>搜尋結果(相似度由高至低)</h2>
    {% if results %}
    <table>
        <tr><th>照片</th><th>SKU</th><th>名稱</th><th>相似度</th><th>目前庫存</th></tr>
        {% for r in results %}
        <tr>
            <td><img class="thumb" src="{{ url_for('serve_image', filename=r['filename']) }}" alt=""></td>
            <td>{{ r['sku'] }}</td>
            <td><a class="plain" href="{{ url_for('product_detail', pid=r['product_id']) }}">{{ r['name'] }}</a></td>
            <td>{{ r['similarity'] }}%</td>
            <td>{{ r['quantity'] }} {{ r['unit'] }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p>庫內尚無照片可比對,請先到商品詳細頁上傳物料照片。</p>
    {% endif %}
</div>
{% endif %}
"""

PAGE_IMPORT = """
<h1>CSV 大量匯入</h1>
<div class="import-help">
    <p><strong>商品匯入</strong>欄位順序(第一列為標題列,會被略過):<br>
    <code>SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存</code><br>
    SKU 與名稱必填,其餘可留空;供應商不存在時自動建立;初始庫存會寫成一筆入庫異動(備註「CSV匯入」)。</p>
    <p><strong>別名匯入</strong>欄位順序:<br>
    <code>我方SKU,公司,別名料號,備註</code></p>
    <p>檔案編碼支援 UTF-8 與 Big5(台灣 Excel 另存 CSV 的預設編碼),系統自動判斷。</p>
</div>
<form method="post" enctype="multipart/form-data">
    <label>匯入類型</label>
    <select name="mode">
        <option value="products">商品匯入</option>
        <option value="aliases">別名匯入</option>
    </select>
    <label>CSV 檔案</label><input type="file" name="csv_file" accept=".csv,text/csv">
    <input type="submit" value="開始匯入">
</form>
{% if report_rows is not none %}
<div class="detail-section">
    <h2>匯入結果:成功匯入 {{ ok_count }} 筆,跳過 {{ skip_count }} 筆</h2>
    <table>
        <tr><th>行號</th><th>內容</th><th>結果</th></tr>
        {% for r in report_rows %}
        <tr><td>{{ r['line'] }}</td><td>{{ r['label'] }}</td><td>{{ r['status'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endif %}
"""


# ---------------------------------------------------------------------------
# 帳號:註冊(僅首位)/ 登入 / 登出 / 帳號管理
# ---------------------------------------------------------------------------

MIN_PASSWORD_LEN = 8
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SEC = 300
_login_fails = {}  # username -> (失敗次數, 最後一次失敗時間);程序內記憶,重啟即清空


def check_password_policy(password):
    if len(password) < MIN_PASSWORD_LEN:
        return f"密碼至少 {MIN_PASSWORD_LEN} 碼,請重新設定"
    return None


def user_count():
    return get_db().execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def create_user(username, password, is_admin):
    # 共用建帳邏輯(首位註冊與管理員新增帳號都走這裡)
    get_db().execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, generate_password_hash(password), 1 if is_admin else 0, now_str()),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    # 只開放給「系統第一位使用者」建立管理員帳號;之後帳號一律由管理員在 /users 新增,
    # 避免任何連得到內網的人自行建帳進入系統。
    error = None
    username = ""
    if user_count() > 0:
        return render_page(PAGE_REGISTER, closed=True,
                           error="系統已完成初始設定,不開放自助註冊。需要帳號請洽管理員建立。")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "帳號與密碼不可為空"
        else:
            error = check_password_policy(password)
            if not error:
                db = get_db()
                try:
                    create_user(username, password, is_admin=True)  # 首位即管理員
                    db.commit()
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    error = "帳號已存在,請改用其他名稱"
    return render_page(PAGE_REGISTER, error=error, username=username, closed=False)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        fails, last = _login_fails.get(username, (0, 0.0))
        if fails >= LOGIN_MAX_FAILS and (time.time() - last) < LOGIN_LOCK_SEC:
            remain = int((LOGIN_LOCK_SEC - (time.time() - last)) / 60) + 1
            error = f"嘗試次數過多,請於約 {remain} 分鐘後再試"
        else:
            if fails >= LOGIN_MAX_FAILS:
                _login_fails.pop(username, None)  # 鎖定期已過,重新計數
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if user and check_password_hash(user["password_hash"], password):
                _login_fails.pop(username, None)
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["is_admin"] = bool(user["is_admin"])  # 權限判斷依據
                return redirect(url_for("index"))
            prev = _login_fails.get(username, (0, 0.0))[0]
            _login_fails[username] = (prev + 1, time.time())
            error = "帳號或密碼錯誤"
    return render_page(PAGE_LOGIN, error=error, username=username)


@app.route("/users")
@admin_required
def users_page(error=None, msg=None):
    rows = []
    for u in get_db().execute("SELECT * FROM users ORDER BY id").fetchall():
        d = dict(u)
        d["created_local"] = fmt_local(u["created_at"])
        rows.append(d)
    return render_page(PAGE_USERS, users=rows, error=error, msg=msg)


@app.route("/users/new", methods=["POST"])
@admin_required
def user_new():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    is_admin = bool(request.form.get("is_admin"))
    if not username or not password:
        return users_page(error="帳號與密碼不可為空")
    policy_err = check_password_policy(password)
    if policy_err:
        return users_page(error=policy_err)
    db = get_db()
    try:
        create_user(username, password, is_admin)
        audit("新增帳號", "帳號", username, "管理員" if is_admin else "一般使用者")
        db.commit()
    except sqlite3.IntegrityError:
        return users_page(error="帳號已存在,請改用其他名稱")
    return redirect(url_for("users_page"))


@app.route("/users/password", methods=["POST"])
@admin_required
def user_password():
    uid = safe_int(request.form.get("user_id", ""))
    password = request.form.get("password", "")
    if uid is None:
        return users_page(error="請選擇要重設密碼的帳號")
    policy_err = check_password_policy(password)
    if policy_err:
        return users_page(error=policy_err)
    db = get_db()
    row = db.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None:
        return users_page(error="找不到指定的帳號")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash(password), uid))
    _login_fails.pop(row["username"], None)  # 重設密碼同時解除鎖定
    audit("重設密碼", "帳號", row["username"])
    db.commit()
    return users_page(msg=f"已重設 {row['username']} 的密碼")


@app.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def user_delete(uid):
    db = get_db()
    if uid == session.get("user_id"):
        return users_page(error="不可刪除自己的帳號")
    row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if row is None:
        return users_page(error="找不到指定的帳號")
    if row["is_admin"]:
        admins = db.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin = 1").fetchone()["c"]
        if admins <= 1:
            return users_page(error="不可刪除最後一位管理員")
    # 保留其異動歷史(transactions.user_id 外鍵),僅停用帳號:改名並鎖定密碼
    has_tx = db.execute("SELECT COUNT(*) AS c FROM transactions WHERE user_id = ?",
                        (uid,)).fetchone()["c"] > 0
    if has_tx:
        db.execute("UPDATE users SET username = ?, password_hash = ?, is_admin = 0 WHERE id = ?",
                   (f"{row['username']}(已停用)", generate_password_hash(secrets.token_hex(16)), uid))
        audit("停用帳號", "帳號", row["username"], "有異動紀錄,保留歷史故改為停用")
    else:
        db.execute("DELETE FROM users WHERE id = ?", (uid,))
        audit("刪除帳號", "帳號", row["username"])
    db.commit()
    return redirect(url_for("users_page"))


@app.route("/audit")
@admin_required
def audit_page():
    q = request.args.get("q", "").strip()
    page = max(1, safe_int(request.args.get("page", "1"), 1) or 1)
    per = 200
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if q:
        sql += " AND (username LIKE ? OR action LIKE ? OR detail LIKE ? OR target_type LIKE ?)"
        params += [f"%{q}%"] * 4
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [per + 1, (page - 1) * per]
    fetched = get_db().execute(sql, params).fetchall()
    has_next = len(fetched) > per
    rows = []
    for r in fetched[:per]:
        d = dict(r)
        d["created_local"] = fmt_local(r["created_at"])
        rows.append(d)
    return render_page(PAGE_AUDIT, rows=rows, q=q,
                       pager=build_pager("audit_page", page, has_next, q=q))


# 登出用 GET 是為了 curl 可測性的刻意簡化;本系統未實作 CSRF token,
# 屬已知取捨(內部工具、無跨站表單情境),部署對外時應補上。
@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# 庫存總覽(首頁)與低庫存警示
# ---------------------------------------------------------------------------

def query_products(q="", category="", limit=None, offset=0):
    # 搜尋同時比對我方 SKU、名稱與各公司別名料號(跨公司料號整合的核心)
    sql = """
        SELECT p.*, s.name AS supplier_name,
               (SELECT GROUP_CONCAT(a.company || ':' || a.alias_sku, ' / ')
                FROM part_aliases a WHERE a.product_id = p.id) AS alias_text
        FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE 1=1
    """
    params = []
    if q:
        sql += """ AND (p.name LIKE ? OR p.sku LIKE ? OR p.location LIKE ? OR EXISTS (
                     SELECT 1 FROM part_aliases a WHERE a.product_id = p.id
                       AND (a.alias_sku LIKE ? OR a.company LIKE ?)))"""
        params += [f"%{q}%"] * 5
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    sql += " ORDER BY p.id"
    if limit is not None:      # 匯出端點傳 limit=None 取得完整資料
        sql += " LIMIT ? OFFSET ?"
        params += [limit + 1, offset]   # 多取一筆用來判斷是否還有下一頁
    rows = [dict(r) for r in get_db().execute(sql, params).fetchall()]
    resv = reserved_map()
    for r in rows:
        r["unit_price_str"] = fmt_money(r["unit_price"])
        r["reserved"] = resv.get(r["id"], 0)
        r["available"] = r["quantity"] - r["reserved"]   # 業界的 on-hand vs available 區分
    return rows


INDEX_PER_PAGE = 100


def render_index(error=None, msg=None):
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page = max(1, safe_int(request.args.get("page", "1"), 1) or 1)
    db = get_db()
    fetched = query_products(q, category, limit=INDEX_PER_PAGE,
                             offset=(page - 1) * INDEX_PER_PAGE)
    has_next = len(fetched) > INDEX_PER_PAGE
    products = fetched[:INDEX_PER_PAGE]
    categories = [r["category"] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE category != '' ORDER BY category"
    ).fetchall()]
    # banner 計數同樣以可用量為準,與警示頁一致
    resv_all = reserved_map()
    low_count = sum(1 for r in db.execute(
        "SELECT id, quantity, low_stock_threshold FROM products WHERE low_stock_threshold > 0"
    ).fetchall() if (r["quantity"] - resv_all.get(r["id"], 0)) <= r["low_stock_threshold"])
    return render_page(PAGE_INDEX, products=products, q=q, category=category,
                       categories=categories, low_count=low_count,
                       pager=build_pager("index", page, has_next, q=q, category=category),
                       error=error, msg=msg)


@app.route("/")
@login_required
def index():
    return render_index()


@app.route("/alerts")
@login_required
def alerts():
    db = get_db()
    resv = reserved_map()
    rows = []
    # 低庫存以「可用量」判斷:已被預留的量不該算成可動用庫存
    for r in db.execute("""
            SELECT p.*, s.name AS supplier_name
            FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.low_stock_threshold > 0
            ORDER BY p.quantity ASC
        """).fetchall():
        d = dict(r)
        d["reserved"] = resv.get(r["id"], 0)
        d["available"] = r["quantity"] - d["reserved"]
        if d["available"] <= r["low_stock_threshold"]:
            rows.append(d)
    # 即將到期批次(30 天內)與已過期批次:FEFO 料件的呆滯與報廢風險
    horizon = (today_local() + timedelta(days=30)).isoformat()
    today = today_local().isoformat()
    expiring = []
    for r in db.execute("""
            SELECT l.*, p.name, p.sku, p.unit FROM lots l JOIN products p ON l.product_id = p.id
            WHERE l.qty_remaining > 0 AND l.expiry_date != '' AND l.expiry_date <= ?
            ORDER BY l.expiry_date
        """, (horizon,)).fetchall():
        d = dict(r)
        d["expired"] = r["expiry_date"] < today
        try:
            d["days_left"] = (datetime.strptime(r["expiry_date"], "%Y-%m-%d").date()
                              - today_local()).days
        except ValueError:
            d["days_left"] = 0
        expiring.append(d)
    return render_page(PAGE_ALERTS, products=rows, expiring=expiring)


# ---------------------------------------------------------------------------
# 商品管理
# ---------------------------------------------------------------------------

def parse_product_form():
    # 回傳 (欄位 dict, 錯誤訊息或 None)
    f = {
        "name": request.form.get("name", "").strip(),
        "sku": request.form.get("sku", "").strip(),
        "category": request.form.get("category", "").strip(),
        "unit": request.form.get("unit", "").strip() or "個",
        "unit_price": request.form.get("unit_price", "").strip() or "0",
        "low_stock_threshold": request.form.get("low_stock_threshold", "").strip() or "0",
        "supplier_id": request.form.get("supplier_id", "").strip(),
        "location": request.form.get("location", "").strip(),
        "purchase_unit": request.form.get("purchase_unit", "").strip(),
        "units_per_purchase": request.form.get("units_per_purchase", "").strip() or "1",
        "lead_time_days": request.form.get("lead_time_days", "").strip() or "7",
        "service_level": request.form.get("service_level", "").strip() or "95",
        "issue_strategy": request.form.get("issue_strategy", "FIFO").strip(),
    }
    if not f["name"] or not f["sku"]:
        return f, "商品名稱與 SKU 不可為空"
    upp = safe_int(f["units_per_purchase"])
    if upp is None or upp < 1 or upp > MAX_QUANTITY:
        return f, "每採購單位的換算數量必須為 1 以上的整數"
    f["upp_val"] = upp
    lead = safe_int(f["lead_time_days"])
    if lead is None or lead < 1 or lead > 3650:
        return f, "採購前置期必須為 1~3650 天"
    f["lead_val"] = lead
    try:
        f["service_val"] = float(f["service_level"])
        if not math.isfinite(f["service_val"]) or not (50 <= f["service_val"] <= 99.9):
            raise ValueError
    except (ValueError, TypeError):
        return f, "服務水準必須介於 50 與 99.9 之間"
    if f["issue_strategy"] not in ("FIFO", "FEFO"):
        f["issue_strategy"] = "FIFO"
    try:
        f["unit_price_val"] = float(f["unit_price"])
        # math.isfinite 擋掉 inf / nan:否則會污染報表金額與 ABC 分級
        if not math.isfinite(f["unit_price_val"]) or f["unit_price_val"] < 0:
            raise ValueError
        if f["unit_price_val"] > MAX_QUANTITY:
            return f, "單價過大,請確認輸入"
    except (ValueError, TypeError, OverflowError):
        return f, "單價必須為有效的非負數字"
    try:
        f["threshold_val"] = int(f["low_stock_threshold"])
        if f["threshold_val"] < 0:
            raise ValueError
        if f["threshold_val"] > MAX_QUANTITY:
            return f, "低庫存門檻過大,請確認輸入"
    except (ValueError, TypeError, OverflowError):
        return f, "低庫存門檻必須為非負整數"
    f["supplier_val"] = safe_int(f["supplier_id"])
    return f, None


def supplier_options():
    return get_db().execute("SELECT id, name FROM suppliers ORDER BY name").fetchall()


EMPTY_PRODUCT_FORM = {"name": "", "sku": "", "category": "", "unit": "個",
                      "unit_price": "0", "low_stock_threshold": "0", "supplier_id": "",
                      "location": "", "purchase_unit": "", "units_per_purchase": "1",
                      "lead_time_days": "7", "service_level": "95", "issue_strategy": "FIFO"}


@app.route("/products/new", methods=["GET", "POST"])
@login_required
def product_new():
    f = dict(EMPTY_PRODUCT_FORM)
    error = None
    if request.method == "POST":
        f, error = parse_product_form()
        if not error:
            db = get_db()
            try:
                cur = db.execute("""
                    INSERT INTO products (name, sku, category, unit, unit_price,
                                          low_stock_threshold, supplier_id, created_at,
                                          location, purchase_unit, units_per_purchase,
                                          lead_time_days, service_level, issue_strategy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (f["name"], f["sku"], f["category"], f["unit"], f["unit_price_val"],
                      f["threshold_val"], f["supplier_val"], now_str(),
                      f["location"], f["purchase_unit"], f["upp_val"],
                      f["lead_val"], f["service_val"], f["issue_strategy"]))
                audit("新增商品", "商品", cur.lastrowid, f"{f['sku']} {f['name']}")
                db.commit()
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "SKU 已存在,請改用其他編號"
    return render_page(PAGE_PRODUCT_FORM, title="新增商品", f=f,
                       supplier_list=supplier_options(), error=error)


@app.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def product_edit(pid):
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return render_index(error="找不到指定的商品")
    error = None
    if request.method == "POST":
        f, error = parse_product_form()
        if not error:
            try:
                db.execute("""
                    UPDATE products SET name=?, sku=?, category=?, unit=?, unit_price=?,
                                        low_stock_threshold=?, supplier_id=?, location=?,
                                        purchase_unit=?, units_per_purchase=?,
                                        lead_time_days=?, service_level=?, issue_strategy=?
                    WHERE id=?
                """, (f["name"], f["sku"], f["category"], f["unit"], f["unit_price_val"],
                      f["threshold_val"], f["supplier_val"], f["location"],
                      f["purchase_unit"], f["upp_val"], f["lead_val"],
                      f["service_val"], f["issue_strategy"], pid))
                audit("編輯商品", "商品", pid,
                      f"{f['sku']} {f['name']} 單價={f['unit_price_val']} 門檻={f['threshold_val']}")
                db.commit()
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "SKU 已存在,請改用其他編號"
    else:
        f = {"name": row["name"], "sku": row["sku"], "category": row["category"],
             "unit": row["unit"], "unit_price": fmt_num(row["unit_price"]),
             "low_stock_threshold": str(row["low_stock_threshold"]),
             "supplier_id": "" if row["supplier_id"] is None else str(row["supplier_id"]),
             "location": row["location"] or "", "purchase_unit": row["purchase_unit"] or "",
             "units_per_purchase": str(row["units_per_purchase"] or 1),
             "lead_time_days": str(row["lead_time_days"] or 7),
             "service_level": fmt_num(row["service_level"] or 95),
             "issue_strategy": row["issue_strategy"] or "FIFO"}
    return render_page(PAGE_PRODUCT_FORM, title="編輯商品", f=f,
                       supplier_list=supplier_options(), error=error)


@app.route("/products/<int:pid>/delete", methods=["POST"])
@admin_required
def product_delete(pid):
    db = get_db()
    has_tx = db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE product_id = ?", (pid,)
    ).fetchone()["c"] > 0
    if has_tx:
        # 有異動紀錄的商品不可刪除,以保留完整歷史
        return render_index(error="此商品已有異動紀錄,無法刪除")
    prow = db.execute("SELECT name, sku FROM products WHERE id = ?", (pid,)).fetchone()
    # 先刪實體照片檔(DB 列由 FK CASCADE 處理,但檔案系統不會自動清)
    for img in db.execute("SELECT filename FROM product_images WHERE product_id = ?", (pid,)).fetchall():
        path = os.path.join(IMAGE_DIR, img["filename"])
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    if prow:
        audit("刪除商品", "商品", pid, f"{prow['sku']} {prow['name']}")
    db.commit()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# 商品詳細頁:照片、跨公司料號別名、近期異動
# ---------------------------------------------------------------------------

def render_product_detail(pid, error=None, msg=None):
    db = get_db()
    row = db.execute("""
        SELECT p.*, s.name AS supplier_name
        FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE p.id = ?
    """, (pid,)).fetchone()
    if row is None:
        return render_index(error="找不到指定的商品")
    p = dict(row)
    p["unit_price_str"] = fmt_money(p["unit_price"])
    p["reserved"] = reserved_qty(pid)
    p["available"] = p["quantity"] - p["reserved"]
    images = db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY id", (pid,)).fetchall()
    aliases = db.execute(
        "SELECT * FROM part_aliases WHERE product_id = ? ORDER BY company, alias_sku", (pid,)).fetchall()
    recent_tx = []
    for r in db.execute("""
            SELECT t.*, u.username FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE t.product_id = ? ORDER BY t.id DESC LIMIT 10
        """, (pid,)).fetchall():
        d = dict(r)
        d["created_local"] = fmt_local(r["created_at"])
        recent_tx.append(d)
    # 批次庫存(FIFO 順序)+ 庫齡天數
    now_utc = datetime.now(timezone.utc)
    lots = []
    for l in db.execute(
            "SELECT * FROM lots WHERE product_id = ? ORDER BY received_at, id", (pid,)).fetchall():
        d = dict(l)
        d["age_days"] = (now_utc - parse_utc(l["received_at"])).days
        d["received_local"] = fmt_local(l["received_at"])
        d["cost_str"] = fmt_money(l["unit_cost"]) if l["unit_cost"] is not None else "—"
        lots.append(d)
    return render_page(PAGE_PRODUCT_DETAIL, p=p, images=images, aliases=aliases,
                       recent_tx=recent_tx, lots=lots, error=error, msg=msg)


@app.route("/products/<int:pid>")
@login_required
def product_detail(pid):
    return render_product_detail(pid)


@app.route("/products/<int:pid>/images", methods=["POST"])
@login_required
def image_upload(pid):
    db = get_db()
    if db.execute("SELECT 1 FROM products WHERE id = ?", (pid,)).fetchone() is None:
        return render_index(error="找不到指定的商品")
    file = request.files.get("photo")
    if not file or not file.filename:
        return render_product_detail(pid, error="請先選擇要上傳的照片檔案")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        return render_product_detail(
            pid, error="不支援的檔案格式,僅接受 jpg / jpeg / png / gif / webp / bmp")
    data = file.read()
    phash = ""
    if HAS_PIL:
        try:
            phash = compute_dhash(io.BytesIO(data))
        except Exception:
            return render_product_detail(pid, error="無法讀取圖片內容,請確認檔案未損壞")
    fname = f"img_{pid}_{secrets.token_hex(8)}.{ext}"
    with open(os.path.join(IMAGE_DIR, fname), "wb") as f:
        f.write(data)
    db.execute("""
        INSERT INTO product_images (product_id, filename, original_name, phash, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (pid, fname, file.filename, phash, now_str()))
    audit("上傳照片", "商品", pid, file.filename)
    db.commit()
    return redirect(url_for("product_detail", pid=pid))


@app.route("/products/<int:pid>/images/<int:img_id>/delete", methods=["POST"])
@admin_required
def image_delete(pid, img_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM product_images WHERE id = ? AND product_id = ?", (img_id, pid)).fetchone()
    if row is not None:
        path = os.path.join(IMAGE_DIR, row["filename"])
        if os.path.exists(path):
            os.remove(path)
        db.execute("DELETE FROM product_images WHERE id = ?", (img_id,))
        audit("刪除照片", "商品", pid, row["filename"])
        db.commit()
    return redirect(url_for("product_detail", pid=pid))


@app.route("/images/<path:filename>")
@login_required
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)


@app.route("/products/<int:pid>/aliases", methods=["POST"])
@login_required
def alias_add(pid):
    db = get_db()
    if db.execute("SELECT 1 FROM products WHERE id = ?", (pid,)).fetchone() is None:
        return render_index(error="找不到指定的商品")
    company = request.form.get("company", "").strip()
    alias_sku = request.form.get("alias_sku", "").strip()
    note = request.form.get("note", "").strip()
    if not company or not alias_sku:
        return render_product_detail(pid, error="公司名稱與該公司料號不可為空")
    try:
        db.execute("""
            INSERT INTO part_aliases (product_id, company, alias_sku, note, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (pid, company, alias_sku, note, now_str()))
        audit("新增別名", "商品", pid, f"{company}:{alias_sku}")
        db.commit()
    except sqlite3.IntegrityError:
        return render_product_detail(pid, error="此公司+料號組合已存在,同一組別名不可重複登記")
    return redirect(url_for("product_detail", pid=pid))


@app.route("/products/<int:pid>/aliases/<int:aid>/delete", methods=["POST"])
@admin_required
def alias_delete(pid, aid):
    db = get_db()
    arow = db.execute("SELECT company, alias_sku FROM part_aliases WHERE id = ?", (aid,)).fetchone()
    db.execute("DELETE FROM part_aliases WHERE id = ? AND product_id = ?", (aid, pid))
    if arow:
        audit("刪除別名", "商品", pid, f"{arow['company']}:{arow['alias_sku']}")
    db.commit()
    return redirect(url_for("product_detail", pid=pid))


# ---------------------------------------------------------------------------
# 入庫 / 出庫
# ---------------------------------------------------------------------------

def product_dropdown():
    return get_db().execute(
        "SELECT id, name, sku, quantity, unit FROM products ORDER BY name"
    ).fetchall()


def parse_stock_form():
    f = {
        "product_id": request.form.get("product_id", "").strip(),
        "quantity": request.form.get("quantity", "").strip(),
        "note": request.form.get("note", "").strip(),
        "lot_no": request.form.get("lot_no", "").strip(),
        "unit_cost": request.form.get("unit_cost", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "expiry_date": request.form.get("expiry_date", "").strip(),
        "qty_unit": request.form.get("qty_unit", "stock").strip(),
    }
    qty = safe_int(f["quantity"])
    if qty is None or qty <= 0:
        return f, "數量必須為正整數"
    if qty > MAX_QUANTITY:
        return f, f"數量過大,單筆不可超過 {MAX_QUANTITY:,},請確認輸入"
    if safe_int(f["product_id"]) is None:
        return f, "請選擇商品"
    if f["unit_cost"]:
        try:
            f["unit_cost_val"] = float(f["unit_cost"])
            if not math.isfinite(f["unit_cost_val"]) or f["unit_cost_val"] < 0:
                raise ValueError
            if f["unit_cost_val"] > MAX_QUANTITY:
                return f, "成本單價過大,請確認輸入"
        except (ValueError, TypeError, OverflowError):
            return f, "成本單價必須為有效的非負數字"
    else:
        f["unit_cost_val"] = None
    return f, None


EMPTY_STOCK_FORM = {"product_id": "", "quantity": "", "note": "", "lot_no": "",
                    "unit_cost": "", "purpose": "", "expiry_date": "", "qty_unit": "stock"}


def stock_done_msg(action):
    # 連續登記:成功後 302 回登記頁,從 done/qty 參數組出成功訊息(含最新庫存)
    done = safe_int(request.args.get("done", ""))
    qty = safe_int(request.args.get("qty", ""))
    if done is None or qty is None:
        return None
    row = get_db().execute(
        "SELECT name, quantity, unit FROM products WHERE id = ?", (done,)).fetchone()
    if row is None:
        return None
    return f"{action}成功:{row['name']} ×{qty},目前庫存 {row['quantity']} {row['unit']},可繼續登記下一筆"


@app.route("/stock/in", methods=["GET", "POST"])
@login_required
def stock_in():
    f = dict(EMPTY_STOCK_FORM)
    f["product_id"] = request.args.get("product_id", "")  # 詳細頁連過來時預選商品
    error = None
    if request.method == "POST":
        f, error = parse_stock_form()
        if not error:
            db = get_db()
            pid, qty = int(f["product_id"]), int(f["quantity"])
            prow = db.execute(
                "SELECT purchase_unit, units_per_purchase FROM products WHERE id = ?", (pid,)).fetchone()
            if prow is None:
                error = "找不到指定的商品"
            elif f["qty_unit"] == "purchase" and not (prow["purchase_unit"] or "").strip():
                error = "此商品尚未設定採購單位,請先在商品編輯頁設定,或改用庫存單位輸入"
            else:
                # 採購單位輸入時依換算率換成庫存單位(避免現場心算造成帳差)
                if f["qty_unit"] == "purchase":
                    qty = qty * max(1, prow["units_per_purchase"] or 1)
                    if qty > MAX_QUANTITY:
                        error = "換算後數量過大,請確認輸入"
            if not error:
                ts = now_str()
                db.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (qty, pid))
                cur = db.execute("""
                    INSERT INTO transactions (product_id, user_id, type, quantity, note, purpose, created_at)
                    VALUES (?, ?, 'in', ?, ?, ?, ?)
                """, (pid, session["user_id"], qty, f["note"], f["purpose"], ts))
                tx_id = cur.lastrowid
                # 每筆入庫建立一個批次(Lot Tracking);批號未填則自動編號
                lot_no = f["lot_no"] or f"L{datetime.now(timezone.utc).strftime('%Y%m%d')}-{tx_id}"
                try:
                    db.execute("""
                        INSERT INTO lots (product_id, transaction_id, lot_no, qty_received,
                                          qty_remaining, unit_cost, note, received_at, expiry_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pid, tx_id, lot_no, qty, qty, f["unit_cost_val"], f["note"], ts,
                          f["expiry_date"]))
                except sqlite3.IntegrityError:
                    db.rollback()
                    error = "此商品已有相同批號,請改用其他批號"
                else:
                    db.commit()
                    return redirect(url_for("stock_in", done=pid, qty=qty))
    return render_page(PAGE_STOCK_FORM, title="入庫登記", f=f, is_in=True,
                       product_list=product_dropdown(), error=error,
                       msg=stock_done_msg("入庫"))


@app.route("/stock/out", methods=["GET", "POST"])
@login_required
def stock_out():
    f = dict(EMPTY_STOCK_FORM)
    f["product_id"] = request.args.get("product_id", "")
    error = None
    if request.method == "POST":
        f, error = parse_stock_form()
        if not error:
            db = get_db()
            pid, qty = int(f["product_id"]), int(f["quantity"])
            row = db.execute("SELECT quantity FROM products WHERE id = ?", (pid,)).fetchone()
            if row is None:
                error = "找不到指定的商品"
            else:
                # 原子更新:條件帶 quantity >= ?,不足時 rowcount 為 0,杜絕負庫存
                updated = db.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                    (qty, pid, qty),
                ).rowcount
                if updated == 0:
                    db.rollback()
                    error = f"庫存不足,無法出庫(目前庫存:{row['quantity']},要求出庫:{qty})"
                else:
                    ts = now_str()
                    cur = db.execute("""
                        INSERT INTO transactions (product_id, user_id, type, quantity, note, purpose, created_at)
                        VALUES (?, ?, 'out', ?, ?, ?, ?)
                    """, (pid, session["user_id"], qty, f["note"], f["purpose"], ts))
                    tx_id = cur.lastrowid
                    consume_lots(db, pid, qty, tx_id, ts)
                    db.commit()
                    return redirect(url_for("stock_out", done=pid, qty=qty))
    return render_page(PAGE_STOCK_FORM, title="出庫登記", f=f, is_in=False,
                       product_list=product_dropdown(), error=error,
                       msg=stock_done_msg("出庫"))


# ---------------------------------------------------------------------------
# 異動歷史
# ---------------------------------------------------------------------------

def history_filters():
    return {
        "product_id": request.args.get("product_id", "").strip(),
        "type": request.args.get("type", "").strip(),
        "start": request.args.get("start", "").strip(),
        "end": request.args.get("end", "").strip(),
        "purpose": request.args.get("purpose", "").strip(),
    }


def query_transactions(filters, limit=None, offset=0):
    # lot_info:入庫顯示建立的批號;出庫顯示 FIFO 消耗明細(批號×數量)
    # limit=None 代表不分頁(CSV 匯出用);有值時多取一筆以判斷還有沒有下一頁
    sql = """
        SELECT t.*, p.name AS product_name, p.sku, p.unit, u.username,
               CASE WHEN t.type = 'in'
                    THEN (SELECT l.lot_no FROM lots l WHERE l.transaction_id = t.id)
                    ELSE (SELECT GROUP_CONCAT(l2.lot_no || '×' || c.quantity, '、')
                          FROM lot_consumptions c JOIN lots l2 ON c.lot_id = l2.id
                          WHERE c.transaction_id = t.id)
               END AS lot_info
        FROM transactions t
        JOIN products p ON t.product_id = p.id
        JOIN users u ON t.user_id = u.id
        WHERE 1=1
    """
    params = []
    pid = safe_int(filters["product_id"])
    if pid is not None:
        sql += " AND t.product_id = ?"
        params.append(pid)
    if filters["type"] in ("in", "out"):
        sql += " AND t.type = ?"
        params.append(filters["type"])
    if filters["purpose"]:
        sql += " AND t.purpose LIKE ?"
        params.append(f"%{filters['purpose']}%")
    # 使用者填的是台灣日期,DB 存 UTC,需換算區間才不會整體偏移 8 小時
    start_utc, end_utc = local_date_to_utc_range(filters["start"], filters["end"])
    if start_utc:
        sql += " AND t.created_at >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND t.created_at <= ?"
        params.append(end_utc)
    sql += " ORDER BY t.id DESC"
    if limit is not None:      # 匯出端點傳 limit=None 取得完整資料
        sql += " LIMIT ? OFFSET ?"
        params += [limit + 1, offset]   # 多取一筆用來判斷是否還有下一頁
    return get_db().execute(sql, params).fetchall()


HISTORY_PER_PAGE = 200


@app.route("/history")
@login_required
def history():
    filters = history_filters()
    page = max(1, safe_int(request.args.get("page", "1"), 1) or 1)
    fetched = query_transactions(filters, limit=HISTORY_PER_PAGE,
                                 offset=(page - 1) * HISTORY_PER_PAGE)
    has_next = len(fetched) > HISTORY_PER_PAGE
    rows = []
    for r in fetched[:HISTORY_PER_PAGE]:
        d = dict(r)
        d["created_local"] = fmt_local(r["created_at"])
        rows.append(d)
    return render_page(PAGE_HISTORY, rows=rows, filters=filters,
                       product_list=product_dropdown(),
                       pager=build_pager("history", page, has_next, **filters))


# ---------------------------------------------------------------------------
# 供應商管理
# ---------------------------------------------------------------------------

EMPTY_SUPPLIER_FORM = {"name": "", "contact": "", "phone": "", "note": ""}


def parse_supplier_form():
    f = {
        "name": request.form.get("name", "").strip(),
        "contact": request.form.get("contact", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "note": request.form.get("note", "").strip(),
    }
    if not f["name"]:
        return f, "供應商名稱不可為空"
    return f, None


@app.route("/suppliers")
@login_required
def suppliers():
    rows = get_db().execute("""
        SELECT s.*, (SELECT COUNT(*) FROM products p WHERE p.supplier_id = s.id) AS product_count
        FROM suppliers s ORDER BY s.id
    """).fetchall()
    return render_page(PAGE_SUPPLIERS, rows=rows)


@app.route("/suppliers/new", methods=["GET", "POST"])
@login_required
def supplier_new():
    f = dict(EMPTY_SUPPLIER_FORM)
    error = None
    if request.method == "POST":
        f, error = parse_supplier_form()
        if not error:
            db = get_db()
            cur = db.execute(
                "INSERT INTO suppliers (name, contact, phone, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (f["name"], f["contact"], f["phone"], f["note"], now_str()),
            )
            audit("新增供應商", "供應商", cur.lastrowid, f["name"])
            db.commit()
            return redirect(url_for("suppliers"))
    return render_page(PAGE_SUPPLIER_FORM, title="新增供應商", f=f, error=error)


@app.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def supplier_edit(sid):
    db = get_db()
    row = db.execute("SELECT * FROM suppliers WHERE id = ?", (sid,)).fetchone()
    if row is None:
        return redirect(url_for("suppliers"))
    error = None
    if request.method == "POST":
        f, error = parse_supplier_form()
        if not error:
            db.execute(
                "UPDATE suppliers SET name=?, contact=?, phone=?, note=? WHERE id=?",
                (f["name"], f["contact"], f["phone"], f["note"], sid),
            )
            audit("編輯供應商", "供應商", sid, f["name"])
            db.commit()
            return redirect(url_for("suppliers"))
    else:
        f = {"name": row["name"], "contact": row["contact"],
             "phone": row["phone"], "note": row["note"]}
    return render_page(PAGE_SUPPLIER_FORM, title="編輯供應商", f=f, error=error)


@app.route("/suppliers/<int:sid>/delete", methods=["POST"])
@admin_required
def supplier_delete(sid):
    db = get_db()
    # FK ON DELETE SET NULL:商品的供應商欄位自動清空
    srow = db.execute("SELECT name FROM suppliers WHERE id = ?", (sid,)).fetchone()
    db.execute("DELETE FROM suppliers WHERE id = ?", (sid,))
    if srow:
        audit("刪除供應商", "供應商", sid, srow["name"])
    db.commit()
    return redirect(url_for("suppliers"))


# ---------------------------------------------------------------------------
# 報表
# ---------------------------------------------------------------------------

@app.route("/report")
@login_required
def report():
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    cond, params = "", []
    start_utc, end_utc = local_date_to_utc_range(start, end)
    if start_utc:
        cond += " AND t.created_at >= ?"
        params.append(start_utc)
    if end_utc:
        cond += " AND t.created_at <= ?"
        params.append(end_utc)
    db = get_db()
    rows = [dict(r) for r in db.execute(f"""
        SELECT p.id, p.sku, p.name, p.quantity, p.unit_price,
               COALESCE(SUM(CASE WHEN t.type = 'in'  THEN t.quantity END), 0) AS total_in,
               COALESCE(SUM(CASE WHEN t.type = 'out' THEN t.quantity END), 0) AS total_out
        FROM products p
        LEFT JOIN transactions t ON t.product_id = p.id {cond}
        GROUP BY p.id ORDER BY p.id
    """, params).fetchall()]
    # 加權平均成本(存貨計價):僅以尚有剩餘且有登記成本的批次計算
    avg_costs = {r["product_id"]: r for r in db.execute("""
        SELECT product_id,
               SUM(qty_remaining * unit_cost) * 1.0 / SUM(qty_remaining) AS avg_cost
        FROM lots WHERE qty_remaining > 0 AND unit_cost IS NOT NULL
        GROUP BY product_id
    """).fetchall()}
    for r in rows:
        r["net"] = r["total_in"] - r["total_out"]
        r["value"] = r["quantity"] * r["unit_price"]
        r["unit_price_str"] = fmt_money(r["unit_price"])
        r["value_str"] = fmt_money(r["value"])
        ac = avg_costs.get(r["id"])
        r["avg_cost_str"] = fmt_money(ac["avg_cost"]) if ac else "—"
    # ABC 分析(柏拉圖法則):依庫存價值累積占比分級,A ≤80%、B ≤95%、其餘 C
    total_value = sum(r["value"] for r in rows)
    abc_rows = sorted(rows, key=lambda r: r["value"], reverse=True)
    cum = 0.0
    for r in abc_rows:
        # 分級依據是「本項之前的累積占比」:跨越 80% 門檻的那一項本身仍屬 A
        # (柏拉圖法則的重點是找出構成多數價值的少數關鍵料號;若改用本項之後的
        #  累積量判斷,單一高價品占比就會超過 80% 而使 A 級從缺,分級失去意義)
        prev_pct = (cum / total_value * 100) if total_value > 0 else 100.0
        cum += r["value"]
        cum_pct = (cum / total_value * 100) if total_value > 0 else 100.0
        r["pct_str"] = fmt_num(r["value"] / total_value * 100) if total_value > 0 else "0"
        r["cum_pct_str"] = fmt_num(cum_pct)
        r["abc"] = "A" if prev_pct < 80 else ("B" if prev_pct < 95 else "C")
    # 庫齡分析(Inventory Aging):在庫批次依庫齡分桶
    now_utc = datetime.now(timezone.utc)
    buckets = [["0-30 天", 0, 30, 0], ["31-60 天", 31, 60, 0], ["61-90 天", 61, 90, 0], ["90 天以上", 91, None, 0]]
    for l in db.execute("SELECT qty_remaining, received_at FROM lots WHERE qty_remaining > 0").fetchall():
        age = (now_utc - parse_utc(l["received_at"])).days
        for b in buckets:
            if age >= b[1] and (b[2] is None or age <= b[2]):
                b[3] += l["qty_remaining"]
                break
    aging_total = sum(b[3] for b in buckets)
    aging = [{"label": b[0], "qty": b[3],
              "pct_str": fmt_num(b[3] / aging_total * 100) if aging_total > 0 else "0"} for b in buckets]
    # XYZ 分級(依需求變異係數)與 ABC-XYZ 組合:價值之外再看穩定度
    for r in abc_rows:
        stats = usage_stats(r["id"])
        xyz, cv = xyz_class(stats)
        r["xyz"] = xyz
        r["cv_str"] = fmt_num(cv) if cv is not None else "—"
        r["abc_xyz"] = f"{r['abc']}{xyz}" if xyz != "—" else r["abc"]
    # 庫存準確率:最近一次已過帳盤點的相符比例(業界基準 95–99%)
    last_count = db.execute("""
        SELECT name, accuracy, posted_at FROM stock_counts
        WHERE status = 'posted' AND accuracy IS NOT NULL ORDER BY id DESC LIMIT 1
    """).fetchone()
    accuracy_info = None
    if last_count:
        accuracy_info = {"name": last_count["name"],
                         "accuracy_str": fmt_num(last_count["accuracy"]),
                         "posted_local": fmt_local(last_count["posted_at"])}
    return render_page(
        PAGE_REPORT, rows=rows, start=start, end=end,
        abc_rows=abc_rows, aging=aging, accuracy_info=accuracy_info,
        total_in=sum(r["total_in"] for r in rows),
        total_out=sum(r["total_out"] for r in rows),
        total_net=sum(r["net"] for r in rows),
        total_qty=sum(r["quantity"] for r in rows),
        total_value_str=fmt_money(total_value),
    )


# ---------------------------------------------------------------------------
# 以圖搜圖:上傳照片 → dHash 比對庫內所有照片 → 相似度排名
# ---------------------------------------------------------------------------

@app.route("/search/image", methods=["GET", "POST"])
@login_required
def image_search():
    results = None
    error = None
    if request.method == "POST":
        if not HAS_PIL:
            error = "此功能需要安裝 Pillow 套件"
        else:
            file = request.files.get("photo")
            if not file or not file.filename:
                error = "請先選擇要搜尋的照片"
            else:
                try:
                    query_hash = compute_dhash(io.BytesIO(file.read()))
                except Exception:
                    error = "無法讀取圖片內容,請確認檔案為有效的圖片"
                    query_hash = None
                if query_hash:
                    rows = get_db().execute("""
                        SELECT i.id, i.filename, i.phash, i.product_id,
                               p.sku, p.name, p.quantity, p.unit
                        FROM product_images i JOIN products p ON i.product_id = p.id
                        WHERE i.phash != ''
                    """).fetchall()
                    scored = []
                    for r in rows:
                        dist = hamming_distance(query_hash, r["phash"])
                        scored.append({**dict(r), "distance": dist,
                                       "similarity": round((64 - dist) / 64 * 100)})
                    scored.sort(key=lambda x: x["distance"])
                    # 同一商品多張照片只留最相似的一張,列出前 10 名
                    seen, results = set(), []
                    for s in scored:
                        if s["product_id"] in seen:
                            continue
                        seen.add(s["product_id"])
                        results.append(s)
                        if len(results) >= 10:
                            break
    return render_page(PAGE_IMAGE_SEARCH, results=results, has_pil=HAS_PIL, error=error)


# ---------------------------------------------------------------------------
# 循環盤點:建立盤點單 → 逐項輸入實盤數 → 過帳修正庫存
# ---------------------------------------------------------------------------

SCOPE_LABELS = {"all": "全部商品", "A": "A 類", "B": "B 類", "C": "C 類", "category": "指定分類"}


def abc_class_map():
    """依庫存價值累積占比計算每個商品的 ABC 分級(與報表同一套規則)。"""
    rows = get_db().execute(
        "SELECT id, quantity * unit_price AS value FROM products").fetchall()
    total = sum(r["value"] for r in rows) or 0
    ranked = sorted(rows, key=lambda r: r["value"], reverse=True)
    result, cum = {}, 0.0
    for r in ranked:
        prev_pct = (cum / total * 100) if total > 0 else 100.0
        cum += r["value"]
        result[r["id"]] = "A" if prev_pct < 80 else ("B" if prev_pct < 95 else "C")
    return result


@app.route("/counts")
@login_required
def counts_page(error=None, msg=None):
    db = get_db()
    rows = []
    for r in db.execute("SELECT * FROM stock_counts ORDER BY id DESC LIMIT 100").fetchall():
        d = dict(r)
        d["created_local"] = fmt_local(r["created_at"])
        d["accuracy_str"] = fmt_num(r["accuracy"]) if r["accuracy"] is not None else "—"
        rows.append(d)
    categories = [r["category"] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE category != '' ORDER BY category").fetchall()]
    return render_page(PAGE_COUNTS, rows=rows, categories=categories,
                       today=today_local().isoformat(), error=error, msg=msg)


@app.route("/counts/new", methods=["POST"])
@admin_required
def count_new():
    name = request.form.get("name", "").strip()
    scope = request.form.get("scope", "all").strip()
    category = request.form.get("category", "").strip()
    if not name:
        return counts_page(error="盤點單名稱不可為空")
    db = get_db()
    if scope == "category":
        if not category:
            return counts_page(error="範圍選「指定分類」時必須選擇分類")
        products = db.execute(
            "SELECT id, quantity FROM products WHERE category = ? ORDER BY id", (category,)).fetchall()
        scope_label = f"分類:{category}"
    elif scope in ("A", "B", "C"):
        abc = abc_class_map()
        products = [p for p in db.execute("SELECT id, quantity FROM products ORDER BY id").fetchall()
                    if abc.get(p["id"]) == scope]
        scope_label = f"{scope} 類"
    else:
        products = db.execute("SELECT id, quantity FROM products ORDER BY id").fetchall()
        scope_label = "全部商品"
    if not products:
        return counts_page(error="此範圍內沒有商品,請改選其他範圍")
    ts = now_str()
    cur = db.execute("""
        INSERT INTO stock_counts (name, scope, status, username, created_at)
        VALUES (?, ?, 'open', ?, ?)
    """, (name, scope_label, session.get("username", ""), ts))
    cid = cur.lastrowid
    for p in products:
        # 建立當下就固定系統帳,之後的進出不影響本次盤點的比較基準
        db.execute("""
            INSERT INTO stock_count_items (count_id, product_id, system_qty)
            VALUES (?, ?, ?)
        """, (cid, p["id"], p["quantity"]))
    audit("建立盤點單", "盤點", cid, f"{name}({scope_label},{len(products)} 項)")
    db.commit()
    return redirect(url_for("count_detail", cid=cid))


def render_count_detail(cid, error=None, msg=None):
    db = get_db()
    c = db.execute("SELECT * FROM stock_counts WHERE id = ?", (cid,)).fetchone()
    if c is None:
        return counts_page(error="找不到指定的盤點單")
    cd = dict(c)
    cd["created_local"] = fmt_local(c["created_at"])
    cd["posted_local"] = fmt_local(c["posted_at"]) if c["posted_at"] else ""
    cd["accuracy_str"] = fmt_num(c["accuracy"]) if c["accuracy"] is not None else "—"
    items = []
    for r in db.execute("""
            SELECT i.*, p.sku, p.name, p.location FROM stock_count_items i
            JOIN products p ON i.product_id = p.id
            WHERE i.count_id = ? ORDER BY p.id
        """, (cid,)).fetchall():
        d = dict(r)
        d["diff"] = (r["counted_qty"] - r["system_qty"]) if r["counted_qty"] is not None else None
        items.append(d)
    counted = sum(1 for i in items if i["counted_qty"] is not None)
    diff_count = sum(1 for i in items if i["diff"] not in (None, 0))
    return render_page(PAGE_COUNT_DETAIL, c=cd, items=items, total=len(items),
                       counted=counted, diff_count=diff_count, error=error, msg=msg)


@app.route("/counts/<int:cid>")
@login_required
def count_detail(cid):
    return render_count_detail(cid)


@app.route("/counts/<int:cid>/count", methods=["POST"])
@login_required
def count_record(cid):
    # 現場人員(一般使用者)即可記錄實盤數;只有過帳需要管理員
    db = get_db()
    c = db.execute("SELECT status FROM stock_counts WHERE id = ?", (cid,)).fetchone()
    if c is None:
        return counts_page(error="找不到指定的盤點單")
    if c["status"] == "posted":
        return render_count_detail(cid, error="此盤點單已過帳,不可再修改")
    pid = safe_int(request.form.get("product_id", ""))
    qty = safe_int(request.form.get("counted_qty", ""))
    note = request.form.get("note", "").strip()
    if pid is None:
        return render_count_detail(cid, error="請指定商品")
    if qty is None or qty < 0:
        return render_count_detail(cid, error="實盤數必須為 0 或正整數")
    if qty > MAX_QUANTITY:
        return render_count_detail(cid, error="實盤數過大,請確認輸入")
    db.execute("""
        UPDATE stock_count_items SET counted_qty = ?, note = ?, counted_at = ?
        WHERE count_id = ? AND product_id = ?
    """, (qty, note, now_str(), cid, pid))
    db.commit()
    return redirect(url_for("count_detail", cid=cid))


@app.route("/counts/<int:cid>/post", methods=["POST"])
@admin_required
def count_post(cid):
    db = get_db()
    c = db.execute("SELECT * FROM stock_counts WHERE id = ?", (cid,)).fetchone()
    if c is None:
        return counts_page(error="找不到指定的盤點單")
    if c["status"] == "posted":
        return render_count_detail(cid, error="此盤點單已過帳,不可重複過帳")
    items = db.execute("""
        SELECT i.*, p.quantity AS current_qty FROM stock_count_items i
        JOIN products p ON i.product_id = p.id
        WHERE i.count_id = ? AND i.counted_qty IS NOT NULL
    """, (cid,)).fetchall()
    if not items:
        return render_count_detail(cid, error="尚未輸入任何實盤數,無法過帳")
    ts = now_str()
    adjusted = matched = 0
    for it in items:
        diff = it["counted_qty"] - it["current_qty"]   # 以過帳當下的庫存為準才不會蓋掉期間的進出
        if diff == 0:
            matched += 1
            continue
        adjusted += 1
        pid = it["product_id"]
        note = f"盤點調整({c['name']})" + (f":{it['note']}" if it["note"] else "")
        if diff > 0:
            # 盤盈:補一筆入庫並建立調整批,批次帳才會跟著對上
            db.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (diff, pid))
            cur = db.execute("""
                INSERT INTO transactions (product_id, user_id, type, quantity, note, purpose, created_at)
                VALUES (?, ?, 'in', ?, ?, '盤點調整', ?)
            """, (pid, session["user_id"], diff, note, ts))
            tx_id = cur.lastrowid
            db.execute("""
                INSERT INTO lots (product_id, transaction_id, lot_no, qty_received,
                                  qty_remaining, note, received_at)
                VALUES (?, ?, ?, ?, ?, '盤盈調整批', ?)
            """, (pid, tx_id, f"CNT{cid}-{tx_id}", diff, diff, ts))
        else:
            # 盤虧:走與出庫相同的批次消耗路徑,維持恆等式
            loss = -diff
            db.execute("UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                       (loss, pid, loss))
            cur = db.execute("""
                INSERT INTO transactions (product_id, user_id, type, quantity, note, purpose, created_at)
                VALUES (?, ?, 'out', ?, ?, '盤點調整', ?)
            """, (pid, session["user_id"], loss, note, ts))
            consume_lots(db, pid, loss, cur.lastrowid, ts)
    total_counted = matched + adjusted
    accuracy = (matched / total_counted * 100) if total_counted else 0.0
    db.execute("""
        UPDATE stock_counts SET status = 'posted', posted_at = ?, accuracy = ? WHERE id = ?
    """, (ts, accuracy, cid))
    audit("盤點過帳", "盤點", cid,
          f"{c['name']}:盤點 {total_counted} 項,相符 {matched} 項,調整 {adjusted} 項,準確率 {accuracy:.1f}%")
    db.commit()
    return render_count_detail(cid, msg=f"過帳完成:調整 {adjusted} 項,庫存準確率 {accuracy:.1f}%")


# ---------------------------------------------------------------------------
# 預留 / 可用量
# ---------------------------------------------------------------------------

@app.route("/reservations")
@login_required
def reservations_page(error=None, msg=None):
    db = get_db()
    resv = reserved_map()
    product_list = []
    for p in db.execute("SELECT id, name, sku, quantity, unit FROM products ORDER BY name").fetchall():
        d = dict(p)
        d["available"] = p["quantity"] - resv.get(p["id"], 0)
        product_list.append(d)
    rows = []
    for r in db.execute("""
            SELECT r.*, p.name, p.sku FROM reservations r JOIN products p ON r.product_id = p.id
            WHERE r.status = 'active' ORDER BY r.id DESC
        """).fetchall():
        d = dict(r)
        d["created_local"] = fmt_local(r["created_at"])
        rows.append(d)
    return render_page(PAGE_RESERVATIONS, rows=rows, product_list=product_list,
                       error=error, msg=msg)


@app.route("/reservations/new", methods=["POST"])
@login_required
def reservation_new():
    pid = safe_int(request.form.get("product_id", ""))
    qty = safe_int(request.form.get("quantity", ""))
    purpose = request.form.get("purpose", "").strip()
    if pid is None:
        return reservations_page(error="請選擇商品")
    if qty is None or qty <= 0:
        return reservations_page(error="預留數量必須為正整數")
    if qty > MAX_QUANTITY:
        return reservations_page(error="預留數量過大,請確認輸入")
    db = get_db()
    row = db.execute("SELECT name, quantity FROM products WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return reservations_page(error="找不到指定的商品")
    available = row["quantity"] - reserved_qty(pid)
    if qty > available:
        return reservations_page(
            error=f"可用量不足,無法預留(目前可用 {available},要求預留 {qty})")
    db.execute("""
        INSERT INTO reservations (product_id, quantity, purpose, username, status, created_at)
        VALUES (?, ?, ?, ?, 'active', ?)
    """, (pid, qty, purpose, session.get("username", ""), now_str()))
    audit("建立預留", "商品", pid, f"{row['name']} ×{qty}" + (f"({purpose})" if purpose else ""))
    db.commit()
    return redirect(url_for("reservations_page"))


@app.route("/reservations/<int:rid>/release", methods=["POST"])
@login_required
def reservation_release(rid):
    db = get_db()
    row = db.execute("SELECT * FROM reservations WHERE id = ?", (rid,)).fetchone()
    if row is None or row["status"] != "active":
        return reservations_page(error="找不到有效的預留紀錄")
    db.execute("UPDATE reservations SET status = 'released', released_at = ? WHERE id = ?",
               (now_str(), rid))
    audit("釋放預留", "商品", row["product_id"], f"預留 #{rid} ×{row['quantity']}")
    db.commit()
    return redirect(url_for("reservations_page"))


# ---------------------------------------------------------------------------
# 存貨規劃:安全庫存建議(依用量變異推導,取代憑印象填的固定門檻)
# ---------------------------------------------------------------------------

def planning_rows():
    rows = []
    for p in get_db().execute("SELECT * FROM products ORDER BY id").fetchall():
        d = dict(p)
        stats = usage_stats(p["id"])
        ss, rop = suggest_safety_stock(p, stats)
        xyz, cv = xyz_class(stats)
        d["stats"], d["ss"], d["rop"], d["xyz"], d["cv"] = stats, ss, rop, xyz, cv
        d["mean_str"] = fmt_num(stats["mean"]) if stats else "—"
        d["sd_str"] = fmt_num(stats["sd"]) if stats else "—"
        d["ss_str"] = str(ss) if ss is not None else "—"
        d["rop_str"] = str(rop) if rop is not None else "—"
        d["service_level_str"] = fmt_num(p["service_level"] or 95)
        rows.append(d)
    return rows


@app.route("/planning")
@login_required
def planning_page(error=None, msg=None):
    rows = planning_rows()
    return render_page(PAGE_PLANNING, rows=rows, window=USAGE_WINDOW_DAYS,
                       has_suggestion=any(r["ss"] is not None for r in rows),
                       error=error, msg=msg)


@app.route("/planning/apply", methods=["POST"])
@admin_required
def planning_apply():
    db = get_db()
    applied = 0
    for r in planning_rows():
        if r["ss"] is None:
            continue
        db.execute("UPDATE products SET low_stock_threshold = ? WHERE id = ?", (r["ss"], r["id"]))
        applied += 1
    audit("套用安全庫存建議", "規劃", "", f"更新 {applied} 項商品的低庫存門檻")
    db.commit()
    return planning_page(msg=f"已將 {applied} 項商品的低庫存門檻更新為建議安全庫存")


# ---------------------------------------------------------------------------
# QR 料架標籤
# ---------------------------------------------------------------------------

@app.route("/products/<int:pid>/qr.png")
@login_required
def product_qr(pid):
    if not HAS_QRCODE:
        return Response("需要安裝 qrcode 套件", status=503, mimetype="text/plain")
    # QR 內容是該商品詳細頁的完整網址:手機掃了就直接開頁面登記進出
    target = url_for("product_detail", pid=pid, _external=True)
    img = qrcode.make(target)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@app.route("/labels")
@login_required
def labels_page():
    products = get_db().execute(
        "SELECT id, sku, name, location FROM products ORDER BY location, sku").fetchall()
    return render_page(PAGE_LABELS, products=products, has_qrcode=HAS_QRCODE)


# ---------------------------------------------------------------------------
# CSV 大量匯入(商品 / 別名),支援 UTF-8 與 Big5(cp950)
# ---------------------------------------------------------------------------

def decode_csv_bytes(raw):
    # 台灣 Excel 另存 CSV 預設 cp950;先試 utf-8-sig(含 BOM 也能吃)再試 cp950
    for enc in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def import_products_rows(rows):
    # 欄位:SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存(第一列為標題)
    db = get_db()
    report = []
    ok = 0
    for line_no, row in rows:
        row = list(row) + [""] * (8 - len(row))
        sku, name, category, unit, price_s, threshold_s, supplier_name, init_qty_s = \
            [c.strip() for c in row[:8]]
        label = f"{sku} {name}".strip()
        if not sku or not name:
            report.append({"line": line_no, "label": label or "(空列)", "status": "跳過:SKU 與名稱必填"})
            continue
        if db.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
            report.append({"line": line_no, "label": label, "status": "跳過:SKU 已存在"})
            continue
        try:
            price = float(price_s) if price_s else 0.0
            threshold = int(threshold_s) if threshold_s else 0
            init_qty = int(init_qty_s) if init_qty_s else 0
            if price < 0 or threshold < 0 or init_qty < 0:
                raise ValueError
            if not math.isfinite(price):
                raise ValueError
            # 超大整數會在 INSERT 時丟 OverflowError(非 ValueError),
            # 若不在此攔下,整批匯入會中斷且已成功的列全部消失
            if price > MAX_QUANTITY or threshold > MAX_QUANTITY or init_qty > MAX_QUANTITY:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            report.append({"line": line_no, "label": label, "status": "跳過:數字欄位格式錯誤或數值過大"})
            continue
        supplier_id = None
        if supplier_name:
            srow = db.execute("SELECT id FROM suppliers WHERE name = ?", (supplier_name,)).fetchone()
            if srow:
                supplier_id = srow["id"]
            else:  # 供應商不存在時自動建立,方便整批倒資料
                cur = db.execute(
                    "INSERT INTO suppliers (name, created_at) VALUES (?, ?)",
                    (supplier_name, now_str()))
                supplier_id = cur.lastrowid
        ts = now_str()
        cur = db.execute("""
            INSERT INTO products (name, sku, category, unit, unit_price,
                                  low_stock_threshold, quantity, supplier_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, sku, category, unit or "個", price, threshold, init_qty,
              supplier_id, ts))
        new_pid = cur.lastrowid
        if init_qty > 0:  # 初始庫存寫成入庫異動 + 建立批次,維持歷史與批次帳一致
            tcur = db.execute("""
                INSERT INTO transactions (product_id, user_id, type, quantity, note, created_at)
                VALUES (?, ?, 'in', ?, 'CSV匯入', ?)
            """, (new_pid, session["user_id"], init_qty, ts))
            db.execute("""
                INSERT INTO lots (product_id, transaction_id, lot_no, qty_received,
                                  qty_remaining, note, received_at)
                VALUES (?, ?, ?, ?, ?, 'CSV匯入', ?)
            """, (new_pid, tcur.lastrowid, f"IMP-{tcur.lastrowid}", init_qty, init_qty, ts))
        ok += 1
        report.append({"line": line_no, "label": label, "status": "成功"})
    db.commit()
    return ok, report


def import_aliases_rows(rows):
    # 欄位:我方SKU,公司,別名料號,備註(第一列為標題)
    db = get_db()
    report = []
    ok = 0
    for line_no, row in rows:
        row = list(row) + [""] * (4 - len(row))
        sku, company, alias_sku, note = [c.strip() for c in row[:4]]
        label = f"{sku} → {company}:{alias_sku}"
        if not sku or not company or not alias_sku:
            report.append({"line": line_no, "label": label, "status": "跳過:我方SKU、公司、別名料號必填"})
            continue
        prow = db.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
        if prow is None:
            report.append({"line": line_no, "label": label, "status": "跳過:找不到我方SKU"})
            continue
        try:
            db.execute("""
                INSERT INTO part_aliases (product_id, company, alias_sku, note, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (prow["id"], company, alias_sku, note, now_str()))
            ok += 1
            report.append({"line": line_no, "label": label, "status": "成功"})
        except sqlite3.IntegrityError:
            report.append({"line": line_no, "label": label, "status": "跳過:此公司+料號組合已存在"})
    db.commit()
    return ok, report


@app.route("/import", methods=["GET", "POST"])
@admin_required
def csv_import():
    report_rows = None
    ok_count = skip_count = 0
    error = None
    if request.method == "POST":
        mode = request.form.get("mode", "products")
        file = request.files.get("csv_file")
        if not file or not file.filename:
            error = "請先選擇 CSV 檔案"
        else:
            text = decode_csv_bytes(file.read())
            if text is None:
                error = "無法辨識檔案編碼,請使用 UTF-8 或 Big5(cp950)編碼的 CSV"
            else:
                all_rows = list(csv.reader(io.StringIO(text)))
                data_rows = [(i + 1, r) for i, r in enumerate(all_rows)][1:]  # 略過標題列
                if mode == "aliases":
                    ok_count, report_rows = import_aliases_rows(data_rows)
                else:
                    ok_count, report_rows = import_products_rows(data_rows)
                skip_count = len(report_rows) - ok_count
                db = get_db()
                audit("CSV 匯入", "匯入", mode,
                      f"檔名 {file.filename},成功 {ok_count} 筆、跳過 {skip_count} 筆")
                db.commit()
    return render_page(PAGE_IMPORT, report_rows=report_rows, ok_count=ok_count,
                       skip_count=skip_count, error=error,
                       msg=f"成功匯入 {ok_count} 筆,跳過 {skip_count} 筆" if report_rows is not None and not error else None)


# ---------------------------------------------------------------------------
# CSV 匯出(UTF-8 加 BOM,Excel 開啟中文不亂碼)
# ---------------------------------------------------------------------------

def csv_safe(value):
    # 防 CSV/DDE 公式注入:Excel 會把 = + - @ 開頭的儲存格當公式執行,
    # 前置單引號讓它保持純文字(使用者可控欄位如品名、備註都會經過這裡)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def csv_response(header, data_rows, filename):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([tuple(csv_safe(c) for c in row) for row in data_rows])
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}",
                 "Content-Type": "text/csv; charset=utf-8"},
    )


@app.route("/export/inventory.csv")
@login_required
def export_inventory():
    rows = query_products(limit=None)
    data = [(r["sku"], r["name"], r["location"] or "", r["category"], r["unit"],
             fmt_num(r["unit_price"]), r["quantity"], r["reserved"], r["available"],
             r["low_stock_threshold"], r["supplier_name"] or "",
             fmt_num(r["quantity"] * r["unit_price"])) for r in rows]
    filename = f"inventory_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return csv_response(
        ["SKU", "名稱", "儲位", "分類", "單位", "單價", "現貨量", "預留量", "可用量",
         "低庫存門檻", "供應商", "庫存價值"],
        data, filename)


@app.route("/export/transactions.csv")
@login_required
def export_transactions():
    rows = query_transactions(history_filters(), limit=None)
    data = [(fmt_local(r["created_at"]), "入庫" if r["type"] == "in" else "出庫", r["sku"],
             r["product_name"], r["quantity"], r["unit"], r["lot_info"] or "",
             r["purpose"] or "", r["note"], r["username"])
            for r in rows]
    filename = f"transactions_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return csv_response(
        ["時間(台灣)", "類型", "SKU", "商品名稱", "數量", "單位", "批次", "用途／工單", "備註", "操作人員"],
        data, filename)


# ---------------------------------------------------------------------------
# 啟動
# ---------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    start_backup_thread()   # 啟動先備份一份,之後每 24 小時自動備份
    print(f"庫存管理系統啟動中…")
    print(f"  資料庫:{os.path.abspath(DB_PATH)}")
    print(f"  照片:{IMAGE_DIR}")
    print(f"  備份:{BACKUP_DIR}" + (f"(另同步到 {EXTRA_BACKUP_DIR})" if EXTRA_BACKUP_DIR else ""))
    try:
        # waitress:正式營運級伺服器(純 Python、Windows 友善),取代開發用伺服器
        from waitress import serve
        print(f"  服務位址:http://0.0.0.0:{port}(waitress)")
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        # 未安裝 waitress 時仍可啟動,確保公司電腦離線安裝失敗也不會卡住
        print("  注意:未安裝 waitress,改用內建伺服器(建議 pip install waitress)")
        app.run(host="0.0.0.0", port=port)
