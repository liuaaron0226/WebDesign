# REQUIREMENTS.md — 驗收清單

本檔案是專案的**驗收依據**。任何程式修改在宣稱完成前,必須逐項對照本清單實際測試(執行 `/verify`)。每一項都要寫成「可實際驗證」的敘述,並附上驗證方式。

- 勾選狀態僅供人工追蹤;`/verify` 每次都會重新實測所有項目,不信任已勾選的狀態。
- 新任務若帶來新要求,**先把要求補進本清單**,再開始實作。

> 測試注意:用 `curl` 測多輸出時必須使用 `--form-string`(不能用 `-F`),否則值裡的 `;` 會被 curl 當成選項分隔符截斷。

## 功能驗收

- [ ] **首頁可載入**:GET `/` 回傳 HTTP 200,且頁面包含 `pi_input` 與 `minterms` 兩個 textarea 及檔案上傳欄位。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/` 應為 `200`;`curl -s http://localhost:5001/ | grep -c '<textarea'` 應為 `2`(注意要含 `<`,否則會多算到 CSS 裡的 `textarea` 選擇器)。
- [ ] **單輸出求解正確**:PI `A'C, AB`、minterms `2,3,12` 應得 `F0 → A'C + AB`。
  - 驗證:`curl -s -X POST http://localhost:5001/ --form-string "pi_input=A'C, AB" --form-string "minterms=2,3,12"`,輸出含 `A&#39;C + AB`。
- [ ] **多輸出(`;` 分隔)求解正確**:PI `A'B'C', A'B; A'C`、minterms `0,1,4; 2,6` 應得 `F0 → A'B'C' + A'B` 與 `F1 → A'C` 兩行結果。
  - 驗證:同上以 `--form-string` POST,輸出須同時含 `F0` 與 `F1` 行。
- [ ] **無解時顯示訊息而非報錯**:PI `AB`、minterm `0` 應顯示「找不到涵蓋所有 minterm 的組合」,HTTP 仍為 200。
  - 驗證:POST 後 grep 該訊息;不得出現 traceback 或 500。
- [ ] **`.txt` 上傳可覆蓋表單輸入**:上傳第 1 行為 PI、第 2 行為 minterms 的檔案,結果須依檔案內容計算(即使表單填了其他值)。
  - 驗證:`printf "A'C, AB\n2,3,12\n" > input.txt` 後以 `-F "input_file=@input.txt"` 上傳,輸出含 `A&#39;C + AB`。
- [ ] **求解結果為最小組合數**:`find_min_sop` 由小到大枚舉組合,回傳的 PI 個數必須是能涵蓋所有 minterm 的最少個數。
  - 驗證:讀碼確認枚舉順序未被更動;或設計一組有冗餘 PI 的輸入確認冗餘項未入選。

## 部署約束

- [ ] **Render 綁定不被破壞**:`app.run` 保持 `host="0.0.0.0"`,port 讀自環境變數 `PORT`(預設 5000)。
  - 驗證:`grep -n 'host="0.0.0.0"' patrick_method_solver.py` 與 `grep -n 'PORT' patrick_method_solver.py` 皆有結果。
- [ ] **`requirements.txt` 編碼不被意外破壞**:此檔為 UTF-16(Windows 存檔),`pip install -r requirements.txt` 必須能成功解析。
  - 驗證:`python -c "print(open('requirements.txt','rb').read(2))"` 應為 BOM `b'\xff\xfe'`;或直接跑 `pip install -r requirements.txt --dry-run`。

## 已知行為(非 bug,勿「修好」)

- 內建預設範例(PI `A'B, AB`、minterms `1,3`)的 F0 **數學上無解**(`A'B` 涵蓋 4–7、`AB` 涵蓋 12–15),顯示「找不到涵蓋所有 minterm 的組合」是正確結果。
- 變數固定為 `A,B,C,D` 四個,A 為最高位;非數字的 minterm 會被靜默略過。

## 介面與美術(patrick_method_solver.py)

> 視覺項目的驗證 = 自動檢查(curl/grep)+ Playwright 截圖(桌面 1280px、手機 390px)人工檢視;截圖必須附在驗收回報中。使用者的視覺回饋由 Claude 代寫成新條目加入本節。

- [ ] **RWD 手機可用**:HTML 含 viewport meta;390px 寬截圖無橫向捲軸、內容不溢出。
  - 驗證:`curl -s http://localhost:5001/ | grep -c 'name="viewport"'` ≥ 1;Playwright 以 390px 寬截圖檢視,並檢查 `document.documentElement.scrollWidth <= 390`。
- [ ] **非瀏覽器預設樣式**:有自訂配色、繁中友善字體堆疊、卡片式布局(頁面主體置中、有視覺層次)。
  - 驗證:HTML 的 `<style>` 含自訂 `font-family` 與背景色設定;截圖檢視非白底 Times/Arial 預設樣貌。
- [ ] **結果區清楚可讀**:計算結果與輸入表單有視覺區隔(不同底色/邊框),SOP 結果以等寬字體呈現。
  - 驗證:結果區 CSS 含 `monospace` 類字體堆疊與獨立底色;POST 預設範例後截圖檢視。
- [ ] **表單控件有樣式**:textarea 與送出按鈕經過設計(圓角/邊框/hover 狀態),按鈕為明顯的主色調。
  - 驗證:`<style>` 內含按鈕 hover 規則;截圖檢視。
- [ ] **對比度足夠**:內文文字與背景對比明顯(深色文字配淺色底),無灰底灰字。
  - 驗證:截圖檢視;主文字色與背景色的 CSS 值差異明顯。
- [ ] **介面文字為繁體中文**:標題、欄位說明、按鈕文字皆為繁中(與改版前一致)。
  - 驗證:`curl -s http://localhost:5001/ | grep -c '最小 SOP'` ≥ 1。

## 介面與美術(inventory_app.py)——導覽整合與大膽設計

> 來源:使用者視覺回饋(2026-08):「功能是很多,但我個人比較喜歡精簡,相關的功能就整合在一起」「美術設計方面需要大膽的多加使用,版面都太死板了」。視覺項目的驗證 = 自動檢查(curl/grep)+ Playwright 截圖(桌面 1280px、手機 390px)人工檢視;截圖必須附在驗收回報中。

- [ ] **導覽列精簡分組**:頂層導覽至多 6 個項目(總覽 + 功能群組 + 使用者區);相關功能收進群組選單(庫存作業/商品資料/分析報表/系統管理)。
  - 驗證:登入後任一頁 HTML 內 `<details class="menu"` ≥ 3(管理員 ≥ 4);頂層 `summary` 數 ≤ 5。
- [ ] **所有既有功能連結一個不少**:分組只是收納,17 條功能路由的入口全部保留。
  - 驗證:登入後首頁 HTML 同時 grep 得到 `/stock/in`、`/stock/out`、`/counts`、`/reservations`、`/alerts`、`/products/new`、`/suppliers`、`/search/image`、`/labels`、`/report`、`/history`、`/planning`(管理員另有 `/import`、`/audit`、`/users`)。
- [ ] **零 JavaScript 原則不破例**:群組選單以純 HTML `<details>/<summary>` 實現。
  - 驗證:登入後首頁 HTML `grep -c '<script'` = 0。
- [ ] **大膽視覺**:琥珀主色(CSS 變數)、深色表頭、KPI 色塊(統計卡有色彩區隔)、主要按鈕為主色而非藍色預設。
  - 驗證:`<style>` 含 `--amber` 變數、`th` 的 `background: var(--hull)` 規則、`.stat-box` 的語意色規則(`.stat-box.good` 等);截圖人工檢視「不死板」。
  - 註(第九階段修訂):代幣改名 `--accent` → `--amber`、`--ink` → `--hull`,理由是一色一義的規則要求名稱講出「這個顏色的意思」而不是「它是第幾個顏色」。
    KPI 色塊原本用 `nth-child(4n+2)` 依**位置**輪流換色——顏色由排第幾個決定而不是由意思決定,等於顏色不傳遞任何資訊;改為由樣板指定 `.stat-box.good/.warn/.bad/.info`。
- [ ] **手機 390px 無橫向捲軸**(分組後導覽更省空間,不得倒退)。
  - 驗證:Playwright 390px 寬檢查 `document.documentElement.scrollWidth <= 390`。
- [ ] **截圖迭代至少 2 輪**:桌面與手機截圖自我審視後再修,最終截圖以 SendUserFile 附上,由使用者做最終美術裁決。

## 庫存管理系統(inventory_app.py)驗收

> 測試前置:先清掉測試資料庫再啟動,session 測試需 cookie jar。**本節條目有順序相依(註冊→登入→建供應商→建商品→入出庫→報表),必須依序執行**;每輪驗收都要先 `rm -f /tmp/verify_inventory.db` 取得乾淨 DB,否則「重複帳號」「首位管理員」等項會誤判。
>
> ```bash
> rm -rf /tmp/verify_inventory.db* /tmp/inv_cookies.txt /tmp/verify_inventory_images /tmp/backups /tmp/secret_key.txt
> INVENTORY_DB=/tmp/verify_inventory.db INVENTORY_IMAGES=/tmp/verify_inventory_images PORT=5002 python inventory_app.py &
> ```

- [ ] **未登入一律導向登入頁**:未帶 cookie GET `/` 回 302,跟隨後可見登入頁。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/` 為 `302`;`curl -s -L http://localhost:5002/ | grep -c 登入` ≥ 1。
- [ ] **首位可註冊且自動為管理員;之後關閉自助註冊**(第四階段起的行為:帳號改由管理員建立,見「安全」節)。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/register --form-string "username=admin1" --form-string "password=pass1234"` 為 `302`;`python3 -c "import sqlite3; print(sqlite3.connect('/tmp/verify_inventory.db').execute('select is_admin from users where username=?',('admin1',)).fetchone())"` 為 `(1,)`;再次 POST `/register`(任何帳號)輸出含「不開放自助註冊」且使用者數不變。
- [ ] **登入成功建立 session、失敗顯示訊息**。
  - 驗證:`curl -s -c /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/login --form-string "username=admin1" --form-string "password=pass1234"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep 庫存總覽`;錯誤密碼 POST 後輸出含「帳號或密碼錯誤」。
- [ ] **供應商新增後列表可見**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/suppliers/new --form-string "name=大同貿易" --form-string "contact=王先生" --form-string "phone=0912345678"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/suppliers | grep 大同貿易`。
- [ ] **商品新增成功且 SKU 唯一**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/new --form-string "name=可樂" --form-string "sku=SKU001" --form-string "category=飲料" --form-string "unit=瓶" --form-string "unit_price=25" --form-string "low_stock_threshold=10" --form-string "supplier_id=1"` 為 `302`;首頁 grep `SKU001`;重送同 SKU 後輸出含「SKU 已存在」。
- [ ] **入庫增加庫存並記錄**:入庫 50 後庫存為 50。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/stock/in --form-string "product_id=1" --form-string "quantity=50" --form-string "note=首批進貨"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep 'id="qty-1">50<'`。
- [ ] **出庫減少庫存**:出庫 20 後庫存為 30。
  - 驗證:POST `/stock/out`(product_id=1, quantity=20)回 302;首頁 grep `id="qty-1">30<`。
