# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains **two independent single-file Flask apps** (UI and comments in Traditional Chinese; neither imports the other):

1. `patrick_method_solver.py` — solves the Petrick's (Patrick) Method for minimal SOP (Sum of Products) Boolean simplification, supporting both single- and multiple-output problems.
2. `inventory_app.py` — a full inventory management system (庫存管理系統): multi-user auth, product & supplier CRUD, stock-in/out, search, low-stock alerts, transaction history, reports, CSV export/import, cross-company part-number aliases, product photos, and image-similarity search (以圖搜圖, dHash). Data lives in SQLite; photos on disk.

## Commands

```bash
pip install -r requirements.txt   # Flask 3.1 and its dependencies (covers both apps; no extra deps)
python patrick_method_solver.py   # solver app: 0.0.0.0, port from $PORT (default 5000)
python inventory_app.py           # inventory app: 0.0.0.0, port from $PORT (default 5000)
```

There are no tests, linters, or build steps in this repository. Both apps are deployed to Render (each as its own service with its own start command), which supplies the `PORT` environment variable — keep the `0.0.0.0` host binding intact.

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

- **Storage**: SQLite at `inventory.db` (gitignored), path overridable via `INVENTORY_DB` env var — the `/verify` loop uses `INVENTORY_DB=/tmp/verify_inventory.db` for a clean, reproducible DB. Tables (`users`, `suppliers`, `products`, `transactions`, `part_aliases`, `product_images`) are created idempotently by `init_db()` at startup. Product photos live under `inventory_images/` (gitignored, overridable via `INVENTORY_IMAGES`). Current stock is stored in `products.quantity` and updated in the same SQL transaction as the `transactions` insert; stock-out uses an atomic `UPDATE ... WHERE quantity >= ?` so stock can never go negative.
- **Auth**: session-based; passwords hashed with `werkzeug.security`. The first registered user becomes admin (`is_admin=1`). `SECRET_KEY` env var should be set in production (dev fallback exists). `/logout` is GET and there is no CSRF token — a deliberate simplification for curl testability, documented in code comments.
- **Flow convention**: successful POSTs redirect (302, PRG pattern); validation failures re-render the same page with HTTP 200 and an inline error message (so curl can grep for it). No JavaScript dependency anywhere. Stock-in/out redirect back to their own form with a success message for rapid consecutive entry.
- **Part-number aliases (跨公司料號)**: `part_aliases` maps other companies' part numbers to our products (`UNIQUE(company, alias_sku)`); the home-page search matches our SKU, name, AND alias SKU/company, so any company's part number finds the same product.
- **Lot tracking + FIFO (批次管理)**: every stock-in creates a `lots` row (auto lot number `L<date>-<txid>` or user-supplied, optional `unit_cost`, `UNIQUE(product_id, lot_no)`); stock-out consumes lots oldest-first (FIFO, `ORDER BY received_at, id`) and records per-lot consumption in `lot_consumptions` for traceability (shown in history/export as `批號×qty`). Invariant: `SUM(lots.qty_remaining) == products.quantity`, maintained in the same SQL transaction; `reconcile_lots()` at startup backfills 期初批 (`INIT-<pid>`) for legacy data, and stock-out defensively creates an `ADJ-<txid>` lot if a gap is ever found. CSV import creates `IMP-<txid>` lots for initial stock. The report page adds weighted-average cost (存貨計價, remaining lots with cost only), inventory aging buckets (庫齡 0-30/31-60/61-90/90+), and ABC analysis (cumulative value ≤80% A / ≤95% B / else C).
- **Image similarity search (以圖搜圖)**: photos get a 64-bit dHash (`compute_dhash`, Pillow) stored in `product_images.phash`; `/search/image` ranks all photos by Hamming distance, top-10 with similarity %. Pillow missing → app still boots, feature politely disabled (`HAS_PIL`). Pillow is the only dependency beyond Flask (added to the UTF-16 `requirements.txt` — always edit that file via bytes→decode('utf-16')→re-encode to preserve BOM).
- **CSV import** (`/import`): products (initial stock recorded as an `in` transaction with note `CSV匯入`, suppliers auto-created) and aliases; encodings tried in order utf-8-sig → cp950 (Taiwanese Excel Big5); per-row success/skip report with line numbers.
- **Intranet restriction**: `ALLOWED_IPS` env var (comma-separated) enables an IP allowlist in `before_request` — non-listed sources get 403 (client IP = first `X-Forwarded-For` value; designed for the cloud-behind-proxy scenario; unset = off, which is correct for true intranet deployment where the network itself is the boundary).
- **CSV export**: UTF-8 with BOM prefix (`\ufeff`) so Excel on Windows renders Chinese correctly.
- **Deployment**: two supported routes. (A) Company intranet machine — run `start_inventory.bat` (Windows) / `start_inventory.sh` (Mac/Linux); data and photos persist on that machine; colleagues browse `http://<internal-ip>:5000`. (B) Render second service (start command `python inventory_app.py`) + `ALLOWED_IPS` set to the company's fixed public IP; note Render free tier disk is ephemeral — `inventory.db` AND photos are wiped on every redeploy/restart (attach a Render Disk for persistence).

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

**譬喻政策**:git/GitHub/部署概念用生活譬喻解釋(已建立且有效:PR=簽核單、main=正式菜單、merge=簽核通過),需要使用者操作時給「你只要做一件事」的單一步驟。但布林邏輯領域術語(minterm、SOP、PI)不需譬喻——使用者熟悉此領域,過度譬喻反而是噪音。

**不留功課**:不要請使用者自行撰寫規格或驗收條目(實證:多次建議自行填寫 REQUIREMENTS.md 皆未執行)。改為從其敘述中主動萃取需求、代寫成可驗證條目、再向其確認。

**控制權**:不可逆動作(開 PR、merge、刪除)先告知選項、由使用者最終確認;回覆結尾提供可照抄的一句話指令(如「幫我盯 PR #2」),使用者會逐字採用。

**優先序**:要求確實達成 > 實測證據 > 省使用者時間 > 誠實透明 > 省用量。絕不因省用量或省輪次而壓縮品質或提早收尾——使用者明確表示寧可多耗用量。

**期望管理**:使用者預期 Claude 有跨視窗的連續記憶。新 session 應主動說明「對你的理解來自本檔案的側寫」,不假裝記得未記錄的事;如需更深入的長期理解,請使用者匯出過往對話上傳後再分析。
