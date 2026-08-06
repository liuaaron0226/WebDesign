@echo off
chcp 65001 >nul
rem ============================================================
rem  庫存管理系統 - 公司內網啟動腳本(Windows)
rem  用法:把整個專案資料夾放到公司那台長開的電腦,雙擊本檔案。
rem  同事在公司內網瀏覽器開 http://(本機內網IP):5000 即可使用。
rem  資料(inventory.db)與照片(inventory_images/)都存在本機,長期保留。
rem ============================================================

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 Python,請先到 https://www.python.org/downloads/ 安裝,
    echo        安裝時記得勾選 "Add Python to PATH"。
    pause
    exit /b 1
)

echo [1/3] 安裝/更新依賴套件...
python -m pip install -r requirements.txt --quiet

echo [2/3] 本機內網 IP 如下(同事請用其中 192.168.x.x 或 10.x.x.x 開頭的位址加 :5000):
ipconfig | findstr /i "IPv4"

echo [3/3] 啟動庫存管理系統(關閉此視窗即停止服務)...
echo 若同事連不上,請到「Windows 安全性 - 防火牆」允許 Python 的連入連線(連接埠 5000)。
python inventory_app.py

pause