- [ ] **出庫不得使庫存為負**:出庫 999 被拒、庫存不變。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -X POST http://localhost:5002/stock/out --form-string "product_id=1" --form-string "quantity=999" | grep 庫存不足`;首頁仍 grep 到 `id="qty-1">30<`。
- [ ] **搜尋商品**:`/?q=可樂` 有結果、`/?q=zzz` 顯示查無商品。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt --get --data-urlencode "q=可樂" http://localhost:5002/ | grep SKU001`(中文 query 必須用 `--data-urlencode` 正確編碼,直接塞進 URL 不符合 HTTP 規範會查不到);`curl -s -b /tmp/inv_cookies.txt "http://localhost:5002/?q=zzz" | grep 查無商品`。
- [ ] **低庫存警示**:再出庫 25(庫存 5 ≤ 門檻 10)後,首頁該列標示低庫存、`/alerts` 列出該商品。
  - 驗證:POST `/stock/out`(quantity=25)後,`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep low-stock`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/alerts | grep 可樂`。
- [ ] **異動歷史含操作人員並可篩選**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/history` 輸出同時含 `<td>入庫</td>`、`<td>出庫</td>`、`admin1`;`curl -s -b /tmp/inv_cookies.txt "http://localhost:5002/history?type=in" | grep -c '<td>出庫</td>'` 為 `0`(比對必須用 `<td>` 包住,否則會誤抓到導覽列的「出庫」連結)。
- [ ] **報表顯示進出統計與庫存價值**:目前狀態應為入庫總量 50、出庫總量 45、庫存 5、單價 25 → 庫存價值 125。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/report` 輸出含 `50`、`45`、`125`(分別對應入庫、出庫、總價值,以報表列的 id 或欄位精準比對)。
- [ ] **CSV 匯出(UTF-8 BOM,Excel 中文不亂碼)**:兩個匯出端點皆為 text/csv、檔案開頭為 BOM、含中文內容。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /tmp/inv.csv -w "%{content_type}" http://localhost:5002/export/inventory.csv` 含 `text/csv`;`python3 -c "print(open('/tmp/inv.csv','rb').read(3)==b'\xef\xbb\xbf')"` 為 `True`;`grep 可樂 /tmp/inv.csv`;`/export/transactions.csv` 同法驗 BOM 且 grep `首批進貨`。
- [ ] **登出後失去存取權**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -c /tmp/inv_cookies.txt -o /dev/null http://localhost:5002/logout` 後,`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" http://localhost:5002/history` 為 `302`。
- [ ] **Render 綁定與依賴管理**:`host="0.0.0.0"` 與 port 讀 `$PORT`(預設 5000)的契約不變(第四階段起由 waitress 提供服務,未安裝時 fallback 到 `app.run`);`requirements.txt` 維持 UTF-16 編碼且 pip 可解析,內容為 Flask + Pillow(以圖搜圖)+ waitress(正式伺服器)+ qrcode(料架標籤)。
  - 驗證:`grep -c 'host="0.0.0.0"' inventory_app.py` ≥ 1、`grep -n 'PORT' inventory_app.py` 有結果;`python3 -c "print(open('requirements.txt','rb').read(2))"` 為 `b'\xff\xfe'`;`python3 -c "print('Pillow' in open('requirements.txt', encoding='utf-16').read())"` 為 `True`;`pip install -r requirements.txt --dry-run` 成功。
- [ ] **inventory.db 不入版控**。
  - 驗證:`grep -n 'inventory.db' .gitignore` 有結果;`git status --porcelain | grep inventory.db` 為空。
- [ ] **原 Patrick app 不受影響**:上方「功能驗收」「部署約束」全部條目(PORT=5001)回歸通過。
  - 驗證:執行本清單上半部所有項目。

## 庫存系統第二階段:料號整合、照片、以圖搜圖、快速登記、內網限制

> 接續上節測試序列執行(同一個測試 DB;上節結尾已登出,本節開頭先重新登入)。照片目錄用 `INVENTORY_IMAGES=/tmp/verify_inventory_images` 啟動,每輪驗收先 `rm -rf` 該目錄。測試圖以 PIL 產生(純紅色 vs 黑白漸層,兩張截然不同)。

- [ ] **商品詳細頁**:GET `/products/1` 包含品名、庫存、「照片」區、「跨公司料號對照」區、「近期異動」區。
  - 驗證:重新登入後 `curl -s -b /tmp/inv_cookies.txt http://localhost:5002/products/1` 輸出含「可樂」「照片」「跨公司料號對照」「近期異動」。
- [ ] **跨公司料號別名:新增、用別名搜尋找到本尊、重複組合被拒**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/1/aliases --form-string "company=台達電" --form-string "alias_sku=DELTA-123"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt --get --data-urlencode "q=DELTA-123" http://localhost:5002/ | grep SKU001`;重送同組合輸出含「此公司+料號組合已存在」。
- [ ] **CSV 商品匯入(UTF-8)**:匯入 2 筆新商品(含初始庫存)成功,重複 SKU 列被跳過並回報行號原因;初始庫存產生 `in` 異動(note=CSV匯入)。
  - 驗證:製作 UTF-8 CSV(標題列 `SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存`,含 SKU002 滑鼠/庫存 30、SKU003 鍵盤/庫存 20、SKU001 重複列),`curl -s -b /tmp/inv_cookies.txt -X POST http://localhost:5002/import -F "mode=products" -F "csv_file=@/tmp/test_products.csv"` 輸出含「成功匯入 2 筆」與「SKU 已存在」;首頁 grep `id="qty-2">30<`;`/history` 含「CSV匯入」。
- [ ] **CSV 商品匯入(cp950/Big5,台灣 Excel 編碼)**:cp950 編碼的 CSV 也能正確匯入中文。
  - 驗證:以 Python 產生 cp950 編碼 CSV(SKU004 螢幕),匯入後首頁 grep `SKU004` 與 `螢幕`。
- [ ] **CSV 別名匯入**:匯入後用別名料號搜尋找得到本尊商品。
  - 驗證:製作別名 CSV(標題列 `我方SKU,公司,別名料號,備註`,一列 `SKU002,群光,CHICONY-M100,`),匯入輸出含「成功匯入 1 筆」;`/?q=CHICONY-M100` grep `SKU002`。
- [ ] **照片上傳與顯示**:上傳 PNG 到商品後詳細頁出現 `<img`,檔案落在照片目錄;非圖片副檔名被拒。
  - 驗證:PIL 產生 `/tmp/red.png`(純紅)上傳 `curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/1/images -F "photo=@/tmp/red.png"` 為 `302`;`/products/1` 含 `<img`;`ls /tmp/verify_inventory_images/ | grep -c png` ≥ 1;上傳 `.txt` 檔輸出含「不支援的檔案格式」。
- [ ] **以圖搜圖:最相似者排第一**:兩張截然不同的照片分掛兩商品後,用與其中一張相近的圖搜尋,第一名必須是掛該照片的商品。
  - 驗證:PIL 產生 `/tmp/gradient.png`(黑白漸層)上傳到商品 2;再以 `/tmp/red_query.png`(接近純紅、少量雜訊)POST `/search/image`,回應中 SKU001 出現位置早於 SKU002,且含「相似度」。
- [ ] **連續登記便利**:入庫成功後 302 導回入庫頁並顯示成功訊息(含品名與最新庫存),出庫同理。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -i -X POST http://localhost:5002/stock/in --form-string "product_id=1" --form-string "quantity=10" --form-string "note=連續登記測試" | grep -i "^location:"` 含 `/stock/in`;跟隨 redirect 後頁面含「入庫成功」與「目前庫存」。
- [ ] **ALLOWED_IPS 內網白名單**:未設定時行為完全不變(本清單其他條目即為證明);設定後非名單來源一律 403,名單內來源正常。
  - 驗證:另啟動一個實例 `ALLOWED_IPS=203.0.113.5 INVENTORY_DB=/tmp/verify_inventory.db PORT=5003 python inventory_app.py`;`curl -s -o /dev/null -w "%{http_code}" http://localhost:5003/` 為 `403` 且回應含「僅限公司內部網路」;`curl -s -o /dev/null -w "%{http_code}" -H "X-Forwarded-For: 203.0.113.5" http://localhost:5003/` 為 `302`(正常導向登入)。測畢 kill 該實例。
- [ ] **內網部署啟動腳本存在且正確**:`start_inventory.bat`(Windows)與 `start_inventory.sh`(Mac/Linux)皆存在,內容含依賴安裝與 `python inventory_app.py` 啟動(讀碼驗證)。
  - 驗證:`grep -l "inventory_app.py" start_inventory.bat start_inventory.sh` 列出兩檔;`bash -n start_inventory.sh` 無語法錯誤。

## 庫存系統第三階段:批次管理與存貨管理理論(FIFO/庫齡/成本/ABC)

> 接續上節測試序列執行(同一測試 DB、同一 cookie jar,上節結尾為已登入狀態、商品 1 庫存 12)。理論依據:批次追溯(Lot Tracking)、先進先出(FIFO)、庫齡分析(Inventory Aging)、加權平均成本(存貨計價)、ABC 分析(柏拉圖法則)。

- [ ] **入庫自動建立批次**:每筆入庫建立一個批次(自動批號 `L<日期>-<流水>`),商品詳細頁有「批次庫存」區,依入庫時間排序顯示批號、入庫時間、庫齡、剩餘數量。
  - 驗證:POST `/stock/in`(product_id=1, quantity=10)後,`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/products/1` 輸出含「批次庫存」「庫齡」與自動批號前綴 `L20`。
- [ ] **自訂批號與成本單價;同商品批號不可重複**:入庫可填批號(如供應商批號)與成本單價。
  - 驗證:POST `/stock/in`(product_id=1, quantity=5, lot_no=B-TEST-01, unit_cost=12.5)回 302,詳細頁含 `B-TEST-01`;重送同批號輸出含「此商品已有相同批號」。
- [ ] **FIFO 先進先出出庫**:出庫自動從最早批次扣起,跨批次分攤;批次剩餘總和恆等於商品現時庫存。
  - 驗證:新建商品(sku=SKU005)→ 入庫 10(自動批)→ 入庫 20(lot_no=B2)→ 出庫 15;以 sqlite 查該商品批次 `qty_remaining` 依序為 `[0, 15]`,且總和等於 `products.quantity`(15)。
- [ ] **批次追溯**:出庫異動記錄消耗了哪些批次;異動歷史顯示批次明細(入庫顯示批號、出庫顯示各批消耗量)。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/history` 輸出含 `B2×5`(上一項出庫 15 = 首批×10 + B2×5)。
- [ ] **全商品批次帳一致性**:所有商品的批次剩餘總和 = `products.quantity`(含 CSV 匯入初始庫存也建批次)。
  - 驗證:sqlite 逐商品比對 `SUM(lots.qty_remaining)` 與 `quantity`,全部相等。
- [ ] **報表:庫齡分析**:報表頁有「庫齡分析」區,依 0-30 / 31-60 / 61-90 / 90 天以上分桶統計在庫數量。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/report | grep 庫齡分析` 且含 `0-30 天`。
- [ ] **報表:加權平均成本**:有記成本的商品顯示加權平均成本(僅以尚有剩餘且有成本的批次計算)。
  - 驗證:`/report` 輸出含「平均成本」且含 `12.5`(商品 1 唯一有成本批次 B-TEST-01)。
- [ ] **報表:ABC 分析**:依庫存價值由高至低累積占比分級(≤80% 為 A、≤95% 為 B、其餘 C)。
  - 驗證:`/report` 輸出含「ABC 分析」與 A/B/C 分級標示。
- [ ] **期初庫存自動補批(讀碼驗證)**:啟動時若商品現時庫存大於批次剩餘總和(舊資料庫升級情境),自動建立期初批補齊,批次帳不留缺口。
  - 驗證:讀碼確認 reconcile 函式存在且於啟動時執行。
- [ ] **既有全部條目回歸**:上方 Patrick、一階段、二階段所有條目全數重測通過。
  - 驗證:執行本清單全部項目。

## 庫存系統第四階段:安全強化與營運韌性

> 本節條目來自五視角系統檢測(安全/資料完整/邊界/效能/品質)的實測發現。部分條目需獨立實例測試,測畢務必 kill。
> 自動化測試:`python test_inventory.py` 必須全綠,是本節的第一道關卡。

### 安全

- [ ] **無法用原始碼裡的舊金鑰偽造登入**:程式不得有硬編碼的可預測 SECRET_KEY;未設環境變數時自動產生持久隨機金鑰檔。
  - 驗證:`grep -c 'dev-inventory-secret-change-me' inventory_app.py` 為 `0`;啟動後 `ls <DB目錄>/secret_key.txt` 存在;用舊字串 `dev-inventory-secret-change-me` 以 itsdangerous 簽出 `{"user_id":1}` 的 session cookie,帶該 cookie GET `/` 必須為 `302`(被拒),而非 200。
- [ ] **IP 白名單不可用偽造標頭繞過**:預設只採實際連線來源;`TRUST_PROXY` 未開啟時 X-Forwarded-For 一律不採信。
  - 驗證:以 `ALLOWED_IPS=203.0.113.5 PORT=5004` 啟動獨立實例;`curl -o /dev/null -w "%{http_code}" http://localhost:5004/` 為 `403`;**帶** `-H "X-Forwarded-For: 203.0.113.5"` 仍必須為 `403`(修正前為 200);再以 `ALLOWED_IPS=127.0.0.1` 啟動則為 `302`。
