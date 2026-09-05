@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>nul
rem ============================================================
rem  庫存管理系統 - 忘記密碼時重設(Windows)
rem  用法:雙擊本檔案,照著問題回答就好。
rem  注意:本檔必須是 CRLF 換行,否則 cmd 無法正確解析(見 .gitattributes)。
rem ============================================================

cd /d "%~dp0"
title 庫存管理系統 - 重設密碼

echo ============================================================
echo   重設登入密碼
echo ============================================================
echo.
echo  說明:密碼在系統裡是「單向」存放的,存的不是你打的原文,
echo        所以沒有人查得出舊密碼(包含系統作者)。
echo        這個工具不是把舊密碼找回來,是直接換一個新的。
echo.

rem --- 找可用的 Python ---
set "PYEXE="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if defined PYEXE goto GOTPYTHON
python --version >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto GOTPYTHON
echo [錯誤] 找不到 Python。請先照架站說明安裝 Python 再回來。
echo.
pause
exit /b 1

:GOTPYTHON
if not exist "inventory.db" goto NODB

echo  這個系統目前有這些帳號:
echo.
%PYEXE% inventory_app.py --list-users
echo.

:ASKUSER
set "ACC="
set /p "ACC=請輸入要重設哪一個帳號(照上面打,大小寫要一樣):"
if not defined ACC goto ASKUSER

:ASKPW
set "PW="
set /p "PW=請輸入新密碼(至少 8 個字,英文數字都可以):"
if not defined PW goto ASKPW

echo.
%PYEXE% inventory_app.py --reset-password "%ACC%" "%PW%"
if errorlevel 1 goto FAILED

echo.
echo  完成。現在可以用這組登入了:
echo      帳號:%ACC%
echo      密碼:%PW%
echo.
echo  請把這組記下來。這個視窗關掉之後就看不到了。
echo  (如果系統本來就在跑,不需要重開,直接回瀏覽器登入即可。)
echo.
pause
exit /b 0

:FAILED
echo.
echo  沒有重設成功,原因請看上面那行訊息。常見狀況:
echo    - 帳號打錯(大小寫要一模一樣)
echo    - 新密碼少於 8 個字
echo  可以直接再跑一次這個檔案。
echo.
pause
exit /b 1

:NODB
echo [注意] 這個資料夾裡找不到 inventory.db,表示系統還沒建立過資料。
echo.
echo 請先雙擊 start_inventory.bat 把系統跑起來,
echo 用瀏覽器開啟後註冊第一個帳號(第一個註冊的人就是管理員)。
echo.
pause
exit /b 1
