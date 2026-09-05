# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains **two independent single-file Flask apps** (UI and comments in Traditional Chinese; neither imports the other):

1. `patrick_method_solver.py` — solves the Petrick's (Patrick) Method for minimal SOP (Sum of Products) Boolean simplification, supporting both single- and multiple-output problems.
2. `inventory_app.py` — a full inventory management system (庫存管理系統): multi-user auth with admin/staff roles, product & supplier CRUD, stock-in/out, search, low-stock alerts, transaction history, reports, CSV export/import, cross-company part-number aliases, product photos, image-similarity search (以圖搜圖, dHash), lot tracking with FIFO/FEFO, cycle counting, reservations, safety-stock derivation, ABC-XYZ analysis, and QR shelf labels. Data lives in SQLite; photos on disk.

## Commands

```bash
pip install -r requirements.txt   # Flask 3.1, Pillow (image search), waitress (server), qrcode (shelf labels)
python patrick_method_solver.py   # solver app: 0.0.0.0, port from $PORT (default 5000)
python inventory_app.py           # inventory app: 0.0.0.0, port from $PORT (default 5000, served by waitress)
python test_inventory.py          # inventory app test suite (stdlib unittest; must be green before /verify)
```

The solver app has no automated tests; `test_inventory.py` covers the inventory app. Both apps are deployed to Render (each as its own service with its own start command), which supplies the `PORT` environment variable — keep the `0.0.0.0` host binding intact.

Note: `requirements.txt` is UTF-16 encoded (saved on Windows). `pip` handles it, but naive text tools may show garbled content; preserve or normalize the encoding deliberately if you edit it.

## Verification workflow (驗收流程)

`REQUIREMENTS.md` is the single source of truth for acceptance criteria. These rules are mandatory:

- Any task that modifies code MUST run the `/verify` acceptance loop (defined in `.claude/commands/verify.md`) before being declared complete — even if the user didn't ask for verification. The loop: start the app, test every item in `REQUIREMENTS.md` with real requests, fix failures, regression-retest, repeat until all pass.
- The final report MUST include the full per-item result table. Any ❌ means the task is NOT complete; if an item still fails after 3 fix rounds, stop and report the blocker honestly instead of claiming success.
- If a new task introduces new requirements, add them to `REQUIREMENTS.md` first, then implement.
- Testing gotchas: use `curl --form-string` (not `-F`) for inputs containing `;`, and match `&#39;` for apostrophes in HTML responses. The built-in default example's F0 is mathematically unsolvable — "找不到涵蓋所有 minterm 的組合" there is correct behavior, not a bug.

## 持續迭代原則 (Continuous iteration)

一次到位是不可預期的,尤其是視覺設計。以下規則強制「持續更新」:

- **側寫是活文件**:session 中觀察到使用者新的用詞習慣、被糾正的解讀、或新偏好(含美術偏好)時,應主動提議更新本檔的側寫章節(走 PR、由使用者確認),不等使用者要求。
- **設計/UI 任務的截圖迭代義務**:凡涉及介面外觀的修改,必須跑截圖迭代循環——修改 → 以 Playwright(Chromium 位於 `/opt/pw-browsers/chromium`,勿執行 `playwright install`)截取桌面(1280px)與手機(390px)寬度截圖 → 自我審視(排版、對比、擁擠度、RWD、中文字體)→ 再修,內部至少 2 輪。
- **成品必須讓使用者看得到**:設計類任務的最終回報必須附上截圖(SendUserFile),由使用者做最終美術裁決;「程式碼寫完了」不等於「設計完成了」。
- **使用者的視覺回饋落地**:使用者對外觀的任何評語(太擠、顏色不對、字太小…)由 Claude 代寫成 REQUIREMENTS.md「介面與美術」節的可驗證條目,成為下一輪迭代的驗收標準。

## Architecture — inventory app (`inventory_app.py`)

