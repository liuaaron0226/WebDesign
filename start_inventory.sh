#!/usr/bin/env bash
# ============================================================
#  庫存管理系統 - 公司內網啟動腳本(Mac / Linux)
#  用法:bash start_inventory.sh
#  同事在公司內網瀏覽器開 http://(本機內網IP):5000 即可使用。
#  資料(inventory.db)與照片(inventory_images/)都存在本機,長期保留。
# ============================================================
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[錯誤] 找不到 python3,請先安裝 Python 3。"
    exit 1
fi

echo "[1/3] 安裝/更新依賴套件..."
python3 -m pip install -r requirements.txt --quiet

echo "[2/3] 本機內網 IP 如下(同事請用 192.168.x.x 或 10.x.x.x 開頭的位址加 :5000):"
(ip -4 addr 2>/dev/null || ifconfig 2>/dev/null) | grep -oE 'inet (addr:)?[0-9.]+' | grep -v '127.0.0.1' || true

echo "[3/3] 啟動庫存管理系統(Ctrl+C 停止)..."
python3 inventory_app.py
