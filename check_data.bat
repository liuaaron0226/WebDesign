@echo off
setlocal
chcp 65001 >nul 2>nul
rem ============================================================
rem  庫存管理系統 - 我的資料在哪裡?
rem  用法:雙擊本檔案。會告訴你這個資料夾裡有沒有資料、有幾筆。
rem  注意:本檔必須是 CRLF 換行,否則 cmd 無法正確解析(見 .gitattributes)。
rem ============================================================

cd /d "%~dp0"
title 庫存管理系統 - 檢查資料位置

echo ============================================================
echo   檢查這個資料夾裡的資料
echo ============================================================
echo.
echo  如果你更新版本之後覺得「東西都不見了」,多半是把新版解壓縮到
echo  另一個資料夾、然後在那裡啟動。資料其實還在舊資料夾裡。
echo  這個工具會告訴你「現在這個資料夾」裡到底有什麼。
echo.

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
echo ------------------------------------------------------------
%PYEXE% inventory_app.py --where
echo ------------------------------------------------------------
echo.
echo  怎麼看:
echo    - 「商品」筆數是你預期的  = 這個資料夾就是對的,直接用。
echo    - 「商品」是 0 或看到星號 = 你在錯的資料夾,去找原本那個
echo                                裝著 inventory.db 的資料夾。
echo.
pause