- [ ] **權限分層:非管理員不可刪除與匯入**:一般使用者 POST 刪除商品/供應商/照片/別名與 `/import` 皆回 403;入庫/出庫/新增商品/查詢不受影響。
  - 驗證:管理員建立一般帳號 `staff1` 後以其 cookie:POST `/products/1/delete` 為 `403`、POST `/import` 為 `403`、GET `/users` 為 `403`;但 POST `/stock/in` 為 `302`、GET `/` 為 `200`。
- [ ] **非管理員介面不顯示管理功能**:一般使用者的頁面不出現「CSV 匯入」「帳號管理」導覽項與刪除按鈕。
  - 驗證:staff1 的 GET `/` 輸出 `grep -c '帳號管理'` 為 `0`、`grep -c 'CSV 匯入'` 為 `0`。
- [ ] **關閉自助註冊,帳號由管理員建立**:已有使用者後 `/register` 不再開放;管理員可於 `/users` 新增帳號與重設密碼。
  - 驗證:已有帳號時 POST `/register` 輸出含「請洽管理員」且 DB 使用者數不變;管理員 POST `/users/new`(username=staff1, password=staff1234)為 `302`,`/users` 頁可見 `staff1`;POST `/users/password`(帶 `user_id` 與新密碼)後回應含「已重設」(此端點就地重繪帳號頁,回 200 而非 302),且 staff1 可用新密碼登入。
- [ ] **管理員帳號保護**:不可刪除自己、不可刪除最後一位管理員。
  - 驗證:管理員 POST 刪除自己的帳號,輸出含「不可刪除自己」且帳號仍在。
- [ ] **CSV 匯出防公式注入**:以 `=`、`+`、`-`、`@` 開頭的欄位在匯出時被跳脫。
  - 驗證:新增商品名稱為 `=2+5`,`/export/inventory.csv` 下載後 `grep -c "'=2+5"` ≥ 1(前置單引號),且不得出現行首未跳脫的 `=2+5`。
- [ ] **上傳大小上限**:超過 10MB 的上傳回 413 友善中文訊息而非佔滿記憶體。
  - 驗證:`head -c 12000000 /dev/urandom > /tmp/big.bin`,POST 至 `/products/1/images` 回 `413`,回應含「檔案過大」。
- [ ] **密碼長度與登入鎖定**:密碼至少 8 碼;同帳號連續 5 次密碼錯誤後暫時鎖定。
  - 驗證:建立帳號時密碼填 `abc` 輸出含「至少 8 碼」;對某帳號連續 6 次錯誤密碼登入,第 6 次輸出含「嘗試次數過多」。

### 穩定與效能

- [ ] **SQLite 啟用 WAL 與 busy_timeout**:多人同時讀寫不再出現 `database is locked` 的 500。
  - 驗證:`python3 -c "import sqlite3;print(sqlite3.connect('/tmp/verify_inventory.db').execute('PRAGMA journal_mode').fetchone()[0])"` 為 `wal`。
- [ ] **並發實測:讀取歷史時他人入庫不失敗**:一條 `/history` 請求進行中同時發 4 筆入庫,全部須為 302 且庫存正確累加。
  - 驗證:背景發 `/history` 後立刻並發 4 筆 `POST /stock/in`(各 1 個單位),4 筆皆 `302`,事後該商品庫存正好增加 4。
- [ ] **lots 交易索引存在**:異動歷史與匯出不因批次表全表掃描而變慢。
  - 驗證:`python3 -c "import sqlite3;print([r[0] for r in sqlite3.connect('/tmp/verify_inventory.db').execute(\"select name from sqlite_master where type='index'\")])"` 含 `idx_lots_tx`。
- [ ] **超大數字回友善訊息而非 500**:數量/門檻/單價超出合理範圍時顯示中文提示。
  - 驗證:POST `/stock/in` quantity=`999999999999999999999999999` 回 `200` 且含「數量」提示(不得為 500);POST `/products/new` low_stock_threshold 同樣超大值亦不得 500。
- [ ] **isdigit 陷阱不再造成 500**:Unicode 數字字元不得使頁面崩潰。
  - 驗證:POST `/stock/out` quantity=`²` 不得為 500;GET `/history?product_id=%C2%B2` 不得為 500。
- [ ] **inf/nan 不得污染報表**:單價/成本填 `inf` 或 `nan` 被拒。
  - 驗證:POST `/products/new` unit_price=`inf` 輸出含「有效的非負數字」且商品未被建立。
- [ ] **CSV 匯入壞列跳過、好列照匯**:單列數字異常不得毀掉整批。
  - 驗證:匯入含 2 筆正常列 + 1 筆超大數字列的 CSV,回應為 `200` 且含「成功匯入 2 筆」,DB 中兩筆正常商品存在(修正前整批 500 全毀)。
- [ ] **清單分頁**:首頁與異動歷史預設分頁,不再一次吐出全部資料;CSV 匯出仍為完整資料。
  - 驗證:讀碼確認 `query_products`/`query_transactions` 具 limit/offset 且匯出端點傳 `limit=None`;`/history` 頁面含「下一頁」或「第 1 頁」字樣。
- [ ] **正式伺服器 waitress**:以 waitress 提供服務,未安裝時可 fallback;Render 綁定字面不變。
  - 驗證:`grep -c 'waitress' inventory_app.py` ≥ 1;`grep -c 'host="0.0.0.0"' inventory_app.py` ≥ 1;`python3 -c "print('waitress' in open('requirements.txt', encoding='utf-16').read())"` 為 `True`;啟動 log 不再出現 `development server` 警告。
- [ ] **刪除商品同時清除照片檔**:不留孤兒檔案。
  - 驗證:建立商品→上傳照片→刪除商品後,照片目錄中該商品的 `img_<pid>_*` 檔案不存在。

### 維運

- [ ] **自動備份**:啟動時產生一份備份,保留最近 14 份;設定 `BACKUP_DIR` 時同步複製一份到該路徑。
  - 驗證:啟動後 `ls <DB目錄>/backups/inventory_*.db` 至少 1 個檔;備份檔可被 sqlite 開啟且含 `users`/`products`/`lots` 等資料表(啟動時的備份先於首位註冊,故 users 可能為 0 筆,屬正常);以 `BACKUP_DIR=/tmp/verify_backup` 啟動的實例,該目錄亦有備份檔。
- [ ] **稽核軌跡**:商品/供應商/別名/照片的新增編輯刪除、CSV 匯入、帳號管理皆留下紀錄,管理員可於 `/audit` 檢視。
  - 驗證:管理員 GET `/audit` 為 `200`,內容含先前操作的動作與操作者 `admin1`;一般使用者 GET `/audit` 為 `403`。
- [ ] **時間以台灣時間顯示**:頁面與 CSV 的時間欄為台灣時間(UTC+8),資料庫仍存 UTC。
  - 驗證:`/history` 表頭含「時間(台灣)」;剛建立的異動,其顯示時間與 `date -u +%H` 相差 8 小時(或以 python 比對 DB 中 UTC 字串 +8 小時等於頁面顯示值)。
- [ ] **日期篩選以台灣日期為準仍正確**:報表既有數字條目(入 50 / 出 45 / 價值 125)不受時區改動影響。
  - 驗證:重跑第一階段報表條目,結果不變。
- [ ] **自動化測試全綠**:`test_inventory.py` 覆蓋 FIFO、批次帳恆等式、加權平均成本、ABC、庫齡、權限、輸入邊界、CSV 匯入韌性、公式注入防護。
  - 驗證:`python3 test_inventory.py` 結束碼為 `0` 且輸出含 `OK`。
- [ ] **既有 104 檢查點全數回歸**:Patrick、一階段、二階段、三階段所有條目重測通過。
  - 驗證:執行本清單全部項目。

## 庫存系統第五階段:業界標準功能補完(盤點/儲位/QR/預留/單位/安全庫存/XYZ/效期/歸屬)

> 條目來源:業界系統(SAP EWM、Odoo、WMS 實務、台灣 ERP)與學術文獻(IRI 研究、安全庫存公式、ABC-XYZ)的差距分析。
> 接續上節測試序列;需要新測試資料的條目會自行建立。

### 循環盤點與差異調整(帳實相符的核心機制)

- [ ] **可建立盤點單並依範圍帶入商品**:支援全部商品、依 ABC 分級、依分類三種範圍。
  - 驗證:管理員 POST `/counts/new`(`name=測試盤點`, `scope=all`)回 `302`;`/counts` 列表含「測試盤點」;盤點單頁面列出的品項數等於商品總數。
- [ ] **輸入實盤數即時顯示差異**:輸入與系統帳不同的數量後,盤點頁顯示差異數。
  - 驗證:POST `/counts/<id>/count`(`product_id=1`, `counted_qty=<系統帳-3>`)後,盤點頁含「-3」。
- [ ] **過帳自動修正帳並維持批次帳恆等式**:盤虧依 FIFO 消耗批次、盤盈建立調整批;過帳後 `products.quantity` 等於實盤數,且批次剩餘總和仍等於庫存。
  - 驗證:過帳後查 sqlite:該商品 `quantity` 等於實盤數;全商品 `SUM(lots.qty_remaining) == quantity` 無例外;`/history` 出現「盤點調整」異動。
- [ ] **過帳留下稽核軌跡且不可重複過帳**:
  - 驗證:`/audit` 含「盤點過帳」;對同一張已過帳的盤點單再次 POST `/counts/<id>/post` 輸出含「已過帳」。
- [ ] **庫存準確率 KPI**:報表顯示最近一次盤點的準確率(相符品項數 ÷ 盤點品項數)。
  - 驗證:`/report` 輸出含「庫存準確率」與百分比數值。
- [ ] **一般使用者可盤點但不可過帳**:
  - 驗證:staff cookie POST `/counts/<id>/count` 為 `302`;POST `/counts/<id>/post` 為 `403`。

### 儲位與 QR 標籤(現場作業)

- [ ] **商品可設定儲位並可用儲位搜尋**:
  - 驗證:編輯商品設 `location=A-03-2` 後,首頁 `?q=A-03-2` 找得到該商品;商品詳細頁顯示該儲位。
- [ ] **QR 標籤可產生**:`/products/<id>/qr.png` 回傳 PNG 圖檔。
  - 驗證:`curl -o /tmp/qr.png -w "%{content_type}"` 含 `image/png`;檔案前 8 bytes 為 PNG 簽章 `\x89PNG\r\n\x1a\n`。
- [ ] **標籤列印頁列出所有商品的 QR 與儲位**:
  - 驗證:GET `/labels` 為 `200`,含 `<img` 且含料號與儲位文字。
- [ ] **掃 QR 可直達商品頁**:QR 內容為該商品詳細頁的完整網址。
  - 驗證:讀碼確認 QR 內容以 `/products/<id>` 結尾(可用 python 解碼或讀碼驗證產生邏輯)。

### 單位換算與領用歸屬

- [ ] **可設定採購單位與換算率,入庫時自動換算**:設「1 箱 = 100 個」後,以採購單位入庫 2,庫存增加 200。
  - 驗證:編輯商品設 `purchase_unit=箱`、`units_per_purchase=100`;POST `/stock/in`(`quantity=2`, `qty_unit=purchase`)後庫存增加 `200`,異動紀錄數量為 `200`。
- [ ] **出庫可填結構化用途(工單/部門)並可篩選**:
  - 驗證:POST `/stock/out` 帶 `purpose=WO-1001`;`/history` 顯示 `WO-1001`;`/history?purpose=WO-1001` 只含該筆(用途含中文時,curl 須用 `--get --data-urlencode` 編碼)。

### 預留與可用量

- [ ] **可建立預留,首頁顯示可用量 = 現貨 − 預留**:
  - 驗證:對庫存 N 的商品 POST `/reservations/new`(`quantity=5`)回 `302`;首頁該商品可用量欄顯示 `N-5`;`id="qty-<id>"`(現貨)維持 `N`。
