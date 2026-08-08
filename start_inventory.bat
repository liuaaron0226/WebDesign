@echo off
setlocal
chcp 65001 >nul 2>nul
rem ============================================================
rem  庫存管理系統 - 公司內網啟動腳本(Windows)
rem  用法:把整個專案資料夾放到公司那台長開的電腦,雙擊本檔案。
rem  同事在公司內網瀏覽器開 http://(本機內網IP):5000 即可使用。
rem  注意:本檔必須是 CRLF 換行,否則 cmd 無法正確解析(見 .gitattributes)。
rem ============================================================

cd /d "%~dp0"
title 庫存管理系統

rem --- 找可用的 Python:先試 py 啟動器,再試 python ---
set "PYEXE="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if defined PYEXE goto GOTPYTHON
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto GOTPYTHON
goto NOPYTHON

:GOTPYTHON
echo [1/4] 使用的 Python:
%PYEXE% --version
echo.

echo [2/4] 安裝/更新依賴套件(第一次會比較久,請稍候)...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto PIPFAIL
echo.

echo [3/4] 本機內網 IP(同事請用 192.168.x.x 或 10.x.x.x 開頭的位址加 :5000):
ipconfig | findstr /i "IPv4"
echo.
echo 資料保存位置(請定期備份這三項):
echo    資料庫 inventory.db
echo    照片   inventory_images\
echo    備份   backups\
echo.

echo [4/4] 啟動中...關閉此視窗即停止服務。
echo.
echo   本機請用這個網址(3 秒後會自動幫你開啟):
echo       http://localhost:5000
echo.
echo   注意:不要輸入 0.0.0.0,那不是網址,瀏覽器會顯示「無法連上這個網站」。
echo   同事請用上面 [3/4] 列出的 192.168.x.x 或 10.x.x.x 位址加 :5000。
echo   若同事連不上,請到「Windows 安全性 - 防火牆」允許 Python 連入(連接埠 5000)。
echo.
rem 等伺服器起來後自動開啟瀏覽器;失敗也不影響服務,使用者仍可自行輸入上面的網址
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:5000"
%PYEXE% inventory_app.py
if errorlevel 1 goto RUNFAIL
goto END

:NOPYTHON
echo [錯誤] 找不到 Python。
echo.
echo 請到 https://www.python.org/downloads/ 下載安裝,
echo 安裝畫面務必勾選「Add Python to PATH」,裝完後重新雙擊本檔案。
echo.
pause
exit /b 1

:PIPFAIL
echo.
echo [錯誤] 依賴套件安裝失敗,系統無法啟動。
echo.
echo 常見原因與處理:
echo   1. 這台電腦沒有網路 - 請先連上網路再重試。
echo   2. 公司網路擋住 pip - 請洽 IT,或在有網路的電腦先下載套件。
echo   3. 權限不足 - 對本檔案按右鍵選「以系統管理員身分執行」。
echo.
pause
exit /b 1

:RUNFAIL
echo.
echo [錯誤] 系統啟動失敗,請把上面的錯誤訊息拍照或複製下來回報。
echo.
pause
exit /b 1

:END
pause
