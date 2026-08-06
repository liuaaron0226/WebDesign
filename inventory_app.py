# inventory_app.py
# 庫存管理系統(完整版)— 單檔 Flask 應用
# 功能:多使用者帳號、商品管理、供應商管理、入庫/出庫、庫存查詢與搜尋、
#       低庫存警示、異動歷史、進出統計報表、CSV 匯出、
#       跨公司料號對照(別名)、物料照片、以圖搜圖(dHash)、CSV 匯入、內網 IP 白名單
# 與 patrick_method_solver.py 完全獨立,互不 import。

import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, g, redirect, render_template_string,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# Pillow 供以圖搜圖使用;缺席時 app 仍可啟動,僅該功能停用
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = Flask(__name__)
# 正式環境務必在 Render 環境變數設定 SECRET_KEY,否則 session 可被偽造
app.secret_key = os.environ.get("SECRET_KEY", "dev-inventory-secret-change-me")

# 資料庫路徑可用環境變數覆蓋,驗收測試用 /tmp 下的乾淨 DB
DB_PATH = os.environ.get("INVENTORY_DB", "inventory.db")

# 物料照片存放目錄(gitignored),同樣可用環境變數覆蓋
IMAGE_DIR = os.path.abspath(os.environ.get("INVENTORY_IMAGES", "inventory_images"))

ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

# 內網白名單:設定 ALLOWED_IPS(逗號分隔)後,只有名單內來源可存取。
# 未設定 = 功能關閉(內網部署靠網路隔離本身,不需要此機制)。
ALLOWED_IPS = {ip.strip() for ip in os.environ.get("ALLOWED_IPS", "").split(",") if ip.strip()}


@app.before_request
def restrict_to_allowed_ips():
    # 來源 IP 取 X-Forwarded-For 第一值(Render 等反向代理會正確設定);
    # 直連部署時此標頭可被偽造,故本機制僅設計給「雲端 + 公司固定 IP」情境。
    if not ALLOWED_IPS:
        return None
    xff = request.headers.get("X-Forwarded-For", "")
    client_ip = xff.split(",")[0].strip() if xff else (request.remote_addr or "")
    if client_ip not in ALLOWED_IPS:
        return Response(
            "<h1>403 禁止存取</h1><p>此系統僅限公司內部網路使用。</p>",
            status=403, mimetype="text/html")
    return None


# ---------------------------------------------------------------------------
# 資料庫連線與初始化
# ---------------------------------------------------------------------------