- [ ] **預留可釋放,釋放後可用量回復**:
  - 驗證:POST `/reservations/<id>/release` 回 `302`;可用量回到 `N`。
- [ ] **預留量不可超過現貨**:
  - 驗證:預留數量大於現貨時輸出含「可用量不足」,且未建立預留。
- [ ] **低庫存警示改以可用量判斷**:
  - 驗證:讀碼確認警示查詢使用可用量;預留使可用量低於門檻時,`/alerts` 列出該商品。

### 安全庫存推導、ABC-XYZ、效期

- [ ] **系統依用量變異推導建議安全庫存**:規劃頁列出每個有用量歷史的商品的日均用量、標準差、建議門檻。
  - 驗證:GET `/planning` 為 `200`,含「建議安全庫存」「日均用量」與服務水準說明;有出庫歷史的商品顯示數值而非「—」。
- [ ] **可一鍵套用建議門檻**:
  - 驗證:POST `/planning/apply` 後回應含「低庫存門檻更新為建議安全庫存」(此端點與 `/users/password`、`/counts/<id>/post` 同屬「就地重繪並附結果摘要」的例外,回 200 而非 302);該商品 `low_stock_threshold` 變為建議值(以 sqlite 比對)。
- [ ] **前置期與服務水準可設定並影響建議值**:
  - 驗證:把商品 `lead_time_days` 由 7 改為 28 後,`/planning` 的建議值變大(前置期越長需備越多)。
- [ ] **ABC-XYZ 九宮格**:報表顯示每個商品的 XYZ 分級(依需求變異係數)與 ABC-XYZ 組合。
  - 驗證:`/report` 含「XYZ」與 `AX`/`AZ`/`CX`/`CZ` 之類的組合標示。
- [ ] **批次可記錄有效期,即將到期會警示**:
  - 驗證:入庫時帶 `expiry_date`(設為 10 天後)後,`/alerts` 含「即將到期」與該批號。
- [ ] **FEFO 策略:設為 FEFO 的商品出庫先出最早到期批**:
  - 驗證:建立商品設 `issue_strategy=FEFO`;先入一批效期較晚、再入一批效期較早,出庫後以 sqlite 確認**效期較早的批**先被消耗。

### 回歸

- [ ] **既有全部條目回歸**:Patrick、一~四階段所有條目重測通過,`python test_inventory.py` 全綠。
  - 驗證:執行本清單全部項目。

## 部署與首次啟動(實機裝機問題修正)

> 來源:使用者實際在公司電腦照步驟裝機失敗。以下條目確保「下載 → 雙擊 → 建帳號」這條路走得通。

- [ ] **Windows 批次檔必須是 CRLF 換行**:`start_inventory.bat` 若為 Unix(LF)換行,cmd.exe 解析多行區塊會出錯,等於無法執行。
  - 驗證:`python3 -c "raw=open('start_inventory.bat','rb').read(); print(raw.count(b'\r\n') > 0 and raw.count(b'\n') == raw.count(b'\r\n'))"` 為 `True`(每一行都是 CRLF)。
- [ ] **`.gitattributes` 鎖定批次檔換行**:避免日後在 Linux/Mac 編輯後又被改回 LF。
  - 驗證:`grep -c '\*.bat' .gitattributes` ≥ 1 且含 `eol=crlf`。
- [ ] **啟動腳本能適應 Windows 的兩種 Python 呼叫方式**:優先用 `py` 啟動器,找不到才用 `python`(可避開 Microsoft Store 的假 python.exe)。
  - 驗證:`grep -c 'py -3' start_inventory.bat` ≥ 1 且 `grep -c 'python' start_inventory.bat` ≥ 1。
- [ ] **依賴安裝失敗時要明確停下並提示**,而不是繼續執行然後噴 ImportError。
  - 驗證:`grep -c 'goto PIPFAIL\|errorlevel' start_inventory.bat` ≥ 1;讀碼確認失敗分支有 `pause`。
- [ ] **首次啟動(零帳號)自動導向建立管理員頁**:全新安裝打開首頁不應停在登入頁,而應直接進到「建立管理員帳號」。
  - 驗證:以全新 DB 啟動後,`curl -s -L http://localhost:5002/ | grep -c '建立管理員帳號'` ≥ 1;建立帳號後再開首頁則導向一般登入頁(`grep -c '登入庫存管理系統'` ≥ 1)。
- [ ] **已有帳號時 `/register` 仍維持關閉**(不得因上一項而被繞過)。
  - 驗證:已有使用者時 POST `/register` 輸出仍含「不開放自助註冊」。

## 庫存系統第六階段:多格式匯入與收貨待驗流程(ASN)

> 來源:使用者需求「支援多種檔案的匯入,像是 Excel 等等」「假如有收到通知確認到這一批貨料,會預先登記在系統,省去員工打字輸入可能會出問題,等確認料無誤就可以放行,登記完成」。
> 對應業界作法:ASN(Advanced Shipping Notice,預先到貨通知)+ 收貨待驗放行。核心價值是**入庫資料來自供應商的檔案而非人工重打**,且**未放行前不動庫存**。

### 多格式匯入

- [ ] **`/import` 支援 Excel(.xlsx)**:除既有 CSV 外,可直接上傳 Excel 檔匯入商品與別名,不必先另存 CSV。
  - 驗證:以 openpyxl 產生 `.xlsx` 商品檔上傳 `/import`(mode=products),回應含「成功匯入」且該 SKU 出現在 `products` 表。
- [ ] **支援 Tab 分隔(TSV/貼上文字檔)**:副檔名 `.txt`/`.tsv` 或內容以 Tab 分隔時自動辨識分隔符。
  - 驗證:上傳 tab 分隔的別名檔,匯入成功筆數 ≥ 1。
- [ ] **Excel 讀取為選用依賴,缺少時系統仍可啟動**:未安裝 openpyxl 時 app 正常運作,僅該功能顯示提示(比照 Pillow/qrcode 的降級設計)。
  - 驗證:讀碼確認 `HAS_OPENPYXL` 旗標與 try/except import;`grep -c 'openpyxl' requirements.txt`(UTF-16 解碼後)≥ 1。
- [ ] **Excel 的數字/日期儲存格轉為乾淨字串**:數量欄讀到 `100.0` 或日期物件時不得讓整批匯入失敗。
  - 驗證:Excel 檔中數量以數字型別寫入,匯入後 `products.quantity` 為正確整數。
- [ ] **無法辨識的檔案給友善訊息**:上傳舊版 `.xls` 或亂碼檔時回明確中文提示,不得 500。
  - 驗證:上傳 `.xls` 副檔名檔案,回應含「請另存為 .xlsx」且 HTTP 200。

### 收貨單:預先登記 → 核對 → 放行

- [ ] **上傳供應商檔案即建立收貨單**:上傳 Excel/CSV(欄位:料號,品名,數量,批號,效期,單價,備註)後建立一張收貨單,狀態為「待核對」。
  - 驗證:POST `/receipts/upload` 帶檔案,回 302;`receipts` 表新增一列且 `status='open'`,`receipt_items` 列數等於資料列數。
- [ ] **未放行前庫存完全不變**(最關鍵的一條):建立收貨單只是預先登記,不得動到 `products.quantity`、`transactions`、`lots`。
  - 驗證:建立收貨單前後比對該商品 `quantity` 相同,且 `transactions` 筆數不變。
- [ ] **料號自動比對我方 SKU**:檔案料號等於我方 SKU 時自動對應到該商品,`match_type='sku'`。
  - 驗證:上傳含既有 SKU 的檔案,對應列的 `product_id` 正確且明細頁顯示「我方料號」。
- [ ] **料號自動比對跨公司別名**(本系統既有強項的延伸):檔案上是供應商自己的料號時,透過 `part_aliases` 對應到我方商品,`match_type='alias'`。
  - 驗證:先建立別名(公司=大同貿易,別名料號=DE-B0620),上傳以 `DE-B0620` 為料號的收貨檔,該列自動對應到我方商品且明細頁顯示別名來源。
- [ ] **對不上的列明確標示「未對應」**,不得靜默丟棄。
  - 驗證:上傳含不存在料號的檔案,明細頁該列顯示「未對應」且 `product_id IS NULL`。
- [ ] **可手動指定商品**:未對應的列能在明細頁選擇我方商品完成對應。
  - 驗證:POST `/receipts/<id>/items/<item_id>/map` 帶 `product_id`,該列 `product_id` 更新且 `match_type='manual'`。
- [ ] **手動對應可記住成別名(下次自動對上)**:勾選「記住此對應」且收貨單有供應商名稱時,自動建立 `part_aliases` 一筆。
  - 驗證:手動對應時帶 `remember=1`,`part_aliases` 新增(公司=該供應商,別名料號=檔案上的料號);同料號再次上傳時 `match_type='alias'`。
- [ ] **逐項核對實收數量**:預設帶入通知數量,現場可改;核對後記錄 `received_qty` 與時間。
  - 驗證:POST `/receipts/<id>/items/<item_id>/check` 帶 `received_qty`,該列數值更新;未核對的列 `received_qty IS NULL`。
- [ ] **放行才真正入庫**:放行後每一列(實收 > 0 且已對應)產生一筆 `in` 異動 + 一個批次,`products.quantity` 增加對應數量。
  - 驗證:放行前後比對 `quantity` 差額等於實收總量;`transactions` 新增對應筆數且 `note` 含收貨單號。
- [ ] **放行維持批次帳恆等式**:放行後全系統仍滿足 `SUM(lots.qty_remaining) == products.quantity`。
  - 驗證:放行後以 sqlite 逐商品比對兩者相等。
- [ ] **批號/效期/成本沿用檔案內容**:檔案有填批號、效期、單價時寫入該批次;批號未填則自動編號 `R<收貨單>-<異動>`。
  - 驗證:上傳含批號與效期的檔案並放行,`lots` 對應列的 `lot_no`、`expiry_date`、`unit_cost` 正確。
- [ ] **有未對應且實收 > 0 的列時拒絕放行**:避免有料進來卻沒有帳。
  - 驗證:未對應列填實收數後 POST 放行,回應含「尚有未對應」且收貨單狀態仍為 `open`。
- [ ] **完全沒有可入庫的列時拒絕放行**(全部未核對或實收皆 0)。
  - 驗證:未填任何實收數即放行,回應含「沒有可入庫」且狀態仍為 `open`。
- [ ] **放行具冪等防護**:已放行的收貨單不可重複放行。
  - 驗證:對同一收貨單連續 POST 放行兩次,第二次回應含「已放行」且庫存未再次增加。
- [ ] **作廢為管理員權限**:一般使用者可建立/核對/放行(等同既有入庫權限),但作廢收貨單僅管理員可執行。
  - 驗證:一般使用者 POST `/receipts/<id>/cancel` 回 403;管理員執行回 302 且狀態為 `cancelled`。
- [ ] **已放行/已作廢的收貨單不可再修改明細**。
  - 驗證:對已放行的收貨單 POST 核對,回應含「已放行」且數值未變。
- [ ] **收貨單操作寫入稽核軌跡**:建立、放行、作廢皆留痕。
  - 驗證:`/audit` 頁面出現「建立收貨單」「收貨單放行」等紀錄。
- [ ] **提供範例檔下載**:讓使用者能把格式直接轉給供應商。
  - 驗證:GET `/receipts/template.csv` 回 200 且含標題列「料號」。
- [ ] **導覽維持精簡**:收貨單入口收在「庫存作業」群組內,頂層項目數不增加。
  - 驗證:登入後首頁 HTML 中 `<summary>` 數 ≤ 5 且含 `href="/receipts"`。

### 回歸

- [ ] **既有全部條目回歸**:Patrick、一~五階段與部署條目全部重測通過,`python test_inventory.py` 全綠。
  - 驗證:執行本清單全部項目。

## 庫存系統第七階段:舊資料搬遷(公司現行 Excel 流水帳)

> 來源:使用者提供公司實際使用中的 Excel 流水帳(「2026」工作表,7,654 有效列,2013-11 ~ 2026-07)。
> 使用者已裁示三項決策:(1) 無料號物料自動編 `TMP-xxxxx` 臨時料號,一項都不漏;(2) 只搬目前結存當期初庫存,歷史留在原 Excel;(3) 分類沿用原本的 Type 欄。

