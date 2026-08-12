# Issue tracker:GitHub

本 repo 的 issue 與 spec 都放在 GitHub Issues:`liuaaron0226/patrick_webapp`。

## 用哪個工具

**看環境而定,兩條路擇一:**

- **本機 Claude Code**:若已安裝 `gh` CLI,依下方慣例操作。
- **Claude Code on the web / 雲端 session**:**沒有 `gh` CLI**,改用 GitHub MCP 工具(`mcp__github__*`,以 ToolSearch 載入)。`issue_write` 建立/更新、`issue_read` 讀取、`list_issues` 列表、`add_issue_comment` 留言。

先確認手上有哪一種再動作,不要假設 `gh` 存在。

## 慣例(`gh` CLI)

- **建立**:`gh issue create --title "..." --body "..."`,多行內容用 heredoc。
- **讀取**:`gh issue view <number> --comments`
- **列表**:`gh issue list --state open --json number,title,body,labels,comments`
- **留言**:`gh issue comment <number> --body "..."`
- **標籤**:`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **關閉**:`gh issue close <number> --comment "..."`

repo 由 `git remote -v` 推得,在 clone 內執行時 `gh` 會自動判斷。

## Pull request 是否納入 triage

**PRs as a request surface: no.**(若本 repo 要把外部 PR 當成需求來源,改成 `yes`;`/triage` 會讀這個旗標。)

設為 `yes` 時,PR 走與 issue 相同的標籤與狀態機,指令換成 `gh pr view` / `gh pr diff` / `gh pr comment` / `gh pr edit` / `gh pr close`。GitHub 的 issue 與 PR 共用同一組編號,`#42` 兩者皆有可能,先試 `gh pr view 42` 再退回 `gh issue view 42`。

## 當 skill 說「發布到 issue tracker」

建立一則 GitHub issue。

## 當 skill 說「取得對應的 ticket」

`gh issue view <number> --comments`(或 MCP 的 `issue_read`)。

## Wayfinding

供 `/wayfinder` 使用。**地圖**是一則 issue,**子票**是它的 sub-issue。

- **地圖**:貼 `wayfinder:map` 標籤的 issue,內含 Notes / Decisions-so-far / Fog。
- **子票**:以 GitHub sub-issue 連到地圖;若未啟用 sub-issue,改在地圖內文放 task list,並在子票開頭寫 `Part of #<map>`。標籤 `wayfinder:<type>`(`research`/`prototype`/`grilling`/`task`)。
- **阻擋關係**:優先用 GitHub 原生 issue dependencies;不可用時退回在子票開頭寫 `Blocked by: #<n>`。所有阻擋者關閉才算解除。
- **取用**:`gh issue edit <n> --add-assignee @me`。
- **結案**:留言寫下答案 → 關閉 → 把結論指標附回地圖的 Decisions-so-far。

## 本 repo 的額外規則

開 PR 前必須確認 `REQUIREMENTS.md` 的驗收流程(見 `CLAUDE.md`「Verification workflow」);動到程式碼的 issue,關閉前要附逐項驗收結果表。