def get_db():
    # 每個 request 一條連線,存在 flask.g,teardown 時關閉
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    # CREATE TABLE IF NOT EXISTS 為冪等操作,啟動時自動建表
    conn = sqlite3.connect(DB_PATH)
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
    """)
    conn.commit()
    conn.close()
    os.makedirs(IMAGE_DIR, exist_ok=True)


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
    # 統一使用 UTC 時間字串,報表日期篩選直接用字串比較
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fmt_num(value):
    # 數字顯示:整數不帶小數點,小數去尾零(125.0 → 125、25.5 → 25.5)
    return f"{value:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# 登入保護
# ---------------------------------------------------------------------------

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
        tr.low-stock td { background: #fef2f2; }
        .badge-low { display: inline-block; background: #fee2e2; color: #b91c1c; font-size: 12px; font-weight: 700;
                     padding: 1px 8px; border-radius: 999px; margin-left: 4px; white-space: nowrap; }
        .msg { padding: 11px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 14px; }
        .msg.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
        .msg.ok { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }
        .banner { background: #fffbeb; border: 1px solid #fde68a; color: #92400e; padding: 11px 14px;
                  border-radius: 10px; margin-bottom: 14px; }
        form.inline { display: inline; }
        label { display: block; margin-top: 12px; font-weight: 600; font-size: 14px; color: #334155; }
        input[type=text], input[type=password], input[type=number], input[type=date], select {
            width: 100%; max-width: 420px; padding: 9px 11px; margin-top: 5px; font-size: 16px;
            border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; }
        input:focus, select:focus { outline: 2px solid #bfdbfe; border-color: #2563eb; }
        input[type=file] { margin-top: 6px; font-size: 14px; }
        input[type=submit], button { padding: 10px 20px; margin-top: 14px; font-size: 15px; font-weight: 600;
            color: #fff; background: #2563eb; border: none; border-radius: 8px; cursor: pointer; }
        input[type=submit]:hover, button:hover { background: #1d4ed8; }
        .small-btn { padding: 4px 12px; margin: 0; font-size: 12px; font-weight: 600;
                     color: #b91c1c; background: #fff; border: 1px solid #fca5a5; border-radius: 6px; }
        .small-btn:hover { background: #fef2f2; color: #b91c1c; }
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
        .auth-box { max-width: 380px; margin: 4vh auto 0; }
        @media (max-width: 760px) {
            .container { margin: 10px; padding: 16px 14px 20px; border-radius: 12px; }
            table { display: block; overflow-x: auto; }
            table.cards { display: block; overflow: visible; }
            table.cards tr:first-child { display: none; }
            table.cards tr { display: block; border: 1px solid #e2e8f0; border-radius: 12px;
                             margin-bottom: 10px; padding: 8px 14px; background: #fff; }
            table.cards tr.low-stock { border-color: #fecaca; background: #fef2f2; }
            table.cards tr.low-stock td { background: transparent; }
            table.cards td { display: flex; justify-content: space-between; align-items: center; gap: 12px;
                             border: none; padding: 7px 0; text-align: right;
                             border-bottom: 1px dashed #eef2f6; }
            table.cards td:last-child { border-bottom: none; }
            table.cards td::before { content: attr(data-label); font-weight: 600; color: #64748b;
                                     font-size: 13px; text-align: left; flex-shrink: 0; }
            input[type=submit], button { min-height: 44px; }
            .small-btn, .filters input[type=submit], .hero-search input[type=submit] { min-height: auto; }
        }
    </style>
</head>
<body>
    {% if session.get('user_id') %}
    <nav>
        <a href="{{ url_for('index') }}">庫存總覽</a>
        <a href="{{ url_for('alerts') }}">低庫存警示</a>
        <a href="{{ url_for('stock_in') }}">入庫</a>
        <a href="{{ url_for('stock_out') }}">出庫</a>
        <a href="{{ url_for('history') }}">異動歷史</a>
        <a href="{{ url_for('suppliers') }}">供應商</a>
        <a href="{{ url_for('report') }}">報表</a>
        <a href="{{ url_for('product_new') }}">新增商品</a>
        <a href="{{ url_for('image_search') }}">以圖搜圖</a>
        <a href="{{ url_for('csv_import') }}">CSV 匯入</a>
        <span class="user-info">使用者:{{ session.get('username') }}&nbsp;|&nbsp;<a href="{{ url_for('logout') }}">登出</a></span>
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


def render_page(body, **ctx):
    ctx.setdefault("error", None)
    ctx.setdefault("msg", None)
    ctx.setdefault("year", datetime.now().year)
    return render_template_string(LAYOUT.replace("__BODY__", body), **ctx)


PAGE_REGISTER = """
<div class="auth-box">
<h1>註冊帳號</h1>
<form method="post">
    <label>帳號</label><input type="text" name="username" value="{{ username or '' }}">
    <label>密碼</label><input type="password" name="password">
    <input type="submit" value="註冊">
</form>
<p>已有帳號?<a class="plain" href="{{ url_for('login') }}">前往登入</a></p>
<p style="color:#94a3b8;font-size:13px;">第一位註冊的使用者將自動成為管理員。</p>
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
    <a href="{{ url_for('stock_in') }}"><span class="qa-icon">📥</span>入庫登記</a>
    <a href="{{ url_for('stock_out') }}"><span class="qa-icon">📤</span>出庫登記</a>
    <a href="{{ url_for('image_search') }}"><span class="qa-icon">📷</span>以圖搜圖</a>
    <a href="{{ url_for('csv_import') }}"><span class="qa-icon">📄</span>CSV 匯入</a>
    <a href="{{ url_for('product_new') }}"><span class="qa-icon">➕</span>新增商品</a>