- [ ] **商品匯入支援選填的第 9 欄「儲位」**:舊系統搬遷時可一次帶入櫃位,不必事後逐筆補。既有 8 欄格式仍須可正常匯入。
  - 驗證:以 9 欄 CSV 匯入後 `products.location` 有值;以既有 8 欄 CSV 匯入仍成功(回歸第二階段 CSV 匯入條目)。
- [ ] **轉檔工具存在且可執行**:`migrate_bl_excel.py` 讀入原始 Excel,產出 `products_import.csv`、`suppliers.csv`、`migration_report.csv` 三個檔案。
  - 驗證:`python3 migrate_bl_excel.py <檔案> 2026 <輸出目錄>` 結束碼 0,三個檔案皆存在且列數 > 0。
- [ ] **一項物料都不漏**:有料號者用原料號,無料號者編臨時料號;料號與品名皆空白的列才可略過並計數回報。
  - 驗證:轉檔摘要的「物料總數」= 有正式料號 + 臨時料號;臨時料號皆以 `TMP-` 開頭且全體唯一。
- [ ] **期初庫存取自最後結存**:每項物料的初始庫存等於其在流水帳中最後一列的「得盛」(結存)欄。
  - 驗證:抽樣比對來源 Excel 末列結存與匯入後的 `products.quantity`。
- [ ] **負庫存與文字結存不得讓匯入失敗**:結存為負數時匯入 0;結存為「10米」「1捲」這類文字時取開頭數字,取不出來記 0;兩者皆須在報告中標記。
  - 驗證:`migration_report.csv` 備註欄含「原結存為負數」與「結存欄為文字」的列;匯入結果無負庫存(`SELECT COUNT(*) FROM products WHERE quantity < 0` 為 0)。
- [ ] **「無庫存」不得被當成儲位**:櫃位欄的狀態標記(無庫存/無在庫/無)須視為空值,不可寫進儲位;其餘非制式但真實的位置(桌上、防潮箱N層、Joyce保管…)須保留。
  - 驗證:`products_import.csv` 的儲位欄不含「無庫存」「無在庫」;`grep -c '桌上'` ≥ 1。
- [ ] **一料多值時取最新並留痕**:同一料號出現多個品名/櫃位/廠商時,取最後一次出現的值,並在報告備註欄說明。
  - 驗證:`migration_report.csv` 備註欄含「已取最新」字樣的列數 > 0。
- [ ] **匯入後逐欄與來源檔零差異**:料號、品名、分類、庫存、儲位五個欄位與 `products_import.csv` 完全一致。
  - 驗證:以 sqlite 讀出全部商品與來源 CSV 逐欄比對,差異筆數為 0。
- [ ] **匯入後批次帳恆等式成立**:`SUM(lots.qty_remaining) == products.quantity`,無例外。
  - 驗證:逐商品比對,不一致筆數為 0。
- [ ] **真實資料量下頁面仍可用**:2,000 項以上商品時,首頁、異動歷史、報表、警示、存貨規劃、料架標籤皆須在 1 秒內回應且為 HTTP 200。
  - 驗證:逐頁 `curl -w "%{time_total}"`,各頁 < 1.0 秒。
- [ ] **搬遷後搜尋仍能用真實料號/品名/儲位找到料**。
  - 驗證:以實際料號(如 `1C01ATS00501001`)、品名關鍵字、儲位(如 `H-8`)、臨時料號分別搜尋,皆有命中。

- [ ] **一鍵轉檔批次檔**:`migrate_data.bat` 雙擊即可完成轉檔,使用者不需開命令列或打指令;自動偵測資料夾中的 Excel(多個時詢問)、缺 openpyxl 時自動安裝、完成後開啟輸出資料夾。
  - 驗證:檔案為 CRLF 換行且無 BOM;`grep -c 'py -3' migrate_data.bat` ≥ 1;`grep -c 'goto NOEXCEL\|goto PIPFAIL\|goto RUNFAIL' migrate_data.bat` ≥ 3。
- [ ] **全新資料夾情境演練通過**:只放程式 + Excel 的乾淨資料夾,轉檔 → 啟動 → 建管理員 → 匯入,全程走得通。
  - 驗證:實際以乾淨目錄執行一次,匯入結果為「成功匯入 N 筆,跳過 0 筆」。
- [ ] **抽查資料與原始 Excel 一致**:任取數個真實料號,系統中的品名/分類/庫存/櫃位/廠商須等於該料號在原始流水帳最後一列的值(文字結存者除外,應為 0 並在報告標記)。
  - 驗證:以 openpyxl 重算來源末列並與資料庫逐欄比對。
- [ ] **ABC 分級在無價格資料時不可誤導**:本次來源檔無單價欄,所有商品價值為 0,ABC 分級無意義;首次盤點的優先序改以「資料異常 → 異動頻繁 → 庫存量大」決定,並產出可列印的優先盤點清單。
  - 驗證:確認 `products` 的 `unit_price` 全為 0;優先盤點清單涵蓋全部被標記為負結存/文字結存的品項。

## 啟動網址可用性(使用者實機回報)

> 來源:使用者照啟動畫面印出的「服務位址:http://0.0.0.0:5000」輸入瀏覽器,得到 `ERR_ADDRESS_INVALID`。`0.0.0.0` 是「綁定所有網卡」的意思,不是可瀏覽的網址——是啟動訊息誤導,不是使用者操作錯誤。

- [ ] **啟動訊息只印可直接貼進瀏覽器的網址**:必須印 `http://localhost:<port>`;不得把 `0.0.0.0` 印成看起來像網址的形式。
  - 驗證:啟動後 log 含 `http://localhost:`;`grep -c '服務位址:http://0.0.0.0' inventory_app.py` 為 `0`。
- [ ] **同時印出同事可用的內網網址**:自動偵測本機區域網路 IP 並印出;偵測不到時明確提示改用 ipconfig 查。
  - 驗證:啟動 log 含「同事請開」且其後為 `http://<IP>:<port>` 或提示字串。
- [ ] **明確說明 0.0.0.0 不是網址**:啟動訊息須有一行解釋,避免下一位使用者再踩。
  - 驗證:啟動 log 含「不是可輸入的網址」。
- [ ] **綁定契約不變**:`host="0.0.0.0"` 與 `$PORT` 的部署契約不得因訊息調整而改變。
  - 驗證:`grep -c 'host="0.0.0.0"' inventory_app.py` ≥ 1。
- [ ] **啟動腳本自動開啟瀏覽器且不干擾服務**:`start_inventory.bat` 於伺服器啟動後自動開 `http://localhost:5000`;即使開啟失敗,服務仍正常且畫面上仍有可照打的網址。
  - 驗證:`grep -c 'start http://localhost:5000' start_inventory.bat` ≥ 1;`grep -c '不要輸入 0.0.0.0' start_inventory.bat` ≥ 1;批次檔仍為 CRLF 無 BOM。

## 版本可辨識性(使用者實機回報)

> 來源:使用者下載到舊版 ZIP 並完成匯入,畫面看起來正常(顯示「成功匯入 2279 筆」),但舊版匯入器只讀 8 欄,**儲位欄被靜默丟棄**。由於畫面上看不出版本,使用者無從察覺跑的是舊版。本系統以「下載 ZIP 覆蓋」更新,版本可辨識性是必要防線。

- [ ] **每一頁的頁尾顯示版本**:登入前後皆可見,使用者回報問題時可直接對版本。
  - 驗證:任一頁 HTML 的 `<footer>` 含「版本」與 `APP_VERSION` 字串;登入頁(未登入狀態)亦然。
- [ ] **啟動訊息顯示版本**:黑底視窗第一行即可看到。
  - 驗證:啟動 log 第一行含「版本」與版本號。
- [ ] **匯入欄位數不符時不得靜默丟棄**:商品匯入說明須明列目前支援的完整欄位(含儲位),使用者能自行核對格式是否相符。
  - 驗證:`/import` 頁面內容含 `SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存,儲位`。

## 一次搞定安裝(`setup_all.bat`)

> 來源:使用者要求「能幫我完成就完成」。轉檔、建帳號、匯入、啟動原本是四次操作加瀏覽器上傳,壓成單一批次檔;命令列子命令讓安裝腳本不必經過瀏覽器挑檔案。

- [ ] **命令列可建立第一個管理員**:`--setup-admin <帳號> <密碼>`;已有帳號時略過而非報錯,密碼不足 8 碼須拒絕並回非零結束碼。
  - 驗證:乾淨 DB 執行後 `users` 有一筆 `is_admin=1`;密碼填 `abc` 時結束碼為 1 且輸出含「至少 8 碼」;重複執行輸出含「略過建立管理員」。
- [ ] **命令列可匯入商品檔**:`--import <檔案>`,以第一位管理員名義記錄異動,結果與瀏覽器上傳一致。
  - 驗證:匯入後商品數、儲位數、供應商數、入庫異動數與瀏覽器上傳的結果相同;批次帳恆等式成立;`audit_log` 有「CSV 匯入」紀錄。
- [ ] **命令列匯入的防呆**:無管理員時拒絕、檔案不存在時拒絕、重複匯入時全數跳過而非重複建立,三者皆回非零結束碼或 0 筆成功。
  - 驗證:三種情境分別實測;重複匯入輸出「成功 0 筆,跳過 N 筆」。
- [ ] **`setup_all.bat` 不得覆蓋既有資料**:資料夾已有 `inventory.db` 時必須停下並提示改用 `start_inventory.bat`。
  - 驗證:讀碼確認有 `if exist "inventory.db"` 的早退分支;批次檔為 CRLF 無 BOM。
- [ ] **一次搞定流程端到端可用**:乾淨資料夾放入程式與 Excel 後,單一批次檔完成轉檔→建帳號→匯入→啟動,且完成後三個檢查點成立(頁尾版本、導覽 5 項、儲位有值)。
  - 驗證:以乾淨目錄逐步模擬,匯入 2,279 筆 0 跳過;首頁儲位欄可見 `H-8` 類值。

## 介面精緻度(使用者實證回饋:「所有設計都很陽春,按鈕的部分也是」)

> 來源:使用者 2026-08 回饋——之前的視覺條目只驗到「有主色變數」「有深色表頭」這種及格線,打勾不代表好看。本節把「精緻度」寫成可驗證的具體要求,避免再用清單交差。
> **原則:任何動到介面的修改都算設計任務**,必須跑截圖迭代並附圖,不需使用者特別交代。

- [ ] **不得使用 emoji 當功能圖示**:圖示一律為內嵌線條 SVG,才能跟著配色走、在各系統長相一致。
  - 驗證:登入後首頁 `grep -c '<svg'` ≥ 2(全站搜尋圖示與表格圖示鈕);首頁不含 emoji 字元。
  - 註(第九階段修訂):首頁的七個「快速動作磚」已移除——它與導覽列 100% 重複,桌機吃 98px、手機吃 422px,使用者明講「功能很多但我比較喜歡精簡」。原條目驗的 `qa-icon` 類別隨之消失。
- [ ] **按鈕有實體感與完整狀態**:主按鈕具備 hover、active(按下位移)、focus-visible(鍵盤可見焦點)三種狀態,且按下時有內陰影。
  - 驗證:`<style>` 含 `input[type=submit]:active` 的 `transform: translateY` 規則、`:focus-visible` 的 `outline` 規則,以及主按鈕 `:active` 的 `inset` 陰影。
  - 註(第九階段修訂):主按鈕由漸層改為實心琥珀。理由:漸層在深色主題下需要第二組色停,而實心色才能讓「琥珀 = 等你動手」這條一色一義的規則在兩種主題下都成立。
- [ ] **層次以陰影色票統一管理**:陰影用藏青而非純黑,並定義為 `--sh-1/--sh-2` 等變數重複使用。
  - 驗證:`<style>` 含 `--sh-1`、`--sh-2`,且 `.pane` 使用 `var(--sh-`;全檔不得再出現一次性的 `box-shadow: 0 ... rgba(` 硬寫法超過 3 處。
- [ ] **資料表列高不得被操作欄撐爆**:1440px 寬時首頁至少可見 8 列商品。
  - 驗證:Playwright 1440px 截圖計算可見資料列數 ≥ 8。
