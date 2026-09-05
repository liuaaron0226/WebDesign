"""把要交給使用者的檔案打包成 ZIP。

用法:python make_package.py [輸出目錄]

為什麼需要這個腳本,而不是直接下 `zip -r`:
ZIP 格式規定,檔名只要不是純英數,就必須在檔頭立起「這是 UTF-8」的旗標
(general purpose bit 11, 0x0800)。Linux 的 Info-ZIP 預設**不會**立那個旗標,
只是把 UTF-8 的位元組原封不動寫進去。Windows 內建的解壓縮看到沒有旗標,
就改用系統的舊編碼(繁體中文是 Big5/cp950)去解讀,解出來是亂碼,
接著 Explorer 直接跳「壓縮資料夾無效」,整包都打不開。

實際發生過:2026-09 交付給使用者的 `庫存管理系統_2026.09.05c.zip`
在 Windows 11 上完全無法解壓縮,而 `unzip -t` 在 Linux 上顯示檔案完全正常。

這裡的做法是雙保險:
  1. 用 Python 的 zipfile(非 ASCII 檔名會自動立旗標,合乎規範);
  2. 更重要的是,**壓縮檔內的路徑一律用純英數命名**,連立旗標這件事都不必仰賴,
     任何一版 Windows 的任何一種解壓縮工具都不會有機會出錯。
中文檔名只用在「使用者自己電腦上產生的檔案」(例如 同事連線網址.txt),
那是 Windows 自己寫的,不經過 ZIP,沒有這個問題。
"""
import os
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
FOLDER = "inventory-system"

# (repo 內的檔名, 壓縮檔內的路徑)。右邊一律純英數。
FILES = [
    ("inventory_app.py",       "inventory_app.py"),
    ("requirements.txt",       "requirements.txt"),
    ("start_inventory.bat",    "start_inventory.bat"),
    ("start_inventory.sh",     "start_inventory.sh"),
    ("setup_all.bat",          "setup_all.bat"),
    ("migrate_data.bat",       "migrate_data.bat"),
    ("migrate_bl_excel.py",    "migrate_bl_excel.py"),
    ("test_inventory.py",      "test_inventory.py"),
    ("公司內網架站指南.md",     "setup-guide.md"),
]


def app_version():
    with open(os.path.join(BASE, "inventory_app.py"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "unknown"


def build(out_dir):
    version = app_version()
    out = os.path.join(out_dir, f"inventory-system-{version}.zip")
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in FILES:
            path = os.path.join(BASE, src)
            if not os.path.exists(path):
                sys.exit(f"[錯誤] 找不到 {src},打包中止")
            z.write(path, f"{FOLDER}/{arc}")

    # 自我檢查:壞掉的包不如不要出。
    with zipfile.ZipFile(out) as z:
        broken = z.testzip()
        if broken:
            sys.exit(f"[錯誤] 壓縮檔損毀:{broken}")
        non_ascii = [i.filename for i in z.infolist() if not i.filename.isascii()]
        if non_ascii:
            sys.exit(f"[錯誤] 壓縮檔內出現非英數路徑,Windows 可能解不開:{non_ascii}")
        count = len(z.infolist())
    print(f"已產生 {out}")
    print(f"  版本 {version}、{count} 個檔案、{os.path.getsize(out)} bytes")
    print(f"  壓縮檔內路徑全為純 ASCII,Windows 內建解壓縮可正常開啟")
    return out


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "dist"))
