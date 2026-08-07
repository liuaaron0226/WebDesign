@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title 舊資料搬家工具

echo ============================================================
echo   舊資料搬家:把公司的 Excel 流水帳轉成系統可匯入的檔案
echo ============================================================
echo.

rem --- 找可用的 Python(與 start_inventory.bat 同一套邏輯) ---
set "PYEXE="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if defined PYEXE goto GOTPYTHON
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto GOTPYTHON
goto NOPYTHON

:GOTPYTHON
echo [1/3] 檢查必要套件...
%PYEXE% -c "import openpyxl" >nul 2>nul
if errorlevel 1 (
    echo      安裝 openpyxl 中,請稍候...
    %PYEXE% -m pip install -r requirements.txt
    if errorlevel 1 goto PIPFAIL
)
echo      OK
echo.

rem --- 找出資料夾裡的 Excel 檔 ---
echo [2/3] 尋找 Excel 庫存表...
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

:RUN
echo [3/3] 開始轉檔(2000 多項物料,約需幾秒)...
echo.
%PYEXE% migrate_bl_excel.py "%XLSX%" 2026 migrate_out
if errorlevel 1 goto RUNFAIL
echo.
echo ============================================================
echo   轉檔完成!產出的檔案在 migrate_out 資料夾:
echo.
echo     products_import.csv    ^<- 這個要上傳到系統
echo     migration_report.csv   ^<- 逐項對照報告,請看「備註」欄
echo     suppliers.csv          ^<- 廠商清單(供核對)
echo.
echo   接下來:
echo     1. 雙擊 start_inventory.bat 啟動系統
echo     2. 用管理員帳號登入
echo     3. 上方選單「系統管理」-^> 「CSV 匯入」
echo     4. 匯入類型選「商品匯入」,選 migrate_out 裡的 products_import.csv
echo     5. 按「開始匯入」
echo ============================================================
echo.
start "" "migrate_out"
pause
exit /b 0

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
goto RUN

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
echo [錯誤] 套件安裝失敗,無法讀取 Excel。
echo.
echo 常見原因:1. 沒有網路  2. 公司網路擋住 pip  3. 權限不足(請以系統管理員身分執行)
echo.
pause
exit /b 1

:RUNFAIL
echo.
echo [錯誤] 轉檔失敗,請把上面的錯誤訊息拍照或複製下來回報。
echo.
pause
exit /b 1