- [ ] **操作欄在橫向捲動時仍可見**:欄位多到需要橫捲時,操作欄釘在表格右緣。
  - 驗證:`<style>` 含 `.table-scroll td[data-label="操作"]` 的 `position: sticky`。
- [ ] **危險動作用圖示鈕但仍可辨識**:刪除鈕為圖示,必須同時有 `title` 與 `aria-label`。
  - 驗證:首頁 `grep -c 'aria-label="刪除商品"'` ≥ 1。
- [ ] **表單頁不得在寬容器中留下大片空白**:純表單頁的容器寬度需收窄。
  - 驗證:`<style>` 含 `.wrap.narrow` 的 max-width 規則,且入庫/出庫/新增商品頁的容器帶有 `narrow` 類別;截圖檢視。
  - 註(第九階段修訂):由 `.container:has(> form)` 改為樣板明確給定的類別。理由:`:has()` 會誤判——首頁的搜尋列與歷史頁的篩選列也是 form,得靠一長串 `:not()` 排除,加一頁就得再加一個例外。
- [ ] **尊重系統的減少動態偏好**:所有轉場在 `prefers-reduced-motion: reduce` 下停用。
  - 驗證:`<style>` 含 `@media (prefers-reduced-motion: reduce)` 且內含 `transition: none`。
- [ ] **零 JavaScript 原則不因視覺升級破例**。
  - 驗證:登入後首頁 `grep -c '<script'` = 0。

## 庫存系統第八階段:採購訂單追蹤與在途可視化

> 來源:使用者需求「我想將登記的部分自動化,並且還會在頁面上顯示目前有訂了哪些料,哪些已出貨,哪些是已抵達尚未檢查」。
> 對應業界作法:採購訂單(PO)生命週期 + 在途庫存(on-order / in-transit)可視化。核心價值是**同一份明細只登記一次**,後續階段自動往下帶,以及**可用量之外再看得到「在路上的量」**,避免重複下單。
> 狀態流轉:`已下訂 → 已出貨 → 已到貨待驗 → 已入庫(結案)`,另有作廢。

### 訂單建立與料號比對

- [ ] **可上傳採購明細建立訂單**:欄位 `料號,品名,數量,單價,預計到貨日,備註`;支援 Excel/CSV(沿用既有讀檔層)。
  - 驗證:POST `/orders/upload` 帶檔案回 302;`purchase_orders` 新增一列且 `status='ordered'`,`purchase_order_items` 列數等於資料列數。
- [ ] **料號比對沿用跨公司別名**:供應商用自己的料號下單也能對應到我方商品。
  - 驗證:先建立別名,上傳以該別名為料號的訂單,該列 `match_type='alias'` 且 `product_id` 正確。
- [ ] **對不上的料號標示未對應且可手動指定**,不得靜默丟棄。
  - 驗證:未知料號列 `match_type='none'` 且 `product_id IS NULL`;POST `/orders/<id>/items/<item_id>/map` 後 `match_type='manual'`。

### 狀態流轉與登記自動化

- [ ] **下訂當下不得影響庫存**:建立訂單只是預先登記,不動 `products.quantity` 與 `transactions`。
  - 驗證:建立訂單前後比對庫存與異動筆數皆不變。
- [ ] **可標記已出貨並記錄出貨日與追蹤號**。
  - 驗證:POST `/orders/<id>/ship` 帶 `shipped_at`/`tracking_no` 後,狀態為 `shipped` 且欄位已寫入。
- [ ] **標記到貨時自動產生收貨單(登記自動化的核心)**:明細、數量、單價、料號對應全部帶入,員工不需重新上傳或重打。
  - 驗證:POST `/orders/<id>/arrive` 後狀態為 `arrived`;`receipts` 新增一列且 `po_id` 指向該訂單,`receipt_items` 列數與內容等同訂單明細;過程中庫存仍未變動。
- [ ] **收貨單放行後回寫訂單已收數量**:全數收齊時訂單自動結案。
  - 驗證:放行後 `purchase_order_items.received_qty` 等於實收數;全收齊時 `purchase_orders.status='closed'`。
- [ ] **部分到貨不得誤結案**:實收少於訂購量時訂單維持 `arrived`,剩餘量仍計入在途。
  - 驗證:實收數小於訂購量時放行,訂單狀態不為 `closed`,且在途量等於未收足的差額。
- [ ] **狀態流轉具防呆**:不可跳階、不可重複推進、已結案/已作廢不可再改。
  - 驗證:對 `ordered` 訂單直接標到貨仍可(允許略過出貨),但對 `closed` 訂單推進任何狀態皆回明確訊息且狀態不變;重複標記出貨回「已標記」訊息。
- [ ] **作廢為管理員權限**:一般使用者可建立與推進狀態(等同既有入庫權限),作廢僅管理員。
  - 驗證:一般使用者 POST `/orders/<id>/cancel` 回 403;管理員回 302 且狀態為 `cancelled`。

### 在途可視化(使用者要求「頁面上顯示」)

- [ ] **首頁顯示採購狀態總覽**:一眼看到目前有多少張採購單在途、共幾件在路上。
  - 驗證:登入後首頁的待辦帶含「在途採購」格,數字與 `SELECT COUNT(DISTINCT o.id)` / `SUM(ordered-received)` 一致;
    點該格進入 `/orders`,清單仍分別列出「已下訂 / 已出貨 / 已到貨待驗」三種狀態。
  - 註(第十階段修訂):首頁三張採購狀態卡改由全站常駐的待辦帶承接。
    理由:同一件事原本在首頁被講三次(橫幅 + 導覽項目 + 狀態卡),而且離開首頁就看不到了;
    待辦帶在每一頁都在,三種細分狀態移到採購單清單本身。
- [ ] **商品列表顯示在途數量**:該料已下訂但尚未入庫的數量,在列上看得到。
  - 驗證:某料有未收足的訂單時,首頁該列出現「在途 N」且 N 為正確差額;無訂單時該列不出現在途字樣。
  - 註(第十階段修訂):由固定欄位改為狀態欄的晶片。理由:2,279 項裡只有個位數有在途,
    一個永遠是「—」的欄位在 13 欄的表格裡是純粹的浪費;改成有值才出現,反而更醒目。
- [ ] **商品詳細頁列出該料的在途訂單**:單號、狀態、訂購量、已收量、預計到貨日。
  - 驗證:`/products/<id>` 含「在途採購」區塊與該訂單單號。
- [ ] **訂單列表可依狀態篩選**。
  - 驗證:`/orders?status=shipped` 只列出已出貨的訂單。
- [ ] **作廢或結案的訂單不計入在途量**。
  - 驗證:作廢訂單後,該商品的在途量回到不含此單的數值。

### 稽核、導覽與回歸

- [ ] **訂單操作寫入稽核軌跡**:建立、出貨、到貨、結案、作廢皆留痕。
  - 驗證:`/audit` 出現「建立採購單」「採購單到貨」等紀錄。
- [ ] **導覽維持精簡**:採購入口收在「庫存作業」群組內,頂層項目數不增加。
  - 驗證:首頁 `<summary>` 數 ≤ 5 且含 `href="/orders"`。
- [ ] **既有全部條目回歸**:一~七階段與自動化測試全數通過。
  - 驗證:執行本清單全部項目。

## 庫存系統第九階段:設計系統地基 + 選料元件(重設計第 1、2 批)

> 來源:使用者 2026-09 指示「B = 第 1、2 批一起做」。第 1 批只動外觀與樣板,不碰任何資料流;
> 第 2 批取代全站的兩千項下拉選單並補上更正入口。第 3~5 批(批次核對、待辦帶與首頁重排、手機與列印)尚未執行。

### 第 1 批:設計代幣與視覺硬傷

- [ ] **兩套完整主題**:淺色與深色各自定義同一組色彩代幣,不得只覆寫片段。
  - 驗證:取出 `:root{}` 與深色區塊的自訂屬性名稱集合,兩者的色彩代幣完全相同(結構代幣如字級/間距不計);且深色區塊不得只有 6 條規則。
- [ ] **深色主題不再讓內容消失**:舊版深色區塊把 `.loc-cell` 設成 `#cbd5e1` 但底色仍為白,對比 1.48:1。
  - 驗證:`<style>` 中不存在「只設定 color 而未同時設定所屬面底色」的深色覆寫;`--text` 對 `--card` 在兩種主題下都 ≥ 4.5:1。
- [ ] **字重只有 400 與 700**:Windows 中文落到微軟正黑體,只有這兩個真字重,600/800 是瀏覽器合成的假粗體。
  - 驗證:`grep -c "font-weight: *\(500\|600\|800\|900\)" inventory_app.py` = 0。
- [ ] **字體堆疊以 Segoe UI 起頭**:`-apple-system` 排第一在 Windows 上是完全不生效的規則。
  - 驗證:`<style>` 的 `--font-ui` 以 `"Segoe UI"` 開頭。
- [ ] **字級成級距、無半像素**:六級整數字級,中文最小 13px。
  - 驗證:`grep -c "font-size: *[0-9]*\.[0-9]" inventory_app.py` = 0;`<style>` 含 `--t1`…`--t6`。
- [ ] **料號/批號/儲位/單號走等寬字體**:使用者要逐字比對 BL-2401 與 BL-2461。
  - 驗證:`<style>` 含 `--font-code`;首頁料號欄的 `<td>` 帶 `mono` 類別。
- [ ] **中文不加字距**:`letter-spacing` 會讓「低庫存門檻」逐字撐開並在末字後留尾隙。
  - 驗證:`<style>` 中 `th` 與中文內容選擇器不得含 `letter-spacing`(僅純拉丁小標籤例外)。
- [ ] **釘住表頭真的生效**:`table { overflow: hidden }` 會讓 `position: sticky` 的 `th` 失效。
  - 驗證:`<style>` 的 `table` 規則不含 `overflow: hidden`;圓角改掛在 `.table-scroll`;Playwright 捲動 600px 後表頭仍在視窗頂端。
- [ ] **缺料紅底不得被斑馬紋蓋掉**:舊版 `tbody tr:nth-child(even) td` 權重高過 `tr.low-stock td`,實測一半的缺料列失去紅色。
  - 驗證:`<style>` 不含 `nth-child(even)` 的背景規則;`/alerts` 頁用 Playwright 讀取所有 `tr.low-stock` 第一格的 computed background,全部一致。
- [ ] **鍵盤焦點框對比達標**:舊版焦點框對比 1.44:1,遠低於 3:1。
  - 驗證:`<style>` 的 `:focus-visible` outline 顏色對其相鄰底色 ≥ 3:1。
- [ ] **每頁有自己的分頁標題**(WCAG 2.4.2,最低 A 級)。
  - 驗證:`/`、`/stock/in`、`/report`、`/orders` 四頁的 `<title>` 互不相同,且都以頁名開頭。
- [ ] **全站搜尋框在每一頁的同一位置**:舊版唯一的搜尋框只存在於首頁。
  - 驗證:`/report`、`/orders`、`/history`、`/receipts` 四頁都含 `name="q"` 的搜尋 form 且 `action` 指向首頁。
- [ ] **刪除鈕的無障礙名稱要對**:舊版供應商/照片/別名/帳號四種刪除鈕的 `aria-label` 全部誤植為「刪除商品」。
  - 驗證:`grep -c 'aria-label="刪除商品"' inventory_app.py` = 1;另存在「刪除供應商」「刪除照片」「刪除別名」「刪除帳號」各 ≥ 1。
- [ ] **頁尾版本號看得清楚**:舊版對比 2.18:1,而它存在的唯一目的就是讓人辨識版本。
  - 驗證:頁尾文字色對頁面底色 ≥ 4.5:1。
- [ ] **明細頁有具名的返回連結**:不得只能靠瀏覽器上一頁(PRG 下可能回到過期畫面)。
  - 驗證:`/products/<id>`、`/orders/<id>`、`/receipts/<id>` 都含指向其清單頁的返回連結。
- [ ] **零 JavaScript 不因視覺升級破例**。
  - 驗證:登入後任一頁 `grep -c '<script'` = 0。

### 第 2 批:選料元件與更正入口