Single file: routes, SQLite schema, and inline HTML (a shared `LAYOUT` string + per-page body fragments assembled by `render_page()`).

- **Storage**: SQLite at `inventory.db` (gitignored), path overridable via `INVENTORY_DB` env var — the `/verify` loop uses `INVENTORY_DB=/tmp/verify_inventory.db` for a clean, reproducible DB. Tables (`users`, `suppliers`, `products`, `transactions`, `part_aliases`, `product_images`) are created idempotently by `init_db()` at startup. Product photos live under `inventory_images/` (gitignored, overridable via `INVENTORY_IMAGES`). Connections run in **WAL mode with a 15s busy timeout** — without WAL, one slow read (e.g. the history page) made concurrent stock-in requests fail with `database is locked` 500s and silently lose the transaction. `backup_db()` snapshots the DB via the sqlite3 backup API (safe under WAL) into `backups/` at startup and every 24h, keeping the newest 14; set `BACKUP_DIR` to also copy each snapshot to a shared drive/NAS. Current stock is stored in `products.quantity` and updated in the same SQL transaction as the `transactions` insert; stock-out uses an atomic `UPDATE ... WHERE quantity >= ?` so stock can never go negative.
- **Auth & permissions**: session-based; passwords hashed with `werkzeug.security` (min 8 chars; 5 failed logins lock an account for 5 minutes, tracked in-process). `SECRET_KEY` comes from the env var, else `load_secret_key()` generates and persists a random key in `secret_key.txt` next to the DB (mode 0600) — there is deliberately **no hardcoded fallback**, since a predictable key lets anyone forge a session offline. Only the *first* user may self-register (becomes admin); afterwards `/register` is closed and accounts are created by an admin at `/users`. `@admin_required` gates the destructive routes (product/supplier/photo/alias delete, `/import`, `/users`, `/audit`) and the templates hide those controls for non-admins; `@login_required` covers everything else. `/logout` is GET and there is no CSRF token — a deliberate simplification for curl testability, documented in code comments.
- **Flow convention**: successful POSTs redirect (302, PRG pattern); validation failures re-render the same page with HTTP 200 and an inline error message (so curl can grep for it). No JavaScript dependency anywhere. Stock-in/out redirect back to their own form with a success message for rapid consecutive entry.
- **Part-number aliases (跨公司料號)**: `part_aliases` maps other companies' part numbers to our products (`UNIQUE(company, alias_sku)`); the home-page search matches our SKU, name, AND alias SKU/company, so any company's part number finds the same product.
- **Lot tracking + FIFO (批次管理)**: every stock-in creates a `lots` row (auto lot number `L<date>-<txid>` or user-supplied, optional `unit_cost`, `UNIQUE(product_id, lot_no)`); stock-out consumes lots oldest-first (FIFO, `ORDER BY received_at, id`) and records per-lot consumption in `lot_consumptions` for traceability (shown in history/export as `批號×qty`). Invariant: `SUM(lots.qty_remaining) == products.quantity`, maintained in the same SQL transaction; `reconcile_lots()` at startup backfills 期初批 (`INIT-<pid>`) for legacy data, and stock-out defensively creates an `ADJ-<txid>` lot if a gap is ever found. CSV import creates `IMP-<txid>` lots for initial stock. The report page adds weighted-average cost (存貨計價, remaining lots with cost only), inventory aging buckets (庫齡 0-30/31-60/61-90/90+), and ABC analysis (cumulative value ≤80% A / ≤95% B / else C).
- **Image similarity search (以圖搜圖)**: photos get a 64-bit dHash (`compute_dhash`, Pillow) stored in `product_images.phash`; `/search/image` ranks all photos by Hamming distance, top-10 with similarity %. Pillow missing → app still boots, feature politely disabled (`HAS_PIL`). Pillow is the only dependency beyond Flask (added to the UTF-16 `requirements.txt` — always edit that file via bytes→decode('utf-16')→re-encode to preserve BOM).
- **Multi-format import**: `read_table_file()` handles Excel (`.xlsx`/`.xlsm` via openpyxl, optional dependency `HAS_OPENPYXL`), CSV, and Tab-separated files (delimiter sniffed from extension or first line). `cell_to_text()` turns Excel floats (`100.0`) back into clean integer strings and dates into `YYYY-MM-DD` — without that layer, a numeric quantity cell fails the whole batch. Legacy `.xls` returns a friendly "save as .xlsx" message instead of a 500.
- **One-shot setup (`setup_all.bat` + CLI subcommands)**: `python inventory_app.py --setup-admin <user> <pass>` and `--import <file>` run without starting the server, so the batch file completes 轉檔 → 建管理員 → 匯入 → 啟動 in a single double-click; the browser is only used to *look* at the result, never to upload. Both subcommands run inside `app.test_request_context()` and reuse `import_products_rows()` so there is one import code path, not two. Guards: `--import` refuses when no admin exists or the file is missing, re-running skips existing SKUs, and `setup_all.bat` refuses to run at all when `inventory.db` already exists (it is a fresh-install tool, never an overwrite tool).
- **One-click migration (`migrate_data.bat`)**: Windows users never open a terminal — the batch file finds the `.xlsx` in its own folder (asking which one if there are several), installs openpyxl if missing, runs the converter, and opens the output folder. Same CRLF + `py -3` + explicit-failure-branch conventions as `start_inventory.bat`.
- **No price data in the source ledger**: every migrated product lands with `unit_price = 0`, so **ABC analysis is meaningless on freshly migrated data** and "count the A items first" is not actionable advice. The first cycle count is prioritised by what the data does support — flagged anomalies (negative/text balances) first, then transaction frequency (the industry's frequency-based cycle counting), then quantity on hand.
- **Legacy migration (`migrate_bl_excel.py`)**: converts the company's existing Excel ledger (one row per movement, 13 years, ~7.6k rows) into the system's import format. Groups by 得盛料號, falling back to 品名規格 when a part number was never assigned (about half the materials) — those get an auto `TMP-xxxxx` number so nothing is dropped. Current stock is the **last non-empty running-balance cell**, since only the closing balance migrates (history stays in the original file, which keeps the lot ledger clean). Per-material fields (櫃位/廠商/品名/Type) take the most recent value and any conflict is written to `migration_report.csv` rather than silently resolved. Two traps handled: the 櫃位 column doubles as a status field (`無庫存`/`無在庫`/`無` are not locations, but `桌上`/`防潮箱N層`/`Joyce保管` are), and balances are sometimes text (`10米`, `1捲`) — the leading number is extracted and flagged. Negative balances import as 0 with a flag, because the system forbids negative stock by design.
- **Purchase orders (`/orders`)**: the PO carries the same line items forward through `已下訂 → 已出貨 → 已到貨待驗 → 已入庫結案`, so **one set of lines is registered once, not four times**. `order_arrive()` is the automation hinge: it turns the PO's outstanding lines into a receipt (quantities, matched product ids, unit costs all carried over) and hands the user straight to it — the warehouse only confirms counts. Partial deliveries are first-class: arriving again is allowed whenever outstanding lines remain, but **refused while an `open` receipt still exists for that PO** (two pending receipts would let the same goods be posted twice), and each batch gets its own `-到貨第N批` ref. `writeback_po_receipt()` runs inside `receipt_post`'s transaction, allocating posted quantities back to PO lines oldest-first and closing the PO only when nothing is outstanding. **On-order (在途) = Σ(ordered − received) over `ordered/shipped/arrived` POs** — surfaced as a home-page band, a column in the product list, and a section on the product page, so nobody re-orders what is already on the way. Cancelled and closed POs drop out of 在途 by definition.
- **Goods receipt / ASN (`/receipts`)**: the supplier's delivery file enters the system as a pending document; **stock is completely untouched until release** — that is the whole point versus a direct stock-in. `match_part()` resolves each line: our SKU → cross-company alias (`part_aliases`) → product name; unresolved lines are flagged `none` and kept for a human to map. Manual mapping offers "remember this mapping", which writes a `part_aliases` row so the same supplier's part number auto-matches next time. Release (`receipt_post`) is what creates the `in` transactions and lots (lot no./expiry/cost carried from the file, else `R<receipt>-<txid>`), and it refuses to run while any unmatched line has a received quantity — goods arriving with no ledger entry is the most common origin of inventory drift. Status is `open`/`posted`/`cancelled`, posting is idempotent-guarded, and cancelling is admin-only (create/check/release keep the same permission level as ordinary stock-in).
- **CSV import** (`/import`): products (initial stock recorded as an `in` transaction with note `CSV匯入`, suppliers auto-created) and aliases; encodings tried in order utf-8-sig → cp950 (Taiwanese Excel Big5); per-row success/skip report with line numbers.
- **Intranet restriction**: `ALLOWED_IPS` env var (comma-separated) enables an IP allowlist in `before_request` — non-listed sources get 403. The client IP is `request.remote_addr` **by default**; `X-Forwarded-For` is only consulted when `TRUST_PROXY` is explicitly enabled (and then the *last* hop is used). This matters: on a direct-connect deployment, trusting XFF let anyone bypass the allowlist with a single forged header. Unset `ALLOWED_IPS` = off, which is correct for true intranet deployment where the network itself is the boundary.
- **Auditing & time**: every product/supplier/alias/photo mutation, CSV import, and account action writes to `audit_log` via `audit()` (committed by the caller's transaction); admins review it at `/audit`. A lot-ledger gap would also be recorded there rather than silently absorbed. Timestamps are **stored in UTC and displayed in Taiwan time** (`fmt_local`); date filters convert the user's local dates to a UTC range via `local_date_to_utc_range()` so filtering doesn't skew by 8 hours.
- **Robustness**: numeric inputs are bounded by `MAX_QUANTITY` and go through `safe_int()`/`math.isfinite()` (`str.isdigit()` is true for characters like `²` that `int()` rejects — that combination used to 500); CSV import catches `OverflowError` alongside `ValueError` so one bad cell skips its row instead of destroying the whole batch; uploads are capped at 10MB (`MAX_CONTENT_LENGTH`) with a friendly 413 page; CSV export escapes leading `= + - @` to prevent spreadsheet formula injection. The home page and history are paginated (100 / 200 per page); export endpoints pass `limit=None` for complete data.
- **CSV export**: UTF-8 with BOM prefix (`\ufeff`) so Excel on Windows renders Chinese correctly.
- **Cycle counting (循環盤點)**: `stock_counts` + `stock_count_items`; a count sheet snapshots `system_qty` at creation (scope = all / ABC class / category). Any logged-in user can record counted quantities; only an admin can **post**, which compares against the *current* quantity (not the snapshot, so concurrent movements aren't clobbered), writes a `盤點調整` transaction, and keeps the lot ledger balanced — shortages go through `consume_lots()`, overages create a `CNT<id>-<txid>` adjustment lot. Posting stores the accuracy (matched ÷ counted) surfaced on the report as the 庫存準確率 KPI (industry benchmark 95–99%). Posting is idempotent-guarded (`status='posted'` refuses a second post).
- **Reservations & available qty**: `reservations` holds soft allocations; **available = quantity − active reservations**. On-hand is unaffected by reserving. Low-stock alerts and the home-page banner both judge on *available*, matching the industry on-hand/available split. Reserving more than available is refused.
- **Safety-stock derivation (`/planning`)**: `usage_stats()` builds a per-day usage series over `USAGE_WINDOW_DAYS` (90) from outbound transactions — days with no issue count as 0, otherwise the mean is badly overstated. `suggest_safety_stock()` applies `SS = Z × σ_d × √L` (demand-variability form; lead-time variability is unknown here) with Z from the product's `service_level` via `Z_TABLE`, plus `ROP = mean × L + SS`. Admins can apply all suggestions to `low_stock_threshold` in one action. `xyz_class()` grades demand variability by coefficient of variation (X <0.5, Y <1.0, else Z); the report shows the ABC-XYZ combination.
- **UoM, location, purpose, expiry**: products carry `location` (searchable alongside SKU/name/alias), `purchase_unit` + `units_per_purchase` (stock-in accepts `qty_unit=purchase` and converts, so nobody does mental arithmetic), `lead_time_days`, `service_level`, and `issue_strategy` (FIFO or **FEFO** — `consume_lots()` orders by `expiry_date` when FEFO, empty expiry last). Lots carry `expiry_date`; `/alerts` lists lots expiring within 30 days or already expired. Transactions carry a structured `purpose` (work order / department), filterable on `/history` and included in the CSV export.
- **QR shelf labels**: `/products/<id>/qr.png` renders a QR of the product page's absolute URL; `/labels` is a print-oriented sheet (QR + SKU + name + location) filterable by `loc` (storage-location prefix), `category`, or a single `sku`, and it states the label count and estimated A4 page count *before* you print — printing all 2,279 items is ~98 pages, so "reprint one cabinet" must not mean "reprint the plant". `qrcode` degrades gracefully like Pillow (`HAS_QRCODE`). The QR's host comes from `public_base_url()`, **not** `_external=True`: the admin prints from the server machine's own browser at `http://localhost:5000` (that's what `start_inventory.bat` opens), and `localhost` on a phone means the phone — every label would be dead. Localhost/127.0.0.1 is rewritten to the detected LAN IP; `PUBLIC_BASE_URL` overrides.
- **Mobile navigation (`.tabbar`)**: desktop `nav` is `position: sticky`, but ≤760px used to override it to `static` — measured on `/history` (54,999px tall on a phone) the nav sat at −1,952px after one flick, so the device that most needs persistent navigation was the one without it. At ≤760px `nav` is hidden and a fixed bottom toolbar takes over: 總覽 / 入庫 / 出庫 / 收貨 plus a zero-JS `<details>` "更多" panel that must contain **every** page the nav had (a toolbar that loses functionality is a regression, and the phase-12 checks assert each route is reachable from it). Two traps: `.tabbar` is itself a `<nav>`, so it inherits `top: 48px` and a `fixed` element with both `top` and `bottom` stretches to full height (`top: auto` fixes it), and `body` needs `padding-bottom` or the bar covers the footer and last row. `env(safe-area-inset-bottom)` keeps it clear of the iPhone gesture bar.
- **Printing is for documents, not screens**: the print stylesheet used to carry `form { display: none !important; }`, and the count sheet and goods receipt put their entire line-item table inside a `<form>` — measured, `/counts/<id>` printed as **1 page with 290 characters and zero rows**. A warehouse worker printed a count sheet and walked out holding a page with no parts on it. The rule now hides *controls* (buttons, `.filters`, `.savebar`, `.pager`, `.rail`, `.tabbar`) and keeps the document, with number/text inputs styled as bordered boxes so the quantity columns print as blanks to fill in by pen. `?print=1` on `/counts/<id>` bypasses the 50-row pagination (half a count sheet is useless), print colours are forced to `#fff`/`#000` so dark mode doesn't print a black page, `thead` repeats per page, and `table.cards` is forced back to a real table so printing from a phone doesn't emit a stack of cards.
- **Touch targets**: at ≤760px every control is ≥44px (WCAG 2.5.5). Before this, the count/receipt quantity inputs were 20px, the product page's 入庫/出庫 links 17px (`.action-links` had no CSS at all — a leftover from removing the home-page action tiles) and the topbar logout 15px. Plain text links have no padding of their own, so table/panel-header links get `display: inline-flex; min-height: 44px` explicitly.
- **Version visibility (`APP_VERSION`)**: shown in every page footer and on the first line of the startup log. This exists because the system updates by "download ZIP and overwrite" — a user ran an older ZIP, saw 「成功匯入 2279 筆」 and assumed it worked, but that build's importer read only 8 columns and **silently dropped the 儲位 column** for all 2,279 items. Without a visible version there was no way to notice. Bump `APP_VERSION` on每次發版.
- **Startup URL messaging**: the console prints `http://localhost:<port>` plus an auto-detected LAN address for colleagues, and explicitly says `0.0.0.0` is not a browsable address. It used to print `服務位址:http://0.0.0.0:5000`, which a user typed into a browser verbatim and got `ERR_ADDRESS_INVALID` — the bind address is not a URL. `start_inventory.bat` also opens the browser automatically 3 seconds after launch. The `host="0.0.0.0"` bind itself is unchanged; only the message did.
- **Deployment**: served by **waitress** (production-grade, pure Python, Windows-friendly), falling back to `app.run` if waitress is missing; the `host="0.0.0.0"` + `$PORT` contract is unchanged. Two supported routes: (A) Company intranet machine — run `start_inventory.bat` (Windows) / `start_inventory.sh` (Mac/Linux); data, photos and backups persist on that machine; colleagues browse `http://<internal-ip>:5000`. (B) Render second service (start command `python inventory_app.py`) + `ALLOWED_IPS` set to the company's fixed public IP; note Render free tier disk is ephemeral — `inventory.db` AND photos are wiped on every redeploy/restart (attach a Render Disk for persistence). **The user chose route A** (2026-09), consistent with their standing 「這個系統應該要是公司的內網才可以登入」 — the LAN itself is the access boundary, so `ALLOWED_IPS` stays unset.
- **Handover for route A**: the server was already reachable over the LAN; what was missing was getting a non-technical person from a folder to a working site. `--lan-url` prints exactly one pasteable URL and exits (no server), and both launchers write it to `同事連線網址.txt` for forwarding — the old scripts dumped raw `ipconfig`/`ip addr` output, and a PC with Docker or VirtualBox installed lists four or five addresses with no way to tell which one works. `local_ip()` now probes several gateways and rejects virtual-adapter ranges (`VIRTUAL_IP_PREFIXES`: Docker `172.17–31.`, VirtualBox `192.168.56.`, link-local `169.254.`). `start_inventory.bat` adds the Windows firewall rule itself when run elevated (`net session` detects it) — a blocked inbound port is the single most common reason colleagues "can't connect" — and when not elevated gives exactly one instruction instead of sending the user to research firewall settings. `公司內網架站指南.md` is the plain-language guide (no jargon, per the user profile).
- **Packaging (`make_package.py`)**: the ZIP handed to the user is built by this script, never by a hand-typed `zip -r`. ZIP requires the UTF-8 flag (general purpose bit 11) on non-ASCII entry names; Info-ZIP on Linux does not set it, so Windows decodes the UTF-8 bytes as Big5, gets mojibake, and Explorer refuses the whole archive with 「壓縮資料夾無效」 — while `unzip -t` on Linux reports it perfectly healthy. The first delivered package (2026-09) was completely unopenable on Windows 11 for exactly this reason. The script uses Python `zipfile` *and* forces every in-archive path to plain ASCII (`公司內網架站指南.md` → `setup-guide.md`), so correctness never depends on the flag being honoured; it aborts rather than emit a bad archive if `testzip()` fails or any path is non-ASCII. Chinese filenames are fine for files Windows itself creates at runtime (`同事連線網址.txt`) — those never pass through a ZIP.
- **First account is a land grab**: on a fresh DB `/register` is open and the first registrant becomes admin. On an intranet that means *whoever opens the page first*, which may not be the person who set it up. Startup now prints a boxed warning while `has_any_user()` is false, telling the operator to register before handing out the URL; the warning disappears once an account exists so it doesn't become daily noise.

## Architecture — solver app (`patrick_method_solver.py`)

Everything is in `patrick_method_solver.py`:

- **Web layer**: one route (`/`, GET+POST) rendering `HTML_PAGE` via `render_template_string`. Input arrives either from two form textareas or an uploaded `.txt` file (line 1 = prime implicants, line 2 = minterms).
- **Input format**: multiple outputs are separated by `;`, terms/minterms within one output by `,`. Example: PIs `A'B, AB; A'C` with minterms `1,3; 2,6` describes two functions F0 and F1. `parse_input` zips the PI groups with the minterm groups positionally.
- **Solver pipeline** for each output: `build_prime_chart` (maps each minterm to the PIs covering it) → `find_min_sop` (brute-force search over PI combinations of increasing size, returning the first combination that covers all minterms — guaranteeing minimal cardinality).
- **Boolean-term evaluation**: `get_covered_minterms` enumerates all assignments over a fixed variable order `A, B, C, D` (the app supports at most four variables) and tests each against the PI expression via `match_pi`/`split_literals`. Complemented literals are written with a trailing apostrophe (e.g. `A'B`), and a PI expression may itself contain `+`-separated parts.

Constraints baked into the code: 4 variables max, minterm indices derived from the binary assignment of `A..D` (A is the most significant bit), and minterms that aren't plain digits are silently dropped during parsing.

## 使用者溝通側寫 (User communication profile)

本節來自對使用者實際對話的逐字稿分析(用詞風格、逐回合命中率稽核、規則提煉、批判檢查),供每個 session 開場即理解使用者。使用者自認不擅長下提示詞,期望 Claude 主動轉譯其口語需求,而非要求他寫得精確。

**語言**:全程以繁體中文回覆(程式碼、指令、檔名、commit 訊息除外)。

**解讀規則**:
- 「我在思考要如何X」「我先統整一下…」「可以用X去…」= 正式行動請求,直接受理執行,不是閒聊或徵詢可行性。
- 訊息常為逗號連寫的長句,結構是「背景→歸因→目的→請求」;真正的請求常埋在句子中段,句尾「目的是為了…」子句是不可妥協的驗收標準——方法可以換,目的不能丟。
- 同音別字照讀音還原(不段=不斷、所以有=所有、有訂=有定),不糾正、不因字面歧義反問。疑問句常無問號、祈使句常無「請」,皆為正常請求。
- 抱怨句中的「他」指過往 session 的 Claude;「上個對話」= 同視窗上一輪;「其他聊天視窗」= 跨 session 記錄(實際不可讀取)。
- 「潦草解決/潦草結束」= 在抱怨「宣稱完成但要求沒達成」,解方永遠是附證據的逐項驗收。

**回報格式**:先講結果再講細節;完成宣稱必須附逐項證據表(見 Verification workflow);過程要可追溯(分支、commit hash)——使用者會在數輪後回頭追問「上次執行了什麼」。

**設計是預設值,不是選配**(2026-08 使用者糾正):使用者說「所有設計都很陽春,按鈕的部分也是,明明之前都有儲存很多不錯的設計為何都不會主動使用,都還要我特別說明」。**任何動到介面的修改都算設計任務**,必須自己跑截圖迭代並附圖,不等使用者交代。REQUIREMENTS 的視覺條目是及格線不是目標——打勾不代表好看。具體禁區:不用 emoji 當功能圖示(一律內嵌線條 SVG)、按鈕要有 hover/active/focus-visible 三態與實體感、陰影要色票化且帶版面色溫、資料表列高不可被操作欄撐爆。

**美術偏好**(2026-08 使用者實證回饋):功能入口要「精簡」——相關功能整合成群組,不要一長排並列(庫存 app 導覽已分為 總覽/庫存作業/商品資料/分析報表/系統管理 五項,零 JS 的 details 選單);視覺要「大膽」,忌死板——現行識別:深藏青 + 琥珀主色(CSS 變數 `--ink`/`--accent`)、深色表頭、KPI 色塊。介面改動一律跑截圖迭代並附圖裁決。

**譬喻政策**:git/GitHub/部署概念用生活譬喻解釋(已建立且有效:PR=簽核單、main=正式菜單、merge=簽核通過),需要使用者操作時給「你只要做一件事」的單一步驟。但布林邏輯領域術語(minterm、SOP、PI)不需譬喻——使用者熟悉此領域,過度譬喻反而是噪音。**譬喻必須一句話講完**(2026-08 使用者糾正:「用很長的篇幅用故事去舉例,我覺得就很多餘了」)——長篇故事式舉例是噪音,不是體貼。

**外行人門檻**(2026-08 使用者明確要求):使用者自述「我不是這個領域的專家」,並指出回覆與提問「都還是太過困難」。回覆一律以**非該領域的一般人看得懂**為標準,不要用專有名詞;真的非用不可(例如那是他必須照打的指令)才用,並在後面用一句話說明它是什麼。這條適用於所有回覆,不是只有開了 ELI5 輸出風格才生效——風格檔是加強,不是前提。注意:安裝工具 ≠ 工具生效,凡是需要使用者自己切換才會啟用的東西,必須明講「你要打這一行它才會動」。

**決策協助的正確形狀**(2026-08 使用者原話):「你叫我做決定需要的是依照我的意願去權衡利弊做取捨,所以重點在這裡,我要搞清楚利害關係以及可能的問題」。因此每個選項必須給滿三樣:**選了會得到什麼、不選會失去或維持什麼、可能有什麼後遺症(能不能反悔、反悔的代價)**。最多兩個選項;可以說出偏好但要附理由,且要讓使用者看得出來選另一個也合理。**不要問技術細節**——要問就問「你比較在意 A 還是 B」這種他答得出來的問題。決定權在使用者,Claude 的工作是把利害攤平,不是代為拍板。

**不留功課**:不要請使用者自行撰寫規格或驗收條目(實證:多次建議自行填寫 REQUIREMENTS.md 皆未執行)。改為從其敘述中主動萃取需求、代寫成可驗證條目、再向其確認。

**控制權**:不可逆動作(開 PR、merge、刪除)先告知選項、由使用者最終確認;回覆結尾提供可照抄的一句話指令(如「幫我盯 PR #2」),使用者會逐字採用。

**優先序**:要求確實達成 > 實測證據 > 省使用者時間 > 誠實透明 > 省用量。絕不因省用量或省輪次而壓縮品質或提早收尾——使用者明確表示寧可多耗用量。

**期望管理**:使用者預期 Claude 有跨視窗的連續記憶。新 session 應主動說明「對你的理解來自本檔案的側寫」,不假裝記得未記錄的事;如需更深入的長期理解,請使用者匯出過往對話上傳後再分析。

## Agent skills

本 repo 安裝了 [mattpocock/skills](https://github.com/mattpocock/skills) 的 engineering / productivity 系列(共 26 支,清單見 `.claude/skills/README.md`),下列設定供這些 skill 讀取。

### Issue tracker

Issue 與 spec 放在 GitHub Issues(`liuaaron0226/patrick_webapp`);雲端 session 沒有 `gh` CLI,改用 GitHub MCP 工具。見 `docs/agents/issue-tracker.md`。

### Triage labels

採用五個標準角色的預設標籤字串(`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`)。見 `docs/agents/triage-labels.md`。

### Domain docs

單一 context:根目錄一份 `CONTEXT.md` 定義統一語彙,ADR 放 `docs/adr/`。`CONTEXT.md` 只講「是什麼」,本檔講「怎麼做、為什麼」。見 `docs/agents/domain.md`。

### 輸出風格

`.claude/output-styles/` 另有 ELI5 風格(`/output-style eli5-zh` 切換),說明見該目錄的 README。
