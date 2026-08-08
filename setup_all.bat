@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title 庫存系統 - 一次搞定安裝

echo ============================================================
echo   庫存管理系統:一次搞定(轉檔 + 建帳號 + 匯入 + 啟動)
echo ============================================================
echo.

set "PYEXE="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if defined PYEXE goto GOTPYTHON
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto GOTPYTHON
goto NOPYTHON

:GOTPYTHON
rem --- 已有資料庫就停下來,絕不覆蓋既有資料 ---
if exist "inventory.db" (
    echo [注意] 這個資料夾已經有 inventory.db,代表系統已經在用了。
    echo.
    echo 本腳本只用於「全新安裝」。若要重新來過,請先把 inventory.db
    echo 搬到別處備份,再重新執行本檔案。
    echo 若只是要啟動系統,請改雙擊 start_inventory.bat。
    echo.
    pause
    exit /b 1
)

echo [1/5] 安裝必要套件(第一次會比較久)...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto PIPFAIL
echo      OK
echo.

echo [2/5] 尋找 Excel 庫存表...
set "XLSX="
set "COUNT=0"
for %%F in (*.xlsx) do (
    set /a COUNT+=1
    set "XLSX=%%F"
)
if "%COUNT%"=="0" goto NOEXCEL
if not "%COUNT%"=="1" goto MANYEXCEL
echo      找到:%XLSX%
echo.

:CONVERT
echo [3/5] 轉檔中...
%PYEXE% migrate_bl_excel.py "%XLSX%" 2026 migrate_out
if errorlevel 1 goto RUNFAIL
echo.

echo [4/5] 建立管理員帳號
echo      這是你之後登入系統要用的帳號密碼,請自己決定並記下來。
echo.
set "ADMINUSER="
set /p "ADMINUSER=      管理員帳號(例如 admin):"
if "%ADMINUSER%"=="" set "ADMINUSER=admin"
set "ADMINPASS="
set /p "ADMINPASS=      密碼(至少 8 碼):"
echo.
%PYEXE% inventory_app.py --setup-admin "%ADMINUSER%" "%ADMINPASS%"
if errorlevel 1 goto ADMINFAIL

echo.
echo [5/5] 匯入舊資料...
%PYEXE% inventory_app.py --import "migrate_out\products_import.csv"
if errorlevel 1 goto IMPORTFAIL
echo.

echo ============================================================
echo   全部完成!正在啟動系統,3 秒後自動開啟瀏覽器。
echo.
echo   登入帳號:%ADMINUSER%
echo   網址:    http://localhost:5000
echo.
echo   請檢查這三點確認資料完整:
echo     1. 頁尾顯示「版本 2026.08.07」或更新
echo     2. 上方導覽只有 5 個項目(不是一長排)
echo     3. 首頁表格的「儲位」欄有 H-8 這類值
echo.
echo   關閉此視窗即停止服務。
echo ============================================================
echo.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:5000"
%PYEXE% inventory_app.py
if errorlevel 1 goto RUNFAIL
goto END

:MANYEXCEL
echo.
echo      這個資料夾有 %COUNT% 個 Excel 檔:
for %%F in (*.xlsx) do echo        %%F
echo.
set /p "XLSX=請輸入要轉檔的檔名(整個檔名含 .xlsx):"
if not exist "%XLSX%" (
    echo [錯誤] 找不到檔案 "%XLSX%"
    pause
    exit /b 1
)
echo.
goto CONVERT

:NOEXCEL
echo.
echo [錯誤] 這個資料夾裡沒有找到任何 .xlsx 檔案。
echo.
echo 請把公司的庫存 Excel 檔複製到這個資料夾:
echo    %~dp0
echo 然後重新雙擊本檔案。
echo.
pause
exit /b 1

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
echo [錯誤] 套件安裝失敗,系統無法啟動。
echo.
echo 常見原因:1. 沒有網路  2. 公司網路擋住 pip  3. 權限不足(請以系統管理員身分執行)
echo.
pause
exit /b 1

:ADMINFAIL
echo.
echo [錯誤] 建立管理員帳號失敗(密碼可能少於 8 碼)。
echo 請重新雙擊本檔案再試一次。
echo.
pause
exit /b 1

:IMPORTFAIL
echo.
echo [錯誤] 匯入失敗,請把上面的錯誤訊息拍照或複製下來回報。
echo.
pause
exit /b 1

:RUNFAIL
echo.
echo [錯誤] 執行失敗,請把上面的錯誤訊息拍照或複製下來回報。
echo.
pause
exit /b 1

:END
pause