- [ ] **全站不得再有無搜尋的全品項下拉選單**:舊版 `product_dropdown()` 無 WHERE 無 LIMIT,實測 2,281 個 option。
  - 驗證:`grep -c 'select name="product_id"' inventory_app.py` = 0;`/stock/in` 的 `grep -c "<option"` ≤ 10。
- [ ] **入庫/出庫改成兩步:先找料、再填數**。
  - 驗證:GET `/stock/in` 顯示搜尋欄與「先找到料」字樣;GET `/stock/in?product_id=<id>` 顯示該料的確認卡與數量欄。
- [ ] **選料頁只命中一筆時直接進入下一步**(掃碼槍可一氣呵成)。
  - 驗證:`/pick?next=in&q=<某料完整料號>` 回 `302`,Location 含 `product_id=`。
- [ ] **選料支援料號、品名、儲位、跨公司別名**(沿用首頁同一組查詢條件)。
  - 驗證:以儲位字串與別名料號各查一次,皆能在結果中找到目標商品。
- [ ] **登記成功後保留同一項料**:舊版 302 不帶 `product_id`,商品欄會無聲跳回排序第一筆,而成功訊息還停在上一筆。
  - 驗證:POST `/stock/in` 成功後的 Location 含 `product_id=<剛才那筆>`;該頁的確認卡顯示同一個料號。
- [ ] **可以沖銷打錯的異動**:舊版全站沒有任何更正入口,唯一辦法是反向出庫,會汙染批號與成本。
  - 驗證:入庫 100 後 POST `/transactions/<txid>/reverse` 回 302,商品數量回到原值,異動歷史出現標記為沖銷的紀錄,且批次剩餘量總和仍等於商品數量。
- [ ] **沖銷有邊界**:已被消耗的批次、已沖銷過的異動、非本人且非管理員,都不得再沖銷。
  - 驗證:重複沖銷同一筆回 200 並顯示錯誤訊息;一般使用者沖銷他人異動回 403。
- [ ] **出庫的原子條件改用可用量**:舊版是 `quantity >= ?`,可以把已被預留的量領走。
  - 驗證:庫存 100、預留 40 時,POST `/stock/out` 領 70 應被拒絕並同時顯示現貨/預留/可用三個數字;領 60 成功。
- [ ] **登記頁顯示「本次已登記」**:最近 10 筆,每筆可直接沖銷。
  - 驗證:連續入庫兩筆後,`/stock/in?product_id=<id>` 含兩筆紀錄與各自的沖銷按鈕。
- [ ] **沖銷寫入稽核軌跡**。
  - 驗證:沖銷後 `/audit` 含該筆沖銷紀錄與操作者。
- [ ] **回歸**:第一至第八階段全部條目維持通過;`python test_inventory.py` 全綠。

## 庫存系統第十階段:待辦帶、首頁重排與報表判讀(重設計第 4 批)

> 來源:使用者 2026-09 指示「跳做第 4 批」。這一批做招牌元素與主管會打開的兩頁。
> 第 3 批(收貨與盤點的批次核對)與第 5 批(手機與列印)尚未執行。

### 待辦帶(招牌元素,全站常駐)

- [ ] **每一頁都有待辦帶**,登入頁與註冊頁除外。
  - 驗證:`/`、`/report`、`/orders`、`/history`、`/stock/in?product_id=1` 都含 `class="rail"`;`/login` 不含。
- [ ] **四格全部是可以數的件數**,沒有一格需要把「個、米、捲、箱」加起來。
  - 驗證:待辦帶四格的單位字元只出現「張」「項」;不得出現商品單位。
- [ ] **即時計算,不做快取**:放行完一張收貨單回頭看,數字必須已經變了。
  - 驗證:放行前後各抓一次首頁,「待驗收貨」的數字相差 1;程式碼中無待辦帶快取。
- [ ] **待辦帶查詢成本可忽略**:四個彙總在 2,279 筆規模下合計 < 5 毫秒。
  - 驗證:以實際資料量計時四個查詢,合計 < 5ms。
- [ ] **沒有資料時說實話,不顯示會誤導人的 0**:全部商品都沒有補貨門檻時,「短缺」格顯示「尚未設定」而不是「0」,並連到可以設定的地方。
  - 驗證:門檻全為 0 的資料庫,首頁待辦帶含「尚未設定」且該格連向 `/planning`;
    設定任一門檻後,同一格改為顯示數字。
- [ ] **每一格都可點,而且點到的是該格說的那件事**。
  - 驗證:四格的 href 分別指向 `/receipts`、`/orders`、`/alerts`(或 `/planning`)、`/?missing=1`。

### 首頁重排

- [ ] **首屏看得到資料**:1280×900 不捲動的情況下,至少可見 8 列商品。
  - 驗證:Playwright 1280×900 計算首屏內可見的 `tbody tr` 數 ≥ 8。
- [ ] **同一件事不在首頁講三次**:低庫存橫幅與採購在途卡片移除,由待辦帶承接。
  - 驗證:首頁不含 `class="banner"` 與 `class="po-home"`。
- [ ] **預設欄位收斂成 7 欄,完整欄位改為可選**。
  - 驗證:`/` 的表頭欄數 = 7;`/?cols=full` 的表頭欄數 ≥ 12,且頁面提供切換連結。
- [ ] **現貨欄保留 `id="qty-<id>"`**(既有驗收條目與單元測試依賴它)。
  - 驗證:`/` 含 `id="qty-1">N<`。
- [ ] **每一列可直接登記進出**:不必先進商品明細頁。
  - 驗證:首頁每列含指向 `/stock/in?product_id=<id>` 與 `/stock/out?product_id=<id>` 的連結。
- [ ] **狀態用晶片,有值才出現**:在途、短缺、無儲位。
  - 驗證:有在途的列出現「在途 N」;缺料的列出現「短缺」;無儲位的列出現「無儲位」;其餘列的狀態欄為空。

### 短缺佇列(原「低庫存警示」)

- [ ] **看得到就要做得到**:每一列可直接建立採購單,不必自己記料號再切頁面。
  - 驗證:`/alerts` 每列含指向 `/orders/new?product_id=<id>` 的連結。
- [ ] **給建議補量**:以補貨規劃推導的再訂購點減去可用量。
  - 驗證:`/alerts` 含「建議補量」欄且數值 = 建議值 − 可用量(不足時為 0)。
- [ ] **空狀態要有出路**,不能只寫「沒有資料」。
  - 驗證:無缺料時 `/alerts` 含前往補貨規劃設定門檻的連結。

### 手動建立採購單

- [ ] **可以不用上傳檔案就開一張採購單**(第一版:單一品項)。
  - 驗證:GET `/orders/new` 回 200;POST 建立後回 302,採購單狀態為 `ordered`,明細 1 列且已對應到該商品。
- [ ] **可從短缺佇列帶入**:料號與建議數量預先填好。
  - 驗證:`/orders/new?product_id=<id>&qty=<n>` 的表單已帶入該商品與數量。
- [ ] **建立採購單寫入稽核**。
  - 驗證:建立後 `/audit` 含該筆紀錄。

### 報表判讀

- [ ] **先講結論,再給明細**:頁面最上方是四張判讀卡,每張附一句白話結論。
  - 驗證:`/report` 中「判讀」區塊的位置在明細表之前(HTML 中的行號較小)。
- [ ] **算不出來就說算不出來**:單價全為 0 時,庫存價值卡顯示「無法計算」並說明原因,而不是顯示 0。
  - 驗證:單價全 0 的資料庫,`/report` 含「無法計算」與「單價」字樣,且不把 0 當成價值呈現。
- [ ] **庫齡用純 CSS 長條呈現**,不引入任何圖表函式庫。
  - 驗證:`/report` 含 `class="bar"` 與 `class="fill"`,且全頁 `grep -c '<script'` = 0。
- [ ] **總計列改用 `<tfoot>`**,不再繼承表頭的釘住規則。
  - 驗證:`/report` 的合計列位於 `<tfoot>` 內且為 `<td>`。
- [ ] **回歸**:第一至第九階段全部條目維持通過;`python test_inventory.py` 全綠。

## 介面密度(使用者實證回饋:「畫面很雜亂」)

> 來源:使用者 2026-09 看過實機畫面後回報「為什麼畫面很雜亂」。實測 1280×900 的首頁:
> 三條深色橫帶疊了 186px、同一頁出現兩個搜尋框、第一列資料在 430px 處(佔掉 48% 的螢幕)。
> 本節把「不雜亂」寫成可量測的條件,而不是形容詞。

- [ ] **同一頁不得有兩個搜尋框**:全站搜尋已在頂列,頁面內不再重複一個。
  - 驗證:任一頁 `grep -c 'name="q"'` = 1。
- [ ] **首屏的介面外框不得超過 150px**:頂列 + 導覽 + 待辦帶三條帶加總。
  - 驗證:Playwright 量 `.topbar` + `nav` + `.rail` 的高度總和 ≤ 150。
- [ ] **第一列資料必須在 330px 以內出現**(1280×900)。
  - 驗證:Playwright 量第一個 `tbody td` 的 top ≤ 330。
- [ ] **同一層級的連結不另起一排**:頁面動作(切換欄位、匯出、篩選)收進所屬面板的標題列,不在標題下方另開一列連結。
  - 驗證:首頁不含 `class="sub-links"`。
- [ ] **標題不與導覽重複**:頁標題不得只是導覽項目的同義詞;首頁標題要說出目前看的是什麼範圍。
  - 驗證:首頁 `<h1>` 文字隨搜尋/篩選改變(全部商品 / 符合「x」的商品 / 資料待補的商品)。
- [ ] **待辦帶壓縮但不失資訊**:四格仍各有標籤、數字、說明,但總高不超過 72px。
  - 驗證:Playwright 量 `.rail` 高度 ≤ 72,且仍可讀到四個 `class="s"` 說明。
- [ ] **回歸**:第一至第十階段全部條目維持通過;`python test_inventory.py` 全綠。

## 庫存系統第十一階段:批次核對(重設計第 3 批)

> 來源:使用者 2026-09 指示「繼續做第 3 批」。這一批解掉診斷中最嚴重的一項資料遺失:
> 收貨核對與盤點的每一列各自是一張表單,現場照著紙本一路打十幾列再回頭存,
> 只有按下去的那一列會被存起來,其餘輸入靜默消失,而且畫面跳回最頂端。

### 一次送出整張表

- [ ] **整張明細包在一個表單裡**,底部一顆「儲存這一頁」一次送出。
  - 驗證:`/counts/<id>` 與 `/receipts/<id>` 的所有 `name="qty_"` 欄位都在同一個 `<form>` 內。
- [ ] **一次 POST 可儲存多列**,不再一列一次。
  - 驗證:一次 POST 三個 `qty_<item_id>`,三列的數量都寫入資料庫。
- [ ] **底部儲存列顯示進度**:已填幾列 / 共幾列。
  - 驗證:頁面含「已填 N / M」字樣且 N、M 與資料一致。
- [ ] **每列仍保留單列儲存當安全網**(用 formaction,不巢狀表單)。
  - 驗證:每列含 `formaction` 指向同一端點;單列送出仍可成功。
- [ ] **儲存後回到原處**:302 回同一頁同一頁碼,並定位到剛存的那一列。
  - 驗證:儲存後的 Location 含 `page=` 與 `#i<id>`;`<style>` 含 `tr:target` 高亮規則。

### 一鍵動作

- [ ] **收貨:全部照通知量核對**(照單全收是最常見的情況)。
  - 驗證:POST `/receipts/<id>/fill` 後,所有已對應列的實收數 = 通知量。
- [ ] **盤點:無差異全部確認**(帳面正確也是最常見的情況)。
  - 驗證:POST `/counts/<id>/fill` 後,所有未盤列的實盤數 = 系統帳。

### 分頁與篩選(2,279 列的盤點單在手機上必須可用)

- [ ] **每頁 50 列並提供分頁**。
  - 驗證:建立全部商品範圍的盤點單後,`/counts/<id>` 的資料列 ≤ 50 且有下一頁連結。
- [ ] **可依儲位排序**:人是站在一排貨架前盤點的,清單順序要跟走位一致。
  - 驗證:`/counts/<id>?sort=loc` 的儲位欄由小到大排列。
- [ ] **可只看未盤**與**只看有差異**。
  - 驗證:`?filter=todo` 只回未填實盤數的列;`?filter=diff` 只回有差異的列。