</div>
{% if products %}
<table class="cards">
    <tr><th>SKU</th><th>名稱</th><th>別名料號</th><th>分類</th><th>庫存</th><th>單位</th><th>單價</th><th>低庫存門檻</th><th>供應商</th><th>操作</th></tr>
    {% for p in products %}
    <tr{% if p['low_stock_threshold'] > 0 and p['quantity'] <= p['low_stock_threshold'] %} class="low-stock"{% endif %}>
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">{{ p['name'] }}</a>{% if p['low_stock_threshold'] > 0 and p['quantity'] <= p['low_stock_threshold'] %} <span class="badge-low">⚠ 低庫存</span>{% endif %}</td>
        <td data-label="別名料號" class="alias-cell">{{ p['alias_text'] or '—' }}</td>
        <td data-label="分類">{{ p['category'] }}</td>
        <td data-label="庫存" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="單位">{{ p['unit'] }}</td>
        <td data-label="單價">{{ p['unit_price_str'] }}</td>
        <td data-label="低庫存門檻">{{ p['low_stock_threshold'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
        <td data-label="操作">
            <a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">詳細</a>
            <a class="plain" href="{{ url_for('product_edit', pid=p['id']) }}">編輯</a>
            <form class="inline" method="post" action="{{ url_for('product_delete', pid=p['id']) }}"
                  onsubmit="return confirm('確定刪除商品「{{ p['name'] }}」?');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
        </td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p>查無商品。</p>
{% endif %}
"""

PAGE_ALERTS = """
<h1>低庫存警示</h1>
{% if products %}
<p>下列商品庫存已達到或低於門檻,請儘快補貨:</p>
<table class="cards">
    <tr><th>SKU</th><th>名稱</th><th>庫存</th><th>低庫存門檻</th><th>單位</th><th>供應商</th></tr>
    {% for p in products %}
    <tr class="low-stock">
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="名稱"><a class="plain" href="{{ url_for('product_detail', pid=p['id']) }}">{{ p['name'] }}</a></td>
        <td data-label="庫存" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="低庫存門檻">{{ p['low_stock_threshold'] }}</td>
        <td data-label="單位">{{ p['unit'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p>目前沒有低庫存商品。</p>
{% endif %}
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
    <label>供應商</label>
    <select name="supplier_id">
        <option value="">(不指定)</option>
        {% for s in supplier_list %}
        <option value="{{ s['id'] }}" {% if f['supplier_id']|string == s['id']|string %}selected{% endif %}>{{ s['name'] }}</option>
        {% endfor %}
    </select>
    <br><input type="submit" value="儲存">
</form>
<p style="color:#888;font-size:13px;">庫存數量不在此處修改,請透過「入庫 / 出庫」登記異動。</p>
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
    <label>數量</label><input type="number" name="quantity" min="1" value="{{ f['quantity'] }}">
    <label>備註</label><input type="text" name="note" value="{{ f['note'] }}">
    <input type="submit" value="{{ title }}">
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
    <input type="submit" value="篩選">
    <a class="plain" href="{{ url_for('history') }}">清除</a>
    &nbsp;|&nbsp;
    <a class="plain" href="{{ url_for('export_transactions', **filters) }}">匯出異動 CSV</a>
</form>
{% if rows %}
<table>
    <tr><th>時間(UTC)</th><th>類型</th><th>商品</th><th>SKU</th><th>數量</th><th>備註</th><th>操作人員</th></tr>
    {% for r in rows %}
    <tr>
        <td>{{ r['created_at'] }}</td>
        <td>{% if r['type'] == 'in' %}入庫{% else %}出庫{% endif %}</td>
        <td>{{ r['product_name'] }}</td>
        <td>{{ r['sku'] }}</td>
        <td>{{ r['quantity'] }}</td>
        <td>{{ r['note'] }}</td>
        <td>{{ r['username'] }}</td>
    </tr>
    {% endfor %}
</table>
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
            <form class="inline" method="post" action="{{ url_for('supplier_delete', sid=s['id']) }}"
                  onsubmit="return confirm('確定刪除供應商「{{ s['name'] }}」?其商品的供應商欄位將被清空。');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
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
<p style="color:#888;font-size:13px;">入庫/出庫總量統計{% if start or end %}套用上方日期區間{% else %}為全部期間{% endif %};「目前庫存」與「庫存價值」一律為現時狀態。</p>
<table>
    <tr><th>SKU</th><th>名稱</th><th>入庫總量</th><th>出庫總量</th><th>淨變動</th><th>目前庫存</th><th>單價</th><th>庫存價值</th></tr>
    {% for r in rows %}
    <tr>
        <td>{{ r['sku'] }}</td>
        <td>{{ r['name'] }}</td>
        <td id="in-{{ r['id'] }}">{{ r['total_in'] }}</td>
        <td id="out-{{ r['id'] }}">{{ r['total_out'] }}</td>
        <td>{{ r['net'] }}</td>
        <td id="qty-{{ r['id'] }}">{{ r['quantity'] }}</td>
        <td>{{ r['unit_price_str'] }}</td>
        <td id="value-{{ r['id'] }}">{{ r['value_str'] }}</td>
    </tr>
    {% endfor %}
    <tr>
        <th colspan="2">總計</th>
        <th id="total-in">{{ total_in }}</th>
        <th id="total-out">{{ total_out }}</th>
        <th>{{ total_net }}</th>
        <th id="total-qty">{{ total_qty }}</th>
        <th></th>
        <th id="total-value">{{ total_value_str }}</th>
    </tr>
</table>
<p>庫存總價值:<strong id="report-total-value">{{ total_value_str }}</strong></p>
"""

PAGE_PRODUCT_DETAIL = """
<h1>商品詳細:{{ p['name'] }}</h1>
<table class="cards">
    <tr><th>SKU</th><th>分類</th><th>目前庫存</th><th>單位</th><th>單價</th><th>低庫存門檻</th><th>供應商</th></tr>
    <tr>
        <td data-label="SKU">{{ p['sku'] }}</td>
        <td data-label="分類">{{ p['category'] }}</td>
        <td data-label="目前庫存" id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td data-label="單位">{{ p['unit'] }}</td>
        <td data-label="單價">{{ p['unit_price_str'] }}</td>
        <td data-label="低庫存門檻">{{ p['low_stock_threshold'] }}</td>
        <td data-label="供應商">{{ p['supplier_name'] or '—' }}</td>
    </tr>
</table>
<p>
    <a class="plain" href="{{ url_for('product_edit', pid=p['id']) }}">編輯基本資料</a> |
    <a class="plain" href="{{ url_for('stock_in', product_id=p['id']) }}">入庫</a> |
    <a class="plain" href="{{ url_for('stock_out', product_id=p['id']) }}">出庫</a> |
    <a class="plain" href="{{ url_for('history', product_id=p['id']) }}">完整異動歷史</a>
</p>

<div class="detail-section">
    <h2>照片</h2>
    {% if images %}
    <div class="photo-wall">
        {% for img in images %}
        <div class="photo-item">
            <img src="{{ url_for('serve_image', filename=img['filename']) }}" alt="{{ p['name'] }}">
            <form class="inline" method="post" action="{{ url_for('image_delete', pid=p['id'], img_id=img['id']) }}"
                  onsubmit="return confirm('確定刪除這張照片?');">
                <button class="small-btn" type="submit">刪除</button>
            </form>
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
                <form class="inline" method="post" action="{{ url_for('alias_delete', pid=p['id'], aid=a['id']) }}">
                    <button class="small-btn" type="submit">刪除</button>
                </form>
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
    <h2>近期異動</h2>
    {% if recent_tx %}
    <table>
        <tr><th>時間(UTC)</th><th>類型</th><th>數量</th><th>備註</th><th>操作人員</th></tr>
        {% for r in recent_tx %}
        <tr>
            <td>{{ r['created_at'] }}</td>
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
# 帳號:註冊 / 登入 / 登出
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "帳號與密碼不可為空"
        else:
            db = get_db()
            # 第一位註冊者自動成為管理員
            first_user = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0
            try:
                db.execute(
                    "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(password), 1 if first_user else 0, now_str()),
                )
                db.commit()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "帳號已存在,請改用其他名稱"
    return render_page(PAGE_REGISTER, error=error, username=username)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        error = "帳號或密碼錯誤"
    return render_page(PAGE_LOGIN, error=error, username=username)


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

def query_products(q="", category=""):
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
        sql += """ AND (p.name LIKE ? OR p.sku LIKE ? OR EXISTS (
                     SELECT 1 FROM part_aliases a WHERE a.product_id = p.id
                       AND (a.alias_sku LIKE ? OR a.company LIKE ?)))"""
        params += [f"%{q}%"] * 4
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    sql += " ORDER BY p.id"
    rows = [dict(r) for r in get_db().execute(sql, params).fetchall()]
    for r in rows:
        r["unit_price_str"] = fmt_num(r["unit_price"])
    return rows


def render_index(error=None, msg=None):
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    db = get_db()
    products = query_products(q, category)
    categories = [r["category"] for r in db.execute(
        "SELECT DISTINCT category FROM products WHERE category != '' ORDER BY category"
    ).fetchall()]
    low_count = db.execute(
        "SELECT COUNT(*) AS c FROM products WHERE low_stock_threshold > 0 AND quantity <= low_stock_threshold"
    ).fetchone()["c"]
    return render_page(PAGE_INDEX, products=products, q=q, category=category,
                       categories=categories, low_count=low_count,
                       error=error, msg=msg)


@app.route("/")
@login_required
def index():
    return render_index()


@app.route("/alerts")
@login_required
def alerts():
    rows = [dict(r) for r in get_db().execute("""
        SELECT p.*, s.name AS supplier_name
        FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE p.low_stock_threshold > 0 AND p.quantity <= p.low_stock_threshold
        ORDER BY p.quantity ASC
    """).fetchall()]
    return render_page(PAGE_ALERTS, products=rows)


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
    }
    if not f["name"] or not f["sku"]:
        return f, "商品名稱與 SKU 不可為空"
    try:
        f["unit_price_val"] = float(f["unit_price"])
        if f["unit_price_val"] < 0:
            raise ValueError
    except ValueError:
        return f, "單價必須為非負數字"
    try:
        f["threshold_val"] = int(f["low_stock_threshold"])
        if f["threshold_val"] < 0:
            raise ValueError
    except ValueError:
        return f, "低庫存門檻必須為非負整數"
    f["supplier_val"] = int(f["supplier_id"]) if f["supplier_id"].isdigit() else None
    return f, None


def supplier_options():
    return get_db().execute("SELECT id, name FROM suppliers ORDER BY name").fetchall()


EMPTY_PRODUCT_FORM = {"name": "", "sku": "", "category": "", "unit": "個",
                      "unit_price": "0", "low_stock_threshold": "0", "supplier_id": ""}


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
                db.execute("""
                    INSERT INTO products (name, sku, category, unit, unit_price,
                                          low_stock_threshold, supplier_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (f["name"], f["sku"], f["category"], f["unit"], f["unit_price_val"],
                      f["threshold_val"], f["supplier_val"], now_str()))
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
                                        low_stock_threshold=?, supplier_id=?
                    WHERE id=?
                """, (f["name"], f["sku"], f["category"], f["unit"], f["unit_price_val"],
                      f["threshold_val"], f["supplier_val"], pid))
                db.commit()
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "SKU 已存在,請改用其他編號"
    else:
        f = {"name": row["name"], "sku": row["sku"], "category": row["category"],
             "unit": row["unit"], "unit_price": fmt_num(row["unit_price"]),
             "low_stock_threshold": str(row["low_stock_threshold"]),
             "supplier_id": "" if row["supplier_id"] is None else str(row["supplier_id"])}
    return render_page(PAGE_PRODUCT_FORM, title="編輯商品", f=f,
                       supplier_list=supplier_options(), error=error)


@app.route("/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    db = get_db()
    has_tx = db.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE product_id = ?", (pid,)
    ).fetchone()["c"] > 0
    if has_tx:
        # 有異動紀錄的商品不可刪除,以保留完整歷史
        return render_index(error="此商品已有異動紀錄,無法刪除")
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
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
    p["unit_price_str"] = fmt_num(p["unit_price"])
    images = db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY id", (pid,)).fetchall()
    aliases = db.execute(
        "SELECT * FROM part_aliases WHERE product_id = ? ORDER BY company, alias_sku", (pid,)).fetchall()
    recent_tx = db.execute("""
        SELECT t.*, u.username FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE t.product_id = ? ORDER BY t.id DESC LIMIT 10
    """, (pid,)).fetchall()
    return render_page(PAGE_PRODUCT_DETAIL, p=p, images=images, aliases=aliases,
                       recent_tx=recent_tx, error=error, msg=msg)


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
    db.commit()
    return redirect(url_for("product_detail", pid=pid))


@app.route("/products/<int:pid>/images/<int:img_id>/delete", methods=["POST"])
@login_required
def image_delete(pid, img_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM product_images WHERE id = ? AND product_id = ?", (img_id, pid)).fetchone()
    if row is not None:
        path = os.path.join(IMAGE_DIR, row["filename"])
        if os.path.exists(path):
            os.remove(path)
        db.execute("DELETE FROM product_images WHERE id = ?", (img_id,))
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
        db.commit()
    except sqlite3.IntegrityError:
        return render_product_detail(pid, error="此公司+料號組合已存在,同一組別名不可重複登記")
    return redirect(url_for("product_detail", pid=pid))


@app.route("/products/<int:pid>/aliases/<int:aid>/delete", methods=["POST"])
@login_required
def alias_delete(pid, aid):
    db = get_db()
    db.execute("DELETE FROM part_aliases WHERE id = ? AND product_id = ?", (aid, pid))
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
    }
    if not f["quantity"].isdigit() or int(f["quantity"]) <= 0:
        return f, "數量必須為正整數"
    if not f["product_id"].isdigit():
        return f, "請選擇商品"
    return f, None


EMPTY_STOCK_FORM = {"product_id": "", "quantity": "", "note": ""}


def stock_done_msg(action):
    # 連續登記:成功後 302 回登記頁,從 done/qty 參數組出成功訊息(含最新庫存)
    done, qty = request.args.get("done", ""), request.args.get("qty", "")
    if not done.isdigit() or not qty.isdigit():
        return None
    row = get_db().execute(
        "SELECT name, quantity, unit FROM products WHERE id = ?", (int(done),)).fetchone()
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
            updated = db.execute(
                "UPDATE products SET quantity = quantity + ? WHERE id = ?", (qty, pid)
            ).rowcount
            if updated == 0:
                db.rollback()
                error = "找不到指定的商品"
            else:
                db.execute("""
                    INSERT INTO transactions (product_id, user_id, type, quantity, note, created_at)
                    VALUES (?, ?, 'in', ?, ?, ?)
                """, (pid, session["user_id"], qty, f["note"], now_str()))
                db.commit()
                return redirect(url_for("stock_in", done=pid, qty=qty))
    return render_page(PAGE_STOCK_FORM, title="入庫登記", f=f,
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
                    db.execute("""
                        INSERT INTO transactions (product_id, user_id, type, quantity, note, created_at)
                        VALUES (?, ?, 'out', ?, ?, ?)
                    """, (pid, session["user_id"], qty, f["note"], now_str()))
                    db.commit()
                    return redirect(url_for("stock_out", done=pid, qty=qty))
    return render_page(PAGE_STOCK_FORM, title="出庫登記", f=f,
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
    }


def query_transactions(filters):
    sql = """
        SELECT t.*, p.name AS product_name, p.sku, p.unit, u.username
        FROM transactions t
        JOIN products p ON t.product_id = p.id
        JOIN users u ON t.user_id = u.id
        WHERE 1=1
    """
    params = []
    if filters["product_id"].isdigit():
        sql += " AND t.product_id = ?"
        params.append(int(filters["product_id"]))
    if filters["type"] in ("in", "out"):
        sql += " AND t.type = ?"
        params.append(filters["type"])
    if filters["start"]:
        sql += " AND t.created_at >= ?"
        params.append(filters["start"])
    if filters["end"]:
        sql += " AND t.created_at <= ?"
        params.append(filters["end"] + " 23:59:59")
    sql += " ORDER BY t.id DESC"
    return get_db().execute(sql, params).fetchall()


@app.route("/history")
@login_required
def history():
    filters = history_filters()
    rows = query_transactions(filters)
    return render_page(PAGE_HISTORY, rows=rows, filters=filters,
                       product_list=product_dropdown())


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
            db.execute(
                "INSERT INTO suppliers (name, contact, phone, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (f["name"], f["contact"], f["phone"], f["note"], now_str()),
            )
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
            db.commit()
            return redirect(url_for("suppliers"))
    else:
        f = {"name": row["name"], "contact": row["contact"],
             "phone": row["phone"], "note": row["note"]}
    return render_page(PAGE_SUPPLIER_FORM, title="編輯供應商", f=f, error=error)


@app.route("/suppliers/<int:sid>/delete", methods=["POST"])
@login_required
def supplier_delete(sid):
    db = get_db()
    # FK ON DELETE SET NULL:商品的供應商欄位自動清空
    db.execute("DELETE FROM suppliers WHERE id = ?", (sid,))
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
    if start:
        cond += " AND t.created_at >= ?"
        params.append(start)
    if end:
        cond += " AND t.created_at <= ?"
        params.append(end + " 23:59:59")
    rows = [dict(r) for r in get_db().execute(f"""
        SELECT p.id, p.sku, p.name, p.quantity, p.unit_price,
               COALESCE(SUM(CASE WHEN t.type = 'in'  THEN t.quantity END), 0) AS total_in,
               COALESCE(SUM(CASE WHEN t.type = 'out' THEN t.quantity END), 0) AS total_out
        FROM products p
        LEFT JOIN transactions t ON t.product_id = p.id {cond}
        GROUP BY p.id ORDER BY p.id
    """, params).fetchall()]
    for r in rows:
        r["net"] = r["total_in"] - r["total_out"]
        r["value"] = r["quantity"] * r["unit_price"]
        r["unit_price_str"] = fmt_num(r["unit_price"])
        r["value_str"] = fmt_num(r["value"])
    return render_page(
        PAGE_REPORT, rows=rows, start=start, end=end,
        total_in=sum(r["total_in"] for r in rows),
        total_out=sum(r["total_out"] for r in rows),
        total_net=sum(r["net"] for r in rows),
        total_qty=sum(r["quantity"] for r in rows),
        total_value_str=fmt_num(sum(r["value"] for r in rows)),
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
        except ValueError:
            report.append({"line": line_no, "label": label, "status": "跳過:數字欄位格式錯誤"})
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
        cur = db.execute("""
            INSERT INTO products (name, sku, category, unit, unit_price,
                                  low_stock_threshold, quantity, supplier_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, sku, category, unit or "個", price, threshold, init_qty,
              supplier_id, now_str()))
        if init_qty > 0:  # 初始庫存寫成入庫異動,維持歷史一致
            db.execute("""
                INSERT INTO transactions (product_id, user_id, type, quantity, note, created_at)
                VALUES (?, ?, 'in', ?, 'CSV匯入', ?)
            """, (cur.lastrowid, session["user_id"], init_qty, now_str()))
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
@login_required
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
    return render_page(PAGE_IMPORT, report_rows=report_rows, ok_count=ok_count,
                       skip_count=skip_count, error=error,
                       msg=f"成功匯入 {ok_count} 筆,跳過 {skip_count} 筆" if report_rows is not None and not error else None)


# ---------------------------------------------------------------------------
# CSV 匯出(UTF-8 加 BOM,Excel 開啟中文不亂碼)
# ---------------------------------------------------------------------------

def csv_response(header, data_rows, filename):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(data_rows)
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}",
                 "Content-Type": "text/csv; charset=utf-8"},
    )


@app.route("/export/inventory.csv")
@login_required
def export_inventory():
    rows = query_products()
    data = [(r["sku"], r["name"], r["category"], r["unit"], fmt_num(r["unit_price"]),
             r["quantity"], r["low_stock_threshold"], r["supplier_name"] or "",
             fmt_num(r["quantity"] * r["unit_price"])) for r in rows]
    filename = f"inventory_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return csv_response(
        ["SKU", "名稱", "分類", "單位", "單價", "目前庫存", "低庫存門檻", "供應商", "庫存價值"],
        data, filename)


@app.route("/export/transactions.csv")
@login_required
def export_transactions():
    rows = query_transactions(history_filters())
    data = [(r["created_at"], "入庫" if r["type"] == "in" else "出庫", r["sku"],
             r["product_name"], r["quantity"], r["unit"], r["note"], r["username"])
            for r in rows]
    filename = f"transactions_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return csv_response(
        ["時間(UTC)", "類型", "SKU", "商品名稱", "數量", "單位", "備註", "操作人員"],
        data, filename)


# ---------------------------------------------------------------------------
# 啟動
# ---------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
