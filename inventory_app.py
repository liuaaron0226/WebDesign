# inventory_app.py
# 庫存管理系統(完整版)— 單檔 Flask 應用
# 功能:多使用者帳號、商品管理、供應商管理、入庫/出庫、庫存查詢與搜尋、
#       低庫存警示、異動歷史、進出統計報表、CSV 匯出
# 與 patrick_method_solver.py 完全獨立,互不 import。

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, g, redirect, render_template_string,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
# 正式環境務必在 Render 環境變數設定 SECRET_KEY,否則 session 可被偽造
app.secret_key = os.environ.get("SECRET_KEY", "dev-inventory-secret-change-me")

# 資料庫路徑可用環境變數覆蓋,驗收測試用 /tmp 下的乾淨 DB
DB_PATH = os.environ.get("INVENTORY_DB", "inventory.db")


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
    """)
    conn.commit()
    conn.close()


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
    <title>庫存管理系統</title>
    <style>
        body { font-family: Arial, "Microsoft JhengHei", sans-serif; margin: 0; background: #f7f7f7; }
        nav { background: #2c3e50; padding: 10px 20px; }
        nav a { color: #ecf0f1; text-decoration: none; margin-right: 14px; }
        nav a:hover { text-decoration: underline; }
        nav .user-info { float: right; color: #bdc3c7; }
        nav .user-info a { margin-right: 0; }
        .container { max-width: 1000px; margin: 20px auto; background: #fff; padding: 20px 30px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
        h1 { font-size: 22px; margin-top: 0; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; }
        th { background: #34495e; color: #fff; }
        tr.low-stock td { background: #fdecea; }
        .badge-low { color: #c0392b; font-weight: bold; }
        .msg { padding: 10px 14px; border-radius: 4px; margin-bottom: 12px; }
        .msg.error { background: #fdecea; color: #c0392b; border: 1px solid #e6b0aa; }
        .msg.ok { background: #eafaf1; color: #1e8449; border: 1px solid #a9dfbf; }
        .banner { background: #fef9e7; border: 1px solid #f7dc6f; padding: 10px 14px; border-radius: 4px; margin-bottom: 12px; }
        form.inline { display: inline; }
        label { display: block; margin-top: 10px; font-weight: bold; }
        input[type=text], input[type=password], input[type=number], select {
            width: 300px; padding: 6px; margin-top: 4px; }
        input[type=submit], button { padding: 8px 18px; margin-top: 14px; cursor: pointer; }
        .small-btn { padding: 3px 10px; margin: 0; font-size: 12px; }
        .filters input, .filters select { width: auto; }
        .filters input[type=submit] { margin-top: 0; }
        footer { text-align: center; color: #999; padding: 14px; font-size: 12px; }
        a.plain { color: #2980b9; }
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
<h1>註冊帳號</h1>
<form method="post">
    <label>帳號</label><input type="text" name="username" value="{{ username or '' }}">
    <label>密碼</label><input type="password" name="password">
    <input type="submit" value="註冊">
</form>
<p>已有帳號?<a class="plain" href="{{ url_for('login') }}">前往登入</a></p>
<p style="color:#888;font-size:13px;">第一位註冊的使用者將自動成為管理員。</p>
"""

PAGE_LOGIN = """
<h1>登入庫存管理系統</h1>
<form method="post">
    <label>帳號</label><input type="text" name="username" value="{{ username or '' }}">
    <label>密碼</label><input type="password" name="password">
    <input type="submit" value="登入">
</form>
<p>還沒有帳號?<a class="plain" href="{{ url_for('register') }}">前往註冊</a></p>
"""

PAGE_INDEX = """
<h1>庫存總覽</h1>
{% if low_count > 0 %}
<div class="banner">⚠ 目前有 {{ low_count }} 項商品低於庫存門檻,<a class="plain" href="{{ url_for('alerts') }}">查看低庫存警示</a></div>
{% endif %}
<form method="get" class="filters">
    <input type="text" name="q" placeholder="搜尋名稱或 SKU" value="{{ q }}">
    <select name="category">
        <option value="">全部分類</option>
        {% for c in categories %}
        <option value="{{ c }}" {% if c == category %}selected{% endif %}>{{ c }}</option>
        {% endfor %}
    </select>
    <input type="submit" value="搜尋">
    <a class="plain" href="{{ url_for('index') }}">清除</a>
    &nbsp;|&nbsp;
    <a class="plain" href="{{ url_for('export_inventory') }}">匯出庫存 CSV</a>
</form>
{% if products %}
<table>
    <tr><th>SKU</th><th>名稱</th><th>分類</th><th>庫存</th><th>單位</th><th>單價</th><th>低庫存門檻</th><th>供應商</th><th>操作</th></tr>
    {% for p in products %}
    <tr{% if p['low_stock_threshold'] > 0 and p['quantity'] <= p['low_stock_threshold'] %} class="low-stock"{% endif %}>
        <td>{{ p['sku'] }}</td>
        <td>{{ p['name'] }}{% if p['low_stock_threshold'] > 0 and p['quantity'] <= p['low_stock_threshold'] %} <span class="badge-low">⚠ 低庫存</span>{% endif %}</td>
        <td>{{ p['category'] }}</td>
        <td id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td>{{ p['unit'] }}</td>
        <td>{{ p['unit_price_str'] }}</td>
        <td>{{ p['low_stock_threshold'] }}</td>
        <td>{{ p['supplier_name'] or '—' }}</td>
        <td>
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
<table>
    <tr><th>SKU</th><th>名稱</th><th>庫存</th><th>低庫存門檻</th><th>單位</th><th>供應商</th></tr>
    {% for p in products %}
    <tr class="low-stock">
        <td>{{ p['sku'] }}</td>
        <td>{{ p['name'] }}</td>
        <td id="qty-{{ p['id'] }}">{{ p['quantity'] }}</td>
        <td>{{ p['low_stock_threshold'] }}</td>
        <td>{{ p['unit'] }}</td>
        <td>{{ p['supplier_name'] or '—' }}</td>
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
    sql = """
        SELECT p.*, s.name AS supplier_name
        FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE 1=1
    """
    params = []
    if q:
        sql += " AND (p.name LIKE ? OR p.sku LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
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


@app.route("/stock/in", methods=["GET", "POST"])
@login_required
def stock_in():
    f = dict(EMPTY_STOCK_FORM)
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
                return redirect(url_for("index"))
    return render_page(PAGE_STOCK_FORM, title="入庫登記", f=f,
                       product_list=product_dropdown(), error=error)


@app.route("/stock/out", methods=["GET", "POST"])
@login_required
def stock_out():
    f = dict(EMPTY_STOCK_FORM)
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
                    return redirect(url_for("index"))
    return render_page(PAGE_STOCK_FORM, title="出庫登記", f=f,
                       product_list=product_dropdown(), error=error)


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