- [ ] **盤點單可依儲位建立**。
  - 驗證:以 `scope=location` 與儲位前綴建立,明細只含該儲位的商品。

### 放行/過帳前說清楚後果

- [ ] **明白列出會被略過的列**:未核對或未對應的列,放行後不能再改。
  - 驗證:有未核對列時,放行區塊列出那些列號並寫明「將被略過且無法再修改」。
- [ ] **回歸**:第一至第十階段全部條目維持通過;`python test_inventory.py` 全綠。

## 庫存系統第十二階段:手機與列印(重設計第 5 批)

> 來源:使用者 2026-09 指示「繼續做第 5 批」。實測(420 項料的活體實例)找出三件會直接
> 影響現場的事實:
> (1) **列印出來的盤點單與收貨單一列明細都沒有** —— `@media print` 有一條
> `form { display: none !important; }`,而兩張單的明細表格整個包在 `<form>` 裡。
> 實測 `/counts/1` 螢幕上有 50 個實盤數輸入格,印成 A4 只有 1 頁、290 個字,
> 表格完全消失;`/receipts/1` 38 列同樣一列都不剩。倉管印一張單走進倉庫,
> 手上拿的是一張沒有料的紙。
> (2) **手機上的導覽會捲走** —— 桌面 `nav` 是 `position: sticky`,760px 以下被覆寫成
> `position: static`。實測 `/history` 手機版整頁 54,999px,捲到 2,000px 時 nav 的
> top 是 −1,952px(已離開畫面),只剩 48px 的頂列(裡面沒有任何頁面入口)。
> 最需要常駐導覽的裝置反而沒有。
> (3) **料架標籤沒有任何篩選** —— `/labels` 是 `SELECT ... FROM products` 無 WHERE 無 LIMIT。
> 420 項料印成 A4 是 18 頁,正式資料 2,279 項料換算約 98 頁。要補印一個櫃子的標籤,
> 只能整廠重印。

### 手機常駐工具列

- [ ] **手機版有固定在畫面底部的工具列**,捲到任何位置都在。
  - 驗證:Playwright 390px 開 `/history`,捲到 2,000px 後量 `.tabbar` 的
    `getBoundingClientRect().bottom` 仍等於視窗高度(844)。
- [ ] **桌面版不出現工具列**。
  - 驗證:1280px 下 `.tabbar` 的 `display` 為 `none`。
- [ ] **工具列不遮住頁面內容**:頁尾與最後一列資料都要看得到。
  - 驗證:390px 捲到頁面最底,`footer` 的 bottom ≤ `.tabbar` 的 top。
- [ ] **避開手機底部的系統手勢區**。
  - 驗證:`<style>` 內含 `env(safe-area-inset-bottom)`。
- [ ] **未登入的頁面(登入、註冊)不出現工具列**。
  - 驗證:`curl /login` 的 HTML 不含 `class="tabbar"`。
- [ ] **列印時工具列不出現**。
  - 驗證:`@media print` 區塊內含 `.tabbar` 的隱藏規則。
- [ ] **工具列不可以讓任何功能消失**:手機隱藏原本的分頁列時,必須有一個入口
      能走到全部頁面(含稽核紀錄、供應商、帳號管理等低頻頁)。
  - 驗證:390px 下點工具列的「更多」,可見連結涵蓋 `/audit`、`/suppliers`、
    `/planning`、`/reservations`、`/labels`(管理員身分)。

### 觸控目標

- [ ] **手機 390px 下所有可點擊元素的高度 ≥ 44px**(WCAG 2.5.5 / Apple HIG)。
  - 驗證:Playwright 列舉 `a, button, input, select, summary` 的
    `getBoundingClientRect()`,可見元素中高度 < 44 的數量為 0。
  - 註:實測修改前 `/products/<id>` 的「入庫」「出庫」連結只有 17px,
    頂列「登出」只有 15px。
- [ ] **相鄰的可點擊目標間距 ≥ 8px**,避免戴手套誤觸。
  - 驗證:同一列並排的操作連結兩兩之間的水平間距 ≥ 8。
- [ ] **掃碼落地後第一屏就看得到入庫/出庫**:商品詳細頁的主要動作不得埋在頁面深處。
  - 驗證:390px 下 `/products/<id>` 的「入庫」連結 top ≤ 844(第一屏內)。
    註:修改前實測在 966px 處,要先捲一屏才看得到。

### 列印:單據印出來要有明細

- [ ] **盤點單印出來含全部明細列**,而且是整張單不是只有第一頁。
  - 驗證:`/counts/<id>?print=1` 的 HTML 含全部 120 列的 `qty_` 欄位;
    Playwright `emulateMedia({media:'print'})` 後可見的表格資料列數 = 120。
- [ ] **收貨單印出來含全部明細列**。
  - 驗證:`/receipts/<id>?print=1` 印刷檢視下可見資料列數 = 38。
- [ ] **實盤數/實收數在紙上是可以用筆填的空格**(不是被隱藏的輸入框)。
  - 驗證:印刷檢視下 `input[name^=qty_]` 的 `display` 不是 `none` 且有可見框線。
- [ ] **操作類元件一律不印**:按鈕、篩選、分頁、待辦帶、頂列、分頁列、頁尾。
  - 驗證:印刷檢視下 `.rail`、`.tabbar`、`.savebar`、`.pager`、`.filters`、
    `input[type=submit]`、`button` 的 `display` 皆為 `none`。
- [ ] **表頭在每一頁重複、資料列不被切成兩半**。
  - 驗證:`<style>` 含 `thead { display: table-header-group }` 與
    `tr { page-break-inside: avoid }`。
- [ ] **深色模式下列印仍是白底黑字**(不浪費碳粉)。
  - 驗證:`colorScheme: 'dark'` + 印刷檢視下 `body` 的背景色為白色。
- [ ] **可列印的頁面上有看得見的列印入口**,並說明會印出整張單。
  - 驗證:`/counts/<id>` 與 `/receipts/<id>` 含指向 `?print=1` 的連結。

### 料架標籤

- [ ] **標籤頁可以只印一部分**:依儲位、依分類、或單一料號。
  - 驗證:`/labels?loc=A-` 只回儲位以 A- 開頭的標籤;`?category=膠帶類` 只回該分類;
    `?sku=DS-10000` 只回一張。
- [ ] **印之前先告訴使用者會印幾張、大約幾頁**。
  - 驗證:頁面含「共 N 張標籤」與估計頁數字樣,且 N 與篩選結果一致。
- [ ] **標籤不會被分頁切成兩半**。
  - 驗證:`<style>` 內 `.label` 含 `page-break-inside: avoid`。
- [ ] **QR 內容不可以是 localhost**:在伺服器本機瀏覽時列印的標籤,手機掃了要能開。
  - 驗證:以 `Host: localhost:5000` 產生的 QR 內容不含 `localhost`,而是內網 IP
    或 `PUBLIC_BASE_URL` 設定值。
- [ ] **回歸**:第一至第十一階段全部條目維持通過;`python test_inventory.py` 全綠。

## 庫存系統第十三階段:公司內網架站(交付到能用)

> 來源:使用者 2026-09 指示「我想要你先製作成一個可以用自己網路登入的網站」,
> 並在選項中選擇「放公司自己的電腦」。與更早的指示一致:「這個系統應該要是公司的
> 內網才可以登入」。
>
> 實測確認伺服器本身已經可用:綁 `0.0.0.0`,用內網 IP(非 localhost)開首頁、
> 登入、看清單全部正常。**缺的不是功能,是交付**——把它交到一個不懂技術的人手上,
> 讓他在公司電腦上跑起來、而且同事找得到網址。

### 一個位址,不是一堆位址

- [ ] **`--lan-url` 子命令只印出一行可直接貼上的網址**,不啟動伺服器。
  - 驗證:`python inventory_app.py --lan-url` 輸出符合 `http://<IP>:<port>` 且只有一行。
- [ ] **不可以印 `0.0.0.0` 當網址**(那是綁定位址,不是可輸入的網址)。
  - 驗證:`--lan-url` 與啟動訊息的輸出都不含 `http://0.0.0.0`。
- [ ] **自動挑到真正的內網卡**:略過 Docker/VirtualBox/WSL 這類虛擬網卡位址,
      否則同事會拿到一個永遠連不上的位址。
  - 驗證:`local_ip()` 不回傳 `172.17.`~`172.31.`、`192.168.56.`、`169.254.` 開頭的位址。
- [ ] **啟動腳本把網址寫成一個檔案**,使用者可以直接把內容貼給同事。
  - 驗證:執行後產生 `同事連線網址.txt`,內容含該網址。

### 同事真的連得上

- [ ] **Windows 防火牆規則自動建立**(以系統管理員身分執行時)。
  - 驗證:`start_inventory.bat` 含 `netsh advfirewall firewall add rule`,
    且有「已是管理員 / 不是管理員」兩條分支。
- [ ] **不是管理員時,只給一個明確動作**,不是叫使用者自己去研究防火牆。
  - 驗證:非管理員分支的訊息含「對這個檔案按右鍵 →『以系統管理員身分執行』」。
- [ ] **用內網 IP(非 localhost)可以完成登入**。
  - 驗證:`curl -X POST http://<內網IP>:<port>/login` 回 302,帶 cookie 開首頁看得到庫存清單。

### 第一個帳號不能被同事搶走

- [ ] **資料庫還沒有任何帳號時,啟動訊息要明確警告**:第一個註冊的人會變成管理員,
      所以要先自己註冊完再叫同事連進來。
  - 驗證:空資料庫啟動時,輸出含「第一個註冊的人會成為管理員」。
- [ ] **已經有帳號時不再顯示該警告**(避免每天開機都看到不相干的紅字)。
  - 驗證:有使用者的資料庫啟動時,輸出不含該警告字樣。

### 交付文件

- [ ] **有一份不懂技術的人看得懂的架站說明**,涵蓋:要準備什麼、怎麼開始、
      同事怎麼連、資料放在哪、要備份什麼、關機會怎樣、IP 變了怎麼辦。
  - 驗證:`公司內網架站指南.md` 存在且包含上述七個小節。
- [ ] **說明中不出現未解釋的專有名詞**;必須出現的(例如要照打的指令)後面用一句話說明。
  - 驗證:人工檢視。

### 打包給使用者的 ZIP 必須在 Windows 上打得開

> 實際踩到:第一版用 Linux 的 `zip -r` 打包,檔名含中文。ZIP 規定非英數檔名要立起
> 「UTF-8」旗標,Info-ZIP 預設不立,Windows 就改用 Big5 解讀 UTF-8 位元組,
> 解出亂碼後 Explorer 直接跳「壓縮資料夾無效」——而同一個檔在 Linux 上
> `unzip -t` 顯示完全正常。使用者拿到的是一個完全打不開的檔案。

- [ ] **打包一律由 `make_package.py` 產生**,不手打 `zip` 指令。
  - 驗證:`python make_package.py <輸出目錄>` 產生 ZIP 並自我檢查通過。
- [ ] **壓縮檔內的所有路徑都是純 ASCII**。
  - 驗證:`python -c "import zipfile;print(all(i.filename.isascii() for i in zipfile.ZipFile('<zip>').infolist()))"` 為 True。
- [ ] **打包腳本在產出非 ASCII 路徑或損毀檔案時要中止**,不可以默默出一個壞包。
  - 驗證:`make_package.py` 含 `testzip()` 與 `isascii()` 檢查且失敗時 `sys.exit`。
- [ ] **打包後解壓縮到全新目錄仍可直接啟動**,且 `requirements.txt` 維持 UTF-16、
      `.bat` 維持 CRLF(編碼在壓縮/解壓縮往返後不可被改動)。
  - 驗證:解壓後 `file requirements.txt` 顯示 UTF-16、`file start_inventory.bat` 顯示 CRLF,
    且 `bash start_inventory.sh` 能起服務並印出內網網址。
- [ ] **回歸**:第一至第十二階段全部條目維持通過;`python test_inventory.py` 全綠。

## 使用者自訂要求(請在此新增你在意的驗收項目)

<!-- 範例格式:
- [ ] **要求標題**:一句話描述預期行為。
  - 驗證:具體的測試指令或檢查步驟。
-->
