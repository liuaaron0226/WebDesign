@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
rem ============================================================
rem  庫存管理系統 - 公司內網啟動腳本(Windows)
rem  用法:把整個專案資料夾放到公司那台長開的電腦,雙擊本檔案。
rem  同事在公司內網用瀏覽器開本檔案印出來的網址即可使用。
rem  注意:本檔必須是 CRLF 換行,否則 cmd 無法正確解析(見 .gitattributes)。
rem ============================================================

cd /d "%~dp0"
title 庫存管理系統
set "PORT_NO=5000"

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
echo [1/5] 使用的 Python:
%PYEXE% --version
echo.

echo [2/5] 安裝/更新依賴套件(第一次會比較久,請稍候)...
%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 goto PIPFAIL
echo.

rem --- 防火牆:同事連不上最常見的原因就是這一項 ---
rem 用 net session 判斷是不是系統管理員(一般權限會失敗)
echo [3/5] 檢查 Windows 防火牆...
net session >nul 2>nul
if errorlevel 1 goto NOADMIN
netsh advfirewall firewall show rule name="庫存管理系統" >nul 2>nul
if not errorlevel 1 goto FWDONE
netsh advfirewall firewall add rule name="庫存管理系統" dir=in action=allow protocol=TCP localport=%PORT_NO% >nul 2>nul
if errorlevel 1 goto FWFAIL
echo       已自動開放連接埠 %PORT_NO%,同事可以連進來了。
goto FWDONE
:FWFAIL
echo       [注意] 防火牆規則建立失敗,同事可能連不上。
echo       請把這個視窗的訊息拍照回報。
goto FWDONE
:NOADMIN
echo       [注意] 目前不是以系統管理員身分執行,沒辦法自動開放防火牆。
echo.
echo       如果等一下同事連不上,你只要做一件事:
echo         關掉這個視窗,對 start_inventory.bat 按右鍵,
echo         選「以系統管理員身分執行」,再跑一次就好。
echo.
echo       (本機自己用不受影響,現在按任意鍵可以繼續。)
echo.
pause
:FWDONE
echo.

rem --- 取得同事要輸入的那一行網址,並寫成文字檔方便轉貼 ---
echo [4/5] 取得內網網址...
set "LANURL="
for /f "usebackq delims=" %%u in (`%PYEXE% inventory_app.py --lan-url 2^>nul`) do set "LANURL=%%u"
if not defined LANURL goto NOLAN
echo 同事請用這個網址開啟庫存管理系統:> "同事連線網址.txt"
echo %LANURL%>> "同事連線網址.txt"
echo.>> "同事連線網址.txt"
echo (要在公司的網路裡才連得上。這台電腦關機或關掉黑色視窗就會停止服務。)>> "同事連線網址.txt"
echo       同事請開:  %LANURL%
echo       這一行也已經存成「同事連線網址.txt」,可以直接貼給同事。
goto LANDONE
:NOLAN
echo       [注意] 抓不到內網位址,可能是這台電腦還沒接上公司網路。
echo       本機自己仍然可以用 http://localhost:%PORT_NO%
:LANDONE
echo.

echo 資料保存位置(請定期備份這三項):
echo    資料庫 inventory.db
echo    照片   inventory_images\
echo    備份   backups\
echo.

echo [5/5] 啟動中...關閉此視窗即停止服務。
echo.
echo   這台電腦請用(3 秒後會自動幫你開啟):
echo       http://localhost:%PORT_NO%
echo.
echo   注意:不要輸入 0.0.0.0,那不是網址,瀏覽器會顯示「無法連上這個網站」。
echo.
rem 等伺服器起來後自動開啟瀏覽器;失敗也不影響服務,使用者仍可自行輸入上面的網址
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%PORT_NO%"
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
