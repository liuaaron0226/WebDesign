#!/usr/bin/env bash
# ============================================================
#  庫存管理系統 - 公司內網啟動腳本(Mac / Linux)
#  用法:bash start_inventory.sh
#  同事在公司內網用瀏覽器開本腳本印出來的網址即可使用。
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

# 只印一個位址。舊版直接把 ip/ifconfig 的結果整串倒出來,一台裝過 Docker 的
# 電腦會列出四五個位址(還包含連不上的虛擬網卡),使用者根本挑不出要給同事哪一個。
echo "[2/3] 取得內網網址..."
LANURL="$(python3 inventory_app.py --lan-url 2>/dev/null || true)"
if [ -n "$LANURL" ]; then
    {
        echo "同事請用這個網址開啟庫存管理系統:"
        echo "$LANURL"
        echo ""
        echo "(要在公司的網路裡才連得上。這台電腦關機或停掉這個程式就會停止服務。)"
    } > 同事連線網址.txt
    echo "      同事請開:  $LANURL"
    echo "      這一行也已經存成「同事連線網址.txt」,可以直接貼給同事。"
else
    echo "      [注意] 抓不到內網位址,可能是這台電腦還沒接上公司網路。"
    echo "      本機自己仍然可以用 http://localhost:${PORT:-5000}"
fi

echo "資料保存位置(請定期備份):inventory.db、inventory_images/、backups/"
echo "[3/3] 啟動庫存管理系統(Ctrl+C 停止)..."
python3 inventory_app.py
